"""The end-to-end data pipeline (PRD v1.1.1 Sections 11.2-11.6, 12; Section 34 integration row).

Section 34 asks one integration test of this layer: *"End-to-end ``ScenarioScheduler -> Twin ->
SensorModel -> dataset`` produces the expected schema (Section 12) and all 14 regime labels are
present; balance residuals recorded and within tolerance."* This module is that test, plus the
contracts a later change could break silently:

* the exported columns are exactly PRD 12.1/12.2, in order, with the ground truth outside them;
* the warm-up window cannot shift a single measured number (NFR-4);
* an unmeasured disturbance is visible in the truth frame and *only* there (PRD 11.3);
* two runs of one seed are identical and two seeds differ (NFR-4, PRD 11.6);
* CSV, Parquet and the JSON sidecar round-trip (PRD 11.6).

The conservation assertion is the one place the test has to be more specific than NFR-10's
"across the full simulated horizon": it is made through the three-regime methodology of
:mod:`src.data_generation.conservation` (SIMULATION_ASSUMPTIONS.md 11.5), whose own test module
``test_conservation_validation.py`` pins the methodology itself.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import schema
from src.config import ConfigError
from src.data_generation import export as export_module
from src.data_generation.conservation import REGIMES, conservation_report
from src.data_generation.generator import DATASETS, DatasetGenerator
from src.data_generation.health import FAULT_COLUMN, HEALTH_COLUMN
from src.simulation.simulation_config import SimulationConfig

#: ASSUMPTION test horizon: 3 days at 1 min = 4,320 exported rows. Long enough for the scheduler
#: to visit every one of the 14 PRD 11.4 regimes plus the startup ramp, short enough to keep the
#: module inside a few seconds.
HORIZON_DAYS = 3.0

#: Warm-up used throughout; PRD 11.2 discards it, and NFR-4 says lengthening it must not move a
#: measured number - which ``test_the_warmup_length_does_not_move_a_measured_number`` checks.
WARMUP_MINUTES = 180.0


@pytest.fixture(scope="module")
def simulation() -> SimulationConfig:
    return SimulationConfig.from_config(
        duration_days=HORIZON_DAYS, warmup_minutes=WARMUP_MINUTES
    )


@pytest.fixture(scope="module")
def generator(simulation) -> DatasetGenerator:
    return DatasetGenerator(simulation)


@pytest.fixture(scope="module")
def run(generator):
    return generator.run()


# =============================================================================
# The exported schema (PRD 12.1/12.2)
# =============================================================================
def test_every_dataset_has_the_documented_columns_in_order(run, generator):
    for dataset in DATASETS:
        frame = run.datasets[dataset]
        assert list(frame.columns) == list(generator.dataset_columns(dataset))
        assert frame.columns[0] == schema.TIMESTAMP_COLUMN
        assert list(frame.columns[-2:]) == [
            schema.REGIME_LABEL_COLUMN,
            schema.FAULT_LABEL_COLUMN,
        ]


def test_the_debug_variant_is_off_by_default_and_adds_only_the_residuals(generator):
    """PRD 12.1: the two residual columns appear only with ``debug_balance_export: true``."""
    for dataset in DATASETS:
        assert generator.debug_balance(dataset) is False
        assert generator.dataset_columns(dataset) == schema.columns_for(dataset)


def test_the_datasets_cover_the_configured_horizon_at_the_sampling_interval(run, simulation):
    for dataset in DATASETS:
        frame = run.datasets[dataset]
        assert len(frame) == simulation.export_steps
        stamps = pd.DatetimeIndex(frame[schema.TIMESTAMP_COLUMN])
        assert stamps.is_monotonic_increasing
        assert stamps.freqstr in {"min", "1min", "T"} or (
            stamps.to_series().diff().dropna().dt.total_seconds() == simulation.dt_seconds
        ).all()
        assert stamps[0] == simulation.start_timestamp


def test_the_warmup_rows_never_leave_the_generator(run, simulation):
    """PRD 11.2 discards the warm-up, which is why it runs *before* the exported epoch.

    ``start_timestamp`` is the first exported sample, so the settling window occupies negative
    time (``run_timestamps`` starts one warm-up earlier). A dataset therefore always opens on
    the configured epoch no matter how long the twin was settled for - the convention NFR-4
    needs, and the one ``test_the_warmup_length_does_not_move_a_measured_number`` relies on.
    """
    assert run.index[0] == simulation.start_timestamp
    assert simulation.run_timestamps[0] < simulation.start_timestamp
    minutes = (simulation.start_timestamp - simulation.run_timestamps[0]).total_seconds() / 60.0
    assert minutes == pytest.approx(WARMUP_MINUTES)
    assert len(run.index) == simulation.export_steps < simulation.total_steps


def test_the_measured_frame_carries_the_sensor_models_gaps(run):
    """PRD 11.5's dropouts are the only NaNs, and they are in the dataset, not the truth.

    ``injected_fault`` is null on every row where nothing is injected, in both frames, so it is
    counted separately: what has to match the sensor model's own tally is the *measurement* gaps.
    """
    for dataset in DATASETS:
        frame = run.datasets[dataset]
        missing = int(frame.isna().sum().sum())
        faults = int(frame[schema.FAULT_LABEL_COLUMN].isna().sum())
        assert missing - faults == run.sensors[dataset].missing_total
        truth = run.truth[dataset].drop(columns=[schema.FAULT_LABEL_COLUMN])
        assert truth.notna().all().all()


# =============================================================================
# Ground truth stays outside the dataset (PRD 12.1/12.2, 34 item 2)
# =============================================================================
def test_health_and_the_unmeasured_disturbances_are_truth_only(run):
    truth_only = (
        HEALTH_COLUMN,
        FAULT_COLUMN,
        "ambient_temperature_C",
        "feed_moisture_swing_pct_abs",
        "fuel_lhv_swing_pct",
        "episode_index",
        "is_startup",
        "sensor_drift_progress",
    )
    for dataset in DATASETS:
        for column in truth_only:
            assert column in run.truth[dataset].columns
            assert column not in run.datasets[dataset].columns


def test_the_truth_frame_holds_the_same_rows_as_the_dataset(run):
    for dataset in DATASETS:
        assert len(run.truth[dataset]) == len(run.datasets[dataset])
        assert (
            run.truth[dataset][schema.TIMESTAMP_COLUMN]
            == run.datasets[dataset][schema.TIMESTAMP_COLUMN]
        ).all()


def test_an_unmeasured_feed_disturbance_is_visible_only_in_the_truth(run):
    """PRD 11.4 regime 8: the DCS sees its setpoint, the process sees the disturbance.

    That gap is what makes the event learnable-but-unlabelled, so it has to survive into the
    export: the dataset's feedback tag must follow ``commanded`` while the truth follows the
    driven value.
    """
    truth = run.truth["kiln"]
    dataset = run.datasets["kiln"]
    disturbed = truth[schema.REGIME_LABEL_COLUMN] == "Feed disturbance"
    assert disturbed.any()
    commanded = dataset.loc[disturbed, "kiln_feed_rate_tph"].to_numpy(dtype=float)
    driven = truth.loc[disturbed, "kiln_feed_rate_tph"].to_numpy(dtype=float)
    finite = np.isfinite(commanded)
    assert np.abs(driven[finite] - commanded[finite]).max() > 1.0


# =============================================================================
# Regime coverage (FR-3, PRD 11.4, Section 34 integration row)
# =============================================================================
def test_all_fourteen_regimes_and_the_startup_ramp_are_present(run):
    labels = set(run.truth["kiln"][schema.REGIME_LABEL_COLUMN]) | set(
        run.truth["mill"][schema.REGIME_LABEL_COLUMN]
    )
    expected = {
        "Normal - low production",
        "Normal - medium production",
        "Normal - high production",
        "High fuel condition",
        "Low oxygen condition",
        "High oxygen condition",
        "Fan instability",
        "Feed disturbance",
        "Temperature disturbance",
        "Mill overload",
        "Mill underload",
        "High separator speed",
        "Low separator speed",
        "Sensor drift",
        "Startup transition",
    }
    assert expected <= labels


def test_every_injected_fault_label_names_a_regime_that_is_running(run):
    for dataset in DATASETS:
        frame = run.datasets[dataset]
        flagged = frame[schema.FAULT_LABEL_COLUMN].notna()
        assert flagged.any()
        assert (frame.loc[flagged, schema.REGIME_LABEL_COLUMN] != "Normal - medium production").all()


# =============================================================================
# Conservation over the generated horizon (NFR-10, Section 34 integration row)
# =============================================================================
@pytest.fixture(scope="module")
def conservation(generator, run):
    """The NFR-10 three-regime report of this module's horizon (SIMULATION_ASSUMPTIONS.md 11.5).

    Built from the run's own trajectory rather than a fresh one, so what is validated is exactly
    the horizon the other tests in this module inspect.
    """
    state = generator.run_trajectory(run.schedule, run.health)
    return conservation_report(
        generator, state=state, schedule=run.schedule, name="test_data_generator"
    )


def test_the_generated_horizon_satisfies_nfr10_in_all_three_regimes(conservation):
    """Section 34's "balance residuals recorded and within tolerance", by the 11.5 methodology.

    One assertion covers the whole of NFR-10 for this horizon: the settled peak against the
    unchanged +/-3 %, the transient regime against its integral (aggregate *and* worst episode)
    plus its own peak bound, the startup ramp against the reference input basis, and the
    horizon-wide energy-weighted integral against the same unchanged +/-3 %. Which statistic
    bounds which regime, and why, is :mod:`src.data_generation.conservation`.
    """
    assert conservation.passed, conservation.summary()
    # Every exported row belongs to exactly one regime, so no row escapes validation.
    assert sum(conservation.regime(name).rows for name in REGIMES) == conservation.rows


def test_the_settled_regime_keeps_the_unchanged_relative_bound(
    conservation, kiln_energy_tolerance_pct
):
    """Regime 1 of the directive: normal operation is still judged by +/-3 % of *its own* input.

    The bound is the config's ``unaccounted_loss_max_fraction``, unchanged and not restated here;
    the statistic is the peak, not an average, so a single bad settled row would fail.
    """
    settled = conservation.regime("settled")
    assert settled.metric == "peak_relative_pct"
    assert settled.bound_pct == pytest.approx(kiln_energy_tolerance_pct)
    assert settled.rows > 0.5 * conservation.rows  # the horizon is mostly settled operation
    assert settled.peak_relative_pct < kiln_energy_tolerance_pct
    assert settled.minimum_basis_fraction > 0.5  # a percentage of this input basis means something


def test_the_transient_regime_is_judged_by_its_integral_not_by_its_worst_step(
    conservation, kiln_energy_tolerance_pct
):
    """Regime 2: a delay transient is redistribution in time, so the honest statistic is a integral.

    The peak is still bounded - by ``transient_peak_max_fraction``, a bound on the *peak of a
    transient* rather than on steady-state closure - so the regime cannot absorb an arbitrarily
    large excursion; it is simply not judged as a steady-state failure.
    """
    transient = conservation.regime("transient")
    assert transient.metric == "integrated_pct"
    assert transient.integrated_pct < kiln_energy_tolerance_pct
    assert transient.worst_episode_integrated_pct < kiln_energy_tolerance_pct
    assert transient.peak_relative_pct > kiln_energy_tolerance_pct  # why the integral is needed
    assert transient.peak_relative_pct < conservation.bounds.transient_peak_max_pct
    assert transient.episodes > 1
    assert {check.statistic for check in transient.checks} == {
        "integrated_pct",
        "worst_episode_integrated_pct",
        "peak_relative_pct",
    }


def test_the_startup_regime_is_never_divided_by_a_collapsing_input_basis(conservation):
    """Regime 3: the startup ramp is judged against the *reference* basis, a fixed non-zero scale.

    The percentage of the instantaneous input is still *reported* - it reaches ~184 % - but no
    check is formed on it, and the reported minimum basis fraction shows why: the input basis on
    those rows is a fraction of the operating point whose outputs are still draining.
    """
    startup = conservation.regime("startup")
    assert startup.metric == "reference_relative_pct"
    assert startup.rows > 0
    assert startup.minimum_basis_fraction < conservation.bounds.near_zero_input_fraction * 2.0
    assert startup.peak_relative_pct > startup.reference_relative_pct  # the artefact, reported
    assert startup.reference_relative_pct < conservation.bounds.startup_reference_max_pct
    assert [check.statistic for check in startup.checks] == ["reference_relative_pct"]


def test_the_settled_bound_holds_without_the_delay_tails_help(
    generator, run, kiln_energy_tolerance_pct
):
    """The strictest possible reading: only the step a move lands on is excused as a transient.

    This is the guard against the transient window being what makes the settled bound pass. With
    the window collapsed to one simulation step - the PRD 8.3 execution-order term alone, no
    settling tail - the settled peak is still inside the unchanged +/-3 %.
    """
    state = generator.run_trajectory(run.schedule, run.health)
    strict = conservation_report(
        generator,
        state=state,
        schedule=run.schedule,
        settling_minutes=generator.simulation.dt_seconds / 60.0,
        name="strict",
    )
    settled = strict.regime("settled")
    assert settled.rows > 0.5 * strict.rows
    assert settled.peak_relative_pct < kiln_energy_tolerance_pct


def test_both_mass_balances_close_to_machine_precision_everywhere(
    run, generator, kiln_mass_tolerance_pct, mill_mass_tolerance_pct
):
    """PRD 9.3/10.2 mass closures are exact discretizations - startup rows included.

    Unchanged by the NFR-10 energy methodology: one metric, one bound, every row.
    """
    state = generator.run_trajectory(run.schedule, run.health)
    exported = run.schedule.exported(state)
    assert exported["kiln_mass_pct"].abs().max() < 1e-6
    assert exported["mill_mass_pct"].abs().max() < 1e-6
    assert kiln_mass_tolerance_pct > 0.0 and mill_mass_tolerance_pct > 0.0


def test_the_debug_variant_exports_the_residuals_it_closes(simulation):
    """PRD 12.1's note, and PRD 10.2's asymmetry: the mill has no energy balance to export."""
    from src.config import KILN, MILL, Config, load_config

    def enabled(name: str) -> Config:
        data = load_config(name).to_dict()
        data["debug_balance_export"] = True
        return Config(data, source=f"<debug {name}>")

    short = simulation.replace(duration_minutes=90.0, warmup_minutes=30.0)
    generator = DatasetGenerator(
        short, kiln_config=enabled(KILN), mill_config=enabled(MILL)
    )
    assert generator.dataset_columns("kiln")[-2:] == (
        "energy_balance_residual_pct",
        "mass_balance_residual_pct",
    )
    assert generator.dataset_columns("mill")[-1:] == ("mass_balance_residual_pct",)
    run = generator.run()
    for dataset in DATASETS:
        assert list(run.datasets[dataset].columns) == list(generator.dataset_columns(dataset))


# =============================================================================
# Reproducibility (NFR-4, PRD 11.6)
# =============================================================================
@pytest.fixture(scope="module")
def short() -> SimulationConfig:
    """A cheap horizon for the tests that need a *second* run to compare against."""
    return SimulationConfig.from_config(duration_minutes=240.0, warmup_minutes=60.0)


def test_two_runs_of_one_seed_are_identical(short):
    first = DatasetGenerator(short).run()
    second = DatasetGenerator(short).run()
    for dataset in DATASETS:
        pd.testing.assert_frame_equal(first.datasets[dataset], second.datasets[dataset])
        pd.testing.assert_frame_equal(first.truth[dataset], second.truth[dataset])
    assert json.dumps(first.describe(), sort_keys=True, default=str) == json.dumps(
        second.describe(), sort_keys=True, default=str
    )


def test_a_different_seed_gives_different_measurements(short):
    first = DatasetGenerator(short).run()
    other = DatasetGenerator(short.replace(seed=987654)).run()
    measured = first.datasets["kiln"]["burning_zone_temperature"].to_numpy(dtype=float)
    again = other.datasets["kiln"]["burning_zone_temperature"].to_numpy(dtype=float)
    assert not np.allclose(measured, again, equal_nan=True)


def test_the_warmup_length_does_not_move_a_measured_number(short):
    """NFR-4: the warm-up settles the twin; it must not shift a single sample.

    This is the strict form of the invariant - not "similar statistics" but *equal frames*. It
    holds because every layer plans on the exported epoch: the scheduler's episodes, PRD 9.5's
    health ramp and PRD 11.5's sensor model all run on ``export_mask`` rows only, so a longer
    warm-up buys the twin more settling time and changes nothing else.
    """
    baseline = DatasetGenerator(short).run()
    longer = DatasetGenerator(short.replace(warmup_minutes=WARMUP_MINUTES)).run()
    assert longer.simulation.total_steps > baseline.simulation.total_steps
    for dataset in DATASETS:
        pd.testing.assert_frame_equal(baseline.datasets[dataset], longer.datasets[dataset])


def test_the_global_numpy_rng_is_never_used(short):
    np.random.seed(11)
    first = DatasetGenerator(short).run()
    np.random.seed(12)
    second = DatasetGenerator(short).run()
    pd.testing.assert_frame_equal(first.datasets["kiln"], second.datasets["kiln"])


def test_the_provenance_carries_the_configs_and_no_wall_clock(run):
    payload = json.loads(json.dumps(run.describe(), default=str))
    assert payload["prd_version"].startswith("1.1")
    assert set(payload["configs"]) == {"scenarios", "kiln_dynamics", "mill_dynamics"}
    assert payload["simulation"]["seed"] == run.simulation.seed
    text = json.dumps(payload)
    for stamp in ("generated_at", "created_at", "wall_clock", "now"):
        assert stamp not in text


def test_an_unknown_dataset_has_no_sidecar(run):
    with pytest.raises(ConfigError):
        run.sidecar("clinker_cooler")  # type: ignore[arg-type]


# =============================================================================
# Export (PRD 11.6)
# =============================================================================
def test_the_export_writes_csv_parquet_and_a_sidecar_per_dataset(short, tmp_path):
    run = DatasetGenerator(short).run()
    manifest = export_module.export_run(run, tmp_path)
    names = {path.name for path in manifest.files}
    assert names == {
        "kiln_raw.csv",
        "kiln_raw.parquet",
        "kiln_raw.json",
        "kiln_truth.csv",
        "kiln_truth.parquet",
        "mill_raw.csv",
        "mill_raw.parquet",
        "mill_raw.json",
        "mill_truth.csv",
        "mill_truth.parquet",
    }
    for path in manifest.files:
        assert path.exists() and path.stat().st_size > 0


def test_parquet_round_trips_the_dataset_exactly(short, tmp_path):
    run = DatasetGenerator(short).run()
    export_module.export_run(run, tmp_path)
    for dataset in DATASETS:
        loaded = export_module.load_dataset(dataset, tmp_path)
        pd.testing.assert_frame_equal(loaded, run.datasets[dataset])
        truth = export_module.load_truth(dataset, tmp_path)
        assert list(truth.columns) == list(run.truth[dataset].columns)


def test_csv_keeps_the_column_contract_and_the_timestamps(short, tmp_path):
    run = DatasetGenerator(short).run()
    export_module.export_run(run, tmp_path)
    for dataset in DATASETS:
        loaded = export_module.load_dataset(dataset, tmp_path, suffix="csv")
        assert list(loaded.columns) == list(run.datasets[dataset].columns)
        assert len(loaded) == len(run.datasets[dataset])
        assert pd.api.types.is_datetime64_any_dtype(loaded[schema.TIMESTAMP_COLUMN])


def test_the_sidecar_is_the_config_that_produced_the_file(short, tmp_path):
    run = DatasetGenerator(short).run()
    export_module.export_run(run, tmp_path)
    sidecar = export_module.load_sidecar("kiln", tmp_path)
    assert sidecar["dataset"] == "kiln"
    assert sidecar["rows"] == len(run.datasets["kiln"])
    assert sidecar["columns"] == list(run.datasets["kiln"].columns)
    assert sidecar["simulation"]["seed"] == run.simulation.seed
    assert sidecar["configs"]["scenarios"]["meta"]["prd_version"] == sidecar["prd_version"]


def test_the_sidecar_of_one_seed_is_byte_identical_between_runs(short, tmp_path):
    """NFR-4: a regression test has to be able to diff two sidecars."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    export_module.export_run(DatasetGenerator(short).run(), first)
    export_module.export_run(DatasetGenerator(short).run(), second)
    assert (first / "kiln_raw.json").read_bytes() == (second / "kiln_raw.json").read_bytes()


def test_the_format_switches_come_from_the_simulation_config(short, tmp_path):
    run = DatasetGenerator(short.replace(export_csv=False)).run()
    manifest = export_module.export_run(run, tmp_path)
    assert not any(path.suffix == ".csv" for path in manifest.files)
    assert any(path.suffix == ".parquet" for path in manifest.files)


def test_exporting_nothing_is_a_config_error(short, tmp_path):
    run = DatasetGenerator(short).run()
    with pytest.raises(ConfigError):
        export_module.export_run(run, tmp_path, csv=False, parquet=False, sidecar=False)


def test_loading_a_missing_export_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        export_module.load_dataset("kiln", tmp_path)
    with pytest.raises(ConfigError):
        export_module.load_sidecar("kiln", tmp_path)
