"""
Check agent004's layout templates on a 6-scene script ("tension vs courant", with a château d'eau
analogy): every storyboard scene gets a "layout_template" its narration allows, at least 2 different
templates, and at least one "analogy_fullscreen" since the script makes an analogy.

The real agent004 run() works in a temporary folder (instance/ and the run log are never touched).
By default the LLM is replaced by fixed answers, so the test is offline and repeatable:
  A. the LLM first puts every scene on "circuit", then corrects it on the retry: full variety,
     never the same template twice in a row
  B. the LLM never corrects it: only the missing analogy and comparison are forced, each on a scene
     whose narration allows it; the circuit cap and the repeats are not forced (that would put an
     analogy or a comparison where the narration has none), they are reported
With --live, the real LLM (schemas/settings.json, keys in .env) answers instead, once.
Prints the templates per scene and PASS or FAIL per case.

  .venv/bin/python tests/test_agent004_diversity.py            # offline: cases A and B
  .venv/bin/python tests/test_agent004_diversity.py --live     # one real LLM call (or up to 3 with retries)
"""

import copy
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import provenance                                       # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004   # noqa: E402

NARRATIONS = [
    "Ce qu'on croit : la tension circulerait dans le fil ; en réalité, c'est le courant qui circule.",
    "La tension se mesure entre deux points, en volts.",
    "Imaginons un château d'eau : la différence de hauteur pousse l'eau dans la conduite.",
    "Le courant est un débit de charges, mesuré en ampères.",
    "Alors que la tension existe sans courant, le courant a besoin d'un circuit fermé.",
    "Retenons : la tension pousse, le courant circule.",
]
SCRIPT = {"scenes": [{"scene_id": str(i + 1), "duration_sec": 8, "narration_text": text, "key_visual_moment": ""}
                     for i, text in enumerate(NARRATIONS)]}
LOOP = [{"source_id": "bat", "source_port": "positive", "target_id": "lamp", "target_port": "left_terminal"},
        {"source_id": "lamp", "source_port": "right_terminal", "target_id": "bat", "target_port": "negative"}]
BATTERY_LAMP = [{"id": "bat", "type": "BATTERY", "position": "LEFT", "initial_state": {"label": "Pile"}},
                {"id": "lamp", "type": "LAMP", "position": "RIGHT", "initial_state": {"label": "Lampe"}}]


def card(entity_id, kind, x, label):
    return {"id": entity_id, "type": kind, "position": [x, 0, 0], "initial_state": {"label": label}}


def spawn(at, target, cue):
    return {"at": at, "action": "spawn", "target": target, "cue": cue}


# Briefs that pass agent004's checks (word cues, one theme per scene, closed circuits...).
BRIEFS = [
    {"entities": [card("idea", "PIPE_VALVE", -3.5, "La tension circulerait"), card("fact", "GAUGE", 3.5, "Le courant circule")],
     "connections": [], "actions": [spawn(0.5, "idea", "Ce qu'on croit"), spawn(4.0, "fact", "en réalité")]},
    {"entities": BATTERY_LAMP, "connections": LOOP,
     "actions": [spawn(0.5, "bat", "La tension"), spawn(3.0, "lamp", "deux points")]},
    {"entities": [{"id": "high", "type": "WATER_TANK", "position": [-3.5, 0.6, 0], "initial_state": {"label": "Haut", "level": 0.6}},
                  {"id": "pipe", "type": "PIPE_VALVE", "position": [0, -0.6, 0], "initial_state": {"label": "Conduite"}},
                  {"id": "low", "type": "WATER_TANK", "position": [3.5, -1.6, 0], "initial_state": {"label": "Bas", "level": 0.2}}],
     "connections": [{"source_id": "high", "source_port": "right", "target_id": "pipe", "target_port": "left"},
                     {"source_id": "pipe", "source_port": "right", "target_id": "low", "target_port": "left"}],
     "actions": [{"at": 2.0, "action": "set_state", "target": "high", "state": {"level": 0.9}, "cue": "différence de hauteur"},
                 {"at": 4.0, "action": "start_flow", "path": ["high", "pipe", "low"], "cue": "pousse l'eau"}]},
    {"entities": BATTERY_LAMP, "connections": LOOP,
     "actions": [{"at": 0.5, "action": "start_flow", "path": ["bat", "lamp", "bat"], "cue": "Le courant"},
                 {"at": 2.0, "action": "set_state", "target": "lamp", "state": {"on": True}, "cue": "débit de charges"}]},
    {"entities": [card("u", "GAUGE", -3.5, "Tension sans courant"), card("i", "PIPE_VALVE", 3.5, "Courant : boucle fermée")],
     "connections": [], "actions": [spawn(0.5, "u", "la tension existe"), spawn(4.0, "i", "circuit fermé")]},
    {"entities": [{"id": "fu", "type": "TEX_FORMULA", "position": "LEFT", "initial_state": {"latex": "U = V_A - V_B"}},
                  {"id": "fi", "type": "TEX_FORMULA", "position": "RIGHT", "initial_state": {"latex": "I = \\Delta Q / \\Delta t"}}],
     "connections": [], "actions": [spawn(1.0, "fu", "la tension pousse"), spawn(3.0, "fi", "le courant circule")]},
]
ALL_CIRCUIT = ["circuit"] * 6
CORRECTED = ["comparison", "circuit", "analogy_fullscreen", "circuit", "comparison", "circuit"]


def answer(templates):
    """An LLM answer: the briefs above, each with its layout_template."""
    scenes = []
    for i, (brief, template) in enumerate(zip(BRIEFS, templates)):
        scene = {"scene_id": str(i + 1), "text_overlay": {"title": f"Scène {i + 1}"}, **copy.deepcopy(brief),
                 "layout_template": template}
        if template == "comparison":
            scene["panel_titles"] = ["Ce qu'on croit", "Ce qui est vrai"]
        scenes.append(scene)
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


def run_agent004(llm_answers):
    """agent004's run() in a temporary folder; llm_answers: the answers, in order (None: the real LLM).
    Returns (storyboard, the agent's "layout_templates" report, number of LLM calls)."""
    calls, report = [], {}
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        with open(os.path.join(folder, "script.json"), "w", encoding="utf-8") as f:
            json.dump(SCRIPT, f, ensure_ascii=False)
        real_llm = agent004.llm_call

        def llm(prompt):
            calls.append(prompt)
            return real_llm(prompt) if llm_answers is None else llm_answers[min(len(calls), len(llm_answers)) - 1]

        def finish(channel_id, agent, stage, status, output_path, data=None, error=None):
            report.update((data or {}).get("layout_templates") or {}, status=status, error=error)
            return {"status": status, "output_path": output_path, "error": error}

        patched = {"channel_dir": lambda channel_id: folder, "llm_call": llm, "finish": finish}
        originals = {name: getattr(agent004, name) for name in patched}
        instance_dir = provenance.INSTANCE_DIR
        try:
            for name, stub in patched.items():
                setattr(agent004, name, stub)
            provenance.INSTANCE_DIR = root
            agent004.run("test_channel", {"render_backend_by_channel": {"test_channel": "manim"}}, [])
        finally:
            for name, original in originals.items():
                setattr(agent004, name, original)
            provenance.INSTANCE_DIR = instance_dir
        path = os.path.join(folder, "storyboard.json")
        storyboard = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"scenes": []}
    return storyboard, report, len(calls)


def check(label, llm_answers, full_variety):
    storyboard, report, calls = run_agent004(llm_answers)
    templates = [scene.get("layout_template") for scene in storyboard["scenes"]]
    problems = []
    if len(templates) != len(NARRATIONS) or None in templates:
        problems.append(f"not every scene has a layout_template ({report.get('error') or templates})")
    if len(set(templates)) < 2:
        problems.append("fewer than 2 different templates")
    repeats = [f"{a['scene_id']}-{b['scene_id']}" for a, b in zip(storyboard["scenes"], storyboard["scenes"][1:])
               if a.get("layout_template") == b.get("layout_template")]
    if repeats and full_variety:
        problems.append(f"same template twice in a row: scenes {repeats}")
    allowed = report.get("allowed") or {}
    for scene, template in zip(storyboard["scenes"], templates):
        if template not in allowed.get(str(scene["scene_id"]), []):
            problems.append(f"scene {scene['scene_id']} is {template!r}, which its narration does not allow")
    if not full_variety and repeats and not report.get("problems_left"):
        problems.append("the variety not reached is not reported")
    if "analogy_fullscreen" not in templates:
        problems.append("no analogy_fullscreen, though scene 3 makes an analogy (château d'eau)")
    print(f'{"FAIL" if problems else "PASS"}  {label}  ({calls} LLM call(s), agent status {report.get("status")!r})')
    for scene, template in zip(storyboard["scenes"], templates):
        proposed = (report.get("proposed") or {}).get(str(scene["scene_id"]))
        allowed = "/".join((report.get("allowed") or {}).get(str(scene["scene_id"]), []))
        print(f"      scene {scene['scene_id']}: {template:<19} (LLM: {proposed}; allowed: {allowed})")
    for line in report.get("forced") or []:
        print(f"      forced: {line}")
    for line in report.get("problems_left") or []:
        print(f"      reported, not forced: {line}")
    for problem in problems:
        print(f"      {problem}")
    return not problems


if "--live" in sys.argv:
    results = [check("real LLM", None, False)]
else:
    results = [check("A. corrected by the LLM on the retry", [answer(ALL_CIRCUIT), answer(CORRECTED)], True),
               check("B. never corrected: the missing templates forced, the rest reported", [answer(ALL_CIRCUIT)], False)]
sys.exit(0 if all(results) else 1)
