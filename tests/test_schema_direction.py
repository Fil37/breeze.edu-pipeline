"""
Check the "direction" of ARROW_ANNOTATION / VECTOR_ARROW (models/visual_brief_schema.py): a cardinal
("UP", "DOWN", "LEFT", "RIGHT", as before) or a vector [x, y] drawn at the angle atan2(y, x).
  A. direction [0.4, 0.9] (the Earth's axis, ~23.5° from the vertical): the schema accepts it, agent010
     gives the angle atan2(0.9, 0.4) = 66.04° (23.96° from the vertical), and the page draws the vector
     and the badge's arrow at that angle (measured on the SVG lines after seek)
  B. direction "UP": the schema accepts it, agent010's page data is exactly what the renderer gave
     before vectors (OLD_VECTOR_DIRECTION below, the previous code), and the arrows are drawn vertical
  C. direction "DIAGONAL" (and [0, 0], ["a", "b"], [1, 2, 3]): the schema refuses it with a message that
     says what is allowed
The drawn angles need Playwright + Chromium (as agent010); without them, A and B check the page data
only and say so. Prints PASS or FAIL per case.

  .venv/bin/python tests/test_schema_direction.py
"""

import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from pydantic import ValidationError                              # noqa: E402

from app.agent import agent010_html_renderer as renderer          # noqa: E402
from models.visual_brief_schema import SceneVisualBrief           # noqa: E402

TOLERANCE = 0.5   # degrees, on the angle measured in the page (pixel rounding)


def OLD_VECTOR_DIRECTION(value):
    """agent010's vector_direction before vectors were validated: the reference for "UP"."""
    named = {"UP": (0, 1), "DOWN": (0, -1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        dx, dy = float(value[0]), float(value[1])
    else:
        dx, dy = named.get(str(value).upper(), (1, 0))
    norm = (dx * dx + dy * dy) ** 0.5 or 1.0
    return [dx / norm, dy / norm]


def brief(direction):
    """A formula with a badge pointing at it, and a vector (the Earth's axis), both along `direction`."""
    return {"scene_id": "1", "text_overlay": {"title": "L'axe de la Terre"},
            "entities": [{"id": "formula", "type": "TEX_FORMULA", "position": [-2, 0, 0], "initial_state": {"latex": "P = m g"}},
                         {"id": "note", "type": "ARROW_ANNOTATION", "position": [-2, -0.6, 0],
                          "initial_state": {"text": "Le poids P", "direction": direction, "target": "formula"}},
                         {"id": "axis", "type": "VECTOR_ARROW", "position": [2.5, -1, 0],
                          "initial_state": {"direction": direction, "length": 2.5, "label": "Axe"}}],
            "connections": [],
            "actions": [{"at": 0.5, "action": "spawn", "target": "formula"}, {"at": 1.0, "action": "spawn", "target": "note"},
                        {"at": 1.5, "action": "spawn", "target": "axis"}]}


def schema_error(data):
    """None if SceneVisualBrief accepts `data`, else its error text."""
    try:
        SceneVisualBrief.model_validate(data)
        return None
    except ValidationError as error:
        return str(error)


def page_entities(data):
    return {e["id"]: e for e in renderer.page_data(data, 6.0, 6)["entities"]}


def drawn_angles(data):
    """The angles (degrees, y up) of the vector's line and the badge's arrow, as the page draws them at
    t = 4 s; None if Playwright or Chromium is missing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    script = """id => { const l = id === "axis" ? E[id].vector.line : E[id].ann.line;
                        const [x1, y1, x2, y2] = ["x1", "y1", "x2", "y2"].map(k => +l.getAttribute(k));
                        return Math.atan2(-(y2 - y1), x2 - x1) * 180 / Math.PI; }"""
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        path = os.path.join(folder, "scene.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer.build_page(renderer.page_data(data, 6.0, 6)))
        try:
            browser = playwright.chromium.launch()
        except Exception:              # Chromium not installed
            return None
        try:
            page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
            renderer.open_scene(page, path)
            page.evaluate("window.seek(4)")
            return {name: page.evaluate(script, name) for name in ("axis", "note")}
        finally:
            browser.close()


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      {p}" for p in problems))
    return not problems


def case_a():
    data, problems, notes = brief([0.4, 0.9]), [], []
    error = schema_error(data)
    if error:
        problems.append(f"schema refused [0.4, 0.9]: {error}")
    expected = math.degrees(math.atan2(0.9, 0.4))
    entities = page_entities(data)
    for name, key in (("axis", "vector"), ("note", "annotation")):
        angle = entities[name][key]["angle"]
        if abs(angle - expected) > 0.01:
            problems.append(f"{name}: page data angle {angle}°, expected {expected:.2f}°")
    notes.append(f"angle atan2(0.9, 0.4) = {expected:.2f}° ({90 - expected:.2f}° from the vertical)")
    drawn = drawn_angles(data)
    if drawn is None:
        notes.append("Playwright/Chromium missing: drawn angles not measured")
    else:
        for name, angle in drawn.items():
            notes.append(f"{name}: drawn at {angle:.2f}°")
            if abs(angle - expected) > TOLERANCE:
                problems.append(f"{name}: drawn at {angle:.2f}°, expected {expected:.2f}°")
    return report("A. direction [0.4, 0.9]: accepted, drawn tilted", problems, notes)


def case_b():
    data, problems, notes = brief("UP"), [], []
    error = schema_error(data)
    if error:
        problems.append(f"schema refused \"UP\": {error}")
    entities = page_entities(data)
    for name, key in (("axis", "vector"), ("note", "annotation")):
        if entities[name][key]["direction"] != OLD_VECTOR_DIRECTION("UP"):
            problems.append(f"{name}: page direction {entities[name][key]['direction']}, before {OLD_VECTOR_DIRECTION('UP')}")
    drawn = drawn_angles(data)
    if drawn is None:
        notes.append("Playwright/Chromium missing: drawn angles not measured")
    else:
        for name, angle in drawn.items():
            notes.append(f"{name}: drawn at {angle:.2f}°")
            if angle != 90:
                problems.append(f"{name}: drawn at {angle}°, expected exactly 90° (vertical, as before)")
    return report("B. direction \"UP\": accepted, same page data and drawing as before", problems, notes)


def case_c():
    problems, notes = [], []
    for value in ("DIAGONAL", [0, 0], ["a", "b"], [1, 2, 3]):
        error = schema_error(brief(value))
        if error is None:
            problems.append(f"schema accepted {value!r}")
        elif "direction" not in error:
            problems.append(f"{value!r} refused without naming direction: {error}")
        else:
            notes.append(f"{value!r}: " + next(line.strip() for line in error.splitlines() if "direction" in line))
    return report("C. invalid directions: refused with a clear message", problems, notes)


results = [case_a(), case_b(), case_c()]
sys.exit(0 if all(results) else 1)
