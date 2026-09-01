"""View H renderer tests (Wave View H): the AI Prediction & Anomaly panel and its routing.

Deliberately bounded, like ``test_task6_optimization_view.py``: nothing here builds a session,
trains a model or runs the detector. The renderer under test is the real
:mod:`src.visualization.intelligence_view`, driven by real
:class:`~src.digital_twin.insights.PredictionSet` / :class:`~src.digital_twin.insights.AnomalyState`
objects and the real row-assembly the state layer uses
(``DashboardState._prediction_rows``) — so what is asserted below is what a browser would
receive from a real run, at stub cost.

Covers the items this wave surfaces on one screen:

* **item 10** — Model A's own forecast grid: every configured horizon as a column, the observed
  ``Current`` column in the OBSERVED channel and the forecasts in the PREDICTION channel — two
  channels, visibly separate, never one series; the spread shown as ``±`` and never a
  confidence percentage (AC-16, AC-18);
* **item 11** — Model B's verdict in the PRD 15 contract lines, the "Evidence inconclusive"
  display state (pinned through :meth:`AnomalyState.from_report` on a real frozen-layer
  ``AnomalyReport`` — its first test), and the NORMAL "No anomaly detected" state.

Plus the honesty rules that reach every screen: no numeric confidence, no forbidden control
label, the standing no-plant-connection statement, and HTML escaping of the payload's free text.

Self-contained on purpose: no shared ``conftest.py`` fixture, so this module runs alone
(``pytest tests/test_task6_intelligence_view.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import app
from src import labels
from src.anomaly_detection.detector import (
    INCONCLUSIVE_HYPOTHESIS,
    UNDETERMINED_ANOMALY,
    AnomalyReport,
)
from src.digital_twin.insights import AnomalyState, PredictionSet
from src.digital_twin.provenance import Provenance, Value
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import DashboardState
from src.visualization import intelligence_view

#: The four PRD 13.1 mandatory horizons, verbatim from ``configs/ml.yaml``
#: ``prediction.horizons_min`` — the column set the item-10 grid must show.
HORIZONS = (5, 10, 15, 30)

#: The (target, horizon) Model A pairs the stub payload records as untrained — serialized
#: exactly as ``PredictionSet.missing`` builds them (``"<target> t+<minutes>min"``).
MISSING = (
    "oxygen_percent t+10min",
    "oxygen_percent t+30min",
    "clinker_production_tph t+5min",
    "clinker_production_tph t+10min",
    "clinker_production_tph t+15min",
    "clinker_production_tph t+30min",
)


def _value(
    tag: str,
    value: float,
    provenance: Provenance,
    *,
    unit: str = "degC",
    uncertainty: float | None = None,
    horizon: int | None = None,
) -> Value:
    """One payload ``Value``, carrying only what the provider layer actually sets."""
    return Value(
        tag=tag,
        value=value,
        unit=unit,
        provenance=provenance,
        source=f"stub/{tag}",
        uncertainty=uncertainty,
        horizon_min=horizon,
    )


def _prediction_set() -> PredictionSet:
    """A normal kiln ``PredictionSet``: two targets forecast, two more wholly missing.

    ``burning_zone_temperature`` is predicted at every horizon; ``oxygen_percent`` is missing
    at t+10 and t+30 (its pairs sit in ``missing``) and carries no ``uncertainty`` at t+15, so
    the no-spread display rule is pinned alongside the missing-pair one.
    ``clinker_production_tph`` has no forecast at all — every pair sits in ``missing`` — so its
    row is one of stated absences, never of zeros.
    """
    def forecast(minutes: int, values: tuple[Value, ...]) -> tuple[Value, ...]:
        return tuple(_value(v.tag, v.value, Provenance.PREDICTION,
                            unit=v.unit, uncertainty=v.uncertainty, horizon=minutes)
                     for v in values)

    by_horizon = {
        5: forecast(5, (
            _value("burning_zone_temperature", 1452.3, Provenance.PREDICTION, uncertainty=6.1),
            _value("oxygen_percent", 3.21, Provenance.PREDICTION, unit="%", uncertainty=0.11),
        )),
        10: forecast(10, (
            _value("burning_zone_temperature", 1453.8, Provenance.PREDICTION, uncertainty=7.4),
        )),
        15: forecast(15, (
            _value("burning_zone_temperature", 1454.1, Provenance.PREDICTION, uncertainty=8.2),
            _value("oxygen_percent", 3.18, Provenance.PREDICTION, unit="%", uncertainty=None),
        )),
        30: forecast(30, (
            _value("burning_zone_temperature", 1455.6, Provenance.PREDICTION, uncertainty=9.9),
        )),
    }
    current = (
        _value("burning_zone_temperature", 1451.2, Provenance.OBSERVED),
        _value("oxygen_percent", 3.24, Provenance.OBSERVED, unit="%"),
    )
    return PredictionSet(
        available=True,
        dataset="kiln",
        timestamp="2024-01-01T00:00:00Z",
        current=current,
        by_horizon=by_horizon,
        horizons_min=HORIZONS,
        missing=MISSING,
        model_version="model-a-kiln-v1",
    )


def _anomaly_state() -> AnomalyState:
    """A WARNING-state ``AnomalyState``: every PRD 15 contract line populated."""
    return AnomalyState(
        available=True,
        dataset="kiln",
        timestamp="2024-01-01T00:00:00Z",
        status="WARNING",
        is_anomaly=True,
        score=-0.62,
        hypothesis="consistent with a process deviation - the pattern of affected tags matches a "
                   "process condition rather than a single drifting transmitter",
        display_cause="Low Oxygen Condition",
        nearest_regime="Low Oxygen Condition",
        regime_similarity=0.91,
        affected_variables=(
            {"tag": "oxygen_percent", "direction": "low", "z_score": -3.2},
            {"tag": "burning_zone_temperature", "direction": "low", "z_score": -2.4},
        ),
        suggested_action="Increase ID fan speed",
        anomaly_kind="process",
        out_of_distribution=False,
    )


@dataclass(frozen=True)
class StubHeader:
    title: str = "AI Prediction & Anomaly"
    subtitle: str = "Model A forecast · Model B anomaly"


@dataclass(frozen=True)
class StubIntelligenceView:
    """Shaped like ``state.IntelligenceView``: the two payloads plus the assembled grid."""

    header: StubHeader = field(default_factory=StubHeader)
    dataset: str = "kiln"
    predictions: PredictionSet = None  # type: ignore[assignment]
    anomaly: AnomalyState = None  # type: ignore[assignment]
    columns: tuple[str, ...] = ()
    rows: tuple[Any, ...] = ()
    trends: tuple[Any, ...] = ()


def _model(
    predictions: PredictionSet | None = None, anomaly: AnomalyState | None = None
) -> StubIntelligenceView:
    predictions = predictions if predictions is not None else _prediction_set()
    return StubIntelligenceView(
        predictions=predictions,
        anomaly=anomaly if anomaly is not None else _anomaly_state(),
        rows=DashboardState._prediction_rows(predictions),
    )


class StubState:
    def __init__(self, models: dict[str, Any]) -> None:
        self._models = models

    def view(self, view_id: str) -> Any:
        return self._models[view_id]


@pytest.fixture(scope="module")
def settings() -> DashboardSettings:
    """The real dashboard settings - a YAML parse, milliseconds, no session."""
    return DashboardSettings.from_config()


# =============================================================================
# A — normal prediction + anomaly rendering
# =============================================================================
def test_the_two_payloads_render_as_their_own_cards(settings: DashboardSettings) -> None:
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert 'data-role="predictions"' in html
    assert 'data-role="anomaly"' in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


def test_prediction_grid_shows_every_configured_horizon_and_both_forecast_targets(
    settings: DashboardSettings,
) -> None:
    """The full PRD 13.1 horizon set as columns (AC-16), one row per target the payload names."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    for minutes in HORIZONS:
        assert f"<th>t+{minutes}</th>" in html
    assert "burning_zone_temperature" in html
    assert "oxygen_percent" in html


def test_predicted_values_and_spreads_are_the_payloads_own(
    settings: DashboardSettings,
) -> None:
    """Value and ± spread come from the payload at FormatSettings precision; a missing spread
    shows the value alone (never a derived one) — and no percentage is computed anywhere."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "1,451" in html  # observed current (magnitude rule: 0 decimals)
    assert "1,452" in html  # burning_zone_temperature at t+5
    assert "&plusmn; 6.100" in html  # its uncertainty, as a spread
    assert "3.210" in html  # oxygen_percent at t+5 (3 decimals)
    assert "Model version: model-a-kiln-v1" in html  # PRD 13.4 provenance


# =============================================================================
# H — the PREDICTION channel stays visibly separate (item 10's two-channel rule)
# =============================================================================
def test_the_grid_is_labelled_as_two_separate_channels(settings: DashboardSettings) -> None:
    """The forecast columns carry the PREDICTION badge and the Current column its OBSERVED one,
    so the observed state can never be read as one series with the predictions."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "Model prediction" in html  # the PREDICTION badge wording (PROVENANCE_LABELS)
    assert "dt-badge--prediction" in html
    assert "dt-badge--observed" in html
    assert "<th>Current</th>" in html


def theme_prediction_badge() -> str:
    return "Model prediction"


# =============================================================================
# G — no fabricated numeric confidence
# =============================================================================
def test_no_numeric_confidence_is_fabricated_anywhere(settings: DashboardSettings) -> None:
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "confidence" not in html.lower()
    assert labels.FORBIDDEN_CONTROL_LABEL not in html


def test_the_anomaly_score_is_the_payloads_own_not_a_derived_one(
    settings: DashboardSettings,
) -> None:
    """The PRD 17 view-7 "live anomaly score" is Model B's own number, shown as-is."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "Anomaly score: -0.620" in html


# =============================================================================
# C — missing horizon / missing target: stated absences, never zeros
# =============================================================================
def test_missing_horizon_cells_show_the_payloads_reason_not_a_number(
    settings: DashboardSettings,
) -> None:
    """A (target, horizon) pair the payload records in ``missing`` shows unavailable plus the
    untrained-model reason — the payload's own account — never a zero or a blank."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert (
        f"{intelligence_view.UNAVAILABLE_TEXT} — {intelligence_view.MISSING_MODEL_TEXT}"
        in html
    )
    # All six recorded pairs are cells in the grid: oxygen's two, clinker's four.
    assert html.count(intelligence_view.MISSING_MODEL_TEXT) == len(MISSING)


def test_a_wholly_missing_target_gets_a_row_of_stated_absences(
    settings: DashboardSettings,
) -> None:
    """A target with no forecast at all still appears as a row — every cell unavailable, the
    current cell the no-value glyph — rather than vanishing from the grid."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "clinker_production_tph" in html
    # Its current cell is the absence glyph, not a zero: the row carries no observed Value.
    assert "<td class=\"dt-num\">—</td>" in html


# =============================================================================
# B / D — missing prediction, unavailable model: stated, never substituted
# =============================================================================
def test_missing_predictions_show_the_models_own_reason(
    settings: DashboardSettings,
) -> None:
    view = _model(
        predictions=PredictionSet.unavailable(
            "kiln",
            "2024-01-01T00:00:00Z",
            "Model A could not build a complete feature row for this timestamp: "
            "Input contains NaN",
        )
    )
    html = intelligence_view.render_intelligence(view, settings=settings)
    assert labels.MODEL_UNAVAILABLE_LABEL in html
    assert "Input contains NaN" in html  # the model's own words
    assert "1,452" not in html  # no number from a model that is not there
    assert 'data-role="predictions"' in html


def test_an_unavailable_anomaly_model_is_stated_not_substituted(
    settings: DashboardSettings,
) -> None:
    view = _model(anomaly=AnomalyState.unavailable("kiln", "2024-01-01T00:00:00Z"))
    html = intelligence_view.render_intelligence(view, settings=settings)
    assert labels.MODEL_UNAVAILABLE_LABEL in html
    assert labels.MODEL_UNAVAILABLE_STATEMENT in html
    assert "WARNING" not in html  # no anomaly manufactured from an absent model
    assert 'data-role="anomaly"' in html


# =============================================================================
# F — the PRD 15 warning card, line by line
# =============================================================================
def test_anomaly_warning_card_shows_the_prd_15_contract(
    settings: DashboardSettings,
) -> None:
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "WARNING" in html
    assert "<strong>Detected anomaly:</strong> Low Oxygen Condition" in html
    assert labels.ANOMALY_HYPOTHESIS_LABEL in html  # the VERBATIM PRD 15 label
    assert "<strong>Affected variables:</strong> oxygen_percent (low, z=-3.2)" in html
    assert labels.RULE_BASED_SUGGESTION_LABEL in html  # the VERBATIM "not a diagnosis" label
    assert "Increase ID fan speed" in html


def test_a_normal_row_renders_no_anomaly_detected(settings: DashboardSettings) -> None:
    """A NORMAL verdict is a populated card ("No anomaly detected"), not a blank one."""
    anomaly = AnomalyState(
        available=True,
        dataset="kiln",
        timestamp="2024-01-01T00:00:00Z",
        status="NORMAL",
        is_anomaly=False,
        score=0.12,
    )
    html = intelligence_view.render_intelligence(_model(anomaly=anomaly), settings=settings)
    assert intelligence_view.NO_ANOMALY_TEXT in html
    assert "WARNING" not in html
    assert "Detected anomaly" not in html


def test_an_anomaly_with_no_flagged_variables_states_that(
    settings: DashboardSettings,
) -> None:
    """The frozen layer's own fallback wording, never a blank affected-variables line."""
    anomaly = AnomalyState(
        available=True, dataset="kiln", timestamp="t", status="WARNING", is_anomaly=True,
        display_cause="Unclassified deviation", affected_variables=(),
    )
    html = intelligence_view.render_intelligence(_model(anomaly=anomaly), settings=settings)
    assert intelligence_view.NO_VARIABLES_TEXT in html


# =============================================================================
# E — "Evidence inconclusive" (item 11), pinned through the real from_report mapping
# =============================================================================
def _inconclusive_report() -> AnomalyReport:
    """A frozen-layer ``AnomalyReport`` whose evidence cannot separate fault from process.

    ``anomaly_kind`` is ``UNDETERMINED_ANOMALY`` — the SPC warm-up state the detector's own
    signature logic reads as "the separation cannot be measured" — which is one of the three
    branches ``AnomalyState.from_report`` maps to the inconclusive display.
    """
    return AnomalyReport(
        dataset="kiln",
        timestamp="2024-01-01T00:00:00Z",
        status="WARNING",
        detected_anomaly="Sensor drift",
        hypothesis=INCONCLUSIVE_HYPOTHESIS,
        affected_variables=({"tag": "oxygen_percent", "direction": "high", "z_score": 4.1},),
        suggested_action="Cross-check the O2 transmitter against the redundancy row.",
        anomaly_score=-0.71,
        flagged=True,
        out_of_distribution=False,
        ood_ratio=1.0,
        anomaly_kind=UNDETERMINED_ANOMALY,
        regime_similarity=float("nan"),
        evidence={},
    )


def test_from_report_maps_undetermined_evidence_to_the_inconclusive_label() -> None:
    """Gap G-4 of the View H audit: this display branch had zero tests. The *cause* reads the
    VERBATIM label; the nearest signature survives under its own name as a similarity match —
    never as a cause."""
    state = AnomalyState.from_report(_inconclusive_report())
    assert state.inconclusive is True
    assert state.display_cause == labels.EVIDENCE_INCONCLUSIVE_LABEL
    assert state.nearest_regime == "Sensor drift"  # carried, not promoted to the cause
    assert state.regime_similarity is None  # NaN similarity is dropped, not shown as a number


def test_the_inconclusive_cause_renders_as_the_label_not_a_regime(
    settings: DashboardSettings,
) -> None:
    html = intelligence_view.render_intelligence(
        _model(anomaly=AnomalyState.from_report(_inconclusive_report())), settings=settings
    )
    assert f"<strong>Detected anomaly:</strong> {labels.EVIDENCE_INCONCLUSIVE_LABEL}" in html
    # The signature still appears, under its own similarity-match label — not as the cause.
    assert "Nearest regime signature (similarity match, not a cause): Sensor drift" in html


def test_a_classified_anomaly_keeps_the_regime_as_the_cause(
    settings: DashboardSettings,
) -> None:
    """The non-inconclusive branch: the detected regime *is* the cause, with its similarity."""
    html = intelligence_view.render_intelligence(_model(), settings=settings)
    assert "<strong>Detected anomaly:</strong> Low Oxygen Condition" in html
    assert "Nearest regime signature (similarity match, not a cause): Low Oxygen Condition" in html
    assert "cosine +0.910" in html


# =============================================================================
# Honesty rules that reach every rendering
# =============================================================================
def test_free_text_from_the_payload_is_escaped(settings: DashboardSettings) -> None:
    anomaly = AnomalyState(
        available=True, dataset="kiln", timestamp="t", status="WARNING", is_anomaly=True,
        hypothesis="drift <inside> the O2 tag",
        display_cause="Low <Oxygen> Condition",
        affected_variables=(), suggested_action="check & verify",
    )
    html = intelligence_view.render_intelligence(_model(anomaly=anomaly), settings=settings)
    assert "drift &lt;inside&gt; the O2 tag" in html
    assert "Low &lt;Oxygen&gt; Condition" in html
    assert "check &amp; verify" in html


def test_out_of_distribution_rows_carry_their_own_pill(settings: DashboardSettings) -> None:
    anomaly = AnomalyState(
        available=True, dataset="kiln", timestamp="t", status="ALARM", is_anomaly=True,
        display_cause="Fan instability", out_of_distribution=True,
    )
    html = intelligence_view.render_intelligence(_model(anomaly=anomaly), settings=settings)
    assert "out of distribution" in html
    assert "ALARM" in html


# =============================================================================
# I — deterministic output
# =============================================================================
def test_the_renderer_is_byte_stable_for_a_fixed_payload(settings: DashboardSettings) -> None:
    """The precondition the golden file rests on: same payload in, same bytes out.

    The twin's convention (``test_task6_twin.py``), restated for this renderer: two renders in
    one process must be byte-identical, which is what would catch a wall clock, a random draw
    or an unordered iteration leaking onto the render path - before the golden file is blamed.
    """
    first = intelligence_view.render_intelligence(_model(), settings=settings)
    second = intelligence_view.render_intelligence(_model(), settings=settings)
    assert first == second, GOLDEN_HINT


# =============================================================================
# The app.py routing
# =============================================================================
def test_app_routes_view_h_to_the_renderer_not_the_raw_payload(
    settings: DashboardSettings,
) -> None:
    html, timings = app.build_document(
        StubState({"H": _model()}), ["H"], settings=settings
    )
    assert list(timings) == ["H"]
    # Not the JSON fallback: its marker sentence is absent and no <pre> payload block is rendered.
    assert "no renderer for this screen yet" not in html
    assert 'class="dt-mono dt-app__payload"' not in html
    assert "AI Prediction &amp; Anomaly" in html
    assert 'data-role="predictions"' in html
    assert 'data-role="anomaly"' in html


def test_app_keeps_the_renderer_away_from_the_other_screens(
    settings: DashboardSettings,
) -> None:
    """The duck-typed predicate must not swallow a view it does not own: view J's model (which
    carries an inner ``view`` attribute, not ``predictions``/``anomaly``) still falls through
    to its own renderer or the fallback, unchanged."""

    @dataclass(frozen=True)
    class OtherView:
        header: StubHeader = field(default_factory=lambda: StubHeader("Energy Monitoring", "kWh/t"))

        def describe(self) -> dict[str, Any]:
            return {"kpis": {"specific_energy": 101.5}}

    html, _ = app.build_document(StubState({"G": OtherView()}), ["G"], settings=settings)
    assert "dt-app__payload" in html  # unchanged behaviour for views without a renderer


# =============================================================================
# Golden regression — the renderer's whole output, pinned (Wave View H)
# =============================================================================
#: The stored render of the stub payload above. Regenerate after a *deliberate* renderer change:
#:
#:     python -c "from pathlib import Path; from tests.test_task6_intelligence_view import \
#: _model; from src.digital_twin.settings import DashboardSettings; \
#: from src.visualization import intelligence_view; \
#: Path('tests/golden/view_h_normal.html').write_bytes(intelligence_view.render_intelligence(\
#: _model(), settings=DashboardSettings.from_config()).encode('utf-8'))"
#:
#: Written with ``write_bytes`` so the fixture keeps its LF newlines in the repository; the
#: comparison below normalises either way, because ``core.autocrlf`` checkouts differ by machine.
GOLDEN_PATH = Path(__file__).parent / "golden" / "view_h_normal.html"

GOLDEN_HINT = (
    "view H's renderer no longer matches its golden file. This is a REGRESSION unless the renderer "
    "was deliberately changed - in which case regenerate the fixture with the command in the "
    "GOLDEN_PATH comment and say so in the commit message. The golden payload is the stub built by "
    "_model() in this module: fixed timestamps, no measured durations, no wall clock, so nothing "
    "runtime-dependent is pinned."
)


def _golden() -> str:
    return GOLDEN_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_render_matches_the_golden_file(settings: DashboardSettings) -> None:
    """The whole output, pinned byte for byte - a silent formatting or wording change fails here.

    Every string assertion above names one property; this one holds the *shape of the whole panel*
    at once, so a change no single property test thought to name (a reordered attribute, a changed
    class name, a reworded heading) still fails. The golden payload is built from the fixed stub
    in this module, so the comparison pins the renderer, not the run: no timestamp, duration or
    measured value enters it.
    """
    html = intelligence_view.render_intelligence(_model(), settings=settings)

    assert html == _golden(), GOLDEN_HINT
    # The fixture is not empty and not a stale stub of itself: it carries the panel's anchors.
    assert 'data-role="predictions"' in html
    assert 'data-role="anomaly"' in html
