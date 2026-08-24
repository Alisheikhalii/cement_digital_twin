"""Per-relationship transport delays (PRD v1.1.1 Sections 9.4, 10.3).

``DelayedResponse`` is a pure transport dead time followed by a first-order lag. One
instance is created **per causal relationship** (fuel->BZT, fuel->O2, ID fan->pressure,
separator->Blaine, ...), never one universal time constant for the whole model - that
distinction is a mandatory, tested requirement (AC-15, Section 34 "delay framework").

``DelayBank`` holds the named instances of one process unit, built directly from the
``delays:`` block of ``configs/kiln_dynamics.yaml`` / ``configs/mill_dynamics.yaml`` so a
delay can never be hard-coded at a call site (NFR-6).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterator, Mapping
from typing import Final

#: Rows whose ``tau_min`` is null get a pure dead time; their lag comes from a physical
#: inventory buffer instead (PRD 9.3 kiln inventory / PRD 10.2 mill holdup).
NO_LAG: Final = 0.0

SECONDS_PER_MINUTE: Final = 60.0


class DelayedResponse:
    """``y(t)`` tracks ``y_target`` with a dead time, then a first-order lag (PRD 9.4).

    The dead time is a real FIFO transport queue (exact for any ``dt``, including the
    variable ``dt`` used by the interactive what-if rollouts), and the lag uses the exact
    zero-order-hold discretization ``alpha = 1 - exp(-dt/tau)`` so results do not depend on
    the step size chosen by the caller (NFR-4 reproducibility).
    """

    __slots__ = ("_clock", "_dead_time_s", "_delayed_target", "_name", "_queue", "_tau_s", "_value")

    def __init__(
        self, dead_time_s: float, tau_s: float | None, initial: float = 0.0, name: str = ""
    ) -> None:
        if dead_time_s is None or float(dead_time_s) < 0.0:
            raise ValueError(f"dead_time_s must be >= 0 (got {dead_time_s!r}) for {name!r}")
        tau = NO_LAG if tau_s is None else float(tau_s)
        if tau < 0.0:
            raise ValueError(f"tau_s must be >= 0 (got {tau_s!r}) for {name!r}")
        self._dead_time_s = float(dead_time_s)
        self._tau_s = tau
        self._value = float(initial)
        self._delayed_target = float(initial)
        self._queue: deque[tuple[float, float]] = deque()
        self._clock = 0.0
        self._name = name

    @classmethod
    def from_minutes(
        cls,
        dead_time_min: float,
        tau_min: float | None = None,
        initial: float = 0.0,
        name: str = "",
    ) -> DelayedResponse:
        """Build from the minute-based values used in the config files (PRD 9.4/10.3)."""
        tau_s = None if tau_min is None else float(tau_min) * SECONDS_PER_MINUTE
        return cls(float(dead_time_min) * SECONDS_PER_MINUTE, tau_s, initial, name)

    @classmethod
    def from_spec(
        cls, spec: Mapping[str, float | None], initial: float = 0.0, name: str = ""
    ) -> DelayedResponse:
        """Build from one ``delays:`` row, e.g. ``{dead_time_min: 2.0, tau_min: 25.0}``."""
        try:
            dead_time_min = spec["dead_time_min"]
        except KeyError as exc:  # pragma: no cover - config contract violation
            raise KeyError(f"delay {name!r} has no 'dead_time_min' key") from exc
        return cls.from_minutes(float(dead_time_min), spec.get("tau_min"), initial, name)

    # -- properties ---------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def dead_time_s(self) -> float:
        return self._dead_time_s

    @property
    def tau_s(self) -> float:
        return self._tau_s

    @property
    def value(self) -> float:
        """Current output, without advancing time."""
        return self._value

    @property
    def delayed_target(self) -> float:
        """Target already released by the transport queue (the lag's current input)."""
        return self._delayed_target

    @property
    def in_transit(self) -> int:
        """Number of targets still inside the transport dead time."""
        return len(self._queue)

    # -- dynamics -----------------------------------------------------------------------
    def step(self, y_target: float, dt_s: float) -> float:
        """Advance by ``dt_s`` and return the new output."""
        if dt_s <= 0.0:
            raise ValueError(f"dt_s must be > 0 (got {dt_s!r}) for delay {self._name!r}")
        self._clock += float(dt_s)
        self._queue.append((self._clock + self._dead_time_s, float(y_target)))
        while self._queue and self._queue[0][0] <= self._clock:
            self._delayed_target = self._queue.popleft()[1]
        if self._tau_s <= NO_LAG:
            self._value = self._delayed_target
        else:
            alpha = 1.0 - math.exp(-float(dt_s) / self._tau_s)
            self._value += alpha * (self._delayed_target - self._value)
        return self._value

    def settle(self, value: float) -> float:
        """Place the whole relationship at steady state on ``value`` (used at init).

        This is what lets the twin start exactly on the reference operating point, so the
        first simulated step shows no artificial start-up transient and the conservation
        residuals start at zero (PRD 9.3 "closure holds at the reference point").
        """
        self._queue.clear()
        self._value = float(value)
        self._delayed_target = float(value)
        return self._value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DelayedResponse(name={self._name!r}, dead_time_s={self._dead_time_s:g}, "
            f"tau_s={self._tau_s:g}, value={self._value:g})"
        )


class DelayBank(Mapping[str, DelayedResponse]):
    """The named ``DelayedResponse`` objects of one process unit, built from its config.

    Look-ups fail loudly on an unknown relationship name: a typo must not silently become an
    instantaneous response, which is exactly the failure mode AC-15 guards against.
    """

    __slots__ = ("_delays", "_source")

    def __init__(
        self,
        spec: Mapping[str, Mapping[str, float | None]],
        *,
        initial: float = 0.0,
        source: str = "<memory>",
    ) -> None:
        self._delays: dict[str, DelayedResponse] = {
            name: DelayedResponse.from_spec(row, initial=initial, name=name)
            for name, row in spec.items()
        }
        self._source = source

    # -- Mapping protocol ---------------------------------------------------------------
    def __getitem__(self, name: str) -> DelayedResponse:
        try:
            return self._delays[name]
        except KeyError as exc:
            raise KeyError(
                f"no delay {name!r} configured in {self._source}; "
                f"available relationships: {sorted(self._delays)}"
            ) from exc

    def __iter__(self) -> Iterator[str]:
        return iter(self._delays)

    def __len__(self) -> int:
        return len(self._delays)

    # -- convenience --------------------------------------------------------------------
    def step(self, name: str, y_target: float, dt_s: float) -> float:
        """Advance one named relationship (PRD 9.4: each relationship has its own delay)."""
        return self[name].step(y_target, dt_s)

    def value(self, name: str) -> float:
        return self[name].value

    def settle(self, name: str, value: float) -> float:
        return self[name].settle(value)

    def settle_all(self, values: Mapping[str, float] | float = 0.0) -> None:
        """Settle every relationship, either at one common value or per-name."""
        if isinstance(values, Mapping):
            for name, value in values.items():
                self[name].settle(value)
            return
        for delay in self._delays.values():
            delay.settle(float(values))

    def dead_time_s(self, name: str) -> float:
        return self[name].dead_time_s

    def tau_s(self, name: str) -> float:
        return self[name].tau_s

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DelayBank({self._source!r}, relationships={sorted(self._delays)})"


def build_delay_bank(
    unit_config: Mapping[str, object], *, key: str = "delays", initial: float = 0.0
) -> DelayBank:
    """Build a :class:`DelayBank` from a unit config's ``delays:`` block."""
    try:
        spec = unit_config[key]
    except KeyError as exc:  # pragma: no cover - config contract violation
        raise KeyError(f"unit config has no {key!r} block (PRD 9.4/10.3)") from exc
    if not isinstance(spec, Mapping):  # pragma: no cover - config contract violation
        raise TypeError(f"{key!r} must be a mapping of relationship -> {{dead_time_min, tau_min}}")
    source = str(getattr(unit_config, "source", "<memory>"))
    return DelayBank(spec, initial=initial, source=source)  # type: ignore[arg-type]


__all__ = [
    "NO_LAG",
    "SECONDS_PER_MINUTE",
    "DelayedResponse",
    "DelayBank",
    "build_delay_bank",
]
