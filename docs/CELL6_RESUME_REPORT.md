# Cell 6 resumable ML training — implementation report

**Wave:** Cell 6 resume/persistence (2026-09-05). Starting HEAD `f585b50` (the PRD §25 notebook
wave). One commit; see `git log` for its hash.

**Objective (three bullets, all met):** make PRD §25 cell 6 show real progress, make it
resumable after a Colab Runtime disconnect/reconnect without touching any frozen-layer file,
and persist checkpoints to Google Drive in Colab so a Runtime deletion doesn't lose completed
work.

---

## 1. Scope boundary — per dataset, deliberately

`train_all` (`src/models/train.py`) loops over datasets with no callback parameter, and the
finer-grained (target, horizon) loop lives inside `ModelATrainer.train()` in the frozen file
with no hook. The frozen layer stays untouched, so the achievable checkpoint granularity is
**per dataset (kiln, mill — two units)**. The notebook now calls the already-public
`train_model_a` / `train_model_b` directly in its own loop — the same functions `train_all`
itself calls per dataset — so a completed dataset is never retrained after an interruption.
Finer-than-dataset granularity would require a frozen-layer exception (see §7).

## 2. What was added

| File | What |
|---|---|
| `src/notebook_support.py` (new, non-frozen) | `resumable_training()` + manifest/artifact/registry/checkpoint logic; `resolve_checkpoint_root()` (Colab Drive vs local); `training_config_digest()`. Imports only public frozen API (`train_model_a`, `train_model_b`, `register_result`, `write_registry`, `model_a_report`, `model_b_report`, `write_report`, `dataset_hash`, `TrainingRun`, report filenames). |
| `notebooks/00_cement_digital_twin_demo.ipynb` | Cell 6 code calls `resumable_training(...)`; markdown rewritten to state the resumability, the Drive requirement, and the honest no-Drive limit. |
| `tests/test_task6_cell6_resume.py` (new) | 11 tests, A–G of the wave directive plus storage-selection tests. |
| `docs/CELL6_RESUME_REPORT.md`, `docs/PROJECT_STATE.md` | this report and the state facts. |
| `.gitignore` | `checkpoints/` excluded (regenerable artifacts + manifest; on Colab they live on Drive). |

Nothing under `src/models/`, `src/process_models/`, `src/optimization/`, `src/simulation/`,
`src/features/`, `src/data_generation/`, `configs/`, `pyproject.toml` was touched — verified by
digest before and after (§6).

## 3. Design

**Checkpoint store.** On Colab with Google Drive mounted:
`/content/drive/MyDrive/cement_digital_twin_checkpoints/` (the mount authorization prompt
appears in cell 6; a declined mount falls back to Runtime-local and says so). Not on Colab:
`checkpoints/training/` in the project tree. Contents:

```
manifest.json                          per-dataset completion records (atomic write-then-rename)
models/{unit}/*.joblib + registry.json the PRD 13.4 artifacts, written by the frozen register_result
registry_entries/{unit}.json           that dataset's registry entries, for re-registration
results/{unit}_model_a.joblib          the full ModelAResult (models + metric rows)
results/{unit}_model_b.joblib          the full ModelBResult (detector + evaluations)
```

**Manifest entry** (per dataset): `status`, PRD 13.4 `dataset_hash` (from
`src.models.registry.dataset_hash` — a changed dataset invalidates the entry), a SHA-256
digest of `configs/ml.yaml` via `Config.to_dict()` (no new versioning scheme — the ML config
is hyperparameters/splits/targets/horizons; the scenarios config shapes the *data* and is
already covered by the dataset hash), the artifact file list, the registry-entries fragment
path, the two result-object paths, and a UTC completion timestamp.

**Ordering.** A dataset's manifest entry is written only after `train_model_a` +
`train_model_b` both returned, every registered artifact is confirmed present on disk, the
result objects are persisted (write-then-rename), and the registry fragment is written. An
interruption anywhere before that leaves the dataset unrecorded and it retrains next run;
completed datasets are never retrained.

**Reuse.** An entry counts only when status is complete, the dataset hash and config digest
match, and every recorded file still exists (missing artifact ⇒ retrain, even if the manifest
says complete). Reused datasets contribute by loading their checkpointed `ModelAResult` /
`ModelBResult` and re-applying their registry entries; the PRD 22 metric reports are rebuilt
from the assembled results with the frozen report builders — the exact payload `train_all`
writes for the same inputs, so `TrainingRun` / `training_summary` (what cells 7+ consume,
including cell 7 reading `reports/metrics/` and cell 8's `build_model_layer` reading
`models/`) see the same shape fresh or reused.

**Sync.** After training, the checkpoint's `models/` tree is copied to the project's
`src.paths.MODELS_DIR` (no-op when they coincide), because later cells load models through
the unparameterized default.

**Progress.** The cell prints a recovery summary before any work (`ML TRAINING` / persistent
storage + what it means / per-dataset plan: `COMPLETE (reusing existing artifacts)`,
`not started — training now`, or `checkpoint invalid (hash, config or artifacts changed) —
retraining`), then per dataset start / elapsed / `n of 2 datasets complete`. No ETA, no
fabricated sub-dataset percentages — there are 2 units, and the output says so.

## 4. Tests (`tests/test_task6_cell6_resume.py`, 11 tests)

Fast deterministic stand-ins for `train_model_a` / `train_model_b` / `register_result`
(monkeypatched **in the `src.notebook_support` namespace** where they were imported; the fake
`register_result` writes real artifact files so the on-disk validity checks run for real) —
everything else (hash, registry, reports, summary) is frozen code under test. Behavioural,
not string-existence:

- **A** first run trains both, writes a complete manifest, PRD 22 reports, synced artifacts;
- **B** valid manifest ⇒ zero training calls, registry still carries both datasets;
- **C** a changed dataset (one edited value ⇒ different PRD 13.4 hash) retrains **only** it;
- **D** missing artifact (or result object) invalidates an entry the manifest calls complete;
- **E** `KeyboardInterrupt` while training dataset 2: kiln recorded + reused, mill unrecorded
  + trained on the next run;
- **F** `TrainingRun` type, `training_summary` output and result-object classes identical
  fresh vs reused;
- **G** import-graph guard: every frozen import is in that module's `__all__`, and
  `src.models.model_a` (the trainer's module) is never imported — the import-graph form of
  the digest check;
- storage selection: local / Colab-without-Drive (described as Runtime-local) /
  Colab-with-Drive (described as surviving deletion).

## 5. Validation performed — local and real, not on Colab

A controlled execution with the **real** frozen functions (not the test fakes) on the standard
short ML fixture (3-day run, 4 320 rows, full configured target/horizon set) in a temp
directory: (1) fresh run trains both datasets (kiln 273 s, mill 110 s — 16 + 12 Model A pairs,
the same pair counts as the full run) and writes the manifest, PRD 22 reports and synced
artifacts; (2) a `KeyboardInterrupt` raised inside the real `train_model_b` while the second
dataset trains leaves dataset 1 complete and dataset 2 unrecorded; (3) the resume run trains
only dataset 2 (113 s vs the fresh run's 385 s) and produces a `training_summary` identical
to the fresh run's; (4) a pure-reuse run trains nothing (9 s: reports + sync only).
**What was NOT verified: an execution on Google Colab itself, and a real Drive mount —
impossible from this environment, and claimed nowhere.** The Drive path is exercised only by
the monkeypatched storage-selection tests.

## 6. Frozen layer

`git ls-files -s` digest over the frozen paths, before and after this wave:

```
c7a1f54dd578900835596c02cb9a19a0   (before)
c7a1f54dd578900835596c02cb9a19a0   (after)  — byte-identical
53f2aefec33494be5ca22c08ab22b5fd   legacy tests, before and after — byte-identical
```

## 7. Remaining gaps

- **Finer-than-dataset granularity** (per target/horizon/model family, 28 units): out of
  scope by directive; would need a callback hook inside the frozen `ModelATrainer`, i.e. an
  explicit frozen-layer exception decision. Recorded as **P2/future**.
- **Sub-dataset progress/ETA** is honestly unavailable for the same reason — the cell reports
  "n of 2 datasets" only.
- **Colab/Drive execution** unverified from this environment (§5); the first real Colab run
  should confirm the Drive mount flow end to end.
- The metrics reports are rebuilt (not checkpointed byte-for-byte): identical for identical
  inputs, and `written_at` is a fresh timestamp — same behaviour `train_all` has.
