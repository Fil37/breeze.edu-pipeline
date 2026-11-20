"""
Check that a TABLE never cuts its text (the German run of 2026-11-16: "Conjonctions de subordination" and
"weil, dass, wenn, obwohl, damit, ob" were cut: a column held 340 px at most and a cell one line):
  1. a long cell widens its column (up to 560 px), then goes on two or three lines, its row taller
  2. the two tables of that run drawn: no cell cut, no layout conflict; a short table keeps its rows
  3. a cell still too long is reported in layoutConflicts ("cuts the text"), so agent004 is told
Prints PASS or FAIL per case. Cases 2 and 3 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_table_wrap.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.layout_solver import TABLE_ROW, table_heights, table_widths      # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


CONJ = {"columns": ["Conjonctions de subordination"], "rows": [["weil"], ["dass"], ["wenn"], ["obwohl"], ["damit"], ["ob"]]}
SORT = {"columns": ["Subordonnée", "Coordination"],
        "rows": [["weil, dass, wenn, obwohl, damit, ob", "—"], ["—", "denn"], ["verbe final", "verbe 2e"]]}
SHORT = {"columns": ["Année", "PIB"], "rows": [["2022", "2 640"], ["2023", "2 800"]]}


def case_sizes():
    problems = []
    if table_widths(CONJ)[0] <= 340:
        problems.append(f"the header's column stays narrow: {table_widths(CONJ)}")
    long = {"columns": ["A", "B"], "rows": [["un texte vraiment très long qui ne tiendra jamais sur une seule ligne du tableau", "x"]]}
    heights = table_heights(long)
    if heights[1] <= TABLE_ROW or table_widths(long)[0] != 560:
        problems.append(f"a long cell: widths {table_widths(long)}, heights {heights}")
    if set(table_heights(SHORT)) != {TABLE_ROW}:
        problems.append(f"a short table changed: {table_heights(SHORT)}")
    return report("1. a long cell widens its column, then wraps; a short table unchanged", problems)


def page(state, scene="2"):
    brief = {"scene_id": scene, "text_overlay": {"title": "Tableau"}, "connections": [],
             "entities": [{"id": "t", "type": "TABLE", "position": [0, -0.3, 0], "initial_state": state}], "actions": []}
    return renderer.page_data(brief, 4, None)


def case_drawn():
    problems = []
    found = open_pages({"conj": page(CONJ), "sort": page(SORT), "short": page(SHORT)}, "() => window.layoutConflicts")
    for name, conflicts in found.items():
        if conflicts:
            problems.append(f"{name}: {conflicts}")
    return report("2. the two tables of the German run drawn whole, no conflict", problems)


def case_reported():
    problems = []
    data = page(SHORT)
    data["entities"] = [dict(e) for e in data["entities"]]
    for e in data["entities"]:
        if e.get("table"):
            e["table"] = dict(e["table"], widths=[130, 130], heights=[64, 64, 64, 64],
                              rows=[["un texte bien trop long pour cent trente pixels et une ligne", "x"], ["2023", "2 800"]])
    found = open_pages({"cut": data}, "() => window.layoutConflicts")["cut"]
    if not any("cuts the text" in c for c in found):
        problems.append(f"a cut cell not reported: {found}")
    return report("3. a cell still cut is reported to agent004", problems)


if __name__ == "__main__":
    results = [case_sizes(), case_drawn(), case_reported()]
    sys.exit(0 if all(results) else 1)
