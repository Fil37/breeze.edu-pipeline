"""
Check the ohmmeter (the electronics video of 2026-11-05 read 500 Ω on a lone 1 kΩ resistor, drew a
bench supply as "the ohmmeter's source", and wrote "1 000 Ω" everywhere), offline but for the browser:
  1. agent004: the reading is worked out from the circuit drawn (two 1 kΩ across the same pins: 500 Ω;
     a part faded out is gone, a closed switch is a wire); a wrong reading, a supply drawn as the
     ohmmeter's source, a supply left on, a part measured before it appears are sent back
  2. units with their prefix: labels and formulas rewritten ("1 000 Ω" -> "1 kΩ", "0,01 A" -> "10 mA"),
     cues left as said; the voice says "kilo-ohms"
  3. the page: the meter shows its range (4,700 kΩ), in ohms from the start when named "Ohmmètre"
Prints PASS or FAIL per case. Case 3 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_ohmmeter.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.tts_manager import normalize_text_for_tts                      # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def part(id_, type_, label, x=0, y=0):
    return {"id": id_, "type": type_, "position": [x, y, 0], "initial_state": {"label": label}}


def wire(a, pa, b, pb):
    return {"source_id": a, "source_port": pa, "target_id": b, "target_port": pb}


def brief(entities, connections, actions):
    return SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "Ohmmètre"}, "entities": entities,
                                            "connections": connections, "actions": actions})


def measure(at, value, a="r1.left", b="r1.right"):
    return {"at": at, "action": "measure", "target": "m", "target_pin_a": a, "target_pin_b": b, "value": value, "unit": "Ω", "cue": "x"}


METER = part("m", "VOLTMETER_PROBES", "Ohmmètre", 5)
PAIR = [part("r1", "RESISTOR", "R1 1 kΩ"), part("r2", "RESISTOR", "R2 = 1 000 Ω", 0, 2), METER]
ACROSS = [wire("r1", "left", "r2", "left"), wire("r1", "right", "r2", "right")]


def case_reading():
    problems = []
    check = agent004.ohmmeter_problems
    if check(brief(PAIR, ACROSS, [measure(1, 500)])):
        problems.append(f"two 1 kΩ in parallel read 500 Ω sent back: {check(brief(PAIR, ACROSS, [measure(1, 500)]))}")
    wrong = check(brief(PAIR, ACROSS, [measure(1, 1000)]))
    if len(wrong) != 1 or "500 Ω" not in wrong[0]:
        problems.append(f"a wrong reading kept, or told without the right one: {wrong}")
    lifted = brief(PAIR, ACROSS, [{"at": 0.5, "action": "fade_out", "target": "r2", "cue": "x"}, measure(1, 1000)])
    if check(lifted):
        problems.append(f"the parallel part faded out still counted: {check(lifted)}")
    lone = check(brief([part("r1", "RESISTOR", "R1 1 kΩ"), METER], [], [measure(1, 500)]))
    if len(lone) != 1:
        problems.append(f"500 Ω on a lone 1 kΩ kept (the video of 2026-11-05): {lone}")
    late = brief(PAIR, ACROSS, [{"at": 3, "action": "spawn", "target": "r1", "cue": "x"}, measure(1, 500)])
    if not any("before it appears" in p for p in check(late)):
        problems.append("a part measured before it appears kept")
    series = [part("r1", "RESISTOR", "R1 1 kΩ"), part("r2", "RESISTOR", "R2 4,7 kΩ", 0, 2),
              part("k", "SWITCH", "K", 2, 2), METER]
    chain = [wire("r1", "right", "k", "in"), wire("k", "out", "r2", "left")]
    if agent004.ohms_between(brief(series, chain, []), "r1.left", "r2.right", 1) != float("inf"):
        problems.append("an open switch conducts")
    closed = brief(series, chain, [{"at": 0.5, "action": "set_state", "target": "k", "state": {"closed": True}, "cue": "x"}])
    if abs(agent004.ohms_between(closed, "r1.left", "r2.right", 1) - 5700) > 1e-6:
        problems.append(f"closed switch, 1 kΩ + 4,7 kΩ in series: {agent004.ohms_between(closed, 'r1.left', 'r2.right', 1)}")
    source = PAIR + [{"id": "ps", "type": "POWER_SUPPLY", "position": [-4, 0, 0],
                      "initial_state": {"voltage": 1, "label": "Source interne de l'ohmmètre"}}]
    if not any("ohmmeter's source" in p for p in check(brief(source, ACROSS, [measure(1, 500)]))):
        problems.append("a supply drawn as the ohmmeter's source kept")
    bench = PAIR + [{"id": "ps", "type": "POWER_SUPPLY", "position": [-4, 0, 0], "initial_state": {"voltage": 5, "label": "Alimentation"}}]
    feed = ACROSS + [wire("ps", "positive", "r1", "left"), wire("ps", "negative", "r1", "right")]
    on = [{"at": 0.2, "action": "set_state", "target": "ps", "state": {"output": True}, "cue": "x"}]
    if not any("on:" in p or "with ['ps'] on" in p for p in check(brief(bench, feed, on + [measure(1, 500)]))):
        problems.append("a measure on a powered circuit kept")
    off = on + [{"at": 0.6, "action": "set_state", "target": "ps", "state": {"output": False}, "cue": "x"}]
    if check(brief(bench, feed, off + [measure(1, 500)])):
        problems.append(f"a measure once the supply is off sent back: {check(brief(bench, feed, off + [measure(1, 500)]))}")
    return report("1. agent004: the ohm reading worked out from the circuit drawn; a source for the ohmmeter sent back", problems)


def case_units():
    problems = []
    scenes = [{"entities": [{"initial_state": {"label": "R1 = 1 000 Ω", "latex": r"R \approx 1\,000\,\Omega"}},
                            {"initial_state": {"label": "Limite 0,01 A", "value": 1000}},
                            {"initial_state": {"label": "R3 470 Ω et 2 200 000 Ω"}}],
               "actions": [{"cue": "1 000 Ω"}]}]
    agent004.si_prefixes(scenes)
    e = scenes[0]["entities"]
    found = [e[0]["initial_state"]["label"], e[0]["initial_state"]["latex"], e[1]["initial_state"]["label"],
             e[1]["initial_state"]["value"], e[2]["initial_state"]["label"], scenes[0]["actions"][0]["cue"]]
    if found != ["R1 = 1 kΩ", r"R \approx 1\,\text{k}\Omega", "Limite 10 mA", 1000, "R3 470 Ω et 2,2 MΩ", "1 000 Ω"]:
        problems.append(f"rewritten: {found}")
    if agent004.label_ohms("R2 4,7 kΩ") != 4700 or agent004.label_ohms("R3 470Ω") != 470:
        problems.append("a label's value misread")
    for text, said in (("R1 vaut 4,7 kΩ", "R1 vaut 4 virgule 7 kilo-ohms"), ("100 µF", "100 microfarads")):
        if normalize_text_for_tts(text) != said:
            problems.append(f"{text!r} said {normalize_text_for_tts(text)!r}")
    return report("2. units with their prefix on screen (1 kΩ, 10 mA), cues untouched, the voice says kilo-ohms", problems)


def case_page():
    problems = []
    pages = {}
    for name, value, actions in (("measured", 4700, True), ("idle", 0, False)):
        b = {"scene_id": "1", "text_overlay": {"title": "Ohmmètre"}, "entities": [part("r1", "RESISTOR", "R1 4,7 kΩ"), METER],
             "connections": [], "actions": [measure(1, value)] if actions else []}
        SceneVisualBrief.model_validate(b)
        data = renderer.page_data(b, 6, None)
        data["events"] = b["actions"]
        pages[name] = data
    found = open_pages(pages, "() => { window.seek(5); const s = document.querySelector('.dmm-screen');"
                              " return {screen: s.textContent, head: document.querySelector('.dmm-head').textContent}; }")
    if found["measured"]["screen"] != "4,700 kΩ":
        problems.append(f"4,7 kΩ shown as {found['measured']['screen']!r}")
    if "Ω" not in found["idle"]["screen"] or "V DC" in found["idle"]["head"]:
        problems.append(f"a meter named Ohmmètre shows volts: {found['idle']}")
    return report("3. the meter shows its range (4,700 kΩ), in ohms from the start when named so", problems)


if __name__ == "__main__":
    results = [case_reading(), case_units(), case_page()]
    sys.exit(0 if all(results) else 1)
