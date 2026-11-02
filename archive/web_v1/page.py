"""Read-only helpers for the web pages. Everything comes from instance/breeze.db
(written by agent000) plus schemas/routes.json for the channel list. Returns plain dicts."""

import json
import os
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.agent import SCHEMAS_DIR, db_connect, find_route, load_json

AGENT_ORDER = ["agent009", "agent001", "agent002", "agent003", "agent004",
               "agent005", "agent010", "agent007", "agent008"]
AGENT_JOBS = {
    "agent009": "read the analytics",
    "agent001": "researched a concept",
    "agent002": "built the learning outline",
    "agent003": "wrote the narration",
    "agent004": "wrote the visual briefs",
    "agent005": "reviewed the video plan",
    "agent006": "rendered the video (Manim, retired)",
    "agent010": "rendered the video",
    "agent007": "wrote the YouTube metadata",
    "agent008": "published the video",
}
STATUS_PHRASES = {
    "healthy": "finished cleanly",
    "not_healthy": "finished with a warning",
    "critical": "failed",
    "revision_needed": "asked for a revision",
    "not_run": "did not run because an earlier agent failed",
    "skipped": "was skipped on purpose (--skip-agents)",
}


def routes():
    return load_json(os.path.join(SCHEMAS_DIR, "routes.json")) or []


def next_daily_run(cron):
    """Next run time for simple daily crons like "0 9 * * *" (minute hour * * *).
    Anything more complex is shown as the raw cron string. The app never schedules anything itself."""
    parts = cron.split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"] or not (parts[0].isdigit() and parts[1].isdigit()):
        return cron
    now = datetime.now()
    candidate = now.replace(hour=int(parts[1]), minute=int(parts[0]), second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d %H:%M")


def agent_statuses(conn, run_id, channel_id):
    rows = conn.execute("SELECT agent, status FROM reports WHERE run_id = ? AND channel = ?", (run_id, channel_id))
    found = {row["agent"]: row["status"] for row in rows}
    # The render slot is agent010's; older runs rendered by agent006 (Manim, retired) still show it.
    order = [("agent006" if name == "agent010" and "agent006" in found and "agent010" not in found else name)
             for name in AGENT_ORDER]
    return [{"agent": name, "status": found.get(name, "not_run")} for name in order]


def dashboard():
    """One dict per channel in routes.json, whether or not it has run yet."""
    cards = []
    with db_connect() as conn:
        for route in routes():
            channel = conn.execute("SELECT * FROM channels WHERE channel_id = ?", (route["channel_id"],)).fetchone()
            channel = dict(channel) if channel else {}
            cards.append({
                "channel_id": route["channel_id"],
                "name": route["name"],
                "enabled": route.get("enabled", False),
                "overall": channel.get("overall_status", "not_run"),
                "last_topic": channel.get("last_topic"),
                "last_video_url": channel.get("last_video_url"),
                "last_run_at": channel.get("last_run_at"),
                "next_run": next_daily_run(route.get("schedule_cron", "")),
                "agents": agent_statuses(conn, channel.get("last_run_id"), route["channel_id"]) if channel else [],
            })
    return cards


def channel_page(channel_id):
    """Last 10 runs, topics, published videos and QA rejections for one channel. None if unknown."""
    route = find_route(routes(), channel_id)
    if route is None:
        return None
    with db_connect() as conn:
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM runs WHERE channel = ? ORDER BY started_at DESC LIMIT 10", (channel_id,))]
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM rows WHERE channel = ? AND stage IN ('publish', 'qa') ORDER BY timestamp DESC", (channel_id,))]
    for row in rows:
        row["data"] = json.loads(row["data"])
    return {
        "route": route,
        "runs": runs,
        "topics": [r["topic"] for r in runs if r["topic"]],
        "videos": [r for r in rows if r["stage"] == "publish" and r["data"].get("url")],
        "rejections": [r for r in rows if r["stage"] == "qa" and r["data"].get("verdict") == "reject"],
    }


def standup():
    """One plain-English line per agent, per channel, for the most recent run."""
    with db_connect() as conn:
        last = conn.execute("SELECT run_id FROM reports ORDER BY timestamp DESC, id DESC LIMIT 1").fetchone()
        if last is None:
            return {"run_id": None, "lines": []}
        reports = [dict(r) for r in conn.execute(
            "SELECT * FROM reports WHERE run_id = ? ORDER BY id", (last["run_id"],))]
    lines = []
    for report in reports:
        if report["channel"] != "global" and report["agent"] == "agent009":
            continue  # agent009 runs once per cycle: shown once, on its global line
        sentence = (f"{report['agent']} {AGENT_JOBS[report['agent']]} for {report['channel']}: "
                    f"{STATUS_PHRASES.get(report['status'], report['status'])}")
        if report["status"] != "not_run":
            sentence += f" in {report['duration_sec']:.1f}s"
        lines.append({"status": report["status"], "text": sentence, "error": report["error"]})
    return {"run_id": last["run_id"], "lines": lines}
