"""
INPUT:  app/instance/{channel_id}/research.json + app/schemas/routes.json (target_age_band)
OUTPUT: app/instance/{channel_id}/outline.json = {learning_outline[], aha_moment, prerequisites[],
        visual_metaphors[], scene_count_target}
NOTES:  Builds the pedagogical arc only, rewritten for the age band.
        Never writes narration. Never picks visuals or renderers.
HEALTH: not_healthy if aha_moment is empty;
        critical if research.json is missing, llm_call fails, or fewer than 3 beats.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import (channel_dir, find_route, finish, llm_call, load_json,
                       parse_llm_json, run_standalone, save_json)
from app import provenance

AGENT = "agent002"
# What this agent can do (the studio kit's skills, registered by agent000 at start: "proposed" until the
# user approves their activation on the standup).
SKILLS = [
    {"skill_id": "learning_outline", "version": "1.0", "objective": "Build the learning arc, from the misconception to the aha moment",
     "summary": "Formats: concept, project, problem, course; five acts for an exam error."},
]

PROMPT = """You are a curriculum designer. Turn this research into a learning arc for age {age}.
Research: {research}
Start from the misconception, build up step by step, and land on one clear "aha moment".
For a measure, a law, a tax, a policy or a news event, the first beats say what it is, who proposed it
and when, where it stands and who is concerned (from the research's facts), before its mechanism.
Do not write narration and do not describe visuals in detail: only the teaching steps.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"learning_outline": ["beat 1", "beat 2", "beat 3", "..."], "aha_moment": "...",
  "prerequisites": ["..."], "visual_metaphors": ["..."], "scene_count_target": 6}}"""


# A worked problem (research "format": "problem"): stated, set up, solved, checked.
PROBLEM_PROMPT = """You are a curriculum designer. This video SOLVES A PROBLEM for age {age}.
Research: {research}
The learning outline follows the solving, in order: the statement (the situation and its numbers, said in
full), the unknowns named (with letters), the equations written from the statement (one per sentence of
it), then ONE beat per step of the method (for a system: each row operation, the unknown it eliminates),
then the back substitution, then the check (the answer put back into the statement), then the answer
said in the situation's words ("une place adulte coûte 12 €"). The aha moment is the method working on
this problem. Do not turn it into a lesson on why the method works.
IMPORTANT: The target audience is French. You MUST write all your output in PERFECT FRENCH (JSON keys in English).
Answer with JSON only:
{{"learning_outline": ["beat 1", "beat 2", "..."], "aha_moment": "...",
  "prerequisites": ["..."], "visual_metaphors": ["..."], "scene_count_target": 7}}"""
# A course on several things (research "format": "course", its "items"): one beat each, none left out.
COURSE_PROMPT = """You are a curriculum designer. This video is a COURSE on several things for age {age}.
Research: {research}
The learning outline: first what they are all FOR (the need they share), then ONE beat per item, in a
sensible order, EVERY item of the research's "items" (none left out, none merged): what it is, how it
works, its key formula with values worked out, a concrete use; then a last beat comparing them (when to
use which). The aha moment is seeing how they differ and when to pick each.
IMPORTANT: The target audience is French. You MUST write all your output in PERFECT FRENCH (JSON keys in English).
Answer with JSON only:
{{"learning_outline": ["beat 1", "beat 2", "..."], "aha_moment": "...",
  "prerequisites": ["..."], "visual_metaphors": ["..."], "scene_count_target": 7}}"""


# A project to build (research "format": "project", agent001): the arc is the build itself.
PROJECT_PROMPT = """You are a curriculum designer. This video is a PROJECT BUILT STEP BY STEP for age {age}.
Research: {research}
The learning outline is the build, in the order it is made: first what it is FOR in everyday life
(where the need comes from, the problem it solves), then the goal (the finished project working: what
it does), then ONE beat per build stage (the parts it adds with their values, what each
does, what is connected to what, how to check the stage works), then the build on a breadboard, then
powering it up and seeing it work. The aha moment is the finished project doing its job. Do not turn
it into a lesson on one concept: what is explained serves the build.
IMPORTANT: The target audience is French. You MUST write all your output in PERFECT FRENCH (JSON keys in English).
Answer with JSON only:
{{"learning_outline": ["stage 1", "stage 2", "..."], "aha_moment": "...",
  "prerequisites": ["..."], "visual_metaphors": ["..."], "scene_count_target": 8}}"""


# A language channel (route "domain": "language"): every video is one exam error taken apart, in five acts
# (the channel's contract, from the obwohl / trotzdem episode of 2026-11-20); act 3 depends on the kind.
LANGUAGE_ACTS = ["L'erreur d'examen", "Le piège du français", "La mécanique", "La version B2", "Le mémo du jour J"]
# act 4 by level (the curriculum, A1 to B2): at A1/A2 the sentence is enriched, never "the B2 version"
LEVEL_ACT4 = {"A1": "Enrichir la phrase", "A2": "Enrichir la phrase", "B1": "La version qui rapporte des points",
              "B2": "La version B2"}
CURRICULUM_KINDS = {"syntax": "syntax", "case": "cases", "vocab": "vocabulary"}   # the curriculum's names -> ours
EPISODE_NOTE = """
This video is episode {id} of the channel's programme, level {level} ({level_title}). Kind: {kind}.
The exam error of beat 1 is EXACTLY this pair, word for word: wrong « {wrong} », right « {right} ».
{type_note}
Beat 4 is "{act4}": {act4_note}
Never mention a level above {level} as the goal (an A1 video never talks of B1 or B2)."""
TYPE_NOTES = {"error": "The first sentence is wrong German: it is shown as the error, then corrected.",
              "upgrade": "The first sentence is CORRECT German, only clumsy or too simple: it is never called an "
                         "error; beat 1 shows it as « correct mais moins naturel » and the second as what the examiner expects."}
ACT4_NOTES = {"A1": "the plain sentence of the lesson enriched with one element of the level (a time, a place, a "
                    "negation), still correct.",
              "A2": "the sentence of the lesson enriched (the past with the Perfekt, a reason with weil), still correct.",
              "B1": "a plain sentence turned into the one an examiner rewards at B1 (a subordinate clause, a connector).",
              "B2": "a plain B1 sentence turned into the B2 one an examiner rewards."}
LANGUAGE_KINDS = ("syntax", "cases", "vocabulary")
LANGUAGE_PROMPT = """You are a curriculum designer for a German channel for French speakers preparing the Goethe or
telc exam, A1 to B2 (age {age}). Research: {research}
The video takes ONE exam error apart in exactly FIVE beats, in this order:
  1. the exam error: the wrong German sentence a French speaker writes or says at the exam, and the right one;
  2. the French trap: why a French speaker makes it (the French construction copied word for word);
  3. the mechanism, shown on the example; by the kind of error:
     syntax (word order, connectors: obwohl, weil, damit, um...zu, the passive): the words move (the verb sent to
       the end, the inversion after a clause in front);
     cases (Wechselpräpositionen, verbs with the dative or accusative, the genitive): the article or ending
       changes (in dem -> in den) with the question that decides it (wo? / wohin?);
     vocabulary (false friends, exam phrases): the wrong word replaced by the right one (bekommen is not
       "devenir": werden);
  4. (unless the episode below says otherwise) the B2 version: a plain B1 sentence turned into the B2 one an examiner rewards (two short sentences
     joined with obwohl; a simple preposition replaced by trotz / wegen + genitive; a basic verb replaced by a
     Nomen-Verb-Verbindung: entscheiden -> eine Entscheidung treffen);
  5. the memo for the exam day: the one image to remember.
Each beat names its German example (correct, short, B1/B2) with its French meaning; one example per beat.
IMPORTANT: The target audience is French. You MUST write all your output in PERFECT FRENCH (JSON keys in English);
the German examples stay German.
Answer with JSON only:
{{"kind": "syntax|cases|vocabulary", "learning_outline": ["beat 1", "beat 2", "beat 3", "beat 4", "beat 5"],
  "aha_moment": "...", "prerequisites": ["..."], "visual_metaphors": ["..."], "scene_count_target": 5}}"""


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    output_path = os.path.join(folder, "outline.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["research.json"])
    research = load_json(os.path.join(folder, "research.json"))
    route = find_route(routes, channel_id)
    if not research or route is None:
        return finish(channel_id, AGENT, "outline", "critical", output_path,
                      error="missing research.json or channel route")

    try:
        kind = research.get("format")
        prompt = {"project": PROJECT_PROMPT, "problem": PROBLEM_PROMPT, "course": COURSE_PROMPT}.get(kind, PROMPT)
        episode = research.get("episode") or {}
        if route.get("domain") == "language":
            kind, prompt = "exam_error", LANGUAGE_PROMPT
            if episode:                    # the programme's episode: its pair, its kind, its level
                level = episode.get("level") or "B1"
                prompt = prompt.replace("\nAnswer with JSON only", EPISODE_NOTE.format(
                    id=episode["id"], level=level, level_title=episode.get("level_title", ""),
                    kind=CURRICULUM_KINDS.get(episode.get("variant"), "syntax"), wrong=episode["wrong_example"],
                    right=episode["right_example"], type_note=TYPE_NOTES.get(episode.get("type"), TYPE_NOTES["error"]),
                    act4=LEVEL_ACT4.get(level, "La version B2"), act4_note=ACT4_NOTES.get(level, ACT4_NOTES["B2"]))
                    .replace("{", "{{").replace("}", "}}") + "\nAnswer with JSON only", 1)
        outline = parse_llm_json(llm_call(prompt.format(age=route["target_age_band"], research=research)))
        if kind in ("project", "problem", "course", "exam_error"):
            outline["format"] = kind
        if kind == "exam_error":           # the five acts are the contract: never more, never fewer
            outline["acts"] = list(LANGUAGE_ACTS)
            outline["scene_count_target"] = len(LANGUAGE_ACTS)
            if outline.get("kind") not in LANGUAGE_KINDS:
                outline["kind"] = "syntax"
            if episode:                    # set by the programme, not by the LLM
                outline["kind"] = CURRICULUM_KINDS.get(episode.get("variant"), outline["kind"])
                outline["acts"][3] = LEVEL_ACT4.get(episode.get("level"), outline["acts"][3])
                outline.update(episode=episode, next_episode=research.get("next_episode"),
                               level_change=research.get("level_change", False))
        if research.get("items"):
            outline["items"] = research["items"]
        if research.get("facts"):          # the script says only these figures (agent003), the QA checks them (agent005)
            outline["facts"] = research["facts"]
    except (RuntimeError, ValueError) as exc:
        return finish(channel_id, AGENT, "outline", "critical", output_path, error=str(exc))

    beats = outline.get("learning_outline", [])
    if len(beats) < 3:
        return finish(channel_id, AGENT, "outline", "critical", output_path, error=f"only {len(beats)} beats")
    save_json(output_path, outline)
    provenance.register_artifact(run_id, channel_id, "outline.json", AGENT)

    status = "healthy" if str(outline.get("aha_moment", "")).strip() else "not_healthy"
    return finish(channel_id, AGENT, "outline", status, output_path,
                  data={"beats": len(beats), "aha_moment": outline.get("aha_moment", "")})


if __name__ == "__main__":
    run_standalone(run)
