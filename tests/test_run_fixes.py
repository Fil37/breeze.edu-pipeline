"""
Check the fixes from the evaluation of the 4-channel run of 2026-11-02 (13:38), offline but for the
browser:
  1. SEESAW: a side never dropped by set_state is there from the start (only {"right": true} given:
     the left load still weighs); balanced, the pivot slides under the beam, which stays in its box
  2. agent010 page: what is wider than its room is made smaller: a seesaw in a comparison panel, a
     long formula in the main area; nothing leaves the frame
  3. the hook's film: a made-up picture (AI-generated, 3D, exoplanet...) is ruled out; with a chooser
     (agent004: the LLM reads the tags against the narration) its pick is taken, "none" or a bad
     answer gives no film, and a clip cached without a chooser is searched again
  4. agent004: a scene where nothing happens but things appearing and highlighted is sent back
  5. agent003: an acronym spoken (hook, plan, then scenes) before it is said in full is found
  6. SPEED_RACE: speeds on one track to one scale (the electron does not move while the signal
     arrives), real times and the ratio in French words; bad runners refused; agent004 sends back a
     slow-versus-fast narration drawn as two badged icons
Prints PASS or FAIL per case. Cases 1 and 2 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_run_fixes.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent003_scriptwriter as agent003                # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004        # noqa: E402
from app.agent import agent010_html_renderer as renderer               # noqa: E402
from app.render import footage                                         # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                # noqa: E402
from test_footage import CDN, Sandbox, hit                             # noqa: E402
from test_reactive import open_pages                                   # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


# The math video's extreme value: the four notes on the left, 100 dropped on the right, then balanced.
SEESAW = {"scene_id": "4", "text_overlay": {"title": "Une valeur extrême"}, "connections": [],
          "entities": [{"id": "s", "type": "SEESAW", "position": [3, -0.34, 0], "initial_state": {
              "left": {"label": "Quatre notes", "weight": 4, "value": 9.5}, "right": {"label": "100", "weight": 1, "value": 100},
              "unit": "pts"}},
                       {"id": "f", "type": "TEX_FORMULA", "position": [-3, 0, 0], "initial_state": {"latex": "\\tilde{x} = 10"}}],
          "actions": [{"at": 2, "action": "set_state", "target": "s", "state": {"right": True}, "cue": "x"},
                      {"at": 6, "action": "set_state", "target": "s", "state": {"balanced": True}, "cue": "x"}]}
WIDE = {"scene_id": "6", "text_overlay": {"title": "Choisir"}, "connections": [], "actions": [],
        "entities": [{"id": "m", "type": "TEX_FORMULA", "position": [-2, 0, 0], "initial_state": {"latex":
            "\\text{Médiane}=x_{(n+1)/2}\\ (n\\text{ impair});\\ \\frac{x_{n/2}+x_{n/2+1}}{2}\\ (n\\text{ pair})"
            "\\ \\text{ et encore une longue suite de mots}"}}]}


def seesaw_page():
    data = renderer.page_data(SEESAW, 12, None, None, "comparison", ["Médiane", "Moyenne"])
    data["events"] = SEESAW["actions"]
    return data


def case_seesaw():
    problems = []
    found = open_pages({"seesaw": seesaw_page()}, """() => {
      const angle = () => { const m = /rotate\\(([-\\d.e]+)deg\\)/.exec(document.querySelector('.seesaw .beam').style.transform); return m ? +m[1] : 0; };
      const read = t => { window.seek(t); const loads = [...document.querySelectorAll('.seesaw .load')];
        const shape = document.querySelector('.seesaw'), beam = document.querySelector('.seesaw .beam');
        return {angle: angle(), opacity: loads.map(l => +l.style.opacity), mean: document.querySelector('.seesaw .mean').textContent,
                beamRight: beam.offsetLeft + beam.offsetWidth, width: shape.offsetWidth}; };
      return {left: read(1.9), balanced: read(11.5)};
    }""")["seesaw"]
    if found["left"]["opacity"] != [1, 0] or found["left"]["angle"] > -8:
        problems.append(f"the left load, never set, is not there from the start: {found['left']}")
    b = found["balanced"]
    if abs(b["angle"]) > 1 or b["mean"] != "27,60 pts" or b["opacity"] != [1, 1]:
        problems.append(f"balanced: {b}")
    if b["beamRight"] > b["width"] + 1:
        problems.append(f"the beam slid out of its box: {b}")
    return report("1. SEESAW: an unset side weighs from the start; the pivot slides, not the beam", problems, [str(b)])


def case_fit():
    problems = []
    found = open_pages({"seesaw": seesaw_page(), "wide": renderer.page_data(WIDE, 8, None)}, """() => {
      window.seek(7);
      const r = n => n.getBoundingClientRect();
      const panel = r(document.querySelectorAll('[data-panel]')[1] || document.body);
      const seesaw = document.querySelector('.seesaw'), formula = document.querySelector('.formula');
      return {conflicts: window.layoutConflicts, seesaw: seesaw ? [r(seesaw).left, r(seesaw).right] : null,
              panel: [panel.left, panel.right], formula: formula ? [r(formula).left, r(formula).right] : null};
    }""")
    s = found["seesaw"]
    if s["seesaw"][0] < s["panel"][0] or s["seesaw"][1] > s["panel"][1]:
        problems.append(f"the seesaw spills out of its panel: {s}")
    if any("leaves the frame" in c for c in s["conflicts"] + found["wide"]["conflicts"]):
        problems.append(f"leaves the frame: {s['conflicts']} {found['wide']['conflicts']}")
    w = found["wide"]["formula"]
    if w[0] < 0 or w[1] > renderer.WIDTH:
        problems.append(f"the long formula is cut: {w}")
    return report("2. what is wider than its room is made smaller: seesaw in a panel, long formula", problems,
                  [f"seesaw {s['seesaw']} in panel {s['panel']}, formula {w}"])


def case_film_choice():
    problems = []
    if footage.allowed(hit(20, "lune, titan, exoplanètes, ciel rouge")) is None \
            or footage.allowed(hit(21, "lune, ciel, rendu 3d")) is None \
            or footage.allowed({**hit(22, "lune, ciel"), "isAiGenerated": True}) is None:
        problems.append("a made-up picture allowed")
    with Sandbox([hit(31, "lampe, kérosène, incendie"), hit(32, "ampoule, lampe, électrique")]) as box:
        os.environ["PIXABAY_API_KEY"] = "test"
        seen = []
        clip = footage.find_clip("lampe", lambda q, c: seen.append(c) or 1)
        if clip.get("id") != 32 or len(seen[0]) != 2 or set(seen[0][0]) != {"tags", "duration"}:
            problems.append(f"the chooser's pick not taken: {clip}, shown {seen}")
        if footage.find_clip("lampe", lambda q, c: 0)["id"] != 32 or len(box.searches) != 1:
            problems.append("a chosen clip searched again")
        footage.find_clip("ampoule")                              # cached without a chooser...
        if footage.find_clip("ampoule", lambda q, c: 1)["id"] != 32 or box.searches.count("ampoule") != 2:
            problems.append(f"a clip cached without a chooser trusted: {box.searches}")
        for answer in (None, 5, "1", True):
            try:
                footage.find_clip(f"lampe rouge{'s' * len(str(answer))}", lambda q, c, a=answer: a)
                problems.append(f"the answer {answer!r} gave a film")
            except footage.FootageError:
                pass
        # agent004: the LLM's answer, numbered from 1; none fits: the hook drawn without a film
        original = agent004.llm_call
        try:
            agent004.llm_call = lambda prompt: '{"choice": 2}'
            if agent004.clip_chooser("La lampe s'allume")("lampe", [{"tags": "a", "duration": 9}] * 2) != 1:
                problems.append("the LLM's choice not read")
            for text in ('{"choice": null}', '{"choice": 3}', "pas de JSON"):
                agent004.llm_call = lambda prompt, t=text: t
                layouts = {"1": {"layout_template": "circuit", "footage": {"query": "lampe verte"}}}
                done = agent004.checked_footage(["1"], layouts, {"1": "La lampe s'allume"})
                if "footage" in layouts["1"] or "dropped" not in done:
                    problems.append(f"{text!r}: the film kept: {done}")
        finally:
            agent004.llm_call = original
        del os.environ["PIXABAY_API_KEY"]
    return report("3. no made-up film; the chooser picks the clip, or none", problems)


def case_still():
    problems = []
    icons = lambda n: [{"id": f"o{i}", "type": "OBJECT", "position": [i, 0, 0], "initial_state": {"icon": "user", "label": "Étudiante"}}
                       for i in range(n)]
    still = {"scene_id": "4", "text_overlay": {"title": "Inactif ou chômeur ?"}, "connections": [], "entities": icons(3),
             "actions": [{"at": 1, "action": "spawn", "target": "o0", "cue": "x"}, {"at": 3, "action": "emphasize", "target": "o1", "cue": "x"}]}
    moving = json.loads(json.dumps(still))
    moving["actions"].append({"at": 5, "action": "move", "target": "o0", "to": [4, 0], "cue": "x"})
    formula = json.loads(json.dumps(still))
    formula["entities"].append({"id": "f", "type": "TEX_FORMULA", "position": [0, 2, 0], "initial_state": {"latex": "A = E + C"}})
    briefs = {i: SceneVisualBrief.model_validate({**b, "scene_id": i}) for i, b in (("1", still), ("2", still), ("3", moving), ("4", formula))}
    order = ["1", "2", "3", "4"]
    found = agent004.still_scenes(order, briefs, {"1": {"footage": {"query": "bureau"}}}, {i: 15 for i in order})
    if [m.split(":")[0] for m in found] != ["scene 2"]:
        problems.append(f"still scenes: {found}")
    if agent004.still_scenes(["2"], briefs, {}, {"2": 5}):
        problems.append("a short scene sent back")
    return report("4. agent004: a scene where nothing happens is sent back (not a hook over a film, a formula, a move)", problems)


def case_acronyms():
    problems = []
    for acronym, text in (("BIT", "Au sens du Bureau international du travail, le BIT, un chômeur..."),
                          ("PIB", "le produit intérieur brut, ou PIB"), ("SMIC", "le salaire minimum interprofessionnel de croissance (SMIC)"),
                          ("INSEE", "l'Institut national de la statistique et des études économiques")):
        if not agent003.said_in_full(acronym, text):
            problems.append(f"{acronym} said in full not seen in {text!r}")
    if agent003.said_in_full("BIT", "Au sens du BIT, un chômeur cumule trois conditions"):
        problems.append("BIT alone taken for its full name")
    scenes = [{"scene_id": 1, "narration_text": "Sans emploi, est-on chômeur ? Tout dépend du XIX siècle."},
              {"scene_id": 2, "narration_text": "Le Bureau international du travail, le BIT, pose trois conditions."},
              {"scene_id": 3, "narration_text": "Au sens du BIT, le PIB ne compte pas."}]
    found = agent003.undefined_acronyms(scenes, {"narration": "Nous verrons les conditions du BIT."})
    if [f.split(":")[0] for f in found] != ["plan", "scene 3"] or '"BIT"' not in found[0] or '"PIB"' not in found[1]:
        problems.append(f"found {found}")
    if agent003.undefined_acronyms(scenes[1:2], None):
        problems.append("an acronym said in full sent back")
    return report("5. agent003: an acronym spoken before it is said in full is found", problems)


RACE = {"scene_id": "2", "text_overlay": {"title": "Deux vitesses"}, "connections": [],
        "entities": [{"id": "r", "type": "SPEED_RACE", "position": [0, -0.3, 0], "initial_state": {
            "distance": 1, "distance_unit": "m",
            "runners": [{"label": "Électron", "speed": 0.1, "unit": "mm/s", "icon": "atom"},
                        {"label": "Signal", "speed": 200000, "unit": "km/s", "icon": "zap"}]}}],
        "actions": [{"at": 2, "action": "set_state", "target": "r", "state": {"go": True}, "cue": "x"}]}


def case_race():
    problems = []
    SceneVisualBrief.model_validate(RACE)
    for bad in ({"speed": 0}, {"unit": "noeuds"}, {"icon": "unicorn"}, {"extra": 1}):
        brief = json.loads(json.dumps(RACE))
        brief["entities"][0]["initial_state"]["runners"][0].update(bad)
        try:
            SceneVisualBrief.model_validate(brief)
            problems.append(f"a runner with {bad} accepted")
        except ValueError:
            pass
    race = renderer.race_data(RACE["entities"][0]["initial_state"], "#000000")
    if [r["time"] for r in race["runners"]] != ["2 h 47 min", "5 ns"] or race["ratio"] != "Signal : 2\u202f000 milliards de fois plus rapide":
        problems.append(f"times or ratio: {race['runners']}, {race['ratio']!r}")
    if [renderer.race_time(x) for x in (3e-5, 150, 86400 * 11)] != ["30 µs", "2 min 30 s", "11 jours"]:
        problems.append("durations in words")
    data = renderer.page_data(RACE, 12, None)
    data["events"] = RACE["actions"]
    found = open_pages({"race": data}, """() => {
      const read = t => { window.seek(t); return {x: [...document.querySelectorAll('.race-runner')].map(r => parseFloat(r.style.left)),
        times: [...document.querySelectorAll('.race-time')].map(r => +r.style.opacity), ratio: +document.querySelector('.race-ratio').style.opacity}; };
      return {before: read(1.9), half: read(3.25), end: read(8), conflicts: window.layoutConflicts};
    }""")["race"]
    if found["before"]["x"] != [0, 0] or found["half"]["x"][0] > 0.01 or not 300 < found["half"]["x"][1] < 600:
        problems.append(f"the race: {found}")
    if found["end"]["x"][0] > 0.01 or found["end"]["x"][1] < 800 or found["end"]["times"] != [1, 1] or found["end"]["ratio"] != 1:
        problems.append(f"the end: {found['end']}")
    if found["conflicts"]:
        problems.append(f"conflicts {found['conflicts']}")
    badges = {"scene_id": "2", "text_overlay": {"title": "Deux vitesses"}, "connections": [], "actions": [],
              "entities": [{"id": "e", "type": "OBJECT", "position": [-3, 0, 0], "initial_state": {"icon": "atom", "label": "Électron"}},
                           {"id": "s", "type": "OBJECT", "position": [3, 0, 0], "initial_state": {"icon": "zap", "label": "Signal"}}]}
    said = "Les électrons dérivent très lentement, alors que le signal est presque instantané."
    if not agent004.speeds_by_badges(SceneVisualBrief.model_validate(badges), said) \
            or agent004.speeds_by_badges(SceneVisualBrief.model_validate(RACE), said):
        problems.append("slow versus fast by badges not sent back, or the race sent back")
    return report("6. SPEED_RACE: one track, one scale; real times and ratio; badges sent back", problems,
                  [f"{race['ratio']}; {found['half']['x']}"])


if __name__ == "__main__":
    results = [case_seesaw(), case_fit(), case_film_choice(), case_still(), case_acronyms(), case_race()]
    sys.exit(0 if all(results) else 1)
