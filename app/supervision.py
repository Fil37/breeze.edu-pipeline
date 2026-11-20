"""STUDIO KIT — socle de supervision (version 1.0, 2026-11-20), extrait d'auto_clip et rendu générique.

Ce que la page Supervision du kit affiche, mesuré pour de vrai :
  - coût de chaque appel à un modèle d'IA (jetons, latence, $), rattaché au run et à l'agent ;
  - budget par run (appels, jetons, $) qui ne peut que BAISSER la dépense ;
  - santé de chaque agent dans le temps (unknown / healthy / degraded / critical / disabled) ;
  - incidents (ouverts, résolus, ignorés) et événements (journal nettoyé, sans secret) ;
  - les données prêtes pour la page Supervision (tuiles, agents, incidents, coûts par jour, erreurs récentes).

Bibliothèque standard uniquement (sqlite3, json, urllib). À copier tel quel dans un projet (structure
agent-project-builder : son contenu va dans app/agent/init.py ou est importé par lui) — voir README du kit.

Règles reprises d'auto_clip (décisions de l'utilisateur) :
  - jamais de bascule automatique vers un autre fournisseur ou modèle : l'erreur remonte ;
  - la clé d'API n'apparaît jamais dans un enregistrement ni dans un journal ;
  - un agent passe « degraded » quand un incident le concerne dans un run et redevient « healthy » à son
    prochain run réussi — fermer un incident NE change PAS sa santé (choix de l'utilisateur, 2026-11-20) ;
  - seules quelques catégories d'erreurs ouvrent un incident (défaut ou configuration) ; un résultat vide valide,
    un budget épuisé ou une langue non gérée n'en ouvrent pas.
"""
from __future__ import annotations

import http.client
import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HEALTH_STATES = ("unknown", "healthy", "degraded", "critical", "disabled")
ERROR_CATEGORIES = ("software_failure", "source_unavailable", "access_denied", "misconfiguration", "missing_data",
                    "valid_empty_result", "budget_exhausted", "timeout", "unsupported_language")
INCIDENT_CATEGORIES = {"software_failure", "timeout", "misconfiguration", "access_denied"}

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS llm_calls (call_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task_id TEXT, "
    "agent_id TEXT NOT NULL, provider TEXT, model TEXT, purpose TEXT, tokens_in INTEGER, tokens_out INTEGER, "
    "latency_ms INTEGER, status TEXT NOT NULL, error_category TEXT, estimated_cost REAL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS agent_health (agent_id TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT, "
    "updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS incidents (incident_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, agent_id TEXT, "
    "task_id TEXT, error_category TEXT NOT NULL, diagnostic TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT "
    "NOT NULL, resolved_at TEXT, resolution TEXT)",
    "CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, agent_id TEXT, "
    "level TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id)",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str, secrets: list[str] | tuple = ()) -> str:
    """Remove secrets (API keys…) and the home path from a text before it is stored or shown."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text.replace(str(Path.home()), "~")


# =========================================================================== costs and budget
def estimate_cost_usd(pricing: dict, model: str, usage: dict, when: datetime | None = None) -> float | None:
    """Estimated cost of one call from the provider's usage. `pricing` (USD per million tokens):
    {"peak": {model: {"input_hit", "input_miss", "output"}}, "peak_hours_utc_mon_fri": [[lo, hi], …],
     "off_peak_factor": 0.5}. None when the model has no price (shown as unknown, never invented)."""
    table = pricing.get("peak", {}).get(model) if pricing else None
    if not table or not usage:
        return None
    when = when or datetime.now(timezone.utc)
    peak = (not pricing.get("peak_hours_utc_mon_fri")) or (
        when.weekday() < 5 and any(lo <= when.hour < hi for lo, hi in pricing["peak_hours_utc_mon_fri"]))
    factor = 1.0 if peak else pricing.get("off_peak_factor", 1.0)
    hit = usage.get("prompt_cache_hit_tokens", 0) or 0
    miss = usage.get("prompt_cache_miss_tokens", (usage.get("prompt_tokens", 0) or 0) - hit) or 0
    out = usage.get("completion_tokens", 0) or 0
    cost = (hit * table.get("input_hit", table["input_miss"]) + miss * table["input_miss"] + out * table["output"])
    return round(cost / 1_000_000 * factor, 6)


class Budget:
    """Limits of one run. `granted` (what the orchestrator still allows) can only LOWER the configured limits."""

    def __init__(self, limits: dict, granted: dict | None = None):
        granted = granted or {}
        self.calls = min(granted.get("llm_calls", limits["llm_calls_per_run"]), limits["llm_calls_per_run"])
        self.tokens = min(granted.get("llm_tokens", limits["llm_tokens_per_run"]), limits["llm_tokens_per_run"])
        self.cost = min(granted.get("llm_cost_usd", limits["llm_cost_usd_per_run"]), limits["llm_cost_usd_per_run"])
        self.used_calls = self.used_tokens = 0
        self.used_cost = 0.0

    def can_call(self) -> bool:
        return self.used_calls < self.calls and self.used_tokens < self.tokens and self.used_cost < self.cost

    def charge(self, records: list[dict]) -> None:
        for r in records:
            self.used_calls += 1
            self.used_tokens += (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0)
            self.used_cost += r.get("estimated_cost") or 0.0

    def remaining(self) -> dict:
        return {"llm_calls": max(0, self.calls - self.used_calls), "llm_tokens": max(0, self.tokens - self.used_tokens),
                "llm_cost_usd": max(0.0, round(self.cost - self.used_cost, 6))}


# =========================================================================== model client
class LLMError(Exception):
    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


def _http_transport(url: str, headers: dict, body: dict, timeout: float):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")[:500]


class LLMClient:
    """OpenAI-compatible JSON chat client for ONE provider and model (no automatic fallback).

    provider = {"name", "base_url", "chat_path", "api_key", "pricing"}; model = {"model", "max_tokens",
    "temperature"}. `transport(url, headers, body, timeout) -> (status, dict | str)` can be injected for tests.
    Every attempt appends a record to `self.calls` (store them with SupervisionStore.record_llm_calls); the key never
    appears in a record. Raises LLMError with a category of ERROR_CATEGORIES."""

    TRANSIENT = {429, 500, 502, 503, 504}

    def __init__(self, provider: dict, model: dict, agent_id: str, *, retries: int = 2, timeout: float = 120,
                 budget: Budget | None = None, transport=None):
        self.provider, self.model, self.agent_id = provider, model, agent_id
        self.retries, self.timeout, self.budget = retries, timeout, budget
        self.transport = transport or _http_transport
        self.calls: list[dict] = []

    def chat_json(self, messages: list[dict], *, purpose: str, run_id: str = "", task_id: str = "") -> dict:
        key = self.provider.get("api_key") or ""
        if not key:
            raise LLMError("misconfiguration", f"no API key for {self.provider.get('name')}")
        if self.budget and not self.budget.can_call():
            raise LLMError("budget_exhausted", "LLM budget of the run exhausted")
        body = {"model": self.model["model"], "messages": messages, "response_format": {"type": "json_object"},
                "max_tokens": self.model.get("max_tokens", 2000), "temperature": self.model.get("temperature", 0.0)}
        url = self.provider["base_url"].rstrip("/") + self.provider.get("chat_path", "/chat/completions")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        last = LLMError("software_failure", "no attempt")
        for attempt in range(1, self.retries + 2):
            started = datetime.now(timezone.utc)
            t0 = time.monotonic()
            rec = {"run_id": run_id, "task_id": task_id, "agent_id": self.agent_id, "provider": self.provider.get("name"),
                   "model": self.model["model"], "purpose": purpose, "tokens_in": None, "tokens_out": None,
                   "latency_ms": None, "status": "failed", "error_category": None, "estimated_cost": None,
                   "created_at": started.isoformat(timespec="seconds")}
            try:
                status, payload = self.transport(url, headers, body, self.timeout)
            except TimeoutError:
                status, payload = None, "timeout"
            except (OSError, ConnectionError, http.client.HTTPException) as exc:
                status, payload = None, f"network error: {type(exc).__name__}"
            rec["latency_ms"] = int((time.monotonic() - t0) * 1000)
            if status == 200 and isinstance(payload, dict):
                usage = payload.get("usage") or {}
                rec.update(tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"),
                           estimated_cost=estimate_cost_usd(self.provider.get("pricing", {}), self.model["model"], usage, started))
                choice = (payload.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    rec.update(error_category="software_failure")
                    self._keep(rec)
                    raise LLMError("software_failure", "model returned invalid JSON")
                rec["status"] = "succeeded"
                self._keep(rec)
                if not isinstance(parsed, dict):
                    raise LLMError("software_failure", "model JSON is not an object")
                return parsed
            category = ("access_denied" if status in (401, 403) else "budget_exhausted" if status == 402
                        else "timeout" if payload == "timeout" else "source_unavailable")
            rec["error_category"] = category
            self._keep(rec)
            last = LLMError(category, redact(f"HTTP {status}: {str(payload)[:200]}", [key]))
            if status not in self.TRANSIENT and status is not None:
                break
        raise last

    def _keep(self, rec: dict) -> None:
        self.calls.append(rec)
        if self.budget:
            self.budget.charge([rec])


# =========================================================================== store (sqlite)
class SupervisionStore:
    """Tables llm_calls, agent_health, incidents, events in the project's main database (one file)."""

    def __init__(self, db_path: str | Path, secrets: list[str] | tuple = ()):
        self.db_path, self.secrets = str(db_path), list(secrets)
        with self.connect() as c:
            for sql in SCHEMA:
                c.execute(sql)

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ---- costs
    def record_llm_calls(self, calls: list[dict]) -> int:
        cols = ("run_id", "task_id", "agent_id", "provider", "model", "purpose", "tokens_in", "tokens_out",
                "latency_ms", "status", "error_category", "estimated_cost", "created_at")
        with self.connect() as c:
            c.executemany(f"INSERT INTO llm_calls({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [tuple(r.get(k) for k in cols) for r in calls])
        return len(calls)

    def run_cost(self, run_id: str) -> dict:
        with self.connect() as c:
            r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(tokens_in), 0) tin, COALESCE(SUM(tokens_out), 0) tout, "
                          "COALESCE(SUM(estimated_cost), 0) cost FROM llm_calls WHERE run_id=?", (run_id,)).fetchone()
        return {"calls": r["n"], "tokens_in": r["tin"], "tokens_out": r["tout"], "cost": round(r["cost"], 6)}

    # ---- events
    def log_event(self, level: str, code: str, message: str, *, run_id: str | None = None,
                  agent_id: str | None = None) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO events(run_id, agent_id, level, code, message, created_at) VALUES (?,?,?,?,?,?)",
                      (run_id, agent_id, level, code, redact(message, self.secrets)[:2000], now_iso()))

    # ---- health
    def set_health(self, agent_id: str, state: str, detail: str = "") -> None:
        if state not in HEALTH_STATES:
            raise ValueError(state)
        with self.connect() as c:
            c.execute("INSERT INTO agent_health(agent_id, state, detail, updated_at) VALUES (?,?,?,?) ON CONFLICT"
                      "(agent_id) DO UPDATE SET state=excluded.state, detail=excluded.detail, updated_at=excluded.updated_at",
                      (agent_id, state, redact(detail, self.secrets)[:300], now_iso()))

    def health(self) -> dict[str, str]:
        with self.connect() as c:
            return {r["agent_id"]: r["state"] for r in c.execute("SELECT agent_id, state FROM agent_health")}

    def update_health_after_run(self, run_id: str, results: dict[str, str]) -> None:
        """After a run: `results` = {agent_id: final status of its work in this run}. An agent with an incident in
        the run becomes 'degraded'; a degraded agent that succeeded again becomes 'healthy'. Never 'critical' from
        here (only startup checks: missing tool, key or model)."""
        with self.connect() as c:
            with_incident = {r["agent_id"] for r in c.execute("SELECT agent_id FROM incidents WHERE run_id=?", (run_id,))}
        current = self.health()
        for agent, status in results.items():
            if agent in with_incident:
                self.set_health(agent, "degraded", f"incident in run {run_id}")
            elif status == "succeeded" and current.get(agent, "unknown") in ("degraded", "unknown"):
                self.set_health(agent, "healthy", f"succeeded in run {run_id}")

    # ---- incidents
    def open_incident(self, *, agent_id: str, category: str, errors: list[str], run_id: str | None = None,
                      task_id: str | None = None, extra: dict | None = None, dedupe_key: str | None = None) -> int | None:
        """Opens an incident for a defect or a configuration problem (INCIDENT_CATEGORIES, plus any category when
        `dedupe_key` is given for an operational failure such as a recording). With `dedupe_key`, at most one open
        incident per key. Returns its id, or None when none was opened."""
        if category not in ERROR_CATEGORIES:
            raise ValueError(category)
        if category not in INCIDENT_CATEGORIES and dedupe_key is None:
            return None
        diag = {"agent": agent_id, "errors": [redact(str(e), self.secrets)[:500] for e in errors][:5], **(extra or {})}
        if dedupe_key is not None:
            diag["key"] = dedupe_key
        with self.connect() as c:
            if dedupe_key is not None:
                for r in c.execute("SELECT incident_id, diagnostic FROM incidents WHERE status='open' AND agent_id=?", (agent_id,)):
                    if json.loads(r["diagnostic"]).get("key") == dedupe_key:
                        return None
            cur = c.execute("INSERT INTO incidents(run_id, agent_id, task_id, error_category, diagnostic, status, "
                            "created_at) VALUES (?,?,?,?,?, 'open', ?)",
                            (run_id, agent_id, task_id, category, json.dumps(diag, ensure_ascii=False), now_iso()))
            return cur.lastrowid

    def close_incident(self, incident_id: int, status: str, resolution: str = "") -> None:
        """'resolved' or 'ignored'. Does not change the agent's health (user choice 2026-11-20)."""
        if status not in ("resolved", "ignored"):
            raise ValueError(status)
        with self.connect() as c:
            cur = c.execute("UPDATE incidents SET status=?, resolved_at=?, resolution=? WHERE incident_id=? AND "
                            "status='open'", (status, now_iso(), resolution[:500], incident_id))
            if cur.rowcount == 0:
                raise KeyError(incident_id)

    # ---- data of the Supervision page (templates/standup.html)
    def standup(self, agents: list[str], days: int = 14, errors: int = 20) -> dict:
        """tiles, agents, incidents, costs (per day), errors — the variables of the kit's standup.html."""
        today = datetime.now(timezone.utc).date().isoformat()
        health = self.health()
        with self.connect() as c:
            info = {r["agent_id"]: dict(r) for r in c.execute("SELECT * FROM agent_health")}
            incidents = [dict(r) for r in c.execute("SELECT * FROM incidents WHERE status='open' ORDER BY incident_id DESC")]
            costs = [dict(r) for r in c.execute(
                "SELECT substr(created_at, 1, 10) day, COUNT(*) calls, COALESCE(SUM(tokens_in + tokens_out), 0) tokens, "
                "COALESCE(SUM(estimated_cost), 0) cost FROM llm_calls GROUP BY day ORDER BY day DESC LIMIT ?", (days,))]
            recent = [dict(r) for r in c.execute("SELECT * FROM events WHERE level='error' ORDER BY event_id DESC LIMIT ?",
                                                 (errors,))]
            total = c.execute("SELECT COALESCE(SUM(estimated_cost), 0) FROM llm_calls").fetchone()[0]
        for i in incidents:
            d = json.loads(i["diagnostic"])
            i["message"], i["agent"], i["id"] = " · ".join(d.get("errors", [])), i["agent_id"], i["incident_id"]
        agent_rows = [{"id": a, "state": health.get(a, "unknown"), "detail": (info.get(a) or {}).get("detail", ""),
                       "when": (info.get(a) or {}).get("updated_at", "")} for a in agents]
        ok = sum(1 for a in agent_rows if a["state"] == "healthy")
        cost_today = next((x["cost"] for x in costs if x["day"] == today), 0.0)
        tiles = [{"label": "Agents", "value": f"{ok}/{len(agents)}", "sub": "healthy",
                  "tone": "good" if ok == len(agents) else ("bad" if any(a["state"] == "critical" for a in agent_rows) else "warn")},
                 {"label": "Cost today", "value": f"${cost_today:.3f}", "sub": f"${total:.3f} since the start"},
                 {"label": "Incidents", "value": len(incidents), "sub": "open", "tone": "bad" if incidents else "good"}]
        return {"tiles": tiles, "agents": agent_rows, "incidents": incidents, "costs": costs, "errors": recent}
