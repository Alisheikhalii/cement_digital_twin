"""Resumable, persistent orchestration for the notebook's ML-training cell (PRD 25 cell 6).

Why this module exists
----------------------
``train_all`` (in the frozen :mod:`src.models.train`) loops over datasets internally and offers
no callback or checkpoint hook, and the finer-grained (target, horizon) loop lives inside
``ModelATrainer.train`` with no hook either. The frozen layer is never modified, so the
achievable checkpoint granularity is **per dataset** (kiln, mill - two units). That is a
deliberate, accepted scope boundary: this module gets one checkpoint boundary per dataset by
calling the already-public ``train_model_a`` / ``train_model_b`` functions directly - exactly
what ``train_all`` itself calls per dataset - and persisting everything they produce.

What one dataset's checkpoint contains (under the checkpoint root)::

    manifest.json                          per-dataset completion records (atomic replace)
    models/{unit}/*.joblib + registry.json  the PRD 13.4 artifacts (via ``register_result``)
    registry_entries/{unit}.json           that dataset's registry entries, for re-registration
    results/{unit}_model_a.joblib          the full ``ModelAResult`` (models + metric rows)
    results/{unit}_model_b.joblib          the full ``ModelBResult`` (detector + evaluations)

A manifest entry is only written *after* ``train_model_a`` + ``train_model_b`` both returned,
the registry artifacts are confirmed present on disk, and the result objects are persisted -
so an interrupted run never marks an incomplete dataset as complete, and completed datasets are
never retrained. An entry is reused only when its ``dataset_hash`` (PRD 13.4) matches the
current data, the ML-config digest matches, and every recorded artifact still exists.

Where the checkpoint root lives: Google Drive when running on Colab with Drive mounted
(survives Runtime deletion), otherwise the project tree (``checkpoints/training/``) - which on
Colab without Drive is Runtime-local only and is stated as such.

Nothing here changes scientific behaviour: same public functions, same hyperparameters, same
data. The PRD 22 reports are rebuilt from the assembled results (fresh or reused) with the
frozen ``model_a_report`` / ``model_b_report``, and the artifacts are synced to the project's
``models/`` so later cells - which read ``src.paths.MODELS_DIR`` without parameters - see them.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from src.config import ML, Config, load_config
from src.models.registry import dataset_hash, register_result, write_registry
from src.models.train import (
    MODEL_A_METRICS,
    MODEL_B_METRICS,
    TrainingRun,
    model_a_report,
    model_b_report,
    train_model_a,
    train_model_b,
    write_report,
)
from src.paths import MODELS_DIR, PROJECT_ROOT, REPORTS_METRICS_DIR

#: Manifest schema marker, so a future layout change is detected rather than guessed.
MANIFEST_SCHEMA = "cell6-resume/1"

#: Name of the manifest file at the checkpoint root.
MANIFEST_NAME = "manifest.json"

#: Where Drive is mounted on Colab and the checkpoint directory created under MyDrive.
_COLAB_MOUNT_POINT = "/content/drive"
_DRIVE_DIR_NAME = "cement_digital_twin_checkpoints"

#: Checkpoint root when there is no persistent Google Drive: the project tree.
_LOCAL_CHECKPOINT_RELATIVE = Path("checkpoints") / "training"

#: Description strings printed once, so the storage situation is never ambiguous.
_DRIVE_STORAGE = "Google Drive (survives a Colab Runtime disconnect or deletion)"
_RUNTIME_LOCAL_STORAGE = (
    "Runtime-local only (no Google Drive) - a Colab Runtime deletion loses it"
)
_PROJECT_LOCAL_STORAGE = "project-local directory"


# -- where checkpoints live -----------------------------------------------------------------


def _in_colab() -> bool:
    """True when the ``google.colab`` package is importable (i.e. running on Colab)."""
    try:
        return importlib.util.find_spec("google.colab") is not None
    except (ImportError, ModuleNotFoundError, ValueError):  # pragma: no cover - defensive
        return False


def _mount_drive() -> Path | None:
    """Mount Google Drive and return the checkpoint root, or ``None`` if not mounted.

    ``drive.mount`` is interactive on Colab (it shows the authorization prompt this cell's
    markdown mentions). A declined or failed mount returns ``None`` and the caller falls back
    to Runtime-local storage, stating honestly what that means.
    """
    try:
        from google.colab import drive

        drive.mount(_COLAB_MOUNT_POINT)
    except Exception as exc:  # noqa: BLE001 - any mount failure means: no persistence
        print(f"Google Drive not mounted ({exc.__class__.__name__}) - checkpoints will be "
              f"Runtime-local only; a Colab Runtime deletion loses them.")
        return None
    return Path(_COLAB_MOUNT_POINT) / "MyDrive" / _DRIVE_DIR_NAME


def resolve_checkpoint_root() -> tuple[Path, str]:
    """The checkpoint root and a one-line description of what survives.

    Colab + Drive: ``/content/drive/MyDrive/cement_digital_twin_checkpoints`` (mount prompt
    shown). Colab without Drive: Runtime-local, stated as such. Locally: the project tree's
    ``checkpoints/training/``.
    """
    if _in_colab():
        mounted = _mount_drive()
        if mounted is not None:
            return mounted, _DRIVE_STORAGE
        return PROJECT_ROOT / _LOCAL_CHECKPOINT_RELATIVE, _RUNTIME_LOCAL_STORAGE
    return PROJECT_ROOT / _LOCAL_CHECKPOINT_RELATIVE, _PROJECT_LOCAL_STORAGE


# -- manifest --------------------------------------------------------------------------------


def training_config_digest(ml: Config) -> str:
    """Stable SHA-256 over the ML config's own content - no new versioning scheme.

    ``configs/ml.yaml`` is the single source of hyperparameters, split fractions, targets and
    horizons (NFR-4), so hashing what :meth:`Config.to_dict` already exposes identifies the
    training configuration. The scenarios config needs no separate digest: it shapes the
    *data*, and a changed dataset is already caught by the PRD 13.4 ``dataset_hash``.
    """
    payload = json.dumps(ml.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_manifest(root: Path) -> dict[str, Any]:
    """The manifest, or an empty one when absent, unreadable, or of a foreign schema."""
    empty: dict[str, Any] = {"schema": MANIFEST_SCHEMA, "datasets": {}}
    path = root / MANIFEST_NAME
    if not path.is_file():
        return empty
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        return empty
    if not isinstance(manifest.get("datasets"), dict):
        return empty
    return manifest


def _atomic_write_text(path: Path, text: str) -> Path:
    """Write-then-rename, so a reader never sees a half-written file (PRD 13.4 spirit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return path


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    _atomic_write_text(
        root / MANIFEST_NAME, json.dumps(manifest, indent=2, default=str) + "\n"
    )


def _atomic_joblib(path: Path, value: Any) -> Path:
    """Persist an object write-then-rename (the checkpoint's result objects)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    joblib.dump(value, temporary)
    temporary.replace(path)
    return path


def _entry_valid(
    entry: Mapping[str, Any] | None,
    root: Path,
    *,
    dataset_hash_value: str,
    config_digest: str,
) -> bool:
    """Is this manifest entry a reusable checkpoint of *this* dataset?

    Complete status, matching dataset hash (PRD 13.4), matching ML-config digest, and every
    recorded file - registry artifacts, registry entries fragment, result objects - still on
    disk. Anything else means retrain.
    """
    if not isinstance(entry, dict) or entry.get("status") != "complete":
        return False
    if entry.get("dataset_hash") != dataset_hash_value:
        return False
    if entry.get("config_digest") != config_digest:
        return False
    results = entry.get("results")
    fragment = entry.get("registry_entries")
    if not isinstance(results, dict) or not isinstance(fragment, str):
        return False
    for relative in [*entry.get("artifacts", []), *results.values(), fragment]:
        if not (root / str(relative)).is_file():
            return False
    return True


def _sync_models(source: Path, destination: Path) -> None:
    """Copy the checkpoint's registry + artifacts to the project ``models/`` tree.

    Later notebook cells (and ``app.py``) load models through ``src.paths.MODELS_DIR`` without
    parameters, so the artifacts must also exist there - the checkpoint store stays the source
    of truth, this is a plain file copy of it. A no-op when both point at the same directory.
    """
    if not source.is_dir():
        return
    if source.resolve() == destination.resolve():
        return
    shutil.copytree(source, destination, dirs_exist_ok=True)
    print(f"model artifacts synced to {destination}")


# -- the resumable training run ----------------------------------------------------------------


def resumable_training(
    datasets: Mapping[str, pd.DataFrame],
    *,
    truth: Mapping[str, pd.DataFrame] | None = None,
    horizons_min: Sequence[int] | None = None,
    targets: Sequence[str] | None = None,
    simulation: Mapping[str, Any] | None = None,
    config: Config | None = None,
    scenarios: Config | None = None,
    checkpoint_root: Path | str | None = None,
    metrics_dir: Path | str | None = None,
    models_dir: Path | str | None = None,
) -> TrainingRun:
    """Train (or reuse) both models per dataset, with one checkpoint boundary per dataset.

    The same public frozen functions ``train_all`` itself calls - ``train_model_a``,
    ``train_model_b``, ``register_result``, ``write_registry``, ``model_a_report``,
    ``model_b_report`` - just orchestrated one dataset at a time so a completed dataset is
    never retrained after an interruption. Returns the same :class:`TrainingRun`
    ``train_all`` would, whether datasets were freshly trained or reused.
    """
    ml = config if config is not None else load_config(ML)
    if checkpoint_root is None:
        root, storage = resolve_checkpoint_root()
    else:
        root, storage = Path(checkpoint_root), "caller-supplied checkpoint root"
    checkpoint_models = root / "models"
    registry_path = checkpoint_models / "registry.json"
    config_digest = training_config_digest(ml)
    manifest = _read_manifest(root)
    total = len(datasets)

    print("ML TRAINING")
    print(f"Persistent storage: {root}  ({storage})")
    print(f"Datasets: {', '.join(datasets)}")

    # Pass 1 - decide per dataset and say so before any work starts.
    plans: dict[str, tuple[pd.DataFrame, dict[str, Any] | None, str]] = {}
    for name, frame in datasets.items():
        prepared = frame.reset_index(drop=True)
        entry = manifest["datasets"].get(name)
        reusable = _entry_valid(
            entry, root, dataset_hash_value=dataset_hash(prepared), config_digest=config_digest
        )
        if reusable:
            state = "COMPLETE (reusing existing artifacts)"
        elif entry is None:
            state = "not started - training now"
        else:
            state = "checkpoint invalid (hash, config or artifacts changed) - retraining"
        print(f"{name}: {state}")
        plans[name] = (prepared, entry if reusable else None, state)

    # Pass 2 - execute in order; each dataset is marked complete only after its artifacts
    # and result objects are safely on disk.
    a_results: dict[str, Any] = {}
    b_results: dict[str, Any] = {}
    entries: list[dict[str, Any]] = []
    reused = 0
    for position, (name, (prepared, entry, _state)) in enumerate(plans.items(), start=1):
        if entry is not None:
            a_results[name] = joblib.load(root / entry["results"]["model_a"])
            b_results[name] = joblib.load(root / entry["results"]["model_b"])
            entries.extend(json.loads((root / entry["registry_entries"]).read_text(
                encoding="utf-8")))
            reused += 1
            print(f"{name}: reused ({position} of {total} datasets complete)")
            continue

        started = time.perf_counter()
        print(f"{name}: training ({position} of {total} datasets)...")
        truth_frame = None
        if truth is not None and name in truth:
            truth_frame = truth[name].reset_index(drop=True)
        result_a = train_model_a(
            name,
            prepared,
            truth=truth_frame,
            horizons_min=horizons_min,
            targets=targets,
            config=ml,
            scenarios=scenarios,
        )
        result_b = train_model_b(name, prepared, config=ml, scenarios=scenarios)
        a_results[name] = result_a
        b_results[name] = result_b

        # register_result writes the PRD 13.4 joblib artifacts into the checkpoint store.
        dataset_entries = register_result(
            result_a,
            hash_of_dataset=dataset_hash(prepared),
            simulation=simulation,
            directory=checkpoint_models,
        )
        artifacts: list[str] = []
        for registered in dataset_entries:
            folder = checkpoint_models / str(registered["dataset"])
            for filename in dict(registered.get("artifacts", {})).values():
                artifact = folder / str(filename)
                if not artifact.is_file():
                    raise RuntimeError(f"artifact missing after registration: {artifact}")
                artifacts.append(artifact.relative_to(root).as_posix())

        results_block = {
            "model_a": _atomic_joblib(root / "results" / f"{name}_model_a.joblib", result_a)
            .relative_to(root)
            .as_posix(),
            "model_b": _atomic_joblib(root / "results" / f"{name}_model_b.joblib", result_b)
            .relative_to(root)
            .as_posix(),
        }
        fragment = _atomic_write_text(
            root / "registry_entries" / f"{name}.json",
            json.dumps(dataset_entries, indent=2, default=str) + "\n",
        ).relative_to(root).as_posix()

        # Registry and manifest after everything else, so an interruption anywhere above
        # leaves this dataset honestly unrecorded (and retrained next run).
        entries.extend(dataset_entries)
        write_registry(entries, path=registry_path, config=ml)
        manifest["datasets"][name] = {
            "status": "complete",
            "dataset_hash": dataset_hash(prepared),
            "config_digest": config_digest,
            "artifacts": artifacts,
            "registry_entries": fragment,
            "results": results_block,
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write_manifest(root, manifest)
        elapsed = time.perf_counter() - started
        print(f"{name}: done in {elapsed:.0f} s ({position} of {total} datasets complete)")

    print(f"{reused} of {total} datasets reused from checkpoint, {total - reused} trained")

    # The PRD 22 reports are rebuilt from the assembled results (fresh or reused) with the
    # frozen report functions - the exact payload train_all writes for the same inputs.
    reports = {
        "model_a": write_report(
            model_a_report(a_results, config=ml), MODEL_A_METRICS, directory=metrics_dir
        ),
        "model_b": write_report(
            model_b_report(b_results, config=ml), MODEL_B_METRICS, directory=metrics_dir
        ),
    }

    _sync_models(checkpoint_models, Path(models_dir) if models_dir is not None else MODELS_DIR)

    return TrainingRun(model_a=a_results, model_b=b_results, reports=reports,
                       registry=registry_path)


__all__ = [
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA",
    "resolve_checkpoint_root",
    "resumable_training",
    "training_config_digest",
]
