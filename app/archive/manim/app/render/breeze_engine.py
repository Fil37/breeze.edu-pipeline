"""
Breeze deterministic render engine. Runs INSIDE the Manim subprocess started by agent006.

Plays one SceneVisualBrief (models/visual_brief_schema.py), timed to the voice-over:
  ComponentRegistry  ComponentType -> component factory. Electronics and mechanics parts are defined
                     here; BreezeComponent, the SVG objects (DynamicSVGComponent + AssetResolver) and
                     the maths/physics concepts (axes, curves, vectors, formulas) in
                     app/render/components/base.py
  FlowWire           a right-angle wire between two ports (BACKGROUND layer)
  start_flow         12 electrons run around the closed loop the path's wires make (FLOW layer)
  BreezeSceneEngine  setup_scene() places components and routes wires; execute_actions() plays the
                     actions strictly one after the other, so nothing animates on top of anything

Not inside agent006 because importing manim takes ~2.5 s and prints SoX warnings: only this
subprocess needs it. Warnings go to stdout as "BREEZE_WARNING: ..." lines; agent006 collects them.
No LaTeX anywhere: every text is a manim Text (Pango).

Actions (free dicts in the schema; the format agent004's prompt asks for):
  {"at": 1.0, "action": "spawn", "target": "battery_1"}
  {"at": 4.0, "action": "set_state", "target": "lamp_1", "state": {"on": true}}   (or "on")
  {"at": 3.0, "action": "start_flow", "path": ["battery_1", "switch_1", "lamp_1", "battery_1"], "current": 0.8}
       ("current" is optional: the amps the ammeters on the path show, DEFAULT_FLOW_CURRENT if absent)
  {"at": 8.0, "action": "stop_flow", "path": [...]}   (no path: stops every flow)
  {"at": 9.0, "action": "fade_out", "target": "lamp_1"}
"at" is in seconds of the script's planned scene length; the engine rescales it to the voice.
Entities that no action spawns appear at the start. A wire is drawn as soon as both its ends are
on screen.
"""

import heapq
import json
import textwrap

import numpy as np
from manim import (BOLD, DOWN, LEFT, PI, RIGHT, UP, AnimationGroup, Arc, Arrow, Circle, Create, DashedVMobject, Dot,
                   FadeIn, FadeOut, FadeTransform, Flash, Line, MovingCameraScene, Polygon, Rectangle, Rotate,
                   RoundedRectangle, Succession, SurroundingRectangle, Text, Transform, ValueTracker, VGroup, VMobject,
                   Write, always_redraw, config)
from manim.utils.rate_functions import ease_in_out_sine, smooth

from app.render.components.base import (ACTIVE, COLOR_BG, COLOR_CARD, COLOR_NEGATIVE, COLOR_POSITIVE, COLOR_PRIMARY,
                                        FONT, HIGHLIGHT, INK, MUTED, AxesGraphComponent, BreezeComponent,
                                        BodyComponent, CurvePlotComponent, DynamicSVGComponent, TexFormulaComponent,
                                        VectorArrowComponent, label_text, warn)
from app.curve_math import anchor_geometry
from models.visual_brief_schema import DEFAULT_OBJECT_ICON, SVG_TYPES, ComponentType, Layer, SceneVisualBrief, split_pin, unit_direction

ELECTRONS = 12            # particles per flow
ELECTRON_SPEED = 1.5      # scene units per second along the loop
ELECTRON_COLOR = COLOR_PRIMARY   # electric blue
LAMP_ON = "#FCC419"
FILAMENT_ON = "#E8590C"

LAYER_Z = {Layer.BACKGROUND: 0, Layer.CIRCUIT: 1, Layer.FLOW: 2, Layer.OVERLAY: 3, Layer.HUD: 4}

# Semantic positions -> scene coordinates. The TOP row sits under the text overlay (HUD, y > 2.2).
COLUMNS = {"LEFT": -4.6, "CENTER": 0.0, "RIGHT": 4.6}
ROWS = {"TOP": 1.45, "MIDDLE": -0.45, "BOTTOM": -2.3}

# Everything (components, labels, wires) stays inside the frame minus these margins, and below the
# text overlay (HUD).
SIDE_MARGIN = 0.8
BOTTOM_MARGIN = 0.3
HUD_FLOOR = 2.45          # highest point for components and wires; lowered under a tall overlay
HUD_GAP = 0.25            # space kept between the overlay and the highest component
X_LIMIT = config.frame_width / 2 - SIDE_MARGIN
Y_MIN = -config.frame_height / 2 + BOTTOM_MARGIN

STEP = 1.0                # normal length of one action
KIND_STEP = {"spawn": 0.6, "set_value": 1.5, "measure": 1.5}   # pop-ins are quick; readings roll longer
LCD_GREEN = "#4ADE80"     # digits of the multimeter's display
MIN_STEP = 0.4            # shortest action, when the next one is due right away
WIRE_TIME = 0.5           # drawing the wires a spawn has completed
OUTRO = 0.5               # final fade-out (shorter on very short scenes)
MIN_RUN = 2 / config.frame_rate   # a compressed animation still lasts at least 2 frames
DEFAULT_FLOW_CURRENT = 1.5        # amps an ammeter shows while current flows, if the brief gives none
STUB = 0.35               # every wire leaves its port straight out by this much
LANE = 0.4                # gap between parallel wires that would otherwise overlap
CLEAR = 0.3               # wire channels run this far outside components and labels
BEND_COST = 0.6           # a corner costs as much as this many units of wire


def place(position):
    """"TOP_LEFT" -> (-4.6, 1.2, 0); (x, y, z) stays as given."""
    if not isinstance(position, str):
        return np.array(position, dtype=float)
    row, column = "MIDDLE", "CENTER"
    for part in position.upper().split("_"):
        row = part if part in ROWS else row
        column = part if part in COLUMNS else column
    return np.array([COLUMNS[column], ROWS[row], 0.0])


class ComponentRegistry:
    """ComponentType -> factory(entity, components created so far) -> component.
    The decorator registers a class built from the entity alone; register_factory() covers the
    rest (an SVG icon name, the axes a curve is drawn on)."""
    factories = {}

    @classmethod
    def register(cls, component_type):
        def decorator(component_class):
            cls.factories[component_type] = lambda entity, components: component_class(entity)
            return component_class
        return decorator

    @classmethod
    def register_factory(cls, component_type, factory):
        cls.factories[component_type] = factory

    @classmethod
    def create(cls, entity, components):
        component = cls.factories[entity.type](entity, components)
        if not component.places_itself:
            component.shift(place(entity.position) - component.anchor.get_center())
        component.set_z_index(LAYER_Z[entity.layer])
        return component


@ComponentRegistry.register(ComponentType.BATTERY)
class BatteryComponent(BreezeComponent):
    """A cell: '+' terminal (nub) on the right = "positive", '-' on the left = "negative".
    "active": the charge fills green; "idle": pale."""
    BOOLEAN_STATES = {"active": ("active", "idle")}

    def build(self, initial_state):
        self.is_active = bool(initial_state.get("active", False))
        cell = RoundedRectangle(corner_radius=0.12, width=1.6, height=0.8, color=INK, stroke_width=4).set_fill(COLOR_CARD, 1)
        self.charge = Rectangle(width=1.36, height=0.58, stroke_width=0) \
            .set_fill(ACTIVE, 0.8 if self.is_active else 0.12)
        nub = Rectangle(width=0.14, height=0.32, color=INK, stroke_width=4).set_fill(INK, 1).next_to(cell, RIGHT, buff=0)
        plus = Text("+", font=FONT, font_size=36, weight=BOLD, color=INK).move_to(RIGHT * 0.5)
        minus = Text("−", font=FONT, font_size=36, weight=BOLD, color=INK).move_to(LEFT * 0.5)
        self.define_port("positive", (0.87, 0), (1, 0))
        self.define_port("negative", (-0.8, 0), (-1, 0))
        return VGroup(cell, self.charge, nub, plus, minus)

    def change_state(self, new_state, **kwargs):
        if new_state not in ("active", "idle"):
            raise ValueError(f"a battery has no state {new_state!r} (active, idle)")
        if (new_state == "active") == self.is_active:
            return None
        self.is_active = new_state == "active"
        fill = self.charge.animate.set_fill(ACTIVE, 0.8 if self.is_active else 0.12)
        if self.is_active:
            return AnimationGroup(fill, Flash(self.get_port("positive"), color=ACTIVE))
        return fill


@ComponentRegistry.register(ComponentType.LAMP)
class LampComponent(BreezeComponent):
    """Bulb with a filament on a socket; the two leads under the socket are the terminals.
    "on": yellow bulb, bright filament, rays and a pulsing glow; "off": white bulb, dark filament.
    The wires leave the terminals sideways (left / right), so nothing has to fit under the lamp."""
    BOOLEAN_STATES = {"on": ("on", "off")}

    def build(self, initial_state):
        self.is_on = bool(initial_state.get("on", False))
        self.clock = 0.0
        self.bulb = Circle(radius=0.55, color=INK, stroke_width=4).set_fill(LAMP_ON if self.is_on else COLOR_CARD, 1) \
            .move_to(UP * 0.3)
        self.filament = VMobject(stroke_color=FILAMENT_ON if self.is_on else INK, stroke_width=4 if self.is_on else 3) \
            .set_points_as_corners([np.array([x, y + 0.3, 0]) for x, y in
                                    [(-0.22, -0.08), (-0.11, 0.17), (0, -0.08), (0.11, 0.17), (0.22, -0.08)]])
        socket = Rectangle(width=0.5, height=0.35, color=INK, stroke_width=4).set_fill("#CBD2D9", 1).move_to(DOWN * 0.4)
        leads = VGroup(Line(np.array([-0.15, -0.575, 0]), np.array([-0.3, -0.75, 0]), color=INK, stroke_width=4),
                       Line(np.array([0.15, -0.575, 0]), np.array([0.3, -0.75, 0]), color=INK, stroke_width=4))
        center = self.bulb.get_center()
        self.rays = VGroup(*[Line(center + 0.78 * d, center + 1.05 * d, color=LAMP_ON, stroke_width=6) for d in
                             [np.array([np.cos(a), np.sin(a), 0]) for a in np.linspace(0, 2 * PI, 8, endpoint=False)]])
        self.rays.set_stroke(opacity=1 if self.is_on else 0)
        self.glow = Circle(radius=0.95, stroke_width=0).set_fill(LAMP_ON, opacity=0).move_to(center)
        self.glow.add_updater(self.pulse)
        self.solid = VGroup(self.bulb, socket, leads)
        self.define_port("left_terminal", (-0.3, -0.75), (-1, 0))
        self.define_port("right_terminal", (0.3, -0.75), (1, 0))
        return VGroup(self.glow, self.rays, self.bulb, self.filament, socket, leads)

    def pulse(self, glow, dt):
        self.clock += dt
        glow.set_fill(opacity=0.25 + 0.12 * np.sin(self.clock * 5) if self.is_on else 0)

    def change_state(self, new_state, **kwargs):
        if new_state not in ("on", "off"):
            raise ValueError(f"a lamp has no state {new_state!r} (on, off)")
        if (new_state == "on") == self.is_on:
            return None
        self.is_on = new_state == "on"     # the glow's updater follows this flag
        filament_color, filament_width = (FILAMENT_ON, 4) if self.is_on else (INK, 3)
        return AnimationGroup(self.bulb.animate.set_fill(LAMP_ON if self.is_on else COLOR_CARD, 1),
                              self.filament.animate.set_stroke(filament_color, width=filament_width),
                              self.rays.animate.set_stroke(opacity=1 if self.is_on else 0))


@ComponentRegistry.register(ComponentType.SWITCH)
class SwitchComponent(BreezeComponent):
    """Two contacts and a lever hinged on the "in" contact. "open": lever up; "closed": lever down
    on the "out" contact, contacts green."""
    BOOLEAN_STATES = {"closed": ("closed", "open")}
    OPEN_ANGLE = 25 * PI / 180      # low enough to leave room for a wire above an open switch

    def build(self, initial_state):
        self.is_closed = bool(initial_state.get("closed", False))
        color = ACTIVE if self.is_closed else COLOR_CARD
        self.contact_in = Circle(radius=0.1, color=INK, stroke_width=4).set_fill(color, 1).move_to(LEFT * 0.7)
        self.contact_out = Circle(radius=0.1, color=INK, stroke_width=4).set_fill(color, 1).move_to(RIGHT * 0.7)
        hinge = self.contact_in.get_center()
        angle = 0 if self.is_closed else self.OPEN_ANGLE
        self.lever = Line(hinge, hinge + 1.4 * np.array([np.cos(angle), np.sin(angle), 0]), color=INK, stroke_width=6)
        self.define_port("in", (-0.8, 0), (-1, 0))
        self.define_port("out", (0.8, 0), (1, 0))
        return VGroup(self.lever, self.contact_in, self.contact_out)

    def change_state(self, new_state, **kwargs):
        if new_state not in ("closed", "open"):
            raise ValueError(f"a switch has no state {new_state!r} (closed, open)")
        if (new_state == "closed") == self.is_closed:
            return None
        self.is_closed = new_state == "closed"
        color = ACTIVE if self.is_closed else COLOR_CARD
        turn = -self.OPEN_ANGLE if self.is_closed else self.OPEN_ANGLE
        return AnimationGroup(Rotate(self.lever, angle=turn, about_point=self.contact_in.get_center()),
                              self.contact_in.animate.set_fill(color, 1), self.contact_out.animate.set_fill(color, 1))


@ComponentRegistry.register(ComponentType.AMMETER)
class AmmeterComponent(BreezeComponent):
    """Dial with a scale, a needle and a digital readout ("0.40 A"). State "reading" with value=amps
    turns the needle and updates the readout. initial_state: reading, max (full scale, default 2 A).
    While current flows through it, the engine sets the reading itself (see do_start_flow)."""
    START, END = 150 * PI / 180, 30 * PI / 180   # needle angle at 0 and at full scale

    def build(self, initial_state):
        self.full_scale = float(initial_state.get("max", 2.0)) or 2.0
        self.reading = float(initial_state.get("reading", 0.0))
        self.pivot = np.array([0, -0.15, 0])
        dial = Circle(radius=0.7, color=INK, stroke_width=4).set_fill(COLOR_CARD, 1)
        scale = Arc(radius=0.5, start_angle=self.END, angle=self.START - self.END, arc_center=self.pivot,
                    color=MUTED, stroke_width=3)
        angle = self.needle_angle(self.reading)
        self.needle = Line(self.pivot, self.pivot + 0.48 * np.array([np.cos(angle), np.sin(angle), 0]),
                           color=COLOR_NEGATIVE, stroke_width=4)
        self.readout = self.readout_text(self.reading).move_to(self.pivot + DOWN * 0.3)
        letter = Text("A", font=FONT, font_size=22, weight=BOLD, color=INK).move_to(UP * 0.42)
        self.define_port("in", (-0.7, 0), (-1, 0))
        self.define_port("out", (0.7, 0), (1, 0))
        return VGroup(dial, scale, letter, self.needle, Dot(self.pivot, radius=0.05, color=INK), self.readout)

    def needle_angle(self, value):
        fraction = min(max(value / self.full_scale, 0), 1)
        return self.START + (self.END - self.START) * fraction

    def readout_text(self, value):
        return Text(f"{value:.2f} A", font=FONT, font_size=20, color=INK)

    def change_state(self, new_state, **kwargs):
        if new_state != "reading" or not isinstance(kwargs.get("value"), (int, float)):
            raise ValueError(f"an ammeter only has the state 'reading' with a number, got {new_state!r} {kwargs}")
        old, self.reading = self.reading, float(kwargs["value"])
        turn = self.needle_angle(self.reading) - self.needle_angle(old)
        new_readout = self.readout_text(self.reading).move_to(self.readout)
        return AnimationGroup(Rotate(self.needle, angle=turn, about_point=self.anchor.get_center() + self.pivot),
                              Transform(self.readout, new_readout))


@ComponentRegistry.register(ComponentType.WIRE_BUS)
class WireBusComponent(BreezeComponent):
    """A thick conductor bar that wires join: "in" on the left, "out" on the right. No states."""

    def build(self, initial_state):
        self.define_port("in", (-0.8, 0), (-1, 0))
        self.define_port("out", (0.8, 0), (1, 0))
        return VGroup(Rectangle(width=1.6, height=0.14, stroke_width=0).set_fill(INK, 1),
                      Dot(LEFT * 0.8, radius=0.1, color=INK), Dot(RIGHT * 0.8, radius=0.1, color=INK))

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a wire bus has no state {new_state!r}")


class GroundComponent(BreezeComponent):
    """A ground symbol hanging from its one port, "terminal" (the top of the lead). No states."""
    LEAD = 0.35

    def build(self, initial_state):
        self.define_port("terminal", (0, self.LEAD), (0, 1))
        return VGroup(Line(UP * self.LEAD, np.zeros(3), color=INK, stroke_width=5), *self.symbol())

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a ground symbol has no state {new_state!r}")


@ComponentRegistry.register(ComponentType.EARTH_GROUND)
class EarthGroundComponent(GroundComponent):
    """Protective earth: the lead meets 3 bars of decreasing width (24 / 16 / 8 in SVG units)."""

    def symbol(self):
        return [Line(LEFT * w / 2, RIGHT * w / 2, color=INK, stroke_width=5).shift(DOWN * y)
                for w, y in ((0.6, 0.0), (0.4, 0.13), (0.2, 0.26))]


@ComponentRegistry.register(ComponentType.CHASSIS_MASS)
class ChassisMassComponent(GroundComponent):
    """Chassis / circuit ground (0 V reference): the lead ends on a triangle pointing down."""

    def symbol(self):
        return [Polygon(LEFT * 0.28, RIGHT * 0.28, DOWN * 0.32, color=INK, stroke_width=5)]


@ComponentRegistry.register(ComponentType.VOLTMETER_PROBES)
class VoltmeterProbesComponent(BreezeComponent):
    """Digital multimeter: a card with a dark display and two jacks (black COM on the left, red V on
    the right). Never wired: a "measure" action draws its red and black leads to two pins and rolls
    the display up to the reading (BreezeSceneEngine.do_measure). No states of its own."""

    def build(self, initial_state):
        card = RoundedRectangle(width=1.9, height=1.5, corner_radius=0.15, color=INK, stroke_width=3)
        card.set_fill(COLOR_CARD, 1)
        self.screen = RoundedRectangle(width=1.5, height=0.55, corner_radius=0.08, stroke_width=0)
        self.screen.set_fill("#0F2A1F", 1).move_to(UP * 0.25)
        self.idle_text = Text("0.00 V", font=FONT, font_size=24, color=LCD_GREEN).move_to(self.screen)
        self.jacks = {"b": Dot(np.array([-0.4, -0.45, 0]), radius=0.09, color=INK),
                      "a": Dot(np.array([0.4, -0.45, 0]), radius=0.09, color=COLOR_NEGATIVE)}
        return VGroup(card, self.screen, self.idle_text, *self.jacks.values())

    def jack(self, which):
        """Where the red ("a") or black ("b") lead leaves the meter."""
        return self.jacks[which].get_center()

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a voltmeter has no state {new_state!r} (use the measure action)")


@ComponentRegistry.register(ComponentType.ARROW_ANNOTATION)
class ArrowAnnotationComponent(BreezeComponent):
    """An arrow whose tip is at the entity's position, with optional text at its tail.
    initial_state: text, direction (where the arrow points: DOWN, UP, LEFT, RIGHT, or a vector [x, y]
    drawn at the angle atan2(y, x)). No ports."""
    BLOCKS_WIRES = False

    def build(self, initial_state):
        direction = np.array([*unit_direction(initial_state.get("direction", "DOWN"), "DOWN"), 0.0])
        arrow = Arrow(-direction * 1.3, np.zeros(3), buff=0, color=HIGHLIGHT, stroke_width=7,
                      max_tip_length_to_length_ratio=0.25)
        parts = [arrow]
        if initial_state.get("text"):
            parts.append(label_text(str(initial_state["text"]), 24).next_to(arrow.get_start(), -direction, buff=0.15))
        return VGroup(*parts)

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"an arrow annotation has no state {new_state!r} (use highlighted / dimmed)")


class SpinningComponent(BreezeComponent):
    """Shared by sprocket and pedal crank: "spinning" keeps self.rotor turning around the "center"
    port; "still" stops it. initial_state: spinning."""
    BOOLEAN_STATES = {"spinning": ("spinning", "still")}
    TURNS_PER_SECOND = 0.4

    def start_spinning(self):
        self.rotor.add_updater(lambda rotor, dt: rotor.rotate(-2 * PI * self.TURNS_PER_SECOND * dt,
                                                              about_point=self.anchor.get_center()))

    def change_state(self, new_state, **kwargs):
        if new_state not in ("spinning", "still"):
            raise ValueError(f"a {type(self).__name__} has no state {new_state!r} (spinning, still)")
        if (new_state == "spinning") == self.is_spinning:
            return None
        self.is_spinning = new_state == "spinning"
        if self.is_spinning:
            self.start_spinning()   # paused while the Rotate below plays, then keeps turning
            return Rotate(self.rotor, angle=-PI / 4, about_point=self.anchor.get_center())
        self.rotor.clear_updaters()
        return Rotate(self.rotor, angle=-PI / 12, about_point=self.anchor.get_center())


@ComponentRegistry.register(ComponentType.SPROCKET)
class SprocketComponent(SpinningComponent):
    """A toothed wheel. Ports: "center" (axle) and "rim" (top of the teeth, where a chain runs)."""

    def build(self, initial_state):
        teeth = VGroup(*[Rectangle(width=0.16, height=0.2, stroke_width=0).set_fill(INK, 1).rotate(a)
                         .move_to(0.72 * np.array([np.cos(a), np.sin(a), 0]))
                         for a in np.linspace(0, 2 * PI, 14, endpoint=False)])
        wheel = Circle(radius=0.65, color=INK, stroke_width=5).set_fill("#E4E7EB", 1)
        spokes = VGroup(*[Line(np.zeros(3), 0.6 * np.array([np.cos(a), np.sin(a), 0]), color=MUTED, stroke_width=3)
                          for a in np.linspace(0, 2 * PI, 5, endpoint=False)])
        self.rotor = VGroup(teeth, wheel, spokes)
        self.define_port("center", (0, 0), (0, 1))
        self.define_port("rim", (0, 0.82), (0, 1))
        self.is_spinning = bool(initial_state.get("spinning", False))
        if self.is_spinning:
            self.start_spinning()
        return VGroup(self.rotor, Dot(radius=0.09, color=INK))


@ComponentRegistry.register(ComponentType.PEDAL_CRANK)
class PedalCrankComponent(SpinningComponent):
    """A crank arm and pedal turning around the axle. Ports: "center" (axle), "rim" (top of the
    pedal's circle)."""

    def build(self, initial_state):
        path = Circle(radius=1.0, color=MUTED, stroke_width=2).set_stroke(opacity=0.4)
        arm = Line(np.zeros(3), RIGHT * 1.0, color=INK, stroke_width=10)
        pedal = RoundedRectangle(corner_radius=0.05, width=0.5, height=0.18, color=INK, stroke_width=3) \
            .set_fill("#9AA5B1", 1).move_to(RIGHT * 1.0)
        self.rotor = VGroup(arm, pedal)
        self.define_port("center", (0, 0), (0, 1))
        self.define_port("rim", (0, 1.0), (0, 1))
        self.is_spinning = bool(initial_state.get("spinning", False))
        if self.is_spinning:
            self.start_spinning()
        return VGroup(path, self.rotor, Dot(radius=0.12, color=INK))


@ComponentRegistry.register(ComponentType.CHAIN_LINK)
class ChainLinkComponent(BreezeComponent):
    """One chain link (a rounded plate with two pins): "in" on the left, "out" on the right."""

    def build(self, initial_state):
        plate = RoundedRectangle(corner_radius=0.2, width=1.2, height=0.4, color=INK, stroke_width=4) \
            .set_fill("#CBD2D9", 1)
        pins = VGroup(Dot(LEFT * 0.4, radius=0.08, color=INK), Dot(RIGHT * 0.4, radius=0.08, color=INK))
        self.define_port("in", (-0.6, 0), (-1, 0))
        self.define_port("out", (0.6, 0), (1, 0))
        return VGroup(plate, pins)

    def change_state(self, new_state, **kwargs):
        raise ValueError(f"a chain link has no state {new_state!r}")


# SVG objects: one class, the icon depends on the type (see asset_resolver.ICON_ALIASES).
for _svg_type in SVG_TYPES:
    ComponentRegistry.register_factory(
        _svg_type, lambda entity, components: DynamicSVGComponent(entity, icon_name=entity.type.value.lower()))
# Maths / physics concepts, drawn with Manim geometry.
ComponentRegistry.register(ComponentType.AXES_GRAPH)(AxesGraphComponent)


def anchored_curve(entity, components):
    """(the CurvePlotComponent, the {"curve", "t" or "x"} anchor) a VECTOR_ARROW's or a BODY's "anchor"
    puts it on (a vector riding on a body: the body's), or (None, None): not anchored, or not drawn."""
    anchor = entity.initial_state.get("anchor")
    if isinstance(anchor, dict) and "body" in anchor:
        anchor = getattr(components.get(anchor["body"]), "curve_anchor", None)
    curve = components.get(anchor.get("curve")) if isinstance(anchor, dict) else None
    return (curve, anchor) if isinstance(curve, CurvePlotComponent) else (None, None)


def axes_of(component):
    """The Manim Axes a graph component draws on: an AXES_GRAPH's, or a curve's (own or shared)."""
    return component.plot_axes if isinstance(component, CurvePlotComponent) else component.axes


def place_on_point(component, entity, components):
    """An entity anchored on a point of a graph ({"axes": id, "x", "y"}): its centre goes there, and it
    places itself (anchor_vectors keeps it there if the graph moves). False if not so anchored."""
    anchor = entity.initial_state.get("anchor")
    host = components.get(anchor.get("axes")) if isinstance(anchor, dict) else None
    if not isinstance(host, (AxesGraphComponent, CurvePlotComponent)):
        return False
    point = (float(anchor["x"]), float(anchor["y"]))
    component.places_itself, component.anchored_on = True, (host, point)
    component.shift(axes_of(host).coords_to_point(*point) - component.anchor.get_center())
    return True


def make_object(entity, components):
    """Any concrete thing, drawn like the icon types from its OBJECT_ICONS icon; anchored on a point of
    a graph (the Earth at an orbit's centre), it sits there."""
    component = DynamicSVGComponent(entity, icon_name=entity.initial_state.get("icon", DEFAULT_OBJECT_ICON))
    place_on_point(component, entity, components)
    return component


def make_body(entity, components):
    """A body; anchored on a curve, it sits on that point (and places itself, like an anchored vector);
    or on a point of a graph."""
    component = BodyComponent(entity)
    if place_on_point(component, entity, components):
        return component
    curve, anchor = anchored_curve(entity, components)
    if curve is not None:
        point, _ = anchor_geometry(curve.curve_state, anchor, None, curve.plot_axes.x_range[:2])
        component.places_itself, component.anchored_on, component.curve_anchor = True, (curve, point), anchor
        component.shift(curve.plot_axes.coords_to_point(*point) - component.anchor.get_center())
    return component


def make_vector(entity, components):
    """A vector at the entity's position; anchored on a curve ("anchor", app/curve_math.py), it starts on
    that point of the curve instead, and a TANGENT / CENTER / OUTWARD direction is worked out on the
    curve's axes. Anchored, it places itself (BreezeSceneEngine.anchor_vectors keeps it on the curve).
    Riding on a body ({"body": id}), it starts on the body and follows it (do_move_along), its label
    past its tip."""
    curve, anchor = anchored_curve(entity, components)
    if curve is None:
        component = VectorArrowComponent(entity)
        place_on_point(component, entity, components)      # on a point of a graph, or where the brief says
        return component
    direction = entity.initial_state.get("direction")
    point, toward = anchor_geometry(curve.curve_state, anchor, direction, curve.plot_axes.x_range[:2])
    state = dict(entity.initial_state)
    if toward is not None:
        start, end = curve.plot_axes.coords_to_point(*point), curve.plot_axes.coords_to_point(*toward)
        state["direction"] = [float(end[0] - start[0]), float(end[1] - start[1])]
    component = VectorArrowComponent(entity.model_copy(update={"initial_state": state}))
    component.places_itself, component.anchored_on = True, (curve, point)
    component.shift(curve.plot_axes.coords_to_point(*point) - component.anchor.get_center())
    component.rides = entity.initial_state["anchor"].get("body")
    if component.rides:
        start = component.arrow.get_start()
        unit = (component.arrow.get_end() - start) / max(np.linalg.norm(component.arrow.get_end() - start), 1e-9)
        component.point_along(start, unit)
    return component


ComponentRegistry.register_factory(ComponentType.VECTOR_ARROW, make_vector)
ComponentRegistry.register_factory(ComponentType.BODY, make_body)
ComponentRegistry.register_factory(ComponentType.OBJECT, make_object)
ComponentRegistry.register(ComponentType.TEX_FORMULA)(TexFormulaComponent)


def make_curve(entity, components):
    """A curve on the AXES_GRAPH named in initial_state.axes, or on its own axes."""
    axes = components.get(entity.initial_state.get("axes"))
    return CurvePlotComponent(entity, axes if isinstance(axes, AxesGraphComponent) else None)


ComponentRegistry.register_factory(ComponentType.CURVE_PLOT, make_curve)


# ---------------------------------------------------------------- wires

class FlowWire(VMobject):
    """A wire from a source port to a target port, drawn on the BACKGROUND layer."""

    def __init__(self, points, source_id, target_id, dashed=False):
        super().__init__(stroke_color=MUTED, stroke_width=6)
        self.set_points_as_corners(points)
        self.corners = points
        self.ends = (source_id, target_id)
        self.drawn = False
        if dashed:      # an optional link: the line itself is hidden, its dashes (6 on, 4 off) are drawn
            length = sum(np.linalg.norm(np.array(b) - np.array(a)) for a, b in zip(points, points[1:]))
            dashes = DashedVMobject(VMobject(stroke_color=MUTED, stroke_width=6).set_points_as_corners(points),
                                    num_dashes=max(4, int(length / 0.12)), dashed_ratio=0.6)
            self.set_stroke(opacity=0)
            self.add(dashes)
        self.set_z_index(LAYER_Z[Layer.BACKGROUND])


SEPARATION_STEP = 0.25
CURVE_COLORS = [COLOR_PRIMARY, COLOR_NEGATIVE, COLOR_POSITIVE, "#8B5CF6", "#F59E0B"]   # curves sharing axes
LEGEND_WRAPS = (28, 22, 18, 15, 12)   # line widths (characters) tried for a curve legend, widest first


def counter_text(value, unit, decimals, color):
    """French number formatting: 1250.5 -> "1 250,5" (+ unit), bold, for the animated counters."""
    number = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return Text(f"{number} {unit}".strip(), font=FONT, font_size=40, weight=BOLD, color=color)


def box_area_overlap(a, b):
    """Area shared by two mobjects' bounding boxes (0 if they do not overlap)."""
    width = min(a.get_right()[0], b.get_right()[0]) - max(a.get_left()[0], b.get_left()[0])
    height = min(a.get_top()[1], b.get_top()[1]) - max(a.get_bottom()[1], b.get_bottom()[1])
    return max(width, 0) * max(height, 0)


def label_cost(label, others, exits, margin=0.05):
    """0 for a perfect label spot; otherwise how bad it is: area overlapping other components and
    labels (with a small margin), port exits covered, and how far it sticks out of the frame."""
    grown = SurroundingRectangle(label, buff=margin)
    cost = sum(box_area_overlap(grown, other) for other in others if has_extent(other))
    cost += sum(1.0 for exit_ in exits if crosses(exit_, label))
    cost += (max(0.0, -X_LIMIT - label.get_left()[0]) + max(0.0, label.get_right()[0] - X_LIMIT)
             + max(0.0, Y_MIN - label.get_bottom()[1]) + max(0.0, label.get_top()[1] - HUD_FLOOR)) * 10
    return cost


def bounding_box(mobject):
    return (mobject.get_left()[0], mobject.get_bottom()[1], mobject.get_right()[0], mobject.get_top()[1])


def boxes_overlap(a, b, margin=0.15):
    return a[0] < b[2] + margin and b[0] < a[2] + margin and a[1] < b[3] + margin and b[1] < a[3] + margin


def box_in_frame(box):
    return box[0] >= -X_LIMIT and box[2] <= X_LIMIT and box[1] >= Y_MIN and box[3] <= HUD_FLOOR


def separation_offsets(max_distance=4.0):
    """(dx, dy) shifts to try, nearest first: below, above, right, left."""
    distance = SEPARATION_STEP
    while distance <= max_distance + 1e-9:
        for dx, dy in ((0, -distance), (0, distance), (distance, 0), (-distance, 0)):
            yield dx, dy
        distance += SEPARATION_STEP


def keep_all_in_frame(components):
    for component in components.values():
        if not component.places_itself:
            keep_in_frame(component.solid, component)


def has_extent(mobject):
    return any(m.has_points() for m in mobject.get_family())


def boxes_touch(m1, m2, margin=0.1):
    """True if the two bounding boxes overlap (with a small margin)."""
    if not (has_extent(m1) and has_extent(m2)):
        return False
    return (m1.get_left()[0] < m2.get_right()[0] + margin and m2.get_left()[0] < m1.get_right()[0] + margin
            and m1.get_bottom()[1] < m2.get_top()[1] + margin and m2.get_bottom()[1] < m1.get_top()[1] + margin)


def inside_frame(mobject):
    return (mobject.get_left()[0] >= -X_LIMIT and mobject.get_right()[0] <= X_LIMIT
            and mobject.get_bottom()[1] >= Y_MIN and mobject.get_top()[1] <= HUD_FLOOR)


def keep_in_frame(measured, moved):
    """Shift `moved` just enough for `measured` to fit inside the frame margins."""
    dx = max(0.0, -X_LIMIT - measured.get_left()[0]) - max(0.0, measured.get_right()[0] - X_LIMIT)
    dy = max(0.0, Y_MIN - measured.get_bottom()[1]) - max(0.0, measured.get_top()[1] - HUD_FLOOR)
    if dx or dy:
        moved.shift(np.array([dx, dy, 0.0]))


def dedupe(points):
    """Drop repeated points and middle points of straight runs."""
    kept = [points[0]]
    for point in points[1:]:
        if np.linalg.norm(point - kept[-1]) > 1e-3:
            kept.append(point)
    clean = [kept[0]]
    for i in range(1, len(kept) - 1):
        if np.linalg.norm(np.cross(kept[i] - clean[-1], kept[i + 1] - kept[i])) > 1e-6:
            clean.append(kept[i])
    return clean + [kept[-1]] if len(kept) > 1 else clean


def segment_hits_box(p, q, box):
    """True if the axis-aligned segment p-q touches the box (left, bottom, right, top)."""
    left, bottom, right, top = box
    return (min(p[0], q[0]) <= right and max(p[0], q[0]) >= left
            and min(p[1], q[1]) <= top and max(p[1], q[1]) >= bottom)


def crosses(points, mobject, margin=0.1):
    """True if the right-angle path passes through the mobject's bounding box."""
    left, bottom = mobject.get_corner(DOWN + LEFT)[:2] - margin
    right, top = mobject.get_corner(UP + RIGHT)[:2] + margin
    for p, q in zip(points, points[1:]):
        x_low, x_high = sorted((p[0], q[0]))
        y_low, y_high = sorted((p[1], q[1]))
        if x_low <= right and x_high >= left and y_low <= top and y_high >= bottom:
            return True
    return False


def overlaps(points, other_points):
    """True if a segment of one path runs along a segment of the other: parallel, closer than half a
    LANE, over a shared length. Such wires would look like one thick wire, or touch."""
    for p, q in zip(points, points[1:]):
        for r, s in zip(other_points, other_points[1:]):
            for axis, other in ((1, 0), (0, 1)):     # horizontal segments share y; vertical share x
                if abs(p[axis] - q[axis]) < 1e-3 and abs(r[axis] - s[axis]) < 1e-3 and abs(p[axis] - r[axis]) < LANE / 2:
                    low = max(min(p[other], q[other]), min(r[other], s[other]))
                    high = min(max(p[other], q[other]), max(r[other], s[other]))
                    if high - low > 0.05:
                        return True
    return False


# ---------------------------------------------------------------- scene

class BreezeSceneEngine(MovingCameraScene):
    """Plays one brief. The generated script subclasses it and sets brief_file to a JSON file:
    {"brief": SceneVisualBrief, "duration": voice seconds, "planned_duration": script seconds,
     "carried_overlay": {"title", "subtitle"} still on screen from the previous scene, or null,
     "pan_out": true if another scene follows (the camera pans away instead of fading out),
     "overlay_stays": true if the next scene keeps this scene's title (it stays put during the pan)}."""
    brief_file = None

    def construct(self):
        with open(self.brief_file, encoding="utf-8") as f:
            data = json.load(f)
        brief = SceneVisualBrief.model_validate(data["brief"])
        # Not self.duration: Manim's Scene.play() overwrites that attribute with each animation's length.
        self.voice_duration = float(data["duration"])
        self.planned_duration = data.get("planned_duration")
        self.outro = min(OUTRO, max(0.15, 0.1 * self.voice_duration))
        self.camera.background_color = COLOR_BG
        self.pan_out = bool(data.get("pan_out", False))
        self.overlay_stays = bool(data.get("overlay_stays", False))
        self.counters = {}       # entity id -> {"tracker", "badge"}: animated numbers (set_value)
        self.probes = {}         # voltmeter id -> {"tracker", "display", "leads", "rings"} (measure)
        self.setup_scene(brief, data.get("carried_overlay"))
        self.execute_actions(brief)

    # ---- setup

    def setup_scene(self, brief, carried_overlay=None):
        """Keep or clear the previous overlay, place the components, route the wires.
        Nothing is drawn here except a kept overlay: components appear when spawned, wires when
        both their ends are on screen."""
        self.overlay = None
        self.lower_hud_floor(brief, carried_overlay)
        keep = brief.text_overlay is None or not brief.text_overlay.clear_previous
        if carried_overlay and keep:
            self.overlay = self.build_overlay(carried_overlay.get("title"), carried_overlay.get("subtitle"))
            if self.overlay:
                self.add(self.overlay)   # it was already on screen at the end of the previous scene
        # Curves last: one drawn on an AXES_GRAPH sits on those axes, so they must be placed first;
        # then the vectors anchored on a curve, which start on it.
        self.components = {}
        self.body_params = {}      # a moving body's current t (or x): where its next move_along starts
        self.entity_states = {e.id: e.initial_state for e in brief.entities}
        curves = [e for e in brief.entities if e.type == ComponentType.CURVE_PLOT]
        bodies = [e for e in brief.entities if e.type in (ComponentType.BODY, ComponentType.OBJECT) and "anchor" in e.initial_state]
        anchored = [e for e in brief.entities if e.type == ComponentType.VECTOR_ARROW and "anchor" in e.initial_state]
        for entity in ([e for e in brief.entities if e.type != ComponentType.CURVE_PLOT and e not in anchored + bodies]
                       + curves + bodies + anchored):          # a vector may ride on a body, on a curve
            if entity in curves and not self.components.get(entity.initial_state.get("axes")):
                keep_all_in_frame(self.components)
            try:
                self.components[entity.id] = ComponentRegistry.create(entity, self.components)
            except (ValueError, KeyError, OSError) as exc:     # bad func, unreadable SVG...
                warn(f"scene {brief.scene_id}: {entity.id} ({entity.type.value}) not drawn: {exc}")
        keep_all_in_frame(self.components)
        self.separate_components()
        self.anchor_vectors()
        self.stack_curve_legends()
        self.connections = brief.connections      # labels keep clear of the ports that will be wired
        self.place_labels()
        self.visible = set()
        self.flows = {}          # flow key (the path, as a tuple) -> {"electrons", "wires"}
        self.wires = []
        for connection in brief.connections:
            try:
                points = self.route(connection)
            except KeyError as exc:
                warn(f"scene {brief.scene_id}: {exc}; wire skipped")
                continue
            self.wires.append(FlowWire(points, connection.source_id, connection.target_id, connection.dashed))

    def build_overlay(self, title, subtitle):
        """Title, then the subtitle 0.25 below it, at the top edge (HUD layer)."""
        parts = []
        if title:
            parts.append(Text(title, font=FONT, font_size=40, weight=BOLD, color=INK))
        if subtitle:
            sub = Text(textwrap.fill(subtitle, 55), font=FONT, font_size=28, color=MUTED)
            parts.append(sub.next_to(parts[-1], DOWN, buff=0.25) if parts else sub)
        if not parts:
            return None
        group = VGroup(*parts)
        if group.width > 12.5:
            group.scale_to_fit_width(12.5)
        group.title_text = title if title else None      # compared when the next title arrives
        return group.to_edge(UP, buff=0.4).set_z_index(LAYER_Z[Layer.HUD])

    def lower_hud_floor(self, brief, carried_overlay):
        """Keep components and wires HUD_GAP below the tallest overlay this scene shows (its own or
        the one kept from the previous scene). One scene per process, so the module value is set."""
        global HUD_FLOOR
        overlays = [brief.text_overlay and self.build_overlay(brief.text_overlay.title, brief.text_overlay.subtitle),
                    carried_overlay and self.build_overlay(carried_overlay.get("title"), carried_overlay.get("subtitle"))]
        bottoms = [o.get_bottom()[1] for o in overlays if o is not None]
        if bottoms:
            HUD_FLOOR = min(HUD_FLOOR, min(bottoms) - HUD_GAP)

    def separate_components(self):
        """No two components on top of each other: one that overlaps a component already placed is
        moved to the nearest free spot (in steps of SEPARATION_STEP, below, above, right, left), inside
        the frame. Components that place themselves (a curve on its axes) go first and never move."""
        def host(c):      # what a component sits on: a curve its axes, an anchored vector its curve's axes
            curve = getattr(c, "anchored_on", (None,))[0]
            return (getattr(curve, "axes_component", None) or curve) if curve is not None else getattr(c, "axes_component", None)

        placed = []      # (component, box)
        for component in sorted(self.components.values(), key=lambda c: not c.places_itself):
            box = bounding_box(component.solid)
            # A curve and the axes it is drawn on overlap on purpose; so does a vector anchored on it.
            others = [b for c, b in placed if host(c) is not component and host(component) is not c]
            if not component.places_itself and any(boxes_overlap(box, other) for other in others):
                for dx, dy in separation_offsets():
                    moved = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
                    if box_in_frame(moved) and not any(boxes_overlap(moved, other) for other in others):
                        component.shift(np.array([dx, dy, 0.0]))
                        # What sits on it goes with it (placed first, so it would stay behind).
                        for i, (c, b) in enumerate(placed):
                            if host(c) is component:
                                c.shift(np.array([dx, dy, 0.0]))
                                placed[i] = (c, (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy))
                        box = moved
                        break
                else:
                    warn(f"{component.entity_id}: no free spot, it overlaps another component")
            placed.append((component, box))

    def place_labels(self):
        """Give each label the first free spot among label_spots(): inside the frame, touching no
        component or label already placed, covering no port's exit (where a wire must go). With no
        free spot, the one that overlaps least wins (not blindly the first side). Only ports that are
        wired count: a valve's four ports must not keep its label away from all four sides."""
        taken = [c.solid for c in self.components.values()]
        wired = ({(c.source_id, c.source_port) for c in self.connections}
                 | {(c.target_id, c.target_port) for c in self.connections})
        exits = [[c.get_port(name), c.get_port(name) + c.port_direction(name) * (STUB + CLEAR)]
                 for c in self.components.values() for name in c.port_vectors if (c.entity_id, name) in wired]
        placed = []
        for component in self.components.values():
            label = component.label
            if not has_extent(label):
                continue
            others = [m for m in taken if m is not component.solid] + placed
            best, best_cost = None, float("inf")
            for spot in self.label_spots(component, placed):
                label.move_to(spot)
                cost = label_cost(label, others, exits)
                if cost < best_cost:
                    best, best_cost = spot, cost
                if cost == 0:
                    break
            label.move_to(best)
            keep_in_frame(label, label)
            component.refresh_veil()
            placed.append(label)

    def label_spots(self, component, placed, buff=0.3, stack_buff=0.15):
        """Centres to try for a component's label, best first: its LABEL_SIDES, then the four corners,
        then stacked just under (or over) a label already placed nearby: several labels piled at
        one spot become a neat column, like VGroup().arrange(DOWN, buff=0.15)."""
        label, solid = component.label, component.solid
        spots = []
        for side in list(component.LABEL_SIDES) + [DOWN + RIGHT, DOWN + LEFT, UP + RIGHT, UP + LEFT]:
            label.next_to(solid, side, buff=buff)
            spots.append(label.get_center())
        natural = spots[0]
        for other in placed:
            if abs(other.get_center()[0] - natural[0]) < (other.width + label.width) / 2 + 0.5:
                for side in (DOWN, UP):
                    label.next_to(other, side, buff=stack_buff)
                    spots.append(label.get_center())
        return spots

    def anchor_vectors(self):
        """Anchored vectors back on their curve's point, after their axes may have been moved."""
        for component in self.components.values():
            host, point = getattr(component, "anchored_on", (None, None))
            if host is not None:
                component.shift(axes_of(host).coords_to_point(*point) - component.anchor.get_center())

    def stack_curve_legends(self):
        """Curves sharing axes get distinct colours, and their legends become one column to the right
        of the graph (buff 0.3 between entries), shrunk to fit the frame. With too little room on
        the right, the column goes under the graph. Legends appear with their curve, one by one."""
        for axes in [c for c in self.components.values() if isinstance(c, AxesGraphComponent)]:
            curves = [c for c in self.components.values()
                      if isinstance(c, CurvePlotComponent) and c.axes_component is axes]
            for i, curve in enumerate(c for c in curves if not c.has_own_color):
                curve.set_color(CURVE_COLORS[i % len(CURVE_COLORS)])
            labelled = [c for c in curves if c.legend is not None]
            if not labelled:
                continue
            legends = [c.legend for c in labelled]
            room = X_LIMIT - (axes.solid.get_right()[0] + 0.3)
            # Narrower lines before smaller letters: rewrap each legend until it fits the room.
            entries = []
            for curve in labelled:
                for width in LEGEND_WRAPS:
                    entry = Text(textwrap.fill(curve.legend_text, width, break_long_words=False), font=FONT,
                                 font_size=24, color=curve.legend.get_color())
                    if entry.width <= room:
                        break
                entries.append(entry)
            column = VGroup(*entries).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
            if column.height > axes.solid.height:      # no taller than the graph it explains
                column.scale_to_fit_height(axes.solid.height)
            if room >= 1.6:
                if column.width > room:
                    column.scale_to_fit_width(room)
                column.next_to(axes.solid, RIGHT, buff=0.3, aligned_edge=UP)
            else:
                if column.width > 2 * X_LIMIT:
                    column.scale_to_fit_width(2 * X_LIMIT)
                column.next_to(axes.solid, DOWN, buff=0.3, aligned_edge=LEFT)
            for legend, spot in zip(legends, column):
                legend.become(spot)

    def route(self, connection):
        """Shortest clean right-angle path from port to port (Dijkstra on a channel grid).

        Each end leaves its port straight out (STUB). The grid's lines are "channels": vertical and
        horizontal lines running CLEAR outside every component and label (and a few LANEs further
        out), plus the lines through the two stub ends. A grid step is allowed if it crosses no
        component or label and does not run along an existing wire. The search minimises length +
        BEND_COST per corner, never doubles back into a port, and arrives straight into the target
        port, so any number of corners is possible."""
        a, b = self.components[connection.source_id], self.components[connection.target_id]
        start, end = a.get_port(connection.source_port), b.get_port(connection.target_port)
        dir_a, dir_b = a.port_direction(connection.source_port), b.port_direction(connection.target_port)
        out_a, out_b = start + dir_a * STUB, end + dir_b * STUB
        gap = end - start
        if (np.allclose(dir_a, -dir_b) and np.linalg.norm(np.cross(gap, dir_a)) < 1e-3
                and np.dot(gap, dir_a) > 0 and np.dot(gap, dir_a) < 2 * STUB):
            return [start, end]     # facing ports on one line, closer than two stubs: one straight wire
        # (mobject, margin): the two ends' own drawings may be grazed (their ports sit on their edge),
        # never crossed; everything else, labels included, is kept at a distance.
        obstacles = []
        for c in self.components.values():
            if not c.BLOCKS_WIRES:
                continue
            if c in (a, b):
                obstacles += [(c.solid, -0.02), (c.label, 0.1)]
            else:
                obstacles.append((c.obstacle, 0.1))
        # Bounding boxes (left, bottom, right, top), grown by each margin, computed once.
        boxes = [(o.get_left()[0] - m, o.get_bottom()[1] - m, o.get_right()[0] + m, o.get_top()[1] + m)
                 for o, m in obstacles if has_extent(o)]
        xs, ys = {out_a[0], out_b[0]}, {out_a[1], out_b[1]}
        edges_x = sorted({e for box in boxes for e in (box[0], box[2])})
        edges_y = sorted({e for box in boxes for e in (box[1], box[3])})
        for left, bottom, right, top in boxes:
            for k in range(3):
                xs |= {left - CLEAR - k * LANE, right + CLEAR + k * LANE}
                ys |= {bottom - CLEAR - k * LANE, top + CLEAR + k * LANE}
        xs |= {(p + q) / 2 for p, q in zip(edges_x, edges_x[1:])}   # through narrow gaps, midway
        ys |= {(p + q) / 2 for p, q in zip(edges_y, edges_y[1:])}
        xs = sorted(x for x in xs if abs(x) <= X_LIMIT + 1e-6)
        ys = sorted(y for y in ys if Y_MIN - 1e-6 <= y <= HUD_FLOOR + 1e-6)
        path = self.grid_search(xs, ys, out_a, out_b, dir_a, dir_b, boxes)
        if path is None:
            # Second chance: around the components only. Crossing a label is better than crossing a
            # part, or than the straight fallback below.
            parts = [c.solid for c in self.components.values() if c.BLOCKS_WIRES]
            margins = [-0.02 if c in (a, b) else 0.1 for c in self.components.values() if c.BLOCKS_WIRES]
            part_boxes = [(o.get_left()[0] - m, o.get_bottom()[1] - m, o.get_right()[0] + m, o.get_top()[1] + m)
                          for o, m in zip(parts, margins) if has_extent(o)]
            path = self.grid_search(xs, ys, out_a, out_b, dir_a, dir_b, part_boxes)
        if path is None:
            warn(f"no clean route from {a.entity_id}:{connection.source_port} to {b.entity_id}:{connection.target_port}")
            path = [out_a, np.array([out_b[0], out_a[1], 0.0]), out_b]
        return dedupe([start, *path, end])

    def grid_search(self, xs, ys, out_a, out_b, dir_a, dir_b, boxes):
        """Dijkstra over grid nodes (x index, y index, direction of travel). Returns the corner
        points from out_a to out_b, or None if no clean path exists."""
        steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        def heading(vector):
            return steps.index((int(np.sign(round(vector[0]))), int(np.sign(round(vector[1])))))
        def node(point):
            return xs.index(point[0]), ys.index(point[1])
        def point(i, j):
            return np.array([xs[i], ys[j], 0.0])
        clean = {}
        def step_is_clean(i, j, i2, j2):
            key = (i, j, i2, j2)
            if key not in clean:
                segment = [point(i, j), point(i2, j2)]
                clean[key] = (not any(segment_hits_box(segment[0], segment[1], box) for box in boxes)
                              and not any(overlaps(segment, w.corners) for w in self.wires))
            return clean[key]
        first, arrive = heading(dir_a), heading(-dir_b)     # leave along dir_a, arrive into the port
        source, goal = node(out_a), node(out_b)
        best = {(*source, first): 0.0}
        parent = {}
        queue = [(0.0, 0, (*source, first))]
        counter = 1
        while queue:
            cost, _, state = heapq.heappop(queue)
            i, j, d = state
            if cost > best.get(state, float("inf")):
                continue
            if (i, j) == goal and d == arrive or (i, j) == goal == source:
                corners = [point(i, j)]
                while state in parent:
                    state = parent[state]
                    corners.append(point(state[0], state[1]))
                return dedupe(corners[::-1])
            for new_d, (di, dj) in enumerate(steps):
                if (di, dj) == tuple(-v for v in steps[d]):       # no U-turn on the spot
                    continue
                i2, j2 = i + di, j + dj
                if not (0 <= i2 < len(xs) and 0 <= j2 < len(ys)) or not step_is_clean(i, j, i2, j2):
                    continue
                new_cost = cost + abs(xs[i2] - xs[i]) + abs(ys[j2] - ys[j]) + (BEND_COST if new_d != d else 0)
                new_state = (i2, j2, new_d)
                if new_cost < best.get(new_state, float("inf")):
                    best[new_state] = new_cost
                    parent[new_state] = state
                    heapq.heappush(queue, (new_cost, counter, new_state))
                    counter += 1
        return None

    # ---- timeline

    def build_events(self, brief):
        """Every timed step as {"at": seconds on the voice, "kind", "target", "run": function returning
        (animations, callbacks after them)}, sorted by time; same-time steps keep their order."""
        actions = [a for a in brief.actions if isinstance(a, dict)]
        times = [float(a["at"]) for a in actions if isinstance(a.get("at"), (int, float))]
        planned = self.planned_duration or (max(times) + 2 if times else self.voice_duration)
        scale = self.voice_duration / planned
        latest = max(self.voice_duration - self.outro - MIN_STEP, 0)
        events = []
        overlay = brief.text_overlay
        if overlay and (overlay.title or overlay.subtitle):
            events.append({"at": 0.0, "kind": "overlay", "target": None, "run": lambda: self.show_overlay(overlay)})
            if overlay.duration:
                events.append({"at": overlay.duration * scale, "kind": "overlay", "target": None,
                               "run": self.hide_overlay})
        spawned_by_action = {a.get("target") for a in actions if a.get("action") == "spawn"}
        for entity in brief.entities:
            if entity.id not in spawned_by_action:
                events.append({"at": 0.0, "kind": "spawn", "target": entity.id,
                               "run": lambda i=entity.id: self.do_spawn(i)})
        for action in actions:
            run = self.action_runner(brief.scene_id, action)
            if run:
                at = action.get("at", 0)
                events.append({"at": float(at) * scale if isinstance(at, (int, float)) else 0.0,
                               "kind": action.get("action"), "target": action.get("target"), "run": run})
        for event in events:
            event["at"] = min(event["at"], latest)
        return sorted(events, key=lambda event: event["at"])

    def action_runner(self, scene_id, action):
        """Check one action dict and return the function that plays it, or None (with a warning)."""
        kind = action.get("action")
        if kind in ("spawn", "set_state", "fade_out"):
            target = action.get("target")
            if target not in self.components:
                warn(f"scene {scene_id}: {kind} on unknown entity {target!r}; skipped")
                return None
            if kind == "spawn":
                return lambda: self.do_spawn(target)
            if kind == "fade_out":
                return lambda: self.do_fade_out(target)
            if "state" not in action:
                warn(f"scene {scene_id}: set_state on {target} without a state; skipped")
                return None
            return lambda: self.do_set_state(scene_id, target, action["state"])
        if kind == "start_flow":
            path = action.get("path")
            if not isinstance(path, list) or len(path) < 2 or any(p not in self.components for p in path):
                warn(f"scene {scene_id}: start_flow needs a path of 2+ known entities, got {path!r}; skipped")
                return None
            current = action.get("current")
            if current is not None and not (isinstance(current, (int, float)) and current >= 0):
                warn(f"scene {scene_id}: start_flow current must be a number of amps, got {current!r}; default used")
                current = None
            return lambda: self.do_start_flow(scene_id, path, current)
        if kind == "stop_flow":
            path = action.get("path")
            return lambda: self.do_stop_flow(tuple(path) if isinstance(path, list) else None)
        if kind == "set_value":
            target, value = action.get("target"), action.get("value")
            if target not in self.components or not isinstance(value, (int, float)):
                warn(f"scene {scene_id}: set_value needs a known target and a numeric value, got "
                     f"{target!r} / {value!r}; skipped")
                return None
            return lambda: self.do_set_value(scene_id, target, float(value), str(action.get("unit", "")),
                                             action.get("decimals"), action.get("tone"))
        if kind == "measure":
            meter, value = self.components.get(action.get("target")), action.get("value")
            pins = [split_pin(action.get(key)) for key in ("target_pin_a", "target_pin_b")]
            if (not isinstance(meter, VoltmeterProbesComponent) or None in pins or not isinstance(value, (int, float))
                    or any(i not in self.components or port not in self.components[i].port_vectors for i, port in pins)):
                warn(f"scene {scene_id}: measure needs a VOLTMETER_PROBES target, two real pins and a value, "
                     f"got {action}; skipped")
                return None
            return lambda: self.do_measure(scene_id, action["target"], pins, float(value),
                                           str(action.get("unit") or "V"), action.get("decimals"))
        if kind == "move_along":
            body, to = self.components.get(action.get("target")), action.get("to")
            duration = action.get("duration", 4)
            if (not isinstance(body, BodyComponent) or not getattr(body, "curve_anchor", None)
                    or not isinstance(to, (int, float)) or not isinstance(duration, (int, float)) or duration <= 0):
                warn(f"scene {scene_id}: move_along needs a BODY anchored on a curve, a number \"to\" and a "
                     f"duration, got {action}; skipped")
                return None
            return lambda: self.do_move_along(action["target"], float(to), float(duration))
        warn(f"scene {scene_id}: unknown action {kind!r}; skipped")
        return None

    def do_move_along(self, target, to, duration):
        """Start the body's trip along its curve, from where it is to `to` (t or x), at an even pace over
        `duration` seconds of the scene: an updater, so the timeline goes on meanwhile (as flows do).
        The vectors riding on it go with it, a TANGENT / CENTER / OUTWARD one turning as it goes."""
        body = self.components[target]
        curve, anchor = body.anchored_on[0], body.curve_anchor
        key = "t" if "t" in anchor else "x"
        start = self.body_params.get(target, anchor[key])
        axes, x_range = curve.plot_axes, curve.plot_axes.x_range[:2]
        riders = [c for c in self.components.values() if getattr(c, "rides", None) == target]
        clock = {"elapsed": 0.0}

        def follow(mobject, dt):
            clock["elapsed"] += dt
            value = start + (to - start) * min(clock["elapsed"] / duration, 1.0)
            self.body_params[target] = value
            here = {"curve": anchor["curve"], key: value}
            point, _ = anchor_geometry(curve.curve_state, here, None, x_range)
            spot = axes.coords_to_point(*point)
            body.shift(spot - body.anchor.get_center())
            for rider in riders:
                direction = self.entity_states[rider.entity_id].get("direction")
                _, toward = anchor_geometry(curve.curve_state, here, direction, x_range)
                if toward is None:                      # a cardinal or [dx, dy]: it keeps its way
                    way = rider.arrow.get_end() - rider.arrow.get_start()
                else:
                    way = axes.coords_to_point(*toward) - spot
                rider.point_along(spot, way / max(np.linalg.norm(way), 1e-9))
            if clock["elapsed"] >= duration:
                mobject.remove_updater(follow)

        def begin():
            body.clear_updaters()           # a new trip replaces a running one, from where it got to
            body.add_updater(follow)
        return [], [begin]

    def plan_timeline(self, events):
        """Dry run of the scheduler's timing rules, drawing nothing: when each event starts, how long
        it runs, and how long drawing the wires it completes takes. Events play one after the other:
        an event starts at its "at" or when the previous one is done; it lasts STEP, or less if the
        next one is due sooner (never under MIN_STEP); then the wires whose two ends are now on
        screen are drawn (WIRE_TIME). Returns (plan, natural_end): the time the timeline needs."""
        visible, drawn, alive = set(), set(), set(range(len(self.wires)))
        plan, now = [], 0.0
        for index, event in enumerate(events):
            start = event["at"] if event["at"] - now > 0.05 else now
            next_at = events[index + 1]["at"] if index + 1 < len(events) else self.voice_duration - self.outro
            kind, target = event["kind"], event["target"]
            run = max(MIN_STEP, min(KIND_STEP.get(kind, STEP), next_at - start))
            if kind == "spawn" or (kind in ("set_state", "set_value", "measure") and target not in visible):
                visible.add(target)
            elif kind == "fade_out":
                visible.discard(target)
                alive -= {i for i in alive if target in self.wires[i].ends}
            ready = {i for i in alive - drawn if set(self.wires[i].ends) <= visible}
            drawn |= ready
            wires = WIRE_TIME if ready else 0.0
            plan.append({"start": start, "run": run, "wires": wires})
            now = start + run + wires
        return plan, now

    def execute_actions(self, brief):
        """Play the events one after the other, compressed if needed to end with the voice.

        plan_timeline() gives the time the timeline naturally needs. If that is longer than the voice
        (minus the outro), every start time, run_time and wire-drawing time is multiplied by
        compression_ratio = available / natural, so the last action (the lamp lighting up...) still
        happens before the voice ends. Each event waits for its planned (compressed) start, so a step
        that turns out to animate nothing gives its time back instead of delaying the rest. Running
        flows, glowing lamps and spinning wheels keep moving during the waits (updaters)."""
        events = self.build_events(brief)
        plan, natural_end = self.plan_timeline(events)
        available = self.voice_duration - self.outro
        ratio = min(1.0, available / natural_end) if natural_end > 0 else 1.0
        # Read by agent006 for render_manifest.json.
        print(f"BREEZE_INFO: compression_ratio={ratio:.3f} natural={natural_end:.2f} available={available:.2f}",
              flush=True)
        now = 0.0
        for event, step in zip(events, plan):
            start = step["start"] * ratio
            if start - now > 0.05:
                self.wait(start - now)
                now = start
            animations, callbacks = event["run"]()
            if animations:
                run_time = max(MIN_RUN, step["run"] * ratio)
                self.play(*animations, run_time=run_time)
                now += run_time
            for callback in callbacks:
                callback()
            ready = [w for w in self.wires if not w.drawn and set(w.ends) <= self.visible]
            if ready:
                for wire in ready:
                    wire.drawn = True
                run_time = max(MIN_RUN, WIRE_TIME * ratio)
                self.play(*[Create(wire, rate_func=ease_in_out_sine) for wire in ready], run_time=run_time)
                now += run_time
        if available - now > 0.05:
            self.wait(available - now)
        self.finish()

    def finish(self):
        """End of the scene. When another scene follows, the camera pans one screen to the right, so
        the content slides out to the left instead of vanishing (the next scene opens on an empty,
        same-colour frame and pops its own content in). A title the next scene keeps is held in
        place during the pan. The last scene fades out; its overlay stays to the cut."""
        if self.pan_out:
            frame = self.camera.frame
            if self.overlay is not None and self.overlay_stays:
                offset = self.overlay.get_center() - frame.get_center()
                # The title's parts went into the scene one by one (Write, FadeIn): put the group in
                # instead, or its updater would never run. It takes dt so Manim redraws it every frame.
                self.remove(*self.overlay)
                self.add(self.overlay)
                self.overlay.add_updater(lambda overlay, dt: overlay.move_to(frame.get_center() + offset))
            self.play(frame.animate.shift(RIGHT * config.frame_width), run_time=self.outro, rate_func=ease_in_out_sine)
            return
        leaving = [self.components[i] for i in self.visible] + [w for w in self.wires if w.drawn]
        leaving += [flow["electrons"] for flow in self.flows.values()]
        leaving += [counter["badge"] for counter in self.counters.values()]
        leaving += [part for probe in self.probes.values() for part in self.probe_parts(probe)]
        if leaving:
            self.play(*[FadeOut(m) for m in leaving], run_time=self.outro)

    # ---- steps: each returns (animations, callbacks to run after they play)

    def show_overlay(self, overlay):
        """Write the scene's title. Over a title kept from the previous scene: same title, it stays
        put and only the subtitle changes; another title, the two cross-fade."""
        new = self.build_overlay(overlay.title, overlay.subtitle)
        old = self.overlay
        self.overlay = new
        if old is None:
            return [AnimationGroup(*[Write(part) for part in new], lag_ratio=0.5)], []
        if overlay.title and old.title_text == overlay.title:
            self.remove(old, *old)
            self.add(new[0])                   # the same words at the same place: an invisible swap
            animations = [FadeOut(old[1])] if len(old) > 1 else []
            if len(new) > 1:
                animations.append(FadeIn(new[1], shift=DOWN * 0.1))
            return animations, []
        return [FadeTransform(old, new)], []

    def hide_overlay(self):
        if self.overlay is None:
            return [], []
        overlay, self.overlay = self.overlay, None
        return [FadeOut(overlay)], []

    def do_spawn(self, entity_id):
        if entity_id in self.visible:
            return [], []
        self.visible.add(entity_id)
        # The whole component goes into the scene now: a spawn that animates only part of it (draw the
        # curve, fade in its label) would otherwise leave the other parts out. Nothing is drawn
        # before the spawn animation starts, so nothing pops in.
        self.add(self.components[entity_id])
        return [self.components[entity_id].spawn()], []

    def do_set_state(self, scene_id, entity_id, state):
        component = self.components[entity_id]
        if entity_id not in self.visible:
            warn(f"scene {scene_id}: set_state on {entity_id} before it was spawned; shown now")
            self.visible.add(entity_id)
            self.add(component)
        animations = []
        for name, kwargs in component.states_from(state):
            try:
                animation = component.animate_state(name, **kwargs)
            except ValueError as exc:
                warn(f"scene {scene_id}: {exc}")
                continue
            if animation is not None:
                animations.append(animation)
        return animations, []

    def flow_loop(self, scene_id, path):
        """The wires along `path`, oriented in the path's direction, joined into one closed loop.
        A path that does not come back to its start is closed with the wire from its last entity to
        its first, if there is one: ["bat", "lamp"] -> bat+ -> top wire -> lamp -> bottom wire -> bat-.
        Between two wires the electrons cross the component (lamp from one terminal to the other,
        battery from - to +). Returns (points of the loop, wires used), or (None, None)."""
        ids = list(path)
        if ids[0] != ids[-1] and any(set(w.ends) == {ids[-1], ids[0]} for w in self.wires):
            ids.append(ids[0])
        points, used = [], []
        for a, b in zip(ids, ids[1:]):
            candidates = [w for w in self.wires if set(w.ends) == {a, b} and w not in used]
            wire = next((w for w in candidates if w.ends == (a, b)), candidates[0] if candidates else None)
            if wire is None or not wire.drawn:
                warn(f"scene {scene_id}: start_flow: no wire on screen between {a} and {b}; flow skipped")
                return None, None
            used.append(wire)
            points += wire.corners if wire.ends == (a, b) else wire.corners[::-1]
        if ids[0] == ids[-1]:
            points.append(points[0])          # through the first component, back to the start
        return dedupe(points), used

    def do_start_flow(self, scene_id, path, current=None):
        """12 electrons, evenly spaced, run around the loop at ELECTRON_SPEED until stop_flow or the
        end of the scene: one ValueTracker drives them all (always_redraw + point_from_proportion).
        Every ammeter on the path that reads 0 now shows `current` (DEFAULT_FLOW_CURRENT if None); a
        reading the brief set earlier is kept."""
        key = tuple(path)
        if key in self.flows:
            return [], []
        points, used = self.flow_loop(scene_id, path)
        if points is None:
            return [], []
        loop = VMobject().set_points_as_corners(points)
        length = sum(np.linalg.norm(b - a) for a, b in zip(points, points[1:]))
        tracker = ValueTracker(0.0)

        def electron(i):
            return always_redraw(lambda: Dot(loop.point_from_proportion((tracker.get_value() + i / ELECTRONS) % 1.0),
                                             radius=0.08, color=ELECTRON_COLOR, fill_opacity=1.0)
                                 .set_z_index(LAYER_Z[Layer.FLOW]))

        electrons = VGroup(*[electron(i) for i in range(ELECTRONS)])
        # Linear: the same distance every second. Paused while an animation plays on the electrons.
        electrons.add_updater(lambda group, dt: tracker.increment_value(dt * ELECTRON_SPEED / length))
        ammeters = [self.components[i] for i in dict.fromkeys(path) if isinstance(self.components[i], AmmeterComponent)]
        self.flows[key] = {"electrons": electrons, "wires": used, "ammeters": ammeters}
        amps = DEFAULT_FLOW_CURRENT if current is None else float(current)
        readings = [meter.change_state("reading", value=amps) for meter in ammeters if meter.reading == 0]
        current_arrives = AnimationGroup(FadeIn(electrons), *readings)
        # Current cannot cross an open switch: close every open switch on the path first, then
        # let the electrons in.
        closing = [self.components[i].change_state("closed") for i in dict.fromkeys(path)
                   if isinstance(self.components[i], SwitchComponent) and not self.components[i].is_closed]
        if closing:
            return [Succession(AnimationGroup(*closing), current_arrives)], []
        return [current_arrives], []

    def do_stop_flow(self, key=None):
        """Fade out the electrons of one flow (or of every flow), stop their tracker, and bring the
        ammeters they ran through back to 0.00 A (unless another flow still runs through them)."""
        keys = [key] if key in self.flows else list(self.flows) if key is None else []
        leaving, stopped_meters = [], []
        for k in keys:
            flow = self.flows.pop(k)
            flow["electrons"].clear_updaters()     # the tracker stops advancing
            leaving.append(flow["electrons"])
            stopped_meters += flow.get("ammeters", [])
        still_measured = {id(m) for flow in self.flows.values() for m in flow.get("ammeters", [])}
        resets = [meter.change_state("reading", value=0.0) for meter in dict.fromkeys(stopped_meters)
                  if id(meter) not in still_measured and meter.reading != 0]
        callbacks = [lambda: self.remove(*leaving)] if leaving else []
        return [FadeOut(group) for group in leaving] + resets, callbacks

    def do_fade_out(self, entity_id):
        if entity_id not in self.visible:
            return [], []
        self.visible.discard(entity_id)
        attached = [w for w in self.wires if entity_id in w.ends]
        for wire in attached:
            self.wires.remove(wire)
        broken = [k for k, flow in self.flows.items() if any(w in attached for w in flow["wires"])]
        stop_animations, callbacks = self.do_stop_flow_many(broken)
        counter = self.counters.pop(entity_id, None)
        counter_out = [FadeOut(counter["badge"])] if counter else []
        probe = self.probes.pop(entity_id, None)
        probe_out = [FadeOut(part) for part in self.probe_parts(probe)] if probe else []
        return ([FadeOut(self.components[entity_id])] + [FadeOut(w) for w in attached if w.drawn]
                + stop_animations + counter_out + probe_out), callbacks

    def do_set_value(self, scene_id, entity_id, value, unit, decimals=None, tone=None):
        """An animated counter above the entity, rolling from its previous value (0 the first time)
        to `value`, e.g. "300 Md€". Text redrawn every frame from a ValueTracker: DecimalNumber
        would need LaTeX. tone "positive" / "negative" colours it (default: by the sign)."""
        component = self.components[entity_id]
        if entity_id not in self.visible:
            warn(f"scene {scene_id}: set_value on {entity_id} before it was spawned; shown now")
            self.visible.add(entity_id)
            self.add(component)
        if decimals is None or not isinstance(decimals, int):
            decimals = 0 if float(value).is_integer() else 1
        color = {"positive": COLOR_POSITIVE, "negative": COLOR_NEGATIVE}.get(
            tone, COLOR_NEGATIVE if value < 0 else INK)
        counter = self.counters.get(entity_id)
        if counter is None:
            tracker = ValueTracker(0.0)
            counter = {"tracker": tracker, "unit": unit, "decimals": decimals, "color": color}
            # always_redraw draws once right away: unit, decimals and colour must be set before.
            counter["badge"] = always_redraw(lambda: counter_text(tracker.get_value(), counter["unit"],
                                                                  counter["decimals"], counter["color"])
                                             .next_to(component.solid, UP, buff=0.25)
                                             .set_z_index(LAYER_Z[Layer.OVERLAY]))
            self.counters[entity_id] = counter
            self.add(counter["badge"])         # it rolls up from 0 as soon as the animation starts
        counter.update(unit=unit, decimals=decimals, color=color)
        return [counter["tracker"].animate(rate_func=smooth).set_value(value)], []

    def do_measure(self, scene_id, meter_id, pins, value, unit, decimals=None):
        """The red lead goes to the first pin, the black one to the second (each ends in a contact
        ring), and the display rolls from the previous reading to `value`, e.g. "4.50 V". Leads are
        straight lines from the meter's jacks; a new measure moves them to the new pins."""
        meter = self.components[meter_id]
        if meter_id not in self.visible:
            warn(f"scene {scene_id}: measure with {meter_id} before it was spawned; shown now")
            self.visible.add(meter_id)
            self.add(meter)
        decimals = decimals if isinstance(decimals, int) else 2
        animations = []
        probe = self.probes.get(meter_id)
        if probe is None:
            tracker = ValueTracker(0.0)
            probe = {"tracker": tracker, "unit": unit, "decimals": decimals, "leads": {}, "rings": {}}
            # always_redraw draws once right away: unit and decimals must be set before.
            probe["display"] = always_redraw(lambda: Text(f"{tracker.get_value():.{probe['decimals']}f} {probe['unit']}",
                                                          font=FONT, font_size=24, color=LCD_GREEN)
                                             .move_to(meter.screen).set_z_index(LAYER_Z[Layer.HUD]))
            self.probes[meter_id] = probe
            meter.body.remove(meter.idle_text)     # the live display replaces the idle "0.00 V"
            self.add(probe["display"])
        probe.update(unit=unit, decimals=decimals)
        for which, (entity_id, port), color in (("a", pins[0], COLOR_NEGATIVE), ("b", pins[1], INK)):
            pin = self.components[entity_id].get_port(port)
            lead = Line(meter.jack(which), pin, color=color, stroke_width=5).set_z_index(LAYER_Z[Layer.OVERLAY])
            ring = Circle(radius=0.13, color=HIGHLIGHT, stroke_width=4).move_to(pin).set_z_index(LAYER_Z[Layer.OVERLAY])
            if which in probe["leads"]:
                animations += [Transform(probe["leads"][which], lead), Transform(probe["rings"][which], ring)]
            else:
                probe["leads"][which], probe["rings"][which] = lead, ring
                animations += [Create(lead), FadeIn(ring)]
        animations.append(probe["tracker"].animate(rate_func=smooth).set_value(value))
        return animations, []

    @staticmethod
    def probe_parts(probe):
        return [probe["display"], *probe["leads"].values(), *probe["rings"].values()]

    def do_stop_flow_many(self, keys):
        animations, callbacks = [], []
        for key in keys:
            new_animations, new_callbacks = self.do_stop_flow(key)
            animations += new_animations
            callbacks += new_callbacks
        return animations, callbacks
