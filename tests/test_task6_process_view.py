"""Views C / D / F renderer tests (Wave CDF): the process detail screens and their routing.

Deliberately bounded, like ``test_task6_overview_view.py`` and ``test_task6_energy_view.py``:
nothing here builds a session, trains a model or runs the optimizer. The renderer under test
is the real :mod:`src.visualization.process_view` — ONE renderer for all three screens, which
is the wave's core architectural claim and what the tests below pin from several angles —
driven by real view-model pieces
(:class:`~src.digital_twin.state.Panel`,
:class:`~src.digital_twin.state.EquipmentDetail`,
:class:`~src.digital_twin.state.ProcessView`,
:class:`~src.digital_twin.payloads.EquipmentStatus`,
:class:`~src.digital_twin.provenance.Value`) and, for the state-layer tests, the real
:meth:`src.digital_twin.state.DashboardState.kiln_process` / ``clinker_cooler`` /
``mill_separator`` builders over the shared ``conftest.py`` stub provider, which serves every
component and panel in exactly the shape the real provider does.

Covers the items this wave surfaces on one screen:

* **item 4 (inspector half)** — each component's state word, health, driving variable and own
  readout, rendered from the payload's own values;
* **items 5 / 6** — the grouped process panels (kiln process, kiln emissions, mill process),
  every row a payload ``Value``;
* **item 9** — the KPI group the screen's dataset owns, rendered whole;
* **item 20** — the honesty rules: no fabricated value, absences as the payload's own glyph,
  the standing no-plant-connection statement, HTML escaping, determinism.

Plus the two properties that are this wave's own: **view D's designed emptiness** (no panels,
no KPI group — stated as fact, never shown as an error, never filled in) and **the shared
renderer / shared dispatch** (one code path serves C, D and F; ``app._is_process`` routes all
three and collides with no other screen).

Self-contained on purpose for the renderer tests (no ``conftest.py`` fixture needed for them);
the state-layer tests use the shared ``stub_provider`` fixture the other Task #6 modules use,
so this module runs alone with ``pytest tests/test_task6_process_view.py`` either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.payloads import EquipmentStatus, KpiGroup
from src.digital_twin.provenance import Provenance, Status, Value
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import DashboardState, EquipmentDetail, Panel, ProcessView
from src.visualization import process_view, theme
from src.visualization.clock import Clock

#: Sentinel distinguishing "no driver given" (build the stub's own) from ``driver=None`` (the
#: absent-driver honesty case, which must reach the payload as ``None``).
_UNSET_DRIVER: Any = object()


def _value(
    tag: str,
    value: float | None,
    *,
    unit: str = "°C",
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


def _status(
    name: str,
    *,
    title: str = "",
    kind: str = "StubModel",
    state: str = labels.EQUIPMENT_RUNNING,
    health: float = 1.0,
    driver: Any = _UNSET_DRIVER,
    detail: str = "",
) -> EquipmentStatus:
    """One :class:`EquipmentStatus` — the component card the view model carries it from.

    ``driver`` uses a sentinel default so an explicit ``driver=None`` (the absent-driver case)
    reaches the payload as ``None`` rather than being replaced by the stub's own value.
    """
    if driver is _UNSET_DRIVER:
        driver = _value(f"{name.lower()}_driver", 50.0, unit="%",
                        description=f"{name} driving variable")
    return EquipmentStatus(
        name=name,
        unit=title or name,
        kind=kind,
        state=state,
        health=health,
        driver=driver,
        detail=detail,
    )


def _detail(
    name: str,
    readout_tags: tuple[tuple[str, float], ...] = (),
    **status_kwargs: Any,
) -> EquipmentDetail:
    """One component card: a status plus the readout of its own output tags."""
    return EquipmentDetail(
        status=_status(name, **status_kwargs),
        readout=Panel(
            title=status_kwargs.get("title", name),
            values=tuple(
                _value(tag, value, description=f"{tag} reading") for tag, value in readout_tags
            ),
        ),
    )


# -- one stub payload per screen, shaped like the real builders' output ---------------------
#: Component display titles, the layout spec's own (``layout.EQUIPMENT``), so the stubs read
#: like the real payloads and the assertions below name the real wording.
_TITLES: dict[str, str] = {
    "Preheater": "Preheater tower",
    "Precalciner": "Precalciner",
    "RotaryKiln": "Rotary kiln",
    "Cooler": "Clinker cooler",
    "FanFuel": "Fuel & fan system",
    "Mill": "Cement mill",
    "Separator": "Dynamic separator",
    "FanFilter": "Mill fan & filter",
    "Product": "Finished cement",
}

#: View C: three components, two panels (kiln process + kiln emissions), the Kiln KPI group.
_C_READOUTS: dict[str, tuple[tuple[str, float], ...]] = {
    "Preheater": (
        ("preheater_outlet_temperature", 330.0),
        ("preheater_pressure", -500.0),
    ),
    "Precalciner": (("calciner_temperature", 880.0),),
    "RotaryKiln": (
        ("burning_zone_temperature", 1451.0),
        ("kiln_feed_rate_tph", 190.0),
    ),
}
_C_COMPONENTS = tuple(
    _detail(name, tags, title=_TITLES[name]) for name, tags in _C_READOUTS.items()
)
_C_PANELS = (
    Panel(
        "Kiln process indicators",
        (
            _value("kiln_inlet_temperature", 1100.0, description="Kiln inlet temperature"),
            _value("kiln_inlet_pressure", -100.0, unit="mbar",
                   description="Kiln inlet pressure"),
        ),
    ),
    Panel(
        "Kiln emissions",
        (
            _value("CO2_percent", 28.0, unit="%",
                   status=Status.NO_LIMIT, description="CO2 concentration"),
            _value("NOx_ppm", 780.0, unit="ppm", description="NOx concentration"),
        ),
    ),
)
_C_KPIS = KpiGroup(
    title="Kiln",
    values=(
        _value("kiln_fuel_rate_tph", 4.1, unit="t/h", description="Kiln fuel rate"),
        _value("burning_zone_temperature", 1451.0, description="Burning zone temperature"),
    ),
)

#: View D: two components, NO panels, NO KPI group — the designed emptiness this wave pins.
_D_COMPONENTS = (
    _detail(
        "Cooler",
        (
            ("clinker_temperature", 1370.0),
            ("cooler_outlet_temperature", 120.0),
            ("cooler_fan_power", 750.0),
        ),
        title="Clinker cooler",
    ),
    _detail(
        "FanFuel",
        (
            ("kiln_fuel_rate_tph", 4.1),
            ("ID_fan_speed", 70.0),
            ("oxygen_percent", 3.2),
            ("CO_ppm", 850.0),
        ),
        title="Fuel & fan system",
    ),
)

#: View F: four components, one panel (mill process), the Cement mill KPI group.
_F_READOUTS: dict[str, tuple[tuple[str, float], ...]] = {
    "Mill": (
        ("mill_feed_rate_tph", 190.0),
        ("mill_motor_power_kw", 2500.0),
    ),
    "Separator": (("separator_speed_rpm", 115.0),),
    "FanFilter": (("fan_speed", 1400.0),),
    "Product": (("cement_production_tph", 125.0),),
}
_F_COMPONENTS = tuple(
    _detail(name, tags, title=_TITLES[name]) for name, tags in _F_READOUTS.items()
)
_F_PANELS = (
    Panel(
        "Mill process indicators",
        (
            _value("clinker_feed_rate", 155.0, unit="t/h",
                   description="Clinker feed rate"),
            _value("mill_pressure", -400.0, unit="mbar", description="Mill pressure"),
        ),
    ),
)
_F_KPIS = KpiGroup(
    title="Cement mill",
    values=(
        _value("mill_motor_power_kw", 2500.0, unit="kW", description="Mill motor power"),
        _value("simulated_blaine_cm2_g", 3850.0, unit="cm²/g", description="Simulated Blaine"),
    ),
)


@dataclass(frozen=True)
class StubHeader:
    title: str = "Process detail"
    subtitle: str = "Components and grouped readouts"
    timestamp: str = "2026-01-01T00:00:00Z"
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class StubProcessView:
    """Shaped like ``state.ProcessView``: components, panels, the optional KPI group.

    Carries only what the renderer reads (``header`` for its timestamp/notices, then
    ``components`` / ``panels`` / ``kpis``) — so a field the renderer started reading would
    fail these tests loudly rather than silently fall back to a stub default.
    """

    header: StubHeader = field(default_factory=StubHeader)
    components: tuple[EquipmentDetail, ...] = ()
    panels: tuple[Panel, ...] = ()
    kpis: KpiGroup | None = None


def _view_c() -> StubProcessView:
    return StubProcessView(components=_C_COMPONENTS, panels=_C_PANELS, kpis=_C_KPIS)


def _view_d() -> StubProcessView:
    return StubProcessView(components=_D_COMPONENTS)


def _view_f() -> StubProcessView:
    return StubProcessView(components=_F_COMPONENTS, panels=_F_PANELS, kpis=_F_KPIS)


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
# A — normal rendering: every section, from the payload's own values
# =============================================================================
def test_view_c_renders_all_three_sections(settings: DashboardSettings) -> None:
    html = process_view.render_process(_view_c(), settings=settings)
    assert 'data-role="process-components"' in html
    assert 'data-role="process-panels"' in html
    assert 'data-role="process-kpis"' in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


def test_every_component_renders_its_own_readout(settings: DashboardSettings) -> None:
    html = process_view.render_process(_view_c(), settings=settings)
    for name, tags in _C_READOUTS.items():
        assert name in html, f"the component card must carry its key {name!r}"
        for tag, value in tags:
            assert tag in html, f"{name}'s readout must carry {tag}"


def test_the_driver_line_renders_the_same_value_the_twin_animates_by(
    settings: DashboardSettings,
) -> None:
    """AC-21's input, as text: the driver is the observed ``Value`` view B/E scale motion by."""
    html = process_view.render_process(_view_c(), settings=settings)
    assert "driver" in html
    # every component card carries its driver tag in the driver line
    for name in _C_READOUTS:
        assert f"{name.lower()}_driver" in html, f"{name}'s driver tag must be shown"


def test_the_panels_carry_their_own_titles_and_values(settings: DashboardSettings) -> None:
    html = process_view.render_process(_view_c(), settings=settings)
    for title in ("Kiln process indicators", "Kiln emissions"):
        assert title in html, f"the grouped panel must carry its own title {title!r}"
    assert "kiln_inlet_temperature" in html and "NOx_ppm" in html
    assert "1,451" in html  # the payload's own number, at FormatSettings precision


def test_the_kpi_group_renders_its_own_members(settings: DashboardSettings) -> None:
    html = process_view.render_process(_view_f(), settings=settings)
    assert "Cement mill KPIs" in html
    for tag in ("mill_motor_power_kw", "simulated_blaine_cm2_g"):
        assert tag in html, f"the KPI group must carry {tag}"
    assert "2,500" in html and "3,850" in html


# =============================================================================
# B — view D's designed emptiness: no panels, no KPI group, stated as fact
# =============================================================================
def test_view_d_renders_components_only(settings: DashboardSettings) -> None:
    """View D's payload is components-only by design (see the renderer's module docstring):
    the two component cards render, and both absences are *stated facts* — never shown as a
    failure state, never filled with a panel or KPI group the state layer did not build."""
    html = process_view.render_process(_view_d(), settings=settings)
    assert html.count('data-role="process-component"') == 2
    for value in _D_COMPONENTS[1].readout.values:
        assert value.tag in html, f"the fuel & fan readout must carry {value.tag}"
    assert "no grouped readout panels of its own" in html
    assert "no KPI group of its own" in html


def test_view_ds_stated_emptiness_is_not_an_unavailable_error(
    settings: DashboardSettings,
) -> None:
    """The designed-emptiness wording is a property statement, not the renderer's
    ``unavailable`` honesty word: a provider that answered nothing reads differently from a
    screen that owns no panel by design."""
    html = process_view.render_process(_view_d(), settings=settings)
    assert "no grouped readout panels of its own" in html
    assert f"{process_view.UNAVAILABLE_TEXT}: this screen carries no grouped readout panels" not in html


def test_view_d_still_carries_the_standing_statement(settings: DashboardSettings) -> None:
    html = process_view.render_process(_view_d(), settings=settings)
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


# =============================================================================
# C — missing / degraded component data: absences stated, never papered over
# =============================================================================
def test_an_empty_component_list_is_stated(settings: DashboardSettings) -> None:
    """A provider that reported none of this screen's equipment: one stated absence, no card."""
    html = process_view.render_process(
        StubProcessView(components=()), settings=settings
    )
    assert "this provider reports none of the components this screen focuses on" in html
    assert "Preheater" not in html  # no card is invented


def test_a_component_with_no_readout_is_stated(settings: DashboardSettings) -> None:
    detail = _detail("Preheater", (), title="Preheater tower")
    html = process_view.render_process(
        StubProcessView(components=(detail,)), settings=settings
    )
    assert "Preheater tower" in html  # the card still renders
    assert "this component carries no readout of its own" in html


def test_an_absent_driver_is_stated_never_invented(settings: DashboardSettings) -> None:
    detail = _detail("Preheater", (("preheater_pressure", -500.0),), driver=None,
                     title="Preheater tower")
    html = process_view.render_process(
        StubProcessView(components=(detail,)), settings=settings
    )
    assert "driver unavailable: no driving variable is reported" in html


def test_a_missing_number_shows_the_absence_glyph_never_a_zero(
    settings: DashboardSettings,
) -> None:
    """A dropped reading is an absence, not a measured-and-zero: the glyph renders, the number
    does not, and the row keeps its own status and provenance rather than a verdict invented
    for it."""
    detail = _detail(
        "RotaryKiln",
        (
            ("burning_zone_temperature", None),
            ("kiln_feed_rate_tph", 190.0),
        ),
        title="Rotary kiln",
    )
    assert detail.readout.values[0].value is None  # the dropped reading itself
    html = process_view.render_process(
        StubProcessView(components=(detail,)), settings=settings
    )
    assert f">{theme.NO_VALUE_TEXT}</td>" in html
    assert "190.0" in html  # the present reading keeps its number


def test_an_empty_panel_is_stated(settings: DashboardSettings) -> None:
    model = StubProcessView(
        components=_C_COMPONENTS,
        panels=(Panel("Kiln process indicators", ()),),
        kpis=_C_KPIS,
    )
    html = process_view.render_process(model, settings=settings)
    assert "this provider carries no Kiln process indicators readings" in html


def test_an_empty_kpi_group_is_stated(settings: DashboardSettings) -> None:
    model = StubProcessView(
        components=_C_COMPONENTS,
        panels=_C_PANELS,
        kpis=KpiGroup(title="Kiln", values=()),
    )
    html = process_view.render_process(model, settings=settings)
    assert "this provider carries no Kiln KPI group" in html


# =============================================================================
# D — no fabricated values, and the honesty rules every screen carries
# =============================================================================
def test_no_confidence_percentage_and_no_forbidden_control_label(
    settings: DashboardSettings,
) -> None:
    html = process_view.render_process(_view_c(), settings=settings)
    assert "confidence" not in html.lower()
    assert labels.FORBIDDEN_CONTROL_LABEL not in html
    assert "saving" not in html.lower()


def test_header_notices_render_verbatim(settings: DashboardSettings) -> None:
    """A header that carries notices (the real C/D/F headers carry none today) shows them
    verbatim — the renderer must not be the layer that drops a payload's own honesty text."""
    header = StubHeader(notices=("a payload notice with <markup>",))
    html = process_view.render_process(
        StubProcessView(header=header, components=_C_COMPONENTS), settings=settings
    )
    assert "a payload notice with &lt;markup&gt;" in html


def test_payload_free_text_is_escaped(settings: DashboardSettings) -> None:
    detail = _detail(
        "Preheater",
        (("preheater_pressure", -500.0),),
        title="Preheater <script>alert(1)</script>",
    )
    html = process_view.render_process(
        StubProcessView(components=(detail,)), settings=settings
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# =============================================================================
# E — determinism
# =============================================================================
def test_two_renders_of_one_view_model_are_byte_identical(
    settings: DashboardSettings,
) -> None:
    """No wall clock, no dict ordering, no randomness: the same payload renders the same panel."""
    assert process_view.render_process(
        _view_c(), settings=settings
    ) == process_view.render_process(_view_c(), settings=settings)


# =============================================================================
# F — the shared renderer: one code path, three screens
# =============================================================================
def test_one_renderer_serves_all_three_screens(settings: DashboardSettings) -> None:
    """The wave's core claim: C, D and F share one payload shape and one renderer, with no
    view-id branching. Each screen renders through the same function, and each output carries
    that screen's own components (so the sharing hides nothing and fabricates nothing)."""
    renders = {
        "C": process_view.render_process(_view_c(), settings=settings),
        "D": process_view.render_process(_view_d(), settings=settings),
        "F": process_view.render_process(_view_f(), settings=settings),
    }
    assert "Preheater" in renders["C"] and "Precalciner" in renders["C"]
    assert "Cooler" in renders["D"] and "Fuel &amp; fan system" in renders["D"]
    assert "Separator" in renders["F"] and "Finished cement" in renders["F"]
    # every render is the same shape: the section anchors all three carry
    for html in renders.values():
        for anchor in ("process-components", "process-panels", "process-kpis"):
            assert f'data-role="{anchor}"' in html


# =============================================================================
# G — the payload / accessor layer: the frozen view models and the state builders
# =============================================================================
def test_the_real_view_models_describe_their_screens() -> None:
    """The frozen ``ProcessView.describe()`` carries each screen's components, panels and KPI
    group, so the payload - not just the renderer - answers each screen's contract."""
    from types import SimpleNamespace

    header = SimpleNamespace(describe=lambda: {"title": "Process detail"})
    described = ProcessView(
        header=header,  # type: ignore[arg-type]
        components=_C_COMPONENTS,
        panels=_C_PANELS,
        kpis=_C_KPIS,
    ).describe()
    assert [item["status"]["name"] for item in described["components"]] == [
        "Preheater", "Precalciner", "RotaryKiln",
    ]
    assert [panel["title"] for panel in described["panels"]] == [
        "Kiln process indicators", "Kiln emissions",
    ]
    assert described["kpis"]["title"] == "Kiln"
    # view D's shape: the two components, no panels, no KPI group
    described_d = ProcessView(
        header=header,  # type: ignore[arg-type]
        components=_D_COMPONENTS,
        panels=(),
    ).describe()
    assert described_d["panels"] == [] and described_d["kpis"] is None


def test_the_state_builders_answer_all_three_screens(
    stub_provider: Any, settings: DashboardSettings,
) -> None:
    """``DashboardState.view("C" / "D" / "F")`` over the shared stub provider: each builder
    returns the real ``ProcessView`` with this screen's own components, and the payload is
    complete enough to render — C and F carry their panel(s) and KPI group, D carries its two
    components with neither, by design."""
    provider = stub_provider()
    state = DashboardState(provider, Clock(provider, settings), settings)
    for view_id, expected_components in (
        ("C", ("Preheater", "Precalciner", "RotaryKiln")),
        ("D", ("Cooler", "FanFuel")),
        ("F", ("Mill", "Separator", "FanFilter", "Product")),
    ):
        model = state.view(view_id)
        assert isinstance(model, ProcessView)
        assert tuple(c.status.name for c in model.components) == expected_components
        assert all(c.readout.values for c in model.components), (
            f"every {view_id} component must carry its own readout"
        )
    kiln = state.view("C")
    assert [p.title for p in kiln.panels] == [
        "Kiln process indicators", "Kiln emissions",
    ]
    assert kiln.kpis is not None and kiln.kpis.title == "Kiln"
    cooler = state.view("D")
    assert cooler.panels == () and cooler.kpis is None  # the designed emptiness, at source
    mill = state.view("F")
    assert [p.title for p in mill.panels] == ["Mill process indicators"]
    assert mill.kpis is not None and mill.kpis.title == "Cement mill"


def test_the_state_builders_render_through_the_shared_renderer(
    stub_provider: Any, settings: DashboardSettings,
) -> None:
    """End to end at stub cost: the real state layer's three view models each render through
    the one renderer without error — the shape the real provider serves is the shape the
    renderer reads."""
    provider = stub_provider()
    state = DashboardState(provider, Clock(provider, settings), settings)
    for view_id in ("C", "D", "F"):
        html = process_view.render_process(state.view(view_id), settings=settings)
        assert 'data-role="process-components"' in html
        assert labels.NO_PLANT_CONNECTION_STATEMENT in html


# =============================================================================
# H — app.py routing (the _is_process duck type)
# =============================================================================
def test_views_c_d_and_f_route_to_the_renderer_in_build_document(
    settings: DashboardSettings,
) -> None:
    models = {"C": _view_c(), "D": _view_d(), "F": _view_f()}
    html, timings = app.build_document(StubState(models), ("C", "D", "F"), settings=settings)
    for view_id, marker in (
        ("C", "Preheater"), ("D", "Clinker cooler"), ("F", "Dynamic separator"),
    ):
        assert f"{view_id} — " in html
        assert marker in html, f"view {view_id} must render its own component {marker!r}"
    assert "no renderer for this screen yet" not in html  # not the payload fallback
    assert list(timings) == ["C", "D", "F"]


def test_the_process_duck_type_does_not_swallow_the_other_screens(
    settings: DashboardSettings,
) -> None:
    """_is_process keys on ``components`` AND ``panels``; A carries stages/plant, H carries
    predictions/anomaly, I carries sliders/view, J carries a view with
    recommendation/baselines, B/E carry line/snapshot — none has the pair, so their routing is
    untouched (this wave's scope rule). The twin's own ``panel`` (singular) and ``equipment``
    fields are the near misses this test pins."""

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
    class StubWhatIfLike:
        header: StubHeader = field(default_factory=StubHeader)
        sliders: object = None
        view: object = None

    @dataclass(frozen=True)
    class StubTwinLike:
        header: StubHeader = field(default_factory=StubHeader)
        line: str = "kiln"
        snapshot: object = None
        panel: object = None  # singular — the twin's grouped readout, deliberately near-named
        equipment: tuple[object, ...] = ()

    assert not app._is_process(StubOverviewLike())
    assert not app._is_process(StubIntelligenceLike())
    assert not app._is_process(StubWhatIfLike())
    assert not app._is_process(StubTwinLike())
    assert app._is_process(_view_c())
    assert app._is_process(_view_d())
    assert app._is_process(_view_f())


# =============================================================================
# The golden files
# =============================================================================
#: The stored render of the stub payload above, one per screen. Regenerate after a
#: *deliberate* renderer change:
#:
#:     python -c "from pathlib import Path; from tests.test_task6_process_view import \
#: _view_c, _view_d, _view_f; from src.digital_twin.settings import DashboardSettings; \
#: from src.visualization import process_view; \
#: s = DashboardSettings.from_config(); \
#: Path('tests/golden/view_c_normal.html').write_bytes(process_view.render_process(_view_c(), settings=s).encode('utf-8')); \
#: Path('tests/golden/view_d_normal.html').write_bytes(process_view.render_process(_view_d(), settings=s).encode('utf-8')); \
#: Path('tests/golden/view_f_normal.html').write_bytes(process_view.render_process(_view_f(), settings=s).encode('utf-8'))"
#:
#: Written with ``write_bytes`` so the fixtures keep their LF newlines in the repository; the
#: comparison below normalises either way, because ``core.autocrlf`` checkouts differ by machine.
GOLDEN_PATHS: dict[str, Path] = {
    view_id: Path(__file__).parent / "golden" / f"view_{view_id.lower()}_normal.html"
    for view_id in ("C", "D", "F")
}
_GOLDEN_MODELS: dict[str, Any] = {}  # filled in below the builders, keyed by view id


GOLDEN_HINT = (
    "a process-screen renderer no longer matches its golden file. This is a REGRESSION unless "
    "the renderer was deliberately changed - in which case regenerate the fixture with the "
    "command in the GOLDEN_PATHS comment and say so in the commit message. The golden payloads "
    "are the stubs built by _view_c() / _view_d() / _view_f() in this module: fixed "
    "timestamps, no measured durations, no wall clock, so nothing runtime-dependent is pinned."
)


def _golden(view_id: str) -> str:
    return GOLDEN_PATHS[view_id].read_text(encoding="utf-8").replace("\r\n", "\n")


def _golden_model(view_id: str) -> Any:
    if not _GOLDEN_MODELS:
        _GOLDEN_MODELS.update(C=_view_c(), D=_view_d(), F=_view_f())
    return _GOLDEN_MODELS[view_id]


@pytest.mark.parametrize("view_id", ["C", "D", "F"])
def test_the_render_matches_the_golden_file(view_id: str, settings: DashboardSettings) -> None:
    """The whole output, pinned byte for byte - a silent formatting or wording change fails here.

    Every string assertion above names one property; this one holds the *shape of the whole
    screen* at once, so a change no single property test thought to name (a reordered
    attribute, a changed class name, a reworded heading) still fails. The golden payloads are
    built from the fixed stubs in this module, so the comparison pins the renderer, not the
    run: no timestamp, duration or measured value enters it.
    """
    html = process_view.render_process(_golden_model(view_id), settings=settings)

    assert html == _golden(view_id), f"view {view_id}: {GOLDEN_HINT}"
    # The fixture is not empty and not a stale stub of itself: it carries the screen's anchors.
    assert 'data-role="process-components"' in html
    assert 'data-role="process-panels"' in html
    assert 'data-role="process-kpis"' in html
