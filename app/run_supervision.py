"""
The supervision of breeze's runs, on the studio kit's socle (app/supervision.py, copied as is):

  store()                       the SupervisionStore on app/instance/breeze.db (tables llm_calls, agent_health,
                                incidents, events), with the secrets of .env and of the environment to hide
  supervise(store, run_id, channel_id, statuses, errors)
                                called by agent000 at the end of each channel's run, from its reports:
                                  - an agent in failure ("critical") whose cause is a defect or a configuration
                                    (software_failure, timeout, misconfiguration, access_denied) opens an incident,
                                    its error cleaned (secrets and the home path removed);
                                  - every error and warning goes to events;
                                  - update_health_after_run: an agent with an incident in the run becomes
                                    "degraded"; a degraded one that succeeds again becomes "healthy". Closing an
                                    incident does NOT change the agent's health (the socle's rule).
  error_category(error)         the socle's category for a breeze error message

The costs stay app/costs.py's (app/instance/costs_history.json): it counts the voice too, which the socle's
LLMClient does not. Nothing here calls a model.
"""

import os
import re

from app.supervision import SupervisionStore

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "app", "instance", "breeze.db")
ENV_PATH = os.path.join(BASE_DIR, ".env")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|DB_URL", re.IGNORECASE)

# breeze's error messages -> the socle's categories, the first rule that matches. A refusal of the QA, a topic
# repeated, a curriculum finished or a picture the renderer cannot draw is a result, not a defect: no incident.
CATEGORY_RULES = (
    ("valid_empty_result", re.compile(r"QA verdict is not pass|still rejected after|repeats one already made|every topic "
                                      r"proposed repeats|every episode of the curriculum is made|Renderer limitation",
                                      re.IGNORECASE)),
    ("timeout", re.compile(r"timed? ?out|timeout|took longer", re.IGNORECASE)),
    ("access_denied", re.compile(r"\b40[13]\b|unauthori[sz]ed|forbidden|permission|invalid (?:api )?key|quota|credit|"
                                 r"insufficient balance", re.IGNORECASE)),
    ("misconfiguration", re.compile(r"not set|no api key|missing \.env|unknown renderer|not in routes|channel route|"
                                    r"settings\.json|no such (?:file|model)", re.IGNORECASE)),
)
SUCCEEDED = {"healthy", "not_healthy", "revision_needed"}     # finished (a warning or a QA revision is a result)


def env_secrets(path=ENV_PATH):
    """The values of .env and of the environment whose name says secret (KEY, TOKEN, SECRET, PASSWORD, DB_URL):
    hidden from every stored diagnostic and event. Short values (under 8 characters) are not secrets."""
    values = {v for k, v in os.environ.items() if SECRET_NAME.search(k)}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                name, _, value = line.strip().partition("=")
                if value and not name.startswith("#") and SECRET_NAME.search(name):
                    values.add(value.strip().strip("'\""))
    except OSError:
        pass
    return sorted(v for v in values if len(v) >= 8)


def store(db_path=None):
    """On the database the pipeline uses at this moment (app.agent.DB_PATH, which the orchestrator's tests point at a
    temporary folder: the tests of 2026-11-20 wrote their fake run into the real breeze.db before this)."""
    from app import agent as helpers
    return SupervisionStore(db_path or helpers.DB_PATH, secrets=env_secrets())


def error_category(error):
    """The socle's category for an error message of breeze; software_failure when nothing else says."""
    for category, rule in CATEGORY_RULES:
        if rule.search(str(error or "")):
            return category
    return "software_failure"


def supervise(supervision, run_id, channel_id, statuses, errors, rows=(), revisions=0):
    """After one channel's run. `statuses` {agent: breeze status}, `errors` {agent: its errors, "; "-joined or None},
    `rows` the rows its agents wrote (the checks' outcomes are read from them). Returns the ids of the incidents
    opened."""
    supervision.record_outcomes(run_id, [{**o, "item": channel_id} for o in outcomes(list(rows), revisions)])
    opened = []
    for agent, status in statuses.items():
        error = errors.get(agent)
        if status == "critical":
            category = error_category(error)
            incident = supervision.open_incident(agent_id=agent, category=category, errors=[error or "failed, no message"],
                                                 run_id=run_id, extra={"channel": channel_id})
            if incident:
                opened.append(incident)
            supervision.log_event("error", category, f"{channel_id} · {error or 'failed, no message'}",
                                  run_id=run_id, agent_id=agent)
        elif error:
            supervision.log_event("warning", status, f"{channel_id} · {error}", run_id=run_id, agent_id=agent)
    supervision.update_health_after_run(run_id, {agent: "succeeded" if status in SUCCEEDED else "failed"
                                                 for agent, status in statuses.items() if status not in ("not_run", "skipped")})
    return opened


# =========================================================================== socle 2.0: skills, checks, start, backups
# breeze's named checks, each with the real case that made it (the method: a defect seen on a real run becomes a
# named check citing it). Their outcomes are read from what the agents already write (outcomes()).
CHECKS = (
    ("SCRIPT_RULES", "agent003", "Narration rules: acronyms said in full, scenes long enough",
     "acronyms spoken before being said in full (FPGA, PIB) and scenes too short for their picture"),
    ("STORYBOARD_COHERENCE", "agent004", "The picture follows the narration (sent back to the LLM until it does)",
     "German run of 2026-11-16: « Ich bleibe heute zu Hause, weil ich krank bin » said, only « weil ich bin krank » drawn"),
    ("SENTENCE_VERDICTS", "agent004", "A wrong German order is shown marked, then turned right",
     "German run 3 of 2026-11-16: « ich heute bleibe zu Hause » shown under « Phrase principale », no ✗"),
    ("QA_REVIEW", "agent005", "The QA's review: passed as is, or corrected before the render",
     "German run 5 of 2026-11-20: « Ich gehe im Park » (correct German) shown as the error"),
    ("LAYOUT_MEASURED", "agent005", "Nothing overlaps or leaves the frame, measured on the page",
     "German run 7 of 2026-11-20: the B2 sentence ran past the right edge, « werden » cut"),
    ("RENDER_WARNINGS", "agent010", "The render finished without a warning (voice fallback, footage missing)",
     "a scene's ElevenLabs voice replaced by edge-tts mid-video (mixed voices)"),
)


def register_skills_and_checks(supervision, modules):
    """At start: every agent module's SKILLS (a new skill starts 'proposed'; a known one keeps the status the user
    decided) and breeze's named checks."""
    for module in modules:
        if getattr(module, "SKILLS", None):
            supervision.register_skills(module.AGENT, module.SKILLS)
    for check_id, agent, name, origin in CHECKS:
        supervision.register_check(check_id, agent, name, origin)


def _data(rows, agent):
    """The last row an agent wrote in this run (its finish() data)."""
    found = [r.get("data") or {} for r in rows if r.get("agent") == agent and isinstance(r.get("data"), dict)]
    return found[-1] if found else None


def outcomes(rows, revisions=0):
    """The checks' outcomes of one channel's run, from the rows its agents wrote: pass, corrected (fixed before the
    end, by the LLM or by the program) or kept_despite (left in the video). A check whose agent did not run has none."""
    out = []
    script = _data(rows, "agent003")
    if script is not None:
        left = list(script.get("acronyms_undefined") or []) + list(script.get("short_scenes") or [])
        out.append({"check": "SCRIPT_RULES", "outcome": "kept_despite" if left else "pass", "detail": "; ".join(map(str, left))})
    board = _data(rows, "agent004")
    if board is not None:
        left = board.get("coherence_left") or []
        out.append({"check": "STORYBOARD_COHERENCE",
                    "outcome": "kept_despite" if left else ("corrected" if (board.get("attempts") or 1) > 1 else "pass"),
                    "detail": "; ".join(map(str, left))[:400] or f"{board.get('attempts', 1)} attempt(s)"})
        marked = [f for f in board.get("sync_fixes") or [] if "marked ✗" in str(f) or "marked ✓" in str(f)]
        if marked:
            out.append({"check": "SENTENCE_VERDICTS", "outcome": "corrected", "detail": "; ".join(marked)[:400]})
    qa = _data(rows, "agent005")
    if qa is not None and qa.get("verdict") == "pass":
        corrected = (qa.get("corrected_count") or 0) or revisions
        out.append({"check": "QA_REVIEW", "outcome": "corrected" if corrected else "pass",
                    "detail": f"{qa.get('corrected_count') or 0} correction(s), {revisions} revision(s)"})
        conflicts = qa.get("layout_conflicts") or []
        out.append({"check": "LAYOUT_MEASURED", "outcome": "kept_despite" if conflicts else "pass",
                    "detail": f"{len(conflicts)} conflict(s)" + (f": {conflicts[0]}" if conflicts else "")})
    render = _data(rows, "agent010")
    if render is not None:
        warnings = render.get("warnings") or []
        out.append({"check": "RENDER_WARNINGS", "outcome": "kept_despite" if warnings else "pass",
                    "detail": "; ".join(map(str, warnings))[:400]})
    return out


LLM_KEYS = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
LLM_AGENTS = ("agent001", "agent002", "agent003", "agent004", "agent005", "agent007")


def startup_checks(supervision, settings, env=None, which=None):
    """{agent: fn() -> (state, detail)} for the socle's startup_check, the only place that sets 'critical': the LLM key
    of the provider in settings for the agents that call it; ffmpeg and Playwright for the renderer; the YouTube keys
    for the publisher when it publishes. A check that passes keeps an agent's 'degraded' (an incident heals at the next
    good run, never at a restart) and lifts a 'critical' or 'unknown' to 'healthy'."""
    import shutil
    env = os.environ if env is None else env
    which = which or shutil.which
    current = supervision.health()

    def ok(agent, detail):
        state = current.get(agent, "unknown")
        return ("degraded" if state == "degraded" else "healthy"), detail

    def needs(agent, missing, detail):
        return lambda: ("critical", f"missing: {', '.join(missing)}") if missing else ok(agent, detail)

    provider = str(settings.get("llm_provider") or "")
    key = LLM_KEYS.get(provider)
    llm_missing = [] if provider == "ollama" else ([key] if key and not env.get(key) else ([] if key else [f"provider {provider!r}"]))
    checks = {agent: needs(agent, llm_missing, f"{provider} key present") for agent in LLM_AGENTS}
    render_missing = [tool for tool in ("ffmpeg", "ffprobe") if not which(tool)]
    try:
        import playwright  # noqa: F401
    except ImportError:
        render_missing.append("playwright")
    checks["agent010"] = needs("agent010", render_missing, "ffmpeg and Playwright found")
    publishing = "youtube" in (settings.get("enabled_platforms") or []) and not settings.get("dry_run", True)
    publish_missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET") if publishing and not env.get(k)]
    checks["agent008"] = needs("agent008", publish_missing, "YouTube keys present" if publishing else "not publishing")
    return supervision.startup_check(checks)


BACKUP_DIR = os.path.expanduser("~/breeze_backups")


def daily_backup(supervision, folder=None):
    """app/instance/breeze.db copied once a day to ~/breeze_backups (verified, private files), with app/schemas/settings.json;
    never .env. One extra file only: the socle names them <name>_<day><suffix>, so two .json files would overwrite
    each other (said to the kit, not changed here)."""
    if folder is None:      # the real base to ~/breeze_backups; a test's base next to itself, never in the home
        real = os.path.realpath(supervision.db_path) == os.path.realpath(DB_PATH)
        folder = BACKUP_DIR if real else os.path.join(os.path.dirname(supervision.db_path), "backups")
    extra = [os.path.join(BASE_DIR, "app", "schemas", "settings.json")]
    return supervision.backup_database(folder, "breeze", extra_files=[p for p in extra if os.path.isfile(p)])
