"""Shared helpers for the breeze agents.

Required by the brief: llm_call, load_json, save_json, append_row, log_status,
channel_dir, db_connect.
Small extras that keep the agents short: utc_now, find_route, parse_llm_json,
finish, run_standalone.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMAS_DIR = os.path.join(BASE_DIR, "schemas")
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
ROWS_PATH = os.path.join(SCHEMAS_DIR, "rows.json")
REPORTS_PATH = os.path.join(SCHEMAS_DIR, "reports.json")
DB_PATH = os.path.join(INSTANCE_DIR, "breeze.db")

# The orchestrator sets this before calling agents; standalone runs keep "standalone".
RUN_ID = "standalone"

CHANNEL_ID_PATTERN = re.compile(r"^breeze_\([a-z_]+\)$")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass  # python-dotenv not installed: rely on variables already in the environment


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path):
    """Return the parsed file, or {} if it does not exist."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """Write JSON atomically (temp file + rename) so a crash never leaves half a file."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def append_row(row):
    """Append one row to schemas/rows.json. Agents call this; they never read the file."""
    rows = load_json(ROWS_PATH) or []
    rows.append(row)
    save_json(ROWS_PATH, rows)


def log_status(run_id, agent, status, error=None, channel=None):
    """Record one agent status in schemas/reports.json. Only agent000 calls this."""
    reports = load_json(REPORTS_PATH) or []
    entry = next((r for r in reports if r["run_id"] == run_id and r["channel"] == channel), None)
    if entry is None:
        entry = {"run_id": run_id, "timestamp": utc_now(), "channel": channel,
                 "agents": {}, "duration_sec": 0, "errors": []}
        reports.append(entry)
    entry["agents"][agent] = status
    if error:
        entry["errors"].append(f"{agent}: {error}")
    save_json(REPORTS_PATH, reports)


def channel_dir(channel_id):
    """Return instance/{channel_id}, creating it if needed. Rejects anything that is not breeze_(xxx)."""
    if not CHANNEL_ID_PATTERN.match(channel_id or ""):
        raise ValueError(f"invalid channel_id: {channel_id!r}")
    path = os.path.join(INSTANCE_DIR, channel_id)
    os.makedirs(path, exist_ok=True)
    return path


def db_connect():
    """Open instance/breeze.db and create the 4 flat tables if missing."""
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT, channel TEXT, started_at TEXT, finished_at TEXT,
            duration_sec REAL, overall_status TEXT, topic TEXT, revisions INTEGER,
            PRIMARY KEY (run_id, channel));
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, channel TEXT,
            agent TEXT, status TEXT, duration_sec REAL, error TEXT, timestamp TEXT);
        CREATE TABLE IF NOT EXISTS rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, channel TEXT,
            agent TEXT, stage TEXT, data TEXT, timestamp TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY, name TEXT, domain TEXT, schedule_cron TEXT,
            enabled INTEGER, last_run_id TEXT, last_run_at TEXT, overall_status TEXT,
            last_topic TEXT, last_video_url TEXT);
    """)
    return conn


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing environment variable {name}")
    return value


# Reasoning models (deepseek, gemini) spend part of this budget thinking before they answer:
# agent004's storyboard prompt (22 component types, 6 scenes) can think for over 16000 tokens.
# 64000 is accepted by deepseek-flash (checked with a real call); a model with a lower output
# limit rejects the call with a 400 error, so lower this for it.
MAX_OUTPUT_TOKENS = 64000


def checked_answer(response, provider):
    """Text of an OpenAI-style answer.
    Cut off (finish_reason "length") with some text: a warning on stderr, and the partial text is
    returned; the agents validate their JSON, so a truncated answer fails there (agent004 then sends
    the errors back to the LLM and retries). Empty: raises, there is nothing to return (an empty
    answer looks like "no JSON" to the agents, and retrying would fail the same way)."""
    choice = response.choices[0]
    content = choice.message.content or ""
    if not content.strip():
        raise RuntimeError(f"{provider} returned an empty answer (finish_reason={choice.finish_reason}): "
                           f"it may have spent all max_tokens={MAX_OUTPUT_TOKENS} thinking")
    if choice.finish_reason == "length":
        print(f"WARNING: {provider} answer cut off at max_tokens={MAX_OUTPUT_TOKENS} after {len(content)} chars: "
              "its JSON may be truncated (raise MAX_OUTPUT_TOKENS in app/agent/__init__.py if this repeats)",
              file=sys.stderr, flush=True)
    return content


def llm_call(prompt: str, model: str | None = None) -> str:
    """Send one prompt to the provider in settings.llm_provider. Raises RuntimeError on any failure."""
    settings = load_json(os.path.join(SCHEMAS_DIR, "settings.json"))
    provider = settings.get("llm_provider")
    model = model or settings.get("llm_model")
    messages = [{"role": "user", "content": prompt}]
    try:
        if provider == "openai":
            require_env("OPENAI_API_KEY")
            import openai
            response = openai.OpenAI().chat.completions.create(model=model, messages=messages)
            return response.choices[0].message.content
        if provider == "ollama":
            # Local model through Ollama's OpenAI-compatible API. No key needed: the client
            # requires one, Ollama ignores it.
            import openai
            client = openai.OpenAI(base_url=settings.get("ollama_base_url", "http://localhost:11434/v1"),
                                   api_key="ollama")
            response = client.chat.completions.create(model=settings.get("ollama_model"), messages=messages)
            return response.choices[0].message.content
        if provider == "deepseek":
            api_key = require_env("DEEPSEEK_API_KEY")
            import openai

            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.3,
            )
            return checked_answer(response, provider)
        if provider == "anthropic":
            require_env("ANTHROPIC_API_KEY")
            import anthropic
            client = anthropic.Anthropic()
            model = model.removeprefix("anthropic.")  # Bedrock-style id -> Claude API id
        if provider == "gemini":
            require_env("GEMINI_API_KEY")
            import openai
            client = openai.OpenAI(
                api_key=require_env("GEMINI_API_KEY"),
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.3,
            )
            return checked_answer(response, provider)
        if provider == "openrouter":
            api_key = require_env("OPENROUTER_API_KEY")
            import openai

            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4000,
                temperature=0.3,
                extra_headers={
                    "HTTP-Referer": "http://localhost",
                    "X-OpenRouter-Title": "Breeze Pipeline",
                },
            )
            return response.choices[0].message.content
        elif provider == "bedrock":
            require_env("AWS_ACCESS_KEY_ID")
            require_env("AWS_SECRET_ACCESS_KEY")
            region = require_env("AWS_DEFAULT_REGION")
            import anthropic
            client = anthropic.AnthropicBedrock(aws_region=region)
        if provider in ("anthropic", "bedrock"):
            response = client.messages.create(model=model, max_tokens=16000, messages=messages)
            return "".join(block.text for block in response.content if block.type == "text")
        raise RuntimeError(f"unknown llm_provider: {provider!r}")
    except RuntimeError:
        raise
    except Exception as exc:  # import errors, network errors, API errors...
        raise RuntimeError(f"{provider} call failed: {exc}") from exc


def parse_llm_json(text):
    """Parse JSON from an LLM answer, tolerating ```json fences around it."""
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in LLM answer")
    return json.loads(match.group(0))


def find_route(routes, channel_id):
    """Return the routes.json entry for channel_id, or None."""
    return next((r for r in routes if r.get("channel_id") == channel_id), None)


def finish(channel_id, agent, stage, status, output_path, data=None, error=None):
    """Append this agent's row to rows.json and build the contract return dict."""
    data = dict(data or {})
    if error:
        data["error"] = error
    append_row({"run_id": RUN_ID, "channel": channel_id, "agent": agent, "stage": stage,
                "data": data, "timestamp": utc_now(), "status": status})
    return {"status": status, "output_path": output_path, "error": error}


def run_standalone(run_fn):
    """CLI shared by every agent: python agentNNN.py --channel "breeze_(math)" [--run-id X].
    --run-id sets LBREEZE_RUN_ID, the run the agent's files are recorded under (app/provenance.py);
    without it, the agent continues the run in the channel's manifest.json."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="global", help='e.g. "breeze_(math)" (quote it in the shell)')
    parser.add_argument("--run-id", help="provenance run id (default: $LBREEZE_RUN_ID, else the channel's current run)")
    args = parser.parse_args()
    if args.run_id:
        os.environ["LBREEZE_RUN_ID"] = args.run_id     # app.provenance.RUN_ID_ENV
    settings = load_json(os.path.join(SCHEMAS_DIR, "settings.json"))
    routes = load_json(os.path.join(SCHEMAS_DIR, "routes.json")) or []
    try:
        result = run_fn(args.channel, settings, routes)
    except ValueError as exc:  # e.g. a mistyped channel_id
        raise SystemExit(f"error: {exc}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
