"""
Check that the orchestrator hands the QA's feedback to the agents it redoes after a reject, in
LBREEZE_QA_FEEDBACK, and only for that redo. The real run_channel() of agent000 runs on a test
channel with mocked agents (they record LBREEZE_QA_FEEDBACK when they are called); everything the
orchestrator writes (reports.json, rows.json, breeze.db, breeze.json, manifest.json, qa.json) goes to
a temporary folder: instance/ and schemas/ are never touched.
The mocked agent005 rejects once (its qa.json: rejection_notes, one blocking and one corrected
issue, blocking_count=1), then passes.
  1. reject_to "agent004": agent004's second run gets the feedback (notes, the 1 blocking issue,
     revision 1), its first run and agent005's second run do not, and it is cleared afterwards;
     the log says "feedback transmis (1 blocking issues)"
  2. reject_to "agent003": agent003 and agent004 both get it on their redo
  3. no reject_to in qa.json: the redo happens as before, without feedback
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_orchestrator_qa_feedback.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
import app.agent as helpers                       # noqa: E402
from app import provenance                        # noqa: E402
from app.agent import agent000_breeze as orchestrator   # noqa: E402

CHANNEL = "breeze_(test)"
ROUTE = {"channel_id": CHANNEL, "name": "Test", "domain": "electronics", "schedule_cron": "0 6 * * *", "enabled": True}
ENV = orchestrator.QA_FEEDBACK_ENV
NOTES = "Scène 5 : la formule de la puissance est fausse."
BLOCKING = {"scene_id": "5", "text": "Scène 5 : P = U + I au lieu de P = U × I.", "kind": "factual",
            "severity": "blocking", "fixed_by": []}
CORRECTED = {"scene_id": "2", "text": "Scène 2 : étiquette corrigée.", "kind": "factual", "severity": "corrected",
             "fixed_by": ["scene 2: lamp_1.label = 'Lampe'"]}


def run_case(reject_to):
    """run_channel() with mocked agents; returns ({agent: [LBREEZE_QA_FEEDBACK at each call]}, stdout,
    the variable after the run)."""
    seen = {}
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, CHANNEL)
        os.makedirs(folder)

        def agent(name):
            def run(channel_id, settings, routes):
                seen.setdefault(name, []).append(os.environ.get(ENV))
                status = "healthy"
                if name == "agent005":                  # rejects the first time, then passes
                    first = len(seen[name]) == 1
                    qa = {"verdict": "reject" if first else "pass", "rejection_notes": NOTES if first else "",
                          "issues": [BLOCKING, CORRECTED] if first else [], "blocking_count": 1 if first else 0}
                    if first and reject_to:
                        qa["reject_to"] = reject_to
                    with open(os.path.join(folder, "qa.json"), "w", encoding="utf-8") as f:
                        json.dump(qa, f, ensure_ascii=False)
                    status = "revision_needed" if first else "healthy"
                return {"status": status, "output_path": None, "error": None}
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
                orchestrator.run_channel(ROUTE, {"max_revisions": 3}, [ROUTE], "20261031T000000Z", "healthy")
        finally:
            for name, original in originals.items():
                setattr(orchestrator, name, original)
            provenance.INSTANCE_DIR = instance_dir
            os.environ.pop(provenance.RUN_ID_ENV, None)
        return seen, output.getvalue(), os.environ.get(ENV)


def feedback_ok(value):
    """The feedback sent: the notes, only the blocking issue, revision 1."""
    try:
        feedback = json.loads(value or "")
    except ValueError:
        return False
    return (feedback.get("rejection_notes") == NOTES and feedback.get("blocking_issues") == [BLOCKING]
            and feedback.get("revision") == 1)


def check(label, reject_to, redone):
    seen, output, after = run_case(reject_to)
    problems = []
    if after is not None:
        problems.append(f"{ENV} still set after the run")
    for name in redone:
        calls = seen.get(name, [])
        if len(calls) != 2:
            problems.append(f"{name} ran {len(calls)} time(s), expected 2")
            continue
        if calls[0] is not None:
            problems.append(f"{name}'s first run already had {ENV}")
        if reject_to and not feedback_ok(calls[1]):
            problems.append(f"{name}'s redo did not get the feedback: {calls[1]!r}")
        if not reject_to and calls[1] is not None:
            problems.append(f"{name}'s redo got {ENV} without an explicit reject_to")
    if seen.get("agent005", [None, None])[1] is not None:
        problems.append(f"{ENV} was not cleared before agent005 ran again")
    expected_line = "feedback transmis (1 blocking issues)" if reject_to else "no feedback"
    if expected_line not in output:
        problems.append(f"the log lacks {expected_line!r}: {output.strip()!r}")
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {p}" for p in problems))
    print("      log: " + " | ".join(line.strip() for line in output.splitlines() if "revision" in line))
    return not problems


results = [check('reject_to "agent004": agent004 gets the feedback, then it is cleared', "agent004", ["agent004"]),
           check('reject_to "agent003": agent003 and agent004 get it', "agent003", ["agent003", "agent004"]),
           check("no reject_to: the redo happens, without feedback", None, ["agent003", "agent004"])]
sys.exit(0 if all(results) else 1)
