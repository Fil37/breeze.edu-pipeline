"""
INPUT:  app/instance/{channel_id}/outline.json
OUTPUT: app/instance/{channel_id}/script.json = {scenes:[{scene_id, narration_text, duration_sec,
        key_visual_moment}], plan: {narration, parts:[{scene_id, text, cue}]} | null, question | null,
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

import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # standalone runs

from app.agent import channel_dir, find_route, finish, llm_call, load_json, parse_llm_json, run_standalone, save_json
from app.language_examples import foreign_quotes, tokens
from app import provenance
from app.qa_feedback import feedback_section

AGENT = "agent003"
# What this agent can do (the studio kit's skills, registered by agent000 at start: "proposed" until the
# user approves their activation on the standup).
SKILLS = [
    {"skill_id": "narration_script", "version": "1.0", "objective": "Write the spoken narration, scene by scene",
     "summary": "Pace and length per channel; acronyms said in full; one example per scene for German."},
]
MIN_SCENE_WORDS = 15      # below this a scene's audio is too short for its animations
WORDS_PER_SEC = 3.1       # the narrator's pace (ElevenLabs at speed 1.12: 3.0 to 3.3 measured on the run of 2026-11-02)
MIN_WORDS = 280           # in all the scenes: under this the video is shorter than 90 s at that pace
MAX_WORDS = 520           # ... and over this, longer than about 170 s
DEFAULT_SPEED = 1.12      # the ElevenLabs speed WORDS_PER_SEC was measured at (tts_manager.ELEVENLABS_SETTINGS)


def channel_pace(settings, channel_id):
    """(words a second, least words, most words) at the channel's voice speed: a slower voice (the German
    channel speaks at 0.9, for learners to hear the pronunciation) says fewer words in the same time."""
    voice = settings.get("voice_by_channel", {}).get(channel_id) or {}
    speed = voice.get("speed") or DEFAULT_SPEED
    factor = float(speed) / DEFAULT_SPEED
    if isinstance(voice.get("words"), list) and len(voice["words"]) == 2:     # the channel's own length
        return voice.get("words_per_sec") or round(WORDS_PER_SEC * factor, 1), int(voice["words"][0]), int(voice["words"][1])
    return round(WORDS_PER_SEC * factor, 1), round(MIN_WORDS * factor), round(MAX_WORDS * factor)
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
- Facts and figures: the outline's "facts" are the only real-world figures you may state (a threshold,
  a number of people, an amount, a date); never another one. A measure, a law, a tax, a policy or a
  news event: its first scene(s) say what it is, who proposed it and when, where it stands and who is
  concerned, before its mechanism. An illustrative example is said as one ("imaginons une fortune de
  200 millions d'euros") and respects the facts (above the threshold if there is one).
- One example, the same values all along: the same battery (6 V in one scene stays 6 V), the same
  prices, the same object, unless the change itself is what a scene shows (then say so).
- The narration is SPOKEN aloud: write every formula and symbol in words, as a teacher says it
  ("t indice n", "dix puissance moins n", "y est inférieur à 1", "zéro virgule neuf neuf neuf, à l'infini").
  No LaTeX, no _ ^ {{ }} < > ≤ ≥ in narration_text.
- Electronics: ONE circuit per scene (two amplifiers in one drawing tangle into an unreadable picture);
  each resistor named with its value ("R1 de 10 kΩ"), the gain worked out with those values ("moins
  R2 sur R1 : moins 2"), and the input and output voltages said, so the drawing can show them.
- Electrical values with their prefix, written with the unit's symbol: "10 kΩ", "4,7 kΩ", "10 mA",
  "100 µF" (the voice says "dix kilo ohms"), never "mille ohms" nor "1 000 Ω".
- A temperature is written in digits followed by "degrés Celsius" ("37 degrés Celsius", never
  "trente-sept degrés" in words: the voice says the digits right).
- An acronym is said in full the first time it is spoken, so a viewer who does not know it is never
  lost: "le Bureau international du travail, le BIT", "le produit intérieur brut, ou PIB"; an English
  acronym is said with what it is: "un FPGA, c'est-à-dire une puce dont on peut recâbler les circuits";
  after that, the acronym alone. ET, OU, NON (the logic gates) are words, not acronyms. The hook and the plan are spoken first: define it there if it is used there.
- A technical word (bourrelet, référentiel, monnaie scripturale, fiduciaire, dépôt à vue, nœud
  d'une orbite...) is explained in plain words the first time it is spoken, so the viewer pictures it:
  "deux bourrelets, c'est-à-dire deux bosses d'eau", "la monnaie scripturale, l'argent écrit sur les
  comptes". Before that, say it in everyday words.
- "question": the question the whole video answers, as a curious viewer would ask it, in everyday
  words (no technical word), at most 70 characters, ending with "?": "La monnaie, ce n'est que des
  pièces et des billets ?", "Pourquoi la mer monte deux fois par jour ?". It is written on screen as
  the video's first title; the last scene answers it.
- Scene 1 is the hook (the question, the surprise). Right after it, the video announces its plan:
  write it in "plan". "narration": 2 or 3 natural spoken sentences (25 to 50 words), as a teacher
  tells the class where the lesson goes, in the order of the scenes; not a list read aloud, never
  "D'abord ... Ensuite ... Puis ... Et enfin". "parts": one per scene after scene 1, in order:
  "scene_id"; "text", what that part will show or make clear, as it is written on screen (4 to 9
  words, no final full stop: "Pourquoi une pile a 6 volts sans courant"); "cue", the exact words of
  "narration" (2 to 4 words, copied as written) where that part is announced.
IMPORTANT: The target audience is French. You MUST write all your output (text, explanations, titles, descriptions, tags) in PERFECT FRENCH. The JSON keys must remain in English, but the VALUES must be in French.
Answer with JSON only:
{{"question": "...?", "scenes": [{{"scene_id": 1, "narration_text": "...", "duration_sec": 15, "key_visual_moment": "..."}}],
  "plan": {{"narration": "...", "parts": [{{"scene_id": 2, "text": "...", "cue": "..."}}]}}}}"""
PLAN_TEXT_MAX = 80        # characters of a part's text on screen
QUESTION_MAX = 80         # characters of the video's question, its first title


def checked_question(question):
    """The video's question as agent004 writes it as the hook's title, or None: a short line ending
    with "?"."""
    if not isinstance(question, str):
        return None
    question = " ".join(question.split())
    return question if question.endswith("?") and 15 <= len(question) <= QUESTION_MAX else None


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
CAPITAL_WORDS = {"ET", "OU", "NON", "OUI", "SI"}     # words written in capitals (logic gates), not acronyms
EXPLAINED = re.compile(r"c'est-à-dire|c’est-à-dire|autrement dit|signifie|veut dire|qu'on appelle|qu’on appelle|en anglais",
                       re.IGNORECASE)
LINK_WORDS = {"de", "du", "des", "la", "le", "les", "l", "d", "et", "en", "à", "a", "au", "aux", "pour", "sur", "un", "une"}
# A project built step by step (outline "format": "project", agent002): one build stage a scene.
PROJECT_RULES = """
This video is a PROJECT BUILT STEP BY STEP, not a lesson on one concept:
- The hook starts from what it is FOR, in everyday life, before naming the project: where the need
  comes from and the problem it solves (for a temperature regulation: a chick incubator, an aquarium,
  a 3D printer's bed, a proofing dough must stay at the right temperature, and by hand we keep
  forgetting or overshooting). The question is about that need ("Comment garder une couveuse à 37
  degrés sans y penser ?"); only then does it say what we will build to answer it.
- Then each scene is ONE build stage, in the order of the build: it names the parts it adds, with
  their values ("une résistance de dix kilo-ohms"), says what each does, says exactly what is connected
  to what ("la CTN va de l'entrée moins au zéro volt"), then how to check this stage works.
- The second to last scene builds it on a breadboard, part after part, in the same order.
- The last scene powers it up and shows it doing its job, and closes the video.
"""
PROBLEM_RULES = """
This video SOLVES A PROBLEM, not a lesson on why the method works:
- The hook states the situation and asks its question ("Au cinéma, combien coûte une place adulte ?").
- One scene states the problem IN FULL, every number of it, then one scene names the unknowns and writes
  the equations, each from one sentence of the statement.
- Then one scene per step of the method, saying the operation and what it eliminates ("je retire deux
  fois la première ligne à la deuxième : les adultes disparaissent"), the system shown after it.
- Then the back substitution, the check (the values put back into the statement), and the last scene
  gives the answer in the situation's words ("une place adulte coûte 12 euros") and closes the video.
"""
COURSE_RULES = """
This video is a COURSE on several things, not one idea from one angle:
- The hook says what they are all for (the need they share) and announces them.
- Then ONE scene per item of the outline, every one (none left out, none merged): what it is, how it
  works, its key formula with values and the result worked out aloud, a concrete use.
- The last scene compares them (when to use which) and closes the video.
"""
# Physics and maths (routes.json domain): the key relation of the topic is said, so it can be written
# (the standing waves of 2026-11-05 had none: all words, no formula on screen).
FORMULA_DOMAINS = ("math", "physics_math")
# German taught in French (routes.json domain "language"): the examples are said in German, then in French.
LANGUAGE_RULES = """
- German taught to French speakers: explain in French; every example is a short, correct German sentence
  written exactly as it is said ("Ich lerne Deutsch, weil ich nach Berlin gehe."), followed by its
  French meaning. Build each rule on an example the viewer sees change: first the plain sentence, then
  the same sentence transformed. Name the conjugated verb and where it goes ("le verbe conjugué, gehe,
  part à la fin"). Each scene has its own example, the one its point needs: never the same German
  sentence in two scenes (an earlier one may come back only transformed, or in the last scene's recap);
  a scene that names dass or wenn gives an example with it ("Ich weiß, dass du müde bist." : je sais que
  tu es fatigué). A wrong sentence is said as wrong ("l'erreur fréquente : ..."), never as a plain example.
- Every German word or sentence in the narration is written between « » (« Obwohl ich müde bin », « bin »,
  « trotzdem »): the voice says what is between « » in German, the rest in French. A whole German sentence
  is NOT translated aloud: its French meaning is written under it on screen; say a meaning only when it IS the
  point (a false friend: « bekommen » veut dire recevoir, pas devenir). The voice explains the error, it does
  not read the subtitles of the examples.
- The wrong sentence is really wrong German, not a correct sentence with another meaning: « Ich gehe im
  Park » is correct (je me promène dans le parc), so it is never "the error"; for the two-case prepositions,
  use a verb of placing or going to a place (« Ich lege das Buch auf dem Tisch » is the error, « auf den
  Tisch » the right one).
- No comparison with English (« ressemble à l'anglais become »): the viewer learns German from French.
- Never describe a drawing (« un point bleu », « une flèche rouge »): the screen shows the German sentences
  themselves; the memo is a sentence to remember, not a picture.
"""
# The language channel's contract (agent002 "format": "exam_error", its "acts"): one scene per act.
EXAM_ERROR_RULES = """
- EXACTLY FIVE scenes, one per act of the outline's "acts", in that order (scene_id 1 to 5), each its own
  example: 1. the exam error (« the wrong sentence » next to « the right one », what it costs at the Goethe
  or telc exam); 2. the French trap (the French sentence copied word for word, why the reflex is logical);
  3. the mechanism (by the outline's "kind": syntax, the words that move; cases, the article or ending that
  changes and the question that decides it; vocabulary, the wrong word replaced by the right one); 4. the
  B2 version (a plain B1 sentence, then the B2 one an examiner rewards); 5. the memo for the exam day (the
  one image to remember, a closing sentence wishing good luck for the exam).
- The plan has one part per scene after the hook (scenes 2 to 5, the memo too), in everyday words (the
  episode a1_01 of 2026-11-20 announced three of the four: its plan was dropped, the video had none).
"""
# An episode of the programme (agent001 "curriculum"): its pair, its level, and the video's ending.
EPISODE_RULES = """
- This is episode {id}, level {level}. Scene 1 says the curriculum's pair word for word: « {wrong} » {type_said},
  then « {right} ». {level_rule}
- The LAST scene ends, after the memo, in three short sentences: the one reflex to keep from this lesson; {teaser};
  then « Abonnez-vous pour ne pas rater la suite du programme jusqu'au B2. »
"""
TYPE_SAID = {"error": "(the error)", "upgrade": "(correct but less natural: NEVER called an error)"}


def episode_rules(outline):
    """The prompt section for an episode of the programme, "" for any other video."""
    episode, following = outline.get("episode"), outline.get("next_episode")
    if not episode:
        return ""
    level = episode.get("level", "")
    if not following:
        teaser = "a sentence saying the programme is complete"
    elif outline.get("level_change"):
        teaser = (f"a sentence celebrating the end of level {level} and announcing that the next video starts "
                  f"level {following['level']} with « {following['topic']} »")
    else:
        teaser = (f"one question that makes the viewer want the next episode, on its trap: « {following['topic']} » "
                  f"(« Dans le prochain épisode, ... »)")
    level_rule = ("Never mention B1, B2 or a later level: the viewer is at " + level + "."
                  if level in ("A1", "A2") else "")
    return EPISODE_RULES.format(id=episode["id"], level=level, wrong=episode["wrong_example"], right=episode["right_example"],
                                type_said=TYPE_SAID.get(episode.get("type"), TYPE_SAID["error"]), level_rule=level_rule,
                                teaser=teaser)


def episode_problems(scenes, outline):
    """What an episode's script must hold (the programme of 2026-11-20): the pair in scene 1, no higher level
    named at A1/A2, the ending (the next episode, the call to subscribe)."""
    episode = outline.get("episode")
    if not episode or not scenes:
        return []
    problems, first, last = [], str(scenes[0].get("narration_text") or ""), str(scenes[-1].get("narration_text") or "")
    said = [tokens(q) for _, _, q in foreign_quotes(first, "de", tokens(episode["wrong_example"] + " " + episode["right_example"]))]
    for name in ("wrong_example", "right_example"):
        if tokens(episode[name]) not in said:
            problems.append(f"scene 1 does not say « {episode[name]} » word for word, between « »: it is the episode's "
                            f"{'error' if name == 'wrong_example' else 'right sentence'}")
    if episode.get("level") in ("A1", "A2"):
        # the call to subscribe names the programme's goal ("jusqu'au B2"): the only place a higher level is said
        aside = lambda text: re.sub(r"[^.!?]*abonn[^.!?]*[.!?]?", "", str(text or ""), flags=re.IGNORECASE)
        higher = [s.get("scene_id") for s in scenes if re.search(r"\b(B1|B2|C1)\b", aside(s.get("narration_text")))]
        higher += ["plan"] if re.search(r"\b(B1|B2|C1)\b", json.dumps(outline.get("plan") or "")) else []
        if higher:
            problems.append(f"scenes {higher} name a level above {episode['level']}: the viewer is at {episode['level']}, "
                            f"say « une phrase plus riche », never B1 / B2")
    if "abonn" not in last.lower():
        problems.append("the last scene does not end with « Abonnez-vous pour ne pas rater la suite du programme jusqu'au B2. »")
    if outline.get("next_episode") and not re.search(r"prochain|prochaine|suite|niveau", last, re.IGNORECASE):
        problems.append("the last scene does not announce the next episode")
    return problems
FORMULA_RULES = """
- Physics and maths: say the KEY RELATION of the topic at least once, in words as a teacher says it,
  with the values of the example ("la longueur d'onde vaut deux fois la longueur de la corde divisée par
  n : pour une corde de 60 centimètres et n égal 2, 60 centimètres"); it is written on screen as a
  formula in that scene. One or two relations in the video, explained, not a list of formulas.
- Never read a whole system, matrix or table aloud number after number: the screen shows it; say the
  operation and what it changes ("j'ajoute la première ligne à la troisième : les x disparaissent"),
  at most one or two numbers per sentence, and one idea per scene.
- Never a measure out of nowhere ("l'arc mesure 1 200 kilomètres"): a number said comes with where it
  comes from (a given of the example, or worked out aloud from one). Prefer how many times more
  ("deux fois plus près, donc deux fois plus vite") to invented distances.
"""
RETRY_NOTE = """

Your previous answer has these problems; rewrite it without them (same JSON shape):
{problems}"""
LONG_NOTE = ("the scenes have {words} words in all: the channel's videos last about two minutes; write at most "
             "{most} words (one example per scene, no French meaning said for a single word: it is on screen)")
SHORT_NOTE = ("the scenes have {words} words in all: at about {pace} words per second the video lasts under "
              "90 seconds; write at least {least} words (more explanation and the example worked through in "
              "each scene, not more scenes)")


def said_in_full(acronym, text):
    """Whether `text` says the words the acronym stands for: consecutive words (linking words such as
    "du", "de la" skipped) whose initials spell it ("Bureau international du travail": BIT), or, in
    the sentence where it first comes, what it is ("un FPGA, c'est-à-dire une puce...")."""
    first = text.find(acronym)
    sentence = re.split(r"(?<=[.!?…])\s+", text[first:])[0] if first >= 0 else ""
    if EXPLAINED.search(text[max(0, text.rfind(".", 0, first) + 1):first] + sentence):
        return True
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
            if acronym in seen or ROMAN.fullmatch(acronym) or acronym in CAPITAL_WORDS:
                continue
            seen.add(acronym)
            if not said_in_full(acronym, text):
                problems.append(f'{where}: "{acronym}" is spoken before it is said in full: say what it stands for '
                                f'(or what it is) the first time ("le produit intérieur brut, le PIB"; "un FPGA, c\'est-à-dire une puce '
                                f'dont on peut recâbler les circuits")')
    return problems


def word_count(scenes):
    return sum(len(str(s.get("narration_text", "")).split()) for s in scenes)


def repeated_examples(scenes, language="de"):
    """A language channel: the same German sentence said in two scenes (the German run of 2026-11-16:
    « weil ich krank bin » in scenes 1, 3, 4 and 5, one example all along); the last scene, a recap, may
    say an earlier one again. Sentences of 3 words or more."""
    where = {}
    for scene in scenes[:-1]:
        for _, _, quote in foreign_quotes(scene.get("narration_text"), language):
            if len(tokens(quote)) >= 3:
                where.setdefault(tokens(quote), []).append(str(scene.get("scene_id")))
    return [f"scenes {sorted(set(ids))} all say « {' '.join(said)} »: give each scene its own example, the one its "
            f"point needs (another verb, a sentence with dass or wenn where the scene names them, the clause in front); "
            f"an earlier sentence comes back only transformed" for said, ids in where.items() if len(set(ids)) > 1]


def acts_problems(scenes, acts):
    """The language channel's five acts: one scene each (the contract of 2026-11-20); [] for other formats."""
    if not acts or len(scenes) == len(acts):
        return []
    return [f"{len(scenes)} scenes: the video has EXACTLY {len(acts)}, one per act in this order: " + "; ".join(
        f"{i}. {act}" for i, act in enumerate(acts, start=1))]


def script_problems(answer, domain=None, acts=None, outline=None):
    """(problems: acronyms used before being said in full, a language channel's repeated examples and acts;
    the scenes' word count): what a retry is asked to fix."""
    scenes = answer.get("scenes") or []
    return (undefined_acronyms(scenes, answer.get("plan")) + (repeated_examples(scenes) if domain == "language" else [])
            + acts_problems(scenes, acts) + episode_problems(scenes, outline or {}), word_count(scenes))


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
        pace, least, most = channel_pace(settings, channel_id)
        domain = (find_route(routes, channel_id) or {}).get("domain")
        prompt = PROMPT.format(outline=outline, pace=pace, least=least, most=most).replace(
            "\nAnswer with JSON only", qa_section + {"project": PROJECT_RULES, "problem": PROBLEM_RULES, "course": COURSE_RULES}.get(outline.get("format"), "")
            + (FORMULA_RULES if (find_route(routes, channel_id) or {}).get("domain") in FORMULA_DOMAINS else "")
            + (LANGUAGE_RULES if (find_route(routes, channel_id) or {}).get("domain") == "language" else "")
            + (EXAM_ERROR_RULES if outline.get("format") == "exam_error" else "")
            + episode_rules(outline)
            + "\nAnswer with JSON only", 1)
        answer = parse_llm_json(llm_call(prompt))
        acronyms, words = script_problems(answer, domain, outline.get("acts"), outline)
        # a channel with its own length (the German run 5 of 2026-11-20: 419 words for 270 to 330) is held to it
        capped = isinstance((settings.get("voice_by_channel", {}).get(channel_id) or {}).get("words"), list)
        too_long = capped and words > most
        if acronyms or words < least or too_long:   # once more, told what: a viewer never lost on a word, nor rushed
            notes = acronyms + ([SHORT_NOTE.format(words=words, pace=pace, least=least)] if words < least else []) \
                + ([LONG_NOTE.format(words=words, most=most)] if too_long else [])
            print(f"--- {AGENT}: asked again: {notes}", file=sys.stderr, flush=True)
            again = parse_llm_json(llm_call(prompt + RETRY_NOTE.format(problems="\n".join(notes))))
            left, more = script_problems(again, domain, outline.get("acts"), outline)
            shortfall = lambda n: max(0, least - n) + (max(0, n - most) if capped else 0)
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
        "question": checked_question(answer.get("question")),
        "total_duration_sec": sum(float(s.get("duration_sec", 0)) for s in scenes),
        "word_count": word_count(scenes),
    }
    for key in ("episode", "next_episode", "level_change"):    # the storyboard and the ending read them (agent004, agent010)
        if outline.get(key) is not None:
            script[key] = outline[key]
    save_json(output_path, script)
    provenance.register_artifact(run_id, channel_id, "script.json", AGENT)

    least = channel_pace(settings, channel_id)[1]
    status = "healthy" if 60 <= script["total_duration_sec"] <= 200 and not acronyms and words >= least else "not_healthy"
    short = [s.get("scene_id") for s in scenes if len(str(s.get("narration_text", "")).split()) < MIN_SCENE_WORDS]
    return finish(channel_id, AGENT, "script", status, output_path,
                  data={"scenes": len(scenes), "total_duration_sec": script["total_duration_sec"],
                        "word_count": script["word_count"], "short_scenes": short, "acronyms_undefined": acronyms})


if __name__ == "__main__":
    run_standalone(run)
