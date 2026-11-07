"""
Check the voltage divider's layout (the electronics run of 2026-11-06 stacked two horizontal resistors:
the wire between them looped back, and "la résistance du bas" was hard to find), offline but for the
browser:
  1. layout_solver: a chain of resistors between a battery's terminals is laid out in one column, the
     one fed by + at the top, upright; a load across the bottom one upright beside it, wired to its foot;
     a circuit that is not a divider is left to place_schematic
  2. the page: the parts upright (taller than wide), R1 above R2, every wire straight across or down
     with few bends, a flow through the load along the wires (not across the page), nothing overlapping
  3. the voice says "kilo ohms" in two words ("dix kiloohms" came out garbled)
Prints PASS or FAIL per case. Case 2 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_divider.py
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.layout_solver import place_divider, solve_layout               # noqa: E402
from app.tts_manager import normalize_text_for_tts                      # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def part(id_, type_, label, x, y):
    return {"id": id_, "type": type_, "position": [x, y, 0], "initial_state": {"label": label}}


def wire(a, pa, b, pb):
    return {"source_id": a, "source_port": pa, "target_id": b, "target_port": pb}


# as the run of 2026-11-06 drew it: R1 over R2, both horizontal, the load beside R2
DIVIDER = {"scene_id": "3", "text_overlay": {"title": "Charge en parallèle avec la résistance du bas"},
           "entities": [part("bat", "BATTERY", "6 V", -5, 0), part("r1", "RESISTOR", "R1 10 kΩ", 0.5, 0.58),
                        part("r2", "RESISTOR", "R2 10 kΩ", 0.29, -1), part("load", "RESISTOR", "Charge 10 kΩ", 2.71, -1)],
           "connections": [wire("bat", "positive", "r1", "left"), wire("r1", "right", "r2", "left"), wire("r2", "right", "bat", "negative"),
                           wire("r1", "right", "load", "left"), wire("load", "right", "bat", "negative")],
           "actions": [{"at": 1, "action": "start_flow", "path": ["bat", "r1", "load", "bat"], "current": 0.001, "cue": "x"}]}


def case_layout():
    problems = []
    b = copy.deepcopy(DIVIDER)
    if not place_divider(b):
        return report("1. layout_solver: a divider laid out in one column", ["not taken as a divider"])
    at = {e["id"]: e for e in b["entities"]}
    if not (at["r1"]["position"][0] == at["r2"]["position"][0] and at["r1"]["position"][1] > at["r2"]["position"][1]):
        problems.append(f"R1 not right above R2: {at['r1']['position']}, {at['r2']['position']}")
    if not (at["load"]["position"][1] == at["r2"]["position"][1] and at["load"]["position"][0] > at["r2"]["position"][0]):
        problems.append(f"the load not beside R2: {at['load']['position']}")
    if [at[i]["initial_state"].get("vertical") for i in ("r1", "r2", "load")] != [1, 1, 1] or not at["bat"]["initial_state"].get("upright"):
        problems.append("the parts not upright")
    if not any(c["source_id"] == "load" and c["target_id"] == "r2" and c["target_port"] == "right" for c in b["connections"]):
        problems.append(f"the load's foot not wired to R2's: {b['connections']}")
    SceneVisualBrief.model_validate(b)
    flipped = copy.deepcopy(DIVIDER)                       # R2 wired the other way round: its right lead on top
    flipped["entities"] = flipped["entities"][:3]
    flipped["connections"] = [wire("bat", "positive", "r1", "left"), wire("r1", "right", "r2", "right"), wire("r2", "left", "bat", "negative")]
    place_divider(flipped)
    if next(e for e in flipped["entities"] if e["id"] == "r2")["initial_state"].get("vertical") != -1:
        problems.append("a resistor wired right lead first not turned the other way")
    bigger = copy.deepcopy(DIVIDER)
    bigger["entities"].append(part("u1", "OPAMP", "AOP", 3, 0))
    if place_divider(bigger):
        problems.append("a circuit with an AOP taken as a plain divider")
    return report("1. layout_solver: a divider in one column, R1 on top, the load beside R2 and wired to its foot", problems)


def case_page():
    problems = []
    b = copy.deepcopy(DIVIDER)
    solve_layout(b, [], "circuit")
    data = renderer.page_data(b, 6, None)
    data["events"] = b["actions"]
    found = open_pages({"d": data}, """() => { window.seek(5);
      const r = id => { const b = E[id].shape.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; };
      // an electron is on a wire (within 14 px of a segment) or crossing a part of its path
      const near = (x, y, p, q) => x >= Math.min(p[0], q[0]) - 14 && x <= Math.max(p[0], q[0]) + 14 && y >= Math.min(p[1], q[1]) - 14 && y <= Math.max(p[1], q[1]) + 14;
      const inside = (x, y, id) => { const b = E[id].shape.getBoundingClientRect(); return x >= b.left - 14 && x <= b.right + 14 && y >= b.top - 14 && y <= b.bottom + 14; };
      const offPath = F.length ? F[0].dots.filter(d => { const b = d.getBoundingClientRect(), x = b.left + b.width / 2, y = b.top + b.height / 2;
        return !W.some(w => w.pts.some((p, i) => i && near(x, y, w.pts[i - 1], p))) && !F[0].ids.some(id => inside(x, y, id)); }).length : -1;
      return {r1: r('r1'), r2: r('r2'), load: r('load'), bends: W.map(w => w.pts.length - 2), offPath, conflicts: window.layoutConflicts}; }""")["d"]
    if not all(found[k][3] > found[k][2] for k in ("r1", "r2", "load")):
        problems.append(f"the resistors not upright: {found}")
    if not found["r1"][1] < found["r2"][1]:
        problems.append("R1 not above R2 on the page")
    if max(found["bends"]) > 3:
        problems.append(f"a wire with more than 3 bends: {found['bends']}")
    if found["offPath"] != 0:
        problems.append(f"{found['offPath']} electrons off the wires (the load's flow across the page)")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("2. the page: upright parts, R1 above R2, straight wires, the flow on the wires", problems)


def case_voice():
    problems = []
    for text, said in (("deux résistances de dix kiloohms", "deux résistances de dix kilo ohms"),
                       ("R1 vaut 10 kΩ", "erre 1 vaut 10 kilo ohms")):
        if normalize_text_for_tts(text) != said:
            problems.append(f"{text!r} said {normalize_text_for_tts(text)!r}")
    return report("3. the voice says kilo ohms in two words", problems)


if __name__ == "__main__":
    results = [case_layout(), case_page(), case_voice()]
    sys.exit(0 if all(results) else 1)
