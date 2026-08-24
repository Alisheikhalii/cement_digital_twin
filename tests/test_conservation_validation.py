"""The NFR-10 residual validation methodology itself (PRD 9.3, NFR-10; SIMULATION_ASSUMPTIONS 11.5).

``test_data_generator.py`` asserts that the shipped horizon *passes* NFR-10. This module asserts
that the passing means something: that the three regimes of
:mod:`src.data_generation.conservation` are classified by cause rather than by outcome, that each
is judged by a statistic that is numerically valid there, that every bound is read from
``configs/kiln_dynamics.yaml`` instead of hard-coded, that mass conservation is untouched, and -
the point of the exercise - that a genuinely broken energy closure still fails.

The five proofs the methodology owes, and where each lives:

============================================================  ===================================
Claim                                                          Test
============================================================  ===================================
settled rows stay inside the configured +/-3 % relative bound   ``..._settled_regime_...``
transient rows are judged by the transient metric               ``..._transient_metric_...``
startup rows are judged without a near-zero denominator         ``..._startup_rows_...``
a genuine normal-operation regression still fails               ``..._broken_closure_...``,
                                                                ``..._injected_...``
no physical model assumption is changed by any of this          ``..._changes_no_physical_...``
============================================================  ===================================
"""

from __future__ import annotations

import inspect
import json

import numpy as np
import pandas as pd
import pytest

from src.config import KILN, Config, ConfigError, load_config
from src.data_generation.conservation import (
    CLOSURE_RELATIONSHIP,
    REGIMES,
    ValidationBounds,
    classify,
    conservation_report,
    moved_mask,
)
from src.data_generation.generator import DatasetGenerator
from src.simulation.simulation_config import SimulationConfig

#: ASSUMPTION test horizon: 1 day at 1 min = 1,440 exported rows. Enough for all three regimes
#: (measured on this seed: 1,010 settled / 355 transient / 75 startup) and for the transient
#: regime to contain many separate episodes, while staying cheap enough to run per-test.
HORIZON_DAYS = 1.0

#: PRD 11.2 discards the warm-up; the report judges exported rows only.
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
def horizon(generator):
    """One trajectory, reused by every test here - the loop is the expensive part."""
    schedule = generator.scheduler.build()
    state = generator.run_trajectory(schedule, generator.equipment_health.plan_all())
    return schedule, state


@pytest.fixture(scope="module")
def report(generator, horizon):
    schedule, state = horizon
    return conservation_report(generator, state=state, schedule=schedule, name="validation")


def kiln_with(**overrides) -> Config:
    """The shipped kiln config with ``energy_balance`` entries replaced (values, or ``None`` to drop).

    Used both to break the closure on purpose and to prove the validation block is inert.
    """
    data = load_config(KILN).to_dict()
    for key, value in overrides.items():
        if value is None:
            data["energy_balance"].pop(key, None)
        else:
            data["energy_balance"][key] = value
    return Config(data, source="<test override>")


# =============================================================================
# Every number is read from config, and the methodology refuses to guess
# =============================================================================
def test_every_bound_is_read_from_config(kiln_config):
    """No bound is hard-coded here or in the module: all five come from the YAML the twin runs on."""
    bounds = ValidationBounds.from_config(kiln_config)
    energy = kiln_config.get_path("energy_balance")
    validation = energy["residual_validation"]
    assert bounds.tolerance_pct == pytest.approx(
        100.0 * float(energy["unaccounted_loss_max_fraction"])
    )
    assert bounds.near_zero_input_fraction == pytest.approx(
        float(validation["near_zero_input_fraction"])
    )
    assert bounds.transient_peak_max_pct == pytest.approx(
        100.0 * float(validation["transient_peak_max_fraction"])
    )
    assert bounds.startup_reference_max_pct == pytest.approx(
        100.0 * float(validation["startup_reference_max_fraction"])
    )


def test_the_settling_window_is_derived_from_the_configured_closure_delay(kiln_config):
    """The transient window is PRD 9.4's own delay, not a tuned number (directive point 2).

    ``dead_time + n*tau`` of the relationship that carries the energy closure. Nothing about the
    window is free: change the delay in config and the window follows.
    """
    bounds = ValidationBounds.from_config(kiln_config)
    closure = kiln_config.get_path(f"delays.{CLOSURE_RELATIONSHIP}")
    expected = float(closure["dead_time_min"]) + bounds.settling_time_constants * float(
        closure["tau_min"]
    )
    assert bounds.settling_minutes == pytest.approx(expected)
    assert bounds.settling_time_constants >= 3.0  # 3*tau is 95 % of a first-order step; 4 is ~98 %


def test_a_config_without_the_validation_block_is_rejected():
    """Missing methodology is an error, never a silent default (NFR-8)."""
    with pytest.raises(ConfigError, match="residual_validation"):
        ValidationBounds.from_config(kiln_with(residual_validation=None))


def test_a_closure_delay_without_a_time_constant_is_rejected():
    data = load_config(KILN).to_dict()
    data["delays"][CLOSURE_RELATIONSHIP]["tau_min"] = None
    with pytest.raises(ConfigError, match="tau_min"):
        ValidationBounds.from_config(Config(data, source="<no tau>"))


# =============================================================================
# Classification is by cause, never by outcome
# =============================================================================
def test_the_classifier_cannot_see_the_residual_it_is_classifying():
    """Structural guard: no residual reaches ``classify``, so no row can be excused for being bad.

    The regimes are decided by the schedule (a startup label, a driven input that moved) and by
    the input basis (a numerical validity guard). None of the three residual arrays is a parameter,
    so "the residual was large" is not expressible as a reason to reclassify.
    """
    parameters = set(inspect.signature(classify).parameters)
    assert parameters == {
        "basis",
        "reference_input",
        "startup_label",
        "driven",
        "settling_rows",
        "near_zero_input_fraction",
    }
    assert not {"pct", "loss", "residual", "unaccounted"} & parameters


def test_every_row_belongs_to_exactly_one_regime(report, generator, horizon):
    """No row escapes validation, and none is judged twice."""
    schedule, state = horizon
    exported = schedule.exported(state)
    masks = classify(
        basis=exported["kiln_energy_input_MJ_per_h"].to_numpy(dtype=float),
        reference_input=report.reference_input_MJ_per_h,
        startup_label=schedule.exported(schedule.labels)["is_startup"].to_numpy(dtype=bool),
        driven=schedule.exported(schedule.inputs["kiln"]).to_numpy(dtype=float),
        settling_rows=int(round(report.settling_minutes * 60.0 / report.dt_seconds)),
        near_zero_input_fraction=report.bounds.near_zero_input_fraction,
    )
    stacked = np.vstack([masks[name] for name in REGIMES])
    assert (stacked.sum(axis=0) == 1).all()
    assert sum(report.regime(name).rows for name in REGIMES) == report.rows


def test_the_transient_window_extends_forward_only(report):
    """A move makes the rows *after* it transient; it cannot retroactively excuse the rows before.

    PRD 8.3's execution order and the closure delay both act forwards in time, so a backwards
    window would be excusing rows for a cause that had not happened yet.
    """
    driven = np.zeros((10, 1))
    driven[5:, 0] = 1.0
    extended = moved_mask(driven, settling_rows=2)
    assert list(np.flatnonzero(extended)) == [5, 6, 7]
    assert not moved_mask(driven, settling_rows=0)[6]


# =============================================================================
# Regime 1: settled operation keeps the unchanged +/-3 % relative bound
# =============================================================================
def test_the_settled_regime_is_bounded_by_the_unchanged_tolerance(
    report, kiln_energy_tolerance_pct
):
    """Directive point 1: normal operation is judged exactly as NFR-10 always judged it."""
    settled = report.regime("settled")
    assert settled.metric == "peak_relative_pct"
    assert settled.basis == "instantaneous energy input"
    assert [check.bound_pct for check in settled.checks] == [kiln_energy_tolerance_pct]
    assert settled.peak_relative_pct < kiln_energy_tolerance_pct
    assert settled.rows > 0.5 * report.rows


def test_the_settled_rows_all_have_a_denominator_worth_dividing_by(report):
    """The bound is only asserted where a percentage of the input basis is a real quantity."""
    settled = report.regime("settled")
    assert settled.minimum_basis_fraction > report.bounds.near_zero_input_fraction
    assert settled.minimum_basis_fraction > 0.5


# =============================================================================
# Regime 2: a delay transient is judged by an integral, with its peak bounded separately
# =============================================================================
def test_the_transient_metric_is_the_integral_over_the_window(
    report, kiln_energy_tolerance_pct
):
    """Directive point 2: integrated absolute residual, not the worst step of a redistribution.

    The integral is judged against the *unchanged* +/-3 %: what the configured delay moves in time
    it has to give back, so the transient regime is not a relaxation of the conservation claim -
    only of the assumption that it can be read off a single step.
    """
    transient = report.regime("transient")
    assert transient.metric == "integrated_pct"
    assert transient.integrated_pct < kiln_energy_tolerance_pct
    assert transient.worst_episode_integrated_pct < kiln_energy_tolerance_pct
    checks = {check.statistic: check for check in transient.checks}
    assert checks["integrated_pct"].bound_pct == pytest.approx(kiln_energy_tolerance_pct)
    assert checks["worst_episode_integrated_pct"].bound_pct == pytest.approx(
        kiln_energy_tolerance_pct
    )


def test_the_transient_peak_is_still_bounded_by_a_bound_of_its_own(report):
    """The regime cannot absorb an arbitrarily large excursion just by being called transient."""
    transient = report.regime("transient")
    checks = {check.statistic: check for check in transient.checks}
    assert checks["peak_relative_pct"].bound_pct == pytest.approx(
        report.bounds.transient_peak_max_pct
    )
    assert transient.peak_relative_pct < report.bounds.transient_peak_max_pct
    assert transient.peak_relative_pct > report.regime("settled").peak_relative_pct


def test_the_transient_regime_is_judged_per_episode_as_well_as_in_aggregate(report):
    """One bad ramp must not hide inside the average of the hundreds of good ones."""
    transient = report.regime("transient")
    assert transient.episodes > 10
    assert transient.worst_episode_integrated_pct > transient.integrated_pct


# =============================================================================
# Regime 3: the startup ramp is judged against a fixed, non-zero reference basis
# =============================================================================
def test_the_startup_rows_are_never_divided_by_the_collapsing_input_basis(report):
    """Directive point 3: one check, and its denominator is the reference operating point.

    The reference basis is the solved PRD 9.3 reference point's own energy input - a fixed,
    non-zero, config-derived scale, not a new coefficient - so the metric is bounded no matter how
    far the instantaneous input falls.
    """
    startup = report.regime("startup")
    assert startup.rows > 0
    assert startup.metric == "reference_relative_pct"
    assert [check.statistic for check in startup.checks] == ["reference_relative_pct"]
    assert startup.basis == "reference operating-point energy input"
    assert report.reference_input_MJ_per_h > 0.0
    assert startup.reference_relative_pct == pytest.approx(
        100.0 * startup.peak_absolute_MJ_per_h / report.reference_input_MJ_per_h
    )
    assert startup.reference_relative_pct < report.bounds.startup_reference_max_pct


def test_the_percentage_metric_is_reported_on_startup_rows_but_never_judged(
    report, kiln_energy_tolerance_pct
):
    """Why the percentage is invalid there, kept visible instead of quietly dropped.

    ``peak_relative_pct`` on the startup rows is far outside the tolerance - and that number stays
    in the report. What the methodology asserts is only that it is not the statistic the regime is
    judged on, because its denominator is a fraction of the operating point whose outputs are still
    draining. The bound it *would* fail is the very thing this test records.
    """
    startup = report.regime("startup")
    assert startup.peak_relative_pct > 10.0 * kiln_energy_tolerance_pct
    assert startup.minimum_basis_fraction < report.bounds.near_zero_input_fraction
    assert startup.peak_relative_pct > startup.reference_relative_pct
    assert startup.within_bound  # judged by the reference metric, and inside it


def test_the_near_zero_guard_only_ever_catches_rows_the_scheduler_calls_startup(
    report, generator, horizon
):
    """The numerical guard is a safety net, not a second classifier: it agrees with the labels here.

    It exists so that no future scenario can form a relative metric on a row that cannot support
    one, even outside a labelled ramp. On the shipped schedule every row it catches is already
    ``is_startup``, which is what makes the startup regime a statement about PRD 11.4's ramp.
    """
    schedule, state = horizon
    exported = schedule.exported(state)
    basis = exported["kiln_energy_input_MJ_per_h"].to_numpy(dtype=float)
    caught = basis < report.bounds.near_zero_input_fraction * report.reference_input_MJ_per_h
    labelled = schedule.exported(schedule.labels)["is_startup"].to_numpy(dtype=bool)
    assert caught.any()
    assert bool(np.all(labelled[caught]))


# =============================================================================
# A genuine regression still fails
# =============================================================================
def _with_injected_loss(state: pd.DataFrame, rows: np.ndarray, bias_MJ_per_h) -> pd.DataFrame:
    """A copy of the trajectory whose unaccounted loss is inflated on ``rows``.

    The bias is applied in the direction of the residual already there, so an injection can never
    cancel one instead of growing it, and the percentage is recomputed from the inflated numerator
    so the frame stays self-consistent - what a regression in the closure would look like in data.
    """
    frame = state.copy()
    loss = frame["kiln_unaccounted_loss_MJ_per_h"].to_numpy(dtype=float).copy()
    basis = frame["kiln_energy_input_MJ_per_h"].to_numpy(dtype=float)
    bias = np.broadcast_to(np.asarray(bias_MJ_per_h, dtype=float), loss.shape)
    direction = np.where(loss < 0.0, -1.0, 1.0)
    loss[rows] = loss[rows] + direction[rows] * np.abs(bias[rows])
    frame["kiln_unaccounted_loss_MJ_per_h"] = loss
    safe = np.where(np.abs(basis) > 0.0, basis, 1.0)
    frame["kiln_energy_pct"] = np.where(np.abs(basis) > 0.0, 100.0 * loss / safe, 0.0)
    return frame


def test_a_broken_closure_fails_the_settled_bound(simulation, kiln_energy_tolerance_pct):
    """The point of the whole exercise: the three regimes did not make the requirement toothless.

    The break is in the *physics path*, not in the report - the preheater-outlet floor of PRD 9.3's
    closure is raised above the reference outlet temperature, so the exhaust-loss term no longer
    matches what the balance computes and the closure genuinely fails during normal operation. The
    settled peak is asserted to break the unchanged tolerance, and the horizon-wide integral to
    break it too, so neither the settled nor the horizon claim can be satisfied by a broken twin.
    """
    generator = DatasetGenerator(
        simulation, kiln_config=kiln_with(min_preheater_outlet_temperature_C=450.0)
    )
    schedule = generator.scheduler.build()
    state = generator.run_trajectory(schedule, generator.equipment_health.plan_all())
    broken = conservation_report(generator, state=state, schedule=schedule, name="broken")
    assert not broken.passed
    failed = {check.statistic for check in broken.failures}
    assert "peak_relative_pct" in failed
    assert "horizon_integrated_pct" in failed
    assert broken.regime("settled").peak_relative_pct > kiln_energy_tolerance_pct
    assert not broken.regime("settled").within_bound


def test_an_injected_normal_operation_bias_fails_the_settled_regime(
    generator, horizon, report, kiln_energy_tolerance_pct
):
    """A drift that only touches normal operation is caught by the settled check alone.

    5 % of the instantaneous input on every non-startup row: comfortably inside the transient
    regime's own peak bound, so nothing but the unchanged +/-3 % relative requirement stands
    between a slow closure drift and a passing report.
    """
    schedule, state = horizon
    startup = schedule.labels["is_startup"].to_numpy(dtype=bool)
    basis = state["kiln_energy_input_MJ_per_h"].to_numpy(dtype=float)
    drifted = conservation_report(
        generator,
        state=_with_injected_loss(state, ~startup, 0.05 * basis),
        schedule=schedule,
        name="drifted",
    )
    assert not drifted.passed
    assert not drifted.regime("settled").within_bound
    assert drifted.regime("settled").peak_relative_pct > kiln_energy_tolerance_pct
    assert drifted.regime("startup").within_bound  # untouched rows still pass


def test_an_injected_startup_bias_fails_the_startup_regime(generator, horizon, report):
    """The startup regime is not a free pass: its absolute metric has a bound and it bites.

    Half the reference input basis added to the unaccounted loss of the ramp rows - a loss no
    reference-based metric can call small - fails the startup check while normal operation, which
    was not touched, still passes.
    """
    schedule, state = horizon
    startup = schedule.labels["is_startup"].to_numpy(dtype=bool)
    bias = 0.5 * report.reference_input_MJ_per_h
    broken = conservation_report(
        generator,
        state=_with_injected_loss(state, startup, np.full(startup.size, bias)),
        schedule=schedule,
        name="startup_break",
    )
    assert not broken.passed
    assert not broken.regime("startup").within_bound
    assert broken.regime("startup").reference_relative_pct > (
        broken.bounds.startup_reference_max_pct
    )
    assert broken.regime("settled").within_bound


def test_the_horizon_integral_is_judged_against_the_same_unchanged_tolerance(
    report, kiln_energy_tolerance_pct
):
    """NFR-10's "across the full simulated horizon", in the one form that is valid everywhere.

    The energy-weighted integral over *every* exported row - startup included, nothing excluded -
    against the unchanged +/-3 %. This is the statistic that keeps the horizon-wide claim intact
    while the pointwise percentage is applied only where it is defined.
    """
    check = {c.statistic: c for c in report.energy_checks}["horizon_integrated_pct"]
    assert check.bound_pct == pytest.approx(kiln_energy_tolerance_pct)
    assert check.value_pct == pytest.approx(report.horizon_integrated_pct)
    assert check.passed


# =============================================================================
# Nothing physical changed, and mass conservation is untouched
# =============================================================================
def test_the_validation_block_changes_no_physical_number(simulation, horizon):
    """The methodology only decides how a row is *judged* - it cannot move the row.

    Two proofs in one: deleting ``residual_validation`` from the config, and replacing its four
    numbers with different ones, both leave the trajectory bit-for-bit identical to the shipped
    run. So no bound in it is reachable from any equation in the twin.
    """
    _, state = horizon
    for label, override in (
        ("deleted", {"residual_validation": None}),
        (
            "different",
            {
                "residual_validation": {
                    "near_zero_input_fraction": 0.05,
                    "settling_time_constants": 9.0,
                    "transient_peak_max_fraction": 0.99,
                    "startup_reference_max_fraction": 0.99,
                }
            },
        ),
    ):
        other = DatasetGenerator(simulation, kiln_config=kiln_with(**override))
        schedule = other.scheduler.build()
        again = other.run_trajectory(schedule, other.equipment_health.plan_all())
        pd.testing.assert_frame_equal(state, again, check_exact=True, obj=label)


def test_widening_the_transient_window_cannot_rescue_a_broken_closure(simulation):
    """And the one number that *does* reach an equation is not exploitable either.

    ``settling_time_constants`` widens the transient window, which is the only lever the
    methodology has over which rows the settled bound is asserted on. With the closure broken and
    the window widened to 9*tau, the report still fails - the residual is in the integral too.
    """
    generator = DatasetGenerator(
        simulation,
        kiln_config=kiln_with(
            min_preheater_outlet_temperature_C=450.0,
            residual_validation={
                "near_zero_input_fraction": 0.30,
                "settling_time_constants": 9.0,
                "transient_peak_max_fraction": 0.20,
                "startup_reference_max_fraction": 0.60,
            },
        ),
    )
    schedule = generator.scheduler.build()
    state = generator.run_trajectory(schedule, generator.equipment_health.plan_all())
    widened = conservation_report(generator, state=state, schedule=schedule, name="widened")
    assert not widened.passed
    assert "horizon_integrated_pct" in {check.statistic for check in widened.failures}


def test_mass_conservation_keeps_its_single_unchanged_metric(
    report, kiln_mass_tolerance_pct, mill_mass_tolerance_pct
):
    """PRD 9.3/10.2 mass balances are exact discretizations, so they need no regimes at all.

    One metric, one bound per unit, every exported row - startup rows included, which is exactly
    what the energy balance cannot do and why it needed the three regimes.
    """
    assert set(report.mass_peak_pct) == {"kiln", "mill"}
    assert report.mass_bound_pct["kiln"] == pytest.approx(kiln_mass_tolerance_pct)
    assert report.mass_bound_pct["mill"] == pytest.approx(mill_mass_tolerance_pct)
    assert report.mass_peak_pct["kiln"] < 1e-6
    assert report.mass_peak_pct["mill"] < 1e-6
    assert all(check.passed for check in report.mass_checks)
    assert len(report.mass_checks) == 2


# =============================================================================
# The report itself
# =============================================================================
def test_the_report_publishes_every_statistic_and_every_check(report):
    """Nothing is hidden: the artefact figures are in the JSON next to the bounds that judge them."""
    described = report.describe()
    assert described["passed"] is True
    assert set(described["regimes"]) == set(REGIMES)
    for name in REGIMES:
        entry = described["regimes"][name]
        assert entry["checks"]
        assert {"peak_relative_pct", "integrated_pct", "reference_relative_pct"} <= set(entry)
    assert described["regimes"]["startup"]["peak_relative_pct"] > 100.0  # the artefact, on record
    assert described["failures"] == []
    assert json.loads(json.dumps(described))  # JSON-serializable as written


def test_the_report_writes_a_sidecar_and_a_readable_summary(report, tmp_path):
    target = report.to_json(tmp_path / "conservation.json")
    assert json.loads(target.read_text(encoding="utf-8"))["name"] == report.name
    summary = report.summary()
    assert "PASS" in summary
    for name in REGIMES:
        assert name in summary
    assert "mass" in summary


def test_an_unknown_regime_is_an_error(report):
    with pytest.raises(ConfigError, match="unknown validation regime"):
        report.regime("steady")


def test_the_report_refuses_a_trajectory_without_the_absolute_diagnostics(generator, horizon):
    """The startup and transient metrics need the numerator and denominator, not just the ratio."""
    schedule, state = horizon
    with pytest.raises(ConfigError, match="absolute energy diagnostics"):
        conservation_report(
            generator,
            state=state.drop(columns=["kiln_unaccounted_loss_MJ_per_h"]),
            schedule=schedule,
        )

