"""Cement mill units: fan/filter, mill, separator, product (PRD v1.1.1 Sections 8.3, 10).

``MillModel`` is the unit PRD 8.3 designates as the owner of the mill mass closure, and it
enforces PRD 10.2 exactly at every step, load change included:

``Mill_Feed = Cement_Production + Dust_Bag_Filter_Loss + d(Mill_Inventory)/dt``

Reject recirculation is *internal* to the closed circuit (PRD 10.2: "not a true loss"), so it
is reported on the balance for transparency but is not a term of the closure. It does have a
physical effect, and it is applied where a closed circuit actually shows it: a larger
circulating load means more material inside the circuit at any instant, so the mill-inventory
time constant scales with ``(1 + circulating_load)``. Fineness classification therefore moves
the mill's loading, differential pressure and specific power - while the *net* product rate
stays fixed by conservation at ``feed - dust``, which is what a mass balance demands.

The two discretization choices are the same as the kiln's (see :mod:`kiln_core`): the
``feed_to_production`` dead time is physical pipe inventory rather than a signal delay, and
the inventory ODE is integrated backward Euler, so ``(I_new - I)/dt = inflow - discharge``
holds exactly and the discretization cannot manufacture a residual.

PRD 10.2 defines a mass closure only - the mill has no energy balance - so these units
publish ``mass_pct`` on ``balance_residuals`` and deliberately do not fabricate an
``energy_pct`` of zero.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.process_models import balances, electrical, gains
from src.process_models.interfaces import UnitBase
from src.process_models.mill_reference import MillReferencePoint, solve_reference_point
from src.simulation.delays import DelayBank, build_delay_bank

#: Key under which the mill drive's health scalar (0-1) is published by the data generator
#: (PRD 9.5 applies to both units). Health is driven from outside the twin, so the twin
#: itself stays deterministic.
HEALTH_KEY = "mill"

#: The three component feed tags of PRD 12.2, in the order their shares are configured.
FEED_COMPONENT_TAGS = ("clinker_feed_rate", "gypsum_feed_rate", "additive_feed_rate")


def mill_context(
    mill_config: Mapping[str, Any] | None = None,
    reference: MillReferencePoint | None = None,
) -> tuple[Mapping[str, Any], MillReferencePoint]:
    """Load the mill config and its derived reference point (shared by every mill unit)."""
    if mill_config is None:
        from src.config import MILL, load_config

        mill_config = load_config(MILL)
    if reference is None:
        reference = solve_reference_point(mill_config)
    return mill_config, reference


class FanFilterModel(UnitBase):
    """Circulation fan and bag filter: gas flow, fan power and the circuit draughts (PRD 8.3).

    One relationship, ``fan_to_pressure``, carries the fan's draught; the mill and separator
    gauge pressures are both derived from that single delayed mechanism rather than given a
    delay each, because physically they are two tappings on one draught (AC-15).
    """

    __slots__ = ("_cfg", "_delays", "_ref")

    def __init__(
        self,
        mill_config: Mapping[str, Any] | None = None,
        reference: MillReferencePoint | None = None,
        name: str = "FanFilter",
    ) -> None:
        super().__init__(name)
        mill_config, reference = mill_context(mill_config, reference)
        self._cfg = mill_config
        self._ref = reference
        self._delays: DelayBank = build_delay_bank(mill_config)
        self.constraints = {
            "fan_speed": tuple(mill_config["operating_ranges"]["fan_speed_pct"]),
        }
        self.reset()

    def reset(self) -> None:
        ref = self._ref
        self.inputs = {"fan_speed_pct": ref.fan_speed_pct}
        self._delays.settle_all(
            {
                "fan_to_gas_flow": ref.gas_flow_Nm3_per_h,
                "load_to_electrical": ref.fan_power_kW,
                # The draught row carries the dimensionless fan factor, so it settles at 1.0.
                "fan_to_pressure": 1.0,
            }
        )
        self.state = {
            "gas_flow_Nm3_per_h": ref.gas_flow_Nm3_per_h,
            "draught_factor": 1.0,
        }
        self.outputs = {
            "fan_speed": ref.fan_speed_pct,
            "gas_flow": ref.gas_flow_Nm3_per_h,
            "fan_power_kw": ref.fan_power_kW,
            "mill_pressure": ref.mill_pressure_mbar,
            "separator_pressure": ref.separator_pressure_mbar,
        }

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        gains_cfg = self._cfg["gains"]
        pressure_gains = gains_cfg["pressures"]

        fan_speed = self.input_value("fan_speed_pct", "fan_speed", default=ref.fan_speed_pct)

        gas_flow = self._delays.step(
            "fan_to_gas_flow",
            ref.gas_flow_Nm3_per_h
            * gains.power_law(
                fan_speed, ref.fan_speed_pct, float(gains_cfg["gas_flow"]["speed_exponent"])
            ),
            dt_seconds,
        )
        fan_power = self._delays.step(
            "load_to_electrical",
            float(gains_cfg["fan_power"]["power_kW_ref"])
            * gains.power_law(
                fan_speed, ref.fan_speed_pct, float(gains_cfg["fan_power"]["speed_exponent"])
            ),
            dt_seconds,
        )
        draught_factor = self._delays.step(
            "fan_to_pressure",
            gains.power_law(fan_speed, ref.fan_speed_pct, float(pressure_gains["fan_exponent"])),
            dt_seconds,
        )

        self.state.update(gas_flow_Nm3_per_h=gas_flow, draught_factor=draught_factor)
        self.outputs.update(
            fan_speed=fan_speed,
            gas_flow=gains.clamp(gas_flow, low=0.0),
            fan_power_kw=gains.clamp(fan_power, low=0.0),
            mill_pressure=float(pressure_gains["mill_pressure_mbar_ref"]) * draught_factor,
            separator_pressure=float(pressure_gains["separator_pressure_mbar_ref"])
            * draught_factor,
        )
        return self.outputs


class MillModel(UnitBase):
    """The mill itself, and the owner of the PRD 10.2 mass closure (PRD 8.3).

    Signals it receives from the rest of the circuit - the gas flow from ``FanFilterModel`` and
    the Blaine and circulating load from ``SeparatorModel`` - are one step old, which is what a
    discrete plant model physically is; at steady state they are exactly consistent with what
    this unit publishes.
    """

    __slots__ = ("_cfg", "_delays", "_mass_balance", "_ref")

    def __init__(
        self,
        mill_config: Mapping[str, Any] | None = None,
        reference: MillReferencePoint | None = None,
        name: str = "Mill",
    ) -> None:
        super().__init__(name)
        mill_config, reference = mill_context(mill_config, reference)
        self._cfg = mill_config
        self._ref = reference
        self._delays: DelayBank = build_delay_bank(mill_config)
        self._mass_balance = self._reference_balance()
        self.constraints = {
            "mill_feed_rate_tph": tuple(mill_config["operating_ranges"]["mill_feed_rate_tph"]),
            "mill_differential_pressure": (20.0, 90.0),  # PRD 12.2 band
        }
        self.reset()

    # -- last evaluated closure (read by the Section 34 conservation tests) ----------------
    @property
    def mass_balance(self) -> balances.MillMassBalance:
        return self._mass_balance

    def _reference_balance(self) -> balances.MillMassBalance:
        ref = self._ref
        return balances.MillMassBalance(
            feed_rate_tph=ref.feed_rate_tph,
            cement_production_tph=ref.cement_production_tph,
            dust_loss_tph=ref.dust_loss_tph,
            inventory_change_tph=0.0,
            reject_recirculation_tph=ref.reject_recirculation_tph,
        )

    def _publish_residuals(self) -> None:
        """Expose the mass closure on the PRD 8.4 ``balance_residuals`` attribute.

        No ``energy_pct`` key: PRD 10.2 mandates a mass balance only for the mill, and a
        fabricated zero would be indistinguishable from a closed energy balance.
        """
        self.balance_residuals = {
            "mass_pct": self._mass_balance.residual_pct,
            "mass_residual_tph": self._mass_balance.residual_tph,
        }


    def reset(self) -> None:
        ref = self._ref
        # Material that has left the feeders but not yet reached the grinding chamber is real
        # inventory, not a signal delay - see the module docstring and PRD 10.2.
        transit_h = self._delays.dead_time_s("feed_to_production") / balances.SECONDS_PER_HOUR
        self.inputs = {
            "mill_feed_rate_tph": ref.feed_rate_tph,
            "mill_speed_rpm": ref.mill_speed_rpm,
            "gas_flow_Nm3_per_h": ref.gas_flow_Nm3_per_h,
            "simulated_blaine_cm2_g": ref.blaine_cm2_per_g,
            "circulating_load_ratio": ref.circulating_load_ratio,
        }
        self._delays.settle_all(
            {
                "feed_to_production": ref.feed_rate_tph,
                "feed_to_mill_power": ref.mill_motor_power_kW,
                "feed_to_differential_pressure": ref.differential_pressure_mbar,
                "power_to_outlet_temperature": ref.mill_outlet_temperature_C,
                "load_to_electrical": ref.mill_current_A,
                "load_to_vibration": ref.vibration_mm_per_s,
            }
        )
        self.health = {HEALTH_KEY: float(self._cfg["equipment"]["health"]["initial"])}
        self.state = {
            "mill_inventory_t": ref.mill_inventory_t,
            "inventory_in_transit_t": ref.feed_rate_tph * transit_h,
            "residence_time_h": ref.residence_time_h,
            "mill_motor_power_kW": ref.mill_motor_power_kW,
            "specific_mill_power_kWh_per_t": float(
                self._cfg["gains"]["mill_power"]["specific_power_kwh_t_ref"]
            ),
            "dust_loss_tph": ref.dust_loss_tph,
        }
        self.outputs = {
            "mill_feed_rate_tph": ref.feed_rate_tph,
            "clinker_feed_rate": ref.clinker_feed_rate_tph,
            "gypsum_feed_rate": ref.gypsum_feed_rate_tph,
            "additive_feed_rate": ref.additive_feed_rate_tph,
            "mill_speed": ref.mill_speed_rpm,
            "mill_motor_power_kw": ref.mill_motor_power_kW,
            "mill_current": ref.mill_current_A,
            "mill_differential_pressure": ref.differential_pressure_mbar,
            "mill_outlet_temperature": ref.mill_outlet_temperature_C,
            "mill_vibration": ref.vibration_mm_per_s,
            "cement_production_tph": ref.cement_production_tph,
        }
        self._mass_balance = self._reference_balance()
        self._publish_residuals()


    def _feed_components(self) -> tuple[float, float, float, float]:
        """Resolve the four PRD 10.1 feed inputs into one consistent set.

        A caller may drive the total (``mill_feed_rate_tph``) or the three components; whichever
        it actually sets wins, and the other side is derived from the reference shares. That
        keeps ``clinker + gypsum + additive == mill_feed_rate_tph`` true at all times, so the
        mass balance has a single unambiguous feed input.
        """
        ref = self._ref
        total = self.input_value(
            "mill_feed_rate_tph", "mill_feed_rate", default=ref.feed_rate_tph
        )
        shares = (
            ref.clinker_feed_rate_tph / ref.feed_rate_tph,
            ref.gypsum_feed_rate_tph / ref.feed_rate_tph,
            ref.additive_feed_rate_tph / ref.feed_rate_tph,
        )
        components = [
            self.input_value(tag, f"{tag}_tph", default=share * total)
            for tag, share in zip(FEED_COMPONENT_TAGS, shares)
        ]
        if any(tag in self.inputs or f"{tag}_tph" in self.inputs for tag in FEED_COMPONENT_TAGS):
            total = sum(components)
        return total, components[0], components[1], components[2]

    # -- dynamics --------------------------------------------------------------------------
    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        gains_cfg = self._cfg["gains"]
        mass_cfg = self._cfg["mass_balance"]
        equipment_cfg = self._cfg["equipment"]
        dt_h = float(dt_seconds) / balances.SECONDS_PER_HOUR

        feed, clinker_feed, gypsum_feed, additive_feed = self._feed_components()
        mill_speed = self.input_value("mill_speed_rpm", "mill_speed", default=ref.mill_speed_rpm)
        gas_flow = self.input_value(
            "gas_flow_Nm3_per_h", "gas_flow", default=ref.gas_flow_Nm3_per_h
        )
        blaine = self.input_value(
            "simulated_blaine_cm2_g", "blaine_cm2_per_g", default=ref.blaine_cm2_per_g
        )
        circulating_load = self.input_value(
            "circulating_load_ratio", default=ref.circulating_load_ratio
        )
        health = gains.clamp(self.health.get(HEALTH_KEY, 1.0), 0.0, 1.0)

        # -- mass balance (PRD 10.2): exact at every step, load change included -------------
        # A larger circulating load holds more material inside the closed circuit, so the
        # inventory time constant scales with it; the *net* product rate stays feed - dust,
        # which is what conservation requires (see the module docstring).
        residence_h = max(
            1e-9,
            ref.residence_time_h
            * (1.0 + max(0.0, circulating_load))
            / (1.0 + ref.circulating_load_ratio),
        )
        # `feed_to_production` is configured with tau_min: null, so it is a pure transport
        # queue; the lag comes from the physical mill-inventory buffer below.
        arrival = self._delays.step("feed_to_production", feed, dt_seconds)
        previous_transit = float(self.state["inventory_in_transit_t"])
        in_transit = previous_transit + (feed - arrival) * dt_h
        dust_loss = arrival * float(mass_cfg["dust_bag_filter_loss_fraction"])
        bed_inflow = arrival - dust_loss
        previous_inventory = float(self.state["mill_inventory_t"])
        # Backward Euler: (I_new - I)/dt == inflow - I_new/tau holds exactly, so the
        # discretization cannot manufacture a conservation residual.
        inventory = (previous_inventory + bed_inflow * dt_h) / (1.0 + dt_h / residence_h)
        production = max(0.0, inventory) / residence_h
        inventory_change = (
            (inventory - previous_inventory) + (in_transit - previous_transit)
        ) / dt_h
        self._mass_balance = balances.MillMassBalance(
            feed_rate_tph=feed,
            cement_production_tph=production,
            dust_loss_tph=dust_loss,
            inventory_change_tph=inventory_change,
            reject_recirculation_tph=production * max(0.0, circulating_load),
        )

        # -- grinding power (PRD 10.3, Bond-work-index-inspired) ----------------------------
        power_gains = gains_cfg["mill_power"]
        specific_power_ref = float(power_gains["specific_power_kwh_t_ref"])
        specific_mill_power = specific_power_ref * gains.power_law(
            blaine, ref.blaine_cm2_per_g, float(power_gains["blaine_exponent"])
        )
        mill_power = self._delays.step(
            "feed_to_mill_power", feed * specific_mill_power, dt_seconds
        )

        # -- mill loading -> differential pressure (PRD 10.3) -------------------------------
        dp_gains = gains_cfg["differential_pressure"]
        differential_pressure = self._delays.step(
            "feed_to_differential_pressure",
            ref.differential_pressure_mbar
            * gains.power_law(
                inventory, ref.mill_inventory_t, float(dp_gains["inventory_exponent"])
            )
            * gains.power_law(
                gas_flow, ref.gas_flow_Nm3_per_h, float(dp_gains["gas_flow_exponent"])
            ),
            dt_seconds,
        )

        # -- grinding heat -> outlet temperature (PRD 10.3) ---------------------------------
        temperature_gains = gains_cfg["mill_outlet_temperature"]
        outlet_temperature = self._delays.step(
            "power_to_outlet_temperature",
            ref.mill_outlet_temperature_C
            + float(temperature_gains["K_per_pct_specific_power"])
            * gains.relative_pct(specific_mill_power, specific_power_ref)
            + float(temperature_gains["K_per_pct_gas_flow"])
            * gains.relative_pct(max(1e-6, gas_flow), ref.gas_flow_Nm3_per_h),
            dt_seconds,
        )

        # -- drive electrical and health-driven equipment signals (PRD 9.5) -----------------
        load = feed / ref.feed_rate_tph
        mill_current = self._delays.step(
            "load_to_electrical",
            electrical.three_phase_current_A(
                mill_power,
                float(equipment_cfg["mill_motor_voltage_V"]),
                float(equipment_cfg["mill_power_factor"]),
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

        self.state.update(
            mill_inventory_t=inventory,
            inventory_in_transit_t=in_transit,
            residence_time_h=residence_h,
            mill_motor_power_kW=mill_power,
            specific_mill_power_kWh_per_t=specific_mill_power,
            dust_loss_tph=dust_loss,
        )
        self.outputs.update(
            mill_feed_rate_tph=feed,
            clinker_feed_rate=clinker_feed,
            gypsum_feed_rate=gypsum_feed,
            additive_feed_rate=additive_feed,
            mill_speed=mill_speed,
            mill_motor_power_kw=gains.clamp(mill_power, low=0.0),
            mill_current=gains.clamp(mill_current, low=0.0),
            mill_differential_pressure=differential_pressure,
            mill_outlet_temperature=outlet_temperature,
            mill_vibration=gains.clamp(vibration, low=0.0),
            cement_production_tph=production,
        )
        self._publish_residuals()
        return self.outputs


class SeparatorModel(UnitBase):
    """Dynamic separator: fineness, sieve residue, circulating load and its own drive (PRD 8.3).

    Two relationships of PRD 10.3 live here: ``separator_to_blaine`` (classification transport)
    and ``separator_to_throughput``, which carries the *reject fraction* - the quantity PRD 10.2
    describes as internal to the circuit. ``residue_percent`` is derived from the already
    delayed Blaine rather than given a delay of its own: it is the same classification measured
    on a different instrument, so a second time constant would be an invented dynamic.
    """

    __slots__ = ("_cfg", "_delays", "_ref")

    def __init__(
        self,
        mill_config: Mapping[str, Any] | None = None,
        reference: MillReferencePoint | None = None,
        name: str = "Separator",
    ) -> None:
        super().__init__(name)
        mill_config, reference = mill_context(mill_config, reference)
        self._cfg = mill_config
        self._ref = reference
        self._delays: DelayBank = build_delay_bank(mill_config)
        self.constraints = {
            "separator_speed_rpm": tuple(mill_config["operating_ranges"]["separator_speed_rpm"]),
            "simulated_blaine_cm2_g": (2900.0, 4200.0),  # PRD 12.2 band
            "residue_percent": (6.0, 18.0),  # PRD 12.2 band
        }
        self.reset()

    def reset(self) -> None:
        ref = self._ref
        self.inputs = {
            "separator_speed_rpm": ref.separator_speed_rpm,
            "mill_feed_rate_tph": ref.feed_rate_tph,
            "gas_flow_Nm3_per_h": ref.gas_flow_Nm3_per_h,
            "cement_production_tph": ref.cement_production_tph,
        }
        self._delays.settle_all(
            {
                "separator_to_blaine": ref.blaine_cm2_per_g,
                "separator_to_throughput": ref.circulating_load_ratio,
                "load_to_electrical": ref.separator_power_kW,
            }
        )
        self.state = {
            "separator_power_kW": ref.separator_power_kW,
            "circulating_load_ratio": ref.circulating_load_ratio,
            "reject_recirculation_tph": ref.reject_recirculation_tph,
        }
        self.outputs = {
            "separator_speed_rpm": ref.separator_speed_rpm,
            "simulated_blaine_cm2_g": ref.blaine_cm2_per_g,
            "residue_percent": ref.residue_percent,
            "separator_current": ref.separator_current_A,
        }


    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        gains_cfg = self._cfg["gains"]
        equipment_cfg = self._cfg["equipment"]

        separator_speed = self.input_value(
            "separator_speed_rpm", "separator_speed", default=ref.separator_speed_rpm
        )
        feed = self.input_value(
            "mill_feed_rate_tph", "mill_feed_rate", default=ref.feed_rate_tph
        )
        gas_flow = self.input_value(
            "gas_flow_Nm3_per_h", "gas_flow", default=ref.gas_flow_Nm3_per_h
        )
        production = self.input_value(
            "cement_production_tph", default=ref.cement_production_tph
        )

        # -- fineness (PRD 10.3/10.4: the throughput/fineness trade-off) ---------------------
        blaine_gains = gains_cfg["blaine"]
        blaine = self._delays.step(
            "separator_to_blaine",
            ref.blaine_cm2_per_g
            + float(blaine_gains["per_pct_separator_speed"])
            * gains.relative_pct(separator_speed, ref.separator_speed_rpm)
            + float(blaine_gains["per_pct_mill_feed"]) * gains.relative_pct(feed, ref.feed_rate_tph)
            + float(blaine_gains["per_pct_gas_flow"])
            * gains.relative_pct(max(1e-6, gas_flow), ref.gas_flow_Nm3_per_h),
            dt_seconds,
        )
        blaine = gains.clamp(blaine, low=1.0)
        residue = ref.residue_percent * gains.power_law(
            ref.blaine_cm2_per_g, blaine, float(gains_cfg["residue"]["exponent"])
        )

        # -- classification loop: reject fraction (PRD 10.2 - internal to the circuit) -------
        load_gains = gains_cfg["circulating_load"]
        circulating_load = self._delays.step(
            "separator_to_throughput",
            float(load_gains["ratio_ref"])
            * gains.power_law(
                separator_speed,
                ref.separator_speed_rpm,
                float(load_gains["separator_speed_exponent"]),
            ),
            dt_seconds,
        )
        circulating_load = gains.clamp(circulating_load, low=0.0)

        # -- separator drive (PRD 10.3 rotor power law) --------------------------------------
        power_gains = gains_cfg["separator_power"]
        separator_power = self._delays.step(
            "load_to_electrical",
            float(power_gains["power_kW_ref"])
            * gains.power_law(
                separator_speed, ref.separator_speed_rpm, float(power_gains["speed_exponent"])
            ),
            dt_seconds,
        )
        separator_current = electrical.three_phase_current_A(
            separator_power,
            float(equipment_cfg["separator_motor_voltage_V"]),
            float(equipment_cfg["separator_power_factor"]),
        )

        self.state.update(
            separator_power_kW=gains.clamp(separator_power, low=0.0),
            circulating_load_ratio=circulating_load,
            reject_recirculation_tph=max(0.0, production) * circulating_load,
        )
        self.outputs.update(
            separator_speed_rpm=separator_speed,
            simulated_blaine_cm2_g=blaine,
            residue_percent=residue,
            separator_current=separator_current,
        )
        return self.outputs


class ProductModel(UnitBase):
    """Finished product: temperature after transport and the circuit's specific power (PRD 8.3).

    ``specific_power_consumption_kwh_t`` is a *circuit* figure - mill motor plus separator plus
    fan divided by the net product rate (PRD 12.2, 26-45 kWh/t) - and this is the only place it
    is formed, so the tag and the optimizer's energy objective can never disagree (Section 8.5).
    That the fan and separator draws are largely fixed while the mill draw scales with feed is
    exactly why specific power falls as throughput rises (PRD 10.4).

    No delay row of its own: the product temperature is the mill outlet temperature, which has
    already been through ``power_to_outlet_temperature``, shifted by the configured transport
    offset.
    """

    __slots__ = ("_cfg", "_ref")

    def __init__(
        self,
        mill_config: Mapping[str, Any] | None = None,
        reference: MillReferencePoint | None = None,
        name: str = "Product",
    ) -> None:
        super().__init__(name)
        mill_config, reference = mill_context(mill_config, reference)
        self._cfg = mill_config
        self._ref = reference
        self.constraints = {
            "specific_power_consumption_kwh_t": (26.0, 45.0),  # PRD 12.2 band
        }
        self.reset()

    def reset(self) -> None:
        ref = self._ref
        self.inputs = {
            "cement_production_tph": ref.cement_production_tph,
            "mill_outlet_temperature": ref.mill_outlet_temperature_C,
            "mill_motor_power_kw": ref.mill_motor_power_kW,
            "separator_power_kW": ref.separator_power_kW,
            "fan_power_kw": ref.fan_power_kW,
        }
        self.state = {
            "total_power_kW": ref.total_power_kW,
        }
        self.outputs = {
            "product_temperature": ref.product_temperature_C,
            "specific_power_consumption_kwh_t": ref.specific_power_kWh_per_t,
        }

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        self.merge_inputs(inputs)
        ref = self._ref
        offset = float(
            self._cfg["gains"]["mill_outlet_temperature"]["product_temperature_offset_K"]
        )

        production = self.input_value("cement_production_tph", default=ref.cement_production_tph)
        outlet_temperature = self.input_value(
            "mill_outlet_temperature",
            "mill_outlet_temperature_C",
            default=ref.mill_outlet_temperature_C,
        )
        total_power = (
            self.input_value("mill_motor_power_kw", default=ref.mill_motor_power_kW)
            + self.input_value("separator_power_kW", default=ref.separator_power_kW)
            + self.input_value("fan_power_kw", default=ref.fan_power_kW)
        )
        specific_power = total_power / production if production > 1e-9 else 0.0

        self.state.update(total_power_kW=total_power)
        self.outputs.update(
            product_temperature=outlet_temperature + offset,
            specific_power_consumption_kwh_t=specific_power,
        )
        return self.outputs


__all__ = [
    "HEALTH_KEY",
    "FEED_COMPONENT_TAGS",
    "mill_context",
    "FanFilterModel",
    "MillModel",
    "SeparatorModel",
    "ProductModel",
]
