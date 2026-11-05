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
        Novelty: the topic is checked against the channel's topics already made into a video (breeze.db,
        runs that ended healthy or not_healthy): first word by word (the same key words), then by the
        LLM, asked whether it is the same subject in other words or from another angle. A repeat is
        sent back with the reason, up to TOPIC_ATTEMPTS answers; research.json records the check in
        "novelty". An imposed topic is checked too, but only reported.
HEALTH: not_healthy if fewer than 2 sources with a URL, if an imposed topic repeats one already made,
        or if the novelty check could not run (LLM error);
        critical if llm_call fails, the answer is not valid JSON, the topic it chose is saturated, or
        every answer repeats a topic already made.
"""

import argparse
import os
import re
import sys
import unicodedata
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import (INSTANCE_DIR, channel_dir, db_connect, find_route, finish, llm_call,
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
# A topic to BUILD ("réaliser un banc", "construire", "monter", "projet", "pas à pas"): the video is a
# project made step by step, not one concept explained; agent002 and agent003 then plan and write it
# as build stages (research "format": "project").
PROJECT_WORDS = re.compile(r"\b(?:réalis\w*|construi\w*|fabriqu\w*|monter|montage|projet|pas à pas|banc)\b", re.IGNORECASE)
IMPOSED_PROJECT = """Le sujet est imposé, et c'est un PROJET À RÉALISER pas à pas : {topic}. Ne pas en choisir un autre.
The concept IS this project: what is built and what it does once finished. Research its stages in the
order they are built (the parts of each, with real values, and what each does), how they are wired,
how each stage is checked, and the mistakes a beginner makes building it (they are the misconceptions).
Add to the JSON "stages": ["...", "..."], the build stages in order."""
IMPOSED = """Le sujet est imposé : {topic}. Ne pas en choisir un autre.
Within this topic, find the concept people commonly misunderstand, that can reach an "aha moment" in 90-180 seconds."""


COVERED = """Topics this channel has ALREADY made a video on: {past}.
NEVER pick one of them again, nor the same idea in other words or from another angle (the same
misconception explained again): pick a different concept."""
REJECTED = """Already refused because the channel has covered them: {rejected}."""
TOPIC_ATTEMPTS = 3
NOVELTY_PROMPT = """You check that a new educational video does not repeat one the channel has already made.
Channel: {name}. Topics already made into a video:
{past}
New topic: {concept}
Its misconceptions: {misconceptions}
Is the new topic the SAME subject as one already made: the same idea or the same misconception,
even in other words or from another angle, so that a viewer would feel they had already seen this
video? Another concept of the same field is NOT the same subject.
Answer with JSON only: {{"duplicate_of": "<the topic already made, copied exactly>" or null,
"reason": "<one sentence, in French>"}}"""
# Word-by-word repeat: the key words (4 letters or more, accents and endings dropped) of the shorter
# topic mostly found in the other.
STOPWORDS = {"pour", "dans", "avec", "sans", "mais", "plus", "moins", "tres", "comme", "quoi", "pourquoi",
             "comment", "vraiment", "cest", "est-ce", "sont", "elle", "elles", "leur", "leurs", "cette",
             "entre", "tout", "tous", "toute", "toutes", "faut", "fait", "font", "peut", "pas", "une", "des"}
WORDS_OVERLAP = 0.6


def past_topics(channel_id):
    """The channel's topics already made into a video (newest first, each once)."""
    with db_connect() as conn:
        rows = conn.execute("SELECT topic FROM runs WHERE channel = ? AND topic IS NOT NULL AND topic != '' "
                            "AND overall_status IN ('healthy', 'not_healthy') ORDER BY started_at DESC", (channel_id,))
        return list(dict.fromkeys(row["topic"] for row in rows))


def key_words(text):
    plain = unicodedata.normalize("NFKD", str(text).lower()).encode("ascii", "ignore").decode()
    return {w[:6] for w in re.findall(r"[a-z]{4,}", plain) if w not in STOPWORDS}


def same_words(concept, past):
    """The topic already made whose key words the new one mostly repeats, or None."""
    new = key_words(concept)
    for topic in past:
        old = key_words(topic)
        if len(new) >= 2 and len(old) >= 2 and len(new & old) / min(len(new), len(old)) >= WORDS_OVERLAP:
            return topic
    return None


def novelty(research, past, route):
    """None when the topic is new; else {"duplicate_of", "reason", "by"}. Raises RuntimeError /
    ValueError when the LLM cannot be asked (the caller reports the check as not run)."""
    concept = str(research.get("concept") or "")
    if not past:
        return None
    match = same_words(concept, past)
    if match:
        return {"duplicate_of": match, "reason": "mêmes mots-clés qu'un sujet déjà traité", "by": "words"}
    answer = parse_llm_json(llm_call(NOVELTY_PROMPT.format(
        name=route["name"], past="\n".join(f"- {t}" for t in past), concept=concept,
        misconceptions=research.get("misconceptions", []))))
    duplicate = answer.get("duplicate_of") if isinstance(answer, dict) else None
    if isinstance(duplicate, str) and duplicate.strip() and duplicate.strip().lower() not in ("null", "none"):
        return {"duplicate_of": duplicate.strip(), "reason": str(answer.get("reason") or ""), "by": "llm"}
    return None


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
    past = past_topics(channel_id)
    rejected = []
    check = {"checked_against": len(past), "attempts": 0, "rejected": rejected, "verdict": "new"}
    for attempt in range(1, (1 if topic else TOPIC_ATTEMPTS) + 1):
        project = bool(topic and PROJECT_WORDS.search(topic))
        choice = ((IMPOSED_PROJECT if project else IMPOSED).format(topic=topic) if topic
                  else FREE_CHOICE.format(top=analytics.get("top_topics", []), saturated=saturated))
        if past and not topic:
            choice += "\n" + COVERED.format(past=past)
        if rejected:
            choice += "\n" + REJECTED.format(rejected=[f"{r['concept']} ({r['reason']})" for r in rejected])
        prompt = PROMPT.format(name=route["name"], domain=route["domain"], scope=DOMAIN_SCOPES.get(route["domain"], ""),
                               age=route["target_age_band"],
                               persona=route["persona"], choice=choice)
        try:
            research = parse_llm_json(llm_call(prompt))
        except (RuntimeError, ValueError) as exc:
            return finish(channel_id, AGENT, "research", "critical", output_path, error=str(exc))
        check["attempts"] = attempt
        try:
            repeat = novelty(research, past, route)
        except (RuntimeError, ValueError) as exc:      # the check could not run: keep the topic, say so
            check["verdict"], check["error"] = "unchecked", str(exc)[:200]
            break
        if repeat is None:
            check["verdict"] = "new"
            break
        rejected.append({"concept": research.get("concept"), **repeat})
        print(f"--- {AGENT}: topic {research.get('concept')!r} repeats {repeat['duplicate_of']!r} "
              f"({repeat['by']}: {repeat['reason']})" + ("" if topic else ": asking for another one"),
              file=sys.stderr, flush=True)
        check["verdict"] = "duplicate"
    if check["verdict"] == "duplicate" and not topic:
        return finish(channel_id, AGENT, "research", "critical", output_path, data={"novelty": check},
                      error=f"every topic proposed repeats one already made ({TOPIC_ATTEMPTS} attempts)")
    research["novelty"] = check                        # an imposed topic that repeats one: kept, reported

    if not topic and research.get("concept", "").lower() in [t.lower() for t in saturated]:
        return finish(channel_id, AGENT, "research", "critical", output_path,
                      data={"concept": research.get("concept")}, error="LLM picked a saturated topic")

    # Keep only sources that carry a URL, and stamp the date we collected them.
    if topic:
        research["imposed_topic"] = topic
    if topic and PROJECT_WORDS.search(topic):          # a build: the project itself, its stages in order
        research.update(format="project", concept=topic)
    today = date.today().isoformat()
    research["sources"] = [
        {"title": s.get("title", ""), "url": s["url"], "accessed": today}
        for s in research.get("sources", []) if str(s.get("url", "")).startswith(("http://", "https://"))
    ]
    save_json(output_path, research)
    provenance.register_artifact(run_id, channel_id, "research.json", AGENT)

    status = "healthy" if len(research["sources"]) >= 2 and check["verdict"] == "new" else "not_healthy"
    return finish(channel_id, AGENT, "research", status, output_path,
                  data={"concept": research.get("concept"), "source_count": len(research["sources"]),
                        "novelty": {k: check[k] for k in ("verdict", "attempts", "checked_against")},
                        **({"imposed_topic": topic} if topic else {})})


if __name__ == "__main__":
    # --topic "..." sets LBREEZE_TOPIC; the other options are run_standalone's (--channel, --run-id).
    topic_parser = argparse.ArgumentParser(add_help=False)
    topic_parser.add_argument("--topic", help="impose the topic (sets LBREEZE_TOPIC)")
    known, sys.argv[1:] = topic_parser.parse_known_args()
    if known.topic:
        os.environ[TOPIC_ENV] = known.topic
    run_standalone(run)
