"""
Check that agent005's QA patches accept the same "direction" as the schema: a cardinal or a vector
[dx, dy]. Before, a set_initial_state patch with [0.4, 0.9] (the Earth's axis, 23.5° from the
vertical) was dropped ("direction must be one of ('UP', 'DOWN', 'LEFT', 'RIGHT')"), so the QA could
not tilt an axis and undid agent004's fix. Goes through agent005's own apply_patches (patch check,
then the brief re-validated by the schema), offline:
  1. direction [0.4, 0.9] on a VECTOR_ARROW and on an ARROW_ANNOTATION: applied, stored as the vector
  2. direction "up" (a cardinal, lowercase): applied, stored "UP" as before
  3. direction "DIAGONAL": still dropped, with the schema's message
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_agent005_direction_patch.py
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent005_educationqa as agent005   # noqa: E402

BRIEF = {"scene_id": "3", "text_overlay": {"title": "L'axe de la Terre"},
         "entities": [{"id": "formula", "type": "TEX_FORMULA", "position": [-2, 0, 0], "initial_state": {"latex": "23{,}5^\\circ"}},
                      {"id": "note", "type": "ARROW_ANNOTATION", "position": [-2, -0.6, 0],
                       "initial_state": {"text": "Inclinaison", "direction": "DOWN", "target": "formula"}},
                      {"id": "axis", "type": "VECTOR_ARROW", "position": [2.5, -1, 0],
                       "initial_state": {"direction": [0, 1], "length": 2.5, "label": "Axe terrestre"}}],
         "connections": [], "actions": [{"at": 0.5, "action": "spawn", "target": "formula"}]}


def patch(entity_id, value):
    return {"op": "set_initial_state", "scene_id": "3", "entity_id": entity_id, "key": "direction", "value": value}


def check(label, patches, expected):
    """expected: {entity id: the direction it must end with}; None means the patches must be dropped."""
    briefs, corrections = {"3": copy.deepcopy(BRIEF)}, []
    agent005.apply_patches(briefs, patches, corrections)
    directions = {e["id"]: e["initial_state"].get("direction") for e in briefs["3"]["entities"]}
    problems = []
    if expected is None:
        if any("dropped patch" not in line for line in corrections):
            problems.append("an invalid direction was applied")
        if directions != {e["id"]: e["initial_state"].get("direction") for e in BRIEF["entities"]}:
            problems.append(f"the brief changed: {directions}")
    else:
        for entity_id, direction in expected.items():
            if directions[entity_id] != direction:
                problems.append(f"{entity_id}: direction {directions[entity_id]!r}, expected {direction!r}")
        problems += [line for line in corrections if "dropped patch" in line]
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {c}" for c in corrections)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


results = [
    check("direction [0.4, 0.9] (axis tilted 23.5°): applied", [patch("axis", [0.4, 0.9]), patch("note", [0.4, 0.9])],
          {"axis": [0.4, 0.9], "note": [0.4, 0.9]}),
    check("direction \"up\" (cardinal): applied, stored \"UP\" as before", [patch("note", "up"), patch("axis", "UP")],
          {"note": "UP", "axis": "UP"}),
    check("direction \"DIAGONAL\": still dropped", [patch("note", "DIAGONAL")], None),
]
sys.exit(0 if all(results) else 1)
