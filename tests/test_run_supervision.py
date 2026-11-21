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
  (socle 2.0, 2026-11-20)
  6. skills: every agent declares its own (id, version, objective, summary); registered "proposed", a decided status
     kept when they are registered again; activation only through an approval
  7. a publication waits for the user: agent008 asks (nothing uploaded); the handler uploads only the video and
     metadata approved (sha256), never without a handler; rejected = nothing uploaded
  8. breeze's named checks registered with their real case; their outcomes (pass / corrected / kept_despite) read
     from the agents' rows and recorded at the end of a channel's run
  9. the startup checks: a missing key or tool makes its agent critical (the only place); a passing check keeps a
     "degraded" agent degraded and lifts a critical one
 10. the daily backup: verified, one per day, next to a test base (never in the home folder), settings copied, never .env
 11. the test launcher refuses to start while a real run is in progress; the orchestrator marks its run, starts the
     supervision before any agent and closes the run after the last channel
 12. the standup's 2.0 panels (runs in progress, approvals, skills, quality checks, backups and disk), each button
     CSRF-checked
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_run_supervision.py
"""

import json
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


def case_skills():
    from app.agent import agent000_breeze as orchestrator
    problems, s = [], temp_store()
    for module in orchestrator.MODULES:
        for skill in getattr(module, "SKILLS", None) or [None]:
            if not skill or not all(skill.get(k) for k in ("skill_id", "version", "objective", "summary")):
                problems.append(f"{module.AGENT}: no complete skill")
    rs.register_skills_and_checks(s, orchestrator.MODULES)
    if not s.skills() or {k["status"] for k in s.skills()} != {"proposed"}:
        problems.append("skills not registered 'proposed'")
    s.propose_skill_activations()
    first = s.approvals()[0]
    s.decide(first["approval_id"], True)
    rs.register_skills_and_checks(s, orchestrator.MODULES)
    active = [k for k in s.skills() if k["status"] == "active"]
    if [f"{k['skill_id']}@{k['version']}" for k in active] != [first["target"]]:
        problems.append(f"after approval and a new registration: {active}")
    return report("6. skills declared by each agent, proposed, activated only by an approval", problems)


def publish_folder():
    """A temporary instance with one channel's video and metadata; app.agent's paths pointed at it."""
    from app import agent as helpers
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "breeze_(math)")
    os.makedirs(folder)
    with open(os.path.join(folder, "video.mp4"), "wb") as f:
        f.write(b"\0" * 4096)
    with open(os.path.join(folder, "metadata.json"), "w") as f:
        json.dump({"title": "Inégalités"}, f)
    saved = helpers.INSTANCE_DIR, helpers.DB_PATH, helpers.ROWS_PATH
    helpers.INSTANCE_DIR, helpers.DB_PATH, helpers.ROWS_PATH = root, os.path.join(root, "breeze.db"), os.path.join(root, "rows.json")
    return folder, lambda: setattr(helpers, "INSTANCE_DIR", saved[0]) or setattr(helpers, "DB_PATH", saved[1]) or setattr(helpers, "ROWS_PATH", saved[2])


def case_publication():
    from app.agent import agent008_platformpublisher as a008
    problems, uploads = [], []
    folder, restore = publish_folder()
    try:
        settings = {"enabled_platforms": ["youtube"], "dry_run": False}
        video = os.path.join(folder, "video.mp4")
        publication = {}
        status, error = a008.publish_one("breeze_(math)", "youtube", settings, video, {"title": "Inégalités"}, publication)
        s = rs.store()
        pending = s.approvals()
        if status != "not_healthy" or "approval" not in str(error) or len(pending) != 1 or publication.get("url"):
            problems.append(f"the run published or did not ask: {status} {error} {pending}")
        target, params = pending[0]["target"], pending[0]["parameters"]
        if target != "breeze_(math):youtube" or params.get("privacy") != "private" or len(params.get("video_sha256", "")) != 64:
            problems.append(f"the request: {target} {params}")
        try:
            s.decide(pending[0]["approval_id"], True)          # no handler: nothing applied
            problems.append("approved without a handler")
        except KeyError:
            pass
        fake = lambda channel, platform, st, path, meta, pub: (uploads.append(path), pub.update(url="https://youtu.be/x"), ("healthy", None))[2]
        outcome = s.decide(pending[0]["approval_id"], True, {"publish_video": lambda t, p: a008.publish_approved(t, p, settings, fake)})
        if not outcome.get("applied") or uploads != [video]:
            problems.append(f"the approved video not uploaded: {outcome} {uploads}")
        a008.publish_one("breeze_(math)", "youtube", settings, video, {"title": "x"}, {})
        with open(video, "ab") as f:
            f.write(b"changed")
        again = s.approvals()[0]
        outcome = a008.publish_approved(again["target"], again["parameters"], settings, fake)
        if outcome.get("applied") or "changed" not in outcome.get("reason", "") or len(uploads) != 1:
            problems.append(f"a changed video uploaded: {outcome}")
        s.decide(again["approval_id"], False)
        if s.approvals() or len(uploads) != 1:
            problems.append("a rejected publication uploaded")
    finally:
        restore()
    return report("7. a publication waits for the user's approval; only the approved video goes up, by the handler", problems)


def case_checks():
    problems, s = [], temp_store()
    rs.register_skills_and_checks(s, [])
    with s.connect() as c:
        registered = {r[0]: r[1] for r in c.execute("SELECT check_id, origin_case FROM quality_checks")}
    if set(registered) != {c[0] for c in rs.CHECKS} or not all(registered.values()):
        problems.append(f"checks registered: {registered}")
    rows = [{"agent": "agent003", "data": {"acronyms_undefined": [], "short_scenes": []}},
            {"agent": "agent004", "data": {"attempts": 3, "coherence_left": [], "sync_fixes": ["scene 1: s starts wrong: marked ✗"]}},
            {"agent": "agent005", "data": {"verdict": "pass", "corrected_count": 0, "layout_conflicts": ["scene 1: a overlaps b"]}},
            {"agent": "agent010", "data": {"warnings": []}}]
    got = {o["check"]: o["outcome"] for o in rs.outcomes(rows)}
    want = {"SCRIPT_RULES": "pass", "STORYBOARD_COHERENCE": "corrected", "SENTENCE_VERDICTS": "corrected",
            "QA_REVIEW": "pass", "LAYOUT_MEASURED": "kept_despite", "RENDER_WARNINGS": "pass"}
    if got != want:
        problems.append(f"outcomes: {got}")
    rs.supervise(s, "r1", "breeze_(math)", {"agent004": "healthy"}, {}, rows, revisions=1)
    summary = {(c["check_id"], c["outcome"]) for c in s.check_summary()}
    if ("QA_REVIEW", "corrected") not in summary or ("LAYOUT_MEASURED", "kept_despite") not in summary:
        problems.append(f"outcomes not recorded by supervise: {summary}")
    return report("8. named checks with their real case; outcomes read from the run and recorded", problems)


def case_startup():
    problems, s = temp_store(), []
    s, problems = problems, s
    s.set_health("agent010", "degraded", "incident in run r1")      # its tools are there: its check passes
    s.set_health("agent003", "critical", "missing: DEEPSEEK_API_KEY")
    tools = lambda name: "/usr/bin/" + name
    states = rs.startup_checks(s, {"llm_provider": "deepseek"}, env={}, which=tools)
    if states.get("agent001") != "critical" or "DEEPSEEK" not in s.standup(["agent001"])["agents"][0]["detail"]:
        problems.append(f"a missing key: {states}")
    states = rs.startup_checks(s, {"llm_provider": "deepseek"}, env={"DEEPSEEK_API_KEY": "x" * 20}, which=tools)
    if states.get("agent010") != "degraded" or states.get("agent003") != "healthy":
        problems.append(f"after the key came back: {states}")
    states = rs.startup_checks(s, {"llm_provider": "deepseek"}, env={"DEEPSEEK_API_KEY": "x" * 20}, which=lambda name: None)
    if states.get("agent010") != "critical":
        problems.append("no ffmpeg, the renderer not critical")
    publishing = {"llm_provider": "deepseek", "enabled_platforms": ["youtube"], "dry_run": False}
    if rs.startup_checks(s, publishing, env={"DEEPSEEK_API_KEY": "x" * 20}, which=tools).get("agent008") != "critical":
        problems.append("publishing without the YouTube keys, the publisher not critical")
    return report("9. startup checks: critical for a missing key or tool; degraded kept, critical lifted", problems)


def case_backup():
    problems, s = [], temp_store()
    first = rs.daily_backup(s)
    second = rs.daily_backup(s)
    folder = os.path.dirname(first["path"])
    if not first["created"] or second["created"] or not folder.startswith(os.path.dirname(s.db_path)):
        problems.append(f"backups: {first} {second}")
    names = os.listdir(folder)
    if not any(n.endswith(".db") for n in names) or not any(n.endswith(".json") for n in names) or any("env" in n for n in names):
        problems.append(f"files: {names}")
    if oct(os.stat(first["path"]).st_mode)[-3:] != "600":
        problems.append("the backup is not private")
    return report("10. the daily backup: verified, once a day, beside a test base, settings kept, never .env", problems)


def case_guard_and_orchestrator():
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import run_tests
    problems, s = [], temp_store()
    run = s.new_run("breeze run test")                      # this process: alive
    if run_tests.main(["nothing_matches"], s.db_path) != 2:
        problems.append("the launcher started during a real run")
    s.finish_run(run, "succeeded")
    if run_tests.main(["nothing_matches"], s.db_path) != 0:
        problems.append("the launcher refused with no run in progress")
    with open(os.path.join(ROOT, "app", "agent", "agent000_breeze.py"), encoding="utf-8") as f:
        source = f.read()
    main = source[source.index("def main("):]
    if not (0 < main.find("start_supervision(") < main.find("call_agent(\"agent009\"") < main.find("supervision.finish_run(")):
        problems.append("the orchestrator does not start the supervision first and close its run last")
    return report("11. the launcher refuses during a real run; the orchestrator marks and closes its run", problems)


def case_dashboard_page():
    from web.app import app
    problems, s = [], temp_store()
    app.config.update(SUPERVISION_DB=s.db_path, BACKUP_DIR=os.path.join(os.path.dirname(s.db_path), "backups"))
    rs.daily_backup(s)
    from app.agent import agent000_breeze as orchestrator
    rs.register_skills_and_checks(s, orchestrator.MODULES)
    client = app.test_client()
    text = client.get("/standup").get_data(as_text=True)
    for want in ("Runs in progress", "Pending approvals", "Propose skill activations", "Skills", "html_render",
                 "Quality checks", "Backups and disk", "breeze_"):
        if want not in text:
            problems.append(f"the standup does not show {want!r}")
    if client.post("/skills/propose", data={"csrf": "forged"}).status_code != 400:
        problems.append("proposing without the CSRF token accepted")
    token = client.get_cookie("csrf").value
    client.post("/skills/propose", data={"csrf": token})
    approval = s.approvals()[0]["approval_id"]
    if client.post(f"/approvals/{approval}", data={"decision": "approve", "csrf": "forged"}).status_code != 400:
        problems.append("an approval without the CSRF token accepted")
    if client.post(f"/approvals/{approval}", data={"decision": "approve", "csrf": token}).status_code != 302 \
            or not any(k["status"] == "active" for k in s.skills()):
        problems.append("approving with the token did not activate the skill")
    app.config.pop("SUPERVISION_DB", None)
    app.config.pop("BACKUP_DIR", None)
    return report("12. the standup's 2.0 panels, each button CSRF-checked", problems)


if __name__ == "__main__":
    results = [case_categories(), case_health(), case_secrets(), case_orchestrator(), case_page(), case_skills(),
               case_publication(), case_checks(), case_startup(), case_backup(), case_guard_and_orchestrator(),
               case_dashboard_page()]
    sys.exit(0 if all(results) else 1)
