"""Task #6 performance evidence: NFR-2, the lazy view path, and where view J's time goes.

This module is the plan's *measure* step (``TASK6_RECOVERY_PLAN.md`` Section 10, phases 6E/6F). It
adds no caching, and it is deliberately built so that almost nothing it asserts can fail for being
run on a slower machine: every claim is either a **PRD budget** (NFR-2's 3 s), a **ratio** between
two numbers measured in the same process, or a **provider call count**, which has no clock in it at
all. Absolute best-case timings are recorded here as measured evidence and never asserted.

What was measured, and how
--------------------------
One process, ``DashboardSession.build(replay=False)`` against ``data/synthetic`` +
``models/registry.json``, ``time.perf_counter`` around each call, Windows 10 / CPython 3.14.
"Warm" means a steady-state call after one throw-away call of the same kind has paid the
sklearn/numpy first-call cost; "cold" means the first call of its kind in the process.

===============================  ==========  ==========
operation                        cold        warm
===============================  ==========  ==========
``DashboardSession.build()``     39.04 s     10.25-11.07 s
  of which ``model_layer``       -           9.99-10.20 s  (97 %; model_a_load 5.69 + model_b_fit 4.31 + optimizer 0.12)
``DashboardState.frame()``       -           0.0015 s
views A-F, each                  -           0.0001-0.0013 s
view G (energy, one history)     -           0.0096-0.0099 s
view H (intelligence)            1.005 s     0.96-1.16 s
view I (what-if)                 1.950 s     1.69-1.87 s
view J (optimization)            4.23-4.35 s 2.84-3.07 s
``state.views()`` (all ten)      ~7.3 s      5.74-6.55 s
``state.views()`` on a stub      -           0.0016 s
``provider.run_what_if(...)``    1.950 s     1.664 / 1.726 / 1.777 s  (min/median/max, 5 runs, a distinct delta each; 1.956 s in one later run)
``provider.what_if_sliders()``   -           0.0002 s
===============================  ==========  ==========

Findings this file exists to record
-----------------------------------
1. **NFR-2 passes at the dashboard layer, not just at the engine layer.** One what-if round trip
   through the real :class:`~src.digital_twin.synthetic.SyntheticDataProvider` costs **1.66-1.96 s**
   against the PRD's 3 s. ``tests/test_optimization.py::TestNfr2Budget`` already
   pins the same budget one layer down, on the :class:`~src.optimization.what_if.WhatIfEngine`
   directly; what is pinned *here* is the operation an operator actually triggers - through the
   provider contract and through ``DashboardState.what_if`` (view I). The measured surcharge the
   dashboard adds over the engine is **under 0.1 %** (view I 1.864 s wall vs 1.862 s of engine
   ``runtime_s``; ``what_if_sliders`` is 0.2 ms and the header is free).

2. **The lazy path is already the one production uses, and the saving is 1900-4900x for the default
   screen.** ``app.py`` calls ``state.view(view_id)`` and nothing under ``app.py`` or ``src/``
   calls ``views()`` - :func:`test_no_production_module_calls_the_eager_accessor` pins that. The
   whole eager cost is behind five provider surfaces (``get_predictions``, ``get_anomaly_state``,
   ``run_what_if``, ``what_if_sliders``, ``get_optimization``): the same ``views()`` call costs
   6-7 s against the real provider and 1.6 ms against the Tier-1 stub, so no part of it is view
   assembly. The stub tests below pin *which* surfaces each screen reads, which is the same fact
   with the clock taken out.

3. **9 of 10 screens are inside 2.0 s warm** - A-G plus H (1.16 s worst) plus I (1.77 s worst).
   The plan's Section 10 claim is therefore correct as written. Single-run figures that put I at
   ~2.6 s and J at ~4.9 s were cold first-calls-in-process: the sklearn/numpy warm-up they include
   is not search cost, exactly as ``configs/optimization.yaml`` (the "MEASURED NFR-2 position"
   block) already records.

4. **View J's cost is Model C's search, not a provider data fetch, and it is already documented.**
   99.8 % of view J is one ``Optimizer.optimize`` call; the provider's own data assembly around it
   is 7 ms (``_optimizer_inputs`` 0.2 ms, ``_flat_row`` 0.2 ms, ``_model_history`` 6.2 ms for 240
   rows, ``_regime_name`` 0.0 ms). Inside that call, measured with accumulating timers rather than
   ``cProfile`` (which inflates the pure-Python twin loop ~2.6x): ``_predict`` **1 call, 1.52 s
   (53 %)** - Model A's 28 horizon models - and ``_evaluate`` **52 calls, 1.33 s (46 %)**, of which
   ``_settle`` is **39 calls, 1.25 s (44 %, 32 ms each)** - fresh twin steady-state solves. Gates,
   ``_recommend`` and ``_rule_state`` are under 1 ms each. So it is *both* one expensive frozen-layer
   call and many: two irreducible halves, both a function of the current operating point.

   This is the shape ``configs/optimization.yaml`` already records as an accepted, measured
   DEVIATION: the full search sits *at* the 3 s budget, neither half shrinks without reshaping an
   approved model (PRD 13.1 / 13.2, frozen by plan Section 11), and shrinking the *search* was
   measured not to help (16 -> 12 -> 8 random candidates moves 3.07 -> 3.01 -> 2.94 s). Within one
   run the deduplication already exists - ``Optimizer._cache`` and ``envelope._MemoScorer`` are
   pure-function memos - and ``Optimizer.optimize`` resets ``self._cache`` per run *on purpose*, so
   that two identical calls produce identical counters. A cross-frame cache is the only lever left,
   and in LIVE mode its key (operating point + history + timestamp) changes every frame, so it would
   miss on every new frame and only pay off when an unchanged frame is re-rendered.

Cost of this module
-------------------
One session build is the only expensive thing here: the :func:`measured` fixture is module-scoped,
builds once, takes every reading in that one pass, and every test below asserts on a recorded number
instead of starting a second stopwatch. ~25 s in total, and it is **skipped** outright when the
exported run or the model registry is absent rather than silently regenerating them - a missing
artefact must never turn into minutes of simulation. Everything else runs against the
``stub_provider`` fixture and costs microseconds.

Nothing here is cached, in the fixture or anywhere else, and no timing figure quoted above is
asserted: the only durations asserted are the PRD's 3 s NFR-2 budget (against the best of three
samples, because this suite runs sessions like this one concurrently and load inflates every
wall-clock reading) and two ratios measured inside a single process.
"""

from __future__ import annotations

import ast
import time
from typing import Any, Callable

import pytest

from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import VIEWS, DashboardState
from src.paths import (
    DATA_SYNTHETIC_DIR,
    KILN_DATASET_STEM,
    MILL_DATASET_STEM,
    MODEL_REGISTRY_PATH,
    PROJECT_ROOT,
    SRC_DIR,
)
from src.visualization.clock import Clock

#: PRD v1.1.1 NFR-2: "A single what-if scenario simulate+predict+optimize round trip completes in
#: **< 3 seconds** on Colab CPU". Restated here rather than read from a config because it has no
#: config home - it is a PRD requirement, not a tunable - and because the point of the assertion is
#: the *requirement*. ``tests/test_optimization.py`` declares the same number for the same reason.
NFR_2_ROUND_TRIP_SECONDS = 3.0

#: Every view id, in layout order.
VIEW_IDS: tuple[str, ...] = tuple(row[0] for row in VIEWS)

#: The four surfaces one :class:`~src.digital_twin.state._Frame` reads. Measured at 1.5 ms for all
#: four together against the real provider, so a screen that reads only these is effectively free.
FRAME_SURFACES: tuple[str, ...] = (
    "get_current_state",
    "get_equipment_status",
    "get_kpis",
    "get_operating_regime",
)

#: The provider surfaces that cost real time, with the measured warm cost of each. These five are
#: the entire difference between 1.6 ms (stub) and 6 s (real provider) for one ``views()`` call.
MODEL_SURFACE_SECONDS: dict[str, str] = {
    "get_predictions": "~0.9 s (Model A, one dataset)",
    "get_anomaly_state": "~0.1 s (Model B)",
    "run_what_if": "1.73 s (Model C what-if round trip)",
    "what_if_sliders": "0.0002 s (metadata only)",
    "get_optimization": "2.84-3.07 s (Model C full search)",
}

#: Which of those five each screen reads - the lazy-path contract, stated per screen. Measured with
#: the Tier-1 stub's own call counter, which is why it needs no clock: a screen that never calls
#: ``get_optimization`` cannot pay Model C's 2.9 s, on any machine.
MODEL_SURFACES_BY_VIEW: dict[str, frozenset[str]] = {
    "A": frozenset(),
    "B": frozenset(),
    "C": frozenset(),
    "D": frozenset(),
    "E": frozenset(),
    "F": frozenset(),
    "G": frozenset(),
    "H": frozenset({"get_predictions", "get_anomaly_state"}),
    "I": frozenset({"run_what_if", "what_if_sliders"}),
    "J": frozenset({"get_optimization"}),
}

#: The screen ``app.py`` renders by default (``app.DEFAULT_VIEWS == ("B",)``) - the animated twin,
#: and the cheapest thing the lazy accessor can be asked for.
DEFAULT_VIEW_ID = "B"

#: Screens that read no model surface at all, so their whole cost is the shared frame.
READOUT_VIEW_IDS: tuple[str, ...] = tuple(
    view_id for view_id, surfaces in MODEL_SURFACES_BY_VIEW.items() if not surfaces
)

#: ``runtime_s`` is the model layer's own measurement of the call the view is a wrapper around, so
#: ``runtime_s / wall`` is the share of a screen that is *not* dashboard code. Measured 0.998-0.999
#: for view I and 0.979-0.998 for view J; asserted at 0.90 because it is a ratio of two numbers
#: taken in the same process and a slower machine scales both.
MODEL_LAYER_SHARE_FLOOR = 0.90

#: Floor on ``eager / lazy`` for the default screen. Measured 1900-4900x (6.0-7.3 s of ten screens
#: against 0.0015-0.003 s for view B with its own frame); asserted an order of magnitude lower still,
#: because the point is "different in kind", not the exact multiple.
LAZY_SAVING_FLOOR = 100.0

#: Ceiling on the share of the eager cost the seven readout screens account for. Measured 0.1-0.3 %.
READOUT_SHARE_CEILING = 0.05


# =============================================================================
# Tier 1 - the lazy-path contract, measured in provider calls rather than seconds
# =============================================================================
@pytest.fixture
def stub_state(stub_provider: type) -> Callable[..., tuple[Any, DashboardState]]:
    """Factory: a :class:`DashboardState` on a fresh counting stub, counter already zeroed.

    :class:`~src.visualization.clock.Clock` reads ``get_current_state`` once when it is constructed,
    which is session setup rather than frame cost, so the counter is cleared *after* wiring. What
    each test then reads out of ``provider.calls`` is exactly what one ``view()`` / ``views()`` call
    asked the provider for.
    """
    settings = DashboardSettings.from_config()

    def build(**flags: Any) -> tuple[Any, DashboardState]:
        provider = stub_provider(**flags)
        state = DashboardState(provider, Clock(provider, settings), settings)
        provider.calls.clear()
        return provider, state

    return build


@pytest.mark.parametrize("view_id", VIEW_IDS)
def test_a_lazy_view_reads_only_the_model_surfaces_its_own_screen_needs(
    stub_state: Callable[..., tuple[Any, DashboardState]], view_id: str
) -> None:
    """``view(id)`` must not pay for a model the screen does not show (plan Section 10).

    The clock-free form of the whole laziness argument. Model C's search is 2.84-3.07 s and its
    what-if round trip 1.73 s; a screen that never calls ``get_optimization`` / ``run_what_if``
    cannot pay them, whatever the machine. Seven of the ten screens call neither.
    """
    provider, state = stub_state()
    state.view(view_id)
    read = {name for name in MODEL_SURFACE_SECONDS if provider.calls[name]}
    assert read == set(MODEL_SURFACES_BY_VIEW[view_id]), (
        f"view {view_id} read model surfaces {sorted(read)}, expected "
        f"{sorted(MODEL_SURFACES_BY_VIEW[view_id])} (costs: {MODEL_SURFACE_SECONDS})"
    )


def test_the_eager_accessor_reads_every_model_surface_that_laziness_skips(
    stub_state: Callable[..., tuple[Any, DashboardState]]
) -> None:
    """``views()`` pays all five, which is the 6 s the lazy path avoids for nine screens in ten."""
    provider, state = stub_state()
    state.views()
    for name in MODEL_SURFACE_SECONDS:
        assert provider.calls[name], f"views() did not read {name}, so the cost model has moved"


def test_each_surface_is_read_once_per_frame_so_the_defect_was_eagerness_not_redundancy(
    stub_state: Callable[..., tuple[Any, DashboardState]]
) -> None:
    """Plan Section 10 / audit P0-2: there is no redundant re-fetch to cache away.

    One ``views()`` call reads each frame surface once and each model surface once - ten screens
    off one read, not ten reads. The 6 s is therefore the *number of models consulted*, not the
    same model consulted repeatedly, which is why the plan's answer is laziness and not caching.
    """
    provider, state = stub_state()
    state.views()
    counts = {name: provider.calls[name] for name in FRAME_SURFACES + tuple(MODEL_SURFACE_SECONDS)}
    repeated = {name: count for name, count in counts.items() if count != 1}
    assert not repeated, f"a surface was read more than once for one frame: {repeated}"


def test_no_production_module_calls_the_eager_accessor() -> None:
    """``app.py`` and everything under ``src/`` must reach a screen through ``view()``.

    Phase 6E/6F's objective, as an invariant rather than a one-off edit: ``DashboardState.views()``
    is kept (it is the documented "all ten from one frame" API and the provenance/contract tests
    use it), but no production caller may reintroduce the eager path. Verified by AST, so a mention
    of ``views()`` in a docstring - ``app.py`` has one, explaining why it does *not* call it - is
    not mistaken for a call.
    """
    modules = [PROJECT_ROOT / "app.py", *sorted(SRC_DIR.rglob("*.py"))]
    offenders: dict[str, list[int]] = {}
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "views"
        ]
        if lines:
            offenders[str(path.relative_to(PROJECT_ROOT))] = lines
    assert not offenders, (
        "production code calls the eager views() accessor, which costs ~6 s against the real "
        f"provider where view() costs 0.003 s: {offenders}"
    )


# =============================================================================
# Tier 3 - one real session, shared by every timing test below
# =============================================================================
def _artefacts_present() -> str:
    """Why the real-provider measurements cannot run here, or ``""`` when they can.

    Checked *before* building, because ``DashboardSession.build`` answers "nothing exported" by
    regenerating the run - correct for a fresh checkout, and minutes of simulation this module has
    no business spending. A missing artefact is a skip, never a slow success.
    """
    missing = [
        str(path.relative_to(PROJECT_ROOT))
        for path in (
            DATA_SYNTHETIC_DIR / f"{KILN_DATASET_STEM}.parquet",
            DATA_SYNTHETIC_DIR / f"{MILL_DATASET_STEM}.parquet",
            MODEL_REGISTRY_PATH,
        )
        if not path.exists()
    ]
    return "" if not missing else f"needs the exported run and the model registry; missing {missing}"


@pytest.fixture(scope="module")
def measured() -> dict[str, Any]:
    """**The one expensive fixture in this module** - a real session, then one measurement pass.

    ~20 s: a ``DashboardSession.build(replay=False)`` (10-11 s warm, and the model layer is 97 % of
    it) plus ~10 s of timed calls. Module-scoped and measured once, so every test below is an
    assertion on a recorded number rather than a second stopwatch; ``replay=False`` because no
    measurement here scrubs a recorded window and building one is a whole second simulation.

    The pass is ordered so that the numbers mean what they say:

    1. one throw-away ``run_what_if`` pays the sklearn/numpy first-call cost - kept as
       ``round_trip_cold`` evidence, and excluded from the budget samples because import warm-up is
       not round-trip cost;
    2. every screen once, on **one shared frame** - which is exactly the work ``views()`` does, so
       ``eager`` is the sum of those ten (7.26 s here against 6.55 s for a real ``views()`` call
       issued straight after; the gap is that this pass pays the *first* ``optimize`` of the
       process and the ``views()`` call behind it does not - see :func:`test_view_j_...`). The
       ``view("I")`` inside it is also the first NFR-2 budget sample: the *whole screen*, wrapper
       included;
    3. ``view(DEFAULT_VIEW_ID)`` with its *own* frame - what ``app.py`` really does - as ``lazy``;
    4. two more ``run_what_if`` calls, each on a delta no earlier run visited, as the remaining
       budget samples through the provider contract.

    Three budget samples rather than one, because this repository's own test suite runs sessions
    like this one concurrently: a machine under load inflates *every* wall-clock reading, and a
    single sample cannot tell "the round trip got slower" from "something else was using the CPU".
    :func:`test_one_what_if_round_trip_is_inside_the_nfr_2_budget` therefore asserts the best of the
    three - and prints all of them on failure, so a genuine regression and a busy machine look
    different in the output.

    Every what-if uses a fresh delta: the engine's memos are pure-function caches, so repeating a
    request would time a dictionary lookup instead of a round trip.
    """
    reason = _artefacts_present()
    if reason:
        pytest.skip(reason)

    from src.digital_twin.session import DashboardSession

    started = time.perf_counter()
    session = DashboardSession.build(replay=False)
    build_seconds = time.perf_counter() - started
    if session.models.what_if is None:
        pytest.skip(f"no what-if engine was wired in, so NFR-2 cannot be measured: {session.notes()}")

    provider = session.provider
    state = DashboardState.from_session(session)

    # Slider names come from the provider, so no manipulated variable is spelled out here.
    variables = [str(slider["name"]) for slider in provider.what_if_sliders()]
    assert len(variables) >= 2, f"NFR-2 needs a manipulated variable to move; got {variables}"

    def timed(call: Callable[[], Any]) -> tuple[float, Any]:
        start = time.perf_counter()
        result = call()
        return time.perf_counter() - start, result

    cold_seconds, _ = timed(lambda: provider.run_what_if(delta_fractions={variables[0]: 0.01}))

    frame = state.frame()
    per_view: dict[str, float] = {}
    models: dict[str, Any] = {}
    for view_id in VIEW_IDS:
        per_view[view_id], models[view_id] = timed(
            lambda vid=view_id: state.view(vid, frame=frame)
        )

    lazy_seconds, _ = timed(lambda: state.view(DEFAULT_VIEW_ID))

    samples: list[tuple[str, float]] = [("view I, the whole screen", per_view["I"])]
    round_trip: Any = None
    for fraction in (0.024, -0.017):
        seconds, round_trip = timed(
            lambda f=fraction: provider.run_what_if(delta_fractions={variables[-1]: f})
        )
        samples.append((f"provider.run_what_if, delta {fraction:+.3f}", seconds))

    return {
        "build_seconds": build_seconds,
        "build_parts": dict(session.build_seconds),
        "per_view": per_view,
        "models": models,
        "eager": sum(per_view.values()),
        "lazy": lazy_seconds,
        "round_trip_cold": cold_seconds,
        "round_trip_samples": samples,
        "round_trip_view": round_trip,
    }


# -- NFR-2 --------------------------------------------------------------------------------------
def test_one_what_if_round_trip_is_inside_the_nfr_2_budget(measured: dict[str, Any]) -> None:
    """**The headline.** PRD NFR-2 through the provider contract and through view I (AC-4).

    Measured 1.664 / 1.726 / 1.777 s (min/median/max over five runs, a distinct delta each) on an
    idle machine, 1.86-1.96 s on a busy one, 1.95 s cold, against the 3 s budget. Asserted against
    the budget rather than against any of those numbers.

    The samples span both layers - one is ``state.view("I")``, the *whole* screen with its slider
    specs and header, and the others are bare ``provider.run_what_if`` calls - so the screen is
    inside the budget claim and not only the engine call within it. That they can be pooled as
    samples of one operation is what
    :func:`test_the_round_trip_cost_belongs_to_the_engine_not_to_the_dashboard` establishes: the
    wrapper is under 0.1 % of the screen. **The best sample is the one asserted**, because a
    concurrently loaded machine adds time that is not the round trip's cost; if this fails, read the
    per-sample list in the message before concluding the round trip regressed.

    The ``assert``s before the timing one matter as much as it does: an unavailable or refused round
    trip would be *fast*, and a timing test that accepted one would pass by not doing the work.
    """
    view = measured["round_trip_view"]
    assert view.available, f"the round trip was not answered at all: {view.unavailable_reason}"
    assert view.requested, "no setpoint request was recorded, so nothing was actually simulated"
    assert view.runtime_s is not None, "the model layer did not report its own runtime"

    samples = measured["round_trip_samples"]
    best = min(seconds for _label, seconds in samples)
    assert best < NFR_2_ROUND_TRIP_SECONDS, (
        f"no what-if round trip came in under the NFR-2 budget of "
        f"{NFR_2_ROUND_TRIP_SECONDS:.0f} s; best was {best:.2f} s. Samples: "
        + "; ".join(f"{label} {seconds:.2f} s" for label, seconds in samples)
        + f" (cold first call in this process: {measured['round_trip_cold']:.2f} s; session build "
        f"{measured['build_seconds']:.1f} s, normally 10-11 s - if that is also inflated, the "
        "machine was busy and this is not a round-trip regression)"
    )


def test_the_what_if_screen_is_the_screen_the_round_trip_is_reached_through(
    measured: dict[str, Any]
) -> None:
    """View I is a real what-if screen, so its timing above is a screen's (item 13, AC-4).

    No second clock: ``state.view("I")`` is already one of the budget samples asserted above, and a
    duplicate timing assertion would only add a second way to fail on a busy machine. What this
    checks is that the sample deserved to count - the screen answered, it carries the slider specs
    an operator moves, and the engine reported its own runtime for the ratio test to use.
    """
    model = measured["models"]["I"]
    assert model.view.available, f"view I could not be answered: {model.view.unavailable_reason}"
    assert model.sliders, "view I carried no sliders, so it is not the what-if screen"
    assert model.view.requested, "view I recorded no setpoint request, so nothing was simulated"
    assert model.view.runtime_s is not None, "view I did not carry the engine's own runtime"
    assert ("view I, the whole screen", measured["per_view"]["I"]) in measured["round_trip_samples"]


def test_the_round_trip_cost_belongs_to_the_engine_not_to_the_dashboard(
    measured: dict[str, Any]
) -> None:
    """The dashboard layer adds no measurable surcharge, so NFR-2 is the engine's number to hold.

    A ratio, not a duration: ``WhatIfView.runtime_s`` is the model layer's own measurement of the
    call view I wraps, so its share of the screen's wall time says how much of the screen is
    dashboard code. Measured 0.998 - the sliders are 0.2 ms and the header is free. This is why
    optimising ``state.py`` or ``synthetic.py`` for NFR-2 would be optimising 0.2 % of the problem.
    """
    seconds = measured["per_view"]["I"]
    runtime = measured["models"]["I"].view.runtime_s
    assert runtime is not None
    share = runtime / seconds
    assert share >= MODEL_LAYER_SHARE_FLOOR, (
        f"only {share:.1%} of the what-if screen was the engine ({runtime:.3f} s of "
        f"{seconds:.3f} s); the dashboard layer has grown a cost of its own"
    )


# -- view J: what a future fix would have to target ---------------------------------------------
def test_view_j_is_one_optimizer_search_and_not_a_provider_data_fetch(
    measured: dict[str, Any]
) -> None:
    """Plan Section 10 names view J the one justified caching candidate; this pins what it *is*.

    ``OptimizationView.runtime_s`` is ``Optimizer.optimize``'s own measurement, and it accounts for
    99.8 % of the screen (measured 2.82-2.93 s of 2.84-3.07 s warm, and 4.336 s of 4.346 s on the
    first ``optimize`` of a process - the ratio holds either way, which is why it is the ratio that
    is asserted). Note that :func:`measured` reaches view J as that first call, so the number the
    failure message prints is the cold one; sklearn/numpy first-call warm-up is roughly 1.4 s of it,
    and ``configs/optimization.yaml`` records the same cold/warm gap for the engine directly.

    The provider's data assembly around the call is 7 ms - ``_optimizer_inputs`` 0.2 ms,
    ``_flat_row`` 0.2 ms, ``_model_history`` 6.2 ms for 240 rows, ``_regime_name`` 0.0 ms. So the
    plan's "the 7.9 s is 100 % provider data-fetching" is the right *location* (behind the contract,
    not in view assembly) but the wrong *mechanism* for this screen: it is model inference and twin
    solving, and no data-fetch cache can reach it.

    Inside the call, measured with accumulating timers: ``_predict`` one call 1.52 s (53 %, Model
    A's 28 horizon models) and ``_evaluate`` 52 calls 1.33 s (46 %), of which ``_settle`` is 39
    fresh twin steady-state solves at 32 ms each. ``configs/optimization.yaml`` already records both
    halves as irreducible without reshaping an approved model, and records that shrinking the search
    does not help. Within one run the deduplication exists already (``Optimizer._cache``,
    ``envelope._MemoScorer``), and ``optimize`` resets that memo per run on purpose so two identical
    calls report identical counters - so the only lever left is a cross-frame cache, whose key moves
    every frame in LIVE.
    """
    seconds = measured["per_view"]["J"]
    view = measured["models"]["J"].view
    assert view.available, f"view J could not be answered: {view.unavailable_reason}"
    assert view.evaluated > 1, (
        f"only {view.evaluated} candidate(s) were evaluated - this was not a real search, so its "
        "timing says nothing about the cost of one"
    )
    assert view.runtime_s is not None
    share = view.runtime_s / seconds
    assert share >= MODEL_LAYER_SHARE_FLOOR, (
        f"only {share:.1%} of view J was the optimizer ({view.runtime_s:.3f} s of {seconds:.3f} s) "
        "- the cost has moved into the provider or the dashboard, and Section 10's caching "
        "candidate would no longer be the right target"
    )


# -- lazy vs eager, against the real provider ---------------------------------------------------
def test_the_lazy_accessor_is_what_makes_a_screen_affordable(measured: dict[str, Any]) -> None:
    """``view(id)`` vs ``views()`` against the real provider, as a ratio.

    ``eager`` is every screen built off one shared frame - the same work ``views()`` does (7.26 s
    summed here; a real ``views()`` call issued straight after, 6.55 s; 5.74-6.31 s over three warm
    runs). ``lazy`` is ``view("B")`` with its own frame - what ``app.py`` does - at 0.0015-0.003 s.
    The measured multiple is 1900-4900x; the floor asserted is 100x, because what has to hold is
    that the two are different in kind, not that this machine reproduces this multiple.
    """
    eager, lazy = measured["eager"], max(measured["lazy"], 1e-9)
    assert eager / lazy >= LAZY_SAVING_FLOOR, (
        f"building all ten screens cost {eager:.3f} s and the default screen {lazy:.4f} s "
        f"({eager / lazy:.0f}x); the lazy path has stopped paying"
    )
    assert measured["lazy"] < NFR_2_ROUND_TRIP_SECONDS, (
        f"the default screen ({DEFAULT_VIEW_ID}) took {measured['lazy']:.3f} s, which is outside "
        f"even the NFR-2 budget of {NFR_2_ROUND_TRIP_SECONDS:.0f} s"
    )


def test_the_seven_readout_screens_are_a_rounding_error_in_the_eager_cost(
    measured: dict[str, Any]
) -> None:
    """All of A-G together are 0.3 % of the eager cost: the three model screens are the whole bill.

    Stated as a share rather than as seconds so it survives any machine. It is the reason the fix
    for a slow dashboard is "do not build H/I/J unless they are on screen" and not a faster panel:
    the seven panel screens read only the shared frame, and the frame is 1.5 ms.
    """
    per_view = measured["per_view"]
    readout = sum(per_view[view_id] for view_id in READOUT_VIEW_IDS)
    share = readout / measured["eager"]
    assert share <= READOUT_SHARE_CEILING, (
        f"the {len(READOUT_VIEW_IDS)} readout screens are {share:.1%} of the eager cost "
        f"({readout:.3f} s of {measured['eager']:.3f} s); they used to be 0.3 %, so one of them "
        "has started consulting a model"
    )
