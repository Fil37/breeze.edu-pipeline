"""
FREE_SVG — the ONLY place in breeze where an LLM's answer is drawing code (the trial of 2026-11-21, branch
essai/objets-libres: free drawing by the LLM, compared with the program-drawn CARD_SCENE). Everywhere else the
LLM gives data and the program draws; that rule still holds, and tests/test_free_objects.py checks that no other
piece takes markup.

  parse(svg_text) -> (tree, problems)

The LLM's SVG is never put in a page as markup. It is parsed here (stdlib XML, no DOCTYPE or entity accepted)
into a plain tree {"tag", "attrs", "text", "children"} keeping only:
  - drawing tags (ALLOWED_TAGS): no script, style, image, a, use, foreignObject, animate...;
  - drawing attributes (ALLOWED_ATTRS), each value checked by its kind: numbers, path data and point lists made of
    numbers and commands, colours (#RRGGBB, a few names, none), transforms of translate/scale/rotate with numbers;
    never url(), javascript, an event handler, an href;
  - texts as plain text (the page sets them with textContent);
  - the animation marks: data-step (1 to 8: revealed by set_state {"step": n}) and data-anim (ANIMATIONS).
Anything else is dropped and named in `problems` (sent back to the LLM). The page rebuilds the tree with
createElementNS / setAttribute / textContent: no innerHTML, no parsing in the page.
"""

import re
import xml.etree.ElementTree as ET

MAX_CHARS = 16_000
MAX_ELEMENTS = 400
MAX_TEXT = 80
VIEWBOX = (1600, 560)            # the size the LLM draws in (the piece's own size, app/layout_solver.py)

ALLOWED_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan"}
ANIMATIONS = ("pop", "slide-up", "slide-right", "draw", "pulse", "fade")

NUMBER = re.compile(r"^-?\d+(\.\d+)?(e-?\d+)?(px|%)?$")
PATH = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE\s,.\-]{1,6000}$")
POINTS = re.compile(r"^[0-9eE\s,.\-]{1,3000}$")
COLOUR = re.compile(r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|none|transparent|currentColor|white|black|"
                    r"red|green|blue|orange|yellow|gray|grey|purple|pink|brown|navy|teal|gold|silver)$")
TRANSFORM = re.compile(r"^(\s*(translate|scale|rotate)\(\s*-?\d+(\.\d+)?(\s*[, ]\s*-?\d+(\.\d+)?){0,2}\s*\)\s*)+$")
DASH = re.compile(r"^(none|[0-9.\s,]{1,60})$")
WORDS = {"stroke-linecap": ("butt", "round", "square"), "stroke-linejoin": ("miter", "round", "bevel"),
         "text-anchor": ("start", "middle", "end"), "dominant-baseline": ("auto", "middle", "central", "hanging"),
         "font-weight": ("normal", "bold", "400", "500", "600", "700", "800"), "fill-rule": ("nonzero", "evenodd"),
         "data-anim": ANIMATIONS}
ALLOWED_ATTRS = {
    "x": NUMBER, "y": NUMBER, "x1": NUMBER, "y1": NUMBER, "x2": NUMBER, "y2": NUMBER, "cx": NUMBER, "cy": NUMBER,
    "r": NUMBER, "rx": NUMBER, "ry": NUMBER, "width": NUMBER, "height": NUMBER, "dx": NUMBER, "dy": NUMBER,
    "stroke-width": NUMBER, "opacity": NUMBER, "fill-opacity": NUMBER, "stroke-opacity": NUMBER, "font-size": NUMBER,
    "d": PATH, "points": POINTS, "fill": COLOUR, "stroke": COLOUR, "transform": TRANSFORM, "stroke-dasharray": DASH,
    "data-step": re.compile(r"^[1-8]$"),
    "font-family": re.compile(r"^[A-Za-z][A-Za-z0-9 ,'\-]{0,60}$"),
    **{name: None for name in WORDS},          # checked against WORDS
}
FORBIDDEN = re.compile(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", re.IGNORECASE)


def _local(name):
    """'{http://www.w3.org/2000/svg}rect' -> 'rect'."""
    return name.rsplit("}", 1)[-1]


def _clean(node, problems, count):
    tag = _local(node.tag)
    if tag not in ALLOWED_TAGS:
        problems.append(f"<{tag}> is not allowed (shapes and text only: {', '.join(sorted(ALLOWED_TAGS))})")
        return None
    count[0] += 1
    if count[0] > MAX_ELEMENTS:
        if count[0] == MAX_ELEMENTS + 1:
            problems.append(f"more than {MAX_ELEMENTS} elements: the drawing was cut")
        return None
    attrs = {}
    for raw, value in node.attrib.items():
        name, value = _local(raw), str(value).strip()
        if tag == "svg" and name in ("viewBox", "width", "height", "version", "preserveAspectRatio"):
            continue                 # the root's size is the program's (VIEWBOX)
        rule = ALLOWED_ATTRS.get(name, False)
        if rule is False:
            problems.append(f'attribute "{name}" on <{tag}> is not allowed')
            continue
        ok = value in WORDS[name] if rule is None else bool(rule.match(value))
        if not ok:
            problems.append(f'<{tag} {name}="{value[:40]}">: not a plain value (numbers, #RRGGBB, path commands)')
            continue
        attrs[name] = value
    text = (node.text or "").strip()
    if text and tag not in ("text", "tspan"):
        text = ""
    out = {"tag": tag, "attrs": attrs, "text": text[:MAX_TEXT], "children": []}
    for child in node:
        kept = _clean(child, problems, count)
        if kept:
            out["children"].append(kept)
    return out


def parse(svg_text):
    """The LLM's SVG -> (tree or None, problems). The tree's root is the <svg>, its viewBox forced to the piece's
    size (VIEWBOX): the drawing is placed by the program, not by the LLM."""
    text = str(svg_text or "").strip()
    if not text.startswith("<svg"):
        return None, ["the drawing must be one <svg ...>...</svg>"]
    if len(text) > MAX_CHARS:
        return None, [f"the drawing is {len(text)} characters long: {MAX_CHARS} at most"]
    if FORBIDDEN.search(text):
        return None, ["no DOCTYPE, entity or stylesheet in the drawing"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return None, [f"not well-formed SVG: {exc}"]
    problems, count = [], [0]
    tree = _clean(root, problems, count)
    if tree is None or tree["tag"] != "svg":
        return None, problems or ["the drawing must be one <svg ...>...</svg>"]
    tree["attrs"] = {"viewBox": f"0 0 {VIEWBOX[0]} {VIEWBOX[1]}"}
    if count[0] < 2:
        problems.append("the drawing is empty: draw the thing with shapes")
        return None, problems
    return tree, problems


def steps(tree):
    """The data-step values used in a parsed tree (sorted)."""
    found = set()

    def walk(node):
        if node["attrs"].get("data-step"):
            found.add(int(node["attrs"]["data-step"]))
        for child in node["children"]:
            walk(child)
    if tree:
        walk(tree)
    return sorted(found)
