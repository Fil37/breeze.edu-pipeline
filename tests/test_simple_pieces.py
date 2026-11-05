"""
Check the simple catalogue pieces (docs/pieces/ORDRE.md 3 to 15), offline but for the browser:
  1. what the program works out, never the brief: a fraction's sum and percentage, a pie's shares adding
     up to 100, a unit conversion and its factor, a tree path's probability, a Venn region's count and
     probability, a game's best answers and Nash equilibrium; bad states refused
  2. the ten pieces drawn with no page error and no layout conflict, each coming in on its states
  3. the multimeter as an ohmmeter: a measure in Ω shows its mode, and beeps under 30 Ω
Prints PASS or FAIL per case. Cases 2 and 3 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_simple_pieces.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, simple_piece_problem   # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


STATES = {
    "TIMELINE": {"events": [{"date": "1929", "label": "Krach"}, {"date": "1945", "label": "Paix"}, {"date": "2008", "label": "Crise"}]},
    "FRACTION_BAR": {"total": 8, "parts": [{"n": 3, "label": "Lucas"}, {"n": 2, "label": "Emma"}]},
    "PIE_CHART": {"slices": [{"label": "A", "value": 1}, {"label": "B", "value": 1}, {"label": "C", "value": 1}], "unit": "€"},
    "UNIT_CONVERTER": {"value": 2.5, "from": "km", "to": "m"},
    "TREE": {"root": "Lancer", "branches": [{"label": "Pile", "p": 0.5, "branches": [{"label": "Pile", "p": 0.5}, {"label": "Face", "p": 0.5}]},
                                            {"label": "Face", "p": 0.5}]},
    "SET_DIAGRAM": {"a": {"label": "Sport", "count": 30}, "b": {"label": "Musique", "count": 20}, "both": 10, "total": 60},
    "GAME_MATRIX": {"players": ["A", "B"], "strategies": [["bas", "haut"], ["bas", "haut"]], "payoffs": [[[3, 3], [5, 1]], [[1, 5], [4, 4]]]},
    "BAR_CHART": {"bars": [{"label": "2022", "value": 5.2}, {"label": "2023", "value": -1}], "unit": "%", "line": 2},
    "EQUATION_STEPS": {"steps": ["2x + 3 = 11", "2x = 8", "x = 4"], "notes": ["-3", "÷ 2"]},
    "POWER_SUPPLY": {"voltage": 12, "current_limit": 2},
}


def case_worked_out():
    problems = []
    d = renderer.simple_data
    if d("FRACTION_BAR", STATES["FRACTION_BAR"])["sum"] != "3/8 + 2/8 = 5/8 = 62,5 %":
        problems.append(f"fraction sum: {d('FRACTION_BAR', STATES['FRACTION_BAR'])['sum']}")
    pct = [s["pct"] for s in d("PIE_CHART", STATES["PIE_CHART"])["slices"]]
    if sum(pct) != 100:
        problems.append(f"pie shares: {pct}")
    u = d("UNIT_CONVERTER", STATES["UNIT_CONVERTER"])
    if (u["result"], u["factor"]) != ("2 500", "× 1 000"):
        problems.append(f"conversion: {u['result']}, {u['factor']}")
    leaf = next(n for n in d("TREE", STATES["TREE"])["nodes"] if n["path"] == ["Pile", "Face"])
    if leaf["product"] != "0,25":
        problems.append(f"tree path: {leaf}")
    v = d("SET_DIAGRAM", STATES["SET_DIAGRAM"])
    if v["counts"]["either"] != 40 or v["counts"]["neither"] != 20 or not v["p"]["both"].endswith("0,167"):
        problems.append(f"Venn: {v['counts']}, {v['p']}")
    g = d("GAME_MATRIX", STATES["GAME_MATRIX"])
    if g["nash"] != [[True, False], [False, False]]:
        problems.append(f"Nash: {g['nash']}")
    for kind, bad in (("FRACTION_BAR", {"total": 4, "parts": [{"n": 5}]}), ("UNIT_CONVERTER", {"value": 1, "from": "km", "to": "kg"}),
                      ("TREE", {"branches": [{"label": "a", "p": 0.7}, {"label": "b", "p": 0.7}]}),
                      ("SET_DIAGRAM", {"a": {"label": "A", "count": 3}, "b": {"label": "B", "count": 2}, "both": 5}),
                      ("PIE_CHART", {"slices": [{"label": "A", "value": 0}, {"label": "B", "value": 1}]})):
        if simple_piece_problem(kind, bad) is None:
            problems.append(f"accepted {kind}: {bad}")
    return report("1. sums, shares, conversions, probabilities and equilibria worked out by the program", problems)


def case_drawn():
    problems = []
    pages = {}
    for kind, state in STATES.items():
        brief = {"scene_id": "2", "text_overlay": {"title": kind}, "connections": [],
                 "entities": [{"id": "x", "type": kind, "position": [0, -0.3, 0], "initial_state": state}], "actions": []}
        SceneVisualBrief.model_validate(brief)
        pages[kind] = renderer.page_data(brief, 6, None)
    found = open_pages(pages, "() => { window.seek(0.1); const early = E.x.box.innerHTML.length; window.seek(5.9); "
                              "return {conflicts: window.layoutConflicts, parts: !!E.x.data.simpleParts}; }")
    for kind, f in found.items():
        if f["conflicts"] or not f["parts"]:
            problems.append(f"{kind}: {f}")
    return report("2. the ten simple pieces drawn, no conflict", problems)


def case_ohmmeter():
    problems = []
    brief = {"scene_id": "3", "text_overlay": {"title": "Continuité"}, "connections": [],
             "entities": [{"id": "r", "type": "RESISTOR", "position": [-3, 0, 0], "initial_state": {"label": "R"}},
                          {"id": "vm", "type": "VOLTMETER_PROBES", "position": [4, 1, 0], "initial_state": {"label": "Multimètre"}}],
             "actions": [{"at": 1, "action": "measure", "target": "vm", "target_pin_a": "r.left", "target_pin_b": "r.right", "value": 0.4,
                          "unit": "Ω", "cue": "x"}]}
    data = renderer.page_data(brief, 6, None)
    found = open_pages({"o": data}, "() => { window.seek(5.5); const p = P[0]; return {mode: p.mode.textContent, beep: !p.beep.hidden, screen: p.screen.textContent}; }")["o"]
    if found["mode"] != "Ω / continuité" or not found["beep"] or "Ω" not in found["screen"]:
        problems.append(f"the ohmmeter: {found}")
    return report("3. the multimeter in Ω: its mode, the continuity beep", problems)


if __name__ == "__main__":
    results = [case_worked_out(), case_drawn(), case_ohmmeter()]
    sys.exit(0 if all(results) else 1)
