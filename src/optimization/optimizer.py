"""``Optimizer`` - "Model C", the PRD v1.1.1 Section 14.1 pipeline and nothing more.

PRD 14.1 fixes the flow, and this module runs it in exactly that order::

    Current State -> Digital Twin -> Candidate Actions -> Simulate Each Action
      -> Operating-Envelope / OOD Validation (14.3) -> Hard-Constraint Evaluation (14.2)
      -> Multi-Objective Optimization over the survivors (14.2) -> Recommended Action

Five properties of that pipeline are structural here rather than conventional:

*Gates run before scoring.* :class:`~src.optimization.objective.SoftObjective` is never shown a
candidate that failed PRD 14.3, so no weight - however extreme - can buy a violating candidate
back. Reweighting can reorder the survivors; it cannot change who they are.

*The gate is four independent gates.* Anomaly state, Model A availability, prediction
uncertainty and the PRD 14.3 envelope/constraint stack are separate :class:`GateOutcome` records
with their own reasons, so "rejected" is never one opaque verdict.

*Nothing read here would be unavailable in a real plant.* Candidates are evaluated through
``to_steady_state``, whose *return value* is the published PRD 12 tag dict; sub-unit states,
reference points and balance residuals are never touched. History is only ever read backwards
from the request timestamp, so a recommendation cannot borrow a future observation.

*Nothing is random unless it is seeded.* The candidate set is a fixed coordinate grid plus a
``search.random_state``-seeded sample, generation order is fixed, and ties keep the earlier
candidate - so two runs on the same inputs return identical results, field for field.

*Constraints are never relaxed to manufacture an answer.* If nothing survives - including the
do-nothing candidate - the run returns :data:`src.labels.NO_SAFE_RECOMMENDATION` and no
:class:`Recommendation` at all. "Hold the current setpoints" is itself a legitimate and
frequently correct recommendation, reported as such rather than as a failure.

Two implementation notes worth stating plainly:

``search.steady_state.tolerance_relative`` is used as a *convergence verification* tolerance.
``to_steady_state`` enforces its own, tighter, internal criterion; after settling a candidate this
module takes one further minute-long step and rejects the candidate if any tag is still moving by
more than that fraction. A candidate that had not actually settled inside the budget is therefore
never scored as though it had.

Candidate states are memoized per *unit*, keyed on that unit's decision variables plus the run's
fixed inputs. That is sound only because the kiln and the cement mill are independent in PRD 8.3
(verified: the plant's settled state equals the two units' settled states merged, tag for tag),
and every solve starts from ``reset()`` so a settled state never depends on the path taken to it.
The memo is cleared at the start of every :meth:`Optimizer.optimize` call, so the reported solve
count is a property of the run rather than of cache warmth.

ASSUMPTION - **uncertainty gating is applied to the objective's own targets.** The ceiling is
unchanged (``configs/ml.yaml recommendation_quality.medium.max_relative_uncertainty_pct``, 8 %);
what is scoped is the prediction set it is applied to. The gate blocks on the worst relative
spread over ``uncertainty.optimizer_targets`` - ``thermal_energy_kcal_per_kg_clinker`` and
``specific_power_consumption_kwh_t``, the two quantities a PRD 14.2 recommendation actually claims
an improvement in. The worst spread over *every* consulted target is still computed, is reported
in the gate detail and the recommendation, names each offending target and horizon, and caps the
categorical Recommendation Quality through :func:`~src.models.quality.assess_quality`.

The reason is measured, not convenient: on the reference operating point every Model A target sits
at or below 0.51 % relative spread except ``oxygen_percent``, which reaches 6.4 / 29.4 / 31.2 /
32.9 % at t+5/10/15/30 min and is graded LOW by the ML layer's own rules. Model A cannot predict
O2 from this feature set in this regime - a Task 4 outcome documented as a limitation rather than
engineered away. Blocking on it would make the gate a constant "no" independent of the candidate,
which is not a check; reporting it beside a capped quality grade is PRD 30's "shown, not hidden".
Deviation recorded here, in ``configs/ml.yaml`` and in the Task 5 report.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from src import PRD_VERSION
from src.config import ML, OPTIMIZATION, Config, load_config
from src.labels import NO_SAFE_RECOMMENDATION
from src.models.quality import assess_quality
from src.optimization.baselines import BaselineComparison, BaselineSet
from src.optimization.constraints import HardConstraints
from src.optimization.envelope import (
    STATE_FAIL,
    STATE_NOT_EVALUATED,
    STATE_PASS,
    EnvelopeReport,
    EnvelopeValidator,
)
from src.optimization.objective import ObjectiveResult, SoftObjective
from src.optimization.prediction import (
    PredictionBundle,
    by_horizon,
    cross_horizon_spread_pct,
    objective_targets,
    relative_uncertainty_pct,
    uncertainty_limit_pct,
    wide_predictions,
    worst_disagreement_pct,
)
from src.optimization.recommendation import (
    SOURCE_MEASURED,
    SOURCE_MODEL_A,
    SOURCE_OPTIMIZER,
    SOURCE_TWIN_SIMULATION,
    ExpectedImpact,
    Recommendation,
    impact_metrics,
)
from src.optimization.rule_engine import RuleEngine, RuleReport
from src.optimization.variables import DecisionSpace

#: The four gates, in the order they are applied. The first two are run-level (they can stop the
#: search before it starts), the last two are winner-level (they can refuse the search's answer).
GATE_ANOMALY = "anomaly_state"
GATE_MODEL_AVAILABILITY = "model_availability"
GATE_ENVELOPE = "envelope_and_constraints"
GATE_UNCERTAINTY = "prediction_uncertainty"

GATE_NAMES: tuple[str, ...] = (
    GATE_ANOMALY,
    GATE_MODEL_AVAILABILITY,
    GATE_ENVELOPE,
    GATE_UNCERTAINTY,
)

#: Where a candidate came from - recorded so a reported rejection can be traced to its generator.
ORIGIN_HOLD = "hold"
ORIGIN_GRID = "coordinate_grid"
ORIGIN_RANDOM = "seeded_random"
#: A candidate proposed by the optional SciPy refinement stage (``search.polish``, PRD 24's
#: ``differential_evolution``). Off by default - see :meth:`Optimizer._polish`.
ORIGIN_POLISH = "differential_evolution"
#: A candidate the *user* proposed through the PRD 16 what-if panel rather than the search.
ORIGIN_WHAT_IF = "what_if_request"

#: Improvement a candidate must beat the incumbent by before it takes over. Numerical only: it
#: exists so that a difference of one float ULP cannot decide a recommendation.
SCORE_EPSILON = 1e-9

#: Dataset name (PRD 11.2 / 12) -> the :class:`~src.process_models.plant.PlantTwin` attribute that
#: owns it. Candidate evaluation is per unit, so the mapping has to be explicit.
_UNIT_ATTRIBUTES: dict[str, str] = {"kiln": "kiln", "mill": "cement_mill"}

#: One extra minute-long step, used to verify that ``to_steady_state`` really did settle.
_VERIFY_STEP_SECONDS = 60.0

#: The only refinement method PRD 24 names, so the only value ``search.polish.method`` may take.
_POLISH_METHOD = "differential_evolution"

#: Score handed to the refinement stage for a candidate the PRD 14.3 gate did not accept. It is a
#: sentinel for "no admissible score exists", not a large penalty: nothing can trade against it,
#: which is what keeps the hard constraints hard even inside a continuous optimizer.
_INADMISSIBLE_SCORE = float("inf")


class _BudgetExhausted(Exception):
    """Raised inside the refinement stage when the unit-solve budget runs out mid-search."""


@dataclass(frozen=True, slots=True)
class _Uncertainty:
    """The two readings of one prediction set's spread - the claim and the report.

    ``claim_pct`` is the worst relative spread over ``targets`` (``uncertainty.optimizer_targets``,
    the quantities the PRD 14.2 objective is scored on) and is what the gate blocks on.
    ``worst_pct`` is the worst over *every* consulted prediction and ``wide`` names each one above
    the ceiling; both are reported and both feed the categorical Recommendation Quality, but
    neither vetoes. See :meth:`Optimizer._uncertainty_gate` for why.
    """

    limit_pct: float
    targets: tuple[str, ...]
    claim_pct: float | None
    worst_pct: float | None
    wide: tuple[tuple[str, int, float], ...]


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """One gate's verdict. ``blocking`` is what actually stops a recommendation."""

    name: str
    state: str
    blocking: bool
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.state == STATE_PASS

    @property
    def evaluated(self) -> bool:
        return self.state != STATE_NOT_EVALUATED

    def describe(self) -> dict[str, Any]:
        return {
            "gate": self.name,
            "state": self.state,
            "blocking": self.blocking,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    """One candidate action: what it proposed, what the gate said, and - only then - its score.

    ``score`` is ``None`` for every candidate the PRD 14.3 gate did not accept. That is the
    structural half of "hard constraints are never traded away": a rejected candidate has no
    number for the objective to compare, not merely a bad one.
    """

    index: int
    origin: str
    setpoints: dict[str, float]
    delta_fractions: dict[str, float]
    moved: tuple[str, ...]
    envelope: EnvelopeReport
    state: dict[str, float] | None = None
    objective: ObjectiveResult | None = None
    score: float | None = None
    settled: bool = True
    drift: float | None = None
    solves: int = 0

    @property
    def constraint_status(self) -> str:
        return self.envelope.constraint_status

    @property
    def envelope_status(self) -> str:
        return self.envelope.envelope_status

    @property
    def accepted(self) -> bool:
        """Eligible to be recommended: gate ``PASS``, verified settled, and scored."""
        return self.envelope.accepted and self.settled and self.score is not None

    @property
    def is_hold(self) -> bool:
        return not self.moved

    def action(self) -> str:
        if self.is_hold:
            return "hold the current setpoints"
        return "; ".join(
            f"{name} {self.delta_fractions[name] * 100:+.2f} %" for name in self.moved
        )

    def reason(self) -> str:
        """Why this candidate is or is not eligible - gate reason first, then convergence."""
        parts = [self.envelope.reason()]
        if not self.settled:
            parts.append(
                f"twin had not converged after {len(self.setpoints)} setpoint(s) were held: "
                f"largest relative drift {self.drift:.3g} over one further minute"
                if self.drift is not None
                else "twin convergence could not be verified"
            )
        return "; ".join(parts)

    def describe(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "origin": self.origin,
            "action": self.action(),
            "accepted": self.accepted,
            "constraint_status": self.constraint_status,
            "envelope_status": self.envelope_status,
            "score": self.score,
            "settled": self.settled,
            "convergence_drift": self.drift,
            "unit_solves": self.solves,
            "setpoints": dict(self.setpoints),
            "delta_fractions": dict(self.delta_fractions),
            "moved": list(self.moved),
            "reason": self.reason(),
            "objective_breakdown": None if self.objective is None else self.objective.breakdown,
            "envelope": self.envelope.describe(),
        }


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Everything one optimization run concluded, whether or not it recommends anything.

    A run that recommends nothing is not an error and is not empty: the candidates it rejected,
    the gates that blocked it and the PRD 14.5 baselines are all still here, because PRD 30 wants
    a refusal to be as inspectable as an acceptance.
    """

    mode: str
    message: str
    recommendation: Recommendation | None
    baseline: CandidateOutcome
    winner: CandidateOutcome | None
    candidates: tuple[CandidateOutcome, ...]
    gates: tuple[GateOutcome, ...]
    rules: RuleReport
    baselines: BaselineComparison | None
    evaluated: int
    solves: int
    budget_exhausted: bool
    runtime_s: float
    timestamp: Any

    @property
    def no_safe_recommendation(self) -> bool:
        return self.recommendation is None

    def gate(self, name: str) -> GateOutcome:
        for outcome in self.gates:
            if outcome.name == name:
                return outcome
        raise KeyError(f"no gate named {name!r}; expected one of {GATE_NAMES}")

    @property
    def blocked_by(self) -> tuple[str, ...]:
        return tuple(outcome.name for outcome in self.gates if outcome.blocking)

    @property
    def accepted_candidates(self) -> tuple[CandidateOutcome, ...]:
        return tuple(item for item in self.candidates if item.accepted)

    @property
    def rejected_candidates(self) -> tuple[CandidateOutcome, ...]:
        return tuple(item for item in self.candidates if not item.accepted)

    def improvement(self) -> float | None:
        """How much better than holding the winner is, on the objective. ``None`` if no winner."""
        if self.winner is None or self.winner.score is None:
            return None
        return float(self.baseline.score or 0.0) - float(self.winner.score)

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "message": self.message,
            "no_safe_recommendation": self.no_safe_recommendation,
            "timestamp": str(self.timestamp),
            "runtime_s": self.runtime_s,
            "candidates_evaluated": self.evaluated,
            "unit_solves": self.solves,
            "budget_exhausted": self.budget_exhausted,
            "accepted_candidates": len(self.accepted_candidates),
            "rejected_candidates": len(self.rejected_candidates),
            "blocked_by": list(self.blocked_by),
            "objective_improvement": self.improvement(),
            "gates": [outcome.describe() for outcome in self.gates],
            "rule_suggestion": self.rules.suggestion(),
            "recommendation": (
                None if self.recommendation is None else self.recommendation.describe()
            ),
            "baseline_candidate": self.baseline.describe(),
            "winner": None if self.winner is None else self.winner.describe(),
            "rejections": [item.describe() for item in self.rejected_candidates],
            "baselines": None if self.baselines is None else self.baselines.describe(),
        }

    #: Fields of :meth:`describe` that are wall-clock measurements rather than results.
    NON_REPRODUCIBLE_FIELDS: ClassVar[tuple[str, ...]] = ("runtime_s",)

    def signature(self) -> dict[str, Any]:
        """:meth:`describe` minus the wall clock - what "deterministic and reproducible" means here.

        Two runs on the same inputs, weights, mode, history and models return an *identical*
        signature, field for field and bit for bit: same candidate set in the same order, same
        gate verdicts and reasons, same rejections, same setpoints, same predictions, same
        baselines, same solve count. ``runtime_s`` is a measurement of the machine, not of the
        optimization, and is the only thing excluded.
        """
        payload = self.describe()
        for field_name in self.NON_REPRODUCIBLE_FIELDS:
            payload.pop(field_name, None)
        return payload


@dataclass(frozen=True, slots=True)
class SetpointAssessment:
    """One explicitly-named operating point, put through the same machinery as a candidate.

    This is the seam :mod:`src.optimization.what_if` reuses, and reusing it is the whole reason
    PRD 16.2's consistency guarantee ("results are guaranteed consistent between AI Recommendation
    and manual what-if") holds by construction rather than by parallel implementation: the settled
    state comes from :meth:`Optimizer._settle`, the verdict from the same
    :class:`~src.optimization.envelope.EnvelopeValidator`, the score from the same
    :class:`~src.optimization.objective.SoftObjective`, and the prediction and impact from the same
    :meth:`Optimizer._predict` / :meth:`Optimizer._recommend` the optimizer's winner goes through.

    One contract difference from :class:`OptimizationResult`, and it is deliberate.
    :attr:`recommendation` is always present, **including when the verdict is REJECTED or
    FLAGGED_FOR_REVIEW**, because PRD 16.3 requires the what-if panel to render a
    ``Recommendation``-shaped object carrying "a constraint-status banner (PASS/REJECTED/FLAGGED per
    constraint and per envelope check)". That is a *what-if answer*, not an optimizer suggestion:
    :meth:`Optimizer.optimize` still refuses to return anything but a ``PASS`` as its
    recommendation (PRD 34), and :attr:`accepted` is what separates the two here.
    """

    candidate: CandidateOutcome
    gates: tuple[GateOutcome, ...]
    predictions: tuple[Any, ...]
    prediction_notes: tuple[str, ...]
    uncertainty: "_Uncertainty"
    recommendation: Recommendation
    solves: int

    @property
    def blocking(self) -> tuple[GateOutcome, ...]:
        return tuple(gate for gate in self.gates if gate.blocking)

    @property
    def blocked_by(self) -> tuple[str, ...]:
        return tuple(gate.name for gate in self.blocking)

    @property
    def accepted(self) -> bool:
        """PRD 14.3 ``PASS`` *and* no blocking gate - the only state that may be acted on."""
        return self.candidate.accepted and not self.blocking

    def gate(self, name: str) -> GateOutcome:
        for outcome in self.gates:
            if outcome.name == name:
                return outcome
        raise KeyError(f"no gate named {name!r}; expected one of {GATE_NAMES}")

    def describe(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "blocked_by": list(self.blocked_by),
            "unit_solves": self.solves,
            "candidate": self.candidate.describe(),
            "gates": [gate.describe() for gate in self.gates],
            "prediction_notes": list(self.prediction_notes),
            "recommendation": self.recommendation.describe(),
        }


class Optimizer:
    """PRD 14.1's Model C. Owns candidate generation, the gates and the ranking - nothing else.

    It holds a twin but never commands it: the only mutation is ``reset()`` plus ``simulation_step``
    while settling a hypothetical, and the only output is a :class:`OptimizationResult` carrying at
    most one :class:`Recommendation`.
    """

    __slots__ = (
        "_baselines",
        "_cache",
        "_config",
        "_constraints",
        "_max_minutes",
        "_metrics",
        "_ml",
        "_objective",
        "_predictions",
        "_rules",
        "_search",
        "_space",
        "_tolerance",
        "_twin",
        "_units",
        "_validator",
    )

    def __init__(
        self,
        *,
        twin: Any,
        space: DecisionSpace,
        constraints: HardConstraints,
        objective: SoftObjective,
        validator: EnvelopeValidator,
        rule_engine: RuleEngine | None = None,
        predictions: Mapping[str, PredictionBundle] | None = None,
        baselines: BaselineSet | None = None,
        config: Config | None = None,
        ml_config: Config | None = None,
    ) -> None:
        self._twin = twin
        self._space = space
        self._constraints = constraints
        self._objective = objective
        self._validator = validator
        self._config = config if config is not None else load_config(OPTIMIZATION)
        self._ml = ml_config if ml_config is not None else load_config(ML)
        self._rules = (
            rule_engine
            if rule_engine is not None
            else RuleEngine.from_config(space=space, config=self._config)
        )
        self._predictions = (
            {} if predictions is None else {str(key): value for key, value in predictions.items()}
        )
        self._baselines = (
            baselines if baselines is not None else BaselineSet.from_config(config=self._config)
        )
        self._metrics = impact_metrics(self._config)
        search = self._config.get_path("search")
        self._search = {
            "delta_grid_fractions": tuple(
                float(value) for value in search.get_path("delta_grid_fractions")
            ),
            "max_coordinate_variables": int(search.get_path("max_coordinate_variables")),
            "coordinate_passes": int(search.get_path("coordinate_passes")),
            "n_random_candidates": int(search.get_path("n_random_candidates")),
            "max_unit_solves": int(search.get_path("max_unit_solves")),
            "random_state": int(search.get_path("random_state")),
            "polish": {
                "enabled": bool(search.get_path("polish.enabled")),
                "method": str(search.get_path("polish.method")),
                "maxiter": int(search.get_path("polish.maxiter")),
                "popsize": int(search.get_path("polish.popsize")),
                "tol": float(search.get_path("polish.tol")),
                "seed": int(search.get_path("polish.seed")),
                "time_budget_s": float(search.get_path("polish.time_budget_s")),
            },
        }
        if self._search["polish"]["method"] != _POLISH_METHOD:
            raise ValueError(
                f"search.polish.method must be {_POLISH_METHOD!r} (the only refinement method PRD "
                f"24 names), got {self._search['polish']['method']!r}"
            )
        self._max_minutes = int(search.get_path("steady_state.max_minutes"))
        self._tolerance = float(search.get_path("steady_state.tolerance_relative"))
        self._units = {}
        for dataset in dict.fromkeys(variable.dataset for variable in space):
            attribute = _UNIT_ATTRIBUTES.get(dataset)
            if attribute is None or not hasattr(twin, attribute):
                raise ValueError(
                    f"decision variables reference dataset {dataset!r}, but the twin exposes no "
                    f"{attribute!r} unit to settle it with"
                )
            self._units[dataset] = getattr(twin, attribute)
        self._cache: dict[tuple[Any, ...], tuple[dict[str, float], bool, float]] = {}

    # -- construction -----------------------------------------------------------------------
    @classmethod
    def from_twin(
        cls,
        twin: Any,
        *,
        scorer: Any | None = None,
        predictions: Mapping[str, PredictionBundle] | None = None,
        reference_scores: Any | None = None,
        training_ranges: Mapping[str, Any] | None = None,
        registry_path: Any | None = None,
        datasets: tuple[str, ...] | None = None,
        production_target_tph: float | None = None,
        blaine_target_cm2_g: float | None = None,
        weights: Mapping[str, float] | None = None,
        config: Config | None = None,
        ml_config: Config | None = None,
        scenarios: Config | None = None,
    ) -> "Optimizer":
        """Assemble the whole Model C stack around a twin, from config.

        ``training_ranges`` / ``registry_path`` pass straight through to
        :meth:`EnvelopeValidator.from_config`; when neither is given and ``predictions`` is, check
        1 validates against the ``training_domain`` of the very models being consulted, which is
        the strictest of the three sources PRD 14.3 allows.
        """
        optimization = config if config is not None else load_config(OPTIMIZATION)
        space = DecisionSpace.from_twin(twin, config=optimization, scenarios=scenarios)
        constraints = HardConstraints.from_config(
            config=optimization,
            production_target_tph=production_target_tph,
            blaine_target_cm2_g=blaine_target_cm2_g,
        )
        objective = SoftObjective.from_config(
            constraints=constraints, config=optimization, ml_config=ml_config, weights=weights
        )
        domains: tuple[dict[str, Any], ...] | None = None
        if training_ranges is None and registry_path is None and predictions:
            domains = tuple(
                domain
                for bundle in predictions.values()
                for domain in bundle.training_domains
            ) or None
        validator = EnvelopeValidator.from_config(
            space=space,
            constraints=constraints,
            scorer=scorer,
            training_ranges=training_ranges,
            training_domains=domains,
            registry_path=registry_path,
            datasets=datasets,
            reference_scores=reference_scores,
            config=optimization,
        )
        return cls(
            twin=twin,
            space=space,
            constraints=constraints,
            objective=objective,
            validator=validator,
            predictions=predictions,
            config=optimization,
            ml_config=ml_config,
        )

    # -- access -----------------------------------------------------------------------------
    @property
    def twin(self) -> Any:
        """The twin this optimizer questions. Read-only by convention: nothing here commands it."""
        return self._twin

    @property
    def max_minutes(self) -> int:
        """``search.steady_state.max_minutes`` - shared so a what-if settles over the same window."""
        return self._max_minutes

    @property
    def space(self) -> DecisionSpace:
        return self._space

    @property
    def constraints(self) -> HardConstraints:
        return self._constraints

    @property
    def objective(self) -> SoftObjective:
        return self._objective

    @property
    def validator(self) -> EnvelopeValidator:
        return self._validator

    @property
    def rule_engine(self) -> RuleEngine:
        return self._rules

    @property
    def baseline_set(self) -> BaselineSet:
        return self._baselines

    @property
    def predictions(self) -> dict[str, PredictionBundle]:
        return dict(self._predictions)

    @property
    def search(self) -> dict[str, Any]:
        return dict(self._search)

    @property
    def model_version(self) -> str:
        """Which artefacts produced this run - the PRD 14.4 ``model_version`` string."""
        versions = sorted(
            {
                str(version)
                for bundle in self._predictions.values()
                for version in bundle.describe()["model_versions"]
            }
        )
        joined = ",".join(versions) if versions else "no_model_a"
        return f"twin=prd-{PRD_VERSION};model_a={joined}"

    # -- the PRD 14.1 flow ------------------------------------------------------------------
    def optimize(
        self,
        *,
        inputs: Mapping[str, float],
        observed_state: Mapping[str, float] | None = None,
        history: pd.DataFrame | None = None,
        mode: str = "NORMAL",
        anomaly: Any = None,
        weights: Mapping[str, float] | None = None,
        timestamp: Any = None,
        regime: str | None = None,
        production_target_tph: float | None = None,
    ) -> OptimizationResult:
        """Run PRD 14.1 end to end and return at most one recommendation.

        ``inputs`` is the current twin input vector (the *setpoints in force*, plus the exogenous
        inputs held constant across the run). ``observed_state`` is what the sensors report now -
        used for the rule engine, the PRD 14.5 "current operating point" row and nothing else;
        every reported delta is twin-vs-twin so that it is the effect of the move rather than the
        twin/sensor offset. ``anomaly`` may be one Model B report, a sequence of them or a
        dataset-keyed mapping.
        """
        started = time.perf_counter()
        mode = str(mode).upper()
        self._space.max_delta_fraction(mode)  # validates the mode name before anything else
        objective = self._objective if weights is None else self._objective.with_weights(weights)
        base_inputs = {str(key): float(value) for key, value in inputs.items()}
        baseline_setpoints = self._space.baseline(base_inputs)
        stamp = _timestamp_of(history, timestamp)
        # The settle memo is per run, not per optimizer. Keeping it across calls would make the
        # reported ``solves`` depend on cache warmth, and requirement 13 wants two identical calls
        # to produce two identical payloads - including the counters.
        self._cache = {}

        # 1. Current state -> digital twin. The do-nothing candidate is candidate zero, so that
        #    "hold" competes on the same footing as every move rather than being a fallback.
        solves = 0
        baseline, used = self._evaluate(
            index=0,
            origin=ORIGIN_HOLD,
            proposed=baseline_setpoints,
            baseline_setpoints=baseline_setpoints,
            base_inputs=base_inputs,
            mode=mode,
            objective=objective,
            baseline_state=None,
        )
        solves += used
        baseline_state = baseline.state

        observed = self._observed(observed_state, history, baseline_state)
        rules = self._rules.evaluate(
            observed.state,
            baseline_setpoints,
            previous_state=_previous_row(history),
            mode=mode,
        )

        # 2. Run-level gates. Neither is a property of any candidate, so both are asked before a
        #    single candidate is generated: an anomalous plant or an absent Model A cannot be
        #    optimized around, and pretending otherwise would waste the budget to no purpose.
        gates = [self._anomaly_gate(anomaly), self._availability_gate()]
        candidates: list[CandidateOutcome] = [baseline]
        exhausted = False
        winner: CandidateOutcome | None = None
        if not any(gate.blocking for gate in gates):
            generated, solves_used, exhausted = self._search_candidates(
                baseline=baseline,
                baseline_setpoints=baseline_setpoints,
                base_inputs=base_inputs,
                mode=mode,
                objective=objective,
                baseline_state=baseline_state,
                solves_used=solves,
            )
            candidates.extend(generated)
            solves += solves_used
            winner = _pick(candidates)

        # 3. Winner-level gates. The envelope gate simply reports what the winning candidate's own
        #    PRD 14.3 report already said - it is a gate because "the search returned nothing that
        #    passed" has to be a blocking, named outcome rather than an empty list.
        gates.append(self._envelope_gate(winner, baseline))
        predictions, notes = self._predict(winner, history)
        uncertainty = self._uncertainty(predictions)
        gates.append(self._uncertainty_gate(winner, predictions, uncertainty, notes))

        blocking = tuple(gate for gate in gates if gate.blocking)
        recommendation: Recommendation | None = None
        if winner is not None and not blocking:
            recommendation = self._recommend(
                winner=winner,
                baseline=baseline,
                observed=observed,
                objective=objective,
                predictions=predictions,
                uncertainty=uncertainty,
                mode=mode,
                timestamp=stamp,
            )
        elif winner is not None:
            winner = None

        rule_state, rule_solves = self._rule_state(rules, base_inputs, baseline, mode)
        solves += rule_solves
        comparison = self._baselines.build(
            observed_state=observed.state,
            observed_setpoints=baseline_setpoints,
            timestamp=stamp,
            history=history,
            regime=regime,
            production_target_tph=production_target_tph,
            rule_state=rule_state,
            rule_setpoints=rules.proposed_setpoints,
            rule_detail=rules.suggestion(),
            recommendation=recommendation,
        )
        message = (
            _accepted_message(recommendation)
            if recommendation is not None
            else f"{NO_SAFE_RECOMMENDATION}: "
            + "; ".join(f"{gate.name} - {gate.reason}" for gate in blocking)
        )
        return OptimizationResult(
            mode=mode,
            message=message,
            recommendation=recommendation,
            baseline=baseline,
            winner=winner,
            candidates=tuple(candidates),
            gates=tuple(gates),
            rules=rules,
            baselines=comparison,
            evaluated=len(candidates),
            solves=solves,
            budget_exhausted=exhausted,
            runtime_s=time.perf_counter() - started,
            timestamp=stamp,
        )

    # -- one named operating point (PRD 16.2's "same call optimization uses") ----------------
    def assess_setpoints(
        self,
        *,
        proposed: Mapping[str, float],
        inputs: Mapping[str, float],
        observed_state: Mapping[str, float] | None = None,
        history: pd.DataFrame | None = None,
        mode: str = "NORMAL",
        anomaly: Any = None,
        weights: Mapping[str, float] | None = None,
        timestamp: Any = None,
        baseline: CandidateOutcome | None = None,
    ) -> SetpointAssessment:
        """Evaluate one caller-supplied setpoint vector exactly as a search candidate is evaluated.

        Everything PRD 16.2 asks a what-if to reuse is reused literally: the baseline is the same
        do-nothing candidate :meth:`optimize` starts from, ``proposed`` goes through the same
        :meth:`_evaluate` (checks 1 and 4 before any solve, then ``to_steady_state``, then checks 2
        and 3, then - and only then - the objective), and the survivor goes through the same
        prediction, uncertainty and :class:`~src.optimization.recommendation.Recommendation`
        assembly. Nothing here re-derives a number the optimizer derives elsewhere.

        ``baseline`` may be passed in to reuse an already-settled baseline candidate across several
        what-if requests against the same operating point; the memo is *not* reset here, so a caller
        exploring a slider pays for each distinct point once.
        """
        mode = str(mode).upper()
        self._space.max_delta_fraction(mode)
        objective = self._objective if weights is None else self._objective.with_weights(weights)
        base_inputs = {str(key): float(value) for key, value in inputs.items()}
        baseline_setpoints = self._space.baseline(base_inputs)
        stamp = _timestamp_of(history, timestamp)
        solves = 0
        if baseline is None:
            baseline, used = self._evaluate(
                index=0,
                origin=ORIGIN_HOLD,
                proposed=baseline_setpoints,
                baseline_setpoints=baseline_setpoints,
                base_inputs=base_inputs,
                mode=mode,
                objective=objective,
                baseline_state=None,
            )
            solves += used
        candidate, used = self._evaluate(
            index=1,
            origin=ORIGIN_WHAT_IF,
            proposed={**baseline_setpoints, **proposed},
            baseline_setpoints=baseline_setpoints,
            base_inputs=base_inputs,
            mode=mode,
            objective=objective,
            baseline_state=baseline.state,
        )
        solves += used

        gates = [
            self._anomaly_gate(anomaly),
            self._availability_gate(),
            self._envelope_gate(candidate if candidate.accepted else None, baseline),
        ]
        predictions, notes = self._predict(candidate if candidate.state else None, history)
        uncertainty = self._uncertainty(predictions)
        gates.append(
            self._uncertainty_gate(
                candidate if candidate.state else None, predictions, uncertainty, notes
            )
        )
        observed = self._observed(observed_state, history, baseline.state)
        return SetpointAssessment(
            candidate=candidate,
            gates=tuple(gates),
            predictions=predictions,
            prediction_notes=notes,
            uncertainty=uncertainty,
            recommendation=self._recommend(
                winner=candidate,
                baseline=baseline,
                observed=observed,
                objective=objective,
                predictions=predictions,
                uncertainty=uncertainty,
                mode=mode,
                timestamp=stamp,
            ),
            solves=solves,
        )

    # -- candidate generation (PRD 14.1 "Candidate Actions") --------------------------------
    def _search_candidates(
        self,
        *,
        baseline: CandidateOutcome,
        baseline_setpoints: Mapping[str, float],
        base_inputs: Mapping[str, float],
        mode: str,
        objective: SoftObjective,
        baseline_state: dict[str, float] | None,
        solves_used: int,
    ) -> tuple[list[CandidateOutcome], int, bool]:
        """Coordinate grid then seeded random sample, both inside the unit-solve budget.

        The grid is deliberately coarse and fixed (``search.delta_grid_fractions``): a documented
        step set is reproducible and auditable, where a continuous solver's trajectory is neither.
        Candidates are always measured against the *baseline* value, never against the incumbent,
        so ``max_change`` means what PRD 14.2 says it means - a bound on the move away from where
        the plant is now, not a bound per pass.
        """
        names = self._optimizable_names()
        results: list[CandidateOutcome] = []
        seen: set[tuple[tuple[str, float], ...]] = {_key(baseline.setpoints)}
        scored: dict[tuple[tuple[str, float], ...], float] = {
            _key(baseline.setpoints): (
                baseline.score if baseline.accepted and baseline.score is not None
                else _INADMISSIBLE_SCORE
            )
        }
        budget = self._search["max_unit_solves"]
        spent = solves_used
        exhausted = False
        incumbent = baseline
        index = 1

        def consider(proposal: dict[str, float], origin: str) -> bool:
            """Evaluate one proposal if it is new and affordable. Returns False when out of budget."""
            nonlocal spent, exhausted, index, incumbent
            signature = _key(proposal)
            if signature in seen:
                return True
            if spent >= budget:
                exhausted = True
                return False
            seen.add(signature)
            outcome, used = self._evaluate(
                index=index,
                origin=origin,
                proposed=proposal,
                baseline_setpoints=baseline_setpoints,
                base_inputs=base_inputs,
                mode=mode,
                objective=objective,
                baseline_state=baseline_state,
            )
            spent += used
            index += 1
            results.append(outcome)
            scored[signature] = (
                outcome.score if outcome.accepted and outcome.score is not None
                else _INADMISSIBLE_SCORE
            )
            if _better(outcome, incumbent):
                incumbent = outcome
            return True

        limit = self._search["max_coordinate_variables"]
        for _ in range(self._search["coordinate_passes"]):
            for name in names:
                for fraction in self._search["delta_grid_fractions"]:
                    if fraction == 0.0:
                        continue
                    proposal = dict(incumbent.setpoints)
                    proposal[name] = self._offset(name, baseline_setpoints[name], fraction, mode)
                    if len(_moved(proposal, baseline_setpoints)) > limit:
                        continue
                    if not consider(proposal, ORIGIN_GRID):
                        return results, spent - solves_used, exhausted

        rng = np.random.default_rng(self._search["random_state"])
        span = self._space.max_delta_fraction(mode)
        for _ in range(self._search["n_random_candidates"]):
            picked = rng.choice(len(names), size=min(limit, len(names)), replace=False)
            proposal = dict(baseline_setpoints)
            for position in sorted(int(value) for value in picked):
                name = names[position]
                fraction = float(rng.uniform(-span, span))
                proposal[name] = self._offset(name, baseline_setpoints[name], fraction, mode)
            if not consider(proposal, ORIGIN_RANDOM):
                break

        if self._search["polish"]["enabled"] and names:
            self._polish(
                consider=consider,
                scored=scored,
                names=names,
                baseline_setpoints=baseline_setpoints,
                mode=mode,
            )
        return results, spent - solves_used, exhausted

    def _polish(
        self,
        *,
        consider: Callable[[dict[str, float], str], bool],
        scored: Mapping[tuple[tuple[str, float], ...], float],
        names: Sequence[str],
        baseline_setpoints: Mapping[str, float],
        mode: str,
    ) -> None:
        """Optional SciPy ``differential_evolution`` refinement over all variables jointly.

        ``search.polish.enabled`` is **false** by default and the stage is documented in
        ``configs/optimization.yaml`` as offline-only, for the measured NFR-2 reason recorded there:
        a population method needs on the order of ``popsize * ndim * maxiter`` evaluations, which is
        far past the 3 s round-trip budget. It exists anyway because it is the one thing the
        coordinate grid structurally cannot do - ``search.max_coordinate_variables`` caps the grid at
        two variables moving jointly, so a three-or-more-variable combination is unreachable from
        that generator no matter how fine the grid gets.

        Three properties make it safe to add a stochastic solver to a safety-gated search:

        * **It cannot reach a candidate the gate has not seen.** Every vector DE proposes is snapped
          onto the PRD 17 step grid and clipped to the mode bound by :meth:`_offset`, then goes
          through the same :meth:`_evaluate` as a grid candidate - same checks, same order. DE
          proposes; it never admits.
        * **It cannot trade a hard constraint away.** An inadmissible candidate scores
          :data:`_INADMISSIBLE_SCORE` (``inf``), not a large finite penalty, so no objective gain can
          buy it. DE simply sees a plateau it cannot descend into.
        * **It is reproducible.** ``search.polish.seed`` fixes the population, the snap makes the
          objective a step function on a fixed grid, and repeated points are answered from the memo,
          so two runs evaluate the same set of candidates in the same order.

        The stage stops early - via the ``callback`` - when the unit-solve budget is exhausted or
        ``search.polish.time_budget_s`` elapses, and it never returns a candidate: everything it
        finds is already in ``results`` through ``consider``, and :func:`_pick` chooses the winner
        from that one list regardless of which generator produced it. The time budget is honoured at
        a *generation* boundary, not per evaluation - SciPy only consults the callback between
        generations - so the first population is always paid for in full. With ``init="sobol"`` SciPy
        rounds ``popsize * ndim`` up to the next power of two, so that first population is 64
        proposals for the six-variable space, not 36.

        MEASURED on the reference operating point, ``max_unit_solves`` raised to 400 so the stage was
        not cut off: 128 distinct proposals (two generations), costing 28 unit solves beyond the
        grid's 41 because the memo answers every repeated grid point, 6.37 s total against 4.45 s
        with the stage off - and **zero of the 128 were accepted by the PRD 14.3 gate**. Every one of
        them moved all six variables at once, and an arbitrary six-variable move at this operating
        point always lands outside the Blaine window or the production tolerance. The winner was the
        same coordinate-grid candidate with the same score (``-0.8208879904152555``) in both runs.
        That is the honest reason the stage ships disabled: on this synthetic plant it is not merely
        too slow for NFR-2, it does not find anything. It is kept, wired and tested rather than
        deleted because the config declares it, PRD 24 names the method, and a future calibration
        with a wider admissible region is exactly where a joint search would start to pay.
        """
        from scipy.optimize import differential_evolution  # local: NFR-2 keeps it off the hot path

        settings = self._search["polish"]
        bounds = [
            self._space.bounds(name, float(baseline_setpoints[name]), mode) for name in names
        ]
        if any(low >= high for low, high in bounds):  # pragma: no cover - degenerate mode bound
            return
        started = time.perf_counter()
        stop = False

        def evaluate(vector: Any) -> float:
            nonlocal stop
            proposal = dict(baseline_setpoints)
            for name, raw in zip(names, vector):
                current = float(baseline_setpoints[name])
                fraction = 0.0 if current == 0.0 else (float(raw) - current) / abs(current)
                proposal[name] = self._offset(name, current, fraction, mode)
            signature = _key(proposal)
            if signature not in scored and not consider(proposal, ORIGIN_POLISH):
                stop = True
                raise _BudgetExhausted
            if time.perf_counter() - started > settings["time_budget_s"]:
                stop = True
            return scored.get(signature, _INADMISSIBLE_SCORE)

        try:
            differential_evolution(
                evaluate,
                bounds,
                maxiter=settings["maxiter"],
                popsize=settings["popsize"],
                tol=settings["tol"],
                seed=settings["seed"],
                polish=False,  # a gradient polish would leave the step grid, so no
                init="sobol",  # deterministic population, unlike the default LHS draw
                callback=lambda *_args, **_kwargs: stop,
            )
        except _BudgetExhausted:
            return

    def _offset(self, name: str, current: float, fraction: float, mode: str) -> float:
        """Move one variable by a fraction of its current value, snapped then clipped to bounds."""
        low, high = self._space.bounds(name, current, mode)
        target = self._space.snap(name, float(current) * (1.0 + float(fraction)), float(current))
        return min(max(target, low), high)

    def _optimizable_names(self) -> tuple[str, ...]:
        """Decision variables the optimizer may move, in config order.

        A dataset with no Model A is frozen rather than optimized blind: requirement "required
        prediction models are unavailable -> reject" is met by never proposing such a move in the
        first place, and the exclusion is disclosed by the availability gate.
        """
        allowed = self._optimizable_datasets()
        return tuple(
            variable.name for variable in self._space if variable.dataset in allowed
        )

    def _optimizable_datasets(self) -> tuple[str, ...]:
        datasets = tuple(dict.fromkeys(variable.dataset for variable in self._space))
        if not self._predictions:
            return ()
        return tuple(
            dataset
            for dataset in datasets
            if dataset in self._predictions and self._predictions[dataset].available
        )

    # -- candidate evaluation (PRD 14.1 "Simulate Each Action") ------------------------------
    def _evaluate(
        self,
        *,
        index: int,
        origin: str,
        proposed: Mapping[str, float],
        baseline_setpoints: Mapping[str, float],
        base_inputs: Mapping[str, float],
        mode: str,
        objective: SoftObjective,
        baseline_state: dict[str, float] | None,
    ) -> tuple[CandidateOutcome, int]:
        """Simulate one candidate, gate it, and score it only if the gate accepted it.

        Checks 1 and 4 are asked *first*, because they need no twin solve: a candidate outside the
        recorded training range or beyond the mode's change limit is rejected for free, with the
        same report structure as any other rejection. Only survivors cost simulation time.
        """
        proposal = {str(name): float(value) for name, value in proposed.items()}
        deltas = self._space.delta_fractions(proposal, baseline_setpoints)
        moved = _moved(proposal, baseline_setpoints)
        pre = self._validator.pre_validate(proposal, baseline_setpoints, mode)
        enforce = self._space.enforce_envelope(mode)
        if pre[1].failed or (enforce and pre[0].failed):
            report = self._validator.validate(
                proposed=proposal, baseline=baseline_setpoints, mode=mode, pre=pre
            )
            return (
                CandidateOutcome(
                    index=index,
                    origin=origin,
                    setpoints=proposal,
                    delta_fractions=deltas,
                    moved=moved,
                    envelope=report,
                ),
                0,
            )

        inputs = {**base_inputs, **self._space.to_twin_inputs(proposal)}
        state, settled, drift, solves = self._settle(inputs)
        report = self._validator.validate(
            proposed=proposal,
            baseline=baseline_setpoints,
            mode=mode,
            simulated_state=state,
            features=self._features(proposal, state),
            pre=pre,
        )
        reference = state if baseline_state is None else baseline_state
        result: ObjectiveResult | None = None
        score: float | None = None
        if report.accepted and settled:
            result = objective.score(reference, state, delta_fractions=deltas)
            score = float(result.total)
        return (
            CandidateOutcome(
                index=index,
                origin=origin,
                setpoints=proposal,
                delta_fractions=deltas,
                moved=moved,
                envelope=report,
                state=state,
                objective=result,
                score=score,
                settled=settled,
                drift=drift,
                solves=solves,
            ),
            solves,
        )

    def _settle(self, inputs: Mapping[str, float]) -> tuple[dict[str, float], bool, float, int]:
        """Settle every unit on ``inputs`` and verify it really settled. Memoized per unit.

        ``reset()`` before each solve is what makes a settled state a function of the inputs alone
        rather than of the order candidates were tried in - which is both a correctness condition
        for the cache and the reason two runs agree exactly.
        """
        decision_inputs = {variable.twin_input for variable in self._space}
        exogenous = tuple(
            sorted(
                (key, round(float(value), 9))
                for key, value in inputs.items()
                if key not in decision_inputs
            )
        )
        state: dict[str, float] = {}
        settled = True
        worst = 0.0
        solves = 0
        for dataset, unit in self._units.items():
            key = (
                dataset,
                exogenous,
                tuple(
                    round(float(inputs[variable.twin_input]), 9)
                    for variable in self._space.of_dataset(dataset)
                ),
            )
            cached = self._cache.get(key)
            if cached is None:
                unit.reset()
                outputs = dict(unit.to_steady_state(dict(inputs), self._max_minutes))
                after = unit.simulation_step(dict(inputs), _VERIFY_STEP_SECONDS)
                drift = max(
                    (
                        abs(float(after[tag]) - float(value)) / max(1.0, abs(float(value)))
                        for tag, value in outputs.items()
                    ),
                    default=0.0,
                )
                cached = (outputs, drift <= self._tolerance, drift)
                self._cache[key] = cached
                solves += 1
            state.update(cached[0])
            settled = settled and cached[1]
            worst = max(worst, cached[2])
        return state, settled, worst, solves

    def _features(
        self, proposal: Mapping[str, float], state: Mapping[str, float]
    ) -> dict[str, float]:
        """PRD 14.3 check 2's feature vector: the settled state, with setpoints filling the gaps.

        The settled state wins on collision because several setpoint tags are also *outputs* -
        ``kiln_fuel_rate_tph`` is derived by the PRD 9.3 energy balance - and Model B was trained
        on the published tag, not on the request.
        """
        features = {str(name): float(value) for name, value in proposal.items()}
        features.update({str(tag): float(value) for tag, value in state.items()})
        return features

    # -- the four gates ----------------------------------------------------------------------
    def _anomaly_gate(self, anomaly: Any) -> GateOutcome:
        """An active Model B anomaly stops the run (PRD 30: no suggestion over an open anomaly)."""
        reports = _as_reports(anomaly)
        detail: dict[str, Any] = {
            "reports": [
                {
                    "dataset": getattr(report, "dataset", None),
                    "status": getattr(report, "status", None),
                    "hypothesis": getattr(report, "hypothesis", None),
                    "flagged": bool(getattr(report, "flagged", False)),
                    "out_of_distribution": bool(getattr(report, "out_of_distribution", False)),
                }
                for report in reports
            ]
        }
        if not reports:
            return GateOutcome(
                GATE_ANOMALY,
                STATE_NOT_EVALUATED,
                False,
                "no Model B report was supplied, so anomaly state could not be checked; with no "
                "Model B the PRD 14.3 feature-space check is unevaluated too, which already "
                "prevents any candidate from reaching a full PASS",
                detail,
            )
        active = tuple(report for report in reports if bool(getattr(report, "is_anomaly", False)))
        if active:
            listed = "; ".join(
                f"{getattr(report, 'dataset', '?')}: {getattr(report, 'status', '?')} - "
                f"{getattr(report, 'hypothesis', 'no hypothesis')}"
                for report in active
            )
            return GateOutcome(
                GATE_ANOMALY,
                STATE_FAIL,
                True,
                f"Model B reports an active anomaly ({listed}); an optimization suggestion laid "
                "on top of an unexplained anomaly would be advice about a plant the models no "
                "longer describe",
                detail,
            )
        noted = tuple(
            getattr(report, "dataset", "?")
            for report in reports
            if bool(getattr(report, "flagged", False))
            or bool(getattr(report, "out_of_distribution", False))
        )
        tail = (
            ""
            if not noted
            else f"; {list(noted)} carry a non-blocking Isolation-Forest flag, reported not hidden"
        )
        return GateOutcome(
            GATE_ANOMALY,
            STATE_PASS,
            False,
            f"all {len(reports)} Model B report(s) are NORMAL{tail}",
            detail,
        )

    def _availability_gate(self) -> GateOutcome:
        """Model A must exist for whatever the recommendation moves, or nothing is recommended."""
        datasets = tuple(dict.fromkeys(variable.dataset for variable in self._space))
        allowed = self._optimizable_datasets()
        frozen = tuple(dataset for dataset in datasets if dataset not in allowed)
        detail = {
            "datasets": list(datasets),
            "optimizable": list(allowed),
            "frozen": list(frozen),
            "missing_models": {
                dataset: [list(pair) for pair in bundle.missing()]
                for dataset, bundle in sorted(self._predictions.items())
            },
        }
        if not allowed:
            return GateOutcome(
                GATE_MODEL_AVAILABILITY,
                STATE_FAIL,
                True,
                "no Model A horizon model is available for any dataset with decision variables, "
                "so no candidate's predicted response could be reported - a recommendation "
                "without a prediction is not a recommendation this platform makes",
                detail,
            )
        if frozen:
            return GateOutcome(
                GATE_MODEL_AVAILABILITY,
                STATE_PASS,
                False,
                f"Model A is available for {list(allowed)}; {list(frozen)} has no trained model, "
                "so its variables are frozen rather than optimized blind",
                detail,
            )
        return GateOutcome(
            GATE_MODEL_AVAILABILITY,
            STATE_PASS,
            False,
            f"Model A is available for every dataset with decision variables {list(allowed)}",
            detail,
        )

    def _envelope_gate(
        self, winner: CandidateOutcome | None, baseline: CandidateOutcome
    ) -> GateOutcome:
        """Reports the winning candidate's own PRD 14.3 verdict, or the absence of a winner."""
        if winner is None:
            return GateOutcome(
                GATE_ENVELOPE,
                STATE_FAIL,
                True,
                "no candidate passed the PRD 14.3 gate; holding the current setpoints is itself "
                f"{baseline.constraint_status} / {baseline.envelope_status} - {baseline.reason()}",
                {
                    "baseline_constraint_status": baseline.constraint_status,
                    "baseline_envelope_status": baseline.envelope_status,
                },
            )
        report = winner.envelope
        return GateOutcome(
            GATE_ENVELOPE,
            STATE_PASS,
            False,
            f"the recommended candidate is {report.constraint_status} / {report.envelope_status} "
            f"in {report.mode} mode: {report.reason()}",
            {
                "ood_ratio": report.ood_ratio,
                "flag_threshold_source": report.flag_threshold_source,
                "constraint_margin": (
                    None if report.constraint_report is None else report.constraint_report.margin
                ),
                "convergence_drift": winner.drift,
            },
        )

    def _uncertainty_gate(
        self,
        winner: CandidateOutcome | None,
        predictions: tuple[Any, ...],
        uncertainty: "_Uncertainty",
        notes: tuple[str, ...],
    ) -> GateOutcome:
        """Model A's own spread, against the ceiling ``configs/ml.yaml`` already documents.

        The limit is ``recommendation_quality.medium.max_relative_uncertainty_pct``: a spread wider
        than what the ML layer already calls MEDIUM cannot support a recommendation of any quality.
        No new threshold is invented here, and no percentage is turned into a confidence figure -
        the spread is Model A's, reported as Model A's.

        ASSUMPTION (documented deviation, see the module docstring) - the ceiling is applied to the
        predictions of ``uncertainty.optimizer_targets``, the quantities the PRD 14.2 objective is
        scored on, rather than to every consulted target. The wider all-target figure is still
        computed, still reported here, and still caps the Recommendation Quality through
        :func:`~src.models.quality.assess_quality`; what it does not do is veto. A target the
        recommendation only *reports* is shown with its spread and its LOW grade beside it
        (FR-23), which is PRD 30's "shown, not hidden" - whereas letting one structurally
        unpredictable tag block every candidate would make the gate a constant answer rather than
        a check on the candidate.
        """
        limit = uncertainty.limit_pct
        detail: dict[str, Any] = {
            "limit_pct": limit,
            "limit_source": "configs/ml.yaml recommendation_quality.medium."
            "max_relative_uncertainty_pct",
            "objective_targets": list(uncertainty.targets),
            "claim_spread_pct": uncertainty.claim_pct,
            "worst_relative_spread_pct": uncertainty.worst_pct,
            "wide_predictions": [
                {"target": target, "horizon_min": horizon, "relative_spread_pct": pct}
                for target, horizon, pct in uncertainty.wide
            ],
            "predictions": len(predictions),
            "notes": list(notes),
        }
        if winner is None:
            return GateOutcome(
                GATE_UNCERTAINTY,
                STATE_NOT_EVALUATED,
                False,
                "not evaluated - the search produced no candidate to predict for",
                detail,
            )
        if not predictions:
            return GateOutcome(
                GATE_UNCERTAINTY,
                STATE_NOT_EVALUATED,
                True,
                "Model A produced no prediction for the recommended candidate"
                + (f" ({'; '.join(notes)})" if notes else "")
                + ", so its uncertainty could not be checked and the candidate cannot be "
                "presented as safe",
                detail,
            )
        if uncertainty.claim_pct is None:
            return GateOutcome(
                GATE_UNCERTAINTY,
                STATE_NOT_EVALUATED,
                True,
                "Model A returned no uncertainty spread for "
                f"{list(uncertainty.targets)}, the targets this objective is scored on, so the "
                "ceiling could not be applied - an unmeasured uncertainty is not a small one",
                detail,
            )
        if uncertainty.claim_pct > limit:
            return GateOutcome(
                GATE_UNCERTAINTY,
                STATE_FAIL,
                True,
                f"worst relative prediction spread {uncertainty.claim_pct:.2f} % on the objective "
                f"targets {list(uncertainty.targets)} exceeds the {limit:.2f} % ceiling that "
                "configs/ml.yaml sets for a MEDIUM-quality recommendation, so the claimed "
                "improvement is not supported by the prediction it rests on",
                detail,
            )
        reason = (
            f"worst relative prediction spread {uncertainty.claim_pct:.2f} % on the objective "
            f"targets {list(uncertainty.targets)} is within the {limit:.2f} % ceiling for a "
            "MEDIUM-quality recommendation"
        )
        if uncertainty.wide:
            widest = "; ".join(
                f"{target} t+{horizon}min {pct:.1f} %" for target, horizon, pct in uncertainty.wide
            )
            reason += (
                f". Reported-only targets above the same ceiling ({widest}) do not block, but they "
                f"cap the Recommendation Quality and are shown with their spread"
            )
        return GateOutcome(GATE_UNCERTAINTY, STATE_PASS, False, reason, detail)

    def _uncertainty(self, predictions: tuple[Any, ...]) -> "_Uncertainty":
        """Both readings of Model A's spread for one prediction set - the claim and the report."""
        limit = uncertainty_limit_pct(self._ml)
        targets = objective_targets(self._ml)
        return _Uncertainty(
            limit_pct=limit,
            targets=targets,
            claim_pct=relative_uncertainty_pct(predictions, targets=targets),
            worst_pct=relative_uncertainty_pct(predictions),
            wide=wide_predictions(predictions, limit),
        )

    # -- Model A, the recommendation, and the observed point ---------------------------------
    def _predict(
        self, winner: CandidateOutcome | None, history: pd.DataFrame | None
    ) -> tuple[tuple[Any, ...], tuple[str, ...]]:
        """Model A's multi-horizon response to the *recommended* candidate only.

        Consulted once, for one candidate: PRD 14.1 uses the twin to rank candidates and Model A to
        report what the survivor is expected to do next, so ``predicted_state_by_horizon`` covers
        the proposed state and nothing else. ``sustained`` defaults to true for a candidate state,
        which is the honest construction - the lag block describes the move being held, not the
        pre-move history spliced onto a settled state.
        """
        if winner is None or winner.state is None or not self._predictions:
            return (), ()
        if history is None or history.empty:
            return (), ("no history was supplied, so Model A's lag features cannot be built",)
        margin = (
            None
            if winner.envelope.constraint_report is None
            else winner.envelope.constraint_report.margin
        )
        predictions: list[Any] = []
        notes: list[str] = []
        for dataset in sorted(self._predictions):
            bundle = self._predictions[dataset]
            if not bundle.available:
                continue
            try:
                predictions.extend(
                    bundle.predict(
                        history=history,
                        candidate_state=winner.state,
                        constraint_margin=margin,
                        ood_score_ratio=winner.envelope.ood_ratio,
                    )
                )
            except (KeyError, ValueError) as error:  # short history, missing feature column
                notes.append(f"{dataset}: {error}")
        return tuple(predictions), tuple(notes)

    def _recommend(
        self,
        *,
        winner: CandidateOutcome,
        baseline: CandidateOutcome,
        observed: "_ObservedPoint",
        objective: SoftObjective,
        predictions: tuple[Any, ...],
        uncertainty: "_Uncertainty",
        mode: str,
        timestamp: Any,
    ) -> Recommendation:
        """Assemble PRD 14.4's object for the one candidate that survived every gate.

        The objective is re-scored here with ``predicted_variability_pct`` so that the stability
        term's second half - how much Model A expects the plant to wander - is assessed for the
        recommendation. Ranking deliberately does not include it: it would cost one Model A call
        per candidate, and NFR-2 gives the whole round trip three seconds. The ranking score stays
        on the :class:`CandidateOutcome`, this one goes in the recommendation, and a test asserts
        the two differ only in that term.

        Quality and the reported impact take the **all-target** spread
        (:attr:`_Uncertainty.worst_pct`), not the narrower figure the gate blocks on: a target the
        recommendation only reports still caps how good the recommendation may be called.
        """
        variability = cross_horizon_spread_pct(predictions) if predictions else None
        final = objective.score(
            baseline.state or {},
            winner.state or {},
            delta_fractions=winner.delta_fractions,
            predicted_variability_pct=variability,
        )
        margin = (
            None
            if winner.envelope.constraint_report is None
            else winner.envelope.constraint_report.margin
        )
        quality = assess_quality(
            relative_uncertainty_pct=uncertainty.worst_pct,
            model_disagreement_pct=worst_disagreement_pct(predictions),
            constraint_margin=margin,
            ood_score_ratio=winner.envelope.ood_ratio,
            config=self._ml,
        )
        impact = ExpectedImpact.build(
            baseline_state=baseline.state or {},
            proposed_state=winner.state or {},
            metrics=self._metrics,
            relative_uncertainty_pct=uncertainty.worst_pct,
            predicted_variability_pct=variability,
        )
        return Recommendation(
            baseline_state=dict(baseline.state or {}),
            proposed_state=dict(winner.state or {}),
            predicted_state_by_horizon=by_horizon(predictions),
            expected_impact=impact,
            objective_breakdown=final.breakdown,
            recommendation_quality=quality.level,
            mode=mode,
            envelope_status=winner.envelope_status,
            constraint_status=winner.constraint_status,
            reason=winner.reason(),
            model_version=self.model_version,
            timestamp=timestamp,
            baseline_setpoints=dict(baseline.setpoints),
            proposed_setpoints=dict(winner.setpoints),
            delta_fractions=dict(winner.delta_fractions),
            observed_state=dict(observed.state),
            state_sources=_sources(observed.source),
            quality_reason=_quality_reason(quality, uncertainty),
            envelope_report=winner.envelope,
            objective=final,
        )

    def _observed(
        self,
        observed_state: Mapping[str, float] | None,
        history: pd.DataFrame | None,
        baseline_state: dict[str, float] | None,
    ) -> "_ObservedPoint":
        """The measured current point, and an honest label for where it came from.

        Order of preference: what the caller measured, then the last historian row, then - only
        because the rule engine needs *something* to compare - the twin's own settled state, which
        is labelled ``twin_simulation`` rather than passed off as a sensor reading.
        """
        if observed_state:
            return _ObservedPoint(_floats(observed_state), SOURCE_MEASURED)
        if history is not None and not history.empty:
            row = history.iloc[-1]
            return _ObservedPoint(
                {
                    str(tag): float(value)
                    for tag, value in row.items()
                    if isinstance(value, (int, float, np.floating, np.integer))
                    and float(value) == float(value)
                },
                SOURCE_MEASURED,
            )
        return _ObservedPoint(dict(baseline_state or {}), SOURCE_TWIN_SIMULATION)

    def _rule_state(
        self,
        rules: RuleReport,
        base_inputs: Mapping[str, float],
        baseline: CandidateOutcome,
        mode: str,
    ) -> tuple[dict[str, float] | None, int]:
        """Settle the rule engine's suggestion for the PRD 14.5 "Digital Twin Baseline" row.

        A hold costs nothing - it is the baseline candidate, already settled - so the extra solves
        are only paid when the rules actually propose a different operating point.
        """
        if rules.is_hold:
            return baseline.state, 0
        inputs = {**base_inputs, **self._space.to_twin_inputs(rules.proposed_setpoints)}
        state, _settled, _drift, solves = self._settle(inputs)
        return state, solves

    def describe(self) -> dict[str, Any]:
        """NFR-11 / PRD 35 record of the whole optimizer: variables, gates, search, limits."""
        return {
            "prd_section": "14.1 Model C",
            "model_version": self.model_version,
            "gates": list(GATE_NAMES),
            "search": {
                **self._search,
                "steady_state_max_minutes": self._max_minutes,
                "convergence_verification_tolerance_relative": self._tolerance,
                "score_epsilon": SCORE_EPSILON,
                "detail": (
                    "fixed coordinate grid over search.delta_grid_fractions, then a "
                    "random_state-seeded sample, then - only if search.polish.enabled - a seeded "
                    "differential_evolution refinement whose every proposal is snapped onto the "
                    "same step grid and put through the same PRD 14.3 gate; ties keep the earlier "
                    "candidate"
                ),
            },
            "optimizable_datasets": list(self._optimizable_datasets()),
            "uncertainty_limit_pct": uncertainty_limit_pct(self._ml),
            "uncertainty_gate_targets": list(objective_targets(self._ml)),
            "uncertainty_gate_detail": (
                "the ceiling blocks on uncertainty.optimizer_targets (the objective's own "
                "targets); the worst spread over all consulted targets is reported and caps the "
                "Recommendation Quality - see the module docstring ASSUMPTION"
            ),
            "impact_metrics": list(self._metrics),
            "decision_space": self._space.describe(),
            "hard_constraints": self._constraints.describe(),
            "objective": self._objective.describe(),
            "envelope": self._validator.describe(),
            "rule_engine": self._rules.describe(),
            "baselines": self._baselines.describe(),
            "limitation": (
                "Synthetic demonstration. Every number here is produced by the synthetic twin and "
                "models trained on synthetic data; none of it is a validated plant recommendation."
            ),
        }


@dataclass(frozen=True, slots=True)
class _ObservedPoint:
    """The measured current point plus which of the four kinds of number it actually is."""

    state: dict[str, float]
    source: str


def _sources(observed_source: str) -> dict[str, str]:
    """Per-field provenance for the recommendation - the strict-distinction requirement, recorded.

    ``simulator_ground_truth`` never appears: the optimizer reads published tags only, so there is
    no field it could label with it.
    """
    return {
        "observed_state": observed_source,
        "baseline_state": SOURCE_TWIN_SIMULATION,
        "proposed_state": SOURCE_TWIN_SIMULATION,
        "predicted_state_by_horizon": SOURCE_MODEL_A,
        "expected_impact": SOURCE_TWIN_SIMULATION,
        "baseline_setpoints": SOURCE_MEASURED,
        "proposed_setpoints": SOURCE_OPTIMIZER,
        "objective_breakdown": SOURCE_OPTIMIZER,
        "delta_fractions": SOURCE_OPTIMIZER,
    }


def _quality_reason(quality: Any, uncertainty: "_Uncertainty | None" = None) -> str:
    """The categorical verdict spelled out with the factor that limited it - never a percentage."""
    parts = [quality.description]
    if quality.limiting_factor:
        parts.append(f"limited by {quality.limiting_factor}")
    if quality.unassessed:
        parts.append(
            f"capped because {list(quality.unassessed)} could not be assessed"
            if quality.capped_by_unassessed
            else f"unassessed factors: {list(quality.unassessed)}"
        )
    if uncertainty is not None and uncertainty.wide:
        widest = "; ".join(
            f"{target} t+{horizon}min {pct:.1f} %" for target, horizon, pct in uncertainty.wide
        )
        parts.append(
            f"reported-only predictions above the {uncertainty.limit_pct:.2f} % spread ceiling "
            f"({widest}) - shown, not hidden, and not claimed as an improvement"
        )
    return "; ".join(parts)


def _accepted_message(recommendation: Recommendation) -> str:
    """One line for the caller: what is proposed, gated how, and on what evidence."""
    action = "hold the current setpoints" if recommendation.is_hold else "; ".join(
        f"{name} {recommendation.delta_fractions[name] * 100:+.2f} %"
        for name in recommendation.moved()
    )
    return (
        f"{recommendation.label}: {action} "
        f"({recommendation.constraint_status} / {recommendation.envelope_status}, "
        f"quality {recommendation.recommendation_quality})"
    )


def _moved(proposal: Mapping[str, float], baseline: Mapping[str, float]) -> tuple[str, ...]:
    """Which variables a proposal actually changes, in the proposal's (config) order."""
    return tuple(
        name
        for name, value in proposal.items()
        if float(value) != float(baseline[name])
    )


def _key(setpoints: Mapping[str, float]) -> tuple[tuple[str, float], ...]:
    """Deduplication key: rounded so two float paths to the same setpoint are one candidate."""
    return tuple(sorted((str(name), round(float(value), 9)) for name, value in setpoints.items()))


def _better(candidate: CandidateOutcome, incumbent: CandidateOutcome) -> bool:
    """Strictly better by more than :data:`SCORE_EPSILON`. Ties keep the incumbent, so generation
    order decides - and generation order is fixed."""
    if candidate.score is None or not candidate.accepted:
        return False
    if incumbent.score is None or not incumbent.accepted:
        return True
    return candidate.score < incumbent.score - SCORE_EPSILON


def _pick(candidates: Sequence[CandidateOutcome]) -> CandidateOutcome | None:
    """Lowest-scoring accepted candidate, earliest wins on a tie."""
    best: CandidateOutcome | None = None
    for candidate in candidates:
        if not candidate.accepted:
            continue
        if best is None or _better(candidate, best):
            best = candidate
    return best


def _as_reports(anomaly: Any) -> tuple[Any, ...]:
    """One Model B report, a sequence of them, or a dataset-keyed mapping - all accepted."""
    if anomaly is None:
        return ()
    if isinstance(anomaly, Mapping):
        return tuple(anomaly.values())
    if isinstance(anomaly, (list, tuple, set, frozenset)):
        return tuple(anomaly)
    return (anomaly,)


def _timestamp_of(history: pd.DataFrame | None, timestamp: Any) -> Any:
    """The timestamp of the observation, never a wall clock - see the module docstring."""
    if history is not None and not history.empty:
        return history.index[-1]
    return timestamp


def _previous_row(history: pd.DataFrame | None) -> dict[str, float] | None:
    """The row before last, for the one rate-of-change rule. Backwards only, never forwards."""
    if history is None or len(history) < 2:
        return None
    row = history.iloc[-2]
    return {
        str(tag): float(value)
        for tag, value in row.items()
        if isinstance(value, (int, float, np.floating, np.integer))
        and float(value) == float(value)
    }


def _floats(values: Mapping[str, Any]) -> dict[str, float]:
    payload: dict[str, float] = {}
    for tag, value in values.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            payload[str(tag)] = number
    return payload


__all__ = [
    "GATE_ANOMALY",
    "GATE_ENVELOPE",
    "GATE_MODEL_AVAILABILITY",
    "GATE_NAMES",
    "GATE_UNCERTAINTY",
    "ORIGIN_GRID",
    "ORIGIN_HOLD",
    "ORIGIN_POLISH",
    "ORIGIN_RANDOM",
    "ORIGIN_WHAT_IF",
    "SCORE_EPSILON",
    "CandidateOutcome",
    "GateOutcome",
    "OptimizationResult",
    "Optimizer",
    "SetpointAssessment",
]
