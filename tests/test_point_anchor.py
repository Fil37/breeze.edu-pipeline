"""
Check anchors on a point of a graph: "anchor": {"axes": "<AXES_GRAPH id>", "x", "y"} for an OBJECT, a
BODY or a VECTOR_ARROW. Before, an OBJECT was placed by a guessed scene position: in the breeze_(math)
run of 2026-10-31 (17:25), the Earth landed beside the graph, the ISS orbited nothing, its gravity
pointed at an empty centre, and the QA shifted the orbit by guesswork.
  1. schema: point anchors accepted on OBJECT, BODY, VECTOR_ARROW; refused with a message: TANGENT on a
     point anchor, unknown axes, an OBJECT anchored on a curve
  2. agent010 page (Chromium, measured on what is drawn): the Earth's icon is centred on the orbit's
     centre, the ISS's gravity (CENTER) points at it, and nothing is reported overlapping
  3. agent010: an anchored object's guessed position pushes nothing away (the graph stays where it is)
  4. agent010: the vectors riding on one body get one colour each, their labels in it
  5. agent005: a patch anchors a planet at its orbit's centre
Prints PASS or FAIL per case. Cases 2 and 3 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_point_anchor.py
"""

import copy
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from pydantic import ValidationError                                    # noqa: E402

from app.agent import agent005_educationqa as agent005                  # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402

AXES = {"id": "ax", "type": "AXES_GRAPH", "position": [0, -0.07, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}}
ORBIT = {"id": "orbit", "type": "CURVE_PLOT", "position": [0, -0.07, 0],
         "initial_state": {"x_func": "2.5*np.cos(t)", "y_func": "2.5*np.sin(t)", "axes": "ax", "label": "Orbite"}}
EARTH = {"id": "earth", "type": "OBJECT", "position": [4.5, 1.5, 0],          # a wrong guess: the anchor wins
         "initial_state": {"icon": "earth", "label": "Terre", "anchor": {"axes": "ax", "x": 0, "y": 0}}}
ISS = {"id": "iss", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "ISS", "anchor": {"curve": "orbit", "t": 2.4}}}
GRAVITY = {"id": "grav", "type": "VECTOR_ARROW", "position": [0, 0, 0],
           "initial_state": {"anchor": {"body": "iss"}, "direction": "CENTER", "length": 1.0, "label": "Gravité"}}
SPEED = {"id": "vel", "type": "VECTOR_ARROW", "position": [0, 0, 0],
         "initial_state": {"anchor": {"body": "iss"}, "direction": "TANGENT", "length": 1.0, "label": "Vitesse"}}


def scene(entities):
    return {"scene_id": "1", "text_overlay": {"title": "Orbite"}, "connections": [], "entities": copy.deepcopy(entities),
            "actions": [{"at": 0.2 + 0.2 * i, "action": "spawn", "target": e["id"]} for i, e in enumerate(entities)]}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_schema():
    problems, notes = [], []
    point = {"axes": "ax", "x": 1, "y": -1}
    good = [EARTH, {**ISS, "initial_state": {"anchor": point}},
            {"id": "w", "type": "VECTOR_ARROW", "position": [0, 0, 0], "initial_state": {"anchor": point, "direction": "DOWN"}}]
    for entity in good:
        try:
            SceneVisualBrief.model_validate(scene([AXES, ORBIT, entity]))
        except ValidationError as exc:
            problems.append(f"{entity['type']} refused: {exc}")
    bad = {"TANGENT on a point anchor": {"id": "w", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                                         "initial_state": {"anchor": point, "direction": "TANGENT"}},
           "unknown axes": {**EARTH, "initial_state": {"icon": "earth", "anchor": {"axes": "nope", "x": 0, "y": 0}}},
           "an OBJECT on a curve": {**EARTH, "initial_state": {"icon": "earth", "anchor": {"curve": "orbit", "t": 0}}}}
    for label, entity in bad.items():
        try:
            SceneVisualBrief.model_validate(scene([AXES, ORBIT, entity]))
            problems.append(f"accepted: {label}")
        except ValidationError as exc:
            notes.append(f"{label}: " + next(line.strip() for line in str(exc).splitlines() if "Value error" in line)[:120])
    return report("1. schema: point anchors accepted, wrong ones refused", problems, notes)


MEASURE = """() => {
  const stage = document.getElementById("stage").getBoundingClientRect();
  const centre = n => { const q = n.getBoundingClientRect(); return [(q.left + q.right) / 2 - stage.left, (q.top + q.bottom) / 2 - stage.top]; };
  const toStage = (el, x, y) => { const p = new DOMPoint(x, y).matrixTransform(el.getScreenCTM()); return [p.x - stage.left, p.y - stage.top]; };
  const out = {graph: centre(E.ax.box), conflicts: window.layoutConflicts};
  if (E.orbit) { const c = E.orbit.curvePath, L = c.getTotalLength(), pts = [];
    for (let i = 0; i < 720; i++) { const p = c.getPointAtLength(L * i / 720); pts.push(toStage(c, p.x, p.y)); }
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    out.orbitCentre = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]; }
  if (E.earth) out.earth = centre(E.earth.shape);
  if (E.grav) { const l = E.grav.vector.line, [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map(k => +l.getAttribute(k));
    out.grav = [toStage(l, x1, y1), toStage(l, x2, y2)]; }
  out.labels = Object.fromEntries(["grav", "vel"].filter(id => E[id]).map(id =>
    [id, [getComputedStyle(E[id].vector.g.querySelector("text")).fill, E[id].vector.line.getAttribute("stroke")]]));
  return out;
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


def case_page():
    data, problems = measure(scene([AXES, ORBIT, EARTH, ISS, GRAVITY, SPEED])), []
    gap = math.dist(data["earth"], data["orbitCentre"])
    (sx, sy), (ex, ey) = data["grav"]
    to_earth = [data["earth"][0] - sx, data["earth"][1] - sy]
    cos = ((ex - sx) * to_earth[0] + (ey - sy) * to_earth[1]) / (math.hypot(ex - sx, ey - sy) * math.hypot(*to_earth))
    off = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
    if gap > 2:
        problems.append(f"the Earth is {gap:.1f} px from the orbit's centre")
    if off > 3:
        problems.append(f"the gravity is {off:.1f}° off the Earth")
    if data["conflicts"]:
        problems.append(f"conflicts: {data['conflicts']}")
    return report("2. agent010: the Earth at the orbit's centre, the gravity at the Earth", problems,
                  [f"Earth {gap:.1f} px from the orbit's centre, gravity {off:.1f}° off it"])


def case_no_push():
    alone = measure(scene([AXES, ORBIT]))["graph"]
    with_earth = measure(scene([AXES, ORBIT, {**EARTH, "position": [0, -0.07, 0]}]))["graph"]   # guessed on the graph
    moved = math.dist(alone, with_earth)
    return report("3. agent010: an anchored object's guessed position pushes nothing", [] if moved < 0.5 else
                  [f"the graph moved {moved:.1f} px"], [f"the graph moved {moved:.1f} px"])


def case_colours():
    data = {e["id"]: e for e in renderer.page_data(scene([AXES, ORBIT, ISS, GRAVITY, SPEED, {**SPEED, "id": "red",
            "initial_state": {**SPEED["initial_state"], "color": "#000000", "label": "Poussée"}}]), 6.0, 6)["entities"]}   # its own legend line
    colours = {i: data[i]["vector"]["color"] for i in ("grav", "vel", "red")}
    problems = []
    if colours["grav"] == colours["vel"] or not data["grav"]["vector"].get("label_color"):
        problems.append(f"riders not told apart: {colours}")
    if colours["red"] != "#000000":
        problems.append("a colour the brief gives was overridden")
    return report("4. agent010: one colour per vector riding on a body, labels in it", problems, [str(colours)])


def case_patch():
    brief = scene([AXES, ORBIT, {**EARTH, "initial_state": {"icon": "earth", "label": "Terre"}}])
    briefs, corrections = {"1": brief}, []
    agent005.apply_patches(briefs, [{"op": "set_initial_state", "scene_id": "1", "entity_id": "earth", "key": "anchor",
                                     "value": {"axes": "ax", "x": 0, "y": 0}}], corrections)
    ok = briefs["1"]["entities"][2]["initial_state"].get("anchor") == {"axes": "ax", "x": 0, "y": 0}
    return report("5. agent005: a patch anchors the planet at the orbit's centre", [] if ok else [str(corrections)], corrections)


try:
    import playwright  # noqa: F401
except ImportError:
    sys.exit("FAIL  Playwright is not installed (pip install playwright && playwright install chromium)")
results = [case_schema(), case_page(), case_no_push(), case_colours(), case_patch()]
sys.exit(0 if all(results) else 1)
