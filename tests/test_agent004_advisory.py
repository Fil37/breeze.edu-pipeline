"""
Check that agent004's coherence rules (word cues, tension / courant words, one theme per scene,
labels that name their target) are advisory: sent back to the LLM for a retry, never a reason to
stop the pipeline. Before, an answer still breaking one of them after 3 attempts made agent004
critical, and the whole channel stopped (orchestrator runs of 2026-10-31, 01:36 and 01:52).
The real agent004 run() works in a temporary folder (instance/ and the run log are never touched),
the LLM replaced by fixed answers:
  1. every answer breaks a coherence rule (an action without a cue, an annotation that does not name
     its formula): agent004 keeps the answer, writes the storyboard, ends "not_healthy" and lists
     what is left in "coherence_left"
  2. the retry fixes it: the fixed answer is the one kept
  3. every answer has a real structural error (an action on an unknown entity): still "critical",
     nothing written
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_agent004_advisory.py
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

NARRATIONS = ["La tension relie deux potentiels.", "Le courant compte les charges par seconde.",
              "La résistance freine les charges."]
SCRIPT = {"scenes": [{"scene_id": str(i + 1), "duration_sec": 8, "narration_text": text}
                     for i, text in enumerate(NARRATIONS)]}
FORMULAS = ["U = V_A - V_B", "I = \\Delta Q / \\Delta t", "R = U / I"]
CUES = ["deux potentiels", "les charges", "freine"]
GOOD = {"scenes": [
    {"scene_id": str(i + 1), "layout_template": "circuit", "text_overlay": {"title": f"Scène {i + 1}"},
     "entities": [{"id": "formula", "type": "TEX_FORMULA", "position": "CENTER", "initial_state": {"latex": latex}}],
     "connections": [], "actions": [{"at": 1.0, "action": "spawn", "target": "formula", "cue": cue}]}
    for i, (latex, cue) in enumerate(zip(FORMULAS, CUES))]}

INCOHERENT = copy.deepcopy(GOOD)
del INCOHERENT["scenes"][0]["actions"][0]["cue"]                         # an action without a cue
INCOHERENT["scenes"][1]["entities"].append(                               # a label that does not name I
    {"id": "note", "type": "ARROW_ANNOTATION", "position": [0, -0.6, 0],
     "initial_state": {"text": "Regardez ici", "direction": "UP", "target": "formula"}})
BROKEN = copy.deepcopy(GOOD)
BROKEN["scenes"][2]["actions"][0]["target"] = "nothing_like_this"        # an unknown entity: structural


def run_agent004(answers):
    """agent004's run() with the LLM giving `answers` in turn. Returns (status, data, storyboard or None)."""
    calls, result = [], {}
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        with open(os.path.join(folder, "script.json"), "w", encoding="utf-8") as f:
            json.dump(SCRIPT, f, ensure_ascii=False)

        def finish(channel_id, agent, stage, status, output_path, data=None, error=None):
            result.update(status=status, data=data or {}, error=error)
            return {"status": status, "output_path": output_path, "error": error}

        patched = {"channel_dir": lambda channel_id: folder, "finish": finish,
                   "llm_call": lambda prompt: calls.append(prompt) or json.dumps(answers[min(len(calls), len(answers)) - 1])}
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
        storyboard = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    return result.get("status"), result.get("data", {}), storyboard, result.get("error"), len(calls)


def check(label, answers, expected_status, expect_storyboard, expect_left):
    status, data, storyboard, error, calls = run_agent004(answers)
    left = data.get("coherence_left") or []
    problems = []
    if status != expected_status:
        problems.append(f"status {status!r}, expected {expected_status!r} ({error})")
    if (storyboard is not None) != expect_storyboard:
        problems.append("storyboard.json " + ("missing" if expect_storyboard else "written anyway"))
    if bool(left) != expect_left:
        problems.append(f"coherence_left: {left}")
    print(f'{"FAIL" if problems else "PASS"}  {label}  ({calls} LLM call(s), status {status!r})'
          + "".join(f"\n      {p}" for p in problems))
    for line in left:
        print(f"      kept despite: {line}")
    return not problems


results = [
    check("coherence still broken after 3 attempts: kept, not_healthy, not critical", [INCOHERENT], "not_healthy", True, True),
    check("coherence fixed on the retry: the fixed answer is kept", [INCOHERENT, GOOD], "not_healthy", True, False),
    check("structural error every time: still critical", [BROKEN], "critical", False, False),
]
sys.exit(0 if all(results) else 1)
