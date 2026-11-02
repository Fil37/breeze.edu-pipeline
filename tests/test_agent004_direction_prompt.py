"""
Check that agent004's prompt offers a vector direction ([dx, dy]) to ARROW_ANNOTATION as well as
VECTOR_ARROW, with a tilted example (the Earth's axis, 23.5° -> [0.4, 0.9]), so the LLM can tilt a
badge or an axis when the narration needs it. The prompt is the one ask_for_storyboard really sends:
the LLM is replaced by a stub that keeps the first prompt and stops (offline, nothing written).
Also checks the prompt was fully formatted (no "{...}" placeholder left) and still holds the other
instructions it had. Prints PASS or FAIL.

  .venv/bin/python tests/test_agent004_direction_prompt.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as agent004   # noqa: E402

SCENES = [{"scene_id": "1", "duration_sec": 8, "key_visual_moment": "",
           "narration_text": "L'axe de la Terre est incliné d'environ 23,5 degrés."}]


# The fields PROMPT.format fills in (a "{d}" in the prompt is LaTeX, e.g. "\\frac{d}{t}").
FIELDS = ("maths", "components", "positions", "max_entities", "max_formulas", "max_circuit",
          "layout_eligibility", "actions", "schema", "scenes")


class Captured(Exception):
    pass


def sent_prompt():
    """The prompt agent004 sends for SCENES."""
    prompts, original = [], agent004.llm_call

    def stub(prompt):
        prompts.append(prompt)
        raise Captured
    agent004.llm_call = stub
    try:
        agent004.ask_for_storyboard(SCENES)
    except Exception:                   # Captured, or agent004's own error once the stub refuses
        pass
    finally:
        agent004.llm_call = original
    return prompts[0] if prompts else ""


prompt = sent_prompt()
annotation_line = next((line for line in prompt.splitlines() if "* ARROW_ANNOTATION:" in line), "")
checks = {
    "the prompt was sent": bool(prompt),
    'ARROW_ANNOTATION offers "[dx, dy]"': "[dx, dy]" in annotation_line or "[x, y]" in annotation_line,
    'VECTOR_ARROW still offers "[dx, dy]"': any("* VECTOR_ARROW:" in line and "[dx, dy]" in line for line in prompt.splitlines()),
    "the cardinals are still offered": all(name in prompt for name in ('"UP"', '"DOWN"', '"LEFT"', '"RIGHT"')),
    "a tilted example: 23.5° -> [0.4, 0.9]": bool(re.search(r"23[.,]5\s*°.*\[0\.4, 0\.9\]", prompt)),
    "no placeholder left unformatted": not any("{" + field + "}" in prompt for field in FIELDS),
    "the other instructions are still there": all(text in prompt for text in (
        "TARGET FIRST", "WORD-SYNCHRONIZED ACTIONS", "WHICH COMPONENTS TO USE", "Answer with JSON only")),
}
failed = [label for label, ok in checks.items() if not ok]
print(f'{"FAIL" if failed else "PASS"}  agent004 prompt: vector directions for ARROW_ANNOTATION, with a tilted example')
for label, ok in checks.items():
    print(f'      {"ok " if ok else "NO "} {label}')
if annotation_line:
    print(f"      {annotation_line.strip()}")
sys.exit(1 if failed else 0)
