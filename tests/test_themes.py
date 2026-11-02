"""
Check the channels' themes (agent010 THEMES, app/render/fonts.py): each channel its colours, its
animated background, its fonts and its title style.
  1. channel_style: electronics -> lab, physics -> space, math -> notebook, economics -> data (an unknown
     channel gets the default); the icons are drawn in the theme's ink (light on a dark theme)
  2. the fonts (Inter, Fira Code, Space Grotesk) are inlined into the page, never fetched by it
  3. agent010 page (Chromium), one scene per theme: dark or light as set, the background built (grid /
     stars, glows), the wires' layer laid over the whole stage (a lost CSS rule once hid every wire),
     the step line of "lab", the word-by-word title of "notebook", the background moving with t
  4. step 2, the effects: the Earth, the Moon, the Sun drawn as spheres (not icon cards); on a dark
     theme, curves with a halo drawn with them and BODYs lit; on "data", the area under y = f(x) filled
  5. step 3, meaning: a "tone" (result / warning / wrong / key) on a formula or a badge is accepted,
     elsewhere refused; "emphasize" (shake / pulse) checked; agent010: the toned formula in its colour,
     a shake moving it then letting it go, a pulse scaling it
Prints PASS or FAIL per case. Case 3 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_themes.py
"""

import base64
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent010_html_renderer as renderer          # noqa: E402

CIRCUIT = {"scene_id": "1", "text_overlay": {"title": "Deux grandeurs", "subtitle": "Tension et courant"},
           "entities": [{"id": "b", "type": "BATTERY", "position": [-3, 0, 0], "initial_state": {"label": "Pile"}},
                        {"id": "l", "type": "LAMP", "position": [2, 0, 0], "initial_state": {"label": "Lampe"}},
                        {"id": "c", "type": "CART", "position": [0, -2, 0], "initial_state": {"label": "Panier"}}],
           "connections": [{"source_id": "b", "source_port": "positive", "target_id": "l", "target_port": "left_terminal"},
                           {"source_id": "l", "source_port": "right_terminal", "target_id": "b", "target_port": "negative"}],
           "actions": []}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_styles():
    problems = []
    names = {ch: renderer.channel_style(f"breeze_({ch})")["name"] for ch in ("electronics", "physics", "math", "economics", "unknown")}
    if names != {"electronics": "lab", "physics": "space", "math": "notebook", "economics": "data", "unknown": "notebook"}:
        problems.append(f"themes {names}")
    dark = renderer.page_data(CIRCUIT, 4, 4, style=renderer.channel_style("breeze_(economics)"))
    cart = next(e for e in dark["entities"] if e["id"] == "c")["icon"]
    svg = base64.b64decode(cart.split(",", 1)[1]).decode()
    if renderer.THEMES["data"]["tokens"]["icon"] not in svg:
        problems.append("the icon is not drawn in the dark theme's ink")
    return report("1. a theme per channel; icons in the theme's ink", problems, [str(names)])


def case_fonts():
    page = renderer.build_page(renderer.page_data(CIRCUIT, 4, 4, style=renderer.channel_style("breeze_(electronics)")))
    problems = [f"{family} not inlined" for family in ("Inter", "Fira Code") if f"font-family:'{family}'" not in page]
    if "fonts.googleapis" in page or "http://" in page.split("<script id=\"scene\"")[0].replace("http://www.w3.org", ""):
        problems.append("the page fetches something")
    return report("2. the theme's fonts inlined into the page", problems, [f"page {len(page) // 1024} KB"])


SCRIPT = """() => ({theme: document.documentElement.dataset.theme, bg: getComputedStyle(document.body).backgroundColor,
  layers: document.querySelectorAll('#bg > *').length, stars: document.querySelectorAll('#bg circle').length,
  wires: (r => [r.width, r.height, getComputedStyle(document.getElementById('wires')).position])(document.getElementById('wires').getBoundingClientRect()),
  subtitle: document.getElementById('subtitle').textContent, words: document.querySelectorAll('#title .word').length,
  glow: document.querySelector('#bg .glow') ? document.querySelector('#bg .glow').style.left : null})"""


def case_pages():
    from playwright.sync_api import sync_playwright
    problems, notes, got = [], [], {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for channel in ("electronics", "physics", "math", "economics"):
                path = os.path.join(folder, f"{channel}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(CIRCUIT, 4, 4, style=renderer.channel_style(f"breeze_({channel})"),
                                                                   scene_number=3)))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                page.evaluate("window.seek(0.5)")
                first = page.evaluate(SCRIPT)
                page.evaluate("window.seek(3.5)")
                got[channel] = page.evaluate(SCRIPT), first["glow"]
        finally:
            browser.close()
    expect = {"electronics": "dark", "physics": "dark", "math": "light", "economics": "dark"}
    for channel, (g, first_glow) in got.items():
        if g["theme"] != expect[channel]:
            problems.append(f"{channel}: theme {g['theme']}")
        if g["wires"] != [renderer.WIDTH, renderer.HEIGHT, "absolute"]:
            problems.append(f"{channel}: the wires' layer is {g['wires']}, not over the whole stage")
        if g["layers"] < 3 or g["glow"] == first_glow:
            problems.append(f"{channel}: background {g['layers']} layers, glow {first_glow} -> {g['glow']} (not moving)")
    if got["physics"][0]["stars"] < 100:
        problems.append(f"physics: {got['physics'][0]['stars']} stars")
    if not got["electronics"][0]["subtitle"].startswith("// étape 03 : "):
        problems.append(f"electronics subtitle {got['electronics'][0]['subtitle']!r}")
    if got["math"][0]["words"] != 2:
        problems.append(f"math title: {got['math'][0]['words']} words, 2 expected")
    notes += [f"{c}: {g['theme']}, {g['layers']} background layers" for c, (g, _) in got.items()]
    return report("3. agent010 pages: dark / light, background moving, wires over the stage, title styles", problems, notes)


SKY = {"scene_id": "1", "text_overlay": {"title": "Orbite"}, "connections": [], "actions": [],
       "entities": [{"id": "ax", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}},
                    {"id": "line", "type": "CURVE_PLOT", "position": [0, 0, 0], "initial_state": {"func": "0.3*x + 1", "axes": "ax"}},
                    {"id": "earth", "type": "OBJECT", "position": [0, 0, 0],
                     "initial_state": {"icon": "earth", "label": "Terre", "anchor": {"axes": "ax", "x": 0, "y": 0}}},
                    {"id": "moon", "type": "OBJECT", "position": [4, 2, 0], "initial_state": {"icon": "moon", "label": "Lune"}},
                    {"id": "sat", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "Satellite", "anchor": {"axes": "ax", "x": 3, "y": 1}}}]}


def case_effects():
    from playwright.sync_api import sync_playwright
    script = """() => ({spheres: [...document.querySelectorAll('.sphere')].map(n => n.className),
      cards: document.querySelectorAll('.card.icon').length, halo: !!E.line.curveHalo, area: !!E.line.curveArea,
      areaOpacity: E.line.curveArea ? E.line.curveArea.style.opacity : null, disc: E.sat.shape.style.boxShadow.includes('22px')})"""
    got = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for channel in ("physics", "economics", "math"):
                path = os.path.join(folder, f"{channel}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(SKY, 4, 4, style=renderer.channel_style(f"breeze_({channel})"))))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                page.evaluate("window.seek(3.5)")
                got[channel] = page.evaluate(script)
        finally:
            browser.close()
    problems = []
    if sorted(got["physics"]["spheres"]) != ["sphere earth", "sphere moon"] or got["physics"]["cards"]:
        problems.append(f"spheres: {got['physics']}")
    if not got["physics"]["halo"] or got["physics"]["area"] or not got["physics"]["disc"]:
        problems.append(f"space: halo {got['physics']['halo']}, area {got['physics']['area']}, lit disc {got['physics']['disc']}")
    if not got["economics"]["area"] or float(got["economics"]["areaOpacity"]) < 0.9:
        problems.append(f"data: area {got['economics']['area']} opacity {got['economics']['areaOpacity']}")
    if got["math"]["halo"] or got["math"]["area"] or got["math"]["disc"]:
        problems.append(f"notebook (light) got dark effects: {got['math']}")
    return report("4. spheres; halos and lit discs on dark themes; the filled area on data", problems,
                  [f"{c}: {g}" for c, g in got.items()])


def case_meaning():
    from playwright.sync_api import sync_playwright
    from pydantic import ValidationError
    from models.visual_brief_schema import SceneVisualBrief, emphasis_problem
    problems = []
    brief = {"scene_id": "1", "text_overlay": {"title": "Contradiction"}, "connections": [],
             "entities": [{"id": "f", "type": "TEX_FORMULA", "position": [-3, 0, 0], "initial_state": {"latex": "d > 0", "tone": "wrong"}},
                          {"id": "g", "type": "TEX_FORMULA", "position": [3, 0, 0], "initial_state": {"latex": "x = 1", "tone": "result"}}],
             "actions": [{"at": 1.0, "action": "emphasize", "target": "f", "effect": "shake"},
                         {"at": 2.5, "action": "emphasize", "target": "g", "effect": "pulse"}]}
    SceneVisualBrief.model_validate(brief)
    for label, entity in {"a tone on a lamp": {"id": "l", "type": "LAMP", "position": [0, 0, 0], "initial_state": {"tone": "wrong"}},
                          "an unknown tone": {"id": "h", "type": "TEX_FORMULA", "position": [0, 2, 0], "initial_state": {"latex": "a", "tone": "pink"}}}.items():
        try:
            SceneVisualBrief.model_validate({**brief, "entities": brief["entities"] + [entity]})
            problems.append(f"accepted: {label}")
        except ValidationError:
            pass
    if not emphasis_problem({"target": "f", "effect": "spin"}, {"f"}) or emphasis_problem({"target": "f", "effect": "pulse"}, {"f"}):
        problems.append("emphasize not checked")
    script = """() => ({shake: E.f.shape.style.transform, pulse: E.g.shape.style.transform,
                       border: getComputedStyle(E.f.shape).borderTopColor, tone: E.f.shape.classList.contains('toned')})"""
    got = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            path = os.path.join(folder, "m.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(brief, 5, 5, style=renderer.channel_style("breeze_(math)"))))
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in (1.2, 2.8, 4.5):
                page.evaluate(f"window.seek({t})")
                got[t] = page.evaluate(script)
        finally:
            browser.close()
    if not got[1.2]["tone"] or got[1.2]["border"] != "rgb(239, 68, 68)":
        problems.append(f"the wrong formula is not red: {got[1.2]}")
    if "translateX" not in got[1.2]["shake"] or "scale" not in got[2.8]["pulse"] or got[4.5]["shake"] or got[4.5]["pulse"]:
        problems.append(f"shake / pulse: {got}")
    return report("5. tones on formulas and badges; shake and pulse", problems, [str(got[1.2]), str(got[2.8])])


results = [case_styles(), case_fonts()]
try:
    import playwright  # noqa: F401
    results += [case_pages(), case_effects(), case_meaning()]
except ImportError:
    print("FAIL  3. Playwright is not installed (pip install playwright && playwright install chromium)")
    results.append(False)
sys.exit(0 if all(results) else 1)
