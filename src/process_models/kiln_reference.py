"""Energy-balance-derived kiln reference point (PRD v1.1.1 Sections 9.2, 9.3).

PRD 9.3 requires that "the model's reduced-order gains are parameterized so the closure holds
at the nominal/reference operating point by construction". This module is what makes that true
rather than aspirational: the reference **fuel rates are not configured at all**, they are
solved from the energy balance for the configured reference feed, temperatures and air system.
Editing any constant in ``configs/kiln_dynamics.yaml`` therefore moves the reference fuel rate
instead of silently opening an energy gap.

The same pure functions in :mod:`src.process_models.balances` are used here and inside
``RotaryKilnModel``, so the dynamic model reproduces this point exactly (verified by
``test_reference_point_is_steady`` and ``test_kiln_energy_balance``, Section 34).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from src.process_models import balances, electrical
from src.process_models.fuel import FuelProperties, specific_thermal_energy_kcal_per_kg

#: Convergence bound of the reference-point solve (relative), and its iteration cap.
_SOLVE_TOLERANCE = 1e-10
_SOLVE_MAX_ITERATIONS = 200

#: Initial guess for the specific thermal energy, MJ/kg clinker (only a starting point for the
#: fixed-point iteration below - the solved value is what the model uses).
_INITIAL_GUESS_MJ_PER_KG_CLINKER = 3.4


@dataclass(frozen=True, slots=True)
class KilnReferencePoint:
    """The nominal operating point every kiln gain is expressed as a deviation from."""

    # -- material side ------------------------------------------------------------------
    feed_rate_tph: float
    clinker_production_tph: float
    LOI_loss_tph: float
    dust_loss_tph: float
    kiln_inventory_t: float
    residence_time_h: float
    # -- fuel side ----------------------------------------------------------------------
    thermal_input_MJ_per_h: float
    total_fuel_rate_tph: float
    kiln_fuel_rate_tph: float
    calciner_fuel_rate_tph: float
    thermal_energy_kcal_per_kg_clinker: float
    # -- temperatures -------------------------------------------------------------------
    ambient_temperature_C: float
    raw_meal_temperature_C: float
    raw_meal_moisture_pct: float
    burning_zone_temperature_C: float
    clinker_exit_temperature_C: float
    calciner_temperature_C: float
    kiln_inlet_temperature_C: float
    preheater_outlet_temperature_C: float
    secondary_air_temperature_C: float
    cooler_outlet_temperature_C: float
    # -- machine setpoints --------------------------------------------------------------
    kiln_speed_rpm: float
    ID_fan_speed_pct: float
    # -- gas side -----------------------------------------------------------------------
    excess_air_ratio: float
    stoichiometric_air_Nm3_per_h: float
    combustion_air_Nm3_per_h: float
    primary_air_flow_Nm3_per_h: float
    secondary_air_flow_Nm3_per_h: float
    tertiary_air_flow_Nm3_per_h: float
    calcination_CO2_Nm3_per_h: float
    calcination_H2O_Nm3_per_h: float
    combustion_CO2_Nm3_per_h: float
    back_end_gas_Nm3_per_h: float
    dry_back_end_gas_Nm3_per_h: float
    exhaust_gas_flow_Nm3_per_h: float
    oxygen_percent: float
    CO2_percent: float
    # -- equipment (PRD 9.5) ------------------------------------------------------------
    exhaust_gas_actual_m3_per_h: float
    ID_fan_power_kW: float
    ID_fan_current_A: float
    kiln_motor_current_A: float
    cooler_fan_power_kW: float
    vibration_mm_per_s: float
    bearing_temperature_C: float
    # -- energy terms (MJ/h) ------------------------------------------------------------
    useful_process_heat_MJ_per_h: float
    exhaust_gas_loss_MJ_per_h: float
    radiation_other_loss_MJ_per_h: float
    cooler_available_heat_MJ_per_h: float
    recovered_cooler_heat_MJ_per_h: float
    energy_balance: balances.KilnEnergyBalance = field(repr=False)

    def as_dict(self) -> dict[str, Any]:
        data = {
            key: value
            for key, value in asdict(self).items()
            if key != "energy_balance"
        }
        data["energy_balance"] = self.energy_balance.as_dict()
        return data


def oxygen_percent_dry(
    combustion_air_Nm3_per_h: float,
    stoichiometric_air_Nm3_per_h: float,
    dry_gas_Nm3_per_h: float,
    oxygen_in_dry_air_pct: float,
) -> float:
    """Back-end O2 on a dry basis: the O2 of the unburnt excess air, diluted by process gas.

    Combustion converts O2 to CO2/H2O at near-constant volume, so the excess-air oxygen is
    what an analyser sees at the kiln inlet (PRD 9.4 gas side; the false-air ingress of
    ``gas_and_combustion.false_air_fraction`` enters downstream of the analyser).

    Shared with ``FanFuelModel`` so the reference point and the dynamic model cannot disagree
    about what "2.14 % O2" means.
    """
    excess_air = max(0.0, float(combustion_air_Nm3_per_h) - float(stoichiometric_air_Nm3_per_h))
    if float(dry_gas_Nm3_per_h) <= 1e-9:
        return 0.0
    return float(oxygen_in_dry_air_pct) * excess_air / float(dry_gas_Nm3_per_h)


def solve_reference_point(
    kiln_config: Mapping[str, Any] | None = None,
    fuel: FuelProperties | None = None,
) -> KilnReferencePoint:
    """Solve the reference thermal input from the PRD 9.3 energy balance, then derive the rest.

    The balance is linear in the fuel energy input ``F`` (radiation is a fraction of ``F``, and
    the combustion-air part of the exhaust flow is proportional to ``F``), so the fixed-point
    iteration below converges geometrically in a handful of passes; it is used instead of the
    closed form so the same code keeps working if a future term is added to the balance.
    """
    if kiln_config is None:
        from src.config import KILN, load_config

        kiln_config = load_config(KILN)
    if fuel is None:
        fuel = FuelProperties.from_config(kiln_config)

    ref = kiln_config["reference"]
    energy_cfg = kiln_config["energy_balance"]
    mass_cfg = kiln_config["mass_balance"]
    gas_cfg = kiln_config["gas_and_combustion"]

    feed = float(ref["kiln_feed_rate_tph"])
    moisture = float(ref["raw_meal_moisture_pct"])
    ambient = float(ref["ambient_temperature_C"])
    meal_temperature = float(ref["raw_meal_temperature_C"])
    burning_zone = float(ref["burning_zone_temperature_C"])
    calciner = float(ref["calciner_temperature_C"])
    preheater_outlet = float(ref["preheater_outlet_temperature_C"])
    excess_air_ratio = float(ref["excess_air_ratio"])

    # -- material side (PRD 9.3 mass balance) -------------------------------------------
    clinker = feed * float(mass_cfg["clinker_factor"])
    loi_loss = feed * float(mass_cfg["LOI_loss_fraction"])
    dust_loss = feed * float(mass_cfg["dust_loss_fraction"])
    residence_h = float(mass_cfg["kiln_residence_time_min"]) / balances.MINUTES_PER_HOUR
    inventory = clinker * residence_h  # steady state: discharge = inventory / residence time

    # -- fixed terms of the energy balance ----------------------------------------------
    clinker_exit = burning_zone - float(energy_cfg["clinker_exit_temperature_offset_K"])
    useful = balances.useful_process_heat_MJ_per_h(
        feed_rate_tph=feed,
        clinker_production_tph=clinker,
        raw_meal_moisture_pct=moisture,
        raw_meal_temperature_C=meal_temperature,
        calciner_temperature_C=calciner,
        clinker_exit_temperature_C=clinker_exit,
        energy_config=energy_cfg,
    )
    cooler_available = balances.cooler_available_heat_MJ_per_h(
        clinker, clinker_exit, ambient, float(energy_cfg["cp_clinker_kJ_per_kgK"])
    )
    recovered = balances.recovered_cooler_heat_MJ_per_h(
        cooler_available, float(energy_cfg["cooler_heat_recovery_fraction"])
    )
    gas = balances.calcination_gas(feed, moisture, mass_cfg)
    false_air = float(gas_cfg["false_air_fraction"])
    cp_exhaust = float(energy_cfg["cp_exhaust_gas_kJ_per_Nm3K"])
    radiation_fraction = float(energy_cfg["radiation_other_loss_fraction"])

    # -- solve for the fuel energy input ------------------------------------------------
    thermal_input = clinker * 1000.0 * _INITIAL_GUESS_MJ_PER_KG_CLINKER
    exhaust_flow = 0.0
    exhaust_loss = 0.0
    for _ in range(_SOLVE_MAX_ITERATIONS):
        combustion_air = fuel.stoichiometric_air_Nm3_per_h(thermal_input) * excess_air_ratio
        exhaust_flow = (combustion_air + gas.total_Nm3_per_h) * (1.0 + false_air)
        exhaust_loss = balances.exhaust_gas_loss_MJ_per_h(
            exhaust_flow, preheater_outlet, ambient, cp_exhaust
        )
        updated = (useful + exhaust_loss - recovered) / (1.0 - radiation_fraction)
        if abs(updated - thermal_input) <= _SOLVE_TOLERANCE * max(1.0, abs(updated)):
            thermal_input = updated
            break
        thermal_input = updated
    else:  # pragma: no cover - only reachable with a non-physical config
        raise RuntimeError(
            "kiln reference energy balance did not converge; check configs/kiln_dynamics.yaml "
            "(radiation_other_loss_fraction must be < 1 and temperatures must be physical)"
        )

    # -- derived fuel, gas and emission quantities --------------------------------------
    stoichiometric_air = fuel.stoichiometric_air_Nm3_per_h(thermal_input)
    combustion_air = stoichiometric_air * excess_air_ratio
    flows = balances.back_end_gas_flows(
        combustion_air, gas.CO2_Nm3_per_h, gas.H2O_Nm3_per_h, false_air
    )
    back_end_gas = flows.back_end_Nm3_per_h
    dry_back_end_gas = flows.dry_back_end_Nm3_per_h
    combustion_CO2 = fuel.combustion_CO2_Nm3_per_h(thermal_input)
    oxygen = oxygen_percent_dry(
        combustion_air,
        stoichiometric_air,
        dry_back_end_gas,
        float(gas_cfg["oxygen_in_dry_air_pct"]),
    )
    co2_percent = (
        100.0 * (combustion_CO2 + gas.CO2_Nm3_per_h) / dry_back_end_gas
        if dry_back_end_gas > 1e-9
        else 0.0
    )
    total_fuel = fuel.solid_fuel_rate_tph(thermal_input)
    kiln_fuel, calciner_fuel = fuel.split_fuel_rates_tph(total_fuel)
    radiation = balances.radiation_other_loss_MJ_per_h(thermal_input, radiation_fraction)

    # -- equipment reference draws (PRD 9.5): the ID fan moves ACTUAL volume ------------
    equipment_cfg = kiln_config["equipment"]
    exhaust_actual = electrical.normal_to_actual_m3_per_h(
        exhaust_flow, preheater_outlet, float(gas_cfg["normal_temperature_K"])
    )
    id_fan_power = electrical.fan_shaft_power_kW(
        exhaust_actual,
        float(equipment_cfg["id_fan_total_dp_mbar_ref"]),
        float(equipment_cfg["id_fan_efficiency"]),
    )
    id_fan_current = electrical.three_phase_current_A(
        id_fan_power,
        float(equipment_cfg["id_fan_motor_voltage_V"]),
        float(equipment_cfg["id_fan_power_factor"]),
    )

    energy_balance = balances.KilnEnergyBalance(
        fuel_energy_input_MJ_per_h=thermal_input,
        recovered_cooler_heat_MJ_per_h=recovered,
        useful_process_heat_MJ_per_h=useful,
        exhaust_gas_loss_MJ_per_h=exhaust_loss,
        radiation_other_loss_MJ_per_h=radiation,
    )

    return KilnReferencePoint(
        feed_rate_tph=feed,
        clinker_production_tph=clinker,
        LOI_loss_tph=loi_loss,
        dust_loss_tph=dust_loss,
        kiln_inventory_t=inventory,
        residence_time_h=residence_h,
        thermal_input_MJ_per_h=thermal_input,
        total_fuel_rate_tph=total_fuel,
        kiln_fuel_rate_tph=kiln_fuel,
        calciner_fuel_rate_tph=calciner_fuel,
        thermal_energy_kcal_per_kg_clinker=specific_thermal_energy_kcal_per_kg(
            thermal_input, clinker
        ),
        ambient_temperature_C=ambient,
        raw_meal_temperature_C=meal_temperature,
        raw_meal_moisture_pct=moisture,
        burning_zone_temperature_C=burning_zone,
        clinker_exit_temperature_C=clinker_exit,
        calciner_temperature_C=calciner,
        kiln_inlet_temperature_C=float(ref["kiln_inlet_temperature_C"]),
        preheater_outlet_temperature_C=preheater_outlet,
        secondary_air_temperature_C=float(ref["secondary_air_temperature_C"]),
        cooler_outlet_temperature_C=float(ref["cooler_outlet_temperature_C"]),
        kiln_speed_rpm=float(ref["kiln_speed_rpm"]),
        ID_fan_speed_pct=float(ref["ID_fan_speed_pct"]),
        excess_air_ratio=excess_air_ratio,
        stoichiometric_air_Nm3_per_h=stoichiometric_air,
        combustion_air_Nm3_per_h=combustion_air,
        primary_air_flow_Nm3_per_h=combustion_air * float(gas_cfg["primary_air_share"]),
        secondary_air_flow_Nm3_per_h=combustion_air * float(gas_cfg["secondary_air_share"]),
        tertiary_air_flow_Nm3_per_h=combustion_air * float(gas_cfg["tertiary_air_share"]),
        calcination_CO2_Nm3_per_h=gas.CO2_Nm3_per_h,
        calcination_H2O_Nm3_per_h=gas.H2O_Nm3_per_h,
        combustion_CO2_Nm3_per_h=combustion_CO2,
        back_end_gas_Nm3_per_h=back_end_gas,
        dry_back_end_gas_Nm3_per_h=dry_back_end_gas,
        exhaust_gas_flow_Nm3_per_h=exhaust_flow,
        oxygen_percent=oxygen,
        CO2_percent=co2_percent,
        exhaust_gas_actual_m3_per_h=exhaust_actual,
        ID_fan_power_kW=id_fan_power,
        ID_fan_current_A=id_fan_current,
        kiln_motor_current_A=float(equipment_cfg["kiln_drive_current_ref_A"]),
        cooler_fan_power_kW=float(equipment_cfg["cooler_fan_power_kW_ref"]),
        vibration_mm_per_s=float(equipment_cfg["vibration_ref_mm_s"]),
        bearing_temperature_C=float(equipment_cfg["bearing_temperature_ref_C"]),
        useful_process_heat_MJ_per_h=useful,
        exhaust_gas_loss_MJ_per_h=exhaust_loss,
        radiation_other_loss_MJ_per_h=radiation,
        cooler_available_heat_MJ_per_h=cooler_available,
        recovered_cooler_heat_MJ_per_h=recovered,
        energy_balance=energy_balance,
    )


def consistency_report(
    reference: KilnReferencePoint, kiln_config: Mapping[str, Any] | None = None
) -> dict[str, float]:
    """Compare the *derived* reference point against the values the config states directly.

    ``configs/kiln_dynamics.yaml`` marks ``oxygen_percent`` and ``CO_ppm`` as DERIVED; this
    report is how the Section 34 tests check that the derivation and the documented value have
    not drifted apart, and that the reference closure really is exact.
    """
    if kiln_config is None:
        from src.config import KILN, load_config

        kiln_config = load_config(KILN)
    ref = kiln_config["reference"]
    return {
        "energy_residual_pct": reference.energy_balance.residual_pct,
        "oxygen_percent_derived": reference.oxygen_percent,
        "oxygen_percent_config": float(ref["oxygen_percent"]),
        "oxygen_percent_delta": reference.oxygen_percent - float(ref["oxygen_percent"]),
        "thermal_energy_kcal_per_kg_clinker": reference.thermal_energy_kcal_per_kg_clinker,
        "specific_thermal_energy_MJ_per_kg": reference.thermal_input_MJ_per_h
        / (reference.clinker_production_tph * 1000.0),
        "mass_residual_pct": balances.KilnMassBalance(
            feed_rate_tph=reference.feed_rate_tph,
            clinker_production_tph=reference.clinker_production_tph,
            LOI_loss_tph=reference.LOI_loss_tph,
            dust_loss_tph=reference.dust_loss_tph,
            inventory_change_tph=0.0,
        ).residual_pct,
    }


__all__ = [
    "KilnReferencePoint",
    "oxygen_percent_dry",
    "solve_reference_point",
    "consistency_report",
]
