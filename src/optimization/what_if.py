"""The PRD v1.1.1 Section 16 what-if engine - the manual counterpart of Model C.

PRD 16.2 fixes the flow and this module runs it in that order::

    User sets D on 1..N variables, selects Normal or Experimental mode
      -> build input_trajectory (ramped, matching Scenario Scheduler ramp logic)
      -> [Normal Mode only] Operating-Envelope / OOD Validation (Section 14.3)
      -> Twin.simulate_scenario(input_trajectory, dt)   # the same call optimization uses
      -> compare final steady-state vs baseline
      -> render ... the full transition trajectory showing the actual dead-time + lag

Three design consequences are worth stating plainly, because each is a requirement rather than a
preference.

*The verdict, the numbers and the recommendation object are not re-derived here.* PRD 16.2 closes
with a guarantee - "results are guaranteed consistent between AI Recommendation and manual
what-if - this consistency is itself a testable acceptance criterion". The only way to make that
guarantee structural rather than aspirational is to have one implementation, so this module owns no
gate, no constraint check, no objective and no impact arithmetic. It calls
:meth:`~src.optimization.optimizer.Optimizer.assess_setpoints`, which is the same
``_evaluate`` -> ``EnvelopeValidator`` -> ``SoftObjective`` -> ``_predict`` -> ``_recommend`` chain
the optimizer's own winning candidate travels. Feeding a :class:`Recommendation`'s
``proposed_setpoints`` back in through :meth:`WhatIfEngine.run` therefore reproduces it exactly,
tag for tag - asserted, not asserted-to.

*The trajectory is a second, independent computation, and the disagreement is reported.* The
before/after table and every impact figure come from ``to_steady_state`` (the optimizer's route);
the transition chart comes from ``simulate_scenario`` over the ramped trajectory (PRD 16.2's
route). They are two different numerical paths to the same physical endpoint, so
:attr:`WhatIfResult.endpoint_agreement` measures how far apart they landed and
:attr:`WhatIfResult.endpoint_converged` says whether that is inside
``configs/optimization.yaml what_if.endpoint_tolerance_relative``. Reporting the residual is the
honest option; quietly using whichever number looks better would not be.

*A rejected what-if is an answer, not an error.* PRD 16.1 says a Normal-mode request that would
leave the calibrated range "is rejected with an explanation, exactly as the optimizer would reject
it", and PRD 16.3 wants that verdict rendered in a ``Recommendation``-shaped object. So every
request returns a :class:`WhatIfResult` carrying a full recommendation object whose
``constraint_status`` may be ``REJECTED`` - and a rejected request is never simulated, so there is
no trajectory to mistake for a prediction of what would have happened.

The Experimental-mode banner is not this module's decision either: it is
:attr:`~src.optimization.envelope.EnvelopeReport.banner`, which returns
:data:`src.labels.OUTSIDE_ENVELOPE_BANNER` whenever the envelope status is ``OUTSIDE_ENVELOPE`` and
cannot be suppressed by a caller.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

import pandas as pd

from src.config import OPTIMIZATION, Config, ConfigError, load_config
from src.optimization.envelope import CHECK_FEATURE_SPACE
from src.optimization.optimizer import CandidateOutcome, Optimizer, SetpointAssessment
from src.optimization.recommendation import MetricDelta, Recommendation
from src.optimization.variables import DecisionSpace

# The ramp is the Scenario Scheduler's, not a second implementation of it. PRD 16.2 requires the
# what-if trajectory to be "ramped, matching Scenario Scheduler ramp logic", and the scheduler's
# own docstrings note that a duplicated table is how two tables drift apart - so the private class
# is imported rather than restated. It has no state beyond one setpoint's ramp clock.
from src.simulation.scheduler import _RampedSetpoint

#: A request that moves nothing is still a legal request (it answers "what if we hold?"), so the
#: hold is labelled rather than rejected.
HOLD_REQUEST = "hold the current setpoints"

#: Seconds per minute - written once so a trajectory index and a ramp clock cannot disagree.
_SECONDS_PER_MINUTE = 60.0


@dataclass(frozen=True, slots=True)
class VariableRequest:
    """One slider move: where the variable was, where the user put it, and what that cost.

    ``requested`` is what the caller asked for and ``value`` is what the engine will actually
    simulate - they differ only when the request was snapped to the variable's documented step
    (PRD 17 sliders) or clipped to the mode's bound. Both are kept because "your 12 % request was
    simulated as 10 %" is information the panel has to be able to show; silently simulating
    something other than what was asked is exactly what PRD 30 calls hiding a clip.
    """

    name: str
    unit: str
    baseline: float
    requested: float
    value: float
    delta_fraction: float
    bounds: tuple[float, float]
    step: float
    clipped: bool
    snapped: bool

    @property
    def moved(self) -> bool:
        return self.value != self.baseline

    def note(self) -> str | None:
        """The one-line explanation of any difference between request and simulation."""
        if self.clipped and self.snapped:
            return (
                f"{self.name}: requested {self.requested:.4g} {self.unit}, clipped to the "
                f"[{self.bounds[0]:.4g}, {self.bounds[1]:.4g}] mode bound and snapped to the "
                f"{self.step:.4g} {self.unit} step -> {self.value:.4g}"
            )
        if self.clipped:
            return (
                f"{self.name}: requested {self.requested:.4g} {self.unit}, clipped to the "
                f"[{self.bounds[0]:.4g}, {self.bounds[1]:.4g}] mode bound -> {self.value:.4g}"
            )
        if self.snapped:
            return (
                f"{self.name}: requested {self.requested:.4g} {self.unit}, snapped to the "
                f"{self.step:.4g} {self.unit} slider step -> {self.value:.4g}"
            )
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "baseline": self.baseline,
            "requested": self.requested,
            "value": self.value,
            "delta": self.value - self.baseline,
            "delta_pct": self.delta_fraction * 100.0,
            "bounds": list(self.bounds),
            "step": self.step,
            "clipped": self.clipped,
            "snapped": self.snapped,
            "moved": self.moved,
            "note": self.note(),
        }


@dataclass(frozen=True, slots=True)
class Transition:
    """The PRD 16.2 trajectory: what the setpoints did, and what the plant did about it.

    ``frame`` is one row per simulated minute over the whole window - the ``hold_minutes`` the
    plant spends at the baseline, the ramp, and the settling that follows. ``setpoints`` is the
    commanded trajectory on the same index, so a chart can draw "what we asked" against "what
    happened" and the gap between them *is* the dead time plus lag.
    """

    frame: pd.DataFrame
    setpoints: pd.DataFrame
    dt_seconds: float
    hold_minutes: float
    ramp_minutes: dict[str, float]
    endpoint: dict[str, float]

    @property
    def minutes(self) -> float:
        return float(len(self.frame)) * self.dt_seconds / _SECONDS_PER_MINUTE

    def response_delay_minutes(self, tag: str, *, fraction: float = 0.5) -> float | None:
        """Minutes from the start of the setpoint move until ``tag`` has travelled ``fraction``.

        This is the number that makes "NOT an instantaneous jump" measurable rather than visual:
        for an instantaneous response it would equal the ramp time, and for a delayed one it is
        strictly larger. ``None`` when the tag never moves (nothing to time) or is absent.
        """
        if tag not in self.frame.columns:
            return None
        series = self.frame[tag].astype(float)
        start = float(series.iloc[0])
        final = float(self.endpoint.get(tag, series.iloc[-1]))
        travel = final - start
        if not math.isfinite(travel) or abs(travel) <= 0.0:
            return None
        target = start + fraction * travel
        moved = series >= target if travel > 0.0 else series <= target
        hits = [position for position, flag in enumerate(moved.to_numpy()) if flag]
        if not hits:
            return None
        minutes = hits[0] * self.dt_seconds / _SECONDS_PER_MINUTE
        return max(0.0, minutes - self.hold_minutes)

    def describe(self) -> dict[str, Any]:
        return {
            "rows": int(len(self.frame)),
            "minutes": self.minutes,
            "dt_seconds": self.dt_seconds,
            "hold_minutes": self.hold_minutes,
            "ramp_minutes": dict(self.ramp_minutes),
            "tags": list(self.frame.columns),
            "commanded_variables": list(self.setpoints.columns),
        }


@dataclass(frozen=True, slots=True)
class WhatIfResult:
    """One answered what-if question - PRD 16.3's output panel, as data.

    Nothing in here is computed by this module except the trajectory and the agreement between the
    trajectory's endpoint and the settled state: :attr:`assessment` carries the verdict, the score,
    the prediction and the recommendation, all produced by the optimizer's own chain.
    """

    mode: str
    request: tuple[VariableRequest, ...]
    assessment: SetpointAssessment
    transition: Transition | None
    endpoint_agreement: float | None
    endpoint_tolerance: float

    # -- the four statuses PRD 16.3 wants on the banner ----------------------------------
    @property
    def recommendation(self) -> Recommendation:
        return self.assessment.recommendation

    @property
    def constraint_status(self) -> str:
        return self.assessment.candidate.constraint_status

    @property
    def envelope_status(self) -> str:
        return self.assessment.candidate.envelope_status

    @property
    def ood_status(self) -> str:
        """PRD 14.3 check 2's own verdict, kept separate from the aggregate envelope status."""
        return self.assessment.candidate.envelope.check(CHECK_FEATURE_SPACE).state

    @property
    def banner(self) -> str | None:
        """:data:`src.labels.OUTSIDE_ENVELOPE_BANNER` when outside - never suppressible."""
        return self.assessment.candidate.envelope.banner

    @property
    def accepted(self) -> bool:
        return self.assessment.accepted

    @property
    def simulated(self) -> bool:
        """False for a request rejected before any solve - there is then nothing to plot."""
        return self.transition is not None

    @property
    def endpoint_converged(self) -> bool | None:
        """Whether the two numerical routes to the same endpoint agree, or ``None`` if unmeasured."""
        if self.endpoint_agreement is None:
            return None
        return self.endpoint_agreement <= self.endpoint_tolerance

    def moved(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.request if item.moved)

    def action(self) -> str:
        moves = [item for item in self.request if item.moved]
        if not moves:
            return HOLD_REQUEST
        return "; ".join(
            f"{item.name} {item.baseline:.4g} -> {item.value:.4g} {item.unit} "
            f"({item.delta_fraction * 100:+.2f} %)"
            for item in moves
        )

    def notes(self) -> tuple[str, ...]:
        """Everything the engine changed about the request, plus any prediction shortfall."""
        notes = [note for note in (item.note() for item in self.request) if note]
        notes.extend(self.assessment.prediction_notes)
        if self.endpoint_converged is False and self.endpoint_agreement is not None:
            notes.append(
                f"the ramped trajectory's last row differs from the settled state by "
                f"{self.endpoint_agreement:.3g} relative, above the "
                f"{self.endpoint_tolerance:.3g} what_if.endpoint_tolerance_relative: the window is "
                f"too short for this move to have finished settling, so read the transition chart "
                f"as still in motion. Every reported number is the settled state, not this row."
            )
        return tuple(notes)

    # -- the PRD 16.3 panel -----------------------------------------------------------------
    def before_after(self) -> tuple[MetricDelta, ...]:
        """The before/after table: the same metric set as every PRD 14.5 baseline row."""
        return self.recommendation.expected_impact.metrics

    def constraint_rows(self) -> tuple[dict[str, Any], ...]:
        """Per-constraint PASS/FAIL, so the banner can be per constraint and not just overall."""
        report = self.assessment.candidate.envelope.constraint_report
        if report is None:
            return ()
        return tuple(item.describe() for item in report.outcomes)

    def envelope_rows(self) -> tuple[dict[str, Any], ...]:
        """Per-envelope-check state - PRD 16.3's "per envelope check" half of the banner."""
        return tuple(check.describe() for check in self.assessment.candidate.envelope.checks)

    def savings_line(self) -> str:
        """PRD 16.3's estimated savings/cost line, carrying its caveat rather than implying one."""
        impact = self.recommendation.expected_impact
        thermal = impact.thermal_energy_kcal_per_day
        electric = impact.electrical_energy_kwh_per_day
        if thermal is None and electric is None:
            return f"No energy impact could be estimated for this scenario. {impact.caveat}"
        pieces = []
        if thermal is not None:
            pieces.append(f"thermal {thermal:+,.0f} kcal/day")
        if electric is not None:
            pieces.append(f"electrical {electric:+,.0f} kWh/day")
        return f"Estimated change at the settled rate: {', '.join(pieces)}. {impact.caveat}"

    def panel(self) -> dict[str, Any]:
        """PRD 16.3's panel contract, with every required element under its own key.

        The ten elements a what-if result has to show are keyed here by what they are rather than
        by where they came from, so the contract can be checked against this dict directly: nothing
        required is folded into something else, and nothing shown is computed twice.
        """
        recommendation = self.recommendation
        impact = recommendation.expected_impact
        return {
            "mode": self.mode,
            "action": self.action(),
            "requested_change": [item.describe() for item in self.request],
            "baseline_state": dict(recommendation.baseline_state),
            "baseline_setpoints": dict(recommendation.baseline_setpoints),
            "observed_state": dict(recommendation.observed_state),
            "state_sources": dict(recommendation.state_sources),
            "predicted_process_response": {
                "settled_state": dict(recommendation.proposed_state),
                "by_horizon": recommendation.predicted_state_by_horizon,
                "transition": None if self.transition is None else self.transition.describe(),
                "endpoint_agreement_relative": self.endpoint_agreement,
                "endpoint_converged": self.endpoint_converged,
            },
            "before_after": [item.describe() for item in self.before_after()],
            "energy_impact": {
                "thermal_energy_kcal_per_day": impact.thermal_energy_kcal_per_day,
                "electrical_energy_kwh_per_day": impact.electrical_energy_kwh_per_day,
                "metrics": [item.describe() for item in impact.energy],
                "savings_line": self.savings_line(),
                "caveat": impact.caveat,
            },
            "production_impact": [
                item.describe()
                for item in self.before_after()
                if item.tag in ("clinker_production_tph", "cement_production_tph")
            ],
            "quality_impact": [
                item.describe()
                for item in self.before_after()
                if item.tag in ("simulated_blaine_cm2_g", "residue_percent")
            ],
            "uncertainty": {
                "relative_uncertainty_pct": impact.relative_uncertainty_pct,
                "predicted_variability_pct": impact.predicted_variability_pct,
                "limit_pct": self.assessment.uncertainty.limit_pct,
                "gate_targets": list(self.assessment.uncertainty.targets),
                "gate_spread_pct": self.assessment.uncertainty.claim_pct,
                "wide_predictions": [
                    {"target": target, "horizon_min": horizon, "relative_spread_pct": pct}
                    for target, horizon, pct in self.assessment.uncertainty.wide
                ],
            },
            "constraint_status": self.constraint_status,
            "constraint_rows": list(self.constraint_rows()),
            "envelope_status": self.envelope_status,
            "ood_status": self.ood_status,
            "envelope_rows": list(self.envelope_rows()),
            "recommendation_status": {
                "accepted": self.accepted,
                "simulated": self.simulated,
                "blocked_by": list(self.assessment.blocked_by),
                "recommendation_quality": recommendation.recommendation_quality,
                "quality_reason": recommendation.quality_reason,
                "explanation": recommendation.explanation(),
                "label": recommendation.label,
            },
            "banner": self.banner,
            "notes": list(self.notes()),
        }

    def describe(self) -> dict[str, Any]:
        payload = self.panel()
        payload["assessment"] = self.assessment.describe()
        return payload

    #: Paths into :meth:`describe` of the fields that count *work done* rather than results.
    #: Both are the same counter seen at two depths - the assessment's total and the candidate's
    #: own - and both have to go, or a warm memo makes an identical request look like a different
    #: answer (this is exactly what
    #: ``tests/test_optimization.py::TestReproducibility::test_a_repeated_what_if_is_bit_identical``
    #: caught).
    NON_REPRODUCIBLE_FIELDS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("assessment", "unit_solves"),
        ("assessment", "candidate", "unit_solves"),
    )

    def signature(self) -> dict[str, Any]:
        """:meth:`describe` minus the solve counter - what "reproducible" means for a what-if.

        Two identical requests against the same operating point, models and history produce an
        identical signature, field for field. The excluded field is the *cost* of the answer, not
        the answer: unlike :meth:`~src.optimization.optimizer.Optimizer.optimize`, which resets its
        memo per run and so reports a reproducible solve count, a what-if deliberately keeps the
        memo warm across requests so a caller dragging a slider pays for each distinct point once -
        which means the second identical request costs fewer solves and returns the same result.
        """
        payload = self.describe()
        for path in self.NON_REPRODUCIBLE_FIELDS:
            target = payload
            for key in path[:-1]:
                target = target.get(key)  # type: ignore[assignment]
                if not isinstance(target, dict):
                    break
            else:
                target.pop(path[-1], None)
        return payload


class WhatIfEngine:
    """PRD 16's engine. Owns the request geometry and the trajectory - nothing else.

    Every verdict and every number in a :class:`WhatIfResult` other than the transition frame comes
    from the :class:`~src.optimization.optimizer.Optimizer` this engine wraps, which is what makes
    PRD 16.2's AI-Recommendation/manual-what-if consistency a property of the code rather than a
    thing to be tested for and hoped about.
    """

    __slots__ = ("_config", "_dt", "_hold", "_optimizer", "_tolerance", "_window")

    def __init__(self, optimizer: Optimizer, *, config: Config | None = None) -> None:
        self._optimizer = optimizer
        self._config = config if config is not None else load_config(OPTIMIZATION)
        block = self._config.get_path("what_if")
        self._dt = float(block.get_path("dt_seconds"))
        self._hold = float(block.get_path("hold_minutes"))
        self._window = float(block.get_path("trajectory_minutes"))
        self._tolerance = float(block.get_path("endpoint_tolerance_relative"))
        if self._dt <= 0.0:
            raise ConfigError(f"what_if.dt_seconds must be > 0, got {self._dt!r}")
        if self._hold < 0.0 or self._window <= 0.0:
            raise ConfigError(
                "what_if.hold_minutes must be >= 0 and what_if.trajectory_minutes > 0, got "
                f"{self._hold!r} and {self._window!r}"
            )

    @classmethod
    def from_twin(cls, twin: Any, **kwargs: Any) -> "WhatIfEngine":
        """Build the whole Model C stack and wrap it - arguments pass to ``Optimizer.from_twin``."""
        optimizer = Optimizer.from_twin(twin, **kwargs)
        return cls(optimizer, config=kwargs.get("config"))

    # -- access -----------------------------------------------------------------------------
    @property
    def optimizer(self) -> Optimizer:
        return self._optimizer

    @property
    def space(self) -> DecisionSpace:
        return self._optimizer.space

    def variables(self) -> tuple[str, ...]:
        """The PRD 16.1 manipulated variables, in config order - what a panel draws sliders for."""
        return self.space.names

    def slider(self, name: str, current: float, mode: str = "NORMAL") -> dict[str, Any]:
        """Everything a PRD 17 slider needs for one variable at one operating point."""
        variable = self.space[name]
        low, high = self.space.bounds(name, float(current), mode)
        return {
            "name": name,
            "unit": variable.unit,
            "current": float(current),
            "minimum": low,
            "maximum": high,
            "absolute_range": [variable.minimum, variable.maximum],
            "step": variable.step_at(float(current)),
            "max_delta_fraction": self.space.max_delta_fraction(mode),
            "mode": str(mode).upper(),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "dt_seconds": self._dt,
            "hold_minutes": self._hold,
            "trajectory_minutes": self._window,
            "endpoint_tolerance_relative": self._tolerance,
            "variables": [self.space[name].describe() for name in self.variables()],
            "modes": self.space.describe()["modes"],
            "reuses": (
                "Optimizer.assess_setpoints - the same _evaluate / EnvelopeValidator / "
                "SoftObjective / _predict / _recommend chain the optimizer's winner travels"
            ),
        }

    # -- the PRD 16.2 flow ------------------------------------------------------------------
    def run(
        self,
        *,
        inputs: Mapping[str, float],
        changes: Mapping[str, float] | None = None,
        delta_fractions: Mapping[str, float] | None = None,
        observed_state: Mapping[str, float] | None = None,
        history: pd.DataFrame | None = None,
        mode: str = "NORMAL",
        anomaly: Any = None,
        weights: Mapping[str, float] | None = None,
        timestamp: Any = None,
        baseline: CandidateOutcome | None = None,
        clip_to_bounds: bool = False,
        simulate_transition: bool = True,
    ) -> WhatIfResult:
        """Answer one what-if question, following PRD 16.2 step for step.

        The move may be given either way round: ``changes`` names absolute target values and
        ``delta_fractions`` names signed fractions of the current value (``-0.05`` for -5 %). A
        variable may appear in one or the other, never both.

        ``clip_to_bounds`` defaults to **False**, and that is the faithful default rather than the
        convenient one. A UI slider cannot physically leave its mode bound, so clipping would never
        fire for the caller PRD 17 describes; a *typed* or programmatic request that does leave it
        must be "rejected with an explanation, exactly as the optimizer would reject it" (PRD 16.1),
        which is what PRD 14.2's check 4 does when the oversized request is passed through intact.
        Clipping instead would quietly convert a 40 % question into a 10 % answer and make check 4
        unreachable from this path. Set it True for a slider-shaped caller; the clip is then always
        reported in :meth:`WhatIfResult.notes` and in ``requested`` beside ``value``.
        """
        mode = str(mode).upper()
        base_inputs = {str(key): float(value) for key, value in inputs.items()}
        baseline_setpoints = self.space.baseline(base_inputs)
        request = self._requests(
            baseline_setpoints=baseline_setpoints,
            changes=changes,
            delta_fractions=delta_fractions,
            mode=mode,
            clip_to_bounds=clip_to_bounds,
        )
        proposed = {item.name: item.value for item in request}
        assessment = self._optimizer.assess_setpoints(
            proposed=proposed,
            inputs=base_inputs,
            observed_state=observed_state,
            history=history,
            mode=mode,
            anomaly=anomaly,
            weights=weights,
            timestamp=timestamp,
            baseline=baseline,
        )
        transition: Transition | None = None
        agreement: float | None = None
        if simulate_transition and assessment.candidate.state is not None:
            transition = self._simulate(
                base_inputs=base_inputs,
                baseline_setpoints=baseline_setpoints,
                proposed=proposed,
                endpoint=assessment.candidate.state,
            )
            agreement = _worst_relative_gap(transition.frame.iloc[-1], assessment.candidate.state)
        return WhatIfResult(
            mode=mode,
            request=request,
            assessment=assessment,
            transition=transition,
            endpoint_agreement=agreement,
            endpoint_tolerance=self._tolerance,
        )

    def replay(
        self,
        recommendation: Recommendation,
        *,
        inputs: Mapping[str, float],
        history: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> WhatIfResult:
        """Re-ask a :class:`Recommendation` as a manual what-if - PRD 16.2's consistency check.

        The recommendation's own ``proposed_setpoints`` and ``mode`` go back in, so the result must
        reproduce it: same settled state, same verdict, same impact. This is the AC-8 acceptance
        criterion expressed as a method rather than only as a test, because the demo notebook has to
        be able to show it.
        """
        kwargs.setdefault("mode", recommendation.mode)
        return self.run(
            inputs=inputs,
            changes=dict(recommendation.proposed_setpoints),
            history=history,
            **kwargs,
        )

    # -- request geometry -------------------------------------------------------------------
    def _requests(
        self,
        *,
        baseline_setpoints: Mapping[str, float],
        changes: Mapping[str, float] | None,
        delta_fractions: Mapping[str, float] | None,
        mode: str,
        clip_to_bounds: bool,
    ) -> tuple[VariableRequest, ...]:
        """Turn a slider request into snapped, bounded, fully-explained variable values."""
        wanted: dict[str, float] = {}
        for name, value in (changes or {}).items():
            key = self._checked(name)
            wanted[key] = float(value)
        for name, fraction in (delta_fractions or {}).items():
            key = self._checked(name)
            if key in wanted:
                raise ValueError(
                    f"{key!r} was given both an absolute target and a delta fraction; a what-if "
                    "request must say which one it means"
                )
            wanted[key] = float(baseline_setpoints[key]) * (1.0 + float(fraction))
        requests: list[VariableRequest] = []
        for name in self.space.names:  # config order, so two identical requests are identical
            current = float(baseline_setpoints[name])
            variable = self.space[name]
            low, high = self.space.bounds(name, current, mode)
            requested = wanted.get(name, current)
            # Snapped onto the step grid but deliberately NOT clipped to the variable's absolute
            # range: PRD 16.1 wants an out-of-range request rejected by check 1 with an
            # explanation, and `DecisionVariable.snap` would quietly pull it to the range edge
            # first. `clip_to_bounds` is the slider-shaped caller's opt-in to that clip, and it
            # then clips to the *mode* bound (which is the absolute range intersected with the
            # mode's change limit), never past it.
            snapped = variable.snap_to_step(requested, current)
            value = min(max(snapped, low), high) if clip_to_bounds else snapped
            requests.append(
                VariableRequest(
                    name=name,
                    unit=variable.unit,
                    baseline=current,
                    requested=requested,
                    value=value,
                    delta_fraction=variable.delta_fraction(value, current),
                    bounds=(low, high),
                    step=variable.step_at(current),
                    clipped=value != snapped,
                    snapped=snapped != requested,
                )
            )
        return tuple(requests)

    def _checked(self, name: str) -> str:
        key = str(name)
        if key not in self.space:
            raise KeyError(
                f"{key!r} is not a PRD 16.1 manipulated variable; the what-if engine may only move "
                f"{list(self.space.names)}"
            )
        return key

    # -- the trajectory (PRD 16.2's "NOT an instantaneous jump") ----------------------------
    def _simulate(
        self,
        *,
        base_inputs: Mapping[str, float],
        baseline_setpoints: Mapping[str, float],
        proposed: Mapping[str, float],
        endpoint: Mapping[str, float],
    ) -> Transition:
        """Settle at the baseline, then roll the ramped request forward through the real delays.

        The starting point is the *settled* baseline rather than whatever state the twin happens to
        be in, so the flat opening stretch of the chart is a genuine steady state and the deflection
        that follows is attributable to the move alone. ``simulate_scenario`` is PRD 8.4's own call,
        which routes every relationship through its configured ``DelayedResponse`` - the dead time
        and the lag come from the physics layer, not from anything here.
        """
        twin = self._optimizer.twin
        commanded, ramps = self._trajectory(base_inputs, baseline_setpoints, proposed)
        twin.reset()
        twin.to_steady_state(
            {**base_inputs, **self.space.to_twin_inputs(baseline_setpoints)},
            self._optimizer.max_minutes,
        )
        frame = twin.simulate_scenario(commanded, self._dt)
        return Transition(
            frame=frame,
            setpoints=pd.DataFrame(
                {
                    name: commanded[self.space[name].twin_input].to_numpy()
                    for name in self.space.names
                },
                index=commanded.index,
            ),
            dt_seconds=self._dt,
            hold_minutes=self._hold,
            ramp_minutes=ramps,
            endpoint={str(tag): float(value) for tag, value in endpoint.items()},
        )

    def _trajectory(
        self,
        base_inputs: Mapping[str, float],
        baseline_setpoints: Mapping[str, float],
        proposed: Mapping[str, float],
    ) -> tuple[pd.DataFrame, dict[str, float]]:
        """The commanded input trajectory: ``hold_minutes`` at baseline, then each variable's ramp."""
        step_minutes = self._dt / _SECONDS_PER_MINUTE
        hold_steps = int(round(self._hold / step_minutes))
        total_steps = hold_steps + int(round(self._window / step_minutes))
        ramps = {
            variable.name: _RampedSetpoint(
                float(baseline_setpoints[variable.name]), variable.ramp_minutes
            )
            for variable in self.space
        }
        rows: list[dict[str, float]] = []
        for step in range(total_steps):
            targets = baseline_setpoints if step < hold_steps else proposed
            row = dict(base_inputs)
            for variable in self.space:
                row[variable.twin_input] = ramps[variable.name].step(
                    float(targets[variable.name]), step_minutes
                )
            rows.append(row)
        index = pd.Index(
            [step * step_minutes for step in range(total_steps)], name="minutes_from_request"
        )
        return pd.DataFrame(rows, index=index), {
            variable.name: variable.ramp_minutes for variable in self.space
        }


def _worst_relative_gap(row: "pd.Series", settled: Mapping[str, float]) -> float | None:
    """Worst relative distance between the trajectory's last row and the settled state.

    Normalized the same way :meth:`Optimizer._settle` verifies convergence - by ``max(1, |value|)``,
    so a tag that sits near zero cannot manufacture a large relative gap out of a small absolute
    one. ``None`` when the two share no comparable tag.
    """
    worst: float | None = None
    for tag, value in settled.items():
        if tag not in row.index:
            continue
        try:
            observed = float(row[tag])
        except (TypeError, ValueError):  # pragma: no cover - numeric frame
            continue
        target = float(value)
        if not (math.isfinite(observed) and math.isfinite(target)):
            continue
        gap = abs(observed - target) / max(1.0, abs(target))
        worst = gap if worst is None else max(worst, gap)
    return worst


__all__ = [
    "HOLD_REQUEST",
    "Transition",
    "VariableRequest",
    "WhatIfEngine",
    "WhatIfResult",
]






