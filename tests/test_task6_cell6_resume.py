"""Task #6 — Cell 6 resumable training: reuse-vs-retrain behaviour, proven not asserted.

What this module pins
---------------------
``src/notebook_support.resumable_training`` gives PRD §25 cell 6 one checkpoint boundary per
dataset (kiln / mill — the accepted scope boundary: the finer (target, horizon) loop lives
inside the frozen ``ModelATrainer`` and is not reachable without a frozen-layer change). These
tests exercise the real manifest / artifact / registry logic with fast stand-in training
functions — no real 30-minute run — and verify *behaviour* (which datasets were retrained vs
reused, what survived an interruption), never just that a file exists:

- A: first run trains every dataset and writes a complete manifest;
- B: a valid, hash-matching manifest reuses every dataset (zero training calls);
- C: a dataset-hash mismatch invalidates that dataset's entry only;
- D: a missing artifact (or result object) invalidates an entry the manifest calls complete;
- E: an interruption after dataset 1 leaves dataset 1 reusable and dataset 2 unrecorded;
- F: the reconstructed ``TrainingRun``/summary has the same shape fresh vs reused;
- G: only the frozen layer's *public* API is imported — nothing requires a frozen change.

The stand-ins monkeypatch ``train_model_a`` / ``train_model_b`` / ``register_result`` **in the
``src.notebook_support`` namespace** (where they were imported), and the fake
``register_result`` writes real artifact files, so the on-disk validity checks run for real.
Everything else — ``dataset_hash``, ``write_registry``, the PRD 22 report builders,
``training_summary`` — is the frozen code under test.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import src.notebook_support as support
from src.models.train import TrainingRun, training_summary

#: Two datasets with different values, so their PRD 13.4 dataset hashes differ.
FRAMES = {
    "kiln": pd.DataFrame({"value": [1.0, 2.0, 3.0, 4.0], "regime": ["NORMAL"] * 4}),
    "mill": pd.DataFrame({"value": [9.0, 8.0, 7.0, 6.0], "regime": ["NORMAL"] * 4}),
}


# -- stand-in training results (picklable, satisfying the report builders' shape) ------------


class FakeAResult:
    """The subset of ``ModelAResult`` the report/summary path actually reads."""

    def __init__(self, dataset: str) -> None:
        self.dataset = dataset
        self.models: dict[tuple[str, int], Any] = {}
        self.metric_rows: tuple[dict[str, Any], ...] = ()
        self.targets: tuple[str, ...] = ()
        self.horizons_min: tuple[int, ...] = ()
        self.splits: dict[int, Any] = {}
        self.matrices: dict[int, Any] = {}

    def describe(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "pairs": len(self.models)}


class FakeBResult:
    """The subset of ``ModelBResult`` the report/summary path actually reads."""

    def __init__(self, dataset: str) -> None:
        self.dataset = dataset
        self.evaluations: dict[str, Any] = {"all_rows": object()}

    def describe(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "splits": sorted(self.evaluations)}


def _fake_register_result(
    result: Any,
    *,
    hash_of_dataset: str,
    simulation: Any = None,
    directory: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Write real artifact files and return registry entries shaped like the real ones."""
    folder = Path(directory) / result.dataset
    folder.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for family in ("random_forest", "gradient_boosting"):
        filename = f"model_temp_t+5min_v1_{family}.joblib"
        (folder / filename).write_bytes(b"fake-artifact")
        artifacts[family] = filename
    return [
        {
            "schema": "model_a/1",
            "dataset": result.dataset,
            "target": "temp",
            "horizon_min": 5,
            "horizon": "t+5min",
            "unit": result.dataset,
            "model_version": "v1",
            "selected_family": "random_forest",
            "dataset_hash": hash_of_dataset,
            "simulation_config": dict(simulation or {}),
            "artifacts": artifacts,
            "hyperparameters": {},
            "uncertainty": {"method": "none"},
        }
    ]


@pytest.fixture
def trained_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch the frozen calls used by ``resumable_training`` and record dataset order."""
    calls: list[str] = []

    def fake_train_model_a(dataset, frame, **kwargs):
        calls.append(f"a:{dataset}")
        return FakeAResult(dataset)

    def fake_train_model_b(dataset, frame, **kwargs):
        calls.append(f"b:{dataset}")
        return FakeBResult(dataset)

    monkeypatch.setattr(support, "train_model_a", fake_train_model_a)
    monkeypatch.setattr(support, "train_model_b", fake_train_model_b)
    monkeypatch.setattr(support, "register_result", _fake_register_result)
    return calls


def _run(
    root: Path, frames: dict[str, pd.DataFrame] | None = None, **kwargs: Any
) -> TrainingRun:
    """One resumable run with checkpoint, metrics and synced models all inside tmp_path."""
    return support.resumable_training(
        frames if frames is not None else FRAMES,
        simulation={"seed": 42},
        checkpoint_root=root,
        metrics_dir=root.parent / "metrics",
        models_dir=root.parent / "models",
        **kwargs,
    )


def _manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / support.MANIFEST_NAME).read_text(encoding="utf-8"))


# -- A: first run trains everything and records it ---------------------------------------------


def test_a_first_run_trains_both_and_writes_complete_manifest(
    tmp_path: Path, trained_calls: list[str]
) -> None:
    root = tmp_path / "ckpt"
    run = _run(root)

    assert trained_calls == ["a:kiln", "b:kiln", "a:mill", "b:mill"]
    manifest = _manifest(root)
    for name in FRAMES:
        entry = manifest["datasets"][name]
        assert entry["status"] == "complete"
        assert entry["artifacts"], "entry must record its artifact files"
        assert (root / entry["registry_entries"]).is_file()
        for relative in entry["results"].values():
            assert (root / relative).is_file()
    assert isinstance(run, TrainingRun)
    assert sorted(run.model_a) == sorted(FRAMES)
    assert (root / "models" / "registry.json").is_file()
    # The PRD 22 reports exist and the artifacts were synced where later cells read them.
    assert (tmp_path / "metrics" / "model_a_horizon_metrics.json").is_file()
    assert (tmp_path / "metrics" / "model_b_metrics.json").is_file()
    assert (tmp_path / "models" / "kiln").is_dir() and (tmp_path / "models" / "mill").is_dir()


# -- B: a valid manifest reuses everything -------------------------------------------------------


def test_b_second_run_reuses_both_without_training(
    tmp_path: Path, trained_calls: list[str]
) -> None:
    root = tmp_path / "ckpt"
    _run(root)
    trained_calls.clear()

    run = _run(root)
    assert trained_calls == [], "a valid, hash-matching manifest must train nothing"
    assert sorted(run.model_a) == sorted(FRAMES)
    assert sorted(run.model_b) == sorted(FRAMES)
    registry = json.loads((root / "models" / "registry.json").read_text(encoding="utf-8"))
    assert sorted({entry["dataset"] for entry in registry["models"]}) == sorted(FRAMES)


# -- C: a dataset hash mismatch invalidates only that dataset -----------------------------------


def test_c_hash_mismatch_invalidates_only_that_dataset(
    tmp_path: Path, trained_calls: list[str]
) -> None:
    root = tmp_path / "ckpt"
    _run(root)
    trained_calls.clear()

    changed = {**FRAMES, "kiln": FRAMES["kiln"].copy()}
    changed["kiln"].loc[0, "value"] = 99.0  # a different dataset -> a different PRD 13.4 hash
    _run(root, changed)

    assert trained_calls == ["a:kiln", "b:kiln"], "only the changed dataset retrains"
    assert _manifest(root)["datasets"]["mill"]["status"] == "complete"


# -- D: missing artifacts invalidate an entry the manifest calls complete -----------------------


def test_d_missing_artifact_invalidates_entry(
    tmp_path: Path, trained_calls: list[str]
) -> None:
    root = tmp_path / "ckpt"
    _run(root)
    trained_calls.clear()

    for artifact in (root / "models" / "kiln").glob("*.joblib"):
        artifact.unlink()
    assert _manifest(root)["datasets"]["kiln"]["status"] == "complete"  # manifest still says so
    _run(root)

    assert trained_calls == ["a:kiln", "b:kiln"], "missing artifacts must force a retrain"
    assert trained_calls.count("a:mill") == 0, "mill stays reusable"


def test_d_missing_result_object_invalidates_entry(
    tmp_path: Path, trained_calls: list[str]
) -> None:
    root = tmp_path / "ckpt"
    _run(root)
    trained_calls.clear()

    (root / "results" / "kiln_model_a.joblib").unlink()
    _run(root)
    assert trained_calls == ["a:kiln", "b:kiln"]


# -- E: an interruption between datasets ---------------------------------------------------------


def test_e_interruption_keeps_completed_dataset_reusable(
    tmp_path: Path, trained_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ckpt"

    # First run dies while training the *second* dataset, after the first completed.
    def dying_train_model_b(dataset, frame, **kwargs):
        trained_calls.append(f"b:{dataset}")
        if dataset == "mill":
            raise KeyboardInterrupt("simulated Colab Runtime death")
        return FakeBResult(dataset)

    monkeypatch.setattr(support, "train_model_b", dying_train_model_b)
    with pytest.raises(KeyboardInterrupt):
        _run(root)

    manifest = _manifest(root)
    assert manifest["datasets"]["kiln"]["status"] == "complete"
    assert "mill" not in manifest["datasets"], "an interrupted dataset must not be recorded"

    # Next run: kiln reused, mill trained.
    monkeypatch.setattr(
        support,
        "train_model_b",
        lambda dataset, frame, **kwargs: (
            trained_calls.append(f"b:{dataset}"),
            FakeBResult(dataset),
        )[1],
    )
    trained_calls.clear()
    run = _run(root)
    assert trained_calls == ["a:mill", "b:mill"], "kiln must be reused, not retrained"
    assert sorted(run.model_a) == sorted(FRAMES)
    assert _manifest(root)["datasets"]["mill"]["status"] == "complete"


# -- F: same shape whether freshly trained or reused ----------------------------------------------


def test_f_training_run_shape_identical_fresh_vs_reused(
    tmp_path: Path, trained_calls: list[str]
) -> None:
    root = tmp_path / "ckpt"
    fresh, fresh_summary = _run(root), None
    fresh_summary = training_summary(fresh)
    trained_calls.clear()

    reused = _run(root)
    reused_summary = training_summary(reused)

    assert trained_calls == []
    assert type(reused) is type(fresh) is TrainingRun
    assert reused_summary == fresh_summary, "downstream cells must see the same object shape"
    assert reused.model_a["kiln"].dataset == fresh.model_a["kiln"].dataset
    assert reused.model_b["kiln"].evaluations.keys() == fresh.model_b["kiln"].evaluations.keys()
    # Reuse really round-tripped the checkpointed result objects.
    assert reused.model_a["kiln"].__class__ is FakeAResult
    assert reused.model_b["kiln"].__class__ is FakeBResult


# -- G: the frozen layer is used through its public API only --------------------------------------


def test_g_only_public_frozen_api_is_imported() -> None:
    """Every name imported from a frozen module must be in that module's ``__all__``.

    A private-name import is the leading indicator of "needs a frozen change to work" —
    this is the import-graph form of the digest check, not a substitute for it.
    """
    import src.models.registry as registry
    import src.models.train as train

    public: dict[str, set[str]] = {
        "src.models.train": set(train.__all__),
        "src.models.registry": set(registry.__all__),
    }
    source = Path(support.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            # Public frozen modules: every imported name must be exported API.
            if node.module in public:
                for alias in node.names:
                    assert alias.name in public[node.module], (
                        f"private frozen import: {node.module}.{alias.name}"
                    )
            # Reaching inside the trainer (for finer-than-dataset progress) is off-limits.
            assert node.module != "src.models.model_a", (
                "cell 6 must not import ModelATrainer's module — per-dataset is the boundary"
            )


# -- storage selection: Drive vs local ------------------------------------------------------------


def test_storage_selection_local(tmp_path: Path) -> None:
    """Not on Colab: the project-local checkpoint directory, described honestly."""
    root, description = support.resolve_checkpoint_root()
    assert root == support.PROJECT_ROOT / "checkpoints" / "training"
    assert description == "project-local directory"


def test_storage_selection_colab_without_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On Colab with the Drive mount declined: Runtime-local, and *stated* as Runtime-local."""
    monkeypatch.setattr(support, "_in_colab", lambda: True)
    monkeypatch.setattr(support, "_mount_drive", lambda: None)
    root, description = support.resolve_checkpoint_root()
    assert "Runtime" in description


def test_storage_selection_colab_with_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Colab with Drive mounted: the Drive directory, described as surviving deletion."""
    monkeypatch.setattr(support, "_in_colab", lambda: True)
    drive_root = Path("/content/drive/MyDrive/cement_digital_twin_checkpoints")
    monkeypatch.setattr(support, "_mount_drive", lambda: drive_root)
    root, description = support.resolve_checkpoint_root()
    assert root == drive_root
    assert "Google Drive" in description
