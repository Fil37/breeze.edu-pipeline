"""
Check the schematic parts (the temperature-regulation bench asked on 2026-11-04: an AOP, a CTN, a
MOSFET, a heater...), offline but for the browser:
  1. the symbols and their ports: a full bench (CTN divider, setpoint, AOP with hysteresis, MOSFET,
     heater) validated and drawn with no layout conflict; each part's state shows (the AOP's output
     high, the MOSFET conducting, the heater red with heat rising, the LED lit); a supply symbol
     carries its voltage over its bar, no caption repeating it
  2. step by step: a wire draws itself on its "connect" words (not before), and a junction dot marks
     a port where two wires meet; agent004 takes up to 16 entities in a schematic (8 otherwise), and
     sends back a connect naming no connection; parts given one named place ("RIGHT") put beside it; a
     ground (or supply) symbol wired to several parts split into one beside each, coming in with it; a
     schematic step keeping what the last one built (a part left out put back, its ground and wires); a
     schematic laid out along the signal (sensor, AOP, MOSFET, heater), the AOP's − source over its +
     source, a ground at the end of its lead
  3. BREADBOARD: a bad netlist refused; laid out with no two parts on the same holes, no body over
     another, the op-amp across the gap; each lead in a strip of its net or jumpered to it, a supply
     net's strips jumpered to their rail; the parts go in on their steps (several on one step one after
     the other), the LED lit on "on"; a voltmeter's probe on a part's lead on the board
Prints PASS or FAIL per case. Needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_schematic.py
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


def part(i, kind, x, y, label=None):
    return {"id": i, "type": kind, "position": [x, y, 0], "initial_state": {"label": label} if label else {}}


def wire(a, ap, b, bp):
    return {"source_id": a, "source_port": ap, "target_id": b, "target_port": bp}


BENCH = {"scene_id": "5", "text_overlay": {"title": "Le banc"},
         "entities": [part("v1", "SUPPLY_RAIL", -5.6, 2.5, "+12 V"), part("r1", "RESISTOR", -5.6, 1.2, "R1 10 kΩ"),
                      part("ctn", "THERMISTOR", -5.6, -0.6, "CTN"), part("g1", "CHASSIS_MASS", -5.6, -2.3),
                      part("pot", "POTENTIOMETER", -2.6, -0.9, "Consigne"), part("op", "OPAMP", 0.4, 0.3, "AOP"),
                      part("rh", "RESISTOR", 0.4, 2.3, "Rh"), part("q", "MOSFET", 3.8, -0.9, "MOSFET"),
                      part("g3", "CHASSIS_MASS", 3.8, -2.8), part("h", "HEATER", 3.8, 1.6, "Chauffage"),
                      part("led", "LED", 6.0, -0.5, "LED")],
         "connections": [wire("v1", "terminal", "r1", "left"), wire("r1", "right", "ctn", "left"), wire("ctn", "right", "g1", "terminal"),
                         wire("ctn", "left", "op", "in_minus"), wire("pot", "wiper", "op", "in_plus"),
                         wire("op", "out", "rh", "right"), wire("rh", "left", "op", "in_plus"), wire("op", "out", "q", "gate"),
                         wire("q", "drain", "h", "left"), wire("q", "source", "g3", "terminal")],
         "actions": [{"at": 2, "action": "set_state", "target": t, "state": st, "cue": "x"}
                     for t, st in (("op", {"high": True}), ("q", {"on": True}), ("h", {"on": True}), ("led", {"on": True}))]}


def case_symbols():
    problems = []
    SceneVisualBrief.model_validate(BENCH)
    data = renderer.page_data(copy.deepcopy(BENCH), 6, None)
    data["events"] = BENCH["actions"]
    found = open_pages({"b": data}, """() => {
      window.seek(5);
      const p = id => E[id].data.partParts;
      return {parts: Object.values(E).filter(e => e.data.partParts).length,
              heat: +p('h').heat.getAttribute('opacity'), led: p('led').body.style.fill, out: p('op').out.style.stroke,
              channel: p('q').channel[0].style.stroke, rail: E.v1.shape.querySelector('text').textContent,
              railCaption: !!labelOf(E.v1), conflicts: window.layoutConflicts};
    }""")["b"]
    if found["parts"] != 9 or found["heat"] != 1 or "239, 68, 68" not in found["led"] and "EF4444" not in found["led"]:
        problems.append(f"parts or states: {found}")
    if not (found["out"] and found["channel"]):
        problems.append(f"the AOP's output or the MOSFET's channel not lit: {found}")
    if found["rail"] != "+12 V" or found["railCaption"]:
        problems.append(f"the supply symbol: {found['rail']!r}, caption under it: {found['railCaption']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("1. a bench in standard symbols, each part's state shown", problems)


def case_steps():
    problems = []
    b = copy.deepcopy(BENCH)
    b["actions"] = [{"at": 3.5, "action": "connect", "source_id": "op", "target_id": "q", "cue": "x"}]
    data = renderer.page_data(b, 6, None)
    data["events"] = b["actions"]
    found = open_pages({"b": data}, """() => {
      const w = W.find(w => (w.a === 'op' && w.b === 'q') || (w.a === 'q' && w.b === 'op'));
      return {start: w.start, others: W.filter(x => x !== w).map(x => x.start), dots: J.length,
              dotLater: (window.seek(0.2), J.every(j => +j.dot.getAttribute('opacity') === 0))};
    }""")["b"]
    if not (found["start"] >= 3.5 and max(found["others"]) < 3.5):
        problems.append(f"the connect wire not on its words: {found}")
    if found["dots"] < 2 or not found["dotLater"]:
        problems.append(f"junction dots: {found['dots']} (at the AOP's output and + input), shown before their wires: {not found['dotLater']}")
    many = copy.deepcopy(BENCH)
    errors = agent004.validate_storyboard_topology([SceneVisualBrief.model_validate(many)], {"5": 20})
    if any("entities, at most" in e for e in errors):
        problems.append(f"11 schematic entities refused: {errors}")
    icons = {"scene_id": "2", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
             "entities": [{"id": f"o{i}", "type": "OBJECT", "position": [i - 4, 0, 0], "initial_state": {"icon": "cpu"}} for i in range(9)]}
    if not any("at most 8" in e for e in agent004.validate_storyboard_topology([SceneVisualBrief.model_validate(icons)], {"2": 20})):
        problems.append("9 icons accepted")
    bad = copy.deepcopy(BENCH)
    bad["actions"] = [{"at": 1, "action": "connect", "source_id": "led", "target_id": "pot", "cue": "x"}]
    if not any("connect" in e for e in agent004.validate_storyboard_topology([SceneVisualBrief.model_validate(bad)], {"5": 20})):
        problems.append("a connect naming no connection kept")
    from app.layout_solver import split_rails
    shared = {"entities": [part("g", "CHASSIS_MASS", 0, -3), part("a", "RESISTOR", -3, 0), part("b", "RESISTOR", 3, 1)],
              "connections": [wire("g", "terminal", "a", "right"), wire("b", "left", "g", "terminal")],
              "actions": [{"at": 4, "action": "spawn", "target": "b", "cue": "x"}]}
    split_rails(shared)
    copy_ = next((e for e in shared["entities"] if e["id"] == "g_2"), None)
    if copy_ is None or shared["connections"][1]["target_id"] != "g_2" or copy_["position"][:2] != [3, -0.25] \
            or not any(a["target"] == "g_2" and a["at"] == 4 for a in shared["actions"]):
        problems.append(f"a ground wired to two parts not split, one beside each: {shared}")
    from app.layout_solver import place_schematic
    from models.visual_brief_schema import scene_point
    laid = place_schematic(split_rails(copy.deepcopy(BENCH)))
    at = {e["id"]: scene_point(e["position"]) for e in laid["entities"]}
    if not at["ctn"][0] < at["op"][0] < at["q"][0] <= at["h"][0]:
        problems.append(f"the schematic not laid out along the signal: {at}")
    if not at["ctn"][1] > at["pot"][1]:
        problems.append(f"the AOP's − input's source not above its + input's: {at['ctn']}, {at['pot']}")
    if not at["g3"][1] < at["q"][1] or abs(at["g3"][0] - at["q"][0]) > 1:
        problems.append(f"the MOSFET's ground not under its source lead: {at['g3']} / {at['q']}")
    step1 = {"scene_id": "5", "entities": [part(i, "RESISTOR", 0, 0) for i in ("a", "b", "c", "d")] + [part("g", "CHASSIS_MASS", 0, -2)],
             "connections": [wire("a", "right", "b", "left"), wire("d", "right", "g", "terminal")]}
    step2 = {"scene_id": "6", "entities": [part(i, "RESISTOR", 0, 0) for i in ("a", "b", "c", "e")], "connections": []}
    back = agent004.carry_circuit([step1, step2])
    ids = {e["id"] for e in step2["entities"]}
    if back != ["scene 6: ['d']"] or not {"d", "g"} <= ids or not any(c["source_id"] == "d" for c in step2["connections"]):
        problems.append(f"a part built at the last step not put back, with its ground and wire: {back}, {ids}")
    renamed1 = {"scene_id": "5", "entities": [part(i, "RESISTOR", 0, 0, f"R{i}") for i in ("a", "b", "c")]
                + [part("r_gate", "RESISTOR", 0, 0, "R 220 Ω")], "connections": []}
    renamed2 = {"scene_id": "6", "entities": [part(i, "RESISTOR", 0, 0, f"R{i}") for i in ("a", "b", "c")]
                + [part("resistor_gate_1", "RESISTOR", 0, 0, "R 220 Ω")], "connections": []}
    if agent004.carry_circuit([renamed1, renamed2]):
        problems.append("a part only renamed put back as a second one")
    preview = {"scene_id": "2", "entities": [part(i, "RESISTOR", 0, 0) for i in ("a", "b", "c", "d", "e", "f")], "connections": []}
    first_step = {"scene_id": "3", "entities": [part(i, "RESISTOR", 0, 0) for i in ("a", "b")], "connections": []}
    if agent004.carry_circuit([preview, first_step]) or len(first_step["entities"]) != 2:
        problems.append("the whole circuit shown first (a preview) put back into the first build step")
    crowded = [{"scene_id": "5", "entities": [{"id": i, "type": "RESISTOR", "position": "RIGHT"} for i in ("a", "b", "c")]}]
    agent004.spread_shared_places(crowded)
    places = [str(e["position"]) for e in crowded[0]["entities"]]
    if crowded[0]["entities"][0]["position"] != "RIGHT" or len(set(places)) != 3:
        problems.append(f"parts sharing a named place not put beside it: {places}")
    return report("2. a wire on its connect words, junction dots, 16 entities in a schematic, shared places spread", problems)


BB = {"parts": [{"id": "r1", "kind": "RESISTOR", "label": "R1 10 kΩ"}, {"id": "ctn", "kind": "THERMISTOR", "label": "CTN"},
                {"id": "pot", "kind": "POTENTIOMETER", "label": "Consigne"}, {"id": "op", "kind": "OPAMP", "label": "LM358"},
                {"id": "q", "kind": "MOSFET", "label": "IRLZ44N"}, {"id": "h", "kind": "HEATER", "label": "Chauffage"},
                {"id": "led", "kind": "LED", "label": "LED"}, {"id": "rl", "kind": "RESISTOR", "label": "R 1 kΩ"}],
      "nets": [["+12 V", "r1.left", "pot.left", "op.vcc", "h.left", "rl.left"], ["0 V", "ctn.right", "pot.right", "op.gnd", "q.source"],
               ["r1.right", "ctn.left", "op.in_minus"], ["pot.wiper", "op.in_plus"], ["op.out", "q.gate"],
               ["q.drain", "h.right", "led.cathode"], ["rl.right", "led.anode"]]}


def case_breadboard():
    from app.breadboard import COLS, PITCH, HOLE_X0, ROW_Y, breadboard_data
    from models.visual_brief_schema import breadboard_problem
    problems = []
    for bad in ({**BB, "nets": BB["nets"] + [["r1.left", "q.gate"]]}, {**BB, "parts": BB["parts"] + [{"id": "x", "kind": "RELAY"}]},
                {**BB, "nets": [["led.top", "rl.right"]]}):
        if breadboard_problem(bad) is None:
            problems.append(f"accepted: {bad['nets'][-1]}")
    if breadboard_problem({"parts": []}) is not None or breadboard_data({"parts": []})["parts"]:
        problems.append("the board alone (the supply stage) refused")
    d = breadboard_data(BB)
    hole = lambda lead: ((lead["x"] - HOLE_X0) // PITCH, ROW_Y.index(lead["y"]))
    spots = [hole(l) for p in d["parts"] for l in p["leads"]]
    if len(spots) != len(set(spots)):
        problems.append("two leads in one hole")
    op = next(p for p in d["parts"] if p["kind"] == "OPAMP")
    if {ROW_Y.index(l["y"]) for l in op["leads"]} != {4, 5}:
        problems.append("the op-amp not across the gap")
    strip = lambda c, r: (c, r < 5)
    lead_strip = {f"{p['id']}.{l['name']}": strip(*hole(l)) for p in d["parts"] for l in p["leads"]}
    jumps = [(strip((j["x1"] - HOLE_X0) // PITCH, ROW_Y.index(j["y1"])),
              strip((j["x2"] - HOLE_X0) // PITCH, ROW_Y.index(j["y2"])) if j["y2"] in ROW_Y else "rail") for j in d["jumpers"]]
    for net in BB["nets"]:
        leads = net[1:] if net[0] in ("+12 V", "0 V") else net
        strips = {lead_strip[l] for l in leads}
        if net[0] in ("+12 V", "0 V"):
            if any(not any(a == s and b == "rail" for a, b in jumps) for s in strips):
                problems.append(f"a strip of {net[0]} not on its rail")
        else:
            linked = {next(iter(strips))}
            for _ in strips:
                linked |= {b for a, b in jumps if a in linked} | {a for a, b in jumps if b in linked}
            if not strips <= linked:
                problems.append(f"net {net} not joined: {strips - linked}")
    brief = {"scene_id": "6", "text_overlay": {"title": "Plaque"}, "connections": [],
             "entities": [{"id": "bb", "type": "BREADBOARD", "position": [0, 0, 0], "initial_state": BB}],
             "actions": [{"at": at, "action": "set_state", "target": "bb", "state": st, "cue": "x"}
                         for at, st in ((1, {"step": 1}), (3, {"step": 4}), (6, {"step": 8}), (8, {"on": ["led"]}))]}
    SceneVisualBrief.model_validate(brief)
    data = renderer.page_data(copy.deepcopy(brief), 10, None)
    data["events"] = brief["actions"]
    found = open_pages({"b": data}, """() => {
      const p = E.bb.data.bbParts, read = t => { window.seek(t);
        return {shown: p.parts.filter(r => +r.g.getAttribute('opacity') === 1).length, step: p.step.textContent,
                led: p.parts.find(r => r.part.kind === 'LED').dome.style.fill}; };
      return {s1: read(2), s4: read(5), s8: read(8.6), lit: read(9.5), conflicts: window.layoutConflicts};
    }""")["b"]
    if [found[k]["shown"] for k in ("s1", "s4", "s8")] != [1, 4, 8] or found["s4"]["step"] != "Étape 4":
        problems.append(f"the parts not in on their steps: {found}")
    if "239, 68, 68" not in found["lit"]["led"] and "EF4444" not in found["lit"]["led"]:
        problems.append(f"the LED not lit: {found['lit']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    from models.visual_brief_schema import measure_problem, ComponentType
    types = {"bb": ComponentType.BREADBOARD, "vm": ComponentType.VOLTMETER_PROBES}
    if measure_problem({"target": "vm", "target_pin_a": "bb.ctn.left", "target_pin_b": "bb.ctn.right", "value": 2.5}, types):
        problems.append("a measure on the breadboard's leads refused")
    probed = copy.deepcopy(brief)
    probed["entities"].append({"id": "vm", "type": "VOLTMETER_PROBES", "position": [5, 2, 0], "initial_state": {"label": "Voltmètre"}})
    probed["actions"] = [{"at": 1, "action": "measure", "target": "vm", "target_pin_a": "bb.ctn.left", "target_pin_b": "bb.ctn.right",
                          "value": 2.5, "unit": "V", "cue": "x"}]
    data = renderer.page_data(probed, 6, None)
    tip = open_pages({"p": data}, """() => { window.seek(5); const m = P[0].measures[0], lead = boardLead('bb.ctn.left');
      return {tip: m.pins.a, lead: lead.pt, name: m.names.a}; }""")["p"]
    if max(abs(a - b) for a, b in zip(tip["tip"], tip["lead"])) > 1 or "CTN" not in tip["name"]:
        problems.append(f"the probe not on the CTN's lead on the board: {tip}")
    return report("3. BREADBOARD: laid out from the netlist, every net joined, parts in step by step", problems)


if __name__ == "__main__":
    results = [case_symbols(), case_steps(), case_breadboard()]
    sys.exit(0 if all(results) else 1)
