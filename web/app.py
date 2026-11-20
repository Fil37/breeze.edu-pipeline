"""breeze web UI: one plain Flask app, read-only. Run: python web/app.py (http://127.0.0.1:5000)

Pages: the dashboard (/), one page per channel (/channel/<channel_id>), the standup (/standup).
The last video of a channel plays from /video/<channel_id> (only a channel of routes.json, only its
video.mp4). The look is the studio kit's (~/ProjetPerso/studio-kit, v1.0): static/css/breeze_master.css
and its fonts beside it; English, or French by the "lang" cookie (/lang/fr); the system's theme, or
the "theme" cookie (/theme/light, /theme/dark); a Content-Security-Policy with a nonce per request, no
inline style. A channel is told by its logo (/logo/<channel_id>: its "watermark_by_channel" file in
settings.json), never by a colour: the kit keeps colours for states."""

import json
import os
import secrets
import sys
from urllib.parse import quote, unquote

from flask import Flask, abort, g, redirect, render_template, request, send_file, send_from_directory, url_for

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


def clock(value):
    """65.4 -> "1:05"; None -> "—"."""
    if not isinstance(value, (int, float)):
        return "—"
    return f"{int(value) // 60}:{int(value) % 60:02d}"


app.jinja_env.filters["clock"] = clock


# The kit's colours by state: breeze's agent statuses -> the kit's badge and step classes.
BADGES = {"healthy": "healthy", "not_healthy": "warning", "critical": "critical", "revision_needed": "partial",
          "not_run": "pending", "skipped": "skipped"}
STEPS = {"healthy": "succeeded", "not_healthy": "partial", "critical": "failed", "revision_needed": "partial",
         "not_run": "not_run", "skipped": "skipped"}
app.jinja_env.filters["badge"] = lambda status: BADGES.get(status, "plain")
app.jinja_env.filters["step"] = lambda status: STEPS.get(status, "not_run")

# The interface in French (cookie "lang"): the English of the pages -> French. What the channels produce
# (names, topics, titles, QA notes) is French already.
FRENCH = {
    "Dashboard": "Tableau de bord", "Standup": "Point du jour", "Theme": "Thème", "Light": "Clair", "Dark": "Sombre",
    "Follow the system": "Suivre le système", "read-only": "lecture seule", "channels": "chaînes",
    "videos ready": "vidéos prêtes", "active": "actives", "failed": "en échec", "agents": "agents",
    "The channels, their latest video and the state of each agent at the last run.":
        "Les chaînes, leur dernière vidéo et l'état de chaque agent au dernier passage.",
    "No video yet": "Pas encore de vidéo", "theme": "thème", "No topic yet": "Pas encore de sujet",
    "Accuracy": "Exactitude", "Simplicity": "Simplicité", "Clarity": "Clarté", "Last run": "Dernier passage",
    "Next run": "Prochain passage", "Scenes": "Scènes", "never": "jamais", "disabled": "désactivée",
    "Open channel": "Ouvrir la chaîne", "Open": "Ouvrir", "audience": "public", "Platforms": "Plateformes",
    "channel disabled": "chaîne désactivée", "Latest video": "Dernière vidéo", "Untitled": "Sans titre",
    "Rendered": "Rendue le", "voice": "voix", "render": "rendu", "Video outline": "Plan de la vidéo",
    "layout conflict(s) measured at render time": "conflit(s) de mise en page mesuré(s) au rendu",
    "No render manifest.": "Pas de manifeste de rendu.", "YouTube chapters": "Chapitres YouTube",
    "No video yet for this channel. Start a run with": "Pas encore de vidéo pour cette chaîne. Lancez un passage avec",
    "Quality check": "Contrôle qualité", "Verdict": "Verdict", "passed": "validé", "corrected": "corrigé(s)",
    "blocking": "bloquant(s)", "scene": "scène", "No issue found.": "Aucun problème relevé.",
    "Last 10 runs": "Les 10 derniers passages", "Run": "Passage", "Status": "État", "Topic": "Sujet",
    "QA revisions": "Révisions QA", "Duration": "Durée", "No run yet.": "Aucun passage pour l'instant.",
    "Published videos": "Vidéos publiées", "Published": "Publiée le", "Platform": "Plateforme", "Link": "Lien",
    "Nothing published yet (uploads are private).": "Rien de publié pour l'instant (les envois sont privés).",
    "QA rejections": "Rejets du QA", "Scores (acc./simp./clarity)": "Notes (exact./simpl./clarté)",
    "Sent back to": "Renvoyé à", "Reason": "Raison", "No rejection.": "Aucun rejet.", "Topics": "Sujets",
    "Video": "Vidéo", "Quality": "Qualité", "Runs": "Passages", "Last run of each agent, channel by channel.":
        "Le dernier passage de chaque agent, chaîne par chaîne.",
    "What each agent did, channel by channel.": "Ce que chaque agent a fait, chaîne par chaîne.",
    "No run yet. Start one with": "Aucun passage pour l'instant. Lancez-en un avec", "warnings": "avertissements",
    "agents in all": "agents en tout", "finished cleanly": "terminés proprement", "to look at": "à regarder",
    "healthy": "sain", "warning": "avertissement", "critical": "échec", "revision": "révision", "not run": "pas lancé",
    "skipped": "sauté", "this interface starts nothing and changes no file.": "cette interface ne lance rien et ne modifie aucun fichier.",
}


def translate(text):
    return FRENCH.get(text, text) if g.get("lang") == "fr" else text


app.jinja_env.filters["status"] = lambda status: translate(page.STATUS_LABELS.get(status, status or "—"))


@app.before_request
def prepare():
    g.lang = request.cookies.get("lang") if request.cookies.get("lang") in ("en", "fr") else "en"
    g.csp_nonce = secrets.token_urlsafe(16)


def channel_logo(channel_id):
    """The channel's logo file (settings.json "watermark_by_channel", a PNG of the project), or None."""
    if channel_id not in {r["channel_id"] for r in page.routes()}:
        return None
    try:
        with open(os.path.join(BASE_DIR, "schemas", "settings.json"), encoding="utf-8") as f:
            path = (json.load(f).get("watermark_by_channel") or {}).get(channel_id)
    except (OSError, ValueError):
        return None
    full = os.path.realpath(os.path.join(BASE_DIR, str(path or "")))
    inside = full.startswith(os.path.join(os.path.realpath(BASE_DIR), "assets") + os.sep)
    return full if path and inside and full.endswith(".png") and os.path.isfile(full) else None


@app.context_processor
def inject():
    theme = request.cookies.get("theme")
    return {"lang": g.lang, "theme": theme if theme in ("light", "dark") else "auto", "_": translate,
            "csp_nonce": g.csp_nonce, "has_logo": lambda channel_id: channel_logo(channel_id) is not None}


@app.after_request
def security(response):
    """The kit's policy: nothing inline without the request's nonce; videos and fonts from here only."""
    nonce = g.get("csp_nonce", "")
    response.headers["Content-Security-Policy"] = (f"default-src 'self'; img-src 'self' data:; media-src 'self'; "
                                                   f"style-src 'self' 'nonce-{nonce}'; script-src 'self' 'nonce-{nonce}'")
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def back(default):
    """Back to the page asked for (a path of this site only), else `default`."""
    target = request.args.get("next") or default
    return redirect(target if target.startswith("/") and not target.startswith("//") else default)


@app.route("/lang/<code>")
def set_language(code):
    response = back(url_for("dashboard"))
    if code in ("en", "fr"):
        response.set_cookie("lang", code, max_age=365 * 86400, samesite="Lax")
    return response


@app.route("/theme/<code>")
def set_theme(code):
    response = back(url_for("dashboard"))
    if code in ("light", "dark"):
        response.set_cookie("theme", code, max_age=365 * 86400, samesite="Lax")
    else:
        response.delete_cookie("theme")
    return response


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


@app.route("/logo/<path:channel_id>")
def logo(channel_id):
    path = channel_logo(unquote(channel_id))
    if path is None:
        abort(404)
    return send_file(path, mimetype="image/png", max_age=86400)


@app.route("/fonts/<name>")
def font(name):
    if name not in FONT_FILES or not os.path.isfile(os.path.join(FONTS_DIR, name)):
        abort(404)
    return send_from_directory(FONTS_DIR, name, mimetype="font/woff2", max_age=86400)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
