"""View J — the AI Optimization panel — as plain HTML (PRD v1.1.1 Sections 14.4, 14.5, 16.3, 17 view 4).

This is the first renderer for a non-twin screen, and it covers the three directive items that
share view J:

* **item 14** — the decision-support recommendation card, rendered straight from
  ``OptimizationView.recommendation()`` (which is ``Recommendation.describe()`` unchanged). The
  panel renders from it and never recomputes an impact, and it shows the categorical
  recommendation quality with its gloss — never a numeric confidence percentage (FR-23, AC-18).
* **item 15** (reconstructed, Tier E2) — the PRD 14.5 five-row baseline comparison, rendered from
  ``OptimizationView.baselines()`` (which is ``BaselineComparison.describe()`` unchanged). The
  chosen form is one comparison table — the display-form decision recorded in
  ``docs/TASK6_DIRECTIVE.md`` §1 item 15 — with unavailable rows showing "unavailable" plus the
  row's own reason, never a zero or a blank.
* **item 16** — refusals as a first-class display state: a blocked run shows its headline, the
  blocking gates' own reasons (the optimizer's words, not a second explanation) and the rejection
  count, never an empty card.

Like :mod:`src.visualization.svg_twin`, this module only renders. It reads the frozen view model,
computes nothing, invents no limit and owns no threshold. Every string passes through
:func:`src.visualization.theme.html`; every number is formatted by
:func:`src.visualization.theme.format_number` at the precision ``FormatSettings`` dictates; every
absence is stated rather than filled in. No animation here — nothing on this screen moves, so
there is no animation contract to honour (item 4 / AC-21 do not reach this panel).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from src import labels
from src.visualization import theme

#: What a baseline row that could not be built shows, followed by the row's own reason. Not a
#: PRD-quoted string, so it lives here rather than in :mod:`src.labels`: that module is mandated
#: vocabulary, and this word is the renderer's own.
UNAVAILABLE_ROW_TEXT: Final = "unavailable"

#: The quality label rendered as a pill. Mapping is presentational (PRD 17.1 green/amber/red
#: coding); the *words* HIGH/MEDIUM/LOW are the optimizer's own categorical values.
_QUALITY_PILL: Final[Mapping[str, str]] = {"HIGH": "ok", "MEDIUM": "warn", "LOW": "alarm"}


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-opt{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-opt__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".dt-opt__grid{display:grid;gap:var(--dt-gap);"
        "grid-template-columns:repeat(auto-fill,minmax(210px,1fr));}"
        "</style>"
    )


def _num(value: Any, fmt: Any) -> str:
    """One payload number as readout text; an absent or non-numeric value as the no-value glyph."""
    try:
        number = None if value is None else float(value)
    except (TypeError, ValueError):
        number = None
    return theme.format_number(number, fmt)


def _badge(text: object, kind: str) -> str:
    return f'<span class="dt-badge dt-badge--{kind}">{theme.html(text)}</span>'


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


# =============================================================================
# The status strip — what ran, in which mode, from which channel (item 1)
# =============================================================================
def _status_strip(view: Any) -> str:
    """Badges every rendering of view J carries: the run's identity, mode and provenance."""
    pills: list[str] = [
        _badge(labels.AI_RECOMMENDATION_LABEL, "recommendation"),
        _badge(theme.provenance_label(view.provenance), theme.provenance_slug(view.provenance)),
        _pill(view.mode, "unknown" if view.mode not in labels.OPTIMIZATION_MODE_VALUES else "ok"),
    ]
    rec = view.recommendation() if view.available else None
    if rec is not None:
        quality = str(rec.get("recommendation_quality", ""))
        pills.append(_pill(quality, _QUALITY_PILL.get(quality, "unknown")))
        envelope = str(rec.get("envelope_status", ""))
        pills.append(
            _pill(envelope, "alarm" if envelope == "OUTSIDE_ENVELOPE" else "ok")
        )
    stamp = f"{view.mode} · {view.timestamp}"
    return (
        f'<div class="dt-opt__badges">{"".join(pills)}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
    )


# =============================================================================
# Item 20 / NFR-6 — the unavailable panel: stated, never substituted
# =============================================================================
def _unavailable_panel(view: Any) -> str:
    return (
        '<div class="dt-card dt-card--alt">'
        f'<h3 class="dt-title">{theme.html(labels.MODEL_UNAVAILABLE_LABEL)}</h3>'
        f'<p>{theme.html(view.unavailable_reason or labels.MODEL_UNAVAILABLE_STATEMENT)}</p>'
        "</div>"
    )


# =============================================================================
# Item 16 — a refusal is a display state, not an empty card
# =============================================================================
def _refusal_panel(view: Any) -> str:
    """The optimizer's refusal, in its own words. The reasons are the blocking gates' reasons."""
    reasons = "".join(f"<li>{theme.html(reason)}</li>" for reason in view.refusal_reasons)
    return (
        '<div class="dt-card dt-card--alt" data-role="refusal">'
        f'<h3 class="dt-title">{theme.html(labels.NO_SAFE_RECOMMENDATION)}</h3>'
        f"<p>{theme.html(view.message)}</p>"
        + (f"<ul>{reasons}</ul>" if reasons else "")
        + (
            '<p class="dt-muted">'
            f"{theme.html(int(view.evaluated))} candidate(s) evaluated, "
            f"{theme.html(int(view.rejected_candidates))} rejected by the gates. "
            "The constraints were not relaxed to manufacture a recommendation."
            "</p>"
        )
        + "</div>"
    )


# =============================================================================
# Item 16 (visible half) — the gates, so a refusal can be inspected
# =============================================================================
def _gates_table(view: Any) -> str:
    """Every gate's verdict; blocking gates are marked. This is the audit trail of a refusal."""
    rows = []
    for gate in view.gates:
        state = str(gate.get("state", ""))
        reason = str(gate.get("reason", ""))
        blocking = bool(gate.get("blocking"))
        state_cell = (
            _pill(f"blocking · {state}", "alarm") if blocking else _pill(state, "ok")
        )
        rows.append(
            f"<tr><td>{theme.html(gate.get('gate', ''))}</td>"
            f"<td>{state_cell}</td>"
            f"<td>{theme.html(reason)}</td></tr>"
        )
    return (
        '<div class="dt-card">'
        '<h3 class="dt-title">Gates (PRD 14.3, in evaluation order)</h3>'
        '<table class="dt-table"><thead><tr><th>Gate</th><th>Verdict</th><th>Reason</th></tr>'
        f"</thead><tbody>{''.join(rows)}</tbody></table>"
        "</div>"
    )


# =============================================================================
# Item 14 — the recommendation card, rendered from Recommendation.describe() unchanged
# =============================================================================
def _impact_table(impact: Mapping[str, Any], fmt: Any) -> str:
    """The expected-impact metrics, before/after per tag. Every number is the payload's own."""
    rows = []
    for metric in impact.get("metrics", ()):
        rows.append(
            f"<tr><td>{theme.html(metric.get('tag', ''))}</td>"
            f'<td class="dt-num">{_num(metric.get("baseline"), fmt)}</td>'
            f'<td class="dt-num">{_num(metric.get("proposed"), fmt)}</td>'
            f'<td class="dt-num">{_num(metric.get("delta"), fmt)}</td>'
            f'<td class="dt-num">{_num(metric.get("delta_pct"), fmt)}</td></tr>'
        )
    basis = impact.get("daily_basis_hours")
    totals = "".join(
        f'<p class="dt-mono dt-muted">{theme.html(key)}: {_num(value, fmt)}'
        f" ({theme.html(basis)} h basis)</p>"
        for key, value in (
            ("thermal_energy_kcal_per_day", impact.get("thermal_energy_kcal_per_day")),
            ("electrical_energy_kwh_per_day", impact.get("electrical_energy_kwh_per_day")),
        )
    )
    return (
        '<table class="dt-table"><thead><tr><th>Metric</th><th>Baseline</th><th>Proposed</th>'
        "<th>&Delta;</th><th>&Delta;&nbsp;%</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>{totals}"
    )


def _setpoints_table(rec: Mapping[str, Any], fmt: Any) -> str:
    """The recommended setpoint moves, current vs proposed. Bounds and steps are not restated."""
    tags = sorted(set(rec.get("baseline_setpoints", {})) | set(rec.get("proposed_setpoints", {})))
    rows = "".join(
        f"<tr><td>{theme.html(tag)}</td>"
        f'<td class="dt-num">{_num(rec.get("baseline_setpoints", {}).get(tag), fmt)}</td>'
        f'<td class="dt-num">{_num(rec.get("proposed_setpoints", {}).get(tag), fmt)}</td></tr>'
        for tag in tags
    )
    if not rows:
        return ""
    return (
        '<table class="dt-table"><thead><tr><th>Setpoint</th><th>Current</th><th>Proposed</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _recommendation_card(rec: Mapping[str, Any], fmt: Any) -> str:
    """Item 14's card: the action, its categorical quality with gloss, the reason, the impact.

    ``rec`` is ``Recommendation.describe()`` verbatim; nothing here recomputes an impact (the
    deltas and daily totals are the optimizer's own). The banner, when the payload carries one,
    is the fixed PRD 14.3/16.1 experimental-mode banner in its mandated wording.
    """
    quality = str(rec.get("recommendation_quality", ""))
    gloss = " ".join(
        theme.html(text)
        for text in (rec.get("quality_description", ""), rec.get("quality_reason", ""))
        if text
    )
    banner = str(rec.get("banner", "") or "")
    banner_html = (
        f'<div class="dt-banner dt-banner--warn">{theme.html(banner)}</div>' if banner else ""
    )
    impact = rec.get("expected_impact")
    impact_html = _impact_table(impact, fmt) if isinstance(impact, Mapping) else ""
    caveat = str(impact.get("caveat", "")) if isinstance(impact, Mapping) else ""
    caveat_html = (
        f'<div class="dt-banner">{theme.html(caveat)}</div>' if caveat else ""
    )
    return (
        '<div class="dt-card" data-role="recommendation">'
        f'<h3 class="dt-title">{theme.html(labels.AI_RECOMMENDATION_LABEL)} — '
        f'{theme.html(rec.get("label", ""))}</h3>'
        f'<p>{theme.html(rec.get("reason", ""))}</p>'
        + (f'<p class="dt-muted">{gloss}</p>' if gloss else "")
        + banner_html
        + f'<h3 class="dt-title">Recommended setpoints</h3>{_setpoints_table(rec, fmt)}'
        + (f'<h3 class="dt-title">Expected impact ({theme.html(labels.SIMULATED_RESULT_LABEL)})'
           "</h3>" if impact_html else "")
        + impact_html
        + caveat_html
        + "</div>"
    )


# =============================================================================
# Item 15 — the PRD 14.5 five-row baseline comparison (reconstructed, Tier E2)
# =============================================================================
def _baselines_table(baselines: Mapping[str, Any], fmt: Any) -> str:
    """All five PRD 14.5 rows over the one shared metric set.

    ``baselines`` is ``BaselineComparison.describe()`` verbatim. An available row shows its
    measured or simulated values; a row that could not be built spans the metric columns with
    ``UNAVAILABLE_ROW_TEXT`` plus the row's own ``detail`` reason — never a zero or a blank. The
    standing caveat is the payload's own (``SIMULATED_SAVING_CAVEAT`` as the frozen layer
    serialized it).
    """
    metrics = [str(tag) for tag in baselines.get("metrics", ())]
    head = "".join(f"<th>{theme.html(tag)}</th>" for tag in metrics)
    body_rows = []
    for row in baselines.get("rows", ()):
        title = f"{row.get('title', '')}"
        detail = str(row.get("detail", "") or "")
        title_cell = (
            f"<th>{theme.html(title)}"
            + (f'<br><span class="dt-muted">{theme.html(detail)}</span>' if detail else "")
            + "</th>"
        )
        source_cell = f'<td class="dt-muted">{theme.html(row.get("source", ""))}</td>'
        if row.get("available"):
            values = "".join(
                f'<td class="dt-num">{_num(row.get("metrics", {}).get(tag), fmt)}</td>'
                for tag in metrics
            )
            body_rows.append(f"<tr>{title_cell}{source_cell}{values}</tr>")
        else:
            body_rows.append(
                f'<tr>{title_cell}<td class="dt-muted" colspan="{max(len(metrics), 1)}">'
                f"{theme.html(UNAVAILABLE_ROW_TEXT)} — {theme.html(detail)}</td></tr>"
            )
    caveat = str(baselines.get("caveat", "") or "")
    return (
        '<table class="dt-table"><thead><tr><th>Baseline (PRD 14.5)</th><th>Source</th>'
        f"{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
        + (f'<div class="dt-banner">{theme.html(caveat)}</div>' if caveat else "")
    )


def _baselines_section(baselines: Mapping[str, Any] | None, fmt: Any) -> str:
    """The comparison, or the honest statement that this run built none."""
    if baselines is None:
        return (
            '<div class="dt-card">'
            '<h3 class="dt-title">Baseline comparison (PRD 14.5)</h3>'
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_ROW_TEXT)}: the optimizer ran without '
            "building the baseline comparison for this request. No baseline numbers are shown "
            "rather than substituted ones.</p></div>"
        )
    missing = ", ".join(str(name) for name in baselines.get("missing", ()))
    note = (
        f'<p class="dt-muted">Missing rows: {theme.html(missing)}.</p>' if missing else ""
    )
    return (
        '<div class="dt-card" data-role="baselines">'
        '<h3 class="dt-title">Baseline comparison (PRD 14.5, identical process conditions)</h3>'
        f"{_baselines_table(baselines, fmt)}{note}</div>"
    )


# =============================================================================
# Entry point
# =============================================================================
def render_optimization(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """View J as a themed HTML fragment (plain HTML — nothing on this screen animates).

    ``model`` is the view-J view model — anything carrying a ``view`` shaped like
    :class:`~src.digital_twin.insights.OptimizationView` (plus the header ``app.py`` renders
    separately). ``settings`` is the :class:`~src.digital_twin.settings.DashboardSettings` the
    numeric formatting reads, so this renderer writes no precision of its own. The fragment
    carries its own scoped layout ``<style>`` and draws every colour and size from the theme
    variables, so it must sit inside a themed root — which :func:`app.build_document` provides.
    """
    view = model.view
    fmt = settings.format
    cards: list[str] = []
    if not view.available:
        cards.append(_unavailable_panel(view))
    else:
        if view.refused:
            cards.append(_refusal_panel(view))
        recommendation = view.recommendation()
        if recommendation is not None:
            cards.append(_recommendation_card(recommendation, fmt))
        cards.append(_baselines_section(view.baselines(), fmt))
        if view.gates:
            cards.append(_gates_table(view))
    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{_panel_style()}"
        '<div class="dt-opt">'
        f"{_status_strip(view)}"
        f"{''.join(cards)}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )
