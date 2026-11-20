"""Tests of the supervision base (app/supervision.py, the studio kit's socle v1.0 copied as is; no network, no
cost). Prints PASS / FAIL per case, like breeze's other tests:
    .venv/bin/python tests/test_supervision.py
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # the project, above tests/
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
