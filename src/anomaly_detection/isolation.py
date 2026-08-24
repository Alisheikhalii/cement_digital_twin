"""Isolation-Forest anomaly scoring - PRD v1.1.1 Section 13.2 "Method 1", and 14.3's OOD gate.

PRD 13.2 is explicit that this is **one component with two consumers**: the score shown next to the
anomaly banner (Section 15) and the out-of-distribution check the optimizer runs before it trusts a
candidate operating point (Section 14.3). Duplicating the logic would let the two drift apart, so
there is a single :class:`AnomalyScorer` and two clearly named decision thresholds on it:

``flagged``
    ``contamination``-calibrated decision boundary of the fitted forest - the anomaly-detection UI.
``out_of_distribution``
    the ``anomaly.ood_threshold_percentile`` quantile of the *normal-regime* score distribution -
    the optimizer's stricter, configurable gate.

The feature space is the **instantaneous** manipulated + process variable block, not a lagged window.
That is what makes the second consumer possible at all: a candidate setpoint the optimizer invents
has no history, so an OOD test defined over lag columns could not score it. PRD 13.2's "normal-regime
windows" is read as *which rows are used for fitting* (the time windows labelled normal), which is
the sense in which the phrase constrains the training set.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.config import ML, SCENARIOS, Config, load_config

METHOD = "isolation_forest"

#: Ground-truth label column names of the exported datasets (PRD 12.1/12.2).
FAULT_COLUMN = "injected_fault"
REGIME_COLUMN = "operating_regime"


def normal_regime_names(scenarios: Config | None = None) -> tuple[str, ...]:
    """Regimes whose ``injected_fault`` is null - PRD 11.4's normal operating regimes 1-3."""
    config = scenarios if scenarios is not None else load_config(SCENARIOS)
    names = [
        str(regime.get_path("name"))
        for regime in config.get_path("regime_schedule.regimes")
        if regime.get_path("injected_fault", None) is None
    ]
    return tuple(names)


def normal_rows(frame: pd.DataFrame, *, startup_regime: str | None = None) -> pd.Series:
    """Rows this unit was genuinely running normally in (PRD 13.2 "normal-regime windows").

    The per-dataset ``injected_fault`` column is the right selector rather than the plant-level
    regime name: a mill-only disturbance leaves the kiln normal, and PRD 12.1/12.2 already encode
    that distinction. The startup ramp is excluded as well - it is a legitimate transient, but a
    forest taught that it is normal would stop protecting the optimizer against it.
    """
    mask = frame[FAULT_COLUMN].isna() if FAULT_COLUMN in frame.columns else pd.Series(
        True, index=frame.index
    )
    if startup_regime is not None and REGIME_COLUMN in frame.columns:
        mask &= frame[REGIME_COLUMN].astype(object) != startup_regime
    return mask


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Scores and both decisions for a scored frame."""

    score: pd.Series
    """Raw ``score_samples`` of the forest: **higher is more normal** (sklearn's convention)."""

    anomaly_score: pd.Series
    """``-score``, so higher is more anomalous - the orientation the UI shows."""

    flagged: pd.Series
    out_of_distribution: pd.Series
    ood_ratio: pd.Series

    def __len__(self) -> int:
        return int(len(self.score))

    def describe(self) -> dict[str, Any]:
        return {
            "rows": len(self),
            "flagged": int(self.flagged.sum()),
            "out_of_distribution": int(self.out_of_distribution.sum()),
            "score_range": [float(self.score.min()), float(self.score.max())],
            "ood_ratio_median": float(np.nanmedian(self.ood_ratio.to_numpy(dtype=float))),
        }


class AnomalyScorer:
    """The single Isolation Forest of PRD 13.2, serving both its consumers."""

    __slots__ = (
        "_config",
        "_features",
        "_flag_threshold",
        "_forest",
        "_normal_median",
        "_ood_threshold",
        "_train_max",
        "_train_mean",
        "_train_min",
        "_train_rows",
        "_train_sigma",
        "dataset",
        "method",
    )

    def __init__(
        self,
        dataset: str,
        features: Sequence[str],
        *,
        config: Config | None = None,
    ) -> None:
        self.dataset = str(dataset)
        self.method = METHOD
        self._config = config if config is not None else load_config(ML)
        self._features = tuple(str(name) for name in features)
        self._forest: Any = None
        self._flag_threshold: float | None = None
        self._ood_threshold: float | None = None
        self._normal_median: float | None = None
        self._train_mean: pd.Series | None = None
        self._train_sigma: pd.Series | None = None
        self._train_min: pd.Series | None = None
        self._train_max: pd.Series | None = None
        self._train_rows = 0

    # -- fitting ------------------------------------------------------------------------
    @property
    def features(self) -> tuple[str, ...]:
        return self._features

    @property
    def fitted(self) -> bool:
        return self._forest is not None

    @property
    def ood_threshold(self) -> float:
        self._require_fitted()
        return float(self._ood_threshold)  # type: ignore[arg-type]

    @property
    def flag_threshold(self) -> float:
        self._require_fitted()
        return float(self._flag_threshold)  # type: ignore[arg-type]

    def fit(self, frame: pd.DataFrame, *, normal: pd.Series | None = None) -> "AnomalyScorer":
        """Fit on the normal rows of ``frame`` only (PRD 13.2) and calibrate both thresholds."""
        from sklearn.ensemble import IsolationForest

        matrix = self._matrix(frame)
        mask = (
            normal.reindex(matrix.index).fillna(False).to_numpy(dtype=bool)
            if normal is not None
            else np.ones(len(matrix), dtype=bool)
        )
        usable = mask & np.isfinite(matrix.to_numpy()).all(axis=1)
        training = matrix.loc[usable]
        if training.empty:
            raise ValueError(
                f"{self.dataset}: no normal-regime rows to fit the Isolation Forest on"
            )

        parameters = dict(self._config.get_path("anomaly.isolation_forest").to_dict())
        parameters["max_samples"] = min(int(parameters.get("max_samples", len(training))), len(training))
        self._forest = IsolationForest(**parameters).fit(training)
        self._train_rows = int(len(training))
        self._train_mean = training.mean()
        self._train_sigma = training.std(ddof=0).replace(0.0, np.nan)
        self._train_min = training.min()
        self._train_max = training.max()

        scores = np.asarray(self._forest.score_samples(training), dtype=float)
        percentile = float(self._config.get_path("anomaly.ood_threshold_percentile"))
        self._ood_threshold = float(np.percentile(scores, percentile))
        self._normal_median = float(np.median(scores))
        # sklearn stores its contamination-calibrated boundary as a negated offset.
        self._flag_threshold = float(self._forest.offset_)
        return self

    # -- scoring ------------------------------------------------------------------------
    def score(self, frame: pd.DataFrame) -> ScoreResult:
        """Score every row: raw score, UI orientation, and both decisions."""
        self._require_fitted()
        matrix = self._matrix(frame)
        complete = np.isfinite(matrix.to_numpy()).all(axis=1)
        raw = pd.Series(np.nan, index=matrix.index, dtype=float)
        if complete.any():
            raw.loc[complete] = self._forest.score_samples(matrix.loc[complete])
        return ScoreResult(
            score=raw,
            anomaly_score=-raw,
            flagged=raw < self.flag_threshold,
            out_of_distribution=raw < self.ood_threshold,
            ood_ratio=self.ood_ratio(raw),
        )

    def ood_ratio(self, score: pd.Series | np.ndarray | float) -> pd.Series:
        """Distance from the training distribution as a 0-1-and-beyond ratio (PRD 13.1.1 factor).

        ``0`` is the median of the normal-regime score distribution, ``1`` is exactly the
        out-of-distribution threshold, and anything above ``1`` is past it. This is the number
        :mod:`src.models.quality` thresholds with ``max_ood_score_ratio``; it is a *relative*
        position inside a known distribution, never presented as a probability.
        """
        self._require_fitted()
        median = float(self._normal_median)  # type: ignore[arg-type]
        span = median - self.ood_threshold
        values = pd.Series(np.asarray(score, dtype=float).ravel())
        if isinstance(score, pd.Series):
            values.index = score.index
        if span <= 0.0:  # pragma: no cover - degenerate distribution
            return pd.Series(np.nan, index=values.index, dtype=float)
        return ((median - values) / span).clip(lower=0.0)

    def contributions(self, row: pd.Series | pd.DataFrame) -> list[dict[str, Any]]:
        """Per-feature distance from the training-normal mean, ranked (PRD 15 attribution).

        ASSUMPTION: an Isolation Forest has no native per-feature attribution, so the ranked
        contribution is the standardized distance of each feature from its training-normal mean.
        It explains *what makes this point unusual relative to the training data* without
        pretending to be an exact decomposition of the forest's own score.
        """
        self._require_fitted()
        series = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        deviation = (
            (series[list(self._features)].astype(float) - self._train_mean) / self._train_sigma
        ).abs()
        ordered = deviation.sort_values(ascending=False, na_position="last")
        return [
            {
                "feature": str(name),
                "training_sigma_from_mean": float(value),
                "value": float(series[name]),
                "training_mean": float(self._train_mean[name]),  # type: ignore[index]
            }
            for name, value in ordered.items()
            if np.isfinite(value)
        ]

    def training_ranges(self) -> dict[str, list[float]]:
        """Min/max of every fitted feature - PRD 14.3 check 1 validates a candidate against these."""
        self._require_fitted()
        return {
            name: [float(self._train_min[name]), float(self._train_max[name])]  # type: ignore[index]
            for name in self._features
        }

    def describe(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method": self.method,
            "dataset": self.dataset,
            "features": list(self._features),
            "feature_count": len(self._features),
            "fitted": self.fitted,
            "detail": (
                "IsolationForest fitted on normal-regime rows only and scored on all rows "
                "(PRD 13.2 Method 1); the same score is the optimizer's out-of-distribution gate "
                "(PRD 14.3)."
            ),
        }
        if self.fitted:
            payload.update(
                {
                    "training_rows": self._train_rows,
                    "hyperparameters": dict(
                        self._config.get_path("anomaly.isolation_forest").to_dict()
                    ),
                    "flag_threshold": self.flag_threshold,
                    "ood_threshold": self.ood_threshold,
                    "ood_threshold_percentile": float(
                        self._config.get_path("anomaly.ood_threshold_percentile")
                    ),
                    "normal_score_median": float(self._normal_median),  # type: ignore[arg-type]
                }
            )
        return payload

    # -- internals ----------------------------------------------------------------------
    def _matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        if isinstance(frame, pd.Series):  # pragma: no cover - convenience
            frame = frame.to_frame().T
        missing = [name for name in self._features if name not in frame.columns]
        if missing:
            raise ValueError(f"{self.dataset}: frame is missing features {missing}")
        return frame[list(self._features)].astype(float)

    def _require_fitted(self) -> None:
        if self._forest is None:
            raise RuntimeError("AnomalyScorer.fit must be called before scoring")


__all__ = [
    "FAULT_COLUMN",
    "METHOD",
    "REGIME_COLUMN",
    "AnomalyScorer",
    "ScoreResult",
    "normal_regime_names",
    "normal_rows",
]
