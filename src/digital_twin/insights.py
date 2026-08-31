"""Model-output payloads: prediction, anomaly, optimization, what-if (PRD 13-16, 26).

These four wrap objects the validated layers already produce - :class:`Prediction`,
:class:`AnomalyReport`, :class:`Recommendation`, :class:`WhatIfResult` - and add exactly three
things a view needs and none of them may invent: a provenance tag, an *availability* state for
when the model was never trained, and the display wording the Task #6 directive fixes.

Nothing here computes a process number, a threshold or a probability. In particular there is no
confidence-percentage field anywhere (FR-23, AC-18): uncertainty is the ensemble spread carried
on :class:`~src.digital_twin.provenance.Value`, and confidence is the categorical
``recommendation_quality`` the optimizer already assigned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping, Sequence

from src.anomaly_detection.detector import (
    INCONCLUSIVE_HYPOTHESIS,
    UNCLASSIFIED,
    UNDETERMINED_ANOMALY,
    AnomalyReport,
)
from src.digital_twin.provenance import Provenance, Value
from src.labels import (
    ANOMALY_HYPOTHESIS_LABEL,
    EVIDENCE_INCONCLUSIVE_LABEL,
    MODEL_UNAVAILABLE_LABEL,
    MODEL_UNAVAILABLE_STATEMENT,
    NO_SAFE_RECOMMENDATION,
    RULE_BASED_SUGGESTION_LABEL,
    WHAT_IF_VERDICT_NONE,
    WHAT_IF_VERDICT_PASS,
    WHAT_IF_VERDICT_REJECTED,
)


@dataclass(frozen=True, slots=True)
class PredictionSet:
    """Model A's multi-horizon output for one dataset (PRD 13.1, directive item 10).

    ``current`` is the observed state of the predicted targets and carries
    :data:`Provenance.OBSERVED`; ``by_horizon`` carries :data:`Provenance.PREDICTION`. They are
    kept in two channels precisely so a view cannot render them as one series of "values".
    """

    available: bool
    dataset: str
    timestamp: str
    current: tuple[Value, ...] = ()
    by_horizon: Mapping[int, tuple[Value, ...]] = field(default_factory=dict)
    horizons_min: tuple[int, ...] = ()
    missing: tuple[str, ...] = ()
    model_version: str = ""
    unavailable_reason: str = ""

    @property
    def label(self) -> str:
        return MODEL_UNAVAILABLE_LABEL if not self.available else "Model A prediction"

    def horizon(self, minutes: int) -> tuple[Value, ...]:
        return tuple(self.by_horizon.get(int(minutes), ()))

    def target_row(self, target: str) -> tuple[Value, ...]:
        """One target across every available horizon, in ascending horizon order."""
        return tuple(
            value
            for minutes in sorted(self.by_horizon)
            for value in self.by_horizon[minutes]
            if value.tag == target
        )

    def targets(self) -> tuple[str, ...]:
        seen: list[str] = []
        for values in self.by_horizon.values():
            for value in values:
                if value.tag not in seen:
                    seen.append(value.tag)
        return tuple(seen)

    def describe(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "dataset": self.dataset,
            "timestamp": self.timestamp,
            "horizons_min": list(self.horizons_min),
            "missing": list(self.missing),
            "model_version": self.model_version,
            "unavailable_reason": self.unavailable_reason,
            "current": [item.describe() for item in self.current],
            "by_horizon": {
                str(minutes): [item.describe() for item in values]
                for minutes, values in sorted(self.by_horizon.items())
            },
        }

    @classmethod
    def unavailable(cls, dataset: str, timestamp: str, reason: str = "") -> "PredictionSet":
        return cls(
            available=False,
            dataset=dataset,
            timestamp=timestamp,
            unavailable_reason=reason or MODEL_UNAVAILABLE_STATEMENT,
        )


@dataclass(frozen=True, slots=True)
class AnomalyState:
    """Model B's row output as a panel reads it (PRD 15, directive item 11)."""

    available: bool
    dataset: str
    timestamp: str
    status: str
    is_anomaly: bool
    score: float | None = None
    hypothesis: str = ""
    display_cause: str = ""
    nearest_regime: str | None = None
    regime_similarity: float | None = None
    affected_variables: tuple[Mapping[str, Any], ...] = ()
    suggested_action: str = ""
    anomaly_kind: str = ""
    out_of_distribution: bool = False
    inconclusive: bool = False
    unavailable_reason: str = ""
    provenance: Provenance = Provenance.PREDICTION

    hypothesis_label: str = ANOMALY_HYPOTHESIS_LABEL
    action_label: str = RULE_BASED_SUGGESTION_LABEL

    def describe(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "dataset": self.dataset,
            "timestamp": self.timestamp,
            "status": self.status,
            "is_anomaly": self.is_anomaly,
            "anomaly_score": self.score,
            "hypothesis_label": self.hypothesis_label,
            "hypothesis": self.hypothesis,
            "display_cause": self.display_cause,
            "inconclusive": self.inconclusive,
            "nearest_regime": self.nearest_regime,
            "regime_similarity": self.regime_similarity,
            "affected_variables": [dict(item) for item in self.affected_variables],
            "action_label": self.action_label,
            "suggested_action": self.suggested_action,
            "anomaly_kind": self.anomaly_kind,
            "out_of_distribution": self.out_of_distribution,
            "provenance": str(self.provenance),
            "unavailable_reason": self.unavailable_reason,
        }

    @classmethod
    def from_report(cls, report: AnomalyReport) -> "AnomalyState":
        """Map one :class:`AnomalyReport` to its display form, adding no judgement.

        The one display decision made here is directive item 11's: when Model B's own evidence
        does not separate an instrument fault from a process deviation - which is exactly the
        documented sensor-drift limitation - the *cause* field reads "Evidence inconclusive"
        instead of naming the nearest regime signature. The nearest signature is still carried,
        under its own name, as a similarity match rather than as a cause.
        """
        inconclusive = (
            INCONCLUSIVE_HYPOTHESIS in report.hypothesis
            or report.anomaly_kind == UNDETERMINED_ANOMALY
            or (report.is_anomaly and report.detected_anomaly is None)
        )
        if not report.is_anomaly:
            cause = ""
        elif inconclusive:
            cause = EVIDENCE_INCONCLUSIVE_LABEL
        else:
            cause = report.detected_anomaly or UNCLASSIFIED
        similarity = report.regime_similarity
        return cls(
            available=True,
            dataset=report.dataset,
            timestamp=str(report.timestamp),
            status=report.status,
            is_anomaly=report.is_anomaly,
            score=float(report.anomaly_score),
            hypothesis=report.hypothesis,
            display_cause=cause,
            nearest_regime=report.detected_anomaly,
            regime_similarity=None if similarity != similarity else float(similarity),
            affected_variables=tuple(dict(item) for item in report.affected_variables),
            suggested_action=report.suggested_action,
            anomaly_kind=report.anomaly_kind,
            out_of_distribution=bool(report.out_of_distribution),
            inconclusive=bool(inconclusive and report.is_anomaly),
        )

    @classmethod
    def unavailable(cls, dataset: str, timestamp: str, reason: str = "") -> "AnomalyState":
        return cls(
            available=False,
            dataset=dataset,
            timestamp=timestamp,
            status=MODEL_UNAVAILABLE_LABEL,
            is_anomaly=False,
            unavailable_reason=reason or MODEL_UNAVAILABLE_STATEMENT,
        )


@dataclass(frozen=True, slots=True)
class OptimizationView:
    """Model C's run as the decision-support card reads it (PRD 14.4/16.3, directive item 14).

    ``payload`` is :meth:`OptimizationResult.describe` unchanged - the panel renders from it and
    never recomputes an impact. ``refused`` and ``refusal_reasons`` make directive item 16's
    refusal a first-class display state rather than an empty card.
    """

    available: bool
    timestamp: str
    mode: str
    refused: bool
    message: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    gates: tuple[Mapping[str, Any], ...] = ()
    refusal_reasons: tuple[str, ...] = ()
    rejected_candidates: int = 0
    evaluated: int = 0
    runtime_s: float | None = None
    unavailable_reason: str = ""
    provenance: Provenance = Provenance.RECOMMENDATION

    @property
    def headline(self) -> str:
        if not self.available:
            return MODEL_UNAVAILABLE_LABEL
        return NO_SAFE_RECOMMENDATION if self.refused else self.message

    def recommendation(self) -> Mapping[str, Any] | None:
        value = self.payload.get("recommendation")
        return value if isinstance(value, Mapping) else None

    def baselines(self) -> Mapping[str, Any] | None:
        """The PRD 14.5 five-row baseline comparison (directive item 15, reconstructed).

        This is ``BaselineComparison.describe()`` exactly as
        :meth:`OptimizationResult.describe` serialized it under ``"baselines"`` - five rows,
        available ones and unavailable ones, over the one shared metric set. It reads what the
        frozen layer already computed and recomputes nothing; ``None`` means the optimizer ran
        without building the comparison, which the renderer states rather than fills in.
        """
        value = self.payload.get("baselines")
        return value if isinstance(value, Mapping) else None

    def predicted_states(self) -> Mapping[str, Any] | None:
        """The PRD 14.4 multi-horizon predicted state (directive item 10).

        This is ``Recommendation.describe()["predicted_state_by_horizon"]`` unchanged:
        ``{"t+5min": {target: {value, unit, uncertainty, uncertainty_method, ...}}}`` for
        whatever horizons Model A actually produced for the recommended candidate. It is Model A
        output - the PREDICTION channel - and reaches this view *inside* the recommendation
        payload without changing channel: the renderer must never merge it with observed values
        into one series (the two-channel rule of directive item 10). ``None`` means there is no
        recommendation to predict from (a refused run); an empty mapping means the recommendation
        carries no horizon predictions, which the renderer states rather than fills in.
        """
        recommendation = self.recommendation()
        if recommendation is None:
            return None
        value = recommendation.get("predicted_state_by_horizon")
        return value if isinstance(value, Mapping) else None

    def blocking_gates(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(item for item in self.gates if item.get("blocking"))

    def describe(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "refused": self.refused,
            "headline": self.headline,
            "message": self.message,
            "gates": [dict(item) for item in self.gates],
            "refusal_reasons": list(self.refusal_reasons),
            "rejected_candidates": self.rejected_candidates,
            "evaluated": self.evaluated,
            "runtime_s": self.runtime_s,
            "provenance": str(self.provenance),
            "unavailable_reason": self.unavailable_reason,
            "payload": dict(self.payload),
        }

    #: Fields of :meth:`describe` that measure this machine on this run rather than the result. The
    #: name and the intent are taken from
    #: :attr:`~src.optimization.optimizer.OptimizationResult.NON_REPRODUCIBLE_FIELDS`: the layer
    #: below already answers "what does reproducible exclude?" for this same field, and this layer
    #: answers it the same way rather than inventing a second answer.
    NON_REPRODUCIBLE_FIELDS: ClassVar[tuple[str, ...]] = ("runtime_s",)

    def signature(self) -> dict[str, Any]:
        """:meth:`describe` minus the wall clock - what "reproducible" means for view J.

        Two reads of the same optimizer run return an *identical* signature, field for field: same
        headline, gates, refusal reasons, rejection count, evaluated count and payload.

        ``runtime_s`` is stripped at **both** depths it appears, because this view carries the same
        measurement twice: its own field, and the copy inside ``payload`` - which is
        ``OptimizationResult.describe()``, whose own :meth:`signature` drops that field for exactly
        this reason. Stripping only the outer one leaves the view non-reproducible for the less
        obvious of the two reasons, which is precisely the trap that made this hard to see.

        The duration is deliberately *not* removed from :meth:`describe`. A panel reporting how long
        the search took is stating a true fact about the run that produced it; only the *comparison*
        excludes it. See ``SyntheticDataProvider.run_what_if`` for why it is measured at all.
        """
        payload = self.describe()
        nested = payload.get("payload")
        for field_name in self.NON_REPRODUCIBLE_FIELDS:
            payload.pop(field_name, None)
            if isinstance(nested, dict):
                nested.pop(field_name, None)
        return payload

    @classmethod
    def unavailable(cls, timestamp: str, mode: str = "NORMAL", reason: str = "") -> "OptimizationView":
        return cls(
            available=False,
            timestamp=timestamp,
            mode=mode,
            refused=False,
            message=MODEL_UNAVAILABLE_LABEL,
            unavailable_reason=reason or MODEL_UNAVAILABLE_STATEMENT,
        )

    @classmethod
    def from_result(cls, result: Any) -> "OptimizationView":
        """Wrap one ``OptimizationResult``. Reads it; recomputes nothing.

        Directive item 16: a refusal is a display state, not an empty card. The reasons shown are
        the blocking gates' own reasons - the optimizer's words, not a second explanation.
        """
        gates = tuple(gate.describe() for gate in result.gates)
        reasons = tuple(
            str(gate["reason"]) for gate in gates if gate.get("blocking") and gate.get("reason")
        )
        return cls(
            available=True,
            timestamp=str(result.timestamp),
            mode=str(result.mode),
            refused=bool(result.no_safe_recommendation),
            message=str(result.message),
            payload=result.describe(),
            gates=gates,
            refusal_reasons=reasons,
            rejected_candidates=len(result.rejected_candidates),
            evaluated=int(result.evaluated),
            runtime_s=float(result.runtime_s),
        )


@dataclass(frozen=True, slots=True)
class WhatIfView:
    """One what-if answer (PRD 16, directive item 13). ``panel`` is WhatIfResult.panel()."""

    available: bool
    timestamp: str
    mode: str
    verdict: str
    action: str
    panel: Mapping[str, Any] = field(default_factory=dict)
    requested: tuple[Mapping[str, Any], ...] = ()
    notes: tuple[str, ...] = ()
    banner: str | None = None
    runtime_s: float | None = None
    unavailable_reason: str = ""
    provenance: Provenance = Provenance.RECOMMENDATION

    def describe(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "verdict": self.verdict,
            "action": self.action,
            "requested": [dict(item) for item in self.requested],
            "notes": list(self.notes),
            "banner": self.banner,
            "runtime_s": self.runtime_s,
            "provenance": str(self.provenance),
            "unavailable_reason": self.unavailable_reason,
            "panel": dict(self.panel),
        }

    #: As :attr:`OptimizationView.NON_REPRODUCIBLE_FIELDS` - the wall clock, and nothing else.
    NON_REPRODUCIBLE_FIELDS: ClassVar[tuple[str, ...]] = ("runtime_s",)

    def signature(self) -> dict[str, Any]:
        """:meth:`describe` minus the wall clock - what "reproducible" means for view I.

        Only the view's own field is stripped. Unlike :meth:`OptimizationView.signature`, ``panel``
        needs no second pass: the PRD 16.3 panel carries no duration of its own, because
        :meth:`from_result` takes ``runtime_s`` as an argument rather than the engine stamping one
        (see that method's note on why a reproducible engine cannot own such a field). That is a
        measured fact about the payload, not an assumption - two calls on one frame differ in this
        one leaf and no other.
        """
        payload = self.describe()
        for field_name in self.NON_REPRODUCIBLE_FIELDS:
            payload.pop(field_name, None)
        return payload

    @classmethod
    def unavailable(cls, timestamp: str, mode: str = "NORMAL", reason: str = "") -> "WhatIfView":
        return cls(
            available=False,
            timestamp=timestamp,
            mode=mode,
            verdict=MODEL_UNAVAILABLE_LABEL,
            action="",
            unavailable_reason=reason or MODEL_UNAVAILABLE_STATEMENT,
        )

    @classmethod
    def from_result(
        cls, result: Any, *, timestamp: Any = "", runtime_s: float | None = None
    ) -> "WhatIfView":
        """Wrap one ``WhatIfResult``. ``panel`` is its PRD 16.3 contract, unchanged.

        The verdict is read from the panel's own ``recommendation_status`` rather than recomputed:
        directive item 13's three outcomes are the ones the engine already reached.

        ``timestamp`` is passed in because the PRD 16.3 panel does not carry one: a what-if answer
        belongs to the observation it was run from, and only the caller that supplied that
        observation knows which row it was. A view never stamps a wall clock of its own (a
        reproducible run cannot have a field that changes when nothing else did).
        """
        panel = result.panel()
        status = panel.get("recommendation_status", {})
        if status.get("accepted"):
            verdict = WHAT_IF_VERDICT_PASS
        elif status.get("simulated"):
            verdict = WHAT_IF_VERDICT_REJECTED
        else:
            verdict = WHAT_IF_VERDICT_NONE
        return cls(
            available=True,
            timestamp=str(timestamp),
            mode=str(panel.get("mode", "")),
            verdict=verdict,
            action=str(panel.get("action", "")),
            panel=panel,
            requested=tuple(dict(item) for item in panel.get("requested_change", ())),
            notes=tuple(str(note) for note in panel.get("notes", ())),
            banner=panel.get("banner"),
            runtime_s=runtime_s,
        )


def horizon_labels(horizons: Sequence[int]) -> tuple[str, ...]:
    """``("Current", "t+5", ...)`` - the column headers of the prediction table."""
    return ("Current",) + tuple(f"t+{int(minutes)}" for minutes in horizons)


__all__ = [
    "AnomalyState",
    "OptimizationView",
    "PredictionSet",
    "WhatIfView",
    "horizon_labels",
]
