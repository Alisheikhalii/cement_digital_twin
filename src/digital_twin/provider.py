"""The ``DataProvider`` contract (PRD v1.1.1 Sections 8.5, 26; FR-14, FR-20).

This is the only surface the dashboard, the presentation mode and the demo sequence are allowed
to read. Nothing above this line imports :mod:`src.process_models`, :mod:`src.simulation`,
:mod:`src.models` or :mod:`src.optimization`, and nothing above it opens a CSV or a Parquet file
- which is the whole point of FR-14: replacing the synthetic source with a plant historian must
change one class and no view.

Two methods are the PRD 26.1 contract verbatim (:meth:`DataProvider.get_timeseries`,
:meth:`DataProvider.get_tag_metadata`). The rest are Task #6 directive item 1's ten data kinds -
current process state, historical series, equipment status, KPI values, sensor values, operating
regime, anomaly state, model predictions, optimization results, what-if results - each returning
one of the provenance-tagged payloads so the four sources can never be mixed in a panel.

Clock control (:meth:`advance`, :meth:`reset`, :meth:`select_scenario`, :meth:`seek`) is
*optional*: it is concrete here and refuses with :class:`CapabilityError` unless a provider
overrides it. A dashboard therefore drives simulated time by asking the provider, never by
touching a process model, and a provider that has no simulated time to drive stays valid.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Final, Mapping, Sequence

import pandas as pd

from src.digital_twin.insights import AnomalyState, OptimizationView, PredictionSet, WhatIfView
from src.digital_twin.payloads import (
    LIVE,
    EquipmentStatus,
    KpiGroup,
    ProviderCapabilities,
    RegimeState,
    Series,
    StateSnapshot,
)
from src.digital_twin.provenance import Value

#: PRD 26.3 / FR-20: the resample rules a provider must accept.
RESAMPLE_RULES: Final[tuple[str, ...]] = ("1s", "5s", "10s", "30s", "1min", "5min")

#: Seconds per rule, used only to refuse a rule finer than the source's own sampling interval.
RESAMPLE_SECONDS: Final[Mapping[str, float]] = {
    "1s": 1.0, "5s": 5.0, "10s": 10.0, "30s": 30.0, "1min": 60.0, "5min": 300.0,
}


class CapabilityError(NotImplementedError):
    """Raised when a view asks a provider for something that provider cannot supply.

    A distinct type so the dashboard can catch it and render the "not available from this data
    source" state instead of a number it does not have.
    """


class DataProvider(ABC):
    """One data source, in the only shape the application layer knows how to read."""

    #: Human-readable name of the source, shown in the dashboard header.
    name: str = "DataProvider"

    # -- PRD 26.1: the two mandated methods -------------------------------------------------
    @abstractmethod
    def get_timeseries(
        self,
        tags: Sequence[str],
        start: datetime,
        end: datetime,
        resample: str | None = None,
    ) -> pd.DataFrame:
        """Historical rows of ``tags`` in ``[start, end]``, optionally resampled (FR-20)."""

    @abstractmethod
    def get_tag_metadata(self) -> pd.DataFrame:
        """One row per tag: unit, description, expected range, sampling interval (PRD 26.1)."""

    # -- directive item 1: the ten data kinds -----------------------------------------------
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """What this provider can answer, so a view degrades instead of failing."""

    @abstractmethod
    def get_current_state(self, dataset: str | None = None) -> StateSnapshot:
        """Current process state as the *instruments* report it (observable channel only)."""

    @abstractmethod
    def get_truth_state(self, dataset: str | None = None) -> StateSnapshot:
        """The simulator's own noise-free state. Synthetic sources only."""

    @abstractmethod
    def get_sensor_values(self, tags: Sequence[str]) -> tuple[Value, ...]:
        """Named sensor readings at the current position, with unit, range and status."""

    @abstractmethod
    def get_history(
        self,
        tags: Sequence[str],
        *,
        minutes: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        max_points: int | None = None,
        truth: bool = False,
    ) -> tuple[Series, ...]:
        """Downsampled trends for the UI (directive item 23: never the raw window)."""

    @abstractmethod
    def get_equipment_status(self) -> tuple[EquipmentStatus, ...]:
        """Every PRD-defined equipment item, its state, health and driving variable."""

    @abstractmethod
    def get_kpis(self) -> tuple[KpiGroup, ...]:
        """The KPI groups of directive item 9 - kiln, mill and plant."""

    @abstractmethod
    def get_operating_regime(self) -> RegimeState:
        """The operating regime label of the current position (PRD 11.4)."""

    @abstractmethod
    def get_anomaly_state(self, dataset: str = "kiln") -> AnomalyState:
        """Model B's output for the current row (PRD 15)."""

    @abstractmethod
    def get_predictions(self, dataset: str = "kiln") -> PredictionSet:
        """Model A's multi-horizon output for the current row (PRD 13.1)."""

    @abstractmethod
    def get_optimization(self, *, mode: str = "NORMAL") -> OptimizationView:
        """Model C's run at the current operating point (PRD 14)."""

    @abstractmethod
    def run_what_if(
        self,
        changes: Mapping[str, float] | None = None,
        *,
        delta_fractions: Mapping[str, float] | None = None,
        mode: str = "NORMAL",
    ) -> WhatIfView:
        """One what-if answer at the current operating point (PRD 16)."""

    @abstractmethod
    def what_if_sliders(self, *, mode: str = "NORMAL") -> tuple[Mapping[str, Any], ...]:
        """Slider bounds and step for every manipulated variable (PRD 16.1)."""

    # -- optional clock control -------------------------------------------------------------
    #: Playback mode currently being served: :data:`payloads.LIVE` (a clock the dashboard steps)
    #: or :data:`payloads.REPLAY` (a recorded window it scrubs). A source that has only one of
    #: the two leaves this fixed and :meth:`set_mode` refusing, which is how the dashboard learns
    #: whether to draw a PLAY button or a scrubber without knowing what is behind the contract.
    mode: str = LIVE

    def modes(self) -> tuple[str, ...]:
        """The playback modes this source can serve (directive items 7 and 8)."""
        return (self.mode,)

    def set_mode(self, mode: str) -> None:
        """Switch playback mode. Refuses unless the source holds both kinds of data."""
        raise CapabilityError(f"{self.name} serves {self.mode} data only")

    def advance(self, minutes: float = 1.0) -> StateSnapshot:
        """Advance simulated time and return the new observable state."""
        raise CapabilityError(f"{self.name} has no simulated clock to advance")

    def reset(self) -> None:
        """Return to the start of the session (RESET, directive item 7)."""
        raise CapabilityError(f"{self.name} has no simulated clock to reset")

    def scenarios(self) -> tuple[Mapping[str, Any], ...]:
        """The selectable scenarios, taken from configuration only (directive item 18)."""
        raise CapabilityError(f"{self.name} exposes no scenarios")

    def select_scenario(self, scenario: str) -> None:
        """Switch the driving scenario (directive item 18)."""
        raise CapabilityError(f"{self.name} exposes no scenarios")

    def seek(self, timestamp: Any) -> StateSnapshot:
        """Move the historical replay position (directive item 8)."""
        raise CapabilityError(f"{self.name} has no replayable history")

    def window(self) -> tuple[Any, Any] | None:
        """First and last timestamp available for replay, or ``None`` if there is none."""
        return None

    # -- shared, non-overridable plumbing ---------------------------------------------------
    @staticmethod
    def check_resample(resample: str | None, *, native_seconds: float | None = None) -> str | None:
        """Validate a resample rule against FR-20's list and the source's own interval.

        A rule finer than the source's sampling interval is refused rather than interpolated: a
        provider must not manufacture samples that were never measured.
        """
        if resample is None:
            return None
        rule = str(resample)
        if rule not in RESAMPLE_RULES:
            raise ValueError(
                f"resample={rule!r} is not one of the FR-20 rules {list(RESAMPLE_RULES)}"
            )
        if native_seconds is not None and RESAMPLE_SECONDS[rule] < float(native_seconds):
            raise ValueError(
                f"resample={rule!r} is finer than this source's {native_seconds:g} s sampling "
                "interval; upsampling would invent samples that were never measured"
            )
        return rule

    def require(self, capability: str) -> None:
        """Raise :class:`CapabilityError` unless ``capability`` is advertised as available."""
        state = self.capabilities().describe().get(capability)
        if not state:
            raise CapabilityError(
                f"{self.name} does not provide {capability!r}; "
                "the view must render its unavailable state instead"
            )

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "capabilities": self.capabilities().describe()}


__all__ = ["RESAMPLE_RULES", "RESAMPLE_SECONDS", "CapabilityError", "DataProvider"]
