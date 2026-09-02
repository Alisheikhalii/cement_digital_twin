"""View G — Energy Monitoring — as plain HTML (item 12, with items 9 and 20).

This is the renderer for the screen ``DashboardState.energy()`` builds. It has no own PRD §17
row (the D-2 discrepancy set): its subject is view 1's energy KPIs (PRD §17 view 1 / §18.1 /
§9.2), carried on the one directive item that owns the screen:

* **item 12** — VERBATIM: *"The dashboard must NOT show only the favorable metric."* Specific
  energy can fall while the daily total rises, because production rose — so the provider binds
  each specific-energy figure and its daily total into one plant KPI group under the item-12
  note, and the view model partitions that same group (by tag, never a second computation) into
  ``specific`` / ``total`` / ``production`` panels. This renderer shows the three panels on one
  screen: the specific figures, the totals they imply, and the production rates that connect
  them — never the favorable half alone. The panels' own note
  (:data:`~src.labels.SPECIFIC_VS_TOTAL_NOTE`) is printed with the pair, verbatim.
* **item 9** — the kiln and cement-mill KPI groups, rendered whole from the groups the provider
  assembled, no invented KPI among them.
* **item 20** — the honesty rules every screen carries: the standing statements, no fabricated
  value, and a missing number stated as the payload's own absence (the no-value glyph), never a
  zero that would read as measured-and-zero.

Like :mod:`src.visualization.overview_view` (the closest precedent — it renders the same plant
group on view A), this module only renders. It reads the frozen view model, computes nothing,
invents no limit and owns no threshold: every status pill is the payload's own banded status,
every provenance badge the payload's own source. Every string passes through
:func:`src.visualization.theme.html`; every number is formatted by
:func:`src.visualization.theme.format_number` at the precision ``FormatSettings`` dictates;
every absence is stated rather than filled in. Nothing on this screen animates.

Known gap, recorded honestly (same class as view H's skipped §17 sparkline and view A's skipped
PRD 18.1 sparklines): the view model carries downsampled ``trends`` channels for the
specific-energy tags, but no Task-6 renderer draws charts — wiring one in would force the
Plotly-optional degradation decision this project has deferred (the view-H G-6 skip). The trend
channels are therefore not rendered here; see the implementation report's remaining-gaps list.
"""

from __future__ import annotations

from typing import Any, Final

from src import labels
from src.digital_twin.provenance import Provenance
from src.visualization import theme

#: What a card that has nothing to render shows. Same wording as the view A / H / J renderers,
#: so all four state absence the same way; the renderer's own word (not PRD-quoted), kept out of
#: :mod:`src.labels` for the same reason those modules keep theirs there.
UNAVAILABLE_TEXT: Final = "unavailable"


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-en{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-en__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".dt-en__kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(13em,1fr));"
        "gap:var(--dt-gap);}"
        ".dt-en__pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(26em,1fr));"
        "gap:var(--dt-gap);}"
        ".dt-en__cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(12em,1fr));"
        "gap:var(--dt-gap);}"
        "</style>"
    )


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


def _badge(text: object, kind: str) -> str:
    return f'<span class="dt-badge dt-badge--{kind}">{theme.html(text)}</span>'


def _provenance_badge(provenance: Provenance) -> str:
    return _badge(theme.provenance_label(provenance), theme.provenance_slug(provenance))


# =============================================================================
# The KPI card — one payload Value, the payload's own number, status and source
# =============================================================================
def _value_card(value: Any, fmt: Any) -> str:
    """One energy / production / KPI card: the payload's own number, status colour and source.

    The title is the tag's own schema description (the wording ``value_from_tag`` read from
    :mod:`src.schema`), with the tag itself in muted mono beneath so every number stays
    traceable to its source (NFR-6). The status pill is the value's own banded status — this
    renderer bands nothing. A missing number shows the absence glyph, never a zero.
    """
    title = value.description or value.tag
    number = theme.value_text(value, fmt)
    return (
        '<div class="dt-card" data-role="energy-kpi">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f'<div class="dt-en__badges">{_pill(value.status, theme.status_slug(value.status))}'
        f"{_provenance_badge(value.provenance)}</div>"
        f'<p class="dt-mono" style="font-size:1.3em">{theme.html(number)}</p>'
        f'<p class="dt-mono dt-muted">{theme.html(value.tag)}</p>'
        "</div>"
    )


def _cards(values: tuple[Any, ...], fmt: Any) -> str:
    """The panel's values as cards, or nothing — the caller states the empty case."""
    return "".join(_value_card(value, fmt) for value in values)


def _panel_block(panel: Any, fmt: Any, *, empty_subject: str) -> str:
    """One partitioned panel: its own title, its own cards, or the stated absence.

    An empty panel (a provider that answered none of this partition's tags) is stated with its
    subject named — no card is invented to fill the space, and the emptiness of one partition
    never hides the others.
    """
    cards = _cards(tuple(panel.values), fmt)
    if not cards:
        cards = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            f"{theme.html(empty_subject)}. No value is invented to fill the space.</p>"
        )
    return f'<div class="dt-en__cards">{cards}</div>'


# =============================================================================
# Item 12 — specific energy AND total energy, on one screen, never one alone
# =============================================================================
def _note_html(note: str) -> str:
    """A group / panel note as its own muted line — the payload's own wording, never reworded."""
    return f'<p class="dt-muted">{theme.html(note)}</p>' if note else ""


def _energy_pair_section(specific: Any, total: Any, production: Any, fmt: Any) -> str:
    """The item-12 core: the specific figures, the totals they imply, and the rates between them.

    The three panels are one plant KPI group partitioned by tag, so this section is the group
    rendered whole — every specific-energy figure appears on the same screen as the daily total
    it implies and the production rate that connects them. Directive item 12 is VERBATIM that
    the dashboard must not show only the favorable metric, so the pairing note both energy
    panels carry (:data:`~src.labels.SPECIFIC_VS_TOTAL_NOTE`) is printed once beneath the pair,
    verbatim from the payload, and no half of the pair is promoted above the other. An empty
    partition is stated (see :func:`_panel_block`) — an absent total never leaves its specific
    figure standing alone as if it were the whole picture.
    """
    return (
        '<div class="dt-card dt-card--alt" data-role="energy-pair">'
        '<h3 class="dt-title">Specific energy vs total energy</h3>'
        '<div class="dt-en__pair">'
        f'<div><h4 class="dt-title">{theme.html(specific.title)}</h4>'
        f"{_panel_block(specific, fmt, empty_subject='specific-energy figures')}</div>"
        f'<div><h4 class="dt-title">{theme.html(total.title)}</h4>'
        f"{_panel_block(total, fmt, empty_subject='daily-total figures')}</div>"
        "</div>"
        f'<div><h4 class="dt-title">{theme.html(production.title)}</h4>'
        f"{_panel_block(production, fmt, empty_subject='production rates')}</div>"
        f"{_note_html(specific.note or total.note)}"
        "</div>"
    )


# =============================================================================
# Item 9 — the kiln and cement-mill KPI groups, rendered whole
# =============================================================================
def _kpi_group_section(group: Any, fmt: Any, *, role: str) -> str:
    """One item-9 KPI group as cards, with the group's own note where it carries one.

    The group's members are the provider's own choice (no invented KPI among them); an empty
    group is stated rather than papered over, exactly like the partitions above.
    """
    cards = _cards(tuple(group.values), fmt)
    if not cards:
        cards = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            f"{theme.html(group.title)} KPI group. No card is invented to fill the space.</p>"
        )
    note = _note_html(group.note)
    return (
        f'<div class="dt-card" data-role="{role}">'
        f'<h3 class="dt-title">{theme.html(group.title)} KPIs</h3>'
        f'<div class="dt-en__kpis">{cards}</div>{note}</div>'
    )


# =============================================================================
# Entry point
# =============================================================================
def render_energy(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """View G as a themed HTML fragment (plain HTML — nothing on this screen animates).

    ``model`` is the view-G view model — anything shaped like
    :class:`~src.digital_twin.state.EnergyView` (the ``specific`` / ``total`` / ``production``
    partition of the plant group, plus the ``kiln`` and ``mill`` KPI groups; the header
    ``app.py`` renders separately). ``settings`` is the
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
        '<div class="dt-en">'
        f'<div class="dt-en__badges">{"".join(badges)}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
        f"{_energy_pair_section(model.specific, model.total, model.production, fmt)}"
        f"{_kpi_group_section(model.kiln, fmt, role='energy-kiln')}"
        f"{_kpi_group_section(model.mill, fmt, role='energy-mill')}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )
