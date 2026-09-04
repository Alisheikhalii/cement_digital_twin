"""Factory Presentation Mode tests (Wave Item 17): the PRD 29 overlay and its routing.

Deliberately bounded, like ``test_task6_overview_view.py`` and
``test_task6_optimization_view.py``: nothing here trains a model or runs the real optimizer. The
renderer under test is the real :mod:`src.visualization.presentation_view`, driven by real
view-model objects (:class:`~src.digital_twin.state.OverviewStageView`,
:class:`~src.digital_twin.state.OverviewStatus`,
:class:`~src.digital_twin.insights.OptimizationView`) and the real state-layer tile mappers, over
a stub recommendation payload that mirrors the keys
:meth:`src.optimization.recommendation.Recommendation.describe` serializes — so what is asserted
below is what a browser would receive from a real run, at stub cost. The state-layer composition
test wires the shared ``stub_provider`` fixture into a real
:class:`~src.digital_twin.state.DashboardState`, which costs milliseconds.

Covers what PRD 29 mandates for this mode:

* **the five KPI cards** — the two saving cards carry the expected impact's own daily-energy
  deltas at ``presentation.headline_decimals`` precision with the "Simulation Estimate" label;
  the two stability cards are honest gaps (no model computes either metric) and never a
  fabricated number; the anomaly card carries Model B's own verdict, never an invented count;
* **the five-stage chain** — Current Plant State → AI Prediction → Optimization Opportunity →
  Recommended Action → Expected Benefit, in the PRD's own order, with refusals as display states
  (item 16) and unavailable models stating their own reason;
* **the §21 footnote** — the transfer-strategy statement, verbatim, in a visible block;
* **what never appears** — no numeric confidence percentage, no raw tag readout lists, no model
  internals, no code, no forbidden control label;
* **routing** — ``app.build_document`` dispatches the overlay's view model to the presentation
  renderer, the ``_PresentationRequest`` wrapper serves the ``P`` / ``presentation`` ids, and the
  generic :data:`~src.digital_twin.state.VIEWS` dispatch is untouched (this mode is an overlay,
  not an eleventh screen — directive item 2's ten rows are pinned).

Self-contained on purpose: no shared ``conftest.py`` fixture beyond the documented
``stub_provider`` factory, so this module runs alone
(``pytest tests/test_task6_presentation_view.py``).
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.insights import AnomalyState, OptimizationView
from src.digital_twin.payloads import EquipmentStatus, KpiGroup
from src.digital_twin.provenance import Provenance, Status, Value
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import (
    OverviewStageView,
    OverviewStatus,
    _ai_status_tile,
    _anomaly_status_tile,
)
from src.visualization import presentation_view, theme


# =============================================================================
# Stubs — shaped like the payload the real builders assemble
# =============================================================================
def _value(
    tag: str,
    value: float | None,
    *,
    unit: str = "t/h",
    status: Status = Status.OK,
    description: str = "",
    provenance: Provenance = Provenance.OBSERVED,
) -> Value:
    """One payload ``Value``, carrying only what the provider layer actually sets."""
    return Value(
        tag=tag,
        value=value,
        unit=unit,
        provenance=provenance,
        source=f"stub/{tag}",
        description=description,
        status=status,
    )


def _stage(name: str, title: str, *, state: str = "RUNNING") -> OverviewStageView:
    return OverviewStageView(
        name=name,
        title=title,
        detail=f"stub detail for {title}",
        rate=_value(f"{name}_rate_tph", 100.0),
        state=state,
        moving=state == labels.EQUIPMENT_RUNNING,
        equipment=(),
    )


#: The five stages of directive item 3, in process order, as the view model assembles them.
def _stages() -> tuple[OverviewStageView, ...]:
    return (
        _stage("feed", "Quarry / feed"),
        _stage("kiln_system", "Kiln system"),
        _stage("clinker", "Clinker", state=labels.EQUIPMENT_IDLE),
        _stage("cement_mill", "Cement mill"),
        _stage("cement_product", "Cement product"),
    )


#: A recommendation payload mirroring the keys ``Recommendation.describe()`` serializes — the
#: ones this renderer reads: the categorical quality, the gate statuses, the setpoint moves, the
#: expected impact (daily-energy deltas, per-metric delta_pct, basis hours, standing caveat) and
#: Model A's predicted-state grid for the recommended action.
def _recommendation_payload() -> dict[str, Any]:
    return {
        "recommendation_quality": "MEDIUM",
        "constraint_status": "PASS",
        "envelope_status": "WITHIN_ENVELOPE",
        "mode": "NORMAL",
        "is_hold": False,
        "delta_fractions": {"kiln_fuel_rate_tph": -0.05, "separator_speed_rpm": -0.022},
        "expected_impact": {
            "metrics": [
                {
                    "tag": "thermal_energy_kcal_per_kg_clinker",
                    "baseline": 807.9,
                    "proposed": 782.7,
                    "delta": -25.2,
                    "delta_pct": -3.12,
                },
                {
                    "tag": "specific_power_consumption_kwh_t",
                    "baseline": 34.1,
                    "proposed": 33.62,
                    "delta": -0.48,
                    "delta_pct": -1.4,
                },
            ],
            "thermal_energy_kcal_per_day": -2323570.323,
            "electrical_energy_kwh_per_day": -1026.5,
            "daily_basis_hours": 24,
            "caveat": labels.SIMULATED_SAVING_CAVEAT,
        },
        "predicted_state_by_horizon": {
            "t+5min": {
                "thermal_energy_kcal_per_kg_clinker": {"value": 782.7, "unit": "kcal/kg"},
                "burning_zone_temperature": {"value": 1452.3, "unit": "°C"},
            },
            "t+10min": {
                "thermal_energy_kcal_per_kg_clinker": {"value": 782.5, "unit": "kcal/kg"},
                "burning_zone_temperature": {"value": 1451.9, "unit": "°C"},
            },
        },
    }


_MESSAGE = (
    "AI Recommendation: kiln_fuel_rate_tph -5.00 %; separator_speed_rpm -2.20 % "
    "(PASS / WITHIN_ENVELOPE, quality MEDIUM)"
)


def _optimization_view(
    payload: dict[str, Any] | None = None,
    *,
    refused: bool = False,
    available: bool = True,
    refusal_reasons: tuple[str, ...] = (),
) -> OptimizationView:
    """The inner view-J payload: available / refused / unavailable, at stub cost."""
    if not available:
        return OptimizationView.unavailable(
            "2024-01-01T00:00:00Z", reason="The model layer was skipped (--skip-models)."
        )
    body = {} if payload is None else {"recommendation": payload}
    return OptimizationView(
        available=True,
        timestamp="2024-01-01T00:00:00Z",
        mode="NORMAL",
        refused=refused,
        message=_MESSAGE,
        payload=body,
        refusal_reasons=refusal_reasons,
    )


def _anomaly_status(
    *, available: bool = True, status: str = "NORMAL", is_anomaly: bool = False
) -> OverviewStatus:
    if not available:
        return _anomaly_status_tile(
            AnomalyState.unavailable("kiln", "2024-01-01T00:00:00Z")
        )
    return _anomaly_status_tile(
        AnomalyState(
            available=True,
            dataset="kiln",
            timestamp="2024-01-01T00:00:00Z",
            status=status,
            is_anomaly=is_anomaly,
            display_cause="" if not is_anomaly else "Low Oxygen Condition",
        )
    )


@dataclass(frozen=True)
class StubHeader:
    title: str = "Factory Presentation Mode"
    subtitle: str = "overlay"
    timestamp: str = "2024-01-01T00:00:00Z"


@dataclass(frozen=True)
class StubOverview:
    """Shaped like ``state.OverviewView`` for the fields the overlay renderer reads."""

    header: StubHeader = field(default_factory=StubHeader)
    stages: tuple[OverviewStageView, ...] = ()
    plant: KpiGroup = None  # type: ignore[assignment]
    ai_status: OverviewStatus = None  # type: ignore[assignment]
    anomaly_status: OverviewStatus = None  # type: ignore[assignment]


@dataclass(frozen=True)
class StubPresentation:
    """Shaped like ``state.PresentationViewModel``: the two composed view models + header.

    Carries only what the renderer reads (``header`` for its timestamp, then ``overview`` /
    ``optimization``) — so a field the renderer started reading would fail these tests loudly
    rather than silently fall back to a stub default.
    """

    header: StubHeader = field(default_factory=StubHeader)
    overview: StubOverview = None  # type: ignore[assignment]
    optimization: Any = None


def _model(
    *,
    view: OptimizationView | None = None,
    anomaly: OverviewStatus | None = None,
) -> StubPresentation:
    view = view if view is not None else _optimization_view(_recommendation_payload())
    overview = StubOverview(
        stages=_stages(),
        plant=KpiGroup(title="Plant", values=(), note=""),
        ai_status=_ai_status_tile(view),
        anomaly_status=anomaly if anomaly is not None else _anomaly_status(),
    )
    return StubPresentation(
        overview=overview,
        optimization=SimpleNamespace(
            header=StubHeader(), mode="NORMAL", view=view,
            quality_descriptions=labels.RECOMMENDATION_QUALITY_DESCRIPTION,
        ),
    )


class StubState:
    """The duck-typed state ``app.build_document`` needs: ``view(view_id)`` and nothing else."""

    def __init__(self, models: dict[str, Any]) -> None:
        self._models = models

    def view(self, view_id: str) -> Any:
        return self._models[view_id]


@pytest.fixture(scope="module")
def settings() -> DashboardSettings:
    """The real dashboard settings - a YAML parse, milliseconds, no session."""
    return DashboardSettings.from_config()


# =============================================================================
# A — normal rendering: the five cards, the five stages, the three sections
# =============================================================================
def _cards(html: str) -> list[str]:
    """The five KPI cards' inner HTML, one chunk per card, in render order."""
    return html.split('data-role="kpi-card"')[1:]


def test_the_three_sections_render_from_one_view_model(settings: DashboardSettings) -> None:
    html = presentation_view.render_presentation(_model(), settings=settings)
    assert 'data-role="kpis"' in html
    assert 'data-role="chain"' in html
    assert 'data-role="transfer-strategy"' in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


def test_the_five_kpi_cards_render_in_the_prds_order(settings: DashboardSettings) -> None:
    """PRD 29 names five cards; all five render, in the order the PRD lists them."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    titles = [
        presentation_view.CARD_THERMAL,
        presentation_view.CARD_ELECTRICAL,
        presentation_view.CARD_PRODUCTION,
        presentation_view.CARD_QUALITY,
        presentation_view.CARD_ANOMALIES,
    ]
    positions = [html.index(f">{title}</h3>") for title in titles]
    assert positions == sorted(positions)
    assert html.count('data-role="kpi-card"') == 5


def test_the_five_chain_stages_render_in_the_prds_order(settings: DashboardSettings) -> None:
    """The chain is PRD 29's own topology, five stages joined by four arrows."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    titles = [
        presentation_view.CHAIN_CURRENT,
        presentation_view.CHAIN_PREDICTION,
        presentation_view.CHAIN_OPPORTUNITY,
        presentation_view.CHAIN_ACTION,
        presentation_view.CHAIN_BENEFIT,
    ]
    positions = [html.index(f">{title}</h3>") for title in titles]
    assert positions == sorted(positions)
    assert html.count('<span class="dt-pres__arrow">&rarr;</span>') == 4


# =============================================================================
# B — the cards that trace to real data: payload values, mandated labels
# =============================================================================
def test_saving_cards_carry_the_impacts_own_numbers(settings: DashboardSettings) -> None:
    """The two saving cards headline the expected impact's own daily-energy deltas, at the
    ``presentation.headline_decimals`` rounding, with the per-metric percentage the optimizer
    itself reports — never a recomputed or rounded-elsewhere figure."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    thermal, electrical = _cards(html)[0], _cards(html)[1]
    assert "-2,323,570.3 kcal/day" in thermal
    assert "-1,026.5 kWh/day" in electrical
    assert "-3.12 %" in thermal
    assert "-1.40 %" in electrical
    assert "24 h basis" in thermal


def test_headline_rounding_comes_from_the_presentation_settings(
    settings: DashboardSettings,
) -> None:
    """``presentation.headline_decimals`` — not FormatSettings — rounds the headline numbers."""
    two = replace(settings, presentation=replace(settings.presentation, headline_decimals=2))
    html = presentation_view.render_presentation(_model(), settings=two)
    assert "-2,323,570.32 kcal/day" in html
    zero = replace(settings, presentation=replace(settings.presentation, headline_decimals=0))
    html = presentation_view.render_presentation(_model(), settings=zero)
    assert "-2,323,570 kcal/day" in html


def test_every_card_carries_one_of_the_two_mandated_labels(
    settings: DashboardSettings,
) -> None:
    """PRD 29: every KPI card is labelled "Synthetic Demonstration" or "Simulation Estimate" —
    split the way ``src.labels`` documents them: the estimate label belongs to a quantified
    benefit (the two saving cards), the demonstration label to everything else."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    cards = _cards(html)
    assert len(cards) == 5
    for card in cards:
        assert (
            labels.SIMULATION_ESTIMATE_LABEL in card
            or labels.SYNTHETIC_DEMONSTRATION_LABEL in card
        ), card
    assert labels.SIMULATION_ESTIMATE_LABEL in cards[0]
    assert labels.SIMULATION_ESTIMATE_LABEL in cards[1]
    assert labels.SYNTHETIC_DEMONSTRATION_LABEL in cards[2]
    assert labels.SYNTHETIC_DEMONSTRATION_LABEL in cards[3]
    assert labels.SYNTHETIC_DEMONSTRATION_LABEL in cards[4]


def test_the_anomaly_card_shows_model_bs_own_verdict(settings: DashboardSettings) -> None:
    """Anomalies Detected shows the current verdict in Model B's own words. The payload carries
    one verdict per instant and no running count — so no count is invented and the card says so."""
    html = presentation_view.render_presentation(
        _model(anomaly=_anomaly_status(status="WARNING", is_anomaly=True)), settings=settings
    )
    card = _cards(html)[4]
    assert "WARNING" in card
    assert "Low Oxygen Condition" in card
    assert presentation_view.ANOMALY_VERDICT_NOTE in card
    normal = presentation_view.render_presentation(_model(), settings=settings)
    assert "No anomaly detected." in _cards(normal)[4]


def test_the_chain_reads_the_payloads_own_fields(settings: DashboardSettings) -> None:
    """Current Plant State is view A's state words; the action is the optimizer's own move
    format; the benefit is the impact's own deltas under the payload's own caveat."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    assert "Quarry / feed" in html and "IDLE" in html
    assert "kiln_fuel_rate_tph -5.00 %" in html
    assert "separator_speed_rpm -2.20 %" in html
    assert labels.SIMULATED_SAVING_CAVEAT in html
    assert "MEDIUM" in html  # the categorical quality pill, never a percentage
    assert "2 plant values" in html  # Model A's grid: 2 targets over t+5min … t+10min
    assert _MESSAGE in html  # the optimizer's own headline, in its own words


# =============================================================================
# C — the honest gaps: stability cards state the absence, never a number
# =============================================================================
def test_stability_cards_state_the_gap_without_inventing_a_number(
    settings: DashboardSettings,
) -> None:
    """No model in this system computes a production- or quality-stability metric. Both cards
    say "unavailable" with the real reason — standing constraint 4: a guard states an absence,
    never substitutes a number. No digit may appear in either card."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    production, quality = _cards(html)[2], _cards(html)[3]
    for card, reason in (
        (production, presentation_view.PRODUCTION_GAP_REASON),
        (quality, presentation_view.QUALITY_GAP_REASON),
    ):
        assert presentation_view.UNAVAILABLE_TEXT in card
        # The renderer escapes the reason's apostrophe (theme.html), so compare escaped.
        assert theme.html(reason) in card
        # No digit in the *visible* text: strip tags and unescape entities first.
        visible = html_module.unescape(re.sub(r"<[^>]+>", " ", card))
        assert not re.search(r"\d", visible), visible


# =============================================================================
# D — the Section 21 disclaimer, visible on the screen itself
# =============================================================================
def test_the_section_21_disclaimer_is_visible(settings: DashboardSettings) -> None:
    """PRD 29 requires a visible link/footnote to the §21 disclaimer; §21.5 requires its
    standing statement verbatim in this mode. The export is a static file, so the link is a
    visible footnote block naming Section 21 and quoting the statement."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    assert labels.TRANSFER_STRATEGY_STATEMENT in html
    assert "Synthetic-to-Real Transfer Strategy" in html
    assert "Section 21" in html


# =============================================================================
# E — what never appears: confidence %, raw tag readouts, model internals, code
# =============================================================================
def test_no_numeric_confidence_and_no_forbidden_control_label(
    settings: DashboardSettings,
) -> None:
    """AC-18 / PRD 30: no numeric confidence percentage anywhere, the quality only ever the
    HIGH/MEDIUM/LOW categorical, and the forbidden control label never appears."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    assert not re.search(r"[Cc]onfidence", html)
    assert labels.FORBIDDEN_CONTROL_LABEL not in html
    assert "MEDIUM" in html  # the categorical, as a pill word


def test_no_raw_tag_readouts_model_internals_or_code(settings: DashboardSettings) -> None:
    """PRD 29: this mode never displays raw tag lists, model internals or code. The observed
    readout tags (views B-F's panels), the serialized payload's internal key names and any
    code/JSON block must all be absent. The one tag-shaped text that remains is the recommended
    action's own variable names — the content of the recommendation itself, the same names the
    optimizer's own one-line message uses."""
    html = presentation_view.render_presentation(_model(), settings=settings)
    for absent in (
        "burning_zone_temperature",  # an observed readout tag, not part of any action here
        "oxygen_percent",
        "residue_percent",
        "simulated_blaine",
        "model_version",
        "runtime_s",
        "objective_breakdown",
        "delta_fractions",  # the serialized key, not the rendered action
        "predicted_state_by_horizon",
        "state_sources",
        "ood",
        "ensemble",
        "<pre",
        "<code",
    ):
        assert absent not in html, absent


# =============================================================================
# F — refusal and unavailable states are display states, never empty cards
# =============================================================================
def test_a_refused_run_is_a_display_state(settings: DashboardSettings) -> None:
    """Item 16: a refusal shows the mandated headline and the blocking gates' own reasons —
    and the recommendation-derived cards state there is nothing to report rather than a zero."""
    view = _optimization_view(
        refused=True,
        refusal_reasons=("Hard constraints - no candidate satisfies every configured bound.",),
    )
    html = presentation_view.render_presentation(_model(view=view), settings=settings)
    assert labels.NO_SAFE_RECOMMENDATION in html
    assert "Hard constraints - no candidate satisfies every configured bound." in html
    thermal, _electrical, _production, _quality, _anomalies = _cards(html)
    assert presentation_view.UNAVAILABLE_TEXT in thermal
    assert labels.NO_SAFE_RECOMMENDATION in thermal
    for stage_title in (
        presentation_view.CHAIN_PREDICTION,
        presentation_view.CHAIN_ACTION,
        presentation_view.CHAIN_BENEFIT,
    ):
        chunk = html.split(f">{stage_title}</h3>")[1]
        assert presentation_view.UNAVAILABLE_TEXT in chunk.split('data-role="chain-stage"')[0]


def test_an_unavailable_model_states_its_own_reason(settings: DashboardSettings) -> None:
    """Under --skip-models the optimizer is absent: the saving cards carry the model layer's
    own reason under the mandated unavailable label, never a substitute number."""
    view = _optimization_view(available=False)
    html = presentation_view.render_presentation(_model(view=view), settings=settings)
    assert labels.MODEL_UNAVAILABLE_LABEL in html
    assert "The model layer was skipped (--skip-models)." in html
    thermal = _cards(html)[0]
    assert presentation_view.UNAVAILABLE_TEXT in thermal
    assert not re.search(r"-?\d[\d,]*\.\d kcal", thermal)


def test_an_unavailable_anomaly_model_states_its_own_reason(
    settings: DashboardSettings,
) -> None:
    html = presentation_view.render_presentation(
        _model(anomaly=_anomaly_status(available=False)), settings=settings
    )
    card = _cards(html)[4]
    assert presentation_view.UNAVAILABLE_TEXT in card
    assert labels.MODEL_UNAVAILABLE_LABEL in card


# =============================================================================
# G — determinism
# =============================================================================
def test_rendering_is_deterministic(settings: DashboardSettings) -> None:
    """Two renders of one view model are byte-identical — the golden file's precondition."""
    first = presentation_view.render_presentation(_model(), settings=settings)
    second = presentation_view.render_presentation(_model(), settings=settings)
    assert first == second


# =============================================================================
# H — routing: app dispatch, the request wrapper, the CLI
# =============================================================================
def test_app_dispatches_the_presentation_model_to_the_presentation_renderer(
    settings: DashboardSettings,
) -> None:
    """``build_document`` routes a model shaped like ``PresentationViewModel`` to the
    presentation renderer — and does not misroute the other screens' models onto it."""
    html, timings = app.build_document(
        StubState({"P": _model()}), ("P",), settings=settings
    )
    assert 'data-role="kpis"' in html
    assert presentation_view.CARD_THERMAL in html
    assert list(timings) == ["P"]
    assert not app._is_presentation(SimpleNamespace(stages=(), plant=None))
    assert not app._is_presentation(SimpleNamespace(sliders=(), view=None))


def test_the_presentation_request_serves_p_and_delegates_every_other_id() -> None:
    """The wrapper that reaches ``DashboardState.presentation()``: the PRD 29 ids are served
    from the composition builder, everything else delegates to the generic dispatch, and
    ``capabilities()`` passes through so the twin's badge derivation still works."""

    class Wrapped:
        def presentation(self) -> Any:
            return _model()

        def view(self, view_id: str) -> Any:
            return f"generic:{view_id}"

        def capabilities(self) -> Any:
            return SimpleNamespace(synthetic=True)

    request = app._PresentationRequest(Wrapped())
    served = request.view("P")
    assert hasattr(served, "overview") and hasattr(served, "optimization")
    served_by_key = request.view("presentation")
    assert hasattr(served_by_key, "overview") and hasattr(served_by_key, "optimization")
    assert request.view("A") == "generic:A"
    assert request.view("I") == "generic:I"
    assert request.capabilities().synthetic is True


def test_the_cli_accepts_the_presentation_ids() -> None:
    """--view P and --view presentation are valid; an unknown id still fails at parse time."""
    parser = app.build_parser()
    assert parser.parse_args(["--view", "P"]).views == ["P"]
    assert parser.parse_args(["--view", "presentation"]).views == ["presentation"]
    with pytest.raises(SystemExit):
        app.build_parser().parse_args(["--view", "Z"])


# =============================================================================
# I — the state-layer composition (real DashboardState over the shared stub provider)
# =============================================================================
def test_presentation_composes_views_a_and_j_with_one_optimizer_pass(
    stub_provider: Any, settings: DashboardSettings
) -> None:
    """``DashboardState.presentation()`` is the overlay PRD 29 describes: the same view A /
    view J models those screens render, on one shared frame, with the optimizer asked **once**
    for both (the ``optimization=`` hand-off), not once per screen."""
    from src.digital_twin.state import DashboardState, OverviewView, PresentationViewModel
    from src.visualization.clock import Clock

    provider = stub_provider()
    state = DashboardState(provider, Clock(provider, settings), settings)
    provider.calls.clear()
    model = state.presentation()
    assert isinstance(model, PresentationViewModel)
    assert isinstance(model.overview, OverviewView)
    # the one shared pass: view A's AI tile and the overlay both read this same model
    assert provider.calls["get_optimization"] == 1
    assert provider.calls["get_anomaly_state"] == 1
    assert model.header.title == "Factory Presentation Mode"
    # and the stub's payload has no recommendation — the renderer must say so, not invent one
    html = presentation_view.render_presentation(model, settings=settings)
    assert presentation_view.CARD_THERMAL in html
    assert presentation_view.UNAVAILABLE_TEXT in html


def test_the_overlay_is_not_an_eleventh_views_row() -> None:
    """Directive item 2 fixes the dashboard at ten screens; PRD 29's mode is an overlay, not a
    screen. The registry must stay at ten rows, and the generic ``view()`` dispatch must not
    learn the P id — only ``_PresentationRequest`` serves it."""
    from src.digital_twin.state import VIEWS, DashboardState

    assert len(VIEWS) == 10
    assert "P" not in {row[0] for row in VIEWS}
    assert "presentation" not in {row[1] for row in VIEWS}
    # the generic dispatch is unchanged: an unregistered id still raises before any state read
    with pytest.raises(KeyError):
        DashboardState.view(object.__new__(DashboardState), "P")


# =============================================================================
# The golden file
# =============================================================================
# Regenerate deliberately, never by hand:
#   python -c "from pathlib import Path; \
#     from src.digital_twin.settings import DashboardSettings; \
#     from tests.test_task6_presentation_view import _model; \
#     from src.visualization import presentation_view; \
#     Path('tests/golden/view_p_normal.html').write_bytes(\
#         presentation_view.render_presentation(\
#             _model(), settings=DashboardSettings.from_config()).encode('utf-8'))"
GOLDEN_PATH = Path(__file__).parent / "golden" / "view_p_normal.html"

GOLDEN_HINT = (
    "the presentation renderer no longer matches its golden file. This is a REGRESSION unless "
    "the renderer was deliberately changed — regenerate with the command in the comment beside "
    "GOLDEN_PATH and say so in the commit message. The golden payload is the stub built by "
    "_model() in this module."
)


def _golden() -> str:
    return GOLDEN_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_render_matches_the_golden_file(settings: DashboardSettings) -> None:
    """Byte-for-byte (newline-normalised) against the stored fixture: every card, label, chain
    stage, gap reason and footnote is pinned, so an accidental rewording, a dropped refusal
    path or a changed number format still fails. A deliberate renderer change regenerates the
    fixture with the recorded command.
    """
    html = presentation_view.render_presentation(_model(), settings=settings)
    assert html.replace("\r\n", "\n") == _golden(), GOLDEN_HINT
