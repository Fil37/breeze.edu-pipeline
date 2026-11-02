"""
Check the follow-ups of the breeze_(math) run of 2026-10-31 (17:25), offline but for the browser:
  1. a move_along cued too late to be seen whole (the ISS of scene 5: 7 s asked, 1 s of scene left)
     is made to end with the scene, starting earlier if it needs MIN_MOVE_SEC; one that fits is left
     as asked
  2. a move_along without a cue, planned at the same time as a cued one (the astronaut the QA added
     beside the ISS, scene 6), starts with it: the two bodies stay together
  3. agent004 tells the LLM a move_along that ends after its scene (advisory, sent back for a retry)
  4. agent003, redone after a QA reject, gets the QA's feedback (LBREEZE_QA_FEEDBACK) in its prompt,
     with what the animation can show; without it, its prompt is as before
  5. agent010 page (Chromium): a badge pointing at a moving body goes with it (its arrow ending by the
     disc: on a curve it is re-placed outside the curve at every frame); a vector anchored on an
     OBJECT ({"body": <OBJECT id>}) starts in line with the object's centre, where it leaves the object
     (its label included)
Prints PASS or FAIL per case. Case 5 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_motion_followups.py
"""

import copy
import json
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import provenance                                              # noqa: E402
from app.agent import agent003_scriptwriter as agent003                 # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.qa_feedback import QA_FEEDBACK_ENV                             # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402

AXES = {"id": "ax", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}}
ORBIT = {"id": "orbit", "type": "CURVE_PLOT", "position": [0, 0, 0],
         "initial_state": {"x_func": "2.5*np.cos(t)", "y_func": "2.5*np.sin(t)", "axes": "ax"}}


def body(entity_id, t=0.0, label="ISS"):
    return {"id": entity_id, "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": label, "anchor": {"curve": "orbit", "t": t}}}


def scene(entities, actions):
    return {"scene_id": "1", "text_overlay": {"title": "Orbite"}, "connections": [], "entities": copy.deepcopy(entities),
            "actions": [{"at": 0.1 * i, "action": "spawn", "target": e["id"], "cue": "x"} for i, e in enumerate(entities)] + actions}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def moves(brief, voice, spoken=None):
    return [e for e in renderer.page_data(brief, voice, None, spoken)["events"] if e["action"] == "move_along"]


def case_fit():
    end = 10.0 + renderer.TAIL_PAUSE
    late = moves(scene([AXES, ORBIT, body("iss")], [{"at": 9.5, "action": "move_along", "target": "iss", "to": 6.2832, "duration": 7}]), 10.0)[0]
    fits = moves(scene([AXES, ORBIT, body("iss")], [{"at": 2.0, "action": "move_along", "target": "iss", "to": 6.2832, "duration": 4}]), 10.0)[0]
    problems = []
    if abs(late["at"] + late["duration"] - end) > 1e-6 or late["duration"] < renderer.MIN_MOVE_SEC - 1e-6 or late.get("planned_duration") != 7:
        problems.append(f"the late move: at {late['at']:.2f}, {late['duration']:.2f} s (scene ends {end:.2f})")
    if fits["duration"] != 4 or "planned_duration" in fits:
        problems.append(f"a move that fits was changed: {fits['duration']} s")
    return report("1. a move cued too late ends with the scene; one that fits is left alone", problems,
                  [f"late: {late['at']:.2f} s + {late['duration']:.2f} s = the scene's end ({end:.2f} s), 7 s asked"])


def case_sync():
    brief = scene([AXES, ORBIT, body("iss", 0.5), body("astro", 0.5, "Astronaute")],
                  [{"at": 6.0, "action": "move_along", "target": "iss", "to": 6.2832, "duration": 3, "cue": "une orbite"},
                   {"at": 6.0, "action": "move_along", "target": "astro", "to": 6.2832, "duration": 3}])
    spoken = [(0.4 * i, w) for i, w in enumerate("Une orbite c'est une chute qui rate sans cesse le sol".split())]
    events = {e["target"]: e for e in moves(brief, 6.0, spoken)}
    same = abs(events["iss"]["at"] - events["astro"]["at"]) < 1e-9
    return report("2. a move without a cue, planned with a cued one, starts with it", [] if same else
                  [f"ISS at {events['iss']['at']:.2f} s, astronaut at {events['astro']['at']:.2f} s"],
                  [f"both at {events['iss']['at']:.2f} s (the cue \"une orbite\")"])


def case_advisory():
    brief = SceneVisualBrief.model_validate(scene([AXES, ORBIT, body("iss")], [
        {"at": 9.0, "action": "move_along", "target": "iss", "to": 6.2832, "duration": 7, "cue": "x"}]))
    found = [e for e in agent004.coherence_problems(brief, "x x x", 10) if "move_along" in e]
    return report("3. agent004: a move ending after its scene is sent back to the LLM", [] if found else ["not reported"], found)


def run_agent003(feedback):
    prompts = []
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        with open(os.path.join(folder, "outline.json"), "w", encoding="utf-8") as f:
            json.dump({"beats": ["La gravité agit en orbite."]}, f)
        answer = json.dumps({"scenes": [{"scene_id": 1, "narration_text": "mot " * 20, "duration_sec": 8}]})
        patched = {"channel_dir": lambda channel_id: folder, "llm_call": lambda prompt: prompts.append(prompt) or answer,
                   "finish": lambda channel_id, agent, stage, status, output_path, data=None, error=None: {"status": status}}
        originals = {name: getattr(agent003, name) for name in patched}
        instance_dir, saved = provenance.INSTANCE_DIR, os.environ.pop(QA_FEEDBACK_ENV, None)
        try:
            for name, stub in patched.items():
                setattr(agent003, name, stub)
            provenance.INSTANCE_DIR = root
            if feedback is not None:
                os.environ[QA_FEEDBACK_ENV] = json.dumps(feedback, ensure_ascii=False)
            stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
            try:
                agent003.run("test_channel", {}, [])
            finally:
                sys.stderr.close()
                sys.stderr = stderr
        finally:
            for name, original in originals.items():
                setattr(agent003, name, original)
            provenance.INSTANCE_DIR = instance_dir
            os.environ.pop(QA_FEEDBACK_ENV, None)
            if saved is not None:
                os.environ[QA_FEEDBACK_ENV] = saved
    return prompts[0] if prompts else ""


def case_agent003():
    issue = "Scène 4 : la narration décrit l'astronaute à l'intérieur de l'ISS, ce que l'animation ne montre pas."
    with_feedback = run_agent003({"rejection_notes": "Réécrire la scène 4.", "blocking_issues": [{"scene_id": "4", "text": issue}], "revision": 1})
    without = run_agent003(None)
    problems = [f"the prompt lacks {part!r}" for part in ("Corrections demandées par le QA (révision 1)", "previous script",
                                                           issue, "Réécrire la scène 4.", agent003.DRAWABLE) if part not in with_feedback]
    if "Corrections demandées par le QA" in without or without != agent003.PROMPT.format(outline={"beats": ["La gravité agit en orbite."]}, pace=agent003.WORDS_PER_SEC,
                                                                                least=agent003.MIN_WORDS, most=agent003.MAX_WORDS):
        problems.append("without feedback, the prompt changed")
    return report("4. agent003 gets the QA's feedback, with what the animation can show", problems)


MEASURE = """() => {
  const stage = document.getElementById("stage").getBoundingClientRect();
  const centre = n => { const q = n.getBoundingClientRect(); return [(q.left + q.right) / 2 - stage.left, (q.top + q.bottom) / 2 - stage.top]; };
  const out = {disc: centre(E.iss.shape), badge: centre(E.note.box), earth: centre(E.earth.shape), tip: E.note.ann.tip,
               earthBox: (q => ({b: q.bottom - stage.top}))(E.earth.box.getBoundingClientRect())};
  const l = E.weight.vector.line, p = new DOMPoint(+l.getAttribute("x1"), +l.getAttribute("y1")).matrixTransform(l.getScreenCTM());
  out.weight = [p.x - stage.left, p.y - stage.top];
  return out;
}"""


def case_page():
    from playwright.sync_api import sync_playwright
    entities = [AXES, ORBIT, body("iss", 1.5708),
                {"id": "note", "type": "ARROW_ANNOTATION", "position": [0, 2.5, 0], "initial_state": {"text": "ISS", "direction": "DOWN", "target": "iss"}},
                {"id": "earth", "type": "OBJECT", "position": [4.5, 1.0, 0], "initial_state": {"icon": "earth", "label": "Terre"}},
                {"id": "weight", "type": "VECTOR_ARROW", "position": [0, 0, 0], "initial_state": {"anchor": {"body": "earth"}, "direction": "DOWN", "label": "Poids"}}]
    brief = scene(entities, [{"at": 2.0, "action": "move_along", "target": "iss", "to": 3.1416, "duration": 2, "cue": "x"}])
    SceneVisualBrief.model_validate(brief)
    frames = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in (1.5, 4.5):
                page.evaluate(f"window.seek({t})")
                frames[t] = page.evaluate(MEASURE)
        finally:
            browser.close()
    before, after = frames[1.5], frames[4.5]
    moved = [after["disc"][i] - before["disc"][i] for i in (0, 1)]
    followed = [after["badge"][i] - before["badge"][i] for i in (0, 1)]
    problems = []
    # On a curve, the badge is re-placed outside it at every frame (orbitBadge), not shifted as one block:
    # it goes with the ISS, its arrow ending by the disc.
    reach = [math.dist(f["tip"], f["disc"]) for f in (before, after)]
    if math.hypot(*moved) < 50 or math.hypot(*followed) < 50 or max(reach) > 80:
        problems.append(f"the ISS moved {moved}, its badge {followed}, the arrow ends {reach} px from the disc")
    gap = abs(after["weight"][0] - after["earth"][0])     # DOWN: in line with the Earth's centre, below the card and its label
    if gap > 2 or not after["earthBox"]["b"] <= after["weight"][1] <= after["earthBox"]["b"] + 12:
        problems.append(f"the vector starts at {after['weight']}, the Earth's centre {after['earth']}, its box ending at {after['earthBox']['b']:.0f}")
    return report("5. agent010: a badge follows its moving body; a vector starts on an OBJECT", problems,
                  [f"ISS moved ({moved[0]:.0f}, {moved[1]:.0f}) px, its badge ({followed[0]:.0f}, {followed[1]:.0f}) px; "
                   f"vector {gap:.1f} px off the Earth's centre line, under its label"])


results = [case_fit(), case_sync(), case_advisory(), case_agent003()]
try:
    import playwright  # noqa: F401
    results.append(case_page())
except ImportError:
    print("FAIL  5. Playwright is not installed (pip install playwright && playwright install chromium)")
    results.append(False)
sys.exit(0 if all(results) else 1)
