"""Provider payload types (PRD v1.1.1 Section 26; Task #6 directive item 1).

The ten things a view may ask a provider for are these dataclasses and the two in
:mod:`src.digital_twin.insights`. They are plain, frozen and JSON-describable so that the
rendering layer can only *read* them: a view holds no process object, calls no model and owns no
limit. Every number inside is a :class:`~src.digital_twin.provenance.Value`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Iterable, Mapping, Sequence

from src.digital_twin.provenance import Provenance, Status, Value, data_sources_of

#: Values a live/replay clock can be in - the provider reports which one produced a snapshot.
LIVE: Final = "LIVE"
REPLAY: Final = "REPLAY"


@dataclass(frozen=True, slots=True)
class Series:
    """One downsampled trend channel (directive item 23: never stream the raw window)."""

    tag: str
    unit: str
    timestamps: tuple[str, ...]
    values: tuple[float | None, ...]
    provenance: Provenance
    source: str
    points_available: int
    method: str = "none"
    range_min: float | None = None
    range_max: float | None = None

    @property
    def points(self) -> int:
        return len(self.values)

    @property
    def downsampled(self) -> bool:
        return self.points_available > self.points

    def finite(self) -> tuple[float, ...]:
        return tuple(v for v in self.values if v is not None and v == v)

    def describe(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "unit": self.unit,
            "points": self.points,
            "points_available": self.points_available,
            "downsampled": self.downsampled,
            "method": self.method,
            "provenance": str(self.provenance),
            "source": self.source,
            "first_timestamp": self.timestamps[0] if self.timestamps else None,
            "last_timestamp": self.timestamps[-1] if self.timestamps else None,
        }


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """The current process state as one source sees it (observed *or* truth, never both)."""

    timestamp: str
    mode: str
    provenance: Provenance
    source: str
    values: Mapping[str, Value] = field(default_factory=dict)

    def value(self, tag: str) -> Value | None:
        return self.values.get(tag)

    def of(self, *tags: str) -> tuple[Value, ...]:
        """The requested tags, skipping any this snapshot does not carry."""
        return tuple(self.values[tag] for tag in tags if tag in self.values)

    def mixed_sources(self) -> bool:
        """True if this channel mixes two of the four data sources (must never happen)."""
        return len(data_sources_of(self.values.values())) > 1

    def describe(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "provenance": str(self.provenance),
            "source": self.source,
            "tags": len(self.values),
            "values": {tag: item.describe() for tag, item in self.values.items()},
        }


@dataclass(frozen=True, slots=True)
class EquipmentStatus:
    """One piece of PRD-defined equipment: its state, its health and its driving variable.

    ``kind`` is drawn from the PRD 8.2/8.3 equipment list only - no invented equipment
    (directive item 2). ``driver`` is the value the animated twin scales that item's motion by,
    which is why it is a :class:`Value` and not a float (AC-21).
    """

    name: str
    unit: str
    kind: str
    state: str
    health: float
    driver: Value | None = None
    detail: str = ""
    constraints: tuple[Value, ...] = ()

    @property
    def status(self) -> Status:
        if self.driver is None:
            return Status.UNKNOWN
        return self.driver.status

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "kind": self.kind,
            "state": self.state,
            "health": self.health,
            "status": str(self.status),
            "detail": self.detail,
            "driver": self.driver.describe() if self.driver else None,
            "constraints": [item.describe() for item in self.constraints],
        }


@dataclass(frozen=True, slots=True)
class KpiGroup:
    """One labelled group of KPI cards (directive item 9)."""

    title: str
    values: tuple[Value, ...]
    note: str = ""

    def describe(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "note": self.note,
            "values": [item.describe() for item in self.values],
        }


@dataclass(frozen=True, slots=True)
class RegimeState:
    """The operating regime a snapshot belongs to (PRD 11.4 label, never a model output)."""

    label: str
    regime_id: int | None
    injected_fault: str | None
    provenance: Provenance
    source: str
    sensor_layer_only: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "regime_id": self.regime_id,
            "injected_fault": self.injected_fault,
            "sensor_layer_only": self.sensor_layer_only,
            "provenance": str(self.provenance),
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can answer, so a view degrades instead of crashing (directive item 1).

    A ``RealPlantDataProvider`` will report ``truth=False`` and, until its plant historian is
    wired up, ``history=False`` - the dashboard must stay renderable in both cases, which is what
    makes the provider genuinely replaceable.
    """

    name: str
    synthetic: bool
    truth: bool
    history: bool
    live: bool
    predictions: bool
    anomaly: bool
    optimization: bool
    what_if: bool
    missing: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "synthetic": self.synthetic,
            "truth": self.truth,
            "history": self.history,
            "live": self.live,
            "predictions": self.predictions,
            "anomaly": self.anomaly,
            "optimization": self.optimization,
            "what_if": self.what_if,
            "missing": list(self.missing),
        }


def group(title: str, values: Iterable[Value], note: str = "") -> KpiGroup:
    """Build a KPI group, dropping tags the current provider cannot supply."""
    return KpiGroup(title=title, values=tuple(v for v in values if v is not None), note=note)


def series_from(
    tag: str,
    timestamps: Sequence[Any],
    values: Sequence[Any],
    *,
    provenance: Provenance,
    source: str,
    unit: str,
    points_available: int,
    method: str,
    range_min: float | None = None,
    range_max: float | None = None,
) -> Series:
    return Series(
        tag=tag,
        unit=unit,
        timestamps=tuple(str(stamp) for stamp in timestamps),
        values=tuple(None if value is None or value != value else float(value) for value in values),
        provenance=provenance,
        source=source,
        points_available=int(points_available),
        method=method,
        range_min=range_min,
        range_max=range_max,
    )


__all__ = [
    "LIVE",
    "REPLAY",
    "EquipmentStatus",
    "KpiGroup",
    "ProviderCapabilities",
    "RegimeState",
    "Series",
    "StateSnapshot",
    "group",
    "series_from",
]
