"""``SensorModel`` - the instrument layer between the twin and the dataset (PRD v1.1.1 11.5).

The twins publish the *true* process state. What a plant historian holds is that state seen
through instruments, so every exported numeric column is passed through this layer:

1. **measurement lag** - a first-order transmitter lag, *separate from and additional to* the
   process delays of PRD 9.4/10.3 (the PRD says so explicitly). It is applied first, because a
   transmitter smooths the process value it is fed, not its own noise;
2. **bias drift** - a slow additive ramp, applied only inside the "Sensor drift" regime of
   PRD 11.4, where the true process stays normal and only the instrument moves;
3. **Gaussian noise** - PRD 11.5 sizes it at 1-2 % of nominal, with gas analysers noisier;
4. **quantization** - the resolution the DCS actually stores;
5. **stuck/frozen signal** - the transmitter repeats its last *reported* value, so freezing
   comes after quantization;
6. **dropout** - 0.1-0.5 % of samples are missing (NaN), which is what a historian gap is.

That order is an ASSUMPTION (PRD 11.5 lists the imperfections but not their composition); it is
recorded in ``SIMULATION_ASSUMPTIONS.md`` and pinned by ``tests/test_sensor_model.py``.

Two rules keep the layer honest:

**Noise is sized from the schema, not from a second copy of the ranges.** ``noise_pct_of_range``
is a percentage of the documented band in :mod:`src.schema`, the single source of that band.

**One named RNG substream per (tag, imperfection).** Adding a tag, or reordering the columns,
cannot shift the numbers drawn for any other tag (NFR-4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final, Mapping

import numpy as np
import pandas as pd

from src import schema
from src.config import SCENARIOS, Config, ConfigError, load_config
from src.schema import DatasetName
from src.simulation.simulation_config import MINUTES_PER_DAY, SimulationConfig

#: RNG substream names. The tag is appended, so each tag draws independently (NFR-4).
NOISE_STREAM: Final = "sensor_noise"
DROPOUT_STREAM: Final = "sensor_dropout"
STUCK_STREAM: Final = "sensor_stuck"

#: Config keys an ``overrides:`` entry may use (anything else is a typo, NFR-6).
_OVERRIDE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "noise_absolute",
        "noise_pct_of_value",
        "noise_pct_of_range",
        "lag_seconds",
        "quantization",
        "dropout_probability",
    }
)
_NOISE_KEYS: Final[tuple[str, ...]] = (
    "noise_absolute",
    "noise_pct_of_value",
    "noise_pct_of_range",
)


# =============================================================================
# One instrument
# =============================================================================
@dataclass(frozen=True, slots=True)
class TagSensor:
    """The instrument of one dataset column (PRD 11.5).

    ``noise_absolute`` and ``noise_pct_of_value`` are combined in quadrature, so a gas analyser
    can be given a floor plus a proportional term - which is what PRD 11.5's "noisier at low
    concentration" note describes - without either term being lost.
    """

    tag: str
    dataset: DatasetName
    noise_absolute: float = 0.0
    noise_pct_of_value: float = 0.0
    lag_seconds: float = 0.0
    quantization: float | None = None
    dropout_probability: float = 0.0
    drift_bias: float = 0.0

    def sigma(self, values: np.ndarray) -> np.ndarray:
        """Per-sample noise standard deviation."""
        proportional = self.noise_pct_of_value / 100.0 * np.abs(values)
        return np.sqrt(self.noise_absolute**2 + proportional**2)

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "dataset": self.dataset,
            "noise_absolute": float(self.noise_absolute),
            "noise_pct_of_value": float(self.noise_pct_of_value),
            "lag_seconds": float(self.lag_seconds),
            "quantization": None if self.quantization is None else float(self.quantization),
            "dropout_probability": float(self.dropout_probability),
            "drift_bias": float(self.drift_bias),
        }


# =============================================================================
# What the layer produces
# =============================================================================
@dataclass(frozen=True, slots=True)
class StuckEvent:
    """One frozen-transmitter episode: the tag repeats ``held_value`` (FR-13)."""

    tag: str
    dataset: DatasetName
    start_step: int
    steps: int
    held_value: float

    @property
    def end_step(self) -> int:
        return self.start_step + self.steps

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "dataset": self.dataset,
            "start_step": self.start_step,
            "steps": self.steps,
            "held_value": float(self.held_value),
        }


@dataclass(frozen=True, slots=True)
class SensorOutcome:
    """The measured frame plus the ground truth of what the instruments did to it."""

    frame: pd.DataFrame
    stuck_events: tuple[StuckEvent, ...] = ()
    missing_counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def missing_total(self) -> int:
        return int(sum(self.missing_counts.values()))

    def describe(self) -> dict[str, Any]:
        """JSON-serializable record for the PRD 11.6 sidecar."""
        return {
            "rows": int(len(self.frame)),
            "missing_values": {tag: int(count) for tag, count in self.missing_counts.items()},
            "missing_total": self.missing_total,
            "stuck_events": [event.describe() for event in self.stuck_events],
        }


# =============================================================================
# The sensor model
# =============================================================================
class SensorModel:
    """Turns the twin's true state into what the historian would hold (PRD 11.5)."""

    def __init__(
        self, simulation: SimulationConfig | None = None, *, scenarios: Config | None = None
    ) -> None:
        self._scenarios = scenarios if scenarios is not None else load_config(SCENARIOS)
        self.simulation = (
            simulation if simulation is not None else SimulationConfig.from_config(self._scenarios)
        )
        block = self._scenarios["sensor_model"]
        self._default: Mapping[str, Any] = block["default"]
        self._overrides: Mapping[str, Any] = block["overrides"]
        self._drift: Mapping[str, Any] = block["drift"]
        self._stuck: Mapping[str, Any] = block["stuck"]
        self._validate()
        self.sensors: Mapping[DatasetName, Mapping[str, TagSensor]] = {
            dataset: self._build(dataset) for dataset in ("kiln", "mill")
        }

    # -- validation ---------------------------------------------------------------------
    def _validate(self) -> None:
        """Every configured key must name a real tag and a real setting (NFR-6)."""
        for key in ("noise_pct_of_range", "lag_seconds", "quantization", "dropout_probability"):
            if key not in self._default:
                raise ConfigError(f"sensor_model.default has no {key!r} key (PRD 11.5)")
        dropout = float(self._default["dropout_probability"])
        if not 0.0 <= dropout < 1.0:
            raise ConfigError(
                f"sensor_model.default.dropout_probability must be in [0, 1), got {dropout!r}"
            )
        for tag, override in self._overrides.items():
            if not schema.has_tag(tag):
                raise ConfigError(
                    f"sensor_model.overrides has an entry for {tag!r}, which is not a "
                    "dataset column (src/schema.py is the single source of the columns)"
                )
            unknown = set(override) - _OVERRIDE_KEYS
            if unknown:
                raise ConfigError(
                    f"sensor_model.overrides.{tag} has unknown keys {sorted(unknown)}; "
                    f"expected any of {sorted(_OVERRIDE_KEYS)}"
                )
        shape = str(self._drift["shape"])
        if shape != "linear":
            raise ConfigError(
                f"sensor_model.drift.shape={shape!r} is not implemented; expected 'linear'"
            )
        for tag in self._drift["tags"]:
            if not schema.has_tag(tag):
                raise ConfigError(
                    f"sensor_model.drift.tags has an entry for {tag!r}, which is not a "
                    "dataset column"
                )
        rate = float(self._stuck["rate_per_day_per_tag"])
        if rate < 0.0:
            raise ConfigError(f"sensor_model.stuck.rate_per_day_per_tag must be >= 0, got {rate!r}")
        low, high = (float(value) for value in self._stuck["duration_min"])
        if not 0.0 < low <= high:
            raise ConfigError(f"sensor_model.stuck.duration_min is invalid: {low, high}")

    # -- one instrument per column ------------------------------------------------------
    def _range_sigma(self, tag: str, dataset: DatasetName, pct_of_range: float) -> float:
        """``pct_of_range`` % of the tag's documented span (:mod:`src.schema` owns the span)."""
        span = schema.get_tag(tag, dataset).span
        if span is None:
            raise ConfigError(
                f"sensor_model sizes the noise of {tag!r} as a percentage of its operating "
                "range, but src/schema.py documents no range for it; give the tag a range or "
                "an explicit noise_absolute override"
            )
        return float(pct_of_range) / 100.0 * float(span)

    def _build(self, dataset: DatasetName) -> Mapping[str, TagSensor]:
        """The instrument of every numeric column of ``dataset``.

        Resolution rule (ASSUMPTION, recorded in ``SIMULATION_ASSUMPTIONS.md``): if an override
        supplies *any* noise key, that override defines the noise completely - the default
        ``noise_pct_of_range`` is not added on top, because an override exists precisely to say
        "this instrument is not a generic 1 %-of-range transmitter".
        """
        default_pct = float(self._default["noise_pct_of_range"])
        default_lag = float(self._default["lag_seconds"])
        default_quantization = self._default["quantization"]
        default_dropout = float(self._default["dropout_probability"])
        drift_tags: Mapping[str, Any] = self._drift["tags"]
        sensors: dict[str, TagSensor] = {}
        for tag in schema.numeric_columns(dataset):
            override: Mapping[str, Any] = self._overrides.get(tag, {})
            if any(key in override for key in _NOISE_KEYS):
                absolute = float(override.get("noise_absolute", 0.0))
                proportional = float(override.get("noise_pct_of_value", 0.0))
                pct_of_range = override.get("noise_pct_of_range")
                if pct_of_range is not None:
                    absolute = math.hypot(absolute, self._range_sigma(tag, dataset, pct_of_range))
            else:
                absolute = self._range_sigma(tag, dataset, default_pct)
                proportional = 0.0
            quantization = override.get("quantization", default_quantization)
            sensors[tag] = TagSensor(
                tag=tag,
                dataset=dataset,
                noise_absolute=absolute,
                noise_pct_of_value=proportional,
                lag_seconds=float(override.get("lag_seconds", default_lag)),
                quantization=None if quantization is None else float(quantization),
                dropout_probability=float(
                    override.get("dropout_probability", default_dropout)
                ),
                drift_bias=float(drift_tags.get(tag, 0.0)),
            )
        return sensors

    # -- the imperfection chain ---------------------------------------------------------
    def alpha(self, lag_seconds: float) -> float:
        """Discrete gain of a first-order transmitter lag over one step.

        Deliberately the same expression as :meth:`src.simulation.delays.DelayedResponse.step`
        (``1 - exp(-dt/tau)``), so the instrument layer and the process layer share one lag
        convention; ``tests/test_sensor_model.py`` asserts the two agree sample-for-sample.
        """
        if float(lag_seconds) <= 0.0:
            return 1.0
        return 1.0 - math.exp(-float(self.simulation.dt_seconds) / float(lag_seconds))

    def _freeze(
        self, sensor: TagSensor, values: np.ndarray
    ) -> tuple[np.ndarray, list[StuckEvent]]:
        """Poisson-arrival frozen transmitter: the tag repeats its last reported value (FR-13).

        ASSUMPTION: an arrival that lands inside a still-running freeze is dropped rather than
        extending it, so ``rate_per_day_per_tag`` stays the rate of *distinct* episodes.
        """
        rate = float(self._stuck["rate_per_day_per_tag"])
        rows = int(values.size)
        if rate <= 0.0 or rows == 0:
            return values, []
        low, high = (float(value) for value in self._stuck["duration_min"])
        steps_per_minute = float(self.simulation.steps_per_minute)
        steps_per_day = MINUTES_PER_DAY * steps_per_minute
        horizon_days = rows / steps_per_day
        rng = self.simulation.rng(f"{STUCK_STREAM}:{sensor.tag}")
        frozen = values.copy()
        events: list[StuckEvent] = []
        clock = 0.0
        settled_until = 0
        while True:
            clock += float(rng.exponential(1.0 / rate))
            if clock >= horizon_days:
                break
            start = int(clock * steps_per_day)
            steps = max(1, int(round(float(rng.uniform(low, high)) * steps_per_minute)))
            if start < settled_until:
                continue  # already frozen: this arrival is the same stuck transmitter
            steps = min(steps, rows - start)
            held = float(frozen[start])
            frozen[start : start + steps] = held
            settled_until = start + steps
            events.append(
                StuckEvent(sensor.tag, sensor.dataset, start, steps, held)
            )
        return frozen, events

    def _drift_progress(
        self, drift_progress: Any, index: pd.Index, rows: int
    ) -> np.ndarray:
        """The 0 -> 1 bias ramp of the "Sensor drift" regime, aligned to ``index``.

        The scheduler publishes it as ``labels['sensor_drift_progress']`` (exactly zero outside
        regime 14), so the bias moves only where PRD 11.4 says the instruments drift.
        """
        if drift_progress is None:
            return np.zeros(rows, dtype=float)
        if isinstance(drift_progress, pd.Series):
            aligned = drift_progress.reindex(index)
            if aligned.isna().any():
                raise ConfigError(
                    "drift_progress does not cover every row of the frame being measured"
                )
            return aligned.to_numpy(dtype=float)
        values = np.asarray(drift_progress, dtype=float)
        if values.size != rows:
            raise ConfigError(
                f"drift_progress has {values.size} values but the frame has {rows} rows"
            )
        return values

    # -- the public entry point ---------------------------------------------------------
    def apply(
        self, frame: pd.DataFrame, dataset: DatasetName, *, drift_progress: Any = None
    ) -> SensorOutcome:
        """Measure ``frame`` (the twin's true state) with ``dataset``'s instruments.

        Columns without an instrument - the labels and the PRD 9.3 debug residuals - pass
        through untouched: they are ground truth, not something a transmitter reports.

        ASSUMPTION: the lag starts settled on the first row (as
        :meth:`DelayedResponse.settle` does) and every RNG draw is sized by the frame handed
        in, so measuring the exported window cannot be perturbed by the warm-up length.
        """
        if dataset not in self.sensors:
            raise ConfigError(f"unknown dataset {dataset!r}; expected 'kiln' or 'mill'")
        sensors = self.sensors[dataset]
        tags = [column for column in frame.columns if column in sensors]
        rows = int(len(frame))
        progress = self._drift_progress(drift_progress, frame.index, rows)
        measured = frame.copy()
        if not tags or rows == 0:
            return SensorOutcome(measured, (), {tag: 0 for tag in tags})
        alphas = np.array([self.alpha(sensors[tag].lag_seconds) for tag in tags], dtype=float)
        lagged = first_order_lag(frame[tags].to_numpy(dtype=float), alphas)
        stuck_events: list[StuckEvent] = []
        missing: dict[str, int] = {}
        for position, tag in enumerate(tags):
            sensor = sensors[tag]
            values = lagged[:, position]
            if sensor.drift_bias != 0.0:
                values = values + sensor.drift_bias * progress
            noise = self.simulation.rng(f"{NOISE_STREAM}:{tag}").standard_normal(rows)
            values = values + noise * sensor.sigma(values)
            if sensor.quantization:
                step = float(sensor.quantization)
                values = np.round(values / step) * step
            values, events = self._freeze(sensor, values)
            stuck_events.extend(events)
            dropped = (
                self.simulation.rng(f"{DROPOUT_STREAM}:{tag}").random(rows)
                < sensor.dropout_probability
            )
            missing[tag] = int(dropped.sum())
            measured[tag] = np.where(dropped, np.nan, values)
        return SensorOutcome(measured, tuple(stuck_events), missing)

    # -- provenance ---------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """JSON-serializable record of the instrument layer, for the PRD 11.6 sidecar."""
        return {
            "default": {
                "noise_pct_of_range": float(self._default["noise_pct_of_range"]),
                "lag_seconds": float(self._default["lag_seconds"]),
                "quantization": (
                    None
                    if self._default["quantization"] is None
                    else float(self._default["quantization"])
                ),
                "dropout_probability": float(self._default["dropout_probability"]),
            },
            "drift": {
                "shape": str(self._drift["shape"]),
                "tags": {tag: float(bias) for tag, bias in self._drift["tags"].items()},
            },
            "stuck": {
                "rate_per_day_per_tag": float(self._stuck["rate_per_day_per_tag"]),
                "duration_min": [float(value) for value in self._stuck["duration_min"]],
            },
            "sensors": {
                dataset: {tag: sensor.describe() for tag, sensor in sensors.items()}
                for dataset, sensors in self.sensors.items()
            },
        }


# =============================================================================
# The measurement lag
# =============================================================================
def first_order_lag(values: np.ndarray, alphas: np.ndarray) -> np.ndarray:
    """Apply one first-order lag per column, settled on the first row.

    ``y[0] = x[0]`` and ``y[i] = y[i-1] + alpha * (x[i] - y[i-1])`` - the exact recurrence
    :class:`src.simulation.delays.DelayedResponse` runs, evaluated for every tag at once so a
    six-month dataset (NFR-3) still costs one pass over the rows rather than one per tag.

    A column with ``alpha == 1`` (no configured lag) is returned unchanged.
    """
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"expected a (rows, tags) array, got shape {matrix.shape}")
    gains = np.asarray(alphas, dtype=float)
    if gains.shape != (matrix.shape[1],):
        raise ValueError(
            f"expected one alpha per column ({matrix.shape[1]}), got {gains.shape}"
        )
    if np.any((gains <= 0.0) | (gains > 1.0)):
        raise ValueError("every lag gain must lie in (0, 1]")
    lagged = np.empty_like(matrix)
    state = matrix[0].copy()
    lagged[0] = state
    for row in range(1, matrix.shape[0]):
        state += gains * (matrix[row] - state)
        lagged[row] = state
    return lagged


__all__ = [
    "DROPOUT_STREAM",
    "NOISE_STREAM",
    "STUCK_STREAM",
    "SensorModel",
    "SensorOutcome",
    "StuckEvent",
    "TagSensor",
    "first_order_lag",
]





