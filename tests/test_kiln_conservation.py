"""Kiln conservation closures (PRD v1.1.1 Section 9.3; NFR-10, AC-14, Section 34).

``test_kiln_energy_balance`` and ``test_kiln_mass_balance`` are the two tests Section 34 names.
The rest of this module pins down *why* they pass, so a future change that closes the balance
by weakening it (dropping a term, widening the tolerance, clamping a temperature) fails here:

* at the reference point both residuals are exactly zero,
* the transient energy residual is dominated by ``energy_closure_to_preheater_temperature``,
* the mass closure holds to machine precision even while the inventory is moving.
"""

from __future__ import annotations

import pytest

from src.process_models import balances
from src.process_models.fuel import FuelProperties

from tests.conftest import HORIZON_MINUTES, STEP_SECONDS


def _worst(series) -> float:
    return float(series.abs().max())


def test_reference_point_closes_exactly(kiln):
    """PRD 9.3: the closure holds at the reference operating point, before any dynamics."""
    residuals = kiln.balance_residuals
    assert residuals["energy_pct"] == pytest.approx(0.0, abs=1e-9)
    assert residuals["mass_pct"] == pytest.approx(0.0, abs=1e-9)
    assert residuals["unaccounted_loss_MJ_per_h"] == pytest.approx(0.0, abs=1e-6)


def test_kiln_energy_balance(kiln, step_trajectory, kiln_energy_tolerance_pct):
    """Energy residual stays inside ``unaccounted_loss_max_fraction`` over the horizon (NFR-10)."""
    ref = kiln.reference
    base = {
        "kiln_feed_rate_tph": ref.feed_rate_tph,
        "kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph,
        "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
        "kiln_speed_rpm": ref.kiln_speed_rpm,
        "ID_fan_speed_pct": ref.ID_fan_speed_pct,
    }
    frame = kiln.simulate_scenario(
        step_trajectory(
            base,
            {"kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph * 1.05},
            hold_minutes=30,
            step_minutes=HORIZON_MINUTES,
        ),
        STEP_SECONDS,
    )
    residual = frame["energy_balance_residual_pct"]
    assert _worst(residual) < kiln_energy_tolerance_pct
    # The settled tail must be far tighter than the bound: a persistent offset would mean the
    # balance is being *reported*, not enforced.
    assert _worst(residual.tail(30)) < 1e-3
    # ... and the step really was felt, so the tight tail is not just an unexcited model.
    assert frame["burning_zone_temperature"].iloc[-1] > frame["burning_zone_temperature"].iloc[0]


def test_kiln_mass_balance(kiln, step_trajectory, kiln_mass_tolerance_pct):
    """``Feed = Clinker + LOI + Dust + d(Inventory)/dt`` holds to machine precision (PRD 9.3)."""
    ref = kiln.reference
    base = {
        "kiln_feed_rate_tph": ref.feed_rate_tph,
        "kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph,
        "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
    }
    frame = kiln.simulate_scenario(
        step_trajectory(
            base,
            {"kiln_feed_rate_tph": ref.feed_rate_tph * 1.08},
            hold_minutes=30,
            step_minutes=HORIZON_MINUTES,
        ),
        STEP_SECONDS,
    )
    assert _worst(frame["mass_balance_residual_pct"]) < kiln_mass_tolerance_pct
    # The discretization of PRD 9.3 is exact, not merely within tolerance (see kiln_core).
    assert _worst(frame["mass_balance_residual_pct"]) < 1e-9
    # Conservation must actually be doing work: production follows the feed step, delayed.
    assert frame["clinker_production_tph"].iloc[29] == pytest.approx(
        ref.clinker_production_tph, rel=1e-6
    )
    assert frame["clinker_production_tph"].iloc[-1] > frame["clinker_production_tph"].iloc[29]


def test_mass_balance_terms_sum_to_the_feed(kiln):
    """The residual is not the only witness: the four terms themselves must add up."""
    kiln.simulation_step({"kiln_feed_rate_tph": kiln.reference.feed_rate_tph * 1.1}, STEP_SECONDS)
    mass = kiln.rotary_kiln.mass_balance
    assert isinstance(mass, balances.KilnMassBalance)
    assert mass.feed_rate_tph == pytest.approx(mass.accounted_output_tph, abs=1e-9)


def test_energy_balance_terms_sum_to_the_input(kiln):
    """Same for the energy side: LHS = accounted outputs + the reported unaccounted loss."""
    kiln.simulation_step({}, STEP_SECONDS)
    energy = kiln.rotary_kiln.energy_balance
    assert isinstance(energy, balances.KilnEnergyBalance)
    assert energy.input_MJ_per_h == pytest.approx(
        energy.accounted_output_MJ_per_h + energy.unaccounted_loss_MJ_per_h, rel=1e-12
    )


def test_fuel_energy_input_matches_the_published_fuel_rates(kiln):
    """The energy balance must be fed by the same MJ conversion as the tags (PRD 9.2)."""
    fuel = FuelProperties.from_config()
    kiln.simulation_step({}, STEP_SECONDS)
    expected = fuel.thermal_input_MJ_per_h(
        kiln.outputs["kiln_fuel_rate_tph"], kiln.outputs["calciner_fuel_rate_tph"]
    )
    assert kiln.rotary_kiln.energy_balance.fuel_energy_input_MJ_per_h == pytest.approx(
        expected, rel=1e-9
    )


def test_transient_energy_residual_is_dominated_by_the_closure_delay(kiln, kiln_config):
    """The delay that carries the closure dominates the transient residual (PRD 9.3).

    Reconfiguring that one relationship to respond instantly (no dead time, no lag) must collapse
    the transient: what survives is the one-step-old gas state implied by the PRD 8.3 execution
    order (the preheater runs after the kiln), which is visible only on the step a setpoint moves
    on and is identical with or without the delay.

    The reconfiguration goes through a config copy, so the test exercises the same construction
    path the twin normally uses rather than reaching into its internals.
    """
    ref = kiln.reference
    step = {"kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph * 1.10}
    with_delay = []
    for _ in range(40):
        kiln.simulation_step(step, STEP_SECONDS)
        with_delay.append(abs(kiln.balance_residuals["energy_pct"]))
    assert max(with_delay) > 1e-3  # the delay is visibly doing something

    from src.process_models.kiln import KilnTwin

    instant_config = kiln_config.to_dict()
    instant_config["delays"]["energy_closure_to_preheater_temperature"] = {
        "dead_time_min": 0.0,
        "tau_min": None,
    }
    instant = KilnTwin(instant_config)
    without_delay = []
    for _ in range(40):
        instant.simulation_step(step, STEP_SECONDS)
        without_delay.append(abs(instant.balance_residuals["energy_pct"]))

    # The step the fuel lands on is the execution-order artifact and nothing else: both twins
    # start settled, so the closure delay cannot yet have contributed anything to it.
    assert without_delay[0] == pytest.approx(with_delay[0], rel=1e-9)
    # The next step is gas-consistent again, and there the closure itself is exact.
    assert without_delay[1] < 1e-6
    # From then on the delay is the whole of the transient: an order of magnitude in the peak,
    # and close to two in the residual accumulated over the horizon.
    assert max(without_delay[1:]) < 0.05
    assert max(with_delay[1:]) > 1.0
    assert max(with_delay[1:]) > 20.0 * max(without_delay[1:])
    assert sum(with_delay[1:]) > 20.0 * sum(without_delay[1:])
