"""
Check the visuals the user does not want (2026-11-21: the water cycle drew a puddle as a WATER_TANK, a tank with
its water level, and the user disliked it).
  1. settings: "banned_visuals" = {"all": [...], "<channel>": [...]}, both read, blanks dropped, none when absent
  2. the prompt: a banned component is not offered, a banned icon is not listed, the rest stays
  3. a storyboard using a banned component or an OBJECT with a banned icon is sent back, with what to do instead;
     the same storyboard with nothing banned passes
  4. the shipped settings ban WATER_TANK for every channel, and the GAUGE rule says it is only for a dial
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_banned_visuals.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as a004          # noqa: E402
from models.visual_brief_schema import SceneVisualBrief as VisualBrief                 # noqa: E402

failed = []


def report(label, problems):
    print(("PASS  " if not problems else "FAIL  ") + label)
    for p in problems:
        print("      - " + p)
    if problems:
        failed.append(label)


s = {"banned_visuals": {"all": ["WATER_TANK", " "], "breeze_(math)": ["cylinder"]}}
p = []
if a004.banned_visuals(s, "breeze_(math)") != {"WATER_TANK", "cylinder"}:
    p.append(f"math: {a004.banned_visuals(s, 'breeze_(math)')}")
if a004.banned_visuals(s, "breeze_(physics)") != {"WATER_TANK"}:
    p.append(f"physics: {a004.banned_visuals(s, 'breeze_(physics)')}")
if a004.banned_visuals({}, "x") or a004.banned_visuals(None, "x"):
    p.append("no setting should ban nothing")
report("1. settings: all + the channel, blanks dropped, none when absent", p)

p = []
text = a004.components_text(frozenset({"WATER_TANK"}))
if any(line.startswith("  * WATER_TANK:") for line in text.split("\n")):
    p.append("WATER_TANK still offered")
if not any(line.startswith("  * GAUGE:") for line in text.split("\n")):
    p.append("GAUGE dropped by mistake")
if a004.components_text() != a004.COMPONENTS_FOR_PROMPT:
    p.append("nothing banned should change nothing")
report("2. the prompt: a banned piece not offered, the others kept", p)


def brief(entities):
    return VisualBrief.model_validate({"scene_id": "3", "text_overlay": {"title": "L'évaporation"}, "connections": [],
                                       "entities": entities, "actions": []})


tank = {"id": "water_tank_1", "type": "WATER_TANK", "position": [0, 0, 0], "initial_state": {"label": "Flaque", "level": 0.6}}
can = {"id": "obj_1", "type": "OBJECT", "position": [2, 0, 0], "initial_state": {"icon": "fuel", "label": "Bidon"}}
cloud = {"id": "obj_2", "type": "OBJECT", "position": [-2, 0, 0], "initial_state": {"icon": "cloud", "label": "Nuage"}}
p = []
found = a004.banned_problems(["3"], {"3": brief([tank, can, cloud])}, frozenset({"WATER_TANK", "fuel"}))
if len(found) != 2 or not all("does not want" in f and "another way" in f for f in found):
    p.append(f"expected the tank and the fuel can sent back: {found}")
if any("obj_2" in f for f in found):
    p.append("the cloud is allowed")
if a004.banned_problems(["3"], {"3": brief([tank, can, cloud])}, frozenset()):
    p.append("nothing banned should send nothing back")
report("3. a banned piece or icon sent back with what to do; nothing banned passes", p)

p = []
shipped = json.load(open(os.path.join(ROOT, "schemas", "settings.json")))
if "WATER_TANK" not in a004.banned_visuals(shipped, "breeze_(physics)"):
    p.append("WATER_TANK not banned in schemas/settings.json")
if "A GAUGE is a dial" not in a004.PROMPT:
    p.append("the GAUGE rule is missing from the prompt")
report("4. shipped: WATER_TANK banned everywhere, GAUGE only for a dial", p)

sys.exit(1 if failed else 0)
