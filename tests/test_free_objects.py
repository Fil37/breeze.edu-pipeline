"""
Check the trial of 2026-11-21 (branch essai/objets-libres): two fallbacks for a thing no piece shows, compared on
the same scripts. CARD_SCENE (the program draws cards from the LLM's data) and FREE_SVG (the LLM's own drawing,
the ONLY code it may give in breeze).
  1. the SVG checker keeps shapes, text and the animation marks; drops scripts, handlers, links, images, styles,
     url(), foreignObject; refuses a DOCTYPE or an entity, a drawing too long or empty; forces the box's size
  2. the rule still holds everywhere else: the page builds nothing from markup (no innerHTML, outerHTML,
     insertAdjacentHTML, DOMParser in the renderer); only the schema, the renderer and agent004 know free_svg
  3. icons: a Lucide name or a plain English word gives an icon; an unknown word gives circle-help, and agent004
     sends it back with the close names
  4. CARD_SCENE: good states accepted, bad ones refused; drawn in its box with no conflict; cards in one by one;
     the highlighted words underlined, links drawn
  5. FREE_SVG: drawn from the checked tree; each data-step part in on its step; "draw" traces the outline
  6. agent004 offers ONE fallback (LBREEZE_FALLBACK): the other is hidden from the prompt and refused if used
Prints PASS or FAIL per case.

  .venv/bin/python tests/test_free_objects.py
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project, above tests/
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.render import free_svg                                       # noqa: E402
from app.render.icons import FALLBACK, find_icon, names, near        # noqa: E402
from app.agent import agent010_html_renderer as renderer             # noqa: E402
from models.visual_brief_schema import SceneVisualBrief, simple_piece_problem   # noqa: E402
from test_reactive import open_pages                                  # noqa: E402

BAD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)">
<script>alert(1)</script><image href="http://x/y.png"/><a href="javascript:x"><rect x="1" y="1" width="5" height="5"/></a>
<rect x="1" y="1" width="5" height="5" fill="url(#g)" style="fill:red" onclick="x()"/>
<g data-step="2" data-anim="pop"><circle cx="5" cy="5" r="2" fill="#1E40AF"/><text x="1" y="9">Terre</text></g>
<foreignObject><div>x</div></foreignObject></svg>"""
GOOD = """<svg viewBox="0 0 1600 560">
<g data-step="1" data-anim="pop"><circle cx="800" cy="300" r="120" fill="#2563EB"/><text x="800" y="310" font-size="34">Terre</text></g>
<g data-step="2" data-anim="draw"><ellipse cx="800" cy="300" rx="420" ry="220" fill="none" stroke="#7C3AED" stroke-width="5"/></g>
</svg>"""


def report(label, problems):
    print(f'{"FAIL" if problems else "PASS"}  {label}' + "".join(f"\n      problem: {p}" for p in problems))
    return not problems


def flat(tree):
    return [tree] + [n for child in tree["children"] for n in flat(child)]


def case_checker():
    problems = []
    tree, found = free_svg.parse(BAD)
    nodes = flat(tree)
    if {n["tag"] for n in nodes} - free_svg.ALLOWED_TAGS:
        problems.append("a tag outside the list kept")
    kept = " ".join(f"{k}={v}" for n in nodes for k, v in n["attrs"].items())
    for bad in ("onload", "onclick", "style", "url(", "href", "javascript"):
        if bad in kept:
            problems.append(f"{bad} kept")
    if not any(n["attrs"].get("data-step") == "2" for n in nodes) or not any(n["text"] == "Terre" for n in nodes):
        problems.append("the animation mark or the text lost")
    if tree["attrs"] != {"viewBox": "0 0 1600 560"} or len(found) < 6:
        problems.append(f"box not forced or problems not named: {tree['attrs']} {len(found)}")
    for text, what in (('<!DOCTYPE x [<!ENTITY a "b">]><svg/>', "an entity"), ("x" * 10, "not svg"),
                       ("<svg>" + "<rect/>" * 3000 + "</svg>", "too long"), ("<svg></svg>", "empty")):
        if free_svg.parse(text)[0] is not None:
            problems.append(f"{what} accepted")
    if free_svg.parse(GOOD)[1] or free_svg.steps(free_svg.parse(GOOD)[0]) != [1, 2]:
        problems.append("a clean drawing reported")
    return report("1. the SVG checker: shapes, text and marks kept; everything active dropped", problems)


def case_rule():
    problems = []
    with open(os.path.join(ROOT, "app", "agent", "agent010_html_renderer.py"), encoding="utf-8") as f:
        source = f.read()
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write"):
        if sink in source:
            problems.append(f"the renderer uses {sink}")
    allowed = {os.path.join("models", "visual_brief_schema.py"), os.path.join("app", "agent", "agent010_html_renderer.py"),
               os.path.join("app", "agent", "agent004_visualbriefgenerator.py"), os.path.join("app", "render", "free_svg.py")}
    for path in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, ROOT)
        if rel.startswith((".venv", "tests", "archive")) or rel in allowed:
            continue
        with open(path, encoding="utf-8") as f:
            if re.search(r"\bfree_svg\b", f.read()):
                problems.append(f"{rel} uses free_svg: the exception must stay in one place")
    return report("2. the rule holds elsewhere: no markup built in the page, free_svg in one place", problems)


def case_icons():
    problems = []
    if len(names()) < 1500:
        problems.append(f"{len(names())} icons")
    for query, want in (("orbit", "orbit"), ("moon", "moon"), ("cloud-rain", "cloud-rain"), ("bank", "landmark")):
        if find_icon(query) != want:
            problems.append(f"{query} -> {find_icon(query)}, wanted {want}")
    if find_icon("xyzzy") != FALLBACK or not near("rain"):
        problems.append("an unknown word not sent to the fallback, or no suggestion")
    from app.agent.agent004_visualbriefgenerator import fallback_problems
    brief = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [], "actions": [],
        "entities": [{"id": "c", "type": "CARD_SCENE", "position": [0, 0, 0], "initial_state": {
            "cards": [{"icon": "volcanoid", "title": "Le volcan"}]}}]})
    if not any("no Lucide icon" in p for p in fallback_problems(["1"], {"1": brief}, "cards")):
        problems.append("an unknown icon not sent back")
    return report("3. icons by name or word; an unknown one sent back with close names", problems)


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
    return report("4. CARD_SCENE: checked, drawn in its box, cards one by one, highlight and links", problems)


def case_free():
    problems = []
    brief = {"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [],
             "entities": [{"id": "f", "type": "FREE_SVG", "position": [0, -0.3, 0], "initial_state": {"svg": GOOD}}],
             "actions": [{"at": 1, "action": "set_state", "target": "f", "state": {"step": 1}},
                         {"at": 3, "action": "set_state", "target": "f", "state": {"step": 2}}]}
    if simple_piece_problem("FREE_SVG", brief["entities"][0]["initial_state"]):
        problems.append("a clean drawing refused")
    if not simple_piece_problem("FREE_SVG", {"svg": BAD}):
        problems.append("a drawing with a script accepted (it must be sent back, even though it would be cleaned)")
    found = open_pages({"f": renderer.page_data(brief, 6, None)}, """() => {
      const steps = E.f.data.simpleParts.steps, op = () => steps.map(s => +s.g.getAttribute("opacity"));
      const at = E.f.states.filter(st => st.state && Number.isInteger(st.state.step)).map(st => st.at);
      window.seek(at[0] + 0.8); const mid = op();
      window.seek(at[1] + 0.3); const drawing = +steps[1].g.querySelector("ellipse").getAttribute("stroke-dashoffset");
      window.seek(5.5);
      return {mid, late: op(), drawing, scripts: document.querySelectorAll("script").length,
              conflicts: window.layoutConflicts, texts: [...E.f.shape.querySelectorAll("text")].map(t => t.textContent)}; }""")["f"]
    if not (found["mid"][0] > 0.99 and found["mid"][1] == 0 and min(found["late"]) > 0.99):
        problems.append(f"parts not on their steps: {found['mid']} {found['late']}")
    if not 0 < found["drawing"] < 1:
        problems.append(f"the outline not traced: {found['drawing']}")
    if found["texts"] != ["Terre"] or found["conflicts"]:
        problems.append(f"texts or conflicts: {found['texts']} {found['conflicts']}")
    return report("5. FREE_SVG: rebuilt from the checked tree, parts on their steps, outlines traced", problems)


def case_switch():
    from app.agent import agent004_visualbriefgenerator as a
    problems, saved = [], os.environ.get(a.FALLBACK_ENV)
    try:
        for mode, shown, hidden in (("cards", "CARD_SCENE", "FREE_SVG"), ("svg", "FREE_SVG", "CARD_SCENE")):
            os.environ[a.FALLBACK_ENV] = mode
            prompt = a.components_for_prompt() + a.fallback_rule()
            if shown not in prompt or hidden in prompt:
                problems.append(f"mode {mode}: the prompt shows {hidden} or not {shown}")
            brief = SceneVisualBrief.model_validate({"scene_id": "1", "text_overlay": {"title": "x"}, "connections": [],
                "actions": [], "entities": [{"id": "h", "type": hidden, "position": [0, 0, 0], "initial_state":
                    {"svg": GOOD} if hidden == "FREE_SVG" else {"cards": [{"icon": "moon", "title": "Lune"}]}}]})
            if not any("not offered here" in p for p in a.fallback_problems(["1"], {"1": brief})):
                problems.append(f"mode {mode}: {hidden} not refused")
        os.environ[a.FALLBACK_ENV] = "nonsense"
        if a.fallback_mode() != "cards":
            problems.append("an unknown mode not back to cards")
    finally:
        if saved is None:
            os.environ.pop(a.FALLBACK_ENV, None)
        else:
            os.environ[a.FALLBACK_ENV] = saved
    return report("6. one fallback offered at a time; the other hidden and refused", problems)


if __name__ == "__main__":
    results = [case_checker(), case_rule(), case_icons(), case_cards(), case_free(), case_switch()]
    sys.exit(0 if all(results) else 1)
