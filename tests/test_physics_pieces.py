"""
Check the first physics pieces (FREE_BODY, KINEMATICS, COLLISION, OSCILLATOR, ORBIT), offline but for the
browser: their figures worked out by the program (resultant, flight, velocities after a collision with
momentum kept, period), bad states refused, the five drawn with no page error and no conflict.
Prints PASS or FAIL per case. Case 2 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_physics_pieces.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import phys_piece_problem               # noqa: E402
from test_reactive import open_pages                                    # noqa: E402

STATES = {"FREE_BODY": {"mass": 2, "incline": 30, "forces": [{"name": "Poids", "symbol": "P", "x": 0, "y": -19.6},
                                                             {"name": "Réaction", "symbol": "R", "x": -8.49, "y": 14.7}]},
          "KINEMATICS": {"kind": "projectile", "v0": [10, 8]},
          "COLLISION": {"m1": 2, "v1": 5, "m2": 3, "v2": -2, "type": "elastic"},
          "OSCILLATOR": {"kind": "spring", "k": 100, "m": 1},
          "ORBIT": {"e": 0.6}}


def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_worked_out():
    problems, d = [], renderer.phys_data
    c = d("COLLISION", STATES["COLLISION"])
    if (round(c["u1"], 6), round(c["u2"], 6)) != (-3.4, 3.6) or abs(2 * c["u1"] + 3 * c["u2"] - 4) > 1e-9:
        problems.append(f"elastic collision: {c['u1']}, {c['u2']}")
    inel = d("COLLISION", {**STATES["COLLISION"], "type": "inelastic"})
    if abs(inel["u1"] - 0.8) > 1e-9 or "perdus" not in inel["verdict"]:
        problems.append(f"inelastic collision: {inel['u1']}, {inel['verdict']}")
    if abs(d("OSCILLATOR", STATES["OSCILLATOR"])["T"] - 2 * math.pi / 10) > 1e-9:
        problems.append("spring period")
    # the exact period: at 10°, 0,19 % over 2π √(L / g)
    if abs(d("OSCILLATOR", {"kind": "pendulum", "L": 1, "theta0": 10, "g": 9.8})["T"] / (2 * math.pi * math.sqrt(1 / 9.8)) - 1.0019) > 0.0002:
        problems.append("pendulum period")
    if "1,63 s" not in d("KINEMATICS", STATES["KINEMATICS"])["text"]:
        problems.append(f"flight time: {d('KINEMATICS', STATES['KINEMATICS'])['text']}")
    orbit = d("ORBIT", {"e": 0.6, "central": "Soleil"})       # (1 + 0.6) / (1 - 0.6) = 4
    if not ("= 4" in orbit["ratio"][0] and "v_P = 4 × v_A" in orbit["ratio"][1] and "périhélie" in orbit["near"]):
        problems.append(f"orbit: P, A and the speed ratio {orbit}")
    if "4,9 m/s²" not in d("FREE_BODY", STATES["FREE_BODY"])["sum_text"]:
        problems.append(f"resultant: {d('FREE_BODY', STATES['FREE_BODY'])['sum_text']}")
    for kind, bad in (("COLLISION", {"m1": 1, "v1": -1, "m2": 1, "v2": 1}), ("ORBIT", {"e": 0.95}),
                      ("KINEMATICS", {"kind": "projectile", "v0": [5, -1]}), ("FREE_BODY", {"forces": []})):
        if phys_piece_problem(kind, bad) is None:
            problems.append(f"accepted {kind}: {bad}")
    return report("1. resultant, flight, collision (momentum kept), periods worked out by the program", problems)


def case_drawn():
    problems, pages = [], {}
    for kind, state in STATES.items():
        brief = {"scene_id": "2", "text_overlay": {"title": kind}, "connections": [],
                 "entities": [{"id": "x", "type": kind, "position": [0, -0.3, 0], "initial_state": state}], "actions": []}
        pages[kind] = renderer.page_data(brief, 6, None)
    for kind, f in open_pages(pages, "() => { window.seek(4); return {c: window.layoutConflicts, p: !!E.x.data.physParts}; }").items():
        if f["c"] or not f["p"]:
            problems.append(f"{kind}: {f}")
    return report("2. the five physics pieces drawn and moving, no conflict", problems)


def case_pendulum():
    """The physics run of 2026-11-06: pendulums of 5° and 45° both showed 2,01 s (the small-angle formula),
    swung at one pace, and a long title ran over its subtitle."""
    problems = []
    big, small = (renderer.phys_data("OSCILLATOR", {"kind": "pendulum", "L": 1, "theta0": th}) for th in (45, 5))
    if abs(big["T"] / small["T"] - 1.0400 / 1.0002) > 0.002 or "2,09 s" not in big["period"] or "2π √(L / g) = 2,01 s" not in small["period"]:
        problems.append(f"exact periods: {big['T']}, {big['period']}; {small['T']}, {small['period']}")
    if not any("0,707" in line for line in big["details"]) or not any("10 %" in line for line in big["details"]):
        problems.append(f"the angle and its sine not shown: {big['details']}")
    title = "Pourquoi la période d’un pendule augmente-t-elle avec l’amplitude ?"
    brief = {"scene_id": "2", "text_overlay": {"title": title, "subtitle": "Petits et grands balancements"}, "connections": [],
             "entities": [{"id": i, "type": "OSCILLATOR", "position": [x, -0.3, 0], "initial_state": {"kind": "pendulum", "L": 1, "theta0": th}}
                          for i, x, th in (("p5", -3, 5), ("p45", 3, 45))],
             "actions": [{"at": 0.5, "action": "set_state", "target": i, "state": st, "cue": "x"}
                         for i in ("p5", "p45") for st in ({"go": True}, {"period": True}, {"count": 10})]}
    data = renderer.page_data(brief, 8, None)
    data["events"] = brief["actions"]
    found = open_pages({"p": data}, """() => { window.seek(7);
      const t = TITLE.getBoundingClientRect(), s = SUBTITLE.getBoundingClientRect();
      return {gap: s.top - t.bottom, count: E.p45.data.physParts.count.textContent, x5: +E.p5.data.physParts.bob.getAttribute('cx'),
              x45: +E.p45.data.physParts.bob.getAttribute('cx'), conflicts: window.layoutConflicts}; }""")["p"]
    if found["gap"] < 0:
        problems.append(f"the title runs over its subtitle by {-found['gap']:.0f} px")
    if found["count"] != "10 oscillations : 10 × 2,09 s = 20,9 s":
        problems.append(f"ten oscillations timed: {found['count']!r}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("3. a pendulum's exact period at its angle, its sine shown, ten oscillations timed; the title on one line", problems)


if __name__ == "__main__":
    sys.exit(0 if all([case_worked_out(), case_drawn(), case_pendulum()]) else 1)
