"""Reduced-order gain helpers (PRD v1.1.1 Sections 9.4, 10.3).

The reduced-order relationships are all written as *deviations from the reference operating
point*: ``y_target = y_ref + sum(gain_i * deviation_i)`` for additive gains, or
``y_target = y_ref * (x / x_ref) ** exponent`` for fan/motor power laws. These helpers make
that convention explicit and identical everywhere, so a gain can never be silently applied to
an absolute value in one place and a relative one in another.

Convention (documented in ``SIMULATION_ASSUMPTIONS.md``):

* ``*_per_pct_<x>``       - gain per **relative percent** deviation of ``x`` from reference,
                            i.e. ``100 * (x / x_ref - 1)`` (see :func:`relative_pct`).
* ``*_per_pct_point_<x>`` - gain per **absolute percentage point** of a variable that is
                            itself a percentage (e.g. raw-meal moisture).
* ``*_per_K_<x>``         - gain per kelvin of absolute temperature deviation.
* ``*_exponent``          - power-law exponent used with :func:`power_law`.
"""

from __future__ import annotations

import math

#: Guard for divisions by a reference value that a caller mis-configured as zero.
_EPS = 1e-12


def relative_pct(value: float, reference: float) -> float:
    """``100 * (value / reference - 1)`` - relative deviation in percent."""
    ref = float(reference)
    if abs(ref) < _EPS:
        raise ValueError("reference value for a relative-percent gain must be non-zero")
    return 100.0 * (float(value) / ref - 1.0)


def power_law(value: float, reference: float, exponent: float) -> float:
    """``(value / reference) ** exponent`` with a non-negative, finite guard.

    Used for fan laws, motor-torque laws and mill-loading laws (PRD 9.5/10.3). Negative or
    zero inputs (a stopped fan during start-up) yield 0.0 rather than a domain error.
    """
    ref = float(reference)
    if abs(ref) < _EPS:
        raise ValueError("reference value for a power-law gain must be non-zero")
    ratio = float(value) / ref
    if ratio <= 0.0:
        return 0.0
    return math.pow(ratio, float(exponent))


def clamp(value: float, low: float | None = None, high: float | None = None) -> float:
    """Clamp to a physical range.

    Used only for quantities that are physically impossible outside the bound (a negative
    flow, a negative concentration, a health scalar above 1). Process variables are never
    clamped to their *documented* ranges - the simulator must be free to leave them under
    abnormal conditions, which is what the anomaly regimes of PRD 11.4 depend on.
    """
    result = float(value)
    if low is not None:
        result = max(float(low), result)
    if high is not None:
        result = min(float(high), result)
    return result


def blend(previous: float, target: float, weight: float) -> float:
    """First-order blend used where a relationship has no configured delay row."""
    factor = clamp(weight, 0.0, 1.0)
    return float(previous) + factor * (float(target) - float(previous))


__all__ = ["relative_pct", "power_law", "clamp", "blend"]
