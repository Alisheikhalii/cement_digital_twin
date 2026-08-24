"""The per-relationship delay framework (PRD v1.1.1 Sections 9.4, 10.3; AC-15, Section 34).

Section 34 asks these tests to prove three separate things:

1. distinct relationships respond with **their own** configured dead time and lag,
2. no shared universal time constant stands in for them, and
3. a step change is **not** reflected in a delayed output before its dead time elapses.
"""

from __future__ import annotations

import math

import pytest

from src.simulation.delays import (
    NO_LAG,
    SECONDS_PER_MINUTE,
    DelayBank,
    DelayedResponse,
    build_delay_bank,
)

STEP = 60.0  # 1 minute, the PRD 11.2 sampling interval


def test_step_is_not_seen_before_the_dead_time_elapses():
    """A 2-minute dead time means exactly that: minute 1 shows nothing (PRD 9.4)."""
    response = DelayedResponse.from_minutes(2.0, 25.0, initial=0.0, name="fuel_to_bzt")
    assert response.step(1.0, STEP) == 0.0  # t = 1 min, still in transit
    assert response.step(1.0, STEP) == 0.0  # t = 2 min, released this step, lag starts next
    third = response.step(1.0, STEP)  # t = 3 min
    assert third > 0.0


def test_lag_follows_the_analytic_zero_order_hold_solution():
    """After release, ``y`` approaches the target as ``1 - exp(-t/tau)`` (PRD 9.4)."""
    tau_min = 10.0
    response = DelayedResponse.from_minutes(0.0, tau_min, initial=0.0, name="lag_only")
    for minute in range(1, 31):
        value = response.step(1.0, STEP)
        expected = 1.0 - math.exp(-minute / tau_min)
        assert value == pytest.approx(expected, abs=1e-12)


def test_lag_result_is_independent_of_the_caller_step_size():
    """Exact ZOH discretization: 1 x 60 s must equal 6 x 10 s (NFR-4 reproducibility).

    Asserted on the lag itself. The transport queue releases on the caller's own step grid, so
    a coarse caller can only ever resolve a dead time to within one of its steps - which is why
    the two parts of the relationship are tested separately.
    """
    coarse = DelayedResponse.from_minutes(0.0, 8.0, name="coarse")
    fine = DelayedResponse.from_minutes(0.0, 8.0, name="fine")
    for _ in range(20):
        coarse.step(5.0, STEP)
        for _ in range(6):
            fine.step(5.0, STEP / 6.0)
    assert fine.value == pytest.approx(coarse.value, rel=1e-12)


def test_dead_time_is_honoured_on_a_fine_step_grid():
    """A 1-minute dead time on a 10 s caller step: nothing arrives for a full minute.

    The target offered during a step is released one dead time *after* that step, so with six
    10 s steps per minute the value moves on the seventh step - exactly 60 s of transport.
    """
    response = DelayedResponse.from_minutes(1.0, None, name="fine_transport")
    for _ in range(6):
        assert response.step(7.0, 10.0) == 0.0
    assert response.step(7.0, 10.0) == pytest.approx(7.0)


def test_null_tau_is_a_pure_transport_queue():
    """``tau_min: null`` rows get their lag from a physical inventory instead (PRD 9.3/10.2)."""
    response = DelayedResponse.from_spec({"dead_time_min": 5.0, "tau_min": None}, name="feed")
    assert response.tau_s == NO_LAG
    for _ in range(5):
        assert response.step(100.0, STEP) == 0.0  # nothing arrives inside the dead time
    assert response.step(100.0, STEP) == 100.0  # then the target arrives undamped


def test_settle_starts_the_relationship_at_steady_state():
    """This is what lets the twins start exactly on the reference point (PRD 9.3)."""
    response = DelayedResponse.from_minutes(3.0, 15.0, name="settled")
    response.settle(42.0)
    assert response.value == 42.0
    assert response.in_transit == 0
    assert response.step(42.0, STEP) == pytest.approx(42.0)


def test_dt_must_be_positive():
    response = DelayedResponse.from_minutes(1.0, 1.0, name="guard")
    with pytest.raises(ValueError):
        response.step(1.0, 0.0)


def test_negative_time_constants_are_rejected():
    with pytest.raises(ValueError):
        DelayedResponse(-1.0, 5.0, name="bad_dead_time")
    with pytest.raises(ValueError):
        DelayedResponse(1.0, -5.0, name="bad_tau")


# -- the configured banks ------------------------------------------------------------------
def test_kiln_relationships_are_not_one_universal_time_constant(kiln_config):
    """AC-15: each PRD 9.4 row is its own instance with its own numbers."""
    bank = build_delay_bank(kiln_config)
    assert len(bank) >= 20  # PRD 9.4 table plus the documented ASSUMPTION rows
    pairs = {(delay.dead_time_s, delay.tau_s) for delay in bank.values()}
    assert len(pairs) > 1, "a single shared (dead_time, tau) pair would violate AC-15"
    # The two rows PRD 9.4 names explicitly must keep their own configured values.
    assert bank.dead_time_s("fuel_to_burning_zone_temperature") == 2.0 * SECONDS_PER_MINUTE
    assert bank.tau_s("fuel_to_burning_zone_temperature") == 25.0 * SECONDS_PER_MINUTE
    assert bank.dead_time_s("fuel_to_oxygen") == 0.5 * SECONDS_PER_MINUTE
    assert bank.tau_s("fuel_to_oxygen") == 4.0 * SECONDS_PER_MINUTE
    assert bank.tau_s("feed_to_production") == NO_LAG  # inventory-buffered, PRD 9.3


def test_mill_relationships_are_not_one_universal_time_constant(mill_config):
    bank = build_delay_bank(mill_config)
    assert len(bank) >= 10
    assert len({(delay.dead_time_s, delay.tau_s) for delay in bank.values()}) > 1
    assert bank.dead_time_s("separator_to_blaine") == 3.0 * SECONDS_PER_MINUTE
    assert bank.tau_s("separator_to_blaine") == 12.0 * SECONDS_PER_MINUTE
    assert bank.tau_s("feed_to_production") == NO_LAG  # holdup-buffered, PRD 10.2


def test_two_relationships_of_one_bank_respond_at_different_times(kiln_config):
    """Same step, two rows: the faster one has moved while the slower one has not (PRD 9.4)."""
    bank = build_delay_bank(kiln_config)
    fast, slow = bank["fuel_to_oxygen"], bank["feed_to_burning_zone_temperature"]
    fast.settle(0.0)
    slow.settle(0.0)
    for _ in range(2):  # 2 minutes: past the 0.5 min dead time, inside the 8 min one
        fast.step(1.0, STEP)
        slow.step(1.0, STEP)
    assert fast.value > 0.0
    assert slow.value == 0.0


def test_unknown_relationship_fails_loudly(kiln_config):
    """A typo must not silently become an instantaneous response (AC-15)."""
    bank = build_delay_bank(kiln_config)
    with pytest.raises(KeyError) as excinfo:
        bank["fuel_to_nothing"]
    assert "available relationships" in str(excinfo.value)


def test_each_unit_owns_its_own_instances(kiln, mill):
    """``load_to_electrical`` exists in several units - as several distinct objects (AC-15)."""
    kiln_banks = [unit._delays for unit in kiln.units if hasattr(unit, "_delays")]
    mill_banks = [unit._delays for unit in mill.units if hasattr(unit, "_delays")]
    assert len(kiln_banks) >= 4 and len(mill_banks) >= 3

    sharing = [bank for bank in kiln_banks + mill_banks if "load_to_electrical" in bank]
    assert len(sharing) >= 3, "expected several units to own a load_to_electrical relationship"
    instances = [id(bank["load_to_electrical"]) for bank in sharing]
    assert len(set(instances)) == len(instances), "units must not share one DelayedResponse"


def test_bank_is_a_read_only_mapping(mill_config):
    bank = build_delay_bank(mill_config)
    assert isinstance(bank, DelayBank)
    assert not hasattr(bank, "__setitem__")
    assert set(bank) == set(mill_config["delays"])
