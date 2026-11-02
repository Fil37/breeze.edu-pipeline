"""
Check the OBJECT component: any concrete thing with no type of its own (an elevator, a rocket, a
person, the Sun...), drawn from a closed list of icons (OBJECT_ICONS, models/visual_brief_schema.py).
Before, the LLM borrowed another type's icon: the elevator of the breeze_(math) run of 2026-10-31 was
a shopping cart (CART).
  1. schema: an OBJECT with a listed icon, or none (a box), is accepted; an icon outside the list is
     refused, the message listing the allowed ones
  2. every listed icon is on disk (assets/icons): drawn offline, never the "?" fallback; "elevator"
     is breeze's own drawing (Lucide has none)
  3. agent010: an OBJECT is an icon card with its own icon, and two OBJECTs wired side to side get
     their wire (the icon types' four ports)
  4. agent004 offers the list and warns against borrowing CART; agent005 can change an OBJECT's icon
     by patch, and an icon outside the list is dropped
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_object_component.py
"""

import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
from pydantic import ValidationError                                    # noqa: E402

from app.agent import agent004_visualbriefgenerator as agent004         # noqa: E402
from app.agent import agent005_educationqa as agent005                  # noqa: E402
from app.agent import agent010_html_renderer as renderer                # noqa: E402
from app.render.asset_resolver import ICONS_DIR, AssetResolver          # noqa: E402
from models.visual_brief_schema import OBJECT_ICON_NAMES, SceneVisualBrief   # noqa: E402


def obj(entity_id, icon=None, x=0.0, label="Objet"):
    state = {"label": label, **({"icon": icon} if icon else {})}
    return {"id": entity_id, "type": "OBJECT", "position": [x, 0, 0], "initial_state": state}


def scene(entities, connections=()):
    return {"scene_id": "1", "text_overlay": {"title": "Objets"}, "entities": entities, "connections": list(connections),
            "actions": [{"at": 0.2 * i, "action": "spawn", "target": e["id"], "cue": "x"} for i, e in enumerate(entities)]}


def report(label, problems, notes=()):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      {n}" for n in notes)
          + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_schema():
    problems, notes = [], []
    try:
        SceneVisualBrief.model_validate(scene([obj("lift", "elevator", -2), obj("crate", None, 2)]))
    except ValidationError as exc:
        problems.append(f"refused: {exc}")
    try:
        SceneVisualBrief.model_validate(scene([obj("ship", "spaceship")]))
        problems.append("an icon outside the list was accepted")
    except ValidationError as exc:
        message = next(line.strip() for line in str(exc).splitlines() if "Value error" in line)
        notes.append(message[:150] + "…")
        if "elevator" not in message:
            problems.append("the message does not list the allowed icons")
    return report("1. schema: listed icons (or none) accepted, others refused", problems, notes)


def case_icons():
    resolver, problems = AssetResolver(offline=True), []
    fallback = [name for name in OBJECT_ICON_NAMES if resolver.resolve(name)[1] != "cache"]
    if fallback:
        problems.append(f"not on disk: {fallback}")
    with open(os.path.join(ICONS_DIR, "elevator.svg"), encoding="utf-8") as f:
        if "<rect" not in f.read():
            problems.append("assets/icons/elevator.svg is not breeze's drawing")
    return report(f"2. all {len(OBJECT_ICON_NAMES)} icons on disk, drawn offline", problems)


def case_html():
    brief = scene([obj("lift", "elevator", -3, "Ascenseur"), obj("rocket", "rocket", 3, "Fusée")],
                  [{"source_id": "lift", "source_port": "right", "target_id": "rocket", "target_port": "left"}])
    data = {e["id"]: e for e in renderer.page_data(brief, 4.0, 4)["entities"]}
    problems = []
    with open(os.path.join(ICONS_DIR, "elevator.svg"), encoding="utf-8") as f:
        own = f.read().replace("currentColor", "#0F172A")
    icon = data["lift"].get("icon") or ""
    if not icon.startswith("data:image/svg+xml;base64,") or base64.b64decode(icon.split(",", 1)[1]).decode() != own:
        problems.append("the elevator OBJECT does not carry its own icon")
    try:
        from playwright.sync_api import sync_playwright
        import tempfile
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
            path = os.path.join(folder, "scene.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(renderer.build_page(renderer.page_data(brief, 4.0, 4)))
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": renderer.WIDTH, "height": renderer.HEIGHT})
                renderer.open_scene(page, path)
                cards, wires = page.evaluate("[document.querySelectorAll('.card.icon').length, W.length]")
            finally:
                browser.close()
        if cards != 2 or wires != 1:
            problems.append(f"{cards} icon card(s) and {wires} wire(s) on the page, expected 2 and 1")
    except ImportError:
        cards = wires = "?"
    return report("3. agent010: icon cards with their own icon, wired by their side ports", problems,
                  [f"{cards} icon cards, {wires} wire on the page"])


def case_prompts():
    prompts = []

    def stub(prompt):
        prompts.append(prompt)
        raise RuntimeError("stop")
    original, agent004.llm_call = agent004.llm_call, stub
    try:
        agent004.ask_for_storyboard([{"scene_id": "1", "duration_sec": 8, "key_visual_moment": "", "narration_text": "Un ascenseur."}])
    except Exception:
        pass
    finally:
        agent004.llm_call = original
    problems = []
    prompt = prompts[0] if prompts else ""
    if "elevator, door-closed" not in prompt or "CART is a shopping cart, never an elevator" not in prompt:
        problems.append("agent004's prompt lacks the icon list or the CART warning")
    brief = scene([obj("lift", "box", 0, "Ascenseur")])
    briefs, corrections = {"1": brief}, []
    agent005.apply_patches(briefs, [{"op": "set_initial_state", "scene_id": "1", "entity_id": "lift", "key": "icon", "value": "elevator"},
                                    {"op": "set_initial_state", "scene_id": "1", "entity_id": "lift", "key": "icon", "value": "spaceship"}],
                           corrections)
    if briefs["1"]["entities"][0]["initial_state"]["icon"] != "elevator" or "dropped" not in corrections[-1]:
        problems.append(f"agent005 patches: {corrections}")
    return report("4. agent004 offers the icons; agent005 can change one by patch", problems, corrections)


results = [case_schema(), case_icons(), case_html(), case_prompts()]
sys.exit(0 if all(results) else 1)
