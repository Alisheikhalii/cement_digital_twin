"""Provenance-tagged values (PRD v1.1.1 Sections 26, 17-19; FR-14, NFR-6, AC-12).

Task #6 directive item 1 requires the payload to *keep four sources apart*:

1. ``OBSERVED``       - what an instrument would report (sensor model applied, PRD 11.5)
2. ``TRUTH``          - the simulator's own noise-free state (synthetic only, PRD 11.2)
3. ``PREDICTION``     - Model A output (PRD 13.1)
4. ``RECOMMENDATION`` - Model C output (PRD 14)

:data:`DATA_SOURCES` is exactly those four. ``CONFIGURATION`` is a fifth member that marks
static engineering metadata - a tag's unit, its documented range, a configured target - which is
not a *data* source at all; it is what the panel labels the data with. The
``no_mixed_provenance`` test asserts that no payload channel carries two of the four data
sources at once, and that every displayed number carries one of the five.

A :class:`Value` is the only object the UI is allowed to render as a number: it arrives with its
unit, its range, its status and the call that produced it, so a panel never has to know a limit
and can never hold a literal (NFR-6).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Iterable, Mapping

from src import schema


class Provenance(StrEnum):
    """Where one displayed number came from (directive item 1)."""

    OBSERVED = "OBSERVED_SENSOR"
    TRUTH = "SIMULATOR_TRUTH"
    PREDICTION = "MODEL_PREDICTION"
    RECOMMENDATION = "OPTIMIZATION_RECOMMENDATION"
    CONFIGURATION = "CONFIGURATION"


#: The four data sources of directive item 1. ``CONFIGURATION`` is metadata, not data.
DATA_SOURCES: Final[tuple[Provenance, ...]] = (
    Provenance.OBSERVED,
    Provenance.TRUTH,
    Provenance.PREDICTION,
    Provenance.RECOMMENDATION,
)

#: The badge each source is drawn with. Wording is fixed here so no view can soften it.
PROVENANCE_LABELS: Final[Mapping[Provenance, str]] = {
    Provenance.OBSERVED: "Observed (simulated sensor)",
    Provenance.TRUTH: "Simulator truth",
    Provenance.PREDICTION: "Model prediction",
    Provenance.RECOMMENDATION: "AI recommendation",
    Provenance.CONFIGURATION: "Configuration",
}


class Status(StrEnum):
    """PRD 17.1 alarm colour coding, as a state rather than a colour."""

    OK = "OK"
    WARN = "WARNING"
    ALARM = "ALARM"
    NO_LIMIT = "NO_LIMIT"
    UNKNOWN = "UNKNOWN"


def status_for(
    value: float | None,
    range_min: float | None,
    range_max: float | None,
    *,
    warn_fraction: float,
) -> Status:
    """Band one value against limits that were handed in, never invented here.

    ``warn_fraction`` is ``status.warn_fraction_of_span`` from ``configs/dashboard.yaml``: the
    amber band, measured inward from each limit as a fraction of the span. The limits themselves
    come from :mod:`src.schema` (documented operating range) or the unit's own ``constraints``
    block - this function adds no engineering limit of its own.
    """
    if value is None or value != value:  # NaN-safe
        return Status.UNKNOWN
    if range_min is None or range_max is None:
        return Status.NO_LIMIT
    low, high = float(range_min), float(range_max)
    if low > high:
        low, high = high, low
    if value < low or value > high:
        return Status.ALARM
    band = abs(high - low) * float(warn_fraction)
    if band > 0.0 and (value - low < band or high - value < band):
        return Status.WARN
    return Status.OK


@dataclass(frozen=True, slots=True)
class Value:
    """One number a panel may render, with everything the panel needs to render it.

    ``source`` names the call that produced the number (``"kiln_raw[t]"``,
    ``"PlantTwin.current_state_snapshot"``, ``"model_a/<target>/t+15min"``). It is what the
    NFR-6 static scan follows: a panel renders ``Value.value``, so the number's origin is always
    one hop away and never a literal.
    """

    tag: str
    value: float | None
    unit: str
    provenance: Provenance
    source: str
    description: str = ""
    range_min: float | None = None
    range_max: float | None = None
    target: float | None = None
    status: Status = Status.UNKNOWN
    uncertainty: float | None = None
    horizon_min: int | None = None

    @property
    def label(self) -> str:
        return PROVENANCE_LABELS[self.provenance]

    @property
    def interval(self) -> tuple[float, float] | None:
        """``value +/- uncertainty`` - an ensemble spread (PRD 13.1.1), never a confidence %."""
        if self.value is None or self.uncertainty is None:
            return None
        return (self.value - self.uncertainty, self.value + self.uncertainty)

    def fraction_of_range(self) -> float | None:
        """Where the value sits in its own documented range, clamped to ``[0, 1]``.

        This is the single scaling function the animation uses (PRD 19.4): an animation
        parameter is ``f(fraction_of_range())``, so it is a function of state by construction.
        """
        if self.value is None or self.range_min is None or self.range_max is None:
            return None
        low, high = float(self.range_min), float(self.range_max)
        if high == low:
            return None
        return max(0.0, min(1.0, (float(self.value) - low) / (high - low)))

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "value": self.value,
            "unit": self.unit,
            "provenance": str(self.provenance),
            "provenance_label": self.label,
            "source": self.source,
            "description": self.description,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "target": self.target,
            "status": str(self.status),
            "uncertainty": self.uncertainty,
            "uncertainty_interval": list(self.interval) if self.interval else None,
            "horizon_min": self.horizon_min,
        }


def value_from_tag(
    tag: str,
    value: float | None,
    *,
    provenance: Provenance,
    source: str,
    dataset: str | None = None,
    warn_fraction: float,
    range_min: float | None = None,
    range_max: float | None = None,
    banded: bool = True,
    target: float | None = None,
    uncertainty: float | None = None,
    horizon_min: int | None = None,
) -> Value:
    """Build a :class:`Value` taking unit, description and range from :mod:`src.schema`.

    ``range_min``/``range_max`` override the documented range only when the caller has a
    *tighter* authority for it - a unit's own ``constraints`` block. Nothing else may pass them.

    ``banded=False`` says the caller knows of *no* range this value may honestly be judged
    against, and suppresses the :mod:`src.schema` fallback so the result carries
    :attr:`Status.NO_LIMIT` instead of a verdict. It exists for the documented-range deviations of
    ``SIMULATION_ASSUMPTIONS.md`` Section 8: where a PRD 12.1 band cannot hold simultaneously with
    the PRD 9-10 equations, the physics was kept and the band was not, so the *nominal* operating
    point already sits outside the documented band. Colouring such a tag red would report a
    permanent excursion that is not happening; widening the band in the UI would invent an
    engineering limit (directive item 5 forbids exactly that). Showing the number with no verdict,
    and saying why, is the only honest third option.
    """
    spec = schema.get_tag(tag, dataset) if schema.has_tag(tag, dataset) else None
    fallback_min = (spec.range_min if spec else None) if banded else None
    fallback_max = (spec.range_max if spec else None) if banded else None
    low = range_min if range_min is not None else fallback_min
    high = range_max if range_max is not None else fallback_max
    return Value(
        tag=tag,
        value=None if value is None else float(value),
        unit=spec.unit if spec else "",
        provenance=provenance,
        source=source,
        description=spec.description if spec else "",
        range_min=low,
        range_max=high,
        target=target,
        status=status_for(value, low, high, warn_fraction=warn_fraction),
        uncertainty=uncertainty,
        horizon_min=horizon_min,
    )


def sources_of(values: Iterable[Value]) -> frozenset[Provenance]:
    """The provenance set of a payload channel - what the no-mixing test inspects."""
    return frozenset(item.provenance for item in values)


def data_sources_of(values: Iterable[Value]) -> frozenset[Provenance]:
    """Same, restricted to the four sources of directive item 1."""
    return frozenset(item for item in sources_of(values) if item in DATA_SOURCES)


__all__ = [
    "DATA_SOURCES",
    "PROVENANCE_LABELS",
    "Provenance",
    "Status",
    "Value",
    "data_sources_of",
    "sources_of",
    "status_for",
    "value_from_tag",
]
