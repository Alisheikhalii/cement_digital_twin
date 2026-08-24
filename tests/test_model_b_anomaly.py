"""Model B: anomaly detection, sensor-versus-process discrimination, PRD 15 output (Section 13.2).

The contracts pinned here are the ones a UI and an operator depend on:

* the forest is fitted on normal, non-startup rows and nothing else (PRD 13.2 "normal operation
  windows"), and no block reports a number produced by a detector that had seen those rows as faults;
* every block carries the PRD 22 detection metrics, with the startup ramp reported on its own line
  rather than counted as false positives;
* the out-of-distribution gate the optimizer consumes (PRD 14.3) is *stricter* than the UI banner,
  because it is the same forest score at a tighter percentile;
* a report renders exactly the five PRD 15 labels, with hedged wording and no causal claim;
* the sensor-vs-process reading stays evidence-only while ``report_sensor_claim`` is false;
* scoring is instantaneous - row ``i``'s score does not depend on any other row of the frame.

As in ``test_model_a.py``, no test asserts that a metric beats a fixed number. The one metric-shaped
assertion is that precision exceeds the base rate of the block, which is a statement about the
detector being better than a coin, not a tuned threshold to optimize against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.anomaly_detection.detector import (
    INCONCLUSIVE_HYPOTHESIS,
    NO_ANOMALY,
    NO_RULE_ENGINE_ACTION,
    PROCESS_ANOMALY,
    SENSOR_ANOMALY,
    UNDETERMINED_ANOMALY,
)
from src.anomaly_detection.isolation import normal_rows
from src.features.lag_features import (
    sensor_layer_faults,
    sensor_layer_regime_names,
    startup_regime_name,
)
from src.features.splits import CHRONOLOGICAL, SCENARIO_HOLDOUT
from src.labels import ANOMALY_HYPOTHESIS_LABEL, RULE_BASED_SUGGESTION_LABEL
from src.models.train import ALL_ROWS, model_b_splits

#: The PRD 22 metrics every detection block must carry.
DETECTION_METRICS = ("rows", "precision", "recall", "f1", "false_positive_rate")

#: Words that would turn PRD 15's hedged hypothesis into a diagnosis.
CAUSAL_WORDS = ("caused by", "because", "due to", "root cause", "is the cause")


# -- what the forest was fitted on (PRD 13.2) ------------------------------------------------
def test_the_forest_is_fitted_on_normal_non_startup_rows_only(kiln_frame, kiln_detector, ml_config):
    """"Trained on normal operation windows" - counted, not assumed.

    Two exclusions stack, and the count only works out if both are applied: the normal-row rule of
    PRD 13.2 (no ``injected_fault``, and not the startup ramp), and completeness - a row carrying a
    PRD 11.5 dropout hole in any monitored tag cannot be fitted on at all.
    """
    blocks = model_b_splits(kiln_frame, config=ml_config)
    fit_rows = kiln_frame.loc[blocks[ALL_ROWS]["fit"]]
    startup = startup_regime_name()
    normal = normal_rows(fit_rows, startup_regime=startup)
    complete = fit_rows[list(kiln_detector.tags)].notna().all(axis=1)
    expected = int((normal & complete).sum())
    assert expected > 0
    assert kiln_detector.scorer.describe()["training_rows"] == expected
    # Each exclusion is doing real work in this run, so neither half of the rule is untested.
    assert int(normal.sum()) > expected, "no dropout rows in the fit block - completeness untested"
    assert fit_rows["injected_fault"].notna().any(), "no fault rows in the fit block - vacuous"
    assert (kiln_frame["operating_regime"].astype(str) == startup).any(), "no startup ramp - vacuous"


def test_no_block_scores_a_fault_row_it_was_fitted_on(kiln_frame, ml_config):
    """The only leakage route Model B has: a row in both the fit set and the evaluated set.

    ``all_rows`` deliberately overlaps - PRD 13.2 says score every row - so the assertion there is
    the one that matters: every overlapping row is a *normal* row, never one of the faults the
    metrics count as positives.
    """
    blocks = model_b_splits(kiln_frame, config=ml_config)
    for name, block in blocks.items():
        overlap = sorted(set(block["fit"]) & set(block["evaluate"]))
        if name != ALL_ROWS:
            assert not overlap, f"{name}: {len(overlap)} rows are both fitted and scored"
            continue
        assert overlap, "all_rows should overlap by design; the split map changed"
        shared = kiln_frame.loc[overlap]
        fitted = normal_rows(shared, startup_regime=startup_regime_name())
        faults = shared.loc[fitted, "injected_fault"]
        assert faults.notna().sum() == 0, "a fault row was both fitted and scored as a positive"


def test_the_scenario_holdout_withholds_whole_regimes_from_the_forest(kiln_frame, ml_config):
    holdout = [str(name) for name in ml_config.get_path("splits.scenario_holdout_regimes")]
    blocks = model_b_splits(kiln_frame, config=ml_config)
    block = blocks[SCENARIO_HOLDOUT]
    regime = kiln_frame["operating_regime"].astype(str)
    assert set(regime.loc[block["evaluate"]]) <= set(holdout)
    assert not set(regime.loc[block["fit"]]) & set(holdout)
    assert block["holdout_regimes"] == holdout


# -- the PRD 22 detection table ---------------------------------------------------------------
def test_the_three_documented_blocks_are_evaluated_and_the_primary_one_ships(kiln_model_b):
    assert set(kiln_model_b.evaluations) == {ALL_ROWS, CHRONOLOGICAL, SCENARIO_HOLDOUT}
    assert kiln_model_b.dataset == "kiln"
    assert kiln_model_b.detector.fitted
    # The shipped detector is the all_rows fit - the configuration the UI and the 14.3 gate use.
    primary = kiln_model_b.evaluations[ALL_ROWS]
    assert primary.split == ALL_ROWS
    assert "Method 1" in primary.detection["decision"]


def test_every_block_reports_the_prd_22_detection_metrics(kiln_model_b):
    """Present for every block, in range - and where one is undefined, its denominator is empty.

    ``None`` is the honest value for "no rows in the denominator" (nothing flagged, or a block with
    no negatives at all). Accepting it unconditionally would hide a metric that failed to compute, so
    each ``None`` is tied back to the confusion cell that explains it.
    """
    for name, evaluation in kiln_model_b.evaluations.items():
        detection = evaluation.detection
        assert all(key in detection for key in DETECTION_METRICS), name
        assert detection["rows"] == evaluation.scored_rows, name
        confusion = detection["confusion"]
        assert sum(confusion.values()) == evaluation.scored_rows, name
        assert evaluation.scored_rows <= evaluation.rows, name
        denominators = {
            "precision": confusion["true_positive"] + confusion["false_positive"],
            "recall": confusion["true_positive"] + confusion["false_negative"],
            "false_positive_rate": confusion["false_positive"] + confusion["true_negative"],
        }
        for key, denominator in denominators.items():
            value = detection[key]
            if value is None:
                assert denominator == 0, f"{name}/{key} is None with {denominator} rows to divide by"
                continue
            assert denominator > 0 and 0.0 <= float(value) <= 1.0, f"{name}/{key} = {value}"
        if detection["precision"] is None or detection["recall"] is None:
            assert detection["f1"] is None, name
        else:
            assert 0.0 <= float(detection["f1"]) <= 1.0, name


def test_the_detector_beats_the_base_rate_of_the_block_it_is_scored_on(kiln_model_b):
    """Not a tuned threshold: precision above the prevalence is what "better than a coin" means.

    Only blocks with both classes present can be read that way. ``scenario_holdout`` is scored on the
    withheld regimes *alone*, so for the kiln every row in it is a fault: precision there is 1.0 by
    construction and recall is the only informative number. That block is checked for recall instead
    of being skipped, and the degeneracy is asserted rather than assumed.
    """
    mixed = 0
    for name, evaluation in kiln_model_b.evaluations.items():
        detection = evaluation.detection
        base_rate = float(detection["positive_rate_actual"])
        negatives = detection["confusion"]["false_positive"] + detection["confusion"]["true_negative"]
        if negatives == 0:
            assert base_rate == 1.0, name
            assert detection["false_positive_rate"] is None, name
            assert detection["recall"] is not None, f"{name} has no readable metric at all"
            continue
        if detection["confusion"]["true_positive"] + detection["confusion"]["false_positive"] == 0:
            continue  # nothing flagged in this block; precision is undefined, not poor
        assert 0.0 < base_rate < 1.0, name
        assert float(detection["precision"]) > base_rate, (
            f"{name}: precision {detection['precision']:.3f} is no better than flagging at "
            f"random ({base_rate:.3f})"
        )
        mixed += 1
    assert mixed, "no block had both classes present, so nothing was actually compared"


def test_the_startup_ramp_is_reported_separately_rather_than_scored(kiln_model_b):
    """PRD 11.4's ramp carries no ``injected_fault`` and was withheld from the fit on purpose."""
    for name, evaluation in kiln_model_b.evaluations.items():
        ramp = evaluation.detection["startup_ramp"]
        assert ramp["regime"] == startup_regime_name()
        assert ramp["rows"] >= 0 and ramp["flagged"] <= ramp["rows"]
        assert ramp["detail"], name
    assert kiln_model_b.evaluations[ALL_ROWS].detection["startup_ramp"]["rows"] > 0, (
        "the run contains no startup ramp, so this test is vacuous"
    )


def test_the_alternate_decision_rules_stay_visible(kiln_model_b):
    """PRD 13.2 names the forest primary; the rules *not* adopted are reported, not hidden."""
    for name, evaluation in kiln_model_b.evaluations.items():
        alternates = evaluation.detection["alternates"]
        assert set(alternates) == {
            "spc_single_sample",
            "forest_or_spc_single_sample",
            "out_of_distribution_gate",
        }, name
        for label, payload in alternates.items():
            assert all(key in payload for key in DETECTION_METRICS), f"{name}/{label}"


def test_the_union_alternate_really_is_the_union_of_the_two_methods(kiln_model_b):
    """The published union must behave like ``forest OR spc``, because the card's verdict reads it.

    The card decides in prose whether adopting the union would have been better (and says so if it
    would), so the row it reads has to be the actual union rather than a third rule. That is checked
    here as set algebra on the confusion counts - a union flags every row either component flags and
    no others, so each count is bounded below by the larger component and above by their sum - rather
    than by recomputing ``evaluate``'s row selection, which would only restate the implementation.
    """
    widened = 0
    for name, evaluation in kiln_model_b.evaluations.items():
        detection = evaluation.detection
        alternates = detection["alternates"]
        union = alternates["forest_or_spc_single_sample"]
        spc = alternates["spc_single_sample"]
        forest = {key: detection[key] for key in ("confusion", "rows")}
        assert union["rows"] == forest["rows"] == spc["rows"], name
        for key in ("true_positive", "false_positive"):
            both = (forest["confusion"][key], spc["confusion"][key])
            assert union["confusion"][key] >= max(both), f"{name}/{key} lost a flagged row"
            assert union["confusion"][key] <= sum(both), f"{name}/{key} flagged a row neither did"
        for key in ("false_negative", "true_negative"):
            both = (forest["confusion"][key], spc["confusion"][key])
            assert union["confusion"][key] <= min(both), f"{name}/{key} grew under a union"
        assert sum(union["confusion"].values()) == union["rows"], name
        assert union["recall"] >= max(detection["recall"], spc["recall"]), name
        if union["confusion"]["true_positive"] > forest["confusion"]["true_positive"]:
            widened += 1
    assert widened, "the SPC layer adds no flags anywhere, so the union test is vacuous"


def test_the_card_reads_the_union_off_the_numbers_instead_of_remembering_a_conclusion(
    kiln_model_b,
):
    """``MODEL_CARD.md`` justifies the forest-only banner in prose, so the prose must be derived.

    The card previously carried the comparison as remembered text from a development run. It is now
    generated from the evaluation it ships beside, which is only worth anything if a *different*
    result would produce a different sentence - so the branch that concedes the union is checked with
    numbers where the union dominates, and this run's own block is checked to reach the honest
    verdict.
    """
    from src.models.model_card import _decision_comparison, _union_verdict

    detection = kiln_model_b.evaluations[ALL_ROWS].detection
    union = detection["alternates"]["forest_or_spc_single_sample"]
    shipped = _union_verdict(detection, union)
    assert 'PRD 13.2\'s "Method 1 (primary)" is taken literally' in shipped
    assert "wins outright" not in shipped, (
        "the union now beats the forest on both F1 and false-positive rate on this run, so the "
        "forest-only banner is no longer the measured choice - see MODEL_CARD.md"
    )

    dominant = dict(union, f1=float(detection["f1"]) + 0.05, false_positive_rate=0.0)
    conceded = _union_verdict(detection, dominant)
    assert "wins outright" in conceded and "should be revisited" in conceded
    assert _union_verdict(detection, None).startswith("The union of the two methods was not scored")
    assert "left to the table above" in _union_verdict(dict(detection, f1=None), union)

    table = "\n".join(_decision_comparison(kiln_model_b.evaluations[ALL_ROWS]))
    for name in detection["alternates"]:
        assert name in table, f"{name} is measured but not shown in the card"
    assert "forest (adopted)" in table
    assert "not evaluated on this run" in "\n".join(_decision_comparison(None))


# -- the dual role of one score: UI banner and PRD 14.3 gate ----------------------------------
@pytest.fixture(scope="module")
def kiln_scores(kiln_detector, kiln_frame):
    return kiln_detector.scorer.score(kiln_frame)


def test_the_ood_gate_is_the_same_score_at_a_stricter_percentile(kiln_detector, kiln_scores):
    """PRD 13.2/14.3: one forest, two thresholds - the optimizer's must be the tighter one."""
    scorer = kiln_detector.scorer
    assert scorer.ood_threshold < scorer.flag_threshold, (
        "the gate is looser than the banner, so the optimizer would accept points the UI warns about"
    )
    flagged = int(kiln_scores.flagged.sum())
    gated = int(kiln_scores.out_of_distribution.sum())
    assert 0 < gated <= flagged
    # Every gated row is also flagged: strictly nested decisions, not two separate rules.
    assert not (kiln_scores.out_of_distribution & ~kiln_scores.flagged).any()


def test_the_ood_ratio_is_a_position_in_a_known_distribution_not_a_probability(
    kiln_detector, kiln_scores
):
    ratio = kiln_scores.ood_ratio.to_numpy(dtype=float)
    finite = ratio[np.isfinite(ratio)]
    assert finite.size and finite.min() >= 0.0
    assert finite.max() > 1.0, "nothing in the run sits past the gate, so the scale is untested"
    # 1.0 is exactly the threshold, so the two decisions must agree at that point.
    crossed = kiln_scores.ood_ratio >= 1.0
    assert bool((crossed == kiln_scores.out_of_distribution)[kiln_scores.score.notna()].all())


def test_scoring_a_single_row_matches_scoring_the_whole_frame(kiln_detector, kiln_frame, kiln_scores):
    """Method 1 is instantaneous: row ``i``'s score cannot depend on any other row (leakage test)."""
    positions = [int(p) for p in np.linspace(200, len(kiln_frame) - 1, 6, dtype=int)]
    for position in positions:
        alone = kiln_detector.scorer.score(kiln_frame.loc[[position]])
        assert float(alone.score.iloc[0]) == pytest.approx(
            float(kiln_scores.score.loc[position]), rel=1e-12
        )
        assert bool(alone.flagged.iloc[0]) == bool(kiln_scores.flagged.loc[position])
        assert bool(alone.out_of_distribution.iloc[0]) == bool(
            kiln_scores.out_of_distribution.loc[position]
        )


# -- the PRD 15 output block -------------------------------------------------------------------
@pytest.fixture(scope="module")
def kiln_spc(kiln_detector, kiln_frame):
    return kiln_detector.spc(kiln_frame)


@pytest.fixture(scope="module")
def anomaly_reports(kiln_detector, kiln_frame, kiln_spc, kiln_scores):
    """A handful of flagged rows, taken late enough that the rolling SPC baseline is established."""
    flagged = kiln_scores.flagged
    positions = [int(p) for p in flagged.index[flagged.to_numpy(dtype=bool)] if int(p) > 200]
    assert positions, "nothing was flagged in the run, so the PRD 15 tests would be vacuous"
    chosen = positions[:: max(1, len(positions) // 8)][:8]
    return [
        kiln_detector.report(kiln_frame, position, spc=kiln_spc, scores=kiln_scores)
        for position in chosen
    ]


@pytest.fixture(scope="module")
def normal_report(kiln_detector, kiln_frame, kiln_spc, kiln_scores):
    quiet = kiln_scores.flagged.to_numpy(dtype=bool)
    positions = [int(p) for p, hot in zip(kiln_scores.flagged.index, quiet) if not hot and int(p) > 200]
    assert positions, "every row was flagged, so the NORMAL branch is untested"
    return kiln_detector.report(kiln_frame, positions[len(positions) // 2], spc=kiln_spc, scores=kiln_scores)


def test_an_anomaly_renders_exactly_the_five_prd_15_labels(anomaly_reports):
    for report in anomaly_reports:
        lines = report.render().splitlines()
        assert len(lines) == 5, lines
        assert lines[0] == "WARNING" == report.status
        assert lines[1].startswith("Detected anomaly: ")
        assert lines[2].startswith(f"{ANOMALY_HYPOTHESIS_LABEL}: ")
        assert lines[3].startswith("Affected variables: ")
        assert lines[4].startswith(f"{RULE_BASED_SUGGESTION_LABEL}: ")
        assert report.is_anomaly


def test_the_report_wording_stays_a_hypothesis_rather_than_a_diagnosis(anomaly_reports):
    """PRD 15: "Causal language is avoided" - the label says hypothesis and so must the prose."""
    assert "hypothesis" in ANOMALY_HYPOTHESIS_LABEL.lower()
    assert "not a diagnosis" in RULE_BASED_SUGGESTION_LABEL.lower()
    for report in anomaly_reports:
        text = report.render().lower()
        for word in CAUSAL_WORDS:
            assert word not in text, f"causal phrasing {word!r} in:\n{report.render()}"


def test_a_quiet_row_renders_as_normal_and_claims_nothing(normal_report):
    assert normal_report.render() == "NORMAL\nNo anomaly detected."
    assert normal_report.status == "NORMAL" and not normal_report.is_anomaly
    assert normal_report.detected_anomaly is None
    assert normal_report.anomaly_kind == NO_ANOMALY
    assert not normal_report.flagged
    assert "anomaly score sits inside the normal-regime range" in normal_report.hypothesis
    # No hypothesis evidence is fabricated for a row that was not flagged.
    assert "lead_tag" not in normal_report.evidence
    assert normal_report.evidence["regime_match"]["regime"] is None


def test_affected_variables_are_capped_ranked_and_interpretable(
    anomaly_reports, ml_config, kiln_detector
):
    """PRD 15 "Affected variables": what a UI puts in a list, so it needs a tag and a direction."""
    limit = int(ml_config.get_path("anomaly.affected_variables_max"))
    kiln_tags = set(kiln_detector.tags)
    for report in anomaly_reports:
        variables = report.affected_variables
        assert 0 < len(variables) <= limit
        magnitudes = [abs(float(item["z_score"])) for item in variables]
        assert magnitudes == sorted(magnitudes, reverse=True), "not ranked by deviation"
        for item in variables:
            assert set(item) >= {"tag", "z_score", "direction", "out_of_band"}
            assert item["tag"] in kiln_tags, f"{item['tag']} is not a monitored tag"
            assert item["direction"] == ("above" if float(item["z_score"]) > 0 else "below")
            assert np.isfinite(float(item["z_score"]))


def test_the_report_carries_the_evidence_the_ui_and_the_gate_both_need(anomaly_reports, ml_config):
    limit = int(ml_config.get_path("anomaly.affected_variables_max"))
    for report in anomaly_reports:
        forest = report.evidence["isolation_forest"]
        assert forest["flag_threshold"] > forest["ood_threshold"]
        assert forest["score"] is not None and np.isfinite(float(forest["score"]))
        assert len(forest["contributions"]) <= limit
        for item in forest["contributions"]:
            assert set(item) == {"feature", "training_sigma_from_mean", "value", "training_mean"}
        match = report.evidence["regime_match"]
        assert set(match) == {"regime", "similarity", "min_similarity", "ranked"}
        assert len(match["ranked"]) <= 3
        if match["regime"] is not None:
            assert float(match["similarity"]) >= float(match["min_similarity"])
            assert report.detected_anomaly == match["regime"]
        payload = report.describe()
        assert payload["hypothesis_label"] == ANOMALY_HYPOTHESIS_LABEL
        assert payload["suggested_action_label"] == RULE_BASED_SUGGESTION_LABEL


# -- the Section 14.6 rule-engine hook ---------------------------------------------------------
def test_without_a_rule_engine_no_action_is_invented(anomaly_reports):
    """Model B never authors advice: the field says the engine is absent (PRD 14.6 is Task 5)."""
    for report in anomaly_reports:
        assert report.suggested_action == NO_RULE_ENGINE_ACTION
        assert NO_RULE_ENGINE_ACTION in report.render()


def test_an_attached_rule_engine_supplies_the_action_and_sees_the_evidence(
    kiln_detector, kiln_frame, kiln_spc, kiln_scores, anomaly_reports
):
    seen: list[dict] = []

    def engine(payload):
        seen.append(payload)
        return "Reduce fuel rate by 2% and re-check in 10 minutes."

    position = int(kiln_scores.flagged.index[kiln_scores.flagged.to_numpy(dtype=bool)][-1])
    report = kiln_detector.report(
        kiln_frame, position, rule_engine=engine, spc=kiln_spc, scores=kiln_scores
    )
    assert report.suggested_action == "Reduce fuel rate by 2% and re-check in 10 minutes."
    assert report.render().splitlines()[4].endswith(report.suggested_action)
    assert len(seen) == 1
    payload = seen[0]
    assert payload["status"] == "WARNING"
    assert set(payload) >= {"dataset", "anomaly_kind", "affected_variables", "evidence"}
    assert payload["evidence"]["isolation_forest"]["score"] is not None
    # A normal row is never sent to the engine at all.
    quiet = [int(p) for p, hot in zip(kiln_scores.flagged.index, kiln_scores.flagged) if not hot]
    kiln_detector.report(kiln_frame, quiet[-1], rule_engine=engine, spc=kiln_spc, scores=kiln_scores)
    assert len(seen) == 1, "the rule engine was consulted about a NORMAL row"


# -- sensor versus process (PRD 11.4 regime 14, PRD 13.2) --------------------------------------
def test_the_sensor_claim_is_withheld_while_the_separation_is_unmeasured(anomaly_reports, ml_config):
    """``report_sensor_claim`` is false because the separation was measured and is not there.

    The three signatures are still computed and still reported as evidence - what is withheld is the
    *label*, which PRD 15 forbids stating as a diagnosis in the first place.
    """
    claimable = bool(ml_config.get_path("anomaly.sensor_discrimination.report_sensor_claim"))
    for report in anomaly_reports:
        evidence = report.evidence
        if evidence.get("lead_tag") is None:  # baseline still warming up
            assert report.anomaly_kind == UNDETERMINED_ANOMALY
            continue
        assert set(evidence["signatures"]) == {
            "drifts_one_way",
            "manipulated_variables_quiet",
            "deviation_is_local",
        }
        assert isinstance(evidence["sensor_signatures_satisfied"], bool)
        assert evidence["sensor_claim_reported"] is claimable
        if claimable:
            continue
        assert report.anomaly_kind != SENSOR_ANOMALY, "a withheld claim was emitted anyway"
        assert report.anomaly_kind in (PROCESS_ANOMALY, UNDETERMINED_ANOMALY)
        if evidence["sensor_signatures_satisfied"]:
            assert report.anomaly_kind == UNDETERMINED_ANOMALY
            assert INCONCLUSIVE_HYPOTHESIS in report.hypothesis


def test_the_sensor_versus_process_split_is_measured_not_asserted(kiln_model_b, ml_config):
    """PRD 13.2 asks the two to be distinguished; PRD 22 asks how well. Both scopes are reported."""
    faults = sensor_layer_faults()
    assert faults, "no sensor-layer fault is configured, so regime 14 cannot be scored"
    for name, evaluation in kiln_model_b.evaluations.items():
        payload = evaluation.sensor_discrimination
        assert payload["positive_class"] == SENSOR_ANOMALY
        assert set(payload["sensor_layer_faults"]) == set(faults)
        assert payload["sensor_claim_reported"] is bool(
            ml_config.get_path("anomaly.sensor_discrimination.report_sensor_claim")
        )
        for scope in ("on_reported_rows", "on_all_fault_rows"):
            metrics = payload[scope]
            assert all(key in metrics for key in DETECTION_METRICS), f"{name}/{scope}"
            assert metrics["no_control_chart_evidence_rows"] >= 0
        assert payload["rule"], "the thresholds behind the rule are not reported"
        assert payload["detail"].startswith("Three ASSUMPTION signatures")
    # The diagnostic scope must actually contain rows, or the claim "measured" would be empty.
    overall = kiln_model_b.evaluations[ALL_ROWS].sensor_discrimination["on_all_fault_rows"]
    assert overall["rows"] > 0, "no fault row carried control-chart evidence - nothing was measured"


def test_the_card_reads_the_drift_limitation_off_the_run_not_off_a_remembered_number(kiln_model_b):
    """``MODEL_CARD.md``'s regime-14 limitation used to carry figures from a development run.

    They had gone stale against the shipped artefacts - the exact failure a generated card exists to
    prevent - so both measured clauses (what Method 1 does with the drift regimes, and whether the
    three-signature rule beats its own base rate) are now read off the run being carded. That is only
    worth anything if a different run would say something different, so the branch that concedes the
    rule became informative is exercised with a doctored block, and this run is checked to reach the
    suppression verdict carrying its own numbers.
    """
    from types import SimpleNamespace

    from src.models.model_card import (
        DRIFT_LIMITATION,
        _drift_measurements,
        _fmt,
        _precision_vs_base,
    )
    from src.models.train import TrainingRun

    def as_run(result: object) -> TrainingRun:
        return TrainingRun(model_a={}, model_b={"kiln": result}, reports={}, registry=None)

    evaluation = kiln_model_b.evaluations[ALL_ROWS]
    block = evaluation.sensor_discrimination
    scope = block["on_all_fault_rows"]
    measured = _drift_measurements(as_run(kiln_model_b))

    seen = 0
    for name in sensor_layer_regime_names():
        entry = evaluation.per_regime_recall.get(str(name))
        if entry is None:  # the regime never occurred in this run
            continue
        seen += 1
        assert f"`{name}` rows" in measured
        assert f"{int(entry['rows']):,}" in measured
        assert _fmt(entry["recall"], 3) in measured
    assert seen, "no sensor-layer regime is in this run's breakdown, so nothing was substituted"
    assert _fmt(scope["precision"], 3) in measured
    assert _fmt(scope["positive_rate_actual"], 3) in measured
    assert "no unit's precision clears its base rate" in measured, (
        "the three-signature rule now beats its base rate by more than sampling noise on this run, "
        "so suppressing the sensor claim is no longer the measured choice - see MODEL_CARD.md"
    )

    # The figures are substituted *into* the structural explanation, not in place of it.
    rendered = DRIFT_LIMITATION[1].format(measured=measured)
    assert measured in rendered
    assert "report_sensor_claim` is **false**" in rendered
    assert "The cause is structural, not a tuning failure" in rendered

    informative = dict(scope, precision=1.0, positive_rate_actual=0.1)
    flipped = _drift_measurements(
        as_run(
            SimpleNamespace(
                evaluations={
                    ALL_ROWS: SimpleNamespace(
                        sensor_discrimination=dict(block, on_all_fault_rows=informative),
                        per_regime_recall=evaluation.per_regime_recall,
                    )
                }
            )
        )
    )
    assert "clears the base rate by more than two binomial standard errors on `kiln`" in flipped
    assert "should be re-examined" in flipped
    assert "no drift figures" in _drift_measurements(
        TrainingRun(model_a={}, model_b={}, reports={}, registry=None)
    )

    # The same comparison drives the discrimination table's closing sentence.
    assert "Neither scope clears it" in _precision_vs_base(block)
    assert "re-examined" in _precision_vs_base(dict(block, on_all_fault_rows=informative))
    assert "Neither scope flagged anything" in _precision_vs_base({})


def test_the_base_rate_comparison_needs_more_than_a_bare_inequality(kiln_model_b):
    """The margin exists because a raw ``precision > base_rate`` flips on noise.

    The 30-day kiln run scores precision 0.152 against a 0.147 base rate over a few thousand called
    rows - a bare inequality would turn that into "the rule became informative, revisit the
    suppression", which is a false alarm in the opposite direction from the stale text this replaced.
    Two binomial standard errors of the null is the threshold, so it is pinned here directly rather
    than only through the prose that reads it.
    """
    from src.models.model_card import _beats_base_rate

    scope = kiln_model_b.evaluations[ALL_ROWS].sensor_discrimination["on_all_fault_rows"]
    called = scope["confusion"]["true_positive"] + scope["confusion"]["false_positive"]
    assert called > 0, "nothing was flagged, so the margin cannot be exercised"
    base = float(scope["positive_rate_actual"])
    sigma = (base * (1.0 - base) / called) ** 0.5
    assert _beats_base_rate(dict(scope, precision=base + 1.5 * sigma)) is False
    assert _beats_base_rate(dict(scope, precision=base + 2.5 * sigma)) is True
    assert _beats_base_rate(dict(scope, precision=None)) is None
    assert _beats_base_rate({"precision": 0.9, "positive_rate_actual": 0.1}) is None


def test_per_regime_recall_marks_which_regimes_are_faults_for_this_unit(kiln_model_b):
    """``operating_regime`` is plant-level, ``injected_fault`` is per-unit (FR-3)."""
    recall = kiln_model_b.evaluations[ALL_ROWS].per_regime_recall
    assert recall, "no per-regime breakdown was produced"
    for name, row in recall.items():
        assert set(row) >= {"rows", "flagged", "recall", "injected_fault_on_this_unit", "metric"}
        assert row["rows"] > 0 and 0 <= row["flagged"] <= row["rows"]
        assert row["metric"] == (
            "recall" if row["injected_fault_on_this_unit"] else "false_positive_rate"
        )
    kinds = {name for name, row in recall.items() if row["injected_fault_on_this_unit"]}
    assert kinds, "no regime is a fault for the kiln, so recall is meaningless here"


# -- reproducibility (NFR-4, task constraint 9) ------------------------------------------------
def test_two_detectors_fitted_on_the_same_rows_score_identically(kiln_frame, ml_config):
    from src.anomaly_detection.detector import AnomalyDetector

    blocks = model_b_splits(kiln_frame, config=ml_config)
    positions = blocks[CHRONOLOGICAL]["fit"]
    sample = kiln_frame.loc[blocks[CHRONOLOGICAL]["evaluate"][:400]]
    first = AnomalyDetector("kiln").fit(kiln_frame, positions=positions)
    second = AnomalyDetector("kiln").fit(kiln_frame, positions=positions)
    assert first.scorer.flag_threshold == second.scorer.flag_threshold
    assert first.scorer.ood_threshold == second.scorer.ood_threshold
    left, right = first.scorer.score(sample), second.scorer.score(sample)
    np.testing.assert_array_equal(left.score.to_numpy(), right.score.to_numpy())
    np.testing.assert_array_equal(
        left.flagged.to_numpy(dtype=bool), right.flagged.to_numpy(dtype=bool)
    )
    assert first.signatures.describe() == second.signatures.describe()
