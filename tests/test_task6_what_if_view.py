"""View I renderer tests (Wave View I): the What-If Simulation panel and its routing.

Deliberately bounded, like ``test_task6_energy_view.py`` and its predecessors: nothing here
builds a session, trains a model or runs the optimizer. The renderer under test is the real
:mod:`src.visualization.what_if_view`, driven by a stub view model shaped exactly like
:class:`~src.digital_twin.state.WhatIfViewModel` over a PRD 16.3 panel shaped exactly like
``WhatIfResult.panel()`` emits — and, for the state-layer and routing tests, the real
:meth:`src.digital_twin.state.DashboardState.what_if` builder over the shared ``conftest.py``
stub provider. So what is asserted below is what a browser would receive from a real run, at
stub cost.

Covers the items this wave surfaces on one screen:

* **item 13** — the sliders with the exact configured bounds and step sizes (read from the
  payload, never restated from configuration), and the three verdicts as display forms of
  states the engine already reached;
* **PRD 16.1** — the mode and the fixed Experimental-Mode banner, visually distinct;
* **PRD 16.3** — the before/after table, the predicted response with the transition summary
  and the savings line, and the per-constraint / per-envelope-check rows;
* **PRD 30 / item 20** — a trimmed request is shown as trimmed (snapped/clipped flags and the
  engine's own notes), no fabricated value, no numeric confidence, absences stated with the
  payload's own reason.

Self-contained on purpose for the renderer tests (no ``conftest.py`` fixture needed for them);
the state-layer tests use the shared ``stub_provider`` fixture, so this module runs alone with
``pytest tests/test_task6_what_if_view.py`` either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.provenance import Provenance
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import DashboardState
from src.visualization import theme, what_if_view
from src.visualization.clock import Clock


# =============================================================================
# The stub payload — shaped exactly like WhatIfResult.panel() and WhatIfView
# =============================================================================
#: One PRD 16.3 before/after row, in the shape ``MetricDelta.describe()`` emits.
_BEFORE_AFTER = (
    {"tag": "clinker_production_tph", "baseline": 119.8, "proposed": 118.1,
     "delta": -1.7, "delta_pct": -1.42},
    {"tag": "kiln_thermal_energy_kcal_per_kg_clinker", "baseline": 807.9, "proposed": 801.2,
     "delta": -6.7, "delta_pct": -0.83},
)

#: One engine slider spec, in the shape ``WhatIfEngine.slider()`` emits.
_SLIDERS = (
    {"name": "kiln_fuel_rate_tph", "unit": "t/h", "current": 6.240, "minimum": 5.616,
     "maximum": 6.864, "absolute_range": [4.975, 7.462], "step": 0.0312,
     "max_delta_fraction": 0.1, "mode": "NORMAL"},
    {"name": "kiln_feed_rate_tph", "unit": "t/h", "current": 190.2, "minimum": 171.18,
     "maximum": 209.22, "absolute_range": [157.8, 222.6], "step": 1.0,
     "max_delta_fraction": 0.1, "mode": "NORMAL"},
)

#: One requested-change row, in the shape ``VariableRequest.describe()`` emits — the snapped
#: flag on, so the trimming is rendered rather than hidden (PRD 30).
_REQUESTED = (
    {"name": "kiln_fuel_rate_tph", "unit": "t/h", "baseline": 6.240, "requested": 5.9,
     "value": 5.902, "delta": -0.338, "delta_pct": -5.42, "bounds": [5.616, 6.864],
     "step": 0.0312, "clipped": False, "snapped": True, "moved": True,
     "note": "kiln_fuel_rate_tph: requested 5.9 t/h, snapped to the 0.0312 t/h slider step "
             "-> 5.902"},
    {"name": "kiln_feed_rate_tph", "unit": "t/h", "baseline": 190.2, "requested": 190.2,
     "value": 190.0, "delta": -0.2, "delta_pct": -0.12, "bounds": [171.18, 209.22],
     "step": 1.0, "clipped": False, "snapped": True, "moved": True,
     "note": "kiln_feed_rate_tph: snapped to the 1 t/h slider step -> 190"},
)

_PANEL: dict[str, Any] = {
    "mode": "NORMAL",
    "action": "kiln_fuel_rate_tph 6.24 -> 5.902 t/h (-5.42 %)",
    "requested_change": [dict(item) for item in _REQUESTED],
    "baseline_state": {"clinker_production_tph": 119.8},
    "predicted_process_response": {
        "settled_state": {
            "clinker_production_tph": 118.1,
            "kiln_thermal_energy_kcal_per_kg_clinker": 801.2,
        },
        "by_horizon": {},
        "transition": {
            "rows": 125, "minutes": 25.0, "dt_seconds": 12.0, "hold_minutes": 5.0,
            "ramp_minutes": {"kiln_fuel_rate_tph": 10.0, "kiln_feed_rate_tph": 15.0},
        },
        "endpoint_agreement_relative": 0.004,
        "endpoint_converged": True,
    },
    "before_after": [dict(item) for item in _BEFORE_AFTER],
    "energy_impact": {
        "thermal_energy_kcal_per_day": -492944.0,
        "electrical_energy_kwh_per_day": None,
        "savings_line": "Estimated change at the settled rate: thermal -492,944 kcal/day. "
                        + labels.SIMULATED_SAVING_CAVEAT,
        "caveat": labels.SIMULATED_SAVING_CAVEAT,
    },
    "constraint_status": "PASS",
    "constraint_rows": (
        {"constraint": "burning_zone_temperature", "state": "PASS", "value": 1448.1,
         "limit": 1500.0, "detail": "inside the hard limit"},
    ),
    "envelope_status": "WITHIN_ENVELOPE",
    "ood_status": "WITHIN_ENVELOPE",
    "envelope_rows": (
        {"check": "operating_envelope", "state": "PASS", "detail": "inside every bound"},
    ),
    "recommendation_status": {"accepted": True, "simulated": True},
    "banner": None,
    "notes": [item["note"] for item in _REQUESTED],
}


@dataclass(frozen=True)
class StubHeader:
    title: str = "What-If Simulation"
    subtitle: str = "Operator-set changes evaluated by the validated what-if engine"
    timestamp: str = "2024-01-01T00:00:00Z"


@dataclass(frozen=True)
class StubWhatIfView:
    """Shaped like ``insights.WhatIfView``: the PRD 16.3 panel plus its own verdict.

    Carries only what the renderer reads — so a field the renderer started reading would fail
    these tests loudly rather than silently fall back to a stub default.
    """

    available: bool = True
    timestamp: str = StubHeader.timestamp
    mode: str = "NORMAL"
    verdict: str = labels.WHAT_IF_VERDICT_PASS
    action: str = _PANEL["action"]
    panel: dict[str, Any] = field(default_factory=lambda: dict(_PANEL))
    requested: tuple[dict[str, Any], ...] = _REQUESTED
    notes: tuple[str, ...] = tuple(item["note"] for item in _REQUESTED)
    banner: str | None = None
    runtime_s: float | None = None
    unavailable_reason: str = ""
    provenance: Provenance = Provenance.RECOMMENDATION


@dataclass(frozen=True)
class StubWhatIfModel:
    """Shaped like ``state.WhatIfViewModel``: header, mode, the engine answer, the sliders."""

    header: StubHeader = field(default_factory=StubHeader)
    mode: str = "NORMAL"
    view: StubWhatIfView = field(default_factory=StubWhatIfView)
    sliders: tuple[dict[str, Any], ...] = _SLIDERS


class StubState:
    """The duck-typed state ``app.build_document`` needs: ``view(view_id)`` and nothing else."""

    def __init__(self, models: dict[str, Any]) -> None:
        self._models = models

    def view(self, view_id: str) -> Any:
        return self._models[view_id]


@pytest.fixture(scope="module")
def settings() -> DashboardSettings:
    """The real dashboard settings - a YAML parse, milliseconds, no session."""
    return DashboardSettings.from_config()


# =============================================================================
# A — normal rendering: the sections, from the payload's own values
# =============================================================================
def test_the_sections_render_from_one_view_model(settings: DashboardSettings) -> None:
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert 'data-role="whatif-sliders"' in html
    assert 'data-role="whatif-change"' in html
    assert 'data-role="whatif-response"' in html
    assert 'data-role="whatif-constraints"' in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html


def test_the_verdict_and_mode_are_the_payloads_own(settings: DashboardSettings) -> None:
    """Item 13: the verdict is one of the three display forms the engine reached, read from
    the payload — and the mode badge is the payload's mode string, not a second guess."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert labels.WHAT_IF_VERDICT_PASS in html
    assert ">NORMAL<" in html


def test_the_action_line_is_the_payloads_own(settings: DashboardSettings) -> None:
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert theme.html(_PANEL["action"]) in html  # verbatim, HTML-escaped like all payload text


# =============================================================================
# B — item 13: the sliders, with the exact configured bounds and step sizes
# =============================================================================
def test_the_sliders_carry_their_configured_bounds_and_steps(
    settings: DashboardSettings,
) -> None:
    """Item 13: the slider cards show the engine's own bounds, step and mode change limit —
    the payload's numbers, never restated from configuration by the renderer."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    for name in ("kiln_fuel_rate_tph", "kiln_feed_rate_tph"):
        assert f'data-variable="{name}"' in html
    assert "6.240" in html  # the current value
    assert "5.616" in html and "6.864" in html  # the NORMAL mode bounds
    assert "0.0312" in html  # the exact configured step


def test_absent_sliders_are_stated_not_invented(settings: DashboardSettings) -> None:
    """A provider that answered no sliders (Model C absent) gets the absence stated — a
    slider whose bounds nothing owns would be a made-up limit (item 5)."""
    html = what_if_view.render_what_if(
        StubWhatIfModel(sliders=()), settings=settings
    )
    assert "unavailable" in html
    assert "no slider specifications" in html
    assert 'data-role="whatif-slider"' not in html  # no slider card is invented


# =============================================================================
# C — the manipulated change: requested vs simulated, trimming shown (PRD 30)
# =============================================================================
def test_the_requested_change_shows_baseline_requested_and_simulated(
    settings: DashboardSettings,
) -> None:
    """PRD 30: a request the engine snapped or clipped is shown as trimmed — baseline,
    requested and simulated side by side, never the simulated value passed off as the ask."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "Baseline" in html and "Requested" in html and "Simulated" in html
    assert "5.9" in html  # what was asked
    assert "5.902" in html  # what will actually be simulated
    assert "snapped" in html  # the engine's own flag
    for note in _PANEL["notes"]:
        assert theme.html(note) in html  # the engine's own one-line explanation, verbatim


# =============================================================================
# D — PRD 16.3: the predicted response (before/after, transition, savings)
# =============================================================================
def test_the_before_after_table_shows_the_payloads_own_numbers(
    settings: DashboardSettings,
) -> None:
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "Baseline" in html and "Scenario" in html
    assert "119.8" in html and "118.1" in html  # before and after, the engine's own


def test_the_transition_summary_is_stated_as_numbers(settings: DashboardSettings) -> None:
    """Beneath the chart, the delay the trajectory carries — window, hold, ramp — is rendered
    as text too, so the transition's timing is carried as numbers as well as a picture."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "25" in html and "5" in html  # window minutes and hold minutes
    assert "kiln_fuel_rate_tph" in html  # the ramp summary names its variable


def test_the_transition_chart_draws_each_moved_variables_command_path(
    settings: DashboardSettings,
) -> None:
    """PRD 16.2/16.3: one polyline per moved variable — the engine's own hold-then-ramp
    command, reconstructed from payload numbers only, so the move is visibly not an
    instantaneous jump. Both stub variables moved, so two lines; the hold guide, the 0%/100%
    rails and the window-end tick are all present, and each legend entry names its variable's
    own ramp minutes and commanded move (the real magnitudes the normalised picture omits)."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert 'data-role="whatif-transition"' in html
    assert html.count("<polyline") == 2  # one per moved variable, none invented
    assert 'class="dt-wi__guide"' in html  # the hold, marked where it ends
    assert ">0%</text>" in html and ">100%</text>" in html  # the baseline and commanded rails
    assert "hold ends" in html and "25.00 min" in html  # window end as the axis' last tick
    # The legend carries the timing and the magnitudes the normalised lines cannot.
    assert "ramp 10.00 min" in html and "ramp 15.00 min" in html
    assert "complete at 15.00 min" in html  # hold 5 + ramp 10 — the delay, as a number
    assert "6.240" in html and "5.902" in html  # the commanded move itself


def test_the_transition_chart_states_when_no_variable_moved(
    settings: DashboardSettings,
) -> None:
    """A request that moves nothing (the null change set the generic dispatch sends) has no
    trajectory to draw — the absence is stated, and no empty or decorative chart is."""
    panel = dict(_PANEL)
    view = StubWhatIfView(
        panel=panel, requested=(),
    )
    html = what_if_view.render_what_if(StubWhatIfModel(view=view), settings=settings)
    assert "No manipulated variable moved" in html
    assert "<svg" not in html and "<polyline" not in html


def test_a_moved_variable_without_ramp_minutes_is_stated_not_timed(
    settings: DashboardSettings,
) -> None:
    """A moved variable whose ramp time the payload does not state is named — no ramp is
    invented for it (the engine always carries one, so this is the robustness branch), and a
    transition summary with no numeric window gets the same stated absence."""
    panel = dict(_PANEL)
    response = dict(panel["predicted_process_response"])
    response["transition"] = {
        "rows": 125, "minutes": 25.0, "dt_seconds": 12.0, "hold_minutes": 5.0,
        "ramp_minutes": {},  # nothing states a ramp — no command path is drawable
    }
    panel["predicted_process_response"] = response
    html = what_if_view.render_what_if(
        StubWhatIfModel(view=StubWhatIfView(panel=panel)), settings=settings
    )
    assert "names no ramp time" in html
    assert "kiln_fuel_rate_tph" in html  # the variable is named, not silently dropped
    assert "<polyline" not in html

    response["transition"] = {"minutes": "not a number"}  # no numeric window at all
    panel["predicted_process_response"] = response
    html = what_if_view.render_what_if(
        StubWhatIfModel(view=StubWhatIfView(panel=panel)), settings=settings
    )
    assert "no numeric transition window" in html
    assert "<polyline" not in html


def test_the_transition_chart_carries_the_response_path_honesty_note(
    settings: DashboardSettings,
) -> None:
    """The plant's response path is not on the payload — the chart says so rather than
    interpolating a curve between the baseline and settled state (a fabricated delay would
    be exactly the thing PRD 16.2 forbids passing off as the trajectory)."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "not carried by this payload" in html
    assert "no response curve is drawn" in html


def test_a_rejected_request_states_there_is_no_trajectory(
    settings: DashboardSettings,
) -> None:
    """A request rejected before any solve is never simulated — so there is no trajectory,
    and the absence is stated rather than a fabricated flat line."""
    panel = dict(_PANEL)
    panel["predicted_process_response"] = {"settled_state": {}, "transition": None}
    view = StubWhatIfView(panel=panel, verdict=labels.WHAT_IF_VERDICT_REJECTED)
    html = what_if_view.render_what_if(StubWhatIfModel(view=view), settings=settings)
    assert labels.WHAT_IF_VERDICT_REJECTED in html
    assert "no transition to show" in html
    assert "rejected before any simulation ran" in html


def test_the_savings_line_carries_its_own_caveat(settings: DashboardSettings) -> None:
    """PRD 16.3's estimated savings/cost line, carrying its caveat rather than implying one."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "Estimated change at the settled rate" in html
    assert labels.SIMULATED_SAVING_CAVEAT in html


def test_an_endpoint_agreement_above_tolerance_is_shown_not_hidden(
    settings: DashboardSettings,
) -> None:
    """The engine measures the disagreement between its two numerical routes; the renderer
    carries the number and the engine's own warning when the window was too short."""
    panel = dict(_PANEL)
    response = dict(panel["predicted_process_response"])
    response["endpoint_agreement_relative"] = 0.08
    response["endpoint_converged"] = False
    panel["predicted_process_response"] = response
    html = what_if_view.render_what_if(
        StubWhatIfModel(view=StubWhatIfView(panel=panel)), settings=settings
    )
    assert "0.08" in html
    assert "too short for this move to have finished settling" in html


# =============================================================================
# E — PRD 16.3: constraints and envelope checks, per constraint and per check
# =============================================================================
def test_constraint_and_envelope_rows_render_the_payloads_own_states(
    settings: DashboardSettings,
) -> None:
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "burning_zone_temperature" in html  # the constraint's own name
    assert "operating_envelope" in html  # the check's own name
    assert "inside the hard limit" in html  # the payload's own detail, verbatim
    assert "1,448" in html and "1,500" in html  # value and limit, the validator's own


def test_absent_constraint_rows_are_stated_not_assumed_passed(
    settings: DashboardSettings,
) -> None:
    """An empty report is stated — never shown as if every constraint had passed."""
    panel = dict(_PANEL)
    panel["constraint_rows"] = ()
    panel["envelope_rows"] = ()
    html = what_if_view.render_what_if(
        StubWhatIfModel(view=StubWhatIfView(panel=panel)), settings=settings
    )
    assert "no constraint or envelope rows" in html
    assert "burning_zone_temperature" not in html  # none is invented as satisfied


# =============================================================================
# F — PRD 16.1: the Experimental-Mode banner, visually distinct
# =============================================================================
def test_the_experimental_banner_renders_when_the_payload_carries_one(
    settings: DashboardSettings,
) -> None:
    """The fixed PRD 14.3/16.1 banner, in its mandated wording, in the warn style — never
    awarded by the renderer, only carried from the payload."""
    view = StubWhatIfView(
        mode="EXPERIMENTAL", banner=labels.OUTSIDE_ENVELOPE_BANNER,
        verdict=labels.WHAT_IF_VERDICT_REJECTED,
    )
    html = what_if_view.render_what_if(
        StubWhatIfModel(mode="EXPERIMENTAL", view=view), settings=settings
    )
    assert labels.OUTSIDE_ENVELOPE_BANNER in html
    assert "dt-banner--warn" in html  # visually distinct from Normal-Mode results


# =============================================================================
# G — missing / unavailable simulation: stated, never substituted
# =============================================================================
def test_the_unavailable_panel_states_the_payloads_own_reason(
    settings: DashboardSettings,
) -> None:
    html = what_if_view.render_what_if(
        StubWhatIfModel(
            view=StubWhatIfView(
                available=False, verdict=labels.MODEL_UNAVAILABLE_LABEL, action="",
                panel={}, requested=(), notes=(), unavailable_reason="no model layer",
            ),
            sliders=(),
        ),
        settings=settings,
    )
    assert labels.MODEL_UNAVAILABLE_LABEL in html
    assert "no model layer" in html  # the payload's own reason, not a second explanation
    assert "119.8" not in html  # no before/after number is invented for an absent model
    assert 'data-role="whatif-response"' not in html


def test_an_empty_before_after_is_stated_not_filled(settings: DashboardSettings) -> None:
    panel = dict(_PANEL)
    panel["before_after"] = []
    html = what_if_view.render_what_if(
        StubWhatIfModel(view=StubWhatIfView(panel=panel)), settings=settings
    )
    assert "no before/after rows" in html
    assert "119.8" not in html


def test_an_empty_settled_state_is_stated_not_filled(settings: DashboardSettings) -> None:
    panel = dict(_PANEL)
    panel["predicted_process_response"] = {"settled_state": {}, "transition": None}
    html = what_if_view.render_what_if(
        StubWhatIfModel(view=StubWhatIfView(panel=panel)), settings=settings
    )
    assert "no settled state" in html  # the settled table's own stated absence
    # No settled row is invented: the only 118.1 on the screen is the before/after table's
    # own "after" number, which is a different element with its own heading.
    assert html.count("118.1") == 1


def test_the_engines_flat_float_settled_state_renders(settings: DashboardSettings) -> None:
    """The engine's actual payload shape: tag -> plain float (proposed_state is
    Mapping[str, float], not a {value, unit} mapping). A shape mismatch here once
    rendered the real settled state as "unavailable" while the numbers existed."""
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "no settled state" not in html  # the numbers exist, so the table renders them
    assert "801.2" in html  # the settled value, not an invented one
    assert html.count("118.1") == 2  # before/after "after" + the settled row
    # A flat entry states no unit, so the settled row's unit cell is left empty — not guessed
    # ("t/h" elsewhere on the page belongs to the action line, never to a settled row).
    assert '118.1</td><td class="dt-muted"></td>' in html


# =============================================================================
# H — no fabricated values, and the honesty rules every screen carries
# =============================================================================
def test_no_confidence_percentage_and_no_forbidden_control_label(
    settings: DashboardSettings,
) -> None:
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert "confidence" not in html.lower()
    assert labels.FORBIDDEN_CONTROL_LABEL not in html
    assert labels.SIMULATED_SAVING_CAVEAT in html  # the saving carries its caveat


def test_payload_free_text_is_escaped(settings: DashboardSettings) -> None:
    """A note or detail carrying markup is escaped — the payload cannot inject into the panel."""
    view = StubWhatIfView(
        notes=("<script>alert(1)</script>",),
        requested=({"name": "kiln_fuel_rate_tph", "unit": "t/h", "baseline": 6.24,
                    "requested": 5.9, "value": 5.902, "delta_pct": -5.42,
                    "bounds": [5.616, 6.864], "step": 0.0312, "clipped": False,
                    "snapped": True, "moved": True, "note": "<script>alert(1)</script>"},),
    )
    html = what_if_view.render_what_if(StubWhatIfModel(view=view), settings=settings)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# =============================================================================
# I — determinism
# =============================================================================
def test_two_renders_of_one_view_model_are_byte_identical(
    settings: DashboardSettings,
) -> None:
    """No wall clock, no dict ordering, no randomness: the same payload renders the same panel."""
    first = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    second = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)
    assert first == second


# =============================================================================
# J — the payload / accessor layer: the state builder over the shared stub provider
# =============================================================================
def test_the_state_builder_carries_mode_changes_and_sliders(
    stub_provider: Any, settings: DashboardSettings,
) -> None:
    """``DashboardState.what_if()`` over the shared stub provider: the mode and the requested
    change travel through to the payload, and the sliders come from the provider's own
    specs — the state layer routes, it never recomputes."""
    provider = stub_provider()
    state = DashboardState(provider, Clock(provider, settings), settings)
    model = state.what_if(changes={"kiln_fuel_rate_tph": 5.9}, mode="EXPERIMENTAL")
    assert model.mode == "EXPERIMENTAL"
    assert model.view.mode == "EXPERIMENTAL"
    assert model.view.available and model.view.verdict == labels.WHAT_IF_VERDICT_PASS
    assert model.view.requested[0]["name"] == "kiln_fuel_rate_tph"
    assert model.sliders  # the stub serves slider specs; the builder passes them through


def test_an_absent_what_if_capability_yields_the_unavailable_view(
    stub_provider: Any, settings: DashboardSettings,
) -> None:
    """A provider with ``what_if=False``: the view is the honest unavailable one — the
    capability's own refusal, never a substitute panel."""
    provider = stub_provider(what_if=False)
    state = DashboardState(provider, Clock(provider, settings), settings)
    model = state.what_if(mode="NORMAL")
    assert model.view.available is False
    assert model.view.unavailable_reason  # the payload's own reason


# =============================================================================
# K — app.py routing (the _is_whatif duck type) and the CLI reachability surface
# =============================================================================
def test_view_i_routes_to_the_renderer_in_build_document(
    settings: DashboardSettings,
) -> None:
    html, timings = app.build_document(StubState({"I": StubWhatIfModel()}), ("I",),
                                       settings=settings)
    assert "I — What-If Simulation" in html
    assert 'data-role="whatif-sliders"' in html
    assert "no renderer for this screen yet" not in html  # not the payload fallback
    assert list(timings) == ["I"]


def test_the_whatif_duck_type_does_not_swallow_the_other_screens(
    settings: DashboardSettings,
) -> None:
    """_is_whatif keys on ``sliders`` AND ``view``; A carries stages/plant, G carries
    specific/total, H carries predictions/anomaly, J carries view+quality_descriptions but no
    sliders, B/E carry line/snapshot — none matches, so their routing is untouched."""

    @dataclass(frozen=True)
    class StubOverviewLike:
        header: StubHeader = field(default_factory=StubHeader)
        stages: object = None
        plant: object = None

    @dataclass(frozen=True)
    class StubEnergyLike:
        header: StubHeader = field(default_factory=StubHeader)
        specific: object = None
        total: object = None

    @dataclass(frozen=True)
    class StubIntelligenceLike:
        header: StubHeader = field(default_factory=StubHeader)
        predictions: object = None
        anomaly: object = None

    @dataclass(frozen=True)
    class StubOptimizationLike:
        header: StubHeader = field(default_factory=StubHeader)
        view: Any = None
        quality_descriptions: Any = None

    @dataclass(frozen=True)
    class StubTwinLike:
        header: StubHeader = field(default_factory=StubHeader)
        line: str = "kiln"
        snapshot: object = None

    assert not app._is_whatif(StubOverviewLike())
    assert not app._is_whatif(StubEnergyLike())
    assert not app._is_whatif(StubIntelligenceLike())
    assert not app._is_whatif(StubOptimizationLike())
    assert not app._is_whatif(StubTwinLike())
    assert app._is_whatif(StubWhatIfModel())


class SpyState:
    """A state that records how each view was asked for — the routing test's witness."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def what_if(self, *, delta_fractions=None, mode="NORMAL") -> Any:
        self.calls.append(("what_if", str(mode), dict(delta_fractions or {})))
        return StubWhatIfModel(mode=mode)

    def view(self, view_id: str) -> Any:
        self.calls.append(("view", view_id))
        return StubWhatIfModel()

    def capabilities(self) -> Any:
        return None


def test_the_request_wrapper_routes_view_i_with_the_callers_mode_and_changes() -> None:
    """PRD 16.1 reachability: ``--mode`` and ``--change`` reach ``DashboardState.what_if``
    without changing the generic dispatch — and every other view still goes through it."""
    spy = SpyState()
    wrapped = app._WhatIfRequest(
        spy, mode="EXPERIMENTAL", delta_fractions={"kiln_fuel_rate_tph": -0.25}
    )
    model = wrapped.view("I")
    assert model.mode == "EXPERIMENTAL"
    assert spy.calls == [
        ("what_if", "EXPERIMENTAL", {"kiln_fuel_rate_tph": -0.25})
    ]
    assert wrapped.view("what_if").mode == "EXPERIMENTAL"  # the registry key routes too
    assert wrapped.view("B") is not None
    assert ("view", "B") in spy.calls  # every other view delegates, unchanged


def test_the_parser_accepts_the_new_what_if_flags() -> None:
    args = app.build_parser().parse_args(
        ["--view", "I", "--change", "kiln_fuel_rate_tph=-5", "--mode", "EXPERIMENTAL"]
    )
    assert args.change == ["kiln_fuel_rate_tph=-5"]
    assert args.mode == "EXPERIMENTAL"


def test_change_parsing_converts_percent_to_delta_fraction() -> None:
    deltas = app._parse_changes(["kiln_fuel_rate_tph=-5", "kiln_feed_rate_tph=+2.5"])
    assert deltas == pytest.approx(
        {"kiln_fuel_rate_tph": -0.05, "kiln_feed_rate_tph": 0.025}
    )


def test_change_parsing_rejects_unknown_variables_and_malformed_pairs() -> None:
    from src.schema import manipulated_variables

    with pytest.raises(SystemExit) as caught:
        app._parse_changes(["not_a_tag=-5"])
    assert manipulated_variables()[0] in str(caught.value)  # the valid names are listed
    with pytest.raises(SystemExit):
        app._parse_changes(["kiln_fuel_rate_tph"])  # no '='
    with pytest.raises(SystemExit):
        app._parse_changes(["kiln_fuel_rate_tph=five"])  # not a number


def test_mode_or_change_without_view_i_is_an_error_not_a_silent_no_op() -> None:
    assert app.main(["--view", "B", "--change", "kiln_fuel_rate_tph=-5",
                     "--no-browser"]) == 2
    assert app.main(["--view", "B", "--mode", "EXPERIMENTAL", "--no-browser"]) == 2


# =============================================================================
# The golden file
# =============================================================================
#: The stored render of the stub payload above. Regenerate after a *deliberate* renderer change:
#:
#:     python -c "from pathlib import Path; from tests.test_task6_what_if_view import \
#: StubWhatIfModel; from src.digital_twin.settings import DashboardSettings; \
#: from src.visualization import what_if_view; \
#: Path('tests/golden/view_i_normal.html').write_bytes(what_if_view.render_what_if(\
#: StubWhatIfModel(), settings=DashboardSettings.from_config()).encode('utf-8'))"
#:
#: Written with ``write_bytes`` so the fixture keeps its LF newlines in the repository; the
#: comparison below normalises either way, because ``core.autocrlf`` checkouts differ by machine.
GOLDEN_PATH = Path(__file__).parent / "golden" / "view_i_normal.html"

GOLDEN_HINT = (
    "view I's renderer no longer matches its golden file. This is a REGRESSION unless the renderer "
    "was deliberately changed - in which case regenerate the fixture with the command in the "
    "GOLDEN_PATH comment and say so in the commit message. The golden payload is the stub built by "
    "StubWhatIfModel() in this module: fixed timestamps, no measured durations, no wall clock, so "
    "nothing runtime-dependent is pinned."
)


def _golden() -> str:
    return GOLDEN_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_render_matches_the_golden_file(settings: DashboardSettings) -> None:
    """The whole output, pinned byte for byte - a silent formatting or wording change fails here.

    Every string assertion above names one property; this one holds the *shape of the whole panel*
    at once, so a change no single property test thought to name (a reordered attribute, a changed
    class name, a reworded heading) still fails. The golden payload is built from the fixed stub
    in this module, so the comparison pins the renderer, not the run: no timestamp, duration or
    measured value enters it.
    """
    html = what_if_view.render_what_if(StubWhatIfModel(), settings=settings)

    assert html == _golden(), GOLDEN_HINT
    # The fixture is not empty and not a stale stub of itself: it carries the panel's anchors.
    assert 'data-role="whatif-sliders"' in html
    assert 'data-role="whatif-response"' in html
