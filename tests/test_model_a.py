"""Model A: multi-horizon prediction, family selection and uncertainty (PRD v1.1.1 Section 13.1).

What this module pins is *contracts*, not numbers:

* every configured (target, horizon) pair is trained, and the horizon set is PRD 13.1's;
* the selected family is chosen on held-out MAE from the chronological validation block, and the
  persistence reference is scored everywhere but is never selectable;
* every PRD 22 metric is present for every (target, horizon, split, block, reference);
* uncertainty is an ensemble spread in the target's own unit, and no output anywhere is a
  confidence percentage (FR-23);
* two identical runs produce identical models (NFR-4).

Deliberately absent: any assertion that an MAE is below some value. Constraint 5 of this task is
"do not optimize for artificially high metrics", and a test that pins a metric is the mechanism by
which that happens - the next person to touch the simulator tunes it until the test passes. Metric
*quality* is reported in ``reports/metrics/`` and ``MODEL_CARD.md``, where a human reads it.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from src.features.lag_features import FeatureBuilder
from src.features.splits import CHRONOLOGICAL, SCENARIO_HOLDOUT
from src.models.metrics import MEASURED, TRUTH
from src.models.model_a import (
    GRADIENT_BOOSTING,
    LIGHTGBM,
    PERSISTENCE,
    RANDOM_FOREST,
    ModelATrainer,
    available_families,
)
from src.models.quality import HIGH, LOW, MEDIUM
from src.models.uncertainty import BOOTSTRAP_ENSEMBLE, TREE_SPREAD
from tests.conftest import ML_FIXTURE_TARGET

#: The horizons PRD 13.1 makes mandatory.
PRD_HORIZONS = (5, 10, 15, 30)

#: Reproducibility tolerance for *derived* numbers (NFR-4). The models themselves are bit-identical:
#: ``estimators_`` tree arrays compare exactly across two runs with the same seed, which is what
#: NFR-4 asks for. Predictions are not, quite: ``RandomForestRegressor.predict`` under the configured
#: ``n_jobs: -1`` accumulates each tree's contribution into one shared array in whatever order the
#: workers finish, so the reduction order varies - a *single* fitted forest differs from itself by
#: ~3.6e-15 between two of its own ``predict`` calls (measured; with ``n_jobs: 1`` it is exact).
#: That is float summation order, not model drift, and it is many orders of magnitude below the
#: sensor resolution of PRD 11.5. Left as it is: setting ``n_jobs: 1`` would buy a digit no reader of
#: a metric table can see, at the cost of real training time - and editing a config to make a test
#: pass is the wrong direction of causation.
REPRODUCIBILITY_RTOL = 1e-12


def tree_signature(estimator: Any) -> np.ndarray:
    """Every split and leaf of a fitted tree ensemble, flattened - the model's own fingerprint.

    Works for both configured families: ``RandomForestRegressor.estimators_`` is a list of trees and
    ``GradientBoostingRegressor.estimators_`` is an ``(n_stages, 1)`` array of them.
    """
    parts: list[np.ndarray] = []
    for tree in np.asarray(estimator.estimators_, dtype=object).ravel():
        internals = tree.tree_
        parts.append(internals.value.ravel())
        parts.append(np.asarray(internals.threshold, dtype=float))
        parts.append(np.asarray(internals.feature, dtype=float))
    return np.concatenate(parts)


# -- configuration and coverage -------------------------------------------------------------
def test_the_four_prd_horizons_are_configured(ml_config):
    horizons = tuple(int(value) for value in ml_config.get_path("prediction.horizons_min"))
    assert set(PRD_HORIZONS) <= set(horizons), (
        f"PRD 13.1 requires t+5/10/15/30 min; configured horizons are {horizons}"
    )


def test_every_configured_target_and_horizon_has_a_feature_layout(ml_config):
    """The full PRD 13.1 grid, checked through the spec - which needs no fit and so stays cheap."""
    for dataset in ("kiln", "mill"):
        builder = FeatureBuilder(dataset)
        targets = tuple(ml_config.get_path(f"prediction.targets.{dataset}"))
        assert targets, f"{dataset} has no configured prediction targets"
        for horizon in builder.horizons_min:
            spec = builder.spec(horizon)
            assert spec.targets == tuple(str(name) for name in targets)
            assert spec.target_names == tuple(
                f"target__{name}__t+{horizon}min" for name in targets
            )
            assert spec.feature_names, f"{dataset} t+{horizon}min has no features"


def test_training_produces_one_model_per_requested_pair(trained_kiln, ml_fixture_horizons):
    assert trained_kiln.dataset == "kiln"
    assert set(trained_kiln.models) == {
        (ML_FIXTURE_TARGET, horizon) for horizon in ml_fixture_horizons
    }
    assert set(trained_kiln.splits) == set(ml_fixture_horizons)
    assert trained_kiln.targets == (ML_FIXTURE_TARGET,)


def test_the_targets_argument_filters_and_refuses_an_empty_selection(kiln_frame):
    """One caller trains both units from one list, so ``targets`` filters rather than overrides."""
    trainer = ModelATrainer("kiln")
    horizon = min(PRD_HORIZONS)
    assert ML_FIXTURE_TARGET in FeatureBuilder("kiln").targets
    result = trainer.train(
        kiln_frame, horizons_min=[horizon], targets=[ML_FIXTURE_TARGET, "mill_motor_power_kw"]
    )
    assert result.targets == (ML_FIXTURE_TARGET,), "a mill target must not create a kiln model"
    with pytest.raises(ValueError, match="none of"):
        trainer.train(kiln_frame, horizons_min=[horizon], targets=["mill_motor_power_kw"])


# -- family selection (PRD 13.1) -------------------------------------------------------------
def test_the_selected_family_is_a_fitted_model_never_the_persistence_reference(trained_kiln):
    for model in trained_kiln.models.values():
        assert model.selected_family in (RANDOM_FOREST, GRADIENT_BOOSTING)
        assert model.selected_family != PERSISTENCE
        assert set(model.estimators) == {RANDOM_FOREST, GRADIENT_BOOSTING}


def test_lightgbm_is_absent_rather_than_half_integrated(ml_config):
    """PRD 13.1 admits LightGBM only if it measurably beats both; it was never tested here."""
    assert LIGHTGBM not in available_families(ml_config)


def test_selection_happens_on_the_chronological_validation_block(trained_kiln):
    for (target, horizon), model in trained_kiln.models.items():
        selection = model.selection
        assert selection["metric"] == "mae"
        assert selection["selected_on"].startswith(CHRONOLOGICAL), selection["selected_on"]
        assert selection["validation_rows"] > 0
        scores = selection["validation_mae"]
        assert set(scores) == {RANDOM_FOREST, GRADIENT_BOOSTING}
        assert all(math.isfinite(float(value)) for value in scores.values())
        assert selection["selected_family"] == model.selected_family
        # Lowest held-out MAE wins (RF takes ties, so compare against the minimum, not to it).
        assert float(scores[model.selected_family]) == pytest.approx(min(map(float, scores.values())))
        # The holdout is measured, never selected on - it gets its own fit instead.
        assert selection["reselected_on_scenario_holdout"] is False


def test_the_persistence_reference_is_scored_beside_every_reported_model_but_never_selected(
    trained_kiln,
):
    """PRD 13.1's baseline is a yardstick on the reported blocks; it can never win selection."""

    def blocks(*models: str) -> set[tuple[Any, ...]]:
        return {
            (row["target"], row["horizon_min"], row["split"], row["block"])
            for row in trained_kiln.metric_rows
            if row["model"] in models
        }

    reference = blocks(PERSISTENCE)
    fitted = blocks(RANDOM_FOREST, GRADIENT_BOOSTING)
    assert reference, "the persistence reference was not scored at all"
    assert reference <= fitted, f"persistence scored where no model was: {reference - fitted}"
    for target, horizon in trained_kiln.models:
        assert (target, horizon, CHRONOLOGICAL, "test") in reference
        skipped = trained_kiln.models[(target, horizon)].selection.get("scenario_holdout_skipped")
        if not skipped:
            assert (target, horizon, SCENARIO_HOLDOUT, "test") in reference
    assert not any(
        row["selected"] for row in trained_kiln.metric_rows if row["model"] == PERSISTENCE
    )


# -- the PRD 22 metric table ------------------------------------------------------------------
def test_every_prd_22_metric_is_present_for_every_pair_split_block_and_reference(trained_kiln):
    required = {"rows", "mae", "rmse", "r2", "mape"}
    seen: set[tuple[Any, ...]] = set()
    for row in trained_kiln.metric_rows:
        assert required <= set(row), f"missing {sorted(required - set(row))} in {row['model']}"
        assert row["dataset"] == "kiln"
        assert row["horizon"] == f"t+{row['horizon_min']}min"
        assert row["split"] in (CHRONOLOGICAL, SCENARIO_HOLDOUT)
        assert row["reference"] in (MEASURED, TRUTH)
        assert row["rows"] > 0
        assert math.isfinite(float(row["mae"])) and float(row["mae"]) >= 0.0
        assert math.isfinite(float(row["rmse"])) and float(row["rmse"]) >= float(row["mae"]) - 1e-9
        if row["mape"] is None:
            assert row["mape_omitted_reason"], "MAPE dropped without saying why"
        seen.add((row["target"], row["horizon_min"], row["split"], row["block"], row["reference"]))
    # Both references and both splits, for every trained pair.
    for target, horizon in trained_kiln.models:
        skipped = trained_kiln.models[(target, horizon)].selection.get("scenario_holdout_skipped")
        splits = (CHRONOLOGICAL,) if skipped else (CHRONOLOGICAL, SCENARIO_HOLDOUT)
        for split in splits:
            for reference in (MEASURED, TRUTH):
                assert any(
                    key[:3] == (target, horizon, split) and key[4] == reference for key in seen
                ), f"no {split}/{reference} row for {target} t+{horizon}min"


def test_both_evaluation_references_are_reported_and_differ(trained_kiln):
    """PRD 22 wants the measurement; PRD 34 item 2 wants the simulator's own true state."""
    by_reference: dict[str, list[float]] = {MEASURED: [], TRUTH: []}
    for row in trained_kiln.metric_rows:
        if row["model"] == PERSISTENCE or row["split"] != CHRONOLOGICAL or row["block"] != "test":
            continue
        by_reference[row["reference"]].append(float(row["mae"]))
    assert by_reference[MEASURED] and by_reference[TRUTH]
    assert by_reference[MEASURED] != by_reference[TRUTH], (
        "the noise-free reference produced identical numbers - the truth frame is not being used"
    )


# -- prediction and uncertainty (PRD 13.1.1, FR-23) -------------------------------------------
@pytest.fixture(scope="module")
def kiln_predictions(trained_kiln, kiln_matrices):
    """One :class:`Prediction` per (target, horizon) pair, from the last row of its own matrix."""
    predictions = {}
    for (target, horizon), model in trained_kiln.models.items():
        matrix = kiln_matrices[horizon]
        predictions[(target, horizon)] = model.predictions(matrix.features.tail(3))
    return predictions


def test_a_prediction_carries_a_spread_in_the_targets_own_unit(kiln_predictions, trained_kiln):
    for (target, horizon), batch in kiln_predictions.items():
        assert len(batch) == 3
        for prediction in batch:
            assert prediction.target == target and prediction.horizon_min == horizon
            assert prediction.unit, "the target has no unit, so the spread has no unit either"
            assert math.isfinite(prediction.value)
            assert math.isfinite(prediction.uncertainty) and prediction.uncertainty > 0.0
            low, high = prediction.interval
            assert low < prediction.value < high
            assert high - low == pytest.approx(2 * prediction.uncertainty)


def test_the_uncertainty_method_is_one_of_the_two_documented_ones(kiln_predictions, trained_kiln):
    """PRD 13.1.1: tree spread for the forest, a bootstrap ensemble for gradient boosting."""
    for (target, horizon), batch in kiln_predictions.items():
        family = trained_kiln.models[(target, horizon)].selected_family
        method = batch[0].uncertainty_method
        if family == RANDOM_FOREST:
            assert method == TREE_SPREAD
        else:
            # The documented fallback is allowed, but it must say so in the method string.
            assert method == BOOTSTRAP_ENSEMBLE or method.startswith(f"{TREE_SPREAD}__fallback_for_")
        assert all(item.uncertainty_method == method for item in batch)


def test_no_output_is_a_confidence_percentage(kiln_predictions):
    """FR-23 allows a width and a category; a calibrated-looking probability is forbidden."""
    for batch in kiln_predictions.values():
        for prediction in batch:
            payload = prediction.describe()
            assert not any("confidence" in str(key).lower() for key in payload), payload.keys()
            assert not any("probability" in str(key).lower() for key in payload)
            assert payload["recommendation_quality"] in (HIGH, MEDIUM, LOW)
            assert prediction.quality.level in (HIGH, MEDIUM, LOW)
            # The category is a label plus its reason, never a number pretending to be one.
            assert isinstance(payload["recommendation_quality"], str)
            assert payload["description"] and "%" not in payload["recommendation_quality"]


def test_the_alternative_family_is_reported_so_disagreement_is_visible(kiln_predictions):
    """PRD 13.1.1 grades quality partly on family disagreement, so both values are carried."""
    for batch in kiln_predictions.values():
        for prediction in batch:
            assert prediction.alternative_value is not None, (
                "only one family was fitted, so disagreement can never be assessed"
            )
            assert math.isfinite(prediction.alternative_value)
            factors = {factor["factor"]: factor for factor in prediction.quality.describe()["factors"]}
            assert "model_disagreement_pct" in factors


# -- reproducibility (NFR-4, task constraint 9) ------------------------------------------------
@pytest.fixture(scope="module")
def retrained_shortest(kiln_frame, kiln_truth_frame, ml_fixture_horizons):
    """A second, independent training pass over the same frame at the shortest horizon only.

    Retraining a *subset* of ``trained_kiln``'s horizons checks two things at once: that a repeated
    run reproduces the first bit for bit (NFR-4), and that a pair's result does not depend on which
    other pairs were trained in the same call - i.e. no RNG or fitted state leaks between horizons.
    """
    from src.models.train import train_model_a

    return train_model_a(
        "kiln",
        kiln_frame,
        truth=kiln_truth_frame,
        horizons_min=[min(ml_fixture_horizons)],
        targets=[ML_FIXTURE_TARGET],
    )


def test_a_repeated_run_fits_bit_identical_models(
    trained_kiln, retrained_shortest, ml_fixture_horizons
):
    """NFR-4 at its strongest: same seed, same data, same trees - split for split, leaf for leaf."""
    horizon = min(ml_fixture_horizons)
    first = trained_kiln.model(ML_FIXTURE_TARGET, horizon)
    second = retrained_shortest.model(ML_FIXTURE_TARGET, horizon)
    assert set(first.estimators) == set(second.estimators)
    for family, estimator in first.estimators.items():
        np.testing.assert_array_equal(
            tree_signature(estimator),
            tree_signature(second.estimators[family]),
            err_msg=f"{family} refitted to a different ensemble",
        )


def test_a_repeated_run_reproduces_the_same_metric_rows(
    trained_kiln, retrained_shortest, ml_fixture_horizons
):
    horizon = min(ml_fixture_horizons)

    def rows(result):
        keyed = {}
        for row in result.metric_rows:
            if int(row["horizon_min"]) != horizon:
                continue
            key = (row["target"], row["split"], row["block"], row["model"], row["reference"])
            keyed[key] = (row["rows"], row["mae"], row["rmse"], row["r2"], row["mape"])
        return keyed

    first, second = rows(trained_kiln), rows(retrained_shortest)
    assert first and set(first) == set(second)
    for key, values in first.items():
        for original, repeat in zip(values, second[key], strict=True):
            if original is None or repeat is None:
                assert original is repeat, f"{key}: {original!r} vs {repeat!r}"
            else:
                assert float(original) == pytest.approx(
                    float(repeat), rel=REPRODUCIBILITY_RTOL
                ), key
    # Row counts are integers and must match exactly - a differing count is a different split.
    for key, values in first.items():
        assert int(values[0]) == int(second[key][0]), key


def test_a_repeated_run_reproduces_the_same_predictions_and_selection(
    trained_kiln, retrained_shortest, kiln_matrices, ml_fixture_horizons
):
    horizon = min(ml_fixture_horizons)
    first = trained_kiln.model(ML_FIXTURE_TARGET, horizon)
    second = retrained_shortest.model(ML_FIXTURE_TARGET, horizon)
    assert first.selected_family == second.selected_family
    assert first.model_version == second.model_version
    assert first.hyperparameters == second.hyperparameters
    assert first.training_domain == second.training_domain
    # Every discrete part of the selection record is identical; only the two held-out MAEs it
    # quotes carry the parallel-reduction wobble described at REPRODUCIBILITY_RTOL.
    scores = {"validation_mae"}
    assert {k: v for k, v in first.selection.items() if k not in scores} == {
        k: v for k, v in second.selection.items() if k not in scores
    }
    for family, value in first.selection["validation_mae"].items():
        assert float(value) == pytest.approx(
            float(second.selection["validation_mae"][family]), rel=REPRODUCIBILITY_RTOL
        )

    features = kiln_matrices[horizon].features.tail(50)
    np.testing.assert_allclose(
        first.predict(features), second.predict(features), rtol=REPRODUCIBILITY_RTOL, atol=0
    )
    left, left_method = first.uncertainty(features)
    right, right_method = second.uncertainty(features)
    assert left_method == right_method
    np.testing.assert_allclose(left, right, rtol=REPRODUCIBILITY_RTOL, atol=0)


def test_the_splits_themselves_are_reproducible(kiln_matrix):
    """Determinism starts before the fit: the same matrix must cut the same blocks every time."""
    from src.features.splits import build_splits

    first, second = build_splits(kiln_matrix), build_splits(kiln_matrix)
    assert set(first) == set(second)
    for name, split in first.items():
        for block in ("train", "validation", "test"):
            np.testing.assert_array_equal(
                getattr(split, block), getattr(second[name], block), err_msg=f"{name}/{block}"
            )


# -- the PRD 13.4 registry contract ------------------------------------------------------------
def test_each_model_describes_itself_well_enough_to_be_registered(trained_kiln):
    """PRD 13.4 wants version, hyperparameters, feature layout and training domain per model."""
    for (target, horizon), model in trained_kiln.models.items():
        payload = model.describe()
        assert payload["dataset"] == "kiln"
        assert payload["target"] == target and payload["horizon_min"] == horizon
        assert payload["model_version"], "an unversioned artifact cannot be registered"
        assert set(payload["hyperparameters"]) == {RANDOM_FOREST, GRADIENT_BOOSTING}
        assert payload["hyperparameters"][model.selected_family], "no recorded hyperparameters"
        assert payload["uncertainty"]["method"] in (TREE_SPREAD, BOOTSTRAP_ENSEMBLE)
        spec = payload["feature_spec"]
        assert spec["feature_count"] == len(model.spec.feature_names)
        assert spec["horizon_min"] == horizon
        # The artifact name carries the version, so two versions never overwrite one another.
        for family in (RANDOM_FOREST, GRADIENT_BOOSTING):
            name = model.artifact_name(family)
            assert name.endswith(".joblib") and payload["model_version"] in name
            assert f"t+{horizon}min" in name and target in name


def test_the_training_domain_covers_every_base_tag_the_ood_gate_will_check(trained_kiln):
    """PRD 14.3 check 1 tests a candidate setpoint against these ranges, so none may be missing."""
    for (target, horizon), model in trained_kiln.models.items():
        domain = model.training_domain
        assert domain["rows"] > 0
        assert len(domain["timestamp_range"]) == 2
        assert domain["operating_regimes"], "no regime recorded - the gate cannot state its domain"
        ranges = domain["variable_ranges"]
        assert set(ranges) == set(model.spec.base_columns), (
            "the domain must describe values at t, one entry per current-value tag"
        )
        for column, (low, high) in ranges.items():
            assert math.isfinite(low) and math.isfinite(high), column
            assert low <= high, column


def test_the_training_domain_is_the_training_block_not_the_whole_run(
    trained_kiln, kiln_matrix, kiln_splits
):
    """Stating a domain that includes the test block would make the OOD gate self-fulfilling."""
    horizon = kiln_matrix.spec.horizon_min
    model = trained_kiln.model(ML_FIXTURE_TARGET, horizon)
    domain = model.training_domain
    assert domain["rows"] < len(kiln_matrix), (
        "the recorded domain spans every row, so no block was held out of it"
    )
    # It is the chronological *train* block (possibly subsampled), never validation or test.
    assert domain["rows"] <= kiln_splits[CHRONOLOGICAL].train.size
    latest_training = kiln_matrix.timestamp.loc[int(kiln_splits[CHRONOLOGICAL].train.max())]
    assert str(domain["timestamp_range"][1]) <= str(latest_training)


def test_the_run_summarises_itself_without_carrying_the_fitted_estimators(trained_kiln):
    payload = trained_kiln.describe()
    assert payload["dataset"] == "kiln"
    assert payload["pairs"] == len(trained_kiln.models)
    assert payload["metric_rows"] == len(trained_kiln.metric_rows)
    assert set(payload["horizons_min"]) == set(trained_kiln.horizons_min)
    for horizon, splits in payload["splits"].items():
        assert set(splits) >= {CHRONOLOGICAL, SCENARIO_HOLDOUT}, horizon
