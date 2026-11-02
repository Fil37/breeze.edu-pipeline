"""
Show the HTML renderer (agent010) on three hard-coded scenes, without the LLM or instance/ files:

  1. a circuit stacked in a column: wires on the named ports, electrons, the ammeter's reading
  2. axes with two curves (legend), a vector and a formula
  3. 1/x on its own axes (gap at 0)
  4. instruments: a voltmeter whose probes measure the lamp then the battery, telemetry cards for
     the counters, an annotation arrow (the instrument column on the right)
  5. ground references: a chassis ground on the battery's - terminal, the earth joined to it by a
     dashed (optional) wire, and probe polarity: +6 V, then -6 V with the probes swapped
  6. annotations: a short pointer badge on the open switch (pill + 50 px arrow, on a side clear of
     the wires) and a status badge ("Tension présente, courant nul") in the instrument column
  7. a water analogy: two tanks and a pipe, the levels moving and the water flowing, all scene long

Actions carry a "cue" (the narration's words they happen on): with --video, each one starts when
the voice says its words; the stills use their "at".

  python tests/test_html_scene.py            # stills: one PNG per scene at 3 moments (fast, no internet)
  python tests/test_html_scene.py --video    # the full video with the French voice (needs internet)

Everything goes to media/test_html_scene/. The .html pages are kept: open one in a browser and
type seek(3) in the console to see the scene at t = 3 s.
Needs: pip install -r requirements.txt, then playwright install chromium (and ffmpeg for --video).
"""

import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from app.agent import agent010_html_renderer as html_renderer   # noqa: E402

OUT_DIR = os.path.join(ROOT, "media", "test_html_scene")
STILL_TIMES = (1.0, 3.5, 7.5)      # seconds into each 8 s scene

circuit = {
    "scene_id": "1",
    "text_overlay": {"title": "Circuit en colonne"},
    "entities": [
        {"id": "bat", "type": "BATTERY", "position": "LEFT", "initial_state": {"label": "Pile"}},
        {"id": "lamp", "type": "LAMP", "position": "TOP", "initial_state": {"label": "Lampe"}},
        {"id": "sw", "type": "SWITCH", "position": "CENTER", "initial_state": {"label": "Interrupteur"}},
        {"id": "amm", "type": "AMMETER", "position": "BOTTOM", "initial_state": {"label": "Ampèremètre"}},
    ],
    "connections": [
        {"source_id": "bat", "source_port": "positive", "target_id": "sw", "target_port": "in"},
        {"source_id": "sw", "source_port": "out", "target_id": "lamp", "target_port": "left_terminal"},
        {"source_id": "lamp", "source_port": "right_terminal", "target_id": "amm", "target_port": "in"},
        {"source_id": "amm", "source_port": "out", "target_id": "bat", "target_port": "negative"},
    ],
    "actions": [
        {"at": 2.5, "action": "set_state", "target": "sw", "state": {"closed": True}},
        {"at": 3, "action": "start_flow", "path": ["bat", "sw", "lamp", "amm", "bat"]},
        {"at": 3.5, "action": "set_state", "target": "lamp", "state": {"on": True}},
        {"at": 5, "action": "set_value", "target": "amm", "value": 0.8, "unit": "A"},
    ],
}

graphs = {
    "scene_id": "2",
    "text_overlay": {"title": "Deux trajectoires", "subtitle": "Linéaire contre quadratique"},
    "entities": [
        {"id": "ax", "type": "AXES_GRAPH", "position": "CENTER",
         "initial_state": {"x_range": [-3, 3], "y_range": [-1, 5], "x_label": "temps", "y_label": "distance"}},
        {"id": "c1", "type": "CURVE_PLOT", "position": "CENTER",
         "initial_state": {"func": "x + 1", "axes": "ax", "label": "Vitesse constante"}},
        {"id": "c2", "type": "CURVE_PLOT", "position": "CENTER",
         "initial_state": {"func": "0.5 * x**2", "axes": "ax", "label": "Accélération"}},
        {"id": "w", "type": "VECTOR_ARROW", "position": [-5.2, 0.8, 0],
         "initial_state": {"direction": "DOWN", "label": "Poids", "length": 1.6}},
        {"id": "f", "type": "TEX_FORMULA", "position": "BOTTOM_RIGHT",
         "initial_state": {"latex": "d = \\frac{1}{2} a t^2"}},
    ],
    "connections": [],
    "actions": [
        {"at": 0.5, "action": "spawn", "target": "ax"},
        {"at": 1.5, "action": "spawn", "target": "c1"},
        {"at": 3.5, "action": "spawn", "target": "c2"},
        {"at": 5, "action": "spawn", "target": "w"},
        {"at": 6, "action": "spawn", "target": "f"},
    ],
}

inverse = {
    "scene_id": "3",
    "text_overlay": {"title": "Une fonction inverse"},
    "entities": [{"id": "inv", "type": "CURVE_PLOT", "position": "CENTER",
                  "initial_state": {"func": "1/x", "label": "y = 1/x"}}],
    "connections": [],
    "actions": [],
}

instruments = {
    "scene_id": "4",
    "text_overlay": {"title": "Mesurer une tension", "subtitle": "Le voltmètre se branche en parallèle"},
    "entities": [
        {"id": "bat", "type": "BATTERY", "position": "LEFT", "initial_state": {"label": "Pile 4,5 V"}},
        {"id": "sw", "type": "SWITCH", "position": [-1.5, 1.2, 0], "initial_state": {"label": "Interrupteur"}},
        {"id": "lamp", "type": "LAMP", "position": [1.5, -0.4, 0], "initial_state": {"label": "Lampe"}},
        {"id": "amm", "type": "AMMETER", "position": [-1.5, -2.2, 0], "initial_state": {"label": "Ampèremètre"}},
        {"id": "vm", "type": "VOLTMETER_PROBES", "position": "RIGHT", "initial_state": {"label": "Voltmètre"}},
        {"id": "note", "type": "ARROW_ANNOTATION", "position": [2.6, 0.6, 0],
         "initial_state": {"text": "Point chaud", "direction": "DOWN"}},
    ],
    "connections": [
        {"source_id": "bat", "source_port": "positive", "target_id": "sw", "target_port": "in"},
        {"source_id": "sw", "source_port": "out", "target_id": "lamp", "target_port": "left_terminal"},
        {"source_id": "lamp", "source_port": "right_terminal", "target_id": "amm", "target_port": "out"},
        {"source_id": "amm", "source_port": "in", "target_id": "bat", "target_port": "negative"},
    ],
    "actions": [
        {"at": 0.8, "action": "set_state", "target": "sw", "state": {"closed": True}},
        {"at": 1.4, "action": "start_flow", "path": ["bat", "sw", "lamp", "amm", "bat"], "current": 0.3},
        {"at": 1.9, "action": "set_state", "target": "lamp", "state": {"on": True}},
        {"at": 2.6, "action": "measure", "target": "vm", "target_pin_a": "lamp.left_terminal",
         "target_pin_b": "lamp.right_terminal", "value": 4.2, "unit": "V"},
        {"at": 4.0, "action": "set_value", "target": "lamp", "value": 1.26, "unit": "W", "decimals": 2,
         "tone": "positive"},
        {"at": 5.0, "action": "measure", "target": "vm", "target_pin_a": "bat.positive",
         "target_pin_b": "bat.negative", "value": 4.5, "unit": "V"},
        {"at": 6.2, "action": "set_value", "target": "bat", "value": 0.3, "unit": "V", "decimals": 1,
         "tone": "negative"},
    ],
}

grounds = {
    "scene_id": "5",
    "text_overlay": {"title": "La masse, notre zéro", "subtitle": "Le signe dépend des pointes"},
    "entities": [
        {"id": "bat", "type": "BATTERY", "position": [-3.8, -0.2, 0], "initial_state": {"label": "Pile 6 V"}},
        {"id": "lamp", "type": "LAMP", "position": [1.0, 0.6, 0], "initial_state": {"label": "Lampe"}},
        {"id": "gnd", "type": "CHASSIS_MASS", "position": [-1.6, -2.0, 0], "initial_state": {"label": "Masse"}},
        {"id": "earth", "type": "EARTH_GROUND", "position": [1.4, -2.0, 0], "initial_state": {"label": "Terre"}},
        {"id": "vm", "type": "VOLTMETER_PROBES", "position": "RIGHT", "initial_state": {"label": "Voltmètre"}},
    ],
    "connections": [
        {"source_id": "bat", "source_port": "positive", "target_id": "lamp", "target_port": "left_terminal"},
        {"source_id": "lamp", "source_port": "right_terminal", "target_id": "bat", "target_port": "negative"},
        {"source_id": "gnd", "source_port": "terminal", "target_id": "bat", "target_port": "negative"},
        {"source_id": "earth", "source_port": "terminal", "target_id": "gnd", "target_port": "terminal",
         "dashed": True},
    ],
    "actions": [
        {"at": 1.0, "action": "start_flow", "path": ["bat", "lamp", "bat"]},
        {"at": 1.5, "action": "set_state", "target": "lamp", "state": {"on": True}},
        {"at": 2.5, "action": "measure", "target": "vm", "target_pin_a": "bat.positive",
         "target_pin_b": "gnd.terminal", "value": 6.0, "unit": "V"},
        {"at": 5.0, "action": "measure", "target": "vm", "target_pin_a": "gnd.terminal",
         "target_pin_b": "bat.positive", "value": -6.0, "unit": "V"},
    ],
}

open_circuit = {
    "scene_id": "6",
    "text_overlay": {"title": "Circuit ouvert : U sans I", "subtitle": "La tension reste, le courant est nul"},
    "entities": [
        {"id": "bat", "type": "BATTERY", "position": [-4.0, 0.0, 0], "initial_state": {"label": "Pile"}},
        {"id": "sw", "type": "SWITCH", "position": [-1.5, 1.5, 0], "initial_state": {"label": "Interrupteur"}},
        {"id": "lamp", "type": "LAMP", "position": [1.0, 0.0, 0], "initial_state": {"label": "Lampe"}},
        {"id": "amm", "type": "AMMETER", "position": [-1.5, -1.5, 0], "initial_state": {"label": "I (A)"}},
        {"id": "vm", "type": "VOLTMETER_PROBES", "position": "RIGHT", "initial_state": {"label": "Voltmètre"}},
        {"id": "open", "type": "ARROW_ANNOTATION", "position": [-1.5, 1.95, 0],
         "initial_state": {"text": "Ouvert", "direction": "DOWN"}},
        {"id": "status", "type": "ARROW_ANNOTATION", "position": [1.0, 0.66, 0],
         "initial_state": {"text": "Tension présente, courant nul", "direction": "DOWN"}},
    ],
    "connections": [
        {"source_id": "bat", "source_port": "positive", "target_id": "sw", "target_port": "in"},
        {"source_id": "sw", "source_port": "out", "target_id": "lamp", "target_port": "left_terminal"},
        {"source_id": "lamp", "source_port": "right_terminal", "target_id": "amm", "target_port": "in"},
        {"source_id": "amm", "source_port": "out", "target_id": "bat", "target_port": "negative"},
    ],
    "actions": [
        {"at": 1.0, "action": "spawn", "target": "open", "cue": "interrupteur est ouvert"},
        {"at": 2.0, "action": "measure", "target": "vm", "target_pin_a": "bat.positive",
         "target_pin_b": "bat.negative", "value": 6.0, "unit": "V", "cue": "six volts"},
        {"at": 4.5, "action": "spawn", "target": "status", "cue": "aucun courant"},
    ],
}

water = {
    "scene_id": "7",
    "text_overlay": {"title": "Le château d'eau", "subtitle": "La hauteur pousse, le débit passe"},
    "entities": [
        {"id": "high", "type": "WATER_TANK", "position": [-3.5, 0.6, 0],
         "initial_state": {"label": "Réservoir haut", "level": 0.6}},
        {"id": "pipe", "type": "PIPE_VALVE", "position": [0.0, -0.6, 0], "initial_state": {"label": "Conduite"}},
        {"id": "low", "type": "WATER_TANK", "position": [3.5, -1.6, 0],
         "initial_state": {"label": "Réservoir bas", "level": 0.15}},
    ],
    "connections": [
        {"source_id": "high", "source_port": "right", "target_id": "pipe", "target_port": "left"},
        {"source_id": "pipe", "source_port": "right", "target_id": "low", "target_port": "left"},
    ],
    "actions": [
        {"at": 1.0, "action": "set_state", "target": "high", "state": {"level": 0.9}, "cue": "différence de hauteur"},
        {"at": 3.0, "action": "start_flow", "path": ["high", "pipe", "low"], "cue": "le débit"},
        {"at": 4.5, "action": "set_state", "target": "low", "state": {"level": 0.7}, "cue": "remplit"},
        {"at": 4.9, "action": "set_state", "target": "high", "state": {"level": 0.45}, "cue": "remplit"},
    ],
}

storyboard = {"scenes": [{"scene_id": b["scene_id"], "visual_brief": b}
                         for b in (circuit, graphs, inverse, instruments, grounds, open_circuit, water)]}
script = {"scenes": [
    {"scene_id": "1", "duration_sec": 8, "narration_text":
        "On ferme l'interrupteur, le courant traverse la lampe puis l'ampèremètre, qui affiche aussitôt sa valeur."},
    {"scene_id": "2", "duration_sec": 8, "narration_text":
        "La première courbe monte régulièrement, la seconde accélère, tandis que le poids tire toujours vers le bas."},
    {"scene_id": "3", "duration_sec": 8, "narration_text":
        "La fonction inverse s'envole près de zéro et se rapproche de l'axe quand x grandit."},
    {"scene_id": "4", "duration_sec": 8, "narration_text":
        "On pose les pointes du voltmètre aux bornes de la lampe, puis aux bornes de la pile : "
        "la différence, ce sont les volts perdus dans les fils."},
    {"scene_id": "5", "duration_sec": 8, "narration_text":
        "Pointe rouge sur le plus, pointe noire sur la masse : plus six volts. On inverse les pointes, "
        "et l'écran affiche moins six volts."},
    {"scene_id": "6", "duration_sec": 8, "narration_text":
        "L'interrupteur est ouvert : le voltmètre lit toujours six volts aux bornes de la pile, "
        "mais aucun courant ne circule."},
    {"scene_id": "7", "duration_sec": 8, "narration_text":
        "Dans le château d'eau, c'est la différence de hauteur qui pousse l'eau ; le débit décrit ce qui "
        "passe dans la conduite et remplit le réservoir du bas."},
]}


def render_stills():
    """One HTML page per scene, screenshotted at a few moments: no voice, no ffmpeg."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": html_renderer.WIDTH, "height": html_renderer.HEIGHT})
        page.on("pageerror", lambda exc: print(f"JavaScript error: {exc}"))
        for scene in storyboard["scenes"]:
            name = f"scene_{scene['scene_id']}"
            html_path = os.path.join(OUT_DIR, name + ".html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_renderer.build_page(html_renderer.page_data(scene["visual_brief"], 8.0, 8)))
            html_renderer.open_scene(page, html_path)
            for conflict in page.evaluate("window.layoutConflicts || []"):
                print(f"Layout conflict ({name}): {conflict}")
            for t in STILL_TIMES:
                page.evaluate(f"window.seek({t})")
                png_path = os.path.join(OUT_DIR, f"{name}_t{t:04.1f}.png")
                page.screenshot(path=png_path)
                print(f"Image : {png_path}")
            print(f"Page  : {html_path}")
        browser.close()


def render_full_video():
    """The same path as agent010 in the pipeline: voices, frames, ffmpeg."""
    warnings = []
    video_path = os.path.join(OUT_DIR, "test_html_scene.mp4")
    error = html_renderer.check_briefs(storyboard)
    if error:
        sys.exit(error)
    scenes = html_renderer.render_video(storyboard, script, video_path, OUT_DIR, warnings)
    for scene in scenes:
        print(scene)
    for warning in warnings:
        print(f"Warning: {warning}")
    print(f"Vidéo générée : {video_path}")


os.makedirs(OUT_DIR, exist_ok=True)
if "--video" in sys.argv:
    render_full_video()
else:
    render_stills()
