"""View A renderer tests (Wave View A): the Plant Overview panel and its routing.

Deliberately bounded, like ``test_task6_intelligence_view.py`` and
``test_task6_optimization_view.py``: nothing here builds a session, trains a model or runs the
optimizer. The renderer under test is the real :mod:`src.visualization.overview_view`, driven by
real view-model objects (:class:`~src.digital_twin.state.OverviewView`,
:class:`~src.digital_twin.state.OverviewStageView`,
:class:`~src.digital_twin.state.OverviewStatus`,
:class:`~src.digital_twin.payloads.KpiGroup`,
:class:`~src.digital_twin.payloads.EquipmentStatus`) and the real state-layer tile mappers
(``state._ai_status_tile`` / ``state._anomaly_status_tile``) applied to real
:class:`~src.digital_twin.insights.OptimizationView` /
:class:`~src.digital_twin.insights.AnomalyState` payloads - so what is asserted below is what a
browser would receive from a real run, at stub cost.

Covers the items this wave surfaces on one screen:

* **item 3** - the five-stage chain in process order, each stage's state word read from its own
  throughput, with the PRD 8.3 equipment it groups;
* **items 9 / 12** - the plant KPI group rendered whole: the specific energy figures *and* the
  daily totals the provider binds into that one group, never the favourable half alone;
* **PRD 18.1's AI status / anomaly status tiles** - compact summaries of the view H / view J
  payloads, with unavailable models stated as unavailable and refusals as display states.

Plus the honesty rules that reach every screen: no numeric confidence, no forbidden control
label, the standing no-plant-connection statement, and HTML escaping of the payload's free text.

Self-contained on purpose: no shared ``conftest.py`` fixture, so this module runs alone
(``pytest tests/test_task6_overview_view.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.insights import AnomalyState, OptimizationView
from src.digital_twin.payloads import EquipmentStatus, KpiGroup, StateSnapshot
from src.digital_twin.provenance import Provenance, Status, Value
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import (
    OverviewStageView,
    OverviewStatus,
    OverviewView,
    _ai_status_tile,
    _anomaly_status_tile,
)
from src.visualization import overview_view, theme


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


def _equipment(name: str, state: str = labels.EQUIPMENT_RUNNING) -> EquipmentStatus:
    return EquipmentStatus(name=name, unit="", kind="stub", state=state, health=1.0)


def _stage(
    name: str,
    title: str,
    *,
    rate: Value | None,
    state: str,
    equipment: tuple[EquipmentStatus, ...] = (),
) -> OverviewStageView:
    return OverviewStageView(
        name=name,
        title=title,
        detail=f"stub detail for {title}",
        rate=rate,
        state=state,
        moving=state == labels.EQUIPMENT_RUNNING,
        equipment=equipment,
    )


#: The five stages of directive item 3, in process order, as the view model assembles them.
def _stages() -> tuple[OverviewStageView, ...]:
    return (
        _stage("feed", "Quarry / feed", rate=_value("kiln_feed_rate_tph", 182.5),
               state=labels.EQUIPMENT_RUNNING),
        _stage("kiln_system", "Kiln system", rate=_value("clinker_production_tph", 119.8),
               state=labels.EQUIPMENT_RUNNING,
               equipment=(_equipment("Preheater"), _equipment("RotaryKiln"))),
        _stage("clinker", "Clinker", rate=_value("clinker_feed_rate", 96.1),
               state=labels.EQUIPMENT_RUNNING),
        _stage("cement_mill", "Cement mill", rate=_value("mill_feed_rate_tph", 121.3),
               state=labels.EQUIPMENT_RUNNING, equipment=(_equipment("Separator"),)),
        _stage("cement_product", "Cement product", rate=_value("cement_production_tph", 125.5),
               state=labels.EQUIPMENT_RUNNING),
    )


#: The plant KPI group the provider builds: specific energy *and* its daily total, both
#: production rates - the item-12 pairing, bound in one group under its own note.
def _plant() -> KpiGroup:
    return KpiGroup(
        title="Plant",
        values=(
            _value("thermal_energy_kcal_per_kg_clinker", 807.9, unit="kcal/kg",
                   description="Specific thermal energy consumption"),
            _value("specific_power_consumption_kwh_t", 34.1, unit="kWh/t",
                   description="Specific electrical energy consumption"),
            _value("clinker_production_tph", 119.8),
            _value("cement_production_tph", 125.5),
            _value("kiln_thermal_energy_kcal_per_day", 2323570323.7, unit="kcal/day",
                   status=Status.NO_LIMIT, description="Total kiln thermal energy per day"),
            _value("mill_electrical_energy_kwh_per_day", 102618.8, unit="kWh/day",
                   status=Status.NO_LIMIT, description="Total cement-mill electricity per day"),
        ),
        note=labels.SPECIFIC_VS_TOTAL_NOTE,
    )


def _ai_status() -> OverviewStatus:
    """An available, non-refused AI tile - the view-J payload's own headline."""
    return _ai_status_tile(
        OptimizationView(
            available=True,
            timestamp="2024-01-01T00:00:00Z",
            mode="NORMAL",
            refused=False,
            message=(
                "AI Recommendation: kiln_fuel_rate_tph -5.00 %; separator_speed_rpm -2.20 % "
                "(PASS / WITHIN_ENVELOPE, quality LOW)"
            ),
        )
    )


def _anomaly_status() -> OverviewStatus:
    """A WARNING-state anomaly tile - the view-H payload's own verdict."""
    return _anomaly_status_tile(
        AnomalyState(
            available=True,
            dataset="kiln",
            timestamp="2024-01-01T00:00:00Z",
            status="WARNING",
            is_anomaly=True,
            display_cause="Low Oxygen Condition",
        )
    )


@dataclass(frozen=True)
class StubHeader:
    title: str = "Plant Overview"
    subtitle: str = "The whole plant at one glance"
    timestamp: str = "2024-01-01T00:00:00Z"


@dataclass(frozen=True)
class StubOverviewView:
    """Shaped like ``state.OverviewView``: the chain, the plant group, the two status tiles.

    Carries only what the renderer reads (``header`` for its timestamp, then ``stages`` /
    ``plant`` / ``ai_status`` / ``anomaly_status``) - so a field the renderer started reading
    would fail these tests loudly rather than silently fall back to a stub default.
    """

    header: StubHeader = field(default_factory=StubHeader)
    stages: tuple[OverviewStageView, ...] = ()
    plant: KpiGroup = None  # type: ignore[assignment]
    ai_status: OverviewStatus = None  # type: ignore[assignment]
    anomaly_status: OverviewStatus = None  # type: ignore[assignment]


def _model(
    *,
    stages: tuple[OverviewStageView, ...] | None = None,
    plant: KpiGroup | None = None,
    ai_status: OverviewStatus | None = None,
    anomaly_status: OverviewStatus | None = None,
) -> StubOverviewView:
    return StubOverviewView(
        stages=stages if stages is not None else _stages(),
        plant=plant if plant is not None else _plant(),
        ai_status=ai_status if ai_status is not None else _ai_status(),
        anomaly_status=anomaly_status if anomaly_status is not None else _anomaly_status(),
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
# A — normal rendering: the three sections, from the payload's own values
# =============================================================================
def test_the_three_sections_render_from_one_view_model(settings: DashboardSettings) -> None:
    html = overview_view.render_overview(_model(), settings=settings)
    assert 'data-role="chain"' in html
    assert 'data-role="kpis"' in html
    assert 'data-role="status"' in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


def test_the_five_stages_render_in_process_order(settings: DashboardSettings) -> None:
    """Item 3: Quarry/feed -> kiln -> clinker -> mill -> product, joined by arrows."""
    html = overview_view.render_overview(_model(), settings=settings)
    titles = ["Quarry / feed", "Kiln system", "Clinker", "Cement mill", "Cement product"]
    positions = [html.index(f">{title}</h3>") for title in titles]
    assert positions == sorted(positions)
    assert html.count('<span class="dt-ov__arrow">&rarr;</span>') == 4


def test_stage_cards_carry_their_own_state_rate_and_equipment(
    settings: DashboardSettings,
) -> None:
    """The state pill is the payload's word; the rate is its own Value; equipment states show."""
    html = overview_view.render_overview(_model(), settings=settings)
    assert 'class="dt-pill dt-pill--ok">RUNNING' in html
    assert "182.5" in html  # the feed stage's own rate, at FormatSettings precision
    assert "Preheater" in html
    assert "RotaryKiln" in html


def test_kpi_cards_show_the_specific_and_the_total_together(
    settings: DashboardSettings,
) -> None:
    """Item 12, VERBATIM: the dashboard must NOT show only the favorable metric. The provider
    binds each specific-energy figure and its daily total into one plant group; the renderer
    shows the group whole, so both halves of every pair appear on the same screen."""
    html = overview_view.render_overview(_model(), settings=settings)
    for tag in (
        "thermal_energy_kcal_per_kg_clinker",
        "kiln_thermal_energy_kcal_per_day",
        "specific_power_consumption_kwh_t",
        "mill_electrical_energy_kwh_per_day",
    ):
        assert tag in html, f"the plant KPI group must carry {tag}"
    assert "kcal/kg" in html and "kcal/day" in html
    assert labels.SPECIFIC_VS_TOTAL_NOTE in html  # the group's own note, verbatim
    assert "807.9" in html  # the specific figure
    assert "2,323,570,324" in html  # the total it implies, grouped not truncated to a zero


# =============================================================================
# B — the two PRD 18.1 status tiles, from the view H / J payloads
# =============================================================================
def test_the_ai_tile_shows_the_optimizers_own_headline(settings: DashboardSettings) -> None:
    html = overview_view.render_overview(_model(), settings=settings)
    assert "AI status" in html
    assert labels.AI_RECOMMENDATION_LABEL in html
    assert "kiln_fuel_rate_tph -5.00 %" in html  # the optimizer's own one-line account
    assert 'class="dt-pill dt-pill--ok">AI Recommendation' in html


def test_the_anomaly_tile_shows_model_bs_own_verdict(settings: DashboardSettings) -> None:
    html = overview_view.render_overview(_model(), settings=settings)
    assert "Anomaly status" in html
    assert 'class="dt-pill dt-pill--warn">WARNING' in html
    assert "Low Oxygen Condition" in html  # Model B's own cause line


def test_a_refusal_is_a_display_state_on_the_tile(settings: DashboardSettings) -> None:
    """Item 16 reaches the overview: a blocked run is shown, with the gates' own words."""
    tile = _ai_status_tile(
        OptimizationView(
            available=True,
            timestamp="t",
            mode="NORMAL",
            refused=True,
            message=(
                f"{labels.NO_SAFE_RECOMMENDATION}: envelope - the candidate sits outside the "
                "calibrated operating envelope"
            ),
        )
    )
    html = overview_view.render_overview(_model(ai_status=tile), settings=settings)
    assert labels.NO_SAFE_RECOMMENDATION in html
    assert 'class="dt-pill dt-pill--warn">No safe recommendation found' in html
    assert "outside the calibrated operating envelope" in html


def test_a_normal_anomaly_row_says_so_in_the_frozen_layers_words(
    settings: DashboardSettings,
) -> None:
    tile = _anomaly_status_tile(
        AnomalyState(
            available=True, dataset="kiln", timestamp="t", status="NORMAL", is_anomaly=False
        )
    )
    html = overview_view.render_overview(_model(anomaly_status=tile), settings=settings)
    assert "No anomaly detected." in html
    assert "WARNING" not in html  # no anomaly manufactured from a normal row


def test_the_inconclusive_cause_is_carried_through_verbatim(settings: DashboardSettings) -> None:
    """Item 11: where Model B cannot separate fault from process, the tile shows the VERBATIM
    label rather than a named cause - the summary resolves nothing the payload did not."""
    tile = _anomaly_status_tile(
        AnomalyState(
            available=True, dataset="kiln", timestamp="t", status="WARNING", is_anomaly=True,
            display_cause=labels.EVIDENCE_INCONCLUSIVE_LABEL,
        )
    )
    html = overview_view.render_overview(_model(anomaly_status=tile), settings=settings)
    assert labels.EVIDENCE_INCONCLUSIVE_LABEL in html
    assert "Low Oxygen Condition" not in html  # no cause promoted from an inconclusive verdict


def test_an_absent_model_is_stated_with_its_own_reason(settings: DashboardSettings) -> None:
    """The honest "unavailable": both tiles carry the payload's own reason under the mandated
    label - the --skip-models path, exactly as a browser would see it."""
    ai = _ai_status_tile(OptimizationView.unavailable("t", reason="model layer skipped"))
    anomaly = _anomaly_status_tile(AnomalyState.unavailable("kiln", "t", reason="model layer skipped"))
    html = overview_view.render_overview(
        _model(ai_status=ai, anomaly_status=anomaly), settings=settings
    )
    assert html.count(labels.MODEL_UNAVAILABLE_LABEL) == 2
    assert html.count("model layer skipped") == 2
    assert "AI Recommendation" not in html  # no status invented for a model that is not there
    assert "No anomaly detected." not in html


# =============================================================================
# C — degraded payload data: absences stated, never filled in
# =============================================================================
def test_a_stage_without_a_rate_shows_the_absence_glyph(settings: DashboardSettings) -> None:
    """An unmeasured line and a stopped one are different states: no rate means the glyph,
    never a zero that would read as measured-and-zero."""
    stages = (
        _stage("feed", "Quarry / feed", rate=None, state=labels.EQUIPMENT_RUNNING),
        *_stages()[1:],
    )
    html = overview_view.render_overview(_model(stages=stages), settings=settings)
    assert f">{theme.NO_VALUE_TEXT}</p>" in html  # the absence glyph, not a number
    assert ">0</p>" not in html  # no invented zero readout


def test_an_unknown_stage_state_gets_the_honest_grey(settings: DashboardSettings) -> None:
    stages = (
        _stages()[0],
        _stage("kiln_system", "Kiln system", rate=_value("clinker_production_tph", None),
               state=labels.EQUIPMENT_UNKNOWN, equipment=(_equipment("RotaryKiln", labels.EQUIPMENT_UNKNOWN),)),
        *_stages()[2:],
    )
    html = overview_view.render_overview(_model(stages=stages), settings=settings)
    assert 'class="dt-pill dt-pill--unknown">UNKNOWN' in html


def test_an_empty_plant_group_is_stated_not_papered_over(settings: DashboardSettings) -> None:
    """A provider that answered no plant KPI gets the honest statement - no invented cards."""
    html = overview_view.render_overview(
        _model(plant=KpiGroup(title="Plant", values=())), settings=settings
    )
    assert "no plant KPI group" in html
    assert 'data-role="kpi">' not in html  # no card invented to fill the space


# =============================================================================
# D — the honesty rules that reach every screen
# =============================================================================
def test_no_confidence_percentage_and_no_forbidden_control_label(
    settings: DashboardSettings,
) -> None:
    """Item 20: confidence stays categorical, and the forbidden control wording never appears."""
    html = overview_view.render_overview(_model(), settings=settings)
    assert "confidence" not in html.lower()
    assert labels.FORBIDDEN_CONTROL_LABEL not in html


def test_payload_free_text_is_escaped(settings: DashboardSettings) -> None:
    """A stage detail carrying markup is escaped - the payload cannot inject into the panel."""
    stages = (
        _stage("feed", "Quarry / feed <script>alert(1)</script>",
               rate=_value("kiln_feed_rate_tph", 182.5), state=labels.EQUIPMENT_RUNNING),
        *_stages()[1:],
    )
    html = overview_view.render_overview(_model(stages=stages), settings=settings)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_standing_no_plant_connection_statement_is_in_the_panel(
    settings: DashboardSettings,
) -> None:
    html = overview_view.render_overview(_model(), settings=settings)
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


# =============================================================================
# E — determinism
# =============================================================================
def test_two_renders_of_one_view_model_are_byte_identical(
    settings: DashboardSettings,
) -> None:
    """No wall clock, no dict ordering, no randomness: the same payload renders the same panel."""
    first = overview_view.render_overview(_model(), settings=settings)
    second = overview_view.render_overview(_model(), settings=settings)
    assert first == second


# =============================================================================
# F — app.py routing (the _is_overview duck type)
# =============================================================================
def test_view_a_routes_to_the_renderer_in_build_document(
    settings: DashboardSettings,
) -> None:
    html, timings = app.build_document(StubState({"A": _model()}), ("A",), settings=settings)
    assert "A — Plant Overview" in html
    assert 'data-role="chain"' in html
    assert "no renderer for this screen yet" not in html  # not the payload fallback
    assert list(timings) == ["A"]


def test_a_screen_with_no_stages_still_falls_to_the_payload_fallback(
    settings: DashboardSettings,
) -> None:
    @dataclass(frozen=True)
    class StubOtherView:
        header: StubHeader = field(default_factory=StubHeader)

        def describe(self) -> dict[str, Any]:
            return {"header": self.header.title}

    html, _ = app.build_document(
        StubState({"C": StubOtherView()}), ("C",), settings=settings
    )
    assert "no renderer for this screen yet" in html


def test_the_overview_duck_type_does_not_swallow_the_h_and_j_screens(
    settings: DashboardSettings,
) -> None:
    """_is_overview keys on ``stages`` AND ``plant``; H carries predictions/anomaly, J carries
    ``view`` - neither has both, so their routing is untouched (this wave's scope rule)."""

    @dataclass(frozen=True)
    class StubIntelligenceLike:
        header: StubHeader = field(default_factory=StubHeader)
        predictions: object = None
        anomaly: object = None

    @dataclass(frozen=True)
    class StubOptimizationLike:
        header: StubHeader = field(default_factory=StubHeader)
        view: Any = None

    assert not app._is_overview(StubIntelligenceLike())
    assert not app._is_overview(StubOptimizationLike())
    assert app._is_overview(_model())


# =============================================================================
# G — the state-layer tile mappers themselves
# =============================================================================
def test_the_real_view_model_describes_its_two_status_tiles() -> None:
    """The frozen ``OverviewView.describe()`` carries both tiles, so the payload - not just the
    renderer - answers PRD 18.1's last two cards."""
    header = SimpleNamespace(
        title="Plant Overview",
        subtitle="",
        describe=lambda: {"title": "Plant Overview"},
    )
    model = OverviewView(
        header=header,  # type: ignore[arg-type]
        stages=_stages(),
        plant=_plant(),
        snapshot=StateSnapshot(
            timestamp="2024-01-01T00:00:00Z",
            mode="NORMAL",
            provenance=Provenance.OBSERVED,
            source="stub",
            values={},
        ),
        equipment=(),
        ai_status=_ai_status(),
        anomaly_status=_anomaly_status(),
    )
    described = model.describe()
    assert described["ai_status"]["title"] == "AI status"
    assert described["ai_status"]["status"] == labels.AI_RECOMMENDATION_LABEL
    assert described["anomaly_status"]["status"] == "WARNING"


def test_the_tile_mappers_map_every_payload_state() -> None:
    """Available / refused / unavailable for AI; anomaly / normal / unavailable for Model B."""
    ai = OptimizationView(available=True, timestamp="t", mode="NORMAL", refused=True, message="m")
    assert _ai_status_tile(ai).status == labels.NO_SAFE_RECOMMENDATION
    missing = OptimizationView.unavailable("t")
    tile = _ai_status_tile(missing)
    assert not tile.available and tile.status == labels.MODEL_UNAVAILABLE_LABEL
    normal = AnomalyState(available=True, dataset="kiln", timestamp="t", status="NORMAL",
                          is_anomaly=False)
    assert _anomaly_status_tile(normal).detail == "No anomaly detected."
    missing_anomaly = AnomalyState.unavailable("kiln", "t")
    assert _anomaly_status_tile(missing_anomaly).detail  # the payload's own reason, not a blank


# =============================================================================
# The golden file
# =============================================================================
#: The stored render of the stub payload above. Regenerate after a *deliberate* renderer change:
#:
#:     python -c "from pathlib import Path; from tests.test_task6_overview_view import \
#: _model; from src.digital_twin.settings import DashboardSettings; \
#: from src.visualization import overview_view; \
#: Path('tests/golden/view_a_normal.html').write_bytes(overview_view.render_overview(\
#: _model(), settings=DashboardSettings.from_config()).encode('utf-8'))"
#:
#: Written with ``write_bytes`` so the fixture keeps its LF newlines in the repository; the
#: comparison below normalises either way, because ``core.autocrlf`` checkouts differ by machine.
GOLDEN_PATH = Path(__file__).parent / "golden" / "view_a_normal.html"

GOLDEN_HINT = (
    "view A's renderer no longer matches its golden file. This is a REGRESSION unless the renderer "
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
    html = overview_view.render_overview(_model(), settings=settings)

    assert html == _golden(), GOLDEN_HINT
    # The fixture is not empty and not a stale stub of itself: it carries the panel's anchors.
    assert 'data-role="chain"' in html
    assert 'data-role="status-tile"' in html
