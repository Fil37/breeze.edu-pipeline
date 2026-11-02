"""
Where a vector anchored on a curve starts, and where it points, in the curve's own (graph) units:
for agent010, which then maps it to its pixels.

A VECTOR_ARROW with initial_state "anchor": {"curve": "<CURVE_PLOT id>", "t": <t>} (a parametric
curve) or {"curve": ..., "x": <x>} (y = f(x)) starts on that point of the curve. Its "direction" is
then a cardinal or [dx, dy] as usual (drawn as given), or one of ANCHORED_DIRECTIONS
(models/visual_brief_schema.py), worked out from the curve:
  TANGENT  along the curve, the way t (or x) grows: a velocity
  CENTER   towards the middle of the curve's drawing (an orbit's centre, where the planet is): gravity
  OUTWARD  the other way
The expressions are the schema-checked ones (safe: numbers, t or x, np. functions, no builtins).
"""

import numpy as np

from models.visual_brief_schema import check_curve, is_parametric, parameter_range

SAMPLES = 360
DEFAULT_X_RANGE = (-5.0, 5.0)


def evaluate(text, variable, values):
    """A schema-checked expression of `variable` at numpy `values`, with no builtins."""
    code = compile(text.strip(), "<func>", "eval")
    namespace = {"__builtins__": {}, "np": np, "pi": np.pi, "e": np.e}
    namespace.update({name: getattr(np, name) for name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs")})
    with np.errstate(all="ignore"):
        return np.broadcast_to(np.asarray(eval(code, namespace, {variable: values}), dtype=float), np.shape(values))


def curve_at(state, values, x_range=None):
    """Points (xs, ys) of a curve at parameter values (t for a parametric curve, x otherwise)."""
    values = np.asarray(values, dtype=float)
    if is_parametric(state):
        return evaluate(state["x_func"], "t", values), evaluate(state["y_func"], "t", values)
    return values, evaluate(state["func"], "x", values)


def domain(state, x_range=None):
    """The curve's parameter range: [t_min, t_max], or its x range."""
    if is_parametric(state):
        return parameter_range(state)
    own = state.get("x_range")
    if isinstance(own, (list, tuple)) and len(own) >= 2 and own[1] > own[0]:
        return float(own[0]), float(own[1])
    return tuple(x_range or DEFAULT_X_RANGE)


def curve_centre(curve_state, x_range=None):
    """The middle of the curve's drawing (graph units): where CENTER points (an orbit's centre)."""
    low, high = domain(curve_state, x_range)
    sx, sy = curve_at(curve_state, np.linspace(low, high, SAMPLES))
    ok = np.isfinite(sx) & np.isfinite(sy)
    return [float((sx[ok].min() + sx[ok].max()) / 2), float((sy[ok].min() + sy[ok].max()) / 2)]


def anchor_geometry(curve_state, anchor, direction, x_range=None):
    """(point, toward) in graph units: the anchor's point on the curve, and, for a direction from
    ANCHORED_DIRECTIONS, a second point a small step that way (None for a cardinal or [dx, dy]:
    the renderer draws those as given). Raises ValueError if the point is not defined."""
    check_curve(curve_state)
    value = float(anchor["t"] if is_parametric(curve_state) else anchor["x"])
    xs, ys = curve_at(curve_state, [value])
    point = np.array([xs[0], ys[0]])
    if not np.all(np.isfinite(point)):
        raise ValueError(f"the curve is not defined at {value}")
    name = str(direction).upper() if isinstance(direction, str) else None
    if name not in ("TANGENT", "CENTER", "OUTWARD"):
        return point.tolist(), None
    low, high = domain(curve_state, x_range)
    if name == "TANGENT":
        h = 1e-4 * (high - low)
        (x0, x1), (y0, y1) = curve_at(curve_state, [value - h, value + h])
        way = np.array([x1 - x0, y1 - y0])
    else:
        way = (np.array(curve_centre(curve_state, x_range)) - point) * (1 if name == "CENTER" else -1)
    norm = float(np.hypot(*way))
    if not np.isfinite(norm) or norm < 1e-12:
        raise ValueError(f"no {name.lower()} direction at {value}")
    sx, sy = curve_at(curve_state, np.linspace(low, high, 50))
    span = max(float(np.nanmax(sx) - np.nanmin(sx)), float(np.nanmax(sy) - np.nanmin(sy)), 1e-6)
    return point.tolist(), (point + way / norm * 1e-3 * span).tolist()
