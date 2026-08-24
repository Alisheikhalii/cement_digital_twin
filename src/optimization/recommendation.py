"""The PRD v1.1.1 Section 14.4 ``Recommendation`` object - the optimizer's only output.

PRD 14.1 is explicit that "the optimizer never touches real equipment - it only ever produces a
``Recommendation`` object", so this module is the whole external surface of Model C. Every field
PRD 14.4 lists is present with its PRD name, and three things are added rather than folded in:

``state_sources``
    Which of the four kinds of number each state is. Keeping *simulator truth*, *observable
    sensor values*, *model predictions* and *optimization outputs* distinguishable is a hard
    requirement, and a dict of floats cannot carry that distinction on its own.
``observed_state``
    The measured operating point the run started from, kept beside ``baseline_state`` (the twin's
    settled response to the *same* setpoints). The comparison is done twin-vs-twin so that a
    reported delta is a genuine effect of the proposed move and not the twin/sensor offset; the
    measured row is what PRD 14.5 reports as "Current Operating Point".
``expected_impact``
    Energy, production, quality, emission and uncertainty in one place, over exactly
    ``configs/optimization.yaml baselines.metrics`` so an impact line and a PRD 14.5 baseline row
    are always the same metric set.

``recommendation_quality`` is categorical (FR-23) and comes from :mod:`src.models.quality`; there
is no numeric confidence anywhere in this module. ``timestamp`` is the timestamp of the
*observation the recommendation was made from*, never a wall clock - a reproducible optimizer
cannot have a field that changes when nothing else did.

Daily energy figures are plain arithmetic over simulated rates (rate x 24 h, ASSUMPTION of
continuous operation at the settled rate) and carry :data:`src.labels.SIMULATED_SAVING_CAVEAT`.
They are demonstrations of the method, not plant savings.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.config import OPTIMIZATION, Config, load_config
from src.labels import (
    AI_RECOMMENDATION_LABEL,
    DECISION_SUPPORT_LABEL,
    RECOMMENDATION_QUALITY_DESCRIPTION,
    SIMULATED_SAVING_CAVEAT,
    SYNTHETIC_DEMONSTRATION_LABEL,
)
from src.optimization.envelope import EnvelopeReport
from src.optimization.objective import ELECTRIC_TAG, THERMAL_TAG, ObjectiveResult

#: The four kinds of number, per the strict-distinction requirement. Recorded per state, never
#: inferred from a field name.
SOURCE_MEASURED = "observable_sensor_value"
SOURCE_TWIN_SIMULATION = "twin_simulation"
SOURCE_MODEL_A = "model_a_prediction"
SOURCE_OPTIMIZER = "optimization_output"
SOURCE_SIMULATOR_TRUTH = "simulator_ground_truth"

SOURCE_VALUES: tuple[str, ...] = (
    SOURCE_MEASURED,
    SOURCE_TWIN_SIMULATION,
    SOURCE_MODEL_A,
    SOURCE_OPTIMIZER,
    SOURCE_SIMULATOR_TRUTH,
)

#: Hours of continuous operation assumed when a rate is annualized to a daily figure.
#: ASSUMPTION - PRD 14.4 asks for an expected impact, not for a specific accounting period.
DAILY_HOURS = 24.0

#: kcal per kg -> kcal per tonne. Public because the dashboard's energy view (Task #6 directive
#: item 12) reports the same daily totals for a single operating point and must not re-declare
#: the conversion: it calls :func:`daily_total` below.
KG_PER_TONNE = 1000.0


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """One metric, before and after, with the change expressed both ways."""

    tag: str
    baseline: float | None
    proposed: float | None
    delta: float | None
    delta_pct: float | None

    @property
    def assessed(self) -> bool:
        return self.delta is not None

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "baseline": self.baseline,
            "proposed": self.proposed,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
        }


def metric_delta(tag: str, baseline: Mapping[str, float], proposed: Mapping[str, float]) -> MetricDelta:
    """Before/after for one tag; an absent or non-finite value yields an unassessed delta."""
    before = baseline.get(tag)
    after = proposed.get(tag)
    if before is None or after is None:
        return MetricDelta(tag=tag, baseline=_finite(before), proposed=_finite(after), delta=None, delta_pct=None)
    before_f, after_f = float(before), float(after)
    if not (math.isfinite(before_f) and math.isfinite(after_f)):
        return MetricDelta(tag=tag, baseline=None, proposed=None, delta=None, delta_pct=None)
    delta = after_f - before_f
    pct = None if before_f == 0.0 else 100.0 * delta / abs(before_f)
    return MetricDelta(tag=tag, baseline=before_f, proposed=after_f, delta=delta, delta_pct=pct)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


@dataclass(frozen=True, slots=True)
class ExpectedImpact:
    """PRD 14.4 ``expected_impact`` - one object covering every impact axis asked for."""

    metrics: tuple[MetricDelta, ...]
    thermal_energy_kcal_per_day: float | None
    electrical_energy_kwh_per_day: float | None
    relative_uncertainty_pct: float | None
    predicted_variability_pct: float | None
    caveat: str = SIMULATED_SAVING_CAVEAT

    def of(self, tag: str) -> MetricDelta | None:
        for item in self.metrics:
            if item.tag == tag:
                return item
        return None

    @property
    def energy(self) -> tuple[MetricDelta, ...]:
        return tuple(item for item in self.metrics if item.tag in (THERMAL_TAG, ELECTRIC_TAG))

    def describe(self) -> dict[str, Any]:
        return {
            "metrics": [item.describe() for item in self.metrics],
            "thermal_energy_kcal_per_day": self.thermal_energy_kcal_per_day,
            "electrical_energy_kwh_per_day": self.electrical_energy_kwh_per_day,
            "daily_basis_hours": DAILY_HOURS,
            "relative_uncertainty_pct": self.relative_uncertainty_pct,
            "predicted_variability_pct": self.predicted_variability_pct,
            "caveat": self.caveat,
        }

    @classmethod
    def build(
        cls,
        *,
        baseline_state: Mapping[str, float],
        proposed_state: Mapping[str, float],
        metrics: Sequence[str],
        relative_uncertainty_pct: float | None = None,
        predicted_variability_pct: float | None = None,
    ) -> "ExpectedImpact":
        deltas = tuple(metric_delta(str(tag), baseline_state, proposed_state) for tag in metrics)
        return cls(
            metrics=deltas,
            thermal_energy_kcal_per_day=_thermal_per_day(baseline_state, proposed_state),
            electrical_energy_kwh_per_day=_electrical_per_day(baseline_state, proposed_state),
            relative_uncertainty_pct=relative_uncertainty_pct,
            predicted_variability_pct=predicted_variability_pct,
        )


def _thermal_per_day(baseline: Mapping[str, float], proposed: Mapping[str, float]) -> float | None:
    """Change in kcal/day: (kcal/kg x kg/t x t/h x h), each factor a simulated quantity."""
    return _rate_per_day(baseline, proposed, THERMAL_TAG, "clinker_production_tph", KG_PER_TONNE)


def _electrical_per_day(baseline: Mapping[str, float], proposed: Mapping[str, float]) -> float | None:
    """Change in kWh/day: (kWh/t x t/h x h)."""
    return _rate_per_day(baseline, proposed, ELECTRIC_TAG, "cement_production_tph", 1.0)


def daily_total(
    state: Mapping[str, float],
    intensity_tag: str,
    rate_tag: str,
    scale: float,
) -> float | None:
    """One operating point's daily energy total: ``intensity x rate x scale x DAILY_HOURS``.

    The *total* half of Task #6 directive item 12, which requires a dashboard to show specific
    energy and total energy side by side rather than only the favourable one. It is the same
    arithmetic :func:`_rate_per_day` differences, factored out so there is exactly one definition
    of "per day" in the system. Returns ``None`` - never a substitute number - when either factor
    is absent or non-finite.
    """
    if intensity_tag not in state or rate_tag not in state:
        return None
    total = float(state[intensity_tag]) * float(state[rate_tag]) * scale * DAILY_HOURS
    return total if math.isfinite(total) else None


def _rate_per_day(
    baseline: Mapping[str, float],
    proposed: Mapping[str, float],
    intensity_tag: str,
    rate_tag: str,
    scale: float,
) -> float | None:
    before = daily_total(baseline, intensity_tag, rate_tag, scale)
    after = daily_total(proposed, intensity_tag, rate_tag, scale)
    if before is None or after is None:
        return None
    return after - before


@dataclass(frozen=True, slots=True)
class Recommendation:
    """PRD 14.4's object. Every field below is either PRD-named or documented in the docstring."""

    baseline_state: dict[str, float]
    proposed_state: dict[str, float]
    predicted_state_by_horizon: dict[str, dict[str, Any]]
    expected_impact: ExpectedImpact
    objective_breakdown: dict[str, float]
    recommendation_quality: str
    mode: str
    envelope_status: str
    constraint_status: str
    reason: str
    model_version: str
    timestamp: Any

    # -- kept beside the PRD 14.4 fields, see the module docstring ---------------------
    baseline_setpoints: dict[str, float] = field(default_factory=dict)
    proposed_setpoints: dict[str, float] = field(default_factory=dict)
    delta_fractions: dict[str, float] = field(default_factory=dict)
    observed_state: dict[str, float] = field(default_factory=dict)
    state_sources: dict[str, str] = field(default_factory=dict)
    quality_reason: str = ""
    envelope_report: EnvelopeReport | None = None
    objective: ObjectiveResult | None = None
    label: str = AI_RECOMMENDATION_LABEL

    @property
    def accepted(self) -> bool:
        """A recommendation that may be presented as an actionable suggestion."""
        return self.constraint_status == "PASS"

    @property
    def flagged(self) -> bool:
        return self.constraint_status == "FLAGGED_FOR_REVIEW"

    @property
    def banner(self) -> str | None:
        return None if self.envelope_report is None else self.envelope_report.banner

    @property
    def is_hold(self) -> bool:
        """True when the recommended action is "keep the current setpoints"."""
        return not any(abs(float(value)) > 0.0 for value in self.delta_fractions.values())

    @property
    def quality_description(self) -> str:
        return RECOMMENDATION_QUALITY_DESCRIPTION.get(self.recommendation_quality, "")

    def moved(self) -> tuple[str, ...]:
        """Decision variables this recommendation actually changes, in config order."""
        return tuple(
            name for name, value in self.delta_fractions.items() if abs(float(value)) > 0.0
        )

    def explanation(self) -> str:
        """Why this recommendation is considered acceptable - the required WHY, in one string."""
        moves = self.moved()
        action = (
            "hold the current setpoints"
            if not moves
            else "; ".join(
                f"{name} {self.baseline_setpoints[name]:.4g} -> "
                f"{self.proposed_setpoints[name]:.4g} "
                f"({self.delta_fractions[name] * 100:+.2f} %)"
                for name in moves
            )
        )
        gate = self.reason.strip()
        if gate and gate[-1] not in ".!?":
            gate = f"{gate}."
        confidence = (self.quality_reason or self.quality_description).strip()
        if confidence and confidence[-1] not in ".!?":
            confidence = f"{confidence}."
        parts = [
            f"{self.label} ({DECISION_SUPPORT_LABEL}, {SYNTHETIC_DEMONSTRATION_LABEL}): {action}.",
            f"Gate: {self.constraint_status} / {self.envelope_status} in {self.mode} mode - {gate}",
            f"Confidence: {self.recommendation_quality} - {confidence}",
        ]
        thermal = self.expected_impact.of(THERMAL_TAG)
        electric = self.expected_impact.of(ELECTRIC_TAG)
        if thermal is not None and thermal.delta_pct is not None:
            parts.append(
                f"Thermal energy {thermal.delta_pct:+.2f} % "
                f"({thermal.baseline:.4g} -> {thermal.proposed:.4g} kcal/kg clinker)."
            )
        if electric is not None and electric.delta_pct is not None:
            parts.append(
                f"Electrical energy {electric.delta_pct:+.2f} % "
                f"({electric.baseline:.4g} -> {electric.proposed:.4g} kWh/t)."
            )
        parts.append(self.expected_impact.caveat)
        if self.banner:
            parts.append(self.banner)
        return " ".join(parts)

    def describe(self) -> dict[str, Any]:
        """Serializable payload - what an export sidecar and the PRD 16.3 panel both read."""
        return {
            "label": self.label,
            "timestamp": str(self.timestamp),
            "mode": self.mode,
            "envelope_status": self.envelope_status,
            "constraint_status": self.constraint_status,
            "recommendation_quality": self.recommendation_quality,
            "quality_description": self.quality_description,
            "quality_reason": self.quality_reason,
            "reason": self.reason,
            "explanation": self.explanation(),
            "banner": self.banner,
            "model_version": self.model_version,
            "is_hold": self.is_hold,
            "baseline_setpoints": dict(self.baseline_setpoints),
            "proposed_setpoints": dict(self.proposed_setpoints),
            "delta_fractions": dict(self.delta_fractions),
            "state_sources": dict(self.state_sources),
            "baseline_state": dict(self.baseline_state),
            "proposed_state": dict(self.proposed_state),
            "observed_state": dict(self.observed_state),
            "predicted_state_by_horizon": self.predicted_state_by_horizon,
            "expected_impact": self.expected_impact.describe(),
            "objective_breakdown": dict(self.objective_breakdown),
            "objective": None if self.objective is None else self.objective.describe(),
            "envelope": None if self.envelope_report is None else self.envelope_report.describe(),
        }


def impact_metrics(config: Config | None = None) -> tuple[str, ...]:
    """``baselines.metrics`` - the single metric set for impacts and PRD 14.5 baseline rows."""
    optimization = config if config is not None else load_config(OPTIMIZATION)
    return tuple(str(tag) for tag in optimization.get_path("baselines.metrics"))


__all__ = [
    "DAILY_HOURS",
    "KG_PER_TONNE",
    "SOURCE_MEASURED",
    "SOURCE_MODEL_A",
    "SOURCE_OPTIMIZER",
    "SOURCE_SIMULATOR_TRUTH",
    "SOURCE_TWIN_SIMULATION",
    "SOURCE_VALUES",
    "ExpectedImpact",
    "MetricDelta",
    "Recommendation",
    "daily_total",
    "impact_metrics",
    "metric_delta",
]
