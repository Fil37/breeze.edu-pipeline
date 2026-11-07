"""
Check EQUATION_STEPS solving a linear system (the pivot de Gauss: a first try drew its three-row systems
one row tall, piled on each other), offline but for the browser:
  1. each step is as tall as its system (three equations, three rows), the arrows between them, nothing
     overlapping on the page
  2. agent004: lines that keep the first system's solution are kept; a wrong row operation is sent back
     with the solution; a single equation solved step by step is not checked as a system
Prints PASS or FAIL per case. Case 1 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_gauss.py
"""

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


SYSTEM = [r"\begin{cases} x+y+z=6 \\ 2x+y-z=1 \\ x-y+2z=5 \end{cases}",
          r"\begin{cases} x+y+z=6 \\ -y-3z=-11 \\ -2y+z=-1 \end{cases}",
          r"\begin{cases} x+y+z=6 \\ -y-3z=-11 \\ 7z=21 \end{cases}",
          r"z=3,\ y=2,\ x=1"]
NOTES = ["L₂ ← L₂ − 2L₁, L₃ ← L₃ − L₁", "L₃ ← L₃ − 2L₂", "on remonte"]


def brief(steps, notes=()):
    return {"scene_id": "1", "text_overlay": {"title": "Pivot de Gauss"}, "connections": [], "actions": [],
            "entities": [{"id": "g", "type": "EQUATION_STEPS", "position": [0, 0, 0],
                          "initial_state": {"steps": steps, "notes": list(notes)}}]}


def case_page():
    problems = []
    b = brief(SYSTEM, NOTES)
    SceneVisualBrief.model_validate(b)
    data = renderer.page_data(b, 10, None)
    data["events"] = []
    found = open_pages({"g": data}, """() => { window.seek(9.5);
      const boxes = [...document.querySelectorAll('.eq')].filter(e => +e.style.opacity > 0.5).map(e => { const r = e.querySelector('.katex').getBoundingClientRect();
        return [r.top, r.bottom]; });
      return {boxes, conflicts: window.layoutConflicts}; }""")["g"]
    boxes = found["boxes"]
    if any(boxes[i][1] > boxes[i + 1][0] for i in range(len(boxes) - 1)):
        problems.append(f"steps overlap: {boxes}")
    if boxes[0][1] - boxes[0][0] < 150:
        problems.append(f"a three-row system drawn {boxes[0][1] - boxes[0][0]:.0f} px tall")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    if renderer.plain_math(r"L_3 \leftarrow L_3 - 2L_2") != "L₃ ← L₃ - 2L₂":       # the run of 2026-11-06 showed "\leftarrow"
        problems.append(f"a LaTeX note shown raw: {renderer.plain_math(r'L_3 \leftarrow L_3 - 2L_2')!r}")
    long = SYSTEM[:3] + [r"\begin{cases} x+y+z=6 \\ -y-3z=-11 \\ z=3 \end{cases}", r"\begin{cases} x+y=3 \\ y=2 \\ z=3 \end{cases}", SYSTEM[3]]
    b = brief(long, NOTES + ["L₃ ← L₃ ÷ 7", "x = 3 − y"])
    b["actions"] = [{"at": 1 + 2 * i, "action": "set_state", "target": "g", "state": {"step": i + 1}, "cue": "x"} for i in range(6)]
    data = renderer.page_data(b, 14, None)
    data["events"] = b["actions"]
    pages = open_pages({"g": data}, """() => { const read = t => { window.seek(t);
        return [...document.querySelectorAll('.eq')].filter(e => +e.style.opacity > 0.5)
          .map(e => { const r = e.querySelector('.katex').getBoundingClientRect(); return [r.top, r.bottom]; }); };
      return {first: read(6.5), last: read(13.5)}; }""")["g"]
    for name, shown in pages.items():
        if any(shown[i][1] > shown[i + 1][0] for i in range(len(shown) - 1)) or max(b for _, b in shown) > 1000:
            problems.append(f"{name} page: steps overlap or run off the screen: {shown}")
    if len(pages["first"]) != 3 or len(pages["last"]) != 2:
        problems.append(f"six three-row steps not put on pages: {pages}")
    return report("1. each step as tall as its system, none overlapping; past the room, a new page", problems)


def case_check():
    problems = []
    check = lambda steps: agent004.gauss_problems(SceneVisualBrief.model_validate(brief(steps)))
    if check(SYSTEM):
        problems.append(f"a right elimination sent back: {check(SYSTEM)}")
    wrong = check(SYSTEM[:2] + [r"\begin{cases} x+y+z=6 \\ -y-3z=-11 \\ 7z=20 \end{cases}"])
    if len(wrong) != 1 or "x = 1, y = 2, z = 3" not in wrong[0]:
        problems.append(f"a wrong row operation kept, or told without the solution: {wrong}")
    if check(SYSTEM[:3] + [r"z=3,\ y=1,\ x=2"]) == []:
        problems.append("a wrong final solution kept")
    if check(["2x + 3 = 11", "2x = 8", "x = 4"]):
        problems.append("a single equation checked as a system")
    return report("2. agent004: every line keeps the first system's solution", problems)


def case_detail():
    """The maths run of 2026-11-06: the reduction never worked out on screen, the augmented table shown with
    its first equation only, the operations shown twice."""
    from app.linear_system import linear_equations, operation_detail
    problems = []
    a = linear_equations(r"\begin{cases} 2x+y-z=8 \\ -3x-y+2z=-11 \\ -2x+y+2z=-3 \end{cases}")
    b = linear_equations(r"\begin{cases} 2x+y-z=8 \\ 0x+\frac{1}{2}y+\frac{1}{2}z=1 \\ -2x+y+2z=-3 \end{cases}")
    detail = operation_detail(a, b)
    if not detail or detail[0]["title"] != "L2 ← L2 + 3/2 L1" or detail[0]["lines"][1] != r"+\ \tfrac{3}{2}L_1 :\ 3x + \tfrac{3}{2}y - \tfrac{3}{2}z = 12" \
            or "0x" not in detail[0]["lines"][2] or "s'annule" not in detail[0]["lines"][3]:
        problems.append(f"the reduction worked out: {detail}")
    swapped = operation_detail(linear_equations(r"\begin{cases} x+y=3 \\ 2x-y=0 \end{cases}"), linear_equations(r"\begin{cases} 2x-y=0 \\ x+y=3 \end{cases}"))
    if not swapped or "↔" not in swapped[0]["title"]:
        problems.append(f"a swap: {swapped}")
    if renderer.plain_math(r"L_2 \leftarrow L_2 + \frac{3}{2}L_1") != "L₂ ← L₂ + 3/2 L₁":
        problems.append(f"a fraction in a note: {renderer.plain_math(r'L_2 \leftarrow L_2 + \frac{3}{2}L_1')!r}")
    table = {"id": "t", "type": "TABLE", "position": [-3, 0, 0], "initial_state": {"columns": ["x", "y", "z", "second membre"],
             "rows": [["2", "1", "-1", "8"], ["-3", "-1", "2", "-11"], ["-2", "1", "2", "-3"]]}}
    one = {"id": "f", "type": "TEX_FORMULA", "position": [3, 0, 0], "initial_state": {"latex": "2x+y-z=8"}}
    scene = lambda entities: SceneVisualBrief.model_validate({"scene_id": "2", "text_overlay": {"title": "Tableau"}, "connections": [],
                                                              "actions": [], "entities": entities})
    if len(agent004.system_display_problems(scene([table, one]))) != 1:
        problems.append("an augmented table with its first equation only kept")
    whole = {**one, "initial_state": {"latex": SYSTEM[0].replace("x+y+z=6", "2x+y-z=8")}}
    if agent004.system_display_problems(scene([table, {**whole, "initial_state": {"latex": r"\begin{cases} 2x+y-z=8 \\ -3x-y+2z=-11 \\ -2x+y+2z=-3 \end{cases}"}}])):
        problems.append("an augmented table with its whole system sent back")
    steps = brief(SYSTEM, NOTES)["entities"][0]
    twice = {"id": "op", "type": "TEX_FORMULA", "position": [-4, 2, 0], "initial_state": {"latex": r"L_3 \leftarrow L_3 - 2L_2"}}
    if len(agent004.system_display_problems(scene([steps, twice]))) != 1:
        problems.append("a row operation shown twice kept")
    b = brief(SYSTEM, NOTES)
    b["actions"] = [{"at": 1 + 2 * i, "action": "set_state", "target": "g", "state": {"step": i + 1}, "cue": "x"} for i in range(4)]
    data = renderer.page_data(b, 10, None)
    data["events"] = b["actions"]
    shown = open_pages({"g": data}, """() => { const read = t => { window.seek(t);
        return [...document.querySelectorAll('.eq-detail')].filter(d => +d.style.opacity > 0.5).map(d => d.querySelector('.eq-detail-title').textContent); };
      return {first: read(4), second: read(6), conflicts: window.layoutConflicts}; }""")["g"]
    if shown["first"] != ["Calcul : L2 ← L2 − 2 L1", "Calcul : L3 ← L3 − L1"][:len(shown["first"])] or not shown["first"] \
            or shown["second"] != ["Calcul : L3 ← L3 − 2 L2"] or shown["conflicts"]:
        problems.append(f"the detail on the page: {shown}")
    return report("3. each reduction worked out beside the steps; a system shown whole, its operations once", problems)


if __name__ == "__main__":
    results = [case_page(), case_check(), case_detail()]
    sys.exit(0 if all(results) else 1)
