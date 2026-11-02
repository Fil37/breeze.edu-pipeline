"""
Check the recurring defects report (app/defect_report.py) on made-up runs (no file is read or
written: rows.json and reports.json are given as data):
  1. a conflict between the same kinds of entities, under different ids, in three runs: one defect,
     in 3 runs (ids become roles, "a overlaps b" = "b overlaps a"), a label conflict kept apart
  2. a QA issue repeated by a revision of the same run: counted in 1 run, 2 times (once per run)
  3. QA issues grouped by theme, with their severities; "unsupported" grouped by what is missing
  4. why a run stopped: the critical agent's error, and the same failure in two runs adds up
     (numbers blanked out)
  5. --last keeps the newest runs; standalone runs and other channels are left out
  6. the Markdown report: the runs table and the recurring table, a defect seen once is not in it
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_defect_report.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import defect_report as report   # noqa: E402

CHANNEL = "breeze_(test)"


def row(run, agent, data, channel=CHANNEL, minute=0):
    stage = {"agent001": "research", "agent004": "storyboard", "agent005": "qa", "agent010": "render"}[agent]
    return {"run_id": run, "channel": channel, "agent": agent, "stage": stage, "data": data,
            "timestamp": f"2026-10-31T10:{minute:02d}:00+00:00", "status": "healthy"}


def render(conflicts):
    return {"video_path": "/x/video.mp4", "scenes": [{"scene_id": 1, "layout_conflicts": conflicts}], "warnings": []}


ORBIT = "Scène 5 : l’orbite est représentée par une sinusoïde, pas par une trajectoire fermée."
ROWS = [
    row("R1", "agent001", {"concept": "Orbite"}, minute=1),
    row("R1", "agent010", render(["arrow_slow overlaps arrow_earth"]), minute=2),
    row("R1", "agent005", {"verdict": "reject", "issues": [{"text": ORBIT, "severity": "blocking"}],
                           "unsupported": ["Terre et Soleil"]}, minute=3),
    row("R1", "agent005", {"verdict": "reject", "issues": [{"text": ORBIT, "severity": "blocking"}]}, minute=4),
    row("R2", "agent010", render(["note_2 overlaps arrow_a (label)", "badge_x overlaps arrow_y"]), minute=10),
    row("R2", "agent005", {"verdict": "pass", "issues": [{"text": "La flèche « Gravité » pointe vers le bas au lieu de la Terre.",
                                                          "severity": "corrected"}], "unsupported": ["Une planète en rotation"]}, minute=11),
    row("R3", "agent010", render(["arrow_earth overlaps arrow_slow", "formula_1 overlaps axes_2"]), minute=20),
    row("R4", "agent001", {"concept": "Autre"}, minute=30),
    row("standalone", "agent010", render(["arrow_a overlaps arrow_b"]), minute=40),
    row("R9", "agent010", render(["arrow_a overlaps arrow_b"]), channel="breeze_(other)", minute=41),
]
REPORTS = [
    {"run_id": "R1", "channel": CHANNEL, "agents": {"agent005": "critical", "agent010": "not_run"},
     "errors": ["agent005: revision 1 -> agent004: ...", "agent005: still rejected after 3 revisions"]},
    {"run_id": "R2", "channel": CHANNEL, "agents": {"agent005": "healthy", "agent010": "not_healthy"}, "errors": []},
    {"run_id": "R3", "channel": CHANNEL, "agents": {"agent001": "critical"}, "errors": ["agent001: gemini call failed: Error code: 429"]},
    {"run_id": "R4", "channel": CHANNEL, "agents": {"agent001": "critical"}, "errors": ["agent001: gemini call failed: Error code: 503"]},
]


def find(groups, source, defect):
    return next((g for g in groups if g["source"] == source and g["defect"] == defect), None)


def check(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


runs = report.collect(ROWS, REPORTS, CHANNEL, 10)[CHANNEL]
groups = report.recurring(runs, min_runs=1)[0]
results = []

g = find(groups, "Rendu : conflit", "badge chevauche badge")
results.append(check("1. the same conflict under other ids, in 3 runs: one defect", [] if g and g["runs"] == 3 and g["count"] == 3
                     else [f"got {g and (g['runs'], g['count'])}, expected 3 runs, 3 times"]))

theme = "courbe, trajectoire ou repère qui ne correspond pas"
g = find(groups, "QA : issue", theme)
results.append(check("2. an issue repeated by a revision: 1 run, 2 times", [] if g and g["runs"] == 1 and g["count"] == 2
                     and g["severities"] == {"blocking": 2} else [f"got {g}"]))

problems = []
if not find(groups, "QA : issue", "flèche ou vecteur mal orienté ou mal placé"):
    problems.append("the arrow issue is not in its theme")
astres = find(groups, "QA : impossible à dessiner", "astres (Terre, Soleil, Lune, planètes)")
if not astres or astres["runs"] != 2:
    problems.append(f"'Terre et Soleil' and 'Une planète' not grouped as astres in 2 runs: {astres}")
if not find(groups, "Rendu : conflit", "badge chevauche badge (étiquette)"):
    problems.append("a label conflict is not told apart")
results.append(check("3. QA issues by theme, unsupported by what is missing", problems))

g = find(groups, "Run : arrêt (agent001)", "agent001: gemini call failed: Error code: N")
stop = runs[0]["stopped_by"]
results.append(check("4. why runs stopped: the critical agent's error, the same failure adds up",
                     ([] if g and g["runs"] == 2 else [f"the 429 and 503 failures not grouped: {g}"])
                     + ([] if stop == "agent005: still rejected after 3 revisions" else [f"R1 stopped by {stop!r}"])))

newest = report.collect(ROWS, REPORTS, CHANNEL, 2)[CHANNEL]
problems = []
if [r["run_id"] for r in newest] != ["R3", "R4"]:
    problems.append(f"--last 2 kept {[r['run_id'] for r in newest]}, expected R3, R4")
if [r["run_id"] for r in runs] != ["R1", "R2", "R3", "R4"]:
    problems.append(f"runs {[r['run_id'] for r in runs]}: standalone or another channel slipped in")
results.append(check("5. --last keeps the newest; standalone and other channels left out", problems))

text = report.markdown({CHANNEL: runs}, min_runs=2)
problems = [f"missing {part!r}" for part in ("| R1 | Orbite | critical (agent005) | oui | 1 | agent005: still rejected after 3 revisions |",
                                             "| 3/4 | 3 | Rendu : conflit | badge chevauche badge |") if part not in text]
if "formule chevauche graphique |" in text.split("## Vus dans un seul run")[0]:
    problems.append("a defect seen in one run is in the recurring table")
results.append(check("6. Markdown: the runs table, the recurring table only", problems))
sys.exit(0 if all(results) else 1)
