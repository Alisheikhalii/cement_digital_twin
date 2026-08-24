"""Mill mass closure (PRD v1.1.1 Section 10.2; NFR-10, AC-14, Section 34).

``test_mill_mass_balance`` is the test Section 34 names. The others pin down the two structural
decisions PRD 10.2 makes explicitly: reject recirculation is *internal to the closed circuit*
and must never appear as a closure term, and the lag of ``feed_to_production`` comes from the
physical mill holdup rather than from an invented time constant.
"""

from __future__ import annotations

import pytest

from src.process_models import balances

from tests.conftest import HORIZON_MINUTES, STEP_SECONDS


def _worst(series) -> float:
    return float(series.abs().max())


def _base_inputs(mill) -> dict[str, float]:
    ref = mill.reference
    return {
        "mill_feed_rate_tph": ref.feed_rate_tph,
        "separator_speed_rpm": ref.separator_speed_rpm,
        "fan_speed_pct": ref.fan_speed_pct,
        "mill_speed_rpm": ref.mill_speed_rpm,
    }


def test_reference_point_closes_exactly(mill):
    """PRD 10.2: the closure holds at the reference operating point, before any dynamics."""
    assert mill.balance_residuals["mass_pct"] == pytest.approx(0.0, abs=1e-9)
    assert mill.balance_residuals["mass_residual_tph"] == pytest.approx(0.0, abs=1e-9)


def test_mill_mass_balance(mill, mill_config, step_trajectory, mill_mass_tolerance_pct):
    """``Mill_Feed = Cement + Dust + d(Inventory)/dt`` across a feed step (NFR-10)."""
    ref = mill.reference
    frame = mill.simulate_scenario(
        step_trajectory(
            _base_inputs(mill),
            {"mill_feed_rate_tph": ref.feed_rate_tph * 1.12},
            hold_minutes=30,
            step_minutes=HORIZON_MINUTES,
        ),
        STEP_SECONDS,
    )
    residual = frame["mass_balance_residual_pct"]
    assert _worst(residual) < mill_mass_tolerance_pct
    # The discretization of PRD 10.2 is exact, not merely inside the tolerance.
    assert _worst(residual) < 1e-9
    # Settled production is the feed minus the bag-filter dust, exactly (no inventory drift).
    dust_fraction = float(mill_config.get_path("mass_balance.dust_bag_filter_loss_fraction"))
    assert frame["cement_production_tph"].iloc[-1] == pytest.approx(
        ref.feed_rate_tph * 1.12 * (1.0 - dust_fraction), rel=1e-6
    )


def test_mass_balance_holds_through_a_separator_step(
    mill, mill_config, step_trajectory, mill_mass_tolerance_pct
):
    """A separator step moves the circulating load, hence the inventory time constant (PRD 10.2)."""
    ref = mill.reference
    frame = mill.simulate_scenario(
        step_trajectory(
            _base_inputs(mill),
            {"separator_speed_rpm": ref.separator_speed_rpm * 1.15},
            hold_minutes=30,
            step_minutes=HORIZON_MINUTES,
        ),
        STEP_SECONDS,
    )
    assert _worst(frame["mass_balance_residual_pct"]) < mill_mass_tolerance_pct
    assert _worst(frame["mass_balance_residual_pct"]) < 1e-9
    # The circulating load really did move - otherwise the varying-tau path is untested.
    assert mill.separator.state["circulating_load_ratio"] > ref.circulating_load_ratio
    # ... and conservation still returns production to feed minus dust.
    dust_fraction = float(mill_config.get_path("mass_balance.dust_bag_filter_loss_fraction"))
    assert frame["cement_production_tph"].iloc[-1] == pytest.approx(
        ref.feed_rate_tph * (1.0 - dust_fraction), rel=1e-6
    )


def test_reject_recirculation_is_not_a_closure_term(mill):
    """PRD 10.2 verbatim: the reject stream is "not a true loss"."""
    mill.simulation_step(
        {"separator_speed_rpm": mill.reference.separator_speed_rpm * 1.2}, STEP_SECONDS
    )
    mass = mill.mill.mass_balance
    assert isinstance(mass, balances.MillMassBalance)
    assert mass.reject_recirculation_tph > 0.0  # it is reported ...
    assert mass.accounted_output_tph == pytest.approx(  # ... but stays out of the closure
        mass.cement_production_tph + mass.dust_loss_tph + mass.inventory_change_tph, abs=1e-12
    )
    assert mass.feed_rate_tph == pytest.approx(mass.accounted_output_tph, abs=1e-9)


def test_dust_loss_is_taken_on_the_arrival_rate(mill, mill_config):
    """Dust is drawn from material that has actually arrived, not from the setpoint (PRD 10.2)."""
    dust_fraction = float(mill_config.get_path("mass_balance.dust_bag_filter_loss_fraction"))
    ref = mill.reference
    # One step after a feed step, the new feed is still inside the transport dead time, so the
    # dust loss must still reflect the OLD rate.
    mill.simulation_step({"mill_feed_rate_tph": ref.feed_rate_tph * 2.0}, STEP_SECONDS)
    assert mill.mill.state["dust_loss_tph"] == pytest.approx(
        ref.feed_rate_tph * dust_fraction, rel=1e-9
    )


def test_inventory_stays_bounded_over_a_long_run(mill):
    """PRD 20.6 stability: a long run must not accumulate or drain the holdup without bound."""
    ref = mill.reference
    for minute in range(6 * 60):
        feed = ref.feed_rate_tph * (1.15 if (minute // 60) % 2 else 0.85)
        mill.simulation_step({"mill_feed_rate_tph": feed}, STEP_SECONDS)
        inventory = mill.mill.state["mill_inventory_t"]
        assert 0.0 < inventory < 5.0 * ref.mill_inventory_t
    assert abs(mill.balance_residuals["mass_pct"]) < 1e-9


def test_residuals_report_mass_only(mill):
    """PRD 10.2 defines a mass closure only; a fabricated ``energy_pct`` would be a false claim."""
    assert set(mill.balance_residuals) == {"mass_pct", "mass_residual_tph"}
