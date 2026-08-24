"""Sensor model: the instrument layer between the twin and the historian.

PRD v1.1.1 11.5 (noise, measurement lag, quantization, dropout, bias drift), 11.4 regime 14
(the drift regime moves the *instrument*, not the process), FR-13 (frozen signals must be
producible so the data-quality report can detect them) and NFR-4 (per-tag RNG substreams).

The composition order of the imperfections is an ASSUMPTION of this implementation - PRD 11.5
lists them but does not order them - so it is pinned here rather than left to drift:

    measurement lag -> drift bias -> Gaussian noise -> quantization -> stuck -> dropout
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import schema
from src.config import SCENARIOS, Config, ConfigError, load_config
from src.simulation.delays import DelayedResponse
from src.simulation.sensors import SensorModel, first_order_lag
from src.simulation.simulation_config import SimulationConfig

ROWS = 4320  # three days at 1 min: long enough for the 0.2 % dropout rate to be measurable


@pytest.fixture(scope="module")
def simulation() -> SimulationConfig:
    return SimulationConfig.from_config(duration_minutes=float(ROWS), warmup_minutes=0.0)


@pytest.fixture(scope="module")
def model(simulation) -> SensorModel:
    return SensorModel(simulation)


def _truth(simulation: SimulationConfig, dataset: str) -> pd.DataFrame:
    """A perfectly steady true-state frame: every tag parked on its documented midpoint.

    A constant process makes the instrument the only source of movement, so each imperfection
    can be measured on its own instead of being inferred through the process dynamics.
    """
    index = simulation.timestamps
    columns = {
        tag: np.full(len(index), float(schema.get_tag(tag, dataset).midpoint))
        for tag in schema.numeric_columns(dataset)
    }
    return pd.DataFrame(columns, index=index)


def _mutated_scenarios(mutate) -> Config:
    data = load_config(SCENARIOS).to_dict()
    mutate(data)
    return Config(data, source="<mutated scenarios>")


# =============================================================================
# Which columns get an instrument
# =============================================================================
def test_every_numeric_column_has_an_instrument(model):
    for dataset in ("kiln", "mill"):
        assert set(model.sensors[dataset]) == set(schema.numeric_columns(dataset))


def test_columns_without_an_instrument_pass_through_untouched(model, simulation):
    """Labels and the PRD 9.3 debug residuals are ground truth, not transmitter readings."""
    frame = _truth(simulation, "kiln")
    frame["operating_regime"] = "Normal - medium production"
    frame["energy_balance_residual_pct"] = np.linspace(0.0, 0.1, len(frame))
    measured = model.apply(frame, "kiln").frame
    assert measured["operating_regime"].equals(frame["operating_regime"])
    assert measured["energy_balance_residual_pct"].equals(frame["energy_balance_residual_pct"])


def test_apply_does_not_mutate_the_true_state(model, simulation):
    frame = _truth(simulation, "mill")
    before = frame.copy()
    model.apply(frame, "mill")
    pd.testing.assert_frame_equal(frame, before)


def test_an_unknown_dataset_is_rejected(model, simulation):
    with pytest.raises(ConfigError):
        model.apply(_truth(simulation, "kiln"), "clinker_cooler")  # type: ignore[arg-type]


# =============================================================================
# Noise (PRD 11.5: 1-2 % of nominal, gas analysers noisier)
# =============================================================================
def test_default_noise_is_a_percentage_of_the_documented_range(model, simulation):
    """The band lives in src/schema.py; scenarios.yaml holds only the percentage."""
    pct = float(model._default["noise_pct_of_range"])
    tag = "clinker_production_tph"  # no override, so the default sizing applies
    sensor = model.sensors["kiln"][tag]
    expected = pct / 100.0 * float(schema.get_tag(tag, "kiln").span)
    assert sensor.noise_absolute == pytest.approx(expected)
    assert 1.0 <= pct <= 2.0  # PRD 11.5 band


def test_an_override_replaces_the_default_noise_rather_than_adding_to_it(model):
    """An override exists to say "this is not a generic 1 %-of-range transmitter"."""
    sensor = model.sensors["kiln"]["oxygen_percent"]
    assert sensor.noise_absolute == pytest.approx(0.06)
    assert sensor.noise_pct_of_value == pytest.approx(0.0)


def test_a_gas_analyser_combines_a_floor_and_a_proportional_term_in_quadrature(model):
    """PRD 11.5's "noisier at low concentration" needs both terms to survive."""
    sensor = model.sensors["kiln"]["CO_ppm"]
    assert sensor.noise_absolute == pytest.approx(3.0)
    assert sensor.noise_pct_of_value == pytest.approx(8.0)
    values = np.array([0.0, 100.0])
    assert sensor.sigma(values) == pytest.approx([3.0, np.hypot(3.0, 8.0)])


def test_measured_noise_matches_the_configured_sigma(model, simulation):
    """A steady process plus a lagged transmitter: the residual std must be sigma * lag gain."""
    frame = _truth(simulation, "kiln")
    measured = model.apply(frame, "kiln").frame
    for tag in ("clinker_production_tph", "oxygen_percent", "burning_zone_temperature"):
        sensor = model.sensors["kiln"][tag]
        residual = (measured[tag] - frame[tag]).dropna().to_numpy()
        # The lag is applied *before* the noise, so the noise is not smoothed by it.
        assert residual.std() == pytest.approx(float(sensor.sigma(frame[tag].to_numpy())[0]), rel=0.1)
        assert abs(residual.mean()) < 0.2 * residual.std()


# =============================================================================
# Measurement lag - the same convention as the process delays (PRD 9.4/11.5)
# =============================================================================
def test_the_measurement_lag_matches_delayed_response_sample_for_sample(model, simulation):
    """PRD 11.5 says the transmitter lag is *additional to* the process delay, and the two
    must therefore be the same kind of first-order lag - not two different discretizations."""
    lag_seconds = 45.0
    signal = np.linspace(3.0, 5.0, 200) + np.sin(np.arange(200) / 7.0)
    vectorized = first_order_lag(signal.reshape(-1, 1), np.array([model.alpha(lag_seconds)]))
    reference = DelayedResponse(0.0, lag_seconds)
    reference.settle(float(signal[0]))
    expected = [float(signal[0])] + [
        reference.step(float(value), simulation.dt_seconds) for value in signal[1:]
    ]
    assert vectorized[:, 0] == pytest.approx(expected, abs=1e-12)


def test_a_step_reaches_63_percent_of_its_way_after_one_time_constant(model, simulation):
    lag_seconds = 300.0
    steps = int(round(lag_seconds / float(simulation.dt_seconds)))
    signal = np.ones((60, 1))
    signal[0] = 0.0
    lagged = first_order_lag(signal, np.array([model.alpha(lag_seconds)]))[:, 0]
    assert lagged[0] == pytest.approx(0.0)
    assert lagged[steps] == pytest.approx(1.0 - np.exp(-1.0), abs=0.02)
    assert lagged[-1] == pytest.approx(1.0, abs=0.02)


def test_an_unlagged_column_is_returned_unchanged():
    signal = np.array([[1.0], [5.0], [2.0]])
    assert first_order_lag(signal, np.array([1.0])) == pytest.approx(signal)


def test_the_lag_helper_rejects_a_malformed_call():
    with pytest.raises(ValueError):
        first_order_lag(np.zeros(5), np.array([0.5]))
    with pytest.raises(ValueError):
        first_order_lag(np.zeros((5, 2)), np.array([0.5]))
    with pytest.raises(ValueError):
        first_order_lag(np.zeros((5, 1)), np.array([1.5]))


# =============================================================================
# Bias drift - regime 14 only (PRD 11.4)
# =============================================================================
def test_the_bias_ramp_is_applied_only_where_the_drift_regime_says_so(model, simulation):
    """The true process is untouched; the instrument walks away from it by `drift_bias`."""
    frame = _truth(simulation, "kiln")
    rows = len(frame)
    progress = np.zeros(rows)
    window = slice(1000, 2000)
    progress[window] = np.linspace(1.0 / 1000.0, 1.0, 1000)
    drifted = model.apply(frame, "kiln", drift_progress=progress).frame
    flat = model.apply(frame, "kiln").frame
    for tag, bias in model._drift["tags"].items():
        if tag not in model.sensors["kiln"]:
            continue
        sensor = model.sensors["kiln"][tag]
        # Quantization is coarser than nothing, so compare against the quantum.
        tolerance = float(sensor.quantization or 0.0) + 1e-9
        difference = (drifted[tag] - flat[tag]).to_numpy()
        expected = float(bias) * progress
        assert np.nanmax(np.abs(difference - expected)) <= tolerance
        assert float(bias) != 0.0


def test_a_tag_without_a_configured_drift_never_drifts(model, simulation):
    frame = _truth(simulation, "kiln")
    progress = np.linspace(0.0, 1.0, len(frame))
    drifted = model.apply(frame, "kiln", drift_progress=progress).frame
    flat = model.apply(frame, "kiln").frame
    undrifted = [tag for tag, s in model.sensors["kiln"].items() if s.drift_bias == 0.0]
    assert undrifted
    for tag in undrifted:
        pd.testing.assert_series_equal(drifted[tag], flat[tag])


def test_the_drift_ramp_must_cover_every_row(model, simulation):
    frame = _truth(simulation, "kiln")
    with pytest.raises(ConfigError):
        model.apply(frame, "kiln", drift_progress=np.zeros(len(frame) - 1))
    partial = pd.Series(0.0, index=frame.index[:-1])
    with pytest.raises(ConfigError):
        model.apply(frame, "kiln", drift_progress=partial)


def test_a_drift_ramp_given_as_a_series_is_aligned_by_timestamp(model, simulation):
    frame = _truth(simulation, "kiln")
    ramp = np.linspace(0.0, 1.0, len(frame))
    as_series = pd.Series(ramp, index=frame.index).iloc[::-1]  # deliberately out of order
    by_series = model.apply(frame, "kiln", drift_progress=as_series).frame
    by_array = model.apply(frame, "kiln", drift_progress=ramp).frame
    pd.testing.assert_frame_equal(by_series, by_array)


# =============================================================================
# Quantization, stuck signals, dropout (PRD 11.5, FR-13)
# =============================================================================
def test_quantized_tags_only_ever_report_multiples_of_their_resolution(model, simulation):
    frame = _truth(simulation, "kiln")
    measured = model.apply(frame, "kiln").frame
    for tag, sensor in model.sensors["kiln"].items():
        if not sensor.quantization:
            continue
        values = measured[tag].dropna().to_numpy() / float(sensor.quantization)
        assert np.abs(values - np.round(values)).max() < 1e-6


def test_a_tag_without_a_configured_resolution_is_not_quantized(model, simulation):
    unquantized = [
        tag for tag, sensor in model.sensors["kiln"].items() if sensor.quantization is None
    ]
    assert unquantized  # the default is `quantization: null`
    measured = model.apply(_truth(simulation, "kiln"), "kiln").frame
    values = measured[unquantized[0]].dropna().to_numpy()
    assert len(np.unique(values)) > len(values) // 2  # a continuum, not a ladder


def test_frozen_transmitters_repeat_their_last_reported_value(model, simulation):
    """FR-13: the generator has to be able to produce the fault the report detects."""
    frame = _truth(simulation, "kiln")
    outcome = model.apply(frame, "kiln")
    assert outcome.stuck_events  # three days x 34 tags at 0.02/day/tag: a handful
    for event in outcome.stuck_events:
        held = outcome.frame[event.tag].iloc[event.start_step : event.end_step].dropna()
        assert held.to_numpy() == pytest.approx(event.held_value)
        assert event.steps >= 1


def test_freezing_happens_after_quantization(model, simulation):
    """The chain is pinned: a frozen reading is a value the DCS could actually have stored."""
    outcome = model.apply(_truth(simulation, "kiln"), "kiln")
    quantized = [
        event
        for event in outcome.stuck_events
        if model.sensors["kiln"][event.tag].quantization
    ]
    assert quantized
    for event in quantized:
        step = float(model.sensors["kiln"][event.tag].quantization)
        assert event.held_value / step == pytest.approx(round(event.held_value / step))


def test_stuck_episodes_never_overlap_on_one_tag(model, simulation):
    outcome = model.apply(_truth(simulation, "kiln"), "kiln")
    for tag in {event.tag for event in outcome.stuck_events}:
        events = sorted(
            (e for e in outcome.stuck_events if e.tag == tag), key=lambda e: e.start_step
        )
        assert all(a.end_step <= b.start_step for a, b in zip(events, events[1:]))


def test_dropouts_land_inside_the_prd_band(model, simulation):
    """PRD 11.5: 0.1-0.5 % of samples are missing, and NaN is the only way they go missing."""
    frame = _truth(simulation, "kiln")
    outcome = model.apply(frame, "kiln")
    tags = list(model.sensors["kiln"])
    fraction = outcome.missing_total / (len(frame) * len(tags))
    assert 0.001 <= fraction <= 0.005
    assert outcome.missing_counts == {
        tag: int(outcome.frame[tag].isna().sum()) for tag in tags
    }
    assert outcome.frame[tags].isna().sum().sum() == outcome.missing_total


def test_a_zero_dropout_configuration_produces_a_complete_frame(simulation):
    scenarios = _mutated_scenarios(
        lambda data: data["sensor_model"]["default"].update(dropout_probability=0.0)
    )
    model = SensorModel(simulation, scenarios=scenarios)
    outcome = model.apply(_truth(simulation, "mill"), "mill")
    assert outcome.missing_total == 0
    assert not outcome.frame.isna().to_numpy().any()


# =============================================================================
# Reproducibility (NFR-4)
# =============================================================================
def test_the_measurement_is_a_pure_function_of_config_and_seed(simulation):
    frame = _truth(simulation, "mill")
    first = SensorModel(simulation).apply(frame, "mill")
    second = SensorModel(simulation).apply(frame, "mill")
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.describe() == second.describe()


def test_a_different_seed_gives_a_different_measurement(simulation):
    frame = _truth(simulation, "mill")
    first = SensorModel(simulation).apply(frame, "mill").frame
    other = SensorModel(simulation.replace(seed=987654)).apply(frame, "mill").frame
    assert not first["mill_motor_power_kw"].equals(other["mill_motor_power_kw"])


def test_the_global_numpy_rng_is_never_used(simulation):
    frame = _truth(simulation, "mill")
    np.random.seed(11)
    first = SensorModel(simulation).apply(frame, "mill").frame
    np.random.seed(22)
    second = SensorModel(simulation).apply(frame, "mill").frame
    pd.testing.assert_frame_equal(first, second)


def test_each_tag_draws_from_its_own_substream(model, simulation):
    """NFR-4: dropping or reordering a column must not shift any other tag's numbers."""
    frame = _truth(simulation, "kiln")
    full = model.apply(frame, "kiln").frame
    subset = ["oxygen_percent", "burning_zone_temperature"]
    reordered = model.apply(frame[subset[::-1]], "kiln").frame
    for tag in subset:
        pd.testing.assert_series_equal(full[tag], reordered[tag])


def test_an_empty_frame_is_measured_without_error(model):
    empty = pd.DataFrame(
        {tag: np.array([], dtype=float) for tag in schema.numeric_columns("mill")},
        index=pd.DatetimeIndex([], name=schema.TIMESTAMP_COLUMN),
    )
    outcome = model.apply(empty, "mill")
    assert outcome.missing_total == 0
    assert outcome.stuck_events == ()


def test_describe_is_json_serializable(model):
    payload = json.loads(json.dumps(model.describe()))
    assert payload["default"]["noise_pct_of_range"] == float(
        model._default["noise_pct_of_range"]
    )
    assert payload["sensors"]["kiln"]["oxygen_percent"]["quantization"] == 0.01
    assert set(payload["drift"]["tags"]) == set(model._drift["tags"])


def test_the_outcome_record_is_json_serializable(model, simulation):
    outcome = model.apply(_truth(simulation, "kiln"), "kiln")
    payload = json.loads(json.dumps(outcome.describe()))
    assert payload["rows"] == simulation.export_steps
    assert payload["missing_total"] == outcome.missing_total
    assert len(payload["stuck_events"]) == len(outcome.stuck_events)


# =============================================================================
# Config validation: a typo must fail loudly, never silently (NFR-6)
# =============================================================================
@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        (
            "a missing default setting",
            lambda data: data["sensor_model"]["default"].pop("lag_seconds"),
        ),
        (
            "a dropout probability of 1",
            lambda data: data["sensor_model"]["default"].update(dropout_probability=1.0),
        ),
        (
            "a negative dropout probability",
            lambda data: data["sensor_model"]["default"].update(dropout_probability=-0.1),
        ),
        (
            "an override for something that is not a dataset column",
            lambda data: data["sensor_model"]["overrides"].update(kiln_temperature={}),
        ),
        (
            "a misspelled override key",
            lambda data: data["sensor_model"]["overrides"]["oxygen_percent"].update(
                noise_pct_of_ranges=1.0
            ),
        ),
        (
            "an unimplemented drift shape",
            lambda data: data["sensor_model"]["drift"].update(shape="exponential"),
        ),
        (
            "a drift entry for something that is not a dataset column",
            lambda data: data["sensor_model"]["drift"]["tags"].update(kiln_temperature=1.0),
        ),
        (
            "a negative stuck rate",
            lambda data: data["sensor_model"]["stuck"].update(rate_per_day_per_tag=-1.0),
        ),
        (
            "an inverted stuck duration band",
            lambda data: data["sensor_model"]["stuck"].update(duration_min=[180.0, 15.0]),
        ),
    ],
)
def test_a_broken_sensor_config_is_rejected(description, mutate, simulation):
    with pytest.raises(ConfigError):
        SensorModel(simulation, scenarios=_mutated_scenarios(mutate))
