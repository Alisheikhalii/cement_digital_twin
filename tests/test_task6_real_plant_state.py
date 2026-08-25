"""Wave 3A: :class:`DashboardState` must be *constructible* over a provider that answers nothing.

PRD 26.1 makes :class:`~src.digital_twin.real_plant.RealPlantDataProvider` a stub whose every data
method raises, and ``real_plant.py`` states the intended consequence precisely: a dashboard handed
one "will get a clear, actionable refusal **from whichever panel it asks first** - not an
``AttributeError``, and not a number". ``tests/test_task6_provider_contract.py`` says the same thing
from the other side - ``__init__`` / ``capabilities()`` / ``describe()`` stay live "precisely so a
dashboard handed one of these degrades every panel instead of **failing at construction**".

Before this file, both statements were false: :class:`~src.visualization.clock.Clock` seeded its
cached position with an unguarded ``provider.get_current_state()``, so the refusal arrived from the
*constructor* rather than from a panel, and no dashboard could be built over the stub at all.

What this file pins - and, just as importantly, what it refuses to pin:

* **construction succeeds** and the session-level surfaces (capabilities, footer, transport state)
  render, because those are the surfaces PRD 26.1 keeps live;
* **the absent position is stated, not invented** - the clock reports ``None``, never a plausible
  timestamp, and stays JSON-describable so directive item 21 still holds;
* **every transport control is disabled**, derived from ``capabilities().live`` and ``window()`` -
  the flags the contract actually defines;
* **the panels still refuse.** This is the load-bearing assertion. Construction must be bought by
  *deferring* the refusal to the panel that asks, never by swallowing it: a "fix" that made
  ``frame()`` return zeros or an empty snapshot would satisfy "no exception" and violate NFR-6 and
  directive item 20, so this file asserts the refusal is still raised, with its two PRD documents
  intact;
* **the happy path is untouched** - a provider that *can* answer is still read exactly once at
  construction, so the fix did not trade item 21's one-coherent-read-per-frame for laziness.

Deliberately absent: any assertion that ``frame()`` or ``views()`` succeeds against the real-plant
stub. They cannot, and must not. ``get_current_state`` / ``get_equipment_status`` / ``get_kpis`` /
``get_operating_regime`` are *required* contract surfaces with no capability flag between them and
the caller (see :meth:`Clock._read_position`), so making the ten screens render over a source that
supplies none of them would mean inventing both a new capability term and a per-view representation
of total absence. Neither exists, and neither is in this wave's remit.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import STUB_PROVIDER_NAME, STUB_TIMESTAMP

#: The transport flags a source with no clock and no window must report. All four are derived - from
#: ``capabilities().live`` (False) and ``window()`` (``None``) - never from the absent position.
DISABLED_CONTROLS = ("can_play", "can_step_back", "can_scrub", "can_reset")


@pytest.fixture(scope="module")
def dashboard_settings():
    """The loaded ``configs/dashboard.yaml`` constants (NFR-6: none are written here)."""
    from src.digital_twin.settings import DashboardSettings

    return DashboardSettings.from_config()


@pytest.fixture
def real_plant_state(dashboard_settings):
    """``(state, clock, provider)`` wired exactly as ``app.py`` would, over the PRD 26.1 stub.

    The construction *is* the assertion for most of this file: before Wave 3A this fixture raised
    ``NotImplementedError`` from :class:`Clock`'s constructor and no test below could run.
    """
    from src.digital_twin.real_plant import RealPlantDataProvider
    from src.digital_twin.state import DashboardState
    from src.visualization.clock import Clock

    provider = RealPlantDataProvider("plant_export.csv")
    clock = Clock(provider, dashboard_settings)
    return DashboardState(provider, clock, dashboard_settings), clock, provider


# =============================================================================
# Constructibility - the Wave 3A objective
# =============================================================================
def test_the_dashboard_is_constructible_over_a_provider_that_answers_nothing(real_plant_state):
    """FR-14 / PRD 26.1: swapping in a source that can answer nothing changes one class, not a view.

    The three surfaces PRD 26.1 keeps live are the three a shell needs to draw a header for a source
    it cannot read: what the source is called, what it can do, and the standing footer.
    """
    from src.digital_twin import real_plant

    state, _clock, _provider = real_plant_state

    caps = state.capabilities()
    assert caps.name == real_plant.PROVIDER_NAME
    assert caps.synthetic is False
    assert state.footer().capabilities.name == real_plant.PROVIDER_NAME
    assert state.clock_state() is not None


def test_the_clock_states_an_absent_position_rather_than_inventing_one(real_plant_state):
    """Item 20 / NFR-6: a guard states an absence; it never substitutes a plausible value.

    ``None`` is the whole point. A timestamp string here - the epoch, "now", the first row of a
    config - would be a number the source never reported, which is the failure mode the honesty
    rules exist to prevent. ``None`` also keeps the view model JSON-describable (item 21).
    """
    _state, clock, _provider = real_plant_state
    reported = clock.state()

    assert reported.timestamp is None
    assert not isinstance(reported.timestamp, str)

    described = clock.describe()
    assert described["timestamp"] is None
    assert json.loads(json.dumps(described))["timestamp"] is None


def test_every_transport_control_is_disabled_for_a_source_with_no_clock(real_plant_state):
    """Items 7/8: which buttons light up is derived from the contract's own capability surface.

    ``live=False`` means there is nothing to advance and ``window() is None`` means there is nothing
    to scrub, so all four controls are off - and they are off for those reasons, not because the
    position happens to be unknown. Both are asserted here so a later change that starts deriving
    the controls from the *position* fails this test.
    """
    _state, clock, provider = real_plant_state

    assert provider.capabilities().live is False
    assert provider.window() is None

    reported = clock.state().describe()
    for control in DISABLED_CONTROLS:
        assert reported[control] is False, control


def test_the_transport_operations_degrade_instead_of_crashing(real_plant_state):
    """A timer beat, a RESET or a STEP over an unreadable source must not raise.

    ``reset()`` is the interesting one: it catches the provider's ``CapabilityError`` and then
    re-reads the position, which is the *second* unguarded call this wave fixed
    (:meth:`Clock._sync`). Every operation must keep reporting the same honest absence rather than
    acquiring a position it never read.
    """
    _state, clock, _provider = real_plant_state

    for label, operation in (
        ("pause", clock.pause),
        ("play", clock.play),
        ("tick", clock.tick),
        ("step_forward", clock.step_forward),
        ("step_back", clock.step_back),
        ("reset", clock.reset),
        ("seek_fraction", lambda: clock.seek_fraction(0.5)),
    ):
        reported = operation()
        assert reported.timestamp is None, label
        assert reported.playing is False, label
        # A source with no clock never reports progress through a session it cannot run.
        assert reported.fraction == 0.0, label


def test_construction_does_not_buy_itself_by_swallowing_the_panel_refusal(real_plant_state):
    """The anti-regression that matters: the refusal moved, it did not disappear.

    ``real_plant.py`` promises "a clear, actionable refusal from whichever panel it asks first", and
    that promise is what a lazier fix would quietly break. A ``frame()`` that returned an empty
    snapshot, a zero-filled one, or a synthetic fallback would make this file's other tests pass and
    would be a straight NFR-6 / item-20 violation - so the refusal is asserted *positively* here,
    including the two documents PRD 26.1 requires it to carry.
    """
    from src.digital_twin import real_plant

    state, _clock, _provider = real_plant_state

    for label, call in (
        ("frame", state.frame),
        ("views", state.views),
        ("overview", lambda: state.view("A")),
        ("history", lambda: state.history(("burning_zone_temperature",))),
    ):
        if label == "history":
            # ``history`` is flag-gated (``capabilities().history`` is False), so it is the one
            # surface that legitimately degrades to empty instead of refusing.
            assert call() == (), label
            continue
        with pytest.raises(NotImplementedError) as raised:
            call()
        message = str(raised.value)
        assert "TODO: " in message, label
        assert real_plant.REQUIREMENTS_DOC in message, label
        assert real_plant.TRANSFER_SECTION in message, label


# =============================================================================
# The happy path must be byte-for-byte unaffected
# =============================================================================
def test_a_provider_that_can_answer_is_still_read_exactly_once_at_construction(
    stub_provider, dashboard_settings
):
    """Item 21/23: the position is seeded eagerly, so a frame stays one coherent read.

    Guarding the seed must not turn it lazy. Were it deferred to the first :meth:`Clock.state` call,
    ``DashboardState.frame()`` would read the provider twice per frame - once for the snapshot and
    once through the clock - and the two reads would carry different noise realisations, breaking the
    "every screen shows the same instant" guarantee. One call at construction, and one per frame.
    """
    from src.digital_twin.state import DashboardState
    from src.visualization.clock import Clock

    provider = stub_provider()
    clock = Clock(provider, dashboard_settings)
    assert provider.calls["get_current_state"] == 1

    state = DashboardState(provider, clock, dashboard_settings)
    provider.calls.clear()
    state.views()
    assert provider.calls["get_current_state"] == 1


def test_a_provider_that_can_answer_still_reports_its_real_position(
    stub_provider, dashboard_settings
):
    """The guard is a fallback for a refusal, not a new default: a readable source is still read."""
    from src.visualization.clock import Clock

    provider = stub_provider()
    reported = Clock(provider, dashboard_settings).state()

    assert reported.timestamp == STUB_TIMESTAMP
    assert provider.capabilities().name == STUB_PROVIDER_NAME
