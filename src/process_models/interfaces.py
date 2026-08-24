"""The mandatory process-unit interface (PRD v1.1.1 Sections 8.4, 8.5).

Every component of the twin implements :class:`ProcessUnit`; the composite twins
(``KilnTwin``, ``CementMillTwin``, ``PlantTwin``) additionally implement :class:`Twin`.
What-if (Section 16), the optimizer (Section 14) and the visualization layer (Section 19.4)
are all thin callers of these methods - physics, delay logic and state exist exactly once
(Section 8.5 single source of truth).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pandas is only needed for the Twin signature, keep import cost off imports
    import pandas as pd

#: Suffix marking the *basis* entries of ``balance_residuals`` (PRD 8.4).
#:
#: The mapping is a residual channel: every entry is a closure error and is therefore zero at the
#: reference operating point. Two entries are not - the instantaneous energy input a percentage is
#: taken *of*, and the reference point's own input - and they carry this suffix so a reader can tell
#: a denominator from a residual. They exist because NFR-10's percentage is undefined where the
#: basis collapses (PRD 11.4's startup ramp), and the three-regime validation of
#: :mod:`src.data_generation.conservation` needs the numerator and the denominator separately.
BASIS_SUFFIX = "energy_input_MJ_per_h"


def is_basis_key(key: str) -> bool:
    """Is this ``balance_residuals`` entry a denominator rather than a closure error?"""
    return key.endswith(BASIS_SUFFIX)


def residual_entries(residuals: Mapping[str, float]) -> dict[str, float]:
    """Only the closure errors of a ``balance_residuals`` mapping - what must vanish at reference."""
    return {key: value for key, value in residuals.items() if not is_basis_key(key)}



@runtime_checkable
class ProcessUnit(Protocol):
    """PRD 8.4 - the interface every component implements."""

    state: dict[str, float]  # current internal state variables
    inputs: dict[str, float]  # current manipulated/disturbance inputs
    outputs: dict[str, float]  # current measured/derived outputs
    constraints: dict[str, tuple]  # {var_name: (min, max)} - hard constraints, Section 14.2
    health: dict[str, float]  # equipment health/wear indicators (0-1)
    balance_residuals: dict[str, float]  # {"energy_pct": .., "mass_pct": ..} - Section 9.2/10.2,
    # plus the absolute companions of the energy closure; entries whose key ends in
    # ``BASIS_SUFFIX`` are denominators, not residuals (see :func:`residual_entries`)

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        """Advance state by dt_seconds given new inputs (routed through each relationship's
        configured DelayedResponse - Section 9.4); return updated outputs."""
        ...


@runtime_checkable
class Twin(ProcessUnit, Protocol):
    """PRD 8.4 - composite twins add scenario rollout, steady state and the snapshot."""

    def simulate_scenario(
        self, input_trajectory: pd.DataFrame, dt_seconds: float
    ) -> pd.DataFrame:
        """Roll the twin forward over a trajectory of inputs; used by What-if and Optimization."""
        ...

    def to_steady_state(
        self, inputs: dict[str, float], max_minutes: int = 120
    ) -> dict[str, float]:
        """Run until |d(state)/dt| < tolerance or max_minutes elapsed; used by Optimization
        candidate evaluation."""
        ...

    def current_state_snapshot(self) -> dict:
        """Single source of truth read by numeric panels AND the visualization renderer
        (Section 19.4)."""
        ...


class UnitBase:
    """Shared bookkeeping for the concrete units (the six attributes of PRD 8.4).

    Deliberately not a base class for physics: each unit implements its own
    ``simulation_step``. This only removes the repeated dictionary plumbing and gives every
    unit the same snapshot shape, which is what the dashboard and the HTML/SVG renderer bind
    to (Section 19.4).
    """

    __slots__ = ("balance_residuals", "constraints", "health", "inputs", "name", "outputs", "state")

    def __init__(self, name: str) -> None:
        self.name = name
        self.state: dict[str, float] = {}
        self.inputs: dict[str, float] = {}
        self.outputs: dict[str, float] = {}
        self.constraints: dict[str, tuple] = {}
        self.health: dict[str, float] = {}
        self.balance_residuals: dict[str, float] = {}

    # -- input handling -----------------------------------------------------------------
    def merge_inputs(self, inputs: Mapping[str, float] | None) -> dict[str, float]:
        """Overlay the given inputs on the retained ones (omitted inputs simply hold).

        Holding is the physically meaningful default: a caller changing only the fuel rate in
        a what-if run must not implicitly zero the feed rate.
        """
        if inputs:
            for key, value in inputs.items():
                if value is None:
                    continue
                self.inputs[key] = float(value)
        return self.inputs

    def input_value(self, *names: str, default: float = 0.0) -> float:
        """First present input among ``names``, else ``default``.

        The dataset tag names of PRD 12.1/12.2 and the model-side variable names of PRD 9.1/10.1
        disagree on unit suffixes (``ID_fan_speed`` vs ``ID_fan_speed_pct``, ``raw_meal_moisture``
        vs ``raw_meal_moisture_pct``). Rather than pick a winner and break the other caller, every
        unit accepts both spellings through this lookup.
        """
        for name in names:
            if name in self.inputs:
                return float(self.inputs[name])
        return float(default)

    def set_health(self, health: Mapping[str, float] | None) -> dict[str, float]:
        """Update equipment health indicators (0-1, PRD 9.5).

        Health is driven from outside the twin (the data generator owns the seeded RNG for the
        Poisson fault process, PRD 9.5/11.4), so the twin itself stays deterministic.
        """
        if health:
            for key, value in health.items():
                if value is None:
                    continue
                self.health[key] = float(value)
        return self.health

    # -- snapshot -----------------------------------------------------------------------
    def current_state_snapshot(self) -> dict[str, Any]:
        """Snapshot of this unit (PRD 8.5); composites nest their sub-units' snapshots."""
        return {
            "unit": self.name,
            "inputs": dict(self.inputs),
            "state": dict(self.state),
            "outputs": dict(self.outputs),
            "health": dict(self.health),
            "balance_residuals": dict(self.balance_residuals),
            "constraints": {key: tuple(value) for key, value in self.constraints.items()},
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(name={self.name!r}, outputs={len(self.outputs)})"


def within_constraints(unit: ProcessUnit) -> dict[str, bool]:
    """Per-variable pass/fail against the unit's own ``constraints`` (PRD 8.4).

    The optimizer's hard-constraint pre-filter (Section 14.2) is a separate, structurally
    independent pass over ``configs/optimization.yaml``; this helper only reports whether the
    twin is being asked to run outside the range its gains were parameterized for.
    """
    report: dict[str, bool] = {}
    pools = (unit.inputs, unit.outputs, unit.state)
    for variable, bounds in unit.constraints.items():
        low, high = float(bounds[0]), float(bounds[1])
        for pool in pools:
            if variable in pool:
                report[variable] = low <= float(pool[variable]) <= high
                break
    return report


__all__ = [
    "BASIS_SUFFIX",
    "ProcessUnit",
    "Twin",
    "UnitBase",
    "is_basis_key",
    "residual_entries",
    "within_constraints",
]
