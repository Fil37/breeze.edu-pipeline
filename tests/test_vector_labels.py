"""
Check agent010's vector labels (placeVectorLabels): stacked, readable, near their arrow. Before, each
label sat beside its arrow's middle whatever was there: three forces on one body (the breeze_(math)
run of 2026-10-31, scene 3) gave three labels on top of each other, and a label could sit on an axis
or a curve (scene 5). Each case is rendered in Chromium (Playwright) and measured in the browser
(label boxes from getBoundingClientRect, arrows from their SVG lines, curves from getPointAtLength),
not with the renderer's own geometry.
  1. three vectors from one point, one direction, on a component (the run's scene 3): no label
     covers another label or the component, each stays near its arrow
  2. a vector next to an orbit, the x axis and another vector (the run's scene 5): its label crosses
     no curve, no axis, no arrow, and stays near its arrow
  3. a lone vector with room: its label keeps its old place, beside the middle, right of the arrow
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_vector_labels.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent010_html_renderer as renderer   # noqa: E402

NEAR_PX = 120      # a label's nearest edge at most this far from its arrow


def scene(entities):
    return {"scene_id": "1", "text_overlay": {"title": "Test"}, "connections": [], "entities": entities,
            "actions": [{"at": 0.2 + 0.2 * i, "action": "spawn", "target": e["id"]} for i, e in enumerate(entities)]}


def vector(entity_id, position, direction, label):
    return {"id": entity_id, "type": "VECTOR_ARROW", "position": position, "initial_state": {"direction": direction, "label": label}}


MEASURE = """() => {
  const stage = document.getElementById("stage").getBoundingClientRect();
  const rect = n => { const q = n.getBoundingClientRect();
    return {l: q.left - stage.left, t: q.top - stage.top, r: q.right - stage.left, b: q.bottom - stage.top}; };
  const toStage = (el, x, y) => { const p = new DOMPoint(x, y).matrixTransform(el.getScreenCTM()); return [p.x - stage.left, p.y - stage.top]; };
  const vectors = Object.values(E).filter(e => e.vector).map(e => {
    const l = e.vector.line, [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map(k => +l.getAttribute(k));
    return {id: e.data.id, label: rect(e.vector.g.querySelector("text")), shaft: [toStage(l, x1, y1), toStage(l, x2, y2)]}; });
  const boxes = Object.values(E).filter(e => e.box && !e.data.axes && !e.data.annotation).map(e => ({id: e.data.id, r: rect(e.box)}));
  const curves = Object.values(E).filter(e => e.curvePath).flatMap(e => { const L = e.curvePath.getTotalLength(), pts = [];
    for (let i = 0; i <= 600; i++) { const p = e.curvePath.getPointAtLength(L * i / 600); pts.push(toStage(e.curvePath, p.x, p.y)); } return pts; });
  const axes = [...document.querySelectorAll("svg line")].filter(l => l.closest(".graph") && +l.getAttribute("stroke-width") !== 3)
    .map(l => [toStage(l, +l.getAttribute("x1"), +l.getAttribute("y1")), toStage(l, +l.getAttribute("x2"), +l.getAttribute("y2"))]);
  return {vectors, boxes, curves, axes: axes.filter(([p, q]) => Math.hypot(p[0] - q[0], p[1] - q[1]) > 100)};
}"""


def render(brief):
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


def overlaps(p, q):
    return min(p["r"], q["r"]) > max(p["l"], q["l"]) and min(p["b"], q["b"]) > max(p["t"], q["t"])


def inside(point, r, margin=0):
    return r["l"] - margin < point[0] < r["r"] + margin and r["t"] - margin < point[1] < r["b"] + margin


def crosses(segment, r, steps=200):
    (x1, y1), (x2, y2) = segment
    return any(inside((x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps), r) for i in range(steps + 1))


def gap_to_shaft(r, shaft, steps=200):
    (x1, y1), (x2, y2) = shaft
    return min(max(r["l"] - x, 0, x - r["r"]) ** 2 + max(r["t"] - y, 0, y - r["b"]) ** 2
               for x, y in ((x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps) for i in range(steps + 1))) ** 0.5


def common_checks(data):
    problems, vectors = [], data["vectors"]
    for i, a in enumerate(vectors):
        for b in vectors[i + 1:]:
            if overlaps(a["label"], b["label"]):
                problems.append(f"{a['id']}'s label covers {b['id']}'s")
        gap = gap_to_shaft(a["label"], a["shaft"])
        if gap > NEAR_PX:
            problems.append(f"{a['id']}'s label is {gap:.0f} px from its arrow")
        for box in data["boxes"]:
            if overlaps(a["label"], box["r"]):
                problems.append(f"{a['id']}'s label covers {box['id']}")
    return problems


def report(label, problems, data):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    for v in data["vectors"]:
        r = v["label"]
        print(f"      {v['id']}: label at ({r['l']:.0f}, {r['t']:.0f})-({r['r']:.0f}, {r['b']:.0f}), "
              f"{gap_to_shaft(r, v['shaft']):.0f} px from its arrow")
    return not problems


def case_stacked():
    data = render(scene([{"id": "cart", "type": "CART", "position": "CENTER", "initial_state": {"label": "Ascenseur en chute libre"}},
                         vector("elev", [0, -0.12, 0], "DOWN", "Chute de l'ascenseur"),
                         vector("astro", [0, -0.12, 0], "DOWN", "Poids de l'astronaute"),
                         vector("obj", [0, -0.12, 0], "DOWN", "Poids des objets")]))
    return report("1. three forces on one body: labels stacked, readable, near the arrow", common_checks(data), data)


def case_crowded():
    axes = {"id": "ax", "type": "AXES_GRAPH", "position": [0, -0.07, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1], "x_label": "x", "y_label": "y"}}
    orbit = {"id": "orbit", "type": "CURVE_PLOT", "position": [0, -0.07, 0],
             "initial_state": {"x_func": "3*np.cos(t)", "y_func": "3*np.sin(t)", "axes": "ax", "label": "Orbite"}}
    data = render(scene([axes, orbit, vector("vel", [3.0, 0.58, 0], "UP", "Vitesse tangentielle"),
                         vector("grav", [3.2, 0.38, 0], "LEFT", "Chute vers la Terre")]))
    problems = common_checks(data)
    for v in data["vectors"]:
        if any(inside(p, v["label"], 2) for p in data["curves"]):
            problems.append(f"{v['id']}'s label crosses a curve")
        for axis in data["axes"]:
            if crosses(axis, v["label"]):
                problems.append(f"{v['id']}'s label crosses an axis")
        for other in data["vectors"]:
            if other is not v and crosses(other["shaft"], v["label"]):
                problems.append(f"{v['id']}'s label crosses {other['id']}'s arrow")
    return report("2. a vector by an orbit, an axis and another vector: its label clear of them", problems, data)


def case_alone():
    data = render(scene([vector("weight", [-3, 1, 0], "DOWN", "Poids")]))
    v = data["vectors"][0]
    (x1, y1), (x2, y2) = v["shaft"]
    middle_y, label = (y1 + y2) / 2, v["label"]
    problems = [] if label["l"] > max(x1, x2) and label["t"] < middle_y < label["b"] else \
        [f"label at ({label['l']:.0f}, {label['t']:.0f}), not beside the middle on the right (arrow x {x1:.0f}, middle y {middle_y:.0f})"]
    return report("3. a lone vector: its label keeps its place (beside the middle, on the right)", problems, data)


try:
    import playwright  # noqa: F401
except ImportError:
    sys.exit("FAIL  Playwright is not installed (pip install playwright && playwright install chromium)")
results = [case_stacked(), case_crowded(), case_alone()]
sys.exit(0 if all(results) else 1)
