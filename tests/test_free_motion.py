"""
Check the follow-ups of the breeze_(math) run of 2026-10-31 (18:12): an elevator in free fall was a
curve on axes with three discs stacked on it, labels written over each other ("As Objet te"); the
station and its astronaut were two discs at one point; moves on one cue started 0.4 s apart; the Earth's
card filled the orbit and the gravity ran through it.
  1. schema: "move" (a straight move, no graph) on an OBJECT or a BODY; a BODY or an OBJECT riding in
     another one ("anchor": {"body": id}); refused with a message: a move on an anchored thing, a
     "to" that is not [x, y], an unknown easing, a passenger riding in a passenger
  2. agent010 timing: moves on one cue start together; other actions on one cue stay SAME_CUE_STEP apart
  3. agent004: two bodies at one point are sent back (ride, or one body); its prompt shows the
     straight move; time_to_cues keeps moves on one cue together
  4. agent010 page (Chromium): the elevator falls, faster and faster ("fall"), the astronaut riding
     beside it and its weight vector go with it, nothing overlaps; the fall is shortened so the
     weight and its label stay in the frame
  5. agent010 page (Chromium): on an orbit, the Earth's icon is compact, the gravity stops short of it,
     the astronaut rides beside the station (not on it) and goes round with it
Then the follow-ups of the run of 2026-11-01 (18:27): the cabin's arrows left the frame, its weight
hid its acceleration, it fell out of its comparison panel, a badge covered the astronaut's label, a
badge pointed where a vector had been, and the forces of scene 2 started on nothing.
  6. agent004: a free vector in a scene with objects is sent back (anchor it), so is a comparison
     with an empty panel
  7. agent010 page (Chromium): in a comparison, a falling cabin with two passengers and two vectors
     the same way: the arrows side by side, the whole group in its panel and in the frame, the badge
     at the astronaut beside its label, the badge at the weight going down with it
Then the follow-ups of the run of 2026-11-01 (18:49): the ground's reaction ran into the subtitle,
the cannon was a lightning bolt hiding the mountain, a "slow cannonball" fell in scene units beside
the graph, and a badge at the orbiting station covered its astronaut.
  8. agent004: a "move" in a scene with a graph, and two icons anchored too close on one graph, are
     sent back; the prompt has the contact-force rule; "cannon" is an icon
  9. agent010 page (Chromium): an arrow up from a person under the subtitle and its weight above the
     ground both show whole (the person moves down, the weight stops short of the ground); a badge at
     a station going round stays outside the orbit, clear of the Earth and of the astronaut's label
Then the follow-ups of the run of 2026-11-01 (19:24): a station and its astronaut put 0.2 apart on
the orbit (stacked discs), a SCALE "anchored" in the elevator but left behind (the anchor was ignored),
an astronaut riding beside the station but over the formula next to it, crowded badges.
  10. schema and agent004: an icon type (SCALE) rides in an OBJECT; an anchor on a type that takes
      none is refused; two bodies near each other on one curve moving together are sent back (ride),
      a cannonball starting at its cannon is not
  11. agent010 page (Chromium): the scale rides in the falling elevator; a passenger never lands on
      the host's neighbour; a badge with no clear side takes a longer arrow
Then the follow-ups of the rerun from agent004 (2026-11-01, 19:55): the QA's fix (the astronaut
riding in the station) was refused, its gravity being CENTER, and half of it applied (its move
removed): the station went round alone.
  12. schema, agent005: a CENTER vector on a passenger of a body on a curve is valid, so the QA's
      patch applies; a refused patch keeps the actions it meant to remove. agent010 page: the
      passenger stays on the orbit's outer side all the way round, its gravity pointing at the Earth
  13. vector names: a short symbol by the arrow ("P"), the label in a legend ("P : Poids"): symbols
      from the brief or the label, one per label; the legend under the graph, else at the bottom with
      the diagram kept above it
Then the follow-ups of the run of 2026-11-01 (20:20): told three times to make the astronaut ride in
the station, the LLM spaced them out on the orbit instead; the passenger's weight hit the scale under it.
  14. agent004 merges travellers itself (the second rides in the first, its moves dropped, what rode
      in it now in the first); not when only one moves. agent010: a passenger with a weight goes
      under the others, its arrow whole; on an orbit, passengers never cover the host or each other
Then the follow-ups of the run of 2026-11-01 (20:38): the QA could not turn the orbital launch (a
parabola) into an orbit, patch by patch; the astronaut's gravity pointed beside the Earth.
  15. agent005: set_initial_state patches on one scene applied together ("func": null, then "x_func",
      "y_func"..., and the body's anchor from "x" to "t"), one by one when together they fail.
      agent010: a passenger's CENTER vector points at the curve's centre from the passenger
Then the follow-ups of the run of 2026-11-01 (21:12): "F_g" written as is; the station and its astronaut
spaced just past the gap check; a straight fall shown for "autour de la Terre"; a badge laid on the
elevator, placed where the elevator started (under the titles).
  16. symbols with a subscript ("F_g": F, g below); agent004 merges bodies moving exactly together up to
      RIGID_GAP, and sends back "autour" with only straight falls; a badge at a falling thing is
      placed for where it ends, kept under the titles before
Then the follow-ups of the run of the 4 channels (2026-11-01, 22:00): a formula where the falling
elevator ends (physics), a moving icon over another (electronics), a counter on the cards and a cart
past the backdrop (economics, analogy page).
  17. agent010: nothing still on the way a thing moves, its arrows included; on an analogy page, the
      cards under the counters' row and inside the backdrop
Then the follow-ups of the run of 2026-11-01 (22:12): a number line drawn as two axes with big discs
(maths), icons pushed onto a graph (economics), bodies catching each other up on an orbit (physics).
  18. agent010: an AXES_GRAPH with no curve and points at y = 0 is a number line (one line, dots); a
      graph shares the frame with the icons beside it, none on its axes. agent004: bodies set off
      one after the other on an orbit, meeting, are sent back
Prints PASS or FAIL per case. Cases 4 and 5 need Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_free_motion.py
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
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from models.visual_brief_schema import ComponentType, SceneVisualBrief, move_problem   # noqa: E402

LIFT = {"id": "lift", "type": "OBJECT", "position": [0, 1.2, 0], "initial_state": {"icon": "elevator", "label": "Ascenseur"}}
ASTRO = {"id": "astro", "type": "OBJECT", "position": [0, 1.2, 0],
         "initial_state": {"icon": "person-standing", "label": "Astronaute", "anchor": {"body": "lift"}}}
WEIGHT = {"id": "weight", "type": "VECTOR_ARROW", "position": [0, 0, 0],
          "initial_state": {"anchor": {"body": "lift"}, "direction": "DOWN", "length": 1.2, "label": "Poids"}}
FALL = {"at": 1.0, "action": "move", "target": "lift", "to": [0, -2.0], "duration": 2.0, "easing": "fall", "cue": "x"}

AXES = {"id": "ax", "type": "AXES_GRAPH", "position": [0, -0.2, 0], "initial_state": {"x_range": [-5, 5, 1], "y_range": [-3, 3, 1]}}
ORBIT = {"id": "orbit", "type": "CURVE_PLOT", "position": [0, -0.2, 0],
         "initial_state": {"x_func": "2.5*np.cos(t)", "y_func": "2.5*np.sin(t)", "axes": "ax"}}
EARTH = {"id": "earth", "type": "OBJECT", "position": [0, 0, 0],
         "initial_state": {"icon": "earth", "label": "Terre", "anchor": {"axes": "ax", "x": 0, "y": 0}}}
ISS = {"id": "iss", "type": "BODY", "position": [0, 0, 0], "initial_state": {"label": "Station", "anchor": {"curve": "orbit", "t": 0.4}}}
CREW = {"id": "crew", "type": "BODY", "position": [0, 0, 0],
        "initial_state": {"label": "Astronaute", "size": 0.15, "color": "#10B981", "anchor": {"body": "iss"}}}
GRAVITY = {"id": "grav", "type": "VECTOR_ARROW", "position": [0, 0, 0],
           "initial_state": {"anchor": {"body": "iss"}, "direction": "CENTER", "length": 2.4, "label": "Gravité"}}
ROUND = {"at": 2.0, "action": "move_along", "target": "iss", "to": 3.5, "duration": 3, "cue": "x"}


def scene(entities, actions=()):
    return {"scene_id": "1", "text_overlay": {"title": "Chute libre"}, "connections": [], "entities": copy.deepcopy(entities),
            "actions": [{"at": 0.1 * i, "action": "spawn", "target": e["id"]} for i, e in enumerate(entities)] + list(actions)}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def first_error(exc):
    return next(line.strip() for line in str(exc).splitlines() if "Value error" in line)[:130]


def case_schema():
    problems, notes = [], []
    for label, entities in {"an elevator with a passenger and its weight": [LIFT, ASTRO, WEIGHT],
                            "a station with a BODY riding in it": [AXES, ORBIT, ISS, CREW]}.items():
        try:
            SceneVisualBrief.model_validate(scene(entities))
        except ValidationError as exc:
            problems.append(f"refused: {label}: {first_error(exc)}")
    entities = {e["id"]: (ComponentType(e["type"]), e["initial_state"]) for e in (LIFT, ASTRO, ISS)}
    if move_problem(FALL, entities):
        problems.append(f"the fall was refused: {move_problem(FALL, entities)}")
    bad_moves = {"a passenger moved on its own": {**FALL, "target": "astro"},
                 "a body on a curve moved straight": {**FALL, "target": "iss"},
                 "\"to\" not [x, y]": {**FALL, "to": 3},
                 "an unknown easing": {**FALL, "easing": "bounce"}}
    for label, action in bad_moves.items():
        problem = move_problem(action, entities)
        (notes if problem else problems).append(f"{label}: {problem}" if problem else f"accepted: {label}")
    chain = {**CREW, "id": "cat", "initial_state": {"label": "Chat", "anchor": {"body": "crew"}}}
    for label, entities in {"a passenger riding in a passenger": [AXES, ORBIT, ISS, CREW, chain],
                            "riding in itself": [{**LIFT, "initial_state": {"icon": "elevator", "anchor": {"body": "lift"}}}]}.items():
        try:
            SceneVisualBrief.model_validate(scene(entities))
            problems.append(f"accepted: {label}")
        except ValidationError as exc:
            notes.append(f"{label}: {first_error(exc)}")
    return report("1. schema: straight moves and passengers accepted, wrong ones refused", problems, notes)


def case_timing():
    brief = scene([AXES, ORBIT, ISS, {**ISS, "id": "moon"}],
                  [{"at": 2.0, "action": "move_along", "target": "iss", "to": 3, "duration": 2, "cue": "poids apparent"},
                   {"at": 2.0, "action": "move_along", "target": "moon", "to": 3, "duration": 2, "cue": "poids apparent"},
                   {"at": 2.0, "action": "fade_out", "target": "ax", "cue": "poids apparent"}])
    spoken = [(0.5 * i, w) for i, w in enumerate("On ne sent plus son poids apparent du tout".split())]
    events = {e["target"]: e["at"] for e in renderer.page_data(brief, 6.0, 6, spoken)["events"] if e["action"] != "spawn"}
    problems = []
    if abs(events["iss"] - events["moon"]) > 1e-9:
        problems.append(f"the two moves start {events['moon'] - events['iss']:.2f} s apart")
    if abs(events["ax"] - events["moon"] - renderer.SAME_CUE_STEP) > 1e-9:
        problems.append(f"the fade after them is {events['ax'] - events['moon']:.2f} s after, not {renderer.SAME_CUE_STEP}")
    return report("2. agent010: moves on one cue start together, other actions stay staggered", problems,
                  [f"moves at {events['iss']:.2f} and {events['moon']:.2f} s, the fade at {events['ax']:.2f} s"])


def case_agent004():
    stacked = SceneVisualBrief.model_validate(scene([AXES, ORBIT, ISS, {**ISS, "id": "astro", "initial_state": {
        "label": "Astronaute", "anchor": {"curve": "orbit", "t": 0.4}}}]))
    found = [e for e in agent004.coherence_problems(stacked, "x", 8) if "same point" in e]
    riding = SceneVisualBrief.model_validate(scene([AXES, ORBIT, ISS, CREW]))
    problems = [] if found else ["two bodies at one point not reported"]
    if any("same point" in e for e in agent004.coherence_problems(riding, "x", 8)):
        problems.append("a passenger was reported")
    prompt = agent004.PROMPT
    for part in ("MOVING THINGS WITHOUT A GRAPH", '"easing": "fall"', '"anchor": {{"body": "<its id>"}}'):
        if part not in prompt:
            problems.append(f"the prompt lacks {part!r}")
    brief = {"actions": [{"at": 0, "action": "move", "target": "lift", "cue": "le câble casse"},
                         {"at": 0, "action": "move_along", "target": "iss", "cue": "le câble casse"},
                         {"at": 0, "action": "spawn", "target": "astro", "cue": "le câble casse"}]}
    agent004.time_to_cues(brief, "Soudain le câble casse et tout tombe.", 8)
    times = [a["at"] for a in brief["actions"]]
    if times[0] != times[1] or abs(times[2] - times[1] - agent004.SAME_CUE_STEP) > 1e-6:
        problems.append(f"time_to_cues: {times}")
    return report("3. agent004: stacked bodies sent back, the straight move in its prompt, moves timed together",
                  problems, found + [f"time_to_cues: {times}"])


def measure(brief, times, script, voice=6.0):
    from playwright.sync_api import sync_playwright
    out = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(brief, voice, 6)))
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in times:
                page.evaluate(f"window.seek({t})")
                out[t] = page.evaluate(script)
        finally:
            browser.close()
    return out


HELPERS = """
  const stage = document.getElementById("stage").getBoundingClientRect();
  const rect = n => { const q = n.getBoundingClientRect(); return {l: q.left - stage.left, t: q.top - stage.top, r: q.right - stage.left, b: q.bottom - stage.top}; };
  const centre = q => [(q.l + q.r) / 2, (q.t + q.b) / 2];
  const ends = id => { const l = E[id].vector.line, h = E[id].vector.head.getAttribute("points").split(" ")[0].split(",").map(Number);
    const p = new DOMPoint(+l.getAttribute("x1"), +l.getAttribute("y1")).matrixTransform(l.getScreenCTM());
    const q = new DOMPoint(h[0], h[1]).matrixTransform(l.getScreenCTM());
    return [[p.x - stage.left, p.y - stage.top], [q.x - stage.left, q.y - stage.top]]; };
  const labelRect = id => rect(E[id].box.querySelector(".label"));
"""
LIFT_SCRIPT = "() => {" + HELPERS + """
  return {lift: rect(E.lift.shape), astro: rect(E.astro.shape), astroBox: rect(E.astro.box), liftLabel: labelRect("lift"),
          astroLabel: labelRect("astro"), weight: ends("weight"), weightLabel: E.weight.vector.labelBox, conflicts: window.layoutConflicts};
}"""
ORBIT_SCRIPT = "() => {" + HELPERS + """
  return {earth: rect(E.earth.shape), iss: rect(E.iss.shape), crew: rect(E.crew.shape), issLabel: labelRect("iss"),
          crewLabel: labelRect("crew"), grav: ends("grav"), conflicts: window.layoutConflicts};
}"""


def overlap(p, q):
    return min(p["r"], q["r"]) - max(p["l"], q["l"]) > 1 and min(p["b"], q["b"]) - max(p["t"], q["t"]) > 1


def case_lift():
    brief = scene([LIFT, ASTRO, WEIGHT], [FALL])
    SceneVisualBrief.model_validate(brief)
    frames = measure(brief, (0.9, 2.0, 3.2), LIFT_SCRIPT)
    rest, half, end = frames[0.9], frames[2.0], frames[3.2]
    drop = lambda f: (f["lift"]["t"] - rest["lift"]["t"])
    expected = renderer.to_pixels([0, -2.0])[1] - renderer.to_pixels([0, 1.2])[1]
    problems = []
    # Asked: 432 px down; the weight and its label hanging under it would then leave the frame, so the
    # fall is shortened to keep them in (the whole move, still speeding up), never cut in mid-move.
    lowest = max(end["weight"][1][1], end["weightLabel"]["b"])
    if lowest > renderer.HEIGHT - 10 + 1 or not 0.6 * expected < drop(end) <= expected + 1:
        problems.append(f"the elevator fell {drop(end):.0f} px ({expected} asked), its weight reaches {lowest:.0f} px "
                        f"(frame {renderer.HEIGHT})")
    if not 0.15 < drop(half) / drop(end) < 0.35:
        problems.append(f"halfway through the fall it had gone {drop(half) / drop(end):.0%} of the way: not speeding up")
    for name, f in (("rest", rest), ("end", end)):
        if overlap(f["astro"], f["lift"]) or overlap(f["astroLabel"], f["liftLabel"]) or overlap(f["astroLabel"], f["lift"]):
            problems.append(f"{name}: the astronaut covers the elevator or the labels overlap")
        if f["astro"]["l"] - f["lift"]["r"] > 30 and f["lift"]["l"] - f["astro"]["r"] > 30:
            problems.append(f"{name}: the astronaut is not beside the elevator")
    went = [end["astro"]["t"] - rest["astro"]["t"], end["weight"][0][1] - rest["weight"][0][1]]
    if any(abs(g - drop(end)) > 2 for g in went):
        problems.append(f"the elevator fell {drop(end):.0f} px, the astronaut and the weight {went}")
    if abs(end["weight"][0][0] - (end["lift"]["l"] + end["lift"]["r"]) / 2) > 2 or end["weight"][0][1] < end["liftLabel"]["b"]:
        problems.append("the weight does not start under the elevator, in line with its centre")
    if rest["conflicts"]:
        problems.append(f"conflicts: {rest['conflicts']}")
    return report("4. agent010: the elevator falls faster and faster, its passenger and weight with it", problems,
                  [f"fell {drop(end):.0f} px of {expected} asked ({drop(half) / drop(end):.0%} at half time), "
                   f"its weight down to {lowest:.0f} px of {renderer.HEIGHT}; astronaut and weight {went}"])


def case_orbit():
    brief = scene([AXES, ORBIT, EARTH, ISS, CREW, GRAVITY], [ROUND])
    SceneVisualBrief.model_validate(brief)
    frames = measure(brief, (1.6, 5.2), ORBIT_SCRIPT)
    problems, notes = [], []
    width = frames[1.6]["earth"]["r"] - frames[1.6]["earth"]["l"]
    if width > 100:
        problems.append(f"the Earth's icon is {width:.0f} px wide in the graph")
    for t, f in frames.items():
        tip = f["grav"][1]
        e = f["earth"]
        if e["l"] - 4 <= tip[0] <= e["r"] + 4 and e["t"] - 4 <= tip[1] <= e["b"] + 4:
            problems.append(f"t={t}: the gravity's tip is on the Earth")
        if overlap(f["crew"], f["iss"]) or overlap(f["crewLabel"], f["issLabel"]):
            problems.append(f"t={t}: the astronaut covers the station, or their labels overlap")
        gap = math.dist([(f["crew"]["l"] + f["crew"]["r"]) / 2, (f["crew"]["t"] + f["crew"]["b"]) / 2],
                        [(f["iss"]["l"] + f["iss"]["r"]) / 2, (f["iss"]["t"] + f["iss"]["b"]) / 2])
        if gap > 90:
            problems.append(f"t={t}: the astronaut is {gap:.0f} px from the station")
        notes.append(f"t={t}: astronaut {gap:.0f} px from the station's centre, gravity tip "
                     f"{math.dist(tip, [(e['l'] + e['r']) / 2, (e['t'] + e['b']) / 2]):.0f} px from the Earth's")
    moved = math.dist([frames[1.6]["iss"]["l"], frames[1.6]["iss"]["t"]], [frames[5.2]["iss"]["l"], frames[5.2]["iss"]["t"]])
    if moved < 100:
        problems.append(f"the station moved {moved:.0f} px")
    if frames[1.6]["conflicts"]:
        problems.append(f"conflicts: {frames[1.6]['conflicts']}")
    return report("5. agent010: a compact Earth, a gravity short of it, the astronaut riding beside the station",
                  problems, [f"Earth icon {width:.0f} px wide"] + notes)


CABIN = {"id": "cabin", "type": "OBJECT", "position": [-3.5, 1.6, 0], "initial_state": {"icon": "box", "label": "Cabine en chute libre"}}
CREWMAN = {"id": "crewman", "type": "OBJECT", "position": [0, 0, 0],
           "initial_state": {"icon": "user", "label": "Astronaute", "anchor": {"body": "cabin"}}}
PARCEL = {"id": "parcel", "type": "OBJECT", "position": [0, 0, 0], "initial_state": {"icon": "package", "label": "Objet", "anchor": {"body": "cabin"}}}
GRAV = {"id": "grav", "type": "VECTOR_ARROW", "position": [0, 0, 0],
        "initial_state": {"anchor": {"body": "cabin"}, "direction": "DOWN", "length": 1.8, "label": "Gravité"}}
ACCEL = {"id": "accel", "type": "VECTOR_ARROW", "position": [0, 0, 0],
         "initial_state": {"anchor": {"body": "cabin"}, "direction": "DOWN", "length": 1.5, "label": "Accélération commune"}}
FLOATING = {"id": "floating", "type": "OBJECT", "position": [3.5, 0, 0], "initial_state": {"icon": "user", "label": "Sans gravité"}}
NO_SUPPORT = {"id": "no_support", "type": "ARROW_ANNOTATION", "position": [2.4, 0.9, 0],
              "initial_state": {"text": "Aucun appui", "direction": "UP", "target": "crewman"}}
STILL = {"id": "still", "type": "ARROW_ANNOTATION", "position": [-1.3, 0.7, 0],
         "initial_state": {"text": "La gravité agit toujours", "direction": "UP", "target": "grav"}}
CABIN_FALL = {"at": 0.8, "action": "move", "target": "cabin", "to": [-3.5, -2.5], "duration": 2.5, "easing": "fall", "cue": "x"}


def case_agent004_rules():
    free = SceneVisualBrief.model_validate(scene([LIFT, {"id": "pull", "type": "VECTOR_ARROW", "position": [0, 2, 0],
                                                         "initial_state": {"direction": "DOWN", "label": "Attraction"}}]))
    anchored = SceneVisualBrief.model_validate(scene([LIFT, WEIGHT]))
    found = [e for e in agent004.coherence_problems(free, "x", 8) if "starts on nothing" in e]
    problems = [] if found else ["a free vector beside an object not reported"]
    if any("starts on nothing" in e for e in agent004.coherence_problems(anchored, "x", 8)):
        problems.append("an anchored vector was reported")
    one_side = SceneVisualBrief.model_validate(scene([CABIN, CREWMAN, GRAV]))
    both = SceneVisualBrief.model_validate(scene([CABIN, CREWMAN, GRAV, FLOATING]))
    empty = agent004.empty_panels({"3": one_side, "4": both}, {"3": "comparison", "4": "comparison"})
    if len(empty) != 1 or not empty[0].startswith("scene 3"):
        problems.append(f"empty panels: {empty}")
    if "FORCES ACT ON SOMETHING" not in agent004.PROMPT:
        problems.append("the prompt lacks the forces rule")
    return report("6. agent004: a free force and an empty comparison panel are sent back", problems, found + empty)


CABIN_SCRIPT = "() => {" + HELPERS + """
  const group = ["cabin", "crewman", "parcel"].map(id => rect(E[id].box)).concat(["grav", "accel"].map(id => E[id].vector.labelBox));
  return {grav: ends("grav"), accel: ends("accel"), group, crewLabel: labelRect("crewman"), noSupport: rect(E.no_support.box),
          still: E.still.ann.tip, cabin: rect(E.cabin.shape), conflicts: window.layoutConflicts};
}"""


def case_cabin():
    brief = scene([CABIN, CREWMAN, PARCEL, GRAV, ACCEL, FLOATING, NO_SUPPORT, STILL], [CABIN_FALL])
    SceneVisualBrief.model_validate(brief)
    from playwright.sync_api import sync_playwright
    frames = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6, None, "comparison", ["Impesanteur", "Absence de gravité"])))
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in (0.7, 5.0):
                page.evaluate(f"window.seek({t})")
                frames[t] = page.evaluate(CABIN_SCRIPT)
        finally:
            browser.close()
    rest, end = frames[0.7], frames[5.0]
    problems = []
    apart = abs(end["grav"][0][0] - end["accel"][0][0])
    if apart < 40:
        problems.append(f"the two arrows are {apart:.0f} px apart")
    panel_right = renderer.WIDTH / 2 - 20
    for name, f in (("rest", rest), ("end", end)):
        worst = max(max(r["r"] for r in f["group"]), max(p[0] for p in f["grav"] + f["accel"]))
        lowest = max(max(r["b"] for r in f["group"]), max(p[1] for p in f["grav"] + f["accel"]))
        if worst > panel_right or lowest > renderer.HEIGHT:
            problems.append(f"{name}: the group reaches x {worst:.0f} (panel ends {panel_right:.0f}), y {lowest:.0f}")
        if overlap(f["noSupport"], f["crewLabel"]):
            problems.append(f"{name}: the badge covers the astronaut's label")
    fell = end["cabin"]["t"] - rest["cabin"]["t"]
    followed = end["still"][1] - rest["still"][1]
    if fell < 100 or abs(followed - fell) > 2:
        problems.append(f"the cabin fell {fell:.0f} px, the badge at its weight {followed:.0f} px")
    if rest["conflicts"]:
        problems.append(f"conflicts: {rest['conflicts']}")
    return report("7. agent010: a falling cabin in its panel, arrows side by side, badges clear and following", problems,
                  [f"arrows {apart:.0f} px apart; the cabin fell {fell:.0f} px, the badge at its weight {followed:.0f} px"])


def case_agent004_graph_rules():
    from models.visual_brief_schema import OBJECT_ICON_NAMES
    mountain = {"id": "mountain", "type": "OBJECT", "position": [0, 0, 0],
                "initial_state": {"icon": "mountain", "anchor": {"axes": "ax", "x": 0, "y": 2.2}}}
    cannon = {"id": "cannon", "type": "OBJECT", "position": [0, 0, 0],
              "initial_state": {"icon": "cannon", "anchor": {"axes": "ax", "x": 0, "y": 2.8}}}
    ball = {"id": "slow", "type": "BODY", "position": [0.3, 2, 0], "initial_state": {"label": "Boulet lent"}}
    brief = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, mountain, cannon, ball], [
        {"at": 1, "action": "move", "target": "slow", "to": [1, 1.5], "cue": "x"},
        {"at": 2, "action": "move", "target": "slow", "to": [1.5, 1], "cue": "x"}]))
    found = agent004.coherence_problems(brief, "x", 8)
    moves = [e for e in found if "scene units" in e]
    close = [e for e in found if "anchored" in e and "apart" in e]
    problems = []
    if len(moves) != 1:
        problems.append(f"{len(moves)} message(s) for the move in a graph, 1 expected")
    if len(close) != 1 or "mountain" not in close[0]:
        problems.append(f"icons too close: {close}")
    spread = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, {**cannon, "initial_state": {
        "icon": "cannon", "anchor": {"axes": "ax", "x": 2.5, "y": 2.6}}}, mountain]))
    if any("apart" in e for e in agent004.coherence_problems(spread, "x", 8)):
        problems.append("icons far enough apart were reported")
    if "contact force starts where the contact is" not in agent004.PROMPT or "cannon" not in OBJECT_ICON_NAMES:
        problems.append("the contact-force rule or the cannon icon is missing")
    return report("8. agent004: a move in a graph and icons anchored too close are sent back", problems, moves + close)


STANDING = scene([{"id": "person", "type": "OBJECT", "position": [0, 1.75, 0], "initial_state": {"icon": "person-standing", "label": "Astronaute"}},
                  {"id": "ground", "type": "OBJECT", "position": [0, -1.6, 0], "initial_state": {"icon": "box", "label": "Sol"}},
                  {"id": "weight", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                   "initial_state": {"anchor": {"body": "person"}, "direction": "DOWN", "length": 1.2, "label": "Poids"}},
                  {"id": "reaction", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                   "initial_state": {"anchor": {"body": "person"}, "direction": "UP", "length": 1.2, "label": "Réaction du sol"}}])
STATION_BADGE = {"id": "note", "type": "ARROW_ANNOTATION", "position": [1.2, -3.2, 0],
                 "initial_state": {"text": "Chute libre permanente", "direction": "LEFT", "target": "iss"}}
LAP = {"at": 0.5, "action": "move_along", "target": "iss", "to": 6.6832, "duration": 5, "cue": "x"}


def case_room():
    from playwright.sync_api import sync_playwright
    standing = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const tip = id => { const v = E[id].vector, [x, y] = E[id].data.xy; return [x + v.dx * v.length, y + v.dy * v.length]; };
      const g = E.ground.box.getBoundingClientRect();
      return {up: tip("reaction"), down: tip("weight"), groundTop: g.top - stage.top, conflicts: window.layoutConflicts}; }"""
    orbit = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const rect = n => { const q = n.getBoundingClientRect(); return {l: q.left - stage.left, t: q.top - stage.top, r: q.right - stage.left, b: q.bottom - stage.top}; };
      return {badge: rect(E.note.box), crewLabel: rect(E.crew.box.querySelector(".label")), earth: rect(E.earth.shape),
              centre: stagePoint(E.orbit, [0, 0]), edge: stagePoint(E.orbit, [2.5, 0]), tip: E.note.ann.tip,
              iss: rect(E.iss.shape)}; }"""
    out = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, brief, script, times in (("standing", STANDING, standing, (3.0,)),
                                               ("orbit", scene([AXES, ORBIT, EARTH, ISS, CREW, STATION_BADGE], [LAP]), orbit, (0.4, 2.0, 3.2, 4.4))):
                SceneVisualBrief.model_validate(brief)
                path = os.path.join(folder, f"{name}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                for t in times:
                    page.evaluate(f"window.seek({t})")
                    out[(name, t)] = page.evaluate(script)
        finally:
            browser.close()
    problems, notes = [], []
    st = out[("standing", 3.0)]
    header = 150                       # no subtitle in these scenes: the title zone ends at 150 px
    if st["up"][1] < header:
        problems.append(f"the reaction's tip is at y {st['up'][1]:.0f}, in the title zone (< {header})")
    if st["down"][1] > st["groundTop"] - 4:
        problems.append(f"the weight's tip ({st['down'][1]:.0f}) is under the ground's card (top {st['groundTop']:.0f})")
    if st["conflicts"]:
        problems.append(f"conflicts: {st['conflicts']}")
    notes.append(f"reaction tip at y {st['up'][1]:.0f}, weight tip {st['groundTop'] - st['down'][1]:.0f} px above the ground")
    radius = math.dist(out[("orbit", 0.4)]["centre"], out[("orbit", 0.4)]["edge"])
    for t in (0.4, 2.0, 3.2, 4.4):
        f = out[("orbit", t)]
        b = f["badge"]
        near = math.dist(f["centre"], [min(max(f["centre"][0], b["l"]), b["r"]), min(max(f["centre"][1], b["t"]), b["b"])])
        if overlap(b, f["crewLabel"]) or overlap(b, f["earth"]) or near < radius * 0.9:
            problems.append(f"t={t}: the badge covers the astronaut's label or the Earth, or is inside the orbit "
                            f"({near:.0f} px from its centre, radius {radius:.0f})")
        if math.dist(f["tip"], [(f["iss"]["l"] + f["iss"]["r"]) / 2, (f["iss"]["t"] + f["iss"]["b"]) / 2]) > 260:
            problems.append(f"t={t}: the badge's arrow ends far from the station")
    return report("9. agent010: arrows from a person show whole; a badge at an orbiting station stays outside", problems, notes)


SCALE_IN = {"id": "scale", "type": "SCALE", "position": [0, 0, 0], "initial_state": {"label": "Balance", "anchor": {"body": "lift"}}}


def case_riding_rules():
    problems, notes = [], []
    try:
        SceneVisualBrief.model_validate(scene([LIFT, ASTRO, SCALE_IN]))
    except ValidationError as exc:
        problems.append(f"a scale riding in the elevator was refused: {first_error(exc)}")
    for label, entity in {"a LAMP with an anchor": {"id": "lamp", "type": "LAMP", "position": [0, 0, 0], "initial_state": {"anchor": {"body": "lift"}}},
                          "a SCALE on a curve": {**SCALE_IN, "initial_state": {"anchor": {"curve": "orbit", "t": 0}}}}.items():
        try:
            SceneVisualBrief.model_validate(scene([AXES, ORBIT, LIFT, entity]))
            problems.append(f"accepted: {label}")
        except ValidationError as exc:
            notes.append(f"{label}: {first_error(exc)}")
    crew = {**ISS, "id": "crew", "initial_state": {"label": "Astronaute", "anchor": {"curve": "orbit", "t": 0.6}}}
    together = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, ISS, crew], [
        ROUND, {**ROUND, "target": "crew", "to": 3.7}]))
    found = [e for e in agent004.coherence_problems(together, "x", 8) if "apart on" in e]
    if len(found) != 1 or '"anchor": {"body": "iss"}' not in found[0]:
        problems.append(f"two bodies 0.2 apart moving together: {found}")
    cannon = {"id": "cannon", "type": "OBJECT", "position": [0, 0, 0], "initial_state": {"icon": "cannon", "anchor": {"axes": "ax", "x": 0, "y": 2.5}}}
    ball = {**ISS, "id": "ball", "initial_state": {"label": "Boulet", "anchor": {"curve": "orbit", "t": 1.5708}}}
    leaving = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, cannon, ball], [{**ROUND, "target": "ball", "to": 6.28}]))
    if any("apart on" in e for e in agent004.coherence_problems(leaving, "x", 8)):
        problems.append("a cannonball leaving its cannon was reported")
    return report("10. a scale rides in the elevator; anchors never ignored; bodies moving together near each other sent back",
                  problems, notes + found)


FORMULA = {"id": "formula", "type": "TEX_FORMULA", "position": [0.0, 1.08, 0], "initial_state": {"latex": "g = 0"}}
STATION = {"id": "station", "type": "OBJECT", "position": [-2.5, 1.0, 0], "initial_state": {"icon": "satellite", "label": "Station spatiale"}}
RIDER = {"id": "rider", "type": "OBJECT", "position": [0, -1, 0], "initial_state": {"icon": "person-standing", "label": "Astronaute", "anchor": {"body": "station"}}}
CROWD = [{"id": f"b{i}", "type": "ARROW_ANNOTATION", "position": [0, 0, 0],
          "initial_state": {"text": text, "direction": direction, "target": "rider"}}
         for i, (text, direction) in enumerate((("Flotte ?", "UP"), ("Pas de contact", "RIGHT")))]


def case_riding_page():
    from playwright.sync_api import sync_playwright
    script = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const rect = n => { const q = n.getBoundingClientRect(); return {l: q.left - stage.left, t: q.top - stage.top, r: q.right - stage.left, b: q.bottom - stage.top}; };
      const out = {conflicts: window.layoutConflicts};
      for (const id of Object.keys(E)) if (E[id].box) out[id] = rect(E[id].box);
      if (E.lift) out.liftShape = rect(E.lift.shape);
      return out; }"""
    frames = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, brief, times in (("lift", scene([LIFT, ASTRO, SCALE_IN], [FALL]), (0.9, 3.2)),
                                       ("crowd", scene([STATION, RIDER, FORMULA] + CROWD), (2.0,))):
                SceneVisualBrief.model_validate(brief)
                path = os.path.join(folder, f"{name}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                for t in times:
                    page.evaluate(f"window.seek({t})")
                    frames[(name, t)] = page.evaluate(script)
        finally:
            browser.close()
    problems = []
    rest, end = frames[("lift", 0.9)], frames[("lift", 3.2)]
    fell, scale_fell = end["liftShape"]["t"] - rest["liftShape"]["t"], end["scale"]["t"] - rest["scale"]["t"]
    if fell < 100 or abs(scale_fell - fell) > 2:
        problems.append(f"the elevator fell {fell:.0f} px, the scale {scale_fell:.0f} px")
    if any(overlap(f["scale"], f["lift"]) or overlap(f["scale"], f["astro"]) for f in (rest, end)):
        problems.append("the scale covers the elevator or the astronaut")
    crowd = frames[("crowd", 2.0)]
    if overlap(crowd["rider"], crowd["formula"]):
        problems.append("the astronaut riding beside the station lands on the formula")
    for badge in ("b0", "b1"):
        for other in ("station", "rider", "formula"):
            if overlap(crowd[badge], crowd[other]):
                problems.append(f"badge {badge} covers {other}")
    if crowd["conflicts"]:
        problems.append(f"conflicts: {crowd['conflicts']}")
    return report("11. agent010: the scale rides in the falling elevator; passengers and badges land on nothing", problems,
                  [f"elevator and scale fell {fell:.0f} / {scale_fell:.0f} px"])


def case_passenger_on_orbit():
    from app.agent import agent005_educationqa as agent005
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    crew_gravity = {"id": "crew_g", "type": "VECTOR_ARROW", "position": [0, 0, 0],
                    "initial_state": {"anchor": {"body": "crew"}, "direction": "CENTER", "length": 1.2, "label": "Gravité"}}
    apart = {**ISS, "id": "crew", "initial_state": {"label": "Astronaute", "anchor": {"curve": "orbit", "t": 0.8}}}
    brief = scene([AXES, ORBIT, EARTH, ISS, apart, GRAVITY, crew_gravity], [ROUND, {**ROUND, "target": "crew", "to": 3.9}])
    move_index = next(i for i, a in enumerate(brief["actions"]) if a.get("target") == "crew" and a["action"] == "move_along")
    briefs, corrections = {"1": copy.deepcopy(brief)}, []
    agent005.apply_patches(briefs, [{"op": "set_initial_state", "scene_id": "1", "entity_id": "crew", "key": "anchor",
                                     "value": {"body": "iss"}},
                                    {"op": "remove_action", "scene_id": "1", "index": move_index}], corrections)
    if (briefs["1"]["entities"][4]["initial_state"].get("anchor") != {"body": "iss"}
            or any(a.get("target") == "crew" and a["action"] == "move_along" for a in briefs["1"]["actions"])):
        problems.append(f"the QA's fix did not apply whole: {corrections}")
    refused, corrections2 = {"1": copy.deepcopy(brief)}, []
    agent005.apply_patches(refused, [{"op": "set_initial_state", "scene_id": "1", "entity_id": "crew", "key": "anchor",
                                      "value": {"body": "nobody"}},
                                     {"op": "remove_action", "scene_id": "1", "index": move_index}], corrections2)
    if not any(a.get("target") == "crew" and a["action"] == "move_along" for a in refused["1"]["actions"]):
        problems.append(f"a refused fix still removed the move: {corrections2}")
    notes += corrections + corrections2[-1:]
    fixed = briefs["1"]
    SceneVisualBrief.model_validate(fixed)
    script = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const centre = n => { const q = n.getBoundingClientRect(); return [(q.left + q.right) / 2 - stage.left, (q.top + q.bottom) / 2 - stage.top]; };
      const l = E.crew_g.vector.line, h = E.crew_g.vector.head.getAttribute("points").split(" ")[0].split(",").map(Number);
      const a = new DOMPoint(+l.getAttribute("x1"), +l.getAttribute("y1")).matrixTransform(l.getScreenCTM());
      const b = new DOMPoint(h[0], h[1]).matrixTransform(l.getScreenCTM());
      return {iss: centre(E.iss.shape), crew: centre(E.crew.shape), earth: centre(E.earth.shape),
              g: [[a.x - stage.left, a.y - stage.top], [b.x - stage.left, b.y - stage.top]]}; }"""
    frames = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            path = os.path.join(folder, "orbit.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(fixed, 6.0, 6)))
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in (1.6, 3.0, 4.4, 5.6):
                page.evaluate(f"window.seek({t})")
                frames[t] = page.evaluate(script)
        finally:
            browser.close()
    for t, f in frames.items():
        out_iss, out_crew = math.dist(f["iss"], f["earth"]), math.dist(f["crew"], f["earth"])
        (sx, sy), (ex, ey) = f["g"]
        to_earth = [f["earth"][0] - sx, f["earth"][1] - sy]
        cos = ((ex - sx) * to_earth[0] + (ey - sy) * to_earth[1]) / ((math.hypot(ex - sx, ey - sy) * math.hypot(*to_earth)) or 1)
        if out_crew <= out_iss or math.dist(f["crew"], f["iss"]) > 120 or math.dist([sx, sy], f["crew"]) > 2 or cos < 0.98:
            problems.append(f"t={t}: astronaut {out_crew:.0f} px from the Earth (station {out_iss:.0f}), "
                            f"{math.dist(f['crew'], f['iss']):.0f} px from the station, its gravity cos {cos:.2f}")
    notes.append("astronaut beyond the station all the way round: " + ", ".join(
        f"{math.dist(f['crew'], f['earth']) - math.dist(f['iss'], f['earth']):.0f} px" for f in frames.values()))
    return report("12. the QA's fix applies whole; a passenger stays on the orbit's outer side, its gravity at the Earth", problems, notes)


def case_symbols():
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    entities = [{"label": label, "initial": initial, "vector": {"color": None}} for label, initial in
                (("Gravité", {}), ("Gravité", {}), ("Gain", {}), ("v", {}), ("Réaction du sol", {"symbol": "R"}), ("g (Station)", {}))]
    renderer.vector_symbols(entities)
    got = [(e["vector"].get("symbol"), e["vector"].get("legend")) for e in entities]
    want = [("G", "Gravité"), ("G", "Gravité"), ("Ga", "Gain"), ("v", None), ("R", "Réaction du sol"), ("g", "g (Station)")]
    if got != want:
        problems.append(f"symbols {got}, expected {want}")
    try:
        SceneVisualBrief.model_validate(scene([{**WEIGHT, "initial_state": {**WEIGHT["initial_state"], "symbol": "Poids"}}, LIFT]))
        problems.append("a symbol of 5 letters was accepted")
    except ValidationError as exc:
        notes.append(first_error(exc))
    script = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const rect = n => { const q = n.getBoundingClientRect(); return {t: q.top - stage.top, b: q.bottom - stage.top}; };
      const items = [...document.querySelectorAll(".legend div")].map(d => d.textContent.trim());
      const bottom = document.getElementById("vlegend");
      return {items, bottom: bottom ? rect(bottom) : null, inGraph: !!document.querySelector(".graph .legend .vsym"),
              labels: Object.values(E).filter(e => e.vector && e.vectorLabel).map(e => e.vectorLabel.label.textContent),
              lowest: Math.max(...["lift", "astro"].filter(id => E[id]).map(id => rect(E[id].box).b))}; }"""
    out = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, brief, t in (("orbit", scene([AXES, ORBIT, EARTH, ISS, GRAVITY, SPEED_NAMED]), 5.8),
                                   ("lift", scene([LIFT, ASTRO, WEIGHT], [{**FALL, "to": [0, -3.5]}]), 5.8)):
                path = os.path.join(folder, f"{name}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                page.evaluate(f"window.seek({t})")
                out[name] = page.evaluate(script)
        finally:
            browser.close()
    orbit, lift = out["orbit"], out["lift"]
    if sorted(orbit["labels"]) != ["G", "v"] or not orbit["inGraph"] or not any("G" in i and "Gravité" in i for i in orbit["items"]):
        problems.append(f"orbit: labels {orbit['labels']}, legend {orbit['items']}, under the graph {orbit['inGraph']}")
    if lift["labels"] != ["P"] or not lift["bottom"] or lift["lowest"] > lift["bottom"]["t"]:
        problems.append(f"lift: labels {lift['labels']}, bottom legend {lift['bottom']}, lowest thing at {lift['lowest']}")
    notes.append(f"orbit legend {orbit['items']}; lift: legend from y {lift['bottom']['t'] if lift['bottom'] else '?'}, "
                 f"the fall stops at {lift['lowest']:.0f}")
    return report("13. vector names: symbol by the arrow, label in the legend, the diagram above it", problems, notes)


def case_travellers():
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    crew = {**ISS, "id": "crew", "initial_state": {"label": "Astronaute", "anchor": {"curve": "orbit", "t": 0.6}}}
    crew_g = {"id": "crew_g", "type": "VECTOR_ARROW", "position": [0, 0, 0],
              "initial_state": {"anchor": {"body": "crew"}, "direction": "CENTER", "symbol": "g", "label": "Gravité"}}
    scale_on_crew = {**SCALE_IN, "initial_state": {"label": "Balance", "anchor": {"body": "crew"}}}
    for label, actions, merged in (("both move", [ROUND, {**ROUND, "target": "crew", "to": 3.7, "cue": "y"}], True),
                                   ("only the station moves", [ROUND], False)):
        brief = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, ISS, crew, crew_g, scale_on_crew], actions))
        data, fixes = brief.model_dump(mode="json"), []
        agent004.merge_travellers(brief, data, "scene 1", fixes)
        by_id = {e["id"]: e for e in data["entities"]}
        did = by_id["crew"]["initial_state"].get("anchor") == {"body": "iss"}
        if did != merged:
            problems.append(f"{label}: merged {did}, expected {merged} ({fixes})")
        if merged and did:
            if any(a.get("target") == "crew" and a["action"] == "move_along" for a in data["actions"]):
                problems.append("the astronaut kept its own move")
            if by_id["scale"]["initial_state"]["anchor"] != {"body": "iss"}:
                problems.append("the scale did not move to the station")
            SceneVisualBrief.model_validate(data)
            notes += fixes
    standing = scene([LIFT, {**ASTRO, "id": "rider"}, {**SCALE_IN, "initial_state": {"label": "Balance", "anchor": {"body": "lift"}}},
                      {**WEIGHT, "initial_state": {**WEIGHT["initial_state"], "anchor": {"body": "rider"}}}])
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            path = os.path.join(folder, "lift.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(standing, 6.0, 6)))
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            page.evaluate("window.seek(3)")
            got = page.evaluate("""() => ({length: E.weight.vector.length, full: E.weight.vector.full,
                                           rider: E.rider.box.getBoundingClientRect().top, scale: E.scale.box.getBoundingClientRect().top})""")
        finally:
            browser.close()
    if got["rider"] < got["scale"] or got["length"] < 0.9 * got["full"]:
        problems.append(f"the passenger with a weight: {got}")
    notes.append(f"weight {got['length']:.0f} of {got['full']:.0f} px, the passenger under the scale")
    return report("14. agent004 merges travellers; a passenger's weight shows whole", problems, notes)


def case_grouped_patches():
    from app.agent import agent005_educationqa as agent005
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    launch = {"id": "launch", "type": "CURVE_PLOT", "position": [0, 0, 0],
              "initial_state": {"func": "2.5 - 0.05*x**2", "x_range": [0, 5], "axes": "ax", "label": "Lancer orbital"}}
    ball = {**ISS, "id": "ball", "initial_state": {"label": "Boulet", "anchor": {"curve": "launch", "x": 0}}}
    brief = scene([AXES, launch, ball])
    patch = lambda key, value, entity="launch": {"op": "set_initial_state", "scene_id": "1", "entity_id": entity, "key": key, "value": value}
    fix = [patch("func", None), patch("x_func", "2.5*np.sin(t)"), patch("y_func", "2.5*np.cos(t)"), patch("t_min", 0),
           patch("t_max", 6.2832), patch("x_range", None), patch("anchor", {"curve": "launch", "t": 0}, "ball")]
    briefs, corrections = {"1": copy.deepcopy(brief)}, []
    agent005.apply_patches(briefs, fix, corrections)
    state = briefs["1"]["entities"][1]["initial_state"]
    if "func" in state or "x_func" not in state or briefs["1"]["entities"][2]["initial_state"]["anchor"] != {"curve": "launch", "t": 0}:
        problems.append(f"the parabola was not turned into an orbit: {corrections}")
    SceneVisualBrief.model_validate(briefs["1"])
    mixed, corrections2 = {"1": copy.deepcopy(brief)}, []
    agent005.apply_patches(mixed, [patch("label", "Orbite"), patch("x_func", "np.cos(t)")], corrections2)   # x_func beside func: invalid
    kept = mixed["1"]["entities"][1]["initial_state"]
    if kept.get("label") != "Orbite" or "x_func" in kept:
        problems.append(f"together refused, one by one should keep the good patch only: {corrections2}")
    notes.append(f"{len(corrections)} patches applied together; then {corrections2}")
    crew_g = {"id": "crew_g", "type": "VECTOR_ARROW", "position": [0, 0, 0],
              "initial_state": {"anchor": {"body": "crew"}, "direction": "CENTER", "length": 1.4, "label": "g"}}
    riding = scene([AXES, ORBIT, EARTH, ISS, CREW, crew_g], [ROUND])
    script = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const l = E.crew_g.vector.line, a = new DOMPoint(+l.getAttribute("x1"), +l.getAttribute("y1")).matrixTransform(l.getScreenCTM());
      const q = E.earth.shape.getBoundingClientRect();
      return {start: [a.x - stage.left, a.y - stage.top], d: [E.crew_g.vector.dx, E.crew_g.vector.dy],
              earth: [(q.left + q.right) / 2 - stage.left, (q.top + q.bottom) / 2 - stage.top]}; }"""
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            path = os.path.join(folder, "riding.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(riding, 6.0, 6)))
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            worst = 0.0
            for t in (1.6, 2.6, 3.6, 4.6):
                page.evaluate(f"window.seek({t})")
                f = page.evaluate(script)
                to = [f["earth"][0] - f["start"][0], f["earth"][1] - f["start"][1]]
                angle = math.degrees(math.acos(max(-1, min(1, (f["d"][0] * to[0] + f["d"][1] * to[1]) / (math.hypot(*to) or 1)))))
                worst = max(worst, angle)
        finally:
            browser.close()
    if worst > 2:
        problems.append(f"the astronaut's gravity is up to {worst:.1f} degrees off the Earth")
    notes.append(f"the astronaut's gravity at most {worst:.2f} degrees off the Earth")
    return report("15. the QA's patches on one scene go together; a passenger's gravity points at the Earth", problems, notes)


def case_followups_2112():
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    crew = {**ISS, "id": "crew", "initial_state": {"label": "Astronaute", "anchor": {"curve": "orbit", "t": 1.6}}}   # 2.8 apart
    rigid = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, ISS, crew], [ROUND, {**ROUND, "target": "crew", "to": 4.7}]))
    data, fixes = rigid.model_dump(mode="json"), []
    agent004.merge_travellers(rigid, data, "scene 1", fixes)
    if not fixes:
        problems.append("bodies 0.5 apart moving exactly together were not merged")
    loose = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, ISS, crew], [ROUND, {**ROUND, "target": "crew", "to": 5.5}]))
    data, fixes2 = loose.model_dump(mode="json"), []
    agent004.merge_travellers(loose, data, "scene 1", fixes2)
    if fixes2:
        problems.append(f"bodies moving differently were merged: {fixes2}")
    falling = SceneVisualBrief.model_validate(scene([EARTH_FREE, {**ISS, "initial_state": {"label": "ISS"}}],
                                                    [{**FALL, "target": "iss"}]))
    around = [e for e in agent004.coherence_problems(falling, "elles tombent ensemble autour de la Terre", 8) if "autour" in e]
    if not around:
        problems.append("a straight fall for 'autour' was not sent back")
    notes += fixes + around[:1]
    weight = {**WEIGHT, "initial_state": {**WEIGHT["initial_state"], "symbol": "F_g"}}
    note = {"id": "zero", "type": "ARROW_ANNOTATION", "position": [0, 0, 0],
            "initial_state": {"text": "Poids apparent = 0", "direction": "DOWN", "target": "scale"}}
    brief = scene([{**LIFT, "position": [0, 1.75, 0]}, ASTRO, SCALE_IN, weight, note],
                  [{**FALL, "at": 1.0, "to": [0, -1.0], "duration": 4.0}])
    brief["actions"] = [a if a.get("target") != "zero" else {**a, "at": 2.0} for a in brief["actions"]]
    SceneVisualBrief.model_validate(brief)
    script = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const rect = n => { const q = n.getBoundingClientRect(); return {l: q.left - stage.left, t: q.top - stage.top, r: q.right - stage.left, b: q.bottom - stage.top}; };
      return {badge: rect(E.zero.box), lift: rect(E.lift.box), scale: rect(E.scale.box), astro: rect(E.astro.box),
              symbol: E.weight.vectorLabel.label.textContent, sub: !!E.weight.vectorLabel.label.querySelector("tspan"),
              legend: document.querySelector("#vlegend b").innerHTML}; }"""
    frames = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            path = os.path.join(folder, "lift.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            for t in (2.6, 5.6):
                page.evaluate(f"window.seek({t})")
                frames[t] = page.evaluate(script)
        finally:
            browser.close()
    end = frames[5.6]
    if end["symbol"] != "Fg" or not end["sub"] or "<sub>g</sub>" not in end["legend"]:
        problems.append(f"F_g not written with a subscript: {end['symbol']!r}, legend {end['legend']!r}")
    for t, f in frames.items():
        if any(overlap(f["badge"], f[o]) for o in ("lift", "scale", "astro")) or f["badge"]["t"] < 150 - 1:
            problems.append(f"t={t}: the badge covers the elevator group or the titles: {f['badge']}")
    return report("16. subscripts, rigid travellers merged, 'autour' needs an orbit, a falling thing's badge clear", problems, notes)


def case_paths_and_rows():
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    formula = {"id": "formula", "type": "TEX_FORMULA", "position": [0.4, -1.2, 0], "initial_state": {"latex": "P_{app} = 0"}}
    falling = scene([{**LIFT, "position": [-3, 1.0, 0]}, WEIGHT, formula], [{**FALL, "to": [0, -1.0], "duration": 3}])
    cards = [{"id": f"c{i}", "type": "TRENDING_UP", "position": [-4.7 + 1.3 * i, 0.5, 0], "initial_state": {"label": f"Prix {i}"}}
             for i in range(5)]
    analogy = scene(cards, [{"at": 1.0, "action": "set_value", "target": "c4", "value": 2.4, "unit": "%", "cue": "x"}])
    script = """() => { const stage = document.getElementById("stage").getBoundingClientRect();
      const rect = n => { const q = n.getBoundingClientRect(); return {l: q.left - stage.left, t: q.top - stage.top, r: q.right - stage.left, b: q.bottom - stage.top}; };
      const out = {}; for (const id of Object.keys(E)) if (E[id].box) out[id] = rect(E[id].box);
      if (E.weight) { const v = E.weight.vector, [x, y] = E.weight.data.xy; out.tip = [x + v.dx * v.length, y + v.dy * v.length]; }
      const side = document.getElementById("side"), back = document.querySelector("[data-backdrop]");
      if (side) out.side = rect(side); if (back) out.back = rect(back); return out; }"""
    got = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, brief, layout, t in (("falling", falling, "circuit", 5.0), ("analogy", analogy, "analogy_fullscreen", 3.0)):
                SceneVisualBrief.model_validate(brief)
                path = os.path.join(folder, f"{name}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6, None, layout)))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                page.evaluate(f"window.seek({t})")
                got[name] = page.evaluate(script)
        finally:
            browser.close()
    f = got["falling"]
    tip_in = f["formula"]["l"] <= f["tip"][0] <= f["formula"]["r"] and f["formula"]["t"] <= f["tip"][1] <= f["formula"]["b"]
    if overlap(f["lift"], f["formula"]) or tip_in:
        problems.append(f"the elevator or its weight ends on the formula: lift {f['lift']}, tip {f['tip']}, formula {f['formula']}")
    a = got["analogy"]
    lowest_row, top_card = a["side"]["b"], min(a[f"c{i}"]["t"] for i in range(5))
    if top_card < lowest_row - 1 or any(a[f"c{i}"]["l"] < a["back"]["l"] - 1 or a[f"c{i}"]["r"] > a["back"]["r"] + 1 for i in range(5)):
        problems.append(f"analogy: row ends {lowest_row}, cards from {top_card}; backdrop {a['back']}")
    notes.append(f"counters' row ends at {lowest_row:.0f} px, cards from {top_card:.0f} px")
    return report("17. nothing on a moving thing's way; analogy cards under the counters and in the backdrop", problems, notes)


def case_number_line_and_room():
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    line = {"id": "line", "type": "AXES_GRAPH", "position": [0, 0, 0], "initial_state": {"x_range": [0, 2, 1], "x_label": "réels"}}
    dots = [{"id": f"p{i}", "type": "BODY", "position": [0, 0, 0],
             "initial_state": {"label": label, "anchor": {"axes": "line", "x": x, "y": 0}}}
            for i, (label, x) in enumerate((("0,999...", 0.999), ("1", 1.0)))]
    numbers = scene([line] + dots)
    by_id = {e["id"]: e for e in numbers["entities"]}
    if not renderer.is_number_line(line, by_id) or renderer.is_number_line(AXES, {e["id"]: e for e in (AXES, ORBIT)}):
        problems.append("number lines not told apart from graphs")
    icons = [{"id": f"i{k}", "type": "OBJECT", "position": [-5.7, 1.7 - 1.6 * k, 0], "initial_state": {"icon": "receipt", "label": f"Prix {k}"}}
             for k in range(4)]
    crowded = scene(icons + [{"id": "cart", "type": "CART", "position": [-4, 1.6, 0], "initial_state": {"label": "Panier"}},
                             {**AXES, "position": [0, -0.07, 0]},
                             {"id": "c", "type": "CURVE_PLOT", "position": [0, -0.07, 0], "initial_state": {"func": "0.2*x", "axes": "ax"}}])
    out = {}
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for name, brief in (("numbers", numbers), ("crowded", crowded)):
                SceneVisualBrief.model_validate(brief)
                path = os.path.join(folder, f"{name}.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(renderer.build_page(renderer.page_data(brief, 6.0, 6)))
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                page.evaluate("window.seek(5)")
                out[name] = page.evaluate("""() => ({conflicts: window.layoutConflicts,
                  lines: E.line ? E.line.data.axes.lines.length : null,
                  dot: E.p0 ? E.p0.shape.getBoundingClientRect().width : null})""")
        finally:
            browser.close()
    if out["numbers"]["lines"] != 1 or out["numbers"]["dot"] > 30:
        problems.append(f"number line: {out['numbers']}")
    if out["crowded"]["conflicts"] or out["numbers"]["conflicts"]:
        problems.append(f"conflicts: {out['crowded']['conflicts'] + out['numbers']['conflicts']}")
    moon = {**ISS, "id": "moon", "initial_state": {"label": "Lune", "anchor": {"curve": "orbit", "t": 0}}}
    sat = {**ISS, "id": "sat", "initial_state": {"label": "Satellite", "anchor": {"curve": "orbit", "t": 2.0}}}
    chase = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, moon, sat], [
        {"at": 1.0, "action": "move_along", "target": "moon", "to": 6.28, "duration": 3, "cue": "x"},
        {"at": 3.0, "action": "move_along", "target": "sat", "to": 4.0, "duration": 3, "cue": "x"}]))
    met = [e for e in agent004.coherence_problems(chase, "x", 8) if " meet " in e]
    together = SceneVisualBrief.model_validate(scene([AXES, ORBIT, EARTH, moon, sat], [
        {"at": 1.0, "action": "move_along", "target": "moon", "to": 3.0, "duration": 3, "cue": "x"},
        {"at": 1.0, "action": "move_along", "target": "sat", "to": 5.0, "duration": 3, "cue": "x"}]))
    if not met or any(" meet " in e for e in agent004.coherence_problems(together, "x", 8)):
        problems.append(f"meetings on an orbit: {met}")
    notes += met + [f"number line: {out['numbers']['lines']} line, dots {out['numbers']['dot']:.0f} px"]
    return report("18. number lines, graphs sharing the frame, bodies meeting on an orbit", problems, notes)


EARTH_FREE = {"id": "earth", "type": "OBJECT", "position": [0, -2.5, 0], "initial_state": {"icon": "earth", "label": "Terre"}}
SPEED_NAMED = {"id": "vel", "type": "VECTOR_ARROW", "position": [0, 0, 0],
               "initial_state": {"anchor": {"body": "iss"}, "direction": "TANGENT", "length": 1.0, "label": "v"}}


results = [case_schema(), case_timing(), case_agent004(), case_agent004_rules(), case_agent004_graph_rules(), case_riding_rules()]
try:
    import playwright  # noqa: F401
    results += [case_lift(), case_orbit(), case_cabin(), case_room(), case_riding_page(), case_passenger_on_orbit(), case_symbols(), case_travellers(), case_grouped_patches(), case_followups_2112(), case_paths_and_rows(), case_number_line_and_room()]
except ImportError:
    print("FAIL  4-5. Playwright is not installed (pip install playwright && playwright install chromium)")
    results.append(False)
sys.exit(0 if all(results) else 1)
