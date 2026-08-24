"""Soft, weighted multi-objective of PRD v1.1.1 Section 14.2 - the *only* place weights live.

    Objective = w_thermal*dThermal + w_electric*dElectric + w_production*Production_Penalty
              + w_quality*Quality_Penalty + w_stability*Stability_Penalty
              + w_emission*Emission_Penalty

Lower is better. Two properties are structural rather than checked afterwards:

* **No weight can reach a hard bound.** The four penalties are built from
  :class:`src.optimization.constraints.HardConstraints` - the same table the pass/fail filter
  uses - but the arrow only points this way. Nothing in this module can admit a candidate the
  filter rejected, whatever the weights are, which is the property PRD 14.2 means by "so they
  can never be traded away" and what the fuzzed-weight test of PRD 34 asserts.
* **Every term is in the same unit.** ``objective.normalization: relative_percent`` fixes that
  unit as *percent*: an energy term is a percent change against the baseline, and a penalty is
  ASSUMPTION-scaled so that ``100`` means "exactly on the hard bound" and ``0`` means "inside
  the comfort band". A candidate that buys a 3 % thermal saving by sitting on a limit therefore
  scores far worse than one that buys 2 % in the middle of the band, which is the behaviour
  PRD 14.2 describes as being "naturally discouraged from hugging the edges".

The comfort band itself is the hard band shrunk by ``soft_margin_fraction`` of its span,
measured in the single normalized margin of :mod:`src.optimization.constraints`: the penalty is
exactly zero while the margin is at least ``soft_margin_fraction`` and rises as
``((s - m) / s) ** penalty_exponent`` from there to ``1`` (i.e. 100 %) at the bound.

The stability term has two halves and only one of them is available during the candidate sweep:
PRD 14.1's flow consults Model A for the *recommended* action, not for every candidate, so
``predicted_variability_pct`` is ``None`` while ranking and populated once for the winner. Both
scores are reported (``ObjectiveResult.assessed``) rather than one quietly standing in for the
other.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.config import ML, OPTIMIZATION, Config, ConfigError, load_config
from src.optimization.constraints import (
    BASIS_BLAINE_TARGET,
    BASIS_PRODUCTION_TARGET,
    BASIS_RESIDUE_MAX,
    ConstraintSpec,
    HardConstraints,
)

#: PRD 14.2's two energy terms, as dataset tags. These are exactly
#: ``configs/ml.yaml uncertainty.optimizer_targets`` - the ML layer already declares which two
#: metrics the optimizer reads, and :meth:`SoftObjective.from_config` fails loudly if the two
#: files ever disagree.
THERMAL_TAG = "thermal_energy_kcal_per_kg_clinker"
ELECTRIC_TAG = "specific_power_consumption_kwh_t"

#: Term names of the PRD 14.4 ``objective_breakdown``.
TERM_THERMAL = "thermal"
TERM_ELECTRIC = "electric"
TERM_PRODUCTION = "production"
TERM_QUALITY = "quality"
TERM_STABILITY = "stability"
TERM_EMISSION = "emission"

TERM_NAMES: tuple[str, ...] = (
    TERM_THERMAL,
    TERM_ELECTRIC,
    TERM_PRODUCTION,
    TERM_QUALITY,
    TERM_STABILITY,
    TERM_EMISSION,
)

_WEIGHT_KEYS: dict[str, str] = {name: f"w_{name}" for name in TERM_NAMES}

#: A penalty of ``1.0`` means "exactly on the hard bound"; the objective's unit is percent
#: (``objective.normalization``), so it is reported as 100. ASSUMPTION - PRD 14.2 fixes the shape
#: of the penalty and the normalization, not this scale factor.
PENALTY_FULL_SCALE = 100.0


@dataclass(frozen=True, slots=True)
class ObjectiveTerm:
    """One weighted term, with the parts it was built from kept visible."""

    name: str
    weight: float
    value: float
    weighted: float
    assessed: bool
    detail: str
    parts: tuple[tuple[str, float], ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "value": self.value,
            "weighted": self.weighted,
            "assessed": self.assessed,
            "detail": self.detail,
            "parts": {name: value for name, value in self.parts},
        }


@dataclass(frozen=True, slots=True)
class ObjectiveResult:
    """The score of one candidate. ``total`` is what the search ranks on."""

    terms: tuple[ObjectiveTerm, ...]
    total: float
    normalization: str
    weights: tuple[tuple[str, float], ...]

    def term(self, name: str) -> ObjectiveTerm:
        for term in self.terms:
            if term.name == name:
                return term
        raise KeyError(f"no objective term {name!r}; expected one of {TERM_NAMES}")

    @property
    def breakdown(self) -> dict[str, float]:
        """PRD 14.4 ``objective_breakdown``: the weighted contribution of each term."""
        payload = {term.name: term.weighted for term in self.terms}
        payload["total"] = self.total
        return payload

    @property
    def assessed(self) -> bool:
        """False when a term could not be evaluated (see the module docstring on stability)."""
        return all(term.assessed for term in self.terms)

    def describe(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "normalization": self.normalization,
            "weights": dict(self.weights),
            "fully_assessed": self.assessed,
            "terms": [term.describe() for term in self.terms],
        }


class SoftObjective:
    """PRD 14.2's weighted objective, built from the hard-constraint table it must respect."""

    __slots__ = ("_config", "_constraints", "_emission", "_exponent", "_margin", "_stability", "_weights")

    def __init__(
        self,
        *,
        weights: Mapping[str, float],
        constraints: HardConstraints,
        soft_margin_fraction: float,
        penalty_exponent: float,
        stability: Mapping[str, float],
        emission: Mapping[str, Any],
        config: Config,
    ) -> None:
        missing = [name for name in TERM_NAMES if name not in weights]
        if missing:
            raise ConfigError(f"objective weights are missing {missing}")
        if float(soft_margin_fraction) <= 0.0:
            raise ConfigError("objective.soft_margin_fraction must be > 0")
        self._weights = {name: float(weights[name]) for name in TERM_NAMES}
        self._constraints = constraints
        self._margin = float(soft_margin_fraction)
        self._exponent = float(penalty_exponent)
        self._stability = {key: float(value) for key, value in stability.items()}
        self._emission = dict(emission)
        self._config = config

    # -- construction -------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        *,
        constraints: HardConstraints | None = None,
        config: Config | None = None,
        ml_config: Config | None = None,
        weights: Mapping[str, float] | None = None,
    ) -> "SoftObjective":
        optimization = config if config is not None else load_config(OPTIMIZATION)
        block = optimization.get_path("objective")
        declared = {
            name: float(block.get_path(f"weights.{key}")) for name, key in _WEIGHT_KEYS.items()
        }
        if weights is not None:
            declared.update({str(name): float(value) for name, value in weights.items()})

        ml = ml_config if ml_config is not None else load_config(ML)
        optimizer_targets = tuple(str(tag) for tag in ml.get_path("uncertainty.optimizer_targets"))
        if set(optimizer_targets) != {THERMAL_TAG, ELECTRIC_TAG}:
            raise ConfigError(
                "configs/ml.yaml uncertainty.optimizer_targets "
                f"{list(optimizer_targets)} does not match the PRD 14.2 energy terms "
                f"{[THERMAL_TAG, ELECTRIC_TAG]}"
            )
        return cls(
            weights=declared,
            constraints=(
                constraints
                if constraints is not None
                else HardConstraints.from_config(config=optimization)
            ),
            soft_margin_fraction=float(block.get_path("soft_margin_fraction")),
            penalty_exponent=float(block.get_path("penalty_exponent")),
            stability=block.get_path("stability").to_dict(),
            emission=block.get_path("emission").to_dict(),
            config=optimization,
        )

    def with_weights(self, weights: Mapping[str, float]) -> "SoftObjective":
        """A copy with some weights replaced - what the PRD 34 weight-fuzzing test drives.

        The hard-constraint table is shared, not copied, precisely so that fuzzing weights
        cannot reach it.
        """
        merged = dict(self._weights)
        merged.update({str(name): float(value) for name, value in weights.items()})
        return SoftObjective(
            weights=merged,
            constraints=self._constraints,
            soft_margin_fraction=self._margin,
            penalty_exponent=self._exponent,
            stability=self._stability,
            emission=self._emission,
            config=self._config,
        )

    # -- access -------------------------------------------------------------------------
    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    @property
    def constraints(self) -> HardConstraints:
        return self._constraints

    @property
    def soft_margin_fraction(self) -> float:
        return self._margin

    @property
    def production_tags(self) -> tuple[str, ...]:
        return self._tags_with_basis(BASIS_PRODUCTION_TARGET)

    @property
    def quality_tags(self) -> tuple[str, ...]:
        return self._tags_with_basis(BASIS_BLAINE_TARGET) + self._tags_with_basis(BASIS_RESIDUE_MAX)

    @property
    def emission_tags(self) -> tuple[str, ...]:
        return tuple(str(tag) for tag in self._emission["tags"])

    def _tags_with_basis(self, basis: str) -> tuple[str, ...]:
        return tuple(spec.tag for spec in self._constraints.specs if spec.basis == basis)

    # -- penalties ----------------------------------------------------------------------
    def approach_penalty(self, spec: ConstraintSpec, value: float) -> float:
        """Percent-scaled comfort-band penalty for one constrained tag (see module docstring)."""
        margin = spec.margin(float(value))
        if margin >= self._margin:
            return 0.0
        shortfall = (self._margin - margin) / self._margin
        return PENALTY_FULL_SCALE * float(shortfall) ** self._exponent

    def _band_penalty(self, tags: tuple[str, ...], state: Mapping[str, float]) -> tuple[float, tuple[tuple[str, float], ...], bool]:
        parts: list[tuple[str, float]] = []
        assessed = True
        for tag in tags:
            spec = self._constraints.spec_of(tag)
            if spec is None or tag not in state:  # pragma: no cover - guarded by callers
                assessed = False
                continue
            parts.append((tag, self.approach_penalty(spec, float(state[tag]))))
        value = sum(penalty for _, penalty in parts) / len(parts) if parts else 0.0
        return value, tuple(parts), assessed

    # -- scoring ------------------------------------------------------------------------
    def score(
        self,
        baseline_state: Mapping[str, float],
        proposed_state: Mapping[str, float],
        *,
        delta_fractions: Mapping[str, float] | None = None,
        predicted_variability_pct: float | None = None,
    ) -> ObjectiveResult:
        """Score ``proposed_state`` against ``baseline_state``. Lower total is better."""
        terms: list[ObjectiveTerm] = []

        for name, tag in ((TERM_THERMAL, THERMAL_TAG), (TERM_ELECTRIC, ELECTRIC_TAG)):
            change, assessed = _relative_change_pct(baseline_state, proposed_state, tag)
            terms.append(
                self._term(
                    name,
                    change,
                    assessed=assessed,
                    detail=f"percent change of {tag} versus the baseline state",
                    parts=(
                        (f"{tag}__baseline", float(baseline_state.get(tag, float("nan")))),
                        (f"{tag}__proposed", float(proposed_state.get(tag, float("nan")))),
                    ),
                )
            )

        production, production_parts, production_ok = self._band_penalty(
            self.production_tags, proposed_state
        )
        terms.append(
            self._term(
                TERM_PRODUCTION,
                production,
                assessed=production_ok,
                detail="comfort-band approach penalty on the PRD 14.2 production floor",
                parts=production_parts,
            )
        )

        quality, quality_parts, quality_ok = self._band_penalty(self.quality_tags, proposed_state)
        terms.append(
            self._term(
                TERM_QUALITY,
                quality,
                assessed=quality_ok,
                detail="comfort-band approach penalty on the Blaine window and residue ceiling",
                parts=quality_parts,
            )
        )

        travel = (
            0.0
            if delta_fractions is None
            else 100.0 * sum(abs(float(value)) for value in delta_fractions.values())
        )
        move_weight = self._stability["setpoint_move_weight"]
        variability_weight = self._stability["predicted_variability_weight"]
        variability = 0.0 if predicted_variability_pct is None else float(predicted_variability_pct)
        terms.append(
            self._term(
                TERM_STABILITY,
                move_weight * travel + variability_weight * variability,
                assessed=predicted_variability_pct is not None,
                detail=(
                    "setpoint travel (percent, summed over the moved variables) plus the "
                    "cross-horizon spread of the Model A predictions; the spread half is "
                    "unavailable while ranking candidates and is marked unassessed there"
                ),
                parts=(
                    ("setpoint_travel_pct", travel),
                    ("predicted_variability_pct", variability),
                ),
            )
        )

        emission_parts: list[tuple[str, float]] = []
        emission_ok = True
        references = self._emission["reference_ppm"]
        for tag in self.emission_tags:
            if tag not in baseline_state or tag not in proposed_state:
                emission_ok = False
                continue
            reference = float(references[tag])
            emission_parts.append(
                (
                    tag,
                    PENALTY_FULL_SCALE
                    * (float(proposed_state[tag]) - float(baseline_state[tag]))
                    / reference,
                )
            )
        emission = (
            sum(value for _, value in emission_parts) / len(emission_parts)
            if emission_parts
            else 0.0
        )
        # PRD 14.2 also requires every penalty to rise as a candidate approaches its *hard*
        # band. CO is the one emission tag that has one, so its approach penalty is added here
        # rather than folded into the relative-change average, and is reported separately.
        co_penalty = 0.0
        for tag in self.emission_tags:
            spec = self._constraints.spec_of(tag)
            if spec is not None and tag in proposed_state:
                penalty = self.approach_penalty(spec, float(proposed_state[tag]))
                co_penalty += penalty
                emission_parts.append((f"{tag}__approach_penalty", penalty))
        terms.append(
            self._term(
                TERM_EMISSION,
                emission + co_penalty,
                assessed=emission_ok,
                detail=(
                    "mean change of the emission basket as a percent of each tag's PRD 12.1 "
                    "band top, plus the comfort-band approach penalty of any emission tag that "
                    "carries a hard bound"
                ),
                parts=tuple(emission_parts),
            )
        )

        total = sum(term.weighted for term in terms)
        return ObjectiveResult(
            terms=tuple(terms),
            total=float(total),
            normalization=str(self._config.get_path("objective.normalization")),
            weights=tuple(sorted(self._weights.items())),
        )

    def _term(
        self,
        name: str,
        value: float,
        *,
        assessed: bool,
        detail: str,
        parts: tuple[tuple[str, float], ...] = (),
    ) -> ObjectiveTerm:
        weight = self._weights[name]
        return ObjectiveTerm(
            name=name,
            weight=weight,
            value=float(value),
            weighted=weight * float(value),
            assessed=assessed,
            detail=detail,
            parts=parts,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "normalization": str(self._config.get_path("objective.normalization")),
            "soft_margin_fraction": self._margin,
            "penalty_exponent": self._exponent,
            "penalty_full_scale": PENALTY_FULL_SCALE,
            "energy_tags": {"thermal": THERMAL_TAG, "electric": ELECTRIC_TAG},
            "production_tags": list(self.production_tags),
            "quality_tags": list(self.quality_tags),
            "emission_tags": list(self.emission_tags),
            "stability": dict(self._stability),
            "detail": (
                "PRD 14.2 soft objective. Lower is better. Hard constraints are not represented "
                "here as penalties - they are a separate pass/fail filter."
            ),
        }


def _relative_change_pct(
    baseline: Mapping[str, float], proposed: Mapping[str, float], tag: str
) -> tuple[float, bool]:
    if tag not in baseline or tag not in proposed:
        return 0.0, False
    reference = float(baseline[tag])
    if reference == 0.0:  # pragma: no cover - no energy metric is zero at any operating point
        return 0.0, False
    return 100.0 * (float(proposed[tag]) - reference) / abs(reference), True


__all__ = [
    "ELECTRIC_TAG",
    "PENALTY_FULL_SCALE",
    "TERM_ELECTRIC",
    "TERM_EMISSION",
    "TERM_NAMES",
    "TERM_PRODUCTION",
    "TERM_QUALITY",
    "TERM_STABILITY",
    "TERM_THERMAL",
    "THERMAL_TAG",
    "ObjectiveResult",
    "ObjectiveTerm",
    "SoftObjective",
]
