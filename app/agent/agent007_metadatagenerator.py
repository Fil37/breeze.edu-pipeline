"""
INPUT:  instance/{channel_id}/script.json + video.mp4 (size only, never decoded) + research.json
        + schemas/routes.json (name, persona) + schemas/words.json (banned_clickbait)
OUTPUT: instance/{channel_id}/metadata.json = {title, description, tags[], thumbnail_brief,
        chapters[], target_keywords[]}
NOTES:  SEO only. Never publishes. Title <= 70 chars, description <= 5000 chars,
        title checked against words.json banned_clickbait.
HEALTH: not_healthy if the title contains a banned term;
        critical if an input is missing, llm_call fails, or metadata.json cannot be serialized.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import (SCHEMAS_DIR, channel_dir, find_route, finish, llm_call, load_json,
                       parse_llm_json, run_standalone, save_json)
from app import provenance

AGENT = "agent007"
MAX_TITLE = 70
MAX_DESCRIPTION = 5000

PROMPT = """You write YouTube metadata for an educational channel: {name} (audience: {persona}).
Concept: {concept}
Sources: {sources}
Scenes: {scenes}
Rules: honest, no clickbait, title at most {max_title} characters, never use: {banned}.
Give one short chapter title per scene, in order.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"title": "...", "description": "...", "tags": ["..."], "thumbnail_brief": "...",
  "chapter_titles": ["..."], "target_keywords": ["..."]}}"""


def timestamp(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def build_chapters(scenes, titles, rendered=None):
    """YouTube chapters ("0:00 Title"). With the render manifest's scenes (`rendered`), their real start
    times, the plan agent010 adds after the hook included; else start times from the script's durations."""
    chapters, start = [], 0.0
    if rendered and all("start_sec" in r for r in rendered):
        index = 0
        for entry in rendered:
            if entry.get("scene_id") == "plan":
                chapters.append(f"{timestamp(entry['start_sec'])} {entry.get('title') or 'Au programme'}")
                continue
            title = titles[index] if index < len(titles) else f"Part {index + 1}"
            chapters.append(f"{timestamp(entry['start_sec'])} {title}")
            index += 1
        return chapters
    for index, scene in enumerate(scenes):
        title = titles[index] if index < len(titles) else f"Part {index + 1}"
        chapters.append(f"{timestamp(start)} {title}")
        start += float(scene.get("duration_sec", 0))
    return chapters


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    output_path = os.path.join(folder, "metadata.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["script.json", "research.json", "video.mp4"])
    script = load_json(os.path.join(folder, "script.json"))
    research = load_json(os.path.join(folder, "research.json"))
    route = find_route(routes, channel_id)
    if not (script and research and route):
        return finish(channel_id, AGENT, "metadata", "critical", output_path,
                      error="missing script, research or channel route")
    video_path = os.path.join(folder, "video.mp4")
    video_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
    banned = load_json(os.path.join(SCHEMAS_DIR, "words.json")).get("banned_clickbait", [])

    prompt = PROMPT.format(name=route["name"], persona=route["persona"], concept=research.get("concept"),
                           sources=research.get("sources"), max_title=MAX_TITLE, banned=banned,
                           scenes=[s.get("narration_text") for s in script["scenes"]])
    try:
        answer = parse_llm_json(llm_call(prompt))
    except (RuntimeError, ValueError) as exc:
        return finish(channel_id, AGENT, "metadata", "critical", output_path, error=str(exc))

    rendered = load_json(os.path.join(folder, "render_manifest.json")).get("scenes")
    chapters = build_chapters(script["scenes"], answer.get("chapter_titles", []), rendered)
    description = str(answer.get("description", "")) + "\n\n" + "\n".join(chapters)
    metadata = {
        "title": str(answer.get("title", ""))[:MAX_TITLE].strip(),
        "description": description[:MAX_DESCRIPTION],
        "tags": answer.get("tags", []),
        "thumbnail_brief": answer.get("thumbnail_brief", ""),
        "chapters": chapters,
        "target_keywords": answer.get("target_keywords", []),
    }
    try:
        save_json(output_path, metadata)
    except (TypeError, ValueError, OSError) as exc:
        return finish(channel_id, AGENT, "metadata", "critical", output_path, error=f"serialization failed: {exc}")
    provenance.register_artifact(run_id, channel_id, "metadata.json", AGENT)

    found = [term for term in banned if term.lower() in metadata["title"].lower()]
    status = "not_healthy" if found else "healthy"
    return finish(channel_id, AGENT, "metadata", status, output_path,
                  data={"title": metadata["title"], "banned_terms_found": found, "video_size_bytes": video_size})


if __name__ == "__main__":
    run_standalone(run)
