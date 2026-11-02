"""
Check vectors anchored on a curve (VECTOR_ARROW "anchor": {"curve": id, "t" or "x"}, with "direction"
TANGENT / CENTER / OUTWARD; models/visual_brief_schema.py, app/curve_math.py). Before, a vector was
placed by a guessed scene position: the velocity and the gravity of a satellite floated off its orbit
(the breeze_(math) run of 2026-10-31, scenes 5 and 6).
  1. schema: anchored vectors accepted; refused with a clear message: TANGENT without an anchor, an
     unknown curve, "x" on a parametric curve, t outside t_min..t_max, an anchor that is not a dict
  2. agent010 (Chromium, measured on what is drawn): a satellite at 45° on an orbit; its velocity
     (TANGENT) starts on the orbit and runs along it, anticlockwise (the way t grows); its gravity
     (CENTER) starts there too and points at the orbit's centre
  3. agent010: a velocity on a parabola y = f(x) at x = 2 follows the curve's slope there
  4. agent005: a QA patch anchors a floating vector, then sets its direction to TANGENT
Prints PASS or FAIL per case. Cases 2 and 3 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_vector_anchor.py
"""

import copy
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from pydantic import ValidationError                              # noqa: E402

from app.agent import agent010_html_renderer as renderer          # noqa: E402
from models.visual_brief_schema import SceneVisualBrief           # noqa: E402

ANGLE_TOLERANCE = 3.0      # degrees
ON_CURVE_PX = 3.0
AXES = {"id": "ax", "type": "AXES_GRAPH", "position": [0, -0.07, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}}
ORBIT = {"id": "orbit", "type": "CURVE_PLOT", "position": [0, -0.07, 0],
         "initial_state": {"x_func": "3*np.cos(t)", "y_func": "3*np.sin(t)", "axes": "ax", "label": "Orbite"}}
PARABOLA = {"id": "p", "type": "CURVE_PLOT", "position": [0, -0.15, 0], "initial_state": {"func": "2 - 0.15*x**2", "axes": "ax"}}


def vector(entity_id, anchor, direction, label):
    return {"id": entity_id, "type": "VECTOR_ARROW", "position": [4, 2, 0],      # a wrong guess: the anchor wins
            "initial_state": {"anchor": anchor, "direction": direction, "length": 1.5, "label": label}}


def scene(entities):
    return {"scene_id": "1", "text_overlay": {"title": "Ancrage"}, "connections": [], "entities": entities,
            "actions": [{"at": 0.2 + 0.2 * i, "action": "spawn", "target": e["id"]} for i, e in enumerate(entities)]}


SATELLITE = scene([AXES, ORBIT, vector("vel", {"curve": "orbit", "t": 0.785}, "TANGENT", "Vitesse"),
                   vector("grav", {"curve": "orbit", "t": 0.785}, "CENTER", "Gravité")])


def angle_between(a, b):
    dot = (a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_schema():
    problems, notes = [], []
    try:
        SceneVisualBrief.model_validate(SATELLITE)
    except ValidationError as exc:
        problems.append(f"the anchored satellite was refused: {exc}")
    bad = {"TANGENT without an anchor": {"direction": "TANGENT"},
           "an unknown curve": {"anchor": {"curve": "nope", "t": 0}},
           "x on a parametric curve": {"anchor": {"curve": "orbit", "x": 1}},
           "t outside t_min..t_max": {"anchor": {"curve": "orbit", "t": 9}},
           "an anchor that is not a dict": {"anchor": "orbit"}}
    for label, state in bad.items():
        brief = scene([AXES, ORBIT, {"id": "v", "type": "VECTOR_ARROW", "position": [0, 0, 0], "initial_state": state}])
        try:
            SceneVisualBrief.model_validate(brief)
            problems.append(f"accepted: {label}")
        except ValidationError as exc:
            notes.append(f"{label}: " + next(line.strip() for line in str(exc).splitlines() if "Value error" in line)[:130])
    return report("1. schema: anchored vectors accepted, wrong anchors refused", problems, notes)


MEASURE = """() => {
  const stage = document.getElementById("stage").getBoundingClientRect();
  const toStage = (el, x, y) => { const p = new DOMPoint(x, y).matrixTransform(el.getScreenCTM()); return [p.x - stage.left, p.y - stage.top]; };
  const curves = {};
  for (const e of Object.values(E).filter(e => e.curvePath)) { const L = e.curvePath.getTotalLength(), pts = [];
    for (let i = 0; i <= 2000; i++) { const p = e.curvePath.getPointAtLength(L * i / 2000); pts.push(toStage(e.curvePath, p.x, p.y)); }
    curves[e.data.id] = pts; }
  const vectors = {};
  for (const e of Object.values(E).filter(e => e.vector)) { const l = e.vector.line, [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map(k => +l.getAttribute(k));
    vectors[e.data.id] = [toStage(l, x1, y1), toStage(l, x2, y2)]; }
  return {curves, vectors};
}"""


def measure(brief):
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            page.evaluate("window.seek(5.8)")
            return page.evaluate(MEASURE)
        finally:
            browser.close()


def nearest(points, p):
    """(distance, index) of the curve point nearest to p."""
    return min((math.hypot(q[0] - p[0], q[1] - p[1]), i) for i, q in enumerate(points))


def local_slope(points, index):
    a, b = points[max(index - 5, 0)], points[min(index + 5, len(points) - 1)]
    return [b[0] - a[0], b[1] - a[1]]


def case_html_orbit():
    data = measure(SATELLITE)
    orbit, problems, notes = data["curves"]["orbit"], [], []
    xs, ys = [p[0] for p in orbit], [p[1] for p in orbit]
    centre = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    for name in ("vel", "grav"):
        start, end = data["vectors"][name]
        gap, index = nearest(orbit, start)
        if gap > ON_CURVE_PX:
            problems.append(f"{name} starts {gap:.1f} px off the orbit")
        way = [end[0] - start[0], end[1] - start[1]]
        if name == "vel":
            off = min(angle_between(way, local_slope(orbit, index)), angle_between(way, [-v for v in local_slope(orbit, index)]))
            radial = [start[0] - centre[0], start[1] - centre[1]]
            anticlockwise = radial[0] * way[1] - radial[1] * way[0] < 0      # screen y points down
            notes.append(f"velocity: {gap:.1f} px from the orbit, {off:.1f}° off its tangent, "
                         f"{'anticlockwise' if anticlockwise else 'clockwise'}")
            if off > ANGLE_TOLERANCE or not anticlockwise:
                problems.append("the velocity does not run along the orbit, anticlockwise")
        else:
            off = angle_between(way, [centre[0] - start[0], centre[1] - start[1]])
            notes.append(f"gravity: {gap:.1f} px from the orbit, {off:.1f}° off the centre")
            if off > ANGLE_TOLERANCE:
                problems.append("the gravity does not point at the orbit's centre")
    return report("2. agent010: a satellite's velocity along its orbit, its gravity to the centre", problems, notes)


def case_html_parabola():
    data = measure(scene([{**AXES, "position": [0, -0.15, 0]}, PARABOLA, vector("v", {"curve": "p", "x": 2}, "TANGENT", "Vitesse")]))
    curve, (start, end) = data["curves"]["p"], data["vectors"]["v"]
    gap, index = nearest(curve, start)
    off = angle_between([end[0] - start[0], end[1] - start[1]], local_slope(curve, index))
    problems = ([f"starts {gap:.1f} px off the curve"] if gap > ON_CURVE_PX else []) + \
               ([f"{off:.1f}° off the curve's slope"] if off > ANGLE_TOLERANCE else [])
    return report("3. agent010: a velocity on y = f(x) follows its slope", problems,
                  [f"{gap:.1f} px from the curve, {off:.1f}° off its slope"])


def case_patch():
    from app.agent import agent005_educationqa as agent005
    floating = copy.deepcopy(SATELLITE)
    floating["entities"][2]["initial_state"] = {"direction": "UP", "label": "Vitesse"}   # off the orbit, as in the run
    briefs, corrections = {"1": floating}, []
    agent005.apply_patches(briefs, [
        {"op": "set_initial_state", "scene_id": "1", "entity_id": "vel", "key": "anchor", "value": {"curve": "orbit", "t": 0.785}},
        {"op": "set_initial_state", "scene_id": "1", "entity_id": "vel", "key": "direction", "value": "tangent"}], corrections)
    state = briefs["1"]["entities"][2]["initial_state"]
    ok = state.get("anchor") == {"curve": "orbit", "t": 0.785} and state.get("direction") == "TANGENT"
    return report("4. agent005: a patch anchors a floating vector, then makes it TANGENT", [] if ok else [f"{state}; {corrections}"],
                  corrections)


try:
    import playwright  # noqa: F401
except ImportError:
    sys.exit("FAIL  Playwright is not installed (pip install playwright && playwright install chromium)")
results = [case_schema(), case_html_orbit(), case_html_parabola(), case_patch()]
sys.exit(0 if all(results) else 1)
