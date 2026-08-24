"""Per-tag statistical process control - PRD v1.1.1 Section 13.2 "Method 2".

The Isolation Forest answers *whether* the plant looks abnormal; this module answers **which
variable is out of band**, which is the part an operator can act on and the part PRD 15 renders as
"Affected variables". It is deliberately the simple, inspectable layer: a rolling mean, a rolling
sigma, an EWMA and +/-3 sigma control limits, all read from ``configs/ml.yaml``.

Two properties make the output usable as evidence rather than decoration:

* **Every statistic is causal.** The baseline for row ``i`` is built from rows ``[i-window, i-1]``
  via an explicit ``shift(1)``, so a sample is never part of the band it is judged against and no
  future sample is ever consulted (the leakage rule of PRD 13.3 applies to Model B too). The EWMA
  is a weighted average of samples ``<= i`` and so is causal without a shift of its own.
* **A z-score is finite by construction.** ``anomaly.spc.min_sigma_fraction`` floors the rolling
  sigma relative to the tag's own magnitude, so a tag that sat unusually still inside its window
  cannot report an infinite deviation on its first genuine move.

The two charts answer different questions and are both kept: the *individual* chart
``(x_i - mean)/sigma`` decides ``out_of_band`` (a single large excursion), and the *EWMA* chart
``(ewma_i - mean)/(sigma*sqrt(alpha/(2-alpha)))`` accumulates small persistent offsets, which is what
:meth:`SpcResult.monotone_fraction` reads when the sensor-versus-process hypothesis asks whether a
tag has been walking one way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.config import ML, Config, load_config

#: Suffix layout of the frames returned by :meth:`SpcMonitor.evaluate`.
Z_SCORE = "z_score"
OUT_OF_BAND = "out_of_band"
EWMA_DEVIATION = "ewma_deviation"


@dataclass(frozen=True, slots=True)
class SpcLimits:
    """The configured control-chart parameters (PRD 13.2, all ASSUMPTION values)."""

    window_min: int
    sigma_limit: float
    ewma_alpha: float
    min_sigma_fraction: float

    @classmethod
    def from_config(cls, config: Config | None = None) -> "SpcLimits":
        ml = config if config is not None else load_config(ML)
        return cls(
            window_min=int(ml.get_path("anomaly.spc.window_min")),
            sigma_limit=float(ml.get_path("anomaly.spc.sigma_limit")),
            ewma_alpha=float(ml.get_path("anomaly.spc.ewma_alpha")),
            min_sigma_fraction=float(ml.get_path("anomaly.spc.min_sigma_fraction", 0.0)),
        )

    def describe(self) -> dict[str, Any]:
        return {
            "window_min": self.window_min,
            "sigma_limit": self.sigma_limit,
            "ewma_alpha": self.ewma_alpha,
            "min_sigma_fraction": self.min_sigma_fraction,
            "detail": (
                "Rolling mean/sigma over the preceding window (shift(1), so a sample is never in "
                "its own baseline) with +/-sigma_limit control limits on the individual chart, "
                "plus an EWMA control chart (ewma - mean)/(sigma*sqrt(alpha/(2-alpha))) for "
                "persistent offsets (PRD 13.2 Method 2)."
            ),
        }


@dataclass(frozen=True, slots=True)
class SpcResult:
    """Per-tag z-scores, band violations and EWMA deviations, aligned to the input rows."""

    tags: tuple[str, ...]
    limits: SpcLimits
    z_score: pd.DataFrame
    out_of_band: pd.DataFrame
    ewma_deviation: pd.DataFrame
    """EWMA control-chart statistic ``(ewma - baseline_mean)/(sigma*sqrt(alpha/(2-alpha)))``.

    ASSUMPTION (deviation from a first draft, recorded rather than silently swapped): this was
    originally the residual ``(x_i - ewma_{i-1})/sigma``, which is a *fast-mean* residual - it
    duplicates the individual chart and carries no trend, so :meth:`monotone_fraction` measured
    ~0.5 throughout a linear sensor ramp and the "drifts one way" signature could never fire (all 34
    flagged sensor-drift rows of a 3-day run were classified ``process``, tp=0/fn=34). The standard
    EWMA chart against the slower rolling baseline accumulates the offset instead, which is the
    behaviour PRD 13.2's "rolling mean/EWMA" pairing is for. ``out_of_band`` still comes from the
    individual chart, so no control-limit decision changed with it.
    """
    baseline_mean: pd.DataFrame
    baseline_sigma: pd.DataFrame

    def __len__(self) -> int:
        return int(len(self.z_score))

    @property
    def any_out_of_band(self) -> pd.Series:
        """True where at least one tag broke its control limits."""
        return self.out_of_band.any(axis=1)

    @property
    def out_of_band_count(self) -> pd.Series:
        return self.out_of_band.sum(axis=1).astype(int)

    def ranked(self, position: Any, limit: int | None = None) -> list[dict[str, Any]]:
        """The PRD 15 "Affected variables" list for one row: tags ranked by ``|z|``."""
        row = self.z_score.loc[position]
        order = row.abs().sort_values(ascending=False, na_position="last")
        ranked: list[dict[str, Any]] = []
        for tag in order.index[: limit if limit is not None else len(order)]:
            value = row[tag]
            if not np.isfinite(value):
                continue
            ranked.append(
                {
                    "tag": str(tag),
                    "z_score": float(value),
                    "direction": "above" if value > 0 else "below",
                    "out_of_band": bool(self.out_of_band.loc[position, tag]),
                    "baseline_mean": _finite(self.baseline_mean.loc[position, tag]),
                    "baseline_sigma": _finite(self.baseline_sigma.loc[position, tag]),
                }
            )
        return ranked

    def monotone_fraction(self, position: Any, tag: str, window_rows: int) -> float:
        """Fraction of the trailing window the tag spent displaced in its current direction.

        A drifting transmitter sits on one side of its centre line and stays there; a process
        excursion crosses back. This is signature 1 of the sensor-vs-process hypothesis
        (``anomaly.sensor_discrimination.min_monotone_fraction``) and it is the standard SPC run-rule
        reading: how much of the window agrees with the sign of the current EWMA chart value.

        ASSUMPTION (defect fix, recorded rather than silently swapped): this first counted the sign of
        *adjacent* steps of the EWMA statistic. Those steps are ``alpha*(x_i - ewma_{i-1})`` plus the
        baseline's own motion - noise, not trend - so the measured value was ~0.5 throughout a linear
        sensor ramp and the signature could never fire. Sign persistence of the chart *level*
        measures the displacement the name refers to. See :attr:`ewma_deviation`.
        """
        series = self.ewma_deviation[tag]
        end = int(series.index.get_loc(position))
        start = max(0, end - int(window_rows) + 1)
        block = series.to_numpy(dtype=float)[start : end + 1]
        current = block[-1] if block.size else np.nan
        finite = block[np.isfinite(block)]
        if finite.size == 0 or not np.isfinite(current) or current == 0.0:
            return 0.0
        return float(np.count_nonzero(np.sign(finite) == np.sign(current))) / float(finite.size)

    def describe(self) -> dict[str, Any]:
        return {
            "tags": list(self.tags),
            "rows": len(self),
            "limits": self.limits.describe(),
            "rows_with_a_violation": int(self.any_out_of_band.sum()),
            "violations_per_tag": {
                tag: int(self.out_of_band[tag].sum()) for tag in self.tags
            },
        }


class SpcMonitor:
    """Rolling control charts for a fixed tag list (PRD 13.2 Method 2)."""

    __slots__ = ("_limits", "_tags")

    def __init__(self, tags: Sequence[str], *, limits: SpcLimits | None = None,
                 config: Config | None = None) -> None:
        self._tags = tuple(str(tag) for tag in tags)
        self._limits = limits if limits is not None else SpcLimits.from_config(config)

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    @property
    def limits(self) -> SpcLimits:
        return self._limits

    def window_rows(self, sampling_interval_min: float = 1.0) -> int:
        """Baseline window in rows; a value below 2 could not produce a sigma at all."""
        rows = int(round(self._limits.window_min / float(sampling_interval_min)))
        return max(2, rows)

    def evaluate(
        self, frame: pd.DataFrame, *, sampling_interval_min: float = 1.0
    ) -> SpcResult:
        """Score every configured tag of ``frame`` against its own rolling control limits."""
        missing = [tag for tag in self._tags if tag not in frame.columns]
        if missing:
            raise ValueError(f"SPC tags missing from the frame: {missing}")
        values = frame[list(self._tags)].astype(float)
        window = self.window_rows(sampling_interval_min)

        rolling = values.rolling(window=window, min_periods=window)
        mean = rolling.mean().shift(1)
        sigma = rolling.std(ddof=0).shift(1)
        floor = self._limits.min_sigma_fraction * mean.abs()
        guarded = sigma.where(sigma > floor, floor)
        guarded = guarded.where(guarded > 0.0, np.nan)

        z = (values - mean) / guarded
        # Textbook EWMA control chart: the smoothed level against the same shifted baseline mean,
        # scaled by the EWMA's own asymptotic standard error sigma*sqrt(alpha/(2-alpha)). The EWMA
        # itself is deliberately *not* shifted - it is a weighted average of samples <= i, so the
        # statistic stays causal while still carrying the accumulated trend a drift produces.
        alpha = self._limits.ewma_alpha
        smoothed = values.ewm(alpha=alpha, adjust=False).mean()
        deviation = (smoothed - mean) / (guarded * np.sqrt(alpha / (2.0 - alpha)))

        return SpcResult(
            tags=self._tags,
            limits=self._limits,
            z_score=z,
            out_of_band=z.abs() > self._limits.sigma_limit,
            ewma_deviation=deviation,
            baseline_mean=mean,
            baseline_sigma=guarded,
        )

    def describe(self) -> dict[str, Any]:
        return {"tags": list(self._tags), "limits": self._limits.describe()}


def _finite(value: Any) -> float | None:
    number = float(value)
    return None if number != number else number


__all__ = [
    "EWMA_DEVIATION",
    "OUT_OF_BAND",
    "Z_SCORE",
    "SpcLimits",
    "SpcMonitor",
    "SpcResult",
]
