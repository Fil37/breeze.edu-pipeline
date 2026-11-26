"""breeze web UI: one plain Flask app, read-only. Run: python app/web/app.py (http://127.0.0.1:5000)

Pages: the dashboard (/), one page per channel (/channel/<channel_id>), the standup (/standup).
The last video of a channel plays from /video/<channel_id> (only a channel of routes.json, only its
video.mp4). The look is the studio kit's (~/ProjetPerso/studio-kit, v1.0): app/static/css/breeze_master.css
and its fonts beside it; English, or French by the "lang" cookie (/lang/fr); the system's theme, or
the "theme" cookie (/theme/light, /theme/dark); a Content-Security-Policy with a nonce per request, no
inline style. A channel is told by its logo (/logo/<channel_id>: its "watermark_by_channel" file in
settings.json), never by a colour: the kit keeps colours for states.
The standup is the kit's supervision (app/run_supervision.py on the socle app/supervision.py): what the runs
cost (app/costs.py's history), each agent's health over time, the open incidents and the recent errors. The
only thing this interface changes, by POSTs checked against the "csrf" cookie: an incident closed ("Resolved" / "Ignore",
which does not change the agent's health), an approval decided (a publication goes up only then, by agent008's
handler), skill activations proposed, and a run started.
Runs from the site (2026-11-21): a channel's page starts the orchestrator for that channel (an optional topic, or an
episode id; publication and analytics skipped unless unticked), in the background, one run at a time (none while a
real run is going: the socle's busy_runs, or a run this site started still alive); its output goes to
app/instance/web_runs/<name>.log, read at /runs/<name>/log as plain text, the secrets of .env removed."""

import glob
import json
import os
import re
import subprocess
import time
import secrets
import sys
from urllib.parse import quote, unquote

import jinja2
from flask import Flask, abort, g, redirect, render_template, request, send_file, send_from_directory, url_for

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/web/
# Replace app/web/ (the script's folder) with the project root on the import path:
# otherwise `import app` would find this file instead of the app/ package.
sys.path = [BASE_DIR] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))]

from app.web import page
from app import run_supervision

FONTS_DIR = os.path.join(BASE_DIR, "app", "assets", "fonts")
FONT_FILES = {"inter-latin-400-normal.woff2", "inter-latin-600-normal.woff2", "inter-latin-800-normal.woff2",
              "fira-code-latin-400-normal.woff2", "fira-code-latin-600-normal.woff2"}

app = Flask(__name__, template_folder="templates", static_folder=os.path.join(BASE_DIR, "app", "static"))
# the channel card lives in app/static/card/ (the ss_pro layout): app/static is a template folder too
app.jinja_loader = jinja2.ChoiceLoader([app.jinja_loader, jinja2.FileSystemLoader(os.path.join(BASE_DIR, "app", "static"))])
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
    "skipped": "sauté", "this interface starts runs, closes incidents and decides approvals; it publishes nothing without your approval.": "cette interface lance des runs, ferme des incidents et décide des validations ; elle ne publie rien sans votre accord.",
    "Runs in progress": "Runs en cours", "Nothing running.": "Rien en cours.", "Pending approvals": "Validations en attente",
    "Propose skill activations": "Proposer les activations", "Action": "Action", "Target": "Cible", "Parameters": "Paramètres",
    "Decision": "Décision", "Approve": "Approuver", "Reject": "Refuser", "No pending approval.": "Aucune validation en attente.",
    "Skills": "Skills", "Skill": "Skill", "proposed": "proposée", "validated": "validée", "active": "active", "retired": "retirée",
    "Quality checks": "Contrôles qualité", "Check": "Contrôle", "Outcome": "Résultat", "Count": "Nombre", "pass": "réussi",
    "kept_despite": "gardé malgré", "No check recorded yet.": "Aucun contrôle enregistré pour l'instant.",
    "Backups and disk": "Sauvegardes et disque", "No backup yet.": "Aucune sauvegarde pour l'instant.", "instance": "instance",
    "backups": "sauvegardes", "free": "libre", "Approvals": "Validations", "waiting for you": "en attente de vous",
    "running": "en cours", "Start a run": "Lancer un run", "Topic (optional)": "Sujet (facultatif)",
    "Skip publication and analytics": "Sans publication ni analytique", "Start": "Lancer", "Log": "Journal",
    "Runs started from the site": "Runs lancés depuis le site", "The run started: it takes 10 to 15 minutes.":
        "Le run est lancé : il prend 10 à 15 minutes.", "No run can start now:": "Impossible de lancer un run maintenant :",
    "empty: the channel chooses (its programme for German)": "vide : la chaîne choisit (son programme pour l'allemand)",
    "about $0.06 with the free voice, $0.60 with ElevenLabs": "environ 0,06 $ avec la voix gratuite, 0,60 $ avec ElevenLabs",
    "succeeded": "terminé", "failed": "échoué", "a run is in progress": "un run est en cours",
    "a run started from the site is in progress": "un run lancé depuis le site est en cours",
    "Cost of the last run": "Coût du dernier run", "AI": "IA", "voice": "voix", "Costs by day": "Coûts par jour",
    "Day": "Jour", "Runs": "Passages", "Calls": "Appels", "Tokens": "Jetons", "Total": "Total",
    "Agent health": "Santé des agents", "Incidents": "Incidents", "Resolved": "Résolu", "Ignore": "Ignorer",
    "No open incident.": "Aucun incident ouvert.", "Recent errors": "Erreurs récentes", "No error.": "Aucune erreur.",
    "unknown": "inconnu", "degraded": "dégradé", "disabled": "désactivé", "Agents": "Agents", "Cost today": "Coût du jour",
    "open": "ouverts", "since the start": "depuis le début", "No cost recorded yet.": "Aucun coût enregistré pour l'instant.",
    "Closing an incident does not change the agent's health: it heals at its next good run.":
        "Fermer un incident ne change pas la santé de l'agent : il guérit à son prochain run réussi.",
    "Channels at the last run": "Les chaînes au dernier passage",
}


def translate(text):
    return FRENCH.get(text, text) if g.get("lang") == "fr" else text


app.jinja_env.filters["status"] = lambda status: translate(page.STATUS_LABELS.get(status, status or "—"))


CSRF_COOKIE = "csrf"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def trusted_hosts():
    """HOST_GUARD (2026-11-25, Secure Agents found HOST_NOT_CHECKED on port 5000): the site answers only to
    localhost, 127.0.0.1 and the exact names of TRUSTED_EXTRA_HOSTS (your Tailscale address, from the environment
    or the project's .env, never committed). Any other Host header is refused, so a web page opened on this PC
    cannot drive the site by DNS rebinding."""
    raw = os.environ.get("TRUSTED_EXTRA_HOSTS")
    env = os.path.join(BASE_DIR, ".env")
    if raw is None and os.path.isfile(env):
        with open(env, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("TRUSTED_EXTRA_HOSTS="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
    extra = {h.strip().lower().rstrip(".") for h in (raw or "").split(",") if h.strip()}
    return LOCAL_HOSTS | {h for h in extra if HOSTNAME.fullmatch(h)}


TRUSTED_HOSTS = trusted_hosts()


def host_name(host):
    """'name:port' -> 'name'; '[::1]:5000' -> '[::1]'."""
    host = (host or "").lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


@app.before_request
def prepare():
    if host_name(request.host) not in TRUSTED_HOSTS:
        abort(400)
    g.lang = request.cookies.get("lang") if request.cookies.get("lang") in ("en", "fr") else "en"
    g.csp_nonce = secrets.token_urlsafe(16)
    token = request.cookies.get(CSRF_COOKIE, "")
    g.csrf_new = len(token) < 32
    g.csrf = secrets.token_urlsafe(32) if g.csrf_new else token


def check_csrf():
    """A form that changes something carries the browser's token (double submit): else 400."""
    sent, kept = request.form.get("csrf", ""), request.cookies.get(CSRF_COOKIE, "")
    if not kept or not secrets.compare_digest(sent, kept):
        abort(400)


def channel_logo(channel_id):
    """The channel's logo file (settings.json "watermark_by_channel", a PNG of the project), or None."""
    if channel_id not in {r["channel_id"] for r in page.routes()}:
        return None
    try:
        with open(os.path.join(BASE_DIR, "app", "schemas", "settings.json"), encoding="utf-8") as f:
            path = (json.load(f).get("watermark_by_channel") or {}).get(channel_id)
    except (OSError, ValueError):
        return None
    full = os.path.realpath(os.path.join(BASE_DIR, str(path or "")))
    inside = full.startswith(os.path.join(os.path.realpath(BASE_DIR), "app", "assets") + os.sep)
    return full if path and inside and full.endswith(".png") and os.path.isfile(full) else None


@app.context_processor
def inject():
    theme = request.cookies.get("theme")
    return {"lang": g.lang, "theme": theme if theme in ("light", "dark") else "auto", "_": translate,
            "csp_nonce": g.csp_nonce, "csrf": g.csrf, "has_logo": lambda channel_id: channel_logo(channel_id) is not None}


@app.after_request
def security(response):
    """The kit's policy: nothing inline without the request's nonce; videos and fonts from here only."""
    nonce = g.get("csp_nonce", "")
    response.headers["Content-Security-Policy"] = (f"default-src 'self'; img-src 'self' data:; media-src 'self'; "
                                                   f"style-src 'self' 'nonce-{nonce}'; script-src 'self' 'nonce-{nonce}'; "
                                                   "frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"                 # HEADER_FRAME: no clickjacking from another site
    response.headers["Referrer-Policy"] = "same-origin"
    if g.get("csrf_new"):
        response.set_cookie(CSRF_COOKIE, g.csrf, httponly=True, samesite="Strict", max_age=86400)
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
    return render_template("breeze.html", channels=page.dashboard(), active="dashboard")


@app.route("/channel/<path:channel_id>")
def channel(channel_id):
    data = page.channel_page(unquote(channel_id))
    if data is None:
        abort(404)
    runs = [r for r in web_runs() if r["channel"] == data["route"]["channel_id"]][:5]
    from app import tiktok
    settings = page.load_json(os.path.join(page.SCHEMAS_DIR, "settings.json")) or {}
    accounts = {a["channel_id"]: a for a in tiktok.accounts(settings)}
    return render_template("breeze_page.html", active="channel", web_runs=runs, busy=busy_reason(),
                           run_message=request.args.get("run"), publish_message=request.args.get("publish"),
                           tiktok_account=accounts.get(data["route"]["channel_id"]), **data)


@app.route("/publish/<path:channel_id>/<platform>", methods=["POST"])
def publish_request(channel_id, platform):
    """PUBLISH_BUTTON (2026-11-26, the user did not find how to publish on TikTok): asks agent008 for this channel's
    publication on one platform. Nothing is uploaded here: agent008 asks for the user's approval (standup), or says
    why it cannot (no cookies, disabled platform, no video...). CSRF-checked; only the route's own platforms."""
    check_csrf()
    from app.agent import agent008_platformpublisher as a008
    channel_id = unquote(channel_id)
    route = page.find_route(page.routes(), channel_id)
    if route is None or platform not in (route.get("publish_platforms") or []) or platform not in a008.VIDEO_FILE:
        abort(404)
    folder = os.path.join(page.INSTANCE_DIR, channel_id)
    video_file = os.path.join(folder, a008.VIDEO_FILE[platform])
    metadata = page.load_json(os.path.join(folder, "metadata.json"))
    if not metadata:
        message = "no metadata.json: run the chain first"
    else:
        settings = page.load_json(os.path.join(page.SCHEMAS_DIR, "settings.json")) or {}
        status, error = a008.publish_one(channel_id, platform, settings, video_file, metadata, {})
        message = error or "done"
    return redirect(url_for("channel", channel_id=channel_id, publish=f"{platform}: {message}") + "#publish")


# ---- runs started from the site
RUNS_DIR = os.path.join(BASE_DIR, "app", "instance", "web_runs")
ORCHESTRATOR = os.path.join(BASE_DIR, "app", "agent", "agent000_breeze.py")
TOPIC_MAX = 200
RUN_NAME = re.compile(r"^\d{8}T\d{6}_[a-z0-9_-]{1,40}$")
RUNNING = {}            # name -> Popen, for the runs this process started (their exit code)


def start_process(argv, log_path):
    """The orchestrator in the background, its output in log_path; returns the Popen. No shell: argv as is."""
    log = open(log_path, "w", encoding="utf-8")
    return subprocess.Popen(argv, cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)


def pid_alive(pid):
    from app.supervision import pid_alive as alive      # never os.kill(pid, 0): it kills on Windows
    return alive(pid)


def web_runs():
    """The runs started from the site, newest first: {name, channel, topic, skip, started_at, state, code}."""
    runs_dir = app.config.get("RUNS_DIR") or RUNS_DIR
    out = []
    for meta in sorted(glob.glob(os.path.join(runs_dir, "*.json")), reverse=True)[:50]:
        try:
            with open(meta, encoding="utf-8") as f:
                run = json.load(f)
        except (OSError, ValueError):
            continue
        proc = RUNNING.get(run.get("name"))
        code = proc.poll() if proc else None
        alive = code is None if proc else pid_alive(run.get("pid"))
        run.update(state="running" if alive else ("succeeded" if code in (0, None) else "failed"), code=code)
        out.append(run)
    return out


def busy_reason():
    """Why no run can start now, or None: a real run going (the socle's busy_runs on breeze.db), or one this site
    started still alive."""
    from app.supervision import busy_runs
    going = busy_runs(app.config.get("SUPERVISION_DB") or run_supervision.DB_PATH)
    if going:
        return f"{translate('a run is in progress')} ({going[0]})"
    alive = [r for r in web_runs() if r["state"] == "running"]
    return f"{translate('a run started from the site is in progress')} ({alive[0]['channel']})" if alive else None


@app.route("/runs/start", methods=["POST"])
def run_start():
    check_csrf()
    channel_id = request.form.get("channel", "")
    if channel_id not in {r["channel_id"] for r in page.routes()}:
        abort(404)
    topic = " ".join(request.form.get("topic", "").split())[:TOPIC_MAX]
    target = url_for("channel", channel_id=channel_id)
    if busy_reason():
        return redirect(target + "?run=busy#run")
    argv = [sys.executable, ORCHESTRATOR, "--channel", channel_id]
    if topic:
        argv.append(f"--topic={topic}")                  # "=": a topic starting with "-" stays a topic
    skip = request.form.get("skip") == "1"
    if skip:
        argv.append("--skip-agents=agent008,agent009")
    runs_dir = app.config.get("RUNS_DIR") or RUNS_DIR
    os.makedirs(runs_dir, exist_ok=True)
    name = time.strftime("%Y%m%dT%H%M%S") + "_" + re.sub(r"[^a-z0-9]+", "-", channel_id.lower()).strip("-")[:40]
    proc = (app.config.get("LAUNCHER") or start_process)(argv, os.path.join(runs_dir, name + ".log"))
    RUNNING[name] = proc
    with open(os.path.join(runs_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "channel": channel_id, "topic": topic, "skip": skip, "pid": getattr(proc, "pid", None),
                   "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
    return redirect(target + "?run=started#run")


@app.route("/runs/<name>/log")
def run_log(name):
    """A run's output, its last 400 lines, as plain text (never HTML), the secrets of .env removed."""
    runs_dir = app.config.get("RUNS_DIR") or RUNS_DIR
    path = os.path.join(runs_dir, name + ".log")
    if not RUN_NAME.match(name) or not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = "".join(f.readlines()[-400:])
    for secret in run_supervision.env_secrets():
        text = text.replace(secret, "***")
    return text, 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}


def supervision():
    return run_supervision.store(app.config.get("SUPERVISION_DB") or run_supervision.DB_PATH)


@app.route("/standup")
def standup():
    from app import supervision as socle
    agents = [a for a in page.AGENT_ORDER]
    store = supervision()
    data = store.dashboard(agents)
    backup_dir = app.config.get("BACKUP_DIR") or run_supervision.BACKUP_DIR
    data["backups"] = socle.backups(backup_dir, "breeze")
    data["disk"] = socle.disk_usage({"instance": os.path.dirname(store.db_path), "backups": backup_dir})
    for row in data["agents"]:
        row["name"] = page.AGENT_NAMES.get(row["id"], row["id"])
    for incident in data["incidents"]:
        incident["name"] = page.AGENT_NAMES.get(incident["agent"], incident["agent"])
    from app import tiktok
    settings = page.load_json(os.path.join(page.SCHEMAS_DIR, "settings.json")) or {}
    tiktok_accounts = tiktok.accounts(settings) if "tiktok" in (settings.get("enabled_platforms") or []) else []
    from app import youtube_auth
    youtube_tokens = youtube_auth.last_states()          # the last start's check (never a token, no network here)
    return render_template("breeze_standup.html", active="standup", supervision=data, costs=page.costs(),
                           tiktok_accounts=tiktok_accounts, youtube_tokens=youtube_tokens, **page.standup())


def publish_handler(target, parameters):
    """The project's handler for "publish_video" (agent008): what an approval applies. Nothing else is applied."""
    from app.agent import agent008_platformpublisher
    return agent008_platformpublisher.publish_approved(target, parameters)


APPROVAL_HANDLERS = {"publish_video": publish_handler}


@app.route("/approvals/<int:approval_id>", methods=["POST"])
def approval_decide(approval_id):
    """Approve (the handler applies it) or reject a pending approval; CSRF-checked. An action with no handler stays
    pending: nothing is applied blindly."""
    check_csrf()
    try:
        supervision().decide(approval_id, request.form.get("decision") == "approve", app.config.get("HANDLERS", APPROVAL_HANDLERS))
    except KeyError:
        abort(404)
    return redirect(url_for("standup") + "#approvals")


@app.route("/skills/propose", methods=["POST"])
def propose_skills():
    """One approval "activate_skill" per skill not active yet."""
    check_csrf()
    supervision().propose_skill_activations()
    return redirect(url_for("standup") + "#approvals")


@app.route("/incidents/<int:incident_id>/close", methods=["POST"])
def incident_close(incident_id):
    """Resolved or ignored, from the standup. The agent's health is not touched: it heals at its next good run."""
    check_csrf()
    try:
        supervision().close_incident(incident_id, request.form.get("status", ""), request.form.get("resolution", ""))
    except (KeyError, ValueError):
        abort(404)
    return redirect(url_for("standup") + "#incidents")


@app.route("/video/<path:channel_id>")
def video(channel_id):
    path = page.video_path(unquote(channel_id), vertical=request.args.get("format") == "vertical")
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
    # FLASK_DEBUG (2026-11-25): never debug=True, its console runs Python code and port 5000 goes through Tailscale.
    app.run(host="127.0.0.1", port=5000, debug=False)
