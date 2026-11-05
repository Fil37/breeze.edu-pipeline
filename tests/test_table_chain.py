"""
Check the first catalogue pieces (docs/pieces/ORDRE.md: TABLE, CHAIN), offline but for the browser:
  1. TABLE: a bad table refused; the total worked out by the program (French figures, a unit kept, a
     column of mixed units left blank); the rows in one after the other, a row picked out, the total
     shown on its state
  2. CHAIN: a bad chain refused; laid out four in a row, then a second row; the boxes in one after the
     other with their arrows; a loop back to the first, around the others
Prints PASS or FAIL per case. Needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_table_chain.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def brief(entity, actions=()):
    return {"scene_id": "2", "text_overlay": {"title": "x"}, "connections": [], "entities": [entity],
            "actions": [{"at": at, "action": "set_state", "target": entity["id"], "state": st, "cue": "x"} for at, st in actions]}


def refused(entity):
    try:
        SceneVisualBrief.model_validate(brief(entity))
        return False
    except ValueError:
        return True


def case_table():
    problems = []
    table = {"id": "t", "type": "TABLE", "position": [0, 0, 0], "initial_state": {
        "columns": ["Poste", "Montant (Md€)", "Part", "Note"],
        "rows": [["Consommation", "1 520", "54 %", "a"], ["Investissement", "650", "23 %", "b"], ["Public", "640,5", "23 %", "3"]]}}
    for bad in ({"columns": [], "rows": [["a"]]}, {"columns": ["a", "b"], "rows": [["1"]]}, {"columns": ["a"], "rows": [["1"]] * 9}):
        if not refused({**table, "initial_state": bad}):
            problems.append(f"accepted: {bad}")
    total = renderer.table_data(table["initial_state"])["total"]
    if total != ["Total", "2 810,5", "100 %", ""]:
        problems.append(f"the total: {total}")
    b = brief(table, [(4, {"row": 1}), (5, {"total": True})])
    data = renderer.page_data(b, 7, None)
    data["events"] = b["actions"]
    found = open_pages({"t": data}, """() => { const p = E.t.data.tableParts, read = t => { window.seek(t);
        return {rows: p.cells.map(r => +r[0].style.opacity), pick: p.cells.map(r => r[0].classList.contains('pick')), total: !p.total[0].hidden}; };
      return {early: read(1.0), all: read(4.5), sum: read(6), conflicts: window.layoutConflicts}; }""")["t"]
    if found["early"]["rows"][2] != 0 or found["all"]["rows"] != [1, 1, 1]:
        problems.append(f"the rows not in one after the other: {found['early']}, {found['all']}")
    if found["all"]["pick"] != [False, True, False] or found["all"]["total"] or not found["sum"]["total"]:
        problems.append(f"the row picked out, or the total: {found}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("1. TABLE: rows in turn, a row picked out, a total summed by the program", problems)


def case_chain():
    problems = []
    chain = {"id": "c", "type": "CHAIN", "position": [0, 0, 0], "initial_state": {
        "steps": ["Taux en hausse", "Crédit plus cher", "Moins d'investissement", "Moins d'embauches", "Demande en baisse"], "loop": True}}
    for bad in ({"steps": ["seul"]}, {"steps": ["a"] * 7}, {"steps": ["a", "b"], "loop": "oui"}):
        if not refused({**chain, "initial_state": bad}):
            problems.append(f"accepted: {bad}")
    z = renderer.chain_data(chain["initial_state"])
    if len({round(y) for _, y in z["centres"]}) != 2 or z["centres"][3][0] != z["centres"][0][0]:
        problems.append(f"not laid out three in a row, then a second row: {z['centres']}")
    data = renderer.page_data(brief(chain), 9, None)
    found = open_pages({"c": data}, """() => { const p = E.c.data.chainParts, read = t => { window.seek(t);
        return {boxes: p.boxes.map(b => +b.style.opacity), loop: +p.loop.getAttribute('opacity')}; };
      return {early: read(1.6), done: read(8), conflicts: window.layoutConflicts}; }""")["c"]
    if found["early"]["boxes"][4] != 0 or found["done"]["boxes"] != [1] * 5 or found["done"]["loop"] != 1:
        problems.append(f"the boxes in turn, the loop: {found}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    return report("2. CHAIN: boxes in turn with their arrows, a loop around them", problems)


if __name__ == "__main__":
    results = [case_table(), case_chain()]
    sys.exit(0 if all(results) else 1)
