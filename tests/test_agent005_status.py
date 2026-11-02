"""
Check agent005's two answers in qa.json: "verdict" (can the pipeline go on?) and "status" (is the
result sound, or passed with a warning?).

Two cases, each run through the real agent005 run() on a small fixture in a temporary folder; only
the LLM is replaced by a fixed answer (its scores), so no network, no key, and nothing written to
instance/ or to the run log:
  1. every score >= 8           -> verdict "pass", status "healthy"
  2. accuracy = 7, the others 8 -> verdict "pass", status "warning"
Each case loads the qa.json the agent wrote and prints PASS or FAIL.

  .venv/bin/python tests/test_agent005_status.py
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app import provenance                                 # noqa: E402
from app.agent import agent005_educationqa as qa_agent   # noqa: E402

CASES = [
    ("all scores >= 8", {"accuracy": 8, "simplicity": 9, "clarity": 8}, "healthy"),
    ("accuracy = 7", {"accuracy": 7, "simplicity": 8, "clarity": 8}, "warning"),
]
SETTINGS = {"qa_strict_mode": True}       # the strictest setting: a 7 must still pass

# A one-scene fixture: a formula, no circuit (the circuit fixes and the layout leave it as it is).
SCRIPT = {"scenes": [{"scene_id": "1", "duration_sec": 8, "narration_text": "La tension U se mesure en volts."}]}
STORYBOARD = {"scenes": [{"scene_id": "1", "renderer": "manim", "visual_brief": {
    "scene_id": "1", "text_overlay": {"title": "La tension"},
    "entities": [{"id": "formula_u", "type": "TEX_FORMULA", "position": "CENTER", "initial_state": {"latex": "U = V_A - V_B"}}],
    "connections": [], "actions": []}}]}
RESEARCH = {"topic": "tension électrique"}


def run_case(scores):
    """agent005's run() with the LLM answering `scores`; returns the qa.json it wrote."""
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        for name, content in (("script.json", SCRIPT), ("storyboard.json", STORYBOARD), ("research.json", RESEARCH)):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False)
        answer = json.dumps({"scores": scores, "issues": [], "patches": [], "unsupported": []})
        patched = {"channel_dir": lambda channel_id: folder,
                   "llm_call": lambda prompt: answer,
                   "finish": lambda channel_id, agent, stage, status, output_path, data=None, error=None:
                             {"status": status, "output_path": output_path, "error": error}}
        originals = {name: getattr(qa_agent, name) for name in patched}
        instance_dir = provenance.INSTANCE_DIR
        try:
            for name, stub in patched.items():
                setattr(qa_agent, name, stub)
            provenance.INSTANCE_DIR = root          # its manifest.json goes to the temporary folder too
            result = qa_agent.run("test_channel", SETTINGS, [])
        finally:
            for name, original in originals.items():
                setattr(qa_agent, name, original)
            provenance.INSTANCE_DIR = instance_dir
        with open(os.path.join(folder, "qa.json"), encoding="utf-8") as f:
            return json.load(f), result


failures = 0
for label, scores, expected_status in CASES:
    qa, result = run_case(scores)
    problems = []
    if qa.get("verdict") != "pass":
        problems.append(f'verdict is {qa.get("verdict")!r}, expected "pass"')
    if qa.get("status") != expected_status:
        problems.append(f'status is {qa.get("status")!r}, expected {expected_status!r}')
    if result["status"] in ("revision_needed", "critical"):     # what the orchestrator acts on
        problems.append(f'agent status {result["status"]!r} would stop the pipeline')
    failures += bool(problems)
    print(f'{"FAIL" if problems else "PASS"}  {label}: verdict={qa.get("verdict")!r} status={qa.get("status")!r} '
          f'(agent status {result["status"]!r})' + "".join(f"\n      {p}" for p in problems))
sys.exit(1 if failures else 0)
