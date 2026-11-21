"""
Base of every Breeze component, and the components that are not electronics parts:

  BreezeComponent         abstract base: drawing, named ports (relative anchor vectors), states
  DynamicSVGComponent     a concrete object drawn from a Lucide SVG icon (tank, coins, bank...),
                          with one port on each side
  AxesGraphComponent      Manim Axes: a coordinate frame with a marked origin
  CurvePlotComponent      a function plotted on axes (its own, or an AXES_GRAPH entity's)
  VectorArrowComponent    a vector (force, velocity...) from the entity's position
  TexFormulaComponent     a formula: MathTex if LaTeX is installed, else readable Text

Imported by the render engine (app/render/breeze_engine.py), inside the Manim subprocess only.
"""

import re
import textwrap
from abc import ABC, abstractmethod

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, AnimationGroup, Arrow, Axes, Circle, Create, Dot, FadeIn, GrowArrow,
                   GrowFromCenter, MathTex,
                   SurroundingRectangle, SVGMobject, Text, VectorizedPoint, VGroup, VMobject, Write)
from manim.utils.rate_functions import ease_out_back

from app.render.asset_resolver import AssetResolver
from models.visual_brief_schema import check_curve, check_function_expression, is_parametric, parameter_range

FONT = "DejaVu Sans"
# Palette (shared by every component and the engine).
COLOR_BG = "#F8FAFC"          # clean off-white background
COLOR_CARD = "#FFFFFF"        # inside of drawn objects (battery cell, bulb, dial...)
COLOR_POSITIVE = "#10B981"    # emerald: revenue, active, switch closed
COLOR_NEGATIVE = "#EF4444"    # coral red: deficit, debt, forces, needles
COLOR_PRIMARY = "#3B82F6"     # electric blue: flow, electricity, highlight
COLOR_TEXT_MAIN = "#0F172A"
COLOR_TEXT_MUTED = "#64748B"

INK = COLOR_TEXT_MAIN         # outlines and text
MUTED = COLOR_TEXT_MUTED      # subtitles, wires
ACTIVE = COLOR_POSITIVE       # "active" / on
MAX_FORMULA_WIDTH = 5.5   # a formula is scaled down to fit this width (about 40% of the frame)
HIGHLIGHT = COLOR_PRIMARY

def warn(message):
    print(f"BREEZE_WARNING: {message}", flush=True)


LABEL_WRAP = 22           # characters per line: a long label becomes a short block, not a long strip


def label_text(text, size=26):
    return Text(textwrap.fill(text, LABEL_WRAP, break_long_words=False), font=FONT, font_size=size, color=INK)


# ---------------------------------------------------------------- components

class BreezeComponent(VGroup, ABC):
    """One entity on stage.

    Ports: self.port_vectors maps a port name to (offset from self.anchor, outward direction).
    self.anchor is an invisible point inside the group, so get_port() follows every move.
    self.solid is the drawing proper (not the glow or rays); self.obstacle = solid + label is what
    wires must go around.
    States: each subclass handles its own (lamp "on"/"off", switch "closed"/"open"...); every
    component also has "highlighted"/"normal" (blue frame) and "dimmed"/"undimmed" (white veil).
    """
    BOOLEAN_STATES = {}   # state key -> (state name if True, if False), e.g. {"on": ("on", "off")}
    LABEL_SIDES = (DOWN, LEFT, RIGHT, UP)   # tried in this order by BreezeSceneEngine.place_labels
    places_itself = False   # True: the registry must not move it (a curve sitting on its axes)
    OWN_LABEL = False       # True: build() draws initial_state.label itself (no generic label)
    BLOCKS_WIRES = True   # annotations point at things: wires may pass behind them

    def __init__(self, entity):
        super().__init__()
        self.entity_id = entity.id
        self.anchor = VectorizedPoint(np.zeros(3))
        self.port_vectors = {}
        self.body = self.build(entity.initial_state)
        self.solid = getattr(self, "solid", self.body)
        label = None if self.OWN_LABEL else entity.initial_state.get("label")
        self.label = label_text(str(label)).next_to(self.solid, self.LABEL_SIDES[0], buff=0.3) if label else VGroup()
        self.obstacle = VGroup(self.solid, self.label)
        self.halo = SurroundingRectangle(self.solid, color=HIGHLIGHT, buff=0.2, corner_radius=0.15,
                                         stroke_width=5).set_stroke(opacity=0)
        self.veil = SurroundingRectangle(VGroup(self.solid, self.label), buff=0.12,
                                         stroke_width=0).set_fill(COLOR_BG, opacity=0)
        self.add(self.anchor, self.body, self.label, self.halo, self.veil)

    def put_label(self, side):
        """Move the label to one side of the drawing; the dimming veil follows it."""
        self.label.next_to(self.solid, side, buff=0.3)
        self.refresh_veil()

    def refresh_veil(self):
        """Resize the dimming veil after the label moved."""
        self.veil.become(SurroundingRectangle(VGroup(self.solid, self.label), buff=0.12,
                                              stroke_width=0).set_fill(COLOR_BG, opacity=self.veil.get_fill_opacity()))

    @abstractmethod
    def build(self, initial_state):
        """Draw the component centered on the origin, already in its initial state; call
        define_port() for each port; return the drawing as a VGroup."""

    @abstractmethod
    def change_state(self, new_state, **kwargs):
        """Animation to one of this component's own states, or None if already there.
        Raises ValueError for a state this component does not have."""

    def define_port(self, name, offset, direction):
        self.port_vectors[name] = (np.array([*offset, 0.0]), np.array([*direction, 0.0]))

    def get_port(self, port_name: str) -> np.ndarray:
        """Absolute scene coordinates of a port."""
        if port_name not in self.port_vectors:
            raise KeyError(f"{self.entity_id} has no port {port_name!r} (ports: {sorted(self.port_vectors)})")
        return self.anchor.get_center() + self.port_vectors[port_name][0]

    def port_direction(self, port_name):
        return self.port_vectors[port_name][1]

    def spawn(self):
        return GrowFromCenter(self, rate_func=ease_out_back)

    def animate_state(self, new_state: str, **kwargs):
        """Animation to new_state, or None if nothing changes. Raises ValueError if unknown."""
        if new_state in ("highlighted", "normal"):
            return self.halo.animate.set_stroke(opacity=1 if new_state == "highlighted" else 0)
        if new_state in ("dimmed", "undimmed"):
            return self.veil.animate.set_fill(opacity=0.75 if new_state == "dimmed" else 0)
        return self.change_state(new_state, **kwargs)

    def states_from(self, state):
        """A set_state value -> [(state name, kwargs)]. Accepts "on" or {"on": true, "reading": 0.4}."""
        if isinstance(state, str):
            return [(state, {})]
        result = []
        for key, value in dict(state).items():
            if key == "label":
                continue
            if key in self.BOOLEAN_STATES and isinstance(value, bool):
                result.append((self.BOOLEAN_STATES[key][0 if value else 1], {}))
            elif key in ("highlighted", "dimmed") and isinstance(value, bool):
                result.append((key if value else {"highlighted": "normal", "dimmed": "undimmed"}[key], {}))
            else:
                result.append((key, {"value": value}))
        return result


def draw_then_fade_in(main, others):
    """Spawn animation of a concept: draw its main shape, fade in the rest (origin, labels)."""
    others = [m for m in others if m.get_family() and any(sm.has_points() for sm in m.get_family())]
    return AnimationGroup(main, *[FadeIn(m) for m in others])


# ---------------------------------------------------------------- SVG objects

ICON_COLORS = {"trending_up": COLOR_POSITIVE, "trending_down": COLOR_NEGATIVE}   # others: INK


class DynamicSVGComponent(BreezeComponent):
    """A concrete object drawn from a Lucide icon (see AssetResolver), as an ink outline.
    Ports: "left", "right", "top", "bottom", in the middle of each side.
    State "active" (green outline) / "idle". initial_state: label, size (height, default 1.4)."""
    BOOLEAN_STATES = {"active": ("active", "idle")}

    def __init__(self, entity, icon_name=None):
        self.icon_name = icon_name or entity.type.value.lower()
        super().__init__(entity)

    def build(self, initial_state):
        self.is_active = bool(initial_state.get("active", False))
        path, source = AssetResolver().resolve(self.icon_name)
        if source == "fallback":
            warn(f"{self.entity_id}: no icon found for {self.icon_name!r}, drawn as a question mark")
        self.base_color = ICON_COLORS.get(self.icon_name, INK)
        self.icon = SVGMobject(path).set_fill(opacity=0).set_stroke(ACTIVE if self.is_active else self.base_color, width=5)
        self.icon.scale_to_fit_height(float(initial_state.get("size", 1.4)))
        self.icon.move_to(np.zeros(3))
        half_w, half_h = self.icon.width / 2, self.icon.height / 2
        self.define_port("left", (-half_w, 0), (-1, 0))
        self.define_port("right", (half_w, 0), (1, 0))
        self.define_port("top", (0, half_h), (0, 1))
        self.define_port("bottom", (0, -half_h), (0, -1))
        return VGroup(self.icon)

    def change_state(self, new_state, **kwargs):
        if new_state not in ("active", "idle"):
            raise ValueError(f"a {self.icon_name} has no state {new_state!r} (active, idle)")
        if (new_state == "active") == self.is_active:
            return None
        self.is_active = new_state == "active"
        return self.icon.animate.set_stroke(ACTIVE if self.is_active else self.base_color)


# ---------------------------------------------------------------- maths / physics concepts

def number_pair(value, default):
    """[min, max] or [min, max, step] from the brief, else the default."""
    if isinstance(value, (list, tuple)) and len(value) in (2, 3) and all(isinstance(v, (int, float)) for v in value):
        low, high = float(value[0]), float(value[1])
        if high > low:
            step = float(value[2]) if len(value) == 3 and value[2] > 0 else max((high - low) / 10, 1e-3)
            return [low, high, step]
    return list(default)


class AxesGraphComponent(BreezeComponent):
    """A coordinate frame (Manim Axes) with arrow tips, a marked origin and Text axis labels.
    initial_state: x_range, y_range ([min, max] or [min, max, step]), x_label, y_label, width, height.
    No ports. CURVE_PLOT entities can be drawn on it (initial_state.axes = this entity's id)."""

    def build(self, initial_state):
        self.x_range = number_pair(initial_state.get("x_range"), (-5, 5, 1))
        self.y_range = number_pair(initial_state.get("y_range"), (-3, 3, 1))
        self.axes = Axes(x_range=self.x_range, y_range=self.y_range,
                         x_length=float(initial_state.get("width", 5.5)), y_length=float(initial_state.get("height", 3.4)),
                         axis_config={"color": INK, "stroke_width": 3, "include_tip": True, "tip_length": 0.2})
        self.axes.move_to(np.zeros(3))
        parts = [self.axes]
        if self.x_range[0] <= 0 <= self.x_range[1] and self.y_range[0] <= 0 <= self.y_range[1]:
            origin = self.axes.c2p(0, 0)
            parts += [Dot(origin, radius=0.06, color=INK),
                      Text("0", font=FONT, font_size=20, color=MUTED).next_to(origin, DOWN + LEFT, buff=0.08)]
        for key, end, side in (("x_label", self.axes.x_axis.get_end(), DOWN), ("y_label", self.axes.y_axis.get_end(), LEFT)):
            if initial_state.get(key):
                parts.append(Text(str(initial_state[key]), font=FONT, font_size=22, color=INK).next_to(end, side, buff=0.15))
        self.extras = parts[1:]
        return VGroup(*parts)

    def spawn(self):
        return draw_then_fade_in(Create(self.axes), self.extras)

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"axes have no state {new_state!r} (use highlighted / dimmed)")


def compile_function(text, variable="x"):
    """Safe expression of x (or t; checked by the schema) -> a Python function of it, evaluated with numpy."""
    check_function_expression(text, variable)
    code = compile(text.strip(), "<func>", "eval")
    namespace = {"__builtins__": {}, "np": np, "pi": np.pi, "e": np.e}
    namespace.update({name: getattr(np, name) for name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs")})
    return lambda value: eval(code, namespace, {variable: value})


PARAMETRIC_SAMPLES = 360      # a full turn: one point per degree
OWN_AXES_SIZE = (5.5, 3.4)    # width, height of a curve's own axes (scene units)


def parametric_points(state):
    """A parametric curve's samples: (ts, xs, ys), the undefined points dropped."""
    check_curve(state)
    x_of, y_of = compile_function(state["x_func"], "t"), compile_function(state["y_func"], "t")
    ts = np.linspace(*parameter_range(state), PARAMETRIC_SAMPLES)
    with np.errstate(all="ignore"):
        xs = np.broadcast_to(np.asarray(x_of(ts), dtype=float), ts.shape)
        ys = np.broadcast_to(np.asarray(y_of(ts), dtype=float), ts.shape)
    ok = np.isfinite(xs) & np.isfinite(ys)
    return ts[ok], xs[ok], ys[ok]


def equal_axes(xs, ys):
    """Own axes for a parametric curve: its box (20 % wider, holding the origin), one unit as long on
    x as on y so a circle stays round."""
    ranges = []
    for values in (xs, ys):
        low, high = min(float(values.min()), 0.0), max(float(values.max()), 0.0)
        pad = 0.2 * max(high - low, 1e-6)
        ranges.append((low - pad, high + pad))
    unit = min(OWN_AXES_SIZE[0] / (ranges[0][1] - ranges[0][0]), OWN_AXES_SIZE[1] / (ranges[1][1] - ranges[1][0]))
    step = lambda low, high: max(1.0, round((high - low) / 6))   # noqa: E731
    return Axes(x_range=[*ranges[0], step(*ranges[0])], y_range=[*ranges[1], step(*ranges[1])],
                x_length=(ranges[0][1] - ranges[0][0]) * unit, y_length=(ranges[1][1] - ranges[1][0]) * unit,
                axis_config={"color": INK, "stroke_width": 3, "include_tip": True, "tip_length": 0.2})


class CurvePlotComponent(BreezeComponent):
    """The graph of initial_state.func (e.g. "np.sin(x)", "0.5 * x**2"), drawn along itself on spawn;
    or a parametric curve (x_func, y_func of t from t_min to t_max: a circle, an orbit), on axes with
    equal scales when they are its own. With initial_state.axes = an AXES_GRAPH entity's id it is drawn
    on those axes (and placed with them); otherwise it brings its own small axes. initial_state: func
    or x_func + y_func (+ t_min, t_max), axes, x_range, color, label. No ports."""
    OWN_LABEL = True

    def __init__(self, entity, axes_component=None):
        self.axes_component = axes_component
        self.places_itself = axes_component is not None    # it sits on its axes, wherever they are
        super().__init__(entity)

    def build(self, initial_state):
        if is_parametric(initial_state):
            return self.build_parametric(initial_state)
        function = compile_function(initial_state["func"])
        if self.axes_component is not None:
            axes, frame = self.axes_component.axes, VGroup()
        else:
            axes = Axes(x_range=[-5, 5, 1], y_range=[-3, 3, 1], x_length=5.5, y_length=3.4,
                        axis_config={"color": INK, "stroke_width": 3, "include_tip": True, "tip_length": 0.2})
            axes.move_to(np.zeros(3))
            frame = VGroup(axes)
        x_min, x_max, _ = number_pair(initial_state.get("x_range"), axes.x_range)
        y_min, y_max = axes.y_range[0], axes.y_range[1]

        def bounded(x):
            # Stay inside the frame: no infinite or undefined points (1/x at 0, log of negatives...).
            with np.errstate(all="ignore"):
                y = function(x)
            return float(np.clip(np.nan_to_num(y, nan=0.0, posinf=y_max, neginf=y_min), y_min, y_max))

        self.curve = axes.plot(bounded, x_range=[x_min, x_max, (x_max - x_min) / 200], use_smoothing=False,
                               color=initial_state.get("color", HIGHLIGHT), stroke_width=5)
        return self.finish_build(initial_state, axes, frame)

    def build_parametric(self, initial_state):
        """(x(t), y(t)) through its samples, clipped to the axes; closed if it ends where it starts."""
        ts, xs, ys = parametric_points(initial_state)
        if len(ts) < 2:
            raise ValueError("the parametric curve has no defined point")
        if self.axes_component is not None:
            axes, frame = self.axes_component.axes, VGroup()
        else:
            axes = equal_axes(xs, ys)
            axes.move_to(np.zeros(3))
            frame = VGroup(axes)
        (x_min, x_max), (y_min, y_max) = axes.x_range[:2], axes.y_range[:2]
        points = [axes.coords_to_point(float(np.clip(x, x_min, x_max)), float(np.clip(y, y_min, y_max)))
                  for x, y in zip(xs, ys)]
        span = max(float(np.ptp(xs)), float(np.ptp(ys)), 1e-9)
        if len(ts) == PARAMETRIC_SAMPLES and np.hypot(xs[0] - xs[-1], ys[0] - ys[-1]) <= 1e-3 * span:
            points.append(points[0])    # ends where it starts (as agent010 judges it): closed exactly
        self.curve = VMobject(color=initial_state.get("color", HIGHLIGHT), stroke_width=5).set_points_as_corners(points)
        return self.finish_build(initial_state, axes, frame)

    def finish_build(self, initial_state, axes, frame):
        """The legend, then the group (shared by y = f(x) and parametric curves). Keeps the axes and the
        curve's initial_state: a vector anchored on the curve is placed with them (make_vector)."""
        self.plot_axes, self.curve_state = axes, initial_state
        self.frame = frame
        self.has_own_color = "color" in initial_state
        parts = [frame, self.curve]
        self.legend = None      # the label, as a legend entry: the engine stacks those of shared axes
        if initial_state.get("label"):
            self.legend_text = str(initial_state["label"])
            self.legend = Text(textwrap.fill(self.legend_text, 28), font=FONT, font_size=24, color=self.curve.get_color())
            if is_parametric(initial_state):     # a closed curve ends on its axis: the legend goes above it
                self.legend.next_to(self.curve, UP, buff=0.15)
            else:
                self.legend.next_to(self.curve.get_end(), UP + RIGHT, buff=0.1)
            parts.append(self.legend)
        group = VGroup(*parts)
        if self.axes_component is not None:
            # The anchor sits at the axes' anchor, so the whole component lines up with them.
            self.anchor.move_to(self.axes_component.anchor.get_center())
        return group

    def set_color(self, color):
        """Curve and legend in one colour (the engine gives curves sharing axes distinct colours)."""
        self.curve.set_stroke(color)
        if self.legend is not None:
            self.legend.set_color(color)

    def spawn(self):
        others = [m for m in self.body if m is not self.curve and m is not self.frame]
        main = AnimationGroup(Create(self.frame), Create(self.curve), lag_ratio=0.6) if len(self.frame) else Create(self.curve)
        return draw_then_fade_in(main, others)

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a curve has no state {new_state!r} (use highlighted / dimmed)")


VECTOR_DIRECTIONS = {"UP": UP, "DOWN": DOWN, "LEFT": LEFT, "RIGHT": RIGHT}


class VectorArrowComponent(BreezeComponent):
    """A vector starting at the entity's position. initial_state: direction ("UP", "DOWN", "LEFT",
    "RIGHT" or [dx, dy]), length (default 1.8), label (e.g. "Poids"), color. Grows on spawn. No ports."""
    OWN_LABEL = True

    def build(self, initial_state):
        direction = initial_state.get("direction", "RIGHT")
        if isinstance(direction, (list, tuple)) and len(direction) >= 2:
            vector = np.array([float(direction[0]), float(direction[1]), 0.0])
        else:
            vector = VECTOR_DIRECTIONS.get(str(direction).upper(), RIGHT).astype(float)
        norm = np.linalg.norm(vector)
        vector = vector / norm if norm > 1e-6 else RIGHT.astype(float)
        length = float(initial_state.get("length", 1.8))
        self.length = length
        self.arrow = Arrow(np.zeros(3), vector * length, buff=0, color=initial_state.get("color", COLOR_NEGATIVE),
                           stroke_width=8, max_tip_length_to_length_ratio=0.25)
        parts, self.caption = [self.arrow], None
        if initial_state.get("label"):
            side = np.array([-vector[1], vector[0], 0.0])        # beside the arrow, not on it
            self.caption = Text(str(initial_state["label"]), font=FONT, font_size=24, color=INK)
            parts.append(self.caption.next_to(self.arrow.get_center(), side, buff=0.2))
        return VGroup(*parts)

    def point_along(self, start, unit):
        """Redraw the arrow from `start` along the unit vector `unit` (a vector riding on a moving body);
        its label goes past the tip, in line with it, so it names this arrow whatever way it turns."""
        end = start + unit * self.length
        self.arrow.put_start_and_end_on(start, end)
        if self.caption is not None:
            reach = 0.15 + abs(unit[0]) * self.caption.width / 2 + abs(unit[1]) * self.caption.height / 2
            self.caption.move_to(end + unit * reach)
        self.anchor.move_to(start)

    def spawn(self):
        return draw_then_fade_in(GrowArrow(self.arrow), [m for m in self.body if m is not self.arrow])

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a vector has no state {new_state!r} (use highlighted / dimmed)")


class BodyComponent(BreezeComponent):
    """A body (satellite, planet, ball): a disc with a white rim, its label under it. initial_state:
    label, size (radius, default 0.25), color, anchor (on a curve: it sits there and travels along it
    with the action move_along, see the engine). No ports."""

    def build(self, initial_state):
        radius = float(initial_state.get("size", 0.25))
        self.disc = Circle(radius=radius, color="#FFFFFF", stroke_width=4).set_fill(initial_state.get("color", "#F59E0B"), 1)
        return VGroup(self.disc)

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a body has no state {new_state!r} (use highlighted / dimmed, or move_along)")


# Simple LaTeX -> readable Unicode, for when LaTeX is not installed.
LATEX_SYMBOLS = {"times": "×", "cdot": "·", "div": "÷", "pm": "±", "leq": "≤", "geq": "≥", "neq": "≠",
                 "approx": "≈", "infty": "∞", "rightarrow": "→", "to": "→", "Delta": "Δ", "delta": "δ",
                 "alpha": "α", "beta": "β", "gamma": "γ", "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π",
                 "rho": "ρ", "sigma": "σ", "omega": "ω", "Omega": "Ω", "sum": "Σ", "int": "∫"}
SUPERSCRIPTS = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")
SUBSCRIPTS = str.maketrans("0123456789+-", "₀₁₂₃₄₅₆₇₈₉₊₋")


def latex_to_text(latex):
    r"""Readable text for a LaTeX formula: "E=mc^2" -> "E=mc²", "\frac{U}{I}" -> "(U)/(I)",
    "\Delta x" -> "Δ x", "v_0" -> "v₀". Anything else keeps its letters, minus the backslashes."""
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", latex)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", text)
    text = re.sub(r"\\([a-zA-Z]+)", lambda m: LATEX_SYMBOLS.get(m.group(1), "\\" + m.group(1)), text)
    text = re.sub(r"\^\{([0-9+\-n]+)\}|\^([0-9+\-n])", lambda m: (m.group(1) or m.group(2)).translate(SUPERSCRIPTS), text)
    text = re.sub(r"_\{([0-9+\-]+)\}|_([0-9+\-])", lambda m: (m.group(1) or m.group(2)).translate(SUBSCRIPTS), text)
    text = re.sub(r"\\(text|mathrm|mathbf|left|right)\b", "", text)
    return re.sub(r"\\([a-zA-Z]+)", r"\1", text).replace("{", "").replace("}", "")


class TexFormulaComponent(BreezeComponent):
    """A formula. MathTex when LaTeX is installed; otherwise (no LaTeX, or a formula it cannot
    compile) a monospace Text with the LaTeX turned into readable Unicode. initial_state: latex,
    size (font size, default 48). Written on spawn. No ports."""
    latex_works = None        # learnt on the first formula: no point retrying a missing LaTeX

    def build(self, initial_state):
        latex = str(initial_state["latex"])
        size = float(initial_state.get("size", 48))
        self.formula = None
        if TexFormulaComponent.latex_works is not False:
            try:
                self.formula = MathTex(latex, color=INK, font_size=size)
                TexFormulaComponent.latex_works = True
            except Exception:          # LaTeX missing or the formula does not compile
                TexFormulaComponent.latex_works = TexFormulaComponent.latex_works or False
        if self.formula is None:
            self.formula = Text(latex_to_text(latex), font="Monospace", font_size=32, color=INK)
        if self.formula.width > MAX_FORMULA_WIDTH:     # a long formula shrinks instead of overflowing
            self.formula.scale_to_fit_width(MAX_FORMULA_WIDTH)
        return VGroup(self.formula)

    def spawn(self):
        return Write(self.formula)

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a formula has no state {new_state!r} (use highlighted / dimmed)")
