"""
Check the fixes from the evaluation of the 4-channel run of 2026-11-02 (16:05), offline but for the
browser:
  1. agent003: scenes with fewer than MIN_WORDS words (a video under 90 s at the narrator's pace) are
     asked again once, told the count; the longer answer is kept, and only then is it healthy
  2. agent004: a probability "P(chien | animal)" is no power nor pressure P (the badge pointing at it
     need not say "puissance"); "P = U I" still is; the plan's words reach each scene ("announced")
  3. agent010 page: axes named with no measure ("orbite", "hauteur") are a sketch, no numbers along
     them; "temps (s)" keeps its numbers
  4. POPULATION: a grid of dots to scale, its groups coloured at set_state {"show"} (or from the
     start), the others dimmed by {"focus"}; the legend gives the people (count x per); a bad
     initial_state is refused; agent004 sends back GAUGEs counting people
  5. agent010 page, comparison: things in a panel stay under its title (the math video's "Maladie
     rare": two dials stacked in each panel went over it), and a badge with a diagonal direction
     finds a free side (it lay over the formula)
  6. agent004 sends back an icon in total contradiction with its label (people for "Animaux", coins
     for "Consommateurs", "Pile" as a zap: a battery is a BATTERY); fitting ones pass ("Chiens" a dog,
     "Incendies rares" a flame, "Sondages" people, a dial giving a share of patients); a battery shown
     alone is no open circuit (that sent the LLM to the zap); the prompt
     asks for a POPULATION for a conditional probability read both ways
Prints PASS or FAIL per case. Cases 3 to 5 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_population_fixes.py
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import provenance                                              # noqa: E402
from app.agent import agent003_scriptwriter as agent003                 # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.qa_feedback import QA_FEEDBACK_ENV                             # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, measured_axis  # noqa: E402
from test_reactive import open_pages                                    # noqa: E402

SUBTITLES = [{"at": 0, "end": 30, "text": "plus la maladie est rare, plus les fausses alertes pèsent."}]


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def run_agent003(answers):
    """agent003.run on a stub outline, the LLM answering `answers` in turn: (prompts, status, script)."""
    prompts, found = [], {}
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "test_channel")
        os.makedirs(folder)
        with open(os.path.join(folder, "outline.json"), "w", encoding="utf-8") as f:
            json.dump({"beats": ["Une pile n'est pas un réservoir."]}, f)
        replies = iter(answers)
        patched = {"channel_dir": lambda channel_id: folder, "llm_call": lambda prompt: prompts.append(prompt) or next(replies),
                   "finish": lambda channel_id, agent, stage, status, output_path, data=None, error=None: found.update(status=status)}
        originals = {name: getattr(agent003, name) for name in patched}
        instance_dir, saved = provenance.INSTANCE_DIR, os.environ.pop(QA_FEEDBACK_ENV, None)
        try:
            for name, stub in patched.items():
                setattr(agent003, name, stub)
            provenance.INSTANCE_DIR = root
            stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
            try:
                agent003.run("test_channel", {}, [])
            finally:
                sys.stderr.close()
                sys.stderr = stderr
            with open(os.path.join(folder, "script.json"), encoding="utf-8") as f:
                found["script"] = json.load(f)
        finally:
            for name, original in originals.items():
                setattr(agent003, name, original)
            provenance.INSTANCE_DIR = instance_dir
            if saved is not None:
                os.environ[QA_FEEDBACK_ENV] = saved
    return prompts, found.get("status"), found.get("script")


def script_of(words_per_scene, scenes=4):
    return json.dumps({"scenes": [{"scene_id": i + 1, "narration_text": "mot " * words_per_scene, "duration_sec": 30}
                                  for i in range(scenes)]})


def case_short_script():
    problems = []
    prompts, status, script = run_agent003([script_of(50), script_of(80)])       # 200 words, then 320
    if f"{agent003.WORDS_PER_SEC} words per second" not in prompts[0] or f"{agent003.MIN_WORDS} to {agent003.MAX_WORDS} words" not in prompts[0]:
        problems.append("the prompt does not give the pace and the words wanted")
    if len(prompts) != 2 or "the scenes have 200 words in all" not in prompts[1]:
        problems.append(f"a 200-word script not asked again with its count ({len(prompts)} calls)")
    if script["word_count"] != 320 or status != "healthy":
        problems.append(f"the longer script not kept: {script['word_count']} words, {status}")
    prompts, status, script = run_agent003([script_of(50), script_of(40)])       # shorter again: the first kept
    if script["word_count"] != 200 or status != "not_healthy":
        problems.append(f"still short: {script['word_count']} words, {status}")
    prompts, status, _ = run_agent003([script_of(80)])
    if len(prompts) != 1 or status != "healthy":
        problems.append(f"a long enough script asked again ({len(prompts)} calls, {status})")
    return report(f"1. agent003: under {agent003.MIN_WORDS} words, asked again once; the longer one kept", problems)


def case_probability():
    problems = []
    for latex, symbol in ((r"P(\text{chien}\mid\text{animal})", None), (r"P(A \mid B) = \frac{P(B|A)P(A)}{P(B)}", None),
                          (r"P\left(A\right) = 0{,}01", None), (r"P = U \times I", "P"), (r"P(t) = U I", "P"), (r"U = R I", "U")):
        if agent004.formula_symbol(latex) != symbol:
            problems.append(f"{latex!r}: {agent004.formula_symbol(latex)!r}, expected {symbol!r}")
    brief = lambda latex, text: SceneVisualBrief.model_validate({
        "scene_id": "2", "text_overlay": {"title": "A sachant B"}, "connections": [],
        "entities": [{"id": "f", "type": "TEX_FORMULA", "position": [0, 0, 0], "initial_state": {"latex": latex}},
                     {"id": "a", "type": "ARROW_ANNOTATION", "position": [0, 1.2, 0],
                      "initial_state": {"text": text, "direction": "DOWN", "target": "f"}}],
        "actions": [{"at": 1, "action": "spawn", "target": "f", "cue": "chien"}]})
    said = [e for e in agent004.coherence_problems(brief(r"P(\text{chien}\mid\text{animal})", "Chien sachant animal"), "un chien") if "puissance" in e]
    if said:
        problems.append(f"a probability taken for a power: {said}")
    if not [e for e in agent004.coherence_problems(brief(r"P = U \times I", "Le produit"), "un chien") if "puissance" in e]:
        problems.append("a power formula pointed at without its name not sent back")
    scenes = [{"scene_id": "1"}, {"scene_id": "2"}, {"scene_id": "3"}]
    agent004.announce(scenes, {"parts": [{"scene_id": "2", "text": "Le ressort bandé transfère son énergie"}]})
    if [s.get("announced") for s in scenes] != [None, "Le ressort bandé transfère son énergie", None] or "announced" not in agent004.PROMPT:
        problems.append(f"the plan's words do not reach their scene: {scenes}")
    return report("2. agent004: P(A | B) is a probability, not a power; the plan's words reach their scene", problems)


def axes_page(x_label, y_label):
    brief = {"scene_id": "3", "text_overlay": {"title": "Deux plans inclinés"}, "connections": [], "actions": [],
             "entities": [{"id": "ax", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {
                 "x_range": [-5, 5, 1], "y_range": [-3, 3, 1], "x_label": x_label, "y_label": y_label}}]}
    return renderer.page_data(brief, 8, None)


def case_sketch_axes():
    problems = []
    for name, measured in (("orbite", False), ("plan orbital", False), ("hauteur", False), ("temps (s)", True),
                           ("x", True), ("années", True), ("", True), ("PIB (milliards d'€)", True)):
        if measured_axis(name) != measured:
            problems.append(f"{name!r} measured: {measured_axis(name)}")
    found = open_pages({"sketch": axes_page("orbite", "hauteur"), "measured": axes_page("temps (s)", "hauteur")},
                       "() => [...document.querySelectorAll('.tick-label')].map(t => t.textContent)")
    if found["sketch"]:
        problems.append(f"numbers along sketch axes: {found['sketch']}")
    if len(found["measured"]) != 11 or "4" not in found["measured"]:     # x: -5 to 5 and the 0; y (hauteur): none
        problems.append(f"time axis without its numbers, or height with some: {found['measured']}")
    return report("3. axes named with no measure carry no numbers; a unit keeps them", problems,
                  [f"temps (s) x hauteur: {found['measured']}"])


POPULATION = {"id": "pop", "type": "POPULATION", "position": [0, -0.5, 0], "initial_state": {
    "total": 1000, "per": 10, "unit": "personnes",
    "groups": [{"id": "sick", "label": "Malades testés positifs", "count": 10, "color": "#DC2626"},
               {"id": "false_alarm", "label": "Faux positifs", "count": 10}],
    "rest": "Bien portants, négatifs"}}


def population_brief(layout_x=0):
    pop = json.loads(json.dumps(POPULATION))
    pop["position"][0] = layout_x
    return {"scene_id": "5", "text_overlay": {"title": "Maladie rare", "subtitle": "Sur 10 000 personnes"}, "connections": [],
            "entities": [pop],
            "actions": [{"at": 4, "action": "set_state", "target": "pop", "state": {"show": "false_alarm"}, "cue": "x"},
                        {"at": 6, "action": "set_state", "target": "pop", "state": {"focus": ["sick", "false_alarm"]}, "cue": "x"},
                        {"at": 8, "action": "set_state", "target": "pop", "state": {"focus": []}, "cue": "x"}]}


def case_population():
    problems = []
    SceneVisualBrief.model_validate(population_brief())
    for bad in ({"total": 5}, {"total": 2000}, {"per": 0}, {"groups": []}, {"rest": "x" * 40},
                {"groups": [{"id": "a", "label": "A", "count": 0}]}, {"groups": [{"id": "a", "label": "A", "count": 2, "color": "red"}]},
                {"groups": [{"id": "a", "label": "A", "count": 2}, {"id": "a", "label": "B", "count": 2}]},
                {"total": 10, "groups": [{"id": "a", "label": "A", "count": 11}]}):
        brief = population_brief()
        brief["entities"][0]["initial_state"].update(bad)
        try:
            SceneVisualBrief.model_validate(brief)
            problems.append(f"accepted: {bad}")
        except ValueError:
            pass
    z = renderer.population_data(POPULATION["initial_state"])
    if [g["people"] for g in z["groups"]] != ["100 personnes"] * 2 or z["rest"]["people"] != "9 800 personnes" \
            or z["head"] != "10 000 personnes · 1 point = 10 personnes" or z["groups"][1]["color"] != renderer.POPULATION_COLORS[1]:
        problems.append(f"the counts: {z}")
    data = renderer.page_data(population_brief(), 10, None)
    data["events"] = population_brief()["actions"]
    found = open_pages({"pop": data}, """() => {
      const dots = [...document.querySelectorAll('.pop-grid circle')], keys = [...document.querySelectorAll('.pop-key')];
      const read = t => { window.seek(t); return {fill: [0, 10, 25].map(i => dots[i].style.fill),
        opacity: [0, 10, 25].map(i => +dots[i].style.opacity), keys: keys.map(k => +k.style.opacity)}; };
      return {count: dots.length, before: read(3), shown: read(5.5), focus: read(7.5), back: read(9.5), conflicts: window.layoutConflicts};
    }""")["pop"]
    grey = found["before"]["fill"][2]
    if found["count"] != 1000:
        problems.append(f"{found['count']} dots, expected 1000")
    if found["before"]["fill"][0] == grey or found["before"]["fill"][1] != grey or found["before"]["keys"] != [1, 0, 1]:
        problems.append(f"before its show, a group is coloured, or one never shown is not: {found['before']}")
    if found["shown"]["fill"][1] == grey or found["shown"]["keys"] != [1, 1, 1]:
        problems.append(f"the shown group not coloured: {found['shown']}")
    if found["focus"]["opacity"][:2] != [1, 1] or found["focus"]["opacity"][2] > 0.2:
        problems.append(f"focus does not dim the others: {found['focus']}")
    if found["back"]["opacity"] != [1, 1, 1]:
        problems.append(f"focus [] does not bring them back: {found['back']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    gauges = SceneVisualBrief.model_validate({
        "scene_id": "3", "text_overlay": {"title": "Compter"}, "connections": [],
        "entities": [{"id": f"g{i}", "type": "GAUGE", "position": [i * 3 - 3, 0, 0], "initial_state": {"label": f"Groupe {i}"}}
                     for i in range(3)],
        "actions": [{"at": 1 + i, "action": "set_value", "target": f"g{i}", "value": 100, "unit": unit, "cue": "x"}
                    for i, unit in enumerate(("pers.", "personnes", "%"))]})
    sent = agent004.people_by_gauges(gauges)
    if len(sent) != 1 or "['g0', 'g1']" not in sent[0]:
        problems.append(f"GAUGEs counting people: {sent}")
    return report("4. POPULATION: dots to scale, groups shown and focused, the people counted; gauges of people sent back",
                  problems, [f"keys before / after the show: {found['before']['keys']} / {found['shown']['keys']}"])


# The math video's scene 5 ("Maladie rare, fausses alertes"), as agent004 wrote it.
RARE = {"scene_id": "5", "text_overlay": {"title": "Maladie rare, fausses alertes",
                                          "subtitle": "Un test positif ne signifie pas 99 % de chances d’être malade"},
        "connections": [],
        "entities": [{"id": "gauge_malades", "type": "GAUGE", "position": [-4.0, -1.0, 0.0], "initial_state": {"label": "Malades sur 10 000"}},
                     {"id": "gauge_true_pos", "type": "GAUGE", "position": [-4.0, -2.69, 0.0], "initial_state": {"label": "Vrais positifs"}},
                     {"id": "gauge_false_pos", "type": "GAUGE", "position": [4.0, -0.94, 0.0], "initial_state": {"label": "Faux positifs"}},
                     {"id": "gauge_prob", "type": "GAUGE", "position": [4.0, -2.76, 0.0], "initial_state": {"label": "Malade sachant positif"}},
                     {"id": "formula_threshold", "type": "TEX_FORMULA", "position": [0.0, -0.74, 0.0],
                      "initial_state": {"latex": "\\frac{10}{110}\\approx 9\\%", "tone": "result"}},
                     {"id": "object_fire", "type": "OBJECT", "position": [0.0, -2.86, 0.0], "initial_state": {"icon": "flame", "label": "Incendies rares"}},
                     {"id": "arrow_alarm", "type": "ARROW_ANNOTATION", "position": [0.0, -2.05, 0.0],
                      "initial_state": {"text": "Alarme très sensible", "direction": [-0.5, -0.5], "target": "object_fire", "tone": "warning"}}],
        "actions": [{"at": 7.35, "action": "set_value", "target": "gauge_malades", "value": 10, "unit": "pers.", "cue": "x"},
                    {"at": 9.08, "action": "set_value", "target": "gauge_true_pos", "value": 10, "unit": "pers.", "cue": "x"},
                    {"at": 13.58, "action": "set_value", "target": "gauge_false_pos", "value": 100, "unit": "pers.", "cue": "x"},
                    {"at": 14.69, "action": "spawn", "target": "formula_threshold", "cue": "x"},
                    {"at": 16.19, "action": "set_value", "target": "gauge_prob", "value": 9, "unit": "%", "cue": "x"},
                    {"at": 16.5, "action": "spawn", "target": "arrow_alarm", "cue": "x"},
                    {"at": 16.5, "action": "spawn", "target": "object_fire", "cue": "x"}]}


def case_panels():
    problems = []
    data = renderer.page_data(RARE, 17, None, None, "comparison", ["Maladie rare", "Faux positifs"])
    data["subtitles"] = SUBTITLES
    found = open_pages({"rare": data}, """() => {
      window.seek(16.9);
      const r = n => n.getBoundingClientRect();
      const heads = [...document.querySelectorAll('.panel-title')].map(h => r(h).bottom);
      const tops = Object.fromEntries(['gauge_malades', 'gauge_false_pos'].map(id => [id, r(E[id].box).top]));
      return {conflicts: window.layoutConflicts, heads, tops};
    }""")["rare"]
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    if any(top < max(found["heads"]) for top in found["tops"].values()):
        problems.append(f"a dial over its panel's title: {found}")
    return report("5. comparison: two dials stacked stay under the panel's title; a diagonal badge finds a free side",
                  problems, [f"panel titles end at {found['heads']}, dials start at {found['tops']}"])


def case_icons():
    problems = []
    obj = lambda i, icon, label: {"id": i, "type": "OBJECT", "position": [0, 0, 0], "initial_state": {"icon": icon, "label": label}}
    brief = lambda *entities: SceneVisualBrief.model_validate({"scene_id": "2", "text_overlay": {"title": "A sachant B"},
                                                               "connections": [], "actions": [], "entities": list(entities)})
    for wrong in (obj("a", "users", "Animaux"), obj("a", "dog", "Patients"), obj("a", "car", "Maison"),
                  obj("a", "flame", "Pluie"), obj("a", "zap", "Pile"),
                  {"id": "a", "type": "COINS", "position": [0, 0, 0], "initial_state": {"label": "Consommateurs"}}):
        if len(agent004.icons_against_labels(brief(wrong))) != 1:
            problems.append(f"not sent back: {wrong['initial_state']} ({wrong['type']})")
    for fine in (obj("a", "dog", "Chiens"), obj("a", "paw-print", "Animaux"), obj("a", "flame", "Incendies rares"),
                 obj("a", "users", "Sondages"), obj("a", "user", "Consommateur final"), obj("a", "factory", "Scierie"),
                 obj("a", "earth", "Terre"), obj("a", "box", "Animaux"),
                 {"id": "a", "type": "GAUGE", "position": [0, 0, 0], "initial_state": {"label": "Malade sachant positif"}},
                 {"id": "a", "type": "WATER_TANK", "position": [0, 0, 0], "initial_state": {"label": "Eau déjà là"}},
                 {"id": "a", "type": "BANK", "position": [0, 0, 0], "initial_state": {"label": "Compte acheteur"}}):
        if agent004.icons_against_labels(brief(fine)):
            problems.append(f"sent back: {fine['initial_state']} ({fine['type']}): {agent004.icons_against_labels(brief(fine))}")
    alone = brief({"id": "b", "type": "BATTERY", "position": [0, 0, 0], "initial_state": {"label": "Pile"}})
    unwired = brief({"id": "b", "type": "BATTERY", "position": [0, 0, 0], "initial_state": {"label": "Pile"}},
                    {"id": "l", "type": "LAMP", "position": [3, 0, 0], "initial_state": {"label": "Lampe"}})
    if agent004.open_circuits(alone) or not agent004.open_circuits(unwired):
        problems.append("a battery shown alone taken for an open circuit (the LLM then drew a zap), or a battery "
                        "and a lamp left unwired not")
    if "chien sachant" not in agent004.PROMPT or "paw-print" not in agent004.PROMPT:
        problems.append("the prompt does not ask for a POPULATION of a conditional probability, or lacks the paw")
    return report("6. agent004: an icon contradicting its label is sent back; fitting ones are kept", problems)


if __name__ == "__main__":
    results = [case_short_script(), case_probability(), case_sketch_axes(), case_population(), case_panels(), case_icons()]
    sys.exit(0 if all(results) else 1)
