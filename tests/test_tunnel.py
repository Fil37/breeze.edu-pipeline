"""
Check TUNNEL (the physics hook of 2026-11-03 drew the tunnel effect as an atom icon beside a door
icon) and the acronyms' voice, offline but for the browser:
  1. TUNNEL: a bad initial_state is refused; the view zooms from a circuit into a dashed frame on its
     wire, which becomes the tube; {"bounce": true} takes the dot to the wall and back; {"tunnel":
     true} takes it through, a wave at the wall (a weaker part beyond it), out whole on the
     other side; never given a state, it zooms then tunnels; agent004 sends back the effect drawn as
     icons; later scenes with a TUNNEL start zoomed in (the physics run of 2026-11-03 zoomed in three
     times, the circuit spilling over a graph: the zoom now stays inside the drawing)
  2. the voice: an acronym is spelled as one hyphenated word, each letter as it sounds ("FPGA" ->
     "èf-pé-jé-a"), words like NASA left alone, the gates ET, OU, NON said as words; "quantum" said as it sounds ("kwantome")
  3. the hook's film: a clip rejected by hand (an electrician at a panel, for a chip factory) is never
     offered again nor taken from the cache
Prints PASS or FAIL per case. Case 1 needs Playwright + Chromium (as agent010).

  .venv/bin/python tests/test_tunnel.py
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


def brief(state, actions=()):
    return {"scene_id": "1", "text_overlay": {"title": "Traverser un mur ?"}, "connections": [],
            "entities": [{"id": "tun", "type": "TUNNEL", "position": [0, 0, 0], "initial_state": state}],
            "actions": [{"at": at, "action": "set_state", "target": "tun", "state": s, "cue": "x"} for at, s in actions]}


READ = """() => {
  const p = E.tun.data.tunnelParts, read = t => { window.seek(t);
    return {x: +p.dot.getAttribute('cx'), faint: +p.dot.getAttribute('opacity'), circuit: +p.ctx.getAttribute('opacity'),
            zoom: p.zoom.getAttribute('transform'), wave: +p.wave.getAttribute('opacity'), path: p.wave.getAttribute('d'),
            note: p.note.textContent}; };
  return {start: read(0.2), zoomed: read(2.4), hit: read(3.6), back: read(5.9), wall: read(8.3), out: read(11),
          conflicts: window.layoutConflicts};
}"""


def case_tunnel():
    problems = []
    state = {"particle": "Circuit entier", "barrier": "Barrière"}
    SceneVisualBrief.model_validate(brief(state))
    for change in ({"particle": "x" * 30}, {"barrier": ""}, {"zoom": "yes"}):
        try:
            SceneVisualBrief.model_validate(brief({**state, **change}))
            problems.append(f"accepted: {change}")
        except ValueError:
            pass
    pages = {}
    for name, actions in (("given", [(2, {"bounce": True}), (6, {"tunnel": True})]), ("auto", [])):
        data = renderer.page_data(brief(state, actions), 12, None)
        data["events"] = brief(state, actions)["actions"]
        pages[name] = data
    found = open_pages(pages, READ)
    g, a = found["given"], found["auto"]
    wall = 650
    if not (g["start"]["circuit"] == 1 and "scale(0.16" in g["start"]["zoom"] and g["zoomed"]["circuit"] == 0
            and "scale(1)" in g["zoomed"]["zoom"]):
        problems.append(f"no zoom from the circuit into the tube: {g['start']} then {g['zoomed']}")
    if not (wall - 60 < g["hit"]["x"] < wall and g["back"]["x"] < 200 and "rebondit" in g["hit"]["note"]):
        problems.append(f"bounce: at the wall {g['hit']}, back {g['back']}")
    if not (abs(g["wall"]["x"] - wall) < 40 and g["wall"]["faint"] < 0.5 and g["wall"]["wave"] > 0.5 and g["wall"]["path"]
            and "onde" in g["wall"]["note"] and g["out"]["x"] > 1100 and g["out"]["faint"] == 1 and not g["out"]["path"]):
        problems.append(f"tunnel: at the wall {g['wall']}, out {g['out']}")
    if a["out"]["x"] < 1100 or "Effet tunnel" not in a["out"]["note"]:
        problems.append(f"never given a state, it does not tunnel through: {a['out']}")
    if g["conflicts"]:
        problems.append(f"conflicts: {g['conflicts']}")
    icons = SceneVisualBrief.model_validate({
        "scene_id": "1", "text_overlay": {"title": "Traverser un mur ?"}, "connections": [], "actions": [],
        "entities": [{"id": "p", "type": "OBJECT", "position": [-3, 0, 0], "initial_state": {"icon": "atom", "label": "Particule"}},
                     {"id": "m", "type": "OBJECT", "position": [3, 0, 0], "initial_state": {"icon": "door-closed", "label": "Mur"}}]})
    if len(agent004.tunnel_by_icons(icons, "Une particule peut traverser un mur : c'est l'effet tunnel.")) != 1 \
            or agent004.tunnel_by_icons(icons, "La particule reste devant la porte."):
        problems.append("the tunnel effect drawn as icons not sent back, or a scene without it sent back")
    scenes = [{"entities": [{"type": "TUNNEL", "initial_state": {}}]}, {"entities": [{"type": "TUNNEL", "initial_state": {}}]}]
    seen = False
    for scene in scenes:
        seen = renderer.once_zoomed(scene, seen)
    if [sc["entities"][0]["initial_state"].get("zoom") for sc in scenes] != [None, False]:
        problems.append(f"the zoom not kept to the first scene with a TUNNEL: {scenes}")
    return report("1. TUNNEL: zoom in (first time only), bounce back, through the wall; icons for it sent back", problems)


def case_voice():
    problems = []
    for text, said in (("Un FPGA", "Un èf-pé-jé-a"), ("le PIB et la BCE", "le pé-i-bé et la bé-cé-eu"),
                       ("la NASA", "la NASA"), ("I = U / R", "i égal u sur erre"),
                       ("Un quantum d'énergie", "Un kwantome d'énergie"),
                       ("les portes ET, OU, NON et NON-ET", "les portes et, ou, non et non-et"),
                       ("à 37 °C", "à 37 degrés Celsius"), ("un angle de 90°", "un angle de 90 degrés"), ("effet quantique", "effet quantique")):
        if normalize_text_for_tts(text) != said:
            problems.append(f"{text!r} -> {normalize_text_for_tts(text)!r}, expected {said!r}")
    from app.agent import agent003_scriptwriter as agent003
    if '"37 degrés Celsius"' not in agent003.PROMPT:
        problems.append("agent003 not told to write a temperature in digits with degrés Celsius")
    return report("2. an acronym spelled as one hyphenated word, each letter as it sounds", problems)


def case_rejected_clip():
    import tempfile
    from app.render import footage
    problems = []
    hits = [{"id": n, "tags": tags, "duration": 10, "isGRated": True,
             "videos": {"large": {"url": f"https://cdn.pixabay.com/{n}.mp4", "size": 1000, "width": 1920}}}
            for n, tags in ((1, "électricien, usine, circuits"), (2, "puce, silicium, salle blanche"))]
    offered = []
    saved = (footage.search_pixabay, footage.download, footage.FOOTAGE_DIR, footage.load_index, footage.save_index)
    with tempfile.TemporaryDirectory() as folder:
        index = {"clips": {"pixabay:1": {"file": "pixabay_1_1920.mp4"}}, "queries": {"usine de puces": "pixabay:1"},
                 "checked": ["usine de puces"], "rejected": {"pixabay:1": "an electrician at a panel"}}
        open(os.path.join(folder, "pixabay_1_1920.mp4"), "w").close()
        try:
            footage.search_pixabay = lambda query, key: hits
            footage.download = lambda url, path: open(path, "w").close()
            footage.FOOTAGE_DIR, footage.load_index, footage.save_index = folder, lambda: index, lambda i: None
            os.environ.setdefault("PIXABAY_API_KEY", "test-key")
            clip = footage.find_clip("usine de puces", lambda query, c: offered.append([x["tags"] for x in c]) or 0)
        finally:
            footage.search_pixabay, footage.download, footage.FOOTAGE_DIR, footage.load_index, footage.save_index = saved
    if clip.get("id") != 2 or offered != [["puce, silicium, salle blanche"]]:
        problems.append(f"the rejected clip offered or taken: {clip.get('id')}, offered {offered}")
    if "electrician at an electrical panel" not in agent004.FOOTAGE_CHOICE:
        problems.append("the chooser is not told an electrical panel is not electronics")
    return report("3. a clip rejected by hand is never offered nor taken from the cache", problems)


if __name__ == "__main__":
    results = [case_tunnel(), case_voice(), case_rejected_clip()]
    sys.exit(0 if all(results) else 1)
