"""Animated HTML/CSS/SVG process twin (PRD v1.1.1 Sections 19.3, 19.4; FR-9, AC-21).

PRD 19.3 fixes the rendering technology: the twin is **self-contained HTML/CSS/SVG** generated in
Python and shown with ``IPython.display.HTML``, exportable as a standalone ``.html`` for the factory
demo (Section 29). No 3D engine, no server, no tunnel (NFR-9). The motion here is pure CSS -
``stroke-dashoffset`` for flowing streams, ``rotate`` for turning glyphs, an opacity pulse for
combustion - so a saved file animates in any browser with nothing loaded alongside it.

PRD 19.4 is the mandatory, *testable* half: every animated element is a computed function of the
one state object the numeric panels also read - never a prerecorded loop or a hard-coded constant
(AC-21 extends the no-hard-coding audit to this code path). This module keeps that promise
structural rather than aspirational by splitting into three layers:

* **Geometry** - where a node sits on the canvas and how a duct curves between two nodes. This is
  the *shape of the drawing*, not a process or animation quantity, so - exactly like the colours
  and type sizes in :mod:`src.visualization.theme` - it lives here as documented code constants.
  ``layout.py`` deliberately carries no coordinates; a viewBox position is a rendering fact.
* **State -> animation** - :func:`flow_anim`, :func:`glyph_anim` and :func:`glow_anim` turn a
  :class:`~src.digital_twin.provenance.Value` into a period, an opacity, a particle count, a
  rotation rate. These functions contain **no animation magnitude of their own**: every output is
  ``AnimationSettings.scale(pair, value.fraction_of_range())`` for a ``pair`` read from
  ``configs/dashboard.yaml``. The only bare numbers they may hold are structural (a full turn is
  ``360``; a stream needs at least one particle) - the audit of this path finds a config lookup or
  a state fraction behind every parameter that changes what the animation *shows*.
* **SVG emission** - pure string builders that place the geometry, paint it with a
  :mod:`theme` colour, and attach the computed animation. They read state only through the layer
  above, so a panel can render but can never invent a limit or a speed.

:func:`animation_report` exposes the middle layer as plain data, which is what the AC-21 test
asserts against: double a feed rate and the stream's period must fall and its particle count rise,
drop a tag from the payload and its stream must read stopped - all without parsing SVG.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Final, Mapping, Sequence

from src import labels
from src.digital_twin import layout
from src.digital_twin.payloads import EquipmentStatus, StateSnapshot
from src.digital_twin.provenance import Status, Value
from src.digital_twin.settings import AnimationSettings, DashboardSettings, FormatSettings
from src.visualization import theme

# =============================================================================
# Geometry - the shape of the diagram (a design-token concern; see the module
# docstring and theme.py for why coordinates are code constants, not YAML).
# =============================================================================
#: The drawing canvas. Every coordinate below is in these user units, so the panel scales as one
#: piece to whatever width the notebook gives it (the SVG carries no pixel size of its own).
VIEWBOX_W: Final = 1040.0
VIEWBOX_H: Final = 640.0


@dataclass(frozen=True, slots=True)
class Point:
    """A point on the canvas."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class NodeGeom:
    """Where one node sits, and whether it is drawn as a turning glyph or a boundary terminal."""

    point: Point
    shape: str  # "glyph" (PRD 8.3 equipment) | "terminal" (a stream boundary)
    rotor: bool = False


#: Glyph and terminal sizes. Geometry, shared by every component so the diagram reads evenly.
#: (These, and the stroke widths below, feed SVG geometry attributes - not CSS - so they are plain
#: user-space numbers, never ``var(--dt-*)``: a custom property resolves in a CSS property, not in a
#: presentation attribute like ``rx`` or ``fill``.)
GLYPH_R: Final = 27.0
GLYPH_CORNER: Final = 7.0
GLYPH_STROKE: Final = 2.0
ROTOR_R: Final = 17.0
GLOW_R: Final = 44.0
TERMINAL_W: Final = 96.0
TERMINAL_H: Final = 34.0
TERMINAL_STROKE: Final = 1.0
LABEL_DY: Final = 15.0
SUB_DY: Final = 29.0
_SPOKES: Final = 6

#: The nine PRD 8.3 components, laid out as a clockwise serpentine: the kiln line runs left to
#: right along the top, the clinker silo bridges down the right edge, and the mill line runs right
#: to left along the bottom - which keeps the main clinker path short and lets the drawing read in
#: process order. Which of them turn (a rotary kiln, a mill drum, a separator rotor, the fans) is a
#: property of the real machine, not of the picture, so it is recorded here once.
_EQUIPMENT_XY: Final[Mapping[str, tuple[float, float]]] = {
    "Preheater": (200.0, 196.0),
    "Precalciner": (352.0, 196.0),
    "RotaryKiln": (536.0, 208.0),
    "Cooler": (724.0, 196.0),
    "FanFuel": (536.0, 330.0),
    "Mill": (724.0, 452.0),
    "Separator": (520.0, 452.0),
    "FanFilter": (724.0, 566.0),
    "Product": (340.0, 452.0),
}

#: The six stream boundaries (PRD 8.2), drawn as labelled terminals rather than equipment: the twin
#: models the stream that crosses the boundary, not the quarry, fuel yard or packing plant behind it.
_BOUNDARY_XY: Final[Mapping[str, tuple[float, float]]] = {
    layout.FEED_NODE: (74.0, 196.0),
    layout.STACK_NODE: (200.0, 74.0),
    layout.FUEL_NODE: (404.0, 74.0),
    layout.AIR_NODE: (560.0, 74.0),
    layout.SILO_NODE: (940.0, 330.0),
    layout.OUTPUT_NODE: (120.0, 452.0),
}

#: Components whose motion the twin animates as a rotation, each driven by its own ``driver`` tag
#: (:data:`~src.digital_twin.layout.EQUIPMENT`): the kiln and mill turn, the separator and the two
#: fans spin, the cooler runs its grate fans. The preheater cyclones, precalciner and product silo
#: have no turning part and are drawn static (the precalciner instead glows, below).
_ROTORS: Final[frozenset[str]] = frozenset(
    {"RotaryKiln", "Cooler", "FanFuel", "Mill", "Separator", "FanFilter"}
)

NODES: Final[Mapping[str, NodeGeom]] = {
    **{
        name: NodeGeom(Point(*xy), "glyph", name in _ROTORS)
        for name, xy in _EQUIPMENT_XY.items()
    },
    **{name: NodeGeom(Point(*xy), "terminal") for name, xy in _BOUNDARY_XY.items()},
}

#: Per-stream curvature: the signed perpendicular offset of a duct's control point, as a fraction
#: of its straight length. Zero is a straight run; a value bows the duct aside so recirculation
#: loops (separator reject, secondary-air recuperation), the tertiary-air bypass over the kiln, and
#: the two long additive feeds read as separate lines instead of overlapping. Pure drawing.
_CURVE: Final[Mapping[str, float]] = {
    "kiln_fuel": 0.12,
    "calciner_fuel": -0.12,
    "secondary_air": 0.26,
    "tertiary_air": -0.42,
    "clinker_to_silo": 0.10,
    "clinker_to_mill": 0.10,
    "gypsum_to_mill": 0.30,
    "additive_to_mill": 0.46,
    "mill_to_separator": -0.16,
    "separator_reject": 0.34,
    "filter_to_stack": -0.30,
}

#: Which tag lights each combustion glow. The rotary kiln glows with its burning-zone temperature
#: (not its rotation-driver ``kiln_speed_rpm``); the precalciner with its calcining temperature.
GLOW_SOURCES: Final[Mapping[str, str]] = {
    "RotaryKiln": "burning_zone_temperature",
    "Precalciner": "calciner_temperature",
}

#: One hue per stream kind, drawn from the theme so a duct is never painted with a bare hex. These
#: are category colours (material/fuel/air/gas/product), the P&ID convention; a stream whose rate
#: is in warning or alarm is overpainted with its alarm colour instead (:func:`_flow_color`).
_KIND_TOKEN: Final[Mapping[str, str]] = {
    "material": "accent",
    "fuel": "accent_alt",
    "air": "no_limit",
    "gas": "unknown",
    "product": "recommendation",
}

#: Legend wording for the stream kinds. Generic UI words (not mandated PRD strings), kept beside the
#: colour map they label.
_KIND_TITLE: Final[Mapping[str, str]] = {
    "material": "Material",
    "fuel": "Fuel",
    "air": "Air",
    "gas": "Gas",
    "product": "Product",
}

#: Sampling resolution used to measure a curved duct's on-screen length (for particle spacing). A
#: geometry constant - more samples is a smoother length estimate, nothing a panel displays.
_LENGTH_SAMPLES: Final = 24


# -- curve maths (geometry only) ------------------------------------------------------------
def _perp_unit(start: Point, end: Point) -> tuple[float, float]:
    """Unit vector perpendicular to the chord ``start -> end`` (the direction a duct bows in)."""
    dx, dy = end.x - start.x, end.y - start.y
    length = hypot(dx, dy) or 1.0
    return (-dy / length, dx / length)


def _control_point(start: Point, end: Point, curve: float) -> Point:
    """The quadratic-Bezier control point that bows ``start -> end`` aside by ``curve``."""
    mid_x, mid_y = (start.x + end.x) / 2.0, (start.y + end.y) / 2.0
    ux, uy = _perp_unit(start, end)
    chord = hypot(end.x - start.x, end.y - start.y)
    return Point(mid_x + ux * curve * chord, mid_y + uy * curve * chord)


def _bezier_point(start: Point, control: Point, end: Point, t: float) -> tuple[float, float]:
    """A point at parameter ``t`` along the quadratic Bezier."""
    mt = 1.0 - t
    x = mt * mt * start.x + 2.0 * mt * t * control.x + t * t * end.x
    y = mt * mt * start.y + 2.0 * mt * t * control.y + t * t * end.y
    return (x, y)


def _bezier_length(start: Point, control: Point, end: Point) -> float:
    """Approximate on-screen length of the curve, by summing a short polyline through it."""
    pts = [
        _bezier_point(start, control, end, i / _LENGTH_SAMPLES)
        for i in range(_LENGTH_SAMPLES + 1)
    ]
    return sum(
        hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(_LENGTH_SAMPLES)
    )


def _path_d(start: Point, control: Point, end: Point) -> str:
    """The SVG ``d`` for one curved duct."""
    return (
        f"M{start.x:.1f},{start.y:.1f} "
        f"Q{control.x:.1f},{control.y:.1f} {end.x:.1f},{end.y:.1f}"
    )


# =============================================================================
# State -> animation. Every field below is scale(pair, fraction_of_range()); the
# only bare numbers are structural (a full turn, at least one particle). This is
# the code path AC-21 audits - there is no animation magnitude hard-coded here.
# =============================================================================
@dataclass(frozen=True, slots=True)
class FlowAnim:
    """The computed animation of one stream: how fast, how dense, how bright, how thick."""

    fraction: float | None
    moving: bool
    period_s: float
    particles: int
    opacity: float
    width: float
    status: Status


def flow_anim(value: Value | None, animation: AnimationSettings) -> FlowAnim:
    """Bind one stream's animation to its rate reading (PRD 19.4 material/gas/fuel/air flow).

    ``value`` is the stream's ``rate_tag`` as the snapshot reports it. Everything visible about the
    stream is a function of ``value.fraction_of_range()``: the dash cycle shortens as the rate
    rises (it moves faster), the particle count and stroke thicken, the whole stream brightens. A
    missing reading has no fraction, so :meth:`AnimationSettings.scale` returns each range's
    at-rest end and :meth:`~AnimationSettings.moving` is false - the stream is drawn stopped, never
    at an invented speed.
    """
    fraction = value.fraction_of_range() if value is not None else None
    return FlowAnim(
        fraction=fraction,
        moving=animation.moving(fraction),
        period_s=animation.scale(animation.flow_period_seconds, fraction),
        particles=max(1, round(animation.scale(animation.particles, fraction))),
        opacity=animation.scale(animation.flow_opacity, fraction),
        width=animation.scale(animation.stroke_width, fraction),
        status=value.status if value is not None else Status.UNKNOWN,
    )


@dataclass(frozen=True, slots=True)
class GlyphAnim:
    """The computed animation of one equipment glyph: whether and how fast it turns."""

    fraction: float | None
    rotating: bool
    rotation_period_s: float
    status: Status


def glyph_anim(
    driver: Value | None, animation: AnimationSettings, *, rotor: bool
) -> GlyphAnim:
    """Bind an equipment glyph's rotation to its driving variable (PRD 19.4 rotation rate).

    A rotor turns with ``driver.fraction_of_range()`` - a faster kiln, a faster mill, a faster
    separator visibly spins faster. A glyph with no turning part (``rotor`` false), or one whose
    driver is missing or below the moving threshold, is drawn still: the period is still computed
    so the report can show it, but :attr:`rotating` gates whether any motion is emitted.
    """
    fraction = driver.fraction_of_range() if driver is not None else None
    return GlyphAnim(
        fraction=fraction,
        rotating=rotor and animation.moving(fraction),
        rotation_period_s=animation.scale(animation.rotation_period_seconds, fraction),
        status=driver.status if driver is not None else Status.UNKNOWN,
    )


@dataclass(frozen=True, slots=True)
class GlowAnim:
    """The computed combustion glow: its intensity and its pulse cadence."""

    fraction: float | None
    active: bool
    opacity: float
    floor: float
    pulse_period_s: float


def glow_anim(value: Value | None, animation: AnimationSettings) -> GlowAnim:
    """Bind a combustion glow to its temperature (PRD 19.4 combustion-glow intensity).

    The glow's peak opacity is ``scale(glow_opacity, fraction)`` of the burning-zone (or calcining)
    temperature, and it pulses between the range's floor and that peak at a cadence that quickens
    with the same fraction. A cold or missing zone has no fraction, so the glow sits at its floor
    and does not pulse - the ember fades rather than freezing at a made-up brightness.
    """
    fraction = value.fraction_of_range() if value is not None else None
    return GlowAnim(
        fraction=fraction,
        active=animation.moving(fraction),
        opacity=animation.scale(animation.glow_opacity, fraction),
        floor=float(animation.glow_opacity[0]),
        pulse_period_s=animation.scale(animation.flow_period_seconds, fraction),
    )


# =============================================================================
# SVG emission (reads state only through the layer above)
# =============================================================================
def _flow_color(kind: str, status: Status, palette: theme.Palette) -> str:
    """A stream's colour: its alarm colour when its rate is out of band, else its kind colour."""
    if status in (Status.WARN, Status.ALARM):
        return theme.status_color(status, palette)
    return getattr(palette, _KIND_TOKEN.get(kind, "accent"))


def _flow_svg(
    flow: layout.FlowSpec, anim: FlowAnim, palette: theme.Palette, *, animate: bool
) -> str:
    """One animated (or, when stopped, static) duct between two nodes."""
    start = NODES[flow.source].point
    end = NODES[flow.target].point
    control = _control_point(start, end, _CURVE.get(flow.name, 0.0))
    path_d = _path_d(start, control, end)
    color = _flow_color(flow.kind, anim.status, palette)
    tip = theme.html(f"{flow.title} - {_KIND_TITLE.get(flow.kind, flow.kind)}")
    base = (
        f"stroke:{color};stroke-width:{anim.width:.2f}px;opacity:{anim.opacity:.3f}"
    )
    if not (animate and anim.moving):
        # Idle pipe: a faint solid line at the range's at-rest end - still state-scaled, not moving.
        return (
            f'<path class="dt-flow dt-flow--idle" d="{path_d}" style="{base}">'
            f"<title>{tip}</title></path>"
        )
    length = _bezier_length(start, control, end)
    dot = anim.width  # a round dash one stroke-width long renders as a particle (linecap:round)
    cycle = length / anim.particles
    gap = max(cycle - dot, dot)
    dash_period = dot + gap
    style = (
        f"{base};stroke-dasharray:{dot:.2f} {gap:.2f};"
        f"--dt-dash:{dash_period:.2f}px;animation-duration:{anim.period_s:.2f}s"
    )
    return (
        f'<path class="dt-flow dt-flow--live" d="{path_d}" style="{style}">'
        f"<title>{tip}</title></path>"
    )


def _rotor_svg(center: Point, period_s: float, color: str, *, rotating: bool) -> str:
    """A hub-and-spokes rotor, spinning when ``rotating`` (CSS turns the group about its centre)."""
    spokes = "".join(
        f'<line x1="{center.x - ROTOR_R:.1f}" y1="{center.y:.1f}" '
        f'x2="{center.x + ROTOR_R:.1f}" y2="{center.y:.1f}" '
        f'transform="rotate({i * 180.0 / _SPOKES:.1f} {center.x:.1f} {center.y:.1f})"/>'
        for i in range(_SPOKES)
    )
    hub = f'<circle cx="{center.x:.1f}" cy="{center.y:.1f}" r="{ROTOR_R:.1f}" fill="none"/>'
    if rotating:
        open_g = (
            f'<g class="dt-rotor" stroke="{color}" '
            f'style="transform-origin:{center.x:.1f}px {center.y:.1f}px;'
            f'animation-duration:{period_s:.2f}s">'
        )
    else:
        open_g = f'<g stroke="{color}">'
    return f"{open_g}{hub}{spokes}</g>"


def _glow_svg(center: Point, glow: GlowAnim, *, animate: bool) -> str:
    """A combustion halo behind a burner glyph, pulsing when the zone is hot."""
    if animate and glow.active:
        style = (
            f"--dt-glow-lo:{glow.floor:.3f};--dt-glow-hi:{glow.opacity:.3f};"
            f"opacity:{glow.opacity:.3f};animation-duration:{glow.pulse_period_s:.2f}s"
        )
        cls = "dt-glow dt-glow--pulse"
    else:
        style = f"opacity:{glow.opacity:.3f}"
        cls = "dt-glow"
    return (
        f'<circle class="{cls}" cx="{center.x:.1f}" cy="{center.y:.1f}" r="{GLOW_R:.1f}" '
        f'fill="url(#dt-glow-grad)" style="{style}"/>'
    )


def _glyph_svg(
    status: EquipmentStatus,
    anim: GlyphAnim,
    glow: GlowAnim | None,
    palette: theme.Palette,
    fmt: FormatSettings,
    *,
    animate: bool,
) -> str:
    """One equipment glyph: optional combustion glow, a status-coloured housing, a rotor if it
    turns, and its name, state word and live driver reading beneath."""
    geom = NODES[status.name]
    center = geom.point
    outline = theme.status_color(status.status, palette)
    spec = layout.equipment_spec(status.name)
    parts: list[str] = ['<g class="dt-glyph">']
    if glow is not None:
        parts.append(_glow_svg(center, glow, animate=animate))
    parts.append(
        f'<rect x="{center.x - GLYPH_R:.1f}" y="{center.y - GLYPH_R:.1f}" '
        f'width="{2 * GLYPH_R:.1f}" height="{2 * GLYPH_R:.1f}" rx="{GLYPH_CORNER:.1f}" '
        f'fill="{palette.surface_alt}" stroke="{outline}" stroke-width="{GLYPH_STROKE:.1f}"/>'
    )
    if geom.rotor:
        parts.append(
            _rotor_svg(center, anim.rotation_period_s, outline, rotating=animate and anim.rotating)
        )
    reading = theme.value_text(status.driver, fmt) if status.driver is not None else theme.NO_VALUE_TEXT
    label_y = center.y + GLYPH_R + LABEL_DY
    sub_y = center.y + GLYPH_R + SUB_DY
    parts.append(
        f'<text class="dt-glyph-name" x="{center.x:.1f}" y="{label_y:.1f}" '
        f'text-anchor="middle">{theme.html(spec.title)}</text>'
    )
    parts.append(
        f'<text class="dt-glyph-sub" x="{center.x:.1f}" y="{sub_y:.1f}" '
        f'text-anchor="middle">{theme.html(status.state)} · {theme.html(reading)}</text>'
    )
    parts.append("</g>")
    return "".join(parts)


def _terminal_svg(name: str, palette: theme.Palette) -> str:
    """A boundary terminal: a labelled tag where a stream enters or leaves the modelled plant."""
    center = NODES[name].point
    x = center.x - TERMINAL_W / 2.0
    y = center.y - TERMINAL_H / 2.0
    return (
        f'<g class="dt-terminal">'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{TERMINAL_W:.1f}" height="{TERMINAL_H:.1f}" '
        f'rx="{TERMINAL_H / 2.0:.1f}" fill="{palette.surface}" '
        f'stroke="{palette.border}" stroke-width="{TERMINAL_STROKE:.1f}"/>'
        f'<text class="dt-terminal-label" x="{center.x:.1f}" y="{center.y:.1f}" '
        f'text-anchor="middle" dominant-baseline="central">{theme.html(name)}</text>'
        f"</g>"
    )


def _legend_html(palette: theme.Palette) -> str:
    """A compact swatch legend for the stream kinds."""
    chips = "".join(
        f'<span class="dt-twin__legend-item">'
        f'<span class="dt-twin__swatch" style="background:{getattr(palette, token)}"></span>'
        f"{theme.html(_KIND_TITLE[kind])}</span>"
        for kind, token in _KIND_TOKEN.items()
    )
    return f'<div class="dt-twin__legend">{chips}</div>'


def _defs(palette: theme.Palette) -> str:
    """The one shared radial gradient every combustion glow paints with."""
    glow = palette.accent_alt
    return (
        '<defs><radialGradient id="dt-glow-grad">'
        f'<stop offset="0%" stop-color="{glow}" stop-opacity="1"/>'
        f'<stop offset="100%" stop-color="{glow}" stop-opacity="0"/>'
        "</radialGradient></defs>"
    )


# =============================================================================
# Assembly
# =============================================================================
def _svg(
    snapshot: StateSnapshot,
    equipment: Sequence[EquipmentStatus],
    animation: AnimationSettings,
    palette: theme.Palette,
    fmt: FormatSettings,
    *,
    animate: bool,
) -> str:
    """The ``<svg>`` element: ducts (behind), then terminals, then equipment glyphs (in front)."""
    flows = "".join(
        _flow_svg(flow, flow_anim(snapshot.value(flow.rate_tag), animation), palette, animate=animate)
        for flow in layout.FLOWS
    )
    terminals = "".join(_terminal_svg(name, palette) for name in layout.boundary_nodes())
    glyphs_out: list[str] = []
    for status in equipment:
        if status.name not in NODES:  # defensive: only PRD 8.3 components are placed
            continue
        geom = NODES[status.name]
        anim = glyph_anim(status.driver, animation, rotor=geom.rotor)
        glow_tag = GLOW_SOURCES.get(status.name)
        glow = glow_anim(snapshot.value(glow_tag), animation) if glow_tag else None
        glyphs_out.append(_glyph_svg(status, anim, glow, palette, fmt, animate=animate))
    aria = theme.html(f"Animated process twin - {snapshot.mode} - {snapshot.timestamp}")
    return (
        f'<svg class="dt-twin__svg" viewBox="0 0 {VIEWBOX_W:.0f} {VIEWBOX_H:.0f}" '
        f'role="img" aria-label="{aria}" xmlns="http://www.w3.org/2000/svg">'
        f"{_defs(palette)}"
        f'<g class="dt-flows">{flows}</g>'
        f'<g class="dt-terminals">{terminals}</g>'
        f'<g class="dt-glyphs">{"".join(glyphs_out)}</g>'
        f"</svg>"
    )


def _header_html(snapshot: StateSnapshot, title: str | None) -> str:
    """The title strip: heading, the standing Synthetic-Demonstration badge, and the live stamp."""
    heading = theme.html(title or labels.SYSTEM_NAME)
    badge = theme.html(labels.SYNTHETIC_DEMONSTRATION_LABEL)
    provenance = theme.html(theme.provenance_label(snapshot.provenance))
    stamp = theme.html(f"{snapshot.mode} · {snapshot.timestamp}")
    return (
        f'<div class="dt-twin__head">'
        f'<div class="dt-twin__title">{heading}</div>'
        f'<div class="dt-twin__meta">'
        f'<span class="dt-badge dt-badge--configuration">{badge}</span>'
        f'<span class="dt-badge dt-badge--observed">{provenance}</span>'
        f'<span class="dt-mono dt-muted">{stamp}</span>'
        f"</div></div>"
    )


def render_twin(
    snapshot: StateSnapshot,
    equipment: Sequence[EquipmentStatus],
    *,
    settings: DashboardSettings,
    theme_name: str = theme.DARK,
    animate: bool = True,
    title: str | None = None,
) -> str:
    """The animated twin as a themed HTML fragment (PRD 19.3/19.4).

    ``snapshot`` and ``equipment`` are the very objects the numeric panels read - the twin adds no
    second source. ``animate`` off renders the same state as a still frame (for a paused clock or a
    snapshot test); the widths, colours and glow intensities still reflect the state, only the
    motion is withheld. The fragment carries its own scoped ``<style>`` (the keyframes) but draws
    every colour and size from the theme variables, so it must sit inside a themed root - use
    :func:`twin_html` or :func:`twin_document` to display or export it on its own.
    """
    palette = theme.theme(theme_name)
    body = _svg(snapshot, equipment, settings.animation, palette, settings.format, animate=animate)
    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{twin_style()}"
        f'<div class="dt-twin">'
        f"{_header_html(snapshot, title)}"
        f"{body}"
        f"{_legend_html(palette)}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        f"</div></div>"
    )


def animation_report(
    snapshot: StateSnapshot,
    equipment: Sequence[EquipmentStatus],
    settings: DashboardSettings,
) -> dict:
    """The state -> animation binding as plain data - the surface the AC-21 test asserts against.

    Every number here came from :func:`flow_anim`/:func:`glyph_anim`/:func:`glow_anim`, i.e. from
    ``scale(pair, fraction_of_range())``. A test can drive the provider, read this, and check that
    a higher rate gives a shorter period and more particles, and that a tag absent from the payload
    reads ``moving: false`` at the at-rest ends - proving the animation is a function of state
    without rendering or parsing any SVG.
    """
    animation = settings.animation
    flows = []
    for flow in layout.FLOWS:
        anim = flow_anim(snapshot.value(flow.rate_tag), animation)
        flows.append(
            {
                "flow": flow.name,
                "rate_tag": flow.rate_tag,
                "kind": flow.kind,
                "fraction": anim.fraction,
                "moving": anim.moving,
                "period_s": anim.period_s,
                "particles": anim.particles,
                "opacity": anim.opacity,
                "width": anim.width,
                "status": str(anim.status),
            }
        )
    equip = []
    for status in equipment:
        geom = NODES.get(status.name)
        anim = glyph_anim(status.driver, animation, rotor=bool(geom and geom.rotor))
        row: dict = {
            "name": status.name,
            "state": status.state,
            "status": str(anim.status),
            "rotor": bool(geom and geom.rotor),
            "rotating": anim.rotating,
            "rotation_period_s": anim.rotation_period_s,
            "fraction": anim.fraction,
        }
        glow_tag = GLOW_SOURCES.get(status.name)
        if glow_tag:
            glow = glow_anim(snapshot.value(glow_tag), animation)
            row["glow"] = {
                "source": glow_tag,
                "active": glow.active,
                "opacity": glow.opacity,
                "pulse_period_s": glow.pulse_period_s,
                "fraction": glow.fraction,
            }
        equip.append(row)
    return {
        "viewBox": [0.0, 0.0, VIEWBOX_W, VIEWBOX_H],
        "flows": flows,
        "equipment": equip,
    }


# -- scoped stylesheet (the CSS motion; reads theme variables, defines no colour) -----------
def stylesheet() -> str:
    """The twin's scoped CSS: the layout of the panel and the three keyframes that move it.

    It defines no colour or size of its own - every value is a ``var(--dt-*)`` from
    :func:`src.visualization.theme.stylesheet`, so the twin restyles with the theme and the
    no-hard-coding audit still finds one home for a token. The motion is three keyframes: a dash
    that slides one cycle (flowing streams), a group that turns a full circle (rotors), and an
    opacity that breathes between a floor and a peak (combustion).
    """
    r = theme.ROOT_CLASS
    return f"""
.{r} .dt-twin{{display:flex;flex-direction:column;gap:var(--dt-gap-sm);}}
.{r} .dt-twin__head{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:var(--dt-gap-sm);}}
.{r} .dt-twin__title{{font-size:var(--dt-size-readout);font-weight:600;}}
.{r} .dt-twin__meta{{display:flex;flex-wrap:wrap;gap:var(--dt-gap-sm);align-items:center;}}
.{r} .dt-twin__svg{{width:100%;height:auto;display:block;background:var(--dt-bg);
  border:var(--dt-border-width) solid var(--dt-border);border-radius:var(--dt-radius);}}
.{r} .dt-twin__legend{{display:flex;flex-wrap:wrap;gap:var(--dt-gap);font-size:var(--dt-size-label);color:var(--dt-text-muted);}}
.{r} .dt-twin__legend-item{{display:inline-flex;align-items:center;gap:var(--dt-gap-sm);}}
.{r} .dt-twin__swatch{{width:.8em;height:.8em;border-radius:2px;display:inline-block;}}

.{r} .dt-flow{{fill:none;stroke-linecap:round;}}
.{r} .dt-flow--live{{animation-name:dt-flow-move;animation-timing-function:linear;animation-iteration-count:infinite;}}
.{r} .dt-glyph-name{{fill:var(--dt-text);font-family:var(--dt-font-sans);font-size:var(--dt-size-label);font-weight:600;}}
.{r} .dt-glyph-sub{{fill:var(--dt-text-muted);font-family:var(--dt-font-mono);font-size:var(--dt-size-micro);}}
.{r} .dt-terminal-label{{fill:var(--dt-text-muted);font-family:var(--dt-font-sans);font-size:var(--dt-size-micro);letter-spacing:.02em;}}

.{r} .dt-rotor{{transform-box:view-box;animation-name:dt-spin;animation-timing-function:linear;animation-iteration-count:infinite;}}
.{r} .dt-glow--pulse{{animation-name:dt-glow-pulse;animation-timing-function:ease-in-out;animation-iteration-count:infinite;}}

@keyframes dt-flow-move{{to{{stroke-dashoffset:calc(-1 * var(--dt-dash));}}}}
@keyframes dt-spin{{to{{transform:rotate(360deg);}}}}
@keyframes dt-glow-pulse{{0%,100%{{opacity:var(--dt-glow-lo);}}50%{{opacity:var(--dt-glow-hi);}}}}

@media (prefers-reduced-motion: reduce){{
  .{r} .dt-flow--live,.{r} .dt-rotor,.{r} .dt-glow--pulse{{animation:none;}}
}}
""".strip()


def twin_style() -> str:
    """The twin stylesheet wrapped in a ``<style>`` element, ready to embed in the fragment."""
    return f"<style>{stylesheet()}</style>"


def twin_html(
    snapshot: StateSnapshot,
    equipment: Sequence[EquipmentStatus],
    *,
    settings: DashboardSettings,
    theme_name: str = theme.DARK,
    animate: bool = True,
    title: str | None = None,
) -> str:
    """The twin as a self-contained fragment including the theme stylesheet.

    This is what ``IPython.display.HTML`` should be handed to show the twin on its own: it prepends
    :func:`src.visualization.theme.style_tag` so the ``var(--dt-*)`` the fragment references are
    defined. Inside the full dashboard, which emits the theme stylesheet once, use
    :func:`render_twin` instead to avoid repeating it.
    """
    return theme.style_tag() + render_twin(
        snapshot, equipment, settings=settings, theme_name=theme_name, animate=animate, title=title
    )


def twin_document(
    snapshot: StateSnapshot,
    equipment: Sequence[EquipmentStatus],
    *,
    settings: DashboardSettings,
    theme_name: str = theme.DARK,
    animate: bool = True,
    title: str | None = None,
) -> str:
    """A complete standalone ``.html`` document for the factory demo (PRD 19.3/29 export).

    Everything is inlined - the theme stylesheet, the twin CSS, the SVG - so the saved file
    animates in any browser with no assets, no server and no network (NFR-9).
    """
    heading = theme.html(title or labels.full_system_label())
    fragment = twin_html(
        snapshot, equipment, settings=settings, theme_name=theme_name, animate=animate, title=title
    )
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{heading}</title>"
        '</head><body style="margin:0">'
        f"{fragment}"
        "</body></html>"
    )


__all__ = [
    "VIEWBOX_W",
    "VIEWBOX_H",
    "NODES",
    "GLOW_SOURCES",
    "Point",
    "NodeGeom",
    "FlowAnim",
    "GlyphAnim",
    "GlowAnim",
    "flow_anim",
    "glyph_anim",
    "glow_anim",
    "animation_report",
    "render_twin",
    "stylesheet",
    "twin_style",
    "twin_html",
    "twin_document",
]
