"""
Visual brief schema: what agent004 asks the LLM for, and what the renderer (agent010) draws.

One SceneVisualBrief per narrated scene:
  text_overlay  -> title / subtitle on screen, and whether they replace the previous ones
  entities      -> the components on stage, each on a layer, at a scene point or a semantic place
  connections   -> wires between named ports ("positive" -> "in"), never raw offsets
  actions       -> the timed steps of the scene (free-form dicts for now)

Closed vocabulary (enums) so the renderer can map every component to hardcoded drawing code:
the LLM describes WHAT is on stage and how it is wired, never HOW to draw it.
"""

import ast
import math
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComponentType(str, Enum):
    BATTERY = "BATTERY"
    LAMP = "LAMP"
    SWITCH = "SWITCH"
    AMMETER = "AMMETER"
    PEDAL_CRANK = "PEDAL_CRANK"
    SPROCKET = "SPROCKET"
    CHAIN_LINK = "CHAIN_LINK"
    WIRE_BUS = "WIRE_BUS"
    ARROW_ANNOTATION = "ARROW_ANNOTATION"
    EARTH_GROUND = "EARTH_GROUND"            # protective earth: a lead and 3 bars, widest on top
    CHASSIS_MASS = "CHASSIS_MASS"            # chassis / circuit ground (0 V reference): a triangle
    # SVG-based: concrete objects, drawn from a Lucide icon (app/render/asset_resolver.py)
    WATER_TANK = "WATER_TANK"
    PIPE_VALVE = "PIPE_VALVE"
    COINS = "COINS"
    SCALE = "SCALE"
    BANK = "BANK"
    CART = "CART"
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    GAUGE = "GAUGE"
    # Abstract maths / physics concepts, drawn geometrically
    AXES_GRAPH = "AXES_GRAPH"
    CURVE_PLOT = "CURVE_PLOT"
    VECTOR_ARROW = "VECTOR_ARROW"
    TEX_FORMULA = "TEX_FORMULA"
    BODY = "BODY"                            # a body (satellite, planet, ball): a disc, moving along a curve or in a straight line
    OBJECT = "OBJECT"                        # any concrete thing with no type of its own, drawn from OBJECT_ICONS
    SEESAW = "SEESAW"                        # a beam on a pivot with a load at each end: weights, the weighted mean
    LANES = "LANES"                          # queues side by side (a toll, checkouts): delimited lanes, things rolling through a gate
    SPEED_RACE = "SPEED_RACE"                # speeds compared on one track, to one scale: who arrives, how long the others would take
    POPULATION = "POPULATION"                # a population as a grid of dots, its groups coloured: shares of people seen at a glance
    TIDES = "TIDES"                          # the Earth, its ocean and the Moon: the pull at three points, the ocean stretched, the Earth turning
    LOGIC_CIRCUIT = "LOGIC_CIRCUIT"          # inputs, logic gates (ET, OU, NON...) and outputs wired together, 0 and 1 on the wires
    FPGA_GRID = "FPGA_GRID"                  # an FPGA's logic blocks and routing: configured by a bitstream, reconfigured, out of room
    MICROCONTROLLER = "MICROCONTROLLER"      # a microcontroller's inside: its program in memory, one unit doing one instruction at a time
    WAVE = "WAVE"                            # a mechanical wave: a rope, the sea, a crowd (ola), a spring (sound); the medium stays
    TUNNEL = "TUNNEL"                        # a zoom into a tube, a dot and a wall as a line across it: it bounces back, or tunnels through
    # Schematic parts (standard symbols), for circuits built step by step: wired by their ports
    BREADBOARD = "BREADBOARD"                # the same circuit built on a breadboard: real parts plugged in, jumpers, rails
    SUPPLY_RAIL = "SUPPLY_RAIL"              # a supply symbol ("+12 V"), put beside each part fed by it (as CHASSIS_MASS for 0 V)
    RESISTOR = "RESISTOR"                    # a resistor (its value in its label: "R1 10 kΩ")
    POTENTIOMETER = "POTENTIOMETER"          # a potentiometer: its two ends and its wiper (a setpoint, a divider)
    THERMISTOR = "THERMISTOR"                # a thermistor (CTN): its resistance falls as it warms
    OPAMP = "OPAMP"                          # an operational amplifier (AOP): + and − inputs, output, supply
    MOSFET = "MOSFET"                        # an N-channel MOSFET: gate, drain, source (a switch driven by a voltage)
    DIODE = "DIODE"                          # a diode: anode, cathode
    LED = "LED"                              # a light-emitting diode: anode, cathode; lit when on
    HEATER = "HEATER"                        # a heating resistor: heat rising from it when on
    # Instruments: drawn as a device beside the diagram, never wired; they act through actions
    VOLTMETER_PROBES = "VOLTMETER_PROBES"    # digital multimeter + red/black probes ("measure")


INSTRUMENT_TYPES = (ComponentType.VOLTMETER_PROBES,)
SVG_TYPES = (ComponentType.WATER_TANK, ComponentType.PIPE_VALVE, ComponentType.COINS, ComponentType.SCALE,
             ComponentType.BANK, ComponentType.CART, ComponentType.TRENDING_UP, ComponentType.TRENDING_DOWN,
             ComponentType.GAUGE)


# Logical port names of each component type, in the direction current (or motion) goes through
# it: in first, out second. A battery's current leaves by "positive" and comes back by "negative".
COMPONENT_PORTS = {
    ComponentType.BATTERY: ("negative", "positive"),
    ComponentType.LAMP: ("left_terminal", "right_terminal"),
    ComponentType.SWITCH: ("in", "out"),
    ComponentType.AMMETER: ("in", "out"),
    ComponentType.PEDAL_CRANK: ("center", "rim"),
    ComponentType.SPROCKET: ("center", "rim"),
    ComponentType.CHAIN_LINK: ("in", "out"),
    ComponentType.WIRE_BUS: ("in", "out"),
    ComponentType.ARROW_ANNOTATION: (),   # an annotation points at things; it is never wired
    ComponentType.EARTH_GROUND: ("terminal",),   # one port: wired to the node it references
    ComponentType.CHASSIS_MASS: ("terminal",),
    **{t: ("left", "right", "top", "bottom") for t in SVG_TYPES},    # one port on each side
    ComponentType.OBJECT: ("left", "right", "top", "bottom"),
    ComponentType.AXES_GRAPH: (),
    ComponentType.CURVE_PLOT: (),
    ComponentType.VECTOR_ARROW: (),
    ComponentType.TEX_FORMULA: (),
    ComponentType.BODY: (),
    ComponentType.LANES: (),
    ComponentType.SEESAW: (),
    ComponentType.SPEED_RACE: (),
    ComponentType.POPULATION: (),
    ComponentType.TIDES: (),
    ComponentType.LOGIC_CIRCUIT: (),
    ComponentType.FPGA_GRID: (),
    ComponentType.TUNNEL: (),
    ComponentType.WAVE: (),
    ComponentType.MICROCONTROLLER: (),
    ComponentType.SUPPLY_RAIL: ("terminal",),
    ComponentType.BREADBOARD: (),
    ComponentType.RESISTOR: ("left", "right"),
    ComponentType.POTENTIOMETER: ("left", "right", "wiper"),
    ComponentType.THERMISTOR: ("left", "right"),
    ComponentType.OPAMP: ("in_plus", "in_minus", "out", "vcc", "gnd"),
    ComponentType.MOSFET: ("gate", "drain", "source"),
    ComponentType.DIODE: ("anode", "cathode"),
    ComponentType.LED: ("anode", "cathode"),
    ComponentType.HEATER: ("left", "right"),
    ComponentType.VOLTMETER_PROBES: (),   # its probes touch other components' ports ("measure")
}

# OBJECT: a concrete thing that has no component type of its own (an elevator, a rocket, a person,
# the Sun...), drawn like the icon types, from one of these icons ("icon"; default "box"), with its
# label. A closed list: the schema can check it, and only these names are ever fetched (Lucide,
# pinned version, cached in assets/icons; "elevator", "cannon" and "spring" are drawn by hand there,
# Lucide has none of them).
OBJECT_ICONS = {
    "things": ("box", "package", "weight", "dumbbell", "anvil", "hammer", "wrench", "key", "lock", "magnet",
               "lightbulb", "smartphone", "laptop", "cpu", "clock", "hourglass", "thermometer", "ruler",
               "flask-conical", "test-tube", "microscope", "telescope", "atom", "cannon", "spring", "compass",
               "timer", "calculator", "dice-5", "anchor"),
    "energy": ("plug", "fuel", "fan", "radiation"),
    "buildings": ("house", "building", "building-2", "factory", "school", "hospital", "store", "warehouse",
                  "elevator", "door-closed", "radio-tower"),
    "transport": ("car", "bus", "truck", "train-front", "plane", "rocket", "satellite", "ship", "bike", "tractor"),
    "people": ("user", "users", "person-standing", "baby", "hard-hat"),
    "nature and sky": ("sun", "moon", "earth", "globe", "cloud", "cloud-rain", "droplet", "flame", "zap", "wind",
                       "waves", "snowflake", "mountain", "tree-pine", "leaf", "apple"),
    "living": ("heart", "brain", "eye", "hand", "paw-print", "dog", "cat", "rabbit",
               "bird", "fish", "squirrel", "turtle", "snail", "bug"),
    "health": ("pill", "syringe", "stethoscope", "heart-pulse"),
    "food and farming": ("wheat", "carrot", "egg", "milk", "croissant", "coffee"),
    "money and trade": ("banknote", "wallet", "piggy-bank", "receipt", "credit-card", "tag", "ticket",
                        "shopping-basket", "handshake"),
    "society": ("vote", "gavel"),
    "other": ("orbit", "trophy", "flag", "book-open", "graduation-cap", "briefcase", "shopping-bag"),
}
OBJECT_ICON_NAMES = tuple(name for names in OBJECT_ICONS.values() for name in names)
DEFAULT_OBJECT_ICON = "box"


# LANES: queues side by side, the analogy of parallel branches (lanes at a toll, checkouts in a shop):
# each lane delimited, its label on its left, its vehicles or people (one "icon", of LANE_ICONS) rolling
# to the gate on the right at its "rate" (how many go through per second), and the count gone through.
#   initial_state {"lanes": [{"label": "File rapide", "rate": 1.5}, {"label": "File lente", "rate": 0.5}],
#                  "icon": "car", "label": "Péage"}
# The lanes run from the moment they are on screen; set_state {"active": false} stops them, {"active":
# true} sets them off again.
LANE_ICONS = ("car", "bus", "truck", "bike", "user", "users", "person-standing", "shopping-bag")
LANE_COUNT = (2, 4)
LANE_RATE = (0.2, 3.0)
LANE_LABEL_MAX = 24


def lanes_problem(state):
    """Why a LANES initial_state is wrong (see above), or None."""
    lanes = state.get("lanes")
    if not isinstance(lanes, list) or not LANE_COUNT[0] <= len(lanes) <= LANE_COUNT[1]:
        return (f'LANES needs "lanes": a list of {LANE_COUNT[0]} to {LANE_COUNT[1]} lanes '
                f'[{{"label": "File rapide", "rate": 1.5}}, ...], got {lanes!r}'[:300])
    for lane in lanes:
        if not isinstance(lane, dict) or set(lane) - {"label", "rate"}:
            return f'each lane is {{"label": "...", "rate": <number>}}, got {lane!r}'[:300]
        label, rate = lane.get("label"), lane.get("rate")
        if not isinstance(label, str) or not label.strip() or len(label) > LANE_LABEL_MAX:
            return f"a lane's label is a short text (at most {LANE_LABEL_MAX} characters), got {label!r}"
        if not is_number(rate) or not LANE_RATE[0] <= rate <= LANE_RATE[1]:
            return (f"a lane's rate is how many go through per second, from {LANE_RATE[0]:g} to {LANE_RATE[1]:g}; "
                    f"got {rate!r}")
    if state.get("icon", "car") not in LANE_ICONS:
        return f"LANES icon must be one of {list(LANE_ICONS)}, got {state.get('icon')!r}"
    return None


# SEESAW: a beam on a pivot, a load at each end, tipping towards the heavier one (a damped swing).
#   initial_state {"left": {"label": "Classe A", "weight": 30, "value": 15},
#                  "right": {"label": "Classe B", "weight": 5, "value": 10}, "unit": "/20"}
# "weight": how heavy the load is (> 0); "value" (optional, both or neither): the number at that end of
# the beam, which is then a scale from one value to the other. set_state {"left": true} / {"right":
# true} drops that load on its end (a side never set is there from the start); {"balanced": true}
# slides the pivot under the beam until it balances: it then stands at the weighted mean of the two
# values, shown under it.
SEESAW_LABEL_MAX = 30


# SPEED_RACE: two or three speeds on ONE track, to ONE scale (the analogy of "how much faster"):
#   initial_state {"distance": 1, "distance_unit": "m",
#                  "runners": [{"label": "Électron", "speed": 0.1, "unit": "mm/s", "icon": "atom"},
#                              {"label": "Signal", "speed": 200000, "unit": "km/s", "icon": "zap"}]}
# The fastest crosses the track in a few seconds on screen, the others at their share of its speed
# (an electron drifting at 0.1 mm/s does not move a pixel); each lane then gives the real time its
# runner takes ("5 ns", "2 h 47 min"), and the fastest how many times faster it goes than the slowest.
# Off at its pop, or at set_state {"go": true}.
RACE_SPEED_UNITS = {"mm/h": 1e-3 / 3600, "mm/s": 1e-3, "cm/s": 1e-2, "m/s": 1.0, "km/h": 1 / 3.6, "km/s": 1e3}
RACE_DISTANCE_UNITS = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "km": 1e3}
RACE_RUNNERS = (2, 3)
RACE_LABEL_MAX = 24


# POPULATION: a population drawn as a grid of dots (an icon array), each dot standing for "per" people
# (or things): its groups' shares seen at a glance (a rare disease and a test's false alarms, a vote).
#   initial_state {"total": 1000, "per": 10, "unit": "personnes",
#                  "groups": [{"id": "sick", "label": "Malades", "count": 10, "color": "#DC2626"},
#                             {"id": "false_alarm", "label": "Faux positifs", "count": 10, "color": "#F59E0B"}],
#                  "rest": "Bien portants"}
# "total" dots (POPULATION_DOTS), the groups' dots first, in order, the others grey ("rest" names
# them). set_state {"show": "<group id>"} colours that group in (a group never shown is coloured from
# the start); {"focus": ["<group id>", ...]} dims every other dot (among the positives only: who is
# ill?), {"focus": []} brings them back. The legend gives each group's count of people (count x per).
# TIDES: the Earth in its ocean, the Moon on its right; everything drawn and labelled by the renderer
# (initial_state: nothing needed). set_state, each on the words that say it:
#   {"points": true}    three points on the Earth-Moon line: "Point proche", "Centre", "Point opposé"
#   {"forces": true}    the Moon's pull on each, to scale: strongest at the near point, weakest opposite
#   {"relative": true}  what is left once the centre's pull is taken away: the near water pulled
#                       towards the Moon, the far water left behind: both move away from the centre
#   {"stretch": true}   the ocean stretches into two bulges ("bourrelets", high tide) on the Earth-Moon
#                       line, low tide between them
#   {"spin": true}      the Earth turns with a port on it: it passes under both bulges, two high tides a day
#   {"sun": "aligned"}  the Sun in line (bigger bulges: vives-eaux), {"sun": "square"} at a right
#                       angle (smaller: mortes-eaux)
# Never given any of them, it plays them in that order from its pop (the Sun left out).
# BREADBOARD: a circuit as it is built on a breadboard, laid out by the renderer (never coordinates
# from the brief): initial_state {"parts": [{"id": "r1", "kind": "RESISTOR", "label": "R1 10 kΩ"}, ...],
# "nets": [["+12 V", "r1.left", "op.vcc"], ["r1.right", "ctn.left", "op.in_minus"], ["0 V", "ctn.right"]]}.
# kinds and their leads in BB_KINDS (OPAMP: an 8-pin DIP, LM358 pinout); a net joins leads ("id.lead"),
# a net led by a supply name ("+12 V", "+5 V", "0 V", "GND") is on the board's red or blue rail. The
# parts go in, in their order: set_state {"step": n} shows the first n parts and their jumpers (never
# given: one part a second from its pop).
BB_KINDS = {"RESISTOR": ("left", "right"), "THERMISTOR": ("left", "right"), "DIODE": ("anode", "cathode"),
            "LED": ("anode", "cathode"), "HEATER": ("left", "right"), "POTENTIOMETER": ("left", "wiper", "right"),
            "MOSFET": ("gate", "drain", "source"), "OPAMP": ("out", "in_minus", "in_plus", "gnd", "vcc")}
BB_RAIL = re.compile(r"\+\s?\d{1,2}(?:[.,]\d)?\s?V|0\s?V|GND")
BB_PARTS = (0, 12)            # 0: the board alone, its rails fed (the supply stage)
BB_LABEL_MAX = 24             # a label longer than this is shortened on the board (app/breadboard.py)
BB_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")


def breadboard_problem(state):
    """Why a BREADBOARD initial_state is wrong (see above), or None."""
    parts, nets = state.get("parts"), state.get("nets")
    if not isinstance(parts, list) or not BB_PARTS[0] <= len(parts) <= BB_PARTS[1]:
        return f'BREADBOARD needs "parts": {BB_PARTS[0]} to {BB_PARTS[1]} parts {{"id", "kind", "label"}}, got {parts!r}'[:300]
    ids = []
    for p in parts:
        if not isinstance(p, dict) or not BB_ID.fullmatch(str(p.get("id", ""))) or p.get("kind") not in BB_KINDS:
            return f'BREADBOARD part {p!r}: "id" (letters, digits), "kind" one of {sorted(BB_KINDS)}'[:300]
        if p.get("label") is not None and not isinstance(p["label"], str):      # a long one is shortened when drawn
            return f'BREADBOARD part {p["id"]}: "label" is a text'
        ids.append(p["id"])
    if len(set(ids)) != len(ids):
        return f"BREADBOARD parts with the same id: {ids}"
    kinds = {p["id"]: p["kind"] for p in parts}
    if not parts and nets in (None, []):
        return None
    if not isinstance(nets, list) or not nets:
        return 'BREADBOARD needs "nets": lists of leads joined ("r1.right"), a supply name first for a rail ("+12 V")'
    seen = set()
    for net in nets:
        if not isinstance(net, list) or not 1 <= len(net) <= 12 or not all(isinstance(x, str) for x in net):
            return f"BREADBOARD net {net!r}: a list of 1 to 12 texts"[:300]
        leads = net[1:] if BB_RAIL.fullmatch(net[0]) else net
        for lead in leads:
            part_id, _, name = lead.partition(".")
            if part_id not in kinds or name not in BB_KINDS[kinds[part_id]]:
                return (f"BREADBOARD net {net!r}: {lead!r} is no lead (a part's id, a dot, one of its leads: "
                        f"{part_id} has {list(BB_KINDS.get(kinds.get(part_id), ()))})")[:300]
            if lead in seen:
                return f"BREADBOARD: {lead} is in two nets: one net per lead (join the two nets)"
            seen.add(lead)
        if len(leads) < 2 and not BB_RAIL.fullmatch(net[0]):
            return f"BREADBOARD net {net!r} joins nothing: two leads at least, or a supply and a lead"[:300]
    return None


# MICROCONTROLLER: a chip, inside it the program memory (its instructions, numbered) and ONE unit
# doing them: initial_state {"label": "Microcontrôleur", "instructions": ["lire Bouton 1", "lire
# Bouton 2", "calculer ET", "allumer Lampe"]} (1 to 8 short texts). set_state {"run": true}: a pointer
# goes down the program, each instruction travels to the unit and is done there, one after the other
# (then again from the top); {"run": false} stops it. Never given "run", it runs from its pop.
MCU_INSTRUCTIONS = (1, 8)
MCU_TEXT_MAX = 26


def mcu_problem(state):
    """Why a MICROCONTROLLER initial_state is wrong (see above), or None."""
    items = state.get("instructions")
    low, high = MCU_INSTRUCTIONS
    if items is not None and (not isinstance(items, list) or not low <= len(items) <= high
                              or any(not isinstance(i, str) or not i.strip() or len(i) > MCU_TEXT_MAX for i in items)):
        return (f'MICROCONTROLLER "instructions": {low} to {high} short texts (at most {MCU_TEXT_MAX} characters: '
                f'"lire Bouton 1", "calculer ET"), got {items!r}'[:300])
    return None


# WAVE: a mechanical wave drawn by the renderer: a real undulating line travelling across. initial_state
# {"mode": "rope" | "water" | "crowd" | "spring", "kind": "pulse" | "continuous", "label": "Corde"}:
# rope: a rope and its points; water: the sea's surface, a buoy on it; crowd: a row of spectators
# standing up and sitting down in turn (an ola); spring: coils squeezed and spread (a longitudinal
# wave, as sound in the air: compressions named). set_state {"go": true} sends the wave (never given:
# from the pop); {"mark": true} picks out one point (the buoy, one spectator) that only goes up and
# down, or back and forth, never along; {"energy": true}: an arrow "Énergie" travelling with the crest;
# {"go": false} stops it. "kind": "standing": a standing wave on a rope tied at both ends (rope mode):
# nodes that never move, named, antinodes swinging most; {"parts": true} draws the two waves going
# opposite ways, each on its own rope over it, whose sum it is; "loops": 1 to 6 antinodes (the harmonic).
WAVE_MODES = ("rope", "water", "crowd", "spring")
WAVE_KINDS = ("pulse", "continuous", "standing")


def wave_problem(state):
    """Why a WAVE initial_state is wrong (see above), or None."""
    if state.get("mode", "rope") not in WAVE_MODES:
        return f'WAVE "mode" is one of {list(WAVE_MODES)}, got {state.get("mode")!r}'
    if state.get("kind", "pulse") not in WAVE_KINDS:
        return f'WAVE "kind" is one of {list(WAVE_KINDS)}, got {state.get("kind")!r}'
    label = state.get("label")
    if label is not None and not isinstance(label, str):
        return f'WAVE "label" is a text, got {label!r}'
    loops = state.get("loops", 3)
    if not isinstance(loops, int) or isinstance(loops, bool) or not 1 <= loops <= 6:
        return f'WAVE "loops" (a standing wave\'s antinodes, its harmonic) is a whole number from 1 to 6, got {loops!r}'
    return None


# TUNNEL: the quantum tunnel effect, drawn by the renderer: the view zooms in on a tube, a blue dot
# in it, the wall a vertical line across the tube. initial_state (all optional): {"particle":
# "Particule", "barrier": "Mur", "zoom": true}. set_state, on the words that say it:
#   {"bounce": true}    what we expect: the dot runs into the wall and bounces back
#   {"tunnel": true}    the quantum effect: the dot reaches the wall and comes out on the other side,
#                       the wall left whole
# Never given any, it zooms in and tunnels through.
TUNNEL_LABEL_MAX = 24


def tunnel_problem(state):
    """Why a TUNNEL initial_state is wrong (see above), or None."""
    for key in ("particle", "barrier"):
        value = state.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > TUNNEL_LABEL_MAX):
            return f'TUNNEL "{key}" is a short text (at most {TUNNEL_LABEL_MAX} characters), got {value!r}'
    if "zoom" in state and not isinstance(state["zoom"], bool):
        return f'TUNNEL "zoom" is true or false, got {state["zoom"]!r}'
    return None


# LOGIC_CIRCUIT: a small logic diagram, laid out and wired by the renderer from what feeds what:
#   initial_state {"inputs": [{"id": "a", "label": "Interrupteur 1"}, {"id": "b", "label": "Interrupteur 2"}],
#                  "gates": [{"id": "g1", "type": "AND", "in": ["a", "b"]}, {"id": "g2", "type": "NOT", "in": ["g1"]}],
#                  "outputs": [{"id": "lamp", "label": "Lampe", "from": "g2"}],
#                  "values": {"a": 0, "b": 0}}
# Each gate takes two inputs (one for NOT), from inputs or earlier gates; an output shows one input or
# gate. A wire at 1 glows, at 0 is grey; each gate's value is shown; an output lamp lights at 1.
# set_state {"a": 1} sets an input (its id as the key, 0 or 1); {"mode": "sequential"}: from then on
# the gates work one after the other (a program's steps, LOGIC_STEP s each), {"mode": "parallel"}
# (the default) all at once (a circuit).
LOGIC_GATES = {"AND": 2, "OR": 2, "XOR": 2, "NAND": 2, "NOR": 2, "NOT": 1}
LOGIC_LIMITS = {"inputs": (1, 4), "gates": (1, 6), "outputs": (1, 3)}
LOGIC_LABEL_MAX = 24
LOGIC_ID = re.compile(r"[a-z][a-z0-9_]{0,15}")
LOGIC_RESERVED = {"mode", "on", "active", "highlighted", "dimmed", "closed"}


def logic_problem(state):
    """Why a LOGIC_CIRCUIT initial_state is wrong (see above), or None."""
    parts = {}
    for key, (low, high) in LOGIC_LIMITS.items():
        items = state.get(key)
        if not isinstance(items, list) or not low <= len(items) <= high:
            return (f'LOGIC_CIRCUIT needs "{key}": {low} to {high} items (see the example: inputs {{"id", "label"}}, '
                    f'gates {{"id", "type", "in"}}, outputs {{"id", "label", "from"}}); got {items!r}'[:300])
        parts[key] = items
    known = []
    for key, fields in (("inputs", {"id", "label"}), ("gates", {"id", "type", "in", "label"}), ("outputs", {"id", "label", "from"})):
        for item in parts[key]:
            if not isinstance(item, dict) or set(item) - fields:
                return f'a {key[:-1]} is {sorted(fields)}, got {item!r}'[:300]
            if not isinstance(item.get("id"), str) or not LOGIC_ID.fullmatch(item["id"]) or item["id"] in known \
                    or item["id"] in LOGIC_RESERVED:
                return f'each id is short, lower case, its own (not {sorted(LOGIC_RESERVED)}): got {item.get("id")!r}'
            if "label" in item and (not isinstance(item["label"], str) or len(item["label"]) > LOGIC_LABEL_MAX):
                return f"a label is a short text (at most {LOGIC_LABEL_MAX} characters), got {item.get('label')!r}"
            if key == "gates":
                if item.get("type") not in LOGIC_GATES:
                    return f'a gate\'s "type" is one of {list(LOGIC_GATES)}, got {item.get("type")!r}'
                feeds = item.get("in")
                if not isinstance(feeds, list) or len(feeds) != LOGIC_GATES[item["type"]] or any(f not in known for f in feeds):
                    return (f'gate {item["id"]}: "in" lists {LOGIC_GATES[item["type"]]} ids of inputs or earlier gates '
                            f'(NOT takes one, the others two); got {feeds!r}')
            if key == "outputs" and item.get("from") not in known:
                return f'output {item["id"]}: "from" is an input or gate id, got {item.get("from")!r}'
            known.append(item["id"])
    values = state.get("values", {})
    if not isinstance(values, dict) or any(k not in [i["id"] for i in parts["inputs"]] or v not in (0, 1, True, False)
                                           for k, v in values.items()):
        return f'"values" gives inputs their first value, 0 or 1: {{"a": 0}}; got {values!r}'[:300]
    return None


# FPGA_GRID: an FPGA's inside, a grid of logic blocks with routing channels between them:
#   initial_state {"cols": 4, "rows": 3, "design": ["ET", "OU", "NON", "Compteur"], "design2": ["Filtre", "ET"]}
# set_state {"configure": true}: the bitstream comes in and places "design" in the blocks, one after
# the other, the routing between them lit (more functions than blocks: the extra ones stay outside,
# in red, "ressources insuffisantes"); {"run": true}: every configured block works at once (signals
# along all the lit routes); {"reconfigure": true}: the blocks are cleared and "design2" is placed;
# {"zoom": "ET"} (a function's name, or a block's number): the view zooms on that block, its inside
# drawn (the gate, or a small table for another function), {"zoom": false} back out; {"wire": true}:
# the interconnect, switches between the blocks closing one route after the other, signals running.
FPGA_SIZE = {"cols": (2, 6), "rows": (2, 4)}
FPGA_DESIGN_MAX = 30
FPGA_LABEL_MAX = 18      # shown on two lines past 9 characters when it has a space


def fpga_problem(state):
    """Why an FPGA_GRID initial_state is wrong (see above), or None."""
    for key, (low, high) in FPGA_SIZE.items():
        value = state.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            return f'FPGA_GRID needs "{key}": a whole number from {low} to {high}, got {value!r}'
    for key in ("design", "design2"):
        design = state.get(key)
        if design is None and key == "design2":
            continue
        if not isinstance(design, list) or not 1 <= len(design) <= FPGA_DESIGN_MAX \
                or any(not isinstance(d, str) or not d.strip() or len(d) > FPGA_LABEL_MAX for d in design):
            return (f'"{key}" lists the functions placed in the blocks, 1 to {FPGA_DESIGN_MAX} short texts (at most '
                    f'{FPGA_LABEL_MAX} characters: "ET", "Compteur"); got {design!r}'[:300])
    return None


POPULATION_DOTS = (10, 1000)
POPULATION_GROUPS = (1, 4)
POPULATION_LABEL_MAX = 28
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
GROUP_ID = re.compile(r"[A-Za-z0-9_-]{1,24}")


def population_problem(state):
    """Why a POPULATION initial_state is wrong (see above), or None."""
    total, per = state.get("total"), state.get("per", 1)
    if not isinstance(total, int) or isinstance(total, bool) or not POPULATION_DOTS[0] <= total <= POPULATION_DOTS[1]:
        return (f'POPULATION needs "total": the number of dots, a whole number from {POPULATION_DOTS[0]} to '
                f'{POPULATION_DOTS[1]} (10 000 people: 1000 dots with "per": 10); got {total!r}')
    if not is_number(per) or per < 1 or per != int(per):
        return f'"per" is how many people one dot stands for, a whole number from 1; got {per!r}'
    if not isinstance(state.get("unit", "personnes"), str) or len(state.get("unit", "personnes")) > 16:
        return f'"unit" is what is counted, a short word ("personnes", "votants"); got {state.get("unit")!r}'
    groups = state.get("groups")
    if not isinstance(groups, list) or not POPULATION_GROUPS[0] <= len(groups) <= POPULATION_GROUPS[1]:
        return (f'POPULATION needs "groups": {POPULATION_GROUPS[0]} to {POPULATION_GROUPS[1]} of {{"id": "sick", '
                f'"label": "Malades", "count": <dots>, "color": "#RRGGBB"}}; got {groups!r}'[:300])
    ids = []
    for group in groups:
        if not isinstance(group, dict) or set(group) - {"id", "label", "count", "color"}:
            return f'a group is {{"id", "label", "count", "color"}}, got {group!r}'[:300]
        if not isinstance(group.get("id"), str) or not GROUP_ID.fullmatch(group["id"]) or group["id"] in ids:
            return f'a group\'s "id" is a short name of its own (letters, digits, _ and -), got {group.get("id")!r}'
        ids.append(group["id"])
        if not isinstance(group.get("label"), str) or not group["label"].strip() or len(group["label"]) > POPULATION_LABEL_MAX:
            return f"a group's label is a short text (at most {POPULATION_LABEL_MAX} characters), got {group.get('label')!r}"
        if not isinstance(group.get("count"), int) or isinstance(group["count"], bool) or group["count"] < 1:
            return (f'a group\'s "count" is its number of dots, a whole number from 1 (a group under one dot: '
                    f'make "per" smaller); got {group.get("count")!r}')
        if "color" in group and not (isinstance(group["color"], str) and HEX_COLOR.fullmatch(group["color"])):
            return f'a group\'s "color" is "#RRGGBB", got {group.get("color")!r}'
    if sum(g["count"] for g in groups) > total:
        return f'the groups have {sum(g["count"] for g in groups)} dots in all, more than "total" ({total})'
    rest = state.get("rest", "")
    if not isinstance(rest, str) or len(rest) > POPULATION_LABEL_MAX:
        return f'"rest" names the grey dots, a short text (at most {POPULATION_LABEL_MAX} characters); got {rest!r}'
    return None


def race_problem(state):
    """Why a SPEED_RACE initial_state is wrong (see above), or None."""
    if not is_number(state.get("distance")) or state["distance"] <= 0 or state.get("distance_unit") not in RACE_DISTANCE_UNITS:
        return (f'SPEED_RACE needs the track\'s length: "distance": <number > 0>, "distance_unit": one of '
                f'{list(RACE_DISTANCE_UNITS)}; got {state.get("distance")!r} {state.get("distance_unit")!r}')
    runners = state.get("runners")
    if not isinstance(runners, list) or not RACE_RUNNERS[0] <= len(runners) <= RACE_RUNNERS[1]:
        return (f'SPEED_RACE needs "runners": {RACE_RUNNERS[0]} to {RACE_RUNNERS[1]} of {{"label": "...", "speed": '
                f'<number > 0>, "unit": one of {list(RACE_SPEED_UNITS)}, "icon": <an OBJECT icon>}}; got {runners!r}'[:300])
    for runner in runners:
        if not isinstance(runner, dict) or set(runner) - {"label", "speed", "unit", "icon"}:
            return f'a runner is {{"label", "speed", "unit", "icon"}}, got {runner!r}'[:300]
        if not isinstance(runner.get("label"), str) or not runner["label"].strip() or len(runner["label"]) > RACE_LABEL_MAX:
            return f"a runner's label is a short text (at most {RACE_LABEL_MAX} characters), got {runner.get('label')!r}"
        if not is_number(runner.get("speed")) or runner["speed"] <= 0 or runner.get("unit") not in RACE_SPEED_UNITS:
            return (f'a runner\'s "speed" is a number > 0 in "unit", one of {list(RACE_SPEED_UNITS)} (0.1 mm/s, '
                    f'200000 km/s); got {runner.get("speed")!r} {runner.get("unit")!r}')
        if runner.get("icon", DEFAULT_OBJECT_ICON) not in OBJECT_ICON_NAMES:
            return f"a runner's icon is an OBJECT icon, got {runner.get('icon')!r}"
    return None


def seesaw_problem(state):
    """Why a SEESAW initial_state is wrong (see above), or None."""
    sides = [state.get(side) for side in ("left", "right")]
    for side, load in zip(("left", "right"), sides):
        if not isinstance(load, dict) or set(load) - {"label", "weight", "value"}:
            return f'SEESAW needs "{side}": {{"label": "...", "weight": <number > 0>, "value": <number, optional>}}, got {load!r}'[:300]
        if not is_number(load.get("weight")) or load["weight"] <= 0:
            return f'the {side} load\'s "weight" must be a number > 0, got {load.get("weight")!r}'
        if not isinstance(load.get("label", ""), str) or len(load.get("label", "")) > SEESAW_LABEL_MAX:
            return f"the {side} load's label is a short text (at most {SEESAW_LABEL_MAX} characters)"
        if "value" in load and not is_number(load["value"]):
            return f'the {side} load\'s "value" must be a number, got {load["value"]!r}'
    if ("value" in sides[0]) != ("value" in sides[1]):
        return 'give a "value" to both loads or to neither'
    if not isinstance(state.get("unit", ""), str) or len(state.get("unit", "")) > 8:
        return '"unit" is a short text (at most 8 characters), e.g. "/20", "€"'
    return None


# Semantic positions -> scene coordinates (x right, y up; the frame is 14.2 x 8 units).
SEMANTIC_COLUMNS = {"LEFT": -4.6, "CENTER": 0.0, "RIGHT": 4.6}
SEMANTIC_ROWS = {"TOP": 1.45, "MIDDLE": -0.45, "BOTTOM": -2.3}


def scene_point(position):
    """"TOP_LEFT" or [x, y, z] -> (x, y) in scene units."""
    if isinstance(position, str):
        row, column = "MIDDLE", "CENTER"
        for part in position.upper().split("_"):
            row = part if part in SEMANTIC_ROWS else row
            column = part if part in SEMANTIC_COLUMNS else column
        return SEMANTIC_COLUMNS[column], SEMANTIC_ROWS[row]
    return float(position[0]), float(position[1])


def split_pin(pin):
    """"lamp_1.left_terminal" -> ("lamp_1", "left_terminal"); None if it is not "<id>.<port>"."""
    if not isinstance(pin, str):
        return None
    entity_id, dot, port = pin.rpartition(".")
    return (entity_id, port) if dot and entity_id and port else None


# "direction" of an ARROW_ANNOTATION (where its arrow points) or a VECTOR_ARROW, in scene axes (x right,
# y up). Either a cardinal name, case-insensitive (the original format, drawn exactly as before):
#     "UP" | "DOWN" | "LEFT" | "RIGHT"
# or a vector [x, y] of two real numbers, of any length but not [0, 0] (the renderers normalise it and
# draw at the angle atan2(y, x)): [0.4, 0.9] is an axis tilted ~23.5° from the vertical (the Earth's),
# [1, 1] points up-right at 45°.
# A VECTOR_ARROW anchored on a curve ("anchor", see check_anchor) may also take, worked out from the
# curve by the renderers (app/curve_math.py): "TANGENT" (along it, the way t or x grows: a velocity),
# "CENTER" (towards the middle of its drawing, an orbit's centre: gravity) or "OUTWARD".
CARDINAL_DIRECTIONS = {"UP": (0.0, 1.0), "DOWN": (0.0, -1.0), "LEFT": (-1.0, 0.0), "RIGHT": (1.0, 0.0)}
ANCHORED_DIRECTIONS = ("TANGENT", "CENTER", "OUTWARD")
DIRECTED_TYPES = ("ARROW_ANNOTATION", "VECTOR_ARROW")


def direction_problem(value, anchored=False):
    """Why `value` is not a valid "direction" (see above), or None. `anchored`: the vector has an
    "anchor" on a curve, so TANGENT / CENTER / OUTWARD are allowed too."""
    if isinstance(value, str):
        if value.upper() in CARDINAL_DIRECTIONS:
            return None
        if value.upper() in ANCHORED_DIRECTIONS:
            return None if anchored else (f"direction {value!r} needs an \"anchor\" on a curve "
                                          f"(e.g. {{\"curve\": \"orbit\", \"t\": 0}})")
    elif isinstance(value, (list, tuple)):
        numbers = [v for v in value if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
        if len(value) == 2 and len(numbers) == 2:
            return None if any(numbers) else "direction [0, 0] has no angle"
    return (f'direction must be "UP", "DOWN", "LEFT", "RIGHT" or a vector [x, y] of two numbers '
            f"(e.g. [0.4, 0.9] for an axis tilted 23.5° from the vertical), got {value!r}")


# An axis name that carries a measure: a unit or a number in it ("PIB (milliards d'€)", "temps (s)",
# "années"), or a maths variable of its own ("x", "t"). Without one ("orbite", "hauteur"), the axes
# are a sketch: numbers along them would be made up.
UNIT_MARK = re.compile(r"[(%€$°/]|\d|\b(?:années?|ans|mois|jours?|heures?|secondes?|mètres?|km|kg|euros?|dollars?|habitants?|milliards?|millions?)\b")


def measured_axis(name):
    """Does an axis named so carry numbers? (see UNIT_MARK; an unnamed axis does, as before)"""
    name = str(name or "").strip()
    return not name or len(name) <= 2 or bool(UNIT_MARK.search(name.lower()))


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# A VECTOR_ARROW's "symbol": the short name drawn by the arrow ("P"), its "label" ("Poids") going in
# the scene's legend: letters (Greek included), digits, "_" and "'", 1 to 3 of them.
VECTOR_SYMBOL = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ\u0370-\u03FF0-9_']{1,3}")
ANCHORED_TYPES = ("VECTOR_ARROW", "BODY", "OBJECT")
# The icon types (a SCALE, a BANK...) take one anchor only: {"body": id}, riding in a BODY or OBJECT
# (a scale in a falling elevator). Any other type has no anchor: one given is an error, never ignored.
RIDING_TYPES = tuple(t.value for t in SVG_TYPES)


def check_anchor(anchor, rides=False, curve=True):
    """Raise ValueError unless an "anchor" is
      {"curve": "<CURVE_PLOT id>", "t": <number>} (a parametric curve) or {"curve": ..., "x": <number>}
        (y = f(x)): on that point of the curve (VECTOR_ARROW, BODY; `curve`)
      {"axes": "<AXES_GRAPH or CURVE_PLOT id>", "x": <number>, "y": <number>}: on that point of the
        graph, in its own units (VECTOR_ARROW, BODY, OBJECT): the Earth at the centre of an orbit
      {"body": "<BODY or OBJECT id>"}: on that body or object, following it when it moves: a vector
        starts on it, a BODY or an OBJECT rides in it, drawn beside it (an astronaut in the ISS, a
        ball in a falling elevator) (`rides`)
    That the curve, axes or body exists, and is of the right kind, is checked with the whole scene
    (SceneVisualBrief)."""
    if rides and isinstance(anchor, dict) and set(anchor) == {"body"} and isinstance(anchor["body"], str):
        return
    if (isinstance(anchor, dict) and set(anchor) == {"axes", "x", "y"} and isinstance(anchor["axes"], str)
            and is_number(anchor["x"]) and is_number(anchor["y"])):
        return
    if not curve:
        raise ValueError(f'anchor must be {{"axes": "<AXES_GRAPH id>", "x": <number>, "y": <number>}}, or '
                         f'{{"body": "<BODY or OBJECT id>"}} to ride in it; got {anchor!r}')
    if (not isinstance(anchor, dict) or not isinstance(anchor.get("curve"), str) or set(anchor) - {"curve", "t", "x"}
            or len(set(anchor) & {"t", "x"}) != 1 or not is_number(anchor.get("t", anchor.get("x")))):
        raise ValueError('anchor must be {"curve": "<CURVE_PLOT id>", "t": <number>} for a parametric curve, '
                         'or {"curve": ..., "x": <number>} for y = f(x), or {"axes": "<AXES_GRAPH id>", "x": <number>, '
                         '"y": <number>} for a point of a graph'
                         + (', or {"body": "<BODY or OBJECT id>"} to ride on it' if rides else "") + f"; got {anchor!r}")


MAX_MOVE_SECONDS = 60.0
EASINGS = ("smooth", "fall", "linear")   # a free move's pace: eases in and out / speeds up (gravity) / even


def move_problem(action, entities):
    """Why a "move_along" or "move" action is wrong, or None. `entities` maps the scene's entity ids to
    (type, initial_state).
      {"action": "move_along", "target": "<BODY id anchored on a curve>", "to": <the t (or x) it goes
        to, along its curve>, "duration": <seconds, default 4>}: the body moves at an even pace from
        where it is (its anchor, or where its last move_along left it); "to" may go past the curve's
        t_max (another lap of an orbit).
      {"action": "move", "target": "<OBJECT or BODY id, not anchored>", "to": [x, y] (scene units,
        where its position goes), "duration": <seconds, default 2>, "easing": "smooth" | "fall" |
        "linear"}: a straight move, no graph needed (an elevator falling, a car driving); "fall"
        speeds up as a falling thing does. What rides in it goes with it."""
    kind, state = entities.get(action.get("target"), (None, {}))
    anchor = (state or {}).get("anchor") or {}
    if action.get("action") == "move":
        if kind not in (ComponentType.OBJECT, ComponentType.BODY):
            return f"move needs an OBJECT or BODY target, got {action.get('target')!r}"
        if anchor:
            return (f"move: {action['target']} is anchored ({anchor}): a body on a curve uses move_along, one that "
                    f"rides in another goes with it; drop the anchor to move it freely")
        to = action.get("to")
        if not (isinstance(to, (list, tuple)) and len(to) in (2, 3) and all(is_number(v) for v in to)):
            return f"move needs \"to\": [x, y], the scene point it goes to, got {to!r}"
        if action.get("easing", "smooth") not in EASINGS:
            return f"move easing must be one of {list(EASINGS)}, got {action.get('easing')!r}"
        default = 2
    else:
        if kind != ComponentType.BODY or "curve" not in anchor:
            return f"move_along needs a BODY target anchored on a curve, got {action.get('target')!r}"
        if not is_number(action.get("to")) or abs(action["to"]) > MAX_T_SPAN:
            return f"move_along needs \"to\": the t (or x) the body goes to on its curve, got {action.get('to')!r}"
        default = 4
    duration = action.get("duration", default)
    if not is_number(duration) or not 0 < duration <= MAX_MOVE_SECONDS:
        return f"{action.get('action')} duration must be seconds between 0 and {MAX_MOVE_SECONDS:g}, got {duration!r}"
    return None


def unit_direction(value, default="DOWN"):
    """A valid direction -> unit vector (dx, dy), scene axes. A cardinal gives its exact axis; a vector
    [x, y] gives (cos a, sin a) with a = atan2(y, x). Anything invalid gives `default`'s."""
    if direction_problem(value) is not None:
        value = default
    if isinstance(value, str):
        return CARDINAL_DIRECTIONS[value.upper()]
    angle = math.atan2(float(value[1]), float(value[0]))
    return math.cos(angle), math.sin(angle)


STATUS_MIN_CHARS = 20      # an annotation this long states a status ("Tension présente, courant nul")
TARGETED_MAX_CHARS = 40    # ... unless it names its target: then a pointer up to this length


def is_status_annotation(entity):
    """An ARROW_ANNOTATION that states the circuit's status rather than naming a part: a badge in the
    instrument column, with no arrow. Set by "kind": "status" (or "pointer") in its initial_state,
    else by its length: from STATUS_MIN_CHARS, or TARGETED_MAX_CHARS when it names a "target"
    ("Tension U (différence de potentiel)" points at its formula; a whole sentence goes to the column)."""
    if entity.get("type") != ComponentType.ARROW_ANNOTATION.value:
        return False
    state = entity.get("initial_state") or {}
    if state.get("kind") in ("status", "pointer"):
        return state["kind"] == "status"
    length = len(str(state.get("text") or ""))
    return length > TARGETED_MAX_CHARS if state.get("target") else length >= STATUS_MIN_CHARS


# Word cues: an action's "cue" is the words of the narration it happens on. Both are compared as
# lowercase words (apostrophes and punctuation split them), so "d’électrons" matches "d'électrons".
def narration_words(text):
    """[(character offset, lowercase word)] of a text."""
    return [(m.start(), m.group().lower()) for m in re.finditer(r"\w+", str(text or ""))]


def find_cue(words, cue, start=0):
    """Index in `words` (from narration_words) where the cue's words begin, searching from `start`,
    else None."""
    wanted = [w for _, w in narration_words(cue)]
    if not wanted:
        return None
    for i in range(start, len(words) - len(wanted) + 1):
        if all(words[i + k][1] == w for k, w in enumerate(wanted)):
            return i
    return None


# What a formula or a badge means, shown by its colour ("tone"): a result (green), a warning (amber),
# something wrong (red: the misconception, a contradiction), a key point (the theme's accent).
TONES = ("result", "warning", "wrong", "key")
TONED_TYPES = ("TEX_FORMULA", "ARROW_ANNOTATION")
# "emphasize": {"action": "emphasize", "target": <id>, "effect": "shake" | "pulse"}: a contradiction
# shakes (and flashes red), a result pulses; on any component, formula or badge.
EFFECTS = ("shake", "pulse")


def emphasis_problem(action, ids):
    """Why an "emphasize" action is wrong, or None. `ids`: the scene's entity ids."""
    if action.get("target") not in ids:
        return f"emphasize needs a \"target\": an entity of the scene, got {action.get('target')!r}"
    if action.get("effect") not in EFFECTS:
        return f"emphasize needs an \"effect\": one of {list(EFFECTS)}, got {action.get('effect')!r}"
    return None


def measure_problem(action, types):
    """Why a "measure" action is wrong, or None. `types` maps the scene's entity ids to their type.
    {"action": "measure", "target": <VOLTMETER_PROBES id>, "target_pin_a": "<id>.<port>" (red probe),
     "target_pin_b": "<id>.<port>" (black probe), "value": volts, "unit": "V" (optional)}; on a breadboard,
    a part's lead: "<board id>.<part id>.<lead>" (or "<board id>.<part id>", its first lead)."""
    if types.get(action.get("target")) != ComponentType.VOLTMETER_PROBES:
        return f"measure needs a VOLTMETER_PROBES target, got {action.get('target')!r}"
    pins = []
    for key in ("target_pin_a", "target_pin_b"):
        pin = split_pin(action.get(key))
        if pin is None:
            return f'measure {key} must be "<entity id>.<port>", got {action.get(key)!r}'
        entity_id, port = pin
        board = entity_id.split(".", 1)[0]
        if types.get(board) == ComponentType.BREADBOARD or (ComponentType.BREADBOARD == types.get(entity_id)):
            pins.append(pin)              # a lead on the breadboard: "<board>.<part>.<lead>" or "<board>.<part>"
            continue
        if entity_id not in types:
            return f"measure {key} refers to unknown entity {entity_id!r}"
        ports = COMPONENT_PORTS.get(ComponentType(types[entity_id]), ())
        if port not in ports:
            return f"measure {key}: {entity_id} has no port {port!r} (ports: {list(ports)})"
        pins.append(pin)
    if pins[0] == pins[1]:
        return "measure: the two probes must touch two different pins"
    value = action.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"measure needs a numeric value (volts), got {value!r}"
    return None

# CURVE_PLOT draws either
#   "func": y = f(x), a maths expression of x ("np.sin(x)", "0.5 * x**2 - 1"), or
#   "x_func" and "y_func": a parametric curve (x(t), y(t)), maths expressions of t, for t from "t_min"
#   to "t_max" (numbers; default 0 and 2*pi: one full turn). A circle of radius 2: "2*np.cos(t)",
#   "2*np.sin(t)"; an orbit (ellipse): "3*np.cos(t)", "2*np.sin(t)". Circles, orbits, ellipses,
#   spirals: what y = f(x) cannot draw. Never both forms on one curve.
# The expressions are checked here because the renderers evaluate them. Only the variable (x or t),
# numbers, pi, e, + - * / ** % and these numpy functions are allowed: no names, attributes or calls
# beyond them, so an LLM-written string can never run arbitrary code.
SAFE_MATH_FUNCTIONS = ("sin", "cos", "tan", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "exp", "log",
                       "log10", "log2", "sqrt", "abs", "floor", "ceil", "sign", "maximum", "minimum")
_SAFE_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call, ast.Attribute,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)


def check_function_expression(text, variable="x", field="func"):
    """Raise ValueError unless `text` is a safe expression of `variable`, e.g. "np.sin(x)", "0.5 * x**2 - 1"
    (or "np.cos(t)" for a parametric curve's x_func / y_func)."""
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise ValueError(f"{field} must be a short maths expression of {variable}")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"{field} is not a valid expression: {exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"{field} may not contain {type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError(f"{field} may only contain numbers")
        if isinstance(node, ast.Name) and node.id not in (variable, "np", "pi", "e") + SAFE_MATH_FUNCTIONS:
            raise ValueError(f"{field} may not use {node.id!r} (only {variable}, pi, e and "
                             f"np.{', np.'.join(SAFE_MATH_FUNCTIONS[:4])}...)")
        if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name) and node.value.id == "np"
                                                    and node.attr in SAFE_MATH_FUNCTIONS + ("pi", "e")):
            raise ValueError(f"{field} may not use .{node.attr}")
        if isinstance(node, ast.Call) and node.keywords:
            raise ValueError(f"{field} calls take no keyword arguments")


DEFAULT_T_RANGE = (0.0, 2 * math.pi)
MAX_T_SPAN = 1000.0


def is_parametric(state):
    """Does a CURVE_PLOT's initial_state describe a parametric curve (x_func / y_func)?"""
    return "x_func" in (state or {}) or "y_func" in (state or {})


def parameter_range(state):
    """A parametric curve's (t_min, t_max): the brief's numbers, else DEFAULT_T_RANGE."""
    low, high = (state or {}).get("t_min", DEFAULT_T_RANGE[0]), (state or {}).get("t_max", DEFAULT_T_RANGE[1])
    return float(low), float(high)


def check_curve(state):
    """Raise ValueError unless a CURVE_PLOT's initial_state has a safe "func" of x, or a safe "x_func"
    and "y_func" of t with numbers t_min < t_max (see above)."""
    if not is_parametric(state):
        check_function_expression(state.get("func"))
        return
    if "func" in state:
        raise ValueError('CURVE_PLOT has "func" or "x_func" + "y_func", not both')
    for field in ("x_func", "y_func"):
        if field not in state:
            raise ValueError(f'a parametric CURVE_PLOT needs both "x_func" and "y_func" (expressions of t); {field} is missing')
        check_function_expression(state[field], "t", field)
    for field in ("t_min", "t_max"):
        value = state.get(field)
        if field in state and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError(f"{field} must be a number, got {value!r}")
    low, high = parameter_range(state)
    if not low < high <= low + MAX_T_SPAN:
        raise ValueError(f"t_min must be below t_max (at most {MAX_T_SPAN:g} apart), got {low} and {high}")


class Layer(str, Enum):
    """Drawing order, back to front."""
    BACKGROUND = "BACKGROUND"
    CIRCUIT = "CIRCUIT"
    FLOW = "FLOW"
    OVERLAY = "OVERLAY"
    HUD = "HUD"


class StrictModel(BaseModel):
    # Unknown fields are an error, so a hallucinated field fails validation instead of being ignored.
    model_config = ConfigDict(extra="forbid")


class ConnectionSpec(StrictModel):
    """A wire from one component's port to another's, by logical port name."""
    source_id: str
    source_port: str = Field(description='e.g. "positive", "out"')
    target_id: str
    target_port: str = Field(description='e.g. "negative", "in"')
    dashed: bool = Field(default=False, description="an optional link (e.g. earth to chassis): drawn dashed")


class TextOverlay(StrictModel):
    title: str | None = None
    subtitle: str | None = None
    clear_previous: bool = True
    duration: float | None = Field(default=None, gt=0, description="Seconds on screen; None = until replaced")


class VisualEntity(StrictModel):
    id: str
    type: ComponentType
    layer: Layer = Layer.CIRCUIT
    position: tuple[float, float, float] | str = Field(
        description='Scene coordinates (x, y, z), x right and y up, or a semantic placement like "LEFT"')
    initial_state: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def concept_data_is_valid(self):
        """CURVE_PLOT needs a safe "func" (or "x_func" + "y_func"); TEX_FORMULA needs a "latex" string; an arrow's "direction",
        when given, is a cardinal or a vector [x, y] (see CARDINAL_DIRECTIONS)."""
        anchor = self.initial_state.get("anchor")
        if anchor is not None and self.type.value in RIDING_TYPES:
            if not (isinstance(anchor, dict) and set(anchor) == {"body"} and isinstance(anchor["body"], str)):
                raise ValueError(f'{self.id}: a {self.type.value} takes only "anchor": {{"body": "<BODY or OBJECT id>"}} '
                                 f'(it rides in it); got {anchor!r}')
        elif anchor is not None and self.type.value not in ANCHORED_TYPES:
            raise ValueError(f"{self.id}: a {self.type.value} takes no \"anchor\" (only VECTOR_ARROW, BODY, OBJECT, "
                             f"and the icon types riding in a body); drop it")
        elif anchor is not None:
            check_anchor(anchor, rides=True, curve=self.type != ComponentType.OBJECT)
        anchored = isinstance(anchor, dict) and ("curve" in anchor or "body" in anchor)   # TANGENT / CENTER need one
        if self.type.value in DIRECTED_TYPES and "direction" in self.initial_state:
            problem = direction_problem(self.initial_state["direction"], anchored)
            if problem:
                raise ValueError(f"{self.id}: {problem}")
        if self.type == ComponentType.VECTOR_ARROW and "symbol" in self.initial_state:
            symbol = self.initial_state["symbol"]
            if not isinstance(symbol, str) or not VECTOR_SYMBOL.fullmatch(symbol):
                raise ValueError(f'{self.id}: "symbol" is the short name drawn by the arrow (1 to 3 letters or digits, '
                                 f'e.g. "P", "R", "g", "v", "F_1"); its "label" goes in the legend; got {symbol!r}')
        if "tone" in self.initial_state and (self.type.value not in TONED_TYPES or self.initial_state["tone"] not in TONES):
            raise ValueError(f'{self.id}: "tone" is for a TEX_FORMULA or an ARROW_ANNOTATION, one of {list(TONES)}; '
                             f'got {self.initial_state["tone"]!r} on a {self.type.value}')
        if self.type == ComponentType.CURVE_PLOT:
            check_curve(self.initial_state)
        if self.type == ComponentType.OBJECT and self.initial_state.get("icon", DEFAULT_OBJECT_ICON) not in OBJECT_ICON_NAMES:
            raise ValueError(f"{self.id}: OBJECT icon must be one of {list(OBJECT_ICON_NAMES)}, "
                             f"got {self.initial_state.get('icon')!r}")
        if self.type == ComponentType.SEESAW and seesaw_problem(self.initial_state):
            raise ValueError(f"{self.id}: {seesaw_problem(self.initial_state)}")
        if self.type == ComponentType.VECTOR_ARROW and "value" in self.initial_state and (
                not is_number(self.initial_state["value"]) or self.initial_state["value"] == 0):
            raise ValueError(f'{self.id}: a vector\'s "value" is its magnitude, a number other than 0 (588 for 588 N); '
                             f'got {self.initial_state["value"]!r}')
        if self.type == ComponentType.LANES and lanes_problem(self.initial_state):
            raise ValueError(f"{self.id}: {lanes_problem(self.initial_state)}")
        if self.type == ComponentType.SPEED_RACE and race_problem(self.initial_state):
            raise ValueError(f"{self.id}: {race_problem(self.initial_state)}")
        if self.type == ComponentType.LOGIC_CIRCUIT and logic_problem(self.initial_state):
            raise ValueError(f"{self.id}: {logic_problem(self.initial_state)}")
        if self.type == ComponentType.BREADBOARD and breadboard_problem(self.initial_state):
            raise ValueError(f"{self.id}: {breadboard_problem(self.initial_state)}")
        if self.type == ComponentType.MICROCONTROLLER and mcu_problem(self.initial_state):
            raise ValueError(f"{self.id}: {mcu_problem(self.initial_state)}")
        if self.type == ComponentType.WAVE and wave_problem(self.initial_state):
            raise ValueError(f"{self.id}: {wave_problem(self.initial_state)}")
        if self.type == ComponentType.TUNNEL and tunnel_problem(self.initial_state):
            raise ValueError(f"{self.id}: {tunnel_problem(self.initial_state)}")
        if self.type == ComponentType.FPGA_GRID and fpga_problem(self.initial_state):
            raise ValueError(f"{self.id}: {fpga_problem(self.initial_state)}")
        if self.type == ComponentType.POPULATION and population_problem(self.initial_state):
            raise ValueError(f"{self.id}: {population_problem(self.initial_state)}")
        if self.type == ComponentType.TEX_FORMULA:
            latex = self.initial_state.get("latex")
            if not isinstance(latex, str) or not latex.strip() or len(latex) > 200:
                raise ValueError("TEX_FORMULA needs initial_state.latex: a short LaTeX string")
        return self


class SceneVisualBrief(StrictModel):
    scene_id: str
    text_overlay: TextOverlay | None
    entities: list[VisualEntity]
    connections: list[ConnectionSpec]
    actions: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_valid(self):
        """Entity ids are unique, every connection joins two entities of this scene, an anchored vector
        or body sits on a CURVE_PLOT of this scene, with "t" (within t_min..t_max) on a parametric
        curve, "x" on y = f(x), a point anchor names an AXES_GRAPH (or CURVE_PLOT) of this scene, a vector
        riding on a body names a BODY or an OBJECT (a BODY on a curve for TANGENT / CENTER / OUTWARD), and
        a BODY or OBJECT riding in another one names one that rides in nothing."""
        ids = [entity.id for entity in self.entities]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate entity ids: {duplicates}")
        by_id = {entity.id: entity for entity in self.entities}
        for entity in self.entities:
            anchor = entity.initial_state.get("anchor") if entity.type.value in ANCHORED_TYPES + RIDING_TYPES else None
            if anchor is None:
                continue
            if "axes" in anchor:
                axes = by_id.get(anchor["axes"])
                if axes is None or axes.type not in (ComponentType.AXES_GRAPH, ComponentType.CURVE_PLOT):
                    raise ValueError(f"{entity.id}: anchor axes {anchor['axes']!r} is not an AXES_GRAPH (or a CURVE_PLOT) of this scene")
                continue
            if "body" in anchor:
                body = by_id.get(anchor["body"])
                if body is None or body.type not in (ComponentType.BODY, ComponentType.OBJECT) or body.id == entity.id:
                    raise ValueError(f"{entity.id}: anchor body {anchor['body']!r} is not a BODY or an OBJECT of this scene")
                if entity.type != ComponentType.VECTOR_ARROW and "body" in ((body.initial_state.get("anchor") or {})
                                                                            if isinstance(body.initial_state.get("anchor"), dict) else {}):
                    raise ValueError(f"{entity.id}: {body.id} rides in another one already: ride in that one "
                                     f"({body.initial_state['anchor']['body']!r})")
                host_anchor = body.initial_state.get("anchor") if isinstance(body.initial_state.get("anchor"), dict) else {}
                if entity.type == ComponentType.VECTOR_ARROW and "body" in host_anchor:   # on a passenger: its host's curve
                    host = by_id.get(host_anchor["body"])
                    host_anchor = (host.initial_state.get("anchor") or {}) if host and host.type == ComponentType.BODY else {}
                    on_curve = isinstance(host_anchor, dict) and "curve" in host_anchor
                else:
                    on_curve = body.type == ComponentType.BODY and "curve" in host_anchor
                direction = entity.initial_state.get("direction")
                if not on_curve and isinstance(direction, str) and direction.upper() in ANCHORED_DIRECTIONS:
                    raise ValueError(f"{entity.id}: direction {direction!r} needs a body anchored on a curve (or riding "
                                     f"in one); {body.id} is not: give a cardinal or [dx, dy]")
                continue
            curve = by_id.get(anchor["curve"])
            if curve is None or curve.type != ComponentType.CURVE_PLOT:
                raise ValueError(f"{entity.id}: anchor curve {anchor['curve']!r} is not a CURVE_PLOT of this scene")
            if is_parametric(curve.initial_state):
                low, high = parameter_range(curve.initial_state)
                if "t" not in anchor or not low <= anchor["t"] <= high:
                    raise ValueError(f"{entity.id}: {curve.id} is parametric: the anchor needs \"t\" between {low:g} and {high:g}")
            elif "x" not in anchor:
                raise ValueError(f"{entity.id}: {curve.id} is y = f(x): the anchor needs \"x\", not \"t\"")
        for connection in self.connections:
            for end in (connection.source_id, connection.target_id):
                if end not in ids:
                    raise ValueError(f"connection refers to unknown entity {end!r}")
        return self
