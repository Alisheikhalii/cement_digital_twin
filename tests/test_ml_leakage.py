"""Numerical proof that neither model can see the future (PRD v1.1.1 Sections 13.1-13.3, NFR-4).

``test_features_ml.py`` pins the *layout* of the ML inputs and the *geometry* of the two PRD 13.3
splits. This module makes the causality argument itself, and makes it by measurement rather than by
inspection: move the data after row ``p``, rebuild everything, and require that row ``p``'s features,
its prediction, its uncertainty, its anomaly score, its SPC statistics and its rendered report are
what they were. Reading ``shift()`` calls and concluding "these look causal" is a weaker claim.

Every perturbation test also carries its own converse. A causality assertion passes trivially if the
quantity under test never moves at all, so each test checks that the perturbation *did* change
something later in the series - otherwise it would still pass against a pipeline broken into
returning constants.

Target leakage is the other half. A feature that happens to be the answer is not the future leaking
through time, it is the label wearing a different column name; that is tested by comparing every
feature column against the target read back from each horizon in play.

No test here asserts a metric value (constraint 5): a leakage proof is about what the numbers can
depend on, never about what they come out to.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.lag_features import startup_regime_name, target_column
from src.features.splits import CHRONOLOGICAL, SCENARIO_HOLDOUT, build_splits

from tests.conftest import ML_FIXTURE_TARGET

#: Where the perturbation boundary sits within the retained rows. Anywhere well clear of both ends
#: works; 60% leaves several hundred rows on each side at the ML fixture length.
BOUNDARY_FRACTION = 0.6

#: Size of the perturbation, in raw tag units. Deliberately enormous - a leak of any weight at all
#: shows against a 1000-unit step, and a causality probe wants its signal far above round-off. It is
#: not a physically meaningful operating point, and nothing here interprets it as one.
PERTURBATION = 1000.0

#: Tolerance for numbers that pass through a fitted forest. The feature frames either side of a
#: perturbation are compared exactly (``atol=0``); predictions off *identical* inputs are compared at
#: this tolerance because ``n_jobs: -1`` sums the trees in worker-completion order - see the note on
#: ``REPRODUCIBILITY_RTOL`` in ``test_model_a.py`` for the measurement behind that.
PREDICT_RTOL = 1e-12


# -- helpers ---------------------------------------------------------------------------------
def perturb_after(
    frame: pd.DataFrame,
    position: int,
    columns,
    *,
    amount: float = PERTURBATION,
) -> pd.DataFrame:
    """A copy of ``frame`` with ``columns`` moved by ``amount`` on every row *after* ``position``.

    Numeric columns only, and the PRD 11.5 dropout holes stay holes: the perturbation has to move
    values a causal pipeline cannot reach without changing *which* rows are missing, since that would
    move the retained-row set and confound every comparison built on top of it.

    The regime labels are left alone deliberately. A regime one-hot is read from the row it belongs
    to, so relabelling later rows could only ever change later rows - and writing the startup label
    into the tail would purge earlier rows through :func:`window_touches`, which is exactly the kind
    of legitimate backwards reach this test must not mistake for a leak.
    """
    modified = frame.copy()
    later = modified.index > position
    for column in columns:
        values = modified.loc[later, column].astype(float)
        modified.loc[later, column] = values + amount
    return modified


def read_window(positions: np.ndarray, *, back: int, forward: int, size: int) -> np.ndarray:
    """Every source row the rows at ``positions`` touch: their lag window and their label.

    A row at ``p`` reads its own tags plus the lag block back to ``p - back``, and its label is the
    observation at ``p + forward``, so ``[p - back, p + forward]`` is every source observation that row
    can be said to have seen. Built by walking the offsets rather than by reusing
    :func:`window_touches`, which answers the transposed question - *which rows' windows touch a flag* -
    and would silently swap the two sides here.
    """
    flags = np.zeros(int(size), dtype=bool)
    for offset in range(-int(back), int(forward) + 1):
        touched = np.asarray(positions, dtype=int) + offset
        flags[touched[(touched >= 0) & (touched < size)]] = True
    return flags


@pytest.fixture(scope="module")
def boundary(kiln_matrix) -> int:
    """A source-frame position with several hundred retained rows on either side of it."""
    positions = kiln_matrix.positions
    return int(positions[int(positions.size * BOUNDARY_FRACTION)])


@pytest.fixture(scope="module")
def perturbed_frame(kiln_frame, kiln_matrix, boundary) -> pd.DataFrame:
    """``kiln_frame`` with every modelled tag stepped by :data:`PERTURBATION` after ``boundary``."""
    return perturb_after(kiln_frame, boundary, kiln_matrix.spec.base_columns)


@pytest.fixture(scope="module")
def perturbed_matrix(kiln_builder, perturbed_frame, kiln_matrix):
    """The same feature build, over the perturbed frame - rebuilt from scratch, not patched."""
    return kiln_builder.build(perturbed_frame, kiln_matrix.spec.horizon_min)


# -- temporal leakage: the features (PRD 13.1) -----------------------------------------------
def test_the_perturbation_leaves_the_retained_row_set_alone(kiln_matrix, perturbed_matrix):
    """Groundwork for everything below: the two builds must be row-for-row comparable.

    An additive step changes no value's presence, so the lag warm-up, the startup exclusion and the
    dropped-label rules all land on the same rows. If that ever stops holding, the perturbation tests
    would be comparing different rows and quietly weaken - so it is asserted rather than assumed.
    """
    np.testing.assert_array_equal(perturbed_matrix.positions, kiln_matrix.positions)
    assert perturbed_matrix.dropped_rows == kiln_matrix.dropped_rows
    assert tuple(perturbed_matrix.features.columns) == tuple(kiln_matrix.features.columns)


def test_no_feature_can_see_a_row_after_its_own_position(kiln_matrix, perturbed_matrix, boundary):
    """The central claim: features at ``p`` are a function of source rows ``<= p`` only.

    Bit-for-bit, not approximately. A 1000-unit step on every modelled tag after ``boundary`` has to
    leave every earlier feature vector untouched in full - all lag blocks, all regime columns.
    """
    positions = kiln_matrix.positions
    earlier = positions[positions <= boundary]
    assert earlier.size > 100, "too few rows before the boundary for this to mean much"
    np.testing.assert_allclose(
        perturbed_matrix.features.loc[earlier].to_numpy(dtype=float),
        kiln_matrix.features.loc[earlier].to_numpy(dtype=float),
        rtol=0,
        atol=0,
    )

    # Converse: the step did reach the later rows, so the comparison above is not vacuous.
    later = positions[positions > boundary]
    assert later.size, "the boundary sits at the end of the frame"
    moved = perturbed_matrix.features.loc[later].to_numpy(dtype=float) != kiln_matrix.features.loc[
        later
    ].to_numpy(dtype=float)
    assert moved.any(), "the perturbation changed nothing at all - it never landed"


def test_the_label_reaches_exactly_the_horizon_and_no_further(
    kiln_matrix, perturbed_matrix, boundary
):
    """The label is the one thing that *must* move, and by a known amount at known rows.

    Row ``p``'s label is the measurement at ``p + h``, so a step applied after ``boundary`` moves the
    labels of rows ``p > boundary - h`` by exactly the step and leaves every earlier label alone. Both
    halves matter: the first says the horizon is real, the second says it is not longer than claimed.
    """
    spec = kiln_matrix.spec
    steps = spec.horizon_steps
    assert steps > 0
    assert ML_FIXTURE_TARGET in spec.base_columns, "the target is not among the perturbed tags"
    column = target_column(ML_FIXTURE_TARGET, spec.horizon_min)

    labelled = kiln_matrix.labelled_positions(ML_FIXTURE_TARGET)
    before = kiln_matrix.targets.loc[labelled, column].to_numpy(dtype=float)
    after = perturbed_matrix.targets.loc[labelled, column].to_numpy(dtype=float)
    reaches = labelled > boundary - steps

    assert reaches.any() and (~reaches).any(), "the boundary splits no labels either side"
    np.testing.assert_allclose(after[reaches] - before[reaches], PERTURBATION, rtol=1e-9)
    np.testing.assert_allclose(after[~reaches], before[~reaches], rtol=0, atol=0)


def test_the_build_does_not_need_the_rows_beyond_the_label_window(
    kiln_builder, kiln_frame, kiln_matrix, boundary
):
    """A structurally different proof: the later rows are not merely unused, they are not needed.

    Cut the frame just past the label window and rebuild. Perturbation catches a pipeline that *reads*
    the future; truncation catches one that *summarises* it - a column mean, a standard deviation, a
    quantile computed over the whole frame would survive the test above and die here.
    """
    steps = kiln_matrix.spec.horizon_steps
    cut = boundary + steps + 1
    assert cut < len(kiln_frame), "the boundary leaves nothing to truncate"
    truncated = kiln_builder.build(kiln_frame.iloc[:cut].copy(), kiln_matrix.spec.horizon_min)

    shared = np.intersect1d(truncated.positions, kiln_matrix.positions)
    shared = shared[shared <= boundary]
    assert shared.size > 100, f"only {shared.size} rows survived both builds"
    np.testing.assert_allclose(
        truncated.features.loc[shared].to_numpy(dtype=float),
        kiln_matrix.features.loc[shared].to_numpy(dtype=float),
        rtol=0,
        atol=0,
    )
    column = target_column(ML_FIXTURE_TARGET, kiln_matrix.spec.horizon_min)
    np.testing.assert_allclose(
        truncated.targets.loc[shared, column].to_numpy(dtype=float),
        kiln_matrix.targets.loc[shared, column].to_numpy(dtype=float),
        rtol=0,
        atol=0,
    )


# -- target leakage (PRD 13.1) ---------------------------------------------------------------
def test_no_feature_column_is_the_target_read_back_from_the_future(
    kiln_builder, kiln_matrix, kiln_frame
):
    """No input may equal a target's value at any future offset the horizon grid uses.

    This is the leak the reserved ``target__`` prefix is meant to prevent, checked numerically over
    the values instead of the names: a column built by some other route - a mislabelled shift, a tag
    that is itself a delayed copy - would carry the same values under an innocent name.

    Exact equality is the right test. High correlation between a tag now and a target soon is the
    process being physical; only identity is leakage.
    """
    spec = kiln_matrix.spec
    positions = kiln_matrix.positions
    interval = spec.sampling_interval_min
    offsets = sorted(
        {1, max(1, spec.horizon_steps // 2), spec.horizon_steps}
        | {int(round(horizon / interval)) for horizon in kiln_builder.horizons_min}
    )
    assert offsets and min(offsets) >= 1

    checked = 0
    for target in spec.targets:
        source = kiln_frame[target].astype(float)
        for offset in offsets:
            future = source.shift(-offset).reindex(positions).to_numpy(dtype=float)
            usable = np.isfinite(future)
            if usable.sum() < 50:
                continue
            for name in spec.feature_names:
                values = kiln_matrix.features[name].to_numpy(dtype=float)[usable]
                if not np.isfinite(values).all():
                    continue
                checked += 1
                assert not np.allclose(values, future[usable], rtol=1e-9, atol=1e-9), (
                    f"feature {name!r} equals {target} at t+{offset * interval:g}min"
                )
    assert checked >= len(spec.feature_names), (
        f"only {checked} comparisons ran across {len(spec.feature_names)} feature columns - "
        "the finite-value filters ate the test"
    )


# -- temporal leakage: the splits (PRD 13.3) -------------------------------------------------
def test_the_chronological_blocks_windows_do_not_overlap_at_all(kiln_matrix, kiln_splits):
    """The embargo, stated as the leakage it prevents rather than as a row count.

    A training row at ``p`` has seen source rows ``[p - max_lag, p + h]``; an evaluated row at ``q``
    will read ``[q - max_lag, q + h]``. Non-overlap of those two spans is what the purge buys, and
    since both blocks are contiguous and ordered it is enough to check the closest pair of rows.
    """
    spec = kiln_matrix.spec
    back, forward = spec.max_lag_steps, spec.horizon_steps
    assert back > 0 and forward > 0, "no lag or no horizon leaves nothing to embargo"
    split = kiln_splits[CHRONOLOGICAL]
    for earlier, later in ((split.train, split.validation), (split.validation, split.test)):
        assert earlier.size and later.size
        assert int(earlier.max()) + forward < int(later.min()) - back, (
            "the last training row's label window reaches the next block's lag window"
        )


def test_no_evaluated_rows_label_is_an_observation_the_training_block_has_seen(
    kiln_matrix, kiln_frame, kiln_splits
):
    """Target leakage across blocks: the answer must not be in the question.

    Every evaluated row's label is one specific source observation, ``q + h``. None of those
    observations may fall inside the training block's read window - not as a training label, and not
    as a lag column either.
    """
    spec = kiln_matrix.spec
    back, forward = spec.max_lag_steps, spec.horizon_steps
    size = len(kiln_frame)
    split = kiln_splits[CHRONOLOGICAL]
    seen = read_window(split.train, back=back, forward=forward, size=size)

    evaluated = np.concatenate([split.validation, split.test])
    label_rows = evaluated + forward
    label_rows = label_rows[label_rows < size]
    assert label_rows.size > 100, "too few evaluated labels to check"
    assert not seen[label_rows].any(), "an evaluated label sits inside the training read window"


def test_the_training_block_never_reads_an_observation_from_a_withheld_regime(
    kiln_matrix, kiln_frame, kiln_splits, ml_config
):
    """PRD 13.3 split 2, in source time: withheld means the model never saw those minutes at all.

    Checked at every offset the feature vector actually reaches - each configured lag, the current
    row, and the label - rather than through the matrix-row arithmetic the split helper uses, so a
    confusion between matrix rows and source rows would show up here as a hit.

    One residual is worth stating plainly: the purge can only see withheld rows the matrix *retained*.
    A withheld minute dropped earlier (a PRD 11.5 hole, or a missing label) is invisible to it and a
    training row's lag column may still touch that minute's tags. It is an input observation, never a
    withheld label paired with its own features, so it cannot inflate the holdout metrics - but it is
    a limitation of the phrase "never trained on", and it is recorded as one in the assumptions log.
    """
    holdout = [str(name) for name in ml_config.get_path("splits.scenario_holdout_regimes")]
    assert holdout, "PRD 13.3 requires at least one withheld regime"
    spec = kiln_matrix.spec
    train = kiln_splits[SCENARIO_HOLDOUT].train
    assert train.size, "nothing left to train on"

    withheld = np.zeros(len(kiln_frame), dtype=bool)
    retained = kiln_matrix.positions[np.isin(kiln_matrix.regime.astype(str).to_numpy(), holdout)]
    assert retained.size, f"the run contains none of {holdout}, so this test is vacuous"
    withheld[retained] = True

    offsets = [-spec.lag_steps(lag) for lag in spec.lags_min] + [0, spec.horizon_steps]
    for offset in offsets:
        touched = train + offset
        touched = touched[(touched >= 0) & (touched < len(kiln_frame))]
        hits = int(withheld[touched].sum())
        assert hits == 0, f"{hits} training rows read a withheld minute at offset {offset:+d}"


def test_each_fitted_model_trained_on_the_purged_positions_it_was_handed(trained_kiln):
    """The split helpers being right is one claim; the fitted models having used them is another.

    Read back from the model object itself - the positions it kept are the positions it fitted on -
    and re-derive the split from its own matrix rather than a fixture, so this holds at every horizon
    in the run and not only the one the shared fixtures happen to build.

    The shipped estimators are the *chronological* fit, so the withheld regimes are deliberately not
    excluded here: PRD 13.3 split 2 gets its own fit on its own purged block (verified above), used
    for its metrics and then discarded. Asserting the shipped model had never seen a withheld regime
    would be asserting the wrong thing about the wrong fit.
    """
    for (target, horizon), model in trained_kiln.models.items():
        assert model._training is not None, (
            f"{target}/t+{horizon}min released its training block during training; the PRD 13.1.1 "
            "bootstrap ensemble and the training-domain record both need it"
        )
        matrix, fitted = model._training
        assert fitted.size and list(fitted) == sorted(fitted)
        chronological = build_splits(matrix)[CHRONOLOGICAL]
        back, forward = matrix.spec.max_lag_steps, matrix.spec.horizon_steps

        offered = set(chronological.train.tolist())
        assert set(fitted.tolist()) <= offered, "the model fitted on rows the split did not offer it"
        for block in (chronological.validation, chronological.test):
            assert not set(fitted.tolist()) & set(block.tolist())
        assert int(fitted.max()) + forward < int(chronological.test.min()) - back
        # Every fitted row carries a real label for *this* target - none were filled in.
        assert set(fitted.tolist()) <= set(matrix.labelled_positions(target).tolist())


# -- Model A at prediction time (PRD 13.1, 13.1.1) -------------------------------------------
@pytest.fixture(scope="module")
def fixture_model(trained_kiln, kiln_matrix):
    """The trained model whose horizon matches the shared feature matrix."""
    return trained_kiln.model(ML_FIXTURE_TARGET, kiln_matrix.spec.horizon_min)


@pytest.fixture(scope="module")
def compared_positions(kiln_matrix, boundary) -> np.ndarray:
    """A thinned sample of retained rows at or before the boundary - enough rows, few enough fits."""
    earlier = kiln_matrix.positions[kiln_matrix.positions <= boundary]
    return earlier[:: max(1, earlier.size // 200)]


def test_a_prediction_at_row_p_is_unchanged_when_the_future_changes(
    fixture_model, kiln_matrix, perturbed_matrix, compared_positions
):
    """The same claim as the feature test, carried through the estimator to the number a user sees."""
    assert compared_positions.size > 20
    before = fixture_model.predict(kiln_matrix.X(compared_positions))
    after = fixture_model.predict(perturbed_matrix.X(compared_positions))
    assert np.isfinite(before).all()
    np.testing.assert_allclose(after, before, rtol=PREDICT_RTOL, atol=0)


def test_the_uncertainty_at_row_p_is_unchanged_when_the_future_changes(
    fixture_model, kiln_matrix, perturbed_matrix, compared_positions
):
    """PRD 13.1.1's spread is a function of the same inputs, so it inherits the same constraint.

    Worth its own test rather than an inference: the ensemble spread and the bootstrap ensemble are a
    second path through the fitted objects, and a resampling method is exactly the kind of place a
    whole-frame statistic could creep in unnoticed.
    """
    before, method = fixture_model.uncertainty(kiln_matrix.X(compared_positions))
    after, method_after = fixture_model.uncertainty(perturbed_matrix.X(compared_positions))
    assert method == method_after
    np.testing.assert_allclose(after, before, rtol=PREDICT_RTOL, atol=0)


def test_the_uncertainty_is_a_spread_in_target_units_not_a_score(
    fixture_model, kiln_matrix, compared_positions
):
    """A spread has units and a width; a confidence percentage has neither (PRD 13.1.1, 15)."""
    features = kiln_matrix.X(compared_positions)
    spread, method = fixture_model.uncertainty(features)
    assert np.isfinite(spread).all() and (spread >= 0.0).all()
    assert (spread > 0.0).any(), "a zero spread everywhere is not an uncertainty estimate"
    assert method and "%" not in method

    for prediction in fixture_model.predictions(features)[:20]:
        low, high = prediction.interval
        assert low <= prediction.value <= high
        assert high - low == pytest.approx(2.0 * prediction.uncertainty)
        assert prediction.unit and "%" not in prediction.unit
        assert prediction.uncertainty_method == method


# -- Model B at prediction time (PRD 13.2) ---------------------------------------------------
@pytest.fixture(scope="module")
def detector_frame(kiln_frame, kiln_detector, boundary) -> pd.DataFrame:
    """``kiln_frame`` with every monitored tag stepped after ``boundary``, for the fitted detector.

    The forest is *not* refitted here, and that is the point: at prediction time the fit is history,
    so the only question is whether scoring row ``i`` consults anything after ``i``.
    """
    return perturb_after(kiln_frame, boundary, kiln_detector.tags)


def test_the_forest_score_at_row_i_is_unchanged_when_the_future_changes(
    kiln_frame, detector_frame, kiln_detector, boundary
):
    """PRD 13.2 Method 1 is a per-row scoring of instantaneous values - so it must be exactly that."""
    before = kiln_detector.scorer.score(kiln_frame)
    after = kiln_detector.scorer.score(detector_frame)
    earlier = kiln_frame.index[kiln_frame.index <= boundary]
    later = kiln_frame.index[kiln_frame.index > boundary]

    np.testing.assert_allclose(
        after.score.loc[earlier].to_numpy(dtype=float),
        before.score.loc[earlier].to_numpy(dtype=float),
        rtol=0,
        atol=0,
    )
    np.testing.assert_array_equal(
        after.flagged.loc[earlier].to_numpy(), before.flagged.loc[earlier].to_numpy()
    )
    np.testing.assert_array_equal(
        after.out_of_distribution.loc[earlier].to_numpy(),
        before.out_of_distribution.loc[earlier].to_numpy(),
    )
    # Converse: a 1000-unit step is far outside the training ranges, so it must move the tail.
    assert (
        after.score.loc[later].to_numpy(dtype=float)
        != before.score.loc[later].to_numpy(dtype=float)
    ).any()
    assert bool(after.out_of_distribution.loc[later].any()), "the step was not even judged unusual"


def test_the_spc_statistics_at_row_i_are_unchanged_when_the_future_changes(
    kiln_frame, detector_frame, kiln_detector, boundary
):
    """Method 2 is a rolling baseline and an EWMA - both of which are easy to write acausally."""
    before = kiln_detector.spc(kiln_frame)
    after = kiln_detector.spc(detector_frame)
    earlier = kiln_frame.index[kiln_frame.index <= boundary]
    for name in ("z_score", "ewma_deviation", "baseline_mean", "baseline_sigma"):
        first = getattr(before, name).loc[earlier].to_numpy(dtype=float)
        second = getattr(after, name).loc[earlier].to_numpy(dtype=float)
        np.testing.assert_array_equal(np.isnan(first), np.isnan(second))
        finite = ~np.isnan(first)
        np.testing.assert_allclose(second[finite], first[finite], rtol=0, atol=0)

    later = kiln_frame.index[kiln_frame.index > boundary]
    assert bool(after.any_out_of_band.loc[later].any()), "the step broke no control limit"


def test_the_spc_baseline_never_includes_the_row_it_judges(kiln_frame, kiln_detector):
    """A control chart whose limits contain the sample cannot flag it - the baseline is shifted by one.

    Recomputed here from the raw frame rather than trusted: the mean at row ``i`` must be the mean of
    the ``window`` rows strictly before ``i``, and the sigma likewise.
    """
    result = kiln_detector.spc(kiln_frame)
    window = kiln_detector.spc_monitor.window_rows()
    tag = kiln_detector.tags[0]
    values = kiln_frame[tag].astype(float)

    positions = [p for p in kiln_frame.index if p > 4 * window][:: max(1, len(kiln_frame) // 40)]
    assert positions, "no rows past the warm-up window"
    compared = 0
    for position in positions:
        expected = values.iloc[position - window : position]
        if not np.isfinite(expected.to_numpy()).all():
            continue  # a PRD 11.5 hole in the baseline window - pandas skips it, so skip it here too
        recorded = result.baseline_mean.loc[position, tag]
        if not np.isfinite(recorded):
            continue
        assert recorded == pytest.approx(float(expected.mean()), rel=1e-9)
        compared += 1
    assert compared > 5, f"only {compared} baselines were comparable"


def test_the_report_for_row_i_is_unchanged_when_the_future_changes(
    kiln_frame, detector_frame, kiln_detector, boundary
):
    """End to end: the PRD 15 block a UI would print for a past minute cannot be edited by later data.

    ``render()`` is compared as a whole string, so the status, the classification, the hypothesis, the
    ranked variables with their z-scores and the suggested action all have to land identically - the
    strongest form of the claim that matters to an operator reading a historical alarm.
    """
    scores = kiln_detector.scorer.score(kiln_frame)
    earlier = kiln_frame.index[kiln_frame.index <= boundary]
    flagged = [p for p in earlier if bool(scores.flagged.loc[p])]
    quiet = [p for p in earlier if not bool(scores.flagged.loc[p])]
    assert flagged and quiet, "the pre-boundary stretch has no anomaly or no normal row to compare"

    for position in (flagged[len(flagged) // 2], quiet[len(quiet) // 2]):
        before = kiln_detector.report(kiln_frame, position)
        after = kiln_detector.report(detector_frame, position)
        assert after.render() == before.render()
        assert after.anomaly_score == before.anomaly_score
        assert after.ood_ratio == before.ood_ratio
        assert after.anomaly_kind == before.anomaly_kind
        assert after.out_of_distribution == before.out_of_distribution


# -- reproducibility (NFR-4) -----------------------------------------------------------------
def test_the_features_and_the_splits_are_reproducible_from_the_same_frame(
    kiln_builder, kiln_frame, kiln_matrix, kiln_splits
):
    """Everything upstream of a fitted estimator is arithmetic, so it must repeat exactly.

    ``test_model_a.py`` and ``test_model_b_anomaly.py`` carry the fitted-model half of NFR-4; this is
    the half that has no excuse for any tolerance at all.
    """
    rebuilt = kiln_builder.build(kiln_frame, kiln_matrix.spec.horizon_min)
    np.testing.assert_array_equal(rebuilt.positions, kiln_matrix.positions)
    np.testing.assert_allclose(
        rebuilt.features.to_numpy(dtype=float),
        kiln_matrix.features.to_numpy(dtype=float),
        rtol=0,
        atol=0,
    )
    again = build_splits(rebuilt)
    assert set(again) == set(kiln_splits)
    for name, split in kiln_splits.items():
        for block in ("train", "validation", "test"):
            np.testing.assert_array_equal(getattr(again[name], block), getattr(split, block))
        assert again[name].purged == split.purged
        assert again[name].embargo_min == split.embargo_min


def test_the_startup_ramp_is_not_what_makes_these_tests_pass(kiln_frame, kiln_matrix, boundary):
    """A guard on the fixture rather than on the code.

    Every test above compares a stretch of rows either side of ``boundary``. If that stretch were all
    startup ramp, or all one regime, the comparisons would still pass and mean far less - so the run
    is checked to be varied where it is being measured.
    """
    startup = startup_regime_name()
    regimes = kiln_matrix.regime.astype(str)
    earlier = kiln_matrix.positions[kiln_matrix.positions <= boundary]
    seen = set(regimes.loc[earlier].tolist())
    assert len(seen) >= 3, f"only {sorted(seen)} appear before the boundary"
    assert startup not in seen, "the startup ramp should already have been dropped"
    assert kiln_frame.loc[earlier, "injected_fault"].notna().any(), (
        "no fault rows before the boundary - the causality tests never cross an anomaly"
    )
