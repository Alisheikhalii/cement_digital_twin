"""Regression and detection metrics (PRD v1.1.1 Section 22).

Two rules the PRD states explicitly and this module enforces rather than leaves to the caller:

* **MAPE only where it means something.** PRD 22 qualifies MAPE with "where target is strictly
  positive and non-near-zero". A target that approaches zero (``CO_ppm`` during a clean burn, or any
  rate during the startup ramp) makes MAPE explode and turns a metric table into a misleading one,
  so MAPE is reported as ``null`` together with the reason it was withheld.
* **Both evaluation references are reported.** PRD 20 item 2 evaluates against the simulator's own
  noise-free state as well as the noisy measurement, which is the only way to separate model error
  from sensor noise. :func:`regression_metrics` is therefore called twice per split and the results
  are tagged ``measured`` / ``truth`` (:data:`REFERENCES`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from src.config import ML, Config, load_config

#: Evaluation reference frames (PRD 20 item 2).
MEASURED = "measured"
TRUTH = "truth"
REFERENCES: tuple[str, ...] = (MEASURED, TRUTH)

#: Metric keys of the PRD 22 regression row, in reporting order.
REGRESSION_METRICS: tuple[str, ...] = ("mae", "rmse", "r2", "mape")

#: Metric keys of the PRD 22 anomaly row.
DETECTION_METRICS: tuple[str, ...] = ("precision", "recall", "f1", "false_positive_rate")


def mean_absolute_error(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(actual, float) - np.asarray(predicted, float))))


def root_mean_squared_error(actual: np.ndarray, predicted: np.ndarray) -> float:
    residual = np.asarray(actual, float) - np.asarray(predicted, float)
    return float(np.sqrt(np.mean(np.square(residual))))


def r2_score(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Coefficient of determination; ``nan`` when the actuals have no variance to explain."""
    truth = np.asarray(actual, float)
    total = float(np.sum(np.square(truth - truth.mean())))
    if total <= 0.0:
        return float("nan")
    residual = float(np.sum(np.square(truth - np.asarray(predicted, float))))
    return float(1.0 - residual / total)


def mape_eligibility(
    actual: np.ndarray, *, near_zero_fraction: float
) -> tuple[bool, str | None]:
    """Is MAPE defensible for these actuals (PRD 22's "strictly positive and non-near-zero")?"""
    truth = np.asarray(actual, float)
    if truth.size == 0:
        return False, "no rows"
    if not np.all(truth > 0.0):
        return False, "target is not strictly positive on this split"
    scale = float(np.median(np.abs(truth)))
    floor = near_zero_fraction * scale
    smallest = float(np.min(np.abs(truth)))
    if scale <= 0.0 or smallest < floor:
        return False, (
            f"target approaches zero on this split (min |actual| {smallest:.6g} < "
            f"{near_zero_fraction:.3g} x median {scale:.6g})"
        )
    return True, None


def mean_absolute_percentage_error(actual: np.ndarray, predicted: np.ndarray) -> float:
    truth = np.asarray(actual, float)
    return float(100.0 * np.mean(np.abs((truth - np.asarray(predicted, float)) / truth)))


def regression_metrics(
    actual: Sequence[float] | np.ndarray,
    predicted: Sequence[float] | np.ndarray,
    *,
    config: Config | None = None,
    near_zero_fraction: float | None = None,
) -> dict[str, Any]:
    """The PRD 22 regression row for one (target, horizon, split, reference) combination."""
    truth = np.asarray(actual, dtype=float)
    estimate = np.asarray(predicted, dtype=float)
    if truth.shape != estimate.shape:
        raise ValueError(f"shape mismatch: actual {truth.shape} vs predicted {estimate.shape}")
    if truth.size == 0:
        return {
            "rows": 0,
            **{key: None for key in REGRESSION_METRICS},
            "mape_omitted_reason": "no rows",
        }
    if near_zero_fraction is None:
        ml = config if config is not None else load_config(ML)
        near_zero_fraction = float(ml.get_path("metrics.mape_near_zero_fraction", 0.05))

    eligible, reason = mape_eligibility(truth, near_zero_fraction=near_zero_fraction)
    return {
        "rows": int(truth.size),
        "mae": mean_absolute_error(truth, estimate),
        "rmse": root_mean_squared_error(truth, estimate),
        "r2": r2_score(truth, estimate),
        "mape": mean_absolute_percentage_error(truth, estimate) if eligible else None,
        "mape_omitted_reason": reason,
        "actual_mean": float(np.mean(truth)),
        "actual_std": float(np.std(truth)),
        "actual_range": [float(np.min(truth)), float(np.max(truth))],
    }


def detection_metrics(
    actual: Sequence[bool] | np.ndarray, flagged: Sequence[bool] | np.ndarray
) -> dict[str, Any]:
    """Precision / Recall / F1 / FPR against ground-truth labels (PRD 22, Model B row).

    The synthetic environment knows the answer (``injected_fault``), which is the whole reason
    PRD 13.2 can promise *real* precision and recall rather than an unlabelled anomaly score with a
    plausible-looking histogram.
    """
    truth = np.asarray(actual, dtype=bool)
    alarm = np.asarray(flagged, dtype=bool)
    if truth.shape != alarm.shape:
        raise ValueError(f"shape mismatch: actual {truth.shape} vs flagged {alarm.shape}")
    true_positive = int(np.count_nonzero(truth & alarm))
    false_positive = int(np.count_nonzero(~truth & alarm))
    false_negative = int(np.count_nonzero(truth & ~alarm))
    true_negative = int(np.count_nonzero(~truth & ~alarm))

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = (
        None
        if precision is None or recall is None or (precision + recall) == 0.0
        else float(2.0 * precision * recall / (precision + recall))
    )
    return {
        "rows": int(truth.size),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": _ratio(false_positive, false_positive + true_negative),
        "confusion": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "positive_rate_actual": _ratio(int(np.count_nonzero(truth)), int(truth.size)),
        "positive_rate_flagged": _ratio(int(np.count_nonzero(alarm)), int(alarm.size)),
    }


def per_class_recall(
    labels: Sequence[str] | np.ndarray, flagged: Sequence[bool] | np.ndarray
) -> dict[str, dict[str, Any]]:
    """Recall broken down per label - which regimes Model B actually catches (PRD 13.2 list)."""
    names = np.asarray(labels, dtype=object)
    alarm = np.asarray(flagged, dtype=bool)
    report: dict[str, dict[str, Any]] = {}
    for label in sorted({str(name) for name in names.tolist() if name is not None}):
        mask = names == label
        rows = int(np.count_nonzero(mask))
        report[label] = {
            "rows": rows,
            "flagged": int(np.count_nonzero(alarm[mask])),
            "recall": _ratio(int(np.count_nonzero(alarm[mask])), rows),
        }
    return report


def worse_of(first: float | None, second: float | None) -> float | None:
    """Larger of two error figures, tolerating ``None`` (used when a metric was withheld)."""
    values = [value for value in (first, second) if value is not None]
    return max(values) if values else None


def summarize_regression(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate a metric table: worst and median MAE, plus how many rows carry each metric."""
    maes = [float(row["mae"]) for row in rows if row.get("mae") is not None]
    r2s = [float(row["r2"]) for row in rows if row.get("r2") is not None and np.isfinite(row["r2"])]
    return {
        "entries": len(rows),
        "mae_median": float(np.median(maes)) if maes else None,
        "mae_worst": float(np.max(maes)) if maes else None,
        "r2_median": float(np.median(r2s)) if r2s else None,
        "r2_worst": float(np.min(r2s)) if r2s else None,
        "mape_reported": sum(1 for row in rows if row.get("mape") is not None),
        "mape_withheld": sum(1 for row in rows if row.get("mape") is None),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else float(numerator) / float(denominator)


__all__ = [
    "DETECTION_METRICS",
    "MEASURED",
    "REFERENCES",
    "REGRESSION_METRICS",
    "TRUTH",
    "detection_metrics",
    "mape_eligibility",
    "mean_absolute_error",
    "mean_absolute_percentage_error",
    "per_class_recall",
    "r2_score",
    "regression_metrics",
    "root_mean_squared_error",
    "summarize_regression",
    "worse_of",
]
