"""The transport controller behind the PLAY / PAUSE / STEP / RESET / speed control and the
replay scrubber (PRD v1.1.1 directive items 7 and 8; Section 26's "the dashboard drives
simulated time by asking the provider").

This module is the *brain* of the clock control, not its buttons. It holds one piece of state a
:class:`~src.digital_twin.provider.DataProvider` cannot hold for itself - whether the user has
pressed PLAY, how fast, and (in LIVE) how much of the session budget is spent - and it turns the
discrete operations the dashboard exposes (PLAY, PAUSE, STEP, RESET, a speed selector, a scrubber)
into calls on the provider's optional clock surface (:meth:`~DataProvider.advance`,
:meth:`~DataProvider.reset`, :meth:`~DataProvider.seek`). Nothing here touches a process model, a
CSV or a chart: the controller reads the provider ABC and ``configs/dashboard.yaml`` and nothing
else, which is what lets the same control drive a plant historian the day one replaces the
synthetic source (FR-14).

**No wall clock lives here.** A media player advances by itself because a timer ticks; that timer
belongs to the dashboard (an ``ipywidgets`` loop) and to Factory Presentation Mode, not to the
transport logic. The controller instead exposes :meth:`tick` - "one beat elapsed, advance if
playing" - so the dashboard calls it from its timer and a test calls it in a ``for`` loop, and the
two agree exactly. That is the NFR-9/Section 34 line: the state machine is testable without a
browser, a widget or a sleeping thread.

**Speed is steps per beat.** At ``1x`` one beat advances one dataset sample (``step_minutes`` of
simulated time, PRD 12); ``2x`` advances two; ``0.25x`` advances a quarter, so three beats out of
four leave the position unchanged and the stream visibly crawls. The fractional remainder is
accumulated (:attr:`_pending`) rather than rounded, so sub-unit speeds are honest over time rather
than either stuck at zero or silently promoted to ``1x``.

Every number the controller uses - the offered speeds, the default speed, the minutes in one step,
the live-session step budget - is read from :class:`~src.digital_twin.settings.DashboardSettings`,
never written here (NFR-6/AC-12). The only bare integers below are structural (``+ 1`` to count an
inclusive endpoint, ``0`` for "no steps taken yet"), not presentation constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from src.config import ConfigError
from src.digital_twin.payloads import LIVE, REPLAY, StateSnapshot
from src.digital_twin.provider import CapabilityError, DataProvider
from src.digital_twin.settings import (
    ClockSettings,
    DashboardSettings,
    ReplaySettings,
    speed_labels,
)

#: One minute as a :class:`pandas.Timedelta`, used only to convert a timestamp difference into a
#: count of ``step_minutes``-sized steps. A unit conversion, not a presentation constant.
_ONE_MINUTE = pd.Timedelta(minutes=1)


def _clamp01(value: float) -> float:
    """Clamp to ``[0, 1]`` - a progress fraction can never sit outside the bar it fills."""
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


@dataclass(frozen=True, slots=True)
class ClockState:
    """A read-only snapshot of the transport, everything the dashboard needs to draw its controls.

    The dashboard renders from this and never reaches into the controller: which button is enabled
    is ``can_*``; which speed is lit is ``speed`` against ``speeds``; where the scrubber sits is
    ``fraction`` with ``step_index``/``step_count`` for the "step X of Y" readout; whether to show
    PLAY or PAUSE is ``playing``. ``at_start``/``at_end`` are the endpoints where PLAY stops on its
    own (a live session hits its budget; a replay hits the last recorded row).
    """

    mode: str
    modes: tuple[str, ...]
    playing: bool
    speed: float
    speeds: tuple[float, ...]
    step_minutes: float
    #: The position the provider last reported, or ``None`` when it reports none at all. A source
    #: that refuses ``get_current_state`` (PRD 26.1's real-plant stub) has no position to show, and
    #: an absent position is stated as ``None`` rather than filled in with a plausible timestamp
    #: (directive item 20 / NFR-6). ``None`` stays JSON-describable, so item 21 still holds.
    timestamp: str | None
    step_index: int
    step_count: int
    fraction: float
    at_start: bool
    at_end: bool
    can_play: bool
    can_step_back: bool
    can_scrub: bool
    can_reset: bool
    can_switch_mode: bool

    @property
    def speed_label(self) -> str:
        """The current speed formatted as the selector shows it (``"0.25x"``, ``"1x"``)."""
        return speed_labels((self.speed,))[0]

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "modes": list(self.modes),
            "playing": self.playing,
            "speed": self.speed,
            "speeds": list(self.speeds),
            "step_minutes": self.step_minutes,
            "timestamp": self.timestamp,
            "step_index": self.step_index,
            "step_count": self.step_count,
            "fraction": self.fraction,
            "at_start": self.at_start,
            "at_end": self.at_end,
            "can_play": self.can_play,
            "can_step_back": self.can_step_back,
            "can_scrub": self.can_scrub,
            "can_reset": self.can_reset,
            "can_switch_mode": self.can_switch_mode,
        }


class Clock:
    """PLAY / PAUSE / STEP / RESET / speed + scrubber, as a pure controller over a provider.

    Construct it with the provider the dashboard is showing and the loaded settings; drive it with
    the discrete methods (:meth:`play`, :meth:`pause`, :meth:`toggle`, :meth:`step_forward`,
    :meth:`step_back`, :meth:`reset`, :meth:`set_speed`, :meth:`seek_fraction`, :meth:`set_mode`)
    and, from a timer, :meth:`tick`. Every method returns the fresh :class:`ClockState`, so the
    dashboard re-renders from the return value and never has to ask twice.

    The controller keeps no copy of the process data - only transport intent (playing, speed), a
    fractional-step accumulator, the count of LIVE steps spent against the session budget, and the
    last timestamp the provider reported (so :meth:`state` needs no fresh, noise-resampling call to
    the provider between beats).
    """

    def __init__(self, provider: DataProvider, settings: DashboardSettings) -> None:
        self._provider = provider
        self._settings = settings
        self._playing = False
        self._pending = 0.0  # accumulated fractional steps not yet advanced (sub-1x speeds)
        self._live_steps = 0  # advances spent this LIVE session, against clock.max_live_steps
        self._ended = False  # the LIVE source refused a further advance (budget reached)
        self._speed = self._mode_clock().default_speed
        # Seed the cached position from the provider's current state (one call, at construction).
        self._last_timestamp = self._read_position()

    def _read_position(self) -> str | None:
        """The provider's current timestamp, or ``None`` when it will not report one.

        ``get_current_state`` is a *required* surface of the contract - it is an
        ``@abstractmethod`` and, unlike ``truth`` / ``history`` / ``predictions`` / ``anomaly`` /
        ``optimization`` / ``what_if``, :class:`~src.digital_twin.payloads.ProviderCapabilities`
        carries **no flag** for it. So there is no flag to gate this read on, and
        ``ProviderCapabilities.missing`` cannot serve as one either: ``real_plant`` fills it with
        data-kind names (``"current_state"``, ``"truth_state"``) while ``synthetic`` and the test
        stub fill it with capability-*flag* names (``"history"``, ``"truth"``), so a membership test
        would silently never fire for one of the two vocabularies.

        The gate is therefore the contract's own refusal, which is the one signal both vocabularies
        agree on: :class:`~src.digital_twin.provider.CapabilityError` is documented as the type
        "the dashboard can catch to render the 'not available from this data source' state", and
        PRD 26.1 has :class:`~src.digital_twin.real_plant.RealPlantDataProvider` refuse with its
        parent ``NotImplementedError``, so catching the parent covers both. This is the same
        "catch the refusal and degrade" pattern :meth:`_advance_steps`, :meth:`reset` and
        :meth:`scenarios` already use below.

        A source that will not report a position gets ``None`` - an absence, not a substituted
        value. Nothing is fabricated and nothing falls back to another provider.
        """
        try:
            return self._provider.get_current_state().timestamp
        except NotImplementedError:
            return None

    # -- mode-aware settings -----------------------------------------------------------------
    def _mode_clock(self) -> ClockSettings | ReplaySettings:
        """The speed list / step size / (LIVE) budget for whichever mode is being served.

        LIVE reads :class:`ClockSettings`, REPLAY reads :class:`ReplaySettings`; both expose
        ``speeds``, ``default_speed`` and ``step_minutes``, so the transport logic is written once
        and the per-mode numbers stay in the YAML.
        """
        return self._settings.clock if self._provider.mode == LIVE else self._settings.replay

    def _step_minutes(self) -> float:
        return float(self._mode_clock().step_minutes)

    # -- position (derived from the ABC surface only, never from synthetic-only helpers) ------
    def _sync(self, snapshot: StateSnapshot | None) -> None:
        """Cache the position after a provider call so :meth:`state` needs no extra read.

        ``advance``/``seek`` hand back the new snapshot; ``reset`` returns nothing, so the caller
        passes ``None`` and we ask the provider once for the fresh timestamp - through
        :meth:`_read_position`, so a source that refuses the read degrades here exactly as it does
        at construction instead of turning RESET into a crash.
        """
        if snapshot is None:
            self._last_timestamp = self._read_position()
            return
        self._last_timestamp = snapshot.timestamp

    def _replay_position(self) -> tuple[int, int, float, bool, bool]:
        """``(step_index, step_count, fraction, at_start, at_end)`` for REPLAY, from the window.

        Derived from :meth:`~DataProvider.window` (the recorded span) and the cached current
        timestamp, converted to a count of ``step_minutes``-sized samples. Uniform sampling is a
        PRD 12 guarantee, so timestamp arithmetic and an index count agree.

        A source with no window, or one that reports no position at all, has nothing to measure:
        both collapse to the single degenerate sample below rather than to ``NaT`` arithmetic, which
        would render as a ``NaN`` scrubber fraction - a fabricated number, which item 20 forbids.
        """
        window = self._provider.window()
        step_min = self._step_minutes()
        if window is None or self._last_timestamp is None:
            return 1, 1, 0.0, True, True
        first, last = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        current = pd.Timestamp(self._last_timestamp)
        span_minutes = (last - first) / _ONE_MINUTE
        count = int(round(span_minutes / step_min)) + 1 if span_minutes > 0 else 1
        raw_index = int(round(((current - first) / _ONE_MINUTE) / step_min))
        index = max(0, min(count - 1, raw_index))
        fraction = 0.0 if span_minutes <= 0 else _clamp01((current - first) / (last - first))
        return index + 1, count, fraction, index <= 0, index >= count - 1

    def _live_position(self) -> tuple[int, int, float, bool, bool]:
        """``(step_index, step_count, fraction, at_start, at_end)`` for LIVE, from the budget.

        A live source has no recorded window to measure against (``window()`` is ``None``); the
        progress bar instead measures the session against ``clock.max_live_steps`` - the directive
        item 7 "a session holds so many simulated minutes" budget the controller owns. That budget
        counts the *samples* a session may show, and the first sample is the opening state the
        provider rendered before any advance, so the number of advances a session permits is one
        fewer than the budget - which is exactly where the source's own step guard stops.
        """
        budget = max(1, int(self._settings.clock.max_live_steps))
        last_advance = budget - 1  # advances allowed; sample 1 is the opening render
        spent = min(self._live_steps, last_advance)
        fraction = _clamp01(spent / last_advance) if last_advance > 0 else 1.0
        at_end = spent >= last_advance or self._ended
        return spent + 1, budget, fraction, spent <= 0, at_end

    def _position(self) -> tuple[int, int, float, bool, bool]:
        return self._live_position() if self._provider.mode == LIVE else self._replay_position()

    # -- capability gating (which controls the dashboard may enable) --------------------------
    def _has_replay(self) -> bool:
        return self._provider.mode == REPLAY and self._provider.window() is not None

    def _can_advance(self) -> bool:
        """Whether stepping forward is meaningful: a live clock with budget left, or a replay."""
        if self._provider.mode == LIVE:
            return bool(self._provider.capabilities().live)
        return self._has_replay()

    # -- the read-only view the dashboard renders from ----------------------------------------
    def state(self) -> ClockState:
        """The current :class:`ClockState`. Pure: it reads cached position, advances nothing."""
        mode = self._provider.mode
        modes = self._provider.modes()
        step_index, step_count, fraction, at_start, at_end = self._position()
        can_advance = self._can_advance()
        return ClockState(
            mode=mode,
            modes=modes,
            playing=self._playing,
            speed=self._speed,
            speeds=tuple(self._mode_clock().speeds),
            step_minutes=self._step_minutes(),
            timestamp=self._last_timestamp,
            step_index=step_index,
            step_count=step_count,
            fraction=fraction,
            at_start=at_start,
            at_end=at_end,
            can_play=can_advance and not at_end,
            can_step_back=self._has_replay() and not at_start,
            can_scrub=self._has_replay(),
            can_reset=can_advance or self._has_replay(),
            can_switch_mode=len(modes) > 1,
        )

    def describe(self) -> dict[str, Any]:
        return self.state().describe()

    # -- transport: play / pause -------------------------------------------------------------
    def play(self) -> ClockState:
        """Press PLAY. Refuses to start at the end of the session - RESET restarts, PLAY does not."""
        _, _, _, _, at_end = self._position()
        if self._can_advance() and not at_end:
            self._playing = True
        return self.state()

    def pause(self) -> ClockState:
        """Press PAUSE. Drops the fractional accumulator so resuming does not lurch forward."""
        self._playing = False
        self._pending = 0.0
        return self.state()

    def toggle(self) -> ClockState:
        """The single PLAY/PAUSE button: pause if playing, else play."""
        return self.pause() if self._playing else self.play()

    def set_playing(self, playing: bool) -> ClockState:
        return self.play() if playing else self.pause()

    # -- transport: the timer beat -----------------------------------------------------------
    def tick(self, beats: float = 1.0) -> ClockState:
        """One (or ``beats``) timer beats elapsed: advance ``speed x beats`` steps if playing.

        This is the only method the dashboard's timer calls. When paused, or when the position is
        already at the end, it advances nothing and simply reports state. Fractional steps left
        over from sub-``1x`` speeds are kept in :attr:`_pending` and advanced once they sum to a
        whole sample, so ``0.25x`` advances on every fourth beat rather than never.
        """
        if not self._playing or beats <= 0.0:
            return self.state()
        self._pending += self._speed * float(beats)
        whole = int(self._pending)  # floor for non-negative accumulator
        if whole >= 1:
            self._pending -= whole
            self._advance_steps(whole)
        # PLAY stops itself at the endpoint so the button flips back to PLAY without user action.
        if self._position()[4]:  # at_end
            self._playing = False
            self._pending = 0.0
        return self.state()

    # -- transport: STEP -----------------------------------------------------------------------
    def step_forward(self, steps: int = 1) -> ClockState:
        """STEP forward one sample (directive item 7). Pauses first: a step is a manual nudge."""
        self._playing = False
        self._pending = 0.0
        self._advance_steps(max(1, int(steps)))
        return self.state()

    def step_back(self, steps: int = 1) -> ClockState:
        """STEP back one sample. REPLAY only - a live clock has no rewind but RESET (directive 8).

        Implemented with :meth:`~DataProvider.seek` at ``current - steps x step_minutes``, clamped
        to the window start, because the provider's step-back is a seek, not a negative advance.
        A source that reports no position has no ``current`` to step back from, so it refuses here
        rather than seeking to ``NaT``.
        """
        self._playing = False
        self._pending = 0.0
        if not self._has_replay() or self._last_timestamp is None:
            return self.state()
        window = self._provider.window()
        first = pd.Timestamp(window[0])
        target = pd.Timestamp(self._last_timestamp) - pd.Timedelta(
            minutes=self._step_minutes() * max(1, int(steps))
        )
        if target < first:
            target = first
        self._sync(self._provider.seek(target))
        return self.state()

    def _advance_steps(self, steps: int) -> None:
        """Advance the provider by ``steps`` samples, honouring the LIVE session budget.

        In LIVE the advance is clamped to what remains of ``clock.max_live_steps`` so a fast speed
        near the end lands exactly on the budget rather than past it; the spent count is the
        controller's own, since a live source keeps no window to measure against. Should the source
        still refuse a further advance (its own step guard is the authority on the budget), that
        refusal is recorded as end-of-session rather than raised, so a timer beat can never crash
        the dashboard loop.
        """
        if steps <= 0 or not self._can_advance():
            return
        if self._provider.mode == LIVE:
            last_advance = max(1, int(self._settings.clock.max_live_steps)) - 1
            remaining = last_advance - self._live_steps
            steps = min(steps, remaining)
            if steps <= 0:
                self._ended = True
                return
            try:
                snapshot = self._provider.advance(minutes=self._step_minutes() * steps)
            except (CapabilityError, ConfigError):
                self._ended = True
                return
            self._live_steps += steps
            self._sync(snapshot)
        else:
            self._sync(self._provider.advance(minutes=self._step_minutes() * steps))

    # -- transport: RESET --------------------------------------------------------------------
    def reset(self) -> ClockState:
        """RESET to the start of the session (directive item 7): pause, zero budget, reseek start."""
        self._playing = False
        self._pending = 0.0
        self._live_steps = 0
        self._ended = False
        try:
            self._provider.reset()
        except CapabilityError:
            pass
        self._sync(None)
        return self.state()

    # -- speed -------------------------------------------------------------------------------
    def set_speed(self, speed: float) -> ClockState:
        """Choose a playback speed. Refuses a speed the current mode does not offer (item 7)."""
        offered = self._mode_clock().speeds
        chosen = float(speed)
        if chosen not in offered:
            raise ValueError(
                f"speed {chosen!r} is not one of the {self._provider.mode} speeds {list(offered)}"
            )
        self._speed = chosen
        self._pending = 0.0
        return self.state()

    # -- scrubber (REPLAY, directive item 8) --------------------------------------------------
    def seek_fraction(self, fraction: float) -> ClockState:
        """Move the scrubber to a fraction of the recorded window. Pauses; REPLAY only.

        The fraction is turned into a timestamp inside the window and handed to
        :meth:`~DataProvider.seek`; the provider snaps it to the nearest recorded row.
        """
        self._playing = False
        self._pending = 0.0
        if not self._has_replay():
            return self.state()
        window = self._provider.window()
        first, last = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        target = first + (last - first) * _clamp01(float(fraction))
        self._sync(self._provider.seek(target))
        return self.state()

    def seek(self, timestamp: Any) -> ClockState:
        """Seek to an explicit timestamp (what a scrubber wired to real timestamps hands back)."""
        self._playing = False
        self._pending = 0.0
        if not self._has_replay():
            return self.state()
        self._sync(self._provider.seek(timestamp))
        return self.state()

    # -- mode + scenarios --------------------------------------------------------------------
    def set_mode(self, mode: str) -> ClockState:
        """Switch LIVE <-> REPLAY (directive items 7/8). Resets transport intent to that mode's default."""
        self._provider.set_mode(mode)  # raises CapabilityError for a single-mode source
        self._playing = False
        self._pending = 0.0
        self._live_steps = 0
        self._ended = False
        self._speed = self._mode_clock().default_speed
        self._sync(None)
        return self.state()

    def scenarios(self) -> tuple[Mapping[str, Any], ...]:
        """The selectable driving scenarios (directive item 18), or empty if the source has none."""
        try:
            return self._provider.scenarios()
        except CapabilityError:
            return ()

    def select_scenario(self, scenario: str) -> ClockState:
        """Switch the driving scenario (directive item 18); pauses and returns to session start."""
        self._playing = False
        self._pending = 0.0
        self._live_steps = 0
        self._ended = False
        self._provider.select_scenario(scenario)  # raises CapabilityError if unsupported
        self._sync(None)
        return self.state()


__all__ = ["Clock", "ClockState"]
