"""
Check AOP circuits (the AOP run of 2026-11-07: every supply read 0,00 V, two circuits tangled in one
scene, resistors with no value, a follower whose wires seemed to join both inputs), offline but for the
browser:
  1. agent004: the voltages worked out from the circuit drawn (an ideal AOP: inverting -R2/R1, non-
     inverting 1 + R2/R1, follower, comparator, the output within its supplies); a wrong reading, two
     AOP circuits in a scene, resistors with no value are sent back
  2. layout_solver: one AOP circuit as in a course (feedback over the AOP, the input resistor on the
     left at the - input's height, the supply only feeding the AOP a "+12 V" symbol on its pin, a
     junction between two leads one wire)
  3. the page: a supply on from its initial_state shows its voltage; no overlap; no wire running
     through the AOP
Prints PASS or FAIL per case. Case 3 needs Playwright + Chromium (as agent010).

  .venv/bin/python app/tests/test_opamp.py
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.layout_solver import place_opamp, solve_layout, split_rails                 # noqa: E402
from app.models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def part(id_, type_, label=None, **state):
    return {"id": id_, "type": type_, "position": [0, 0, 0], "initial_state": {**({"label": label} if label else {}), **state}}


def wire(a, b):
    (sa, pa), (sb, pb) = a.split("."), b.split(".")
    return {"source_id": sa, "source_port": pa, "target_id": sb, "target_port": pb}


def circuit(kind, dual=True, measure=None):
    """An AOP circuit of `kind` (inv, ninv, follower, comparator), Ve = 2 V, supplies ±12 V (dual) or 0 / 12 V."""
    entities = [part("u", "OPAMP", "AOP"), part("ve", "POWER_SUPPLY", "Ve", voltage=2, output=True),
                part("ps", "POWER_SUPPLY", "+12 V", voltage=12, output=True), part("g", "CHASSIS_MASS", "0 V"),
                part("r1", "RESISTOR", "R1 10 kΩ"), part("r2", "RESISTOR", "R2 20 kΩ"),
                part("m", "VOLTMETER_PROBES", "Voltmètre")]
    wires = [wire("ve.negative", "g.terminal"), wire("ps.positive", "u.vcc"), wire("ps.negative", "g.terminal")]
    if dual:
        entities.append(part("pn", "POWER_SUPPLY", "-12 V", voltage=12, output=True))
        wires += [wire("pn.positive", "g.terminal"), wire("pn.negative", "u.gnd")]
    else:
        wires.append(wire("u.gnd", "g.terminal"))
    if kind == "inv":
        wires += [wire("ve.positive", "r1.left"), wire("r1.right", "u.in_minus"), wire("u.in_minus", "r2.left"),
                  wire("r2.right", "u.out"), wire("u.in_plus", "g.terminal")]
    elif kind == "ninv":
        wires += [wire("ve.positive", "u.in_plus"), wire("u.in_minus", "r1.left"), wire("r1.right", "g.terminal"),
                  wire("u.in_minus", "r2.left"), wire("r2.right", "u.out")]
    else:
        entities = [e for e in entities if e["id"] not in ("r1", "r2")]
        wires.append(wire("ve.positive", "u.in_plus"))
        if kind == "follower":
            entities.append(part("j", "WIRE_BUS"))
            wires += [wire("u.out", "j.in"), wire("j.out", "u.in_minus")]
        else:
            entities.append(part("vr", "POWER_SUPPLY", "Vref", voltage=1, output=True))
            wires += [wire("vr.positive", "u.in_minus"), wire("vr.negative", "g.terminal")]
    actions = [] if measure is None else [{"at": 1, "action": "measure", "target": "m", "target_pin_a": "u.out",
                                           "target_pin_b": "g.terminal", "value": measure, "unit": "V", "cue": "x"}]
    return {"scene_id": "1", "text_overlay": {"title": kind}, "entities": entities, "connections": wires, "actions": actions}


def case_worked_out():
    problems = []
    for kind, dual, want in (("inv", True, -4), ("inv", False, 0), ("ninv", True, 6), ("follower", True, 2), ("comparator", False, 12)):
        out = agent004.circuit_volts(SceneVisualBrief.model_validate(circuit(kind, dual)), 1)["u.out"]
        if abs(out - want) > 1e-6:
            problems.append(f"{kind} ({'±12' if dual else '0/12'} V): {out:.3g} V, expected {want} V")
    wrong = agent004.aop_problems(SceneVisualBrief.model_validate(circuit("ninv", measure=4)))
    if len(wrong) != 1 or "6 V" not in wrong[0]:
        problems.append(f"a wrong reading kept, or told without the right one: {wrong}")
    if agent004.aop_problems(SceneVisualBrief.model_validate(circuit("ninv", measure=6))):
        problems.append("a right reading sent back")
    bare = circuit("inv")
    for e in bare["entities"]:
        if e["type"] == "RESISTOR":
            e["initial_state"]["label"] = e["id"].upper()
    if not any("no value" in p for p in agent004.aop_problems(SceneVisualBrief.model_validate(bare))):
        problems.append("resistors with no value kept")
    two = circuit("follower")
    two["entities"].append(part("u2", "OPAMP", "AOP"))
    if not any("2 AOP circuits" in p for p in agent004.aop_problems(SceneVisualBrief.model_validate(two))):
        problems.append("two AOP circuits in one scene kept")
    # the AOP course of 2026-11-09: no supply on 5 AOPs, an inverter on 0 / +12 V announcing -2,5 V
    bare = circuit("inv", dual=False, measure=-4)
    bare["connections"] = [c for c in bare["connections"] if "ps" not in (c["source_id"], c["target_id"])]
    bare["entities"] = [e for e in bare["entities"] if e["id"] != "ps"]
    added = agent004.power_opamps([bare])
    if len(added) != 2 or agent004.aop_problems(SceneVisualBrief.model_validate(bare)):
        problems.append(f"an unpowered inverter not given +12 V and -12 V by the program: {added}, "
                        f"{agent004.aop_problems(SceneVisualBrief.model_validate(bare))}")
    follower = circuit("follower", dual=False)
    if agent004.power_opamps([follower]):
        problems.append("a powered follower given another supply")
    return report("1. agent004: the AOP's output worked out (gains, follower, comparator, saturation); wrong readings sent back; "
                  "an AOP powered by the program", problems)


def case_layout():
    problems = []
    b = circuit("inv", dual=False)
    split_rails(b)                                         # as solve_layout: one ground symbol a part first
    laid = place_opamp(b)
    at = {e["id"]: e for e in b["entities"]}
    if not laid or "u" not in laid:
        return report("2. layout_solver: an AOP circuit as in a course", ["not laid out"])
    ux, uy = at["u"]["position"][:2]
    if not (at["r2"]["position"][1] > uy + 1 and abs(at["r2"]["position"][0] - ux) < 0.5):
        problems.append(f"the feedback resistor not over the AOP: {at['r2']['position']} vs {at['u']['position']}")
    if not (at["r1"]["position"][0] < ux - 1.5 and abs(at["r1"]["position"][1] - (uy + 0.24)) < 0.2):
        problems.append(f"the input resistor not on the left at the - input: {at['r1']['position']}")
    # its supply not wired as in a course: written under the AOP, the supply and its 0 V gone
    if "ps" in at or at["u"]["initial_state"].get("label") != "alimentation +12 V" or any("u" in (c["source_id"], c["target_id"])
            and {c["source_port"], c["target_port"]} & {"vcc", "gnd"} for c in b["connections"]):
        problems.append(f"the AOP's supply not written under it: {at['u']}, {[c for c in b['connections'] if 'u' in (c['source_id'], c['target_id'])]}")
    if not at["u"]["initial_state"].get("plus_top") is False or at["r2"]["position"][1] < uy:
        problems.append("an inverting amplifier not drawn - on top, its feedback over it")
    n = circuit("ninv")
    split_rails(n)
    place_opamp(n)
    nat = {e["id"]: e for e in n["entities"]}
    if not nat["u"]["initial_state"].get("plus_top") or nat["r2"]["position"][1] > nat["u"]["position"][1] \
            or nat["u"]["initial_state"].get("label") != "±12 V":
        problems.append(f"a non-inverting amplifier not drawn + on top, its feedback under it, ±12 V: {nat['u']}, {nat['r2']['position']}")
    f = circuit("follower")
    split_rails(f)
    place_opamp(f)
    if any(e["type"] == "WIRE_BUS" for e in f["entities"]) or not any(
            {c["source_id"], c["target_id"]} == {"u"} and {c["source_port"], c["target_port"]} == {"out", "in_minus"} for c in f["connections"]):
        problems.append("the follower's junction not made one wire from the output to the - input")
    SceneVisualBrief.model_validate(b)
    # Rf wired left lead to the output (the run of 2026-11-08): turned round, its two wires no longer cross
    from app.layout_solver import orient_parts
    t = circuit("inv", dual=False)
    t["connections"] = [c if not ({c["source_id"], c["target_id"]} == {"u", "r2"}) else
                        ({**c, "source_port": "left", "target_id": "u", "target_port": "out"} if c["source_id"] == "r2" and c["target_port"] == "out"
                         else c) for c in t["connections"]]
    t["connections"] = [c for c in t["connections"] if "r2" not in (c["source_id"], c["target_id"])] + [
        wire("u.out", "r2.left"), wire("r2.right", "u.in_minus")]
    split_rails(t)
    place_opamp(t)
    if orient_parts(t) != ["r2"] or not any(c["source_id"] == "u" and c["source_port"] == "out" and c["target_port"] == "right" for c in t["connections"]):
        problems.append(f"a feedback resistor wired backwards not turned round: {t['connections']}")
    return report("2. layout_solver: an AOP circuit as in a course (+ on top when the signal comes in by it); its supply written under it; "
                  "a resistor wired backwards turned round", problems)


def case_page():
    problems = []
    b = circuit("follower", dual=False, measure=2)
    solve_layout(b, [], "circuit")
    data = renderer.page_data(b, 4, None)
    data["events"] = b["actions"]
    found = open_pages({"f": data}, """() => { window.seek(3.5);
      const amp = E.u.shape.getBoundingClientRect(), inner = {l: amp.left + 20, r: amp.right - 20, t: amp.top + 20, b: amp.bottom - 20};
      const through = W.filter(w => w.pts.some((p, i) => i && [0, 1, 2, 3, 4, 5, 6, 7, 8].some(k => {
        const x = w.pts[i - 1][0] + (p[0] - w.pts[i - 1][0]) * k / 8, y = w.pts[i - 1][1] + (p[1] - w.pts[i - 1][1]) * k / 8;
        return x > inner.l && x < inner.r && y > inner.t && y < inner.b; }))).length;
      return {ve: E.ve.data.simpleParts ? E.ve.data.simpleParts.volts.textContent : document.querySelector('[data-id=ve]')?.textContent,
              screens: [...document.querySelectorAll('.simple text')].map(t => t.textContent).filter(t => / V$/.test(t)),
              through, conflicts: window.layoutConflicts}; }""")["f"]
    if "2,00 V" not in found["screens"]:
        problems.append(f"the input supply on from its initial_state does not show 2,00 V: {found['screens']}")
    if found["through"]:
        problems.append(f"{found['through']} wires run through the AOP")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("3. the page: a supply on from the start shows its voltage, no wire through the AOP, no overlap", problems)


if __name__ == "__main__":
    results = [case_worked_out(), case_layout(), case_page()]
    sys.exit(0 if all(results) else 1)
