"""
Check that agent004 puts the QA's feedback (LBREEZE_QA_FEEDBACK) into its LLM prompt, and only from
there: the real agent004 run() works in a temporary folder (instance/ and the run log are never
touched) with the LLM replaced by a fixed answer that records the prompt it is sent.
  1. LBREEZE_QA_FEEDBACK set (a blocking issue on scene 5): the prompt has the section
     "Corrections demandées par le QA (révision 1)", the rejection notes and the issue's text
  2. no LBREEZE_QA_FEEDBACK: no such section
  3. LBREEZE_QA_FEEDBACK not valid JSON: no section, and the agent still writes its storyboard
In every case a qa.json with its own sentence sits in the folder: it must never be read (the
sentence never reaches the prompt, and no qa.json is ever loaded).
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_agent004_qa_feedback.py
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import provenance                                       # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004   # noqa: E402

SECTION = "Corrections demandées par le QA"
FEEDBACK = {"rejection_notes": "Scène 5 : la formule de la puissance est fausse, elle additionne U et I.",
            "blocking_issues": [{"scene_id": "5", "text": "Scène 5 : formula_p affiche P = U + I au lieu de P = U × I.",
                                 "kind": "factual", "severity": "blocking", "fixed_by": []}],
            "revision": 1}
QA_SENTINEL = "PHRASE-DU-QA-JSON-QUI-NE-DOIT-JAMAIS-ETRE-LUE"

# Five neutral scenes (one formula each): nothing in them calls for another layout or an instrument.
NARRATIONS = ["La tension relie deux potentiels.", "Le courant compte les charges par seconde.",
              "La résistance freine les charges.", "La loi d'Ohm relie les trois grandeurs.",
              "La puissance électrique vient de la tension et du courant."]
FORMULAS = ["U = V_A - V_B", "I = \\Delta Q / \\Delta t", "R = U / I", "U = R \\times I", "P = U + I"]
SCRIPT = {"scenes": [{"scene_id": str(i + 1), "duration_sec": 8, "narration_text": text}
                     for i, text in enumerate(NARRATIONS)]}
CUES = ["deux potentiels", "les charges", "freine", "loi d'Ohm", "La puissance"]
ANSWER = json.dumps({"scenes": [
    {"scene_id": str(i + 1), "layout_template": "circuit", "text_overlay": {"title": f"Scène {i + 1}"},
     "entities": [{"id": "formula", "type": "TEX_FORMULA", "position": "CENTER", "initial_state": {"latex": latex}}],
     "connections": [], "actions": [{"at": 1.0, "action": "spawn", "target": "formula", "cue": cue}]}
    for i, (latex, cue) in enumerate(zip(FORMULAS, CUES))]}, ensure_ascii=False)


def run_agent004(feedback_value):
    """agent004's run() with LBREEZE_QA_FEEDBACK = feedback_value (None: unset). Returns (the
    prompts sent to the LLM, the paths it loaded, whether storyboard.json was written)."""
    prompts, loaded = [], []
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        with open(os.path.join(folder, "script.json"), "w", encoding="utf-8") as f:
            json.dump(SCRIPT, f, ensure_ascii=False)
        with open(os.path.join(folder, "qa.json"), "w", encoding="utf-8") as f:   # must never be read
            json.dump({"verdict": "reject", "rejection_notes": QA_SENTINEL, "issues": []}, f)
        real_load_json = agent004.load_json

        def load_json(path):
            loaded.append(path)
            return real_load_json(path)

        patched = {"channel_dir": lambda channel_id: folder,
                   "llm_call": lambda prompt: prompts.append(prompt) or ANSWER,
                   "load_json": load_json,
                   "finish": lambda channel_id, agent, stage, status, output_path, data=None, error=None:
                             {"status": status, "output_path": output_path, "error": error}}
        originals = {name: getattr(agent004, name) for name in patched}
        instance_dir, saved_env = provenance.INSTANCE_DIR, os.environ.pop(agent004.QA_FEEDBACK_ENV, None)
        try:
            for name, stub in patched.items():
                setattr(agent004, name, stub)
            provenance.INSTANCE_DIR = root
            if feedback_value is not None:
                os.environ[agent004.QA_FEEDBACK_ENV] = feedback_value
            agent004.run("test_channel", {"render_backend_by_channel": {"test_channel": "manim"}}, [])
        finally:
            for name, original in originals.items():
                setattr(agent004, name, original)
            provenance.INSTANCE_DIR = instance_dir
            os.environ.pop(agent004.QA_FEEDBACK_ENV, None)
            if saved_env is not None:
                os.environ[agent004.QA_FEEDBACK_ENV] = saved_env
        written = os.path.exists(os.path.join(folder, "storyboard.json"))
    return prompts, loaded, written


def check(label, feedback_value, expect_section):
    prompts, loaded, written = run_agent004(feedback_value)
    prompt = prompts[0] if prompts else ""
    problems = []
    if not prompts:
        problems.append("the LLM was never called")
    if expect_section:
        for needed in (f"{SECTION} (révision 1)", FEEDBACK["rejection_notes"], FEEDBACK["blocking_issues"][0]["text"], "- scene 5:"):
            if needed not in prompt:
                problems.append(f"the prompt lacks {needed!r}")
    elif SECTION in prompt:
        problems.append(f"the prompt has a {SECTION!r} section")
    if QA_SENTINEL in prompt or any(os.path.basename(path) == "qa.json" for path in loaded):
        problems.append("qa.json was read: the only channel must be LBREEZE_QA_FEEDBACK")
    if not written:
        problems.append("no storyboard.json written")
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {p}" for p in problems))
    if expect_section and not problems:
        start = prompt.index(SECTION)
        print("      " + prompt[start:prompt.index("Answer with JSON only")].strip().replace("\n", "\n      "))
    return not problems


results = [check("with LBREEZE_QA_FEEDBACK: the corrections are in the prompt", json.dumps(FEEDBACK, ensure_ascii=False), True),
           check("without LBREEZE_QA_FEEDBACK: no corrections section", None, False),
           check("LBREEZE_QA_FEEDBACK not valid JSON: ignored, the agent still runs", "{not json", False)]
sys.exit(0 if all(results) else 1)
