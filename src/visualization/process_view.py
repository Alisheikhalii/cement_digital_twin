"""Views C, D and F — the process detail screens — as plain HTML (items 5, 6, 9, 20).

This is ONE renderer for the three screens ``DashboardState.kiln_process()``,
``DashboardState.clinker_cooler()`` and ``DashboardState.mill_separator()`` build. All three
return the same frozen view model, :class:`~src.digital_twin.state.ProcessView`
(``header`` / ``components`` / ``panels`` / ``kpis``), and no field of that shape means
something different on one screen than on another — the header names the screen, the
components are the PRD 8.3 equipment this screen focuses on, the panels are grouped observed
readouts, and the KPI group is the label the screen's dataset owns. So one renderer serves
all three with **zero view-specific branching**: it never reads ``view_id``, never special-cases
a screen, and would render any fourth ``ProcessView`` the state layer ever builds.

What it renders, per the directive items that own this screen group:

* **item 4 (inspector half)** — each component as a card: its state word (RUNNING / DERATED /
  IDLE / UNKNOWN — the payload's own), its health, the driving variable the animated twin
  scales its motion by (the same observed ``Value`` view B/E animate from), and the readout of
  its own output tags. The *animation* itself belongs to views B and E; this screen is the
  static inspector.
* **items 5 / 6** — the grouped process panels: "Kiln process indicators", "Kiln emissions"
  (view C — CO in the main panel only, per item 5, which is why the emissions block is its own
  panel) and "Mill process indicators" (view F). Every row is a payload ``Value`` with its own
  unit, status and provenance — the renderer bands nothing and writes no literal (NFR-6).
* **item 9** — the KPI group the screen's dataset owns (Kiln for C, Cement mill for F), rendered
  whole from the provider's group, no invented KPI among them.
* **item 20** — the honesty rules: the standing no-plant-connection statement, absences as the
  payload's own glyph rather than a zero, and empty sections *stated*, never papered over.

**View D carries no panels and no KPI group — by design, not by omission.** PRD §17's ten-row
table has no row for C, D or F (the directive D-2 discrepancy: these three screens come from
directive item 2's A–J registry, not the PRD's table), so no PRD text requires a grouped panel
or KPI group on view D. Its payload is components-only: the Cooler's readout carries the
cooler temperatures and fan power, and the Fuel & fan system's readout carries the fuel rates,
ID-fan and air figures plus O2 / CO / CO2 / NOx / SO2 — every tag the screen's own registry
line promises. The renderer states that plainly ("this screen carries no grouped readout
panels / KPI group of its own") instead of inventing one, and that statement is a property of
the payload, rendered because the payload says so — not an error state.

Like :mod:`src.visualization.overview_view` and :mod:`src.visualization.energy_view` (the
closest precedents — one renders the same equipment state words, the other the same KPI-group
cards), this module only renders. It reads the frozen view model, computes nothing, invents no
limit and owns no threshold: every status pill is the payload's own banded status, every
provenance badge the payload's own source. Every string passes through
:func:`src.visualization.theme.html`; every number is formatted by
:func:`src.visualization.theme.format_number` at the precision ``FormatSettings`` dictates;
every absence is stated rather than filled in. Nothing on this screen animates.
"""

from __future__ import annotations

from typing import Any, Final

from src import labels
from src.digital_twin.provenance import Provenance, Value
from src.visualization import theme

#: What a card that has nothing to render shows. Same wording as the view A / G / H / I / J
#: renderers, so all of them state absence the same way; the renderer's own word (not
#: PRD-quoted), kept out of :mod:`src.labels` for the same reason those modules keep theirs
#: there.
UNAVAILABLE_TEXT: Final = "unavailable"

#: The equipment-state pill colours, shared with :mod:`src.visualization.overview_view` so the
#: state words read identically on the overview chain and the process detail screens: RUNNING
#: is green, DERATED amber, IDLE / UNKNOWN the honest grey.
_STATE_PILL: Final[dict[str, str]] = {
    labels.EQUIPMENT_RUNNING: "ok",
    labels.EQUIPMENT_DERATED: "warn",
    labels.EQUIPMENT_IDLE: "no_limit",
    labels.EQUIPMENT_UNKNOWN: "unknown",
}


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-pr{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-pr__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".dt-pr__notices{margin:0;}"
        ".dt-pr__kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(13em,1fr));"
        "gap:var(--dt-gap);}"
        ".dt-pr__meta{display:flex;flex-wrap:wrap;gap:1em;align-items:baseline;}</style>"
    )


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


def _badge(text: object, kind: str) -> str:
    return f'<span class="dt-badge dt-badge--{kind}">{theme.html(text)}</span>'


def _provenance_badge(provenance: Provenance) -> str:
    return _badge(theme.provenance_label(provenance), theme.provenance_slug(provenance))


# =============================================================================
# One readout row / one readout table — a payload Value, the payload's own everything
# =============================================================================
def _readout_row(value: Value, fmt: Any) -> str:
    """One observed reading as a table row: its own title, number, status and source.

    The row's label is the tag's own schema description (the wording ``value_from_tag`` read
    from :mod:`src.schema`), with the tag itself beneath in muted mono so every number stays
    traceable to its source (NFR-6). The status pill is the value's own banded status — this
    renderer bands nothing. A missing number shows the absence glyph, never a zero.
    """
    title = value.description or value.tag
    return (
        "<tr>"
        f'<td>{theme.html(title)}<br><span class="dt-mono dt-muted">{theme.html(value.tag)}</span></td>'
        f'<td class="dt-num">{theme.html(theme.value_text(value, fmt))}</td>'
        f"<td>{_pill(value.status, theme.status_slug(value.status))}"
        f"{_provenance_badge(value.provenance)}</td>"
        "</tr>"
    )


def _readout_table(values: tuple[Value, ...], fmt: Any) -> str:
    """The values as one readout table, or nothing — the caller states the empty case."""
    rows = "".join(_readout_row(value, fmt) for value in values)
    if not rows:
        return ""
    return (
        '<table class="dt-table"><thead><tr><th>Indicator</th><th>Reading</th>'
        f"<th>Status</th></tr></thead><tbody>{rows}</tbody></table>"
    )


# =============================================================================
# Item 4 (inspector half) — one component card: state, health, driver, own readout
# =============================================================================
def _driver_line(status: Any, fmt: Any) -> str:
    """The driving variable the animated twin scales this unit's motion by (AC-21's input).

    The same observed ``Value`` view B/E animate from, so the number here and the motion there
    can never disagree. An absent driver (``None``) is stated — the payload's own UNKNOWN
    status already carries that word on the state pill.
    """
    driver = getattr(status, "driver", None)
    if driver is None:
        return '<p class="dt-muted">driver unavailable: no driving variable is reported</p>'
    return (
        '<p class="dt-mono">driver <span class="dt-muted">'
        f"{theme.html(driver.tag)}</span> {theme.html(theme.value_text(driver, fmt))}</p>"
    )


def _component_card(detail: Any, fmt: Any) -> str:
    """One :class:`~src.digital_twin.state.EquipmentDetail` as a card.

    The card title is the payload's own (``status.unit`` — the layout spec's title, e.g.
    "Preheater tower"); the equipment key and model kind render in muted mono beneath it so the
    card names exactly the PRD 8.3 component it speaks for. The state pill is the payload's own
    state word (the same test that produced the twin's animation state), the health figure the
    payload's own scalar. The readout is the component's own output tags — this renderer adds
    no tag to any component.
    """
    status = detail.status
    title = status.unit or status.name
    table = _readout_table(tuple(detail.readout.values), fmt)
    if not table:
        table = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this component carries no '
            "readout of its own. No reading is invented to fill the space.</p>"
        )
    return (
        '<div class="dt-card" data-role="process-component">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f'<div class="dt-pr__badges">{_pill(status.state, _STATE_PILL.get(str(status.state), "unknown"))}'
        f'{_provenance_badge(Provenance.OBSERVED)}</div>'
        '<div class="dt-pr__meta">'
        f'<span class="dt-mono dt-muted">{theme.html(status.name)} · {theme.html(status.kind)}</span>'
        f'<span class="dt-mono">health <span class="dt-num">'
        f"{theme.html(theme.format_number(status.health, fmt))}</span></span></div>"
        f"{_driver_line(status, fmt)}"
        f"{table}"
        "</div>"
    )


def _components_section(components: tuple[Any, ...], fmt: Any) -> str:
    """The components this screen focuses on, one card each, or the stated absence.

    The state layer filters a component the provider omitted (``_components`` drops ``None``),
    so an empty tuple means the provider answered none of this screen's equipment — stated,
    never filled in with a card the payload did not build.
    """
    cards = "".join(_component_card(detail, fmt) for detail in components)
    if not cards:
        cards = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider reports none of '
            "the components this screen focuses on. No card is invented to fill the space.</p>"
        )
    return (
        '<div class="dt-card dt-card--alt" data-role="process-components">'
        "<h3 class=\"dt-title\">Components</h3>"
        f'<div class="dt-pr__kpis">{cards}</div></div>'
    )


# =============================================================================
# Items 5 / 6 — the grouped process panels (view C's two, view F's one, view D's none)
# =============================================================================
def _panel_card(panel: Any, fmt: Any) -> str:
    """One grouped readout panel: its own title, its own rows, its own note.

    View C's emissions panel is a panel of its own (item 5: CO belongs in the main panel only,
    and the emissions block is deliberately separate); the renderer treats every panel the
    same — one channel, observed, the payload's own note verbatim.
    """
    table = _readout_table(tuple(panel.values), fmt)
    if not table:
        table = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            f"{theme.html(panel.title)} readings. No value is invented to fill the space.</p>"
        )
    note = f'<p class="dt-muted">{theme.html(panel.note)}</p>' if panel.note else ""
    return (
        '<div class="dt-card" data-role="process-panel">'
        f'<h3 class="dt-title">{theme.html(panel.title)}</h3>'
        f"{table}{note}"
        "</div>"
    )


def _panels_section(panels: tuple[Any, ...], fmt: Any) -> str:
    """The grouped panels, one card each — or view D's stated, designed emptiness.

    An empty ``panels`` tuple is a property of the payload, not an error: view D
    (Clinker Cooler) carries none by design, its Cooler and Fuel & fan readouts carrying every
    tag the screen's registry line promises. The absence is stated as that fact — never as a
    failure, and never filled with a panel the state layer did not build.
    """
    if not panels:
        return (
            '<div class="dt-card dt-card--alt" data-role="process-panels">'
            "<h3 class=\"dt-title\">Process readouts</h3>"
            '<p class="dt-muted">This screen carries no grouped readout panels of its own; '
            "every reading it reports lives in the component cards above.</p></div>"
        )
    return (
        '<div class="dt-card dt-card--alt" data-role="process-panels">'
        '<h3 class="dt-title">Process readouts</h3>'
        f"{''.join(_panel_card(panel, fmt) for panel in panels)}</div>"
    )


# =============================================================================
# Item 9 — the KPI group the screen's dataset owns (view D carries none)
# =============================================================================
def _kpi_card(value: Value, fmt: Any) -> str:
    """One KPI card: the payload's own number, status colour and provenance.

    Same shape as the overview and energy renderers' KPI cards, so the three screens that show
    a KPI group show it identically. A missing number shows the absence glyph, never a zero.
    """
    title = value.description or value.tag
    number = theme.value_text(value, fmt)
    return (
        '<div class="dt-card" data-role="process-kpi">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f'<div class="dt-pr__badges">{_pill(value.status, theme.status_slug(value.status))}'
        f"{_provenance_badge(value.provenance)}</div>"
        f'<p class="dt-mono" style="font-size:1.3em">{theme.html(number)}</p>'
        f'<p class="dt-mono dt-muted">{theme.html(value.tag)}</p>'
        "</div>"
    )


def _kpis_section(kpis: Any, fmt: Any) -> str:
    """The screen's KPI group as cards, or the stated absence (view D's designed ``None``).

    ``kpis=None`` is view D's shape, not a failure: the Clinker Cooler screen owns no KPI group
    because its dataset's groups (Kiln) belong to view C. Stated as that fact; never invented.
    """
    if kpis is None:
        return (
            '<div class="dt-card dt-card--alt" data-role="process-kpis">'
            "<h3 class=\"dt-title\">KPIs</h3>"
            '<p class="dt-muted">This screen carries no KPI group of its own.</p></div>'
        )
    cards = "".join(_kpi_card(value, fmt) for value in kpis.values)
    if not cards:
        cards = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            f"{theme.html(kpis.title)} KPI group. No card is invented to fill the space.</p>"
        )
    note = f'<p class="dt-muted">{theme.html(kpis.note)}</p>' if kpis.note else ""
    return (
        f'<div class="dt-card dt-card--alt" data-role="process-kpis">'
        f'<h3 class="dt-title">{theme.html(kpis.title)} KPIs</h3>'
        f'<div class="dt-pr__kpis">{cards}</div>{note}</div>'
    )


# =============================================================================
# Entry point
# =============================================================================
def render_process(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """A process detail screen (C, D or F) as a themed HTML fragment (nothing animates).

    ``model`` is the process view model — anything shaped like
    :class:`~src.digital_twin.state.ProcessView` (``components`` / ``panels`` / ``kpis`` plus
    the ``header`` ``app.py`` renders separately). The renderer reads no view id: all three
    screens share one payload shape, so one code path serves all three and any future
    ``ProcessView`` besides. ``settings`` is the
    :class:`~src.digital_twin.settings.DashboardSettings` the numeric formatting reads, so this
    renderer writes no precision of its own. The fragment carries its own scoped layout
    ``<style>`` and draws every colour and size from the theme variables, so it must sit inside
    a themed root — which :func:`app.build_document` provides.
    """
    fmt = settings.format
    header = getattr(model, "header", None)
    stamp = header.timestamp if header is not None else ""
    notices = (
        f'<p class="dt-muted dt-pr__notices">{theme.html(text)}</p>'
        for text in (header.notices if header is not None else ())
    )
    badges = [
        _badge(labels.SIMULATED_RESULT_LABEL, "configuration"),
        _badge(labels.NOT_VALIDATED_LABEL, "configuration"),
    ]
    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{_panel_style()}"
        '<div class="dt-pr">'
        f'<div class="dt-pr__badges">{"".join(badges)}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
        f"{''.join(notices)}"
        f"{_components_section(tuple(model.components), fmt)}"
        f"{_panels_section(tuple(model.panels), fmt)}"
        f"{_kpis_section(model.kpis, fmt)}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )
