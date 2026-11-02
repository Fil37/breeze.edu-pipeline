"""
Check BODY and the move_along action: a body anchored on a curve travels along it, the vectors riding
on it ({"anchor": {"body": id}}) going with it. Before, nothing could move: the "chute permanente" of
the breeze_(math) run of 2026-10-31 was a still picture.
  1. validation (schema, agent004, agent005): a satellite on an orbit with a move_along is valid;
     refused with a message: move_along on a non-BODY, on a body that is not anchored, without "to",
     with a duration of 0, a vector riding on an unknown body
  2. agent010 data: a move_along gets its track, 30 samples a second, from the anchor to "to"; a second
     move_along starts where the first one ended
  3. agent010 page (Chromium, measured on what is drawn): before the move the satellite is at rest on
     its anchor; during it, at a quarter, half and three quarters of the lap, its disc is on the orbit
     at the right angle, its velocity runs along the orbit anticlockwise, its gravity points at the
     centre, each label past its own arrow's tip; after it, the satellite holds its last place
Prints PASS or FAIL per case. Case 3 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_move_along.py
"""

import copy
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from pydantic import ValidationError                                    # noqa: E402

from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent005_educationqa as agent005                  # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import SceneVisualBrief                 # noqa: E402

LAP = 6.2832
ON_CURVE_PX, ANGLE_TOLERANCE = 3.0, 4.0
ENTITIES = [
    {"id": "ax", "type": "AXES_GRAPH", "position": [0, -0.07, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}},
    {"id": "orbit", "type": "CURVE_PLOT", "position": [0, -0.07, 0],
     "initial_state": {"x_func": "3*np.cos(t)", "y_func": "3*np.sin(t)", "axes": "ax", "label": "Orbite"}},
    {"id": "sat", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "Satellite", "anchor": {"curve": "orbit", "t": 0}}},
    {"id": "vel", "type": "VECTOR_ARROW", "position": [0, 0, 0],
     "initial_state": {"anchor": {"body": "sat"}, "direction": "TANGENT", "length": 1.3, "label": "Vitesse"}},
    {"id": "grav", "type": "VECTOR_ARROW", "position": [0, 0, 0],
     "initial_state": {"anchor": {"body": "sat"}, "direction": "CENTER", "length": 1.0, "label": "Gravité"}}]
MOVE = {"at": 2.0, "action": "move_along", "target": "sat", "to": LAP, "duration": 4, "cue": "il tombe"}


def scene(actions, entities=ENTITIES):
    spawns = [{"at": 0.2 + 0.2 * i, "action": "spawn", "target": e["id"], "cue": "x"} for i, e in enumerate(entities)]
    return {"scene_id": "1", "text_overlay": {"title": "Une chute permanente"}, "connections": [],
            "entities": copy.deepcopy(entities), "actions": spawns + actions}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def problems_of(brief):
    """What the schema, then agent004's checks, then agent005's action check say about a brief."""
    try:
        model = SceneVisualBrief.model_validate(brief)
    except ValidationError as exc:
        return [next(line.strip() for line in str(exc).splitlines() if "Value error" in line)[:150]]
    found = agent004.validate_storyboard_topology([model], {"1": 10})
    entities = {e["id"]: e for e in brief["entities"]}
    found += [f"agent005: {p}" for p in (agent005.action_problem(a, entities) for a in brief["actions"]) if p]
    return found


def case_validation():
    problems, notes = [], []
    good = problems_of(scene([MOVE]))
    if good:
        problems.append(f"the satellite was refused: {good}")
    unanchored = copy.deepcopy(ENTITIES[:3])
    unanchored[2]["initial_state"].pop("anchor")
    rider_on_nothing = copy.deepcopy(ENTITIES)
    rider_on_nothing[3]["initial_state"]["anchor"] = {"body": "ghost"}
    bad = {"move_along on a non-BODY": scene([{**MOVE, "target": "orbit"}]),
           "a body that is not anchored": scene([MOVE], unanchored),
           "no \"to\"": scene([{k: v for k, v in MOVE.items() if k != "to"}]),
           "a duration of 0": scene([{**MOVE, "duration": 0}]),
           "a vector riding on an unknown body": scene([MOVE], rider_on_nothing)}
    for label, brief in bad.items():
        found = problems_of(brief)
        if not found:
            problems.append(f"accepted: {label}")
        else:
            notes.append(f"{label}: {found[0][:140]}")
    return report("1. validation: a moving satellite accepted, wrong ones refused", problems, notes)


def case_tracks():
    second = {**MOVE, "at": 6.5, "to": 2 * LAP, "duration": 2}
    events = renderer.page_data(scene([MOVE, second]), 10.0, 10)["events"]
    moves = [e for e in events if e["action"] == "move_along"]
    problems = []
    first, then = moves[0]["track"], moves[1]["track"]
    if len(first["points"]) != 4 * renderer.MOTION_FPS or len(then["points"]) != 2 * renderer.MOTION_FPS:
        problems.append(f"{len(first['points'])} and {len(then['points'])} samples, expected 120 and 60")
    if max(abs(first["points"][0][0] - 3), abs(first["points"][0][1])) > 1e-6:
        problems.append(f"the first track starts at {first['points'][0]}, not at the anchor (3, 0)")
    if max(abs(a - b) for a, b in zip(first["points"][-1], then["points"][0])) > 1e-6:
        problems.append("the second move does not start where the first ended")
    if set(first["riders"]) != {"vel", "grav"}:
        problems.append(f"riders {set(first['riders'])}")
    return report("2. agent010 data: tracks from the anchor, chained, 30 samples a second", problems,
                  [f"{len(first['points'])} + {len(then['points'])} samples, riders {sorted(first['riders'])}"])


MEASURE = """() => {
  const stage = document.getElementById("stage").getBoundingClientRect();
  const rect = n => { const q = n.getBoundingClientRect(); return [(q.left + q.right) / 2 - stage.left, (q.top + q.bottom) / 2 - stage.top]; };
  const toStage = (el, x, y) => { const p = new DOMPoint(x, y).matrixTransform(el.getScreenCTM()); return [p.x - stage.left, p.y - stage.top]; };
  const c = E.orbit.curvePath, L = c.getTotalLength(), orbit = [];
  for (let i = 0; i <= 2000; i++) { const p = c.getPointAtLength(L * i / 2000); orbit.push(toStage(c, p.x, p.y)); }
  const arrows = {};
  for (const id of ["vel", "grav"]) { const l = E[id].vector.line, [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map(k => +l.getAttribute(k));
    arrows[id] = {start: toStage(l, x1, y1), end: toStage(l, x2, y2), label: rect(E[id].vector.g.querySelector("text"))}; }
  return {disc: rect(E.sat.shape), orbit, arrows};
}"""


def case_page():
    from playwright.sync_api import sync_playwright
    brief, frames = scene([MOVE]), {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(brief, 8.0, 8)))
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in (1.9, 3.0, 4.0, 5.0, 7.5):
                page.evaluate(f"window.seek({t})")
                frames[t] = page.evaluate(MEASURE)
        finally:
            browser.close()
    problems, notes = [], []
    orbit = frames[1.9]["orbit"]
    xs, ys = [p[0] for p in orbit], [p[1] for p in orbit]
    centre = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    for t, expected in ((1.9, 0.0), (3.0, 90.0), (4.0, 180.0), (5.0, 270.0), (7.5, 0.0)):
        frame = frames[t]
        disc = frame["disc"]
        gap = min(math.hypot(p[0] - disc[0], p[1] - disc[1]) for p in orbit)
        angle = math.degrees(math.atan2(centre[1] - disc[1], disc[0] - centre[0])) % 360   # screen y points down
        off = min(abs(angle - expected), 360 - abs(angle - expected))
        line = f"t={t}: satellite {gap:.1f} px from the orbit at {angle:.0f}° (expected {expected:.0f}°)"
        if gap > ON_CURVE_PX or off > ANGLE_TOLERANCE:
            problems.append(line)
        radial = [disc[0] - centre[0], disc[1] - centre[1]]
        for name, arrow in frame["arrows"].items():
            start, end = arrow["start"], arrow["end"]
            way = [end[0] - start[0], end[1] - start[1]]
            if math.hypot(start[0] - disc[0], start[1] - disc[1]) > ON_CURVE_PX:
                problems.append(f"t={t}: {name} does not start on the satellite")
            if name == "vel":
                cross = radial[0] * way[1] - radial[1] * way[0]
                dev = abs(90 - math.degrees(math.acos(max(-1, min(1, (radial[0] * way[0] + radial[1] * way[1])
                                                                   / (math.hypot(*radial) * math.hypot(*way)))))))
                if dev > ANGLE_TOLERANCE or cross >= 0:
                    problems.append(f"t={t}: the velocity is not along the orbit, anticlockwise ({dev:.1f}° off)")
            else:
                to_centre = [centre[0] - start[0], centre[1] - start[1]]
                dev = math.degrees(math.acos(max(-1, min(1, (to_centre[0] * way[0] + to_centre[1] * way[1])
                                                          / (math.hypot(*to_centre) * math.hypot(*way))))))
                if dev > ANGLE_TOLERANCE:
                    problems.append(f"t={t}: the gravity is {dev:.1f}° off the centre")
            label = arrow["label"]
            ahead = (label[0] - end[0]) * way[0] + (label[1] - end[1]) * way[1]
            if ahead <= 0:
                problems.append(f"t={t}: {name}'s label is not past its arrow's tip")
        notes.append(line)
    return report("3. agent010: the satellite goes round, its vectors and labels with it", problems, notes)


try:
    import playwright  # noqa: F401
except ImportError:
    sys.exit("FAIL  Playwright is not installed (pip install playwright && playwright install chromium)")
results = [case_validation(), case_tracks(), case_page()]
sys.exit(0 if all(results) else 1)
