"""The five baselines of PRD v1.1.1 Section 14.5 - what an optimization result is compared against.

PRD 14.5 names them and this module builds exactly those five, always all five, always over the
same metric set (``configs/optimization.yaml baselines.metrics``):

1. **Current Operating Point** - the measured state now. Observable sensor values, not twin truth.
2. **Historical Baseline** - the trailing ``historical_window_hours`` of the historian, restricted
   to the same operating regime so a 24 h mean is not half startup.
3. **Best Comparable Historical Condition** - the *best* ``best_comparable.window_minutes`` window
   in the recorded history that ran at a comparable production rate in the same regime, ranked on
   ``best_comparable.rank_metric``. PRD 14.5 is explicit that this must be "a legitimate,
   non-artificial comparator, avoiding the 'compare against a deliberately poor baseline' failure
   mode" - so the search deliberately picks the *strongest* comparable window, the one hardest for
   the optimizer to beat, not a representative or a convenient one.
4. **Digital Twin Baseline** - where the PRD 14.6 rule engine would move, settled through the twin.
   A non-AI, fully explainable comparator.
5. **AI-Optimized Operating Point** - the accepted :class:`Recommendation`'s proposed state.

Rows 1-3 are aggregates of *observable* history, rows 4-5 are *twin simulations* of proposed
setpoints; :attr:`BaselineRow.source` records which, because comparing a measured mean with a
simulated steady state is a comparison worth labelling rather than hiding. A row that cannot be
built (no history yet, no comparable window, nothing recommended) is still present, marked
``available = False`` with the reason - PRD 30 wants missing evidence shown, not omitted.

Every reported difference carries :data:`src.labels.SIMULATED_SAVING_CAVEAT`. Nothing in this
module is a validated plant saving.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.config import OPTIMIZATION, Config, load_config
from src.labels import SIMULATED_SAVING_CAVEAT
from src.optimization.prediction import REGIME_LABEL_COLUMN
from src.optimization.recommendation import (
    SOURCE_MEASURED,
    SOURCE_TWIN_SIMULATION,
    MetricDelta,
    Recommendation,
    impact_metrics,
    metric_delta,
)

#: PRD 14.5's five rows, in PRD order. The order is part of the deliverable: a comparison table
#: that starts at "where we are" and ends at "where the AI would go" reads as an argument.
BASELINE_CURRENT = "current_operating_point"
BASELINE_HISTORICAL = "historical_baseline"
BASELINE_BEST_COMPARABLE = "best_comparable_historical"
BASELINE_TWIN_RULES = "digital_twin_baseline"
BASELINE_AI = "ai_optimized_operating_point"

BASELINE_NAMES: tuple[str, ...] = (
    BASELINE_CURRENT,
    BASELINE_HISTORICAL,
    BASELINE_BEST_COMPARABLE,
    BASELINE_TWIN_RULES,
    BASELINE_AI,
)

BASELINE_TITLES: dict[str, str] = {
    BASELINE_CURRENT: "Current Operating Point",
    BASELINE_HISTORICAL: "Historical Baseline",
    BASELINE_BEST_COMPARABLE: "Best Comparable Historical Condition",
    BASELINE_TWIN_RULES: "Digital Twin Baseline (rule engine)",
    BASELINE_AI: "AI-Optimized Operating Point",
}

#: Which of the four kinds of number each row holds - see the module docstring.
BASELINE_SOURCES: dict[str, str] = {
    BASELINE_CURRENT: SOURCE_MEASURED,
    BASELINE_HISTORICAL: SOURCE_MEASURED,
    BASELINE_BEST_COMPARABLE: SOURCE_MEASURED,
    BASELINE_TWIN_RULES: SOURCE_TWIN_SIMULATION,
    BASELINE_AI: SOURCE_TWIN_SIMULATION,
}

#: The production tag the "comparable condition" search matches on.
PRODUCTION_TAG = "clinker_production_tph"


@dataclass(frozen=True, slots=True)
class BaselineRow:
    """One row of the PRD 14.5 comparison, over the shared metric set."""

    name: str
    title: str
    source: str
    metrics: dict[str, float | None]
    available: bool
    detail: str
    rows: int = 0
    setpoints: dict[str, float] = field(default_factory=dict)
    timestamp: Any = None

    def value_of(self, tag: str) -> float | None:
        return self.metrics.get(tag)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "source": self.source,
            "available": self.available,
            "detail": self.detail,
            "historian_rows": self.rows,
            "timestamp": None if self.timestamp is None else str(self.timestamp),
            "setpoints": dict(self.setpoints),
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """All five PRD 14.5 rows plus the deltas that make them an argument."""

    rows: tuple[BaselineRow, ...]
    metrics: tuple[str, ...]
    caveat: str = SIMULATED_SAVING_CAVEAT

    def row(self, name: str) -> BaselineRow:
        for item in self.rows:
            if item.name == name:
                return item
        raise KeyError(f"no baseline {name!r}; expected one of {BASELINE_NAMES}")

    @property
    def available(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.rows if item.available)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.rows if not item.available)

    @property
    def complete(self) -> bool:
        return not self.missing

    def table(self) -> list[dict[str, Any]]:
        """Rectangular table - every row carries every metric key, ``None`` where unavailable."""
        return [
            {
                "baseline": item.title,
                "name": item.name,
                "source": item.source,
                "available": item.available,
                **{tag: item.metrics.get(tag) for tag in self.metrics},
            }
            for item in self.rows
        ]

    def delta(self, name: str, reference: str = BASELINE_CURRENT) -> dict[str, MetricDelta]:
        """Metric-by-metric difference of one row against another (default: the current point)."""
        base = {
            tag: value
            for tag, value in self.row(reference).metrics.items()
            if value is not None
        }
        proposed = {
            tag: value for tag, value in self.row(name).metrics.items() if value is not None
        }
        return {tag: metric_delta(tag, base, proposed) for tag in self.metrics}

    def best_on(self, tag: str, *, lower_is_better: bool = True) -> str | None:
        """Which available row is best on one metric - the honest way to read the table."""
        scored = [
            (item.name, float(item.metrics[tag]))
            for item in self.rows
            if item.available and item.metrics.get(tag) is not None
        ]
        if not scored:
            return None
        pick = min(scored, key=lambda pair: pair[1] if lower_is_better else -pair[1])
        return pick[0]

    def describe(self) -> dict[str, Any]:
        return {
            "metrics": list(self.metrics),
            "available": list(self.available),
            "missing": list(self.missing),
            "complete": self.complete,
            "caveat": self.caveat,
            "rows": [item.describe() for item in self.rows],
            "table": self.table(),
        }


class BaselineSet:
    """Builds the PRD 14.5 comparison. Aggregates only - it owns no twin and no model."""

    __slots__ = ("_best", "_config", "_metrics", "_window_hours")

    def __init__(
        self,
        *,
        metrics: Sequence[str],
        historical_window_hours: float,
        best_comparable: Mapping[str, Any],
        config: Config,
    ) -> None:
        self._metrics = tuple(str(tag) for tag in metrics)
        self._window_hours = float(historical_window_hours)
        self._best = dict(best_comparable)
        self._config = config

    @classmethod
    def from_config(
        cls, *, config: Config | None = None, metrics: Sequence[str] | None = None
    ) -> "BaselineSet":
        optimization = config if config is not None else load_config(OPTIMIZATION)
        block = optimization.get_path("baselines")
        return cls(
            metrics=metrics if metrics is not None else impact_metrics(optimization),
            historical_window_hours=float(block.get_path("historical_window_hours")),
            best_comparable=block.get_path("best_comparable").to_dict(),
            config=optimization,
        )

    # -- access -------------------------------------------------------------------------
    @property
    def metrics(self) -> tuple[str, ...]:
        return self._metrics

    @property
    def historical_window_hours(self) -> float:
        return self._window_hours

    @property
    def rank_metric(self) -> str:
        return str(self._best["rank_metric"])

    # -- building -----------------------------------------------------------------------
    def build(
        self,
        *,
        observed_state: Mapping[str, float],
        observed_setpoints: Mapping[str, float] | None = None,
        timestamp: Any = None,
        history: pd.DataFrame | None = None,
        regime: str | None = None,
        production_target_tph: float | None = None,
        rule_state: Mapping[str, float] | None = None,
        rule_setpoints: Mapping[str, float] | None = None,
        rule_detail: str = "",
        recommendation: Recommendation | None = None,
    ) -> BaselineComparison:
        """Build all five rows. Absent inputs produce unavailable rows, never missing ones."""
        active_regime = regime if regime is not None else _regime_of(history)
        rows = [
            self._point_row(
                BASELINE_CURRENT,
                observed_state,
                setpoints=observed_setpoints,
                timestamp=timestamp,
                detail="Measured operating point at the time of the request.",
            ),
            self._historical_row(history, active_regime, timestamp),
            self._best_comparable_row(history, active_regime, production_target_tph, observed_state),
            self._rule_row(rule_state, rule_setpoints, rule_detail, timestamp),
            self._ai_row(recommendation),
        ]
        return BaselineComparison(rows=tuple(rows), metrics=self._metrics)

    def _point_row(
        self,
        name: str,
        state: Mapping[str, float] | None,
        *,
        setpoints: Mapping[str, float] | None,
        timestamp: Any,
        detail: str,
        unavailable_detail: str = "",
    ) -> BaselineRow:
        if state is None:
            return self._empty_row(name, unavailable_detail or detail)
        return BaselineRow(
            name=name,
            title=BASELINE_TITLES[name],
            source=BASELINE_SOURCES[name],
            metrics=self._extract(state),
            available=True,
            detail=detail,
            rows=1,
            setpoints={} if setpoints is None else {str(k): float(v) for k, v in setpoints.items()},
            timestamp=timestamp,
        )

    def _empty_row(self, name: str, detail: str) -> BaselineRow:
        return BaselineRow(
            name=name,
            title=BASELINE_TITLES[name],
            source=BASELINE_SOURCES[name],
            metrics={tag: None for tag in self._metrics},
            available=False,
            detail=detail,
        )

    def _historical_row(
        self, history: pd.DataFrame | None, regime: str | None, timestamp: Any
    ) -> BaselineRow:
        if history is None or history.empty:
            return self._empty_row(
                BASELINE_HISTORICAL, "No historian rows available for the trailing window."
            )
        window = _trailing_window(history, self._window_hours)
        same_regime = _same_regime(window, regime)
        used = same_regime if not same_regime.empty else window
        note = (
            f"Mean of the trailing {self._window_hours:g} h"
            if same_regime.empty
            else f"Mean of the trailing {self._window_hours:g} h in regime {regime!r}"
        )
        if same_regime.empty and regime is not None:
            note += " (no rows in that regime, so the window is not regime-filtered)"
        return BaselineRow(
            name=BASELINE_HISTORICAL,
            title=BASELINE_TITLES[BASELINE_HISTORICAL],
            source=BASELINE_SOURCES[BASELINE_HISTORICAL],
            metrics=self._mean(used),
            available=True,
            detail=f"{note}; {len(used)} rows.",
            rows=len(used),
            timestamp=timestamp,
        )

    def _best_comparable_row(
        self,
        history: pd.DataFrame | None,
        regime: str | None,
        production_target_tph: float | None,
        observed_state: Mapping[str, float],
    ) -> BaselineRow:
        if history is None or history.empty:
            return self._empty_row(
                BASELINE_BEST_COMPARABLE, "No historian rows to search for a comparable condition."
            )
        target = production_target_tph
        if target is None:
            target = _finite(observed_state.get(PRODUCTION_TAG))
        if target is None:
            return self._empty_row(
                BASELINE_BEST_COMPARABLE,
                f"No production target and no observed {PRODUCTION_TAG} to match against.",
            )
        window_minutes = int(self._best["window_minutes"])
        tolerance = float(self._best["production_match_tolerance_fraction"])
        require_regime = bool(self._best["require_same_regime"])
        rank_metric = self.rank_metric
        for tag in (PRODUCTION_TAG, rank_metric):
            if tag not in history.columns:
                return self._empty_row(
                    BASELINE_BEST_COMPARABLE,
                    f"Historian has no {tag!r} column, so comparable windows cannot be ranked.",
                )

        numeric = [tag for tag in self._metrics if tag in history.columns]
        rolled = history[numeric].rolling(window=window_minutes, min_periods=window_minutes).mean()
        eligible = (rolled[PRODUCTION_TAG] - float(target)).abs() <= abs(float(target)) * tolerance
        if require_regime and regime is not None and REGIME_LABEL_COLUMN in history.columns:
            matches = (history[REGIME_LABEL_COLUMN].astype("string") == regime).astype("float64")
            uniform = matches.rolling(window=window_minutes, min_periods=window_minutes).min()
            eligible = eligible & (uniform >= 1.0)
        eligible = eligible & rolled[rank_metric].notna()
        if not bool(eligible.any()):
            return self._empty_row(
                BASELINE_BEST_COMPARABLE,
                f"No {window_minutes} min window ran within {tolerance * 100:g} % of "
                f"{float(target):.4g} t/h"
                + (f" in regime {regime!r}." if require_regime and regime is not None else "."),
            )
        candidates = rolled.loc[eligible, rank_metric]
        best_index = candidates.idxmin()
        best = rolled.loc[best_index]
        metrics = {tag: _finite(best.get(tag)) for tag in self._metrics}
        return BaselineRow(
            name=BASELINE_BEST_COMPARABLE,
            title=BASELINE_TITLES[BASELINE_BEST_COMPARABLE],
            source=BASELINE_SOURCES[BASELINE_BEST_COMPARABLE],
            metrics=metrics,
            available=True,
            detail=(
                f"Best of {int(eligible.sum())} comparable {window_minutes} min window(s) "
                f"(within {tolerance * 100:g} % of {float(target):.4g} t/h"
                + (f", regime {regime!r}" if require_regime and regime is not None else "")
                + f"), ranked on lowest {rank_metric}; window ending {best_index}."
            ),
            rows=window_minutes,
            timestamp=best_index,
        )

    def _rule_row(
        self,
        rule_state: Mapping[str, float] | None,
        rule_setpoints: Mapping[str, float] | None,
        rule_detail: str,
        timestamp: Any,
    ) -> BaselineRow:
        return self._point_row(
            BASELINE_TWIN_RULES,
            rule_state,
            setpoints=rule_setpoints,
            timestamp=timestamp,
            detail=(
                rule_detail
                or "Twin steady state of the PRD 14.6 rule engine's suggested setpoints."
            ),
            unavailable_detail="The rule engine produced no state to settle.",
        )

    def _ai_row(self, recommendation: Recommendation | None) -> BaselineRow:
        if recommendation is None:
            return self._empty_row(
                BASELINE_AI,
                "No safe recommendation was produced, so there is no AI-optimized point to show.",
            )
        return self._point_row(
            BASELINE_AI,
            recommendation.proposed_state,
            setpoints=recommendation.proposed_setpoints,
            timestamp=recommendation.timestamp,
            detail=(
                f"Twin steady state of the recommended setpoints "
                f"({recommendation.constraint_status} / {recommendation.envelope_status}, "
                f"{recommendation.mode} mode, quality {recommendation.recommendation_quality})."
            ),
        )

    # -- helpers ------------------------------------------------------------------------
    def _extract(self, state: Mapping[str, float]) -> dict[str, float | None]:
        return {tag: _finite(state.get(tag)) for tag in self._metrics}

    def _mean(self, frame: pd.DataFrame) -> dict[str, float | None]:
        payload: dict[str, float | None] = {}
        for tag in self._metrics:
            if tag not in frame.columns:
                payload[tag] = None
                continue
            payload[tag] = _finite(frame[tag].mean())
        return payload

    def describe(self) -> dict[str, Any]:
        return {
            "baselines": list(BASELINE_NAMES),
            "titles": dict(BASELINE_TITLES),
            "sources": dict(BASELINE_SOURCES),
            "metrics": list(self._metrics),
            "historical_window_hours": self._window_hours,
            "best_comparable": dict(self._best),
            "detail": (
                "PRD 14.5 five-way comparison on one metric set. The comparable-condition row is "
                "the strongest matching historical window, not a representative one."
            ),
        }


def _trailing_window(history: pd.DataFrame, hours: float) -> pd.DataFrame:
    if not isinstance(history.index, pd.DatetimeIndex):
        rows = max(int(hours * 60.0), 1)
        return history.iloc[-rows:]
    cutoff = history.index[-1] - pd.Timedelta(hours=float(hours))
    return history.loc[history.index > cutoff]


def _same_regime(frame: pd.DataFrame, regime: str | None) -> pd.DataFrame:
    if regime is None or REGIME_LABEL_COLUMN not in frame.columns:
        return frame.iloc[0:0]
    return frame.loc[frame[REGIME_LABEL_COLUMN].astype("string") == regime]


def _regime_of(history: pd.DataFrame | None) -> str | None:
    if history is None or history.empty or REGIME_LABEL_COLUMN not in history.columns:
        return None
    value = history[REGIME_LABEL_COLUMN].iloc[-1]
    return None if value is None else str(value)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):  # pragma: no cover - historian columns are numeric
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "BASELINE_AI",
    "BASELINE_BEST_COMPARABLE",
    "BASELINE_CURRENT",
    "BASELINE_HISTORICAL",
    "BASELINE_NAMES",
    "BASELINE_SOURCES",
    "BASELINE_TITLES",
    "BASELINE_TWIN_RULES",
    "PRODUCTION_TAG",
    "BaselineComparison",
    "BaselineRow",
    "BaselineSet",
]
