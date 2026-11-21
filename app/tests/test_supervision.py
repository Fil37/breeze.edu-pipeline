"""Tests of the supervision base (app/supervision.py, the studio kit's socle 2.0 copied as is; no network, no
cost). Prints PASS / FAIL per case, like breeze's other tests:
    .venv/bin/python app/tests/test_supervision.py
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # the project, above app/tests/
from app import supervision as sv  # noqa: E402

PRICING = {"peak": {"m": {"input_hit": 0.1, "input_miss": 1.0, "output": 4.0}},
           "peak_hours_utc_mon_fri": [[0, 24]], "off_peak_factor": 0.5}
PROVIDER = {"name": "prov", "base_url": "https://example.invalid", "api_key": "sk-SECRET-123", "pricing": PRICING}
MODEL = {"model": "m", "max_tokens": 100}


def ok_answer(content, prompt=1000, completion=100):
    return 200, {"choices": [{"message": {"content": json.dumps(content)}}],
                 "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


def store():
    return sv.SupervisionStore(Path(tempfile.mkdtemp()) / "db.sqlite", secrets=["sk-SECRET-123"])


def test_cost_is_computed_and_unknown_model_is_none():
    """Cost per call from usage (1000 in at 1 $/M + 100 out at 4 $/M = 0.0014 $), off-peak factor; a model
    without a price gives None (never an invented figure)."""
    monday_noon = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    assert sv.estimate_cost_usd(PRICING, "m", {"prompt_tokens": 1000, "completion_tokens": 100}, monday_noon) == 0.0014
    off = dict(PRICING, peak_hours_utc_mon_fri=[[1, 2]])
    assert sv.estimate_cost_usd(off, "m", {"prompt_tokens": 1000, "completion_tokens": 100}, monday_noon) == 0.0007
    assert sv.estimate_cost_usd(PRICING, "other", {"prompt_tokens": 10}) is None


def test_client_records_calls_without_the_key_and_retries_transient():
    """A 503 then a good answer: 2 records (failed, succeeded), cost on the good one, the API key nowhere."""
    answers = [(503, "busy"), ok_answer({"ok": True})]
    seen = []

    def transport(url, headers, body, timeout):
        seen.append(headers["Authorization"])
        return answers.pop(0)
    c = sv.LLMClient(PROVIDER, MODEL, "agent002", transport=transport)
    assert c.chat_json([{"role": "user", "content": "x"}], purpose="select", run_id="r1") == {"ok": True}
    assert [r["status"] for r in c.calls] == ["failed", "succeeded"] and c.calls[1]["estimated_cost"] > 0
    assert "sk-SECRET-123" not in json.dumps(c.calls) and seen == ["Bearer sk-SECRET-123"] * 2


def test_client_errors_are_categorised_and_never_switch_model():
    """401 -> access_denied at once (no retry); no key -> misconfiguration before any call; the model asked is the
    only one ever used."""
    calls = []
    c = sv.LLMClient(PROVIDER, MODEL, "a", transport=lambda u, h, b, t: (calls.append(b["model"]), (401, "no"))[1])
    try:
        c.chat_json([], purpose="p")
        raise AssertionError("no error")
    except sv.LLMError as e:
        assert e.category == "access_denied" and "sk-SECRET" not in str(e)
    assert calls == ["m"]
    try:
        sv.LLMClient(dict(PROVIDER, api_key=""), MODEL, "a").chat_json([], purpose="p")
        raise AssertionError("no error")
    except sv.LLMError as e:
        assert e.category == "misconfiguration"


def test_budget_only_lowers_and_stops_calls():
    """The granted budget can only lower the configured one; once spent, the client refuses (budget_exhausted)."""
    b = sv.Budget({"llm_calls_per_run": 2, "llm_tokens_per_run": 10**6, "llm_cost_usd_per_run": 1.0},
                  granted={"llm_calls": 50})
    assert b.calls == 2
    c = sv.LLMClient(PROVIDER, MODEL, "a", budget=b, transport=lambda u, h, bd, t: ok_answer({"x": 1}))
    c.chat_json([], purpose="p")
    c.chat_json([], purpose="p")
    try:
        c.chat_json([], purpose="p")
        raise AssertionError("no error")
    except sv.LLMError as e:
        assert e.category == "budget_exhausted"
    assert b.remaining()["llm_calls"] == 0


def test_health_incidents_and_events():
    """Incident in a run -> agent 'degraded'; closing the incident does NOT heal it (user choice); its next
    successful run does. Only defect categories open incidents; a dedupe key keeps one open incident per key;
    secrets are removed from events."""
    s = store()
    assert s.open_incident(agent_id="agent001", category="valid_empty_result", errors=["empty"]) is None
    iid = s.open_incident(agent_id="agent001", category="software_failure", errors=["boom sk-SECRET-123"], run_id="r1")
    s.update_health_after_run("r1", {"agent001": "failed", "agent002": "succeeded"})
    assert s.health() == {"agent001": "degraded", "agent002": "healthy"}
    s.close_incident(iid, "resolved", "fixed")
    assert s.health()["agent001"] == "degraded"
    s.update_health_after_run("r2", {"agent001": "succeeded"})
    assert s.health()["agent001"] == "healthy"
    k1 = s.open_incident(agent_id="agent001", category="source_unavailable", errors=["live failed"], dedupe_key="chan")
    assert k1 and s.open_incident(agent_id="agent001", category="source_unavailable", errors=["again"], dedupe_key="chan") is None
    s.log_event("error", "agent_crash", "key sk-SECRET-123 in " + str(Path.home()) + "/x", run_id="r1", agent_id="agent001")
    with s.connect() as c:
        diag = c.execute("SELECT diagnostic FROM incidents WHERE incident_id=?", (iid,)).fetchone()[0]
        msg = c.execute("SELECT message FROM events").fetchone()[0]
    assert "sk-SECRET" not in diag and "sk-SECRET" not in msg and msg.endswith("~/x")


def test_standup_data_for_the_page():
    """standup() gives the kit page's variables: tiles (agents, cost today, incidents), agents, incidents, costs by
    day, recent errors; costs are summed by the program from the stored calls."""
    s = store()
    c = sv.LLMClient(PROVIDER, MODEL, "agent002", transport=lambda u, h, b, t: ok_answer({"x": 1}))
    c.chat_json([], purpose="p", run_id="r1")
    c.chat_json([], purpose="p", run_id="r1")
    s.record_llm_calls(c.calls)
    s.set_health("agent002", "healthy")
    s.open_incident(agent_id="agent001", category="timeout", errors=["too long"], run_id="r1")
    data = s.standup(["agent001", "agent002"])
    assert s.run_cost("r1") == {"calls": 2, "tokens_in": 2000, "tokens_out": 200, "cost": 0.0028}
    assert data["tiles"][0]["value"] == "1/2" and data["tiles"][1]["value"] == "$0.003"
    assert data["incidents"][0]["message"] == "too long" and data["costs"][0]["calls"] == 2
    assert [a["state"] for a in data["agents"]] == ["unknown", "healthy"]


def test_model_profiles_by_purpose():
    """LLM_PROFILE (auto_clip 'mixed'): one purpose of one agent uses another model under a profile chosen per run;
    the record keeps the model really used and its price; an unknown profile is refused before any call."""
    pricing = dict(PRICING, peak=dict(PRICING["peak"], pro={"input_hit": 1, "input_miss": 4, "output": 12}))
    seen = []
    c = sv.LLMClient(dict(PROVIDER, pricing=pricing), MODEL, "agent002", profile="mixed",
                     profiles={"mixed": {"agent002": {"select": {"model": "pro"}}}},
                     transport=lambda u, h, b, t: (seen.append(b["model"]), ok_answer({"x": 1}))[1])
    c.chat_json([], purpose="select")
    c.chat_json([], purpose="package")
    assert seen == ["pro", "m"] and [r["model"] for r in c.calls] == ["pro", "m"]
    assert c.calls[0]["estimated_cost"] > c.calls[1]["estimated_cost"]
    try:
        sv.LLMClient(PROVIDER, MODEL, "a", profile="turbo", profiles={})
        raise AssertionError("no error")
    except ValueError:
        pass


def test_skills_and_their_approval():
    """Skills declared by an agent start 'proposed'; re-declaring keeps the user's decision; activation goes through
    an approval (one pending per skill); 'approved' makes it active."""
    s = store()
    s.register_skills("agent002", [{"skill_id": "SK_SELECT", "version": "1", "objective": "pick passages"}])
    assert [k["status"] for k in s.skills()] == ["proposed"]
    assert s.propose_skill_activations() == 1 and s.propose_skill_activations() == 0
    aid = s.approvals()[0]["approval_id"]
    assert s.decide(aid, True) == {"applied": True}
    s.register_skills("agent002", [{"skill_id": "SK_SELECT", "version": "1", "objective": "new text"}])
    k = s.skills()[0]
    assert k["status"] == "active" and k["objective"] == "new text" and s.approvals() == []


def test_approvals_apply_only_with_a_handler():
    """A sensitive action waits for the user with its target and parameters; approving calls the project's handler;
    an approved action without a handler is refused and stays pending (nothing applied blindly); rejecting applies
    nothing; every decision is logged."""
    s = store()
    done = []
    aid = s.request_approval("remove_source", "video.mp4", {"bytes": 12})
    assert s.request_approval("remove_source", "video.mp4", {}) is None
    try:
        s.decide(aid, True)
        raise AssertionError("no error")
    except KeyError:
        pass
    assert s.approvals()[0]["parameters"] == {"bytes": 12}
    out = s.decide(aid, True, handlers={"remove_source": lambda target, p: (done.append(target), {"applied": True})[1]})
    assert out == {"applied": True} and done == ["video.mp4"]
    rid = s.request_approval("remove_source", "other.mp4", {})
    assert s.decide(rid, False) == {"applied": False} and done == ["video.mp4"]
    with s.connect() as c:
        assert [r[0] for r in c.execute("SELECT code FROM events ORDER BY event_id")] == ["approval_approved", "approval_rejected"]


def test_quality_checks_and_ratings():
    """Named checks cite their real case; outcomes are counted per check (pass / corrected / kept_despite); an
    unknown check is kept, not lost; the latest rating of an item counts."""
    s = store()
    s.register_check("ENDING_COMPLETE", "agent002", "end on a full sentence", "87 of 105 rejections were ends_unresolved")
    n = s.record_outcomes("r1", [{"check": "ENDING_COMPLETE", "outcome": "corrected"},
                                 {"check": "ENDING_COMPLETE", "outcome": "pass"}, {"check": "NEW_ONE", "outcome": "pass"}])
    summary = {(x["check_id"], x["outcome"]): x["count"] for x in s.check_summary()}
    assert n == 3 and summary == {("ENDING_COMPLETE", "corrected"): 1, ("ENDING_COMPLETE", "pass"): 1, ("NEW_ONE", "pass"): 1}
    s.rate("clip1", "bad")
    s.rate("clip1", "good", "fixed")
    s.rate("clip2", "good")
    assert s.ratings_summary() == {"good": 2, "bad": 0}


def test_runs_tasks_stages_and_interrupted_runs():
    """Runs and tasks with their states; the stepper shows 'reused' for a first step skipped while the next ones
    went on (auto_clip); a run left 'running' by a dead process is closed 'failed' at start, never a live one."""
    s = store()
    rid = s.new_run("Video A", {"clips": 5})
    t1 = s.new_task(rid, "agent001", "transcribe")
    s.set_task(t1, "skipped", "reused from run X")
    t2 = s.new_task(rid, "agent002", "select")
    s.set_task(t2, "running")
    stages = s.stage_states(rid, [("agent001", "Transcribe"), ("agent002", "Select"), ("agent003", "Review")])
    assert [x["state"] for x in stages] == ["reused", "running", "pending"]
    s.set_task(t2, "succeeded")
    s.finish_run(rid, "succeeded", {"clips": 5})
    with s.connect() as c:
        c.execute("UPDATE sup_runs SET status='running', owner_pid=999999999 WHERE run_id=?", (rid,))
    assert s.mark_interrupted_runs() == [rid]
    live = s.new_run("Video B")                       # owner = this process, alive
    assert s.mark_interrupted_runs() == [] and live


def test_trash_restore_and_purge():
    """RUN_TRASH: a finished run goes to the trash with a purge date, can be restored, and is erased only once the
    date has passed (the project's erase function is called; rows are kept); a running run cannot be deleted."""
    from datetime import timedelta
    s = store()
    rid = s.new_run("Video A")
    try:
        s.trash_run(rid)
        raise AssertionError("no error")
    except RuntimeError:
        pass
    s.finish_run(rid, "succeeded")
    s.trash_run(rid, days=7)
    assert rid in s.trashed_runs() and s.restore_run(rid) and s.trashed_runs() == {}
    s.trash_run(rid, days=7)
    erased = []
    assert s.purge_trash(lambda r: erased.append(r) or 10) == []
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert s.purge_trash(lambda r: erased.append(r) or 10, now=later) == [rid] and erased == [rid]
    assert s.trashed_runs() == {}


def test_operations_backup_startup_disk_brief_and_guard():
    """Daily backup verified (integrity_check) and private, not redone the same day; startup checks are the only
    place that sets 'critical' (a failing check too); disk sizes; repair brief; the test guard sees a real running
    run and an extra condition (e.g. a live recording)."""
    import os
    s = store()
    folder = Path(tempfile.mkdtemp()) / "backups"
    b1 = s.backup_database(folder, "proj")
    assert b1["created"] and b1["integrity"] == "ok" and oct(os.stat(b1["path"]).st_mode)[-3:] == "600"
    assert s.backup_database(folder, "proj")["created"] is False and sv.backups(folder, "proj")[0]["name"].startswith("proj_")
    states = s.startup_check({"agent001": lambda: ("healthy", "tool ok"), "agent002": lambda: ("critical", "key missing"),
                              "agent003": lambda: 1 / 0})
    assert states == {"agent001": "healthy", "agent002": "critical", "agent003": "critical"}
    du = sv.disk_usage({"base": folder})
    assert du["base"] > 0 and du["free"] > 0
    iid = s.open_incident(agent_id="agent001", category="software_failure", errors=["boom"], run_id="r1")
    assert "Incident" in s.repair_brief(iid, {"agent001": "app/agent/agent001.py"}) and "agent001.py" in s.repair_brief(iid, {"agent001": "app/agent/agent001.py"})
    rid = s.new_run("busy")
    assert rid in sv.busy_runs(s.db_path)
    assert "rec1" in sv.busy_runs(s.db_path, ("SELECT 'rec1'",))


def test_dashboard_has_everything():
    """dashboard() = standup() + runs in progress and recent (trash marked), skills, pending approvals, quality
    checks, ratings, and an Approvals tile."""
    s = store()
    rid = s.new_run("Video A")
    s.register_skills("agent002", [{"skill_id": "SK", "version": "1"}])
    s.propose_skill_activations()
    s.record_outcomes(rid, [{"check": "C", "outcome": "pass"}])
    s.rate("x", "good")
    d = s.dashboard(["agent002"])
    assert [r["run_id"] for r in d["runs_active"]] == [rid] and d["runs_recent"][0]["trash"] is None
    assert len(d["skills"]) == 1 and len(d["approvals"]) == 1 and d["checks"][0]["count"] == 1
    assert d["ratings"] == {"good": 1, "bad": 0} and d["tiles"][-1] == {"label": "Approvals", "value": 1,
                                                                      "sub": "waiting for you", "tone": "warn"}


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failed else 0)
