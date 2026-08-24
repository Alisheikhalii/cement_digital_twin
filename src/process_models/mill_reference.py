"""Mill reference point (PRD v1.1.1 Sections 10.1-10.3, 12.2).

The mill's counterpart to :mod:`src.process_models.kiln_reference`. The mill has no energy
closure to solve (PRD 10.2 mandates only a mass balance), so this is a direct derivation rather
than an iteration - but it is still the *single* place the reference values are computed, so
``MillModel`` and the Section 34 tests cannot disagree about what "reference" means.

Everything a gain is expressed as a deviation from lives here: the reference production rate
(feed minus bag-filter dust), the reference power draws, the reference specific power and the
reference currents.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from src.process_models import balances, electrical


@dataclass(frozen=True, slots=True)
class MillReferencePoint:
    """The nominal mill operating point every mill gain is a deviation from."""

    # -- material side ------------------------------------------------------------------
    feed_rate_tph: float
    clinker_feed_rate_tph: float
    gypsum_feed_rate_tph: float
    additive_feed_rate_tph: float
    cement_production_tph: float
    dust_loss_tph: float
    reject_recirculation_tph: float
    circulating_load_ratio: float
    mill_inventory_t: float
    residence_time_h: float
    # -- machine setpoints --------------------------------------------------------------
    separator_speed_rpm: float
    fan_speed_pct: float
    mill_speed_rpm: float
    # -- power / electrical -------------------------------------------------------------
    mill_motor_power_kW: float
    separator_power_kW: float
    fan_power_kW: float
    total_power_kW: float
    specific_power_kWh_per_t: float
    mill_current_A: float
    separator_current_A: float
    # -- gas / pressures ----------------------------------------------------------------
    gas_flow_Nm3_per_h: float
    mill_pressure_mbar: float
    separator_pressure_mbar: float
    differential_pressure_mbar: float
    # -- quality / temperatures ---------------------------------------------------------
    blaine_cm2_per_g: float
    residue_percent: float
    mill_outlet_temperature_C: float
    product_temperature_C: float
    ambient_temperature_C: float
    vibration_mm_per_s: float

    def as_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


def solve_reference_point(mill_config: Mapping[str, Any] | None = None) -> MillReferencePoint:
    """Derive the mill reference point from ``configs/mill_dynamics.yaml``.

    The one non-obvious step is the specific power: PRD 12.2's ``specific_power_consumption``
    tag (26-45 kWh/t) is a *circuit* figure, so it is the mill motor plus the separator plus the
    fan divided by the **net product** rate - not the mill motor alone divided by the feed rate.
    ``gains.mill_power.specific_power_kwh_t_ref`` is documented as mill-motor-only and is
    applied to the feed rate, which is the flow the mill actually grinds.
    """
    if mill_config is None:
        from src.config import MILL, load_config

        mill_config = load_config(MILL)

    ref = mill_config["reference"]
    mass_cfg = mill_config["mass_balance"]
    gains_cfg = mill_config["gains"]
    equipment_cfg = mill_config["equipment"]

    feed = float(ref["mill_feed_rate_tph"])
    separator_speed = float(ref["separator_speed_rpm"])
    fan_speed = float(ref["fan_speed_pct"])
    gas_flow = float(ref["gas_flow_Nm3_h"])
    outlet_temperature = float(ref["mill_outlet_temperature_C"])

    # -- material side (PRD 10.2 mass balance) -------------------------------------------
    dust_loss = feed * float(mass_cfg["dust_bag_filter_loss_fraction"])
    production = feed - dust_loss  # steady state: d(inventory)/dt = 0
    inventory = float(mass_cfg["mill_holdup_t"])
    residence_h = inventory / production if production > 1e-9 else 0.0
    circulating_load = float(gains_cfg["circulating_load"]["ratio_ref"])
    reject = production * circulating_load

    # -- power side ----------------------------------------------------------------------
    mill_power = feed * float(gains_cfg["mill_power"]["specific_power_kwh_t_ref"])
    separator_power = float(gains_cfg["separator_power"]["power_kW_ref"])
    fan_power = float(gains_cfg["fan_power"]["power_kW_ref"])
    total_power = mill_power + separator_power + fan_power
    specific_power = total_power / production if production > 1e-9 else 0.0

    mill_current = electrical.three_phase_current_A(
        mill_power,
        float(equipment_cfg["mill_motor_voltage_V"]),
        float(equipment_cfg["mill_power_factor"]),
    )
    separator_current = electrical.three_phase_current_A(
        separator_power,
        float(equipment_cfg["separator_motor_voltage_V"]),
        float(equipment_cfg["separator_power_factor"]),
    )

    outlet_offset = float(gains_cfg["mill_outlet_temperature"]["product_temperature_offset_K"])

    return MillReferencePoint(
        feed_rate_tph=feed,
        clinker_feed_rate_tph=feed * float(ref["clinker_feed_share"]),
        gypsum_feed_rate_tph=feed * float(ref["gypsum_feed_share"]),
        additive_feed_rate_tph=feed * float(ref["additive_feed_share"]),
        cement_production_tph=production,
        dust_loss_tph=dust_loss,
        reject_recirculation_tph=reject,
        circulating_load_ratio=circulating_load,
        mill_inventory_t=inventory,
        residence_time_h=residence_h,
        separator_speed_rpm=separator_speed,
        fan_speed_pct=fan_speed,
        mill_speed_rpm=float(ref["mill_speed_rpm"]),
        mill_motor_power_kW=mill_power,
        separator_power_kW=separator_power,
        fan_power_kW=fan_power,
        total_power_kW=total_power,
        specific_power_kWh_per_t=specific_power,
        mill_current_A=mill_current,
        separator_current_A=separator_current,
        gas_flow_Nm3_per_h=gas_flow,
        mill_pressure_mbar=float(gains_cfg["pressures"]["mill_pressure_mbar_ref"]),
        separator_pressure_mbar=float(gains_cfg["pressures"]["separator_pressure_mbar_ref"]),
        differential_pressure_mbar=float(ref["mill_differential_pressure_mbar"]),
        blaine_cm2_per_g=float(ref["simulated_blaine_cm2_g"]),
        residue_percent=float(ref["residue_percent"]),
        mill_outlet_temperature_C=outlet_temperature,
        product_temperature_C=outlet_temperature + outlet_offset,
        ambient_temperature_C=float(ref["ambient_temperature_C"]),
        vibration_mm_per_s=float(equipment_cfg["vibration_ref_mm_s"]),
    )


def consistency_report(
    reference: MillReferencePoint, mill_config: Mapping[str, Any] | None = None
) -> dict[str, float]:
    """Residuals and derived-vs-documented deltas used by the Section 34 mill tests."""
    if mill_config is None:
        from src.config import MILL, load_config

        mill_config = load_config(MILL)
    balance = balances.MillMassBalance(
        feed_rate_tph=reference.feed_rate_tph,
        cement_production_tph=reference.cement_production_tph,
        dust_loss_tph=reference.dust_loss_tph,
        inventory_change_tph=0.0,
        reject_recirculation_tph=reference.reject_recirculation_tph,
    )
    return {
        "mass_residual_pct": balance.residual_pct,
        "specific_power_kWh_per_t": reference.specific_power_kWh_per_t,
        "residence_time_min": reference.residence_time_h * balances.MINUTES_PER_HOUR,
        "mill_current_A": reference.mill_current_A,
        "separator_current_A": reference.separator_current_A,
        "feed_share_residual_tph": reference.feed_rate_tph
        - (
            reference.clinker_feed_rate_tph
            + reference.gypsum_feed_rate_tph
            + reference.additive_feed_rate_tph
        ),
    }


__all__ = ["MillReferencePoint", "solve_reference_point", "consistency_report"]
