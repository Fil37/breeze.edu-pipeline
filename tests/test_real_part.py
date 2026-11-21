"""
Check the REAL_PART piece (2026-11-21: electronic parts as they look in the hand, Fritzing drawings, CC BY-SA 3.0,
accepted by the user for the electronics channel only).
  1. the colour code worked out by the program: 220, 4 700, 10 k, 1 M, 4,7 Ω, 0,22 Ω; 4 750 or 0 refused
  2. the schema: a listed part accepted, an unknown one refused, a resistor needs a two-digit value (the message
     gives one); "4,7 kΩ" written in French
  3. the drawings: the 15 parts on disk, nothing active in them, the licence beside; a resistor's SVG carries its bands
  4. the page (electronics' theme): drawn without JS error nor conflict, the bands' reading in when "show", an LED lit
  5. only on the electronics channel: hidden and sent back elsewhere, offered there
  6. agent007: the Fritzing credit and the CC BY-SA licence in the description when a scene shows a part
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_real_part.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.render import fritzing                                       # noqa: E402
from app.agent import agent004_visualbriefgenerator as a004          # noqa: E402
from app.agent import agent007_metadatagenerator as a007             # noqa: E402
from app.agent import agent010_html_renderer as renderer             # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, simple_piece_problem   # noqa: E402

failed = []


def report(label, problems):
    print(("PASS  " if not problems else "FAIL  ") + label)
    for p in problems:
        print("      - " + p)
    if problems:
        failed.append(label)


p = []
for value, names in ((220, ["rouge", "rouge", "marron", "or"]), (4700, ["jaune", "violet", "rouge", "or"]),
                     (10000, ["marron", "noir", "orange", "or"]), (1e6, ["marron", "noir", "vert", "or"]),
                     (4.7, ["jaune", "violet", "or", "or"]), (0.22, ["rouge", "rouge", "argent", "or"])):
    got = (fritzing.resistor_bands(value) or {}).get("names")
    if got != names:
        p.append(f"{value}: {got}, expected {names}")
for wrong in (4750, 0, -10, True, "220"):
    if fritzing.resistor_bands(wrong) is not None:
        p.append(f"{wrong!r} should have no code")
report("1. the colour code worked out by the program", p)

p = []
if simple_piece_problem("REAL_PART", {"part": "led"}) or simple_piece_problem("REAL_PART", {"part": "resistor", "value": 220}):
    p.append("a listed part refused")
if not simple_piece_problem("REAL_PART", {"part": "flux-capacitor"}):
    p.append("an unknown part accepted")
message = simple_piece_problem("REAL_PART", {"part": "resistor", "value": 4750}) or ""
if "two significant digits" not in message or "4700" not in message:
    p.append(f"4750 not sent back with a value to use: {message}")
if fritzing.ohms_text(4700) != "4,7 kΩ" or fritzing.ohms_text(220) != "220 Ω" or fritzing.ohms_text(1e6) != "1 MΩ":
    p.append(f"French values: {fritzing.ohms_text(4700)}, {fritzing.ohms_text(220)}, {fritzing.ohms_text(1e6)}")
report("2. the schema: listed parts, a two-digit resistor, French values", p)

p = []
for part in fritzing.REAL_PARTS:
    text = fritzing.part_svg(part)
    if not text or "<svg" not in text:
        p.append(f"{part}: no drawing")
    elif fritzing.UNSAFE.search(text):
        p.append(f"{part}: something active")
if "Attribution-ShareALike" not in open(os.path.join(fritzing.FRITZING_DIR, "LICENSE.txt")).read():
    p.append("the CC BY-SA licence is not beside the drawings")
banded = fritzing.part_svg("resistor", 4700)
if not all(c in banded for c in fritzing.resistor_bands(4700)["colours"]):
    p.append("the resistor's SVG does not carry its bands' colours")
report("3. the 15 drawings on disk, nothing active, licence, bands coloured", p)

p = []
brief = {"scene_id": "1", "text_overlay": {"title": "Les composants"}, "connections": [], "entities": [
    {"id": "r", "type": "REAL_PART", "position": [-3, 0, 0], "initial_state": {"part": "resistor", "value": 220}},
    {"id": "l", "type": "REAL_PART", "position": [3, 0, 0], "initial_state": {"part": "led"}}],
    "actions": [{"at": 1.0, "action": "set_state", "target": "r", "state": {"show": True}},
                {"at": 2.0, "action": "set_state", "target": "l", "state": {"on": True}}]}
from playwright.sync_api import sync_playwright                       # noqa: E402
with sync_playwright() as pw, tempfile.TemporaryDirectory() as d:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    path = os.path.join(d, "p.html")
    open(path, "w").write(renderer.build_page(renderer.page_data(
        brief, 5, None, style=renderer.channel_style("breeze_(electronics)"))))
    renderer.open_scene(page, path)
    states = {}
    for t in (0.6, 4.0):
        page.evaluate(f"window.seek({t})")
        states[t] = page.evaluate("""() => { const r = E.r.data.simpleParts, l = E.l.data.simpleParts;
            return {reading: +r.reading.getAttribute("opacity"), text: r.reading.textContent, glow: +l.glow.getAttribute("opacity")}; }""")
    conflicts = page.evaluate("window.layoutConflicts")
    b.close()
if errors or conflicts:
    p.append(f"errors {errors}, conflicts {conflicts}")
if states[0.6]["reading"] > 0 or states[4.0]["reading"] < 1:
    p.append(f"the reading should come on 'show': {states}")
if "rouge · rouge · marron · or" not in states[4.0]["text"] or "220 Ω" not in states[4.0]["text"]:
    p.append(f"reading: {states[4.0]['text']}")
if states[0.6]["glow"] > 0 or states[4.0]["glow"] < 0.4:
    p.append(f"the LED should light on 'on': {states}")
report("4. the page: no error, the reading on show, the LED lit on on", p)

p = []
used = {"1": SceneVisualBrief.model_validate(brief)}
if not a004.banned_problems(["1"], used, frozenset({"REAL_PART"})):
    p.append("a REAL_PART elsewhere should be sent back")
if any(line.startswith("  * REAL_PART:") for line in a004.components_text(frozenset({"REAL_PART"})).split("\n")):
    p.append("REAL_PART still offered off the electronics channel")
import inspect                                                        # noqa: E402
if 'channel_domain != "electronics"' not in inspect.getsource(a004.ask_for_storyboard):
    p.append("ask_for_storyboard does not hide REAL_PART off the electronics channel")
report("5. only on the electronics channel", p)

p = []
story = {"scenes": [{"visual_brief": brief}]}
if a007.parts_credits(story) != [fritzing.CREDIT] or "CC BY-SA 3.0" not in fritzing.CREDIT:
    p.append(f"credit: {a007.parts_credits(story)}")
if a007.parts_credits({"scenes": [{"visual_brief": {"entities": [{"type": "OBJECT"}]}}]}):
    p.append("a video with no part credits Fritzing")
report("6. agent007: Fritzing credit and CC BY-SA licence in the description", p)

sys.exit(1 if failed else 0)
