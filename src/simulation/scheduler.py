"""``ScenarioScheduler`` - the 14 mandatory operating regimes (PRD v1.1.1 11.3, 11.4).

The scheduler is the only component that decides *what the plant is asked to do* at each
minute. It turns the declarative ``regime_schedule:`` block of ``configs/scenarios.yaml`` into

* one input trajectory per line, in the spelling the twins' ``inputs`` dicts use,
* the *commanded* trajectory, which differs from the above wherever a regime injects an
  effect the instruments cannot see (PRD 11.4 "unmeasured disturbance"),
* the ``operating_regime`` / ``injected_fault`` ground-truth labels of PRD 12.1/12.2, and
* the disturbance ground truth (ambient temperature, moisture swing, fuel LHV swing).

Three properties are deliberate and tested:

**Ratios, not absolutes.** Every regime setpoint in the config is a ratio of (or a delta on) the
reference operating point solved from the energy balance, so editing a reference constant can
never leave a regime definition silently inconsistent with the physics.

**Ramped, never stepped.** PRD 11.3 requires setpoint changes to be smooth. Each variable has
its own minimum ramp time from ``ramp_times_min:``, so a regime change is a coordinated set of
ramps rather than one instantaneous jump.

**Deterministic for a seed.** Episode lengths, disturbance arrivals and per-episode signs are
drawn from named substreams of :class:`~src.simulation.simulation_config.SimulationConfig`, so
the whole plan is a pure function of ``(config, seed)`` as NFR-4 requires.

ASSUMPTIONs introduced here (recorded in ``SIMULATION_ASSUMPTIONS.md``, PRD 11.3/11.4 leave
them open):

* a variable a regime does not name returns to its reference value (ratio 1.0), so the
  ``operating_regime`` label fully determines the intended operating point;
* the same regime is never scheduled twice in a row (the second-largest share deficit is used
  instead), so an episode boundary is always a real change of intent;
* the warm-up window runs at the reference operating point and is discarded before export;
* overlapping disturbance events of the same kind add up, then clip to the configured band.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Sequence

import numpy as np
import pandas as pd

from src.config import KILN, MILL, SCENARIOS, Config, ConfigError, load_config
from src.process_models import kiln_reference, mill_reference
from src.schema import DatasetName, FAULT_LABEL_COLUMN, REGIME_LABEL_COLUMN
from src.simulation.simulation_config import MINUTES_PER_DAY, SimulationConfig

#: Label of the simulated-but-discarded warm-up rows. Never reaches an exported dataset.
WARMUP_LABEL: Final = "Warm-up (discarded)"

#: Named RNG substreams (NFR-4: one independent generator per stochastic component).
DWELL_STREAM: Final = "regime_dwell"
EPISODE_SIGN_STREAM: Final = "regime_sign"
MOISTURE_STREAM: Final = "disturbance_feed_moisture"
FUEL_QUALITY_STREAM: Final = "disturbance_fuel_quality"
AMBIENT_STREAM: Final = "disturbance_ambient_temperature"
OSCILLATION_STREAM: Final = "regime_oscillation_noise"


# =============================================================================
# The manipulated / disturbance variables the scheduler drives (PRD 9.1, 10.1)
# =============================================================================
@dataclass(frozen=True, slots=True)
class SetpointSpec:
    """One scheduled variable: its twin-input name, its dataset tag and its config keys.

    ``variable`` and ``tag`` differ for four variables (``ID_fan_speed_pct`` vs the PRD 12.1
    tag ``ID_fan_speed``, and likewise for the raw-meal pair and the mill fan/speed pair).
    The distinction is load-bearing: :meth:`UnitBase.input_value` returns the *first present*
    alias, and the twins pre-seed the ``_pct``/``_C`` spellings, so a trajectory written in tag
    spelling would be silently ignored instead of failing loudly.
    """

    variable: str
    tag: str
    dataset: DatasetName
    ramp_key: str
    reference_attr: str
    ratio_key: str | None = None
    delta_key: str | None = None


KILN_SETPOINTS: Final[tuple[SetpointSpec, ...]] = (
    SetpointSpec("kiln_feed_rate_tph", "kiln_feed_rate_tph", "kiln", "kiln_feed_rate_tph",
                 "feed_rate_tph", ratio_key="kiln_feed_ratio"),
    SetpointSpec("kiln_fuel_rate_tph", "kiln_fuel_rate_tph", "kiln", "kiln_fuel_rate_tph",
                 "kiln_fuel_rate_tph", ratio_key="kiln_fuel_ratio"),
    SetpointSpec("calciner_fuel_rate_tph", "calciner_fuel_rate_tph", "kiln",
                 "calciner_fuel_rate_tph", "calciner_fuel_rate_tph",
                 ratio_key="calciner_fuel_ratio"),
    SetpointSpec("kiln_speed_rpm", "kiln_speed_rpm", "kiln", "kiln_speed_rpm", "kiln_speed_rpm",
                 ratio_key="kiln_speed_ratio"),
    SetpointSpec("ID_fan_speed_pct", "ID_fan_speed", "kiln", "ID_fan_speed", "ID_fan_speed_pct",
                 ratio_key="ID_fan_ratio"),
    SetpointSpec("raw_meal_moisture_pct", "raw_meal_moisture", "kiln", "raw_meal_moisture",
                 "raw_meal_moisture_pct", delta_key="raw_meal_moisture_delta_pct_abs"),
    SetpointSpec("raw_meal_temperature_C", "raw_meal_temperature", "kiln",
                 "raw_meal_temperature", "raw_meal_temperature_C",
                 delta_key="raw_meal_temperature_delta_K"),
)

MILL_SETPOINTS: Final[tuple[SetpointSpec, ...]] = (
    SetpointSpec("mill_feed_rate_tph", "mill_feed_rate_tph", "mill", "mill_feed_rate_tph",
                 "feed_rate_tph", ratio_key="mill_feed_ratio"),
    SetpointSpec("separator_speed_rpm", "separator_speed_rpm", "mill", "separator_speed_rpm",
                 "separator_speed_rpm", ratio_key="separator_speed_ratio"),
    SetpointSpec("fan_speed_pct", "fan_speed", "mill", "fan_speed", "fan_speed_pct",
                 ratio_key="fan_speed_ratio"),
    SetpointSpec("mill_speed_rpm", "mill_speed", "mill", "mill_speed", "mill_speed_rpm",
                 ratio_key="mill_speed_ratio"),
)

SETPOINTS: Final[tuple[SetpointSpec, ...]] = KILN_SETPOINTS + MILL_SETPOINTS
_BY_TAG: Final[dict[str, SetpointSpec]] = {spec.tag: spec for spec in SETPOINTS}
_BY_VARIABLE: Final[dict[str, SetpointSpec]] = {spec.variable: spec for spec in SETPOINTS}

#: Config keys a regime's ``setpoints:`` block may use (anything else is a typo, PRD 11.4).
_RATIO_KEYS: Final[frozenset[str]] = frozenset(
    spec.ratio_key for spec in SETPOINTS if spec.ratio_key
)
_DELTA_KEYS: Final[frozenset[str]] = frozenset(
    spec.delta_key for spec in SETPOINTS if spec.delta_key
)

#: Fuel streams whose *mass* rate carries the fuel-quality (LHV) swing of PRD 11.3.
_FUEL_VARIABLES: Final[tuple[str, ...]] = ("kiln_fuel_rate_tph", "calciner_fuel_rate_tph")


# =============================================================================
# Episodes
# =============================================================================
@dataclass(frozen=True, slots=True)
class RegimeEpisode:
    """One contiguous stretch of the schedule spent in one regime (PRD 11.4)."""

    index: int
    name: str
    start_step: int
    steps: int
    regime_id: int | None = None
    injected_fault: str | None = None
    affects: tuple[str, ...] = ()
    setpoints: Mapping[str, float] = field(default_factory=dict)
    oscillation: Mapping[str, Any] | None = None
    unmeasured_disturbance: Mapping[str, Any] | None = None
    sensor_layer_only: bool = False
    is_startup: bool = False
    is_warmup: bool = False
    sign: float = 1.0

    @property
    def end_step(self) -> int:
        """Exclusive end of the episode, in simulation steps."""
        return self.start_step + self.steps

    def fault_for(self, dataset: DatasetName) -> str | None:
        """The ``injected_fault`` label of one dataset: set only on an affected unit."""
        return self.injected_fault if dataset in self.affects else None

    def describe(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "regime_id": self.regime_id,
            "injected_fault": self.injected_fault,
            "affects": list(self.affects),
            "start_step": self.start_step,
            "steps": self.steps,
            "is_startup": self.is_startup,
            "is_warmup": self.is_warmup,
            "sensor_layer_only": self.sensor_layer_only,
        }


@dataclass(frozen=True, slots=True)
class DisturbanceEvent:
    """One Poisson-arrival disturbance episode (PRD 11.3)."""

    kind: str
    start_step: int
    steps: int
    magnitude: float

    @property
    def end_step(self) -> int:
        return self.start_step + self.steps

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_step": self.start_step,
            "steps": self.steps,
            "magnitude": float(self.magnitude),
        }


class _RampedSetpoint:
    """A setpoint that needs ``ramp_minutes`` to travel to a new target (PRD 11.3).

    PRD 11.3 specifies a *minimum ramp time* per variable rather than a rate limit, so a move
    of any size takes the same configured time: the DCS interpolates from where the variable
    currently is to the new target. A ramp time of 0 makes the move instantaneous.
    """

    __slots__ = ("_elapsed_min", "_origin", "_ramp_min", "_target", "_value")

    def __init__(self, initial: float, ramp_minutes: float) -> None:
        if float(ramp_minutes) < 0.0:
            raise ConfigError(f"ramp time must be >= 0 min, got {ramp_minutes!r}")
        self._value = float(initial)
        self._origin = float(initial)
        self._target = float(initial)
        self._ramp_min = float(ramp_minutes)
        self._elapsed_min = self._ramp_min

    @property
    def value(self) -> float:
        return self._value

    def step(self, target: float, dt_minutes: float) -> float:
        """Aim at ``target`` and advance the ramp by ``dt_minutes``."""
        target = float(target)
        if target != self._target:
            self._origin = self._value
            self._target = target
            self._elapsed_min = 0.0
        self._elapsed_min += float(dt_minutes)
        if self._ramp_min <= 0.0 or self._elapsed_min >= self._ramp_min:
            self._value = self._target
        else:
            fraction = self._elapsed_min / self._ramp_min
            self._value = self._origin + fraction * (self._target - self._origin)
        return self._value


#: Public alias. The interactive driver of PRD 19.2 needs the *same* ramp object the offline
#: run uses, so that a regime change looks identical in both modes; exporting the name is
#: cheaper than re-implementing PRD 11.3's minimum-ramp-time rule a second time.
RampedSetpoint = _RampedSetpoint


# =============================================================================
# The planned schedule
# =============================================================================
@dataclass(frozen=True, slots=True)
class ScenarioSchedule:
    """Everything the generator needs to drive the twins for one run (PRD 11.2 step 2).

    ``inputs`` is what the twin is driven with; ``commanded`` is what the DCS asked for. They
    differ only where PRD 11.4 calls for an effect the instruments cannot see: the unmeasured
    feed disturbance of regime 8 and the fuel-quality (LHV) swing of PRD 11.3, which is applied
    to the twin as an energy-equivalent mass rate while the fuel tags keep the commanded rate.
    """

    simulation: SimulationConfig
    episodes: tuple[RegimeEpisode, ...]
    events: tuple[DisturbanceEvent, ...]
    inputs: Mapping[DatasetName, pd.DataFrame]
    commanded: Mapping[DatasetName, pd.DataFrame]
    labels: pd.DataFrame
    ground_truth: pd.DataFrame

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.labels.index  # type: ignore[return-value]

    @property
    def export_mask(self) -> np.ndarray:
        """Rows that survive the warm-up window (PRD 11.2 warm-up rows are discarded)."""
        return np.asarray(~self.labels["is_warmup"].to_numpy(dtype=bool))

    def exported(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Drop the warm-up rows of a frame built on this schedule's index."""
        return frame.loc[self.export_mask]

    def dataset_labels(self, dataset: DatasetName) -> pd.DataFrame:
        """The two PRD 12 ground-truth label columns of one dataset."""
        return pd.DataFrame(
            {
                REGIME_LABEL_COLUMN: self.labels[REGIME_LABEL_COLUMN],
                FAULT_LABEL_COLUMN: self.labels[f"injected_fault_{dataset}"],
            },
            index=self.labels.index,
        )

    def regime_minutes(self) -> dict[str, float]:
        """Realized minutes per regime label - the audit of the PRD 11.4 ``share`` targets."""
        minutes = self.labels.loc[self.export_mask, "operating_regime"].value_counts()
        step_minutes = float(self.simulation.dt_seconds) / 60.0
        return {str(name): float(count) * step_minutes for name, count in minutes.items()}

    def describe(self) -> dict[str, Any]:
        """JSON-serializable provenance record for the PRD 11.6 sidecar."""
        return {
            "simulation": self.simulation.describe(),
            "episodes": [episode.describe() for episode in self.episodes],
            "disturbance_events": [event.describe() for event in self.events],
            "regime_minutes": self.regime_minutes(),
        }


# =============================================================================
# The scheduler
# =============================================================================
class ScenarioScheduler:
    """Builds the input trajectories and ground-truth labels of one run (PRD 11.3/11.4)."""

    def __init__(
        self,
        simulation: SimulationConfig | None = None,
        *,
        scenarios: Config | None = None,
        kiln_config: Config | None = None,
        mill_config: Config | None = None,
    ) -> None:
        self._scenarios = scenarios if scenarios is not None else load_config(SCENARIOS)
        self.simulation = (
            simulation if simulation is not None else SimulationConfig.from_config(self._scenarios)
        )
        self.kiln_reference = kiln_reference.solve_reference_point(
            kiln_config if kiln_config is not None else load_config(KILN)
        )
        self.mill_reference = mill_reference.solve_reference_point(
            mill_config if mill_config is not None else load_config(MILL)
        )
        self._ramp_times: Mapping[str, Any] = self._scenarios["ramp_times_min"]
        schedule = self._scenarios["regime_schedule"]
        self._order = str(schedule["order"])
        self._startup_first = bool(schedule["startup_first"])
        self._regimes: tuple[Mapping[str, Any], ...] = tuple(schedule["regimes"])
        self._startup: Mapping[str, Any] = schedule["startup"]
        self._validate()

    # -- validation ---------------------------------------------------------------------
    def _validate(self) -> None:
        """Fail loudly on anything the config could get silently wrong (PRD 11.4, NFR-6)."""
        if self._order != "share_deficit":
            raise ConfigError(
                f"regime_schedule.order={self._order!r} is not implemented; "
                "the only supported rule is 'share_deficit'"
            )
        for spec in SETPOINTS:
            if spec.ramp_key not in self._ramp_times:
                raise ConfigError(
                    f"ramp_times_min has no entry for {spec.ramp_key!r} "
                    f"(needed by the scheduled variable {spec.variable!r}, PRD 11.3)"
                )
        seen_ids: set[int] = set()
        for regime in self._regimes:
            for key in ("id", "name", "share", "dwell_hours"):
                if key not in regime:
                    raise ConfigError(f"regime {regime.get('name', '?')!r} has no {key!r} key")
            regime_id = int(regime["id"])
            if regime_id in seen_ids:
                raise ConfigError(f"duplicate regime id {regime_id}")
            seen_ids.add(regime_id)
            low, high = (float(value) for value in regime["dwell_hours"])
            if not 0.0 < low <= high:
                raise ConfigError(f"regime {regime_id} has an invalid dwell_hours {low, high}")
            unknown = set(regime.get("setpoints", {})) - _RATIO_KEYS - _DELTA_KEYS
            if unknown:
                raise ConfigError(
                    f"regime {regime_id} has unknown setpoint keys {sorted(unknown)}; "
                    f"expected ratios {sorted(_RATIO_KEYS)} or deltas {sorted(_DELTA_KEYS)}"
                )
            for block in ("oscillation", "unmeasured_disturbance"):
                injected = regime.get(block)
                if injected is None:
                    continue
                unknown_vars = set(injected["variables"]) - set(_BY_TAG)
                if unknown_vars:
                    raise ConfigError(
                        f"regime {regime_id} {block}.variables {sorted(unknown_vars)} are not "
                        f"scheduled variables; expected any of {sorted(_BY_TAG)}"
                    )
        if len(self._regimes) != 14:
            raise ConfigError(
                f"PRD 11.4 mandates exactly 14 operating regimes, found {len(self._regimes)}"
            )
        target_id = int(self._startup["target_regime_id"])
        if target_id not in seen_ids:
            raise ConfigError(f"startup.target_regime_id={target_id} is not a defined regime")

    # -- the reference operating point ---------------------------------------------------
    def _regime_by_id(self, regime_id: int) -> Mapping[str, Any]:
        for regime in self._regimes:
            if int(regime["id"]) == regime_id:
                return regime
        raise ConfigError(f"no regime with id {regime_id}")  # unreachable after _validate

    def reference_value(self, spec: SetpointSpec) -> float:
        """The reference value of one scheduled variable: its ratio-1.0 / delta-0.0 point."""
        reference = self.kiln_reference if spec.dataset == "kiln" else self.mill_reference
        return float(getattr(reference, spec.reference_attr))

    def reference_inputs(self, dataset: DatasetName) -> dict[str, float]:
        """The reference input dict of one unit - what the warm-up window is driven with."""
        return {
            spec.variable: self.reference_value(spec)
            for spec in SETPOINTS
            if spec.dataset == dataset
        }

    def _target_for(self, episode: RegimeEpisode, spec: SetpointSpec) -> float:
        """The commanded target of one variable inside one episode (PRD 11.4).

        A variable the regime does not name returns to its reference value (ASSUMPTION), so the
        ``operating_regime`` label alone determines the intended operating point.
        """
        base = self.reference_value(spec)
        setpoints = episode.setpoints
        if spec.ratio_key is not None and spec.ratio_key in setpoints:
            return base * float(setpoints[spec.ratio_key])
        if spec.delta_key is not None and spec.delta_key in setpoints:
            return base + float(setpoints[spec.delta_key])
        return base

    # -- read-only accessors for the interactive driver (PRD 19.2) ------------------------
    # The dashboard's live mode drives *one* regime at a time instead of a whole planned run,
    # but it must drive it with exactly the numbers this scheduler uses. These accessors expose
    # the config as-read; none of them computes a process value.
    @property
    def regimes(self) -> tuple[Mapping[str, Any], ...]:
        """The 14 configured regimes, verbatim from ``configs/scenarios.yaml`` (PRD 11.4)."""
        return self._regimes

    @property
    def startup(self) -> Mapping[str, Any]:
        """The configured startup transition block."""
        return self._startup

    def regime(self, regime_id: int) -> Mapping[str, Any]:
        """One configured regime by its PRD 11.4 id."""
        return self._regime_by_id(int(regime_id))

    def regime_by_name(self, name: str) -> Mapping[str, Any]:
        """One configured regime by its label, as the dashboard's scenario picker shows it."""
        for regime in self._regimes:
            if str(regime["name"]) == str(name):
                return regime
        raise ConfigError(f"no regime named {name!r}")

    def ramp_minutes(self, spec: SetpointSpec) -> float:
        """The configured minimum ramp time of one scheduled variable (PRD 11.3)."""
        return float(self._ramp_times[spec.ramp_key])

    def target_for(self, episode: RegimeEpisode, spec: SetpointSpec) -> float:
        """Public form of the per-episode setpoint target."""
        return self._target_for(episode, spec)

    def startup_factors(self, elapsed_minutes: float) -> dict[str, float]:
        """Public form of the startup ramp multipliers."""
        return self._startup_factors(elapsed_minutes)

    def episode_for(
        self,
        regime_id: int,
        *,
        steps: int,
        start_step: int = 0,
        index: int = 0,
        sign: float = 1.0,
    ) -> RegimeEpisode:
        """Build the :class:`RegimeEpisode` of one regime, as :meth:`plan_episodes` would.

        Used by the interactive driver to hold a single selected regime for ``steps`` steps. The
        episode carries the regime's own ``setpoints``/``oscillation``/``unmeasured_disturbance``
        blocks unchanged, so :meth:`step_variable` treats it exactly like a planned episode.
        """
        regime = self._regime_by_id(int(regime_id))
        return RegimeEpisode(
            index=int(index),
            name=str(regime["name"]),
            start_step=int(start_step),
            steps=max(1, int(steps)),
            regime_id=int(regime["id"]),
            injected_fault=regime.get("injected_fault"),
            affects=tuple(regime.get("affects", ())),
            setpoints=dict(regime.get("setpoints", {})),
            oscillation=regime.get("oscillation"),
            unmeasured_disturbance=regime.get("unmeasured_disturbance"),
            sensor_layer_only=bool(regime.get("sensor_layer_only", False)),
            sign=float(sign),
        )

    def step_variable(
        self,
        spec: SetpointSpec,
        episode: RegimeEpisode,
        ramp: _RampedSetpoint,
        *,
        dt_minutes: float,
        elapsed_minutes: float,
        progress: float,
        startup_factor: float = 1.0,
        oscillation_rng: np.random.Generator | None = None,
        moisture_pct_abs: float = 0.0,
        lhv_pct: float = 0.0,
    ) -> tuple[float, float]:
        """Advance one scheduled variable by one step: ``(driven, commanded)``.

        The single implementation of PRD 11.3/11.4's per-step rule, called once per variable per
        row by :meth:`build` and once per variable per step by the interactive driver of PRD
        19.2. ``driven`` is what the twin is integrated with; ``commanded`` is what the
        instruments see - they differ only for the effects PRD 11.4 calls unmeasured (regime 8's
        feed disturbance and the fuel-quality swing).
        """
        target = self._target_for(episode, spec) * float(startup_factor)
        value = ramp.step(target, dt_minutes)
        commanded_value = value
        osc = episode.oscillation
        if osc is not None and spec.tag in osc["variables"]:
            wave = math.sin(2.0 * math.pi * elapsed_minutes / float(osc["period_min"]))
            jitter = 0.0
            if oscillation_rng is not None:
                jitter = float(
                    oscillation_rng.normal(0.0, float(osc["noise_pct_of_current"]) / 100.0)
                )
            value *= 1.0 + float(osc["amplitude_pct_of_current"]) / 100.0 * wave + jitter
            # A hunting fan is visible in its own speed feedback: measured.
            commanded_value = value
        und = episode.unmeasured_disturbance
        if und is not None and spec.tag in und["variables"]:
            shape = str(und.get("shape", "step"))
            envelope = 1.0 - progress if shape == "step_then_ramp_back" else 1.0
            value *= (
                1.0
                + episode.sign * float(und["magnitude_pct_of_current"]) / 100.0 * envelope
            )
        if spec.variable == "raw_meal_moisture_pct":
            value = max(0.0, value + float(moisture_pct_abs))
            commanded_value = value
        elif spec.variable in _FUEL_VARIABLES:
            # An LHV swing is unmeasured: the twin gets the energy-equivalent mass rate while
            # the fuel tags keep reporting the commanded rate.
            value *= 1.0 + float(lhv_pct) / 100.0
        return value, commanded_value

    # -- the episode plan (PRD 11.4) -----------------------------------------------------
    def plan_episodes(self) -> tuple[RegimeEpisode, ...]:
        """Lay the run out into episodes: warm-up, the startup transition, then the regimes."""
        sim = self.simulation
        steps_per_minute = sim.steps_per_minute
        export_minutes = float(sim.duration_minutes)
        dwell_rng = sim.rng(DWELL_STREAM)
        sign_rng = sim.rng(EPISODE_SIGN_STREAM)

        episodes: list[RegimeEpisode] = []
        if sim.warmup_steps > 0:
            episodes.append(
                RegimeEpisode(
                    index=0,
                    name=WARMUP_LABEL,
                    start_step=0,
                    steps=sim.warmup_steps,
                    is_warmup=True,
                )
            )
        step = sim.warmup_steps
        remaining = sim.export_steps
        realized_minutes: dict[int, float] = {int(r["id"]): 0.0 for r in self._regimes}
        previous_id: int | None = None

        if self._startup_first and remaining > 0:
            target = self._regime_by_id(int(self._startup["target_regime_id"]))
            minutes = max(
                float(self._startup["ramp_minutes"]),
                float(self._startup["share"]) * export_minutes,
            )
            steps = min(remaining, max(1, int(round(minutes * steps_per_minute))))
            episodes.append(
                RegimeEpisode(
                    index=len(episodes),
                    name=str(self._startup["name"]),
                    start_step=step,
                    steps=steps,
                    injected_fault=self._startup.get("injected_fault"),
                    setpoints=dict(target.get("setpoints", {})),
                    is_startup=True,
                )
            )
            step += steps
            remaining -= steps
            previous_id = int(target["id"])

        while remaining > 0:
            regime = self._pick_regime(realized_minutes, previous_id, export_minutes)
            low, high = (float(value) for value in regime["dwell_hours"])
            minutes = float(dwell_rng.uniform(low, high)) * 60.0
            steps = min(remaining, max(1, int(round(minutes * steps_per_minute))))
            unmeasured = regime.get("unmeasured_disturbance")
            sign = 1.0
            if unmeasured is not None and bool(unmeasured.get("signed", False)):
                sign = 1.0 if sign_rng.random() < 0.5 else -1.0
            regime_id = int(regime["id"])
            episodes.append(
                RegimeEpisode(
                    index=len(episodes),
                    name=str(regime["name"]),
                    start_step=step,
                    steps=steps,
                    regime_id=regime_id,
                    injected_fault=regime.get("injected_fault"),
                    affects=tuple(str(unit) for unit in regime.get("affects", ())),
                    setpoints=dict(regime.get("setpoints", {})),
                    oscillation=regime.get("oscillation"),
                    unmeasured_disturbance=unmeasured,
                    sensor_layer_only=bool(regime.get("sensor_layer_only", False)),
                    sign=sign,
                )
            )
            realized_minutes[regime_id] += steps / steps_per_minute
            previous_id = regime_id
            step += steps
            remaining -= steps
        return tuple(episodes)

    def _pick_regime(
        self,
        realized_minutes: Mapping[int, float],
        previous_id: int | None,
        export_minutes: float,
    ) -> Mapping[str, Any]:
        """The regime with the largest remaining share deficit, never twice in a row.

        Ties break on the regime id, so the plan is a pure function of ``(config, seed)`` and
        does not depend on dict iteration order (NFR-4).
        """
        ranked = sorted(
            self._regimes,
            key=lambda regime: (
                -(float(regime["share"]) * export_minutes - realized_minutes[int(regime["id"])]),
                int(regime["id"]),
            ),
        )
        for regime in ranked:
            if int(regime["id"]) != previous_id:
                return regime
        return ranked[0]

    # -- disturbance events (PRD 11.3) ---------------------------------------------------
    def _plan_pulses(
        self, name: str, stream: str, total_steps: int, *, magnitude_key: str, signed: bool
    ) -> tuple[np.ndarray, tuple[DisturbanceEvent, ...]]:
        """Poisson-arrival rectangular pulses of one disturbance kind.

        Overlapping events add up and the sum is clipped to the configured band (ASSUMPTION):
        two wet-feed events in a row make the feed wetter, but never wetter than the worst
        single event the config allows.
        """
        cfg = self._scenarios.get_path(f"disturbances.{name}")
        rate_per_day = float(cfg["rate_per_day"])
        if rate_per_day <= 0.0:
            raise ConfigError(
                f"disturbances.{name}.rate_per_day must be > 0, got {rate_per_day!r}"
            )
        low_min, high_min = (float(value) for value in cfg["duration_min"])
        low_mag, high_mag = (float(value) for value in cfg[magnitude_key])
        rng = self.simulation.rng(stream)
        steps_per_minute = self.simulation.steps_per_minute
        steps_per_day = steps_per_minute * MINUTES_PER_DAY
        horizon_days = total_steps / steps_per_day
        series = np.zeros(total_steps, dtype=float)
        events: list[DisturbanceEvent] = []
        arrival = 0.0
        while True:
            arrival += float(rng.exponential(1.0 / rate_per_day))
            if arrival >= horizon_days:
                break
            start = int(arrival * steps_per_day)
            steps = max(1, int(round(float(rng.uniform(low_min, high_min)) * steps_per_minute)))
            magnitude = float(rng.uniform(low_mag, high_mag))
            if signed:
                magnitude = abs(magnitude) * (1.0 if rng.random() < 0.5 else -1.0)
            events.append(DisturbanceEvent(name, start, steps, magnitude))
            series[start : min(total_steps, start + steps)] += magnitude
        bound = max(abs(low_mag), abs(high_mag))
        if signed:
            np.clip(series, -bound, bound, out=series)
        else:
            np.clip(series, min(low_mag, high_mag), max(low_mag, high_mag), out=series)
        return series, tuple(events)

    def _ambient_series(self, index: pd.DatetimeIndex) -> np.ndarray:
        """Ambient temperature: a diurnal cycle plus a slow random walk (PRD 11.3).

        ASSUMPTIONs: the diurnal peak sits at 15:00 of the dataset's own clock, and the walk's
        per-step std scales with ``sqrt(dt)`` so the configured per-day std means the same thing
        at any ``dt_seconds``.
        """
        cfg = self._scenarios.get_path("disturbances.ambient_temperature")
        rng = self.simulation.rng(AMBIENT_STREAM)
        hours = np.asarray(
            index.hour + index.minute / 60.0 + index.second / 3600.0, dtype=float
        )
        diurnal = float(cfg["diurnal_amplitude_K"]) * np.sin(2.0 * np.pi * (hours - 9.0) / 24.0)
        dt_days = float(self.simulation.dt_seconds) / (MINUTES_PER_DAY * 60.0)
        step_std = float(cfg["random_walk_std_K_per_day"]) * math.sqrt(dt_days)
        walk = np.cumsum(rng.normal(0.0, step_std, size=len(index)))
        return np.asarray(float(cfg["mean_C"]) + diurnal + walk, dtype=float)

    def _startup_factors(self, elapsed_minutes: float) -> dict[str, float]:
        """Multipliers that walk the kiln line from ``*_start_ratio`` up to nominal (PRD 11.4).

        ASSUMPTION: only the kiln line ramps. The mill starts at its target-regime setpoint,
        which the PRD 8.3 decoupling (a buffered clinker silo between the two) allows.
        """
        ramp_minutes = float(self._startup["ramp_minutes"])
        fraction = 1.0 if ramp_minutes <= 0.0 else min(1.0, elapsed_minutes / ramp_minutes)
        feed = float(self._startup["feed_start_ratio"])
        fuel = float(self._startup["fuel_start_ratio"])
        return {
            "kiln_feed_rate_tph": feed + fraction * (1.0 - feed),
            "kiln_fuel_rate_tph": fuel + fraction * (1.0 - fuel),
            "calciner_fuel_rate_tph": fuel + fraction * (1.0 - fuel),
        }

    def _pad_warmup(
        self, series: np.ndarray, events: Sequence[DisturbanceEvent]
    ) -> tuple[np.ndarray, tuple[DisturbanceEvent, ...]]:
        """Shift a disturbance plan drawn over the exported window into run coordinates.

        Disturbances are drawn over the *exported* horizon only, so the warm-up window really is
        the undisturbed settle its ASSUMPTION claims, and changing ``warmup_minutes`` cannot
        reshuffle the disturbance plan of an otherwise identical run.
        """
        offset = self.simulation.warmup_steps
        if offset == 0:
            return series, tuple(events)
        padded = np.concatenate([np.zeros(offset, dtype=float), series])
        shifted = tuple(
            DisturbanceEvent(event.kind, event.start_step + offset, event.steps, event.magnitude)
            for event in events
        )
        return padded, shifted

    # -- the run plan (PRD 11.2 step 2) --------------------------------------------------
    def build(self) -> ScenarioSchedule:
        """Plan one whole run: input trajectories, commanded trajectories, labels, truth."""
        sim = self.simulation
        total = sim.total_steps
        index = sim.run_timestamps
        dt_minutes = float(sim.dt_seconds) / 60.0
        episodes = self.plan_episodes()

        moisture, moisture_events = self._pad_warmup(
            *self._plan_pulses(
                "feed_moisture_swing",
                MOISTURE_STREAM,
                sim.export_steps,
                magnitude_key="magnitude_pct_abs",
                signed=True,
            )
        )
        lhv, lhv_events = self._pad_warmup(
            *self._plan_pulses(
                "fuel_quality_swing",
                FUEL_QUALITY_STREAM,
                sim.export_steps,
                magnitude_key="lhv_change_pct",
                signed=False,
            )
        )
        ambient = self._ambient_series(index)
        oscillation_rng = sim.rng(OSCILLATION_STREAM)

        ramps = {
            spec.variable: _RampedSetpoint(
                self.reference_value(spec), float(self._ramp_times[spec.ramp_key])
            )
            for spec in SETPOINTS
        }
        driven = {spec.variable: np.zeros(total, dtype=float) for spec in SETPOINTS}
        ordered = {spec.variable: np.zeros(total, dtype=float) for spec in SETPOINTS}
        regime_label: list[str] = [""] * total
        faults: dict[DatasetName, list[str | None]] = {
            "kiln": [None] * total,
            "mill": [None] * total,
        }
        episode_index = np.zeros(total, dtype=int)
        is_warmup = np.zeros(total, dtype=bool)
        is_startup = np.zeros(total, dtype=bool)
        drift_progress = np.zeros(total, dtype=float)

        for episode in episodes:
            for row in range(episode.start_step, min(total, episode.end_step)):
                elapsed_minutes = (row - episode.start_step) * dt_minutes
                progress = (row - episode.start_step + 1) / episode.steps
                startup = self._startup_factors(elapsed_minutes) if episode.is_startup else {}
                for spec in SETPOINTS:
                    if episode.is_startup and row == episode.start_step:
                        # The plant was off, so the startup ramp begins *at* its initial value
                        # instead of gliding down from the (discarded) warm-up operating point.
                        ramps[spec.variable] = _RampedSetpoint(
                            self._target_for(episode, spec) * startup.get(spec.variable, 1.0),
                            self.ramp_minutes(spec),
                        )
                    value, commanded_value = self.step_variable(
                        spec,
                        episode,
                        ramps[spec.variable],
                        dt_minutes=dt_minutes,
                        elapsed_minutes=elapsed_minutes,
                        progress=progress,
                        startup_factor=startup.get(spec.variable, 1.0),
                        oscillation_rng=oscillation_rng,
                        moisture_pct_abs=float(moisture[row]),
                        lhv_pct=float(lhv[row]),
                    )
                    driven[spec.variable][row] = value
                    ordered[spec.variable][row] = commanded_value
                regime_label[row] = episode.name
                faults["kiln"][row] = episode.fault_for("kiln")
                faults["mill"][row] = episode.fault_for("mill")
                episode_index[row] = episode.index
                is_warmup[row] = episode.is_warmup
                is_startup[row] = episode.is_startup
                if episode.sensor_layer_only:
                    drift_progress[row] = progress

        labels = pd.DataFrame(
            {
                REGIME_LABEL_COLUMN: regime_label,
                "injected_fault_kiln": faults["kiln"],
                "injected_fault_mill": faults["mill"],
                "episode_index": episode_index,
                "is_warmup": is_warmup,
                "is_startup": is_startup,
                "sensor_drift_progress": drift_progress,
            },
            index=index,
        )
        ground_truth = pd.DataFrame(
            {
                "ambient_temperature_C": ambient,
                "feed_moisture_swing_pct_abs": moisture,
                "fuel_lhv_swing_pct": lhv,
            },
            index=index,
        )
        inputs = {
            dataset: pd.DataFrame(
                {spec.variable: driven[spec.variable] for spec in SETPOINTS
                 if spec.dataset == dataset},
                index=index,
            )
            for dataset in ("kiln", "mill")
        }
        commanded = {
            dataset: pd.DataFrame(
                {spec.variable: ordered[spec.variable] for spec in SETPOINTS
                 if spec.dataset == dataset},
                index=index,
            )
            for dataset in ("kiln", "mill")
        }
        return ScenarioSchedule(
            simulation=sim,
            episodes=episodes,
            events=moisture_events + lhv_events,
            inputs=inputs,
            commanded=commanded,
            labels=labels,
            ground_truth=ground_truth,
        )


__all__ = [
    "DisturbanceEvent",
    "KILN_SETPOINTS",
    "MILL_SETPOINTS",
    "RampedSetpoint",
    "RegimeEpisode",
    "SETPOINTS",
    "ScenarioSchedule",
    "ScenarioScheduler",
    "SetpointSpec",
    "WARMUP_LABEL",
]
