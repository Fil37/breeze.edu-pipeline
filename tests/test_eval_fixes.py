"""
Check the fixes from the evaluation of the 4-channel run of 2026-11-02 (04:14), offline but for the
browser:
  1. a ray or a curve named by its colour is drawn in it ("Bleu diffusé" blue even if the brief says
     red); the arrows of one legend line share one colour; a label with no colour keeps the brief's
  2. agent004 sends back a GAUGE that never gets a value
  3. agent004 measures each scene's page as the renderer lays it out (app/render/layout_check.py):
     what overlaps is sent back to the LLM with the other advisory problems; a badge in a graph's
     empty margin is not a conflict
  4. agent010 page: the axis titles are drawn over the curves, outlined; a badge pointing at a
     formula keeps off the axis titles and off the other formulas
Prints PASS or FAIL per case. Cases 3 and 4 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_eval_fixes.py
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as agent004        # noqa: E402
from app.agent import agent010_html_renderer as renderer               # noqa: E402
from app.render.layout_check import measured_conflicts                 # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def vector(entity_id, label, color, direction="RIGHT", symbol=None):
    state = {"direction": direction, "label": label, "color": color, "anchor": {"body": "p"}}
    if symbol:
        state["symbol"] = symbol
    return {"id": entity_id, "type": "VECTOR_ARROW", "position": [0, 0, 0], "initial_state": state}


def case_colours():
    problems = []
    brief = {"scene_id": "4", "text_overlay": {"title": "La diffusion"}, "connections": [], "actions": [],
             "entities": [{"id": "p", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "Particule"}},
                          vector("b1", "Bleu diffusé", "#EF4444", "UP"), vector("b2", "Bleu diffusé", "#10B981", "LEFT"),
                          vector("r", "Rouge-orange direct", "#3B82F6"), vector("f", "Force", "#F59E0B", "DOWN"),
                          {"id": "axes", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {}},
                          {"id": "c", "type": "CURVE_PLOT", "position": [0, 0, 0],
                           "initial_state": {"func": "x", "axes": "axes", "label": "Lumière verte", "color": "#EF4444"}}]}
    data = {e["id"]: e for e in renderer.page_data(brief, 8, None)["entities"]}
    colours = {i: (data[i].get("vector") or data[i].get("curve"))["color"] for i in ("b1", "b2", "r", "f", "c")}
    expected = {"b1": "#3B82F6", "b2": "#3B82F6", "r": "#EF4444", "f": "#F59E0B", "c": "#10B981"}
    if colours != expected:
        problems.append(f"colours {colours}, expected {expected}")
    if renderer.named_colour("Lumière violette") != "#8B5CF6" or renderer.named_colour("Vertical") is not None:
        problems.append("colour words: a feminine form missed, or a word merely starting like one taken")
    return report("1. rays and curves in the colour they are named by, one per legend line", problems)


def case_gauges():
    problems = []
    brief = {"scene_id": "2", "text_overlay": {"title": "Déficit"}, "connections": [],
             "entities": [{"id": "g1", "type": "GAUGE", "position": [-3, 0, 0], "initial_state": {"label": "Déficit annuel"}},
                          {"id": "g2", "type": "GAUGE", "position": [3, 0, 0], "initial_state": {"label": "Dette"}}],
             "actions": [{"at": 1, "action": "set_value", "target": "g2", "value": 3000, "unit": "Md€", "cue": "x"}]}
    found = agent004.gauges_without_value(SceneVisualBrief.model_validate(brief))
    if len(found) != 1 or "g1" not in found[0]:
        problems.append(f"gauges without a value: {found}")
    return report("2. agent004: a gauge that never shows a value is sent back", problems)


# The toll of the electronics video: cars moved one by one, piled up where the page cannot spread them.
CARS = [("car_fast1", -5.37, 1.7, 4.5, 1.2), ("car_fast2", -3.47, 1.7, 5.2, 1.2), ("car_fast3", -1.58, 1.2, 5.8, 1.2),
        ("car_mid1", -5.1, 0.01, 3.8, 0), ("car_mid2", -3.5, 0.01, 4.5, 0), ("car_slow1", -5.0, -1.67, 3.2, -1.2),
        ("car_slow2", -3.5, -1.67, 4.0, -1.2)]
OVERLAP = {"scene_id": "1", "text_overlay": {"title": "Des files au péage"}, "connections": [],
           "entities": [{"id": "toll", "type": "OBJECT", "position": [3, 0, 0], "initial_state": {"icon": "building", "label": "Péage"}}]
                       + [{"id": i, "type": "OBJECT", "position": [x, y, 0], "initial_state": {"icon": "car", "label": "File"}}
                          for i, x, y, _, _ in CARS],
           "actions": [{"at": 0.7, "action": "move", "target": i, "to": [tx, ty], "duration": 3, "cue": "x"} for i, _, _, tx, ty in CARS]}
GRAPH = {"scene_id": "2", "text_overlay": {"title": "Une loi"}, "connections": [],
         "entities": [{"id": "axes", "type": "AXES_GRAPH", "position": [1.2, -0.6, 0],
                       "initial_state": {"x_range": [0, 10, 1], "y_range": [0, 1, 0.1], "x_label": "Nombre de pile", "y_label": "Probabilité"}},
                      {"id": "curve", "type": "CURVE_PLOT", "position": [1.2, -0.6, 0],
                       "initial_state": {"func": "np.exp(-(x - 5)**2 / 4)", "axes": "axes", "label": "Allure"}},
                      {"id": "f1", "type": "TEX_FORMULA", "position": [-4.3, 1.8, 0], "initial_state": {"latex": "P(X=5) < 1"}},
                      {"id": "f2", "type": "TEX_FORMULA", "position": [0, 1.8, 0], "initial_state": {"latex": "P(X=5) \\approx 0{,}246"}},
                      {"id": "n1", "type": "ARROW_ANNOTATION", "position": [-4.3, 1.3, 0],
                       "initial_state": {"text": "P(X=5) n'est pas garanti", "target": "f1", "direction": "UP"}}],
         "actions": []}


def case_measured():
    problems = []
    briefs = {b["scene_id"]: SceneVisualBrief.model_validate(b) for b in (OVERLAP, GRAPH)}
    found = measured_conflicts(["1", "2"], briefs, {"1": "analogy_fullscreen", "2": "circuit"}, {}, {"1": 8, "2": 8}, None)
    if not any(m.startswith("scene 1:") and " overlaps car_" in m for m in found):
        problems.append(f"the piled-up cars not measured: {found}")
    if any(m.startswith("scene 2:") for m in found):
        problems.append(f"the graph scene has conflicts: {found}")
    answer = {"scenes": [{**OVERLAP, "layout_template": "circuit"}]}
    calls, measured = [], []
    original = agent004.llm_call
    agent004.llm_call = lambda prompt: calls.append(prompt) or json.dumps(answer)
    try:
        scenes = [{"scene_id": "1", "duration_sec": 8, "narration_text": "Deux pièces au même endroit.", "key_visual_moment": ""}]
        result = agent004.ask_for_storyboard(scenes, "", lambda *a: measured.append(a) or ["scene 1: measured on the page: a overlaps b"])
    finally:
        agent004.llm_call = original
    if len(calls) != agent004.MAX_ATTEMPTS or "a overlaps b" not in calls[-1]:
        problems.append(f"the measured overlap not sent back: {len(calls)} calls")
    if not any("a overlaps b" in m for m in result[3]):
        problems.append(f"not in the problems left: {result[3]}")
    if not measured or measured[0][2] != {"1": "circuit"}:
        problems.append(f"measured with templates {measured[0][2] if measured else None}")
    return report("3. agent004 measures the pages and sends overlaps back", problems, found[:2])


def case_axis_titles():
    from playwright.sync_api import sync_playwright
    problems = []
    data = renderer.page_data(GRAPH, 8, None)
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            path = os.path.join(folder, "graph.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(data))
            renderer.open_scene(page, path)
            page.evaluate("window.seek(7)")
            shown = page.evaluate("""() => {
              const rect = n => { const r = n.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom}; };
              const titles = [...document.querySelectorAll('.axis-label')];
              const svg = titles[0].ownerSVGElement, kids = [...svg.children];
              const curves = kids.findIndex(k => k.tagName === 'g' && k.querySelector('path'));
              const badge = [...document.querySelectorAll('.pill')].map(rect)[0];
              const formulas = [...document.querySelectorAll('.formula')].map(rect);
              const hit = (a, b) => Math.min(a.r, b.r) > Math.max(a.l, b.l) && Math.min(a.b, b.b) > Math.max(a.t, b.t);
              return {after: titles.every(t => kids.indexOf(t) > curves), halo: titles.every(t => t.classList.contains('halo')),
                      onTitle: titles.some(t => hit(badge, rect(t))), onFormula: formulas.some(f => hit(badge, f)),
                      conflicts: window.layoutConflicts};
            }""")
        finally:
            browser.close()
    if not shown["after"] or not shown["halo"]:
        problems.append(f"axis titles under the curves or not outlined: {shown}")
    if shown["onTitle"] or shown["onFormula"]:
        problems.append(f"the badge covers an axis title or a formula: {shown}")
    if shown["conflicts"]:
        problems.append(f"conflicts {shown['conflicts']}")
    return report("4. axis titles over the curves; a badge keeps off them and off the formulas", problems)


if __name__ == "__main__":
    results = [case_colours(), case_gauges(), case_measured(), case_axis_titles()]
    sys.exit(0 if all(results) else 1)
