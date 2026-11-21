"""
Check the SENTENCE piece (German word order, made for the breeze_(allemand) channel: the maths channel's
demo of 2026-11-16 on "weil, dass, wenn" turned into a video on why German is not maths, and agent004
had no piece to show a sentence, every scene forced to "circuit"):
  1. good states accepted; a role out of the list, a bad "order", too many words, refused
  2. the tiles worked out to fit the line: a 14-word sentence shrinks its font, stays inside the piece
  3. drawn with no layout conflict; the verb slides to the end on set_state "order": before it, the comma
     and "weil" are not shown, after it they are and the verb is the last word; focus and translation
  4. preview images (instance/previews/sentence/) to look at
  5. the second German run's fixes: a "label" and "verdict" shown; two neighbours swapped, the verb jumps
     over (it went through "müde"); a scene with a SENTENCE stays full width (never comparison panels); a
     scene that says the verb moves while no SENTENCE moves is sent back
  6. the third run's fixes, on its scene 3 (the subordinate clause put first): "Weil" gets its capital and
     "Ich" loses it; the label once, over the line; the two clauses pass in two lanes, never through
     each other
  7. the fourth run's fixes (run 3 of 2026-11-16): a wrong order is judged by the program ("ich heute bleibe
     zu Hause", "weil ich bin krank"; the right ones of the three German runs accepted), marked ✗ then ✓ on
     the move that corrects it; sent back: a wrong order unmarked, a label naming dass over a weil
     sentence, a sentence said in full but shown in part, the same move in two scenes, the same example
     said in two scenes of the script; a clause alone keeps its small letter ("weil ich krank bin")
  8. (and run 4: no arrow on a sentence, a status badge kept; "Berlin" in a French meaning said in French)
     the voice: the German examples split from the French, said apart (« Ich bleibe heute zu Hause »,
     "bleibe", "weil, dass"), the French meanings left French (« je reste à la maison »)
  10. the French meaning shown by itself once the words are in ("Sens voulu : " under a wrong sentence), at its
     action's time when one says it; a sentence without one sent back
  11. the channel's mark (watermark_by_channel): bottom right, clear of the subtitles (they end at x 1740); none
      without one, a missing file said, not fatal
  9. the five acts (2026-11-20): a language script with another number of scenes sent back, five accepted; the
     channel's own length; a word that changes ("dem" -> "den") judged and drawn: one fades away, one in
Prints PASS or FAIL per case. Cases 3 and 4 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_sentence.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, simple_piece_problem   # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


WORDS = [{"text": "Ich", "role": "subject"}, {"text": "lerne", "role": "verb"}, {"text": "Deutsch", "role": "object"},
         {"text": ",", "role": "punct"}, {"text": "weil", "role": "conjunction"}, {"text": "ich", "role": "subject"},
         {"text": "gehe", "role": "verb"}, {"text": "nach", "role": "other"}, {"text": "Berlin", "role": "object"}]
STATE = {"words": WORDS, "order": [0, 1, 2, 5, 6, 7, 8], "translation": "J'apprends l'allemand parce que je vais à Berlin"}
FINAL = [0, 1, 2, 3, 4, 5, 7, 8, 6]


def brief():
    return {"scene_id": "2", "text_overlay": {"title": "Le verbe part à la fin"}, "connections": [],
            "entities": [{"id": "s", "type": "SENTENCE", "position": [0, -0.3, 0], "initial_state": STATE}],
            "actions": [{"at": 2.0, "action": "set_state", "target": "s", "state": {"order": FINAL}, "cue": "weil"},
                        {"at": 3.5, "action": "set_state", "target": "s", "state": {"focus": 6}, "cue": "gehe"},
                        {"at": 4.0, "action": "set_state", "target": "s", "state": {"translation": True}, "cue": "parce que"}]}


def case_states():
    problems = []
    if simple_piece_problem("SENTENCE", STATE):
        problems.append(f"good state refused: {simple_piece_problem('SENTENCE', STATE)}")
    bad = {"role": {"words": [{"text": "Ich", "role": "pronoun"}, {"text": "bin", "role": "verb"}]},
           "order": {"words": WORDS, "order": [0, 0, 1]},
           "order out": {"words": WORDS, "order": [0, 9]},
           "too many": {"words": WORDS * 2},
           "one word": {"words": WORDS[:1]}}
    for name, state in bad.items():
        if not simple_piece_problem("SENTENCE", state):
            problems.append(f"bad state accepted: {name}")
    SceneVisualBrief.model_validate(brief())
    return report("1. good states accepted, bad roles, orders and lengths refused", problems)


def case_fits():
    problems = []
    width = renderer.simple_size("SENTENCE", STATE)[0]
    long = {"words": [{"text": "Wahrscheinlichkeit", "role": "object"}] * 14}
    data = renderer.simple_data("SENTENCE", long)
    total = sum(w["width"] for w in data["words"]) + data["gap"] * 13
    if data["font"] >= 46 or total > width - 60 and data["font"] > 26:
        problems.append(f"14 long words: font {data['font']} px, line {total} px for {width}")
    short = renderer.simple_data("SENTENCE", STATE)
    if short["font"] != 46 or short["order"] != STATE["order"] or short["words"][1]["label"] != "verbe":
        problems.append(f"a short sentence: {short['font']} px, order {short['order']}, label {short['words'][1]['label']}")
    return report("2. the tiles fit the line, the font shrinks for a long sentence", problems)


SCRIPT = """() => {
  const at = t => { window.seek(t); return E.s.data.simpleParts.words.map(g => {
    const m = /translate\\(([-\\d.]+) ([-\\d.]+)\\)/.exec(g.getAttribute("transform") || "") || [0, 0, 0];
    return {x: +m[1], op: +g.getAttribute("opacity")}; }); };
  const before = at(1.5), middle = at(2.15), after = at(2.8);   // the move starts at 1.67 s (2 s scaled to the scene)
  window.seek(4.8);
  return {before, middle, after, conflicts: window.layoutConflicts,
          translation: +E.s.data.simpleParts.translation.getAttribute("opacity"),
          focus: E.s.data.simpleParts.words[6].querySelector("rect").getAttribute("stroke-width")};
}"""


def case_drawn():
    problems = []
    found = open_pages({"s": renderer.page_data(brief(), 5, None)}, SCRIPT)["s"]
    before, after = found["before"], found["after"]
    if found["conflicts"]:
        problems.append(f"layout conflicts: {found['conflicts']}")
    if before[3]["op"] > 0.01 or before[4]["op"] > 0.01:
        problems.append(f"the comma and weil shown before the order changes: {before[3]}, {before[4]}")
    if not before[6]["x"] < before[8]["x"]:
        problems.append(f"gehe not before Berlin at first: {before[6]}, {before[8]}")
    if after[3]["op"] < 0.99 or after[4]["op"] < 0.99:
        problems.append(f"the comma and weil not in after the change: {after[3]}, {after[4]}")
    if not after[6]["x"] > max(w["x"] for i, w in enumerate(after) if i != 6):
        problems.append(f"gehe not the last word after the change: {[w['x'] for w in after]}")
    if not before[6]["x"] < found["middle"][6]["x"] < after[6]["x"]:
        problems.append(f"gehe does not slide: {before[6]['x']} -> {found['middle'][6]['x']} -> {after[6]['x']}")
    if found["translation"] < 0.99 or found["focus"] != "6":
        problems.append(f"translation {found['translation']}, focus stroke {found['focus']}")
    return report("3. drawn, no conflict; the verb slides to the end, weil comes in", problems)


def case_preview():
    from playwright.sync_api import sync_playwright
    import tempfile
    folder = os.path.join(ROOT, "instance", "previews", "sentence")
    os.makedirs(folder, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            path = os.path.join(tmp, "s.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(brief(), 5, None)))
            renderer.open_scene(page, path)
            for t in (1.5, 2.15, 4.8):
                page.evaluate(f"window.seek({t})")
                page.screenshot(path=os.path.join(folder, f"t{t}.png"))
        finally:
            browser.close()
    return report("4. previews written", [], [folder])


def case_second_run():
    problems = []
    from app.agent.agent004_visualbriefgenerator import needs_circuit, sentences_moved
    swap = {"words": [{"text": "weil", "role": "conjunction"}, {"text": "ich", "role": "subject"},
                      {"text": "müde", "role": "other"}, {"text": "bin", "role": "verb"}],
            "order": [0, 1, 3, 2], "label": "Ce qu'on croit", "verdict": "wrong"}
    if simple_piece_problem("SENTENCE", swap) or not simple_piece_problem("SENTENCE", {**swap, "verdict": "faux"}):
        problems.append("label / verdict: good refused or bad accepted")
    b = {"scene_id": "2", "text_overlay": {"title": "x"}, "connections": [],
         "entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0], "initial_state": swap}],
         "actions": [{"at": 1.0, "action": "set_state", "target": "s", "state": {"order": [0, 1, 2, 3]}, "cue": "fin"}]}
    found = open_pages({"w": renderer.page_data(b, 4, None)}, """() => {   // the middle of the move: its state's time + 0.5 s
      window.seek(E.s.states.find(st => st.state && st.state.order).at + 0.5);
      const g = E.s.data.simpleParts.words; const y = i => +/translate\\([-\\d.]+ ([-\\d.]+)\\)/.exec(g[i].getAttribute("transform"))[1];
      return {bin: y(3), mude: y(2), caption: E.s.data.simpleParts.caption ? E.s.data.simpleParts.caption.textContent : null}; }""")["w"]
    if not found["bin"] < found["mude"] - 40:
        problems.append(f"the verb does not jump over its neighbour: {found}")
    if found["caption"] != "✗ Ce qu'on croit":
        problems.append(f"caption: {found['caption']!r}")
    brief_ok = SceneVisualBrief.model_validate(b)
    if "2" not in needs_circuit({"2": brief_ok}):
        problems.append("a scene with a SENTENCE may go in comparison panels")
    still = SceneVisualBrief.model_validate({**b, "actions": [{"at": 1.0, "action": "set_state", "target": "s",
                                                                "state": {"focus": 3}, "cue": "fin"}]})
    said = {"2": "Le verbe conjugué part à la fin de la subordonnée."}
    if not sentences_moved(["2"], {"2": still}, said, "language"):
        problems.append("a scene saying the verb moves, with a still SENTENCE, not sent back")
    if sentences_moved(["2"], {"2": brief_ok}, said, "language") or sentences_moved(["2"], {"2": still}, said, "math"):
        problems.append("a moving sentence, or another channel, sent back")
    return report("5. label and verdict, the jump past a neighbour, full width, a still sentence sent back", problems)


def case_third_run():
    problems = []
    words = [{"text": "Ich", "role": "subject"}, {"text": "bleibe", "role": "verb"}, {"text": "zu", "role": "other"},
             {"text": "Hause", "role": "object"}, {"text": ",", "role": "punct"}, {"text": "weil", "role": "conjunction"},
             {"text": "ich", "role": "subject"}, {"text": "krank", "role": "other"}, {"text": "bin", "role": "verb"}]
    b = {"scene_id": "3", "text_overlay": {"title": "x"}, "connections": [],
         "entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0],
                       "initial_state": {"words": words, "label": "La subordonnée passe devant"}}],
         "actions": [{"at": 1.0, "action": "set_state", "target": "s", "state": {"order": [5, 6, 7, 8, 4, 1, 0, 2, 3]}, "cue": "début"}]}
    found = open_pages({"c": renderer.page_data(b, 4, None)}, """() => {
      const at = E.s.states.find(st => st.state && st.state.order).at, g = E.s.data.simpleParts.words;
      const read = () => g.map(w => w.querySelector("text").textContent);
      const box = w => w.querySelector("rect") ? w.querySelector("rect").getBoundingClientRect() : null;
      window.seek(at + 0.5);
      const boxes = g.map(box), overlaps = [];
      boxes.forEach((a, i) => boxes.forEach((c, j) => { if (a && c && i < j && Math.min(a.right, c.right) > Math.max(a.left, c.left) + 4
        && Math.min(a.bottom, c.bottom) > Math.max(a.top, c.top) + 4) overlaps.push([i, j]); }));
      window.seek(at + 2);
      return {before: (window.seek(0.9), read()), after: (window.seek(at + 2), read()), overlaps,
              labels: E.s.box.querySelectorAll(".label").length}; }""")["c"]
    if found["after"][5] != "Weil" or found["after"][0] != "ich" or found["before"][0] != "Ich":
        problems.append(f"capitals: before {found['before']}, after {found['after']}")
    if found["labels"]:
        problems.append(f"the label drawn again under the sentence ({found['labels']})")
    if found["overlaps"]:
        problems.append(f"words through each other mid-move: {found['overlaps']}")
    return report("6. capitals follow the place, the label once, two clauses passing in two lanes", problems)


def sub_words(order_text):
    roles = {"weil": "conjunction", "dass": "conjunction", "ich": "subject", "bin": "verb", "krank": "other"}
    return [{"text": w, "role": roles[w]} for w in order_text.split()]


def case_fourth_run():
    problems = []
    from app.language_examples import order_problem
    from app.agent.agent004_visualbriefgenerator import sentence_problems, sentence_verdicts
    from app.agent.agent003_scriptwriter import repeated_examples
    main = [{"text": "ich", "role": "subject"}, {"text": "heute", "role": "other"}, {"text": "bleibe", "role": "verb"},
            {"text": "zu", "role": "other"}, {"text": "Hause", "role": "other"}]
    if not order_problem(main, [0, 2, 1, 3, 4]) is None or order_problem(main, [0, 1, 2, 3, 4]) is None:
        problems.append("main clause: verb in second place not judged")
    if order_problem(WORDS, [0, 1, 2, 3, 4, 5, 6, 7, 8]) is None or order_problem(WORDS, [0, 1, 2, 3, 4, 5, 7, 8, 6]) is not None:
        problems.append("subordinate clause: verb at the end not judged")
    if order_problem(WORDS, [4, 5, 7, 8, 6, 3, 1, 0, 2]) is not None or order_problem(WORDS, [4, 5, 7, 8, 6, 3, 0, 1, 2]) is None:
        problems.append("clause in front: verb right after it not judged")
    words = sub_words("weil ich bin krank")
    b = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [],
         "entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0],
                       "initial_state": {"words": words, "label": "Erreur fréquente"}}],
         "actions": [{"at": 2.0, "action": "set_state", "target": "s", "state": {"order": [0, 1, 3, 2]}, "cue": "fin"}]}
    fixed, fixes = json.loads(json.dumps(b)), []
    sentence_verdicts(fixed, "scene 1", fixes)
    marks = [a["state"] for a in fixed["actions"] if "verdict" in a["state"]]
    if [a.get("cue") for a in fixed["actions"] if "verdict" in a["state"]] != ["fin"]:
        problems.append("the ✓ without the move's cue: agent010 would time it apart from the move")
    if fixed["entities"][0]["initial_state"].get("verdict") != "wrong" or marks != [{"verdict": "right", "label": "Correct"}]:
        problems.append(f"not marked ✗ then ✓: {fixed['entities'][0]['initial_state']}, {marks}")
    caption = open_pages({"v": renderer.page_data(fixed, 4, None)}, """() => {
      const c = () => E.s.data.simpleParts.caption.textContent;
      const at = E.s.states.find(st => st.state && st.state.order).at;
      window.seek(1); const before = c(); window.seek(at + 0.2); const moving = c(); window.seek(3.5); return [before, moving, c()]; }""")["v"]
    if caption != ["✗ Erreur fréquente", "✗ Erreur fréquente", "✓ Correct"]:     # ✓ once the words are there
        problems.append(f"the caption does not follow the verdict: {caption}")
    said = {"1": "L'erreur fréquente : « weil ich bin krank ». Même règle avec dass."}
    found = sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(b)}, said, "language")
    if not any("no \"verdict\"" in p for p in found):
        problems.append("a wrong order unmarked not sent back")
    labelled = {**b, "entities": [{**b["entities"][0], "initial_state": {**b["entities"][0]["initial_state"],
                                                                         "verdict": "wrong", "label": "Même règle avec dass"}}]}
    found = sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(labelled)}, said, "language")
    if not any("names dass" in p for p in found) or any("no \"verdict\"" in p for p in found):
        problems.append(f"label over a sentence without dass: {found}")
    whole = {"1": "Prenons « Ich bleibe heute zu Hause, weil ich krank bin »."}
    if not any("no SENTENCE has all its words" in p for p in sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(b)}, whole, "language")):
        problems.append("a sentence said in full, shown in part, not sent back")
    twice = sentence_problems(["1", "2"], {"1": SceneVisualBrief.model_validate(b), "2": SceneVisualBrief.model_validate({**b, "scene_id": "2"})},
                              {"1": "", "2": ""}, "language")
    if not any("the same move" in p for p in twice):
        problems.append("the same move in two scenes not sent back")
    three = {**b, "entities": [{**b["entities"][0], "id": f"s{i}", "position": [0, 2 - 2 * i, 0]} for i in range(3)], "actions": []}
    if not any("at most 2" in p for p in sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(three)}, {"1": ""}, "language")):
        problems.append("three sentences in a scene not sent back")
    from app.agent.agent004_visualbriefgenerator import coherence_problems
    if any("numbers" in p or "Gauss" in p for p in coherence_problems(SceneVisualBrief.model_validate(b),
                                                                        "Version B1, version B2 : éliminez la ligne fausse.")):
        problems.append("maths checks run on a sentence scene")
    if sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(b)}, said, "math"):
        problems.append("another channel checked")
    scenes = [{"scene_id": i, "narration_text": "On dit « weil ich krank bin »."} for i in ("1", "2")] + [{"scene_id": "3", "narration_text": "« weil ich krank bin »"}]
    if not repeated_examples(scenes) or repeated_examples(scenes[1:]):
        problems.append("the same example in two scenes of the script: not sent back, or the recap refused")
    alone = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
             "entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0], "initial_state": {"words": sub_words("weil ich krank bin")}}]}
    first = open_pages({"a": renderer.page_data(alone, 2, None)}, """() => { window.seek(1);
      return E.s.data.simpleParts.words[0].querySelector("text").textContent; }""")["a"]
    if first != "weil":
        problems.append(f"a clause alone written {first!r}")
    return report("7. wrong orders judged and marked, the said sentence shown whole, one example per scene", problems)


def case_voice():
    problems = []
    from app.tts_manager import foreign_parts
    text = ("Reprenons : « Ich bleibe heute zu Hause », qui signifie « je reste aujourd'hui à la maison ». "
            "Le verbe conjugué, « bleibe », occupe la deuxième position. Retenez : weil, dass ou wenn ouvrent la voie.")
    parts = foreign_parts(text, "de", ["bleibe", "Hause"])
    german = [p for p, lang in parts if lang == "de"]
    if german != ["Ich bleibe heute zu Hause", "bleibe", "weil, dass", "wenn"]:
        problems.append(f"German parts: {german}")
    if not any("je reste aujourd'hui à la maison" in p for p, lang in parts if lang is None):
        problems.append("the French meaning said in German")
    if [p for p, lang in foreign_parts("« je vais à Berlin »", "de", ["Berlin"]) if lang]:
        problems.append("a word of the example said in German inside its French meaning")
    from app.agent.agent004_visualbriefgenerator import sentence_arrows
    scene = {"entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0], "initial_state": {"words": sub_words("weil ich krank bin")}},
                          {"id": "a", "type": "ARROW_ANNOTATION", "position": [0, 1, 0], "initial_state": {"text": "Verbe final", "target": "s"}},
                          {"id": "b", "type": "ARROW_ANNOTATION", "position": [3, 3, 0], "initial_state": {"text": "Entrée", "status": True}},
                          {"id": "park", "type": "OBJECT", "position": [-3, 0, 0], "initial_state": {"icon": "tree", "label": "Parc"}}],
             "connections": [], "actions": [{"at": 1, "action": "spawn", "target": "a"}]}
    long = [{"text": t, "role": "other"} for t in "Obwohl ich das Stipendium bekomme , treffe ich die Entscheidung , Arzt zu werden".split()]
    for w in long:
        w["role"] = "punct" if w["text"] == "," else "other"
    fit = renderer.sentence_data({"words": long}, 1600)
    if sum(w["width"] for w in fit["words"]) + fit["gap"] * (len(long) - 1) > 1600:   # run 7: 1731 px for 1600
        problems.append(f"the B2 sentence of run 7 wider than its piece (font {fit['font']})")
    from app.agent.agent004_visualbriefgenerator import sentence_centered
    off = {"entities": [{"id": "s", "type": "SENTENCE", "position": [1.03, -2.19, 0.0], "initial_state": {}}]}
    sentence_centered(off, "scene 4", [])
    if off["entities"][0]["position"] != [0.0, -2.19, 0.0]:      # run 7: the B2 sentence ran out at x 1.03
        problems.append(f"a sentence placed sideways not centred: {off['entities'][0]['position']}")
    sentence_arrows(scene, "scene 1", [])
    if [e["id"] for e in scene["entities"]] != ["s", "b"] or scene["actions"]:
        problems.append(f"arrow on a sentence: {[e['id'] for e in scene['entities']]}, {scene['actions']}")
    asked = [p for p, lang in foreign_parts("on demande « Wohin? », « où vers ? » : avec « Wo? », la préposition « in » décide", "de") if lang]
    if asked != ["Wohin?", "Wo?", "in"]:     # run 5: the questions said by the French voice
        problems.append(f"questions and prepositions alone: {asked}")
    if foreign_parts("Le verbe est en deuxième position et il y a des mots.", "de") != [("Le verbe est en deuxième position et il y a des mots.", None)]:
        problems.append("a French sentence cut")
    return report("8. the German examples said apart, the French left French", problems, german)


def case_acts():
    problems = []
    from app.agent.agent003_scriptwriter import acts_problems, channel_pace
    from app.agent.agent002_curriculumsimplifier import LANGUAGE_ACTS
    scenes = [{"scene_id": str(i), "narration_text": "x"} for i in range(1, 7)]
    if not acts_problems(scenes, LANGUAGE_ACTS) or acts_problems(scenes[:5], LANGUAGE_ACTS) or acts_problems(scenes, None):
        problems.append("five acts: six scenes accepted, five refused, or another format checked")
    settings = {"voice_by_channel": {"c": {"speed": 0.9, "words": [270, 330], "words_per_sec": 2.75}}}
    if channel_pace(settings, "c") != (2.75, 270, 330):
        problems.append(f"the channel's length: {channel_pace(settings, 'c')}")
    words = [{"text": "Ich", "role": "subject"}, {"text": "gehe", "role": "verb"}, {"text": "in", "role": "other"},
             {"text": "dem", "role": "other"}, {"text": "den", "role": "other"}, {"text": "Park", "role": "object"}]
    b = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [],
         "entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0],
                       "initial_state": {"words": words, "order": [0, 1, 2, 3, 5], "label": "Erreur fréquente", "verdict": "wrong"}}],
         "actions": [{"at": 1.0, "action": "set_state", "target": "s", "state": {"order": [0, 1, 2, 4, 5], "verdict": "right", "label": "Correct"}, "cue": "den"}]}
    # the words come in one by one first (0.25 s apart): the change is looked at once they are all in
    if simple_piece_problem("SENTENCE", b["entities"][0]["initial_state"]):
        problems.append("a sentence with a word left out refused")
    b["actions"][0]["at"] = 3.0
    seen = open_pages({"p": renderer.page_data(b, 6, None)}, """() => {
      const g = E.s.data.simpleParts.words, op = i => +(g[i].getAttribute("opacity") ?? 1);
      window.seek(E.s.states[0].at - 0.1); const before = [op(3), op(4)]; window.seek(E.s.states[0].at + 2); return {before, after: [op(3), op(4)],
        caption: E.s.data.simpleParts.caption.textContent}; }""")["p"]
    if not (seen["before"][0] > 0.9 and seen["before"][1] < 0.1 and seen["after"][0] < 0.1 and seen["after"][1] > 0.9):
        problems.append(f"dem -> den not drawn: {seen}")
    if seen["caption"] != "✓ Correct":
        problems.append(f"caption after the change: {seen['caption']!r}")
    return report("9. five acts, the channel's length, a word that changes", problems)


def case_translation():
    problems = []
    from app.agent.agent004_visualbriefgenerator import sentence_problems
    b = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
         "entities": [{"id": "s", "type": "SENTENCE", "position": [0, 0, 0],
                       "initial_state": {"words": sub_words("weil ich bin krank"), "verdict": "wrong",
                                         "translation": "parce que je suis malade"}}]}
    seen = open_pages({"p": renderer.page_data(b, 4, None)}, """() => { const tr = E.s.data.simpleParts.translation;
      window.seek(0.2); const early = +tr.getAttribute("opacity"); window.seek(3.5);
      return [early, +tr.getAttribute("opacity"), tr.textContent]; }""")["p"]
    if seen != [0, 1, "Sens voulu : parce que je suis malade"]:
        problems.append(f"shown by itself: {seen}")
    late = json.loads(json.dumps(b))
    late["actions"] = [{"at": 3.8, "action": "set_state", "target": "s", "state": {"translation": True}}]
    if open_pages({"p": renderer.page_data(late, 4, None)}, """() => { window.seek(3.0);
        return +E.s.data.simpleParts.translation.getAttribute("opacity"); }""")["p"] < 0.99:
        problems.append("a late action held the meaning back")      # run 8: set at the scenes' ends
    bare = json.loads(json.dumps(b)); del bare["entities"][0]["initial_state"]["translation"]
    if not any("no \"translation\"" in p for p in sentence_problems(["1"], {"1": SceneVisualBrief.model_validate(bare)}, {"1": ""}, "language")):
        problems.append("a sentence without its meaning not sent back")
    return report("10. the French meaning under every sentence", problems)


def case_watermark():
    problems, warnings = [], []
    mark = renderer.watermark("assets/brand/breeze_b.png", warnings)
    if not (mark or "").startswith("data:image/png;base64,") or renderer.watermark(None, []) is not None:
        problems.append("the mark not read, or one made up")
    if renderer.watermark("assets/brand/none.png", warnings) is not None or not warnings:
        problems.append("a missing mark not said")
    b = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [], "entities": []}
    data = renderer.page_data(b, 2, None)
    data["watermark"] = mark
    box = open_pages({"p": data}, """() => { window.seek(1); const m = document.getElementById("watermark").getBoundingClientRect();
      return [m.left, m.right, m.bottom]; }""")["p"]
    if not (box[0] > 1740 and box[1] <= 1920 and box[2] <= 1080):
        problems.append(f"the mark not in the free corner: {box}")
    return report("11. the channel's mark, bottom right", problems)


if __name__ == "__main__":
    results = [case_states(), case_fits(), case_drawn(), case_preview(), case_second_run(), case_third_run(),
               case_fourth_run(), case_voice(), case_acts(), case_translation(), case_watermark()]
    sys.exit(0 if all(results) else 1)
