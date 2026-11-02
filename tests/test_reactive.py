"""
Check the "reactive" pictures and the fixes from the evaluation of the run of 2026-11-02 (11:26),
offline but for the browser:
  1. agent005's layout arbiter keeps a comparison's things in their panel and squeezes nothing to a
     column it does not have (the empty "Ce qu'on mesure" panel)
  2. agent004 sends back: a graph 0 to 10 with no unit, electrons drawn as still discs, a hook
     without a film on a channel that films (not on maths); the schema checks a SEESAW and a vector's value
  3. vectors with a "value" are drawn to scale (588 N against 96 N) and set_value shrinks one before
     the eyes; a thing "floating" rises
  4. SEESAW: a load dropped tips the beam its way; "balanced" slides the pivot to the weighted mean
     and shows it (30 x 15 + 5 x 10 over 35: 14,29)
  5. electrons ("carriers": "electrons") go round the other way; a curve draws with a dot at its head,
     a formula writes itself left to right
  6. a number line: no "-0", 5 to 10 graduations over 0 to 10 000, none hidden under a dot's label
Prints PASS or FAIL per case. Cases 3 to 6 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_reactive.py
"""

import copy
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as agent004        # noqa: E402
from app.agent import agent010_html_renderer as renderer               # noqa: E402
from app.layout_solver import solve_layout                             # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, scene_point   # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def open_pages(pages, script):
    """Load each page ({name: page data}) and run `script` (a JS function, given the page's name) on it."""
    from playwright.sync_api import sync_playwright
    found = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            for name, data in pages.items():
                path = os.path.join(folder, name + ".html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(data))
                renderer.open_scene(page, path)
                found[name] = page.evaluate(script)
        finally:
            browser.close()
    return found


def case_comparison_arbiter():
    problems = []
    brief = {"scene_id": "1", "text_overlay": {"title": "Masse ou poids ?"}, "connections": [],
             "entities": [{"id": "scale", "type": "SCALE", "position": [-3.5, -1.3, 0], "initial_state": {"label": "Balance"}},
                          {"id": "person", "type": "OBJECT", "position": [-3.5, 0.3, 0], "initial_state": {"icon": "user", "label": "Personne"}},
                          {"id": "formula", "type": "TEX_FORMULA", "position": [0.4, 0, 0], "initial_state": {"latex": "P = m \\times g"}},
                          {"id": "question", "type": "ARROW_ANNOTATION", "position": [5.2, 1.2, 0],
                           "initial_state": {"text": "Que mesure-t-on vraiment ici ?", "kind": "status"}}],
             "actions": []}
    compared = copy.deepcopy(brief)
    solve_layout(compared, [], "comparison")
    x = {e["id"]: scene_point(e["position"])[0] for e in compared["entities"]}
    if x["formula"] <= 0:
        problems.append(f"the formula left panel B: x = {x['formula']:.2f}")
    masse_poids = {"scene_id": "5", "text_overlay": {"title": "Les bonnes phrases", "subtitle": "Grandeur et unité"},
                   "connections": [], "actions": [], "entities": [      # the run's scene 5: the weights went to the mass panel
        {"id": "earth", "type": "OBJECT", "position": [-4.2, -0.8, 0], "initial_state": {"icon": "earth", "label": "Terre"}},
        {"id": "moon", "type": "OBJECT", "position": [3.5, -0.8, 0], "initial_state": {"icon": "moon", "label": "Lune"}},
        {"id": "masse", "type": "TEX_FORMULA", "position": [-3.5, 1.4, 0], "initial_state": {"latex": "m = 60\\ \\text{kg}"}},
        {"id": "poids", "type": "TEX_FORMULA", "position": [3.5, 1.4, 0], "initial_state": {"latex": "P_T \\approx 588\\ \\text{N}"}},
        {"id": "badge", "type": "ARROW_ANNOTATION", "position": [5.2, 1.2, 0], "initial_state": {"text": "Grandeur ≠ unité", "kind": "status"}}]}
    solve_layout(masse_poids, [], "comparison")
    sides = {e["id"]: scene_point(e["position"])[0] < 0 for e in masse_poids["entities"] if e["id"] != "badge"}
    if sides != {"earth": True, "moon": False, "masse": True, "poids": False}:
        problems.append(f"Masse | Poids: a thing changed panel: {sides}")
    circuit = copy.deepcopy(brief)
    circuit["entities"][2]["position"] = [4.5, 0, 0]          # under the column a circuit page has
    notes = []
    solve_layout(circuit, notes, "circuit")
    if not any("squeezed" in n for n in notes):
        problems.append("a circuit scene with a status badge is no longer squeezed left of its column")
    return report("1. agent005's arbiter keeps a comparison's panels", problems, [f"x: {x}"])


def case_agent004():
    problems = []
    graph = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "PIB"}, "connections": [], "actions": [], "entities": [
        {"id": "a", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [0, 10, 1], "y_range": [0, 10, 1], "x_label": "temps", "y_label": "PIB"}}]})
    real = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "PIB"}, "connections": [], "actions": [], "entities": [
        {"id": "a", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [2015, 2025, 1], "y_range": [0, 3000, 500], "x_label": "années", "y_label": "PIB (Md€)"}}]})
    maths = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "f"}, "connections": [], "actions": [], "entities": [
        {"id": "a", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_label": "x", "y_label": "y"}}]})
    if not agent004.placeholder_graphs(graph) or agent004.placeholder_graphs(real) or agent004.placeholder_graphs(maths):
        problems.append("placeholder graphs: a 0-10 'temps'/'PIB' graph not sent back, or a real / maths one sent back")
    circuit = {"scene_id": "3", "text_overlay": {"title": "Porteurs"}, "actions": [],
               "entities": [{"id": "b", "type": "BATTERY", "position": [-3, 0, 0]}, {"id": "l", "type": "LAMP", "position": [3, 0, 0]},
                            {"id": "e1", "type": "BODY", "position": [0, 1, 0], "initial_state": {"label": "e⁻"}}],
               "connections": [{"source_id": "b", "source_port": "positive", "target_id": "l", "target_port": "left_terminal"},
                               {"source_id": "l", "source_port": "right_terminal", "target_id": "b", "target_port": "negative"}]}
    if not agent004.electrons_as_discs(SceneVisualBrief.model_validate(circuit)):
        problems.append("electron discs on a circuit not sent back")
    hook = {"1": SceneVisualBrief.model_validate({**circuit, "entities": circuit["entities"][:2]})}
    if not agent004.footage_problems(["1"], hook, {}, expected=True) or agent004.footage_problems(["1"], hook, {}, expected=False):
        problems.append("a hook without film: sent back on a filming channel only")
    for why, state in (("no weight", {"left": {"label": "A"}, "right": {"label": "B", "weight": 5}}),
                       ("one value", {"left": {"label": "A", "weight": 3, "value": 15}, "right": {"label": "B", "weight": 5}}),
                       ("weight 0", {"left": {"label": "A", "weight": 0}, "right": {"label": "B", "weight": 5}})):
        try:
            SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": None, "connections": [], "actions": [],
                                             "entities": [{"id": "s", "type": "SEESAW", "position": [0, 0, 0], "initial_state": state}]})
            problems.append(f"SEESAW with {why} accepted")
        except Exception:
            pass
    try:
        SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": None, "connections": [], "actions": [],
                                         "entities": [{"id": "v", "type": "VECTOR_ARROW", "position": [0, 0, 0], "initial_state": {"value": "beaucoup"}}]})
        problems.append("a vector's value as text accepted")
    except Exception:
        pass
    return report("2. agent004: placeholder graphs, electron discs, hook film; SEESAW and vector values checked", problems)


WEIGHT = {"scene_id": "3", "text_overlay": {"title": "Terre et Lune"}, "connections": [],
          "entities": [{"id": "person", "type": "OBJECT", "position": [-1, 0.6, 0], "initial_state": {"icon": "person-standing", "label": "Personne"}},
                       {"id": "earth", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                        "initial_state": {"direction": "DOWN", "label": "Poids", "symbol": "P", "value": 588, "unit": "N", "anchor": {"body": "person"}}},
                       {"id": "moon", "type": "OBJECT", "position": [4, 0.6, 0], "initial_state": {"icon": "moon", "label": "Lune"}},
                       {"id": "small", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                        "initial_state": {"direction": "DOWN", "label": "Poids lunaire", "symbol": "PL", "value": 96, "unit": "N", "anchor": {"body": "moon"}}}],
          "actions": [{"at": 4, "action": "set_value", "target": "earth", "value": 96, "unit": "N", "cue": "x"},
                      {"at": 4.2, "action": "set_state", "target": "person", "state": {"floating": True}, "cue": "x"}]}


def case_vectors():
    problems = []
    data = renderer.page_data(WEIGHT, 10, None)
    data["events"] = [{**a, "at": a["at"]} for a in WEIGHT["actions"]]     # at the brief's times
    lengths = {e["id"]: e["vector"]["length"] for e in data["entities"] if e.get("vector")}
    if abs(lengths["earth"] / lengths["small"] - 588 / 96) > 0.01:
        problems.append(f"lengths not to scale: {lengths}")
    found = open_pages({"weight": data}, """() => {
      const len = () => { const l = document.querySelector('#wires line');      // the shaft stops 22 px short of the tip
        return Math.hypot(l.x2.baseVal.value - l.x1.baseVal.value, l.y2.baseVal.value - l.y1.baseVal.value) + 22; };
      const person = () => document.querySelector('.entity').getBoundingClientRect().top;
      window.seek(3.5); const before = [len(), person()];
      window.seek(9.5); const after = [len(), person()];
      return {before, after};
    }""")["weight"]
    (l0, y0), (l1, y1) = found["before"], found["after"]
    if not 0.12 < l1 / l0 < 0.22:
        problems.append(f"the weight did not shrink to about 96/588: {l0:.0f} px -> {l1:.0f} px")
    if y0 - y1 < 60:
        problems.append(f"the floating person rose {y0 - y1:.0f} px")
    return report("3. vectors to scale, shrinking with set_value; a floating thing rises", problems,
                  [f"arrow {l0:.0f} -> {l1:.0f} px, person up {y0 - y1:.0f} px"])


def seesaw_brief(actions):
    return {"scene_id": "3", "text_overlay": {"title": "Le grand groupe pèse plus"}, "connections": [],
            "entities": [{"id": "s", "type": "SEESAW", "position": [0, -0.4, 0], "initial_state": {
                "left": {"label": "Classe A", "weight": 30, "value": 15}, "right": {"label": "Classe B", "weight": 5, "value": 10}, "unit": "/20"}}],
            "actions": actions}


def case_seesaw():
    problems = []
    actions = [{"at": 1, "action": "set_state", "target": "s", "state": {"left": True}, "cue": "x"},
               {"at": 3.5, "action": "set_state", "target": "s", "state": {"right": True}, "cue": "x"},
               {"at": 6, "action": "set_state", "target": "s", "state": {"balanced": True}, "cue": "x"}]
    SceneVisualBrief.model_validate(seesaw_brief(actions))
    data = renderer.page_data(seesaw_brief(actions), 12, None, None, "analogy_fullscreen")
    data["events"] = actions
    found = open_pages({"seesaw": data}, """() => {
      const angle = () => { const m = /rotate\\(([-\\d.e]+)deg\\)/.exec(document.querySelector('.seesaw .beam').style.transform); return m ? +m[1] : 0; };
      const read = t => { window.seek(t); const mean = document.querySelector('.seesaw .mean');
        return [angle(), mean.textContent, +mean.style.opacity, +document.querySelectorAll('.seesaw .load')[1].style.opacity]; };
      return {start: read(0.5), left: read(3.3), both: read(5.9), balanced: read(11.5)};
    }""")["seesaw"]
    if abs(found["start"][0]) > 0.5:
        problems.append(f"the empty beam tips: {found['start']}")
    if found["left"][0] > -8 or found["left"][3] != 0:
        problems.append(f"the left load alone does not tip the beam to the left: {found['left']}")
    if not found["left"][0] < found["both"][0] < 0:
        problems.append(f"the right load does not lift the beam back a little: {found['both']}")
    if abs(found["balanced"][0]) > 1 or found["balanced"][1] != "14,29 /20" or found["balanced"][2] < 0.99:
        problems.append(f"balanced: {found['balanced']}")
    return report("4. SEESAW: loads tip the beam, balance shows the weighted mean", problems, [str(found)])


def case_flow_curve_formula():
    problems = []
    flow = {"scene_id": "4", "text_overlay": {"title": "Deux sens"}, "actions": [],
            "entities": [{"id": "b", "type": "BATTERY", "position": [-3, -0.5, 0]}, {"id": "l", "type": "LAMP", "position": [3, -0.5, 0]}],
            "connections": [{"source_id": "b", "source_port": "positive", "target_id": "l", "target_port": "left_terminal"},
                            {"source_id": "l", "source_port": "right_terminal", "target_id": "b", "target_port": "negative"}]}
    pages = {}
    for carriers in ("conventional", "electrons"):
        data = renderer.page_data(flow, 10, None)
        data["events"] = [{"at": 1, "action": "start_flow", "path": ["b", "l", "b"], "carriers": carriers}]
        pages[carriers] = data
    graph = {"scene_id": "2", "text_overlay": {"title": "f"}, "connections": [], "actions": [],
             "entities": [{"id": "a", "type": "AXES_GRAPH", "position": [-2, -0.5, 0], "initial_state": {"x_label": "x", "y_label": "y"}},
                          {"id": "c", "type": "CURVE_PLOT", "position": [-2, -0.5, 0], "initial_state": {"func": "x", "axes": "a"}},
                          {"id": "f", "type": "TEX_FORMULA", "position": [4.5, 2, 0], "initial_state": {"latex": "y = x"}}]}
    pages["graph"] = renderer.page_data(graph, 10, None)
    found = open_pages(pages, """() => {
      const dot = document.querySelector('.electron') || document.querySelector('#wires g circle');
      const at = t => { window.seek(t); return dot ? parseFloat(dot.style.offsetDistance) : null; };
      const tracer = [...document.querySelectorAll('circle')].find(c => c.getAttribute('r') === '12');
      const katex = document.querySelector('.formula .katex');
      const read = t => { window.seek(t); return [tracer ? +tracer.getAttribute('opacity') : null, katex ? katex.style.clipPath : null]; };
      return {moves: [at(2), at(2.2)], electron: !!document.querySelector('.electron'), early: read(0.6), late: read(8)};
    }""")
    conv, elec = found["conventional"]["moves"], found["electrons"]["moves"]
    if not conv[1] > conv[0] or not elec[1] < elec[0] or not found["electrons"]["electron"]:
        problems.append(f"flows: conventional {conv}, electrons {elec}")
    early, late = found["graph"]["early"], found["graph"]["late"]
    if early[0] != 1 or late[0] != 0:
        problems.append(f"curve tracer while drawing / after: {early[0]}, {late[0]}")
    if not early[1] or "inset" not in early[1] or late[1] not in ("inset(-20% 0% -20% 0px)", "inset(-20% 0% -20% 0%)"):
        problems.append(f"formula wipe: {early[1]!r} then {late[1]!r}")
    return report("5. electrons the other way round; a curve's head dot; a formula written left to right", problems)


def case_number_line():
    problems = []
    brief = {"scene_id": "3", "text_overlay": {"title": "PIB par habitant"}, "connections": [], "actions": [],
             "entities": [{"id": "line", "type": "AXES_GRAPH", "position": [-2, -1.3, 0], "initial_state": {"x_range": [0, 10000, 1000], "x_label": "euros"}},
                          {"id": "total", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "PIB total 10 000 €", "anchor": {"axes": "line", "x": 10000, "y": 0}}},
                          {"id": "avg", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "PIB/hab. 5 000 €", "anchor": {"axes": "line", "x": 5000, "y": 0}}}]}
    found = open_pages({"line": renderer.page_data(brief, 8, None)}, """() => {
      const ticks = [...document.querySelectorAll('.tick-label')];
      const shown = ticks.filter(t => t.style.display !== 'none');
      const labels = [...document.querySelectorAll('.entity')].filter(e => e.querySelector('.body-disc')).map(e => e.getBoundingClientRect());   // the dots, with their labels
      const under = shown.filter(t => { const r = t.getBoundingClientRect();
        return labels.some(b => Math.min(b.right, r.right) > Math.max(b.left, r.left) && Math.min(b.bottom, r.bottom) > Math.max(b.top, r.top)); });
      return {all: ticks.map(t => t.textContent), shown: shown.map(t => t.textContent), under: under.map(t => t.textContent)};
    }""")["line"]
    if any(t.startswith("-") for t in found["all"]) or not 5 <= len(found["all"]) <= 11:
        problems.append(f"graduations {found['all']}")
    if found["under"]:
        problems.append(f"numbers under a dot's label: {found['under']}")
    return report("6. number line: no -0, enough graduations, none under a dot's label", problems, [f"shown {found['shown']}"])


if __name__ == "__main__":
    results = [case_comparison_arbiter(), case_agent004(), case_vectors(), case_seesaw(), case_flow_curve_formula(), case_number_line()]
    sys.exit(0 if all(results) else 1)
