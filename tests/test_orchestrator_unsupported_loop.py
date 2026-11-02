"""
Check that the orchestrator stops, instead of redoing agent004 again and again, when the QA rejects
to agent004 for something the renderer cannot show (the breeze_(math) run of 2026-10-31: "une orbite
fermée n'est pas représentable", agent004 redone 3 times for nothing, 25 minutes lost).
The real run_channel() of agent000 runs on a test channel with mocked agents; the mocked agent005
writes the qa.json of each case. Everything is written in a temporary folder: instance/ and schemas/
are never touched.
  1. blocking issue "... is not representable ..." (reject_to agent004), every time: agent004 runs
     once, never again; agent005 critical "Renderer limitation: ..."; nothing rendered
  2. the same said in the rejection notes only, in French ("n'est pas représentable avec les entités
     autorisées", with "unsupported" listed): the same stop
  3. a blocking issue agent004 can fix (a wrong arrow), with "unsupported" listed (the QA lists it
     even when the narration carries it): agent004 is redone, the QA passes, the video is rendered
  4. a renderer limit but reject_to agent003 (a rewrite can avoid it): agent003 + agent004 are redone
Also checks agent004's coherence message on a formula label (case 5): readable ("Tension U") for the
quantities it knows by name, no rule for the others (F: no "F F" message).
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_orchestrator_unsupported_loop.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
import app.agent as helpers                                       # noqa: E402
from app import provenance                                        # noqa: E402
from app.agent import agent000_breeze as orchestrator             # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004   # noqa: E402
from models.visual_brief_schema import SceneVisualBrief           # noqa: E402

CHANNEL = "breeze_(test)"
ROUTE = {"channel_id": CHANNEL, "name": "Test", "domain": "physics_math", "schedule_cron": "0 6 * * *", "enabled": True}
ORBIT = "Scene 5: a closed orbit around the Earth is not representable with the allowed components."
ARROW = {"scene_id": "2", "text": "Scène 2 : la flèche pointe vers le bas au lieu de la formule.", "kind": "factual",
         "severity": "blocking", "fixed_by": []}
UNSUPPORTED = ["Une orbite fermée (cercle) autour d'une Terre sphérique"]


def qa(reject_to, notes, blocking_texts=(), unsupported=()):
    issues = [{"scene_id": "5", "text": t, "kind": "factual", "severity": "blocking", "fixed_by": []} for t in blocking_texts]
    return {"verdict": "reject", "reject_to": reject_to, "rejection_notes": notes, "issues": issues,
            "blocking_count": len(issues), "unsupported": list(unsupported)}


def run_case(answers):
    """run_channel() with mocked agents; agent005 writes answers[i] on its i-th call (the last one
    again after that; None: it passes). Returns ({agent: calls}, statuses, stdout)."""
    calls = {}
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, CHANNEL)
        os.makedirs(folder)

        def agent(name):
            def run(channel_id, settings, routes):
                calls[name] = calls.get(name, 0) + 1
                if name != "agent005":
                    return {"status": "healthy", "output_path": None, "error": None}
                answer = answers[min(calls[name], len(answers)) - 1]
                with open(os.path.join(folder, "qa.json"), "w", encoding="utf-8") as f:
                    json.dump(answer or {"verdict": "pass", "issues": []}, f, ensure_ascii=False)
                return {"status": "revision_needed" if answer else "healthy", "output_path": None, "error": None}
            return run

        def db_connect():                               # the real tables, in the temporary folder
            saved = helpers.DB_PATH, helpers.INSTANCE_DIR
            helpers.DB_PATH, helpers.INSTANCE_DIR = os.path.join(root, "breeze.db"), root
            try:
                return saved_db_connect()
            finally:
                helpers.DB_PATH, helpers.INSTANCE_DIR = saved

        saved_db_connect = orchestrator.db_connect
        patched = {"AGENTS": {name: agent(name) for name in orchestrator.AGENTS},
                   "INSTANCE_DIR": root, "REPORTS_PATH": os.path.join(root, "reports.json"),
                   "ROWS_PATH": os.path.join(root, "rows.json"), "db_connect": db_connect,
                   "log_status": lambda *args, **kwargs: None}
        originals = {name: getattr(orchestrator, name) for name in patched}
        instance_dir = provenance.INSTANCE_DIR
        output = io.StringIO()
        try:
            for name, value in patched.items():
                setattr(orchestrator, name, value)
            provenance.INSTANCE_DIR = root
            with contextlib.redirect_stdout(output):
                statuses, _overall = orchestrator.run_channel(ROUTE, {"max_revisions": 3, "render_engine_by_channel": {CHANNEL: "html"}},
                                                              [ROUTE], "20261031T000000Z", "healthy")
        finally:
            for name, original in originals.items():
                setattr(orchestrator, name, original)
            provenance.INSTANCE_DIR = instance_dir
            os.environ.pop(provenance.RUN_ID_ENV, None)
    return calls, statuses, output.getvalue()


def check(label, answers, expected_calls, expected_005, stop_line):
    calls, statuses, output = run_case(answers)
    problems = []
    for name, count in expected_calls.items():
        if calls.get(name, 0) != count:
            problems.append(f"{name} ran {calls.get(name, 0)} time(s), expected {count}")
    if statuses.get("agent005") != expected_005:
        problems.append(f"agent005 is {statuses.get('agent005')!r}, expected {expected_005!r}")
    stopped = "Renderer limitation:" in output
    if stopped != stop_line:
        problems.append("no 'Renderer limitation' stop" if stop_line else "stopped though agent004 can fix it")
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {p}" for p in problems))
    print("      " + ", ".join(f"{n[-3:]}x{c}" for n, c in sorted(calls.items())) + " | statuses: "
          + " ".join(f"{n[-3:]}:{s}" for n, s in statuses.items()))
    for line in output.splitlines():
        if "revision" in line or "stopped" in line:
            print(f"      log: {line.strip()[:220]}")
    return not problems


def check_message():
    """agent004's label rule: readable for U, nothing for F."""
    def brief(latex, text):
        return SceneVisualBrief.model_validate({
            "scene_id": "1", "text_overlay": {"title": "t"}, "connections": [],
            "entities": [{"id": "formula", "type": "TEX_FORMULA", "position": "CENTER", "initial_state": {"latex": latex}},
                         {"id": "note", "type": "ARROW_ANNOTATION", "position": [0, -0.6, 0],
                          "initial_state": {"text": text, "direction": "UP", "target": "formula"}}],
            "actions": [{"at": 0.5, "action": "spawn", "target": "formula", "cue": "la"},
                        {"at": 1.0, "action": "spawn", "target": "note", "cue": "formule"}]})
    narration = "Voici la formule."
    label_errors = lambda errors: [e for e in errors if "must name it" in e]   # noqa: E731
    u = label_errors(agent004.coherence_problems(brief("U = R I", "Regardez ici"), narration))
    f = label_errors(agent004.coherence_problems(brief("F = G m M / r^2", "Pas d'air requis"), narration))
    problems = []
    if len(u) != 1 or 'e.g. "Tension U"' not in u[0]:
        problems.append(f"U: {u}")
    if f:
        problems.append(f"F: a rule for a quantity it does not know by name: {f}")
    print(f'{"FAIL" if problems else "PASS"}  5. agent004 label message: readable for U, no rule for F'
          + "".join(f"\n      {m}" for m in u) + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


RENDER = {"agent010": 0, "agent007": 0}
results = [
    check("1. blocking 'not representable' (reject_to agent004): stop, agent004 not redone",
          [qa("agent004", "The storyboard cannot be fixed.", [ORBIT])],
          {"agent004": 1, "agent005": 1, **RENDER}, "critical", True),
    check("2. the same in French, in the notes only (with unsupported): stop",
          [qa("agent004", "Le script est correct, mais une orbite fermée autour de la Terre n’est pas représentable "
                          "avec les entités autorisées.", unsupported=UNSUPPORTED)],
          {"agent004": 1, "agent005": 1, **RENDER}, "critical", True),
    check("3. fixable blocking issue (with unsupported listed): agent004 redone, then rendered",
          [{**qa("agent004", "Scène 2 : flèche à corriger.", unsupported=UNSUPPORTED), "issues": [ARROW]}, None],
          {"agent004": 2, "agent005": 2, "agent010": 1}, "healthy", False),
    check("4. renderer limit but reject_to agent003: the rewrite is tried",
          [qa("agent003", "La narration décrit une orbite qui n'est pas représentable : réécrire la scène 5.", [ORBIT]), None],
          {"agent003": 2, "agent004": 2, "agent005": 2, "agent010": 1}, "healthy", False),
    check_message(),
]
sys.exit(0 if all(results) else 1)
