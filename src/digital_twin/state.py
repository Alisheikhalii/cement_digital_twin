"""The Dashboard API / State layer (PRD v1.1.1 Section 26; Task #6 directive items 1-21).

This module is the one the views read. It sits above the :class:`~src.digital_twin.provider.
DataProvider` contract and the :class:`~src.visualization.clock.Clock`, and below the HTML/SVG
renderer, and its single job is to turn what a provider can answer into the ten *view models* the
dashboard draws - one per screen A-J - without emitting a byte of HTML. That division is the whole
of item 21's clean architecture: a view model is a plain, frozen, JSON-describable object, so a
test can assert against the numbers a screen will show without a browser, and a renderer can only
*read* a view model - it holds no process object, calls no model and owns no limit.

Four rules hold for everything built here, and each is a directive requirement rather than a style
choice:

* **One provider, kept apart (item 1).** Every number reaches a view as a
  :class:`~src.digital_twin.provenance.Value`, and the four data sources - observed, truth,
  prediction, recommendation - are never merged inside one channel. A :class:`Panel` is one
  channel; a prediction's *current* column (observed) and its *horizon* columns (prediction) are
  two. :func:`mixed_channels` walks a finished view model and returns any channel that broke the
  rule, so the item 22 test is a one-liner.
* **No literal, no invented limit (NFR-6, items 5/6).** A panel is a selection of tags declared in
  :mod:`src.digital_twin.layout`; its ranges, statuses and targets are the ones the provider
  already put on each :class:`Value`. Nothing here writes an engineering number, a threshold or a
  KPI the implementation does not produce.
* **Degrade, never crash (item 1, NFR-6).** A ``RealPlantDataProvider`` that reports
  ``predictions=False`` or ``history=False`` must still render every screen. Optional surfaces are
  guarded by :meth:`~src.digital_twin.provider.DataProvider.capabilities` and by catching
  :class:`~src.digital_twin.provider.CapabilityError`, falling back to the payloads' own
  ``unavailable`` states - a stated absence, not a substituted number.
* **Honesty wording is fixed (item 20).** Every header carries the
  :data:`~src.labels.SYNTHETIC_DEMONSTRATION_LABEL` badge, every decision-support screen carries
  the AI-recommendation and decision-support labels and the simulated-saving caveat, and the
  standing limitations live in the session-level :class:`Footer`. All of it comes from
  :mod:`src.labels`, so no view can soften it.

Coherence across a single frame is why the state layer fetches the current observed snapshot, the
equipment, the KPIs and the regime *once* into a :class:`_Frame` and shares it across the ten
views: two reads of a noisy sensor channel could disagree, and a dashboard drawn from disagreeing
reads is not one dashboard. Model outputs (prediction, anomaly, optimization, what-if) and trends
are per-view, because each is its own answer with its own timestamp.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from src import labels
from src.digital_twin import layout
from src.digital_twin.insights import (
    AnomalyState,
    OptimizationView,
    PredictionSet,
    WhatIfView,
    horizon_labels,
)
from src.digital_twin.payloads import (
    EquipmentStatus,
    KpiGroup,
    ProviderCapabilities,
    RegimeState,
    Series,
    StateSnapshot,
)
from src.digital_twin.provenance import Provenance, Value, data_sources_of
from src.digital_twin.provider import CapabilityError, DataProvider
from src.digital_twin.settings import DashboardSettings
from src.visualization.clock import Clock, ClockState

# =============================================================================
# The ten screens (directive item 2). id -> key (the method name) -> title -> subtitle.
# =============================================================================
#: Each row is ``(view_id, method_key, title, subtitle)``. The id is the directive's A-J; the key
#: is the :class:`DashboardState` method that builds it, so :meth:`DashboardState.view` can
#: dispatch on either. Titles and subtitles live here, once, rather than restated in each method.
VIEWS: tuple[tuple[str, str, str, str], ...] = (
    ("A", "overview", "Plant Overview", "Quarry / feed → kiln system → clinker → cement mill → product"),
    ("B", "kiln_twin", "Kiln Digital Twin", "Animated process twin — kiln line, driven by simulated state"),
    ("C", "kiln_process", "Preheater & Kiln", "Preheater, precalciner and rotary-kiln detail"),
    ("D", "clinker_cooler", "Clinker Cooler", "Clinker cooler and fuel / fan system detail"),
    ("E", "mill_twin", "Cement Mill Digital Twin", "Animated process twin — closed grinding circuit"),
    ("F", "mill_separator", "Mill & Separator", "Mill, dynamic separator, fan / filter and finished product"),
    ("G", "energy", "Energy Monitoring", "Specific energy (per tonne) and total energy (per day), together"),
    ("H", "intelligence", "AI Prediction & Anomaly", "Model A multi-horizon forecast and Model B anomaly hypothesis"),
    ("I", "what_if", "What-If Simulation", "Operator-set changes evaluated by the validated what-if engine"),
    ("J", "optimization", "AI Optimization", "Decision support only — the system writes no setpoint"),
)

_VIEW_BY_ID: Mapping[str, tuple[str, str, str, str]] = {row[0]: row for row in VIEWS}
_VIEW_BY_KEY: Mapping[str, tuple[str, str, str, str]] = {row[1]: row for row in VIEWS}


# =============================================================================
# Shared view-model pieces
# =============================================================================
@dataclass(frozen=True, slots=True)
class Panel:
    """A titled block of readouts, one :class:`Value` per row (PRD 17.1, items 5/6).

    A panel is *one channel* for the item 1 no-mixing rule: it is the current, observed reading of
    a set of tags declared in :mod:`src.digital_twin.layout`. Each :class:`Value` arrives with its
    own unit, documented range, status and (where the provider set one) target, so the panel holds
    no limit and renders no literal.
    """

    title: str
    values: tuple[Value, ...]
    note: str = ""

    @property
    def data_sources(self) -> frozenset[Provenance]:
        """The four-source set this channel carries - empty or a single element in a valid view."""
        return data_sources_of(self.values)

    @property
    def mixed(self) -> bool:
        return len(self.data_sources) > 1

    def describe(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "note": self.note,
            "values": [item.describe() for item in self.values],
        }


@dataclass(frozen=True, slots=True)
class ViewHeader:
    """The banner every screen shares: what it is, when, and the honesty labels it must carry."""

    view_id: str
    key: str
    title: str
    subtitle: str
    mode: str
    timestamp: str
    badge: str
    regime: RegimeState
    notices: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "key": self.key,
            "title": self.title,
            "subtitle": self.subtitle,
            "mode": self.mode,
            "timestamp": self.timestamp,
            "badge": self.badge,
            "regime": self.regime.describe(),
            "notices": list(self.notices),
        }


@dataclass(frozen=True, slots=True)
class Footer:
    """The session-level footer under every screen (item 20): the standing statements, verbatim."""

    system: str
    statements: tuple[str, ...]
    notes: tuple[str, ...]
    capabilities: ProviderCapabilities

    def describe(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "statements": list(self.statements),
            "notes": list(self.notes),
            "capabilities": self.capabilities.describe(),
        }


# =============================================================================
# View A - Plant Overview
# =============================================================================
@dataclass(frozen=True, slots=True)
class OverviewStageView:
    """One stage of the item 3 chain, and whether its arrow moves.

    ``rate`` is the stage's simulated throughput; ``moving`` is that rate against
    ``animation.min_rate_fraction`` - the same test the twin uses - so the overview animates only a
    stage that is actually flowing (item 3: animation on real relationships only). ``equipment`` is
    the PRD 8.3 components the stage groups, each with its own state.
    """

    name: str
    title: str
    detail: str
    rate: Value | None
    state: str
    moving: bool
    equipment: tuple[EquipmentStatus, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "detail": self.detail,
            "state": self.state,
            "moving": self.moving,
            "rate": self.rate.describe() if self.rate else None,
            "equipment": [item.describe() for item in self.equipment],
        }


@dataclass(frozen=True, slots=True)
class OverviewView:
    """View A: the five-stage chain, the plant KPIs and the whole-plant observed snapshot."""

    header: ViewHeader
    stages: tuple[OverviewStageView, ...]
    plant: KpiGroup
    snapshot: StateSnapshot
    equipment: tuple[EquipmentStatus, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "stages": [stage.describe() for stage in self.stages],
            "plant": self.plant.describe(),
            "snapshot": self.snapshot.describe(),
            "equipment": [item.describe() for item in self.equipment],
        }


# =============================================================================
# Views B / E - the animated digital twin
# =============================================================================
@dataclass(frozen=True, slots=True)
class TwinView:
    """Views B and E: the animated twin plus the line's headline panel and KPIs (items 4-6).

    The twin drawing is whole-plant (the SVG models the whole plant), so ``snapshot`` and
    ``equipment`` are the full observed state; ``line`` says which line this screen foregrounds and
    ``panel`` is that line's manipulated / headline tags with their current / target / range /
    status. Every animated element downstream is a function of ``snapshot`` via
    :meth:`Value.fraction_of_range` - there is no animation input this view model does not carry.
    """

    header: ViewHeader
    line: str
    panel: Panel
    kpis: KpiGroup
    snapshot: StateSnapshot
    equipment: tuple[EquipmentStatus, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "line": self.line,
            "panel": self.panel.describe(),
            "kpis": self.kpis.describe(),
            "snapshot": self.snapshot.describe(),
            "equipment": [item.describe() for item in self.equipment],
        }


# =============================================================================
# Views C / D / F - equipment detail
# =============================================================================
@dataclass(frozen=True, slots=True)
class EquipmentDetail:
    """One component's status card and the readout of its own output tags (item 4 inspector)."""

    status: EquipmentStatus
    readout: Panel

    def describe(self) -> dict[str, Any]:
        return {"status": self.status.describe(), "readout": self.readout.describe()}


@dataclass(frozen=True, slots=True)
class ProcessView:
    """Views C, D and F: the components this screen focuses on, plus grouped process readouts."""

    header: ViewHeader
    components: tuple[EquipmentDetail, ...]
    panels: tuple[Panel, ...]
    kpis: KpiGroup | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "components": [item.describe() for item in self.components],
            "panels": [panel.describe() for panel in self.panels],
            "kpis": self.kpis.describe() if self.kpis else None,
        }


# =============================================================================
# View G - Energy Monitoring
# =============================================================================
@dataclass(frozen=True, slots=True)
class EnergyView:
    """View G: specific and total energy shown together (item 12).

    The provider binds the two into one plant :class:`KpiGroup` under
    :data:`~src.labels.SPECIFIC_VS_TOTAL_NOTE` precisely so a view cannot show the favourable half
    alone. This view model keeps that whole group *and* offers the same numbers partitioned into
    ``specific`` / ``total`` / ``production`` panels for layout - the partition is by tag against
    :data:`~src.digital_twin.layout.DAILY_TOTALS`, never a second computation of the numbers.
    """

    header: ViewHeader
    plant: KpiGroup
    specific: Panel
    total: Panel
    production: Panel
    kiln: KpiGroup
    mill: KpiGroup
    trends: tuple[Series, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "plant": self.plant.describe(),
            "specific": self.specific.describe(),
            "total": self.total.describe(),
            "production": self.production.describe(),
            "kiln": self.kiln.describe(),
            "mill": self.mill.describe(),
            "trends": [series.describe() for series in self.trends],
        }


# =============================================================================
# View H - AI Prediction & Anomaly
# =============================================================================
@dataclass(frozen=True, slots=True)
class PredictionRow:
    """One predicted target across the horizons (item 10).

    ``current`` is the observed value now (:data:`Provenance.OBSERVED`); ``horizon`` is the model's
    forecast at each horizon (:data:`Provenance.PREDICTION`). They are two fields, not one row of
    "values", so the observed and the predicted are never rendered as one series. Uncertainty is
    the ensemble spread carried on each forecast :class:`Value` (``interval``), never a confidence
    percentage.
    """

    target: str
    unit: str
    current: Value | None
    horizon: tuple[Value, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "unit": self.unit,
            "current": self.current.describe() if self.current else None,
            "horizon": [item.describe() for item in self.horizon],
        }


@dataclass(frozen=True, slots=True)
class IntelligenceView:
    """View H: Model A's forecast table and Model B's anomaly hypothesis, kept as two channels.

    ``anomaly`` is a hypothesis, never a diagnosis (item 11); its ``display_cause`` reads "Evidence
    inconclusive" wherever Model B cannot separate an instrument fault from a process deviation -
    the documented sensor-drift limitation, preserved rather than papered over.
    """

    header: ViewHeader
    dataset: str
    predictions: PredictionSet
    anomaly: AnomalyState
    columns: tuple[str, ...]
    rows: tuple[PredictionRow, ...]
    trends: tuple[Series, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "dataset": self.dataset,
            "predictions": self.predictions.describe(),
            "anomaly": self.anomaly.describe(),
            "columns": list(self.columns),
            "rows": [row.describe() for row in self.rows],
            "trends": [series.describe() for series in self.trends],
        }


# =============================================================================
# View I - What-If Simulation
# =============================================================================
@dataclass(frozen=True, slots=True)
class WhatIfViewModel:
    """View I: one what-if answer plus the sliders that produced it (item 13).

    ``sliders`` carry the *exact configured step sizes* the what-if engine offers - the view sets
    changes in those steps and never in a step of its own. ``view`` is the engine's own verdict
    (PASS / REJECTED / NO SAFE RECOMMENDATION), read from the result, not recomputed here.
    """

    header: ViewHeader
    mode: str
    view: WhatIfView
    sliders: tuple[Mapping[str, Any], ...]

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "mode": self.mode,
            "view": self.view.describe(),
            "sliders": [dict(item) for item in self.sliders],
        }


# =============================================================================
# View J - AI Optimization / Decision Support
# =============================================================================
@dataclass(frozen=True, slots=True)
class OptimizationViewModel:
    """View J: the optimizer's recommendation - or its refusal - as decision support only.

    A refusal is a first-class display state (item 16): ``view.refused`` with the blocking gates'
    own reasons, headlined "No safe recommendation found", never an empty card. Recommendation
    confidence is the categorical HIGH / MEDIUM / LOW the optimizer assigned, glossed by
    ``quality_descriptions`` - there is no confidence percentage anywhere (item 14, FR-23).
    """

    header: ViewHeader
    mode: str
    view: OptimizationView
    quality_descriptions: Mapping[str, str]

    def describe(self) -> dict[str, Any]:
        return {
            "header": self.header.describe(),
            "mode": self.mode,
            "view": self.view.describe(),
            "quality_descriptions": dict(self.quality_descriptions),
        }


# =============================================================================
# The per-frame snapshot the ten views share
# =============================================================================
@dataclass(frozen=True, slots=True)
class _Frame:
    """One coherent read of the provider's required surfaces, shared across the ten views.

    Fetched once per render so every screen shows the same instant: the observed snapshot (which
    carries a noise realisation that a second read would not reproduce), the equipment, the three
    KPI groups keyed by title, the operating regime and the clock state.
    """

    snapshot: StateSnapshot
    equipment: tuple[EquipmentStatus, ...]
    kpis: Mapping[str, KpiGroup]
    regime: RegimeState
    clock: ClockState

    def equipment_by_name(self) -> dict[str, EquipmentStatus]:
        return {item.name: item for item in self.equipment}

    def kpi(self, title: str) -> KpiGroup:
        """The group with this title, or an empty one so a screen degrades to blank, not crash."""
        return self.kpis.get(title, KpiGroup(title=title, values=()))


# =============================================================================
# DashboardState
# =============================================================================
class DashboardState:
    """Builds the ten view models (A-J) from a provider and a clock, and nothing else.

    Construct it with the two things item 21 says this layer may know - a
    :class:`~src.digital_twin.provider.DataProvider` and a
    :class:`~src.visualization.clock.Clock` - plus the loaded settings and any session notes; or
    use :meth:`from_session`. Each screen has a method returning its frozen view model; a renderer
    reads the model and this class never renders. :meth:`views` builds all ten from one shared
    frame, :meth:`view` dispatches by id or key, and :meth:`footer` / :meth:`clock_state` /
    :meth:`capabilities` give the app shell what wraps every screen.
    """

    def __init__(
        self,
        provider: DataProvider,
        clock: Clock,
        settings: DashboardSettings,
        *,
        notes: Sequence[str] = (),
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._settings = settings
        self._notes = tuple(notes)

    @classmethod
    def from_session(cls, session: Any) -> "DashboardState":
        """Build from a :class:`~src.digital_twin.session.DashboardSession` (its wired provider/clock)."""
        return cls(
            session.provider,
            session.clock,
            session.settings,
            notes=session.notes(),
        )

    # -- session-level surfaces --------------------------------------------------------------
    def clock_state(self) -> ClockState:
        """The transport state the control bar renders from (PLAY / PAUSE / STEP / speed / scrubber)."""
        return self._clock.state()

    def capabilities(self) -> ProviderCapabilities:
        """What this provider can answer, so the shell can grey out a screen it cannot fill."""
        return self._provider.capabilities()

    def footer(self) -> Footer:
        """The standing footer under every screen (item 20): the verbatim limitations, once."""
        return Footer(
            system=labels.full_system_label(),
            statements=(
                labels.NO_PLANT_CONNECTION_STATEMENT,
                labels.LIMITATIONS_STATEMENT,
                labels.TRANSFER_STRATEGY_STATEMENT,
            ),
            notes=self._notes,
            capabilities=self._provider.capabilities(),
        )

    # -- trends (item 23: the provider downsamples; this layer only guards the capability) ---
    def history(self, tags: Sequence[str], *, truth: bool = False) -> tuple[Series, ...]:
        """Full-window trends for ``tags``, or empty if the provider has no history."""
        return self._history(tags, truth=truth)

    def sparklines(self, tags: Sequence[str]) -> tuple[Series, ...]:
        """KPI-card trends: the same read at the card's smaller point budget."""
        return self._history(tags, sparkline=True)

    def _history(
        self, tags: Sequence[str], *, sparkline: bool = False, truth: bool = False
    ) -> tuple[Series, ...]:
        wanted = tuple(str(tag) for tag in tags)
        if not wanted or not self._provider.capabilities().history:
            return ()
        budget = self._settings.history.sparkline_points if sparkline else None
        try:
            return self._provider.get_history(wanted, max_points=budget, truth=truth)
        except CapabilityError:
            return ()

    # -- the shared frame + header ------------------------------------------------------------
    def frame(self) -> _Frame:
        """One coherent read of the required provider surfaces (see :class:`_Frame`)."""
        return _Frame(
            snapshot=self._provider.get_current_state(),
            equipment=self._provider.get_equipment_status(),
            kpis={group.title: group for group in self._provider.get_kpis()},
            regime=self._provider.get_operating_regime(),
            clock=self._clock.state(),
        )

    def _header(
        self,
        view_id: str,
        frame: _Frame,
        *,
        timestamp: str | None = None,
        notices: Sequence[str] = (),
    ) -> ViewHeader:
        _, key, title, subtitle = _VIEW_BY_ID[view_id]
        return ViewHeader(
            view_id=view_id,
            key=key,
            title=title,
            subtitle=subtitle,
            mode=self._provider.mode,
            timestamp=timestamp if timestamp is not None else frame.snapshot.timestamp,
            # Item 20 / B-7: the badge states what the source actually is. It is read from the
            # provider's own ``synthetic`` flag rather than fixed here, because a header printing
            # "Synthetic Demonstration" over a provider reporting ``synthetic=False`` would be a
            # false claim about the data's origin. ``capabilities()`` is a few microseconds and is
            # already read inline elsewhere in this class, so it is not carried on ``_Frame``.
            badge=labels.presentation_card_label(
                "synthetic" if self._provider.capabilities().synthetic else "estimate"
            ),
            regime=frame.regime,
            notices=tuple(notices),
        )

    def _panel(self, title: str, tags: Sequence[str], frame: _Frame, *, note: str = "") -> Panel:
        """A readout panel of ``tags`` from the shared observed snapshot (one channel, observed)."""
        return Panel(title=title, values=frame.snapshot.of(*tags), note=note)

    @staticmethod
    def _stage_state(rate: Value | None, moving: bool) -> str:
        """RUNNING / IDLE / UNKNOWN for an overview stage, read from its throughput (item 3)."""
        if rate is None or rate.value is None:
            return labels.EQUIPMENT_UNKNOWN
        return labels.EQUIPMENT_RUNNING if moving else labels.EQUIPMENT_IDLE

    def _decision_notices(self, mode: str) -> tuple[str, ...]:
        """The honesty labels every decision-support screen carries (items 14, 20).

        In EXPERIMENTAL mode the outside-envelope banner is added, because that mode evaluates
        points outside the calibrated envelope and PRD 14.3/16.1 fixes that banner to every such
        result. The what-if / optimization payloads also carry their own banner; this repeats the
        standing labels at the header so the screen is labelled even before its result is read.
        """
        base = (
            labels.AI_RECOMMENDATION_LABEL,
            labels.DECISION_SUPPORT_LABEL,
            labels.SIMULATED_SAVING_CAVEAT,
        )
        if str(mode).upper() == "EXPERIMENTAL":
            return base + (labels.OUTSIDE_ENVELOPE_BANNER,)
        return base

    # -- view A ------------------------------------------------------------------------------
    def overview(self, frame: _Frame | None = None) -> OverviewView:
        """View A: the Quarry/feed → kiln → clinker → mill → product chain (item 3)."""
        frame = frame or self.frame()
        by_name = frame.equipment_by_name()
        stages: list[OverviewStageView] = []
        for stage in layout.OVERVIEW_CHAIN:
            rate = frame.snapshot.value(stage.rate_tag)
            fraction = rate.fraction_of_range() if rate else None
            moving = self._settings.animation.moving(fraction)
            equipment = tuple(by_name[name] for name in stage.equipment if name in by_name)
            stages.append(
                OverviewStageView(
                    name=stage.name,
                    title=stage.title,
                    detail=stage.detail,
                    rate=rate,
                    state=self._stage_state(rate, moving),
                    moving=moving,
                    equipment=equipment,
                )
            )
        return OverviewView(
            header=self._header("A", frame),
            stages=tuple(stages),
            plant=frame.kpi(layout.PLANT_KPI_TITLE),
            snapshot=frame.snapshot,
            equipment=frame.equipment,
        )

    # -- views B / E -------------------------------------------------------------------------
    def _twin_view(
        self,
        view_id: str,
        line: str,
        panel_tags: Sequence[str],
        kpi_title: str,
        frame: _Frame,
    ) -> TwinView:
        return TwinView(
            header=self._header(view_id, frame),
            line=line,
            panel=self._panel(f"{kpi_title} panel", panel_tags, frame),
            kpis=frame.kpi(kpi_title),
            snapshot=frame.snapshot,
            equipment=frame.equipment,
        )

    def kiln_twin(self, frame: _Frame | None = None) -> TwinView:
        """View B: the animated twin foregrounding the kiln line, plus the kiln panel (items 4-5)."""
        frame = frame or self.frame()
        return self._twin_view(
            "B", layout.KILN_LINE, layout.KILN_PANEL_TAGS, layout.KILN_KPI_TITLE, frame
        )

    def mill_twin(self, frame: _Frame | None = None) -> TwinView:
        """View E: the animated twin foregrounding the grinding circuit, plus the mill panel (item 6)."""
        frame = frame or self.frame()
        return self._twin_view(
            "E", layout.MILL_LINE, layout.MILL_PANEL_TAGS, layout.MILL_KPI_TITLE, frame
        )

    # -- views C / D / F ---------------------------------------------------------------------
    def _equipment_detail(self, name: str, frame: _Frame) -> EquipmentDetail | None:
        """One component's card + its own output-tag readout, or ``None`` if the provider omits it."""
        status = frame.equipment_by_name().get(name)
        if status is None:
            return None
        spec = layout.equipment_spec(name)
        return EquipmentDetail(
            status=status,
            readout=Panel(title=status.unit, values=frame.snapshot.of(*spec.detail)),
        )

    def _components(self, names: Sequence[str], frame: _Frame) -> tuple[EquipmentDetail, ...]:
        return tuple(
            detail
            for detail in (self._equipment_detail(name, frame) for name in names)
            if detail is not None
        )

    def kiln_process(self, frame: _Frame | None = None) -> ProcessView:
        """View C: preheater, precalciner and rotary kiln, with kiln process and emission panels."""
        frame = frame or self.frame()
        return ProcessView(
            header=self._header("C", frame),
            components=self._components(("Preheater", "Precalciner", "RotaryKiln"), frame),
            panels=(
                self._panel("Kiln process indicators", layout.KILN_PROCESS_TAGS, frame),
                self._panel("Kiln emissions", layout.KILN_EMISSION_TAGS, frame),
            ),
            kpis=frame.kpi(layout.KILN_KPI_TITLE),
        )

    def clinker_cooler(self, frame: _Frame | None = None) -> ProcessView:
        """View D: the clinker cooler and the fuel / fan system that feeds the burning zone."""
        frame = frame or self.frame()
        return ProcessView(
            header=self._header("D", frame),
            components=self._components(("Cooler", "FanFuel"), frame),
            panels=(),
            kpis=None,
        )

    def mill_separator(self, frame: _Frame | None = None) -> ProcessView:
        """View F: mill, dynamic separator, fan/filter and finished product, with the mill panel."""
        frame = frame or self.frame()
        return ProcessView(
            header=self._header("F", frame),
            components=self._components(("Mill", "Separator", "FanFilter", "Product"), frame),
            panels=(self._panel("Mill process indicators", layout.MILL_PROCESS_TAGS, frame),),
            kpis=frame.kpi(layout.MILL_KPI_TITLE),
        )

    # -- view G ------------------------------------------------------------------------------
    def energy(self, frame: _Frame | None = None) -> EnergyView:
        """View G: specific and total energy, partitioned but never separated (item 12)."""
        frame = frame or self.frame()
        plant = frame.kpi(layout.PLANT_KPI_TITLE)
        total_tags = {total.tag for total in layout.DAILY_TOTALS}
        specific_tags = {total.intensity_tag for total in layout.DAILY_TOTALS}
        rate_tags = {total.rate_tag for total in layout.DAILY_TOTALS}

        def subset(keep: set[str]) -> tuple[Value, ...]:
            return tuple(value for value in plant.values if value.tag in keep)

        # The intensity tags in the order layout declares them, for a stable trend order.
        specific_order = tuple(total.intensity_tag for total in layout.DAILY_TOTALS)
        return EnergyView(
            header=self._header("G", frame),
            plant=plant,
            specific=Panel(
                "Specific energy (per tonne)", subset(specific_tags), note=labels.SPECIFIC_VS_TOTAL_NOTE
            ),
            total=Panel(
                "Total energy (per day)", subset(total_tags), note=labels.SPECIFIC_VS_TOTAL_NOTE
            ),
            production=Panel("Production", subset(rate_tags)),
            kiln=frame.kpi(layout.KILN_KPI_TITLE),
            mill=frame.kpi(layout.MILL_KPI_TITLE),
            trends=self._history(specific_order),
        )

    # -- view H ------------------------------------------------------------------------------
    def intelligence(self, frame: _Frame | None = None, *, dataset: str = "kiln") -> IntelligenceView:
        """View H: Model A's forecast table and Model B's anomaly hypothesis (items 10-11)."""
        frame = frame or self.frame()
        caps = self._provider.capabilities()
        stamp = frame.snapshot.timestamp
        predictions = self._predictions(dataset, stamp) if caps.predictions else PredictionSet.unavailable(dataset, stamp)
        anomaly = self._anomaly(dataset, stamp) if caps.anomaly else AnomalyState.unavailable(dataset, stamp)
        rows = self._prediction_rows(predictions)
        targets = predictions.targets()
        return IntelligenceView(
            header=self._header(
                "H",
                frame,
                timestamp=predictions.timestamp or stamp,
                notices=(labels.SIMULATED_RESULT_LABEL, labels.NOT_VALIDATED_LABEL),
            ),
            dataset=dataset,
            predictions=predictions,
            anomaly=anomaly,
            columns=horizon_labels(predictions.horizons_min),
            rows=rows,
            trends=self._history(targets) if targets else (),
        )

    def _predictions(self, dataset: str, stamp: str) -> PredictionSet:
        """Model A's payload, or the documented unavailable one - never a raised exception.

        ``ValueError`` is caught beside :class:`CapabilityError` because a model that needs a
        complete input says so by *raising*: Model A refuses a feature row containing NaN (a PRD
        11.5 sensor dropout in the trailing window) and one built from a window shorter than its lag
        block. Both are correct on the model's side, and neither may take the whole screen down - so
        the refusal becomes the payload's own unavailable state carrying the model's words, which
        states the absence instead of substituting a number for it (item 5, NFR-6).
        """
        try:
            return self._provider.get_predictions(dataset)
        except CapabilityError:
            return PredictionSet.unavailable(dataset, stamp)
        except ValueError as error:
            return PredictionSet.unavailable(dataset, stamp, str(error))

    def _anomaly(self, dataset: str, stamp: str) -> AnomalyState:
        """Model B's verdict, or the documented unavailable one (see :meth:`_predictions`)."""
        try:
            return self._provider.get_anomaly_state(dataset)
        except CapabilityError:
            return AnomalyState.unavailable(dataset, stamp)
        except ValueError as error:
            return AnomalyState.unavailable(dataset, stamp, str(error))

    @staticmethod
    def _prediction_rows(predictions: PredictionSet) -> tuple[PredictionRow, ...]:
        """One :class:`PredictionRow` per predicted target: observed now, forecast per horizon."""
        current_by_tag = {value.tag: value for value in predictions.current}
        rows: list[PredictionRow] = []
        for target in predictions.targets():
            horizon = predictions.target_row(target)
            current = current_by_tag.get(target)
            unit = current.unit if current else (horizon[0].unit if horizon else "")
            rows.append(PredictionRow(target=target, unit=unit, current=current, horizon=horizon))
        return tuple(rows)

    # -- view I ------------------------------------------------------------------------------
    def what_if(
        self,
        frame: _Frame | None = None,
        *,
        changes: Mapping[str, float] | None = None,
        delta_fractions: Mapping[str, float] | None = None,
        mode: str = "NORMAL",
    ) -> WhatIfViewModel:
        """View I: evaluate operator-set changes through the validated engine (item 13)."""
        frame = frame or self.frame()
        caps = self._provider.capabilities()
        stamp = frame.snapshot.timestamp
        if caps.what_if:
            try:
                view = self._provider.run_what_if(changes, delta_fractions=delta_fractions, mode=mode)
                sliders = self._provider.what_if_sliders(mode=mode)
            except CapabilityError:
                view, sliders = WhatIfView.unavailable(stamp, mode), ()
        else:
            view, sliders = WhatIfView.unavailable(stamp, mode), ()
        return WhatIfViewModel(
            header=self._header(
                "I", frame, timestamp=view.timestamp or stamp, notices=self._decision_notices(mode)
            ),
            mode=mode,
            view=view,
            sliders=tuple(sliders),
        )

    # -- view J ------------------------------------------------------------------------------
    def optimization(self, frame: _Frame | None = None, *, mode: str = "NORMAL") -> OptimizationViewModel:
        """View J: the optimizer's recommendation or its refusal, as decision support (items 14-16)."""
        frame = frame or self.frame()
        caps = self._provider.capabilities()
        stamp = frame.snapshot.timestamp
        if caps.optimization:
            try:
                view = self._provider.get_optimization(mode=mode)
            except CapabilityError:
                view = OptimizationView.unavailable(stamp, mode)
        else:
            view = OptimizationView.unavailable(stamp, mode)
        return OptimizationViewModel(
            header=self._header(
                "J", frame, timestamp=view.timestamp or stamp, notices=self._decision_notices(mode)
            ),
            mode=mode,
            view=view,
            quality_descriptions=labels.RECOMMENDATION_QUALITY_DESCRIPTION,
        )

    # -- dispatch ----------------------------------------------------------------------------
    def view(self, view_id: str, *, frame: _Frame | None = None) -> Any:
        """The view model for a screen named by its id (``"A"``) or its key (``"overview"``)."""
        row = _VIEW_BY_ID.get(view_id) or _VIEW_BY_KEY.get(view_id)
        if row is None:
            raise KeyError(
                f"{view_id!r} is not a dashboard view: "
                f"{tuple(r[0] for r in VIEWS)} or {tuple(r[1] for r in VIEWS)}"
            )
        return getattr(self, row[1])(frame=frame)

    def views(self, frame: _Frame | None = None) -> dict[str, Any]:
        """All ten view models, built from one shared frame so every screen shows the same instant."""
        frame = frame or self.frame()
        return {row[1]: getattr(self, row[1])(frame=frame) for row in VIEWS}


# =============================================================================
# Provenance-separation audit (directive items 1, 22)
# =============================================================================
_SKIP: tuple[type, ...] = (
    AnomalyState,
    OptimizationView,
    WhatIfView,
    Series,
    ClockState,
    ProviderCapabilities,
    RegimeState,
    Footer,
    ViewHeader,
)


def _collect_channels(node: Any, path: str, out: dict[str, tuple[Value, ...]]) -> None:
    """Record every :class:`Value`-bearing channel in ``node`` under a unique path.

    A *channel* is a group of values a view renders together - a panel, a snapshot, one horizon of
    a forecast. The item 1 rule is that no channel mixes two of the four data sources, so the audit
    keys each group by its own path and never merges two. The forecast's observed ``current`` and
    each prediction horizon are deliberately separate paths; the types in :data:`_SKIP` carry no
    :class:`Value` channels (their numbers live in plain mappings, single-provenance by type).
    """
    if node is None:
        return
    if isinstance(node, Value):
        out[path] = (node,)
        return
    if isinstance(node, (Panel, KpiGroup)):
        if node.values:
            out[path] = tuple(node.values)
        return
    if isinstance(node, StateSnapshot):
        if node.values:
            out[path] = tuple(node.values.values())
        return
    if isinstance(node, EquipmentStatus):
        channel = tuple(v for v in ((node.driver,) + tuple(node.constraints)) if v is not None)
        if channel:
            out[path] = channel
        return
    if isinstance(node, PredictionSet):
        if node.current:
            out[f"{path}.current"] = tuple(node.current)
        for minutes in sorted(node.by_horizon):
            values = tuple(node.by_horizon[minutes])
            if values:
                out[f"{path}.t+{minutes}"] = values
        return
    if isinstance(node, _SKIP):
        return
    if is_dataclass(node) and not isinstance(node, type):
        for spec in fields(node):
            _collect_channels(getattr(node, spec.name), f"{path}.{spec.name}", out)
        return
    if isinstance(node, Mapping):
        return
    if isinstance(node, (tuple, list)):
        for index, item in enumerate(node):
            _collect_channels(item, f"{path}[{index}]", out)


def value_channels(view: Any) -> dict[str, tuple[Value, ...]]:
    """Every :class:`Value`-bearing channel in a finished view model, keyed by a unique path."""
    out: dict[str, tuple[Value, ...]] = {}
    _collect_channels(view, type(view).__name__, out)
    return out


def mixed_channels(view: Any) -> dict[str, frozenset[Provenance]]:
    """Channels that broke the item 1 rule: any carrying two of the four data sources.

    A valid view model returns ``{}``. The item 22 no-mixing test asserts exactly that for each of
    the ten screens - a mixed channel here is a UI payload that fused, say, an observed reading and
    a model forecast into one row of "values", which is precisely what the directive forbids.
    """
    bad: dict[str, frozenset[Provenance]] = {}
    for path, values in value_channels(view).items():
        sources = data_sources_of(values)
        if len(sources) > 1:
            bad[path] = sources
    return bad


__all__ = [
    "VIEWS",
    "DashboardState",
    "EnergyView",
    "EquipmentDetail",
    "Footer",
    "IntelligenceView",
    "OptimizationViewModel",
    "OverviewStageView",
    "OverviewView",
    "Panel",
    "PredictionRow",
    "ProcessView",
    "TwinView",
    "ViewHeader",
    "WhatIfViewModel",
    "mixed_channels",
    "value_channels",
]
