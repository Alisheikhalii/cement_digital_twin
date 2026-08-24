"""Filesystem layout of the project (PRD v1.1.1 Section 23).

Every module resolves paths through this one place, so the notebook (Colab, where the
repository is cloned into an arbitrary directory) and the local/standalone runtime behave
identically. No module may hard-code a relative path.
"""

from __future__ import annotations

from pathlib import Path

# ``src/paths.py`` -> ``src`` -> project root.
SRC_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = SRC_DIR.parent

CONFIG_DIR: Path = PROJECT_ROOT / "configs"
NOTEBOOKS_DIR: Path = PROJECT_ROOT / "notebooks"
DOCS_DIR: Path = PROJECT_ROOT / "docs"
TESTS_DIR: Path = PROJECT_ROOT / "tests"

DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_RAW_DIR: Path = DATA_DIR / "raw"                # untouched synthetic exports
DATA_PROCESSED_DIR: Path = DATA_DIR / "processed"    # cleaned / validated
DATA_SYNTHETIC_DIR: Path = DATA_DIR / "synthetic"    # generator outputs + config sidecars

MODELS_DIR: Path = PROJECT_ROOT / "models"           # joblib artifacts + registry.json
MODEL_REGISTRY_PATH: Path = MODELS_DIR / "registry.json"   # PRD 13.4

REPORTS_DIR: Path = PROJECT_ROOT / "reports"
REPORTS_METRICS_DIR: Path = REPORTS_DIR / "metrics"          # PRD 22
REPORTS_DATA_QUALITY_DIR: Path = REPORTS_DIR / "data_quality"
REPORTS_EXPERIMENTS_DIR: Path = REPORTS_DIR / "experiments"  # PRD 13.4

# PRD 35 documentation deliverables that are *generated* rather than hand-written, and so need a
# canonical path. MODEL_CARD.md is regenerated from the artefacts of a training run, which is the
# only way its metric tables can be guaranteed to match ``reports/metrics/*.json``.
MODEL_CARD_PATH: Path = PROJECT_ROOT / "MODEL_CARD.md"

# Canonical dataset file stems (PRD 11.2 / 12).
KILN_DATASET_STEM = "kiln_raw"
MILL_DATASET_STEM = "mill_raw"

# Ground-truth companions of the two datasets. PRD 12.1/12.2's column tables end at
# ``injected_fault``, so the noise-free state, the equipment-health scalar and the unmeasured
# disturbances are exported *beside* each dataset rather than inside it (PRD 34 item 2: models
# are evaluated against the simulator's own true state, not just the noisy measurement).
KILN_TRUTH_STEM = "kiln_truth"
MILL_TRUTH_STEM = "mill_truth"

#: Directories that are created on demand (data/model/report outputs only - never configs).
_WRITABLE_DIRS: tuple[Path, ...] = (
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR,
    DATA_SYNTHETIC_DIR,
    MODELS_DIR,
    REPORTS_METRICS_DIR,
    REPORTS_DATA_QUALITY_DIR,
    REPORTS_EXPERIMENTS_DIR,
)


def ensure_dirs() -> None:
    """Create the output directory tree if it does not exist yet (idempotent)."""
    for directory in _WRITABLE_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def config_path(name: str) -> Path:
    """Return the path of a config file in :data:`CONFIG_DIR`.

    ``name`` may be given with or without the ``.yaml`` suffix.
    """
    filename = name if name.endswith((".yaml", ".yml", ".json")) else f"{name}.yaml"
    return CONFIG_DIR / filename


def synthetic_dataset_path(stem: str, suffix: str = "parquet") -> Path:
    """Path of a generated dataset export, e.g. ``kiln_raw`` + ``parquet`` (PRD 11.6)."""
    return DATA_SYNTHETIC_DIR / f"{stem}.{suffix.lstrip('.')}"


__all__ = [
    "PROJECT_ROOT",
    "SRC_DIR",
    "CONFIG_DIR",
    "NOTEBOOKS_DIR",
    "DOCS_DIR",
    "TESTS_DIR",
    "DATA_DIR",
    "DATA_RAW_DIR",
    "DATA_PROCESSED_DIR",
    "DATA_SYNTHETIC_DIR",
    "MODELS_DIR",
    "MODEL_CARD_PATH",
    "MODEL_REGISTRY_PATH",
    "REPORTS_DIR",
    "REPORTS_METRICS_DIR",
    "REPORTS_DATA_QUALITY_DIR",
    "REPORTS_EXPERIMENTS_DIR",
    "KILN_DATASET_STEM",
    "MILL_DATASET_STEM",
    "KILN_TRUTH_STEM",
    "MILL_TRUTH_STEM",
    "ensure_dirs",
    "config_path",
    "synthetic_dataset_path",
]
