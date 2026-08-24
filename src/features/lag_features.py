"""Lag-feature construction shared by Model A and Model B (PRD v1.1.1 Sections 13.1, 13.3, 23).

One builder serves both models so the leakage argument only has to be made once. Two rules are
structural rather than checked after the fact:

* **A feature can only look backwards.** Every column is either the value at ``t`` or
  ``shift(+k)`` of it; the horizon target is the only ``shift(-h)`` in the module and it never
  re-enters the feature matrix. There is no code path that could put ``t+h`` into ``X``.
* **A target is never a feature of itself.** The horizon columns are built into a separate frame
  (:class:`FeatureMatrix.targets`) and named with a reserved prefix that cannot collide with a
  measurement name, so ``features`` and ``targets`` cannot be confused by a caller.

The *current* value of a target tag is a legitimate feature (a plant operator predicting the
burning-zone temperature 15 minutes out obviously knows it now); what would be leakage is its
future value, and that is what the two rules above exclude. ``tests/test_features_ml.py`` and
``tests/test_ml_leakage.py`` assert both properties directly rather than trusting this docstring.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.config import ML, SCENARIOS, Config, load_config
from src.schema import FAULT_LABEL_COLUMN, REGIME_LABEL_COLUMN, TIMESTAMP_COLUMN

#: Reserved prefix of a horizon target column - unusable as a measurement name (PRD 12 tags are
#: bare identifiers), which is what makes "no target-derived feature" checkable by name alone.
TARGET_PREFIX = "target__"

#: Prefix of the one-hot ``operating_regime`` columns (PRD 13.1).
REGIME_PREFIX = "regime_is__"

_NON_WORD = re.compile(r"[^0-9a-z]+")


def target_column(target: str, horizon_min: int) -> str:
    """Column name of ``target`` at ``t+horizon_min`` (never present in a feature matrix)."""
    return f"{TARGET_PREFIX}{target}__t+{int(horizon_min)}min"


def lag_column(column: str, lag_min: int) -> str:
    """Column name of ``column`` at ``t-lag_min``."""
    return f"{column}__lag{int(lag_min)}min"


def regime_column(regime: str) -> str:
    """One-hot column name of an ``operating_regime`` label."""
    return f"{REGIME_PREFIX}{_NON_WORD.sub('_', regime.strip().lower()).strip('_')}"


def is_target_column(column: str) -> bool:
    """Is this a horizon-target column rather than a feature?"""
    return column.startswith(TARGET_PREFIX)


def regime_categories(config: Config | None = None) -> tuple[str, ...]:
    """Every ``operating_regime`` label the generator can emit, in configured order.

    The one-hot layout is fixed by config rather than by the labels present in the frame at hand:
    a model trained on a scenario-holdout split must still accept a feature vector describing the
    withheld regime, and a 3-day fixture must produce the same columns as a 30-day run.
    """
    scenarios = config if config is not None else load_config(SCENARIOS)
    schedule = scenarios.get_path("regime_schedule")
    names = [str(regime["name"]) for regime in schedule["regimes"]]
    startup = str(schedule.get_path("startup.name"))
    if startup not in names:
        names.append(startup)
    return tuple(names)


def startup_regime_name(config: Config | None = None) -> str:
    """Label of the PRD 11.4 startup ramp (excluded from training windows by default)."""
    scenarios = config if config is not None else load_config(SCENARIOS)
    return str(scenarios.get_path("regime_schedule.startup.name"))


def sensor_layer_faults(config: Config | None = None) -> frozenset[str]:
    """``injected_fault`` values whose regime is flagged ``sensor_layer_only`` (PRD 11.4).

    Model B's sensor-versus-process discriminator is *evaluated* against this set; it is read from
    config so the evaluation cannot silently disagree with the generator about which regime is a
    transmitter fault rather than a process upset.
    """
    scenarios = config if config is not None else load_config(SCENARIOS)
    faults = {
        str(regime["injected_fault"])
        for regime in scenarios.get_path("regime_schedule.regimes")
        if regime.get("sensor_layer_only") and regime.get("injected_fault")
    }
    return frozenset(faults)


def sensor_layer_regime_names(config: Config | None = None) -> tuple[str, ...]:
    """``operating_regime`` labels of the same regimes :func:`sensor_layer_faults` names.

    Two fields of one config entry, needed in two places: ``injected_fault`` is what a row's label
    carries and what the sensor-versus-process rule is scored against, while ``name`` is what the
    per-regime breakdown is keyed by. Reading a per-regime figure for a sensor-layer fault therefore
    needs this projection, and taking both from the same predicate keeps them from disagreeing.
    """
    scenarios = config if config is not None else load_config(SCENARIOS)
    return tuple(
        str(regime["name"])
        for regime in scenarios.get_path("regime_schedule.regimes")
        if regime.get("sensor_layer_only") and regime.get("injected_fault")
    )


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """The exact feature layout of one (dataset, horizon) model (PRD 13.1, 13.4).

    Frozen and hashable so it can be recorded verbatim in ``models/registry.json`` and compared
    against the columns a caller offers at prediction time.
    """

    dataset: str
    horizon_min: int
    base_columns: tuple[str, ...]
    lags_min: tuple[int, ...]
    include_operating_regime: bool
    regime_categories: tuple[str, ...]
    targets: tuple[str, ...]
    sampling_interval_min: float

    @property
    def feature_names(self) -> tuple[str, ...]:
        """Feature columns in their canonical order (current values, then lag blocks, then regime)."""
        names = list(self.base_columns)
        for lag in self.lags_min:
            names.extend(lag_column(column, lag) for column in self.base_columns)
        if self.include_operating_regime:
            names.extend(regime_column(regime) for regime in self.regime_categories)
        return tuple(names)

    @property
    def target_names(self) -> tuple[str, ...]:
        return tuple(target_column(target, self.horizon_min) for target in self.targets)

    @property
    def max_lag_min(self) -> int:
        return int(max(self.lags_min)) if self.lags_min else 0

    @property
    def horizon_steps(self) -> int:
        return self._steps(self.horizon_min)

    @property
    def max_lag_steps(self) -> int:
        return self._steps(self.max_lag_min)

    def lag_steps(self, lag_min: int) -> int:
        return self._steps(lag_min)

    def _steps(self, minutes: float) -> int:
        steps = float(minutes) / float(self.sampling_interval_min)
        if abs(steps - round(steps)) > 1e-9:
            raise ValueError(
                f"{minutes} min is not a whole multiple of the "
                f"{self.sampling_interval_min} min sampling interval (PRD 11.2)"
            )
        return int(round(steps))

    def describe(self) -> dict[str, Any]:
        """Registry/model-card payload (PRD 13.4 "feature list")."""
        return {
            "dataset": self.dataset,
            "horizon_min": self.horizon_min,
            "sampling_interval_min": self.sampling_interval_min,
            "lags_min": list(self.lags_min),
            "base_columns": list(self.base_columns),
            "include_operating_regime": self.include_operating_regime,
            "regime_categories": list(self.regime_categories),
            "feature_count": len(self.feature_names),
            "feature_names": list(self.feature_names),
            "targets": list(self.targets),
        }


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    """Features, horizon targets and row labels of one (dataset, horizon) pair.

    Every frame shares one index: the integer row position of the *source* frame. Keeping the
    original position (rather than reindexing after rows are dropped) is what lets the split
    helpers reason about time distance and episode adjacency on the real timeline.
    """

    spec: FeatureSpec
    features: pd.DataFrame
    targets: pd.DataFrame
    truth_targets: pd.DataFrame | None
    regime: pd.Series
    target_regime: pd.Series
    fault: pd.Series
    timestamp: pd.Series
    dropped_rows: dict[str, int]

    def __len__(self) -> int:
        return int(len(self.features))

    @property
    def dataset(self) -> str:
        return self.spec.dataset

    @property
    def horizon_min(self) -> int:
        return self.spec.horizon_min

    @property
    def positions(self) -> np.ndarray:
        """Source-frame row positions retained, ascending (chronological)."""
        return self.features.index.to_numpy()

    def X(self, positions: Sequence[int] | np.ndarray | None = None) -> pd.DataFrame:
        """Feature frame, optionally restricted to ``positions`` (order preserved)."""
        frame = self.features if positions is None else self.features.loc[list(positions)]
        return frame

    def y(self, target: str, positions: Sequence[int] | np.ndarray | None = None) -> pd.Series:
        """Measured target at ``t+horizon`` - what a real historian would have as a label."""
        series = self.targets[target_column(target, self.horizon_min)]
        return series if positions is None else series.loc[list(positions)]

    def y_truth(self, target: str, positions: Sequence[int] | np.ndarray | None = None) -> pd.Series:
        """Noise-free simulator state at ``t+horizon`` (PRD 20 item 2 evaluation reference)."""
        if self.truth_targets is None:
            raise ValueError("this FeatureMatrix was built without a truth frame")
        series = self.truth_targets[target_column(target, self.horizon_min)]
        return series if positions is None else series.loc[list(positions)]

    def labelled_positions(
        self, target: str, positions: Sequence[int] | np.ndarray | None = None
    ) -> np.ndarray:
        """Positions whose measured label exists (dropout can remove a single sample, PRD 11.5).

        A missing label is dropped rather than filled: forward-filling a *label* would invent an
        observation, which is a different and much worse thing than holding a stale input.
        """
        series = self.y(target, positions)
        return series.index.to_numpy()[series.notna().to_numpy()]

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "horizon_min": self.horizon_min,
            "rows": len(self),
            "feature_count": int(self.features.shape[1]),
            "first_timestamp": None if self.timestamp.empty else str(self.timestamp.iloc[0]),
            "last_timestamp": None if self.timestamp.empty else str(self.timestamp.iloc[-1]),
            "operating_regimes": sorted(self.regime.dropna().unique().tolist()),
            "dropped_rows": dict(self.dropped_rows),
            "has_truth_targets": self.truth_targets is not None,
        }


class FeatureBuilder:
    """Builds the per-horizon feature sets of PRD 13.1 for one dataset (``kiln`` or ``mill``)."""

    __slots__ = ("_config", "_dataset", "_regimes", "_scenarios", "_startup")

    def __init__(
        self,
        dataset: str,
        *,
        config: Config | None = None,
        scenarios: Config | None = None,
    ) -> None:
        if dataset not in ("kiln", "mill"):
            raise ValueError(f"unknown dataset {dataset!r}; expected 'kiln' or 'mill'")
        self._dataset = dataset
        self._config = config if config is not None else load_config(ML)
        self._scenarios = scenarios if scenarios is not None else load_config(SCENARIOS)
        self._regimes = regime_categories(self._scenarios)
        self._startup = startup_regime_name(self._scenarios)

    # -- configuration ------------------------------------------------------------------
    @property
    def dataset(self) -> str:
        return self._dataset

    @property
    def config(self) -> Config:
        return self._config

    @property
    def horizons_min(self) -> tuple[int, ...]:
        return tuple(int(value) for value in self._config.get_path("prediction.horizons_min"))

    @property
    def targets(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self._config.get_path(f"prediction.targets.{self._dataset}"))

    @property
    def base_columns(self) -> tuple[str, ...]:
        """Manipulated + correlated process variables of PRD 13.1, inputs first, de-duplicated."""
        inputs = self._config.get_path(f"features.{self._dataset}_inputs")
        process = self._config.get_path(f"features.{self._dataset}_process")
        seen: dict[str, None] = {}
        for column in (*inputs, *process):
            seen.setdefault(str(column), None)
        return tuple(seen)

    def lags_for(self, horizon_min: int) -> tuple[int, ...]:
        """The horizon-appropriate lag set (PRD 13.1 "sized appropriately per horizon").

        ``features.lag_sizing`` selects the documented rule; ``horizon_scaled`` keeps a lag only if
        it is no longer than the horizon itself (always retaining the shortest one), so the t+5
        model gets a compact recent-history vector while the t+30 model gets the full 15-minute
        window the slower relationships of PRD 9.4/10.3 need.
        """
        configured = sorted(int(value) for value in self._config.get_path("features.lags_min"))
        if not configured:
            return ()
        rule = str(self._config.get_path("features.lag_sizing", "all")).lower()
        if rule == "all":
            return tuple(configured)
        if rule != "horizon_scaled":
            raise ValueError(f"unknown features.lag_sizing {rule!r}; expected 'horizon_scaled'/'all'")
        kept = [lag for lag in configured if lag <= int(horizon_min)]
        return tuple(kept or [configured[0]])

    def spec(self, horizon_min: int, *, sampling_interval_min: float = 1.0) -> FeatureSpec:
        """The feature layout for one horizon (no data needed - the registry records this)."""
        return FeatureSpec(
            dataset=self._dataset,
            horizon_min=int(horizon_min),
            base_columns=self.base_columns,
            lags_min=self.lags_for(horizon_min),
            include_operating_regime=bool(
                self._config.get_path("features.include_operating_regime", True)
            ),
            regime_categories=self._regimes,
            targets=self.targets,
            sampling_interval_min=float(sampling_interval_min),
        )

    # -- construction -------------------------------------------------------------------
    def build(
        self,
        frame: pd.DataFrame,
        horizon_min: int,
        *,
        truth: pd.DataFrame | None = None,
        drop_startup: bool | None = None,
    ) -> FeatureMatrix:
        """Build the feature/target matrices for one horizon from a historian frame.

        ``frame`` is the *measured* dataset of PRD 12 (that is what a real plant would hand over);
        ``truth`` is its noise-free companion, used only to build the second set of evaluation
        labels PRD 20 item 2 asks for. Truth values never enter ``features``.
        """
        ordered = self._validated(frame)
        interval = _sampling_interval_min(ordered[TIMESTAMP_COLUMN])
        spec = self.spec(horizon_min, sampling_interval_min=interval)

        measured = ordered[list(spec.base_columns)].astype("float64")
        held = _causal_forward_fill(measured, self._ffill_limit_steps(interval))

        blocks: list[pd.DataFrame] = [held]
        for lag in spec.lags_min:
            lagged = held.shift(spec.lag_steps(lag))
            lagged.columns = [lag_column(column, lag) for column in held.columns]
            blocks.append(lagged)
        if spec.include_operating_regime:
            blocks.append(self._one_hot_regime(ordered[REGIME_LABEL_COLUMN]))
        features = pd.concat(blocks, axis=1)[list(spec.feature_names)]

        horizon_steps = spec.horizon_steps
        targets = self._horizon_targets(measured, spec, horizon_steps)
        truth_targets = None
        if truth is not None:
            truth_frame = self._validated(truth, require_labels=False)
            _assert_aligned(ordered[TIMESTAMP_COLUMN], truth_frame[TIMESTAMP_COLUMN])
            truth_targets = self._horizon_targets(
                truth_frame[list(spec.targets)].astype("float64"), spec, horizon_steps
            )

        regime = ordered[REGIME_LABEL_COLUMN].astype("string")
        keep, dropped = self._retained_rows(
            features=features,
            targets=targets,
            regime=regime,
            spec=spec,
            drop_startup=self._drop_startup(drop_startup),
        )
        return FeatureMatrix(
            spec=spec,
            features=features.loc[keep],
            targets=targets.loc[keep],
            truth_targets=None if truth_targets is None else truth_targets.loc[keep],
            regime=regime.loc[keep],
            target_regime=regime.shift(-horizon_steps).loc[keep],
            fault=ordered[FAULT_LABEL_COLUMN].astype("string").loc[keep],
            timestamp=ordered[TIMESTAMP_COLUMN].loc[keep],
            dropped_rows=dropped,
        )

    def build_all(
        self,
        frame: pd.DataFrame,
        *,
        truth: pd.DataFrame | None = None,
        drop_startup: bool | None = None,
    ) -> dict[int, FeatureMatrix]:
        """One :class:`FeatureMatrix` per configured horizon (PRD 13.1 mandatory horizons)."""
        return {
            horizon: self.build(frame, horizon, truth=truth, drop_startup=drop_startup)
            for horizon in self.horizons_min
        }

    # -- internals ----------------------------------------------------------------------
    def _drop_startup(self, override: bool | None) -> bool:
        if override is not None:
            return bool(override)
        return bool(self._config.get_path("training.drop_startup_regime", True))

    def _ffill_limit_steps(self, interval_min: float) -> int:
        limit_min = float(self._config.get_path("features.ffill_limit_min", 0.0))
        return int(max(0.0, limit_min) // max(interval_min, 1e-9))

    def _validated(self, frame: pd.DataFrame, *, require_labels: bool = True) -> pd.DataFrame:
        needed = [TIMESTAMP_COLUMN, *self.base_columns, *self.targets]
        if require_labels:
            needed += [REGIME_LABEL_COLUMN, FAULT_LABEL_COLUMN]
        missing = [column for column in dict.fromkeys(needed) if column not in frame.columns]
        if missing:
            raise ValueError(f"{self._dataset} frame is missing required columns: {missing}")
        ordered = frame.reset_index(drop=True)
        stamps = ordered[TIMESTAMP_COLUMN]
        if not stamps.is_monotonic_increasing:
            raise ValueError(f"{self._dataset} frame must be sorted by {TIMESTAMP_COLUMN}")
        if stamps.duplicated().any():
            raise ValueError(f"{self._dataset} frame has duplicate {TIMESTAMP_COLUMN} values")
        return ordered

    def _one_hot_regime(self, labels: pd.Series) -> pd.DataFrame:
        """Fixed-layout one-hot of ``operating_regime`` (PRD 13.1).

        Built from the configured category list rather than from ``get_dummies``, so the column set
        never depends on which regimes happen to occur in the frame being encoded.
        """
        text = labels.astype("string")
        columns = {
            regime_column(regime): (text == regime).to_numpy(dtype="int8")
            for regime in self._regimes
        }
        return pd.DataFrame(columns, index=labels.index)

    @staticmethod
    def _horizon_targets(
        values: pd.DataFrame, spec: FeatureSpec, horizon_steps: int
    ) -> pd.DataFrame:
        """``shift(-h)`` of each target - the only forward shift in the module."""
        shifted = {
            target_column(target, spec.horizon_min): values[target].shift(-horizon_steps)
            for target in spec.targets
        }
        return pd.DataFrame(shifted, index=values.index)

    def _retained_rows(
        self,
        *,
        features: pd.DataFrame,
        targets: pd.DataFrame,
        regime: pd.Series,
        spec: FeatureSpec,
        drop_startup: bool,
    ) -> tuple[pd.Index, dict[str, int]]:
        """Rows with a complete feature vector, at least one label, and no startup contamination."""
        total = len(features)
        complete = features.notna().all(axis=1).to_numpy()
        warm_up = np.zeros(total, dtype=bool)
        warm_up[: spec.max_lag_steps] = True
        labelled = targets.notna().any(axis=1).to_numpy()
        keep = complete & labelled

        startup_window = np.zeros(total, dtype=bool)
        if drop_startup:
            startup_window = window_touches(
                (regime == self._startup).to_numpy(),
                back=spec.max_lag_steps,
                forward=spec.horizon_steps,
            )
            keep &= ~startup_window

        dropped = {
            "total_rows": int(total),
            "incomplete_features": int(np.count_nonzero(~complete)),
            "lag_warm_up": int(np.count_nonzero(warm_up)),
            "no_label_at_horizon": int(np.count_nonzero(~labelled)),
            "startup_window": int(np.count_nonzero(startup_window)),
            "retained": int(np.count_nonzero(keep)),
        }
        return features.index[keep], dropped


def window_touches(flags: np.ndarray, *, back: int, forward: int) -> np.ndarray:
    """``True`` wherever ``flags`` is set anywhere in ``[i - back, i + forward]``.

    Used by every "this row's window is contaminated" rule in the ML layer - startup exclusion
    here, scenario-holdout and embargo purging in :mod:`src.features.splits`. One implementation
    keeps those three rules provably consistent.

    Both call sites pass ``back=max_lag_steps, forward=horizon_steps``, i.e. exactly the span row
    ``i`` touches: it reads back over its lag window and labels forward over its horizon. The pad on
    the *left* is therefore ``back`` (it is what lets ``i - back`` still be addressable), which is
    the orientation ``tests/test_features_ml.py`` pins directly - an inverted pad silently swaps the
    two guards and only shows up when ``horizon != max_lag``.
    """
    marks = np.asarray(flags, dtype=bool)
    if marks.size == 0 or not marks.any():
        return np.zeros(marks.shape, dtype=bool)
    back = max(int(back), 0)
    forward = max(int(forward), 0)
    padded = np.concatenate(
        (np.zeros(back, dtype=np.int64), marks.astype(np.int64), np.zeros(forward, dtype=np.int64))
    )
    cumulative = np.concatenate(([0], np.cumsum(padded)))
    width = back + forward + 1
    counts = cumulative[width:] - cumulative[:-width]
    return counts > 0


def _causal_forward_fill(frame: pd.DataFrame, limit_steps: int) -> pd.DataFrame:
    """Hold the last good value across a dropout gap (PRD 11.5) - past-only, never ``bfill``."""
    if limit_steps <= 0:
        return frame.copy()
    return frame.ffill(limit=limit_steps)


def _sampling_interval_min(stamps: pd.Series) -> float:
    """Uniform sampling interval of the frame, in minutes (PRD 11.2 expects 1 min)."""
    if len(stamps) < 2:
        return 1.0
    deltas = stamps.diff().dropna().unique()
    if len(deltas) != 1:
        raise ValueError(
            "feature building needs a uniformly sampled frame; found "
            f"{len(deltas)} distinct timestamp steps"
        )
    return float(pd.Timedelta(deltas[0]).total_seconds() / 60.0)


def _assert_aligned(left: pd.Series, right: pd.Series) -> None:
    if len(left) != len(right) or not left.reset_index(drop=True).equals(
        right.reset_index(drop=True)
    ):
        raise ValueError("truth frame timestamps do not match the measured frame")


def feature_builders(
    *, config: Config | None = None, scenarios: Config | None = None
) -> dict[str, FeatureBuilder]:
    """One builder per dataset, sharing the loaded configs."""
    ml = config if config is not None else load_config(ML)
    scn = scenarios if scenarios is not None else load_config(SCENARIOS)
    return {name: FeatureBuilder(name, config=ml, scenarios=scn) for name in ("kiln", "mill")}


__all__ = [
    "FeatureBuilder",
    "FeatureMatrix",
    "FeatureSpec",
    "REGIME_PREFIX",
    "TARGET_PREFIX",
    "feature_builders",
    "is_target_column",
    "lag_column",
    "regime_categories",
    "regime_column",
    "sensor_layer_faults",
    "sensor_layer_regime_names",
    "startup_regime_name",
    "target_column",
    "window_touches",
]
