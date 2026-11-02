"""
Check the orchestrator's --skip-agents (and --channel): the real main() of agent000 runs with
command-line arguments, the agents are mocked (they only record that they were called), and
everything the orchestrator reads or writes (settings.json, routes.json, words.json, reports.json,
rows.json, breeze.db, breeze.json, manifest.json) is in a temporary folder: schemas/ and instance/
are never touched.
  1. --channel "breeze_(test)" --skip-agents agent008,agent009: agents 001-005, 010 (the renderer)
     and 007 are called, 008 and 009 are not; both are "skipped" in the final statuses and logged
     "skipped (--skip-agents)"
  2. no option: every agent is called, 008 and 009 included, on the enabled channel only (as before)
  3. --channel on a channel routes.json disables: it runs
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_orchestrator_skip_agents.py
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

ROUTES = [{"channel_id": "breeze_(test)", "name": "Test", "domain": "electronics", "schedule_cron": "0 6 * * *", "enabled": True},
          {"channel_id": "breeze_(other)", "name": "Other", "domain": "math", "schedule_cron": "0 7 * * *", "enabled": False}]


def run_main(argv, engine):
    """orchestrator.main(argv) with mocked agents; returns ([(agent, channel)] called, stdout, breeze.json)."""
    called = []
    with tempfile.TemporaryDirectory() as root:
        schemas = os.path.join(root, "schemas")
        os.makedirs(schemas)
        for name, content in (("settings.json", {"render_engine_by_channel": {"breeze_(test)": engine, "breeze_(other)": engine},
                                                 "max_revisions": 3, "dry_run": True}),
                              ("routes.json", ROUTES), ("words.json", {"banned_clickbait": []})):
            with open(os.path.join(schemas, name), "w", encoding="utf-8") as f:
                json.dump(content, f)

        def agent(name):
            return lambda channel_id, settings, routes: called.append((name, channel_id)) or \
                {"status": "healthy", "output_path": None, "error": None}

        def db_connect():                               # the real tables, in the temporary folder
            saved = helpers.DB_PATH, helpers.INSTANCE_DIR
            helpers.DB_PATH, helpers.INSTANCE_DIR = os.path.join(root, "breeze.db"), root
            try:
                return saved_db_connect()
            finally:
                helpers.DB_PATH, helpers.INSTANCE_DIR = saved

        saved_db_connect = orchestrator.db_connect
        patched = {"AGENTS": {name: agent(name) for name in orchestrator.AGENTS}, "SCHEMAS_DIR": schemas,
                   "INSTANCE_DIR": root, "REPORTS_PATH": os.path.join(root, "reports.json"),
                   "ROWS_PATH": os.path.join(root, "rows.json"), "db_connect": db_connect,
                   "log_status": lambda *args, **kwargs: None}
        originals = {name: getattr(orchestrator, name) for name in patched}
        instance_dir, run_id = provenance.INSTANCE_DIR, helpers.RUN_ID
        output = io.StringIO()
        try:
            for name, value in patched.items():
                setattr(orchestrator, name, value)
            provenance.INSTANCE_DIR = root
            with contextlib.redirect_stdout(output):
                orchestrator.main(argv)
        finally:
            for name, original in originals.items():
                setattr(orchestrator, name, original)
            provenance.INSTANCE_DIR, helpers.RUN_ID = instance_dir, run_id
            os.environ.pop(provenance.RUN_ID_ENV, None)
        state = json.load(open(os.path.join(root, "breeze.json"), encoding="utf-8"))
    return called, output.getvalue(), state


def check(label, argv, engine, channel, expected, skipped):
    called, output, state = run_main(argv, engine)
    names = {name for name, _ in called}
    problems = []
    if names != set(expected):
        problems.append(f"called {sorted(names)}, expected {sorted(expected)}")
    channels = {c for _, c in called if c != "global"}
    if channels != {channel}:
        problems.append(f"channels run: {sorted(channels)}, expected [{channel}]")
    statuses = (state.get(channel) or {}).get("agents", {})
    for name in skipped:
        if statuses.get(name) != "skipped":
            problems.append(f"{name}'s final status is {statuses.get(name)!r}, expected 'skipped'")
        if f"{name}: skipped (--skip-agents)" not in output:
            problems.append(f"no log line '{name}: skipped (--skip-agents)'")
    if not skipped and "skipped" in statuses.values():
        problems.append(f"an agent is 'skipped' without --skip-agents: {statuses}")
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {p}" for p in problems))
    print(f"      called: {', '.join(sorted(names))}")
    print(f"      statuses: {', '.join(f'{n[-3:]}:{s}' for n, s in statuses.items())}")
    return not problems


CONTENT = ["agent001", "agent002", "agent003", "agent004", "agent005", "agent007"]
SKIP = ["--skip-agents", "agent008,agent009"]
results = [
    check("--channel breeze_(test) --skip-agents agent008,agent009",
          ["--channel", "breeze_(test)", *SKIP], "html", "breeze_(test)", CONTENT + ["agent010"], ["agent008", "agent009"]),
    check("no option: every agent, every enabled channel (unchanged)", [], "html", "breeze_(test)",
          CONTENT + ["agent010", "agent008", "agent009"], []),
    check("--channel on a disabled channel: it runs", ["--channel", "breeze_(other)", *SKIP], "html", "breeze_(other)",
          CONTENT + ["agent010"], ["agent008", "agent009"]),
]
sys.exit(0 if all(results) else 1)
