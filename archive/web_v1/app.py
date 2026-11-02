"""breeze web UI: one plain Flask app, 3 read-only pages. Run: python web/app.py"""

import os
import sys
from urllib.parse import quote, unquote

from flask import Flask, abort, render_template
from jinja2 import ChoiceLoader, FileSystemLoader

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Replace web/ (the script's folder) with the project root on the import path:
# otherwise `import app` would find this file instead of the app/ package.
sys.path = [BASE_DIR] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))]

from web import page

app = Flask(__name__, template_folder="templates", static_folder=os.path.join(BASE_DIR, "static"))
# Also look up templates in static/, so breeze.html can include card/breeze_card.html.
app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(app.static_folder)])
# breeze_(math) -> breeze_%28math%29 in links.
app.jinja_env.filters["quote"] = lambda text: quote(text, safe="")


@app.route("/")
def dashboard():
    return render_template("breeze.html", channels=page.dashboard())


@app.route("/channel/<path:channel_id>")
def channel(channel_id):
    data = page.channel_page(unquote(channel_id))
    if data is None:
        abort(404)
    return render_template("breeze_page.html", **data)


@app.route("/standup")
def standup():
    return render_template("breeze_standup.html", **page.standup())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
