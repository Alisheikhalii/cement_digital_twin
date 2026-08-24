"""The FR-13 data-quality report (PRD v1.1.1 FR-13, Section 34 "Data quality" row).

Section 34 asks that the report *"correctly flags synthetically-injected missing values,
duplicate timestamps, constant sensors, spikes, and drift when deliberately introduced in a test
fixture"* - so each check gets a fixture that introduces exactly one defect into an otherwise
clean frame, and is asserted to fire on that column and to stay quiet on the others. The sixth
FR-13 check, sync, is covered the same way with a clock defect.

The clean frame is deliberately *not* a generated dataset: PRD 11.5 injects dropouts, stuck
sensors and a drifting bias on purpose, so a real dataset cannot serve as the negative control.
It is used in the last section instead, where the report is asked to find the imperfections the
sensor model is documented to have put there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import schema
from src.config import ConfigError
from src.data_processing.quality import (
    CHECKS,
    MISSING_ERROR_FRACTION,
    STUCK_MIN_RUN,
    DataQualityReport,
    data_quality_report,
    report_run,
)

ROWS = 600


@pytest.fixture
def clean() -> pd.DataFrame:
    """A frame with nothing wrong with it: two smooth, noisy, gap-free tags on a 1-min clock."""
    rng = np.random.default_rng(20260817)
    stamps = pd.date_range("2026-01-01", periods=ROWS, freq="1min", tz="UTC")
    ramp = np.linspace(0.0, 2.0 * np.pi, ROWS)
    return pd.DataFrame(
        {
            schema.TIMESTAMP_COLUMN: stamps,
            "burning_zone_temperature": 1450.0 + 5.0 * np.sin(ramp) + rng.normal(0, 0.5, ROWS),
            "oxygen_percent": 3.0 + 0.2 * np.cos(ramp) + rng.normal(0, 0.02, ROWS),
        }
    )


def _fired(frame: pd.DataFrame, check: str) -> tuple[str, ...]:
    return data_quality_report(frame, name="fixture").flagged(check)


# =============================================================================
# The negative control
# =============================================================================
def test_a_clean_frame_produces_no_findings(clean):
    report = data_quality_report(clean, name="clean")
    assert report.findings == ()
    assert report.severity == "info"
    assert report.rows == ROWS
    assert report.describe()["counts"] == {check: 0 for check in CHECKS}


# =============================================================================
# The six checks, one deliberate defect each
# =============================================================================
def test_missing_values_are_flagged_with_their_fraction(clean):
    frame = clean.copy()
    frame.loc[10:19, "oxygen_percent"] = np.nan
    report = data_quality_report(frame, name="fixture")
    finding = report.by_check("missing_values")[0]
    assert report.flagged("missing_values") == ("oxygen_percent",)
    assert finding.count == 10
    assert finding.detail["fraction"] == pytest.approx(10 / ROWS, abs=1e-6)


def test_a_column_of_nothing_but_gaps_is_an_error(clean):
    frame = clean.copy()
    frame["oxygen_percent"] = np.nan
    finding = data_quality_report(frame, name="fixture").by_check("missing_values")[0]
    assert finding.severity == "error"
    assert finding.detail["fraction"] > MISSING_ERROR_FRACTION


def test_duplicate_timestamps_and_duplicate_rows_are_flagged_separately(clean):
    frame = pd.concat([clean, clean.iloc[[100]]], ignore_index=True)
    report = data_quality_report(frame, name="fixture")
    kinds = {finding.detail["kind"] for finding in report.by_check("duplicates")}
    assert kinds == {"duplicate_timestamp", "duplicate_row"}
    assert report.severity == "error"


def test_a_dead_sensor_is_flagged_as_constant(clean):
    frame = clean.copy()
    frame["oxygen_percent"] = 3.0
    finding = data_quality_report(frame, name="fixture").by_check("constant_sensors")[0]
    assert finding.column == "oxygen_percent"
    assert finding.detail["kind"] == "constant"
    assert finding.severity == "error"


def test_a_frozen_window_is_flagged_as_a_stuck_run(clean):
    """PRD 11.5's stuck/frozen sensor: the tag lives, but repeats one sample for a while."""
    frame = clean.copy()
    frame.loc[200 : 200 + STUCK_MIN_RUN + 5, "burning_zone_temperature"] = 1451.0
    finding = data_quality_report(frame, name="fixture").by_check("constant_sensors")[0]
    assert finding.column == "burning_zone_temperature"
    assert finding.detail["kind"] == "stuck_run"
    assert finding.detail["longest_run"] >= STUCK_MIN_RUN


def test_a_single_sample_glitch_is_flagged_as_a_spike(clean):
    frame = clean.copy()
    frame.loc[300, "burning_zone_temperature"] = 1650.0
    report = data_quality_report(frame, name="fixture")
    assert report.flagged("spikes") == ("burning_zone_temperature",)
    assert report.by_check("spikes")[0].detail["worst_sigmas"] > 8.0


def test_a_ramp_is_not_a_spike(clean):
    """A regime change moves the level a long way one small step at a time - not a glitch."""
    frame = clean.copy()
    frame["burning_zone_temperature"] += np.linspace(0.0, 60.0, ROWS)
    assert _fired(frame, "spikes") == ()


def test_an_additive_bias_ramp_is_flagged_as_drift(clean):
    """PRD 11.5 regime 14: a slow additive bias at the sensor layer only."""
    frame = clean.copy()
    frame["oxygen_percent"] += np.linspace(0.0, 1.5, ROWS)
    report = data_quality_report(frame, name="fixture")
    assert "oxygen_percent" in report.flagged("drift")
    assert report.by_check("drift")[0].detail["sigmas"] > 3.0


def test_a_clock_gap_and_an_out_of_order_block_are_sync_findings(clean):
    gapped = clean.drop(index=range(300, 340)).reset_index(drop=True)
    report = data_quality_report(gapped, name="fixture")
    findings = {finding.detail["kind"] for finding in report.by_check("sync")}
    assert "irregular_interval" in findings
    assert report.by_check("sync")[0].detail["expected_seconds"] == pytest.approx(60.0)

    shuffled = clean.copy()
    stamps = shuffled[schema.TIMESTAMP_COLUMN].to_numpy()
    stamps[[100, 101]] = stamps[[101, 100]]
    shuffled[schema.TIMESTAMP_COLUMN] = stamps
    kinds = {
        finding.detail["kind"]
        for finding in data_quality_report(shuffled, name="fixture").by_check("sync")
    }
    assert "non_monotonic" in kinds


def test_each_defect_leaves_the_other_columns_alone(clean):
    frame = clean.copy()
    frame.loc[50:59, "oxygen_percent"] = np.nan
    frame.loc[300, "burning_zone_temperature"] = 1650.0
    report = data_quality_report(frame, name="fixture")
    assert report.flagged("missing_values") == ("oxygen_percent",)
    assert report.flagged("spikes") == ("burning_zone_temperature",)


# =============================================================================
# Report plumbing
# =============================================================================
def test_a_subset_of_checks_can_be_requested(clean):
    frame = clean.copy()
    frame.loc[10, "oxygen_percent"] = np.nan
    frame.loc[300, "burning_zone_temperature"] = 1650.0
    report = data_quality_report(frame, name="fixture", checks=["missing_values"])
    assert report.by_check("missing_values")
    assert report.by_check("spikes") == ()


def test_an_unknown_check_is_rejected(clean):
    with pytest.raises(ConfigError):
        data_quality_report(clean, checks=["telepathy"])
    with pytest.raises(ConfigError):
        data_quality_report(clean).by_check("telepathy")


def test_something_that_is_not_a_frame_is_rejected():
    with pytest.raises(ConfigError):
        data_quality_report({"a": [1, 2, 3]})  # type: ignore[arg-type]


def test_the_report_is_json_serializable_and_writes_to_disk(clean, tmp_path):
    import json

    frame = clean.copy()
    frame.loc[10:19, "oxygen_percent"] = np.nan
    report = data_quality_report(frame, name="kiln")
    target = report.to_json(tmp_path / "kiln_quality.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["name"] == "kiln"
    assert payload["severity"] in {"info", "warning", "error"}
    assert payload["counts"]["missing_values"] == 1
    assert payload == json.loads(json.dumps(report.describe()))


# =============================================================================
# On a generated dataset the report must find PRD 11.5's own imperfections
# =============================================================================
@pytest.fixture(scope="module")
def generated():
    from src.data_generation.generator import DatasetGenerator
    from src.simulation.simulation_config import SimulationConfig

    return DatasetGenerator(
        SimulationConfig.from_config(duration_days=2.0, warmup_minutes=180.0)
    ).run()


def test_the_report_finds_the_dropouts_the_sensor_model_injected(generated):
    """Every NaN the report counts is a PRD 11.5 dropout - the label columns are not measurements."""
    for dataset, frame in generated.datasets.items():
        report = data_quality_report(frame, name=str(dataset))
        flagged = report.flagged("missing_values")
        assert flagged, "PRD 11.5 dropouts should be visible to FR-13"
        assert schema.FAULT_LABEL_COLUMN not in flagged
        total = sum(finding.count for finding in report.by_check("missing_values"))
        assert total == generated.sensors[dataset].missing_total


def test_an_absent_label_is_not_a_missing_measurement(generated):
    """``injected_fault`` is null on most rows by design; FR-13 must not read that as data loss.

    Without the :data:`DEFAULT_EXCLUDED_COLUMNS` skip the label's null fraction clears
    ``MISSING_ERROR_FRACTION`` on every healthy record, so an annotation would outrank every
    instrument finding in the report. Asserted on the label column rather than on the report's
    overall severity, because a real instrument finding is free to be an error too.
    """
    frame = generated.datasets["kiln"]
    assert frame[schema.FAULT_LABEL_COLUMN].isna().mean() > MISSING_ERROR_FRACTION
    default = data_quality_report(frame, name="kiln")
    assert schema.FAULT_LABEL_COLUMN not in default.flagged("missing_values")
    assert schema.REGIME_LABEL_COLUMN not in default.flagged("missing_values")

    audited = data_quality_report(frame, name="kiln", exclude=())
    label = [
        finding
        for finding in audited.by_check("missing_values")
        if finding.column == schema.FAULT_LABEL_COLUMN
    ]
    assert label and label[0].severity == "error"


def test_the_report_finds_the_stuck_windows_the_sensor_model_injected(generated):
    for dataset, frame in generated.datasets.items():
        stuck = {event.tag for event in generated.sensors[dataset].stuck_events}
        if not stuck:
            continue
        report = data_quality_report(frame, name=str(dataset))
        assert stuck & set(report.flagged("constant_sensors"))


def test_a_generated_dataset_has_no_duplicate_or_out_of_order_timestamps(generated):
    for dataset, frame in generated.datasets.items():
        report = data_quality_report(frame, name=str(dataset))
        assert report.by_check("duplicates") == ()
        assert report.by_check("sync") == ()


def test_report_run_covers_both_datasets_and_can_write(generated, tmp_path, monkeypatch):
    from src import paths

    monkeypatch.setattr(paths, "REPORTS_DATA_QUALITY_DIR", tmp_path)
    reports = report_run(generated, write=True)
    assert set(reports) == {"kiln", "mill"}
    assert all(isinstance(report, DataQualityReport) for report in reports.values())
    assert {path.name for path in tmp_path.iterdir()} == {
        "kiln_quality.json",
        "mill_quality.json",
    }
