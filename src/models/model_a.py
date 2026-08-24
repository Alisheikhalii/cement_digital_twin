"""Model A - multi-horizon process prediction (PRD v1.1.1 Sections 13.1, 13.1.1, 13.3, 22).

One model per (target, horizon) pair, exactly as PRD 13.1 requires: a ``RandomForestRegressor`` is
always trained as the baseline, a ``GradientBoostingRegressor`` challenges it, and the pair is chosen
by MAE on a held-out block that is neither the training block nor the test block. Both fitted
families are kept, because the RF/GBM agreement is one of the four Recommendation-Quality factors of
PRD 13.1.1 - discarding the loser would make that factor unavailable at prediction time.

Three deliberate choices are worth stating because they are what keeps the reported numbers honest:

* **Training labels are the measured historian values; evaluation is reported against both the
  measurement and the simulator's noise-free state** (ASSUMPTION, PRD 20 item 2). A real plant only
  ever has noisy labels, so training on them is the honest setup; reporting against truth as well is
  the only way to separate model error from sensor noise, which is a benefit only a synthetic
  environment can offer.
* **The scenario-holdout split gets its own fit.** PRD 13.3 withholds whole regimes from *training*,
  so re-using the chronological model would measure nothing. The model family and hyperparameters
  are *not* re-selected on the holdout, because selecting there would leak the generalization gap
  the split exists to expose.
* **A persistence reference is reported alongside every model.** ADDITION (not PRD-specified,
  documented in ``MODEL_CARD.md``): predicting "the target does not change over the next h minutes"
  costs nothing and is the only way to read an R2 on a minute-sampled, heavily autocorrelated series
  without overstating skill. It is a reporting row, never a deployed model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.config import ML, SCENARIOS, Config, load_config
from src.features.lag_features import FeatureBuilder, FeatureMatrix, FeatureSpec
from src.features.splits import (
    CHRONOLOGICAL,
    SCENARIO_HOLDOUT,
    DataSplit,
    build_splits,
    split_coverage,
    subsample_positions,
)
from src.models.metrics import MEASURED, TRUTH, regression_metrics
from src.models.quality import QualityAssessment, assess_quality
from src.models.uncertainty import (
    BOOTSTRAP_ENSEMBLE,
    TREE_SPREAD,
    BootstrapEnsemble,
    TreeSpread,
    bootstrap_ensemble_from_config,
    disagreement_pct,
    optimizer_targets,
    relative_uncertainty_pct,
)
from src.schema import get_tag, has_tag

RANDOM_FOREST = "random_forest"
GRADIENT_BOOSTING = "gradient_boosting"
LIGHTGBM = "lightgbm"
PERSISTENCE = "persistence_reference"

#: The two mandatory families of PRD 13.1, RF first (it is the declared baseline).
MODEL_FAMILIES: tuple[str, ...] = (RANDOM_FOREST, GRADIENT_BOOSTING)


def build_estimator(family: str, config: Config | None = None) -> Any:
    """Construct an unfitted estimator with every hyperparameter read from ``configs/ml.yaml``."""
    ml = config if config is not None else load_config(ML)
    parameters = dict(ml.get_path(f"models.{family}").to_dict())
    parameters.pop("enabled", None)
    if family == RANDOM_FOREST:
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(**parameters)
    if family == GRADIENT_BOOSTING:
        from sklearn.ensemble import GradientBoostingRegressor

        return GradientBoostingRegressor(**parameters)
    if family == LIGHTGBM:
        raise NotImplementedError(
            "LightGBM is a PRD 13.1 stretch model, promoted only if it measurably beats both "
            "sklearn baselines; models.lightgbm.enabled is the switch and the comparison belongs "
            "in MODEL_CARD.md"
        )
    raise ValueError(f"unknown model family {family!r}; expected one of {MODEL_FAMILIES}")


def available_families(config: Config | None = None) -> tuple[str, ...]:
    """Families actually trained: the two mandatory ones, plus LightGBM only if enabled."""
    ml = config if config is not None else load_config(ML)
    families = list(MODEL_FAMILIES)
    if bool(ml.get_path("models.lightgbm.enabled", False)):
        families.append(LIGHTGBM)
    return tuple(families)


@dataclass(frozen=True, slots=True)
class Prediction:
    """One (target, horizon) prediction with its uncertainty and categorical quality.

    ``uncertainty`` is a width in the target's own unit (PRD 13.1.1 ensemble spread). There is no
    confidence-percentage field, by design: FR-23 allows the width and the category, nothing that
    looks like a calibrated probability.
    """

    dataset: str
    target: str
    horizon_min: int
    unit: str
    value: float
    uncertainty: float
    uncertainty_method: str
    model_family: str
    model_version: str
    alternative_value: float | None
    quality: QualityAssessment

    @property
    def interval(self) -> tuple[float, float]:
        """``value +/- spread`` - an ensemble-spread band, not a calibrated confidence interval."""
        return (self.value - self.uncertainty, self.value + self.uncertainty)

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "target": self.target,
            "horizon_min": self.horizon_min,
            "unit": self.unit,
            "value": self.value,
            "uncertainty": self.uncertainty,
            "uncertainty_method": self.uncertainty_method,
            "uncertainty_interval": list(self.interval),
            "model_family": self.model_family,
            "model_version": self.model_version,
            "alternative_model_value": self.alternative_value,
            **self.quality.describe(),
        }


@dataclass(slots=True)
class HorizonModel:
    """The fitted models, selection evidence and training domain of one (target, horizon) pair."""

    dataset: str
    target: str
    horizon_min: int
    spec: FeatureSpec
    selected_family: str
    estimators: dict[str, Any]
    hyperparameters: dict[str, dict[str, Any]]
    selection: dict[str, Any]
    training_domain: dict[str, Any]
    model_version: str
    config: Config
    bootstrap: BootstrapEnsemble | None = None
    _training: tuple[FeatureMatrix, np.ndarray] | None = field(default=None, repr=False)

    # -- prediction ---------------------------------------------------------------------
    @property
    def unit(self) -> str:
        return get_tag(self.target).unit if has_tag(self.target) else ""

    def features_of(self, frame: pd.DataFrame | pd.Series) -> pd.DataFrame:
        """Reorder/validate a caller's feature frame against this model's own layout."""
        matrix = frame.to_frame().T if isinstance(frame, pd.Series) else frame
        missing = [name for name in self.spec.feature_names if name not in matrix.columns]
        if missing:
            raise ValueError(
                f"{self.dataset}/{self.target}/t+{self.horizon_min}min is missing "
                f"{len(missing)} feature columns, e.g. {missing[:4]}"
            )
        return matrix[list(self.spec.feature_names)]

    def predict(self, frame: pd.DataFrame | pd.Series, *, family: str | None = None) -> np.ndarray:
        estimator = self.estimators[family or self.selected_family]
        return np.asarray(estimator.predict(self.features_of(frame)), dtype=float)

    def uncertainty(self, frame: pd.DataFrame | pd.Series) -> tuple[np.ndarray, str]:
        """Ensemble spread and the method that produced it (PRD 13.1.1).

        When the selected family is the GradientBoosting model, its bootstrap ensemble is required.
        If the ensemble was neither pre-trained nor reachable (no retained training block - e.g.
        after loading artifacts from the registry), the RandomForest tree spread is used instead and
        the returned method string says so. The fallback is visible rather than silent, which is the
        only acceptable way to substitute one documented method for another.
        """
        features = self.features_of(frame)
        if self.selected_family == GRADIENT_BOOSTING:
            ensemble = self.bootstrap or self._fit_bootstrap()
            if ensemble is not None:
                return ensemble.spread(features), BOOTSTRAP_ENSEMBLE
            return (
                TreeSpread(self.estimators[RANDOM_FOREST]).spread(features),
                f"{TREE_SPREAD}__fallback_for_{GRADIENT_BOOSTING}",
            )
        return TreeSpread(self.estimators[self.selected_family]).spread(features), TREE_SPREAD

    def predictions(
        self,
        frame: pd.DataFrame | pd.Series,
        *,
        constraint_margin: float | None = None,
        ood_score_ratio: float | None = None,
    ) -> list[Prediction]:
        """Predict + quantify + label, one :class:`Prediction` per row of ``frame``."""
        features = self.features_of(frame)
        values = self.predict(features)
        spread, method = self.uncertainty(features)
        other = _other_family(self.selected_family)
        alternative = (
            self.predict(features, family=other) if other in self.estimators else None
        )
        relative = relative_uncertainty_pct(spread, values)
        disagreement = (
            None if alternative is None else disagreement_pct(values, alternative)
        )
        results: list[Prediction] = []
        for index in range(len(features)):
            quality = assess_quality(
                relative_uncertainty_pct=float(relative[index]),
                model_disagreement_pct=None if disagreement is None else float(disagreement[index]),
                constraint_margin=constraint_margin,
                ood_score_ratio=ood_score_ratio,
                config=self.config,
            )
            results.append(
                Prediction(
                    dataset=self.dataset,
                    target=self.target,
                    horizon_min=self.horizon_min,
                    unit=self.unit,
                    value=float(values[index]),
                    uncertainty=float(spread[index]),
                    uncertainty_method=method,
                    model_family=self.selected_family,
                    model_version=self.model_version,
                    alternative_value=None if alternative is None else float(alternative[index]),
                    quality=quality,
                )
            )
        return results

    # -- housekeeping -------------------------------------------------------------------
    def artifact_name(self, family: str) -> str:
        """PRD 13.4 artifact name: ``{model_name}_{target}_{horizon}_{version}.joblib``."""
        return f"{family}_{self.target}_t+{self.horizon_min}min_{self.model_version}.joblib"

    def release_training_block(self) -> None:
        """Drop the retained training rows (called once every lazy ensemble has been built)."""
        self._training = None

    def _fit_bootstrap(self) -> BootstrapEnsemble | None:
        if self._training is None:
            return None
        matrix, positions = self._training
        ensemble = bootstrap_ensemble_from_config(
            self.estimators[GRADIENT_BOOSTING], config=self.config
        )
        ensemble.fit(matrix.X(positions), matrix.y(self.target, positions).to_numpy(dtype=float))
        self.bootstrap = ensemble
        return ensemble

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "target": self.target,
            "horizon_min": self.horizon_min,
            "unit": self.unit,
            "selected_family": self.selected_family,
            "model_version": self.model_version,
            "selection": dict(self.selection),
            "hyperparameters": {
                family: dict(values) for family, values in self.hyperparameters.items()
            },
            "uncertainty": {
                "method": (
                    BOOTSTRAP_ENSEMBLE
                    if self.selected_family == GRADIENT_BOOSTING
                    else TREE_SPREAD
                ),
                "bootstrap_members": None if self.bootstrap is None else self.bootstrap.members,
            },
            "training_domain": dict(self.training_domain),
            "feature_spec": self.spec.describe(),
        }


@dataclass(frozen=True, slots=True)
class ModelAResult:
    """Everything one dataset's training run produced (PRD 13.4 registry input, 22 metrics)."""

    dataset: str
    models: dict[tuple[str, int], HorizonModel]
    metric_rows: tuple[dict[str, Any], ...]
    splits: dict[int, dict[str, dict[str, Any]]]
    matrices: dict[int, dict[str, Any]]
    horizons_min: tuple[int, ...]
    targets: tuple[str, ...]

    def model(self, target: str, horizon_min: int) -> HorizonModel:
        return self.models[(target, int(horizon_min))]

    def metric_frame(self) -> pd.DataFrame:
        """The PRD 22 table (one row per target/horizon/split/reference/model)."""
        return pd.DataFrame(list(self.metric_rows))

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "targets": list(self.targets),
            "horizons_min": list(self.horizons_min),
            "pairs": len(self.models),
            "metric_rows": len(self.metric_rows),
            "splits": self.splits,
            "matrices": self.matrices,
        }


class ModelATrainer:
    """Trains and evaluates every (target, horizon) pair of one dataset (PRD 13.1)."""

    __slots__ = ("_builder", "_config", "_dataset", "_scenarios")

    def __init__(
        self,
        dataset: str,
        *,
        config: Config | None = None,
        scenarios: Config | None = None,
    ) -> None:
        self._config = config if config is not None else load_config(ML)
        self._scenarios = scenarios if scenarios is not None else load_config(SCENARIOS)
        self._dataset = dataset
        self._builder = FeatureBuilder(dataset, config=self._config, scenarios=self._scenarios)

    @property
    def builder(self) -> FeatureBuilder:
        return self._builder

    @property
    def config(self) -> Config:
        return self._config

    def train(
        self,
        frame: pd.DataFrame,
        *,
        truth: pd.DataFrame | None = None,
        horizons_min: Sequence[int] | None = None,
        targets: Sequence[str] | None = None,
    ) -> ModelAResult:
        """Fit, select and evaluate every configured (target, horizon) pair.

        ``targets`` acts as a *filter* over the dataset's configured targets, not as an override: the
        two units have different target lists, so a caller training both from one list (the notebook,
        :func:`~src.models.train.train_all`) would otherwise have to know which name belongs to which
        unit. An explicit list that selects nothing is an error rather than an empty result.
        """
        horizons = tuple(int(value) for value in (horizons_min or self._builder.horizons_min))
        configured = tuple(self._builder.targets)
        wanted = configured
        if targets is not None:
            requested = tuple(str(name) for name in targets)
            wanted = tuple(name for name in configured if name in set(requested))
            if not wanted:
                raise ValueError(
                    f"{self._dataset}: none of {list(requested)} is a configured target "
                    f"({list(configured)})"
                )
        minimum_rows = int(self._config.get_path("training.min_rows", 0))
        max_rows = int(self._config.get_path("training.max_rows", 0))
        eager = set(optimizer_targets(self._config))

        models: dict[tuple[str, int], HorizonModel] = {}
        rows: list[dict[str, Any]] = []
        split_report: dict[int, dict[str, dict[str, Any]]] = {}
        matrix_report: dict[int, dict[str, Any]] = {}

        for horizon in horizons:
            matrix = self._builder.build(frame, horizon, truth=truth)
            splits = build_splits(matrix, config=self._config)
            coverage = split_coverage(matrix, splits)
            split_report[horizon] = {
                name: {**split.describe(), "coverage": coverage[name]}
                for name, split in splits.items()
            }
            matrix_report[horizon] = matrix.describe()

            for target in wanted:
                model, target_rows = self._train_pair(
                    matrix=matrix,
                    splits=splits,
                    target=target,
                    max_rows=max_rows,
                    minimum_rows=minimum_rows,
                    eager_bootstrap=target in eager,
                )
                models[(target, horizon)] = model
                rows.extend(target_rows)

        return ModelAResult(
            dataset=self._dataset,
            models=models,
            metric_rows=tuple(rows),
            splits=split_report,
            matrices=matrix_report,
            horizons_min=horizons,
            targets=wanted,
        )

    # -- one (target, horizon) pair -----------------------------------------------------
    def _train_pair(
        self,
        *,
        matrix: FeatureMatrix,
        splits: Mapping[str, DataSplit],
        target: str,
        max_rows: int,
        minimum_rows: int,
        eager_bootstrap: bool,
    ) -> tuple[HorizonModel, list[dict[str, Any]]]:
        chronological = splits[CHRONOLOGICAL]
        holdout = splits[SCENARIO_HOLDOUT]
        labelled = set(matrix.labelled_positions(target).tolist())

        train = subsample_positions(_keep(chronological.train, labelled), max_rows)
        validation = _keep(chronological.validation, labelled)
        test = _keep(chronological.test, labelled)
        if train.size < minimum_rows:
            raise ValueError(
                f"{self._dataset}/{target}/t+{matrix.horizon_min}min has {train.size} training "
                f"rows, below training.min_rows={minimum_rows}"
            )

        families = available_families(self._config)
        estimators: dict[str, Any] = {}
        hyperparameters: dict[str, dict[str, Any]] = {}
        validation_metrics: dict[str, dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []

        for family in families:
            estimator = build_estimator(family, self._config)
            estimator.fit(matrix.X(train), matrix.y(target, train).to_numpy(dtype=float))
            estimators[family] = estimator
            hyperparameters[family] = _hyperparameters(estimator)
            if validation.size:
                measured = self._metrics(
                    matrix, validation, target, estimator.predict(matrix.X(validation))
                )
                validation_metrics[family] = measured[MEASURED]
                rows.extend(
                    self._rows(
                        target=target,
                        horizon_min=matrix.horizon_min,
                        split=CHRONOLOGICAL,
                        block="validation",
                        model=family,
                        selected=False,
                        metrics=measured,
                    )
                )

        selected = self._select(validation_metrics, families)
        selection = {
            "metric": str(self._config.get_path("models.selection_metric", "mae")),
            "selected_on": "chronological validation block (PRD 13.1 held-out MAE)",
            "validation_rows": int(validation.size),
            "validation_mae": {
                family: metrics.get("mae") for family, metrics in validation_metrics.items()
            },
            "selected_family": selected,
            "reselected_on_scenario_holdout": False,
        }

        # -- chronological test block: every family plus the persistence reference -------
        for family in families:
            rows.extend(
                self._rows(
                    target=target,
                    horizon_min=matrix.horizon_min,
                    split=CHRONOLOGICAL,
                    block="test",
                    model=family,
                    selected=family == selected,
                    metrics=self._metrics(
                        matrix, test, target, estimators[family].predict(matrix.X(test))
                    ),
                )
            )
        rows.extend(
            self._rows(
                target=target,
                horizon_min=matrix.horizon_min,
                split=CHRONOLOGICAL,
                block="test",
                model=PERSISTENCE,
                selected=False,
                metrics=self._metrics(matrix, test, target, self._persistence(matrix, test, target)),
            )
        )

        # -- scenario holdout: its own fit of the selected family (PRD 13.3) -------------
        holdout_train = subsample_positions(_keep(holdout.train, labelled), max_rows)
        holdout_test = _keep(holdout.test, labelled)
        if holdout_train.size >= max(minimum_rows, 1) and holdout_test.size:
            holdout_model = build_estimator(selected, self._config)
            holdout_model.fit(
                matrix.X(holdout_train), matrix.y(target, holdout_train).to_numpy(dtype=float)
            )
            rows.extend(
                self._rows(
                    target=target,
                    horizon_min=matrix.horizon_min,
                    split=SCENARIO_HOLDOUT,
                    block="test",
                    model=selected,
                    selected=True,
                    metrics=self._metrics(
                        matrix, holdout_test, target, holdout_model.predict(matrix.X(holdout_test))
                    ),
                )
            )
            rows.extend(
                self._rows(
                    target=target,
                    horizon_min=matrix.horizon_min,
                    split=SCENARIO_HOLDOUT,
                    block="test",
                    model=PERSISTENCE,
                    selected=False,
                    metrics=self._metrics(
                        matrix, holdout_test, target, self._persistence(matrix, holdout_test, target)
                    ),
                )
            )
        else:
            selection["scenario_holdout_skipped"] = (
                f"train rows {holdout_train.size}, test rows {holdout_test.size}"
            )

        model = HorizonModel(
            dataset=self._dataset,
            target=target,
            horizon_min=matrix.horizon_min,
            spec=matrix.spec,
            selected_family=selected,
            estimators=estimators,
            hyperparameters=hyperparameters,
            selection=selection,
            training_domain=self._training_domain(matrix, train),
            model_version=str(self._config.get_path("registry.model_version", "v1")),
            config=self._config,
            _training=(matrix, train),
        )
        if eager_bootstrap and selected == GRADIENT_BOOSTING:
            model._fit_bootstrap()
        return model, rows

    # -- helpers ------------------------------------------------------------------------
    def _select(self, validation: Mapping[str, Mapping[str, Any]], families: Sequence[str]) -> str:
        """PRD 13.1: lowest held-out MAE wins; the RF baseline wins ties and empty cases."""
        metric = str(self._config.get_path("models.selection_metric", "mae"))
        scored = [
            (float(values[metric]), family)
            for family, values in validation.items()
            if values.get(metric) is not None
        ]
        if not scored:
            return families[0]
        best = min(scored, key=lambda item: (item[0], list(families).index(item[1])))
        return best[1]

    def _metrics(
        self,
        matrix: FeatureMatrix,
        positions: np.ndarray,
        target: str,
        predicted: np.ndarray,
    ) -> dict[str, dict[str, Any]]:
        """Metrics against the measurement and, when available, the noise-free state."""
        report = {
            MEASURED: regression_metrics(
                matrix.y(target, positions).to_numpy(dtype=float), predicted, config=self._config
            )
        }
        if matrix.truth_targets is not None:
            report[TRUTH] = regression_metrics(
                matrix.y_truth(target, positions).to_numpy(dtype=float),
                predicted,
                config=self._config,
            )
        return report

    @staticmethod
    def _persistence(matrix: FeatureMatrix, positions: np.ndarray, target: str) -> np.ndarray:
        """"Nothing changes over the horizon": the current measured value, held forward."""
        return matrix.X(positions)[target].to_numpy(dtype=float)

    def _rows(
        self,
        *,
        target: str,
        horizon_min: int,
        split: str,
        block: str,
        model: str,
        selected: bool,
        metrics: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "dataset": self._dataset,
                "target": target,
                "horizon_min": horizon_min,
                "horizon": f"t+{horizon_min}min",
                "split": split,
                "block": block,
                "model": model,
                "selected": bool(selected),
                "reference": reference,
                **dict(values),
            }
            for reference, values in metrics.items()
        ]

    def _training_domain(self, matrix: FeatureMatrix, positions: np.ndarray) -> dict[str, Any]:
        """Ranges and regimes actually represented in training (PRD 13.4, consumed by 14.3).

        Only the *current-value* columns are recorded: PRD 14.3 check 1 validates a proposed
        manipulated variable, and a candidate setpoint is a value at ``t``, not at ``t-15 min``.
        """
        frame = matrix.X(positions)[list(matrix.spec.base_columns)]
        stamps = matrix.timestamp.loc[list(positions)]
        regimes = matrix.regime.loc[list(positions)].dropna().unique().tolist()
        return {
            "rows": int(positions.size),
            "timestamp_range": [str(stamps.min()), str(stamps.max())],
            "operating_regimes": sorted(str(name) for name in regimes),
            "variable_ranges": {
                column: [float(frame[column].min()), float(frame[column].max())]
                for column in frame.columns
            },
        }


def _keep(positions: np.ndarray, labelled: set[int]) -> np.ndarray:
    """Restrict split positions to rows whose measured label survived dropout."""
    if positions.size == 0:
        return positions
    mask = np.fromiter((int(value) in labelled for value in positions), dtype=bool, count=positions.size)
    return positions[mask]


def _other_family(family: str) -> str:
    return GRADIENT_BOOSTING if family == RANDOM_FOREST else RANDOM_FOREST


def _hyperparameters(estimator: Any) -> dict[str, Any]:
    """JSON-safe hyperparameters for the registry (PRD 13.4)."""
    return {
        key: (value if isinstance(value, (int, float, str, bool, type(None))) else str(value))
        for key, value in estimator.get_params().items()
    }


__all__ = [
    "GRADIENT_BOOSTING",
    "HorizonModel",
    "LIGHTGBM",
    "MODEL_FAMILIES",
    "ModelAResult",
    "ModelATrainer",
    "PERSISTENCE",
    "Prediction",
    "RANDOM_FOREST",
    "available_families",
    "build_estimator",
]
