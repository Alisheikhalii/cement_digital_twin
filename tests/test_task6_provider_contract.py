"""Task #6 Tier 1: the ``DataProvider`` contract, provenance separation and substitutability.

``TASK6_RECOVERY_PLAN.md`` Section 7 phase 6B and Section 9 "Tier 1" define this file as the
oracle that has to exist *before* any Task #6 code is trusted, and Section 10 explains why it is
built on a stub rather than on :class:`~src.digital_twin.synthetic.SyntheticDataProvider`: one
``DashboardState.views()`` costs 7.9 s against the real provider and 0.4 ms against a stub, because
that 7.9 s is provider data-fetching and nothing else. Everything below therefore runs against
``stub_provider`` from ``tests/conftest.py``, which is the point - a test that needs the real
simulator to check the *contract* would be testing the wrong thing.

What this file pins, and nothing more:

* **the contract itself** - fifteen abstract methods, an optional clock surface that refuses rather
  than pretends, and no lingering abstract method on either shipped implementation (plan 3.1-3.2);
* **provenance separation** (directive item 1, PRD 26) - the four data sources OBSERVED / TRUTH /
  PREDICTION / RECOMMENDATION never share one payload channel, and ``CONFIGURATION`` stays metadata;
* **the PRD 26.1 refusal** - every data method of :class:`RealPlantDataProvider` raises with the two
  documents a reader needs next, while its constructor, ``capabilities()`` and ``describe()`` stay
  live so a dashboard can still render a header for it;
* **substitutability** (FR-14) - :class:`DashboardState` and :class:`DashboardSession` accept a
  provider they have never seen, with no dashboard change, and degrade rather than crash when that
  provider can answer almost nothing;
* **the T1-06 honesty failure** - two ``xfail(strict=True)`` tests holding the *correct* derived-badge
  behaviour, so the suite stays green today and turns red the moment phase 6D half-fixes it.

Deliberately absent: any assertion about a process value, an alarm band or a model metric. Those
belong to Tasks #2-#5, which are frozen; a Tier-1 test that pinned one would couple the dashboard
contract to the simulator's tuning, which is exactly the coupling FR-14 exists to forbid.
"""

from __future__ import annotations

import inspect

import pytest

from tests.conftest import STUB_PROVIDER_NAME, STUB_TIMESTAMP, STUB_UNCERTAINTY

#: The fifteen abstract methods of PRD 26.1 + directive item 1, written out rather than derived.
#: Deriving them from ``__abstractmethods__`` would make the test a tautology; this list is the
#: independent statement of the contract, so *adding* a sixteenth method or quietly dropping one
#: fails here and forces the change to be argued for.
CONTRACT_METHODS: frozenset[str] = frozenset(
    {
        # PRD 26.1, verbatim
        "get_timeseries",
        "get_tag_metadata",
        # directive item 1: capability advertisement + the ten data kinds
        "capabilities",
        "get_current_state",
        "get_truth_state",
        "get_sensor_values",
        "get_history",
        "get_equipment_status",
        "get_kpis",
        "get_operating_regime",
        "get_anomaly_state",
        "get_predictions",
        "get_optimization",
        "run_what_if",
        "what_if_sliders",
    }
)

#: The one method :class:`RealPlantDataProvider` answers: a view asks it first so it can find out
#: what is unavailable without an exception per panel (``real_plant.py`` :meth:`capabilities`).
REAL_PLANT_LIVE_METHOD = "capabilities"

#: Minimal, schema-valid arguments for the methods that need one, so the refusal is reached rather
#: than a ``TypeError``. No engineering meaning - a stub never looks at them.
REAL_PLANT_ARGS: dict[str, tuple[tuple, dict]] = {
    "get_timeseries": (("burning_zone_temperature",), {}),
    "get_sensor_values": ((("burning_zone_temperature",),), {}),
    "get_history": ((("burning_zone_temperature",),), {}),
}

#: The xfail reason for T1-06, written once because it must cite *both* defect sites. A phase-6D
#: fix that repairs only the first one leaves the honesty violation live in the twin's own HTML, and
#: a single-site reason would let that half-fix look green.
BADGE_XFAIL_REASON = (
    "T1-06 (TASK6_RECOVERY_PLAN.md B-7): the 'Synthetic Demonstration' badge is hard-coded at TWO "
    "sites, not one - src/digital_twin/state.py:570 (badge=labels.SYNTHETIC_DEMONSTRATION_LABEL, "
    "unconditional inside DashboardState._header) and src/visualization/svg_twin.py:530 "
    "(badge = theme.html(labels.SYNTHETIC_DEMONSTRATION_LABEL), inside _header_html). Both ignore "
    "ProviderCapabilities.synthetic (src/digital_twin/payloads.py:181). The recovery plan names "
    "only the first. Fixed in phase 6D; until BOTH sites derive the badge, this stays xfail."
)

#: Parameter names a phase-6D fix could plausibly use to hand the twin renderer the fact it is
#: missing. Probed rather than assumed, so the site-2 test flips green for any of them instead of
#: silently xfailing forever on a ``TypeError`` because 6D picked a different word.
TWIN_CAPABILITY_PARAMETERS = ("capabilities", "caps", "provider_capabilities", "synthetic")


def _twin_capability_kwargs(func, *, synthetic: bool) -> dict | None:
    """The keyword by which ``func`` can be told whether its source is synthetic, or ``None``.

    ``svg_twin._header_html`` receives only ``snapshot`` and ``title``, so today no such keyword
    exists anywhere on the render path and this returns ``None`` - which is the defect, stated as a
    fact about the signature rather than as a guess about the eventual API.
    """
    from src.digital_twin.payloads import ProviderCapabilities

    names = inspect.signature(func).parameters
    for name in TWIN_CAPABILITY_PARAMETERS:
        if name not in names:
            continue
        if name == "synthetic":
            return {name: synthetic}
        flags = dict.fromkeys(
            (f.name for f in ProviderCapabilities.__dataclass_fields__.values() if f.name != "name"),
            False,
        )
        flags.pop("missing", None)
        flags["synthetic"] = synthetic
        return {name: ProviderCapabilities(name=STUB_PROVIDER_NAME, **flags)}
    return None


# =============================================================================
# Fixtures local to this file
# =============================================================================
@pytest.fixture(scope="module")
def dashboard_settings():
    """The loaded ``configs/dashboard.yaml`` presentation constants (NFR-6: none are written here)."""
    from src.digital_twin.settings import DashboardSettings

    return DashboardSettings.from_config()


@pytest.fixture
def make_state(stub_provider, dashboard_settings):
    """Wire a provider into :class:`DashboardState` exactly as ``app.py`` would (item 21).

    Returns ``(state, provider)`` and resets ``provider.calls`` afterwards, because
    :class:`~src.visualization.clock.Clock` seeds its position with one ``get_current_state`` at
    construction: a per-frame call-count assertion has to start from a clean counter or it would be
    measuring the wiring instead of the frame.
    """
    from src.digital_twin.state import DashboardState
    from src.visualization.clock import Clock

    def build(**flags):
        provider = stub_provider(**flags)
        state = DashboardState(provider, Clock(provider, dashboard_settings), dashboard_settings)
        provider.calls.clear()
        return state, provider

    return build


# =============================================================================
# Contract completeness (plan Section 9 Tier 1: "DataProvider has exactly 15 abstract methods")
# =============================================================================
def test_the_contract_declares_exactly_the_fifteen_abstract_methods():
    """Plan 3.1: the two PRD 26.1 methods plus directive item 1's capability + ten data kinds."""
    from src.digital_twin.provider import DataProvider

    assert DataProvider.__abstractmethods__ == CONTRACT_METHODS
    assert len(DataProvider.__abstractmethods__) == len(CONTRACT_METHODS) == 15


def test_the_stub_satisfies_the_whole_contract(stub_provider):
    """A provider the dashboard has never seen is usable iff it implements all fifteen (FR-14)."""
    from src.digital_twin.provider import DataProvider

    provider = stub_provider()
    assert isinstance(provider, DataProvider)
    assert type(provider).__abstractmethods__ == frozenset()
    for method in sorted(CONTRACT_METHODS):
        assert callable(getattr(provider, method)), method


def test_the_synthetic_provider_leaves_no_abstract_method_unimplemented():
    """Plan 3.2 declares ``SyntheticDataProvider`` sound; this is the check, not the claim.

    Each of the fifteen must be overridden *below* the ABC - inheriting an abstract method would
    make the class uninstantiable, but inheriting a method Python no longer marks abstract would
    make it silently incomplete.
    """
    from src.digital_twin.provider import DataProvider
    from src.digital_twin.synthetic import SyntheticDataProvider

    assert SyntheticDataProvider.__abstractmethods__ == frozenset()
    for method in sorted(CONTRACT_METHODS):
        own = getattr(SyntheticDataProvider, method)
        inherited = getattr(DataProvider, method)
        assert own is not inherited, f"{method} is not implemented by SyntheticDataProvider"


def test_the_optional_clock_surface_refuses_rather_than_pretending(stub_provider):
    """``provider.py`` 15-18: clock control is optional and must refuse, never fake a position.

    The stub overrides none of it, so this pins the ABC's own behaviour: a provider with no
    simulated time stays a valid provider, and the dashboard learns that from an exception type it
    can catch rather than from a number that was never measured.
    """
    from src.digital_twin.payloads import LIVE
    from src.digital_twin.provider import CapabilityError

    provider = stub_provider()
    assert issubclass(CapabilityError, NotImplementedError)
    assert provider.modes() == (LIVE,)
    assert provider.window() is None
    for call in (
        lambda: provider.set_mode("REPLAY"),
        lambda: provider.advance(),
        lambda: provider.reset(),
        lambda: provider.scenarios(),
        lambda: provider.select_scenario("normal_operation"),
        lambda: provider.seek(STUB_TIMESTAMP),
    ):
        with pytest.raises(CapabilityError):
            call()


# =============================================================================
# Provenance separation (directive item 1; plan Section 9 Tier 1 "provenance never co-mingled")
# =============================================================================
def test_the_four_data_sources_are_the_documented_four_and_configuration_is_metadata():
    """``provenance.py`` 3-14: ``DATA_SOURCES`` is exactly four; ``CONFIGURATION`` is not data."""
    from src.digital_twin.provenance import DATA_SOURCES, Provenance

    assert DATA_SOURCES == (
        Provenance.OBSERVED,
        Provenance.TRUTH,
        Provenance.PREDICTION,
        Provenance.RECOMMENDATION,
    )
    assert Provenance.CONFIGURATION not in DATA_SOURCES
    assert set(Provenance) == set(DATA_SOURCES) | {Provenance.CONFIGURATION}


def test_the_observed_and_truth_snapshots_are_single_source_and_disjoint(stub_provider):
    """Item 1 channels 1 and 2: an instrument reading and the simulator's truth never share a payload."""
    from src.digital_twin.provenance import Provenance, data_sources_of

    provider = stub_provider()
    observed = provider.get_current_state()
    truth = provider.get_truth_state()

    assert not observed.mixed_sources()
    assert not truth.mixed_sources()
    assert data_sources_of(observed.values.values()) == {Provenance.OBSERVED}
    assert data_sources_of(truth.values.values()) == {Provenance.TRUTH}
    assert observed.provenance is not truth.provenance
    assert observed.source != truth.source


def test_the_forecast_keeps_the_observed_present_apart_from_the_predicted_future(stub_provider):
    """Item 1 channel 8 / PRD 13.1: ``PredictionSet`` is two channels on purpose, not one blend.

    ``current`` is what the instrument reports now; each ``by_horizon`` entry is Model A's output.
    Fusing them into one row of "values" is precisely what the directive forbids, so each horizon is
    checked for a single source, a stated horizon and an ensemble spread in the target's own unit
    (PRD 13.1.1 - a width, never a confidence percentage).
    """
    from src.digital_twin.provenance import Provenance, data_sources_of

    predictions = stub_provider().get_predictions("kiln")

    assert data_sources_of(predictions.current) == {Provenance.OBSERVED}
    assert all(value.horizon_min is None for value in predictions.current)
    assert all(value.uncertainty is None for value in predictions.current)

    assert predictions.horizons_min == tuple(sorted(predictions.by_horizon))
    for minutes, values in predictions.by_horizon.items():
        assert data_sources_of(values) == {Provenance.PREDICTION}, minutes
        assert all(value.horizon_min == minutes for value in values)
        assert all(value.uncertainty == STUB_UNCERTAINTY for value in values)


def test_every_kpi_group_and_equipment_channel_carries_one_source(stub_provider):
    """Items 9 and 12 / item 2: a KPI card group and an equipment readout are each one channel.

    The daily totals of item 12 are the interesting case: they are arithmetic over observed values,
    so they stay ``OBSERVED`` rather than becoming a fifth source - if a total ever arrived tagged
    differently it would split the plant KPI group into a mixed channel here.
    """
    from src.digital_twin.provenance import Provenance, data_sources_of

    provider = stub_provider()

    groups = provider.get_kpis()
    assert groups
    for kpis in groups:
        assert data_sources_of(kpis.values) == {Provenance.OBSERVED}, kpis.title

    equipment = provider.get_equipment_status()
    assert equipment
    for item in equipment:
        channel = tuple(v for v in ((item.driver,) + item.constraints) if v is not None)
        assert len(data_sources_of(channel)) <= 1, item.name


def test_the_operating_regime_is_configuration_and_not_a_data_source(stub_provider):
    """Item 1 channel 6 / PRD 11.4: a regime label is a configured fact, never a model output.

    ``real_plant.get_operating_regime`` says the same thing from the other side - a real plant has
    no such label to read, which is why it cannot be a *data* source on either provider.
    """
    from src.digital_twin.provenance import DATA_SOURCES, Provenance

    regime = stub_provider().get_operating_regime()
    assert regime.provenance is Provenance.CONFIGURATION
    assert regime.provenance not in DATA_SOURCES


def test_no_view_model_mixes_two_data_sources(make_state):
    """Item 22: the ten finished screens are audited channel by channel and must all come back clean."""
    from src.digital_twin.state import VIEWS, mixed_channels, value_channels

    state, _ = make_state()
    views = state.views()

    assert set(views) == {row[1] for row in VIEWS}
    for key, view in views.items():
        assert mixed_channels(view) == {}, key
    # A clean audit is only meaningful if the audit actually looked at something.
    assert any(value_channels(view) for view in views.values())


# =============================================================================
# The PRD 26.1 refusal (plan Section 9 Tier 1: "RealPlantDataProvider raises correctly")
# =============================================================================
def test_every_data_method_of_the_real_plant_stub_refuses_and_says_what_is_missing():
    """PRD 26.1: ``NotImplementedError`` per method body, with a clear TODO and the two documents.

    The method list is derived from the contract minus ``capabilities()`` rather than hand-written,
    so a sixteenth contract method added without a refusal here fails this test instead of shipping
    as a silent ``AttributeError`` in a panel.
    """
    from datetime import datetime

    from src.digital_twin import real_plant
    from src.digital_twin.provider import DataProvider

    provider = real_plant.RealPlantDataProvider("plant_export.csv")
    refusing = sorted(DataProvider.__abstractmethods__ - {REAL_PLANT_LIVE_METHOD})
    assert len(refusing) == 14

    stamp = datetime.fromisoformat(STUB_TIMESTAMP)
    for method in refusing:
        args, kwargs = REAL_PLANT_ARGS.get(method, ((), {}))
        if method == "get_timeseries":
            args = (args[0], stamp, stamp)
        with pytest.raises(NotImplementedError) as raised:
            getattr(provider, method)(*args, **kwargs)
        message = str(raised.value)
        assert "TODO: " in message, method
        assert real_plant.REQUIREMENTS_DOC in message, method
        assert real_plant.TRANSFER_SECTION in message, method
        assert real_plant.TAG_MAPPING_CONFIG in message, method


def test_the_real_plant_stub_still_constructs_advertises_and_describes_itself():
    """PRD 26.1 / FR-14: the header must render for a provider that can answer nothing.

    ``__init__``, ``capabilities()`` and ``describe()`` stay live precisely so a dashboard handed one
    of these degrades every panel instead of failing at construction - and ``synthetic=False`` is the
    honest answer that item 20's header is supposed to read.
    """
    from src.digital_twin import real_plant

    provider = real_plant.RealPlantDataProvider(kind="opcua", endpoint="opc.tcp://plant:4840")
    assert provider.kind == "opcua"

    caps = provider.capabilities()
    assert caps.name == real_plant.PROVIDER_NAME
    flags = caps.describe()
    assert not any(flags[flag] for flag in ("synthetic", "truth", "history", "live"))
    assert not any(flags[flag] for flag in ("predictions", "anomaly", "optimization", "what_if"))
    assert len(caps.missing) == len(CONTRACT_METHODS) - 2  # every kind but capabilities + timeseries

    described = provider.describe()
    assert described["implemented"] is False
    assert described["profile_kind"] == "opcua"
    assert real_plant.REQUIREMENTS_DOC in described["status"]
    assert real_plant.TRANSFER_SECTION in described["status"]


# =============================================================================
# Substitutability (FR-14; plan Section 9 Tier 1 "DashboardState accepts the stub unchanged")
# =============================================================================
def test_the_dashboard_state_accepts_a_provider_it_has_never_seen(make_state):
    """FR-14: swapping the source changes one class and no view - not even the footer.

    ``DashboardState`` is constructed with the two things item 21 lets this layer know, a provider
    and a clock, and nothing in ``state.py`` is touched to make the stub work.
    """
    state, provider = make_state()

    assert state.capabilities().name == STUB_PROVIDER_NAME == provider.name
    frame = state.frame()
    assert frame.snapshot.timestamp == STUB_TIMESTAMP
    assert frame.equipment and frame.kpis
    assert state.footer().capabilities.name == STUB_PROVIDER_NAME
    assert state.clock_state() is not None


def test_every_screen_builds_from_its_id_and_from_its_key(make_state):
    """Item 2 / ``state.py`` :data:`VIEWS`: ten screens, dispatchable as ``"A"`` or ``"overview"``."""
    from src.digital_twin.state import VIEWS

    state, _ = make_state()
    assert len(VIEWS) == 10

    for view_id, key, title, _subtitle in VIEWS:
        by_id = state.view(view_id)
        by_key = state.view(key)
        assert type(by_id) is type(by_key)
        assert by_id.header.view_id == view_id
        assert by_id.header.key == key
        assert by_id.header.title == title

    with pytest.raises(KeyError):
        state.view("not-a-screen")


def test_all_ten_screens_come_from_one_shared_read_of_the_provider(make_state):
    """``state.py`` :meth:`views`: one frame, so every screen shows the same instant (items 2, 21).

    Asserted through the stub's call counter, which is the reason it has one: ten screens must cost
    one ``get_current_state``, not ten. This is the property the plan's 7.9 s measurement makes
    load-bearing - a per-view re-read would multiply the real provider's cost by ten.
    """
    from src.digital_twin.state import VIEWS

    state, provider = make_state()
    views = state.views()

    assert len(views) == len(VIEWS)
    assert provider.calls["get_current_state"] == 1
    assert provider.calls["get_equipment_status"] == 1
    assert provider.calls["get_kpis"] == 1
    assert provider.calls["get_operating_regime"] == 1
    assert {view.header.timestamp for view in views.values()} == {STUB_TIMESTAMP}


def test_a_session_wrapper_around_the_stub_builds_the_same_screens(stub_provider, dashboard_settings):
    """FR-14 through the convenience layer: ``DashboardSession`` is not a second contract.

    Built by hand rather than through :meth:`DashboardSession.build`, which would train models; the
    point here is that ``from_session`` reads only ``provider`` / ``clock`` / ``settings`` / notes.
    """
    from src.digital_twin.session import DashboardSession, ModelLayer
    from src.digital_twin.state import VIEWS, DashboardState
    from src.visualization.clock import Clock

    provider = stub_provider()
    session = DashboardSession(
        provider=provider,
        clock=Clock(provider, dashboard_settings),
        settings=dashboard_settings,
        models=ModelLayer(),
        training_source=STUB_PROVIDER_NAME,
        replay_source=STUB_PROVIDER_NAME,
    )
    state = DashboardState.from_session(session)

    assert state.capabilities().name == STUB_PROVIDER_NAME
    assert set(state.views()) == {row[1] for row in VIEWS}


def test_a_capability_poor_provider_degrades_instead_of_crashing(make_state):
    """``payloads.py`` 174-177: the dashboard must stay renderable when almost nothing is available.

    This is the case that makes the provider genuinely replaceable rather than nominally so - the
    same shape :class:`RealPlantDataProvider` presents, without its refusal messages in the way.
    """
    from src.digital_twin.state import VIEWS, mixed_channels

    state, provider = make_state(
        truth=False,
        history=False,
        predictions=False,
        anomaly=False,
        optimization=False,
        what_if=False,
    )
    views = state.views()

    assert set(views) == {row[1] for row in VIEWS}
    for key, view in views.items():
        assert mixed_channels(view) == {}, key
    assert state.history(("burning_zone_temperature",)) == ()
    assert views["intelligence"].predictions.available is False
    assert views["intelligence"].anomaly.available is False
    assert views["optimization"].view.available is False
    assert views["what_if"].view.available is False
    assert provider.capabilities().missing


def test_the_stub_fixture_hands_out_a_fresh_call_counter(stub_provider):
    """The fixture's own contract: counters must not leak, or a call-count assertion means nothing."""
    first = stub_provider()
    second = stub_provider()

    assert first is not second
    assert not first.calls and not second.calls
    first.get_current_state()
    assert first.calls["get_current_state"] == 1
    assert second.calls["get_current_state"] == 0


# =============================================================================
# T1-06: the hard-coded honesty badge (plan B-7) - the correct behaviour, held as xfail
# =============================================================================
@pytest.mark.xfail(strict=True, reason=BADGE_XFAIL_REASON)
def test_the_screen_header_badge_is_derived_from_the_providers_synthetic_flag(make_state):
    """T1-06 site 1 - ``state.py:570``. Item 20: the header states what the source actually is.

    A provider reporting ``synthetic=False`` is telling the truth about itself, and a header that
    prints "Synthetic Demonstration" over it is making a false claim about the data's origin - the
    exact class of dishonesty the standing-label rules exist to prevent. The badge must come from
    :attr:`ProviderCapabilities.synthetic` (``payloads.py:181``) through
    :func:`labels.presentation_card_label`, which already encodes the two allowed wordings.
    """
    from src import labels

    state, provider = make_state(synthetic=False)
    caps = provider.capabilities()
    assert caps.synthetic is False
    expected = labels.presentation_card_label("synthetic" if caps.synthetic else "estimate")
    assert expected == labels.SIMULATION_ESTIMATE_LABEL

    for key, view in state.views().items():
        assert view.header.badge == expected, key


@pytest.mark.xfail(strict=True, reason=BADGE_XFAIL_REASON)
def test_the_animated_twin_badge_is_derived_from_the_providers_synthetic_flag(
    stub_provider, dashboard_settings
):
    """T1-06 site 2 - ``svg_twin.py:530``, the site the recovery plan does not name.

    ``_header_html`` receives only the snapshot and a title, so it cannot see capabilities at all: a
    phase-6D fix has to thread that fact through :func:`render_twin` / :func:`twin_html` /
    :func:`twin_document`. Until it does, the twin's own HTML keeps asserting "Synthetic
    Demonstration" over a source that says it is not synthetic, so a 6D change touching only
    ``state.py`` leaves the honesty violation live here while site 1 goes green.

    The assertion is bidirectional and wording-agnostic on purpose: the badge must be *absent* for a
    source reporting ``synthetic=False`` and *present* for one reporting ``synthetic=True``. That is
    what "derived" means, and it holds whether 6D substitutes the other allowed label or drops the
    badge entirely.
    """
    from src import labels
    from src.visualization import svg_twin

    provider = stub_provider()
    snapshot = provider.get_current_state()
    equipment = provider.get_equipment_status()

    honest = _twin_capability_kwargs(svg_twin.render_twin, synthetic=False)
    assert honest is not None, (
        "svg_twin.render_twin takes no capability argument, so _header_html (svg_twin.py:530) "
        f"cannot know whether its source is synthetic and emits {labels.SYNTHETIC_DEMONSTRATION_LABEL!r} "
        f"unconditionally; expected one of {TWIN_CAPABILITY_PARAMETERS}"
    )
    synthetic = _twin_capability_kwargs(svg_twin.render_twin, synthetic=True)

    def render(extra: dict) -> str:
        return svg_twin.render_twin(
            snapshot, equipment, settings=dashboard_settings, animate=False, **extra
        )

    assert labels.SYNTHETIC_DEMONSTRATION_LABEL not in render(honest)
    assert labels.SYNTHETIC_DEMONSTRATION_LABEL in render(synthetic)
