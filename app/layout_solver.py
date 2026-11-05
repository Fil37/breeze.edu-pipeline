"""
Spatial arbiter: makes every scene's layout feasible before it is rendered. Deterministic, no LLM.
A module, not an agent (the orchestrator never calls it), used by three agents:
  - agent005_educationqa: solve_layout() on each brief, after its circuit fixes;
  - agent004_visualbriefgenerator and agent010_html_renderer: annotation_targets() and
    target_first_timing() (an annotation never appears before what it points at).

Works in screen pixels (1920 x 1080, y down) on bounding boxes [left, top, right, bottom] estimated
from the HTML renderer's sizes (agent010's CSS: drawing + label under it, text widths from the
font size). These are estimates: agent010 measures the real boxes, applies the same rules and
reports in render_manifest.json what still overlaps.

solve_layout(brief, corrections) -> conflicts left (empty list = certified), in this order:
  1. Zones: instruments and status badges (a long ARROW_ANNOTATION, or "kind": "status": it states
     the circuit's status, e.g. "Tension présente, courant nul") go to the right-hand column, away
     from the wires; when the column is used, the diagram is squeezed (shape kept) into the left
     part of the frame. Other annotations are pill badges with a 50 px arrow onto their component.
  2. Orphan arrows: an ARROW_ANNOTATION's tip and a VECTOR_ARROW's origin must touch a component
     (or, for a force, a point other forces start from). Otherwise the arrow is snapped to the
     nearest component; one under 20 px, or with nothing at all to point at, is removed together
     with its actions. A vector alone in a scene with nothing else is its own subject: kept.
     Target first: an annotation never appears before the entity it points at (target_first_timing,
     shared with agent004).
  3. Text bands: formula cards stacked in one column become one horizontal band under the title
     (top at 180 px, 24 px apart, wrapping onto a second row if needed).
  4. Title zone: nothing above y = 150 px (200 px with a subtitle): moved down.
  5. Collisions (AABB, 20 px gap): pushed apart along the axis where they overlap least. The band
     stays put; a graph only makes way for another graph; an arrow moves with what it points at.
  6. Verification: every pair, the title zone and the frame edges are checked again.
Positions are written back in scene coordinates [x, y, 0], only for what moved. Idempotent: a
second run on its own output changes nothing.
"""

import math
import re

from models.visual_brief_schema import (COMPONENT_PORTS, INSTRUMENT_TYPES, SVG_TYPES, ComponentType, is_status_annotation,
                                        scene_point)

SCREEN_W, SCREEN_H = 1920, 1080
PX_PER_UNIT = SCREEN_W / 14.222            # 135 px per scene unit, as in both renderers
HEADER, HEADER_WITH_SUBTITLE = 150, 200    # title zone: nothing may start above this y
EDGE = 20                                  # kept free along the frame's edges
GAP = 20                                   # between two boxes
SLACK = 2                                  # added to each push: positions are written to 0.01 unit (1.35 px)
WIRE_ROOM = 45                             # around a wired component: room for its wires to leave and turn
COLUMN_LEFT = round(SCREEN_W * 0.75)       # instrument column (agent010's MAIN_RIGHT)
MAIN_X, FULL_X = (123, 1311), (96, 1824)   # diagram centres, with / without the column
COLUMN_SCENE_X, COLUMN_TOP, COLUMN_STEP = 5.2, 1.2, 2.2   # instruments, in scene units
BAND_TOP_BELOW_HEADER = 30                 # band top = 180 px without a subtitle
BAND_GAP_X, BAND_GAP_Y = 24, 16
SNAP_PX = 40                               # an arrow end this close to a component touches it
MIN_ARROW_PX = 20
LABEL_GAP = 18                             # arrow label: off the arrow's line, on the perpendicular
ARROW_HALF_WIDTH = 16                      # a vector's arrowhead half width (the line itself is 10 px)
VECTOR_UNITS = 1.8                         # a vector's default length, in scene units
ANNOTATION_ARROW_PX, ANNOTATION_HALF_WIDTH = 50, 6   # an annotation's arrow (2 px line, 12 px head)
TIP_GAP = 6                                # between an annotation's tip and its component's drawing
PILL_SLIDE_KEEP = 20                       # a badge slid sideways still has its arrow this far inside its edge
PILL_FONT, PILL_PAD_X, PILL_H = 19, 17, 40   # an annotation's pill badge: 19 px text, 16 px padding + 1 px border (height measured)
CHAR_EM = 0.65                             # average glyph width in DejaVu Sans, in ems (labels)

# Drawing sizes in px (agent010's CSS), the label not included.
SHAPES = {"BATTERY": (190, 96), "LAMP": (110, 110), "SWITCH": (200, 90), "AMMETER": (158, 158),
          "WIRE_BUS": (160, 14), "EARTH_GROUND": (60, 65), "CHASSIS_MASS": (60, 65),
          "SUPPLY_RAIL": (70, 50), "RESISTOR": (140, 44), "POTENTIOMETER": (140, 80), "THERMISTOR": (140, 64), "OPAMP": (170, 160),
          "MOSFET": (120, 140), "DIODE": (120, 50), "LED": (120, 70), "HEATER": (150, 96)}
ICON_SIZE = (154, 154)                     # icon cards (and the bicycle parts, drawn as icons)
ICON_TYPES = {t.value for t in SVG_TYPES} | {"SPROCKET", "PEDAL_CRANK", "CHAIN_LINK", "OBJECT"}
CARD_SIZE = (150, 80)
LANES_W, LANE_H = 1260, 104                # LANES: labels + road + counts, and one lane's height
SEESAW_SIZE = (1100, 470)                  # SEESAW: the beam swinging, the loads on it, the mean under the pivot
RACE_W, RACE_ROW, RACE_EXTRA = 1400, 120, 114   # SPEED_RACE: label + track + time; a runner's row; the head and the ratio
POPULATION_SIZE = (700, 520)               # POPULATION: the head, the grid of dots, its legend under it
BREADBOARD_SIZE = (1080, 560)              # BREADBOARD: app/breadboard.py WIDTH, HEIGHT
MCU_SIZE = (760, 480)                      # MICROCONTROLLER: the chip, its memory and its unit, the count under it
WAVE_SIZE = (1300, 420)                    # WAVE: the medium across, its marked point, the energy over it
TUNNEL_SIZE = (1300, 440)                  # TUNNEL: a tube across, the wall a line in its middle
TIDES_SIZE = (1300, 600)                   # TIDES: the Earth in its ocean on the left, the Moon on the right
LOGIC_COL, LOGIC_ROW, LOGIC_EXTRA = 320, 190, (260, 90)   # LOGIC_CIRCUIT: a column per depth, a row per item, labels
FPGA_CELL, FPGA_EXTRA = 160, (300, 150)    # FPGA_GRID: a block and its routing channel; the bitstream, the list left out


def logic_depths(state):
    """Each input, gate and output's column: inputs 0, a gate one past its deepest feed, outputs last."""
    depth = {i.get("id"): 0 for i in state.get("inputs") or [] if isinstance(i, dict)}
    for gate in state.get("gates") or []:
        if isinstance(gate, dict):
            depth[gate.get("id")] = 1 + max((depth.get(f, 0) for f in gate.get("in") or []), default=0)
    last = max(depth.values(), default=0) + 1
    for out in state.get("outputs") or []:
        if isinstance(out, dict):
            depth[out.get("id")] = last
    return depth


PROGRAM_W, PROGRAM_LINE, PROGRAM_TOP = 520, 50, 110   # a LOGIC_CIRCUIT's program listing, on its right


def logic_size(state):
    depth = logic_depths(state)
    columns = max(depth.values(), default=1) + 1
    per_column = max([list(depth.values()).count(d) for d in set(depth.values())] or [1])
    width, height = LOGIC_COL * (columns - 1) + LOGIC_EXTRA[0], LOGIC_ROW * per_column + LOGIC_EXTRA[1]
    if state.get("program"):           # one line per gate and per output
        lines = len(state.get("gates") or []) + len(state.get("outputs") or [])
        width, height = width + PROGRAM_W, max(height, PROGRAM_TOP + lines * PROGRAM_LINE + 40)
    return width, height


RAIL_TYPES = {"CHASSIS_MASS": -1.25, "EARTH_GROUND": -1.25, "SUPPLY_RAIL": 1.25}
SCHEMATIC_PARTS = {"RESISTOR", "POTENTIOMETER", "THERMISTOR", "OPAMP", "MOSFET", "DIODE", "LED", "HEATER"}
SCHEMATIC_MIN = 4                                      # as agent004's: from this many parts a scene is a schematic   # beside a part: under it (0 V), over it (+V)


def split_rails(brief):
    """A ground or supply symbol wired to several parts becomes one symbol per part, put beside that
    part (under it for 0 V, over it for the supply) and coming in with it: on a schematic each part has
    its own, never a bundle of wires running back to one symbol. In place; returns the brief."""
    from models.visual_brief_schema import scene_point
    entities = brief.get("entities") or []
    by_id = {e.get("id"): e for e in entities}
    spawns = {a.get("target"): a for a in brief.get("actions") or [] if isinstance(a, dict) and a.get("action") == "spawn"}
    for rail in [e for e in entities if e.get("type") in RAIL_TYPES]:
        wires = [c for c in brief.get("connections") or [] if rail["id"] in (c.get("source_id"), c.get("target_id"))]
        for k, wire in enumerate(wires[1:], start=2):
            end = "source_id" if wire.get("source_id") == rail["id"] else "target_id"
            near = "target_id" if end == "source_id" else "source_id"
            other = by_id.get(wire.get(near))
            if other is None or other.get("type") in RAIL_TYPES:
                continue
            x, y = scene_point(other.get("position"))
            copy = {**rail, "id": f"{rail['id']}_{k}", "position": [round(x, 2), round(y + RAIL_TYPES[rail["type"]], 2), 0],
                    "initial_state": dict(rail.get("initial_state") or {})}
            entities.append(copy)
            by_id[copy["id"]] = copy
            wire[end] = copy["id"]
            if wire.get(near) in spawns:                     # it comes in with its part
                brief.setdefault("actions", []).append({**spawns[wire[near]], "target": copy["id"]})
    return brief


# Automatic schematic layout (place_schematic): the LLM's positions are not kept for the parts of a
# schematic. Each part's stage of the signal, from the sensors to the load, is a column (fixed x, so a
# part keeps its place from one build step to the next); a resistor or a diode takes the stage between
# the parts it joins. In a column the parts follow what they are wired to (the AOP's − input above its
# + input). A ground / supply symbol goes at the end of the lead it feeds.
STAGE = {"THERMISTOR": 0, "POTENTIOMETER": 0, "BATTERY": 0, "SWITCH": 1, "OPAMP": 2, "AMMETER": 3, "MOSFET": 4,
         "HEATER": 5, "LED": 5, "LAMP": 5}
FLOATING = ("RESISTOR", "DIODE")                       # stage between what they join
UNIT = SCREEN_W / 14.222                               # px per scene unit
SCHEMATIC_X = (-6.0, 5.6)                              # the columns' span, scene units (to 2.6 beside the instrument column)
SCHEMATIC_X_COLUMN = 2.6
SCHEMATIC_Y = (-1.7, 1.2)                              # the rows' span: room for a supply over, a ground under
PORT_AT = {                                            # (x, y) fractions of the drawing, as agent010's PORTS
    "RESISTOR": {"left": (0, .5), "right": (1, .5)}, "THERMISTOR": {"left": (0, .44), "right": (1, .44)},
    "POTENTIOMETER": {"left": (0, .25), "right": (1, .25), "wiper": (.5, 1)},
    "OPAMP": {"in_minus": (0, .3), "in_plus": (0, .7), "out": (1, .5), "vcc": (.47, 0), "gnd": (.47, 1)},
    "MOSFET": {"gate": (0, .64), "drain": (.75, 0), "source": (.75, 1)}, "DIODE": {"anode": (0, .5), "cathode": (1, .5)},
    "LED": {"anode": (0, .57), "cathode": (1, .57)}, "HEATER": {"left": (0, .68), "right": (1, .68)},
    "BATTERY": {"negative": (.25, 0), "positive": (.75, 0)}, "LAMP": {"left_terminal": (0, .5), "right_terminal": (1, .5)},
    "SWITCH": {"in": (0, .8), "out": (1, .8)}, "AMMETER": {"in": (0, .5), "out": (1, .5)}}


def port_offset(kind, port):
    """(dx, dy) in scene units from a part's centre to its lead (y up), and the lead's side."""
    w, h = SHAPES.get(kind, (140, 60))
    fx, fy = PORT_AT.get(kind, {}).get(port, (.5, .5))
    side = "left" if fx == 0 else "right" if fx == 1 else "up" if fy == 0 else "down" if fy == 1 else "right"
    return (fx - .5) * w / UNIT, (.5 - fy) * h / UNIT, side


def place_schematic(brief):
    """Lay a schematic's parts out (see above), in place; nothing for a scene with fewer than
    SCHEMATIC_MIN schematic parts. Returns the brief."""
    from models.visual_brief_schema import scene_point
    entities = brief.get("entities") or []
    kinds = {e["id"]: e["type"] for e in entities}
    if sum(t in SCHEMATIC_PARTS for t in kinds.values()) < SCHEMATIC_MIN:
        return brief
    parts = [e for e in entities if e["type"] in SCHEMATIC_PARTS or e["type"] in STAGE]
    ids = {e["id"] for e in parts}
    wires = [(c["source_id"], c.get("source_port"), c["target_id"], c.get("target_port"))
             for c in brief.get("connections") or [] if c.get("source_id") in ids and c.get("target_id") in ids]
    neighbours = {i: [] for i in ids}
    for a, pa, b, pb in wires:
        neighbours[a].append((b, pa, pb))
        neighbours[b].append((a, pb, pa))
    stage = {i: STAGE.get(kinds[i]) for i in ids}
    for _ in range(4):                                  # a resistor between its neighbours' stages
        for i in ids:
            if kinds[i] in FLOATING or stage[i] is None:
                known = [stage[n] for n, _, _ in neighbours[i] if stage[n] is not None]
                stage[i] = sum(known) / len(known) if known else 1
    column = {i: max(0, min(5, round(stage[i]))) for i in ids}
    low, high = SCHEMATIC_X[0], SCHEMATIC_X_COLUMN if uses_column(brief) else SCHEMATIC_X[1]
    x_of = lambda c: low + c * (high - low) / 5
    y = {i: 0.0 for i in ids}
    for _ in range(3):                                  # each part towards the leads it is wired to, then spread
        wanted = {}
        for i in ids:
            pulls = [y[n] + port_offset(kinds[n], pn)[1] - port_offset(kinds[i], pi)[1] for n, pi, pn in neighbours[i]]
            wanted[i] = sum(pulls) / len(pulls) if pulls else 0.0
        for c in set(column.values()):
            members = sorted((i for i in ids if column[i] == c), key=lambda i: (wanted[i], [e["id"] for e in parts].index(i)))
            members.reverse()                           # the highest first
            n = len(members)
            for k, i in enumerate(members):
                y[i] = SCHEMATIC_Y[1] - (SCHEMATIC_Y[1] - SCHEMATIC_Y[0]) * (k / (n - 1) if n > 1 else 0.5)
    for e in parts:
        e["position"] = [round(x_of(column[e["id"]]), 2), round(y[e["id"]], 2), 0]
    # ground and supply symbols at the end of the lead they feed
    for rail in (e for e in entities if e["type"] in RAIL_TYPES):
        wire = next((c for c in brief.get("connections") or [] if rail["id"] in (c.get("source_id"), c.get("target_id"))), None)
        if wire is None:
            continue
        other, port = (wire["target_id"], wire.get("target_port")) if wire["source_id"] == rail["id"] else (wire["source_id"], wire.get("source_port"))
        if other not in ids:
            continue
        ox, oy = scene_point(next(e["position"] for e in parts if e["id"] == other))
        dx, dy, side = port_offset(kinds[other], port)
        up = RAIL_TYPES[rail["type"]] > 0
        if side in ("up", "down"):
            rx, ry = ox + dx, oy + dy + (0.75 if side == "up" else -0.75)
        else:
            rx, ry = ox + dx + (0.6 if side == "right" else -0.6), oy + dy + (0.75 if up else -0.75)
        rail["position"] = [round(rx, 2), round(ry, 2), 0]
    return brief


def with_program(brief):
    """A LOGIC_CIRCUIT set to "sequential" (a program read step by step) shows its program: the same
    gates as instructions, one line each (initial_state "program": true, set here, in place)."""
    sequential = {a.get("target") for a in brief.get("actions") or [] if isinstance(a, dict) and a.get("action") == "set_state"
                  and isinstance(a.get("state"), dict) and a["state"].get("mode") == "sequential"}
    for entity in brief.get("entities") or []:
        if entity.get("type") == "LOGIC_CIRCUIT" and entity.get("id") in sequential:
            entity["initial_state"] = {**(entity.get("initial_state") or {}), "program": True}
    return brief
GRAPH_W, GRAPH_H = round(SCREEN_W * 0.7), round(SCREEN_H * 0.6) + 49   # + the legend under it (measured)
FORMULA_EM = 2.2 * 24 * 1.21               # KaTeX glyph size in px: 2.2rem of 24 px, times KaTeX's 1.21
FORMULA_PADDING, FORMULA_H = 76, 129       # card padding + border; a card's height (measured, with or without \frac)
ARROW_TYPES = ("VECTOR_ARROW", "ARROW_ANNOTATION")
MIN_SHOWN_SEC = 1.0                        # an annotation stays at least this long
DIRECTIONS = {"UP": (0, 1), "DOWN": (0, -1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


# ---------------------------------------------------------------- sizes

def text_size(text, font_px, max_width=None):
    """(width, height) of a text, wrapped at max_width."""
    width = len(str(text)) * CHAR_EM * font_px
    lines = max(1, math.ceil(width / max_width)) if max_width else 1
    return (min(width, max_width) if max_width else width), lines * font_px * 1.2


def label_size(text):
    """A component's label: 30 px, at most 360 px wide, 10 px side padding, 12 px above it."""
    width, height = text_size(text, 30, 360)
    return width + 20, height + 4 + 12


def formula_size(latex):
    """A KaTeX card, width in ems: a fraction is as wide as its wider part, = and x take their
    spacing, superscripts are small, other symbols about 0.6 em. Calibrated against agent010."""
    tex = latex or ""
    ems = 0.0
    for numerator, denominator in re.findall(r"\\d?frac\{([^{}]*)\}\{([^{}]*)\}", tex):
        ems += 0.55 * max(len(numerator), len(denominator), 1)
    tex = re.sub(r"\\d?frac\{[^{}]*\}\{[^{}]*\}", "", tex)
    for exponent in re.findall(r"\^\{?([^{}\s]+)\}?", tex):
        ems += 0.45 * len(exponent)
    tex = re.sub(r"\^\{?[^{}\s]+\}?", "", tex)
    operators = len(re.findall(r"\\(?:times|cdot|pm|leq|geq|neq|approx)|[=+\-<>]", tex))
    tex = re.sub(r"\\(?:times|cdot|pm|leq|geq|neq|approx)|[=+\-<>]", "", tex)
    symbols = len(re.sub(r"[{}_\s]", "", re.sub(r"\\[a-zA-Z]+", "x", tex)))
    ems += 1.3 * operators + 0.6 * symbols
    return ems * FORMULA_EM + FORMULA_PADDING, FORMULA_H


def slide(centre, size, low, high, anchor):
    """A badge's centre moved into [low, high] (its whole size inside), but never so far that the
    arrow's end `anchor` gets nearer than PILL_SLIDE_KEEP to its edge."""
    if size <= high - low:
        centre = min(max(centre, low + size / 2), high - size / 2)
    reach = max(size / 2 - PILL_SLIDE_KEEP, 0)
    return min(max(centre, anchor - reach), anchor + reach)


def own_axes(entity, ids):
    return entity["type"] == "CURVE_PLOT" and (entity.get("initial_state") or {}).get("axes") not in ids


def shape_size(entity, graph_count):
    kind, state = entity["type"], entity.get("initial_state") or {}
    if kind in SHAPES:
        return SHAPES[kind]
    if kind in ICON_TYPES:
        return ICON_SIZE
    if kind == "SEESAW":
        return SEESAW_SIZE
    if kind == "POPULATION":
        return POPULATION_SIZE
    if kind == "TIDES":
        return TIDES_SIZE
    if kind == "TUNNEL":
        return TUNNEL_SIZE
    if kind == "WAVE":                         # a standing wave: the two waves it is the sum of over it
        return (WAVE_SIZE[0], 620) if state.get("kind") == "standing" else WAVE_SIZE
    if kind == "MICROCONTROLLER":
        return MCU_SIZE
    if kind == "BREADBOARD":
        return BREADBOARD_SIZE
    if kind == "LOGIC_CIRCUIT":                # columns by depth (inputs, gates, outputs), a row per item
        return logic_size(state)
    if kind == "FPGA_GRID":
        cols, rows = state.get("cols"), state.get("rows")
        return (FPGA_CELL * (cols if isinstance(cols, int) else 4) + FPGA_EXTRA[0],
                FPGA_CELL * (rows if isinstance(rows, int) else 3) + FPGA_EXTRA[1])
    if kind == "SPEED_RACE":
        runners = state.get("runners")
        return RACE_W, RACE_EXTRA + RACE_ROW * (len(runners) if isinstance(runners, list) else 2)
    if kind == "LANES":
        lanes = state.get("lanes")
        return LANES_W, LANE_H * (len(lanes) if isinstance(lanes, list) else 2)
    if kind in ("AXES_GRAPH", "CURVE_PLOT"):
        return GRAPH_W / max(1, graph_count), GRAPH_H
    if kind == "TEX_FORMULA":
        return formula_size(state.get("latex"))
    return CARD_SIZE


# ---------------------------------------------------------------- geometry

def to_px(position):
    x, y = scene_point(position)
    return SCREEN_W / 2 + x * PX_PER_UNIT, SCREEN_H / 2 - y * PX_PER_UNIT


def to_scene(x, y):
    return [round((x - SCREEN_W / 2) / PX_PER_UNIT, 2), round((SCREEN_H / 2 - y) / PX_PER_UNIT, 2), 0]


def grid(x, y):
    """(x, y) on the grid positions are written on (0.01 unit): the solver checks exactly what it
    writes, so a second run finds nothing left to move."""
    return to_px(to_scene(x, y))


def overlap(a, b, gap=0):
    """How far boxes a and b (with `gap` between them) overlap on x and on y; both > 0 = collision."""
    return min(a[2], b[2]) - max(a[0], b[0]) + gap, min(a[3], b[3]) - max(a[1], b[1]) + gap


def collide(a, b, gap=0):
    ox, oy = overlap(a, b, gap)
    return ox > 0 and oy > 0


def union(*boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def distance_to_box(point, box):
    dx = max(box[0] - point[0], 0, point[0] - box[2])
    dy = max(box[1] - point[1], 0, point[1] - box[3])
    return math.hypot(dx, dy)


def screen_direction(value):
    """"DOWN" / [dx, dy] (scene axes, y up) -> unit vector on screen (y down)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        dx, dy = float(value[0]), float(value[1])
    else:
        dx, dy = DIRECTIONS.get(str(value).upper(), (0, -1))
    norm = math.hypot(dx, dy) or 1.0
    return dx / norm, -dy / norm


def label_normal(direction):
    """The side an arrow's label goes: perpendicular, to the right of a vertical arrow, below a
    horizontal one (the same rule as agent010)."""
    nx, ny = -direction[1], direction[0]
    if nx < -1e-6 or (abs(nx) <= 1e-6 and ny < 0):
        nx, ny = -nx, -ny
    return nx, ny


# ---------------------------------------------------------------- items

class Item:
    """One entity on screen: a box centred on (x, y), or an arrow from `start` to `end`."""

    def __init__(self, entity, graph_count, connections=()):
        self.entity, self.id, self.type = entity, entity["id"], entity["type"]
        state = entity.get("initial_state") or {}
        self.x, self.y = to_px(entity["position"])
        self.home = (self.x, self.y)
        self.anchor = None            # what an arrow points at (it moves with it)
        self.band = False             # in the formula band: does not move any more
        self.limits = (0, 0, SCREEN_W, SCREEN_H)   # where a badge may go (set by solve_layout)
        self.arrow = self.type in ARROW_TYPES
        if self.arrow:
            annotation = self.type == "ARROW_ANNOTATION"
            self.direction = screen_direction(state.get("direction", "DOWN"))
            self.length = (ANNOTATION_ARROW_PX if annotation
                           else float(state.get("length", VECTOR_UNITS) or 0) * PX_PER_UNIT)
            self.text = state.get("text") if annotation else state.get("label")
            self.tip_is_position = annotation       # an annotation's position is its tip
        else:
            self.w, self.h = shape_size(entity, graph_count)
            label = state.get("label")
            shows_label = label and self.type not in ("CURVE_PLOT", "WIRE_BUS")
            self.lw, self.lh = label_size(label) if shows_label else (0, 0)
            wired = any(entity["id"] in (c["source_id"], c["target_id"]) for c in connections)
            self.room = WIRE_ROOM if wired and COMPONENT_PORTS.get(ComponentType(self.type)) else 0

    # arrows
    def ends(self):
        dx, dy = self.direction
        if self.tip_is_position:
            return (self.x - dx * self.length, self.y - dy * self.length), (self.x, self.y)
        return (self.x, self.y), (self.x + dx * self.length, self.y + dy * self.length)

    def label_box(self):
        if not self.text:
            return None
        (sx, sy), (ex, ey) = self.ends()
        if self.tip_is_position:                    # an annotation's pill badge, beyond its arrow's tail
            width, height = text_size(self.text, PILL_FONT)[0] + 2 * PILL_PAD_X, PILL_H
            dx, dy = self.direction
            half = abs(dx) * width / 2 + abs(dy) * height / 2
            cx, cy = sx - dx * half, sy - dy * half
            # A wide badge slides along the arrow's end to stay in the frame (the arrow still meets it).
            left, top, right, bottom = self.limits
            if abs(dy) > 0.5:
                cx = slide(cx, width, left + EDGE, right - EDGE, sx)
            else:
                cy = slide(cy, height, top, bottom - EDGE, sy)
            return [cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2]
        width, height = text_size(self.text, 34)
        nx, ny = label_normal(self.direction)
        offset = LABEL_GAP + 5 + abs(nx) * width / 2 + abs(ny) * height / 2
        cx, cy = (sx + ex) / 2 + nx * offset, (sy + ey) / 2 + ny * offset
        return [cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2]

    # every item
    def box(self):
        if self.arrow:
            (sx, sy), (ex, ey) = self.ends()
            half = ANNOTATION_HALF_WIDTH if self.tip_is_position else ARROW_HALF_WIDTH
            line = [min(sx, ex) - half, min(sy, ey) - half, max(sx, ex) + half, max(sy, ey) + half]
            label = self.label_box()
            return union(line, label) if label else line
        width, height = max(self.w, self.lw) + 2 * self.room, self.h + self.lh + 2 * self.room
        return [self.x - width / 2, self.y - height / 2, self.x + width / 2, self.y + height / 2]

    def shape_box(self):
        """The drawing alone (what an arrow touches), the label left out."""
        top = self.y - (self.h + self.lh) / 2
        return [self.x - self.w / 2, top, self.x + self.w / 2, top + self.h]

    def drawn_box(self):
        """What is drawn (drawing + label), without the wiring room: for the title zone and the frame."""
        box = self.box()
        return [box[0] + self.room, box[1] + self.room, box[2] - self.room, box[3] - self.room] if not self.arrow else box

    def moved(self):
        return math.hypot(self.x - self.home[0], self.y - self.home[1]) > 0.5


# ---------------------------------------------------------------- the solver

def uses_column(brief):
    """The instrument column is needed for an instrument, a status badge, or a counter (set_value) on
    anything but an ammeter (an ammeter shows its value in its own dial)."""
    types = {e["id"]: e["type"] for e in brief["entities"]}
    return (any(ComponentType(t) in INSTRUMENT_TYPES for t in types.values())
            or any(is_status_annotation(e) for e in brief["entities"])
            or any(a.get("action") == "set_value" and types.get(a.get("target")) not in (None, "AMMETER")
                   for a in brief["actions"]))


def solve_layout(brief, corrections, template="circuit"):
    """Make the brief's layout feasible (see the module's docstring). Edits `brief` in place, adds a
    line to `corrections` for each change, and returns the conflicts it could not resolve.
    `template`: the scene's layout template (agent010's page). Only "circuit" has the instrument
    column (elsewhere status badges and counters make a row under the titles): nothing is squeezed
    to its left. On a "comparison", a thing never leaves its panel (A: x < 0, B: x > 0): a move that
    would take it across is undone."""
    where = f"scene {brief['scene_id']}"
    with_program(brief)
    split_rails(brief)
    place_schematic(brief)
    overlay = brief.get("text_overlay") or {}
    header = HEADER_WITH_SUBTITLE if overlay.get("subtitle") else HEADER
    column = uses_column(brief) and template == "circuit"
    before = {e["id"]: e["position"] for e in brief["entities"]}
    right = COLUMN_LEFT - 24 if column else SCREEN_W
    ids = {e["id"] for e in brief["entities"]}
    graph_count = sum(e["type"] == "AXES_GRAPH" or own_axes(e, ids) for e in brief["entities"])

    items, curves, instruments = {}, [], []
    for entity in brief["entities"]:
        if ComponentType(entity["type"]) in INSTRUMENT_TYPES or is_status_annotation(entity):
            instruments.append(entity)            # in the column: never near a wire
        elif entity["type"] == "CURVE_PLOT" and not own_axes(entity, ids):
            curves.append(entity)                 # drawn on its axes: it goes where they go
        else:
            items[entity["id"]] = Item(entity, graph_count, brief["connections"])
    graph_home = {i: (it.x, it.y) for i, it in items.items() if it.type == "AXES_GRAPH"}
    for item in items.values():
        item.limits = (0, header, right, SCREEN_H)

    place_instruments(instruments, column, where, corrections)
    if column:
        squeeze(items, right, where, corrections)
    sanitize_arrows(brief, items, where, corrections)
    target_first_timing(brief, {a.id: a.anchor for a in items.values() if a.arrow and a.tip_is_position and a.anchor},
                        where, corrections)
    band_formulas(items, header, right, where, corrections)
    clear_title_zone(items, header, right, where, corrections)
    choose_sides(items, header, right, where, corrections)
    for _ in range(3):                    # components moved: badges may need another side, and so on
        resolve_collisions(items, header, right, where, corrections)
        if not choose_sides(items, header, right, where, corrections):
            break

    for item in items.values():
        if item.moved():
            position = to_scene(item.x, item.y)
            side = lambda p: scene_point(p)[0] < 0
            if template == "comparison" and side(position) != side(before[item.id]):
                corrections.append(f"{where}: layout: {item.id} kept in its panel (the move would cross to the other one)")
                continue
            item.entity["position"] = position
    for curve in curves:                          # a curve keeps its axes' position
        axes = items.get((curve.get("initial_state") or {}).get("axes"))
        if axes is not None and axes.id in graph_home and axes.moved():
            curve["position"] = axes.entity["position"]
    return verify(items, header, right, where)


def place_instruments(instruments, column, where, corrections):
    if not column:
        return
    for i, entity in enumerate(instruments):
        target = [COLUMN_SCENE_X, round(COLUMN_TOP - i * COLUMN_STEP, 2), 0]
        if list(scene_point(entity["position"])) + [0] != target:
            entity["position"] = target
            what = "status badge" if is_status_annotation(entity) else "instrument"
            corrections.append(f"{where}: layout: {entity['id']} ({what}) moved to the instrument column")


def squeeze(items, right, where, corrections):
    """A component reaching into the column: the whole diagram is scaled into the main area, shape
    kept (arrows follow their targets: only components count)."""
    if all(it.drawn_box()[2] <= right for it in items.values() if not it.arrow):
        return
    scale = (MAIN_X[1] - MAIN_X[0]) / (FULL_X[1] - FULL_X[0])
    for it in items.values():
        it.x, it.y = grid(MAIN_X[0] + (min(max(it.x, FULL_X[0]), FULL_X[1]) - FULL_X[0]) * scale, it.y)
    corrections.append(f"{where}: layout: diagram squeezed into the left part (instrument column on the right)")


def remove_entity(brief, entity_id):
    """Take an entity out of the brief, with every action and wire that uses it."""
    brief["entities"] = [e for e in brief["entities"] if e["id"] != entity_id]
    brief["actions"] = [a for a in brief["actions"]
                        if a.get("target") != entity_id and entity_id not in (a.get("path") or [])]
    brief["connections"] = [c for c in brief["connections"] if entity_id not in (c["source_id"], c["target_id"])]


def sanitize_arrows(brief, items, where, corrections):
    """Every arrow must point at something real (see the module's docstring)."""
    solids = [it for it in items.values() if not it.arrow]
    arrows = sorted((it for it in items.values() if it.arrow), key=lambda it: it.type != "ARROW_ANNOTATION")
    for arrow in arrows:
        if arrow.length < MIN_ARROW_PX:
            remove_entity(brief, arrow.id)
            del items[arrow.id]
            corrections.append(f"{where}: layout: removed {arrow.id} (an arrow under {MIN_ARROW_PX} px)")
            continue
        (sx, sy), (ex, ey) = arrow.ends()
        point = (ex, ey) if arrow.tip_is_position else (sx, sy)   # the end that must touch something
        named = items.get((arrow.entity.get("initial_state") or {}).get("target"))
        if arrow.tip_is_position and named is not None and not named.arrow:   # it says what it points at
            if distance_to_box(point, named.drawn_box()) > SNAP_PX:
                land_tip(arrow, named)
                corrections.append(f"{where}: layout: {arrow.id} snapped to its target {named.id}")
            arrow.anchor = named.id
            continue
        reach = (lambda s: s.drawn_box()) if arrow.tip_is_position else (lambda s: s.shape_box())   # a badge may point at a label
        touching = [s for s in solids if distance_to_box(point, reach(s)) <= SNAP_PX]
        if touching:
            arrow.anchor = min(touching, key=lambda s: distance_to_box(point, reach(s))).id
            continue
        if not arrow.tip_is_position:              # a force may start where other forces start
            shared = [o for o in arrows if o is not arrow and not o.tip_is_position and o.id in items
                      and math.hypot(o.x - arrow.x, o.y - arrow.y) <= SNAP_PX]
            if shared:
                arrow.anchor = shared[0].anchor
                continue
        if not solids:
            if arrow.tip_is_position or len(items) > 1:
                remove_entity(brief, arrow.id)
                del items[arrow.id]
                corrections.append(f"{where}: layout: removed {arrow.id} (it points at nothing)")
            continue                               # a lone vector is the scene's subject: kept
        target = min(solids, key=lambda s: distance_to_box(point, s.shape_box()))
        if arrow.tip_is_position:
            land_tip(arrow, target)
        else:                                      # a force starts at the object's centre
            box = target.shape_box()
            arrow.x, arrow.y = grid((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        arrow.anchor = target.id
        corrections.append(f"{where}: layout: {arrow.id} pointed at empty space; snapped to {target.id}")


def annotation_targets(brief):
    """{annotation id: id of the entity it points at}, before any layout: its initial_state "target"
    when that names an entity, else the component whose drawing its tip touches (SNAP_PX). Status
    badges point at nothing."""
    ids = {e["id"] for e in brief["entities"]}
    solids = [Item(e, 1, brief["connections"]) for e in brief["entities"]
              if e["type"] not in ARROW_TYPES + ("CURVE_PLOT",) and ComponentType(e["type"]) not in INSTRUMENT_TYPES]
    targets = {}
    for entity in brief["entities"]:
        if entity["type"] != "ARROW_ANNOTATION" or is_status_annotation(entity):
            continue
        named = (entity.get("initial_state") or {}).get("target")
        if named in ids and named != entity["id"]:
            targets[entity["id"]] = named
            continue
        tip = to_px(entity["position"])
        near = sorted((distance_to_box(tip, s.shape_box()), s.id) for s in solids)
        if near and near[0][0] <= SNAP_PX:
            targets[entity["id"]] = near[0][1]
    return targets


def spawn_time(brief, entity_id):
    """When an entity appears: its first spawn, else 0 (there from the start)."""
    times = [a["at"] for a in brief["actions"] if a.get("action") == "spawn" and a.get("target") == entity_id
             and isinstance(a.get("at"), (int, float))]
    return min(times) if times else 0.0


def target_first_timing(brief, targets, where, corrections):
    """Target first: an annotation never appears before what it points at. Its spawn moves to its
    target's (both appear together; one is added if it had none); a fade_out that would now come
    less than MIN_SHOWN_SEC after it is dropped (it stays to the end of the scene)."""
    changed = False
    for arrow_id, target_id in targets.items():
        target_at = spawn_time(brief, target_id)
        if spawn_time(brief, arrow_id) >= target_at:
            continue
        spawns = [a for a in brief["actions"] if a.get("action") == "spawn" and a.get("target") == arrow_id]
        for action in spawns:
            action["at"] = max(action["at"], target_at)
        if not spawns:
            brief["actions"].append({"at": target_at, "action": "spawn", "target": arrow_id})
        brief["actions"] = [a for a in brief["actions"] if not (a.get("action") == "fade_out" and a.get("target") == arrow_id
                                                                and a.get("at", 0) < target_at + MIN_SHOWN_SEC)]
        corrections.append(f"{where}: timing: {arrow_id} now appears with {target_id} at {target_at} s "
                           f"(it pointed at it before it was there)")
        changed = True
    if changed:
        brief["actions"].sort(key=lambda a: a.get("at", 0))    # stable: same-time actions keep their order


def land_tip(arrow, target):
    """Put an annotation's tip TIP_GAP px off the side of `target`'s drawing that the arrow comes from
    (from below, off its label: it hangs under the drawing; as agent010)."""
    box, (dx, dy) = (target.drawn_box() if arrow.direction[1] < -0.5 else target.shape_box()), arrow.direction
    reach = abs(dx) * (box[2] - box[0]) / 2 + abs(dy) * (box[3] - box[1]) / 2 + TIP_GAP
    arrow.x, arrow.y = grid((box[0] + box[2]) / 2 - dx * reach, (box[1] + box[3]) / 2 - dy * reach)


def flipped(value):
    """The opposite direction, written the way the brief wrote it."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [-float(value[0]), -float(value[1])]
    return {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}.get(str(value).upper(), "UP")


def band_formulas(items, header, right, where, corrections):
    """Formula cards stacked in one column -> a balanced horizontal band under the title."""
    formulas = [it for it in items.values() if it.type == "TEX_FORMULA"]
    stacked = any(min(a.box()[2], b.box()[2]) > max(a.box()[0], b.box()[0])
                  for i, a in enumerate(formulas) for b in formulas[i + 1:])
    if len(formulas) < 2 or not stacked:
        return
    rows, row, width = [], [], 0
    available = right - 2 * EDGE
    for it in sorted(formulas, key=lambda it: it.x):
        w = it.box()[2] - it.box()[0]
        if row and width + BAND_GAP_X + w > available:
            rows.append(row)
            row, width = [], 0
        width += (BAND_GAP_X if row else 0) + w
        row.append(it)
    rows.append(row)
    top = header + BAND_TOP_BELOW_HEADER
    for row in rows:
        widths = [it.box()[2] - it.box()[0] for it in row]
        height = max(it.box()[3] - it.box()[1] for it in row)
        x = (right - (sum(widths) + BAND_GAP_X * (len(row) - 1))) / 2
        for it, w in zip(row, widths):
            shift(items, it, x + w / 2, top + height / 2)
            it.band = True
            x += w + BAND_GAP_X
        top += height + BAND_GAP_Y
    corrections.append(f"{where}: layout: {len(formulas)} stacked formulas put side by side in a band under the title")


def attached(items, item):
    """The arrows that point at `item` (they move with it)."""
    return [a for a in items.values() if a.arrow and a.anchor == item.id]


def shift(items, item, x, y):
    """Put a component at (x, y); the arrows pointing at it follow."""
    x, y = grid(x, y)
    dx, dy = x - item.x, y - item.y
    item.x, item.y = x, y
    for arrow in attached(items, item):
        arrow.x, arrow.y = grid(arrow.x + dx, arrow.y + dy)


def move(items, item, x, y, header, right):
    """shift(), kept inside the frame and below the title zone (1 px inside: the grid may round 0.7 px)."""
    box = item.drawn_box()
    half_w, half_h = (box[2] - box[0]) / 2 + 1, (box[3] - box[1]) / 2 + 1
    shift(items, item, min(max(x, EDGE + half_w), right - EDGE - half_w),
          min(max(y, header + half_h), SCREEN_H - EDGE - half_h))


def clear_title_zone(items, header, right, where, corrections):
    """Nothing above the title line. An annotation coming down into its target from the title zone
    comes from the other side instead; then a component goes down with its arrows until the
    highest of them clears it (cards of the band stay in it)."""
    for arrow in [a for a in items.values() if a.arrow and a.anchor and a.tip_is_position]:
        if arrow.box()[1] < header:
            state = arrow.entity.setdefault("initial_state", {})
            state["direction"] = flipped(state.get("direction", "DOWN"))
            arrow.direction = screen_direction(state["direction"])
            land_tip(arrow, items[arrow.anchor])
            corrections.append(f"{where}: layout: {arrow.id} turned round (it reached into the title zone)")
    for item in [it for it in items.values() if not (it.arrow and it.anchor) and not it.band]:
        top = min([item.drawn_box()[1]] + [a.box()[1] for a in attached(items, item)])
        if top < header:
            move(items, item, item.x, item.y + header - top + SLACK, header, right)
            corrections.append(f"{where}: layout: {item.id} moved down out of the title zone")


def fixed(item):
    """Band cards and arrows with an anchor never move by themselves."""
    return item.band or (item.arrow and item.anchor is not None)


def related(a, b):
    """An arrow touches what it points at, and forces from the same object may cross: not collisions.
    Two annotation badges on one target are (they would cover each other)."""
    return (a.anchor == b.id or b.anchor == a.id
            or (a.anchor is not None and a.anchor == b.anchor and not (a.tip_is_position or b.tip_is_position)))


SIDES = ("DOWN", "UP", "LEFT", "RIGHT")
OPPOSITE = {"DOWN": "UP", "UP": "DOWN", "LEFT": "RIGHT", "RIGHT": "LEFT"}


def side_name(value):
    """The one of SIDES nearest to a direction ("DOWN" or [dx, dy])."""
    dx, dy = screen_direction(value)
    return max(SIDES, key=lambda name: dx * screen_direction(name)[0] + dy * screen_direction(name)[1])


def choose_sides(items, header, right, where, corrections):
    """Each annotation badge on the side of its target where it is clear: inside the frame, below
    the title, out of the column, off the other components and badges. The brief's side first, then
    the opposite one, then the two others (agent010 makes the same choice on the real boxes)."""
    notes = [a for a in items.values() if a.arrow and a.tip_is_position and a.anchor in items]
    solids = [it for it in items.values() if not it.arrow]
    placed, changed = [], False
    for note in notes:
        target = items[note.anchor]
        state = note.entity.setdefault("initial_state", {})
        current = side_name(state.get("direction", "DOWN"))
        options = [current, OPPOSITE[current]] + [n for n in SIDES if n not in (current, OPPOSITE[current])]

        def cost(name):
            note.direction = screen_direction(name)
            land_tip(note, target)
            box = note.box()
            outside = box[1] < header or box[0] < EDGE or box[2] > right - EDGE or box[3] > SCREEN_H - EDGE
            return (10000 * outside + 1000 * sum(collide(box, o.drawn_box(), GAP / 2) for o in solids if o is not target)
                    + 1000 * sum(collide(box, p, GAP / 2) for p in placed))

        costs = {name: cost(name) for name in options}
        best = min(options, key=lambda name: (costs[name], options.index(name)))
        note.direction = screen_direction(best)
        land_tip(note, target)
        placed.append(note.box())
        if best != current:
            state["direction"] = best
            corrections.append(f"{where}: layout: {note.id} goes on the {best.lower()} side of {target.id} (clear there)")
            changed = True
    return changed


def mover(items, item):
    """What moves when `item` must: an annotation's target (the annotation follows it), else itself."""
    return items[item.anchor] if item.arrow and item.tip_is_position and item.anchor in items else item


def resolve_collisions(items, header, right, where, corrections):
    """Push overlapping boxes apart along the axis of least overlap (away from the band: down). An
    annotation in the way moves with its target, so it never pins a component against the frame."""
    reported = set()
    for _ in range(40):
        changed = False
        values = list(items.values())
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                ma, mb = mover(items, a), mover(items, b)
                if ma is mb or related(a, b) or (fixed(ma) and fixed(mb)):
                    continue
                A, B = a.box(), b.box()
                ox, oy = overlap(A, B, GAP)
                if ox <= 0 or oy <= 0:
                    continue
                band = a.band or b.band
                axis = 1 if band else (0 if ox <= oy else 1)
                need = (oy if axis else ox) + SLACK
                sign = 1 if ((B[1] + B[3] - A[1] - A[3]) if axis else (B[0] + B[2] - A[0] - A[2])) >= 0 else -1
                if band:                            # the other one goes below the band
                    sign = 1 if a.band else -1
                # Share of the move: a fixed one does not move; a graph only for another graph.
                if fixed(ma) or (ma.type == "AXES_GRAPH" and mb.type != "AXES_GRAPH"):
                    share_a = 0.0
                elif fixed(mb) or (mb.type == "AXES_GRAPH" and ma.type != "AXES_GRAPH"):
                    share_a = 1.0
                else:
                    share_a = 0.5
                def push(item, amount):             # how far it really went (the frame may stop it)
                    before = (item.x, item.y)[axis]
                    move(items, item, item.x + (0 if axis else amount), item.y + (amount if axis else 0), header, right)
                    return abs((item.x, item.y)[axis] - before)
                plan = ((ma, share_a, -sign), (mb, 1 - share_a, sign))
                left = need
                for item, share, direction in plan:
                    if share and not fixed(item):
                        left -= push(item, direction * need * share)
                for item, share, direction in plan:  # what the frame stopped, the other one does (even a graph)
                    if left > 0.5 and not fixed(item):
                        left -= push(item, direction * left)
                for item, other in ((ma, b), (mb, a)):
                    if item.id not in reported and not fixed(item) and item.moved():
                        reported.add(item.id)
                        corrections.append(f"{where}: layout: {item.id} moved apart from {other.id} (boxes overlapped)")
                changed = True
        if not changed:
            break


def verify(items, header, right, where):
    """What still overlaps, sits in the title zone or leaves the frame (empty list = certified)."""
    conflicts = []
    values = list(items.values())
    for item in values:
        box = item.drawn_box()
        if box[1] < header - 0.5:
            conflicts.append(f"{where}: {item.id} enters the title zone (top at {box[1]:.0f} px < {header} px)")
        if box[0] < -0.5 or box[2] > SCREEN_W + 0.5 or box[3] > SCREEN_H + 0.5:
            conflicts.append(f"{where}: {item.id} leaves the frame")
        if not item.arrow and box[2] > right + 0.5:
            conflicts.append(f"{where}: {item.id} reaches into the instrument column")
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            if not related(a, b) and collide(a.box(), b.box()):
                conflicts.append(f"{where}: {a.id} overlaps {b.id}")
    return conflicts
