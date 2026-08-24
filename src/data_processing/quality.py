"""FR-13 data-quality report: what a historian extract would be audited for.

PRD v1.1.1 FR-13 asks for a report covering *"missing values, duplicates, constant sensors,
spikes, drift, sync issues"*, surfaced as dashboard view 9 (PRD 17) and re-run unchanged on the
factory's real data during the Section 21 transfer (**"Data Quality Assessment - Section
11.5-equivalent checks re-run on real data"**). That second consumer is the reason this module
knows nothing about the simulator: it takes a frame and a timestamp column, and every threshold
is a module-level ``ASSUMPTION`` constant that a plant-specific config can override.

On synthetic data the report is *expected* to fire. PRD 11.5 deliberately injects dropouts,
stuck sensors, quantization and (in regime 14) a drifting bias, so a clean report on a generated
dataset would mean the sensor model was not running. The report therefore describes and counts;
it never repairs, and it never fails a run - :mod:`src.data_processing` cleaning is a separate
concern (PRD 23).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import numpy as np
import pandas as pd

from src import paths, schema
from src.config import ConfigError

# =============================================================================
# Thresholds (every one an ASSUMPTION; documented in SIMULATION_ASSUMPTIONS.md)
# =============================================================================
#: Missing-value fraction per column above which the finding is a warning / an error.
MISSING_WARN_FRACTION: Final = 0.005
MISSING_ERROR_FRACTION: Final = 0.05

#: A column whose full range is this small relative to its own scale counts as a dead sensor.
CONSTANT_RELATIVE_RANGE: Final = 1e-9

#: Consecutive identical samples that count as a frozen ("stuck") sensor. At the PRD 11.2
#: 1-minute sampling interval this is 30 minutes of a perfectly unchanging reading, which no
#: noisy analogue instrument produces - but a quantized integer tag legitimately can, so the
#: check reports the run length and leaves the interpretation to the reader.
STUCK_MIN_RUN: Final = 30

#: Robust z-score (median absolute deviation of the first difference) above which a one-sample
#: excursion counts as a spike. 8 sigma_MAD is far outside the PRD 11.5 Gaussian noise band.
SPIKE_MAD_THRESHOLD: Final = 8.0

#: Fraction of spike samples above which the finding is raised to a warning.
SPIKE_WARN_FRACTION: Final = 0.001

#: Drift is measured as the shift between the first and last ``DRIFT_WINDOW_FRACTION`` of the
#: record, expressed in robust standard deviations of the whole column.
DRIFT_WINDOW_FRACTION: Final = 0.1
DRIFT_WARN_SIGMAS: Final = 3.0
DRIFT_ERROR_SIGMAS: Final = 6.0

#: Sampling-interval tolerance: a gap differing from the modal interval by more than this
#: fraction is a synchronisation finding (clock skew, a lost historian connection, a resample).
SYNC_INTERVAL_TOLERANCE: Final = 0.01

#: Columns the per-column checks skip by default. PRD 12's two label columns are *annotations*,
#: not measurements: ``injected_fault`` is null on every row where nothing is injected, which is
#: an absent label rather than a lost reading, and on a healthy record that is most of the rows -
#: reported as a missing-value fraction it would escalate every dataset to ``error`` and bury the
#: instrument findings underneath. A real-plant caller with no label columns passes ``exclude=()``.
DEFAULT_EXCLUDED_COLUMNS: Final[tuple[str, ...]] = (
    schema.REGIME_LABEL_COLUMN,
    schema.FAULT_LABEL_COLUMN,
)

#: The six FR-13 checks, in report order.
CHECKS: Final[tuple[str, ...]] = (
    "missing_values",
    "duplicates",
    "constant_sensors",
    "spikes",
    "drift",
    "sync",
)

#: Severity ladder, worst last.
SEVERITIES: Final[tuple[str, ...]] = ("info", "warning", "error")


def _worse(left: str, right: str) -> str:
    """The more serious of two severities."""
    return left if SEVERITIES.index(left) >= SEVERITIES.index(right) else right


# =============================================================================
# Findings
# =============================================================================
@dataclass(frozen=True, slots=True)
class QualityFinding:
    """One thing the report noticed, on one column (or on the frame, for ``sync``)."""

    check: str
    column: str
    severity: str
    count: int
    detail: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "column": self.column,
            "severity": self.severity,
            "count": int(self.count),
            **{key: _plain(value) for key, value in self.detail.items()},
        }


def _plain(value: Any) -> Any:
    """Make a numpy scalar JSON-serializable without losing its value."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """The FR-13 report of one frame: the findings plus enough context to read them."""

    name: str
    rows: int
    columns: tuple[str, ...]
    findings: tuple[QualityFinding, ...]

    @property
    def severity(self) -> str:
        """Worst severity present, or ``"info"`` for a clean frame."""
        worst = "info"
        for finding in self.findings:
            worst = _worse(worst, finding.severity)
        return worst

    def by_check(self, check: str) -> tuple[QualityFinding, ...]:
        """Findings of one FR-13 check, in column order."""
        if check not in CHECKS:
            raise ConfigError(f"unknown check {check!r}; expected one of {list(CHECKS)}")
        return tuple(finding for finding in self.findings if finding.check == check)

    def flagged(self, check: str) -> tuple[str, ...]:
        """Columns one check fired on."""
        return tuple(finding.column for finding in self.by_check(check))

    def describe(self) -> dict[str, Any]:
        """JSON-serializable report body (PRD 17 view 9 renders this; no wall-clock in it)."""
        return {
            "name": self.name,
            "rows": int(self.rows),
            "columns": list(self.columns),
            "severity": self.severity,
            "counts": {check: len(self.by_check(check)) for check in CHECKS},
            "findings": [finding.describe() for finding in self.findings],
        }

    def to_json(self, path: Path | str | None = None) -> Path:
        """Write the report to ``reports/data_quality/`` (PRD 23) and return its path."""
        target = (
            Path(path)
            if path is not None
            else paths.REPORTS_DATA_QUALITY_DIR / f"{self.name}_quality.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.describe(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return target


# =============================================================================
# The six FR-13 checks
# =============================================================================
def _numeric_columns(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> tuple[str, ...]:
    """Columns the numeric checks apply to (the label columns are categorical by design)."""
    return tuple(
        str(column)
        for column in frame.columns
        if column != timestamp
        and str(column) not in exclude
        and pd.api.types.is_numeric_dtype(frame[column])
    )


def _robust_sigma(values: np.ndarray) -> float:
    """MAD-based standard-deviation estimate; 0.0 for a constant or empty column.

    The median absolute deviation is used rather than the sample standard deviation because the
    very things this module looks for - spikes, a stuck run, a drifting bias - inflate the
    latter, which would then hide them (a spike raising its own detection threshold).
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    deviation = float(np.median(np.abs(finite - np.median(finite))))
    return deviation * 1.4826  # MAD -> sigma for a Gaussian


def _check_missing(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> list[QualityFinding]:
    """FR-13 missing values: PRD 11.5's dropouts land here (NaN, never an imputed value)."""
    findings: list[QualityFinding] = []
    rows = max(len(frame), 1)
    for column in frame.columns:
        if str(column) in exclude:
            continue
        missing = int(frame[column].isna().sum())
        if missing == 0:
            continue
        fraction = missing / rows
        severity = (
            "error"
            if fraction > MISSING_ERROR_FRACTION
            else "warning"
            if fraction > MISSING_WARN_FRACTION
            else "info"
        )
        findings.append(
            QualityFinding(
                check="missing_values",
                column=str(column),
                severity=severity,
                count=missing,
                detail={"fraction": round(fraction, 6)},
            )
        )
    return findings


def _check_duplicates(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> list[QualityFinding]:
    """FR-13 duplicates: a repeated timestamp, and a fully repeated row.

    Both are reported because they mean different things in a historian extract: a duplicated
    timestamp is an export or merge fault, while an identical *row* at a distinct timestamp is
    usually a replayed buffer. ``exclude`` is deliberately ignored here: a replayed buffer repeats
    every field, so the row comparison is made over the frame as it stands.
    """
    findings: list[QualityFinding] = []
    if timestamp in frame.columns:
        repeated = int(frame[timestamp].duplicated().sum())
        if repeated:
            findings.append(
                QualityFinding(
                    check="duplicates",
                    column=timestamp,
                    severity="error",
                    count=repeated,
                    detail={"kind": "duplicate_timestamp"},
                )
            )
    whole = int(frame.duplicated().sum())
    if whole:
        findings.append(
            QualityFinding(
                check="duplicates",
                column="<row>",
                severity="warning",
                count=whole,
                detail={"kind": "duplicate_row"},
            )
        )
    return findings


def _longest_run(values: np.ndarray) -> int:
    """Longest run of bit-identical consecutive samples (NaN breaks a run)."""
    if values.size == 0:
        return 0
    same = np.zeros(values.size, dtype=bool)
    same[1:] = (values[1:] == values[:-1]) & np.isfinite(values[1:])
    longest = current = 1
    for flag in same[1:]:
        current = current + 1 if flag else 1
        longest = max(longest, current)
    return longest


def _check_constant(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> list[QualityFinding]:
    """FR-13 constant sensors: a dead tag, and PRD 11.5's stuck/frozen windows."""
    findings: list[QualityFinding] = []
    for column in _numeric_columns(frame, timestamp, exclude):
        values = frame[column].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            continue
        scale = max(abs(float(np.median(finite))), 1e-12)
        spread = float(finite.max() - finite.min())
        if spread / scale <= CONSTANT_RELATIVE_RANGE:
            findings.append(
                QualityFinding(
                    check="constant_sensors",
                    column=column,
                    severity="error",
                    count=int(finite.size),
                    detail={"kind": "constant", "value": float(finite[0])},
                )
            )
            continue
        longest = _longest_run(values)
        if longest >= STUCK_MIN_RUN:
            findings.append(
                QualityFinding(
                    check="constant_sensors",
                    column=column,
                    severity="warning",
                    count=longest,
                    detail={"kind": "stuck_run", "longest_run": longest},
                )
            )
    return findings


def _check_spikes(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> list[QualityFinding]:
    """FR-13 spikes: a single-sample excursion far outside the tag's own step-to-step scale.

    The statistic is the first difference rather than the level, so a legitimate ramp or regime
    change - which moves the level a long way but each *step* only a little - is not a spike,
    while a one-sample glitch is one regardless of where the level happens to be.

    On a full PRD 11.4 record two tag classes fire here in bulk without anything being wrong with
    the instrument, which is why this check is capped at ``warning``: the regime-7 fan-instability
    burst *is* per-sample noise on a fan speed, and ``CO_ppm`` is deliberately nonlinear near the
    oxygen floor (PRD 9.4), so its step-to-step distribution is heavy-tailed and a robust
    threshold flags its tail. FR-13 is a report, not an alarm.
    """
    findings: list[QualityFinding] = []
    rows = max(len(frame), 1)
    for column in _numeric_columns(frame, timestamp, exclude):
        values = frame[column].to_numpy(dtype=float)
        if values.size < 3:
            continue
        difference = np.diff(values)
        sigma = _robust_sigma(difference)
        if sigma <= 0.0:
            continue
        score = np.abs(difference - np.nanmedian(difference)) / sigma
        spikes = int(np.count_nonzero(score > SPIKE_MAD_THRESHOLD))
        if spikes == 0:
            continue
        fraction = spikes / rows
        findings.append(
            QualityFinding(
                check="spikes",
                column=column,
                severity="warning" if fraction > SPIKE_WARN_FRACTION else "info",
                count=spikes,
                detail={
                    "fraction": round(fraction, 6),
                    "worst_sigmas": round(float(np.nanmax(score)), 3),
                },
            )
        )
    return findings


def _check_drift(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> list[QualityFinding]:
    """FR-13 drift: a level shift between the head and the tail of the record.

    PRD 11.5's regime-14 bias drift is exactly this signature. The shift is expressed in robust
    sigmas of the column itself so the check needs no per-tag calibration and transfers to real
    data unchanged (PRD 21). A regime change also shows here, and on a long record the head and
    tail windows average over many regimes, so a genuine drift episode in the middle can wash
    out - the check is sensitive to a *net* shift across the extract, not to every excursion.
    """
    findings: list[QualityFinding] = []
    window = int(max(2, round(len(frame) * DRIFT_WINDOW_FRACTION)))
    if len(frame) < 4 * window:
        return findings
    for column in _numeric_columns(frame, timestamp, exclude):
        values = frame[column].to_numpy(dtype=float)
        sigma = _robust_sigma(values)
        if sigma <= 0.0:
            continue
        head = float(np.nanmedian(values[:window]))
        tail = float(np.nanmedian(values[-window:]))
        if not (np.isfinite(head) and np.isfinite(tail)):
            continue
        sigmas = abs(tail - head) / sigma
        if sigmas < DRIFT_WARN_SIGMAS:
            continue
        findings.append(
            QualityFinding(
                check="drift",
                column=column,
                severity="error" if sigmas > DRIFT_ERROR_SIGMAS else "warning",
                count=window,
                detail={
                    "sigmas": round(sigmas, 3),
                    "head_median": round(head, 6),
                    "tail_median": round(tail, 6),
                },
            )
        )
    return findings


def _check_sync(
    frame: pd.DataFrame, timestamp: str, exclude: frozenset[str]
) -> list[QualityFinding]:
    """FR-13 sync issues: non-monotonic time, and gaps off the modal sampling interval.

    "Sync" in a historian extract means the sample clock, not the tags: an out-of-order block, a
    lost connection (one long gap), or a resampled section (many short ones). All three show up
    as intervals that differ from the modal one, which is what is reported here. ``exclude`` does
    not apply: this check reads the timestamp column only.
    """
    if timestamp not in frame.columns or len(frame) < 3:
        return []
    stamps = pd.to_datetime(frame[timestamp])
    findings: list[QualityFinding] = []
    deltas = stamps.diff().dropna()
    if deltas.empty:
        return findings
    backwards = int((deltas <= pd.Timedelta(0)).sum())
    if backwards:
        findings.append(
            QualityFinding(
                check="sync",
                column=timestamp,
                severity="error",
                count=backwards,
                detail={"kind": "non_monotonic"},
            )
        )
    seconds = deltas.dt.total_seconds().to_numpy(dtype=float)
    positive = seconds[seconds > 0.0]
    if positive.size == 0:
        return findings
    modal = float(np.median(positive))
    tolerance = modal * SYNC_INTERVAL_TOLERANCE
    irregular = int(np.count_nonzero(np.abs(seconds - modal) > tolerance))
    if irregular:
        findings.append(
            QualityFinding(
                check="sync",
                column=timestamp,
                severity="warning",
                count=irregular,
                detail={
                    "kind": "irregular_interval",
                    "expected_seconds": modal,
                    "largest_gap_seconds": float(np.nanmax(seconds)),
                },
            )
        )
    return findings


#: The checks, in FR-13 order, as the report runs them.
_CHECK_FUNCTIONS: Final = (
    ("missing_values", _check_missing),
    ("duplicates", _check_duplicates),
    ("constant_sensors", _check_constant),
    ("spikes", _check_spikes),
    ("drift", _check_drift),
    ("sync", _check_sync),
)


# =============================================================================
# The report (FR-13, dashboard view 9)
# =============================================================================
def data_quality_report(
    frame: pd.DataFrame,
    name: str = "dataset",
    *,
    timestamp: str = schema.TIMESTAMP_COLUMN,
    checks: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
) -> DataQualityReport:
    """Run the six FR-13 checks over ``frame`` and collect what they found.

    ``checks`` restricts the run to a subset (the dashboard uses it to refresh one panel); by
    default all six run, in FR-13 order. ``exclude`` names columns the per-column checks skip and
    defaults to :data:`DEFAULT_EXCLUDED_COLUMNS`; pass ``()`` to audit every column.
    """
    if not isinstance(frame, pd.DataFrame):
        raise ConfigError("data_quality_report needs a pandas DataFrame")
    wanted = tuple(checks) if checks is not None else CHECKS
    unknown = [check for check in wanted if check not in CHECKS]
    if unknown:
        raise ConfigError(f"unknown check(s) {unknown}; expected a subset of {list(CHECKS)}")
    skipped = frozenset(
        str(column)
        for column in (DEFAULT_EXCLUDED_COLUMNS if exclude is None else exclude)
    )
    findings: list[QualityFinding] = []
    for check, function in _CHECK_FUNCTIONS:
        if check in wanted:
            findings.extend(function(frame, timestamp, skipped))
    return DataQualityReport(
        name=name,
        rows=int(len(frame)),
        columns=tuple(str(column) for column in frame.columns),
        findings=tuple(findings),
    )


def report_run(run: Any, *, write: bool = False) -> dict[str, DataQualityReport]:
    """FR-13 over both datasets of a :class:`~src.data_generation.generator.GeneratedRun`.

    Typed loosely on purpose: the same helper serves PRD 26's ``RealPlantDataProvider``, which
    hands over frames that never came from the generator at all.
    """
    reports: dict[str, DataQualityReport] = {}
    for dataset, frame in run.datasets.items():
        report = data_quality_report(frame, name=str(dataset))
        if write:
            report.to_json()
        reports[str(dataset)] = report
    return reports


__all__ = [
    "CHECKS",
    "CONSTANT_RELATIVE_RANGE",
    "DEFAULT_EXCLUDED_COLUMNS",
    "DRIFT_ERROR_SIGMAS",
    "DRIFT_WARN_SIGMAS",
    "DRIFT_WINDOW_FRACTION",
    "MISSING_ERROR_FRACTION",
    "MISSING_WARN_FRACTION",
    "SEVERITIES",
    "SPIKE_MAD_THRESHOLD",
    "SPIKE_WARN_FRACTION",
    "STUCK_MIN_RUN",
    "SYNC_INTERVAL_TOLERANCE",
    "DataQualityReport",
    "QualityFinding",
    "data_quality_report",
    "report_run",
]
