# WAVE VIEW J CLOSEOUT REPORT

**Date:** 2026-08-31
**Branch:** `main`
**Objective:** the two open items Wave View J left on the shelf (`WAVE_VIEWJ_REPORT.md` §6):
the golden file for the view-J renderer, and the `app.py` badge derivation carried from Wave 3B.

Two small objectives, in order, each verified before the next. No View H, no Item 10, no
unrelated refactors, no frozen-layer change.

---

## 1. Objective 1 — golden regression test for `optimization_view.py`

The repository has no stored golden fixture yet; its established golden conventions are the
twin's in-process byte-stability tests (`test_task6_twin.py`) and Wave 3C's `signature()`
exclusion (`test_task6_reproducibility.py`), which is what made view J golden-testable. This
wave writes the stored fixture those conventions point at, in their style.

| File | Change |
|---|---|
| `tests/golden/view_j_normal.html` | **New** fixture (4,910 bytes) — the renderer's whole output for the fixed stub payload already defined in the test module (`_view()`: fixed timestamps, no measured durations, no wall clock). Generated with `write_bytes`, so it keeps LF newlines in the repository. |
| `tests/test_task6_optimization_view.py` | +2 tests: (a) byte-stability — two renders of the same payload are byte-identical, the precondition the golden rests on and the check that would catch a clock/draw/ordering leak before the fixture is blamed; (b) byte-equality with the golden file, newline-normalised on read (`core.autocrlf` checkouts differ by machine), with the regeneration command and its intent recorded next to `GOLDEN_PATH`. |

The comparison pins the renderer, not the run: nothing runtime-dependent enters it. The
renderer itself was **not** changed — no deterministic defect surfaced; the first generated
fixture rendered byte-identically on a second render. A change no single property test thought
to name (a reordered attribute, a reworded heading, a changed class name) now fails the suite.

## 2. Objective 2 — `app.py` passes `capabilities().synthetic` to `render_twin`

The defect (carried from Wave 3B, `PROJECT_STATE.md` "`app.py:123` badge derivation"):
`build_document` called `svg_twin.render_twin` without `synthetic=`, so the exported twin's
badge took the `True` default instead of the source's own account of itself — truthful today
(synthetic provider), but derived from nothing.

| File | Change |
|---|---|
| `app.py` | One helper `_source_is_synthetic(state)` reading `state.capabilities().synthetic` — the same derivation `DashboardState._header` uses (Wave 3B's fix) — and one added keyword `synthetic=_source_is_synthetic(state)` on the `render_twin` call. Duck-typed: a bare `view(view_id)` stub state has no capabilities to ask and keeps the renderer's documented `True` default, so no existing stub or caller breaks. The `build_document` docstring's contract note widened accordingly (this wave owns `app.py`, which is what Wave 3B was waiting for). No dispatch-logic change. |
| `tests/test_task6_app_smoke.py` | +1 focused test (parametrised both directions): intercepts `render_twin` and asserts the `synthetic` value handed down equals a real `ProviderCapabilities(..., synthetic=flipped)` built on the stub state. Interception rather than badge-text so the assertion is about the value passed, and bidirectional because a constant `synthetic=False` would also be a derivation of nothing. **Mutation-tested**: deleting the one `synthetic=` line fails both cases. |

## 3. Tests and regression

- Objective 1 focused: `pytest tests/test_task6_optimization_view.py` — **18 passed** (16 existing + 2 new).
- Objective 2 focused: `pytest tests/test_task6_app_smoke.py` — **18 passed** (16 existing + 2 parametrised new).
- Neighbours re-run after the `app.py` change: `test_task6_provider_contract.py` +
  `test_task6_optimization_view.py` + `test_task6_reproducibility.py` — 49 passed.
- **Full regression, once, at the end: 557 passed, 0 failed, 0 xfailed** (was 553; +4 new, none changed/removed).

## 4. Frozen layer

Verified before **and** after the wave — both digests unchanged:

```
src/models src/process_models src/optimization src/simulation src/features
src/data_generation configs pyproject.toml -> c7a1f54dd578900835596c02cb9a19a0
tests/ (non-task6)                               -> 53f2aefec33494be5ca22c08ab22b5fd
```

## 5. Scope discipline

Not started: View H, Item 10 (multi-horizon prediction display), Factory Presentation Mode,
the Experimental What-if Mode routing, the `app.py` docstring timing. No frozen file, no
optimization/baseline computation, no payload schema, no renderer behaviour touched.

## 6. Still open after this closeout

1. Multi-horizon prediction display (item 10) on view J — `predicted_state_by_horizon` is in
   the recommendation payload, unrendered.
2. PRD §17 view 4's full three-state comparison (current / multi-horizon / recommended).
3. Experimental What-if Mode unreachable (`DashboardState.view()` passes only `frame`).
4. `app.py` docstring timing (`--skip-models` advertised at ~0.4 s, measured 4.5 s).
5. Item 17 Factory Presentation Mode; item 19 "Run Demo"; item 22's two missing scans.
6. Twin missing-data symmetry; `TestNfr2Budget`; items 2–13 renderers (8 of 10 views).
7. Item 15's verbatim requirement text (the Tier E2 reconstruction stands; a display now exists).

## 7. Git

One commit on `main`, pushed to `origin/main`.
