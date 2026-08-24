"""Fuel-energy unit consistency (PRD v1.1.1 Section 9.2, FR-24, AC-13, Section 34).

The failure mode these tests exist to prevent is the one v1.1 was written to correct: adding a
mass-based LHV (MJ/kg) and a volume-based LHV (MJ/Nm3) in native units, or re-deriving the
kcal display conversion at a second call site with a slightly different constant.
"""

from __future__ import annotations

import math

import pytest

from src.process_models.fuel import (
    KG_PER_TONNE,
    MJ_PER_KCAL,
    FuelProperties,
    kcal_to_mj,
    mj_to_kcal,
    specific_thermal_energy_kcal_per_kg,
)


def test_fuel_energy_unit_consistency(kiln_config):
    """Fuel flow x LHV is a physically consistent MJ/h figure, per stream and in total."""
    fuel = FuelProperties.from_config(kiln_config)

    # A mass stream: t/h -> kg/h -> MJ/h. Nothing else may enter this product.
    assert fuel.solid_fuel_energy_MJ_per_h(1.0) == pytest.approx(
        KG_PER_TONNE * fuel.lhv_solid_fuel_MJ_per_kg
    )
    # A volume stream: Nm3/h x MJ/Nm3 -> MJ/h, with no mass factor anywhere.
    assert fuel.gas_fuel_energy_MJ_per_h(1000.0) == pytest.approx(
        1000.0 * fuel.lhv_gas_fuel_MJ_per_Nm3
    )

    # The total is the sum of the per-stream MJ/h conversions - never of the raw flows.
    kiln_tph, calciner_tph, gas_flow = 4.8, 7.2, 500.0
    total = fuel.thermal_input_MJ_per_h(kiln_tph, calciner_tph, gas_flow)
    assert total == pytest.approx(
        fuel.solid_fuel_energy_MJ_per_h(kiln_tph)
        + fuel.solid_fuel_energy_MJ_per_h(calciner_tph)
        + fuel.gas_fuel_energy_MJ_per_h(gas_flow)
    )
    # A mass flow and a volume flow of equal magnitude must NOT contribute equally: if the two
    # LHVs were ever summed in native units this equality would hold and the test would fail.
    assert fuel.solid_fuel_energy_MJ_per_h(1.0) != pytest.approx(fuel.gas_fuel_energy_MJ_per_h(1.0))


def test_solid_fuel_rate_inverts_its_own_energy_conversion(kiln_config):
    """``kiln_reference`` solves the reference point through this inverse (PRD 9.3)."""
    fuel = FuelProperties.from_config(kiln_config)
    for rate_tph in (0.0, 1.0, 4.8, 12.0):
        energy = fuel.solid_fuel_energy_MJ_per_h(rate_tph)
        assert fuel.solid_fuel_rate_tph(energy) == pytest.approx(rate_tph, abs=1e-12)


def test_fuel_split_conserves_total_mass(kiln_config):
    """``split_fuel_rates_tph`` is a split, not a scaling (PRD 9.2 burner share)."""
    fuel = FuelProperties.from_config(kiln_config)
    kiln_rate, calciner_rate = fuel.split_fuel_rates_tph(12.0)
    assert kiln_rate + calciner_rate == pytest.approx(12.0)
    assert kiln_rate == pytest.approx(12.0 * fuel.kiln_burner_fuel_share)


def test_kcal_conversion_is_the_single_documented_constant():
    """``1 kcal = 4.184e-3 MJ`` (PRD 9.2); ``mj_to_kcal`` is the only sanctioned path."""
    assert MJ_PER_KCAL == 4.184e-3
    assert mj_to_kcal(MJ_PER_KCAL) == pytest.approx(1.0)
    for value_MJ in (0.0, 1.0, 1234.5):
        assert kcal_to_mj(mj_to_kcal(value_MJ)) == pytest.approx(value_MJ, rel=1e-12)


def test_specific_thermal_energy_matches_manual_conversion():
    """The display tag equals MJ/h -> kcal/h divided by clinker kg/h, and nothing else."""
    thermal_MJ_per_h, clinker_tph = 400_000.0, 119.7
    expected = mj_to_kcal(thermal_MJ_per_h) / (clinker_tph * KG_PER_TONNE)
    assert specific_thermal_energy_kcal_per_kg(thermal_MJ_per_h, clinker_tph) == pytest.approx(
        expected
    )
    # Plausibility: a modern precalciner kiln runs 700-800 kcal/kg clinker (PRD 12.1 band).
    assert 600.0 < expected < 1000.0


def test_specific_thermal_energy_is_finite_at_zero_production():
    """Start-up must not put an ``inf`` into the dataset (PRD 9.2 / 11.4 startup ramp)."""
    value = specific_thermal_energy_kcal_per_kg(400_000.0, 0.0)
    assert value == 0.0 and math.isfinite(value)


def test_twin_specific_thermal_energy_tag_uses_the_same_conversion(kiln):
    """The kiln twin's published tag must reproduce the sanctioned conversion exactly (AC-13)."""
    fuel = FuelProperties.from_config()
    outputs = kiln.outputs
    thermal_MJ_per_h = fuel.thermal_input_MJ_per_h(
        outputs["kiln_fuel_rate_tph"], outputs["calciner_fuel_rate_tph"]
    )
    expected = specific_thermal_energy_kcal_per_kg(
        thermal_MJ_per_h, outputs["clinker_production_tph"]
    )
    assert outputs["thermal_energy_kcal_per_kg_clinker"] == pytest.approx(expected, rel=1e-9)
