"""
INPUT:  instance/{channel_id}/research.json + schemas/routes.json (target_age_band)
OUTPUT: instance/{channel_id}/outline.json = {learning_outline[], aha_moment, prerequisites[],
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
        outline = parse_llm_json(llm_call(prompt.format(age=route["target_age_band"], research=research)))
        if kind in ("project", "problem", "course"):
            outline["format"] = kind
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
