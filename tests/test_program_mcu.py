"""
Check what shows a program at work (the FPGA video of 2026-11-03: "un programme s'exécute instruction
par instruction" over a cpu icon, the circuit with no instructions), offline but for the browser:
  1. a LOGIC_CIRCUIT set to "sequential" shows its program: one line per gate ("r1 = Bouton 1 ET
     Bouton 2"), then the outputs; a pointer on the line at work, in step with the gates; the lines
     dimmed once the circuit works all at once; room made for them (logic_size)
  2. MICROCONTROLLER: bad instructions refused; running, the pointer goes down the program, each
     instruction in turn in the one unit, the count "Une instruction à la fois : 2 / 4"; stopped, it
     stays; agent004 sends back a cpu icon labelled "Microcontrôleur"
Prints PASS or FAIL per case. Needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_program_mcu.py
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.layout_solver import logic_size                                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


LOGIC = {"inputs": [{"id": "a", "label": "Bouton 1"}, {"id": "b", "label": "Bouton 2"}],
         "gates": [{"id": "g1", "type": "AND", "in": ["a", "b"]}, {"id": "g2", "type": "NOT", "in": ["g1"]}],
         "outputs": [{"id": "lamp", "label": "Lampe", "from": "g2"}]}


def brief(entity, actions):
    return {"scene_id": "2", "text_overlay": {"title": "Un programme"}, "connections": [], "entities": [entity],
            "actions": [{"at": at, "action": "set_state", "target": entity["id"], "state": st, "cue": "x"} for at, st in actions]}


def case_program():
    problems = []
    logic = {"id": "lc", "type": "LOGIC_CIRCUIT", "position": [0, 0, 0], "initial_state": copy.deepcopy(LOGIC)}
    actions = [(1, {"mode": "sequential"}), (2, {"a": 1}), (6, {"mode": "parallel"})]
    b = brief(logic, actions)
    data = renderer.page_data(b, 9, None)
    data["events"] = b["actions"]
    program = data["entities"][0]["logic"]["program"]
    if program is None or program["lines"] != ["r1 = Bouton 1 ET Bouton 2", "r2 = NON r1", "Lampe = r2"]:
        problems.append(f"the program's lines: {program}")
    if logic_size({**LOGIC, "program": True})[0] <= logic_size(LOGIC)[0]:
        problems.append("no room made for the program")
    plain = renderer.page_data(brief({**logic, "initial_state": copy.deepcopy(LOGIC)}, [(2, {"a": 1})]), 9, None)
    if plain["entities"][0]["logic"]["program"] is not None:
        problems.append("a program shown for a circuit never set to sequential")
    found = open_pages({"p": data}, """() => {
      const p = E.lc.data.logicParts, read = t => { window.seek(t);
        return {pointer: +p.pointer.getAttribute('opacity'), y: +p.pointer.getAttribute('y'), dim: +p.lines[0].style.opacity}; };
      return {g1: read(2.3), g2: read(3.1), out: read(3.9), after: read(5), parallel: read(7), conflicts: window.layoutConflicts};
    }""")["p"]
    if not (found["g1"]["pointer"] == 1 and found["g2"]["y"] > found["g1"]["y"] and found["out"]["y"] > found["g2"]["y"]):
        problems.append(f"the pointer does not go down with the gates: {found}")
    if found["after"]["pointer"] or found["parallel"]["dim"] >= 1:
        problems.append(f"the pointer stays after the outputs, or the lines are not dimmed in parallel: {found}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("1. a circuit run step by step shows its program, the pointer in step with the gates", problems)


def case_mcu():
    problems = []
    mcu = {"id": "m", "type": "MICROCONTROLLER", "position": [0, 0, 0],
           "initial_state": {"label": "Microcontrôleur", "instructions": ["lire A", "lire B", "calculer ET", "allumer Lampe"]}}
    SceneVisualBrief.model_validate(brief(mcu, []))
    for bad in ([], ["x" * 40], ["a"] * 9, "lire A"):
        try:
            SceneVisualBrief.model_validate(brief({**mcu, "initial_state": {"instructions": bad}}, []))
            problems.append(f"accepted: {bad!r}")
        except ValueError:
            pass
    b = brief(mcu, [(1, {"run": True}), (7, {"run": False})])
    data = renderer.page_data(b, 10, None)
    data["events"] = b["actions"]
    found = open_pages({"m": data}, """() => {
      const p = E.m.data.mcuParts, read = t => { window.seek(t);
        return {doing: p.doing.textContent, count: p.count.textContent, token: +p.token.getAttribute('opacity')}; };
      return {before: read(0.5), first: read(1.2), unit1: read(1.9), unit2: read(3.1), stopped: read(9), conflicts: window.layoutConflicts};
    }""")["m"]
    if found["before"]["count"] or found["first"]["token"] != 1 or found["first"]["doing"]:
        problems.append(f"before running, or the first instruction not travelling: {found['before']}, {found['first']}")
    if found["unit1"]["doing"] != "lire A" or found["unit2"]["doing"] != "lire B" or found["unit2"]["count"] != "Une instruction à la fois : 2 / 4":
        problems.append(f"the unit does not do one instruction after the other: {found['unit1']}, {found['unit2']}")
    if not found["stopped"]["doing"] or found["stopped"]["token"]:
        problems.append(f"stopped: {found['stopped']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    icon = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
                                            "entities": [{"id": "c", "type": "OBJECT", "position": [0, 0, 0],
                                                          "initial_state": {"icon": "cpu", "label": "Microcontrôleur"}}]})
    if not any("MICROCONTROLLER" in e for e in agent004.icons_against_labels(icon)):
        problems.append("a cpu icon labelled Microcontrôleur not sent back")
    return report("2. MICROCONTROLLER: its program done one instruction at a time by its one unit", problems)


if __name__ == "__main__":
    results = [case_program(), case_mcu()]
    sys.exit(0 if all(results) else 1)
