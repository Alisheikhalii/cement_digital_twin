"""Typed reader for ``configs/dashboard.yaml`` - presentation constants only (Task #6).

Nothing here is a process quantity. Every field is a *display* number: how wide the amber band
is, how fast a dash cycle runs at full rate, how many points a trend may send to the browser,
which clock speeds the PLAY control offers. Process limits stay in :mod:`src.schema` and the two
dynamics configs; model thresholds stay in ``configs/ml.yaml`` and ``configs/optimization.yaml``.

The reason this is a module and not a dict lookup at each use site is NFR-6/AC-12: a panel may
not hold a literal number, so the panel reads ``settings.animation.particles`` and the number
exists exactly once, in the YAML, marked ``ASSUMPTION``.

:meth:`AnimationSettings.scale` is the single function that turns a process fraction into an
animation parameter (AC-21: "every animated element is driven by live state"). An animation
parameter is therefore ``scale(pair, value.fraction_of_range())`` by construction - there is no
other way to reach one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Sequence

from src.config import DASHBOARD, Config, ConfigError, load_config

#: Two-element output ranges are read as ``(at_zero, at_full)``. The second value may be the
#: *smaller* of the two - a faster dash cycle is a shorter period - so no ordering is imposed.
Pair = tuple[float, float]

#: Minutes in a simulated day. Here rather than at the use site for the same reason as everything
#: else in this module: the use site may not hold a literal (NFR-6, AC-12).
_MINUTES_PER_DAY: Final = 24.0 * 60.0


def _pair(block: Config, key: str) -> Pair:
    values = block.get_path(key)
    if len(values) != 2:
        raise ConfigError(f"dashboard {key!r} must be a [at_zero, at_full] pair, got {values!r}")
    return (float(values[0]), float(values[1]))


def _speeds(block: Config, key: str) -> tuple[float, ...]:
    speeds = tuple(float(value) for value in block.get_path(key))
    if not speeds or any(speed <= 0.0 for speed in speeds):
        raise ConfigError(f"dashboard {key!r} must be positive multipliers, got {speeds!r}")
    return speeds


def _optional_float(block: Config, key: str) -> float | None:
    """A YAML number or an explicit ``null``, which every reader here treats as "derive it"."""
    value = block.get_path(key, None)
    if value is None:
        return None
    number = float(value)
    if number <= 0.0:
        raise ConfigError(f"dashboard {key!r} must be > 0 or null, got {value!r}")
    return number


@dataclass(frozen=True, slots=True)
class StatusSettings:
    """PRD 17.1 alarm banding. The limits it bands against are never defined here."""

    warn_fraction_of_span: float
    alarm_fraction_of_span: float


@dataclass(frozen=True, slots=True)
class AnimationSettings:
    """Output ranges of the state -> animation functions of PRD 19.4."""

    flow_period_seconds: Pair
    particles: Pair
    flow_opacity: Pair
    rotation_period_seconds: Pair
    glow_opacity: Pair
    stroke_width: Pair
    min_rate_fraction: float

    @staticmethod
    def scale(pair: Pair, fraction: float | None) -> float:
        """Linear map from a ``[0, 1]`` process fraction onto one output range.

        ``fraction`` is :meth:`~src.digital_twin.provenance.Value.fraction_of_range` - already
        clamped there. ``None`` (no value, or a tag with no documented range) returns the
        at-zero end: an element whose driving reading is missing is drawn at rest rather than at
        an invented speed.
        """
        low, high = float(pair[0]), float(pair[1])
        if fraction is None:
            return low
        return low + (high - low) * max(0.0, min(1.0, float(fraction)))

    def moving(self, fraction: float | None) -> bool:
        """Whether a stream at this fraction of its range is drawn as flowing at all."""
        return fraction is not None and float(fraction) >= self.min_rate_fraction


@dataclass(frozen=True, slots=True)
class HistorySettings:
    """Trend budgets (NFR-1, directive item 23: never stream the raw window)."""

    max_points: int
    sparkline_points: int
    live_window_minutes: float
    default_window_hours: float
    downsample_method: str


@dataclass(frozen=True, slots=True)
class ClockSettings:
    """The PLAY / PAUSE / STEP / speed control of directive item 7."""

    speeds: tuple[float, ...]
    default_speed: float
    step_minutes: float
    max_live_steps: int


@dataclass(frozen=True, slots=True)
class ReplaySettings:
    """The scrubber of directive item 8."""

    speeds: tuple[float, ...]
    default_speed: float
    step_minutes: float


@dataclass(frozen=True, slots=True)
class PresentationSettings:
    """Factory Presentation Mode (PRD 29) - cadence and headline rounding."""

    refresh_seconds: float
    headline_decimals: int


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """How much simulated material one session holds (directive items 7, 8, 21).

    Both fields are ``None``-able because both have a defensible derivation from a number that
    already exists: the replay window can be the full configured run length, and the live warm-up
    can be exactly the window the models read. :meth:`replay_minutes` and :meth:`priming_minutes`
    perform those two derivations so no caller has to restate them.
    """

    replay_days: float | None
    prime_minutes: float | None

    def replay_minutes(self, configured_minutes: float | None = None) -> float | None:
        """Minutes of run to build for REPLAY, or ``None`` for "the whole configured run".

        ``configured_minutes`` is ``SimulationConfig.duration_minutes``; it is only consulted to
        refuse a window longer than the run being replayed, which would silently extend the
        simulation rather than replay it.
        """
        if self.replay_days is None:
            return None
        minutes = float(self.replay_days) * _MINUTES_PER_DAY
        if configured_minutes is not None and minutes > float(configured_minutes):
            return float(configured_minutes)
        return minutes

    def priming_minutes(self, history: "HistorySettings") -> float:
        """Trailing minutes the live clock is primed with before the first frame is drawn."""
        if self.prime_minutes is None:
            return float(history.live_window_minutes)
        return float(self.prime_minutes)


@dataclass(frozen=True, slots=True)
class FormatSettings:
    """How many digits a numeric readout shows (PRD 17.1).

    Typography only. :meth:`digits` decides *decimal places* from the magnitude of the number
    being shown, so a burning-zone temperature reads ``1451`` and an oxygen percentage reads
    ``3.42`` from the same rule rather than from a per-tag precision table - a table would be a
    per-tag claim about instrument resolution, which is a plant fact this project does not have.
    """

    significant_digits: int
    max_decimals: int

    def digits(self, value: float) -> int:
        """Decimal places for one value: ``significant_digits`` of it, capped and never negative.

        A magnitude-based rule rather than a fixed decimal count because the tags on one screen
        span six orders of magnitude (``residue_percent`` ~ 1, ``exhaust_gas_flow`` ~ 3e5): a fixed
        two decimals would print noise on one and hide the whole signal on the other.
        """
        magnitude = abs(float(value))
        if magnitude == 0.0 or magnitude != magnitude:  # NaN-safe
            return 0
        from math import floor, log10

        used = int(floor(log10(magnitude))) + 1
        return max(0, min(self.max_decimals, self.significant_digits - used))


@dataclass(frozen=True, slots=True)
class DashboardSettings:
    """Every presentation constant, in one object the provider and the views share."""

    status: StatusSettings
    animation: AnimationSettings
    history: HistorySettings
    clock: ClockSettings
    replay: ReplaySettings
    presentation: PresentationSettings
    session: SessionSettings
    format: FormatSettings

    @classmethod
    def from_config(cls, config: Config | None = None) -> "DashboardSettings":
        """Read ``configs/dashboard.yaml``; refuse a malformed block rather than defaulting."""
        dashboard = config if config is not None else load_config(DASHBOARD)
        status = dashboard.get_path("status")
        animation = dashboard.get_path("animation")
        history = dashboard.get_path("history")
        clock = dashboard.get_path("clock")
        replay = dashboard.get_path("replay")
        presentation = dashboard.get_path("presentation")
        session = dashboard.get_path("session")
        numbers = dashboard.get_path("format")
        settings = cls(
            status=StatusSettings(
                warn_fraction_of_span=float(status.get_path("warn_fraction_of_span")),
                alarm_fraction_of_span=float(status.get_path("alarm_fraction_of_span")),
            ),
            animation=AnimationSettings(
                flow_period_seconds=_pair(animation, "flow_period_seconds"),
                particles=_pair(animation, "particles"),
                flow_opacity=_pair(animation, "flow_opacity"),
                rotation_period_seconds=_pair(animation, "rotation_period_seconds"),
                glow_opacity=_pair(animation, "glow_opacity"),
                stroke_width=_pair(animation, "stroke_width"),
                min_rate_fraction=float(animation.get_path("min_rate_fraction")),
            ),
            history=HistorySettings(
                max_points=int(history.get_path("max_points")),
                sparkline_points=int(history.get_path("sparkline_points")),
                live_window_minutes=float(history.get_path("live_window_minutes")),
                default_window_hours=float(history.get_path("default_window_hours")),
                downsample_method=str(history.get_path("downsample_method")),
            ),
            clock=ClockSettings(
                speeds=_speeds(clock, "speeds"),
                default_speed=float(clock.get_path("default_speed")),
                step_minutes=float(clock.get_path("step_minutes")),
                max_live_steps=int(clock.get_path("max_live_steps")),
            ),
            replay=ReplaySettings(
                speeds=_speeds(replay, "speeds"),
                default_speed=float(replay.get_path("default_speed")),
                step_minutes=float(replay.get_path("step_minutes")),
            ),
            presentation=PresentationSettings(
                refresh_seconds=float(presentation.get_path("refresh_seconds")),
                headline_decimals=int(presentation.get_path("headline_decimals")),
            ),
            session=SessionSettings(
                replay_days=_optional_float(session, "replay_days"),
                prime_minutes=_optional_float(session, "prime_minutes"),
            ),
            format=FormatSettings(
                significant_digits=int(numbers.get_path("significant_digits")),
                max_decimals=int(numbers.get_path("max_decimals")),
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Refuse settings that would make a view silently wrong rather than merely ugly."""
        if not 0.0 <= self.status.warn_fraction_of_span < 0.5:
            raise ConfigError(
                "status.warn_fraction_of_span is measured inward from each limit, so it must be "
                f"in [0, 0.5); got {self.status.warn_fraction_of_span!r}"
            )
        if self.history.max_points < self.history.sparkline_points:
            raise ConfigError(
                f"history.max_points ({self.history.max_points}) is below sparkline_points "
                f"({self.history.sparkline_points}): a trend cannot carry fewer points than a card"
            )
        if self.history.max_points < 2 or self.history.sparkline_points < 2:
            raise ConfigError("a trend needs at least two points to be a trend")
        for label, speeds, default in (
            ("clock", self.clock.speeds, self.clock.default_speed),
            ("replay", self.replay.speeds, self.replay.default_speed),
        ):
            if default not in speeds:
                raise ConfigError(
                    f"{label}.default_speed {default!r} is not one of {label}.speeds {speeds!r}"
                )
        if self.clock.step_minutes <= 0.0 or self.replay.step_minutes <= 0.0:
            raise ConfigError("clock/replay step_minutes must be > 0")
        if self.clock.max_live_steps < 1:
            raise ConfigError("clock.max_live_steps must allow at least one step")
        if not 0.0 <= self.animation.min_rate_fraction < 1.0:
            raise ConfigError(
                "animation.min_rate_fraction is a fraction of a documented range, so it must be "
                f"in [0, 1); got {self.animation.min_rate_fraction!r}"
            )
        if self.presentation.refresh_seconds <= 0.0 or self.presentation.headline_decimals < 0:
            raise ConfigError("presentation.refresh_seconds must be > 0 and decimals >= 0")
        if self.session.priming_minutes(self.history) < self.history.live_window_minutes:
            raise ConfigError(
                f"session.prime_minutes ({self.session.prime_minutes!r}) is shorter than "
                f"history.live_window_minutes ({self.history.live_window_minutes:g}): the model "
                "panels would open on a window the models cannot read"
            )
        if self.format.significant_digits < 1 or self.format.max_decimals < 0:
            raise ConfigError(
                "format.significant_digits must be >= 1 and format.max_decimals >= 0; got "
                f"{self.format.significant_digits!r} and {self.format.max_decimals!r}"
            )

    def describe(self) -> dict[str, Any]:
        return {
            "status": {
                "warn_fraction_of_span": self.status.warn_fraction_of_span,
                "alarm_fraction_of_span": self.status.alarm_fraction_of_span,
            },
            "animation": {
                "flow_period_seconds": list(self.animation.flow_period_seconds),
                "particles": list(self.animation.particles),
                "flow_opacity": list(self.animation.flow_opacity),
                "rotation_period_seconds": list(self.animation.rotation_period_seconds),
                "glow_opacity": list(self.animation.glow_opacity),
                "stroke_width": list(self.animation.stroke_width),
                "min_rate_fraction": self.animation.min_rate_fraction,
            },
            "history": {
                "max_points": self.history.max_points,
                "sparkline_points": self.history.sparkline_points,
                "live_window_minutes": self.history.live_window_minutes,
                "default_window_hours": self.history.default_window_hours,
                "downsample_method": self.history.downsample_method,
            },
            "clock": {
                "speeds": list(self.clock.speeds),
                "default_speed": self.clock.default_speed,
                "step_minutes": self.clock.step_minutes,
                "max_live_steps": self.clock.max_live_steps,
            },
            "replay": {
                "speeds": list(self.replay.speeds),
                "default_speed": self.replay.default_speed,
                "step_minutes": self.replay.step_minutes,
            },
            "presentation": {
                "refresh_seconds": self.presentation.refresh_seconds,
                "headline_decimals": self.presentation.headline_decimals,
            },
            "session": {
                "replay_days": self.session.replay_days,
                "prime_minutes": self.session.prime_minutes,
                "priming_minutes": self.session.priming_minutes(self.history),
            },
            "format": {
                "significant_digits": self.format.significant_digits,
                "max_decimals": self.format.max_decimals,
            },
        }


#: Speed labels the UI draws on the speed selector - the configured multipliers, formatted.
def speed_labels(speeds: Sequence[float]) -> tuple[str, ...]:
    """``(0.25, 1.0, 10.0)`` -> ``("0.25x", "1x", "10x")``; no speed is added or removed."""
    return tuple(
        f"{speed:g}x" if speed != int(speed) else f"{int(speed)}x" for speed in speeds
    )


DOWNSAMPLE_METHODS: Final[tuple[str, ...]] = ("minmax", "mean", "last")


__all__ = [
    "DOWNSAMPLE_METHODS",
    "AnimationSettings",
    "ClockSettings",
    "DashboardSettings",
    "FormatSettings",
    "HistorySettings",
    "Pair",
    "PresentationSettings",
    "ReplaySettings",
    "SessionSettings",
    "StatusSettings",
    "speed_labels",
]
