"""
TikTok for L_breeze (2026-11-26, the user: "la publication sur tiktok aussi comme avec auto_clip avec le suivi de la
validité des cookies"): one TikTok account per channel (the user's choice), video_vertical.mp4 sent by agent008 only
after the user's approval on the standup, like YouTube.

UPLOAD      auto_clip's agent006, kept as it is: tiktok-uploader 1.2.0's upload-form functions only (its browser
            launcher fakes a user agent and hides automation, its cookie loader prints every cookie: neither used);
            Playwright's own Chromium, a fresh context per publication with ONLY that account's cookies, thrown away
            after. PRIVATE_VISIBILITY_STRICT: a private post whose visibility cannot be read back is not posted.
            Closed error codes; no automatic retry; messages cleaned (no cookie value, no home path, no query string).
COOKIES     COOKIE_WATCH: the state of each account's cookies, read from the file without ever showing a value:
            missing, no_session (no sessionid), expired, expiring (the session ends in under warn_days), ok,
            rejected (TikTok asked to log in again at the last publication, with this same file). check_accounts()
            runs at every start of the chain: an account that needs fresh cookies opens one incident (the standup,
            and harness's morning page, which reads the project's incidents). The standup lists the accounts.
No network here except upload(); the tests never call it.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIKTOK_HOME = "https://www.tiktok.com/"
SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt")
REJECTIONS = PROJECT_ROOT / "app" / "instance" / "tiktok_sessions.json"
CATEGORY = {"COOKIES_MISSING": "misconfiguration", "COOKIES_EXPIRED": "access_denied", "CAPTCHA_BLOCKED": "access_denied",
            "RATE_LIMITED": "budget_exhausted", "UPLOAD_TIMEOUT": "timeout", "UPLOADER_ERROR": "software_failure"}
NEEDS_ACTION = {"no_session", "expired", "expiring", "rejected"}
STATE_TEXT = {"missing": "no cookies file yet", "no_session": "the file has no TikTok session: export the cookies again",
              "expired": "the session has expired: export fresh cookies", "ok": "valid",
              "expiring": "the session ends soon: export fresh cookies", "rejected": "TikTok refused these cookies at "
              "the last publication: log in again and export fresh cookies"}
PRIVATE_LABELS = ("only you", "moi uniquement", "seulement moi", "uniquement moi", "privé", "private")
VISIBILITY_BOX = "xpath=//div[@data-e2e='video_visibility_container']"


class PublishError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def conf(settings):
    return (settings or {}).get("tiktok") or {}


def account(settings, channel_id):
    return (conf(settings).get("accounts_by_channel") or {}).get(channel_id)


def cookies_file(path):
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_cookies(path):
    """Netscape cookies.txt (a browser extension's export) -> Playwright cookies, TikTok's only. Values are never
    printed nor put in an error. '#HttpOnly_' lines are cookies, other '#' lines comments."""
    cookies = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_"):]
        elif not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, cpath, secure, expires, name, value = (x.strip() for x in parts[:7])
        if "tiktok.com" not in domain:
            continue
        c = {"name": name, "value": value, "domain": domain, "path": cpath or "/",
             "secure": secure.upper() == "TRUE", "httpOnly": http_only}
        if expires.isdigit() and int(expires) > 0:
            c["expires"] = int(expires)
        cookies.append(c)
    return cookies


def rejections():
    try:
        return json.loads(REJECTIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(channel_id, **fields):
    """app/instance/tiktok_sessions.json, per channel: the last rejection (rejected_at, cookies_mtime) and the last
    publication (published_at). Never a cookie value."""
    data = rejections()
    data[channel_id] = {**data.get(channel_id, {}), **fields}
    REJECTIONS.parent.mkdir(parents=True, exist_ok=True)
    REJECTIONS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def remember_rejection(channel_id, path):
    """TikTok refused this file's session: kept until the file changes (fresh cookies)."""
    remember(channel_id, rejected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
             cookies_mtime=Path(path).stat().st_mtime)


def cookie_status(channel_id, path, warn_days=7, now=None, rejected=None):
    """{"state", "text", "days_left", "expires_at"}: never a cookie value."""
    now = now or time.time()
    path = cookies_file(path)
    out = {"state": "missing", "days_left": None, "expires_at": None, "file": path.name}
    if not path.is_file() or path.stat().st_size == 0:
        return {**out, "text": STATE_TEXT["missing"]}
    try:
        cookies = load_cookies(path)
    except OSError:
        return {**out, "text": STATE_TEXT["missing"]}
    session = [c for c in cookies if c["name"] in SESSION_COOKIES and c["value"]]
    if not any(c["name"] == "sessionid" for c in session):
        return {**out, "state": "no_session", "text": STATE_TEXT["no_session"]}
    ends = [c["expires"] for c in session if c.get("expires")]
    if ends:
        end = min(ends)
        out["expires_at"] = datetime.fromtimestamp(end, timezone.utc).date().isoformat()
        out["days_left"] = int((end - now) // 86400)
        if end <= now:
            return {**out, "state": "expired", "text": STATE_TEXT["expired"]}
    seen = (rejections() if rejected is None else rejected).get(channel_id)
    if seen and seen.get("cookies_mtime") == path.stat().st_mtime:
        return {**out, "state": "rejected", "text": STATE_TEXT["rejected"]}
    if out["days_left"] is not None and out["days_left"] < warn_days:
        return {**out, "state": "expiring", "text": STATE_TEXT["expiring"] + f" (in {out['days_left']} day(s))"}
    return {**out, "state": "ok", "text": STATE_TEXT["ok"] + (f" until {out['expires_at']}" if out["expires_at"] else "")}


def accounts(settings, now=None, rejected=None):
    """The standup's list: one row per channel with a TikTok account."""
    warn = int(conf(settings).get("warn_days", 7))
    return [{"channel_id": channel, "label": a.get("label") or channel,
             **cookie_status(channel, a["cookies_path"], warn, now, rejected)}
            for channel, a in (conf(settings).get("accounts_by_channel") or {}).items()]


def check_accounts(supervision, settings, now=None, rejected=None):
    """COOKIE_WATCH, at every start of the chain: one open incident per account whose cookies need renewing
    (deduplicated by key, so one per account until the user closes it). Returns the rows."""
    if "tiktok" not in (settings.get("enabled_platforms") or []):
        return []
    rows = accounts(settings, now, rejected)
    for row in rows:
        if row["state"] in NEEDS_ACTION:
            supervision.open_incident(agent_id="agent008", category="access_denied",
                                      errors=[f"TikTok {row['label']}: {row['text']}"],
                                      extra={"channel": row["channel_id"], "cookies": row["file"]},
                                      dedupe_key=f"tiktok_cookies:{row['channel_id']}:{row['state']}")
    return rows


def post_text(metadata, limit=2200):
    """The post's text: the title, then up to 5 hashtags from the tags (letters and digits only)."""
    title = str(metadata.get("title") or "").strip()
    tags = metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    hashtags = []
    for tag in tags:
        word = re.sub(r"[^\w]", "", str(tag), flags=re.UNICODE)
        if word and f"#{word}" not in hashtags:
            hashtags.append(f"#{word}")
        if len(hashtags) == 5:
            break
    return (title + ("\n\n" + " ".join(hashtags) if hashtags else ""))[:limit]


def sanitize(text, secrets_=None):
    """No cookie value, no home path, no URL query string, no long token-like string, at most 200 characters."""
    text = str(text or "")
    for s in secrets_ or []:
        if s and len(s) >= 4:
            text = text.replace(s, "***")
    text = text.replace(str(Path.home()), "~")
    text = re.sub(r"(https?://[^\s?#'\"]+)[?#][^\s'\"]*", r"\1", text)
    text = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "***", text)
    return " ".join(text.split())[:200]


def classify(message, url="", html=""):
    low = f"{message} {url} {html[:200000]}".lower()
    if "/login" in url.lower() or "log in to tiktok" in low:
        return "COOKIES_EXPIRED"
    if "captcha" in low or "verify to continue" in low or "secsdk-captcha" in low:
        return "CAPTCHA_BLOCKED"
    if "timeout" in low and "exceeded" in low:
        return "UPLOAD_TIMEOUT"
    return "UPLOADER_ERROR"


def too_soon(last_published, min_gap_hours, now=None):
    """RATE_LIMIT_GUARD: at most one post per account every min_gap_hours (last_published: ISO time or None)."""
    if not last_published:
        return False
    try:
        last = datetime.fromisoformat(str(last_published).replace("Z", "+00:00"))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - last < timedelta(hours=min_gap_hours)


def set_private_strict(page, tu):
    """PRIVATE_VISIBILITY_STRICT (auto_clip, 2026-11-19: tiktok-uploader swallowed its own error and the video went
    public): the visibility is read back; not 'Only you', nothing is posted."""
    tu._set_visibility(page, "only_you")
    try:
        shown = page.locator(VISIBILITY_BOX).inner_text(timeout=10_000).lower()
    except Exception as exc:  # noqa: BLE001
        raise PublishError("UPLOADER_ERROR", "private visibility could not be checked: nothing was posted") from exc
    if not any(label in shown for label in PRIVATE_LABELS):
        raise PublishError("UPLOADER_ERROR", "private visibility could not be set: nothing was posted")


def upload(video_path, text, cookies, visibility="private", headless=False):
    """The real publication (network). Raises PublishError."""
    from playwright.sync_api import sync_playwright
    from tiktok_uploader import upload as tu
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=bool(headless))
        try:
            context = browser.new_context()
            context.add_cookies(cookies)
            page = context.new_page()
            page.set_default_timeout(30_000)
            try:
                page.goto(TIKTOK_HOME, wait_until="domcontentloaded")
                if "/login" in page.url or not any(c["name"] == "sessionid" for c in context.cookies()):
                    raise PublishError("COOKIES_EXPIRED", "TikTok asks to log in again: export fresh cookies")
                tu._go_to_upload(page)
                tu._remove_cookies_window(page)
                tu._set_video(page, path=str(video_path), num_retries=1)
                tu._remove_split_window(page)
                tu._set_interactivity(page)
                tu._set_description(page, text)
                if visibility == "private":
                    set_private_strict(page, tu)
                tu._post_video(page)
            except PublishError:
                raise
            except Exception as exc:  # noqa: BLE001 - classified from what the page shows
                try:
                    url, html = page.url, page.content()
                except Exception:  # noqa: BLE001
                    url, html = "", ""
                raise PublishError(classify(str(exc), url, html), str(exc)) from exc
        finally:
            browser.close()


def publish(channel_id, settings, video_path, metadata, last_published=None, uploader=None):
    """One approved publication: (status, error, details). `uploader` replaces upload() in tests."""
    a = account(settings, channel_id)
    if not a:
        return "not_healthy", f"no TikTok account for {channel_id} (settings tiktok.accounts_by_channel)", {}
    path = cookies_file(a["cookies_path"])
    state = cookie_status(channel_id, path, int(conf(settings).get("warn_days", 7)))
    if state["state"] in ("missing", "no_session", "expired", "rejected"):
        return "not_healthy", f"TikTok {a.get('label') or channel_id}: {state['text']} ({path.name})", {}
    if last_published is None:
        last_published = rejections().get(channel_id, {}).get("published_at")
    if too_soon(last_published, float(conf(settings).get("min_gap_hours", 20))):
        return "not_healthy", "RATE_LIMITED: one TikTok post per account per day at most", {"error_code": "RATE_LIMITED"}
    cookies = load_cookies(path)
    secrets_ = [c["value"] for c in cookies]
    visibility = conf(settings).get("visibility", "private")
    try:
        (uploader or upload)(video_path, post_text(metadata), cookies, visibility, conf(settings).get("headless", False))
    except PublishError as exc:
        if exc.code == "COOKIES_EXPIRED":
            remember_rejection(channel_id, path)
        return "critical", f"{exc.code}: {sanitize(str(exc), secrets_)}", {"error_code": exc.code}
    except Exception as exc:  # noqa: BLE001
        return "critical", f"UPLOADER_ERROR: {sanitize(f'{type(exc).__name__}: {exc}', secrets_)}", {"error_code": "UPLOADER_ERROR"}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    remember(channel_id, published_at=stamp)
    return "healthy", None, {"visibility": visibility, "publish_timestamp": stamp}


if __name__ == "__main__":         # the accounts' state, never a cookie value
    settings = json.loads((PROJECT_ROOT / "app" / "schemas" / "settings.json").read_text(encoding="utf-8"))
    for row in accounts(settings):
        print(f"{row['channel_id']:24} {row['state']:10} {row['text']}  ({row['file']})")
