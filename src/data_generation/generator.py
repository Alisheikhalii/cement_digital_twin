"""``DatasetGenerator`` - the PRD v1.1.1 Section 11.2 simulation loop that produces the datasets.

The generator owns no physics and no randomness of its own. It wires together the four objects
that do, in the order PRD 11.2 lays down:

1. :class:`~src.simulation.scheduler.ScenarioScheduler` plans the run - regime episodes, ramped
   setpoints, Poisson disturbances and the ground-truth labels (PRD 11.3/11.4);
2. :class:`~src.data_generation.health.EquipmentHealthProcess` plans the slow wear scalar and
   its occasional mechanical-fault dip (PRD 9.5);
3. :class:`~src.process_models.plant.PlantTwin` is stepped once per row, giving the *true*
   noise-free process state and the two PRD 9.3/10.2 conservation residuals;
4. :class:`~src.simulation.sensors.SensorModel` turns that true state into what a historian
   would actually have stored (PRD 11.5).

Three consequences of the PRD worth stating up front, because they shape the output:

* **The warm-up window never leaves this module.** PRD 11.2 discards it, so the twin is stepped
  over the whole run but every exported frame is sliced to ``schedule.export_mask`` *before* the
  sensor model runs. Lengthening ``warmup_minutes`` therefore cannot shift a single measured
  number (NFR-4) - the same convention the scheduler and the health process already follow.
* **``commanded`` is what the instruments see.** Regime 8's unmeasured feed disturbance and PRD
  11.3's fuel-quality swing are, by definition, invisible to the DCS: the twin is driven with
  ``schedule.inputs`` while the dataset's setpoint-feedback tags carry ``schedule.commanded``.
  The true (driven) values stay in the ground-truth frame, which is what makes those two events
  learnable-but-not-labelled the way a real unmeasured disturbance is.
* **``equipment_health`` / ``equipment_fault`` are ground truth, not dataset columns.** PRD
  12.1/12.2's column tables end at ``operating_regime`` / ``injected_fault``, so the health
  scalar and its fault flag are exported beside the dataset, never inside it.

``run`` is a pure function of the configs and the seed: no wall-clock, no global RNG, no
filesystem access (:mod:`src.data_generation.export` does the writing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

import numpy as np
import pandas as pd

from src import schema
from src.config import KILN, MILL, SCENARIOS, Config, ConfigError, load_config
from src.data_generation.health import (
    FAULT_COLUMN,
    HEALTH_COLUMN,
    EquipmentHealthProcess,
    HealthTrajectory,
)
from src.process_models.plant import PlantTwin
from src.schema import DatasetName
from src.simulation.scheduler import SETPOINTS, ScenarioSchedule, ScenarioScheduler
from src.simulation.sensors import SensorModel, SensorOutcome
from src.simulation.simulation_config import SimulationConfig

#: Datasets produced by one run, in PRD 12 order.
DATASETS: Final[tuple[DatasetName, ...]] = ("kiln", "mill")

#: Config flag of PRD 12.1's note: add the two conservation residuals to the exported dataset.
DEBUG_BALANCE_FLAG: Final = "debug_balance_export"

#: Ground-truth columns copied out of the scheduler's label frame (PRD 11.4).
_LABEL_COLUMNS: Final[tuple[str, ...]] = (
    "episode_index",
    "is_startup",
    "sensor_drift_progress",
)

#: Per-dataset conservation residuals, published in the ground-truth frame (PRD 9.3/10.2).
_RESIDUAL_COLUMNS: Final[Mapping[DatasetName, tuple[str, ...]]] = {
    "kiln": ("energy_balance_residual_pct", "mass_balance_residual_pct"),
    "mill": ("mass_balance_residual_pct",),
}

#: Residual column -> the key the twins publish it under in ``balance_residuals``.
_RESIDUAL_SOURCE: Final[Mapping[str, str]] = {
    "energy_balance_residual_pct": "energy_pct",
    "mass_balance_residual_pct": "mass_pct",
}

#: Absolute energy-closure diagnostics carried in the *trajectory* frame and nowhere else.
#:
#: NFR-10's percentage metric divides the unaccounted loss by the instantaneous input basis, and
#: on a PRD 11.4 startup ramp that basis collapses toward zero while the preheater outlet coasts
#: behind its dead time - a ratio to a vanishing input diverges arithmetically even though the
#: absolute loss stays small. :mod:`src.data_generation.conservation` therefore needs the
#: numerator and the denominator separately, plus the reference point's fixed input basis as a
#: numerically stable alternative denominator. These are diagnostics of the *simulation*, not
#: plant measurements: they stay out of ``_RESIDUAL_COLUMNS``, so neither the PRD 12.1 debug
#: dataset variant nor the PRD 12.2 ground-truth contract gains a column.
_ENERGY_DIAGNOSTIC_KEYS: Final[tuple[str, ...]] = (
    "kiln_unaccounted_loss_MJ_per_h",
    "kiln_energy_input_MJ_per_h",
    "kiln_reference_energy_input_MJ_per_h",
)


# =============================================================================
# The result of one run
# =============================================================================
@dataclass(frozen=True, slots=True)
class GeneratedRun:
    """Everything one seeded run produces (PRD 11.2 output, 11.6 provenance).

    ``datasets`` are the historian-style frames of PRD 12.1/12.2 - measured, warm-up already
    discarded, columns in the documented order with ``timestamp`` first. ``truth`` holds the
    noise-free state of the same rows plus the labels, the equipment-health ground truth, the
    unmeasured disturbances and the conservation residuals, which is what PRD 34 item 2 means by
    "evaluated against the simulator's own true state, not just the noisy measurement".
    """

    simulation: SimulationConfig
    schedule: ScenarioSchedule
    datasets: Mapping[DatasetName, pd.DataFrame]
    truth: Mapping[DatasetName, pd.DataFrame]
    health: Mapping[DatasetName, HealthTrajectory]
    sensors: Mapping[DatasetName, SensorOutcome]
    provenance: Mapping[str, Any]

    @property
    def index(self) -> pd.DatetimeIndex:
        """Exported timestamps (the warm-up rows are already gone)."""
        return pd.DatetimeIndex(self.datasets["kiln"][schema.TIMESTAMP_COLUMN])

    def describe(self) -> dict[str, Any]:
        """JSON-serializable summary of the run; the body of the PRD 11.6 sidecar."""
        return {
            **self.provenance,
            "schedule": self.schedule.describe(),
            "datasets": {
                dataset: {
                    "rows": int(len(frame)),
                    "columns": list(frame.columns),
                    "missing_total": int(self.sensors[dataset].missing_total),
                    "stuck_events": len(self.sensors[dataset].stuck_events),
                    "health": self.health[dataset].describe(),
                }
                for dataset, frame in self.datasets.items()
            },
        }

    def sidecar(self, dataset: DatasetName) -> dict[str, Any]:
        """The JSON sidecar of one dataset (PRD 11.6: saved alongside every export)."""
        if dataset not in self.datasets:
            raise ConfigError(f"unknown dataset {dataset!r}; expected one of {list(DATASETS)}")
        return {
            **self.provenance,
            "dataset": dataset,
            "rows": int(len(self.datasets[dataset])),
            "columns": list(self.datasets[dataset].columns),
            "truth_columns": list(self.truth[dataset].columns),
            "schedule": self.schedule.describe(),
            "sensor_outcome": self.sensors[dataset].describe(),
            "equipment_health": self.health[dataset].describe(),
        }



# =============================================================================
# The generator
# =============================================================================
class DatasetGenerator:
    """Runs the PRD 11.2 loop: plan -> step the twin -> measure -> label."""

    def __init__(
        self,
        simulation: SimulationConfig | None = None,
        *,
        scenarios: Config | None = None,
        kiln_config: Config | None = None,
        mill_config: Config | None = None,
    ) -> None:
        self._scenarios = scenarios if scenarios is not None else load_config(SCENARIOS)
        self._configs: Mapping[DatasetName, Config] = {
            "kiln": kiln_config if kiln_config is not None else load_config(KILN),
            "mill": mill_config if mill_config is not None else load_config(MILL),
        }
        self.simulation = (
            simulation
            if simulation is not None
            else SimulationConfig.from_config(self._scenarios)
        )
        self.scheduler = ScenarioScheduler(
            self.simulation,
            scenarios=self._scenarios,
            kiln_config=self._configs["kiln"],
            mill_config=self._configs["mill"],
        )
        self.equipment_health = EquipmentHealthProcess(
            self.simulation,
            kiln_config=self._configs["kiln"],
            mill_config=self._configs["mill"],
        )
        self.sensor_model = SensorModel(self.simulation, scenarios=self._scenarios)
        self.twin = PlantTwin(self._configs["kiln"], self._configs["mill"])

    # -- the exported column contract ----------------------------------------------------
    @property
    def configs(self) -> Mapping[DatasetName, Config]:
        """The per-unit configs this generator is running on (read-only).

        Exposed because a validator has to read the tolerances and delays of *this* run rather
        than re-loading ``configs/*.yaml``: a test that hands the generator a deliberately broken
        closure must be judged against the config it was given.
        """
        return self._configs

    def debug_balance(self, dataset: DatasetName) -> bool:
        """PRD 12.1's note: is the debug residual variant switched on for this unit?"""
        return bool(self._configs[dataset].get(DEBUG_BALANCE_FLAG, False))

    def dataset_columns(self, dataset: DatasetName) -> tuple[str, ...]:
        """Columns of one exported dataset, in PRD 12 order.

        The debug variant appends only the residuals the unit actually closes: PRD 10.2 gives
        the mill a mass balance and no energy balance, so its debug variant carries one extra
        column where the kiln's carries two.
        """
        columns = schema.columns_for(dataset)
        return columns + _RESIDUAL_COLUMNS[dataset] if self.debug_balance(dataset) else columns

    # -- the simulation loop (PRD 11.2 step 3) -------------------------------------------
    def run_trajectory(
        self,
        schedule: ScenarioSchedule | None = None,
        trajectories: Mapping[DatasetName, HealthTrajectory] | None = None,
    ) -> pd.DataFrame:
        """Step the twin once per planned row and return the true state of the whole run.

        This is the generator's own loop rather than ``PlantTwin.simulate_scenario`` for one
        reason: PRD 9.5's health scalar changes between steps, and ``set_health`` is the only
        way in. With a constant health the two produce identical numbers, which the test suite
        pins - the loop adds no physics, it only interleaves the health update.
        """
        schedule = schedule if schedule is not None else self.scheduler.build()
        trajectories = (
            trajectories if trajectories is not None else self.equipment_health.plan_all()
        )
        dt_seconds = float(self.simulation.dt_seconds)
        variables: list[str] = []
        blocks: list[np.ndarray] = []
        for dataset in DATASETS:
            frame = schedule.inputs[dataset]
            variables.extend(str(column) for column in frame.columns)
            blocks.append(frame.to_numpy(dtype=float))
        driven = np.hstack(blocks) if blocks else np.zeros((len(schedule.index), 0))
        health_keys = [trajectories[dataset].key for dataset in DATASETS]
        health = np.column_stack([trajectories[dataset].values for dataset in DATASETS])
        if health.shape[0] != driven.shape[0]:
            raise ConfigError(
                f"the health plan has {health.shape[0]} steps but the schedule has "
                f"{driven.shape[0]} (PRD 11.2: both are planned over the same run)"
            )
        twin = self.twin
        twin.reset()
        records: list[dict[str, float]] = []
        for row in range(driven.shape[0]):
            twin.set_health(dict(zip(health_keys, health[row])))
            outputs = dict(twin.simulation_step(dict(zip(variables, driven[row])), dt_seconds))
            residuals = twin.balance_residuals
            for dataset in DATASETS:
                for column in _RESIDUAL_COLUMNS[dataset]:
                    key = f"{dataset}_{_RESIDUAL_SOURCE[column]}"
                    outputs[key] = float(residuals.get(key, 0.0))
            for key in _ENERGY_DIAGNOSTIC_KEYS:
                outputs[key] = float(residuals.get(key, 0.0))
            records.append(outputs)
        return pd.DataFrame(records, index=schedule.index)

    # -- frame assembly ------------------------------------------------------------------
    def _visible_frame(
        self, state: pd.DataFrame, schedule: ScenarioSchedule, dataset: DatasetName
    ) -> pd.DataFrame:
        """The true state as the *instruments* see it, before the sensor model runs.

        Every numeric column comes from the twin, except the setpoint-feedback tags: those carry
        ``schedule.commanded``, because regime 8's unmeasured feed disturbance and PRD 11.3's
        fuel-quality swing are by definition invisible to the DCS. The driven values stay in the
        ground-truth frame.
        """
        columns: dict[str, Any] = {
            tag: state[tag].to_numpy(dtype=float) for tag in schema.numeric_columns(dataset)
        }
        for spec in SETPOINTS:
            if spec.dataset == dataset and spec.tag in columns:
                columns[spec.tag] = schedule.commanded[dataset][spec.variable].to_numpy(
                    dtype=float
                )
        return pd.DataFrame(columns, index=state.index)

    def _dataset_frame(
        self,
        measured: pd.DataFrame,
        state: pd.DataFrame,
        schedule: ScenarioSchedule,
        dataset: DatasetName,
    ) -> pd.DataFrame:
        """One historian-style dataset: measurements, the two labels, ``timestamp`` first."""
        labels = schedule.exported(schedule.dataset_labels(dataset))
        frame = measured.copy()
        frame[schema.REGIME_LABEL_COLUMN] = labels[schema.REGIME_LABEL_COLUMN]
        frame[schema.FAULT_LABEL_COLUMN] = labels[schema.FAULT_LABEL_COLUMN]
        if self.debug_balance(dataset):
            exported = schedule.exported(state)
            for column in _RESIDUAL_COLUMNS[dataset]:
                frame[column] = exported[f"{dataset}_{_RESIDUAL_SOURCE[column]}"]
        frame.insert(0, schema.TIMESTAMP_COLUMN, frame.index)
        return frame.reset_index(drop=True)[list(self.dataset_columns(dataset))]

    def _truth_frame(
        self,
        state: pd.DataFrame,
        schedule: ScenarioSchedule,
        trajectory: HealthTrajectory,
        dataset: DatasetName,
    ) -> pd.DataFrame:
        """The ground truth of the same rows (PRD 12.2 keeps all of this out of the dataset).

        Noise-free tag values (the *driven* ones, so an unmeasured disturbance is visible here
        and nowhere else), the conservation residuals, PRD 9.5's health scalar and fault flag,
        the plant-level unmeasured disturbances and the episode bookkeeping.
        """
        exported = schedule.exported(state)
        columns: dict[str, Any] = {
            tag: exported[tag].to_numpy(dtype=float) for tag in schema.numeric_columns(dataset)
        }
        for column in _RESIDUAL_COLUMNS[dataset]:
            columns[column] = exported[f"{dataset}_{_RESIDUAL_SOURCE[column]}"].to_numpy(
                dtype=float
            )
        frame = pd.DataFrame(columns, index=exported.index)
        health = schedule.exported(trajectory.frame(schedule.index))
        frame[HEALTH_COLUMN] = health[HEALTH_COLUMN]
        frame[FAULT_COLUMN] = health[FAULT_COLUMN]
        for column in schedule.ground_truth.columns:
            frame[column] = schedule.exported(schedule.ground_truth)[column]
        labels = schedule.exported(schedule.labels)
        frame[schema.REGIME_LABEL_COLUMN] = labels[schema.REGIME_LABEL_COLUMN]
        frame[schema.FAULT_LABEL_COLUMN] = labels[f"injected_fault_{dataset}"]
        for column in _LABEL_COLUMNS:
            frame[column] = labels[column]
        frame.insert(0, schema.TIMESTAMP_COLUMN, frame.index)
        return frame.reset_index(drop=True)

    # -- the run (PRD 11.2) --------------------------------------------------------------
    def run(self) -> GeneratedRun:
        """Generate both datasets and their ground truth from the configs and the seed alone."""
        schedule = self.scheduler.build()
        trajectories = self.equipment_health.plan_all()
        state = self.run_trajectory(schedule, trajectories)
        progress = schedule.exported(schedule.labels)["sensor_drift_progress"]
        datasets: dict[DatasetName, pd.DataFrame] = {}
        truth: dict[DatasetName, pd.DataFrame] = {}
        outcomes: dict[DatasetName, SensorOutcome] = {}
        for dataset in DATASETS:
            # The sensor model runs on the exported rows only, so `warmup_minutes` cannot shift
            # a single measured number (NFR-4) - the same rule the scheduler and health use.
            visible = schedule.exported(self._visible_frame(state, schedule, dataset))
            outcome = self.sensor_model.apply(visible, dataset, drift_progress=progress)
            outcomes[dataset] = outcome
            datasets[dataset] = self._dataset_frame(outcome.frame, state, schedule, dataset)
            truth[dataset] = self._truth_frame(state, schedule, trajectories[dataset], dataset)
        return GeneratedRun(
            simulation=self.simulation,
            schedule=schedule,
            datasets=datasets,
            truth=truth,
            health=trajectories,
            sensors=outcomes,
            provenance=self.provenance(),
        )

    # -- provenance (PRD 11.6) -----------------------------------------------------------
    def provenance(self) -> dict[str, Any]:
        """The config actually used, JSON-serializable, for the PRD 11.6 sidecar.

        Deliberately free of wall-clock time: everything a run produces has to be a pure
        function of the configs and the seed (NFR-4), sidecars included, so that a regression
        test can compare two runs byte for byte.
        """
        return {
            "prd_version": str(self._scenarios.get_path("meta.prd_version") or "unknown"),
            "simulation": self.simulation.describe(),
            "sensor_model": self.sensor_model.describe(),
            "equipment_health": self.equipment_health.describe(),
            "configs": {
                "scenarios": self._scenarios.to_dict(),
                "kiln_dynamics": self._configs["kiln"].to_dict(),
                "mill_dynamics": self._configs["mill"].to_dict(),
            },
        }


__all__ = [
    "DATASETS",
    "DEBUG_BALANCE_FLAG",
    "DatasetGenerator",
    "GeneratedRun",
]





