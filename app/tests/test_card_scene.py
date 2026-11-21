"""
Check CARD_SCENE, the piece for a thing no other piece shows (chosen on 2026-11-21 over FREE_SVG, the LLM's own
SVG drawing, by an A/B trial on the same scripts: orbit, water cycle, volcano).
  1. the rule holds: the page builds nothing from markup (no innerHTML, outerHTML, insertAdjacentHTML, DOMParser),
     and no LLM drawing code is left (no FREE_SVG type, no free_svg module)
  2. icons: an OBJECT icon (3D) or a Lucide name or a plain English word gives an icon; an unknown word is sent
     back by agent004 with close names; a card's 3D icon is drawn as its PNG
  3. CARD_SCENE: good states accepted, bad ones refused; drawn in its box with no conflict; cards in one by one;
     the highlighted words underlined, links drawn
  4. agent004: the card rule in the prompt, CARD_SCENE offered
Prints PASS or FAIL per case.

  .venv/bin/python app/tests/test_card_scene.py
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the project, above app/tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.render.icons import FALLBACK, find_icon, names, near        # noqa: E402
from app.agent import agent010_html_renderer as renderer             # noqa: E402
from app.models.visual_brief_schema import SceneVisualBrief, simple_piece_problem   # noqa: E402
from test_reactive import open_pages                                  # noqa: E402

def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def case_rule():
    problems = []
    with open(os.path.join(ROOT, "app", "agent", "agent010_html_renderer.py"), encoding="utf-8") as f:
        source = f.read()
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write"):
        if sink in source:
            problems.append(f"the renderer uses {sink}")
    from app.models.visual_brief_schema import ComponentType
    if "FREE_SVG" in ComponentType.__members__ or os.path.exists(os.path.join(ROOT, "app", "render", "free_svg.py")):
        problems.append("the LLM's drawing code (FREE_SVG) is still there")
    for path in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, ROOT)
        if rel.startswith((".venv", "app/tests", "app/archive", "app/instance")):
            continue
        with open(path, encoding="utf-8") as f:
            if re.search(r"\bfree_svg\b|\bFREE_SVG\b(?!.*#)", "\n".join(l for l in f.read().split("\n") if not l.lstrip().startswith("#"))):
                problems.append(f"{rel} still knows FREE_SVG")
    return report("1. no markup built in the page, no LLM drawing code left", problems)


def case_icons():
    problems = []
    if len(names()) < 1500:
        problems.append(f"{len(names())} icons")
    for query, want in (("orbit", "orbit"), ("moon", "moon"), ("cloud-rain", "cloud-rain"), ("bank", "landmark")):
        if find_icon(query) != want:
            problems.append(f"{query} -> {find_icon(query)}, wanted {want}")
    if find_icon("xyzzy") != FALLBACK or not near("rain"):
        problems.append("an unknown word not sent to the fallback, or no suggestion")
    from app.agent.agent004_visualbriefgenerator import card_problems
    brief = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
        "entities": [{"id": "c", "type": "CARD_SCENE", "position": [0, 0, 0], "initial_state": {
            "cards": [{"icon": "volcanoid", "title": "Le volcan"}]}}]})
    if not any('no icon "volcanoid"' in p for p in card_problems(["1"], {"1": brief})):
        problems.append("an unknown icon not sent back")
    brief.entities[0].initial_state["cards"][0]["icon"] = "volcano"           # an OBJECT icon, only in 3D
    if card_problems(["1"], {"1": brief}):
        problems.append("a 3D OBJECT icon sent back")
    uri = renderer.page_data(cards_brief(), 6, None)["entities"][0]["simple"]["cards"][0]["icon_uri"]
    if not uri.startswith("data:image/png;base64,"):
        problems.append("the card's earth is not drawn in relief")
    return report("2. icons: 3D, Lucide or a word; an unknown one sent back with close names", problems)


def cards_brief(links=True):
    state = {"cards": [{"icon": "earth", "title": "La Terre", "text": "attire la Lune vers son centre", "tone": "blue"},
                       {"icon": "moon", "title": "La Lune", "text": "file de côté et tombe sans cesse", "tone": "violet"},
                       {"icon": "orbit", "title": "L'orbite", "text": "elle tombe mais rate la Terre", "tone": "green"}],
             "highlight": "rate la Terre"}
    if links:
        state["links"] = [{"from": 0, "to": 1, "label": "attire"}, {"from": 0, "to": 2, "label": "donc"}]
    return {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [],
            "entities": [{"id": "c", "type": "CARD_SCENE", "position": [0, -0.3, 0], "initial_state": state}],
            "actions": [{"at": 1 + i, "action": "set_state", "target": "c", "state": {"step": i + 1}} for i in range(3)]}


def case_cards():
    problems = []
    good = cards_brief()["entities"][0]["initial_state"]
    if simple_piece_problem("CARD_SCENE", good):
        problems.append(f"good refused: {simple_piece_problem('CARD_SCENE', good)}")
    for bad in ({"cards": []}, {"cards": [{"icon": "x", "title": "y" * 40}]}, {"cards": [{"icon": "x", "title": "y", "tone": "pink"}]},
                {**good, "links": [{"from": 0, "to": 0}]}, {**good, "highlight": "absent"}):
        if not simple_piece_problem("CARD_SCENE", bad):
            problems.append(f"bad accepted: {str(bad)[:60]}")
    found = open_pages({"c": renderer.page_data(cards_brief(), 6, None)}, """() => {
      const p = E.c.data.simpleParts, op = () => p.cards.map(c => +c.g.getAttribute("opacity"));
      const at = E.c.states.filter(st => st.state && Number.isInteger(st.state.step)).map(st => st.at);
      window.seek(at[0] + 0.8); const early = op(); window.seek(5.5);
      return {early, late: op(), conflicts: window.layoutConflicts, marks: p.cards[2].marks.map(m => +m.getAttribute("width")),
              links: p.links.map(g => +g.getAttribute("opacity"))}; }""")["c"]
    if not (found["early"][0] > 0.9 and found["early"][2] == 0 and min(found["late"]) > 0.99):
        problems.append(f"cards not in one by one: {found['early']} {found['late']}")
    if found["conflicts"]:
        problems.append(f"conflicts: {found['conflicts']}")
    if len(found["marks"]) != 2 or min(found["marks"]) <= 0:
        problems.append(f"the highlight over two lines not drawn: {found['marks']}")
    if min(found["links"]) < 0.99:
        problems.append(f"links not drawn: {found['links']}")
    return report("3. CARD_SCENE: checked, drawn in its box, cards one by one, highlight and links", problems)


def case_prompt():
    from app.agent import agent004_visualbriefgenerator as a
    problems = []
    if "ONE CARD_SCENE" not in a.CARD_RULE or "{card_rule}" not in a.PROMPT:
        problems.append("the card rule is not in the prompt")
    if not any(line.startswith("  * CARD_SCENE:") for line in a.COMPONENTS_FOR_PROMPT.split("\n")):
        problems.append("CARD_SCENE not offered")
    return report("4. agent004: the card rule in the prompt, CARD_SCENE offered", problems)


if __name__ == "__main__":
    results = [case_rule(), case_icons(), case_cards(), case_prompt()]
    sys.exit(0 if all(results) else 1)
