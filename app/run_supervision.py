"""
The supervision of breeze's runs, on the studio kit's socle (app/supervision.py, copied as is):

  store()                       the SupervisionStore on instance/breeze.db (tables llm_calls, agent_health,
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

The costs stay app/costs.py's (instance/costs_history.json): it counts the voice too, which the socle's
LLMClient does not. Nothing here calls a model.
"""

import os
import re

from app.supervision import SupervisionStore

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "instance", "breeze.db")
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


def store(db_path=DB_PATH):
    return SupervisionStore(db_path, secrets=env_secrets())


def error_category(error):
    """The socle's category for an error message of breeze; software_failure when nothing else says."""
    for category, rule in CATEGORY_RULES:
        if rule.search(str(error or "")):
            return category
    return "software_failure"


def supervise(supervision, run_id, channel_id, statuses, errors):
    """After one channel's run. `statuses` {agent: breeze status}, `errors` {agent: its errors, "; "-joined or None}.
    Returns the ids of the incidents opened."""
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
