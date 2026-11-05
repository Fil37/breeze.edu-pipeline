"""
Check LOGIC_CIRCUIT and FPGA_GRID (the FPGA run of 2026-11-03, rejected for want of them), offline
but for the browser:
  1. LOGIC_CIRCUIT: a bad circuit is refused (a gate fed by one input, a later gate, a cycle, an
     unknown type); laid out by depth (inputs, gates, outputs); on the page the gates compute (ET,
     NON, OU exclusif; an input set as {"b": 1} or {"values": {"b": 1}}), wires and lamps follow; in sequential mode the gates follow one another
  2. FPGA_GRID: refused when too big; configure fills the blocks in turn, a packet of the bitstream's
     bits flying to each, a note saying what the bitstream is, and lists in red what has no block; reconfigure clears and places the second design; agent004 sends back gates drawn as
     WIRE_BUS junctions labelled "Porte ET"
  3. the FPGA run of 2026-11-03 (03:43): a block named "Portes logiques" is accepted (two lines);
     agent003 takes ET, OU, NON for words, and an English acronym said with what it is as explained
  4. FPGA_GRID zoom and wire: {"zoom": "OU"} zooms on that block, its gate drawn inside, the name
     faded; {"zoom": false} back out; {"wire": true}: the switches close one route after the other,
     the routes lit then (not as the blocks fill), a note says what they are
Prints PASS or FAIL per case. Needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_logic_fpga.py
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


LOGIC = {"inputs": [{"id": "a", "label": "Interrupteur 1"}, {"id": "b", "label": "Interrupteur 2"}],
         "gates": [{"id": "g1", "type": "AND", "in": ["a", "b"]}, {"id": "g2", "type": "NOT", "in": ["g1"]},
                   {"id": "g3", "type": "XOR", "in": ["a", "g2"]}],
         "outputs": [{"id": "lamp", "label": "Lampe", "from": "g1"}, {"id": "alarm", "label": "Alarme", "from": "g3"}]}


def brief(entity, actions=()):
    return {"scene_id": "3", "text_overlay": {"title": "Portes logiques"}, "connections": [], "entities": [entity],
            "actions": [{"at": at, "action": "set_state", "target": entity["id"], "state": state, "cue": "x"} for at, state in actions]}


def refused(entity):
    try:
        SceneVisualBrief.model_validate(brief(entity))
        return False
    except ValueError:
        return True


def case_logic():
    problems = []
    logic = {"id": "lc", "type": "LOGIC_CIRCUIT", "position": [0, 0, 0], "initial_state": LOGIC}
    SceneVisualBrief.model_validate(brief(logic))
    for change in ({"gates": [{"id": "g1", "type": "AND", "in": ["a"]}]}, {"gates": [{"id": "g1", "type": "AND", "in": ["a", "g2"]}]},
                   {"gates": [{"id": "g1", "type": "MAYBE", "in": ["a", "b"]}]}, {"outputs": [{"id": "lamp", "from": "zz"}]},
                   {"inputs": [{"id": "mode"}]}, {"values": {"a": 2}}):
        bad = copy.deepcopy(logic)
        bad["initial_state"] = {**LOGIC, **change}
        if not refused(bad):
            problems.append(f"accepted: {change}")
    z = renderer.logic_data(LOGIC)
    xs = {i: z["nodes"][i]["x"] for i in ("a", "g1", "g2", "g3", "lamp")}
    if not xs["a"] < xs["g1"] < xs["g2"] < xs["g3"] < xs["lamp"] or z["nodes"]["g1"]["name"] != "ET":
        problems.append(f"layout by depth: {xs}")
    actions = [(2, {"a": 1}), (4, {"values": {"b": 1}}), (6, {"mode": "sequential"}), (7, {"b": 0})]
    data = renderer.page_data(brief(logic, actions), 12, None)
    data["events"] = brief(logic, actions)["actions"]
    found = open_pages({"logic": data}, """() => {
      const p = E.lc.data.logicParts.nodes, read = t => { window.seek(t);
        return {g1: p.g1.value.textContent, g2: p.g2.value.textContent, g3: p.g3.value.textContent,
                lamp: p.lamp.lamp.style.fill.includes('FDE047') || p.lamp.lamp.style.fill.includes('253'), a: p.a.value.textContent}; };
      return {start: read(1), both: read(5), seq1: read(7.5), seq2: read(8.3), seq3: read(9.5), conflicts: window.layoutConflicts};
    }""")["logic"]
    if found["start"] != {"g1": "0", "g2": "1", "g3": "1", "lamp": False, "a": "0"}:
        problems.append(f"both inputs at 0: {found['start']}")
    if found["both"] != {"g1": "1", "g2": "0", "g3": "1", "lamp": True, "a": "1"}:
        problems.append(f"both inputs at 1: {found['both']}")
    # b back to 0 at 7, sequential: g1 changes after 0.8 s, g2 after 1.6 s, g3 after 2.4 s
    if (found["seq1"]["g1"], found["seq2"]["g1"], found["seq2"]["g2"], found["seq3"]["g2"]) != ("1", "0", "0", "1"):
        problems.append(f"sequential steps: {found['seq1']}, {found['seq2']}, {found['seq3']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("1. LOGIC_CIRCUIT: bad circuits refused, laid out by depth, gates computing, step by step", problems)


def case_fpga():
    problems = []
    design = ["ET", "OU", "NON", "Compteur", "Filtre", "Mémoire", "Horloge"]
    fpga = {"id": "fp", "type": "FPGA_GRID", "position": [0, 0, 0],
            "initial_state": {"cols": 3, "rows": 2, "design": design, "design2": ["Filtre", "ET"]}}
    SceneVisualBrief.model_validate(brief(fpga))
    for change in ({"cols": 9}, {"rows": 1}, {"design": []}, {"design": ["x" * 20]}, {"design2": "ET"}):
        bad = copy.deepcopy(fpga)
        bad["initial_state"].update(change)
        if not refused(bad):
            problems.append(f"accepted: {change}")
    actions = [(1, {"configure": True}), (6, {"run": True}), (8, {"reconfigure": True})]
    data = renderer.page_data(brief(fpga, actions), 12, None)
    data["events"] = brief(fpga, actions)["actions"]
    found = open_pages({"fpga": data}, """() => {
      const p = E.fp.data.fpgaParts, read = t => { window.seek(t);
        return {labels: p.blocks.map(b => b.label.textContent), over: p.over.textContent,
                routes: p.routes.map(r => +r.getAttribute('opacity'))}; };
      return {before: read(0.5), early: read(2.1), done: read(5.5), again: read(11), conflicts: window.layoutConflicts};
    }""")["fpga"]
    if any(found["before"]["labels"]) or found["early"]["labels"][0] != "ET" or found["early"]["labels"][5]:
        problems.append(f"the blocks not filled in turn: {found['before']['labels']} then {found['early']['labels']}")
    if found["done"]["labels"] != design[:6] or found["done"]["over"] != "Ressources insuffisantes : Horloge sans bloc" \
            or found["done"]["routes"] != [1] * 5:
        problems.append(f"configured: {found['done']}")
    if found["again"]["labels"] != ["Filtre", "ET", "", "", "", ""] or found["again"]["over"]:
        problems.append(f"reconfigured: {found['again']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    flight = open_pages({"fpga": data}, """() => { const p = E.fp.data.fpgaParts; window.seek(1.6);
      return {bits: p.packet.textContent, shown: +p.packet.getAttribute('opacity'), note: p.wireNote.textContent}; }""")["fpga"]
    if not (flight["shown"] == 1 and flight["bits"] and "bitstream" in flight["note"].lower()):
        problems.append(f"no packet of bits flying to the block, or no word on what the bitstream is: {flight}")
    fake = SceneVisualBrief.model_validate({
        "scene_id": "3", "text_overlay": {"title": "Portes"}, "connections": [], "actions": [],
        "entities": [{"id": "w", "type": "WIRE_BUS", "position": [0, 0, 0], "initial_state": {"label": "Porte ET"}}]})
    if len(agent004.gates_by_hand(fake)) != 1:
        problems.append("gates drawn as WIRE_BUS not sent back")
    return report("2. FPGA_GRID: configured in turn, what has no block in red, reconfigured; fake gates sent back", problems)


def case_long_names():
    problems = []
    fpga = {"id": "fp", "type": "FPGA_GRID", "position": [0, 0, 0],
            "initial_state": {"cols": 3, "rows": 2, "design": ["Portes logiques", "Recâblable"]}}
    if refused(fpga):
        problems.append("a block named 'Portes logiques' refused")
    found = open_pages({"fpga": renderer.page_data(brief(fpga, [(1, {"configure": True})]), 8, None)}, """() => {
      window.seek(6); const b = E.fp.data.fpgaParts.blocks[0]; return [b.label.textContent, b.label2.textContent];
    }""")["fpga"]
    if found != ["Portes", "logiques"]:
        problems.append(f"a long name not on two lines: {found}")
    from app.agent import agent003_scriptwriter as agent003
    said = agent003.undefined_acronyms([{"scene_id": "1", "narration_text":
                                         "Un FPGA, c'est-à-dire une puce recâblable. Les portes ET, OU et NON."}], None)
    unsaid = agent003.undefined_acronyms([{"scene_id": "1", "narration_text": "Le FPGA est rapide."}], None)
    if said or len(unsaid) != 1:
        problems.append(f"acronyms: {said} / {unsaid}")
    return report("3. long block names on two lines; ET, OU, NON are words; FPGA explained by what it is", problems)


def case_zoom_wire():
    problems = []
    fpga = {"id": "fp", "type": "FPGA_GRID", "position": [0, 0, 0],
            "initial_state": {"cols": 3, "rows": 2, "design": ["ET", "OU", "NON", "Compteur"]}}
    actions = [(1, {"configure": True}), (4, {"zoom": "OU"}), (7, {"zoom": False}), (9, {"wire": True})]
    data = renderer.page_data(brief(fpga, actions), 14, None)
    data["events"] = brief(fpga, actions)["actions"]
    found = open_pages({"fpga": data}, """() => {
      const p = E.fp.data.fpgaParts, read = t => { window.seek(t);
        return {zoom: p.world.getAttribute('transform'), inside: +p.blocks[1].inside.getAttribute('opacity'),
                gate: !!p.blocks[1].inside.querySelector('path'), table: p.blocks[3].inside.querySelectorAll('rect').length,
                name: +p.blocks[1].label.style.opacity, routes: p.routes.map(r => +r.getAttribute('opacity')),
                switches: p.switches.map(s => /10B981|16, 185, 129/i.test(s[0].style.fill)), note: p.wireNote.textContent}; };
      return {filled: read(3.5), zoomed: read(6), out: read(8.5), wiring: read(9.9), wired: read(13), conflicts: window.layoutConflicts};
    }""")["fpga"]
    f, zm, out, wiring, wired = (found[k] for k in ("filled", "zoomed", "out", "wiring", "wired"))
    if f["zoom"] or any(f["routes"]):
        problems.append(f"zoomed or routes lit before their states: {f}")
    if not (zm["zoom"] and "scale(3.2)" in zm["zoom"] and zm["inside"] == 1 and zm["gate"] and zm["name"] == 0):
        problems.append(f"the zoom on OU: {zm}")
    if zm["table"] != 4:
        problems.append(f"Compteur's inside is not a table: {zm['table']} rows")
    if out["zoom"] or out["inside"] != 0:
        problems.append(f"not zoomed back out: {out}")
    if not (wiring["switches"][0] and not wiring["switches"][2] and wired["switches"][:3] == [True] * 3
            and wired["routes"][:3] == [1, 1, 1] and wired["routes"][3:] == [0, 0] and "Interconnexions" in wired["note"]):
        problems.append(f"the wiring: {wiring} then {wired}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("4. FPGA_GRID: zoom on a block (its gate inside), back out, switches closing route by route", problems)


if __name__ == "__main__":
    results = [case_logic(), case_fpga(), case_long_names(), case_zoom_wire()]
    sys.exit(0 if all(results) else 1)
