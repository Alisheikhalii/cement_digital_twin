"""Recommendation Quality: the four documented factors -> HIGH / MEDIUM / LOW (PRD v1.1.1 13.1.1).

PRD 13.1.1 and FR-23 draw a hard line: the system may show a *category* and its written gloss, and
it may show an uncertainty width in engineering units, but it may never show a confidence
percentage - a number of that shape claims a calibrated probability that an ensemble spread does not
provide. This module is the only place the mapping happens, and it returns
:data:`src.labels.RecommendationQuality` values, so no caller can invent a fifth level or a
percentage.

The four factors are exactly the ones the PRD names:

============================  ========================  ==============================
factor                        better when               source
============================  ========================  ==============================
``relative_uncertainty_pct``  smaller                   Section 13.1.1 ensemble spread
``model_disagreement_pct``    smaller                   Section 13.1.1 RF vs GBM
``constraint_margin``         larger                    Section 14.2 hard constraints
``ood_score_ratio``           smaller                   Section 14.3 distance from training
============================  ========================  ==============================

The overall level is the *worst* level any assessed factor reaches, and an unassessed factor caps
the result at MEDIUM (ASSUMPTION, documented in ``MODEL_CARD.md``): Model A on its own can measure
spread and agreement but knows nothing about constraint margin or distance from the training
distribution, and calling such a prediction HIGH would overstate what was actually checked. The
optimizer (Section 14) supplies all four, which is the only configuration in which HIGH is
reachable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.config import ML, Config, load_config
from src.labels import (
    RECOMMENDATION_QUALITY_DESCRIPTION,
    RECOMMENDATION_QUALITY_VALUES,
    RecommendationQuality,
)

HIGH: RecommendationQuality = "HIGH"
MEDIUM: RecommendationQuality = "MEDIUM"
LOW: RecommendationQuality = "LOW"

#: Ordering used to take the worst level (index 0 is best).
QUALITY_ORDER: tuple[RecommendationQuality, ...] = (HIGH, MEDIUM, LOW)

#: ``factor name -> (config key, direction)``; ``max`` means "smaller is better".
FACTOR_DIRECTIONS: dict[str, tuple[str, str]] = {
    "relative_uncertainty_pct": ("max_relative_uncertainty_pct", "max"),
    "model_disagreement_pct": ("max_model_disagreement_pct", "max"),
    "constraint_margin": ("min_constraint_margin", "min"),
    "ood_score_ratio": ("max_ood_score_ratio", "max"),
}

FACTOR_NAMES: tuple[str, ...] = tuple(FACTOR_DIRECTIONS)

#: Factors Model A can assess on its own; the rest arrive with the optimizer (Section 14).
MODEL_A_FACTORS: tuple[str, ...] = ("relative_uncertainty_pct", "model_disagreement_pct")


@dataclass(frozen=True, slots=True)
class QualityFactor:
    """One factor's contribution, kept for the "why" the UI shows next to the label."""

    name: str
    value: float | None
    level: RecommendationQuality | None
    high_threshold: float
    medium_threshold: float
    direction: str

    @property
    def assessed(self) -> bool:
        return self.value is not None and self.level is not None

    def describe(self) -> dict[str, Any]:
        return {
            "factor": self.name,
            "value": self.value,
            "level": self.level,
            "assessed": self.assessed,
            "high_threshold": self.high_threshold,
            "medium_threshold": self.medium_threshold,
            "better_when": "smaller" if self.direction == "max" else "larger",
        }


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    """The categorical outcome plus the evidence that produced it (PRD 13.1.1, 14.4)."""

    level: RecommendationQuality
    factors: tuple[QualityFactor, ...]
    limiting_factor: str | None
    unassessed: tuple[str, ...]
    capped_by_unassessed: bool

    def __post_init__(self) -> None:
        if self.level not in RECOMMENDATION_QUALITY_VALUES:
            raise ValueError(f"{self.level!r} is not one of {RECOMMENDATION_QUALITY_VALUES}")

    @property
    def description(self) -> str:
        """The mandated gloss for this level (``src.labels``) - no percentage anywhere."""
        return RECOMMENDATION_QUALITY_DESCRIPTION[self.level]

    def factor(self, name: str) -> QualityFactor:
        for candidate in self.factors:
            if candidate.name == name:
                return candidate
        raise KeyError(name)

    def describe(self) -> dict[str, Any]:
        return {
            "recommendation_quality": self.level,
            "description": self.description,
            "limiting_factor": self.limiting_factor,
            "unassessed_factors": list(self.unassessed),
            "capped_by_unassessed_factors": self.capped_by_unassessed,
            "factors": [factor.describe() for factor in self.factors],
        }


def quality_thresholds(config: Config | None = None) -> dict[str, dict[str, float]]:
    """The two threshold rows of ``configs/ml.yaml → recommendation_quality``."""
    ml = config if config is not None else load_config(ML)
    return {
        level: {
            key: float(ml.get_path(f"recommendation_quality.{level}.{key}"))
            for key, _direction in FACTOR_DIRECTIONS.values()
        }
        for level in ("high", "medium")
    }


def assess_quality(
    *,
    relative_uncertainty_pct: float | None = None,
    model_disagreement_pct: float | None = None,
    constraint_margin: float | None = None,
    ood_score_ratio: float | None = None,
    config: Config | None = None,
) -> QualityAssessment:
    """Map the four factors onto HIGH / MEDIUM / LOW (PRD 13.1.1).

    ``None`` means "this caller did not assess that factor", which is different from a bad value:
    it is recorded in ``unassessed`` and caps the result at MEDIUM rather than being silently
    treated as a pass.
    """
    thresholds = quality_thresholds(config)
    values: dict[str, float | None] = {
        "relative_uncertainty_pct": relative_uncertainty_pct,
        "model_disagreement_pct": model_disagreement_pct,
        "constraint_margin": constraint_margin,
        "ood_score_ratio": ood_score_ratio,
    }

    factors: list[QualityFactor] = []
    for name, (key, direction) in FACTOR_DIRECTIONS.items():
        high = thresholds["high"][key]
        medium = thresholds["medium"][key]
        value = _finite_or_none(values[name])
        factors.append(
            QualityFactor(
                name=name,
                value=value,
                level=None if value is None else _factor_level(value, high, medium, direction),
                high_threshold=high,
                medium_threshold=medium,
                direction=direction,
            )
        )

    assessed = [factor for factor in factors if factor.assessed]
    unassessed = tuple(factor.name for factor in factors if not factor.assessed)
    if not assessed:
        # Nothing was measured, so nothing can be claimed.
        return QualityAssessment(
            level=LOW,
            factors=tuple(factors),
            limiting_factor=None,
            unassessed=unassessed,
            capped_by_unassessed=True,
        )

    worst = max(assessed, key=lambda factor: QUALITY_ORDER.index(factor.level))
    level: RecommendationQuality = worst.level  # type: ignore[assignment]
    capped = bool(unassessed) and level == HIGH
    if capped:
        level = MEDIUM
    return QualityAssessment(
        level=level,
        factors=tuple(factors),
        limiting_factor=worst.name if worst.level != HIGH else None,
        unassessed=unassessed,
        capped_by_unassessed=capped,
    )


def assess_prediction_quality(
    *,
    prediction: float,
    uncertainty: float,
    alternative_prediction: float | None = None,
    constraint_margin: float | None = None,
    ood_score_ratio: float | None = None,
    config: Config | None = None,
) -> QualityAssessment:
    """Convenience wrapper for Model A: turn a prediction + spread into the two factors it owns."""
    from src.models.uncertainty import disagreement_pct, relative_uncertainty_pct

    relative = float(relative_uncertainty_pct(uncertainty, prediction))
    disagreement = (
        None
        if alternative_prediction is None
        else float(disagreement_pct(prediction, alternative_prediction))
    )
    return assess_quality(
        relative_uncertainty_pct=relative,
        model_disagreement_pct=disagreement,
        constraint_margin=constraint_margin,
        ood_score_ratio=ood_score_ratio,
        config=config,
    )


def _factor_level(
    value: float, high: float, medium: float, direction: str
) -> RecommendationQuality:
    if direction == "max":
        if value <= high:
            return HIGH
        return MEDIUM if value <= medium else LOW
    if value >= high:
        return HIGH
    return MEDIUM if value >= medium else LOW


def _finite_or_none(value: float | None) -> float | None:
    """A NaN factor (e.g. a relative width around a zero prediction) counts as unassessed."""
    if value is None:
        return None
    number = float(value)
    return None if number != number else number


def quality_counts(assessments: Mapping[Any, QualityAssessment]) -> dict[str, int]:
    """How many assessments landed on each level (model-card / metrics summary)."""
    counts = dict.fromkeys(RECOMMENDATION_QUALITY_VALUES, 0)
    for assessment in assessments.values():
        counts[assessment.level] += 1
    return counts


__all__ = [
    "FACTOR_DIRECTIONS",
    "FACTOR_NAMES",
    "HIGH",
    "LOW",
    "MEDIUM",
    "MODEL_A_FACTORS",
    "QUALITY_ORDER",
    "QualityAssessment",
    "QualityFactor",
    "assess_prediction_quality",
    "assess_quality",
    "quality_counts",
    "quality_thresholds",
]
