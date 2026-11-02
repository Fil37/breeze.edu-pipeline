"""Read-only helpers for the web pages. The runs come from instance/breeze.db (written by agent000),
the channel list from schemas/routes.json, and the last video of each channel from its files in
instance/<channel_id>/ (render_manifest.json, metadata.json, qa.json, research.json). Nothing is
written. Returns plain dicts."""

import json
import os
import re
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.agent import INSTANCE_DIR, SCHEMAS_DIR, db_connect, find_route, load_json
from app.agent.agent010_html_renderer import channel_style

AGENT_ORDER = ["agent009", "agent001", "agent002", "agent003", "agent004",
               "agent005", "agent010", "agent007", "agent008"]
AGENT_NAMES = {
    "agent009": "Statistiques", "agent001": "Recherche", "agent002": "Plan pédagogique", "agent003": "Script",
    "agent004": "Storyboard", "agent005": "Contrôle QA", "agent006": "Rendu (Manim)", "agent010": "Rendu",
    "agent007": "Métadonnées", "agent008": "Publication",
}
AGENT_JOBS = {
    "agent009": "lecture des statistiques",
    "agent001": "recherche d'un concept",
    "agent002": "plan pédagogique",
    "agent003": "écriture de la narration",
    "agent004": "storyboard",
    "agent005": "contrôle qualité",
    "agent006": "rendu de la vidéo (Manim, retiré)",
    "agent010": "rendu de la vidéo",
    "agent007": "métadonnées YouTube",
    "agent008": "publication",
}
STATUS_LABELS = {
    "healthy": "OK", "not_healthy": "avertissement", "critical": "échec", "revision_needed": "révision",
    "not_run": "non lancé", "skipped": "ignoré",
}
STATUS_PHRASES = {
    "healthy": "terminé sans problème",
    "not_healthy": "terminé avec un avertissement",
    "critical": "en échec",
    "revision_needed": "révision demandée",
    "not_run": "non lancé (un agent précédent a échoué)",
    "skipped": "ignoré volontairement (--skip-agents)",
}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def routes():
    return load_json(os.path.join(SCHEMAS_DIR, "routes.json")) or []


def channel_theme(channel_id):
    """The colours of the channel's video theme (agent010), for its card and page."""
    style = channel_style(channel_id)
    tokens = style.get("tokens", {})
    accent = tokens.get("accent") if HEX.match(str(tokens.get("accent", ""))) else "#3B82F6"
    return {"name": style.get("name") or "notebook", "accent": accent}


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
    return [{"agent": name, "name": AGENT_NAMES.get(name, name), "status": found.get(name, "not_run")} for name in order]


def video_path(channel_id):
    """instance/<channel_id>/video.mp4 for a channel of routes.json, if it exists; else None."""
    if find_route(routes(), channel_id) is None:
        return None
    path = os.path.join(INSTANCE_DIR, channel_id, "video.mp4")
    return path if os.path.isfile(path) else None


def latest(channel_id):
    """What the channel's folder holds of its last video: the video, its scenes (the plan included),
    its YouTube title and chapters, the QA's verdict. Missing files give empty values."""
    folder = os.path.join(INSTANCE_DIR, channel_id)
    read = lambda name: load_json(os.path.join(folder, name)) if os.path.isdir(folder) else {}
    manifest, metadata, qa, research, storyboard = (read(n) for n in ("render_manifest.json", "metadata.json", "qa.json",
                                                                        "research.json", "storyboard.json"))
    path = video_path(channel_id)
    titles = {str(s.get("scene_id")): ((s.get("visual_brief") or {}).get("text_overlay") or {}).get("title")
              for s in storyboard.get("scenes", [])}           # for videos rendered before the manifest kept them
    scenes = [{"scene_id": s.get("scene_id"),
               "title": s.get("title") or titles.get(str(s.get("scene_id"))) or f"Scène {s.get('scene_id')}",
               "plan": s.get("scene_id") == "plan", "start": s.get("start_sec"), "duration": s.get("duration_sec"),
               "voice": s.get("voice_engine"), "status": s.get("status"), "conflicts": len(s.get("layout_conflicts") or [])}
              for s in manifest.get("scenes", [])]
    issues = [{"scene_id": i.get("scene_id"), "text": i.get("text"), "severity": i.get("severity")}
              for i in qa.get("issues", []) if isinstance(i, dict)]
    return {
        "video": bool(path),
        "rendered_at": (manifest.get("rendered_at") or "")[:16].replace("T", " "),
        "duration": manifest.get("duration"),
        "voice_engine": manifest.get("voice_engine"),
        "render_status": manifest.get("status"),
        "scenes": scenes,
        "title": metadata.get("title"),
        "chapters": [{"time": c.split(" ", 1)[0], "seconds": seconds(c.split(" ", 1)[0]), "title": c.split(" ", 1)[-1]}
                     for c in metadata.get("chapters", []) if isinstance(c, str) and " " in c],
        "concept": research.get("concept"),
        "qa": {"verdict": qa.get("verdict"), "scores": qa.get("scores") or {}, "issues": issues,
               "corrected": qa.get("corrected_count", 0), "blocking": qa.get("blocking_count", 0)} if qa else None,
    }


def seconds(timestamp):
    """"1:05" -> 65; anything else -> None."""
    match = re.fullmatch(r"(\d+):(\d{2})", timestamp)
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


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
                "theme": channel_theme(route["channel_id"]),
                "overall": channel.get("overall_status", "not_run"),
                "last_topic": channel.get("last_topic"),
                "last_video_url": channel.get("last_video_url"),
                "last_run_at": (channel.get("last_run_at") or "")[:16].replace("T", " ") or None,
                "next_run": next_daily_run(route.get("schedule_cron", "")),
                "agents": agent_statuses(conn, channel.get("last_run_id"), route["channel_id"]) if channel else [],
                "latest": latest(route["channel_id"]),
            })
    return cards


def channel_page(channel_id):
    """The last video, the last 10 runs, topics, published videos and QA rejections for one channel.
    None if the channel is not in routes.json."""
    route = find_route(routes(), channel_id)
    if route is None:
        return None
    with db_connect() as conn:
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM runs WHERE channel = ? ORDER BY started_at DESC LIMIT 10", (channel_id,))]
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM rows WHERE channel = ? AND stage IN ('publish', 'qa') ORDER BY timestamp DESC", (channel_id,))]
        last_run = runs[0]["run_id"] if runs else None
        agents = agent_statuses(conn, last_run, channel_id) if last_run else []
    for row in rows:
        row["data"] = json.loads(row["data"])
    return {
        "route": route,
        "theme": channel_theme(channel_id),
        "latest": latest(channel_id),
        "agents": agents,
        "runs": runs,
        "topics": list(dict.fromkeys(r["topic"] for r in runs if r["topic"])),
        "videos": [r for r in rows if r["stage"] == "publish" and r["data"].get("url")],
        "rejections": [r for r in rows if r["stage"] == "qa" and r["data"].get("verdict") == "reject"],
    }


def standup():
    """One line per agent, per channel, for the most recent run (French)."""
    with db_connect() as conn:
        last = conn.execute("SELECT run_id FROM reports ORDER BY timestamp DESC, id DESC LIMIT 1").fetchone()
        if last is None:
            return {"run_id": None, "groups": []}
        reports = [dict(r) for r in conn.execute(
            "SELECT * FROM reports WHERE run_id = ? ORDER BY id", (last["run_id"],))]
    groups = {}
    for report in reports:
        if report["channel"] != "global" and report["agent"] == "agent009":
            continue  # agent009 runs once per cycle: shown once, on its global line
        sentence = (f"{report['agent']} · {AGENT_JOBS.get(report['agent'], report['agent'])} : "
                    f"{STATUS_PHRASES.get(report['status'], report['status'])}")
        if report["status"] not in ("not_run", "skipped") and report["duration_sec"] is not None:
            sentence += f", en {report['duration_sec']:.1f} s"
        groups.setdefault(report["channel"], []).append(
            {"agent": report["agent"], "status": report["status"], "text": sentence, "error": report["error"]})
    names = {r["channel_id"]: r["name"] for r in routes()}
    return {"run_id": last["run_id"],
            "groups": [{"channel_id": channel, "name": names.get(channel, "Global" if channel == "global" else channel),
                        "theme": channel_theme(channel), "lines": lines} for channel, lines in groups.items()]}
