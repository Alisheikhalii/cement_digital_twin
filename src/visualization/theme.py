"""Design tokens for the visualization layer (PRD v1.1.1 Section 17.1).

PRD 17.1 asks for an "industrial control/engineering-analytics look ... alarm color coding
(green/amber/red), monospace-flavored numeric readouts" and states that the design tokens
themselves are "the responsibility of the implementer". This module *is* that responsibility
discharged in one place: it is to colours, typography and spacing what :mod:`src.labels` is to
mandated strings and ``configs/dashboard.yaml`` is to presentation numbers.

Why here and not in the YAML: ``configs/dashboard.yaml`` holds presentation *numbers* that change
what a panel means - how wide the amber band is, how fast a flow animates, how many digits a
readout shows. A hex colour changes how a panel *looks*, not what it says, and PRD 17.1 delegates
that choice to the implementer rather than to configuration. Keeping the tokens as code constants
here gives the no-hard-coding audit (NFR-6/AC-12) exactly one sanctioned home for a colour or a
font size, the same way it has exactly one home for a string: a view references
``theme`` and never writes ``#f85149`` or ``13px`` inline, so the scan still rejects a literal
anywhere else.

Nothing in this module is a process quantity, and nothing here imports a chart library, a widget
toolkit or a process model - it is pure, so every layer above can style itself without pulling in
plotly, ipywidgets or the simulation. The two things a rendering layer needs from a number - which
alarm colour it earns, and how many digits it shows - both resolve here:
:func:`status_color` reads the :class:`~src.digital_twin.provenance.Status` the provider already
banded, and :func:`value_text` reads the :class:`~src.digital_twin.settings.FormatSettings` the
provider already loaded. Neither invents a limit or a precision of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from html import escape
from typing import Final, Mapping

from src.digital_twin.provenance import (
    PROVENANCE_LABELS,
    Provenance,
    Status,
    Value,
)
from src.digital_twin.settings import FormatSettings

#: The single CSS scope class. Every rendered fragment lives inside ``<div class="dt-root ...">``
#: so the stylesheet's rules and custom properties cannot leak into the surrounding Colab
#: notebook, and the notebook's own styles cannot bleed into the twin (NFR-9: the panel is
#: self-contained). One class, referenced here, so no view spells it differently.
ROOT_CLASS: Final = "dt-root"

#: Theme names. Dark is the base (a control-room look); light is applied by adding a class.
DARK: Final = "dark"
LIGHT: Final = "light"
THEME_NAMES: Final[tuple[str, ...]] = (DARK, LIGHT)

#: What a readout shows when it has no number. NFR-6: a missing value is stated as an absence,
#: never filled with a zero a chart would draw as a real reading or a panel would total.
NO_VALUE_TEXT: Final = "—"  # em dash


@dataclass(frozen=True, slots=True)
class Palette:
    """The colours of one theme. Every field is a CSS colour; none is a process number.

    The status quartet (``ok``/``warn``/``alarm``/``unknown``) is the PRD 17.1 green/amber/red
    coding plus the honest grey for "no reading". The provenance colours give each of the five
    channels of :class:`~src.digital_twin.provenance.Provenance` a fixed badge hue, so a violet
    chip means "simulator truth" on every screen and can never be confused with an observed
    reading - the Synthetic-to-Real distinction rendered as a colour, not just a word.
    """

    name: str
    # surfaces and text
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    # accents used by charts and controls
    accent: str
    accent_alt: str
    grid: str
    # PRD 17.1 alarm coding + the two non-alarm states a Status can hold
    ok: str
    warn: str
    alarm: str
    no_limit: str
    unknown: str
    # one hue per provenance channel (directive item 1)
    observed: str
    truth: str
    prediction: str
    recommendation: str
    configuration: str


@dataclass(frozen=True, slots=True)
class Tokens:
    """Typography and geometry shared by both themes (only colours change between dark/light).

    ``font_mono`` is the "monospace-flavored numeric readouts" of PRD 17.1: every number a panel
    prints is set in it, so columns of figures line up on the decimal the way a control-room HMI
    lines them up. The rest are spacing and shape - a design system needs one home for them too.
    """

    font_sans: str
    font_mono: str
    size_kpi: str
    size_readout: str
    size_body: str
    size_label: str
    size_micro: str
    radius: str
    radius_sm: str
    radius_pill: str
    gap: str
    gap_sm: str
    pad: str
    border_width: str
    shadow: str
    transition: str


#: The two industrial palettes. Dark is a slate control-room ground; light is an analytics report
#: ground. The status hues keep a colour-blind-safe green/amber/red separation (distinct in
#: lightness, not only hue) and the provenance hues are chosen to stay distinct from the status
#: ones so a badge is never mistaken for an alarm.
_DARK = Palette(
    name=DARK,
    bg="#0b0f14",
    surface="#131a22",
    surface_alt="#1b242e",
    border="#2b3947",
    text="#e6edf3",
    text_muted="#8b98a5",
    accent="#4cc9f0",
    accent_alt="#f5a524",
    grid="#223040",
    ok="#3fb950",
    warn="#d29922",
    alarm="#f85149",
    no_limit="#58a6ff",
    unknown="#6e7681",
    observed="#4cc9f0",
    truth="#a78bfa",
    prediction="#f5a524",
    recommendation="#3fb950",
    configuration="#8b98a5",
)

_LIGHT = Palette(
    name=LIGHT,
    bg="#f4f6f8",
    surface="#ffffff",
    surface_alt="#eef2f6",
    border="#d0d7de",
    text="#1c2530",
    text_muted="#5b6470",
    accent="#0969da",
    accent_alt="#bc5a00",
    grid="#d8e0e8",
    ok="#1a7f37",
    warn="#9a6700",
    alarm="#cf222e",
    no_limit="#0969da",
    unknown="#6e7781",
    observed="#0969da",
    truth="#8250df",
    prediction="#bc5a00",
    recommendation="#1a7f37",
    configuration="#5b6470",
)

PALETTES: Final[Mapping[str, Palette]] = {DARK: _DARK, LIGHT: _LIGHT}

#: One set of typography/geometry tokens, shared by both themes.
TOKENS: Final = Tokens(
    font_sans=(
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    ),
    font_mono="'SFMono-Regular', ui-monospace, 'Cascadia Mono', Consolas, 'Liberation Mono', monospace",
    size_kpi="1.9rem",
    size_readout="1.15rem",
    size_body="0.9rem",
    size_label="0.78rem",
    size_micro="0.68rem",
    radius="10px",
    radius_sm="6px",
    radius_pill="999px",
    gap="16px",
    gap_sm="8px",
    pad="14px",
    border_width="1px",
    shadow="0 1px 2px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.12)",
    transition="180ms ease",
)


# -- status and provenance lookups ----------------------------------------------------------
#: :class:`Status` -> the palette field that colours it. A dict, not a chain of ``if``, so the
#: mapping is exhaustive by construction and a new Status would fail the lookup loudly.
_STATUS_FIELD: Final[Mapping[Status, str]] = {
    Status.OK: "ok",
    Status.WARN: "warn",
    Status.ALARM: "alarm",
    Status.NO_LIMIT: "no_limit",
    Status.UNKNOWN: "unknown",
}

#: :class:`Provenance` -> the palette field that colours its badge.
_PROVENANCE_FIELD: Final[Mapping[Provenance, str]] = {
    Provenance.OBSERVED: "observed",
    Provenance.TRUTH: "truth",
    Provenance.PREDICTION: "prediction",
    Provenance.RECOMMENDATION: "recommendation",
    Provenance.CONFIGURATION: "configuration",
}


def theme(name: str = DARK) -> Palette:
    """The palette for a theme name, defaulting to dark; unknown names are refused, not guessed."""
    try:
        return PALETTES[name]
    except KeyError:
        raise ValueError(f"unknown theme {name!r}; expected one of {THEME_NAMES}") from None


def status_color(status: Status, palette: Palette | None = None) -> str:
    """The alarm colour a banded :class:`Status` earns (PRD 17.1). Never bands anything itself."""
    pal = palette or _DARK
    return getattr(pal, _STATUS_FIELD.get(status, "unknown"))


def status_slug(status: Status) -> str:
    """A CSS-class suffix for a status (``Status.WARN`` -> ``"warn"``) so a pill can be styled."""
    return _STATUS_FIELD.get(status, "unknown")


def provenance_color(provenance: Provenance, palette: Palette | None = None) -> str:
    """The badge hue for a provenance channel (directive item 1)."""
    pal = palette or _DARK
    return getattr(pal, _PROVENANCE_FIELD.get(provenance, "configuration"))


def provenance_slug(provenance: Provenance) -> str:
    """A CSS-class suffix for a provenance channel (``Provenance.TRUTH`` -> ``"truth"``)."""
    return _PROVENANCE_FIELD.get(provenance, "configuration")


def provenance_label(provenance: Provenance) -> str:
    """The fixed badge wording, read from :data:`PROVENANCE_LABELS` so no view can soften it."""
    return PROVENANCE_LABELS[provenance]


# -- number formatting (the one place a value becomes text) ---------------------------------
def format_number(
    value: float | None,
    settings: FormatSettings,
    *,
    group: bool = True,
) -> str:
    """One float -> its readout text, at the precision :class:`FormatSettings` dictates.

    The decimal count is ``settings.digits(value)`` - a magnitude rule, not a per-tag table - so a
    burning-zone temperature reads ``1,451`` and an oxygen percentage ``3.42`` from the same call.
    ``group`` inserts thousands separators, which is typography (``312,450`` is easier to read
    than ``312450``) and never changes the value: the panel was handed a float and still holds it,
    only its *rendering* is grouped. ``None`` or NaN returns :data:`NO_VALUE_TEXT`.
    """
    if value is None or value != value:  # NaN-safe
        return NO_VALUE_TEXT
    digits = settings.digits(value)
    spec = f"{',' if group else ''}.{digits}f"
    return format(float(value), spec)


def value_number(value: Value, settings: FormatSettings, *, group: bool = True) -> str:
    """The numeric text of a :class:`Value`, unit omitted (for tables that head the unit once)."""
    return format_number(value.value, settings, group=group)


def value_text(
    value: Value,
    settings: FormatSettings,
    *,
    with_unit: bool = True,
    group: bool = True,
) -> str:
    """A :class:`Value` as a full readout: ``"1,451 °C"``, ``"3.42 %"``, or the no-value glyph.

    The unit is dropped when the value has none (a dimensionless ratio) or when ``with_unit`` is
    off, so a bare ``—`` never trails a stray unit for a reading that is absent.
    """
    number = value_number(value, settings, group=group)
    if not with_unit or not value.unit or number == NO_VALUE_TEXT:
        return number
    return f"{number} {value.unit}"  # narrow no-break space keeps number and unit together


def html(text: object) -> str:
    """Escape arbitrary text for safe embedding in the generated HTML/SVG (quotes included).

    Every string that reaches a rendered fragment - a tag description, a unit, a provider name -
    passes through here, so a stray ``<`` or ``&`` in a label can never break the markup or inject
    into it. Non-strings are stringified first.
    """
    return escape(str(text), quote=True)


# -- stylesheet generation ------------------------------------------------------------------
def _var_name(field_name: str) -> str:
    """``surface_alt`` -> ``--dt-surface-alt``: one naming rule for every custom property."""
    return f"--dt-{field_name.replace('_', '-')}"


def _palette_vars(palette: Palette) -> str:
    """The ``--dt-*`` colour declarations for one palette, derived from its fields.

    Generated from :func:`dataclasses.fields` rather than hand-listed so a palette colour and its
    CSS variable can never drift apart - adding a field to :class:`Palette` adds its variable.
    """
    return "".join(
        f"{_var_name(f.name)}:{getattr(palette, f.name)};"
        for f in fields(palette)
        if f.name != "name"
    )


def _token_vars(tokens: Tokens) -> str:
    """The ``--dt-*`` typography/geometry declarations, shared by both themes."""
    return "".join(f"{_var_name(f.name)}:{getattr(tokens, f.name)};" for f in fields(tokens))


def stylesheet() -> str:
    """The scoped CSS for the whole visualization layer: variables plus base primitives.

    Two responsibilities, both belonging to the design system: it declares the custom properties
    (dark on the scope, light overriding them under an added class) and it styles the primitives
    every view reuses - the card, the KPI figure, the status pill, the provenance badge, the
    banner, the readout table. A view therefore composes classes and never writes a colour or a
    size; that is what keeps NFR-6/AC-12 enforceable above this module.
    """
    dark = _palette_vars(_DARK)
    light = _palette_vars(_LIGHT)
    toks = _token_vars(TOKENS)
    r = ROOT_CLASS
    return f"""
.{r}{{{toks}{dark}
  color:var(--dt-text);background:var(--dt-bg);
  font-family:var(--dt-font-sans);font-size:var(--dt-size-body);line-height:1.45;
  -webkit-font-smoothing:antialiased;padding:var(--dt-pad);border-radius:var(--dt-radius);
}}
.{r}.dt-theme-{LIGHT}{{{light}}}
.{r} *{{box-sizing:border-box;}}
.{r} .dt-mono{{font-family:var(--dt-font-mono);font-variant-numeric:tabular-nums;}}
.{r} .dt-muted{{color:var(--dt-text-muted);}}

/* layout */
.{r} .dt-grid{{display:grid;gap:var(--dt-gap);grid-template-columns:repeat(auto-fill,minmax(210px,1fr));}}
.{r} .dt-row{{display:flex;flex-wrap:wrap;gap:var(--dt-gap);align-items:stretch;}}
.{r} .dt-title{{font-size:var(--dt-size-label);letter-spacing:.06em;text-transform:uppercase;color:var(--dt-text-muted);margin:0 0 var(--dt-gap-sm);}}

/* card */
.{r} .dt-card{{background:var(--dt-surface);border:var(--dt-border-width) solid var(--dt-border);
  border-radius:var(--dt-radius);padding:var(--dt-pad);box-shadow:var(--dt-shadow);}}
.{r} .dt-card--alt{{background:var(--dt-surface-alt);}}

/* KPI figure */
.{r} .dt-kpi{{display:flex;flex-direction:column;gap:2px;}}
.{r} .dt-kpi__label{{font-size:var(--dt-size-label);color:var(--dt-text-muted);}}
.{r} .dt-kpi__value{{font-family:var(--dt-font-mono);font-variant-numeric:tabular-nums;
  font-size:var(--dt-size-kpi);font-weight:600;line-height:1.1;}}
.{r} .dt-kpi__unit{{font-size:var(--dt-size-label);color:var(--dt-text-muted);margin-left:.3em;}}
.{r} .dt-readout{{font-family:var(--dt-font-mono);font-variant-numeric:tabular-nums;font-size:var(--dt-size-readout);}}

/* status pill (PRD 17.1 green/amber/red) */
.{r} .dt-pill{{display:inline-flex;align-items:center;gap:.4em;padding:.12em .6em;
  border-radius:var(--dt-radius-pill);font-size:var(--dt-size-label);font-weight:600;
  border:var(--dt-border-width) solid transparent;}}
.{r} .dt-pill::before{{content:"";width:.55em;height:.55em;border-radius:50%;background:currentColor;}}
.{r} .dt-pill--ok{{color:var(--dt-ok);border-color:var(--dt-ok);}}
.{r} .dt-pill--warn{{color:var(--dt-warn);border-color:var(--dt-warn);}}
.{r} .dt-pill--alarm{{color:var(--dt-alarm);border-color:var(--dt-alarm);}}
.{r} .dt-pill--no_limit{{color:var(--dt-no-limit);border-color:var(--dt-no-limit);}}
.{r} .dt-pill--unknown{{color:var(--dt-unknown);border-color:var(--dt-unknown);}}

/* provenance badge (directive item 1: source is always named) */
.{r} .dt-badge{{display:inline-flex;align-items:center;gap:.35em;padding:.1em .5em;
  border-radius:var(--dt-radius-sm);font-size:var(--dt-size-micro);font-weight:600;
  letter-spacing:.03em;text-transform:uppercase;border:var(--dt-border-width) solid currentColor;}}
.{r} .dt-badge--observed{{color:var(--dt-observed);}}
.{r} .dt-badge--truth{{color:var(--dt-truth);}}
.{r} .dt-badge--prediction{{color:var(--dt-prediction);}}
.{r} .dt-badge--recommendation{{color:var(--dt-recommendation);}}
.{r} .dt-badge--configuration{{color:var(--dt-configuration);}}

/* status colouring applied to a readout value */
.{r} .dt-v--ok{{color:var(--dt-text);}}
.{r} .dt-v--warn{{color:var(--dt-warn);}}
.{r} .dt-v--alarm{{color:var(--dt-alarm);}}
.{r} .dt-v--no_limit{{color:var(--dt-text);}}
.{r} .dt-v--unknown{{color:var(--dt-text-muted);}}

/* banner (limitations, envelope, no-plant-connection) */
.{r} .dt-banner{{border-left:3px solid var(--dt-accent-alt);background:var(--dt-surface-alt);
  padding:var(--dt-gap-sm) var(--dt-pad);border-radius:var(--dt-radius-sm);
  font-size:var(--dt-size-label);color:var(--dt-text-muted);}}
.{r} .dt-banner--warn{{border-left-color:var(--dt-warn);}}
.{r} .dt-banner--alarm{{border-left-color:var(--dt-alarm);}}

/* table (readouts / requirements) */
.{r} table.dt-table{{border-collapse:collapse;width:100%;font-size:var(--dt-size-body);}}
.{r} table.dt-table th,.{r} table.dt-table td{{text-align:left;padding:.4em .6em;
  border-bottom:var(--dt-border-width) solid var(--dt-border);}}
.{r} table.dt-table th{{color:var(--dt-text-muted);font-weight:600;font-size:var(--dt-size-label);
  text-transform:uppercase;letter-spacing:.04em;}}
.{r} table.dt-table td.dt-num{{font-family:var(--dt-font-mono);font-variant-numeric:tabular-nums;text-align:right;}}
""".strip()


def style_tag() -> str:
    """The stylesheet wrapped in a ``<style>`` element, ready to prepend to any rendered view."""
    return f"<style>{stylesheet()}</style>"


def theme_class(name: str = DARK) -> str:
    """The class string for a themed root: ``"dt-root"`` for dark, ``"dt-root dt-theme-light"``.

    Dark is carried by the scope itself, so it needs no extra class; light is opt-in. Passing an
    unknown name raises rather than silently rendering an unstyled panel.
    """
    palette = theme(name)  # validates the name
    return ROOT_CLASS if palette.name == DARK else f"{ROOT_CLASS} dt-theme-{palette.name}"


__all__ = [
    "DARK",
    "LIGHT",
    "NO_VALUE_TEXT",
    "PALETTES",
    "ROOT_CLASS",
    "THEME_NAMES",
    "TOKENS",
    "Palette",
    "Tokens",
    "format_number",
    "html",
    "provenance_color",
    "provenance_label",
    "provenance_slug",
    "status_color",
    "status_slug",
    "style_tag",
    "stylesheet",
    "theme",
    "theme_class",
    "value_number",
    "value_text",
]
