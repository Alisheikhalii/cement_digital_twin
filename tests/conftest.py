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


# =============================================================================
# Task #6 dashboard layer - the Tier-1 stub provider
# =============================================================================
# ``TASK6_RECOVERY_PLAN.md`` Section 7 phase 6B and Section 9 "Tier 1": every Task #6 test that is
# not explicitly an integration test runs against a stub
# :class:`~src.digital_twin.provider.DataProvider`. The reason is measured rather than stylistic -
# the plan's Section 10 records ``DashboardState.views()`` at 7.9 s against
# :class:`~src.digital_twin.synthetic.SyntheticDataProvider` and 0.4 ms against a stub, so that
# 7.9 s is entirely provider data-fetching and a suite built on the real provider would be
# unrunnable. Nothing below reads a CSV, loads a model artefact or touches a process model.
from functools import lru_cache

#: Name the stub reports through the contract, so a header built in a test says what it is.
STUB_PROVIDER_NAME = "StubDataProvider"

#: The one timestamp every stub payload carries. Fixed, so a frame is reproducible and a test can
#: assert all ten screens came from a single read; the stub holds no wall clock (plan BUG 2).
STUB_TIMESTAMP = "2026-01-01T00:00:00"

#: Operating-regime label the stub reports. Deliberately *not* one of the PRD 11.4 regime names: a
#: stub payload must never be mistakable for a configured scenario.
STUB_REGIME_LABEL = "STUB_REGIME"

#: Horizons the stub's Model-A channel serves. Two, not PRD 13.1's four: Tier 1 pins the *channels*
#: a :class:`PredictionSet` keeps apart, and one horizon could not show the ordering is preserved.
STUB_HORIZONS_MIN = (5, 15)

#: The targets that channel forecasts, per dataset - schema tags, so each Value carries a real unit.
STUB_PREDICTION_TARGETS = {
    "kiln": ("burning_zone_temperature", "clinker_production_tph"),
    "mill": ("simulated_blaine_cm2_g", "cement_production_tph"),
}

#: Ensemble spread the stub puts on every forecast Value, in the target's own unit (PRD 13.1.1 - a
#: width, never a confidence percentage).
STUB_UNCERTAINTY = 1.0

#: The value the stub serves for a tag :mod:`src.schema` documents no numeric range for. Such a
#: Value carries :attr:`Status.NO_LIMIT`, the honest state for a number with nothing to judge it by.
STUB_UNRANGED_VALUE = 1.0

#: Equipment health the stub reports (the PRD 9.5 scalar; 1.0 is as-new).
STUB_HEALTH = 1.0

#: Anomaly score the stub reports - no anomaly, so no Tier-1 test depends on Model B's own bands.
STUB_ANOMALY_SCORE = 0.0

#: Points a stub trend carries, and the number it claims *were* available. Unequal on purpose, so
#: :attr:`Series.downsampled` is True and directive item 23's contract is actually exercised.
STUB_HISTORY_POINTS = 5
STUB_HISTORY_AVAILABLE = 500

#: Native sampling interval the stub claims; read only by :meth:`DataProvider.check_resample`.
STUB_NATIVE_SECONDS = 60.0

#: Steps a stub what-if slider divides its documented range into.
STUB_SLIDER_STEPS = 10

#: Headline the stub's optimization / what-if channel carries. It names itself, so no test can
#: mistake it for a Model C run.
STUB_OPTIMIZATION_MESSAGE = "Stub recommendation - no optimizer was run"


@lru_cache(maxsize=1)
def stub_provider_class() -> type:
    """The stub :class:`~src.digital_twin.provider.DataProvider` class, built on first use.

    Defined inside a cached function rather than at module scope for the same reason every other
    heavy import in this file is deferred into its fixture: importing
    :mod:`src.digital_twin.provider` pulls the whole ML stack (measured 1.4 s) and ``conftest.py``
    is imported by *every* pytest invocation in this repository, including the ones that never touch
    Task #6. Cached, so identity and ``isinstance`` checks are stable across tests.
    """
    from collections import Counter
    from datetime import datetime
    from typing import Sequence

    import pandas as pd

    from src import labels, schema
    from src.digital_twin import layout
    from src.digital_twin.insights import AnomalyState, OptimizationView, PredictionSet, WhatIfView
    from src.digital_twin.payloads import (
        LIVE,
        EquipmentStatus,
        KpiGroup,
        ProviderCapabilities,
        RegimeState,
        Series,
        StateSnapshot,
        group,
    )
    from src.digital_twin.provenance import Provenance, Status, Value
    from src.digital_twin.provider import CapabilityError, DataProvider

    #: Every tag any view can display, in layout order, deduplicated across the two datasets.
    served_tags: tuple[str, ...] = tuple(
        dict.fromkeys(layout.panel_tags("kiln") + layout.panel_tags("mill"))
    )

    #: The trend x-axis, built once: a stub must not produce a different frame on a second call.
    history_stamps: tuple[str, ...] = tuple(
        str(stamp)
        for stamp in pd.date_range(STUB_TIMESTAMP, periods=STUB_HISTORY_POINTS, freq="1min")
    )

    def stub_value(
        tag: str,
        *,
        provenance: Provenance,
        source: str,
        uncertainty: float | None = None,
        horizon_min: int | None = None,
    ) -> Value:
        """One fixed :class:`Value`: the *midpoint* of that tag's own documented range.

        The midpoint is the one synthetic number that is honest about its own status - it sits
        inside any warn band a configuration could declare, so the stub can report
        :attr:`Status.OK` without importing an alarm fraction, and
        :meth:`Value.fraction_of_range` comes out at exactly 0.5, which is the input the AC-21
        animation scaling reads. Unit, description and range come from :mod:`src.schema`; this
        helper writes no engineering number of its own.
        """
        spec = schema.get_tag(tag) if schema.has_tag(tag) else None
        midpoint = spec.midpoint if spec is not None else None
        return Value(
            tag=tag,
            value=STUB_UNRANGED_VALUE if midpoint is None else midpoint,
            unit=spec.unit if spec is not None else "",
            provenance=provenance,
            source=source,
            description=spec.description if spec is not None else "",
            range_min=spec.range_min if spec is not None else None,
            range_max=spec.range_max if spec is not None else None,
            status=Status.NO_LIMIT if midpoint is None else Status.OK,
            uncertainty=uncertainty,
            horizon_min=horizon_min,
        )

    def stub_total(total: Any, source: str) -> Value:
        """One directive item 12 daily total. Unit and wording are the layout spec's own.

        Carries :data:`Provenance.OBSERVED`, as the real provider's totals do: a display
        aggregation of observed values is not a fifth data source.
        """
        return Value(
            tag=total.tag,
            value=STUB_UNRANGED_VALUE,
            unit=total.unit,
            provenance=Provenance.OBSERVED,
            source=source,
            description=total.description,
            status=Status.NO_LIMIT,
        )

    class StubDataProvider(DataProvider):
        """A fixed-value provider for the Tier-1 tests (plan Section 7 phase 6B, Section 9).

        It implements all fifteen abstract methods of the contract and nothing else: the optional
        clock surface is left at the ABC's own refusing implementations, because
        :mod:`src.digital_twin.provider` states that surface *is* optional and a stub that faked a
        clock would be pinning something the contract does not require.

        Every capability is a constructor argument, so one class covers both the fully-capable
        source and the degraded one a ``history=False`` / ``predictions=False`` provider stands for,
        with no second stub. ``synthetic`` is an argument for the same reason: T1-06 needs a
        provider that honestly reports ``synthetic=False``.

        :attr:`calls` counts every contract call this instance served, so a later phase can assert
        that one rendered frame cost one ``get_current_state`` rather than ten.
        """

        name = STUB_PROVIDER_NAME

        #: The capability flags, in :class:`ProviderCapabilities` field order.
        FLAGS: tuple[str, ...] = (
            "synthetic",
            "truth",
            "history",
            "live",
            "predictions",
            "anomaly",
            "optimization",
            "what_if",
        )

        def __init__(
            self,
            *,
            synthetic: bool = True,
            truth: bool = True,
            history: bool = True,
            live: bool = True,
            predictions: bool = True,
            anomaly: bool = True,
            optimization: bool = True,
            what_if: bool = True,
            mode: str = LIVE,
        ) -> None:
            self.calls: Counter = Counter()
            self.flags: dict[str, bool] = {
                "synthetic": bool(synthetic),
                "truth": bool(truth),
                "history": bool(history),
                "live": bool(live),
                "predictions": bool(predictions),
                "anomaly": bool(anomaly),
                "optimization": bool(optimization),
                "what_if": bool(what_if),
            }
            self.mode = str(mode)

        # -- bookkeeping ---------------------------------------------------------------------
        def _served(self, method: str) -> str:
            """Record one contract call and return the ``source`` string its Values will carry."""
            self.calls[method] += 1
            return f"{self.name}.{method}"

        def _require_flag(self, flag: str, method: str) -> str:
            """Record the call, then refuse it the way the ABC says an absent surface must."""
            source = self._served(method)
            if not self.flags[flag]:
                raise CapabilityError(f"{self.name} was built with {flag}=False")
            return source

        # -- what this provider can answer ---------------------------------------------------
        def capabilities(self) -> ProviderCapabilities:
            self._served("capabilities")
            return ProviderCapabilities(
                name=self.name,
                **self.flags,
                missing=tuple(
                    flag for flag in self.FLAGS if flag != "synthetic" and not self.flags[flag]
                ),
            )

        # -- PRD 26.1: the two mandated methods ----------------------------------------------
        def get_timeseries(
            self,
            tags: Sequence[str],
            start: datetime,
            end: datetime,
            resample: str | None = None,
        ) -> pd.DataFrame:
            self._served("get_timeseries")
            self.check_resample(resample, native_seconds=STUB_NATIVE_SECONDS)
            wanted = [str(tag) for tag in tags if schema.has_tag(str(tag))]
            index = pd.date_range(start, periods=STUB_HISTORY_POINTS, freq="1min")
            return pd.DataFrame(
                {tag: [schema.get_tag(tag).midpoint] * len(index) for tag in wanted},
                index=index,
            )

        def get_tag_metadata(self) -> pd.DataFrame:
            self._served("get_tag_metadata")
            return pd.DataFrame(
                [
                    {
                        "tag": spec.name,
                        "dataset": spec.dataset,
                        "unit": spec.unit,
                        "description": spec.description,
                        "range_min": spec.range_min,
                        "range_max": spec.range_max,
                        "sampling_interval": f"{STUB_NATIVE_SECONDS:g} s",
                        "provider": self.name,
                    }
                    for spec in schema.ALL_TAGS
                ]
            )

        # -- directive item 1: the ten data kinds --------------------------------------------
        def get_current_state(self, dataset: str | None = None) -> StateSnapshot:
            source = self._served("get_current_state")
            return StateSnapshot(
                timestamp=STUB_TIMESTAMP,
                mode=self.mode,
                provenance=Provenance.OBSERVED,
                source=source,
                values={
                    tag: stub_value(tag, provenance=Provenance.OBSERVED, source=source)
                    for tag in served_tags
                },
            )

        def get_truth_state(self, dataset: str | None = None) -> StateSnapshot:
            source = self._require_flag("truth", "get_truth_state")
            return StateSnapshot(
                timestamp=STUB_TIMESTAMP,
                mode=self.mode,
                provenance=Provenance.TRUTH,
                source=source,
                values={
                    tag: stub_value(tag, provenance=Provenance.TRUTH, source=source)
                    for tag in served_tags
                },
            )

        def get_sensor_values(self, tags: Sequence[str]) -> tuple[Value, ...]:
            source = self._served("get_sensor_values")
            return tuple(
                stub_value(str(tag), provenance=Provenance.OBSERVED, source=source)
                for tag in tags
                if str(tag) in served_tags
            )

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
            source = self._require_flag("history", "get_history")
            if truth and not self.flags["truth"]:
                raise CapabilityError(f"{self.name} was built with truth=False")
            budget = STUB_HISTORY_POINTS if max_points is None else max(1, int(max_points))
            stamps = history_stamps[:budget]
            provenance = Provenance.TRUTH if truth else Provenance.OBSERVED
            out: list[Series] = []
            for tag in tags:
                name = str(tag)
                if name not in served_tags:
                    continue
                point = stub_value(name, provenance=provenance, source=source)
                out.append(
                    Series(
                        tag=name,
                        unit=point.unit,
                        timestamps=stamps,
                        values=(point.value,) * len(stamps),
                        provenance=provenance,
                        source=source,
                        points_available=STUB_HISTORY_AVAILABLE,
                        method="stub",
                        range_min=point.range_min,
                        range_max=point.range_max,
                    )
                )
            return tuple(out)

        def get_equipment_status(self) -> tuple[EquipmentStatus, ...]:
            source = self._served("get_equipment_status")
            return tuple(
                EquipmentStatus(
                    name=spec.name,
                    unit=spec.title,
                    kind=spec.kind,
                    state=labels.EQUIPMENT_RUNNING,
                    health=STUB_HEALTH,
                    driver=stub_value(spec.driver, provenance=Provenance.OBSERVED, source=source),
                    detail=", ".join(spec.detail),
                    constraints=(),
                )
                for spec in layout.EQUIPMENT
            )

        def get_kpis(self) -> tuple[KpiGroup, ...]:
            source = self._served("get_kpis")

            def cards(tags: Sequence[str]) -> tuple[Value, ...]:
                return tuple(
                    stub_value(tag, provenance=Provenance.OBSERVED, source=source) for tag in tags
                )

            totals = tuple(stub_total(total, source) for total in layout.DAILY_TOTALS)
            return (
                group(layout.KILN_KPI_TITLE, cards(layout.KILN_KPI_TAGS)),
                group(layout.MILL_KPI_TITLE, cards(layout.MILL_KPI_TAGS)),
                group(
                    layout.PLANT_KPI_TITLE,
                    cards(layout.PLANT_KPI_TAGS) + totals,
                    note=labels.SPECIFIC_VS_TOTAL_NOTE,
                ),
            )

        def get_operating_regime(self) -> RegimeState:
            source = self._served("get_operating_regime")
            return RegimeState(
                label=STUB_REGIME_LABEL,
                regime_id=0,
                injected_fault=None,
                provenance=Provenance.CONFIGURATION,
                source=source,
                sensor_layer_only=False,
            )

        def get_anomaly_state(self, dataset: str = "kiln") -> AnomalyState:
            self._require_flag("anomaly", "get_anomaly_state")
            return AnomalyState(
                available=True,
                dataset=dataset,
                timestamp=STUB_TIMESTAMP,
                status=labels.STATUS_LEVEL_VALUES[0],
                is_anomaly=False,
                score=STUB_ANOMALY_SCORE,
                provenance=Provenance.PREDICTION,
            )

        def get_predictions(self, dataset: str = "kiln") -> PredictionSet:
            source = self._require_flag("predictions", "get_predictions")
            targets = STUB_PREDICTION_TARGETS.get(dataset, STUB_PREDICTION_TARGETS["kiln"])
            return PredictionSet(
                available=True,
                dataset=dataset,
                timestamp=STUB_TIMESTAMP,
                current=tuple(
                    stub_value(target, provenance=Provenance.OBSERVED, source=source)
                    for target in targets
                ),
                by_horizon={
                    minutes: tuple(
                        stub_value(
                            target,
                            provenance=Provenance.PREDICTION,
                            source=f"{source}/{target}/t+{minutes}min",
                            uncertainty=STUB_UNCERTAINTY,
                            horizon_min=minutes,
                        )
                        for target in targets
                    )
                    for minutes in STUB_HORIZONS_MIN
                },
                horizons_min=STUB_HORIZONS_MIN,
                model_version=STUB_PROVIDER_NAME,
            )

        def get_optimization(self, *, mode: str = "NORMAL") -> OptimizationView:
            self._require_flag("optimization", "get_optimization")
            return OptimizationView(
                available=True,
                timestamp=STUB_TIMESTAMP,
                mode=mode,
                refused=False,
                message=STUB_OPTIMIZATION_MESSAGE,
                payload={},
                gates=(),
                evaluated=1,
                runtime_s=None,  # a stub carries no wall clock (plan Section 10 / BUG 2)
            )

        def run_what_if(
            self,
            changes: Mapping[str, float] | None = None,
            *,
            delta_fractions: Mapping[str, float] | None = None,
            mode: str = "NORMAL",
        ) -> WhatIfView:
            self._require_flag("what_if", "run_what_if")
            return WhatIfView(
                available=True,
                timestamp=STUB_TIMESTAMP,
                mode=mode,
                verdict=labels.WHAT_IF_VERDICT_PASS,
                action=STUB_OPTIMIZATION_MESSAGE,
                panel={},
                requested=tuple(
                    {"name": name, "value": float(value)}
                    for name, value in dict(changes or {}).items()
                ),
                runtime_s=None,
            )

        def what_if_sliders(self, *, mode: str = "NORMAL") -> tuple[Mapping[str, Any], ...]:
            self._require_flag("what_if", "what_if_sliders")
            out: list[dict[str, Any]] = []
            for name in schema.manipulated_variables():
                spec = schema.get_tag(name)
                if spec.span is None:
                    continue
                out.append(
                    {
                        "name": name,
                        "unit": spec.unit,
                        "current": spec.midpoint,
                        "min": float(spec.range_min),
                        "max": float(spec.range_max),
                        "step": float(spec.span) / STUB_SLIDER_STEPS,
                        "mode": mode,
                    }
                )
            return tuple(out)

    return StubDataProvider


@pytest.fixture
def stub_provider() -> type:
    """The stub :class:`~src.digital_twin.provider.DataProvider` *class*, used as a factory.

    Returns the class rather than an instance, and is function-scoped rather than session-scoped,
    because the stub counts the contract calls it served in ``provider.calls``: a shared instance
    would leak those counts between tests and the per-frame call-count assertions the later phases
    need would stop meaning anything. Call it for a fresh provider with an empty counter; keyword
    arguments set the capability flags - ``stub_provider(predictions=False)``,
    ``stub_provider(synthetic=False)``.
    """
    return stub_provider_class()
