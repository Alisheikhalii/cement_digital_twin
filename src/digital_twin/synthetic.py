"""``SyntheticDataProvider`` - the synthetic source behind the PRD 26.1 contract (item 1).

This is the *only* place in the system that knows the current numbers come from a simulation.
Above it sit the dashboard, the animated twin, the presentation mode and the demo sequence, and
they see nothing but :class:`~src.digital_twin.provider.DataProvider`: no CSV path, no
:class:`PlantTwin`, no model object, no threshold. That is Task #6 item 1 and FR-14, and it is
what makes :class:`~src.digital_twin.real_plant.RealPlantDataProvider` a drop-in rather than a
rewrite.

Two sources, one contract:

``LIVE``
    a :class:`~src.digital_twin.scenario_driver.ScenarioDriver` the dashboard steps with PLAY /
    PAUSE / STEP / RESET (item 7). Scenario selection (item 18) switches the driving regime.
``REPLAY``
    a :class:`~src.data_generation.generator.GeneratedRun` with a cursor the dashboard scrubs
    (item 8). Only rows up to the cursor exist: a replay cannot show the future.

Four channels are kept apart at the source, never merged into one "values" dict (item 1):
the observable sensor row (:data:`Provenance.OBSERVED`), the simulator's own noise-free state
(:data:`Provenance.TRUTH`), Model A's horizons (:data:`Provenance.PREDICTION`) and Model C's
output (:data:`Provenance.RECOMMENDATION`).

Three rules this module holds itself to:

* **It computes no process number.** Every value is read from a component the test suite already
  pins, and the only arithmetic performed here is the daily-total pairing of item 12, which calls
  :func:`~src.optimization.recommendation.daily_total` rather than restating "per day".
* **It invents no limit.** Ranges come from :mod:`src.schema`, tightened only where a unit's own
  ``constraints`` block is tighter - which is existing configuration, per items 5 and 6.
* **A missing model is a state, not a substitute number.** The three model layers are injected;
  without them :meth:`capabilities` reports ``False`` and each payload renders its documented
  unavailable state (NFR-6).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Mapping, Sequence

import numpy as np
import pandas as pd

from src import schema
from src.config import KILN, MILL, ML, Config, ConfigError, load_config
from src.data_generation.generator import DATASETS, GeneratedRun
from src.data_generation.health import HEALTH_COLUMN
from src.digital_twin import layout
from src.digital_twin.insights import AnomalyState, OptimizationView, PredictionSet, WhatIfView
from src.digital_twin.payloads import (
    LIVE,
    REPLAY,
    EquipmentStatus,
    KpiGroup,
    ProviderCapabilities,
    RegimeState,
    Series,
    StateSnapshot,
    group,
    series_from,
)
from src.digital_twin.provenance import Provenance, Value, value_from_tag
from src.digital_twin.provider import CapabilityError, DataProvider
from src.digital_twin.scenario_driver import ScenarioDriver
from src.digital_twin.settings import DashboardSettings
from src.labels import (
    EQUIPMENT_DERATED,
    EQUIPMENT_IDLE,
    EQUIPMENT_RUNNING,
    EQUIPMENT_UNKNOWN,
    SPECIFIC_VS_TOTAL_NOTE,
)
from src.optimization.recommendation import daily_total
from src.process_models.plant import PlantTwin
from src.simulation.scheduler import SETPOINTS

#: Shown in the dashboard header. It names the source, which is half of item 20's honesty rule.
PROVIDER_NAME: Final = "SyntheticDataProvider"

#: ``Value.source`` strings - the call that produced the number, so NFR-6's scan has one hop to
#: follow from any rendered figure back to the component that computed it.
_SOURCE_OBSERVED: Final[Mapping[str, str]] = {
    LIVE: "ScenarioDriver.observed_history[t]",
    REPLAY: "GeneratedRun.datasets[t]",
}
_SOURCE_TRUTH: Final[Mapping[str, str]] = {
    LIVE: "ScenarioDriver.truth_history[t]",
    REPLAY: "GeneratedRun.truth[t]",
}
_SOURCE_DAILY_TOTAL: Final = "recommendation.daily_total(observed)"
_SOURCE_HEALTH: Final = "EquipmentHealthProcess.health_at"
_SOURCE_MODEL_A: Final = "model_a/{target}/t+{horizon}min"

#: The ML config keys whose windows the model frame must be long enough to satisfy. Checked once
#: at construction so the trailing-window truncation below is provably exact rather than a
#: performance shortcut that quietly changes a model input (item 23).
_WINDOW_KEYS: Final[tuple[str, ...]] = (
    "anomaly.spc.window_min",
    "anomaly.sensor_discrimination.drift_window_min",
)


#: The wording ``get_tag_metadata`` reports in its ``range_basis`` column, and the dashboard shows
#: beside a value whose range came from somewhere other than the data dictionary. Fixed here so a
#: view cannot paraphrase a provenance claim (item 1: every displayed value carries its origin).
BAND_BASIS_SETPOINT: Final = "configured operating range of a scheduled setpoint"
BAND_BASIS_CONSTRAINT: Final = "unit constraint block, intersected with the documented range"
BAND_BASIS_DOCUMENTED: Final = "documented range (src/schema.py, PRD 12.1)"
BAND_BASIS_DEVIATION: Final = (
    "no range judged: the nominal operating point lies outside the documented range "
    "(SIMULATION_ASSUMPTIONS.md Section 8 - the physics was kept and the band was not)"
)
BAND_BASIS_NONE: Final = "no documented range"


@dataclass(frozen=True, slots=True)
class BandAuthority:
    """Which configured range each tag's status is judged against, resolved once (items 5, 6).

    Built by :meth:`SyntheticDataProvider._collect_limits`, which documents the ranking. Held as
    one object so the four call sites that need a band all read the same resolution rather than
    each re-deriving one, and so ``get_tag_metadata`` can publish the *basis* alongside the band.
    """

    #: Tag -> the band a status is judged against. Absent means "no band" (see :attr:`unbanded`).
    display: Mapping[str, tuple[float, float]]
    #: Component name -> its own ``constraints`` block, for the equipment panel's constraint list.
    per_component: Mapping[str, Mapping[str, tuple[float, float]]]
    #: Tag -> its unit's raw ``constraints`` band, unintersected. Published, never used for status.
    constraints: Mapping[str, tuple[float, float]]
    #: Tags rendered with a value but no verdict, because no configured band can judge them.
    unbanded: frozenset[str]
    #: Tag -> which of the ``BAND_BASIS_*`` authorities produced its band.
    basis: Mapping[str, str]

    def band(self, tag: str) -> tuple[float | None, float | None]:
        low, high = self.display.get(tag, (None, None))
        return low, high

    def describe(self) -> dict[str, Any]:
        """Counts per authority - the audit item 24 asks the provenance rules to be documented by."""
        counts: dict[str, int] = {}
        for basis in self.basis.values():
            counts[basis] = counts.get(basis, 0) + 1
        return {
            "tags_banded": len(self.display),
            "tags_unbanded": len(self.unbanded),
            "by_basis": dict(sorted(counts.items())),
            "unbanded": sorted(self.unbanded),
        }


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    """A frame indexed by its timestamps, whichever of the two shapes it arrived in.

    The exporter writes ``timestamp`` as the first *column* (PRD 12.1) while the live driver
    returns a frame already indexed by it. Both are accepted so that neither shape has to be
    converted at its source, and every reader below can assume ``frame.index`` is the clock.
    """
    if schema.TIMESTAMP_COLUMN in frame.columns:
        return frame.set_index(schema.TIMESTAMP_COLUMN)
    return frame


def _exported(frame: pd.DataFrame) -> pd.DataFrame:
    """The inverse: the PRD 12.1 export shape, ``timestamp`` first and a plain range index.

    :meth:`SyntheticDataProvider.get_timeseries` returns this so that a provider frame and a row
    read back from ``data/kiln_process_data.csv`` are interchangeable - which is the property a
    future ``RealPlantDataProvider`` has to reproduce, and therefore the one to hand out.
    """
    out = frame.reset_index()
    if out.columns[0] != schema.TIMESTAMP_COLUMN:
        out = out.rename(columns={out.columns[0]: schema.TIMESTAMP_COLUMN})
    return out


class SyntheticDataProvider(DataProvider):
    """The synthetic plant, behind the PRD 26.1 contract and nothing but the contract."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        driver: ScenarioDriver | None = None,
        run: GeneratedRun | None = None,
        mode: str | None = None,
        settings: DashboardSettings | None = None,
        predictions: Mapping[str, Any] | None = None,
        detectors: Mapping[str, Any] | None = None,
        optimizer: Any = None,
        what_if: Any = None,
        ml_config: Config | None = None,
        kiln_config: Config | None = None,
        mill_config: Config | None = None,
    ) -> None:
        self._settings = settings if settings is not None else DashboardSettings.from_config()
        self._run = run
        self._driver = driver
        if driver is None and run is None:
            self._driver = ScenarioDriver(
                kiln_config=kiln_config,
                mill_config=mill_config,
                max_steps=self._settings.clock.max_live_steps,
            )
        available = tuple(
            label
            for label, source in ((LIVE, self._driver), (REPLAY, self._run))
            if source is not None
        )
        self._available_modes = available
        requested = str(mode) if mode is not None else available[0]
        if requested not in available:
            raise ConfigError(
                f"mode={requested!r} needs a "
                f"{'ScenarioDriver' if requested == LIVE else 'GeneratedRun'}; "
                f"this provider was built with {list(available)}"
            )
        self.mode = requested
        self._predictions = dict(predictions or {})
        self._detectors = dict(detectors or {})
        self._what_if = what_if
        self._optimizer = optimizer
        if self._optimizer is None and self._what_if is not None:
            self._optimizer = self._what_if.optimizer
        if self._what_if is None and self._optimizer is not None:
            from src.optimization.what_if import WhatIfEngine  # local: keeps import graph acyclic

            self._what_if = WhatIfEngine(self._optimizer)
        self._model_minutes = self._checked_model_window(ml_config)
        self._bands = self._collect_limits(kiln_config, mill_config)
        self._derated_below = self._derated_thresholds(kiln_config, mill_config)
        self._cursor = 0
        if self._run is not None:
            rows = len(self._run.index)
            # Open where a full sparkline and a full lag block already exist behind the cursor,
            # leaving the rest of the window to scrub through (item 8).
            self._cursor = min(rows - 1, self._settings.history.sparkline_points)
        # A recorded row carries the regime *label* only; the numeric id and the sensor-layer-only
        # flag live on the schedule that produced the run, so they are looked up by label rather
        # than re-derived from the readings (which is what "regime is configuration" means).
        self._replay_regime: dict[str, tuple[int | None, bool]] = (
            {
                str(episode.name): (episode.regime_id, bool(episode.sensor_layer_only))
                for episode in self._run.schedule.episodes
            }
            if self._run is not None
            else {}
        )

    # -- construction checks ----------------------------------------------------------------
    def _checked_model_window(self, ml_config: Config | None) -> int:
        """Trailing minutes handed to the models, verified against every window they need.

        The models are given ``history.live_window_minutes`` of trailing rows rather than the
        whole session, because Model B's SPC pass and Model A's feature build both cost O(rows).
        Truncation is only legitimate if the models' answer for the *last* row is unchanged by it,
        so the windows they read are checked here and the provider refuses to start otherwise -
        a silently short frame would change a model output to save time (item 23).
        """
        config = ml_config if ml_config is not None else load_config(ML)
        window = float(self._settings.history.live_window_minutes)
        needed: dict[str, float] = {
            key: float(config.get_path(key)) for key in _WINDOW_KEYS
        }
        needed["features.lags_min"] = max(
            float(value) for value in config.get_path("features.lags_min")
        )
        for key, minutes in needed.items():
            if window < minutes:
                raise ConfigError(
                    f"history.live_window_minutes is {window:g} min but {key} needs {minutes:g} "
                    "min of history; truncating the model frame would change a model output"
                )
        return int(window)

    def _collect_limits(
        self, kiln_config: Config | None, mill_config: Config | None
    ) -> BandAuthority:
        """Resolve, per tag, which configured range a status may honestly be judged against.

        Three existing authorities disagree about what "the range" of a tag is, and none of them
        may be edited to make the dashboard tidier (directive item 5: no new engineering limit in
        the UI). They are ranked here, once, at construction:

        1. **A scheduled setpoint** is banded by its own ``operating_ranges`` entry in
           ``configs/kiln_dynamics.yaml`` / ``configs/mill_dynamics.yaml`` - the band the scenario
           scheduler ramps it inside, so it is by construction the range the simulated data spans.
           Two of them (the fuel rates) are configured as a *ratio* of a reference rate the energy
           balance solves rather than as absolute t/h, and are resolved against that reference here
           exactly as :class:`~src.optimization.variables.DecisionSpace` resolves them.
        2. **Any other tag** is banded by the tighter of its unit's ``constraints`` block and its
           documented :mod:`src.schema` range - which is the "tighter authority" contract
           :func:`value_from_tag` states. Intersecting rather than overriding matters: three
           constraint bands are *looser* than the documented range (``oxygen_percent`` is clamped
           only to the physical 0-100 %), and overriding with those would have banded O2 against a
           span thirty times its documented one and coloured a normal reading amber.
        3. **Unless the nominal operating point lies outside that band**, in which case the tag is
           returned in the third element and rendered with no verdict at all. This is the
           machine-checkable form of ``SIMULATION_ASSUMPTIONS.md`` Section 8: where a PRD 12.1 band
           could not hold together with the PRD 9-10 equations the physics was kept, so the
           reference point itself sits outside the documented band. A band that excludes the
           nominal point cannot be the band an excursion is judged against - it would report a
           permanent alarm on a plant that is, by its own definition, at rest.

        Read once, from a twin used for metadata only - in ``REPLAY`` that twin is never stepped.
        """
        kiln = kiln_config if kiln_config is not None else load_config(KILN)
        mill = mill_config if mill_config is not None else load_config(MILL)
        self._metadata_twin = (
            self._driver.twin if self._driver is not None else PlantTwin(kiln, mill)
        )
        snapshot = self._metadata_twin.current_state_snapshot()
        per_component: dict[str, dict[str, tuple[float, float]]] = {}
        constraints: dict[str, tuple[float, float]] = {}
        for line in snapshot.get("units", {}).values():
            for name, component in line.get("units", {}).items():
                bands = {
                    str(tag): (float(low), float(high))
                    for tag, (low, high) in (component.get("constraints") or {}).items()
                }
                per_component[str(name)] = bands
                constraints.update(bands)

        # A live driver's twin has been stepped, so the nominal point is read from an unstepped
        # one. When there is no driver the metadata twin *is* unstepped and is reused as-is.
        reference_twin = self._metadata_twin if self._driver is None else PlantTwin(kiln, mill)
        nominal = self._nominal_readings(reference_twin)
        setpoints = self._setpoint_bands(reference_twin, kiln, mill)

        flat: dict[str, tuple[float, float]] = dict(setpoints)
        basis: dict[str, str] = {tag: BAND_BASIS_SETPOINT for tag in setpoints}
        unbanded: set[str] = set()
        for spec in schema.ALL_TAGS:
            if spec.name in flat:
                continue
            if spec.range_min is None or spec.range_max is None:
                basis[spec.name] = BAND_BASIS_NONE
                unbanded.add(spec.name)
                continue
            documented = (float(spec.range_min), float(spec.range_max))
            band = constraints.get(spec.name)
            resolved = (
                documented
                if band is None
                else (max(band[0], documented[0]), min(band[1], documented[1]))
            )
            point = nominal.get(spec.name)
            if point is not None and not resolved[0] <= point <= resolved[1]:
                unbanded.add(spec.name)
                basis[spec.name] = BAND_BASIS_DEVIATION
                continue
            flat[spec.name] = resolved
            basis[spec.name] = (
                BAND_BASIS_DOCUMENTED if band is None else BAND_BASIS_CONSTRAINT
            )
        return BandAuthority(
            display=flat,
            per_component=per_component,
            constraints=constraints,
            unbanded=frozenset(unbanded),
            basis=basis,
        )

    @staticmethod
    def _nominal_readings(twin: PlantTwin) -> dict[str, float]:
        """Every tag's value at the twin's own reference operating point.

        The reference point is where PRD 9.3 states the energy and mass balances close "by
        construction", so an unstepped twin is at rest by definition. That makes it the one place
        to ask whether a documented band is a band this simulation can actually sit inside.
        """
        readings: dict[str, float] = {}
        snapshot = twin.current_state_snapshot()
        for line in snapshot.get("units", {}).values():
            for component in line.get("units", {}).values():
                for section in ("inputs", "outputs"):
                    for tag, value in (component.get(section) or {}).items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            readings.setdefault(str(tag), float(value))
        return readings

    @staticmethod
    def _setpoint_bands(
        twin: PlantTwin, kiln: Config, mill: Config
    ) -> dict[str, tuple[float, float]]:
        """``operating_ranges`` for every scheduled setpoint, ratio bands resolved (authority 1).

        Keyed by dataset *tag* rather than by scheduler variable name, because the tag is what a
        panel asks for. A setpoint with no configured range (``mill_speed_rpm``) is simply absent
        and falls through to the documented range like any other reading.
        """
        blocks = {
            "kiln": kiln.get_path("operating_ranges"),
            "mill": mill.get_path("operating_ranges"),
        }
        references = {"kiln": twin.kiln.reference, "mill": twin.cement_mill.reference}
        bands: dict[str, tuple[float, float]] = {}
        for spec in SETPOINTS:
            block = blocks[spec.dataset]
            absolute = block.get_path(spec.variable, None)
            if absolute is not None:
                bands[spec.tag] = (float(absolute[0]), float(absolute[1]))
                continue
            ratio = None if spec.ratio_key is None else block.get_path(spec.ratio_key, None)
            if ratio is None:
                continue
            point = float(getattr(references[spec.dataset], spec.reference_attr))
            bands[spec.tag] = (float(ratio[0]) * point, float(ratio[1]) * point)
        return bands

    @staticmethod
    def _derated_thresholds(
        kiln_config: Config | None, mill_config: Config | None
    ) -> dict[str, float]:
        """Health at or below which a unit reads DERATED, from its own PRD 9.5 fault step-down.

        ``equipment.health.fault_health_drop`` is the loss a mechanical fault inflicts, so
        ``1 - drop`` is the health a *fault* takes the unit to. Reading it here keeps the state
        vocabulary on a number the process models already apply (item 5): nothing new is defined,
        and if a config changes its fault severity the word follows it.
        """
        sources: dict[str, Config | None] = {"kiln": kiln_config, "mill": mill_config}
        defaults = {"kiln": KILN, "mill": MILL}
        out: dict[str, float] = {}
        for dataset, config in sources.items():
            block = config if config is not None else load_config(defaults[dataset])
            drop = block.get_path("equipment.health.fault_health_drop", None)
            if drop is not None:
                out[dataset] = 1.0 - float(drop)
        return out

    # -- access -----------------------------------------------------------------------------
    @property
    def settings(self) -> DashboardSettings:
        """Presentation constants, so a view reads them through the provider it already holds."""
        return self._settings

    @property
    def driver(self) -> ScenarioDriver | None:
        """The live driver, or ``None``. For the demo builder and tests; views use the contract."""
        return self._driver

    @property
    def run(self) -> GeneratedRun | None:
        """The replayed run, or ``None``."""
        return self._run

    def modes(self) -> tuple[str, ...]:
        return self._available_modes

    def set_mode(self, mode: str) -> None:
        """Switch between the live clock and the recorded window (items 7 and 8)."""
        label = str(mode)
        if label not in self._available_modes:
            raise CapabilityError(
                f"{self.name} was built without a {label} source; available: "
                f"{list(self._available_modes)}"
            )
        self.mode = label

    def capabilities(self) -> ProviderCapabilities:
        """What this provider can answer right now - the basis of every degraded panel."""
        missing: list[str] = []
        if not self._predictions:
            missing.append("predictions")
        if not self._detectors:
            missing.append("anomaly")
        if self._optimizer is None:
            missing.append("optimization")
        if self._what_if is None:
            missing.append("what_if")
        return ProviderCapabilities(
            name=self.name,
            synthetic=True,
            truth=True,
            history=True,
            live=LIVE in self._available_modes,
            predictions=bool(self._predictions),
            anomaly=bool(self._detectors),
            optimization=self._optimizer is not None,
            what_if=self._what_if is not None,
            missing=tuple(missing),
        )

    def _dataset(self, dataset: str | None) -> tuple[str, ...]:
        """Normalise a dataset argument to the datasets to read (``None`` = both)."""
        if dataset is None:
            return tuple(DATASETS)
        label = str(dataset)
        if label not in DATASETS:
            raise KeyError(f"{label!r} is not a modelled dataset; expected {list(DATASETS)}")
        return (label,)

    @staticmethod
    def _owner(tag: str) -> str | None:
        """The dataset a tag belongs to, or ``None`` if no dataset exports it.

        :func:`schema.dataset_of` deliberately raises for the two shared label columns, so the
        first dataset that carries the tag is taken instead of letting a legitimate lookup fail.
        """
        for dataset in DATASETS:
            if schema.has_tag(tag, dataset) or tag in schema.numeric_columns(dataset):
                return dataset
        return None

    # -- position (the current row, in either mode) ------------------------------------------
    def _started(self) -> None:
        """Make sure a live session has produced its first row before it is read."""
        if self._driver is not None and self.mode == LIVE and self._driver.steps_taken == 0:
            self._driver.latest()

    def timestamp(self) -> pd.Timestamp:
        """Timestamp of the row every payload below describes."""
        self._started()
        if self.mode == LIVE:
            return self._driver.latest().timestamp
        return pd.Timestamp(self._run.index[self._cursor])

    def position(self) -> dict[str, Any]:
        """Where the session is - what the clock and the scrubber both render from."""
        self._started()
        live = self.mode == LIVE
        return {
            "mode": self.mode,
            "modes": list(self._available_modes),
            "timestamp": str(self.timestamp()),
            "step": self._driver.steps_taken if live else self._cursor + 1,
            "steps": self._driver.max_steps if live else len(self._run.index),
            "step_minutes": (
                self._settings.clock.step_minutes if live else self._settings.replay.step_minutes
            ),
            "speeds": list(
                self._settings.clock.speeds if live else self._settings.replay.speeds
            ),
            "default_speed": (
                self._settings.clock.default_speed
                if live
                else self._settings.replay.default_speed
            ),
        }

    def _frame(self, dataset: str, *, truth: bool = False) -> pd.DataFrame:
        """Every row up to the current position, indexed by timestamp, oldest first."""
        self._started()
        if self.mode == LIVE:
            frame = (
                self._driver.truth_history(dataset)
                if truth
                else self._driver.observed_history(dataset)
            )
            return frame
        source = self._run.truth if truth else self._run.datasets
        frame = _indexed(source[dataset])
        # A replay position is a *now*: rows after the cursor have not happened yet on screen.
        return frame.iloc[: self._cursor + 1]

    def _row(self, dataset: str, *, truth: bool = False) -> Mapping[str, float]:
        """The current row of one dataset, in one channel."""
        self._started()
        if self.mode == LIVE and not truth:
            return self._driver.latest().observed[dataset]
        if self.mode == LIVE:
            true_state = self._driver.latest().true_state
            return {
                tag: float(true_state[tag])
                for tag in schema.numeric_columns(dataset)
                if tag in true_state
            }
        frame = self._frame(dataset, truth=truth)
        if frame.empty:
            return {}
        row = frame.iloc[-1]
        return {str(tag): value for tag, value in row.items()}

    def _model_frame(self, dataset: str) -> pd.DataFrame:
        """The trailing window the models are given (see :meth:`_checked_model_window`)."""
        frame = self._frame(dataset)
        window = self._model_minutes
        return frame if len(frame) <= window else frame.iloc[-window:]

    # -- values ------------------------------------------------------------------------------
    @staticmethod
    def _number(value: Any) -> float | None:
        """A finite float, or ``None``. A gap in the data stays a gap (PRD 12.4, NFR-6)."""
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def _value(
        self,
        tag: str,
        value: Any,
        *,
        provenance: Provenance,
        source: str,
        dataset: str | None = None,
        target: float | None = None,
        uncertainty: float | None = None,
        horizon_min: int | None = None,
    ) -> Value:
        """One displayable number, banded by :meth:`_collect_limits`' resolved authority."""
        low, high = self._bands.band(tag)
        return value_from_tag(
            tag,
            self._number(value),
            provenance=provenance,
            source=source,
            dataset=dataset if dataset is not None else self._owner(tag),
            warn_fraction=self._settings.status.warn_fraction_of_span,
            range_min=low,
            range_max=high,
            banded=tag not in self._bands.unbanded,
            target=target,
            uncertainty=uncertainty,
            horizon_min=horizon_min,
        )

    def _snapshot(self, dataset: str | None, *, truth: bool) -> StateSnapshot:
        """One channel of the current state, for one dataset or for the whole plant."""
        provenance = Provenance.TRUTH if truth else Provenance.OBSERVED
        source = (_SOURCE_TRUTH if truth else _SOURCE_OBSERVED)[self.mode]
        values: dict[str, Value] = {}
        for name in self._dataset(dataset):
            row = self._row(name, truth=truth)
            for tag in schema.numeric_columns(name):
                if tag in row and tag not in values:
                    values[tag] = self._value(
                        tag, row[tag], provenance=provenance, source=source, dataset=name
                    )
        return StateSnapshot(
            timestamp=str(self.timestamp()),
            mode=self.mode,
            provenance=provenance,
            source=source,
            values=values,
        )

    def get_current_state(self, dataset: str | None = None) -> StateSnapshot:
        """The observable channel: what an instrument would report (PRD 11.5)."""
        return self._snapshot(dataset, truth=False)

    def get_truth_state(self, dataset: str | None = None) -> StateSnapshot:
        """The simulator's own state, noise-free. Never merged with the observable channel."""
        return self._snapshot(dataset, truth=True)

    def get_sensor_values(self, tags: Sequence[str]) -> tuple[Value, ...]:
        """Named readings from the observable channel, in the order asked for."""
        state = self.get_current_state()
        return tuple(
            state.values[tag]
            for tag in (str(item) for item in tags)
            if tag in state.values
        )

    # -- history (item 23: downsampled, never the raw window) --------------------------------
    @property
    def _native_seconds(self) -> float:
        simulation = (
            self._driver.simulation if self._driver is not None else self._run.simulation
        )
        return float(simulation.dt_seconds)

    def _default_minutes(self) -> float:
        """Trailing window a trend shows when the caller names none."""
        if self.mode == LIVE:
            return float(self._settings.history.live_window_minutes)
        return float(self._settings.history.default_window_hours) * 60.0

    def _window_frame(
        self,
        dataset: str,
        *,
        truth: bool,
        minutes: float | None,
        start: Any,
        end: Any,
    ) -> pd.DataFrame:
        """Rows of one dataset inside the requested window, clipped to the current position."""
        frame = self._frame(dataset, truth=truth)
        if frame.empty:
            return frame
        last = frame.index[-1]
        upper = pd.Timestamp(end) if end is not None else last
        if upper > last:
            upper = last
        if start is not None:
            lower = pd.Timestamp(start)
        else:
            span = self._default_minutes() if minutes is None else float(minutes)
            lower = upper - pd.Timedelta(minutes=span)
        return frame.loc[(frame.index >= lower) & (frame.index <= upper)]

    def _downsample(
        self, index: pd.DatetimeIndex, values: np.ndarray, budget: int, method: str
    ) -> tuple[pd.DatetimeIndex, np.ndarray, str]:
        """Reduce one channel to ``budget`` points, keeping what the method promises to keep.

        ``minmax`` (the configured default) keeps each bucket's extremes in time order, so an
        excursion survives the reduction - a mean would average a two-minute O2 dip away, and the
        excursions are exactly what an anomaly demonstration is about. Nothing is interpolated and
        no point is moved: every emitted sample is a sample that was in the window.
        """
        total = len(values)
        if total <= budget:
            return index, values, "none"
        if method == "last":
            keep = np.linspace(0, total - 1, budget).astype(int)
            return index[keep], values[keep], "last"
        buckets = max(1, budget // 2 if method == "minmax" else budget)
        edges = np.linspace(0, total, buckets + 1).astype(int)
        if method == "mean":
            stamps = [index[a] for a, b in zip(edges[:-1], edges[1:]) if b > a]
            means = [np.nanmean(values[a:b]) for a, b in zip(edges[:-1], edges[1:]) if b > a]
            return pd.DatetimeIndex(stamps), np.asarray(means, dtype=float), "mean"
        keep: list[int] = []
        for a, b in zip(edges[:-1], edges[1:]):
            if b <= a:
                continue
            chunk = values[a:b]
            finite = np.isfinite(chunk)
            if not finite.any():
                keep.append(a)
                continue
            offsets = np.flatnonzero(finite)
            low = offsets[int(np.argmin(chunk[offsets]))]
            high = offsets[int(np.argmax(chunk[offsets]))]
            keep.extend(sorted({a + int(low), a + int(high)}))
        selected = np.asarray(sorted(set(keep)), dtype=int)
        return index[selected], values[selected], "minmax"

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
        """Trends for the requested tags, downsampled to the configured budget."""
        budget = int(max_points) if max_points is not None else self._settings.history.max_points
        method = self._settings.history.downsample_method
        provenance = Provenance.TRUTH if truth else Provenance.OBSERVED
        source = (_SOURCE_TRUTH if truth else _SOURCE_OBSERVED)[self.mode]
        frames: dict[str, pd.DataFrame] = {}
        out: list[Series] = []
        for tag in (str(item) for item in tags):
            dataset = self._owner(tag)
            if dataset is None:
                continue
            if dataset not in frames:
                frames[dataset] = self._window_frame(
                    dataset, truth=truth, minutes=minutes, start=start, end=end
                )
            frame = frames[dataset]
            if frame.empty or tag not in frame.columns:
                continue
            available = len(frame)
            index, values, applied = self._downsample(
                frame.index, frame[tag].to_numpy(dtype=float), budget, method
            )
            low, high = self._bands.band(tag)
            spec = schema.get_tag(tag, dataset) if schema.has_tag(tag, dataset) else None
            out.append(
                series_from(
                    tag,
                    index,
                    values,
                    provenance=provenance,
                    source=source,
                    unit=spec.unit if spec else "",
                    points_available=available,
                    method=applied,
                    range_min=low,
                    range_max=high,
                )
            )
        return tuple(out)

    def sparklines(self, tags: Sequence[str]) -> tuple[Series, ...]:
        """KPI-card trends: the same call at the card's smaller point budget (PRD 18.1)."""
        return self.get_history(tags, max_points=self._settings.history.sparkline_points)

    # -- PRD 26.1: the two mandated methods ---------------------------------------------------
    def get_timeseries(
        self,
        tags: Sequence[str],
        start: datetime,
        end: datetime,
        resample: str | None = None,
    ) -> pd.DataFrame:
        """PRD 26.1 verbatim: raw rows of ``tags`` in ``[start, end]``, optionally resampled.

        This is the historian contract, so the shape is the PRD 12.1 export shape - ``timestamp``
        first, plain range index - and a frame from here is interchangeable with one read from
        ``data/kiln_process_data.csv``. Unlike :meth:`get_history` nothing is downsampled: a
        caller who asks for raw rows gets raw rows, and the UI's budget is applied by the UI's
        own call.

        A rule finer than the source's sampling interval is refused by
        :meth:`DataProvider.check_resample` rather than interpolated (FR-20).
        """
        rule = self.check_resample(resample, native_seconds=self._native_seconds)
        wanted = [str(tag) for tag in tags]
        columns: dict[str, pd.Series] = {}
        cache: dict[str, pd.DataFrame] = {}
        for tag in wanted:
            dataset = self._owner(tag)
            if dataset is None:
                continue
            if dataset not in cache:
                cache[dataset] = self._frame(dataset)
            frame = cache[dataset]
            if tag in frame.columns and tag not in columns:
                columns[tag] = frame[tag]
        if not columns:
            return pd.DataFrame(columns=[schema.TIMESTAMP_COLUMN, *wanted])
        joined = pd.DataFrame(columns)
        lower, upper = pd.Timestamp(start), pd.Timestamp(end)
        joined = joined.loc[(joined.index >= lower) & (joined.index <= upper)]
        if rule is not None:
            # Aggregation only - the check above has already refused any upsampling rule, so this
            # can never manufacture a sample. The mean is the aggregation the resample contract of
            # PRD 26.3 describes; excursion-preserving reduction is get_history's job, not this
            # method's, because a historian read must not distort the values it returns.
            joined = joined.resample(rule).mean()
        joined.index.name = schema.TIMESTAMP_COLUMN
        return _exported(joined)

    def get_tag_metadata(self) -> pd.DataFrame:
        """PRD 26.1 verbatim: one row per tag with unit, description, range and interval.

        Three range columns, because they answer three different questions a PRD 27.1 reviewer
        asks and must not be conflated:

        * ``range_min``/``range_max`` - the documented operating range (``src/schema.py``, PRD 12.1).
        * ``constraint_min``/``constraint_max`` - the unit's own raw ``constraints`` band, what the
          process is *allowed* to do, published unintersected exactly as the unit declares it.
        * ``band_min``/``band_max`` + ``range_basis`` - the range this provider actually judges a
          status against, and which of the three authorities produced it. ``band_min`` is null for
          the tags :attr:`BandAuthority.unbanded` names, whose ``range_basis`` says why.
        """
        interval = f"{self._native_seconds:g} s"
        rows = []
        for spec in schema.ALL_TAGS:
            constraint = self._bands.constraints.get(spec.name)
            band_min, band_max = self._bands.band(spec.name)
            rows.append(
                {
                    "tag": spec.name,
                    "dataset": spec.dataset,
                    "process_unit": spec.process_unit,
                    "role": spec.role,
                    "unit": spec.unit,
                    "description": spec.description,
                    "range_min": spec.range_min,
                    "range_max": spec.range_max,
                    "constraint_min": constraint[0] if constraint else None,
                    "constraint_max": constraint[1] if constraint else None,
                    "band_min": band_min,
                    "band_max": band_max,
                    "range_basis": self._bands.basis.get(spec.name, BAND_BASIS_NONE),
                    "sampling_interval": interval,
                    "importance": spec.importance,
                    "mandatory": spec.mandatory,
                    "assumption": spec.assumption,
                    "provider": self.name,
                }
            )
        return pd.DataFrame(rows)

    # -- equipment (directive items 2 and 4) --------------------------------------------------
    def _health(self, dataset: str, health_key: str) -> float:
        """The unit's health scalar - the physics derating factor, read where it is produced.

        In ``REPLAY`` this is the exported ``equipment_health`` column of the truth frame rather
        than :attr:`GeneratedRun.health`: the planned trajectory still carries its warm-up head
        (:meth:`EquipmentHealthProcess.plan` pads the front), so indexing it by the replay cursor
        would report health from ``warmup_steps`` rows *before* the row on screen. The exported
        column is already trimmed to the same rows every other reading here uses.
        """
        if self.mode == LIVE:
            return float(self._driver.latest().health.get(health_key, 1.0))
        frame = self._frame(dataset, truth=True)
        if frame.empty or HEALTH_COLUMN not in frame.columns:
            return 1.0
        value = self._number(frame[HEALTH_COLUMN].iloc[-1])
        return 1.0 if value is None else value

    def _state_of(self, spec: layout.EquipmentSpec, driver: Value | None, health: float) -> str:
        """The four-word equipment state of :data:`src.labels.EquipmentState`.

        No threshold is invented here. UNKNOWN is the honest answer when the driving reading is
        absent (NFR-6). IDLE is the *line's* throughput below ``animation.min_rate_fraction``, a
        presentation constant - a component's own ``driver`` may be a temperature, which never
        falls to zero and so cannot answer "is anything flowing".

        DERATED reads the unit's own ``equipment.health.fault_health_drop``, the step-down PRD 9.5
        applies when a mechanical fault lands. "Health below 1.0" would not do: the same config
        block decays health continuously at ``degradation_per_day``, so every component would read
        DERATED within the first hour of any run and RUNNING would be unreachable - the word would
        stop carrying information rather than start. A fault-sized loss is the configuration's own
        definition of a health *event*, so the state still reports the simulation instead of
        grading it.
        """
        if driver is None or driver.value is None:
            return EQUIPMENT_UNKNOWN
        throughput = self._value(
            layout.LINE_THROUGHPUT[spec.line],
            self._row(spec.dataset).get(layout.LINE_THROUGHPUT[spec.line]),
            provenance=Provenance.OBSERVED,
            source=_SOURCE_OBSERVED[self.mode],
            dataset=spec.dataset,
        )
        if not self._settings.animation.moving(throughput.fraction_of_range()):
            return EQUIPMENT_IDLE
        derated_at = self._derated_below.get(spec.dataset)
        if derated_at is not None and health <= derated_at:
            return EQUIPMENT_DERATED
        return EQUIPMENT_RUNNING

    def get_equipment_status(self) -> tuple[EquipmentStatus, ...]:
        """Every PRD 8.3 component: state, health, driving variable and its own constraints.

        ``constraints`` carries the bands that component's ``constraints`` block declares, as
        :class:`Value` objects, so the inspector of item 4 shows current-versus-allowed for the
        selected equipment without the view holding a limit of its own (items 5, 6).
        """
        rows: dict[str, Mapping[str, float]] = {}
        out: list[EquipmentStatus] = []
        for spec in layout.EQUIPMENT:
            if spec.dataset not in rows:
                rows[spec.dataset] = self._row(spec.dataset)
            row = rows[spec.dataset]
            source = _SOURCE_OBSERVED[self.mode]
            driver = None
            if spec.driver in row:
                driver = self._value(
                    spec.driver,
                    row[spec.driver],
                    provenance=Provenance.OBSERVED,
                    source=source,
                    dataset=spec.dataset,
                )
            health = self._health(spec.dataset, spec.health_key)
            bands = self._bands.per_component.get(spec.name, {})
            constraints = tuple(
                self._value(
                    tag,
                    row.get(tag),
                    provenance=Provenance.OBSERVED,
                    source=source,
                    dataset=spec.dataset,
                )
                for tag in bands
                if tag in row
            )
            out.append(
                EquipmentStatus(
                    name=spec.name,
                    unit=spec.title,
                    kind=spec.kind,
                    state=self._state_of(spec, driver, health),
                    health=health,
                    driver=driver,
                    detail=", ".join(spec.detail),
                    constraints=constraints,
                )
            )
        return tuple(out)

    # -- KPIs (directive items 9 and 12) ------------------------------------------------------
    def _kpi_values(self, dataset: str, tags: Sequence[str]) -> tuple[Value, ...]:
        """One card per tag of one dataset, skipping tags this row does not carry."""
        row = self._row(dataset)
        source = _SOURCE_OBSERVED[self.mode]
        return tuple(
            self._value(
                tag, row[tag], provenance=Provenance.OBSERVED, source=source, dataset=dataset
            )
            for tag in tags
            if tag in row
        )

    def _cards(self, tags: Sequence[str]) -> tuple[Value, ...]:
        """One card per tag, each read from whichever dataset exports it (plant-wide groups)."""
        out: list[Value] = []
        rows: dict[str, Mapping[str, float]] = {}
        for tag in tags:
            dataset = self._owner(tag)
            if dataset is None:
                continue
            if dataset not in rows:
                rows[dataset] = self._row(dataset)
            row = rows[dataset]
            if tag in row:
                out.append(
                    self._value(
                        tag,
                        row[tag],
                        provenance=Provenance.OBSERVED,
                        source=_SOURCE_OBSERVED[self.mode],
                        dataset=dataset,
                    )
                )
        return tuple(out)

    def daily_totals(self) -> tuple[Value, ...]:
        """The *total* energy figures that pair with the specific ones (directive item 12).

        Item 12 is explicit that showing only specific energy is dishonest: specific consumption
        can fall while the plant burns more per day, because production rose. Each total is
        ``intensity x rate x 24 h`` via :func:`~src.optimization.recommendation.daily_total`, so
        the definition of "per day" lives in the optimization layer that reports savings against
        it, not in a second copy here. The result stays ``OBSERVED`` - it is arithmetic on two
        measured rates, not a fifth data source - and its ``source`` names the arithmetic.
        """
        out: list[Value] = []
        for total in layout.DAILY_TOTALS:
            row = self._row(total.dataset)
            amount = self._number(
                daily_total(
                    row,
                    intensity_tag=total.intensity_tag,
                    rate_tag=total.rate_tag,
                    scale=total.scale,
                )
            )
            out.append(
                Value(
                    tag=total.tag,
                    value=amount,
                    unit=total.unit,
                    provenance=Provenance.OBSERVED,
                    source=f"{_SOURCE_DAILY_TOTAL}: {total.intensity_tag} x {total.rate_tag}",
                    description=total.description,
                )
            )
        return tuple(out)

    def get_kpis(self) -> tuple[KpiGroup, ...]:
        """The three KPI groups of directive item 9, no invented KPI among them.

        The plant group carries the specific figures *and* the daily totals in one group, under
        :data:`~src.labels.SPECIFIC_VS_TOTAL_NOTE`, so the pair cannot be split across views and
        the favourable half shown alone.
        """
        plant = self._cards(layout.PLANT_KPI_TAGS)
        return (
            group(layout.KILN_KPI_TITLE, self._kpi_values("kiln", layout.KILN_KPI_TAGS)),
            group(layout.MILL_KPI_TITLE, self._kpi_values("mill", layout.MILL_KPI_TAGS)),
            group(
                layout.PLANT_KPI_TITLE,
                plant + self.daily_totals(),
                note=SPECIFIC_VS_TOTAL_NOTE,
            ),
        )

    # -- operating regime (PRD 11.4) ----------------------------------------------------------
    @staticmethod
    def _first_fault(faults: Mapping[str, Any]) -> str | None:
        """The injected fault to name, in :data:`DATASETS` order, or ``None``.

        A regime injects a fault into one dataset at a time, but the schedule records the field for
        both, so the two are scanned in a fixed order rather than only the kiln - a mill-only fault
        would otherwise be dropped from the panel that exists to announce it.
        """
        for dataset in DATASETS:
            fault = faults.get(dataset)
            if fault:
                return str(fault)
        return None

    def get_operating_regime(self) -> RegimeState:
        """The regime label of the current row - a configured label, never a model output.

        ``sensor_layer_only`` is the scenario's own flag: a sensor-drift regime perturbs the
        measurement and not the process, which is exactly why the anomaly panel cannot resolve it
        (the documented Task #4 limitation, preserved here rather than restated).
        """
        self._started()
        if self.mode == LIVE:
            step = self._driver.latest()
            return RegimeState(
                label=step.regime,
                regime_id=step.regime_id,
                injected_fault=self._first_fault(step.faults),
                provenance=Provenance.CONFIGURATION,
                source="ScenarioSchedule.regime_at",
                sensor_layer_only=bool(step.sensor_layer_only),
            )
        rows = {dataset: self._row(dataset) for dataset in DATASETS}
        kiln_row = rows.get(DATASETS[0]) or {}
        label = str(kiln_row.get(schema.REGIME_LABEL_COLUMN, "")) if kiln_row else ""
        fault = self._first_fault(
            {
                dataset: row.get(schema.FAULT_LABEL_COLUMN)
                for dataset, row in rows.items()
                if row
            }
        )
        regime_id, sensor_only = self._replay_regime.get(label, (None, False))
        return RegimeState(
            label=label,
            regime_id=regime_id,
            injected_fault=fault,
            provenance=Provenance.CONFIGURATION,
            source=f"{_SOURCE_OBSERVED[REPLAY]}.{schema.REGIME_LABEL_COLUMN}",
            sensor_layer_only=sensor_only,
        )

    # -- the optimizer's view of the current row ----------------------------------------------
    def _flat_row(self, *, back: int = 0) -> dict[str, float]:
        """Every observable numeric of both datasets in one mapping, ``back`` rows behind now.

        The rule engine and the PRD 14.5 "current operating point" row both read the plant as one
        state rather than two datasets. ``back=1`` is the previous sample, which the one
        rate-of-change rule needs; at the native one-minute step that is exactly its
        ``CO_RATE_WINDOW_MIN`` window, so no interval is re-declared here.
        """
        out: dict[str, float] = {}
        for dataset in DATASETS:
            if back == 0:
                row: Mapping[str, Any] = self._row(dataset)
            else:
                frame = self._frame(dataset)
                if len(frame) <= back:
                    continue
                row = frame.iloc[-1 - back].to_dict()
            for tag, value in row.items():
                number = self._number(value)
                if number is not None:
                    out[str(tag)] = number
        return out

    def _setpoint_vector(self) -> dict[str, float]:
        """The setpoints in force, read from the observable channel (never from the twin).

        Keyed by :attr:`SetpointSpec.variable` because that is the twin's own input spelling, and
        read from :attr:`SetpointSpec.tag` because that is what the instrument reports. Going
        through the observable channel is the point: the optimizer is asked the same question an
        operator could ask from the control room, not one that needs the simulator's private state.
        """
        observed = self._flat_row()
        return {
            spec.variable: observed[spec.tag] for spec in SETPOINTS if spec.tag in observed
        }

    def _optimizer_inputs(self) -> dict[str, float]:
        """The twin input vector the optimizer starts from: reference point, observed setpoints on.

        The reference point supplies the exogenous inputs a run holds constant (raw-meal moisture
        and temperature among them) and the observed setpoints overwrite the manipulated ones, so
        the search starts at the operating point the instruments report rather than at the
        reference. The twin consulted here is never stepped - it is read for its input *names*.
        """
        twin = self._driver.twin if self._driver is not None else self._metadata_twin
        inputs = {str(key): float(value) for key, value in twin.inputs.items()}
        inputs.update(self._setpoint_vector())
        return inputs

    def _model_history(self) -> pd.DataFrame:
        """The joined trailing frame the models and the baselines read (both datasets, one index).

        Joined rather than concatenated per dataset because Model A's feature row, Model B's SPC
        window and the PRD 14.5 baselines are all given one ``history`` frame that has to carry
        every column they may read, including the two shared label columns.
        """
        joined: pd.DataFrame | None = None
        for dataset in DATASETS:
            frame = self._model_frame(dataset)
            if frame.empty:
                continue
            if joined is None:
                joined = frame
                continue
            fresh = [column for column in frame.columns if column not in joined.columns]
            joined = joined.join(frame[fresh], how="outer")
        return pd.DataFrame() if joined is None else joined

    # -- Model B (PRD 15, item 11) --------------------------------------------------------------
    def _rule_hook(self) -> Any:
        """The PRD 14.6 hook Model B's report calls for its suggested action, or ``None``.

        Model B never authors advice; when an optimizer is wired in, its rule engine does. The hook
        ignores the evidence payload it is handed and evaluates the *state*, because that is what
        the rule engine takes - the evidence is Model B's own explanation and is displayed beside
        the suggestion under its own label, never folded into it.
        """
        if self._optimizer is None:
            return None
        engine = self._optimizer.rule_engine
        setpoints = self._setpoint_vector()
        if not setpoints:
            return None
        state = self._flat_row()
        previous = self._flat_row(back=1) or None

        def suggest(_evidence: Mapping[str, Any]) -> str:
            return engine.evaluate(state, setpoints, previous_state=previous).suggestion()

        return suggest

    def get_anomaly_state(self, dataset: str = "kiln") -> AnomalyState:
        """Model B's verdict on the current row, or its documented unavailable state.

        The row is the *last* row of the trailing model frame, which is the current position in
        both modes - a replay asks Model B about the row under the cursor, not about the newest row
        in the file.
        """
        self._started()
        name = self._dataset(dataset)[0]
        stamp = str(self.timestamp())
        detector = self._detectors.get(name)
        if detector is None:
            return AnomalyState.unavailable(name, stamp)
        frame = self._model_frame(name)
        if frame.empty:
            return AnomalyState.unavailable(
                name, stamp, "No rows have been simulated yet, so there is nothing to score."
            )
        report = detector.report(frame, frame.index[-1], rule_engine=self._rule_hook())
        return AnomalyState.from_report(report)

    # -- Model A (PRD 13.1, item 10) ------------------------------------------------------------
    def get_predictions(self, dataset: str = "kiln") -> PredictionSet:
        """Model A's horizons for the current row, grouped by horizon and kept out of OBSERVED.

        ``current`` is the observed value of each predicted target and carries
        :data:`Provenance.OBSERVED`; the horizons carry :data:`Provenance.PREDICTION`. Item 10 wants
        the two shown side by side, and the payload keeps them in separate channels so a view can
        line them up without a bare number ever losing which of the two it is.
        """
        self._started()
        name = self._dataset(dataset)[0]
        stamp = str(self.timestamp())
        bundle = self._predictions.get(name)
        if bundle is None or not bundle.available:
            return PredictionSet.unavailable(name, stamp)
        history = self._model_frame(name)
        if history.empty:
            return PredictionSet.unavailable(
                name, stamp, "No rows have been simulated yet, so there is nothing to predict from."
            )
        row = self._row(name)
        by_horizon: dict[int, list[Value]] = {}
        for prediction in bundle.predict(history=history):
            by_horizon.setdefault(int(prediction.horizon_min), []).append(
                self._value(
                    prediction.target,
                    prediction.value,
                    provenance=Provenance.PREDICTION,
                    source=_SOURCE_MODEL_A.format(
                        target=prediction.target, horizon=prediction.horizon_min
                    ),
                    dataset=name,
                    uncertainty=prediction.uncertainty,
                    horizon_min=prediction.horizon_min,
                )
            )
        targets = tuple(
            dict.fromkeys(value.tag for values in by_horizon.values() for value in values)
        )
        return PredictionSet(
            available=bool(by_horizon),
            dataset=name,
            timestamp=stamp,
            current=tuple(
                self._value(
                    target,
                    row.get(target),
                    provenance=Provenance.OBSERVED,
                    source=_SOURCE_OBSERVED[self.mode],
                    dataset=name,
                )
                for target in targets
            ),
            by_horizon={
                horizon: tuple(values) for horizon, values in sorted(by_horizon.items())
            },
            horizons_min=tuple(sorted(by_horizon)),
            missing=tuple(
                f"{target} t+{horizon}min" for target, horizon in bundle.missing()
            ),
            model_version=self._model_version(bundle),
        )

    @staticmethod
    def _model_version(bundle: Any) -> str:
        """The artefact versions behind one bundle, as the model card names them (PRD 13.4)."""
        versions = bundle.describe().get("model_versions", ())
        return ",".join(str(version) for version in versions)

    # -- Model C (PRD 14, 16, 17; items 15-17) ---------------------------------------------------
    def _regime_name(self) -> str | None:
        """The regime label the optimizer's PRD 14.3 regime check compares against, if known."""
        regime = self.get_operating_regime()
        return regime.label or None

    def get_optimization(self, *, mode: str = "NORMAL") -> OptimizationView:
        """Model C's run at the current operating point, refusals included (items 15-16).

        The optimizer is handed the *observed* row and the joined history, never the simulator's
        private state: the envelope and OOD gates have to see the same numbers an operator would.
        A refusal comes back as a populated view with :attr:`OptimizationView.refused` set, because
        item 16 makes "no safe recommendation" a display state rather than an empty card.
        """
        self._started()
        stamp = str(self.timestamp())
        if self._optimizer is None:
            return OptimizationView.unavailable(stamp, mode)
        inputs = self._optimizer_inputs()
        if not inputs:
            return OptimizationView.unavailable(
                stamp, mode, "No operating point has been simulated yet, so there is nothing to optimize."
            )
        result = self._optimizer.optimize(
            inputs=inputs,
            observed_state=self._flat_row(),
            history=self._model_history(),
            mode=mode,
            timestamp=self.timestamp(),
            regime=self._regime_name(),
        )
        return OptimizationView.from_result(result)

    def run_what_if(
        self,
        changes: Mapping[str, float] | None = None,
        *,
        delta_fractions: Mapping[str, float] | None = None,
        mode: str = "NORMAL",
    ) -> WhatIfView:
        """Answer one operator what-if from the current operating point (PRD 16, item 17).

        ``clip_to_bounds=True`` because every caller of this method is slider-shaped: a slider
        cannot be dragged past its own end, so a value at the end is a legitimate request to sit on
        the limit rather than a malformed one to reject. The engine still records the clip in the
        panel's notes, so the operator is told the request was trimmed.

        Timing is measured here rather than inside the engine: the number is a property of this
        machine on this run, and a reproducible engine cannot own a field that changes when
        nothing else does.
        """
        self._started()
        stamp = str(self.timestamp())
        if self._what_if is None:
            return WhatIfView.unavailable(stamp, mode)
        inputs = self._optimizer_inputs()
        if not inputs:
            return WhatIfView.unavailable(
                stamp, mode, "No operating point has been simulated yet, so there is nothing to vary."
            )
        started = time.perf_counter()
        result = self._what_if.run(
            inputs=inputs,
            changes=changes,
            delta_fractions=delta_fractions,
            observed_state=self._flat_row(),
            history=self._model_history(),
            mode=mode,
            timestamp=self.timestamp(),
            clip_to_bounds=True,
        )
        return WhatIfView.from_result(
            result, timestamp=self.timestamp(), runtime_s=time.perf_counter() - started
        )

    def what_if_sliders(self, *, mode: str = "NORMAL") -> tuple[Mapping[str, Any], ...]:
        """One PRD 17 slider spec per manipulated variable, at the current operating point.

        The current value is the *observed* setpoint where an instrument reports it, and the twin's
        own input otherwise; :meth:`_optimizer_inputs` already resolves that precedence, so a
        slider opens exactly where the optimizer starts. Empty when Model C is absent - a slider
        whose bounds nothing owns would be a made-up limit (item 5).
        """
        self._started()
        if self._what_if is None:
            return ()
        inputs = self._optimizer_inputs()
        baseline = self._what_if.space.baseline(inputs)
        return tuple(
            self._what_if.slider(name, baseline[name], mode)
            for name in self._what_if.variables()
            if name in baseline
        )

    # -- clock control: PLAY / PAUSE / STEP / RESET (item 7) and the scrubber (item 8) -----------
    def advance(self, minutes: float = 1.0) -> StateSnapshot:
        """Move time forward and return the new observable state.

        In ``LIVE`` this steps the driver; in ``REPLAY`` it moves the cursor over rows that already
        exist. PLAY and STEP are the same call from the provider's side - PLAY is the dashboard
        repeating it on a timer, which is why there is no ``play`` method here (item 7).

        The step is expressed in *minutes* rather than rows because that is the unit both modes
        share: a live step is ``ScenarioDriver.dt_minutes`` long and a replay row is the export's
        one-minute sample, so a caller can ask for the same amount of plant time either way.
        """
        span = float(minutes)
        if span <= 0.0:
            raise ValueError(f"minutes must be positive; got {minutes!r}")
        if self.mode == LIVE:
            self._started()
            steps = max(1, int(round(span / self._driver.dt_minutes)))
            self._driver.step(steps)
            return self.get_current_state()
        rows = len(self._run.index)
        step_minutes = self._settings.replay.step_minutes
        self._cursor = min(rows - 1, self._cursor + max(1, int(round(span / step_minutes))))
        return self.get_current_state()

    def reset(self) -> None:
        """Back to the start of the session (RESET, item 7).

        Both modes are reset, not just the active one: RESET means "start the demo over", and a
        dashboard that switched modes mid-session would otherwise find the other mode still sitting
        where it was left.
        """
        if self._driver is not None:
            self._driver.reset()
        if self._run is not None:
            self._cursor = min(
                len(self._run.index) - 1, self._settings.history.sparkline_points
            )

    def scenarios(self) -> tuple[Mapping[str, Any], ...]:
        """The selectable scenarios, as configuration describes them (item 18).

        ``REPLAY`` has none: the recorded run already happened under whichever schedule produced
        it, and offering a scenario switch there would imply the past can be re-driven.
        """
        if self._driver is None or self.mode != LIVE:
            raise CapabilityError(
                f"{self.name} exposes scenarios in {LIVE} only; current mode is {self.mode}"
            )
        return self._driver.scenario_options()

    def select_scenario(self, scenario: str) -> None:
        """Switch the driving scenario (item 18).

        The plant keeps its state and the setpoints ramp into the new episode - that is the
        driver's own PRD 11.3 behaviour and it is the point: a scenario change is a process event
        the operator watches arrive, not a redraw that teleports the twin to a new operating point.
        The regime label therefore changes on the next step, not on this call.
        """
        if self._driver is None or self.mode != LIVE:
            raise CapabilityError(
                f"{self.name} selects scenarios in {LIVE} only; current mode is {self.mode}"
            )
        self._driver.select(scenario)

    def seek(self, timestamp: Any) -> StateSnapshot:
        """Move the replay cursor to the recorded row at or before ``timestamp`` (item 8).

        "At or before" rather than "nearest": a scrubber dropped between two samples should show
        the last row that actually happened, never a row from the future of the position it names.
        """
        if self._run is None or self.mode != REPLAY:
            raise CapabilityError(
                f"{self.name} seeks in {REPLAY} only; current mode is {self.mode}"
            )
        index = pd.DatetimeIndex(self._run.index)
        wanted = pd.Timestamp(timestamp)
        first, last = index[0], index[-1]
        if wanted < first or wanted > last:
            raise ValueError(
                f"{wanted} is outside the recorded window {first} .. {last}"
            )
        self._cursor = int(index.searchsorted(wanted, side="right")) - 1
        return self.get_current_state()

    def window(self) -> tuple[Any, Any] | None:
        """First and last recorded timestamp, or ``None`` when there is nothing to scrub."""
        if self._run is None:
            return None
        index = pd.DatetimeIndex(self._run.index)
        return (pd.Timestamp(index[0]), pd.Timestamp(index[-1]))

    # -- self-description (NFR-6, item 20) ------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """What this provider is and what it can answer - the header's honesty line (item 20)."""
        payload = super().describe()
        payload["mode"] = self.mode
        payload["position"] = self.position()
        replay_window = self.window()
        payload["window"] = None if replay_window is None else [str(end) for end in replay_window]
        payload["models"] = {
            "prediction": sorted(self._predictions),
            "anomaly": sorted(self._detectors),
            "optimization": self._optimizer is not None,
            "what_if": self._what_if is not None,
        }
        payload["bands"] = self._bands.describe()
        payload["note"] = SPECIFIC_VS_TOTAL_NOTE
        return payload


__all__ = ["PROVIDER_NAME", "SyntheticDataProvider"]
