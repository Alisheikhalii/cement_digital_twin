"""Feature construction and the two PRD 13.3 splits (PRD v1.1.1 Sections 13.1, 13.3).

This module pins the *shape* of the ML layer's inputs - what a feature vector is allowed to
contain, what a label is, and how the two evaluation splits are cut. The causality argument
itself (that no feature can see past ``t``) is made numerically in ``test_ml_leakage.py``; here
the concern is that the layout, the lag-sizing rule, the label handling and the split geometry
are the ones PRD 13.1/13.3 specify.

Nothing in this module asserts a metric value. A test that pins MAE pins the simulator, and the
whole point of the split machinery is that the numbers are allowed to move when the data does.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.features.lag_features import (
    REGIME_PREFIX,
    TARGET_PREFIX,
    is_target_column,
    lag_column,
    regime_categories,
    startup_regime_name,
    target_column,
    window_touches,
)
from src.features.splits import (
    CHRONOLOGICAL,
    SCENARIO_HOLDOUT,
    build_splits,
    chronological_split,
    embargo_minutes,
    scenario_holdout_split,
    split_coverage,
    subsample_positions,
)


# -- the feature layout (PRD 13.1) ----------------------------------------------------------
def test_the_feature_frame_is_exactly_the_specs_columns_in_order(kiln_matrix):
    spec = kiln_matrix.spec
    assert tuple(kiln_matrix.features.columns) == spec.feature_names
    assert len(spec.feature_names) == len(set(spec.feature_names)), "duplicate feature column"
    assert kiln_matrix.features.shape[1] == spec.describe()["feature_count"]


def test_no_feature_column_is_a_horizon_target(kiln_matrix):
    """The reserved prefix is the mechanism; this is the assertion that it holds in practice."""
    assert not any(is_target_column(column) for column in kiln_matrix.features.columns)
    assert not any(str(column).startswith(TARGET_PREFIX) for column in kiln_matrix.features.columns)
    assert all(str(column).startswith(TARGET_PREFIX) for column in kiln_matrix.targets.columns)


def test_the_lag_blocks_are_shifted_copies_of_the_current_values(kiln_matrix):
    """``lag_column(c, L)`` at row ``p`` must be ``c`` at row ``p - L`` and nothing else."""
    spec = kiln_matrix.spec
    features = kiln_matrix.features
    assert spec.lags_min, "the configured lag set is empty - there is nothing to check"
    for lag in spec.lags_min:
        steps = spec.lag_steps(lag)
        for column in spec.base_columns[:4]:  # four tags is enough; the shift is one operation
            lagged = features[lag_column(column, lag)]
            # Compare on the source-frame positions the matrix retained: position p of the lag
            # column must equal position p-steps of the current-value column.
            shared = [p for p in features.index if (p - steps) in features.index]
            assert shared, "no overlapping positions to compare"
            expected = features.loc[[p - steps for p in shared], column].to_numpy()
            np.testing.assert_allclose(lagged.loc[shared].to_numpy(), expected, rtol=0, atol=0)


def test_the_horizon_target_is_the_measured_value_at_t_plus_horizon(kiln_matrix, kiln_frame):
    spec = kiln_matrix.spec
    steps = spec.horizon_steps
    for target in spec.targets:
        column = target_column(target, spec.horizon_min)
        labelled = kiln_matrix.labelled_positions(target)
        assert labelled.size, f"{target} has no labelled rows"
        sample = labelled[:: max(1, labelled.size // 200)]
        expected = kiln_frame.loc[[p + steps for p in sample], target].to_numpy(dtype=float)
        np.testing.assert_allclose(
            kiln_matrix.targets.loc[sample, column].to_numpy(dtype=float), expected
        )


def test_the_lag_set_follows_the_configured_sizing_rule(kiln_builder, ml_config):
    """PRD 13.1 asks for lags "sized appropriately per horizon"; the rule is a config choice."""
    configured = sorted(int(value) for value in ml_config.get_path("features.lags_min"))
    rule = str(ml_config.get_path("features.lag_sizing", "all")).lower()
    for horizon in kiln_builder.horizons_min:
        lags = kiln_builder.lags_for(horizon)
        assert lags, f"t+{horizon}min ended up with no lag features at all"
        assert set(lags) <= set(configured)
        assert list(lags) == sorted(lags)
        if rule == "horizon_scaled":
            longer = [lag for lag in lags if lag > horizon]
            assert not longer or lags == (configured[0],), (
                f"t+{horizon}min kept lags longer than its own horizon: {longer}"
            )
    if rule == "horizon_scaled":
        shortest, longest = min(kiln_builder.horizons_min), max(kiln_builder.horizons_min)
        assert len(kiln_builder.lags_for(shortest)) <= len(kiln_builder.lags_for(longest))


def test_the_regime_one_hot_covers_every_configured_regime(kiln_matrix, scenario_config):
    spec = kiln_matrix.spec
    if not spec.include_operating_regime:
        pytest.skip("features.include_operating_regime is off in this configuration")
    one_hot = [c for c in kiln_matrix.features.columns if str(c).startswith(REGIME_PREFIX)]
    assert len(one_hot) == len(regime_categories(scenario_config))
    values = kiln_matrix.features[one_hot].to_numpy(dtype=float)
    assert set(np.unique(values)) <= {0.0, 1.0}
    # At most one regime is running at a time, and an unknown label leaves every column at zero.
    assert values.sum(axis=1).max() <= 1.0


# -- label handling (PRD 11.5 dropout, 13.1) ------------------------------------------------
def test_a_missing_label_is_dropped_rather_than_filled(kiln_matrix):
    """Forward-filling a *label* would invent an observation - only inputs may be held."""
    spec = kiln_matrix.spec
    for target in spec.targets:
        column = target_column(target, spec.horizon_min)
        series = kiln_matrix.targets[column]
        labelled = set(kiln_matrix.labelled_positions(target).tolist())
        missing = set(series.index[series.isna()].tolist())
        assert not (labelled & missing)
        assert labelled | missing == set(series.index.tolist())


def test_every_retained_row_has_a_complete_feature_vector(kiln_matrix):
    assert not kiln_matrix.features.isna().any().any()
    dropped = kiln_matrix.dropped_rows
    assert dropped["retained"] == len(kiln_matrix)
    assert dropped["total_rows"] >= dropped["retained"] + dropped["lag_warm_up"]


def test_the_startup_ramp_is_kept_out_of_the_feature_matrix(kiln_matrix, scenario_config):
    """PRD 11.4's startup transition is a scripted ramp, not one of the 14 regimes."""
    startup = startup_regime_name(scenario_config)
    assert kiln_matrix.dropped_rows["startup_window"] > 0, (
        "the run contains no startup ramp, so this test is vacuous"
    )
    assert startup not in set(kiln_matrix.regime.dropna().astype(str))
    assert startup not in set(kiln_matrix.target_regime.dropna().astype(str))


def test_window_touches_marks_the_whole_lag_and_horizon_window():
    """``[i - back, i + forward]``, in that orientation.

    Pinned asymmetrically on purpose: with ``back == forward`` an inverted pad is invisible, and
    the two real call sites (startup exclusion, scenario holdout) pass ``back=max_lag_steps,
    forward=horizon_steps`` - unequal at every horizon but the shortest.
    """
    flags = np.zeros(12, dtype=bool)
    flags[6] = True
    assert np.flatnonzero(window_touches(flags, back=2, forward=3)).tolist() == [3, 4, 5, 6, 7, 8]
    assert np.flatnonzero(window_touches(flags, back=0, forward=3)).tolist() == [3, 4, 5, 6]
    assert np.flatnonzero(window_touches(flags, back=3, forward=0)).tolist() == [6, 7, 8, 9]
    assert np.flatnonzero(window_touches(flags, back=0, forward=0)).tolist() == [6]
    assert window_touches(np.zeros(5, dtype=bool), back=2, forward=2).sum() == 0
    assert window_touches(np.array([], dtype=bool), back=2, forward=2).size == 0


# -- the two PRD 13.3 splits ----------------------------------------------------------------
def test_both_documented_splits_are_produced(kiln_splits):
    assert set(kiln_splits) == {CHRONOLOGICAL, SCENARIO_HOLDOUT}


def test_the_chronological_split_is_ordered_train_validation_test(kiln_matrix, ml_config):
    """PRD 13.3 split 1: the validation block sits at the *end* of the training span."""
    split = chronological_split(kiln_matrix)
    assert split.train.size and split.validation.size and split.test.size
    assert split.train.max() < split.validation.min()
    assert split.validation.max() < split.test.min()
    fraction = float(ml_config.get_path("splits.chronological_train_fraction"))
    train_share = (split.train.size + split.validation.size) / len(kiln_matrix)
    assert train_share == pytest.approx(fraction, abs=0.05)


def test_the_chronological_blocks_are_separated_by_the_embargo(kiln_matrix):
    """A training row may neither label into the next block nor read back into it."""
    split = chronological_split(kiln_matrix)
    purge = embargo_minutes(kiln_matrix) / kiln_matrix.spec.sampling_interval_min
    assert purge > 0
    for earlier, later in ((split.train, split.validation), (split.validation, split.test)):
        assert int(later.min()) - int(earlier.max()) >= purge, (
            "consecutive blocks are closer than the embargo width"
        )
    assert split.purged > 0
    assert split.embargo_min == pytest.approx(
        kiln_matrix.spec.horizon_min + kiln_matrix.spec.max_lag_min
    ) or split.embargo_min == pytest.approx(embargo_minutes(kiln_matrix))


def test_no_row_appears_in_two_blocks_of_either_split(kiln_splits):
    for split in kiln_splits.values():
        blocks = [set(split.train.tolist()), set(split.validation.tolist()), set(split.test.tolist())]
        for first in range(len(blocks)):
            for second in range(first + 1, len(blocks)):
                assert not blocks[first] & blocks[second]


def test_the_scenario_holdout_withholds_whole_regimes_from_training(kiln_matrix, ml_config):
    """PRD 13.3 split 2: at least one entire labelled regime is never trained on."""
    holdout = [str(name) for name in ml_config.get_path("splits.scenario_holdout_regimes")]
    assert holdout, "no scenario holdout is configured - PRD 13.3 requires at least one regime"
    split = scenario_holdout_split(kiln_matrix)
    present = [name for name in holdout if name in set(kiln_matrix.regime.dropna().astype(str))]
    assert present, f"the run contains none of {holdout}, so this test is vacuous"

    regime = kiln_matrix.regime.astype(str)
    test_regimes = set(regime.loc[split.test].tolist())
    assert test_regimes <= set(present)
    train_regimes = set(regime.loc[split.train].tolist())
    assert not train_regimes & set(present), "a holdout regime leaked into the training block"
    assert split.validation.size == 0, "the holdout split selects nothing; it only measures"


def test_the_scenario_holdout_also_purges_the_rows_whose_window_touches_it(kiln_matrix):
    """A row outside the regime whose lag window or label reaches into it is not trainable either."""
    split = scenario_holdout_split(kiln_matrix)
    assert split.purged > 0
    trainable = set(split.train.tolist())
    withheld = set(split.test.tolist())
    back = kiln_matrix.spec.max_lag_steps
    forward = kiln_matrix.spec.horizon_steps
    for position in sorted(withheld)[:: max(1, len(withheld) // 50)]:
        for offset in range(-forward, back + 1):
            assert position + offset not in trainable, (
                f"training row {position + offset} is within the holdout window of {position}"
            )


def test_split_coverage_reports_the_regimes_each_block_contains(kiln_matrix, kiln_splits):
    coverage = split_coverage(kiln_matrix, kiln_splits, target=kiln_matrix.spec.targets[0])
    for name, split in kiln_splits.items():
        blocks = coverage[name]
        for block in ("train", "validation", "test"):
            entry = blocks[block]
            assert entry["rows"] == split.sizes[block]
            if entry["rows"] == 0:  # the holdout split has no validation block, by design
                assert set(entry) == {"rows"}
                continue
            assert entry["regimes"] == len(entry["regime_rows"])
            assert sum(entry["regime_rows"].values()) == split.sizes[block]
            assert "target_std" in entry and "target_mean" in entry
    assert coverage[CHRONOLOGICAL]["train"]["regimes"] >= 1


def test_subsampling_keeps_chronological_order_and_never_invents_positions(kiln_splits):
    train = kiln_splits[CHRONOLOGICAL].train
    limit = max(1, train.size // 3)
    kept = subsample_positions(train, limit)
    assert 0 < kept.size <= limit
    assert list(kept) == sorted(kept)
    assert set(kept.tolist()) <= set(train.tolist())
    # Deterministic (NFR-4) and anchored at the recent end by default.
    np.testing.assert_array_equal(kept, subsample_positions(train, limit))
    assert kept[-1] == train[-1]
    assert subsample_positions(train, train.size + 10).size == train.size
