"""View G renderer tests (Wave View G): the Energy Monitoring panel and its routing.

Deliberately bounded, like ``test_task6_overview_view.py`` and
``test_task6_intelligence_view.py``: nothing here builds a session, trains a model or runs the
optimizer. The renderer under test is the real :mod:`src.visualization.energy_view`, driven by
real view-model pieces (:class:`~src.digital_twin.state.Panel`,
:class:`~src.digital_twin.payloads.KpiGroup`,
:class:`~src.digital_twin.provenance.Value`) — and, for the state-layer tests, the real
:meth:`src.digital_twin.state.DashboardState.energy` builder over the shared ``conftest.py``
stub provider, which serves the plant KPI group in exactly the shape the real provider does
(specific figures + daily totals bound in under the item-12 note). So what is asserted below is
what a browser would receive from a real run, at stub cost.

Covers the items this wave surfaces on one screen:

* **item 12** — VERBATIM: "The dashboard must NOT show only the favorable metric." The specific
  figures, the daily totals they imply and the production rates between them render on one
  screen, under the payload's own pairing note; an absent half of a pair is stated, never
  hidden, so the favorable half can never stand alone;
* **item 9** — the kiln and cement-mill KPI groups, rendered whole from the provider's groups;
* **item 20** — the honesty rules: no fabricated value, absences as the payload's own glyph,
  no numeric confidence, the standing no-plant-connection statement, HTML escaping.

Self-contained on purpose for the renderer tests (no ``conftest.py`` fixture needed for them);
the two state-layer tests use the shared ``stub_provider`` fixture the other Task #6 modules
use, so this module runs alone with ``pytest tests/test_task6_energy_view.py`` either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.layout import DAILY_TOTALS
from src.digital_twin.payloads import KpiGroup
from src.digital_twin.provenance import Provenance, Status, Value
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import DashboardState, EnergyView, Panel
from src.visualization import energy_view, theme
from src.visualization.clock import Clock


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


#: The item-12 pairing, in the shape the provider builds it: the two specific figures, the two
#: rates that drive them, and the two daily totals — one plant group, six cards.
_SPECIFIC = (
    _value("thermal_energy_kcal_per_kg_clinker", 807.9, unit="kcal/kg",
           description="Specific thermal energy consumption"),
    _value("specific_power_consumption_kwh_t", 34.1, unit="kWh/t",
           description="Specific electrical energy consumption"),
)
_RATES = (
    _value("clinker_production_tph", 119.8),
    _value("cement_production_tph", 125.5),
)
_TOTALS = (
    _value("kiln_thermal_energy_kcal_per_day", 2323570323.7, unit="kcal/day",
           status=Status.NO_LIMIT, description="Total kiln thermal energy per day"),
    _value("mill_electrical_energy_kwh_per_day", 102618.8, unit="kWh/day",
           status=Status.NO_LIMIT, description="Total cement-mill electricity per day"),
)


def _specific(note: str = labels.SPECIFIC_VS_TOTAL_NOTE) -> Panel:
    return Panel("Specific energy (per tonne)", _SPECIFIC, note=note)


def _total(note: str = labels.SPECIFIC_VS_TOTAL_NOTE) -> Panel:
    return Panel("Total energy (per day)", _TOTALS, note=note)


def _production() -> Panel:
    return Panel("Production", _RATES)


def _kiln() -> KpiGroup:
    return KpiGroup(
        title="Kiln",
        values=(
            _value("kiln_fuel_rate_tph", 4.1, description="Kiln fuel rate"),
            _value("burning_zone_temperature", 1451.0, unit="°C",
                   description="Burning zone temperature"),
        ),
    )


def _mill() -> KpiGroup:
    return KpiGroup(
        title="Cement mill",
        values=(
            _value("mill_motor_power_kw", 2500.0, unit="kW", description="Mill motor power"),
            _value("simulated_blaine_cm2_g", 3850.0, unit="cm²/g",
                   description="Simulated Blaine"),
        ),
    )


@dataclass(frozen=True)
class StubHeader:
    title: str = "Energy Monitoring"
    subtitle: str = "Specific and total energy, together"
    timestamp: str = "2024-01-01T00:00:00Z"


@dataclass(frozen=True)
class StubEnergyView:
    """Shaped like ``state.EnergyView``: the item-12 partition plus the two other KPI groups.

    Carries only what the renderer reads (``header`` for its timestamp, then ``specific`` /
    ``total`` / ``production`` / ``kiln`` / ``mill``) — so a field the renderer started reading
    would fail these tests loudly rather than silently fall back to a stub default. The real
    model's ``trends`` channels are deliberately absent: no Task-6 renderer draws charts, and
    the renderer under test must not read them (a renderer that did would be new chart scope).
    """

    header: StubHeader = field(default_factory=StubHeader)
    specific: Panel = None  # type: ignore[assignment]
    total: Panel = None  # type: ignore[assignment]
    production: Panel = None  # type: ignore[assignment]
    kiln: KpiGroup = None  # type: ignore[assignment]
    mill: KpiGroup = None  # type: ignore[assignment]


def _model(
    *,
    specific: Panel | None = None,
    total: Panel | None = None,
    production: Panel | None = None,
    kiln: KpiGroup | None = None,
    mill: KpiGroup | None = None,
) -> StubEnergyView:
    return StubEnergyView(
        specific=specific if specific is not None else _specific(),
        total=total if total is not None else _total(),
        production=production if production is not None else _production(),
        kiln=kiln if kiln is not None else _kiln(),
        mill=mill if mill is not None else _mill(),
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
# A — normal rendering: the sections, from the payload's own values
# =============================================================================
def test_the_sections_render_from_one_view_model(settings: DashboardSettings) -> None:
    html = energy_view.render_energy(_model(), settings=settings)
    assert 'data-role="energy-pair"' in html
    assert 'data-role="energy-kiln"' in html
    assert 'data-role="energy-mill"' in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


def test_the_three_partitions_carry_their_own_titles(settings: DashboardSettings) -> None:
    """The partition titles are the view model's own, not the renderer's rewording."""
    html = energy_view.render_energy(_model(), settings=settings)
    for title in ("Specific energy (per tonne)", "Total energy (per day)", "Production"):
        assert title in html, f"the partition panel must carry its own title {title!r}"


def test_the_kiln_and_mill_groups_render_their_own_members(settings: DashboardSettings) -> None:
    html = energy_view.render_energy(_model(), settings=settings)
    for tag in ("kiln_fuel_rate_tph", "burning_zone_temperature",
                "mill_motor_power_kw", "simulated_blaine_cm2_g"):
        assert tag in html, f"the KPI groups must carry {tag}"
    assert "1,451" in html  # the kiln's own number, at FormatSettings precision
    assert "2,500" in html


# =============================================================================
# B — item 12, VERBATIM: both halves of every pair, never the favorable one alone
# =============================================================================
def test_specific_and_total_energy_appear_together(settings: DashboardSettings) -> None:
    """Item 12, VERBATIM: "The dashboard must NOT show only the favorable metric." The provider
    binds each specific-energy figure and its daily total into one plant group; the view model
    partitions that group, and this renderer shows all three partitions on one screen — so both
    halves of every pair appear, with the payload's own pairing note verbatim."""
    html = energy_view.render_energy(_model(), settings=settings)
    for tag in (
        "thermal_energy_kcal_per_kg_clinker",
        "kiln_thermal_energy_kcal_per_day",
        "specific_power_consumption_kwh_t",
        "mill_electrical_energy_kwh_per_day",
    ):
        assert tag in html, f"the screen must carry {tag}"
    assert "kcal/kg" in html and "kcal/day" in html
    assert labels.SPECIFIC_VS_TOTAL_NOTE in html  # the payload's own note, verbatim
    assert "807.9" in html  # the specific figure
    assert "2,323,570,324" in html  # the total it implies, grouped not truncated to a zero
    assert "102,619" in html  # the electrical total, at FormatSettings precision


def test_an_absent_total_never_leaves_the_specific_figure_alone(
    settings: DashboardSettings,
) -> None:
    """The honesty core of item 12: a provider that answered no daily totals gets that absence
    stated in place, beside the specific figures — the unfavorable half is never silently
    dropped, and the pairing note still reads, so the specific figure cannot pass for the whole
    picture."""
    html = energy_view.render_energy(
        _model(total=Panel("Total energy (per day)", (), note="")), settings=settings
    )
    assert "807.9" in html  # the specific half still shows
    assert "unavailable: this provider carries no daily-total figures" in html
    assert labels.SPECIFIC_VS_TOTAL_NOTE in html  # from the specific panel's own note


# =============================================================================
# C — missing energy data: absences stated, never papered over
# =============================================================================
def test_empty_partitions_are_stated_not_papered_over(settings: DashboardSettings) -> None:
    """A provider that answered no energy KPI at all: three stated absences, no invented card.
    The kiln / mill groups are a different partition (item 9) and keep their own cards - what is
    asserted absent is every tag of the energy pair itself."""
    model = _model(
        specific=Panel("Specific energy (per tonne)", (), note=""),
        total=Panel("Total energy (per day)", (), note=""),
        production=Panel("Production", ()),
    )
    html = energy_view.render_energy(model, settings=settings)
    assert html.count("unavailable: this provider carries no") == 3
    for tag in ("thermal_energy_kcal_per_kg_clinker", "specific_power_consumption_kwh_t",
                "kiln_thermal_energy_kcal_per_day", "mill_electrical_energy_kwh_per_day",
                "clinker_production_tph", "cement_production_tph"):
        assert tag not in html, f"no card may be invented for {tag}"


def test_empty_kpi_groups_are_stated_not_papered_over(settings: DashboardSettings) -> None:
    html = energy_view.render_energy(
        _model(kiln=KpiGroup(title="Kiln", values=()),
               mill=KpiGroup(title="Cement mill", values=())),
        settings=settings,
    )
    assert "unavailable: this provider carries no Kiln KPI group" in html
    assert "unavailable: this provider carries no Cement mill KPI group" in html


# =============================================================================
# D — degraded data: a missing number is the payload's own glyph, never a zero
# =============================================================================
def test_a_missing_number_shows_the_absence_glyph_never_a_zero(
    settings: DashboardSettings,
) -> None:
    """A dropped reading is an absence, not a measured-and-zero: the glyph renders, the number
    does not, and the card keeps its own status and provenance rather than a verdict invented
    for it."""
    specific = Panel(
        "Specific energy (per tonne)",
        (_value("thermal_energy_kcal_per_kg_clinker", None, unit="kcal/kg",
                status=Status.UNKNOWN, description="Specific thermal energy consumption"),
         _SPECIFIC[1]),
    )
    html = energy_view.render_energy(_model(specific=specific), settings=settings)
    assert f">{theme.NO_VALUE_TEXT}</p>" in html
    assert "807.9" not in html  # the absent figure is not rendered from anywhere
    assert 'dt-pill--unknown' in html  # the payload's own status word for an absent reading


def test_a_total_with_no_limit_carries_the_no_limit_pill(settings: DashboardSettings) -> None:
    """The daily totals are display aggregations with no band of their own: their status is the
    payload's NO_LIMIT, and the pill renders that - not an OK the renderer awarded."""
    html = energy_view.render_energy(_model(), settings=settings)
    slug = theme.status_slug(Status.NO_LIMIT)
    assert f'dt-pill--{slug}' in html


# =============================================================================
# E — no fabricated values, and the honesty rules every screen carries
# =============================================================================
def test_no_confidence_percentage_and_no_forbidden_control_label(
    settings: DashboardSettings,
) -> None:
    """Item 20: confidence stays categorical, the forbidden control wording never appears, and
    this screen - which reports energy, not savings - claims no saving at all."""
    html = energy_view.render_energy(_model(), settings=settings)
    assert "confidence" not in html.lower()
    assert labels.FORBIDDEN_CONTROL_LABEL not in html
    assert "saving" not in html.lower()


def test_payload_free_text_is_escaped(settings: DashboardSettings) -> None:
    """A card description carrying markup is escaped - the payload cannot inject into the panel."""
    specific = Panel(
        "Specific energy (per tonne)",
        (_value("thermal_energy_kcal_per_kg_clinker", 807.9, unit="kcal/kg",
                description="Specific thermal <script>alert(1)</script>"),),
        note=labels.SPECIFIC_VS_TOTAL_NOTE,
    )
    html = energy_view.render_energy(_model(specific=specific), settings=settings)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# =============================================================================
# F — determinism
# =============================================================================
def test_two_renders_of_one_view_model_are_byte_identical(
    settings: DashboardSettings,
) -> None:
    """No wall clock, no dict ordering, no randomness: the same payload renders the same panel."""
    first = energy_view.render_energy(_model(), settings=settings)
    second = energy_view.render_energy(_model(), settings=settings)
    assert first == second


# =============================================================================
# G — the payload / accessor layer: the frozen view model and the state builder
# =============================================================================
def test_the_real_view_model_describes_its_partitions() -> None:
    """The frozen ``EnergyView.describe()`` carries the whole partition plus the two KPI groups,
    so the payload - not just the renderer - answers the screen's contract."""
    from types import SimpleNamespace

    header = SimpleNamespace(
        title="Energy Monitoring",
        subtitle="",
        describe=lambda: {"title": "Energy Monitoring"},
    )
    model = EnergyView(
        header=header,  # type: ignore[arg-type]
        plant=KpiGroup(title="Plant", values=_SPECIFIC + _RATES + _TOTALS,
                       note=labels.SPECIFIC_VS_TOTAL_NOTE),
        specific=_specific(),
        total=_total(),
        production=_production(),
        kiln=_kiln(),
        mill=_mill(),
        trends=(),
    )
    described = model.describe()
    assert [item["tag"] for item in described["specific"]["values"]] == [
        "thermal_energy_kcal_per_kg_clinker", "specific_power_consumption_kwh_t",
    ]
    assert [item["tag"] for item in described["total"]["values"]] == [
        "kiln_thermal_energy_kcal_per_day", "mill_electrical_energy_kwh_per_day",
    ]
    assert described["specific"]["note"] == labels.SPECIFIC_VS_TOTAL_NOTE
    assert described["kiln"]["title"] == "Kiln"


def test_the_state_layer_partitions_the_plant_group_by_tag(
    stub_provider: Any, settings: DashboardSettings,
) -> None:
    """``DashboardState.energy()`` over the shared stub provider: the three panels are the plant
    group partitioned *by tag* against ``layout.DAILY_TOTALS`` — the same numbers, never a
    second computation — and the totals keep OBSERVED provenance (item 12: a display
    aggregation of observed values, not a fifth data source)."""
    provider = stub_provider()
    state = DashboardState(provider, Clock(provider, settings), settings)
    model = state.energy()

    total_tags = {total.tag for total in DAILY_TOTALS}
    intensity_tags = {total.intensity_tag for total in DAILY_TOTALS}
    rate_tags = {total.rate_tag for total in DAILY_TOTALS}

    assert {value.tag for value in model.specific.values} == intensity_tags
    assert {value.tag for value in model.total.values} == total_tags
    assert {value.tag for value in model.production.values} == rate_tags
    assert model.specific.note == labels.SPECIFIC_VS_TOTAL_NOTE
    assert model.total.note == labels.SPECIFIC_VS_TOTAL_NOTE
    # The partition loses nothing: the three panels together are exactly the plant group.
    partition = {value.tag for value in
                 model.specific.values + model.total.values + model.production.values}
    assert partition == {value.tag for value in model.plant.values}
    # The totals are arithmetic on observed rates (item 12), never a fifth data source.
    assert all(value.provenance == Provenance.OBSERVED for value in model.total.values)
    assert model.kiln.values and model.mill.values


def test_the_state_layer_carries_trend_channels_for_the_intensity_tags(
    stub_provider: Any, settings: DashboardSettings,
) -> None:
    """The payload's ``trends`` are the downsampled specific-energy channels (item 23) — carried
    even though this renderer does not draw charts, so a later chart wave finds them there."""
    provider = stub_provider()
    state = DashboardState(provider, Clock(provider, settings), settings)
    model = state.energy()
    intensity_tags = {total.intensity_tag for total in DAILY_TOTALS}
    assert model.trends, "the stub provider serves history, so the channels must be there"
    assert all(series.tag in intensity_tags for series in model.trends)


# =============================================================================
# H — app.py routing (the _is_energy duck type)
# =============================================================================
def test_view_g_routes_to_the_renderer_in_build_document(
    settings: DashboardSettings,
) -> None:
    html, timings = app.build_document(StubState({"G": _model()}), ("G",), settings=settings)
    assert "G — Energy Monitoring" in html
    assert 'data-role="energy-pair"' in html
    assert "no renderer for this screen yet" not in html  # not the payload fallback
    assert list(timings) == ["G"]


def test_a_screen_with_no_partition_still_falls_to_the_payload_fallback(
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


def test_the_energy_duck_type_does_not_swallow_the_other_screens(
    settings: DashboardSettings,
) -> None:
    """_is_energy keys on ``specific`` AND ``total``; A carries stages/plant, H carries
    predictions/anomaly, J carries ``view``, B/E carry line/snapshot — none has the partition,
    so their routing is untouched (this wave's scope rule)."""

    @dataclass(frozen=True)
    class StubOverviewLike:
        header: StubHeader = field(default_factory=StubHeader)
        stages: object = None
        plant: object = None

    @dataclass(frozen=True)
    class StubIntelligenceLike:
        header: StubHeader = field(default_factory=StubHeader)
        predictions: object = None
        anomaly: object = None

    @dataclass(frozen=True)
    class StubOptimizationLike:
        header: StubHeader = field(default_factory=StubHeader)
        view: Any = None

    @dataclass(frozen=True)
    class StubTwinLike:
        header: StubHeader = field(default_factory=StubHeader)
        line: str = "kiln"
        snapshot: object = None

    assert not app._is_energy(StubOverviewLike())
    assert not app._is_energy(StubIntelligenceLike())
    assert not app._is_energy(StubOptimizationLike())
    assert not app._is_energy(StubTwinLike())
    assert app._is_energy(_model())


# =============================================================================
# The golden file
# =============================================================================
#: The stored render of the stub payload above. Regenerate after a *deliberate* renderer change:
#:
#:     python -c "from pathlib import Path; from tests.test_task6_energy_view import \
#: _model; from src.digital_twin.settings import DashboardSettings; \
#: from src.visualization import energy_view; \
#: Path('tests/golden/view_g_normal.html').write_bytes(energy_view.render_energy(\
#: _model(), settings=DashboardSettings.from_config()).encode('utf-8'))"
#:
#: Written with ``write_bytes`` so the fixture keeps its LF newlines in the repository; the
#: comparison below normalises either way, because ``core.autocrlf`` checkouts differ by machine.
GOLDEN_PATH = Path(__file__).parent / "golden" / "view_g_normal.html"

GOLDEN_HINT = (
    "view G's renderer no longer matches its golden file. This is a REGRESSION unless the renderer "
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
    html = energy_view.render_energy(_model(), settings=settings)

    assert html == _golden(), GOLDEN_HINT
    # The fixture is not empty and not a stale stub of itself: it carries the panel's anchors.
    assert 'data-role="energy-pair"' in html
    assert 'data-role="energy-kpi"' in html
