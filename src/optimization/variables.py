"""Decision variables of PRD v1.1.1 Section 16.1 - the only quantities Model C may move.

Three separate vocabularies meet in this module and keeping them apart is load-bearing:

``name``
    the PRD 12 dataset **tag** and the ``configs/optimization.yaml`` key - ``ID_fan_speed``.
    This is what a UI slider, a what-if request and a ``Recommendation`` all speak.
``twin_input``
    the twin's **input key** - ``ID_fan_speed_pct``. :meth:`UnitBase.input_value` returns the
    *first present* alias and the twins pre-seed the ``_pct``/``_C`` spellings, so a trajectory
    written in tag spelling would be silently held rather than fail loudly. The mapping is not
    re-derived here: it is :class:`src.simulation.scheduler.SetpointSpec`, the same table the
    Scenario Scheduler drives the synthetic run with (PRD 16.2 requires the what-if ramp to
    match the scheduler's, and two copies of an alias table is exactly how they drift apart).
``ratio_of_reference``
    two of PRD 16.1's variables are bounded relative to a solved reference operating point
    rather than absolutely, because the kiln fuel rate is an *output* of the PRD 9.3 energy
    balance and its absolute value moves with the fuel's calorific value.

NFR-11 requires every decision variable to carry a documented range, step size, hard
constraint and rationale; :meth:`DecisionSpace.describe` is what the Section 35 review
checklist reads, so nothing here may be implicit.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from src.config import OPTIMIZATION, SCENARIOS, Config, ConfigError, load_config
from src.labels import OPTIMIZATION_MODE_VALUES
from src.simulation.scheduler import SETPOINTS, SetpointSpec

#: ``SetpointSpec`` by PRD 12 tag - the alias table, borrowed rather than restated.
_SPEC_BY_TAG: dict[str, SetpointSpec] = {spec.tag: spec for spec in SETPOINTS}

#: Config sub-key of ``modes`` for each mode label of :mod:`src.labels`.
_MODE_KEYS: dict[str, str] = {mode: mode.lower() for mode in OPTIMIZATION_MODE_VALUES}


@dataclass(frozen=True, slots=True)
class DecisionVariable:
    """One manipulated variable, with everything NFR-11 asks a decision variable to declare."""

    name: str
    twin_input: str
    dataset: str
    unit: str
    minimum: float
    maximum: float
    ramp_minutes: float
    step_absolute: float | None = None
    step_pct_of_current: float | None = None
    reference_value: float | None = None
    ratio_of_reference: tuple[float, float] | None = None

    def step_at(self, current: float) -> float:
        """Slider granularity at ``current`` (PRD 17); percentage steps scale with the value."""
        if self.step_absolute is not None:
            return float(self.step_absolute)
        pct = float(self.step_pct_of_current or 0.0)
        return abs(float(current)) * pct / 100.0

    def snap_to_step(self, value: float, current: float) -> float:
        """Round ``value`` onto this variable's step grid, *without* clipping it.

        Split out from :meth:`snap` for one caller with a real need for it: PRD 16.1 requires a
        what-if request that would leave the calibrated range to be "rejected with an explanation",
        which means the out-of-range value has to survive intact as far as PRD 14.3 check 1. Clipping
        it here first would make that check unreachable and turn the rejection into a silent
        correction. The optimizer's own search always wants the clip and keeps using :meth:`snap`.
        """
        step = self.step_at(current)
        return float(value) if step <= 0.0 else round(float(value) / step) * step

    def snap(self, value: float, current: float) -> float:
        """Round ``value`` onto this variable's step grid, then clip to its absolute range.

        Snapping is what makes a swept candidate reproducible as a *slider position*: PRD 17's
        UI cannot express a value between two steps, so the optimizer must not recommend one.
        """
        return self.clip(self.snap_to_step(value, current))

    def clip(self, value: float) -> float:
        return min(max(float(value), self.minimum), self.maximum)

    def contains(self, value: float) -> bool:
        return self.minimum <= float(value) <= self.maximum

    def delta_fraction(self, value: float, current: float) -> float:
        """Signed change as a fraction of ``current`` - the quantity PRD 14.2 caps at 10 %."""
        if float(current) == 0.0:  # pragma: no cover - no PRD 16.1 variable is zero-valued
            return 0.0 if float(value) == float(current) else math.inf
        return (float(value) - float(current)) / abs(float(current))

    def describe(self) -> dict[str, Any]:
        """NFR-11 record: range, step, and where each of them comes from."""
        return {
            "name": self.name,
            "twin_input": self.twin_input,
            "dataset": self.dataset,
            "unit": self.unit,
            "range": [self.minimum, self.maximum],
            "range_basis": (
                "ratio_of_reference"
                if self.ratio_of_reference is not None
                else "absolute_range"
            ),
            "ratio_of_reference": (
                None if self.ratio_of_reference is None else list(self.ratio_of_reference)
            ),
            "reference_value": self.reference_value,
            "step_absolute": self.step_absolute,
            "step_pct_of_current": self.step_pct_of_current,
            "ramp_minutes": self.ramp_minutes,
        }


class DecisionSpace:
    """The six PRD 16.1 variables, their bounds, and the per-mode change limit."""

    __slots__ = ("_config", "_scenarios", "_variables")

    def __init__(
        self,
        variables: Mapping[str, DecisionVariable],
        *,
        config: Config,
        scenarios: Config,
    ) -> None:
        self._variables = dict(variables)
        self._config = config
        self._scenarios = scenarios

    # -- construction -------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        *,
        references: Mapping[str, Any],
        config: Config | None = None,
        scenarios: Config | None = None,
    ) -> "DecisionSpace":
        """Build the space from config, resolving ratio bounds against ``references``.

        ``references`` maps a dataset name to its solved reference point (``KilnReferencePoint``
        / ``MillReferencePoint``, i.e. ``twin.kiln.reference`` and ``twin.cement_mill.reference``).
        Passing the twin's own reference objects - rather than re-solving them here - is what
        keeps a ratio bound anchored to the same operating point the physics was built around.
        """
        optimization = config if config is not None else load_config(OPTIMIZATION)
        scenario_config = scenarios if scenarios is not None else load_config(SCENARIOS)
        ramps = scenario_config.get_path("ramp_times_min")
        block = optimization.get_path("decision_variables")

        variables: dict[str, DecisionVariable] = {}
        for name in block:
            entry = block.get_path(name)
            spec = _SPEC_BY_TAG.get(name)
            if spec is None:
                raise ConfigError(
                    f"decision variable {name!r} is not a scheduled setpoint; expected one of "
                    f"{sorted(_SPEC_BY_TAG)}"
                )
            reference = references.get(spec.dataset)
            if reference is None:
                raise ConfigError(f"no reference point supplied for dataset {spec.dataset!r}")
            reference_value = float(getattr(reference, spec.reference_attr))

            ratio = entry.get_path("ratio_of_reference", None)
            if ratio is not None:
                bounds = (
                    float(ratio[0]) * reference_value,
                    float(ratio[1]) * reference_value,
                )
                ratio_bounds: tuple[float, float] | None = (float(ratio[0]), float(ratio[1]))
            else:
                absolute = entry.get_path("range")
                bounds = (float(absolute[0]), float(absolute[1]))
                ratio_bounds = None

            variables[name] = DecisionVariable(
                name=name,
                twin_input=spec.variable,
                dataset=spec.dataset,
                unit=str(entry.get_path("unit")),
                minimum=bounds[0],
                maximum=bounds[1],
                ramp_minutes=float(ramps.get_path(spec.ramp_key)),
                step_absolute=(
                    None if entry.get_path("step", None) is None else float(entry.get_path("step"))
                ),
                step_pct_of_current=(
                    None
                    if entry.get_path("step_pct_of_current", None) is None
                    else float(entry.get_path("step_pct_of_current"))
                ),
                reference_value=reference_value,
                ratio_of_reference=ratio_bounds,
            )
        return cls(variables, config=optimization, scenarios=scenario_config)

    @classmethod
    def from_twin(
        cls,
        twin: Any,
        *,
        config: Config | None = None,
        scenarios: Config | None = None,
    ) -> "DecisionSpace":
        """Convenience wrapper: take the reference points off a :class:`PlantTwin`."""
        return cls.from_config(
            references={
                "kiln": twin.kiln.reference,
                "mill": twin.cement_mill.reference,
            },
            config=config,
            scenarios=scenarios,
        )

    # -- mapping-ish access -------------------------------------------------------------
    @property
    def names(self) -> tuple[str, ...]:
        """Variable names in config order - the deterministic iteration order of the search."""
        return tuple(self._variables)

    @property
    def config(self) -> Config:
        return self._config

    def __len__(self) -> int:
        return len(self._variables)

    def __iter__(self) -> Iterator[DecisionVariable]:
        return iter(self._variables.values())

    def __contains__(self, name: object) -> bool:
        return name in self._variables

    def __getitem__(self, name: str) -> DecisionVariable:
        try:
            return self._variables[name]
        except KeyError:
            raise KeyError(
                f"{name!r} is not a decision variable; PRD 16.1 allows {self.names}"
            ) from None

    def of_dataset(self, dataset: str) -> tuple[DecisionVariable, ...]:
        return tuple(item for item in self if item.dataset == dataset)

    # -- modes (PRD 14.3 / 16.1) --------------------------------------------------------
    def max_delta_fraction(self, mode: str) -> float:
        """The |dSetpoint| cap of ``mode`` - 10 % in Normal Mode (PRD 14.2 check 4)."""
        return float(self._config.get_path(f"modes.{self._mode_key(mode)}.max_delta_fraction"))

    def enforce_envelope(self, mode: str) -> bool:
        """Whether PRD 14.3's checks are enforced (Normal) or only reported (Experimental)."""
        return bool(self._config.get_path(f"modes.{self._mode_key(mode)}.enforce_envelope"))

    @staticmethod
    def _mode_key(mode: str) -> str:
        try:
            return _MODE_KEYS[str(mode).upper()]
        except KeyError:
            raise ValueError(
                f"unknown optimization mode {mode!r}; expected one of {OPTIMIZATION_MODE_VALUES}"
            ) from None

    # -- candidate geometry --------------------------------------------------------------
    def baseline(self, inputs: Mapping[str, float]) -> dict[str, float]:
        """Current value of every decision variable, read out of a twin input dict.

        Both spellings are accepted on the way in (``twin.inputs`` uses ``twin_input``, an
        exported dataset row uses ``name``) and the result is always keyed by ``name``.
        """
        current: dict[str, float] = {}
        for variable in self:
            for key in (variable.twin_input, variable.name):
                if key in inputs:
                    current[variable.name] = float(inputs[key])
                    break
            else:
                raise KeyError(
                    f"cannot read decision variable {variable.name!r}: neither "
                    f"{variable.twin_input!r} nor {variable.name!r} is present"
                )
        return current

    def to_twin_inputs(self, values: Mapping[str, float]) -> dict[str, float]:
        """Translate a ``name``-keyed proposal into the twin's input spelling."""
        return {self[name].twin_input: float(value) for name, value in values.items()}

    def bounds(self, name: str, current: float, mode: str) -> tuple[float, float]:
        """Absolute range intersected with the mode's change limit around ``current``."""
        variable = self[name]
        span = abs(float(current)) * self.max_delta_fraction(mode)
        return (
            max(variable.minimum, float(current) - span),
            min(variable.maximum, float(current) + span),
        )

    def snap(self, name: str, value: float, current: float) -> float:
        return self[name].snap(value, current)

    def delta_fractions(
        self, proposed: Mapping[str, float], baseline: Mapping[str, float]
    ) -> dict[str, float]:
        """Per-variable signed change fraction of a proposal versus a baseline."""
        return {
            name: self[name].delta_fraction(float(value), float(baseline[name]))
            for name, value in proposed.items()
        }

    def describe(self) -> dict[str, Any]:
        """NFR-11 / PRD 35 review-checklist record for the whole space."""
        return {
            "variables": [variable.describe() for variable in self],
            "modes": {
                mode: {
                    "max_delta_fraction": self.max_delta_fraction(mode),
                    "enforce_envelope": self.enforce_envelope(mode),
                }
                for mode in OPTIMIZATION_MODE_VALUES
            },
        }


__all__ = ["DecisionSpace", "DecisionVariable"]
