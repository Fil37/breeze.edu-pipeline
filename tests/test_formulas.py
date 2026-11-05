"""
Check that physics and maths write their key relation (the standing-waves video of 2026-11-05 had no
formula on screen: the narration stated none), offline:
  1. agent003 is told, for a physics or maths channel only, to say the key relation in words
  2. agent004 sends back a scene stating a relation with no TEX_FORMULA, and a physics / maths video
     with no formula at all; keeps a scene showing it, and leaves the other channels alone
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_formulas.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent003_scriptwriter as agent003                 # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_agent003():
    problems = []
    if "KEY RELATION" not in agent003.FORMULA_RULES or set(agent003.FORMULA_DOMAINS) != {"math", "physics_math"}:
        problems.append("agent003 not told to say the key relation for physics and maths")
    return report("1. agent003: physics and maths say their key relation", problems)


def brief(scene_id, formula):
    entities = [{"id": "w", "type": "WAVE", "position": [0, 0, 0], "initial_state": {"kind": "standing"}}]
    if formula:
        entities.append({"id": "f", "type": "TEX_FORMULA", "position": [0, 2, 0], "initial_state": {"latex": "\\\\lambda = \\\\frac{2L}{n}"}})
    return SceneVisualBrief.model_validate({"scene_id": scene_id, "text_overlay": {"title": "x"}, "connections": [],
                                            "entities": entities, "actions": []})


def case_agent004():
    problems = []
    said = {"2": "Les nœuds restent fixes.", "3": "La longueur d'onde vaut deux fois la longueur de la corde divisée par n."}
    if len(agent004.formulas_said(["2", "3"], {"2": brief("2", False), "3": brief("3", False)}, said, "physics_math")) != 1:
        problems.append("a relation said with no formula not sent back")
    if agent004.formulas_said(["2", "3"], {"2": brief("2", False), "3": brief("3", True)}, said, "physics_math"):
        problems.append("a relation shown as a formula sent back")
    quiet = {"2": "Les nœuds restent fixes.", "3": "Les ventres bougent."}
    if len(agent004.formulas_said(["2", "3"], {"2": brief("2", False), "3": brief("3", False)}, quiet, "math")) != 1:
        problems.append("a maths video with no formula at all not sent back")
    if agent004.formulas_said(["2", "3"], {"2": brief("2", False), "3": brief("3", False)}, said, "economics"):
        problems.append("an economics video asked for formulas")
    return report("2. agent004: a relation said is written; a physics / maths video has a formula", problems)


if __name__ == "__main__":
    results = [case_agent003(), case_agent004()]
    sys.exit(0 if all(results) else 1)
