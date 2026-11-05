"""
What a run really costs: every LLM call's tokens and every voice-over's characters, priced with
settings.json "prices", per agent and per run.

  record_llm / record_tts   called where the money is spent (app/agent/__init__.py llm_call,
                            app/tts_manager.py generate_voice): one record in memory each
  settle(channel, agent)    called by finish() when an agent is done: its records are added to
                            instance/{channel}/costs.json, the ledger of the channel's current run
                            (a new run id starts a new ledger), and summed up for its row
  run_summary(channel)      the ledger's totals, for the orchestrator's line and costs_history.json

instance/{channel}/costs.json = {run_id, currency, by_agent: {agent: totals}, total: totals,
unpriced: [what has no price in settings]}, totals = {llm_calls, input_tokens, cached_input_tokens,
output_tokens, tts_chars, llm_cost, tts_cost, cost}. A provider or a voice engine with no price is
counted (tokens, characters) but not priced, and named in "unpriced": the cost is then a floor.
Prices are the user's to keep up to date: nothing here fetches them.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
SETTINGS_PATH = os.path.join(BASE_DIR, "schemas", "settings.json")
HISTORY_PATH = os.path.join(INSTANCE_DIR, "costs_history.json")
FIELDS = ("llm_calls", "input_tokens", "cached_input_tokens", "output_tokens", "tts_chars", "llm_cost", "tts_cost", "cost")

PENDING = []          # this process's records not yet settled (an agent's calls, until its finish())


def record_llm(provider, model, input_tokens, output_tokens, cached_input_tokens=0):
    """One LLM call: input_tokens counts all the prompt (cached part included), output_tokens the
    answer (thinking included)."""
    PENDING.append({"kind": "llm", "provider": str(provider), "model": str(model or ""),
                    "input_tokens": int(input_tokens or 0), "cached_input_tokens": int(cached_input_tokens or 0),
                    "output_tokens": int(output_tokens or 0)})


def record_tts(engine, chars):
    """One voice-over: the characters sent to the engine (what ElevenLabs bills)."""
    PENDING.append({"kind": "tts", "engine": str(engine), "chars": int(chars or 0)})


def prices():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f).get("prices") or {}
    except (OSError, ValueError):
        return {}


def priced(record, table):
    """(cost, None) or (None, what has no price)."""
    if record["kind"] == "llm":
        price = (table.get("llm") or {}).get(f"{record['provider']}:{record['model']}") \
            or (table.get("llm") or {}).get(record["provider"])
        if not price:
            return None, f"llm {record['provider']}"
        fresh = record["input_tokens"] - record["cached_input_tokens"]
        cached = price.get("cached_input_per_million", price.get("input_per_million", 0))
        return (fresh * price.get("input_per_million", 0) + record["cached_input_tokens"] * cached
                + record["output_tokens"] * price.get("output_per_million", 0)) / 1e6, None
    price = (table.get("tts") or {}).get(record["engine"])
    if not price:
        return None, f"tts {record['engine']}"
    return record["chars"] * price.get("per_thousand_chars", 0) / 1000, None


def totals(records, table):
    """The records summed up (see the module's docstring), and what has no price."""
    out, unpriced = dict.fromkeys(FIELDS, 0), set()
    for r in records:
        cost, missing = priced(r, table)
        if missing:
            unpriced.add(missing)
        if r["kind"] == "llm":
            out["llm_calls"] += 1
            for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
                out[key] += r[key]
            out["llm_cost"] += cost or 0
        else:
            out["tts_chars"] += r["chars"]
            out["tts_cost"] += cost or 0
    out["cost"] = out["llm_cost"] + out["tts_cost"]
    return out, unpriced


def add(a, b):
    return {k: round(a.get(k, 0) + b.get(k, 0), 6) for k in FIELDS}


def ledger_path(channel_id):
    return os.path.join(INSTANCE_DIR, channel_id, "costs.json")


def channel_run_id(channel_id):
    """The channel's current run (LBREEZE_RUN_ID, else its manifest's), never a new one."""
    run_id = os.environ.get("LBREEZE_RUN_ID")
    if run_id:
        return run_id
    try:
        with open(os.path.join(INSTANCE_DIR, channel_id, "manifest.json"), encoding="utf-8") as f:
            return json.load(f).get("run_id")
    except (OSError, ValueError):
        return None


def settle(channel_id, agent):
    """Add this process's pending records to the channel's ledger under `agent`; their totals, or
    None when there were none. A channel with no folder ("global") keeps no ledger."""
    if not PENDING:
        return None
    records, table = PENDING[:], prices()
    PENDING.clear()
    spent, unpriced = totals(records, table)
    folder = os.path.join(INSTANCE_DIR, channel_id)
    if os.path.isdir(folder):
        run_id, path = channel_run_id(channel_id), ledger_path(channel_id)
        try:
            with open(path, encoding="utf-8") as f:
                ledger = json.load(f)
        except (OSError, ValueError):
            ledger = {}
        if ledger.get("run_id") != run_id:          # a new run: a new ledger
            ledger = {"run_id": run_id, "currency": table.get("currency", "USD"), "by_agent": {},
                      "total": dict.fromkeys(FIELDS, 0), "unpriced": []}
        ledger["by_agent"][agent] = add(ledger["by_agent"].get(agent, {}), spent)
        ledger["total"] = add(ledger["total"], spent)
        ledger["unpriced"] = sorted(set(ledger["unpriced"]) | unpriced)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=2)
    return {**{k: round(v, 6) for k, v in spent.items()}, **({"unpriced": sorted(unpriced)} if unpriced else {})}


def run_summary(channel_id):
    """The channel's ledger (its current run's), or None."""
    try:
        with open(ledger_path(channel_id), encoding="utf-8") as f:
            ledger = json.load(f)
    except (OSError, ValueError):
        return None
    return ledger if ledger.get("run_id") == channel_run_id(channel_id) else None


def remember(entry):
    """Append one finished run's costs to instance/costs_history.json (what agent011 will read)."""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, ValueError):
        history = []
    history.append(entry)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def money(value, currency="USD"):
    """0.4213 -> "0,42 $" (French style; a cent or less shown as "< 0,01 $")."""
    symbol = {"USD": "$", "EUR": "€"}.get(currency, currency)
    if value and value < 0.005:
        return f"< 0,01 {symbol}"
    return f"{value:.2f}".replace(".", ",") + f" {symbol}"
