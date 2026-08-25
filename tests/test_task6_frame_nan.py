"""Task #6 BUG 1: a sensor dropout in the trailing window must not kill the frame.

The defect, reproduced against the real stack before this module was written: PRD 11.5 gives every
instrument a ``dropout_probability`` (``configs/scenarios.yaml``, 0.2 % per tag per sample), so the
measured historian carries NaN cells - a historian gap, exactly what PRD 12.4 says a gap is.
:func:`src.optimization.prediction.feature_row` reads the lag block *positionally* out of that
frame, applying none of the bounded causal forward-fill that
:meth:`src.features.lag_features.FeatureBuilder.build` applies during training, so one dropped cell
anywhere in the read positions produces a feature row containing NaN.
``GradientBoostingRegressor.predict`` - consulted on every call as Model A's *alternative* family
(``src/models/model_a.py`` ``predictions()``) even when RandomForest is the selected one - raises
``ValueError: Input X contains NaN``. Measured at 26/234 cursor positions (11.1 %) at the bundle,
and 12/150 (8.0 %) escaping ``DashboardState.intelligence()`` before the fix.

Model A raising is *correct*: it needs a complete feature row and says so rather than guessing. The
bug is Task #6 handing it an incomplete one and then letting the refusal escape, which is why both
guards live in this layer and ``src/models/model_a.py`` is untouched (directive Section 4
constraint 3).

What the guards may do is narrow: state the absence. A dropped sample must never be forward-filled,
zero-filled or interpolated into a number the panel then shows as if an instrument had reported it
(item 5, NFR-6) - so the assertions below check both that the frame survives *and* that the
surviving payload carries no fabricated value.

Tier 1 throughout except :func:`test_a_sensor_dropout_makes_a_real_feature_row_unusable`, which is
the one bounded test that touches the real feature path: it is what pins the *cause*, and a stub
cannot express "sklearn refuses this row". It builds no model and runs no simulation - it drops one
cell into a hand-built frame - so it costs milliseconds.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from src import labels
from src.digital_twin.insights import AnomalyState, PredictionSet
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import DashboardState
from src.visualization.clock import Clock

#: The dataset every test below asks about. One is enough: the guard is per-call, not per-dataset.
DATASET = "kiln"

#: The message a refusing provider raises with. Distinctive, so an assertion that the *model's own
#: words* survived into the payload cannot pass on some other string.
REFUSAL = "Input X contains NaN."


@pytest.fixture(scope="module")
def dashboard_settings() -> DashboardSettings:
    """The real ``configs/dashboard.yaml`` presentation constants (NFR-6: none written here)."""
    return DashboardSettings.from_config()


@pytest.fixture
def make_state(stub_provider, dashboard_settings):
    """Wire a provider into :class:`DashboardState` exactly as ``app.py`` would (item 21).

    Mirrors the helper in ``tests/test_task6_provider_contract.py`` rather than importing it, so
    this module runs alone while other phases edit that file.
    """

    def build(provider: Any = None, **flags: Any):
        provider = stub_provider(**flags) if provider is None else provider
        state = DashboardState(provider, Clock(provider, dashboard_settings), dashboard_settings)
        provider.calls.clear()
        return state, provider

    return build


@pytest.fixture
def refusing_provider(stub_provider):
    """A stub whose Model A / Model B channels raise ``ValueError`` the way the real ones do.

    ``ValueError`` and not :class:`~src.digital_twin.provider.CapabilityError`: the capability is
    present - Model A is trained and wired - it is *this timestamp's input* that is incomplete. The
    two are different states and the existing ``except CapabilityError`` could not tell them apart.
    """

    def build(*, predictions: bool = True, anomaly: bool = True, **flags: Any):
        provider = stub_provider(**flags)

        if predictions:
            def refuse_predictions(dataset: str = DATASET) -> PredictionSet:
                provider.calls["get_predictions"] += 1
                raise ValueError(REFUSAL)

            provider.get_predictions = refuse_predictions  # type: ignore[method-assign]

        if anomaly:
            def refuse_anomaly(dataset: str = DATASET) -> AnomalyState:
                provider.calls["get_anomaly_state"] += 1
                raise ValueError(REFUSAL)

            provider.get_anomaly_state = refuse_anomaly  # type: ignore[method-assign]

        return provider

    return build


def _numbers(payload: Any) -> list[float]:
    """Every finite number anywhere in a ``describe()`` payload, however deeply nested.

    An honest-absence assertion has to be able to say "and no number came back", and a shallow
    check would miss one buried in ``by_horizon`` or ``affected_variables``.
    """
    out: list[float] = []
    if isinstance(payload, bool):
        return out
    if isinstance(payload, (int, float)):
        return [float(payload)] if np.isfinite(float(payload)) else out
    if isinstance(payload, dict):
        for value in payload.values():
            out.extend(_numbers(value))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            out.extend(_numbers(value))
    return out


# =============================================================================
# The cause: a dropped sample makes a real feature row unusable
# =============================================================================
def test_a_sensor_dropout_makes_a_real_feature_row_unusable() -> None:
    """One NaN cell in the read positions -> a NaN feature row -> sklearn refuses it.

    This is the whole defect in one test, with no model artefact and no simulation: it builds the
    feature row through the real :func:`src.optimization.prediction.feature_row`, so if that path
    ever gained a fill this test would fail and tell us the *training* contract changed.
    """
    from sklearn.ensemble import GradientBoostingRegressor

    from src.features.lag_features import FeatureBuilder
    from src.optimization.prediction import feature_row

    builder = FeatureBuilder(DATASET)
    spec = builder.spec(min(builder.horizons_min))
    rows = spec.max_lag_steps + 4
    index = pd.date_range("2026-01-01", periods=rows, freq="1min")
    frame = pd.DataFrame(
        {column: np.linspace(1.0, 2.0, rows) for column in spec.base_columns}, index=index
    )
    frame[labels_regime_column()] = "NORMAL_OPERATION"

    intact = feature_row(spec, history=frame)
    assert not bool(intact.isna().to_numpy().any()), "the control row must be complete"

    # One dropped sample, at a position the lag block reads - a PRD 11.5 dropout, nothing exotic.
    holed = frame.copy()
    holed.iloc[-1 - spec.lag_steps(spec.lags_min[0]), holed.columns.get_loc(spec.base_columns[0])] = np.nan
    row = feature_row(spec, history=holed)
    assert bool(row.isna().to_numpy().any()), "a dropped sample must reach the feature row"

    # And the family Model A always consults as its alternative refuses such a row.
    training = pd.DataFrame(np.zeros((6, row.shape[1])), columns=list(row.columns))
    estimator = GradientBoostingRegressor(n_estimators=2, random_state=0).fit(
        training, np.arange(6.0)
    )
    with pytest.raises(ValueError, match="NaN"):
        estimator.predict(row)


def labels_regime_column() -> str:
    """``operating_regime`` - the one categorical column ``feature_row`` may read."""
    from src.optimization.prediction import REGIME_LABEL_COLUMN

    return REGIME_LABEL_COLUMN


# =============================================================================
# The join is not the cause (the recovery plan's "double outer-join" is a misreading)
# =============================================================================
def test_the_model_history_join_manufactures_no_gap_row() -> None:
    """Both datasets share one clock, so the outer join's union of indexes is that clock.

    Pinned because the join has been blamed for the NaN. If a future change ever gave the two
    frames different indexes, the join *would* start manufacturing gaps and this test would say so
    before a model saw them.
    """
    from src.digital_twin.synthetic import SyntheticDataProvider

    index = pd.date_range("2026-01-01", periods=8, freq="1min")
    kiln = pd.DataFrame({"a": np.arange(8.0), "shared": np.arange(8.0)}, index=index)
    mill = pd.DataFrame({"b": np.arange(8.0), "shared": np.arange(8.0)}, index=index)
    frames = {"kiln": kiln, "mill": mill}

    provider = object.__new__(SyntheticDataProvider)
    provider._model_frame = frames.__getitem__  # type: ignore[method-assign]
    joined = SyntheticDataProvider._model_history(provider)

    assert joined.index.equals(index), "the join must not extend the clock"
    assert list(joined.columns) == ["a", "shared", "b"], "shared columns are joined once"
    assert int(joined.isna().to_numpy().sum()) == 0, "the join introduced NaN where none existed"


def test_model_history_carries_a_gap_through_without_inventing_a_value() -> None:
    """A dropout present in a source frame stays exactly one gap - not filled, not multiplied."""
    from src.digital_twin.synthetic import SyntheticDataProvider

    index = pd.date_range("2026-01-01", periods=8, freq="1min")
    kiln = pd.DataFrame({"a": np.arange(8.0)}, index=index)
    kiln.iloc[3, 0] = np.nan  # one PRD 11.5 dropout
    mill = pd.DataFrame({"b": np.arange(8.0)}, index=index)
    frames = {"kiln": kiln, "mill": mill}

    provider = object.__new__(SyntheticDataProvider)
    provider._model_frame = frames.__getitem__  # type: ignore[method-assign]
    joined = SyntheticDataProvider._model_history(provider)

    assert int(joined.isna().to_numpy().sum()) == 1, "the gap must neither grow nor be filled"
    assert bool(joined["a"].isna().iloc[3]), "and it must stay on the row it happened on"


# =============================================================================
# The guard: a refusal becomes a display state, not a dead frame
# =============================================================================
def test_view_h_survives_a_model_a_refusal(make_state, refusing_provider) -> None:
    """``state.py:771`` used to catch only CapabilityError, so ValueError killed the frame."""
    state, _ = make_state(refusing_provider(anomaly=False))

    view = state.intelligence(dataset=DATASET)  # must not raise

    assert view.predictions.available is False
    assert view.predictions.label == labels.MODEL_UNAVAILABLE_LABEL
    assert REFUSAL in view.predictions.unavailable_reason, "the model's own words must survive"


def test_view_h_survives_a_model_b_refusal(make_state, refusing_provider) -> None:
    """The identical unguarded pattern at ``state.py:777`` for the anomaly channel."""
    state, _ = make_state(refusing_provider(predictions=False))

    view = state.intelligence(dataset=DATASET)  # must not raise

    assert view.anomaly.available is False
    assert view.anomaly.status == labels.MODEL_UNAVAILABLE_LABEL
    assert REFUSAL in view.anomaly.unavailable_reason


def test_view_h_survives_both_models_refusing_at_once(make_state, refusing_provider) -> None:
    """A dropout hits the trailing window both models read, so both can refuse on one frame."""
    state, _ = make_state(refusing_provider())

    view = state.intelligence(dataset=DATASET)

    assert view.predictions.available is False and view.anomaly.available is False
    assert view.rows == (), "no forecast row may be rendered from a refused prediction"
    # ``horizon_labels`` always opens with the observed "Current" column; what must be absent is
    # every ``t+`` forecast column, since there is no forecast behind one.
    assert view.columns == ("Current",), "no horizon column may be offered for a refused forecast"
    assert view.header.title, "the screen itself still renders"


def test_a_refusal_is_still_distinguished_from_an_absent_capability(
    make_state, refusing_provider
) -> None:
    """Two different states must not collapse: 'not trained' vs 'this timestamp is incomplete'.

    Both are unavailable, but only the refusal carries the model's reason - so a reader can tell a
    session with no model layer from a session whose sensor dropped a sample.
    """
    absent, _ = make_state(predictions=False, anomaly=False)
    refused, _ = make_state(refusing_provider())

    absent_reason = absent.intelligence(dataset=DATASET).predictions.unavailable_reason
    refused_reason = refused.intelligence(dataset=DATASET).predictions.unavailable_reason

    assert absent_reason == labels.MODEL_UNAVAILABLE_STATEMENT
    assert REFUSAL in refused_reason and refused_reason != absent_reason


# =============================================================================
# Honest absence: nothing is invented to fill the hole
# =============================================================================
def test_a_refused_prediction_payload_contains_no_fabricated_number(
    make_state, refusing_provider
) -> None:
    """Dropping an incomplete row is allowed; substituting a value for it is not (item 5, NFR-6)."""
    state, _ = make_state(refusing_provider())
    view = state.intelligence(dataset=DATASET)

    payload = view.predictions.describe()
    assert payload["available"] is False
    assert payload["current"] == [] and payload["by_horizon"] == {}
    assert _numbers(payload) == [], f"a refused forecast produced numbers: {_numbers(payload)}"


def test_a_refused_anomaly_payload_reports_no_score(make_state, refusing_provider) -> None:
    """An unscored row has *no* score - not 0.0, which reads on screen as 'nothing wrong'."""
    state, _ = make_state(refusing_provider())
    payload = state.intelligence(dataset=DATASET).anomaly.describe()

    assert payload["available"] is False
    assert payload["anomaly_score"] is None, "0.0 would be a fabricated 'all clear'"
    assert payload["is_anomaly"] is False and payload["affected_variables"] == []
    assert payload["status"] == labels.MODEL_UNAVAILABLE_LABEL


def test_the_provider_states_the_absence_rather_than_filling_the_gap() -> None:
    """``SyntheticDataProvider.get_predictions`` turns Model A's refusal into the payload itself.

    The provider-side half of the guard, tested without a session: a bundle that raises the way a
    real one does on a NaN row must come back as ``unavailable`` carrying the reason, and the
    trailing window it was handed must be returned *unmodified* - no fill was applied on the way in.
    """
    from src.digital_twin.synthetic import SyntheticDataProvider

    index = pd.date_range("2026-01-01", periods=8, freq="1min")
    history = pd.DataFrame({"a": np.arange(8.0)}, index=index)
    history.iloc[5, 0] = np.nan
    seen: list[pd.DataFrame] = []

    class RefusingBundle:
        available = True

        def predict(self, *, history: pd.DataFrame, **_: Any) -> tuple[Any, ...]:
            seen.append(history)
            raise ValueError(REFUSAL)

    provider = object.__new__(SyntheticDataProvider)
    provider._started = lambda: None  # type: ignore[method-assign]
    provider._dataset = lambda name: (str(name),)  # type: ignore[method-assign]
    provider.timestamp = lambda: pd.Timestamp("2026-01-01T00:07:00")  # type: ignore[method-assign]
    provider._predictions = {DATASET: RefusingBundle()}
    provider._model_frame = lambda name: history  # type: ignore[method-assign]
    # Stubbed so the refusal is the *only* thing that can end this call: without it an unguarded
    # `get_predictions` would die reading the observed row instead, and this test would pass its
    # fails-before check for the wrong reason.
    provider._row = lambda name: {}  # type: ignore[method-assign]

    result = SyntheticDataProvider.get_predictions(provider, DATASET)

    assert result.available is False
    assert REFUSAL in result.unavailable_reason
    assert _numbers(result.describe()) == []
    assert seen and bool(seen[0]["a"].isna().iloc[5]), "the gap must reach the model unfilled"
    assert int(seen[0].isna().to_numpy().sum()) == 1, "and nothing may be filled in on the way"


def test_a_working_provider_is_untouched_by_the_guard(make_state) -> None:
    """The guard must be invisible when nothing raises - a forecast still arrives intact."""
    state, _ = make_state()
    view = state.intelligence(dataset=DATASET)

    assert view.predictions.available is True and view.anomaly.available is True
    assert view.rows and view.columns
    assert _numbers(view.predictions.describe()), "a working channel must still carry numbers"


def test_the_guard_does_not_swallow_a_programming_error(make_state, stub_provider) -> None:
    """Only ``ValueError`` is a model refusal. A ``TypeError`` is a bug and must still surface."""
    provider = stub_provider()

    def broken(dataset: str = DATASET) -> PredictionSet:
        raise TypeError("this is a wiring bug, not a refusal")

    provider.get_predictions = broken  # type: ignore[method-assign]
    state, _ = make_state(provider)

    with pytest.raises(TypeError):
        state.intelligence(dataset=DATASET)
