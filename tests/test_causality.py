"""Directional / causality tests (PRD v1.1.1 Sections 20.1, 20.4, 20.8; Section 34).

PRD 20.1 is explicit that these are *directional within a regime*, not global monotonicity:
the reduced-order model contains deliberate nonlinearities (the CO/O2 relationship of 9.4, the
mill quality/throughput trade-off of 10.4), so each test states the regime it perturbs around
and asserts the sign of the response - plus, per PRD 20.4, that the response appears only
**after** the configured dead time.
"""

from __future__ import annotations

import pytest

from tests.conftest import STEP_SECONDS


def _hold(twin, inputs: dict[str, float], minutes: int) -> None:
    for _ in range(int(minutes)):
        twin.simulation_step(inputs, STEP_SECONDS)


def _settled(twin, inputs: dict[str, float], minutes: int = 180) -> dict[str, float]:
    _hold(twin, inputs, minutes)
    return dict(twin.outputs)


# -- kiln ----------------------------------------------------------------------------------
def test_more_fuel_raises_burning_zone_temperature_after_its_dead_time(kiln):
    """PRD 20.8 / 9.4: fuel -> BZT, dead time 2 min, tau 25 min."""
    before = dict(kiln.outputs)
    step = {"kiln_fuel_rate_tph": kiln.reference.kiln_fuel_rate_tph * 1.05}

    kiln.simulation_step(step, STEP_SECONDS)  # minute 1: inside the 2-minute dead time
    assert kiln.outputs["burning_zone_temperature"] == pytest.approx(
        before["burning_zone_temperature"], abs=1e-12
    )
    kiln.simulation_step(step, STEP_SECONDS)  # minute 2: released, lag has not acted yet
    assert kiln.outputs["burning_zone_temperature"] == pytest.approx(
        before["burning_zone_temperature"], abs=1e-12
    )
    kiln.simulation_step(step, STEP_SECONDS)  # minute 3: the response is now visible
    assert kiln.outputs["burning_zone_temperature"] > before["burning_zone_temperature"]

    after = _settled(kiln, step)
    assert after["burning_zone_temperature"] > before["burning_zone_temperature"]
    # More fuel at constant feed also means more thermal input per tonne of clinker.
    assert after["specific_fuel_consumption"] > before["specific_fuel_consumption"]
    assert after["thermal_energy_kcal_per_kg_clinker"] > before["thermal_energy_kcal_per_kg_clinker"]


def test_more_fuel_consumes_oxygen_and_raises_CO2(kiln):
    """PRD 9.4: at constant fan speed, extra fuel burns into the available excess air."""
    before = dict(kiln.outputs)
    after = _settled(kiln, {"kiln_fuel_rate_tph": kiln.reference.kiln_fuel_rate_tph * 1.10})
    assert after["oxygen_percent"] < before["oxygen_percent"]
    assert after["CO2_percent"] > before["CO2_percent"]
    # Thermal NOx rises with the burning-zone temperature (PRD 9.4).
    assert after["NOx_ppm"] > before["NOx_ppm"]


def test_more_id_fan_speed_raises_oxygen_and_draught(kiln):
    """PRD 20.8: ID fan -> O2 up, tower pressure more negative, exhaust flow up."""
    before = dict(kiln.outputs)
    after = _settled(kiln, {"ID_fan_speed_pct": kiln.reference.ID_fan_speed_pct + 5.0})
    assert after["oxygen_percent"] > before["oxygen_percent"]
    assert after["exhaust_gas_flow"] > before["exhaust_gas_flow"]
    assert after["preheater_pressure"] < before["preheater_pressure"]  # stronger suction
    assert after["ID_fan_power"] > before["ID_fan_power"]


def test_low_oxygen_raises_CO(kiln):
    """PRD 9.4: the CO/O2 relationship is nonlinear but directionally clear within a regime."""
    before = dict(kiln.outputs)
    after = _settled(kiln, {"ID_fan_speed_pct": kiln.reference.ID_fan_speed_pct - 6.0})
    assert after["oxygen_percent"] < before["oxygen_percent"]
    assert after["CO_ppm"] > before["CO_ppm"]


def test_more_feed_raises_production_and_cools_the_burning_zone(kiln):
    """PRD 20.8: feed -> production up; at constant fuel the same heat is spread thinner."""
    before = dict(kiln.outputs)
    after = _settled(kiln, {"kiln_feed_rate_tph": kiln.reference.feed_rate_tph * 1.08})
    assert after["clinker_production_tph"] > before["clinker_production_tph"]
    assert after["burning_zone_temperature"] < before["burning_zone_temperature"]
    # Thermal demand per tonne of clinker falls because fuel was held fixed - the twin is not
    # claiming a free efficiency gain, it is claiming an under-fired kiln (PRD 20.1 regime note).
    assert after["thermal_energy_kcal_per_kg_clinker"] < before["thermal_energy_kcal_per_kg_clinker"]


def test_production_step_appears_only_after_the_feed_dead_time(kiln):
    """PRD 9.4 ``feed_to_production``: 5 min dead time, then the inventory buffer (PRD 9.3)."""
    before = kiln.outputs["clinker_production_tph"]
    step = {"kiln_feed_rate_tph": kiln.reference.feed_rate_tph * 1.20}
    for _ in range(5):
        kiln.simulation_step(step, STEP_SECONDS)
        assert kiln.outputs["clinker_production_tph"] == pytest.approx(before, abs=1e-12)
    kiln.simulation_step(step, STEP_SECONDS)
    assert kiln.outputs["clinker_production_tph"] > before


def test_health_loss_raises_vibration_and_bearing_temperature(kiln):
    """PRD 9.5: health is an input to the equipment signals, not a hidden fudge factor."""
    before = dict(kiln.outputs)
    kiln.set_health({"kiln": 0.6})
    after = _settled(kiln, {})
    assert after["vibration"] > before["vibration"]
    assert after["bearing_temperature"] > before["bearing_temperature"]


# -- mill ----------------------------------------------------------------------------------
def test_faster_separator_raises_blaine_and_specific_power(mill):
    """PRD 10.4 trade-off: finer cement costs electricity and circulating load."""
    before = dict(mill.outputs)
    after = _settled(mill, {"separator_speed_rpm": mill.reference.separator_speed_rpm * 1.15})
    assert after["simulated_blaine_cm2_g"] > before["simulated_blaine_cm2_g"]
    assert after["residue_percent"] < before["residue_percent"]  # finer => less residue
    assert after["specific_power_consumption_kwh_t"] > before["specific_power_consumption_kwh_t"]
    assert after["mill_differential_pressure"] > before["mill_differential_pressure"]
    assert mill.separator.state["circulating_load_ratio"] > mill.reference.circulating_load_ratio


def test_blaine_step_appears_only_after_the_separator_dead_time(mill):
    """PRD 10.3 ``separator_to_blaine``: 3 min dead time, 12 min lag."""
    before = mill.outputs["simulated_blaine_cm2_g"]
    step = {"separator_speed_rpm": mill.reference.separator_speed_rpm * 1.15}
    for _ in range(3):
        mill.simulation_step(step, STEP_SECONDS)
        assert mill.outputs["simulated_blaine_cm2_g"] == pytest.approx(before, abs=1e-12)
    mill.simulation_step(step, STEP_SECONDS)
    assert mill.outputs["simulated_blaine_cm2_g"] > before


def test_more_mill_feed_coarsens_the_product_and_dilutes_fixed_power(mill):
    """The other half of the PRD 10.4 trade-off: throughput up, fineness and kWh/t down."""
    before = dict(mill.outputs)
    after = _settled(mill, {"mill_feed_rate_tph": mill.reference.feed_rate_tph * 1.12})
    assert after["cement_production_tph"] > before["cement_production_tph"]
    assert after["simulated_blaine_cm2_g"] < before["simulated_blaine_cm2_g"]
    assert after["residue_percent"] > before["residue_percent"]
    assert after["mill_motor_power_kw"] > before["mill_motor_power_kw"]  # absolute power rises
    assert (  # ... but the fixed fan/separator draw is amortized over more tonnes
        after["specific_power_consumption_kwh_t"] < before["specific_power_consumption_kwh_t"]
    )


def test_more_fan_speed_moves_gas_flow_power_and_pressure_by_their_own_laws(mill):
    """PRD 10.3 fan curve: flow ~ linear, power ~ cube, pressure ~ square (ASSUMPTION exponents)."""
    before = dict(mill.outputs)
    ratio = 1.125
    after = _settled(mill, {"fan_speed_pct": mill.reference.fan_speed_pct * ratio})
    assert after["gas_flow"] / before["gas_flow"] == pytest.approx(ratio, rel=1e-6)
    assert after["fan_power_kw"] > before["fan_power_kw"] * ratio  # steeper than linear
    assert after["mill_pressure"] < before["mill_pressure"]  # gauge pressure, more negative
    assert abs(after["mill_pressure"]) > abs(before["mill_pressure"]) * ratio
    # More sweep air carries heat away, so the mill outlet runs cooler.
    assert after["mill_outlet_temperature"] < before["mill_outlet_temperature"]


def test_mill_health_loss_raises_vibration(mill):
    before = dict(mill.outputs)
    mill.set_health({"mill": 0.5})
    after = _settled(mill, {})
    assert after["mill_vibration"] > before["mill_vibration"]


# -- steady state --------------------------------------------------------------------------
@pytest.mark.parametrize("line", ["kiln", "mill"])
def test_to_steady_state_reaches_the_same_point_as_a_long_hold(line):
    """PRD 8.4: the optimizer's candidate evaluation must agree with a plain long rollout."""
    from src.process_models.kiln import KilnTwin
    from src.process_models.mill import CementMillTwin

    factory = KilnTwin if line == "kiln" else CementMillTwin
    settling, rolling = factory(), factory()  # two twins: the fixtures are per-test singletons
    if line == "kiln":
        step = {"kiln_fuel_rate_tph": settling.reference.kiln_fuel_rate_tph * 1.04}
    else:
        step = {"separator_speed_rpm": settling.reference.separator_speed_rpm * 1.08}

    settled = settling.to_steady_state(step, max_minutes=600)
    _hold(rolling, step, 600)
    for key, value in settled.items():
        scale = max(1.0, abs(value))
        assert abs(rolling.outputs[key] - value) / scale < 1e-4
