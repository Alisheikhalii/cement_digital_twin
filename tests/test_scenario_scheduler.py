"""Scenario scheduler: the 14 regimes, the ramps and the reproducibility contract.

PRD v1.1.1 11.3 (scheduler), 11.4 (the 14 mandatory regimes + the startup transition), 11.6 /
NFR-4 (same config + seed => same plan), FR-3 (all 14 regimes present in the dataset).

The default 30-day plan is built once for the module: it is the horizon the config actually
ships, and the FR-3 coverage claim is only meaningful on it.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.config import SCENARIOS, Config, ConfigError, load_config
from src.simulation.scheduler import (
    SETPOINTS,
    WARMUP_LABEL,
    ScenarioScheduler,
    _RampedSetpoint,
)
from src.simulation.simulation_config import SimulationConfig


@pytest.fixture(scope="module")
def scheduler() -> ScenarioScheduler:
    return ScenarioScheduler()


@pytest.fixture(scope="module")
def plan(scheduler):
    """The plan of the shipped configuration: 30 days at 1 min (PRD 11.2)."""
    return scheduler.build()


@pytest.fixture(scope="module")
def short_plan():
    """A two-day plan, for the assertions that do not need full regime coverage."""
    return ScenarioScheduler(
        SimulationConfig.from_config(duration_days=2.0, warmup_minutes=60.0)
    ).build()


def _mutated_scenarios(mutate) -> Config:
    """A copy of ``configs/scenarios.yaml`` with ``mutate`` applied to the plain dict."""
    data = load_config(SCENARIOS).to_dict()
    mutate(data)
    return Config(data, source="<mutated scenarios>")


# =============================================================================
# The plan: coverage, shares, tiling (PRD 11.4, FR-3)
# =============================================================================
def test_all_fourteen_regimes_are_present(plan, scheduler):
    """FR-3: every one of the 14 regimes must actually occur in the exported window."""
    realized = set(plan.regime_minutes())
    expected = {str(regime["name"]) for regime in scheduler._regimes}
    assert expected <= realized
    assert WARMUP_LABEL not in realized
    # The startup transition is the only extra label (PRD 11.4 trailing paragraph).
    assert realized - expected == {"Startup transition"}


def test_realized_shares_track_the_configured_targets(plan, scheduler):
    """The share-deficit rule must land every regime within a few points of its target."""
    minutes = plan.regime_minutes()
    total = float(plan.simulation.duration_minutes)
    for regime in scheduler._regimes:
        realized = minutes[str(regime["name"])] / total
        assert realized == pytest.approx(float(regime["share"]), abs=0.02)


def test_episodes_tile_the_run_without_gaps_or_overlaps(plan):
    steps = 0
    for episode in plan.episodes:
        assert episode.start_step == steps
        assert episode.steps > 0
        steps = episode.end_step
    assert steps == plan.simulation.total_steps
    assert len(plan.labels) == steps


def test_no_regime_runs_twice_in_a_row(plan):
    """ASSUMPTION: an episode boundary is always a real change of intent."""
    ids = [episode.regime_id for episode in plan.episodes if episode.regime_id is not None]
    assert all(first != second for first, second in zip(ids, ids[1:]))


def test_warmup_precedes_the_epoch_and_is_excluded_from_export(plan):
    simulation = plan.simulation
    assert plan.labels["is_warmup"].sum() == simulation.warmup_steps
    assert (plan.labels.loc[plan.labels["is_warmup"], "operating_regime"] == WARMUP_LABEL).all()
    exported = plan.exported(plan.labels)
    assert len(exported) == simulation.export_steps
    assert exported.index[0] == simulation.start_timestamp
    assert (plan.labels.index[: simulation.warmup_steps] < simulation.start_timestamp).all()


# =============================================================================
# Ratios, not absolutes; ramped, never stepped (PRD 11.3)
# =============================================================================
def test_regime_setpoints_are_ratios_of_the_reference_point(plan, scheduler):
    """A settled episode sits exactly on ``ratio x reference``, never on a hard-coded number."""
    reference = scheduler.kiln_reference.feed_rate_tph
    episode = next(e for e in plan.episodes if e.name == "Normal - high production")
    settled = plan.commanded["kiln"]["kiln_feed_rate_tph"].iloc[
        episode.end_step - 30 : episode.end_step
    ]
    assert settled.to_numpy() == pytest.approx(reference * 1.13, rel=1e-9)
    assert reference != pytest.approx(reference * 1.13)  # the ratio is doing work


def test_unnamed_variables_return_to_their_reference_value(plan, scheduler):
    """ASSUMPTION: the regime label alone determines the intended operating point."""
    # No regime moves the kiln speed, so it must sit on the reference for the whole run.
    assert plan.commanded["kiln"]["kiln_speed_rpm"].to_numpy() == pytest.approx(
        scheduler.kiln_reference.kiln_speed_rpm
    )
    # Regime 10 names only the mill feed, so the separator returns to reference inside it.
    episode = next(e for e in plan.episodes if e.name == "Mill overload")
    settled = plan.commanded["mill"]["separator_speed_rpm"].iloc[episode.end_step - 1]
    assert settled == pytest.approx(scheduler.mill_reference.separator_speed_rpm, rel=1e-9)


def test_setpoint_changes_are_ramped_not_stepped(plan, scheduler):
    """PRD 11.3: a setpoint change takes its configured minimum ramp time."""
    dt_minutes = float(plan.simulation.dt_seconds) / 60.0
    for variable in ("kiln_feed_rate_tph", "mill_feed_rate_tph"):
        spec = next(s for s in SETPOINTS if s.variable == variable)
        ramp_minutes = float(scheduler._ramp_times[spec.ramp_key])
        series = plan.exported(plan.commanded[spec.dataset])[variable]
        span = float(series.max() - series.min())
        largest_step = float(series.diff().abs().max())
        assert largest_step <= span * dt_minutes / ramp_minutes + 1e-9
        assert largest_step > 0.0  # the variable really does move


def test_a_ramped_setpoint_takes_its_configured_time(short_plan):
    """A move of any size takes ``ramp_minutes``: PRD 11.3 gives a time, not a rate."""
    for size in (1.0, 100.0):
        ramp = _RampedSetpoint(0.0, 10.0)
        values = [ramp.step(size, 1.0) for _ in range(10)]
        assert values[0] == pytest.approx(size * 0.1)
        assert values[4] == pytest.approx(size * 0.5)
        assert values[-1] == pytest.approx(size)
    instant = _RampedSetpoint(0.0, 0.0)
    assert instant.step(7.0, 1.0) == pytest.approx(7.0)
    with pytest.raises(ConfigError):
        _RampedSetpoint(0.0, -1.0)


# =============================================================================
# The startup transition (PRD 11.4 trailing paragraph)
# =============================================================================
def test_startup_ramps_the_kiln_line_from_zero_to_nominal(plan, scheduler):
    startup = plan.episodes[1]
    assert startup.is_startup
    assert startup.start_step == plan.simulation.warmup_steps  # it is the first exported episode
    feed = plan.exported(plan.commanded["kiln"])["kiln_feed_rate_tph"]
    fuel = plan.exported(plan.commanded["kiln"])["kiln_fuel_rate_tph"]
    assert feed.iloc[0] == pytest.approx(0.0)
    assert fuel.iloc[0] == pytest.approx(0.0)
    ramp_minutes = int(float(scheduler._startup["ramp_minutes"]))
    assert feed.iloc[:ramp_minutes].is_monotonic_increasing
    assert fuel.iloc[:ramp_minutes].is_monotonic_increasing
    # By the end of the episode the line sits on the target regime's operating point.
    assert feed.iloc[startup.steps - 1] == pytest.approx(
        scheduler.kiln_reference.feed_rate_tph, rel=1e-6
    )


def test_the_mill_does_not_follow_the_kiln_cold_start(plan, scheduler):
    """ASSUMPTION: PRD 8.3 decouples the units, so the mill starts at its own setpoint."""
    mill_feed = plan.exported(plan.commanded["mill"])["mill_feed_rate_tph"]
    assert mill_feed.iloc[0] == pytest.approx(scheduler.mill_reference.feed_rate_tph, rel=1e-9)


# =============================================================================
# Measured vs unmeasured effects (PRD 11.4 / 11.3)
# =============================================================================
def test_the_feed_disturbance_is_unmeasured(plan):
    """Regime 8 moves the twin's feed while the tag keeps reporting the setpoint."""
    episode = next(e for e in plan.episodes if e.name == "Feed disturbance")
    window = slice(episode.start_step, episode.end_step)
    for dataset, variable in (("kiln", "kiln_feed_rate_tph"), ("mill", "mill_feed_rate_tph")):
        driven = plan.inputs[dataset][variable].iloc[window].to_numpy()
        commanded = plan.commanded[dataset][variable].iloc[window].to_numpy()
        relative = driven / commanded - 1.0
        magnitude = float(episode.unmeasured_disturbance["magnitude_pct_of_current"]) / 100.0
        # ``step_then_ramp_back``: full magnitude at onset, linearly back to zero by the end.
        assert abs(relative[0]) == pytest.approx(
            magnitude * (1.0 - 1.0 / episode.steps), rel=1e-9
        )
        assert relative[-1] == pytest.approx(0.0, abs=1e-12)
        assert np.sign(relative[0]) == episode.sign


def test_the_fan_oscillation_is_measured(plan):
    """Regime 7: a hunting fan is visible in its own speed feedback, so both series move."""
    episode = next(e for e in plan.episodes if e.name == "Fan instability")
    window = slice(episode.start_step + 30, episode.end_step)  # past the entry ramp
    for dataset, variable in (("kiln", "ID_fan_speed_pct"), ("mill", "fan_speed_pct")):
        driven = plan.inputs[dataset][variable].iloc[window]
        commanded = plan.commanded[dataset][variable].iloc[window]
        assert driven.to_numpy() == pytest.approx(commanded.to_numpy())
        amplitude = float(episode.oscillation["amplitude_pct_of_current"]) / 100.0
        relative = (driven / driven.mean() - 1.0).abs().max()
        assert relative > amplitude / 2.0
        assert relative < amplitude * 3.0


def test_the_fuel_quality_swing_is_unmeasured(plan):
    """An LHV swing changes the energy the twin receives, not the mass the tag reports."""
    swing = plan.ground_truth["fuel_lhv_swing_pct"].to_numpy()
    assert swing.min() < -1.0 and swing.max() > 1.0
    for variable in ("kiln_fuel_rate_tph", "calciner_fuel_rate_tph"):
        driven = plan.inputs["kiln"][variable].to_numpy()
        commanded = plan.commanded["kiln"][variable].to_numpy()
        moving = commanded > 1e-6
        assert (driven[moving] / commanded[moving] - 1.0) == pytest.approx(
            swing[moving] / 100.0, abs=1e-12
        )


def test_the_moisture_swing_is_measured(plan):
    """A wet-feed event is visible to the moisture analyser, so both series carry it."""
    driven = plan.inputs["kiln"]["raw_meal_moisture_pct"]
    assert driven.to_numpy() == pytest.approx(
        plan.commanded["kiln"]["raw_meal_moisture_pct"].to_numpy()
    )
    swing = plan.ground_truth["feed_moisture_swing_pct_abs"]
    assert float(swing.abs().max()) > 0.0
    assert (driven >= 0.0).all()


def test_disturbances_are_clipped_to_their_configured_band(plan, scheduler):
    moisture_band = scheduler._scenarios.get_path("disturbances.feed_moisture_swing")
    bound = max(abs(float(value)) for value in moisture_band["magnitude_pct_abs"])
    assert float(plan.ground_truth["feed_moisture_swing_pct_abs"].abs().max()) <= bound + 1e-12
    lhv_band = scheduler._scenarios.get_path("disturbances.fuel_quality_swing")
    low, high = (float(value) for value in lhv_band["lhv_change_pct"])
    swing = plan.ground_truth["fuel_lhv_swing_pct"]
    assert float(swing.min()) >= low - 1e-12 and float(swing.max()) <= high + 1e-12


# =============================================================================
# Ground-truth labels (PRD 12.1 / 12.2)
# =============================================================================
def test_the_fault_label_is_set_only_on_the_affected_unit(plan):
    """PRD 22's precision/recall figures need the fault flagged on the unit it perturbs."""
    kiln_only = next(e for e in plan.episodes if e.name == "High fuel condition")
    mill_only = next(e for e in plan.episodes if e.name == "Mill overload")
    both = next(e for e in plan.episodes if e.name == "Fan instability")
    labels = plan.labels
    for episode, kiln_fault, mill_fault in (
        (kiln_only, "high_fuel", None),
        (mill_only, None, "mill_overload"),
        (both, "fan_instability", "fan_instability"),
    ):
        window = slice(episode.start_step, episode.end_step)
        kiln_column = labels["injected_fault_kiln"].iloc[window]
        mill_column = labels["injected_fault_mill"].iloc[window]
        assert set(kiln_column.dropna().unique()) == ({kiln_fault} if kiln_fault else set())
        assert set(mill_column.dropna().unique()) == ({mill_fault} if mill_fault else set())
        # The plant-level regime label is on both datasets regardless (FR-3).
        assert (labels["operating_regime"].iloc[window] == episode.name).all()


def test_normal_regimes_carry_no_fault_label(plan):
    normal = plan.labels["operating_regime"].str.startswith("Normal")
    assert plan.labels.loc[normal, "injected_fault_kiln"].isna().all()
    assert plan.labels.loc[normal, "injected_fault_mill"].isna().all()


def test_dataset_labels_expose_the_two_prd_columns(plan):
    for dataset in ("kiln", "mill"):
        frame = plan.dataset_labels(dataset)
        assert list(frame.columns) == ["operating_regime", "injected_fault"]
        assert frame["injected_fault"].equals(
            plan.labels[f"injected_fault_{dataset}"].rename("injected_fault")
        )


def test_the_sensor_drift_regime_is_flagged_for_the_sensor_layer_only(plan, scheduler):
    """PRD 11.4: regime 14 leaves the process alone; only the instruments drift."""
    episode = next(e for e in plan.episodes if e.name == "Sensor drift")
    assert episode.sensor_layer_only
    assert not episode.setpoints  # no process setpoint is touched
    window = slice(episode.start_step, episode.end_step)
    progress = plan.labels["sensor_drift_progress"].iloc[window].to_numpy()
    assert progress[0] == pytest.approx(1.0 / episode.steps)
    assert progress[-1] == pytest.approx(1.0)
    assert (np.diff(progress) > 0).all()
    # Outside the drift episodes the ramp is exactly zero.
    assert float(plan.labels["sensor_drift_progress"].iloc[episode.end_step]) == 0.0


# =============================================================================
# Reproducibility (NFR-4)
# =============================================================================
def _two_day_plan(**overrides):
    simulation = SimulationConfig.from_config(
        duration_days=2.0, warmup_minutes=60.0, **overrides
    )
    return ScenarioScheduler(simulation).build()


def test_the_plan_is_a_pure_function_of_config_and_seed(short_plan):
    import pandas as pd

    again = _two_day_plan()
    for dataset in ("kiln", "mill"):
        pd.testing.assert_frame_equal(short_plan.inputs[dataset], again.inputs[dataset])
        pd.testing.assert_frame_equal(short_plan.commanded[dataset], again.commanded[dataset])
    pd.testing.assert_frame_equal(short_plan.labels, again.labels)
    pd.testing.assert_frame_equal(short_plan.ground_truth, again.ground_truth)
    assert short_plan.describe() == again.describe()


def test_a_different_seed_gives_a_different_plan(short_plan):
    other = _two_day_plan(seed=987654)
    assert not short_plan.labels["operating_regime"].equals(other.labels["operating_regime"])
    assert not short_plan.ground_truth.equals(other.ground_truth)


def test_the_global_numpy_rng_is_never_used(short_plan):
    """NFR-4: seeding the legacy global generator must not change a single number."""
    import pandas as pd

    np.random.seed(11)
    first = _two_day_plan()
    np.random.seed(22)
    second = _two_day_plan()
    pd.testing.assert_frame_equal(first.inputs["kiln"], second.inputs["kiln"])
    pd.testing.assert_frame_equal(first.ground_truth, short_plan.ground_truth)


def test_warmup_length_does_not_reshuffle_the_disturbance_plan():
    """Disturbances are drawn over the exported window, so the warm-up cannot perturb them."""
    short = _two_day_plan()
    long_warmup = ScenarioScheduler(
        SimulationConfig.from_config(duration_days=2.0, warmup_minutes=240.0)
    ).build()
    kinds = [(e.kind, e.steps, e.magnitude) for e in short.events]
    shifted = [(e.kind, e.steps, e.magnitude) for e in long_warmup.events]
    assert kinds == shifted


def test_describe_is_json_serializable(short_plan):
    payload = json.dumps(short_plan.describe())
    restored = json.loads(payload)
    assert restored["simulation"]["seed"] == short_plan.simulation.seed
    assert len(restored["episodes"]) == len(short_plan.episodes)
    assert len(restored["disturbance_events"]) == len(short_plan.events)
    assert restored["regime_minutes"]


# =============================================================================
# Config validation: a typo must fail loudly, never silently (NFR-6)
# =============================================================================
@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        (
            "an unimplemented ordering rule",
            lambda data: data["regime_schedule"].update(order="round_robin"),
        ),
        (
            "a missing regime",
            lambda data: data["regime_schedule"]["regimes"].pop(),
        ),
        (
            "a duplicated regime id",
            lambda data: data["regime_schedule"]["regimes"][1].update(id=1),
        ),
        (
            "a misspelled setpoint key",
            lambda data: data["regime_schedule"]["regimes"][0]["setpoints"].update(
                kiln_feed_ration=1.1
            ),
        ),
        (
            "a setpoint key from the wrong unit spelling",
            lambda data: data["regime_schedule"]["regimes"][0]["setpoints"].update(
                ID_fan_speed_pct=80.0
            ),
        ),
        (
            "an oscillation on an undriven variable",
            lambda data: data["regime_schedule"]["regimes"][6]["oscillation"].update(
                variables=["burning_zone_temperature"]
            ),
        ),
        (
            "a ramp time that is not configured",
            lambda data: data["ramp_times_min"].pop("mill_speed"),
        ),
        (
            "a startup target that is not a regime",
            lambda data: data["regime_schedule"]["startup"].update(target_regime_id=99),
        ),
        (
            "a dwell band that is inverted",
            lambda data: data["regime_schedule"]["regimes"][0].update(dwell_hours=[10.0, 4.0]),
        ),
    ],
)
def test_a_broken_schedule_config_is_rejected(description, mutate):
    with pytest.raises(ConfigError):
        ScenarioScheduler(scenarios=_mutated_scenarios(mutate))
