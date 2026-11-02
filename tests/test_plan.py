"""
Check the plan announced after the hook and the follow-ups of the 4-channel run of 2026-11-02, offline
but for the browser:
  1. without a plan from agent003, agent010 builds it from the scenes' titles: its narration ("Au
     programme. D'abord, ... Et enfin, ..."), its page (one line per chapter, appearing in turn) and, on the scenes after it,
     where they are in the plan ("02 / 05"); agent007's YouTube chapters use the rendered start times
     (the plan included)
  2. the voice says the maths written in the narration: "t_n", "10^{-n}", < ≤ > ≥, a truncation "0,999…9"
  3. a title or a label written in LaTeX shows "10⁻ⁿ", "tₙ"; an identifier is left alone
  4. agent004: a comparison with an empty panel or a circuit wired across the panels goes back to
     "circuit"; a curve too small for its graph and a scene of icons only (with numbers in its
     narration) are sent back to the LLM
  5. agent003's plan (a spoken narration, what each later scene shows, the words announcing it) is
     kept when it matches the scenes and shown line by line on those words; one that does not match
     falls back to the titles
  6. agent001 checks the topic against the channel's topics already made: a repeat (same key words,
     or the LLM says so) is sent back with the reason; every answer a repeat is critical; an imposed
     topic that repeats one is kept and reported (not_healthy)
  7. agent010 page: a counter shows the decimals of its value (0,96, not 1,0); a scene drawn in a corner
     is moved to the middle of the frame (a comparison only vertically: its panels go by x); the last
     scene of a video fades to the background
  8. agent004 reports a disc (BODY) that neither moves nor sits on a graph
Prints PASS or FAIL per case. Cases 1 and 7 need Playwright + Chromium (as agent010).

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
    plan = renderer.video_plan({"scenes": []}, STORYBOARD)       # no plan from agent003: from the titles
    text = plan["narration"]
    problems = []
    if [n for n, _ in chapters] != [2, 3, 4] or chapters[1][1] != "L'écart vaut 10⁻ⁿ":
        problems.append(f"chapters {chapters}")
    if not (text.startswith("Au programme. D'abord, La tension") and "Et enfin, Pourquoi pas zéro ?" in text):
        problems.append(f"narration {text!r}")
    if renderer.plan_chapters({"scenes": STORYBOARD["scenes"][:2]}):
        problems.append("a plan for a video of two scenes")
    if plan["source"] != "titles":
        problems.append(f"plan source {plan['source']!r}")
    data = renderer.plan_page_data(plan, None, 9.0, 9.4, None)
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


def case_script_plan():
    from app.agent import agent003_scriptwriter as agent003
    scenes = [{"scene_id": i} for i in (1, 2, 3, 4)]
    answer = {"narration": "On va voir pourquoi la tension existe sans courant, puis comment le courant circule, "
                           "et enfin ce que mesure chaque appareil.",
              "parts": [{"scene_id": 2, "text": "Une tension sans aucun courant.", "cue": "pourquoi la tension"},
                        {"scene_id": 3, "text": "Comment le courant circule", "cue": "comment le courant"},
                        {"scene_id": 4, "text": "Ce que mesure chaque appareil", "cue": "ce que mesure"}]}
    checked = agent003.checked_plan(answer, scenes)
    problems = []
    if not checked or checked["parts"][0]["text"] != "Une tension sans aucun courant":
        problems.append(f"agent003 kept {checked}")
    if agent003.checked_plan({**answer, "parts": answer["parts"][:2]}, scenes) is not None:
        problems.append("agent003 kept a plan missing a scene")
    plan = renderer.video_plan({"plan": checked}, STORYBOARD)
    spoken = [(0.3 * i, w) for i, w in enumerate(answer["narration"].split())]
    times = renderer.plan_times(plan["items"], spoken, 9.0)
    said = {w: 0.3 * i for i, w in reversed(list(enumerate(answer["narration"].split())))}
    if plan["source"] != "script" or [t for _, t, _ in plan["items"]][1] != "Comment le courant circule":
        problems.append(f"agent010 plan {plan}")
    if [round(t, 2) for t in times] != [round(said["pourquoi"], 2), round(said["comment"], 2), round(said["ce"], 2)]:
        problems.append(f"lines at {times}")
    broken = {"plan": {**checked, "parts": checked["parts"][::-1]}}
    if renderer.video_plan(broken, STORYBOARD)["source"] != "titles":
        problems.append("a plan in the wrong order was used")
    return report("5. agent003's plan is said naturally and each line appears on its words", problems,
                  [f"lines at {[round(t, 1) for t in times]} s"])


def run_agent001(answers, past, topic=None):
    """agent001.run with its LLM answering `answers` in turn and `past` as the topics already made."""
    import json
    from app import provenance
    from app.agent import agent001_conceptresearcher as agent001
    calls, saved = [], {}
    stubs = {"llm_call": lambda prompt: calls.append(prompt) or json.dumps(answers[len(calls) - 1]),
             "past_topics": lambda channel_id: past, "channel_dir": lambda channel_id: "/nonexistent",
             "save_json": lambda path, data: saved.update(data),
             "finish": lambda channel_id, agent, stage, status, path, data=None, error=None: {"status": status, "error": error}}
    originals = {name: getattr(agent001, name) for name in stubs}
    prov = (provenance.check_inputs, provenance.register_artifact)
    old_topic = os.environ.pop(agent001.TOPIC_ENV, None)
    try:
        for name, stub in stubs.items():
            setattr(agent001, name, stub)
        provenance.check_inputs, provenance.register_artifact = (lambda *a, **k: "run"), (lambda *a, **k: None)
        if topic:
            os.environ[agent001.TOPIC_ENV] = topic
        stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
        try:
            result = agent001.run("breeze_(physics)", {}, [{"channel_id": "breeze_(physics)", "name": "Physique",
                                  "domain": "physics_math", "target_age_band": "14-18", "persona": "lycéen"}])
        finally:
            sys.stderr.close()
            sys.stderr = stderr
    finally:
        for name, original in originals.items():
            setattr(agent001, name, original)
        provenance.check_inputs, provenance.register_artifact = prov
        os.environ.pop(agent001.TOPIC_ENV, None)
        if old_topic is not None:
            os.environ[agent001.TOPIC_ENV] = old_topic
    return result, saved, calls


def case_novelty():
    past = ["Une orbite est une chute libre permanente", "Les saisons viennent de l'inclinaison de l'axe terrestre"]
    sources = [{"title": "a", "url": "https://a.org"}, {"title": "b", "url": "https://b.org"}]
    same_words = {"concept": "L'orbite : une chute libre permanente autour de la Terre", "sources": sources}
    other_angle = {"concept": "L'impesanteur des astronautes dans l'ISS", "sources": sources}
    new = {"concept": "La poussée d'Archimède ne dépend pas de la profondeur", "sources": sources}
    problems = []
    result, saved, calls = run_agent001([same_words, other_angle, {"duplicate_of": past[0], "reason": "même idée"},
                                         new, {"duplicate_of": None, "reason": "nouveau"}], past)
    novelty = saved.get("novelty", {})
    if result["status"] != "healthy" or saved.get("concept") != new["concept"] or novelty.get("attempts") != 3 \
            or [r["by"] for r in novelty.get("rejected", [])] != ["words", "llm"]:
        problems.append(f"repeats sent back: {result}, {novelty}")
    if "ALREADY made a video" not in calls[0] or past[0] not in calls[0] or "Already refused" not in calls[3]:
        problems.append("the prompts do not list the topics made / refused")
    result, saved, _ = run_agent001([same_words, same_words, same_words], past)
    if result["status"] != "critical" or "repeats one already made" not in str(result["error"]):
        problems.append(f"only repeats: {result}")
    result, saved, _ = run_agent001([same_words], past, topic="L'orbite comme chute libre")
    if result["status"] != "not_healthy" or saved.get("novelty", {}).get("verdict") != "duplicate":
        problems.append(f"imposed repeat: {result}, {saved.get('novelty')}")
    result, saved, _ = run_agent001([new], [])
    if result["status"] != "healthy" or saved.get("novelty", {}).get("checked_against") != 0:
        problems.append(f"first video of a channel: {result}")
    return report("6. agent001: a topic already made is sent back, by its words or by the LLM", problems)


def case_page_fixes():
    from playwright.sync_api import sync_playwright
    left = {"scene_id": "1", "text_overlay": {"title": "Juillet"}, "connections": [], "actions": [
                {"at": 1.0, "action": "set_value", "target": "gauge", "value": 0.96}],
            "entities": [{"id": "sun", "type": "OBJECT", "position": [-6.4, 1.8, 0], "initial_state": {"icon": "sun", "label": "Soleil"}},
                         {"id": "earth", "type": "OBJECT", "position": [-5.2, 0.2, 0], "initial_state": {"icon": "earth", "label": "Terre"}},
                         {"id": "gauge", "type": "GAUGE", "position": [-4, -1, 0], "initial_state": {"label": "Coefficient global"}}]}
    data = renderer.page_data(left, 6.0, None)
    data["ending"] = {"at": 4.8, "length": 1.2}
    xs = [e["xy"][0] for e in data["entities"]]
    comparison = renderer.page_data(left, 6.0, None, layout="comparison")
    problems = []
    middle = (renderer.CONTENT_SIDES[0] + renderer.SIDE_COLUMN_LEFT) / 2      # a counter: a side column on the right
    if min(xs) < renderer.CONTENT_SIDES[0] or abs((min(xs) + max(xs)) / 2 - middle) > 2:
        problems.append(f"not centred: x {xs}")
    if [e["xy"][0] for e in comparison["entities"]][:2] != [round(renderer.WIDTH / 2 - 6.4 * renderer.WIDTH / renderer.UNITS_WIDE),
                                                            round(renderer.WIDTH / 2 - 5.2 * renderer.WIDTH / renderer.UNITS_WIDE)]:
        problems.append("a comparison was moved sideways")
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            path = os.path.join(folder, "scene.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(data))
            renderer.open_scene(page, path)
            shown = {}
            for t in (4.5, 5.4, 6.0):
                page.evaluate(f"window.seek({t})")
                shown[t] = page.evaluate("""() => ({value: (document.querySelector('.t-value') || {}).textContent,
                    fade: +getComputedStyle(document.getElementById('fade')).opacity})""")
        finally:
            browser.close()
    if (shown[4.5]["value"] or "").strip() != "0,96":
        problems.append(f"counter shows {shown[4.5]['value']!r}")
    if not (shown[4.5]["fade"] == 0 and 0 < shown[5.4]["fade"] < 1 and shown[6.0]["fade"] > 0.99):
        problems.append(f"fade {[shown[t]['fade'] for t in shown]}")
    return report("7. counter decimals, a corner scene centred, the last scene fades out", problems,
                  [f"the drawing now at x {xs} (was 92 to 449); counter {shown[4.5]['value']!r}"])


def case_idle_disc():
    disc = {"id": "pain", "type": "BODY", "position": [-3, 1, 0], "initial_state": {"label": "Prix du pain"}}
    found = [e for e in agent004.coherence_problems(brief([disc]), "le pain", 10) if "plain disc" in e]
    axes = {"id": "ax", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [0, 2, 1]}}
    dot = {"id": "p", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "1", "anchor": {"axes": "ax", "x": 1, "y": 0}}}
    on_line = [e for e in agent004.coherence_problems(brief([axes, dot]), "un", 10) if "plain disc" in e]
    return report("8. agent004 reports a disc standing for an idea, not a dot on a number line",
                  [] if found and not on_line else [f"{found} / {on_line}"])


results = [case_voice(), case_display(), case_agent004(), case_script_plan(), case_novelty(), case_idle_disc()]
try:
    import playwright  # noqa: F401
    results.insert(0, case_plan())
    results.append(case_page_fixes())
except ImportError:
    print("FAIL  1. Playwright is not installed (pip install playwright && playwright install chromium)")
    results.append(False)
sys.exit(0 if all(results) else 1)
