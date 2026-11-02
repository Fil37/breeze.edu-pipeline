"""
INPUT:  instance/{channel_id}/outline.json
OUTPUT: instance/{channel_id}/script.json = {scenes:[{scene_id, narration_text, duration_sec,
        key_visual_moment}], total_duration_sec, word_count}
NOTES:  Narration only, aiming at 90-180 s. A scene that cannot be drawn as one visual is split.
        Never names a renderer or a template.
        Redone after a QA reject (reject_to agent003), it gets the QA's feedback in LBREEZE_QA_FEEDBACK
        (app/qa_feedback.py) as a "Corrections demandées par le QA" section of its prompt, with what the
        animation can show: never reads qa.json itself.
HEALTH: not_healthy if total_duration_sec > 200 or < 60;
        critical if outline.json is missing, llm_call fails, or scenes[] is empty.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import channel_dir, finish, llm_call, load_json, parse_llm_json, run_standalone, save_json
from app import provenance
from app.qa_feedback import feedback_section

AGENT = "agent003"
MIN_SCENE_WORDS = 15      # below this a scene's audio is too short for its animations
# What the animation can show, for a rewrite after the QA found the narration asked for the impossible.
DRAWABLE = ("Write narration whose key visual moments the animation can show: electric circuits, graphs and "
            "curves (orbits and circles too), force and velocity arrows, formulas, counters, icons of everyday "
            "objects, people, buildings, vehicles and planets, and bodies moving along a curve. Not: realistic "
            "scenes, one object inside another, light beams, maps or tables.")

PROMPT = """You write narration for a short animated educational video (90 to 180 seconds total).
Learning outline: {outline}
Rules:
- One scene = one visual. If a scene cannot be drawn as ONE visual, split it into two scenes.
- Narration only. Never mention software, renderers or templates.
- Speaking pace is about 2.5 words per second; set duration_sec accordingly.
- Each scene must have a narration of at least 15-20 words to ensure the audio track lasts at least
  6-8 seconds. Do not write very short sentences.
- The narration is SPOKEN aloud: write every formula and symbol in words, as a teacher says it
  ("t indice n", "dix puissance moins n", "y est inférieur à 1", "zéro virgule neuf neuf neuf, à l'infini").
  No LaTeX, no _ ^ {{ }} < > ≤ ≥ in narration_text.
- Scene 1 is the hook (the question, the surprise). Do not announce the plan of the video: it is
  announced automatically right after scene 1, from the scenes' titles.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"scenes": [{{"scene_id": 1, "narration_text": "...", "duration_sec": 15, "key_visual_moment": "..."}}]}}"""


def run(channel_id: str, settings: dict, routes: list) -> dict:
    folder = channel_dir(channel_id)
    output_path = os.path.join(folder, "script.json")
    run_id = provenance.check_inputs(channel_id, AGENT, ["outline.json"])
    outline = load_json(os.path.join(folder, "outline.json"))
    if not outline:
        return finish(channel_id, AGENT, "script", "critical", output_path, error="missing outline.json")

    try:
        qa_section, qa_feedback = feedback_section(AGENT, "script", DRAWABLE)
        if qa_feedback:
            print(f"--- {AGENT}: QA feedback (revision {qa_feedback['revision']}): {qa_feedback['blocking_issues']} "
                  f"blocking issue(s): added to the prompt", file=sys.stderr, flush=True)
        prompt = PROMPT.format(outline=outline).replace("\nAnswer with JSON only", qa_section + "\nAnswer with JSON only", 1)
        answer = parse_llm_json(llm_call(prompt))
    except (RuntimeError, ValueError) as exc:
        return finish(channel_id, AGENT, "script", "critical", output_path, error=str(exc))

    scenes = answer.get("scenes", [])
    if not scenes:
        return finish(channel_id, AGENT, "script", "critical", output_path, error="scenes[] is empty")

    # Totals are computed here, never trusted from the LLM.
    script = {
        "scenes": scenes,
        "total_duration_sec": sum(float(s.get("duration_sec", 0)) for s in scenes),
        "word_count": sum(len(str(s.get("narration_text", "")).split()) for s in scenes),
    }
    save_json(output_path, script)
    provenance.register_artifact(run_id, channel_id, "script.json", AGENT)

    status = "healthy" if 60 <= script["total_duration_sec"] <= 200 else "not_healthy"
    short = [s.get("scene_id") for s in scenes if len(str(s.get("narration_text", "")).split()) < MIN_SCENE_WORDS]
    return finish(channel_id, AGENT, "script", status, output_path,
                  data={"scenes": len(scenes), "total_duration_sec": script["total_duration_sec"],
                        "word_count": script["word_count"], "short_scenes": short})


if __name__ == "__main__":
    run_standalone(run)
