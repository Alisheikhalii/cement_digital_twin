"""Uncertainty estimation for Model A (PRD v1.1.1 Section 13.1.1).

The PRD names the method rather than leaving it open, precisely so that the number behind the
categorical Recommendation Quality is defensible:

* ``RandomForestRegressor`` - the **spread across individual trees** on a given input.
* ``GradientBoostingRegressor`` - it has no per-sample variance, so an explicit **bootstrap
  ensemble** of ``N=20`` models (``configs/ml.yaml → uncertainty.bootstrap_ensemble_size``) trained
  on bootstrap-resampled training sets supplies the spread.

Both produce a width in the target's own engineering units (deg C, %, kWh/t). That width is an
input to :mod:`src.models.quality`, which maps it - together with model agreement, constraint margin
and distance from the training distribution - onto HIGH / MEDIUM / LOW. It is never rendered as a
confidence percentage anywhere (FR-23, AC-18): a percentage would imply a calibrated probability
that an ensemble spread does not provide. Calibrated intervals (conformal prediction) are a
documented Phase-2 item (PRD 32).

Every resample draws from a seeded :class:`numpy.random.Generator` built from the configured
``random_state``; no global RNG is touched anywhere (NFR-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from src.config import ML, Config, load_config

TREE_SPREAD = "random_forest_tree_spread"
BOOTSTRAP_ENSEMBLE = "gradient_boosting_bootstrap_ensemble"

#: Human-readable descriptions of the two methods, quoted verbatim into ``MODEL_CARD.md``.
METHOD_DESCRIPTIONS: dict[str, str] = {
    TREE_SPREAD: (
        "Standard deviation of the individual decision trees' predictions inside the fitted "
        "RandomForestRegressor (PRD 13.1.1)."
    ),
    BOOTSTRAP_ENSEMBLE: (
        "Standard deviation across an explicit bootstrap ensemble of GradientBoostingRegressor "
        "models, each fitted on a bootstrap resample of the training rows (PRD 13.1.1, N "
        "configurable)."
    ),
}


class SpreadEstimator(Protocol):
    """Anything that can turn a feature matrix into a per-row uncertainty width."""

    method: str
    members: int

    def spread(self, features: pd.DataFrame | np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class TreeSpread:
    """Per-tree spread of a fitted ``RandomForestRegressor`` (PRD 13.1.1, first bullet)."""

    forest: Any
    method: str = TREE_SPREAD

    @property
    def members(self) -> int:
        return int(len(self.forest.estimators_))

    def member_predictions(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        matrix = _as_matrix(features)
        return np.vstack([tree.predict(matrix) for tree in self.forest.estimators_])

    def spread(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        return np.std(self.member_predictions(features), axis=0)

    def describe(self) -> dict[str, Any]:
        return {"method": self.method, "members": self.members, "detail": METHOD_DESCRIPTIONS[self.method]}


class BootstrapEnsemble:
    """Bootstrap ensemble supplying the spread a ``GradientBoostingRegressor`` cannot (PRD 13.1.1).

    The ensemble is *not* the predictor: the selected model of PRD 13.1 stays the single model
    trained on the full training block, and this object only measures how much that model's
    prediction moves when the training rows are resampled. Keeping the two apart means the reported
    prediction never silently changes when the uncertainty configuration does.
    """

    __slots__ = ("_members", "_n_estimators", "_rows", "_seed", "_size", "method", "template")

    def __init__(
        self,
        template: Any,
        *,
        size: int,
        max_rows: int,
        n_estimators: int | None = None,
        random_state: int = 0,
    ) -> None:
        self.template = template
        self.method = BOOTSTRAP_ENSEMBLE
        self._size = int(size)
        self._rows = int(max_rows)
        self._seed = int(random_state)
        self._members: list[Any] = []
        self._n_estimators = n_estimators

    @property
    def members(self) -> int:
        return len(self._members)

    def fit(self, features: pd.DataFrame | np.ndarray, actual: Sequence[float] | np.ndarray) -> "BootstrapEnsemble":
        """Fit ``size`` clones, each on a seeded bootstrap resample of the training rows."""
        from sklearn.base import clone

        matrix = _as_matrix(features)
        target = np.asarray(actual, dtype=float)
        if matrix.shape[0] != target.shape[0]:
            raise ValueError("features and target row counts differ")
        rows = matrix.shape[0]
        draw = min(rows, self._rows) if self._rows > 0 else rows

        self._members = []
        for member in range(self._size):
            generator = np.random.default_rng(self._seed + member)
            picked = generator.integers(0, rows, size=draw)
            model = clone(self.template)
            parameters: dict[str, Any] = {"random_state": self._seed + member}
            if self._n_estimators is not None and hasattr(model, "n_estimators"):
                parameters["n_estimators"] = int(self._n_estimators)
            model.set_params(**{k: v for k, v in parameters.items() if k in model.get_params()})
            model.fit(matrix[picked], target[picked])
            self._members.append(model)
        return self

    def member_predictions(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        if not self._members:
            raise RuntimeError("BootstrapEnsemble.fit must be called before predicting")
        matrix = _as_matrix(features)
        return np.vstack([model.predict(matrix) for model in self._members])

    def predict(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        """Ensemble mean - reported only for diagnostics, never as the model's prediction."""
        return np.mean(self.member_predictions(features), axis=0)

    def spread(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        return np.std(self.member_predictions(features), axis=0)

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "members": self.members,
            "bootstrap_max_rows": self._rows,
            "bootstrap_n_estimators": self._n_estimators,
            "random_state": self._seed,
            "detail": METHOD_DESCRIPTIONS[self.method],
        }


def bootstrap_ensemble_from_config(
    template: Any, *, config: Config | None = None
) -> BootstrapEnsemble:
    """Build the PRD 13.1.1 bootstrap ensemble with every number read from ``configs/ml.yaml``."""
    ml = config if config is not None else load_config(ML)
    return BootstrapEnsemble(
        template,
        size=int(ml.get_path("uncertainty.bootstrap_ensemble_size")),
        max_rows=int(ml.get_path("uncertainty.bootstrap_max_rows")),
        n_estimators=int(ml.get_path("uncertainty.bootstrap_n_estimators")),
        random_state=int(ml.get_path("models.gradient_boosting.random_state", 0)),
    )


def optimizer_targets(config: Config | None = None) -> tuple[str, ...]:
    """Targets whose bootstrap ensemble is trained eagerly (the ones the optimizer reads)."""
    ml = config if config is not None else load_config(ML)
    if not bool(ml.get_path("uncertainty.pretrain_for_optimizer_targets_only", True)):
        return ()
    return tuple(str(name) for name in ml.get_path("uncertainty.optimizer_targets", ()))


def relative_uncertainty_pct(spread: np.ndarray | float, prediction: np.ndarray | float) -> np.ndarray:
    """Spread as a percentage of the prediction magnitude - an internal factor, never displayed.

    This is the quantity ``recommendation_quality`` thresholds against. It is deliberately *not*
    surfaced in the UI: PRD 13.1.1/FR-23 allow a physical width ("+/- 12 deg C, ensemble spread")
    and a categorical quality label, not a percentage that reads like a calibrated confidence.
    """
    width = np.abs(np.asarray(spread, dtype=float))
    scale = np.abs(np.asarray(prediction, dtype=float))
    safe = np.where(scale > 0.0, scale, np.nan)
    return 100.0 * width / safe


def disagreement_pct(first: np.ndarray | float, second: np.ndarray | float) -> np.ndarray:
    """|RF - GBM| as a percentage of their mean magnitude (PRD 13.1.1 "model agreement")."""
    left = np.asarray(first, dtype=float)
    right = np.asarray(second, dtype=float)
    scale = np.abs(0.5 * (left + right))
    safe = np.where(scale > 0.0, scale, np.nan)
    return 100.0 * np.abs(left - right) / safe


def _as_matrix(features: pd.DataFrame | np.ndarray) -> np.ndarray:
    if isinstance(features, pd.DataFrame):
        return features.to_numpy(dtype=float)
    matrix = np.asarray(features, dtype=float)
    return matrix.reshape(1, -1) if matrix.ndim == 1 else matrix


__all__ = [
    "BOOTSTRAP_ENSEMBLE",
    "BootstrapEnsemble",
    "METHOD_DESCRIPTIONS",
    "SpreadEstimator",
    "TREE_SPREAD",
    "TreeSpread",
    "bootstrap_ensemble_from_config",
    "disagreement_pct",
    "optimizer_targets",
    "relative_uncertainty_pct",
]
