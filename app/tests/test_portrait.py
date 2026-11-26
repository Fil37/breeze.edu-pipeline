"""
Check the vertical (TikTok, 1080 x 1920) video, option 3 of 2026-11-26: each scene drawn a second time for the phone
(the user: option 2, the YouTube picture shrunk into a tall frame, "n'a rien changé" on the phone).
  1. a portrait page: laid out at the video's size, then turned 1080 x 1920; the drawing enlarged to the phone's width
     (never cut), the instrument under it with its probe's cords still on their pins, the logo top right at a fixed size
     (the user's choice), the title clear of it
  2. the other pages in portrait: a comparison and the plan inside the frame
  3. without "portrait" nothing changes: the page and its layout exactly the YouTube one
  4. the wiring: render_video makes the vertical file only when asked (settings vertical.enabled), its failure never
     costs the horizontal video; the skill declared
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_portrait.py
"""

import inspect
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer             # noqa: E402
from test_opamp import circuit                                        # noqa: E402

MARK = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
MEASURE = """() => {
  const rect = n => { const q = n.getBoundingClientRect(); return {l: q.left, t: q.top, r: q.right, b: q.bottom}; };
  const entities = [...document.querySelectorAll('#stage .entity')].map(rect).filter(q => q.r - q.l > 1);
  const mark = document.getElementById('watermark'), title = document.getElementById('title');
  const panels = [...document.querySelectorAll('.comparison-panel')].map(rect);
  const plan = [...document.querySelectorAll('.plan-item')].map(rect);
  return {width: document.body.offsetWidth, height: document.body.offsetHeight, scale: window.portraitScale || null,
          entities, panels, plan, conflicts: window.layoutConflicts || [],
          mark: mark ? {...rect(mark), inDrawing: !!mark.closest('#portrait')} : null,
          title: title ? rect(title) : null};
}"""


def report(label, problems, notes=()):
    print(("PASS" if not problems else "FAIL") + f"  {label}")
    for line in list(problems) + list(notes):
        print(f"        - {line}")
    return not problems


def open_pages(pages, viewport):
    from playwright.sync_api import sync_playwright
    found = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport=viewport)
            for name, data in pages.items():
                path = os.path.join(folder, name + ".html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(data))
                renderer.open_scene(page, path)
                found[name] = page.evaluate(MEASURE)
        finally:
            browser.close()
    return found


def scene(brief, layout="circuit", portrait=True):
    data = renderer.page_data(brief, 6, None, None, layout)
    data["watermark"] = MARK
    data["subtitles"] = [{"at": 0, "end": 6, "text": "Ce retour négatif force la sortie à recopier l'entrée."}]
    if portrait:
        data["portrait"] = renderer.PORTRAIT
    return data


def inside(box, frame, margin=2):
    return (box["l"] >= frame["l"] - margin and box["r"] <= frame["r"] + margin
            and box["t"] >= frame["t"] - margin and box["b"] <= frame["b"] + margin)


def case_circuit(found):
    problems = []
    tall, wide = found["tall"], found["wide"]
    if (tall["width"], tall["height"]) != (1080, 1920):
        problems.append(f"the page is {tall['width']} x {tall['height']}, not 1080 x 1920")
    if not tall["scale"] or tall["scale"] < 0.6:
        problems.append(f"the drawing not enlarged for the phone: scale {tall['scale']}")
    frame = {"l": 0, "r": 1080, "t": 0, "b": 1920 - 390}           # above the subtitles and TikTok's caption
    cut = [q for q in tall["entities"] if not inside(q, frame)]
    if cut:
        problems.append(f"{len(cut)} piece(s) of the drawing out of the frame: {cut[:2]}")
    mark = tall["mark"]
    if not mark or mark["inDrawing"] or mark["r"] < 1000 or mark["t"] > 260 or mark["r"] - mark["l"] > 100:
        problems.append(f"the logo is not top right at a fixed size, out of the drawing: {mark}")
    if len(tall["conflicts"]) > len(wide["conflicts"]):
        problems.append(f"more layout conflicts than on YouTube: {tall['conflicts']} vs {wide['conflicts']}")
    return report("1. a circuit in portrait: 1080 x 1920, enlarged, nothing cut, logo top right, no new conflict",
                  problems, [f"scale {tall['scale']:.2f}"] if tall["scale"] else [])


def case_others(found):
    problems = []
    compared = found["compared"]
    frame = {"l": 0, "r": 1080, "t": 0, "b": 1920 - 390}
    if len(compared["panels"]) != 2 or not all(inside(q, frame) for q in compared["panels"]):
        problems.append(f"the comparison's panels not inside the frame: {compared['panels']}")
    plan = found["plan"]
    if not plan["plan"] or not all(inside(q, {"l": 0, "r": 1080, "t": 0, "b": 1920}) for q in plan["plan"]):
        problems.append(f"the plan's chapters not inside the frame: {plan['plan'][:2]}")
    return report("2. a comparison and the plan in portrait: inside the frame", problems)


def case_unchanged(found):
    problems = []
    wide = found["wide"]
    if (wide["width"], wide["height"]) != (renderer.WIDTH, renderer.HEIGHT) or wide["scale"]:
        problems.append(f"without portrait the page is {wide['width']} x {wide['height']} (scale {wide['scale']})")
    if wide["mark"] and wide["mark"]["r"] < 1800:
        problems.append(f"without portrait the logo moved: {wide['mark']}")
    data = scene(circuit("follower", dual=False, measure=2))
    if "1080px; height:1920px" in renderer.build_page(data):
        problems.append("a portrait page is not laid out at the video's size first")
    return report("3. without portrait nothing changes (the YouTube page)", problems)


def case_wiring():
    problems = []
    source = inspect.getsource(renderer.render_video)
    if "portrait_path" not in inspect.signature(renderer.render_video).parameters:
        problems.append("render_video has no portrait_path")
    for needle in ("vertical version not made", "if portrait_ok:"):
        if needle not in source:
            problems.append(f"render_video: {needle!r} missing (a vertical failure must only be a warning)")
    run_source = inspect.getsource(renderer.run)
    if '(settings.get("vertical") or {}).get("enabled")' not in run_source:
        problems.append("run() does not ask for the vertical video only when vertical.enabled")
    if 'os.remove(vertical_path)' not in run_source:
        problems.append("run() may leave last run's vertical video beside today's")
    skill = {s["skill_id"]: s for s in renderer.SKILLS}.get("vertical_format")
    if not skill or skill["version"] != "2.0":
        problems.append(f"skill vertical_format 2.0 not declared: {skill}")
    return report("4. the wiring: only when enabled, never costing the horizontal video, skill declared", problems)


if __name__ == "__main__":
    follower = circuit("follower", dual=False, measure=2)
    compared = {"scene_id": "1", "text_overlay": {"title": "Masse ou poids ?"}, "connections": [], "actions": [],
                "entities": [{"id": "scale", "type": "SCALE", "position": [-3.5, -1.3, 0], "initial_state": {"label": "Balance"}},
                             {"id": "formula", "type": "TEX_FORMULA", "position": [3.5, 0, 0], "initial_state": {"latex": "P = m g"}}]}
    plan = {"items": [(n, f"Mélanger plusieurs tensions avec des poids {n}", None) for n in range(2, 8)],
            "narration": "x", "source": "test"}
    plan_data = renderer.plan_page_data(plan, [], 4, 5, None)
    plan_data["portrait"] = renderer.PORTRAIT
    found = open_pages({"tall": scene(follower), "compared": scene(compared, "comparison"), "plan": plan_data},
                       renderer.PORTRAIT)
    found.update(open_pages({"wide": scene(follower, portrait=False)}, {"width": renderer.WIDTH, "height": renderer.HEIGHT}))
    results = [case_circuit(found), case_others(found), case_unchanged(found), case_wiring()]
    sys.exit(0 if all(results) else 1)
