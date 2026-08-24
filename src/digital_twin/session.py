"""``DashboardSession`` - the application/domain layer between the models and the dashboard.

Directive item 21 asks for one direction of dependency::

    DataProvider  ->  Application / Domain Services  ->  Digital Twin / ML / Optimization
                                  |
                                  v
                        Dashboard API / State  ->  Visualization

This module is the second box. It is the *only* place that knows how the four validated layers of
Tasks #2-#5 are wired together: where Model A's artefacts live, which rows Model B is fitted on,
which twin the optimizer searches over, how a live clock is primed and how a replay window is
built. Everything above it - :mod:`src.digital_twin.state`, the views, the presentation mode, the
demo sequence - receives a :class:`~src.digital_twin.provider.DataProvider` and a
:class:`~src.visualization.clock.Clock` and knows nothing else.

Three rules it holds itself to.

**It trains nothing and changes no model.** Model A is *loaded* from ``models/registry.json`` -
the artefacts Task #4 selected and registered. Model B is fitted here because a detector is a
cheap, deterministic fit over rows the session already has (1.7 s over 30 days) and no artefact
format exists for it, but it is fitted with :class:`AnomalyDetector`'s own defaults on the leading
``splits.chronological_train_fraction`` of the frame - the same block PRD 13.3 trains on and the
same call ``tests/conftest.py`` makes. No threshold, weight, range or objective is touched.

**A missing layer is a reported state, not a substitute.** If ``models/registry.json`` is absent
the session still builds: :meth:`ModelLayer.notes` says why, the provider's
:meth:`capabilities` reports ``predictions=False``, and the prediction panel renders its
documented unavailable state (NFR-6). The dashboard is demonstrable on a machine with no trained
models; it just says so on the screen instead of inventing numbers.

**The replay window is regenerated, not reconstructed.** A replay needs a whole
:class:`~src.data_generation.generator.GeneratedRun`: the regime episodes that label each row, the
noise-free companion frames, the run's own :class:`SimulationConfig`. ``data/synthetic/*.parquet``
carries the rows but not the schedule that produced them, so rebuilding a run from the export
would mean *inventing* an episode plan. The session instead re-runs the seeded generator, which is
a pure function of the configs and the seed: with ``session.replay_days: null`` that reproduces
the exported dataset exactly, and with the default 3 days it is a shorter run of the same kind,
built in under two seconds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import pandas as pd

from src.config import KILN, ML, MILL, SCENARIOS, Config, ConfigError, load_config
from src.data_generation.generator import DATASETS, DatasetGenerator, GeneratedRun
from src.digital_twin.payloads import LIVE, REPLAY
from src.digital_twin.provider import DataProvider
from src.digital_twin.scenario_driver import ScenarioDriver
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.synthetic import SyntheticDataProvider
from src.simulation.simulation_config import SimulationConfig
from src.visualization.clock import Clock

#: Where the exported dataset is read from when the session is not handed frames of its own.
#: ``None`` means :data:`src.paths.DATA_SYNTHETIC_DIR`, which is what :mod:`src.data_generation`
#: writes to; a caller passing a directory is the offline/factory-laptop case.
DEFAULT_DATA_DIR: Final[Path | None] = None

#: Reasons a layer can be absent, in the words the dashboard shows beside the empty panel.
NO_REGISTRY_NOTE: Final = (
    "Model A is not available: no model registry was found, so the prediction panel shows no "
    "number rather than a substitute one. Train and register Model A to populate it."
)
NO_TRAINING_NOTE: Final = (
    "Model B is not available: this session has no historical rows to fit the detector on, so "
    "the anomaly panel shows its unavailable state."
)
NO_OPTIMIZER_NOTE: Final = (
    "Model C is not available: the optimizer needs Model A's predictions and Model B's scorer, "
    "and at least one of the two is missing in this session."
)
DATASET_MISMATCH_NOTE: Final = (
    "The registered Model A artefacts were trained on a different dataset than the one this "
    "session loaded. The predictions are the registered models' own output; their training "
    "domain, and therefore the envelope check, belongs to the dataset they were trained on."
)


# =============================================================================
# The model layer
# =============================================================================
@dataclass(frozen=True, slots=True)
class ModelLayer:
    """The three model layers the provider consults, plus why any of them is missing.

    Held as one object so :meth:`DashboardSession.build` can be handed a prepared layer (which is
    what the tests do - fitting Model B twice per test module would dominate the suite) without
    every caller having to know the four keyword arguments
    :class:`~src.digital_twin.synthetic.SyntheticDataProvider` takes.
    """

    predictions: Mapping[str, Any] = field(default_factory=dict)
    detectors: Mapping[str, Any] = field(default_factory=dict)
    scorers: Mapping[str, Any] = field(default_factory=dict)
    reference_scores: Mapping[str, Any] = field(default_factory=dict)
    optimizer: Any = None
    what_if: Any = None
    notes: tuple[str, ...] = ()
    model_versions: Mapping[str, str] = field(default_factory=dict)
    dataset_match: bool = True
    build_seconds: Mapping[str, float] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        """JSON-serializable summary; the source of the report's "what is wired in" table."""
        return {
            "predictions": {
                dataset: {
                    "targets": list(bundle.targets),
                    "horizons_min": list(bundle.horizons_min),
                    "available": bool(bundle.available),
                }
                for dataset, bundle in sorted(self.predictions.items())
            },
            "detectors": sorted(self.detectors),
            "optimizer": self.optimizer is not None,
            "what_if": self.what_if is not None,
            "model_versions": dict(sorted(self.model_versions.items())),
            "dataset_match": self.dataset_match,
            "notes": list(self.notes),
            "build_seconds": {
                key: round(float(value), 3) for key, value in sorted(self.build_seconds.items())
            },
        }


def load_training_frames(
    directory: Path | str | None = DEFAULT_DATA_DIR,
    *,
    datasets: Sequence[str] = DATASETS,
    suffix: str = "parquet",
) -> dict[str, pd.DataFrame] | None:
    """The exported measured frames, or ``None`` when nothing has been exported yet.

    ``None`` rather than an exception because "no dataset on disk" is a normal state of a fresh
    checkout, and the caller's answer to it is to regenerate rather than to fail.
    """
    from src.data_generation.export import load_dataset

    frames: dict[str, pd.DataFrame] = {}
    for dataset in datasets:
        try:
            frames[dataset] = load_dataset(dataset, directory, suffix=suffix)  # type: ignore[arg-type]
        except (ConfigError, FileNotFoundError, OSError):
            return None
    return frames


def build_model_layer(
    frames: Mapping[str, pd.DataFrame] | None,
    *,
    ml_config: Config | None = None,
    kiln_config: Config | None = None,
    mill_config: Config | None = None,
    scenarios: Config | None = None,
    registry_path: Path | str | None = None,
    artifact_dir: Path | str | None = None,
    datasets: Sequence[str] = DATASETS,
) -> ModelLayer:
    """Load Model A, fit Model B, assemble Model C - or report what could not be assembled.

    ``frames`` are *measured* frames (PRD 12.1 shape). They are used for two things and no third:
    fitting Model B on the leading training fraction, and giving its OOD gate the training scores
    to compare against. Nothing here reads the noise-free companion, because nothing the dashboard
    shows may be conditioned on the simulator's private state.
    """
    ml = ml_config if ml_config is not None else load_config(ML)
    notes: list[str] = []
    timings: dict[str, float] = {}

    predictions, versions, dataset_match, prediction_notes = _load_predictions(
        frames,
        ml=ml,
        registry_path=registry_path,
        artifact_dir=artifact_dir,
        datasets=datasets,
        timings=timings,
    )
    notes.extend(prediction_notes)

    detectors, scorers, references, detector_notes = _fit_detectors(
        frames, ml=ml, scenarios=scenarios, datasets=datasets, timings=timings
    )
    notes.extend(detector_notes)

    optimizer: Any = None
    what_if: Any = None
    if predictions and scorers:
        started = time.perf_counter()
        from src.optimization.optimizer import Optimizer
        from src.optimization.what_if import WhatIfEngine
        from src.process_models.plant import PlantTwin

        # A twin of its own, never the live driver's: the optimizer steps a twin through every
        # candidate it evaluates, and sharing the session's twin would let a search move the
        # operating point the dashboard is displaying.
        optimizer = Optimizer.from_twin(
            PlantTwin(
                kiln_config if kiln_config is not None else load_config(KILN),
                mill_config if mill_config is not None else load_config(MILL),
            ),
            predictions=predictions,
            scorer=scorers,
            reference_scores=references,
            ml_config=ml,
            scenarios=scenarios,
        )
        what_if = WhatIfEngine(optimizer)
        timings["optimizer"] = time.perf_counter() - started
    else:
        notes.append(NO_OPTIMIZER_NOTE)

    return ModelLayer(
        predictions=predictions,
        detectors=detectors,
        scorers=scorers,
        reference_scores=references,
        optimizer=optimizer,
        what_if=what_if,
        notes=tuple(notes),
        model_versions=versions,
        dataset_match=dataset_match,
        build_seconds=timings,
    )


def _load_predictions(
    frames: Mapping[str, pd.DataFrame] | None,
    *,
    ml: Config,
    registry_path: Path | str | None,
    artifact_dir: Path | str | None,
    datasets: Sequence[str],
    timings: dict[str, float],
) -> tuple[dict[str, Any], dict[str, str], bool, list[str]]:
    """One :class:`PredictionBundle` per dataset, rebuilt from the registered artefacts.

    Every registered ``(target, horizon)`` pair is loaded, not just the optimizer's targets:
    directive item 10 asks the prediction view for the full horizon grid, and the optimizer reads
    the subset of it that its own config names.
    """
    from src.models.registry import entry_matches_dataset, load_model_a, read_registry
    from src.optimization.prediction import PredictionBundle

    started = time.perf_counter()
    try:
        registry = read_registry(registry_path)
    except (ConfigError, FileNotFoundError, OSError, ValueError):
        return {}, {}, True, [NO_REGISTRY_NOTE]
    entries = list(registry.get("models", ()))
    if not entries:
        return {}, {}, True, [NO_REGISTRY_NOTE]

    bundles: dict[str, Any] = {}
    versions: dict[str, str] = {}
    for dataset in datasets:
        models = load_model_a(
            dataset,
            registry_path=registry_path,
            directory=artifact_dir,
            config=ml,
        )
        if not models:
            continue
        bundles[dataset] = PredictionBundle(dataset, models, config=ml)
        versions[dataset] = ",".join(
            sorted({str(model.model_version) for model in models.values()})
        )
    timings["model_a_load"] = time.perf_counter() - started

    notes: list[str] = []
    if not bundles:
        notes.append(NO_REGISTRY_NOTE)
    match = True
    if frames:
        # ``entry_matches_dataset`` hashes the frame the way the trainer did, so a mismatch is a
        # fact about provenance worth stating rather than a reason to refuse the artefacts.
        match = any(
            entry_matches_dataset(entry, frames[str(entry.get("dataset"))])
            for entry in entries
            if str(entry.get("dataset")) in frames
        )
        if not match:
            notes.append(DATASET_MISMATCH_NOTE)
    return bundles, versions, match, notes


def _fit_detectors(
    frames: Mapping[str, pd.DataFrame] | None,
    *,
    ml: Config,
    scenarios: Config | None,
    datasets: Sequence[str],
    timings: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    """A fitted Model B per dataset, with the training scores its OOD threshold reads.

    The fitting block is the leading ``splits.chronological_train_fraction`` of each frame - PRD
    13.3's chronological split, so the percentile the OOD threshold is taken from comes from rows
    the forest actually saw. The remainder of the frame is deliberately unseen: it is what the
    session's own live and replay rows stand in for.
    """
    if not frames:
        return {}, {}, {}, [NO_TRAINING_NOTE]

    from src.anomaly_detection.detector import AnomalyDetector

    started = time.perf_counter()
    fraction = float(ml.get_path("splits.chronological_train_fraction"))
    detectors: dict[str, Any] = {}
    scorers: dict[str, Any] = {}
    references: dict[str, Any] = {}
    notes: list[str] = []
    for dataset in datasets:
        frame = frames.get(dataset)
        if frame is None or frame.empty:
            continue
        rows = frame.reset_index(drop=True)
        training = rows.iloc[: max(1, int(len(rows) * fraction))]
        detector = AnomalyDetector(dataset, config=ml, scenarios=scenarios).fit(training)
        detectors[dataset] = detector
        scorers[dataset] = detector.scorer
        references[dataset] = detector.scorer.score(training).score
    timings["model_b_fit"] = time.perf_counter() - started
    if not detectors:
        notes.append(NO_TRAINING_NOTE)
    return detectors, scorers, references, notes


# =============================================================================
# The session
# =============================================================================
def build_replay_run(
    settings: DashboardSettings,
    *,
    scenarios: Config | None = None,
    kiln_config: Config | None = None,
    mill_config: Config | None = None,
    simulation: SimulationConfig | None = None,
) -> GeneratedRun:
    """A :class:`GeneratedRun` for the scrubber, regenerated from the seeded configuration.

    Deterministic: the generator is a pure function of the configs and the seed, so the same
    ``configs/`` produce the same replay window on every machine and in every session - which is
    what makes the demo sequence of directive item 19 repeatable in front of an audience.
    """
    scenario_config = scenarios if scenarios is not None else load_config(SCENARIOS)
    base = (
        simulation
        if simulation is not None
        else SimulationConfig.from_config(scenario_config)
    )
    minutes = settings.session.replay_minutes(base.duration_minutes)
    if minutes is not None and minutes != base.duration_minutes:
        base = SimulationConfig.from_config(scenario_config, duration_minutes=minutes)
    return DatasetGenerator(
        base,
        scenarios=scenario_config,
        kiln_config=kiln_config,
        mill_config=mill_config,
    ).run()


@dataclass(frozen=True, slots=True)
class DashboardSession:
    """One assembled demonstration session: a provider, a clock and the model layer behind them.

    The dashboard holds this object and reads :attr:`provider` and :attr:`clock` from it. It is a
    convenience, not a second contract: every number a view renders still arrives through
    :class:`~src.digital_twin.provider.DataProvider`.
    """

    provider: DataProvider
    clock: Clock
    settings: DashboardSettings
    models: ModelLayer
    training_source: str
    replay_source: str
    build_seconds: Mapping[str, float] = field(default_factory=dict)

    # -- construction -----------------------------------------------------------------------
    @classmethod
    def build(
        cls,
        *,
        mode: str | None = None,
        live: bool = True,
        replay: bool = True,
        settings: DashboardSettings | None = None,
        models: ModelLayer | None = None,
        training: Mapping[str, pd.DataFrame] | None = None,
        run: GeneratedRun | None = None,
        data_dir: Path | str | None = DEFAULT_DATA_DIR,
        registry_path: Path | str | None = None,
        artifact_dir: Path | str | None = None,
        kiln_config: Config | None = None,
        mill_config: Config | None = None,
        ml_config: Config | None = None,
        scenarios: Config | None = None,
        prime: bool = True,
        regime: str | int | None = None,
    ) -> "DashboardSession":
        """Assemble a session. Every argument exists to let a caller supply a piece it already has.

        ``live`` / ``replay`` select which playback sources are built; at least one is required.
        ``training`` and ``run`` short-circuit the two expensive steps, which is how the test
        suite builds a session in a fraction of a second: it hands over the frames and the run its
        session-scoped fixtures already produced.
        """
        if not live and not replay:
            raise ConfigError(
                "a session needs at least one playback source: live=True (a clock the dashboard "
                "steps) or replay=True (a recorded window it scrubs)"
            )
        resolved = settings if settings is not None else DashboardSettings.from_config()
        timings: dict[str, float] = {}

        generated = run
        frames: Mapping[str, pd.DataFrame] | None = training
        training_source = "caller-supplied frames"
        if frames is None:
            started = time.perf_counter()
            frames = load_training_frames(data_dir)
            timings["load_frames"] = time.perf_counter() - started
            training_source = "data/synthetic export"
        if frames is None:
            # Nothing exported and nothing supplied: regenerate once and use the same run for
            # both jobs, so a fresh checkout pays for one simulation rather than two.
            started = time.perf_counter()
            generated = generated or build_replay_run(
                resolved,
                scenarios=scenarios,
                kiln_config=kiln_config,
                mill_config=mill_config,
            )
            timings["generate_run"] = time.perf_counter() - started
            frames = generated.datasets
            training_source = "regenerated run (no export on disk)"

        replay_source = "not built"
        if replay and generated is None:
            started = time.perf_counter()
            generated = build_replay_run(
                resolved,
                scenarios=scenarios,
                kiln_config=kiln_config,
                mill_config=mill_config,
            )
            timings["generate_run"] = timings.get("generate_run", 0.0) + (
                time.perf_counter() - started
            )
        if replay and generated is not None:
            days = resolved.session.replay_days
            replay_source = (
                f"regenerated run, {len(generated.index)} rows"
                f"{'' if days is None else f' ({days:g} simulated days)'}"
            )

        layer = models
        if layer is None:
            started = time.perf_counter()
            layer = build_model_layer(
                frames,
                ml_config=ml_config,
                kiln_config=kiln_config,
                mill_config=mill_config,
                scenarios=scenarios,
                registry_path=registry_path,
                artifact_dir=artifact_dir,
            )
            timings["model_layer"] = time.perf_counter() - started

        driver: ScenarioDriver | None = None
        if live:
            started = time.perf_counter()
            driver = ScenarioDriver(
                scenarios=scenarios,
                kiln_config=kiln_config,
                mill_config=mill_config,
                regime=regime,
                max_steps=resolved.clock.max_live_steps,
            )
            if prime:
                # The model panels read a trailing window; priming it here means the first frame
                # the audience sees is a populated one rather than four minutes of empty trends.
                minutes = resolved.session.priming_minutes(resolved.history)
                steps = max(1, int(round(minutes / driver.dt_minutes)))
                driver.step(min(steps, driver.max_steps))
            timings["live_driver"] = time.perf_counter() - started

        provider = SyntheticDataProvider(
            driver=driver,
            run=generated if replay else None,
            mode=mode,
            settings=resolved,
            predictions=layer.predictions,
            detectors=layer.detectors,
            optimizer=layer.optimizer,
            what_if=layer.what_if,
            ml_config=ml_config,
            kiln_config=kiln_config,
            mill_config=mill_config,
        )
        return cls(
            provider=provider,
            clock=Clock(provider, resolved),
            settings=resolved,
            models=layer,
            training_source=training_source,
            replay_source=replay_source,
            build_seconds=timings,
        )

    # -- access -----------------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.provider.mode

    def capabilities(self) -> dict[str, Any]:
        return self.provider.capabilities().describe()

    def notes(self) -> tuple[str, ...]:
        """Why any panel will render its unavailable state - shown in the dashboard footer."""
        return self.models.notes

    def describe(self) -> dict[str, Any]:
        """JSON-serializable session summary: what is wired in, from where, and how long it took."""
        window = self.provider.window()
        return {
            "provider": self.provider.name,
            "mode": self.provider.mode,
            "modes": list(self.provider.modes()),
            "capabilities": self.capabilities(),
            "models": self.models.describe(),
            "training_source": self.training_source,
            "replay_source": self.replay_source,
            "replay_window": None if window is None else [str(window[0]), str(window[1])],
            "clock": self.clock.describe(),
            "build_seconds": {
                key: round(float(value), 3) for key, value in sorted(self.build_seconds.items())
            },
            "notes": list(self.notes()),
        }


__all__ = [
    "DATASET_MISMATCH_NOTE",
    "DEFAULT_DATA_DIR",
    "NO_OPTIMIZER_NOTE",
    "NO_REGISTRY_NOTE",
    "NO_TRAINING_NOTE",
    "DashboardSession",
    "ModelLayer",
    "build_model_layer",
    "build_replay_run",
    "load_training_frames",
    "LIVE",
    "REPLAY",
]
