"""Kiln gas-side units: fans/fuel and the preheater tower (PRD v1.1.1 Sections 8.3, 9.4, 9.5).

``FanFuelModel`` owns the fuel properties, the combustion-air supply, the back-end gas
composition (O2, CO, CO2, NOx, SO2) and the ID fan's electrical draw. ``PreheaterModel`` owns
the exhaust gas flow, the tower pressure, and the preheater outlet temperature - which is the
state variable that *carries* the kiln energy-balance closure (PRD 9.3).

Every causal relationship in both units is routed through its own configured
``DelayedResponse``. Where the PRD tabulates two delays into one output (``fuel -> O2`` at
0.5/4 min and ``ID fan -> O2`` at 0.2/3 min), the two are applied to the two *physical
mechanisms* - the fuel's stoichiometric oxygen demand and the fan's air delivery - and the
output is then computed from both delayed quantities. That keeps one delay per relationship
(AC-15) instead of collapsing them into a single time constant.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from src.process_models import balances, electrical, gains
from src.process_models.fuel import FuelProperties
from src.process_models.interfaces import UnitBase
from src.process_models.kiln_reference import (
    KilnReferencePoint,
    oxygen_percent_dry,
    solve_reference_point,
)
from src.simulation.delays import DelayBank, build_delay_bank

#: Bound on the CO exponential so an extreme what-if O2 cannot overflow the float.
_MAX_EXPONENT = 700.0


def kiln_context(
    kiln_config: Mapping[str, Any] | None = None,
    reference: KilnReferencePoint | None = None,
) -> tuple[Mapping[str, Any], KilnReferencePoint]:
    """Load the kiln config and its solved reference point (shared by every kiln unit)."""
    if kiln_config is None:
        from src.config import KILN, load_config

        kiln_config = load_config(KILN)
    if reference is None:
        reference = solve_reference_point(kiln_config)
    return kiln_config, reference


class FanFuelModel(UnitBase):
    """Fuel energy, combustion air, back-end gas composition and ID fan power (PRD 8.3/9.4).

    Reads two feedback signals from the rest of the kiln (both one step old, which is what a
    discrete plant model physically is): the burning-zone temperature that drives thermal NOx,
    and the preheater outlet temperature that sets the ID fan's actual volumetric duty.
    """

    __slots__ = ("_cfg", "_delays", "_fuel", "_ref")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        reference: KilnReferencePoint | None = None,
        fuel: FuelProperties | None = None,
        name: str = "FanFuel",
    ) -> None:
        super().__init__(name)
        kiln_config, reference = kiln_context(kiln_config, reference)
        self._cfg = kiln_config
        self._ref = reference
        self._fuel = fuel if fuel is not None else FuelProperties.from_config(kiln_config)
        self._delays: DelayBank = build_delay_bank(kiln_config)
        self.constraints = {
            "ID_fan_speed": tuple(kiln_config["operating_ranges"]["ID_fan_speed_pct"]),
            "oxygen_percent": (0.0, 100.0),
        }
        self.reset()

    # -- initialisation -------------------------------------------------------------------
    def reset(self) -> None:
        """Place every relationship exactly on the reference point (PRD 9.3 closure at t=0)."""
        ref = self._ref
        reference_CO = self.CO_from_oxygen(ref.oxygen_percent)
        reference_NOx = float(self._cfg["reference"]["NOx_ppm"])
        reference_SO2 = float(self._cfg["reference"]["SO2_ppm"])
        reference_pressure = float(self._cfg["gains"]["pressures"]["kiln_inlet_pressure_mbar_ref"])

        self.inputs = {
            "kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph,
            "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
            "kiln_feed_rate_tph": ref.feed_rate_tph,
            "ID_fan_speed_pct": ref.ID_fan_speed_pct,
            "raw_meal_moisture_pct": ref.raw_meal_moisture_pct,
            "burning_zone_temperature_C": ref.burning_zone_temperature_C,
            "preheater_outlet_temperature_C": ref.preheater_outlet_temperature_C,
        }
        self._delays.settle_all(
            {
                "fuel_to_oxygen": ref.stoichiometric_air_Nm3_per_h,
                "id_fan_to_oxygen": ref.combustion_air_Nm3_per_h,
                "fuel_to_CO2": ref.combustion_CO2_Nm3_per_h,
                "oxygen_to_CO": reference_CO,
                "burning_zone_temperature_to_NOx": reference_NOx,
                "oxygen_to_SO2": reference_SO2,
                "id_fan_to_pressure": reference_pressure,
                "load_to_electrical": ref.ID_fan_power_kW,
            }
        )
        self.state = {
            "thermal_input_MJ_per_h": ref.thermal_input_MJ_per_h,
            "stoichiometric_air_Nm3_per_h": ref.stoichiometric_air_Nm3_per_h,
            "combustion_air_Nm3_per_h": ref.combustion_air_Nm3_per_h,
            "excess_air_ratio": ref.excess_air_ratio,
            "back_end_gas_Nm3_per_h": ref.back_end_gas_Nm3_per_h,
            "dry_back_end_gas_Nm3_per_h": ref.dry_back_end_gas_Nm3_per_h,
            "exhaust_gas_flow_Nm3_per_h": ref.exhaust_gas_flow_Nm3_per_h,
            "calcination_CO2_Nm3_per_h": ref.calcination_CO2_Nm3_per_h,
            "calcination_H2O_Nm3_per_h": ref.calcination_H2O_Nm3_per_h,
        }
        self.outputs = {
            "kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph,
            "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
            "ID_fan_speed": ref.ID_fan_speed_pct,
            "primary_air_flow": ref.primary_air_flow_Nm3_per_h,
            "secondary_air_flow": ref.secondary_air_flow_Nm3_per_h,
            "tertiary_air_flow": ref.tertiary_air_flow_Nm3_per_h,
            "oxygen_percent": ref.oxygen_percent,
            "CO_ppm": reference_CO,
            "CO2_percent": ref.CO2_percent,
            "NOx_ppm": reference_NOx,
            "SO2_ppm": reference_SO2,
            "kiln_inlet_pressure": reference_pressure,
            "ID_fan_power": ref.ID_fan_power_kW,
            "ID_fan_current": ref.ID_fan_current_A,
        }

    # -- relationships (pure, so the reference solve and the tests can reuse them) --------
    def CO_from_oxygen(self, oxygen_percent: float) -> float:
        """Deliberately nonlinear CO(O2) curve (PRD 9.4/20.1: CO must blow up as O2 -> floor)."""
        cfg = self._cfg["gains"]["CO_ppm"]
        exponent = gains.clamp(
            -float(cfg["decay_per_pct_O2"])
            * (float(oxygen_percent) - float(cfg["O2_floor_pct"])),
            -_MAX_EXPONENT,
            _MAX_EXPONENT,
        )
        return float(cfg["base_ppm"]) + float(cfg["amplitude_ppm"]) * math.exp(exponent)

    def NOx_from_state(self, burning_zone_temperature_C: float, oxygen_percent: float) -> float:
        """Thermal-NOx form: exponential in BZT, power law in O2 (PRD 9.4)."""
        cfg = self._cfg["gains"]["NOx_ppm"]
        ref = self._ref
        exponent = gains.clamp(
            float(cfg["exp_per_100K_BZT"])
            * (float(burning_zone_temperature_C) - ref.burning_zone_temperature_C)
            / 100.0,
            -_MAX_EXPONENT,
            _MAX_EXPONENT,
        )
        oxygen_factor = gains.power_law(
            max(0.0, float(oxygen_percent)), ref.oxygen_percent, float(cfg["O2_exponent"])
        )
        return float(self._cfg["reference"]["NOx_ppm"]) * math.exp(exponent) * oxygen_factor

    def SO2_from_oxygen(self, oxygen_percent: float) -> float:
        """SO2 release rises once reducing conditions appear below the O2 threshold (PRD 9.4)."""
        cfg = self._cfg["gains"]["SO2_ppm"]
        deficit = max(0.0, float(cfg["O2_threshold_pct"]) - float(oxygen_percent))
        return float(self._cfg["reference"]["SO2_ppm"]) * (
            1.0 + float(cfg["gain_per_pct_O2_deficit"]) * deficit
        )

    def air_supplied_Nm3_per_h(
        self, ID_fan_speed_pct: float, calcination_gas_Nm3_per_h: float
    ) -> float:
        """Combustion air the fan delivers: fan law, reduced by calcination-gas displacement.

        At constant fan speed the tower's total gas volume is roughly fixed, so extra
        calcination gas from a higher feed rate displaces combustion air - the mechanism that
        makes O2 fall when feed rises (PRD 9.4 ``gas_displacement_factor``).
        """
        gas_cfg = self._cfg["gas_and_combustion"]
        ref = self._ref
        fan_factor = gains.power_law(
            ID_fan_speed_pct, ref.ID_fan_speed_pct, float(gas_cfg["air_supply_fan_exponent"])
        )
        reference_gas = ref.calcination_CO2_Nm3_per_h + ref.calcination_H2O_Nm3_per_h
        displacement = 1.0 - float(gas_cfg["gas_displacement_factor"]) * (
            float(calcination_gas_Nm3_per_h) / reference_gas - 1.0
        )
        return gains.clamp(ref.combustion_air_Nm3_per_h * fan_factor * displacement, low=0.0)

    # -- dynamics --------------------------------------------------------------------------
    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        """Advance the gas side by ``dt_seconds`` (PRD 8.4 interface, PRD 9.4 delays)."""
        self.merge_inputs(inputs)
        ref = self._ref
        gas_cfg = self._cfg["gas_and_combustion"]

        kiln_fuel = self.input_value("kiln_fuel_rate_tph", default=ref.kiln_fuel_rate_tph)
        calciner_fuel = self.input_value(
            "calciner_fuel_rate_tph", default=ref.calciner_fuel_rate_tph
        )
        feed = self.input_value(
            "kiln_feed_rate_tph", "kiln_feed_rate", default=ref.feed_rate_tph
        )
        fan_speed = self.input_value(
            "ID_fan_speed_pct", "ID_fan_speed", default=ref.ID_fan_speed_pct
        )
        moisture = self.input_value(
            "raw_meal_moisture_pct", "raw_meal_moisture", default=ref.raw_meal_moisture_pct
        )
        burning_zone = self.input_value(
            "burning_zone_temperature_C",
            "burning_zone_temperature",
            default=ref.burning_zone_temperature_C,
        )
        preheater_outlet = self.input_value(
            "preheater_outlet_temperature_C",
            "preheater_outlet_temperature",
            default=ref.preheater_outlet_temperature_C,
        )

        # -- fuel energy and the two O2 mechanisms, each with its own delay ---------------
        thermal_input = self._fuel.thermal_input_MJ_per_h(kiln_fuel, calciner_fuel)
        calcination = balances.calcination_gas(feed, moisture, self._cfg["mass_balance"])
        air_supplied_target = self.air_supplied_Nm3_per_h(fan_speed, calcination.total_Nm3_per_h)

        # PRD 9.4 row "Fuel rate -> O2": the fuel's oxygen DEMAND arrives with this delay.
        stoichiometric_air = self._delays.step(
            "fuel_to_oxygen", self._fuel.stoichiometric_air_Nm3_per_h(thermal_input), dt_seconds
        )
        # PRD 9.4 row "ID fan speed -> O2": the fan's air DELIVERY arrives with this delay.
        combustion_air = self._delays.step("id_fan_to_oxygen", air_supplied_target, dt_seconds)

        flows = balances.back_end_gas_flows(
            combustion_air,
            calcination.CO2_Nm3_per_h,
            calcination.H2O_Nm3_per_h,
            float(gas_cfg["false_air_fraction"]),
        )
        oxygen = oxygen_percent_dry(
            combustion_air,
            stoichiometric_air,
            flows.dry_back_end_Nm3_per_h,
            float(gas_cfg["oxygen_in_dry_air_pct"]),
        )
        excess_air_ratio = (
            combustion_air / stoichiometric_air if stoichiometric_air > 1e-9 else 0.0
        )

        # -- composition, each through its own relationship delay -------------------------
        combustion_CO2 = self._delays.step(
            "fuel_to_CO2", self._fuel.combustion_CO2_Nm3_per_h(thermal_input), dt_seconds
        )
        CO2_percent = (
            100.0
            * (combustion_CO2 + calcination.CO2_Nm3_per_h)
            / flows.dry_back_end_Nm3_per_h
            if flows.dry_back_end_Nm3_per_h > 1e-9
            else 0.0
        )
        CO_ppm = self._delays.step("oxygen_to_CO", self.CO_from_oxygen(oxygen), dt_seconds)
        NOx_ppm = self._delays.step(
            "burning_zone_temperature_to_NOx",
            self.NOx_from_state(burning_zone, oxygen),
            dt_seconds,
        )
        SO2_ppm = self._delays.step("oxygen_to_SO2", self.SO2_from_oxygen(oxygen), dt_seconds)

        # -- draught and ID fan electrical draw (PRD 9.5) ---------------------------------
        pressure_cfg = self._cfg["gains"]["pressures"]
        pressure_target = (
            float(pressure_cfg["kiln_inlet_pressure_mbar_ref"])
            * gains.power_law(fan_speed, ref.ID_fan_speed_pct, float(pressure_cfg["fan_exponent"]))
            * (
                1.0
                + float(pressure_cfg["flow_sensitivity"])
                * (flows.exhaust_Nm3_per_h / ref.exhaust_gas_flow_Nm3_per_h - 1.0)
            )
        )
        kiln_inlet_pressure = self._delays.step("id_fan_to_pressure", pressure_target, dt_seconds)

        equipment_cfg = self._cfg["equipment"]
        actual_flow = electrical.normal_to_actual_m3_per_h(
            flows.exhaust_Nm3_per_h, preheater_outlet, float(gas_cfg["normal_temperature_K"])
        )
        fan_dp = float(equipment_cfg["id_fan_total_dp_mbar_ref"]) * gains.power_law(
            fan_speed, ref.ID_fan_speed_pct, float(pressure_cfg["fan_exponent"])
        )
        fan_power = self._delays.step(
            "load_to_electrical",
            electrical.fan_shaft_power_kW(
                actual_flow, fan_dp, float(equipment_cfg["id_fan_efficiency"])
            ),
            dt_seconds,
        )
        fan_current = electrical.three_phase_current_A(
            fan_power,
            float(equipment_cfg["id_fan_motor_voltage_V"]),
            float(equipment_cfg["id_fan_power_factor"]),
        )

        self.state.update(
            thermal_input_MJ_per_h=thermal_input,
            stoichiometric_air_Nm3_per_h=stoichiometric_air,
            combustion_air_Nm3_per_h=combustion_air,
            excess_air_ratio=excess_air_ratio,
            back_end_gas_Nm3_per_h=flows.back_end_Nm3_per_h,
            dry_back_end_gas_Nm3_per_h=flows.dry_back_end_Nm3_per_h,
            exhaust_gas_flow_Nm3_per_h=flows.exhaust_Nm3_per_h,
            calcination_CO2_Nm3_per_h=calcination.CO2_Nm3_per_h,
            calcination_H2O_Nm3_per_h=calcination.H2O_Nm3_per_h,
            exhaust_gas_actual_m3_per_h=actual_flow,
        )
        self.outputs.update(
            kiln_fuel_rate_tph=kiln_fuel,
            calciner_fuel_rate_tph=calciner_fuel,
            ID_fan_speed=fan_speed,
            primary_air_flow=combustion_air * float(gas_cfg["primary_air_share"]),
            secondary_air_flow=combustion_air * float(gas_cfg["secondary_air_share"]),
            tertiary_air_flow=combustion_air * float(gas_cfg["tertiary_air_share"]),
            oxygen_percent=gains.clamp(oxygen, low=0.0),
            CO_ppm=gains.clamp(CO_ppm, low=0.0),
            CO2_percent=gains.clamp(CO2_percent, low=0.0),
            NOx_ppm=gains.clamp(NOx_ppm, low=0.0),
            SO2_ppm=gains.clamp(SO2_ppm, low=0.0),
            kiln_inlet_pressure=kiln_inlet_pressure,
            ID_fan_power=gains.clamp(fan_power, low=0.0),
            ID_fan_current=gains.clamp(fan_current, low=0.0),
        )
        return self.outputs


class PreheaterModel(UnitBase):
    """Preheater tower: exhaust gas flow, tower draught, and the energy-closure temperature.

    The preheater outlet temperature is *not* a fitted gain. ``RotaryKilnModel`` computes how
    much energy the exhaust gas must carry for the PRD 9.3 balance to close, inverts it into a
    temperature, and passes it here as ``preheater_outlet_temperature_target_C``; this unit
    routes it through the ``energy_closure_to_preheater_temperature`` relationship. That delay
    is therefore the single source of transient energy-balance residual, bounded by
    ``energy_balance.unaccounted_loss_max_fraction`` (NFR-10).
    """

    __slots__ = ("_cfg", "_delays", "_ref")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        reference: KilnReferencePoint | None = None,
        name: str = "Preheater",
    ) -> None:
        super().__init__(name)
        kiln_config, reference = kiln_context(kiln_config, reference)
        self._cfg = kiln_config
        self._ref = reference
        self._delays: DelayBank = build_delay_bank(kiln_config)
        self.constraints = {
            "preheater_outlet_temperature": (
                float(kiln_config["energy_balance"]["min_preheater_outlet_temperature_C"]),
                1000.0,
            ),
        }
        self.reset()

    def reset(self) -> None:
        ref = self._ref
        false_air = float(self._cfg["gas_and_combustion"]["false_air_fraction"])
        reference_pressure = float(
            self._cfg["gains"]["pressures"]["preheater_pressure_mbar_ref"]
        )
        self.inputs = {
            "combustion_air_Nm3_per_h": ref.combustion_air_Nm3_per_h,
            "calcination_CO2_Nm3_per_h": ref.calcination_CO2_Nm3_per_h,
            "calcination_H2O_Nm3_per_h": ref.calcination_H2O_Nm3_per_h,
            "preheater_outlet_temperature_target_C": ref.preheater_outlet_temperature_C,
            "ID_fan_speed_pct": ref.ID_fan_speed_pct,
        }
        self._delays.settle_all(
            {
                # Fuel-side and feed-side contributions to the exhaust volume travel at
                # different speeds (gas-side fast, material-side slow) - PRD 9.4.
                "fuel_to_exhaust_flow": ref.combustion_air_Nm3_per_h * (1.0 + false_air),
                "feed_to_exhaust_flow": (
                    ref.calcination_CO2_Nm3_per_h + ref.calcination_H2O_Nm3_per_h
                )
                * (1.0 + false_air),
                "energy_closure_to_preheater_temperature": ref.preheater_outlet_temperature_C,
                "id_fan_to_pressure": reference_pressure,
            }
        )
        self.state = {
            "exhaust_gas_flow_Nm3_per_h": ref.exhaust_gas_flow_Nm3_per_h,
            "preheater_outlet_temperature_C": ref.preheater_outlet_temperature_C,
        }
        self.outputs = {
            "exhaust_gas_flow": ref.exhaust_gas_flow_Nm3_per_h,
            "preheater_outlet_temperature": ref.preheater_outlet_temperature_C,
            "preheater_pressure": reference_pressure,
        }

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        false_air = float(self._cfg["gas_and_combustion"]["false_air_fraction"])

        combustion_air = self.input_value(
            "combustion_air_Nm3_per_h", default=ref.combustion_air_Nm3_per_h
        )
        calcination_CO2 = self.input_value(
            "calcination_CO2_Nm3_per_h", default=ref.calcination_CO2_Nm3_per_h
        )
        calcination_H2O = self.input_value(
            "calcination_H2O_Nm3_per_h", default=ref.calcination_H2O_Nm3_per_h
        )
        target_temperature = self.input_value(
            "preheater_outlet_temperature_target_C",
            default=ref.preheater_outlet_temperature_C,
        )
        fan_speed = self.input_value(
            "ID_fan_speed_pct", "ID_fan_speed", default=ref.ID_fan_speed_pct
        )

        fuel_side = self._delays.step(
            "fuel_to_exhaust_flow", combustion_air * (1.0 + false_air), dt_seconds
        )
        feed_side = self._delays.step(
            "feed_to_exhaust_flow",
            (calcination_CO2 + calcination_H2O) * (1.0 + false_air),
            dt_seconds,
        )
        exhaust_flow = gains.clamp(fuel_side + feed_side, low=0.0)

        outlet_temperature = self._delays.step(
            "energy_closure_to_preheater_temperature", target_temperature, dt_seconds
        )

        pressure_cfg = self._cfg["gains"]["pressures"]
        pressure_target = (
            float(pressure_cfg["preheater_pressure_mbar_ref"])
            * gains.power_law(fan_speed, ref.ID_fan_speed_pct, float(pressure_cfg["fan_exponent"]))
            * (
                1.0
                + float(pressure_cfg["flow_sensitivity"])
                * (exhaust_flow / ref.exhaust_gas_flow_Nm3_per_h - 1.0)
            )
        )
        preheater_pressure = self._delays.step("id_fan_to_pressure", pressure_target, dt_seconds)

        self.state.update(
            exhaust_gas_flow_Nm3_per_h=exhaust_flow,
            preheater_outlet_temperature_C=outlet_temperature,
        )
        self.outputs.update(
            exhaust_gas_flow=exhaust_flow,
            preheater_outlet_temperature=outlet_temperature,
            preheater_pressure=preheater_pressure,
        )
        return self.outputs


__all__ = ["kiln_context", "FanFuelModel", "PreheaterModel"]
