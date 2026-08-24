"""Operating-envelope and OOD gating of PRD v1.1.1 Section 14.3 - five ordered checks.

This is the gate every candidate has to survive before it can become a recommendation, and it
runs *before* the objective is allowed to have an opinion. PRD 14.3's order is kept literally:

1. **Operating-range validation** - every tag that the currently active model actually saw a
   range for must sit inside that recorded range (``models/registry.json`` ->
   ``training_domain.variable_ranges``, PRD 13.4). Not a hand-written envelope: the min/max the
   training data really contains.
2. **Feature-space / OOD validation** - Model B's Isolation Forest, scored on the proposed
   state (:class:`src.anomaly_detection.isolation.AnomalyScorer`).
3. **Hard-constraint evaluation** - the PRD 14.2 table, unchanged and unweighted.
4. **Maximum-change validation** - ``|dSetpoint| <= modes.<mode>.max_delta_fraction``.
5. Survivors proceed to scoring; this module never scores anything.

Failing any check yields ``constraint_status = "REJECTED"``. A *borderline* OOD score yields
``"FLAGGED_FOR_REVIEW"`` (``envelope.flag_instead_of_reject_when_borderline``, PRD 14.3's
documented implementer discretion) - never a silent promotion to a full recommendation.

Two orderings coexist on purpose. The **reported** order is always PRD's 1-2-3-4, with an
explicit ``NOT_EVALUATED`` state for any check that a cheaper failure made unnecessary. The
**executed** order puts the two setpoint-only checks (1 and 4) first, because they need no twin
solve at all: :meth:`EnvelopeValidator.pre_validate` can reject a candidate for free, which is
most of how the search stays inside the NFR-2 budget.

Mode semantics (PRD 16.1, and the one place they differ from "enforce everything"):

* ``NORMAL`` - all four checks enforced, ``max_delta_fraction`` 10 %.
* ``EXPERIMENTAL`` - ``modes.experimental.enforce_envelope: false``, so checks 1 and 2 are
  *reported and banner-flagged* rather than fatal; the point of the mode is to leave the
  calibrated envelope deliberately. Checks 3 and 4 stay fatal in every mode: PRD 30 makes the
  hard constraints structurally non-negotiable, and a move beyond the mode's own slider bound is
  not something the UI can express in the first place.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import OPTIMIZATION, Config, ConfigError, load_config
from src.labels import (
    CONSTRAINT_STATUS_VALUES,
    ENVELOPE_STATUS_VALUES,
    OUTSIDE_ENVELOPE_BANNER,
)
from src.optimization.constraints import ConstraintReport, HardConstraints
from src.optimization.variables import DecisionSpace

#: Check names, in PRD 14.3 order. The number is part of the identity: a report that renamed a
#: check would still be readable, one that reordered them would not be PRD 14.3.
CHECK_OPERATING_RANGE = "operating_range"
CHECK_FEATURE_SPACE = "feature_space_ood"
CHECK_HARD_CONSTRAINTS = "hard_constraints"
CHECK_MAX_CHANGE = "max_change"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_OPERATING_RANGE,
    CHECK_FEATURE_SPACE,
    CHECK_HARD_CONSTRAINTS,
    CHECK_MAX_CHANGE,
)

#: Per-check verdicts. ``NOT_EVALUATED`` is a first-class outcome, not a missing value.
STATE_PASS = "PASS"
STATE_FAIL = "FAIL"
STATE_BORDERLINE = "BORDERLINE"
STATE_NOT_EVALUATED = "NOT_EVALUATED"

STATE_VALUES: tuple[str, ...] = (STATE_PASS, STATE_FAIL, STATE_BORDERLINE, STATE_NOT_EVALUATED)

#: Which checks a mode may downgrade from fatal to banner-flagged (see the module docstring).
_ENVELOPE_CHECKS: frozenset[str] = frozenset({CHECK_OPERATING_RANGE, CHECK_FEATURE_SPACE})

#: Recorded on every report so a reader can tell where the borderline OOD boundary came from -
#: the same visible-fallback discipline ``HorizonModel.uncertainty`` uses for its spread method.
FLAG_SOURCE_PERCENTILE = "reference_score_percentile"
FLAG_SOURCE_FOREST_OFFSET = "isolation_forest_offset__fallback_no_reference_scores"
FLAG_SOURCE_UNAVAILABLE = "unavailable__no_scorer"


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """One PRD 14.3 check for one candidate."""

    number: int
    name: str
    state: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.state == STATE_FAIL

    @property
    def borderline(self) -> bool:
        return self.state == STATE_BORDERLINE

    @property
    def evaluated(self) -> bool:
        return self.state != STATE_NOT_EVALUATED

    def describe(self) -> dict[str, Any]:
        return {
            "check": self.number,
            "name": self.name,
            "state": self.state,
            "reason": self.reason,
            "detail": self.detail,
        }


def _not_evaluated(number: int, name: str, why: str) -> CheckOutcome:
    return CheckOutcome(number=number, name=name, state=STATE_NOT_EVALUATED, reason=why)


@dataclass(frozen=True, slots=True)
class EnvelopeReport:
    """The verdict of the whole gate: the two PRD 14.4 status fields plus every check."""

    checks: tuple[CheckOutcome, ...]
    mode: str
    enforce_envelope: bool
    envelope_status: str
    constraint_status: str
    ood_ratio: float | None
    flag_threshold_source: str
    constraint_report: ConstraintReport | None

    def check(self, name: str) -> CheckOutcome:
        for outcome in self.checks:
            if outcome.name == name:
                return outcome
        raise KeyError(f"no PRD 14.3 check named {name!r}; expected one of {CHECK_NAMES}")

    @property
    def accepted(self) -> bool:
        """True only for a full ``PASS``. ``FLAGGED_FOR_REVIEW`` is deliberately not accepted."""
        return self.constraint_status == "PASS"

    @property
    def rejected(self) -> bool:
        return self.constraint_status == "REJECTED"

    @property
    def flagged(self) -> bool:
        return self.constraint_status == "FLAGGED_FOR_REVIEW"

    @property
    def within_envelope(self) -> bool:
        return self.envelope_status == "WITHIN_ENVELOPE"

    @property
    def banner(self) -> str | None:
        """PRD 14.3 / 16.1: the fixed, non-removable banner, or ``None`` when inside."""
        return None if self.within_envelope else OUTSIDE_ENVELOPE_BANNER

    @property
    def failures(self) -> tuple[CheckOutcome, ...]:
        return tuple(outcome for outcome in self.checks if outcome.failed)

    @property
    def borderline(self) -> tuple[CheckOutcome, ...]:
        return tuple(outcome for outcome in self.checks if outcome.borderline)

    def reason(self) -> str:
        """Why this candidate was accepted, flagged or rejected - the PRD 14.4 ``reason``."""
        notable = (*self.failures, *self.borderline)
        if notable:
            return "; ".join(f"check {item.number} ({item.name}): {item.reason}" for item in notable)
        evaluated = [outcome for outcome in self.checks if outcome.evaluated]
        return (
            f"all {len(evaluated)} evaluated PRD 14.3 checks passed in {self.mode} mode: "
            + "; ".join(f"{item.name} {item.state.lower()}" for item in evaluated)
        )

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "enforce_envelope": self.enforce_envelope,
            "envelope_status": self.envelope_status,
            "constraint_status": self.constraint_status,
            "banner": self.banner,
            "ood_ratio": self.ood_ratio,
            "flag_threshold_source": self.flag_threshold_source,
            "reason": self.reason(),
            "checks": [outcome.describe() for outcome in self.checks],
            "hard_constraints": (
                None if self.constraint_report is None else self.constraint_report.describe()
            ),
        }


class _MemoScorer:
    """A Model B scorer that remembers what it already scored, keyed on the feature vector.

    Check 2 asks one question of one row, and scikit-learn's ``IsolationForest.score_samples``
    costs the same for one row as for forty: MEASURED on the reference operating point, 36.9 ms
    for a single row and 35.1 ms for forty. Almost all of it is the per-call walk over the forest's
    trees, so a run that scores 39 candidates against 2 forests pays ~2.9 s of overhead - about
    half the whole optimization - for work that is, in part, literally repeated.

    It is repeated because PRD 8.3 decouples the kiln from the cement mill through the clinker
    silo. A candidate that moves only kiln setpoints leaves every mill tag at exactly the baseline
    value, so the mill forest is handed a byte-identical row and returns a byte-identical score.
    This is the same argument ``src/optimization/optimizer.py`` already uses to memoize unit
    solves, applied to unit scoring: the score is a pure function of the row.

    Nothing observable changes - no threshold, no verdict, no reported number. Cache warmth cannot
    alter a value, only how long it took to obtain, so reproducibility is unaffected.
    """

    __slots__ = ("_cache", "_limit", "_scorer")

    #: ASSUMPTION - plenty for one optimization run (52 candidates x 2 units) with a bound.
    CACHE_LIMIT = 512

    def __init__(self, scorer: Any) -> None:
        self._scorer = scorer
        self._cache: dict[tuple[float, ...], Any] = {}
        self._limit = int(self.CACHE_LIMIT)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._scorer, name)

    @property
    def wrapped(self) -> Any:
        """The Model B scorer itself - so a caller can still reach the unwrapped object."""
        return self._scorer

    def score(self, frame: Any) -> Any:
        if getattr(frame, "shape", (0,))[0] != 1:  # only single-row calls are memoizable
            return self._scorer.score(frame)
        key = tuple(float(value) for value in frame.to_numpy(dtype=float)[0])
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        result = self._scorer.score(frame)
        if len(self._cache) < self._limit:
            self._cache[key] = result
        return result


class EnvelopeValidator:
    """PRD 14.3's gate. Knows the training ranges, Model B and the PRD 14.2 table - no weights."""

    __slots__ = (
        "_config",
        "_constraints",
        "_margin",
        "_ranges",
        "_scorers",
        "_space",
        "_thresholds",
    )

    def __init__(
        self,
        *,
        space: DecisionSpace,
        constraints: HardConstraints,
        training_ranges: Mapping[str, tuple[float, float]],
        scorer: Any | None,
        config: Config,
        reference_scores: Any | None = None,
    ) -> None:
        self._space = space
        self._constraints = constraints
        self._ranges = {
            str(tag): (float(low), float(high)) for tag, (low, high) in training_ranges.items()
        }
        self._scorers = tuple(_MemoScorer(item) for item in _as_scorers(scorer))
        self._config = config
        self._margin = float(config.get_path("envelope.training_range_margin_fraction"))
        self._thresholds = tuple(
            _ood_thresholds(item, config, _reference_for(item, reference_scores))
            for item in self._scorers
        )

    # -- construction -------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        *,
        space: DecisionSpace,
        constraints: HardConstraints,
        scorer: Any | None = None,
        training_ranges: Mapping[str, Mapping[str, float] | tuple[float, float]] | None = None,
        training_domains: Any | None = None,
        registry_path: str | Path | None = None,
        datasets: tuple[str, ...] | None = None,
        reference_scores: Any | None = None,
        config: Config | None = None,
    ) -> "EnvelopeValidator":
        """Build the gate, resolving check 1's ranges from whichever source is supplied.

        Exactly one of ``training_ranges`` (an explicit mapping), ``training_domains`` (the
        ``training_domain`` dicts of the :class:`HorizonModel` objects actually being consulted)
        or the registry file is used, in that order. All three describe the same thing - the
        min/max the *active* model was trained on - and the fallback order is "most specific
        first" so a test running off a short fixture never silently validates against the ranges
        of the full 90-day artefact.

        ``scorer`` may be one Model B, a sequence of them, or a dataset-keyed mapping; check 2
        consults every one and takes the worst verdict. ``reference_scores`` may likewise be one
        score distribution or a dataset-keyed mapping of them.
        """
        optimization = config if config is not None else load_config(OPTIMIZATION)
        if training_ranges is not None:
            ranges = _normalize_ranges(training_ranges)
        elif training_domains is not None:
            ranges = _ranges_from_domains(training_domains)
        else:
            path = (
                Path(registry_path)
                if registry_path is not None
                else Path(str(optimization.get_path("envelope.training_range_source")))
            )
            ranges = _ranges_from_registry(path, datasets)
        return cls(
            space=space,
            constraints=constraints,
            training_ranges=ranges,
            scorer=scorer,
            config=optimization,
            reference_scores=reference_scores,
        )

    # -- access -------------------------------------------------------------------------
    @property
    def training_ranges(self) -> dict[str, tuple[float, float]]:
        return dict(self._ranges)

    @property
    def constraints(self) -> HardConstraints:
        return self._constraints

    @property
    def scorer(self) -> Any | None:
        """The first Model B scorer, or ``None`` - convenience for the single-scorer case."""
        return self._scorers[0] if self._scorers else None

    @property
    def scorers(self) -> tuple[Any, ...]:
        """Every Model B scorer check 2 consults - one per dataset the caller supplied."""
        return self._scorers

    @property
    def flag_threshold_source(self) -> str:
        sources = tuple(dict.fromkeys(source for _, _, source in self._thresholds))
        if not sources:
            return FLAG_SOURCE_UNAVAILABLE
        return sources[0] if len(sources) == 1 else " + ".join(sources)

    def range_of(self, tag: str) -> tuple[float, float] | None:
        """Recorded training range of ``tag`` with ``training_range_margin_fraction`` applied."""
        bounds = self._ranges.get(tag)
        if bounds is None:
            return None
        low, high = bounds
        if self._margin <= 0.0:
            return (low, high)
        slack = (high - low) * self._margin
        return (low - slack, high + slack)

    # -- check 1: recorded training range ------------------------------------------------
    def check_operating_range(self, values: Mapping[str, float]) -> CheckOutcome:
        outside: list[dict[str, Any]] = []
        checked: list[str] = []
        for tag, value in values.items():
            bounds = self.range_of(tag)
            if bounds is None:
                continue
            current = float(value)
            checked.append(tag)
            if not math.isfinite(current) or current < bounds[0] or current > bounds[1]:
                outside.append(
                    {"tag": tag, "value": current, "training_min": bounds[0], "training_max": bounds[1]}
                )
        if not checked:
            return _not_evaluated(
                1,
                CHECK_OPERATING_RANGE,
                "no evaluated tag has a recorded training range - cannot be verified",
            )
        detail = {"checked": checked, "outside": outside, "margin_fraction": self._margin}
        if outside:
            listed = "; ".join(
                f"{item['tag']} = {item['value']:.4g} outside training range "
                f"[{item['training_min']:.4g}, {item['training_max']:.4g}]"
                for item in outside
            )
            return CheckOutcome(1, CHECK_OPERATING_RANGE, STATE_FAIL, listed, detail)
        return CheckOutcome(
            1,
            CHECK_OPERATING_RANGE,
            STATE_PASS,
            f"all {len(checked)} tags with a recorded training range are inside it",
            detail,
        )

    # -- check 2: Model B feature-space / OOD --------------------------------------------
    def check_feature_space(self, features: Mapping[str, float] | None) -> tuple[CheckOutcome, float | None]:
        """Score the proposed feature vector against every Model B supplied.

        The twin has one Model B per dataset (PRD 8.3 keeps the kiln and the mill separate), so
        "the Isolation Forest says this point is novel" is asked of each of them and the *worst*
        answer stands: a candidate that is ordinary for the kiln and unheard-of for the mill is
        still a candidate no model was trained near. ``ood_ratio`` is likewise the worst of the
        scorers, because that is the number the quality assessment must not be flattered by.
        """
        if not self._scorers:
            return (
                _not_evaluated(
                    2,
                    CHECK_FEATURE_SPACE,
                    "Model B is unavailable or unfitted - feature-space novelty cannot be verified",
                ),
                None,
            )
        if features is None:
            return (
                _not_evaluated(
                    2, CHECK_FEATURE_SPACE, "no feature vector supplied for the proposed state"
                ),
                None,
            )
        evaluated: list[tuple[str, str, str, dict[str, Any], float]] = []
        skipped: list[str] = []
        for scorer, (reject, flag, source) in zip(self._scorers, self._thresholds, strict=True):
            dataset = str(getattr(scorer, "dataset", "?"))
            if not getattr(scorer, "fitted", False):
                skipped.append(f"{dataset}: unfitted")
                continue
            missing = [name for name in scorer.features if name not in features]
            if missing:
                skipped.append(
                    f"{dataset}: feature vector is missing {len(missing)} feature(s) "
                    f"{missing[:5]}"
                )
                continue
            frame = pd.DataFrame([{name: float(features[name]) for name in scorer.features}])
            result = scorer.score(frame)
            score = float(result.score.iloc[0])
            ratio = float(result.ood_ratio.iloc[0])
            detail = {
                "dataset": dataset,
                "score": score,
                "ood_ratio": ratio,
                "reject_threshold": reject,
                "flag_threshold": flag,
                "flag_threshold_source": source,
                "method": getattr(scorer, "method", None),
            }
            if score < reject:
                state, reason = (
                    STATE_FAIL,
                    f"{dataset} Isolation Forest score {score:.4g} is below the "
                    f"out-of-distribution threshold {reject:.4g} (ood_ratio {ratio:.3f})",
                )
            elif flag is not None and score < flag:
                state, reason = (
                    STATE_BORDERLINE,
                    f"{dataset} Isolation Forest score {score:.4g} is between the borderline "
                    f"threshold {flag:.4g} and the rejection threshold {reject:.4g} "
                    f"(ood_ratio {ratio:.3f})",
                )
            else:
                state, reason = (
                    STATE_PASS,
                    f"{dataset} Isolation Forest score {score:.4g} is inside the training "
                    f"distribution (ood_ratio {ratio:.3f})",
                )
            evaluated.append((dataset, state, reason, detail, ratio))

        if not evaluated:
            return (
                _not_evaluated(
                    2,
                    CHECK_FEATURE_SPACE,
                    "no Model B could score the proposed state - " + "; ".join(skipped),
                ),
                None,
            )
        ratio = max(item[4] for item in evaluated)
        detail: dict[str, Any] = {
            "scorers": {item[0]: item[3] for item in evaluated},
            "worst_ood_ratio": ratio,
        }
        if skipped:
            detail["not_scored"] = skipped
        states = {item[1] for item in evaluated}
        worst = (
            STATE_FAIL
            if STATE_FAIL in states
            else STATE_BORDERLINE
            if STATE_BORDERLINE in states
            else STATE_PASS
        )
        reasons = "; ".join(item[2] for item in evaluated if item[1] == worst)
        if skipped:
            reasons = f"{reasons}; not scored: {'; '.join(skipped)}"
        return CheckOutcome(2, CHECK_FEATURE_SPACE, worst, reasons, detail), ratio

    # -- check 3: PRD 14.2 hard constraints ----------------------------------------------
    def check_hard_constraints(
        self, state: Mapping[str, float] | None
    ) -> tuple[CheckOutcome, ConstraintReport | None]:
        if state is None:
            return (
                _not_evaluated(
                    3, CHECK_HARD_CONSTRAINTS, "no simulated state supplied for the proposed action"
                ),
                None,
            )
        report = self._constraints.evaluate(state)
        outcome = CheckOutcome(
            3,
            CHECK_HARD_CONSTRAINTS,
            STATE_PASS if report.satisfied else STATE_FAIL,
            report.reason(),
            {
                "worst_margin": report.margin,
                "violations": [item.tag for item in report.violations],
                "unevaluated": [item.tag for item in report.unevaluated],
            },
        )
        return outcome, report

    # -- check 4: maximum change ----------------------------------------------------------
    def check_max_change(
        self, proposed: Mapping[str, float], baseline: Mapping[str, float], mode: str
    ) -> CheckOutcome:
        limit = self._space.max_delta_fraction(mode)
        deltas = self._space.delta_fractions(proposed, baseline)
        exceeded = {
            name: value for name, value in deltas.items() if abs(value) > limit + 1e-12
        }
        detail = {
            "limit_fraction": limit,
            "delta_fractions": deltas,
            "exceeded": exceeded,
            "mode": mode,
        }
        if exceeded:
            listed = "; ".join(
                f"{name} moves {value * 100:+.2f} % of its current value, beyond the "
                f"{limit * 100:.0f} % {mode} limit"
                for name, value in exceeded.items()
            )
            return CheckOutcome(4, CHECK_MAX_CHANGE, STATE_FAIL, listed, detail)
        largest = max((abs(value) for value in deltas.values()), default=0.0)
        return CheckOutcome(
            4,
            CHECK_MAX_CHANGE,
            STATE_PASS,
            f"largest setpoint move is {largest * 100:.2f} % of its current value, within the "
            f"{limit * 100:.0f} % {mode} limit",
            detail,
        )

    # -- the gate ------------------------------------------------------------------------
    def pre_validate(
        self, proposed: Mapping[str, float], baseline: Mapping[str, float], mode: str
    ) -> tuple[CheckOutcome, CheckOutcome]:
        """Checks 1 and 4 - the setpoint-only pair, evaluable without a twin solve."""
        return (
            self.check_operating_range(proposed),
            self.check_max_change(proposed, baseline, mode),
        )

    def validate(
        self,
        *,
        proposed: Mapping[str, float],
        baseline: Mapping[str, float],
        mode: str,
        simulated_state: Mapping[str, float] | None = None,
        features: Mapping[str, float] | None = None,
        pre: tuple[CheckOutcome, CheckOutcome] | None = None,
    ) -> EnvelopeReport:
        """Run the gate and assemble the PRD 14.3 report.

        ``proposed``/``baseline`` are decision-variable values keyed by PRD 12 tag;
        ``simulated_state`` is the twin's settled response to ``proposed`` (never simulator
        internals - only the tags a real plant would also publish); ``features`` is the Model B
        feature vector for that same proposed state.
        """
        enforce = self._space.enforce_envelope(mode)
        range_check, change_check = pre if pre is not None else self.pre_validate(
            proposed, baseline, mode
        )

        fatal_pre = change_check.failed or (enforce and range_check.failed)
        if fatal_pre:
            space_check = _not_evaluated(
                2,
                CHECK_FEATURE_SPACE,
                "not evaluated - an earlier PRD 14.3 check already rejected this candidate",
            )
            constraint_check = _not_evaluated(
                3,
                CHECK_HARD_CONSTRAINTS,
                "not evaluated - an earlier PRD 14.3 check already rejected this candidate",
            )
            ratio: float | None = None
            report: ConstraintReport | None = None
        else:
            extended = dict(proposed)
            if simulated_state is not None:
                extended.update({str(tag): value for tag, value in simulated_state.items()})
                range_check = self.check_operating_range(extended)
            space_check, ratio = self.check_feature_space(features)
            constraint_check, report = self.check_hard_constraints(simulated_state)

        checks = (range_check, space_check, constraint_check, change_check)
        envelope_status = (
            "OUTSIDE_ENVELOPE"
            if range_check.failed or space_check.failed
            else "WITHIN_ENVELOPE"
        )
        constraint_status = _resolve_status(checks, enforce=enforce, config=self._config)
        assert envelope_status in ENVELOPE_STATUS_VALUES
        assert constraint_status in CONSTRAINT_STATUS_VALUES
        return EnvelopeReport(
            checks=checks,
            mode=str(mode).upper(),
            enforce_envelope=enforce,
            envelope_status=envelope_status,
            constraint_status=constraint_status,
            ood_ratio=ratio,
            flag_threshold_source=self.flag_threshold_source,
            constraint_report=report,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "checks": [
                {"check": 1, "name": CHECK_OPERATING_RANGE, "source": "training_domain.variable_ranges"},
                {"check": 2, "name": CHECK_FEATURE_SPACE, "source": "Model B Isolation Forest"},
                {"check": 3, "name": CHECK_HARD_CONSTRAINTS, "source": "PRD 14.2 table"},
                {"check": 4, "name": CHECK_MAX_CHANGE, "source": "modes.<mode>.max_delta_fraction"},
            ],
            "training_range_tags": sorted(self._ranges),
            "training_range_margin_fraction": self._margin,
            "ood_scorers": [
                {
                    "dataset": str(getattr(scorer, "dataset", "?")),
                    "fitted": bool(getattr(scorer, "fitted", False)),
                    "reject_threshold": reject,
                    "flag_threshold": flag,
                    "flag_threshold_source": source,
                }
                for scorer, (reject, flag, source) in zip(
                    self._scorers, self._thresholds, strict=True
                )
            ],
            "flag_threshold_source": self.flag_threshold_source,
            "flag_instead_of_reject_when_borderline": bool(
                self._config.get_path("envelope.flag_instead_of_reject_when_borderline")
            ),
            "modes": {
                mode: {
                    "enforce_envelope": self._space.enforce_envelope(mode),
                    "max_delta_fraction": self._space.max_delta_fraction(mode),
                    "fatal_checks": sorted(
                        CHECK_NAMES
                        if self._space.enforce_envelope(mode)
                        else set(CHECK_NAMES) - _ENVELOPE_CHECKS
                    ),
                }
                for mode in ("NORMAL", "EXPERIMENTAL")
            },
        }


def _resolve_status(checks: tuple[CheckOutcome, ...], *, enforce: bool, config: Config) -> str:
    """Map the four check states onto the PRD 14.4 ``constraint_status`` vocabulary."""
    flag_borderline = bool(config.get_path("envelope.flag_instead_of_reject_when_borderline"))
    fatal = [
        outcome
        for outcome in checks
        if outcome.failed and (enforce or outcome.name not in _ENVELOPE_CHECKS)
    ]
    if fatal:
        return "REJECTED"
    downgraded = [
        outcome for outcome in checks if outcome.failed and outcome.name in _ENVELOPE_CHECKS
    ]
    borderline = [outcome for outcome in checks if outcome.borderline]
    if downgraded:
        # Experimental Mode: leaving the envelope is the point, so it is flagged and bannered
        # rather than rejected - but it is never promoted to a plain PASS.
        return "FLAGGED_FOR_REVIEW"
    if borderline:
        return "FLAGGED_FOR_REVIEW" if flag_borderline else "REJECTED"
    unevaluated = [outcome for outcome in checks if not outcome.evaluated]
    if unevaluated:
        # PRD 30: a check nobody could run is not evidence of safety.
        return "FLAGGED_FOR_REVIEW"
    return "PASS"


def _as_scorers(scorer: Any | None) -> tuple[Any, ...]:
    """Accept one Model B, several, or a dataset-keyed mapping of them - always return a tuple."""
    if scorer is None:
        return ()
    if isinstance(scorer, Mapping):
        return tuple(scorer.values())
    if isinstance(scorer, (list, tuple, set, frozenset)):
        return tuple(scorer)
    return (scorer,)


def _reference_for(scorer: Any, reference_scores: Any | None) -> Any | None:
    """Pick the reference score distribution belonging to ``scorer``, if one was supplied."""
    if reference_scores is None:
        return None
    if isinstance(reference_scores, Mapping):
        return reference_scores.get(str(getattr(scorer, "dataset", "")))
    return reference_scores


def _ood_thresholds(
    scorer: Any | None, config: Config, reference_scores: Any | None
) -> tuple[float, float | None, str]:
    """Resolve the reject / borderline score boundaries and record where they came from."""
    if scorer is None or not getattr(scorer, "fitted", False):
        return (-math.inf, None, FLAG_SOURCE_UNAVAILABLE)
    reject = float(scorer.ood_threshold)
    flag_percentile = float(config.get_path("envelope.ood.flag_score_percentile"))
    if reference_scores is not None and len(reference_scores) > 0:
        series = pd.Series([float(value) for value in reference_scores], dtype=float)
        return (reject, float(series.quantile(flag_percentile / 100.0)), FLAG_SOURCE_PERCENTILE)
    # No reference distribution was supplied and `AnomalyScorer` deliberately does not retain
    # one, so the contamination-calibrated forest boundary stands in - visibly.
    return (reject, float(scorer.flag_threshold), FLAG_SOURCE_FOREST_OFFSET)


def _normalize_ranges(
    ranges: Mapping[str, Mapping[str, float] | tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    resolved: dict[str, tuple[float, float]] = {}
    for tag, bounds in ranges.items():
        if isinstance(bounds, Mapping):
            resolved[str(tag)] = (float(bounds["min"]), float(bounds["max"]))
        else:
            low, high = bounds
            resolved[str(tag)] = (float(low), float(high))
    return resolved


def _intersect(
    into: dict[str, tuple[float, float]], ranges: Mapping[str, tuple[float, float]]
) -> None:
    """Intersect ``ranges`` into ``into``: a tag is only in range for *every* active model."""
    for tag, (low, high) in ranges.items():
        if tag in into:
            current = into[tag]
            into[tag] = (max(current[0], low), min(current[1], high))
        else:
            into[tag] = (low, high)


def _ranges_from_domains(domains: Any) -> dict[str, tuple[float, float]]:
    """Intersect the ``variable_ranges`` of every supplied ``training_domain`` mapping."""
    items = domains.values() if isinstance(domains, Mapping) else domains
    resolved: dict[str, tuple[float, float]] = {}
    for domain in items:
        block = domain.get("variable_ranges", {}) if isinstance(domain, Mapping) else {}
        _intersect(resolved, _normalize_ranges(block))
    if not resolved:
        raise ConfigError("no training_domain supplied a variable_ranges block")
    return resolved


def _ranges_from_registry(
    path: Path, datasets: tuple[str, ...] | None
) -> dict[str, tuple[float, float]]:
    if not path.exists():
        raise ConfigError(
            f"PRD 14.3 check 1 needs recorded training ranges but {path} does not exist; "
            "train the models first or pass training_ranges / training_domains explicitly"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("models", {})
    resolved: dict[str, tuple[float, float]] = {}
    for entry in entries.values() if isinstance(entries, Mapping) else entries:
        if datasets is not None and str(entry.get("dataset")) not in datasets:
            continue
        block = (entry.get("training_domain") or {}).get("variable_ranges", {})
        _intersect(resolved, _normalize_ranges(block))
    if not resolved:
        raise ConfigError(
            f"{path} records no training_domain.variable_ranges for datasets {datasets}"
        )
    return resolved


__all__ = [
    "CHECK_FEATURE_SPACE",
    "CHECK_HARD_CONSTRAINTS",
    "CHECK_MAX_CHANGE",
    "CHECK_NAMES",
    "CHECK_OPERATING_RANGE",
    "FLAG_SOURCE_FOREST_OFFSET",
    "FLAG_SOURCE_PERCENTILE",
    "FLAG_SOURCE_UNAVAILABLE",
    "STATE_BORDERLINE",
    "STATE_FAIL",
    "STATE_NOT_EVALUATED",
    "STATE_PASS",
    "STATE_VALUES",
    "CheckOutcome",
    "EnvelopeReport",
    "EnvelopeValidator",
]
