"""Task #6 — BUG 2: ``runtime_s`` must not make views I and J non-reproducible.

What this module pins
---------------------
Views I (What-If) and J (AI Optimization) each carry a ``runtime_s`` field measured with
``time.perf_counter()`` in :meth:`SyntheticDataProvider.run_what_if` / ``get_optimization``. Two
calls on **one shared frame**, with every input identical, therefore produced payloads that differed
— measured before the fix, on the real provider:

- view I: one changed leaf, ``view.runtime_s`` (2.905 s → 2.506 s)
- view J: two changed leaves, ``view.runtime_s`` **and** ``view.payload.runtime_s`` (6.268 → 4.629)

Nothing else changed in either payload. That is the whole of BUG 2: the views are already
deterministic, and a single wall-clock measurement — appearing at two depths in view J — was the only
thing standing between them and a golden test.

The fix, and the option not taken
---------------------------------
The recovery plan (Section 6, N-1) offered two routes: exclude the field from comparison, or inject a
clock so the duration becomes deterministic under test. This module tests the **exclusion** route,
via a ``signature()`` method — ``describe()`` minus the wall clock — because:

1. the layer below already answers this exact question for this exact field. ``runtime_s`` is
   excluded from :meth:`src.optimization.optimizer.OptimizationResult.signature` by way of its
   ``NON_REPRODUCIBLE_FIELDS``, whose docstring reasons that "``runtime_s`` is a measurement of the
   machine, not of the optimization". Task #6 reuses that convention instead of introducing a second,
   divergent answer in the same repository;
2. it changes **no production behaviour at all** — not one call signature, not one constructor;
3. a clock injected for tests would put a *fabricated* duration into the golden payload, so the
   golden file would pin a number production never emits. The directive forbids fabricating a
   duration, and "fabricated only under test" is still a fabricated number in the artefact a reviewer
   reads.

The honesty requirement this module also guards
----------------------------------------------
Excluding the field from *comparison* must never become deleting it from *production*.
:func:`test_production_still_measures_a_real_duration_and_does_not_fabricate_one` asserts against the
source of ``run_what_if`` that the value handed to the view is still a ``perf_counter`` subtraction
and not a constant — so the cheap "fix" of hardcoding ``runtime_s=0.0`` fails here rather than
passing quietly.

Cost
----
Everything except the last test is hand-built view objects or the stub provider: microseconds, no
provider, no models. The one real-provider test carries the original reproduction end to end and is
**skipped** — never silently slow — when the exported run or the model registry is absent.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import replace
from typing import Any, Callable

import pytest

from src.digital_twin.insights import OptimizationView, WhatIfView
from src.digital_twin.state import DashboardState

#: Two durations a real machine might report for the same run. Distinct, and neither one zero — a
#: zero would let a bug that nulls the field masquerade as a passing strip.
FAST_SECONDS = 4.629229699999996
SLOW_SECONDS = 6.268030100000033


def leaves(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a payload to dotted leaf paths, so a failure names the exact offending field.

    ``{"view": {"runtime_s": 1.0}}`` becomes ``{"view.runtime_s": 1.0}``. Without this, a dict
    inequality on a payload this size reports "these two large dicts differ" and leaves the reader to
    find where — which is exactly the work that made BUG 2 hard to characterise in the first place.
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.update(leaves(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            out.update(leaves(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = obj
    return out


def changed_leaves(first: Any, second: Any) -> dict[str, tuple[Any, Any]]:
    """Every dotted leaf path whose value differs between two payloads."""
    left, right = leaves(first), leaves(second)
    return {
        key: (left.get(key), right.get(key))
        for key in sorted(set(left) | set(right))
        if left.get(key) != right.get(key)
    }


def optimization_view(seconds: float) -> OptimizationView:
    """A view J payload whose duration appears at both depths the real one does.

    ``payload`` is ``OptimizationResult.describe()`` in production, which carries its own
    ``runtime_s``; reproducing that nesting here is the point of this helper, because the nested copy
    is the half of BUG 2 that an outer-only strip would miss.
    """
    return OptimizationView(
        available=True,
        timestamp="2026-01-01T00:00:00",
        mode="NORMAL",
        refused=False,
        message="Reduce kiln feed",
        payload={"runtime_s": seconds, "winner": {"setpoints": {"kiln_feed_tph": 210.0}}},
        gates=({"name": "envelope", "blocking": False, "reason": ""},),
        evaluated=7,
        rejected_candidates=2,
        runtime_s=seconds,
    )


def what_if_view(seconds: float) -> WhatIfView:
    """A view I payload. ``panel`` carries no duration — measured, not assumed (see module docstring)."""
    return WhatIfView(
        available=True,
        timestamp="2026-01-01T00:00:00",
        mode="NORMAL",
        verdict="Within safe operating envelope",
        action="Increase separator speed",
        panel={"mode": "NORMAL", "action": "Increase separator speed"},
        requested=({"name": "separator_speed_rpm", "value": 88.0},),
        runtime_s=seconds,
    )


# =============================================================================
# Tier 1 — the two view classes, in isolation
# =============================================================================
@pytest.mark.parametrize(
    ("build", "depths"),
    [(optimization_view, 2), (what_if_view, 1)],
    ids=["view_J_optimization", "view_I_what_if"],
)
def test_two_views_differing_only_in_runtime_have_identical_signatures(
    build: Callable[[float], Any], depths: int
) -> None:
    """The fix, stated as the property BUG 2 violated.

    Same inputs, same result, two different measured durations: ``describe()`` differs — because
    production is still telling the truth about how long each run took — and ``signature()`` does not.
    ``depths`` records how many leaves the duration reaches, which is the difference between the two
    views and the reason view J needed a nested strip.
    """
    slow, fast = build(SLOW_SECONDS), build(FAST_SECONDS)

    differing = changed_leaves(slow.describe(), fast.describe())
    assert set(differing) == {"runtime_s"} | ({"payload.runtime_s"} if depths == 2 else set()), (
        f"describe() should differ in the duration and nothing else, but changed {sorted(differing)}"
    )
    assert len(differing) == depths

    assert slow.signature() == fast.signature(), (
        "signature() must be identical for two runs differing only in wall clock; still differs at "
        f"{sorted(changed_leaves(slow.signature(), fast.signature()))}"
    )


@pytest.mark.parametrize(
    "build", [optimization_view, what_if_view], ids=["view_J_optimization", "view_I_what_if"]
)
def test_signature_strips_the_duration_at_every_depth_but_describe_keeps_it(
    build: Callable[[float], Any]
) -> None:
    """``signature()`` removes the duration; ``describe()`` is left telling the whole truth.

    The paired assertion matters more than either half. A ``signature()`` that strips nothing leaves
    BUG 2 open; a ``describe()`` that has quietly lost the field means the panel can no longer report
    how long the search took, which is a real fact about the run and not this wave's to delete.
    """
    view = build(SLOW_SECONDS)
    assert "runtime_s" not in leaves(view.signature())
    assert leaves(view.describe())["runtime_s"] == SLOW_SECONDS


def test_view_j_strips_the_nested_duration_and_not_only_the_outer_one() -> None:
    """The trap, pinned on its own: view J carries the same measurement twice.

    ``OptimizationView.payload`` is ``OptimizationResult.describe()``, which has its own
    ``runtime_s``. An implementation that popped only the outer field would satisfy a naive
    "runtime_s not in signature" check on the top level and still leave view J non-reproducible —
    which is what the pre-fix measurement showed (two changed leaves, not one).
    """
    signature = optimization_view(SLOW_SECONDS).signature()
    assert "runtime_s" not in signature
    assert "runtime_s" not in signature["payload"]
    # The rest of the payload must survive the strip - this removes a field, not the nesting.
    assert signature["payload"]["winner"] == {"setpoints": {"kiln_feed_tph": 210.0}}
    assert signature["evaluated"] == 7 and signature["rejected_candidates"] == 2


def test_signature_does_not_mutate_the_view_it_was_called_on() -> None:
    """``signature()`` strips a copy. Called twice, it must answer the same thing twice.

    ``describe()`` shallow-copies ``payload``, so popping the nested duration is safe — but "is safe"
    is a property of that copy existing, and a future ``describe()`` that returned ``self.payload``
    directly would turn this method into a silent mutation that empties the field it reads.
    """
    view = optimization_view(SLOW_SECONDS)
    view.signature()
    assert view.payload["runtime_s"] == SLOW_SECONDS
    assert view.runtime_s == SLOW_SECONDS
    assert view.describe()["runtime_s"] == SLOW_SECONDS
    assert view.signature() == view.signature()


# =============================================================================
# Tier 2 — the screen, which is the level a golden test actually compares
# =============================================================================
@pytest.mark.parametrize(
    ("view_id", "build"),
    [("I", what_if_view), ("J", optimization_view)],
    ids=["view_I_what_if", "view_J_optimization"],
)
def test_the_screen_payload_is_reproducible_once_the_duration_is_excluded(
    stub_provider: type, view_id: str, build: Callable[[float], Any]
) -> None:
    """The property a golden test for views I/J would rest on, at the level it would rest on it.

    A golden file compares the *screen*, not the inner view, so ``WhatIfViewModel`` /
    ``OptimizationViewModel`` are where ``signature()`` has to be reachable. The screen is built
    through the real ``DashboardState.view`` dispatch and only its inner view is then swapped for one
    carrying a measured duration — the stub deliberately reports ``runtime_s=None`` (conftest:903),
    so swapping is what makes this test about a real wall clock rather than about ``None``.
    """
    from src.digital_twin.settings import DashboardSettings
    from src.visualization.clock import Clock

    settings = DashboardSettings.from_config()
    provider = stub_provider()
    model = DashboardState(provider, Clock(provider, settings), settings).view(view_id)

    slow = replace(model, view=build(SLOW_SECONDS))
    fast = replace(model, view=build(FAST_SECONDS))

    assert changed_leaves(slow.describe(), fast.describe()), (
        "the screen payload should still carry the differing duration in describe()"
    )
    assert slow.signature() == fast.signature(), (
        f"screen {view_id} still differs at {sorted(changed_leaves(slow.signature(), fast.signature()))}"
    )
    assert "runtime_s" not in leaves(slow.signature())
    # Header, mode and the view's own content must survive - this excludes one field, not a screen.
    assert slow.signature()["header"] == model.describe()["header"]
    assert slow.signature()["view"]["timestamp"] == "2026-01-01T00:00:00"


# =============================================================================
# Tier 3 — the honesty guard: exclusion from comparison, never from production
# =============================================================================
def test_production_still_measures_a_real_duration_and_does_not_fabricate_one() -> None:
    """``run_what_if`` must still hand the view a measured subtraction, not a constant.

    This is the test that makes the chosen fix safe to keep. "Make views I/J reproducible" has an
    illegitimate one-line solution — ``runtime_s=0.0`` in production — which would pass every other
    test in this module while making the panel lie about the run. So the shape of the expression is
    asserted against the source: the argument must be a subtraction built from ``perf_counter``, and a
    literal there fails here.

    Asserted structurally rather than by calling the provider because the alternative is an 11 s
    session build to observe a number this states as a fact about the code.
    """
    from src.digital_twin.synthetic import SyntheticDataProvider

    # dedent because a method's source arrives indented, which ast.parse rejects outright.
    tree = ast.parse(textwrap.dedent(inspect.getsource(SyntheticDataProvider.run_what_if)))
    durations = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "runtime_s"
    ]
    assert len(durations) == 1, f"expected exactly one runtime_s argument, found {len(durations)}"
    expression = durations[0]

    assert not isinstance(expression, ast.Constant), (
        "runtime_s is a hardcoded constant in production: reproducibility must come from excluding "
        "the field from comparison (signature()), never from fabricating the duration"
    )
    assert isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Sub), (
        "runtime_s should be an elapsed-time subtraction"
    )
    assert "perf_counter" in ast.dump(expression), (
        "the elapsed time should still be measured with time.perf_counter()"
    )


# =============================================================================
# Tier 4 — the original reproduction, end to end on the real provider
# =============================================================================
def _artefacts_missing() -> str:
    """Why the real-provider reproduction cannot run here, or ``""`` when it can.

    Checked *before* building, because ``DashboardSession.build`` answers "nothing exported" by
    regenerating the run — correct for a fresh checkout, and minutes of simulation this test has no
    business spending. A missing artefact is a skip, never a slow success. Same discipline, and the
    same three artefacts, as ``test_task6_performance._artefacts_present``.
    """
    from src.paths import (
        DATA_SYNTHETIC_DIR,
        KILN_DATASET_STEM,
        MILL_DATASET_STEM,
        MODEL_REGISTRY_PATH,
        PROJECT_ROOT,
    )

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


@pytest.mark.parametrize("view_id", ["I", "J"])
def test_the_real_provider_returns_one_reproducible_signature_per_view(view_id: str) -> None:
    """BUG 2's own reproduction, kept as a test: two calls, one frame, identical signatures.

    Everything above works on constructed payloads, which is what makes it fast — but it also means
    nothing above would notice if the real provider introduced a *second* non-deterministic field.
    This test is the one that would: it asserts the strong form, that after excluding the duration the
    two payloads are equal leaf for leaf, so any new wall clock, counter or random draw anywhere in
    views I/J fails here.

    One shared frame, because two frames would legitimately differ in timestamp and observed state;
    the claim under test is about the view, not about the plant advancing.

    ~25 s when it runs: one real session build plus two optimizer searches per view.
    """
    reason = _artefacts_missing()
    if reason:
        pytest.skip(reason)

    from src.digital_twin.session import DashboardSession

    session = DashboardSession.build(replay=False)
    if session.models.what_if is None:
        pytest.skip(f"no what-if engine was wired in: {session.notes()}")

    state = DashboardState(session.provider, session.clock, session.settings)
    frame = state.frame()
    first = state.view(view_id, frame=frame)
    second = state.view(view_id, frame=frame)

    assert first.signature() == second.signature(), (
        f"view {view_id} is still not reproducible; changed leaves: "
        f"{sorted(changed_leaves(first.signature(), second.signature()))}"
    )
    assert "runtime_s" not in leaves(first.signature())

    # The other half of the contract: production is still reporting a real, positive duration. If
    # this view reports None, the test above proved nothing and should not be read as passing.
    measured = first.describe()["view"]["runtime_s"]
    assert isinstance(measured, float) and measured > 0.0, (
        f"view {view_id} reported runtime_s={measured!r}; the field must remain a real measurement"
    )
