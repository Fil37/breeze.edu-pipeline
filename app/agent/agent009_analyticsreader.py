"""
INPUT:  schemas/rows.json (stage "publish" rows = published videos, stage "research" rows = topics)
        + YouTube Data / Analytics APIs (read-only, skipped when settings.dry_run=true)
OUTPUT: instance/analytics.json = {by_channel:{channel_id:{views, retention, ctr, revenue_estimate}},
        top_topics[], saturated_topics[]}
NOTES:  Global (not per-channel); runs FIRST in every orchestrator cycle and feeds agent001.
        Read-only on platform APIs, never publishes. Always writes valid JSON, even with 0 videos.
HEALTH: not_healthy if fewer than 3 published videos;
        critical if a platform API read fails.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import INSTANCE_DIR, ROWS_PATH, finish, load_json, require_env, run_standalone, save_json

AGENT = "agent009"
ESTIMATED_RPM = 1.0  # rough revenue per 1000 views, a placeholder to tune with real payouts
SATURATION_COUNT = 2  # a concept published this many times (any channel) is saturated
TOP_TOPICS = 5


def youtube_access_token(channel_id):
    import requests
    token_name = "YOUTUBE_REFRESH_TOKEN_" + channel_id.replace("(", "").replace(")", "").upper()
    response = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": require_env("YOUTUBE_CLIENT_ID"),
        "client_secret": require_env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": require_env(token_name),
        "grant_type": "refresh_token",
    })
    response.raise_for_status()
    return response.json()["access_token"]


def read_video_stats(channel_id, video_id):
    """Return (views, retention %) for one video. Read-only GET calls."""
    import requests
    headers = {"Authorization": "Bearer " + youtube_access_token(channel_id)}
    stats = requests.get("https://www.googleapis.com/youtube/v3/videos", headers=headers, timeout=30,
                         params={"part": "statistics", "id": video_id})
    stats.raise_for_status()
    items = stats.json().get("items", [])
    views = int(items[0]["statistics"].get("viewCount", 0)) if items else 0
    report = requests.get("https://youtubeanalytics.googleapis.com/v2/reports", headers=headers, timeout=30,
                          params={"ids": "channel==MINE", "startDate": "2020-01-01",
                                  "endDate": date.today().isoformat(),
                                  "metrics": "averageViewPercentage", "filters": f"video=={video_id}"})
    report.raise_for_status()
    rows = report.json().get("rows") or [[0]]
    return views, float(rows[0][0])


def run(channel_id: str, settings: dict, routes: list) -> dict:
    output_path = os.path.join(INSTANCE_DIR, "analytics.json")
    rows = load_json(ROWS_PATH) or []

    # Topic of each channel run, from agent001's research rows.
    topics = {(r["run_id"], r["channel"]): r["data"].get("concept")
              for r in rows if r.get("stage") == "research" and r["data"].get("concept")}
    published = [r for r in rows if r.get("stage") == "publish" and r.get("status") == "healthy"
                 and r["data"].get("url")]

    by_channel = {route["channel_id"]: {"views": 0, "retention": 0.0, "ctr": 0.0, "revenue_estimate": 0.0}
                  for route in routes}
    views_by_topic, publish_count_by_topic, retentions = {}, {}, {}
    error = None
    for row in published:
        channel = row["channel"]
        topic = topics.get((row["run_id"], channel), "unknown")
        publish_count_by_topic[topic] = publish_count_by_topic.get(topic, 0) + 1
        views, retention = 0, 0.0
        if not settings.get("dry_run", True) and row["data"]["platform"] == "youtube":
            try:
                views, retention = read_video_stats(channel, row["data"]["video_id"])
            except Exception as exc:
                error = f"YouTube read failed for {row['data']['video_id']}: {exc}"
                break
        metrics = by_channel.setdefault(channel, {"views": 0, "retention": 0.0, "ctr": 0.0, "revenue_estimate": 0.0})
        metrics["views"] += views
        metrics["revenue_estimate"] = round(metrics["views"] / 1000 * ESTIMATED_RPM, 2)
        retentions.setdefault(channel, []).append(retention)
        views_by_topic[topic] = views_by_topic.get(topic, 0) + views
        # TODO: ctr needs impression data from YouTube Analytics; it stays 0.0 until wired.

    for channel, values in retentions.items():
        by_channel[channel]["retention"] = round(sum(values) / len(values), 2)

    analytics = {
        "by_channel": by_channel,
        "top_topics": [t for t, v in sorted(views_by_topic.items(), key=lambda kv: -kv[1]) if v > 0][:TOP_TOPICS],
        "saturated_topics": sorted(t for t, n in publish_count_by_topic.items() if n >= SATURATION_COUNT),
    }
    save_json(output_path, analytics)  # written even on errors, so agent001 always has valid input

    if error:
        status = "critical"
    else:
        status = "healthy" if len(published) >= 3 else "not_healthy"
    return finish("global", AGENT, "analytics", status, output_path,
                  data={"published_videos": len(published), "saturated_topics": analytics["saturated_topics"]},
                  error=error)


if __name__ == "__main__":
    run_standalone(run)
