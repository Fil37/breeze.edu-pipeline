"""
INPUT:  app/instance/{channel_id}/video.mp4 + metadata.json + subtitles.srt (agent010; optional)
        + app/schemas/routes.json (publish_platforms)
        + settings (dry_run, enabled_platforms, publisher, youtube_quota_limit,
        youtube_quota_used_today: injected by the orchestrator)
OUTPUT: one row per platform appended to app/schemas/rows.json, stage "publish",
        data = {platform, video_id, url, publish_timestamp, quota_used}
NOTES:  The ONLY agent that touches platform APIs. Only YouTube is wired at launch.
        A publication is a sensitive action (2026-11-20): the run only asks for it (the socle's request_approval,
        target "<channel>:<platform>", parameters: the video, its and the metadata's sha256, the title, private);
        it is uploaded when the user approves it on the standup, by publish_approved() given to decide(), and only
        if the video and the metadata are still the ones approved. Without that handler nothing is uploaded.
        Uploads go out as "private" so a human reviews them before they go public.
        On YouTube (direct), the subtitles go up as the video's French captions (captions.insert,
        400 units; the refresh token needs the youtube.force-ssl scope). A caption upload that fails
        leaves the video published: not_healthy, with the reason.
        With publisher "uploadpost" the upload goes through Upload-Post instead of the YouTube API.
HEALTH: not_healthy if dry_run, a platform is disabled, there is no real video to upload, or the
        captions did not go up;
        critical if metadata is missing, a key is missing, the YouTube quota is exhausted, or an API call fails.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

import app.agent as helpers  # helpers.RUN_ID is read at call time (set by the orchestrator)
from app.agent import (ROWS_PATH, append_row, channel_dir, find_route, load_json,
                       require_env, run_standalone, utc_now)
from app import provenance

AGENT = "agent008"
# What this agent can do (the studio kit's skills, registered by agent000 at start: "proposed" until the
# user approves their activation on the standup).
SKILLS = [
    {"skill_id": "platform_publish", "version": "1.0", "objective": "Upload the video, private, to the channel's platforms",
     "summary": "Since 2026-11-20 a publication waits for the user's approval on the standup."},
]
UPLOAD_COST = 1600  # YouTube Data API units for one videos.insert
CAPTION_COST = 400  # ... and for one captions.insert
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


def upload_captions(channel_id, video_id, srt_path):
    """The subtitles as the video's French captions (one multipart request: the caption's snippet, then
    the SubRip file)."""
    import requests
    boundary = "breeze-captions"
    snippet = {"snippet": {"videoId": video_id, "language": "fr", "name": "Français", "isDraft": False}}
    with open(srt_path, "rb") as f:
        srt = f.read()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(snippet)}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + srt + f"\r\n--{boundary}--\r\n".encode()
    response = requests.post("https://www.googleapis.com/upload/youtube/v3/captions?uploadType=multipart&part=snippet",
                             headers={"Authorization": "Bearer " + youtube_access_token(channel_id),
                                      "Content-Type": f"multipart/related; boundary={boundary}"},
                             data=body, timeout=120)
    response.raise_for_status()


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

    if not publication.get("approved"):             # the run asks; the user's approval uploads (publish_approved)
        approval = request_publication(channel_id, platform, video_path, metadata)
        publication["approval_id"] = approval
        return "not_healthy", (f"waiting for the user's approval #{approval} on the standup: nothing uploaded" if approval
                               else "already waiting for the user's approval on the standup: nothing uploaded")

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
    srt_path = os.path.join(os.path.dirname(video_path), "subtitles.srt")
    if uses_uploadpost or not os.path.isfile(srt_path):
        return "healthy", None
    if quota_used_today + UPLOAD_COST + CAPTION_COST > settings.get("youtube_quota_limit", 10000):
        return "not_healthy", "captions not uploaded: YouTube quota exhausted"
    try:
        upload_captions(channel_id, video_id, srt_path)
        publication["quota_used"] += CAPTION_COST
        publication["captions"] = True
    except Exception as exc:
        return "not_healthy", f"captions not uploaded (the token needs the youtube.force-ssl scope): {exc}"
    return "healthy", None


def sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def request_publication(channel_id, platform, video_path, metadata):
    """The approval this publication waits for (the socle's request_approval), or None when the same one is already
    pending. Its parameters say exactly what would go up."""
    from app import run_supervision
    folder = os.path.dirname(video_path)
    return run_supervision.store().request_approval("publish_video", f"{channel_id}:{platform}", {
        "run_id": helpers.RUN_ID, "video": os.path.relpath(video_path, os.path.dirname(os.path.dirname(folder))),
        "video_sha256": sha256(video_path), "metadata_sha256": sha256(os.path.join(folder, "metadata.json")),
        "title": metadata.get("title"), "privacy": "private"})


def publish_approved(target, parameters, settings=None, upload=None):
    """The handler of "publish_video" for the socle's decide(): uploads the approved video, if it and its metadata
    are still the ones approved (sha256), with the settings of the moment (dry_run, enabled platforms, quota).
    `upload` replaces publish_one in tests. Returns the outcome stored with the approval."""
    channel_id, _, platform = target.rpartition(":")
    folder = channel_dir(channel_id)
    video_path, metadata_path = os.path.join(folder, "video.mp4"), os.path.join(folder, "metadata.json")
    if not os.path.isfile(video_path) or sha256(video_path) != parameters.get("video_sha256"):
        return {"applied": False, "reason": "the video changed since the request: nothing uploaded"}
    if not os.path.isfile(metadata_path) or sha256(metadata_path) != parameters.get("metadata_sha256"):
        return {"applied": False, "reason": "the metadata changed since the request: nothing uploaded"}
    settings = settings or load_json(os.path.join(helpers.SCHEMAS_DIR, "settings.json")) or {}
    helpers.RUN_ID = parameters.get("run_id") or helpers.RUN_ID
    publication = {"platform": platform, "video_id": None, "url": None, "publish_timestamp": None, "quota_used": 0,
                   "approved": True}
    status, error = (upload or publish_one)(channel_id, platform, settings, video_path, load_json(metadata_path), publication)
    append_row({"run_id": helpers.RUN_ID, "channel": channel_id, "agent": AGENT, "stage": "publish",
                "data": {**publication, **({"error": error} if error else {})}, "timestamp": utc_now(), "status": status})
    return {"applied": status == "healthy", "status": status, "url": publication.get("url"), "error": error}


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
