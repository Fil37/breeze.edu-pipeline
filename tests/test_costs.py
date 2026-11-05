"""
Check the run's cost counter (app/costs.py), offline:
  1. an LLM answer's usage is recorded: OpenAI-style (deepseek's cache hits included) and
     Anthropic-style; priced with settings "prices" (cached input at its own price); a provider with
     no price is counted, not priced, and named
  2. a voice-over records the characters sent to its engine (ElevenLabs stubbed)
  3. settle(): an agent's records go to instance/{channel}/costs.json under that agent, summed in
     the total; a new run id starts a new ledger; run_summary() gives it; the history keeps runs
  4. money(): French style, a cent or less shown as "< 0,01 $"
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_costs.py
"""

import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import costs, tts_manager                                      # noqa: E402
from app.agent import tracked                                           # noqa: E402

PRICES = {"currency": "USD", "llm": {"deepseek": {"input_per_million": 0.28, "cached_input_per_million": 0.028,
                                                  "output_per_million": 0.42}},
          "tts": {"elevenlabs": {"per_thousand_chars": 0.22}, "edge-tts": {"per_thousand_chars": 0}}}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_llm():
    problems = []
    costs.PENDING.clear()
    tracked(NS(usage=NS(prompt_tokens=1_000_000, completion_tokens=500_000, prompt_cache_hit_tokens=400_000)), "deepseek", "deepseek-flash")
    tracked(NS(usage=NS(input_tokens=100, output_tokens=50, cache_read_input_tokens=20)), "anthropic", "claude-opus-5-5")
    records = costs.PENDING[:]
    costs.PENDING.clear()
    if [(r["input_tokens"], r["cached_input_tokens"], r["output_tokens"]) for r in records] != [(1_000_000, 400_000, 500_000), (120, 20, 50)]:
        problems.append(f"records: {records}")
    spent, unpriced = costs.totals(records, PRICES)
    expected = 600_000 * 0.28 / 1e6 + 400_000 * 0.028 / 1e6 + 500_000 * 0.42 / 1e6     # 0.168 + 0.0112 + 0.21
    if abs(spent["llm_cost"] - expected) > 1e-9 or spent["llm_calls"] != 2 or unpriced != {"llm anthropic"}:
        problems.append(f"priced {spent['llm_cost']} (expected {expected}), unpriced {unpriced}")
    return report("1. LLM usage recorded (cache hits too) and priced; an unpriced provider named", problems,
                  [f"1 M tokens in (400 k cached), 500 k out: {costs.money(spent['llm_cost'])}"])


def case_voice():
    problems = []
    costs.PENDING.clear()
    saved = (tts_manager.elevenlabs_voice, tts_manager.media_duration, os.environ.get("ELEVENLABS_API_KEY"))
    try:
        tts_manager.elevenlabs_voice = lambda text, mp3_path, key, voice_id=None: [(0.0, "Bonjour")]
        tts_manager.media_duration = lambda path: 1.0
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        tts_manager.generate_voice("Bonjour à tous.", os.devnull)
    finally:
        tts_manager.elevenlabs_voice, tts_manager.media_duration = saved[:2]
        if saved[2] is None:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        else:
            os.environ["ELEVENLABS_API_KEY"] = saved[2]
    records = costs.PENDING[:]
    costs.PENDING.clear()
    sent = len(tts_manager.normalize_text_for_tts("Bonjour à tous."))
    if records != [{"kind": "tts", "engine": "elevenlabs", "chars": sent}]:
        problems.append(f"records: {records}")
    spent, _ = costs.totals([{"kind": "tts", "engine": "elevenlabs", "chars": 2500}], PRICES)
    if abs(spent["tts_cost"] - 0.55) > 1e-9:
        problems.append(f"2 500 characters priced {spent['tts_cost']}")
    return report("2. a voice-over records the characters sent to its engine", problems)


def case_ledger():
    problems = []
    saved = (costs.INSTANCE_DIR, costs.HISTORY_PATH, costs.prices, os.environ.get("LBREEZE_RUN_ID"))
    with tempfile.TemporaryDirectory() as root:
        try:
            costs.INSTANCE_DIR, costs.HISTORY_PATH, costs.prices = root, os.path.join(root, "costs_history.json"), lambda: PRICES
            os.makedirs(os.path.join(root, "breeze_(math)"))
            os.environ["LBREEZE_RUN_ID"] = "run-1"
            costs.PENDING.clear()
            costs.record_llm("deepseek", "deepseek-flash", 10_000, 2_000)
            first = costs.settle("breeze_(math)", "agent003")
            costs.record_llm("deepseek", "deepseek-flash", 20_000, 4_000)
            costs.record_tts("elevenlabs", 1_000)
            costs.settle("breeze_(math)", "agent004")
            costs.record_tts("elevenlabs", 1_000)
            costs.settle("breeze_(math)", "agent004")
            ledger = costs.run_summary("breeze_(math)")
            if first["llm_calls"] != 1 or costs.settle("breeze_(math)", "agent005") is not None:
                problems.append(f"an agent's own totals: {first}")
            if sorted(ledger["by_agent"]) != ["agent003", "agent004"] or ledger["by_agent"]["agent004"]["tts_chars"] != 2000 \
                    or ledger["total"]["llm_calls"] != 2 or abs(ledger["total"]["tts_cost"] - 0.44) > 1e-9:
                problems.append(f"ledger: {ledger}")
            if costs.settle("global", "agent009") is not None or os.path.exists(os.path.join(root, "global")):
                problems.append("a ledger kept for global")
            os.environ["LBREEZE_RUN_ID"] = "run-2"
            if costs.run_summary("breeze_(math)") is not None:
                problems.append("the last run's ledger given for a new run")
            costs.record_llm("deepseek", "deepseek-flash", 1, 1)
            costs.settle("breeze_(math)", "agent001")
            if list(costs.run_summary("breeze_(math)")["by_agent"]) != ["agent001"]:
                problems.append("a new run did not start a new ledger")
            costs.remember({"run_id": "run-1"})
            costs.remember({"run_id": "run-2"})
            with open(costs.HISTORY_PATH, encoding="utf-8") as f:
                if [e["run_id"] for e in json.load(f)] != ["run-1", "run-2"]:
                    problems.append("history")
        finally:
            costs.INSTANCE_DIR, costs.HISTORY_PATH, costs.prices = saved[:3]
            if saved[3] is None:
                os.environ.pop("LBREEZE_RUN_ID", None)
            else:
                os.environ["LBREEZE_RUN_ID"] = saved[3]
            costs.PENDING.clear()
    return report("3. each agent's costs in the channel's ledger, a ledger per run, the history", problems)


def case_money():
    problems = [f"{v} -> {costs.money(v, c)!r}" for v, c, shown in ((0.4213, "USD", "0,42 $"), (0.001, "USD", "< 0,01 $"),
                                                                     (0, "EUR", "0,00 €"), (12.5, "EUR", "12,50 €"))
                if costs.money(v, c) != shown]
    return report("4. money in French style", problems)


if __name__ == "__main__":
    results = [case_llm(), case_voice(), case_ledger(), case_money()]
    sys.exit(0 if all(results) else 1)
