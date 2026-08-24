"""NFR-10 conservation validation over a generated horizon (PRD 9.3, 11.2, NFR-10).

NFR-10 asks that the mass and energy residuals stay inside a configurable tolerance - default
+/-3 % (**ASSUMPTION**, `configs/kiln_dynamics.yaml -> energy_balance.unaccounted_loss_max_fraction`)
- "across the full simulated horizon". Taken as a *pointwise percentage of the instantaneous energy
input*, that single statistic is not well defined everywhere on a PRD 11.3/11.4 schedule, for two
reasons that have nothing to do with whether the balance closes:

* **The denominator is not always a valid scale.** PRD 11.4's startup transition ramps fuel and
  feed from zero, so the input basis collapses toward the recovered cooler heat alone (measured
  minimum: 23.6 % of the reference operating point's basis) while the accounted output terms are
  still sized for the operating point the kiln is leaving. The ratio then reports the *mismatch of
  two operating points*, magnified by a shrinking denominator, and reaches ~184 %. Dividing by a
  basis that is heading for zero is an arithmetic artefact, not a conservation failure.
* **A delay transient is not a steady-state offset.** The kiln's energy closure is carried by
  `energy_closure_to_preheater_temperature` (PRD 9.4), so after a setpoint move the accounted
  outputs lag the inputs by a configured dead time and time constant. Energy is redistributed in
  *time*; the honest statistic over such a window is an integral, not the worst single step.

So this module evaluates the energy residual in three regimes and reports each with a statistic
that is numerically valid there. The physical model is untouched: every number below is read from
the same config the twin runs on, the closure itself is unchanged, and mass conservation keeps its
single unchanged metric (an exact discretization, machine precision on every row - startup rows
included).

======================  =========================================  ========================
Regime                  Governing statistic                        Bound
======================  =========================================  ========================
``settled``             peak \\|residual\\| relative to the         ``unaccounted_loss_max_fraction``
                        instantaneous input basis                   (unchanged +/-3 %)
``transient``           integrated \\|unaccounted\\| / integrated    the same +/-3 %, applied to
                        input, over the regime and per episode      the integral
``startup``             peak \\|unaccounted\\| / the REFERENCE       ``startup_reference_max_fraction``
                        input basis (fixed, non-zero)
======================  =========================================  ========================

The horizon-wide energy-weighted integral is reported too, and is judged against the same
unchanged +/-3 %: that is NFR-10's "across the full simulated horizon" in a numerically valid form.

Classification is by *cause*, never by outcome - a row is never moved out of ``settled`` because
its residual is large:

* ``startup``: the scheduler's own ``is_startup`` label, or an input basis below
  ``near_zero_input_fraction`` of the reference basis (a numerical guard, so no relative metric is
  ever formed on a row that cannot support one, whatever the labels say).
* ``transient``: a driven kiln input moved on this step or within the preceding settling window,
  where the window is ``dead_time + settling_time_constants * tau`` of the closure relationship.
* ``settled``: everything else.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from src import paths
from src.config import KILN, Config, ConfigError, load_config
from src.data_generation.generator import DatasetGenerator
from src.simulation.scheduler import ScenarioSchedule

#: The three validation regimes, in the order they are reported.
REGIMES: Final[tuple[str, ...]] = ("settled", "transient", "startup")

#: Relationship whose configured delay carries the kiln energy closure (PRD 9.3/9.4).
CLOSURE_RELATIONSHIP: Final = "energy_closure_to_preheater_temperature"

#: Trajectory columns this report needs beyond the residual percentages.
ENERGY_COLUMNS: Final[tuple[str, ...]] = (
    "kiln_energy_pct",
    "kiln_unaccounted_loss_MJ_per_h",
    "kiln_energy_input_MJ_per_h",
    "kiln_reference_energy_input_MJ_per_h",
)

#: A basis (or an integral of one) at or below this is treated as idle, not as a denominator.
IDLE_BASIS: Final = 1e-9

#: Decimals every reported statistic is rounded to, so two reports of one seed diff cleanly.
_ROUND = 6


def _signif(value: float, digits: int = 6) -> float:
    """Round to ``digits`` significant figures rather than to a fixed number of decimals.

    The mass closure is exact to machine precision (order 1e-13 %), so fixed-decimal rounding would
    publish it as ``0.0`` - a claim of *exactly* zero the arithmetic does not support. Reporting the
    magnitude keeps the sidecar honest about what was measured.
    """
    if value == 0.0 or not isfinite(value):
        return float(value)
    return float(f"{value:.{digits}g}")


# =============================================================================
# The bounds and the settling window, all read from config
# =============================================================================
@dataclass(frozen=True, slots=True)
class ValidationBounds:
    """The NFR-10 methodology's numbers, read from ``configs/kiln_dynamics.yaml``.

    ``tolerance_pct`` is the unchanged ``energy_balance.unaccounted_loss_max_fraction`` and governs
    three of the five reported statistics; the other two bounds exist because a delay transient's
    peak and a startup ramp's absolute loss are *not* claims about steady-state closure and cannot
    be judged by the same number. None of them is used by the twin.
    """

    tolerance_pct: float
    near_zero_input_fraction: float
    settling_time_constants: float
    transient_peak_max_pct: float
    startup_reference_max_pct: float
    closure_dead_time_min: float
    closure_tau_min: float

    @property
    def settling_minutes(self) -> float:
        """How long after a setpoint move the closure is still a transient (PRD 9.4)."""
        return self.closure_dead_time_min + self.settling_time_constants * self.closure_tau_min

    @classmethod
    def from_config(cls, kiln_config: Config | None = None) -> "ValidationBounds":
        config = kiln_config if kiln_config is not None else load_config(KILN)
        energy = config.get_path("energy_balance")
        validation = energy.get("residual_validation")
        if not isinstance(validation, Mapping):
            raise ConfigError(
                "energy_balance.residual_validation is missing: the NFR-10 three-regime "
                "validation of SIMULATION_ASSUMPTIONS.md 11.5 has no bounds to read"
            )
        closure = config.get_path(f"delays.{CLOSURE_RELATIONSHIP}")
        tau = closure.get("tau_min")
        if tau is None:
            raise ConfigError(
                f"delays.{CLOSURE_RELATIONSHIP} has no tau_min: the settling window of the "
                "energy closure cannot be derived from the configured delay"
            )
        return cls(
            tolerance_pct=100.0 * float(energy["unaccounted_loss_max_fraction"]),
            near_zero_input_fraction=float(validation["near_zero_input_fraction"]),
            settling_time_constants=float(validation["settling_time_constants"]),
            transient_peak_max_pct=100.0 * float(validation["transient_peak_max_fraction"]),
            startup_reference_max_pct=100.0 * float(validation["startup_reference_max_fraction"]),
            closure_dead_time_min=float(closure["dead_time_min"]),
            closure_tau_min=float(tau),
        )

    def describe(self) -> dict[str, float]:
        return {
            "tolerance_pct": self.tolerance_pct,
            "near_zero_input_fraction": self.near_zero_input_fraction,
            "settling_time_constants": self.settling_time_constants,
            "settling_minutes": self.settling_minutes,
            "transient_peak_max_pct": self.transient_peak_max_pct,
            "startup_reference_max_pct": self.startup_reference_max_pct,
        }


# =============================================================================
# Classifying the rows of a horizon (by cause, never by outcome)
# =============================================================================
def moved_mask(driven: np.ndarray, settling_rows: int) -> np.ndarray:
    """Rows on which a driven input moved, extended over the settling window that follows.

    The window is what keeps the directive's point 2 honest: the step *after* a move is still a
    transient even though nothing moved on it, because PRD 8.3's sequential execution order has
    the kiln reading a one-step-old preheater state, and the configured closure delay then takes
    ``dead_time + n*tau`` to give the energy back. Neither is a steady-state offset.
    """
    rows = int(driven.shape[0])
    moved = np.zeros(rows, dtype=bool)
    if rows > 1:
        moved[1:] = np.abs(np.diff(driven, axis=0)).max(axis=1) > IDLE_BASIS
    window = max(0, int(settling_rows))
    extended = moved.copy()
    for shift in range(1, window + 1):
        extended[shift:] |= moved[: rows - shift]
    return extended


def classify(
    *,
    basis: np.ndarray,
    reference_input: float,
    startup_label: np.ndarray,
    driven: np.ndarray,
    settling_rows: int,
    near_zero_input_fraction: float,
) -> dict[str, np.ndarray]:
    """Split a horizon into the three validation regimes of the module docstring.

    ``startup`` is the union of the scheduler's own label and the numerical near-zero guard, so a
    row whose input basis cannot support a percentage is never judged by one - even if a future
    scenario reaches that state outside a labelled startup ramp.
    """
    startup = np.asarray(startup_label, dtype=bool) | (
        np.asarray(basis, dtype=float) < float(near_zero_input_fraction) * float(reference_input)
    )
    transient = moved_mask(driven, settling_rows) & ~startup
    settled = ~(startup | transient)
    return {"settled": settled, "transient": transient, "startup": startup}


def _episodes(mask: np.ndarray) -> tuple[tuple[int, int], ...]:
    """Contiguous ``[start, end)`` runs of ``True`` - one delay transient each."""
    padded = np.concatenate(([False], np.asarray(mask, dtype=bool), [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return tuple((int(start), int(end)) for start, end in zip(edges[0::2], edges[1::2]))


# =============================================================================
# One regime's residual
# =============================================================================
#: What each regime's *governing* statistic is, and what it is divided by.
_GOVERNING: Final[Mapping[str, tuple[str, str]]] = {
    "settled": ("peak_relative_pct", "instantaneous energy input"),
    "transient": ("integrated_pct", "integrated energy input over the transient rows"),
    "startup": ("reference_relative_pct", "reference operating-point energy input"),
}


@dataclass(frozen=True, slots=True)
class BoundCheck:
    """One statistic of one regime, and the configured bound it has to hold."""

    statistic: str
    value_pct: float
    bound_pct: float

    @property
    def passed(self) -> bool:
        return self.value_pct <= self.bound_pct

    def describe(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "value_pct": round(self.value_pct, _ROUND),
            "bound_pct": round(self.bound_pct, _ROUND),
            "passed": self.passed,
        }



@dataclass(frozen=True, slots=True)
class RegimeResidual:
    """The energy residual of one validation regime, by every statistic that is valid there.

    Every field is reported for every regime - it is only ``metric`` that says which one the
    ``bound_pct`` applies to. That is deliberate: the 184 % startup figure stays visible in
    ``peak_relative_pct`` instead of being quietly dropped, and the reader can see both why it is
    large and why it is not the number the regime is judged on.
    """

    regime: str
    rows: int
    row_fraction: float
    metric: str
    basis: str
    value_pct: float
    bound_pct: float
    peak_relative_pct: float
    integrated_pct: float
    peak_absolute_MJ_per_h: float
    reference_relative_pct: float
    minimum_basis_fraction: float
    episodes: int
    worst_episode_integrated_pct: float
    checks: tuple[BoundCheck, ...]

    @property
    def within_bound(self) -> bool:
        """Do every one of this regime's configured bounds hold?"""
        return all(check.passed for check in self.checks)

    def describe(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "rows": self.rows,
            "row_fraction": round(self.row_fraction, _ROUND),
            "metric": self.metric,
            "basis": self.basis,
            "value_pct": round(self.value_pct, _ROUND),
            "bound_pct": round(self.bound_pct, _ROUND),
            "within_bound": self.within_bound,
            "peak_relative_pct": round(self.peak_relative_pct, _ROUND),
            "integrated_pct": round(self.integrated_pct, _ROUND),
            "peak_absolute_MJ_per_h": round(self.peak_absolute_MJ_per_h, _ROUND),
            "reference_relative_pct": round(self.reference_relative_pct, _ROUND),
            "minimum_basis_fraction": round(self.minimum_basis_fraction, _ROUND),
            "episodes": self.episodes,
            "worst_episode_integrated_pct": round(self.worst_episode_integrated_pct, _ROUND),
            "checks": [check.describe() for check in self.checks],
        }



def _integrated_pct(loss: np.ndarray, basis: np.ndarray) -> float:
    """``100 * integral|unaccounted| / integral input`` over the rows given.

    The sampling interval cancels out of the ratio (PRD 11.2 samples on a fixed 1-minute clock),
    so this is the energy-weighted mean residual of the window: what a delay redistributes in time
    it must give back inside the integral, which is why a transient can be judged by it while its
    worst single step cannot. ``|unaccounted|`` rather than the signed sum, so a positive and a
    negative excursion cannot cancel into a false pass.
    """
    total = float(np.abs(basis).sum())
    if total <= IDLE_BASIS:
        return 0.0
    return 100.0 * float(np.abs(loss).sum()) / total


def _regime_residual(
    regime: str,
    mask: np.ndarray,
    *,
    pct: np.ndarray,
    loss: np.ndarray,
    basis: np.ndarray,
    reference_input: float,
    bounds: ValidationBounds,
) -> RegimeResidual:
    """Score one regime with every statistic, and mark which one bounds it."""
    metric, denominator = _GOVERNING[regime]
    rows = int(mask.sum())
    peak_absolute = float(np.abs(loss[mask]).max()) if rows else 0.0
    spans = _episodes(mask) if regime == "transient" else ()
    worst_episode = 0.0
    for start, end in spans:
        worst_episode = max(worst_episode, _integrated_pct(loss[start:end], basis[start:end]))
    statistics = {
        "peak_relative_pct": float(np.abs(pct[mask]).max()) if rows else 0.0,
        "integrated_pct": _integrated_pct(loss[mask], basis[mask]) if rows else 0.0,
        "reference_relative_pct": 100.0 * peak_absolute / float(reference_input),
    }
    if regime == "settled":
        # The unchanged NFR-10 requirement, on the rows where a percentage of the instantaneous
        # input is what it claims to be. Nothing here is relaxed.
        checks = (BoundCheck(metric, statistics[metric], bounds.tolerance_pct),)
    elif regime == "transient":
        checks = (
            BoundCheck("integrated_pct", statistics["integrated_pct"], bounds.tolerance_pct),
            # Per episode as well as in aggregate, so a single bad ramp cannot hide inside the
            # average of five hundred good ones.
            BoundCheck("worst_episode_integrated_pct", worst_episode, bounds.tolerance_pct),
            BoundCheck(
                "peak_relative_pct",
                statistics["peak_relative_pct"],
                bounds.transient_peak_max_pct,
            ),
        )
    else:
        checks = (
            BoundCheck(metric, statistics[metric], bounds.startup_reference_max_pct),
        )
    return RegimeResidual(
        regime=regime,
        rows=rows,
        row_fraction=rows / float(mask.size),
        metric=metric,
        basis=denominator,
        value_pct=statistics[metric],
        bound_pct=checks[0].bound_pct,
        peak_relative_pct=statistics["peak_relative_pct"],
        integrated_pct=statistics["integrated_pct"],
        peak_absolute_MJ_per_h=peak_absolute,
        reference_relative_pct=statistics["reference_relative_pct"],
        minimum_basis_fraction=(float(basis[mask].min()) / float(reference_input)) if rows else 0.0,
        episodes=len(spans),
        worst_episode_integrated_pct=worst_episode,
        checks=checks,
    )


# =============================================================================
# The report
# =============================================================================
@dataclass(frozen=True, slots=True)
class ConservationReport:
    """NFR-10 over one generated horizon: three energy regimes plus the mass closures.

    ``passed`` is the whole of NFR-10 for this run. The mass entries are deliberately unchanged -
    PRD 9.3/10.2's mass balances are exact discretizations, so they keep the one metric they always
    had (peak relative residual, machine precision on every row including startup) and are simply
    reported here beside the energy regimes.
    """

    name: str
    rows: int
    dt_seconds: float
    settling_minutes: float
    reference_input_MJ_per_h: float
    bounds: ValidationBounds
    regimes: Mapping[str, RegimeResidual]
    horizon_integrated_pct: float
    mass_peak_pct: Mapping[str, float]
    mass_bound_pct: Mapping[str, float]

    # -- verdict -------------------------------------------------------------------------
    @property
    def energy_checks(self) -> tuple[BoundCheck, ...]:
        """Every energy bound of the run, in regime order, plus the horizon-wide integral."""
        checks = [check for regime in REGIMES for check in self.regimes[regime].checks]
        checks.append(
            BoundCheck(
                "horizon_integrated_pct",
                self.horizon_integrated_pct,
                self.bounds.tolerance_pct,
            )
        )
        return tuple(checks)

    @property
    def mass_checks(self) -> tuple[BoundCheck, ...]:
        return tuple(
            BoundCheck(f"{unit}_mass_peak_pct", value, self.mass_bound_pct[unit])
            for unit, value in self.mass_peak_pct.items()
        )

    @property
    def failures(self) -> tuple[BoundCheck, ...]:
        return tuple(
            check for check in self.energy_checks + self.mass_checks if not check.passed
        )

    @property
    def passed(self) -> bool:
        return not self.failures

    def regime(self, name: str) -> RegimeResidual:
        if name not in self.regimes:
            raise ConfigError(f"unknown validation regime {name!r}; known: {REGIMES}")
        return self.regimes[name]

    # -- serialization -------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rows": self.rows,
            "dt_seconds": self.dt_seconds,
            "settling_minutes": round(self.settling_minutes, _ROUND),
            "reference_input_MJ_per_h": round(self.reference_input_MJ_per_h, _ROUND),
            "bounds": {
                key: round(value, _ROUND) for key, value in self.bounds.describe().items()
            },
            "passed": self.passed,
            "horizon_integrated_pct": round(self.horizon_integrated_pct, _ROUND),
            "regimes": {name: self.regimes[name].describe() for name in REGIMES},
            "mass": {
                unit: {
                    "peak_relative_pct": _signif(value),
                    "bound_pct": round(self.mass_bound_pct[unit], _ROUND),
                    "passed": value <= self.mass_bound_pct[unit],
                }
                for unit, value in self.mass_peak_pct.items()
            },
            "failures": [check.describe() for check in self.failures],
        }

    def to_json(self, target: Path | str | None = None) -> Path:
        """Write :meth:`describe` beside the FR-13 data-quality reports (PRD 23 layout)."""
        if target is None:
            paths.ensure_dirs()
            target = paths.REPORTS_DATA_QUALITY_DIR / f"{self.name}_conservation.json"
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.describe(), indent=2) + "\n", encoding="utf-8")
        return path

    def summary(self) -> str:
        """One line per regime, for a notebook cell or a demo log."""
        lines = [
            f"NFR-10 conservation over {self.rows} rows of '{self.name}' "
            f"({'PASS' if self.passed else 'FAIL'}), "
            f"tolerance {self.bounds.tolerance_pct:g} %"
        ]
        for name in REGIMES:
            entry = self.regimes[name]
            lines.append(
                f"  {name:<9} {entry.rows:>6} rows ({entry.row_fraction:6.1%})  "
                f"{entry.metric} = {entry.value_pct:8.4f} % "
                f"(bound {entry.bound_pct:g} %, per {entry.basis})"
            )
        lines.append(
            f"  horizon   integrated |residual| / integrated input = "
            f"{self.horizon_integrated_pct:.4f} % (bound {self.bounds.tolerance_pct:g} %)"
        )
        for unit, value in self.mass_peak_pct.items():
            lines.append(
                f"  mass      {unit}: peak {value:.3e} % (bound {self.mass_bound_pct[unit]:g} %)"
            )
        return "\n".join(lines)


# =============================================================================
# Building it from a generated horizon
# =============================================================================
def conservation_report(
    generator: DatasetGenerator,
    *,
    state: pd.DataFrame | None = None,
    schedule: ScenarioSchedule | None = None,
    trajectories: Mapping[str, Any] | None = None,
    settling_minutes: float | None = None,
    name: str = "run",
) -> ConservationReport:
    """Validate NFR-10 over one generated horizon in the three regimes of the module docstring.

    ``state`` is a trajectory frame from :meth:`DatasetGenerator.run_trajectory`; pass the one you
    already have rather than paying for a second pass. ``schedule`` must be the schedule that
    produced it, because the row classification reads the scheduler's driven inputs and its
    ``is_startup`` label. Only the **exported** rows are judged: the warm-up is a numerical device
    that never leaves the generator, and NFR-10 is a claim about the delivered horizon.

    ``settling_minutes`` overrides the config-derived transient window. The intended use is a test
    that pins the *strictest* reading of the settled bound - one simulation step, i.e. the PRD 8.3
    execution-order term alone - and shows it still holds without the delay tail's help. Only
    ``regime("settled")`` is meaningful under such an override: a window shorter than the configured
    closure delay deliberately leaves delay-tail rows in ``settled``, and shreds the transient
    regime into single-row "episodes" whose integral is just the pointwise percentage again, so the
    transient checks stop measuring what they exist for.
    """
    if not isinstance(generator, DatasetGenerator):
        raise ConfigError(
            f"conservation_report needs a DatasetGenerator, got {type(generator).__name__}"
        )
    schedule = schedule if schedule is not None else generator.scheduler.build()
    if state is None:
        state = generator.run_trajectory(schedule, trajectories)
    missing = [column for column in ENERGY_COLUMNS if column not in state.columns]
    if missing:
        raise ConfigError(
            f"the trajectory frame is missing {missing}: NFR-10's startup and transient metrics "
            "need the absolute energy diagnostics, not only the residual percentage"
        )
    bounds = ValidationBounds.from_config(generator.configs["kiln"])
    exported = schedule.exported(state)
    labels = schedule.exported(schedule.labels)
    driven = schedule.exported(schedule.inputs["kiln"]).to_numpy(dtype=float)

    pct = exported["kiln_energy_pct"].to_numpy(dtype=float)
    loss = exported["kiln_unaccounted_loss_MJ_per_h"].to_numpy(dtype=float)
    basis = exported["kiln_energy_input_MJ_per_h"].to_numpy(dtype=float)
    reference_input = float(exported["kiln_reference_energy_input_MJ_per_h"].max())
    if reference_input <= IDLE_BASIS:
        raise ConfigError(
            "the reference operating point reports no energy input, so it cannot serve as the "
            "stable denominator NFR-10 needs during a startup ramp"
        )

    dt_seconds = float(generator.simulation.dt_seconds)
    window_minutes = (
        bounds.settling_minutes if settling_minutes is None else float(settling_minutes)
    )
    settling_rows = int(round(window_minutes * 60.0 / dt_seconds))
    masks = classify(
        basis=basis,
        reference_input=reference_input,
        startup_label=labels["is_startup"].to_numpy(dtype=bool),
        driven=driven,
        settling_rows=settling_rows,
        near_zero_input_fraction=bounds.near_zero_input_fraction,
    )
    regimes = {
        regime: _regime_residual(
            regime,
            masks[regime],
            pct=pct,
            loss=loss,
            basis=basis,
            reference_input=reference_input,
            bounds=bounds,
        )
        for regime in REGIMES
    }
    mass_tolerance = "mass_balance.tolerance_pct"
    return ConservationReport(
        name=name,
        rows=int(pct.size),
        dt_seconds=dt_seconds,
        settling_minutes=window_minutes,
        reference_input_MJ_per_h=reference_input,
        bounds=bounds,
        regimes=regimes,
        horizon_integrated_pct=_integrated_pct(loss, basis),
        mass_peak_pct={
            "kiln": float(exported["kiln_mass_pct"].abs().max()),
            "mill": float(exported["mill_mass_pct"].abs().max()),
        },
        mass_bound_pct={
            unit: float(generator.configs[unit].get_path(mass_tolerance))
            for unit in ("kiln", "mill")
        },
    )


__all__ = [
    "CLOSURE_RELATIONSHIP",
    "ENERGY_COLUMNS",
    "REGIMES",
    "BoundCheck",
    "ConservationReport",
    "RegimeResidual",
    "ValidationBounds",
    "classify",
    "conservation_report",
    "moved_mask",
]






