"""
Check the orchestrator's --topic: the real main() of agent000 runs with command-line arguments; the
real agent001 runs with its LLM replaced by a stub (it records the prompt and what LBREEZE_TOPIC
holds, and answers a fixed research); the other agents are mocked (they record LBREEZE_TOPIC too).
Everything read or written (settings, routes, words, reports, rows, breeze.db, breeze.json,
manifest.json, research.json) is in a temporary folder: schemas/ and instance/ are never touched.
  1. --channel breeze_(physics) --topic "Les saisons et l'inclinaison terrestre à 23,5°":
     LBREEZE_TOPIC holds the topic while agent001 runs, not before (agent009), not after (agents
     002-007) and not once main() returns; agent001's prompt says "Le sujet est imposé : <topic>.
     Ne pas en choisir un autre."; research.json records "imposed_topic" = the topic
  2. no --topic: LBREEZE_TOPIC is never set, the prompt lets the LLM choose (as before), research.json
     has no "imposed_topic"
  3. --topic without --channel: refused (one topic suits one channel)
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_orchestrator_topic.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
import app.agent as helpers                                       # noqa: E402
from app import provenance                                        # noqa: E402
from app.agent import agent000_breeze as orchestrator             # noqa: E402
from app.agent import agent001_conceptresearcher as agent001      # noqa: E402

TOPIC = "Les saisons et l'inclinaison terrestre à 23,5°"
CHANNEL = "breeze_(physics)"
ROUTES = [{"channel_id": CHANNEL, "name": "Physique", "domain": "physics", "target_age_band": "15-25",
           "persona": "curieux", "schedule_cron": "0 6 * * *", "enabled": True}]
RESEARCH = {"concept": "Les saisons viennent de l'inclinaison de l'axe terrestre (23,5°), pas de la distance au Soleil.",
            "misconceptions": ["L'été arrive quand la Terre est plus proche du Soleil."], "analogies": [],
            "sources": [{"title": "Saisons", "url": "https://example.org/saisons"},
                        {"title": "Axe", "url": "https://example.org/axe"}],
            "difficulty_assessment": "facile", "why_now": "solstice"}


def run_main(argv):
    """orchestrator.main(argv); returns ({agent: LBREEZE_TOPIC when called}, agent001's prompts,
    research.json or None, LBREEZE_TOPIC after main)."""
    seen, prompts = {}, []
    with tempfile.TemporaryDirectory() as root:
        schemas = os.path.join(root, "schemas")
        os.makedirs(schemas)
        for name, content in (("settings.json", {"render_engine_by_channel": {CHANNEL: "html"}, "max_revisions": 3,
                                                 "dry_run": True}),
                              ("routes.json", ROUTES), ("words.json", {"banned_clickbait": []})):
            with open(os.path.join(schemas, name), "w", encoding="utf-8") as f:
                json.dump(content, f)

        def mocked(name):
            def agent(channel_id, settings, routes):
                seen[name] = os.environ.get(agent001.TOPIC_ENV)
                return {"status": "healthy", "output_path": None, "error": None}
            return agent

        def real_agent001(channel_id, settings, routes):
            seen["agent001"] = os.environ.get(agent001.TOPIC_ENV)
            return agent001.run(channel_id, settings, routes)

        def llm(prompt):
            prompts.append(prompt)
            return json.dumps(RESEARCH, ensure_ascii=False)

        def db_connect():                               # the real tables, in the temporary folder
            saved = helpers.DB_PATH, helpers.INSTANCE_DIR
            helpers.DB_PATH, helpers.INSTANCE_DIR = os.path.join(root, "breeze.db"), root
            try:
                return saved_db_connect()
            finally:
                helpers.DB_PATH, helpers.INSTANCE_DIR = saved

        saved_db_connect = orchestrator.db_connect
        agents = {name: mocked(name) for name in orchestrator.AGENTS}
        agents["agent001"] = real_agent001
        patches = [(orchestrator, {"AGENTS": agents, "SCHEMAS_DIR": schemas, "INSTANCE_DIR": root,
                                   "REPORTS_PATH": os.path.join(root, "reports.json"),
                                   "ROWS_PATH": os.path.join(root, "rows.json"), "db_connect": db_connect,
                                   "log_status": lambda *args, **kwargs: None}),
                   (agent001, {"llm_call": llm, "INSTANCE_DIR": root,
                               "channel_dir": lambda channel_id: os.makedirs(os.path.join(root, channel_id), exist_ok=True)
                               or os.path.join(root, channel_id),
                               "finish": lambda channel_id, agent, stage, status, output_path, data=None, error=None:
                               {"status": status, "output_path": output_path, "error": error}}),
                   (provenance, {"INSTANCE_DIR": root})]
        originals = [(module, {name: getattr(module, name) for name in values}) for module, values in patches]
        run_id, output = helpers.RUN_ID, io.StringIO()
        try:
            for module, values in patches:
                for name, value in values.items():
                    setattr(module, name, value)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                orchestrator.main(argv)
        finally:
            for module, values in originals:
                for name, value in values.items():
                    setattr(module, name, value)
            helpers.RUN_ID = run_id
            os.environ.pop(provenance.RUN_ID_ENV, None)
        after = os.environ.get(agent001.TOPIC_ENV)
        path = os.path.join(root, CHANNEL, "research.json")
        research = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    return seen, prompts, research, after, output.getvalue()


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      {p}" for p in problems))
    return not problems


def case_topic():
    seen, prompts, research, after, output = run_main(["--channel", CHANNEL, "--topic", TOPIC,
                                                       "--skip-agents", "agent008,agent009"])
    problems = []
    if seen.get("agent001") != TOPIC:
        problems.append(f"LBREEZE_TOPIC during agent001: {seen.get('agent001')!r}")
    leaked = {name: value for name, value in seen.items() if name != "agent001" and value is not None}
    if leaked:
        problems.append(f"LBREEZE_TOPIC seen by other agents: {leaked}")
    if after is not None:
        problems.append(f"LBREEZE_TOPIC still set after main(): {after!r}")
    sentence = f"Le sujet est imposé : {TOPIC}. Ne pas en choisir un autre."
    if not prompts or sentence not in prompts[0]:
        problems.append("agent001's prompt does not impose the topic")
    if prompts and "Pick ONE concept" in prompts[0]:
        problems.append("agent001's prompt still lets the LLM choose")
    if (research or {}).get("imposed_topic") != TOPIC:
        problems.append(f"research.json imposed_topic: {(research or {}).get('imposed_topic')!r}")
    return report("--topic: LBREEZE_TOPIC set for agent001 only, prompt imposes it, research.json records it", problems,
                  [f"agents called: {', '.join(sorted(seen))}", f"prompt: {sentence}",
                   f"research.json imposed_topic: {(research or {}).get('imposed_topic')!r}",
                   f"research.json concept: {(research or {}).get('concept')!r}"])


def case_free():
    seen, prompts, research, after, output = run_main(["--channel", CHANNEL, "--skip-agents", "agent008,agent009"])
    problems = []
    if any(value is not None for value in seen.values()) or after is not None:
        problems.append(f"LBREEZE_TOPIC set without --topic: {seen}, after: {after!r}")
    if not prompts or "Pick ONE concept" not in prompts[0] or "Le sujet est imposé" in prompts[0]:
        problems.append("without --topic, the prompt does not let the LLM choose")
    if research is None or "imposed_topic" in research:
        problems.append(f"research.json: {research}")
    return report("no --topic: the LLM chooses freely (unchanged)", problems)


def case_no_channel():
    try:
        run_main(["--topic", TOPIC])
    except SystemExit as exc:
        return report("--topic without --channel: refused", [] if exc.code else ["exited with code 0"])
    return report("--topic without --channel: refused", ["main() ran"])


if os.environ.get(agent001.TOPIC_ENV):
    sys.exit(f"unset {agent001.TOPIC_ENV} in your shell first (it would impose a topic on case 2)")
results = [case_topic(), case_free(), case_no_channel()]
sys.exit(0 if all(results) else 1)
