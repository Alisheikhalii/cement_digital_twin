"""Equipment health: the slow wear scalar and its occasional mechanical fault (PRD 9.5).

PRD v1.1.1 9.5 asks for "a slow degrading ``health`` scalar (0-1) that very occasionally
(Poisson process, configurable rate) dips to simulate a mechanical-fault regime". The shape of
the wear ramp and of the post-fault recovery is an ASSUMPTION of the implementation; these
tests pin it so it cannot drift, and check the reproducibility contract of NFR-4.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.config import KILN, MILL, Config, ConfigError, load_config
from src.data_generation.health import (
    FAULT_COLUMN,
    HEALTH_COLUMN,
    HEALTH_KEYS,
    EquipmentHealthProcess,
)
from src.process_models.plant import PlantTwin
from src.simulation.simulation_config import MINUTES_PER_DAY, SimulationConfig


@pytest.fixture(scope="module")
def simulation() -> SimulationConfig:
    """A 90-day horizon: at 0.02 faults/day/unit a 30-day run may draw none at all."""
    return SimulationConfig.from_config(duration_days=90.0, warmup_minutes=180.0)


@pytest.fixture(scope="module")
def process(simulation) -> EquipmentHealthProcess:
    return EquipmentHealthProcess(simulation)


@pytest.fixture(scope="module")
def trajectories(process):
    return process.plan_all()


@pytest.fixture(scope="module")
def faulted(simulation):
    """A deliberately fault-heavy run.

    The shipped rate is 0.02 faults/day/unit, so whether a given horizon draws one at all is a
    coin toss - the *shape* of a fault must be pinned on a config that guarantees several,
    while the shipped config is left to prove only that faults stay rare.
    """
    raised = lambda data: data["equipment"]["health"].update(fault_rate_per_day=0.3)
    process = EquipmentHealthProcess(
        simulation,
        kiln_config=_mutated(KILN, raised),
        mill_config=_mutated(MILL, raised),
    )
    return process, process.plan_all()


def _mutated(name: str, mutate) -> Config:
    data = load_config(name).to_dict()
    mutate(data)
    return Config(data, source=f"<mutated {name}>")


def _settings(process: EquipmentHealthProcess, dataset: str) -> dict[str, float]:
    return {key: float(value) for key, value in process._settings[dataset].items()}


# =============================================================================
# Shape of the trajectory (PRD 9.5)
# =============================================================================
def test_the_trajectory_covers_every_simulated_step(trajectories, simulation):
    for dataset, trajectory in trajectories.items():
        assert trajectory.values.size == simulation.total_steps
        assert trajectory.key == HEALTH_KEYS[dataset]
        assert trajectory.dataset == dataset


def test_health_stays_inside_zero_to_one_and_above_the_configured_floor(
    trajectories, process
):
    for dataset, trajectory in trajectories.items():
        floor = _settings(process, dataset)["min_health"]
        assert trajectory.values.min() >= floor - 1e-12
        assert trajectory.values.max() <= 1.0 + 1e-12


def test_the_warmup_window_sits_at_the_initial_value(trajectories, simulation, process):
    """The warm-up settles the twin, so wear must start at the exported epoch."""
    for dataset, trajectory in trajectories.items():
        warmup = trajectory.values[: simulation.warmup_steps]
        assert warmup.size == simulation.warmup_steps
        assert warmup == pytest.approx(_settings(process, dataset)["initial"])


def test_wear_is_a_slow_linear_ramp_between_faults(faulted, simulation):
    """Away from a fault the only movement is ``degradation_per_day``."""
    process, trajectories = faulted
    steps_per_day = MINUTES_PER_DAY * simulation.steps_per_minute
    for dataset, trajectory in trajectories.items():
        settings = _settings(process, dataset)
        healthy = ~trajectory.fault_mask
        # A step counts as "between faults" only when both of its endpoints are healthy.
        differences = np.diff(trajectory.values)[healthy[:-1] & healthy[1:]]
        expected = -settings["degradation_per_day"] / steps_per_day
        # The warm-up plateau contributes exact zeros; the wear ramp contributes `expected`.
        assert set(np.round(np.unique(differences), 12)) <= {0.0, round(expected, 12)}
        assert (np.round(differences, 12) == round(expected, 12)).any()
        assert abs(expected) * steps_per_day < 0.01  # "slow" (PRD 9.5): < 1 %/day


def test_a_fault_is_a_step_down_followed_by_a_recovery_ramp(faulted, simulation):
    """PRD 9.5's "dips": the drop is immediate, the repair is not.

    Overlapping episodes add their deficits (the documented ASSUMPTION), so the assertions are
    written on the shape every episode has regardless of what else is running: health falls at
    the onset and then only ever rises until the next onset.
    """
    process, trajectories = faulted
    steps_per_day = MINUTES_PER_DAY * simulation.steps_per_minute
    for dataset, trajectory in trajectories.items():
        settings = _settings(process, dataset)
        # The wear ramp advances over the same step, so the observed fall is the fault drop
        # plus one step of wear.
        wear_step = settings["degradation_per_day"] / steps_per_day
        onsets = [fault.start_step for fault in trajectory.faults]
        for position, fault in enumerate(trajectory.faults):
            start = fault.start_step
            drop = trajectory.values[start - 1] - trajectory.values[start]
            assert 0.0 < drop <= settings["fault_health_drop"] + wear_step + 1e-12
            assert fault.drop == pytest.approx(settings["fault_health_drop"])
            next_onset = onsets[position + 1] if position + 1 < len(onsets) else fault.end_step
            recovering = trajectory.values[start : min(fault.end_step, next_onset)]
            assert (np.diff(recovering) >= 0.0).all()  # repair, never a second dip


def test_recovery_takes_the_configured_number_of_days(faulted, simulation):
    process, trajectories = faulted
    steps_per_day = MINUTES_PER_DAY * simulation.steps_per_minute
    for dataset, trajectory in trajectories.items():
        settings = _settings(process, dataset)
        expected_days = settings["fault_health_drop"] / settings["fault_recovery_per_day"]
        for fault in trajectory.faults:
            if fault.end_step >= trajectory.values.size:
                continue  # truncated by the end of the run
            assert fault.steps / steps_per_day == pytest.approx(expected_days, rel=1e-3)


def test_faults_are_rare_at_the_shipped_rate(trajectories, simulation):
    """PRD 9.5: "very occasionally". Over 90 days at least one unit must still dip."""
    assert any(trajectory.faults for trajectory in trajectories.values())
    for trajectory in trajectories.values():
        assert len(trajectory.faults) / simulation.duration_days < 0.1


def test_the_fault_mask_marks_exactly_the_fault_windows(faulted):
    _, trajectories = faulted
    for trajectory in trajectories.values():
        assert trajectory.faults
        expected = np.zeros(trajectory.values.size, dtype=bool)
        for fault in trajectory.faults:
            expected[fault.start_step : fault.end_step] = True
        assert (trajectory.fault_mask == expected).all()
        assert not trajectory.fault_mask[
            : min(fault.start_step for fault in trajectory.faults)
        ].any()


def test_a_zero_fault_rate_gives_a_purely_monotone_wear_ramp(simulation):
    process = EquipmentHealthProcess(
        simulation,
        kiln_config=_mutated(
            KILN, lambda data: data["equipment"]["health"].update(fault_rate_per_day=0.0)
        ),
    )
    trajectory = process.plan("kiln")
    assert trajectory.faults == ()
    assert (np.diff(trajectory.values) <= 0.0).all()


# =============================================================================
# The ground-truth frame (PRD 12.2 keeps these OUT of the dataset itself)
# =============================================================================
def test_the_ground_truth_frame_carries_the_scalar_and_the_flag(trajectories, simulation):
    index = simulation.run_timestamps
    for trajectory in trajectories.values():
        frame = trajectory.frame(index)
        assert list(frame.columns) == [HEALTH_COLUMN, FAULT_COLUMN]
        assert frame[HEALTH_COLUMN].to_numpy() == pytest.approx(trajectory.values)
        assert frame[FAULT_COLUMN].dtype == bool
        assert frame.index.equals(index)


def test_a_mismatched_index_is_rejected(trajectories, simulation):
    trajectory = next(iter(trajectories.values()))
    with pytest.raises(ConfigError):
        trajectory.frame(simulation.run_timestamps[:-1])


def test_describe_is_json_serializable(process, trajectories):
    payload = json.loads(json.dumps(process.describe()))
    assert set(payload) == {"kiln", "mill"}
    assert payload["kiln"]["min_health"] == 0.35
    trajectory = json.loads(json.dumps(trajectories["kiln"].describe()))
    assert trajectory["key"] == HEALTH_KEYS["kiln"]
    assert len(trajectory["faults"]) == len(trajectories["kiln"].faults)


# =============================================================================
# The twins consume it through set_health (PRD 9.5)
# =============================================================================
def test_the_planned_keys_are_the_keys_the_twin_expects(process, trajectories):
    twin = PlantTwin()
    payload = process.health_at(trajectories, 0)
    assert set(payload) == set(twin.health)
    twin.set_health(payload)
    assert twin.health == pytest.approx(payload)


def test_a_health_dip_raises_vibration_and_bearing_temperature(process, trajectories):
    """PRD 9.5: the equipment tags are functions of load *and* health.

    Settled, not stepped once: ``load_to_vibration`` and ``load_to_bearing_temperature`` carry
    the PRD 9.4 dead time and lag, so a single 60 s step would still read the reference value.
    """
    healthy = PlantTwin().to_steady_state({}, max_minutes=300)
    faulted_twin = PlantTwin()
    faulted_twin.set_health({key: 0.5 for key in faulted_twin.health})
    faulted = faulted_twin.to_steady_state({}, max_minutes=300)
    assert faulted["vibration"] > healthy["vibration"]
    assert faulted["bearing_temperature"] > healthy["bearing_temperature"]
    assert faulted["mill_vibration"] > healthy["mill_vibration"]


# =============================================================================
# Reproducibility (NFR-4)
# =============================================================================
def test_the_plan_is_a_pure_function_of_config_and_seed(simulation, trajectories):
    again = EquipmentHealthProcess(simulation).plan_all()
    for dataset, trajectory in trajectories.items():
        assert again[dataset].values == pytest.approx(trajectory.values)
        assert again[dataset].faults == trajectory.faults


def test_a_different_seed_gives_a_different_plan(simulation, trajectories):
    other = EquipmentHealthProcess(simulation.replace(seed=424242)).plan_all()
    assert other["kiln"].faults != trajectories["kiln"].faults


def test_the_two_units_draw_from_independent_substreams(simulation, trajectories):
    """NFR-4: the kiln's fault list must not depend on the mill's configuration."""
    process = EquipmentHealthProcess(
        simulation,
        mill_config=_mutated(
            MILL, lambda data: data["equipment"]["health"].update(fault_rate_per_day=5.0)
        ),
    )
    assert process.plan("kiln").faults == trajectories["kiln"].faults
    assert len(process.plan("mill").faults) > len(trajectories["mill"].faults)


def test_the_global_numpy_rng_is_never_used(simulation, trajectories):
    np.random.seed(3)
    first = EquipmentHealthProcess(simulation).plan("kiln")
    np.random.seed(4)
    second = EquipmentHealthProcess(simulation).plan("kiln")
    assert first.values == pytest.approx(second.values)
    assert first.values == pytest.approx(trajectories["kiln"].values)


def test_the_warmup_length_does_not_reshuffle_the_faults(simulation, trajectories):
    longer = EquipmentHealthProcess(simulation.replace(warmup_minutes=600.0)).plan("kiln")
    shift = int(round(600.0 - 180.0))  # dt = 60 s, so minutes are steps
    assert [f.start_step - shift for f in longer.faults] == [
        f.start_step for f in trajectories["kiln"].faults
    ]


# =============================================================================
# Config validation (NFR-6)
# =============================================================================
@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        ("a missing setting", lambda data: data["equipment"]["health"].pop("min_health")),
        (
            "a floor above the initial value",
            lambda data: data["equipment"]["health"].update(min_health=1.5),
        ),
        (
            "an initial value above 1",
            lambda data: data["equipment"]["health"].update(initial=1.2),
        ),
        (
            "a negative degradation rate",
            lambda data: data["equipment"]["health"].update(degradation_per_day=-0.1),
        ),
        (
            "a negative fault rate",
            lambda data: data["equipment"]["health"].update(fault_rate_per_day=-1.0),
        ),
        (
            "a fault that never recovers",
            lambda data: data["equipment"]["health"].update(fault_recovery_per_day=0.0),
        ),
        ("no health block at all", lambda data: data["equipment"].pop("health")),
    ],
)
def test_a_broken_health_config_is_rejected(description, mutate, simulation):
    with pytest.raises(ConfigError):
        EquipmentHealthProcess(simulation, kiln_config=_mutated(KILN, mutate))


def test_an_unknown_dataset_is_rejected(process):
    with pytest.raises(ConfigError):
        process.plan("clinker_cooler")  # type: ignore[arg-type]
