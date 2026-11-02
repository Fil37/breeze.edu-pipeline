"""
Check the subtitles, the LANES analogy and the follow-ups of the electronics video of 2026-11-02,
offline but for the browser:
  1. the narration is cut into short lines (a sentence too long into lines of even length), each
     timed on the voice's words (numbers and units spelled out by the voice: "6 V", "0,96 A"); the
     whole video's lines in SubRip form; without word timings, the lines share the voice's length
  2. agent010 page: the line being said shows at the bottom, nothing after the voice; the diagram,
     the vectors' legend and a comparison's panels stay above it
  3. LANES: the schema takes 2 to 4 lanes with a label and a rate (0.2 to 3 per second) and a lane
     icon, nothing else
  4. agent010 page: the lanes' vehicles roll through the gate at each lane's rate (the counts),
     stand still before the lanes are on screen and while they are stopped ({"active": false})
  5. agent004: cars moved one by one to show queues, and a battery standing in the column of the
     branches it feeds, are sent back to the LLM
  6. agent010: on a comparison, each panel's drawing is centred in its panel
Prints PASS or FAIL per case. Cases 2 and 4 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_subtitles_lanes.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent004_visualbriefgenerator as agent004        # noqa: E402
from app.agent import agent010_html_renderer as renderer               # noqa: E402
from app.render.subtitles import LINE_MAX_CHARS, lines_of, srt, subtitle_cues   # noqa: E402
from app.tts_manager import normalize_text_for_tts                     # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, narration_words   # noqa: E402

NARRATION = ("Imagine une pile de 6 V reliée à deux branches parallèles, une branche facile et une branche résistante. "
             "Beaucoup de personnes prédisent que le courant va choisir un seul chemin. "
             "L'ampèremètre lit pourtant 0,96 A dans la branche résistante.")


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def fake_voice(text, step=0.25):
    """Word timings as a voice reading the spelled-out text gives them: one word every `step` s."""
    return [(round(i * step, 2), word) for i, (_, word) in enumerate(narration_words(normalize_text_for_tts(text)))]


def render(pages, script):
    """Load each page, run `script` (a JS function of the page) and return its results by name."""
    from playwright.sync_api import sync_playwright
    found = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            for name, data in pages.items():
                path = os.path.join(folder, name + ".html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(data))
                renderer.open_scene(page, path)
                found[name] = page.evaluate(script)
        finally:
            browser.close()
    return found


def case_lines():
    problems = []
    lines = lines_of(NARRATION)
    if " ".join(lines) != " ".join(NARRATION.split()):
        problems.append("the lines lose or change words")
    if any(len(line) > LINE_MAX_CHARS + 4 for line in lines):
        problems.append(f"lines too long: {[line for line in lines if len(line) > LINE_MAX_CHARS + 4]}")
    if any(len(line) < 12 for line in lines):
        problems.append(f"a leftover line: {lines}")
    spoken = fake_voice(NARRATION)
    words = [word for _, word in spoken]
    cues = subtitle_cues(NARRATION, spoken, spoken[-1][0] + 0.4)
    for cue in cues:              # each line starts on its own first word, as the voice says it
        first = narration_words(normalize_text_for_tts(cue["text"]))[0][1]
        at = [t for t, word in spoken if word == first]
        if not at or min(abs(cue["at"] - t) for t in at) > 1e-6:
            problems.append(f"{cue['text']!r} starts at {cue['at']}, not on {first!r}")
    if [c["at"] for c in cues] != sorted(c["at"] for c in cues) or any(c["end"] <= c["at"] for c in cues):
        problems.append(f"cue times {[(c['at'], c['end']) for c in cues]}")
    if any(cues[i]["end"] != cues[i + 1]["at"] for i in range(len(cues) - 1)):
        problems.append("a gap or an overlap between two lines")
    text = srt([{"at": 61.5, "end": 63.25, "text": "Bonjour"}, {"at": 63.25, "end": 3725.0, "text": "Fin"}])
    if text != "1\n00:01:01,500 --> 00:01:03,250\nBonjour\n\n2\n00:01:03,250 --> 01:02:05,000\nFin\n\n":
        problems.append(f"SubRip {text!r}")
    plain = subtitle_cues(NARRATION, None, 20.0)
    if plain[0]["at"] != 0 or not 19 < plain[-1]["end"] <= 20.6 or len(plain) != len(lines):
        problems.append(f"without word timings: {[(c['at'], c['end']) for c in plain]}")
    if "0,96 A" not in " ".join(c["text"] for c in cues) or "zéro virgule" in " ".join(c["text"] for c in cues):
        problems.append("the lines show the spelled-out text, not the narration")
    return report("1. lines cut short and even, timed on the voice's words, SubRip", problems,
                  [f"{len(lines)} lines: {lines[:3]}...", f"words said: {len(words)}"])


SCENE = {"scene_id": "1", "text_overlay": {"title": "Le courant se partage"},
         "entities": [{"id": "b", "type": "BATTERY", "position": [-3, -2.6, 0], "initial_state": {"label": "Pile 6 V"}},
                      {"id": "l", "type": "LAMP", "position": [2, -2.6, 0], "initial_state": {"label": "Lampe"}},
                      {"id": "v", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                       "initial_state": {"direction": "RIGHT", "symbol": "I", "label": "Courant"}}],
         "connections": [{"source_id": "b", "source_port": "positive", "target_id": "l", "target_port": "left_terminal"},
                         {"source_id": "l", "source_port": "right_terminal", "target_id": "b", "target_port": "negative"}],
         "actions": []}
COMPARISON = {"scene_id": "2", "text_overlay": {"title": "Deux idées"},
              "entities": [{"id": "a", "type": "OBJECT", "position": [-3, 0, 0], "initial_state": {"icon": "car", "label": "A"}},
                           {"id": "c", "type": "OBJECT", "position": [3, 0, 0], "initial_state": {"icon": "bus", "label": "B"}}],
              "connections": [], "actions": []}


def case_page_subtitles():
    problems = []
    cues = subtitle_cues(NARRATION, fake_voice(NARRATION), 12.0, renderer.plain_math)
    pages = {}
    for name, brief, layout in (("circuit", SCENE, "circuit"), ("comparison", COMPARISON, "comparison")):
        data = renderer.page_data(brief, 13.0, None, None, layout, ["A", "B"] if layout == "comparison" else None)
        data["subtitles"] = cues
        pages[name] = data
    at = (cues[1]["at"] + cues[1]["end"]) / 2
    found = render(pages, f"""() => {{
      const read = t => {{ window.seek(t); const s = document.getElementById('subs');
        return [s.textContent, +getComputedStyle(s).opacity]; }};
      const mid = read({at}), top = document.getElementById('subs').getBoundingClientRect().top;
      const lowest = Math.max(...[...document.querySelectorAll('.entity')].map(e => e.getBoundingClientRect().bottom));
      const legend = document.getElementById('vlegend'), panel = document.querySelector('.comparison-panel');
      return {{mid, after: read(12.4), top, lowest, legend: legend ? legend.getBoundingClientRect().bottom : null,
               panel: panel ? panel.getBoundingClientRect().bottom : null}};
    }}""")
    for name, shown in found.items():
        if shown["mid"] != [cues[1]["text"], 1]:
            problems.append(f"{name}: at {at:.2f} s the subtitles show {shown['mid']}, not {cues[1]['text']!r}")
        if shown["after"][1] != 0:
            problems.append(f"{name}: a line still shown after the voice: {shown['after']}")
        if shown["lowest"] > shown["top"]:
            problems.append(f"{name}: the diagram goes down to {shown['lowest']:.0f} px, under the subtitles' top ({shown['top']:.0f})")
    if found["circuit"]["legend"] is None or found["circuit"]["legend"] > found["circuit"]["top"]:
        problems.append(f"the vectors' legend ends at {found['circuit']['legend']}, under the subtitles")
    if found["comparison"]["panel"] is None or found["comparison"]["panel"] > found["comparison"]["top"]:
        problems.append(f"the panels end at {found['comparison']['panel']}, under the subtitles")
    return report("2. the line being said at the bottom; diagram, legend and panels above it", problems,
                  [f"subtitles from y = {found['circuit']['top']:.0f} px"])


def lanes_brief(lanes, icon="car", actions=()):
    return {"scene_id": "5", "text_overlay": {"title": "Des files au péage"},
            "entities": [{"id": "toll", "type": "LANES", "position": [0, 0, 0],
                          "initial_state": {"label": "Péage", "icon": icon, "lanes": lanes}}],
            "connections": [], "actions": list(actions)}


THREE_LANES = [{"label": "File rapide", "rate": 1.5}, {"label": "File 2", "rate": 0.8}, {"label": "File lente", "rate": 0.4}]


def case_lanes_schema():
    problems = []
    try:
        SceneVisualBrief.model_validate(lanes_brief(THREE_LANES))
    except Exception as exc:
        problems.append(f"three good lanes refused: {exc}")
    for why, lanes, icon in (("one lane", THREE_LANES[:1], "car"), ("five lanes", THREE_LANES + THREE_LANES[:2], "car"),
                             ("a rate of 5", [{"label": "A", "rate": 5}, {"label": "B", "rate": 1}], "car"),
                             ("a rate as text", [{"label": "A", "rate": "vite"}, {"label": "B", "rate": 1}], "car"),
                             ("an extra field", [{"label": "A", "rate": 1, "color": "red"}, {"label": "B", "rate": 1}], "car"),
                             ("a long label", [{"label": "Une file beaucoup trop longue ici", "rate": 1}, {"label": "B", "rate": 1}], "car"),
                             ("a rocket", THREE_LANES, "rocket")):
        try:
            SceneVisualBrief.model_validate(lanes_brief(lanes, icon))
            problems.append(f"{why} accepted")
        except Exception:
            pass
    return report("3. LANES: 2 to 4 lanes, a label and a rate each, a lane icon", problems)


def case_lanes_page():
    problems = []
    stop = [{"at": 0, "action": "set_state", "target": "toll", "state": {"active": False}, "cue": "x"}]
    pages = {"running": renderer.page_data(lanes_brief(THREE_LANES), 12.0, None, None, "analogy_fullscreen"),
             "stopped": renderer.page_data(lanes_brief(THREE_LANES, actions=stop), 12.0, None, None, "analogy_fullscreen")}
    pages["stopped"]["events"] = [{**stop[0], "at": 3.0}]       # stopped at 3 s
    found = render(pages, """() => {
      const counts = t => { window.seek(t); return [...document.querySelectorAll('.lane-count')].map(c => +c.textContent); };
      const cars = [...document.querySelectorAll('.lane:first-child .lane-car')];
      window.seek(0); const still = cars.map(c => c.style.left);
      window.seek(0.5); const before = cars.map(c => c.style.left);
      return {at0: counts(0), at3: counts(3), at10: counts(10), still: still.join() === before.join(),
              labels: [...document.querySelectorAll('.lane-label')].map(l => l.textContent), conflicts: window.layoutConflicts};
    }""")
    running, stopped = found["running"], found["stopped"]
    if running["at0"] != [0, 0, 0] or not running["still"]:
        problems.append(f"the lanes move before they are on screen: {running['at0']}")
    expected = [int(((10 - 0.6) * rate * 120 - 70) // 120) + 1 for rate in (1.5, 0.8, 0.4)]
    if running["at10"] != expected:
        problems.append(f"counts at 10 s {running['at10']}, expected {expected}")
    if not running["at10"][0] > running["at10"][1] > running["at10"][2] > 0:
        problems.append(f"the faster lane does not let more through: {running['at10']}")
    if stopped["at10"] != stopped["at3"] or stopped["at3"] != running["at3"]:
        problems.append(f"stopped at 3 s, the counts still change: {stopped['at3']} -> {stopped['at10']}")
    if running["labels"] != ["File rapide", "File 2", "File lente"]:
        problems.append(f"lane labels {running['labels']}")
    if running["conflicts"]:
        problems.append(f"layout conflicts {running['conflicts']}")
    return report("4. lanes roll at their rates, counts at the gate, stopped by active false", problems,
                  [f"counts at 3 s {running['at3']}, at 10 s {running['at10']}"])


def case_agent004():
    problems = []
    cars = {"scene_id": "5", "text_overlay": {"title": "Péage"}, "connections": [],
            "entities": [{"id": f"car_{i}", "type": "OBJECT", "position": [-5, i, 0], "initial_state": {"icon": "car", "label": "File"}}
                         for i in range(3)],
            "actions": [{"at": 1, "action": "move", "target": f"car_{i}", "to": [5, i], "cue": "x"} for i in range(3)]}
    flagged = agent004.queues_by_hand(SceneVisualBrief.model_validate(cars))
    if not flagged or "LANES" not in flagged[0]:
        problems.append(f"three cars moved one by one: {flagged}")
    two = {**cars, "actions": cars["actions"][:2]}
    if agent004.queues_by_hand(SceneVisualBrief.model_validate(two)):
        problems.append("two moved cars sent back")
    column = {"scene_id": "1", "text_overlay": {"title": "Deux branches"}, "actions": [],
              "entities": [{"id": "bat", "type": "BATTERY", "position": [0.11, -0.06, 0]},
                           {"id": "la", "type": "LAMP", "position": [0.95, 1.91, 0]},
                           {"id": "lb", "type": "LAMP", "position": [0.95, -2.04, 0]}],
              "connections": [{"source_id": "bat", "source_port": "positive", "target_id": "la", "target_port": "left_terminal"},
                              {"source_id": "bat", "source_port": "positive", "target_id": "lb", "target_port": "left_terminal"},
                              {"source_id": "la", "source_port": "right_terminal", "target_id": "bat", "target_port": "negative"},
                              {"source_id": "lb", "source_port": "right_terminal", "target_id": "bat", "target_port": "negative"}]}
    flagged = agent004.battery_in_column(SceneVisualBrief.model_validate(column))
    if len(flagged) != 1 or "['la', 'lb']" not in flagged[0]:
        problems.append(f"battery in its branches' column: {flagged}")
    left = {**column, "entities": [{**column["entities"][0], "position": [-3, 0, 0]}] + column["entities"][1:]}
    if agent004.battery_in_column(SceneVisualBrief.model_validate(left)):
        problems.append("a battery on the left of its branches sent back")
    return report("5. agent004: queues drawn car by car, a battery in its branches' column", problems)


def case_panel_centring():
    problems = []
    brief = {"scene_id": "1", "text_overlay": {"title": "Deux branches"}, "actions": [], "connections": [],
             "entities": [{"id": "a", "type": "LAMP", "position": [-5.1, 0, 0]}, {"id": "b", "type": "LAMP", "position": [-2.5, 0, 0]},
                          {"id": "c", "type": "LAMP", "position": [0.2, 1.9, 0]}, {"id": "d", "type": "LAMP", "position": [0.9, -2, 0]}]}
    data = renderer.page_data(brief, 5, None, None, "comparison", ["Prédiction", "Question"])
    x = {e["id"]: e["xy"][0] for e in data["entities"]}
    for (low, high), ids in zip(renderer.PANEL_ROOM, (("a", "b"), ("c", "d"))):
        middle, centre = (min(x[i] for i in ids) + max(x[i] for i in ids)) / 2, (low + high) / 2
        if abs(middle - centre) > 1:
            problems.append(f"panel {ids}: drawn around x = {middle:.0f}, its middle is {centre:.0f}")
        if any(not low <= x[i] <= high for i in ids):
            problems.append(f"panel {ids} leaves its panel: {[x[i] for i in ids]}")
    return report("6. a comparison's panels each centred", problems, [f"x: {x}"])


if __name__ == "__main__":
    results = [case_lines(), case_page_subtitles(), case_lanes_schema(), case_lanes_page(), case_agent004(),
               case_panel_centring()]
    sys.exit(0 if all(results) else 1)
