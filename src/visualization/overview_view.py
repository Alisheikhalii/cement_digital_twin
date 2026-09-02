"""View A — the Plant Overview — as plain HTML (PRD 17 view 1 / 18.1, items 3, 9, 12).

This is the renderer for the screen ``DashboardState.overview()`` builds — PRD §17's landing
view and AC-1's subject. It covers the three directive items that share view A:

* **item 3** — the five-stage ``Quarry/Feed → Kiln system → Clinker → Cement Mill → Cement
  Product`` chain, rendered from the ``stages`` the view model assembled: one card per stage
  with its own state word (RUNNING / IDLE / UNKNOWN, read from the stage's throughput), its
  simulated rate, and the PRD 8.3 equipment it groups. The overview is a *grouping of the
  twin*, not a second diagram: every number on a stage card is the same observed ``Value`` the
  animated twin scales its arrows by. Nothing here moves — the animation contract (item 4,
  AC-21) belongs to the twin screens B and E; this screen shows the state words only.
* **items 9 / 12** — the plant KPI group's cards: the specific energy figures, the two
  production rates, and the *daily totals* the provider binds into the same group. Directive
  item 12 is VERBATIM that "the dashboard must NOT show only the favorable metric", so every
  specific-energy card is rendered inside the one group that also carries its total — the
  group's own note says so, and no card is promoted above the pairing.
* **PRD 18.1's two AI tiles** — "AI status" and "Anomaly status", rendered from the compact
  :class:`~src.digital_twin.state.OverviewStatus` summaries the view model derives from the
  view H / view J payloads. The tile shows the payload's own headline word and its own
  one-line account; a model that was not run is stated as unavailable with its own reason —
  never paraphrased into a reassuring status, never substituted with a number.

Like :mod:`src.visualization.intelligence_view` and :mod:`src.visualization.optimization_view`,
this module only renders. It reads the frozen view model, computes nothing, invents no limit
and owns no threshold. Every string passes through :func:`src.visualization.theme.html`; every
number is formatted by :func:`src.visualization.theme.format_number` at the precision
``FormatSettings`` dictates; every absence is stated rather than filled in.

Known gap, recorded honestly (same class as view H's skipped §17 sparkline): PRD 18.1 asks for
a trend sparkline on each KPI card. ``OverviewView`` carries no trend channels, and adding
history reads is an accessor change this wave was not asked to make — so the cards render value
and status colour only, and the sparkline stays a backlog item for the next wave that owns
view A.
"""

from __future__ import annotations

from typing import Any, Final

from src import labels
from src.digital_twin.provenance import Provenance, Value
from src.visualization import theme

#: What a stage's rate readout shows when the payload carries no ``Value`` for it — the honest
#: absence glyph, never a zero that would read as a stopped-but-measured line.
_NO_RATE: Final = theme.NO_VALUE_TEXT

#: What a card that has nothing to render shows. Same wording as the view H / J renderers, so
#: all three state absence the same way; the renderer's own word (not PRD-quoted), kept out of
#: :mod:`src.labels` for the same reason those modules keep theirs there.
UNAVAILABLE_TEXT: Final = "unavailable"

#: The equipment-state pill colours. PRD 17.1's green/amber/red applied to the four words the
#: payload can carry: RUNNING is green, DERATED amber (health below the unit's own fault
#: step-down), UNKNOWN the honest grey; IDLE is grey too — a stopped line is a state, not a
#: fault, and colouring it amber would claim a degradation the payload never reported.
_STAGE_PILL: Final[dict[str, str]] = {
    labels.EQUIPMENT_RUNNING: "ok",
    labels.EQUIPMENT_DERATED: "warn",
    labels.EQUIPMENT_IDLE: "no_limit",
    labels.EQUIPMENT_UNKNOWN: "unknown",
}

#: The anomaly tile's pill colours — the same NORMAL/WARNING/ALARM → ok/warn/alarm mapping view
#: H's renderer uses, so the two screens colour Model B's levels identically. Anything else
#: (the unavailable label included) falls to the honest grey.
_STATUS_PILL: Final[dict[str, str]] = {"NORMAL": "ok", "WARNING": "warn", "ALARM": "alarm"}


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-ov{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-ov__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".dt-ov__chain{display:flex;flex-wrap:wrap;gap:.4em;align-items:stretch;}"
        ".dt-ov__arrow{display:flex;align-items:center;color:var(--dt-accent-alt);"
        "font-size:1.4em;padding:0 .1em;}"
        ".dt-ov__stage{flex:1 1 11em;max-width:16em;}"
        ".dt-ov__kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(13em,1fr));"
        "gap:var(--dt-gap);}"
        ".dt-ov__chips{display:flex;flex-wrap:wrap;gap:.3em;margin-top:.3em;}"
        ".dt-ov__chip{font-size:.85em;}"
        "</style>"
    )


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


def _badge(text: object, kind: str) -> str:
    return f'<span class="dt-badge dt-badge--{kind}">{theme.html(text)}</span>'


def _provenance_badge(provenance: Provenance) -> str:
    return _badge(theme.provenance_label(provenance), theme.provenance_slug(provenance))


# =============================================================================
# Item 3 — the five-stage chain (a grouping of the twin, not a second diagram)
# =============================================================================
def _rate_readout(rate: Value | None, fmt: Any) -> str:
    """The stage's simulated throughput as readout text, or the absence glyph.

    The rate is the same observed ``Value`` the twin's animation scales by, so the number on
    the card and the motion on view B/E can never disagree. A stage whose rate tag the snapshot
    does not carry shows the glyph — a stopped line and an unmeasured one are different states.
    """
    if rate is None:
        return f'<p class="dt-mono">{_NO_RATE}</p>'
    return (
        f'<p class="dt-mono">{theme.html(theme.value_text(rate, fmt))}'
        f' <span class="dt-muted">/ h</span></p>'
    )


def _equipment_chip(item: Any) -> str:
    """One PRD 8.3 component as a name + state chip, in the payload's own words."""
    return (
        f'<span class="dt-ov__chip">{theme.html(item.name)} '
        f'<span class="dt-muted">{theme.html(item.state)}</span></span>'
    )


def _stage_card(stage: Any, fmt: Any) -> str:
    """One stage of the chain: its state, its rate, and the equipment it groups.

    The state pill is the payload's own word (RUNNING / IDLE / UNKNOWN, item 3's throughput
    test); ``moving`` is deliberately not shown as a second status — the twin renders motion,
    this screen renders the state word the same test produced. Equipment the stage groups is
    listed with each item's own state, so "equipment state changes" (item 4's phrase) is
    legible here too, as text rather than animation.
    """
    chips = (
        f'<div class="dt-ov__chips">{"".join(_equipment_chip(item) for item in stage.equipment)}</div>'
        if stage.equipment
        else ""
    )
    return (
        '<div class="dt-card dt-ov__stage" data-role="stage">'
        f'<h3 class="dt-title">{theme.html(stage.title)}</h3>'
        f'<div class="dt-ov__badges">{_pill(stage.state, _STAGE_PILL.get(str(stage.state), "unknown"))}'
        f"{_provenance_badge(stage.rate.provenance if stage.rate else Provenance.OBSERVED)}</div>"
        f"{_rate_readout(stage.rate, fmt)}"
        f'<p class="dt-muted">{theme.html(stage.detail)}</p>'
        f"{chips}"
        "</div>"
    )


def _chain_section(stages: tuple[Any, ...], fmt: Any) -> str:
    """The five stages in process order, joined by arrows (item 3's own topology)."""
    parts: list[str] = []
    for index, stage in enumerate(stages):
        if index:
            parts.append('<span class="dt-ov__arrow">&rarr;</span>')
        parts.append(_stage_card(stage, fmt))
    return (
        '<div class="dt-card dt-card--alt" data-role="chain">'
        '<h3 class="dt-title">Plant overview chain</h3>'
        f'<div class="dt-ov__chain">{"".join(parts)}</div></div>'
    )


# =============================================================================
# Items 9 / 12 — the plant KPI group (specific and total energy, never one alone)
# =============================================================================
def _kpi_card(value: Value, fmt: Any) -> str:
    """One plant KPI card: the payload's own number, status colour and provenance.

    The title is the tag's own schema description (the wording ``value_from_tag`` read from
    :mod:`src.schema`), with the tag itself in muted mono beneath so every number stays
    traceable to its source (NFR-6). The status pill is the value's own banded status — this
    renderer bands nothing. A missing number shows the absence glyph, never a zero.
    """
    title = value.description or value.tag
    number = theme.value_text(value, fmt)
    return (
        '<div class="dt-card" data-role="kpi">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f'<div class="dt-ov__badges">{_pill(value.status, theme.status_slug(value.status))}'
        f"{_provenance_badge(value.provenance)}</div>"
        f'<p class="dt-mono" style="font-size:1.3em">{theme.html(number)}</p>'
        f'<p class="dt-mono dt-muted">{theme.html(value.tag)}</p>'
        "</div>"
    )


def _kpi_section(plant: Any, fmt: Any) -> str:
    """The plant KPI group as cards, with the group's own specific-vs-total note.

    The provider binds the specific figures and their daily totals into this one group under
    the item-12 note precisely so a view cannot split the pair; this section renders the group
    whole — every value it carries, in its own order — and prints the note beneath, so the
    favourable half can never stand alone (directive item 12, VERBATIM). An empty group (a
    provider that answered no plant KPI) is stated, not papered over with invented cards.
    """
    cards = "".join(_kpi_card(value, fmt) for value in plant.values) if plant.values else ""
    if not cards:
        cards = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            "plant KPI group. No production or energy card is invented to fill the space.</p>"
        )
    note = (
        f'<p class="dt-muted">{theme.html(plant.note)}</p>' if plant.note else ""
    )
    return (
        '<div class="dt-card dt-card--alt" data-role="kpis">'
        '<h3 class="dt-title">Plant KPIs</h3>'
        f'<div class="dt-ov__kpis">{cards}</div>{note}</div>'
    )


# =============================================================================
# PRD 18.1 — the AI status and anomaly status tiles
# =============================================================================
def _status_tile(status: Any) -> str:
    """One compact status tile from the view model's summary of a view H / J payload.

    The pill word and the detail line are the payload's own, chosen by the state layer's
    accessor (see ``state._ai_status_tile`` / ``state._anomaly_status_tile``): a status this
    renderer invents would be a second judgement on top of the model's. An unavailable model
    shows its own reason under the mandated unavailable label — never a reassuring status.
    The pill colour follows the payload's own level word where it has one.
    """
    kind = _STATUS_PILL.get(str(status.status), "unknown")
    if status.available and str(status.status) == labels.NO_SAFE_RECOMMENDATION:
        kind = "warn"  # a refusal is a display state (item 16), not a fault colour
    elif status.available and str(status.status) == labels.AI_RECOMMENDATION_LABEL:
        kind = "ok"
    return (
        '<div class="dt-card" data-role="status-tile">'
        f'<h3 class="dt-title">{theme.html(status.title)}</h3>'
        f'<div class="dt-ov__badges">{_pill(status.status, kind)}'
        f"{_provenance_badge(status.provenance)}</div>"
        f"<p>{theme.html(status.detail)}</p>"
        "</div>"
    )


def _status_section(ai_status: Any, anomaly_status: Any) -> str:
    return (
        '<div class="dt-card dt-card--alt" data-role="status">'
        "<h3 class=\"dt-title\">AI &amp; anomaly status</h3>"
        f'<div class="dt-ov__kpis">{_status_tile(ai_status)}{_status_tile(anomaly_status)}</div>'
        '<p class="dt-muted">One-line summaries of the AI Prediction &amp; Anomaly screen (view '
        "H) and the AI Optimization screen (view J) at this instant — the same payloads those "
        "screens render, not a second computation. The full cards live there.</p></div>"
    )


# =============================================================================
# Entry point
# =============================================================================
def render_overview(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """View A as a themed HTML fragment (plain HTML — nothing on this screen animates).

    ``model`` is the view-A view model — anything shaped like
    :class:`~src.digital_twin.state.OverviewView` (the ``stages`` chain, the ``plant`` KPI
    group, and the ``ai_status`` / ``anomaly_status`` tiles; plus the header ``app.py`` renders
    separately). ``settings`` is the
    :class:`~src.digital_twin.settings.DashboardSettings` the numeric formatting reads, so this
    renderer writes no precision of its own. The fragment carries its own scoped layout
    ``<style>`` and draws every colour and size from the theme variables, so it must sit inside
    a themed root — which :func:`app.build_document` provides.
    """
    fmt = settings.format
    stamp = model.header.timestamp if getattr(model, "header", None) is not None else ""
    badges = [
        _badge(labels.SIMULATED_RESULT_LABEL, "configuration"),
        _badge(labels.NOT_VALIDATED_LABEL, "configuration"),
    ]
    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{_panel_style()}"
        '<div class="dt-ov">'
        f'<div class="dt-ov__badges">{"".join(badges)}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
        f"{_chain_section(tuple(model.stages), fmt)}"
        f"{_kpi_section(model.plant, fmt)}"
        f"{_status_section(model.ai_status, model.anomaly_status)}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )
