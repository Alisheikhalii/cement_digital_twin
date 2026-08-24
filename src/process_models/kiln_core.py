"""Kiln core units: precalciner, rotary kiln and clinker cooler (PRD v1.1.1 Sections 8.3-9.5).

``RotaryKilnModel`` is the unit PRD 8.3 designates as the owner of **both** kiln conservation
closures, and it is where the two hard requirements of Section 9.3 are actually enforced:

* **Mass.** ``Kiln_Feed = Clinker_Production + LOI_Loss + Dust_Loss + d(Kiln_Inventory)/dt``
  holds *exactly*, at every step, including during a feed change. The 5-minute
  ``feed_to_production`` dead time is treated as physical pipe inventory rather than as a signal
  delay: material that has left the feeder but not yet reached the kiln bed is held in
  ``inventory_in_transit_t`` and counted in the inventory term. Without that, a 10 % feed step
  opens a ~6 % instantaneous residual and violates the 3 % tolerance.
* **Energy.** ``Fuel + Recovered_Cooler_Heat = Useful + Exhaust_Loss + Radiation_Loss +
  Unaccounted`` is closed by *solving* for the energy the exhaust gas must carry and inverting
  it into a preheater outlet temperature target (:func:`balances.preheater_outlet_temperature_from_energy`).
  ``Unaccounted`` is then identically zero at steady state, and non-zero only while the
  ``energy_closure_to_preheater_temperature`` relationship is in transit.

The inventory ODE uses backward Euler (``I_new = (I + inflow*dt) / (1 + dt/tau)``), which is
unconditionally stable *and* satisfies ``(I_new - I)/dt = inflow - discharge`` exactly - so the
discretization itself cannot manufacture a conservation residual.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.process_models import balances, gains
from src.process_models.fuel import FuelProperties, specific_thermal_energy_kcal_per_kg
from src.process_models.interfaces import UnitBase
from src.process_models.kiln_gas import kiln_context
from src.process_models.kiln_reference import KilnReferencePoint
from src.simulation.delays import DelayBank, build_delay_bank

#: Key under which the kiln drive's health scalar (0-1) is published by the data generator
#: (PRD 9.5). Health is driven from outside the twin so the twin itself stays deterministic.
HEALTH_KEY = "kiln"


class PrecalcinerModel(UnitBase):
    """Calciner outlet temperature and the material temperature at the kiln inlet (PRD 9.4)."""

    __slots__ = ("_cfg", "_delays", "_ref")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        reference: KilnReferencePoint | None = None,
        name: str = "Precalciner",
    ) -> None:
        super().__init__(name)
        kiln_config, reference = kiln_context(kiln_config, reference)
        self._cfg = kiln_config
        self._ref = reference
        self._delays: DelayBank = build_delay_bank(kiln_config)
        self.constraints = {
            "calciner_temperature": (800.0, 950.0),  # PRD 12.1 band, widened for excursions
        }
        self.reset()

    def reset(self) -> None:
        ref = self._ref
        self.inputs = {
            "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
            "kiln_feed_rate_tph": ref.feed_rate_tph,
        }
        self._delays.settle_all(
            {
                "calciner_fuel_to_calciner_temperature": ref.calciner_temperature_C,
                "calciner_to_kiln_inlet_temperature": ref.kiln_inlet_temperature_C,
            }
        )
        self.state = {"calciner_temperature_C": ref.calciner_temperature_C}
        self.outputs = {
            "calciner_temperature": ref.calciner_temperature_C,
            "kiln_inlet_temperature": ref.kiln_inlet_temperature_C,
        }

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        calciner_gains = self._cfg["gains"]["calciner_temperature"]

        calciner_fuel = self.input_value(
            "calciner_fuel_rate_tph", default=ref.calciner_fuel_rate_tph
        )
        feed = self.input_value("kiln_feed_rate_tph", "kiln_feed_rate", default=ref.feed_rate_tph)

        target = (
            ref.calciner_temperature_C
            + float(calciner_gains["K_per_pct_calciner_fuel"])
            * gains.relative_pct(calciner_fuel, ref.calciner_fuel_rate_tph)
            + float(calciner_gains["K_per_pct_feed"])
            * gains.relative_pct(feed, ref.feed_rate_tph)
        )
        calciner_temperature = self._delays.step(
            "calciner_fuel_to_calciner_temperature", target, dt_seconds
        )

        coupling = float(self._cfg["gains"]["kiln_inlet_temperature"]["coupling_to_calciner"])
        inlet_target = ref.kiln_inlet_temperature_C + coupling * (
            calciner_temperature - ref.calciner_temperature_C
        )
        kiln_inlet_temperature = self._delays.step(
            "calciner_to_kiln_inlet_temperature", inlet_target, dt_seconds
        )

        self.state.update(calciner_temperature_C=calciner_temperature)
        self.outputs.update(
            calciner_temperature=calciner_temperature,
            kiln_inlet_temperature=kiln_inlet_temperature,
        )
        return self.outputs


class CoolerModel(UnitBase):
    """Grate cooler: recuperated air temperature, clinker discharge temperature, fan power."""

    __slots__ = ("_cfg", "_delays", "_ref")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        reference: KilnReferencePoint | None = None,
        name: str = "Cooler",
    ) -> None:
        super().__init__(name)
        kiln_config, reference = kiln_context(kiln_config, reference)
        self._cfg = kiln_config
        self._ref = reference
        self._delays: DelayBank = build_delay_bank(kiln_config)
        self.reset()

    def reset(self) -> None:
        ref = self._ref
        self.inputs = {
            "clinker_production_tph": ref.clinker_production_tph,
            "clinker_exit_temperature_C": ref.clinker_exit_temperature_C,
        }
        self._delays.settle_all(
            {
                "clinker_to_secondary_air_temperature": ref.secondary_air_temperature_C,
                "clinker_to_cooler_outlet_temperature": ref.cooler_outlet_temperature_C,
                "load_to_electrical": ref.cooler_fan_power_kW,
            }
        )
        self.state = {
            "cooler_available_heat_MJ_per_h": ref.cooler_available_heat_MJ_per_h,
            "recovered_cooler_heat_MJ_per_h": ref.recovered_cooler_heat_MJ_per_h,
        }
        self.outputs = {
            "secondary_air_temperature": ref.secondary_air_temperature_C,
            "cooler_outlet_temperature": ref.cooler_outlet_temperature_C,
            # PRD 12.1 lists clinker_temperature and cooler_outlet_temperature separately with
            # the same 80-150 C band; they are the same physical stream under two factory names.
            "clinker_temperature": ref.cooler_outlet_temperature_C,
            "cooler_fan_power": ref.cooler_fan_power_kW,
        }

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        energy_cfg = self._cfg["energy_balance"]
        equipment_cfg = self._cfg["equipment"]

        clinker = self.input_value("clinker_production_tph", default=ref.clinker_production_tph)
        clinker_exit = self.input_value(
            "clinker_exit_temperature_C", default=ref.clinker_exit_temperature_C
        )

        available = balances.cooler_available_heat_MJ_per_h(
            clinker, clinker_exit, ref.ambient_temperature_C, float(energy_cfg["cp_clinker_kJ_per_kgK"])
        )
        recovered = balances.recovered_cooler_heat_MJ_per_h(
            available, float(energy_cfg["cooler_heat_recovery_fraction"])
        )

        secondary_gains = self._cfg["gains"]["secondary_air_temperature"]
        secondary_target = (
            ref.secondary_air_temperature_C
            + float(secondary_gains["K_per_K_clinker_exit"])
            * (clinker_exit - ref.clinker_exit_temperature_C)
            + float(secondary_gains["K_per_pct_clinker_rate"])
            * gains.relative_pct(max(1e-6, clinker), ref.clinker_production_tph)
        )
        secondary_air_temperature = self._delays.step(
            "clinker_to_secondary_air_temperature", secondary_target, dt_seconds
        )

        outlet_gains = self._cfg["gains"]["cooler_outlet_temperature"]
        outlet_target = (
            ref.cooler_outlet_temperature_C
            + float(outlet_gains["K_per_K_clinker_exit"])
            * (clinker_exit - ref.clinker_exit_temperature_C)
            + float(outlet_gains["K_per_pct_clinker_rate"])
            * gains.relative_pct(max(1e-6, clinker), ref.clinker_production_tph)
        )
        cooler_outlet_temperature = self._delays.step(
            "clinker_to_cooler_outlet_temperature", outlet_target, dt_seconds
        )

        fan_power = self._delays.step(
            "load_to_electrical",
            float(equipment_cfg["cooler_fan_power_kW_ref"])
            * gains.power_law(
                max(0.0, clinker),
                ref.clinker_production_tph,
                float(equipment_cfg["cooler_fan_clinker_exponent"]),
            ),
            dt_seconds,
        )

        self.state.update(
            cooler_available_heat_MJ_per_h=available,
            recovered_cooler_heat_MJ_per_h=recovered,
        )
        self.outputs.update(
            secondary_air_temperature=secondary_air_temperature,
            cooler_outlet_temperature=cooler_outlet_temperature,
            clinker_temperature=cooler_outlet_temperature,
            cooler_fan_power=gains.clamp(fan_power, low=0.0),
        )
        return self.outputs


class RotaryKilnModel(UnitBase):
    """The kiln itself, and the owner of both PRD 9.3 conservation closures (PRD 8.3).

    Signals it receives from the rest of the kiln - ``recovered_cooler_heat_MJ_per_h`` from the
    cooler, ``exhaust_gas_flow_Nm3_per_h`` and ``preheater_outlet_temperature_C`` from the
    preheater - are one step old, which is what a discrete plant model physically is. At steady
    state they are exactly consistent with what this unit publishes, so both residuals are zero;
    during a transient the residual is bounded by the single delay that carries the closure.
    """

    __slots__ = ("_cfg", "_delays", "_energy_balance", "_fuel", "_mass_balance", "_ref")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        reference: KilnReferencePoint | None = None,
        fuel: FuelProperties | None = None,
        name: str = "RotaryKiln",
    ) -> None:
        super().__init__(name)
        kiln_config, reference = kiln_context(kiln_config, reference)
        self._cfg = kiln_config
        self._ref = reference
        self._fuel = fuel if fuel is not None else FuelProperties.from_config(kiln_config)
        self._delays: DelayBank = build_delay_bank(kiln_config)
        self._energy_balance = reference.energy_balance
        self._mass_balance = balances.KilnMassBalance(
            feed_rate_tph=reference.feed_rate_tph,
            clinker_production_tph=reference.clinker_production_tph,
            LOI_loss_tph=reference.LOI_loss_tph,
            dust_loss_tph=reference.dust_loss_tph,
            inventory_change_tph=0.0,
        )
        self.constraints = {
            "burning_zone_temperature": (1400.0, 1500.0),  # PRD 12.1
            "clinker_production_tph": (95.0, 150.0),  # PRD 12.1
        }
        self.reset()

    # -- last evaluated closures (read by the Section 34 conservation tests) --------------
    @property
    def energy_balance(self) -> balances.KilnEnergyBalance:
        return self._energy_balance

    @property
    def mass_balance(self) -> balances.KilnMassBalance:
        return self._mass_balance

    def reset(self) -> None:
        ref = self._ref
        # Material that has left the feeder but not yet reached the kiln bed is real inventory,
        # not a signal delay - see the module docstring and PRD 9.3.
        transit_h = self._delays.dead_time_s("feed_to_production") / balances.SECONDS_PER_HOUR
        self.inputs = {
            "kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph,
            "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
            "kiln_feed_rate_tph": ref.feed_rate_tph,
            "kiln_speed_rpm": ref.kiln_speed_rpm,
            "raw_meal_moisture_pct": ref.raw_meal_moisture_pct,
            "raw_meal_temperature_C": ref.raw_meal_temperature_C,
            "calciner_temperature_C": ref.calciner_temperature_C,
            "recovered_cooler_heat_MJ_per_h": ref.recovered_cooler_heat_MJ_per_h,
            "exhaust_gas_flow_Nm3_per_h": ref.exhaust_gas_flow_Nm3_per_h,
            "preheater_outlet_temperature_C": ref.preheater_outlet_temperature_C,
        }
        self._delays.settle_all(
            {
                "feed_to_production": ref.feed_rate_tph,
                # The two burning-zone rows carry the K *deviation* of their own mechanism, so
                # they settle at zero and the reference temperature is added back below.
                "fuel_to_burning_zone_temperature": 0.0,
                "feed_to_burning_zone_temperature": 0.0,
                "load_to_electrical": ref.kiln_motor_current_A,
                "load_to_vibration": ref.vibration_mm_per_s,
                "load_to_bearing_temperature": ref.bearing_temperature_C,
            }
        )
        self.health = {HEALTH_KEY: float(self._cfg["equipment"]["health"]["initial"])}
        self.state = {
            "kiln_inventory_t": ref.kiln_inventory_t,
            "inventory_in_transit_t": ref.feed_rate_tph * transit_h,
            "clinker_exit_temperature_C": ref.clinker_exit_temperature_C,
            "thermal_input_MJ_per_h": ref.thermal_input_MJ_per_h,
            "useful_process_heat_MJ_per_h": ref.useful_process_heat_MJ_per_h,
            "radiation_other_loss_MJ_per_h": ref.radiation_other_loss_MJ_per_h,
            "exhaust_gas_loss_MJ_per_h": ref.exhaust_gas_loss_MJ_per_h,
            "energy_available_for_exhaust_MJ_per_h": ref.exhaust_gas_loss_MJ_per_h,
        }
        self.outputs = {
            "kiln_feed_rate_tph": ref.feed_rate_tph,
            "kiln_speed_rpm": ref.kiln_speed_rpm,
            "raw_meal_moisture": ref.raw_meal_moisture_pct,
            "raw_meal_temperature": ref.raw_meal_temperature_C,
            "burning_zone_temperature": ref.burning_zone_temperature_C,
            "clinker_production_tph": ref.clinker_production_tph,
            "clinker_exit_temperature_C": ref.clinker_exit_temperature_C,
            # Internal coupling signal: what PreheaterModel routes through the
            # energy_closure_to_preheater_temperature relationship (PRD 9.3).
            "preheater_outlet_temperature_target_C": ref.preheater_outlet_temperature_C,
            "thermal_energy_kcal_per_kg_clinker": ref.thermal_energy_kcal_per_kg_clinker,
            # PRD 12.1 keeps specific_fuel_consumption as a factory-familiar duplicate.
            "specific_fuel_consumption": ref.thermal_energy_kcal_per_kg_clinker,
            "kiln_motor_current": ref.kiln_motor_current_A,
            "vibration": ref.vibration_mm_per_s,
            "bearing_temperature": ref.bearing_temperature_C,
        }
        self._energy_balance = ref.energy_balance
        self._mass_balance = balances.KilnMassBalance(
            feed_rate_tph=ref.feed_rate_tph,
            clinker_production_tph=ref.clinker_production_tph,
            LOI_loss_tph=ref.LOI_loss_tph,
            dust_loss_tph=ref.dust_loss_tph,
            inventory_change_tph=0.0,
        )
        self._publish_residuals()

    def _publish_residuals(self) -> None:
        """Expose both closures on the PRD 8.4 ``balance_residuals`` attribute.

        ``energy_pct`` is the pointwise NFR-10 metric and is only meaningful while the balance
        has a non-trivial input basis. The two absolute companions - the unaccounted loss in
        MJ/h and the instantaneous input it is divided by - are published alongside it so that
        the three-regime validation of :mod:`src.data_generation.conservation` can form a
        numerically stable metric during a startup ramp instead of dividing by a vanishing
        denominator. ``reference_energy_input_MJ_per_h`` is the solved reference operating
        point's own input basis: a fixed, non-zero, config-derived scale, not a new coefficient.
        """
        self.balance_residuals = {
            "energy_pct": self._energy_balance.residual_pct,
            "mass_pct": self._mass_balance.residual_pct,
            "unaccounted_loss_MJ_per_h": self._energy_balance.unaccounted_loss_MJ_per_h,
            "mass_residual_tph": self._mass_balance.residual_tph,
            "energy_input_MJ_per_h": self._energy_balance.input_MJ_per_h,
            "reference_energy_input_MJ_per_h": self._ref.energy_balance.input_MJ_per_h,
        }

    # -- dynamics --------------------------------------------------------------------------
    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        energy_cfg = self._cfg["energy_balance"]
        mass_cfg = self._cfg["mass_balance"]
        equipment_cfg = self._cfg["equipment"]
        dt_h = float(dt_seconds) / balances.SECONDS_PER_HOUR

        kiln_fuel = self.input_value("kiln_fuel_rate_tph", default=ref.kiln_fuel_rate_tph)
        calciner_fuel = self.input_value(
            "calciner_fuel_rate_tph", default=ref.calciner_fuel_rate_tph
        )
        feed = self.input_value("kiln_feed_rate_tph", "kiln_feed_rate", default=ref.feed_rate_tph)
        kiln_speed = self.input_value("kiln_speed_rpm", "kiln_speed", default=ref.kiln_speed_rpm)
        moisture = self.input_value(
            "raw_meal_moisture_pct", "raw_meal_moisture", default=ref.raw_meal_moisture_pct
        )
        meal_temperature = self.input_value(
            "raw_meal_temperature_C", "raw_meal_temperature", default=ref.raw_meal_temperature_C
        )
        calciner_temperature = self.input_value(
            "calciner_temperature_C", "calciner_temperature", default=ref.calciner_temperature_C
        )
        recovered = self.input_value(
            "recovered_cooler_heat_MJ_per_h", default=ref.recovered_cooler_heat_MJ_per_h
        )
        exhaust_flow = self.input_value(
            "exhaust_gas_flow_Nm3_per_h", "exhaust_gas_flow", default=ref.exhaust_gas_flow_Nm3_per_h
        )
        preheater_outlet = self.input_value(
            "preheater_outlet_temperature_C",
            "preheater_outlet_temperature",
            default=ref.preheater_outlet_temperature_C,
        )
        health = gains.clamp(self.health.get(HEALTH_KEY, 1.0), 0.0, 1.0)

        # -- burning zone temperature: fuel mechanism and material mechanism, one delay each
        bzt_gains = self._cfg["gains"]["burning_zone_temperature"]
        fuel_term = float(bzt_gains["K_per_pct_kiln_fuel"]) * gains.relative_pct(
            kiln_fuel, ref.kiln_fuel_rate_tph
        ) + float(bzt_gains["K_per_pct_calciner_fuel"]) * gains.relative_pct(
            calciner_fuel, ref.calciner_fuel_rate_tph
        )
        material_term = (
            float(bzt_gains["K_per_pct_feed"]) * gains.relative_pct(feed, ref.feed_rate_tph)
            + float(bzt_gains["K_per_pct_kiln_speed"])
            * gains.relative_pct(kiln_speed, ref.kiln_speed_rpm)
            + float(bzt_gains["K_per_pct_point_moisture"])
            * (moisture - ref.raw_meal_moisture_pct)
            + float(bzt_gains["K_per_K_meal_temperature"])
            * (meal_temperature - ref.raw_meal_temperature_C)
        )
        burning_zone = (
            ref.burning_zone_temperature_C
            + self._delays.step("fuel_to_burning_zone_temperature", fuel_term, dt_seconds)
            + self._delays.step("feed_to_burning_zone_temperature", material_term, dt_seconds)
        )
        clinker_exit = burning_zone - float(energy_cfg["clinker_exit_temperature_offset_K"])

        # -- mass balance (PRD 9.3): exact at every step, feed step included ---------------
        # `feed_to_production` is configured with tau_min: null, so it is a pure transport
        # queue; the lag comes from the physical kiln-inventory buffer below.
        arrival = self._delays.step("feed_to_production", feed, dt_seconds)
        previous_transit = float(self.state["inventory_in_transit_t"])
        # Non-negative by construction: this is the integral of the queued feed still in flight.
        in_transit = previous_transit + (feed - arrival) * dt_h
        loi_loss = arrival * float(mass_cfg["LOI_loss_fraction"])
        dust_loss = arrival * float(mass_cfg["dust_loss_fraction"])
        bed_inflow = arrival * float(mass_cfg["clinker_factor"])
        previous_inventory = float(self.state["kiln_inventory_t"])
        # Backward Euler: (I_new - I)/dt == inflow - I_new/tau holds exactly, so the
        # discretization cannot manufacture a conservation residual.
        inventory = (previous_inventory + bed_inflow * dt_h) / (1.0 + dt_h / ref.residence_time_h)
        clinker = balances.clinker_discharge_tph(inventory, ref.residence_time_h)
        inventory_change = (
            (inventory - previous_inventory) + (in_transit - previous_transit)
        ) / dt_h
        self._mass_balance = balances.KilnMassBalance(
            feed_rate_tph=feed,
            clinker_production_tph=clinker,
            LOI_loss_tph=loi_loss,
            dust_loss_tph=dust_loss,
            inventory_change_tph=inventory_change,
        )

        # -- energy balance (PRD 9.3): solved for the exhaust term, then inverted ---------
        thermal_input = self._fuel.thermal_input_MJ_per_h(kiln_fuel, calciner_fuel)
        useful = balances.useful_process_heat_MJ_per_h(
            feed_rate_tph=feed,
            clinker_production_tph=clinker,
            raw_meal_moisture_pct=moisture,
            raw_meal_temperature_C=meal_temperature,
            calciner_temperature_C=calciner_temperature,
            clinker_exit_temperature_C=clinker_exit,
            energy_config=energy_cfg,
        )
        radiation = balances.radiation_other_loss_MJ_per_h(
            thermal_input, float(energy_cfg["radiation_other_loss_fraction"])
        )
        cp_exhaust = float(energy_cfg["cp_exhaust_gas_kJ_per_Nm3K"])
        # Whatever is neither used by the process nor radiated must leave with the exhaust gas.
        energy_available = thermal_input + recovered - useful - radiation
        target_temperature = balances.preheater_outlet_temperature_from_energy(
            energy_available,
            exhaust_flow,
            ref.ambient_temperature_C,
            cp_exhaust,
            float(energy_cfg["min_preheater_outlet_temperature_C"]),
        )
        # The residual is measured against the temperature the preheater is ACTUALLY at, so it
        # is zero at steady state and non-zero only while that relationship is in transit.
        exhaust_loss = balances.exhaust_gas_loss_MJ_per_h(
            exhaust_flow, preheater_outlet, ref.ambient_temperature_C, cp_exhaust
        )
        self._energy_balance = balances.KilnEnergyBalance(
            fuel_energy_input_MJ_per_h=thermal_input,
            recovered_cooler_heat_MJ_per_h=recovered,
            useful_process_heat_MJ_per_h=useful,
            exhaust_gas_loss_MJ_per_h=exhaust_loss,
            radiation_other_loss_MJ_per_h=radiation,
        )

        # -- kiln drive and health-driven equipment signals (PRD 9.5) ---------------------
        load = feed / ref.feed_rate_tph
        motor_current = self._delays.step(
            "load_to_electrical",
            float(equipment_cfg["kiln_drive_current_ref_A"])
            * gains.power_law(
                feed, ref.feed_rate_tph, float(equipment_cfg["kiln_drive_feed_exponent"])
            )
            * gains.power_law(
                kiln_speed, ref.kiln_speed_rpm, float(equipment_cfg["kiln_drive_speed_exponent"])
            ),
            dt_seconds,
        )
        vibration = self._delays.step(
            "load_to_vibration",
            float(equipment_cfg["vibration_ref_mm_s"])
            + float(equipment_cfg["vibration_load_gain_mm_s"]) * (load - 1.0)
            + float(equipment_cfg["vibration_health_gain_mm_s"]) * (1.0 - health),
            dt_seconds,
        )
        bearing_temperature = self._delays.step(
            "load_to_bearing_temperature",
            float(equipment_cfg["bearing_temperature_ref_C"])
            + float(equipment_cfg["bearing_temperature_load_gain_K"]) * (load - 1.0)
            + float(equipment_cfg["bearing_temperature_health_gain_K"]) * (1.0 - health),
            dt_seconds,
        )

        specific_energy = specific_thermal_energy_kcal_per_kg(thermal_input, clinker)
        self.state.update(
            kiln_inventory_t=inventory,
            inventory_in_transit_t=in_transit,
            clinker_exit_temperature_C=clinker_exit,
            thermal_input_MJ_per_h=thermal_input,
            useful_process_heat_MJ_per_h=useful,
            radiation_other_loss_MJ_per_h=radiation,
            exhaust_gas_loss_MJ_per_h=exhaust_loss,
            energy_available_for_exhaust_MJ_per_h=energy_available,
        )
        self.outputs.update(
            kiln_feed_rate_tph=feed,
            kiln_speed_rpm=kiln_speed,
            raw_meal_moisture=moisture,
            raw_meal_temperature=meal_temperature,
            burning_zone_temperature=burning_zone,
            clinker_production_tph=gains.clamp(clinker, low=0.0),
            clinker_exit_temperature_C=clinker_exit,
            preheater_outlet_temperature_target_C=target_temperature,
            thermal_energy_kcal_per_kg_clinker=specific_energy,
            specific_fuel_consumption=specific_energy,
            kiln_motor_current=gains.clamp(motor_current, low=0.0),
            vibration=gains.clamp(vibration, low=0.0),
            bearing_temperature=bearing_temperature,
        )
        self._publish_residuals()
        return self.outputs


__all__ = ["HEALTH_KEY", "PrecalcinerModel", "RotaryKilnModel", "CoolerModel"]
