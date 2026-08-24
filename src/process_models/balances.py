"""Enforced energy and mass balances (PRD v1.1.1 Sections 9.3, 10.2; NFR-10, AC-14).

These are the *only* implementations of the conservation equations. ``kiln_reference`` uses
them to solve the reference operating point, ``RotaryKilnModel``/``MillModel`` use them every
simulation step, and the Section 34 conservation tests assert on the residuals they report.
Nothing here holds state: the balances are pure functions of the current flows, so the twin
can never carry a second, divergent copy of them (Section 8.5).

Unit bookkeeping shortcuts used throughout (both exact, not approximations):

* ``t/h * kJ/(kg K) * K = MJ/h``      (1000 kg * kJ = MJ)
* ``t/h * 1000 * MJ/kg = MJ/h``
* ``Nm3/h * kJ/(Nm3 K) * K / 1000 = MJ/h``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

MINUTES_PER_HOUR = 60.0
SECONDS_PER_HOUR = 3600.0


def _residual_pct(residual: float, basis: float) -> float:
    """Residual as a percentage of the balance's input basis (0.0 when the basis is idle)."""
    if abs(float(basis)) <= 1e-9:
        return 0.0
    return 100.0 * float(residual) / float(basis)


# =============================================================================
# Kiln energy balance (PRD 9.3)
#   Fuel_Energy_Input + Recovered_Cooler_Heat
#       = Useful_Process_Heat + Exhaust_Gas_Loss + Radiation_Other_Loss + Unaccounted_Loss
# =============================================================================
@dataclass(frozen=True, slots=True)
class KilnEnergyBalance:
    """One evaluation of the kiln energy balance, all terms in MJ/h."""

    fuel_energy_input_MJ_per_h: float
    recovered_cooler_heat_MJ_per_h: float
    useful_process_heat_MJ_per_h: float
    exhaust_gas_loss_MJ_per_h: float
    radiation_other_loss_MJ_per_h: float

    @property
    def input_MJ_per_h(self) -> float:
        """Left-hand side: fuel energy plus heat recuperated from the cooler."""
        return self.fuel_energy_input_MJ_per_h + self.recovered_cooler_heat_MJ_per_h

    @property
    def accounted_output_MJ_per_h(self) -> float:
        return (
            self.useful_process_heat_MJ_per_h
            + self.exhaust_gas_loss_MJ_per_h
            + self.radiation_other_loss_MJ_per_h
        )

    @property
    def unaccounted_loss_MJ_per_h(self) -> float:
        """``residual = LHS - (Useful + Exhaust_Loss + Radiation_Loss)`` (PRD 9.3)."""
        return self.input_MJ_per_h - self.accounted_output_MJ_per_h

    @property
    def residual_pct(self) -> float:
        """Unaccounted loss as a percent of the energy input (the NFR-10 closure metric)."""
        return _residual_pct(self.unaccounted_loss_MJ_per_h, self.input_MJ_per_h)

    def as_dict(self) -> dict[str, float]:
        data: dict[str, float] = {key: float(value) for key, value in asdict(self).items()}
        data["input_MJ_per_h"] = self.input_MJ_per_h
        data["unaccounted_loss_MJ_per_h"] = self.unaccounted_loss_MJ_per_h
        data["residual_pct"] = self.residual_pct
        return data


def radiation_other_loss_MJ_per_h(fuel_energy_input_MJ_per_h: float, fraction: float) -> float:
    """``radiation_other_loss_fraction * Fuel_Energy_Input`` (PRD 9.3, ASSUMPTION 0.06)."""
    return float(fuel_energy_input_MJ_per_h) * float(fraction)


def cooler_available_heat_MJ_per_h(
    clinker_production_tph: float,
    clinker_exit_temperature_C: float,
    ambient_temperature_C: float,
    cp_clinker_kJ_per_kgK: float,
) -> float:
    """Sensible heat carried into the cooler by hot clinker leaving the kiln (PRD 9.3)."""
    delta_T = float(clinker_exit_temperature_C) - float(ambient_temperature_C)
    return max(0.0, float(clinker_production_tph) * float(cp_clinker_kJ_per_kgK) * delta_T)


def recovered_cooler_heat_MJ_per_h(available_heat_MJ_per_h: float, recovery_fraction: float) -> float:
    """``cooler_heat_recovery_fraction * Cooler_Available_Heat`` (PRD 9.3, ASSUMPTION 0.75)."""
    return float(available_heat_MJ_per_h) * float(recovery_fraction)


def useful_process_heat_MJ_per_h(
    *,
    feed_rate_tph: float,
    clinker_production_tph: float,
    raw_meal_moisture_pct: float,
    raw_meal_temperature_C: float,
    calciner_temperature_C: float,
    clinker_exit_temperature_C: float,
    energy_config: Mapping[str, Any],
) -> float:
    """Clinker-formation enthalpy plus the lumped sensible/evaporation terms (PRD 9.3).

    The lumped reduced-order term of PRD 9.3 is resolved into three auditable parts: heating
    the raw meal from its inlet temperature to calciner outlet temperature, heating the
    resulting clinker from there to its kiln exit temperature, and evaporating the residual
    raw-meal moisture. The clinker sensible heat is not lost here - 75 % of it returns on the
    input side as ``Recovered_Cooler_Heat``.
    """
    formation = (
        float(clinker_production_tph) * 1000.0 * float(energy_config["clinker_formation_MJ_per_kg"])
    )
    preheating = (
        float(feed_rate_tph)
        * float(energy_config["cp_raw_meal_kJ_per_kgK"])
        * (float(calciner_temperature_C) - float(raw_meal_temperature_C))
    )
    kiln_heating = (
        float(clinker_production_tph)
        * float(energy_config["cp_clinker_kJ_per_kgK"])
        * (float(clinker_exit_temperature_C) - float(calciner_temperature_C))
    )
    evaporation = (
        float(feed_rate_tph)
        * (float(raw_meal_moisture_pct) / 100.0)
        * 1000.0
        * float(energy_config["water_evaporation_MJ_per_kg"])
    )
    return formation + preheating + kiln_heating + evaporation


def exhaust_gas_loss_MJ_per_h(
    exhaust_gas_flow_Nm3_per_h: float,
    preheater_outlet_temperature_C: float,
    ambient_temperature_C: float,
    cp_exhaust_gas_kJ_per_Nm3K: float,
) -> float:
    """``f(exhaust_gas_flow, preheater_outlet_temperature)`` (PRD 9.3)."""
    delta_T = float(preheater_outlet_temperature_C) - float(ambient_temperature_C)
    return float(exhaust_gas_flow_Nm3_per_h) * float(cp_exhaust_gas_kJ_per_Nm3K) * delta_T / 1000.0


def preheater_outlet_temperature_from_energy(
    energy_available_MJ_per_h: float,
    exhaust_gas_flow_Nm3_per_h: float,
    ambient_temperature_C: float,
    cp_exhaust_gas_kJ_per_Nm3K: float,
    minimum_temperature_C: float,
) -> float:
    """Invert :func:`exhaust_gas_loss_MJ_per_h` for the gas temperature (PRD 9.3 closure).

    This is what makes the balance *enforced* rather than merely reported: whatever energy is
    not consumed by the process or lost to radiation must leave with the exhaust gas, and the
    preheater outlet temperature is the state variable that carries it.
    """
    heat_capacity_rate = float(exhaust_gas_flow_Nm3_per_h) * float(cp_exhaust_gas_kJ_per_Nm3K)
    if heat_capacity_rate <= 1e-9:
        return float(minimum_temperature_C)
    temperature = float(ambient_temperature_C) + float(energy_available_MJ_per_h) * 1000.0 / heat_capacity_rate
    return max(float(minimum_temperature_C), temperature)


# =============================================================================
# Kiln mass balance (PRD 9.3)
#   Kiln_Feed = Clinker_Production + LOI_Loss + Dust_Loss + d(Kiln_Inventory)/dt
# =============================================================================
@dataclass(frozen=True, slots=True)
class KilnMassBalance:
    """One evaluation of the kiln mass balance, all terms in t/h."""

    feed_rate_tph: float
    clinker_production_tph: float
    LOI_loss_tph: float
    dust_loss_tph: float
    inventory_change_tph: float

    @property
    def accounted_output_tph(self) -> float:
        return (
            self.clinker_production_tph
            + self.LOI_loss_tph
            + self.dust_loss_tph
            + self.inventory_change_tph
        )

    @property
    def residual_tph(self) -> float:
        return self.feed_rate_tph - self.accounted_output_tph

    @property
    def residual_pct(self) -> float:
        return _residual_pct(self.residual_tph, self.feed_rate_tph)

    def as_dict(self) -> dict[str, float]:
        data: dict[str, float] = {key: float(value) for key, value in asdict(self).items()}
        data["residual_tph"] = self.residual_tph
        data["residual_pct"] = self.residual_pct
        return data


@dataclass(frozen=True, slots=True)
class CalcinationGas:
    """Gas released by calcination and raw-meal drying (Nm3/h), from the LOI mass flow."""

    CO2_Nm3_per_h: float
    H2O_Nm3_per_h: float

    @property
    def total_Nm3_per_h(self) -> float:
        return self.CO2_Nm3_per_h + self.H2O_Nm3_per_h


def calcination_gas(
    feed_rate_tph: float,
    raw_meal_moisture_pct: float,
    mass_config: Mapping[str, Any],
) -> CalcinationGas:
    """Calcination CO2 + H2O vapour released per hour (PRD 9.3 mass balance, gas side).

    Shared by the O2/CO2 dilution terms of ``FanFuelModel`` and the exhaust-flow term of
    ``PreheaterModel`` so the gas volumes are derived exactly once.
    """
    loi_rate_tph = float(feed_rate_tph) * float(mass_config["LOI_loss_fraction"])
    co2_share = float(mass_config["LOI_CO2_mass_share"])
    co2_mass_tph = loi_rate_tph * co2_share
    water_mass_tph = loi_rate_tph * (1.0 - co2_share) + float(feed_rate_tph) * (
        float(raw_meal_moisture_pct) / 100.0
    )
    co2_volume = co2_mass_tph * 1000.0 / float(mass_config["CO2_density_kg_per_Nm3"])
    water_volume = water_mass_tph * 1000.0 / float(mass_config["H2O_vapour_density_kg_per_Nm3"])
    return CalcinationGas(CO2_Nm3_per_h=co2_volume, H2O_Nm3_per_h=water_volume)


@dataclass(frozen=True, slots=True)
class BackEndGasFlows:
    """The three gas volumes the kiln gas side is expressed in (Nm3/h).

    * ``back_end_Nm3_per_h``     - process gas at the kiln inlet / back end, where the O2 and CO
      analysers sit: combustion air plus calcination CO2 plus water vapour.
    * ``dry_back_end_Nm3_per_h`` - the same stream on a dry basis (the analyser's basis).
    * ``exhaust_Nm3_per_h``      - after false-air ingress across the preheater tower, i.e. what
      the ID fan and the stack actually see.
    """

    back_end_Nm3_per_h: float
    dry_back_end_Nm3_per_h: float
    exhaust_Nm3_per_h: float


def back_end_gas_flows(
    combustion_air_Nm3_per_h: float,
    calcination_CO2_Nm3_per_h: float,
    calcination_H2O_Nm3_per_h: float,
    false_air_fraction: float,
) -> BackEndGasFlows:
    """Derive the back-end, dry-back-end and exhaust gas volumes exactly once (PRD 9.3/9.4).

    Both ``FanFuelModel`` (O2/CO2 dilution, ID fan power) and ``PreheaterModel`` (exhaust flow,
    tower pressure) need these; deriving them here keeps the false-air convention - ingress is
    downstream of the back-end analyser - in a single place.
    """
    back_end = (
        max(0.0, float(combustion_air_Nm3_per_h))
        + max(0.0, float(calcination_CO2_Nm3_per_h))
        + max(0.0, float(calcination_H2O_Nm3_per_h))
    )
    return BackEndGasFlows(
        back_end_Nm3_per_h=back_end,
        dry_back_end_Nm3_per_h=max(0.0, back_end - max(0.0, float(calcination_H2O_Nm3_per_h))),
        exhaust_Nm3_per_h=back_end * (1.0 + float(false_air_fraction)),
    )


def clinker_discharge_tph(kiln_inventory_t: float, residence_time_h: float) -> float:
    """``Clinker_Discharge_Rate = Kiln_Inventory / kiln_residence_time_h`` (PRD 9.3)."""
    if float(residence_time_h) <= 0.0:
        raise ValueError("kiln_residence_time_h must be > 0")
    return max(0.0, float(kiln_inventory_t)) / float(residence_time_h)


# =============================================================================
# Mill mass balance (PRD 10.2)
#   Mill_Feed = Cement_Production + Dust_Bag_Filter_Loss + d(Mill_Inventory)/dt
#   (Reject_Recirculation is internal to the closed circuit - PRD 10.2: "not a true loss")
# =============================================================================
@dataclass(frozen=True, slots=True)
class MillMassBalance:
    """One evaluation of the mill mass balance, all terms in t/h."""

    feed_rate_tph: float
    cement_production_tph: float
    dust_loss_tph: float
    inventory_change_tph: float
    reject_recirculation_tph: float = 0.0  # reported for transparency, not part of the closure

    @property
    def accounted_output_tph(self) -> float:
        return self.cement_production_tph + self.dust_loss_tph + self.inventory_change_tph

    @property
    def residual_tph(self) -> float:
        return self.feed_rate_tph - self.accounted_output_tph

    @property
    def residual_pct(self) -> float:
        return _residual_pct(self.residual_tph, self.feed_rate_tph)

    def as_dict(self) -> dict[str, float]:
        data: dict[str, float] = {key: float(value) for key, value in asdict(self).items()}
        data["residual_tph"] = self.residual_tph
        data["residual_pct"] = self.residual_pct
        return data


__all__ = [
    "MINUTES_PER_HOUR",
    "SECONDS_PER_HOUR",
    "KilnEnergyBalance",
    "KilnMassBalance",
    "CalcinationGas",
    "BackEndGasFlows",
    "MillMassBalance",
    "radiation_other_loss_MJ_per_h",
    "cooler_available_heat_MJ_per_h",
    "recovered_cooler_heat_MJ_per_h",
    "useful_process_heat_MJ_per_h",
    "exhaust_gas_loss_MJ_per_h",
    "preheater_outlet_temperature_from_energy",
    "calcination_gas",
    "back_end_gas_flows",
    "clinker_discharge_tph",
]
