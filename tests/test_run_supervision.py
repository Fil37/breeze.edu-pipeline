"""
Check the supervision of breeze's runs (app/run_supervision.py on the studio kit's socle, 2026-11-20):
  1. breeze's errors in the socle's categories: a defect or a configuration opens an incident; a QA refusal, a
     topic repeated, a finished curriculum or a renderer limitation does not
  2. the rules of health: an incident puts the agent in "degraded", a good run heals it, closing the incident
     does NOT heal it; warnings and errors go to events
  3. no key in the database: the secrets of .env are removed from incidents and events
  4. the orchestrator calls the supervision at the end of each channel, and never stops for it
  5. the standup page shows the costs (AI and voice), each agent's health and the open incidents; "Resolved"
     closes one only with the browser's CSRF token (else 400) and leaves the agent's health as it was
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_run_supervision.py
"""

import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import run_supervision as rs                                 # noqa: E402
from app.supervision import SupervisionStore                          # noqa: E402

KEY = "sk-test-0123456789abcdef"


def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def temp_store():
    return SupervisionStore(os.path.join(tempfile.mkdtemp(), "breeze.db"), secrets=[KEY])


def case_categories():
    problems = []
    for error, want in (("ReadTimeout: timed out after 120 s", "timeout"),
                        ("HTTP 401: invalid api key", "access_denied"),
                        ("ELEVENLABS_API_KEY not set", "misconfiguration"),
                        ("unknown renderer 'manim'", "misconfiguration"),
                        ("QA verdict is not pass", "valid_empty_result"),
                        ("Renderer limitation: the QA lists what cannot be drawn", "valid_empty_result"),
                        ("every episode of the curriculum is made", "valid_empty_result"),
                        ("KeyError: 'scenes'", "software_failure"), (None, "software_failure")):
        if rs.error_category(error) != want:
            problems.append(f"{error!r}: {rs.error_category(error)}, wanted {want}")
    return report("1. breeze's errors in the socle's categories", problems)


def case_health():
    problems, s = [], temp_store()
    statuses = {"agent001": "healthy", "agent004": "critical", "agent005": "not_run", "agent008": "skipped"}
    opened = rs.supervise(s, "r1", "breeze_(math)", statuses, {"agent004": "KeyError: 'scenes'"})
    if len(opened) != 1 or s.health() != {"agent001": "healthy", "agent004": "degraded"}:
        problems.append(f"after a defect: {opened}, {s.health()}")
    s.close_incident(opened[0], "resolved", "fixed")
    if s.health()["agent004"] != "degraded":
        problems.append("closing the incident healed the agent")
    rs.supervise(s, "r2", "breeze_(math)", {"agent004": "not_healthy"}, {"agent004": "kept despite: overlap"})
    if s.health()["agent004"] != "healthy":
        problems.append(f"a good run did not heal it: {s.health()}")
    rs.supervise(s, "r3", "breeze_(math)", {"agent005": "critical"}, {"agent005": "QA verdict is not pass"})
    with s.connect() as c:
        open_now = c.execute("SELECT COUNT(*) FROM incidents WHERE status='open'").fetchone()[0]
        levels = [r[0] for r in c.execute("SELECT level FROM events ORDER BY event_id")]
    if open_now != 0:
        problems.append("a QA refusal opened an incident")
    if levels != ["error", "warning", "error"]:
        problems.append(f"events: {levels}")
    return report("2. an incident degrades, a good run heals, closing does not heal; events kept", problems)


def case_secrets():
    problems = []
    env = os.path.join(tempfile.mkdtemp(), ".env")
    with open(env, "w") as f:
        f.write(f"DEEPSEEK_API_KEY={KEY}\nLLM_PROVIDER=deepseek\n# OLD_TOKEN=x\n")
    secrets = rs.env_secrets(env)
    if KEY not in secrets or "deepseek" in secrets:
        problems.append(f"secrets read: {secrets}")
    s = SupervisionStore(os.path.join(tempfile.mkdtemp(), "breeze.db"), secrets=secrets)
    rs.supervise(s, "r1", "breeze_(math)", {"agent003": "critical"}, {"agent003": f"HTTP 500 with key {KEY}"})
    with open(s.db_path, "rb") as f:
        if KEY.encode() in f.read():
            problems.append("the key is in the database")
    return report("3. no key in the database (the secrets of .env removed)", problems)


def case_orchestrator():
    with open(os.path.join(ROOT, "app", "agent", "agent000_breeze.py"), encoding="utf-8") as f:
        source = f.read()
    problems = []
    call = source.find("run_supervision.supervise(")
    if call < 0 or "except Exception" not in source[call:call + 600]:
        problems.append("agent000 does not call the supervision, or a failure there would stop the run")
    if source.find("run_supervision.supervise(") > source.find("costs.run_summary(channel_id)"):
        problems.append("the supervision comes after the costs (it must see the run's reports first)")
    return report("4. the orchestrator supervises each channel's run, never stopping for it", problems)


def case_page():
    from web.app import app
    from web import page
    problems, s = [], temp_store()
    app.config["SUPERVISION_DB"] = s.db_path
    rs.supervise(s, "r1", "breeze_(math)", {"agent004": "critical", "agent001": "healthy"}, {"agent004": "KeyError: 'scenes'"})
    client = app.test_client()
    text = client.get("/standup").get_data(as_text=True)
    costs = page.costs()
    for want in ("Cost of the last run", "Agent health", "Incidents", "Costs by day", "KeyError", "Resolved", "degraded"):
        if want not in text:
            problems.append(f"the standup does not show {want!r}")
    if costs and f"${costs['last']['cost']:.3f}" not in text:
        problems.append("the last run's cost not shown")
    incident = int(re.search(r"/incidents/(\d+)/close", text).group(1))
    if client.post(f"/incidents/{incident}/close", data={"status": "resolved", "csrf": "forged"}).status_code != 400:
        problems.append("a forged CSRF token accepted")
    token = client.get_cookie("csrf").value
    response = client.post(f"/incidents/{incident}/close", data={"status": "resolved", "csrf": token})
    if response.status_code != 302 or "No open incident" not in client.get("/standup").get_data(as_text=True):
        problems.append(f"Resolved with the token: {response.status_code}")
    if s.health().get("agent004") != "degraded":
        problems.append("closing from the page changed the agent's health")
    if client.post(f"/incidents/{incident}/close", data={"status": "resolved", "csrf": token}).status_code != 404:
        problems.append("an incident closed twice")
    app.config.pop("SUPERVISION_DB", None)
    return report("5. the standup shows costs, health and incidents; Resolved needs the CSRF token, heals nothing", problems)


if __name__ == "__main__":
    results = [case_categories(), case_health(), case_secrets(), case_orchestrator(), case_page()]
    sys.exit(0 if all(results) else 1)
