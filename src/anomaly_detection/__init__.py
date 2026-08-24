"""Anomaly detection (PRD v1.1.1 Sections 13.2, 15).

Isolation Forest + per-tag SPC/EWMA wrappers, the anomaly explanation contract of
Section 15, and the ``DemoInjector`` behind the "Inject abnormal condition" control
(FR-10). The same scorer is the optimizer's out-of-distribution gate (Section 14.3) -
one implementation, two consumers.
"""

from src.anomaly_detection.detector import (
    INCONCLUSIVE_HYPOTHESIS,
    NO_ANOMALY,
    NO_RULE_ENGINE_ACTION,
    PROCESS_ANOMALY,
    SENSOR_ANOMALY,
    UNCLASSIFIED,
    UNDETERMINED_ANOMALY,
    AnomalyDetector,
    AnomalyEvaluation,
    AnomalyReport,
    RegimeSignatures,
)
from src.anomaly_detection.isolation import (
    FAULT_COLUMN,
    METHOD,
    REGIME_COLUMN,
    AnomalyScorer,
    ScoreResult,
    normal_regime_names,
    normal_rows,
)
from src.anomaly_detection.spc import SpcLimits, SpcMonitor, SpcResult

__all__ = [
    "FAULT_COLUMN",
    "INCONCLUSIVE_HYPOTHESIS",
    "METHOD",
    "NO_ANOMALY",
    "NO_RULE_ENGINE_ACTION",
    "PROCESS_ANOMALY",
    "REGIME_COLUMN",
    "SENSOR_ANOMALY",
    "UNCLASSIFIED",
    "UNDETERMINED_ANOMALY",
    "AnomalyDetector",
    "AnomalyEvaluation",
    "AnomalyReport",
    "AnomalyScorer",
    "RegimeSignatures",
    "ScoreResult",
    "SpcLimits",
    "SpcMonitor",
    "SpcResult",
    "normal_regime_names",
    "normal_rows",
]
