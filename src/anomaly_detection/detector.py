"""Model B - the anomaly-detection output contract of PRD v1.1.1 Section 15.

This module assembles the block PRD 15 specifies, field by field, out of the two methods of
Section 13.2:

* ``Detected anomaly`` - the nearest matching labelled regime, found by comparing the live SPC
  z-vector against per-regime signatures learned on the training block. When nothing matches well
  enough the report says :data:`UNCLASSIFIED` rather than naming a regime it does not resemble.
* ``Likely cause (model-based hypothesis)`` - phrased as a hypothesis, never a diagnosis, and split
  into the *sensor/data* versus *process* reading that PRD 11.4's regime 14 exists to test.
* ``Affected variables`` - the SPC z-score ranking, with the Isolation Forest's distance-from-
  training attribution available alongside it.
* ``Suggested action`` - supplied by the Section 14.6 rule engine and labelled as a rule-based
  suggestion. Until that engine is attached the field says so explicitly instead of inventing advice.

Everything the report consults is available at the moment of the report: the SPC statistics look
back only (``shift(1)`` inside :mod:`src.anomaly_detection.spc`), the forest is fitted on earlier
normal rows, and the regime signatures come from the training block. No field reads a future
observation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.anomaly_detection.isolation import (
    FAULT_COLUMN,
    REGIME_COLUMN,
    AnomalyScorer,
    ScoreResult,
    normal_rows,
)
from src.anomaly_detection.spc import SpcMonitor, SpcResult
from src.config import ML, SCENARIOS, Config, load_config
from src.features.lag_features import sensor_layer_faults, startup_regime_name
from src.labels import ANOMALY_HYPOTHESIS_LABEL, RULE_BASED_SUGGESTION_LABEL
from src.models.metrics import detection_metrics, per_class_recall

#: Used when the deviation matches no learned regime signature well enough (PRD 15 honesty rule).
UNCLASSIFIED = "Unclassified deviation"

#: The two readings the PRD 11.4 regime-14 test distinguishes.
SENSOR_ANOMALY = "sensor_or_data"
PROCESS_ANOMALY = "process"
NO_ANOMALY = "none"

#: Used when the SPC layer has no finite z-score for the row yet (inside the rolling warm-up) and
#: the sensor-versus-process signatures therefore cannot be measured at all. Saying so is the
#: honest answer; picking one of the two readings without evidence would not be.
UNDETERMINED_ANOMALY = "undetermined"

#: Placeholder for the field PRD 15 sources from the Section 14.6 rule engine.
NO_RULE_ENGINE_ACTION = (
    "No rule-engine suggestion available - the Section 14.6 rule engine is not attached."
)

#: Wording of the two hypotheses. Deliberately hedged: causality is only knowable in the simulator.
SENSOR_HYPOTHESIS = (
    "consistent with an instrument/data fault - the deviation drifts one way on a single tag, "
    "the manipulated variables are quiet, and physically coupled tags do not corroborate it"
)
PROCESS_HYPOTHESIS = (
    "consistent with a process deviation - the pattern of affected tags matches a process "
    "condition rather than a single drifting transmitter"
)

#: Used when the sensor signatures are satisfied but ``report_sensor_claim`` is off, because the
#: separation between the two readings was measured on generated data and is not there. PRD 15 wants
#: a hypothesis, not a diagnosis; a hypothesis the evidence cannot support is worse than none.
INCONCLUSIVE_HYPOTHESIS = (
    "the available evidence does not distinguish an instrument/data fault from a process deviation "
    "- the drift signatures are satisfied but they are not selective for this plant's sensor-fault "
    "magnitudes (see MODEL_CARD.md)"
)


class RegimeSignatures:
    """Mean SPC z-vector of each labelled abnormal regime, and the nearest-match lookup.

    ASSUMPTION (``anomaly.regime_signature`` in ``configs/ml.yaml``): PRD 15 asks for the "nearest
    matching regime" without naming a method. The signature of a regime is the mean z-vector of its
    rows *in the training block*, and a live z-vector is matched by cosine similarity - a shape
    comparison, so a mild and a severe episode of the same regime match the same signature. Only
    abnormal regimes get a signature: naming a normal regime as "the detected anomaly" would be a
    category error.
    """

    __slots__ = ("_min_rows", "_min_similarity", "_signatures", "_tags")

    def __init__(self, tags: Sequence[str], *, config: Config | None = None) -> None:
        ml = config if config is not None else load_config(ML)
        self._tags = tuple(str(tag) for tag in tags)
        self._min_rows = int(ml.get_path("anomaly.regime_signature.min_rows"))
        self._min_similarity = float(ml.get_path("anomaly.regime_signature.min_similarity"))
        self._signatures: dict[str, np.ndarray] = {}

    @property
    def regimes(self) -> tuple[str, ...]:
        return tuple(sorted(self._signatures))

    @property
    def min_similarity(self) -> float:
        return self._min_similarity

    def fit(
        self,
        z_score: pd.DataFrame,
        regime: pd.Series,
        fault: pd.Series,
        *,
        positions: Sequence[int] | np.ndarray | None = None,
    ) -> "RegimeSignatures":
        """Learn one signature per abnormal regime from the given (training) rows only."""
        frame = z_score if positions is None else z_score.loc[list(positions)]
        labels = regime.reindex(frame.index)
        faults = fault.reindex(frame.index)
        abnormal = faults.notna()
        self._signatures = {}
        for name in sorted({str(value) for value in labels[abnormal].dropna().tolist()}):
            rows = frame.loc[abnormal & (labels.astype(object) == name), list(self._tags)]
            usable = rows.dropna(how="all")
            if len(usable) < self._min_rows:
                continue
            self._signatures[name] = np.nan_to_num(
                usable.mean(axis=0).to_numpy(dtype=float), nan=0.0
            )
        return self

    def match(self, z_row: pd.Series) -> tuple[str | None, float, list[tuple[str, float]]]:
        """Nearest regime, its similarity, and the full ranking (best first)."""
        if not self._signatures:
            return None, float("nan"), []
        live = np.nan_to_num(
            z_row.reindex(list(self._tags)).to_numpy(dtype=float), nan=0.0
        )
        ranked = sorted(
            ((name, _cosine(live, signature)) for name, signature in self._signatures.items()),
            key=lambda item: (-item[1], item[0]),
        )
        best, similarity = ranked[0]
        if not np.isfinite(similarity) or similarity < self._min_similarity:
            return None, float(similarity), ranked
        return best, float(similarity), ranked

    def describe(self) -> dict[str, Any]:
        return {
            "regimes": list(self.regimes),
            "tags": list(self._tags),
            "min_rows": self._min_rows,
            "min_similarity": self._min_similarity,
            "detail": (
                "Mean SPC z-vector per labelled abnormal regime over the training block; matched "
                "by cosine similarity (ASSUMPTION, PRD 15 'nearest matching regime')."
            ),
        }


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    scale = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / scale) if scale > 0.0 else float("nan")


@dataclass(frozen=True, slots=True)
class AnomalyReport:
    """One row's Model B output, in exactly the fields PRD 15 specifies."""

    dataset: str
    timestamp: Any
    status: str
    detected_anomaly: str | None
    hypothesis: str
    affected_variables: tuple[dict[str, Any], ...]
    suggested_action: str
    anomaly_score: float
    flagged: bool
    out_of_distribution: bool
    ood_ratio: float
    anomaly_kind: str
    regime_similarity: float
    evidence: dict[str, Any]

    @property
    def is_anomaly(self) -> bool:
        return self.status != "NORMAL"

    def render(self) -> str:
        """The PRD 15 block, verbatim in shape and label wording."""
        if not self.is_anomaly:
            return "NORMAL\nNo anomaly detected."
        variables = ", ".join(
            f"{item['tag']} ({item['direction']}, z={item['z_score']:+.1f})"
            for item in self.affected_variables
        )
        return "\n".join(
            [
                self.status,
                f"Detected anomaly: {self.detected_anomaly or UNCLASSIFIED}",
                f"{ANOMALY_HYPOTHESIS_LABEL}: {self.hypothesis}",
                f"Affected variables: {variables or 'none above the control limits'}",
                f"{RULE_BASED_SUGGESTION_LABEL}: {self.suggested_action}",
            ]
        )

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "timestamp": str(self.timestamp),
            "status": self.status,
            "detected_anomaly": self.detected_anomaly,
            "hypothesis_label": ANOMALY_HYPOTHESIS_LABEL,
            "hypothesis": self.hypothesis,
            "affected_variables": [dict(item) for item in self.affected_variables],
            "suggested_action_label": RULE_BASED_SUGGESTION_LABEL,
            "suggested_action": self.suggested_action,
            "anomaly_score": self.anomaly_score,
            "flagged": self.flagged,
            "out_of_distribution": self.out_of_distribution,
            "ood_score_ratio": self.ood_ratio,
            "anomaly_kind": self.anomaly_kind,
            "regime_similarity": self.regime_similarity,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class AnomalyEvaluation:
    """PRD 22's Model B row: real precision/recall/F1/FPR against the injected ground truth."""

    dataset: str
    split: str
    rows: int
    scored_rows: int
    detection: dict[str, Any]
    per_regime_recall: dict[str, dict[str, Any]]
    sensor_discrimination: dict[str, Any]
    spc: dict[str, Any]
    scorer: dict[str, Any]

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "split": self.split,
            "rows": self.rows,
            "scored_rows": self.scored_rows,
            "detection": dict(self.detection),
            "per_regime_recall": {key: dict(value) for key, value in self.per_regime_recall.items()},
            "sensor_vs_process": dict(self.sensor_discrimination),
            "spc": dict(self.spc),
            "isolation_forest": dict(self.scorer),
        }


class AnomalyDetector:
    """Model B: the Isolation Forest, the SPC layer and the PRD 15 report they produce together."""

    __slots__ = (
        "_config",
        "_dataset",
        "_discrimination",
        "_inputs",
        "_interval",
        "_max_variables",
        "_scorer",
        "_sensor_faults",
        "_signatures",
        "_spc",
        "_startup",
        "_tags",
    )

    def __init__(
        self,
        dataset: str,
        *,
        tags: Sequence[str] | None = None,
        config: Config | None = None,
        scenarios: Config | None = None,
        sampling_interval_min: float = 1.0,
    ) -> None:
        from src.features.lag_features import FeatureBuilder

        self._config = config if config is not None else load_config(ML)
        scenario_config = scenarios if scenarios is not None else load_config(SCENARIOS)
        self._dataset = str(dataset)
        builder = FeatureBuilder(dataset, config=self._config, scenarios=scenario_config)
        self._tags = tuple(tags) if tags is not None else builder.base_columns
        self._inputs = tuple(
            str(name) for name in self._config.get_path(f"features.{dataset}_inputs")
        )
        self._interval = float(sampling_interval_min)
        self._startup = startup_regime_name(scenario_config)
        self._sensor_faults = sensor_layer_faults(scenario_config)
        self._discrimination = dict(
            self._config.get_path("anomaly.sensor_discrimination").to_dict()
        )
        self._max_variables = int(self._config.get_path("anomaly.affected_variables_max", 5))
        self._spc = SpcMonitor(self._tags, config=self._config)
        self._scorer = AnomalyScorer(self._dataset, self._tags, config=self._config)
        self._signatures = RegimeSignatures(self._tags, config=self._config)

    # -- accessors ----------------------------------------------------------------------
    @property
    def dataset(self) -> str:
        return self._dataset

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    @property
    def scorer(self) -> AnomalyScorer:
        return self._scorer

    @property
    def signatures(self) -> RegimeSignatures:
        return self._signatures

    @property
    def spc_monitor(self) -> SpcMonitor:
        return self._spc

    # -- fitting ------------------------------------------------------------------------
    def fit(
        self,
        frame: pd.DataFrame,
        *,
        positions: Sequence[int] | np.ndarray | None = None,
        spc: SpcResult | None = None,
    ) -> "AnomalyDetector":
        """Fit the forest and the regime signatures on ``positions`` (the training block) only.

        ``positions`` are index labels of ``frame``. The SPC layer itself has nothing to fit - its
        baseline is rolling and causal - but it is evaluated over the *whole* frame so that a
        training row's baseline is the same one it would have had live.
        """
        result = spc if spc is not None else self.spc(frame)
        index = frame.index if positions is None else pd.Index(list(positions))
        training = frame.loc[index]
        self._scorer.fit(training, normal=normal_rows(training, startup_regime=self._startup))
        regime, fault = self._labels(frame)
        self._signatures.fit(result.z_score, regime, fault, positions=list(index))
        return self

    @property
    def fitted(self) -> bool:
        return self._scorer.fitted

    def spc(self, frame: pd.DataFrame) -> SpcResult:
        """Run the Section 13.2 Method 2 control charts over ``frame``."""
        return self._spc.evaluate(frame, sampling_interval_min=self._interval)

    def _labels(self, frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """The two ground-truth columns, or all-null stand-ins when a frame carries none."""
        empty = pd.Series(np.nan, index=frame.index, dtype=object)
        regime = frame[REGIME_COLUMN] if REGIME_COLUMN in frame.columns else empty
        fault = frame[FAULT_COLUMN] if FAULT_COLUMN in frame.columns else empty
        return regime, fault

    def decision(self, scores: ScoreResult, spc: SpcResult) -> pd.Series:
        """The banner decision of PRD 15, as one series both the UI and the PRD 22 metrics use.

        PRD 13.2 names the Isolation Forest "Method 1 (primary)" and the SPC layer the secondary,
        always-on explanation of *which variable is out of band* - so the banner is the forest's
        decision and the charts supply the attribution.

        That division of labour is not asserted: :meth:`evaluate` scores this decision against the
        two it could have been - SPC alone, and the union of the two configured methods - on every
        run and publishes all of them under ``detection["alternates"]``, so the comparison can be
        read off the shipped ``reports/metrics/model_b_metrics.json`` rather than taken on trust.
        Raising the banner on control-chart violations as well only trades recall against
        false-positive rate (the numbers are in ``MODEL_CARD.md``), which is why it is not done.
        """
        _ = spc  # the charts explain the row; they do not vote on the banner (see above)
        return scores.flagged

    # -- evaluation (PRD 22 Model B row) -------------------------------------------------
    def evaluate(
        self,
        frame: pd.DataFrame,
        *,
        split: str,
        positions: Sequence[int] | np.ndarray | None = None,
        spc: SpcResult | None = None,
        scores: ScoreResult | None = None,
    ) -> AnomalyEvaluation:
        """Precision / recall / F1 / FPR of ``positions`` against the injected ground truth.

        Both statistics are computed over the whole frame first, so a row's baseline and score are
        the ones it would have had live, and only then restricted to the evaluated block.

        The startup ramp is reported on its own line instead of inside the metrics: it is not one of
        the PRD 11.4 regimes and carries no ``injected_fault``, but it was deliberately withheld
        from fitting (:func:`~src.anomaly_detection.isolation.normal_rows`), so counting the rows it
        flags as false positives would score the detector for doing what it was built to do.
        """
        control = spc if spc is not None else self.spc(frame)
        scored = scores if scores is not None else self._scorer.score(frame)
        index = frame.index if positions is None else pd.Index(list(positions))
        scorable = scored.score.reindex(index).notna().to_numpy(dtype=bool)
        regime, fault = self._labels(frame)
        startup = (regime.reindex(index).astype(str) == self._startup).to_numpy(dtype=bool)
        rows = index[scorable & ~startup]

        decided = self.decision(scored, control).reindex(rows).to_numpy(dtype=bool)
        out_of_band = control.any_out_of_band.reindex(rows).to_numpy(dtype=bool)
        truth = fault.reindex(rows).notna().to_numpy(dtype=bool)
        labels = regime.reindex(rows).to_numpy(dtype=object)
        ramp = index[scorable & startup]

        return AnomalyEvaluation(
            dataset=self._dataset,
            split=str(split),
            rows=int(len(index)),
            scored_rows=int(len(rows)),
            detection={
                **detection_metrics(truth, decided),
                "decision": "isolation_forest flagged (PRD 13.2 Method 1, primary)",
                "alternates": {
                    "spc_single_sample": detection_metrics(truth, out_of_band),
                    "forest_or_spc_single_sample": detection_metrics(truth, decided | out_of_band),
                    "out_of_distribution_gate": detection_metrics(
                        truth, scored.out_of_distribution.reindex(rows).to_numpy(dtype=bool)
                    ),
                },
                "startup_ramp": {
                    "regime": self._startup,
                    "rows": int(len(ramp)),
                    "flagged": int(
                        self.decision(scored, control).reindex(ramp).to_numpy(dtype=bool).sum()
                    ),
                    "detail": (
                        "Excluded from the metrics above: a legitimate transient that carries no "
                        "injected_fault and is deliberately not in the training set."
                    ),
                },
            },
            per_regime_recall=self._regime_recall(labels, decided, fault, rows),
            sensor_discrimination=self._discrimination_metrics(control, rows, fault, decided),
            spc=control.describe(),
            scorer=self._scorer.describe(),
        )

    def _regime_recall(
        self,
        labels: np.ndarray,
        decided: np.ndarray,
        fault: pd.Series,
        rows: pd.Index,
    ) -> dict[str, dict[str, Any]]:
        """Per-regime recall, marked with whether the regime is a fault *for this dataset*.

        ``operating_regime`` is the plant-level label on both datasets (FR-3) while
        ``injected_fault`` is set only on the unit a regime perturbs, so a mill-only regime appears
        here as a normal-operation row for the kiln. Without the flag the table reads like a pile of
        missed detections instead of the false-positive check it actually is.
        """
        recall = per_class_recall(labels, decided)
        faulted = fault.reindex(rows).notna().to_numpy(dtype=bool)
        for name, row in recall.items():
            mask = labels == name
            row["injected_fault_on_this_unit"] = bool(faulted[mask].any())
            row["metric"] = "recall" if row["injected_fault_on_this_unit"] else "false_positive_rate"
        return recall

    def _discrimination_metrics(
        self,
        control: SpcResult,
        rows: pd.Index,
        fault: pd.Series,
        decided: np.ndarray,
    ) -> dict[str, Any]:
        """How well the PRD 11.4 regime-14 test is passed: sensor as the positive class.

        Two scopes, because they answer different questions and the first alone can be empty:

        ``on_reported_rows``
            the operational scope - fault rows Model B actually raised a banner for. This is what an
            operator would ever see a reading for.
        ``on_all_fault_rows``
            the diagnostic scope - every fault row with control-chart evidence, reported or not. With
            the forest-only banner almost no sensor-drift row is reported at all (the forest does not
            detect regime 14), so without this scope the discrimination would show no positives and
            look untested rather than measured.

        Both score the *signature rule* (``sensor_signatures_satisfied``), not the emitted label, so
        the number stays meaningful whether or not ``report_sensor_claim`` lets the claim through.
        ``reported_kinds`` records what the UI actually says.
        """
        reported = {"actual": [], "called": [], "undetermined": 0}
        overall = {"actual": [], "called": [], "undetermined": 0}
        kinds: dict[str, int] = {}
        for position, flagged in zip(rows.tolist(), decided.tolist(), strict=True):
            label = fault.get(position)
            if label is None or pd.isna(label):
                continue
            kind, _, evidence = self._hypothesis(control, position)
            if flagged:
                kinds[kind] = kinds.get(kind, 0) + 1
            for bucket, applies in ((overall, True), (reported, bool(flagged))):
                if not applies:
                    continue
                if evidence.get("lead_tag") is None:
                    bucket["undetermined"] += 1
                    continue
                bucket["actual"].append(str(label) in self._sensor_faults)
                bucket["called"].append(bool(evidence["sensor_signatures_satisfied"]))

        def scored(bucket: dict[str, Any]) -> dict[str, Any]:
            payload = detection_metrics(
                np.asarray(bucket["actual"], dtype=bool),
                np.asarray(bucket["called"], dtype=bool),
            )
            payload["no_control_chart_evidence_rows"] = bucket["undetermined"]
            return payload

        return {
            "positive_class": SENSOR_ANOMALY,
            "sensor_layer_faults": sorted(self._sensor_faults),
            "on_reported_rows": scored(reported),
            "on_all_fault_rows": scored(overall),
            "reported_kinds": kinds,
            "sensor_claim_reported": bool(self._discrimination.get("report_sensor_claim", False)),
            "rule": dict(self._discrimination),
            "detail": (
                "Three ASSUMPTION signatures of anomaly.sensor_discrimination, measured on "
                "information available at the row itself: persistent one-sided displacement of the "
                "leading tag's EWMA control chart, quiet manipulated variables, and few "
                "corroborating out-of-band tags (PRD 11.4 regime 14 / PRD 15 hypothesis wording). "
                "Scored against injected_fault membership of features.sensor_layer_faults."
            ),
        }

    # -- sensor-versus-process hypothesis (PRD 11.4 regime 14, PRD 15 wording) -----------
    def _hypothesis(self, control: SpcResult, position: Any) -> tuple[str, str, dict[str, Any]]:
        """``(kind, hedged clause, evidence)`` for one row, from three configured signatures.

        The three signatures are always computed and always reported as evidence. Whether a
        satisfied set is allowed to *name* the sensor reading is governed by
        ``anomaly.sensor_discrimination.report_sensor_claim``, which is ``false`` because the
        separation was measured and is not there (see the config comment and the model card). With it
        off the row reads :data:`UNDETERMINED_ANOMALY` and the clause says the evidence is
        inconclusive - the honest version of a field PRD 15 forbids stating as a diagnosis.
        """
        rule = self._discrimination
        window = max(2, int(round(float(rule["drift_window_min"]) / self._interval)))
        z_row = control.z_score.loc[position]
        finite = z_row[np.isfinite(z_row.to_numpy(dtype=float))]
        if finite.empty:
            return (
                UNDETERMINED_ANOMALY,
                "no control-chart evidence yet - the rolling baseline is still warming up",
                {"lead_tag": None, "reason": "no finite SPC z-score for this row"},
            )

        lead = str(finite.abs().sort_values(ascending=False).index[0])
        monotone = control.monotone_fraction(position, lead, window)
        inputs = [tag for tag in self._inputs if tag in finite.index]
        input_deviation = float(finite[inputs].abs().max()) if inputs else 0.0
        out_of_band = [
            str(tag) for tag in control.out_of_band.columns
            if bool(control.out_of_band.loc[position, tag])
        ]
        corroborating = [tag for tag in out_of_band if tag != lead]

        drifts = monotone >= float(rule["min_monotone_fraction"])
        quiet_inputs = input_deviation <= float(rule["max_input_deviation_sigma"])
        local = len(corroborating) <= int(rule["max_corroborating_tags"])
        sensor = bool(drifts and quiet_inputs and local)
        claimable = bool(rule.get("report_sensor_claim", False))

        evidence = {
            "lead_tag": lead,
            "lead_z_score": float(z_row[lead]),
            "monotone_fraction": float(monotone),
            "max_input_deviation_sigma": input_deviation,
            "out_of_band_tags": out_of_band,
            "corroborating_tags": corroborating,
            "drift_window_rows": window,
            "signatures": {
                "drifts_one_way": bool(drifts),
                "manipulated_variables_quiet": bool(quiet_inputs),
                "deviation_is_local": bool(local),
            },
            "sensor_signatures_satisfied": sensor,
            "sensor_claim_reported": claimable,
            "thresholds": dict(rule),
        }
        if sensor and not claimable:
            return UNDETERMINED_ANOMALY, INCONCLUSIVE_HYPOTHESIS, evidence
        return (
            SENSOR_ANOMALY if sensor else PROCESS_ANOMALY,
            SENSOR_HYPOTHESIS if sensor else PROCESS_HYPOTHESIS,
            evidence,
        )

    # -- the PRD 15 report ---------------------------------------------------------------
    def report(
        self,
        frame: pd.DataFrame,
        position: Any = None,
        *,
        rule_engine: Callable[[Mapping[str, Any]], str | None] | None = None,
        spc: SpcResult | None = None,
        scores: ScoreResult | None = None,
    ) -> AnomalyReport:
        """The Section 15 block for one row (the last row of ``frame`` by default).

        ``rule_engine`` is the Section 14.6 hook: it receives the assembled evidence and returns the
        suggested action. Until it is attached the field states that no suggestion is available -
        Model B never invents advice of its own.
        """
        control = spc if spc is not None else self.spc(frame)
        scored = scores if scores is not None else self._scorer.score(frame)
        where = frame.index[-1] if position is None else position

        ranked = control.ranked(where, self._max_variables)
        flagged = bool(scored.flagged.loc[where])
        out_of_band = bool(control.any_out_of_band.loc[where])
        anomaly = bool(self.decision(scored, control).loc[where])  # PRD 13.2 Method 1 is primary

        if anomaly:
            kind, clause, evidence = self._hypothesis(control, where)
            regime, similarity, ranked_regimes = self._signatures.match(control.z_score.loc[where])
        else:
            kind, clause, evidence = NO_ANOMALY, "", {}
            regime, similarity, ranked_regimes = None, float("nan"), []

        evidence = {
            **evidence,
            "regime_match": {
                "regime": regime,
                "similarity": similarity,
                "min_similarity": self._signatures.min_similarity,
                "ranked": [
                    {"regime": name, "similarity": float(value)}
                    for name, value in ranked_regimes[:3]
                ],
            },
            "isolation_forest": {
                "score": _number(scored.score.loc[where]),
                "anomaly_score": _number(scored.anomaly_score.loc[where]),
                "flag_threshold": self._scorer.flag_threshold,
                "ood_threshold": self._scorer.ood_threshold,
                "contributions": self._scorer.contributions(frame.loc[where])[
                    : self._max_variables
                ],
            },
        }

        if anomaly:
            pieces: list[str] = []
            lead = evidence.get("lead_tag")
            if lead is not None:
                pieces.append(
                    f"{lead} is the strongest deviation (z={evidence['lead_z_score']:+.1f})"
                )
            pieces.append(
                f"nearest labelled regime signature is '{regime}' "
                f"(cosine similarity {similarity:.2f})"
                if regime is not None
                else "no labelled regime signature matches closely enough to name one"
            )
            pieces.append(clause)
            hypothesis = "; ".join(pieces)
        else:
            hypothesis = (
                "the anomaly score sits inside the normal-regime range"
                + (
                    f"; {int(control.out_of_band_count.loc[where])} tag(s) are outside their "
                    "control limits but not in a combination the detector treats as abnormal"
                    if out_of_band
                    else " and no tag is outside its control limits"
                )
            )

        status = "WARNING" if anomaly else "NORMAL"
        payload: dict[str, Any] = {
            "dataset": self._dataset,
            "status": status,
            "detected_anomaly": regime,
            "anomaly_kind": kind,
            "affected_variables": [dict(item) for item in ranked],
            "any_tag_out_of_band": out_of_band,
            "out_of_distribution": bool(scored.out_of_distribution.loc[where]),
            "ood_score_ratio": _number(scored.ood_ratio.loc[where]),
            "evidence": evidence,
        }
        action = NO_RULE_ENGINE_ACTION
        if anomaly and rule_engine is not None:
            action = str(rule_engine(payload) or NO_RULE_ENGINE_ACTION)

        return AnomalyReport(
            dataset=self._dataset,
            timestamp=(
                frame.loc[where, "timestamp"] if "timestamp" in frame.columns else where
            ),
            status=status,
            detected_anomaly=regime,
            hypothesis=hypothesis,
            affected_variables=tuple(ranked),
            suggested_action=action,
            anomaly_score=float(scored.anomaly_score.loc[where]),
            flagged=flagged,
            out_of_distribution=bool(scored.out_of_distribution.loc[where]),
            ood_ratio=float(scored.ood_ratio.loc[where]),
            anomaly_kind=kind,
            regime_similarity=float(similarity),
            evidence=evidence,
        )

    def reports(
        self,
        frame: pd.DataFrame,
        positions: Sequence[int] | np.ndarray | None = None,
        *,
        rule_engine: Callable[[Mapping[str, Any]], str | None] | None = None,
        anomalies_only: bool = True,
    ) -> list[AnomalyReport]:
        """Report every requested row, sharing one SPC pass and one scoring pass."""
        control = self.spc(frame)
        scored = self._scorer.score(frame)
        index = frame.index if positions is None else pd.Index(list(positions))
        decided = self.decision(scored, control)
        chosen = [
            position for position in index.tolist()
            if not anomalies_only or bool(decided.loc[position])
        ]
        return [
            self.report(frame, position, rule_engine=rule_engine, spc=control, scores=scored)
            for position in chosen
        ]

    def describe(self) -> dict[str, Any]:
        return {
            "dataset": self._dataset,
            "tags": list(self._tags),
            "manipulated_variables": list(self._inputs),
            "sampling_interval_min": self._interval,
            "status_values": ["NORMAL", "WARNING"],
            "anomaly_kinds": [
                NO_ANOMALY, SENSOR_ANOMALY, PROCESS_ANOMALY, UNDETERMINED_ANOMALY
            ],
            "affected_variables_max": self._max_variables,
            "startup_regime_excluded_from_training": self._startup,
            "isolation_forest": self._scorer.describe(),
            "spc": self._spc.describe(),
            "regime_signatures": self._signatures.describe(),
            "sensor_discrimination": dict(self._discrimination),
            "output_contract": {
                "fields": [
                    "Detected anomaly",
                    ANOMALY_HYPOTHESIS_LABEL,
                    "Affected variables",
                    RULE_BASED_SUGGESTION_LABEL,
                ],
                "detail": (
                    "PRD 15 block. The hypothesis is always hedged and the action is always "
                    "labelled a rule-based suggestion, never a diagnosis (PRD 15, FR-23)."
                ),
            },
        }


def _number(value: Any) -> float | None:
    """``float`` unless the value is NaN, in which case ``None`` (JSON-friendly evidence)."""
    number = float(value)
    return None if number != number else number


__all__ = [
    "NO_ANOMALY",
    "NO_RULE_ENGINE_ACTION",
    "PROCESS_ANOMALY",
    "PROCESS_HYPOTHESIS",
    "SENSOR_ANOMALY",
    "SENSOR_HYPOTHESIS",
    "UNCLASSIFIED",
    "UNDETERMINED_ANOMALY",
    "AnomalyDetector",
    "AnomalyEvaluation",
    "AnomalyReport",
    "RegimeSignatures",
]



