"""
Check the German channel's programme (schemas/german_curriculum.json, A1 to B2, 2026-11-20): agent001 takes the next
episode from it instead of asking the LLM for a topic, and the plan, the script and the storyboard follow it.
  1. the file: 90 episodes, ids unique, each with a variant, a type (error / upgrade) and two different sentences
  2. the next episode: a1_01 first; one made (its id starts a topic in breeze.db) is passed; the test runs' topics
     count for nothing; an episode marked "review" is left out; --topic set to an id picks it; the last one made:
     none; a1_20 announces a2_01, a level change
  3. research.json for an episode: its pair, the next one, the level change, no LLM
  4. agent002's prompt with the episode still formats (no stray braces), act 4 by level
  5. the script: the pair said word for word in scene 1, no B1 / B2 named at A1, the ending (next episode, subscribe)
  6. the storyboard: the pair shown word for word in scene 1
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_curriculum.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent.agent001_conceptresearcher import curriculum_episodes, curriculum_research, next_episode   # noqa: E402
from app.agent import agent002_curriculumsimplifier as a002                                          # noqa: E402
from app.agent.agent003_scriptwriter import episode_problems, episode_rules                          # noqa: E402
from app.agent.agent004_visualbriefgenerator import sentence_problems                                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                                              # noqa: E402

PATH = "schemas/german_curriculum.json"


def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_file():
    problems, episodes = [], curriculum_episodes(PATH)
    ids = [e["id"] for e in episodes]
    if len(episodes) != 90 or len(set(ids)) != 90:
        problems.append(f"{len(episodes)} episodes, {len(set(ids))} ids")
    for e in episodes:
        if e.get("variant") not in ("syntax", "case", "vocab") or e.get("type") not in ("error", "upgrade") \
                or e["wrong_example"] == e["right_example"] or e.get("level") not in ("A1", "A2", "B1", "B2"):
            problems.append(f"{e['id']}: variant {e.get('variant')}, type {e.get('type')}, level {e.get('level')}")
    return report("1. the programme: 90 episodes, each complete", problems)


def case_next():
    problems, episodes = [], curriculum_episodes(PATH)
    first, after = next_episode(episodes, [])
    if (first["id"], after["id"]) != ("a1_01", "a1_02"):
        problems.append(f"first: {first['id']}, then {after['id']}")
    tests = ["Pourquoi « in den Park » et parfois « im Park » ?", "Allemand B1 : weil"]     # the test runs before
    if next_episode(episodes, tests + ["a1_01 · Place du verbe"])[0]["id"] != "a1_02":
        problems.append("an episode made not passed, or a test run counted")
    made = [f"{e['id']} · x" for e in episodes if e["id"] <= "a2_16"]
    if next_episode(episodes, made)[0]["id"] != "a2_18":                  # a2_17 waits for a review
        problems.append(f"after a2_16: {next_episode(episodes, made)[0]['id']} (a2_17 is to review)")
    picked, following = next_episode(episodes, [], "a1_20")
    if picked["id"] != "a1_20" or following["id"] != "a2_01":
        problems.append(f"--topic a1_20: {picked['id']}, then {following and following['id']}")
    if next_episode(episodes, [f"{e['id']} · x" for e in episodes]) != (None, None):
        problems.append("every episode made: one more given")
    return report("2. the next episode: in order, made ones passed, reviews left out, --topic by id", problems)


def case_research():
    episodes = curriculum_episodes(PATH)
    r = curriculum_research(*next_episode(episodes, [], "a1_20"))
    problems = []
    if not r["concept"].startswith("a1_20 · ") or not r["level_change"] or r["next_episode"]["level"] != "A2":
        problems.append(f"concept {r['concept']!r}, level change {r['level_change']}")
    if r["episode"]["wrong_example"] != "Ich mag schwimmen." or "level_title" not in r["episode"]:
        problems.append(f"the pair: {r['episode']}")
    if curriculum_research(*next_episode(episodes, [], "a1_05"))["level_change"]:
        problems.append("a level change inside A1")
    return report("3. research.json for an episode: its pair, the next one, the level change", problems)


def case_plan_prompt():
    problems, episode = [], curriculum_research(*next_episode(curriculum_episodes(PATH), []))["episode"]
    note = a002.EPISODE_NOTE.format(id=episode["id"], level="A1", level_title="x", kind="syntax", wrong=episode["wrong_example"],
                                    right=episode["right_example"], type_note=a002.TYPE_NOTES["error"],
                                    act4=a002.LEVEL_ACT4["A1"], act4_note=a002.ACT4_NOTES["A1"])
    prompt = a002.LANGUAGE_PROMPT.replace("\nAnswer with JSON only", note.replace("{", "{{").replace("}", "}}")
                                          + "\nAnswer with JSON only", 1)
    try:
        text = prompt.format(age="16-35", research={"episode": episode})
    except (KeyError, IndexError, ValueError) as exc:
        return report("4. the plan's prompt with an episode", [f"does not format: {exc!r}"])
    if "Heute ich gehe ins Kino." not in text or "Enrichir la phrase" not in text or "never talks of B1" not in text:
        problems.append("the pair, act 4 or the level rule missing")
    return report("4. the plan's prompt with an episode, act 4 by level", problems)


def case_script():
    problems, episodes = [], curriculum_episodes(PATH)
    r = curriculum_research(*next_episode(episodes, []))
    outline = {"episode": r["episode"], "next_episode": r["next_episode"], "level_change": False}
    if "Never mention B1" not in episode_rules(outline) or "Dans le prochain épisode" not in episode_rules(outline):
        problems.append("the A1 rule or the teaser missing from the prompt")
    good = [{"scene_id": "1", "narration_text": "L'erreur : « Heute ich gehe ins Kino. » La bonne phrase : « Heute gehe ich ins Kino. »"},
            {"scene_id": "5", "narration_text": "Retenez le verbe en deuxième place. Dans le prochain épisode : nicht ou kein ? "
                                                "Abonnez-vous pour ne pas rater la suite du programme jusqu'au B2."}]
    # the call to subscribe names B2, the programme's goal: allowed in that sentence only
    found = episode_problems(good, outline)
    if found:
        problems.append(f"a good script refused: {found}")
    bad = [{"scene_id": "1", "narration_text": "L'erreur : « Heute ich gehe Kino. » C'est utile pour le B2."},
           {"scene_id": "5", "narration_text": "Retenez cela."}]
    found = episode_problems(bad, outline)
    for want in ("Heute ich gehe ins Kino", "level above", "Abonnez-vous", "next episode"):
        if not any(want in p for p in found):
            problems.append(f"not sent back: {want}")
    if episode_problems(bad, {}):
        problems.append("a video outside the programme checked")
    return report("5. the script: the pair in scene 1, no higher level at A1, the ending", problems)


def case_storyboard():
    words = lambda text: [{"text": w, "role": "other"} for w in text.rstrip(".").split()]
    brief = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
             "entities": [{"id": "w", "type": "SENTENCE", "position": [0, 1, 0],
                           "initial_state": {"words": words("Heute ich gehe ins Kino."), "translation": "x", "verdict": "wrong"}}]}
    pair = ("Heute ich gehe ins Kino.", "Heute gehe ich ins Kino.")
    problems = []
    found = sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(brief)}, {"1": ""}, "language", pair)
    if not any("right sentence" in p for p in found) or any("wrong sentence" in p for p in found):
        problems.append(f"the right sentence missing not found: {found}")
    brief["actions"] = [{"at": 2, "action": "set_state", "target": "w", "state": {"order": [0, 2, 1, 3, 4]}, "cue": "x"}]
    found = sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(brief)}, {"1": ""}, "language", pair)
    if any("episode" in p for p in found):
        problems.append(f"the pair shown by a move refused: {found}")
    return report("6. the storyboard: the pair shown in the hook", problems)


if __name__ == "__main__":
    results = [case_file(), case_next(), case_research(), case_plan_prompt(), case_script(), case_storyboard()]
    sys.exit(0 if all(results) else 1)
