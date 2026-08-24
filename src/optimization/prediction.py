"""Model A access for the optimizer - candidate feature rows and multi-horizon predictions.

Two things happen here and the boundary between them is requirement-level, not stylistic.

**Building a feature row for a state the plant has never been in.**
:meth:`FeatureBuilder.build` cannot help: it needs a *label*, so it drops exactly the rows near
"now" that a live prediction needs. The row is therefore assembled here, in the canonical
:attr:`FeatureSpec.feature_names` order, from two sources and no others:

* the **current-value block** - the candidate's twin-simulated settled state, with any base column
  the twin does not produce (ambient/exogenous inputs) held at its last *observed* value;
* the **lag blocks** - values at ``t - lag``, taken from observed history.

No index ever points forward. That is the structural guarantee behind "the optimizer must not use
future observations": the only forward-looking quantity in this module is a model *output*.

ASSUMPTION - a candidate row is built as a **sustained operating point**: its lag blocks repeat
the settled state rather than splicing the old operating point's history onto the new state's
current values. A candidate is by construction the steady state the plant reaches if these
setpoints are held, so "the plant has been running here" is the question being asked, and the
alternative row (settled current values, pre-move lags) is a combination the process can never
actually produce and that no training row resembles. The "predict now" row for the *observed*
state uses real lags and is built by the same function with ``sustained=False``.

**Reading Model A without inventing anything.** :class:`PredictionBundle` returns
:class:`src.models.model_a.Prediction` objects unchanged - value, ``uncertainty``,
``uncertainty_method``, categorical ``quality``. There is no confidence percentage here and none
is derived. ``relative_uncertainty_pct`` is the ensemble spread divided by the prediction, which
is the same quantity ``configs/ml.yaml recommendation_quality.*.max_relative_uncertainty_pct``
already thresholds - so the uncertainty gate reuses a documented number instead of adding one.

When a model a horizon needs is missing, the bundle says so (:attr:`PredictionBundle.missing`)
rather than silently predicting fewer horizons: "required prediction models are unavailable" is
one of the documented reasons a candidate must not be recommended.

**Claim versus report.** :func:`relative_uncertainty_pct` takes an optional ``targets`` filter, and
the optimizer calls it twice: once over :func:`objective_targets` (the quantities a PRD 14.2
recommendation claims an improvement in) and once over everything consulted. The first is what the
uncertainty gate blocks on - an unsupportable claim is not a recommendation. The second is wider by
construction, is always reported, and caps the categorical Recommendation Quality. Both numbers are
Model A's own spread against the one ceiling ``configs/ml.yaml`` already documents; neither is a
confidence figure and no threshold is introduced here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pandas as pd

from src.config import ML, Config, load_config
from src.features.lag_features import (
    FeatureSpec,
    lag_column,
    regime_column,
)
from src.models.model_a import Prediction

#: Column of the measured historian holding the PRD 11.3 regime label - the one categorical
#: feature, read from the *last observed row* (a candidate does not change the regime).
REGIME_LABEL_COLUMN = "operating_regime"

#: PRD 14.4 ``predicted_state_by_horizon`` key format.
HORIZON_KEY_TEMPLATE = "t+{minutes}min"


def horizon_key(horizon_min: int) -> str:
    """``5 -> "t+5min"`` - the PRD 14.4 spelling, in one place."""
    return HORIZON_KEY_TEMPLATE.format(minutes=int(horizon_min))


def feature_row(
    spec: FeatureSpec,
    *,
    history: pd.DataFrame,
    candidate_state: Mapping[str, float] | None = None,
    sustained: bool = False,
) -> pd.DataFrame:
    """One feature row in :attr:`FeatureSpec.feature_names` order (see the module docstring).

    ``history`` is the *measured* historian, oldest row first; only its tail is read. Passing
    ``candidate_state=None`` builds the honest "predict now" row for the observed state.
    """
    if history.empty:
        raise ValueError("cannot build a feature row from an empty history frame")
    if len(history) <= spec.max_lag_steps:
        raise ValueError(
            f"history has {len(history)} rows but the t+{spec.horizon_min} model needs "
            f"{spec.max_lag_steps + 1} to fill its {spec.max_lag_min} min lag block"
        )
    last = history.iloc[-1]
    proposed = {} if candidate_state is None else candidate_state

    current: dict[str, float] = {}
    for column in spec.base_columns:
        if column in proposed:
            current[column] = float(proposed[column])
        elif column in history.columns:
            current[column] = float(last[column])
        else:
            raise KeyError(
                f"base column {column!r} is neither in the candidate state nor in the history "
                "frame - the feature row would be incomplete"
            )

    row: dict[str, float] = dict(current)
    for lag in spec.lags_min:
        steps = spec.lag_steps(lag)
        past = history.iloc[-1 - steps]
        for column in spec.base_columns:
            if sustained:
                value = current[column]
            elif column in history.columns:
                value = float(past[column])
            else:  # pragma: no cover - unreachable: `current` already required one of the two
                raise KeyError(f"no history for base column {column!r}")
            row[lag_column(column, lag)] = float(value)

    if spec.include_operating_regime:
        label = str(last[REGIME_LABEL_COLUMN]) if REGIME_LABEL_COLUMN in history.columns else ""
        for regime in spec.regime_categories:
            row[regime_column(regime)] = 1.0 if regime == label else 0.0

    frame = pd.DataFrame([row], index=[history.index[-1]])
    return frame[list(spec.feature_names)].astype("float64")


def _pin_single_threaded(model: Any) -> None:
    """Force ``n_jobs = 1`` on every estimator the optimizer will consult, for bit-reproducibility.

    ``configs/ml.yaml models.random_forest.n_jobs: -1`` is the right setting for *training* on
    Colab, but scikit-learn's forest ``predict`` accumulates each tree's output into one shared
    array from worker threads, so the summation order - and therefore the last bit or two of the
    mean - depends on thread scheduling. Two identical optimizer runs then differ at ~1e-15
    relative, which is harmless for every number shown but makes "the optimizer is reproducible"
    an approximate claim instead of an exact one, and in principle lets a value sitting exactly on
    a quality threshold land on either side.

    Nothing about the trained model changes: the same trees are averaged, in a fixed order. Only
    the *arithmetic order* is pinned, and only on the copy the optimizer holds. Prediction cost is
    irrelevant here - Model A is consulted once per run, for the winning candidate, not per
    candidate.
    """
    for estimator in getattr(model, "estimators", {}).values():
        _pin_one(estimator)
    bootstrap = getattr(model, "bootstrap", None)
    if bootstrap is not None:
        _pin_one(getattr(bootstrap, "template", None))
        for member in getattr(bootstrap, "_members", ()) or ():
            _pin_one(member)


def _pin_one(estimator: Any) -> None:
    """``n_jobs = 1`` if the estimator has one (GradientBoosting does not)."""
    if estimator is not None and getattr(estimator, "n_jobs", None) not in (None, 1):
        estimator.n_jobs = 1


class PredictionBundle:
    """The Model A horizon models the optimizer is allowed to consult, for one dataset."""

    __slots__ = ("_config", "_dataset", "_models", "_targets")

    def __init__(
        self,
        dataset: str,
        models: Mapping[tuple[str, int], Any],
        *,
        config: Config | None = None,
    ) -> None:
        self._dataset = str(dataset)
        self._models = {(str(target), int(horizon)): model for (target, horizon), model in models.items()}
        self._config = config if config is not None else load_config(ML)
        self._targets = tuple(dict.fromkeys(target for target, _ in self._models))
        for model in self._models.values():
            _pin_single_threaded(model)

    # -- construction -------------------------------------------------------------------
    @classmethod
    def from_result(
        cls,
        result: Any,
        *,
        targets: Sequence[str] | None = None,
        horizons_min: Sequence[int] | None = None,
        config: Config | None = None,
    ) -> "PredictionBundle":
        """Take the horizon models out of a :class:`src.models.model_a.ModelAResult`."""
        wanted_targets = tuple(str(name) for name in (targets if targets is not None else result.targets))
        wanted_horizons = tuple(
            int(value) for value in (horizons_min if horizons_min is not None else result.horizons_min)
        )
        models: dict[tuple[str, int], Any] = {}
        for target in wanted_targets:
            for horizon in wanted_horizons:
                try:
                    models[(target, horizon)] = result.model(target, horizon)
                except KeyError:
                    continue
        return cls(result.dataset, models, config=config)

    # -- access -------------------------------------------------------------------------
    @property
    def dataset(self) -> str:
        return self._dataset

    @property
    def targets(self) -> tuple[str, ...]:
        return self._targets

    @property
    def horizons_min(self) -> tuple[int, ...]:
        return tuple(sorted({horizon for _, horizon in self._models}))

    @property
    def available(self) -> bool:
        return bool(self._models)

    def missing(
        self, *, targets: Sequence[str] | None = None, horizons_min: Sequence[int] | None = None
    ) -> tuple[tuple[str, int], ...]:
        """(target, horizon) pairs that were asked for but have no trained model."""
        wanted_targets = tuple(str(name) for name in (targets if targets is not None else self._targets))
        wanted_horizons = tuple(
            int(value)
            for value in (
                horizons_min
                if horizons_min is not None
                else self._config.get_path("prediction.horizons_min")
            )
        )
        return tuple(
            (target, horizon)
            for target in wanted_targets
            for horizon in wanted_horizons
            if (target, horizon) not in self._models
        )

    def model(self, target: str, horizon_min: int) -> Any:
        try:
            return self._models[(str(target), int(horizon_min))]
        except KeyError:
            raise KeyError(
                f"no Model A for {self._dataset}/{target} at t+{horizon_min}min; available: "
                f"{sorted(self._models)}"
            ) from None

    @property
    def training_domains(self) -> tuple[dict[str, Any], ...]:
        """``training_domain`` of every consulted model - PRD 14.3 check 1's range source."""
        return tuple(model.training_domain for model in self._models.values())

    # -- prediction ---------------------------------------------------------------------
    def predict(
        self,
        *,
        history: pd.DataFrame,
        candidate_state: Mapping[str, float] | None = None,
        sustained: bool | None = None,
        constraint_margin: float | None = None,
        ood_score_ratio: float | None = None,
        targets: Sequence[str] | None = None,
        horizons_min: Sequence[int] | None = None,
    ) -> tuple[Prediction, ...]:
        """Predict every requested (target, horizon) for one state.

        ``sustained`` defaults to "yes for a candidate, no for the observed state" - the two
        constructions of the module docstring, so a caller cannot accidentally splice pre-move
        history onto a settled candidate.
        """
        as_sustained = (candidate_state is not None) if sustained is None else bool(sustained)
        wanted_targets = tuple(str(name) for name in (targets if targets is not None else self._targets))
        wanted_horizons = tuple(
            int(value) for value in (horizons_min if horizons_min is not None else self.horizons_min)
        )
        predictions: list[Prediction] = []
        for target in wanted_targets:
            for horizon in wanted_horizons:
                model = self._models.get((target, horizon))
                if model is None:
                    continue
                row = feature_row(
                    model.spec,
                    history=history,
                    candidate_state=candidate_state,
                    sustained=as_sustained,
                )
                predictions.extend(
                    model.predictions(
                        row,
                        constraint_margin=constraint_margin,
                        ood_score_ratio=ood_score_ratio,
                    )
                )
        return tuple(predictions)

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self._dataset,
            "targets": list(self._targets),
            "horizons_min": list(self.horizons_min),
            "models": len(self._models),
            "model_versions": sorted({model.model_version for model in self._models.values()}),
        }


# --- reading a prediction set ---------------------------------------------------------------
def by_horizon(predictions: Iterable[Prediction]) -> dict[str, dict[str, Any]]:
    """PRD 14.4 ``predicted_state_by_horizon``: ``{"t+5min": {target: {...}}}``.

    Every entry keeps the uncertainty, its method and the categorical quality beside the value -
    a bare number would drop exactly the information FR-23 requires to be shown with it.
    """
    payload: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        slot = payload.setdefault(horizon_key(prediction.horizon_min), {})
        slot[prediction.target] = {
            "value": prediction.value,
            "unit": prediction.unit,
            "uncertainty": prediction.uncertainty,
            "uncertainty_method": prediction.uncertainty_method,
            "model_family": prediction.model_family,
            "model_version": prediction.model_version,
            "quality": prediction.quality,
        }
    return {key: payload[key] for key in sorted(payload, key=_horizon_of)}


def _horizon_of(key: str) -> int:
    return int(key.removeprefix("t+").removesuffix("min"))


def relative_uncertainty_pct(
    predictions: Iterable[Prediction], *, targets: Sequence[str] | None = None
) -> float | None:
    """Worst ensemble spread as a percent of its own prediction, or ``None`` if unmeasurable.

    "Worst" rather than "mean": the uncertainty gate asks whether *any* consulted model is too
    unsure to support a recommendation, so averaging a wide horizon away would defeat it.

    ``targets`` restricts the set to named targets. The optimizer uses that to separate the
    *claim* (the targets its objective is scored on) from the *report* (everything it shows);
    see :func:`objective_targets` and the gate that consumes it.
    """
    wanted = None if targets is None else {str(name) for name in targets}
    worst: float | None = None
    for prediction in predictions:
        if wanted is not None and prediction.target not in wanted:
            continue
        value = float(prediction.value)
        spread = prediction.uncertainty
        if spread is None or not math.isfinite(float(spread)) or value == 0.0:
            continue
        pct = 100.0 * abs(float(spread)) / abs(value)
        worst = pct if worst is None else max(worst, pct)
    return worst


def wide_predictions(
    predictions: Iterable[Prediction], limit_pct: float
) -> tuple[tuple[str, int, float], ...]:
    """``(target, horizon_min, relative_spread_pct)`` for every prediction above ``limit_pct``.

    Named rather than counted: a gate that reports "3 predictions were too wide" hides which
    quantity the platform cannot predict, and that is the part worth documenting.
    """
    wide: list[tuple[str, int, float]] = []
    for prediction in predictions:
        value = float(prediction.value)
        spread = prediction.uncertainty
        if spread is None or not math.isfinite(float(spread)) or value == 0.0:
            continue
        pct = 100.0 * abs(float(spread)) / abs(value)
        if pct > float(limit_pct):
            wide.append((prediction.target, int(prediction.horizon_min), pct))
    return tuple(sorted(wide, key=lambda item: (-item[2], item[0], item[1])))


def objective_targets(config: Config | None = None) -> tuple[str, ...]:
    """``configs/ml.yaml uncertainty.optimizer_targets`` - the targets the objective is scored on.

    The same list that decides which targets get an eagerly-trained bootstrap ensemble
    (``uncertainty.pretrain_for_optimizer_targets_only``), reused rather than restated: these are
    exactly the quantities a PRD 14.2 recommendation claims an improvement in.
    """
    ml = config if config is not None else load_config(ML)
    return tuple(str(name) for name in ml.get_path("uncertainty.optimizer_targets"))



def cross_horizon_spread_pct(predictions: Iterable[Prediction]) -> float | None:
    """Mean per-target spread across horizons, as a percent of the target's own mean.

    This is the "predicted variability" half of PRD 14.2's Stability_Penalty: a candidate whose
    t+5 and t+30 predictions disagree is one the models expect to still be moving.
    """
    grouped: dict[str, list[float]] = {}
    for prediction in predictions:
        grouped.setdefault(prediction.target, []).append(float(prediction.value))
    spreads: list[float] = []
    for values in grouped.values():
        if len(values) < 2:
            continue
        centre = sum(values) / len(values)
        if centre == 0.0:  # pragma: no cover - no PRD 12 target is zero-valued
            continue
        spreads.append(100.0 * (max(values) - min(values)) / abs(centre))
    return sum(spreads) / len(spreads) if spreads else None


def worst_quality(predictions: Iterable[Prediction]) -> str | None:
    """Worst categorical quality over a prediction set (HIGH > MEDIUM > LOW), never a number."""
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    labels = [prediction.quality for prediction in predictions if prediction.quality]
    return max(labels, key=lambda label: order.get(str(label), 3)) if labels else None


def worst_disagreement_pct(predictions: Iterable[Prediction]) -> float | None:
    """Worst family-vs-family disagreement over a prediction set, or ``None`` if unmeasurable.

    Model A carries a second family's value in ``alternative_value``, and
    ``configs/ml.yaml recommendation_quality.*.max_model_disagreement_pct`` already thresholds
    exactly this quantity - so it is read here rather than redefined.
    """
    from src.models.uncertainty import disagreement_pct

    worst: float | None = None
    for prediction in predictions:
        alternative = prediction.alternative_value
        if alternative is None:
            continue
        value = float(prediction.value)
        if value == 0.0:  # pragma: no cover - no PRD 12 target is zero-valued
            continue
        pct = abs(float(disagreement_pct(value, float(alternative))))
        worst = pct if worst is None else max(worst, pct)
    return worst


def uncertainty_limit_pct(config: Config | None = None) -> float:
    """The documented uncertainty gate: ``recommendation_quality.medium``'s spread ceiling.

    Reused rather than reinvented - a candidate whose spread is wider than what the ML layer
    already calls MEDIUM cannot support a recommendation of any quality.
    """
    ml = config if config is not None else load_config(ML)
    return float(ml.get_path("recommendation_quality.medium.max_relative_uncertainty_pct"))


__all__ = [
    "HORIZON_KEY_TEMPLATE",
    "REGIME_LABEL_COLUMN",
    "PredictionBundle",
    "by_horizon",
    "cross_horizon_spread_pct",
    "feature_row",
    "horizon_key",
    "objective_targets",
    "relative_uncertainty_pct",
    "uncertainty_limit_pct",
    "wide_predictions",
    "worst_disagreement_pct",
    "worst_quality",
]
