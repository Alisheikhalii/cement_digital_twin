"""View H — the AI Prediction & Anomaly panel — as plain HTML (PRD 17 view 7, items 10–11).

This is the renderer for the screen ``DashboardState.intelligence()`` builds, and it covers the
two directive items that share view H:

* **item 10** — Model A's own multi-horizon forecast grid, rendered from
  :class:`~src.digital_twin.insights.PredictionSet` (via the ``PredictionRow`` grid the view
  model already assembled): one row per target, one column per horizon the payload produced,
  the observed ``current`` in its own OBSERVED column and every forecast in the PREDICTION
  channel — the two are shown side by side and never as one series of "values" (directive
  item 10's two-channel rule). The horizon set is the payload's own ``horizons_min`` plus the
  horizons named in its ``missing`` pairs, so a horizon with no forecasts still appears as a
  column of stated absences rather than silently vanishing. The ``±`` figure is the ensemble
  spread Model A reported (PRD 13.1.1) — never a confidence percentage (FR-23, AC-18). This is
  *not* view J's ``predicted_state_by_horizon``: that field is Recommendation-scoped and belongs
  to view J; this grid is Model A's forecast of the current row.
* **item 11** — Model B's anomaly verdict, rendered from
  :class:`~src.digital_twin.insights.AnomalyState` in exactly the PRD 15 contract lines:
  WARNING, detected anomaly, the model-based hypothesis, the ranked affected variables, and
  the rule-engine's suggested action under its own "not a diagnosis" label. A NORMAL row
  renders "No anomaly detected", not a blank card. Where Model B's evidence cannot separate an
  instrument fault from a process deviation, ``display_cause`` already reads "Evidence
  inconclusive" — the renderer shows that verbatim and still carries the nearest regime
  signature under its own name as a *similarity match*, never as a cause. Nothing here
  invents a cause, a variable, an action or a score.

Like :mod:`src.visualization.optimization_view`, this module only renders. It reads the frozen
view model, computes nothing, invents no limit and owns no threshold. Every string passes
through :func:`src.visualization.theme.html`; every number is formatted by
:func:`src.visualization.theme.format_number` at the precision ``FormatSettings`` dictates;
every absence is stated rather than filled in. No animation here — nothing on this screen
moves, so there is no animation contract to honour (item 4 / AC-21 do not reach this panel).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from src import labels
from src.digital_twin.provenance import Provenance, Value
from src.visualization import theme

#: What a cell that could not be predicted shows, followed by a reason. Same wording as view J's
#: renderer so the two horizon grids state absence the same way. Not a PRD-quoted string, so it
#: lives here rather than in :mod:`src.labels`: that module is mandated vocabulary, and this
#: word is the renderer's own.
UNAVAILABLE_TEXT: Final = "unavailable"

#: What a missing (target, horizon) cell shows when the payload's ``missing`` list already named
#: the pair — the bundle's own account of which Model A (target, horizon) models do not exist,
#: restated at the cell it explains.
MISSING_MODEL_TEXT: Final = "no trained Model A for this target at this horizon"

#: What a missing (target, horizon) cell shows when the payload simply does not carry it and
#: ``missing`` does not explain why. A statement of where it is absent *from*, never a cause.
MISSING_ENTRY_TEXT: Final = "not carried in this prediction payload"

#: What the anomaly card shows for a row Model B scored as normal — the frozen layer's own
#: wording for the same state (``AnomalyReport.render()``'s NORMAL branch).
NO_ANOMALY_TEXT: Final = "No anomaly detected."

#: What the affected-variables line shows when Model B flagged an anomaly but no variable
#: crossed a control limit — the frozen layer's own fallback wording, never a blank line.
NO_VARIABLES_TEXT: Final = "none above the control limits"

#: The anomaly status pill colours. PRD 17.1 green/amber/red applied to the three status
#: levels the payload can carry (``labels.STATUS_LEVEL_VALUES``); the words are Model B's own.
_STATUS_PILL: Final[Mapping[str, str]] = {"NORMAL": "ok", "WARNING": "warn", "ALARM": "alarm"}


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-int{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-int__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
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
# Item 20 / NFR-6 — the unavailable panel: stated, never substituted
# =============================================================================
def _unavailable_panel(reason: str) -> str:
    return (
        '<div class="dt-card dt-card--alt">'
        f'<h3 class="dt-title">{theme.html(labels.MODEL_UNAVAILABLE_LABEL)}</h3>'
        f"<p>{theme.html(reason or labels.MODEL_UNAVAILABLE_STATEMENT)}</p>"
        "</div>"
    )


# =============================================================================
# Item 10 — Model A's forecast grid (OBSERVED current, PREDICTION horizons)
# =============================================================================
def _predicted_cell(value: Value, fmt: Any) -> str:
    """One forecast with its spread — the payload's own numbers, never a percentage.

    The ``±`` figure is ``uncertainty`` as Model A reported it (the ensemble spread, PRD
    13.1.1). A forecast without one shows the value alone; no confidence is derived in either
    case.
    """
    number = theme.format_number(value.value, fmt)
    spread = theme.format_number(value.uncertainty, fmt)
    spread_html = (
        f' <span class="dt-muted">&plusmn; {spread}</span>'
        if value.uncertainty is not None and spread != theme.NO_VALUE_TEXT
        else ""
    )
    return f'<td class="dt-num">{number}{spread_html}</td>'


def _missing_pairs(missing: tuple[str, ...]) -> frozenset[tuple[str, int]]:
    """``("oxygen_percent t+10min",)`` -> ``{(oxygen_percent, 10)}`` — the payload's own list.

    ``PredictionSet.missing`` is the bundle's own account of which (target, horizon) Model A
    models do not exist, serialized as ``"<target> t+<minutes>min"``. This parses it back into
    pairs so a missing cell can be matched to its entry; anything unparseable is skipped rather
    than guessed at.
    """
    pairs: set[tuple[str, int]] = set()
    for entry in missing:
        text = str(entry)
        if not (text.endswith("min") and " t+" in text):
            continue
        target, _, rest = text.rpartition(" t+")
        try:
            pairs.add((target, int(rest[:-3])))
        except ValueError:
            continue
    return frozenset(pairs)


def _prediction_grid(predictions: Any, rows: tuple[Any, ...], fmt: Any) -> str:
    """One row per target, one column per horizon — the grid Model A actually produced.

    The horizon set is the payload's own ``horizons_min`` plus the horizons its ``missing``
    entries name, so a horizon with no forecasts at all still appears as a column of stated
    absences. The ``Current`` column holds the observed value of each target (OBSERVED channel);
    every other column holds Model A's forecast (PREDICTION channel). A missing (target,
    horizon) cell shows ``UNAVAILABLE_TEXT`` plus the reason the payload carries — the pair's
    own ``missing`` entry, or the plain statement that the payload does not carry the forecast.
    A target whose every pair sits in ``missing`` gets a row of stated absences too (the view
    model's ``rows`` cover only the targets Model A forecast): its current cell is the no-value
    glyph, because the payload carries no observed value for a target it never forecast.
    """
    horizons = sorted(
        set(int(m) for m in predictions.horizons_min)
        | {minutes for _, minutes in _missing_pairs(predictions.missing)}
    )
    missing = _missing_pairs(predictions.missing)
    head = "".join(f"<th>t+{int(minutes)}</th>" for minutes in horizons)
    body_rows = []
    covered: set[str] = set()
    for row in rows:
        covered.add(str(row.target))
        forecast_by_minutes = {int(value.horizon_min): value for value in row.horizon}
        title_cell = (
            f"<th>{theme.html(row.target)}"
            + (f'<br><span class="dt-muted">{theme.html(row.unit)}</span>' if row.unit else "")
            + "</th>"
        )
        current_cell = (
            f'<td class="dt-num">{theme.format_number(row.current.value, fmt)}</td>'
            if row.current is not None
            else f'<td class="dt-num">{theme.NO_VALUE_TEXT}</td>'
        )
        cells = []
        for minutes in horizons:
            forecast = forecast_by_minutes.get(minutes)
            if forecast is None:
                reason = (
                    MISSING_MODEL_TEXT
                    if (row.target, minutes) in missing
                    else MISSING_ENTRY_TEXT
                )
                cells.append(
                    f'<td class="dt-muted">{theme.html(UNAVAILABLE_TEXT)} — '
                    f"{theme.html(reason)}</td>"
                )
            else:
                cells.append(_predicted_cell(forecast, fmt))
        body_rows.append(f"<tr>{title_cell}{current_cell}{''.join(cells)}</tr>")
    for target in sorted({name for name, _ in missing if name not in covered}):
        cells = "".join(
            f'<td class="dt-muted">{theme.html(UNAVAILABLE_TEXT)} — '
            f"{theme.html(MISSING_MODEL_TEXT)}</td>"
            for _ in horizons
        )
        body_rows.append(
            f"<tr><th>{theme.html(target)}</th>"
            f'<td class="dt-num">{theme.NO_VALUE_TEXT}</td>{cells}</tr>'
        )
    return (
        '<table class="dt-table"><thead><tr><th>Target</th><th>Current</th>'
        f"{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _prediction_section(predictions: Any, rows: tuple[Any, ...], fmt: Any) -> str:
    """Model A's forecast grid, or the honest statement that there is none.

    An unavailable ``PredictionSet`` shows the model's own reason (a refusal, a capability
    gate, or "no rows simulated yet"), never a grid of substitute numbers. An available set
    with no rows is stated too — no forecast is invented for a model that produced none. The
    model version, when the payload carries one, is shown with the grid (PRD 13.4: every
    prediction carries its source model version).
    """
    if not predictions.available:
        return f'<div class="dt-card" data-role="predictions">{_unavailable_panel(predictions.unavailable_reason)}</div>'
    if not rows:
        return (
            '<div class="dt-card" data-role="predictions">'
            '<h3 class="dt-title">Model A prediction</h3>'
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this prediction payload '
            "carries no forecasts. No predicted values are shown rather than substituted "
            "ones.</p></div>"
        )
    missing_note = (
        f'<p class="dt-muted">Missing models: {theme.html(", ".join(predictions.missing))}.</p>'
        if predictions.missing
        else ""
    )
    version_note = (
        f'<p class="dt-mono dt-muted">Model version: {theme.html(predictions.model_version)}'
        "</p>"
        if predictions.model_version
        else ""
    )
    return (
        '<div class="dt-card" data-role="predictions">'
        '<h3 class="dt-title">Model A prediction '
        f"{_badge(theme.provenance_label(Provenance.PREDICTION), theme.provenance_slug(Provenance.PREDICTION))}"
        "</h3>"
        f"{_prediction_grid(predictions, rows, fmt)}"
        f"{missing_note}{version_note}"
        '<p class="dt-muted">The <em>Current</em> column is the '
        f"{_badge(theme.provenance_label(Provenance.OBSERVED), theme.provenance_slug(Provenance.OBSERVED))}"
        " value of each target; every other column is Model A's forecast of it "
        f"({theme.html(theme.provenance_label(Provenance.PREDICTION))}). The &plusmn; figure "
        "is the model's own ensemble spread (PRD 13.1.1), shown as a spread and never as a "
        "percentage.</p></div>"
    )


# =============================================================================
# Item 11 — the PRD 15 anomaly warning card (Model B's verdict, never a diagnosis)
# =============================================================================
def _variables_text(affected: tuple[Mapping[str, Any], ...]) -> str:
    """The ranked affected-variables list, in the frozen layer's own presentation.

    Each entry is the payload's own mapping (``tag``, ``direction``, ``z_score``), already
    ranked by Model B. The wording follows ``AnomalyReport.render()`` — ``tag (direction,
    z=+1.2)`` — so the panel and the frozen layer's text output name the same variable the
    same way. An empty list shows the frozen layer's own fallback, never a blank line.
    """
    if not affected:
        return NO_VARIABLES_TEXT
    parts = []
    for item in affected:
        try:
            z = float(item.get("z_score"))
        except (TypeError, ValueError):
            z = None
        z_text = f"z={z:+.1f}" if z is not None else "z=?"
        parts.append(f"{item.get('tag', '')} ({item.get('direction', '')}, {z_text})")
    return ", ".join(parts)


def _nearest_regime_note(anomaly: Any) -> str:
    """The nearest regime signature, carried as a similarity match — never as a cause.

    Shown wherever Model B matched a regime signature at all. When the evidence is
    inconclusive this is the *only* place the signature appears: ``display_cause`` reads
    "Evidence inconclusive" and the signature stays under its own label. The similarity is
    the payload's own cosine; ``None``/NaN is omitted rather than shown as a number.
    """
    if not anomaly.nearest_regime:
        return ""
    similarity = anomaly.regime_similarity
    similarity_text = (
        f", cosine {float(similarity):+.3f}" if similarity is not None and similarity == similarity else ""
    )
    return (
        '<p class="dt-muted">Nearest regime signature (similarity match, not a cause): '
        f"{theme.html(anomaly.nearest_regime)}{theme.html(similarity_text)}</p>"
    )


def _anomaly_card(anomaly: Any, fmt: Any) -> str:
    """The PRD 15 contract, one line per field, from the payload's own values.

    The five contract lines — WARNING, detected anomaly, model-based hypothesis, affected
    variables, rule-based suggestion — carry Model B's own words. ``hypothesis_label`` and
    ``action_label`` are the VERBATIM PRD 15 labels the payload already carries. The anomaly
    score is the payload's own number (PRD 17 view 7: "live anomaly score"); nothing is
    derived from it.
    """
    status = str(anomaly.status)
    pills = [
        _pill(status, _STATUS_PILL.get(status, "unknown")),
        _badge(theme.provenance_label(anomaly.provenance), theme.provenance_slug(anomaly.provenance)),
    ]
    if anomaly.out_of_distribution:
        pills.append(_pill("out of distribution", "alarm"))
    score_line = (
        f'<p class="dt-mono dt-muted">Anomaly score: {_num(anomaly.score, fmt)}</p>'
        if anomaly.score is not None
        else ""
    )
    if not anomaly.is_anomaly:
        return (
            '<div class="dt-card" data-role="anomaly">'
            '<h3 class="dt-title">Anomaly detection</h3>'
            f'<div class="dt-int__badges">{"".join(pills)}</div>'
            f"<p>{theme.html(NO_ANOMALY_TEXT)}</p>"
            f"{score_line}{_nearest_regime_note(anomaly)}"
            "</div>"
        )
    return (
        '<div class="dt-card" data-role="anomaly">'
        '<h3 class="dt-title">Anomaly detection</h3>'
        f'<div class="dt-int__badges">{"".join(pills)}</div>'
        f'<div class="dt-banner dt-banner--alarm">{theme.html("WARNING")}</div>'
        f'<p><strong>Detected anomaly:</strong> {theme.html(anomaly.display_cause)}</p>'
        f"<p><strong>{theme.html(anomaly.hypothesis_label)}:</strong> "
        f"{theme.html(anomaly.hypothesis)}</p>"
        f"<p><strong>Affected variables:</strong> {theme.html(_variables_text(anomaly.affected_variables))}</p>"
        f"<p><strong>{theme.html(anomaly.action_label)}:</strong> "
        f"{theme.html(anomaly.suggested_action)}</p>"
        f"{score_line}{_nearest_regime_note(anomaly)}"
        "</div>"
    )


def _anomaly_section(anomaly: Any, fmt: Any) -> str:
    """Model B's verdict, or the honest statement that Model B is not there to give one."""
    if not anomaly.available:
        return f'<div class="dt-card" data-role="anomaly">{_unavailable_panel(anomaly.unavailable_reason)}</div>'
    return _anomaly_card(anomaly, fmt)


# =============================================================================
# Entry point
# =============================================================================
def render_intelligence(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """View H as a themed HTML fragment (plain HTML — nothing on this screen animates).

    ``model`` is the view-H view model — anything shaped like
    :class:`~src.digital_twin.state.IntelligenceView` (a ``predictions`` payload, an
    ``anomaly`` payload, and the ``rows`` grid the view model assembled; plus the header
    ``app.py`` renders separately). ``settings`` is the
    :class:`~src.digital_twin.settings.DashboardSettings` the numeric formatting reads, so
    this renderer writes no precision of its own. The fragment carries its own scoped layout
    ``<style>`` and draws every colour and size from the theme variables, so it must sit
    inside a themed root — which :func:`app.build_document` provides.
    """
    predictions = model.predictions
    anomaly = model.anomaly
    fmt = settings.format
    stamp = f"{getattr(model, 'dataset', '')} · {predictions.timestamp or model.anomaly.timestamp}"
    badges = [
        _badge(labels.SIMULATED_RESULT_LABEL, "configuration"),
        _badge(labels.NOT_VALIDATED_LABEL, "configuration"),
    ]
    cards = [
        _prediction_section(predictions, tuple(model.rows), fmt),
        _anomaly_section(anomaly, fmt),
    ]
    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{_panel_style()}"
        '<div class="dt-int">'
        f'<div class="dt-int__badges">{"".join(badges)}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
        f"{''.join(cards)}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )
