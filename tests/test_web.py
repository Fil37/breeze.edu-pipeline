"""
Check the web interface (Flask test client, no server, no browser):
  1. the dashboard, a channel's page and the standup answer 200, in French; an unknown channel is a 404
  2. /video/<channel_id> serves only a channel of routes.json, with range requests (the player seeks);
     anything else, a path included, is a 404; /fonts/ serves only the listed woff2 files
  3. each channel gets its video theme's accent colour (a #RRGGBB, from agent010's THEMES)
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_web.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from web import page                                                  # noqa: E402
from web.app import app                                               # noqa: E402

client = app.test_client()


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def get(url, **kwargs):
    response = client.get(url, **kwargs)
    response.close()
    return response


def case_pages():
    problems = []
    channel = page.routes()[0]["channel_id"]
    for url, words in (("/", "Tableau de bord"), (f"/channel/{channel.replace('(', '%28').replace(')', '%29')}", "Dernière vidéo"),
                       ("/standup", "Standup")):
        response = get(url)
        if response.status_code != 200 or words not in response.get_data(as_text=True):
            problems.append(f"{url}: {response.status_code}")
    if get("/channel/breeze_(nope)").status_code != 404:
        problems.append("an unknown channel is not a 404")
    return report("1. the three pages answer, in French; an unknown channel is a 404", problems)


def case_files():
    problems = []
    with_video = [r["channel_id"] for r in page.routes() if page.video_path(r["channel_id"])]
    if with_video:
        response = get(f"/video/{with_video[0]}", headers={"Range": "bytes=0-99"})
        if response.status_code != 206 or response.content_length != 100 or response.mimetype != "video/mp4":
            problems.append(f"video range: {response.status_code} {response.content_length} {response.mimetype}")
    for url in ("/video/breeze_(nope)", "/video/..%2Fbreeze.db", "/video/breeze_(math)%2F..%2F..%2Fschemas",
                "/fonts/x.woff2", "/fonts/..%2Fkatex"):
        if get(url).status_code != 404:
            problems.append(f"{url} is served")
    if get("/fonts/inter-latin-400-normal.woff2").status_code not in (200, 404):   # 404: fonts not cached yet
        problems.append("the Inter font")
    return report("2. only a channel's video.mp4 and the listed fonts are served", problems,
                  [f"video checked for {with_video[0]}" if with_video else "no video yet: range not checked"])


def case_colours():
    themes = {r["channel_id"]: page.channel_theme(r["channel_id"]) for r in page.routes()}
    problems = [f"{c}: {t}" for c, t in themes.items() if not re.fullmatch(r"#[0-9A-Fa-f]{6}", t["accent"])]
    if len({t["accent"] for t in themes.values()}) < min(len(themes), 3):
        problems.append(f"the channels share their colours: {themes}")
    return report("3. each channel has its theme's accent colour", problems,
                  [", ".join(f"{c} {t['name']} {t['accent']}" for c, t in themes.items())])


sys.exit(0 if all([case_pages(), case_files(), case_colours()]) else 1)
