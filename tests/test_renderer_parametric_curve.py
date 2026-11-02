"""
Check parametric curves (CURVE_PLOT "x_func" / "y_func" of t, models/visual_brief_schema.py) on a
simple orbit: x = cos(t), y = sin(t), t from 0 to 2*pi.
  1. schema: the orbit is accepted; refused with a clear message: "func" and "x_func" together, an
     "x_func" without "y_func", t_min >= t_max, an expression using x instead of t, code
     ("__import__('os')")
  2. agent010 page data: the curve is sampled in Python (360 points, all defined), marked closed
  3. agent010 rendered page (Playwright): one SVG subpath closed with "Z", as wide as it is high (a
     round circle: equal scales on x and y), its axes too; also on an AXES_GRAPH shared with a
     y = f(x) curve, which stays an open path
Prints PASS or FAIL per case. Case 3 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_renderer_parametric_curve.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from pydantic import ValidationError                              # noqa: E402

from app.agent import agent010_html_renderer as renderer          # noqa: E402
from models.visual_brief_schema import SceneVisualBrief           # noqa: E402

ORBIT = {"x_func": "np.cos(t)", "y_func": "np.sin(t)", "t_min": 0, "t_max": 6.2832, "label": "orbite"}


def scene(*entities):
    return {"scene_id": "1", "text_overlay": {"title": "Orbite"}, "connections": [], "entities": list(entities),
            "actions": [{"at": 0.3, "action": "spawn", "target": e["id"]} for e in entities]}


def curve(entity_id, state):
    return {"id": entity_id, "type": "CURVE_PLOT", "position": "CENTER", "initial_state": state}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_schema():
    problems, notes = [], []
    try:
        SceneVisualBrief.model_validate(scene(curve("o", ORBIT)))
    except ValidationError as exc:
        problems.append(f"the orbit was refused: {exc}")
    bad = {"func and x_func together": {**ORBIT, "func": "np.sin(x)"},
           "x_func without y_func": {"x_func": "np.cos(t)"},
           "t_min >= t_max": {**ORBIT, "t_min": 3, "t_max": 1},
           "x instead of t": {**ORBIT, "x_func": "np.cos(x)"},
           "code": {**ORBIT, "y_func": "__import__('os').system('ls')"}}
    for label, state in bad.items():
        try:
            SceneVisualBrief.model_validate(scene(curve("o", state)))
            problems.append(f"accepted: {label}")
        except ValidationError as exc:
            notes.append(f"{label}: " + next(line.strip() for line in str(exc).splitlines() if "Value error" in line)[:150])
    return report("1. schema: the orbit accepted, the wrong forms refused", problems, notes)


def case_data():
    data = {e["id"]: e for e in renderer.page_data(scene(curve("o", ORBIT)), 6.0, 6)["entities"]}["o"]["curve"]
    problems = []
    if not data.get("parametric") or not data.get("closed"):
        problems.append(f"parametric {data.get('parametric')!r}, closed {data.get('closed')!r}")
    if len(data["points"]) != renderer.PARAMETRIC_SAMPLES or any(y is None for _, y in data["points"]):
        problems.append(f"{len(data['points'])} points, gaps: {sum(y is None for _, y in data['points'])}")
    return report("2. agent010 data: sampled in Python, closed", problems,
                  [f"{len(data['points'])} points, own axes x {data['x_range']}, y {data['y_range']}"])


def measure(brief):
    """{curve id: (path d, its box width, height)} on the rendered page at t = 4 s; None without Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
        try:
            browser = playwright.chromium.launch()
        except Exception:
            return None
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            page.evaluate("window.seek(4)")
            return page.evaluate("""() => Object.fromEntries(Object.values(E).filter(e => e.curvePath).map(e => {
                const b = e.curvePath.getBoundingClientRect();
                return [e.data.id, [e.curvePath.getAttribute("d"), b.width, b.height]]; }))""")
        finally:
            browser.close()


def closed_and_round(d, width, height):
    problems = []
    if d.count("M") != 1 or not d.rstrip().endswith("Z"):
        problems.append(f"{d.count('M')} subpath(s), ends {d.rstrip()[-12:]!r}: not one closed path")
    if abs(width - height) > 0.02 * max(width, height):
        problems.append(f"{width:.1f} x {height:.1f} px: not round")
    return problems


def case_page():
    own = measure(scene(curve("o", ORBIT)))
    if own is None:
        return report("3. agent010 page: closed, round", ["Playwright/Chromium missing"])
    problems, notes = [], []
    d, width, height = own["o"]
    problems += closed_and_round(d, width, height)
    notes.append(f"own axes: path {width:.1f} x {height:.1f} px, ends {d.rstrip()[-1]!r}")
    axes = {"id": "ax", "type": "AXES_GRAPH", "position": "CENTER", "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}}
    shared = measure(scene(axes, curve("o", {**ORBIT, "x_func": "2*np.cos(t)", "y_func": "2*np.sin(t)", "axes": "ax"}),
                           curve("s", {"func": "np.sin(x)", "axes": "ax", "label": "sinus"})))
    d, width, height = shared["o"]
    problems += [f"on an AXES_GRAPH: {p}" for p in closed_and_round(d, width, height)]
    notes.append(f"on an AXES_GRAPH (x -5..5, y -3..3): path {width:.1f} x {height:.1f} px")
    if shared["s"][0].rstrip().endswith("Z"):
        problems.append("the y = f(x) curve was closed")
    return report("3. agent010 page: one closed path, round, also on shared axes", problems, notes)


results = [case_schema(), case_data(), case_page()]
sys.exit(0 if all(results) else 1)
