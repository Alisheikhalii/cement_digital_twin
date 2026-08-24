"""Feature engineering shared by Model A and Model B (PRD v1.1.1 Section 13.1).

Lag-feature builders (current + t-1/t-5/t-15 min), one-hot operating-regime encoding and
the per-horizon feature/target windowing used for the 5/10/15/30 min horizons. Never adds
target-derived features - leakage prevention is a tested contract (Section 34).
"""

from src.features.lag_features import (
    REGIME_PREFIX,
    TARGET_PREFIX,
    FeatureBuilder,
    FeatureMatrix,
    FeatureSpec,
    feature_builders,
    is_target_column,
    lag_column,
    regime_categories,
    regime_column,
    sensor_layer_faults,
    startup_regime_name,
    target_column,
    window_touches,
)
from src.features.splits import (
    CHRONOLOGICAL,
    SCENARIO_HOLDOUT,
    SPLIT_NAMES,
    DataSplit,
    build_splits,
    chronological_split,
    embargo_minutes,
    scenario_holdout_split,
    split_table,
    subsample_positions,
)

__all__ = [
    "CHRONOLOGICAL",
    "DataSplit",
    "FeatureBuilder",
    "FeatureMatrix",
    "FeatureSpec",
    "REGIME_PREFIX",
    "SCENARIO_HOLDOUT",
    "SPLIT_NAMES",
    "TARGET_PREFIX",
    "build_splits",
    "chronological_split",
    "embargo_minutes",
    "feature_builders",
    "is_target_column",
    "lag_column",
    "regime_categories",
    "regime_column",
    "scenario_holdout_split",
    "sensor_layer_faults",
    "split_table",
    "startup_regime_name",
    "subsample_positions",
    "target_column",
    "window_touches",
]
