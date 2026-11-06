"""
INPUT:  instance/{channel_id}/storyboard.json (each scene with a visual_brief) + script.json
        + qa.json (verdict must be "pass") + settings (dry_run)
OUTPUT: instance/{channel_id}/video.mp4 + subtitles.srt + render_manifest.json = {video_path, duration,
        resolution, renderer_used "html_playwright", rendered_at, status, voice_engine, subtitles_path, scenes:[{scene_id,
        start_sec, end_sec, duration_sec, voice_sec, voice_engine, voice_fallback, layout_template,
        layout_conflicts, status, error}]}
NOTES:  The renderer (the Manim one, agent006, is retired): "web-style" motion design drawn by a browser.
        Per scene, in a temporary folder:
          1. scene_001.mp3   French voice-over (app/tts_manager.generate_voice: ElevenLabs, else
                             edge-tts with retries), with its word timings
          2. scene_001.html  one standalone page: the brief as JSON + a small script whose
                             seek(t) draws the scene at time t: CSS keyframes are paused and
                             scrubbed, "transitions" and electron positions (CSS offset-path) are
                             computed for t, nothing runs on the wall clock, so every frame is exact.
                             KaTeX (pinned npm package, hash-checked, cached in assets/katex/) is
                             inlined for formulas: the page never touches the network
          3. headless Chromium (Playwright) calls seek(i / FPS) for each frame and screenshots it;
             the JPEGs are piped straight into ffmpeg -> scene_001_visual.mp4
          4. ffmpeg joins picture and voice, then concatenates the scenes and normalizes the audio
             to -14 LUFS (app/render/video.py)
        All voice-overs are made before the browser starts: Playwright's sync API keeps an asyncio
        loop running, and edge-tts needs its own.
        Zones: when a scene has an instrument (VOLTMETER_PROBES), a status badge or counters, a
        column on the right holds the instruments and status badges, then one telemetry card per
        counter (flex, 16 px gaps); components and wires stay in the main area on the left.
        Annotations are pill badges with a short arrow (at most 50 px) onto their component's edge,
        put on the side where neither the badge nor the arrow touches a wire or another box. A "measure" moves red/black probes on Bezier
        cables onto two pins, rings the contacts and rolls the meter's display. No placeholder
        text: a type name is never drawn (junctions, annotation arrows, icons stand in).
        Draws: title/subtitle; components as cards (rounded, light border, soft shadow; lamp with a
        radial glow, battery, switch, ammeter; icons from the Lucide cache) popping in with a spring;
        right-angle wires on the named ports, routed around every component, at least 40 px from
        each other; glowing, pulsing electrons along them; axes (70 % x 60 % of the frame) with tick
        labels, curves (sampled here in Python, never evaluated in the page), vectors; KaTeX
        formulas; states; set_value counters.
        All LLM text goes into the page with textContent: it can never become HTML or script.
HEALTH: not_healthy if dry_run, a scene fell back to an error screen, or a scene's measured layout
        still has conflicts (overlaps, title zone, frame edges: "layout_conflicts" per scene);
        critical if an input is missing, a brief is invalid, QA did not pass, Playwright/Chromium
        or ffmpeg is missing, or the voice-over or the final assembly fails.
"""

import base64
import functools
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import channel_dir, finish, load_json, run_standalone, save_json, utc_now
from app import provenance
from app.curve_math import anchor_geometry, curve_at, curve_centre
from app.tts_manager import generate_voice, normalize_text_for_tts, voice_report   # the voice: ElevenLabs, else edge-tts
from app.render.asset_resolver import BASE_DIR, AssetResolver
from app.render import footage as film
from app.render.subtitles import srt, subtitle_cues
from app.render.fonts import font_face_css
from app.breadboard import breadboard_data
from app.layout_solver import (TREE_LEAF, TREE_LEVEL, EQUATION_LINE, simple_size, CHAIN_BOX, CHAIN_GAP, CHAIN_ROW, TABLE_ROW, chain_size, table_widths, FPGA_CELL, LOGIC_COL, PROGRAM_LINE, PROGRAM_TOP, PROGRAM_W, annotation_targets, logic_depths,
                               logic_size, place_schematic, split_rails, target_first_timing, with_program)
from app.render.soundtrack import soundtrack
from models.visual_brief_schema import PHYS_PIECES, SIMPLE_PIECES, UNIT_FACTORS as UNIT_FACTORS_RENDER
from models.visual_brief_schema import (TONES, DEFAULT_OBJECT_ICON, INSTRUMENT_TYPES, RACE_DISTANCE_UNITS, RACE_SPEED_UNITS, SVG_TYPES,
                                        check_curve, check_function_expression, find_cue,
                                        is_number, is_parametric, is_status_annotation, measured_axis, narration_words, parameter_range,
                                        scene_point, unit_direction)
from app.render.video import (END_FADE, END_HOLD, FPS, HEIGHT, PLACEHOLDER, TAIL_PAUSE, VIDEO_CODEC, WIDTH, check_briefs, concat_scenes,
                              ffmpeg, make_error_visual, mux_scene, scene_field)
from app.tts_manager import media_duration

AGENT = "agent010"
THEME = "light"          # the default when no channel theme is given: "light" or "dark" design tokens
# Each channel's theme: its colours (design tokens), its animated background, its fonts and the style
# of its titles. Fixed here, never from the LLM; the page checks every colour is a "#RRGGBB".
#   lab       electronics: dark, a printed-circuit grid and traces with pulses, a code-style step line
#   space     physics: dark, stars drifting in three layers (parallax), faint nebulae
#   notebook  math: light, a squared-paper grid, the title appearing word by word
#   data      economics: dark, a data grid, Space Grotesk titles, an upper-case accent line
# "effects": "glow" (dark themes: curves, parts and bodies lit), "area" (a filled area under y = f(x)).
DARK = {"card": "#0F172A", "border": "#1E293B", "ink": "#CBD5E1", "text": "#F1F5F9", "muted": "#94A3B8",
        "wire": "#7C8BA1", "bulb-off": "#1E293B", "ring": "#0F172A", "icon": "#E2E8F0"}   # wires well lit on the dark
THEMES = {
    "lab": {"mode": "dark", "background": "pcb", "title": "glow", "subtitle": "code", "fonts": ["Inter", "Fira Code"], "effects": ["glow"],
            "tokens": {**DARK, "bg": "#050914", "primary": "#38BDF8", "electron": "#38BDF8", "accent": "#10B981",
                       "grid": "#10B981", "glow1": "#0EA5E9", "glow2": "#10B981"}},
    "space": {"mode": "dark", "background": "stars", "title": "glow", "subtitle": "plain", "fonts": ["Inter"], "effects": ["glow"],
              "tokens": {**DARK, "bg": "#020617", "primary": "#60A5FA", "electron": "#93C5FD", "accent": "#A78BFA",
                         "grid": "#FFFFFF", "glow1": "#6366F1", "glow2": "#EC4899"}},
    "notebook": {"mode": "light", "background": "notebook", "title": "kinetic", "subtitle": "plain", "fonts": ["Inter"], "effects": [],
                 "tokens": {"bg": "#F8F9FA", "card": "#FFFFFF", "border": "#CBD5E1", "ink": "#334155", "text": "#1E293B",
                            "muted": "#64748B", "wire": "#94A3B8", "bulb-off": "#F1F5F9", "ring": "#FFFFFF", "icon": "#0F172A",
                            "primary": "#3B82F6", "electron": "#60A5FA", "accent": "#3B82F6", "grid": "#0F172A",
                            "glow1": "#F97316", "glow2": "#8B5CF6"}},
    "data": {"mode": "dark", "background": "data", "title": "display", "subtitle": "caps", "fonts": ["Inter", "Space Grotesk"],
             "effects": ["glow", "area"],
             "tokens": {**DARK, "bg": "#0B1120", "card": "#172033", "border": "#2A3A55", "primary": "#38BDF8",
                        "electron": "#38BDF8", "accent": "#38BDF8", "grid": "#38BDF8", "glow1": "#0EA5E9", "glow2": "#14B8A6"}},
}
CHANNEL_THEMES = {"electronics": "lab", "physics": "space", "math": "notebook", "economics": "data"}
DEFAULT_STYLE = {"name": "notebook", **THEMES["notebook"]}


def channel_style(channel_id):
    """The theme of "breeze_(math)" and the like (the word in brackets), else the default."""
    match = re.search(r"\(([a-z_]+)\)", str(channel_id or ""))
    name = CHANNEL_THEMES.get(match.group(1) if match else "")
    return {"name": name, **THEMES[name]} if name else dict(DEFAULT_STYLE)
JPEG_QUALITY = 92
PAGE_TIMEOUT_MS = 30_000

# Scene coordinates (a 3x3 grid of semantic places on 14.2 x 8 units, x right, y up) -> pixels.
UNITS_WIDE, UNITS_HIGH = 14.222, 8.0


def to_pixels(position):
    """"TOP_LEFT" or [x, y, z] in scene units -> (x, y) pixels from the top-left corner."""
    x, y = scene_point(position)
    return round(WIDTH / 2 + x * WIDTH / UNITS_WIDE), round(HEIGHT / 2 - y * HEIGHT / UNITS_HIGH)


SAME_CUE_STEP = 0.4      # s between two actions on the same spoken words (as agent004)
MOTIONS = ("move_along", "move")   # ... except moves after a move: things set moving on one cue go together


def timeline(brief, voice_duration, planned_duration, spoken=None):
    """The brief's actions as plain data for the page. An action with a "cue" starts when the voice
    says its words (spoken: [(seconds, word)] from generate_voice; searched in the brief's order, so a
    word said twice goes to the right action); the others, and every action when the words are
    unknown, have their time stretched to the voice. Actions on one cue follow each other
    SAME_CUE_STEP apart, but moves on one cue start together; an action without a cue planned at the
    same time as a cued one goes with it (two bodies set moving together stay together). Then target first:
    an annotation never appears before what it points at. Components no action spawns appear at
    the start, a little apart."""
    actions = [dict(a) for a in brief.get("actions", []) if isinstance(a, dict)]
    times = [float(a["at"]) for a in actions if isinstance(a.get("at"), (int, float))]
    planned = planned_duration or (max(times) + 2 if times else voice_duration)
    scale = voice_duration / planned
    latest = max(voice_duration - 0.6, 0)
    words = [(at, word) for at, text in (spoken or []) for _, word in narration_words(text)]
    position, last, cued, uncued = 0, None, {}, []
    for action in sorted(actions, key=lambda a: a.get("at") if isinstance(a.get("at"), (int, float)) else 0):
        at = action.get("at")
        planned_at = round(float(at), 2) if isinstance(at, (int, float)) else None
        action["at"] = float(at) * scale if isinstance(at, (int, float)) else 0.0
        cue = normalize_text_for_tts(action["cue"]) if isinstance(action.get("cue"), str) else None
        index = find_cue(words, cue, position) if words else None     # the voice read the normalized text:
        if index is None and words:                                   # "10x" was said "10 x"
            index = find_cue(words, cue)
        if index is not None:
            together = last and last[2] in MOTIONS and action.get("action") in MOTIONS
            action["at"] = (last[1] if together else last[1] + SAME_CUE_STEP) if last and last[0] == index else words[index][0]
            position, last = index, (index, action["at"], action.get("action"))
            cued.setdefault(planned_at, action["at"])
        else:
            uncued.append((planned_at, action))
        action["at"] = min(action["at"], latest)
    for planned_at, action in uncued:           # planned with a cued action: at the same moment as it
        if planned_at in cued:
            action["at"] = min(cued[planned_at], latest)
    timed = {**brief, "actions": actions}
    target_first_timing(timed, annotation_targets(timed), "", [])
    spawned = {a.get("target") for a in actions if a.get("action") == "spawn"}
    events = [{"at": 0.15 * i, "action": "spawn", "target": e["id"]}
              for i, e in enumerate(e for e in brief["entities"] if e["id"] not in spawned)]
    return sorted(events + timed["actions"], key=lambda event: event["at"])


def icon_data_uri(component_type, ink="#0F172A"):
    """The component's Lucide icon (cached by AssetResolver), as a data: URI the page can show
    with <img>: no network from the page. Its outline is drawn in `ink`, the theme's icon colour."""
    path, _source = AssetResolver().resolve(component_type)
    with open(path, encoding="utf-8") as f:
        svg = f.read().replace("currentColor", ICON_COLORS.get(component_type, ink))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


ICON_COLORS = {"TRENDING_UP": "#10B981", "TRENDING_DOWN": "#EF4444"}   # others: text colour
# Bicycle parts have no drawing of their own here: a Lucide icon stands in (never their type name).
ICON_STANDINS = {"SPROCKET": "cog", "PEDAL_CRANK": "bike", "CHAIN_LINK": "link"}


SCENE_PX_PER_UNIT = WIDTH / UNITS_WIDE      # 135 px per scene unit at 1920 px
DEFAULT_X_RANGE, DEFAULT_Y_RANGE = (-5.0, 5.0), (-3.0, 3.0)
CURVE_SAMPLES = 240
PARAMETRIC_SAMPLES = 360      # a full turn: one point per degree


def number_range(value, default):
    """[min, max] (or [min, max, step]) from the brief, else the default."""
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
        if float(value[1]) > float(value[0]):
            return [float(value[0]), float(value[1])]
    return list(default)


def evaluate(text, variable, values):
    """A safe expression (checked by the schema) of `variable` at numpy `values`, with no builtins."""
    code = compile(text.strip(), "<func>", "eval")
    namespace = {"__builtins__": {}, "np": np, "pi": np.pi, "e": np.e}
    namespace.update({name: getattr(np, name) for name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs")})
    with np.errstate(all="ignore"):
        return np.broadcast_to(np.asarray(eval(code, namespace, {variable: values}), dtype=float), values.shape)


def sample_parametric(state, x_range=None, y_range=None):
    """Points [x, y] of a parametric CURVE_PLOT (x_func, y_func of t from t_min to t_max), sampled here
    in Python like "func". An undefined point, or one far outside the axes (a quarter of their span
    beyond them) when the curve sits on an AXES_GRAPH, becomes [0, None]: a gap. Returns (points,
    closed): closed when it has no gap and ends where it starts (a circle, an orbit)."""
    check_curve(state)
    ts = np.linspace(*parameter_range(state), PARAMETRIC_SAMPLES)
    xs, ys = evaluate(state["x_func"], "t", ts), evaluate(state["y_func"], "t", ts)
    ok = np.isfinite(xs) & np.isfinite(ys)
    for values, bounds in ((xs, x_range), (ys, y_range)):
        if bounds:
            margin = 0.25 * (bounds[1] - bounds[0])
            ok &= (values >= bounds[0] - margin) & (values <= bounds[1] + margin)
    points = [[round(float(x), 4), round(float(y), 4)] if good else [0.0, None] for x, y, good in zip(xs, ys, ok)]
    span = max(float(np.ptp(xs[ok])), float(np.ptp(ys[ok])), 1e-9) if ok.any() else 1.0
    closed = bool(ok.all()) and math.hypot(xs[0] - xs[-1], ys[0] - ys[-1]) <= 1e-3 * span
    return points, closed


def parametric_box(points):
    """Own axes for a parametric curve: its bounding box, 20 % wider each way, holding the origin."""
    xs = [p[0] for p in points if p[1] is not None] or [0.0]
    ys = [p[1] for p in points if p[1] is not None] or [0.0]
    box = []
    for low, high in ((min(xs + [0.0]), max(xs + [0.0])), (min(ys + [0.0]), max(ys + [0.0]))):
        pad = 0.2 * max(high - low, 1e-6)
        box.append([round(low - pad, 3), round(high + pad, 3)])
    return box


def sample_function(text, x_range, y_range):
    """Points [x, y] of a CURVE_PLOT "func", sampled here in Python (the page never evaluates code).
    The expression was checked by the schema; it is checked again, then run with numpy and no
    builtins. Points outside the y range or undefined (1/x at 0...) become None: a gap."""
    check_function_expression(text)
    code = compile(text.strip(), "<func>", "eval")
    namespace = {"__builtins__": {}, "np": np, "pi": np.pi, "e": np.e}
    namespace.update({name: getattr(np, name) for name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs")})
    xs = np.linspace(x_range[0], x_range[1], CURVE_SAMPLES)
    with np.errstate(all="ignore"):
        ys = np.broadcast_to(np.asarray(eval(code, namespace, {"x": xs}), dtype=float), xs.shape)
    margin = 0.05 * (y_range[1] - y_range[0])
    return [[round(float(x), 4), round(float(y), 4) if np.isfinite(y) and y_range[0] - margin <= y <= y_range[1] + margin
             else None] for x, y in zip(xs, ys)]


def vector_direction(value, default):
    """"UP" / "DOWN" / "LEFT" / "RIGHT" / [x, y] (scene axes, y up) -> unit vector [dx, dy]: a cardinal
    exactly as before, a vector at the angle atan2(y, x) (unit_direction). The page draws along it."""
    return list(unit_direction(value, default))


def direction_degrees(direction):
    """A unit vector [dx, dy] -> its angle in degrees, atan2(dy, dx) (0 = right, 90 = up)."""
    return round(math.degrees(math.atan2(direction[1], direction[0])), 2)


SPHERES = {"earth": "earth", "globe": "earth", "moon": "moon", "sun": "sun"}   # OBJECT icons drawn as spheres


# A plain text (a title, a label, an axis name) written in LaTeX by the LLM, "10^{-n}", "t_n": shown
# with Unicode exponents and indices, "10⁻ⁿ", "tₙ", when every character has one; left as written otherwise.
SUPER = str.maketrans("0123456789+-=()nix", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣ")
SUB = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
PLAIN_MATH = re.compile(r"(?<=[\w)}])([\^_])(?:\{([^{}]{1,8})\}|(-?\w))")


def french_amount(x):
    """A positive number as said in French, about 3 significant digits: 1 000, 2,5, 0,96."""
    if x >= 99.5:
        return f"{round(x):,}".replace(",", "\u202f")
    return f"{x:.{1 if x >= 9.95 else 2}f}".rstrip("0").rstrip(".").replace(".", ",")


def french_big(x):
    """A large count in words past a million: 2 000 milliards, 3,5 millions, 800."""
    for size, word in ((1e9, "milliards"), (1e6, "millions")):
        if x >= size:
            return f"{french_amount(x / size)} {word}"
    return french_amount(x)


def race_time(seconds):
    """A duration in the unit a viewer pictures: 5 ns, 30 µs, 2,5 s, 2 h 47 min, 11 jours, 3 200 ans."""
    for limit, size, unit in ((1e-6, 1e-9, "ns"), (1e-3, 1e-6, "µs"), (1, 1e-3, "ms"), (60, 1, "s")):
        if seconds < limit:
            return f"{french_amount(seconds / size)} {unit}"
    if seconds < 600:
        minutes, rest = divmod(round(seconds), 60)
        return f"{minutes} min {rest:02d} s" if rest else f"{minutes} min"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    if seconds < 86400:
        hours, rest = divmod(minutes, 60)
        return f"{hours} h {rest:02d} min" if rest else f"{hours} h"
    days = seconds / 86400
    if days < 730:
        return f"{french_amount(days)} jours"
    return f"{french_big(days / 365.25)} ans"


def race_data(state, ink):
    """SPEED_RACE: each runner's share of the fastest's speed (its pace on the one track), its real
    time over the track, and how many times faster the fastest goes than the slowest."""
    distance = float(state["distance"]) * RACE_DISTANCE_UNITS[state["distance_unit"]]
    speeds = [float(r["speed"]) * RACE_SPEED_UNITS[r["unit"]] for r in state["runners"]]
    fastest, slowest = speeds.index(max(speeds)), speeds.index(min(speeds))
    times = french_big(speeds[fastest] / speeds[slowest])     # "2 000 milliards" (de fois), "800" (fois)
    return {"distance": f"{french_amount(float(state['distance']))} {state['distance_unit']}",
            "runners": [{"label": plain_math(r.get("label")), "share": v / speeds[fastest], "time": race_time(distance / v),
                         "icon": icon_data_uri(r.get("icon", DEFAULT_OBJECT_ICON), ink)} for r, v in zip(state["runners"], speeds)],
            "fastest": fastest,
            "ratio": f"{plain_math(state['runners'][fastest]['label'])} : {times} {'de ' if times[-1] == 's' else ''}"
                     f"fois plus rapide"}


GATE_NAMES = {"AND": "ET", "OR": "OU", "NOT": "NON", "XOR": "OU exclusif", "NAND": "NON-ET", "NOR": "NON-OU"}


def logic_data(state):
    """LOGIC_CIRCUIT laid out: each input, gate and output at its column (its depth: logic_depths) and
    row, the wires from what feeds to what is fed (which input pin), the gates in their order (a
    program's steps, in sequential mode). The page draws it and computes the 0s and 1s."""
    width, height = logic_size(state)
    depth = logic_depths(state)
    items = [("input", i) for i in state["inputs"]] + [("gate", g) for g in state["gates"]] + [("output", o) for o in state["outputs"]]
    columns = {}
    for _, item in items:
        columns.setdefault(depth[item["id"]], []).append(item["id"])
    nodes = {}
    for kind, item in items:
        column = columns[depth[item["id"]]]
        nodes[item["id"]] = {"kind": kind, "x": 150 + depth[item["id"]] * LOGIC_COL,
                             "y": round(50 + (height - 100) * (column.index(item["id"]) + 0.5) / len(column)),
                             "label": plain_math(item.get("label") or (GATE_NAMES.get(item.get("type")) if kind == "gate" else item["id"])),
                             **({"type": item["type"], "name": GATE_NAMES[item["type"]]} if kind == "gate" else {})}
    wires = [{"from": f, "to": g["id"], "pin": k, "pins": len(g["in"])} for g in state["gates"] for k, f in enumerate(g["in"])]
    wires += [{"from": o["from"], "to": o["id"], "pin": 0, "pins": 1} for o in state["outputs"]]
    program = None
    if state.get("program"):           # the same circuit as a program: one instruction per gate, then the outputs
        name = lambda i: nodes[i]["label"] if nodes[i]["kind"] == "input" else f"r{[g['id'] for g in state['gates']].index(i) + 1}"
        lines = [f"r{k + 1} = NON {name(g['in'][0])}" if g["type"] == "NOT"
                 else f"r{k + 1} = {name(g['in'][0])} {GATE_NAMES[g['type']]} {name(g['in'][1])}" for k, g in enumerate(state["gates"])]
        lines += [f"{nodes[o['id']]['label']} = {name(o['from'])}" for o in state["outputs"]]
        program = {"x": width - PROGRAM_W + 30, "width": PROGRAM_W, "top": PROGRAM_TOP, "line": PROGRAM_LINE, "lines": lines}
    return {"width": width, "height": height, "nodes": nodes, "wires": wires, "gates": [g["id"] for g in state["gates"]], "program": program,
            "feeds": {g["id"]: g["in"] for g in state["gates"]}, "outputs": {o["id"]: o["from"] for o in state["outputs"]},
            "values": {i["id"]: int(bool(state.get("values", {}).get(i["id"], 0))) for i in state["inputs"]}}


NUMBER = re.compile(r"^\s*([^\d\s+-]*)\s*([+-]?\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)\s*(\S*)\s*$")


def table_number(cell):
    """"2 640" -> (2640.0, 0, "", ""), "2,5 %" -> (2.5, 1, "", "%"), "€ 12" -> (12.0, 0, "€", ""); None if no number."""
    m = NUMBER.match(str(cell))
    if not m:
        return None
    digits = re.sub(r"[\s\u00a0\u202f]", "", m.group(2)).replace(",", ".")
    try:
        value = float(digits)
    except ValueError:
        return None
    return value, len(digits.split(".")[1]) if "." in digits else 0, m.group(1), m.group(3)


def french_figure(value, decimals):
    """12345.6 -> "12 345,6": a thin space between thousands, a decimal comma."""
    text = f"{value:,.{decimals}f}".replace(",", "\u202f").replace(".", ",")
    return text


def table_data(state):
    """TABLE: its cells as text, its columns' widths, and the "Total" row the program sums (a column whose
    cells are all numbers with the same unit), never the brief."""
    columns, rows = [plain_math(str(c)) for c in state["columns"]], [[plain_math(str(c)) for c in r] for r in state["rows"]]
    total = []
    for j in range(len(columns)):
        parsed = [table_number(r[j]) for r in state["rows"]]
        if j and parsed and all(parsed) and len({(p[2], p[3]) for p in parsed}) == 1:
            decimals = max(p[1] for p in parsed)
            total.append(f"{parsed[0][2]}{french_figure(sum(p[0] for p in parsed), decimals)}{(' ' + parsed[0][3]) if parsed[0][3] else ''}".strip())
        else:
            total.append("Total" if j == 0 else "")
    return {"columns": columns, "rows": rows, "widths": table_widths(state), "row": TABLE_ROW, "total": total}


PALETTE = ("#3B82F6", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#06B6D4", "#EC4899")


def figure(value, decimals=None):
    """A number in French, its decimals trimmed: 2500.0 -> "2 500", 0.125 -> "0,125"."""
    if decimals is None:
        decimals = 0 if abs(value - round(value)) < 1e-9 else min(4, max(1, 3 - int(math.floor(math.log10(abs(value)))) if value else 1))
    text = french_figure(value, decimals)
    return text.rstrip("0").rstrip(",") if "," in text else text


def shares(values):
    """Whole percentages adding up to exactly 100 (largest remainders)."""
    total = sum(values)
    raw = [100 * v / total for v in values]
    out = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)[:100 - sum(out)]:
        out[i] += 1
    return out


def simple_data(kind, state):
    """The simple catalogue pieces, worked out here (positions, shares, products, equilibria): the page
    only draws them. Texts from the brief go through plain_math and are shown as text only."""
    width, height = simple_size(kind, state)
    out = {"kind": kind, "width": width, "height": height}
    if kind == "TIMELINE":
        events = state["events"]
        years = [int(e["date"]) if str(e["date"]).strip().lstrip("-").isdigit() else None for e in events]
        x0, x1 = 90, width - 90
        if all(y is not None for y in years) and max(years) > min(years):
            xs = [x0 + (x1 - x0) * (y - min(years)) / (max(years) - min(years)) for y in years]
        else:
            xs = [x0 + (x1 - x0) * i / (len(events) - 1) for i in range(len(events))]
        out["events"] = [{"date": plain_math(str(e["date"])), "label": plain_math(e["label"]), "x": round(x, 1)} for e, x in zip(events, xs)]
    elif kind == "FRACTION_BAR":
        total, parts = state["total"], state["parts"]
        out.update(total=total, parts=[{"n": p["n"], "label": plain_math(p.get("label") or f"{p['n']}/{total}"),
                                        "color": PALETTE[i % len(PALETTE)]} for i, p in enumerate(parts)])
        n = sum(p["n"] for p in parts)
        out["sum"] = " + ".join(f"{p['n']}/{total}" for p in parts) + f" = {n}/{total} = {figure(100 * n / total)} %"
    elif kind == "PIE_CHART":
        slices = state["slices"]
        pct = shares([s["value"] for s in slices])
        unit = plain_math(str(state.get("unit") or ""))
        start, items = -90.0, []
        total = sum(s["value"] for s in slices)
        for i, (s, p) in enumerate(zip(slices, pct)):
            sweep = 360 * s["value"] / total
            items.append({"label": plain_math(s["label"]), "value": f"{figure(s['value'])} {unit}".strip(), "pct": p,
                          "start": start, "sweep": sweep, "color": PALETTE[i % len(PALETTE)]})
            start += sweep
        out["slices"] = items
    elif kind == "UNIT_CONVERTER":
        kind_name, fa = UNIT_FACTORS_RENDER[state["from"]]
        fb = UNIT_FACTORS_RENDER[state["to"]][1]
        ratio = fa / fb
        ladder = sorted((u for u, (k, f) in UNIT_FACTORS_RENDER.items() if k == kind_name and min(fa, fb) <= f <= max(fa, fb)),
                        key=lambda u: -UNIT_FACTORS_RENDER[u][1])
        if len(ladder) > 8:
            ladder = [state["from"], state["to"]] if fa > fb else [state["to"], state["from"]]
        out.update(value=figure(state["value"]), src=state["from"], dst=state["to"], result=figure(state["value"] * ratio),
                   factor=("× " + figure(ratio)) if ratio >= 1 else ("÷ " + figure(1 / ratio)), ladder=ladder, kind_name=kind_name)
    elif kind == "TREE":
        nodes, leaves = [], [0]

        def walk(branches, depth, path, prob):
            """Lay out a node's branches (leaves one under the other, a node at its leaves' middle)."""
            ys = []
            for b in branches:
                p = b.get("p")
                here, chance = path + [b["label"]], (prob * p if prob is not None and p is not None else None)
                if b.get("branches"):
                    y = walk(b["branches"], depth + 1, here, chance)
                else:
                    y = 20 + TREE_LEAF * (leaves[0] + 0.5)
                    leaves[0] += 1
                nodes.append({"label": plain_math(b["label"]), "p": None if p is None else figure(p), "x": 110 + TREE_LEVEL * (depth + 1), "y": round(y, 1),
                              "depth": depth, "path": [plain_math(x) for x in here], "parent": [plain_math(x) for x in path],
                              "product": None if chance is None else figure(chance), "leaf": not b.get("branches")})
                ys.append(y)
            return sum(ys) / len(ys)
        root_y = walk(state["branches"], 0, [], 1.0)
        out.update(nodes=nodes, root={"label": plain_math(str(state.get("root") or "")), "x": 70, "y": round(root_y, 1)})
    elif kind == "SET_DIAGRAM":
        a, b, both = state["a"], state["b"], state.get("both", 0)
        either = a["count"] + b["count"] - both
        total = state.get("total")
        counts = {"a": a["count"], "b": b["count"], "both": both, "either": either, "only_a": a["count"] - both,
                  "only_b": b["count"] - both, "neither": None if total is None else total - either}
        out.update(a=plain_math(a["label"]), b=plain_math(b["label"]), counts=counts, total=total,
                   p={k: (None if total in (None, 0) or v is None else f"{figure(v)}/{total} = {figure(round(v / total, 3))}") for k, v in counts.items()})
    elif kind == "GAME_MATRIX":
        pay = state["payoffs"]
        best_a = [[pay[i][j][0] == max(pay[k][j][0] for k in range(2)) for j in range(2)] for i in range(2)]
        best_b = [[pay[i][j][1] == max(pay[i][k][1] for k in range(2)) for j in range(2)] for i in range(2)]
        out.update(players=[plain_math(p) for p in state["players"]], strategies=[[plain_math(s) for s in r] for r in state["strategies"]],
                   payoffs=[[[figure(v) for v in c] for c in r] for r in pay], best=[best_a, best_b],
                   nash=[[best_a[i][j] and best_b[i][j] for j in range(2)] for i in range(2)])
    elif kind == "BAR_CHART":
        bars, unit = state["bars"], plain_math(str(state.get("unit") or ""))
        values = [b["value"] for b in bars] + ([state["line"]] if state.get("line") is not None else [])
        out.update(bars=[{"label": plain_math(str(b["label"])), "value": b["value"], "text": f"{figure(b['value'])} {unit}".strip()} for b in bars],
                   low=min(0, min(values)), high=max(0, max(values)), line=state.get("line"),
                   line_text=None if state.get("line") is None else f"{figure(state['line'])} {unit}".strip())
    elif kind == "EQUATION_STEPS":
        out.update(steps=list(state["steps"]), notes=[plain_math(n) for n in state.get("notes", [])], line=EQUATION_LINE)
    elif kind == "POWER_SUPPLY":
        out.update(voltage=state.get("voltage", 12), limit=state.get("current_limit", 1))
    return out


def phys_data(kind, state):
    """The physics pieces, worked out here (resultants, flight times, velocities after a collision,
    periods): the page moves things with the same exact formulas, the figures shown come from here."""
    width, height = simple_size(kind, state)
    out = {"kind": kind, "width": width, "height": height}
    if kind == "FREE_BODY":
        m, forces = float(state.get("mass", 1)), state["forces"]
        sx, sy = sum(f.get("x", 0) for f in forces), sum(f.get("y", 0) for f in forces)
        biggest = max(math.hypot(f.get("x", 0), f.get("y", 0)) for f in forces)
        r = math.hypot(sx, sy)
        out.update(body=state.get("body", "block"), incline=float(state.get("incline", 0)), scale=170 / biggest,
                   forces=[{"name": plain_math(f["name"]), "symbol": plain_math(str(f.get("symbol") or f["name"][:1])),
                            "x": f.get("x", 0), "y": f.get("y", 0), "text": f"{figure(math.hypot(f.get('x', 0), f.get('y', 0)), 1)} N"} for f in forces],
                   sum=[sx, sy], balanced=r < 0.01 * biggest,
                   sum_text=("ΣF = 0 : équilibre, pas d'accélération" if r < 0.01 * biggest
                             else f"ΣF = {figure(r, 1)} N  →  a = ΣF / m = {figure(r / m, 2)} m/s²"))
    elif kind == "KINEMATICS":
        k, (vx, vy), g, a = state.get("kind", "projectile"), state.get("v0", [10, 5]), float(state.get("g", 9.8)), float(state.get("a", 2))
        if k == "projectile":
            T = 2 * vy / g
            out["text"] = f"Durée {figure(T, 2)} s · portée {figure(vx * T, 1)} m · hauteur max {figure(vy * vy / (2 * g), 1)} m"
        elif k == "free_fall":
            T, vx, vy = 2.0, 0.0, 0.0
            out["text"] = f"En 2 s : chute de {figure(0.5 * g * 4, 1)} m, vitesse {figure(g * 2, 1)} m/s"
        elif k == "accelerated":
            T = 4.0
            out["text"] = f"En 4 s : {figure(vx * T + a * T * T / 2, 1)} m, vitesse {figure(vx + a * T, 1)} m/s"
        else:
            T = 4.0
            out["text"] = f"Vitesse constante {figure(vx, 1)} m/s : {figure(vx * T, 1)} m en 4 s"
        out.update(motion=k, vx=vx, vy=vy, g=g, a=a, T=T)
    elif kind == "COLLISION":
        m1, v1, m2, v2 = (float(state[k]) for k in ("m1", "v1", "m2", "v2"))
        if state.get("type", "elastic") == "elastic":
            u1, u2 = ((m1 - m2) * v1 + 2 * m2 * v2) / (m1 + m2), ((m2 - m1) * v2 + 2 * m1 * v1) / (m1 + m2)
        else:
            u1 = u2 = (m1 * v1 + m2 * v2) / (m1 + m2)
        e0, e1 = 0.5 * m1 * v1 ** 2 + 0.5 * m2 * v2 ** 2, 0.5 * m1 * u1 ** 2 + 0.5 * m2 * u2 ** 2
        out.update(m1=m1, m2=m2, v1=v1, v2=v2, u1=u1, u2=u2, elastic=state.get("type", "elastic") == "elastic",
                   before=f"Avant : p = {figure(m1 * v1 + m2 * v2, 2)} kg·m/s, Ec = {figure(e0, 2)} J",
                   after=f"Après : p = {figure(m1 * u1 + m2 * u2, 2)} kg·m/s, Ec = {figure(e1, 2)} J",
                   verdict="Quantité de mouvement conservée" + (", énergie cinétique conservée" if abs(e1 - e0) < 1e-6 * max(e0, 1)
                                                                else f", {figure(e0 - e1, 2)} J perdus (déformation, chaleur)"),
                   speeds=[f"{figure(v, 2)} m/s" for v in (v1, v2, u1, u2)], masses=[f"{figure(m1)} kg", f"{figure(m2)} kg"])
    elif kind == "OSCILLATOR":
        if state.get("kind", "spring") == "pendulum":
            L, g, th = float(state.get("L", 1)), float(state.get("g", 9.8)), float(state.get("theta0", 20))
            w = math.sqrt(g / L)
            out.update(osc="pendulum", omega=w, gamma=0.0, amp=th, T=2 * math.pi / w,
                       period=f"T = 2π √(L / g) = {figure(2 * math.pi / w, 2)} s")
        else:
            k, m, d, x0 = float(state.get("k", 100)), float(state.get("m", 1)), float(state.get("damping", 0)), float(state.get("x0", 0.1))
            w = math.sqrt(k / m)
            out.update(osc="spring", omega=w, gamma=d * w, amp=x0, T=2 * math.pi / w,
                       period=f"T = 2π √(m / k) = {figure(2 * math.pi / w, 2)} s")
    elif kind == "ORBIT":
        e = float(state.get("e", 0.5))
        central = plain_math(str(state.get("central") or "Terre"))
        # the nearest and farthest points, named for the body at the focus
        near, far = (("périgée", "apogée") if "terre" in central.lower() else ("périhélie", "aphélie")
                     if "soleil" in central.lower() else ("point le plus proche", "point le plus loin"))
        # equal areas in equal times: r_P v_P = r_A v_A, so v_P / v_A = r_A / r_P = (1 + e) / (1 - e)
        ratio = (1 + e) / (1 - e)
        out.update(e=e, central=central, body=plain_math(str(state.get("body") or "Satellite")),
                   near=f"P : {near}", far=f"A : {far}",
                   ratio=[f"r_A / r_P = (1 + e) / (1 − e) = {figure(ratio, 2)}",
                          f"Aires égales : r_P × v_P = r_A × v_A, donc v_P = {figure(ratio, 2)} × v_A"])
    return out


def chain_data(state):
    """CHAIN: its boxes' centres (left to right, a second row under the first past four, its arrows
    between them), and the loop back from the last to the first."""
    steps = [plain_math(str(s)) for s in state["steps"]]
    n = len(steps)
    per_row = n if n <= 4 else CHAIN_ROW
    width, height = chain_size(state)
    w, h = CHAIN_BOX
    left = 70 if state.get("loop") else 0          # room on the left for the way back
    centres = [[left + w / 2 + (i % per_row) * (w + CHAIN_GAP), h / 2 + (i // per_row) * (h + 70)] for i in range(n)]
    return {"steps": steps, "centres": centres, "box": [w, h], "loop": bool(state.get("loop")), "width": width, "height": height}


def fpga_data(state):
    """FPGA_GRID: its size and the two designs (labels shown as text by the page)."""
    return {"cols": int(state["cols"]), "rows": int(state["rows"]), "cell": FPGA_CELL,
            "design": [plain_math(d) for d in state["design"]], "design2": [plain_math(d) for d in state.get("design2") or []]}


POPULATION_COLORS = ("#DC2626", "#F59E0B", "#2563EB", "#10B981")   # a group's colour when the brief gives none


def population_data(state):
    """POPULATION: its dots, each group's (in order, then the rest), and the counts of people the
    legend gives: "Malades : 100 personnes" (count x per)."""
    total, per, unit = int(state["total"]), int(state.get("per", 1)), str(state.get("unit") or "personnes")[:16]
    people = lambda dots: f"{french_big(dots * per)} {unit}"
    groups = [{"id": g["id"], "label": plain_math(g["label"]), "count": int(g["count"]), "people": people(int(g["count"])),
               "color": g.get("color") or POPULATION_COLORS[i % len(POPULATION_COLORS)]} for i, g in enumerate(state["groups"])]
    rest = total - sum(g["count"] for g in groups)
    return {"total": total, "groups": groups,
            "rest": {"id": "rest", "label": plain_math(state.get("rest") or ""), "people": people(rest)} if rest > 0 else None,
            "head": people(total) + (f" · 1 point = {people(1)}" if per > 1 else "")}


def plain_math(text):
    if not isinstance(text, str):
        return text
    def script(m):
        written = m.group(2) if m.group(2) is not None else m.group(3)
        table = SUPER if m.group(1) == "^" else SUB
        shown = written.replace(" ", "").translate(table)
        return shown if all(ord(c) > 127 for c in shown) else m.group(0)
    if "_" in text and " " not in text.strip() and not re.search(r"[\^{}]", text) and len(text) > 4:
        return text                       # an identifier ("body_0999"), not maths
    return PLAIN_MATH.sub(script, text)


def entity_data(entity, entities_by_id, ink="#0F172A"):
    state = entity.get("initial_state") or {}
    data = {"id": entity["id"], "type": entity["type"], "label": plain_math(state.get("label")), "latex": state.get("latex"),
            "tone": state.get("tone") if state.get("tone") in TONES else None,
            "initial": state, "xy": to_pixels(entity["position"]),
            "instrument": entity["type"] in {t.value for t in INSTRUMENT_TYPES}}
    if entity["type"] in {t.value for t in SVG_TYPES}:
        data["icon"] = icon_data_uri(entity["type"], ink)
    if entity["type"] in ICON_STANDINS:
        data["icon"] = icon_data_uri(ICON_STANDINS[entity["type"]], ink)
    if entity["type"] == "OBJECT":                # any concrete thing: its icon from OBJECT_ICONS, like the icon types
        data["icon"] = icon_data_uri(state.get("icon", DEFAULT_OBJECT_ICON), ink)
        if state.get("icon") in SPHERES:          # a planet, a moon, the Sun: drawn as a lit sphere, not an icon card
            data["sphere"] = SPHERES[state["icon"]]
    if entity["type"] == "SEESAW":                # a beam on a pivot, a load at each end
        data["seesaw"] = {side: {"label": plain_math((state.get(side) or {}).get("label")),
                                 "weight": float(state[side]["weight"]),
                                 **({"value": float(state[side]["value"])} if is_number(state[side].get("value")) else {})}
                          for side in ("left", "right")}
        data["seesaw"]["unit"] = str(state.get("unit") or "")[:8]
    if entity["type"] == "VECTOR_ARROW" and is_number(state.get("value")) and state["value"] != 0:
        data["vector_value"] = {"value": float(state["value"]), "unit": str(state.get("unit") or "")}
    if entity["type"] == "LANES":                 # queues side by side: their labels and rates, one icon for all
        data["lanes"] = [{"label": plain_math(lane.get("label")), "rate": float(lane.get("rate"))}
                         for lane in state.get("lanes", [])]
        data["icon"] = icon_data_uri(state.get("icon", "car"), ink)
    if entity["type"] == "SPEED_RACE":            # speeds on one track, to one scale
        data["race"] = race_data(state, ink)
    if entity["type"] == "POPULATION":            # a grid of dots, its groups coloured
        data["population"] = population_data(state)
    if entity["type"] == "TIDES":                 # the Earth in its ocean, the Moon: drawn and labelled by the page
        data["tides"] = True
    if entity["type"] == "BREADBOARD":            # laid out by app/breadboard.py: parts, jumpers, rails in pixels
        data["breadboard"] = breadboard_data(state)
    if entity["type"] == "SUPPLY_RAIL":           # its voltage written over its bar, no caption under it
        data["rail"], data["label"] = plain_math(state.get("label") or "+12 V"), None
    if entity["type"] == "MICROCONTROLLER":       # its program and its one unit
        data["mcu"] = {"label": plain_math(state.get("label") or "Microcontrôleur"),
                       "instructions": [plain_math(i) for i in state.get("instructions")
                                        or ["lire Bouton 1", "lire Bouton 2", "calculer ET", "allumer Lampe"]]}
    if entity["type"] == "TABLE":                 # a table: its rows, its total summed here
        data["table"] = table_data(state)
    if entity["type"] == "CHAIN":                 # steps or causes, one after the other
        data["chain"] = chain_data(state)
    if entity["type"] in PHYS_PIECES:             # the physics pieces, worked out here
        data["phys"] = phys_data(entity["type"], state)
    if entity["type"] in SIMPLE_PIECES:           # the simple catalogue pieces, worked out here
        data["simple"] = simple_data(entity["type"], state)
    if entity["type"] == "WAVE":                  # a rope, the sea, a crowd, a spring: drawn and moved by the page
        data["wave"] = {"mode": state.get("mode", "rope"), "kind": state.get("kind", "pulse"), "loops": int(state.get("loops", 3))}
    if entity["type"] == "TUNNEL":                # a dot in a tube, the wall a line across it
        data["tunnel"] = {"particle": str(state.get("particle") or "Particule"), "barrier": str(state.get("barrier") or "Mur"),
                          "zoom": state.get("zoom") is not False}
    if entity["type"] == "LOGIC_CIRCUIT":         # inputs, gates and outputs, laid out here, computed by the page
        data["logic"] = logic_data(state)
    if entity["type"] == "FPGA_GRID":             # logic blocks and routing
        data["fpga"] = fpga_data(state)
    if entity["type"] == "ARROW_ANNOTATION":     # a pill badge; the position is where its short arrow points
        direction = vector_direction(state.get("direction", "DOWN"), "DOWN")
        data["annotation"] = {"direction": direction, "angle": direction_degrees(direction),
                              "status": is_status_annotation(entity)}   # a status badge: in the column, no arrow
        data["label"] = plain_math(state.get("text"))
    if entity["type"] == "AXES_GRAPH":
        data["graph"] = {"x_range": number_range(state.get("x_range"), DEFAULT_X_RANGE),
                         "y_range": number_range(state.get("y_range"), DEFAULT_Y_RANGE),
                         "x_label": plain_math(state.get("x_label")), "y_label": plain_math(state.get("y_label")),
                         "line": is_number_line(entity, entities_by_id),
                         # an axis named with no measure ("orbite", "hauteur"): a sketch, no numbers along it
                         "numbered": [measured_axis(state.get("x_label")), measured_axis(state.get("y_label"))]}
    if entity["type"] == "CURVE_PLOT":
        axes = entities_by_id.get(state.get("axes"))
        axes_state = (axes.get("initial_state") or {}) if axes and axes["type"] == "AXES_GRAPH" else {}
        x_range = number_range(axes_state.get("x_range"), DEFAULT_X_RANGE)
        y_range = number_range(axes_state.get("y_range"), DEFAULT_Y_RANGE)
        hosted = state.get("axes") if axes_state or (axes and axes["type"] == "AXES_GRAPH") else None
        data["curve"] = {"axes": hosted, "x_range": x_range, "y_range": y_range, "color": state.get("color")}
        if is_parametric(state):   # x(t), y(t): drawn closed if it ends where it starts; equal scales on x and y
            points, closed = sample_parametric(state, x_range if hosted else None, y_range if hosted else None)
            data["curve"].update(points=points, parametric=True, closed=closed)
            if not hosted:
                data["curve"]["x_range"], data["curve"]["y_range"] = parametric_box(points)
        else:
            data["curve"]["points"] = sample_function(state.get("func"), number_range(state.get("x_range"), x_range), y_range)
    if entity["type"] == "VECTOR_ARROW":
        direction = vector_direction(state.get("direction", "RIGHT"), "RIGHT")
        data["vector"] = {"direction": direction, "angle": direction_degrees(direction),
                          "length": float(state.get("length", 1.8)) * SCENE_PX_PER_UNIT, "color": state.get("color")}
        place = curve_anchor(state.get("anchor"), entities_by_id)
        if place:                                     # on a point of a curve, or riding on a body there
            curve, anchor, body = place
            x_range = curve_x_range(curve, entities_by_id)
            point, toward = anchor_geometry(curve["initial_state"], anchor, state.get("direction"), x_range)
            data["vector"]["anchor"] = {"curve": curve["id"], "point": point, "toward": toward, "body": body,
                                        "host": rides_in(body, entities_by_id) if body else None}   # on a passenger: from it
            if str(state.get("direction")).upper() == "CENTER":   # stops short of what sits there (the planet)
                data["vector"]["anchor"]["centre"] = curve_centre(curve["initial_state"], x_range)
        elif point_anchor(state.get("anchor")):       # on a point of a graph
            data["vector"]["anchor"] = {**point_anchor(state["anchor"]), "toward": None, "body": None}
        elif isinstance(state.get("anchor"), dict) and "body" in state["anchor"]:   # from an OBJECT (or a body off curves)
            data["vector"]["anchor"] = {"body": state["anchor"]["body"], "point": None, "toward": None}
    anchor = state.get("anchor") if isinstance(state.get("anchor"), dict) else {}
    rides = anchor.get("body") if entity["type"] in ("BODY", "OBJECT") or entity["type"] in {t.value for t in SVG_TYPES} else None
    if rides:                                         # in another body or object: drawn beside it, goes with it
        data["rides"] = rides
    if entity["type"] == "BODY":                      # a disc; on a curve, it can move along it (move_along)
        data["body"] = {"radius": float(state.get("size", BODY_SIZE)) * SCENE_PX_PER_UNIT, "color": state.get("color") or BODY_COLOR}
        place = None if rides else curve_anchor(state.get("anchor"), entities_by_id)
        if place:
            curve, anchor, _ = place
            point, _ = anchor_geometry(curve["initial_state"], anchor, None, curve_x_range(curve, entities_by_id))
            data["body"]["anchor"] = {"curve": curve["id"], "point": point}
        elif point_anchor(state.get("anchor")):
            data["body"]["anchor"] = point_anchor(state["anchor"])
            axes = entities_by_id.get(state["anchor"]["axes"])
            if axes and axes["type"] == "AXES_GRAPH" and is_number_line(axes, entities_by_id):
                data["body"]["radius"] = min(data["body"]["radius"], NUMBER_LINE_DOT * SCENE_PX_PER_UNIT)
    if entity["type"] == "OBJECT" and point_anchor(state.get("anchor")):   # e.g. the Earth at an orbit's centre
        data["placed"] = point_anchor(state["anchor"])
    data["compact"] = bool(data.get("icon")) and bool(data.get("placed") or rides)   # a small icon, to scale with a graph, or riding
    return data


NUMBER_LINE_DOT = 0.1      # radius (scene units) of a point on a number line: a dot, not a planet


def is_number_line(axes, entities_by_id):
    """An AXES_GRAPH with no curve on it, no y label, and whatever is anchored on it at y = 0 (0,999...
    and 1 as points): a number line, drawn as one graduated line, its points as dots."""
    if (axes.get("initial_state") or {}).get("y_label"):
        return False
    for other in entities_by_id.values():
        state = other.get("initial_state") or {}
        if other["type"] == "CURVE_PLOT" and state.get("axes") == axes["id"]:
            return False
        anchor = point_anchor(state.get("anchor"))
        if anchor and anchor["axes"] == axes["id"] and abs(anchor["point"][1]) > 1e-9:
            return False
    return True


def point_anchor(anchor):
    """{"axes": id, "point": [x, y]} for an anchor on a point of a graph ({"axes", "x", "y"}), else None."""
    if isinstance(anchor, dict) and set(anchor) == {"axes", "x", "y"}:
        return {"axes": anchor["axes"], "point": [float(anchor["x"]), float(anchor["y"])]}
    return None


BODY_SIZE, BODY_COLOR = 0.25, "#F59E0B"      # a body's radius (scene units) and colour, by default
# Vectors riding on one body turn together: each its own colour, its label in that colour, so a label
# names its arrow even when it ends up nearer the other one.
RIDER_COLORS = ("#EF4444", "#2563EB", "#059669", "#D97706")
MOTION_FPS = 30                              # samples per second of a move_along track


def rides_in(entity_id, entities_by_id):
    """The id of the body or object this one rides in ("anchor": {"body": id}), or None."""
    anchor = ((entities_by_id.get(entity_id) or {}).get("initial_state") or {}).get("anchor")
    return anchor.get("body") if isinstance(anchor, dict) else None


def curve_anchor(anchor, entities_by_id):
    """(curve entity, {"curve", "t" or "x"}, body id or None) for an "anchor" on a curve, or riding on a
    body anchored on one (or on a passenger of such a body: its host's curve); None otherwise (the
    schema checked the ids and kinds)."""
    body = None
    if isinstance(anchor, dict) and "body" in anchor:
        body = anchor["body"]
        host = rides_in(body, entities_by_id)
        anchor = ((entities_by_id.get(host or body) or {}).get("initial_state") or {}).get("anchor")
    curve = entities_by_id.get(anchor.get("curve")) if isinstance(anchor, dict) else None
    return (curve, anchor, body) if curve and curve["type"] == "CURVE_PLOT" else None


def curve_x_range(curve, entities_by_id):
    axes = entities_by_id.get((curve.get("initial_state") or {}).get("axes")) or {}
    return number_range((axes.get("initial_state") or {}).get("x_range"), DEFAULT_X_RANGE)


MIN_MOVE_SEC = 1.5          # a move squeezed to fit its scene still lasts at least this long


def fit_move(event, duration, scene_end):
    """The move's duration, made shorter to end with the scene (`scene_end`, seconds) if needed, and
    started earlier if it would last less than MIN_MOVE_SEC ("planned_duration" keeps the brief's)."""
    if scene_end is not None and event["at"] + duration > scene_end:
        event["planned_duration"] = duration
        event["at"] = max(0.0, min(event["at"], scene_end - MIN_MOVE_SEC))
        duration = max(scene_end - event["at"], 0.1)
    event["duration"] = duration
    return duration


def motion_tracks(brief, events, scene_end=None):
    """Each move_along event gets its "track": the body's points along its curve, from where it is (its
    anchor, or where its previous move left it) to "to", MOTION_FPS a second (graph units), and for each
    vector riding on it with a TANGENT / CENTER / OUTWARD direction, the matching "toward" points.
    Each move event gets its "shift": how far it goes, in pixels (from its position to "to"; the page
    adds it to where the layout put it), and its "easing". The page interpolates them at seek(t):
    nothing is evaluated in the browser. A move that would end after `scene_end` is made to fit (fit_move)."""
    by_id = {e["id"]: e for e in brief["entities"]}
    where = {}                                   # body id -> its current t (or x)
    for event in events:
        body = by_id.get(event.get("target"))
        if event.get("action") == "move" and body and isinstance(event.get("to"), (list, tuple)) and len(event["to"]) >= 2:
            (x0, y0), (x1, y1) = to_pixels(body["position"]), to_pixels(list(event["to"]))
            fit_move(event, float(event.get("duration", 2)), scene_end)
            event["shift"], event["easing"] = [x1 - x0, y1 - y0], event.get("easing", "smooth")
            continue
        place = curve_anchor((body or {}).get("initial_state", {}).get("anchor"), by_id) if event.get("action") == "move_along" else None
        if not place or not isinstance(event.get("to"), (int, float)):
            continue
        curve, anchor, _ = place
        key = "t" if "t" in anchor else "x"
        start, end = where.get(body["id"], anchor[key]), float(event["to"])
        duration = fit_move(event, float(event.get("duration", 4)), scene_end)
        steps = max(2, min(int(duration * MOTION_FPS), 600))
        values = np.linspace(start, end, steps)
        xs, ys = curve_at(curve["initial_state"], values)
        riders = {}
        for vector in brief["entities"]:
            state = vector.get("initial_state") or {}
            on = (state.get("anchor") or {}).get("body") if isinstance(state.get("anchor"), dict) else None
            if vector["type"] == "VECTOR_ARROW" and on and body["id"] in (on, rides_in(on, by_id)):
                towards = [anchor_geometry(curve["initial_state"], {"curve": curve["id"], key: float(v)}, state.get("direction"),
                                           curve_x_range(curve, by_id))[1] for v in values]
                riders[vector["id"]] = towards if towards[0] is not None else None
        event["track"] = {"points": [[round(float(x), 5), round(float(y), 5)] for x, y in zip(xs, ys)], "riders": riders}
        where[body["id"]] = end
    return events


SYMBOL_MAX = 3      # a vector label this short ("v", "F", "P_1") is its own symbol: no legend line


def vector_symbols(entities):
    """Each labelled vector gets the "symbol" drawn by its arrow, and, when its label is longer than
    SYMBOL_MAX, the "legend" line that says what it is ("P : Poids"): a long label beside every arrow
    takes the room the drawing needs. The symbol is the brief's "symbol", else the label's own first
    letter ("Gravité" -> "G"; a one-letter first word as it is: "g (Station)" -> "g"), with its second
    letter when another label of the scene already has it ("Gr"), then a number. One label, one symbol."""
    taken, by_label = {}, {}
    for data in entities:
        vector, label = data.get("vector"), (data.get("label") or "").strip()
        if not vector or not label:
            continue
        given = (data.get("initial") or {}).get("symbol")
        if not given and len(label) <= SYMBOL_MAX:
            vector["symbol"] = label
            continue
        symbol = given or by_label.get(label)
        if not symbol:
            words = re.findall(r"\w+", label)
            first = words[0] if words else label
            options = [first] if len(first) == 1 else [first[0].upper(), first[0].upper() + first[1:2].lower()]
            symbol = next((o for o in options if taken.get(o, label) == label), None)
            symbol = symbol or next(f"{options[0]}{n}" for n in range(2, 99) if taken.get(f"{options[0]}{n}", label) == label)
        taken.setdefault(symbol, label)
        by_label.setdefault(label, symbol)
        vector["symbol"], vector["legend"] = symbol, label


# A light, a ray or a curve named by its colour ("Bleu diffusé", "Lumière rouge") is drawn in that
# colour, whatever the brief says: a blue ray drawn red teaches the opposite. The first colour word
# of the label wins ("Rouge-orange direct": red). Vectors that share a legend line take one colour.
NAMED_COLOURS = [(re.compile(r"\bbleu(?:e|s|es)?\b"), "#3B82F6"), (re.compile(r"\brouges?\b"), "#EF4444"),
                 (re.compile(r"\bvert(?:e|s|es)?\b"), "#10B981"), (re.compile(r"\boranges?\b"), "#F97316"),
                 (re.compile(r"\bjaunes?\b"), "#EAB308"), (re.compile(r"\bviolet(?:te|s|tes)?\b"), "#8B5CF6")]


def named_colour(label):
    """The colour a label names, by its first colour word, else None."""
    text = str(label or "").lower()
    found = [(match.start(), colour) for pattern, colour in NAMED_COLOURS for match in [pattern.search(text)] if match]
    return min(found)[1] if found else None


VECTOR_MAX_UNITS = 2.6      # the largest value of a unit gets this length (scene units); the others to scale


def vectors_to_scale(entities, actions):
    """Vectors given a "value" (588 N): drawn to scale, the largest value of each unit (all its vectors,
    all their set_value steps) VECTOR_MAX_UNITS long. Each keeps its largest value (value_max, the
    length it is laid out with) and its first (value): the page draws value / value_max of it."""
    steps = {}
    for action in actions:
        if action.get("action") == "set_value" and is_number(action.get("value")):
            steps.setdefault(action.get("target"), []).append(abs(float(action["value"])))
    scaled = [d for d in entities if d.get("vector") and d.get("vector_value")]
    largest = {}
    for d in scaled:
        top = max([abs(d["vector_value"]["value"])] + steps.get(d["id"], []))
        d["vector"]["value_max"] = top
        largest[d["vector_value"]["unit"]] = max(largest.get(d["vector_value"]["unit"], 0), top)
    for d in scaled:
        d["vector"]["value"] = d["vector_value"]["value"]
        d["vector"]["length"] = VECTOR_MAX_UNITS * SCENE_PX_PER_UNIT * d["vector"]["value_max"] / largest[d["vector_value"]["unit"]]


def colour_by_name(entities):
    """Vectors and curves named by a colour take it; then each legend line ("B : Bleu diffusé") one
    colour for all its arrows (the first one's)."""
    for data in entities:
        drawn = data.get("vector") or data.get("curve")
        colour = named_colour(data.get("label")) if drawn is not None else None
        if colour:
            drawn["color"] = colour
    shared = {}
    for data in entities:
        vector = data.get("vector")
        if vector and vector.get("legend"):
            key = (vector.get("symbol"), vector["legend"])
            shared.setdefault(key, vector.get("color"))
            vector["color"] = shared[key] or vector.get("color")


CONTENT_BAND = (240, HEIGHT - 140)     # px: under the titles, above the legend
CONTENT_SIDES = (140, WIDTH - 140)     # px: left and right, the badges and labels need room past the centres
SIDE_COLUMN_LEFT = round(WIDTH * 0.75) - 100   # with a side column (instruments, counters), the drawing ends here
PANEL_ROOM = ((140, WIDTH // 2 - 120), (WIDTH // 2 + 120, WIDTH - 140))   # px: a comparison's panels (the page's PANELS), less room for the labels
CENTRE_MIN_SHIFT = 40


def centred(values, low, high):
    """The shift that centres `values` in [low, high] without pushing any of them out of it; 0 when small."""
    if max(values) - min(values) > high - low:      # wider than the room: left as placed
        return 0
    shift = (low + high) / 2 - (min(values) + max(values)) / 2
    shift = max(min(shift, high - max(values)), low - min(values))
    return shift if abs(shift) >= CENTRE_MIN_SHIFT else 0


def centre_content(entities, brief, horizontal=True):
    """The LLM tends to put everything in a corner (y > 0, or x far left), leaving the frame empty:
    move the whole drawing so its free things (not in a graph, not riding, not in the side column)
    are centred, vertically in CONTENT_BAND and horizontally between the sides (or the side column);
    on a comparison (horizontal False), each panel's things in their panel (PANEL_ROOM), so a circuit
    put at x = 0 does not stick to its panel's edge. A scene with a graph is left alone: the graph is
    laid out to fit by the page."""
    free = [d for d in entities if not d.get("instrument") and not (d.get("annotation") or {}).get("status")
            and not d.get("placed") and not d.get("rides") and not (d.get("vector") or {}).get("anchor")
            and not (d.get("body") or {}).get("anchor") and not (d.get("curve") or {}).get("axes")]
    if not free or any(d.get("graph") or d.get("curve") for d in free):
        return
    dy = centred([d["xy"][1] for d in free], *CONTENT_BAND)
    dx = 0
    if horizontal:
        column = any(d.get("instrument") or (d.get("annotation") or {}).get("status") for d in entities) \
            or any(a.get("action") == "set_value" for a in brief.get("actions", []))
        dx = centred([d["xy"][0] for d in free], CONTENT_SIDES[0], SIDE_COLUMN_LEFT if column else CONTENT_SIDES[1])
    if dx or dy:
        for d in entities:
            d["xy"] = [round(d["xy"][0] + dx), round(d["xy"][1] + dy)]
    if not horizontal:              # a comparison: each panel on its own (the page puts a thing in a panel by its x)
        for low, high in PANEL_ROOM:
            inside = lambda d: (d["xy"][0] < WIDTH / 2) == (low < WIDTH / 2)
            xs = [d["xy"][0] for d in free if inside(d)]
            shift = centred(xs, low, high) if xs else 0
            if shift:
                for d in entities:
                    if inside(d):
                        d["xy"] = [round(d["xy"][0] + shift), d["xy"][1]]


def page_data(brief, voice_duration, planned_duration, spoken=None, layout="circuit", panel_titles=None,
              style=None, scene_number=1):
    with_program(brief)
    split_rails(brief)
    place_schematic(brief)
    by_id = {e["id"]: e for e in brief["entities"]}
    overlay = brief.get("text_overlay") or {}
    style = style or dict(DEFAULT_STYLE)
    entities = [entity_data(e, by_id, style["tokens"].get("icon", "#0F172A")) for e in brief["entities"]]
    riders = {}                              # the vectors riding on one body: one colour each, their label too
    for data in entities:
        anchor = (data.get("vector") or {}).get("anchor") or {}
        if anchor.get("body"):               # a passenger's vectors share its host's colours: they move together
            riders.setdefault(anchor.get("host") or rides_in(anchor["body"], by_id) or anchor["body"], []).append(data["vector"])
    for vectors in riders.values():
        for i, vector in enumerate(v for v in vectors if not v.get("color")):
            vector["color"], vector["label_color"] = RIDER_COLORS[i % len(RIDER_COLORS)], True
    vector_symbols(entities)
    colour_by_name(entities)
    vectors_to_scale(entities, brief.get("actions", []))
    if layout in ("circuit", "comparison") and not any(a.get("action") == "move" for a in brief.get("actions", [])):
        centre_content(entities, brief, layout == "circuit")   # (a straight move keeps its scene positions: its end is one)
    targets = annotation_targets(brief)       # what each badge points at (as the layout solver sees it)
    for data in entities:
        if data.get("annotation"):
            data["annotation"]["target"] = targets.get(data["id"])
    return {"width": WIDTH, "height": HEIGHT, "duration": voice_duration, "theme": style.get("mode", THEME),
            "title": plain_math(overlay.get("title")), "subtitle": plain_math(overlay.get("subtitle")),
            "entities": entities,
            "connections": [[c["source_id"], c.get("source_port"), c["target_id"], c.get("target_port"),
                             bool(c.get("dashed"))] for c in brief.get("connections", [])],
            "events": motion_tracks(brief, timeline(brief, voice_duration, planned_duration, spoken), voice_duration + TAIL_PAUSE),
            "layout": layout, "panels": [str(t) for t in panel_titles or []][:2],
            "style": {k: style.get(k) for k in ("name", "mode", "background", "title", "subtitle", "tokens", "effects")},
            "fonts": list(style.get("fonts", [])), "scene_number": int(scene_number)}


# KaTeX for TEX_FORMULA: the npm package, pinned and checked against its published hash, cached in
# assets/katex/ on first use, then inlined into each page (CSS with its fonts as data: URIs + JS), so
# the page itself never touches the network. Without it (offline first run), formulas are plain text.
KATEX_VERSION = "0.16.11"
KATEX_URL = f"https://registry.npmjs.org/katex/-/katex-{KATEX_VERSION}.tgz"
KATEX_SHA512 = "RQrI8rlHY92OLf3rho/Ts8i/XvjgguEjOkO1BEXcU3N8BqPpSzBNwV/G0Ukr+P/l3ivvJUE/Fa/CwbS6HesGNQ=="
KATEX_DIR = os.path.join(BASE_DIR, "assets", "katex")
KATEX_MAX_BYTES = 5_000_000
KATEX_FONT = re.compile(r"^package/dist/fonts/(KaTeX_[A-Za-z0-9_-]+\.woff2)$")


def download_katex():
    """Fetch the KaTeX tarball, check its sha512, keep only the JS, the CSS and the woff2 fonts.
    True on success; never raises (no network, wrong hash...)."""
    try:
        with urllib.request.urlopen(KATEX_URL, timeout=30) as response:
            data = response.read(KATEX_MAX_BYTES + 1)
    except OSError:
        return False
    if len(data) > KATEX_MAX_BYTES or base64.b64encode(hashlib.sha512(data).digest()).decode() != KATEX_SHA512:
        print(f"--- {AGENT}: KaTeX download refused (size or hash mismatch)", file=sys.stderr)
        return False
    os.makedirs(os.path.join(KATEX_DIR, "fonts"), exist_ok=True)
    wanted = {"package/dist/katex.min.css": "katex.min.css", "package/dist/katex.min.js": "katex.min.js"}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = [m for m in archive.getmembers() if m.isfile() and (m.name in wanted or KATEX_FONT.match(m.name))]
        # Fonts first, the JS last: katex.min.js on disk means the cache is complete.
        for member in sorted(members, key=lambda m: m.name.endswith(".js")):
            font = KATEX_FONT.match(member.name)
            target = os.path.join(KATEX_DIR, "fonts", font.group(1)) if font else os.path.join(KATEX_DIR, wanted[member.name])
            with open(target + ".tmp", "wb") as f:
                f.write(archive.extractfile(member).read())
            os.replace(target + ".tmp", target)
    return True


@functools.lru_cache(maxsize=1)
def katex_assets():
    """(CSS with the fonts inlined, JS) for the pages, or None if KaTeX is not available."""
    js_path, css_path = os.path.join(KATEX_DIR, "katex.min.js"), os.path.join(KATEX_DIR, "katex.min.css")
    if not os.path.exists(js_path) and os.environ.get("BREEZE_OFFLINE") != "1":
        download_katex()
    if not (os.path.exists(js_path) and os.path.exists(css_path)):
        return None
    with open(js_path, encoding="utf-8") as f:
        js = f.read()
    with open(css_path, encoding="utf-8") as f:
        css = f.read()

    def inline_font(match):            # woff2 as a data: URI; the woff/ttf alternatives are dropped
        path = os.path.join(KATEX_DIR, "fonts", match.group(1) + ".woff2")
        if not os.path.exists(path):
            return match.group(0)
        with open(path, "rb") as font:
            return f'src:url(data:font/woff2;base64,{base64.b64encode(font.read()).decode()}) format("woff2")'
    css = re.sub(r'src:url\(fonts/([\w-]+)\.woff2\) format\("woff2"\)[^;}]*', inline_font, css)
    if "</script" in js.lower() or "</style" in css.lower():     # could not be inlined safely
        return None
    return css, js


# The page. @@NAME@@ markers are filled in one pass by build_page (the scene's JSON with "</" escaped,
# so it cannot close its tag). Every animation is driven by seek(t): CSS keyframes are paused and
# scrubbed with a negative animation-delay, "transitions" are computed in seek, electrons sit at an
# offset-distance on a CSS offset-path. Nothing runs on the wall clock, so every frame is exact.
PAGE_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">@@KATEX@@<style>
  /* Design tokens: light by default, dark with <html data-theme="dark">. 1rem = 24 px at 1080p. */
  :root { --bg:#F8FAFC; --card:#FFFFFF; --border:#E2E8F0; --ink:#334155; --text:#0F172A; --muted:#64748B;
          --wire:#94A3B8; --pos:#10B981; --neg:#EF4444; --primary:#3B82F6; --glow:#FBBF24; --bulb-off:#F1F5F9;
          --electron:#60A5FA; --radius:12px; --shadow:0 10px 15px -3px rgba(0, 0, 0, 0.05); --spring:ease-out;
          font-size:24px; }
  [data-theme="dark"] { --bg:#0F172A; --card:#1E293B; --border:#334155; --ink:#CBD5E1; --text:#F1F5F9;
          --muted:#94A3B8; --wire:#64748B; --bulb-off:#334155; --shadow:0 10px 15px -3px rgba(0, 0, 0, 0.4); }
  html, body { margin:0; width:@@WIDTH@@px; height:@@HEIGHT@@px; overflow:hidden; background:var(--bg);
               font-family:"Inter", "DejaVu Sans", "Liberation Sans", sans-serif; color:var(--text); }
  #stage { position:relative; width:100%; height:100%; }
  /* the camera (zoom_in / zoom_out): every drawn thing, not the titles, subtitles or background */
  #world { position:absolute; inset:0; transform-origin:0 0; }
  .zoom-frame { position:absolute; border:5px dashed var(--accent); border-radius:18px; pointer-events:none; opacity:0; }
  /* The theme's background (built by buildBackground from D.style.background, moved by seek(t)): its
     colour, a grid or stars, soft glows, a vignette. The tokens come from D.style.tokens. */
  :root { --accent:#3B82F6; --grid:#0F172A; --glow1:#F97316; --glow2:#8B5CF6; --ring:#FFFFFF; }
  #bg { position:absolute; inset:0; overflow:hidden; background:var(--bg); }
  #bg .grid { position:absolute; inset:-80px; }
  #bg .glow { position:absolute; width:1300px; height:1300px; margin:-650px 0 0 -650px; }
  #bg .vignette { position:absolute; inset:0; background:radial-gradient(circle at 50% 50%, transparent 35%, var(--bg) 100%); }
  #bg svg { position:absolute; left:0; top:0; overflow:visible; }
  #title { position:absolute; top:46px; width:100%; text-align:center; font-size:64px; font-weight:800; letter-spacing:-1px;
           color:var(--text); }
  #title.glow { text-shadow:0 0 28px color-mix(in srgb, var(--accent) 45%, transparent); }
  #title.display { font-family:"Space Grotesk", "Inter", "DejaVu Sans", sans-serif; font-weight:700; }
  #title .word { display:inline-block; white-space:pre; }
  #subtitle { position:absolute; top:136px; width:100%; text-align:center; font-size:40px; color:var(--muted); }
  #subtitle.code { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:32px; letter-spacing:2px; color:var(--accent);
                   text-transform:uppercase; }
  #subtitle.caps { font-size:32px; font-weight:600; letter-spacing:3px; color:var(--accent); text-transform:uppercase; }
  #wires { position:absolute; left:0; top:0; width:100%; height:100%; overflow:visible; }
  @keyframes popIn { from { opacity:0; transform:scale(0.9); } to { opacity:1; transform:scale(1); } }
  .entity { position:absolute; transform:translate(-50%, -50%); }
  .pop { position:relative; display:flex; flex-direction:column; align-items:center; transform-origin:center;
         animation:popIn 0.8s var(--spring) both paused; }
  .card { min-width:150px; max-width:420px; padding:22px 28px; background:var(--card);
          border:2px solid var(--border); box-shadow:0 12px 24px -8px color-mix(in srgb, var(--accent) 25%, rgba(0, 0, 0, .35));
          border-radius:var(--radius); font-size:34px; text-align:center; color:var(--text); }
  .label { margin-top:12px; padding:2px 10px; border-radius:8px; font-size:30px; color:var(--ink); max-width:360px;
           text-align:center; background:color-mix(in srgb, var(--bg) 88%, transparent); }   /* wires pass behind */
  .halo { paint-order:stroke; stroke:var(--bg); stroke-width:10px; stroke-linejoin:round; }
  #overlay { position:absolute; left:0; top:0; width:100%; height:100%; overflow:visible; }
  #side { position:absolute; display:flex; flex-direction:column; gap:16px; }
  #side .entity { position:relative; transform:none; }
  .probe-rest { height:190px; flex:none; }
  .pill { background:var(--card); border:1px solid color-mix(in srgb, var(--accent) 40%, var(--border)); padding:8px 16px; border-radius:9999px;
          box-shadow:0 4px 10px rgba(0, 0, 0, 0.12); font-size:19px; font-weight:600; color:var(--text); white-space:nowrap; }   /* readable on a phone */
  #side .pill { white-space:normal; }
  .telemetry { box-sizing:border-box; min-width:0; max-width:none; padding:14px 24px; text-align:left; }
  .telemetry .t-label { font-size:24px; font-weight:600; color:var(--muted); }
  .telemetry .t-value { font-size:48px; font-weight:700; white-space:nowrap; }
  .dmm { box-sizing:border-box; width:100%; min-width:0; max-width:none; padding:18px 24px 16px; }
  .dmm-head { display:flex; justify-content:space-between; gap:16px; font-size:24px; font-weight:600; color:var(--muted); }
  .dmm-screen { margin:12px 0 14px; padding:8px 18px; border-radius:8px; background:#0F2A1F; color:#4ADE80;
                font-family:"DejaVu Sans Mono", monospace; font-size:52px; font-weight:700; text-align:right;
                box-shadow:inset 0 2px 8px rgba(0, 0, 0, .55); }
  .dmm-pins { min-height:52px; margin-top:10px; font-size:19px; font-weight:600; line-height:1.35; color:var(--muted);
              text-align:left; white-space:pre-line; }
  .dmm-jacks { display:flex; justify-content:space-around; }
  .jack { width:32px; height:32px; border-radius:50%; border:7px solid; box-sizing:border-box; background:#0F172A; }
  .jack.black { border-color:#334155; } .jack.red { border-color:#EF4444; }
  /* LANES: a row per lane: its label, the road (delimited: solid edges, dashed between two lanes) with
     its vehicles and the gate across all lanes, and the count gone through. Sizes in app/layout_solver.py. */
  .lanes { position:relative; width:1260px; }
  .lane { position:absolute; left:0; width:100%; height:104px; }
  .lane-label { position:absolute; left:0; top:0; width:214px; height:100%; display:flex; align-items:center; justify-content:flex-end;
                font-size:28px; font-weight:600; color:var(--text); text-align:right; line-height:1.1; }
  .lane-road { position:absolute; left:230px; top:0; width:900px; height:100%; overflow:hidden; box-sizing:border-box;
               background:color-mix(in srgb, var(--muted) 14%, transparent); border-top:4px dashed color-mix(in srgb, var(--ink) 55%, transparent); }
  .lane:first-child .lane-road { border-top:5px solid var(--ink); }
  .lane:last-child .lane-road { border-bottom:5px solid var(--ink); }
  .lane-car { position:absolute; top:50%; width:62px; height:62px; margin-top:-31px; }
  .lane-gate { position:absolute; top:-10px; width:10px; border-radius:5px; background:var(--accent);
               box-shadow:0 0 16px color-mix(in srgb, var(--accent) 60%, transparent); }
  .lane-count { position:absolute; left:1146px; top:50%; transform:translateY(-50%); min-width:100px; padding:6px 12px; box-sizing:border-box;
                border-radius:10px; background:var(--card); border:2px solid var(--border); text-align:center;
                font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:32px; font-weight:700; color:var(--accent); }
  /* SPEED_RACE: the track's length on top, a row per runner (its label, the track from the start line
     to the finish line, its real time), how many times faster under. Sizes in app/layout_solver.py. */
  .race { position:relative; width:1400px; }
  .race-head { position:absolute; left:230px; top:0; width:900px; text-align:center; font-size:26px; font-weight:600; color:var(--muted); }
  .race-row { position:absolute; left:0; width:100%; height:120px; }
  .race-label { position:absolute; left:0; top:0; width:214px; height:100%; display:flex; align-items:center; justify-content:flex-end;
                font-size:28px; font-weight:600; color:var(--text); text-align:right; line-height:1.1; }
  .race-track { position:absolute; left:230px; top:14px; width:900px; height:92px; box-sizing:border-box; border-radius:10px;
                background:color-mix(in srgb, var(--muted) 14%, transparent); border-left:6px solid var(--ink);
                border-right:6px dashed var(--accent); }
  .race-runner { position:absolute; top:50%; width:62px; height:62px; margin-top:-31px; }
  .race-time { position:absolute; left:1150px; top:50%; transform:translateY(-50%); min-width:150px; padding:6px 14px; box-sizing:border-box;
               border-radius:10px; background:var(--card); border:2px solid var(--border); text-align:center; white-space:nowrap;
               font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:30px; font-weight:700; color:var(--accent); }
  .race-ratio { position:absolute; left:230px; width:900px; text-align:center; }
  .race-ratio span { display:inline-block; padding:8px 20px; border-radius:9999px; background:var(--accent); color:#FFFFFF;
                     font-size:30px; font-weight:700; }
  /* TIDES: the Earth in its ocean on the left, the Moon on the right (sizes in app/layout_solver.py). */
  .tides { position:relative; width:1300px; height:600px; }
  .tunnel { position:relative; width:1300px; height:440px; }
  .wave { position:relative; width:1300px; }
  .tbl { position:relative; display:grid; border-radius:14px; overflow:hidden; border:2px solid var(--border); background:var(--card); }
  .tbl > div { display:flex; align-items:center; justify-content:center; padding:0 14px; font-size:26px; color:var(--text);
               border-bottom:1px solid var(--border); border-right:1px solid var(--border); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .tbl > div.head { font-weight:700; background:color-mix(in srgb, var(--accent) 18%, var(--card)); }
  .tbl > div.pick { background:color-mix(in srgb, var(--accent) 30%, var(--card)); }
  .tbl > div.sum { font-weight:700; border-top:3px solid var(--accent); }
  .chain { position:relative; }
  .simple { position:relative; }
  .simple text { font-size:26px; font-weight:600; fill:var(--text); paint-order:stroke; stroke:var(--bg, #0B1120); stroke-width:5px; stroke-linejoin:round; }
  .simple text.note { font-size:22px; font-weight:500; fill:var(--muted); }
  .simple text.big { font-size:40px; font-weight:700; }
  .simple .eq { position:absolute; left:0; display:flex; align-items:center; justify-content:center; font-size:40px; color:var(--text); }
  .chain .step { position:absolute; display:flex; align-items:center; justify-content:center; text-align:center; padding:10px 16px;
                 box-sizing:border-box; border-radius:16px; border:3px solid var(--border); background:var(--card); color:var(--text);
                 font-size:26px; font-weight:600; line-height:1.15; }
  .chain .step.focus { border-color:var(--accent); box-shadow:0 0 0 6px color-mix(in srgb, var(--accent) 25%, transparent); }
  .wave text { font-size:26px; font-weight:600; fill:var(--text); paint-order:stroke; stroke:var(--bg, #0B1120); stroke-width:5px; }
  .wave text.tide-note { font-size:24px; font-weight:500; fill:var(--muted); }
  .mcu { position:relative; width:760px; height:480px; }
  .bb { position:relative; width:1080px; height:560px; }
  .bb text { font-size:17px; font-weight:600; fill:var(--text); paint-order:stroke; stroke:var(--bg, #0B1120); stroke-width:4px; }
  .bb text.bb-note { font-size:22px; fill:var(--muted); }
  .bb text.bb-chip { font-size:15px; fill:#E5E7EB; stroke:none; font-weight:700; letter-spacing:1px; }
  .part { position:relative; }
  .part text.part-mark { font-size:22px; font-weight:700; fill:var(--ink); stroke:none; }
  .mcu text { font-size:24px; font-weight:600; fill:var(--text); paint-order:stroke; stroke:var(--bg, #0B1120); stroke-width:5px; stroke-linejoin:round; }
  .mcu text.tide-note { font-size:21px; font-weight:500; fill:var(--muted); }
  .mcu text.mcu-code { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:21px; font-weight:600; }
  .tides text, .tunnel text { font-size:24px; font-weight:600; fill:var(--text); paint-order:stroke; stroke:var(--bg, #0B1120); stroke-width:6px; stroke-linejoin:round; }
  .tides text.tide-note, .tunnel text.tide-note { font-size:22px; font-weight:500; fill:var(--muted); }
  .tunnel text { font-size:32px; }
  .tunnel text.tide-note { font-size:28px; }
  /* LOGIC_CIRCUIT and FPGA_GRID: drawn in SVG with the tides' text style; sizes in app/layout_solver.py. */
  .logic, .fpga { position:relative; }
  .logic text, .fpga text { font-size:27px; font-weight:600; fill:var(--text); paint-order:stroke; stroke:var(--bg, #0B1120);
                            stroke-width:6px; stroke-linejoin:round; }
  .fpga text.fpga-file { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:18px; font-weight:600; fill:var(--accent); stroke-width:3px; }
  .fpga text.fpga-bits { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:24px; font-weight:700; fill:var(--accent); }
  .logic text.tide-note, .fpga text.tide-note { font-size:22px; font-weight:500; fill:var(--muted); }
  .logic text.logic-value { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:30px; font-weight:700; }
  .logic .logic-program text:not(.tide-note) { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:26px; font-weight:600; }
  .logic text.logic-bit { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:26px; font-weight:700; }
  .logic .logic-ink { stroke:var(--ink); } .logic .logic-hole { fill:var(--card); }
  /* POPULATION: how many people on top, the grid of dots, the legend (a swatch, a group, its count). */
  .population { position:relative; width:700px; }
  .pop-head { height:44px; line-height:44px; text-align:center; font-size:26px; font-weight:600; color:var(--muted); }
  .pop-grid { display:block; }
  .pop-legend { display:flex; flex-wrap:wrap; justify-content:center; gap:6px 24px; margin-top:12px; }
  .pop-key { display:flex; align-items:center; gap:8px; font-size:24px; font-weight:600; color:var(--text); }
  .pop-swatch { width:18px; height:18px; border-radius:50%; flex:none; }
  /* SEESAW: a beam on a pivot, a load on each end, the balance point's value under the pivot. */
  .seesaw { position:relative; width:1100px; height:470px; }
  .seesaw .beam { position:absolute; height:16px; border-radius:8px; background:var(--ink); transform-origin:0 50%; }
  .seesaw .pivot { position:absolute; width:0; height:0; border-left:48px solid transparent; border-right:48px solid transparent;
                   border-bottom:96px solid var(--accent); filter:drop-shadow(0 0 14px color-mix(in srgb, var(--accent) 45%, transparent)); }
  .seesaw .base { position:absolute; height:8px; border-radius:4px; background:color-mix(in srgb, var(--ink) 45%, transparent); }
  .seesaw .load { position:absolute; display:flex; flex-direction:column; align-items:center; justify-content:center; box-sizing:border-box;
                  width:210px; padding:8px 12px; border-radius:var(--radius); background:var(--card); border:3px solid var(--accent);
                  color:var(--text); font-size:26px; font-weight:600; text-align:center; line-height:1.15;
                  box-shadow:0 12px 24px -8px rgba(0, 0, 0, .45); }
  .seesaw .load b { font-size:40px; font-weight:800; color:var(--accent); }
  .seesaw .end-value { position:absolute; transform:translate(-50%, 0); font-family:"Fira Code", "DejaVu Sans Mono", monospace;
                       font-size:30px; font-weight:700; color:var(--muted); }
  .seesaw .mean { position:absolute; transform:translate(-50%, 0); padding:6px 16px; border-radius:9999px; background:var(--accent);
                  color:#FFFFFF; font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:34px; font-weight:700; white-space:nowrap; }
  .electron { position:absolute; left:0; top:0; width:28px; height:28px; border-radius:50%; background:var(--electron); color:#FFFFFF;
              font:700 26px/26px "Inter", "DejaVu Sans", sans-serif; text-align:center; offset-anchor:center;
              box-shadow:0 0 14px var(--electron); z-index:5; }
  .junction { width:160px; height:14px; border-radius:7px; background:var(--ink); }
  .body-disc { border-radius:50%; box-shadow:0 0 0 4px var(--ring), 0 6px 16px rgba(15, 23, 42, .25); }
  /* A planet, a moon, the Sun: a sphere lit from the top left, its atmosphere or its light around it. */
  .sphere { width:120px; height:120px; border-radius:50%; }
  .compact .sphere { width:72px; height:72px; }
  .sphere.earth { background:radial-gradient(circle at 34% 30%, #BBF7D0 0%, #4ADE80 14%, #2563EB 48%, #1E3A8A 82%, #0B1A4A 100%);
                  box-shadow:0 0 30px rgba(96, 165, 250, .55), inset -10px -12px 24px rgba(2, 6, 23, .55); }
  .sphere.moon { background:radial-gradient(circle at 62% 64%, rgba(75, 85, 99, .55) 0 9%, transparent 10%),
                            radial-gradient(circle at 38% 58%, rgba(75, 85, 99, .45) 0 6%, transparent 7%),
                            radial-gradient(circle at 34% 30%, #F9FAFB 0%, #D1D5DB 35%, #6B7280 85%, #374151 100%);
                 box-shadow:0 0 22px rgba(226, 232, 240, .35), inset -8px -10px 20px rgba(2, 6, 23, .5); }
  .sphere.sun { background:radial-gradient(circle at 45% 42%, #FFFBEB 0%, #FDE68A 25%, #FBBF24 55%, #F97316 100%);
                box-shadow:0 0 60px rgba(251, 191, 36, .75), 0 0 120px rgba(249, 115, 22, .35); }
  /* "tone": what a formula or a badge means, in its colour. */
  :root { --tone-result:#10B981; --tone-warning:#F59E0B; --tone-wrong:#EF4444; --tone-key:var(--accent); }
  .toned { border-width:3px; border-color:var(--tone); background:color-mix(in srgb, var(--tone) 12%, var(--card));
           box-shadow:0 0 0 1px color-mix(in srgb, var(--tone) 25%, transparent), 0 10px 28px color-mix(in srgb, var(--tone) 25%, transparent); }
  .toned.formula { color:color-mix(in srgb, var(--tone) 55%, var(--text)); }
  .pill.toned { color:color-mix(in srgb, var(--tone) 70%, var(--text)); }
  /* "glow" (dark themes): parts lit in their colour. */
  .fx-glow .battery { box-shadow:0 0 24px color-mix(in srgb, var(--pos) 35%, transparent); border-color:color-mix(in srgb, var(--pos) 60%, var(--border)); }
  .fx-glow .meter { box-shadow:0 0 24px color-mix(in srgb, var(--primary) 30%, transparent); }
  .fx-glow .dmm-screen { text-shadow:0 0 12px #10B981; }
  .dmm-beep { margin-top:6px; padding:4px 10px; border-radius:999px; background:#F59E0B; color:#111827; font-weight:700; font-size:18px; text-align:center; }
  .fx-glow .card { box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent), 0 14px 32px rgba(0, 0, 0, .55); }
  .ground { width:60px; height:65px; } .ground svg { width:100%; height:100%; overflow:visible; }
  .bulb { position:relative; width:110px; height:110px; }
  .bulb svg { position:absolute; left:-70px; top:-70px; width:250px; height:250px; overflow:visible; }
  .battery { width:190px; height:96px; display:flex; justify-content:space-between; align-items:center; padding:0 28px;
             box-sizing:border-box; font-size:52px; font-weight:700; min-width:0; }
  .battery .neg { color:var(--neg); } .battery .pos { color:var(--pos); }
  .switch { width:200px; height:90px; position:relative; }
  .switch .dot { position:absolute; bottom:8px; width:22px; height:22px; border-radius:50%; border:5px solid var(--ink);
                 background:var(--card); }
  .switch .lever { position:absolute; left:18px; bottom:22px; width:170px; height:8px; background:var(--ink);
                   transform-origin:left center; border-radius:4px; }
  .meter { width:150px; height:150px; border-radius:50%; border:4px solid var(--border); background:var(--card);
           box-shadow:var(--shadow); display:flex; flex-direction:column; justify-content:center; align-items:center;
           font-weight:700; }
  .meter .unit { font-size:44px; color:var(--ink); } .meter .reading { font-size:26px; color:var(--muted); }
  .formula { font-size:2.2rem; padding:22px 36px; white-space:nowrap; max-width:none; }
  .formula.plain { font-family:"DejaVu Sans Mono", monospace; }
  .icon { width:110px; height:110px; padding:20px; min-width:0; } .icon img { width:100%; height:100%; display:block; }
  .compact .icon { width:60px; height:60px; padding:12px; } .compact .label { margin-top:6px; font-size:24px; }   /* in a graph, or riding */
  .passenger .pop { flex-direction:row; } .passenger .label { margin:0 0 0 8px; }   /* its label on its side: the host's is below */
  .passenger.flip .pop { flex-direction:row-reverse; } .passenger.flip .label { margin:0 8px 0 0; }   /* left of its host: label on the left */
  .tank { position:relative; overflow:hidden; } .tank img { position:relative; }   /* the icon over its water */
  .tank .water { position:absolute; left:0; top:0; width:100%; height:100%; }
  .graph { display:flex; flex-direction:column; align-items:center; }
  .legend { display:flex; flex-wrap:wrap; column-gap:44px; row-gap:10px; justify-content:center; margin-top:14px; max-width:100%; }
  .legend div { display:flex; align-items:center; gap:14px; font-size:30px; font-weight:600; color:var(--ink); white-space:nowrap; }   /* an entry on one line; entries wrap */
  .legend span { width:38px; height:8px; border-radius:4px; }
  .legend .vsym { display:flex; gap:6px; width:auto; height:auto; }   /* a vector's colours (one per arrow it names) */
  .legend .vsym i { display:block; width:38px; height:8px; border-radius:4px; }
  .legend .vtext { width:auto; height:auto; font-weight:500; }
  #vlegend { position:absolute; left:0; right:0; bottom:18px; margin:0; flex-wrap:wrap; row-gap:8px; }
  /* The plan (D.plan): its chapters, one per line, appearing as the voice names them; the one being
     named in the accent colour. The progress (D.progress): where the scene is in the plan, top right. */
  #plan { position:absolute; left:50%; top:210px; bottom:70px; transform:translateX(-50%); display:flex; flex-direction:column;
          justify-content:center; gap:22px; width:1300px; }   /* centred in the room under the titles */
  .plan-item { display:flex; align-items:center; gap:28px; padding:18px 32px; border-radius:var(--radius); background:var(--card);
               border:2px solid var(--border); font-size:40px; font-weight:600; color:var(--text); }
  .plan-item .num { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:34px; font-weight:600; color:var(--accent);
                    min-width:64px; }
  .plan-item.now { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent), 0 0 28px color-mix(in srgb, var(--accent) 35%, transparent); }
  /* Subtitles (D.subtitles): the line being said, at the bottom, readable on any background. */
  #subs { position:absolute; left:50%; bottom:22px; transform:translateX(-50%); width:max-content; max-width:1560px; box-sizing:border-box;
          padding:10px 28px; border-radius:14px; background:rgba(15, 23, 42, .82); color:#F8FAFC; font-size:38px; font-weight:600;
          line-height:1.3; text-align:center; z-index:40; opacity:0; }
  .with-subs .comparison-panel { bottom:118px; }
  /* Film behind the scene (D.footage): its frames full-frame over the theme's background, darkened so
     the titles (white, shadowed) and the drawing read over it. */
  #footage { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
  #footage-shade { position:absolute; inset:0; background:linear-gradient(180deg, rgba(2, 6, 23, .62) 0%, rgba(2, 6, 23, .2) 40%, rgba(2, 6, 23, .2) 70%, rgba(2, 6, 23, .5) 100%); }
  .on-footage #title, .on-footage #subtitle { color:#F8FAFC; text-shadow:0 2px 18px rgba(0, 0, 0, .7); }   /* the panels end above the subtitles */
  #fade { position:absolute; inset:0; z-index:50; background:var(--bg); opacity:0; pointer-events:none; }
  #progress { position:absolute; top:34px; right:40px; display:flex; flex-direction:column; align-items:flex-end; gap:8px; }
  #progress .count { font-family:"Fira Code", "DejaVu Sans Mono", monospace; font-size:22px; font-weight:600; color:var(--muted); letter-spacing:1px; }
  #progress .bars { display:flex; gap:6px; }
  #progress .bars i { display:block; width:26px; height:6px; border-radius:3px; background:color-mix(in srgb, var(--muted) 35%, transparent); }
  #progress .bars i.done { background:color-mix(in srgb, var(--accent) 55%, transparent); }
  #progress .bars i.now { background:var(--accent); box-shadow:0 0 10px color-mix(in srgb, var(--accent) 60%, transparent); }
  .axis-label { font-size:34px; font-weight:600; fill:var(--ink); }
  .tick-label { font-size:26px; fill:var(--muted); }
</style></head>
<body><div id="stage" data-layout="@@LAYOUT@@"><div id="bg"></div>@@LAYOUT_HTML@@<svg id="wires"><defs>
  <radialGradient id="lampGlow"><stop offset="0" stop-color="#FDE68A" stop-opacity="0.95"/>
    <stop offset="0.45" stop-color="#FBBF24" stop-opacity="0.45"/><stop offset="1" stop-color="#FBBF24" stop-opacity="0"/></radialGradient>
  <filter id="electronGlow" filterUnits="userSpaceOnUse" x="0" y="0" width="@@WIDTH@@" height="@@HEIGHT@@">
    <feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <marker id="annHead" viewBox="0 0 6 6" markerWidth="6" markerHeight="6" refX="1" refY="3" orient="auto">
    <path d="M0 0 L6 3 L0 6 Z" fill="#3B82F6"/></marker>
</defs></svg><div id="title"></div><div id="subtitle"></div></div>
<script id="scene" type="application/json">@@DATA@@</script>
<script>
const D = JSON.parse(document.getElementById("scene").textContent);
const stage = document.getElementById("stage"), svg = document.getElementById("wires");
// The channel's theme (fixed in Python): its tokens (each checked to be a "#RRGGBB"), light or dark.
const STYLE = D.style || {tokens: {}};
for (const [key, value] of Object.entries(STYLE.tokens || {}))
  if (/^[a-z0-9-]+$/.test(key) && /^#[0-9A-Fa-f]{6}$/.test(value)) document.documentElement.style.setProperty(`--${key}`, value);
const SVGNS = "http://www.w3.org/2000/svg";
const CURVE_COLORS = ["#3B82F6", "#EF4444", "#10B981", "#8B5CF6", "#F59E0B"];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const easeOutBack = p => { const c = 1.70158; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); };
const easeInOut = p => -(Math.cos(Math.PI * p) - 1) / 2;
const progress = (t, start, length) => clamp((t - start) / length, 0, 1);
const frenchNumber = (v, d) => v.toLocaleString("fr-FR", {minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: "always"});   // 1 000 as 10 000
const LATEX = {"\\times":"×","\\cdot":"·","\\pm":"±","\\leq":"≤","\\geq":"≥","\\neq":"≠","\\approx":"≈","\\Delta":"Δ",
               "\\pi":"π","\\alpha":"α","\\beta":"β","\\theta":"θ","\\lambda":"λ","\\mu":"μ","\\omega":"ω","\\Omega":"Ω"};
const SUP = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹","-":"⁻"};
function latexText(s) {            // fallback when KaTeX is not available
  s = s.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, "($1)/($2)").replace(/\\text\{([^{}]*)\}/g, "$1");
  for (const [k, v] of Object.entries(LATEX)) s = s.split(k).join(v);
  return s.replace(/\^\{?([0-9-]+)\}?/g, (m, g) => [...g].map(c => SUP[c] || c).join("")).replace(/[{}\\]/g, "");
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text); return e; }
function sv(tag, attrs, parent) { const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v); if (parent) parent.append(e); return e; }
function polylineLength(pts) { let n = 0; for (let i = 1; i < pts.length; i++) n += Math.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]); return n; }
function pathD(pts) { return pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" "); }
function springEasing(damping = 0.5, stiffness = 12, seconds = 0.8, samples = 48) {
  // A damped spring (overshoots ~16 %, settles within the 0.8 s) as a CSS linear() easing.
  const wd = stiffness * Math.sqrt(1 - damping * damping), points = [];
  for (let i = 0; i <= samples; i++) {
    const t = i / samples * seconds, decay = Math.exp(-damping * stiffness * t);
    points.push(i === samples ? 1 : 1 - decay * (Math.cos(wd * t) + damping * stiffness / wd * Math.sin(wd * t)));
  }
  return `linear(${points.map(p => p.toFixed(4)).join(", ")})`;
}
document.documentElement.dataset.theme = D.theme || "light";
document.documentElement.style.setProperty("--spring", springEasing());

// ---- graphs: 70 % of the width and 60 % of the height of the frame (shared when there are several)
const ownAxes = ent => ent.type === "CURVE_PLOT" && !(ent.curve.axes && D.entities.some(o => o.id === ent.curve.axes));
const graphCount = D.entities.filter(e => e.type === "AXES_GRAPH" || ownAxes(e)).length;
// A graph takes 70 % x 60 % of the frame when it is alone with what sits in it; with other things
// beside it (icons, formulas, bodies not anchored in it), 55 % x 48 % (three or more: 48 % x 42 %),
// so they find room around it instead of being pushed onto its axes or into the titles.
const besideGraph = D.entities.filter(e => !["AXES_GRAPH", "CURVE_PLOT", "VECTOR_ARROW", "ARROW_ANNOTATION"].includes(e.type)
                                           && !e.instrument && !(e.initial || {}).anchor).length;
const GRAPH_SHARE = besideGraph >= 3 ? [0.48, 0.42] : besideGraph ? [0.55, 0.48] : [0.7, 0.6];
const GRAPH_W = Math.round(D.width * GRAPH_SHARE[0] / Math.max(1, graphCount)), GRAPH_H = Math.round(D.height * GRAPH_SHARE[1]), PAD = 70;
const NUMBER_LINE_H = 2 * PAD + 60;   // a number line's height: its line, ticks and numbers, the dots' labels
function buildAxes(g, holder) {
  if (g.line) return buildNumberLine(g, holder);
  const s = sv("svg", {width: GRAPH_W, height: GRAPH_H, viewBox: `0 0 ${GRAPH_W} ${GRAPH_H}`, overflow: "visible"});
  let [x0, x1] = g.x_range, [y0, y1] = g.y_range;
  if (g.equal) {     // a parametric curve on these axes: one unit as long on x as on y, so a circle stays round
    const unit = Math.max((x1 - x0) / (GRAPH_W - 2 * PAD), (y1 - y0) / (GRAPH_H - 2 * PAD));
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, hw = unit * (GRAPH_W - 2 * PAD) / 2, hh = unit * (GRAPH_H - 2 * PAD) / 2;
    [x0, x1, y0, y1] = [cx - hw, cx + hw, cy - hh, cy + hh];
  }
  const map = (x, y) => [PAD + (x - x0) / (x1 - x0) * (GRAPH_W - 2 * PAD), GRAPH_H - PAD - (y - y0) / (y1 - y0) * (GRAPH_H - 2 * PAD)];
  const ox = clamp(0, x0, x1), oy = clamp(0, y0, y1);         // axes cross at 0, or at the nearest edge
  const axes = sv("g", {"stroke-width": 4, "stroke-linecap": "round"}, s);
  axes.style.stroke = axes.style.fill = "var(--ink)";
  const [ax, ay] = map(x0, oy), [bx] = map(x1, oy), [cx, cy] = map(ox, y0), [, dy] = map(ox, y1);
  sv("line", {x1: ax, y1: ay, x2: bx, y2: ay}, axes); sv("line", {x1: cx, y1: cy, x2: cx, y2: dy}, axes);
  sv("polygon", {points: `${bx + 22},${ay} ${bx},${ay - 11} ${bx},${ay + 11}`, stroke: "none"}, axes);
  sv("polygon", {points: `${cx},${dy - 22} ${cx - 11},${dy} ${cx + 11},${dy}`, stroke: "none"}, axes);
  const step = (lo, hi) => { const r = hi - lo; return r <= 12 ? 1 : r <= 30 ? 5 : r <= 120 ? 10 : niceStep(r); };
  const tick = v => frenchNumber(v, Number.isInteger(v) ? 0 : 1);
  const sx = step(x0, x1), sy = step(y0, y1), [xNumbered, yNumbered] = g.numbered || [true, true];
  // An axis named with no measure ("orbite", "hauteur") is a sketch: no ticks nor numbers along it.
  for (let i = Math.ceil(x0 / sx); xNumbered && i * sx <= x1 + 1e-9; i++) {
    const x = i * sx, [px] = map(x, oy);
    sv("line", {x1: px, y1: ay - 9, x2: px, y2: ay + 9, "stroke-width": 3}, axes);
    if (x !== 0) sv("text", {x: px, y: ay + 40, "text-anchor": "middle", class: "tick-label"}, s).textContent = tick(x);
  }
  for (let i = Math.ceil(y0 / sy); yNumbered && i * sy <= y1 + 1e-9; i++) {
    const y = i * sy, [, py] = map(ox, y);
    sv("line", {x1: cx - 9, y1: py, x2: cx + 9, y2: py, "stroke-width": 3}, axes);
    if (y !== 0) sv("text", {x: cx - 18, y: py + 9, "text-anchor": "end", class: "tick-label"}, s).textContent = tick(y);
  }
  if ((xNumbered || yNumbered) && x0 <= 0 && 0 <= x1 && y0 <= 0 && 0 <= y1) {
    const [px, py] = map(0, 0); sv("circle", {cx: px, cy: py, r: 6, stroke: "none"}, axes);
    sv("text", {x: px - 16, y: py + 40, "text-anchor": "end", class: "tick-label"}, s).textContent = "0";
  }
  // The axis titles over the curves (drawn after their group), outlined in the background colour: a
  // curve passing under one never hides it. A badge must not cover them (placeAnnotations).
  const curves = sv("g", {}, s), labels = [];
  if (g.x_label) { const t = sv("text", {x: bx, y: ay - 24, "text-anchor": "end", class: "axis-label halo"}, s); t.textContent = g.x_label; labels.push(t); }
  if (g.y_label) { const t = sv("text", {x: cx + 26, y: dy + 6, class: "axis-label halo"}, s); t.textContent = g.y_label; labels.push(t); }
  holder.append(s);
  return {svg: s, map, curves, labels, lines: [[ax, ay, bx, ay], [cx, cy, cx, dy]]};   // lines: the two axes
}
// A number line (is_number_line in Python): one graduated line across, no vertical axis; y in [-1, 1]
// spans its small height, so points anchored at y = 0 sit on the line.
function buildNumberLine(g, holder) {
  const W = GRAPH_W, H = NUMBER_LINE_H;
  const s = sv("svg", {width: W, height: H, viewBox: `0 0 ${W} ${H}`, overflow: "visible"});
  const [x0, x1] = g.x_range, mid = H / 2;
  const map = (x, y) => [PAD + (x - x0) / (x1 - x0) * (W - 2 * PAD), mid - y * 30];
  const axes = sv("g", {"stroke-width": 4, "stroke-linecap": "round"}, s);
  axes.style.stroke = axes.style.fill = "var(--ink)";
  const [ax] = map(x0, 0), [bx] = map(x1, 0);
  sv("line", {x1: ax - 30, y1: mid, x2: bx, y2: mid}, axes);
  sv("polygon", {points: `${bx + 22},${mid} ${bx},${mid - 11} ${bx},${mid + 11}`, stroke: "none"}, axes);
  const r = x1 - x0, step = r <= 2 ? 0.1 : r <= 12 ? 1 : niceStep(r), ticks = [];
  for (let i = Math.ceil(x0 / step - 1e-9); i * step <= x1 + 1e-9; i++) {
    const x = Math.round(i * step * 1000) / 1000 + 0, [px] = map(x, 0), whole = Math.abs(x - Math.round(x)) < 1e-9;   // + 0: never "-0"
    sv("line", {x1: px, y1: mid - (whole ? 14 : 8), x2: px, y2: mid + (whole ? 14 : 8), "stroke-width": whole ? 4 : 2}, axes);
    if (whole || r <= 2) {
      const t = sv("text", {x: px, y: mid + 48, "text-anchor": "middle", class: "tick-label"}, s);
      t.textContent = frenchNumber(x, whole ? 0 : 1); ticks.push(t);
    }
  }
  const curves = sv("g", {}, s), labels = [];
  if (g.x_label) { const t = sv("text", {x: bx, y: mid - 30, "text-anchor": "end", class: "axis-label halo"}, s); t.textContent = g.x_label; labels.push(t); }
  holder.append(s);
  return {svg: s, map, curves, labels, ticks, lines: [[ax - 30, mid, bx, mid]], line: true};
}
// A step giving 5 to 10 graduations over a range: 1, 2 or 5 times a power of ten (0 to 10 000: 1 000).
function niceStep(range) {
  const raw = range / 8, unit = Math.pow(10, Math.floor(Math.log10(raw))), k = raw / unit;
  return (k < 1.5 ? 1 : k < 3.5 ? 2 : k < 7.5 ? 5 : 10) * unit;
}
// A number line's dots carry their own labels ("9 000 €"): a graduation's number under one is hidden,
// the dot's label already says where it is; so is one too close to the previous number shown (every
// other one stays). Run once the dots are where they rest (after the first seek).
function hideCoveredTicks() {
  const labels = Object.values(E).filter(e => e.box && e.data.body).map(e => e.box.getBoundingClientRect());
  const hit = (b, r, gap) => Math.min(b.right, r.right) > Math.max(b.left, r.left) - gap && Math.min(b.bottom, r.bottom) > Math.max(b.top, r.top);
  for (const host of Object.values(E).filter(e => e.data.axes && e.data.axes.line)) {
    let last = null;
    for (const t of host.data.axes.ticks) {
      const r = t.getBoundingClientRect();
      if (labels.some(b => hit(b, r, 20)) || (last && hit(last, r, 14))) { t.style.display = "none"; continue; }
      last = r;
    }
  }
}
function curvePath(points, map, closed) {   // gaps (null y) split the curve into separate segments
  const parts = []; let current = [];
  for (const [x, y] of points) { if (y === null) { if (current.length > 1) parts.push(current); current = []; } else current.push(map(x, y)); }
  if (current.length > 1) parts.push(current);
  return parts.map(pathD).join(" ") + (closed && parts.length === 1 ? " Z" : "");   // a circle, an orbit: closed
}
// Axes that carry a parametric curve keep equal scales (see buildAxes).
const parametricOn = id => D.entities.some(c => c.curve && c.curve.parametric && c.curve.axes === id);
// Ground symbols, drawn in a 24 x 26 box at 2.5x (so their strokes match the 7 px wires); the
// port "terminal" is the top of the lead.
function buildGround(shape, type) {
  const s = sv("svg", {viewBox: "0 0 24 26"}), g = sv("g", {fill: "none", "stroke-width": 2.4, "stroke-linecap": "round",
                                                             "stroke-linejoin": "round"}, s);
  g.style.stroke = "var(--ink)";
  if (type === "EARTH_GROUND") {   // protective earth: a lead meeting 3 bars, 24 / 16 / 8 wide
    sv("path", {d: "M12 0 V12 M0 12 H24 M4 17 H20 M8 22 H16"}, g);
  } else {                         // chassis / ground reference: a lead and a triangle pointing down
    sv("path", {d: "M12 0 V11 M2 11 H22 L12 24 Z"}, g);
  }
  shape.append(s);
}
// LANES: queues side by side. Each lane's vehicles stand one behind the other up to the gate and,
// while the lanes run, roll through it at the lane's rate (LANE_STEP px apart, so rate x LANE_STEP px/s):
// worked out from t by seekLanes, nothing runs on its own. The count is how many went through.
const LANE_H = 104, LANE_ROAD = 900, LANE_STEP = 120, LANE_GATE = 700, LANE_CAR = 62;
const LANE_PAST = LANE_GATE + LANE_CAR + 8;     // the gate's line, in the road: a vehicle whose back is past it went through
function buildLanes(ent) {
  const shape = el("div", "lanes");
  shape.style.height = ent.lanes.length * LANE_H + "px";
  ent.laneRows = ent.lanes.map((lane, i) => {
    const row = el("div", "lane"), road = el("div", "lane-road"), count = el("div", "lane-count", "0");
    row.style.top = i * LANE_H + "px";
    row.append(el("div", "lane-label", lane.label || ""), road, count);   // LLM text: textContent only
    const cars = [];
    for (let k = 0; k < Math.ceil(LANE_ROAD / LANE_STEP) + 2; k++) {
      const car = el("img", "lane-car"); car.src = ent.icon; road.append(car); cars.push(car);
    }
    shape.append(row);
    return {rate: Math.min(3, Math.max(0.2, +lane.rate || 1)), cars, count};
  });
  const gate = el("div", "lane-gate");
  Object.assign(gate.style, {left: `${230 + LANE_PAST}px`, height: `${ent.lanes.length * LANE_H + 20}px`});
  shape.append(gate);
  return shape;
}
function laneSeconds(e, t) {        // how long the lanes have run by t: from the pop, minus the stops
  const start = e.spawn + 0.6;
  if (t <= start) return 0;
  let on = true, from = start, total = 0;
  for (const s of e.states) {
    if (!s.state || typeof s.state !== "object" || !("active" in s.state)) continue;
    if (s.at <= start) { on = s.state.active !== false; continue; }
    if (s.at >= t) break;
    if (on) total += s.at - from;
    from = s.at; on = s.state.active !== false;
  }
  return total + (on ? t - from : 0);
}
function seekLanes(e, t) {
  const run = laneSeconds(e, t);
  for (const lane of e.data.laneRows) {
    const travel = run * lane.rate * LANE_STEP;       // vehicle k (0: the first in line) is at LANE_GATE - k x LANE_STEP + travel
    const first = Math.max(0, Math.ceil((LANE_GATE + travel - LANE_ROAD) / LANE_STEP));
    lane.cars.forEach((car, j) => {
      const x = LANE_GATE - (first + j) * LANE_STEP + travel;
      car.style.left = `${x}px`;
      car.style.opacity = x > LANE_PAST ? clamp(1 - (x - LANE_PAST) / (LANE_ROAD - LANE_PAST - LANE_CAR), 0, 1) : 1;
    });
    lane.count.textContent = String(travel > LANE_PAST - LANE_GATE ? Math.floor((travel - LANE_PAST + LANE_GATE) / LANE_STEP) + 1 : 0);   // backs past the gate
  }
}
// SPEED_RACE: the runners set off together (at the pop, or set_state {"go": true}) on one track, to
// one scale: the fastest crosses it in RACE_SEC, the others at their share of its speed, so a runner a
// million times slower does not move a pixel. A runner's real time over the track shows when it
// arrives, or soon after the fastest for one that would take far too long; then the ratio.
const RACE_SEC = 2.5, RACE_ROW = 120, RACE_HEAD = 44, RACE_TRACK = 900, RACE_RUNNER = 62, RACE_WAIT = 6;
function buildRace(ent) {
  const shape = el("div", "race"), z = ent.race;
  shape.style.height = `${RACE_HEAD + z.runners.length * RACE_ROW + 70}px`;
  shape.append(el("div", "race-head", `Même piste : ${z.distance}`));
  ent.raceRows = z.runners.map((r, i) => {
    const row = el("div", "race-row"), track = el("div", "race-track"), runner = el("img", "race-runner"), time = el("div", "race-time", r.time);
    runner.src = r.icon; track.append(runner);
    row.style.top = `${RACE_HEAD + i * RACE_ROW}px`;
    row.append(el("div", "race-label", r.label || ""), track, time);   // LLM text: textContent only
    shape.append(row);
    return {share: r.share, runner, time};
  });
  const ratio = el("div", "race-ratio"); ratio.append(el("span", "", z.ratio));
  ratio.style.top = `${RACE_HEAD + z.runners.length * RACE_ROW + 12}px`;
  shape.append(ratio);
  ent.raceRatio = ratio;
  return shape;
}
function seekRace(e, t) {
  const run = Math.max(0, t - (stateTime(e, "go") ?? e.spawn + 0.6));
  for (const r of e.data.raceRows) {
    const arrives = RACE_SEC / r.share;              // screen seconds to cross, at its share of the fastest's pace
    r.runner.style.left = `${Math.min(1, run / arrives) * (RACE_TRACK - 12 - RACE_RUNNER)}px`;
    const shown = arrives <= RACE_SEC + RACE_WAIT ? arrives : RACE_SEC + 0.8;
    r.time.style.opacity = clamp((run - shown) / 0.4, 0, 1);
  }
  e.data.raceRatio.style.opacity = clamp((run - RACE_SEC - 1.4) / 0.4, 0, 1);
}
// TIDES: the Earth in its ocean, the Moon on its right. Each step on its set_state (never given any: in
// turn from the pop): three points on the Earth-Moon line; the Moon's pull on each, to scale (strongest
// near); what is left once the centre's pull is taken away (both sides move away from the centre);
// the ocean stretched into two bulges (high tide) with low tide between; the Earth turning with a port
// that passes under both bulges (TIDE_DAY s a day, its high tides counted); the Sun in line (bigger
// bulges) or at a right angle (smaller). Every text here is the page's own, in French.
const TIDE_W = 1300, TIDE_H = 600, TIDE_E = [520, 300], TIDE_R = 150, TIDE_SEA = 185, TIDE_MOON = [1220, 300], TIDE_DAY = 8;
const TIDE_AUTO = {points: 0.5, forces: 2.5, relative: 5, stretch: 7.5, spin: 10};
const TIDE_SHAPES = {none: [265, 160], aligned: [295, 148], square: [235, 172]};   // the stretched ocean's half axes
const TIDE_FORCE = {near: 170, centre: 125, far: 90}, TIDE_REL = 80;
function tideArrow(g, x1, y1, x2, color) {
  const dir = Math.sign(x2 - x1) || 1, a = sv("g", {}, g);
  sv("line", {x1, y1, x2: x2 - dir * 14, y2: y1, stroke: color, "stroke-width": 7, "stroke-linecap": "round"}, a);
  sv("polygon", {points: `${x2},${y1} ${x2 - dir * 22},${y1 - 12} ${x2 - dir * 22},${y1 + 12}`, fill: color}, a);
  return a;
}
function tideText(g, x, y, text, anchor = "middle", cls = "") {
  const t = sv("text", {x, y, "text-anchor": anchor, class: cls}, g);
  t.textContent = text;
  return t;
}
function buildTides(ent) {
  const shape = el("div", "tides"), [ex, ey] = TIDE_E, [mx, my] = TIDE_MOON, R = TIDE_R;
  const s = sv("svg", {width: TIDE_W, height: TIDE_H, viewBox: `0 0 ${TIDE_W} ${TIDE_H}`, overflow: "visible"});
  const id = `tide-${String(ent.id).replace(/[^\w-]/g, "_")}`, defs = sv("defs", {}, s);
  const grad = sv("radialGradient", {id: `${id}-land`, cx: "35%", cy: "30%", r: "75%"}, defs);
  [["0%", "#6EE7B7"], ["55%", "#059669"], ["100%", "#064E3B"]].forEach(([o, c]) => sv("stop", {offset: o, "stop-color": c}, grad));
  const z = {};
  z.sea = sv("ellipse", {cx: ex, cy: ey, rx: TIDE_SEA, ry: TIDE_SEA, fill: "#3B82F6", "fill-opacity": 0.35, stroke: "#3B82F6", "stroke-width": 3}, s);
  sv("circle", {cx: ex, cy: ey, r: R, fill: `url(#${id}-land)`}, s);
  tideText(s, ex - R * 0.42, ey - R * 0.5, "Terre");
  sv("circle", {cx: mx, cy: my, r: 44, fill: "#CBD5E1", stroke: "#94A3B8", "stroke-width": 3}, s);
  tideText(s, mx, my + 82, "Lune");
  z.sun = sv("g", {opacity: 0}, s);
  z.sunDisc = sv("circle", {r: 40, fill: "#FBBF24"}, z.sun);
  z.sunName = tideText(z.sun, 0, 74, "Soleil");
  z.sunTide = tideText(z.sun, 0, 102, "", "middle", "tide-note");
  // the pull at three points, then what is left once the centre's is taken away
  const points = [["far", ex - R, "Point opposé"], ["centre", ex, "Centre"], ["near", ex + R, "Point proche"]];
  z.forces = sv("g", {opacity: 0}, s);
  for (const [k, x] of points) tideArrow(z.forces, x, ey, x + TIDE_FORCE[k], "#EF4444");
  tideText(z.forces, ex + R + TIDE_FORCE.near + 16, ey + 8, "attraction de la Lune", "start", "tide-note");
  z.relative = sv("g", {opacity: 0}, s);
  tideArrow(z.relative, ex + R, ey, ex + R + TIDE_REL, "#F59E0B");
  tideArrow(z.relative, ex - R, ey, ex - R - TIDE_REL, "#F59E0B");
  tideText(z.relative, ex, ey - TIDE_SEA - 60, "Sans l'attraction du centre : l'eau s'éloigne des deux côtés", "middle", "tide-note");
  z.points = sv("g", {opacity: 0}, s);
  for (const [k, x, name] of points) {     // the outer two labelled outwards: the three never meet
    sv("circle", {cx: x, cy: ey, r: 10, fill: "#F8FAFC", stroke: "#0F172A", "stroke-width": 3}, z.points);
    tideText(z.points, k === "far" ? x - 14 : k === "near" ? x + 14 : x, ey + 44, name, k === "far" ? "end" : k === "near" ? "start" : "middle");
  }
  // the bulges: high tide on the Earth-Moon line, low tide between, the word explained
  z.tide = sv("g", {opacity: 0}, s);
  z.highNear = tideText(z.tide, 0, ey - 46, "Marée haute", "start");
  z.highFar = tideText(z.tide, 0, ey - 46, "Marée haute", "end");
  z.low = tideText(z.tide, ex, 0, "Marée basse");
  tideText(z.tide, ex, TIDE_H - 6, "Bourrelet : la bosse d'eau, là où c'est marée haute", "middle", "tide-note");
  // the port, turning with the Earth, and its high tides counted
  z.spin = sv("g", {opacity: 0}, s);
  z.port = sv("circle", {r: 11, fill: "#F97316", stroke: "#FFFFFF", "stroke-width": 3}, z.spin);
  z.portName = tideText(z.spin, 0, 0, "Port");
  z.count = tideText(z.spin, TIDE_W - 300, TIDE_H - 40, "");
  shape.append(s);
  ent.tideParts = z;
  return shape;
}
// TUNNEL: first a small circuit, a dashed frame around a bit of its wire ("Vue agrandie"); the view
// zooms into that frame until the frame is the tube: a blue dot in it, the wall a vertical line across
// it. {"bounce": true}: the dot runs into the wall and comes back (a ball); {"tunnel": true}: near the
// wall the dot becomes a wave, most of it stays on its side, a weaker part goes on beyond the wall,
// and the dot comes out whole on the other side, the wall untouched. Never given a state: zoom, then
// tunnel. Every text but the two names is the page's.
const TUN_W = 1300, TUN_H = 440, TUN_Y = 225, TUN_WALL = 650, TUN_FROM = 150, TUN_TO = 1150, TUN_ZOOM = 2.2;
const TUN_RUN = 1.6, TUN_CROSS = 1.4, TUN_OUT = 1.4, TUN_K0 = 0.16;
const TUN_LOOP = {left: -1400, right: 2700, bottom: 1150};    // the circuit, in the zoomed-in frame
function buildTunnel(ent) {
  const shape = el("div", "tunnel"), z = ent.tunnel, p = {};
  const s = sv("svg", {width: TUN_W, height: TUN_H, viewBox: `0 0 ${TUN_W} ${TUN_H}`, overflow: "visible"});
  const clip = `tun-${String(ent.id).replace(/[^\w-]/g, "_")}-clip`;    // the zoom stays inside the drawing
  sv("rect", {x: 0, y: 0, width: TUN_W, height: TUN_H}, sv("clipPath", {id: clip}, sv("defs", {}, s)));
  p.zoom = sv("g", {}, sv("g", {"clip-path": `url(#${clip})`}, s));
  // the circuit around the tube, drawn at the zoomed-in scale (seen small before the zoom)
  p.ctx = sv("g", {}, p.zoom);
  const {left, right, bottom} = TUN_LOOP, wire = {fill: "none", stroke: "var(--muted)", "stroke-width": 26, "stroke-linejoin": "round"};
  sv("path", {d: `M60 ${TUN_Y} H${left} V${TUN_Y + bottom} H${right} V${TUN_Y} H${TUN_W - 60}`, ...wire}, p.ctx);
  sv("circle", {cx: right, cy: TUN_Y + bottom / 2, r: 200, fill: "var(--card)", stroke: "var(--text)", "stroke-width": 26}, p.ctx);
  sv("line", {x1: (left + right) / 2 - 60, y1: TUN_Y + bottom - 200, x2: (left + right) / 2 - 60, y2: TUN_Y + bottom + 100,
              stroke: "var(--text)", "stroke-width": 30}, p.ctx);
  sv("line", {x1: (left + right) / 2 + 60, y1: TUN_Y + bottom - 130, x2: (left + right) / 2 + 60, y2: TUN_Y + bottom + 40,
              stroke: "var(--text)", "stroke-width": 30}, p.ctx);
  sv("rect", {x: 20, y: TUN_Y - 110, width: TUN_W - 40, height: 220, rx: 30, fill: "none", stroke: "var(--accent)",
              "stroke-width": 26, "stroke-dasharray": "70 50"}, p.ctx);
  p.caption = tideText(p.ctx, TUN_W / 2, TUN_Y - 190, "Vue agrandie du fil");
  p.caption.style.fontSize = "170px";
  // the tube, the wall, the dot
  p.view = sv("g", {}, p.zoom);
  sv("rect", {x: 60, y: TUN_Y - 60, width: TUN_W - 120, height: 120, rx: 60, fill: "color-mix(in srgb, #3B82F6 10%, transparent)",
              stroke: "var(--muted)", "stroke-width": 4}, p.view);
  p.wave = sv("path", {d: "", fill: "none", stroke: "#3B82F6", "stroke-width": 5, "stroke-linecap": "round", opacity: 0}, p.view);
  p.wall = sv("line", {x1: TUN_WALL, y1: TUN_Y - 85, x2: TUN_WALL, y2: TUN_Y + 85, stroke: "var(--text)", "stroke-width": 9,
                       "stroke-linecap": "round"}, p.view);
  tideText(p.view, TUN_WALL, TUN_Y - 100, z.barrier);       // LLM text: textContent only
  p.dot = sv("circle", {cx: TUN_FROM, cy: TUN_Y, r: 22, fill: "#3B82F6", stroke: "#BFDBFE", "stroke-width": 3}, p.view);
  p.name = tideText(p.view, TUN_FROM, TUN_Y + 105, z.particle);
  p.note = tideText(s, TUN_W / 2, TUN_H - 12, "", "middle", "tide-note");
  shape.append(s);
  ent.tunnelParts = p;
  return shape;
}
// MICROCONTROLLER: a chip (pins all round), inside it the program memory (numbered instructions) and
// ONE unit. Running (set_state {"run": true}, or from its pop when never given "run"): a pointer goes
// down the program, MCU_STEP s per instruction: the instruction travels along the bus to the unit,
// which then does it (lit, the instruction written in it); after the last, again from the top. The
// count under the chip: "Une instruction à la fois : 2 / 4". Its label is the usual caption under it.
const MCU_W = 760, MCU_H = 480, MCU_STEP = 1.2, MCU_LINE = 31, MCU_TOP = 158;
function buildMcu(ent) {
  const z = ent.mcu, shape = el("div", "mcu"), p = {};
  const s = sv("svg", {width: MCU_W, height: MCU_H, viewBox: `0 0 ${MCU_W} ${MCU_H}`, overflow: "visible"});
  for (let i = 0; i < 9; i++) {         // pins
    const x = 90 + i * 72;
    sv("line", {x1: x, y1: 8, x2: x, y2: 30, stroke: "var(--ink)", "stroke-width": 6}, s);
    sv("line", {x1: x, y1: 410, x2: x, y2: 432, stroke: "var(--ink)", "stroke-width": 6}, s);
  }
  sv("rect", {x: 40, y: 30, width: 680, height: 380, rx: 18, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 5}, s);
  sv("rect", {x: 72, y: 96, width: 320, height: 290, rx: 12, fill: "none", stroke: "var(--muted)", "stroke-width": 3}, s);
  tideText(s, 232, 126, "Mémoire : le programme", "middle", "tide-note");
  p.pointer = sv("rect", {x: 80, y: 0, width: 304, height: MCU_LINE - 3, rx: 6, opacity: 0,
                          fill: "color-mix(in srgb, var(--accent) 25%, transparent)", stroke: "var(--accent)", "stroke-width": 2}, s);
  z.instructions.forEach((text, i) => {
    tideText(s, 92, MCU_TOP + i * MCU_LINE, String(i + 1), "start", "tide-note");
    tideText(s, 122, MCU_TOP + i * MCU_LINE, text, "start", "mcu-code");      // LLM text: textContent only
  });
  tideArrow(s, 396, 240, 470, "var(--muted)");
  p.unit = sv("rect", {x: 476, y: 160, width: 220, height: 160, rx: 14, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 4}, s);
  tideText(s, 586, 194, "Unité de calcul", "middle", "tide-note");
  p.doing = tideText(s, 586, 258, "", "middle", "mcu-code");
  p.token = sv("g", {opacity: 0}, s);
  sv("rect", {x: -16, y: -14, width: 32, height: 28, rx: 6, fill: "var(--accent)"}, p.token);
  p.count = tideText(s, MCU_W / 2, 466, "", "middle", "tide-note");
  shape.append(s);
  ent.mcuParts = p;
  return shape;
}
function seekMcu(e, t) {
  const z = e.data.mcu, p = e.data.mcuParts, n = z.instructions.length;
  const given = e.states.some(s => s.at >= 0 && s.state && typeof s.state === "object" && "run" in s.state);
  const start = given ? stateTime(e, "run") : (e.spawn || 0) + 0.8;
  const stop = given ? (e.states.find(s => s.at >= 0 && s.at > (start ?? Infinity) && s.state && s.state.run === false) || {}).at : undefined;
  const running = start !== null && t >= start && (stop === undefined || t < stop);
  const at = running ? t - start : stop !== undefined && start !== null && t >= stop ? stop - start : -1;
  const step = at < 0 ? -1 : Math.floor(at / MCU_STEP) % n, u = at < 0 ? 0 : (at / MCU_STEP) % 1;
  p.pointer.setAttribute("opacity", step >= 0 ? 1 : 0);
  if (step >= 0) p.pointer.setAttribute("y", MCU_TOP - 23 + step * MCU_LINE);
  // the instruction travels along the bus, then the unit does it
  const travel = running && u < 0.4 ? u / 0.4 : -1;
  p.token.setAttribute("opacity", travel >= 0 ? 1 : 0);
  p.token.setAttribute("transform", `translate(${396 + 74 * Math.max(0, travel)} 240)`);
  const busy = step >= 0 && (u >= 0.4 || !running);
  p.unit.style.stroke = busy ? "var(--accent)" : "var(--ink)";
  p.unit.style.fill = busy && running ? `color-mix(in srgb, var(--accent) ${Math.round(18 + 14 * Math.sin(Math.PI * (u - 0.4) / 0.6))}%, var(--card))` : "var(--card)";
  p.doing.textContent = busy ? z.instructions[step] : "";           // LLM text: textContent only
  p.doing.style.fontSize = busy && z.instructions[step].length > 14 ? `${Math.max(14, Math.round(21 * 14 / z.instructions[step].length))}px` : "";
  p.count.textContent = step >= 0 ? `Une instruction à la fois : ${step + 1} / ${n}` : "";
}
// BREADBOARD: laid out in app/breadboard.py (every coordinate); drawn here: the board, its holes, the
// red (+) and blue (0 V) rails fed by the supply on the left, the parts as they look (a resistor's
// colour bands, the CTN's bead, the trimmer, the DIP-8 op-amp across the gap, the TO-220 MOSFET, the
// LED's dome, the heating resistor's cement body) and the jumpers arching between holes. The parts
// go in one by one (set_state {"step": n}, else one a second): each drops into its holes, then the
// jumpers of what is in. {"on": [ids]}: the LED lit, the heater glowing.
const BB_DROP = 0.45, BB_AUTO = 1.0, BB_STAGGER = 0.6;
function buildBreadboard(ent) {
  const z = ent.breadboard, shape = el("div", "bb"), p = {parts: [], jumpers: []};
  const s = sv("svg", {width: z.width, height: z.height, viewBox: `0 0 ${z.width} ${z.height}`, overflow: "visible"});
  const b = z.board;
  sv("rect", {x: b.x, y: b.y, width: b.w, height: b.h, rx: 14, fill: "#F3F1EA", stroke: "#CFCBBE", "stroke-width": 3}, s);
  sv("rect", {x: b.x + 10, y: (z.rows[4] + z.rows[5]) / 2 - 7, width: b.w - 20, height: 14, rx: 4, fill: "#E2DED2"}, s);   // the gap
  for (const [key, y] of Object.entries(z.rails)) {
    const plus = key.endsWith("+");
    sv("line", {x1: b.x + 16, y1: y - 13, x2: b.x + b.w - 16, y2: y - 13, stroke: plus ? "#EF4444" : "#2563EB", "stroke-width": 3}, s);
    tideText(s, b.x + 4, y + 6, plus ? "+" : "−", "start", "bb-note").style.fill = plus ? "#EF4444" : "#2563EB";
    for (let c = 0; c < z.cols; c++) if (c % 6 !== 5) sv("rect", {x: z.x0 + c * z.pitch - 4, y: y - 4, width: 8, height: 8, rx: 2, fill: "#3F3F46"}, s);
  }
  for (const y of z.rows) for (let c = 0; c < z.cols; c++)
    sv("rect", {x: z.x0 + c * z.pitch - 4, y: y - 4, width: 8, height: 8, rx: 2, fill: "#3F3F46"}, s);
  // the supply on the left, its leads to the top rails
  sv("rect", {x: 6, y: 64, width: 110, height: 92, rx: 10, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 3}, s);
  tideText(s, 61, 100, "Alim", "middle"); tideText(s, 61, 126, z.supply, "middle");       // LLM text: textContent only
  sv("path", {d: `M116 ${z.rails["top,+"] ?? 80} H${z.x0 - 4}`, stroke: "#EF4444", "stroke-width": 5, fill: "none"}, s);
  sv("path", {d: `M116 ${(z.rails["top,-"] ?? 104)} H${z.x0 - 4}`, stroke: "#1E3A8A", "stroke-width": 5, fill: "none"}, s);
  if (z.bridge) for (const [from, to, color] of [["top,+", "bottom,+", "#EF4444"], ["top,-", "bottom,-", "#1E3A8A"]]) {
    const x = z.x0 + (z.cols - 1) * z.pitch + 22;
    sv("path", {d: `M${x - 22} ${z.rails[from]} H${x} V${z.rails[to]} H${x - 22}`, stroke: color, "stroke-width": 5, fill: "none"}, s);
  }
  const layer = sv("g", {}, s), tops = sv("g", {}, s);
  for (const j of z.jumpers) {
    const lift = Math.min(60, 18 + Math.hypot(j.x2 - j.x1, j.y2 - j.y1) / 5), mx = (j.x1 + j.x2) / 2, my = Math.min(j.y1, j.y2) - lift;
    const path = sv("path", {d: `M${j.x1} ${j.y1} Q${mx} ${my} ${j.x2} ${j.y2}`, fill: "none", stroke: j.color, "stroke-width": 6,
                             "stroke-linecap": "round", opacity: 0}, layer);
    p.jumpers.push({path, step: j.step, length: 0});
  }
  for (const part of z.parts) p.parts.push(bbPart(tops, part));
  p.step = tideText(s, 61, 196, "", "middle", "bb-note");           // under the supply: "Étape 3"
  p.note = tideText(s, 61, 224, "", "middle");                       // and the part that went in
  shape.append(s);
  ent.bbParts = p;
  return shape;
}
function bbPart(svg, part) {
  // one part drawn over its leads, its label outside the board (above the top half, below the bottom)
  const g = sv("g", {opacity: 0}, svg), L = part.leads, legs = {stroke: "#9CA3AF", "stroke-width": 4, fill: "none", "stroke-linecap": "round"};
  const cx = L.reduce((a, l) => a + l.x, 0) / L.length, cy = Math.min(...L.map(l => l.y)), xs = L.map(l => l.x);
  const ref = {g, part, glow: null};
  if (part.kind === "OPAMP") {
    const pins = L.map(l => l.x), x1 = Math.min(...pins) - 16, x2 = x1 + 4 * 29 + 4, top = L.find(l => l.name === "vcc").y;
    sv("rect", {x: x1, y: top + 2, width: x2 - x1, height: 36, rx: 4, fill: "#18181B"}, g);
    sv("path", {d: `M${x1} ${top + 12} a8 8 0 0 1 0 16`, fill: "#3F3F46"}, g);
    tideText(g, (x1 + x2) / 2 + 4, top + 26, part.label.slice(0, 10), "middle", "bb-chip");       // LLM text: textContent only
  } else if (L.length === 3) {
    for (const l of L) sv("path", {d: `M${l.x} ${l.y} V${l.y - 18}`, ...legs}, g);
    if (part.kind === "POTENTIOMETER") {
      sv("rect", {x: cx - 26, y: cy - 66, width: 52, height: 50, rx: 6, fill: "#2563EB"}, g);
      sv("circle", {cx, cy: cy - 41, r: 15, fill: "#F3F4F6"}, g);
      sv("path", {d: `M${cx - 9} ${cy - 41} H${cx + 9} M${cx} ${cy - 50} V${cy - 32}`, stroke: "#6B7280", "stroke-width": 3}, g);
    } else {           // a TO-220 MOSFET: black body, metal tab with its hole
      sv("rect", {x: cx - 24, y: cy - 84, width: 48, height: 22, rx: 3, fill: "#9CA3AF"}, g);
      sv("circle", {cx, cy: cy - 73, r: 6, fill: "#F3F1EA"}, g);
      sv("rect", {x: cx - 24, y: cy - 62, width: 48, height: 44, rx: 3, fill: "#18181B"}, g);
    }
  } else {
    const [a, b] = L, mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    sv("path", {d: `M${a.x} ${a.y} L${mx - 26} ${my} M${b.x} ${b.y} L${mx + 26} ${my}`, ...legs}, g);
    if (part.kind === "RESISTOR") {
      sv("rect", {x: mx - 28, y: my - 9, width: 56, height: 18, rx: 8, fill: "#E8D3A9"}, g);
      (part.bands || []).forEach((c, i) => sv("rect", {x: mx - 18 + i * 9 + (i === 3 ? 6 : 0), y: my - 9, width: 5, height: 18, fill: c}, g));
    } else if (part.kind === "THERMISTOR") {
      sv("circle", {cx: mx, cy: my - 4, r: 13, fill: "#1F2937"}, g);
    } else if (part.kind === "DIODE") {
      sv("rect", {x: mx - 20, y: my - 8, width: 40, height: 16, rx: 6, fill: "#18181B"}, g);
      sv("rect", {x: mx + 10, y: my - 8, width: 6, height: 16, fill: "#D1D5DB"}, g);
    } else if (part.kind === "LED") {
      ref.glow = sv("circle", {cx: mx, cy: my - 6, r: 30, fill: "#EF4444", opacity: 0}, g);
      ref.dome = sv("circle", {cx: mx, cy: my - 6, r: 14, fill: "#7F1D1D", stroke: "#EF4444", "stroke-width": 3}, g);
    } else {           // HEATER: a cement power resistor
      ref.glow = sv("rect", {x: mx - 56, y: my - 24, width: 112, height: 40, rx: 10, fill: "#F97316", opacity: 0}, g);
      ref.dome = sv("rect", {x: mx - 46, y: my - 15, width: 92, height: 26, rx: 4, fill: "#F3F4F6", stroke: "#9CA3AF", "stroke-width": 2}, g);
    }
  }
  const above = part.half === "top", ly = part.label_y;
  sv("path", {d: `M${cx} ${above ? ly + 6 : ly - 18} V${above ? cy - 30 : Math.max(...L.map(l => l.y)) + 14}`, stroke: "var(--muted)",
              "stroke-width": 1.5, "stroke-dasharray": "3 4", fill: "none"}, g);
  tideText(g, cx, ly, part.label);                                  // LLM text: textContent only
  return ref;
}
function seekBreadboard(e, t) {
  const p = e.data.bbParts, spawn = e.spawn || 0;
  const stepped = e.states.filter(s => s.at >= 0 && s.state && typeof s.state === "object" && Number.isInteger(s.state.step));
  const shownAt = k => {               // when part k (1-based) goes in: several on one step, one after the other
    if (!stepped.length) return spawn + 0.5 + (k - 1) * BB_AUTO;
    const i = stepped.findIndex(s => s.state.step >= k);
    if (i < 0) return Infinity;
    const before = i ? stepped[i - 1].state.step : 0;
    return stepped[i].at + Math.max(0, k - before - 1) * BB_STAGGER;
  };
  const lit = (stateAt(e, t) || {}).state;
  const on = new Set(lit && typeof lit === "object" && Array.isArray(lit.on) ? lit.on : []);
  let newest = null;
  p.parts.forEach(ref => {
    const at = shownAt(ref.part.step), k = clamp((t - at) / BB_DROP, 0, 1);
    ref.g.setAttribute("opacity", k);
    ref.g.setAttribute("transform", `translate(0 ${-30 * (1 - easeInOut(k))})`);
    if (k > 0 && (!newest || at > newest.at || (at === newest.at && ref.part.step > newest.ref.part.step))) newest = {at, ref};
    if (ref.glow) {
      const heat = on.has(ref.part.id) ? 1 : 0;
      ref.glow.setAttribute("opacity", heat * (ref.part.kind === "LED" ? 0.45 : 0.35 + 0.15 * Math.sin(t * 4)));
      if (ref.part.kind === "LED") ref.dome.style.fill = heat ? "#EF4444" : "#7F1D1D";
      else ref.dome.style.fill = heat ? "#FDBA74" : "#F3F4F6";
    }
  });
  p.jumpers.forEach(j => {
    const at = shownAt(j.step) + BB_DROP, k = clamp((t - at) / 0.5, 0, 1);
    if (!j.length) j.length = j.path.getTotalLength();
    j.path.setAttribute("opacity", k > 0 ? 1 : 0);
    j.path.setAttribute("stroke-dasharray", j.length);
    j.path.setAttribute("stroke-dashoffset", j.length * (1 - easeInOut(k)));
  });
  p.step.textContent = newest ? `Étape ${newest.ref.part.step}` : "";
  p.note.textContent = newest ? newest.ref.part.label : "";         // LLM label: textContent only
}
// WAVE: a mechanical wave across WAVE_W px, its medium drawn as it is: a rope (a line through its
// points), the sea (a surface over blue water, a buoy), a crowd (a row of spectators standing up and
// sitting down: an ola), a spring (coils squeezed and spread: longitudinal, compressions named). A
// pulse (a bump crossing, again and again) or a continuous wave (a sine). The marked point (the buoy,
// one spectator, one coil) only moves up and down (or back and forth): its path is drawn beside it.
// "energy": an arrow travelling with the crest. Every text is the page's own.
const WAVE_W = 1300, WAVE_Y = 210, WAVE_X0 = 70, WAVE_X1 = 1230, WAVE_A = 80, WAVE_SPEED = 260, WAVE_LEN = 300;
const WAVE_COUNT = {rope: 24, water: 80, crowd: 14, spring: 46};
// A standing wave: z.loops loops (its harmonic) between the rope's two tied ends; drawn STANDING_DOWN px
// lower, the two waves it is the sum of on their own ropes over it ("parts"): one going right, one left.
const STANDING_DOWN = 200, STANDING_H = 620, PART_Y = [70, 175], PART_A = 34;
function waveShift(z, x, u) {        // the medium's displacement at x, u s after the wave set off
  if (z.kind === "standing") {
    const k = (z.loops || 3) * Math.PI / (WAVE_X1 - WAVE_X0);
    return Math.sin(k * (x - WAVE_X0)) * Math.cos(2 * Math.PI * u * 0.8);
  }
  if (z.kind === "continuous") return Math.sin(2 * Math.PI * ((x - WAVE_X0) / WAVE_LEN - u * WAVE_SPEED / WAVE_LEN)) * (u * WAVE_SPEED > x - WAVE_X0 ? 1 : 0);
  const span = WAVE_X1 - WAVE_X0 + 260, front = WAVE_X0 - 130 + (u * WAVE_SPEED) % span;     // a bump, crossing again and again
  return Math.exp(-(((x - front) / 70) ** 2));
}
function buildWave(ent) {
  const z = ent.wave, shape = el("div", "wave"), p = {pts: []}, standing = z.kind === "standing", H = standing ? STANDING_H : 420;
  shape.style.height = `${H}px`;
  const svg = sv("svg", {width: WAVE_W, height: H, viewBox: `0 0 ${WAVE_W} ${H}`, overflow: "visible"});
  if (standing) {                    // the two waves going opposite ways, each on its own rope, then "=" their sum
    p.lanes = sv("g", {opacity: 0}, svg);
    p.partsDrawn = PART_Y.map((y, j) => {
      sv("line", {x1: WAVE_X0, y1: y, x2: WAVE_X1, y2: y, stroke: "var(--muted)", "stroke-width": 1.5, "stroke-dasharray": "4 8"}, p.lanes);
      tideText(p.lanes, j ? WAVE_X1 : WAVE_X0, y - PART_A - 14, j ? "← Onde qui revient" : "Onde qui va →", j ? "end" : "start", "tide-note");
      return sv("path", {d: "", fill: "none", stroke: j ? "#F472B6" : "#38BDF8", "stroke-width": 5, "stroke-linecap": "round"}, p.lanes);
    });
    tideText(p.lanes, 30, (PART_Y[0] + PART_Y[1]) / 2 + 10, "+");
    tideText(p.lanes, 30, PART_Y[1] + 72, "=");
  }
  const s = standing ? sv("g", {transform: `translate(0 ${STANDING_DOWN})`}, svg) : svg;   // the rope itself
  const n = WAVE_COUNT[z.mode] || 28;
  p.xs = Array.from({length: n}, (_, i) => WAVE_X0 + i * (WAVE_X1 - WAVE_X0) / (n - 1));
  p.mark = Math.round(n * 0.55);
  if (z.mode === "water") {
    p.sea = sv("path", {d: "", fill: "color-mix(in srgb, #3B82F6 35%, transparent)", stroke: "#60A5FA", "stroke-width": 4}, s);
    p.buoy = sv("g", {}, s);
    sv("circle", {cx: 0, cy: -16, r: 18, fill: "#F59E0B", stroke: "#FDE68A", "stroke-width": 3}, p.buoy);
  } else if (z.mode === "crowd") {
    sv("line", {x1: WAVE_X0 - 40, y1: WAVE_Y + 110, x2: WAVE_X1 + 40, y2: WAVE_Y + 110, stroke: "var(--muted)", "stroke-width": 4}, s);
    p.people = p.xs.map(x => { const g = sv("g", {}, s);
      sv("circle", {cx: 0, cy: -58, r: 14, fill: "var(--ink)"}, g);
      sv("path", {d: "M0 -44 V8 M0 8 L-14 40 M0 8 L14 40", ...INK, "stroke-width": 6}, g);
      const arms = sv("path", {d: "", ...INK, "stroke-width": 6}, g);
      return {g, arms}; });
  } else if (z.mode === "spring") {
    p.coils = p.xs.map(() => sv("line", {y1: WAVE_Y - 50, y2: WAVE_Y + 50, stroke: "var(--ink)", "stroke-width": 4, "stroke-linecap": "round"}, s));
    sv("line", {x1: WAVE_X0, y1: WAVE_Y, x2: WAVE_X1, y2: WAVE_Y, stroke: "var(--muted)", "stroke-width": 2, "stroke-dasharray": "6 8"}, s);
    p.squeeze = tideText(s, 0, WAVE_Y + 92, "Compression", "middle", "tide-note");
    p.spread = tideText(s, 0, WAVE_Y - 66, "Dilatation", "middle", "tide-note");
  } else {
    if (standing) {                  // its tied ends (the rope cannot move there), its nodes and antinodes named
      const loops = z.loops || 3, step = (WAVE_X1 - WAVE_X0) / loops;
      for (const x of [WAVE_X0, WAVE_X1]) sv("rect", {x: x - 12, y: WAVE_Y - 50, width: 24, height: 100, rx: 4, fill: "var(--muted)"}, s);
      tideText(s, WAVE_X0, WAVE_Y + 82, "Fixée", "middle", "tide-note"); tideText(s, WAVE_X1, WAVE_Y + 82, "Fixée", "middle", "tide-note");
      p.nodes = Array.from({length: loops + 1}, (_, i) => WAVE_X0 + i * step);
      p.nodes.forEach((x, i) => { sv("circle", {cx: x, cy: WAVE_Y, r: 10, fill: "#22C55E"}, s);
        if (i && i < loops) tideText(s, x, WAVE_Y + 110, "Nœud", "middle", "tide-note"); });
      for (let i = 0; i < loops; i++) tideText(s, WAVE_X0 + (i + 0.5) * step, WAVE_Y - WAVE_A - 34, "Ventre", "middle", "tide-note");
    }
    p.rope = sv("path", {d: "", ...INK, "stroke-width": 6}, s);
    p.dots = p.xs.map(() => sv("circle", {r: 7, fill: "var(--ink)"}, s));
  }
  // the marked point's own path: a short line it goes up and down (or back and forth) along
  p.track = sv("line", {stroke: "#F59E0B", "stroke-width": 3, "stroke-dasharray": "6 6", opacity: 0}, s);
  p.dot = sv("circle", {r: 13, fill: "#F59E0B", stroke: "#FDE68A", "stroke-width": 3, opacity: 0}, s);
  p.note = tideText(svg, WAVE_W / 2, H - 12, "", "middle", "tide-note");
  p.energy = sv("g", {opacity: 0}, s);
  tideArrow(p.energy, -70, 0, 70, "#EF4444");
  tideText(p.energy, 0, -22, "Énergie");
  shape.append(svg);
  ent.waveParts = p;
  return shape;
}
function seekWave(e, t) {
  const z = e.data.wave, p = e.data.waveParts, spawn = e.spawn || 0;
  const given = e.states.filter(s => s.at >= 0 && s.state && typeof s.state === "object" && "go" in s.state);
  const go = given.length ? stateTime(e, "go") : spawn + 0.5;
  const stop = given.length ? (given.find(s => s.state.go === false && s.at > (go ?? Infinity)) || {}).at : undefined;
  const u = go === null || t < go ? -1 : (stop !== undefined && t > stop ? stop : t) - go;
  const shift = x => u < 0 ? 0 : waveShift(z, x, u);
  const marked = !e.states.some(s => s.at >= 0 && s.state && typeof s.state === "object" && "mark" in s.state) || stateTime(e, "mark") !== null && t >= stateTime(e, "mark");
  const mx = p.xs[p.mark];
  let markXY = [mx, WAVE_Y];
  if (z.mode === "water") {
    const top = p.xs.map(x => [x, WAVE_Y - 50 * shift(x)]);
    p.sea.setAttribute("d", `M${WAVE_X0} 380 L${top.map(q => q.join(" ")).join(" L")} L${WAVE_X1} 380 Z`);
    markXY = [mx, WAVE_Y - 50 * shift(mx)];
    p.buoy.setAttribute("transform", `translate(${markXY[0]} ${markXY[1]})`);
  } else if (z.mode === "crowd") {
    p.people.forEach((person, i) => {
      const up = shift(p.xs[i]);
      person.g.setAttribute("transform", `translate(${p.xs[i]} ${WAVE_Y + 70 - 60 * up})`);
      person.arms.setAttribute("d", up > 0.5 ? "M0 -30 L-22 -78 M0 -30 L22 -78" : "M0 -30 L-18 0 M0 -30 L18 0");
      person.g.querySelector("circle").style.fill = i === p.mark && marked ? "#F59E0B" : "var(--ink)";
    });
    markXY = [mx, WAVE_Y + 12 - 60 * shift(mx)];
  } else if (z.mode === "spring") {
    let squeeze = null, spread = null, most = 0, least = 0;
    p.coils.forEach((c, i) => {
      const x = p.xs[i] + 22 * shift(p.xs[i]);
      c.setAttribute("x1", x); c.setAttribute("x2", x);
      c.style.stroke = i === p.mark && marked ? "#F59E0B" : "";
      if (i) { const gap = x - (p.xs[i - 1] + 22 * shift(p.xs[i - 1])), d = gap - (p.xs[1] - p.xs[0]);
               if (d < most) { most = d; squeeze = x; } if (d > least) { least = d; spread = x; } }
    });
    p.squeeze.setAttribute("x", squeeze ?? -999); p.squeeze.setAttribute("opacity", most < -4 ? 1 : 0);
    p.spread.setAttribute("x", spread ?? -999); p.spread.setAttribute("opacity", least > 4 ? 1 : 0);
    markXY = [mx + 22 * shift(mx), WAVE_Y];
  } else {
    const pts = p.xs.map(x => [x, WAVE_Y - WAVE_A * shift(x)]), fine = [];       // the rope: a smooth curve, its points on it
    for (let x = WAVE_X0; x <= WAVE_X1; x += 6) fine.push(`${x} ${(WAVE_Y - WAVE_A * shift(x)).toFixed(1)}`);
    p.rope.setAttribute("d", "M" + fine.join(" L"));
    if (p.partsDrawn) {              // the two waves going opposite ways, each on its own rope: their sum is the rope below
      const k = (z.loops || 3) * Math.PI / (WAVE_X1 - WAVE_X0), w = 2 * Math.PI * 0.8 * Math.max(u, 0), on = stateTime(e, "parts");
      p.partsDrawn.forEach((path, j) => {
        const pts = [];
        for (let x = WAVE_X0; x <= WAVE_X1; x += 8) pts.push(`${x} ${(PART_Y[j] - PART_A * Math.sin(k * (x - WAVE_X0) + (j ? w : -w))).toFixed(1)}`);
        path.setAttribute("d", "M" + pts.join(" L"));
      });
      p.lanes.setAttribute("opacity", on !== null && t >= on ? clamp((t - on) / 0.5, 0, 1) : 0);
    }
    p.dots.forEach((d, i) => { d.setAttribute("cx", pts[i][0]); d.setAttribute("cy", pts[i][1]); });
    markXY = pts[p.mark];
  }
  // the marked point and its path: up and down (or back and forth), never along
  if (z.kind === "standing") p.mark = Math.round((p.xs.length - 1) / (2 * (z.loops || 3)));     // on the first antinode
  const vertical = z.mode !== "spring", reach = z.mode === "crowd" ? 60 : z.mode === "water" ? 50 : z.mode === "spring" ? 22 : WAVE_A;
  p.dot.setAttribute("opacity", marked && z.mode !== "crowd" && z.mode !== "water" ? 1 : 0);
  p.dot.setAttribute("cx", markXY[0]); p.dot.setAttribute("cy", z.mode === "spring" ? WAVE_Y - 62 : markXY[1]);
  const base = z.mode === "crowd" ? WAVE_Y + 12 : WAVE_Y;
  if (vertical) { p.track.setAttribute("x1", mx + 34); p.track.setAttribute("x2", mx + 34);
                  p.track.setAttribute("y1", base + 10); p.track.setAttribute("y2", base - reach - 10); }
  else { p.track.setAttribute("x1", mx - 10); p.track.setAttribute("x2", mx + reach + 10);
         p.track.setAttribute("y1", WAVE_Y - 62); p.track.setAttribute("y2", WAVE_Y - 62); }
  p.track.setAttribute("opacity", marked ? 1 : 0);
  p.note.textContent = !marked ? "" : z.mode === "crowd" ? "Chaque spectateur se lève puis se rassoit, à sa place"
                     : z.mode === "spring" ? "Chaque spire va et vient, à sa place : la compression, elle, avance"
                     : z.mode === "water" ? "La bouée monte et descend : l'eau n'avance pas"
                     : z.kind === "standing" ? "Les nœuds ne bougent jamais, les ventres oscillent le plus : rien n'avance"
                     : "Le point monte et descend : il n'avance pas";
  // the energy: an arrow with the crest
  const shown = z.kind === "standing" ? null : stateTime(e, "energy");   // a standing wave carries no energy along
  if (shown !== null && t >= shown && u >= 0) {
    // with the bump (a pulse), or at the front of a continuous wave: where the energy has got to
    let crest = Math.min(WAVE_X1, WAVE_X0 + u * WAVE_SPEED) - 40, top = -Infinity;
    if (z.kind !== "continuous") for (let x = WAVE_X0; x <= WAVE_X1; x += 10) { const v = shift(x); if (v > top) { top = v; crest = x; } }
    p.energy.setAttribute("opacity", clamp((t - shown) / 0.4, 0, 1));
    p.energy.setAttribute("transform", `translate(${crest} ${z.mode === "spring" ? WAVE_Y - 110 : WAVE_Y - WAVE_A - 70})`);
  } else p.energy.setAttribute("opacity", 0);
}
// TABLE: a grid of cells (textContent only), the header first; the rows come in one after the other
// (set_state {"fill": n}, else one every TABLE_STEP s from its pop); {"row": i} / {"column": j} pick one
// out; {"total": true}: the last row, "Total" and the sums worked out in Python.
const TABLE_STEP = 0.7;
function buildTable(ent) {
  const z = ent.table, shape = el("div", "tbl"), p = {cells: [], total: []};
  shape.style.gridTemplateColumns = z.widths.map(w => `${w}px`).join(" ");
  shape.style.gridAutoRows = `${z.row}px`;
  z.columns.forEach(c => shape.append(el("div", "head", c)));
  z.rows.forEach(r => p.cells.push(r.map(c => { const d = el("div", "", c); shape.append(d); return d; })));
  p.total = z.total.map(c => { const d = el("div", "sum", c); d.hidden = true; shape.append(d); return d; });
  ent.tableParts = p;
  return shape;
}
function seekTable(e, t) {
  const z = e.data.table, p = e.data.tableParts, spawn = e.spawn || 0;
  const given = e.states.filter(s => s.at >= 0 && s.at <= t && s.state && typeof s.state === "object");
  const fills = e.states.filter(s => s.at >= 0 && s.state && Number.isInteger(s.state.fill));
  const inAt = i => { if (!fills.length) return spawn + 0.5 + i * TABLE_STEP;
                      const s = fills.find(s => s.state.fill > i); return s ? s.at + Math.max(0, i - ((fills[fills.indexOf(s) - 1] || {state: {fill: 0}}).state.fill)) * 0.3 : Infinity; };
  const last = given.length ? given[given.length - 1].state : {};
  p.cells.forEach((row, i) => row.forEach((d, j) => {
    const k = clamp((t - inAt(i)) / 0.4, 0, 1);
    d.style.opacity = k; d.style.transform = `translateY(${(1 - k) * 12}px)`;
    d.classList.toggle("pick", last.row === i || last.column === j);
  }));
  const sum = stateTime(e, "total");
  p.total.forEach(d => { d.hidden = sum === null || t < sum; d.style.opacity = sum === null ? 0 : clamp((t - sum) / 0.4, 0, 1); });
}
// CHAIN: steps in boxes (textContent only), an arrow from each to the next, laid out in Python (four in a
// row at most, then a second row); {"loop": true}: an arrow from the last back to the first, under them.
// The boxes come in one after the other (set_state {"step": n}, else one every CHAIN_STEP s).
const CHAIN_STEP = 1.0;
function buildChain(ent) {
  const z = ent.chain, shape = el("div", "chain"), p = {boxes: [], arrows: []};
  Object.assign(shape.style, {width: `${z.width}px`, height: `${z.height}px`});
  const svg = sv("svg", {width: z.width, height: z.height, viewBox: `0 0 ${z.width} ${z.height}`, overflow: "visible", style: "position:absolute;left:0;top:0"});
  shape.append(svg);
  const [w, h] = z.box;
  const arrow = (d) => { const g = sv("g", {opacity: 0}, svg);
    sv("path", {d, fill: "none", stroke: "var(--accent)", "stroke-width": 5, "stroke-linecap": "round", "marker-end": "url(#annHead)"}, g); return g; };
  z.centres.forEach(([x, y], i) => {
    const box = el("div", "step", z.steps[i]);
    Object.assign(box.style, {left: `${x - w / 2}px`, top: `${y - h / 2}px`, width: `${w}px`, height: `${h}px`, opacity: 0});
    shape.append(box); p.boxes.push(box);
    if (i) {                         // from the last box: along its row, or down to the start of the next row
      const [px, py] = z.centres[i - 1];
      p.arrows.push(arrow(py === y ? `M${px + w / 2 + 6} ${y} H${x - w / 2 - 14}`
                                   : `M${px} ${py + h / 2 + 6} V${(py + y) / 2} H${x} V${y - h / 2 - 14}`));
    }
  });
  if (z.loop) {
    // under the boxes, up their left side, into the first one: around the others, never through them
    const [fx, fy] = z.centres[0], [lx, ly] = z.centres[z.centres.length - 1], bottom = z.height - 20;
    p.loop = arrow(`M${lx} ${ly + h / 2 + 6} V${bottom} H24 V${fy} H${fx - w / 2 - 14}`);
  }
  ent.chainParts = p;
  return shape;
}
function seekChain(e, t) {
  const z = e.data.chain, p = e.data.chainParts, spawn = e.spawn || 0;
  const steps = e.states.filter(s => s.at >= 0 && s.state && Number.isInteger(s.state.step));
  const inAt = i => { if (!steps.length) return spawn + 0.4 + i * CHAIN_STEP; const s = steps.find(s => s.state.step > i); return s ? s.at : Infinity; };
  const focus = (e.states.filter(s => s.at >= 0 && s.at <= t && s.state && "focus" in s.state).pop() || {state: {}}).state.focus;
  p.boxes.forEach((b, i) => {
    const k = clamp((t - inAt(i)) / 0.5, 0, 1);
    b.style.opacity = k; b.style.transform = `scale(${0.85 + 0.15 * k})`;
    b.classList.toggle("focus", focus === i);
  });
  p.arrows.forEach((a, i) => a.setAttribute("opacity", clamp((t - inAt(i + 1) + 0.3) / 0.3, 0, 1)));
  if (p.loop) p.loop.setAttribute("opacity", clamp((t - inAt(p.boxes.length - 1) - 0.6) / 0.4, 0, 1));
}
// The simple catalogue pieces (TIMELINE, FRACTION_BAR, PIE_CHART, UNIT_CONVERTER, TREE, SET_DIAGRAM,
// GAME_MATRIX, BAR_CHART, EQUATION_STEPS, POWER_SUPPLY): worked out in Python (simple_data), drawn here in
// SVG, every text from the brief as textContent. Things come in one after the other: set_state {"step": n}
// (or {"level": n} for a tree), else one every SIMPLE_STEP s from the pop.
const SIMPLE_STEP = 0.8, SIMPLE_COLORS = ["#3B82F6", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#06B6D4", "#EC4899"];
function inTurn(e, key, i, t0 = 0.4) {          // when the i-th thing comes in
  const given = e.states.filter(s => s.at >= 0 && s.state && Number.isInteger(s.state[key]));
  if (!given.length) return (e.spawn || 0) + t0 + i * SIMPLE_STEP;
  const s = given.find(s => s.state[key] > i);
  return s ? s.at : Infinity;
}
function lastState(e, t, key) {                 // the last value set for key by now, or undefined
  const s = e.states.filter(s => s.at >= 0 && s.at <= t && s.state && typeof s.state === "object" && key in s.state).pop();
  return s ? s.state[key] : undefined;
}
function txt(g, x, y, text, anchor = "middle", cls = "") { return tideText(g, x, y, text, anchor, cls); }
function arc(cx, cy, r, a0, a1) {               // an SVG pie slice from angle a0 to a1 (degrees, 0 = right, clockwise)
  const p = a => [cx + r * Math.cos(a * Math.PI / 180), cy + r * Math.sin(a * Math.PI / 180)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${cx} ${cy} L${x0} ${y0} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1} Z`;
}
function buildSimple(ent) {
  const z = ent.simple, shape = el("div", "simple"), p = {items: []};
  Object.assign(shape.style, {width: `${z.width}px`, height: `${z.height}px`});
  const s = sv("svg", {width: z.width, height: z.height, viewBox: `0 0 ${z.width} ${z.height}`, overflow: "visible"});
  shape.append(s);
  const ink = {stroke: "var(--ink)", "stroke-width": 4, fill: "none", "stroke-linecap": "round"};
  if (z.kind === "TIMELINE") {
    sv("line", {x1: 40, y1: 150, x2: z.width - 30, y2: 150, ...ink}, s);
    sv("path", {d: `M${z.width - 30} 150 l-18 -10 v20 Z`, fill: "var(--ink)"}, s);
    z.events.forEach((ev, i) => { const g = sv("g", {opacity: 0}, s), up = i % 2 === 0;
      sv("circle", {cx: ev.x, cy: 150, r: 12, fill: "var(--accent)"}, g);
      sv("line", {x1: ev.x, y1: 150, x2: ev.x, y2: up ? 96 : 204, stroke: "var(--muted)", "stroke-width": 2}, g);
      txt(g, ev.x, up ? 80 : 232, ev.date, "middle", "big").style.fontSize = "30px";
      txt(g, ev.x, up ? 44 : 268, ev.label, "middle", "note");
      p.items.push(g); });
  } else if (z.kind === "FRACTION_BAR") {
    const x0 = 60, w = z.width - 120, cell = w / z.total;
    p.cells = Array.from({length: z.total}, (_, i) => sv("rect", {x: x0 + i * cell, y: 80, width: cell, height: 100, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 3}, s));
    let from = 0;
    z.parts.forEach(part => { const g = sv("g", {opacity: 0}, s), mid = x0 + (from + part.n / 2) * cell;
      txt(g, mid, 60, part.label, "middle", "note"); p.items.push({g, from, n: part.n, color: part.color}); from += part.n; });
    p.sum = txt(s, z.width / 2, 250, z.sum, "middle", "big"); p.sum.setAttribute("opacity", 0);
  } else if (z.kind === "PIE_CHART") {
    const cx = 280, cy = z.height / 2, r = 220;
    z.slices.forEach((sl, i) => { const g = sv("g", {opacity: 0}, s), mid = (sl.start + sl.sweep / 2) * Math.PI / 180;
      const path = sv("path", {d: arc(cx, cy, r, sl.start, sl.start + sl.sweep - 0.01), fill: sl.color, stroke: "var(--bg, #0B1120)", "stroke-width": 3}, g);
      if (sl.sweep > 22) txt(g, cx + 0.62 * r * Math.cos(mid), cy + 0.62 * r * Math.sin(mid) + 9, `${sl.pct} %`).style.fill = "#FFFFFF";
      const ly = 90 + i * 64;
      sv("rect", {x: 580, y: ly - 22, width: 30, height: 30, rx: 6, fill: sl.color}, g);
      txt(g, 626, ly, `${sl.label} : ${sl.pct} %`, "start");
      txt(g, 626, ly + 26, sl.value, "start", "note");
      p.items.push({g, path, mid}); });
  } else if (z.kind === "UNIT_CONVERTER") {
    const n = z.ladder.length, step = (z.width - 200) / Math.max(1, n - 1), y = 120;
    p.rungs = z.ladder.map((u, i) => { const x = 100 + i * step;
      sv("rect", {x: x - 50, y: y - 34, width: 100, height: 60, rx: 10, fill: "var(--card)", stroke: "var(--border)", "stroke-width": 3}, s);
      txt(s, x, y + 6, u); return x; });
    const src = z.ladder.indexOf(z.src), dst = z.ladder.indexOf(z.dst);
    p.token = sv("circle", {cx: p.rungs[src], cy: y - 54, r: 12, fill: "var(--accent)", opacity: 0}, s);
    p.factor = txt(s, (p.rungs[src] + p.rungs[dst]) / 2, y - 76, z.factor, "middle", "big"); p.factor.setAttribute("opacity", 0);
    p.result = txt(s, z.width / 2, 300, `${z.value} ${z.src} = ${z.result} ${z.dst}`, "middle", "big"); p.result.setAttribute("opacity", 0);
    p.from = p.rungs[src]; p.to = p.rungs[dst];
  } else if (z.kind === "TREE") {
    const at = path => path.length ? z.nodes.find(n => n.path.join("/") === path.join("/")) : z.root;
    txt(s, z.root.x, z.root.y + 9, z.root.label, "middle");
    p.nodes = z.nodes.map(n => { const g = sv("g", {opacity: 0}, s), par = at(n.parent);
      const line = sv("line", {x1: par.x + 60, y1: par.y, x2: n.x - 70, y2: n.y, stroke: "var(--ink)", "stroke-width": 3}, g);
      if (n.p !== null) txt(g, (par.x + 60 + n.x - 70) / 2, (par.y + n.y) / 2 - 10, n.p, "middle", "note");
      txt(g, n.x, n.y + 9, n.label);
      const prod = n.leaf && n.product !== null ? txt(g, n.x + 90, n.y + 9, `→ ${n.product}`, "start", "note") : null;
      return {g, line, n, prod}; });
  } else if (z.kind === "SET_DIAGRAM") {
    const cy = z.height / 2 - 10, ra = 170, ax = z.width / 2 - 100, bx = z.width / 2 + 100;
    p.frame = sv("rect", {x: 20, y: 20, width: z.width - 40, height: z.height - 80, rx: 18, fill: "none", stroke: "var(--muted)", "stroke-width": 2}, s);
    const defs = sv("defs", {}, s), id = `venn-${String(ent.id).replace(/[^\w-]/g, "_")}`;
    sv("circle", {cx: ax, cy, r: ra}, sv("clipPath", {id: `${id}-a`}, defs));
    sv("circle", {cx: bx, cy, r: ra}, sv("clipPath", {id: `${id}-b`}, defs));
    p.shade = {
      a: sv("circle", {cx: ax, cy, r: ra, fill: "var(--accent)", opacity: 0}, s),
      b: sv("circle", {cx: bx, cy, r: ra, fill: "var(--accent)", opacity: 0}, s),
      both: sv("circle", {cx: bx, cy, r: ra, fill: "var(--accent)", opacity: 0, "clip-path": `url(#${id}-a)`}, s),
      only_a: sv("path", {d: `M0 0 H${z.width} V${z.height} H0 Z`, fill: "var(--accent)", opacity: 0, "clip-path": `url(#${id}-a)`}, s),
      neither: sv("rect", {x: 20, y: 20, width: z.width - 40, height: z.height - 80, rx: 18, fill: "var(--accent)", opacity: 0}, s)};
    sv("circle", {cx: ax, cy, r: ra, fill: "none", stroke: "#3B82F6", "stroke-width": 4}, s);
    sv("circle", {cx: bx, cy, r: ra, fill: "none", stroke: "#F59E0B", "stroke-width": 4}, s);
    txt(s, ax - 90, cy - ra + 20, z.a); txt(s, bx + 90, cy - ra + 20, z.b);
    txt(s, ax - 70, cy + 10, String(z.counts.only_a), "middle", "big"); txt(s, bx + 70, cy + 10, String(z.counts.only_b), "middle", "big");
    txt(s, z.width / 2, cy + 10, String(z.counts.both), "middle", "big");
    if (z.counts.neither !== null) txt(s, 70, z.height - 90, String(z.counts.neither), "middle", "big");
    p.caption = txt(s, z.width / 2, z.height - 22, "", "middle");
  } else if (z.kind === "GAME_MATRIX") {
    const x0 = 330, y0 = 140, cw = 300, ch = 150;
    txt(s, x0 + cw, 40, z.players[1]); txt(s, 110, y0 + ch, z.players[0], "middle");
    z.strategies[1].forEach((st, j) => txt(s, x0 + cw * (j + 0.5), 100, st, "middle", "note"));
    z.strategies[0].forEach((st, i) => txt(s, x0 - 20, y0 + ch * (i + 0.5) + 8, st, "end", "note"));
    p.cells = [];
    for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
      const x = x0 + j * cw, y = y0 + i * ch;
      const rect = sv("rect", {x, y, width: cw, height: ch, fill: "var(--card)", stroke: "var(--border)", "stroke-width": 3}, s);
      const a = txt(s, x + cw * 0.3, y + ch / 2 + 12, z.payoffs[i][j][0], "middle", "big"), b = txt(s, x + cw * 0.7, y + ch / 2 + 12, z.payoffs[i][j][1], "middle", "big");
      a.style.fill = "#3B82F6"; b.style.fill = "#F59E0B";
      p.cells.push({i, j, rect, a, b});
    }
    p.caption = txt(s, x0 + cw, y0 + 2 * ch + 50, "", "middle");
  } else if (z.kind === "BAR_CHART") {
    const left = 120, right = z.width - 40, top = 40, bottom = z.height - 90, span = (z.high - z.low) || 1;
    const y = v => bottom - (bottom - top) * (v - z.low) / span, w = (right - left) / z.bars.length;
    sv("line", {x1: left, y1: y(0), x2: right, y2: y(0), ...ink}, s);
    p.bars = z.bars.map((b, i) => { const g = sv("g", {}, s), x = left + w * (i + 0.2);
      const rect = sv("rect", {x, y: y(0), width: w * 0.6, height: 0, rx: 6, fill: SIMPLE_COLORS[0]}, g);
      txt(g, x + w * 0.3, bottom + 40, b.label, "middle", "note");
      const val = txt(g, x + w * 0.3, (b.value >= 0 ? y(b.value) - 12 : y(b.value) + 34), b.text); val.setAttribute("opacity", 0);
      return {rect, val, to: y(b.value), zero: y(0)}; });
    if (z.line !== null) { p.line = sv("g", {opacity: 0}, s);
      sv("line", {x1: left, y1: y(z.line), x2: right, y2: y(z.line), stroke: "#EF4444", "stroke-width": 3, "stroke-dasharray": "10 8"}, p.line);
      txt(p.line, right, y(z.line) - 10, z.line_text, "end", "note"); }
  } else if (z.kind === "EQUATION_STEPS") {
    p.lines = z.steps.map((latex, i) => { const box = el("div", "eq");
      Object.assign(box.style, {top: `${i * z.line}px`, width: `${z.width}px`, height: `${z.line - 40}px`, opacity: 0});
      if (window.katex) katex.render(latex, box, {throwOnError: false, trust: false, strict: "ignore", maxSize: 10, maxExpand: 200});
      else box.textContent = latex;
      shape.append(box); return box; });
    p.notes = z.notes.map((note, i) => { const g = sv("g", {opacity: 0}, s), y = (i + 1) * z.line - 26;
      sv("path", {d: `M${z.width / 2} ${y - 16} V${y + 12}`, stroke: "var(--accent)", "stroke-width": 4, "marker-end": "url(#annHead)"}, g);
      txt(g, z.width / 2 + 30, y + 6, note, "start", "note"); return g; });
  } else if (z.kind === "POWER_SUPPLY") {
    sv("rect", {x: 10, y: 10, width: z.width - 20, height: z.height - 60, rx: 16, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 4}, s);
    sv("rect", {x: 30, y: 30, width: z.width - 60, height: 70, rx: 8, fill: "#0F2A1F"}, s);
    p.volts = txt(s, z.width / 2, 78, "", "middle", "big"); p.volts.style.fill = "#4ADE80";
    p.amps = txt(s, z.width / 2, 130, "", "middle", "note");
    p.cv = sv("circle", {cx: 60, cy: 150, r: 9, fill: "#14532D"}, s); txt(s, 78, 157, "CV", "start", "note");
    p.cc = sv("circle", {cx: 150, cy: 150, r: 9, fill: "#7F1D1D"}, s); txt(s, 168, 157, "CC", "start", "note");
    sv("circle", {cx: z.width * 0.25, cy: z.height - 50, r: 14, fill: "#1E3A8A"}, s); txt(s, z.width * 0.25, z.height - 14, "−");
    sv("circle", {cx: z.width * 0.75, cy: z.height - 50, r: 14, fill: "#DC2626"}, s); txt(s, z.width * 0.75, z.height - 14, "+");
  }
  ent.simpleParts = p;
  return shape;
}
function seekSimple(e, t) {
  const z = e.data.simple, p = e.data.simpleParts, ease = (at, d = 0.5) => clamp((t - at) / d, 0, 1);
  if (z.kind === "TIMELINE") {
    const focus = lastState(e, t, "focus");
    p.items.forEach((g, i) => { g.setAttribute("opacity", ease(inTurn(e, "step", i)));
      g.querySelector("circle").setAttribute("r", focus === i ? 18 : 12); });
  } else if (z.kind === "FRACTION_BAR") {
    p.cells.forEach(c => c.style.fill = "var(--card)");
    p.items.forEach((part, i) => { const k = ease(inTurn(e, "step", i));
      part.g.setAttribute("opacity", k);
      for (let c = part.from; c < part.from + part.n; c++) if (k > 0) p.cells[c].style.fill = `color-mix(in srgb, ${part.color} ${Math.round(85 * k)}%, var(--card))`; });
    const sum = stateTime(e, "sum");
    p.sum.setAttribute("opacity", sum === null ? 0 : ease(sum));
  } else if (z.kind === "PIE_CHART") {
    const focus = lastState(e, t, "focus");
    p.items.forEach((it, i) => { it.g.setAttribute("opacity", ease(inTurn(e, "step", i)));
      const out = focus === i ? 26 : 0;
      it.g.setAttribute("transform", `translate(${out * Math.cos(it.mid)} ${out * Math.sin(it.mid)})`); });
  } else if (z.kind === "UNIT_CONVERTER") {
    const go = e.states.some(s => s.state && "go" in s.state) ? stateTime(e, "go") : (e.spawn || 0) + 0.6;
    const k = go === null ? 0 : easeInOut(ease(go, 1.6));
    p.token.setAttribute("opacity", go !== null && t >= go ? 1 : 0);
    p.token.setAttribute("cx", p.from + (p.to - p.from) * k);
    p.factor.setAttribute("opacity", go === null ? 0 : ease(go + 0.3));
    p.result.setAttribute("opacity", go === null ? 0 : ease(go + 1.6));
  } else if (z.kind === "TREE") {
    const path = lastState(e, t, "path");
    const on = n => Array.isArray(path) && path.slice(0, n.path.length).join("/") === n.path.join("/");
    p.nodes.forEach(({g, line, n, prod}) => {
      g.setAttribute("opacity", ease(inTurn(e, "level", n.depth)));
      line.style.stroke = on(n) ? "var(--accent)" : ""; line.style.strokeWidth = on(n) ? 6 : "";
      if (prod) prod.setAttribute("opacity", Array.isArray(path) ? (on(n) && path.length === n.path.length ? 1 : 0.25) : 1);
    });
  } else if (z.kind === "SET_DIAGRAM") {
    const show = lastState(e, t, "show"), names = {a: z.a, b: z.b, both: `${z.a} et ${z.b}`, either: `${z.a} ou ${z.b}`,
      only_a: `${z.a} seulement`, only_b: `${z.b} seulement`, neither: "Ni l'un ni l'autre"};
    const k = show === undefined ? 0 : 0.35;
    for (const [key, el2] of Object.entries(p.shade)) el2.setAttribute("opacity", 0);
    if (show === "a" || show === "either" || show === "only_a") p.shade.a.setAttribute("opacity", k);
    if (show === "b" || show === "either") p.shade.b.setAttribute("opacity", k);
    if (show === "both") p.shade.both.setAttribute("opacity", k);
    if (show === "only_b") p.shade.b.setAttribute("opacity", k);
    if (show === "neither") p.shade.neither.setAttribute("opacity", 0.2);
    p.caption.textContent = show && names[show] !== undefined && z.counts[show] !== null && z.counts[show] !== undefined
      ? `${names[show]} : ${z.counts[show]}` + (z.p[show] ? `  (probabilité ${z.p[show]})` : "") : "";
  } else if (z.kind === "GAME_MATRIX") {
    const best = lastState(e, t, "best"), nash = stateTime(e, "nash") !== null && t >= stateTime(e, "nash");
    p.cells.forEach(c => {
      c.a.style.textDecoration = best === 0 && z.best[0][c.i][c.j] ? "underline" : "";
      c.b.style.textDecoration = best === 1 && z.best[1][c.i][c.j] ? "underline" : "";
      c.rect.style.fill = nash && z.nash[c.i][c.j] ? "color-mix(in srgb, var(--accent) 35%, var(--card))" : "var(--card)";
      c.rect.style.stroke = nash && z.nash[c.i][c.j] ? "var(--accent)" : "";
    });
    p.caption.textContent = nash ? (z.nash.flat().some(Boolean) ? "Équilibre de Nash : personne ne gagne à changer seul" : "Pas d'équilibre de Nash en stratégies pures") : "";
  } else if (z.kind === "BAR_CHART") {
    const focus = lastState(e, t, "focus");
    p.bars.forEach((b, i) => { const k = easeInOut(ease(inTurn(e, "step", i), 0.7)), top = b.zero + (b.to - b.zero) * k;
      b.rect.setAttribute("y", Math.min(top, b.zero)); b.rect.setAttribute("height", Math.abs(top - b.zero));
      b.rect.style.fill = focus === i ? SIMPLE_COLORS[1] : SIMPLE_COLORS[0];
      b.val.setAttribute("opacity", k >= 1 ? 1 : 0); });
    if (p.line) p.line.setAttribute("opacity", ease((e.spawn || 0) + 0.3));
  } else if (z.kind === "EQUATION_STEPS") {
    p.lines.forEach((l, i) => { const k = ease(inTurn(e, "step", i, 0.3)); l.style.opacity = k; l.style.transform = `translateY(${(1 - k) * 14}px)`; });
    p.notes.forEach((g, i) => g.setAttribute("opacity", ease(inTurn(e, "step", i + 1, 0.3) - 0.4)));
  } else if (z.kind === "POWER_SUPPLY") {
    const on = lastState(e, t, "output") === true, v = lastState(e, t, "voltage"), cc = lastState(e, t, "cc") === true;
    const target = typeof v === "number" ? v : z.voltage;
    p.volts.textContent = on ? `${frenchNumber(cc ? target * 0.6 : target, 2)} V` : "0,00 V";
    p.amps.textContent = `Limite ${frenchNumber(z.limit, 2)} A`;
    p.cv.style.fill = on && !cc ? "#22C55E" : "#14532D";
    p.cc.style.fill = on && cc ? "#EF4444" : "#7F1D1D";
  }
}
// Physics pieces (FREE_BODY, KINEMATICS, COLLISION, OSCILLATOR, ORBIT): their figures worked out in
// Python (phys_data); here, things move by the same exact formulas, time slowed or sped up so that one
// motion lasts PHYS_RUN s on screen. Texts from the brief as textContent only.
const PHYS_RUN = 3.5;
function arrowSvg(g, x1, y1, x2, y2, color, width = 5) {     // a straight arrow, its head at (x2, y2)
  const a = Math.atan2(y2 - y1, x2 - x1), h = 16;
  sv("line", {x1, y1, x2: x2 - Math.cos(a) * h * 0.6, y2: y2 - Math.sin(a) * h * 0.6, stroke: color, "stroke-width": width, "stroke-linecap": "round"}, g);
  sv("path", {d: `M${x2} ${y2} L${x2 - h * Math.cos(a - 0.4)} ${y2 - h * Math.sin(a - 0.4)} L${x2 - h * Math.cos(a + 0.4)} ${y2 - h * Math.sin(a + 0.4)} Z`, fill: color}, g);
}
function physStart(e, key = "go") {             // when the motion starts: its "go", else from the pop
  return e.states.some(s => s.state && typeof s.state === "object" && key in s.state) ? stateTime(e, key) : (e.spawn || 0) + 0.6;
}
function shownFrom(e, key, t, d = 0.5) { const at = stateTime(e, key); return at === null ? 0 : clamp((t - at) / d, 0, 1); }
function buildPhys(ent) {
  const z = ent.phys, shape = el("div", "simple"), p = {};
  Object.assign(shape.style, {width: `${z.width}px`, height: `${z.height}px`});
  const s = sv("svg", {width: z.width, height: z.height, viewBox: `0 0 ${z.width} ${z.height}`, overflow: "visible"});
  shape.append(s); p.s = s;
  if (z.kind === "FREE_BODY") {
    const cx = z.width / 2 - 80, cy = z.height / 2, rad = -z.incline * Math.PI / 180;
    p.world = sv("g", {}, s);
    if (z.incline) sv("path", {d: `M${cx - 330} ${cy + 60 + 330 * Math.tan(-rad)} L${cx + 330} ${cy + 60 - 330 * Math.tan(-rad)} L${cx + 330} ${cy + 60 + 330 * Math.tan(-rad)} Z`,
                              fill: "color-mix(in srgb, var(--muted) 25%, transparent)", stroke: "var(--muted)", "stroke-width": 3}, s);
    else sv("line", {x1: cx - 330, y1: cy + 60, x2: cx + 330, y2: cy + 60, stroke: "var(--muted)", "stroke-width": 4}, s);
    p.body = sv("g", {transform: `translate(${cx} ${cy}) rotate(${-z.incline})`}, s);
    if (z.body === "ball") sv("circle", {cx: 0, cy: 0, r: 56, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 4}, p.body);
    else sv("rect", {x: -70, y: -58, width: 140, height: 116, rx: 10, fill: "var(--card)", stroke: "var(--ink)", "stroke-width": 4}, p.body);
    p.centre = [cx, cy];
    p.axes = sv("g", {opacity: 0, transform: `translate(${cx} ${cy}) rotate(${-z.incline})`}, s);
    arrowSvg(p.axes, -230, 0, 230, 0, "var(--muted)", 2); arrowSvg(p.axes, 0, 230, 0, -230, "var(--muted)", 2);
    txt(p.axes, 240, -10, "x", "start", "note"); txt(p.axes, 10, -236, "y", "start", "note");
    p.forces = z.forces.map((f, i) => { const g = sv("g", {opacity: 0}, s), dx = f.x * z.scale, dy = -f.y * z.scale;
      arrowSvg(g, cx, cy, cx + dx, cy + dy, SIMPLE_COLORS[i % SIMPLE_COLORS.length]);
      txt(g, cx + dx * 1.12 + (dx >= 0 ? 10 : -10), cy + dy * 1.12 + 8, `${f.symbol} = ${f.text}`, dx >= 0 ? "start" : "end");
      // its components along the axes (tilted with the slope): ex = (cos θ, sin θ), ey = (−sin θ, cos θ), y up
      const proj = sv("g", {opacity: 0}, s), th = z.incline * Math.PI / 180, ex = [Math.cos(th), Math.sin(th)], ey = [-Math.sin(th), Math.cos(th)];
      const fx = f.x * ex[0] + f.y * ex[1], fy = f.x * ey[0] + f.y * ey[1];
      const px = [cx + fx * ex[0] * z.scale, cy - fx * ex[1] * z.scale], py = [cx + fy * ey[0] * z.scale, cy - fy * ey[1] * z.scale];
      sv("line", {x1: cx + dx, y1: cy + dy, x2: px[0], y2: px[1], stroke: SIMPLE_COLORS[i % SIMPLE_COLORS.length], "stroke-width": 2, "stroke-dasharray": "6 6"}, proj);
      sv("line", {x1: cx + dx, y1: cy + dy, x2: py[0], y2: py[1], stroke: SIMPLE_COLORS[i % SIMPLE_COLORS.length], "stroke-width": 2, "stroke-dasharray": "6 6"}, proj);
      return {g, proj}; });
    p.sum = sv("g", {opacity: 0}, s);
    if (!z.balanced) arrowSvg(p.sum, cx, cy, cx + z.sum[0] * z.scale, cy - z.sum[1] * z.scale, "#EF4444", 7);
    txt(p.sum, z.width / 2, z.height - 16, z.sum_text, "middle");
  } else if (z.kind === "KINEMATICS") {
    const left = 80, bottom = z.height - 70, w = 760, h = z.height - 160, T = z.T;
    const pos = tt => z.motion === "projectile" ? [z.vx * tt, z.vy * tt - z.g * tt * tt / 2]
                    : z.motion === "free_fall" ? [0, -z.g * tt * tt / 2]
                    : z.motion === "accelerated" ? [z.vx * tt + z.a * tt * tt / 2, 0] : [z.vx * tt, 0];
    const vel = tt => z.motion === "projectile" ? [z.vx, z.vy - z.g * tt] : z.motion === "free_fall" ? [0, -z.g * tt]
                    : z.motion === "accelerated" ? [z.vx + z.a * tt, 0] : [z.vx, 0];
    const pts = Array.from({length: 41}, (_, i) => pos(T * i / 40));
    const xs = pts.map(q => q[0]), ys = pts.map(q => q[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1, y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
    const k = Math.min(w / ((x1 - x0) || 1), h / ((y1 - y0) || 1)), base = z.motion === "free_fall" ? left + w / 2 : left;
    const X = q => base + (q[0] - x0) * (z.motion === "free_fall" ? 0 : k), Y = q => bottom - (q[1] - y0) * k - (z.motion === "free_fall" ? 0 : 0);
    p.pos = pos; p.vel = vel; p.X = X; p.Y = Y; p.k = Math.min(k, 30);
    sv("line", {x1: left - 20, y1: bottom, x2: left + w + 20, y2: bottom, stroke: "var(--muted)", "stroke-width": 3}, s);
    sv("path", {d: "M" + pts.map(q => `${X(q).toFixed(1)} ${Y(q).toFixed(1)}`).join(" L"), fill: "none", stroke: "var(--muted)", "stroke-width": 2, "stroke-dasharray": "6 8"}, s);
    p.ghosts = Array.from({length: 8}, (_, i) => sv("circle", {cx: X(pos(T * (i + 1) / 9)), cy: Y(pos(T * (i + 1) / 9)), r: 12, fill: "var(--accent)", opacity: 0}, s));
    p.dot = sv("circle", {r: 16, fill: "#F59E0B", stroke: "#FDE68A", "stroke-width": 3}, s);
    p.vecs = sv("g", {opacity: 0}, s);
    // the graphs on the right: x(t) and v(t)
    p.graphs = sv("g", {opacity: 0}, s);
    const gx = left + w + 80, gw = z.width - gx - 30, gh = (z.height - 170) / 2;
    p.gbox = [gx, gw, gh];
    [["x(t)", 30], ["v(t)", 60 + gh]].forEach(([name, y]) => {
      sv("line", {x1: gx, y1: y + gh, x2: gx + gw, y2: y + gh, stroke: "var(--muted)", "stroke-width": 2}, p.graphs);
      sv("line", {x1: gx, y1: y, x2: gx, y2: y + gh, stroke: "var(--muted)", "stroke-width": 2}, p.graphs);
      txt(p.graphs, gx + 8, y + 18, name, "start", "note"); });
    p.gx = sv("path", {d: "", fill: "none", stroke: "#3B82F6", "stroke-width": 4}, p.graphs);
    p.gv = sv("path", {d: "", fill: "none", stroke: "#22C55E", "stroke-width": 4}, p.graphs);
    const speeds = Array.from({length: 41}, (_, i) => Math.hypot(...vel(T * i / 40)));
    p.vmax = Math.max(...speeds, 1e-9); p.xmax = Math.max(...pts.map(q => Math.hypot(q[0] - pts[0][0], q[1] - pts[0][1])), 1e-9);
    txt(s, (left + left + w) / 2, z.height - 16, z.text, "middle", "note");
  } else if (z.kind === "COLLISION") {
    const r1 = 30 + 18 * Math.sqrt(z.m1), r2 = 30 + 18 * Math.sqrt(z.m2), y = 190;
    sv("line", {x1: 40, y1: y + Math.max(r1, r2) + 4, x2: z.width - 40, y2: y + Math.max(r1, r2) + 4, stroke: "var(--muted)", "stroke-width": 3}, s);
    p.b1 = sv("g", {}, s); sv("circle", {r: r1, fill: "#3B82F6"}, p.b1); txt(p.b1, 0, 9, z.masses[0]).style.fill = "#FFFFFF";
    p.b2 = sv("g", {}, s); sv("circle", {r: r2, fill: "#F59E0B"}, p.b2); txt(p.b2, 0, 9, z.masses[1]).style.fill = "#111827";
    p.v1 = sv("g", {}, s); p.v2 = sv("g", {}, s); p.r = [r1, r2]; p.y = y;
    p.flash = sv("circle", {r: 30, fill: "#FDE68A", opacity: 0}, s);
    p.balance = sv("g", {opacity: 0}, s);
    txt(p.balance, z.width / 2, 340, z.before); txt(p.balance, z.width / 2, 384, z.after); txt(p.balance, z.width / 2, 430, z.verdict, "middle", "note");
  } else if (z.kind === "OSCILLATOR") {
    if (z.osc === "spring") {
      sv("rect", {x: 40, y: 120, width: 24, height: 180, fill: "var(--muted)"}, s);
      sv("line", {x1: 40, y1: 300, x2: 720, y2: 300, stroke: "var(--muted)", "stroke-width": 3}, s);
      p.spring = sv("path", {d: "", fill: "none", stroke: "var(--ink)", "stroke-width": 4, "stroke-linejoin": "round"}, s);
      p.mass = sv("rect", {y: 160, width: 120, height: 120, rx: 10, fill: "#3B82F6"}, s);
      p.rest = sv("line", {x1: 360, y1: 110, x2: 360, y2: 310, stroke: "var(--muted)", "stroke-width": 2, "stroke-dasharray": "6 6"}, s);
    } else {
      sv("rect", {x: 300, y: 36, width: 120, height: 14, fill: "var(--muted)"}, s);
      p.string = sv("line", {x1: 360, y1: 50, stroke: "var(--ink)", "stroke-width": 3}, s);
      p.bob = sv("circle", {r: 30, fill: "#3B82F6"}, s);
      sv("line", {x1: 360, y1: 50, x2: 360, y2: 400, stroke: "var(--muted)", "stroke-width": 2, "stroke-dasharray": "6 6"}, s);
    }
    p.energy = sv("g", {opacity: 0}, s);           // two bars: kinetic, potential
    txt(p.energy, 830, 420, "Ec", "middle", "note"); txt(p.energy, 930, 420, "Ep", "middle", "note");
    p.ec = sv("rect", {x: 805, width: 50, fill: "#22C55E"}, p.energy); p.ep = sv("rect", {x: 905, width: 50, fill: "#F59E0B"}, p.energy);
    p.graph = sv("g", {opacity: 0}, s);
    sv("line", {x1: 1000, y1: 250, x2: z.width - 20, y2: 250, stroke: "var(--muted)", "stroke-width": 2}, p.graph);
    txt(p.graph, 1010, 110, z.osc === "spring" ? "x(t)" : "θ(t)", "start", "note");
    p.curve = sv("path", {d: "", fill: "none", stroke: "#3B82F6", "stroke-width": 4}, p.graph);
    p.period = txt(s, 380, z.height - 20, z.period, "middle", "big"); p.period.setAttribute("opacity", 0);
  } else if (z.kind === "ORBIT") {
    const a = 300, b = a * Math.sqrt(1 - z.e * z.e), c = a * z.e, cx = z.width / 2 + c, cy = z.height / 2 - 10;
    p.geo = {a, b, c, cx, cy};       // the ellipse's centre at (cx - c, cy); the central body at the focus (cx, cy)
    sv("ellipse", {cx: cx - c, cy, rx: a, ry: b, fill: "none", stroke: "var(--muted)", "stroke-width": 2, "stroke-dasharray": "6 8"}, s);
    p.areas = sv("g", {opacity: 0}, s);
    p.sweeps = [sv("path", {d: "", fill: "#3B82F6", opacity: 0.35}, p.areas), sv("path", {d: "", fill: "#F59E0B", opacity: 0.35}, p.areas)];
    sv("circle", {cx, cy, r: 46, fill: "#2563EB"}, s); txt(s, cx, cy + 80, z.central, "middle", "note");
    // P (nearest, on the right: E = 0) and A (farthest), always named; their distances to the focus with the ratio
    const px = cx - c + a, ax = cx - c - a;
    p.dist = sv("g", {opacity: 0}, s);
    sv("line", {x1: cx + 46, y1: cy, x2: px, y2: cy, stroke: "#3B82F6", "stroke-width": 3, "stroke-dasharray": "8 6"}, p.dist);
    sv("line", {x1: ax, y1: cy, x2: cx - 46, y2: cy, stroke: "#F59E0B", "stroke-width": 3, "stroke-dasharray": "8 6"}, p.dist);
    txt(p.dist, (cx + 46 + px) / 2, cy - 14, "r_P", "middle", "note"); txt(p.dist, (ax + cx - 46) / 2, cy - 14, "r_A", "middle", "note");
    p.ratio = z.ratio.map((line, i) => txt(p.dist, z.width / 2, cy + b + 46 + 34 * i, line, "middle", "note"));
    for (const [x, name, anchor, dx] of [[px, z.near, "start", 12], [ax, z.far, "end", -12]]) {
      sv("circle", {cx: x, cy, r: 8, fill: "var(--ink)"}, s);
      txt(s, x + dx, cy + 34, name, anchor, "note");
    }
    p.force = sv("g", {}, s); p.speed = sv("g", {}, s);
    p.sat = sv("circle", {r: 14, fill: "#F59E0B"}, s); p.name = txt(s, 0, 0, z.body, "middle", "note");
  }
  ent.physParts = p;
  return shape;
}
function keplerAt(e, M) {           // the eccentric anomaly E for the mean anomaly M: E - e sin E = M (Newton)
  let E = M;
  for (let i = 0; i < 8; i++) E -= (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
  return E;
}
function seekPhys(e, t) {
  const z = e.data.phys, p = e.data.physParts;
  if (z.kind === "FREE_BODY") {
    p.forces.forEach((f, i) => { f.g.setAttribute("opacity", clamp((t - inTurn(e, "step", i)) / 0.5, 0, 1));
      f.proj.setAttribute("opacity", shownFrom(e, "project", t)); });
    p.axes.setAttribute("opacity", shownFrom(e, "axes", t));
    p.sum.setAttribute("opacity", shownFrom(e, "sum", t));
    const move = stateTime(e, "move"), u = move === null || t < move || z.balanced ? 0 : Math.min(t - move, 2.5);
    const shift = 0.5 * 40 * u * u, len = Math.hypot(...z.sum) || 1;      // drawn moving the way the resultant goes
    p.body.setAttribute("transform", `translate(${p.centre[0] + shift * z.sum[0] / len} ${p.centre[1] - shift * z.sum[1] / len}) rotate(${-z.incline})`);
  } else if (z.kind === "KINEMATICS") {
    const go = physStart(e), slow = z.T / PHYS_RUN, tt = go === null || t < go ? 0 : Math.min((t - go) * slow, z.T);
    const q = p.pos(tt), v = p.vel(tt);
    p.dot.setAttribute("cx", p.X(q)); p.dot.setAttribute("cy", p.Y(q));
    const strobe = stateTime(e, "strobe");
    p.ghosts.forEach((g, i) => g.setAttribute("opacity", strobe !== null && t >= strobe && tt >= z.T * (i + 1) / 9 ? 0.45 : 0));
    p.vecs.replaceChildren(); p.vecs.setAttribute("opacity", shownFrom(e, "vectors", t));
    const vk = 120 / p.vmax, ak = z.motion === "uniform" ? 0 : 70 / Math.max(z.g, Math.abs(z.a), 1e-9);
    arrowSvg(p.vecs, p.X(q), p.Y(q), p.X(q) + v[0] * vk, p.Y(q) - v[1] * vk, "#22C55E", 5);
    const acc = z.motion === "projectile" || z.motion === "free_fall" ? [0, -z.g] : z.motion === "accelerated" ? [z.a, 0] : [0, 0];
    if (ak) arrowSvg(p.vecs, p.X(q), p.Y(q), p.X(q) + acc[0] * ak, p.Y(q) - acc[1] * ak, "#EF4444", 5);
    p.graphs.setAttribute("opacity", shownFrom(e, "graphs", t));
    const [gx, gw, gh] = p.gbox, n = 30, x0 = p.pos(0), gpx = [], gpv = [];
    for (let i = 0; i <= n; i++) { const ti = tt * i / n, qi = p.pos(ti);
      gpx.push(`${gx + gw * ti / z.T} ${30 + gh - gh * Math.hypot(qi[0] - x0[0], qi[1] - x0[1]) / p.xmax}`);
      gpv.push(`${gx + gw * ti / z.T} ${60 + 2 * gh - gh * Math.hypot(...p.vel(ti)) / p.vmax}`); }
    p.gx.setAttribute("d", "M" + gpx.join(" L")); p.gv.setAttribute("d", "M" + gpv.join(" L"));
  } else if (z.kind === "COLLISION") {
    // on screen: approach at the bodies' speeds (to scale) until they touch, then their speeds after
    const go = physStart(e), u = go === null || t < go ? 0 : t - go, vs = 70 / Math.max(Math.abs(z.v1), Math.abs(z.v2), 1e-9);
    const gap = 520 - p.r[0] - p.r[1], tHit = gap / ((z.v1 - z.v2) * vs);
    const before = Math.min(u, tHit), after = Math.max(0, u - tHit);
    let x1 = z.width / 2 - 260 + z.v1 * vs * before, x2 = z.width / 2 + 260 + z.v2 * vs * before;
    x1 += z.u1 * vs * after; x2 += z.u2 * vs * after;
    p.b1.setAttribute("transform", `translate(${x1} ${p.y})`); p.b2.setAttribute("transform", `translate(${x2} ${p.y})`);
    const hit = u >= tHit;
    p.flash.setAttribute("cx", x1 + p.r[0]); p.flash.setAttribute("cy", p.y);
    p.flash.setAttribute("opacity", hit ? Math.max(0, 1 - after / 0.4) : 0);
    for (const [g, x, r, v, text] of [[p.v1, x1, p.r[0], hit ? z.u1 : z.v1, z.speeds[hit ? 2 : 0]], [p.v2, x2, p.r[1], hit ? z.u2 : z.v2, z.speeds[hit ? 3 : 1]]]) {
      g.replaceChildren();
      if (Math.abs(v) > 1e-6) arrowSvg(g, x, p.y - r - 26, x + v * vs * 1.6, p.y - r - 26, "#22C55E", 5);
      txt(g, x, p.y - r - 44, text, "middle", "note");
    }
    p.balance.setAttribute("opacity", shownFrom(e, "balance", t));
  } else if (z.kind === "OSCILLATOR") {
    const go = physStart(e), shownT = z.T * 2.2, slow = shownT / (PHYS_RUN * 2), u = go === null || t < go ? 0 : (t - go) * slow;
    const wd = Math.sqrt(Math.max(z.omega * z.omega - z.gamma * z.gamma, 1e-9)), at = tt => Math.exp(-z.gamma * tt) * Math.cos(wd * tt);
    const f = go === null || t < go ? 1 : at(u);      // released from its start position
    const v = go === null || t < go ? 0 : -Math.exp(-z.gamma * u) * (z.gamma * Math.cos(wd * u) + wd * Math.sin(wd * u)) / z.omega;
    if (z.osc === "spring") {
      const x = 360 + 160 * f, coils = 12, pts = [`64 220`];
      for (let i = 1; i <= coils; i++) pts.push(`${64 + (x - 64) * (i - 0.5) / coils} ${220 + (i % 2 ? -28 : 28)}`);
      pts.push(`${x} 220`);
      p.spring.setAttribute("d", "M" + pts.join(" L")); p.mass.setAttribute("x", x);
    } else {
      const th = z.amp * f * Math.PI / 180, L = 300, bx = 360 + L * Math.sin(th), by = 50 + L * Math.cos(th);
      p.string.setAttribute("x2", bx); p.string.setAttribute("y2", by); p.bob.setAttribute("cx", bx); p.bob.setAttribute("cy", by);
    }
    // energies: Ep ~ f², Ec ~ v² (shares of the starting energy, damped as the motion is)
    const ep = f * f, ec = v * v, H = 260;
    p.energy.setAttribute("opacity", shownFrom(e, "energy", t));
    p.ec.setAttribute("y", 400 - H * ec); p.ec.setAttribute("height", H * ec);
    p.ep.setAttribute("y", 400 - H * ep); p.ep.setAttribute("height", H * ep);
    p.graph.setAttribute("opacity", shownFrom(e, "graph", t));
    const gw = z.width - 1030, pts = [];
    for (let i = 0; i <= 80; i++) { const ti = u * i / 80; pts.push(`${1010 + gw * ti / shownT} ${250 - 110 * at(ti)}`); }
    p.curve.setAttribute("d", go === null || t < go ? "" : "M" + pts.join(" L"));
    p.period.setAttribute("opacity", shownFrom(e, "period", t));
  } else if (z.kind === "ORBIT") {
    const {a, b, c, cx, cy} = p.geo, go = physStart(e), M = go === null || t < go ? 0 : 2 * Math.PI * (t - go) / (PHYS_RUN * 1.6);
    const at = Mx => { const E = keplerAt(z.e, Mx); return [cx - c + a * Math.cos(E), cy + b * Math.sin(E)]; };
    const [x, y] = at(M), [xn, yn] = at(M + 0.01);
    p.sat.setAttribute("cx", x); p.sat.setAttribute("cy", y);
    p.name.setAttribute("x", x); p.name.setAttribute("y", y - 26);
    p.force.replaceChildren(); p.force.setAttribute("opacity", shownFrom(e, "force", t));
    const r = Math.hypot(x - cx, y - cy), pull = Math.min(160, 60 * (a * (1 - z.e)) ** 2 / (r * r) * 1.6);   // ~ 1 / r²
    arrowSvg(p.force, x, y, x + (cx - x) / r * pull, y + (cy - y) / r * pull, "#EF4444", 5);
    p.speed.replaceChildren(); p.speed.setAttribute("opacity", shownFrom(e, "speed", t));
    const vis = Math.sqrt(2 / r - 1 / a), vmax = Math.sqrt(2 / (a * (1 - z.e)) - 1 / a), len = 130 * vis / vmax;   // vis-viva
    const dx = xn - x, dy = yn - y, dl = Math.hypot(dx, dy) || 1;
    arrowSvg(p.speed, x, y, x + dx / dl * len, y + dy / dl * len, "#22C55E", 5);
    // Kepler's second law: two arcs of equal time, one near the centre, one far: equal areas
    p.areas.setAttribute("opacity", shownFrom(e, "areas", t));
    const sector = (m0, m1) => { const pts = []; for (let i = 0; i <= 24; i++) pts.push(at(m0 + (m1 - m0) * i / 24).map(v => v.toFixed(1)).join(" "));
      return `M${cx} ${cy} L${pts.join(" L")} Z`; };
    p.sweeps[0].setAttribute("d", sector(-0.35, 0.35)); p.sweeps[1].setAttribute("d", sector(Math.PI - 0.35, Math.PI + 0.35));
    p.dist.setAttribute("opacity", Math.max(shownFrom(e, "ratio", t), shownFrom(e, "areas", t)));
  }
}
function tunnelWave(centre, spread, phase) {
  // a wave packet along the tube around `centre`; beyond the wall its height is a third (what gets through)
  const pts = [];
  for (let x = Math.max(70, centre - spread); x <= Math.min(TUN_W - 70, centre + spread); x += 6) {
    const envelope = Math.exp(-(((x - centre) / (spread / 2.2)) ** 2)), side = x > TUN_WALL ? 0.33 : 1;
    pts.push(`${x.toFixed(1)},${(TUN_Y - 44 * envelope * side * Math.sin((x - phase) / 14)).toFixed(1)}`);
  }
  return pts.length > 1 ? "M" + pts.join(" L") : "";
}
function seekTunnel(e, t) {
  const z = e.data.tunnel, p = e.data.tunnelParts, spawn = e.spawn || 0;
  const given = e.states.some(s => s.at >= 0 && s.state && typeof s.state === "object");
  // the zoom: from the circuit seen whole into its dashed frame, which becomes the tube
  const zoom = z.zoom ? easeInOut(clamp((t - spawn - 0.6) / (TUN_ZOOM - 0.6), 0, 1)) : 1, k = TUN_K0 + (1 - TUN_K0) * zoom;
  p.zoom.setAttribute("transform", `translate(${TUN_W / 2} ${TUN_Y}) scale(${k}) translate(${-TUN_W / 2} ${-TUN_Y})`);
  p.ctx.setAttribute("opacity", z.zoom ? 1 - clamp((zoom - 0.55) / 0.35, 0, 1) : 0);
  p.caption.setAttribute("opacity", 1 - clamp(zoom / 0.3, 0, 1));     // gone before it grows big
  p.view.setAttribute("opacity", z.zoom ? clamp(zoom / 0.4, 0, 1) : 1);
  const bounce = given ? stateTime(e, "bounce") : null, through = given ? stateTime(e, "tunnel") : spawn + TUN_ZOOM + 0.5;
  // the run playing now: the last one started
  const runs = [["bounce", bounce], ["tunnel", through]].filter(([, a]) => a !== null && t >= a).sort((a, b) => a[1] - b[1]);
  const [kind, from] = runs.length ? runs[runs.length - 1] : [null, 0], u = t - from;
  const near = TUN_WALL - 34, far = TUN_WALL + 34;
  let x = TUN_FROM, wave = 0, note = "";
  if (kind === "bounce") {
    x = u < TUN_RUN ? TUN_FROM + (near - TUN_FROM) * easeInOut(u / TUN_RUN)
      : near - (near - TUN_FROM) * easeInOut(clamp((u - TUN_RUN) / TUN_RUN, 0, 1));
    note = "Ce qu'on attend : il rebondit sur le mur";
  } else if (kind === "tunnel") {
    if (u < TUN_RUN) x = TUN_FROM + (near - TUN_FROM) * easeInOut(u / TUN_RUN);
    else if (u < TUN_RUN + TUN_CROSS) { const q = (u - TUN_RUN) / TUN_CROSS; x = near + (far - near) * q; wave = Math.sin(Math.PI * q); }
    else x = far + (TUN_TO - far) * easeInOut(clamp((u - TUN_RUN - TUN_CROSS) / TUN_OUT, 0, 1));
    note = u < TUN_RUN ? "" : u < TUN_RUN + TUN_CROSS ? "Une onde, pas une bille : une petite partie passe le mur"
                                                    : "Effet tunnel : il passe de l'autre côté, le mur reste intact";
  }
  // near the wall the dot gives way to its wave
  p.dot.setAttribute("cx", x);
  p.dot.setAttribute("opacity", 1 - 0.85 * wave);
  p.wave.setAttribute("d", wave > 0 ? tunnelWave(x, 120 + 200 * wave, t * 90) : "");
  p.wave.setAttribute("opacity", wave);
  p.name.setAttribute("x", x);
  // the wall flashes when the dot meets it
  const hit = kind === "bounce" ? Math.max(0, 1 - Math.abs(u - TUN_RUN) / 0.3) : wave;
  p.wall.style.stroke = hit > 0 ? `color-mix(in srgb, #F59E0B ${Math.round(100 * hit)}%, var(--text))` : "";
  p.note.textContent = note;
  p.note.setAttribute("opacity", note ? clamp((u - (kind === "tunnel" ? TUN_RUN : 0)) / 0.4, 0, 1) : 0);
}
function seekTides(e, t) {
  const z = e.data.tideParts, [ex, ey] = TIDE_E, R = TIDE_R;
  const given = e.states.some(s => s.at >= 0 && s.state && typeof s.state === "object");
  const at = k => given ? stateTime(e, k) : (e.spawn || 0) + TIDE_AUTO[k];
  const on = (k, d = 0.5) => { const a = at(k); return a === null ? 0 : clamp((t - a) / d, 0, 1); };
  z.points.setAttribute("opacity", on("points"));
  const rel = on("relative");
  z.forces.setAttribute("opacity", on("forces") * (1 - 0.75 * rel));
  z.relative.setAttribute("opacity", rel);
  // the Sun: the last {"sun": ...} given so far
  const sun = e.states.filter(s => s.at >= 0 && s.at <= t && s.state && typeof s.state.sun === "string").pop();
  const mode = sun && TIDE_SHAPES[sun.state.sun] ? sun.state.sun : "none", ps = sun ? easeInOut(clamp((t - sun.at) / 1.2, 0, 1)) : 0;
  z.sun.setAttribute("opacity", sun ? ps : 0);
  if (sun) {
    const [sx, sy] = mode === "square" ? [ex + 330, 60] : [40, ey];
    z.sun.setAttribute("transform", `translate(${sx} ${sy})`);
    z.sunTide.textContent = mode === "square" ? "mortes-eaux" : mode === "aligned" ? "vives-eaux" : "";
  }
  const stretch = Math.max(easeInOut(on("stretch", 1.6)), sun ? 1 : 0);
  const [rx0, ry0] = TIDE_SHAPES.none, [rx1, ry1] = TIDE_SHAPES[mode];
  const rx = TIDE_SEA + (rx0 + (rx1 - rx0) * ps - TIDE_SEA) * stretch, ry = TIDE_SEA + (ry0 + (ry1 - ry0) * ps - TIDE_SEA) * stretch;
  z.sea.setAttribute("rx", rx.toFixed(1)); z.sea.setAttribute("ry", ry.toFixed(1));
  z.tide.setAttribute("opacity", on("stretch", 1.2));
  z.highNear.setAttribute("x", ex + rx + 10); z.highFar.setAttribute("x", ex - rx - 10);
  z.low.setAttribute("y", ey - ry - 16);
  // the Earth turning: the port starts on top (low tide), a high tide each time it faces a bulge
  const spun = at("spin");
  z.spin.setAttribute("opacity", on("spin"));
  const turn = spun === null ? -90 : -90 + 360 * Math.max(0, t - spun) / TIDE_DAY, a = turn * Math.PI / 180;
  const [px, py] = [ex + R * Math.cos(a), ey + R * Math.sin(a)];
  z.port.setAttribute("cx", px.toFixed(1)); z.port.setAttribute("cy", py.toFixed(1));
  z.portName.setAttribute("x", (ex + (R + 50) * Math.cos(a)).toFixed(1)); z.portName.setAttribute("y", (ey + (R + 50) * Math.sin(a) + 8).toFixed(1));
  const highs = turn < 0 ? 0 : Math.floor(turn / 180) + 1;
  z.count.textContent = turn >= 270 ? "En un jour : 2 marées hautes" : `Marées hautes au port : ${highs}`;
}
// LOGIC_CIRCUIT: inputs (a box showing 0 or 1, its label on the left), gates in their standard shapes
// (ET, OU, NON...: their French name under them, their value beside their output), outputs as lamps;
// laid out in Python (logic_data). A wire at 1 glows green, at 0 is grey. Each gate shows the result of
// the inputs as they were LOGIC_LAG s ago (a circuit: all at once), or, from set_state {"mode":
// "sequential"}, (k + 1) x LOGIC_STEP s ago for the k-th gate (a program: one step after the other,
// the gate at work outlined). set_state {"<input id>": 1 | 0} sets an input.
const LOGIC_STEP = 0.8, LOGIC_LAG = 0.3, GATE_W = 120, GATE_H = 90, LOGIC_ON = "#22C55E";
const gateOut = type => ({AND: 45, NAND: 45, OR: 52, NOR: 52, XOR: 52, NOT: 32}[type] + (["NAND", "NOR", "NOT"].includes(type) ? 14 : 0));
function gatePath(type, cx, cy) {
  const l = cx - GATE_W / 2, t = cy - GATE_H / 2, b = cy + GATE_H / 2;
  if (type === "AND" || type === "NAND") return `M${l} ${t} H${cx} A${GATE_H / 2} ${GATE_H / 2} 0 0 1 ${cx} ${b} H${l} Z`;
  if (type === "NOT") return `M${l} ${t} L${cx + 32} ${cy} L${l} ${b} Z`;
  return `M${l} ${t} Q${cx - 22} ${cy} ${l} ${b} Q${cx + 12} ${b} ${cx + 52} ${cy} Q${cx + 12} ${t} ${l} ${t} Z`;   // OR, NOR, XOR
}
function logicPoint(z, id, side, pin = 0, pins = 1) {   // where a wire leaves a node (side "out") or enters it ("in")
  const n = z.nodes[id];
  if (side === "out") return n.kind === "input" ? [n.x + 36, n.y] : [n.x + gateOut(n.type), n.y];
  if (n.kind === "output") return [n.x - 26, n.y];
  return [n.x - GATE_W / 2 + (n.type === "XOR" ? -4 : 0), n.y + (pins === 2 ? (pin ? 24 : -24) : 0)];
}
function buildLogic(ent) {
  const z = ent.logic, shape = el("div", "logic");
  Object.assign(shape.style, {width: `${z.width}px`, height: `${z.height}px`});
  const s = sv("svg", {width: z.width, height: z.height, viewBox: `0 0 ${z.width} ${z.height}`, overflow: "visible"});
  const parts = {wires: [], nodes: {}};
  z.wires.forEach((w, i) => {
    const [sx, sy] = logicPoint(z, w.from, "out"), [ex, ey] = logicPoint(z, w.to, "in", w.pin, w.pins);
    const mx = Math.round((sx + ex) / 2 + (w.pin - (w.pins - 1) / 2) * 14);
    const path = sv("path", {d: `M${sx} ${sy} H${mx} V${ey} H${ex}`, fill: "none", "stroke-width": 6, "stroke-linejoin": "round"}, s);
    parts.wires.push({path, from: w.from});
  });
  for (const [id, n] of Object.entries(z.nodes)) {
    const g = sv("g", {}, s), p = {g};
    if (n.kind === "input") {
      p.box = sv("rect", {x: n.x - 36, y: n.y - 24, width: 72, height: 48, rx: 10, "stroke-width": 4}, g);
      p.value = tideText(g, n.x, n.y + 11, "0");
      p.value.classList.add("logic-value");
      tideText(g, n.x - 48, n.y + 8, n.label || id, "end");
    } else if (n.kind === "gate") {
      p.body = sv("path", {d: gatePath(n.type, n.x, n.y), "stroke-width": 5, "stroke-linejoin": "round"}, g);
      if (n.type === "XOR") sv("path", {d: `M${n.x - GATE_W / 2 - 10} ${n.y - GATE_H / 2} Q${n.x - 34} ${n.y} ${n.x - GATE_W / 2 - 10} ${n.y + GATE_H / 2}`,
                                       fill: "none", "stroke-width": 5, class: "logic-ink"}, g);
      if (["NAND", "NOR", "NOT"].includes(n.type)) sv("circle", {cx: n.x + gateOut(n.type) - 7, cy: n.y, r: 7, "stroke-width": 4, class: "logic-ink logic-hole"}, g);
      tideText(g, n.x, n.y + GATE_H / 2 + 30, n.name);
      p.value = tideText(g, n.x + gateOut(n.type) + 8, n.y - 14, "0", "start");
      p.value.classList.add("logic-bit");
    } else {
      p.lamp = sv("circle", {cx: n.x, cy: n.y, r: 26, "stroke-width": 4}, g);
      tideText(g, n.x, n.y + 56, n.label || id);
    }
    parts.nodes[id] = p;
  }
  z.note = tideText(s, 0, 4, "", "start", "tide-note");
  if (z.program) {                 // the program: one line per gate, a pointer on the line at work
    const pr = z.program, g = sv("g", {class: "logic-program"}, s);
    tideText(g, pr.x, pr.top - 50, "Programme : une ligne à la fois", "start", "tide-note");
    parts.pointer = sv("rect", {x: pr.x - 14, y: pr.top - 34, width: pr.width - 40, height: pr.line - 6, rx: 8, opacity: 0,
                                fill: "color-mix(in srgb, var(--accent) 22%, transparent)", stroke: "var(--accent)", "stroke-width": 2}, g);
    parts.lines = pr.lines.map((text, i) => {
      tideText(g, pr.x, pr.top + i * pr.line, String(i + 1), "start", "tide-note");
      return tideText(g, pr.x + 40, pr.top + i * pr.line, text, "start");       // LLM labels: textContent only
    });
  }
  shape.append(s);
  ent.logicParts = parts;
  return shape;
}
function seekLogic(e, t) {
  const z = e.data.logic, parts = e.data.logicParts, given = e.states.filter(s => s.at >= 0 && s.state && typeof s.state === "object");
  const input = (id, at) => { let v = z.values[id]; for (const s of given) if (s.at <= at && id in s.state) v = s.state[id] ? 1 : 0; return v; };
  const mode = (given.filter(s => s.at <= t && (s.state.mode === "sequential" || s.state.mode === "parallel")).pop() || {state: {mode: "parallel"}}).state.mode;
  const compute = at => {           // every value with the inputs as they were at `at`
    const v = {};
    for (const id of Object.keys(z.values)) v[id] = input(id, at);
    for (const g of z.gates) {
      const [a, b] = z.feeds[g].map(f => v[f]), type = z.nodes[g].type;
      v[g] = type === "AND" ? a & b : type === "OR" ? a | b : type === "XOR" ? a ^ b : type === "NAND" ? 1 - (a & b)
           : type === "NOR" ? 1 - (a | b) : 1 - a;
    }
    return v;
  };
  const shown = {};
  for (const id of Object.keys(z.values)) shown[id] = input(id, t);
  z.gates.forEach((g, k) => { shown[g] = compute(t - (mode === "sequential" ? (k + 1) * LOGIC_STEP : LOGIC_LAG))[g]; });
  for (const [o, f] of Object.entries(z.outputs)) shown[o] = shown[f];
  // the step at work: since the last input change, one gate per LOGIC_STEP
  const change = Math.max(-Infinity, ...given.filter(s => s.at <= t && Object.keys(s.state).some(k => k in z.values)).map(s => s.at));
  const working = mode === "sequential" ? Math.floor((t - change) / LOGIC_STEP) : -1;
  for (const w of parts.wires) w.path.style.stroke = shown[w.from] ? LOGIC_ON : "color-mix(in srgb, var(--muted) 70%, transparent)";
  for (const [id, n] of Object.entries(z.nodes)) {
    const p = parts.nodes[id], on = shown[id];
    if (n.kind === "input") {
      p.value.textContent = String(on);
      p.box.style.fill = on ? `color-mix(in srgb, ${LOGIC_ON} 25%, var(--card))` : "var(--card)";
      p.box.style.stroke = on ? LOGIC_ON : "var(--ink)";
    } else if (n.kind === "gate") {
      p.value.textContent = String(on);
      p.value.style.fill = on ? LOGIC_ON : "var(--muted)";
      p.body.style.fill = "var(--card)";
      p.body.style.stroke = z.gates.indexOf(id) === working ? "var(--accent)" : "var(--ink)";
      p.body.style.strokeWidth = z.gates.indexOf(id) === working ? 8 : 5;
    } else {
      p.lamp.style.fill = on ? "#FDE047" : "var(--card)";
      p.lamp.style.stroke = on ? "#F59E0B" : "var(--ink)";
      p.lamp.style.filter = on ? "drop-shadow(0 0 18px rgba(251, 191, 36, .9))" : "none";
    }
  }
  if (parts.pointer) {             // the line at work: gate k's, then the outputs' (one step for them all)
    const line = working < 0 || !Number.isFinite(change) ? -1 : working < z.gates.length ? working
               : working === z.gates.length ? z.gates.length : -1;
    parts.pointer.setAttribute("opacity", line >= 0 ? 1 : 0);
    parts.pointer.setAttribute("height", (line === z.gates.length ? parts.lines.length - z.gates.length : 1) * z.program.line - 6);
    if (line >= 0) parts.pointer.setAttribute("y", z.program.top - 34 + line * z.program.line);
    parts.lines.forEach((l, i) => { l.style.opacity = mode === "sequential" ? 1 : 0.45; });
  }
  z.note.textContent = given.some(s => s.state.mode) ? (mode === "sequential" ? "Pas à pas : une porte après l'autre" : "Circuit : toutes les portes en même temps") : "";
}
// FPGA_GRID: a grid of logic blocks, routing channels between them. {"configure": true}: the bitstream
// slides in and "design" fills the blocks one by one (FPGA_PLACE s apart), the routing between
// consecutive blocks lit; functions beyond the blocks are listed in red, "ressources insuffisantes".
// {"run": true}: signals run along every lit route at once, the blocks beating together.
// {"reconfigure": true}: the blocks empty, then "design2" fills them the same way.
// {"zoom": "ET"} (a function's name, or a block's number from 0): the view zooms on that block and
// shows what is inside: the gate drawn for ET, OU, NON..., a small table (LUT) whose bits come from
// the bitstream for any other function; {"zoom": false} zooms back out. {"wire": true}: the
// interconnect: a switch at each crossing of the channels closes, one route after the other, and
// the signal runs along the routes (given "wire", the routes light then, not as the blocks fill).
const FPGA_PLACE = 0.6, FPGA_FLY = 0.45, FPGA_X0 = 170, FPGA_Y0 = 40, FPGA_BLOCK = 110, FPGA_ZOOM = 3.2, FPGA_ZOOM_SEC = 1.1;
const FPGA_SWITCH = 0.35;           // s between two routes' switches closing
const FPGA_GATES = {"et": "AND", "ou": "OR", "non": "NOT", "ou exclusif": "XOR", "non-et": "NAND", "non-ou": "NOR"};
function fpgaGate(name) { return FPGA_GATES[String(name || "").toLowerCase().replace(/^porte\s+/, "").trim()] || null; }
function fpgaInside(g, name) {
  // what a block holds, drawn small in its centre (seen once zoomed): a gate, or a LUT and its bits
  g.replaceChildren();
  const type = fpgaGate(name), ink = {fill: "none", stroke: "var(--text)", "stroke-width": 6, "stroke-linecap": "round"};
  if (type) {
    const out = gateOut(type);
    for (const y of type === "NOT" ? [0] : [-24, 24]) sv("line", {x1: -GATE_W / 2 - 50, y1: y, x2: -GATE_W / 2, y2: y, ...ink}, g);
    sv("line", {x1: out, y1: 0, x2: out + 50, y2: 0, ...ink}, g);
    if (type === "XOR") sv("path", {d: `M${-GATE_W / 2 - 10} ${-GATE_H / 2} Q-34 0 ${-GATE_W / 2 - 10} ${GATE_H / 2}`, ...ink}, g);
    sv("path", {d: gatePath(type, 0, 0), ...ink, fill: "var(--card)"}, g);
    if (["NAND", "NOR", "NOT"].includes(type)) sv("circle", {cx: out - 7, cy: 0, r: 7, ...ink, fill: "var(--card)"}, g);
    tideText(g, 0, 105, `Porte ${name}`).style.fontSize = "38px";
  } else {
    const bits = ["0", "1", "1", "0"];
    ["00", "01", "10", "11"].forEach((row, i) => {
      sv("rect", {x: -90, y: -78 + i * 34, width: 180, height: 34, fill: "var(--card)", stroke: "var(--muted)", "stroke-width": 3}, g);
      tideText(g, -40, -52 + i * 34, row).style.fontSize = "26px";
      tideText(g, 45, -52 + i * 34, bits[i]).style.fontSize = "26px";
    });
    tideText(g, 0, 105, "Table (LUT)").style.fontSize = "38px";
  }
}
function fpgaZoom(e, t, design, n) {
  // {block, k}: the block zoomed on (or null) and how far in, from the "zoom" values in the states
  let block = null, k = 0, prev;
  for (const s of e.states) {
    if (s.at < 0 || s.at > t || !s.state || typeof s.state !== "object") continue;
    const v = s.state.zoom;
    if (v === prev) continue;
    const zoomed = block !== null ? k : 0;
    if (v === undefined || v === false || v === null) { if (block !== null) k = zoomed * (1 - easeInOut(clamp((t - s.at) / FPGA_ZOOM_SEC, 0, 1))); }
    else {
      const name = String(v).toLowerCase(), byName = design.findIndex(d => String(d).toLowerCase() === name);
      block = typeof v === "number" ? clamp(Math.round(v), 0, n - 1) : byName >= 0 ? byName
            : Math.max(0, design.findIndex(d => String(d).toLowerCase().includes(name)));
      k = easeInOut(clamp((t - s.at) / FPGA_ZOOM_SEC, 0, 1));
    }
    prev = v;
  }
  return {block, k};
}
function fpgaSwitches(z, i) {     // the channel crossings the route into block i passes
  const [ax, ay] = fpgaCentre(z, i - 1), [bx, by] = fpgaCentre(z, i), mx = ax + z.cell / 2;
  return ay === by ? [[mx, ay]] : [[mx, ay], [bx, by - z.cell / 2]];
}
function fpgaCentre(z, i) { const c = i % z.cols, r = Math.floor(i / z.cols);
  return [FPGA_X0 + c * z.cell + z.cell / 2, FPGA_Y0 + r * z.cell + z.cell / 2]; }
function buildFpga(ent) {
  const z = ent.fpga, shape = el("div", "fpga"), n = z.cols * z.rows;
  const W = z.cols * z.cell + 300, H = z.rows * z.cell + 150;
  Object.assign(shape.style, {width: `${W}px`, height: `${H}px`});
  const svg = sv("svg", {width: W, height: H, viewBox: `0 0 ${W} ${H}`, overflow: "visible"});
  // everything zooms inside the drawing's own frame (clipped), but the red "ressources" line
  const clip = `fpga-${String(ent.id).replace(/[^\w-]/g, "_")}-clip`;
  sv("rect", {x: -120, y: -20, width: W + 120, height: H + 20}, sv("clipPath", {id: clip}, sv("defs", {}, svg)));
  const s = sv("g", {}, sv("g", {"clip-path": `url(#${clip})`}, svg));
  const chan = sv("g", {stroke: "color-mix(in srgb, var(--muted) 35%, transparent)", "stroke-width": 3, "stroke-dasharray": "6 8"}, s);
  for (let c = 0; c <= z.cols; c++) sv("line", {x1: FPGA_X0 + c * z.cell, y1: FPGA_Y0, x2: FPGA_X0 + c * z.cell, y2: FPGA_Y0 + z.rows * z.cell}, chan);
  for (let r = 0; r <= z.rows; r++) sv("line", {x1: FPGA_X0, y1: FPGA_Y0 + r * z.cell, x2: FPGA_X0 + z.cols * z.cell, y2: FPGA_Y0 + r * z.cell}, chan);
  const routes = sv("g", {}, s), parts = {blocks: [], routes: []};
  for (let i = 1; i < n; i++) {     // block i-1 to block i, along the channels: right, then down the channel, then in
    const [ax, ay] = fpgaCentre(z, i - 1), [bx, by] = fpgaCentre(z, i), mx = ax + z.cell / 2;
    const d = ay === by ? `M${ax} ${ay} H${bx}` : `M${ax} ${ay} H${mx} V${by - z.cell / 2} H${bx} V${by}`;
    parts.routes.push(sv("path", {d, fill: "none", stroke: "var(--accent)", "stroke-width": 6, "stroke-linecap": "round", opacity: 0}, routes));
  }
  parts.switches = [];
  for (let i = 1; i < n; i++) parts.switches.push(fpgaSwitches(z, i).map(([x, y]) =>
    sv("circle", {cx: x, cy: y, r: 11, fill: "var(--card)", stroke: "var(--accent)", "stroke-width": 4, opacity: 0}, s)));
  for (let i = 0; i < n; i++) {
    const [cx, cy] = fpgaCentre(z, i), g = sv("g", {}, s);
    const rect = sv("rect", {x: cx - FPGA_BLOCK / 2, y: cy - FPGA_BLOCK / 2, width: FPGA_BLOCK, height: FPGA_BLOCK, rx: 12, "stroke-width": 4}, g);
    const label = tideText(g, cx, cy + 9, ""), label2 = tideText(g, cx, cy + 24, "");
    const inside = sv("g", {transform: `translate(${cx} ${cy - 6}) scale(0.28)`, opacity: 0}, g);
    parts.blocks.push({rect, label, label2, cy, cx, inside, holds: null});
  }
  tideText(s, FPGA_X0 + z.cols * z.cell / 2, FPGA_Y0 + z.rows * z.cell + 34, "Blocs logiques et routage", "middle", "tide-note");
  // the bitstream: a file (a page, its corner folded) of bits, left of the grid
  parts.bits = sv("g", {opacity: 0}, s);
  sv("path", {d: "M-44 -60 H24 L44 -40 V60 H-44 Z", fill: "var(--card)", stroke: "var(--accent)", "stroke-width": 3}, parts.bits);
  sv("path", {d: "M24 -60 V-40 H44", fill: "none", stroke: "var(--accent)", "stroke-width": 3}, parts.bits);
  ["1011", "0010", "1101"].forEach((bits, i) => tideText(parts.bits, 0, -14 + i * 28, bits, "middle", "fpga-file"));
  tideText(parts.bits, 0, -74, "Bitstream", "middle", "tide-note");
  // a packet of the bitstream's bits flies to each block as it gets its function
  parts.packet = tideText(s, 0, 0, "", "middle", "fpga-bits");
  parts.wireNote = tideText(svg, FPGA_X0 + z.cols * z.cell / 2, FPGA_Y0 + z.rows * z.cell + 84, "", "middle", "tide-note");
  parts.world = s;
  parts.size = [W, H];
  parts.over = tideText(svg, FPGA_X0, FPGA_Y0 + z.rows * z.cell + 84, "", "start");
  parts.over.style.fill = "#EF4444";
  shape.append(svg);
  ent.fpgaParts = parts;
  return shape;
}
function fpgaLines(text) {
  // a long name with a space ("Portes logiques") on two lines, cut at the space nearest the middle
  const spaces = [...text.matchAll(/ /g)].map(m => m.index);
  if (text.length <= 9 || !spaces.length) return [text, ""];
  const cut = spaces.reduce((a, b) => Math.abs(b - text.length / 2) < Math.abs(a - text.length / 2) ? b : a);
  return [text.slice(0, cut), text.slice(cut + 1)];
}
function seekFpga(e, t) {
  const z = e.data.fpga, p = e.data.fpgaParts, n = z.cols * z.rows;
  const configured = stateTime(e, "configure"), reconfigured = stateTime(e, "reconfigure"), running = stateTime(e, "run");
  // the phase now: the first design from "configure", the second from "reconfigure" (after a clear)
  const phase = reconfigured !== null && t >= reconfigured && z.design2.length ? {at: reconfigured + 0.6, design: z.design2, clear: reconfigured}
              : configured !== null && t >= configured ? {at: configured, design: z.design} : null;
  const placedAt = i => phase ? phase.at + 0.9 + i * FPGA_PLACE : Infinity;
  const zoom = fpgaZoom(e, t, phase ? phase.design : [], n);
  const clearing = phase && phase.clear !== undefined ? 1 - clamp((t - phase.clear) / 0.5, 0, 1) : 0;
  p.blocks.forEach((b, i) => {
    const k = phase && i < phase.design.length ? clamp((t - placedAt(i)) / 0.3, 0, 1) : 0;
    const beat = running !== null && t >= running && k ? 0.5 + 0.5 * Math.sin((t - running) * 2 * Math.PI) : 0;
    b.rect.style.fill = k ? `color-mix(in srgb, var(--accent) ${Math.round(18 + 22 * k + 25 * beat)}%, var(--card))`
                          : clearing ? `color-mix(in srgb, var(--accent) ${Math.round(40 * clearing)}%, var(--card))` : "var(--card)";
    b.rect.style.stroke = k ? "var(--accent)" : "var(--ink)";
    const [line1, line2] = k ? fpgaLines(phase.design[i]) : ["", ""], longest = Math.max(line1.length, line2.length);
    b.label.textContent = line1;      // LLM text: textContent only
    b.label2.textContent = line2;
    b.label.setAttribute("y", line2 ? b.cy - 6 : b.cy + 9);
    const name = k ? phase.design[i] : null, seen = zoom.block === i ? zoom.k : 0;
    if (b.holds !== name) { fpgaInside(b.inside, name); b.holds = name; }     // LLM text: textContent only
    b.inside.setAttribute("opacity", clamp((seen - 0.5) / 0.4, 0, 1));
    for (const l of [b.label, b.label2]) {
      l.style.fontSize = longest > 7 ? `${Math.max(15, Math.round(24 * 7 / longest))}px` : "";
      l.style.opacity = k * (1 - clamp(seen / 0.5, 0, 1));
    }
  });
  const wired = stateTime(e, "wire"), closeAt = i => wired + 0.5 + i * FPGA_SWITCH;
  p.routes.forEach((r, i) => {     // the route into block i + 1, once both ends are placed (given "wire": once its switches close)
    const used = phase && i + 1 < Math.min(phase.design.length, n);
    const lit = !used ? 0 : wired === null ? clamp((t - placedAt(i + 1)) / 0.3, 0, 1)
              : Math.min(clamp((t - closeAt(i)) / 0.3, 0, 1), clamp((t - placedAt(i + 1)) / 0.3, 0, 1));
    r.setAttribute("opacity", lit);
    p.switches[i].forEach(c => {
      c.setAttribute("opacity", used && wired !== null && t >= wired ? clamp((t - wired) / 0.4, 0, 1) : 0);
      c.style.fill = used && wired !== null && t >= closeAt(i) ? "#10B981" : "var(--card)";
    });
    const flowing = (running !== null && t >= running) || (wired !== null && t >= closeAt(i) + 0.3);
    if (flowing && lit) { r.setAttribute("stroke-dasharray", "14 12"); r.setAttribute("stroke-dashoffset", String(-t * 90)); }
    else r.removeAttribute("stroke-dasharray");
  });
  const slide = phase ? clamp((t - (phase.clear !== undefined ? phase.clear + 0.6 : phase.at)) / 0.9, 0, 1) : 0;
  const last = phase ? placedAt(Math.min(phase.design.length, n) - 1) : 0;
  p.bits.setAttribute("opacity", phase ? Math.max(0, 1 - Math.max(0, t - last - 1) / 0.6) : 0);
  p.bits.setAttribute("transform", `translate(${40 + 50 * slide} ${FPGA_Y0 + z.cell / 2})`);
  // the packet on its way to the block being configured (FPGA_FLY s before it gets its function)
  const flying = phase ? p.blocks.findIndex((b, i) => i < Math.min(phase.design.length, n) && t >= placedAt(i) - FPGA_FLY && t < placedAt(i)) : -1;
  if (flying >= 0) {
    const q = easeInOut((t - placedAt(flying) + FPGA_FLY) / FPGA_FLY), [bx, by] = fpgaCentre(z, flying), [sx, sy] = [134, FPGA_Y0 + z.cell / 2 + 8];
    p.packet.textContent = ["1011", "0110", "1101", "0010", "1110", "0101"][flying % 6];
    p.packet.setAttribute("x", sx + (bx - sx) * q);
    p.packet.setAttribute("y", sy + (by + 8 - sy) * q);
    p.packet.setAttribute("opacity", 1);
  } else p.packet.setAttribute("opacity", 0);
  const configuring = phase && t < placedAt(Math.min(phase.design.length, n) - 1) + 2;
  p.wireNote.textContent = wired !== null && t >= wired ? "Interconnexions : des interrupteurs programmables relient les blocs"
                         : configuring ? "Le bitstream : le fichier qui dit à chaque bloc quelle fonction faire" : "";
  p.over.setAttribute("y", FPGA_Y0 + z.rows * z.cell + (p.wireNote.textContent ? 110 : 84));
  // the zoom on one block: its centre to the middle, FPGA_ZOOM times bigger
  const [W, H] = p.size;
  if (zoom.block !== null && zoom.k > 0) {
    const [cx, cy] = fpgaCentre(z, zoom.block), kk = 1 + (FPGA_ZOOM - 1) * zoom.k;
    const tx = cx + (W / 2 - cx) * zoom.k, ty = cy + (H / 2 - 30 - cy) * zoom.k;
    p.world.setAttribute("transform", `translate(${tx} ${ty}) scale(${kk}) translate(${-cx} ${-cy})`);
  } else p.world.removeAttribute("transform");
  const extra = phase ? phase.design.slice(n) : [];
  p.over.textContent = extra.length && t >= placedAt(n - 1) + 0.4 ? `Ressources insuffisantes : ${extra.join(", ")} sans bloc` : "";
}
// POPULATION: "total" dots in a grid, each standing for "per" people; the groups' dots first, in order,
// the others grey. A group is coloured in, dot after dot (POP_SHOW), at its set_state {"show": id},
// or at the pop if never shown; its key in the legend with it. set_state {"focus": [ids]} dims every
// other dot (and key), {"focus": []} brings them back.
const POP_W = 700, POP_GRID_H = 380, POP_SHOW = 0.9, POP_DIM = 0.12;
const POP_REST = "color-mix(in srgb, var(--muted) 30%, transparent)";
function buildPopulation(ent) {
  const z = ent.population, shape = el("div", "population"), n = z.total;
  const cols = Math.ceil(Math.sqrt(n * POP_W / POP_GRID_H)), rows = Math.ceil(n / cols);
  const cell = Math.min(POP_W / cols, POP_GRID_H / rows), x0 = (POP_W - cols * cell) / 2;
  const svg = sv("svg", {width: POP_W, height: rows * cell, viewBox: `0 0 ${POP_W} ${rows * cell}`, class: "pop-grid"});
  const keys = [...z.groups, ...(z.rest ? [z.rest] : [])];
  for (const g of z.groups) if (!/^#[0-9A-Fa-f]{6}$/.test(g.color)) g.color = "#DC2626";   // a "#RRGGBB" only
  const owner = z.groups.flatMap(g => Array.from({length: g.count}, (_, k) => [g, k]));
  ent.popDots = Array.from({length: n}, (_, i) => {
    const [g, k] = owner[i] || [z.rest, 0];
    const dot = sv("circle", {cx: x0 + (i % cols + 0.5) * cell, cy: (Math.floor(i / cols) + 0.5) * cell, r: cell * 0.36}, svg);
    dot.style.fill = POP_REST;
    return {dot, group: g, k};
  });
  const legend = el("div", "pop-legend");
  ent.popKeys = keys.map(g => {
    const key = el("div", "pop-key"), swatch = el("span", "pop-swatch");
    swatch.style.background = g.color || POP_REST;
    key.append(swatch, el("span", "", g.label ? `${g.label} : ${g.people}` : g.people));   // LLM text: textContent only
    legend.append(key);
    return {key, group: g};
  });
  shape.append(el("div", "pop-head", z.head), svg, legend);
  return shape;
}
function seekPopulation(e, t) {
  const shown = g => { if (!g || g.id === "rest") return -Infinity;
    const s = e.states.find(s => s.at >= 0 && s.state && s.state.show === g.id);
    return s ? s.at : (e.spawn || 0); };
  // the focus now, the one before it, and how far the dimming has gone from one to the other
  const focus = e.states.filter(s => s.at >= 0 && s.at <= t && s.state && Array.isArray(s.state.focus));
  const dimIn = list => g => list && list.length && !list.includes(g ? g.id : "rest") ? 1 : 0;
  const now = focus.length ? focus[focus.length - 1] : null, before = focus.length > 1 ? focus[focus.length - 2] : null;
  const p = now ? clamp((t - now.at) / 0.4, 0, 1) : 1;
  const dim = g => dimIn(before && before.state.focus)(g) * (1 - p) + dimIn(now && now.state.focus)(g) * p;
  for (const d of e.data.popDots) {
    const at = shown(d.group) + (d.group && d.group.id !== "rest" ? POP_SHOW * d.k / d.group.count : 0);
    d.dot.style.fill = d.group && d.group.color && t >= at ? d.group.color : POP_REST;
    d.dot.style.opacity = 1 - (1 - POP_DIM) * dim(d.group);
  }
  for (const k of e.data.popKeys)
    k.key.style.opacity = (t >= shown(k.group) ? 1 : 0) * (1 - (1 - POP_DIM) * dim(k.group));
}
// SEESAW: a beam on a pivot, a load on each end ("left", "right": a label and a weight; a "value" at
// each end makes the beam a scale from one value to the other). Each load drops onto its end (set_state
// {"left": true} / {"right": true}; a side never set is there from the start) and the beam tips
// towards the heavier side on a damped spring (it overshoots, then settles). set_state
// {"balanced": true}: the pivot slides under the beam until the loads balance; it then stands at
// the weighted mean of the two values, shown under it. All worked out from t (seekSeesaw).
const SEESAW_W = 1100, SEESAW_BEAM = 820, SEESAW_PIVOT_Y = 330, SEESAW_TILT = 15, LOAD_INSET = 120, LOAD_FALL = 0.5;
function buildSeesaw(ent) {
  const shape = el("div", "seesaw"), z = ent.seesaw;
  const base = el("div", "base"), pivot = el("div", "pivot"), beam = el("div", "beam");
  Object.assign(base.style, {left: `${SEESAW_W / 2 - 160}px`, width: "320px", top: `${SEESAW_PIVOT_Y + 96}px`});
  Object.assign(pivot.style, {left: `${SEESAW_W / 2 - 48}px`, top: `${SEESAW_PIVOT_Y}px`});
  beam.style.width = `${SEESAW_BEAM}px`;
  shape.append(base, beam, pivot);
  const wmax = Math.max(z.left.weight, z.right.weight);
  const side = s => {
    const load = el("div", "load"); load.append(el("b", "", frenchNumber(s.weight, decimalsOf(s.weight))), el("span", "", s.label || ""));
    load.style.minHeight = `${Math.round(80 + 70 * Math.sqrt(s.weight / wmax))}px`;   // heavier, taller
    const end = el("div", "end-value", s.value === undefined ? "" : frenchNumber(s.value, decimalsOf(s.value)));
    shape.append(load, end);
    return {load, end, weight: s.weight, value: s.value};
  };
  const mean = el("div", "mean"); shape.append(mean);
  Object.assign(ent, {seesawParts: {beam, pivot, base, left: side(z.left), right: side(z.right), mean}});
  return shape;
}
function stateTime(e, key) {        // when a set_state first made `key` true, else null
  const s = e.states.find(s => s.at >= 0 && s.state && typeof s.state === "object" && s.state[key] === true);
  return s ? s.at : null;
}
const CURVE_DRAW = 2.2;             // s: a curve draws itself (as a pen would, at the voice's pace)
const easeOutElastic = p => p <= 0 ? 0 : p >= 1 ? 1 : Math.pow(2, -10 * p) * Math.sin((p * 10 - 0.75) * (2 * Math.PI / 3)) + 1;
function seekSeesaw(e, t) {
  const z = e.data.seesawParts;
  const drop = k => stateTime(e, k) ?? e.spawn + 0.3;   // when each load starts falling
  const landed = (k, at) => drop(k) !== null && at >= drop(k) + LOAD_FALL;
  const balance = stateTime(e, "balanced"), wl = z.left.weight, wr = z.right.weight;
  const share = wr / (wl + wr);        // where the pivot balances the loads, from the left end (0 to 1)
  const pivotAt = at => balance === null ? 0.5 : 0.5 + (share - 0.5) * easeInOut(progress(at, balance, 1.6));
  const target = at => {               // the beam's resting angle (degrees, clockwise) for the loads and pivot at `at`
    const l = landed("left", at) ? wl : 0, r = landed("right", at) ? wr : 0, p = pivotAt(at);
    const left = l * p, right = r * (1 - p);
    return left + right > 0 ? SEESAW_TILT * Math.max(-1, Math.min(1, (right - left) / (left + right))) : 0;
  };
  let angle = 0, speed = 0;             // a damped spring towards the target, stepped from 0 to t
  for (let at = 0, dt = 1 / 120; at < t; at += dt) {
    speed += (-55 * (angle - target(at)) - 6 * speed) * dt;
    angle += speed * dt;
  }
  const p = pivotAt(t), a = angle * Math.PI / 180, cx = SEESAW_W / 2 + (p - 0.5) * SEESAW_BEAM, cy = SEESAW_PIVOT_Y;
  z.pivot.style.left = `${cx - 48}px`; z.base.style.left = `${cx - 160}px`;
  const along = d => [cx + d * Math.cos(a), cy + d * Math.sin(a)];   // a point of the beam, d px from the pivot
  const [lx, ly] = along(-p * SEESAW_BEAM);
  Object.assign(z.beam.style, {left: `${lx}px`, top: `${ly - 8}px`, transform: `rotate(${angle}deg)`});
  for (const [k, part, d] of [["left", z.left, -p * SEESAW_BEAM + LOAD_INSET], ["right", z.right, (1 - p) * SEESAW_BEAM - LOAD_INSET]]) {
    const [x, y] = along(d), h = part.load.offsetHeight, start = drop(k);
    const fall = start === null ? 0 : progress(t, start, LOAD_FALL);
    const lift = (1 - fall * fall) * 300;   // falling: faster and faster
    Object.assign(part.load.style, {left: `${x - 105}px`, top: `${y - 8 - h - lift}px`, opacity: start !== null && t >= start ? 1 : 0});
    const [ex, ey] = along(k === "left" ? -p * SEESAW_BEAM : (1 - p) * SEESAW_BEAM);
    Object.assign(part.end.style, {left: `${ex}px`, top: `${ey + 22}px`});
  }
  const m = z.left.value !== undefined && z.right.value !== undefined && balance !== null;
  const shown = m ? easeInOut(progress(t, balance + 1.4, 0.5)) : 0;
  if (m) {
    const value = z.left.value + share * (z.right.value - z.left.value);
    z.mean.textContent = `${frenchNumber(value, 2)}${e.data.seesaw.unit ? " " + e.data.seesaw.unit : ""}`;
  }
  Object.assign(z.mean.style, {left: `${cx}px`, top: `${cy + 112}px`, opacity: shown});
}
// A vector given a "value" is drawn to scale (Python: length from the largest value of its unit) and
// follows its set_value steps: it shrinks or grows before the eyes, with an elastic overshoot.
function vectorShare(e, t) {
  const vec = e.data.vector;
  let shown = vec.value, from = shown, at = null;
  for (const c of e.values) { if (c.at > t) break; from = shown; shown = c.value; at = c.at; }
  const value = at === null ? shown : from + (shown - from) * easeOutElastic(progress(t, at, 1.2));
  return Math.max(VECTOR_MIN_PX / Math.max(e.vector.length, 1), Math.abs(value) / vec.value_max);
}
const VECTOR_MIN_PX = 36;
// "floating": a thing that loses its weight rises slowly and drifts up and down (what rides on it and
// the vectors starting on it go along).
function floatOffset(e, t) {
  const at = stateTime(e, "floating");
  if (at === null || t < at) return 0;
  return 100 * easeInOut(progress(t, at, 3)) + 12 * Math.sin(1.7 * (t - at)) * Math.min(1, (t - at) / 1.5);
}
// Schematic parts: standard symbols (IEC, as in French schools), drawn in SVG at their size in
// app/layout_solver.py SHAPES, their ports in PORTS. States: LED {"on"} lit; HEATER {"on"} red, heat
// rising; OPAMP {"high"} its output at the high level; MOSFET {"on"} conducting; THERMISTOR {"hot"}.
const INK = {fill: "none", stroke: "var(--ink)", "stroke-width": 4, "stroke-linecap": "round", "stroke-linejoin": "round"};
const PART_SYMBOLS = {
  SUPPLY_RAIL: [70, 50, (g, p) => {         // the supply: a bar on a lead, its voltage over it
    sv("path", {d: "M35 50 V18 M14 18 H56", ...INK}, g);
    tideText(g, 35, 8, p.label, "middle", "part-mark"); }],
  RESISTOR: [140, 44, (g, p) => {
    sv("path", {d: "M0 22 H30 M110 22 H140", ...INK}, g);
    p.body = sv("rect", {x: 30, y: 10, width: 80, height: 24, ...INK}, g); }],
  POTENTIOMETER: [140, 80, (g, p) => {
    sv("path", {d: "M0 20 H30 M110 20 H140 M70 80 V40", ...INK}, g);
    sv("path", {d: "M62 46 L70 34 L78 46 Z", ...INK, fill: "var(--ink)"}, g);
    p.body = sv("rect", {x: 30, y: 8, width: 80, height: 24, ...INK}, g); }],
  THERMISTOR: [140, 64, (g, p) => {
    sv("path", {d: "M0 28 H30 M110 28 H140", ...INK}, g);
    p.body = sv("rect", {x: 30, y: 16, width: 80, height: 24, ...INK}, g);
    sv("path", {d: "M22 54 H36 L104 4", ...INK}, g);
    tideText(g, 120, 60, "−θ", "middle", "part-mark"); }],
  OPAMP: [170, 160, (g, p) => {
    p.body = sv("path", {d: "M20 10 L160 80 L20 150 Z", ...INK, fill: "var(--card)"}, g);
    sv("path", {d: "M0 48 H20 M0 112 H20 M80 0 V40 M80 120 V160", ...INK}, g);
    p.out = sv("path", {d: "M160 80 H170", ...INK}, g);
    tideText(g, 36, 57, "−", "middle", "part-mark"); tideText(g, 36, 121, "+", "middle", "part-mark");
    tideText(g, 80, 88, "AOP", "middle", "part-mark"); }],
  MOSFET: [120, 140, (g, p) => {
    sv("path", {d: "M0 90 H40 M40 40 V110 M52 46 H90 V0 M52 104 H90 V140 M52 75 H90 V104", ...INK}, g);
    p.channel = [36, 64, 94].map(y => sv("path", {d: `M52 ${y} V${y + 20}`, ...INK}, g));
    sv("path", {d: "M58 75 L70 68 L70 82 Z", ...INK, fill: "var(--ink)"}, g); }],
  DIODE: [120, 50, (g, p) => {
    sv("path", {d: "M0 25 H40 M74 25 H120 M74 8 V42", ...INK}, g);
    p.body = sv("path", {d: "M40 8 L74 25 L40 42 Z", ...INK, fill: "var(--ink)"}, g); }],
  LED: [120, 70, (g, p) => {
    sv("path", {d: "M0 40 H40 M74 40 H120 M74 23 V57", ...INK}, g);
    p.body = sv("path", {d: "M40 23 L74 40 L40 57 Z", ...INK, fill: "var(--card)"}, g);
    for (const x of [62, 78]) {
      sv("path", {d: `M${x} 18 L${x + 14} 4`, ...INK, "stroke-width": 3}, g);
      sv("path", {d: `M${x + 16} 2 L${x + 6} 4 L${x + 14} 12 Z`, ...INK, "stroke-width": 2, fill: "var(--ink)"}, g); }
  }],
  HEATER: [150, 96, (g, p) => {
    sv("path", {d: "M0 65 H30 M120 65 H150", ...INK}, g);
    p.body = sv("rect", {x: 30, y: 50, width: 90, height: 30, ...INK}, g);
    for (let x = 42; x < 120; x += 14) sv("path", {d: `M${x} 78 L${x + 10} 52`, ...INK, "stroke-width": 2}, g);
    p.heat = sv("g", {opacity: 0}, g);
    for (const x of [50, 75, 100]) sv("path", {d: `M${x} 44 q-8 -7 0 -14 q8 -7 0 -14 q-8 -7 0 -14`, fill: "none", stroke: "#F97316",
                                                "stroke-width": 4, "stroke-linecap": "round"}, p.heat);
  }],
};
function buildPart(ent) {
  const [w, h, draw] = PART_SYMBOLS[ent.type], shape = el("div", "part");
  Object.assign(shape.style, {width: `${w}px`, height: `${h}px`});
  const svg = sv("svg", {width: w, height: h, viewBox: `0 0 ${w} ${h}`, overflow: "visible"});
  ent.partParts = {label: ent.rail || ""};      // a supply's voltage (LLM text: textContent only)
  draw(svg, ent.partParts);
  shape.append(svg);
  return shape;
}
function seekPart(e, t) {
  const p = e.data.partParts, s = stateAt(e, t), k = s ? easeInOut(progress(t, s.at, 0.4)) : 0, type = e.data.type;
  const on = key => is(s, key) ? k : 0;      // lit as its state says, fading in over 0.4 s
  if (type === "LED") {
    const v = on("on");
    p.body.style.fill = v ? `color-mix(in srgb, #EF4444 ${Math.round(100 * v)}%, var(--card))` : "var(--card)";
    p.body.style.filter = v ? `drop-shadow(0 0 ${Math.round(16 * v)}px rgba(239, 68, 68, .95))` : "none";
  } else if (type === "HEATER") {
    const v = on("on");
    p.body.style.fill = v ? `color-mix(in srgb, #EF4444 ${Math.round(55 * v)}%, transparent)` : "none";
    p.heat.setAttribute("opacity", v);
    p.heat.setAttribute("transform", `translate(0 ${-((t * 18) % 14)})`);
  } else if (type === "OPAMP") {
    const v = on("high");
    p.body.style.fill = v ? `color-mix(in srgb, #22C55E ${Math.round(22 * v)}%, var(--card))` : "var(--card)";
    p.out.style.stroke = v ? "#22C55E" : "";
  } else if (type === "MOSFET") {
    const v = on("on");
    p.channel.forEach(c => { c.style.stroke = v ? "#22C55E" : ""; });
  } else if (type === "THERMISTOR") {
    const v = on("hot");
    p.body.style.fill = v ? `color-mix(in srgb, #F97316 ${Math.round(45 * v)}%, transparent)` : "none";
  }
}
function buildLamp(shape) {                 // a bulb with a filament and a radial glow behind it
  const s = sv("svg", {viewBox: "-125 -125 250 250"});
  const halo = sv("circle", {r: 122, fill: "url(#lampGlow)", opacity: 0}, s);
  const bulb = sv("circle", {r: 52, "stroke-width": 4}, s);
  bulb.style.fill = "var(--bulb-off)"; bulb.style.stroke = "var(--ink)";
  const filament = sv("path", {d: "M -20 12 L -10 -10 L 0 12 L 10 -10 L 20 12", fill: "none", "stroke-width": 4,
                               "stroke-linejoin": "round", "stroke-linecap": "round"}, s);
  filament.style.stroke = "var(--ink)";
  shape.append(s);
  return {halo, bulb};
}

// ---- zones: the main diagram on the left; an instrument column on the right (instruments and status
// badges, then one telemetry card per counter, 16 px apart) when the scene has any. Nothing in the column moves or
// overlaps, and components and wires stay out of it.
const hasCounter = D.events.some(ev => ev.action === "set_value" && D.entities.some(e => e.id === ev.target && e.type !== "AMMETER"));
const SIDE = D.entities.some(e => e.instrument || (e.annotation && e.annotation.status)) || hasCounter;
// Layout template (the page constant sets it on #stage, from agent004's "layout_template"):
//   circuit             diagram on the left, the instrument column on the right (as above);
//   comparison          two panels side by side, A | B: each entity stays in the panel its position is in;
//   analogy_fullscreen  one large visual across the frame, annotations over it.
// Outside "circuit" there is no column: status badges and counters make a row under the titles,
// and the diagram uses the full width below it (CONTENT_TOP, set once the fonts are in).
const LAYOUT = stage.dataset.layout || "circuit", ROW = LAYOUT !== "circuit";
const MAIN_RIGHT = SIDE && !ROW ? Math.round(D.width * 0.75) : D.width;
const PANEL_HEAD = 56;
const PANELS = LAYOUT === "comparison" ? [[40, D.width / 2 - 20], [D.width / 2 + 20, D.width - 40]] : null;
let CONTENT_TOP = 0;               // stays 0 for "circuit": its limits are the titles' only
const SUBS_SPACE = Array.isArray(D.subtitles) && D.subtitles.length ? 96 : 0;   // the subtitles' room at the bottom
let FLOOR = D.height - SUBS_SPACE;   // the lowest the diagram goes: above the subtitles and the vector legend, when it is at the bottom
const below = top => Math.max(top, CONTENT_TOP);
const side = el("div");
side.id = "side";
if (SIDE && ROW) {
  Object.assign(side.style, {left: "40px", top: `${D.subtitle ? 210 : 160}px`, width: `${D.width - 80}px`});
  stage.append(side);
} else if (SIDE) {
  Object.assign(side.style, {left: `${MAIN_RIGHT + 24}px`, top: `${D.subtitle ? 210 : 160}px`, width: `${D.width - MAIN_RIGHT - 48}px`});
  stage.append(side);
}
if (LAYOUT === "analogy_fullscreen") {   // one large visual: positions spread 1.25 x from the centre
  for (const ent of D.entities) ent.xy = [D.width / 2 + (ent.xy[0] - D.width / 2) * 1.25, D.height / 2 + 40 + (ent.xy[1] - D.height / 2 - 40) * 1.25];
}

// ---- build the scene once; seek(t) only sets styles
const GLOW = (STYLE.effects || []).includes("glow"), AREA = (STYLE.effects || []).includes("area");
if (GLOW) stage.classList.add("fx-glow");
// The background, built once (the same stars and traces every time: a seeded generator) and moved by
// seekBackground(t): glows drifting on slow ellipses, a grid sliding, star layers at three speeds,
// pulses running along the circuit traces.
const BG = document.getElementById("bg"), BGK = STYLE.background, SEED = D.scene_number || 1;
const rand = (() => { let x = (SEED * 7919) % 233280; return () => (x = (x * 9301 + 49297) % 233280) / 233280; })();
const GLOWS = [], LAYERS = [], PULSES = [];
function addGlow(color, cx, cy, opacity) {
  const g = el("div", "glow"); g.style.background = `radial-gradient(circle, ${color} 0%, transparent 62%)`; g.style.opacity = opacity;
  BG.append(g); GLOWS.push({node: g, cx: cx * D.width, cy: cy * D.height, phase: SEED * 1.7 + GLOWS.length * 2.3});
}
if (BGK === "stars") {
  addGlow("var(--glow1)", 0.2, 0.3, 0.22); addGlow("var(--glow2)", 0.85, 0.75, 0.16);
  for (const [count, size, speed] of [[260, 1.3, 5], [90, 2.2, 12], [24, 3.2, 22]]) {   // far, middle, near: parallax
    const layer = sv("svg", {width: D.width * 2, height: D.height}, BG);
    for (let i = 0; i < count; i++)
      sv("circle", {cx: rand() * D.width * 2, cy: rand() * D.height, r: size * (0.6 + rand() * 0.6), fill: "#FFFFFF",
                    opacity: 0.3 + rand() * 0.6}, layer);
    LAYERS.push({node: layer, speed, wrap: D.width});
  }
} else {
  const grid = el("div", "grid"), cell = BGK === "notebook" ? 44 : 40, alpha = BGK === "notebook" ? 7 : 9;
  grid.style.backgroundImage = `linear-gradient(color-mix(in srgb, var(--grid) ${alpha}%, transparent) 1.5px, transparent 1.5px),`
    + `linear-gradient(90deg, color-mix(in srgb, var(--grid) ${alpha}%, transparent) 1.5px, transparent 1.5px)`;
  grid.style.backgroundSize = `${cell}px ${cell}px`;
  BG.append(grid); LAYERS.push({node: grid, speed: BGK === "notebook" ? 0 : 6, wrap: cell});
  addGlow("var(--glow1)", 0.2, 0.35, BGK === "notebook" ? 0.12 : 0.20);
  addGlow("var(--glow2)", 0.8, 0.7, BGK === "notebook" ? 0.10 : 0.16);
  if (BGK === "pcb") {           // a few circuit traces, faint, with a pulse running along each
    const traces = sv("svg", {width: D.width, height: D.height}, BG);
    for (let i = 0; i < 9; i++) {
      let x = Math.round(rand() * 47) * 40, y = Math.round(rand() * 26) * 40, d = `M${x} ${y}`;
      for (let k = 0; k < 4; k++) {
        if (k % 2) y += (rand() < 0.5 ? -1 : 1) * 40 * (2 + Math.round(rand() * 5)); else x += 40 * (3 + Math.round(rand() * 8));
        d += ` L${x} ${y}`;
      }
      const path = sv("path", {d, fill: "none", stroke: "var(--grid)", "stroke-width": 2, opacity: 0.09, "stroke-linejoin": "round"}, traces);
      const pulse = sv("path", {d, fill: "none", stroke: "var(--accent)", "stroke-width": 3, opacity: 0.3, "stroke-linecap": "round"}, traces);
      const length = path.getTotalLength();
      pulse.setAttribute("stroke-dasharray", `60 ${length + 60}`);
      PULSES.push({pulse, length, phase: rand() * 8});
    }
  }
}
if (STYLE.mode === "dark") BG.append(el("div", "vignette"));
// Film behind the scene: one JPEG per frame, cut by agent010 next to this page (D.footage.dir, a folder
// name it chose); seek shows the frame for t and waits until it is decoded.
let FOOTAGE = null;
if (D.footage && D.footage.count > 0) {
  FOOTAGE = el("img"); FOOTAGE.id = "footage"; BG.append(FOOTAGE, el("div")); BG.lastChild.id = "footage-shade";
  stage.classList.add("on-footage");
}
function seekFootage(t) {
  const n = clamp(Math.floor(t * D.footage.fps + 1e-6), 0, D.footage.count - 1) + 1;
  const src = `${D.footage.dir}/${String(n).padStart(5, "0")}.jpg`;
  if (FOOTAGE.getAttribute("src") !== src) FOOTAGE.setAttribute("src", src);
  return FOOTAGE.decode().catch(() => {});
}
function seekBackground(t) {
  GLOWS.forEach((g, i) => {
    const a = g.phase + t * (0.10 + 0.04 * i);
    g.node.style.left = `${g.cx + 170 * Math.cos(a)}px`; g.node.style.top = `${g.cy + 110 * Math.sin(a * 1.3)}px`;
  });
  for (const l of LAYERS) l.node.style.transform = `translateX(${-((t * l.speed) % l.wrap)}px)`;
  for (const p of PULSES) p.pulse.setAttribute("stroke-dashoffset", -(((t + p.phase) * 160) % (p.length + 120)) + 60);
}
// Titles: the theme's style; "kinetic" shows the title word by word (seek moves each word).
const TITLE = document.getElementById("title"), SUBTITLE = document.getElementById("subtitle");
TITLE.classList.add(STYLE.title || "plain"); SUBTITLE.classList.add(STYLE.subtitle || "plain");
const TITLE_WORDS = [];
if (STYLE.title === "kinetic") String(D.title || "").split(/(\s+)/).forEach(part => {
  if (!part.trim()) { TITLE.append(document.createTextNode(part)); return; }
  const w = el("span", "word", part); TITLE.append(w); TITLE_WORDS.push(w); });
else TITLE.textContent = D.title || "";
SUBTITLE.textContent = (STYLE.subtitle === "code" && !D.plan ? `// étape ${String(D.scene_number || 1).padStart(2, "0")} : ` : "") + (D.subtitle || "");
// The plan: one row per chapter, PLAN_PAGE rows a page; the next page takes the place of the last one
// when its first chapter is named (ten chapters no longer run over the titles).
const PLAN = [], PLAN_PAGE = 6;
if (Array.isArray(D.plan)) {
  const list = el("div"); list.id = "plan"; stage.append(list);
  D.plan.forEach((item, i) => {
    const row = el("div", "plan-item"); row.append(el("span", "num", String(item.number).padStart(2, "0")), el("span", "", String(item.title)));
    list.append(row); PLAN.push({row, at: +item.at || 0, page: Math.floor(i / PLAN_PAGE)});
  });
}
// The end of the video (D.ending, on its last scene): the picture fades to the background.
let FADE = null;
if (D.ending && D.ending.length > 0) {
  FADE = el("div"); FADE.id = "fade"; stage.append(FADE);
}
// Subtitles: the line the voice is saying (D.subtitles, timed in Python), text only.
let SUBS = null;
if (SUBS_SPACE) {
  SUBS = el("div"); SUBS.id = "subs"; stage.append(SUBS); stage.classList.add("with-subs");
}
let PROGRESS = null;
if (D.progress && D.progress.total > 0) {
  const box = el("div"), bars = el("div", "bars"); box.id = "progress";
  box.append(el("div", "count", `${String(D.progress.current).padStart(2, "0")} / ${String(D.progress.total).padStart(2, "0")}`), bars);
  for (let i = 1; i <= D.progress.total; i++) bars.append(el("i", i < D.progress.current ? "done" : (i === D.progress.current ? "now" : "")));
  stage.append(box); PROGRESS = box;
}
const E = {};
for (const ent of D.entities) {
  const box = el("div", "entity"), pop = el("div", "pop"); let shape, lamp = null, water = null;
  if (ent.compact) box.classList.add("compact");
  if (ent.rides) box.classList.add("passenger");
  if (ent.type === "LAMP") { shape = el("div", "bulb"); lamp = buildLamp(shape); }
  else if (ent.type === "BATTERY") { shape = el("div", "card battery"); shape.append(el("span", "neg", "−"), el("span", "pos", "+")); }
  else if (ent.type === "SWITCH") { shape = el("div", "switch"); const l = el("div", "lever");
    const a = el("div", "dot"), b = el("div", "dot"); a.style.left = "6px"; b.style.right = "6px"; shape.append(a, b, l); }
  else if (ent.type === "AMMETER") { shape = el("div", "meter"); shape.append(el("div", "unit", "A"), el("div", "reading", "0,00 A")); }
  else if (ent.type === "TEX_FORMULA") {
    shape = el("div", "card formula");
    // KaTeX builds the formula from the LaTeX text; trust: false, so no links, classes or raw HTML.
    if (window.katex) katex.render(ent.latex || "", shape, {throwOnError: false, trust: false, strict: "ignore", maxSize: 10, maxExpand: 200});
    else { shape.classList.add("plain"); shape.textContent = latexText(ent.latex || ""); }
  }
  else if (ent.type === "AXES_GRAPH") { shape = el("div", "graph"); ent.axes = buildAxes({...ent.graph, equal: parametricOn(ent.id)}, shape);
    ent.legend = el("div", "legend"); shape.append(ent.legend); }
  else if (ownAxes(ent)) {
    shape = el("div", "graph");
    ent.axes = buildAxes({x_range: ent.curve.x_range, y_range: ent.curve.y_range, equal: !!ent.curve.parametric}, shape);
    ent.legend = el("div", "legend"); shape.append(ent.legend); }
  else if (ent.type === "VOLTMETER_PROBES") {       // digital multimeter; its probes are drawn in #overlay
    shape = el("div", "card dmm");
    const head = el("div", "dmm-head"), jacks = el("div", "dmm-jacks");
    const ohmmeter = /ohmm|continuit/i.test(ent.label || "");    // named so: in ohms before any measure
    head.append(el("span", "", ohmmeter ? "Ω / continuité" : "V DC"), el("span", "", ent.label || ""));
    jacks.append(el("div", "jack black"), el("div", "jack red"));
    shape.append(head, el("div", "dmm-screen", ohmmeter ? "0,0 Ω" : "0,00 V"), jacks, el("div", "dmm-pins", ""));   // where its probes touch
    shape.dataset.ohms = ohmmeter ? "1" : "";
  }
  else if (PART_SYMBOLS[ent.type]) shape = buildPart(ent);     // a schematic symbol (resistor, AOP, MOSFET...)
  else if (ent.annotation) shape = el("div", "pill", ent.label || "");   // its arrow is drawn once it is placed
  else if (ent.type === "WIRE_BUS") shape = el("div", "junction");
  else if (ent.type === "EARTH_GROUND" || ent.type === "CHASSIS_MASS") { shape = el("div", "ground"); buildGround(shape, ent.type); }
  else if (ent.vector || ent.type === "CURVE_PLOT") shape = null;   // drawn in SVG below
  else if (ent.body) {                 // a disc (satellite, planet, ball); anchorVectors puts it on its curve
    if (!/^#[0-9A-Fa-f]{6}$/.test(ent.body.color)) ent.body.color = "#F59E0B";   // a colour from the brief: a "#RRGGBB" only
    shape = el("div", "body-disc");      // lit from the top left, as the spheres; on a dark theme, glowing in its colour
    Object.assign(shape.style, {width: 2 * ent.body.radius + "px", height: 2 * ent.body.radius + "px",
      background: `radial-gradient(circle at 35% 30%, color-mix(in srgb, ${ent.body.color} 45%, #FFFFFF) 0%, ${ent.body.color} 45%,`
                  + ` color-mix(in srgb, ${ent.body.color} 70%, #000000) 100%)`});
    if (GLOW) shape.style.boxShadow = `0 0 0 3px var(--ring), 0 0 22px color-mix(in srgb, ${ent.body.color} 70%, transparent)`;
  }
  else if (ent.lanes) shape = buildLanes(ent);
  else if (ent.seesaw) shape = buildSeesaw(ent);
  else if (ent.race) shape = buildRace(ent);
  else if (ent.population) shape = buildPopulation(ent);
  else if (ent.tides) shape = buildTides(ent);
  else if (ent.tunnel) shape = buildTunnel(ent);
  else if (ent.wave) shape = buildWave(ent);
  else if (ent.table) shape = buildTable(ent);
  else if (ent.chain) shape = buildChain(ent);
  else if (ent.simple) shape = buildSimple(ent);
  else if (ent.phys) shape = buildPhys(ent);
  else if (ent.mcu) shape = buildMcu(ent);
  else if (ent.breadboard) shape = buildBreadboard(ent);
  else if (ent.logic) shape = buildLogic(ent);
  else if (ent.fpga) shape = buildFpga(ent);
  else if (ent.sphere) shape = el("div", `sphere ${ent.sphere}`);
  else if (ent.icon) {
    shape = el("div", "card icon");
    if (ent.type === "WATER_TANK") {   // water behind the icon: its level and waves are set by seek()
      shape.classList.add("tank");
      water = sv("path", {fill: "rgba(59, 130, 246, .35)"}, sv("svg", {class: "water"}, shape));
    }
    const img = el("img"); img.src = ent.icon; shape.append(img);
  }
  else shape = el("div", "card");      // never the type name: no placeholder text on screen
  E[ent.id] = {data: ent, box: null, pop: null, shape, lamp, water, baseShadow: shape ? shape.style.boxShadow : "", spawn: null, out: null, states: [], values: [],
               counter: null, measures: [], inSide: false};
  if (!shape) continue;
  if (ent.tone) { shape.classList.add("toned"); shape.style.setProperty("--tone", `var(--tone-${ent.tone})`); }
  pop.append(shape);
  // A curve's label is its legend, a meter's is in its header; a junction has none.
  if (ent.label && !["CURVE_PLOT", "WIRE_BUS"].includes(ent.type) && !ent.instrument && !ent.annotation)
    pop.append(el("div", "label", ent.label));
  box.append(pop);
  if ((ent.instrument || (ent.annotation && ent.annotation.status)) && SIDE) {   // instruments and status badges: in the column
    side.append(box);
    if (ent.instrument) side.append(el("div", "probe-rest"));   // room under it for the probes
    E[ent.id].inSide = true;
  } else {
    box.style.left = ent.xy[0] + "px"; box.style.top = ent.xy[1] + "px";
    stage.append(box);
  }
  Object.assign(E[ent.id], {box, pop});
}
// Curves: drawn on their AXES_GRAPH (or their own axes), one colour each, with a legend entry.
const curvesOn = {};
for (const ent of D.entities.filter(e => e.type === "CURVE_PLOT")) {
  const host = E[ent.curve.axes] && E[ent.curve.axes].data.axes ? E[ent.curve.axes] : E[ent.id];
  const n = (curvesOn[host.data.id] = (curvesOn[host.data.id] || 0) + 1) - 1;
  const color = ent.curve.color || CURVE_COLORS[n % CURVE_COLORS.length];
  const d = curvePath(ent.curve.points, host.data.axes.map, ent.curve.closed);
  // "area": the space between a y = f(x) curve and the x axis filled with its colour, fading downwards.
  let area = null;
  if (AREA && !ent.curve.parametric && !host.data.axes.line) {
    const pts = ent.curve.points.filter(p => p[1] !== null);
    if (pts.length > 1) {
      const yr = (host.data.graph || host.data.curve).y_range, base = Math.min(Math.max(0, yr[0]), yr[1]), id = `area-${ent.id.replace(/[^\w-]/g, "")}`;
      const grad = sv("linearGradient", {id, x1: 0, y1: 0, x2: 0, y2: 1}, svg.querySelector("defs"));
      sv("stop", {offset: 0, "stop-color": color, "stop-opacity": 0.45}, grad); sv("stop", {offset: 1, "stop-color": color, "stop-opacity": 0}, grad);
      const [sx, sy] = host.data.axes.map(pts[0][0], base), [ex, ey] = host.data.axes.map(pts[pts.length - 1][0], base);
      area = sv("path", {d: `${curvePath(pts, host.data.axes.map, false)} L${ex} ${ey} L${sx} ${sy} Z`, fill: `url(#${id})`, stroke: "none"},
                host.data.axes.curves);
    }
  }
  // "glow": a wide faint stroke under the curve, drawn with it (cheaper than an SVG blur filter).
  const halo = GLOW ? sv("path", {d, fill: "none", stroke: color, "stroke-width": 26, opacity: 0.22, "stroke-linecap": "round",
                                  "stroke-linejoin": "round"}, host.data.axes.curves) : null;
  const path = sv("path", {d, fill: "none", stroke: color,
                           "stroke-width": 8, "stroke-linecap": "round", "stroke-linejoin": "round"}, host.data.axes.curves);
  let legend = null;
  if (ent.label) {
    legend = el("div"); const swatch = el("span"); swatch.style.background = color;
    legend.append(swatch, el("b", "", ent.label)); host.data.legend.append(legend);
  }
  // A glowing dot at the head of the curve while it draws itself: the eye follows it.
  const tracer = sv("circle", {r: 12, fill: color, stroke: "var(--bg)", "stroke-width": 4, opacity: 0}, host.data.axes.curves);
  Object.assign(E[ent.id], {curvePath: path, curveLength: path.getTotalLength(), legendItem: legend, curveHalo: halo, curveArea: area, curveTracer: tracer});
}
// A symbol as a physicist writes it: "F_g" is F with a g below ("_" starts the subscript), text only.
function writeSymbol(node, symbol, svgText) {
  const [main, ...rest] = String(symbol).split("_"), sub = rest.join("_");
  if (!sub) { node.textContent = symbol; return; }
  if (svgText) {
    node.textContent = main;
    const s = sv("tspan", {"baseline-shift": "sub", "font-size": "70%"}, node);
    s.textContent = sub;
  } else {
    node.append(document.createTextNode(main), el("sub", "", sub));
  }
}
// Vectors: an arrow from the entity's position, in the SVG layer, label beside it.
const LABEL_GAP = 18;
for (const ent of D.entities.filter(e => e.vector)) {
  const color = ent.vector.color || "#EF4444", [dx, dy] = ent.vector.direction;
  const g = sv("g", {}, svg);
  const line = sv("line", {stroke: color, "stroke-width": 10, "stroke-linecap": "round"}, g);
  const head = sv("polygon", {fill: color}, g);
  let labelBox = null;
  if (ent.label) {
    // Beside the middle of the arrow, LABEL_GAP px off its line on the perpendicular (to the right of
    // a vertical arrow, below a horizontal one), so the arrow never runs through its own label. It
    // goes to the other side if that side would reach into the instrument column.
    const label = sv("text", {class: "axis-label halo", "text-anchor": "middle", "dominant-baseline": "central"}, g);
    if (ent.vector.label_color) label.style.fill = color;     // riding vectors: the label in its arrow's colour
    writeSymbol(label, ent.vector.symbol || ent.label, true);   // a short symbol; what it stands for is in the legend
    if (ent.vector.legend) label.style.fontStyle = "italic";
    const len = ent.vector.length, mx = ent.xy[0] + dx * len / 2, my = ent.xy[1] - dy * len / 2;
    let [nx, ny] = [dy, dx];                       // perpendicular to the screen direction (dx, -dy)
    if (nx < -1e-6 || (Math.abs(nx) <= 1e-6 && ny < 0)) { nx = -nx; ny = -ny; }
    const {width, height} = label.getBBox();
    const place = side => {
      const off = LABEL_GAP + 5 + Math.abs(nx) * width / 2 + Math.abs(ny) * height / 2;
      label.setAttribute("x", mx + side * nx * off); label.setAttribute("y", my + side * ny * off);
      return {l: mx + side * nx * off - width / 2, t: my + side * ny * off - height / 2,
              r: mx + side * nx * off + width / 2, b: my + side * ny * off + height / 2};
    };
    labelBox = place(1);
    if (labelBox.r > MAIN_RIGHT - 10) labelBox = place(-1);
    Object.assign(E[ent.id], {vectorLabel: {label, width, height, nx, ny}});   // placed again once laid out
  }
  Object.assign(E[ent.id], {vector: {g, line, head, dx, dy: -dy, length: ent.vector.length, full: ent.vector.length, labelBox}});
}
// The vectors' legend, one line per label, "P : Poids", with the colour of each arrow it names: under
// the scene's graph when it has one, else in a row at the bottom of the frame (the diagram stays above
// it: FLOOR). Shown once one of its arrows is.
const VLEGEND = {}, VLEGEND_ROOM = 84;
const legendGraph = D.entities.find(ent => ent.legend);
let bottomLegend = null;
for (const ent of D.entities.filter(e => e.vector && e.vector.legend)) {
  const key = `${ent.vector.symbol}\u0000${ent.vector.legend}`, color = ent.vector.color || "#EF4444";
  if (!VLEGEND[key]) {
    if (!legendGraph && !bottomLegend) {
      bottomLegend = el("div", "legend"); bottomLegend.id = "vlegend"; stage.append(bottomLegend);
      bottomLegend.style.right = `${D.width - MAIN_RIGHT}px`;          // under the diagram, not the instrument column
      FLOOR = D.height - SUBS_SPACE - VLEGEND_ROOM;
      bottomLegend.style.bottom = `${18 + SUBS_SPACE}px`;
    }
    const item = el("div"), colours = el("span", "vsym"), symbol = el("b");
    writeSymbol(symbol, ent.vector.symbol, false);
    symbol.style.fontStyle = "italic";
    item.append(colours, symbol, el("span", "vtext", `: ${ent.vector.legend}`));
    (legendGraph ? legendGraph.legend : bottomLegend).append(item);
    VLEGEND[key] = {item, colours, ids: [], seen: new Set()};
  }
  const entry = VLEGEND[key];
  if (!entry.seen.has(color)) { entry.seen.add(color); const c = el("i"); c.style.background = color; entry.colours.append(c); }
  entry.ids.push(ent.id);
}
// A value shows the decimals it was given (0.96 -> "0,96", 1.5 -> "1,5"), up to 3.
function decimalsOf(v) { const s = String(v), i = s.indexOf("."); return i < 0 || /e/i.test(s) ? 0 : Math.min(3, s.length - i - 1); }
for (const ev of D.events) {
  const e = E[ev.target];
  if (ev.action === "spawn" && e && e.spawn === null) e.spawn = ev.at;
  if (ev.action === "fade_out" && e) e.out = ev.at;
  if (ev.action === "set_state" && e) {
    const {values, ...rest} = ev.state && typeof ev.state === "object" ? ev.state : {};   // LOGIC_CIRCUIT's {"values": {"b": 1}} as {"b": 1}
    e.states.push({at: ev.at, state: values && typeof values === "object" && e.data.logic ? {...rest, ...values} : ev.state});
  }
  if (ev.action === "set_value" && e && typeof ev.value === "number") {
    e.values.push({at: ev.at, value: ev.value, unit: ev.unit || "", tone: ev.tone,
                   decimals: Number.isInteger(ev.decimals) ? ev.decimals : decimalsOf(ev.value)});
    if (!e.counter && e.data.type !== "AMMETER") {   // an ammeter shows its value in its own dial
      e.counter = el("div", "card telemetry");
      e.counter.append(el("div", "t-label", e.data.label || ""), el("div", "t-value", "\u00a0"));   // its line kept from the start: the row is measured before any value
      side.append(e.counter);
    }
  }
  if (ev.action === "measure" && e && e.data.type === "VOLTMETER_PROBES") e.measures.push(ev);
  if (ev.action === "emphasize" && e && ["shake", "pulse"].includes(ev.effect)) (e.emphases ||= []).push(ev);
}
// A state the brief gives from the start ("closed": true in a switch's initial_state) holds from the
// first frame, as a step before t = 0: without it, a switch closed from the start is drawn open while
// its current flows. The actions' steps come after it.
const START_STATES = ["on", "closed", "active", "highlighted", "dimmed", "spinning"];
for (const e of Object.values(E)) {
  const initial = e.data.initial || {}, start = Object.fromEntries(START_STATES.filter(k => initial[k] === true).map(k => [k, true]));
  if (Object.keys(start).length) e.states.unshift({at: -1, state: start});
  // Steps add up: a switch closed, then highlighted, stays closed (each step only changes what it names).
  const asObject = st => typeof st === "string" ? {[st]: true} : (st && typeof st === "object" ? st : {});
  e.states.sort((a, b) => a.at - b.at);
  e.states.forEach((step, i) => { if (i) step.state = {...asObject(e.states[i - 1].state), ...asObject(step.state)}; });
}
const overlay = sv("svg", {id: "overlay"}, stage);   // above every component: probes, cables, contact rings
for (const e of Object.values(E)) if (e.spawn === null) e.spawn = 0;
for (const ev of D.events) {   // ammeters on a flow jump straight to its current when it starts
  if (ev.action !== "start_flow" || !Array.isArray(ev.path)) continue;
  const stop = D.events.find(s => s.action === "stop_flow" && s.at > ev.at
                                  && (!s.path || JSON.stringify(s.path) === JSON.stringify(ev.path)));
  for (const id of new Set(ev.path)) {
    const e = E[id];
    if (!e || e.data.type !== "AMMETER" || e.values.some(v => v.at <= ev.at + 0.01)) continue;
    // Target: the flow's "current", else the brief's next set_value for this meter, else 1.5 A.
    const next = e.values.find(v => v.at >= ev.at);
    const target = typeof ev.current === "number" ? ev.current : next ? next.value : 1.5;
    e.values.push({at: ev.at, value: target, unit: "A", decimals: 2, instant: true});
    if (stop) e.values.push({at: stop.at, value: 0, unit: "A", decimals: 2});
    e.values.sort((a, b) => a.at - b.at);
  }
}

// ---- right-angle wires around the components (run once fonts are loaded: boxes have their real size)
const STUB = 30, CLEAR = 30, BEND = 40, MARGIN = 10;
const LANE = 40;                   // clearance between two parallel wires (and channel spacing), >= 30 px
const CROSS = 800, ALONG = 3000, BACK = 2000, BLOCKED = 5000;   // routing penalties, in px of extra length
function offsetIn(node, root) {    // position of node inside root (layout offsets: transforms ignored)
  let x = 0, y = 0;
  for (; node && node !== root; node = node.offsetParent) { x += node.offsetLeft; y += node.offsetTop; }
  return [x, y];
}
function boxOf(e) {                // whole component (shape + label), centred on its position
  const w = e.box.offsetWidth, h = e.box.offsetHeight;
  return {l: e.data.xy[0] - w / 2, t: e.data.xy[1] - h / 2, r: e.data.xy[0] + w / 2, b: e.data.xy[1] + h / 2};
}
function rectIn(e, node) {         // a part of the component, in stage pixels
  const b = boxOf(e), [x, y] = offsetIn(node, e.box);
  return {l: b.l + x, t: b.t + y, r: b.l + x + node.offsetWidth, b: b.t + y + node.offsetHeight};
}
const shapeOf = e => rectIn(e, e.shape);                       // the drawing alone, where ports are
const labelOf = e => { const label = e.box.querySelector(".label"); return label ? rectIn(e, label) : null; };
const grow = (r, m) => ({l: r.l - m, t: r.t - m, r: r.r + m, b: r.b + m});
function hits(p, q, r) {           // axis-aligned segment p-q touches rectangle r
  return Math.min(p[0], q[0]) <= r.r && Math.max(p[0], q[0]) >= r.l && Math.min(p[1], q[1]) <= r.b && Math.max(p[1], q[1]) >= r.t;
}
function runsAlong(pts, other, besideOnly = false) {   // a segment lies on (unless besideOnly), or less than LANE px beside, another's
  for (let i = 1; i < pts.length; i++) for (let j = 1; j < other.length; j++) {
    const [p, q, u, v] = [pts[i - 1], pts[i], other[j - 1], other[j]];
    for (const [a, o] of [[1, 0], [0, 1]]) {
      const gap = Math.abs(p[a] - u[a]);
      if (Math.abs(p[a] - q[a]) < 1 && Math.abs(u[a] - v[a]) < 1 && gap < LANE && !(besideOnly && gap < 1)) {
        const lo = Math.max(Math.min(p[o], q[o]), Math.min(u[o], v[o])), hi = Math.min(Math.max(p[o], q[o]), Math.max(u[o], v[o]));
        if (hi - lo > 4) return true;
      }
    }
  }
  return false;
}
function sharedLength(pts, other) {   // how long two wires run on top of each other
  let n = 0;
  for (let i = 1; i < pts.length; i++) for (let j = 1; j < other.length; j++) {
    const [p, q, u, v] = [pts[i - 1], pts[i], other[j - 1], other[j]];
    for (const [a, o] of [[1, 0], [0, 1]])
      if (Math.abs(p[a] - q[a]) < 1 && Math.abs(u[a] - v[a]) < 1 && Math.abs(p[a] - u[a]) < 1)
        n += Math.max(0, Math.min(Math.max(p[o], q[o]), Math.max(u[o], v[o])) - Math.max(Math.min(p[o], q[o]), Math.min(u[o], v[o])));
  }
  return n;
}
function crossings(pts, other) {  // how many times two wires cross at a right angle
  let n = 0;
  for (let i = 1; i < pts.length; i++) for (let j = 1; j < other.length; j++) {
    const [p, q, u, v] = [pts[i - 1], pts[i], other[j - 1], other[j]];
    const h = Math.abs(p[1] - q[1]) < 1 ? [p, q] : Math.abs(u[1] - v[1]) < 1 ? [u, v] : null;
    const w = h === null ? null : h[0] === p ? [u, v] : [p, q];
    if (!h || Math.abs(w[0][0] - w[1][0]) > 1) continue;
    const x = w[0][0], y = h[0][1];
    if (x > Math.min(h[0][0], h[1][0]) + 1 && x < Math.max(h[0][0], h[1][0]) - 1
        && y > Math.min(w[0][1], w[1][1]) + 1 && y < Math.max(w[0][1], w[1][1]) - 1) n++;
  }
  return n;
}
function simplify(pts) {
  const out = [pts[0]];
  for (const p of pts.slice(1)) { if (Math.hypot(p[0] - out[out.length - 1][0], p[1] - out[out.length - 1][1]) > 0.5) out.push(p); }
  return out.filter((p, i) => i === 0 || i === out.length - 1 ||
    Math.abs((p[0] - out[i - 1][0]) * (out[i + 1][1] - p[1]) - (p[1] - out[i - 1][1]) * (out[i + 1][0] - p[0])) > 0.5);
}
// Named ports: [x, y] as fractions of the drawing, and the side the wire leaves from.
const LEFT = [-1, 0], RIGHT = [1, 0], UP = [0, -1], DOWN = [0, 1];
const SIDE_PORTS = {left: [0, 0.5, LEFT], right: [1, 0.5, RIGHT], top: [0.5, 0, UP], bottom: [0.5, 1, DOWN]};
const PORTS = {
  BATTERY: {negative: [0.25, 0, UP], positive: [0.75, 0, UP]},        // above the − and + signs
  LAMP: {left_terminal: [0, 0.5, LEFT], right_terminal: [1, 0.5, RIGHT]},
  AMMETER: {in: [0, 0.5, LEFT], out: [1, 0.5, RIGHT]},
  SWITCH: {in: [0, 0.8, LEFT], out: [1, 0.8, RIGHT]},                  // replaced by the real contacts below
  CHAIN_LINK: {in: [0, 0.5, LEFT], out: [1, 0.5, RIGHT]},
  WIRE_BUS: {in: [0, 0.5, LEFT], out: [1, 0.5, RIGHT]},
  EARTH_GROUND: {terminal: [0.5, 0, UP]},
  SUPPLY_RAIL: {terminal: [0.5, 1, DOWN]},
  POWER_SUPPLY: {negative: [0.25, 180 / 230, DOWN], positive: [0.75, 180 / 230, DOWN]},
  RESISTOR: {left: [0, 0.5, LEFT], right: [1, 0.5, RIGHT]},
  POTENTIOMETER: {left: [0, 0.25, LEFT], right: [1, 0.25, RIGHT], wiper: [0.5, 1, DOWN]},
  THERMISTOR: {left: [0, 28 / 64, LEFT], right: [1, 28 / 64, RIGHT]},
  OPAMP: {in_minus: [0, 48 / 160, LEFT], in_plus: [0, 112 / 160, LEFT], out: [1, 0.5, RIGHT], vcc: [80 / 170, 0, UP], gnd: [80 / 170, 1, DOWN]},
  MOSFET: {gate: [0, 90 / 140, LEFT], drain: [90 / 120, 0, UP], source: [90 / 120, 1, DOWN]},
  DIODE: {anode: [0, 0.5, LEFT], cathode: [1, 0.5, RIGHT]},
  LED: {anode: [0, 40 / 70, LEFT], cathode: [1, 40 / 70, RIGHT]},
  HEATER: {left: [0, 65 / 96, LEFT], right: [1, 65 / 96, RIGHT]},
  CHASSIS_MASS: {terminal: [0.5, 0, UP]},
  PEDAL_CRANK: {rim: [1, 0.5, RIGHT]},
  SPROCKET: {rim: [1, 0.5, RIGHT]},
};
const portsOf = e => PORTS[e.data.type] || (e.data.icon ? SIDE_PORTS : {});
function anchor(e, port) {
  // The exact point of a named port on the drawing, and its outward direction; null if unknown.
  const spec = portsOf(e)[port];
  if (!spec) return null;
  const r = shapeOf(e);
  if (e.data.type === "SWITCH") {                // a switch is wired at the outer edge of its contacts
    const dot = rectIn(e, e.shape.querySelectorAll(".dot")[port === "in" ? 0 : 1]);
    return {pt: [port === "in" ? dot.l : dot.r, (dot.t + dot.b) / 2], dir: spec[2]};
  }
  return {pt: [r.l + (r.r - r.l) * spec[0], r.t + (r.b - r.t) * spec[1]], dir: spec[2]};
}
function sideAnchor(e, other) {
  // No (known) port name: the middle of the side facing the other component, never the label's side.
  const r = shapeOf(e), [x, y] = e.data.xy, dx = other[0] - x, dy = other[1] - y;
  let dir = Math.abs(dx) >= Math.abs(dy) ? [Math.sign(dx) || 1, 0] : [0, Math.sign(dy) || 1];
  if (dir[1] > 0 && labelOf(e)) dir = [Math.sign(dx) || 1, 0];
  const pt = dir[0] > 0 ? [r.r, (r.t + r.b) / 2] : dir[0] < 0 ? [r.l, (r.t + r.b) / 2]
           : dir[1] > 0 ? [(r.l + r.r) / 2, r.b] : [(r.l + r.r) / 2, r.t];
  return {pt, dir};
}
function stubLength(e, end) {
  // Out far enough to clear the drawing's own label when the port faces down.
  const label = labelOf(e);
  return end.dir[1] > 0 && label ? Math.max(STUB, label.b - end.pt[1] + MARGIN + 6) : STUB;
}
function route(a, b, ends, placed, net) {
  const A = shapeOf(a), B = shapeOf(b), [ea, eb] = ends;
  const pa = ea.pt, pb = eb.pt, da = ea.dir, db = eb.dir, sa = stubLength(a, ea), sb = stubLength(b, eb);
  const oa = [pa[0] + da[0] * sa, pa[1] + da[1] * sa], ob = [pb[0] + db[0] * sb, pb[1] + db[1] * sb];
  // Obstacles: every other component (with its label); the two ends by their drawing and label;
  // the last stretch of every wire already drawn, so no wire lands on another's port.
  const obstacles = Object.values(E).filter(e => e.box && !e.data.annotation && e !== a && e !== b).map(e => grow(boxOf(e), MARGIN));
  obstacles.push(grow(A, -2), grow(B, -2));
  for (const label of [labelOf(a), labelOf(b)]) if (label) obstacles.push(grow(label, MARGIN));
  for (const w of placed) for (const [p, q] of [[w.pts[0], w.pts[1]], [w.pts[w.pts.length - 1], w.pts[w.pts.length - 2]]])
    obstacles.push(grow({l: Math.min(p[0], q[0]), t: Math.min(p[1], q[1]), r: Math.max(p[0], q[0]), b: Math.max(p[1], q[1])}, LANE / 2));
  // Channels: lines CLEAR px around every obstacle (and LANE px further out, twice), and lanes LANE px
  // on each side of every wire already drawn, so a new wire can always run beside one, never on it.
  const xs = new Set([oa[0], ob[0], (oa[0] + ob[0]) / 2]), ys = new Set([oa[1], ob[1], (oa[1] + ob[1]) / 2]);
  for (const r of obstacles) for (const k of [0, 1, 2]) {
    xs.add(r.l - CLEAR - k * LANE); xs.add(r.r + CLEAR + k * LANE);
    ys.add(r.t - CLEAR - k * LANE); ys.add(r.b + CLEAR + k * LANE);
  }
  for (const w of placed) for (let i = 1; i < w.pts.length; i++) {
    const [p, q] = [w.pts[i - 1], w.pts[i]];
    if (Math.abs(p[0] - q[0]) < 1) { xs.add(p[0] - LANE); xs.add(p[0] + LANE); }
    else { ys.add(p[1] - LANE); ys.add(p[1] + LANE); }
  }
  const top = below(D.subtitle ? 200 : 160);
  const X = [...xs].filter(x => x > 40 && x < MAIN_RIGHT - 30), Y = [...ys].filter(y => y > top && y < FLOOR - 30);
  // Candidates: the two L shapes (horizontal then vertical, vertical then horizontal), then paths
  // with 2 or 3 bends through the channels.
  const middles = [[[ob[0], oa[1]]], [[oa[0], ob[1]]]];
  for (const x of X) middles.push([[x, oa[1]], [x, ob[1]]]);
  for (const y of Y) middles.push([[oa[0], y], [ob[0], y]]);
  for (const x of X) for (const y of Y) { middles.push([[oa[0], y], [x, y], [x, ob[1]]]); middles.push([[x, oa[1]], [x, y], [ob[0], y]]); }
  // Cheapest wins: length + bends; crossing a wire, turning back into a port, running less than LANE px
  // beside another wire and going through an obstacle cost more and more. Nothing is forbidden, so
  // there is always a path, and a clean one beats any path that breaks a rule.
  let best = null, bestCost = Infinity;
  for (const m of middles) {
    const path = simplify([oa, ...m, ob]);
    let cost = polylineLength(path) + BEND * (path.length - 2);
    if (cost >= bestCost) continue;
    const back = (path[1][0] - oa[0]) * da[0] + (path[1][1] - oa[1]) * da[1] < -0.5
              || (path[path.length - 2][0] - ob[0]) * db[0] + (path[path.length - 2][1] - ob[1]) * db[1] < -0.5;
    cost += back ? BACK : 0;
    for (let i = 1; i < path.length; i++) cost += BLOCKED * obstacles.filter(r => hits(path[i - 1], path[i], r)).length;
    for (const w of placed) {
      // a wire of the same node may share its way (one wire, then a junction where they part); beside it, never
      if (net !== undefined && w.net === net) cost += (runsAlong(path, w.pts, true) ? ALONG : 0) - 0.7 * sharedLength(path, w.pts);
      else cost += CROSS * crossings(path, w.pts) + (runsAlong(path, w.pts) ? ALONG : 0);
    }
    if (cost < bestCost) { best = path; bestCost = cost; }
  }
  return simplify([pa, ...best, pb]);
}

// Dense layouts: components closer than GAP px (box + label) are pushed apart along the axis where
// they overlap least. A graph stays where the brief put it and the other one makes room; two
// ordinary components move half each. Everything stays inside the stage, below the titles.
const GAP = 20;
function place(e, x, y) {
  const w = e.box.offsetWidth, h = e.box.offsetHeight, top = below(D.subtitle ? 200 : 150) + h / 2 + (PANELS ? 12 : 0);
  const [left, right] = PANELS && e.panel !== undefined ? PANELS[e.panel]     // its panel, the backdrop, or the main area
    : LAYOUT === "analogy_fullscreen" ? [40, D.width - 40] : [0, MAIN_RIGHT];
  // Under the titles (and a comparison's row and panel titles) while it fits; taller than the room, centred.
  const lowest = FLOOR - h / 2 - 20;
  e.data.xy = [clamp(x, left + w / 2 + 20, right - w / 2 - 20), clamp(y, top <= lowest ? top : Math.min(top, FLOOR / 2), lowest)];
  e.box.style.left = e.data.xy[0] + "px"; e.box.style.top = e.data.xy[1] + "px";
}
function layoutZones() {           // outside "circuit": where the diagram starts, under the titles and the row
  if (LAYOUT === "circuit") return;
  const row = SIDE ? side.offsetTop + side.offsetHeight + 24 : 0;
  CONTENT_TOP = Math.max(D.subtitle ? 200 : 150, row) + (PANELS ? PANEL_HEAD : 0);
  const titles = Array.isArray(D.panels) ? D.panels : [];
  stage.querySelectorAll("[data-panel]").forEach((panel, i) => {
    panel.style.top = `${CONTENT_TOP - PANEL_HEAD}px`;
    if (titles[i]) panel.firstElementChild.textContent = titles[i];     // LLM text: textContent only
  });
  const backdrop = stage.querySelector("[data-backdrop]");
  if (backdrop) Object.assign(backdrop.style, {top: `${CONTENT_TOP - 20}px`, height: `${D.height - CONTENT_TOP - 4}px`});
  if (PANELS) for (const e of Object.values(E)) if (e.box && !e.inSide) e.panel = e.data.xy[0] < D.width / 2 ? 0 : 1;
}
// What is wider than its room (a panel, the main area, the backdrop) is made smaller, not left to
// spill out: a formula by its font size, a fixed-size drawing (a seesaw, toll lanes, a race) scaled down
// inside a wrapper of its new size, so every measure after this sees the size shown.
function fitToRoom() {
  for (const e of Object.values(E)) {
    if (!e.box || e.inSide || !e.shape) continue;
    const [left, right] = PANELS && e.panel !== undefined ? PANELS[e.panel]
      : LAYOUT === "analogy_fullscreen" ? [40, D.width - 40] : [0, MAIN_RIGHT];
    const room = right - left - 40;
    for (let i = 0; i < 3 && e.box.offsetWidth > room; i++) {
      const s = room / e.box.offsetWidth;
      if (e.shape.classList.contains("formula")) {
        e.shape.style.fontSize = `${parseFloat(getComputedStyle(e.shape).fontSize) * s * 0.98}px`;
      } else if (e.data.seesaw || e.data.lanes || e.data.race || e.data.population || e.data.tides || e.data.tunnel || e.data.wave || e.data.table || e.data.chain || e.data.simple || e.data.phys || e.data.mcu || e.data.breadboard || e.data.logic || e.data.fpga) {
        const w = e.shape.offsetWidth, h = e.shape.offsetHeight, wrap = el("div", "fit");
        Object.assign(wrap.style, {width: `${w * s}px`, height: `${h * s}px`});
        e.shape.replaceWith(wrap); wrap.append(e.shape);
        Object.assign(e.shape.style, {scale: String(s), transformOrigin: "0 0"});
        e.shape = wrap;
        break;
      } else break;
    }
  }
}
function locateSideItems() {      // the column lays itself out (flex): read where its items ended up
  for (const e of Object.values(E)) if (e.inSide) {
    const [x, y] = offsetIn(e.box, stage);
    e.data.xy = [x + e.box.offsetWidth / 2, y + e.box.offsetHeight / 2];
  }
}
// A host and the passengers placePassengers will put on its right, as one block: spreading things
// out with the host's box alone, a passenger would land on a neighbour.
// A thing moved in a straight line counts with the whole way it goes (start to end): nothing still
// may stand on its path (a formula the falling elevator would slide under).
function groupBox(e) {
  let b = boxOf(e);
  const riders = Object.values(E).filter(p => p.data.rides === e.data.id && p.box);
  if (riders.length) {
    const s = shapeOf(e), cy = (s.t + s.b) / 2, w = Math.max(...riders.map(p => p.box.offsetWidth)) + PASSENGER_GAP;
    const h = riders.reduce((sum, p) => sum + p.box.offsetHeight + PASSENGER_GAP, -PASSENGER_GAP);
    b = {l: b.l, t: Math.min(b.t, cy - h / 2), r: Math.max(b.r, s.r + w), b: Math.max(b.b, cy + h / 2)};
  }
  const ids = new Set([e.data.id, ...riders.map(p => p.data.id)]);
  for (const v of Object.values(E)) {        // the arrows starting on it reach that far (their symbol too)
    const a = v.vector && v.data.vector.anchor;
    if (!a || a.point || !ids.has(a.body)) continue;
    const reach = v.vector.full + 40;
    if (v.vector.dy > 0.5) b = {...b, b: b.b + reach}; else if (v.vector.dy < -0.5) b = {...b, t: b.t - reach};
    if (v.vector.dx > 0.5) b = {...b, r: b.r + reach}; else if (v.vector.dx < -0.5) b = {...b, l: b.l - reach};
  }
  const way = D.events.filter(ev => ev.action === "move" && ev.shift && ev.target === e.data.id)
    .reduce((sum, ev) => [sum[0] + ev.shift[0], sum[1] + ev.shift[1]], [0, 0]);
  return {l: Math.min(b.l, b.l + way[0]), t: Math.min(b.t, b.t + way[1]), r: Math.max(b.r, b.r + way[0]), b: Math.max(b.b, b.b + way[1])};
}
function spreadOut() {
  // Badges are placed by placeAnnotations; a body or object anchored in a graph, or riding in another
  // one, by anchorVectors (where the brief guessed it must push nothing away).
  const boxed = Object.values(E).filter(e => e.box && !e.inSide && !e.data.annotation && !e.data.placed && !e.data.rides
                                             && !(e.data.body && e.data.body.anchor));
  for (const e of boxed) place(e, ...e.data.xy);
  for (let pass = 0; pass < 30; pass++) {
    let moved = false;
    for (let i = 0; i < boxed.length; i++) for (let j = i + 1; j < boxed.length; j++) {
      const a = boxed[i], b = boxed[j], A = groupBox(a), B = groupBox(b);
      const ox = Math.min(A.r, B.r) - Math.max(A.l, B.l) + GAP, oy = Math.min(A.b, B.b) - Math.max(A.t, B.t) + GAP;
      if (ox <= 0 || oy <= 0) continue;                  // already GAP px apart on one axis
      const axis = ox <= oy ? 0 : 1, need = (axis ? oy : ox) + 2;
      const sign = Math.sign(b.data.xy[axis] - a.data.xy[axis]) || 1;
      const fa = a.data.axes && !b.data.axes ? 0 : b.data.axes && !a.data.axes ? 1 : 0.5;   // a's share of the move
      const push = (e, amount) => {   // how far it really went: the frame's edges may stop it
        const before = e.data.xy[axis], to = [...e.data.xy]; to[axis] += amount;
        place(e, ...to);
        return Math.abs(e.data.xy[axis] - before);
      };
      const start = [a.data.xy.slice(), b.data.xy.slice()];
      let left = need - push(a, -sign * need * fa) - push(b, sign * need * (1 - fa));
      // What the frame stopped, the other one does (a graph too).
      if (left > 0.5) left -= push(a, -sign * left);
      if (left > 0.5) left -= push(b, sign * left);
      if (left > 0.5) {                      // stuck against the frame: apart along the other axis instead
        place(a, ...start[0]); place(b, ...start[1]);
        const other = 1 - axis, A2 = groupBox(a), B2 = groupBox(b);
        const need2 = (other ? Math.min(A2.b, B2.b) - Math.max(A2.t, B2.t) : Math.min(A2.r, B2.r) - Math.max(A2.l, B2.l)) + GAP + 2;
        const sign2 = Math.sign(b.data.xy[other] - a.data.xy[other]) || 1;
        const push2 = (e, amount) => { const to = [...e.data.xy]; to[other] += amount; const before = e.data.xy[other];
                                       place(e, ...to); return Math.abs(e.data.xy[other] - before); };
        let rest = need2 - push2(a, -sign2 * need2 * fa) - push2(b, sign2 * need2 * (1 - fa));
        if (rest > 0.5) rest -= push2(a, -sign2 * rest);
        if (rest > 0.5) push2(b, sign2 * rest);
      }
      moved = true;
    }
    if (!moved) break;
  }
}

// Still overlapping once spread out (the frame too small for them all): the bigger of the two (never a
// graph, whose curves are drawn from its measures) is made 15 % smaller, and they are spread out again.
const SHRINK = 0.85, SHRINK_ROUNDS = 4;
function shrink(e, k) {
  if (!e.shape.classList.contains("fit")) {
    const wrap = el("div", "fit");
    Object.assign(wrap.style, {width: `${e.shape.offsetWidth}px`, height: `${e.shape.offsetHeight}px`});
    e.shape.replaceWith(wrap); wrap.append(e.shape);
    Object.assign(e.shape.style, {transformOrigin: "0 0"});
    e.shape = wrap;
  }
  const inner = e.shape.firstElementChild, scale = (parseFloat(inner.style.scale) || 1) * k;
  inner.style.scale = String(scale);
  Object.assign(e.shape.style, {width: `${inner.offsetWidth * scale}px`, height: `${inner.offsetHeight * scale}px`});
}
function shrinkToFit() {
  const boxed = Object.values(E).filter(e => e.box && !e.inSide && !e.data.annotation && !e.data.placed && !e.data.rides
                                             && !(e.data.body && e.data.body.anchor));
  for (let round = 0; round < SHRINK_ROUNDS; round++) {
    const smaller = new Set();
    for (let i = 0; i < boxed.length; i++) for (let j = i + 1; j < boxed.length; j++) {
      const A = groupBox(boxed[i]), B = groupBox(boxed[j]);
      if (Math.min(A.r, B.r) - Math.max(A.l, B.l) <= 1 || Math.min(A.b, B.b) - Math.max(A.t, B.t) <= 1) continue;
      const area = r => (r.r - r.l) * (r.b - r.t);
      const pick = [boxed[i], boxed[j]].filter(e => !e.data.axes && !ownAxes(e.data) && e.shape)
                                       .sort((a, b) => area(groupBox(b)) - area(groupBox(a)))[0];
      if (pick) smaller.add(pick);
    }
    if (!smaller.size) return;
    for (const e of smaller) shrink(e, SHRINK);
    spreadOut();
  }
}
function orthogonalD(pts) {        // "M x y" then only H and V commands: every wire segment is straight across or down
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    if (Math.abs(pts[i][0] - pts[i - 1][0]) > 0.05) d += ` H${pts[i][0].toFixed(1)}`;
    if (Math.abs(pts[i][1] - pts[i - 1][1]) > 0.05) d += ` V${pts[i][1].toFixed(1)}`;
  }
  return d;
}
// Wires: from the exact source port to the exact target port; an end without a known port name
// takes the side facing the other component.
const W = [], F = [], J = [];
function wireNets() {               // "id.port" -> the node it belongs to (leads joined by wires)
  const up = {}, find = k => up[k] === undefined || up[k] === k ? (up[k] = k) : (up[k] = find(up[k]));
  for (const [a, ap, b, bp] of D.connections) up[find(`${a}.${ap}`)] = find(`${b}.${bp}`);
  return find;
}
function drawWires() {
  const netOf = wireNets();
  for (const [a, ap, b, bp, dashed] of D.connections) {
    if (!E[a] || !E[b] || !E[a].box || !E[b].box) continue;
    const ea = anchor(E[a], ap) || sideAnchor(E[a], E[b].data.xy), eb = anchor(E[b], bp) || sideAnchor(E[b], E[a].data.xy);
    const net = netOf(`${a}.${ap}`), pts = route(E[a], E[b], [ea, eb], W, net), d = orthogonalD(pts);
    const path = sv("path", {d, fill: "none", "stroke-width": 7, "stroke-linejoin": "round", "stroke-linecap": "round"}, svg);
    path.style.stroke = "var(--wire)";
    // A dashed (optional) wire keeps its 6,4 dashes: it draws itself in through a mask instead.
    let reveal = null;
    if (dashed) {
      const mask = sv("mask", {id: `reveal-${W.length}`, maskUnits: "userSpaceOnUse", x: 0, y: 0, width: D.width, height: D.height}, svg);
      reveal = sv("path", {d, fill: "none", stroke: "#FFFFFF", "stroke-width": 14, "stroke-linejoin": "round", "stroke-linecap": "round"}, mask);
      Object.entries({"stroke-dasharray": "6,4", "stroke-linecap": "butt", mask: `url(#reveal-${W.length})`})
        .forEach(([k, v]) => path.setAttribute(k, v));
    }
    // drawn once both ends are there, or on its own words: {"action": "connect", "source_id", "target_id"}
    const said = D.events.find(ev => ev.action === "connect" && ((ev.source_id === a && ev.target_id === b)
                                                                || (ev.source_id === b && ev.target_id === a)));
    const ready = Math.max(E[a].spawn, E[b].spawn) + 0.4;
    W.push({a, b, ap, bp, net, pts, path, reveal, length: path.getTotalLength(), start: said ? Math.max(said.at, ready) : ready});
  }
  // a junction dot where two wires or more leave the same port: joined, not just crossing
  const ends = {};
  W.forEach(w => {
    for (const [id, pt, port] of [[w.a, w.pts[0], w.ap], [w.b, w.pts[w.pts.length - 1], w.bp]]) {
      const key = `${id}.${port}|${Math.round(pt[0])},${Math.round(pt[1])}`;
      (ends[key] = ends[key] || {pt, starts: []}).starts.push(w.start);
    } });
  // and where two wires of one node part: a bend of one lying on the other's way
  for (const w of W) for (const o of W) {
    if (w === o || w.net !== o.net) continue;
    for (const pt of w.pts.slice(1, -1)) {
      const onIt = o.pts.some((u, j) => j && (Math.abs(u[0] - o.pts[j - 1][0]) < 1 ? Math.abs(pt[0] - u[0]) < 1 && pt[1] > Math.min(u[1], o.pts[j - 1][1]) + 1 && pt[1] < Math.max(u[1], o.pts[j - 1][1]) - 1
                                                                                  : Math.abs(pt[1] - u[1]) < 1 && pt[0] > Math.min(u[0], o.pts[j - 1][0]) + 1 && pt[0] < Math.max(u[0], o.pts[j - 1][0]) - 1));
      if (onIt) {
        const key = `fork|${Math.round(pt[0])},${Math.round(pt[1])}`;
        (ends[key] = ends[key] || {pt, starts: [o.start]}).starts.push(w.start);
      }
    }
  }
  for (const j of Object.values(ends)) if (j.starts.length > 1)
    J.push({dot: sv("circle", {cx: j.pt[0], cy: j.pt[1], r: 8, fill: "var(--wire)", opacity: 0}, svg), at: Math.min(...j.starts.slice().sort((x, y) => x - y).slice(1)) + 0.5});
}
// Annotations: a pill badge and a short arrow (ARROW_MAX px) onto what it points at (aimOf): the
// edge of a component (from below, onto its label: the label hangs under the drawing), or a point
// of a curve or a vector. Of the four sides, the brief's direction first, the badge takes the first
// where neither it nor its arrow touches a wire or another box, and it stays out of the title zone
// and the instrument column.
const ARROW_MAX = 50, TIP_GAP = 6, HEAD = 10, NEAR = 60, CURVE_SPOTS = 24, FARTHER = 0.5;   // FARTHER: cost per px
// With no clear side at 50 px, a longer arrow (110, then 170 px) takes the badge past what is in the
// way; LONGER, the cost of each step, stays well under that of covering something (1000).
const ARROW_LENGTHS = [ARROW_MAX, ARROW_MAX + 60, ARROW_MAX + 120, ARROW_MAX + 200, ARROW_MAX + 300], LONGER = 150;   // longer ones: further off, rather than over another badge
function plotOf(host) {            // a graph's plot (its axes' SVG), without the legend under it
  const s = shapeOf(host), l = s.l + (s.r - s.l - GRAPH_W) / 2;   // .graph: a centred column, the SVG first
  return {l, t: s.t, r: l + GRAPH_W, b: s.t + (host.data.axes.line ? NUMBER_LINE_H : GRAPH_H)};
}
const graphHost = t => E[t.data.curve.axes] && E[t.data.curve.axes].data.axes ? E[t.data.curve.axes] : t;
// What a badge points at: the entity the brief names in "target" (resolved in Python, as the layout
// solver does). A curve: points along it (CURVE_SPOTS, the nearest to the brief's tip first: the
// badge takes the one where it fits best, a little farther costing a little); a vector: the middle
// of its shaft;
// axes: their plot, not the legend; a component: its box. Without a target, the box nearest to the
// brief's tip (NEAR px). {} when there is nothing: the badge then points at nothing (a conflict).
function batteryTerminal(text) {   // "positive" / "negative" when a text names one terminal (and only one)
  const t = String(text || "").toLowerCase();
  // a sign on its own ("borne -", "le −"), never the hyphen inside a word ("Qu'est-ce", "peut-il")
  const plus = /\+|\bplus\b|positi/.test(t), minus = /(?<!\p{L})[−–-](?!\p{L})|\bmoins\b|négati|negati/u.test(t);
  return plus === minus ? null : plus ? "positive" : "negative";
}
function aimOf(e, tip0, solids) {
  const t = E[e.data.annotation.target];
  const dist = p => Math.hypot(p[0] - tip0[0], p[1] - tip0[1]);
  if (t && t.curvePath) {
    const host = graphHost(t), plot = plotOf(host);
    const points = t.data.curve.points.filter(([, y]) => y !== null)
      .map(([x, y]) => { const [px, py] = host.data.axes.map(x, y); return [plot.l + px, plot.t + py]; });
    const spots = points.filter((_, i) => i % Math.max(1, Math.floor(points.length / CURVE_SPOTS)) === 0)
      .filter(p => p[1] > plot.t + 20 && p[1] < plot.b - 20 && p[0] > plot.l + 20 && p[0] < plot.r - 20);
    if (points.length) return {spots: [points.reduce((a, b) => dist(b) < dist(a) ? b : a), ...spots], host};
  }
  if (t && t.vector) {
    const v = t.vector, [x, y] = t.data.xy;
    return {point: [x + v.dx * v.length / 2, y + v.dy * v.length / 2], avoid: v.labelBox};
  }
  if (t && t.box && !t.inSide && !t.data.annotation) {
    if (t.data.axes) return {box: plotOf(t), solid: t};
    // A badge naming one terminal of a battery ("borne +", "pôle négatif") points at that terminal's
    // sign on the drawing, never at the battery as a whole (it could land by the other one).
    const terminal = t.data.type === "BATTERY" && batteryTerminal(e.data.label);
    if (terminal) return {box: rectIn(t, t.shape.querySelector(terminal === "positive" ? ".pos" : ".neg")), solid: t};
    // A thing with passengers beside it: the badge points at the group, so it never lands on them.
    const riders = Object.values(E).filter(p => p.data.rides === t.data.id && p.box).map(boxOf);
    const group = riders.length ? [boxOf(t), ...riders].reduce((a, b) => ({l: Math.min(a.l, b.l), t: Math.min(a.t, b.t),
                                                                           r: Math.max(a.r, b.r), b: Math.max(a.b, b.b)})) : null;
    return {solid: t, host: t.anchorHost, group};   // anchored in a graph: its box is no obstacle
  }
  const away = (r, p) => Math.hypot(Math.max(r.l - p[0], 0, p[0] - r.r), Math.max(r.t - p[1], 0, p[1] - r.b));
  const near = solids.filter(o => away(shapeOf(o), tip0) <= NEAR).sort((a, b) => away(shapeOf(a), tip0) - away(shapeOf(b), tip0))[0];
  return near ? {solid: near} : {};
}
function curvePointsOn(host) {     // stage points of every curve drawn on these axes (a badge avoids them)
  const plot = plotOf(host);
  return Object.values(E).filter(o => o.curvePath && graphHost(o) === host).flatMap(o => o.data.curve.points
    .filter(([, y]) => y !== null).map(([x, y]) => { const [px, py] = host.data.axes.map(x, y); return [plot.l + px, plot.t + py]; }));
}
// Anchored vectors, once the graphs are laid out: the start goes on the curve's point (graph units,
// worked out in Python), and a TANGENT / CENTER / OUTWARD direction becomes the screen direction from
// that point to "toward" (a small step that way on the curve's axes, so their scales are taken into
// account). A vector whose curve is not drawn keeps its position.
function labelNormal(sx, sy) {     // the side a vector's label goes, for a screen direction (sx, sy)
  let [nx, ny] = [-sy, sx];        // as in the vectors' build: right of a vertical arrow, below a horizontal one
  if (nx < -1e-6 || (Math.abs(nx) <= 1e-6 && ny < 0)) { nx = -nx; ny = -ny; }
  return [nx, ny];
}
const stagePoint = (curve, point) => {   // a curve's point (graph units) -> stage pixels
  const host = graphHost(curve), plot = plotOf(host), [px, py] = host.data.axes.map(...point);
  return [plot.l + px, plot.t + py];
};
// The graph an anchor ({curve, point} or {axes, point}) is on: an AXES_GRAPH, or a curve's own axes.
const anchorHost = a => { const t = E[a.curve || a.axes];
  return !t ? null : t.data.axes ? t : t.curvePath ? graphHost(t) : null; };
const anchorPoint = a => { const host = anchorHost(a); if (!host || !host.box) return null;
  const plot = plotOf(host), [px, py] = host.data.axes.map(...a.point); return [plot.l + px, plot.t + py]; };
function placeBody(e, point) {     // the body's disc centred on a stage point (its label hangs below)
  const b = boxOf(e), s = shapeOf(e), off = [(s.l + s.r) / 2 - (b.l + b.r) / 2, (s.t + s.b) / 2 - (b.t + b.b) / 2];
  e.data.xy = [point[0] - off[0], point[1] - off[1]];
  e.box.style.left = e.data.xy[0] + "px"; e.box.style.top = e.data.xy[1] + "px";
}
// Passengers (a BODY or an OBJECT anchored on another one: the astronaut in the ISS) sit beside their
// host's drawing, on its right (its left if there is no room: the frame, or the host's panel), one
// under the other, below the titles, their labels on their side: two things at one point would hide
// each other and their labels.
const PASSENGER_GAP = 10;
function placePassengers() {
  const passengers = {};
  for (const e of Object.values(E)) if (e.data.rides && e.box && E[e.data.rides] && E[e.data.rides].box) (passengers[e.data.rides] ||= []).push(e);
  // Stacked one under the other: a passenger with an arrow up goes first, one with an arrow down last
  // (the weight of a person standing over a scale would run into the scale).
  const downward = p => Math.max(-1, ...Object.values(E).filter(v => v.vector && (v.data.vector.anchor || {}).body === p.data.id)
                                                        .map(v => v.vector.dy));
  for (const list of Object.values(passengers)) list.sort((a, b) => downward(a) - downward(b));
  for (const [id, list] of Object.entries(passengers)) {
    if (E[id].data.body && E[id].data.body.anchor && E[id].data.body.anchor.curve) {   // on a curve: on its outer side
      placeOutward(E[id], list);
      list.forEach(p => { p.rest = p.data.xy.slice(); p.anchorHost = E[id].anchorHost; });
      continue;
    }
    const host = E[id], s = shapeOf(host), heights = list.map(p => p.box.offsetHeight);
    const right = PANELS && host.panel !== undefined ? PANELS[host.panel][1] : MAIN_RIGHT;
    let y = Math.max((s.t + s.b) / 2 - (heights.reduce((a, b) => a + b, 0) + PASSENGER_GAP * (list.length - 1)) / 2,
                     below(D.subtitle ? 200 : 150));
    // A stack reaching down to the host's label (below its drawing) goes past that label too.
    const label = labelOf(host), low = y + heights.reduce((a, b) => a + b, 0) + PASSENGER_GAP * (list.length - 1);
    const [l, r] = label && low > label.t ? [Math.min(s.l, label.l), Math.max(s.r, label.r)] : [s.l, s.r];
    list.forEach((p, i) => {
      const w = shapeOf(p).r - shapeOf(p).l, cy = y + heights[i] / 2;
      placeBody(p, [r + PASSENGER_GAP + w / 2, cy]);
      if (boxOf(p).r > right - 10) placeBody(p, [l - PASSENGER_GAP - p.box.offsetWidth + w / 2, cy]);
      p.rest = p.data.xy.slice();
      p.anchorHost = E[id].anchorHost;
      y += heights[i] + PASSENGER_GAP;
    });
  }
}
// A CENTER vector (gravity) stops short of what sits at the centre (the planet's drawing), else at 80 %
// of the way: its tip never runs through the planet. Never longer than the brief asked.
function fitCentre(r) {
  const a = r.data.vector.anchor, curve = a && a.centre && E[a.curve];
  if (!curve || !curve.curvePath) return;
  const c = stagePoint(curve, a.centre), [x, y] = r.data.xy, d = Math.hypot(c[0] - x, c[1] - y);
  const inside = o => { const q = shapeOf(o); return c[0] >= q.l && c[0] <= q.r && c[1] >= q.t && c[1] <= q.b; };
  const there = Object.values(E).find(o => o.box && o.anchorHost && !o.data.rides && inside(o));
  const room = there ? d - Math.max(shapeOf(there).r - shapeOf(there).l, shapeOf(there).b - shapeOf(there).t) / 2 - 14 : 0.8 * d;
  r.vector.length = clamp(room, Math.min(40, r.vector.full), r.vector.full);
}
// A vector starting on an object stops FRAME_ROOM px short of the titles, the frame's edges (its
// panel's, on a comparison page), and 14 px short of another component in its way (the weight of a
// person standing over the ground): its head is never under a card. Never shorter than 40 px, nor
// longer than the brief asked.
const FRAME_ROOM = 40;
function fitFrame(r, host) {
  const [x, y] = r.data.xy, v = r.vector;
  const [left, right] = PANELS && host.panel !== undefined ? PANELS[host.panel] : [0, MAIN_RIGHT];
  const reach = (p, d, low, high) => d > 1e-9 ? (high - p) / d : d < -1e-9 ? (low - p) / d : Infinity;
  let room = Math.min(reach(x, v.dx, left, right), reach(y, v.dy, below(D.subtitle ? 200 : 150), FLOOR)) - FRAME_ROOM;
  for (const o of Object.values(E)) {        // where the ray enters another component's box (slab method)
    if (!o.box || o.inSide || o === host || o.data.rides === host.data.id || o.data.annotation || o.data.axes) continue;
    const q = boxOf(o);
    let near = 0, far = Infinity;
    for (const [p, d, low, high] of [[x, v.dx, q.l, q.r], [y, v.dy, q.t, q.b]]) {
      if (Math.abs(d) < 1e-9) { if (p < low || p > high) far = -1; continue; }
      const a = (low - p) / d, b = (high - p) / d;
      near = Math.max(near, Math.min(a, b)); far = Math.min(far, Math.max(a, b));
    }
    if (near <= far && near > 0) room = Math.min(room, near - 14);
  }
  v.length = clamp(room, Math.min(40, v.full), v.full);
}
// A free object (not anchored, not riding) whose vector would have no room (an arrow up from a person
// under the subtitle) moves away from that edge first, so at least MIN_ARROW px of it show.
const MIN_ARROW = 100;
function makeRoom() {
  for (const r of Object.values(E)) {
    const a = r.vector && r.data.vector.anchor, host = a && !a.point && E[a.body];
    if (!host || !host.box || host.data.placed || host.data.rides || (host.data.body && host.data.body.anchor)) continue;
    const b = boxOf(host), want = Math.min(r.vector.full, MIN_ARROW) + FRAME_ROOM + 6, {dx, dy} = r.vector;
    const [left, right] = PANELS && host.panel !== undefined ? PANELS[host.panel] : [0, MAIN_RIGHT];
    const sx = dx < -0.5 ? Math.max(0, left + want - b.l) : dx > 0.5 ? -Math.max(0, b.r + want - right) : 0;
    const sy = dy < -0.5 ? Math.max(0, below(D.subtitle ? 200 : 150) + want - b.t) : dy > 0.5 ? -Math.max(0, b.b + want - FLOOR) : 0;
    if (sx || sy) place(host, host.data.xy[0] + sx, host.data.xy[1] + sy);
  }
}
function anchorVectors() {
  makeRoom();
  for (const e of Object.values(E)) {        // bodies and objects first: on their curve's or graph's point
    const anchor = (e.data.body && e.data.body.anchor) || e.data.placed, point = anchor && e.box && anchorPoint(anchor);
    if (!point) continue;
    placeBody(e, point);
    e.rest = e.data.xy.slice();
    e.anchorHost = anchorHost(anchor);       // it sits in that graph on purpose (overlaps, badges)
  }
  for (const e of Object.values(E)) if (MOVERS.has(e.data.id) && e.box && !e.rest) e.rest = e.data.xy.slice();   // moved by "move"
  placePassengers();
  for (const e of Object.values(E)) {
    const anchor = e.vector && e.data.vector.anchor;
    if (anchor && !anchor.point && E[anchor.body] && E[anchor.body].box) {
      // From an object: in line with its drawing's centre, where it leaves the object (its label
      // included), so the arrow runs through neither.
      const s = shapeOf(E[anchor.body]), b = boxOf(E[anchor.body]), [cx, cy] = [(s.l + s.r) / 2, (s.t + s.b) / 2];
      const [dx, dy] = [e.vector.dx, e.vector.dy];
      const out = Math.min(dx > 1e-9 ? (b.r - cx) / dx : dx < -1e-9 ? (b.l - cx) / dx : Infinity,
                           dy > 1e-9 ? (b.b - cy) / dy : dy < -1e-9 ? (b.t - cy) / dy : Infinity);
      e.data.xy = [cx + dx * (out + 6), cy + dy * (out + 6)];
      fitFrame(e, E[anchor.body]);
      e.rest = {xy: e.data.xy.slice(), dx: e.vector.dx, dy: e.vector.dy};
      continue;
    }
    const host = anchor && anchorHost(anchor);
    if (!host || !host.box) continue;
    const plot = plotOf(host), map = host.data.axes.map;
    const [px, py] = map(...anchor.point);
    e.data.xy = [plot.l + px, plot.t + py];
    if (anchor.host && E[anchor.body] && E[anchor.body].box) {   // on a passenger: from its drawing, beside its host
      const s = shapeOf(E[anchor.body]);
      e.data.xy = [(s.l + s.r) / 2, (s.t + s.b) / 2];
    }
    if (anchor.toward) {
      const [qx, qy] = map(...anchor.toward), n = Math.hypot(qx - px, qy - py) || 1;
      e.vector.dx = (qx - px) / n; e.vector.dy = (qy - py) / n;
      if (e.vectorLabel) [e.vectorLabel.nx, e.vectorLabel.ny] = labelNormal(e.vector.dx, e.vector.dy);
    }
    fitCentre(e);
    e.rest = {xy: e.data.xy.slice(), dx: e.vector.dx, dy: e.vector.dy};
    e.ridesMoving = !!anchor.body && MOVING.has(anchor.body);
  }
  // Vectors from one object the same way (its weight and its acceleration) side by side, PARALLEL_GAP
  // apart across their direction: on one line, the last one drawn would hide the others.
  const same = {};
  for (const e of Object.values(E)) {
    const a = e.vector && e.rest && e.data.vector.anchor;
    if (a && !a.point && a.body) (same[`${a.body} ${e.vector.dx.toFixed(2)} ${e.vector.dy.toFixed(2)}`] ||= []).push(e);
  }
  for (const group of Object.values(same)) group.forEach((e, i) => {
    const off = (i - (group.length - 1) / 2) * PARALLEL_GAP, [nx, ny] = [-e.vector.dy, e.vector.dx];
    e.data.xy = [e.data.xy[0] + nx * off, e.data.xy[1] + ny * off];
    e.rest.xy = e.data.xy.slice();
  });
}
const PARALLEL_GAP = 48;   // px between two parallel arrows (their heads are 32 px wide)
// A vector riding on a moving body turns as it goes: its label sits past its tip, in line with it,
// so it always names that arrow (beside it, it would end up beside another one). If a component is
// there (gravity points at the planet), it goes beside the arrow (its middle, then nearer its tip,
// either side, a line further out if needed), then behind its start, past the body. With no clear
// place, the one that covers the least. Placed at rest here, then at every seek by seekMotion.
function riderLabel(r) {
  const v = r.vector, l = r.vectorLabel, [x, y] = r.data.xy;
  const rider = E[r.data.vector.anchor.body], body = rider && rider.box ? boxOf(rider) : null;
  const bodyReach = body ? Math.abs(v.dx) * (body.r - body.l) / 2 + Math.abs(v.dy) * (body.b - body.t) / 2 : 0;
  const along = LABEL_GAP * 0.6 + Math.abs(v.dx) * l.width / 2 + Math.abs(v.dy) * l.height / 2;
  const [nx, ny] = labelNormal(v.dx, v.dy), aside = LABEL_GAP * 0.6 + Math.abs(nx) * l.width / 2 + Math.abs(ny) * l.height / 2;
  const at = f => [x + v.dx * v.length * f, y + v.dy * v.length * f];
  const spots = [at(1).map((c, i) => c + [v.dx, v.dy][i] * along)];
  for (const k of [0, 1]) for (const f of [0.5, 0.75]) for (const side of [1, -1]) {
    const [mx, my] = at(f), out = aside + k * (l.height + 6);
    spots.push([mx + side * nx * out, my + side * ny * out]);
  }
  spots.push([x - v.dx * (along + bodyReach), y - v.dy * (along + bodyReach)]);
  const boxes = Object.values(E).filter(o => o.box && !o.inSide && !o.data.annotation && !o.data.axes && o !== r).map(boxOf)
    .concat(Object.values(E).filter(o => o !== r && o.vector && o.vector.labelBox).map(o => o.vector.labelBox))   // nor on another label
    .concat(Object.values(E).filter(o => o.box && o.data.legend && o.data.legend.offsetHeight).map(o => rectIn(o, o.data.legend)));   // nor a legend
  const rectAt = ([cx, cy]) => ({l: cx - l.width / 2, t: cy - l.height / 2, r: cx + l.width / 2, b: cy + l.height / 2});
  const covered = q => boxes.reduce((sum, b) => sum + Math.max(0, Math.min(q.r, b.r) - Math.max(q.l, b.l) + 4)
                                                   * Math.max(0, Math.min(q.b, b.b) - Math.max(q.t, b.t) + 4), 0);
  const spot = spots.find(p => covered(rectAt(p)) === 0) || spots.reduce((a, b) => covered(rectAt(b)) < covered(rectAt(a)) ? b : a);
  l.label.setAttribute("x", spot[0]); l.label.setAttribute("y", spot[1]);
  v.labelBox = rectAt(spot);
}
// move_along: at seek(t), each moving body is where its latest started track puts it (an even pace
// over the track's duration; held at the end until the next one), else at rest on its anchor. The
// vectors riding on it go with it, their TANGENT / CENTER direction from the track, their label
// keeping its offset from the arrow's start.
// move: a thing moved in a straight line is at its rest plus the shifts started, each at its pace
// ("smooth", "fall": faster and faster, "linear"), kept in the frame.
// Then what goes with a moved thing: its passengers, the vectors starting on it, the badges at it.
const MOVES = D.events.filter(ev => ev.action === "move_along" && ev.track);
const SHIFTS = D.events.filter(ev => ev.action === "move" && ev.shift);
const EASE = {smooth: easeInOut, fall: p => p * p, linear: p => p};
const MOVERS = new Set([...MOVES, ...SHIFTS].map(ev => ev.target));
const MOVING = new Set([...MOVERS, ...D.entities.filter(e => MOVERS.has(e.rides)).map(e => e.id)]);   // and what rides in them
// A straight move goes as far as the brief asks, unless the thing would leave the frame (or its panel)
// with all that goes with it: its box, its passengers, the vectors starting on them and their labels,
// the badges at them. Then the whole move is shortened, on that axis, so it ends at the edge (eased
// as asked, never stopped short in mid-move). [scale x, scale y], once, at rest.
function moveScale(e) {
  const ids = new Set([e.data.id, ...Object.values(E).filter(p => p.data.rides === e.data.id).map(p => p.data.id)]);
  const parts = [...ids].map(id => boxOf(E[id]));
  for (const r of Object.values(E)) {
    const a = r.vector && r.data.vector.anchor;
    if (!a || a.point || !ids.has(a.body)) continue;
    const [x, y] = r.data.xy, v = r.vector, x2 = x + v.dx * v.length, y2 = y + v.dy * v.length;
    parts.push(grow({l: Math.min(x, x2), t: Math.min(y, y2), r: Math.max(x, x2), b: Math.max(y, y2)}, 18));
    if (v.labelBox) parts.push(v.labelBox);
  }
  const carried = new Set([...ids, ...Object.values(E).filter(r => r.vector && r.data.vector.anchor
                                                              && ids.has(r.data.vector.anchor.body)).map(r => r.data.id)]);
  for (const a of Object.values(E)) if (a.ann && carried.has(a.data.annotation.target)) parts.push(boxOf(a));
  const g = {l: Math.min(...parts.map(p => p.l)), t: Math.min(...parts.map(p => p.t)),
             r: Math.max(...parts.map(p => p.r)), b: Math.max(...parts.map(p => p.b))};
  const [left, right] = PANELS && e.panel !== undefined ? PANELS[e.panel] : [0, MAIN_RIGHT];
  const total = [0, 0];
  for (const ev of SHIFTS) if (ev.target === e.data.id) { total[0] += ev.shift[0]; total[1] += ev.shift[1]; }
  const room = [[left + 10 - g.l, right - 10 - g.r], [below(D.subtitle ? 200 : 150) - g.t, FLOOR - 10 - g.b]];
  return total.map((d, i) => {
    const [low, high] = room[i], allowed = clamp(d, Math.min(low, 0), Math.max(high, 0));
    return Math.abs(d) > 1e-6 ? allowed / d : 1;
  });
}
// A badge at a body moving along a curve: kept at a fixed offset, it would cross the curve's middle
// (the planet) half a lap later. So, at every frame, it sits outside the curve: on the line from the
// curve's centre through the body, past the body and its passengers, its arrow pointing back at them.
function curveCentre(curve) {        // the middle of a curve's drawing, stage pixels
  if (!curve.centre) {
    const pts = curve.data.curve.points.filter(p => p[1] !== null), xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    curve.centre = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  }
  return stagePoint(curve, curve.centre);
}
// The passengers of a body on a curve sit on the curve's outer side at every frame (on its right,
// half a lap later they would be over the planet in the middle), one past the other, in the frame and
// off the graph's legend. One with no room there (the orbit's bottom, near the legend) goes beside,
// along the curve, where it covers neither the host nor the others.
function placeOutward(host, riders) {
  const c = curveCentre(E[host.data.body.anchor.curve]), s = shapeOf(host), hc = [(s.l + s.r) / 2, (s.t + s.b) / 2];
  const n = Math.hypot(hc[0] - c[0], hc[1] - c[1]) || 1, u = [(hc[0] - c[0]) / n, (hc[1] - c[1]) / n], tg = [-u[1], u[0]];
  const top = below(D.subtitle ? 200 : 150), graph = host.anchorHost;
  const legend = graph && graph.data.legend && graph.data.legend.offsetHeight ? rectIn(graph, graph.data.legend) : null;
  const hits = (p, q) => Math.min(p.r, q.r) > Math.max(p.l, q.l) && Math.min(p.b, q.b) > Math.max(p.t, q.t);
  const taken = [shapeOf(host), labelOf(host)].filter(Boolean);   // its disc and its label, not the box around both
  let d = Math.max(s.r - s.l, s.b - s.t) / 2 + PASSENGER_GAP;
  for (const p of riders) {
    p.box.classList.toggle("flip", u[0] < -0.3);   // its label on the outer side too, never towards the host
    const q = boxOf(p), ps = shapeOf(p), pc = [(ps.l + ps.r) / 2, (ps.t + ps.b) / 2];
    const reach = [[q.l, q.t], [q.r, q.t], [q.l, q.b], [q.r, q.b]].map(([x, y]) => (x - pc[0]) * u[0] + (y - pc[1]) * u[1]);
    const back = -Math.min(...reach), r = d + back, step = (q.r - q.l) / 2 + PASSENGER_GAP;
    const fit = ([x, y]) => {               // placed there, then pushed into the frame and off the legend
      placeBody(p, [x, y]);
      const b = boxOf(p);
      const floor = Math.min(FLOOR, legend && b.r > legend.l && b.l < legend.r ? legend.t : Infinity);
      const dx = b.l < 10 ? 10 - b.l : b.r > MAIN_RIGHT - 10 ? MAIN_RIGHT - 10 - b.r : 0;
      const dy = b.t < top ? top - b.t : b.b > floor - 10 ? floor - 10 - b.b : 0;
      if (dx || dy) placeBody(p, [x + dx, y + dy]);
      return !taken.some(t => hits(boxOf(p), t));
    };
    // Straight out, then further out by 20 px steps (past the host's label), then just beside along
    // the curve; with no clear spot, straight out (touching the host's label beats drifting away).
    const spots = [[0, 0], [20, 0], [40, 0], [60, 0], [0, 1], [0, -1]]
      .map(([more, k]) => [hc[0] + u[0] * (r + more) + tg[0] * k * step, hc[1] + u[1] * (r + more) + tg[1] * k * step]);
    if (!spots.some(fit)) fit(spots[0]);
    taken.push(boxOf(p));
    d += back + Math.max(...reach) + PASSENGER_GAP;
  }
}
function orbitBadge(a, host) {
  const c = curveCentre(E[host.data.body.anchor.curve]), s = shapeOf(host), p = [(s.l + s.r) / 2, (s.t + s.b) / 2];
  const n = Math.hypot(p[0] - c[0], p[1] - c[1]) || 1, out0 = [(p[0] - c[0]) / n, (p[1] - c[1]) / n];
  const g = [host, ...Object.values(E).filter(o => o.data.rides === host.data.id && o.box)].map(boxOf)
    .reduce((x, y) => ({l: Math.min(x.l, y.l), t: Math.min(x.t, y.t), r: Math.max(x.r, y.r), b: Math.max(x.b, y.b)}));
  const w = a.box.offsetWidth, h = a.box.offsetHeight;
  // Straight out first, then tilted (30, 60, 90 degrees either way), each with the arrow lengths of
  // ARROW_LENGTHS: the first that keeps the badge off the graphs' legends and the other components
  // (at the frame's edge, straight out may have no room); else straight out, the shortest.
  const avoid = Object.values(E).filter(o => o.box && o.data.axes && o.data.legend && o.data.legend.offsetHeight).map(o => rectIn(o, o.data.legend))
    .concat(Object.values(E).filter(o => o.box && !o.inSide && !o.data.axes && !o.data.annotation && o !== host).map(boxOf));
  const at = (turn, arrow) => {
    const u = [out0[0] * Math.cos(turn) - out0[1] * Math.sin(turn), out0[0] * Math.sin(turn) + out0[1] * Math.cos(turn)];
    const out = Math.min(u[0] > 1e-9 ? (g.r - p[0]) / u[0] : u[0] < -1e-9 ? (g.l - p[0]) / u[0] : Infinity,
                         u[1] > 1e-9 ? (g.b - p[1]) / u[1] : u[1] < -1e-9 ? (g.t - p[1]) / u[1] : Infinity);
    const tip = [p[0] + u[0] * (out + TIP_GAP), p[1] + u[1] * (out + TIP_GAP)];
    const half = Math.min(Math.abs(u[0]) > 1e-9 ? w / 2 / Math.abs(u[0]) : Infinity, Math.abs(u[1]) > 1e-9 ? h / 2 / Math.abs(u[1]) : Infinity);
    const tail = [tip[0] + u[0] * arrow, tip[1] + u[1] * arrow];
    const c = [clamp(tail[0] + u[0] * half, w / 2 + 10, MAIN_RIGHT - w / 2 - 10),
               clamp(tail[1] + u[1] * half, below(D.subtitle ? 200 : 150) + h / 2, FLOOR - h / 2 - 10)];
    const r = {l: c[0] - w / 2, t: c[1] - h / 2, r: c[0] + w / 2, b: c[1] + h / 2};
    return {u, tip, tail, c, clear: !avoid.some(q => Math.min(r.r, q.r) > Math.max(r.l, q.l) && Math.min(r.b, q.b) > Math.max(r.t, q.t))};
  };
  const tries = [0, 30, -30, 60, -60, 90, -90].flatMap(deg => ARROW_LENGTHS.map(arrow => [deg * Math.PI / 180, arrow]));
  const {u, tip, tail, c: place} = tries.map(([turn, arrow]) => at(turn, arrow)).find(x => x.clear) || at(0, ARROW_MAX);
  setXY(a, place);
  Object.assign(a.ann, {tip, tail, end: [tip[0] + u[0] * HEAD, tip[1] + u[1] * HEAD]});
}
function setXY(e, xy) { e.data.xy = xy; e.box.style.left = xy[0] + "px"; e.box.style.top = xy[1] + "px"; }
function seekMotion(t) {
  const delta = {};                          // id -> [dx, dy]: how far it is from its rest, in px
  for (const e of Object.values(E)) {
    if (!e.data.body || !e.rest || !e.data.body.anchor || !e.data.body.anchor.curve) continue;
    const curve = E[e.data.body.anchor.curve], move = MOVES.filter(ev => ev.target === e.data.id && ev.at <= t).pop();
    let point = null, index = 0, track = null;
    if (move) {
      track = move.track;
      const pts = track.points, f = clamp((t - move.at) / move.duration, 0, 1) * (pts.length - 1);
      index = Math.min(Math.floor(f), pts.length - 2); const w = f - index;
      const lerp = (a, b) => [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w];
      point = lerp(pts[index], pts[index + 1]);
      track.at = {w, index, lerp};
      placeBody(e, stagePoint(curve, point));
    } else setXY(e, e.rest.slice());
    delta[e.data.id] = [e.data.xy[0] - e.rest[0], e.data.xy[1] - e.rest[1]];
    const riders = Object.values(E).filter(p => p.data.rides === e.data.id && p.box && p.rest);
    if (riders.length) {                     // its passengers: on the curve's outer side (placed here, before its vectors)
      placeOutward(e, riders);
      for (const p of riders) { p.onCurve = true; delta[p.data.id] = [p.data.xy[0] - p.rest[0], p.data.xy[1] - p.rest[1]]; }
    }
    for (const r of Object.values(E)) {
      const va = r.vector && r.rest && r.data.vector.anchor;
      if (!va || !va.point || (va.body !== e.data.id && va.host !== e.data.id)) continue;   // riding on it, or on its passenger
      if (!move) {
        r.data.xy = r.rest.xy.slice(); r.vector.dx = r.rest.dx; r.vector.dy = r.rest.dy;
        if (va.host && E[va.body]) { const ps = shapeOf(E[va.body]); r.data.xy = [(ps.l + ps.r) / 2, (ps.t + ps.b) / 2]; }
      }
      else {
        const on = stagePoint(curve, point), towards = track.riders[r.data.id];
        r.data.xy = on;
        if (va.host && E[va.body]) { const ps = shapeOf(E[va.body]); r.data.xy = [(ps.l + ps.r) / 2, (ps.t + ps.b) / 2]; }
        if (towards) {
          const q = stagePoint(curve, track.at.lerp(towards[index], towards[index + 1])), n = Math.hypot(q[0] - on[0], q[1] - on[1]) || 1;
          r.vector.dx = (q[0] - on[0]) / n; r.vector.dy = (q[1] - on[1]) / n;
        }
      }
      if (va.host && va.centre) {            // CENTER from a passenger: at the centre from where the passenger is
        const c = stagePoint(curve, va.centre), [x, y] = r.data.xy, n = Math.hypot(c[0] - x, c[1] - y) || 1;
        r.vector.dx = (c[0] - x) / n; r.vector.dy = (c[1] - y) / n;
      }
      fitCentre(r);
      if (r.vectorLabel && r.ridesMoving) riderLabel(r);
    }
  }
  for (const e of Object.values(E)) {
    if (!e.box || !e.rest || !SHIFTS.some(ev => ev.target === e.data.id)) continue;
    let dx = 0, dy = 0;
    for (const ev of SHIFTS) if (ev.target === e.data.id && ev.at <= t) {
      const f = (EASE[ev.easing] || easeInOut)(clamp((t - ev.at) / ev.duration, 0, 1));
      dx += ev.shift[0] * f; dy += ev.shift[1] * f;
    }
    e.moveScale = e.moveScale || moveScale(e);
    setXY(e, [e.rest[0] + dx * e.moveScale[0], e.rest[1] + dy * e.moveScale[1]]);
    delta[e.data.id] = [e.data.xy[0] - e.rest[0], e.data.xy[1] - e.rest[1]];
  }
  for (const e of Object.values(E)) {        // passengers go with their host (those on a curve are placed above)
    if (!e.data.rides || !e.rest || e.onCurve) continue;
    const d = delta[e.data.rides] || [0, 0];
    setXY(e, [e.rest[0] + d[0], e.rest[1] + d[1]]);
    delta[e.data.id] = d;
  }
  for (const r of Object.values(E)) {        // vectors starting on an object (or a passenger) go with it
    const anchor = r.vector && r.rest && r.data.vector.anchor;
    if (!anchor || anchor.point || !delta[anchor.body]) continue;
    const d = delta[anchor.body], v = r.vector;
    r.data.xy = [r.rest.xy[0] + d[0], r.rest.xy[1] + d[1]];
    delta[r.data.id] = d;                    // a badge at this vector goes along too
    if (r.vectorLabel && v.labelBox) {       // its label, placed at rest (placeVectorLabels), goes along
      const label = r.vectorLabel.label;
      r.labelRest = r.labelRest || {x: +label.getAttribute("x"), y: +label.getAttribute("y"), box: {...v.labelBox}};
      const {x, y, box} = r.labelRest;
      label.setAttribute("x", x + d[0]); label.setAttribute("y", y + d[1]);
      v.labelBox = {l: box.l + d[0], t: box.t + d[1], r: box.r + d[0], b: box.b + d[1]};
    }
  }
  for (const a of Object.values(E)) {        // a badge pointing at a moved thing goes with it
    const target = a.ann && E[a.data.annotation.target];
    const onCurve = o => o && o.data.body && o.data.body.anchor && o.data.body.anchor.curve && MOVERS.has(o.data.id);
    const mover = onCurve(target) ? target : target && onCurve(E[target.data.rides]) ? E[target.data.rides] : null;
    if (mover) {                             // going round a curve (or riding in what does): re-placed outside it at every frame
      orbitBadge(a, mover);
      continue;
    }
    const d = a.ann && delta[a.data.annotation.target];
    if (!d) continue;
    a.annBase = a.annBase || {xy: a.data.xy.slice(), tip: a.ann.tip.slice(), tail: a.ann.tail.slice(), end: a.ann.end.slice()};
    const shift = p => [p[0] + d[0], p[1] + d[1]];
    // Kept under the titles (placed for where its target ends, it may start too high): pushed down,
    // its arrow shorter, its tip still on the target.
    const top = below(D.subtitle ? 200 : 150), xy = shift(a.annBase.xy), tail = shift(a.annBase.tail);
    const down = Math.max(0, top - (xy[1] - a.box.offsetHeight / 2));
    setXY(a, [xy[0], xy[1] + down]);
    Object.assign(a.ann, {tip: shift(a.annBase.tip), tail: [tail[0], tail[1] + down], end: shift(a.annBase.end)});
  }
}
// Vector labels, once everything is laid out: each takes, of the places beside its arrow (either side,
// at its middle, then nearer its start or its end; or in line with it, behind its start or past its
// tip; each shifted up or down by whole text lines), the
// best: touching nothing (another label, an arrow, a component, an axis or its title, a curve, the
// frame edges, the title zone, the instrument column), then the least moved (beside the middle, then
// nearer an end, then in line; then the fewest lines up or down), and never farther from its arrow
// than LABEL_REACH (a label far from its arrow names nothing). The
// first place is the one the label had before (beside the middle, the column side avoided), so a
// vector with room keeps it. Vectors that share a start and a direction (several forces on one body)
// keep their arrows there: only their labels move, stacked beside the shared arrow.
const LABEL_ALONG = [0.5, 0.3, 0.7], LABEL_SHIFTS = [0, 1, -1, 2, -2, 3, -3], STACK_GAP = 8, FAR = 0.3;   // FAR: cost per px moved up or down
const LABEL_REACH = 80;           // px beyond half the label's width: the farthest a label's centre may sit from its arrow
function placeVectorLabels() {
  const header = below(D.subtitle ? 200 : 150), placed = [];
  const overlaps = (p, q) => Math.min(p.r, q.r) > Math.max(p.l, q.l) && Math.min(p.b, q.b) > Math.max(p.t, q.t);
  const shafts = Object.values(E).filter(o => o.vector).map(o => { const [x, y] = o.data.xy, v = o.vector;
    return [[x, y], [x + v.dx * v.length, y + v.dy * v.length]]; });
  const solids = Object.values(E).filter(o => o.box && !o.inSide && !o.data.annotation && !o.data.axes).map(boxOf);
  const hosts = Object.values(E).filter(o => o.box && o.data.axes);
  const axisLines = hosts.flatMap(h => { const p = plotOf(h);
    return h.data.axes.lines.map(([x1, y1, x2, y2]) => [[p.l + x1, p.t + y1], [p.l + x2, p.t + y2]]); });
  const axisTitles = hosts.flatMap(h => { const p = plotOf(h);
    return h.data.axes.labels.map(t => { const b = t.getBBox(); return {l: p.l + b.x, t: p.t + b.y, r: p.l + b.x + b.width, b: p.t + b.y + b.height}; }); });
  const curvePoints = hosts.flatMap(curvePointsOn);
  for (const e of Object.values(E)) {
    if (!e.vector || !e.vectorLabel) continue;
    if (e.ridesMoving) { riderLabel(e); placed.push(e.vector.labelBox); continue; }   // past its tip, see riderLabel
    const v = e.vector, {label, width, height, nx, ny} = e.vectorLabel, [x, y] = e.data.xy;
    const toShaft = (px, py) => {   // distance from a point to the arrow (its segment)
      const along = clamp((px - x) * v.dx + (py - y) * v.dy, 0, v.length);
      return Math.hypot(px - x - v.dx * along, py - y - v.dy * along);
    };
    const off = LABEL_GAP + 5 + Math.abs(nx) * width / 2 + Math.abs(ny) * height / 2;
    const line = height + STACK_GAP;                // one text line: labels stack up or down, as lines of text do
    const end = LABEL_GAP + 5 + Math.abs(v.dx) * width / 2 + Math.abs(v.dy) * height / 2;   // in line, past an end
    const spots = [...LABEL_ALONG.flatMap((along, a) => [1, -1].map(side => [v.length * along, side * off, 2 * a + (side < 0 ? 1 : 0)])),
                   [-end, 0, 6], [v.length + end, 0, 6]];   // [along the arrow, beside it, preference]
    let best = null;
    spots.forEach(([along, beside, preference]) => LABEL_SHIFTS.forEach(shift => {
      const cx = x + v.dx * along + nx * beside;
      const cy = y + v.dy * along + ny * beside + shift * line;
      const r = {l: cx - width / 2, t: cy - height / 2, r: cx + width / 2, b: cy + height / 2}, near = grow(r, 4);
      const far = toShaft(cx, cy);
      let cost = preference + FAR * Math.abs(shift) * line + (far > width / 2 + LABEL_REACH ? 5000 : 0);
      if (r.t < header || r.l < 10 || r.r > MAIN_RIGHT - 10 || r.b > FLOOR - 10) cost += 10000;
      for (const q of placed) if (overlaps(near, q)) cost += 1000;
      for (const q of solids) if (overlaps(near, q)) cost += 1000;
      for (const q of axisTitles) if (overlaps(near, q)) cost += 1000;
      for (const [p, q] of shafts) if (segmentHits(p, q, near)) cost += 800;
      for (const [p, q] of axisLines) if (segmentHits(p, q, near)) cost += 400;
      cost += 300 * curvePoints.filter(p => p[0] > near.l && p[0] < near.r && p[1] > near.t && p[1] < near.b).length;
      if (!best || cost < best.cost) best = {cost, cx, cy, r};
    }));
    label.setAttribute("x", best.cx); label.setAttribute("y", best.cy);
    v.labelBox = best.r;
    placed.push(best.r);
  }
}
function placeAnnotations() {
  const header = below(D.subtitle ? 200 : 150);
  const placed = Object.values(E).filter(o => o.vector && o.vector.labelBox).map(o => o.vector.labelBox);   // badges avoid vector labels
  const solids = Object.values(E).filter(o => o.box && !o.inSide && !o.data.annotation);
  const axisTitles = solids.filter(o => o.data.axes).flatMap(h => { const p = plotOf(h);   // every graph's: SVG units are stage pixels
    return h.data.axes.labels.map(t => { const b = t.getBBox(); return {l: p.l + b.x, t: p.t + b.y, r: p.l + b.x + b.width, b: p.t + b.y + b.height}; }); });
  const wireRects = W.flatMap(w => w.pts.slice(1).map((q, i) => { const p = w.pts[i];
    return grow({l: Math.min(p[0], q[0]), t: Math.min(p[1], q[1]), r: Math.max(p[0], q[0]), b: Math.max(p[1], q[1])}, 6); }));
  const overlaps = (p, q) => Math.min(p.r, q.r) > Math.max(p.l, q.l) && Math.min(p.b, q.b) > Math.max(p.t, q.t);
  // A badge at a thing moved in a straight line (or riding in one, or a vector on one) is placed where
  // that thing is once its moves are over (while the badge is still there), where it spends the most
  // time, not where it starts (an elevator still under the titles has no room around it); its
  // positions are kept relative to the rest, as seekMotion moves it along.
  const restOf = o => o && (Array.isArray(o.rest) ? o.rest : o.rest && o.rest.xy);
  const movesOf = o => !o || !restOf(o) ? [] : SHIFTS.filter(ev => [o.data.id, o.data.rides, o.data.vector && (o.data.vector.anchor || {}).body]
    .some(id => id && (ev.target === id || ev.target === (E[id] && E[id].data.rides))));
  let moved = false;
  for (const e of Object.values(E)) {
    if (!e.data.annotation || e.inSide || !e.box) continue;
    const aimed = E[e.data.annotation.target], moves = movesOf(aimed);
    // Every placement (side, arrow length, spot) is scored where things stand. For a badge at a moving
    // thing: when it appears and once the moves are over (while it is still there), the two costs
    // added; at the start, reaching into the title zone costs little (`soft`): seekMotion pushes the
    // badge down under the titles there. The positions kept are those at the end.
    const candidates = (soft = false) => {
    const out = [];
    const shafts = Object.values(E).filter(o => o.vector).map(o => { const [x, y] = o.data.xy, v = o.vector;
      return [[x, y], [x + v.dx * v.length, y + v.dy * v.length], o.data.id]; });   // a badge is never laid over another arrow
    const tip0 = e.data.xy, [bx, by] = e.data.annotation.direction, d0 = [bx, -by];   // screen: badge -> tip
    const aim = aimOf(e, tip0, solids), target = aim.solid;
    const onCurves = Object.values(E).filter(o => o.box && o.data.axes).flatMap(curvePointsOn);   // every curve drawn
    if (!aim.solid && !aim.point && !aim.spots) e.pointsAtNothing = true;
    const w = e.box.offsetWidth, h = e.box.offsetHeight;
    // The brief's side, the opposite one, the two across; a diagonal ([-0.5, -0.5]) has no other two
    // ([dy, dx] is itself): the four straight sides then.
    const sides = [d0, [-d0[0], -d0[1]], [d0[1], d0[0]], [-d0[1], -d0[0]], [0, 1], [0, -1], [1, 0], [-1, 0]]
      .filter((d, i, all) => all.findIndex(o => Math.abs(o[0] - d[0]) < 1e-6 && Math.abs(o[1] - d[1]) < 1e-6) === i);
    for (const spot of aim.spots || [aim.point]) sides.forEach((d, i) => ARROW_LENGTHS.forEach((arrow, k) => {
      let tip = tip0;
      if (spot) tip = [spot[0] - d[0] * TIP_GAP, spot[1] - d[1] * TIP_GAP];
      else if (target) {
        // the side where the target's label is (below it; on its right for a passenger): its whole box
        const labelSide = target.data.rides ? d[0] < -0.5 : d[1] < -0.5;
        const r = aim.box || aim.group || (labelSide ? boxOf(target) : shapeOf(target)), c = [(r.l + r.r) / 2, (r.t + r.b) / 2];
        // where the ray from the centre leaves the box: half its height / width on a cardinal, a corner
        // side on a tilted direction ([x, y]); x / 0 is Infinity, so min() keeps the other side.
        const reach = Math.min((r.r - r.l) / 2 / Math.abs(d[0]), (r.b - r.t) / 2 / Math.abs(d[1])) + TIP_GAP;
        tip = [c[0] - d[0] * reach, c[1] - d[1] * reach];
      }
      const tail = [tip[0] - d[0] * arrow, tip[1] - d[1] * arrow];
      const half = Math.abs(d[0]) * w / 2 + Math.abs(d[1]) * h / 2, c = [tail[0] - d[0] * half, tail[1] - d[1] * half];
      // A wide badge slides along the arrow's end to stay in the frame (the arrow still meets it, 20 px in).
      const slide = (centre, size, low, high, at) => {
        if (size <= high - low) centre = clamp(centre, low + size / 2, high - size / 2);
        const reach = Math.max(size / 2 - 20, 0);
        return clamp(centre, at - reach, at + reach);
      };
      if (Math.abs(d[1]) > 0.5) c[0] = slide(c[0], w, 20, MAIN_RIGHT - 20, tail[0]);
      else c[1] = slide(c[1], h, header, FLOOR - 20, tail[1]);
      const r = {l: c[0] - w / 2, t: c[1] - h / 2, r: c[0] + w / 2, b: c[1] + h / 2};
      let cost = i + LONGER * k + (aim.spots ? FARTHER * Math.hypot(spot[0] - tip0[0], spot[1] - tip0[1]) : 0);   // the brief's side, and spot, win a tie
      if (r.l < 20 || r.r > MAIN_RIGHT - 20 || r.b > FLOOR - 20) cost += 10000;
      if (r.t < header) cost += soft ? 300 : 10000;
      for (const o of solids) {
        if (o === aim.host) continue;              // pointing at a curve: inside its graph is fine...
        // over another graph's empty plot is bad; over a formula, an icon, a component (what they
        // show is lost) worse still
        if (overlaps(grow(r, 10), boxOf(o))) cost += o.data.axes ? 1000 : 2500;
        if (o !== target && segmentHits(tail, tip, boxOf(o))) cost += 1000;
      }
      cost += 200 * onCurves.filter(p => p[0] > r.l - 10 && p[0] < r.r + 10 && p[1] > r.t - 10 && p[1] < r.b + 10).length;
      if (aim.host) {                              // ...but not on its legend
        const legend = aim.host.data.legend;
        if (legend && legend.offsetHeight && overlaps(grow(r, 10), rectIn(aim.host, legend))) cost += 1000;
      }
      for (const title of axisTitles) if (overlaps(grow(r, 10), title)) cost += 1000;   // nor on any graph's axis titles
      if (aim.avoid && overlaps(grow(r, 10), aim.avoid)) cost += 1000;   // a vector's own label
      for (const [p, q, id] of shafts) if (id !== e.data.annotation.target && segmentHits(p, q, grow(r, 8))) cost += 800;
      for (const q of placed) {             // nor on a badge already placed, nor its arrow through one
        if (overlaps(grow(r, 10), q)) cost += 1000;
        if (segmentHits(tail, tip, grow(q, 4))) cost += 1000;
      }
      for (const q of wireRects) cost += (overlaps(r, q) ? 500 : 0) + (segmentHits(tail, tip, q) ? 300 : 0);
      out.push({key: `${aim.spots ? aim.spots.indexOf(spot) : 0}/${i}/${k}`, cost, c, tip, tail, r, d});
    }));
    return out;
    };
    let shift = [0, 0], options;
    if (moves.length) {
      const over = Math.max(...moves.map(ev => ev.at + ev.duration)), until = e.out === null ? Infinity : e.out - 0.1;
      const totals = {};
      e.placedForMotion = true;              // checked where it shows, not at the rest (layoutConflicts)
      for (const [t, soft] of [[e.spawn, true], [Math.max(e.spawn, Math.min(over, until)), false]]) {
        seekMotion(t + 0.01); moved = true;
        shift = [aimed.data.xy[0] - restOf(aimed)[0], aimed.data.xy[1] - restOf(aimed)[1]];
        options = candidates(soft);
        for (const o of options) totals[o.key] = (totals[o.key] || 0) + o.cost;
      }
      for (const o of options) o.cost = totals[o.key];
    } else options = candidates();
    const best = options.reduce((a, b) => (b.cost < a.cost ? b : a));
    const back = p => [p[0] - shift[0], p[1] - shift[1]];
    e.data.xy = back(best.c);
    e.box.style.left = e.data.xy[0] + "px"; e.box.style.top = e.data.xy[1] + "px";
    placed.push(best.r);
    const g = sv("g", {}, overlay);
    const line = sv("line", {stroke: "#3B82F6", "stroke-width": 2, "stroke-linecap": "round", "marker-end": "url(#annHead)"}, g);
    // The line stops HEAD px short: the 12 px head (6 units x the 2 px stroke) ends on the tip.
    e.ann = {g, line, tip: back(best.tip), tail: back(best.tail), end: back([best.tip[0] - best.d[0] * HEAD, best.tip[1] - best.d[1] * HEAD])};
  }
  if (moved) {                               // back to the rest; the moves' extents are worked out again, badges included
    seekMotion(0);
    for (const o of Object.values(E)) delete o.moveScale;
  }
}
// Flows: glowing electrons on a CSS offset-path along the wires of the path, in the path's direction
// (closed back to the start when a wire joins the last component to the first), crossing each
// component in a straight line. seek(t) sets their offset-distance.
function buildFlows() {
  for (const ev of D.events) {
    if (ev.action !== "start_flow" || !Array.isArray(ev.path)) continue;
    const ids = ev.path.filter(id => E[id]);
    if (ids.length >= 2 && ids[0] !== ids[ids.length - 1] && W.some(w => (w.a === ids[ids.length - 1] && w.b === ids[0]) || (w.b === ids[ids.length - 1] && w.a === ids[0])))
      ids.push(ids[0]);
    let pts = [], used = [];
    for (let i = 1; i < ids.length; i++) {
      const w = W.find(w => !used.includes(w) && w.a === ids[i - 1] && w.b === ids[i]) || W.find(w => !used.includes(w) && w.a === ids[i] && w.b === ids[i - 1]);
      if (w) { used.push(w); pts = pts.concat(w.a === ids[i - 1] ? w.pts : [...w.pts].reverse()); }
      else pts.push(E[ids[i - 1]].data.xy, E[ids[i]].data.xy);
    }
    if (pts.length < 2) continue;
    const stop = D.events.find(s => s.action === "stop_flow" && s.at > ev.at
                                    && (!s.path || JSON.stringify(s.path) === JSON.stringify(ev.path)));
    // "carriers": "electrons": the real carriers, from - to + (against the conventional current): the
    // dots go the other way round, each marked with a minus sign.
    const electrons = ev.carriers === "electrons";
    const total = polylineLength(pts), g = sv("g", {filter: "url(#electronGlow)"}, svg), d = pathD(pts);
    const dots = [...Array(Math.max(8, Math.round(total / (electrons ? 110 : 90))))].map(() => {
      // electrons: HTML discs with their minus sign (offset-path moves HTML boxes and single SVG shapes,
      // not SVG groups), in stage pixels as the wires
      const dot = electrons ? el("div", "electron", "−") : sv("circle", {r: 9}, g);
      if (electrons) stage.append(dot); else dot.style.fill = "var(--electron)";
      dot.style.offsetPath = `path("${d}")`; dot.style.offsetRotate = "0deg";
      return dot;
    });
    F.push({start: ev.at, stop: stop ? stop.at : Infinity, total, dots, ids, electrons});
  }
}
// Voltmeter probes: a red (pin a) and a black (pin b) probe on Bezier cables from the meter's jacks.
// They rest under the meter; a "measure" moves each tip onto its pin (black 0.15 s after red), a
// glowing ring marks the contact, then the display rolls up to the reading.
const P = [], MOVE = 0.9, LAG = {a: 0, b: 0.15}, NEEDLE = 22, BODY = 78;
function drawProbe(color) {        // pointing down: tip at (0, 0), body above it; seek() moves and turns it
  const g = sv("g", {}, overlay);
  sv("line", {x1: 0, y1: 0, x2: 0, y2: -NEEDLE, stroke: "#94A3B8", "stroke-width": 5, "stroke-linecap": "round"}, g);
  sv("path", {d: `M -8 ${-NEEDLE} L 8 ${-NEEDLE} L 11 ${-NEEDLE - BODY} Q 0 ${-NEEDLE - BODY - 12} -11 ${-NEEDLE - BODY} Z`, fill: color}, g);
  sv("rect", {x: -12, y: -NEEDLE - 30, width: 24, height: 7, rx: 3, fill: "rgba(255, 255, 255, .35)"}, g);   // grip ring
  return g;
}
function boardLead(pin) {
  // "<board>.<part>.<lead>" or "<board>.<part>": that lead's hole on the board, in stage pixels, and its name
  const [board, partId, leadName] = String(pin).split(".");
  const b = E[board];
  if (!b || !b.data.breadboard || !partId) return null;
  const part = b.data.breadboard.parts.find(q => q.id === partId);
  if (!part) return null;
  const lead = part.leads.find(l => l.name === leadName) || part.leads[0];
  const r = rectIn(b, b.shape.querySelector("svg")), k = (r.r - r.l) / b.data.breadboard.width;
  return {pt: [r.l + lead.x * k, r.t + lead.y * k], name: `${part.label} (${lead.name})`};
}
function buildProbes() {
  for (const e of Object.values(E)) {
    if (e.data.type !== "VOLTMETER_PROBES" || !e.box) continue;
    const [black, red] = e.shape.querySelectorAll(".jack"), centre = r => [(r.l + r.r) / 2, (r.t + r.b) / 2];
    const jack = {a: centre(rectIn(e, red)), b: centre(rectIn(e, black))};
    const rest = {a: [jack.a[0] + 30, jack.a[1] + 170], b: [jack.b[0] - 30, jack.b[1] + 170]};
    const measures = [];
    for (const m of e.measures) {
      const pins = {};
      const names = {};
      for (const [which, key] of [["a", "target_pin_a"], ["b", "target_pin_b"]]) {
        const pin = String(m[key] ?? ""), dot = pin.lastIndexOf("."), id = pin.slice(0, dot), port = pin.slice(dot + 1);
        const lead = boardLead(pin);         // a lead of a part on a breadboard
        if (lead) { pins[which] = lead.pt; names[which] = lead.name; continue; }
        const end = dot > 0 && E[id] && E[id].box ? anchor(E[id], port) : null;
        if (!end) continue;
        // on a battery terminal, the tip lands on its sign (+ or −), so the viewer sees which one
        const sign = E[id].data.type === "BATTERY" && (port === "positive" || port === "negative")
          ? E[id].shape.querySelector(port === "positive" ? ".pos" : ".neg") : null;
        pins[which] = sign ? (r => [(r.l + r.r) / 2, (r.t + r.b) / 2])(rectIn(E[id], sign)) : end.pt;
        names[which] = (E[id].data.label || id) + (sign ? (port === "positive" ? " (+)" : " (−)") : "");
      }
      if (pins.a && pins.b) measures.push({at: m.at, pins, names, value: Number(m.value) || 0, unit: m.unit || "V",
                                           decimals: Number.isInteger(m.decimals) ? m.decimals : 2});
    }
    // Cables run under the components and their labels (in the wires layer); probes and rings on top.
    const parts = {}, cables = sv("g", {}, svg);
    for (const [which, color] of [["a", "#EF4444"], ["b", STYLE.mode === "dark" ? "#94A3B8" : "#1F2937"]]) {   // the COM probe: black, grey on a dark theme
      const cable = sv("path", {fill: "none", stroke: color, "stroke-width": 6, "stroke-linecap": "round"}, cables);
      const ring = sv("circle", {r: 16, fill: "none", stroke: "#FBBF24", "stroke-width": 5, filter: "url(#electronGlow)"}, overlay);
      parts[which] = {cable, ring, body: drawProbe(color)};
    }
    const beep = el("div", "dmm-beep", "BIP : continuité"); beep.hidden = true; e.shape.append(beep);
    P.push({e, jack, rest, measures, parts, screen: e.shape.querySelector(".dmm-screen"), pinsText: e.shape.querySelector(".dmm-pins"),
            mode: e.shape.querySelector(".dmm-head span"), beep});
  }
}
function tipAt(p, which, t) {      // a probe's tip at time t (resting, moving to a pin, or on it), and its move
  let from = p.rest[which], to = p.rest[which], start = 0;
  for (const m of p.measures) { if (m.at + LAG[which] > t) break; from = to; to = m.pins[which]; start = m.at + LAG[which]; }
  const k = easeInOut(progress(t, start, MOVE));
  return {tip: [from[0] + (to[0] - from[0]) * k, from[1] + (to[1] - from[1]) * k], from, to, k};
}
function segmentHits(a, b, r) {    // does segment a-b cross rectangle r? (Liang-Barsky clipping)
  let t0 = 0, t1 = 1;
  const d = [b[0] - a[0], b[1] - a[1]];
  for (const [p, q] of [[-d[0], a[0] - r.l], [d[0], r.r - a[0]], [-d[1], a[1] - r.t], [d[1], r.b - a[1]]]) {
    if (Math.abs(p) < 1e-9) { if (q < 0) return false; continue; }
    const u = q / p;
    if (p < 0) t0 = Math.max(t0, u); else t1 = Math.min(t1, u);
    if (t0 > t1) return false;
  }
  return true;
}
const CABLE_ARC = 80;
function cableArc(jack, tip) {
  // The height of an arc over the diagram if the straight line from the jack to the probe would
  // cross a component (the one the probe touches excepted), else null: the cable hangs freely.
  const crossed = Object.values(E).filter(o => o.box && !o.inSide).map(boxOf)
    .filter(r => !(tip[0] >= r.l - 4 && tip[0] <= r.r + 4 && tip[1] >= r.t - 4 && tip[1] <= r.b + 4) && segmentHits(jack, tip, r));
  if (!crossed.length) return null;
  return Math.max(Math.min(...crossed.map(r => r.t), jack[1], tip[1]) - CABLE_ARC, below(D.subtitle ? 200 : 150));
}
const OHM_BEEP = 30;               // ohms: under this a multimeter in continuity mode beeps
function ohmReading(v) {           // 470,0 Ω, 1,000 kΩ, 2,200 MΩ: the range a multimeter picks
  return v >= 1e6 ? `${frenchNumber(v / 1e6, 3)} MΩ` : v >= 1e3 ? `${frenchNumber(v / 1e3, 3)} kΩ` : `${frenchNumber(v, 1)} Ω`;
}
function seekProbes(t) {
  for (const p of P) {
    const e = p.e, shown = progress(t, e.spawn + 0.3, 0.4) * (1 - (e.out === null ? 0 : progress(t, e.out, 0.5)));
    // The display rolls from the previous reading to the new one once both probes touch their pins.
    let current = null, before = 0;
    for (const m of p.measures) { if (m.at + LAG.b + MOVE > t) break; before = current ? current.value : 0; current = m; }
    const value = current ? before + (current.value - before) * easeInOut(progress(t, current.at + LAG.b + MOVE, 1.0)) : 0;
    // as an ohmmeter (a measure in Ω, or a meter named so): its mode written, its range (kΩ, MΩ) as on a
    // real one, and the continuity beep under OHM_BEEP
    const ohms = current ? current.unit === "Ω" : e.shape.dataset.ohms === "1";
    p.screen.textContent = ohms ? ohmReading(value) : `${frenchNumber(value, current ? current.decimals : 2)} ${current ? current.unit : "V"}`;
    if (p.mode) p.mode.textContent = ohms ? "Ω / continuité" : "V DC";
    if (p.beep) p.beep.hidden = !(ohms && current && current.value < OHM_BEEP && value <= OHM_BEEP);
    p.screen.style.color = current ? "#4ADE80" : "#22C55E80";
    if (p.pinsText) p.pinsText.textContent = current ? `Rouge : ${current.names.a}\nNoire : ${current.names.b}` : "";   // LLM labels: textContent
    for (const which of ["a", "b"]) {
      const part = p.parts[which], move = tipAt(p, which, t), tip = move.tip, jack = p.jack[which];
      // The probe points away from its tip towards the meter, held from above.
      const n = Math.hypot(jack[0] - tip[0], jack[1] - tip[1]) || 1;
      let ax = (jack[0] - tip[0]) / n, ay = (jack[1] - tip[1]) / n - 1;
      const an = Math.hypot(ax, ay) || 1; ax /= an; ay /= an;
      part.body.setAttribute("transform", `translate(${tip[0].toFixed(1)} ${tip[1].toFixed(1)}) rotate(${(Math.atan2(ax, -ay) * 180 / Math.PI).toFixed(2)})`);
      const back = [tip[0] + ax * (NEEDLE + BODY), tip[1] + ay * (NEEDLE + BODY)];
      // Free cable: down from the jack, into the probe's back. Over a component: an arc whose two
      // control points sit CABLE_ARC px above the highest thing it would cross. During a move the
      // shape blends from the arc needed at the start to the one needed at the end.
      const arcFrom = cableArc(jack, move.from), arcTo = cableArc(jack, move.to);
      const arched = (arcFrom !== null ? 1 - move.k : 0) + (arcTo !== null ? move.k : 0);
      const arcY = arcFrom !== null && arcTo !== null ? arcFrom + (arcTo - arcFrom) * move.k : (arcTo ?? arcFrom ?? 0);
      const mix = (a, b) => a + (b - a) * arched;
      const c1 = [mix(back[0] + ax * 120, back[0]), mix(back[1] + ay * 120, arcY)];
      const c2 = [jack[0], mix(jack[1] + 160, arcY)];
      part.cable.setAttribute("d", `M${back[0].toFixed(1)} ${back[1].toFixed(1)} C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} `
                                   + `${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${jack[0].toFixed(1)} ${jack[1].toFixed(1)}`);
      part.body.style.opacity = part.cable.style.opacity = shown;
      // Contact ring: from the moment the tip lands until the probe leaves for the next pins.
      let on = null;
      p.measures.forEach((m, i) => { const next = p.measures[i + 1];
        if (m.at + LAG[which] + MOVE <= t && !(next && next.at + LAG[which] <= t)) on = m; });
      part.ring.style.opacity = on ? progress(t, on.at + LAG[which] + MOVE, 0.2) * shown : 0;
      if (on) { part.ring.setAttribute("cx", on.pins[which][0]); part.ring.setAttribute("cy", on.pins[which][1]);
                part.ring.setAttribute("r", 15 + 3 * Math.sin(2 * Math.PI * 2 * t)); }
    }
  }
}
function stateAt(e, t) { let current = null; for (const s of e.states) if (s.at <= t) current = s; return current; }
function is(state, key) { return state && (state.state === key || (typeof state.state === "object" && state.state[key] === true)); }
function blend(e, t, test, seconds) {
  // 0..1: how far the component is into the states where test() holds, eased over `seconds` from the
  // previous state (what a CSS "transition: ... 0.4s ease" would show, but exact at any t).
  let current = null, before = null;
  for (const s of e.states) if (s.at <= t) { before = current; current = s; }
  if (!current) return 0;
  const from = before && test(before) ? 1 : 0, to = test(current) ? 1 : 0;
  return from + (to - from) * easeInOut(progress(t, current.at, seconds));
}
function valueAt(e, t, rollSeconds) {   // [value, the step it comes from, the step before] at time t
  let shown = 0, previous = 0, v = null, before = null;
  for (const c of e.values) { if (c.at > t) break; previous = shown; shown = c.value; before = v; v = c; }
  if (!v) return [0, null, null];
  return [v.instant ? v.value : previous + (v.value - previous) * easeInOut(progress(t, v.at, rollSeconds)), v, before];
}
const lit = s => is(s, "on") || is(s, "active"), closed = s => is(s, "closed") || is(s, "on") || is(s, "active");

function seekTelemetry(e, t, gone) {
  // The entity's telemetry card in the column: it fades in with the first value, rolls each new
  // value up from the previous one in 0.8 s (the value is read while it is said, not after), and
  // fades out with its entity (then it is hidden). A value in a new unit never overlaps the old text:
  // the old one fades out, then the new one in.
  if (!e.counter) return;
  const [value, v, before] = valueAt(e, t, 0.8), text = e.counter.lastChild;
  const opacity = v ? easeInOut(progress(t, e.values[0].at, 0.4)) * (1 - gone) : 0;
  e.counter.style.opacity = opacity;
  e.counter.style.visibility = opacity > 0 ? "visible" : "hidden";
  if (!v) return;
  const swap = before && before.unit !== v.unit ? progress(t, v.at, 0.5) : 1, old = swap < 0.5;
  const step = old ? before : v;
  text.textContent = `${frenchNumber(old ? before.value : value, step.decimals)} ${step.unit}`.trim();
  text.style.opacity = old ? 1 - 2 * swap : 2 * swap - 1;
  text.style.color = step.tone === "positive" ? "var(--pos)" : (step.tone === "negative" || step.value < 0) ? "var(--neg)" : "var(--text)";
}

// A water tank: its level (initial_state / set_state "level", 0 to 1) rises or falls over 1.2 s;
// its surface ripples, harder while a flow runs through the tank.
function levelAt(e, t) {
  const clampLevel = v => Math.min(0.95, Math.max(0.05, v));
  let shown = clampLevel(Number(e.data.initial.level ?? 0.6)), previous = shown;
  for (const s of e.states) {
    if (s.at > t) break;
    if (!s.state || typeof s.state.level !== "number") continue;
    previous = shown;
    shown = previous + (clampLevel(s.state.level) - previous) * easeInOut(progress(t, s.at, 1.2));
  }
  return shown;
}
function seekWater(e, t) {
  const w = e.shape.clientWidth, h = e.shape.clientHeight, y0 = h * (1 - levelAt(e, t));
  const flowing = F.some(f => f.ids.includes(e.data.id) && t >= f.start && t < f.stop), amp = flowing ? 6 : 2.5;
  let d = `M0 ${h} L0 ${y0.toFixed(1)}`;
  for (let i = 0; i <= 12; i++) {
    const x = w * i / 12;
    d += ` L${x.toFixed(1)} ${(y0 + amp * Math.sin(2 * Math.PI * (1.5 * i / 12 - 0.8 * t))).toFixed(1)}`;
  }
  e.water.setAttribute("d", d + ` L${w} ${h} Z`);
}

// "emphasize": a shake (a contradiction: 0.9 s, fading, the drawing flashing red) or a pulse (a result:
// two beats over 1.2 s, a ring in its tone's colour). On the shape, after its own state is set.
const EMPHASIS = {shake: 0.9, pulse: 1.2};
// A large drawing (tides, a seesaw, a race, a grid of dots, lanes) has no card around it: a ring would
// draw a rectangle round the whole page; it only beats, gently.
const bigDrawing = e => e.data.tides || e.data.seesaw || e.data.race || e.data.population || e.data.lanes || e.data.tunnel || e.data.wave || e.data.table || e.data.chain || e.data.simple || e.data.phys || e.data.mcu || e.data.breadboard || e.data.logic || e.data.fpga;
function seekEmphasis(e, t) {
  if (!e.emphases || !e.shape) return;
  const ev = e.emphases.filter(x => x.at <= t && t < x.at + EMPHASIS[x.effect]).pop();
  if (!ev) { e.shape.style.transform = ""; if (bigDrawing(e)) e.shape.style.boxShadow = ""; return; }
  const k = (t - ev.at) / EMPHASIS[ev.effect];
  if (bigDrawing(e)) {
    const beat = Math.sin(Math.PI * ((k * 2) % 1)), fade = 1 - k;
    e.shape.style.transform = ev.effect === "shake" ? `translateX(${Math.sin((t - ev.at) * 2 * Math.PI * 7) * 10 * fade}px)`
                                                    : `scale(${1 + 0.03 * beat})`;
    e.shape.style.boxShadow = "";
  } else if (ev.effect === "shake") {
    const fade = 1 - k, dx = Math.sin((t - ev.at) * 2 * Math.PI * 7) * 14 * fade;
    e.shape.style.transform = `translateX(${dx}px) rotate(${dx * 0.12}deg)`;
    e.shape.style.borderColor = "var(--tone-wrong)";
    e.shape.style.boxShadow = `0 0 0 ${6 * fade}px color-mix(in srgb, var(--tone-wrong) 35%, transparent), 0 0 30px color-mix(in srgb, var(--tone-wrong) ${50 * fade}%, transparent)`;
  } else {
    const beat = Math.sin(Math.PI * ((k * 2) % 1));
    e.shape.style.transform = `scale(${1 + 0.1 * beat})`;
    e.shape.style.boxShadow = `0 0 0 ${10 * beat}px color-mix(in srgb, ${e.data.tone ? `var(--tone-${e.data.tone})` : "var(--accent)"} 35%, transparent)`;
  }
}
// ---- the only function the renderer calls: draw everything as it is at time t (seconds)
// The camera. {"action": "zoom_in", "target": id}: a dashed frame around the thing, the view zooms
// on it until it fills the screen, then fades: the next scene shows its inside, arriving from the zoom
// (D.arrive: it grows in from the middle, a dashed frame around it). {"action": "zoom_out", "target":
// id} (a scene's start): the view begins zoomed on the thing and pulls back to the whole. Titles,
// subtitles and the background never move.
const ZOOM_SEC = 1.6, ZOOM_MAX = 7, ARRIVE_SEC = 1.2;
let WORLD = null, CAMERA = [];
function buildCamera() {
  const keep = new Set(["bg", "title", "subtitle", "plan", "fade", "subs"]);
  WORLD = el("div"); WORLD.id = "world";
  for (const child of [...stage.children]) if (!keep.has(child.id) && child !== PROGRESS) WORLD.append(child);
  stage.insertBefore(WORLD, document.getElementById("title"));
  const room = stage.getBoundingClientRect();
  for (const ev of D.events) {
    if (ev.action !== "zoom_in" && ev.action !== "zoom_out") continue;
    const e = E[ev.target], node = e && (e.box || e.shape);
    if (!node) continue;
    const r = node.getBoundingClientRect(), pad = 18;
    const rect = {l: r.left - room.left, t: r.top - room.top, w: r.width, h: r.height};
    const frame = el("div", "zoom-frame");
    Object.assign(frame.style, {left: `${rect.l - pad}px`, top: `${rect.t - pad}px`, width: `${rect.w + 2 * pad}px`, height: `${rect.h + 2 * pad}px`});
    WORLD.append(frame);
    CAMERA.push({kind: ev.action, at: ev.at, rect, frame});
  }
  if (D.arrive && !CAMERA.some(c => c.kind === "zoom_out")) {
    const frame = el("div", "zoom-frame");
    Object.assign(frame.style, {left: "60px", top: "150px", width: `${D.width - 120}px`, height: `${D.height - 300}px`});
    WORLD.append(frame);
    CAMERA.push({kind: "arrive", at: 0, frame});
  }
}
function cameraOn(rect, q) {      // the transform that brings `rect` q of the way to filling the screen
  const K = Math.min(0.8 * D.width / Math.max(rect.w, 1), 0.7 * D.height / Math.max(rect.h, 1), ZOOM_MAX);
  const k = 1 + (Math.max(K, 1) - 1) * q, cx = rect.l + rect.w / 2, cy = rect.t + rect.h / 2;
  const tx = cx + (D.width / 2 - cx) * q - k * cx, ty = cy + (D.height / 2 + 20 - cy) * q - k * cy;
  return `translate(${tx}px, ${ty}px) scale(${k})`;
}
function seekCamera(t) {
  if (!WORLD) return;
  let transform = "", opacity = 1;
  for (const c of CAMERA) c.frame.style.opacity = 0;
  const out = CAMERA.find(c => c.kind === "zoom_out"), arrive = CAMERA.find(c => c.kind === "arrive");
  const zin = CAMERA.filter(c => c.kind === "zoom_in" && t >= c.at).pop();
  if (zin) {
    const p = easeInOut(progress(t, zin.at, ZOOM_SEC));
    transform = cameraOn(zin.rect, p);
    opacity = 1 - clamp((p - 0.7) / 0.3, 0, 1);
    zin.frame.style.opacity = easeInOut(progress(t, zin.at, 0.3));
  } else if (out) {
    const q = 1 - (t < out.at ? 0 : easeInOut(progress(t, out.at, ZOOM_SEC)));
    transform = q > 0 ? cameraOn(out.rect, q) : "";
    out.frame.style.opacity = q;
  } else if (arrive) {
    const p = 1 - Math.pow(1 - progress(t, 0, ARRIVE_SEC), 3), k = 0.3 + 0.7 * p;
    transform = p < 1 ? `translate(${D.width / 2 * (1 - k)}px, ${D.height / 2 * (1 - k)}px) scale(${k})` : "";
    opacity = Math.min(1, 0.2 + p);
    arrive.frame.style.opacity = 1 - p;
  }
  WORLD.style.transform = transform;
  WORLD.style.opacity = opacity;
}
window.seek = function (t) {
  const title = TITLE, subtitle = SUBTITLE;
  const ti = easeInOut(progress(t, 0, 0.6));
  if (TITLE_WORDS.length) TITLE_WORDS.forEach((w, i) => {      // word by word, sliding up
    const k = easeInOut(progress(t, 0.08 * i, 0.5)); w.style.opacity = k; w.style.transform = `translateY(${(1 - k) * 24}px)`; });
  else { title.style.opacity = ti; title.style.transform = `translateY(${(1 - ti) * -30}px)`; }
  const si = easeInOut(progress(t, 0.3, 0.6));
  subtitle.style.opacity = si; subtitle.style.transform = `translateY(${(1 - si) * 20}px)`;
  if (PROGRESS) PROGRESS.style.opacity = si;
  if (FADE) FADE.style.opacity = easeInOut(progress(t, D.ending.at, D.ending.length));
  if (SUBS) {
    const cue = D.subtitles.find(c => t >= c.at && t < c.end), text = cue ? String(cue.text) : "";
    if (SUBS.textContent !== text) SUBS.textContent = text;
    SUBS.style.opacity = cue ? 1 : 0;
  }
  const page = Math.max(0, ...PLAN.filter(p => t >= p.at).map(p => p.page));
  PLAN.forEach((p, i) => {             // each chapter slides in when it is named; the one named last is lit
    p.row.hidden = p.page !== page;    // only this page's rows
    const k = easeInOut(progress(t, p.at, 0.5));
    p.row.style.opacity = k; p.row.style.transform = `translateX(${(1 - k) * -40}px)`;
    p.row.classList.toggle("now", t >= p.at && !(PLAN[i + 1] && t >= PLAN[i + 1].at));
  });
  const footageReady = FOOTAGE ? seekFootage(t) : null;
  seekMotion(t);
  seekBackground(t);
  for (const entry of Object.values(VLEGEND))         // a legend line shows with the first of its arrows
    entry.item.style.opacity = Math.max(...entry.ids.map(id => { const e = E[id];
      return easeInOut(progress(t, e.spawn + 0.3, 0.5)) * (e.out === null ? 1 : 1 - progress(t, e.out, 0.5)); }));
  for (const e of Object.values(E)) {
    const gone = e.out === null ? 0 : progress(t, e.out, 0.5);
    const s = stateAt(e, t), k = s ? easeInOut(progress(t, s.at, 0.5)) : 0;
    const dim = is(s, "dimmed") ? 1 - 0.65 * k : 1;
    if (e.curvePath) {               // a curve draws itself along its length over CURVE_DRAW s, a dot at its head
      const p = easeInOut(progress(t, e.spawn, CURVE_DRAW));
      if (e.curveTracer) {
        const head = e.curvePath.getPointAtLength(e.curveLength * p);
        e.curveTracer.setAttribute("cx", head.x); e.curveTracer.setAttribute("cy", head.y);
        e.curveTracer.setAttribute("opacity", p > 0 && p < 1 ? 1 - gone : 0);
      }
      e.curvePath.setAttribute("stroke-dasharray", e.curveLength);
      e.curvePath.setAttribute("stroke-dashoffset", e.curveLength * (1 - p));
      e.curvePath.style.opacity = (1 - gone) * dim;
      if (e.curveHalo) {
        e.curveHalo.setAttribute("stroke-dasharray", e.curveLength); e.curveHalo.setAttribute("stroke-dashoffset", e.curveLength * (1 - p));
        e.curveHalo.style.opacity = 0.22 * (1 - gone) * dim;
      }
      if (e.curveArea) e.curveArea.style.opacity = easeInOut(progress(t, e.spawn + 1.0, 0.8)) * (1 - gone) * dim;   // once drawn
      if (e.legendItem) e.legendItem.style.opacity = easeInOut(progress(t, e.spawn + 0.6, 0.6)) * (1 - gone);
      if (!e.box) continue;
    }
    if (e.vector) {                  // a vector grows from its start point
      seekTelemetry(e, t, gone);
      const v = e.vector, p = easeOutBack(progress(t, e.spawn, 0.7)), share = e.data.vector.value_max ? vectorShare(e, t) : 1;
      const len = v.length * p * share;
      const host = e.data.vector.anchor && e.data.vector.anchor.body && E[e.data.vector.anchor.body];
      const lift = host ? floatOffset(host, t) : 0;        // on a floating thing: up with it
      v.g.setAttribute("transform", `translate(0 ${-lift})`);
      if (e.vectorLabel && share < 1) {    // its label stays beside the arrow's middle as it shrinks
        const back = v.length * p * (1 - share) / 2;
        e.vectorLabel.label.setAttribute("transform", `translate(${-v.dx * back} ${-v.dy * back})`);
      } else if (e.vectorLabel) e.vectorLabel.label.removeAttribute("transform");
      const [x, y] = e.data.xy, ex = x + v.dx * len, ey = y + v.dy * len, nx = -v.dy, ny = v.dx;
      v.line.setAttribute("x1", x); v.line.setAttribute("y1", y);
      v.line.setAttribute("x2", ex - v.dx * 22 * Math.min(p, 1)); v.line.setAttribute("y2", ey - v.dy * 22 * Math.min(p, 1));
      v.head.setAttribute("points", `${ex},${ey} ${ex - v.dx * 34 + nx * 16},${ey - v.dy * 34 + ny * 16} ${ex - v.dx * 34 - nx * 16},${ey - v.dy * 34 - ny * 16}`);
      v.g.style.opacity = (t >= e.spawn ? 1 : 0) * (1 - gone) * dim;
      continue;
    }
    // popIn: the paused keyframes, scrubbed to (t - spawn); before the spawn they show their first frame.
    e.pop.style.animationDelay = `${-(t - e.spawn)}s`;
    e.box.style.opacity = (1 - gone) * dim;
    e.box.style.translate = `0 ${-floatOffset(e, t)}px`;
    if (e.data.type === "TEX_FORMULA" && e.shape.firstElementChild) {   // written from left to right as it appears
      // cut on the right only: a formula on several rows (cases, a matrix) reaches far above and below
      // its line box, and is left uncut once written
      const hidden = 100 * (1 - easeInOut(progress(t, e.spawn + 0.15, 0.9)));
      e.shape.firstElementChild.style.clipPath = hidden > 0 ? `inset(-100vh ${hidden}% -100vh -100vw)` : "none";
    }
    if (e.ann) {                     // the badge's arrow grows towards its component after the pop
      const p = easeInOut(progress(t, e.spawn + 0.2, 0.4)), {tail, end} = e.ann;
      e.ann.line.setAttribute("x1", tail[0]); e.ann.line.setAttribute("y1", tail[1]);
      e.ann.line.setAttribute("x2", tail[0] + (end[0] - tail[0]) * p); e.ann.line.setAttribute("y2", tail[1] + (end[1] - tail[1]) * p);
      e.ann.g.style.opacity = p > 0 ? (1 - gone) * dim : 0;
    }
    if (e.lamp) {                    // fill and glow ease in (and out) over 0.4 s
      const on = blend(e, t, lit, 0.4);
      e.lamp.bulb.style.fill = `color-mix(in srgb, var(--glow) ${Math.round(on * 100)}%, var(--bulb-off))`;
      e.lamp.bulb.style.filter = on > 0 ? `drop-shadow(0 0 ${Math.round(24 * on)}px rgba(251, 191, 36, ${0.85 * on}))` : "none";
      e.lamp.halo.setAttribute("opacity", on * (0.85 + 0.15 * Math.sin(t * 4)));
    } else if (e.data.type === "SWITCH") {
      e.shape.querySelector(".lever").style.transform = `rotate(${-25 * (1 - blend(e, t, closed, 0.4))}deg)`;
    } else if (e.data.type === "AMMETER") {
      const [value] = valueAt(e, t, 1.0), reading = e.shape.querySelector(".reading");
      reading.textContent = `${frenchNumber(value, 2)} A`;
      reading.style.color = value > 0 ? "var(--primary)" : "var(--muted)";
      e.shape.style.borderColor = value > 0 ? "var(--primary)" : "";
      e.shape.style.boxShadow = is(s, "highlighted") ? "0 0 0 10px rgba(59, 130, 246, .25)" : "";   // the current is read here
    } else if (e.data.lanes) {
      seekLanes(e, t);
    } else if (e.data.seesaw) {
      seekSeesaw(e, t);
    } else if (e.data.race) {
      seekRace(e, t);
    } else if (e.data.population) {
      seekPopulation(e, t);
    } else if (e.data.tides) {
      seekTides(e, t);
    } else if (e.data.tunnel) {
      seekTunnel(e, t);
    } else if (e.data.wave) {
      seekWave(e, t);
    } else if (e.data.table) {
      seekTable(e, t);
    } else if (e.data.chain) {
      seekChain(e, t);
    } else if (e.data.simple) {
      seekSimple(e, t);
    } else if (e.data.phys) {
      seekPhys(e, t);
    } else if (e.data.mcu) {
      seekMcu(e, t);
    } else if (e.data.breadboard) {
      seekBreadboard(e, t);
    } else if (e.data.partParts) {
      seekPart(e, t);
    } else if (e.data.logic) {
      seekLogic(e, t);
    } else if (e.data.fpga) {
      seekFpga(e, t);
    } else if (!e.data.axes) {
      const active = is(s, "on") || is(s, "active") || is(s, "closed");
      if (e.data.icon && !e.data.sphere) {
        e.shape.style.background = active ? "rgba(16, 185, 129, .12)" : "";
        e.shape.querySelector("img").style.transform = is(s, "spinning") ? `rotate(${(t - s.at) * 180}deg)` : "";
      }
      e.shape.style.borderColor = active ? "var(--pos)" : (is(s, "highlighted") ? "var(--primary)" : "");
      e.shape.style.boxShadow = is(s, "highlighted") ? "0 0 0 8px rgba(59, 130, 246, .25)" : (e.baseShadow || "");   // back to its own (a lit disc)
      if (e.water) seekWater(e, t);
    }
    seekEmphasis(e, t);
    seekTelemetry(e, t, gone);
  }
  for (const w of W) {               // wires draw themselves once both ends are on screen
    const p = easeInOut(progress(t, w.start, 0.6)), drawn = w.reveal || w.path;
    drawn.setAttribute("stroke-dasharray", w.length); drawn.setAttribute("stroke-dashoffset", w.length * (1 - p));
    w.path.style.opacity = t >= Math.min(E[w.a].out ?? Infinity, E[w.b].out ?? Infinity) ? 0 : 1;
  }
  for (const j of J) j.dot.setAttribute("opacity", t >= j.at ? 1 : 0);   // once the second wire reaches it
  seekProbes(t);
  for (const f of F) {               // electrons move at 260 px/s and pulse, each a little out of step
    const on = t >= f.start && t < f.stop;
    f.dots.forEach((dot, i) => {
      if (!on) { dot.style.opacity = 0; return; }
      const along = ((t - f.start) * (f.electrons ? 150 : 260) + i * f.total / f.dots.length) % f.total;   // electrons drift slower
      dot.style.offsetDistance = `${f.electrons ? f.total - along : along}px`;
      if (!f.electrons) dot.setAttribute("r", 8 + 2.5 * (0.5 + 0.5 * Math.sin(2 * Math.PI * 1.5 * t + i)));
      dot.style.opacity = Math.min(1, (t - f.start) / 0.3);
    });
  }
  seekCamera(t);
  return footageReady;               // the renderer's evaluate waits for the film's frame (null without one)
};
// Layout needs the real size of every box, KaTeX formulas included: wait for the fonts.
// Feasibility check on the real boxes, once everything is placed: what still overlaps, sits in the
// title zone or leaves the frame. The renderer reports it in render_manifest.json.
function layoutConflicts() {
  const found = [], header = below(D.subtitle ? 200 : 150);
  const items = Object.values(E).filter(e => e.box && !e.inSide && !e.placedForMotion).map(e => ({id: e.data.id, r: boxOf(e),
    shown: [e.spawn ?? 0, e.out ?? Infinity],
    origin: e.ann ? e.ann.tip : (e.anchorHost ? e.data.xy : null), rides: e.data.rides, badge: !!e.ann,
    // a graph's drawn part: its axes and curves, without the empty margins around them (a badge may sit there)
    plot: e.data.axes ? (p => ({l: p.l + PAD / 2, t: p.t + PAD / 2, r: p.r - PAD / 2, b: p.b - PAD / 2}))(plotOf(e)) : null}));   // an anchored body or object sits in its graph on purpose
  for (const e of Object.values(E)) if (e.vector && e.vector.labelBox) items.push({id: `${e.data.id} (label)`, r: e.vector.labelBox, origin: e.data.xy});
  for (const e of Object.values(E)) if (e.pointsAtNothing) found.push(`${e.data.id} points at nothing`);
  for (const {id, r} of items) {
    if (r.t < header - 0.5) found.push(`${id} enters the title zone`);
    if (r.l < -0.5 || r.r > D.width + 0.5 || r.b > FLOOR + 0.5) found.push(`${id} leaves the frame`);
  }
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j];
    const holds = (x, p) => p && p[0] >= x.r.l - 40 && p[0] <= x.r.r + 40 && p[1] >= x.r.t - 40 && p[1] <= x.r.b + 40;
    if (holds(a, b.origin) || holds(b, a.origin)) continue;      // an arrow's label next to what it points at
    if (a.rides === b.id || b.rides === a.id) continue;          // a passenger beside its host, on purpose (placePassengers)
    if (a.shown && b.shown && (a.shown[1] <= b.shown[0] || b.shown[1] <= a.shown[0])) continue;   // never on screen together
    const ra = a.plot && !b.plot ? a.plot : a.r, rb = b.plot && !a.plot ? b.plot : b.r;   // a graph's empty margins may hold anything
    if (Math.min(ra.r, rb.r) > Math.max(ra.l, rb.l) + 1 && Math.min(ra.b, rb.b) > Math.max(ra.t, rb.t) + 1)
      found.push(`${a.id} overlaps ${b.id}`);
  }
  return found;
}
document.fonts.ready.then(() => {
  locateSideItems(); layoutZones(); fitToRoom(); spreadOut(); shrinkToFit(); anchorVectors(); drawWires(); placeVectorLabels(); placeAnnotations(); buildFlows(); buildProbes();
  window.layoutConflicts = layoutConflicts();
  buildCamera();
  window.seek(0); hideCoveredTicks(); window.sceneReady = true;
});
</script></body></html>
"""

# Layout templates (agent004 writes "layout_template" on each storyboard scene). Each page is the
# same template, script and animations included; only the grid differs: its name on #stage, a few
# CSS rules, and its static frame (the panels, the backdrop).
ROW_STYLE = "  #side { flex-direction:row; flex-wrap:wrap; justify-content:center; align-items:flex-start; }\n"
COMPARISON_STYLE = ROW_STYLE + """  .comparison-panel { position:absolute; top:200px; bottom:24px; width:calc(50% - 60px); box-sizing:border-box;
                      border:2px solid var(--border); border-radius:var(--radius); background:color-mix(in srgb, var(--card) 55%, transparent); }
  .comparison-panel[data-panel="A"] { left:40px; } .comparison-panel[data-panel="B"] { right:40px; }
  .comparison-panel .panel-title { height:56px; line-height:56px; text-align:center; font-size:30px; font-weight:700;
                                   color:var(--muted); border-bottom:2px solid var(--border); }
"""
COMPARISON_HTML = ('<div class="comparison-panel" data-panel="A"><div class="panel-title">A</div></div>'
                   '<div class="comparison-panel" data-panel="B"><div class="panel-title">B</div></div>')
ANALOGY_STYLE = ROW_STYLE + """  .fullscreen-svg { position:absolute; left:40px; top:180px; width:calc(100% - 80px); height:876px; }
  #stage[data-layout="analogy_fullscreen"] .icon { width:190px; height:190px; padding:26px; }
  #stage[data-layout="analogy_fullscreen"] .label { font-size:36px; max-width:460px; }
"""
ANALOGY_HTML = ('<svg class="fullscreen-svg" data-backdrop><defs><linearGradient id="analogyBackdrop" x1="0" y1="0" x2="0" y2="1">'
                '<stop offset="0" style="stop-color:color-mix(in srgb, var(--accent) 10%, var(--card))"/>'
                '<stop offset="1" style="stop-color:color-mix(in srgb, var(--card) 70%, transparent)"/></linearGradient></defs>'
                '<rect x="1" y="1" width="99.8%" height="99.6%" rx="24" fill="url(#analogyBackdrop)" '
                'style="stroke:color-mix(in srgb, var(--accent) 30%, var(--border))" stroke-width="2"/></svg>')   # the theme's colours
STYLE_END = "</style></head>"


def layout_page(name, style="", html=""):
    return (PAGE_TEMPLATE.replace("@@LAYOUT@@", name).replace("@@LAYOUT_HTML@@", html)
            .replace(STYLE_END, style + STYLE_END, 1))


PAGE_CIRCUIT = layout_page("circuit")                                     # the original page
PAGE_COMPARISON = layout_page("comparison", COMPARISON_STYLE, COMPARISON_HTML)
PAGE_ANALOGY_FULLSCREEN = layout_page("analogy_fullscreen", ANALOGY_STYLE, ANALOGY_HTML)
PAGES = {"circuit": PAGE_CIRCUIT, "comparison": PAGE_COMPARISON, "analogy_fullscreen": PAGE_ANALOGY_FULLSCREEN}
DEFAULT_LAYOUT = "circuit"


def select_page(layout_template):
    """The page for a layout template; PAGE_CIRCUIT when it is missing or unknown."""
    return PAGES.get(layout_template, PAGE_CIRCUIT)


def scene_layout(scene):
    """(layout template to render with, why it differs from the scene's, or None). A storyboard without
    "layout_template" (older runs) gets "circuit"; an instrument needs the circuit page's column."""
    asked = scene.get("layout_template") or DEFAULT_LAYOUT
    if asked not in PAGES:
        return DEFAULT_LAYOUT, f"unknown layout_template {asked!r}: circuit page"
    brief = scene.get("visual_brief") or {}
    instruments = {t.value for t in INSTRUMENT_TYPES}
    if asked != DEFAULT_LAYOUT and any(e.get("type") in instruments for e in brief.get("entities", [])):
        return DEFAULT_LAYOUT, f"layout_template {asked!r} has no instrument column, the scene has an instrument: circuit page"
    return asked, None


def build_page(data):
    """The scene's standalone HTML: markers filled in one pass, so no inserted text is re-read."""
    katex = katex_assets()
    parts = {"WIDTH": str(WIDTH), "HEIGHT": str(HEIGHT),
             "DATA": json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
             "KATEX": (f"<style>{katex[0]}</style><script>{katex[1]}</script>" if katex else "")
                      + f"<style>{font_face_css(data.get('fonts') or [])}</style>"}
    return re.sub(r"@@(WIDTH|HEIGHT|DATA|KATEX)@@", lambda m: parts[m.group(1)], select_page(data.get("layout")))


def open_scene(page, html_path):
    """Load a scene page and wait until it is laid out (fonts loaded, components placed, wires routed)."""
    page.goto("file://" + html_path, wait_until="load", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_function("window.sceneReady === true", timeout=PAGE_TIMEOUT_MS)


def render_html_visual(page, html_path, duration, visual_path):
    """Load the page, screenshot every frame (seek(i / FPS)) and pipe the JPEGs into ffmpeg.
    Returns the layout conflicts the page measured (empty list = nothing overlaps)."""
    open_scene(page, html_path)
    conflicts = page.evaluate("window.layoutConflicts || []")
    frames = max(1, round(duration * FPS))
    encoder = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe",
                                "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-", *VIDEO_CODEC, visual_path],
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            page.evaluate(f"window.seek({i / FPS})")
            encoder.stdin.write(page.screenshot(type="jpeg", quality=JPEG_QUALITY))
    finally:
        encoder.stdin.close()
        error = encoder.stderr.read().decode(errors="replace")
        encoder.wait(timeout=600)
    if encoder.returncode != 0:
        raise RuntimeError(f"ffmpeg failed while encoding frames: {error.strip()[-300:]}")
    return conflicts


# The plan, announced right after the hook (scene 1) so the viewer knows where the video goes: a scene
# of its own. agent003 writes it in script.json ("plan"): a spoken narration, as a teacher announces
# the lesson, and for each later scene what it will show, with the words ("cue") that announce it;
# each line appears when the voice says them. Without a usable one (older scripts, a plan that does
# not match the scenes), it is built here from the scenes' titles ("D'abord, ... Et enfin, ...").
# From then on each scene shows where it is in the plan (D.progress, top right).
SCENE_SOUNDS = {"spawn": "pop", "set_value": "tick"}   # the sound effect of an action (app/render/soundtrack.py)
PLAN_AFTER = 1                     # the plan comes after this many scenes
PLAN_MIN_CHAPTERS = 2              # fewer chapters: no plan scene
PLAN_TITLE, PLAN_SUBTITLE = "Au programme", "Le plan de la vidéo"
PLAN_CONNECTORS = ("D'abord", "Ensuite", "Puis", "Après cela", "Puis")


def scene_title(scene, number):
    overlay = (scene.get("visual_brief") or {}).get("text_overlay") or {}
    return plain_math(str(overlay.get("title") or "").strip()) or f"Étape {number}"


def plan_chapters(storyboard):
    """[(number, title)] of the scenes after the hook, or [] when the video is too short for a plan."""
    chapters = [(number, scene_title(scene, number)) for number, scene in enumerate(storyboard["scenes"], start=1)
                if number > PLAN_AFTER]
    return chapters if len(chapters) >= PLAN_MIN_CHAPTERS else []


def plan_lines(chapters):
    """[(connector, title)]: "D'abord", "Ensuite", "Puis"..., "Et enfin" for the last."""
    return [("Et enfin" if i == len(chapters) - 1 else PLAN_CONNECTORS[min(i, len(PLAN_CONNECTORS) - 1)], title.rstrip(" .:;"))
            for i, (_, title) in enumerate(chapters)]


def plan_narration(chapters):
    """'Au programme. D'abord, <title>. Ensuite, <title>. ... Et enfin, <title>.'"""
    return "Au programme. " + " ".join(f"{lead}, {title}" + ("" if title.endswith(("?", "!")) else ".")
                                       for lead, title in plan_lines(chapters))


def script_plan(script, storyboard):
    """agent003's plan as {"narration", "items": [(number, text, cue)]}, or None when it does not give
    one line per scene after the hook, in the storyboard's order."""
    plan = script.get("plan") if isinstance(script, dict) else None
    if not isinstance(plan, dict) or not str(plan.get("narration") or "").strip():
        return None
    numbers = {str(scene.get("scene_id")): number for number, scene in enumerate(storyboard["scenes"], start=1)}
    items = [(numbers.get(str(part.get("scene_id"))), plain_math(str(part.get("text") or "").strip()), str(part.get("cue") or ""))
             for part in plan.get("parts") or [] if isinstance(part, dict)]
    if [n for n, _, _ in items] != list(range(PLAN_AFTER + 1, len(storyboard["scenes"]) + 1)) or not all(t for _, t, _ in items):
        return None
    return {"narration": str(plan["narration"]).strip(), "items": items, "source": "script"}


def video_plan(script, storyboard):
    """The plan to show: agent003's, else one from the titles; None for a video too short for a plan."""
    chapters = plan_chapters(storyboard)
    if not chapters:
        return None
    return script_plan(script, storyboard) or {
        "narration": plan_narration(chapters), "source": "titles",
        "items": [(n, title, f"{lead}, {title}") for (n, title), (lead, _) in zip(chapters, plan_lines(chapters))]}


def plan_times(items, spoken, voice):
    """When each line is announced (its cue's first word), in order; spread over the voice when its
    cue is not found."""
    words = [(at, word) for at, text in (spoken or []) for _, word in narration_words(text)]
    times, position = [], 0
    for i, (_, _, cue) in enumerate(items):
        index = find_cue(words, normalize_text_for_tts(cue), position) if words and cue else None
        if index is not None:
            position = index + 1
            times.append(max(words[index][0], times[-1] + 0.3 if times else 0.0))
        else:
            times.append(max(0.8 + (voice - 1.2) * i / max(len(items), 1), times[-1] + 0.3 if times else 0.0))
    return times


def once_zoomed(brief, zoomed_in):
    """A TUNNEL zooms in from its circuit in the first scene showing one; later ones start zoomed in
    (their initial_state "zoom" set to false). Returns whether one has zoomed in by now."""
    for entity in brief.get("entities") or []:
        if entity.get("type") == "TUNNEL":
            if zoomed_in:
                entity["initial_state"] = {**(entity.get("initial_state") or {}), "zoom": False}
            zoomed_in = zoomed_in or (entity.get("initial_state") or {}).get("zoom") is not False
    return zoomed_in


def plan_page_data(plan, spoken, voice, total, style):
    brief = {"entities": [], "actions": [], "connections": [], "text_overlay": {"title": PLAN_TITLE, "subtitle": PLAN_SUBTITLE}}
    data = page_data(brief, total, None, None, DEFAULT_LAYOUT, None, style, 0)
    data["plan"] = [{"number": n, "title": t, "at": round(at, 2)}
                    for (n, t, _), at in zip(plan["items"], plan_times(plan["items"], spoken, voice))]
    return data


def render_video(storyboard, script, video_path, folder, warnings, style=None, burn_subtitles=True, sound=None):
    """1. every voice-over, 2. every picture in one browser session, 3. join and concatenate, and the
    subtitles in folder/subtitles.srt (burnt into the picture too, unless burn_subtitles is False).
    `sound` {"channel", "music", "effects", "voice_id"}: the music bed and sound effects mixed under the
    voice (app/render/soundtrack.py), what was made going into sound["made"]; the channel's ElevenLabs
    voice (None: the default)."""
    from playwright.sync_api import sync_playwright

    temp_dir = os.path.join(folder, "temp_html")
    shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir)
    script_scenes = {s.get("scene_id"): s for s in script["scenes"]}
    try:
        # 1. Voices first (outside Playwright: see NOTES). Their length sets each scene's length.
        jobs = []
        for number, scene in enumerate(storyboard["scenes"], start=1):
            name = f"scene_{number:03d}"
            source = script_scenes.get(scene["scene_id"], {})
            narration = str(scene_field(source, "narration_text", "narration") or "").strip()
            if not narration:
                raise RuntimeError(f"{name} (scene_id {scene['scene_id']}): no narration in script.json")
            audio_path = os.path.join(temp_dir, name + ".mp3")
            spoken = []                    # when each word is said: the actions' cues are timed on it
            engine = {}
            voice = generate_voice(narration, audio_path, spoken, engine, (sound or {}).get("voice_id"))
            jobs.append({"name": name, "scene": scene, "source": source, "audio": audio_path, "voice": voice, "spoken": spoken,
                         "subtitles": subtitle_cues(narration, spoken, voice, plain_math),
                         "total": voice + TAIL_PAUSE, "visual": os.path.join(temp_dir, name + "_visual.mp4"),
                         "entry": {"scene_id": scene["scene_id"], "title": scene_title(scene, number), "voice_sec": round(voice, 2),
                                   "voice_engine": engine["used"], "voice_fallback": engine["fallback"],
                                   "status": "ok", "error": None}})
        plan = video_plan(script, storyboard)
        if plan:                           # the plan, after the hook
            audio_path = os.path.join(temp_dir, "plan.mp3")
            spoken, engine = [], {}
            voice = generate_voice(plan["narration"], audio_path, spoken, engine, (sound or {}).get("voice_id"))
            jobs.insert(PLAN_AFTER, {"name": "plan", "plan": plan, "audio": audio_path, "voice": voice, "spoken": spoken,
                                     "subtitles": subtitle_cues(plan["narration"], spoken, voice, plain_math),
                                     "total": voice + TAIL_PAUSE, "visual": os.path.join(temp_dir, "plan_visual.mp4"),
                                     "entry": {"scene_id": "plan", "title": PLAN_TITLE, "plan_source": plan["source"],
                                               "voice_sec": round(voice, 2),
                                               "voice_engine": engine["used"], "voice_fallback": engine["fallback"],
                                               "status": "ok", "error": None}})
        total_chapters = len(storyboard["scenes"])
        jobs[-1]["total"] += END_HOLD      # the video ends: its last picture held, then a fade, not a cut
        # Real film behind a scene (agent004's "footage", the hook): found (app/render/footage.py) and cut
        # into the scene's frames here, before the browser starts. No clip: the scene is drawn without one.
        for job in jobs:
            wanted = (job.get("scene") or {}).get("footage")
            if not wanted:
                continue
            try:
                clip = film.find_clip((wanted or {}).get("query"))
                folder_name = job["name"] + "_footage"
                count = film.cut_frames(clip["file"], job["total"], os.path.join(temp_dir, folder_name), FPS, WIDTH, HEIGHT, ffmpeg)
                job["footage"] = {"dir": folder_name, "count": count, "fps": FPS}
                job["entry"]["footage"] = film.credit(clip)
            except Exception as exc:       # no clip found, network, ffmpeg: the scene keeps its drawing alone
                warnings.append(f"{job['name']}: no footage for {wanted!r}: {exc}")
        # 2. Pictures: one page per scene, one screenshot per frame.
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            number = 0
            zoomed_in = False           # a TUNNEL zooms in the first time only, not again in later scenes
            arrive = False              # the scene before ended on a zoom_in: this one (its inside) arrives from it
            for job in jobs:
                try:
                    html_path = os.path.join(temp_dir, job["name"] + ".html")
                    if job.get("plan"):
                        data = plan_page_data(job["plan"], job["spoken"], job["voice"], job["total"], style)
                        if burn_subtitles:
                            data["subtitles"] = job["subtitles"]
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(build_page(data))
                        job["sounds"] = [(item["at"], "pop") for item in data["plan"]]
                        job["entry"]["layout_conflicts"] = render_html_visual(page, html_path, job["total"], job["visual"])
                        arrive = False
                        continue
                    number += 1
                    layout, note = scene_layout(job["scene"])
                    job["entry"]["layout_template"] = layout
                    if note:
                        warnings.append(f"{job['name']}: {note}")
                    zoomed_in = once_zoomed(job["scene"]["visual_brief"], zoomed_in)
                    data = page_data(job["scene"]["visual_brief"], job["total"],
                                     scene_field(job["source"], "duration_sec", "duration_seconds"), job["spoken"],
                                     layout, job["scene"].get("panel_titles"), style, number)
                    data["arrive"], arrive = arrive, any(isinstance(a, dict) and a.get("action") == "zoom_in"
                                                         for a in job["scene"]["visual_brief"].get("actions") or [])
                    if burn_subtitles:
                        data["subtitles"] = job["subtitles"]
                    if job.get("footage"):
                        data["footage"] = job["footage"]
                    if job is jobs[-1]:
                        data["ending"] = {"at": round(job["total"] - END_FADE, 2), "length": END_FADE}
                    if plan and number > PLAN_AFTER:       # where this scene is in the plan
                        data["progress"] = {"current": number - PLAN_AFTER, "total": total_chapters - PLAN_AFTER}
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(build_page(data))
                    job["sounds"] = [(ev["at"], SCENE_SOUNDS[ev.get("action")]) for ev in data.get("events", [])
                                     if ev.get("action") in SCENE_SOUNDS and is_number(ev.get("at"))]
                    conflicts = render_html_visual(page, html_path, job["total"], job["visual"])
                    job["entry"]["layout_conflicts"] = conflicts
                    if conflicts:
                        warnings.append(f"{job['name']}: layout conflicts: {'; '.join(conflicts[:3])}")
                except Exception as exc:     # page error, browser crash...: error screen, keep going
                    print(f"--- {AGENT}: {job['name']} rendered as an error screen: {exc}", file=sys.stderr)
                    warnings.append(f"{job['name']}: {exc}")
                    job["entry"].update(status="error_screen", error=str(exc))
                    make_error_visual(f"{job['name']}\n{exc}", job["total"], job["visual"])
            browser.close()
        # 3. Picture + voice per scene, then the whole video.
        clips, scenes, start = [], [], 0.0
        for job in jobs:
            clip_path = os.path.join(temp_dir, job["name"] + ".mp4")
            mux_scene(job["visual"], job["audio"], job["total"], clip_path)
            duration = media_duration(clip_path)
            job["entry"].update(start_sec=round(start, 2), end_sec=round(start + duration, 2),
                                duration_sec=round(duration, 2))
            start += duration
            clips.append(clip_path)
            scenes.append(job["entry"])
        beds = []
        if sound and (sound.get("music") or sound.get("effects")):
            events = [(job["entry"]["start_sec"] + at, kind) for job in jobs for at, kind in job.get("sounds", [])]
            events += [(job["entry"]["start_sec"] - 0.3, "whoosh") for job in jobs[1:]]   # a scene gives way to the next
            sound["made"], beds = soundtrack(start, events, sound.get("channel"), os.path.join(temp_dir, "music.wav"),
                                             os.path.join(temp_dir, "effects.wav"), sound.get("music"), sound.get("effects"),
                                             sound.get("style"))
        concat_scenes(clips, os.path.join(temp_dir, "scenes.txt"), video_path, beds)
        with open(os.path.join(folder, "subtitles.srt"), "w", encoding="utf-8") as f:   # the whole video's lines
            f.write(srt([{**cue, "at": cue["at"] + job["entry"]["start_sec"], "end": cue["end"] + job["entry"]["start_sec"]}
                         for job in jobs for cue in job["subtitles"]]))
        return scenes
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    video_path = os.path.join(folder, "video.mp4")
    manifest_path = os.path.join(folder, "render_manifest.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["storyboard.json", "script.json", "qa.json"])
    storyboard = load_json(os.path.join(folder, "storyboard.json"))
    script = load_json(os.path.join(folder, "script.json"))
    qa = load_json(os.path.join(folder, "qa.json"))
    if not (storyboard.get("scenes") and script.get("scenes") and qa):
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error="missing storyboard, script or qa")
    if qa.get("verdict") != "pass":
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error="QA verdict is not pass")
    brief_error = check_briefs(storyboard)
    if brief_error:
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error=brief_error)

    warnings, scenes, duration = [], [], None
    sound = {"channel": channel_id, "music": settings.get("background_music", True), "effects": settings.get("sound_effects", True),
             "style": settings.get("music_style_by_channel", {}).get(channel_id) or settings.get("music_style", "ambient"),
             "voice_id": str((settings.get("voice_by_channel", {}).get(channel_id) or {}).get("voice_id") or "").strip() or None}
    try:
        if settings.get("dry_run", True):
            with open(video_path, "wb") as f:
                f.write(PLACEHOLDER)
            renderer_used = "dry_run"
            warnings.append("dry_run: placeholder video written")
        else:
            missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
            if missing:
                raise RuntimeError(f"{' and '.join(missing)} not found on PATH")
            scenes = render_video(storyboard, script, video_path, folder, warnings, channel_style(channel_id),
                                  settings.get("burn_subtitles", True), sound)
            duration = round(media_duration(video_path), 2)
            renderer_used = "html_playwright"
    except ImportError:
        return finish(channel_id, AGENT, "render", "critical", manifest_path,
                      error="playwright is not installed: pip install playwright && playwright install chromium")
    except Exception as exc:  # browser missing, edge-tts down, ffmpeg error...
        print(f"--- {AGENT}: render failed for {channel_id}: {exc!r}", file=sys.stderr)
        return finish(channel_id, AGENT, "render", "critical", manifest_path, error=f"render failed: {exc!r}")

    voice_engine = voice_report(scenes, warnings)
    status = "not_healthy" if warnings else "healthy"
    manifest = {"video_path": video_path, "duration": duration if duration is not None else script.get("total_duration_sec"),
                "resolution": f"{WIDTH}x{HEIGHT}", "renderer_used": renderer_used, "soundtrack": sound.get("made"),
                "rendered_at": utc_now(), "status": status, "voice_engine": voice_engine, "scenes": scenes}
    if os.path.exists(video_path) and renderer_used != "skip":   # written by ffmpeg (or the dry-run placeholder)
        provenance.register_artifact(run_id, channel_id, "video.mp4", AGENT)
    if renderer_used == "html_playwright":
        manifest["subtitles_path"] = os.path.join(folder, "subtitles.srt")
        provenance.register_artifact(run_id, channel_id, "subtitles.srt", AGENT)
    save_json(manifest_path, manifest)
    provenance.register_artifact(run_id, channel_id, "render_manifest.json", AGENT)
    return finish(channel_id, AGENT, "render", status, manifest_path, data={**manifest, "warnings": warnings})


if __name__ == "__main__":
    run_standalone(run)
