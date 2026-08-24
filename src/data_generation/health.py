"""``EquipmentHealthProcess`` - the slow wear scalar behind the equipment tags (PRD v1.1.1 9.5).

PRD 9.5 defines exactly one stochastic object for the equipment signals:

    "``vibration``, ``bearing_temperature`` ... plus a slow degrading ``health`` scalar (0-1)
    that very occasionally (Poisson process, configurable rate) dips to simulate a
    mechanical-fault regime, feeding the anomaly detector's equipment-fault feature set."

so this module produces the scalar and nothing else. The twins already consume it: PRD 9.5's
tags are computed from ``load`` and ``1 - health`` inside
:class:`src.process_models.kiln_core.RotaryKilnModel` and
:class:`src.process_models.mill_units.MillModel`, and ``set_health`` is the only way in.

The trajectory is the sum of two ASSUMPTIONs, both recorded in ``SIMULATION_ASSUMPTIONS.md``
because PRD 9.5 gives a shape ("slow degrading ... occasionally dips") rather than an equation:

1. **wear** is a linear ramp of ``degradation_per_day`` - monotone, never repaired inside one
   dataset, because a 30-day demo window is far shorter than an overhaul interval;
2. **a fault** subtracts ``fault_health_drop`` at a Poisson arrival and that deficit then
   decays linearly at ``fault_recovery_per_day`` (maintenance), so a fault is a step down
   followed by a recovery ramp - the shape an equipment-fault detector has to separate from
   the wear ramp underneath it.

The result is clamped into ``[min_health, 1.0]``: below the floor the equipment would have been
stopped, and the twin's gain expressions are only linearized for a running machine.

Both units draw from their own named substream (``equipment_health:kiln`` /
``equipment_health:mill``), so lengthening one unit's fault list cannot shift the other's
(NFR-4), and the whole trajectory is planned up front rather than sampled step by step - the
generator needs the array to hand to ``set_health`` per row, and a pre-planned array is what
makes the ground-truth ``equipment_fault`` column exportable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping

import numpy as np
import pandas as pd

from src.config import KILN, MILL, Config, ConfigError, load_config
from src.process_models.kiln_core import HEALTH_KEY as KILN_HEALTH_KEY
from src.process_models.mill_units import HEALTH_KEY as MILL_HEALTH_KEY
from src.schema import DatasetName
from src.simulation.simulation_config import MINUTES_PER_DAY, SimulationConfig

#: RNG substream prefix; the unit name is appended (NFR-4).
HEALTH_STREAM: Final = "equipment_health"

#: ``health`` dictionary key per dataset - owned by the process models, never re-spelled here.
HEALTH_KEYS: Final[Mapping[str, str]] = {"kiln": KILN_HEALTH_KEY, "mill": MILL_HEALTH_KEY}

#: Ground-truth column naming the unit's health scalar in the exported dataset (PRD 12.2).
HEALTH_COLUMN: Final = "equipment_health"

#: Ground-truth flag: is a mechanical-fault episode active on this row (PRD 12.2)?
FAULT_COLUMN: Final = "equipment_fault"

_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "initial",
    "degradation_per_day",
    "fault_rate_per_day",
    "fault_health_drop",
    "fault_recovery_per_day",
    "min_health",
)


@dataclass(frozen=True, slots=True)
class HealthFault:
    """One mechanical-fault episode: a step down at ``start_step`` and its recovery."""

    dataset: DatasetName
    start_step: int
    steps: int
    drop: float

    @property
    def end_step(self) -> int:
        """First step at which the fault deficit has fully recovered."""
        return self.start_step + self.steps

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "start_step": self.start_step,
            "steps": self.steps,
            "drop": float(self.drop),
        }


@dataclass(frozen=True, slots=True)
class HealthTrajectory:
    """The planned health scalar of one unit, plus the ground truth of what shaped it."""

    dataset: DatasetName
    key: str
    values: np.ndarray
    faults: tuple[HealthFault, ...]

    @property
    def fault_mask(self) -> np.ndarray:
        """True on every step inside a fault episode (the PRD 12.2 ground-truth flag)."""
        mask = np.zeros(self.values.size, dtype=bool)
        for fault in self.faults:
            mask[fault.start_step : fault.end_step] = True
        return mask

    def frame(self, index: pd.Index) -> pd.DataFrame:
        """The two ground-truth columns of this unit, indexed by ``index``."""
        if len(index) != self.values.size:
            raise ConfigError(
                f"health trajectory has {self.values.size} steps but the index has {len(index)}"
            )
        return pd.DataFrame(
            {HEALTH_COLUMN: self.values, FAULT_COLUMN: self.fault_mask}, index=index
        )

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "key": self.key,
            "initial": float(self.values[0]) if self.values.size else None,
            "final": float(self.values[-1]) if self.values.size else None,
            "minimum": float(self.values.min()) if self.values.size else None,
            "faults": [fault.describe() for fault in self.faults],
        }


# =============================================================================
# The process
# =============================================================================
class EquipmentHealthProcess:
    """Plans the PRD 9.5 health scalar of both units for a whole run."""

    def __init__(
        self,
        simulation: SimulationConfig | None = None,
        *,
        kiln_config: Config | None = None,
        mill_config: Config | None = None,
    ) -> None:
        self.simulation = (
            simulation if simulation is not None else SimulationConfig.from_config()
        )
        self._configs: Mapping[DatasetName, Config] = {
            "kiln": kiln_config if kiln_config is not None else load_config(KILN),
            "mill": mill_config if mill_config is not None else load_config(MILL),
        }
        self._settings: dict[DatasetName, Mapping[str, Any]] = {}
        for dataset, config in self._configs.items():
            self._settings[dataset] = self._validated(dataset, config)

    # -- validation ---------------------------------------------------------------------
    def _validated(self, dataset: DatasetName, config: Config) -> Mapping[str, Any]:
        """The ``equipment.health`` block of one unit, checked before it is trusted (NFR-6)."""
        block = config.get_path("equipment.health")
        if block is None:
            raise ConfigError(f"{dataset} config has no equipment.health block (PRD 9.5)")
        missing = [key for key in _REQUIRED_KEYS if key not in block]
        if missing:
            raise ConfigError(
                f"{dataset} equipment.health is missing {missing} (PRD 9.5); expected "
                f"{list(_REQUIRED_KEYS)}"
            )
        initial = float(block["initial"])
        floor = float(block["min_health"])
        if not 0.0 < floor <= initial <= 1.0:
            raise ConfigError(
                f"{dataset} equipment.health needs 0 < min_health <= initial <= 1, got "
                f"min_health={floor!r}, initial={initial!r}"
            )
        for key in ("degradation_per_day", "fault_rate_per_day", "fault_health_drop"):
            if float(block[key]) < 0.0:
                raise ConfigError(
                    f"{dataset} equipment.health.{key} must be >= 0, got {block[key]!r}"
                )
        if float(block["fault_recovery_per_day"]) <= 0.0:
            raise ConfigError(
                f"{dataset} equipment.health.fault_recovery_per_day must be > 0 (a fault that "
                f"never recovers would make the run's health monotone), got "
                f"{block['fault_recovery_per_day']!r}"
            )
        return block

    # -- planning -----------------------------------------------------------------------
    @property
    def steps_per_day(self) -> float:
        return MINUTES_PER_DAY * float(self.simulation.steps_per_minute)

    def plan(self, dataset: DatasetName) -> HealthTrajectory:
        """The health scalar of ``dataset`` for every simulated step of the run.

        Faults are drawn over the *exported* window and the warm-up is then padded with the
        initial value, exactly as the scheduler pads its disturbances: the warm-up exists to
        settle the twin, so changing ``warmup_minutes`` must not reshuffle the run (NFR-4).
        """
        if dataset not in self._settings:
            raise ConfigError(f"unknown dataset {dataset!r}; expected 'kiln' or 'mill'")
        block = self._settings[dataset]
        export_steps = int(self.simulation.export_steps)
        initial = float(block["initial"])
        floor = float(block["min_health"])
        steps_per_day = self.steps_per_day
        elapsed_days = np.arange(export_steps, dtype=float) / steps_per_day
        wear = initial - float(block["degradation_per_day"]) * elapsed_days
        deficit, faults = self._plan_faults(dataset, block, export_steps)
        values = np.clip(wear - deficit, floor, 1.0)
        warmup = int(self.simulation.warmup_steps)
        if warmup:
            head = np.full(warmup, initial if export_steps == 0 else float(values[0]))
            values = np.concatenate([head, values])
            faults = tuple(
                HealthFault(fault.dataset, fault.start_step + warmup, fault.steps, fault.drop)
                for fault in faults
            )
        return HealthTrajectory(dataset, HEALTH_KEYS[dataset], values, faults)

    def _plan_faults(
        self, dataset: DatasetName, block: Mapping[str, Any], steps: int
    ) -> tuple[np.ndarray, tuple[HealthFault, ...]]:
        """Poisson mechanical faults: a step down, then a linear maintenance recovery.

        ASSUMPTION: two overlapping faults add their deficits and the sum is clipped at
        ``min_health`` - the same rule the scenario scheduler uses for overlapping
        disturbances, so "worse than the floor" never silently becomes "better".
        """
        deficit = np.zeros(max(steps, 0), dtype=float)
        rate = float(block["fault_rate_per_day"])
        drop = float(block["fault_health_drop"])
        if steps <= 0 or rate <= 0.0 or drop <= 0.0:
            return deficit, ()
        steps_per_day = self.steps_per_day
        horizon_days = steps / steps_per_day
        recovery_steps = max(
            1, int(round(drop / float(block["fault_recovery_per_day"]) * steps_per_day))
        )
        ramp = drop * (1.0 - np.arange(recovery_steps, dtype=float) / recovery_steps)
        rng = self.simulation.rng(f"{HEALTH_STREAM}:{dataset}")
        faults: list[HealthFault] = []
        clock = 0.0
        while True:
            clock += float(rng.exponential(1.0 / rate))
            if clock >= horizon_days:
                break
            start = int(clock * steps_per_day)
            end = min(steps, start + recovery_steps)
            deficit[start:end] += ramp[: end - start]
            faults.append(HealthFault(dataset, start, end - start, drop))
        return deficit, tuple(faults)

    def plan_all(self) -> Mapping[DatasetName, HealthTrajectory]:
        """The trajectory of both units, keyed by dataset."""
        return {dataset: self.plan(dataset) for dataset in ("kiln", "mill")}

    def health_at(
        self, trajectories: Mapping[DatasetName, HealthTrajectory], step: int
    ) -> dict[str, float]:
        """The ``set_health`` payload for one step, keyed as the twins expect (PRD 9.5)."""
        return {
            trajectory.key: float(trajectory.values[step])
            for trajectory in trajectories.values()
        }

    # -- provenance ---------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """JSON-serializable record of the health settings, for the PRD 11.6 sidecar."""
        return {
            dataset: {key: float(block[key]) for key in _REQUIRED_KEYS}
            for dataset, block in self._settings.items()
        }


__all__ = [
    "FAULT_COLUMN",
    "HEALTH_COLUMN",
    "HEALTH_KEYS",
    "HEALTH_STREAM",
    "EquipmentHealthProcess",
    "HealthFault",
    "HealthTrajectory",
]

