"""
INPUT:  instance/{channel_id}/script.json + storyboard.json (from agent004) + research.json
        + routes (the channel's domain) + settings.qa_strict_mode
OUTPUT: instance/{channel_id}/qa.json = {verdict: "pass"|"reject", status: "healthy"|"warning"|"not_healthy",
        scores:{accuracy, simplicity, clarity}, rejection_notes, reject_to: "agent003"|"agent004"|null,
        issues: [{scene_id, text, kind, severity: "blocking"|"corrected"|"informative", fixed_by}],
        blocking_count, corrected_count, informative_count, corrections: [...], unsupported: [...]}
        (verdict vs status: see score_status(); severity, in observation mode: see issue_severities())
        + instance/{channel_id}/storyboard.json, auto-corrected in place.
NOTES:  Pedagogical and scientific QA judge, in two layers, applied in this order:
          1. LLM review against the channel domain's rules (electronics, physics, maths, economics):
             scores, plus corrections as small patches (overlay text, labels, arrow directions,
             states, actions). Each patch is validated; one that would break the brief is dropped.
             What the visual vocabulary cannot show at all (no light cone or bar chart type yet)
             is listed in "unsupported" instead of being faked.
          2. Deterministic circuit fixes, in code: ammeters in series, every flow on a closed loop
             (missing wires added between consecutive components of its path), no dead-end wire,
             switches closed before current crosses them, current stopped when a switch opens,
             a lamp lit only while current flows through it.
          3. Spatial arbiter (app/layout_solver.py, solve_layout): zones, orphan arrows, formula
             bands, title zone and box collisions, on boxes estimated in 1920 x 1080 pixels. What
             it cannot resolve is listed in qa.json under "layout_conflicts".
        The corrected storyboard is re-validated against the schema before it is saved.
        The ONLY agent that may return "revision_needed": scores are /10; with qa_strict_mode all
        three must be >= 7 to pass (without it the verdict is always "pass"). Visual problems are
        corrected here; a reject goes to agent003 only when the LLM says the script itself is
        wrong, otherwise to agent004 (the visuals are redone, the script is kept).
HEALTH: not_healthy if any score is exactly 7 (or below 7 when strict mode is off), something in
        the narration cannot be shown with the current components ("unsupported"), or the layout
        still has conflicts ("layout_conflicts");
        critical if an input is missing, the storyboard is invalid, or llm_call fails.
        "Reject after max_revisions" is turned into critical by the orchestrator.
"""

import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from pydantic import ValidationError

from app.agent import channel_dir, finish, find_route, llm_call, load_json, parse_llm_json, run_standalone, save_json
from app import provenance
from app.layout_solver import solve_layout
from models.visual_brief_schema import (COMPONENT_PORTS, ComponentType, SceneVisualBrief, direction_problem, measure_problem,
                                        emphasis_problem, move_problem)

AGENT = "agent005"
PASS_SCORE = 7             # a score at this level passes, with a warning; below it fails
SWITCH_LEAD_SEC = 0.6      # an inserted "close the switch" comes this long before the flow
LAMP_DELAY_SEC = 0.5       # a lamp lights up this long after current starts through it

# Domain rules from the brief; the channel's domain picks which ones the LLM applies.
DOMAIN_RULES = {
    "electronics": """ELECTRONICS:
- Current flows only around a complete closed circuit; never across an open switch.
- An ammeter is always in series (in the loop); a voltmeter is in parallel, across two terminals.
- Never a single wire left floating (a component connected by only one of its two ports).
- Measured values are read on instruments (AMMETER for a current, VOLTMETER_PROBES with a "measure"
  across two pins for a voltage), never shown as loose text.
- Probe polarity: target_pin_a is the red probe (V+), target_pin_b the black one (COM, reference);
  the reading is V(a) - V(b), so it is negative when the red probe is on the lower potential.
- Ground symbols: CHASSIS_MASS is the circuit's ground / 0 V reference, EARTH_GROUND the protective
  earth; an optional link between them is a dashed connection. No water metaphors in a circuit.""",
    "physics": """PHYSICS (mechanics and fluids):
- Force vectors point the way the force acts: weight/gravity always points DOWN; they match the motion.
- A fluid flows only through an open valve and connected pipes.""",
    "math": """MATHEMATICS:
- A plotted function must match its formula (linear = straight line, quadratic = parabola,
  exponential = ever steeper curve).
- Coordinate frames have a clear origin and correctly oriented axes (x to the right, y up).""",
    "economics": """ECONOMICS:
- Supply curves slope upward; demand curves slope downward.
- A price increase comes from a rightward demand shift or a leftward supply shift.
- A balance scale tilts toward the heavier factor (e.g. more money supply -> lower purchasing power).""",
}
DOMAIN_GROUPS = {"electronics": ["electronics"], "physics_math": ["physics", "math"], "math": ["math"],
                 "economics": ["economics"]}

ACTIONS = ("spawn", "set_state", "start_flow", "stop_flow", "fade_out", "set_value", "measure", "move_along", "move",
           "emphasize")
STATE_KEYS = ("on", "closed", "active", "reading", "spinning", "highlighted", "dimmed", "level")
INITIAL_STATE_KEYS = STATE_KEYS + ("label", "text", "direction", "max", "func", "latex", "axes", "x_range",
                                   "y_range", "x_label", "y_label", "length", "size", "target", "kind",
                                   "x_func", "y_func", "t_min", "t_max", "anchor", "icon", "symbol", "tone")
VOCABULARY = "\n".join(f"  * {t.value}: ports {list(p) if p else 'none'}" for t, p in COMPONENT_PORTS.items())

PROMPT = """ROLE: You are the lead pedagogical QA judge of an educational animation studio. You review a
French video plan for scientific and pedagogical errors, score it, and correct the storyboard.

DOMAIN RULES TO ENFORCE:
{rules}

RESEARCH (the facts the video must respect): {research}
SCRIPT (narration, one entry per scene): {script}
STORYBOARD (one visual brief per scene, drawn by a deterministic renderer): {storyboard}

THE RENDERER CAN ONLY DRAW THESE COMPONENT TYPES:
{vocabulary}
ARROW_ANNOTATION.initial_state: "direction" (where it points: UP, DOWN, LEFT, RIGHT, or [dx, dy] when tilted,
e.g. [0.4, 0.9] for an axis 23.5° from the vertical) and "text".
States: LAMP {{"on": bool}}, SWITCH {{"closed": bool}}, BATTERY {{"active": bool}}, AMMETER
{{"reading": amps}}, PEDAL_CRANK / SPROCKET {{"spinning": bool}}, icon types (WATER_TANK, COINS...)
{{"active": bool}}; any component {{"highlighted": bool}}.
CURVE_PLOT.initial_state.func is a Python expression of x (np.sin(x), 0.5 * x**2...), or, for a closed curve
(circle, orbit, ellipse), x_func and y_func are expressions of t, with t_min / t_max (default 0 and 2*pi):
a circle is x_func "2*np.cos(t)", y_func "2*np.sin(t)". So a circle or an orbit IS representable: a sine
standing for one is an error to fix, not a renderer limit. A VECTOR_ARROW can start ON a curve:
initial_state.anchor {{"curve": "<CURVE_PLOT id>", "t": <t>}} (or "x" for y = f(x)), with direction
"TANGENT" (velocity), "CENTER" (gravity towards an orbit's centre) or "OUTWARD": a velocity or a force
floating off its orbit is fixed by a set_initial_state patch on "anchor" (then "direction"), not a
renderer limit. A BODY (a disc: satellite, planet, ball) anchored on a curve travels along it with the
action {{"action": "move_along", "target": <BODY id>, "to": <t or x>, "duration": <s>}}, and a vector
with anchor {{"body": <BODY id>}} rides on it: a moving satellite IS representable. A thing moving in a
straight line (an elevator falling, a car) needs no graph: {{"action": "move", "target": <OBJECT or BODY id,
not anchored>, "to": [x, y] (scene point), "duration": <s>, "easing": "fall" (speeds up) | "smooth" |
"linear"}}. A BODY or OBJECT with anchor {{"body": <id>}} rides in that one (drawn beside it, goes with it):
two bodies at one point (the ISS and its astronaut stacked) are fixed by a patch giving the second that
anchor, then removing its own moves. A force or a velocity of a drawn OBJECT or BODY drawn as a free arrow
(starting on nothing, or on a formula) is fixed by a set_initial_state patch giving the vector "anchor"
{{"body": "<that thing's id>"}}. A TEX_FORMULA or ARROW_ANNOTATION may have initial_state "tone": "result" (green),
"warning" (amber), "wrong" (red: a misconception, a contradiction) or "key"; a formula stating the false idea
coloured as a result is an error to fix by patch. {{"action": "emphasize", "target": <id>, "effect": "shake" |
"pulse"}} shakes a contradiction, makes a result pulse. An OBJECT draws any
concrete thing from a list of icons ("icon": elevator, rocket, satellite, person-standing, user, sun, moon,
earth, house, building, tree-pine, car...): an elevator drawn as a CART (a shopping cart) is an error to
fix (an OBJECT "elevator"), not a renderer limit. An OBJECT, BODY or VECTOR_ARROW can sit on a point of a
graph: initial_state.anchor {{"axes": "<AXES_GRAPH id>", "x": 0, "y": 0}} (graph units). A planet beside
its orbit instead of at its centre is fixed by a set_initial_state patch giving the planet that anchor
(the orbit's centre), never by moving the orbit to where the planet seems to be. VECTOR_ARROW.initial_state
.direction is UP/DOWN/LEFT/RIGHT or [dx, dy]; TEX_FORMULA.initial_state.latex is the formula.
VOLTMETER_PROBES reads a voltage: {{"action": "measure", "target": "<its id>", "target_pin_a": "<id>.<port>" (red
probe), "target_pin_b": "<id>.<port>" (black probe), "value": volts, "unit": "V"}}.

TASK:
1. Score from 0 to 10: accuracy (claims match the research and the domain rules), simplicity
   (the audience can follow), clarity (each visual supports its narration).
2. Correct the storyboard with patches, ONLY of these kinds (scene_id as in the storyboard):
   {{"op": "set_overlay", "scene_id": "1", "title": "...", "subtitle": "..."}}
   {{"op": "set_initial_state", "scene_id": "1", "entity_id": "arrow_1", "key": "direction", "value": "DOWN"}}
   {{"op": "add_action", "scene_id": "1", "action": {{"at": 3.0, "action": "set_state", "target": "lamp_1", "state": {{"on": true}}}}}}
   {{"op": "remove_action", "scene_id": "1", "index": 4}}
   Keys allowed in set_initial_state: {initial_keys}. Actions: {actions}. "value": null removes the key.
   Consecutive set_initial_state patches on one scene are applied together and checked once: to turn
   a y = f(x) curve into a closed one, send "func": null, "x_func", "y_func", "t_min", "t_max" and, in
   the same row, the anchor of a body on it ({{"curve": ..., "t": ...}} instead of "x").
   Text you write (title, subtitle, label, text) is in PERFECT FRENCH.
3. List in "unsupported" what the narration needs but these component types cannot show
   (e.g. a demand curve, a light cone, a bar chart). Do not fake it with other components.
4. Check the whole video too: the same example keeps the same values from scene to scene (a "Pile 6 V"
   that becomes "9 V" without the narration saying so is a factual issue: fix the label by patch, or the
   script if the narration changes it); and the last scene closes the video (answers the hook's
   question, sums up the idea, ends on a closing sentence). A video ending on a question, on a new
   example left unexplained or mid-thought is unfinished: set reject_to "agent003".
5. If the SCRIPT itself is wrong, set reject_to "agent003"; if the visuals are wrong in a way
   patches cannot fix, set reject_to "agent004"; otherwise null.

Answer with JSON only:
{{"scores": {{"accuracy": 8, "simplicity": 8, "clarity": 8}},
  "issues": [{{"scene_id": "1", "text": "...", "kind": "factual", "patches": [0]}}], "patches": [],
  "unsupported": [], "rejection_notes": "...", "reject_to": null}}
Each issue: "kind" is "factual" (a scientific error, or narration and picture that disagree) or "style"
(a clarification or a suggestion, not an error); "patches" lists the indexes (from 0) in "patches" of
the patches that correct it ([] if none does)."""


# ---------------------------------------------------------------- LLM patches

def apply_patches(briefs, patches, corrections, applied=None):
    """Apply the LLM's patches, each only if the brief still validates afterwards. Consecutive
    set_initial_state patches on one scene are first tried together and checked once (turning a
    curve's "func" into "x_func" + "y_func", then the anchor of the body on it from "x" to "t", goes
    through states that are not valid alone); if that fails, one by one. A remove_action on an entity
    whose set_initial_state was just refused is skipped too: the two made one fix (anchor the
    astronaut in the station, then drop its own move), half of it would break the scene. `applied`,
    if given, gets {index of the patch: what it did} for each patch applied."""
    patches = list(patches) if isinstance(patches, list) else []
    dropped = set()                  # (scene, entity) whose change was refused: its fix is not half done
    is_state = lambda p: isinstance(p, dict) and p.get("op") == "set_initial_state"

    def apply(group):
        """Apply patches[group] together to their scene: True if done, False if refused."""
        patch = patches[group[0]]
        scene_id = str(patch.get("scene_id"))
        if scene_id not in briefs:
            corrections.append(f"dropped patch for unknown scene {scene_id!r}")
            return False
        if patch.get("op") == "remove_action" and isinstance(patch.get("index"), int) \
                and 0 <= patch["index"] < len(briefs[scene_id]["actions"]) \
                and (scene_id, briefs[scene_id]["actions"][patch["index"]].get("target")) in dropped:
            target = briefs[scene_id]["actions"][patch["index"]].get("target")
            corrections.append(f"scene {scene_id}: kept action #{patch['index']}: the change to {target} it went with was dropped")
            return False
        candidate = copy.deepcopy(briefs[scene_id])
        problem = next((p for p in (patch_problem(candidate, patches[i]) for i in group) if p), None)
        if problem is None:
            try:
                SceneVisualBrief.model_validate(candidate)
            except ValidationError as exc:
                problem = f"would make the scene invalid ({str(exc).splitlines()[0]})"
        if problem:
            if len(group) == 1:
                corrections.append(f"scene {scene_id}: dropped patch {patch.get('op')!r}: {problem}")
                if is_state(patch):
                    dropped.add((scene_id, patch.get("entity_id")))
            return False
        briefs[scene_id] = candidate
        for i in group:
            corrections.append(f"scene {scene_id}: {describe_patch(patches[i])}")
            if applied is not None:
                applied[i] = f"scene {scene_id}: {describe_patch(patches[i])}"
        return True

    index = 0
    while index < len(patches):
        group = [index]
        if is_state(patches[index]):
            while group[-1] + 1 < len(patches) and is_state(patches[group[-1] + 1]) \
                    and str(patches[group[-1] + 1].get("scene_id")) == str(patches[index].get("scene_id")):
                group.append(group[-1] + 1)
        index = group[-1] + 1
        if not isinstance(patches[group[0]], dict):
            continue
        if not apply(group) and len(group) > 1:   # together refused: one by one, as any patch
            for i in group:
                apply([i])


def patch_problem(brief, patch):
    """Apply one patch to `brief` in place; return why it is refused, or None."""
    op = patch.get("op")
    entities = {e["id"]: e for e in brief["entities"]}
    if op == "set_overlay":
        overlay = brief.get("text_overlay") or {"clear_previous": True}
        for key in ("title", "subtitle"):
            if isinstance(patch.get(key), str) and patch[key].strip():
                overlay[key] = patch[key].strip()
        brief["text_overlay"] = overlay
        return None
    if op == "set_initial_state":
        entity, key, value = entities.get(patch.get("entity_id")), patch.get("key"), patch.get("value")
        if entity is None:
            return f"unknown entity {patch.get('entity_id')!r}"
        if key not in INITIAL_STATE_KEYS:
            return f"key {key!r} not allowed"
        if value is None:                     # null removes the key ("func", to turn a curve parametric)
            entity.setdefault("initial_state", {}).pop(key, None)
            return None
        anchored = "anchor" in (entity.get("initial_state") or {})   # TANGENT / CENTER / OUTWARD need one
        if key == "direction" and direction_problem(value, anchored):  # a cardinal or a vector [dx, dy], as the schema
            return direction_problem(value, anchored)
        if key == "direction":
            value = value.upper() if isinstance(value, str) else [float(v) for v in value]
        entity.setdefault("initial_state", {})[key] = value
        return None
    if op == "add_action":
        action = patch.get("action")
        problem = action_problem(action, entities)
        if problem:
            return problem
        brief["actions"].append(action)
        brief["actions"].sort(key=lambda a: a.get("at", 0))
        return None
    if op == "remove_action":
        index = patch.get("index")
        if not isinstance(index, int) or not 0 <= index < len(brief["actions"]):
            return f"no action #{index}"
        brief["actions"].pop(index)
        return None
    return f"unknown op {op!r}"


def action_problem(action, entities):
    if not isinstance(action, dict) or action.get("action") not in ACTIONS:
        return f"action must be one of {ACTIONS}"
    if not isinstance(action.get("at"), (int, float)) or action["at"] < 0:
        return "action needs a time 'at' >= 0"
    if action["action"] == "measure":
        return measure_problem(action, {i: e["type"] for i, e in entities.items()})
    if action["action"] == "emphasize":
        return emphasis_problem(action, entities)
    if action["action"] in ("move_along", "move"):
        return move_problem(action, {i: (ComponentType(e["type"]), e.get("initial_state") or {}) for i, e in entities.items()})
    referenced = action.get("path") if "flow" in action["action"] else [action.get("target")]
    if action["action"] == "stop_flow" and referenced is None:
        return None
    if not isinstance(referenced, list) or any(r not in entities for r in referenced):
        return f"action refers to unknown entities {referenced!r}"
    if action["action"] == "set_state" and not isinstance(action.get("state"), (dict, str)):
        return "set_state needs a state"
    return None


def describe_patch(patch):
    op = patch.get("op")
    if op == "set_overlay":
        return f"overlay set to {patch.get('title') or ''!r} / {patch.get('subtitle') or ''!r}"
    if op == "set_initial_state":
        return f"{patch.get('entity_id')}.{patch.get('key')} = {patch.get('value')!r}"
    if op == "add_action":
        return f"added action {patch.get('action')}"
    return f"removed action #{patch.get('index')}"


# ---------------------------------------------------------------- deterministic circuit fixes

def ports_of(brief, entity_id):
    entity = next(e for e in brief["entities"] if e["id"] == entity_id)
    return COMPONENT_PORTS[ComponentType(entity["type"])]


def used_ports(brief):
    used = {}
    for c in brief["connections"]:
        for end, port in ((c["source_id"], c["source_port"]), (c["target_id"], c["target_port"])):
            used.setdefault(end, set()).add(port)
    return used


def loop_is_closed(brief, battery_id):
    """True if the battery's positive leads back to its negative (current goes in by one port of a
    component and out by its other one, never through a battery)."""
    links = {}
    for c in brief["connections"]:
        a, b = (c["source_id"], c["source_port"]), (c["target_id"], c["target_port"])
        links.setdefault(a, set()).add(b)
        links.setdefault(b, set()).add(a)
    for entity in brief["entities"]:
        ports = COMPONENT_PORTS[ComponentType(entity["type"])]
        if entity["type"] != ComponentType.BATTERY.value and len(ports) == 2:
            links.setdefault((entity["id"], ports[0]), set()).add((entity["id"], ports[1]))
            links.setdefault((entity["id"], ports[1]), set()).add((entity["id"], ports[0]))
    seen, todo = {(battery_id, "positive")}, [(battery_id, "positive")]
    while todo:
        for neighbour in links.get(todo.pop(), ()):
            if neighbour not in seen:
                seen.add(neighbour)
                todo.append(neighbour)
    return (battery_id, "negative") in seen


def put_ammeters_in_series(brief, where, corrections):
    """An ammeter measures the current only in series: one left outside every flow path is put into
    the first battery loop, just before the current returns to the battery."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    flows = [a for a in brief["actions"] if a.get("action") == "start_flow" and isinstance(a.get("path"), list)
             and types.get(a["path"][0]) == ComponentType.BATTERY.value]
    if not flows:
        return
    on_paths = {i for a in flows for i in a["path"]}
    for ammeter in [i for i, t in types.items() if t == ComponentType.AMMETER.value and i not in on_paths]:
        path = flows[0]["path"]
        position = len(path) - 1 if len(path) > 1 and path[-1] == path[0] else len(path)
        path.insert(position, ammeter)
        # Its old wires led nowhere useful (it was outside the loop): rewire it through the loop.
        old = [c for c in brief["connections"] if ammeter in (c["source_id"], c["target_id"])]
        for c in old:
            brief["connections"].remove(c)
        corrections.append(f"{where}: {ammeter} put in series in the loop {path} (an ammeter must be in series)"
                           + (f"; {len(old)} old wire(s) replaced" if old else ""))


def close_flow_paths(brief, where, corrections):
    """Every start_flow path becomes a closed, wired loop: the path is closed back to its start
    when it starts at a battery, and two consecutive components with no wire between them get one,
    from the first one's free "out" port to the second one's free "in" port."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    for action in brief["actions"]:
        if action.get("action") != "start_flow" or not isinstance(action.get("path"), list):
            continue
        path = action["path"]
        if types.get(path[0]) == ComponentType.BATTERY.value and path[-1] != path[0]:
            action["path"] = path = path + [path[0]]
            corrections.append(f"{where}: flow path closed back to {path[0]}")
        taken = []      # each step of the path needs its own wire: [bat, lamp, bat] needs two
        for a, b in zip(path, path[1:]):
            wire = next((c for c in brief["connections"]
                         if {c["source_id"], c["target_id"]} == {a, b} and c not in taken), None)
            if wire is not None:
                taken.append(wire)
                continue
            used = used_ports(brief)
            out_port = next((p for p in reversed(ports_of(brief, a)) if p not in used.get(a, ())), None)
            in_port = next((p for p in ports_of(brief, b) if p not in used.get(b, ())), None)
            if out_port is None or in_port is None:
                continue        # no free port: the loop check below reports it
            brief["connections"].append({"source_id": a, "source_port": out_port,
                                         "target_id": b, "target_port": in_port})
            taken.append(brief["connections"][-1])
            corrections.append(f"{where}: added missing wire {a}:{out_port} -> {b}:{in_port}")


def remove_dead_ends(brief, where, corrections):
    """A two-port component wired by only one port, on no flow path, is a floating dead end:
    remove that wire."""
    on_paths = {i for a in brief["actions"] if a.get("action") == "start_flow" for i in a.get("path") or []}
    used = used_ports(brief)
    for entity in brief["entities"]:
        ports = COMPONENT_PORTS[ComponentType(entity["type"])]
        if len(ports) == 2 and len(used.get(entity["id"], ())) == 1 and entity["id"] not in on_paths:
            dead = [c for c in brief["connections"] if entity["id"] in (c["source_id"], c["target_id"])]
            for c in dead:
                brief["connections"].remove(c)
                corrections.append(f"{where}: removed dead-end wire {c['source_id']}:{c['source_port']} -> "
                                   f"{c['target_id']}:{c['target_port']} ({entity['id']} had only one wire)")


def remove_open_flows(brief, where, corrections):
    """Current needs a closed loop: drop a flow whose battery's loop is still open."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    for action in list(brief["actions"]):
        if action.get("action") != "start_flow":
            continue
        batteries = [i for i in action.get("path") or [] if types.get(i) == ComponentType.BATTERY.value]
        if batteries and not all(loop_is_closed(brief, b) for b in batteries):
            brief["actions"].remove(action)
            corrections.append(f"{where}: removed start_flow {action.get('path')}: the circuit is not closed")


def state_at(brief, entity_id, key, time):
    """Value of a boolean state key for an entity at `time` (initial_state, then set_state actions)."""
    entity = next(e for e in brief["entities"] if e["id"] == entity_id)
    value = bool(entity.get("initial_state", {}).get(key, False))
    for action in sorted(brief["actions"], key=lambda a: a.get("at", 0)):
        if action.get("at", 0) > time:
            break
        state = action.get("state")
        if action.get("action") == "set_state" and action.get("target") == entity_id and isinstance(state, dict) \
                and key in state:
            value = bool(state[key])
    return value


def close_switches_before_flows(brief, where, corrections):
    """No current across an open switch: close it SWITCH_LEAD_SEC before the flow starts."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    for action in list(brief["actions"]):
        if action.get("action") != "start_flow":
            continue
        for switch in dict.fromkeys(i for i in action.get("path") or [] if types.get(i) == ComponentType.SWITCH.value):
            if not state_at(brief, switch, "closed", action["at"]):
                at = round(max(0.0, action["at"] - SWITCH_LEAD_SEC), 2)
                brief["actions"].append({"at": at, "action": "set_state", "target": switch, "state": {"closed": True}})
                corrections.append(f"{where}: {switch} closed at {at}s, before the current flows through it")


def stop_flows_when_switch_opens(brief, where, corrections):
    """Opening a switch while current flows through it stops that current and turns its lamps off."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    for action in list(brief["actions"]):
        state = action.get("state")
        if (action.get("action") != "set_state" or types.get(action.get("target")) != ComponentType.SWITCH.value
                or not isinstance(state, dict) or state.get("closed") is not False):
            continue
        at = action["at"]
        for flow in [a for a in brief["actions"] if a.get("action") == "start_flow"
                     and action["target"] in (a.get("path") or []) and a["at"] <= at]:
            path = flow["path"]
            stopped = any(a.get("action") == "stop_flow" and a.get("path") in (path, None) and flow["at"] < a["at"] <= at + 0.5
                          for a in brief["actions"])
            if stopped:
                continue
            brief["actions"].append({"at": at, "action": "stop_flow", "path": path})
            lamps = [i for i in dict.fromkeys(path) if types.get(i) == ComponentType.LAMP.value]
            for lamp in lamps:
                brief["actions"].append({"at": round(at + 0.2, 2), "action": "set_state", "target": lamp,
                                         "state": {"on": False}})
            corrections.append(f"{where}: {action['target']} opens at {at}s: current stopped"
                               + (f", {', '.join(lamps)} turned off" if lamps else ""))


def light_lamps_only_with_current(brief, where, corrections):
    """A lamp turned on before any current flows through it is turned on when the current arrives;
    if no current ever flows through it, the "on" is removed. The same for a lamp "on" from the start
    (its initial_state), unless its current flows from the start too."""
    flows = [(a["at"], set(a.get("path") or [])) for a in brief["actions"] if a.get("action") == "start_flow"]
    for entity in brief["entities"]:
        state = entity.get("initial_state") or {}
        if entity.get("type") != "LAMP" or state.get("on") is not True:
            continue
        starts = [at for at, ids in flows if entity["id"] in ids]
        if starts and min(starts) <= LAMP_DELAY_SEC:
            continue
        state.pop("on")
        if starts:
            new_at = round(min(starts) + LAMP_DELAY_SEC, 2)
            brief["actions"].append({"at": new_at, "action": "set_state", "target": entity["id"], "state": {"on": True}})
            brief["actions"].sort(key=lambda a: a.get("at", 0))
            corrections.append(f"{where}: {entity['id']} was on from the start: it now lights up at {new_at}s, when the current reaches it")
        else:
            corrections.append(f"{where}: {entity['id']} was on from the start, but no current flows through it: off")
    for action in list(brief["actions"]):
        state = action.get("state")
        if action.get("action") != "set_state" or not isinstance(state, dict) or state.get("on") is not True:
            continue
        starts = [at for at, ids in flows if action.get("target") in ids]
        if not starts:
            brief["actions"].remove(action)
            corrections.append(f"{where}: {action.get('target')} no longer lights up: no current flows through it")
        elif action["at"] < min(starts):
            new_at = round(min(starts) + LAMP_DELAY_SEC, 2)
            corrections.append(f"{where}: {action.get('target')} now lights up at {new_at}s, when the current "
                               f"reaches it (was {action['at']}s)")
            action["at"] = new_at


def fix_circuits(brief, corrections):
    where = f"scene {brief['scene_id']}"
    put_ammeters_in_series(brief, where, corrections)
    close_flow_paths(brief, where, corrections)
    remove_dead_ends(brief, where, corrections)
    remove_open_flows(brief, where, corrections)
    close_switches_before_flows(brief, where, corrections)
    stop_flows_when_switch_opens(brief, where, corrections)
    light_lamps_only_with_current(brief, where, corrections)
    brief["actions"].sort(key=lambda a: a.get("at", 0))


# ---------------------------------------------------------------- issue severity (observation mode)

# Every issue in qa.json gets a "severity". OBSERVATION MODE: it is written, counted
# (blocking_count, corrected_count, informative_count) and never changes the verdict.
#   "corrected"   the issue was found, then corrected here: every patch the LLM names for it
#                 ("patches": indexes into its own patch list) was applied (validated, not dropped).
#                 An issue that names no patch is corrected when a change in its scene (an applied
#                 patch or a deterministic rule: circuit fixes, layout) is about an entity the issue
#                 names, or sets the title / subtitle the issue talks about.
#   "blocking"    not corrected, and factual: a scientific error, or narration and picture that
#                 disagree. It is still in the storyboard (or the script) after every correction.
#   "informative" not corrected, and stylistic: a clarification or a suggestion, not an error.
# Decided by code, in that order: corrected first (checked against what was really applied), then
# the LLM's "kind" ("factual" / "style"). An issue given as plain text (older answer format) has
# no kind: it is stylistic when its wording is a suggestion (STYLE_WORDS), factual otherwise, and
# its scene is read from "Scène N".
SEVERITIES = ("blocking", "corrected", "informative")
STYLE_KINDS = ("style", "stylistic", "clarification", "suggestion")
STYLE_WORDS = re.compile(r"clarifi|pourrait|suggestion|stylist|lisibilit|reformul|trop long|plus court|plus clair",
                         re.IGNORECASE)
SCENE_IN_TEXT = re.compile(r"sc[eè]ne\s*(\w+)", re.IGNORECASE)
TITLE_WORDS = re.compile(r"titre|title", re.IGNORECASE)


def issue_severities(raw_issues, applied, rule_corrections, briefs):
    """The LLM's issues as {"scene_id", "text", "kind", "severity", "fixed_by"} (see above).
    applied: {patch index: what it did}; rule_corrections: what the deterministic rules changed
    ("scene N: ..."); briefs: {scene_id: brief}, for the entity ids an issue names."""
    issues = []
    for raw in raw_issues if isinstance(raw_issues, list) else []:
        if isinstance(raw, dict):
            text, scene_id = str(raw.get("text") or ""), raw.get("scene_id")
            kind = "style" if str(raw.get("kind", "")).lower() in STYLE_KINDS else "factual"
            named = raw.get("patches") if isinstance(raw.get("patches"), list) else []
        else:
            text, scene_id, named = str(raw), None, []
            kind = "style" if STYLE_WORDS.search(text) else "factual"
        if scene_id is None:
            found = SCENE_IN_TEXT.search(text)
            scene_id = found.group(1) if found else None
        scene_id = None if scene_id is None else str(scene_id)
        if named:                                   # judged on the patches it names, and only on them
            fixed_by = [applied[i] for i in named if i in applied] if all(i in applied for i in named) else []
        elif scene_id in briefs:                    # a change in its scene about what it names
            ids = [e["id"] for e in briefs[scene_id]["entities"] if re.search(rf"\b{re.escape(e['id'])}\b", text)]
            fixed_by = [c for c in list(applied.values()) + list(rule_corrections) if c.startswith(f"scene {scene_id}:")
                        and (any(re.search(rf"\b{re.escape(i)}\b", c) for i in ids)
                             or (TITLE_WORDS.search(text) and "overlay set" in c))]
        else:
            fixed_by = []
        severity = "corrected" if fixed_by else ("blocking" if kind == "factual" else "informative")
        issues.append({"scene_id": scene_id, "text": text, "kind": kind, "severity": severity, "fixed_by": fixed_by})
    return issues


# ---------------------------------------------------------------- agent

# Two separate answers in qa.json:
#   "verdict": can the pipeline go on?  "pass" -> render; "reject" -> revision (agent003 / agent004).
#              Decided as before: every score >= PASS_SCORE, or qa_strict_mode off. The renderers and
#              the orchestrator act on it (the orchestrator through this agent's return status:
#              "revision_needed" when the verdict is "reject").
#   "status":  how sound is the result, from the scores alone? Informative: nothing acts on it.
#              "healthy"     every score above PASS_SCORE (8 and more)
#              "warning"     none below, but at least one exactly at PASS_SCORE (7): passed, to watch
#              "not_healthy" at least one below PASS_SCORE (failed, or passed only because
#                            qa_strict_mode is off)
# So verdict "pass" + status "warning" is a pass, with a warning.
def score_status(scores):
    """qa.json "status" from the scores (see above)."""
    if any(score < PASS_SCORE for score in scores.values()):
        return "not_healthy"
    if any(score == PASS_SCORE for score in scores.values()):
        return "warning"
    return "healthy"


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    output_path = os.path.join(folder, "qa.json")
    storyboard_path = os.path.join(folder, "storyboard.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["script.json", "storyboard.json", "research.json"])
    script = load_json(os.path.join(folder, "script.json"))
    storyboard = load_json(storyboard_path)
    research = load_json(os.path.join(folder, "research.json"))
    if not (script and storyboard.get("scenes") and research):
        return finish(channel_id, AGENT, "qa", "critical", output_path, error="missing script, storyboard or research")
    if any("visual_brief" not in scene for scene in storyboard["scenes"]):
        return finish(channel_id, AGENT, "qa", "critical", output_path,
                      error="storyboard has scenes without visual_brief: rerun agent004")
    briefs = {str(scene["visual_brief"]["scene_id"]): copy.deepcopy(scene["visual_brief"])
              for scene in storyboard["scenes"]}

    route = find_route(routes, channel_id) or {}
    domains = DOMAIN_GROUPS.get(route.get("domain"), list(DOMAIN_RULES))
    prompt = PROMPT.format(rules="\n\n".join(DOMAIN_RULES[d] for d in domains),
                           research=json.dumps(research, ensure_ascii=False),
                           script=json.dumps(script.get("scenes"), ensure_ascii=False),
                           storyboard=json.dumps(list(briefs.values()), ensure_ascii=False),
                           vocabulary=VOCABULARY, initial_keys=", ".join(INITIAL_STATE_KEYS), actions=", ".join(ACTIONS))
    try:
        answer = parse_llm_json(llm_call(prompt))
        scores = {key: float(answer["scores"][key]) for key in ("accuracy", "simplicity", "clarity")}
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        return finish(channel_id, AGENT, "qa", "critical", output_path, error=f"QA failed: {exc}")

    # 1. The LLM's corrections, each validated; 2. the circuit rules, enforced by code.
    corrections, layout_conflicts, applied = [], [], {}
    apply_patches(briefs, answer.get("patches"), corrections, applied)
    from_patches = len(corrections)
    for brief in briefs.values():
        fix_circuits(brief, corrections)
        layout_conflicts += solve_layout(brief, corrections)
    issues = issue_severities(answer.get("issues"), applied, corrections[from_patches:], briefs)
    try:
        for scene in storyboard["scenes"]:
            corrected = briefs[str(scene["visual_brief"]["scene_id"])]
            scene["visual_brief"] = SceneVisualBrief.model_validate(corrected).model_dump(mode="json")
    except ValidationError as exc:
        return finish(channel_id, AGENT, "qa", "critical", output_path,
                      error=f"corrected storyboard does not validate: {str(exc)[:300]}")
    if corrections:
        save_json(storyboard_path, storyboard)
        provenance.register_artifact(run_id, channel_id, "storyboard.json", AGENT)   # corrected in place

    # The verdict is decided by code, not by the LLM.
    all_pass = all(score >= PASS_SCORE for score in scores.values())
    verdict = "pass" if all_pass or not settings.get("qa_strict_mode", True) else "reject"
    # Only a script the LLM calls wrong goes back to agent003; any other reject redoes the visuals.
    reject_to = "agent003" if answer.get("reject_to") == "agent003" else "agent004"
    unsupported = [str(u) for u in answer.get("unsupported") or []]
    qa = {
        "verdict": verdict,                    # can we go on? (unchanged: the pipeline acts on it)
        "status": score_status(scores),        # is it sound, or passed with a warning? (informative)
        "scores": scores,
        "rejection_notes": answer.get("rejection_notes", "") if verdict == "reject" else "",
        "reject_to": reject_to if verdict == "reject" else None,
        "issues": issues,                      # each with its "severity" (observation: no effect on the verdict)
        **{f"{severity}_count": sum(i["severity"] == severity for i in issues) for severity in SEVERITIES},
        "corrections": corrections,
        "unsupported": unsupported,
        "layout_conflicts": layout_conflicts,
    }
    save_json(output_path, qa)
    provenance.register_artifact(run_id, channel_id, "qa.json", AGENT)

    if verdict == "reject":
        status = "revision_needed"
    elif all_pass and PASS_SCORE not in scores.values() and not unsupported and not layout_conflicts:
        status = "healthy"
    else:
        status = "not_healthy"
    return finish(channel_id, AGENT, "qa", status, output_path,
                  data={**qa, "corrected_scenes": sorted({c.split(':')[0] for c in corrections})})


if __name__ == "__main__":
    run_standalone(run)
