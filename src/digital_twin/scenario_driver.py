"""Interactive single-regime driver (PRD v1.1.1 19.2; Task #6 directive items 7, 18).

The offline pipeline plans a whole 30-day run before it steps the twin once. A dashboard cannot:
the operator presses PLAY, watches, switches scenario and presses PLAY again. This module is that
mode - and it is deliberately *thin*. Every number it produces comes from a component the test
suite already pins:

* setpoint trajectories from :meth:`ScenarioScheduler.step_variable` (the same per-step rule
  :meth:`ScenarioScheduler.build` runs, called once per variable per step instead of per row),
* physics from :meth:`PlantTwin.simulation_step`,
* equipment health from :meth:`EquipmentHealthProcess.health_at`,
* the observable channel from :meth:`SensorModel.apply`.

No process equation, limit or noise parameter is re-implemented here.

Three ASSUMPTIONs, recorded in ``SIMULATION_ASSUMPTIONS.md`` because PRD 19.2 leaves interactive
mode's bookkeeping open:

* the selected regime is held for the *mean* of its configured ``dwell_hours``, which is what
  the progress-driven effects (regime 8's ``step_then_ramp_back`` envelope and regime 14's drift
  ramp) are scaled against; past that the regime holds at full progress rather than ending, so a
  demonstration can dwell in a scenario as long as the presenter needs;
* the Poisson-arrival plant disturbances of PRD 11.3 (feed-moisture pulses, fuel-LHV swings) and
  the ambient random walk stay in the offline path: they are drawn over a whole planned run, so
  live mode runs without them and the dashboard says so rather than inventing arrivals;
* live mode is bounded by ``clock.max_live_steps`` in ``configs/dashboard.yaml``; the equipment
  health trajectory is read from the planned run, so a live session ages the plant exactly as the
  first ``max_live_steps`` steps of an offline run would.

Determinism (NFR-4, directive item 22): every step is a pure function of the configs, the seed,
the selected regime and the number of steps taken since :meth:`reset`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping

import numpy as np
import pandas as pd

from src import schema
from src.config import KILN, MILL, SCENARIOS, Config, ConfigError, load_config
from src.data_generation.generator import DATASETS
from src.data_generation.health import EquipmentHealthProcess, HealthTrajectory
from src.process_models.plant import PlantTwin
from src.schema import DatasetName
from src.simulation.scheduler import (
    OSCILLATION_STREAM,
    SETPOINTS,
    RampedSetpoint,
    RegimeEpisode,
    ScenarioScheduler,
)
from src.simulation.sensors import SensorModel
from src.simulation.simulation_config import SimulationConfig

#: Hours -> steps needs the step length, so the conversion lives with the driver.
_MINUTES_PER_HOUR: Final = 60.0
_SECONDS_PER_MINUTE: Final = 60.0


@dataclass(frozen=True, slots=True)
class DriverStep:
    """One simulated minute, with the four channels kept apart at the source.

    ``true_state`` is the twin's own state and ``observed`` is what the instruments report: the
    provider tags them :data:`Provenance.TRUTH` and :data:`Provenance.OBSERVED` respectively and
    never merges them. ``inputs`` are the *driven* setpoints (they carry regime 8's unmeasured
    disturbance) while ``commanded`` are the values a DCS faceplate would show.
    """

    step: int
    timestamp: pd.Timestamp
    regime: str
    regime_id: int | None
    sensor_layer_only: bool
    drift_progress: float
    progress: float
    inputs: Mapping[str, float]
    commanded: Mapping[str, float]
    true_state: Mapping[str, float]
    observed: Mapping[DatasetName, Mapping[str, float]]
    residuals: Mapping[str, float]
    health: Mapping[str, float]
    faults: Mapping[DatasetName, str | None] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "timestamp": str(self.timestamp),
            "regime": self.regime,
            "regime_id": self.regime_id,
            "sensor_layer_only": self.sensor_layer_only,
            "drift_progress": self.drift_progress,
            "progress": self.progress,
            "faults": dict(self.faults),
            "health": dict(self.health),
        }


class ScenarioDriver:
    """Holds one selected regime and steps the plant through it, one minute at a time."""

    def __init__(
        self,
        *,
        simulation: SimulationConfig | None = None,
        scenarios: Config | None = None,
        kiln_config: Config | None = None,
        mill_config: Config | None = None,
        regime: str | int | None = None,
        max_steps: int | None = None,
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
        self._trajectories: Mapping[DatasetName, HealthTrajectory] = (
            self.equipment_health.plan_all()
        )
        planned = int(self.simulation.total_steps)
        self._max_steps = min(planned, int(max_steps)) if max_steps else planned
        self._regime_id = self._resolve(regime) if regime is not None else self._default_regime()
        self._episode = self._episode_for(self._regime_id)
        self.reset()

    # -- scenario selection (directive item 18: configured scenarios only) ----------------
    def _default_regime(self) -> int:
        """The regime the dashboard opens in: the startup block's target (PRD 11.4)."""
        return int(self.scheduler.startup["target_regime_id"])

    def _resolve(self, regime: str | int) -> int:
        """Accept a regime id or its configured name; refuse anything else."""
        if isinstance(regime, bool):
            raise ConfigError(f"{regime!r} is not a regime id or name")
        if isinstance(regime, (int, np.integer)):
            return int(self.scheduler.regime(int(regime))["id"])
        return int(self.scheduler.regime_by_name(str(regime))["id"])

    def _episode_for(self, regime_id: int) -> RegimeEpisode:
        """Hold ``regime_id`` for the mean of its configured dwell (ASSUMPTION, see module doc)."""
        regime = self.scheduler.regime(regime_id)
        low, high = (float(value) for value in regime["dwell_hours"])
        minutes = 0.5 * (low + high) * _MINUTES_PER_HOUR
        steps = max(1, int(round(minutes * self.simulation.steps_per_minute)))
        return self.scheduler.episode_for(regime_id, steps=steps)

    def scenario_options(self) -> tuple[dict[str, Any], ...]:
        """The selectable scenarios, read from ``configs/scenarios.yaml`` and nothing else."""
        return tuple(
            {
                "id": int(regime["id"]),
                "name": str(regime["name"]),
                "injected_fault": regime.get("injected_fault"),
                "affects": list(regime.get("affects", ())),
                "sensor_layer_only": bool(regime.get("sensor_layer_only", False)),
                "setpoints": dict(regime.get("setpoints", {})),
                "oscillation": regime.get("oscillation") is not None,
                "unmeasured_disturbance": regime.get("unmeasured_disturbance") is not None,
                "dwell_hours": [float(value) for value in regime["dwell_hours"]],
            }
            for regime in self.scheduler.regimes
        )

    def select(self, regime: str | int) -> None:
        """Switch the driving regime. The plant keeps its state; the setpoints ramp (PRD 11.3).

        This is what makes a scenario change a *process* event rather than a redraw: the ramps
        carry their current value into the new episode, so the twin transitions through the same
        coordinated ramp the offline run would have taken.
        """
        regime_id = self._resolve(regime)
        if regime_id == self._regime_id:
            return
        self._regime_id = regime_id
        self._episode = self._episode_for(regime_id)
        self._episode_step = 0

    # -- session state --------------------------------------------------------------------
    def reset(self) -> None:
        """Return to step 0: twin at its reference point, ramps settled, RNG streams re-drawn."""
        self.twin.reset()
        self._episode = self._episode_for(self._regime_id)
        self._episode_step = 0
        self._step_index = 0
        self._oscillation_rng = self.simulation.rng(OSCILLATION_STREAM)
        self._ramps: dict[str, RampedSetpoint] = {
            spec.variable: RampedSetpoint(
                self.scheduler.reference_value(spec), self.scheduler.ramp_minutes(spec)
            )
            for spec in SETPOINTS
        }
        self._timestamps: list[pd.Timestamp] = []
        self._drift: list[float] = []
        self._regimes: list[str] = []
        self._faults: dict[DatasetName, list[str | None]] = {d: [] for d in DATASETS}
        self._visible: dict[DatasetName, list[dict[str, float]]] = {d: [] for d in DATASETS}
        self._measured: dict[DatasetName, pd.DataFrame] = {
            dataset: pd.DataFrame() for dataset in DATASETS
        }
        self._truth_rows: list[dict[str, float]] = []
        self._latest: DriverStep | None = None

    @property
    def regime_id(self) -> int:
        return self._regime_id

    @property
    def regime_name(self) -> str:
        return str(self.scheduler.regime(self._regime_id)["name"])

    @property
    def steps_taken(self) -> int:
        return self._step_index

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def dt_minutes(self) -> float:
        return float(self.simulation.dt_seconds) / _SECONDS_PER_MINUTE

    def latest(self) -> DriverStep:
        """The current step, taking one if the session has not started yet."""
        if self._latest is None:
            return self.step()
        return self._latest

    # -- the step (PRD 11.2's loop, one minute at a time) ---------------------------------
    def step(self, steps: int = 1) -> DriverStep:
        """Advance the plant by ``steps`` simulated steps and return the last one.

        The twin is stepped once per simulated minute; the instrument layer is applied once for
        the whole batch. That is exact rather than an approximation - the noise draws of a
        length-n frame are the first n draws of a length-(n+k) frame - and it keeps a 10x clock
        tick as cheap as a 1x one (directive item 23).
        """
        rows = [self._advance_state() for _ in range(max(1, int(steps)))]
        observed = self._measure_pending()
        last = rows[-1]
        self._latest = DriverStep(
            step=int(last["step"]),
            timestamp=last["timestamp"],
            regime=str(last["regime"]),
            regime_id=last["regime_id"],
            sensor_layer_only=bool(last["sensor_layer_only"]),
            drift_progress=float(last["drift_progress"]),
            progress=float(last["progress"]),
            inputs=last["inputs"],
            commanded=last["commanded"],
            true_state=last["true_state"],
            observed=observed,
            residuals=last["residuals"],
            health=last["health"],
            faults=last["faults"],
        )
        return self._latest

    def _advance_state(self) -> dict[str, Any]:
        """One simulated minute of setpoints and physics. No measurement happens here."""
        if self._step_index >= self._max_steps:
            raise ConfigError(
                f"live session reached its {self._max_steps}-step bound "
                "(clock.max_live_steps in configs/dashboard.yaml); RESET to continue"
            )
        row = self._step_index
        episode_row = self._episode_step
        dt_minutes = self.dt_minutes
        elapsed_minutes = episode_row * dt_minutes
        progress = min(1.0, (episode_row + 1) / self._episode.steps)

        driven: dict[str, float] = {}
        commanded: dict[str, float] = {}
        for spec in SETPOINTS:
            value, commanded_value = self.scheduler.step_variable(
                spec,
                self._episode,
                self._ramps[spec.variable],
                dt_minutes=dt_minutes,
                elapsed_minutes=elapsed_minutes,
                progress=progress,
                oscillation_rng=self._oscillation_rng,
            )
            driven[spec.variable] = value
            commanded[spec.tag] = commanded_value

        health = self.equipment_health.health_at(self._trajectories, row)
        self.twin.set_health(health)
        true_state = dict(self.twin.simulation_step(driven, float(self.simulation.dt_seconds)))
        residuals = dict(self.twin.balance_residuals)

        timestamp = self.simulation.start_timestamp + row * self.simulation.step
        self._timestamps.append(timestamp)
        self._truth_rows.append(true_state)
        self._drift.append(progress if self._episode.sensor_layer_only else 0.0)
        self._regimes.append(self._episode.name)
        faults = {dataset: self._episode.fault_for(dataset) for dataset in DATASETS}
        for dataset, fault in faults.items():
            self._faults[dataset].append(fault)
        self._queue_visible(true_state, commanded)

        self._step_index += 1
        self._episode_step += 1
        return {
            "step": row,
            "timestamp": timestamp,
            "regime": self._episode.name,
            "regime_id": self._episode.regime_id,
            "sensor_layer_only": self._episode.sensor_layer_only,
            "drift_progress": self._drift[-1],
            "progress": progress,
            "inputs": driven,
            "commanded": commanded,
            "true_state": true_state,
            "residuals": residuals,
            "health": health,
            "faults": faults,
        }

    def _queue_visible(
        self, true_state: Mapping[str, float], commanded: Mapping[str, float]
    ) -> None:
        """Record the row the instruments will see: twin state, with commanded setpoints."""
        for dataset in DATASETS:
            visible = {tag: float(true_state[tag]) for tag in schema.numeric_columns(dataset)}
            for spec in SETPOINTS:
                # A setpoint's feedback tag reports what the DCS asked for: PRD 11.4's
                # unmeasured disturbance is by definition invisible to the instrument.
                if spec.dataset == dataset and spec.tag in visible:
                    visible[spec.tag] = float(commanded[spec.tag])
            self._visible[dataset].append(visible)

    def _measure_pending(self) -> dict[DatasetName, dict[str, float]]:
        """Run the validated instrument layer over the session so far; keep the last row.

        The sensor model is frame-based (its lag is a filter down the column and its noise draw is
        sized by the frame), so it is re-applied to the whole session rather than re-implemented
        per row. Rows already displayed do not move: the draws of a length-n call are the first n
        draws of a longer call, which is what makes this reuse exact instead of merely similar.
        """
        index = pd.DatetimeIndex(self._timestamps)
        progress = np.asarray(self._drift, dtype=float)
        observed: dict[DatasetName, dict[str, float]] = {}
        for dataset in DATASETS:
            rows = self._visible[dataset]
            frame = pd.DataFrame(
                {column: [row[column] for row in rows] for column in rows[0]}, index=index
            )
            outcome = self.sensor_model.apply(frame, dataset, drift_progress=progress)
            self._measured[dataset] = outcome.frame
            observed[dataset] = {
                str(tag): float(value) for tag, value in outcome.frame.iloc[-1].items()
            }
        return observed

    # -- the session's history ------------------------------------------------------------
    def observed_history(self, dataset: DatasetName) -> pd.DataFrame:
        """Every measured row of the session so far (OBSERVED channel).

        The two PRD 12.1 label columns are appended so a live frame has the same shape as an
        exported one: :func:`src.features.lag_features.feature_row` one-hots ``operating_regime``,
        and a live session that omitted it would hand Model A a different feature vector than the
        same row read back from a CSV. They are labels of the driving regime, not measurements -
        the same status the offline exporter gives them.
        """
        frame = self._measured[dataset]
        if frame.empty:
            return frame
        labelled = frame.copy()
        labelled[schema.REGIME_LABEL_COLUMN] = self._regimes
        labelled[schema.FAULT_LABEL_COLUMN] = self._faults[dataset]
        return labelled

    def truth_history(self, dataset: DatasetName) -> pd.DataFrame:
        """The same rows as the twin knows them, noise-free (TRUTH channel)."""
        if not self._truth_rows:
            return pd.DataFrame()
        columns = list(schema.numeric_columns(dataset))
        index = pd.DatetimeIndex(self._timestamps)
        return pd.DataFrame(
            {column: [row[column] for row in self._truth_rows] for column in columns},
            index=index,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "regime_id": self._regime_id,
            "regime": self.regime_name,
            "steps_taken": self._step_index,
            "max_steps": self._max_steps,
            "dt_minutes": self.dt_minutes,
            "episode_steps": self._episode.steps,
            "seed": int(self.simulation.seed),
            "scenarios": [option["name"] for option in self.scenario_options()],
        }


__all__ = ["DriverStep", "ScenarioDriver"]




