"""Model registry (PRD v1.1.1 Section 13.4).

Artefacts land at ``models/{unit}/{model_name}_{target}_{horizon}_{version}.joblib`` and every one of
them gets an entry in ``models/registry.json`` recording exactly what PRD 13.4 lists: the training
timestamp, the dataset hash, the feature list, the hyperparameters, the metrics for *both* split
types, the training data range together with the operating regimes represented, and the simulation
config version.

The dataset hash is what makes the rest meaningful: a metric row is only interpretable next to the
data that produced it, and a synthetic environment can regenerate its data at any moment. Recording
the hash means a stale model can be *detected* rather than quietly re-used
(:func:`entry_matches_dataset`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import ML, Config, load_config
from src.features.lag_features import FeatureSpec
from src.models.model_a import HorizonModel, ModelAResult
from src.models.uncertainty import BOOTSTRAP_ENSEMBLE, BootstrapEnsemble
from src.paths import MODEL_REGISTRY_PATH, MODELS_DIR

#: Name under which a bootstrap ensemble is stored (PRD 13.1.1 uncertainty companion).
BOOTSTRAP_ARTIFACT = "bootstrap_ensemble"

#: Registry schema marker, so a future change can be detected rather than guessed.
REGISTRY_SCHEMA = "model_a/1"


def dataset_hash(frame: pd.DataFrame) -> str:
    """Stable SHA-256 over the frame's values and column order (PRD 13.4 "dataset hash")."""
    digest = hashlib.sha256()
    digest.update("|".join(map(str, frame.columns)).encode("utf-8"))
    digest.update(str(frame.shape).encode("utf-8"))
    hashed = pd.util.hash_pandas_object(frame, index=False, categorize=False)
    digest.update(hashed.to_numpy().tobytes())
    return digest.hexdigest()


def dataset_dir(dataset: str, *, directory: Path | str | None = None) -> Path:
    """``models/{unit}`` - PRD 13.4 keeps one sub-directory per unit."""
    root = Path(directory) if directory is not None else MODELS_DIR
    return root / dataset


def artifact_path(
    dataset: str, filename: str, *, directory: Path | str | None = None
) -> Path:
    """``models/{unit}/{filename}`` - the PRD 13.4 layout."""
    return dataset_dir(dataset, directory=directory) / filename


def bootstrap_artifact_name(target: str, horizon_min: int, version: str) -> str:
    return f"{BOOTSTRAP_ARTIFACT}_{target}_t+{horizon_min}min_{version}.joblib"


def save_horizon_model(
    model: HorizonModel,
    *,
    metrics: Mapping[str, Any],
    hash_of_dataset: str,
    simulation: Mapping[str, Any] | None = None,
    directory: Path | str | None = None,
) -> dict[str, Any]:
    """Persist every fitted family of one pair and return its ``registry.json`` entry."""
    import joblib

    folder = dataset_dir(model.dataset, directory=directory)
    folder.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {}
    for family, estimator in model.estimators.items():
        filename = model.artifact_name(family)
        payload = {
            "estimator": estimator,
            "spec": model.spec,
            "dataset": model.dataset,
            "target": model.target,
            "horizon_min": model.horizon_min,
            "family": family,
            "model_version": model.model_version,
        }
        joblib.dump(payload, folder / filename)
        artifacts[family] = filename

    if model.bootstrap is not None:
        filename = bootstrap_artifact_name(model.target, model.horizon_min, model.model_version)
        joblib.dump(
            {
                "ensemble": model.bootstrap,
                "spec": model.spec,
                "dataset": model.dataset,
                "target": model.target,
                "horizon_min": model.horizon_min,
                "family": BOOTSTRAP_ENSEMBLE,
                "model_version": model.model_version,
            },
            folder / filename,
        )
        artifacts[BOOTSTRAP_ARTIFACT] = filename

    described = model.describe()
    return {
        "schema": REGISTRY_SCHEMA,
        "dataset": model.dataset,
        "target": model.target,
        "horizon_min": model.horizon_min,
        "horizon": f"t+{model.horizon_min}min",
        "unit": model.unit,
        "model_version": model.model_version,
        "selected_family": model.selected_family,
        "selection": described["selection"],
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_hash": hash_of_dataset,
        "simulation_config": dict(simulation or {}),
        "artifacts": artifacts,
        "feature_list": list(model.spec.feature_names),
        "feature_count": len(model.spec.feature_names),
        "feature_spec": described["feature_spec"],
        "hyperparameters": described["hyperparameters"],
        "uncertainty": described["uncertainty"],
        "training_domain": described["training_domain"],
        "metrics": dict(metrics),
    }


def metrics_by_pair(result: ModelAResult) -> dict[tuple[str, int], dict[str, Any]]:
    """Group a run's metric rows into the per-pair, per-split payload PRD 13.4 stores."""
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for row in result.metric_rows:
        key = (str(row["target"]), int(row["horizon_min"]))
        split = grouped.setdefault(key, {}).setdefault(str(row["split"]), {})
        block = split.setdefault(str(row["block"]), {})
        model = block.setdefault(str(row["model"]), {})
        model[str(row["reference"])] = {
            name: row.get(name)
            for name in (
                "rows",
                "mae",
                "rmse",
                "r2",
                "mape",
                "mape_omitted_reason",
                "actual_mean",
                "actual_std",
                "actual_range",
            )
        }
    return grouped


def register_result(
    result: ModelAResult,
    *,
    hash_of_dataset: str,
    simulation: Mapping[str, Any] | None = None,
    directory: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Persist every pair of one dataset's run and return the entries (not yet written)."""
    grouped = metrics_by_pair(result)
    entries: list[dict[str, Any]] = []
    for (target, horizon), model in result.models.items():
        entries.append(
            save_horizon_model(
                model,
                metrics=grouped.get((target, horizon), {}),
                hash_of_dataset=hash_of_dataset,
                simulation=simulation,
                directory=directory,
            )
        )
    return entries


def write_registry(
    entries: Iterable[Mapping[str, Any]],
    *,
    path: Path | str | None = None,
    config: Config | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write ``models/registry.json``, replacing entries of the same (dataset, target, horizon)."""
    ml = config if config is not None else load_config(ML)
    destination = Path(path) if path is not None else MODEL_REGISTRY_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)

    keep: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    if destination.exists():
        for entry in read_registry(destination).get("models", []):
            keep[_key(entry)] = dict(entry)
    for entry in entries:
        keep[_key(entry)] = dict(entry)

    payload = {
        "schema": REGISTRY_SCHEMA,
        "prd_version": str(ml.get_path("meta.prd_version", "1.1.1")),
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **dict(extra or {}),
        "models": [keep[key] for key in sorted(keep)],
    }
    destination.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return destination


def read_registry(path: Path | str | None = None) -> dict[str, Any]:
    destination = Path(path) if path is not None else MODEL_REGISTRY_PATH
    if not destination.exists():
        return {"schema": REGISTRY_SCHEMA, "models": []}
    return json.loads(destination.read_text(encoding="utf-8"))


def registry_entry(
    dataset: str,
    target: str,
    horizon_min: int,
    *,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """The entry of one pair, or a ``KeyError`` naming what is missing."""
    for entry in read_registry(path).get("models", []):
        if (
            str(entry.get("dataset")) == dataset
            and str(entry.get("target")) == target
            and int(entry.get("horizon_min", -1)) == int(horizon_min)
        ):
            return dict(entry)
    raise KeyError(f"no registry entry for {dataset}/{target}/t+{horizon_min}min")


def entry_matches_dataset(entry: Mapping[str, Any], frame: pd.DataFrame) -> bool:
    """Was this model trained on this exact dataset (PRD 13.4 dataset hash)?"""
    return str(entry.get("dataset_hash", "")) == dataset_hash(frame)


def load_horizon_model(
    dataset: str,
    target: str,
    horizon_min: int,
    *,
    registry_path: Path | str | None = None,
    directory: Path | str | None = None,
    config: Config | None = None,
) -> HorizonModel:
    """Rebuild a :class:`HorizonModel` from its artefacts (used by Sections 14, 16 and 19).

    The rebuilt model can predict and label, but it carries no training rows, so a bootstrap
    ensemble that was never persisted cannot be re-fitted here - the uncertainty then falls back to
    the RandomForest tree spread and says so in ``uncertainty_method``.
    """
    import joblib

    entry = registry_entry(dataset, target, horizon_min, path=registry_path)
    folder = dataset_dir(dataset, directory=directory)
    estimators: dict[str, Any] = {}
    spec: FeatureSpec | None = None
    bootstrap: BootstrapEnsemble | None = None

    for family, filename in dict(entry["artifacts"]).items():
        payload = joblib.load(folder / filename)
        if family == BOOTSTRAP_ARTIFACT:
            bootstrap = payload["ensemble"]
        else:
            estimators[family] = payload["estimator"]
        spec = payload["spec"] if spec is None else spec

    if spec is None:  # pragma: no cover - an entry always carries at least one artifact
        raise ValueError(f"registry entry for {dataset}/{target} has no usable artifact")

    return HorizonModel(
        dataset=dataset,
        target=target,
        horizon_min=int(entry["horizon_min"]),
        spec=spec,
        selected_family=str(entry["selected_family"]),
        estimators=estimators,
        hyperparameters=dict(entry.get("hyperparameters", {})),
        selection=dict(entry.get("selection", {})),
        training_domain=dict(entry.get("training_domain", {})),
        model_version=str(entry.get("model_version", "v1")),
        config=config if config is not None else load_config(ML),
        bootstrap=bootstrap,
    )


def load_model_a(
    dataset: str,
    *,
    targets: Sequence[str] | None = None,
    horizons_min: Sequence[int] | None = None,
    registry_path: Path | str | None = None,
    directory: Path | str | None = None,
    config: Config | None = None,
) -> dict[tuple[str, int], HorizonModel]:
    """Every registered pair of one dataset, keyed ``(target, horizon_min)``."""
    models: dict[tuple[str, int], HorizonModel] = {}
    for entry in read_registry(registry_path).get("models", []):
        if str(entry.get("dataset")) != dataset:
            continue
        target = str(entry["target"])
        horizon = int(entry["horizon_min"])
        if targets is not None and target not in set(targets):
            continue
        if horizons_min is not None and horizon not in {int(h) for h in horizons_min}:
            continue
        models[(target, horizon)] = load_horizon_model(
            dataset,
            target,
            horizon,
            registry_path=registry_path,
            directory=directory,
            config=config,
        )
    return models


def registry_summary(path: Path | str | None = None) -> dict[str, Any]:
    """Counts used by the model card and the notebook's "what is registered" cell."""
    entries = read_registry(path).get("models", [])
    families: dict[str, int] = {}
    for entry in entries:
        families[str(entry.get("selected_family"))] = (
            families.get(str(entry.get("selected_family")), 0) + 1
        )
    return {
        "models": len(entries),
        "datasets": sorted({str(entry.get("dataset")) for entry in entries}),
        "horizons_min": sorted({int(entry.get("horizon_min", 0)) for entry in entries}),
        "selected_family_counts": dict(sorted(families.items())),
        "bootstrap_ensembles": sum(
            1 for entry in entries if BOOTSTRAP_ARTIFACT in dict(entry.get("artifacts", {}))
        ),
        "uncertainty_methods": sorted(
            {str(dict(entry.get("uncertainty", {})).get("method")) for entry in entries}
        ),
    }


def _key(entry: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(entry.get("dataset")),
        str(entry.get("target")),
        int(entry.get("horizon_min", 0)),
        str(entry.get("model_version", "v1")),
    )


__all__ = [
    "BOOTSTRAP_ARTIFACT",
    "REGISTRY_SCHEMA",
    "artifact_path",
    "bootstrap_artifact_name",
    "dataset_dir",
    "dataset_hash",
    "entry_matches_dataset",
    "load_horizon_model",
    "load_model_a",
    "metrics_by_pair",
    "read_registry",
    "register_result",
    "registry_entry",
    "registry_summary",
    "save_horizon_model",
    "write_registry",
]
