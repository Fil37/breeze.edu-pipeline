"""
Check WAVE (the mechanical-waves video of 2026-11-05 drew a rope as five discs scattered, an ola as
spectator icons all over), offline but for the browser:
  1. a bad initial_state is refused; in each mode (rope, water, crowd, spring) the medium moves where
     the wave is and only there; the marked point stays at its x (up and down: rope, water, crowd) or
     only moves along a little (spring); the energy arrow goes along; the ola's spectators stand up in
     turn; a spring's compression is named; a standing wave's nodes never move, its antinodes swing, the
     two waves it is the sum of drawn on "parts"
  2. agent004 sends back a wave drawn as discs or icons, a standing wave drawn travelling (the physics
     video of 2026-11-05: the whole rope moving), the two waves it is the sum of spoken of, not shown
Prints PASS or FAIL per case. Case 1 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_wave.py
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


def brief(state, actions=()):
    return {"scene_id": "2", "text_overlay": {"title": "Une onde"}, "connections": [],
            "entities": [{"id": "w", "type": "WAVE", "position": [0, 0, 0], "initial_state": state}],
            "actions": [{"at": at, "action": "set_state", "target": "w", "state": st, "cue": "x"} for at, st in actions]}


READ = """() => {
  const p = E.w.data.waveParts, read = t => { window.seek(t);
    const dot = [+p.dot.getAttribute('cx'), +p.dot.getAttribute('cy')];
    const people = p.people ? p.people.map(q => new DOMMatrix(q.g.getAttribute('transform').replace(/translate\\(([^ ]+) ([^)]+)\\)/, 'translate($1px, $2px)')).f) : null;
    const coils = p.coils ? p.coils.map(c => +c.getAttribute('x1')) : null;
    return {dot, energy: +p.energy.getAttribute('opacity'), ex: new DOMMatrix((p.energy.getAttribute('transform') || '').replace(/translate\\(([^ ]+) ([^)]+)\\)/, 'translate($1px, $2px)')).e,
            rope: p.rope ? p.rope.getAttribute('d').length : 0, people, coils, note: p.note.textContent,
            squeeze: p.squeeze ? +p.squeeze.getAttribute('opacity') : null}; };
  return {before: read(0.3), a: read(2.6), b: read(3.4), c: read(4.2), conflicts: window.layoutConflicts};
}"""


def case_modes():
    problems = []
    for bad in ({"mode": "laser"}, {"kind": "square"}, {"label": 5}):
        try:
            SceneVisualBrief.model_validate(brief(bad))
            problems.append(f"accepted: {bad}")
        except ValueError:
            pass
    pages = {}
    for mode in ("rope", "water", "crowd", "spring"):
        b = brief({"mode": mode, "kind": "pulse"}, [(1, {"go": True}), (1.5, {"mark": True}), (2, {"energy": True})])
        SceneVisualBrief.model_validate(b)
        data = renderer.page_data(b, 6, None)
        data["events"] = b["actions"]
        pages[mode] = data
    found = open_pages(pages, READ)
    rope = found["rope"]
    if not (rope["before"]["energy"] == 0 and rope["a"]["energy"] == 1 and rope["c"]["ex"] > rope["a"]["ex"]):
        problems.append(f"the energy does not go along: {rope['a']['ex']} then {rope['c']['ex']}")
    xs = {round(found[m][k]["dot"][0]) for m in ("rope",) for k in ("a", "b", "c")}
    if len(xs) != 1:
        problems.append(f"the rope's marked point moves along: {xs}")
    if len({round(found['rope'][k]['dot'][1]) for k in ('a', 'b', 'c')}) < 2:
        problems.append("the rope's marked point never moves up or down")
    crowd = found["crowd"]["b"]["people"]
    if not crowd or max(crowd) - min(crowd) < 30 or "spectateur" not in found["crowd"]["b"]["note"]:
        problems.append(f"the ola: no spectator standing up: {crowd}")
    coils = [found["spring"][k]["coils"] for k in ("a", "c")]
    if coils[0] == coils[1] or not any(found["spring"][k]["squeeze"] for k in ("a", "b", "c")):
        problems.append("the spring's coils do not move, or no compression named")
    if any(found[m]["conflicts"] for m in found):
        problems.append(f"conflicts: {[found[m]['conflicts'] for m in found]}")
    b = brief({"mode": "rope", "kind": "standing"}, [(0.5, {"go": True}), (1, {"parts": True})])
    SceneVisualBrief.model_validate(b)
    data = renderer.page_data(b, 6, None)
    data["events"] = b["actions"]
    st = open_pages({"s": data}, """() => { const p = E.w.data.waveParts, at = x => { const i = p.xs.findIndex(v => Math.abs(v - x) < 1); return i; };
      const read = t => { window.seek(t); return p.rope.getAttribute('d'); };
      const ys = d => d.slice(1).split(' L').map(q => q.split(' ').map(Number));
      const node = p.nodes[1], anti = (p.nodes[0] + p.nodes[1]) / 2, near = (pts, x) => pts.reduce((a, q) => Math.abs(q[0] - x) < Math.abs(a[0] - x) ? q : a)[1];
      const a = ys(read(1.2)), b = ys(read(1.8));
      return {node: [near(a, node), near(b, node)], anti: [near(a, anti), near(b, anti)], parts: +p.lanes.getAttribute('opacity')}; }""")["s"]
    if abs(st["node"][0] - st["node"][1]) > 8 or abs(st["anti"][0] - st["anti"][1]) < 20 or st["parts"] == 0:
        problems.append(f"standing wave: a node moves or an antinode stays, or the two waves not drawn: {st}")
    return report("1. WAVE: rope, water, crowd, spring, standing; the marked point stays, the energy goes", problems)


def case_agent004():
    problems = []
    scattered = SceneVisualBrief.model_validate({
        "scene_id": "3", "text_overlay": {"title": "La corde"}, "connections": [], "actions": [],
        "entities": [{"id": f"m{i}", "type": "BODY", "position": [i * 2 - 4, (-1) ** i, 0], "initial_state": {"label": f"Morceau {i}"}}
                     for i in range(5)]})
    if len(agent004.waves_by_hand(scattered, "La corde transmet la perturbation de proche en proche.")) != 1:
        problems.append("a rope drawn as discs not sent back")
    drawn = SceneVisualBrief.model_validate(brief({"mode": "rope"}))
    if agent004.waves_by_hand(drawn, "La corde transmet la perturbation."):
        problems.append("a WAVE sent back")
    briefs = {"3": drawn}
    if "3" not in agent004.needs_circuit(briefs):
        problems.append("a WAVE scene may be a comparison (the wave halved in a panel)")
    say = "Une onde stationnaire : les nœuds restent fixes. Deux ondes opposées s'additionnent."
    travelling = SceneVisualBrief.model_validate(brief({"mode": "rope", "kind": "continuous"}))
    if len(agent004.standing_waves(travelling, say)) != 1:
        problems.append("a standing wave drawn travelling not sent back")
    standing = SceneVisualBrief.model_validate(brief({"mode": "rope", "kind": "standing"}))
    if len(agent004.standing_waves(standing, say)) != 1:
        problems.append("the two waves spoken of, not shown, not sent back")
    shown = SceneVisualBrief.model_validate(brief({"mode": "rope", "kind": "standing"}, [(1, {"parts": True})]))
    if agent004.standing_waves(shown, say):
        problems.append("a standing wave with its two waves shown sent back")
    for bad in ({"kind": "standing", "loops": 9}, {"kind": "standing", "loops": "deux"}):
        try:
            SceneVisualBrief.model_validate(brief(bad))
            problems.append(f"accepted: {bad}")
        except ValueError:
            pass
    same = {str(i): SceneVisualBrief.model_validate({**brief({"mode": "rope", "kind": "standing", "loops": 2}), "scene_id": str(i)})
            for i in range(2, 7)}
    if len(agent004.repeated_drawings(list(same), same)) != 1:
        problems.append("one standing wave set alike in five scenes not sent back")
    same["4"] = SceneVisualBrief.model_validate({**brief({"mode": "rope", "kind": "standing", "loops": 3}), "scene_id": "4"})
    same["5"] = SceneVisualBrief.model_validate({**brief({"mode": "rope", "kind": "standing", "loops": 1}), "scene_id": "5"})
    if agent004.repeated_drawings(list(same), same):
        problems.append("harmonics that change sent back")
    return report("2. agent004: a wave drawn as discs, a standing wave drawn travelling, its two waves unshown, one picture all along: sent back", problems)


if __name__ == "__main__":
    results = [case_modes(), case_agent004()]
    sys.exit(0 if all(results) else 1)
