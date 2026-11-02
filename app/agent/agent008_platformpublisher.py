"""
INPUT:  instance/{channel_id}/video.mp4 + metadata.json + schemas/routes.json (publish_platforms)
        + settings (dry_run, enabled_platforms, publisher, youtube_quota_limit,
        youtube_quota_used_today: injected by the orchestrator)
OUTPUT: one row per platform appended to schemas/rows.json, stage "publish",
        data = {platform, video_id, url, publish_timestamp, quota_used}
NOTES:  The ONLY agent that touches platform APIs. Only YouTube is wired at launch.
        Uploads go out as "private" so a human reviews them before they go public.
        With publisher "uploadpost" the upload goes through Upload-Post instead of the YouTube API.
HEALTH: not_healthy if dry_run, a platform is disabled, or there is no real video to upload;
        critical if metadata is missing, a key is missing, the YouTube quota is exhausted, or an API call fails.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

import app.agent as helpers  # helpers.RUN_ID is read at call time (set by the orchestrator)
from app.agent import (ROWS_PATH, append_row, channel_dir, find_route, load_json,
                       require_env, run_standalone, utc_now)
from app import provenance

AGENT = "agent008"
UPLOAD_COST = 1600  # YouTube Data API units for one videos.insert
MIN_VIDEO_BYTES = 1024  # anything smaller is a dry-run placeholder, never uploaded
SEVERITY = {"healthy": 0, "not_healthy": 1, "critical": 2}


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


def upload_to_youtube(channel_id, video_path, metadata):
    """Resumable upload: 1) send metadata, get an upload URL, 2) PUT the video bytes."""
    import requests
    headers = {"Authorization": "Bearer " + youtube_access_token(channel_id)}
    body = {
        "snippet": {"title": metadata["title"], "description": metadata["description"],
                    "tags": metadata.get("tags", []), "categoryId": "27"},  # 27 = Education
        # TODO: review "made for kids" (COPPA) for channels whose age band starts under 13.
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }
    start = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={**headers, "X-Upload-Content-Type": "video/mp4"}, json=body, timeout=30)
    start.raise_for_status()
    with open(video_path, "rb") as f:
        upload = requests.put(start.headers["Location"], headers={**headers, "Content-Type": "video/mp4"},
                              data=f, timeout=1800)
    upload.raise_for_status()
    video_id = upload.json()["id"]
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def upload_via_uploadpost(channel_id, platform, video_path, metadata):
    # Field names follow Upload-Post's public docs at the time of writing: check them before going live.
    import requests
    with open(video_path, "rb") as f:
        response = requests.post(
            "https://api.upload-post.com/api/upload",
            headers={"Authorization": "Apikey " + require_env("UPLOADPOST_API_KEY")},
            data={"user": channel_id, "title": metadata["title"], "platform[]": [platform]},
            files={"video": f}, timeout=1800)
    response.raise_for_status()
    answer = response.json()
    return answer.get("video_id"), answer.get("url")


def publish_one(channel_id, platform, settings, video_path, metadata, publication):
    """Fill `publication` in place and return (status, error)."""
    if platform not in settings.get("enabled_platforms", []):
        return "not_healthy", f"{platform} is disabled"
    if settings.get("dry_run", True):
        return "not_healthy", "dry_run: nothing uploaded"
    if not os.path.exists(video_path) or os.path.getsize(video_path) < MIN_VIDEO_BYTES:
        return "not_healthy", "no real video to upload"
    if platform != "youtube":
        return "not_healthy", f"{platform} publishing is not wired yet"

    uses_uploadpost = settings.get("publisher") == "uploadpost"
    quota_used_today = settings.get("youtube_quota_used_today", 0)
    if not uses_uploadpost and quota_used_today + UPLOAD_COST > settings.get("youtube_quota_limit", 10000):
        return "critical", f"YouTube quota exhausted ({quota_used_today} units used today)"
    try:
        if uses_uploadpost:
            video_id, url = upload_via_uploadpost(channel_id, platform, video_path, metadata)
        else:
            video_id, url = upload_to_youtube(channel_id, video_path, metadata)
            publication["quota_used"] = UPLOAD_COST  # Upload-Post spends its own quota, not ours
    except Exception as exc:
        return "critical", f"{platform} upload failed: {exc}"
    publication.update(video_id=video_id, url=url, publish_timestamp=utc_now())
    return "healthy", None


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    video_path = os.path.join(folder, "video.mp4")
    provenance.check_inputs(channel_id, AGENT, ["video.mp4", "metadata.json"])   # writes nothing in the folder
    metadata = load_json(os.path.join(folder, "metadata.json"))
    route = find_route(routes, channel_id)
    if not metadata or route is None:
        return {"status": "critical", "output_path": ROWS_PATH, "error": "missing metadata.json or channel route"}

    worst_status, errors = "healthy", []
    for platform in route.get("publish_platforms", []):
        publication = {"platform": platform, "video_id": None, "url": None,
                       "publish_timestamp": None, "quota_used": 0}
        status, error = publish_one(channel_id, platform, settings, video_path, metadata, publication)
        if error:
            publication["error"] = error
            errors.append(error)
        append_row({"run_id": helpers.RUN_ID, "channel": channel_id, "agent": AGENT, "stage": "publish",
                    "data": publication, "timestamp": utc_now(), "status": status})
        if SEVERITY[status] > SEVERITY[worst_status]:
            worst_status = status
    return {"status": worst_status, "output_path": ROWS_PATH, "error": "; ".join(errors) or None}


if __name__ == "__main__":
    run_standalone(run)
