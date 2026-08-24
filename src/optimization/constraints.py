"""Hard-constraint pre-filter of PRD v1.1.1 Section 14.2 - pass/fail, never a penalty term.

PRD 14.2 is explicit about the structure, and the structure is the safety property: the hard
constraints are "evaluated as a pass/fail filter ... so they can never be traded away for a
better objective score". This module therefore knows nothing about the objective, has no weight
anywhere in it, and returns a verdict rather than a number to be added up. The objective module
imports *this* module's normalized margin to build its approach penalties; the dependency
deliberately points one way only, so no weight can ever reach a hard bound.

The normalized ``margin`` reported per constraint is a single scale for one- and two-sided
bounds alike (ASSUMPTION - PRD 14.2 defines the bounds, not a distance measure):

* ``1``  the value sits at the most comfortable point of its band,
* ``0``  the value sits exactly on a bound,
* ``<0`` the bound is violated.

It is the number ``configs/ml.yaml recommendation_quality.*.min_constraint_margin`` thresholds
(PRD 13.1.1 factor 3) and the number the soft objective's comfort band is measured in, so there
is exactly one definition of "how close to a limit is this" in the system.

A two-sided bound normalizes itself: the half-width is the span. A one-sided bound has no
intrinsic span, so one has to be declared (ASSUMPTION, and the only choice in this module that
is not read straight off the PRD 14.2 table):

* a bound **derived from a target** uses the declared tolerance window as its span, because that
  window is exactly the distance between "on target" and "contractually short". Running at the
  production target therefore reads as margin ``1.0`` rather than as a hair above the floor,
  which is what ``production_target x (1 - 1 %)`` would otherwise imply.
* a **rated equipment limit** has no declared companion number, so its own magnitude is the
  span: 90 % of rated reads as margin 0.10.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.config import OPTIMIZATION, Config, ConfigError, load_config

#: Basis strings recorded on every constraint, so a report can say *why* a bound is what it is.
BASIS_EXPLICIT = "prd_14_2_explicit"
BASIS_PRODUCTION_TARGET = "production_target_minus_tolerance"
BASIS_BLAINE_TARGET = "blaine_target_plus_minus_tolerance"
BASIS_RESIDUE_MAX = "residue_max_percent"
BASIS_EQUIPMENT = "rated_equipment_limit"


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    """One row of the PRD 14.2 table."""

    tag: str
    minimum: float | None
    maximum: float | None
    basis: str
    span: float | None = None

    def __post_init__(self) -> None:
        if self.minimum is None and self.maximum is None:
            raise ConfigError(f"hard constraint {self.tag!r} declares neither a min nor a max")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum >= self.maximum
        ):
            raise ConfigError(
                f"hard constraint {self.tag!r} has min {self.minimum} >= max {self.maximum}"
            )
        if self.span is not None and float(self.span) <= 0.0:
            raise ConfigError(f"hard constraint {self.tag!r} has a non-positive span {self.span}")

    @property
    def two_sided(self) -> bool:
        return self.minimum is not None and self.maximum is not None

    def margin(self, value: float) -> float:
        """Normalized distance to the nearest bound (see the module docstring)."""
        current = float(value)
        if self.two_sided:
            half = (float(self.maximum) - float(self.minimum)) / 2.0  # type: ignore[arg-type]
            centre = (float(self.maximum) + float(self.minimum)) / 2.0  # type: ignore[arg-type]
            return (half - abs(current - centre)) / half
        if self.maximum is not None:
            scale = float(self.span) if self.span is not None else (abs(float(self.maximum)) or 1.0)
            return (float(self.maximum) - current) / scale
        scale = float(self.span) if self.span is not None else (abs(float(self.minimum)) or 1.0)  # type: ignore[arg-type]
        return (current - float(self.minimum)) / scale  # type: ignore[arg-type]

    def evaluate(self, state: Mapping[str, float]) -> "ConstraintOutcome":
        """Pass/fail this one constraint against ``state``; an absent tag is *not* a pass."""
        if self.tag not in state:
            return ConstraintOutcome(
                tag=self.tag,
                value=None,
                minimum=self.minimum,
                maximum=self.maximum,
                basis=self.basis,
                satisfied=False,
                evaluated=False,
                margin=None,
            )
        value = float(state[self.tag])
        if not math.isfinite(value):
            return ConstraintOutcome(
                tag=self.tag,
                value=value,
                minimum=self.minimum,
                maximum=self.maximum,
                basis=self.basis,
                satisfied=False,
                evaluated=False,
                margin=None,
            )
        low_ok = self.minimum is None or value >= float(self.minimum)
        high_ok = self.maximum is None or value <= float(self.maximum)
        return ConstraintOutcome(
            tag=self.tag,
            value=value,
            minimum=self.minimum,
            maximum=self.maximum,
            basis=self.basis,
            satisfied=bool(low_ok and high_ok),
            evaluated=True,
            margin=self.margin(value),
        )

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "min": self.minimum,
            "max": self.maximum,
            "basis": self.basis,
            "margin_span": self.span,
        }


@dataclass(frozen=True, slots=True)
class ConstraintOutcome:
    """The verdict on one constraint for one state."""

    tag: str
    value: float | None
    minimum: float | None
    maximum: float | None
    basis: str
    satisfied: bool
    evaluated: bool
    margin: float | None

    @property
    def violated(self) -> bool:
        return self.evaluated and not self.satisfied

    def reason(self) -> str:
        """One line, in the wording an operator panel shows (PRD 30: shown, never hidden)."""
        if not self.evaluated:
            return f"{self.tag}: not available in the evaluated state - cannot be verified"
        assert self.value is not None
        if self.satisfied:
            return f"{self.tag} = {self.value:.4g} within {self._band()}"
        return f"{self.tag} = {self.value:.4g} outside {self._band()}"

    def _band(self) -> str:
        if self.minimum is not None and self.maximum is not None:
            return f"[{self.minimum:.4g}, {self.maximum:.4g}]"
        if self.maximum is not None:
            return f"<= {self.maximum:.4g}"
        return f">= {self.minimum:.4g}"  # type: ignore[union-attr]

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "value": self.value,
            "min": self.minimum,
            "max": self.maximum,
            "basis": self.basis,
            "satisfied": self.satisfied,
            "evaluated": self.evaluated,
            "margin": self.margin,
            "reason": self.reason(),
        }


@dataclass(frozen=True, slots=True)
class ConstraintReport:
    """Every PRD 14.2 verdict for one state, plus the aggregate the filter acts on."""

    outcomes: tuple[ConstraintOutcome, ...]

    @property
    def satisfied(self) -> bool:
        """True only if every constraint was evaluated *and* satisfied.

        An unevaluated constraint is deliberately not a pass: PRD 30 forbids presenting a
        candidate as safe on the strength of a limit nobody checked.
        """
        return all(outcome.satisfied for outcome in self.outcomes)

    @property
    def violations(self) -> tuple[ConstraintOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if outcome.violated)

    @property
    def unevaluated(self) -> tuple[ConstraintOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.evaluated)

    @property
    def margin(self) -> float | None:
        """Worst normalized margin over every evaluated constraint (PRD 13.1.1 factor 3)."""
        margins = [
            outcome.margin for outcome in self.outcomes if outcome.margin is not None
        ]
        return min(margins) if margins else None

    def margin_of(self, tag: str) -> float | None:
        for outcome in self.outcomes:
            if outcome.tag == tag:
                return outcome.margin
        return None

    def outcome_of(self, tag: str) -> ConstraintOutcome | None:
        for outcome in self.outcomes:
            if outcome.tag == tag:
                return outcome
        return None

    def reason(self) -> str:
        """Why this state passed or failed the filter, naming every failure."""
        if self.satisfied:
            return (
                f"all {len(self.outcomes)} hard constraints satisfied "
                f"(worst normalized margin {self.margin:.3f})"
                if self.margin is not None
                else f"all {len(self.outcomes)} hard constraints satisfied"
            )
        parts = [outcome.reason() for outcome in (*self.violations, *self.unevaluated)]
        return "; ".join(parts)

    def describe(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "evaluated": len(self.outcomes) - len(self.unevaluated),
            "violations": [outcome.tag for outcome in self.violations],
            "unevaluated": [outcome.tag for outcome in self.unevaluated],
            "worst_margin": self.margin,
            "reason": self.reason(),
            "outcomes": [outcome.describe() for outcome in self.outcomes],
        }


class HardConstraints:
    """The PRD 14.2 table, built once from config and applied to any candidate state."""

    __slots__ = ("_config", "_specs", "_targets")

    def __init__(
        self,
        specs: tuple[ConstraintSpec, ...],
        *,
        config: Config,
        targets: Mapping[str, float],
    ) -> None:
        self._specs = specs
        self._config = config
        self._targets = dict(targets)

    @classmethod
    def from_config(
        cls,
        *,
        config: Config | None = None,
        production_target_tph: float | None = None,
        blaine_target_cm2_g: float | None = None,
    ) -> "HardConstraints":
        """Build the table; the two production/quality targets may be overridden per run.

        Overriding a *target* is a legitimate operating decision (the plant is asked for a
        different tonnage or a different cement fineness) and is recorded in the report's basis
        strings. Overriding a *bound* is not offered anywhere in this class - PRD 14.2's numbers
        come from config and nothing in the optimizer may move them.
        """
        optimization = config if config is not None else load_config(OPTIMIZATION)
        block = optimization.get_path("hard_constraints")
        target_block = optimization.get_path("targets")

        production = float(
            target_block.get_path("production_target_tph")
            if production_target_tph is None
            else production_target_tph
        )
        production_tol = float(target_block.get_path("production_tolerance_fraction"))
        blaine = float(
            target_block.get_path("blaine_target_cm2_g")
            if blaine_target_cm2_g is None
            else blaine_target_cm2_g
        )
        blaine_tol = float(target_block.get_path("blaine_tolerance_cm2_g"))
        residue_max = float(target_block.get_path("residue_max_percent"))
        targets = {
            "production_target_tph": production,
            "production_tolerance_fraction": production_tol,
            "blaine_target_cm2_g": blaine,
            "blaine_tolerance_cm2_g": blaine_tol,
            "residue_max_percent": residue_max,
        }

        specs: list[ConstraintSpec] = []
        for tag in block:
            if tag == "equipment_limits":
                continue
            entry = block.get_path(tag)
            if bool(entry.get_path("min_from_target", False)):
                specs.append(
                    ConstraintSpec(
                        tag=tag,
                        minimum=production * (1.0 - production_tol),
                        maximum=None,
                        basis=BASIS_PRODUCTION_TARGET,
                        span=production * production_tol,
                    )
                )
            elif bool(entry.get_path("from_target", False)):
                specs.append(
                    ConstraintSpec(
                        tag=tag,
                        minimum=blaine - blaine_tol,
                        maximum=blaine + blaine_tol,
                        basis=BASIS_BLAINE_TARGET,
                    )
                )
            elif bool(entry.get_path("max_from_target", False)):
                specs.append(
                    ConstraintSpec(
                        tag=tag, minimum=None, maximum=residue_max, basis=BASIS_RESIDUE_MAX
                    )
                )
            else:
                specs.append(
                    ConstraintSpec(
                        tag=tag,
                        minimum=_optional(entry, "min"),
                        maximum=_optional(entry, "max"),
                        basis=BASIS_EXPLICIT,
                    )
                )

        equipment = block.get_path("equipment_limits")
        for tag in equipment:
            entry = equipment.get_path(tag)
            specs.append(
                ConstraintSpec(
                    tag=tag,
                    minimum=_optional(entry, "min"),
                    maximum=_optional(entry, "max"),
                    basis=BASIS_EQUIPMENT,
                )
            )
        return cls(tuple(specs), config=optimization, targets=targets)

    # -- access -------------------------------------------------------------------------
    @property
    def specs(self) -> tuple[ConstraintSpec, ...]:
        return self._specs

    @property
    def tags(self) -> tuple[str, ...]:
        return tuple(spec.tag for spec in self._specs)

    @property
    def targets(self) -> dict[str, float]:
        return dict(self._targets)

    def spec_of(self, tag: str) -> ConstraintSpec | None:
        for spec in self._specs:
            if spec.tag == tag:
                return spec
        return None

    def evaluate(self, state: Mapping[str, float]) -> ConstraintReport:
        """Apply the whole table to one state. This is the entire PRD 14.2 filter."""
        return ConstraintReport(tuple(spec.evaluate(state) for spec in self._specs))

    def describe(self) -> dict[str, Any]:
        return {
            "count": len(self._specs),
            "targets": self.targets,
            "specs": [spec.describe() for spec in self._specs],
            "detail": (
                "PRD 14.2 hard constraints, evaluated as a pass/fail pre-filter. No weight and "
                "no objective term can reach these bounds."
            ),
        }


def _optional(entry: Any, key: str) -> float | None:
    value = entry.get_path(key, None)
    return None if value is None else float(value)


__all__ = [
    "BASIS_BLAINE_TARGET",
    "BASIS_EQUIPMENT",
    "BASIS_EXPLICIT",
    "BASIS_PRODUCTION_TARGET",
    "BASIS_RESIDUE_MAX",
    "ConstraintOutcome",
    "ConstraintReport",
    "ConstraintSpec",
    "HardConstraints",
]
