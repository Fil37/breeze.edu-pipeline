"""
YouTube access for L_breeze (2026-11-26: the four channels' refresh tokens had all been refused by Google,
"invalid_grant", since at least 2026-10-30, and nothing said so before a publication failed).

RENEW        python -m app.youtube_auth renew "breeze_(math)"
             Opens Google's consent page in the browser (the user signs in with the Google account of THAT
             channel), receives the answer on http://localhost:8799/ (this computer only), exchanges it for a
             refresh token with the four scopes agent008/agent009 need, writes it in .env
             (YOUTUBE_REFRESH_TOKEN_BREEZE_MATH, the line replaced, the file kept private) and shows the name of
             the YouTube channel it opens, so a token is never saved for the wrong channel unnoticed.
             The token is never printed.
TOKEN_WATCH  check_tokens(): at every start of the chain, each publishing channel's token is tried (a token
             refresh: no YouTube quota). Refused by Google: one incident per channel (standup, harness's morning
             page). Network down: nothing opened. The result is kept in app/instance/youtube_tokens.json for the
             standup (never a token).
             python -m app.youtube_auth check   prints each channel's state.
If tokens keep dying after about 7 days, the Google Cloud project's OAuth consent screen is in "Testing":
publish it ("In production"; an unverified personal app is fine).
"""

import http.server
import json
import os
import secrets
import stat
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
STATE_FILE = PROJECT_ROOT / "app" / "instance" / "youtube_tokens.json"
PORT = 8799      # 8765 is auto_clip's site (the first version took it and failed at once)
REDIRECT = f"http://localhost:{PORT}/"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly", "https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_URL = "https://oauth2.googleapis.com/token"
TESTING_HINT = ("if this keeps happening about 7 days after a renewal, the OAuth consent screen is in 'Testing': "
                "publish the app in Google Cloud Console")


def token_name(channel_id):
    return "YOUTUBE_REFRESH_TOKEN_" + channel_id.replace("(", "").replace(")", "").upper()


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
    except ImportError:
        pass


def publishing_channels(settings, routes):
    if "youtube" not in (settings.get("enabled_platforms") or []) or settings.get("dry_run", True):
        return []
    return [r["channel_id"] for r in routes if r.get("enabled") and "youtube" in (r.get("publish_platforms") or [])]


def try_token(channel_id, env=None, post=None):
    """("ok" | "refused" | "missing" | "unreachable", detail). A refused token is Google's 400/401 answer."""
    import requests
    env = os.environ if env is None else env
    token = env.get(token_name(channel_id))
    if not token or not env.get("YOUTUBE_CLIENT_ID") or not env.get("YOUTUBE_CLIENT_SECRET"):
        return "missing", f"{token_name(channel_id)} or the OAuth client missing in .env"
    try:
        response = (post or requests.post)(TOKEN_URL, timeout=20, data={
            "client_id": env["YOUTUBE_CLIENT_ID"], "client_secret": env["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": token, "grant_type": "refresh_token"})
    except Exception as exc:  # noqa: BLE001 - offline: nothing to say about the token
        return "unreachable", type(exc).__name__
    if response.status_code == 200:
        return "ok", "accepted by Google"
    try:
        error = response.json().get("error", "")
    except ValueError:
        error = ""
    if response.status_code in (400, 401):
        return "refused", f"refused by Google ({error or response.status_code}): renew it"
    return "unreachable", f"HTTP {response.status_code}"


def check_tokens(supervision, settings, routes, env=None, post=None, state_file=None):
    """TOKEN_WATCH, at every start: one incident per publishing channel whose token Google refuses (or that has
    none). Returns {channel: {"state", "detail", "checked_at"}} and keeps it for the standup."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    states = {}
    for channel in publishing_channels(settings, routes):
        state, detail = try_token(channel, env, post)
        states[channel] = {"state": state, "detail": detail, "checked_at": now}
        if state in ("refused", "missing") and supervision is not None:
            supervision.open_incident(agent_id="agent008", category="access_denied",
                                      errors=[f"YouTube {channel}: {detail}. python -m app.youtube_auth renew "
                                              f"\"{channel}\" ({TESTING_HINT})"],
                                      extra={"channel": channel}, dedupe_key=f"youtube_token:{channel}:{state}")
    target = Path(state_file) if state_file else STATE_FILE
    if states:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(states, indent=2), encoding="utf-8")
    return states


def last_states():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_env(name, value, path=ENV_FILE):
    """Replace (or add) one NAME=value line in .env, the rest untouched, the file private (0600)."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == name:
            if not done:
                out.append(f"{name}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def receive_code(state, timeout=300):
    """Wait for Google's redirect on localhost:PORT; return the code (or raise)."""
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            got["code"], got["error"] = query.get("code", [None])[0], query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>C'est fait : tu peux fermer cet onglet et revenir au terminal.</p>".encode())

        def log_message(self, *args):
            pass

    try:
        server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        raise SystemExit(f"port {PORT} is taken by another program on this computer ({exc.strerror}): "
                         f"close it, or change PORT in app/youtube_auth.py and allow http://localhost:<port>/ "
                         f"in the OAuth client") from exc
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout + 5)
    server.server_close()
    if got.get("error") or not got.get("code"):
        raise SystemExit(f"Google did not give access: {got.get('error') or 'no answer in time'}")
    return got["code"]


def renew(channel_id):
    import requests
    load_env()
    client_id, client_secret = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET missing in .env")
    state = secrets.token_urlsafe(24)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "consent select_account", "state": state})
    print(f"Sign in with the Google account of the channel {channel_id} (choose its YouTube channel if asked).")
    print(f"If the browser does not open, paste this address in it:\n{url}\n")
    webbrowser.open(url)
    code = receive_code(state)
    answer = requests.post(TOKEN_URL, timeout=30, data={"code": code, "client_id": client_id, "client_secret": client_secret,
                                                        "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    if answer.status_code != 200:
        raise SystemExit(f"Google refused the exchange: {answer.json().get('error_description') or answer.status_code} "
                         f"(a 'redirect_uri_mismatch' means the OAuth client must allow {REDIRECT})")
    tokens = answer.json()
    if not tokens.get("refresh_token"):
        raise SystemExit("Google gave no refresh token: remove the app's access in the Google account "
                         "(myaccount.google.com/permissions) and try again")
    granted = set(tokens.get("scope", "").split())
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES if s not in granted]
    seen = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                        headers={"Authorization": "Bearer " + tokens["access_token"]}, timeout=30).json()
    titles = [i["snippet"]["title"] for i in seen.get("items") or []]
    write_env(token_name(channel_id), tokens["refresh_token"])
    print(f"Saved in .env as {token_name(channel_id)} (not shown).")
    print(f"This token opens the YouTube channel: {', '.join(titles) or 'NONE (this Google account has no channel)'}")
    if missing:
        print(f"Warning: rights not granted: {', '.join(missing)} (tick every box on Google's page)")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "renew":
        return renew(argv[1])
    if argv == ["check"]:
        load_env()
        settings = json.loads((PROJECT_ROOT / "app" / "schemas" / "settings.json").read_text(encoding="utf-8"))
        routes = json.loads((PROJECT_ROOT / "app" / "schemas" / "routes.json").read_text(encoding="utf-8"))
        for channel, row in check_tokens(None, settings, routes).items():
            print(f"{channel:24} {row['state']:12} {row['detail']}")
        return None
    raise SystemExit('usage: python -m app.youtube_auth renew "breeze_(math)" | check')


if __name__ == "__main__":
    main()
