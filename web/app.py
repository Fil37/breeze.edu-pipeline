"""breeze web UI: one plain Flask app, read-only. Run: python web/app.py (http://127.0.0.1:5000)

Pages: the dashboard (/), one page per channel (/channel/<channel_id>), the standup (/standup).
The last video of a channel plays from /video/<channel_id> (only a channel of routes.json, only its
video.mp4); the page fonts come from assets/fonts/ (cached by the renderer), else the system's."""

import os
import sys
from urllib.parse import quote, unquote

from flask import Flask, abort, render_template, send_file, send_from_directory

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Replace web/ (the script's folder) with the project root on the import path:
# otherwise `import app` would find this file instead of the app/ package.
sys.path = [BASE_DIR] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))]

from web import page

FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")
FONT_FILES = {"inter-latin-400-normal.woff2", "inter-latin-600-normal.woff2", "inter-latin-800-normal.woff2",
              "fira-code-latin-400-normal.woff2", "fira-code-latin-600-normal.woff2"}

app = Flask(__name__, template_folder="templates", static_folder=os.path.join(BASE_DIR, "static"))
# breeze_(math) -> breeze_%28math%29 in links.
app.jinja_env.filters["quote"] = lambda text: quote(text, safe="")
app.jinja_env.filters["status"] = lambda status: page.STATUS_LABELS.get(status, status or "—")


def clock(value):
    """65.4 -> "1:05"; None -> "—"."""
    if not isinstance(value, (int, float)):
        return "—"
    return f"{int(value) // 60}:{int(value) % 60:02d}"


app.jinja_env.filters["clock"] = clock


@app.route("/")
def dashboard():
    return render_template("dashboard.html", channels=page.dashboard(), active="dashboard")


@app.route("/channel/<path:channel_id>")
def channel(channel_id):
    data = page.channel_page(unquote(channel_id))
    if data is None:
        abort(404)
    return render_template("channel.html", active="channel", **data)


@app.route("/standup")
def standup():
    return render_template("standup.html", active="standup", **page.standup())


@app.route("/video/<path:channel_id>")
def video(channel_id):
    path = page.video_path(unquote(channel_id))
    if path is None:
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)     # range requests: the player can seek


@app.route("/fonts/<name>")
def font(name):
    if name not in FONT_FILES or not os.path.isfile(os.path.join(FONTS_DIR, name)):
        abort(404)
    return send_from_directory(FONTS_DIR, name, mimetype="font/woff2", max_age=86400)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
