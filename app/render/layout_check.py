"""
What the renderer would still find wrong in a storyboard's layout, measured before rendering: each
scene's page is built as agent010 builds it (app/agent/agent010_html_renderer.page_data, the
channel's theme, the subtitles' room at the bottom) and loaded in a headless Chromium, which lays it
out and lists what still overlaps, enters the title zone, leaves the frame or points at nothing
(window.layoutConflicts, the same list render_manifest.json reports). agent004 sends these back to
the LLM with its other advisory problems, so they are fixed in the storyboard, not found in the video.
No voice: the actions are spread over the planned durations; the positions measured are the rest
positions, as the renderer's check.
"""

import os
import tempfile

MAX_PER_SCENE = 4         # conflicts reported per scene: the first ones, the LLM fixes those first


def advice(conflict):
    """What to tell the LLM about one measured conflict."""
    if " overlaps " in conflict:
        return f"{conflict} on screen: move them apart (positions), or keep fewer things in the scene"
    if conflict.endswith("leaves the frame"):
        return f"{conflict}: bring it inside the frame"
    if conflict.endswith("enters the title zone"):
        return f"{conflict}: place it lower, under the titles"
    if conflict.endswith("points at nothing"):
        return f"{conflict}: give the badge a \"target\" that is drawn"
    return conflict


def measured_conflicts(order, briefs, templates, titles, durations, style, subtitles=True):
    """["scene <id>: <what> ..."] for the scenes `order` ({scene_id: SceneVisualBrief} `briefs`,
    {scene_id: layout template} `templates`, {scene_id: panel titles or None} `titles`, planned
    {scene_id: seconds} `durations`). Raises if Playwright or Chromium is missing (as agent010)."""
    from playwright.sync_api import sync_playwright
    from app.agent import agent010_html_renderer as renderer
    found = []
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            for number, scene_id in enumerate(order, start=1):
                duration = float(durations.get(scene_id) or 15)
                data = renderer.page_data(briefs[scene_id].model_dump(mode="json"), duration, duration, None,
                                          templates.get(scene_id) or renderer.DEFAULT_LAYOUT, titles.get(scene_id),
                                          style, number)
                if subtitles:          # their room at the bottom, as in the video
                    data["subtitles"] = [{"at": 0, "end": duration, "text": "…"}]
                path = os.path.join(folder, f"scene_{number:03d}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(data))
                renderer.open_scene(page, path)
                conflicts = page.evaluate("window.layoutConflicts || []")
                found += [f"scene {scene_id}: measured on the page: {advice(c)}" for c in conflicts[:MAX_PER_SCENE]]
        finally:
            browser.close()
    return found
