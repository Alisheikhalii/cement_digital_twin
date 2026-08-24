"""Deterministic rule engine of PRD v1.1.1 Section 14.6 - the one place if/else logic may stand
in for a recommendation.

It has three jobs, all of them PRD-assigned:

* PRD 14.6 - a transparent, explainable fallback that works with no trained model at all.
* PRD 14.5 item 4 - the **Digital Twin Baseline**: the operating point these rules would move to,
  so the AI-optimized point has a non-AI comparator that is neither the current point nor a
  deliberately poor one.
* PRD 15 - the "Suggested action (rule-based suggestion, not a diagnosis)" line beside an anomaly.

Every threshold is a key of ``configs/optimization.yaml rule_engine.thresholds`` and every step
size a key of ``rule_engine.actions``; nothing is written in this module. A rule fires on a tag it
can actually read - an absent tag makes the rule *unevaluated* and says so, because "no rule
fired" and "nobody could tell" are different statements.

Conflicts are resolved by a fixed priority, never by ordering luck: combustion and mechanical
protection outrank thermal correction, which outranks quality, which outranks throughput. When two
rules want the same variable the lower-priority one is suppressed *and reported*, so the
suggestion stays explainable. Same state in, same suggestion out - the engine holds no state.

The engine proposes **setpoint moves**, never actions on equipment, and its output is shaped like
everything else in Section 14: a set of proposed decision-variable values that still has to pass
the PRD 14.3 gate before anyone calls it a recommendation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.config import OPTIMIZATION, Config, load_config
from src.labels import RULE_BASED_SUGGESTION_LABEL
from src.optimization.variables import DecisionSpace

#: Fixed priority bands (lower fires first). ASSUMPTION - PRD 14.6 lists the rules, not an
#: ordering; the bands encode "safety before efficiency before product before throughput".
PRIORITY_SAFETY = 10
PRIORITY_COMBUSTION_AIR = 20
PRIORITY_THERMAL = 30
PRIORITY_EFFICIENCY = 40
PRIORITY_QUALITY = 50
PRIORITY_THROUGHPUT = 60

#: Rate-of-change window for the one derivative rule of PRD 14.6, in minutes.
CO_RATE_WINDOW_MIN = 1.0


@dataclass(frozen=True, slots=True)
class Rule:
    """One PRD 14.6 rule: a threshold on one tag, a signed step on one decision variable."""

    identifier: str
    tag: str
    comparison: str
    threshold_key: str
    variable: str
    step_key: str
    direction: int
    priority: int
    rationale: str
    rate_of_change: bool = False

    def condition(self, threshold: float) -> str:
        subject = f"d{self.tag}/dt" if self.rate_of_change else self.tag
        return f"{subject} {self.comparison} {threshold:g}"

    def triggered(self, value: float, threshold: float) -> bool:
        return value > threshold if self.comparison == ">" else value < threshold

    def describe(self, thresholds: Mapping[str, float], actions: Mapping[str, float]) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "tag": self.tag,
            "condition": self.condition(float(thresholds[self.threshold_key])),
            "variable": self.variable,
            "step_fraction": float(actions[self.step_key]) * self.direction,
            "priority": self.priority,
            "rationale": self.rationale,
        }


#: PRD 14.6's rule set. Every threshold key and every action key of the config block is used
#: exactly once here, so a config entry cannot go quietly dead.
RULES: tuple[Rule, ...] = (
    Rule(
        "co_high",
        "CO_ppm",
        ">",
        "CO_high_ppm",
        "ID_fan_speed",
        "id_fan_step_fraction",
        +1,
        PRIORITY_SAFETY,
        "High CO indicates incomplete combustion; more induced draught raises available oxygen.",
    ),
    Rule(
        "co_rising",
        "CO_ppm",
        ">",
        "CO_rising_ppm_per_min",
        "ID_fan_speed",
        "id_fan_step_fraction",
        +1,
        PRIORITY_SAFETY,
        "CO climbing faster than the configured rate is an early combustion-instability signal.",
        rate_of_change=True,
    ),
    Rule(
        "vibration_high",
        "vibration",
        ">",
        "vibration_high_mm_s",
        "kiln_feed_rate_tph",
        "feed_step_fraction",
        -1,
        PRIORITY_SAFETY,
        "Kiln vibration above its threshold calls for a lower mechanical load, i.e. less feed.",
    ),
    Rule(
        "bearing_hot",
        "bearing_temperature",
        ">",
        "bearing_temperature_high_C",
        "kiln_feed_rate_tph",
        "feed_step_fraction",
        -1,
        PRIORITY_SAFETY,
        "A hot bearing calls for a lower mechanical load until the cause is understood.",
    ),
    Rule(
        "oxygen_low",
        "oxygen_percent",
        "<",
        "oxygen_low_pct",
        "ID_fan_speed",
        "id_fan_step_fraction",
        +1,
        PRIORITY_COMBUSTION_AIR,
        "Oxygen below its floor risks sub-stoichiometric burning; raise induced draught.",
    ),
    Rule(
        "burning_zone_low",
        "burning_zone_temperature",
        "<",
        "burning_zone_low_C",
        "kiln_fuel_rate_tph",
        "fuel_step_fraction",
        +1,
        PRIORITY_THERMAL,
        "A cold burning zone under-burns the clinker; add fuel.",
    ),
    Rule(
        "burning_zone_high",
        "burning_zone_temperature",
        ">",
        "burning_zone_high_C",
        "kiln_fuel_rate_tph",
        "fuel_step_fraction",
        -1,
        PRIORITY_THERMAL,
        "An over-hot burning zone wastes fuel and stresses the refractory; cut fuel.",
    ),
    Rule(
        "oxygen_high",
        "oxygen_percent",
        ">",
        "oxygen_high_pct",
        "ID_fan_speed",
        "id_fan_step_fraction",
        -1,
        PRIORITY_EFFICIENCY,
        "Excess air carries heat out of the stack; trim induced draught.",
    ),
    Rule(
        "blaine_low",
        "simulated_blaine_cm2_g",
        "<",
        "blaine_low_cm2_g",
        "separator_speed_rpm",
        "separator_step_fraction",
        +1,
        PRIORITY_QUALITY,
        "Coarse cement needs a tighter separator cut, i.e. a faster separator.",
    ),
    Rule(
        "blaine_high",
        "simulated_blaine_cm2_g",
        ">",
        "blaine_high_cm2_g",
        "separator_speed_rpm",
        "separator_step_fraction",
        -1,
        PRIORITY_QUALITY,
        "Over-fine cement costs mill power for no product benefit; open the separator cut.",
    ),
    Rule(
        "mill_dp_high",
        "mill_differential_pressure",
        ">",
        "mill_differential_pressure_high_mbar",
        "mill_feed_rate_tph",
        "mill_feed_step_fraction",
        -1,
        PRIORITY_THROUGHPUT,
        "Rising mill differential pressure means the mill is filling; reduce feed.",
    ),
    Rule(
        "mill_dp_low",
        "mill_differential_pressure",
        "<",
        "mill_differential_pressure_low_mbar",
        "mill_feed_rate_tph",
        "mill_feed_step_fraction",
        +1,
        PRIORITY_THROUGHPUT,
        "An under-loaded mill is grinding air; raise feed toward the design load.",
    ),
)


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """What one rule concluded for one state."""

    rule: Rule
    state: str
    value: float | None
    threshold: float
    variable: str
    current: float | None = None
    proposed: float | None = None
    step_fraction: float = 0.0
    suppressed_by: str | None = None

    @property
    def fired(self) -> bool:
        return self.state == "FIRED"

    @property
    def applied(self) -> bool:
        return self.fired and self.suppressed_by is None and self.proposed is not None

    def reason(self) -> str:
        condition = self.rule.condition(self.threshold)
        if self.state == "NOT_EVALUATED":
            return f"{self.rule.identifier}: {self.rule.tag} unavailable - {condition} not checked"
        if not self.fired:
            return f"{self.rule.identifier}: {condition} not met ({self.value:.4g})"
        head = (
            f"{self.rule.identifier}: {condition} met ({self.value:.4g}) - "
            f"{self.rule.rationale}"
        )
        if self.suppressed_by is not None:
            return f"{head} Suppressed by the higher-priority rule {self.suppressed_by}."
        if self.proposed is None:  # pragma: no cover - only when the variable is unreadable
            return f"{head} No current value for {self.variable} - no move proposed."
        return (
            f"{head} Proposed: {self.variable} {self.current:.4g} -> {self.proposed:.4g} "
            f"({self.step_fraction * 100:+.2f} %)."
        )

    def describe(self) -> dict[str, Any]:
        return {
            "rule": self.rule.identifier,
            "state": self.state,
            "tag": self.rule.tag,
            "value": self.value,
            "threshold": self.threshold,
            "priority": self.rule.priority,
            "variable": self.variable,
            "current": self.current,
            "proposed": self.proposed,
            "step_fraction": self.step_fraction,
            "suppressed_by": self.suppressed_by,
            "applied": self.applied,
            "reason": self.reason(),
        }


@dataclass(frozen=True, slots=True)
class RuleReport:
    """Everything the engine concluded: the proposed setpoints and why, or why not."""

    findings: tuple[RuleFinding, ...]
    proposed_setpoints: dict[str, float]
    baseline_setpoints: dict[str, float]
    label: str = RULE_BASED_SUGGESTION_LABEL
    unevaluated_tags: tuple[str, ...] = ()

    @property
    def fired(self) -> tuple[RuleFinding, ...]:
        return tuple(item for item in self.findings if item.fired)

    @property
    def applied(self) -> tuple[RuleFinding, ...]:
        return tuple(item for item in self.findings if item.applied)

    @property
    def suppressed(self) -> tuple[RuleFinding, ...]:
        return tuple(item for item in self.findings if item.fired and item.suppressed_by)

    @property
    def is_hold(self) -> bool:
        """True when the rules propose keeping every setpoint where it is."""
        return not self.applied

    def suggestion(self) -> str:
        """PRD 15's suggested-action line - always prefixed with the mandated label."""
        if self.is_hold:
            tail = (
                "no rule threshold is exceeded; hold the current setpoints"
                if not self.unevaluated_tags
                else (
                    "no rule threshold is exceeded among the tags available; "
                    f"{len(self.unevaluated_tags)} tag(s) could not be checked "
                    f"({', '.join(self.unevaluated_tags)})"
                )
            )
            return f"{self.label}: {tail}."
        moves = "; ".join(
            f"{item.variable} {item.current:.4g} -> {item.proposed:.4g} "
            f"({item.step_fraction * 100:+.2f} %) because {item.rule.condition(item.threshold)}"
            for item in self.applied
        )
        return f"{self.label}: {moves}."

    def reason(self) -> str:
        """The full explanation, including rules that fired but were outranked."""
        parts = [self.suggestion()]
        parts.extend(item.reason() for item in self.suppressed)
        return " ".join(parts)

    def describe(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "suggestion": self.suggestion(),
            "reason": self.reason(),
            "is_hold": self.is_hold,
            "baseline_setpoints": dict(self.baseline_setpoints),
            "proposed_setpoints": dict(self.proposed_setpoints),
            "applied": [item.rule.identifier for item in self.applied],
            "suppressed": [item.rule.identifier for item in self.suppressed],
            "unevaluated_tags": list(self.unevaluated_tags),
            "findings": [item.describe() for item in self.findings],
        }


class RuleEngine:
    """PRD 14.6's engine. Stateless, deterministic, and readable without a model."""

    __slots__ = ("_actions", "_config", "_space", "_thresholds")

    def __init__(
        self,
        *,
        space: DecisionSpace,
        thresholds: Mapping[str, float],
        actions: Mapping[str, float],
        config: Config,
    ) -> None:
        self._space = space
        self._thresholds = {str(key): float(value) for key, value in thresholds.items()}
        self._actions = {str(key): float(value) for key, value in actions.items()}
        self._config = config

    @classmethod
    def from_config(
        cls, *, space: DecisionSpace, config: Config | None = None
    ) -> "RuleEngine":
        optimization = config if config is not None else load_config(OPTIMIZATION)
        block = optimization.get_path("rule_engine")
        return cls(
            space=space,
            thresholds=block.get_path("thresholds").to_dict(),
            actions=block.get_path("actions").to_dict(),
            config=optimization,
        )

    # -- access -------------------------------------------------------------------------
    @property
    def rules(self) -> tuple[Rule, ...]:
        return RULES

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    @property
    def actions(self) -> dict[str, float]:
        return dict(self._actions)

    # -- evaluation ---------------------------------------------------------------------
    def evaluate(
        self,
        state: Mapping[str, float],
        setpoints: Mapping[str, float],
        *,
        previous_state: Mapping[str, float] | None = None,
        mode: str = "NORMAL",
        interval_min: float = CO_RATE_WINDOW_MIN,
    ) -> RuleReport:
        """Apply every rule to ``state`` and return the suggested setpoints.

        ``setpoints`` is the current decision-variable vector (PRD 12 tag spelling);
        ``previous_state`` supplies the one derivative rule and may be omitted, in which case that
        rule reports itself unevaluated instead of assuming a flat trend.
        """
        current = self._space.baseline(setpoints)
        raw: list[RuleFinding] = []
        unevaluated: list[str] = []

        for rule in RULES:
            threshold = self._thresholds[rule.threshold_key]
            value = self._observed(rule, state, previous_state, interval_min)
            if value is None:
                raw.append(
                    RuleFinding(
                        rule=rule,
                        state="NOT_EVALUATED",
                        value=None,
                        threshold=threshold,
                        variable=rule.variable,
                    )
                )
                subject = f"d{rule.tag}/dt" if rule.rate_of_change else rule.tag
                if subject not in unevaluated:
                    unevaluated.append(subject)
                continue
            if not rule.triggered(value, threshold):
                raw.append(
                    RuleFinding(
                        rule=rule,
                        state="NOT_TRIGGERED",
                        value=value,
                        threshold=threshold,
                        variable=rule.variable,
                    )
                )
                continue
            step = self._actions[rule.step_key] * rule.direction
            base = current.get(rule.variable)
            proposed = (
                None
                if base is None
                else self._bounded(rule.variable, float(base) * (1.0 + step), float(base), mode)
            )
            raw.append(
                RuleFinding(
                    rule=rule,
                    state="FIRED",
                    value=value,
                    threshold=threshold,
                    variable=rule.variable,
                    current=None if base is None else float(base),
                    proposed=proposed,
                    step_fraction=step,
                )
            )

        findings = _resolve_conflicts(raw)
        proposed_setpoints = dict(current)
        for item in findings:
            if item.applied:
                proposed_setpoints[item.variable] = float(item.proposed)  # type: ignore[arg-type]
        return RuleReport(
            findings=findings,
            proposed_setpoints=proposed_setpoints,
            baseline_setpoints=current,
            unevaluated_tags=tuple(unevaluated),
        )

    def _observed(
        self,
        rule: Rule,
        state: Mapping[str, float],
        previous_state: Mapping[str, float] | None,
        interval_min: float,
    ) -> float | None:
        if not rule.rate_of_change:
            value = state.get(rule.tag)
            if value is None:
                return None
            number = float(value)
            return number if math.isfinite(number) else None
        if previous_state is None or rule.tag not in state or rule.tag not in previous_state:
            return None
        span = float(interval_min)
        if span <= 0.0:  # pragma: no cover - callers pass the sampling interval
            return None
        rate = (float(state[rule.tag]) - float(previous_state[rule.tag])) / span
        return rate if math.isfinite(rate) else None

    def _bounded(self, name: str, target: float, current: float, mode: str) -> float:
        """Snap onto the slider grid and clip to the mode's change limit - never past it."""
        low, high = self._space.bounds(name, current, mode)
        snapped = self._space.snap(name, target, current)
        return min(max(snapped, low), high)

    def describe(self) -> dict[str, Any]:
        return {
            "rule_count": len(RULES),
            "rules": [rule.describe(self._thresholds, self._actions) for rule in RULES],
            "thresholds": self.thresholds,
            "actions": self.actions,
            "priority_bands": {
                "safety": PRIORITY_SAFETY,
                "combustion_air": PRIORITY_COMBUSTION_AIR,
                "thermal": PRIORITY_THERMAL,
                "efficiency": PRIORITY_EFFICIENCY,
                "quality": PRIORITY_QUALITY,
                "throughput": PRIORITY_THROUGHPUT,
            },
            "detail": (
                "PRD 14.6 rule engine. Also the PRD 14.5 Digital Twin Baseline and the PRD 15 "
                "suggested-action source. Proposes setpoints only - never equipment actions."
            ),
        }


def _resolve_conflicts(raw: list[RuleFinding]) -> tuple[RuleFinding, ...]:
    """Keep the highest-priority firing rule per variable; mark the others suppressed.

    Ties break on the rule's position in :data:`RULES`, which is fixed - so two rules of equal
    priority on the same variable always resolve the same way.
    """
    winner: dict[str, RuleFinding] = {}
    order = {rule.identifier: index for index, rule in enumerate(RULES)}
    for finding in raw:
        if not finding.fired or finding.proposed is None:
            continue
        held = winner.get(finding.variable)
        if held is None:
            winner[finding.variable] = finding
            continue
        better = (finding.rule.priority, order[finding.rule.identifier]) < (
            held.rule.priority,
            order[held.rule.identifier],
        )
        if better:
            winner[finding.variable] = finding
    resolved: list[RuleFinding] = []
    for finding in raw:
        champion = winner.get(finding.variable)
        if (
            finding.fired
            and finding.proposed is not None
            and champion is not None
            and champion.rule.identifier != finding.rule.identifier
        ):
            resolved.append(
                RuleFinding(
                    rule=finding.rule,
                    state=finding.state,
                    value=finding.value,
                    threshold=finding.threshold,
                    variable=finding.variable,
                    current=finding.current,
                    proposed=finding.proposed,
                    step_fraction=finding.step_fraction,
                    suppressed_by=champion.rule.identifier,
                )
            )
        else:
            resolved.append(finding)
    return tuple(resolved)


__all__ = [
    "CO_RATE_WINDOW_MIN",
    "PRIORITY_COMBUSTION_AIR",
    "PRIORITY_EFFICIENCY",
    "PRIORITY_QUALITY",
    "PRIORITY_SAFETY",
    "PRIORITY_THERMAL",
    "PRIORITY_THROUGHPUT",
    "RULES",
    "Rule",
    "RuleEngine",
    "RuleFinding",
    "RuleReport",
]
