"""
Check the YouTube access tools (app/youtube_auth.py), 2026-11-26: the four channels' tokens had been refused by
Google since 2026-10-30 and nothing said so before a publication failed. No network: Google's answer is faked;
no real .env, supervision base or state file: all in a temporary folder.
  1. TOKEN_WATCH: a token accepted, refused (400 invalid_grant), absent, or Google unreachable, read right; only the
     publishing channels checked (not a disabled one, not in dry run); one incident per refused channel, never twice,
     none when offline; never a token in an incident or in the kept states
  2. RENEW's .env writing: the channel's line replaced (or added), every other line kept, the file private (0600)
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_youtube_auth.py
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
from app import youtube_auth as ya                                    # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="breeze_youtube_"))
ya.STATE_FILE = TMP / "youtube_tokens.json"                          # never the real instance's file
ya.ENV_FILE = TMP / ".env"
SECRET = "1//refresh_token_never_shown"
ROUTES = [{"channel_id": "breeze_(math)", "enabled": True, "publish_platforms": ["youtube", "tiktok"]},
          {"channel_id": "breeze_(physics)", "enabled": True, "publish_platforms": ["youtube"]},
          {"channel_id": "breeze_(economics)", "enabled": True, "publish_platforms": ["youtube"]},
          {"channel_id": "breeze_(allemand)", "enabled": False, "publish_platforms": ["youtube"]}]
SETTINGS = {"enabled_platforms": ["youtube"], "dry_run": False}
ENV = {"YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "secret",
       "YOUTUBE_REFRESH_TOKEN_BREEZE_MATH": SECRET, "YOUTUBE_REFRESH_TOKEN_BREEZE_PHYSICS": SECRET + "2",
       "YOUTUBE_REFRESH_TOKEN_BREEZE_ALLEMAND": SECRET + "3"}


def report(label, problems):
    print(("PASS" if not problems else "FAIL") + f"  {label}")
    for line in problems:
        print(f"        - {line}")
    return not problems


class Answer:
    def __init__(self, code, body):
        self.status_code, self.body = code, body

    def json(self):
        return self.body


def case_watch():
    from app import run_supervision
    problems, asked = [], []

    def google(url, timeout, data):
        asked.append(data["refresh_token"])
        return Answer(200, {}) if data["refresh_token"] == SECRET else Answer(400, {"error": "invalid_grant"})

    store = run_supervision.store(str(TMP / "watch.db"))
    states = ya.check_tokens(store, SETTINGS, ROUTES, ENV, google)
    ya.check_tokens(store, SETTINGS, ROUTES, ENV, google)              # the next start: not opened twice
    got = {c: s["state"] for c, s in states.items()}
    if got != {"breeze_(math)": "ok", "breeze_(physics)": "refused", "breeze_(economics)": "missing"}:
        problems.append(f"states {got}")
    if SECRET + "3" in asked:
        problems.append("the disabled channel's token was tried")
    with store.connect() as c:
        rows = [r["diagnostic"] for r in c.execute("SELECT diagnostic FROM incidents WHERE status='open'")]
    if len(rows) != 2 or not any("physics" in r for r in rows) or not any("economics" in r for r in rows):
        problems.append(f"expected one incident for physics and one for economics: {rows}")
    if any(SECRET in r for r in rows) or SECRET in ya.STATE_FILE.read_text():
        problems.append("a token shown")
    if not all("youtube_auth renew" in r for r in rows):
        problems.append("an incident does not say how to renew")

    def offline(url, timeout, data):
        raise ConnectionError("no network")
    store2 = run_supervision.store(str(TMP / "offline.db"))
    states = ya.check_tokens(store2, SETTINGS, ROUTES[:1], ENV, offline)
    with store2.connect() as c:
        opened = c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    if states["breeze_(math)"]["state"] != "unreachable" or opened:
        problems.append(f"offline read as a refused token: {states} ({opened} incident)")
    if ya.check_tokens(store2, {**SETTINGS, "dry_run": True}, ROUTES, ENV, google) or \
            ya.check_tokens(store2, {"enabled_platforms": [], "dry_run": False}, ROUTES, ENV, google):
        problems.append("tokens checked in dry run or with YouTube disabled")
    return report("1. TOKEN_WATCH: ok / refused / missing / offline, publishing channels only, one incident each", problems)


def case_env():
    problems = []
    env = TMP / "env_test"
    env.write_text("OPENAI_API_KEY=keep\nYOUTUBE_REFRESH_TOKEN_BREEZE_MATH=old\n# comment\nOTHER=1\n", encoding="utf-8")
    ya.write_env("YOUTUBE_REFRESH_TOKEN_BREEZE_MATH", "new", env)
    ya.write_env("YOUTUBE_REFRESH_TOKEN_BREEZE_PHYSICS", "added", env)
    lines = env.read_text(encoding="utf-8").splitlines()
    if lines != ["OPENAI_API_KEY=keep", "YOUTUBE_REFRESH_TOKEN_BREEZE_MATH=new", "# comment", "OTHER=1",
                 "YOUTUBE_REFRESH_TOKEN_BREEZE_PHYSICS=added"]:
        problems.append(f".env written wrong: {lines}")
    if stat.S_IMODE(env.stat().st_mode) != 0o600:
        problems.append(f".env not private: {oct(stat.S_IMODE(env.stat().st_mode))}")
    if ya.token_name("breeze_(electronics)") != "YOUTUBE_REFRESH_TOKEN_BREEZE_ELECTRONICS":
        problems.append("token name differs from agent008's")
    return report("2. RENEW's .env: the channel's line replaced or added, the rest kept, private", problems)


if __name__ == "__main__":
    results = [case_watch(), case_env()]
    sys.exit(0 if all(results) else 1)
