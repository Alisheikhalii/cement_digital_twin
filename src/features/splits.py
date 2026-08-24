"""Chronological and scenario-holdout splits (PRD v1.1.1 Section 13.3).

PRD 13.3 forbids random row splitting outright: adjacent minutes of a heavily autocorrelated
process are near-duplicates, so a random split leaks the answer across the boundary and reports a
metric no real deployment could reproduce. This module offers only the two mandated splits, and
neither of them can be built from shuffled indices - there is no ``shuffle`` argument anywhere.

Both splits *purge* rather than merely cut. A training row at ``t`` carries a label at ``t+h``, so
a naive 70/30 cut still lets the last training rows read the first minutes of the test block. Every
split therefore drops, from the earlier block, any row whose ``[t - max_lag, t + h]`` window reaches
into a later one - the conservative direction, since purging only ever removes training rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.config import ML, Config, load_config
from src.features.lag_features import FeatureMatrix, window_touches

CHRONOLOGICAL = "chronological"
SCENARIO_HOLDOUT = "scenario_holdout"

#: Both split names, in the order PRD 13.3/22 report them.
SPLIT_NAMES: tuple[str, ...] = (CHRONOLOGICAL, SCENARIO_HOLDOUT)


@dataclass(frozen=True, slots=True)
class DataSplit:
    """Positional row indices of one split (never boolean masks - order matters for time series)."""

    name: str
    dataset: str
    horizon_min: int
    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray
    embargo_min: float
    purged: int
    detail: dict[str, Any]

    def __post_init__(self) -> None:
        overlap = (
            set(self.train.tolist()) & set(self.test.tolist())
            or set(self.train.tolist()) & set(self.validation.tolist())
            or set(self.validation.tolist()) & set(self.test.tolist())
        )
        if overlap:
            raise ValueError(f"{self.name} split blocks overlap on {sorted(overlap)[:5]}")

    @property
    def sizes(self) -> dict[str, int]:
        return {
            "train": int(self.train.size),
            "validation": int(self.validation.size),
            "test": int(self.test.size),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "split": self.name,
            "dataset": self.dataset,
            "horizon_min": self.horizon_min,
            "sizes": self.sizes,
            "embargo_min": self.embargo_min,
            "purged_rows": int(self.purged),
            **self.detail,
        }


def embargo_minutes(matrix: FeatureMatrix, config: Config | None = None) -> float:
    """Purge width in minutes: configured value, or ``max(horizon) + max(lag)`` when null.

    The default is the smallest width that makes the two blocks causally independent - a training
    row can neither label into the next block (``horizon``) nor read back into it (``max_lag``).
    """
    ml = config if config is not None else load_config(ML)
    configured = ml.get_path("splits.embargo_minutes", None)
    if configured is not None:
        return float(configured)
    return float(matrix.spec.horizon_min + matrix.spec.max_lag_min)


def chronological_split(
    matrix: FeatureMatrix,
    *,
    config: Config | None = None,
    train_fraction: float | None = None,
    validation_fraction: float | None = None,
) -> DataSplit:
    """PRD 13.3 split 1: first ~70 % train (its tail held out for model selection), last ~30 % test.

    The validation block sits at the *end* of the training span rather than at a random position,
    so selecting a model family on it mimics the only honest situation available in production -
    choosing on the recent past and being judged on the unseen future.
    """
    ml = config if config is not None else load_config(ML)
    train_fraction = float(
        train_fraction
        if train_fraction is not None
        else ml.get_path("splits.chronological_train_fraction")
    )
    validation_fraction = float(
        validation_fraction
        if validation_fraction is not None
        else ml.get_path("splits.chronological_validation_fraction", 0.0)
    )
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(f"chronological_train_fraction must be in (0, 1), got {train_fraction}")
    if not 0.0 <= validation_fraction < train_fraction:
        raise ValueError(
            f"chronological_validation_fraction must be in [0, {train_fraction}), "
            f"got {validation_fraction}"
        )

    positions = matrix.positions
    rows = positions.size
    test_start = int(round(rows * train_fraction))
    validation_start = int(round(rows * (train_fraction - validation_fraction)))
    purge = _purge_steps(matrix, config=ml)

    train_block = np.arange(0, validation_start)
    validation_block = np.arange(validation_start, test_start)
    test_block = np.arange(test_start, rows)

    train_kept = _purge_tail(train_block, positions, boundary=positions[validation_start:], purge=purge)
    validation_kept = _purge_tail(
        validation_block, positions, boundary=positions[test_start:], purge=purge
    )
    purged = (train_block.size - train_kept.size) + (validation_block.size - validation_kept.size)
    return DataSplit(
        name=CHRONOLOGICAL,
        dataset=matrix.dataset,
        horizon_min=matrix.horizon_min,
        train=positions[train_kept],
        validation=positions[validation_kept],
        test=positions[test_block],
        embargo_min=embargo_minutes(matrix, ml),
        purged=int(purged),
        detail={
            "train_fraction": train_fraction,
            "validation_fraction": validation_fraction,
            "boundary_timestamps": {
                "validation_start": _stamp(matrix, validation_start),
                "test_start": _stamp(matrix, test_start),
            },
        },
    )


def scenario_holdout_split(
    matrix: FeatureMatrix,
    *,
    config: Config | None = None,
    regimes: Sequence[str] | None = None,
) -> DataSplit:
    """PRD 13.3 split 2: entire labeled regimes withheld from training and evaluated separately.

    Withheld means withheld: a row is trainable only if *no* minute of its
    ``[t - max_lag, t + h]`` window carries a holdout label, so the model cannot see the regime
    through a lag column or a horizon target either. The test block is every row whose own label is
    a holdout regime - the question being asked is how the model behaves *during* a condition it has
    never been trained on.

    This split gets no validation block on purpose. Model selection happens once, on the
    chronological validation block; selecting on the holdout would leak the very generalization gap
    the split exists to measure (PRD 13.3 "never based on the easier, leakage-prone split alone").
    """
    ml = config if config is not None else load_config(ML)
    holdout = tuple(
        str(name)
        for name in (
            regimes if regimes is not None else ml.get_path("splits.scenario_holdout_regimes")
        )
    )
    positions = matrix.positions
    labels = matrix.regime.to_numpy(dtype=object)
    is_holdout = np.isin(labels, np.array(holdout, dtype=object))
    missing = [name for name in holdout if name not in set(labels.tolist())]

    contaminated = window_touches(
        is_holdout, back=matrix.spec.max_lag_steps, forward=matrix.spec.horizon_steps
    )
    train_mask = ~contaminated
    test_mask = is_holdout
    return DataSplit(
        name=SCENARIO_HOLDOUT,
        dataset=matrix.dataset,
        horizon_min=matrix.horizon_min,
        train=positions[train_mask],
        validation=np.array([], dtype=positions.dtype),
        test=positions[test_mask],
        embargo_min=embargo_minutes(matrix, ml),
        purged=int(np.count_nonzero(contaminated & ~is_holdout)),
        detail={
            "holdout_regimes": list(holdout),
            "holdout_regimes_absent_from_data": missing,
            "test_regime_rows": {
                name: int(np.count_nonzero(labels == name)) for name in holdout
            },
        },
    )


def build_splits(matrix: FeatureMatrix, *, config: Config | None = None) -> dict[str, DataSplit]:
    """Both mandated splits for one (dataset, horizon) pair - always computed, always reported."""
    ml = config if config is not None else load_config(ML)
    return {
        CHRONOLOGICAL: chronological_split(matrix, config=ml),
        SCENARIO_HOLDOUT: scenario_holdout_split(matrix, config=ml),
    }


def subsample_positions(
    positions: np.ndarray, max_rows: int, *, keep_recent: bool = True
) -> np.ndarray:
    """Thin ``positions`` to ``max_rows`` by a uniform stride, preserving chronological order.

    A stride subsample is used instead of random sampling for the same reason the splits are
    chronological: it keeps the retained rows spread over the whole training span rather than
    clustering them, and it is deterministic (NFR-4). ``keep_recent`` anchors the stride at the end
    of the span so the most recent minute is always retained.
    """
    if max_rows <= 0 or positions.size <= max_rows:
        return positions
    stride = int(np.ceil(positions.size / max_rows))
    thinned = positions[::-1][::stride][::-1] if keep_recent else positions[::stride]
    return thinned[-max_rows:] if keep_recent else thinned[:max_rows]


def _purge_steps(matrix: FeatureMatrix, *, config: Config) -> int:
    minutes = embargo_minutes(matrix, config)
    return int(np.ceil(minutes / max(matrix.spec.sampling_interval_min, 1e-9)))


def _purge_tail(
    block: np.ndarray, positions: np.ndarray, *, boundary: np.ndarray, purge: int
) -> np.ndarray:
    """Drop rows of ``block`` whose window reaches within ``purge`` steps of ``boundary``.

    Distance is measured on the *source-frame* row position, not on the position within the feature
    matrix, so rows dropped earlier (dropout, startup exclusion) do not shrink the embargo.
    """
    if block.size == 0 or boundary.size == 0 or purge <= 0:
        return block
    limit = int(boundary[0]) - purge
    return block[positions[block] < limit]


def _stamp(matrix: FeatureMatrix, index: int) -> str | None:
    if index < 0 or index >= len(matrix):
        return None
    return str(matrix.timestamp.iloc[index])


def split_coverage(
    matrix: FeatureMatrix, splits: Mapping[str, DataSplit], target: str | None = None
) -> dict[str, dict[str, Any]]:
    """Which regimes each block actually contains, and how much the target varies inside it.

    This is what makes a metric row readable. R-squared is measured against the *evaluated block's*
    own variance, so a block that happens to cover one steady regime produces a large negative value
    from a moderate MAE - a statement about the scenario schedule, not about the model. Recording the
    regime counts and the target's standard deviation per block lets a reader tell the two apart
    instead of guessing (a 3-day run's chronological tail carries 1-2 regimes; the configured 30-day
    default carries all 14).
    """
    report: dict[str, dict[str, Any]] = {}
    for name, split in splits.items():
        blocks: dict[str, Any] = {}
        for block, positions in (
            ("train", split.train),
            ("validation", split.validation),
            ("test", split.test),
        ):
            if positions.size == 0:
                blocks[block] = {"rows": 0}
                continue
            regimes = matrix.regime.loc[list(positions)].astype(str)
            entry: dict[str, Any] = {
                "rows": int(positions.size),
                "regimes": int(regimes.nunique()),
                "regime_rows": {
                    str(key): int(value) for key, value in regimes.value_counts().items()
                },
            }
            if target is not None:
                values = matrix.y(target, positions).to_numpy(dtype=float)
                entry["target_std"] = float(np.nanstd(values))
                entry["target_mean"] = float(np.nanmean(values))
            blocks[block] = entry
        report[name] = blocks
    return report


def split_table(splits: dict[str, DataSplit]) -> pd.DataFrame:
    """Both splits as one small frame (used by the model card and the notebook)."""
    return pd.DataFrame([split.describe() for split in splits.values()])


__all__ = [
    "CHRONOLOGICAL",
    "DataSplit",
    "SCENARIO_HOLDOUT",
    "SPLIT_NAMES",
    "build_splits",
    "chronological_split",
    "embargo_minutes",
    "scenario_holdout_split",
    "split_coverage",
    "split_table",
    "subsample_positions",
]
