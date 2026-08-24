"""Section 34 tests for the Model C layer: PRD 14 (optimization) and PRD 16 (what-if).

Three rules hold everywhere in this module, and they are the reason several tests are shaped the
way they are rather than the obvious way:

*No test hard-codes a bound it checks.* Every limit is read back out of ``configs/*.yaml`` through
the fixtures, so NFR-10 cannot be relaxed by editing a test instead of a config.

*No test asserts on a particular winning move.* The fixture models are freshly fitted on a short
synthetic run, so the winner legitimately differs from the one a notebook run picks. What is
asserted is always a *property* of whatever won - inside the envelope, inside the mode's change
limit, gated, explained - never its identity.

*A test that widens or tightens a threshold says so and does it in memory.* Directive item 16
forbids tuning a constraint after seeing a result; an in-memory :class:`~src.config.Config` built
for one test is not a config change, and each one below states what it is proving.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd
import pytest

from src.config import Config, ConfigError
from src.features.lag_features import FeatureBuilder, lag_column
from src.labels import (
    AI_RECOMMENDATION_LABEL,
    CONSTRAINT_STATUS_VALUES,
    DECISION_SUPPORT_LABEL,
    ENVELOPE_STATUS_VALUES,
    FORBIDDEN_CONTROL_LABEL,
    NO_SAFE_RECOMMENDATION,
    OUTSIDE_ENVELOPE_BANNER,
    RECOMMENDATION_QUALITY_VALUES,
    RULE_BASED_SUGGESTION_LABEL,
    SIMULATED_SAVING_CAVEAT,
    SYNTHETIC_DEMONSTRATION_LABEL,
)
from src.optimization.baselines import (
    BASELINE_AI,
    BASELINE_BEST_COMPARABLE,
    BASELINE_CURRENT,
    BASELINE_HISTORICAL,
    BASELINE_NAMES,
    BASELINE_TWIN_RULES,
)
from src.optimization.envelope import (
    CHECK_FEATURE_SPACE,
    CHECK_HARD_CONSTRAINTS,
    CHECK_MAX_CHANGE,
    CHECK_OPERATING_RANGE,
    FLAG_SOURCE_UNAVAILABLE,
    STATE_FAIL,
    STATE_NOT_EVALUATED,
    STATE_PASS,
)
from src.optimization.objective import (
    ELECTRIC_TAG,
    TERM_ELECTRIC,
    TERM_EMISSION,
    TERM_PRODUCTION,
    TERM_QUALITY,
    TERM_STABILITY,
    TERM_THERMAL,
    THERMAL_TAG,
)
from src.optimization.optimizer import (
    GATE_ANOMALY,
    GATE_ENVELOPE,
    GATE_MODEL_AVAILABILITY,
    GATE_UNCERTAINTY,
    ORIGIN_GRID,
    ORIGIN_HOLD,
    ORIGIN_POLISH,
    ORIGIN_RANDOM,
    ORIGIN_WHAT_IF,
)
from src.optimization.prediction import (
    PredictionBundle,
    feature_row,
    objective_targets,
    relative_uncertainty_pct,
    uncertainty_limit_pct,
)
from src.optimization.recommendation import (
    SOURCE_MEASURED,
    SOURCE_MODEL_A,
    SOURCE_OPTIMIZER,
    SOURCE_SIMULATOR_TRUTH,
    SOURCE_TWIN_SIMULATION,
)
from src.optimization.what_if import HOLD_REQUEST, WhatIfEngine

#: The six PRD 16.1 manipulated variables, in the order ``configs/optimization.yaml`` declares them.
PRD_16_1_VARIABLES = (
    "kiln_fuel_rate_tph",
    "ID_fan_speed",
    "kiln_feed_rate_tph",
    "kiln_speed_rpm",
    "separator_speed_rpm",
    "mill_feed_rate_tph",
)

#: The PRD 14.2 hard-constraint tags that are not equipment limits.
PRD_14_2_PROCESS_TAGS = (
    "clinker_production_tph",
    "burning_zone_temperature",
    "oxygen_percent",
    "CO_ppm",
    "simulated_blaine_cm2_g",
    "residue_percent",
)

#: The four PRD 14.3 checks, in the order the PRD numbers them.
PRD_14_3_CHECKS = (
    CHECK_OPERATING_RANGE,
    CHECK_FEATURE_SPACE,
    CHECK_HARD_CONSTRAINTS,
    CHECK_MAX_CHANGE,
)

#: The ten elements PRD 16.3 requires a what-if panel to show.
PRD_16_3_PANEL_ELEMENTS = (
    "baseline_state",
    "requested_change",
    "predicted_process_response",
    "energy_impact",
    "production_impact",
    "quality_impact",
    "uncertainty",
    "constraint_status",
    "envelope_status",
    "recommendation_status",
)

#: NFR-2's budget for "a single what-if scenario simulate+predict+optimize round trip", in seconds.
#: Quoted from the PRD rather than measured: the point of the test is the requirement, and the
#: measured position of the *full search* against the same number is recorded as a documented
#: deviation in ``configs/optimization.yaml`` instead of being asserted here.
NFR_2_ROUND_TRIP_SECONDS = 3.0

#: The three constraint statuses and two envelope statuses, unpacked from :mod:`src.labels` so a
#: test never spells one of them differently from the platform.
STATUS_PASS, STATUS_REJECTED, STATUS_FLAGGED = CONSTRAINT_STATUS_VALUES
WITHIN_ENVELOPE, OUTSIDE_ENVELOPE = ENVELOPE_STATUS_VALUES


@dataclass(frozen=True)
class StubAnomalyReport:
    """The Model B report surface :func:`~src.optimization.optimizer._as_reports` reads.

    A stub rather than a fitted detector on purpose: the gate under test is "what does Model C do
    when Model B says X", and driving that from a real detector would mean engineering a synthetic
    fault first and testing two layers at once. Model B's own behaviour has its own module.
    """

    dataset: str = "kiln"
    status: str = "ANOMALY"
    hypothesis: str = "test hypothesis"
    is_anomaly: bool = True
    flagged: bool = True
    out_of_distribution: bool = False


def override(config: Config, path: str, value: Any) -> Config:
    """A copy of ``config`` with one dotted path replaced - in memory, never on disk.

    Used only where a test has to prove what happens *at* a threshold (an impossible quality window,
    a zero uncertainty ceiling, an exhausted solve budget). The shipped YAML is untouched, which is
    what keeps directive item 16 - "do not tune constraints after seeing results" - checkable.
    """
    payload = config.to_dict()
    target = payload
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    return Config(payload, source=f"<override {path}>")


def impossible_quality_window(config: Config) -> Config:
    """``configs/optimization.yaml`` with a Blaine window nothing can satisfy - in memory only.

    The reference operating point settles at exactly the configured 3400 cm2/g target, so moving the
    target to 3000 with a 1 cm2/g tolerance is the smallest change that makes *every* candidate,
    including holding the current setpoints, fail check 3. That is the only way to exercise "the
    optimizer found nothing safe" without touching physics (directive item 15) or the shipped
    thresholds (item 16): the refusal is manufactured by an obviously impossible spec, and the
    behaviour under test is what the platform does when it cannot recommend anything.
    """
    tightened = override(config, "targets.blaine_target_cm2_g", 3000.0)
    return override(tightened, "targets.blaine_tolerance_cm2_g", 1.0)


class UnmeasurableSpreadBundle:
    """A real :class:`PredictionBundle` whose spreads have been replaced by NaN.

    The point is *not* a fake model: value, family, version, quality and the training domain all
    still come from the fitted bundle, so check 1 and the availability gate see exactly what they
    would normally see. Only the ensemble spread is made unmeasurable, which is the one branch of
    the uncertainty gate a fitted model cannot be talked into producing - and the branch whose
    documented behaviour ("an unmeasured uncertainty is not a small one") is the interesting one.
    """

    def __init__(self, bundle: PredictionBundle) -> None:
        self._bundle = bundle

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bundle, name)

    def predict(self, **kwargs: Any) -> tuple[Any, ...]:
        return tuple(
            replace(prediction, uncertainty=float("nan"))
            for prediction in self._bundle.predict(**kwargs)
        )


def keys_of(payload: Any) -> set[str]:
    """Every mapping key anywhere in a nested payload - for the "no invented percentage" check."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(str(key))
            found |= keys_of(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found |= keys_of(item)
    return found


def round_tripped(payload: Any) -> Any:
    """The payload as JSON sees it - so "identical" means identical after serialization too."""
    return json.loads(json.dumps(payload, default=str, sort_keys=True))


class TestDecisionSpace:
    """PRD 16.1 / NFR-11: the controllable variables and what each one must declare."""

    def test_exactly_the_six_prd_16_1_variables(self, optimizer):
        assert optimizer.space.names == PRD_16_1_VARIABLES

    def test_every_variable_documents_range_step_and_ramp(self, optimizer):
        for record in optimizer.space.describe()["variables"]:
            low, high = record["range"]
            assert low < high, record["name"]
            assert record["unit"]
            assert record["ramp_minutes"] > 0.0, record["name"]
            steps = (record["step_absolute"], record["step_pct_of_current"])
            assert sum(step is not None for step in steps) == 1, record["name"]
            assert record["range_basis"] in ("absolute_range", "ratio_of_reference")

    def test_ratio_bounds_resolve_against_the_twins_reference_point(
        self, optimizer, optimization_config
    ):
        """A fuel bound is a ratio of the solved reference rate, not an absolute t/h figure."""
        variable = optimizer.space["kiln_fuel_rate_tph"]
        low, high = optimization_config.get_path(
            "decision_variables.kiln_fuel_rate_tph.ratio_of_reference"
        )
        reference = optimizer.twin.kiln.reference.kiln_fuel_rate_tph
        assert variable.reference_value == pytest.approx(reference)
        assert variable.minimum == pytest.approx(float(low) * reference)
        assert variable.maximum == pytest.approx(float(high) * reference)

    def test_mode_bounds_are_the_range_intersected_with_the_change_limit(
        self, optimizer, optimizer_inputs
    ):
        space = optimizer.space
        baseline = space.baseline(optimizer_inputs)
        for mode in ("NORMAL", "EXPERIMENTAL"):
            span = space.max_delta_fraction(mode)
            for name, current in baseline.items():
                low, high = space.bounds(name, current, mode)
                variable = space[name]
                assert low >= variable.minimum - 1e-9
                assert high <= variable.maximum + 1e-9
                assert low >= current - abs(current) * span - 1e-9
                assert high <= current + abs(current) * span + 1e-9
        assert space.max_delta_fraction("EXPERIMENTAL") > space.max_delta_fraction("NORMAL")

    def test_snap_to_step_keeps_an_out_of_range_request_reachable(self, optimizer):
        """PRD 16.1 wants an out-of-range request *rejected with an explanation*, not clipped."""
        variable = optimizer.space["kiln_feed_rate_tph"]
        wild = variable.maximum + 37.4
        snapped = variable.snap_to_step(wild, variable.maximum)
        assert snapped > variable.maximum
        assert not variable.contains(snapped)
        assert variable.snap(wild, variable.maximum) == pytest.approx(variable.maximum)

    def test_unknown_variable_and_unknown_mode_are_refused(self, optimizer):
        with pytest.raises(KeyError):
            optimizer.space["kiln_pressure_bar"]
        with pytest.raises(ValueError):
            optimizer.space.max_delta_fraction("YOLO")


class TestConstraintSeparation:
    """Directive item 4: objective, hard constraints, soft preferences and gates are separate."""

    def test_no_hard_constraint_tag_is_an_objective_weight(self, optimizer):
        weights = dict(optimizer.objective.weights)
        assert set(weights) == {
            TERM_THERMAL,
            TERM_ELECTRIC,
            TERM_PRODUCTION,
            TERM_QUALITY,
            TERM_STABILITY,
            TERM_EMISSION,
        }
        assert not set(weights) & set(optimizer.constraints.tags)

    def test_every_prd_14_2_process_tag_is_a_hard_constraint(self, optimizer):
        tags = set(optimizer.constraints.tags)
        assert set(PRD_14_2_PROCESS_TAGS) <= tags

    def test_equipment_limits_are_hard_constraints_with_their_own_basis(
        self, optimizer, optimization_config
    ):
        from src.optimization.constraints import BASIS_EQUIPMENT

        limits = optimization_config.get_path("hard_constraints.equipment_limits")
        for tag in limits:
            spec = optimizer.constraints.spec_of(tag)
            assert spec is not None, tag
            assert spec.basis == BASIS_EQUIPMENT
            assert spec.maximum == pytest.approx(float(limits.get_path(f"{tag}.max")))

    def test_production_bound_is_derived_from_target_and_tolerance(
        self, optimizer, optimization_config
    ):
        target = float(optimization_config.get_path("targets.production_target_tph"))
        tolerance = float(optimization_config.get_path("targets.production_tolerance_fraction"))
        spec = optimizer.constraints.spec_of("clinker_production_tph")
        assert spec.minimum == pytest.approx(target * (1.0 - tolerance))

    def test_a_violation_is_named_with_its_tag_and_its_band(self, optimizer, normal_result):
        doctored = dict(normal_result.baseline.state)
        doctored["burning_zone_temperature"] = 1500.0
        report = optimizer.constraints.evaluate(doctored)
        assert not report.satisfied
        assert "burning_zone_temperature" in {item.tag for item in report.violations}
        assert "burning_zone_temperature" in report.reason()

    def test_an_unevaluated_constraint_is_not_a_pass(self, optimizer):
        """PRD 30: nothing is presented as safe on the strength of a limit nobody checked."""
        report = optimizer.constraints.evaluate({})
        assert not report.satisfied
        assert len(report.unevaluated) == len(optimizer.constraints.specs)
        assert not report.violations

    def test_soft_penalties_are_zero_inside_the_comfort_band(self, optimizer):
        """PRD 14.2: a soft penalty rises only as a candidate *approaches* a hard bound."""
        spec = optimizer.constraints.spec_of("burning_zone_temperature")
        centre = (spec.minimum + spec.maximum) / 2.0
        assert optimizer.objective.approach_penalty(spec, centre) == pytest.approx(0.0)
        margin = optimizer.objective.soft_margin_fraction
        half = (spec.maximum - spec.minimum) / 2.0
        near = spec.maximum - half * margin * 0.25
        assert optimizer.objective.approach_penalty(spec, near) > 0.0


class TestEnvelopeGating:
    """PRD 14.3's five ordered checks, and directive items 1-3: gate *before* accepting anything."""

    def test_the_four_checks_are_present_numbered_and_ordered(self, normal_result):
        checks = normal_result.baseline.envelope.checks
        assert tuple(check.name for check in checks) == PRD_14_3_CHECKS
        assert tuple(check.number for check in checks) == (1, 2, 3, 4)

    def test_a_setpoint_outside_the_recorded_training_range_fails_check_one(self, optimizer):
        ranges = optimizer.validator.training_ranges
        assert ranges, "the fixture optimizer must carry recorded training ranges"
        tag = next(iter(sorted(ranges)))
        low, high = optimizer.validator.range_of(tag)
        outcome = optimizer.validator.check_operating_range({tag: high + (high - low) + 1.0})
        assert outcome.state == STATE_FAIL
        assert outcome.number == 1
        assert tag in outcome.reason

    def test_an_absurd_feature_row_fails_the_ood_check(self, optimizer, normal_result):
        sane = dict(normal_result.baseline.state)
        outcome, ratio = optimizer.validator.check_feature_space(sane)
        assert outcome.number == 2
        absurd = {tag: value * 1000.0 + 1.0e6 for tag, value in sane.items()}
        rejected, absurd_ratio = optimizer.validator.check_feature_space(absurd)
        assert rejected.state == STATE_FAIL
        assert "isolation forest" in rejected.reason.lower() or "score" in rejected.reason.lower()
        assert absurd_ratio is not None and ratio is not None
        # ood_ratio is 0 at the training median and 1 at the rejection threshold, so "further out"
        # is a *larger* ratio.
        assert absurd_ratio > ratio

    def test_without_model_b_check_two_is_unevaluated_and_nothing_reaches_a_full_pass(
        self, make_optimizer, optimizer_inputs, optimization_history
    ):
        """Directive item 3: an unavailable check is disclosed, never assumed to have passed."""
        blind = make_optimizer(scorer=None, reference_scores=None)
        assessment = blind.assess_setpoints(
            proposed={}, inputs=optimizer_inputs, history=optimization_history
        )
        report = assessment.candidate.envelope
        assert report.check(CHECK_FEATURE_SPACE).state == STATE_NOT_EVALUATED
        assert report.constraint_status == STATUS_FLAGGED
        assert report.flag_threshold_source == FLAG_SOURCE_UNAVAILABLE
        assert not report.accepted

    def test_an_oversized_move_is_refused_before_the_twin_is_solved(
        self, optimizer, optimizer_inputs, optimization_history
    ):
        """PRD 14.3's order is load-bearing: checks 1 and 4 are cheap, so they run first."""
        baseline = optimizer.space.baseline(optimizer_inputs)
        proposed = {"kiln_fuel_rate_tph": baseline["kiln_fuel_rate_tph"] * 1.40}
        assessment = optimizer.assess_setpoints(
            proposed=proposed, inputs=optimizer_inputs, history=optimization_history
        )
        candidate = assessment.candidate
        report = candidate.envelope
        assert candidate.state is None, "no solve may be spent on an inadmissible candidate"
        assert report.check(CHECK_MAX_CHANGE).state == STATE_FAIL
        assert report.check(CHECK_HARD_CONSTRAINTS).state == STATE_NOT_EVALUATED
        assert report.check(CHECK_FEATURE_SPACE).state == STATE_NOT_EVALUATED
        assert report.constraint_status == STATUS_REJECTED
        assert not candidate.accepted

    def test_every_accepted_candidate_stays_inside_the_decision_ranges(self, normal_result, optimizer):
        assert normal_result.accepted_candidates
        for candidate in normal_result.accepted_candidates:
            for name, value in candidate.setpoints.items():
                variable = optimizer.space[name]
                assert variable.contains(value), f"{name}={value} outside {variable.describe()}"

    def test_every_accepted_candidate_stays_inside_the_recorded_training_ranges(
        self, normal_result, optimizer
    ):
        """Directive item 1, checked on the setpoints themselves rather than on a status string."""
        checked = 0
        for candidate in normal_result.accepted_candidates:
            for name, value in candidate.setpoints.items():
                window = optimizer.validator.range_of(name)
                if window is None:
                    continue
                low, high = window
                assert low <= value <= high, f"{name}={value} outside training range {window}"
                checked += 1
        assert checked, "no decision variable had a recorded training range to check against"

    def test_every_accepted_candidate_respects_the_mode_change_limit(
        self, normal_result, optimizer, optimizer_inputs
    ):
        limit = optimizer.space.max_delta_fraction(normal_result.mode)
        baseline = optimizer.space.baseline(optimizer_inputs)
        for candidate in normal_result.accepted_candidates:
            for name, fraction in candidate.delta_fractions.items():
                assert abs(fraction) <= limit + 1e-9, f"{name} moved {fraction:+.4f}"
                assert candidate.setpoints[name] == pytest.approx(
                    baseline[name] * (1.0 + fraction), rel=1e-6, abs=1e-9
                )


class TestRunLevelGates:
    """Directive item 3's four blocking conditions, one class per condition below this docstring."""

    def test_an_active_anomaly_blocks_the_whole_run(
        self, optimizer, optimizer_inputs, optimization_history
    ):
        result = optimizer.optimize(
            inputs=optimizer_inputs,
            history=optimization_history,
            anomaly=StubAnomalyReport(),
        )
        gate = result.gate(GATE_ANOMALY)
        assert gate.state == STATE_FAIL and gate.blocking
        assert result.no_safe_recommendation
        assert result.recommendation is None
        assert result.message.startswith(NO_SAFE_RECOMMENDATION)
        assert GATE_ANOMALY in result.blocked_by
        assert result.winner is None
        assert len(result.candidates) == 1, "no candidate is generated over an open anomaly"

    def test_a_merely_flagged_report_is_reported_but_does_not_block(
        self, optimizer, optimizer_inputs, optimization_history
    ):
        """PRD 30: a non-blocking Isolation-Forest flag is shown, not promoted into a veto."""
        assessment = optimizer.assess_setpoints(
            proposed={},
            inputs=optimizer_inputs,
            history=optimization_history,
            anomaly=StubAnomalyReport(status="NORMAL", is_anomaly=False, flagged=True),
        )
        gate = assessment.gate(GATE_ANOMALY)
        assert gate.state == STATE_PASS
        assert not gate.blocking
        assert "flag" in gate.reason

    def test_an_absent_model_b_report_is_declared_unevaluated(self, normal_result):
        gate = normal_result.gate(GATE_ANOMALY)
        assert gate.state == STATE_NOT_EVALUATED
        assert not gate.blocking
        assert GATE_ANOMALY not in normal_result.blocked_by

    def test_missing_model_a_blocks_every_recommendation(
        self, make_optimizer, optimizer_inputs, optimization_history
    ):
        blind = make_optimizer(predictions=None)
        result = blind.optimize(inputs=optimizer_inputs, history=optimization_history)
        gate = result.gate(GATE_MODEL_AVAILABILITY)
        assert gate.state == STATE_FAIL and gate.blocking
        assert result.recommendation is None
        assert result.no_safe_recommendation
        assert result.message.startswith(NO_SAFE_RECOMMENDATION)

    def test_a_dataset_without_model_a_is_frozen_rather_than_optimized_blind(
        self, make_optimizer, optimization_predictions, optimizer_inputs, optimization_history
    ):
        kiln_only = make_optimizer(predictions={"kiln": optimization_predictions["kiln"]})
        result = kiln_only.optimize(inputs=optimizer_inputs, history=optimization_history)
        gate = result.gate(GATE_MODEL_AVAILABILITY)
        assert gate.state == STATE_PASS and not gate.blocking
        assert gate.detail["frozen"] == ["mill"]
        mill_variables = {
            variable.name for variable in kiln_only.space if variable.dataset == "mill"
        }
        baseline = kiln_only.space.baseline(optimizer_inputs)
        for candidate in result.candidates:
            for name in mill_variables:
                assert candidate.setpoints[name] == pytest.approx(baseline[name])

    def test_the_envelope_gate_names_the_absence_of_a_survivor(
        self, make_optimizer, optimization_config, optimizer_inputs, optimization_history
    ):
        """Directive item 17: an impossible quality window returns a refusal, not a relaxed window.

        The Blaine window is moved off the plant *in memory* purely to manufacture "nothing passes"
        (see :func:`impossible_quality_window`). It proves the refusal path; it changes no shipped
        number, and the last two assertions below are what keep that honest.
        """
        impossible = make_optimizer(config=impossible_quality_window(optimization_config))
        result = impossible.optimize(inputs=optimizer_inputs, history=optimization_history)
        assert result.recommendation is None
        assert result.no_safe_recommendation
        assert result.message.startswith(NO_SAFE_RECOMMENDATION)
        assert GATE_ENVELOPE in result.blocked_by
        assert not result.accepted_candidates
        assert result.rejected_candidates, "the refusal must still show what was tried"
        assert impossible.constraints.spec_of("simulated_blaine_cm2_g").maximum == pytest.approx(
            3001.0
        ), "the override, not the shipped config, is what made this run impossible"
        assert float(
            optimization_config.get_path("targets.blaine_tolerance_cm2_g")
        ) > 1.0, "the shipped tolerance must be untouched by the override"

    def test_no_weight_vector_can_buy_a_hard_constraint_violation(
        self, make_optimizer, optimization_config, optimizer_inputs, optimization_history
    ):
        """PRD 14.2: hard constraints "can never be traded away for a better objective score"."""
        impossible = make_optimizer(config=impossible_quality_window(optimization_config))
        baseline = impossible.space.baseline(optimizer_inputs)
        proposed = {"kiln_fuel_rate_tph": baseline["kiln_fuel_rate_tph"] * 0.95}
        fuzzed = (
            {TERM_THERMAL: 1.0e6},
            {TERM_QUALITY: 0.0},
            {TERM_QUALITY: 0.0, TERM_PRODUCTION: 0.0, TERM_EMISSION: 0.0},
            {name: 0.0 for name in impossible.objective.weights},
        )
        for weights in fuzzed:
            assessment = impossible.assess_setpoints(
                proposed=proposed,
                inputs=optimizer_inputs,
                history=optimization_history,
                weights=weights,
            )
            assert assessment.candidate.constraint_status == STATUS_REJECTED, weights
            assert not assessment.candidate.accepted, weights
            assert not assessment.accepted, weights


class TestUncertaintyGating:
    """Directive items 3 and 8: too-wide spread blocks, and no percentage is invented to say so."""

    def test_the_ceiling_and_its_scope_are_read_from_ml_config(self, normal_result, ml_config):
        gate = normal_result.gate(GATE_UNCERTAINTY)
        assert gate.detail["limit_pct"] == pytest.approx(uncertainty_limit_pct(ml_config))
        assert gate.detail["limit_source"] == (
            "configs/ml.yaml recommendation_quality.medium.max_relative_uncertainty_pct"
        )
        assert tuple(gate.detail["objective_targets"]) == objective_targets(ml_config)
        assert gate.state in (STATE_PASS, STATE_FAIL, STATE_NOT_EVALUATED)

    def test_the_gate_invents_no_confidence_percentage(self, normal_result):
        """Directive item 8: Model A's own spread, never a manufactured confidence number."""
        gate = normal_result.gate(GATE_UNCERTAINTY)
        assert not any("confidence" in key for key in keys_of(gate.detail))
        assert not any("probability" in key for key in keys_of(gate.detail))
        for entry in gate.detail["wide_predictions"]:
            assert set(entry) == {"target", "horizon_min", "relative_spread_pct"}

    def test_the_blocking_claim_is_never_wider_than_the_reported_spread(
        self, optimizer, optimizer_inputs, optimization_history
    ):
        """The documented claim/report split: the gate blocks on a subset of what it shows."""
        baseline = optimizer.space.baseline(optimizer_inputs)
        assessment = optimizer.assess_setpoints(
            proposed=baseline, inputs=optimizer_inputs, history=optimization_history
        )
        spread = assessment.uncertainty
        assert spread.targets == objective_targets()
        assert spread.claim_pct is not None and spread.worst_pct is not None
        assert spread.claim_pct <= spread.worst_pct + 1e-9
        assert spread.claim_pct == pytest.approx(
            relative_uncertainty_pct(assessment.predictions, targets=spread.targets)
        )

    def test_a_zero_ceiling_refuses_every_recommendation(
        self, make_optimizer, ml_config, optimizer_inputs, optimization_history
    ):
        """Directive item 3: "predicted uncertainty is too high" must be able to stop a run.

        The ceiling is driven to 0 % *in memory* so that any measurable spread exceeds it. The
        shipped 8 % is asserted untouched below; nothing about the model or the plant changes.
        """
        strict = make_optimizer(
            ml_config=override(
                ml_config, "recommendation_quality.medium.max_relative_uncertainty_pct", 0.0
            )
        )
        result = strict.optimize(inputs=optimizer_inputs, history=optimization_history)
        gate = result.gate(GATE_UNCERTAINTY)
        assert gate.state == STATE_FAIL
        assert gate.blocking
        assert "ceiling" in gate.reason
        assert GATE_UNCERTAINTY in result.blocked_by
        assert result.recommendation is None
        assert result.no_safe_recommendation
        assert result.message.startswith(NO_SAFE_RECOMMENDATION)
        assert uncertainty_limit_pct(ml_config) == pytest.approx(8.0), "shipped ceiling untouched"

    def test_an_unmeasurable_spread_is_not_treated_as_a_small_one(
        self, make_optimizer, optimization_predictions, optimizer_inputs, optimization_history
    ):
        """A candidate whose spread cannot be read is refused, not waved through."""
        blinded = make_optimizer(
            predictions={
                dataset: UnmeasurableSpreadBundle(bundle)
                for dataset, bundle in optimization_predictions.items()
            }
        )
        assessment = blinded.assess_setpoints(
            proposed=blinded.space.baseline(optimizer_inputs),
            inputs=optimizer_inputs,
            history=optimization_history,
        )
        gate = assessment.gate(GATE_UNCERTAINTY)
        assert assessment.predictions, "the models still answered; only the spread is unreadable"
        assert assessment.uncertainty.claim_pct is None
        assert gate.state == STATE_NOT_EVALUATED
        assert gate.blocking
        assert "unmeasured uncertainty is not a small one" in gate.reason
        assert not assessment.accepted

    def test_without_history_model_a_cannot_be_consulted_and_that_blocks(
        self, optimizer, optimizer_inputs
    ):
        """Directive item 3: "required prediction models are unavailable" - here, for want of lags."""
        assessment = optimizer.assess_setpoints(
            proposed=optimizer.space.baseline(optimizer_inputs),
            inputs=optimizer_inputs,
            history=None,
        )
        gate = assessment.gate(GATE_UNCERTAINTY)
        assert not assessment.predictions
        assert gate.state == STATE_NOT_EVALUATED
        assert gate.blocking
        assert "cannot be presented as safe" in gate.reason
        assert not assessment.accepted

    def test_the_gate_scope_must_stay_the_two_prd_14_2_energy_terms(
        self, make_optimizer, ml_config
    ):
        """The claim/report split is a documented deviation, so its scope is not free to drift.

        ``uncertainty.optimizer_targets`` is simultaneously the objective's energy terms and the
        gate's scope. Narrowing it to something else would silently narrow what the gate checks, so
        the objective refuses to build at all rather than let the two definitions separate.
        """
        with pytest.raises(ConfigError, match="optimizer_targets"):
            make_optimizer(
                ml_config=override(
                    ml_config, "uncertainty.optimizer_targets", ["burning_zone_temperature"]
                )
            )
        assert set(objective_targets(ml_config)) == {THERMAL_TAG, ELECTRIC_TAG}


class TestReproducibility:
    """Directive item 13: the optimizer is deterministic and reproducible."""

    def test_two_independent_runs_agree_field_for_field(
        self, make_optimizer, optimizer_inputs, optimization_history, normal_result
    ):
        """Not the same object re-read: a second optimizer, a second twin, a second search."""
        second = make_optimizer().optimize(
            inputs=optimizer_inputs, history=optimization_history, mode="NORMAL"
        )
        assert round_tripped(second.signature()) == round_tripped(normal_result.signature())
        assert second.solves == normal_result.solves
        assert second.evaluated == normal_result.evaluated
        assert [item.action() for item in second.candidates] == [
            item.action() for item in normal_result.candidates
        ]

    def test_only_the_wall_clock_is_excluded_from_the_signature(self, normal_result):
        described = normal_result.describe()
        signed = normal_result.signature()
        assert normal_result.NON_REPRODUCIBLE_FIELDS == ("runtime_s",)
        assert set(described) - set(signed) == {"runtime_s"}
        assert described["runtime_s"] >= 0.0

    def test_the_random_candidate_draw_is_seeded(self, optimizer, normal_result):
        """The sampled part of the search is reproducible for a stated reason, not by luck."""
        assert optimizer.search["random_state"] == 42
        drawn = [item for item in normal_result.candidates if item.origin == ORIGIN_RANDOM]
        assert drawn, "the search must actually have drawn candidates for this to mean anything"
        assert len(drawn) <= optimizer.search["n_random_candidates"], "no draw is added twice"

    def test_a_repeated_what_if_is_bit_identical(
        self, what_if_engine, optimizer_inputs, optimization_history
    ):
        """PRD 16.2's consistency guarantee has to survive being asked twice."""
        first = what_if_engine.run(
            inputs=optimizer_inputs,
            history=optimization_history,
            delta_fractions={"kiln_fuel_rate_tph": -0.03},
        )
        again = what_if_engine.run(
            inputs=optimizer_inputs,
            history=optimization_history,
            delta_fractions={"kiln_fuel_rate_tph": -0.03},
        )
        assert round_tripped(again.signature()) == round_tripped(first.signature())
        assert first.NON_REPRODUCIBLE_FIELDS == (
            ("assessment", "unit_solves"),
            ("assessment", "candidate", "unit_solves"),
        )
        # The excluded field is the *cost*, and the two runs genuinely differ in it: the engine
        # keeps its memo warm across requests, so the repeat is free.
        assert first.describe()["assessment"]["unit_solves"] > 0
        assert again.describe()["assessment"]["unit_solves"] == 0


class TestNoFutureData:
    """Directive items 9-11: only the past, only published tags, and each labelled for what it is."""

    def test_every_lag_feature_comes_from_a_strictly_earlier_row(self, optimization_history):
        """A marker frame makes leakage arithmetically visible.

        Each numeric column is overwritten with its own row *position*, so a feature's value is a
        statement about which row it was read from. A feature built from a future row would carry a
        marker above the last position; a feature built from the wrong past row would carry the
        wrong one. Both are checked, per lag, rather than trusting the builder's intent.
        """
        spec = FeatureBuilder("kiln").spec(30)
        marker = optimization_history.copy()
        for column in marker.columns:
            marker[column] = range(len(marker))
        last = len(marker) - 1
        row = feature_row(spec, history=marker, sustained=False)

        checked = 0
        for base in spec.base_columns:
            for lag in spec.lags_min:
                column = lag_column(base, lag)
                if column not in row.columns:
                    continue
                expected = last - spec.lag_steps(lag)
                assert float(row.iloc[0][column]) == pytest.approx(expected), column
                assert float(row.iloc[0][column]) <= last, f"{column} read a future row"
                checked += 1
        assert checked, "the marker frame proved nothing if no lag column was compared"
        assert row.index[-1] == marker.index[-1]

    def test_a_history_too_short_for_its_lags_is_an_error_not_a_guess(self, optimization_history):
        spec = FeatureBuilder("kiln").spec(30)
        with pytest.raises(ValueError):
            feature_row(spec, history=optimization_history.iloc[0:0], sustained=False)
        with pytest.raises(ValueError):
            feature_row(
                spec,
                history=optimization_history.iloc[: spec.max_lag_steps],
                sustained=False,
            )

    def test_the_run_is_stamped_with_the_last_observed_timestamp(
        self, normal_result, optimization_history
    ):
        assert normal_result.timestamp == optimization_history.index[-1]

    def test_the_observed_point_is_the_last_sensor_row_not_the_simulator(
        self, normal_result, optimization_history
    ):
        """Directive items 10-11: the optimizer reads published tags, and says so."""
        recommendation = normal_result.recommendation
        assert recommendation is not None
        last = optimization_history.iloc[-1]
        assert recommendation.observed_state
        for tag, value in recommendation.observed_state.items():
            assert value == pytest.approx(float(last[tag])), tag
        assert recommendation.state_sources["observed_state"] == SOURCE_MEASURED
        assert recommendation.state_sources["baseline_state"] == SOURCE_TWIN_SIMULATION
        assert recommendation.state_sources["proposed_state"] == SOURCE_TWIN_SIMULATION
        assert recommendation.state_sources["predicted_state_by_horizon"] == SOURCE_MODEL_A
        assert recommendation.state_sources["proposed_setpoints"] == SOURCE_OPTIMIZER
        assert recommendation.state_sources["objective_breakdown"] == SOURCE_OPTIMIZER
        assert SOURCE_SIMULATOR_TRUTH not in recommendation.state_sources.values()
        # Every state the recommendation carries is labelled - none may be left unattributed.
        assert set(recommendation.state_sources).issuperset(
            {"observed_state", "baseline_state", "proposed_state", "expected_impact"}
        )

    def test_no_payload_anywhere_claims_simulator_ground_truth(self, normal_result):
        """The label exists so the distinction is expressible; nothing Model C emits may use it."""
        payload = json.dumps(round_tripped(normal_result.describe()))
        assert SOURCE_SIMULATOR_TRUTH not in payload
        assert SOURCE_MEASURED in payload and SOURCE_TWIN_SIMULATION in payload

    def test_a_run_without_a_historian_falls_back_and_labels_the_fallback(
        self, optimizer, optimizer_inputs
    ):
        """No history means no sensor row - and the substitute is named, not disguised."""
        assessment = optimizer.assess_setpoints(
            proposed=optimizer.space.baseline(optimizer_inputs), inputs=optimizer_inputs
        )
        assert assessment.recommendation.state_sources["observed_state"] == SOURCE_TWIN_SIMULATION


class TestBaselines:
    """Directive item 12 / PRD 14.5: the five comparison rows, over one shared metric set."""

    def test_all_five_prd_14_5_rows_are_present_and_named(self, normal_result):
        comparison = normal_result.baselines
        assert comparison is not None
        assert tuple(item.name for item in comparison.rows) == BASELINE_NAMES
        for item in comparison.rows:
            assert item.title and item.detail, item.name
            assert item.source in (SOURCE_MEASURED, SOURCE_TWIN_SIMULATION)

    def test_every_row_reports_the_same_metric_set(self, normal_result, optimization_config):
        comparison = normal_result.baselines
        configured = tuple(str(tag) for tag in optimization_config.get_path("baselines.metrics"))
        assert comparison.metrics == configured
        for row in comparison.table():
            for tag in configured:
                assert tag in row, f"{row['name']} is missing {tag}"

    def test_the_measured_rows_are_measured_and_the_modelled_rows_are_not(self, normal_result):
        """Directive item 11 again, where it matters most: a saving argument mixes both kinds."""
        comparison = normal_result.baselines
        assert comparison.row(BASELINE_CURRENT).source == SOURCE_MEASURED
        assert comparison.row(BASELINE_HISTORICAL).source == SOURCE_MEASURED
        assert comparison.row(BASELINE_BEST_COMPARABLE).source == SOURCE_MEASURED
        assert comparison.row(BASELINE_TWIN_RULES).source == SOURCE_TWIN_SIMULATION
        assert comparison.row(BASELINE_AI).source == SOURCE_TWIN_SIMULATION

    def test_the_ai_row_is_the_recommendation_itself(self, normal_result):
        """The comparison may not quote a different operating point than the one recommended."""
        recommendation = normal_result.recommendation
        assert recommendation is not None
        ai = normal_result.baselines.row(BASELINE_AI)
        assert ai.available
        assert ai.setpoints == pytest.approx(recommendation.proposed_setpoints)
        for tag, value in ai.metrics.items():
            if value is not None and tag in recommendation.proposed_state:
                assert value == pytest.approx(recommendation.proposed_state[tag]), tag

    def test_the_current_row_is_the_measured_point(self, normal_result, optimization_history):
        current = normal_result.baselines.row(BASELINE_CURRENT)
        last = optimization_history.iloc[-1]
        assert current.available
        for tag, value in current.metrics.items():
            if value is not None:
                assert value == pytest.approx(float(last[tag])), tag

    def test_a_delta_is_signed_against_the_current_point_by_default(self, normal_result):
        comparison = normal_result.baselines
        deltas = comparison.delta(BASELINE_AI)
        assert set(deltas) == set(comparison.metrics)
        current = comparison.row(BASELINE_CURRENT)
        ai = comparison.row(BASELINE_AI)
        for tag, item in deltas.items():
            left, right = current.value_of(tag), ai.value_of(tag)
            if left is None or right is None:
                assert item.delta is None, tag
            else:
                assert item.delta == pytest.approx(right - left), tag

    def test_best_on_reads_the_table_rather_than_asserting_the_ai_row_wins(self, normal_result):
        """Directive item 18: the comparison has to be able to say the AI row is *not* the best."""
        comparison = normal_result.baselines
        winner = comparison.best_on(THERMAL_TAG)
        assert winner in comparison.available
        values = {
            item.name: item.value_of(THERMAL_TAG)
            for item in comparison.rows
            if item.available and item.value_of(THERMAL_TAG) is not None
        }
        assert values[winner] == pytest.approx(min(values.values()))
        assert comparison.best_on("no_such_tag") is None

    def test_the_comparison_carries_the_synthetic_caveat(self, normal_result):
        """Directive items 7 and 20: a saving table is never presented as a real-world saving."""
        comparison = normal_result.baselines
        assert comparison.caveat == SIMULATED_SAVING_CAVEAT
        assert comparison.describe()["caveat"] == SIMULATED_SAVING_CAVEAT

    def test_a_missing_historian_is_reported_not_silently_zeroed(
        self, optimizer, optimizer_inputs
    ):
        """PRD 30: an unavailable baseline says so; it does not become a zero to compare against."""
        result = optimizer.optimize(inputs=optimizer_inputs, history=None)
        comparison = result.baselines
        assert comparison is not None
        assert not comparison.complete
        assert BASELINE_HISTORICAL in comparison.missing
        assert BASELINE_BEST_COMPARABLE in comparison.missing
        for name in comparison.missing:
            row = comparison.row(name)
            assert row.detail, name
            assert all(value is None for value in row.metrics.values()), name
        assert tuple(item["name"] for item in comparison.table()) == BASELINE_NAMES


#: Five what-if scenarios, one per family of controllable variable named in the Task 5 directive:
#: kiln fuel, the kiln ID fan, the kiln feed/speed pair, the separator, and the mill feed. All are
#: inside Normal Mode's 10 % change limit, so any refusal would be a verdict rather than a bound.
WHAT_IF_SCENARIOS: dict[str, dict[str, float]] = {
    "kiln_fuel_-3pct": {"kiln_fuel_rate_tph": -0.03},
    "id_fan_+4pct": {"ID_fan_speed": 0.04},
    "kiln_feed_-2pct_speed_+2pct": {"kiln_feed_rate_tph": -0.02, "kiln_speed_rpm": 0.02},
    "separator_+5pct": {"separator_speed_rpm": 0.05},
    "mill_feed_-2pct": {"mill_feed_rate_tph": -0.02},
}


@pytest.fixture(scope="session")
def what_if_examples(what_if_engine, optimizer_inputs, optimization_history):
    """The five scenarios, answered once and shared - a round trip each is the expensive part."""
    return {
        name: what_if_engine.run(
            inputs=optimizer_inputs, history=optimization_history, delta_fractions=deltas
        )
        for name, deltas in WHAT_IF_SCENARIOS.items()
    }


@pytest.fixture(scope="session")
def fuel_cut(what_if_examples):
    """The reference scenario for the panel-shape tests: kiln fuel -3 % in Normal Mode."""
    return what_if_examples["kiln_fuel_-3pct"]


class TestWhatIf:
    """Directive items 5-6 and PRD 16: the controllable variables, and what a result must show."""

    def test_the_engine_offers_exactly_the_prd_16_1_sliders(self, what_if_engine, optimizer_inputs):
        assert what_if_engine.variables() == PRD_16_1_VARIABLES
        for name in PRD_16_1_VARIABLES:
            current = what_if_engine.space.baseline(optimizer_inputs)[name]
            slider = what_if_engine.slider(name, current)
            low, high = what_if_engine.space.bounds(name, current, "NORMAL")
            assert slider["minimum"] == pytest.approx(low)
            assert slider["maximum"] == pytest.approx(high)
            assert slider["step"] > 0.0
            assert slider["unit"]
            assert slider["absolute_range"] == [
                what_if_engine.space[name].minimum,
                what_if_engine.space[name].maximum,
            ]

    def test_every_directive_item_5_variable_family_is_answered_not_ignored(self, what_if_examples):
        """Fuel, ID fan, kiln feed/speed, separator, mill feed - each gets a verdict and a panel.

        Deliberately *not* "each is accepted". One of the five moves the kiln speed, whose recorded
        training range is narrower than its own slider step at the reference point, so Normal Mode
        refuses it at check 1 - which is the envelope gate working, not a failure to answer. What
        every family must have is a full evaluation and an explained verdict.
        """
        assert len(what_if_examples) == 5
        for name, result in what_if_examples.items():
            assert result.moved() == tuple(WHAT_IF_SCENARIOS[name]), name
            assert result.constraint_status in CONSTRAINT_STATUS_VALUES, name
            assert result.envelope_status in ENVELOPE_STATUS_VALUES, name
            assert result.recommendation.explanation(), name
            assert set(result.panel()).issuperset(PRD_16_3_PANEL_ELEMENTS), name
            if not result.simulated:
                assert result.assessment.candidate.state is None, name
                assert result.assessment.candidate.envelope.failures, (
                    f"{name} was not simulated, so some PRD 14.3 check has to say why"
                )

    def test_the_five_scenarios_produce_both_an_accepted_and_a_refused_answer(
        self, what_if_examples
    ):
        """Directive item 18: the engine must be able to demonstrate both outcomes."""
        statuses = {name: result.constraint_status for name, result in what_if_examples.items()}
        assert STATUS_PASS in statuses.values(), statuses
        assert STATUS_REJECTED in statuses.values(), statuses
        for name, result in what_if_examples.items():
            if result.constraint_status == STATUS_REJECTED:
                assert not result.accepted, name
                assert result.recommendation.explanation(), name

    def test_the_panel_carries_all_ten_prd_16_3_elements(self, fuel_cut):
        """Directive item 6, element for element - nothing folded into something else."""
        panel = fuel_cut.panel()
        assert set(panel).issuperset(PRD_16_3_PANEL_ELEMENTS)
        assert panel["baseline_state"] and panel["requested_change"]
        assert panel["predicted_process_response"]["settled_state"]
        assert panel["predicted_process_response"]["by_horizon"]
        assert panel["energy_impact"]["savings_line"]
        assert panel["production_impact"] and panel["quality_impact"]
        assert panel["uncertainty"]["limit_pct"] > 0.0
        assert panel["constraint_status"] in CONSTRAINT_STATUS_VALUES
        assert panel["envelope_status"] in ENVELOPE_STATUS_VALUES
        assert panel["recommendation_status"]["recommendation_quality"] in (
            RECOMMENDATION_QUALITY_VALUES
        )
        assert panel["recommendation_status"]["explanation"]

    def test_the_panel_reports_spread_and_never_a_confidence_percentage(self, fuel_cut):
        """Directive item 8: Model A's own numbers, under names that say what they are."""
        panel = fuel_cut.panel()
        keys = keys_of(panel)
        assert not any("confidence" in key for key in keys)
        assert not any("probability" in key for key in keys)
        assert set(panel["uncertainty"]) >= {
            "relative_uncertainty_pct",
            "limit_pct",
            "gate_targets",
            "gate_spread_pct",
            "wide_predictions",
        }

    def test_the_process_response_is_delayed_rather_than_instantaneous(self, fuel_cut, optimization_config):
        """PRD 16.2: the panel must show the real dead time + lag, not a step change."""
        transition = fuel_cut.transition
        assert transition is not None
        hold = float(optimization_config.get_path("what_if.hold_minutes"))
        assert transition.hold_minutes == pytest.approx(hold)
        delay = transition.response_delay_minutes("burning_zone_temperature")
        assert delay is not None and delay > 0.0
        ramp = transition.ramp_minutes["kiln_fuel_rate_tph"]
        assert delay > ramp, (
            "a response that reaches half travel no later than the setpoint ramp would be an "
            "instantaneous jump, which is exactly what PRD 16.2 forbids showing"
        )

    def test_the_two_routes_to_the_endpoint_are_compared_not_assumed(self, fuel_cut, optimization_config):
        """The ramped trajectory and the settled solve are computed differently and reconciled."""
        tolerance = float(optimization_config.get_path("what_if.endpoint_tolerance_relative"))
        assert fuel_cut.endpoint_tolerance == pytest.approx(tolerance)
        assert fuel_cut.endpoint_agreement is not None
        if fuel_cut.endpoint_converged:
            assert fuel_cut.endpoint_agreement <= tolerance
        else:
            assert any("still in motion" in note for note in fuel_cut.notes())

    def test_holding_the_current_setpoints_is_a_legitimate_question(
        self, what_if_engine, optimizer_inputs, optimization_history
    ):
        """"What if we change nothing?" is answered, not rejected as an empty request."""
        result = what_if_engine.run(inputs=optimizer_inputs, history=optimization_history)
        assert result.moved() == ()
        assert result.action() == HOLD_REQUEST
        assert result.simulated
        assert result.recommendation is not None
        assert set(result.panel()).issuperset(PRD_16_3_PANEL_ELEMENTS)

    def test_an_oversized_normal_mode_request_is_refused_with_an_explanation(
        self, what_if_engine, optimizer_inputs, optimization_history
    ):
        """+40 % in Normal Mode: refused before any solve, and told which checks refused it.

        Requirement 3's "materially different from the training distribution" case. The engine
        deliberately does *not* quietly pull the request back to the 10 % bound - a silently clipped
        answer would look like an answer to the question that was asked.
        """
        result = what_if_engine.run(
            inputs=optimizer_inputs,
            history=optimization_history,
            delta_fractions={"kiln_fuel_rate_tph": 0.40},
        )
        report = result.assessment.candidate.envelope
        assert report.check(CHECK_MAX_CHANGE).state == STATE_FAIL
        assert report.check(CHECK_OPERATING_RANGE).state == STATE_FAIL
        assert not result.simulated
        assert result.assessment.candidate.state is None
        assert result.transition is None
        assert result.envelope_status == OUTSIDE_ENVELOPE
        assert result.banner == OUTSIDE_ENVELOPE_BANNER
        assert not result.accepted
        assert "40.00 %" in result.action()
        assert result.recommendation.explanation()

    def test_a_slider_caller_may_clip_and_the_clip_is_always_reported(
        self, what_if_engine, optimizer_inputs, optimization_history
    ):
        """``clip_to_bounds`` is the PRD 17 slider's opt-in - and PRD 30 forbids hiding it."""
        result = what_if_engine.run(
            inputs=optimizer_inputs,
            history=optimization_history,
            delta_fractions={"kiln_fuel_rate_tph": 0.40},
            clip_to_bounds=True,
        )
        moved = next(item for item in result.request if item.name == "kiln_fuel_rate_tph")
        assert moved.clipped
        assert moved.value < moved.requested
        assert moved.value == pytest.approx(moved.bounds[1])
        assert result.simulated, "a clipped request is inside the mode bound, so it can be solved"
        assert any("clipped" in note for note in result.notes())
        assert f"{moved.requested:.4g}" in result.notes()[0], (
            "the note has to say what was asked for, not only what was simulated"
        )
        assert result.panel()["requested_change"]

    def test_experimental_mode_may_leave_the_envelope_but_must_flag_it(
        self, what_if_engine, optimizer_inputs, optimization_history
    ):
        """PRD 16.1: Experimental Mode widens the limit and stops enforcing - it never hides."""
        kwargs = {
            "inputs": optimizer_inputs,
            "history": optimization_history,
            "delta_fractions": {"kiln_fuel_rate_tph": 0.25},
        }
        experimental = what_if_engine.run(**kwargs, mode="EXPERIMENTAL")
        normal = what_if_engine.run(**kwargs, mode="NORMAL")
        assert experimental.simulated, "Experimental Mode answers the question it was asked"
        assert experimental.envelope_status == OUTSIDE_ENVELOPE
        assert experimental.banner == OUTSIDE_ENVELOPE_BANNER
        assert not experimental.accepted, "flagged is not the same as accepted"
        assert GATE_ENVELOPE in experimental.assessment.blocked_by
        assert not normal.simulated, "the same request in Normal Mode is refused, not flagged"
        assert normal.assessment.candidate.envelope.check(CHECK_MAX_CHANGE).state == STATE_FAIL

    def test_an_impossible_or_unknown_request_is_an_error_not_a_guess(
        self, what_if_engine, optimizer_inputs, optimization_history
    ):
        """A request the engine cannot interpret is refused loudly rather than half-honoured."""
        with pytest.raises(ValueError, match="both an absolute target and a delta fraction"):
            what_if_engine.run(
                inputs=optimizer_inputs,
                history=optimization_history,
                changes={"kiln_fuel_rate_tph": 6.0},
                delta_fractions={"kiln_fuel_rate_tph": -0.02},
            )
        with pytest.raises(KeyError, match="not a PRD 16.1 manipulated variable"):
            what_if_engine.run(
                inputs=optimizer_inputs,
                history=optimization_history,
                delta_fractions={"kiln_shell_temperature": 0.01},
            )

    def test_a_recommendation_replayed_as_a_what_if_reproduces_it(
        self, what_if_engine, optimizer_inputs, optimization_history, normal_result
    ):
        """AC-8: the optimizer's answer and the manual what-if of that answer must agree."""
        recommended = normal_result.recommendation
        assert recommended is not None
        replayed = what_if_engine.replay(
            recommended, inputs=optimizer_inputs, history=optimization_history
        ).recommendation
        assert replayed.mode == recommended.mode
        assert replayed.proposed_setpoints == pytest.approx(recommended.proposed_setpoints)
        assert replayed.delta_fractions == pytest.approx(recommended.delta_fractions)
        assert replayed.proposed_state == pytest.approx(recommended.proposed_state)
        assert replayed.constraint_status == recommended.constraint_status
        assert replayed.envelope_status == recommended.envelope_status
        assert replayed.recommendation_quality == recommended.recommendation_quality
        assert replayed.expected_impact.describe() == recommended.expected_impact.describe()

    def test_the_savings_line_never_claims_a_real_world_saving(self, fuel_cut):
        """Directive items 7 and 20, in the one sentence a demo audience is most likely to quote."""
        line = fuel_cut.savings_line()
        assert SIMULATED_SAVING_CAVEAT in line
        assert fuel_cut.panel()["energy_impact"]["caveat"] == SIMULATED_SAVING_CAVEAT
        assert fuel_cut.recommendation.label == AI_RECOMMENDATION_LABEL


def quiet_state(engine: Any) -> dict[str, float]:
    """A state built *from the configured thresholds* so that, by construction, no rule fires.

    Written this way rather than as literals so the state stays quiet if a threshold is ever
    retuned: every tag sits mid-band for two-sided rules and half-way to the limit for one-sided
    ones. Rule 1 of this module - no test hard-codes a bound it checks.
    """
    limits = engine.thresholds
    return {
        "oxygen_percent": (limits["oxygen_low_pct"] + limits["oxygen_high_pct"]) / 2.0,
        "CO_ppm": limits["CO_high_ppm"] / 2.0,
        "burning_zone_temperature": (
            limits["burning_zone_low_C"] + limits["burning_zone_high_C"]
        ) / 2.0,
        "simulated_blaine_cm2_g": (
            limits["blaine_low_cm2_g"] + limits["blaine_high_cm2_g"]
        ) / 2.0,
        "mill_differential_pressure": (
            limits["mill_differential_pressure_low_mbar"]
            + limits["mill_differential_pressure_high_mbar"]
        ) / 2.0,
        "vibration": limits["vibration_high_mm_s"] / 2.0,
        "bearing_temperature": limits["bearing_temperature_high_C"] / 2.0,
    }


class TestRuleEngine:
    """PRD 14.6: the transparent fallback, and directive item 12's rule-based baseline."""

    def test_every_threshold_and_step_is_a_config_key(self, optimizer, optimization_config):
        """NFR-10: nothing in the rule table is written in Python."""
        engine = optimizer.rule_engine
        assert engine.thresholds == pytest.approx(
            optimization_config.get_path("rule_engine.thresholds").to_dict()
        )
        assert engine.actions == pytest.approx(
            optimization_config.get_path("rule_engine.actions").to_dict()
        )
        for rule in engine.rules:
            assert rule.threshold_key in engine.thresholds, rule.identifier
            assert rule.step_key in engine.actions, rule.identifier
            assert rule.variable in optimizer.space.names, rule.identifier
            assert rule.rationale, rule.identifier

    def test_a_state_inside_every_threshold_proposes_a_hold_and_says_so(
        self, optimizer, optimizer_inputs
    ):
        engine = optimizer.rule_engine
        state = quiet_state(engine)
        setpoints = optimizer.space.baseline(optimizer_inputs)
        report = engine.evaluate(state, setpoints, previous_state=state)
        assert report.unevaluated_tags == (), "every rule's tag was supplied, so all are evaluated"
        assert report.is_hold
        assert report.applied == ()
        assert report.proposed_setpoints == pytest.approx(dict(report.baseline_setpoints))
        assert report.label == RULE_BASED_SUGGESTION_LABEL
        assert report.suggestion().startswith(RULE_BASED_SUGGESTION_LABEL)
        assert "no rule threshold is exceeded" in report.suggestion()

    def test_a_low_oxygen_state_fires_its_documented_rule_within_the_mode_limit(
        self, optimizer, optimizer_inputs
    ):
        """PRD 14.6's oxygen floor: more induced draught, by the configured step, never past it."""
        engine = optimizer.rule_engine
        state = quiet_state(engine)
        state["oxygen_percent"] = engine.thresholds["oxygen_low_pct"] - 0.5
        report = engine.evaluate(
            state, optimizer.space.baseline(optimizer_inputs), previous_state=state
        )
        assert [item.rule.identifier for item in report.applied] == ["oxygen_low"]
        finding = report.applied[0]
        assert finding.variable == "ID_fan_speed"
        assert finding.step_fraction == pytest.approx(engine.actions["id_fan_step_fraction"])
        assert finding.proposed > finding.current, "the fan has to actually move for this to help"
        low, high = optimizer.space.bounds("ID_fan_speed", finding.current, "NORMAL")
        assert low <= finding.proposed <= high
        assert not report.is_hold
        assert "oxygen_percent" in finding.reason()
        assert RULE_BASED_SUGGESTION_LABEL in report.suggestion()

    def test_safety_outranks_efficiency_and_the_outranked_rule_is_still_reported(
        self, optimizer, optimizer_inputs
    ):
        """Two rules want the ID fan in opposite directions; the loser is suppressed, not hidden."""
        engine = optimizer.rule_engine
        state = quiet_state(engine)
        state["CO_ppm"] = engine.thresholds["CO_high_ppm"] * 1.5
        state["oxygen_percent"] = engine.thresholds["oxygen_high_pct"] + 0.5
        report = engine.evaluate(
            state, optimizer.space.baseline(optimizer_inputs), previous_state=state
        )
        applied = [item.rule.identifier for item in report.applied]
        suppressed = {item.rule.identifier: item.suppressed_by for item in report.suppressed}
        assert "co_high" in applied
        assert suppressed.get("oxygen_high") == "co_high"
        assert "oxygen_high" not in applied
        assert "Suppressed by the higher-priority rule co_high" in report.reason()
        assert report.proposed_setpoints["ID_fan_speed"] > report.baseline_setpoints["ID_fan_speed"]

    def test_the_one_derivative_rule_reports_itself_unevaluated_without_a_previous_state(
        self, optimizer, optimizer_inputs
    ):
        """"No rule fired" and "nobody could tell" are different statements (PRD 14.6)."""
        engine = optimizer.rule_engine
        setpoints = optimizer.space.baseline(optimizer_inputs)
        state = quiet_state(engine)
        blind = engine.evaluate(state, setpoints)
        rising = {item.rule.identifier: item.state for item in blind.findings}
        assert rising["co_rising"] == "NOT_EVALUATED"
        assert "dCO_ppm/dt" in blind.unevaluated_tags
        assert blind.is_hold
        assert "could not be checked" in blind.suggestion()

        rate = engine.thresholds["CO_rising_ppm_per_min"] * 1.2
        previous = dict(state)
        previous["CO_ppm"] = state["CO_ppm"] - rate  # one minute earlier, so d/dt = rate
        seen = engine.evaluate(state, setpoints, previous_state=previous, interval_min=1.0)
        assert [item.rule.identifier for item in seen.applied] == ["co_rising"]
        assert seen.unevaluated_tags == ()

    def test_the_rule_engine_is_the_non_ai_baseline_of_the_comparison(self, normal_result):
        """PRD 14.5 item 4: the AI point is compared against what if/else alone would have done."""
        rules = normal_result.rules
        row = normal_result.baselines.row(BASELINE_TWIN_RULES)
        assert rules.label == RULE_BASED_SUGGESTION_LABEL
        assert row.available
        assert row.source == SOURCE_TWIN_SIMULATION
        assert row.setpoints == pytest.approx(dict(rules.proposed_setpoints))
        assert row.detail == rules.suggestion()


class TestCandidateEvaluation:
    """PRD 14.1's pipeline per candidate: solve, gate, and only then score."""

    def test_unit_composition_matches_plant(
        self, make_optimizer, optimizer_inputs, optimization_history
    ):
        """PRD 8.3 decouples kiln and mill, so a mill-only move must not re-solve the kiln.

        This is the assertion ``configs/optimization.yaml`` cites for its search sizing: the whole
        candidate budget is affordable only because one candidate costs one solve per *affected*
        unit, and that is measured here rather than assumed. A fresh optimizer is built so the
        memo starts cold - the session-scoped one has a warm cache by construction.
        """
        optimizer = make_optimizer()
        units = dict.fromkeys(variable.dataset for variable in optimizer.space)
        assert len(units) > 1, "a single-unit twin would make this test vacuous"
        baseline = optimizer.space.baseline(optimizer_inputs)
        common = {"inputs": optimizer_inputs, "history": optimization_history}

        hold = optimizer.assess_setpoints(proposed=dict(baseline), **common)
        assert hold.solves == len(units), "the do-nothing point costs exactly one solve per unit"

        # One mill variable and one kiln variable, both chosen because they are *solvable* from the
        # reference point: a candidate refused at check 1 never reaches the twin, so it would count
        # zero solves and prove nothing. (`separator_speed_rpm` is exactly that case here - see
        # `TestTrainingRangeHeadroom` - which is why the mill move is the feed.)
        mill_variable = "mill_feed_rate_tph"
        assert optimizer.space[mill_variable].dataset == "mill"
        mill_only = dict(baseline)
        mill_only[mill_variable] = baseline[mill_variable] * 1.02
        moved_mill = optimizer.assess_setpoints(proposed=mill_only, **common)
        assert moved_mill.candidate.setpoints[mill_variable] != baseline[mill_variable]
        assert moved_mill.candidate.state is not None, "this move has to reach the twin at all"
        assert moved_mill.solves == 1, "moving the mill re-solves the mill and nothing else"

        kiln_variable = "ID_fan_speed"
        assert optimizer.space[kiln_variable].dataset == "kiln"
        kiln_only = dict(baseline)
        kiln_only[kiln_variable] = baseline[kiln_variable] * 1.04
        moved_kiln = optimizer.assess_setpoints(proposed=kiln_only, **common)
        assert moved_kiln.candidate.setpoints[kiln_variable] != baseline[kiln_variable]
        assert moved_kiln.candidate.state is not None
        assert moved_kiln.solves == 1, "moving the kiln re-solves the kiln and nothing else"

        assert optimizer.assess_setpoints(proposed=mill_only, **common).solves == 0

    def test_the_hold_candidate_is_the_baseline_and_is_evaluated_like_any_other(
        self, normal_result, optimizer, optimizer_inputs
    ):
        """"Do nothing" is a candidate, not an exception - it is gated and scored the same way."""
        first = normal_result.candidates[0]
        assert first.origin == ORIGIN_HOLD
        assert first is normal_result.baseline
        assert first.setpoints == pytest.approx(optimizer.space.baseline(optimizer_inputs))
        assert len(first.envelope.checks) == len(PRD_14_3_CHECKS)
        assert first.action() == HOLD_REQUEST

    def test_the_objective_is_the_configured_weighted_sum_of_the_six_terms(
        self, normal_result, optimization_config
    ):
        """PRD 14.4: six named terms, each weighted by config, and a total that is their sum."""
        objective = normal_result.winner.objective
        assert objective is not None
        # ``objective.weights`` is keyed ``w_thermal`` in the config and ``thermal`` on the term,
        # so the prefix is stripped here rather than the term names being restated as literals.
        weights = {
            str(key).removeprefix("w_"): float(value)
            for key, value in optimization_config.get_path("objective.weights").to_dict().items()
        }
        assert dict(objective.weights) == pytest.approx(weights)
        assert {term.name for term in objective.terms} == {
            TERM_THERMAL,
            TERM_ELECTRIC,
            TERM_PRODUCTION,
            TERM_QUALITY,
            TERM_STABILITY,
            TERM_EMISSION,
        }
        for term in objective.terms:
            assert term.weight == pytest.approx(weights[term.name]), term.name
            assert term.weighted == pytest.approx(term.weight * term.value), term.name
            assert term.detail, term.name
        assert objective.total == pytest.approx(sum(term.weighted for term in objective.terms))
        breakdown = objective.breakdown
        assert breakdown["total"] == pytest.approx(objective.total)
        assert set(breakdown) == {term.name for term in objective.terms} | {"total"}

    def test_the_winner_is_the_best_scoring_accepted_candidate(self, normal_result):
        """Lower is better, ties go to the earlier candidate, and no rejected candidate can win."""
        accepted = normal_result.accepted_candidates
        assert normal_result.winner in accepted
        assert normal_result.winner.score == pytest.approx(
            min(candidate.score for candidate in accepted)
        )
        assert all(candidate.score is None for candidate in normal_result.rejected_candidates)
        if normal_result.baseline.score is not None:
            assert normal_result.improvement() == pytest.approx(
                normal_result.baseline.score - normal_result.winner.score
            )
            assert normal_result.improvement() >= 0.0, (
                "the hold is itself a candidate, so the winner can never be worse than holding"
            )

    def test_every_candidate_carries_its_origin_and_its_own_verdict(self, normal_result):
        origins = {candidate.origin for candidate in normal_result.candidates}
        assert origins <= {ORIGIN_HOLD, ORIGIN_GRID, ORIGIN_RANDOM, ORIGIN_POLISH, ORIGIN_WHAT_IF}
        assert ORIGIN_HOLD in origins and ORIGIN_GRID in origins
        assert len(normal_result.candidates) == normal_result.evaluated
        for candidate in normal_result.candidates:
            states = {check.name: check.state for check in candidate.envelope.checks}
            assert tuple(states) == PRD_14_3_CHECKS, candidate.origin
            if candidate.accepted:
                assert set(states.values()) == {STATE_PASS}
                assert candidate.settled and candidate.state is not None
            else:
                assert candidate.score is None


class TestTrainingRangeHeadroom:
    """PRD 14.3 check 1 uses the *recorded* training range, which can be narrower than the step.

    This is a property of the platform worth pinning down rather than a defect: the synthetic run
    barely varied some setpoints, so the validated envelope around the reference point is narrower
    than one slider step for those variables. The required behaviour is then a refusal with a
    reason - never a quiet round into a region no model was trained on.
    """

    def test_check_one_uses_the_recorded_range_and_not_the_configured_range(self, optimizer):
        recorded = optimizer.validator.training_ranges
        checked = 0
        for variable in optimizer.space:
            window = optimizer.validator.range_of(variable.name)
            if window is None:
                continue
            checked += 1
            low, high = window
            assert variable.minimum <= low <= high <= variable.maximum, variable.name
            outside = high + (high - low + 1.0)  # inside no recorded range, whatever the data
            assert (
                optimizer.validator.check_operating_range({variable.name: outside}).state
                == STATE_FAIL
            ), variable.name
        assert checked, "no decision variable has a recorded range - check 1 would be vacuous"
        assert set(recorded) >= {variable.name for variable in optimizer.space if recorded}

    def test_a_variable_with_less_headroom_than_its_step_is_refused_not_rounded(
        self, optimizer, optimizer_inputs
    ):
        """Either a one-step move fits inside the recorded range, or check 1 refuses it. No third
        option - and in particular no silent snap into an unvalidated region."""
        baseline = optimizer.space.baseline(optimizer_inputs)
        narrow: list[str] = []
        for variable in optimizer.space:
            window = optimizer.validator.range_of(variable.name)
            if window is None:
                continue
            current = baseline[variable.name]
            step = variable.step_at(current)
            low, high = window
            headroom = max(high - current, current - low)
            for direction in (+1.0, -1.0):
                target = variable.snap_to_step(current + direction * step, current)
                state = optimizer.validator.check_operating_range({variable.name: target}).state
                if low <= target <= high:
                    assert state == STATE_PASS, (variable.name, target)
                else:
                    assert state == STATE_FAIL, (variable.name, target)
            if step > headroom:
                narrow.append(variable.name)
        # Reported through the test name rather than asserted as a count: which variables are
        # narrow depends on the synthetic run, and pinning the list would make a data change look
        # like a code failure.
        assert all(name in optimizer.space for name in narrow)


class TestSearchAndPolish:
    """PRD 24's optional refinement, and what happens when the solve budget runs out."""

    def test_polish_is_disabled_by_default_and_the_config_records_why(
        self, optimizer, normal_result, optimization_config
    ):
        polish = optimization_config.get_path("search.polish").to_dict()
        assert polish["enabled"] is False
        assert polish["method"] == "differential_evolution"
        assert polish["seed"] is not None, "a refinement that ran would still have to be seeded"
        assert polish["time_budget_s"] > 0.0
        assert optimizer.search["polish"]["enabled"] is False
        assert all(
            candidate.origin != ORIGIN_POLISH for candidate in normal_result.candidates
        ), "the shipped default must not spend the budget the config says it does not spend"

    def test_an_enabled_polish_is_gated_exactly_like_the_grid(
        self, make_optimizer, optimization_config, optimizer_inputs, optimization_history
    ):
        """Directive item 1: a refined candidate is still a candidate, not a shortcut past the gate.

        In-memory config only, and both knobs are declared: ``polish.enabled`` is turned on because
        the shipped default is off, and ``max_unit_solves`` is raised because the shipped budget is
        sized for the grid alone (the measurement is in ``configs/optimization.yaml``).
        """
        enabled = override(optimization_config, "search.polish.enabled", True)
        funded = override(enabled, "search.max_unit_solves", 4096)
        optimizer = make_optimizer(config=funded)
        result = optimizer.optimize(
            inputs=optimizer_inputs, history=optimization_history, mode="NORMAL"
        )
        polished = [item for item in result.candidates if item.origin == ORIGIN_POLISH]
        assert polished, "polish was enabled and funded, so it has to have proposed something"
        limit = optimizer.space.max_delta_fraction("NORMAL")
        baseline = optimizer.space.baseline(optimizer_inputs)
        for candidate in polished:
            states = {check.name: check.state for check in candidate.envelope.checks}
            assert tuple(states) == PRD_14_3_CHECKS
            for name, value in candidate.setpoints.items():
                current = baseline[name]
                variable = optimizer.space[name]
                low, high = optimizer.space.bounds(name, current, "NORMAL")
                assert low - 1e-9 <= value <= high + 1e-9, name
                assert abs(value - current) <= abs(current) * limit + 1e-9, name
                # `Optimizer._offset` snaps onto the slider grid and *then* clips to the mode
                # bound, and the mode bound (current +/- max_delta_fraction) is not itself a
                # slider position - so a candidate pinned to the bound legitimately sits between
                # two steps. Asserted as "on the grid or at the bound" rather than relaxed away,
                # because anything else off-grid would be a real defect. Reported as a minor
                # deviation rather than silently fixed.
                on_grid = value == pytest.approx(variable.snap_to_step(value, current))
                at_bound = value == pytest.approx(low) or value == pytest.approx(high)
                assert on_grid or at_bound, (name, value)
            if candidate.accepted:
                assert set(states.values()) == {STATE_PASS}
        if result.recommendation is not None:
            assert result.recommendation.envelope_status == WITHIN_ENVELOPE

    def test_an_exhausted_solve_budget_is_reported_rather_than_hidden(
        self, make_optimizer, optimization_config, optimizer_inputs, optimization_history,
        normal_result,
    ):
        """NFR-2 is a budget, not a licence to truncate silently (in-memory override, declared)."""
        starved = override(optimization_config, "search.max_unit_solves", 4)
        optimizer = make_optimizer(config=starved)
        result = optimizer.optimize(
            inputs=optimizer_inputs, history=optimization_history, mode="NORMAL"
        )
        units = len(dict.fromkeys(variable.dataset for variable in optimizer.space))
        assert result.budget_exhausted is True
        assert result.describe()["budget_exhausted"] is True
        assert result.solves <= 4 + units, "the backstop is allowed to overshoot by at most a unit"
        assert result.evaluated < normal_result.evaluated, "it really did stop early"
        assert normal_result.budget_exhausted is False, "the shipped budget is not itself starved"
        assert result.message
        assert result.recommendation is not None or result.no_safe_recommendation


def strings_of(payload: Any) -> list[str]:
    """Every string anywhere in a nested payload - for the forbidden-phrase scan."""
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        found: list[str] = []
        for key, value in payload.items():
            found.append(str(key))
            found.extend(strings_of(value))
        return found
    if isinstance(payload, (list, tuple)):
        found = []
        for item in payload:
            found.extend(strings_of(item))
        return found
    return []


class TestSyntheticOnlyFraming:
    """Directive items 7, 19 and 20, and FR-16/PRD 30: what an output may and may not claim."""

    def test_every_recommendation_is_labelled_decision_support_and_synthetic(self, normal_result):
        recommendation = normal_result.recommendation
        assert recommendation is not None
        assert recommendation.label == AI_RECOMMENDATION_LABEL
        explanation = recommendation.explanation()
        assert AI_RECOMMENDATION_LABEL in explanation
        assert DECISION_SUPPORT_LABEL in explanation
        assert SYNTHETIC_DEMONSTRATION_LABEL in explanation

    def test_the_explanation_names_the_gate_the_quality_and_the_caveat(self, normal_result):
        """Directive item 19: WHY this is acceptable, in the string a demo actually shows."""
        recommendation = normal_result.recommendation
        explanation = recommendation.explanation()
        assert recommendation.constraint_status in explanation
        assert recommendation.envelope_status in explanation
        assert recommendation.mode in explanation
        assert recommendation.recommendation_quality in explanation
        assert recommendation.reason.strip().rstrip(".") in explanation
        assert SIMULATED_SAVING_CAVEAT in explanation

    def test_no_reported_saving_travels_without_its_caveat(self, normal_result, fuel_cut):
        """Directive item 7 - in all four places a number is shown."""
        assert normal_result.recommendation.expected_impact.caveat == SIMULATED_SAVING_CAVEAT
        assert normal_result.baselines.caveat == SIMULATED_SAVING_CAVEAT
        assert SIMULATED_SAVING_CAVEAT in fuel_cut.savings_line()
        assert fuel_cut.panel()["energy_impact"]["caveat"] == SIMULATED_SAVING_CAVEAT

    def test_the_forbidden_control_phrase_appears_nowhere(self, normal_result, fuel_cut):
        """PRD 30 / FR-16: this platform recommends; it never commands."""
        payloads = [normal_result.describe(), fuel_cut.describe(), fuel_cut.panel()]
        for payload in payloads:
            haystack = strings_of(payload)
            assert not any(FORBIDDEN_CONTROL_LABEL in text for text in haystack)
            assert not any("automatic control" in text.lower() for text in haystack)

    def test_no_safe_recommendation_is_a_displayable_outcome_not_an_error(
        self, make_optimizer, optimization_config, optimizer_inputs, optimization_history
    ):
        """Directive item 17: refuse and say so, never relax a constraint to produce an answer.

        The impossible Blaine window is in-memory and declared (see
        :func:`impossible_quality_window`); what is under test is the platform's behaviour when
        nothing can pass, which cannot be provoked at all from a feasible operating point.
        """
        optimizer = make_optimizer(config=impossible_quality_window(optimization_config))
        result = optimizer.optimize(
            inputs=optimizer_inputs, history=optimization_history, mode="NORMAL"
        )
        assert result.no_safe_recommendation
        assert result.recommendation is None
        assert result.message.startswith(NO_SAFE_RECOMMENDATION)
        assert result.blocked_by, "a refusal has to name what refused it"
        assert result.accepted_candidates == ()
        assert result.candidates, "it still evaluated candidates - it did not give up early"
        assert result.rules.suggestion(), "the non-AI fallback is still available and shown"
        payload = round_tripped(result.describe())
        assert payload["no_safe_recommendation"] is True
        assert payload["recommendation"] is None
        # The shipped window is untouched by this test.
        assert optimization_config.get_path("targets.blaine_tolerance_cm2_g") > 1.0


class TestNfr2Budget:
    """NFR-2: "a single what-if scenario simulate+predict+optimize round trip" under 3 s."""

    def test_one_what_if_round_trip_is_inside_the_budget(
        self, make_optimizer, optimizer_inputs, optimization_history
    ):
        """Timed warm, on a cold memo, exactly as ``configs/optimization.yaml`` records it.

        Its own engine rather than the shared one: the session optimizer's cache already holds
        every point the reference search visited, so a timed call against it could be answered
        from the memo and would measure nothing. The first call in a process also pays
        sklearn/numpy warm-up that is not search cost, so one throw-away round trip runs first.
        """
        engine = WhatIfEngine(make_optimizer())
        common = {"inputs": optimizer_inputs, "history": optimization_history}
        warm_up = engine.run(**common, delta_fractions={"kiln_feed_rate_tph": 0.01})
        assert warm_up.recommendation is not None

        started = time.perf_counter()
        timed = engine.run(**common, delta_fractions={"mill_feed_rate_tph": 0.024})
        elapsed = time.perf_counter() - started

        assert timed.simulated, "an unsolved request would not be a round trip at all"
        assert timed.assessment.solves > 0, "the twin was really solved, not read from the memo"
        assert timed.assessment.predictions, "Model A was really consulted"
        assert elapsed < NFR_2_ROUND_TRIP_SECONDS, (
            f"one what-if round trip took {elapsed:.2f} s against the NFR-2 budget of "
            f"{NFR_2_ROUND_TRIP_SECONDS:.0f} s"
        )
