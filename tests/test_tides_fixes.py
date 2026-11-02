"""
Check the fixes from the evaluation of the 4-channel run of 2026-11-02 (21:02), offline but for the
browser:
  1. TIDES: the Earth in its ocean and the Moon; each step on its set_state (the three points, the
     pull to scale, what is left once the centre's is taken away, the ocean stretched into two bulges,
     the Earth turning with its port's high tides counted, the Sun); never given one, it plays them in
     turn; agent004 sends back tides drawn as droplets around an Earth
  2. the voltmeter: a probe on a battery terminal touches its sign (+ or −), and the meter says where
     each probe is ("Rouge : GND (0 V)", "Noire : Pile 6 V (−)")
  3. the video's question (agent003, everyday words) becomes the hook's title, the LLM's title kept
     as the subtitle; a technical word is explained the first time (agent003's prompt, agent005's)
Prints PASS or FAIL per case. Cases 1 and 2 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_tides_fixes.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent003_scriptwriter as agent003                 # noqa: E402
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent005_educationqa as agent005                  # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def tides_brief(actions):
    return {"scene_id": "3", "text_overlay": {"title": "Deux marées hautes par jour"}, "connections": [],
            "entities": [{"id": "tides", "type": "TIDES", "position": [0, 0, 0], "initial_state": {}}],
            "actions": [{"at": at, "action": "set_state", "target": "tides", "state": state, "cue": "x"} for at, state in actions]}


READ_TIDES = """() => {
  const z = E.tides.data.tideParts, o = g => +g.getAttribute('opacity');
  const read = t => { window.seek(t); return {points: o(z.points), forces: o(z.forces), relative: o(z.relative),
    tide: o(z.tide), spin: o(z.spin), sun: o(z.sun), rx: +z.sea.getAttribute('rx'), ry: +z.sea.getAttribute('ry'),
    count: z.count.textContent, arrows: [...z.forces.querySelectorAll('line')].map(l => Math.abs(+l.getAttribute('x2') - +l.getAttribute('x1')))}; };
  return {start: read(0.5), points: read(2), relative: read(7), stretched: read(11), day: read(13 + 8.5), sun: read(26), conflicts: window.layoutConflicts};
}"""


def case_tides():
    problems = []
    steps = [(1, {"points": True}), (3, {"forces": True}), (6, {"relative": True}), (9, {"stretch": True}),
             (13, {"spin": True}), (24, {"sun": "aligned"})]
    SceneVisualBrief.model_validate(tides_brief(steps))
    pages = {}
    for name, actions in (("given", steps), ("auto", [])):
        data = renderer.page_data(tides_brief(actions), 28, None)
        data["events"] = tides_brief(actions)["actions"]
        pages[name] = data
    found = open_pages(pages, READ_TIDES)
    g = found["given"]
    if g["start"]["points"] or g["start"]["forces"] or g["start"]["rx"] != g["start"]["ry"]:
        problems.append(f"something shown before its state: {g['start']}")
    if g["points"]["points"] != 1 or g["points"]["forces"]:
        problems.append(f"the points not alone at first: {g['points']}")
    if not g["points"]["arrows"][2] > g["points"]["arrows"][1] > g["points"]["arrows"][0]:
        problems.append(f"the pull not strongest at the near point: {g['points']['arrows']}")
    if g["relative"]["relative"] != 1 or g["relative"]["forces"] > 0.3:
        problems.append(f"the relative pull not shown over the faded pull: {g['relative']}")
    s = g["stretched"]
    if not (s["tide"] == 1 and s["rx"] > s["ry"] + 80):
        problems.append(f"the ocean not stretched towards the Moon: {s}")
    if g["day"]["count"] != "En un jour : 2 marées hautes":
        problems.append(f"after a turn, the port's count: {g['day']['count']!r}")
    if not (g["sun"]["sun"] == 1 and g["sun"]["rx"] > s["rx"]):
        problems.append(f"the Sun in line does not make the bulges bigger: {g['sun']}")
    a = found["auto"]
    if not (a["stretched"]["tide"] == 1 and a["day"]["spin"] == 1 and a["sun"]["sun"] == 0):
        problems.append(f"never given a state, the steps not played in turn: {a['stretched']}")
    if g["conflicts"]:
        problems.append(f"conflicts: {g['conflicts']}")
    icons = SceneVisualBrief.model_validate({
        "scene_id": "5", "text_overlay": {"title": "Marées"}, "connections": [], "actions": [],
        "entities": [{"id": "e", "type": "OBJECT", "position": [0, 0, 0], "initial_state": {"icon": "earth", "label": "Terre"}},
                     {"id": "w", "type": "OBJECT", "position": [2, 0, 0], "initial_state": {"icon": "droplet", "label": "Bourrelet"}}]})
    if len(agent004.tides_by_icons(icons, "Deux bourrelets : deux marées hautes par jour.")) != 1 \
            or agent004.tides_by_icons(icons, "La pluie tombe sur la Terre."):
        problems.append("tides drawn as droplets not sent back, or a scene without tides sent back")
    return report("1. TIDES: points, pull to scale, relative pull, two bulges, the Earth turning, the Sun", problems,
                  [f"pull {g['points']['arrows']}, ocean {s['rx']:.0f} x {s['ry']:.0f}, with the Sun {g['sun']['rx']:.0f}"])


CIRCUIT = {"scene_id": "3", "text_overlay": {"title": "Masse : référence"},
           "entities": [{"id": "bat", "type": "BATTERY", "position": [-4, 0, 0], "initial_state": {"label": "Pile 6 V"}},
                        {"id": "lamp", "type": "LAMP", "position": [0, 1, 0], "initial_state": {"label": "Lampe"}},
                        {"id": "gnd", "type": "CHASSIS_MASS", "position": [0, -1.5, 0], "initial_state": {"label": "GND (0 V)"}},
                        {"id": "vm", "type": "VOLTMETER_PROBES", "position": [5, 2, 0], "initial_state": {"label": "Voltmètre"}}],
           "connections": [{"source_id": "bat", "source_port": "positive", "target_id": "lamp", "target_port": "left_terminal"},
                           {"source_id": "lamp", "source_port": "right_terminal", "target_id": "gnd", "target_port": "terminal"},
                           {"source_id": "gnd", "source_port": "terminal", "target_id": "bat", "target_port": "negative"}],
           "actions": [{"at": 1, "action": "measure", "target": "vm", "target_pin_a": "gnd.terminal", "target_pin_b": "bat.negative",
                        "value": 0, "unit": "V", "cue": "x"}]}


def case_probes():
    problems = []
    found = open_pages({"probes": renderer.page_data(CIRCUIT, 8, None)}, """() => {
      window.seek(7);
      const p = P[0], m = p.measures[0], sign = E.bat.shape.querySelector('.neg').getBoundingClientRect();
      const stage = document.getElementById('stage').getBoundingClientRect();
      return {tip: m.pins.b, sign: [(sign.left + sign.right) / 2 - stage.left, (sign.top + sign.bottom) / 2 - stage.top],
              text: p.pinsText.textContent};
    }""")["probes"]
    if max(abs(a - b) for a, b in zip(found["tip"], found["sign"])) > 2:
        problems.append(f"the black probe not on the battery's − sign: {found}")
    if found["text"] != "Rouge : GND (0 V)\nNoire : Pile 6 V (−)":
        problems.append(f"the meter does not say where its probes are: {found['text']!r}")
    return report("2. voltmeter: a probe on a battery touches its sign; the meter says where each probe is", problems,
                  [repr(found["text"])])


def case_question():
    problems = []
    for question, kept in (("La monnaie, ce n'est que des pièces et des billets ?", True), ("La monnaie", False),
                           ("Pourquoi ?", False), ("x" * 90 + " ?", False), (None, False)):
        if (agent003.checked_question(question) is not None) != kept:
            problems.append(f"question {question!r} kept: {not kept}")
    board = {"scenes": [{"visual_brief": {"text_overlay": {"title": "Paiement par carte : et la monnaie ?"}}}]}
    agent004.ask_the_question(board, "La monnaie, ce n'est que des pièces et des billets ?")
    overlay = board["scenes"][0]["visual_brief"]["text_overlay"]
    if overlay != {"title": "La monnaie, ce n'est que des pièces et des billets ?", "subtitle": "Paiement par carte : et la monnaie ?"}:
        problems.append(f"the hook's overlay: {overlay}")
    if "explained in plain words the first time" not in agent003.PROMPT or "bourrelet" not in agent005.PROMPT \
            or "never a technical" not in agent004.PROMPT:
        problems.append("a technical word explained the first time: not asked by agent003, agent004 or agent005")
    return report("3. the video's question is the hook's title; technical words explained the first time", problems)


if __name__ == "__main__":
    results = [case_tides(), case_probes(), case_question()]
    sys.exit(0 if all(results) else 1)
