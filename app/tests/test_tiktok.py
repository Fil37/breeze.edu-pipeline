"""
Check TikTok publishing (app/tiktok.py, agent008), 2026-11-26, the user: "la publication sur tiktok aussi comme avec
auto_clip avec le suivi de la validité des cookies"; one account per channel. Nothing here opens a browser or the
network, nor touches the real instance: cookies, records and the supervision base live in a temporary folder.
  1. the cookies: only TikTok's read; every state (missing, no_session, expired, expiring, ok, rejected, and
     rejected forgotten once the file changes); never a cookie value in what is shown
  2. COOKIE_WATCH: one incident per account needing fresh cookies, not twice, none for a valid or absent file
  3. a publication: refused without cookies or too soon after the last one; posted private with the title and
     hashtags; TikTok asking to log in again remembered as "rejected", the error without any cookie value
  4. agent008: TikTok receives video_vertical.mp4, asks for approval only with usable cookies, publishes the
     approved vertical video only if it is still the one approved
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_tiktok.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
from app import tiktok                                               # noqa: E402
from app.agent import agent008_platformpublisher as a008             # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="breeze_tiktok_"))
tiktok.REJECTIONS = TMP / "tiktok_sessions.json"                     # never the real instance's record
SECRET = "S3cr3tSessionValue_do_not_show"
CHANNEL = "breeze_(electronics)"


def report(label, problems, notes=()):
    print(("PASS" if not problems else "FAIL") + f"  {label}")
    for line in list(problems) + list(notes):
        print(f"        - {line}")
    return not problems


def cookies(name, session=True, days=60, extra=True):
    path = TMP / name
    end = int(time.time() + days * 86400)
    lines = ["# Netscape HTTP Cookie File"]
    if session:
        lines.append(f"#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t{end}\tsessionid\t{SECRET}")
        lines.append(f".tiktok.com\tTRUE\t/\tTRUE\t{end + 86400 * 30}\tsid_tt\t{SECRET}2")
    if extra:
        lines.append(f".google.com\tTRUE\t/\tTRUE\t{end}\tNID\tgoogle_value_never_loaded")
        lines.append(f".tiktok.com\tTRUE\t/\tFALSE\t{end}\ttt_csrf_token\tabc")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def settings_for(path, **more):
    return {"enabled_platforms": ["youtube", "tiktok"], "dry_run": False,
            "tiktok": {"accounts_by_channel": {CHANNEL: {"label": "breeze électronique", "cookies_path": str(path)}},
                       "warn_days": 7, "min_gap_hours": 20, "visibility": "private", **more}}


def case_cookies():
    problems = []
    loaded = tiktok.load_cookies(cookies("c1.txt"))
    if sorted(c["name"] for c in loaded) != ["sessionid", "sid_tt", "tt_csrf_token"]:
        problems.append(f"not only TikTok's cookies loaded: {[c['name'] for c in loaded]}")
    if not next(c for c in loaded if c["name"] == "sessionid")["httpOnly"]:
        problems.append("a #HttpOnly_ line not read as an http-only cookie")
    states = {
        "missing": tiktok.cookie_status(CHANNEL, TMP / "none.txt", rejected={}),
        "no_session": tiktok.cookie_status(CHANNEL, cookies("c2.txt", session=False), rejected={}),
        "expired": tiktok.cookie_status(CHANNEL, cookies("c3.txt", days=-1), rejected={}),
        "expiring": tiktok.cookie_status(CHANNEL, cookies("c4.txt", days=3), rejected={}),
        "ok": tiktok.cookie_status(CHANNEL, cookies("c5.txt", days=60), rejected={}),
    }
    for want, got in states.items():
        if got["state"] != want:
            problems.append(f"{want}: read as {got['state']} ({got['text']})")
    if states["ok"]["days_left"] not in (59, 60):
        problems.append(f"days left of a 60-day session: {states['ok']['days_left']}")
    path = cookies("c6.txt")
    rejected = {CHANNEL: {"cookies_mtime": path.stat().st_mtime}}
    if tiktok.cookie_status(CHANNEL, path, rejected=rejected)["state"] != "rejected":
        problems.append("cookies refused by TikTok not shown as rejected")
    os.utime(path, (time.time() + 5, time.time() + 5))               # fresh cookies exported over the file
    if tiktok.cookie_status(CHANNEL, path, rejected=rejected)["state"] != "ok":
        problems.append("a new cookies file still shown as rejected")
    if any(SECRET in str(s) for s in states.values()) or SECRET in str(tiktok.accounts(settings_for(path))):
        problems.append("a cookie value shown")
    return report("1. the cookies: TikTok's only, every state, never a value shown", problems)


def case_watch():
    from app import run_supervision
    problems = []
    store = run_supervision.store(str(TMP / "watch.db"))
    expiring = cookies("w1.txt", days=2)
    settings = settings_for(expiring)
    settings["tiktok"]["accounts_by_channel"]["breeze_(math)"] = {"label": "maths", "cookies_path": str(cookies("w2.txt"))}
    settings["tiktok"]["accounts_by_channel"]["breeze_(physics)"] = {"label": "physique", "cookies_path": str(TMP / "none.txt")}
    tiktok.check_accounts(store, settings, rejected={})
    tiktok.check_accounts(store, settings, rejected={})                 # the next start: not opened twice
    with store.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT agent_id, error_category, diagnostic FROM incidents WHERE status='open'")]
    if len(rows) != 1 or "électronique" not in rows[0]["diagnostic"] or rows[0]["agent_id"] != "agent008":
        problems.append(f"expected one incident for the expiring account only: {rows}")
    if any(SECRET in r["diagnostic"] for r in rows):
        problems.append("a cookie value in an incident")
    if tiktok.check_accounts(store, {**settings, "enabled_platforms": ["youtube"]}, rejected={}):
        problems.append("checked although TikTok is not enabled")
    return report("2. COOKIE_WATCH: one incident per account to renew, never twice, none for valid or absent", problems)


def case_publish():
    problems, sent = [], []
    metadata = {"title": "AOP : suiveur, inverseur", "tags": ["AOP", "amplificateur opérationnel", "AOP"]}
    video = TMP / "video_vertical.mp4"
    video.write_bytes(b"x" * 4096)

    def uploader(path, text, loaded, visibility, headless):
        sent.append({"path": str(path), "text": text, "visibility": visibility, "names": [c["name"] for c in loaded]})

    status, error, _ = tiktok.publish(CHANNEL, settings_for(TMP / "none.txt"), video, metadata, uploader=uploader)
    if status == "healthy" or sent:
        problems.append(f"published without cookies: {status} {error}")
    good = cookies("p1.txt")
    status, error, details = tiktok.publish(CHANNEL, settings_for(good), video, metadata, uploader=uploader)
    if status != "healthy" or len(sent) != 1:
        problems.append(f"not published with valid cookies: {status} {error}")
    elif sent[0]["visibility"] != "private" or sent[0]["text"] != "AOP : suiveur, inverseur\n\n#AOP #amplificateuropérationnel":
        problems.append(f"post not private or wrong text: {sent[0]}")
    status, error, _ = tiktok.publish(CHANNEL, settings_for(good), video, metadata, uploader=uploader)
    if status == "healthy" or "RATE_LIMITED" not in str(error) or len(sent) != 1:
        problems.append(f"a second post the same day not refused: {status} {error}")
    tiktok.REJECTIONS.unlink()

    def refused(*args):
        raise tiktok.PublishError("COOKIES_EXPIRED", f"login page with sessionid={SECRET}")
    status, error, _ = tiktok.publish(CHANNEL, settings_for(good), video, metadata, uploader=refused)
    if status != "critical" or not str(error).startswith("COOKIES_EXPIRED") or SECRET in str(error):
        problems.append(f"an expired session not reported cleanly: {status} {error}")
    if tiktok.cookie_status(CHANNEL, good)["state"] != "rejected":
        problems.append("TikTok's refusal not remembered: the cookies still shown valid")
    return report("3. a publication: refused without cookies or too soon, private with hashtags, a refusal remembered",
                  problems)


def case_agent008():
    problems, asked, uploaded = [], [], []
    folder = TMP / CHANNEL
    folder.mkdir(exist_ok=True)
    (folder / "video.mp4").write_bytes(b"h" * 4096)
    (folder / "video_vertical.mp4").write_bytes(b"v" * 4096)
    (folder / "metadata.json").write_text('{"title": "AOP"}', encoding="utf-8")
    a008.channel_dir, a008.request_publication = (lambda channel: str(folder)), \
        (lambda channel, platform, path, metadata: asked.append((platform, os.path.basename(path))) or 7)
    if a008.VIDEO_FILE.get("tiktok") != "video_vertical.mp4":
        problems.append(f"TikTok does not receive the vertical video: {a008.VIDEO_FILE}")
    publication = {}
    status, error = a008.publish_one(CHANNEL, "tiktok", settings_for(TMP / "none.txt"), str(folder / "video_vertical.mp4"),
                                     {"title": "AOP"}, publication)
    if asked or "no cookies" not in str(error):
        problems.append(f"an approval asked without cookies: {asked} {error}")
    settings = settings_for(cookies("a1.txt"))
    status, error = a008.publish_one(CHANNEL, "tiktok", settings, str(folder / "video_vertical.mp4"), {"title": "AOP"}, {})
    if asked != [("tiktok", "video_vertical.mp4")] or "approval #7" not in str(error):
        problems.append(f"no approval asked for the vertical video: {asked} {error}")
    parameters = {"video_sha256": a008.sha256(str(folder / "video_vertical.mp4")),
                  "metadata_sha256": a008.sha256(str(folder / "metadata.json")), "run_id": "r1"}
    a008.append_row = lambda row: None                                  # never the real rows.json

    def upload(channel, platform, settings_, path, metadata, publication_):
        uploaded.append(os.path.basename(path))
        return "healthy", None
    outcome = a008.publish_approved(f"{CHANNEL}:tiktok", parameters, settings, upload)
    if not outcome["applied"] or uploaded != ["video_vertical.mp4"]:
        problems.append(f"the approved vertical video not published: {outcome} {uploaded}")
    (folder / "video_vertical.mp4").write_bytes(b"w" * 4096)           # rendered again after the approval
    outcome = a008.publish_approved(f"{CHANNEL}:tiktok", parameters, settings, upload)
    if outcome["applied"] or len(uploaded) != 1:
        problems.append(f"a vertical video changed since the approval was published: {outcome}")
    return report("4. agent008: the vertical video to TikTok, approval only with usable cookies, sha256 checked", problems)


if __name__ == "__main__":
    results = [case_cookies(), case_watch(), case_publish(), case_agent008()]
    sys.exit(0 if all(results) else 1)
