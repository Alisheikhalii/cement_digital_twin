"""View J renderer tests (Wave View J): the AI Optimization panel and its routing.

Deliberately bounded, like ``test_task6_app_smoke.py``: nothing here builds a session or runs the
optimizer. The renderer under test is the real :mod:`src.visualization.optimization_view`, driven
by real :class:`~src.digital_twin.insights.OptimizationView` objects assembled from payload dicts
shaped exactly as ``OptimizationResult.describe()`` / ``BaselineComparison.describe()`` serialize
them — so what is asserted below is what a browser would receive from a real run, at stub cost.

Covers the three items this wave surfaces on one screen:

* **item 14** — the recommendation card renders from the payload and recomputes nothing;
* **item 15** (reconstructed) — the PRD 14.5 comparison shows **all five** rows (AC-22), and a row
  that could not be built shows "unavailable" with its own reason, never a zero or a blank;
* **item 16** — a refusal is a display state: headline, the gates' own reasons, rejection count.

Plus the honesty rules that reach every screen: no numeric confidence, no forbidden control label,
the standing no-plant-connection statement, and HTML escaping of the payload's free text.

Self-contained on purpose: no shared ``conftest.py`` fixture, so this module runs alone
(``pytest tests/test_task6_optimization_view.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.insights import OptimizationView
from src.digital_twin.provenance import Provenance
from src.digital_twin.settings import DashboardSettings
from src.visualization import optimization_view

#: The shared metric set, verbatim from ``configs/optimization.yaml`` ``baselines.metrics`` —
#: PRD 14.5's "same metric set", so the stub payload uses the real tag names.
METRICS = (
    "thermal_energy_kcal_per_kg_clinker",
    "specific_power_consumption_kwh_t",
    "clinker_production_tph",
    "cement_production_tph",
    "simulated_blaine_cm2_g",
)

#: The five PRD 14.5 titles in PRD order — what AC-22's "full Section 14.5 baseline set" means.
PRD_145_TITLES = (
    "Current Operating Point",
    "Historical Baseline",
    "Best Comparable Historical Condition",
    "Digital Twin Baseline (rule engine)",
    "AI-Optimized Operating Point",
)

UNAVAILABLE_ROW_DETAIL = "No historian rows to search for a comparable condition."


def _row(name: str, title: str, *, available: bool, detail: str, values: dict[str, Any]) -> dict[str, Any]:
    """One ``BaselineRow.describe()``-shaped dict."""
    return {
        "name": name,
        "title": title,
        "source": "observable_sensor_value" if name != "digital_twin_baseline" else "twin_simulation",
        "available": available,
        "detail": detail,
        "historian_rows": 1 if available else 0,
        "timestamp": "2024-01-01T00:00:00Z",
        "setpoints": {},
        "metrics": {tag: values.get(tag) for tag in METRICS},
    }


def _baselines_payload() -> dict[str, Any]:
    """A ``BaselineComparison.describe()``-shaped dict: four available rows, one unavailable.

    The Best Comparable row is unavailable on purpose — it is the row the frozen layer most often
    cannot build (no comparable window), so its display rule is the one this wave must pin.
    """
    values = {
        "thermal_energy_kcal_per_kg_clinker": 745.31,
        "specific_power_consumption_kwh_t": 38.9,
        "clinker_production_tph": 51.2,
        "cement_production_tph": 68.4,
        "simulated_blaine_cm2_g": None,  # an absent metric in an available row reads as no-value
    }
    rows = [
        _row("current_operating_point", PRD_145_TITLES[0], available=True,
             detail="Measured operating point at the time of the request.", values=values),
        _row("historical_baseline", PRD_145_TITLES[1], available=True,
             detail="Mean of the trailing 24 h in regime 'Normal - medium production'; 1440 rows.",
             values=values),
        _row("best_comparable_historical", PRD_145_TITLES[2], available=False,
             detail=UNAVAILABLE_ROW_DETAIL, values={}),
        _row("digital_twin_baseline", PRD_145_TITLES[3], available=True,
             detail="Twin steady state of the PRD 14.6 rule engine's suggested setpoints.",
             values=values),
        _row("ai_optimized_operating_point", PRD_145_TITLES[4], available=True,
             detail="Twin steady state of the recommended setpoints (PASS / WITHIN_ENVELOPE, "
                    "NORMAL mode, quality HIGH).",
             values=values),
    ]
    return {
        "metrics": list(METRICS),
        "available": [row["name"] for row in rows if row["available"]],
        "missing": ["best_comparable_historical"],
        "complete": False,
        "caveat": labels.SIMULATED_SAVING_CAVEAT,
        "rows": rows,
        "table": [],
    }


def _recommendation_payload(reason: str) -> dict[str, Any]:
    """A ``Recommendation.describe()``-shaped dict — the card renders from it unchanged."""
    return {
        "label": "Kiln fuel trim",
        "timestamp": "2024-01-01T00:00:00Z",
        "mode": "NORMAL",
        "envelope_status": "WITHIN_ENVELOPE",
        "constraint_status": "PASS",
        "recommendation_quality": "HIGH",
        "quality_description": labels.RECOMMENDATION_QUALITY_DESCRIPTION["HIGH"],
        "quality_reason": "ensemble spread tight",
        "reason": reason,
        "explanation": reason,
        "banner": None,
        "model_version": "model-c-1",
        "is_hold": False,
        "baseline_setpoints": {"kiln_fuel_rate_tph": 4.1},
        "proposed_setpoints": {"kiln_fuel_rate_tph": 4.02},
        "delta_fractions": {"kiln_fuel_rate_tph": -0.0195},
        "state_sources": {},
        "baseline_state": {},
        "proposed_state": {},
        "observed_state": {},
        "predicted_state_by_horizon": {},
        "expected_impact": {
            "metrics": [
                {
                    "tag": "thermal_energy_kcal_per_kg_clinker",
                    "baseline": 745.31,
                    "proposed": 738.62,
                    "delta": -6.69,
                    "delta_pct": -0.897,
                }
            ],
            "thermal_energy_kcal_per_day": -549216.0,
            "electrical_energy_kwh_per_day": 0.0,
            "daily_basis_hours": 24,
            "relative_uncertainty_pct": 2.1,
            "predicted_variability_pct": 1.4,
            "caveat": labels.SIMULATED_SAVING_CAVEAT,
        },
        "objective_breakdown": {},
        "objective": None,
        "envelope": None,
    }


def _gates_payload() -> tuple[dict[str, Any], ...]:
    return (
        {"gate": "operating_range", "state": "PASS", "blocking": False,
         "reason": "within trained ranges", "detail": {}},
        {"gate": "constraint_validation", "state": "REJECT", "blocking": True,
         "reason": "CO_ppm above its limit", "detail": {}},
    )


def _view(refused: bool = False, *, with_baselines: bool = True) -> OptimizationView:
    """A real ``OptimizationView``, assembled from payload dicts exactly as ``from_result`` would."""
    payload: dict[str, Any] = {
        "mode": "NORMAL",
        "message": "No safe recommendation found" if refused else "Kiln fuel trim recommended",
        "recommendation": None if refused else _recommendation_payload(
            "Fuel trim within <burning zone> margin"  # free text that must arrive escaped
        ),
        "baselines": _baselines_payload() if with_baselines else None,
    }
    return OptimizationView(
        available=True,
        timestamp="2024-01-01T00:00:00Z",
        mode="NORMAL",
        refused=refused,
        message="No safe recommendation found" if refused else "Kiln fuel trim recommended",
        payload=payload,
        gates=_gates_payload(),
        refusal_reasons=("CO_ppm above its limit",) if refused else (),
        rejected_candidates=3 if refused else 1,
        evaluated=12,
        provenance=Provenance.RECOMMENDATION,
    )


@dataclass(frozen=True)
class StubHeader:
    title: str = "AI Optimization"
    subtitle: str = "Decision support"


@dataclass(frozen=True)
class StubOptimizationViewModel:
    """Shaped like ``state.OptimizationViewModel``: a header plus the inner ``OptimizationView``."""

    header: StubHeader = field(default_factory=StubHeader)
    mode: str = "NORMAL"
    view: OptimizationView = None  # type: ignore[assignment]
    quality_descriptions: dict[str, str] = field(
        default_factory=lambda: dict(labels.RECOMMENDATION_QUALITY_DESCRIPTION)
    )


def _model(view: OptimizationView) -> StubOptimizationViewModel:
    return StubOptimizationViewModel(view=view)


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
# Item 15 — the PRD 14.5 comparison: all five rows, honest absences (AC-22)
# =============================================================================
def test_all_five_prd_145_baselines_are_shown(settings: DashboardSettings) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    for title in PRD_145_TITLES:
        assert title in html
    for tag in METRICS:
        assert tag in html


def test_unavailable_baseline_row_shows_its_reason_not_a_number(
    settings: DashboardSettings,
) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert optimization_view.UNAVAILABLE_ROW_TEXT in html
    assert UNAVAILABLE_ROW_DETAIL in html
    # The unavailable row's metric cells are one spanning "unavailable — <reason>" cell; the
    # honest absence marker, not a zero substituted into a metric column.
    assert f'{optimization_view.UNAVAILABLE_ROW_TEXT} — {UNAVAILABLE_ROW_DETAIL}' in html


def test_missing_row_names_are_summarised(settings: DashboardSettings) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert "best_comparable_historical" in html  # named in the "Missing rows" note


def test_absent_baselines_are_stated_never_invented(settings: DashboardSettings) -> None:
    """A run whose payload has no baselines at all: stated, with no substitute table."""
    html = optimization_view.render_optimization(
        _model(_view(with_baselines=False)), settings=settings
    )
    assert optimization_view.UNAVAILABLE_ROW_TEXT in html
    for title in PRD_145_TITLES[1:]:  # no row titles from a comparison that was never built
        assert title not in html


def test_baseline_metric_values_come_from_the_payload(settings: DashboardSettings) -> None:
    """The numbers shown are the payload's own - formatted, not recomputed or re-derived."""
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert "745.3" in html  # thermal metric at FormatSettings precision
    assert "38.90" in html


# =============================================================================
# Item 14 — the recommendation card renders from the payload, recomputes nothing
# =============================================================================
def test_recommendation_card_shows_quality_category_not_a_percentage(
    settings: DashboardSettings,
) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert labels.AI_RECOMMENDATION_LABEL in html
    assert "HIGH" in html
    assert labels.RECOMMENDATION_QUALITY_DESCRIPTION["HIGH"] in html
    assert "confidence" not in html.lower()


def test_impact_numbers_are_the_payloads_own(settings: DashboardSettings) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    # The payload's own values at FormatSettings precision (4 significant digits, 3 decimals):
    # proposed 738.62 -> "738.6", delta -6.69 -> "-6.690". Recomputation would not reproduce these
    # from the stub's single metric row.
    assert "738.6" in html
    assert "-6.690" in html


def test_free_text_from_the_payload_is_escaped(settings: DashboardSettings) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert "Fuel trim within &lt;burning zone&gt; margin" in html


# =============================================================================
# Item 16 — a refusal is a display state, not an empty card
# =============================================================================
def test_refusal_shows_headline_and_the_gates_own_reasons(
    settings: DashboardSettings,
) -> None:
    html = optimization_view.render_optimization(_model(_view(refused=True)), settings=settings)
    assert labels.NO_SAFE_RECOMMENDATION in html
    assert "CO_ppm above its limit" in html
    assert 'data-role="refusal"' in html


def test_gates_table_marks_the_blocking_gate(settings: DashboardSettings) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert "operating_range" in html and "constraint_validation" in html
    assert "blocking" in html


# =============================================================================
# Item 20 — honesty vocabulary and the unavailable panel
# =============================================================================
def test_panel_carries_the_standing_statement_and_no_control_claim(
    settings: DashboardSettings,
) -> None:
    html = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html
    assert labels.SIMULATED_SAVING_CAVEAT in html
    assert labels.FORBIDDEN_CONTROL_LABEL not in html


def test_unavailable_model_is_stated_not_substituted(settings: DashboardSettings) -> None:
    view = OptimizationView.unavailable("2024-01-01T00:00:00Z")
    html = optimization_view.render_optimization(_model(view), settings=settings)
    assert labels.MODEL_UNAVAILABLE_LABEL in html
    assert labels.MODEL_UNAVAILABLE_STATEMENT in html
    assert "745.3" not in html  # no number from a model that is not there


# =============================================================================
# The accessor (insights.py) and the app.py routing
# =============================================================================
def test_baselines_accessor_exposes_the_payload_mapping() -> None:
    view = _view()
    baselines = view.baselines()
    assert isinstance(baselines, dict)
    assert baselines["missing"] == ["best_comparable_historical"]
    assert [row["name"] for row in baselines["rows"]] == [
        "current_operating_point",
        "historical_baseline",
        "best_comparable_historical",
        "digital_twin_baseline",
        "ai_optimized_operating_point",
    ]


def test_baselines_accessor_returns_none_when_absent() -> None:
    assert _view(with_baselines=False).baselines() is None


def test_app_routes_view_j_to_the_renderer_not_the_raw_payload(
    settings: DashboardSettings,
) -> None:
    html, timings = app.build_document(
        StubState({"J": _model(_view())}), ["J"], settings=settings
    )
    assert list(timings) == ["J"]
    # Not the JSON fallback: its marker sentence is absent and no <pre> payload block is rendered.
    assert "no renderer for this screen yet" not in html
    assert 'class="dt-mono dt-app__payload"' not in html
    assert "AI Optimization" in html
    for title in PRD_145_TITLES:
        assert title in html


def test_app_keeps_the_payload_fallback_for_other_non_twin_views(
    settings: DashboardSettings,
) -> None:
    @dataclass(frozen=True)
    class OtherView:
        header: StubHeader = field(default_factory=lambda: StubHeader("Energy Monitoring", "kWh/t"))

        def describe(self) -> dict[str, Any]:
            return {"kpis": {"specific_energy": 101.5}}

    html, _ = app.build_document(
        StubState({"G": OtherView()}), ["G"], settings=settings
    )
    assert "dt-app__payload" in html  # unchanged behaviour for views without a renderer


# =============================================================================
# Golden regression — the renderer's whole output, pinned (Wave View J closeout)
# =============================================================================
#: The stored render of the stub payload above. Regenerate after a *deliberate* renderer change:
#:
#:     python -c "from pathlib import Path; from tests.test_task6_optimization_view import \
#: _model, _view; from src.digital_twin.settings import DashboardSettings; \
#: from src.visualization import optimization_view; \
#: Path('tests/golden/view_j_normal.html').write_bytes(optimization_view.render_optimization(\
#: _model(_view()), settings=DashboardSettings.from_config()).encode('utf-8'))"
#:
#: Written with ``write_bytes`` so the fixture keeps its LF newlines in the repository; the
#: comparison below normalises either way, because ``core.autocrlf`` checkouts differ by machine.
GOLDEN_PATH = Path(__file__).parent / "golden" / "view_j_normal.html"

GOLDEN_HINT = (
    "view J's renderer no longer matches its golden file. This is a REGRESSION unless the renderer "
    "was deliberately changed - in which case regenerate the fixture with the command in the "
    "GOLDEN_PATH comment and say so in the commit message. The golden payload is the stub built by "
    "_view() in this module: fixed timestamps, no measured durations, no wall clock, so nothing "
    "runtime-dependent is pinned."
)


def _golden() -> str:
    return GOLDEN_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_renderer_is_byte_stable_for_a_fixed_payload(settings: DashboardSettings) -> None:
    """The precondition the golden file rests on: same payload in, same bytes out.

    The twin's convention (``test_task6_twin.py``), restated for this renderer: two renders in one
    process must be byte-identical, which is what would catch a wall clock, a random draw or an
    unordered iteration leaking onto the render path - before the golden file is blamed.
    """
    first = optimization_view.render_optimization(_model(_view()), settings=settings)
    second = optimization_view.render_optimization(_model(_view()), settings=settings)
    assert first == second, GOLDEN_HINT


def test_the_render_matches_the_golden_file(settings: DashboardSettings) -> None:
    """The whole output, pinned byte for byte - a silent formatting or wording change fails here.

    Every string assertion above names one property; this one holds the *shape of the whole panel*
    at once, so a change no single property test thought to name (a reordered attribute, a changed
    class name, a reworded heading) still fails. The golden payload is built from the fixed stub
    in this module, so the comparison pins the renderer, not the run: no timestamp, duration or
    measured value enters it.
    """
    html = optimization_view.render_optimization(_model(_view()), settings=settings)

    assert html == _golden(), GOLDEN_HINT
    # The fixture is not empty and not a stale stub of itself: it carries the panel's anchors.
    assert 'data-role="recommendation"' in html
    assert 'data-role="baselines"' in html
