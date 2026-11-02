"""
INPUT:  instance/{channel_id}/outline.json
OUTPUT: instance/{channel_id}/script.json = {scenes:[{scene_id, narration_text, duration_sec,
        key_visual_moment}], plan: {narration, parts:[{scene_id, text, cue}]} | null,
        total_duration_sec, word_count}
NOTES:  Narration only, aiming at 90-180 s. Also the plan announced after the hook (agent010 shows it):
        its spoken narration and what each later scene shows; null when the LLM's plan does not
        match the scenes (agent010 then builds one from the titles). A scene that cannot be drawn as one visual is split.
        Never names a renderer or a template.
        Redone after a QA reject (reject_to agent003), it gets the QA's feedback in LBREEZE_QA_FEEDBACK
        (app/qa_feedback.py) as a "Corrections demandées par le QA" section of its prompt, with what the
        animation can show: never reads qa.json itself.
        An acronym ("BIT", "PIB") is said in full the first time it is spoken (hook, plan, then the
        scenes), in the same sentence or scene: a narration using one before is sent back once.
        The narrator speaks about WORDS_PER_SEC words a second: scenes with fewer than MIN_WORDS words in
        all (a video under 90 s) are sent back once, with the acronyms if any.
HEALTH: not_healthy if total_duration_sec > 200 or < 60, the scenes still have fewer than MIN_WORDS words,
        or an acronym is still used before it is said in full;
        critical if outline.json is missing, llm_call fails, or scenes[] is empty.
"""

import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import channel_dir, finish, llm_call, load_json, parse_llm_json, run_standalone, save_json
from app import provenance
from app.qa_feedback import feedback_section

AGENT = "agent003"
MIN_SCENE_WORDS = 15      # below this a scene's audio is too short for its animations
WORDS_PER_SEC = 3.1       # the narrator's pace (ElevenLabs at speed 1.12: 3.0 to 3.3 measured on the run of 2026-11-02)
MIN_WORDS = 280           # in all the scenes: under this the video is shorter than 90 s at that pace
MAX_WORDS = 520           # ... and over this, longer than about 170 s
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
- Speaking pace is about {pace} words per second; set duration_sec accordingly. All the scenes
  together have {least} to {most} words: explain, give the example, do not rush.
- Each scene must have a narration of at least 15-20 words to ensure the audio track lasts at least
  6-8 seconds. Do not write very short sentences.
- The last scene CLOSES the video: it answers the hook's question in one clear sentence (the "aha"),
  sums up the key idea, and ends on a closing sentence. Never end on a question, a colon, "Vérifions"
  or a new example left unexplained: an example used to check the idea is given AND explained.
- One example, the same values all along: the same battery (6 V in one scene stays 6 V), the same
  prices, the same object, unless the change itself is what a scene shows (then say so).
- The narration is SPOKEN aloud: write every formula and symbol in words, as a teacher says it
  ("t indice n", "dix puissance moins n", "y est inférieur à 1", "zéro virgule neuf neuf neuf, à l'infini").
  No LaTeX, no _ ^ {{ }} < > ≤ ≥ in narration_text.
- An acronym is said in full the first time it is spoken, so a viewer who does not know it is never
  lost: "le Bureau international du travail, le BIT", "le produit intérieur brut, ou PIB"; after
  that, the acronym alone. The hook and the plan are spoken first: define it there if it is used there.
- Scene 1 is the hook (the question, the surprise). Right after it, the video announces its plan:
  write it in "plan". "narration": 2 or 3 natural spoken sentences (25 to 50 words), as a teacher
  tells the class where the lesson goes, in the order of the scenes; not a list read aloud, never
  "D'abord ... Ensuite ... Puis ... Et enfin". "parts": one per scene after scene 1, in order:
  "scene_id"; "text", what that part will show or make clear, as it is written on screen (4 to 9
  words, no final full stop: "Pourquoi une pile a 6 volts sans courant"); "cue", the exact words of
  "narration" (2 to 4 words, copied as written) where that part is announced.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"scenes": [{{"scene_id": 1, "narration_text": "...", "duration_sec": 15, "key_visual_moment": "..."}}],
  "plan": {{"narration": "...", "parts": [{{"scene_id": 2, "text": "...", "cue": "..."}}]}}}}"""
PLAN_TEXT_MAX = 80        # characters of a part's text on screen


def checked_plan(plan, scenes):
    """The plan as agent010 can use it, or None (it then builds one from the scenes' titles): a spoken
    narration and one short text per scene after the hook, each on a scene of the script."""
    if not isinstance(plan, dict) or not isinstance(plan.get("narration"), str) or not plan["narration"].strip():
        return None
    later = [str(s.get("scene_id")) for s in scenes[1:]]
    parts = []
    for part in plan.get("parts") or []:
        if not isinstance(part, dict) or str(part.get("scene_id")) not in later or not isinstance(part.get("text"), str):
            continue
        text = part["text"].strip().rstrip(".")
        if text and len(text) <= PLAN_TEXT_MAX:
            parts.append({"scene_id": str(part["scene_id"]), "text": text,
                          "cue": part["cue"].strip() if isinstance(part.get("cue"), str) else ""})
    if [p["scene_id"] for p in parts] != later:       # one part per scene after the hook, in order
        return None
    return {"narration": plan["narration"].strip(), "parts": parts}


ACRONYM = re.compile(r"(?<![\w'’-])[A-ZÀ-Ý]{2,6}(?![\w'’-])")
ROMAN = re.compile(r"[IVXLCDM]+")
LINK_WORDS = {"de", "du", "des", "la", "le", "les", "l", "d", "et", "en", "à", "a", "au", "aux", "pour", "sur", "un", "une"}
RETRY_NOTE = """

Your previous answer has these problems; rewrite it without them (same JSON shape):
{problems}"""
SHORT_NOTE = ("the scenes have {words} words in all: at about {pace} words per second the video lasts under "
              "90 seconds; write at least {least} words (more explanation and the example worked through in "
              "each scene, not more scenes)")


def said_in_full(acronym, text):
    """Whether `text` says the words the acronym stands for: consecutive words (linking words such as
    "du", "de la" skipped) whose initials spell it ("Bureau international du travail": BIT)."""
    initials = "".join(unicodedata.normalize("NFD", w)[0].upper() for w in re.findall(r"[^\W\d_]+", text)
                       if w.lower() not in LINK_WORDS and w != acronym)
    return acronym in initials


def undefined_acronyms(scenes, plan):
    """["<where>: \"BIT\" ..."] for each acronym whose first spoken use (hook, plan, then the scenes)
    is not said in full in the same text."""
    spoken = [(f"scene {scenes[0].get('scene_id')}", scenes[0].get("narration_text"))] if scenes else []
    spoken += [("plan", (plan or {}).get("narration"))] + [(f"scene {s.get('scene_id')}", s.get("narration_text")) for s in scenes[1:]]
    seen, problems = set(), []
    for where, text in spoken:
        text = str(text or "")
        for acronym in ACRONYM.findall(text):
            if acronym in seen or ROMAN.fullmatch(acronym):
                continue
            seen.add(acronym)
            if not said_in_full(acronym, text):
                problems.append(f'{where}: "{acronym}" is spoken before it is said in full: say what it stands for '
                                f'the first time ("le Bureau international du travail, le BIT")')
    return problems


def word_count(scenes):
    return sum(len(str(s.get("narration_text", "")).split()) for s in scenes)


def script_problems(answer):
    """(acronyms used before being said in full, the scenes' word count): what a retry is asked to fix."""
    scenes = answer.get("scenes") or []
    return undefined_acronyms(scenes, answer.get("plan")), word_count(scenes)


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
        prompt = PROMPT.format(outline=outline, pace=WORDS_PER_SEC, least=MIN_WORDS, most=MAX_WORDS).replace(
            "\nAnswer with JSON only", qa_section + "\nAnswer with JSON only", 1)
        answer = parse_llm_json(llm_call(prompt))
        acronyms, words = script_problems(answer)
        if acronyms or words < MIN_WORDS:   # once more, told what: a viewer never lost on a word, nor rushed
            notes = acronyms + ([SHORT_NOTE.format(words=words, pace=WORDS_PER_SEC, least=MIN_WORDS)] if words < MIN_WORDS else [])
            print(f"--- {AGENT}: asked again: {notes}", file=sys.stderr, flush=True)
            again = parse_llm_json(llm_call(prompt + RETRY_NOTE.format(problems="\n".join(notes))))
            left, more = script_problems(again)
            shortfall = lambda n: max(0, MIN_WORDS - n)
            if again.get("scenes") and len(left) <= len(acronyms) and (len(left), shortfall(more)) < (len(acronyms), shortfall(words)):
                answer, acronyms, words = again, left, more
    except (RuntimeError, ValueError) as exc:
        return finish(channel_id, AGENT, "script", "critical", output_path, error=str(exc))

    scenes = answer.get("scenes", [])
    if not scenes:
        return finish(channel_id, AGENT, "script", "critical", output_path, error="scenes[] is empty")

    # Totals are computed here, never trusted from the LLM.
    script = {
        "scenes": scenes,
        "plan": checked_plan(answer.get("plan"), scenes),
        "total_duration_sec": sum(float(s.get("duration_sec", 0)) for s in scenes),
        "word_count": word_count(scenes),
    }
    save_json(output_path, script)
    provenance.register_artifact(run_id, channel_id, "script.json", AGENT)

    status = "healthy" if 60 <= script["total_duration_sec"] <= 200 and not acronyms and words >= MIN_WORDS else "not_healthy"
    short = [s.get("scene_id") for s in scenes if len(str(s.get("narration_text", "")).split()) < MIN_SCENE_WORDS]
    return finish(channel_id, AGENT, "script", status, output_path,
                  data={"scenes": len(scenes), "total_duration_sec": script["total_duration_sec"],
                        "word_count": script["word_count"], "short_scenes": short, "acronyms_undefined": acronyms})


if __name__ == "__main__":
    run_standalone(run)
