"""STUDIO KIT — socle de supervision (version 2.0, 2026-11-20), extrait d'auto_clip et rendu générique.

Ce que la page Supervision du kit affiche, mesuré pour de vrai :
  - coût de chaque appel à un modèle d'IA (jetons, latence, $), rattaché au run et à l'agent ;
  - budget par run (appels, jetons, $) qui ne peut que BAISSER la dépense ;
  - santé de chaque agent dans le temps (unknown / healthy / degraded / critical / disabled) ;
  - incidents (ouverts, résolus, ignorés) et événements (journal nettoyé, sans secret) ;
  - les données prêtes pour la page Supervision (tuiles, agents, incidents, coûts par jour, erreurs récentes).
Depuis la 2.0 (tout ce qui est réutilisable dans auto_clip) :
  - skills versionnées par agent (proposée → validation → active) ;
  - validations en attente (une action sensible n'est appliquée qu'après accord, avec cible et paramètres) ;
  - contrôles qualité nommés et leurs résultats (pass / corrected / kept_despite) ;
  - notes de l'utilisateur sur les résultats (good / bad) ;
  - runs et tâches (statuts, frise d'étapes, runs interrompus), corbeille avec délai de grâce ;
  - profils de modèle par usage (jamais de bascule automatique) ;
  - sauvegarde quotidienne vérifiée, espace disque, contrôles au démarrage, brief de réparation, garde-fou des tests.
Compatible 1.0 : mêmes fonctions et clés, des clés en plus. Les tables de runs s'appellent sup_runs / sup_tasks
pour ne pas heurter une table « runs » existante d'un projet.

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

RUN_STATUSES = ("pending", "running", "succeeded", "partial", "failed", "cancelled")
TASK_STATUSES = ("pending", "running", "waiting_dependency", "waiting_approval", "succeeded", "partial", "failed",
                 "blocked", "cancelled", "skipped", "not_run")
SKILL_STATUSES = ("proposed", "validated", "active", "retired")
CHECK_OUTCOMES = ("pass", "corrected", "kept_despite")
RATING_LABELS = ("good", "bad")
SCHEMA_V2 = (
    "CREATE TABLE IF NOT EXISTS skills (skill_id TEXT NOT NULL, version TEXT NOT NULL, agent_id TEXT NOT NULL, "
    "status TEXT NOT NULL, objective TEXT, summary TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (skill_id, version))",
    "CREATE TABLE IF NOT EXISTS approvals (approval_id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, "
    "target TEXT NOT NULL, parameters TEXT NOT NULL, status TEXT NOT NULL, requested_at TEXT NOT NULL, decided_at TEXT, "
    "outcome TEXT)",
    "CREATE TABLE IF NOT EXISTS quality_checks (check_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, name TEXT NOT NULL, "
    "origin_case TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS check_outcomes (outcome_id INTEGER PRIMARY KEY AUTOINCREMENT, check_id TEXT NOT NULL, "
    "run_id TEXT, item_id TEXT, outcome TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ratings (rating_id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, "
    "label TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS sup_runs (run_id TEXT PRIMARY KEY, title TEXT, status TEXT NOT NULL, created_at TEXT "
    "NOT NULL, completed_at TEXT, owner_pid INTEGER, params TEXT NOT NULL DEFAULT '{}', totals TEXT NOT NULL DEFAULT '{}')",
    "CREATE TABLE IF NOT EXISTS sup_tasks (task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_task_id TEXT, "
    "agent_id TEXT NOT NULL, objective TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0, "
    "detail TEXT, created_at TEXT NOT NULL, completed_at TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_sup_tasks_run ON sup_tasks(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_check_outcomes_check ON check_outcomes(check_id)",
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
                 budget: Budget | None = None, transport=None, profiles: dict | None = None, profile: str | None = None):
        self.provider, self.model, self.agent_id = provider, model, agent_id
        self.profiles, self.profile = profiles or {}, profile
        if profile is not None and profile not in self.profiles:
            raise ValueError(f"unknown model profile {profile!r}")   # refused before any call, never a fallback
        self.retries, self.timeout, self.budget = retries, timeout, budget
        self.transport = transport or _http_transport
        self.calls: list[dict] = []

    def chat_json(self, messages: list[dict], *, purpose: str, run_id: str = "", task_id: str = "") -> dict:
        key = self.provider.get("api_key") or ""
        if not key:
            raise LLMError("misconfiguration", f"no API key for {self.provider.get('name')}")
        if self.budget and not self.budget.can_call():
            raise LLMError("budget_exhausted", "LLM budget of the run exhausted")
        model = profile_model(self.model, self.profiles, self.profile, self.agent_id, purpose)   # LLM_PROFILE
        body = {"model": model["model"], "messages": messages, "response_format": {"type": "json_object"},
                "max_tokens": model.get("max_tokens", 2000), "temperature": model.get("temperature", 0.0)}
        url = self.provider["base_url"].rstrip("/") + self.provider.get("chat_path", "/chat/completions")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        last = LLMError("software_failure", "no attempt")
        for attempt in range(1, self.retries + 2):
            started = datetime.now(timezone.utc)
            t0 = time.monotonic()
            rec = {"run_id": run_id, "task_id": task_id, "agent_id": self.agent_id, "provider": self.provider.get("name"),
                   "model": model["model"], "purpose": purpose, "tokens_in": None, "tokens_out": None,
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
                           estimated_cost=estimate_cost_usd(self.provider.get("pricing", {}), model["model"], usage, started))
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
            for sql in SCHEMA + SCHEMA_V2:
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

    # --------------------------------------------------------------------------------------------- skills
    def register_skills(self, agent_id: str, skills: list[dict]) -> int:
        """Skills declared by an agent module: [{"skill_id", "version", "objective", "summary", "status"?}]. A new
        skill/version is inserted with its declared status (default 'proposed'); a known one keeps the status decided
        by the user (only its texts are refreshed)."""
        n = 0
        with self.connect() as c:
            for sk in skills:
                status = sk.get("status", "proposed")
                if status not in SKILL_STATUSES:
                    raise ValueError(status)
                c.execute("INSERT INTO skills(skill_id, version, agent_id, status, objective, summary, updated_at) "
                          "VALUES (?,?,?,?,?,?,?) ON CONFLICT(skill_id, version) DO UPDATE SET agent_id=excluded.agent_id, "
                          "objective=excluded.objective, summary=excluded.summary",
                          (sk["skill_id"], str(sk["version"]), agent_id, status, sk.get("objective"), sk.get("summary"),
                           now_iso()))
                n += 1
        return n

    def skills(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM skills ORDER BY agent_id, skill_id, version")]

    def propose_skill_activations(self) -> int:
        """One approval 'activate_skill' per skill that is not active yet (the user decides on the Supervision page)."""
        return sum(1 for sk in self.skills() if sk["status"] not in ("active", "retired")
                   and self.request_approval("activate_skill", f"{sk['skill_id']}@{sk['version']}", {}))

    # --------------------------------------------------------------------------------------------- approvals
    def request_approval(self, action: str, target: str, parameters: dict) -> int | None:
        """A sensitive action waiting for the user, with its exact target and parameters. None if the same action on
        the same target is already pending."""
        with self.connect() as c:
            if c.execute("SELECT 1 FROM approvals WHERE action=? AND target=? AND status='pending'", (action, target)).fetchone():
                return None
            cur = c.execute("INSERT INTO approvals(action, target, parameters, status, requested_at) VALUES (?,?,?, 'pending', ?)",
                            (action, target, json.dumps(parameters, ensure_ascii=False), now_iso()))
            return cur.lastrowid

    def decide(self, approval_id: int, approve: bool, handlers: dict | None = None) -> dict:
        """Applies (approve=True) or rejects a pending approval. `handlers` = {action: fn(target, parameters) -> dict}
        for the project's own actions; 'activate_skill' is built in. An approved action without a handler is refused
        (KeyError) and stays pending: nothing is applied blindly. The decision is logged as an event."""
        with self.connect() as c:
            row = c.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if row is None or row["status"] != "pending":
            raise KeyError(approval_id)
        params = json.loads(row["parameters"])
        outcome = {"applied": False}
        if approve:
            if row["action"] == "activate_skill":
                skill_id, version = row["target"].split("@", 1)
                with self.connect() as c:
                    c.execute("UPDATE skills SET status='active', updated_at=? WHERE skill_id=? AND version=?",
                              (now_iso(), skill_id, version))
                outcome = {"applied": True}
            else:
                fn = (handlers or {}).get(row["action"])
                if fn is None:
                    raise KeyError(f"no handler for action {row['action']!r}")
                outcome = fn(row["target"], params) or {"applied": True}
        status = "approved" if approve else "rejected"
        with self.connect() as c:
            c.execute("UPDATE approvals SET status=?, decided_at=?, outcome=? WHERE approval_id=?",
                      (status, now_iso(), json.dumps(outcome, ensure_ascii=False, default=str), approval_id))
        self.log_event("info", f"approval_{status}", f"{row['action']} {row['target']}: {outcome}")
        return outcome

    def approvals(self, status: str = "pending") -> list[dict]:
        with self.connect() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM approvals WHERE status=? ORDER BY approval_id", (status,))]
        for r in rows:
            r["parameters"] = json.loads(r["parameters"])
        return rows

    # --------------------------------------------------------------------------------------------- quality checks
    def register_check(self, check_id: str, agent_id: str, name: str, origin_case: str) -> None:
        """A named check (e.g. ENDING_COMPLETE) with the real case that created it (rule of the method: each defect seen
        on a real run becomes a named check citing that case)."""
        with self.connect() as c:
            c.execute("INSERT INTO quality_checks(check_id, agent_id, name, origin_case, created_at) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(check_id) DO UPDATE SET name=excluded.name, origin_case=excluded.origin_case",
                      (check_id, agent_id, name, origin_case, now_iso()))

    def record_outcomes(self, run_id: str | None, outcomes: list[dict]) -> int:
        """[{"check": id, "outcome": pass|corrected|kept_despite, "detail", "item"}]; an unknown check is registered
        with agent 'unknown' rather than lost."""
        n = 0
        with self.connect() as c:
            known = {r[0] for r in c.execute("SELECT check_id FROM quality_checks")}
            for o in outcomes:
                if o["outcome"] not in CHECK_OUTCOMES:
                    raise ValueError(o["outcome"])
                if o["check"] not in known:
                    c.execute("INSERT INTO quality_checks(check_id, agent_id, name, origin_case, created_at) "
                              "VALUES (?, 'unknown', ?, 'not registered', ?)", (o["check"], o["check"], now_iso()))
                    known.add(o["check"])
                c.execute("INSERT INTO check_outcomes(check_id, run_id, item_id, outcome, detail, created_at) VALUES (?,?,?,?,?,?)",
                          (o["check"], run_id, o.get("item"), o["outcome"], redact(str(o.get("detail", "")), self.secrets)[:500],
                           now_iso()))
                n += 1
        return n

    def check_summary(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT o.check_id, q.name, q.origin_case, o.outcome, COUNT(*) AS count FROM check_outcomes o "
                "JOIN quality_checks q USING(check_id) GROUP BY o.check_id, o.outcome ORDER BY o.check_id, o.outcome")]

    # --------------------------------------------------------------------------------------------- ratings
    def rate(self, item_id: str, label: str, note: str = "") -> None:
        """The user's opinion of a result (good / bad + note); the latest rating of an item counts."""
        if label not in RATING_LABELS:
            raise ValueError(label)
        with self.connect() as c:
            c.execute("INSERT INTO ratings(item_id, label, note, created_at) VALUES (?,?,?,?)",
                      (item_id, label, note[:500], now_iso()))

    def ratings_summary(self) -> dict:
        with self.connect() as c:
            rows = c.execute("SELECT label, COUNT(*) FROM ratings r WHERE rating_id = (SELECT MAX(rating_id) FROM ratings "
                             "WHERE item_id = r.item_id) GROUP BY label").fetchall()
        out = {lab: 0 for lab in RATING_LABELS}
        out.update({r[0]: r[1] for r in rows})
        return out

    # --------------------------------------------------------------------------------------------- runs and tasks
    def new_run(self, title: str, params: dict | None = None) -> str:
        import os
        import uuid
        run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
        with self.connect() as c:
            c.execute("INSERT INTO sup_runs(run_id, title, status, created_at, owner_pid, params) VALUES (?,?, 'running', ?,?,?)",
                      (run_id, title, now_iso(), os.getpid(), json.dumps(params or {}, ensure_ascii=False)))
        return run_id

    def new_task(self, run_id: str, agent_id: str, objective: str, *, parent: str | None = None,
                 status: str = "pending") -> str:
        if status not in TASK_STATUSES:
            raise ValueError(status)
        with self.connect() as c:
            n = c.execute("SELECT COUNT(*) FROM sup_tasks WHERE run_id=?", (run_id,)).fetchone()[0] + 1
            task_id = f"{run_id}_t{n:03d}_{agent_id}"
            c.execute("INSERT INTO sup_tasks(task_id, run_id, parent_task_id, agent_id, objective, status, created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (task_id, run_id, parent, agent_id, objective, status, now_iso()))
        return task_id

    def set_task(self, task_id: str, status: str, detail: str = "") -> None:
        if status not in TASK_STATUSES:
            raise ValueError(status)
        done = status in ("succeeded", "partial", "failed", "cancelled", "skipped", "not_run")
        with self.connect() as c:
            c.execute("UPDATE sup_tasks SET status=?, detail=?, attempt_count=attempt_count + (?='running'), "
                      "completed_at=CASE WHEN ? THEN ? ELSE completed_at END WHERE task_id=?",
                      (status, redact(detail, self.secrets)[:500], status, done, now_iso(), task_id))

    def finish_run(self, run_id: str, status: str, totals: dict | None = None) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(status)
        with self.connect() as c:
            c.execute("UPDATE sup_runs SET status=?, completed_at=?, totals=? WHERE run_id=?",
                      (status, now_iso(), json.dumps(totals or {}, ensure_ascii=False, default=str), run_id))

    def stage_states(self, run_id: str, stages: list[tuple[str, str]]) -> list[dict]:
        """One state per pipeline step [(agent_id, name)] for the kit's .stepper: running > failed (nothing done) >
        succeeded > skipped > not_run; a first step skipped while later ones went on is 'reused' (auto_clip: a
        transcription taken from another run is not 'skipped')."""
        with self.connect() as c:
            tasks = [dict(r) for r in c.execute("SELECT agent_id, status FROM sup_tasks WHERE run_id=?", (run_id,))]
        out = []
        for agent, name in stages:
            sts = [t["status"] for t in tasks if t["agent_id"] == agent]
            if not sts:
                state = "pending"
            elif "running" in sts:
                state = "running"
            elif "failed" in sts and not any(s in ("succeeded", "partial") for s in sts):
                state = "failed"
            elif any(s in ("succeeded", "partial") for s in sts):
                state = "succeeded"
            elif all(s == "skipped" for s in sts):
                state = "skipped"
            elif "not_run" in sts:
                state = "not_run"
            else:
                state = sts[-1]
            out.append({"agent": agent, "name": name, "state": state, "count": len(sts),
                        "done": sum(1 for s in sts if s in ("succeeded", "partial"))})
        if out and out[0]["state"] == "skipped" and any(s["state"] in ("succeeded", "running") for s in out[1:]):
            out[0]["state"] = "reused"
        return out

    def mark_interrupted_runs(self) -> list[str]:
        """At start: runs left pending/running by a process that no longer exists are closed 'failed' (never a run
        whose owner is still alive: auto_clip RUN_OWNER_ALIVE)."""
        import os
        closed = []
        with self.connect() as c:
            for r in c.execute("SELECT run_id, owner_pid FROM sup_runs WHERE status IN ('pending','running')").fetchall():
                try:
                    if r["owner_pid"]:
                        os.kill(int(r["owner_pid"]), 0)
                        continue
                except PermissionError:
                    continue
                except (ProcessLookupError, ValueError):
                    pass
                c.execute("UPDATE sup_runs SET status='failed', completed_at=? WHERE run_id=?", (now_iso(), r["run_id"]))
                c.execute("UPDATE sup_tasks SET status='cancelled', completed_at=? WHERE run_id=? AND status IN "
                          "('pending','running','waiting_dependency','waiting_approval')", (now_iso(), r["run_id"]))
                closed.append(r["run_id"])
        for rid in closed:
            self.log_event("warning", "run_interrupted", "application stopped during the run", run_id=rid)
        return closed

    # --------------------------------------------------------------------------------------------- trash
    def trash_run(self, run_id: str, days: int = 7) -> str:
        """RUN_TRASH: the run goes to the trash (archive); restorable for `days`, then erased by purge_trash.
        Refused while the run is pending/running. Returns the purge date."""
        from datetime import timedelta
        with self.connect() as c:
            row = c.execute("SELECT status FROM sup_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        if row["status"] in ("pending", "running"):
            raise RuntimeError("a run in progress cannot be deleted")
        purge_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
        self.log_event("info", "run_trashed", purge_at, run_id=run_id)
        return purge_at

    def trashed_runs(self) -> dict[str, str]:
        """{run_id: purge date} of the runs in the trash now (the last trash event is not a restore)."""
        state: dict[str, str | None] = {}
        with self.connect() as c:
            for r in c.execute("SELECT run_id, code, message FROM events WHERE code IN ('run_trashed','run_restored',"
                               "'run_trash_purged') AND run_id IS NOT NULL ORDER BY event_id"):
                state[r["run_id"]] = r["message"] if r["code"] == "run_trashed" else None
        return {k: v for k, v in state.items() if v}

    def restore_run(self, run_id: str) -> bool:
        if run_id not in self.trashed_runs():
            return False
        self.log_event("info", "run_restored", "taken out of the trash", run_id=run_id)
        return True

    def purge_trash(self, erase, now: datetime | None = None) -> list[str]:
        """Erases the runs whose purge date has passed: `erase(run_id) -> freed bytes` removes the project's files
        (checked inside the project's folders by the project); database rows are kept."""
        now = now or datetime.now(timezone.utc)
        done = []
        for run_id, due in self.trashed_runs().items():
            if datetime.fromisoformat(due) > now:
                continue
            freed = erase(run_id) or 0
            self.log_event("info", "run_trash_purged", json.dumps({"freed_bytes": freed}), run_id=run_id)
            done.append(run_id)
        return done

    # --------------------------------------------------------------------------------------------- operations
    def startup_check(self, checks: dict) -> dict[str, str]:
        """`checks` = {agent_id: fn() -> (state, detail)} (key present, tool installed, model reachable…). The only place
        that sets 'critical'; a check that raises makes its agent critical with the error (cleaned)."""
        out = {}
        for agent, fn in checks.items():
            try:
                state, detail = fn()
            except Exception as exc:  # noqa: BLE001 - reported, never kills the start
                state, detail = "critical", f"{type(exc).__name__}: {exc}"
            self.set_health(agent, state, detail)
            out[agent] = state
        return out

    def backup_database(self, folder: str | Path, name: str, extra_files: list[Path] = (), force: bool = False) -> dict:
        """Daily backup: consistent SQLite copy (backup API) verified with integrity_check, plus extra files (instance
        config); files named <name>_<YYYYMMDD>.db, private (0600), never deleted automatically."""
        import os
        import shutil
        folder = Path(folder).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        day = time.strftime("%Y%m%d")
        target = folder / f"{name}_{day}.db"
        if target.exists() and not force:
            return {"path": str(target), "created": False, "integrity": "ok"}
        tmp = target.with_suffix(".db.part")
        src, dst = self.connect(), sqlite3.connect(tmp)
        try:
            src.backup(dst)
            integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
            src.close()
        if integrity != "ok":
            tmp.unlink(missing_ok=True)
            self.log_event("error", "backup_failed", f"integrity_check: {integrity}")
            raise RuntimeError(f"backup integrity check failed: {integrity}")
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        for f in extra_files:
            f = Path(f)
            if f.is_file():
                copy = folder / f"{name}_{day}{f.suffix}"
                shutil.copy2(f, copy)
                os.chmod(copy, 0o600)
        self.log_event("info", "backup_done", f"{target.name} ({target.stat().st_size} bytes)")
        return {"path": str(target), "created": True, "integrity": integrity}

    def repair_brief(self, incident_id: int, modules: dict[str, str] | None = None) -> str:
        """Steps 1-3 of assisted repair as Markdown (incident, cleaned diagnostic, context, procedure). No patch is
        produced or applied automatically."""
        with self.connect() as c:
            row = c.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if row is None:
            raise KeyError(incident_id)
        diag = json.loads(row["diagnostic"])
        module = (modules or {}).get(row["agent_id"], "")
        lines = [f"# Incident {incident_id} — {row['agent_id']}", "",
                 f"- run: `{row['run_id']}`  task: `{row['task_id']}`", f"- category: `{row['error_category']}`",
                 f"- opened: {row['created_at']}  status: {row['status']}", "", "## Errors (secrets and home path removed)", ""]
        lines += [f"- {e}" for e in diag.get("errors", [])]
        lines += ["", "## Context", "", f"- code: `{module}`" if module else "- code: (agent module)", "",
                  "## Procedure", "", "1. Reproduce on a copy (git worktree), never on the working copy.",
                  "2. Write a failing test that cites this incident.", "3. Fix the responsible agent at the root.",
                  "4. Run the WHOLE test suite.", "5. Show the diff and the results; apply only after approval."]
        return "\n".join(lines) + "\n"

    # --------------------------------------------------------------------------------------------- the whole page
    def dashboard(self, agents: list[str], days: int = 14) -> dict:
        """Everything the kit's standup.html shows (2.0): standup() keys + runs in progress, recent runs (with trash),
        skills, pending approvals, quality checks, ratings."""
        data = self.standup(agents, days=days)
        trash = self.trashed_runs()
        with self.connect() as c:
            active = [dict(r) for r in c.execute("SELECT * FROM sup_runs WHERE status IN ('pending','running') "
                                                 "ORDER BY created_at DESC")]
            recent = [dict(r) for r in c.execute("SELECT * FROM sup_runs ORDER BY created_at DESC LIMIT 50")]
        for r in recent:
            r["trash"] = trash.get(r["run_id"])
        pending = self.approvals()
        data.update(runs_active=active, runs_recent=recent, skills=self.skills(), approvals=pending,
                    checks=self.check_summary(), ratings=self.ratings_summary())
        data["tiles"].append({"label": "Approvals", "value": len(pending), "sub": "waiting for you",
                              "tone": "warn" if pending else "good"})
        return data

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


# =========================================================================== module helpers (2.0)
# --------------------------------------------------------------------------------------------- model profiles
def profile_model(model: dict, profiles: dict, profile: str | None, agent_id: str, purpose: str) -> dict:
    """LLM_PROFILE (auto_clip): the model settings for one purpose of one agent under a named profile, e.g.
    profiles = {"default": {}, "mixed": {"agent002": {"select": {"model": "pro-model"}}}}. Unknown profile ->
    ValueError (never a silent fallback). The profile is chosen per run by the user; nothing switches by itself."""
    if profile is None:
        return dict(model)
    if profile not in profiles:
        raise ValueError(f"unknown model profile {profile!r}")
    return {**model, **((profiles[profile] or {}).get(agent_id, {}).get(purpose, {}))}


def backups(folder: str | Path, name: str) -> list[dict]:
    folder = Path(folder).expanduser()
    return [{"name": p.name, "size_kb": p.stat().st_size // 1024} for p in sorted(folder.glob(f"{name}_*.db"), reverse=True)]


def disk_usage(paths: dict[str, str | Path]) -> dict:
    """{label: size in bytes} of the project's folders + 'free' (space left on the disk of the first one)."""
    import shutil
    out = {}
    first = None
    for label, p in paths.items():
        p = Path(p)
        first = first or p
        out[label] = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0
    if first is not None:
        out["free"] = shutil.disk_usage(first if first.exists() else first.parent).free
    return out


def busy_runs(db_path: str | Path, extra_sql: tuple[str, ...] = ()) -> list[str]:
    """Test guard (auto_clip TESTS_NOT_DURING_A_RUN): runs of the REAL database still pending/running with a live
    owner, plus the ids returned by `extra_sql` (e.g. a live recording in progress). A test suite calls it in
    conftest.py / at start and refuses to run when the list is not empty (it could starve a real run of memory)."""
    import os
    db_path = Path(db_path)
    if not db_path.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        rows = con.execute("SELECT run_id, owner_pid FROM sup_runs WHERE status IN ('pending','running')").fetchall() \
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='sup_runs'").fetchone() else []
        extra = [str(r[0]) for sql in extra_sql for r in con.execute(sql)]
        con.close()
    except sqlite3.Error:
        return []
    alive = []
    for run_id, pid in rows:
        try:
            if pid:
                os.kill(int(pid), 0)
                alive.append(run_id)
        except (ProcessLookupError, ValueError):
            pass
        except PermissionError:
            alive.append(run_id)
    return alive + extra
