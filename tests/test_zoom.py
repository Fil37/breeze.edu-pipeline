"""
Check the camera's zoom (going inside a thing: the user asked for it wherever the narration goes into
an entity), offline but for the browser:
  1. on the page: zoom_in frames the thing with a dashed line, the view grows on it and fades; the
     next scene (D.arrive) grows in from the middle; zoom_out starts on the thing and pulls back;
     titles never move
  2. agent004: a narration going inside a thing ("à l'intérieur de la puce") with no zoom before it is
     sent back; a zoom_in with seconds of narration after it, or a zoom_out late in its scene, too;
     zooms in the right places, or a component zooming by itself, are kept
Prints PASS or FAIL per case. Case 1 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_zoom.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402
from test_reactive import open_pages                                    # noqa: E402


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


BOARD = [{"id": "chip", "type": "OBJECT", "position": [0, 0, 0], "initial_state": {"icon": "cpu", "label": "Puce"}},
         {"id": "led", "type": "OBJECT", "position": [4, 0, 0], "initial_state": {"icon": "lightbulb", "label": "LED"}}]


def brief(scene_id, entities, actions):
    return {"scene_id": scene_id, "text_overlay": {"title": "La puce"}, "connections": [], "entities": entities,
            "actions": [{"at": at, "action": kind, "target": target, "cue": "x"} for at, kind, target in actions]}


READ = """() => {
  const read = t => { window.seek(t); const m = new DOMMatrix(getComputedStyle(WORLD).transform);
    const frames = [...WORLD.querySelectorAll('.zoom-frame')].map(f => +f.style.opacity);
    return {k: m.a, opacity: +WORLD.style.opacity, frame: Math.max(0, ...frames),
            title: document.getElementById('title').parentElement.id}; };
  return {before: read(1), framed: read(3.3), half: read(3.9), done: read(4.9), conflicts: window.layoutConflicts};
}"""


def case_page():
    problems = []
    pages = {}
    for name, b, arrive in (("in", brief("2", BOARD, [(3, "zoom_in", "chip")]), False),
                            ("inside", brief("3", [{"id": "fp", "type": "FPGA_GRID", "position": [0, 0, 0],
                                                    "initial_state": {"cols": 3, "rows": 2, "design": ["ET"]}}], []), True),
                            ("out", brief("4", BOARD, [(0, "zoom_out", "chip")]), False)):
        SceneVisualBrief.model_validate(b)
        data = renderer.page_data(b, 6, None)
        data["events"], data["arrive"] = b["actions"], arrive
        pages[name] = data
    found = open_pages(pages, READ)
    z, inside, out = found["in"], found["inside"], found["out"]
    if not (z["before"]["k"] == 1 and z["framed"]["frame"] > 0.5 and 1 < z["half"]["k"] < z["done"]["k"] and z["done"]["opacity"] == 0):
        problems.append(f"zoom_in: {z}")
    if z["done"]["title"] != "stage":
        problems.append("the title moved into the camera")
    if not (inside["done"]["k"] == 1 and inside["done"]["opacity"] == 1):
        problems.append(f"the scene after a zoom_in does not settle once arrived: {inside}")
    if not (out["before"]["k"] > 1.2 or out["framed"]["k"] == 1) or out["done"]["k"] != 1:
        problems.append(f"zoom_out: {out}")
    if any(f["conflicts"] for f in found.values()):
        problems.append(f"conflicts: {[f['conflicts'] for f in found.values()]}")
    arrival = open_pages({"inside": pages["inside"]}, "() => { window.seek(0.2); return new DOMMatrix(getComputedStyle(WORLD).transform).a; }")
    if not arrival["inside"] < 0.8:
        problems.append(f"the inside does not grow in from the zoom: scale {arrival['inside']} at 0.2 s")
    out_start = open_pages({"out": pages["out"]}, "() => { window.seek(0); return new DOMMatrix(getComputedStyle(WORLD).transform).a; }")
    if not out_start["out"] > 2:
        problems.append(f"zoom_out does not start on the thing: scale {out_start['out']}")
    return report("1. zoom_in dives into a thing, the next scene arrives from it, zoom_out pulls back", problems)


def case_agent004():
    problems = []
    narrations = {"2": "Voici une carte avec sa puce.", "3": "À l'intérieur de la puce, des blocs logiques.",
                  "4": "Revenons à la carte."}
    durations = {"2": 10, "3": 12, "4": 8}
    fpga = [{"id": "fp", "type": "FPGA_GRID", "position": [0, 0, 0], "initial_state": {"cols": 3, "rows": 2, "design": ["ET"]}}]

    def check(two, three, four=()):
        briefs = {i: SceneVisualBrief.model_validate(b) for i, b in
                  (("2", brief("2", BOARD, two)), ("3", brief("3", fpga, three)), ("4", brief("4", BOARD, four)))}
        return agent004.zoom_problems(["2", "3", "4"], briefs, narrations, durations)
    if len(check([], [])) != 1:
        problems.append(f"going inside with no zoom kept: {check([], [])}")
    if check([(8.5, "zoom_in", "chip")], [], [(0, "zoom_out", "chip")]):
        problems.append(f"zooms in the right places sent back: {check([(8.5, 'zoom_in', 'chip')], [], [(0, 'zoom_out', 'chip')])}")
    if len(check([(1, "zoom_in", "chip")], [])) != 1:
        problems.append("a zoom_in with seconds of narration after it kept")
    if len(check([(8.5, "zoom_in", "chip")], [], [(5, "zoom_out", "chip")])) != 1:
        problems.append("a zoom_out late in its scene kept")
    zoomed = brief("3", fpga, [])
    zoomed["actions"] = [{"at": 2, "action": "set_state", "target": "fp", "state": {"zoom": "ET"}, "cue": "x"}]
    briefs = {"2": SceneVisualBrief.model_validate(brief("2", BOARD, [])), "3": SceneVisualBrief.model_validate(zoomed)}
    if agent004.zoom_problems(["2", "3"], briefs, narrations, durations):
        problems.append("an FPGA_GRID zooming by itself sent back")
    return report("2. agent004: going inside a thing needs a zoom; zoom_in ends a scene, zoom_out opens one", problems)


if __name__ == "__main__":
    results = [case_page(), case_agent004()]
    sys.exit(0 if all(results) else 1)
