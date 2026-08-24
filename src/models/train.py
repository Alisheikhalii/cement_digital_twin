"""Training orchestration and the PRD v1.1.1 Section 22 metric reports.

One entry point per model plus a combined one, each of which does exactly three things: fit, measure,
and write the artefacts PRD 13.4 and 22 name. Nothing here decides anything a model does not already
decide for itself - the split rules live in :mod:`src.features.splits`, the family choice in
:class:`~src.models.model_a.ModelATrainer`, the anomaly decision in
:class:`~src.anomaly_detection.AnomalyDetector`. This module is the wiring plus the JSON layout.

Outputs
-------
``reports/metrics/model_a_horizon_metrics.json``
    MAE / RMSE / R2 / MAPE per target, per horizon, per split block, per model, against both the
    measurement and the noise-free simulator state (PRD 22 and PRD 34 item 2).
``reports/metrics/model_b_metrics.json``
    Precision / recall / F1 / false-positive rate against ``injected_fault``, per-regime recall, the
    sensor-versus-process discrimination, and the alternate decision rules that were not adopted.
``models/{unit}/*.joblib`` + ``models/registry.json``
    The PRD 13.4 registry, written only when ``register=True``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.anomaly_detection import AnomalyDetector, AnomalyEvaluation
from src.config import ML, Config, load_config
from src.features.splits import CHRONOLOGICAL, SCENARIO_HOLDOUT
from src.models.model_a import ModelAResult, ModelATrainer
from src.models.registry import dataset_hash, register_result, registry_summary, write_registry
from src.paths import REPORTS_METRICS_DIR

#: Filenames PRD 22 reports are written under.
MODEL_A_METRICS = "model_a_horizon_metrics.json"
MODEL_B_METRICS = "model_b_metrics.json"

#: The Model B split names reported. ``all_rows`` is the primary row: PRD 13.2 fits the forest on
#: normal-regime windows and scores *all* data, and a 3-day chronological tail can contain only one
#: or two regimes, which makes a tail-only precision/recall pair a statement about the schedule
#: rather than about the detector.
ALL_ROWS = "all_rows"


@dataclass(frozen=True, slots=True)
class ModelBResult:
    """One dataset's fitted anomaly detector and the evaluations of it."""

    dataset: str
    detector: AnomalyDetector
    evaluations: dict[str, AnomalyEvaluation]

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "detector": self.detector.describe(),
            "splits": {name: block.describe() for name, block in self.evaluations.items()},
        }


@dataclass(frozen=True, slots=True)
class TrainingRun:
    """Everything one call to :func:`train_all` produced, per dataset."""

    model_a: dict[str, ModelAResult]
    model_b: dict[str, ModelBResult]
    reports: dict[str, Path]
    registry: Path | None

    def describe(self) -> dict[str, Any]:
        return {
            "model_a": {name: result.describe() for name, result in self.model_a.items()},
            "model_b": {name: result.describe() for name, result in self.model_b.items()},
            "reports": {name: str(path) for name, path in self.reports.items()},
            "registry": None if self.registry is None else str(self.registry),
        }


# -- Model A ----------------------------------------------------------------------------------
def train_model_a(
    dataset: str,
    frame: pd.DataFrame,
    *,
    truth: pd.DataFrame | None = None,
    horizons_min: Sequence[int] | None = None,
    targets: Sequence[str] | None = None,
    config: Config | None = None,
    scenarios: Config | None = None,
) -> ModelAResult:
    """Fit, select and evaluate every configured (target, horizon) pair of one dataset."""
    trainer = ModelATrainer(dataset, config=config, scenarios=scenarios)
    return trainer.train(frame, truth=truth, horizons_min=horizons_min, targets=targets)


def model_a_report(
    results: Mapping[str, ModelAResult],
    *,
    config: Config | None = None,
) -> dict[str, Any]:
    """The PRD 22 payload: the flat metric table plus the index needed to read it."""
    ml = config if config is not None else load_config(ML)
    rows: list[dict[str, Any]] = []
    for result in results.values():
        rows.extend(dict(row) for row in result.metric_rows)
    return {
        "prd_version": str(ml.get_path("meta.prd_version", "1.1.1")),
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "synthetic_only": True,
        "metric_definitions": {
            "mae": "mean absolute error, target units",
            "rmse": "root mean squared error, target units",
            "r2": "coefficient of determination on the evaluated block",
            "mape": (
                "mean absolute percentage error; omitted with a stated reason where the target "
                "crosses or approaches zero"
            ),
        },
        "references": {
            "measured": "scored against the sensor-layer measurement the model was trained on",
            "truth": (
                "scored against the simulator's noise-free state - available only in a synthetic "
                "environment and the separation PRD 20 item 2 exists to expose"
            ),
        },
        "splits": {
            CHRONOLOGICAL: "PRD 13.3 chronological train/validation/test, no shuffling",
            SCENARIO_HOLDOUT: "PRD 13.3 scenario holdout: at least one entire labelled regime",
        },
        "models": {
            "persistence": (
                "reference, not a fitted model: the current measured value held over the horizon. "
                "ADDITION beyond the PRD's named baselines, reported so a metric can be read as "
                "better-than-nothing rather than in isolation"
            )
        },
        "datasets": {
            name: {
                "targets": list(result.targets),
                "horizons_min": list(result.horizons_min),
                "pairs": len(result.models),
                "splits": result.splits,
                "feature_matrices": result.matrices,
                "selection": {
                    f"{target}@t+{horizon}min": result.models[(target, horizon)].selection
                    for target, horizon in result.models
                },
            }
            for name, result in results.items()
        },
        "rows": rows,
    }


# -- Model B ----------------------------------------------------------------------------------
def model_b_splits(
    frame: pd.DataFrame,
    *,
    config: Config | None = None,
) -> dict[str, dict[str, Any]]:
    """The row blocks Model B is fitted and measured on (PRD 13.3, applied to Section 13.2).

    Model B has no horizon and no lag window, so it needs no embargo: the only leakage route is
    fitting on rows that are then scored, and each block below states exactly which rows were fitted.

    ``all_rows``
        Fitted on the normal rows of the chronological training fraction, scored on every row. This
        is the primary PRD 22 row because PRD 13.2 specifies exactly that - "trained on normal
        operation windows, scored on all data".
    ``chronological``
        The same fit, scored on the last ``1 - train_fraction`` of the run. Reported as a secondary
        block: over a short run this tail can contain one or two regimes, so its precision/recall
        describes the scenario schedule as much as the detector.
    ``scenario_holdout``
        Fitted with the ``splits.scenario_holdout_regimes`` rows withheld from *both* the forest and
        the regime-signature library, then scored on those regimes alone - "how does it behave during
        a condition it has never seen", which for Model B also means "can it still name it".
    """
    ml = config if config is not None else load_config(ML)
    train_fraction = float(ml.get_path("splits.chronological_train_fraction"))
    holdout = tuple(str(name) for name in ml.get_path("splits.scenario_holdout_regimes"))
    positions = list(frame.index)
    boundary = int(round(len(positions) * train_fraction))
    regime = (
        frame["operating_regime"].astype(str)
        if "operating_regime" in frame.columns
        else pd.Series("", index=frame.index)
    )
    in_holdout = regime.isin(holdout).to_numpy(dtype=bool)

    return {
        ALL_ROWS: {
            "fit": positions[:boundary],
            "evaluate": positions,
            "detail": (
                f"fitted on the first {train_fraction:.0%} of the run, scored on every row "
                "(PRD 13.2)"
            ),
        },
        CHRONOLOGICAL: {
            "fit": positions[:boundary],
            "evaluate": positions[boundary:],
            "detail": f"fitted on the first {train_fraction:.0%}, scored on the remainder",
        },
        SCENARIO_HOLDOUT: {
            "fit": [
                position for position, held in zip(positions, in_holdout.tolist(), strict=True)
                if not held
            ],
            "evaluate": [
                position for position, held in zip(positions, in_holdout.tolist(), strict=True)
                if held
            ],
            "detail": f"regimes withheld from the fit and scored on their own: {list(holdout)}",
            "holdout_regimes": list(holdout),
        },
    }


def train_model_b(
    dataset: str,
    frame: pd.DataFrame,
    *,
    config: Config | None = None,
    scenarios: Config | None = None,
) -> ModelBResult:
    """Fit one detector per block and evaluate it, keeping the primary fit as the shipped detector.

    Each block gets its own fit so that no reported number was produced by a detector that had
    already seen the rows it is being scored on. The detector returned on the result is the
    ``all_rows`` one, which is the configuration the UI and the Section 14.3 gate use.
    """
    blocks = model_b_splits(frame, config=config)
    evaluations: dict[str, AnomalyEvaluation] = {}
    primary: AnomalyDetector | None = None

    for name, block in blocks.items():
        detector = AnomalyDetector(dataset, config=config, scenarios=scenarios)
        detector.fit(frame, positions=block["fit"])
        evaluation = detector.evaluate(frame, split=name, positions=block["evaluate"])
        evaluations[name] = evaluation
        if name == ALL_ROWS:
            primary = detector

    if primary is None:  # pragma: no cover - ALL_ROWS is always in the block map
        raise RuntimeError("Model B produced no primary fit")
    return ModelBResult(dataset=dataset, detector=primary, evaluations=evaluations)


def model_b_report(
    results: Mapping[str, ModelBResult],
    *,
    config: Config | None = None,
) -> dict[str, Any]:
    """The PRD 22 anomaly payload, with the blocks that were *not* adopted kept visible."""
    ml = config if config is not None else load_config(ML)
    return {
        "prd_version": str(ml.get_path("meta.prd_version", "1.1.1")),
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "synthetic_only": True,
        "ground_truth": "injected_fault is non-null (PRD 22), labelled by operating_regime",
        "primary_split": ALL_ROWS,
        "methods": {
            "method_1": (
                "Isolation Forest on the instantaneous manipulated + process variable block, fitted "
                "on normal-regime rows only - PRD 13.2's primary detector and the only component "
                "that raises the banner"
            ),
            "method_2": (
                "per-tag rolling mean / EWMA control charts with +/-sigma_limit bands - PRD 13.2's "
                "always-on secondary method, used to answer which variable is out of band and to "
                "rank the PRD 15 affected-variable list, not to vote on the banner"
            ),
        },
        "metric_definitions": {
            "precision": "of the rows reported, the fraction that carried an injected fault",
            "recall": "of the rows carrying an injected fault, the fraction reported",
            "false_positive_rate": "of the fault-free rows, the fraction reported",
            "per_regime_recall": (
                "per operating_regime. injected_fault is per-unit while operating_regime is "
                "plant-level, so a regime that perturbs the other unit appears here as a "
                "false-positive check - read the 'metric' field of each entry"
            ),
            "alternates": (
                "the same metrics for the banner decisions that were *not* adopted, scored on the "
                "same rows: 'spc_single_sample' is method 2 alone, 'forest_or_spc_single_sample' is "
                "the union of both configured methods, and 'out_of_distribution_gate' is the same "
                "forest score at the stricter PRD 14.3 optimizer-gate percentile"
            ),
        },
        "datasets": {name: result.describe() for name, result in results.items()},
    }


# -- writing ----------------------------------------------------------------------------------
def write_report(
    payload: Mapping[str, Any],
    filename: str,
    *,
    directory: Path | str | None = None,
) -> Path:
    """Write one PRD 22 report as JSON, creating ``reports/metrics`` if needed."""
    folder = Path(directory) if directory is not None else REPORTS_METRICS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / filename
    destination.write_text(
        json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    return destination


def _json_default(value: Any) -> Any:
    """numpy scalars, pandas timestamps and NaN, in the JSON forms a reader expects."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return None if number != number else number
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def train_all(
    datasets: Mapping[str, pd.DataFrame],
    *,
    truth: Mapping[str, pd.DataFrame] | None = None,
    horizons_min: Sequence[int] | None = None,
    targets: Sequence[str] | None = None,
    register: bool = True,
    simulation: Mapping[str, Any] | None = None,
    config: Config | None = None,
    scenarios: Config | None = None,
    metrics_dir: Path | str | None = None,
    models_dir: Path | str | None = None,
    registry_path: Path | str | None = None,
) -> TrainingRun:
    """Train both models on every dataset, write the PRD 22 reports and the PRD 13.4 registry.

    ``simulation`` is the generator's provenance block; it is stored verbatim on every registry entry
    so a model can always be traced to the simulation config version that produced its data.
    """
    ml = config if config is not None else load_config(ML)
    a_results: dict[str, ModelAResult] = {}
    b_results: dict[str, ModelBResult] = {}
    entries: list[dict[str, Any]] = []

    for name, frame in datasets.items():
        prepared = frame.reset_index(drop=True)
        truth_frame = None
        if truth is not None and name in truth:
            truth_frame = truth[name].reset_index(drop=True)

        a_results[name] = train_model_a(
            name,
            prepared,
            truth=truth_frame,
            horizons_min=horizons_min,
            targets=targets,
            config=ml,
            scenarios=scenarios,
        )
        b_results[name] = train_model_b(name, prepared, config=ml, scenarios=scenarios)

        if register:
            entries.extend(
                register_result(
                    a_results[name],
                    hash_of_dataset=dataset_hash(prepared),
                    simulation=simulation,
                    directory=models_dir,
                )
            )

    reports = {
        "model_a": write_report(
            model_a_report(a_results, config=ml), MODEL_A_METRICS, directory=metrics_dir
        ),
        "model_b": write_report(
            model_b_report(b_results, config=ml), MODEL_B_METRICS, directory=metrics_dir
        ),
    }
    registry = None
    if register:
        registry = write_registry(entries, path=registry_path, config=ml)

    return TrainingRun(model_a=a_results, model_b=b_results, reports=reports, registry=registry)


def training_summary(run: TrainingRun) -> dict[str, Any]:
    """The short block the notebook and the model card print after a training run."""
    return {
        "datasets": sorted(run.model_a),
        "model_a_pairs": {name: len(result.models) for name, result in run.model_a.items()},
        "model_a_metric_rows": {
            name: len(result.metric_rows) for name, result in run.model_a.items()
        },
        "model_b_splits": {name: sorted(result.evaluations) for name, result in run.model_b.items()},
        "registry": None if run.registry is None else registry_summary(run.registry),
        "reports": {name: str(path) for name, path in run.reports.items()},
    }


__all__ = [
    "ALL_ROWS",
    "MODEL_A_METRICS",
    "MODEL_B_METRICS",
    "ModelBResult",
    "TrainingRun",
    "model_a_report",
    "model_b_report",
    "model_b_splits",
    "train_all",
    "train_model_a",
    "train_model_b",
    "training_summary",
    "write_report",
]
