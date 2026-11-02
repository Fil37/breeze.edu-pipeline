"""
INPUT:  schemas/settings.json, routes.json, words.json, reports.json
OUTPUT: schemas/reports.json (one entry per channel per run), instance/breeze.db, instance/breeze.json
NOTES:  The orchestrator. Calls agent009 once (global), then for each enabled channel agents 001 -> 005,
        agent010 (the HTML renderer: the render step), 007 and 008: nine agents per channel. Never retries
        anything except the agent005 QA revision loop. (agent006, the Manim renderer, is retired: see
        archive/manim/README.md; settings.render_engine_by_channel is no longer read.)
        Never calls an agent outside 001-010. The only writer of reports.json, breeze.db and breeze.json.
        Provenance (app/provenance.py): each channel's run gets its own run id
        ("2026-10-30T16-19-05-electronics"), passed to the agents in the LBREEZE_RUN_ID environment
        variable, and a fresh instance/<channel>/manifest.json (run_id, channel, topic, started_at)
        that each agent fills in as it writes its files. Observation only: nothing is moved.
        QA revisions: after a reject, the agents redone (agent004, or agent003 + agent004) get the
        QA's feedback ({rejection_notes, blocking_issues, revision}) as JSON in the
        LBREEZE_QA_FEEDBACK environment variable, set for that redo only. A reject to agent004 whose
        notes or blocking issues say the renderer cannot show it ("pas représentable", "aucun
        composant", "cannot draw"...: RENDERER_LIMIT) stops the channel at once, agent005
        critical "Renderer limitation: <reason>": redoing agent004 cannot fix it.
        Command line (all optional; without them, every enabled channel and every agent run as before):
          --channel "breeze_(electronics)"   only this channel (run even if routes.json disables it)
          --skip-agents agent008,agent009    never call these agents; they are logged
                                             "<agent>: skipped (--skip-agents)" and get the status
                                             "skipped" in reports.json, breeze.db and breeze.json (not
                                             left out: a missing agent would look like a crash).
          --topic "Les saisons et l'inclinaison terrestre à 23,5°"   impose agent001's topic (needs
                                             --channel): set in LBREEZE_TOPIC for agent001's call only,
                                             then cleared. Without it, agent001's LLM chooses freely.
HEALTH: a critical agent stops its channel; every later agent is recorded as "not_run".
        A critical agent009 does not stop anything (analytics are advisory).
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # `./run` support

import app.agent as helpers
from app.agent import (INSTANCE_DIR, REPORTS_PATH, ROWS_PATH, SCHEMAS_DIR, db_connect,
                       load_json, log_status, save_json, utc_now)
from app.agent import agent001_conceptresearcher, agent002_curriculumsimplifier, agent003_scriptwriter
from app.agent import agent004_visualbriefgenerator, agent005_educationqa
from app.agent import agent007_metadatagenerator, agent008_platformpublisher, agent009_analyticsreader
from app.agent import agent010_html_renderer
from app import provenance

AGENTS = {                                   # in pipeline order: the renderer after the QA
    "agent001": agent001_conceptresearcher.run,
    "agent002": agent002_curriculumsimplifier.run,
    "agent003": agent003_scriptwriter.run,
    "agent004": agent004_visualbriefgenerator.run,
    "agent005": agent005_educationqa.run,
    "agent010": agent010_html_renderer.run,
    "agent007": agent007_metadatagenerator.run,
    "agent008": agent008_platformpublisher.run,
    "agent009": agent009_analyticsreader.run,
}
RENDERER = "agent010"
CONTENT_STEPS = ["agent001", "agent002", "agent003", "agent004"]
TOPIC_ENV = agent001_conceptresearcher.TOPIC_ENV   # "LBREEZE_TOPIC": --topic, for agent001 only
QA_FEEDBACK_ENV = "LBREEZE_QA_FEEDBACK"      # the QA's feedback for the agents redone after a reject
FEEDBACK_TARGETS = ("agent003", "agent004")
# A QA reject agent004 cannot fix: what the QA blocks on is beyond the renderer's components (a closed
# orbit, the Earth and the Sun...). Matched in the rejection notes and the blocking issues, French or
# English. Not "unsupported" alone: the QA lists it even when it passes (the narration then carries it).
RENDERER_LIMIT = re.compile(
    r"(?:pas|non|not)\s+(?:directement\s+|directly\s+)?(?:représentables?|réalisables?|rendables?|dessinables?|representable)"
    r"|(?:non|pas)\s+disponibles?|not\s+available"
    r"|ne\s+peu(?:t|vent)\s+pas\s+(?:être\s+)?(?:dessin|montr|rend|représent|produi|trac)"
    r"|ne\s+dessinen?t?\s+(?:ni|pas)"
    r"|cannot\s+(?:be\s+)?(?:draw|render|represent|show)"
    r"|aucun\s+composant|pas\s+de\s+composant|missing\s+component|no\s+component"
    r"|limit(?:e|ation)\s+du\s+renderer|renderer\s+limitation", re.IGNORECASE)
def call_agent(name, channel_id, settings, routes, run_id, timings):
    """Run one agent, never letting its exception crash the cycle, and record its status."""
    start = time.perf_counter()
    try:
        result = AGENTS[name](channel_id, settings, routes)
    except Exception as exc:
        result = {"status": "critical", "output_path": None, "error": f"crashed: {exc!r}"}
    timings.append({"agent": name, "status": result["status"],
                    "duration_sec": round(time.perf_counter() - start, 3), "error": result.get("error")})
    log_status(run_id, name, result["status"], result.get("error"), channel=channel_id)
    return result


def renderer_limitation(qa):
    """Why a reject to agent004 cannot be fixed by redoing agent004 (see RENDERER_LIMIT), or None."""
    if qa.get("reject_to") != "agent004":
        return None
    texts = [i.get("text", "") for i in qa.get("issues", []) if isinstance(i, dict) and i.get("severity") == "blocking"]
    reason = next((str(t) for t in texts + [qa.get("rejection_notes") or ""] if RENDERER_LIMIT.search(str(t))), None)
    if reason is None:
        return None
    unsupported = [str(u) for u in qa.get("unsupported") or []]
    return reason.strip()[:300] + (f" (unsupported: {'; '.join(unsupported)[:300]})" if unsupported else "")


def qa_feedback(qa, revision):
    """What agent004 (and agent003) get after a QA reject: the notes, and the issues still blocking
    (qa.json "severity", see agent005). Issues in the older plain-text form have no severity: none."""
    return {"rejection_notes": qa.get("rejection_notes", ""),
            "blocking_issues": [i for i in qa.get("issues", []) if isinstance(i, dict) and i.get("severity") == "blocking"],
            "revision": revision}


def youtube_quota_used_today():
    """Units spent today, summed from agent008's publish rows (quota resets daily)."""
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(r["data"].get("quota_used", 0) for r in load_json(ROWS_PATH) or []
               if r.get("stage") == "publish" and r.get("timestamp", "").startswith(today))


def overall_status(statuses):
    """Worst status among the channel's agents (001-005, the renderer agent010, 007, 008);
    agent009 is advisory and left out, and "skipped" (--skip-agents) counts as no problem."""
    values = [s for name, s in statuses.items() if name != "agent009"]
    if "critical" in values:
        return "critical"
    if "not_healthy" in values or "revision_needed" in values:
        return "not_healthy"
    return "healthy"


def run_channel(route, settings, routes, run_id, analytics_status, skip=frozenset(), topic=None):
    channel_id = route["channel_id"]
    started_at, start = utc_now(), time.perf_counter()
    settings = dict(settings, youtube_quota_used_today=youtube_quota_used_today())
    timings = []
    # Provenance: this channel's run id, for every agent below (they read LBREEZE_RUN_ID).
    provenance_run_id = provenance.generate_run_id(channel_id)
    provenance.new_manifest(provenance_run_id, channel_id, topic=None, orchestrator_run_id=run_id)
    os.environ[provenance.RUN_ID_ENV] = provenance_run_id
    delivery_steps = [RENDERER, "agent007", "agent008"]
    statuses = {name: "not_run" for name in AGENTS}          # nine agents per channel, in pipeline order
    statuses.update({name: "skipped" for name in skip if name in statuses})   # skipped even if never reached
    statuses["agent009"] = analytics_status
    for name, status in statuses.items():  # every agent has a status, even if never reached
        log_status(run_id, name, status, channel=channel_id)

    def step(name):
        if name in skip:                           # --skip-agents: not called, recorded as skipped
            statuses[name] = "skipped"
            print(f"  {name}: skipped (--skip-agents)")
            log_status(run_id, name, "skipped", channel=channel_id)
            return True
        if name == "agent001" and topic:           # --topic: in LBREEZE_TOPIC for this call only
            os.environ[TOPIC_ENV] = topic
            print(f"  agent001: imposed topic {topic!r} (--topic)")
        try:
            statuses[name] = call_agent(name, channel_id, settings, routes, run_id, timings)["status"]
        finally:
            if name == "agent001" and topic:
                os.environ.pop(TOPIC_ENV, None)
        if name == "agent001" and statuses[name] != "critical":     # the topic is known now
            provenance.set_topic(channel_id, load_json(os.path.join(INSTANCE_DIR, channel_id, "research.json")).get("concept"))
        return statuses[name] != "critical"

    revisions = 0
    if all(step(name) for name in CONTENT_STEPS):  # all() stops at the first critical
        qa_passed = False
        while True:
            if step("agent005"):
                if statuses["agent005"] != "revision_needed":
                    qa_passed = True
                    break
            else:
                break
            if revisions >= settings.get("max_revisions", 3):
                error = f"still rejected after {revisions} revisions"
                statuses["agent005"] = "critical"
                timings.append({"agent": "agent005", "status": "critical", "duration_sec": 0, "error": error})
                log_status(run_id, "agent005", "critical", error, channel_id)
                break
            qa = load_json(os.path.join(INSTANCE_DIR, channel_id, "qa.json"))
            limit = renderer_limitation(qa)
            if limit:      # agent004 cannot draw it: redoing it would only be rejected again
                error = f"Renderer limitation: {limit}"
                statuses["agent005"] = "critical"
                timings.append({"agent": "agent005", "status": "critical", "duration_sec": 0, "error": error})
                log_status(run_id, "agent005", "critical", error, channel_id)
                print(f"  {channel_id}: stopped, agent004 not redone: {error}")
                break
            revisions += 1
            reject_to = qa.get("reject_to") or "agent003"
            # A new script needs a new storyboard too; a visual fix only needs agent004.
            redo = ["agent003", "agent004"] if reject_to == "agent003" else ["agent004"]
            # The QA's feedback goes to the agents redone, in LBREEZE_QA_FEEDBACK, for this redo only
            # (agent004 never reads qa.json). Only for a reject_to qa.json names explicitly.
            feedback = qa_feedback(qa, revisions) if qa.get("reject_to") in FEEDBACK_TARGETS else None
            sent = (f"feedback transmis ({len(feedback['blocking_issues'])} blocking issues)" if feedback
                    else "no feedback (no explicit reject_to)")
            print(f"  {channel_id}: revision {revisions} -> {' + '.join(redo)}: {sent}")
            log_status(run_id, "agent005", "revision_needed",
                       f"revision {revisions} -> {reject_to}: {sent}: {qa.get('rejection_notes', '')}", channel_id)
            if feedback:
                os.environ[QA_FEEDBACK_ENV] = json.dumps(feedback, ensure_ascii=False)
            try:
                redone = all(step(name) for name in redo)
            finally:
                os.environ.pop(QA_FEEDBACK_ENV, None)
            if not redone:
                break
        if qa_passed:
            all(step(name) for name in delivery_steps)

    duration = round(time.perf_counter() - start, 3)
    finished_at = utc_now()
    overall = overall_status(statuses)

    reports = load_json(REPORTS_PATH) or []
    for entry in reports:
        if entry["run_id"] == run_id and entry["channel"] == channel_id:
            entry["duration_sec"] = duration
    save_json(REPORTS_PATH, reports)

    # Topic and video link of this run, for the dashboard.
    research = load_json(os.path.join(INSTANCE_DIR, channel_id, "research.json"))
    topic = research.get("concept") if statuses["agent001"] in ("healthy", "not_healthy") else None
    run_rows = [r for r in load_json(ROWS_PATH) or [] if r["run_id"] == run_id and r["channel"] == channel_id]
    video_url = next((r["data"]["url"] for r in run_rows if r["stage"] == "publish" and r["data"].get("url")), None)

    with db_connect() as conn:
        conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (run_id, channel_id, started_at, finished_at, duration, overall, topic, revisions))
        for name, status in statuses.items():  # one row per agent: final status, total time, all errors
            calls = [t for t in timings if t["agent"] == name]
            errors = "; ".join(t["error"] for t in calls if t["error"]) or None
            conn.execute("INSERT INTO reports (run_id, channel, agent, status, duration_sec, error, timestamp) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (run_id, channel_id, name, status, round(sum(t["duration_sec"] for t in calls), 3),
                          errors, finished_at))
        save_rows_to_db(conn, run_rows)
        conn.execute("INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (channel_id, route["name"], route["domain"], route["schedule_cron"], 1,
                      run_id, finished_at, overall, topic, video_url))

    state = load_json(os.path.join(INSTANCE_DIR, "breeze.json"))
    os.environ.pop(provenance.RUN_ID_ENV, None)    # the next channel gets its own run id
    state[channel_id] = {"last_run_id": run_id, "finished_at": finished_at, "overall": overall,
                         "agents": statuses, "revisions": revisions, "topic": topic, "video_url": video_url}
    save_json(os.path.join(INSTANCE_DIR, "breeze.json"), state)
    return statuses, overall


def save_rows_to_db(conn, rows):
    for r in rows:
        conn.execute("INSERT INTO rows (run_id, channel, agent, stage, data, timestamp, status) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (r["run_id"], r["channel"], r["agent"], r["stage"],
                      json.dumps(r["data"], ensure_ascii=False), r["timestamp"], r["status"]))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="breeze orchestrator: agent009, then agents 001-008 per channel "
                                                 "(the render step by agent010, the HTML renderer)")
    parser.add_argument("--channel", help='run only this channel, e.g. "breeze_(electronics)" (quote it)')
    parser.add_argument("--skip-agents", default="", metavar="AGENTS",
                        help="comma-separated agents not to call, e.g. agent008,agent009")
    parser.add_argument("--topic", help="impose agent001's topic (needs --channel); sets LBREEZE_TOPIC for agent001")
    args = parser.parse_args(argv)
    args.topic = (args.topic or "").strip() or None
    if args.topic and not args.channel:
        parser.error("--topic needs --channel: one topic suits one channel")
    args.skip = frozenset(name.strip() for name in args.skip_agents.split(",") if name.strip())
    unknown = sorted(args.skip - set(AGENTS))
    if unknown:
        parser.error(f"--skip-agents: unknown agent(s) {unknown} (known: {', '.join(AGENTS)})")
    return args


def main(argv=None):
    args = parse_args(argv)
    settings = load_json(os.path.join(SCHEMAS_DIR, "settings.json"))
    routes = load_json(os.path.join(SCHEMAS_DIR, "routes.json")) or []
    words = load_json(os.path.join(SCHEMAS_DIR, "words.json"))
    load_json(REPORTS_PATH)  # fails loudly here if reports.json is corrupted, before any work
    if not settings or not routes or not words:
        sys.exit("settings.json, routes.json and words.json must exist in schemas/")
    if args.channel and not any(route["channel_id"] == args.channel for route in routes):
        sys.exit(f"--channel: {args.channel!r} is not in routes.json (known: {', '.join(r['channel_id'] for r in routes)})")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    helpers.RUN_ID = run_id
    print(f"breeze run {run_id}  dry_run={settings.get('dry_run')}  provider={settings.get('llm_provider')}"
          + (f"  channel={args.channel}" if args.channel else "") + (f"  skip={','.join(sorted(args.skip))}" if args.skip else "") + (f"  topic={args.topic!r}" if args.topic else ""))

    # 1. Analytics first, once, for every channel. Advisory: a critical result stops nothing.
    timings = []
    if "agent009" in args.skip:
        analytics = {"status": "skipped", "output_path": None, "error": None}
        timings.append({"agent": "agent009", "status": "skipped", "duration_sec": 0, "error": None})
        print("  agent009: skipped (--skip-agents)")
        log_status(run_id, "agent009", "skipped", channel="global")
    else:
        analytics = call_agent("agent009", "global", settings, routes, run_id, timings)
    with db_connect() as conn:
        conn.execute("INSERT INTO reports (run_id, channel, agent, status, duration_sec, error, timestamp) "
                     "VALUES (?, 'global', 'agent009', ?, ?, ?, ?)",
                     (run_id, analytics["status"], timings[0]["duration_sec"], analytics.get("error"), utc_now()))
        save_rows_to_db(conn, [r for r in load_json(ROWS_PATH) or []
                               if r["run_id"] == run_id and r["channel"] == "global"])
    print(f"  agent009 (global): {analytics['status']}")

    # 2. Each enabled channel, one after the other (or only the --channel one, enabled or not).
    for route in routes:
        if args.channel and route["channel_id"] != args.channel:
            continue
        if not route.get("enabled") and not args.channel:
            continue
        statuses, overall = run_channel(route, settings, routes, run_id, analytics["status"], args.skip, args.topic)
        line = " ".join(f"{name[-3:]}:{status}" for name, status in statuses.items())
        print(f"  {route['channel_id']:<22} {overall:<12} {line}")


if __name__ == "__main__":
    main()
