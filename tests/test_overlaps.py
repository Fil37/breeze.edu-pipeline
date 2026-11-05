"""
Check what keeps a frame clear (the four videos of 2026-11-05: a plan of ten chapters over the titles,
a grid of people over a graph, two badges counted as overlapping though never shown together), offline
but for the browser:
  1. the plan: PLAN_PAGE chapters a page, the next page in place of the last when its first chapter
     is named
  2. two things put on the same spot, too big to be pushed apart: the bigger one (not a graph) is made
     smaller until they no longer overlap; two badges never on screen together are no conflict
Prints PASS or FAIL per case. Needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_overlaps.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_plan():
    problems = []
    plan = {"items": [(i + 2, f"Chapitre {i + 2}", None) for i in range(10)], "source": "script"}
    data = renderer.plan_page_data(plan, None, 20, 20, renderer.DEFAULT_STYLE)
    times = [p["at"] for p in data["plan"]]
    found = open_pages({"p": data}, f"""() => {{ const read = t => {{ window.seek(t); return PLAN.map(p => p.row.hidden ? 0 : 1).join(''); }};
      return [read({times[2]}), read({times[7] + 0.1})]; }}""")["p"]
    if found != ["1111110000", "0000001111"]:
        problems.append(f"the plan's pages: {found}")
    return report("1. a long plan goes over pages, the next one when its first chapter is named", problems)


def case_crowded():
    problems = []
    brief = {"scene_id": "2", "text_overlay": {"title": "Une population"}, "connections": [],
             "entities": [{"id": "pop", "type": "POPULATION", "position": [-1, 0.5, 0],
                           "initial_state": {"total": 100, "groups": [{"id": "a", "label": "Actifs", "count": 55}]}},
                          {"id": "big", "type": "OBJECT", "position": [-1, 0.2, 0], "initial_state": {"icon": "users", "label": "Habitants"}},
                          {"id": "n1", "type": "ARROW_ANNOTATION", "position": [3, 1, 0], "initial_state": {"text": "Avant", "target": "big"}},
                          {"id": "n2", "type": "ARROW_ANNOTATION", "position": [3, 1, 0], "initial_state": {"text": "Après", "target": "big"}}],
             "actions": [{"at": 1, "action": "spawn", "target": "n1", "cue": "x"}, {"at": 3, "action": "fade_out", "target": "n1", "cue": "x"},
                         {"at": 5, "action": "spawn", "target": "n2", "cue": "x"}]}
    data = renderer.page_data(brief, 8, None)
    found = open_pages({"c": data}, "() => window.layoutConflicts")["c"]
    if found:
        problems.append(f"still overlapping, or badges never shown together counted: {found}")
    return report("2. what cannot be pushed apart is made smaller; badges at different times are no conflict", problems)


if __name__ == "__main__":
    results = [case_plan(), case_crowded()]
    sys.exit(0 if all(results) else 1)
