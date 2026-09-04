"""View I — What-If Simulation — as plain HTML (PRD v1.1.1 Sections 16.1-16.3, 17 view 5).

This is the renderer for the screen ``DashboardState.what_if()`` builds. It covers directive
item 13 (the sliders and the three outcomes) and reads only what the PRD 16.3 panel contract
already carries under ``WhatIfView.panel``:

* the mode (NORMAL / EXPERIMENTAL) and the experimental banner, when the payload carries one —
  the fixed PRD 14.3/16.1 wording, visually distinct from Normal-Mode results;
* the manipulated variables — each ``requested_change`` row's own baseline, requested and
  simulated value, bounds, step, snapped/clipped flags and one-line note, so "your request was
  snapped/clipped" is shown rather than hidden (PRD 30: never hide a clip);
* the verdict — one of exactly the three display forms the engine already reached
  (``accepted`` / ``simulated`` / envelope status), read from the panel, never recomputed;
* the predicted response — the settled state and the before/after table over the same metric
  set as every PRD 14.5 baseline row;
* the expected impact — the energy figures and the savings line with its own caveat;
* the constraints and envelope checks — per-constraint and per-check rows, PASS/REJECTED/
  FLAGGED in the payload's own words, so the banner can be read per constraint and not just
  overall;
* the transition — the PRD 16.3 chart, drawn as a self-contained inline SVG of each moved
  variable's *commanded* setpoint path (the engine's own hold-then-ramp arithmetic, so the
  move is visibly not an instantaneous jump), with the trajectory summary (rows, minutes,
  hold, ramps) as numbers beneath it. The plant's response path is not on the payload —
  only its settled endpoints are — so no response curve is invented; a rejected request
  states that there is no trajectory to show — a rejected what-if is never simulated.

Like :mod:`src.visualization.optimization_view` (the closest precedent — view J renders from
the same ``Recommendation``-shaped panel), this module only renders. It reads the frozen view
model, computes nothing, invents no limit and owns no threshold: every number is the panel's
own, every verdict the engine's own, every absence stated with the payload's own reason rather
than filled in. Every string passes through :func:`src.visualization.theme.html`; every number
is formatted by :func:`src.visualization.theme.format_number` at the precision
``FormatSettings`` dictates. Nothing on this screen animates.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from src import labels
from src.digital_twin.provenance import Provenance
from src.visualization import theme

#: What a panel that could not be filled shows, followed by the payload's own reason. The
#: renderer's own word (not PRD-quoted), kept out of :mod:`src.labels` for the same reason the
#: other view renderers keep theirs there.
UNAVAILABLE_TEXT: Final = "unavailable"

#: What a rejected request's transition block shows. The engine's own contract: a request
#: rejected before any solve has no trajectory (``WhatIfResult.simulated`` is False), so the
#: absence is stated — never a fabricated flat line.
NO_TRAJECTORY_TEXT: Final = (
    "this request was rejected before any simulation ran, so there is no transition to show"
)

#: What the chart's caption states about the half of PRD 16.2 the payload does not carry. The
#: commanded setpoint path is payload-exact (hold + each variable's configured ramp — the same
#: linear ramp the scheduler's ``_RampedSetpoint`` applies); the plant's *response* path is not
#: on the payload at all, and an interpolated curve would be a fabricated delay — the exact
#: thing PRD 16.2 forbids passing off as the trajectory.
COMMAND_PATH_NOTE: Final = (
    "Commanded setpoint paths are payload-exact: the engine's own hold and configured ramp "
    "arithmetic, drawn per moved variable. The plant's response path between the baseline and "
    "the settled state is not carried by this payload — only its endpoints (the tables above) "
    "and the endpoint agreement are — so no response curve is drawn."
)

#: The verdict pill kinds. PASS is ok, REJECTED is alarm, NO SAFE RECOMMENDATION is warn: a
#: refusal is a display state (item 16's rule, carried to view I), not a crash.
_VERDICT_PILL: Final[Mapping[str, str]] = {
    labels.WHAT_IF_VERDICT_PASS: "ok",
    labels.WHAT_IF_VERDICT_REJECTED: "alarm",
    labels.WHAT_IF_VERDICT_NONE: "warn",
}


def _panel_style() -> str:
    """Scoped layout CSS for the panel. Geometry only — colours and type come from the theme."""
    return (
        "<style>.dt-wi{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".dt-wi__badges{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".dt-wi__sliders{display:grid;gap:var(--dt-gap);"
        "grid-template-columns:repeat(auto-fill,minmax(19em,1fr));}"
        ".dt-wi__chart{width:100%;height:auto;display:block;background:var(--dt-bg);"
        "border:var(--dt-border-width) solid var(--dt-border);border-radius:var(--dt-radius);}"
        ".dt-wi__axis{stroke:var(--dt-border);stroke-width:1;}"
        ".dt-wi__rail{stroke:var(--dt-text-muted);stroke-width:1;stroke-dasharray:2 3;"
        "opacity:.4;}"
        ".dt-wi__guide{stroke:var(--dt-text-muted);stroke-width:1;stroke-dasharray:4 4;"
        "opacity:.5;}"
        ".dt-wi__cmd{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;}"
        ".dt-wi__tick{fill:var(--dt-text-muted);font-family:var(--dt-font-mono);"
        "font-size:11px;}"
        ".dt-wi__note{fill:var(--dt-text-muted);font-family:var(--dt-font-sans);"
        "font-size:11px;}"
        ".dt-wi__legend{display:flex;flex-wrap:wrap;gap:var(--dt-gap-sm) var(--dt-gap);"
        "font-size:var(--dt-size-label);color:var(--dt-text-muted);"
        "margin-top:var(--dt-gap-sm);}"
        ".dt-wi__legend-item{display:inline-flex;align-items:center;"
        "gap:var(--dt-gap-sm);}"
        ".dt-wi__swatch{display:inline-block;width:1.4em;height:0;"
        "border-top:3px solid;}</style>"
    )


def _badge(text: object, kind: str) -> str:
    return f'<span class="dt-badge dt-badge--{kind}">{theme.html(text)}</span>'


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


def _num(value: Any, fmt: Any) -> str:
    """One payload number as readout text; an absent or non-numeric value as the no-value glyph."""
    try:
        number = None if value is None else float(value)
    except (TypeError, ValueError):
        number = None
    return theme.format_number(number, fmt)


def _num_or_raw(value: Any, fmt: Any) -> str:
    """A payload number, or its own text when it is not a number (e.g. a step size that is
    exactly representable): the payload's own rendering, never an invented precision."""
    text = _num(value, fmt)
    if text == theme.NO_VALUE_TEXT and value is not None:
        return theme.html(str(value))
    return text


def _spec_text(value: Any) -> str:
    """A *specification* number as the payload's own text, not at ``FormatSettings`` precision.

    The slider step is contractual — item 13's "exact configured step sizes" — and a step of
    ``0.0312`` would lose its fourth digit to ``max_decimals: 3``. Specs are read, never
    reformatted: the engine's own text is the honest rendering of the engine's own number.
    """
    if value is None:
        return theme.NO_VALUE_TEXT
    return theme.html(str(value))


def _slider_bounds(slider: Mapping[str, Any]) -> tuple[Any, Any]:
    """The mode bounds of one slider spec, in whichever shape the payload spelled them.

    The engine's ``WhatIfEngine.slider`` writes ``minimum`` / ``maximum``; the conftest stub
    writes ``min`` / ``max``; ``absolute_range`` is the schema range both also carry and the
    last resort — never a guess. The mode bounds, not the absolute range, are what a slider
    physically spans in the mode it was asked for.
    """
    for low_key, high_key in (("minimum", "maximum"), ("min", "max")):
        low, high = slider.get(low_key), slider.get(high_key)
        if low is not None and high is not None:
            return low, high
    bounds = slider.get("absolute_range")
    if isinstance(bounds, (tuple, list)) and len(bounds) == 2:
        return bounds[0], bounds[1]
    return None, None


# =============================================================================
# The status strip — mode, verdict, provenance, banner (PRD 16.1 / 16.3)
# =============================================================================
def _status_strip(view: Any) -> str:
    """Badges every rendering of view I carries: the mode, the verdict, the channel.

    The experimental banner is rendered here as well as in the body: PRD 16.1 fixes it to
    *every* Experimental-Mode result, and the header notices repeat it — this is the payload's
    own ``banner`` field, never one the renderer awarded.
    """
    pills: list[str] = [
        _badge(theme.provenance_label(view.provenance), theme.provenance_slug(view.provenance)),
        _pill(view.mode, "unknown" if view.mode not in labels.OPTIMIZATION_MODE_VALUES else "ok"),
    ]
    if view.available:
        pills.append(_pill(view.verdict, _VERDICT_PILL.get(view.verdict, "unknown")))
    stamp = f"{view.mode} · {view.timestamp}"
    return (
        f'<div class="dt-wi__badges">{"".join(pills)}'
        f'<span class="dt-mono dt-muted">{theme.html(stamp)}</span></div>'
    )


def _banner_html(banner: str | None) -> str:
    """The payload's own banner — the fixed PRD 14.3/16.1 wording, visually distinct (warn)."""
    if not banner:
        return ""
    return f'<div class="dt-banner dt-banner--warn">{theme.html(banner)}</div>'


# =============================================================================
# Item 20 / NFR-6 — the unavailable panel: stated, never substituted
# =============================================================================
def _unavailable_panel(view: Any) -> str:
    return (
        '<div class="dt-card dt-card--alt" data-role="whatif-unavailable">'
        f'<h3 class="dt-title">{theme.html(labels.MODEL_UNAVAILABLE_LABEL)}</h3>'
        f'<p>{theme.html(view.unavailable_reason or labels.MODEL_UNAVAILABLE_STATEMENT)}</p>'
        "</div>"
    )


# =============================================================================
# Item 13 — the sliders: the exact configured bounds and step sizes
# =============================================================================
def _slider_card(slider: Mapping[str, Any], fmt: Any) -> str:
    """One manipulated variable as a slider-shaped card: bounds, step, current, mode.

    The bounds, the step and the mode's change limit are the engine's own numbers (read from
    the payload, never restated from configuration here); a slider the payload did not carry
    is simply not drawn — no card is invented for a variable the engine does not offer.
    """
    name = str(slider.get("name", ""))
    unit = str(slider.get("unit", ""))
    mode = str(slider.get("mode", ""))
    low, high = _slider_bounds(slider)
    rows = "".join(
        f'<tr><th>{theme.html(label)}</th><td class="dt-num">{cell}</td></tr>'
        for label, cell in (
            ("Current", _num(slider.get("current"), fmt)),
            ("Minimum", _num(low, fmt)),
            ("Maximum", _num(high, fmt)),
            ("Step", _spec_text(slider.get("step"))),
            ("Max Δ fraction", _num(slider.get("max_delta_fraction"), fmt)),
        )
        if cell != theme.NO_VALUE_TEXT or label == "Current"
    )
    return (
        f'<div class="dt-card" data-role="whatif-slider" data-variable="{theme.html(name)}">'
        f'<h3 class="dt-title dt-mono" style="font-size:1em">{theme.html(name)}</h3>'
        f'<div class="dt-wi__badges">{_pill(mode or "NORMAL", "ok")}'
        f'{_pill(unit, "unknown")}</div>'
        f'<table class="dt-table"><tbody>{rows}</tbody></table>'
        "</div>"
    )


def _sliders_section(sliders: tuple[Mapping[str, Any], ...], fmt: Any) -> str:
    """The item-13 slider surface, or the stated absence of one.

    A provider that answered no sliders (Model C absent) gets that absence stated — a slider
    whose bounds nothing owns would be a made-up limit (item 5).
    """
    if not sliders:
        return (
            '<div class="dt-card" data-role="whatif-sliders">'
            f'<h3 class="dt-title">Manipulated variables (PRD 16.1)</h3>'
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this provider carries no '
            "slider specifications. No bounds or steps are shown rather than invented ones.</p>"
            "</div>"
        )
    cards = "".join(_slider_card(slider, fmt) for slider in sliders)
    return (
        '<div class="dt-card" data-role="whatif-sliders">'
        '<h3 class="dt-title">Manipulated variables (PRD 16.1)</h3>'
        '<div class="dt-wi__sliders">'
        + cards
        + "</div>"
        '<p class="dt-muted">Bounds, step and the mode&rsquo;s change limit are the '
        "engine&rsquo;s own configured numbers; a request is set in the engine&rsquo;s steps, "
        "never in a step of this screen&rsquo;s.</p></div>"
    )


# =============================================================================
# The manipulated change — requested vs simulated, with the engine's own notes
# =============================================================================
def _requested_change_table(requested: tuple[Mapping[str, Any], ...], fmt: Any) -> str:
    """Every manipulated variable: baseline, requested, simulated, and what the engine changed.

    The engine's own notes distinguish snapping from clipping (a grid alignment vs a mode-bound
    refusal); both are rendered so a trimmed request is shown as trimmed — never passed off as
    what was asked (PRD 30).
    """
    rows = []
    for item in requested:
        name = str(item.get("name", ""))
        unit = str(item.get("unit", ""))
        bounds = item.get("bounds") or ()
        bounds_text = (
            f"[{_num_or_raw(bounds[0], fmt)}, {_num_or_raw(bounds[1], fmt)}]"
            if isinstance(bounds, (tuple, list)) and len(bounds) == 2
            else theme.NO_VALUE_TEXT
        )
        flags = []
        if item.get("clipped"):
            flags.append("clipped")
        if item.get("snapped"):
            flags.append("snapped")
        if item.get("moved"):
            flags.append("moved")
        flag_text = " · ".join(flags)
        rows.append(
            f"<tr><th>{theme.html(name)}"
            + (f'<br><span class="dt-muted">{theme.html(unit)}</span>' if unit else "")
            + f"</th>"
            f'<td class="dt-num">{_num(item.get("baseline"), fmt)}</td>'
            f'<td class="dt-num">{_num(item.get("requested"), fmt)}</td>'
            f'<td class="dt-num">{_num(item.get("value"), fmt)}</td>'
            f'<td class="dt-num">{_num_or_raw(item.get("delta_pct"), fmt)}</td>'
            f'<td class="dt-num">{bounds_text}</td>'
            f'<td class="dt-num">{_spec_text(item.get("step"))}</td>'
            f'<td class="dt-muted">{theme.html(flag_text)}</td></tr>'
        )
    if not rows:
        return ""
    return (
        '<table class="dt-table"><thead><tr><th>Variable</th><th>Baseline</th>'
        "<th>Requested</th><th>Simulated</th><th>&Delta;&nbsp;%</th><th>Mode bounds</th>"
        "<th>Step</th><th>Flags</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _change_section(view: Any, fmt: Any) -> str:
    """The requested change, the action line, and every note the engine attached."""
    table = _requested_change_table(tuple(view.requested), fmt)
    if not table:
        return ""
    notes = "".join(
        f'<li class="dt-muted">{theme.html(note)}</li>' for note in view.notes
    )
    return (
        '<div class="dt-card" data-role="whatif-change">'
        '<h3 class="dt-title">Requested change</h3>'
        f'<p class="dt-mono">{theme.html(view.action)}</p>'
        f"{table}"
        + (f'<ul>{notes}</ul>' if notes else "")
        + "</div>"
    )


# =============================================================================
# PRD 16.3 — the before/after table and the predicted response
# =============================================================================
def _before_after_table(panel: Mapping[str, Any], fmt: Any) -> str:
    """Baseline vs scenario, over the same metric set as every PRD 14.5 baseline row."""
    rows = []
    for metric in panel.get("before_after", ()):
        rows.append(
            f"<tr><th>{theme.html(metric.get('tag', ''))}</th>"
            f'<td class="dt-num">{_num(metric.get("baseline"), fmt)}</td>'
            f'<td class="dt-num">{_num(metric.get("proposed"), fmt)}</td>'
            f'<td class="dt-num">{_num(metric.get("delta"), fmt)}</td>'
            f'<td class="dt-num">{_num(metric.get("delta_pct"), fmt)}</td></tr>'
        )
    if not rows:
        return (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this panel carries no '
            "before/after rows. No comparison numbers are shown rather than substituted "
            "ones.</p>"
        )
    return (
        '<table class="dt-table"><thead><tr><th>Metric</th><th>Baseline</th>'
        "<th>Scenario</th><th>&Delta;</th><th>&Delta;&nbsp;%</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _settled_table(settled: Mapping[str, Any], fmt: Any) -> str:
    """The settled state of the scenario: tag, value, unit — the payload's own prediction.

    The engine maps tag to a plain number (``proposed_state`` is ``Mapping[str, float]``);
    a richer payload may carry ``{"value": ..., "unit": ...}`` instead. Both shapes render,
    and a tag whose unit the payload does not state is left blank rather than guessed.
    """
    rows = []
    for tag, entry in settled.items():
        if isinstance(entry, Mapping):
            value, unit = entry.get("value"), str(entry.get("unit", ""))
        elif isinstance(entry, (int, float)) and not isinstance(entry, bool):
            value, unit = entry, ""
        else:
            continue
        rows.append(
            f"<tr><th>{theme.html(str(tag))}</th>"
            f'<td class="dt-num">{_num(value, fmt)}</td>'
            f'<td class="dt-muted">{theme.html(unit)}</td></tr>'
        )
    if not rows:
        return (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: the panel carries no settled '
            "state. No predicted values are shown rather than substituted ones.</p>"
        )
    return (
        '<table class="dt-table"><thead><tr><th>Tag</th><th>Settled value</th>'
        f"<th>Unit</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _response_section(view: Any, fmt: Any) -> str:
    """The predicted response: settled state, before/after, transition chart, savings line.

    The PRD 16.3 chart is drawn by :func:`_transition_chart` — each moved variable's commanded
    path over the payload's own window, so the hold and the configured ramp (the delay before
    anything is asked of the plant, and the non-instantaneous move itself) are visible rather
    than only numeric. What the payload states about the trajectory (window, hold, ramps,
    endpoint agreement) renders as text beneath the chart; the plant's response path is not on
    the payload and is never interpolated. A rejected request states that no trajectory exists
    — it was never simulated.
    """
    panel = view.panel if isinstance(view.panel, Mapping) else {}
    response = panel.get("predicted_process_response")
    response = response if isinstance(response, Mapping) else {}
    settled = response.get("settled_state")
    settled = settled if isinstance(settled, Mapping) else {}
    transition = response.get("transition")

    if transition is None:
        transition_html = (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: '
            f"{theme.html(NO_TRAJECTORY_TEXT)}.</p>"
        )
    else:
        transition_html = _transition_chart(transition, tuple(view.requested), fmt)
        if isinstance(transition, Mapping):
            ramps = ", ".join(
                f"{theme.html(name)} {_num_or_raw(minutes, fmt)} min"
                for name, minutes in (transition.get("ramp_minutes") or {}).items()
            )
            transition_html += (
                '<p class="dt-mono dt-muted">'
                f"window {theme.html(transition.get('minutes'))} min · "
                f"{theme.html(transition.get('rows'))} rows · "
                f"dt {theme.html(transition.get('dt_seconds'))} s · "
                f"hold {theme.html(transition.get('hold_minutes'))} min"
                + (f" · ramps: {ramps}" if ramps else "")
                + "</p>"
            )
    agreement = response.get("endpoint_agreement_relative")
    agreement_html = (
        f'<p class="dt-muted">Endpoint agreement (ramped trajectory vs settled state): '
        f"{_num(agreement, fmt)} relative"
        + (
            " — the window is too short for this move to have finished settling; read every "
            "reported number as the settled state."
            if response.get("endpoint_converged") is False
            else ""
        )
        + ".</p>"
        if agreement is not None
        else ""
    )

    impact = panel.get("energy_impact")
    impact = impact if isinstance(impact, Mapping) else {}
    savings = str(impact.get("savings_line", "") or "")
    savings_html = (
        f'<div class="dt-banner">{theme.html(savings)}</div>' if savings else ""
    )
    caveat = str(impact.get("caveat", "") or "")
    caveat_html = (
        f'<div class="dt-banner">{theme.html(caveat)}</div>' if caveat else ""
    )

    return (
        '<div class="dt-card" data-role="whatif-response">'
        '<h3 class="dt-title">Predicted response '
        + _badge(
            theme.provenance_label(Provenance.PREDICTION),
            theme.provenance_slug(Provenance.PREDICTION),
        )
        + "</h3>"
        '<h4 class="dt-title">Before / after (settled state vs baseline)</h4>'
        f"{_before_after_table(panel, fmt)}"
        f"{_settled_table(settled, fmt)}"
        '<h4 class="dt-title">Transition (PRD 16.2 — the delay is in the trajectory)</h4>'
        f"{transition_html}"
        f"{agreement_html}"
        f"{savings_html}"
        f"{caveat_html}"
        "</div>"
    )


# =============================================================================
# PRD 16.2 / 16.3 — the transition chart: inline SVG, no chart dependency
# =============================================================================
#: Chart geometry, in SVG user-space units — plain numbers, never ``var(--dt-*)``: a custom
#: property resolves in a CSS property, not in a geometry attribute (the twin's rule).
_CHART_W: Final[float] = 640.0
_CHART_H: Final[float] = 200.0
_CHART_PAD_L: Final[float] = 52.0
_CHART_PAD_R: Final[float] = 14.0
_CHART_PAD_T: Final[float] = 16.0
_CHART_PAD_B: Final[float] = 26.0

#: The y domain, in "percent of each variable's own commanded move" — padded so a 2 px stroke
#: never clips at the 0 % / 100 % rails. The per-variable normalisation is labelled on the
#: chart; each variable's real baseline → simulated numbers stay in the legend and the
#: requested-change table, so the picture carries the *timing* and the tables the magnitude.
_Y_MIN: Final[float] = -6.0
_Y_MAX: Final[float] = 106.0

#: One stroke colour per drawn variable, in payload order. These are display distinctions
#: only — *not* provenance badges (view I's channel is RECOMMENDATION throughout) — six deep
#: like the PRD 16.1 variable set, and wrapping deterministically beyond that.
_CHART_STROKES: Final[tuple[str, ...]] = (
    "var(--dt-accent)",
    "var(--dt-accent-alt)",
    "var(--dt-ok)",
    "var(--dt-warn)",
    "var(--dt-truth)",
    "var(--dt-configuration)",
)


def _transition_chart(
    transition: Any, requested: tuple[Mapping[str, Any], ...], fmt: Any
) -> str:
    """The PRD 16.3 transition chart as a self-contained inline SVG — the command path.

    What is drawn is the *commanded* setpoint path of every moved variable: the engine holds
    each setpoint at its baseline for ``hold_minutes``, then ramps it to the simulated value
    over that variable's configured ``ramp_minutes`` — the scheduler's own linear ramp
    (``_RampedSetpoint``), so a ramp of 0 is drawn as the step it is, and a ramp longer than
    the window is drawn still climbing at the window's end. Every number on the chart is a
    payload number; the only arithmetic here is that same hold-then-ramp interpolation, so
    the picture is the trajectory the engine commanded, reconstructed — never invented.

    The plant's *response* path is not on the payload (only its settled endpoints and the
    endpoint agreement are), so no response curve is drawn; the caption says so. Unusable or
    absent data is stated, never substituted: a request that moved nothing says so, and a
    moved variable whose ramp time the payload does not state is named rather than given an
    invented ramp.
    """

    def _f(value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    if not isinstance(transition, Mapping):
        return (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: the transition summary is '
            "not in a shape this renderer can chart, so no transition is drawn.</p>"
        )
    minutes = _f(transition.get("minutes"))
    hold = _f(transition.get("hold_minutes"))
    if minutes is None or minutes <= 0.0 or hold is None or hold < 0.0:
        return (
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: the payload carries no '
            "numeric transition window, so no transition is drawn rather than one with "
            "invented timing.</p>"
        )

    ramps = transition.get("ramp_minutes")
    ramps = ramps if isinstance(ramps, Mapping) else {}
    series: list[tuple[str, str, float, float, float]] = []
    untimed: list[str] = []
    for item in requested:
        name = str(item.get("name", ""))
        baseline, value = _f(item.get("baseline")), _f(item.get("value"))
        if baseline is None or value is None or baseline == value:
            continue  # the engine's own definition of "moved": value differs from baseline
        ramp = _f(ramps.get(name))
        if ramp is None or ramp < 0.0:
            untimed.append(name)
            continue
        series.append((name, str(item.get("unit", "")), baseline, value, ramp))
    if not series:
        if untimed:
            names = ", ".join(theme.html(name) for name in untimed)
            return (
                f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: the payload names no '
                f"ramp time for {names}, so no command path is drawn rather than one with "
                "invented timing.</p>"
            )
        return (
            '<p class="dt-muted">No manipulated variable moved — the request holds the '
            "current setpoints, so there is no transition to draw.</p>"
        )

    plot_w = _CHART_W - _CHART_PAD_L - _CHART_PAD_R
    plot_h = _CHART_H - _CHART_PAD_T - _CHART_PAD_B
    bottom = _CHART_PAD_T + plot_h

    def x(minute: float) -> float:
        return _CHART_PAD_L + max(0.0, min(minute, minutes)) / minutes * plot_w

    def y(pct: float) -> float:
        return _CHART_PAD_T + (1.0 - (pct - _Y_MIN) / (_Y_MAX - _Y_MIN)) * plot_h

    right = _CHART_PAD_L + plot_w
    rails = (
        f'<line class="dt-wi__rail" x1="{_CHART_PAD_L:.1f}" x2="{right:.1f}" '
        f'y1="{y(0.0):.1f}" y2="{y(0.0):.1f}"/>'
        f'<line class="dt-wi__rail" x1="{_CHART_PAD_L:.1f}" x2="{right:.1f}" '
        f'y1="{y(100.0):.1f}" y2="{y(100.0):.1f}"/>'
        f'<text class="dt-wi__tick" x="{_CHART_PAD_L - 8:.1f}" y="{y(0.0) + 4:.1f}" '
        'text-anchor="end">0%</text>'
        f'<text class="dt-wi__tick" x="{_CHART_PAD_L - 8:.1f}" y="{y(100.0) + 4:.1f}" '
        'text-anchor="end">100%</text>'
    )
    axis = (
        f'<line class="dt-wi__axis" x1="{_CHART_PAD_L:.1f}" x2="{right:.1f}" '
        f'y1="{bottom:.1f}" y2="{bottom:.1f}"/>'
    )
    guide = ""
    if 0.0 < hold < minutes:
        guide = (
            f'<line class="dt-wi__guide" x1="{x(hold):.1f}" x2="{x(hold):.1f}" '
            f'y1="{_CHART_PAD_T + 2:.1f}" y2="{bottom:.1f}"/>'
        )
    ticks = [
        f'<text class="dt-wi__tick" x="{x(0.0):.1f}" y="{_CHART_H - 8:.1f}" '
        'text-anchor="middle">0</text>'
    ]
    if 0.0 < hold < minutes:
        ticks.append(
            f'<text class="dt-wi__tick" x="{x(hold):.1f}" y="{_CHART_H - 8:.1f}" '
            f'text-anchor="middle">{theme.html(_num(hold, fmt))} · hold ends</text>'
        )
    ticks.append(
        f'<text class="dt-wi__tick" x="{right:.1f}" y="{_CHART_H - 8:.1f}" '
        f'text-anchor="end">{theme.html(_num(minutes, fmt))} min</text>'
    )
    notes = (
        f'<text class="dt-wi__note" x="{_CHART_PAD_L:.1f}" y="{_CHART_PAD_T - 4:.1f}">'
        "commanded setpoint, % of each move</text>"
        f'<text class="dt-wi__note" x="{right:.1f}" y="{_CHART_PAD_T - 4:.1f}" '
        'text-anchor="end">minutes from request · window end</text>'
    )

    lines: list[str] = []
    legend: list[str] = []
    for index, (name, unit, baseline, value, ramp) in enumerate(series):
        stroke = _CHART_STROKES[index % len(_CHART_STROKES)]
        complete = hold + ramp
        points = [(0.0, 0.0), (hold, 0.0)]
        if complete <= minutes:
            points += [(complete, 100.0), (minutes, 100.0)]
            timing = f"complete at {theme.html(_num(complete, fmt))} min"
        else:
            # The window ends mid-ramp: the last point is the ramp's own linear position
            # there — the payload-exact truncation, never a flattened tail.
            points.append((minutes, 100.0 * (minutes - hold) / ramp))
            timing = "still ramping at window end"
        poly = " ".join(f"{x(px):.1f},{y(py):.1f}" for px, py in points)
        lines.append(
            f'<polyline class="dt-wi__cmd" style="stroke:{stroke}" points="{poly}"/>'
        )
        move = f"{_num(baseline, fmt)} → {_num(value, fmt)}" + (
            f" {theme.html(unit)}" if unit else ""
        )
        legend.append(
            f'<span class="dt-wi__legend-item"><i class="dt-wi__swatch" '
            f'style="border-top-color:{stroke}"></i>{theme.html(name)} · ramp '
            f"{theme.html(_num_or_raw(ramp, fmt))} min · {timing} · {move}</span>"
        )

    svg = (
        f'<svg class="dt-wi__chart" viewBox="0 0 {_CHART_W:.0f} {_CHART_H:.0f}" role="img" '
        'aria-label="Commanded setpoint transition over the what-if window: the hold at the '
        'baseline, then each moved variable&#39;s configured ramp; the window ends where the '
        'settled state is reported.">'
        f"{rails}{axis}{guide}{''.join(ticks)}{notes}{''.join(lines)}</svg>"
    )
    return (
        '<div class="dt-wi__chartbox" data-role="whatif-transition">'
        f"{svg}"
        f'<div class="dt-wi__legend">{"".join(legend)}</div>'
        f'<p class="dt-muted">{theme.html(COMMAND_PATH_NOTE)}</p>'
        "</div>"
    )



# =============================================================================
# PRD 16.3 — the constraint / envelope banner, per constraint and per check
# =============================================================================
def _constraints_section(view: Any, fmt: Any) -> str:
    """Per-constraint PASS/REJECTED/FLAGGED rows plus per-envelope-check states.

    The words are the payload's own (the validator's, not a second explanation); an empty
    report is stated — never shown as if every constraint had passed.
    """
    panel = view.panel if isinstance(view.panel, Mapping) else {}
    constraint_rows = list(panel.get("constraint_rows", ()))
    envelope_rows = list(panel.get("envelope_rows", ()))
    if not constraint_rows and not envelope_rows:
        return (
            '<div class="dt-card" data-role="whatif-constraints">'
            '<h3 class="dt-title">Constraints &amp; envelope checks</h3>'
            f'<p class="dt-muted">{theme.html(UNAVAILABLE_TEXT)}: this panel carries no '
            "constraint or envelope rows. No constraint is shown as satisfied rather than "
            "substituted ones.</p></div>"
        )

    def _state_pill(state: object) -> str:
        text = str(state or "")
        kind = {"PASS": "ok", "REJECTED": "alarm"}.get(text, "warn")
        return _pill(text, kind)

    rows_html = []
    if constraint_rows:
        body = "".join(
            f"<tr><th>{theme.html(row.get('constraint', row.get('name', '')))}</th>"
            f"<td>{_state_pill(row.get('state', row.get('status')))}</td>"
            f'<td class="dt-num">{_num(row.get("value"), fmt)}</td>'
            f'<td class="dt-num">{_num(row.get("limit"), fmt)}</td>'
            f'<td class="dt-muted">{theme.html(row.get("detail", row.get("reason", "")))}</td></tr>'
            for row in constraint_rows
        )
        rows_html.append(
            '<table class="dt-table"><thead><tr><th>Constraint</th><th>State</th>'
            "<th>Value</th><th>Limit</th><th>Detail</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    if envelope_rows:
        body = "".join(
            f"<tr><th>{theme.html(row.get('check', row.get('name', '')))}</th>"
            f"<td>{_state_pill(row.get('state', row.get('status')))}</td>"
            f'<td class="dt-muted">{theme.html(row.get("detail", row.get("reason", "")))}</td></tr>'
            for row in envelope_rows
        )
        rows_html.append(
            '<table class="dt-table"><thead><tr><th>Envelope check</th><th>State</th>'
            "<th>Detail</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    statuses = []
    if panel.get("constraint_status"):
        statuses.append(_pill(f"constraint: {panel.get('constraint_status')}", "unknown"))
    if panel.get("envelope_status"):
        statuses.append(_pill(f"envelope: {panel.get('envelope_status')}", "unknown"))
    if panel.get("ood_status"):
        statuses.append(_pill(f"feature space: {panel.get('ood_status')}", "unknown"))
    return (
        '<div class="dt-card" data-role="whatif-constraints">'
        '<h3 class="dt-title">Constraints &amp; envelope checks '
        + "".join(statuses)
        + "</h3>"
        + "".join(rows_html)
        + "</div>"
    )


# =============================================================================
# Entry point
# =============================================================================
def render_what_if(model: Any, *, settings: Any, theme_name: str = theme.DARK) -> str:
    """View I as a themed HTML fragment (plain HTML — nothing on this screen animates).

    ``model`` is the view-I view model — anything shaped like
    :class:`~src.digital_twin.state.WhatIfViewModel` (a ``view`` shaped like
    :class:`~src.digital_twin.insights.WhatIfView`, the ``mode`` string and the ``sliders``
    tuple; the header ``app.py`` renders separately). ``settings`` is the
    :class:`~src.digital_twin.settings.DashboardSettings` the numeric formatting reads, so this
    renderer writes no precision of its own. The fragment carries its own scoped layout
    ``<style>`` and draws every colour and size from the theme variables, so it must sit inside
    a themed root — which :func:`app.build_document` provides.
    """
    view = model.view
    fmt = settings.format
    cards: list[str] = []
    if not view.available:
        cards.append(_unavailable_panel(view))
        cards.append(_sliders_section(tuple(model.sliders), fmt))
    else:
        cards.append(_banner_html(view.banner))
        cards.append(_sliders_section(tuple(model.sliders), fmt))
        cards.append(_change_section(view, fmt))
        cards.append(_response_section(view, fmt))
        cards.append(_constraints_section(view, fmt))
    return (
        f'<div class="{theme.theme_class(theme_name)}">'
        f"{_panel_style()}"
        '<div class="dt-wi">'
        f"{_status_strip(view)}"
        f"{''.join(cards)}"
        f'<div class="dt-banner">{theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)}</div>'
        "</div></div>"
    )

