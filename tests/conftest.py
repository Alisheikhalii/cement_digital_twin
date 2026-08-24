"""Shared fixtures for the process-model and ML test suites (PRD v1.1.1 Section 34).

These tests cover the layers the PRD requires to be tested *alongside* their implementation:
the fuel-energy units (9.2), the enforced conservation closures (9.3/10.2), the
per-relationship delay framework (9.4/10.3), the directional behaviour of Section 20.8, and
the ML layer of Sections 13.1-13.3 (feature construction, splits, both models, leakage).

Every tolerance comes from ``configs/*.yaml`` - a test must not hard-code the bound it is
checking, or NFR-10 could be relaxed by editing the test instead of the config.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import pytest

from src.config import KILN, MILL, ML, OPTIMIZATION, SCENARIOS, load_config

#: Simulation step used throughout the suite (PRD 11.2 sampling interval is 1 minute).
STEP_SECONDS = 60.0

#: ASSUMPTION representative horizon for the conservation tests: 4 h is long enough to cover
#: the slowest configured relationship (``load_to_bearing_temperature``, tau = 30 min) several
#: times over, and the kiln residence time (35 min) about seven times.
HORIZON_MINUTES = 240

#: ASSUMPTION horizon of the ML fixtures: 3 days at 1 min = 4,320 rows. Long enough for the
#: scheduler to visit all 14 PRD 11.4 regimes at least once (so a scenario holdout exists and the
#: forest sees faults it must *not* be fitted on), short enough that one generated run plus a
#: two-horizon training pass stays inside a minute or so. It is deliberately *shorter* than the
#: configured ``duration_days``: these tests pin behaviour and contracts, never metric values, and
#: :func:`src.models.model_card._short_run` is what flags a card built at this length.
ML_HORIZON_DAYS = 3.0

#: Warm-up discarded before the ML fixtures' first exported row (PRD 11.2).
ML_WARMUP_MINUTES = 180.0


# -- configs -------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def kiln_config():
    return load_config(KILN)


@pytest.fixture(scope="session")
def mill_config():
    return load_config(MILL)


@pytest.fixture(scope="session")
def ml_config():
    """``configs/ml.yaml`` - horizons, lags, split fractions, anomaly thresholds (PRD 13)."""
    return load_config(ML)


@pytest.fixture(scope="session")
def scenario_config():
    return load_config(SCENARIOS)


# -- twins ---------------------------------------------------------------------------------
@pytest.fixture
def kiln():
    """A fresh :class:`KilnTwin` on its reference operating point."""
    from src.process_models.kiln import KilnTwin

    return KilnTwin()


@pytest.fixture
def mill():
    """A fresh :class:`CementMillTwin` on its reference operating point."""
    from src.process_models.mill import CementMillTwin

    return CementMillTwin()


@pytest.fixture
def plant():
    """A fresh :class:`PlantTwin` (both lines on their reference points)."""
    from src.process_models.plant import PlantTwin

    return PlantTwin()


# -- tolerances (read from config, never hard-coded in a test) ------------------------------
@pytest.fixture(scope="session")
def kiln_energy_tolerance_pct(kiln_config) -> float:
    """NFR-10 energy bound: ``energy_balance.unaccounted_loss_max_fraction`` as a percent.

    PRD 9.3 is explicit that this number is a *test tolerance bound*, never a fit parameter -
    which is exactly why the test reads it rather than restating it.
    """
    return 100.0 * float(kiln_config.get_path("energy_balance.unaccounted_loss_max_fraction"))


@pytest.fixture(scope="session")
def kiln_mass_tolerance_pct(kiln_config) -> float:
    return float(kiln_config.get_path("mass_balance.tolerance_pct"))


@pytest.fixture(scope="session")
def mill_mass_tolerance_pct(mill_config) -> float:
    return float(mill_config.get_path("mass_balance.tolerance_pct"))


# -- helpers -------------------------------------------------------------------------------
@pytest.fixture
def step_trajectory() -> Callable[..., Any]:
    """Build a two-level input trajectory: ``hold_minutes`` at ``base``, then ``base | step``.

    This is the shape every Section 20.8 perturbation test needs - a settled stretch, one step
    change, then long enough to see the delayed response arrive - and returning a DataFrame
    keeps the tests on the same ``Twin.simulate_scenario`` path the optimizer and What-if use.
    """
    import pandas as pd

    def build(
        base: Mapping[str, float],
        step: Mapping[str, float] | None = None,
        hold_minutes: int = 30,
        step_minutes: int = 120,
    ) -> "pd.DataFrame":
        after = dict(base)
        after.update(step or {})
        rows = [dict(base) for _ in range(int(hold_minutes))]
        rows += [dict(after) for _ in range(int(step_minutes))]
        return pd.DataFrame(
            rows,
            index=pd.date_range("2026-01-01", periods=len(rows), freq="1min"),
        )

    return build


@pytest.fixture
def relative_drift() -> Callable[[Mapping[str, float], Mapping[str, float]], float]:
    """Largest relative change between two output dictionaries (scaled, so 0-valued tags are safe)."""

    def drift(first: Mapping[str, float], second: Mapping[str, float]) -> float:
        largest = 0.0
        for key, value in first.items():
            other = float(second.get(key, value))
            scale = max(1.0, abs(float(value)))
            largest = max(largest, abs(other - float(value)) / scale)
        return largest

    return drift


# -- ML layer (PRD 13) ----------------------------------------------------------------------
# One generated run is shared by every ML module: the simulator is the expensive part, and each
# module then builds only the features/models it actually asserts on. Session scope, so `pytest
# tests/` pays for the run once.
@pytest.fixture(scope="session")
def ml_simulation():
    from src.simulation.simulation_config import SimulationConfig

    return SimulationConfig.from_config(
        duration_minutes=ML_HORIZON_DAYS * 24 * 60.0, warmup_minutes=ML_WARMUP_MINUTES
    )


@pytest.fixture(scope="session")
def ml_run(ml_simulation):
    """One :class:`~src.data_generation.generator.GeneratedRun` for the whole ML suite."""
    from src.data_generation.generator import DatasetGenerator

    return DatasetGenerator(ml_simulation).run()


@pytest.fixture(scope="session")
def kiln_frame(ml_run):
    """The *measured* kiln dataset of PRD 12.1, positionally indexed.

    Positional indexing (rather than the timestamp) is what the split helpers and
    :class:`~src.features.lag_features.FeatureMatrix` reason about, so every ML fixture hands the
    same shape around.
    """
    return ml_run.datasets["kiln"].reset_index(drop=True)


@pytest.fixture(scope="session")
def kiln_truth_frame(ml_run):
    """The noise-free kiln companion (PRD 20 item 2 evaluation reference; never a feature)."""
    return ml_run.truth["kiln"].reset_index(drop=True)


@pytest.fixture(scope="session")
def mill_frame(ml_run):
    return ml_run.datasets["mill"].reset_index(drop=True)


@pytest.fixture(scope="session")
def mill_truth_frame(ml_run):
    return ml_run.truth["mill"].reset_index(drop=True)


@pytest.fixture(scope="session")
def kiln_builder():
    from src.features.lag_features import FeatureBuilder

    return FeatureBuilder("kiln")


@pytest.fixture(scope="session")
def kiln_matrices(kiln_builder, kiln_frame, kiln_truth_frame):
    """One :class:`FeatureMatrix` per configured horizon (PRD 13.1's four mandatory horizons)."""
    return kiln_builder.build_all(kiln_frame, truth=kiln_truth_frame)


@pytest.fixture(scope="session")
def kiln_matrix(kiln_builder, kiln_matrices):
    """The shortest-horizon matrix - the cheapest one that still exercises the full lag path."""
    return kiln_matrices[min(kiln_builder.horizons_min)]


@pytest.fixture(scope="session")
def kiln_splits(kiln_matrix):
    """Both PRD 13.3 splits of :func:`kiln_matrix`."""
    from src.features.splits import build_splits

    return build_splits(kiln_matrix)


#: Targets/horizons the Model A fixtures train on. A subset, and stated as one: PRD 13.1's full
#: grid is exercised by ``test_model_a.py::test_every_configured_target_and_horizon_is_trained``
#: through the *spec*, which needs no fit, while the behavioural tests need a real fit and so use
#: the shortest and longest horizons of one target - the two ends of the lag-sizing rule.
ML_FIXTURE_TARGET = "burning_zone_temperature"


@pytest.fixture(scope="session")
def ml_fixture_horizons(kiln_builder) -> tuple[int, ...]:
    horizons = kiln_builder.horizons_min
    return (min(horizons), max(horizons))


@pytest.fixture(scope="session")
def trained_kiln(kiln_frame, kiln_truth_frame, ml_fixture_horizons):
    """A real Model A training pass: one kiln target at the shortest and longest horizon."""
    from src.models.train import train_model_a

    return train_model_a(
        "kiln",
        kiln_frame,
        truth=kiln_truth_frame,
        horizons_min=list(ml_fixture_horizons),
        targets=[ML_FIXTURE_TARGET],
    )


@pytest.fixture(scope="session")
def kiln_model_b(kiln_frame):
    """A full Model B pass over the kiln frame: all three blocks, each independently fitted."""
    from src.models.train import train_model_b

    return train_model_b("kiln", kiln_frame)


@pytest.fixture(scope="session")
def kiln_detector(kiln_model_b):
    """The shipped (``all_rows``) detector of :func:`kiln_model_b` - the one the UI/gate would use."""
    return kiln_model_b.detector


# -- optimization layer (PRD 14 / 16) ---------------------------------------------------------
# Model C needs more than the ML fixtures above supply. An Optimizer consults Model A for *both*
# datasets - the kiln and the cement mill each carry PRD 16.1 decision variables - and Model B for
# both, so the single-dataset `trained_kiln` / `kiln_model_b` pair cannot stand in for it. What is
# deliberately NOT widened is the training grid: only `uncertainty.optimizer_targets` are fitted,
# at the same two horizons the ML fixtures use. Those are the targets the uncertainty gate blocks
# on, so a bundle without them would make every optimization test read the same "uncertainty could
# not be checked" answer instead of the behaviour it is there to pin.

#: ASSUMPTION history length of the optimization fixtures: 24 h at 1 min. Sized by the widest
#: window any consumer reads - ``baselines.historical_window_hours`` - so all five PRD 14.5 rows
#: are genuinely available and the baseline test asserts on a populated table rather than on the
#: "unavailable, and here is why" path (which has its own test).
OPTIMIZATION_HISTORY_ROWS = 24 * 60

#: Sentinel for :func:`make_optimizer`: "argument not supplied", so a test can pass ``None``
#: explicitly to *remove* a piece of the wiring and get the missing-model behaviour.
_FIXTURE_DEFAULT: Any = object()


@pytest.fixture(scope="session")
def optimization_config():
    """``configs/optimization.yaml`` - decision variables, constraints, weights, search knobs."""
    return load_config(OPTIMIZATION)


@pytest.fixture(scope="session")
def optimizer_targets(ml_config) -> dict[str, tuple[str, ...]]:
    """``uncertainty.optimizer_targets``, grouped by the dataset that owns each one.

    Read from config rather than restated: the fixtures must train exactly the targets the gate
    blocks on, and if that list changes the fixtures have to follow it, not lag behind it.
    """
    from src.optimization.prediction import objective_targets

    wanted = objective_targets(ml_config)
    return {
        dataset: tuple(
            str(target)
            for target in ml_config.get_path(f"prediction.targets.{dataset}")
            if str(target) in wanted
        )
        for dataset in ("kiln", "mill")
    }


@pytest.fixture(scope="session")
def optimization_predictions(
    kiln_frame,
    kiln_truth_frame,
    mill_frame,
    mill_truth_frame,
    ml_fixture_horizons,
    optimizer_targets,
):
    """One real :class:`PredictionBundle` per dataset - a genuine fit, not a stub.

    The gate under test is Model A's own uncertainty, so a fake model with an invented spread would
    test the fixture rather than the platform. Two (target, horizon) pairs per dataset is the
    cheapest fit that still gives the gate a measured spread to read and the stability term a
    cross-horizon spread to compute.
    """
    from src.models.train import train_model_a
    from src.optimization.prediction import PredictionBundle

    sources = {"kiln": (kiln_frame, kiln_truth_frame), "mill": (mill_frame, mill_truth_frame)}
    bundles = {}
    for dataset, targets in optimizer_targets.items():
        frame, truth = sources[dataset]
        result = train_model_a(
            dataset,
            frame,
            truth=truth,
            horizons_min=list(ml_fixture_horizons),
            targets=list(targets),
        )
        bundles[dataset] = PredictionBundle.from_result(result)
    return bundles


@pytest.fixture(scope="session")
def optimization_anomaly_models(kiln_frame, mill_frame, ml_config):
    """A fitted Model B scorer per dataset, with the training scores its OOD threshold reads.

    Fitted on the leading ``splits.chronological_train_fraction`` of each frame - the same fraction
    PRD 13.3 trains on - so the percentile the threshold is taken from comes from a block the
    forest actually saw, exactly as it would in the notebook.
    """
    from src.anomaly_detection.detector import AnomalyDetector

    fraction = float(ml_config.get_path("splits.chronological_train_fraction"))
    scorers: dict[str, Any] = {}
    references: dict[str, Any] = {}
    for dataset, frame in (("kiln", kiln_frame), ("mill", mill_frame)):
        training = frame.iloc[: int(len(frame) * fraction)]
        detector = AnomalyDetector(dataset).fit(training)
        scorers[dataset] = detector.scorer
        references[dataset] = detector.scorer.score(training).score
    return scorers, references


@pytest.fixture(scope="session")
def optimization_history(kiln_frame, mill_frame):
    """The trailing 24 h of both datasets, joined on the timestamp - one ``history`` frame.

    The optimizer takes a single frame that has to cover everything it may read: Model A's lag
    features for both units, the PRD 14.5 baseline windows, the rule engine's rate-of-change
    window and the regime label. Timestamp-indexed on purpose - that is the branch
    ``baselines._trailing_window`` takes in the notebook, and the positional fallback is what a
    test would otherwise exercise by accident.
    """
    import pandas as pd

    indexed = {}
    for dataset, frame in (("kiln", kiln_frame), ("mill", mill_frame)):
        tail = frame.tail(OPTIMIZATION_HISTORY_ROWS)
        indexed[dataset] = tail.drop(columns=["timestamp"]).set_index(
            pd.to_datetime(tail["timestamp"])
        )
    kiln, mill = indexed["kiln"], indexed["mill"]
    shared = [column for column in mill.columns if column in kiln.columns]
    return kiln.join(mill.drop(columns=shared))


@pytest.fixture(scope="session")
def optimizer_inputs() -> dict[str, float]:
    """The reference input vector the optimization tests start from - a copy, never a live twin's.

    Taken off a throwaway :class:`PlantTwin` so that no test can perturb the starting point of
    another by settling the twin it shares.
    """
    from src.process_models.plant import PlantTwin

    return dict(PlantTwin().inputs)


@pytest.fixture(scope="session")
def make_optimizer(optimization_predictions, optimization_anomaly_models):
    """Factory: an :class:`Optimizer` on a *fresh* twin with the fixture Model A/Model B wiring.

    A factory rather than a value because several gate tests need one piece of the wiring
    deliberately removed (``predictions=None`` for the model-availability gate, ``scorer=None`` for
    the unavailable-OOD path) or one config knob overridden, and a shared instance cannot express
    that. Passing ``None`` removes a piece; omitting the argument keeps the fixture default.
    """
    from src.optimization.optimizer import Optimizer
    from src.process_models.plant import PlantTwin

    scorers, references = optimization_anomaly_models

    def build(*, predictions=_FIXTURE_DEFAULT, scorer=_FIXTURE_DEFAULT,
              reference_scores=_FIXTURE_DEFAULT, twin=None, **kwargs):
        return Optimizer.from_twin(
            PlantTwin() if twin is None else twin,
            predictions=(
                optimization_predictions if predictions is _FIXTURE_DEFAULT else predictions
            ),
            scorer=scorers if scorer is _FIXTURE_DEFAULT else scorer,
            reference_scores=(
                references if reference_scores is _FIXTURE_DEFAULT else reference_scores
            ),
            **kwargs,
        )

    return build


@pytest.fixture(scope="session")
def optimizer(make_optimizer):
    """The default-wired optimizer, shared by every test that only *reads* a run of it."""
    return make_optimizer()


@pytest.fixture(scope="session")
def normal_result(optimizer, optimizer_inputs, optimization_history):
    """One shared PRD 14.1 run in Normal Mode - the reference result of the whole module.

    Session-scoped because a full search is the expensive operation in this suite and every test
    that asserts on its *shape* can read the same run. Tests that need a different wiring, a
    different mode or a second independent run build their own through :func:`make_optimizer`.
    """
    return optimizer.optimize(
        inputs=optimizer_inputs, history=optimization_history, mode="NORMAL"
    )


@pytest.fixture(scope="session")
def what_if_engine(optimizer):
    """A :class:`WhatIfEngine` over the same optimizer, so AC-8 compares like with like."""
    from src.optimization.what_if import WhatIfEngine

    return WhatIfEngine(optimizer)
