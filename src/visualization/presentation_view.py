"""Factory Presentation Mode — PRD §29, Task #6 directive item 17 — as plain HTML.

This is the renderer for the overlay ``DashboardState.presentation()`` builds. PRD §29 defines
the mode as *"a simplified rendering path (not a separate data path — reuses Sections 14/17/18
outputs)"*, and §17.1's eleventh-view line calls it *"a simplified overlay/alternate rendering of
views 1 and 4"* — so this module renders nothing of its own: every word and number is the view A
/ view J payloads' own, read through :class:`~src.digital_twin.state.PresentationViewModel`, and
a value neither payload carries is **stated as unavailable, never computed here** (standing
constraint 4).

What the PRD asks for, and where each piece comes from:

* **the five-stage chain** — ``Current Plant State → AI Prediction → Optimization Opportunity →
  Recommended Action → Expected Benefit`` (§29's own topology). Current Plant State is view A's
  item-3 stage chain state words; AI Prediction is a summary of the recommendation's
  ``predicted_state_by_horizon`` (Model A's own grid, carried whole on views H and J — this
  overlay names it, it does not re-plot it); Optimization Opportunity is the optimizer's own
  headline, refusal reasons included (item 16: a refusal is a display state, never dropped);
  Recommended Action is the setpoint moves in the same format the optimizer's own one-line
  message uses; Expected Benefit is the expected impact's own daily-energy deltas with the
  standing simulated-saving caveat.
* **the five KPI cards** — Potential Thermal Energy Saving and Potential Electrical Energy
  Saving are the expected impact's own ``thermal_energy_kcal_per_day`` /
  ``electrical_energy_kwh_per_day``; Anomalies Detected is Model B's current verdict in its own
  words (a verdict per instant — no running count exists anywhere, so none is invented);
  Production Stability and Quality Stability are **honest gaps**: no model in this system
  computes a stability metric of either kind, and PRD §30/§21 honesty rules forbid inventing
  one, so both cards state their unavailability and the real reason.
* **labels** — every card carries one of the two mandated labels via
  :func:`src.labels.presentation_card_label`, split the way :mod:`src.labels` documents them:
  "Simulation Estimate" for a quantified benefit (the two saving cards), "Synthetic
  Demonstration" for everything else.
* **the §21 footnote** — §29 requires a visible link/footnote to the Synthetic-to-Real Transfer
  Strategy disclaimer, and §21.5 requires its standing statement verbatim in this mode. The
  export is a static self-contained HTML file (no server, no assets — the app.py contract), so
  the "link" is a visible footnote block naming §21 and quoting the statement verbatim.
* **what never appears** — raw tag readout lists, model internals, code, or a numeric
  confidence percentage (§29, AC-18). Recommendation Quality renders as the HIGH/MEDIUM/LOW
  categorical only, exactly as view J renders it.

Two configuration notes, both from ``PresentationSettings`` (PRD 29): ``headline_decimals``
rounds the headline KPI numbers — the one formatting decision this screen owns — and
``refresh_seconds`` is **not consumed**. It is an ``ASSUMPTION`` about the cadence of a
presentation loop, and this application exports a static HTML file per view (no view has a
refresh loop); inventing a JavaScript polling mechanism for this one screen alone would be new
behavior nothing else in the app has, so the key stays read-but-unused and the omission is
documented here rather than papered over.

Like every other renderer in this package, this module only renders: it reads the frozen view
model, computes nothing, invents no limit and owns no threshold. Every string passes through
:func:`src.visualization.theme.html`; every absence is stated rather than filled in.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from src import labels
from src.optimization.objective import ELECTRIC_TAG, THERMAL_TAG
from src.visualization import theme

#: What a card that has nothing honest to show displays — the same wording the view A / H / J
#: renderers use, so every screen states absence the same way. The renderer's own word (not
#: PRD-quoted), kept out of :mod:`src.labels` for the same reason those modules keep theirs.
UNAVAILABLE_TEXT: Final = "unavailable"

#: The five chain stages, in §29's own order and wording.
CHAIN_CURRENT: Final = "Current Plant State"
CHAIN_PREDICTION: Final = "AI Prediction"
CHAIN_OPPORTUNITY: Final = "Optimization Opportunity"
CHAIN_ACTION: Final = "Recommended Action"
CHAIN_BENEFIT: Final = "Expected Benefit"

#: The five KPI cards, §29's own titles.
CARD_THERMAL: Final = "Potential Thermal Energy Saving"
CARD_ELECTRICAL: Final = "Potential Electrical Energy Saving"
CARD_PRODUCTION: Final = "Production Stability"
CARD_QUALITY: Final = "Quality Stability"
CARD_ANOMALIES: Final = "Anomalies Detected"

#: The honest reasons the two stability cards carry. PRD §29 names the cards but no payload in
#: this system computes either metric — and standing constraint 4 (a guard states an absence,
#: never substitutes a number) plus §30's honesty rules forbid filling the space with a
#: plausible score. The nearest real quantity, Model A's ``predicted_variability_pct``, is a
#: cross-horizon model spread for the recommended action — not a stability measure — so it
#: stays on view J rather than being re-labelled here.
PRODUCTION_GAP_REASON: Final = (
    "No model in this system computes a production-stability metric. Rather than invent a "
    "score, this card states the gap; the nearest real quantity (Model A's cross-horizon "
    "spread, view J) is a model spread, not a stability measure."
)
QUALITY_GAP_REASON: Final = (
    "No model in this system computes a quality-stability metric. Rather than invent a score, "
    "this card states the gap; quality appears where it is real — as the recommendation's "
    "Blaine / residue impact on view J."
)

#: Why the anomaly card shows a verdict, not a number: Model B emits one verdict per dataset per
#: instant. There is no anomaly counter anywhere in the payload, so none is displayed.
ANOMALY_VERDICT_NOTE: Final = (
    "Model B reports one verdict per instant, not a running count — the current verdict is "
    "shown as it was issued; no count is invented."
)

#: The quality label rendered as a pill — the same categorical HIGH/MEDIUM/LOW mapping view J
#: uses (:data:`src.visualization.optimization_view._QUALITY_PILL`), so both screens colour the
#: optimizer's own category identically.
_QUALITY_PILL: Final[Mapping[str, str]] = {"HIGH": "ok", "MEDIUM": "warn", "LOW": "alarm"}

#: The anomaly verdict's pill colours — Model B's own level words, mapped the same way view A's
#: status tile maps them. Anything else (the unavailable label included) falls to honest grey.
_STATUS_PILL: Final[Mapping[str, str]] = {"NORMAL": "ok", "WARNING": "warn", "ALARM": "alarm"}


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-pres{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-pres__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".dt-pres__cards{display:grid;gap:var(--dt-gap);"
        "grid-template-columns:repeat(auto-fit,minmax(15em,1fr));}"
        ".dt-pres__chain{display:flex;flex-wrap:wrap;gap:.4em;align-items:stretch;}"
        ".dt-pres__arrow{display:flex;align-items:center;color:var(--dt-accent-alt);"
        "font-size:1.4em;padding:0 .1em;}"
        ".dt-pres__stage{flex:1 1 11em;max-width:18em;}"
        ".dt-pres__stages{display:flex;flex-direction:column;gap:.15em;}"
        ".dt-pres__line{display:flex;justify-content:space-between;gap:.5em;}"
        "</style>"
    )


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


def _badge(text: object, kind: str) -> str:
    return f'<span class="dt-badge dt-badge--{kind}">{theme.html(text)}</span>'


def _provenance_badge(provenance: Any) -> str:
    return _badge(theme.provenance_label(provenance), theme.provenance_slug(provenance))


def _headline_number(value: Any, decimals: int) -> str:
    """One headline KPI number at ``presentation.headline_decimals`` — the mode's own rounding.

    Thousands-grouped typography, the payload's own sign (a *saving* arrives negative), and the
    no-value glyph for an absent or non-numeric entry — never a zero that would read as
    "measured and nil".
    """
    try:
        number = None if value is None else float(value)
    except (TypeError, ValueError):
        return theme.NO_VALUE_TEXT
    if number != number:  # NaN — the same test theme.format_number applies
        return theme.NO_VALUE_TEXT
    return f"{number:,.{max(int(decimals), 0)}f}"


def _delta_pct(impact: Mapping[str, Any], tag: str) -> Any:
    """The expected impact's own ``delta_pct`` for one metric tag, or ``None``."""
    for metric in impact.get("metrics", ()):
        if isinstance(metric, Mapping) and str(metric.get("tag", "")) == tag:
            return metric.get("delta_pct")
    return None


# =============================================================================
# The five KPI cards (PRD 29) — each one carries one of the two mandated labels
# =============================================================================
def _saving_card(
    title: str,
    *,
    per_day: Any,
    unit: str,
    impact: Mapping[str, Any] | None,
    pct: Any,
    reason: str,
    decimals: int,
    provenance: Any,
) -> str:
    """One quantified-benefit card: the expected impact's own daily-energy delta.

    ``per_day`` is ``expected_impact.thermal_energy_kcal_per_day`` /
    ``electrical_energy_kwh_per_day`` exactly as the frozen layer serialized it — the change the
    simulation expects per day against the current operating point, sign and all. The secondary
    line is the impact's own ``delta_pct`` for the matching intensity metric, at the same two
    decimals the optimizer's own message uses. Label: "Simulation Estimate" — the label
    :mod:`src.labels` documents for a quantified benefit in this mode.
    """
    if per_day is None:
        body = (
            f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
            f'<p class="dt-muted">{theme.html(reason)}</p>'
        )
    else:
        basis = impact.get("daily_basis_hours") if isinstance(impact, Mapping) else None
        pct_line = (
            f" &middot; specific &Delta; {float(pct):+.2f} %" if pct is not None else ""
        )
        basis_line = f" &middot; per day, {theme.html(basis)} h basis" if basis else " per day"
        body = (
            f'<p class="dt-mono" style="font-size:1.3em">'
            f"{theme.html(_headline_number(per_day, decimals))} {theme.html(unit)}</p>"
            f'<p class="dt-muted">{theme.html(title)}{pct_line}{basis_line}</p>'
        )
    return (
        '<div class="dt-card" data-role="kpi-card">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f'<div class="dt-pres__badges">{_badge(labels.presentation_card_label("estimate"), "configuration")}'
        f"{_provenance_badge(provenance)}</div>"
        f"{body}"
        "</div>"
    )


def _gap_card(title: str, reason: str) -> str:
    """One of the two stability cards — an honest gap, never an invented score.

    PRD §29 names the card; no payload in this system carries its metric, and standing
    constraint 4 forbids substituting a number for an absence. The label is "Synthetic
    Demonstration" (the environment's badge): the card makes no quantified-benefit claim, which
    is the condition :mod:`src.labels` attaches to "Simulation Estimate".
    """
    return (
        '<div class="dt-card" data-role="kpi-card">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f'<div class="dt-pres__badges">{_badge(labels.presentation_card_label("synthetic"), "configuration")}</div>'
        f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
        f'<p class="dt-muted">{theme.html(reason)}</p>'
        "</div>"
    )


def _anomaly_card(tile: Any) -> str:
    """The Anomalies Detected card: Model B's current verdict, in its own words.

    The payload carries one verdict per instant (status word + cause line) — there is no
    anomaly counter anywhere, so the card shows the verdict and says so, rather than printing a
    "0" that would claim a counted empty history. An unavailable Model B shows its own reason
    under the mandated label. Label: "Synthetic Demonstration" — not a quantified benefit.
    """
    if not tile.available:
        body = (
            f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
            f'<p class="dt-muted">{theme.html(tile.detail)}</p>'
        )
        head = _pill(tile.status, "unknown")
    else:
        head = _pill(tile.status, _STATUS_PILL.get(str(tile.status), "unknown"))
        body = (
            f'<p class="dt-mono" style="font-size:1.3em">{theme.html(tile.status)}</p>'
            f"<p>{theme.html(tile.detail)}</p>"
            f'<p class="dt-muted">{theme.html(ANOMALY_VERDICT_NOTE)}</p>'
        )
    return (
        '<div class="dt-card" data-role="kpi-card">'
        f'<h3 class="dt-title">{theme.html(CARD_ANOMALIES)}</h3>'
        f'<div class="dt-pres__badges">{_badge(labels.presentation_card_label("synthetic"), "configuration")}'
        f"{_provenance_badge(tile.provenance)}</div>"
        f'<div>{head}</div>'
        f"{body}"
        "</div>"
    )


def _unavailable_reason(view: Any, *, stage: str) -> str:
    """Why a recommendation-derived value is absent — the payload's own account, in order.

    A model that was not run states its own unavailable reason; a refusal is a display state
    (item 16) and carries the headline the vocabulary mandates; only the residual "ran, accepted,
    but the figure is not in the payload" case gets this renderer's own words.
    """
    if not view.available:
        return str(view.unavailable_reason or labels.MODEL_UNAVAILABLE_STATEMENT)
    if view.refused:
        return f"{labels.NO_SAFE_RECOMMENDATION} — the optimizer refused every candidate, so there is no {stage} to report."
    return f"this run's payload carries no {stage}."


# =============================================================================
# The five-stage chain (PRD 29's own topology) — each stage one simplified card
# =============================================================================
def _chain_card(title: str, body: str) -> str:
    return (
        '<div class="dt-card dt-pres__stage" data-role="chain-stage">'
        f'<h3 class="dt-title">{theme.html(title)}</h3>'
        f"{body}"
        "</div>"
    )


def _current_state_card(stages: tuple[Any, ...]) -> str:
    """Stage 1 — the plant as view A's chain reports it: each stage's own state word.

    The state words are the item-3 throughput test's own (RUNNING / IDLE / UNKNOWN); the rates
    and equipment detail stay on view A — this overlay keeps one word per stage.
    """
    lines = "".join(
        f'<div class="dt-pres__line"><span>{theme.html(stage.title)}</span>'
        f'<span class="dt-muted">{theme.html(stage.state)}</span></div>'
        for stage in stages
    )
    if not lines:
        lines = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            "stage chain.</p>"
        )
    return _chain_card(CHAIN_CURRENT, f'<div class="dt-pres__stages">{lines}</div>')


def _prediction_card(view: Any) -> str:
    """Stage 2 — what Model A predicted for the recommended action, as a stated availability.

    The full horizon grid is Model A's output and stays on the screens that carry it (H, J);
    this overlay says what exists — how many targets, over which horizons — from the payload's
    own keys, and never re-derives or re-plots a value.
    """
    if not view.available:
        body = (
            f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
            f'<p class="dt-muted">{theme.html(_unavailable_reason(view, stage="prediction"))}</p>'
        )
    else:
        grid = view.predicted_states()
        if grid is None:
            body = (
                f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
                '<p class="dt-muted">the optimizer was not run or refused every candidate, so '
                "there is no recommended action to predict from.</p>"
            )
        elif not grid:
            body = (
                f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
                "<p class=\"dt-muted\">this recommendation carries no horizon predictions.</p>"
            )
        else:
            horizons = sorted(str(key) for key in grid)
            first = grid[horizons[0]]
            count = len(first) if isinstance(first, Mapping) else 0
            span = horizons[0] if len(horizons) == 1 else f"{horizons[0]} … {horizons[-1]}"
            body = (
                f"<p>Model A forecasts <strong>{count} plant values</strong> for the "
                f"recommended action over {theme.html(span)}.</p>"
                '<p class="dt-muted">The full forecast grid is on the AI Prediction &amp; '
                "Anomaly and AI Optimization screens (views H and J).</p>"
            )
    return _chain_card(CHAIN_PREDICTION, body)


def _opportunity_card(view: Any) -> str:
    """Stage 3 — the optimizer's own headline: what it found, or its refusal with the gates' words.

    Item 16: a refusal is a display state, never dropped — the reasons shown are the blocking
    gates' own reasons, exactly as the payload carries them.
    """
    if not view.available:
        kind = "unknown"
    elif view.refused:
        kind = "warn"
    else:
        kind = "ok"
    body = (
        f'<div class="dt-pres__badges">{_pill(view.headline, kind)}</div>'
        f"<p>{theme.html(view.message)}</p>"
    )
    if view.available and view.refusal_reasons:
        body += "".join(
            f'<p class="dt-muted">{theme.html(reason)}</p>' for reason in view.refusal_reasons
        )
    return _chain_card(CHAIN_OPPORTUNITY, body)


def _action_card(view: Any, rec: Mapping[str, Any] | None) -> str:
    """Stage 4 — the recommended setpoint moves, in the optimizer's own message format.

    ``{name} {delta:+.2f} %`` is the format the frozen layer's own accepted-message uses, so the
    overlay's action line and view J's message can never disagree in wording. A hold renders as
    the payload's own ``is_hold`` state in the same phrase the optimizer's message uses for it.
    The categorical quality pill is the payload's own HIGH / MEDIUM / LOW — never a percentage.
    """
    if not view.available or view.refused or not isinstance(rec, Mapping):
        return _chain_card(
            CHAIN_ACTION,
            f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
            f'<p class="dt-muted">{theme.html(_unavailable_reason(view, stage="recommended action"))}</p>',
        )
    deltas = rec.get("delta_fractions") or {}
    moves = " &middot; ".join(
        f"{theme.html(str(name))} {float(value) * 100:+.2f} %"
        for name, value in deltas.items()
        if abs(float(value)) > 0.0
    )
    action = (
        f'<p class="dt-mono">{moves}</p>'
        if moves
        else "<p>Hold the current setpoints.</p>"
    )
    quality = str(rec.get("recommendation_quality", ""))
    pill = f'{_pill(quality, _QUALITY_PILL.get(quality, "unknown"))}' if quality else ""
    statuses = " / ".join(
        str(part)
        for part in (rec.get("constraint_status"), rec.get("envelope_status"), rec.get("mode"))
        if part
    )
    return _chain_card(
        CHAIN_ACTION,
        f"{action}"
        f'<div class="dt-pres__badges">{pill}'
        f'{_badge(labels.AI_RECOMMENDATION_LABEL, "configuration")}</div>'
        f'<p class="dt-muted">{theme.html(statuses)}</p>',
    )


def _benefit_card(
    view: Any,
    rec: Mapping[str, Any] | None,
    impact: Mapping[str, Any] | None,
    decimals: int,
) -> str:
    """Stage 5 — the expected benefit: the impact's own daily-energy deltas and standing caveat.

    The same two numbers the saving cards headline, with the payload's own caveat — the banner
    the frozen layer attaches to every reported saving — so the benefit can never read as a
    promised factory saving.
    """
    if not view.available or view.refused or not isinstance(impact, Mapping):
        return _chain_card(
            CHAIN_BENEFIT,
            f'<p class="dt-mono">{theme.html(UNAVAILABLE_TEXT)}</p>'
            f'<p class="dt-muted">{theme.html(_unavailable_reason(view, stage="expected benefit"))}</p>',
        )
    rows = "".join(
        f'<div class="dt-pres__line"><span>{theme.html(title)}</span>'
        f'<span class="dt-mono">{theme.html(_headline_number(impact.get(key), decimals))}'
        f" {theme.html(unit)}</span></div>"
        for title, key, unit in (
            ("Thermal energy", "thermal_energy_kcal_per_day", "kcal/day"),
            ("Electrical energy", "electrical_energy_kwh_per_day", "kWh/day"),
        )
    )
    caveat = str(impact.get("caveat") or labels.SIMULATED_SAVING_CAVEAT)
    return _chain_card(
        CHAIN_BENEFIT,
        f'<div class="dt-pres__stages">{rows}</div>'
        f'<div class="dt-banner">{theme.html(caveat)}</div>',
    )


# =============================================================================
# Entry point
# =============================================================================
def render_presentation(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """Factory Presentation Mode as a themed HTML fragment (plain HTML — nothing animates).

    ``model`` is the overlay view model — anything shaped like
    :class:`~src.digital_twin.state.PresentationViewModel` (the ``overview`` / ``optimization``
    view models it composes, plus the header ``app.py`` renders separately). ``settings`` is the
    :class:`~src.digital_twin.settings.DashboardSettings` whose ``presentation.headline_decimals``
    rounds the headline KPI numbers — the one setting this screen reads; see the module docstring
    for why ``refresh_seconds`` is deliberately not consumed. The fragment carries its own scoped
    layout ``<style>`` and draws every colour and size from the theme variables, so it must sit
    inside a themed root — which :func:`app.build_document` provides.
    """
    decimals = int(settings.presentation.headline_decimals)
    view = model.optimization.view
    rec = view.recommendation() if view.available else None
    impact = rec.get("expected_impact") if isinstance(rec, Mapping) else None
    stamp = model.header.timestamp if getattr(model, "header", None) is not None else ""

    chain = [
        _current_state_card(tuple(model.overview.stages)),
        _prediction_card(view),
        _opportunity_card(view),
        _action_card(view, rec),
        _benefit_card(view, rec, impact, decimals),
    ]
    chain_html = "".join(
        part if index == 0 else f'<span class="dt-pres__arrow">&rarr;</span>{part}'
        for index, part in enumerate(chain)
    )

    reason = _unavailable_reason(view, stage="expected saving")
    cards = "".join(
        (
            _saving_card(
                CARD_THERMAL,
                per_day=impact.get("thermal_energy_kcal_per_day") if isinstance(impact, Mapping) else None,
                unit="kcal/day",
                impact=impact if isinstance(impact, Mapping) else None,
                pct=_delta_pct(impact, THERMAL_TAG) if isinstance(impact, Mapping) else None,
                reason=reason,
                decimals=decimals,
                provenance=view.provenance,
            ),
            _saving_card(
                CARD_ELECTRICAL,
                per_day=impact.get("electrical_energy_kwh_per_day") if isinstance(impact, Mapping) else None,
                unit="kWh/day",
                impact=impact if isinstance(impact, Mapping) else None,
                pct=_delta_pct(impact, ELECTRIC_TAG) if isinstance(impact, Mapping) else None,
                reason=reason,
                decimals=decimals,
                provenance=view.provenance,
            ),
            _gap_card(CARD_PRODUCTION, PRODUCTION_GAP_REASON),
            _gap_card(CARD_QUALITY, QUALITY_GAP_REASON),
            _anomaly_card(model.overview.anomaly_status),
        )
    )

    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{_panel_style()}"
        '<div class="dt-pres">'
        f'<div class="dt-pres__badges">'
        f'{_badge(labels.presentation_card_label("synthetic"), "configuration")}'
        f'{_badge(labels.NOT_VALIDATED_LABEL, "configuration")}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
        '<div class="dt-card dt-card--alt" data-role="kpis">'
        '<h3 class="dt-title">KPI cards</h3>'
        f'<div class="dt-pres__cards">{cards}</div></div>'
        '<div class="dt-card dt-card--alt" data-role="chain">'
        '<h3 class="dt-title">From plant state to expected benefit</h3>'
        f'<div class="dt-pres__chain">{chain_html}</div></div>'
        '<div class="dt-card dt-card--alt" data-role="transfer-strategy">'
        '<h3 class="dt-title">Synthetic-to-Real Transfer Strategy (PRD &sect;21)</h3>'
        f'<p>{theme.html(labels.TRANSFER_STRATEGY_STATEMENT)}</p>'
        '<p class="dt-muted">Every number on this screen is a synthetic demonstration or a '
        "simulation estimate, not a validated real-plant result — the full transfer strategy "
        "is Section 21 of the PRD.</p></div>"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )
