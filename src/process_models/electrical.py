"""Motor and fan electrical relationships (PRD v1.1.1 Sections 9.5, 10.3, 12.1, 12.2).

The equipment tags of PRD 12.1/12.2 (``ID_fan_power``, ``ID_fan_current``,
``kiln_motor_current``, ``mill_current``, ``separator_current``, ``fan_power_kw``) are not
independent signals: each is derived from the process load the unit is already carrying. These
are the shared derivations so a current is never computed one way in the kiln and another way
in the mill.

Two points of physics that the reduced-order form must respect:

* A fan moves **actual** volume, not normal volume. Preheater exhaust leaves at ~360 C, so its
  actual volumetric flow is ~2.3x its Nm3/h value; the ID fan's shaft power follows the actual
  flow (:func:`normal_to_actual_m3_per_h`, :func:`fan_shaft_power_kW`).
* Motor current is bounded below by no-load magnetising current, so it is not simply
  proportional to shaft power (:func:`three_phase_current_A` is the ideal part; the callers add
  the configured no-load reference).
"""

from __future__ import annotations

import math

#: sqrt(3), the three-phase line-to-line factor.
SQRT_3 = math.sqrt(3.0)

#: mbar -> Pa.
PA_PER_MBAR = 100.0

#: Default temperature of the Nm3 basis, overridden from ``gas_and_combustion`` config.
DEFAULT_NORMAL_TEMPERATURE_K = 273.15


def normal_to_actual_m3_per_h(
    flow_Nm3_per_h: float,
    temperature_C: float,
    normal_temperature_K: float = DEFAULT_NORMAL_TEMPERATURE_K,
) -> float:
    """Ideal-gas expansion of a normal volume flow to its actual flow at ``temperature_C``.

    Pressure correction is deliberately omitted: process draughts here are tens of mbar, i.e.
    a few percent of atmospheric, well inside the ASSUMPTION error of the fan efficiency.
    """
    normal_T = float(normal_temperature_K)
    if normal_T <= 0.0:
        raise ValueError("normal_temperature_K must be > 0")
    return max(0.0, float(flow_Nm3_per_h)) * (float(temperature_C) + normal_T) / normal_T


def fan_shaft_power_kW(
    volume_flow_m3_per_h: float,
    pressure_rise_mbar: float,
    efficiency: float,
) -> float:
    """``P = Q * dp / eta`` in kW, from an **actual** volume flow and a static pressure rise.

    ``m3/h / 3600 * (mbar * 100) / 1000 = kW``; the sign of ``pressure_rise_mbar`` is ignored
    because a draught fan is quoted as a negative gauge pressure but still absorbs power.
    """
    eta = float(efficiency)
    if not 0.0 < eta <= 1.0:
        raise ValueError("fan efficiency must be in (0, 1]")
    watts = (
        max(0.0, float(volume_flow_m3_per_h))
        / 3600.0
        * abs(float(pressure_rise_mbar))
        * PA_PER_MBAR
        / eta
    )
    return watts / 1000.0


def three_phase_current_A(power_kW: float, voltage_V: float, power_factor: float) -> float:
    """``I = P / (sqrt(3) * V * cos(phi))`` for a three-phase motor (PRD 9.5/12.1).

    Returns 0.0 for non-positive power (a stopped drive) rather than a negative current.
    """
    voltage = float(voltage_V)
    pf = float(power_factor)
    if voltage <= 0.0:
        raise ValueError("voltage_V must be > 0")
    if not 0.0 < pf <= 1.0:
        raise ValueError("power_factor must be in (0, 1]")
    power_W = float(power_kW) * 1000.0
    if power_W <= 0.0:
        return 0.0
    return power_W / (SQRT_3 * voltage * pf)


__all__ = [
    "SQRT_3",
    "PA_PER_MBAR",
    "DEFAULT_NORMAL_TEMPERATURE_K",
    "normal_to_actual_m3_per_h",
    "fan_shaft_power_kW",
    "three_phase_current_A",
]
