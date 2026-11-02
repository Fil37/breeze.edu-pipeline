"""
INPUT:  instance/{channel_id}/script.json (from agent003) + settings.render_backend_by_channel
        Each script scene: scene_id, narration_text, duration_sec, key_visual_moment
        (also accepted under the names narration, duration_seconds, visual_intent).
OUTPUT: instance/{channel_id}/storyboard.json = {scenes:[{scene_id, renderer, visual_brief,
        aspect_ratio, transition_in, transition_out}]}
        visual_brief = one SceneVisualBrief (models/visual_brief_schema.py): components with
        positions, wires between named ports, timed actions, text overlay.
NOTES:  The LLM decomposes each narration into concrete components, how they are wired and what
        happens to them. Its answer is parsed as list[SceneVisualBrief] (Pydantic), sanitized, then
        checked by validate_storyboard_topology(): known ids, real ports, known actions (a
        "measure" touches two real pins), times inside the scene, at most MAX_ENTITIES entities
        and MAX_FORMULAS formulas per scene. The prompt asks for dense
        scenes: instruments instead of floating numbers, 5 to 8 actions per 8 s of narration. On failure the errors are sent back and the LLM tries again
        (MAX_ATTEMPTS in total). Never renders anything. Never changes the narration.
        After a QA reject, the orchestrator passes the QA's feedback in LBREEZE_QA_FEEDBACK (JSON:
        rejection_notes, blocking_issues, revision): it becomes a "Corrections demandées par le QA"
        section of the prompt. This agent never reads qa.json.
        Coherence with the narration (coherence_problems, sent back to the LLM for a retry, but
        advisory: after MAX_ATTEMPTS the best answer is kept with what is left):
          - word sync: every action has a "cue", words of the narration it happens on; tension /
            volts need a "measure", courant / débit a "start_flow", opening words an open switch;
          - one theme per scene: never an analogy (water tank, pipe) with a circuit, an analogy
            stays on screen to the end, a circuit is closed unless the narration says it is open;
          - labels match their target: an annotation at a formula of U names U / tension, never I.
        Repairs before saving (listed in "sync_fixes"): each "at" recomputed from where its cue
        falls in the narration (agent010 then times it on the spoken word itself), a flow stops
        when its switch opens, ammeters are highlighted when the current starts, target first:
        an ARROW_ANNOTATION never spawns before the entity it points at, and travellers: two bodies
        moving along one curve close to each other (a station and its astronaut, which the LLM
        tends to space out however it is told) become a body and its passenger.
HEALTH: not_healthy if the answer only validated after a retry, a battery's circuit is not
        closed (positive does not lead back to negative), or coherence / layout problems are left
        after MAX_ATTEMPTS (listed in "coherence_left" and "layout_templates": advisory, never
        blocking: agent005's QA judges the result);
        critical if script.json is missing, the renderer is unknown, llm_call fails,
        or no answer passes the schema and topology checks after MAX_ATTEMPTS.
"""

import copy
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

import numpy as np
from pydantic import TypeAdapter, ValidationError

from app.agent import channel_dir, find_route, finish, llm_call, load_json, parse_llm_json, run_standalone, save_json
from app import provenance
from app.qa_feedback import QA_FEEDBACK_ENV, feedback_section   # noqa: F401  (the variable's name, for tests)
from app.curve_math import curve_at, domain
from app.layout_solver import annotation_targets, target_first_timing
from app.render import footage as film
from app.render.footage import clean_query, query_problem
from app.render.layout_check import measured_conflicts
from models.visual_brief_schema import (COMPONENT_PORTS, LANE_ICONS, SAFE_MATH_FUNCTIONS, SVG_TYPES, ComponentType, SceneVisualBrief,
                                        OBJECT_ICON_NAMES, emphasis_problem, find_cue, measure_problem, move_problem, narration_words, scene_point)

AGENT = "agent004"
KNOWN_RENDERERS = ("html", "skip")       # "html": agent010 draws it (default); "manim" is read as "html" (retired)
MAX_ATTEMPTS = 3          # 1 call + 2 retries; each attempt is one LLM call
MAX_ERROR_CHARS = 2000    # errors sent back to the LLM on a retry
MAX_ENTITIES = 8          # per scene, instruments included: more does not fit in one readable frame
MAX_FORMULAS = 2          # TEX_FORMULA per scene: equations only, never notes
MAX_OVER_FOOTAGE = 3      # things drawn over the hook's film (app/render/footage.py)
FOOTAGE_DOMAINS = ("electronics", "physics_math", "economics")   # routes.json domains whose hook always has a film
LAYOUT_TEMPLATES = ("circuit", "comparison", "analogy_fullscreen")   # agent010's pages (scene "layout_template")
BRIEFS = TypeAdapter(list[SceneVisualBrief])

# Every component type the render engine draws, with the only port names each one has.
PORTS = dict(COMPONENT_PORTS)
NO_STATE = "none (only highlighted / dimmed)"
# What set_state accepts for each component (the engine's state keys), and what initial_state holds.
STATES = {
    ComponentType.BATTERY: '{"active": true|false}',
    ComponentType.LAMP: '{"on": true|false}',
    ComponentType.SWITCH: '{"closed": true|false}',
    ComponentType.AMMETER: '{"reading": <amps, number>}',
    ComponentType.WIRE_BUS: NO_STATE,
    ComponentType.EARTH_GROUND: NO_STATE + ' (protective earth symbol)',
    ComponentType.CHASSIS_MASS: NO_STATE + ' (chassis / ground reference, 0 V)',
    ComponentType.ARROW_ANNOTATION: NO_STATE + '; initial_state {"text": "...", "direction": "DOWN" or [dx, dy], '
                                               '"target": "<id it points at>", "tone": "wrong"}',
    ComponentType.PEDAL_CRANK: '{"spinning": true|false}',
    ComponentType.SPROCKET: '{"spinning": true|false}',
    ComponentType.CHAIN_LINK: NO_STATE,
    **{t: '{"active": true|false} (green outline); rides in a BODY or OBJECT (a scale in an elevator): '
          '"anchor": {"body": "<its id>"}, its only anchor' for t in SVG_TYPES},
    ComponentType.WATER_TANK: '{"active": true|false, "level": <0 to 1, the water height>}; '
                              'initial_state {"level": 0.6}',
    ComponentType.AXES_GRAPH: NO_STATE + '; initial_state {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1], '
                                         '"x_label": "temps", "y_label": "vitesse"}',
    ComponentType.CURVE_PLOT: NO_STATE + '; initial_state {"func": "np.sin(x)", "axes": "<id of an AXES_GRAPH '
                                         'of the scene>", "label": "..."}, or parametric {"x_func": "np.cos(t)", '
                                         '"y_func": "np.sin(t)", "t_min": 0, "t_max": 6.2832, "axes": ..., "label": ...}',
    ComponentType.VECTOR_ARROW: NO_STATE + '; initial_state {"direction": "DOWN" or [dx, dy], "length": 1.8, '
                                           '"symbol": "P", "label": "Poids"}; with a number: "value": 588, "unit": "N" '
                                           '(drawn to scale with the other vectors of that unit; set_value on it later '
                                           'shrinks or grows it before the eyes); on a curve: {"anchor": {"curve": "<CURVE_PLOT id>", '
                                           '"t": 0}, "direction": "TANGENT" or "CENTER" or "OUTWARD", ...}',
    ComponentType.TEX_FORMULA: NO_STATE + '; initial_state {"latex": "E=mc^2", "tone": "result"}',
    ComponentType.OBJECT: '{"active": true|false} (green outline), {"floating": true} (rises slowly and drifts: '
                          'weight lost); initial_state {"icon": "<one of the OBJECT icons>", '
                          '"label": "Ascenseur"}; in a graph: "anchor": {"axes": "<AXES_GRAPH id>", "x": 0, "y": 0}; '
                          'moves in a straight line with "move"; rides in another one: "anchor": {"body": "<its id>"}',
    ComponentType.BODY: NO_STATE + '; moves with "move_along" (on a curve) or "move" (straight); initial_state '
                                   '{"label": "Satellite", "anchor": {"curve": "<CURVE_PLOT id>", "t": 0}, "size": 0.25, '
                                   '"color": "#F59E0B"}; rides in another body or object: "anchor": {"body": "<its id>"}',
    ComponentType.SEESAW: '{"left": true} / {"right": true} drops that load on its end (both there from the start '
                          'if never set), {"balanced": true} slides the beam until it balances: the pivot shows the '
                          'weighted mean; initial_state {"left": {"label": "Classe A", "weight": 30, "value": 15}, '
                          '"right": {"label": "Classe B", "weight": 5, "value": 10}, "unit": "/20"}',
    ComponentType.LANES: '{"active": true|false} (false stops the lanes, true sets them off again); initial_state '
                         '{"lanes": [{"label": "File rapide", "rate": 1.5}, {"label": "File lente", "rate": 0.5}], '
                         f'"icon": one of {list(LANE_ICONS)}, "label": "Péage"}}; 2 to 4 lanes, "rate" = how many '
                         'go through per second (0.2 to 3)',
    ComponentType.VOLTMETER_PROBES: NO_STATE + '; reads a voltage with the "measure" action; '
                                               'initial_state {"label": "Voltmètre"}',
}
ACTIONS = ("spawn", "set_state", "start_flow", "stop_flow", "fade_out", "set_value", "measure", "move_along", "move",
           "emphasize")
SEMANTIC_POSITIONS = ("TOP_LEFT", "TOP", "TOP_RIGHT", "LEFT", "CENTER", "RIGHT",
                      "BOTTOM_LEFT", "BOTTOM", "BOTTOM_RIGHT")
COMPONENTS_FOR_PROMPT = "\n".join(f"  * {t.value}: ports {list(PORTS[t]) or 'none'}, set_state {STATES[t]}"
                                  for t in PORTS)

# llm_call sends a single user message, so the "system" instructions open the prompt.
PROMPT = """ROLE: You are the visual director of an educational animation studio. You do not draw and
you do not write code: you describe each scene as real components, the wires between them, and
timed actions. A deterministic renderer draws exactly what you describe, nothing more.

TASK: For each scene below, build a rich, multi-layered scene that SHOWS what the narrator says,
moment by moment: the main diagram (components and wires), the instruments that measure it, and
the key numbers. Decompose the narration into the components it talks about, how they are wired,
and a continuous sequence of actions in the order the narrator explains it. Example: spawn the
battery, spawn the lamp, close the switch, start the flow, turn the lamp on, read the current on
the ammeter, measure the lamp's voltage with the voltmeter probes.

ALLOWED COMPONENTS (the ONLY types and the ONLY port names that exist):
{components}

STRICT RULES:
- NEVER use abstract types like 'box', 'node', or generic rectangles. Every entity's type must be
  one of the components above, written exactly as above.
- NEVER invent arbitrary port names. source_port and target_port must be ports of that
  component's type, exactly as listed above.
- Every connection and every action must refer to entities declared in the same scene.
- KEEP EACH FRAME READABLE: at most {max_entities} entities per scene (instruments included). One
  circuit per scene, unless the narration compares circuits: then at most two, each one closed. At
  most {max_formulas} TEX_FORMULA per scene, only for real equations, never for notes or sentences.
  Rather than piling everything up, fade out what the narrator has finished with, then spawn
  the next thing.
- Every WIRE_BUS has both of its ports wired; never leave a component unconnected in a circuit.
- NO METAPHORS INSIDE A CIRCUIT: a pure electrical explanation uses only electrical components.
  Never WATER_TANK or PIPE_VALVE in a circuit (not for the earth, not for a reference): use
  EARTH_GROUND, CHASSIS_MASS and dashed connections. Water analogies only when the narration
  itself makes the water comparison.
- CLOSED CIRCUITS: connections must form a loop that starts at BATTERY:positive, goes through each
  component (in by one port, out by its other port) and comes back to BATTERY:negative. Example:
  battery_1:positive -> lamp_1:left_terminal, lamp_1:right_terminal -> battery_1:negative.
  With a switch: battery_1:positive -> switch_1:in, switch_1:out -> lamp_1:left_terminal,
  lamp_1:right_terminal -> battery_1:negative.
  Only leave a circuit open if the narration is explicitly about an open (broken) circuit.
- position: one of {positions}, or scene coordinates [x, y, 0] with x between -6 and 6 and
  y between -3 and 2 (y above 2 is reserved for the text overlay). Each entity gets its own position.
- initial_state may hold "label": a short French name shown under the component (e.g. "Pile").
- WHICH COMPONENTS TO USE:
  * Electrical circuits: BATTERY, LAMP, SWITCH, AMMETER, WIRE_BUS, and VOLTMETER_PROBES to measure
    a voltage (never wired: its probes touch two pins, see "measure").
  * Ground references: CHASSIS_MASS for the circuit's ground / 0 V reference ("GND", "masse"),
    EARTH_GROUND for the protective earth ("terre"). Each has one port, "terminal", wired to the
    node it references: a battery terminal, or a WIRE_BUS placed between two components when the
    reference is a point in the middle of the circuit. A link that exists only optionally (e.g.
    earth to chassis) is a connection with "dashed": true.
  * Concrete objects, everyday analogies and economics: the icon types WATER_TANK, PIPE_VALVE (water
    analogies), COINS, BANK, CART, SCALE, TRENDING_UP, TRENDING_DOWN, GAUGE (money, prices, markets).
    They have a port on each side ("left", "right", "top", "bottom") to show a flow between them.
  * Any other concrete thing (an elevator, a rocket, a person, a house, the Sun, a tree...): an OBJECT,
    with "icon" one of {object_icons}, and its "label". It is drawn like the icon types, ports
    included. Never borrow another type's icon for it: CART is a shopping cart, never an elevator
    (that is OBJECT "elevator"); BANK is a bank, never a building in general (OBJECT "building").
    An icon means what it shows: "zap" is electricity, never a cannon (that is "cannon"). When no
    icon in the list is the thing, use a BODY (a plain disc) with its label rather than an icon
    that shows something else.
  * Queues side by side (lanes at a toll, checkouts in a shop, counters: the analogy of parallel
    branches, of a flow that splits between ways): ONE LANES, never cars or people moved one by one.
    It draws the lanes delimited, each with its label, its vehicles rolling through the gate at its
    "rate" (the faster lane: the higher rate) and the count gone through: every lane keeps going.
  * Maths and physics concepts: AXES_GRAPH with CURVE_PLOT for functions and quantities over time,
    VECTOR_ARROW for forces and velocities (weight / gravity always points DOWN), TEX_FORMULA for
    equations. These have no ports and are never wired.
  * "direction" (VECTOR_ARROW, ARROW_ANNOTATION): "UP", "DOWN", "LEFT" or "RIGHT" for the simple
    cases, or a vector [dx, dy] (two real numbers, not both 0; y points up) when the narration gives a
    tilt or an angle. For an axis tilted 23.5° from the vertical (the Earth's), use [0.4, 0.9].
  * Bicycle mechanics: PEDAL_CRANK, SPROCKET, CHAIN_LINK.
- CURVE_PLOT "func" is a Python expression of x using ONLY x, numbers, pi, e, + - * / ** and
  np.{maths}, e.g. "np.sin(x)", "0.5 * x**2 - 1", "np.exp(-x)". It must match the narration's function
  (linear: straight line, quadratic: parabola, exponential: ever steeper). Put the curve on an
  AXES_GRAPH of the same scene ("axes": its id; give the curve the same position).
- PARAMETRIC CURVES: for a circle, an orbit, an ellipse, a spiral or any closed curve, y = f(x) cannot
  work: give the CURVE_PLOT "x_func" and "y_func" instead of "func", expressions of t (same rules, t
  instead of x), and optionally "t_min" / "t_max" (default 0 and 2*pi: one full turn). A circle of
  radius 2: "x_func": "2*np.cos(t)", "y_func": "2*np.sin(t)"; an elliptic orbit: "3*np.cos(t)",
  "2*np.sin(t)". The renderer keeps equal scales on x and y, so a circle stays round. Never fake a
  closed curve with a sine or a parabola.
- VECTORS ON A CURVE: a force or a velocity of a body moving along a curve (a satellite on its orbit,
  a ball on its trajectory) starts ON the curve: give the VECTOR_ARROW "anchor": {{"curve": "<id of the
  CURVE_PLOT>", "t": <t>}} for a parametric curve (t between its t_min and t_max) or {{"curve": ..., "x":
  <x>}} for y = f(x), instead of guessing a position (still give one: it is ignored). Its "direction"
  can then be "TANGENT" (along the curve: a velocity), "CENTER" (towards the centre of the curve: the
  gravity of the planet at the centre of an orbit) or "OUTWARD", worked out by the renderer, or a
  cardinal as usual ("DOWN" for a weight). A satellite on an orbit "3*np.cos(t)", "3*np.sin(t)" at
  t = 0.785 (45°): velocity {{"anchor": {{"curve": "orbit", "t": 0.785}}, "direction": "TANGENT"}}, gravity
  {{"anchor": {{"curve": "orbit", "t": 0.785}}, "direction": "CENTER"}}.
- MOVING BODIES: a body that moves along a curve (a satellite on its orbit, a planet round the Sun, a
  ball on its trajectory) is a BODY anchored on that curve ("anchor": {{"curve": ..., "t": <where it
  starts>}}, "label": "Satellite"). The action {{"action": "move_along", "target": <its id>, "to": <the t
  (or x) it goes to>, "duration": <seconds>}} makes it travel along the curve at an even pace, from
  where it is ("to" may go past t_max: t from 0 to 6.2832 is one lap of an orbit, to 12.5664 two).
  Show what the narration says is moving: when it speaks of falling round the Earth, make the
  satellite go round. A move must END before the scene does (at + duration <= the scene's
  duration_sec): cue it on early words, not on the last ones. Things that travel together (the ISS and
  its astronaut, an elevator and what is in it) are never two bodies at one point (they would hide each
  other): move ONE, and give the others "anchor": {{"body": "<its id>"}}: they ride in it, drawn beside
  it, and go with it. Or make them one body ("Station et astronaute"). A VECTOR_ARROW with "anchor": {{"body": <its id>}} rides on the body and follows
  it as it moves, TANGENT / CENTER worked out at every instant: the velocity and the gravity of a
  satellite, {{"anchor": {{"body": "satellite_1"}}, "direction": "TANGENT"}} and the same with "CENTER".
- MOVING THINGS WITHOUT A GRAPH: a fall, a lift going down, a car driving, a ball dropped are shown
  as the thing itself moving, not as a curve on axes (axes are for a quantity over time, an orbit, a
  trajectory the narration draws). Use an OBJECT (the "elevator" icon...) or a BODY, no anchor, and the
  action {{"action": "move", "target": <its id>, "to": [x, y] (the scene point it goes to), "duration":
  <s>, "easing": "fall"}}: "fall" speeds up as a falling thing does, "smooth" eases in and out (the
  default), "linear" keeps one speed. What rides in it ("anchor": {{"body": <its id>}}) and the vectors
  starting on it go with it: an elevator in free fall is the elevator OBJECT from [0, 1.5] "move" "to"
  [0, -1] with "fall", the astronaut riding in it, and a weight VECTOR_ARROW {{"anchor": {{"body":
  "elevator_1"}}, "direction": "DOWN"}}. Leave room for what goes with it: its vectors hang below
  it, so a fall ends around y = -1, not at the bottom of the screen (the renderer shortens a move
  that would take them off screen).
- MEANING IN COLOUR: give a TEX_FORMULA or an ARROW_ANNOTATION a "tone" when it means something:
  "result" (green: the conclusion, the formula proved), "warning" (amber: a trap, "attention"),
  "wrong" (red: the misconception, a false claim, a contradiction), "key" (the key idea). Leave it
  out for a plain step. Then the action {{"action": "emphasize", "target": <id>, "effect": "shake"}}
  makes a contradiction or a false idea shake, on the words that say it is false, and "effect":
  "pulse" makes a result pulse when it is reached (use them once or twice a video, not on every step):
  {{"at": 9.0, "action": "emphasize", "target": "formula_2", "effect": "shake", "cue": "contradiction"}}
- VECTOR NAMES: give every VECTOR_ARROW a short "symbol" drawn by its arrow, as on a physics diagram
  (1 to 3 characters: "P" poids, "R" réaction, "g" or "F_g" gravité, "v" vitesse, "T" tension, "F"
  force), and its full French "label" ("Poids", "Réaction du sol"): the label goes in the scene's
  legend ("P : Poids"), not beside the arrow, so the picture keeps its room. One symbol per quantity
  in a scene (two arrows for the same force, on two bodies: the same symbol and label).
- FORCES ACT ON SOMETHING: a VECTOR_ARROW for a force or a velocity of a drawn OBJECT or BODY starts
  on it: "anchor": {{"body": "<its id>"}} (a cardinal or [dx, dy] direction; TANGENT / CENTER on a
  body on a curve). Never a free arrow placed near it, or near a formula: it would point from
  nothing. The Earth's pull on the ISS: {{"anchor": {{"body": "iss_1"}}, "direction": [-1, -0.9]}}. A
  contact force starts where the contact is: the ground's reaction on a person starts on the ground
  ({{"anchor": {{"body": "ground_1"}}, "direction": "UP"}}, the person standing on it, just above),
  a rope's pull on the rope; the weight starts on the person.
- NUMBER LINE: to place numbers on a line (0,999... and 1, a fraction, a decimal), use an AXES_GRAPH
  with only "x_range" (no y_label, no curve on it) and each number a BODY anchored on it at y = 0
  ({{"anchor": {{"axes": "<id>", "x": 0.999, "y": 0}}, "label": "0,999..."}}): it is drawn as one
  graduated line with dots, not as two axes.
  Numbers closer than a twentieth of the line's range pile up: zoom the line on them ("x_range":
  [0.99, 1] for 0,999 and 0,9999), or show only those far enough apart (0,9 ; 0,99 ; 1 on [0.8, 1]).
- IN A GRAPH, EVERYTHING USES THE GRAPH'S UNITS: a trajectory drawn with a graph (a cannonball, a
  ball thrown) is a CURVE_PLOT on the same axes (a parabola from the cannon's point, or a short arc),
  with a BODY anchored on it and moved by "move_along"; never a "move" (its [x, y] are scene units,
  unrelated to the graph: the body would fall beside the graph). A trajectory starts at its launch
  point and goes one way: give its CURVE_PLOT its own "x_range" (a throw to the right from x = 0:
  "x_range": [0, 4]), never a parabola drawn on both sides. When the planet's size matters (Newton's
  cannonball falling back to the ground), draw its surface as a parametric circle on the same axes
  ("x_func": "1.5*np.cos(t)", "y_func": "1.5*np.sin(t)", label "Surface de la Terre"): an icon has
  no size, a trajectory would cross it. Things anchored on the graph are
  drawn as 60 px icons: keep them apart (a mountain and the cannon on it: the cannon on the
  mountain's top, a little to the side, not on the same point).
- EVERY CURVE IS SEEN: a CURVE_PLOT spans at least a fifth of its graph. Throws compared with a
  planet (Newton's cannonball): a planet of radius 2 to 3 on axes about twice as wide, and each throw
  long enough to tell apart (the slow one lands clearly near the tower, the fast one far round the
  planet, the orbital one goes all the way round), not three arcs piled at the top of the tower.
- NUMBERS AND CHANGES ARE DRAWN, NOT ONLY NAMED: when the narration gives values or a change (a price
  that rises, an inflation rate in %, a target of 2 %, a speed, a share), draw them: an AXES_GRAPH with
  a CURVE_PLOT of the quantity over time (years on x, the price or the rate on y), a GAUGE showing the
  value, a TEX_FORMULA. Icons (CART, TRENDING_UP, COINS...) illustrate, they explain nothing alone: a
  scene of icons and labels only is a list, not an explanation. Each video has at least one graph
  of its main quantity when there is one (economics: always).
- A BODY IS A DISC FOR SOMETHING THAT MOVES OR SITS ON A GRAPH: a ball, a satellite, a point on a
  curve or a number line. Never a disc standing for an idea, a price or a quantity ("Prix du pain"):
  show a thing by its icon (OBJECT with an icon, CART, COINS...), a value by a GAUGE or a graph, an
  idea by an ARROW_ANNOTATION. A planet, a moon, the Sun: an OBJECT with the icon "earth", "moon" or "sun".
- THE PICTURE DEMONSTRATES, IT DOES NOT DECORATE: every key idea is an action the viewer sees happen,
  in proportion to the numbers said:
  * a force or a quantity with a number is a VECTOR_ARROW with "value" (and "unit"): vectors are drawn
    to scale; when the value changes (Terre -> Lune: 588 N -> 96 N) it is set_value on THE SAME vector,
    which shrinks before the eyes; never two separate arrows with made-up lengths. A thing losing
    its weight: set_state {{"floating": true}} on it.
  * weights, a weighted mean, a lever, a comparison of two amounts: ONE SEESAW (the loads drop on its
    ends, it tips; set_state {{"balanced": true}} shows where it balances: the weighted mean).
  * electrons in a circuit move: start_flow with "carriers": "electrons" (they go from - to +, against
    the conventional current, which is a plain start_flow); never BODY discs standing still on a wire.
  * a curve draws itself, a formula writes itself: spawn them on the words that say them.
- A LIGHT OR A RAY NAMED BY ITS COLOUR IS DRAWN IN IT: "Bleu diffusé" is blue (#3B82F6), "Rouge direct"
  red (#EF4444), green #10B981, orange #F97316, yellow #EAB308, violet #8B5CF6; never a blue ray in red.
- A GRAPH SHOWS REAL NUMBERS: its axes run over the quantity's real range, named with their unit
  ("années" 2015 to 2025, "PIB (milliards d'€)"), and its curve goes through the values the narration
  gives; never a line from 0 to 10 over "temps" and "PIB".
- A GAUGE SHOWS A VALUE: every GAUGE gets its number with set_value, cued on the words that say it; a
  dial with no number means nothing (for an idea with no number: an OBJECT icon or an ARROW_ANNOTATION).
- THE SAME VALUES ALL ALONG: a battery, a price, an object keeps the values the narration gives it
  from one scene to the next (a "Pile 6 V" stays "Pile 6 V"); change them only where the narration does.
- THINGS IN A GRAPH: an OBJECT, a BODY or a VECTOR_ARROW that belongs to a graph (the Earth at the
  centre of an orbit, the Sun at a focus, a car at a point of a road drawn as a curve) is placed on
  that point of the graph, in the graph's units: "anchor": {{"axes": "<AXES_GRAPH id>", "x": 0, "y": 0}}
  (its "position" is then ignored). Never guess a scene position for it: it would land beside the
  graph, and an orbit would go round nothing. The Earth at the centre of an orbit "2.5*np.cos(t)",
  "2.5*np.sin(t)" on axes "axes_1": OBJECT "earth" with "anchor": {{"axes": "axes_1", "x": 0, "y": 0}}
  (then a gravity "CENTER" points at it). Centre the orbit on the planet, not the other way round.
- An AXES_GRAPH fills most of the screen (70 % of its width): place it CENTER, and add other
  entities only where the narration needs them.
- LAYOUT: the renderer shows VOLTMETER_PROBES and the counters in an instrument column on the right
  of the screen. When a scene has them, keep the main diagram in the left two thirds (x between -6
  and 2.5).
- SHOW MEASUREMENTS WITH INSTRUMENTS, NEVER AS FLOATING TEXT:
  * Electronics: a current is read on an AMMETER in series (in the loop); a voltage is read with
    VOLTMETER_PROBES and a "measure" action: the red probe touches target_pin_a, the black probe
    touches target_pin_b (two ports of the circuit, written "<entity id>.<port>", e.g.
    "lamp_1.left_terminal"), and the meter shows "value" in volts. Lamps light up only while
    current flows through them.
    PROBE POLARITY: target_pin_a is the red probe (V+, the point measured), target_pin_b the black
    probe (COM, the reference, usually the ground). "value" = potential of pin a minus potential
    of pin b: positive when the red probe is on the higher potential (+6.0 for the + terminal
    against the - terminal of a 6 V battery), negative when it is on the lower one (-6.0 with the
    red probe on the - terminal and COM on the + terminal).
    Readings must be physically right: two points joined by a wire, a WIRE_BUS or a closed switch
    are at the same potential (0 V between them); across the battery's two terminals the meter
    reads the battery's voltage; in a loop with a single lamp, the lamp gets that whole voltage.
    Every reading in a scene must agree with the others (one battery voltage, one ground).
    When a switch opens, stop the flow at the same moment; ammeters then fall back to 0 by
    themselves (do not set their reading).
  * Physics: every force is its own VECTOR_ARROW with a label ("Poids", "Réaction du sol"...);
    motions over time (trajectories, positions, speeds) are CURVE_PLOTs on an AXES_GRAPH.
  * Economics: quantities live on objects: WATER_TANK for a stock that fills or empties, COINS and
    BANK for money, SCALE for a balance (state active when it tips), TRENDING_UP / TRENDING_DOWN for
    rises and falls; every amount is a set_value counter on its object, "tone": "positive" for a
    gain or rise (green), "negative" for a loss or fall (red).
  * Use only the components listed above: there is no light cone, bar chart or liquid-level type, and
    no OBJECT icon outside the list. If the narration needs one, show the idea with the closest listed
    components.
- TEX_FORMULA "latex" is plain LaTeX, e.g. "U = R \\times I", "E = mc^2", "\\frac{{d}}{{t}}".
- actions: objects with "at" (seconds from the start of the scene, between 0 and the scene's
  duration_sec) and "action", one of {actions}:
  {{"at": 0.5, "action": "spawn", "target": "battery_1", "cue": "une pile"}}
  {{"at": 3.0, "action": "set_state", "target": "switch_1", "state": {{"closed": true}}, "cue": "on ferme"}}
  {{"at": 3.5, "action": "start_flow", "path": ["battery_1", "switch_1", "lamp_1", "battery_1"], "current": 0.5,
    "cue": "le courant"}}
  {{"at": 4.0, "action": "set_state", "target": "lamp_1", "state": {{"on": true}}, "cue": "la lampe brille"}}
  {{"at": 8.0, "action": "set_state", "target": "switch_1", "state": {{"closed": false}}, "cue": "circuit ouvert"}}
  {{"at": 8.0, "action": "stop_flow", "path": ["battery_1", "switch_1", "lamp_1", "battery_1"], "cue": "circuit ouvert"}}
  {{"at": 9.0, "action": "fade_out", "target": "lamp_1", "cue": "ensuite"}}
  {{"at": 5.0, "action": "set_value", "target": "bank_1", "value": 300, "unit": "Md€", "tone": "negative",
    "cue": "300 milliards"}}
  {{"at": 6.0, "action": "measure", "target": "voltmeter_1", "target_pin_a": "lamp_1.left_terminal",
    "target_pin_b": "lamp_1.right_terminal", "value": 4.5, "unit": "V", "cue": "la tension"}}
  {{"at": 7.0, "action": "move_along", "target": "satellite_1", "to": 6.2832, "duration": 4, "cue": "il tombe sans cesse"}}
  {{"at": 3.0, "action": "move", "target": "elevator_1", "to": [0, -2.5], "duration": 2.5, "easing": "fall", "cue": "le câble casse"}}
  set_value shows an animated counter for the target, rolling up to "value" (optional "unit",
  "decimals", "tone": "positive" or "negative"). Use it for every key number the narrator says.
  measure moves the voltmeter's probes onto the two pins and rolls its display up to "value".
  Spawn components before using them; close a switch BEFORE the current flows through it; spread
  the actions over the whole scene.
- TARGET FIRST: an ARROW_ANNOTATION points at one entity (a component, a formula, a gauge...): name
  it in its initial_state "target" and put its tip next to it. It MUST NOT spawn before that
  target: if the formula spawns at 9.5 s, the arrow spawns at 9.5 s or later (together is fine).
  An arrow at a target that is there from the start may spawn whenever the narration needs it.
  start_flow may give "current": the amps shown by the ammeters on the path (default 1.5 A); give it
  when the narration states a value.
- WORD-SYNCHRONIZED ACTIONS: every action has a "cue": the exact words of the narration_text (1 to
  4 consecutive words, copied as written) on which it happens. The action is timed on those words:
  its "at" is recomputed from them, and the renderer starts it when the voice says them. Follow the
  narration word by word, in its order:
  * the narrator says "tension", "volts", "différence de potentiel": a "measure" on the voltmeter,
    cued on those words;
  * the narrator says "courant", "débit", "ampères": "start_flow" through the circuit (its ammeters
    are highlighted automatically), cued on those words;
  * the narrator says "circuit ouvert" / "on ouvre": set_state {{"closed": false}} on the switch AND
    "stop_flow" on the same cue (a flow never runs through an open switch);
  * every key number the narrator says: its own action (set_value, measure, or a flow's current)
    cued on that number.
- DENSITY: a scene is a continuous sequence of micro-actions, never a still picture: about one
  action every 1 to 1.5 s of narration, each on its own cue. Components that are simply there from
  the start need no spawn action: they appear automatically when the scene opens.
- ONE THEME PER SCENE: a scene shows one thing, from its first word to its last.
  * A list of ideas (misconceptions, definitions, a comparison): 2 or 3 icon cards side by side in
    the centre, each an icon type with a short French label that states the idea (GAUGE "Tension =
    poussée", PIPE_VALVE "Courant = débit", SCALE for a comparison...), each spawned on its cue. No
    circuit, and never an incomplete one.
  * An analogy (water, château d'eau): only its objects (WATER_TANK, PIPE_VALVE), on screen for the
    whole scene (never faded out), and alive: set_state {{"level": ...}} on the tanks when the
    narration speaks of height or level, start_flow along tank -> pipe -> tank when it speaks of
    débit. Never a circuit component in the same scene: the circuit comes in the next scene.
  * A circuit is always closed (see CLOSED CIRCUITS), unless the narration says it is open.
- LABELS MATCH THEIR TARGET: an ARROW_ANNOTATION names the quantity of what it points at, never
  another one. At a formula of U (e.g. "U = V_A - V_B"): "Tension U (différence de potentiel)"; at
  a formula of I (e.g. "I = \\Delta Q / \\Delta t"): "Courant I (débit de charge)"; at an ammeter:
  the current I. Set its "target" to that entity's id. Keep it short (at most 40 characters); a
  whole sentence about the circuit's state ("Circuit ouvert : le courant ne circule pas") is a
  status badge: "kind": "status", shown beside the diagram without an arrow.
- LAYOUT TEMPLATE: next to "scene_id" in each scene, "layout_template" names the page the renderer
  draws the scene on (it sits outside the visual brief schema below):
  * "circuit": the diagram on the left, the instrument column on the right. The default, and the
    only one for a scene with VOLTMETER_PROBES.
  * "comparison": two panels side by side: side A on the left (x < 0), side B on the right (x > 0),
    e.g. "ce qu'on croit" | "ce qui est vrai", or two branches to compare. Only when the scene's
    narration opposes two notions, and only with something drawn on EACH side (an empty panel
    compares nothing). Optional "panel_titles": ["<A>", "<B>"], short, in French. Each thing goes in
    the panel of what it is about: with "Masse (kg)" | "Poids (N)", m = 60 kg on the left (x < 0), the
    weights in newtons on the right (x > 0); never both formulas in one panel. A thing moved with
    "move" stays in its panel.
  * "analogy_fullscreen": one large visual across the screen, annotations over it. Only when the
    scene's narration makes an explicit analogy (château d'eau, péage...).
  Vary them as far as the script allows: at most {max_circuit} scenes "circuit"; at least one
  "analogy_fullscreen" when a scene makes an analogy, at least one "comparison" when a scene opposes
  two notions; never the same template in two consecutive scenes. What this script allows, per scene:
{layout_eligibility}
- FILM BEHIND THE HOOK: the first scene (the hook) has a real film clip behind it, full-frame and
  darkened: "footage": {{"query": "<1 to 4 French words of what to film>"}} next to its "scene_id" (outside
  the visual brief): the real sight the question starts from, instead of icons: the sky to ask why it
  is blue, a motorway toll, a market, rain on a window, power lines, a city at night, a phone charging.
  Only a topic of pure mathematics with nothing to film goes without one. The query
  names what to film: landscapes, sky, water, streets, machines, objects, people at work or in a crowd
  (a face in close-up is never taken).
  Over the film draw at most {max_over_footage} things: the question as an ARROW_ANNOTATION status badge,
  a formula or one key icon; never icons standing for the setting the film already shows.
- text_overlay: a short title (under 8 words) and an optional one-line subtitle; set
  clear_previous to true unless the scene explicitly continues the previous scene's title.

LANGUAGE: The target audience is French. title, subtitle and label MUST be in PERFECT FRENCH.
Keys, ids, component types, layers, ports, states and action names stay exactly as written above.

JSON SCHEMA of one SceneVisualBrief (each scene must validate against it):
{schema}

SCENES:
{scenes}

Answer with JSON only: {{"scenes": [ ...one SceneVisualBrief per scene, scene_id as a string, plus its
"layout_template" (and "panel_titles" for a comparison, "footage" on the hook when it has one)... ]}}"""

RETRY_NOTE = """

YOUR PREVIOUS ANSWER WAS REJECTED by the validator with these errors:
{errors}
Answer again with the complete corrected JSON, fixing every error above."""


def scene_field(scene, *names):
    """First present value among several field names (agent003's names first)."""
    return next((scene[name] for name in names if scene.get(name) is not None), None)


def validate_storyboard_topology(briefs, durations) -> list:
    """Every problem in the briefs, as readable messages (empty list = valid):
    allowed component types, known entity ids in connections and actions, real port names,
    known action names, action times inside the scene, and no two entities at the same position."""
    errors = []
    for brief in briefs:
        where = f"scene {brief.scene_id}"
        types = {entity.id: entity.type for entity in brief.entities}
        for entity_id, entity_type in types.items():
            if entity_type not in PORTS:
                errors.append(f"{where}: {entity_id} is a {entity_type.value}, which is not allowed "
                              f"(allowed: {[t.value for t in PORTS]})")
        for c in brief.connections:
            for end_id, port in ((c.source_id, c.source_port), (c.target_id, c.target_port)):
                if end_id not in types:
                    errors.append(f"{where}: connection uses unknown entity {end_id!r}")
                elif types[end_id] in PORTS and port not in PORTS[types[end_id]]:
                    errors.append(f"{where}: {end_id} is a {types[end_id].value}, it has no port {port!r} "
                                  f"(allowed: {list(PORTS[types[end_id]])})")
        duration = durations.get(brief.scene_id)
        for i, action in enumerate(brief.actions):
            kind = action.get("action")
            if kind not in ACTIONS:
                errors.append(f"{where}: action #{i} {kind!r} is not one of {list(ACTIONS)}")
                continue
            at = action.get("at")
            if not isinstance(at, (int, float)) or at < 0 or (duration and at > duration):
                errors.append(f"{where}: {kind} at {at!r} must be a number between 0 and {duration}")
            if kind == "emphasize":
                problem = emphasis_problem(action, types)
                if problem:
                    errors.append(f"{where}: {problem}")
                continue
            if kind == "measure":
                problem = measure_problem(action, types)
                if problem:
                    errors.append(f"{where}: {problem}")
                continue
            if kind in ("move_along", "move"):
                problem = move_problem(action, {e.id: (e.type, e.initial_state) for e in brief.entities})
                if problem:
                    errors.append(f"{where}: {problem}")
                continue
            referenced = action.get("path") if kind in ("start_flow", "stop_flow") else [action.get("target")]
            if kind == "stop_flow" and referenced is None:
                continue                      # stop_flow without a path stops every flow
            if not isinstance(referenced, list) or (kind == "start_flow" and len(referenced) < 2):
                errors.append(f"{where}: {kind} needs {'a path of 2+ ids' if 'flow' in kind else 'a target'}")
                continue
            errors += [f"{where}: {kind} refers to unknown entity {r!r}" for r in referenced if r not in types]
            if kind == "set_state" and not isinstance(action.get("state"), (dict, str)):
                errors.append(f"{where}: set_state on {action.get('target')} needs a state")
            if kind == "set_value" and not isinstance(action.get("value"), (int, float)):
                errors.append(f"{where}: set_value needs a numeric value, got {action.get('value')!r}")
            current = action.get("current")
            if kind == "start_flow" and current is not None and not (isinstance(current, (int, float)) and current >= 0):
                errors.append(f"{where}: start_flow current must be a number of amps >= 0, got {current!r}")
            if kind == "start_flow" and action.get("carriers", "conventional") not in ("conventional", "electrons"):
                errors.append(f"{where}: start_flow carriers must be \"conventional\" or \"electrons\", got {action.get('carriers')!r}")
        if len(brief.entities) > MAX_ENTITIES:
            errors.append(f"{where}: {len(brief.entities)} entities, at most {MAX_ENTITIES}: drop or reuse some")
        formulas = sum(entity.type == ComponentType.TEX_FORMULA for entity in brief.entities)
        if formulas > MAX_FORMULAS:
            errors.append(f"{where}: {formulas} TEX_FORMULA, at most {MAX_FORMULAS} (equations only, no notes)")
        seen = {}
        for entity in brief.entities:
            if entity.type == ComponentType.CURVE_PLOT or "anchor" in entity.initial_state:
                continue        # a curve sits on its axes; an anchored vector or body on its curve (its position is ignored)
            key = entity.position if isinstance(entity.position, str) else tuple(round(v, 1) for v in entity.position)
            if key in seen:
                errors.append(f"{where}: {entity.id} and {seen[key]} share the position {key}")
            seen[key] = entity.id
    return errors


def open_circuits(brief) -> list:
    """Batteries whose positive port does not lead back to their negative port. Current enters a
    component by one port and leaves by its other port, but never passes through a battery."""
    types = {entity.id: entity.type for entity in brief.entities}
    links = {}
    for c in brief.connections:
        a, b = (c.source_id, c.source_port), (c.target_id, c.target_port)
        links.setdefault(a, set()).add(b)
        links.setdefault(b, set()).add(a)
    for entity_id, entity_type in types.items():
        ports = PORTS.get(entity_type, ())
        if entity_type != ComponentType.BATTERY and len(ports) == 2:
            links.setdefault((entity_id, ports[0]), set()).add((entity_id, ports[1]))
            links.setdefault((entity_id, ports[1]), set()).add((entity_id, ports[0]))
    open_ones = []
    for battery in [i for i, t in types.items() if t == ComponentType.BATTERY]:
        start, goal = (battery, "positive"), (battery, "negative")
        seen, todo = {start}, [start]
        while todo:
            for neighbour in links.get(todo.pop(), ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    todo.append(neighbour)
        if goal not in seen:
            open_ones.append(f"scene {brief.scene_id}: {battery}")
    return open_ones


# ---- coherence between the narration and the picture: word cues, one theme, labels that match

SAME_CUE_STEP = 0.4       # s between two actions on the same cue (in the brief's order)
MOTIONS = ("move_along", "move")   # ... but moves after a move start together
# Word stems (narration_words are lowercase): what the narrator talks about.
VOLTAGE = ("tension", "volt", "potentiel")
VOLTAGE_CUE = VOLTAGE + ("borne",)
CURRENT = ("courant", "débit", "ampère", "intensité")
FLOW_CUE = CURRENT + ("circul", "parcour", "travers", "ferm", "passe")
OPENING = ("ouvert", "ouvre", "ouvrant", "coup", "interromp", "cass", "rompu")
ANALOGY_TYPES = {ComponentType.WATER_TANK, ComponentType.PIPE_VALVE}
CIRCUIT_TYPES = {ComponentType.BATTERY, ComponentType.LAMP, ComponentType.SWITCH, ComponentType.AMMETER,
                 ComponentType.WIRE_BUS, ComponentType.VOLTMETER_PROBES, ComponentType.EARTH_GROUND,
                 ComponentType.CHASSIS_MASS}
# What each letter may stand for (the first name is the one suggested): E is an energy or a field.
QUANTITIES = {"U": ("tension",), "I": ("courant", "intensité"), "R": ("résistance",), "P": ("puissance", "pression"),
              "E": ("énergie", "champ"), "Q": ("charge", "chaleur")}
INSTRUMENT_SYMBOLS = {"AMMETER": "I", "VOLTMETER_PROBES": "U"}


def said(words, stems):
    return any(word.startswith(stems) for _, word in words)


def cue_says(action, stems):
    return said(narration_words(action.get("cue")), stems)


def formula_symbol(latex):
    """The quantity a formula defines: the capital letter on the left of "=" ("U = V_A - V_B" -> U)."""
    match = re.search(r"(?<![\\A-Za-z])([A-Z])(?![A-Za-z])", str(latex or "").split("=")[0])
    return match.group(1) if match else None


def names_quantity(text, symbol):
    """Does the text name this quantity: its letter on its own, or its French name?"""
    return bool(re.search(rf"(?<!\w){symbol}(?!\w)", text)) or any(name in text.lower() for name in QUANTITIES.get(symbol, ()))


ANCHOR_GAP = 0.2         # share of the graph's wider range: closer than that, two anchored icons or discs overlap


def anchored_points(brief, graphs):
    """[(id, graph id, (x, y))] for the BODYs and OBJECTs anchored on a point of a graph, or on a curve
    (its point there, on the curve's axes): in graph units, so they can be compared."""
    by_id = {e.id: e for e in brief.entities}
    points = []
    for e in brief.entities:
        anchor = e.initial_state.get("anchor")
        if e.type not in (ComponentType.OBJECT, ComponentType.BODY) or not isinstance(anchor, dict):
            continue
        if "axes" in anchor:
            points.append((e.id, anchor["axes"], (anchor["x"], anchor["y"])))
        elif "curve" in anchor and anchor["curve"] in by_id:
            curve = by_id[anchor["curve"]].initial_state
            try:
                xs, ys = curve_at(curve, [float(anchor.get("t", anchor.get("x")))])
            except Exception:
                continue
            if math.isfinite(xs[0]) and math.isfinite(ys[0]):
                graph = curve.get("axes") if curve.get("axes") in graphs else anchor["curve"]
                points.append((e.id, graph, (float(xs[0]), float(ys[0]))))
    return points


def curve_meetings(brief, graphs, duration):
    """[(a, b, curve, when)]: two BODYs moving along one curve that come closer than ANCHOR_GAP while
    they move (the Moon, a satellite and an astronaut set off one after the other at the same speed:
    the first catches up), unless they move exactly together (merged as travellers instead)."""
    by_id = {e.id: e for e in brief.entities}
    riders = {}
    for e in brief.entities:
        anchor = e.initial_state.get("anchor") or {}
        if e.type == ComponentType.BODY and isinstance(anchor, dict) and anchor.get("curve") in by_id \
                and isinstance(anchor.get("t", anchor.get("x")), (int, float)):
            riders.setdefault(anchor["curve"], []).append(e.id)
    end = float(duration or 0) or max([float(a.get("at", 0)) + float(a.get("duration", 4)) for a in brief.actions
                                       if a.get("action") == "move_along"] + [10.0])
    times = np.linspace(0, end, max(2, int(end * 10)))
    found = []
    for curve_id, ids in riders.items():
        curve = by_id[curve_id].initial_state
        moves = {i: sorted((a for a in brief.actions if a.get("action") == "move_along" and a.get("target") == i
                            and isinstance(a.get("to"), (int, float)) and isinstance(a.get("at"), (int, float))),
                           key=lambda a: a["at"]) for i in ids}
        if sum(bool(m) for m in moves.values()) < 2:
            continue
        paths = {}
        for i in ids:
            anchor = by_id[i].initial_state["anchor"]
            value, where = float(anchor.get("t", anchor.get("x"))), np.empty_like(times)
            where.fill(value)
            for a in moves[i]:
                at, length = float(a["at"]), max(float(a.get("duration", 4)), 1e-6)
                going = (times >= at) & (times < at + length)
                where[going] = value + (float(a["to"]) - value) * (times[going] - at) / length
                where[times >= at + length] = float(a["to"])
                value = float(a["to"])
            try:
                xs, ys = curve_at(curve, where)
            except Exception:
                break
            paths[i] = np.stack([xs, ys], axis=1)
        near = ANCHOR_GAP * graph_span(graphs.get(curve.get("axes")) if curve.get("axes") in graphs else None)
        for k, a in enumerate(ids):
            for b in ids[k + 1:]:
                if a not in paths or b not in paths or not (moves[a] or moves[b]):
                    continue
                if moves[a] and rigid_moves(brief, a) == rigid_moves(brief, b):
                    continue
                gaps = np.hypot(*(paths[a] - paths[b]).T)
                close = np.where(gaps < near)[0]
                if len(close) and gaps[0] >= near:      # apart at first, then they meet
                    found.append((a, b, curve_id, round(float(times[close[0]]), 1)))
    return found


CURVE_MIN_SHARE = 0.15      # a curve smaller than this share of its graph's span is lost in it


def tiny_curves(brief, graphs):
    """The CURVE_PLOTs drawn so small on their graph that nobody can see them (a throw of 0.7 on axes
    16 wide): what part of the graph each one spans, inside its ranges."""
    errors = []
    for curve in brief.entities:
        state = curve.initial_state
        axes = graphs.get(state.get("axes"))
        if curve.type != ComponentType.CURVE_PLOT or axes is None or axes.type != ComponentType.AXES_GRAPH:
            continue
        ranges = [axes.initial_state.get(k) for k in ("x_range", "y_range")]
        if not all(isinstance(r, (list, tuple)) and len(r) >= 2 for r in ranges):
            continue
        try:
            low, high = domain(state, ranges[0][:2])
            xs, ys = curve_at(state, np.linspace(low, high, 200), ranges[0][:2])
        except Exception:       # an expression the checks already report
            continue
        inside = np.isfinite(xs) & np.isfinite(ys) & (ys >= ranges[1][0]) & (ys <= ranges[1][1]) \
            & (xs >= ranges[0][0]) & (xs <= ranges[0][1])
        if not inside.any():
            continue
        size = max(np.ptp(xs[inside]), np.ptp(ys[inside]))
        span = graph_span(axes)
        if size < CURVE_MIN_SHARE * span:
            errors.append(f"scene {brief.scene_id}: the curve {curve.id} ({state.get('label')!r}) spans {size:.2g} on "
                          f"{axes.id}, {span:g} wide: too small to be seen; make it span at least "
                          f"{CURVE_MIN_SHARE * span:.2g} (longer x_range, bigger curve) or narrow the axes")
    return errors


def idle_discs(brief, graphs):
    """BODYs that neither move nor sit on a graph, in a scene without one: a disc standing for an idea
    or a price ("Prix du pain") means nothing to the viewer."""
    if graphs:
        return []
    moving = {a.get("target") for a in brief.actions if a.get("action") in MOTIONS}
    idle = [e for e in brief.entities if e.type == ComponentType.BODY and e.id not in moving
            and not isinstance(e.initial_state.get("anchor"), dict)]
    return [f"scene {brief.scene_id}: the BODY {e.id} ({e.initial_state.get('label')!r}) is a plain disc that neither "
            f"moves nor sits on a graph: show the thing by its icon (OBJECT with an icon; \"earth\", \"moon\", "
            f"\"sun\" for a planet), a value by a GAUGE, an idea by an ARROW_ANNOTATION" for e in idle]


SHOWS_VALUES = {ComponentType.SEESAW, ComponentType.LANES, ComponentType.AXES_GRAPH, ComponentType.CURVE_PLOT, ComponentType.TEX_FORMULA, ComponentType.GAUGE,
                ComponentType.AMMETER, ComponentType.VOLTMETER_PROBES, ComponentType.VECTOR_ARROW, ComponentType.WATER_TANK}


QUEUE_ICONS = set(LANE_ICONS)
QUEUE_MOVERS = 3          # this many vehicles or people moved one by one: a queue, drawn by hand


UNIT_MARK = re.compile(r"[(%€$°/]|\d|\b(?:années?|ans|mois|jours?|heures?|secondes?|mètres?|km|kg|euros?|dollars?|habitants?|milliards?|millions?)\b")


def placeholder_graphs(brief):
    """AXES_GRAPHs drawn 0 to 10 on both axes with names that carry no unit ("temps", "PIB"): a line
    over made-up numbers, explaining nothing. A maths variable ("x", "t", "y") is a name of its own."""
    errors = []
    for axes in (e for e in brief.entities if e.type == ComponentType.AXES_GRAPH):
        state = axes.initial_state
        ranges = [state.get(k) or [0, 10] for k in ("x_range", "y_range")]
        default = all(isinstance(r, list) and len(r) >= 2 and r[:2] == [0, 10] for r in ranges)
        names = [str(state.get(k) or "") for k in ("x_label", "y_label")]
        if default and not any(len(n.strip()) <= 2 or UNIT_MARK.search(n.lower()) for n in names):
            errors.append(f"scene {brief.scene_id}: the graph {axes.id} ({names[0]!r}, {names[1]!r}) runs 0 to 10 on both "
                          f"axes with no unit: a line over made-up numbers; give the real ranges and units of the "
                          f"quantity (\"années\" 2015 to 2025, \"PIB (milliards d'€)\"), with the narration's values on the curve")
    return errors


ELECTRON_LABEL = re.compile(r"(?:^|\W)(?:e\s*[-−⁻]|électrons?)(?:\W|$)", re.IGNORECASE)


def electrons_as_discs(brief):
    """BODY discs standing for electrons in a scene with a circuit: still dots on a wire; electrons are
    a flow (start_flow "carriers": "electrons")."""
    if not brief.connections:
        return []
    found = [e.id for e in brief.entities if e.type == ComponentType.BODY and ELECTRON_LABEL.search(str(e.initial_state.get("label") or ""))]
    return [f"scene {brief.scene_id}: {found} are discs standing for electrons: drop them and show the electrons moving, "
            f"start_flow along the circuit with \"carriers\": \"electrons\" (from - to +)"] if found else []


def gauges_without_value(brief):
    """GAUGEs that never get a number (no set_value on them): a dial standing for nothing."""
    valued = {a.get("target") for a in brief.actions if a.get("action") == "set_value"}
    return [f"scene {brief.scene_id}: the GAUGE {e.id} ({e.initial_state.get('label')!r}) never shows a value: give it "
            f"its number with set_value, cued on the words that say it, or show the idea by an OBJECT icon or an "
            f"ARROW_ANNOTATION" for e in brief.entities if e.type == ComponentType.GAUGE and e.id not in valued]


def queues_by_hand(brief):
    """Vehicles or people (OBJECTs) moved one by one to show queues: they pile up and leave the frame;
    LANES draws the lanes, the flow and the counts."""
    moved = {a.get("target") for a in brief.actions if a.get("action") == "move"}
    queue = [e.id for e in brief.entities if e.type == ComponentType.OBJECT and e.id in moved
             and e.initial_state.get("icon") in QUEUE_ICONS]
    if len(queue) < QUEUE_MOVERS:
        return []
    return [f"scene {brief.scene_id}: {queue} are moved one by one to show queues: they pile up and leave the "
            f"frame; draw ONE LANES instead (its lanes delimited, each with its label and its \"rate\"), and drop these OBJECTs"]


COLUMN_GAP = 1.2          # scene units: a battery this close (in x) to the parts it feeds is in their column


def battery_in_column(brief):
    """A battery feeding several parts that stand in its own column (one above it, one below): its wires
    run over them and their labels."""
    position = {e.id: scene_point(e.position) for e in brief.entities if e.type.value in CIRCUIT_PARTS}
    errors = []
    for battery in (e for e in brief.entities if e.type == ComponentType.BATTERY):
        fed = {c.target_id if c.source_id == battery.id else c.source_id for c in brief.connections
               if battery.id in (c.source_id, c.target_id)}
        near = sorted(i for i in fed if i in position and abs(position[i][0] - position[battery.id][0]) < COLUMN_GAP)
        if len(fed) >= 2 and near:
            errors.append(f"scene {brief.scene_id}: the battery {battery.id} stands in the same column as {near}, which it "
                          f"feeds: its wires would run over them and their labels; put the battery on the left, at least "
                          f"2.5 units left of its branches, the branches one above the other on its right")
    return errors


def icons_only(brief, narration):
    """A scene whose narration gives numbers but which draws only icons and labels: they are named,
    not shown."""
    if not re.search(r"\d|%|pour ?cent", str(narration or "")) or not brief.entities:
        return []
    if any(e.type in SHOWS_VALUES or e.type.value in CIRCUIT_PARTS for e in brief.entities):
        return []
    return [f"scene {brief.scene_id}: the narration gives numbers, but the scene is only icons and labels: show "
            f"them (an AXES_GRAPH with a CURVE_PLOT of the quantity over time, a GAUGE with the value, a TEX_FORMULA)"]


def graph_span(graph):
    """The wider of an AXES_GRAPH's two ranges (graph units); 10 when unknown."""
    state = (graph.initial_state if graph else {}) or {}
    spans = [r[1] - r[0] for r in (state.get("x_range"), state.get("y_range"))
             if isinstance(r, (list, tuple)) and len(r) >= 2 and all(isinstance(v, (int, float)) for v in r[:2])]
    return max(spans) if spans else 10.0


def coherence_problems(brief, narration, duration=None) -> list:
    """What does not follow the narration (word cues, voltage / current / opening words), mixes two
    themes, labels one thing with another's name, or moves a body past the scene's end (`duration`).
    Messages for the LLM's retry."""
    where, errors = f"scene {brief.scene_id}", []
    for action in brief.actions:
        kind = action.get("action")
        if kind in MOTIONS and duration and isinstance(action.get("at"), (int, float)):
            default = 4 if kind == "move_along" else 2
            ends = action["at"] + float(action.get("duration", default) if isinstance(action.get("duration", default), (int, float)) else default)
            if ends > duration + 0.5:
                errors.append(f"{where}: {kind} of {action.get('target')} ends at {ends:g} s, after the scene's end "
                              f"({duration:g} s): cue it earlier or make it shorter, so the whole trip is seen")
    straight = sorted({a.get("target") for a in brief.actions if a.get("action") == "move"})
    closed = any(e.type == ComponentType.CURVE_PLOT and "x_func" in e.initial_state for e in brief.entities)
    if straight and not closed and any(word == "autour" for _, word in narration_words(narration)):
        errors.append(f"{where}: the narration says \"autour\" but {straight} only fall in a straight line: show "
                      f"the fall around the planet as an orbit (a CURVE_PLOT x_func / y_func on an AXES_GRAPH) with "
                      f"BODYs moved by move_along")
    things = [e.id for e in brief.entities if e.type in (ComponentType.OBJECT, ComponentType.BODY)]
    if things:
        for entity in brief.entities:
            if entity.type == ComponentType.VECTOR_ARROW and not entity.initial_state.get("anchor"):
                errors.append(f"{where}: the vector {entity.id} ({entity.initial_state.get('label')!r}) starts on nothing, "
                              f"in a scene with {things}: anchor it on what it acts on, \"anchor\": {{\"body\": \"<id>\"}} "
                              f"(or on a curve or a point of a graph)")
    graphs = {e.id: e for e in brief.entities if e.type in (ComponentType.AXES_GRAPH, ComponentType.CURVE_PLOT)}
    if graphs:
        errors += [f"{where}: move of {a.get('target')} in a scene with a graph: \"to\" is in scene units, not the "
                   f"graph's; draw the path as a CURVE_PLOT on the axes and move a BODY anchored on it with move_along"
                   for a in {a.get("target"): a for a in brief.actions if a.get("action") == "move"}.values()]
    points = anchored_points(brief, graphs)
    moving = {a.get("target") for a in brief.actions if a.get("action") in MOTIONS}
    for i, (a, graph, pa) in enumerate(points):    # things anchored on one graph: 60 px icons, discs, they must not stack
        for b, other, pb in points[i + 1:]:
            gap = math.dist(pa, pb)
            near = ANCHOR_GAP * graph_span(graphs.get(graph))
            if graph != other or gap >= near or (a in moving) != (b in moving):
                continue                           # apart, or one leaves the other (a cannonball its cannon)
            ride = (f"; they travel together: do not space them out (two separate things), make {b} ride in {a}: "
                    f"\"anchor\": {{\"body\": \"{a}\"}}, drop {b}'s own moves (its vectors keep their direction, "
                    f"CENTER and TANGENT included)") if a in moving else ""
            errors.append(f"{where}: {a} and {b} are anchored {gap:.2g} apart on {graph}: their drawings would "
                          f"overlap; put them at least {near:.2g} apart (graph units){ride}"
                          + ("" if ride else "; on a number line, narrow its x_range around these numbers "
                                             "or keep only those far enough apart"))
    errors += tiny_curves(brief, graphs)
    errors += idle_discs(brief, graphs)
    errors += queues_by_hand(brief)
    errors += gauges_without_value(brief)
    errors += placeholder_graphs(brief)
    errors += electrons_as_discs(brief)
    errors += battery_in_column(brief)
    errors += icons_only(brief, narration)
    errors += [f"{where}: {a} and {b} meet on {curve} around {when:g} s (one catches the other up): set them off "
               f"together, at the same speed (same \"at\", \"duration\" and distance), or keep them apart all along"
               for a, b, curve, when in curve_meetings(brief, graphs, duration)]
    at_point = {}
    for entity in brief.entities:          # two bodies at one point hide each other, their labels too
        anchor = entity.initial_state.get("anchor")
        if entity.type in (ComponentType.BODY, ComponentType.OBJECT) and isinstance(anchor, dict) and "body" not in anchor:
            key = json.dumps(anchor, sort_keys=True)
            if key in at_point:
                errors.append(f"{where}: {entity.id} and {at_point[key]} sit at the same point ({anchor}): they hide each "
                              f"other; give {entity.id} \"anchor\": {{\"body\": \"{at_point[key]}\"}} (it rides in it, "
                              f"drawn beside it, and goes with it) and drop its moves, or make them one body")
            at_point.setdefault(key, entity.id)
    words = narration_words(narration)
    types = {entity.id: entity.type for entity in brief.entities}
    present = set(types.values())
    actions = brief.actions
    for i, action in enumerate(actions):
        label = f"action #{i} ({action.get('action')} {action.get('target') or action.get('path') or ''})"
        if not str(action.get("cue") or "").strip():
            errors.append(f"{where}: {label} needs a \"cue\": the words of the narration it happens on")
        elif find_cue(words, action["cue"]) is None:
            errors.append(f"{where}: {label} has the cue {action['cue']!r}, which is not in the narration "
                          f"(copy 1 to 4 consecutive words exactly as written)")
    # What the narrator says, the picture does.
    if ComponentType.VOLTMETER_PROBES in present and said(words, VOLTAGE) and not any(
            a.get("action") == "measure" and cue_says(a, VOLTAGE_CUE) for a in actions):
        errors.append(f"{where}: the narration speaks of tension / volts: add a \"measure\" on the voltmeter, "
                      f"cued on those words")
    if {ComponentType.BATTERY, ComponentType.AMMETER} <= present and said(words, CURRENT) and not any(
            a.get("action") == "start_flow" and cue_says(a, FLOW_CUE) for a in actions):
        errors.append(f"{where}: the narration speaks of courant / débit: add a \"start_flow\" through the "
                      f"ammeter, cued on those words")
    opening = next((i for i, (_, word) in enumerate(words) if word.startswith(OPENING)), None)
    flow_before = any(a.get("action") == "start_flow" and (find_cue(words, a.get("cue")) or 0) < opening
                      for a in actions) if opening is not None else False
    if ComponentType.SWITCH in present and flow_before and not any(
            a.get("action") == "set_state" and types.get(a.get("target")) == ComponentType.SWITCH
            and isinstance(a.get("state"), dict) and a["state"].get("closed") is False and cue_says(a, OPENING)
            for a in actions):
        errors.append(f"{where}: the narration opens the circuit: add set_state {{\"closed\": false}} on the switch, "
                      f"cued on the opening words (the flow then stops)")
    # One theme per scene.
    if present & ANALOGY_TYPES and present & CIRCUIT_TYPES:
        errors.append(f"{where}: one theme per scene: an analogy ({sorted(t.value for t in present & ANALOGY_TYPES)}) "
                      f"and a circuit ({sorted(t.value for t in present & CIRCUIT_TYPES)}) in the same scene; keep "
                      f"the analogy for the whole scene and show the circuit in another one")
    for action in actions:
        if action.get("action") == "fade_out" and types.get(action.get("target")) in ANALOGY_TYPES:
            errors.append(f"{where}: {action['target']} fades out: an analogy stays on screen for the whole scene")
    if not said(words, OPENING):
        errors += [f"{problem}: the circuit is not closed and the narration never says it is open "
                   f"(close it, or show the ideas as icon cards without a circuit)" for problem in open_circuits(brief)]
    # Labels name their own target.
    data = brief.model_dump(mode="json")
    entities = {e["id"]: e for e in data["entities"]}
    symbols = {formula_symbol((e.get("initial_state") or {}).get("latex")) for e in data["entities"]
               if e["type"] == "TEX_FORMULA"} - {None}
    for arrow_id, target_id in annotation_targets(data).items():
        target = entities[target_id]
        own = (formula_symbol((target.get("initial_state") or {}).get("latex")) if target["type"] == "TEX_FORMULA"
               else INSTRUMENT_SYMBOLS.get(target["type"]))
        text = str((entities[arrow_id].get("initial_state") or {}).get("text") or "")
        if not own:
            continue
        if own in QUANTITIES and not names_quantity(text, own):     # only the quantities it knows by name
            errors.append(f"{where}: {arrow_id} ({text!r}) points at {target_id}, the formula of "
                          f"{' / '.join(QUANTITIES[own])} {own}: its text must name it "
                          f"(e.g. \"{QUANTITIES[own][0].capitalize()} {own}\")")
        errors += [f"{where}: {arrow_id} ({text!r}) points at {target_id} ({own}) but names {other}: never "
                   f"another quantity than its target's" for other in sorted(symbols - {own})
                   if re.search(rf"(?<!\w){other}(?!\w)", text)]
    return errors


def time_to_cues(brief, narration, duration):
    """Each action's "at" from its cue: where the cue's words fall in the narration, as a share of
    the scene (the renderer then moves it onto the spoken word). Actions on one cue follow each other
    SAME_CUE_STEP apart, in the brief's order; moves on one cue start together."""
    words, length = narration_words(narration), max(len(str(narration or "")), 1)
    position, last = 0, None
    for action in sorted(brief["actions"], key=lambda a: a.get("at", 0)):
        index = find_cue(words, action.get("cue"), position)
        if index is None:
            index = find_cue(words, action.get("cue"))
        if index is None:
            continue
        at = duration * words[index][0] / length
        if last and index == last[0]:
            at = last[1] if last[2] in MOTIONS and action.get("action") in MOTIONS else last[1] + SAME_CUE_STEP
        action["at"] = round(min(at, duration), 2)
        position, last = index, (index, action["at"], action.get("action"))
    brief["actions"].sort(key=lambda a: a.get("at", 0))


def flow_rules(brief, where, fixes):
    """A switch that opens stops every flow through it at once; a flow highlights its ammeters."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    actions = brief["actions"]
    flows = [a for a in actions if a.get("action") == "start_flow" and isinstance(a.get("path"), list)]
    for opening in [a for a in actions if a.get("action") == "set_state" and types.get(a.get("target")) == "SWITCH"
                    and isinstance(a.get("state"), dict) and a["state"].get("closed") is False]:
        for flow in [f for f in flows if opening["target"] in f["path"] and f["at"] <= opening["at"]]:
            stopped = any(a.get("action") == "stop_flow" and flow["at"] < a["at"] <= opening["at"] + 0.05
                          and a.get("path") in (None, flow["path"]) for a in actions)
            if not stopped:
                actions.append({"at": opening["at"], "action": "stop_flow", "path": flow["path"], "cue": opening.get("cue")})
                fixes.append(f"{where}: sync: the flow stops when {opening['target']} opens at {opening['at']} s")
    for flow in flows:
        for ammeter in [i for i in dict.fromkeys(flow["path"]) if types.get(i) == "AMMETER"]:
            if not any(a.get("action") == "set_state" and a.get("target") == ammeter and abs(a["at"] - flow["at"]) < 0.05
                       for a in actions):
                actions.append({"at": flow["at"], "action": "set_state", "target": ammeter,
                                "state": {"highlighted": True}, "cue": flow.get("cue")})
                fixes.append(f"{where}: sync: {ammeter} highlighted when the current starts at {flow['at']} s")
    actions.sort(key=lambda a: a.get("at", 0))


RIGID_GAP = 0.5          # bodies moving exactly together (rigid_moves): merged up to this share of the range


def rigid_moves(brief, body_id):
    """The moves of a body along its curve, as (when, cue, duration, how far): two bodies with the same
    list travel as one block, whatever the gap the LLM left between them."""
    anchor = next((e.initial_state.get("anchor") for e in brief.entities if e.id == body_id), None) or {}
    where = anchor.get("t", anchor.get("x"))
    moves = []
    for action in sorted((a for a in brief.actions if a.get("action") == "move_along" and a.get("target") == body_id),
                         key=lambda a: a.get("at", 0)):
        if not isinstance(where, (int, float)) or not isinstance(action.get("to"), (int, float)):
            return None
        moves.append((round(float(action.get("at", 0)), 2), action.get("cue"), action.get("duration", 4),
                      round(float(action["to"]) - float(where), 3)))
        where = action["to"]
    return moves


def merge_travellers(brief, data, where, fixes):
    """Two BODYs anchored on one curve, both moving along it, closer than ANCHOR_GAP, or than
    RIGID_GAP when they move exactly together (rigid_moves: the station and its astronaut, spaced out
    by the LLM even when told to make one ride in the other, just past the ANCHOR_GAP check): the
    second rides in the first, "anchor": {"body": <first>}, and its own moves are dropped; its
    vectors stay, TANGENT / CENTER included (agent010 draws them from it, turning with its host), and
    what rode in it (a scale) rides in the first one too. Only when the scene still validates."""
    graphs = {e.id: e for e in brief.entities if e.type in (ComponentType.AXES_GRAPH, ComponentType.CURVE_PLOT)}
    moving = {a.get("target") for a in brief.actions if a.get("action") == "move_along"}
    on_curve = {e.id for e in brief.entities if e.type == ComponentType.BODY and "curve" in (e.initial_state.get("anchor") or {})}
    points, merged = [p for p in anchored_points(brief, graphs) if p[0] in on_curve & moving], set()
    for i, (a, graph, pa) in enumerate(points):
        for b, other, pb in points[i + 1:]:
            same = rigid_moves(brief, a)
            gap = RIGID_GAP if same and same == rigid_moves(brief, b) else ANCHOR_GAP
            if a in merged or b in merged or graph != other or math.dist(pa, pb) >= gap * graph_span(graphs.get(graph)):
                continue
            candidate = copy.deepcopy(data)
            for entity in candidate["entities"]:
                anchor = entity["initial_state"].get("anchor")
                if entity["id"] == b:
                    entity["initial_state"]["anchor"] = {"body": a}
                elif entity["type"] != "VECTOR_ARROW" and isinstance(anchor, dict) and anchor.get("body") == b:
                    entity["initial_state"]["anchor"] = {"body": a}     # what rode in it: in the host now
            candidate["actions"] = [x for x in candidate["actions"] if not (x.get("target") == b and x.get("action") in MOTIONS)]
            try:
                SceneVisualBrief.model_validate(candidate)
            except ValidationError:
                continue
            data.clear()
            data.update(candidate)
            merged.add(b)
            fixes.append(f"{where}: travellers: {b} rides in {a} (they move together on {graph}, "
                         f"{math.dist(pa, pb):.2g} apart), its own moves dropped")


def finished_brief(brief, narration, duration, fixes):
    """The brief as JSON, travellers merged, timed on the narration's words, with the flow rules and
    target first applied."""
    data = brief.model_dump(mode="json")
    where = f"scene {data['scene_id']}"
    merge_travellers(brief, data, where, fixes)
    time_to_cues(data, narration, duration)
    flow_rules(data, where, fixes)
    target_first_timing(data, annotation_targets(data), where, fixes)
    return data


# ---- layout templates: which page agent010 draws each scene on, and the variety rules

# Eligibility comes from the script, deterministically: a template is never imposed on a scene whose
# narration does not call for it.
#   analogy_fullscreen  the scene's narration makes an explicit analogy (ANALOGY_WORDS)
#   comparison          the scene's narration opposes two notions (OPPOSITION_WORDS)
#   circuit             always (the default)
# A scene with an instrument (VOLTMETER_PROBES) stays "circuit": only that page has the instrument column.
# Variety, as far as eligibility allows: at most ceil(N / 2) "circuit" scenes; at least one
# "analogy_fullscreen" if a scene may have it, one "comparison" likewise; never the same template
# twice in a row. A rule that eligibility makes impossible (two consecutive scenes that can only be
# "circuit") is not asked for.
# Explicit analogies only: "imaginons", "comme un", "de même" also open thought experiments and
# plain comparisons ("Imaginons un circuit série"), which are no analogy to draw full screen.
ANALOGY_WORDS = re.compile(r"analogi|château d.eau|péage|c.est comme|comme si\b|à la manière d|tel(?:le)? (?:un|une)\b|"
                           r"\btuyau|robinet|rivière|cascade|\bpompe\b", re.IGNORECASE)
OPPOSITION_WORDS = re.compile(r"contrairement|au contraire|à l.inverse|alors que|tandis que|ce qu.on croit|en réalité|"
                              r"\bversus\b|\bvs\b|d.un côté|de l.autre|par opposition|plutôt que|deux branches|"
                              r"compar(?:ons|er|aison)|confondre|distinct", re.IGNORECASE)
CIRCUIT_PARTS = {"BATTERY", "LAMP", "SWITCH", "AMMETER", "WIRE_BUS", "EARTH_GROUND", "CHASSIS_MASS"}


def circuit_cap(scene_count):
    return math.ceil(scene_count / 2)


def layout_eligibility(narrations):
    """{scene_id: [the templates its narration allows]} ("circuit" always first)."""
    return {scene_id: ["circuit"] + (["comparison"] if OPPOSITION_WORDS.search(text or "") else [])
                      + (["analogy_fullscreen"] if ANALOGY_WORDS.search(text or "") else [])
            for scene_id, text in narrations.items()}


def needs_circuit(briefs):
    """Scenes that must stay "circuit": they have an instrument, drawn only in its column."""
    return {scene_id for scene_id, brief in briefs.items()
            if any(entity.type == ComponentType.VOLTMETER_PROBES for entity in brief.entities)}


def layout_options(scene_id, eligible, locked):
    return ["circuit"] if scene_id in locked else eligible[scene_id]


def layout_problems(order, templates, eligible, locked) -> list:
    """What breaks the layout rules (see above), as messages for the LLM's retry. Only what the
    script makes possible is asked for."""
    errors, options = [], {i: layout_options(i, eligible, locked) for i in order}
    for scene_id in order:
        template = templates.get(scene_id)
        if template not in LAYOUT_TEMPLATES:
            errors.append(f"scene {scene_id}: \"layout_template\" must be one of {list(LAYOUT_TEMPLATES)}, got {template!r}")
        elif template not in options[scene_id]:
            why = ("it has a VOLTMETER_PROBES (only \"circuit\" has the instrument column)" if scene_id in locked
                   else "its narration makes no explicit analogy" if template == "analogy_fullscreen"
                   else "its narration opposes no two notions")
            errors.append(f"scene {scene_id}: {template!r} is not allowed: {why}; allowed: {options[scene_id]}")
    flexible = sum(len(options[i]) > 1 for i in order)
    cap = max(circuit_cap(len(order)), len(order) - flexible)       # never below what eligibility allows
    circuits = sum(templates.get(i) == "circuit" for i in order)
    if circuits > cap:
        errors.append(f"{circuits} scenes are \"circuit\", at most {cap}: give an allowed other template to some")
    for template, label in (("analogy_fullscreen", "makes an analogy"), ("comparison", "opposes two notions")):
        possible = [i for i in order if template in options[i]]
        if possible and not any(templates.get(i) == template for i in order):
            errors.append(f"no scene is {template!r}, though scene(s) {possible} {label}: use it on one of them")
    for a, b in zip(order, order[1:]):
        if templates.get(a) == templates.get(b) and (len(options[a]) > 1 or len(options[b]) > 1):
            errors.append(f"scenes {a} and {b} are both {templates.get(a)!r}: never the same template twice in a row")
    return errors


def comparison_sides(brief):
    """Which panels of a comparison have something of their own: "A" (x < 0), "B" (x > 0). Badges
    and anchored things (riding, on a curve or a graph) follow what they belong to, so they do not count."""
    sides = set()
    for entity in brief.entities:
        if entity.type == ComponentType.ARROW_ANNOTATION or entity.initial_state.get("anchor") or entity.type == ComponentType.CURVE_PLOT:
            continue
        x = scene_point(entity.position)[0]
        sides |= {"A"} if x < 0 else {"B"} if x > 0 else set()
    return sides


def crossing_wires(brief):
    """The connections of a comparison going from one panel to the other: a circuit cut in two."""
    side = {e.id: ("A" if scene_point(e.position)[0] < 0 else "B") for e in brief.entities
            if not e.initial_state.get("anchor")}
    return [f"{c.source_id}-{c.target_id}" for c in brief.connections
            if c.source_id in side and c.target_id in side and side[c.source_id] != side[c.target_id]]


def comparison_problem(brief):
    """Why this scene cannot be a "comparison" as drawn, or None: a panel with nothing of its own (it
    compares nothing), or a circuit wired across the two panels (cut in two by the frame)."""
    missing = {"A", "B"} - comparison_sides(brief)
    if missing:
        return (f"nothing in panel {' or '.join(sorted(missing))} (A: x < 0, B: x > 0): draw each side's thing "
                f"in its panel, or use another template")
    crossing = crossing_wires(brief)
    if crossing:
        return (f"wires {crossing[:3]} go from one panel to the other: a circuit belongs in one panel (or use "
                f"\"circuit\"); each panel shows one side of the comparison")
    return None


def empty_panels(briefs, templates) -> list:
    """A "comparison" that compares nothing (an empty panel) or cuts a circuit in two."""
    errors = []
    for scene_id, template in templates.items():
        brief = briefs.get(scene_id)
        problem = comparison_problem(brief) if template == "comparison" and brief is not None else None
        if problem:
            errors.append(f"scene {scene_id}: \"comparison\" with {problem}")
    return errors


def change_cost(brief, template):
    """How much a scene loses by leaving "circuit" (lower = less critical): its wires and circuit
    parts; a comparison also needs something on each side."""
    if template == "circuit":
        return 0
    cost = 2 * len(brief.connections) + sum(entity.type.value in CIRCUIT_PARTS for entity in brief.entities)
    if template == "comparison":
        cost += 0 if comparison_problem(brief) is None else 5
    return cost


def force_layouts(order, proposed, eligible, locked, briefs):
    """The final templates: the LLM's where they follow the rules; then only two things are forced:
    a template the scene does not allow goes back to "circuit", and a missing analogy / comparison
    goes on the eligible scene that loses least (change_cost). The circuit cap and the repeats are
    asked of the LLM but never forced: filling them would put an analogy or a comparison on a
    scene that has none; what is left is reported (layout_problems). Returns (templates, [why each change])."""
    options = {i: layout_options(i, eligible, locked) for i in order}
    templates, forced = {}, []

    def put(scene_id, template, why):
        forced.append(f"scene {scene_id}: {templates.get(scene_id) or proposed.get(scene_id)!r} -> {template!r} ({why})")
        templates[scene_id] = template

    for scene_id in order:
        templates[scene_id] = proposed.get(scene_id)
        if templates[scene_id] not in options[scene_id]:
            put(scene_id, "circuit", "not allowed for this scene" if templates[scene_id] in LAYOUT_TEMPLATES else "missing or unknown")
    for scene_id in order:              # an empty panel or a circuit cut in two: better no comparison
        problem = comparison_problem(briefs[scene_id]) if templates[scene_id] == "comparison" and scene_id in briefs else None
        if problem:
            put(scene_id, "circuit", f"the comparison would show {re.split(r' [(]|:', problem)[0]}")
    for template in ("analogy_fullscreen", "comparison"):
        possible = [i for i in order if template in options[i]
                    and (template != "comparison" or (i in briefs and comparison_problem(briefs[i]) is None))]
        if possible and template not in templates.values():
            scene_id = min(possible, key=lambda i: (templates[i] != "circuit", change_cost(briefs[i], template)))
            put(scene_id, template, f"the script calls for at least one {template!r}")
    return templates, forced


def footage_problems(order, briefs, layouts, expected=False):
    """A film asked for on another scene than the hook, a query that is not a few words, too much
    drawn over the film, or (`expected`: a channel of FOOTAGE_DOMAINS) a hook without one."""
    errors = []
    if expected and order and (layouts.get(order[0]) or {}).get("footage") is None:
        errors.append(f"scene {order[0]}: the hook has no film: give it \"footage\": {{\"query\": \"<1 to 4 French words "
                      f"of the real sight the question starts from>\"}}, and keep at most {MAX_OVER_FOOTAGE} things drawn over it")
    for scene_id in order:
        wanted = (layouts.get(scene_id) or {}).get("footage")
        if wanted is None:
            continue
        if scene_id != order[0]:
            errors.append(f"scene {scene_id}: \"footage\" is for the first scene (the hook) only: drop it here")
        elif query_problem(wanted):
            errors.append(f"scene {scene_id}: {query_problem(wanted)}")
        elif len(briefs[scene_id].entities) > MAX_OVER_FOOTAGE:
            errors.append(f"scene {scene_id}: {len(briefs[scene_id].entities)} things drawn over the film: keep at most "
                          f"{MAX_OVER_FOOTAGE} (the question as a status badge, a formula, one key icon); the film shows the setting")
    return errors


FOOTAGE_CHOICE = """You pick the real film shown behind the opening of a French educational video, behind its
question. What the narration says over it:
{narration}

Pixabay's clips for the search {query!r}, each by its tags (what the clip shows) and length:
{candidates}

Answer with JSON only: {{"choice": <the number of the clip that shows the narration's real subject, as it is>}},
or {{"choice": null}} when none does. A clip that shows something else, or the subject's look-alike, is
misleading and must not be picked: an oil lamp for an electric lamp, another planet or moon for the Moon,
a keyboard for a job centre. People may be in it, far off or from behind, never a face in the foreground
(a portrait, a close-up). Better no film than a wrong one."""


def clip_chooser(narration):
    """footage.find_clip's chooser: the LLM reads the candidates' tags against the hook's narration.
    Its answer is a number checked against the list; anything else picks nothing."""
    def choose(query, candidates):
        listed = "\n".join(f"{n}. tags: {c['tags']}; {c['duration']} s" for n, c in enumerate(candidates, start=1))
        try:
            answer = parse_llm_json(llm_call(FOOTAGE_CHOICE.format(narration=narration[:1200], query=query, candidates=listed)))
        except Exception as exc:      # no answer, no JSON: no film rather than an unchecked one
            print(f"--- {AGENT}: film not chosen ({type(exc).__name__})", file=sys.stderr, flush=True)
            return None
        pick = answer.get("choice") if isinstance(answer, dict) else None
        return pick - 1 if type(pick) is int and 1 <= pick <= len(candidates) else None
    return choose


def checked_footage(order, layouts, narrations, find=None):
    """The hook's film, found now and chosen for its narration (cached in assets/footage/index.json,
    where agent010 finds it); none fits, or none can be found: the hook is drawn without one.
    Returns what happened, for the report ({} without a film asked for)."""
    hook = order[0] if order else None
    wanted = (layouts.get(hook) or {}).get("footage")
    if hook is None or wanted is None or query_problem(wanted):
        return {}
    query = clean_query(wanted["query"])
    try:
        clip = (find or film.find_clip)(query, clip_chooser(narrations.get(hook, "")))
        return {"query": query, "clip": film.credit(clip)}
    except film.FootageError as exc:
        layouts[hook] = {k: v for k, v in layouts[hook].items() if k != "footage"}
        print(f"--- {AGENT}: the hook has no film: {exc}", file=sys.stderr, flush=True)
        return {"query": query, "dropped": str(exc)[:200]}


CHANGES = ("set_state", "start_flow", "set_value", "measure", "move_along", "move")   # actions that show something happen
DRAWN_IN = (ComponentType.TEX_FORMULA, ComponentType.AXES_GRAPH)   # written or traced before the eyes: not still
STILL_MIN_SEC = 8


def still_scenes(order, briefs, layouts, durations):
    """Scenes where nothing happens but things appearing and being highlighted: icons named one after
    the other, the idea never shown at work. A hook over a film, or a scene writing a formula or
    tracing a graph, is not still."""
    errors = []
    for scene_id in order:
        brief = briefs.get(scene_id)
        if brief is None or not brief.entities or float(durations.get(scene_id) or 0) < STILL_MIN_SEC:
            continue
        if (scene_id == order[0] and (layouts.get(scene_id) or {}).get("footage")) \
                or any(e.type in DRAWN_IN for e in brief.entities) or any(a.get("action") in CHANGES for a in brief.actions):
            continue
        errors.append(f"scene {scene_id}: nothing happens on screen but things appearing and being highlighted: show the "
                      f"narration's idea at work (move what it moves in or out, set_state / set_value what changes, "
                      f"start_flow what flows), cued on the words that say it")
    return errors


def scene_footage(scene_id, order, layout):
    """The storyboard scene's "footage" field: the hook's, when its query is valid."""
    wanted = (layout or {}).get("footage")
    if scene_id != order[0] or query_problem(wanted):
        return {}
    return {"footage": {"query": clean_query(wanted["query"])}}


def panel_titles(layout, template):
    """The comparison's two panel titles, when the LLM gave them (short text, kept as is)."""
    titles = (layout or {}).get("panel_titles")
    if template != "comparison" or not isinstance(titles, list) or len(titles) != 2:
        return {}
    return {"panel_titles": [str(t)[:40] for t in titles]}


def log_layouts(report, problems_after_retries):
    """What was allowed, proposed by the LLM, and finally kept, and why anything was forced (stderr)."""
    say = lambda line: print(f"--- {AGENT}: {line}", file=sys.stderr, flush=True)
    say("layout templates allowed by the script: " + "; ".join(f"{i}: {'/'.join(t)}" for i, t in report["allowed"].items()))
    say("layout templates proposed by the LLM:   " + ", ".join(f"{i}: {t}" for i, t in report["proposed"].items()))
    say("layout templates kept:                  " + ", ".join(f"{i}: {t}" for i, t in report["final"].items()))
    if problems_after_retries:
        say(f"still wrong after {MAX_ATTEMPTS} attempts, forced: " + "; ".join(problems_after_retries))
    for line in report["forced"]:
        say(f"forced: {line}")
    for line in report["problems_left"]:
        say(f"layout variety not reached (not forced): {line}")


def sanitize(raw_scenes):
    """Small fixes before validation: scene_id as a string, and clear_previous=true on every text
    overlay that does not say otherwise (the schema default, written out explicitly)."""
    for scene in raw_scenes:
        if isinstance(scene, dict):
            if "scene_id" in scene:
                scene["scene_id"] = str(scene["scene_id"])
            if isinstance(scene.get("text_overlay"), dict):
                scene["text_overlay"].setdefault("clear_previous", True)
    return raw_scenes


def parse_storyboard(text, durations, narrations):
    """LLM answer -> ({scene_id: SceneVisualBrief}, {scene_id: {"layout_template", "panel_titles"}}).
    The layout fields belong to the storyboard scene, not to the brief (whose schema forbids extra
    fields): they are taken out first. Raises ValueError with every problem found in the briefs."""
    answer = parse_llm_json(text)
    raw_scenes = answer.get("scenes") if isinstance(answer, dict) else answer
    if not isinstance(raw_scenes, list):
        raise ValueError('the answer must be {"scenes": [...]}')
    layouts = {str(scene.get("scene_id")): {"layout_template": scene.pop("layout_template", None),
                                            "panel_titles": scene.pop("panel_titles", None),
                                            "footage": scene.pop("footage", None)}
               for scene in raw_scenes if isinstance(scene, dict)}
    try:
        briefs = BRIEFS.validate_python(sanitize(raw_scenes))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    errors = validate_storyboard_topology(briefs, durations)
    missing = sorted(set(durations) - {brief.scene_id for brief in briefs})
    if missing:
        errors.append(f"missing a brief for scene_id {missing}")
    if errors:
        raise ValueError("\n".join(errors))
    return {brief.scene_id: brief for brief in briefs}, layouts


def qa_feedback_section():
    """The prompt section with the QA's corrections, from LBREEZE_QA_FEEDBACK (app/qa_feedback.py; the
    only channel: this agent never reads qa.json). Returns (section, summary for the logs); ("", None)
    when the variable is missing, not valid JSON, or empty."""
    return feedback_section(AGENT, "storyboard")


def ask_for_storyboard(scenes_for_prompt, qa_section="", measure=None, footage_expected=False):
    """Call the LLM until its answer is right. Two kinds of problems, both sent back for a retry
    (MAX_ATTEMPTS calls in all):
      - blocking: the JSON, the schema, the topology (unknown ids, ports, actions, times...): an
        answer with any is never used;
      - advisory: coherence with the narration (coherence_problems), the layout templates
        (layout_problems) and, given `measure` (run: app/render/layout_check.py), what the
        renderer's page would still find overlapping or out of the frame: an answer with some is
        kept if no better one comes.
    Returns ({scene_id: brief}, {scene_id: layout fields}, attempts, coherence problems left, layout
    problems left), from the usable answer with the fewest advisory problems. Raises RuntimeError
    if llm_call fails (no point retrying a quota or network error) or if no answer is usable."""
    durations = {s["scene_id"]: s["duration_sec"] for s in scenes_for_prompt}
    narrations = {s["scene_id"]: s["narration_text"] for s in scenes_for_prompt}
    order = [s["scene_id"] for s in scenes_for_prompt]
    eligible = layout_eligibility(narrations)
    prompt = PROMPT.format(object_icons=", ".join(OBJECT_ICON_NAMES), maths=", np.".join(SAFE_MATH_FUNCTIONS), components=COMPONENTS_FOR_PROMPT, positions=", ".join(SEMANTIC_POSITIONS),
                           max_entities=MAX_ENTITIES, max_formulas=MAX_FORMULAS, max_over_footage=MAX_OVER_FOOTAGE, max_circuit=circuit_cap(len(order)),
                           layout_eligibility="\n".join(f"  scene {i}: {', '.join(eligible[i])}" for i in order),
                           actions=", ".join(ACTIONS), schema=json.dumps(SceneVisualBrief.model_json_schema()),
                           scenes=json.dumps(scenes_for_prompt, ensure_ascii=False))
    prompt = prompt.replace("\n\nAnswer with JSON only", qa_section + "\n\nAnswer with JSON only", 1)
    errors, best = "", None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text = llm_call(prompt + (RETRY_NOTE.format(errors=errors) if errors else ""))
        try:
            briefs, layouts = parse_storyboard(text, durations, narrations)
        except ValueError as exc:  # bad JSON, schema errors, topology errors
            errors = str(exc)[:MAX_ERROR_CHARS]
            continue
        coherence = [e for brief in briefs.values()
                     for e in coherence_problems(brief, narrations.get(brief.scene_id, ""), durations.get(brief.scene_id))]
        proposed = {i: (layouts.get(i) or {}).get("layout_template") for i in order}
        layout = layout_problems(order, proposed, eligible, needs_circuit(briefs)) + empty_panels(briefs, proposed)
        coherence += footage_problems(order, briefs, layouts, footage_expected) + still_scenes(order, briefs, layouts, durations)
        if measure:                     # laid out as the renderer will, with the templates it will get
            templates = force_layouts(order, proposed, eligible, needs_circuit(briefs), briefs)[0]
            titles = {i: panel_titles(layouts.get(i), templates[i]).get("panel_titles") for i in order}
            coherence += measure(order, briefs, templates, titles, durations)
        if best is None or len(coherence) + len(layout) < len(best[3]) + len(best[4]):
            best = (briefs, layouts, attempt, coherence, layout)
        if not coherence and not layout:
            return best
        errors = "\n".join(coherence + layout)[:MAX_ERROR_CHARS]
    if best:
        return best[:2] + (MAX_ATTEMPTS,) + best[3:]     # attempts: every call was made
    raise RuntimeError(f"no valid storyboard after {MAX_ATTEMPTS} attempts; last errors: {errors[:500]}")


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    output_path = os.path.join(folder, "storyboard.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["script.json"])
    qa_section, qa_feedback = qa_feedback_section()
    if qa_feedback:
        print(f"--- {AGENT}: QA feedback (revision {qa_feedback['revision']}): {qa_feedback['blocking_issues']} "
              f"blocking issue(s){', with rejection notes' if qa_feedback['rejection_notes'] else ''}: added to the prompt",
              file=sys.stderr, flush=True)
    script = load_json(os.path.join(folder, "script.json"))
    if not script.get("scenes"):
        return finish(channel_id, AGENT, "storyboard", "critical", output_path, error="missing script.json")

    renderer = settings.get("render_backend_by_channel", {}).get(channel_id) or "html"
    if renderer == "manim":                   # the Manim renderer is retired: agent010 draws every storyboard
        renderer = "html"
    if renderer not in KNOWN_RENDERERS:
        return finish(channel_id, AGENT, "storyboard", "critical", output_path, error=f"unknown renderer {renderer!r}")

    scenes_for_prompt = [{"scene_id": str(s["scene_id"]),
                          "duration_sec": scene_field(s, "duration_sec", "duration_seconds"),
                          "narration_text": scene_field(s, "narration_text", "narration"),
                          "key_visual_moment": scene_field(s, "key_visual_moment", "visual_intent")}
                         for s in script["scenes"]]
    def measure(order, briefs, templates, titles, durations):
        try:
            from app.agent.agent010_html_renderer import channel_style    # the channel's theme: its sizes and fonts
            return measured_conflicts(order, briefs, templates, titles, durations, channel_style(channel_id),
                                      settings.get("burn_subtitles", True))
        except Exception as exc:        # no Chromium here: agent010 will say so; the storyboard is still checked
            print(f"--- {AGENT}: layout not measured ({type(exc).__name__}: {str(exc)[:120]})", file=sys.stderr, flush=True)
            return []

    try:
        briefs, layouts, attempts, coherence_left, layout_left = ask_for_storyboard(
            scenes_for_prompt, qa_section, None if renderer == "skip" else measure,
            (find_route(routes, channel_id) or {}).get("domain") in FOOTAGE_DOMAINS)
    except RuntimeError as exc:
        return finish(channel_id, AGENT, "storyboard", "critical", output_path, error=str(exc))
    order = [s["scene_id"] for s in scenes_for_prompt]
    eligible = layout_eligibility({s["scene_id"]: s["narration_text"] for s in scenes_for_prompt})
    proposed = {i: (layouts.get(i) or {}).get("layout_template") for i in order}
    templates, forced = force_layouts(order, proposed, eligible, needs_circuit(briefs), briefs)
    layout_report = {"allowed": {i: eligible[i] for i in order}, "proposed": proposed, "final": templates,
                     "forced": forced, "problems_left": layout_problems(order, templates, eligible, needs_circuit(briefs))}
    log_layouts(layout_report, layout_left)
    footage_report = {} if renderer == "skip" else checked_footage(
        order, layouts, {s["scene_id"]: s["narration_text"] or "" for s in scenes_for_prompt})
    for problem in coherence_left:
        print(f"--- {AGENT}: kept despite (narration coherence, after {MAX_ATTEMPTS} attempts): {problem}",
              file=sys.stderr, flush=True)

    # One storyboard scene per script scene, in script order.
    storyboard, sync_fixes = {"scenes": []}, []
    for scene in script["scenes"]:
        storyboard["scenes"].append({
            "scene_id": scene["scene_id"],
            "renderer": renderer,
            "visual_brief": finished_brief(briefs[str(scene["scene_id"])], scene_field(scene, "narration_text", "narration"),
                                           scene_field(scene, "duration_sec", "duration_seconds"), sync_fixes),
            "layout_template": templates[str(scene["scene_id"])],
            **panel_titles(layouts.get(str(scene["scene_id"])), templates[str(scene["scene_id"])]),
            **scene_footage(str(scene["scene_id"]), order, layouts.get(str(scene["scene_id"]))),
            "aspect_ratio": "16:9",  # YouTube landscape; the only platform enabled at launch
            "transition_in": "fade",
            "transition_out": "cut",
        })
    save_json(output_path, storyboard)
    provenance.register_artifact(run_id, channel_id, "storyboard.json", AGENT)

    not_closed = [problem for brief in briefs.values() for problem in open_circuits(brief)]
    status = "healthy" if attempts == 1 and not not_closed and not coherence_left else "not_healthy"
    return finish(channel_id, AGENT, "storyboard", status, output_path,
                  data={"renderer": renderer, "scenes": len(storyboard["scenes"]), "attempts": attempts,
                        "actions": sum(len(b.actions) for b in briefs.values()), "open_circuits": not_closed,
                        "sync_fixes": sync_fixes, "layout_templates": layout_report, "qa_feedback": qa_feedback,
                        "coherence_left": coherence_left, "footage": footage_report})


if __name__ == "__main__":
    run_standalone(run)
