"""
Check LANDSCAPE (a place drawn by the program, in cross-section, and what flows where) and the checks that came with
it, all from the runs of 2026-11-21 (water cycle, volcano, resistor drawn with 3D objects and cards; the user: the
objects "did not speak", nothing showed what goes where).
  1. LANDSCAPE: good states accepted (water, volcano), bad ones refused (unknown view, a place of the other view,
     an unknown kind, an eruption of the sea)
  2. the page: both views drawn with no JS error nor conflict; the flows in one by one, things moving along them;
     the labels off the names; the volcano erupts on {"erupt": true} (magma up, lava down, plume up)
  3. agent004 sends back: OBJECTs scattered with nothing linking them (water scene 4), a CARD_SCENE beside a chart
     (volcano scene 6), a GAUGE in mm (water scene 5), a text repeating a resistor's bands (resistor scene 3);
     the program also drops such a label from the REAL_PART itself
  4. agent004: LANDSCAPE offered, its rule in the prompt
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_landscape.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent004_visualbriefgenerator as a004          # noqa: E402
from app.agent import agent010_html_renderer as renderer             # noqa: E402
from app.models.visual_brief_schema import SceneVisualBrief, simple_piece_problem   # noqa: E402
from test_reactive import open_pages                                  # noqa: E402

WATER = {"view": "water", "labels": ["sun"], "focus": "cloud", "flows": [
    {"from": "sea", "to": "cloud", "kind": "vapour", "label": "Évaporation"},
    {"from": "cloud", "to": "mountain", "kind": "rain", "label": "Précipitations"},
    {"from": "mountain", "to": "sea", "kind": "water", "label": "Ruissellement"},
    {"from": "ground", "to": "groundwater", "kind": "water", "label": "Infiltration"}]}
VOLCANO = {"view": "volcano", "labels": ["chamber", "conduit", "crater"],
           "flows": [{"from": "chamber", "to": "crater", "kind": "magma", "label": "Le magma monte"}]}


def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def brief(state, actions=()):
    return {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": list(actions),
            "entities": [{"id": "ls", "type": "LANDSCAPE", "position": [0, -0.3, 0], "initial_state": state}]}


def case_states():
    problems = []
    for good in (WATER, VOLCANO, {**VOLCANO, "erupt": True}, {"view": "water"}):
        if simple_piece_problem("LANDSCAPE", good):
            problems.append(f"good refused: {simple_piece_problem('LANDSCAPE', good)}")
    for bad in ({"view": "desert"}, {**WATER, "flows": [{"from": "sea", "to": "chamber"}]},
                {**WATER, "flows": [{"from": "sea", "to": "cloud", "kind": "smoke"}]},
                {**WATER, "erupt": True}, {**WATER, "labels": ["crater"]}, {**WATER, "flows": WATER["flows"] * 2}):
        if not simple_piece_problem("LANDSCAPE", bad):
            problems.append(f"bad accepted: {str(bad)[:80]}")
    return report("1. LANDSCAPE: good states accepted, bad ones refused", problems)


def case_page():
    problems = []
    steps = [{"at": 1 + i, "action": "set_state", "target": "ls", "state": {"step": i + 1}} for i in range(4)]
    erupt = [{"at": 2, "action": "set_state", "target": "ls", "state": {"erupt": True}}]
    found = open_pages({"water": renderer.page_data(brief(WATER, steps), 10, None),
                        "volcano": renderer.page_data(brief(VOLCANO, erupt), 10, None)}, """() => {
      const p = E.ls.data.simpleParts, flows = () => p.flows.map(f => +f.g.getAttribute("opacity"));
      const moving = () => p.flows.map(f => f.dots.filter(d => +d.getAttribute("opacity") > 0.05).length);
      const at = E.ls.states.filter(st => st.state && Number.isInteger(st.state.step)).map(st => st.at);
      window.seek(at.length ? at[0] + 0.8 : 1.5); const early = flows(); const lava0 = p.lava ? p.lava.getAttribute("stroke-dasharray") : null;
      const rise0 = p.rise ? +p.rise.getAttribute("height") : null;
      window.seek(8); const late = flows(), dots = moving();
      return {early, late, dots, conflicts: window.layoutConflicts, lava0, rise0,
              lava: p.lava ? p.lava.getAttribute("stroke-dasharray") : null, rise: p.rise ? +p.rise.getAttribute("height") : null,
              plume: p.plume ? Math.max(...p.plume.map(c => +c.c.getAttribute("opacity"))) : null}; }""")
    water, volcano = found["water"], found["volcano"]
    if water["conflicts"] or volcano["conflicts"]:
        problems.append(f"conflicts: {water['conflicts']} {volcano['conflicts']}")
    if not (water["early"][0] == 1 and water["early"][3] == 0 and min(water["late"]) == 1):
        problems.append(f"flows not in one by one: {water['early']} {water['late']}")
    if min(water["dots"]) == 0:
        problems.append(f"nothing moves along a flow: {water['dots']}")
    if volcano["rise0"] != 0 or volcano["rise"] <= 100 or volcano["plume"] < 0.5 or volcano["lava"].startswith("0 "):
        problems.append(f"the eruption: {volcano}")
    data = renderer.page_data(brief(WATER), 10, None)["entities"][0]["simple"]
    names = [(n["x"] - len(n["text"]) * 8, n["y"] - 26, n["x"] + len(n["text"]) * 8, n["y"] + 10) for n in data["names"]]
    for f in data["flows"]:
        w = len(f["label"]) * 15 + 36
        box = (f["lx"] - w / 2, f["ly"] - 26, f["lx"] + w / 2, f["ly"] + 24)
        hit = [b for b in names if box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3]]
        if hit:
            problems.append(f"the label {f['label']!r} on a place's name")
    return report("2. the page: drawn, flows one by one and moving, labels off the names, the eruption", problems)


def scene(entities, actions=(), scene_id="1"):
    return SceneVisualBrief.model_validate({"scene_id": scene_id, "text_overlay": {"title": "x"}, "connections": [],
                                            "entities": entities, "actions": list(actions)})


def case_checks():
    problems = []
    obj = lambda i, icon: {"id": i, "type": "OBJECT", "position": [0, 0, 0], "initial_state": {"icon": icon, "label": icon}}
    scattered = scene([obj("a", "cloud"), obj("b", "droplet"), obj("c", "snowflake")])       # water scene 4
    if not a004.scattered_objects(["1"], {"1": scattered}):
        problems.append("scattered OBJECTs not sent back")
    moved = scene([obj("a", "cloud"), obj("b", "droplet"), obj("c", "snowflake")],
                  [{"at": 1, "action": "move", "target": "b", "to": [1, 1], "duration": 1}])
    if a004.scattered_objects(["1"], {"1": moved}):
        problems.append("objects with one moving sent back")
    cards = {"id": "c", "type": "CARD_SCENE", "position": [0, 0, 0], "initial_state": {"cards": [{"icon": "rock", "title": "Basalte"}]}}
    bars = {"id": "b", "type": "BAR_CHART", "position": [0, 0, 0], "initial_state": {"bars": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]}}
    if not a004.cards_beside_charts(["1"], {"1": scene([cards, bars])}) or a004.cards_beside_charts(["1"], {"1": scene([cards])}):
        problems.append("a CARD_SCENE beside a chart not sent back, or alone sent back")
    gauge = {"id": "g", "type": "GAUGE", "position": [0, 0, 0], "initial_state": {"label": "Hauteur de pluie"}}
    for unit, wrong in (("mm", True), ("°C", False), ("bar", False), ("L", True), ("%", True)):
        sent = a004.gauges_off_dial(["1"], {"1": scene([gauge], [{"at": 1, "action": "set_value", "target": "g", "value": 1, "unit": unit}])})
        if bool(sent) != wrong:
            problems.append(f"a GAUGE in {unit}: {'kept' if wrong else 'sent back'}")
    part = {"id": "r", "type": "REAL_PART", "position": [0, 0, 0],
            "initial_state": {"part": "resistor", "value": 27000, "label": "Rouge, violet, orange, doré : 27 kΩ ±5 %"}}
    if not a004.reading_repeated(["1"], {"1": scene([part])}):
        problems.append("a label repeating the bands not sent back")
    label = renderer.entity_data(part, {"r": part}, "#0F172A")["label"]
    if label != "Résistance":
        problems.append(f"the REAL_PART's label repeating the bands kept: {label!r}")
    if a004.reading_repeated(["1"], {"1": scene([{**part, "initial_state": {**part["initial_state"], "label": "Résistance de 27 kΩ"}}])}):
        problems.append("a plain label sent back")
    return report("3. agent004 sends back scattered objects, cards beside a chart, a GAUGE in mm, the bands said twice", problems)


def case_prompt():
    problems = []
    if "ONE LANDSCAPE" not in a004.CARD_RULE or "{{" in a004.CARD_RULE:
        problems.append("the LANDSCAPE rule is not in the prompt (or its braces are doubled: it is inserted by format)")
    if not any(line.startswith("  * LANDSCAPE:") for line in a004.COMPONENTS_FOR_PROMPT.split("\n")):
        problems.append("LANDSCAPE not offered")
    return report("4. agent004: LANDSCAPE offered, its rule in the prompt", problems)


if __name__ == "__main__":
    results = [case_states(), case_page(), case_checks(), case_prompt()]
    sys.exit(0 if all(results) else 1)
