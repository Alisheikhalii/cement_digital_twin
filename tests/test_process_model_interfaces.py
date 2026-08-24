"""The ``ProcessUnit``/``Twin`` contract and plant composition (PRD v1.1.1 Sections 8.3-8.5).

These tests guard the seam the rest of the project is built on: What-if (16), the optimizer (14)
and the renderer (19.4) only ever call these six attributes and four methods, so a unit that
quietly stops publishing one of them would break those layers rather than this file.
"""

from __future__ import annotations

import json

import pytest

from src.process_models.interfaces import (
    ProcessUnit,
    Twin,
    UnitBase,
    is_basis_key,
    residual_entries,
    within_constraints,
)

from tests.conftest import STEP_SECONDS

ATTRIBUTES = ("state", "inputs", "outputs", "constraints", "health", "balance_residuals")


def _all_units(twin) -> list:
    """The twin plus every unit below it (the plant nests two composite twins)."""
    found = [twin]
    for unit in getattr(twin, "units", ()):
        found.extend(_all_units(unit))
    return found


@pytest.mark.parametrize("line", ["kiln", "mill", "plant"])
def test_every_unit_implements_the_process_unit_protocol(request, line):
    """PRD 8.4: the interface is mandatory for every component, not just the composites."""
    twin = request.getfixturevalue(line)
    units = _all_units(twin)
    assert len(units) > 1
    for unit in units:
        assert isinstance(unit, ProcessUnit), unit
        for attribute in ATTRIBUTES:
            value = getattr(unit, attribute)
            assert isinstance(value, dict), f"{unit.name}.{attribute}"
        assert all(isinstance(key, str) for key in unit.outputs)
        assert all(isinstance(value, float) for value in unit.outputs.values())


@pytest.mark.parametrize("line", ["kiln", "mill", "plant"])
def test_composite_twins_implement_the_twin_protocol(request, line):
    twin = request.getfixturevalue(line)
    assert isinstance(twin, Twin)
    assert isinstance(twin, UnitBase)


@pytest.mark.parametrize("line", ["kiln", "mill", "plant"])
def test_simulation_step_returns_the_published_outputs(request, line):
    """The return value and the ``outputs`` attribute must be the same numbers (PRD 8.4/8.5)."""
    twin = request.getfixturevalue(line)
    returned = twin.simulation_step({}, STEP_SECONDS)
    assert returned == twin.outputs


@pytest.mark.parametrize("line", ["kiln", "mill", "plant"])
def test_omitted_inputs_hold_rather_than_zeroing(request, line):
    """``merge_inputs``: a what-if that changes one setpoint must not zero the others."""
    twin = request.getfixturevalue(line)
    before = dict(twin.inputs)
    changed = next(iter(before))
    twin.simulation_step({changed: before[changed] * 1.01}, STEP_SECONDS)
    for key, value in before.items():
        if key != changed:
            assert twin.inputs[key] == value


@pytest.mark.parametrize("line", ["kiln", "mill", "plant"])
def test_snapshot_is_json_serializable_and_complete(request, line):
    """PRD 8.5/19.4: the renderer binds to this snapshot, so it must be plain, complete data."""
    twin = request.getfixturevalue(line)
    snapshot = twin.current_state_snapshot()
    assert set(ATTRIBUTES) <= set(snapshot) | {"state"}
    for attribute in ATTRIBUTES:
        assert attribute in snapshot
    assert snapshot["unit"] == twin.name
    assert set(snapshot["units"]) == {unit.name for unit in twin.units}
    payload = json.loads(json.dumps(snapshot))
    assert payload["outputs"] == pytest.approx(twin.outputs)


@pytest.mark.parametrize("line", ["kiln", "mill"])
def test_reset_returns_the_twin_to_the_reference_point(request, line):
    """A scenario run must be repeatable from a clean state (NFR-4)."""
    twin = request.getfixturevalue(line)
    reference_outputs = dict(twin.outputs)
    for _ in range(30):
        twin.simulation_step({key: value * 1.1 for key, value in twin.inputs.items()}, STEP_SECONDS)
    assert twin.outputs != reference_outputs
    twin.reset()
    assert twin.outputs == pytest.approx(reference_outputs)
    # Every closure error vanishes at the reference point. The basis entries are denominators of
    # the NFR-10 metric rather than residuals (PRD 8.4, ``interfaces.BASIS_SUFFIX``), so they are
    # asserted to be a usable scale instead - a zero there would be the defect.
    residuals = residual_entries(twin.balance_residuals)
    assert residuals
    assert all(abs(value) < 1e-9 for value in residuals.values())
    for key, value in twin.balance_residuals.items():
        if is_basis_key(key):
            assert value > 0.0


@pytest.mark.parametrize("line", ["kiln", "mill"])
def test_reference_point_satisfies_every_declared_constraint(request, line):
    """The nominal operating point may not sit outside the twin's own hard constraints (14.2)."""
    twin = request.getfixturevalue(line)
    report = within_constraints(twin)
    assert report, "the twin declares no constraints at all"
    assert all(report.values()), {key: value for key, value in report.items() if not value}


@pytest.mark.parametrize("line", ["kiln", "mill"])
def test_constraints_are_ranges_not_clamps(request, line):
    """PRD 11.4 needs excursions: a documented range must never silently limit the model."""
    twin = request.getfixturevalue(line)
    for bounds in twin.constraints.values():
        low, high = float(bounds[0]), float(bounds[1])
        assert low < high


def test_kiln_is_not_clamped_to_its_documented_ranges(kiln):
    """A large fuel cut must be allowed to drive BZT below its constraint band (PRD 11.4)."""
    low, _high = kiln.constraints["burning_zone_temperature"]
    for _ in range(180):
        kiln.simulation_step({"kiln_fuel_rate_tph": kiln.reference.kiln_fuel_rate_tph * 0.70}, STEP_SECONDS)
    assert kiln.outputs["burning_zone_temperature"] < float(low)
    assert not within_constraints(kiln)["burning_zone_temperature"]


# -- plant composition (PRD 8.3) -----------------------------------------------------------
def test_plant_exposes_both_lines_with_disjoint_tag_sets(plant):
    """Each PRD 12.1/12.2 tag is produced by exactly one unit, so the flat view is a union."""
    kiln_tags = set(plant.kiln.outputs)
    mill_tags = set(plant.cement_mill.outputs)
    assert not kiln_tags & mill_tags
    assert set(plant.outputs) == kiln_tags | mill_tags


def test_plant_state_keys_are_namespaced_per_line(plant):
    """Both lines hold states of the same name; the plant view must keep them apart."""
    assert all(key.startswith(("Kiln.", "CementMill.")) for key in plant.state)
    assert len(plant.state) == len(plant.kiln.state) + len(plant.cement_mill.state)


def test_plant_residuals_carry_both_closures(plant):
    """PRD 9.3 + 10.2: the plant reports each line's closure and the worse of the two."""
    residuals = plant.balance_residuals
    assert {"kiln_energy_pct", "kiln_mass_pct", "mill_mass_pct", "energy_pct", "mass_pct"} <= set(
        residuals
    )
    plant.simulation_step({"kiln_fuel_rate_tph": plant.kiln.reference.kiln_fuel_rate_tph * 1.1}, STEP_SECONDS)
    residuals = plant.balance_residuals
    assert residuals["energy_pct"] == residuals["kiln_energy_pct"]
    assert abs(residuals["mass_pct"]) == max(
        abs(residuals["kiln_mass_pct"]), abs(residuals["mill_mass_pct"])
    )


def test_plant_does_not_couple_the_kiln_to_the_mill(plant):
    """PRD 8.3: independent, buffered clinker supply - tight coupling is a Phase-2 item (32).

    A large kiln disturbance must leave the mill line bit-for-bit identical to a mill that never
    saw it; if a future change introduces clinker coupling, this test is where it must be argued.
    """
    from src.process_models.mill import CementMillTwin

    alone = CementMillTwin()
    step = {"kiln_fuel_rate_tph": plant.kiln.reference.kiln_fuel_rate_tph * 1.25}
    for _ in range(60):
        plant.simulation_step(step, STEP_SECONDS)
        alone.simulation_step({}, STEP_SECONDS)
    assert plant.cement_mill.outputs == alone.outputs
    # ... while the kiln line did move.
    assert plant.outputs["burning_zone_temperature"] > plant.kiln.reference.burning_zone_temperature_C


def test_plant_health_is_dispatched_to_the_owning_line(plant):
    """PRD 9.5: one health dictionary, two owners, no cross-talk."""
    plant.set_health({"kiln": 0.75, "mill": 0.55})
    assert plant.kiln.health["kiln"] == 0.75
    assert plant.cement_mill.health["mill"] == 0.55
    assert plant.kiln.rotary_kiln.health["kiln"] == 0.75
    assert plant.cement_mill.mill.health["mill"] == 0.55


def test_plant_scenario_frame_carries_every_tag_and_residual(plant, step_trajectory):
    """One rollout must serve both datasets and the conservation report (PRD 8.4/11)."""
    frame = plant.simulate_scenario(
        step_trajectory(
            {
                "kiln_fuel_rate_tph": plant.kiln.reference.kiln_fuel_rate_tph,
                "mill_feed_rate_tph": plant.cement_mill.reference.feed_rate_tph,
            },
            {"mill_feed_rate_tph": plant.cement_mill.reference.feed_rate_tph * 1.05},
            hold_minutes=10,
            step_minutes=30,
        ),
        STEP_SECONDS,
    )
    assert len(frame) == 40
    assert set(plant.outputs) <= set(frame.columns)
    for column in (
        "energy_balance_residual_pct",
        "mass_balance_residual_pct",
        "kiln_mass_balance_residual_pct",
        "mill_mass_balance_residual_pct",
    ):
        assert column in frame.columns
        assert frame[column].notna().all()
