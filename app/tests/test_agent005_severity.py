"""
Check the "severity" agent005 gives each issue in qa.json, and BLOCKING_REJECTS (2026-11-26, the user: a blocking
error must really stop the video; before, observation mode let the physics video pass with one).

Two cases, each run through the real agent005 run() on a one-scene fixture in a temporary folder;
only the LLM is replaced by a fixed answer (scores 8, issues, patches), so no network, no key, and
nothing written to app/instance/ or to the run log. Each case loads the qa.json the agent wrote:
  1. 0 blocking: a factual issue whose patch is applied -> "corrected", a stylistic one ->
     "informative"; verdict "pass"
  2. 1 blocking: the same, plus a factual issue whose patch is refused by the validator (unknown
     entity) -> "blocking"; verdict "reject" although every score passes, sent back to agent004 (about the picture)
  3. the same in strict mode off: verdict "pass" (strict mode off never rejects)
  4. a blocking issue about what is said (the physics case): reject to agent003, its text in the notes
Checks: a "severity" on every issue, the expected severities, blocking_count / corrected_count /
informative_count matching the issues, the verdict expected. Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_agent005_severity.py
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
from app import provenance                                 # noqa: E402
from app.agent import agent005_educationqa as qa_agent   # noqa: E402

SCRIPT = {"scenes": [{"scene_id": "1", "duration_sec": 8, "narration_text": "La tension U se mesure en volts."}]}
STORYBOARD = {"scenes": [{"scene_id": "1", "renderer": "manim", "visual_brief": {
    "scene_id": "1", "text_overlay": {"title": "La tension, une différence de potentiel entre deux points"},
    "entities": [{"id": "formula_u", "type": "TEX_FORMULA", "position": "CENTER", "initial_state": {"latex": "U = R + I"}}],
    "connections": [], "actions": []}}]}
RESEARCH = {"topic": "tension électrique"}

CORRECTED = {"scene_id": "1", "text": "Scène 1 : formula_u affiche U = R + I au lieu de U = R × I.",
             "kind": "factual", "patches": [0]}
INFORMATIVE = {"scene_id": "1", "text": "Scène 1 : le titre est un peu long.", "kind": "style", "patches": []}
BLOCKING = {"scene_id": "1", "text": "Scène 1 : la narration parle de volts mais aucun voltmètre n'est montré.",
            "kind": "factual", "patches": [1]}
PATCHES = [
    {"op": "set_initial_state", "scene_id": "1", "entity_id": "formula_u", "key": "latex", "value": "U = R \\times I"},
    {"op": "set_initial_state", "scene_id": "1", "entity_id": "voltmeter_1", "key": "label", "value": "V"},  # refused
]
SAID = {"scene_id": "1", "kind": "factual", "patches": [],
        "text": "La narration dit que la période est « presque constante » ; dans le modèle idéal elle est exactement "
                "indépendante de l'amplitude."}
CASES = [   # label, issues, severities, strict, verdict, reject_to
    ("0 blocking", [CORRECTED, INFORMATIVE], ["corrected", "informative"], True, "pass", None),
    ("1 blocking rejects", [CORRECTED, INFORMATIVE, BLOCKING], ["corrected", "informative", "blocking"], True, "reject", "agent004"),
    ("1 blocking, strict mode off", [CORRECTED, INFORMATIVE, BLOCKING], ["corrected", "informative", "blocking"], False, "pass", None),
    ("blocking about the narration", [CORRECTED, SAID], ["corrected", "blocking"], True, "reject", "agent003"),
]


def run_case(issues, strict=True):
    """agent005's run() with the LLM answering scores 8 and `issues`; returns the qa.json it wrote."""
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        for name, content in (("script.json", SCRIPT), ("storyboard.json", STORYBOARD), ("research.json", RESEARCH)):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False)
        answer = json.dumps({"scores": {"accuracy": 8, "simplicity": 8, "clarity": 8}, "issues": issues,
                             "patches": PATCHES, "unsupported": []})
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
            qa_agent.run("test_channel", {"qa_strict_mode": strict}, [])
        finally:
            for name, original in originals.items():
                setattr(qa_agent, name, original)
            provenance.INSTANCE_DIR = instance_dir
        with open(os.path.join(folder, "qa.json"), encoding="utf-8") as f:
            return json.load(f)


failures = 0
for label, issues, expected, strict, verdict, reject_to in CASES:
    qa = run_case(issues, strict)
    got = [issue.get("severity") for issue in qa.get("issues", [])]
    problems = []
    if qa.get("verdict") != verdict or qa.get("reject_to") != reject_to:
        problems.append(f'verdict {qa.get("verdict")!r} to {qa.get("reject_to")!r}, expected {verdict!r} to {reject_to!r}')
    if verdict == "reject" and "blocking" in got and not qa.get("rejection_notes"):
        problems.append("a reject for a blocking issue without its text in rejection_notes")
    if any(severity is None for severity in got) or len(got) != len(issues):
        problems.append(f"an issue has no severity: {qa.get('issues')}")
    if got != expected:
        problems.append(f"severities {got}, expected {expected}")
    for severity in ("blocking", "corrected", "informative"):
        if qa.get(f"{severity}_count") != got.count(severity):
            problems.append(f"{severity}_count is {qa.get(f'{severity}_count')!r}, the issues have {got.count(severity)}")
    if sum(qa.get(f"{s}_count", 0) for s in ("blocking", "corrected", "informative")) != len(got):
        problems.append("the three counts do not add up to the number of issues")
    failures += bool(problems)
    print(f'{"FAIL" if problems else "PASS"}  {label}: verdict={qa.get("verdict")!r} severities={got} '
          f'blocking={qa.get("blocking_count")} corrected={qa.get("corrected_count")} '
          f'informative={qa.get("informative_count")}' + "".join(f"\n      {p}" for p in problems))
sys.exit(1 if failures else 0)
