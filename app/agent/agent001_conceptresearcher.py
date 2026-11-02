"""
INPUT:  schemas/routes.json (channel_id, name, domain, target_age_band, persona)
        + instance/analytics.json (optional: top_topics, saturated_topics)
OUTPUT: instance/{channel_id}/research.json = {concept, misconceptions[], analogies[],
        sources[{title, url, accessed}], difficulty_assessment, why_now}
NOTES:  Never states a fact without a source URL. Never picks a topic listed in
        analytics.saturated_topics. Never reads another channel's folder.
        Imposed topic: if LBREEZE_TOPIC is set and not empty (the orchestrator's --topic, or this
        agent's own --topic), the LLM researches that topic instead of choosing one, the saturated
        check is skipped (the topic was asked for), and research.json records it as "imposed_topic".
        Without it, the LLM chooses freely, as before.
HEALTH: not_healthy if fewer than 2 sources with a URL;
        critical if llm_call fails, the answer is not valid JSON, or the topic it chose is saturated.
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import (INSTANCE_DIR, channel_dir, find_route, finish, llm_call,
                       load_json, parse_llm_json, run_standalone, save_json)
from app import provenance

AGENT = "agent001"
EMPTY_ANALYTICS = {"top_topics": [], "saturated_topics": [], "by_channel": {}}
TOPIC_ENV = "LBREEZE_TOPIC"      # an imposed topic (set by --topic), for reproducible runs

PROMPT = """You research topics for an educational video channel.
Channel: {name} (domain: {domain}). Audience: age {age}, persona: {persona}.
{scope}
{choice}
Every factual claim must come from a source with a real, public URL. If you cannot cite it, leave it out.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"concept": "...", "misconceptions": ["..."], "analogies": ["..."],
  "sources": [{{"title": "...", "url": "https://..."}}],
  "difficulty_assessment": "...", "why_now": "..."}}"""
# What each domain covers: the concept stays inside it (a "math" channel never gets the seasons).
DOMAIN_SCOPES = {
    "math": "Stay strictly in MATHEMATICS: numbers, fractions, percentages, proportionality, algebra, functions "
            "and their graphs, sequences, probability, statistics, geometry, trigonometry. Never a physics, "
            "astronomy or biology topic, even one that uses some maths.",
    "physics_math": "Stay in PHYSICS (mechanics, energy, waves, fluids, astronomy), with the maths it needs.",
    "electronics": "Stay in ELECTRONICS and electricity: circuits, voltage, current, resistance, components.",
    "economics": "Stay in ECONOMICS: prices, money, inflation, markets, trade, public finance, personal finance.",
}
FREE_CHOICE = """Pick ONE concept that people commonly misunderstand and that can reach an "aha moment" in 90-180 seconds.
Topics that performed well recently: {top}. NEVER pick any of these saturated topics: {saturated}."""
IMPOSED = """Le sujet est imposé : {topic}. Ne pas en choisir un autre.
Within this topic, find the concept people commonly misunderstand, that can reach an "aha moment" in 90-180 seconds."""


def imposed_topic():
    """The topic LBREEZE_TOPIC imposes, or None (the LLM chooses)."""
    return os.environ.get(TOPIC_ENV, "").strip() or None


def run(channel_id: str, settings: dict, routes: list) -> dict:
    output_path = os.path.join(channel_dir(channel_id), "research.json")
    run_id = provenance.check_inputs(channel_id, AGENT, [])          # no input in the channel's folder
    route = find_route(routes, channel_id)
    if route is None:
        return finish(channel_id, AGENT, "research", "critical", output_path, error="channel not in routes.json")

    # Global file written by agent009; missing on the very first run.
    analytics = load_json(os.path.join(INSTANCE_DIR, "analytics.json")) or EMPTY_ANALYTICS
    saturated = analytics.get("saturated_topics", [])

    topic = imposed_topic()
    choice = (IMPOSED.format(topic=topic) if topic
              else FREE_CHOICE.format(top=analytics.get("top_topics", []), saturated=saturated))
    prompt = PROMPT.format(name=route["name"], domain=route["domain"], scope=DOMAIN_SCOPES.get(route["domain"], ""),
                           age=route["target_age_band"],
                           persona=route["persona"], choice=choice)
    try:
        research = parse_llm_json(llm_call(prompt))
    except (RuntimeError, ValueError) as exc:
        return finish(channel_id, AGENT, "research", "critical", output_path, error=str(exc))

    if not topic and research.get("concept", "").lower() in [t.lower() for t in saturated]:
        return finish(channel_id, AGENT, "research", "critical", output_path,
                      data={"concept": research.get("concept")}, error="LLM picked a saturated topic")

    # Keep only sources that carry a URL, and stamp the date we collected them.
    if topic:
        research["imposed_topic"] = topic
    today = date.today().isoformat()
    research["sources"] = [
        {"title": s.get("title", ""), "url": s["url"], "accessed": today}
        for s in research.get("sources", []) if str(s.get("url", "")).startswith(("http://", "https://"))
    ]
    save_json(output_path, research)
    provenance.register_artifact(run_id, channel_id, "research.json", AGENT)

    status = "healthy" if len(research["sources"]) >= 2 else "not_healthy"
    return finish(channel_id, AGENT, "research", status, output_path,
                  data={"concept": research.get("concept"), "source_count": len(research["sources"]),
                        **({"imposed_topic": topic} if topic else {})})


if __name__ == "__main__":
    # --topic "..." sets LBREEZE_TOPIC; the other options are run_standalone's (--channel, --run-id).
    topic_parser = argparse.ArgumentParser(add_help=False)
    topic_parser.add_argument("--topic", help="impose the topic (sets LBREEZE_TOPIC)")
    known, sys.argv[1:] = topic_parser.parse_known_args()
    if known.topic:
        os.environ[TOPIC_ENV] = known.topic
    run_standalone(run)
