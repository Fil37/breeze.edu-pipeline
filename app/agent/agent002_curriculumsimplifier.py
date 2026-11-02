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
Do not write narration and do not describe visuals in detail: only the teaching steps.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"learning_outline": ["beat 1", "beat 2", "beat 3", "..."], "aha_moment": "...",
  "prerequisites": ["..."], "visual_metaphors": ["..."], "scene_count_target": 6}}"""


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
        outline = parse_llm_json(llm_call(PROMPT.format(age=route["target_age_band"], research=research)))
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
