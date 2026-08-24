"""Writing a :class:`~src.data_generation.generator.GeneratedRun` to disk (PRD v1.1.1 11.6).

PRD 11.6 asks for three artefacts per generated dataset: CSV, Parquet and *"a JSON sidecar of
the config used, saved alongside every generated dataset"*. This module is the only place in
the project that touches the filesystem for generated data; the generator itself stays a pure
function of the configs and the seed so it can be exercised without a writable directory.

Two conventions worth stating, because they are what make a re-run comparable to the run before
it (NFR-4):

* **The sidecar carries no wall-clock.** It is ``run.sidecar(dataset)`` verbatim - the config
  actually used, the seed, the schedule summary, the sensor outcome - so two runs of the same
  seed produce byte-identical sidecars and a regression test can diff them.
* **Ground truth is a separate file, never an extra column.** PRD 12.1/12.2's column tables end
  at ``injected_fault``; the noise-free state, the PRD 9.5 health scalar and the unmeasured
  disturbances go to ``*_truth.*`` beside the dataset (PRD 34 item 2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping

import pandas as pd

from src import paths
from src.config import ConfigError
from src.data_generation.generator import DATASETS, GeneratedRun
from src.schema import DatasetName

#: File stem of each exported dataset (PRD 11.6 writes into ``data/synthetic/``).
DATASET_STEMS: Final[Mapping[DatasetName, str]] = {
    "kiln": paths.KILN_DATASET_STEM,
    "mill": paths.MILL_DATASET_STEM,
}

#: File stem of each dataset's ground-truth companion.
TRUTH_STEMS: Final[Mapping[DatasetName, str]] = {
    "kiln": paths.KILN_TRUTH_STEM,
    "mill": paths.MILL_TRUTH_STEM,
}

#: Timestamp format used by the CSV writer: ISO-8601, UTC, whole seconds (PRD 11.2 is 1 min).
CSV_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%S%z"

#: ``float_format`` of the CSV writer. ASSUMPTION: 6 significant digits is far finer than any
#: quantization step in PRD 11.5, so the CSV cannot lose a measured number, while keeping the
#: file free of 17-digit binary-rounding noise that would make two equal runs *look* different.
CSV_FLOAT_FORMAT: Final = "%.6g"


# =============================================================================
# What one export produced
# =============================================================================
@dataclass(frozen=True, slots=True)
class ExportManifest:
    """Paths written by one :func:`export_run`, grouped the way PRD 11.6 lists them."""

    directory: Path
    datasets: Mapping[DatasetName, tuple[Path, ...]] = field(default_factory=dict)
    truth: Mapping[DatasetName, tuple[Path, ...]] = field(default_factory=dict)
    sidecars: Mapping[DatasetName, Path] = field(default_factory=dict)

    @property
    def files(self) -> tuple[Path, ...]:
        """Every path this export wrote, in a deterministic order."""
        written: list[Path] = []
        for dataset in DATASETS:
            written.extend(self.datasets.get(dataset, ()))
            written.extend(self.truth.get(dataset, ()))
            sidecar = self.sidecars.get(dataset)
            if sidecar is not None:
                written.append(sidecar)
        return tuple(written)

    def describe(self) -> dict[str, Any]:
        """JSON-serializable summary (relative to ``directory``, so it stays machine-portable)."""
        return {
            "directory": str(self.directory),
            "files": [path.name for path in self.files],
        }


# =============================================================================
# Writing one frame
# =============================================================================
def _write_frame(frame: pd.DataFrame, stem: str, directory: Path, csv: bool, parquet: bool) -> tuple[Path, ...]:
    """Write one frame in the requested formats and return the paths, CSV first."""
    written: list[Path] = []
    if csv:
        target = directory / f"{stem}.csv"
        frame.to_csv(
            target,
            index=False,
            date_format=CSV_TIMESTAMP_FORMAT,
            float_format=CSV_FLOAT_FORMAT,
        )
        written.append(target)
    if parquet:
        target = directory / f"{stem}.parquet"
        try:
            frame.to_parquet(target, index=False)
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise ConfigError(
                "Parquet export (PRD 11.6) needs pyarrow; install it or run with "
                "export_parquet=false in configs/scenarios.yaml"
            ) from error
        written.append(target)
    return tuple(written)


def _write_sidecar(payload: Mapping[str, Any], stem: str, directory: Path) -> Path:
    """Write one dataset's JSON sidecar (PRD 11.6). Sorted keys: two runs diff cleanly."""
    target = directory / f"{stem}.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return target


# =============================================================================
# The export (PRD 11.6)
# =============================================================================
def export_run(
    run: GeneratedRun,
    directory: Path | str | None = None,
    *,
    csv: bool | None = None,
    parquet: bool | None = None,
    sidecar: bool | None = None,
) -> ExportManifest:
    """Write both datasets, their ground truth and their sidecars (PRD 11.6).

    The three format switches default to the ``SimulationConfig`` flags the run was generated
    with (``export_csv`` / ``export_parquet`` / ``export_config_sidecar``), so the config
    decides what a run produces and the keyword arguments exist for tests and the notebook.
    """
    simulation = run.simulation
    want_csv = simulation.export_csv if csv is None else bool(csv)
    want_parquet = simulation.export_parquet if parquet is None else bool(parquet)
    want_sidecar = simulation.export_config_sidecar if sidecar is None else bool(sidecar)
    if not (want_csv or want_parquet or want_sidecar):
        raise ConfigError(
            "nothing to export: CSV, Parquet and the config sidecar are all switched off "
            "(PRD 11.6 asks for all three)"
        )
    target = Path(directory) if directory is not None else paths.DATA_SYNTHETIC_DIR
    target.mkdir(parents=True, exist_ok=True)

    datasets: dict[DatasetName, tuple[Path, ...]] = {}
    truth: dict[DatasetName, tuple[Path, ...]] = {}
    sidecars: dict[DatasetName, Path] = {}
    for dataset in DATASETS:
        datasets[dataset] = _write_frame(
            run.datasets[dataset], DATASET_STEMS[dataset], target, want_csv, want_parquet
        )
        truth[dataset] = _write_frame(
            run.truth[dataset], TRUTH_STEMS[dataset], target, want_csv, want_parquet
        )
        if want_sidecar:
            sidecars[dataset] = _write_sidecar(
                run.sidecar(dataset), DATASET_STEMS[dataset], target
            )
    return ExportManifest(directory=target, datasets=datasets, truth=truth, sidecars=sidecars)


def load_dataset(
    dataset: DatasetName, directory: Path | str | None = None, *, suffix: str = "parquet"
) -> pd.DataFrame:
    """Read back one exported dataset (used by the tests and by PRD 26's DataProvider)."""
    return _read(DATASET_STEMS, dataset, directory, suffix)


def load_truth(
    dataset: DatasetName, directory: Path | str | None = None, *, suffix: str = "parquet"
) -> pd.DataFrame:
    """Read back one exported ground-truth frame."""
    return _read(TRUTH_STEMS, dataset, directory, suffix)


def _read(
    stems: Mapping[DatasetName, str],
    dataset: DatasetName,
    directory: Path | str | None,
    suffix: str,
) -> pd.DataFrame:
    if dataset not in stems:
        raise ConfigError(f"unknown dataset {dataset!r}; expected one of {list(DATASETS)}")
    base = Path(directory) if directory is not None else paths.DATA_SYNTHETIC_DIR
    kind = suffix.lstrip(".").lower()
    path = base / f"{stems[dataset]}.{kind}"
    if not path.exists():
        raise ConfigError(f"no export at {path}; run the generator first (PRD 11.6)")
    if kind == "parquet":
        return pd.read_parquet(path)
    if kind == "csv":
        return pd.read_csv(path, parse_dates=["timestamp"])
    raise ConfigError(f"unsupported export format {suffix!r}; expected 'csv' or 'parquet'")


def load_sidecar(dataset: DatasetName, directory: Path | str | None = None) -> dict[str, Any]:
    """Read back one dataset's JSON sidecar (PRD 11.6 provenance)."""
    if dataset not in DATASET_STEMS:
        raise ConfigError(f"unknown dataset {dataset!r}; expected one of {list(DATASETS)}")
    base = Path(directory) if directory is not None else paths.DATA_SYNTHETIC_DIR
    path = base / f"{DATASET_STEMS[dataset]}.json"
    if not path.exists():
        raise ConfigError(f"no sidecar at {path}; run the generator first (PRD 11.6)")
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "CSV_FLOAT_FORMAT",
    "CSV_TIMESTAMP_FORMAT",
    "DATASET_STEMS",
    "TRUTH_STEMS",
    "ExportManifest",
    "export_run",
    "load_dataset",
    "load_sidecar",
    "load_truth",
]
