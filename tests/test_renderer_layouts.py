"""
Check agent010's layout templates on a mini storyboard of 3 scenes, one per template, by the HTML
it generates (no browser, no voice, no other agent):
  1. no "layout_template" at all (an older storyboard) -> PAGE_CIRCUIT: data-layout="circuit",
     neither the comparison panels nor the full-screen backdrop
  2. "comparison"          -> PAGE_COMPARISON: two "comparison-panel" (A and B), panel titles passed on
  3. "analogy_fullscreen"  -> PAGE_ANALOGY_FULLSCREEN: the "fullscreen-svg" backdrop, no panels
Each scene goes through the renderer's own path: scene_layout(scene) -> page_data -> build_page.
Prints PASS or FAIL per scene. With --screenshots (needs Playwright + Chromium), also saves one
PNG per scene in media/test_renderer_layouts/ to look at.

  .venv/bin/python tests/test_renderer_layouts.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent010_html_renderer as renderer   # noqa: E402

OUT_DIR = os.path.join(ROOT, "media", "test_renderer_layouts")

circuit = {"scene_id": "1", "renderer": "manim", "visual_brief": {     # no layout_template: an older storyboard
    "scene_id": "1", "text_overlay": {"title": "Le circuit"},
    "entities": [{"id": "bat", "type": "BATTERY", "position": "LEFT", "initial_state": {"label": "Pile"}},
                 {"id": "lamp", "type": "LAMP", "position": "RIGHT", "initial_state": {"label": "Lampe"}}],
    "connections": [{"source_id": "bat", "source_port": "positive", "target_id": "lamp", "target_port": "left_terminal"},
                    {"source_id": "lamp", "source_port": "right_terminal", "target_id": "bat", "target_port": "negative"}],
    "actions": [{"at": 1.0, "action": "start_flow", "path": ["bat", "lamp", "bat"]},
                {"at": 1.5, "action": "set_state", "target": "lamp", "state": {"on": True}}]}}
comparison = {"scene_id": "2", "renderer": "manim", "layout_template": "comparison",
              "panel_titles": ["Ce qu'on croit", "Ce qui est vrai"], "visual_brief": {
    "scene_id": "2", "text_overlay": {"title": "Tension ou courant ?"},
    "entities": [{"id": "idea", "type": "PIPE_VALVE", "position": [-3.5, 0, 0], "initial_state": {"label": "La tension circule"}},
                 {"id": "fact", "type": "GAUGE", "position": [3.5, 0, 0], "initial_state": {"label": "Le courant circule"}}],
    "connections": [], "actions": [{"at": 0.5, "action": "spawn", "target": "idea"},
                                   {"at": 2.0, "action": "spawn", "target": "fact"}]}}
analogy = {"scene_id": "3", "renderer": "manim", "layout_template": "analogy_fullscreen", "visual_brief": {
    "scene_id": "3", "text_overlay": {"title": "Le château d'eau"},
    "entities": [{"id": "high", "type": "WATER_TANK", "position": [-3.5, 0.6, 0], "initial_state": {"label": "Haut", "level": 0.8}},
                 {"id": "pipe", "type": "PIPE_VALVE", "position": [0, -0.6, 0], "initial_state": {"label": "Conduite"}},
                 {"id": "low", "type": "WATER_TANK", "position": [3.5, -1.6, 0], "initial_state": {"label": "Bas", "level": 0.2}}],
    "connections": [{"source_id": "high", "source_port": "right", "target_id": "pipe", "target_port": "left"},
                    {"source_id": "pipe", "source_port": "right", "target_id": "low", "target_port": "left"}],
    "actions": [{"at": 1.0, "action": "start_flow", "path": ["high", "pipe", "low"]}]}}


def html_for(scene):
    """The scene's page, by the renderer's own path (as render_video does)."""
    layout, _note = renderer.scene_layout(scene)
    return layout, renderer.build_page(renderer.page_data(scene["visual_brief"], 8.0, 8, None, layout,
                                                          scene.get("panel_titles")))


def page_data_of(html):
    start = html.index('<script id="scene" type="application/json">') + len('<script id="scene" type="application/json">')
    return json.loads(html[start:html.index("</script>", start)].replace("<\\/", "</"))


CASES = [
    ("circuit (no layout_template: fallback)", circuit, "circuit",
     lambda h: h.count('class="comparison-panel"') == 0 and 'class="fullscreen-svg"' not in h),
    ("comparison", comparison, "comparison",
     lambda h: h.count('class="comparison-panel"') == 2 and 'data-panel="A"' in h and 'data-panel="B"' in h
     and 'class="fullscreen-svg"' not in h and page_data_of(h)["panels"] == ["Ce qu'on croit", "Ce qui est vrai"]),
    ("analogy_fullscreen", analogy, "analogy_fullscreen",
     lambda h: 'class="fullscreen-svg"' in h and 'class="comparison-panel"' not in h),
]

failures, pages = 0, []
for label, scene, expected, markers in CASES:
    layout, html = html_for(scene)
    problems = []
    if layout != expected:
        problems.append(f"layout {layout!r}, expected {expected!r}")
    if f'data-layout="{expected}"' not in html:
        problems.append(f'no data-layout="{expected}" on the stage')
    if not markers(html):
        problems.append("the template's markers are missing, or another template's are there")
    if "@@" in html.split('<script id="scene"')[0]:
        problems.append("a @@MARKER@@ was left unfilled")
    failures += bool(problems)
    pages.append((scene["scene_id"], html))
    print(f'{"FAIL" if problems else "PASS"}  scene {scene["scene_id"]} {label}: layout={layout!r}'
          + "".join(f"\n      {p}" for p in problems))

if "--screenshots" in sys.argv:
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as playwright:
        page = playwright.chromium.launch().new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
        for scene_id, html in pages:
            path = os.path.join(OUT_DIR, f"scene_{scene_id}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            renderer.open_scene(page, path)
            page.evaluate("window.seek(7.5)")
            page.screenshot(path=path.replace(".html", ".png"))
            print(f"Image : {path.replace('.html', '.png')}  conflicts: {page.evaluate('window.layoutConflicts')}")
sys.exit(1 if failures else 0)
