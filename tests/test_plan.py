"""
Check the plan announced after the hook and the follow-ups of the 4-channel run of 2026-11-02, offline
but for the browser:
  1. agent010 builds the plan from the scenes' titles: its narration ("Au programme. D'abord, ...
     Et enfin, ..."), its page (one line per chapter, appearing in turn) and, on the scenes after it,
     where they are in the plan ("02 / 05"); agent007's YouTube chapters use the rendered start times
     (the plan included)
  2. the voice says the maths written in the narration: "t_n", "10^{-n}", < ≤ > ≥, a truncation "0,999…9"
  3. a title or a label written in LaTeX shows "10⁻ⁿ", "tₙ"; an identifier is left alone
  4. agent004: a comparison with an empty panel or a circuit wired across the panels goes back to
     "circuit"; a curve too small for its graph and a scene of icons only (with numbers in its
     narration) are sent back to the LLM
Prints PASS or FAIL per case. Case 1 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_plan.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as agent004        # noqa: E402
from app.agent import agent007_metadatagenerator as agent007           # noqa: E402
from app.agent import agent010_html_renderer as renderer               # noqa: E402
from app.tts_manager import normalize_text_for_tts                     # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def scene(number, title):
    return {"scene_id": number, "visual_brief": {"scene_id": str(number), "text_overlay": {"title": title},
                                                 "entities": [], "actions": [], "connections": []}}


STORYBOARD = {"scenes": [scene(1, "Que signifie 9 V ?"), scene(2, "La tension est une différence"),
                         scene(3, "L'écart vaut 10^{-n}"), scene(4, "Pourquoi pas zéro ?")]}


def case_plan():
    from playwright.sync_api import sync_playwright
    chapters = renderer.plan_chapters(STORYBOARD)
    text = renderer.plan_narration(chapters)
    problems = []
    if [n for n, _ in chapters] != [2, 3, 4] or chapters[1][1] != "L'écart vaut 10⁻ⁿ":
        problems.append(f"chapters {chapters}")
    if not (text.startswith("Au programme. D'abord, La tension") and "Et enfin, Pourquoi pas zéro ?" in text):
        problems.append(f"narration {text!r}")
    if renderer.plan_chapters({"scenes": STORYBOARD["scenes"][:2]}):
        problems.append("a plan for a video of two scenes")
    data = renderer.plan_page_data(chapters, None, 9.0, 9.4, None)
    times = [item["at"] for item in data["plan"]]
    if times != sorted(times) or times[0] <= 0:
        problems.append(f"chapter times {times}")
    content = renderer.page_data(STORYBOARD["scenes"][2]["visual_brief"], 6, None)
    content["progress"] = {"current": 2, "total": 3}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            shown = {}
            for name, page_data, t in (("plan_mid", data, (times[0] + times[1]) / 2 + 0.6), ("plan_end", data, 9.3),
                                       ("content", content, 5)):
                path = os.path.join(folder, name + ".html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(page_data))
                renderer.open_scene(page, path)
                page.evaluate(f"window.seek({t})")
                shown[name] = page.evaluate("""() => ({
                  rows: [...document.querySelectorAll('.plan-item')].map(r => [+getComputedStyle(r).opacity, r.classList.contains('now'), r.textContent]),
                  progress: (document.querySelector('#progress .count') || {}).textContent || null,
                  subtitle: document.getElementById('subtitle').textContent})""")
        finally:
            browser.close()
    mid, end = shown["plan_mid"]["rows"], shown["plan_end"]["rows"]
    if len(end) != 3 or not all(r[0] > 0.99 for r in end) or not end[2][1] or end[0][1]:
        problems.append(f"plan at its end: {end}")
    if not (mid[0][0] > 0.99 and mid[2][0] < 0.01 and mid[0][1]):
        problems.append(f"plan half way: {mid}")
    if "02" not in end[0][2] or "étape" in shown["plan_end"]["subtitle"]:
        problems.append(f"numbers / subtitle: {end[0][2]!r}, {shown['plan_end']['subtitle']!r}")
    if shown["content"]["progress"] != "02 / 03":
        problems.append(f"progress {shown['content']['progress']!r}")
    rendered = [{"scene_id": 1, "start_sec": 0}, {"scene_id": "plan", "title": "Au programme", "start_sec": 12.4},
                {"scene_id": 2, "start_sec": 21}, {"scene_id": 3, "start_sec": 65.2}]
    chapters_yt = agent007.build_chapters([{}, {}, {}], ["Intro", "Tension", "Écart"], rendered)
    if chapters_yt != ["0:00 Intro", "0:12 Au programme", "0:21 Tension", "1:05 Écart"]:
        problems.append(f"YouTube chapters {chapters_yt}")
    return report("1. the plan after the hook, the progress on each scene, the YouTube chapters", problems,
                  [text, f"chapters at {times} s"])


def case_voice():
    expected = {
        "notons t_n = 0,999…9.": "notons t indice enne égal 0 virgule neuf neuf neuf, et ainsi de suite jusqu'à un dernier neuf.",
        "1 − t_n = 10^{-n}": "1 moins t indice enne égal 10 puissance moins enne",
        "0,999… < y < 1": "0 virgule neuf neuf neuf à l'infini inférieur à y inférieur à 1",
        "t_n ≤ 1 et x ≥ 0": "t indice enne inférieur ou égal à 1 et ixe supérieur ou égal à 0",
        "le fichier snake_case": "le fichier snake_case",
    }
    problems = [f"{text!r} -> {normalize_text_for_tts(text)!r}" for text, said in expected.items()
                if normalize_text_for_tts(text) != said]
    return report("2. the voice says indices, powers, comparisons and truncations", problems)


def case_display():
    expected = {"1 − t_n = 10^{-n}": "1 − tₙ = 10⁻ⁿ", "x^2": "x²", "body_0999": "body_0999", "U_{AB}": "U_{AB}"}
    problems = [f"{text!r} -> {renderer.plain_math(text)!r}" for text, shown in expected.items()
                if renderer.plain_math(text) != shown]
    return report("3. LaTeX in a title or a label is shown with exponents and indices", problems)


def brief(entities, connections=(), number=1):
    return SceneVisualBrief.model_validate({"scene_id": str(number), "text_overlay": {"title": "t"}, "entities": entities,
                                            "connections": list(connections), "actions": []})


def case_agent004():
    icon = lambda i, x: {"id": i, "type": "CART", "position": [x, 0, 0], "initial_state": {"label": i}}
    battery = {"id": "bat", "type": "BATTERY", "position": [-3, 0, 0], "initial_state": {}}
    lamp = {"id": "lamp", "type": "LAMP", "position": [3, 0, 0], "initial_state": {}}
    wired = brief([battery, lamp], [{"source_id": "bat", "source_port": "positive", "target_id": "lamp", "target_port": "left"}])
    empty = brief([icon("a", 3), icon("b", 4)], number=2)
    fine = brief([icon("a", -3), icon("b", 3)], number=3)
    briefs = {"1": wired, "2": empty, "3": fine}
    eligible = {i: ["circuit", "comparison"] for i in briefs}
    templates, forced = agent004.force_layouts(["1", "2", "3"], {"1": "comparison", "2": "comparison", "3": "circuit"},
                                               eligible, set(), briefs)
    problems = []
    if templates != {"1": "circuit", "2": "circuit", "3": "comparison"}:
        problems.append(f"templates {templates} ({forced})")
    axes = {"id": "ax", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-5, 5, 1]}}
    throw = {"id": "slow", "type": "CURVE_PLOT", "position": [0, 0, 0],
             "initial_state": {"func": "3 - x**2", "x_range": [0, 0.5], "axes": "ax", "label": "Lancer lent"}}
    tiny = [e for e in agent004.coherence_problems(brief([axes, throw]), "un lancer", 10) if "too small" in e]
    icons = [e for e in agent004.coherence_problems(brief([icon("a", 0)]), "une hausse de 2 %", 10) if "only icons" in e]
    words_only = [e for e in agent004.coherence_problems(brief([icon("a", 0)]), "une hausse générale", 10) if "only icons" in e]
    if not tiny or not icons or words_only:
        problems.append(f"advisories: tiny curve {tiny}, icons {icons}, without numbers {words_only}")
    return report("4. agent004: broken comparisons go back to circuit; tiny curves and icon-only scenes are reported",
                  problems, forced + tiny + icons)


results = [case_voice(), case_display(), case_agent004()]
try:
    import playwright  # noqa: F401
    results.insert(0, case_plan())
except ImportError:
    print("FAIL  1. Playwright is not installed (pip install playwright && playwright install chromium)")
    results.append(False)
sys.exit(0 if all(results) else 1)
