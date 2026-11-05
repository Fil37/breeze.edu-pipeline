"""
A circuit laid out on a breadboard (BREADBOARD, models/visual_brief_schema.py), as someone building it
would: the op-amp (an 8-pin DIP, LM358 pinout) straddling the middle gap, each other part plugged so
that its leads share the column strips of what they join (5 holes a strip), a jumper where a net
still has to reach another strip, and one from every strip of a supply net to the board's red (+) or
blue (0 V) rail. Nothing here comes from the LLM but the parts, their nets and their labels; every
coordinate is computed. breadboard_data(state) gives agent010 the drawing in pixels.
"""

import re

from models.visual_brief_schema import BB_KINDS, BB_LABEL_MAX, BB_RAIL

COLS = 30
PITCH = 29
HOLE_X0 = 170                       # column 0's x
ROW_Y = [140 + 28 * r for r in range(5)] + [292 + 28 * r for r in range(5)]   # rows a..e, then f..j
RAIL_Y = {("top", "+"): 80, ("top", "-"): 104, ("bottom", "-"): 440, ("bottom", "+"): 464}
BOARD = {"x": 140, "y": 60, "w": 900, "h": 424}
WIDTH, HEIGHT = 1080, 560
PART_ROWS = {"top": [1, 2, 3, 0, 4], "bottom": [8, 7, 6, 9, 5]}     # where a part's lead goes first (b c d a e, i h g j f)
JUMPER_ROWS = {"top": [3, 0, 4, 2, 1], "bottom": [6, 9, 5, 7, 8]}
OPAMP_COL = 13
OPAMP_PINS = {"out": (0, 5), "in_minus": (1, 5), "in_plus": (2, 5), "gnd": (3, 5), "vcc": (0, 4)}   # (column offset, row)
MIN_SPAN = {"RESISTOR": 3, "HEATER": 4}   # columns between a two-lead part's leads (its body between them)
BODY_ROWS = {"POTENTIOMETER": 2, "MOSFET": 3, "LED": 1, "HEATER": 1, "THERMISTOR": 1}   # rows its body rises over
LABEL_TIERS = {"top": [46, 24, 2], "bottom": [512, 534, 556]}
SIGNAL_COLORS = ("#FACC15", "#22C55E", "#F97316", "#A855F7", "#06B6D4", "#EC4899")
BAND_COLORS = ("#111111", "#7C4A1E", "#DC2626", "#F97316", "#FACC15", "#16A34A", "#2563EB", "#7C3AED", "#6B7280", "#F9FAFB")
VALUE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([kKM]?)\s*(?:Ω|ohms?)")


def half_of(row):
    return "top" if row < 5 else "bottom"


def x_of(col):
    return HOLE_X0 + col * PITCH


def bands(label):
    """A resistor's four colour bands from its value in its label ("R1 10 kΩ": brown, black, orange,
    gold), or None when it has no value."""
    m = VALUE.search(str(label or ""))
    if not m:
        return None
    ohms = float(m.group(1).replace(",", ".")) * {"": 1, "k": 1e3, "K": 1e3, "M": 1e6}[m.group(2)]
    if ohms < 10:
        return None
    digits = f"{ohms:.3e}"                       # "1.000e+04"
    first, second, power = int(digits[0]), int(digits[2]), int(digits.split("e")[1]) - 1
    return [BAND_COLORS[first], BAND_COLORS[second], BAND_COLORS[max(0, min(9, power))], "#D4A72C"]


def breadboard_data(state):
    parts = state["parts"]
    net_of, rail_of, nets = {}, {}, []
    for i, net in enumerate(state.get("nets") or []):
        rail = net[0] if BB_RAIL.fullmatch(net[0]) else None
        leads = net[1:] if rail else net
        name = rail or f"n{i}"
        nets.append(name)
        if rail:
            rail_of[name] = "+" if rail.startswith("+") else "-"
        for lead in leads:
            net_of[lead] = name
    strips, holes, placed = {}, {}, {}       # (half, col) -> net; (col, row) -> taken; part id -> [(lead, col, row)]
    spans = {}                               # row -> [(first col, last col)] of the parts lying along it
    covered = set()                          # (col, row) under a part's body: no other part there

    def footprint(kind, cols, row):
        rise, wide = BODY_ROWS.get(kind, 0), len(cols) == 3
        rows = range(row - rise, row + 1)
        span = range(cols[0] - 1, cols[-1] + 2) if wide else range(cols[0], cols[-1] + 1)
        return {(c, r) for c in span for r in rows}

    def take(col, row):
        holes[(col, row)] = True
        return col, row

    def free_row(half, col, order=None):
        return next((r for r in (order or PART_ROWS[half]) if (col, r) not in holes), None)

    def row_for(half, cols, kind):
        """A row where the part lies along free holes, its body inside its half over no other part, or None."""
        low = 0 if half == "top" else 5
        for r in PART_ROWS[half]:
            cells = footprint(kind, cols, r)
            grown = cells | {(c, rr + d) for c, rr in cells for d in (-1, 1)}      # a free row around each body
            if all((c, r) not in holes for c in cols) and min(rr for _, rr in cells) >= low and not grown & covered \
                    and all(cols[-1] < a - 1 or cols[0] > b + 1 for a, b in spans.get(r, [])):
                return r
        return None

    def fits(half, col, net):
        if not 0 <= col < COLS or free_row(half, col) is None:
            return False
        return strips.get((half, col)) in (None, net)

    # the op-amp first, across the gap in the middle
    for p in parts:
        if p["kind"] == "OPAMP" and "OPAMP" not in placed.values():
            spots = []
            for lead, (dc, row) in OPAMP_PINS.items():
                col = OPAMP_COL + dc
                spots.append((lead, *take(col, row)))
                strips[(half_of(row), col)] = net_of.get(f"{p['id']}.{lead}", f"{p['id']}.{lead}")
            for dc, row in ((1, 4), (2, 4), (3, 4)):        # pins 7, 6, 5: not used, but in the board
                take(OPAMP_COL + dc, row)
                strips[("top", OPAMP_COL + dc)] = f"{p['id']}.unused{dc}"
            covered.update((OPAMP_COL + dc, r) for dc in range(-1, 5) for r in (4, 5))
            placed[p["id"]] = spots
    cursor = 0
    for p in parts:
        if p["id"] in placed:
            continue
        leads = BB_KINDS[p["kind"]]
        nets_here = [net_of.get(f"{p['id']}.{lead}", f"{p['id']}.{lead}") for lead in leads]
        best = None
        for half in ("top", "bottom"):
            if len(leads) == 3:
                options = [(k, k + 1, k + 2) for k in range(COLS - 2)]
            else:
                options = [(a, a + d) for a in range(COLS) for d in range(MIN_SPAN.get(p["kind"], 2), 8) if a + d < COLS]
            for cols in options:
                if not all(fits(half, c, n) for c, n in zip(cols, nets_here)) or row_for(half, cols, p["kind"]) is None:
                    continue
                reuse = sum(strips.get((half, c)) == n for c, n in zip(cols, nets_here))
                score = 10 * reuse - (cols[-1] - cols[0]) - 0.4 * abs(cols[0] - cursor)
                if best is None or score > best[0]:
                    best = (score, half, cols)
        if best is None:
            raise ValueError(f"no room on the breadboard for {p['id']}")
        _, half, cols = best
        row = row_for(half, cols, p["kind"])
        spans.setdefault(row, []).append((cols[0], cols[-1]))
        covered.update(footprint(p["kind"], cols, row))
        spots = []
        for lead, c, n in zip(leads, cols, nets_here):
            spots.append((lead, *take(c, row)))
            strips[(half, c)] = n
        placed[p["id"]] = spots
        cursor = cols[-1] + 2
    order = {p["id"]: i + 1 for i, p in enumerate(parts)}
    first = {}                               # strip -> the step its first lead comes in
    for pid, spots in placed.items():
        for _, c, r in spots:
            key = (half_of(r), c)
            first[key] = min(first.get(key, 99), order[pid])
    # jumpers: a net's strips one after the other; a supply net's strips each to its rail
    jumpers, colors = [], {}
    for net in nets + sorted({n for n in strips.values() if n not in nets}):
        mine = sorted(k for k, n in strips.items() if n == net and k in first)
        if net in rail_of:
            for half, c in mine:
                r = free_row(half, c, JUMPER_ROWS[half][::-1] if half == "top" else JUMPER_ROWS[half])
                if r is None:
                    continue
                take(c, r)
                jumpers.append({"x1": x_of(c), "y1": ROW_Y[r], "x2": x_of(c), "y2": RAIL_Y[(half, rail_of[net])],
                                "color": "#EF4444" if rail_of[net] == "+" else "#1E3A8A", "step": first[(half, c)]})
            continue
        color = colors.setdefault(net, SIGNAL_COLORS[len(colors) % len(SIGNAL_COLORS)])
        for (h1, c1), (h2, c2) in zip(mine, mine[1:]):
            r1, r2 = free_row(h1, c1, JUMPER_ROWS[h1]), free_row(h2, c2, JUMPER_ROWS[h2])
            if r1 is None or r2 is None:
                continue
            take(c1, r1), take(c2, r2)
            jumpers.append({"x1": x_of(c1), "y1": ROW_Y[r1], "x2": x_of(c2), "y2": ROW_Y[r2], "color": color,
                            "step": max(first[(h1, c1)], first[(h2, c2)])})
    used_bottom = any(h == "bottom" for (h, _), n in strips.items() if n in rail_of)
    drawn, tiers = [], {"top": [], "bottom": []}
    short = lambda text: text if len(text) <= BB_LABEL_MAX else text[:BB_LABEL_MAX - 1].rstrip() + "…"
    for p in sorted(parts, key=lambda p: sum(x_of(c) for _, c, _ in placed[p["id"]]) / len(placed[p["id"]])):
        spots = placed[p["id"]]
        half, x = half_of(spots[0][2]), sum(x_of(c) for _, c, _ in spots) / len(spots)
        width = 9 * len(short(str(p.get("label") or p["id"]))) + 14
        tier = next((k for k in range(len(LABEL_TIERS[half])) if all(abs(x - x2) >= (width + w2) / 2
                     for x2, w2, k2 in tiers[half] if k2 == k)), len(LABEL_TIERS[half]) - 1)
        tiers[half].append((x, width, tier))
        drawn.append({"label_y": LABEL_TIERS[half][tier], "id": p["id"], "kind": p["kind"], "label": short(str(p.get("label") or p["id"])), "step": order[p["id"]],
                      "half": half_of(spots[0][2]), "bands": bands(p.get("label")) if p["kind"] == "RESISTOR" else None,
                      "leads": [{"name": lead, "x": x_of(c), "y": ROW_Y[r]} for lead, c, r in spots]})
    return {"width": WIDTH, "height": HEIGHT, "board": BOARD, "cols": COLS, "pitch": PITCH, "x0": HOLE_X0, "rows": ROW_Y,
            "rails": {f"{h},{sign}": y for (h, sign), y in RAIL_Y.items()}, "parts": drawn, "jumpers": jumpers, "bridge": used_bottom,
            "supply": next((n for n in nets if n in rail_of and rail_of[n] == "+"), "+12 V")}
