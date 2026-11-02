"""
Check that agent010's annotation badges point at the entity their brief names ("target"), not at
the nearest box: before, a badge aimed at a curve, a vector or axes floated at the edge of the graph
or pointed at its legend (the breeze_(math) run of 2026-10-31, scenes 2, 4, 5, 6). Each case is a
small scene taken from that run, rendered in Chromium (Playwright); where the arrow ends is compared
with where the browser itself draws the target (getPointAtLength on the curve's SVG path, the
vector's line), so the check does not reuse the renderer's own geometry.
  1. a badge on a curve (one of three on shared axes): its arrow ends on that curve, and the badge
     covers neither the legend nor the axis titles
  2. a badge on a closed orbit (parametric curve): its arrow ends on the orbit
  3. a badge on a vector: its arrow ends on the vector's shaft
  4. a badge with no target and nothing near it: reported "points at nothing" in layoutConflicts
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_annotation_targets.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent010_html_renderer as renderer   # noqa: E402

ON_TARGET_PX = 22      # the arrow's line stops HEAD (10) px before its tip, the tip TIP_GAP (6) px before the target


def scene(entities):
    return {"scene_id": "1", "text_overlay": {"title": "Test"}, "connections": [], "entities": entities,
            "actions": [{"at": 0.2 + 0.2 * i, "action": "spawn", "target": e["id"]} for i, e in enumerate(entities)]}


def axes(x_label="distance", y_label="hauteur"):
    return {"id": "ax", "type": "AXES_GRAPH", "position": [0, -0.15, 0],
            "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1], "x_label": x_label, "y_label": y_label}}


def curve(entity_id, state, label):
    return {"id": entity_id, "type": "CURVE_PLOT", "position": [0, -0.15, 0], "initial_state": {**state, "axes": "ax", "label": label}}


def badge(entity_id, text, position, direction, target=None):
    state = {"text": text, "direction": direction, **({"target": target} if target else {})}
    return {"id": entity_id, "type": "ARROW_ANNOTATION", "position": position, "initial_state": state}


PARABOLAS = [axes(), curve("slow", {"func": "2 - 0.5*x**2"}, "Lancer doux"), curve("med", {"func": "2 - 0.15*x**2"}, "Lancer fort"),
             curve("fast", {"func": "2 - 0.05*x**2"}, "Très grande vitesse")]
ORBIT = [axes("x", "y"), curve("earth", {"x_func": "1.5*np.cos(t)", "y_func": "1.5*np.sin(t)"}, "Terre"),
         curve("orbit", {"x_func": "3*np.cos(t)", "y_func": "3*np.sin(t)"}, "Orbite")]

MEASURE = """([badgeId, targetId]) => {
  const stage = document.getElementById("stage").getBoundingClientRect();
  const toStage = (el, x, y) => { const p = new DOMPoint(x, y).matrixTransform(el.getScreenCTM()); return [p.x - stage.left, p.y - stage.top]; };
  const b = E[badgeId], t = E[targetId], end = ["x2", "y2"].map(k => +b.ann.line.getAttribute(k));
  let points = [];
  if (t.curvePath) { const L = t.curvePath.getTotalLength();
    for (let i = 0; i <= 400; i++) { const p = t.curvePath.getPointAtLength(L * i / 400); points.push(toStage(t.curvePath, p.x, p.y)); } }
  if (t.vector) { const l = t.vector.line, [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map(k => +l.getAttribute(k));
    for (let i = 0; i <= 100; i++) points.push(toStage(l, x1 + (x2 - x1) * i / 100, y1 + (y2 - y1) * i / 100)); }
  const dist = Math.min(...points.map(p => Math.hypot(p[0] - end[0], p[1] - end[1])));
  const r = b.box.getBoundingClientRect(), box = {l: r.left - stage.left, t: r.top - stage.top, r: r.right - stage.left, b: r.bottom - stage.top};
  const covered = [...document.querySelectorAll(".legend > div, .axis-label")].filter(n => {
    const q = n.getBoundingClientRect(); return Math.min(box.r, q.right - stage.left) > Math.max(box.l, q.left - stage.left)
      && Math.min(box.b, q.bottom - stage.top) > Math.max(box.t, q.top - stage.top); }).map(n => n.textContent);
  return {dist, covered, conflicts: window.layoutConflicts};
}"""


def render(brief, badge_id, target_id):
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
            if target_id is None:
                return {"conflicts": page.evaluate("window.layoutConflicts")}
            return page.evaluate(MEASURE, [badge_id, target_id])
        finally:
            browser.close()


def check(label, brief, badge_id, target_id):
    result, problems = render(brief, badge_id, target_id), []
    if result["dist"] > ON_TARGET_PX:
        problems.append(f"the arrow ends {result['dist']:.0f} px from {target_id} (at most {ON_TARGET_PX})")
    if result["covered"]:
        problems.append(f"the badge covers {result['covered']}")
    print(f'{"FAIL" if problems else "PASS"}  {label}  (arrow end {result["dist"]:.1f} px from {target_id})'
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def check_nothing():
    lone = scene([badge("note", "Regardez", [4.5, 1.5, 0], "DOWN")])
    conflicts = render(lone, "note", None)["conflicts"]
    ok = "note points at nothing" in conflicts
    print(f'{"PASS" if ok else "FAIL"}  4. a badge with nothing to point at is reported  {conflicts}')
    return ok


try:
    import playwright  # noqa: F401
except ImportError:
    sys.exit("FAIL  Playwright is not installed (pip install playwright && playwright install chromium)")
results = [
    check("1. badge on one curve of three (the run's scene 4): on it, legend and axis titles clear",
          scene(PARABOLAS + [badge("longer", "Trajectoire de plus en plus longue", [0, -2.78, 0], "UP", "fast")]), "longer", "fast"),
    check("2. badge on a closed orbit (the run's scene 5)",
          scene(ORBIT + [badge("miss", "Il « rate » le sol", [0, -2.7, 0], "UP", "orbit")]), "miss", "orbit"),
    check("3. badge on a vector (the run's scene 5)",
          scene(ORBIT + [{"id": "grav", "type": "VECTOR_ARROW", "position": [3.2, 0.38, 0], "initial_state": {"direction": "LEFT", "label": "Chute"}},
                         badge("g", "Gravité", [5.02, -0.07, 0], "LEFT", "grav")]), "g", "grav"),
    check_nothing(),
]
sys.exit(0 if all(results) else 1)
