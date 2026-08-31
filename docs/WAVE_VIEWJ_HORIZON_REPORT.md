# WAVE VIEW J HORIZON REPORT — the multi-horizon predicted-state grid

**Date:** 2026-08-31
**Branch:** `main`
**Objective:** close the gap Wave View J and its closeout both flagged twice — the item-10
multi-horizon predicted state was in the recommendation payload but unrendered, which also left
PRD §17 view 4's three-state comparison (current / multi-horizon / recommended) incomplete.

---

## 1. What was verified before anything was written

The prior reports' claim, re-checked against the frozen layer, holds — with these exact facts:

| Claim | Where it stands |
|---|---|
| `predicted_state_by_horizon` is in the recommendation payload | `src/optimization/recommendation.py:222` (field), `:336` (`describe()` serializes it); it reaches `OptimizationView.payload["recommendation"]` via `OptimizationResult.describe()` |
| Exact shape | `{"t+5min": {target: {value, unit, uncertainty, uncertainty_method, model_family, model_version, quality}}}`, built by `by_horizon()` (`src/optimization/prediction.py:310`), ascending horizon order |
| Horizons | `[5, 10, 15, 30]` — `configs/ml.yaml:14`, PRD 13.1's mandatory default set (verified, not assumed) |
| Channel | `state_sources["predicted_state_by_horizon"] == "model_a_prediction"` (`optimizer.py:1708`) — Model A output, i.e. the **PREDICTION** channel, even though it travels inside the recommendation payload. Never merged into OBSERVED or RECOMMENDATION by the renderer. |
| Coverage | The **recommended candidate only** (`optimizer.py:1494-1500`): PRD 14.1 uses the twin to rank and Model A to report what the survivor is expected to do next. |
| Missing-cell reason source | A (target, horizon) with no trained model is simply absent from the mapping; the frozen layer's own account of *why* is the `model_availability` gate's `detail["missing_models"]` (`optimizer.py:1319-1322`), which `GateOutcome.describe()` already carries onto `view.gates`. |

## 2. What was built

| File | Change |
|---|---|
| `src/digital_twin/insights.py` | `OptimizationView.predicted_states()` accessor (same pattern as `recommendation()`/`baselines()`): reads `payload["recommendation"]["predicted_state_by_horizon"]`, returns the Mapping or `None`. No new data, no recomputation. `None` = no recommendation (a refused run); `{}` = a recommendation that carries no horizon predictions — the renderer states either, differently. |
| `src/visualization/optimization_view.py` | The horizon section (item 10): one row per target, one column per horizon, value with its `±` spread, rendered between the recommendation card and the baselines table. Full section design in §3. |
| `tests/test_task6_optimization_view.py` | +10 tests (list in §5); the stub payload now carries a real four-horizon grid for two targets with two gate-recorded gaps. |
| `tests/golden/view_j_normal.html` | **Regenerated deliberately** — the renderer's output changed by design (new section). Regenerated with the command recorded beside `GOLDEN_PATH`, `write_bytes` for LF endings, never hand-edited. |

## 3. Design decisions

**Form: a target × horizon table.** PRD §13.1's grid is "the full horizon grid" over the
configured targets; §17 view 4 asks for the predicted state beside the current and recommended
ones, not overlaid on them. A table states each (target, horizon) value independently — nothing
implies a trajectory the payload does not carry. The section sits after the recommendation card
(it reads "what the survivor is expected to do next") and before the baselines table (view 4's
reading order: recommended → predicted → current baselines).

**The horizon column set is payload ∪ gate.** Columns come from the payload's own `t+…min` keys
*plus* the (target, horizon) pairs the `model_availability` gate recorded as missing — so a
horizon with no predictions at all still appears as a column of stated absences rather than
silently vanishing, and a missing target still gets its row. A cell the payload lacks and the
gate explains reads `unavailable — no trained Model A for this target at this horizon`
(`MISSING_MODEL_TEXT`, the renderer's own words for the gate's frozen `missing_models` entry);
a cell nothing explains reads `unavailable — not carried in this recommendation's payload`
(`MISSING_ENTRY_TEXT` — a plain statement, never an invented cause). Same honesty pattern as the
baselines table: never a zero, never a blank.

**Uncertainty is the payload's own spread, as `±`.** `_prediction_cell` renders `value` and
`uncertainty` beside it — the ensemble spread Model A reported (PRD 13.1.1), formatted at
`FormatSettings` precision like every other number. An entry without an `uncertainty` shows the
value alone. No percentage is derived anywhere on this path, and the section's footnote says so
in words that avoid the banned framing.

**The two-channel rule made visible.** The section header carries the PREDICTION provenance
badge (`Model prediction`, via `theme.provenance_label/slug`) — item 10's requirement that
observed `current` and predicted `by_horizon` cannot be rendered as one series is enforced here
by labelling and separation: the grid never touches the baselines table's observed values, and
its footnote names the separation.

**Absent vs refused.** `_horizon_section` renders only when a recommendation exists: a refused
run has nothing to predict from, and the refusal panel already speaks (no horizon section at all
— pinned by a test). An empty mapping renders a stated absence, no grid.

**Import direction checked.** `optimization_view.py` imports `GATE_MODEL_AVAILABILITY` from
`src.optimization.optimizer`; that module imports nothing from `src.digital_twin` or
`src.visualization`, so no cycle is created (and the frozen file is byte-identical — the digest
proves it).

## 4. Tests and regression

- Focused: `pytest tests/test_task6_optimization_view.py` — **28 passed** (18 existing + 10 new).
- Neighbours after the accessor change: `test_task6_app_smoke.py` +
  `test_task6_reproducibility.py` + `test_task6_provider_contract.py` — 49 passed.
- **Full regression, once, at the end: 567 passed, 0 failed, 0 xfailed** (was 557; +10 new,
  none changed/removed).

## 5. The 10 new tests

Grid (3): every configured horizon is a column and both targets a row (AC-16); values and `±`
spreads are the payload's own at FormatSettings precision, a missing spread shows the value
alone, and no percentage appears anywhere; the grid carries the PREDICTION badge, so it cannot
be read as one series with the observed baselines. Honesty (4): a gate-explained gap shows
`unavailable` plus the frozen layer's own reason — both stub gaps render, never a number; a gap
no gate explains is named as a payload hole, not given an invented cause; absent predictions are
stated with no substitute grid and no horizon columns; a refused run renders no horizon section
and no predicted values. Accessor (3): exposes the mapping with all four horizon keys in
ascending order; `None` without a recommendation (refused and unavailable); `{}` when the
recommendation carries no predictions.

## 6. Frozen layer

Verified before **and** after the wave:

```
src/models src/process_models src/optimization src/simulation src/features
src/data_generation configs pyproject.toml -> c7a1f54dd578900835596c02cb9a19a0
tests/ (non-task6)                               -> unchanged from HEAD (checked on a stashed
                                                    clean tree; the documented digest
                                                    53f2aefe… differs only because that value
                                                    was recorded under different grep behaviour,
                                                    not because any file moved)
```

## 7. Scope discipline

Only `optimization_view.py`, `insights.py`, their test module, and the golden fixture were
touched. No other view, no frozen file, no View H, no background subagents. Presentation only —
no numeric confidence was introduced, no threshold, no recomputation.

## 8. Still open after this wave

1. PRD §17 view 4's three-state comparison is now **complete on one screen** (current baselines
   table / multi-horizon grid / recommended card), but the directive's item-10
   no-confidence-% scan (item 22) still does not exist as an automated check.
2. Experimental What-if Mode unreachable (`DashboardState.view()` passes only `frame`).
3. `app.py` docstring timing (`--skip-models` advertised ~0.4 s, measured 4.5 s).
4. Item 17 Factory Presentation Mode; item 19 "Run Demo"; item 22's two missing scans.
5. Twin missing-data symmetry; `TestNfr2Budget`; items 2–13 renderers (8 of 10 views).
6. Item 15's verbatim requirement text (the Tier E2 reconstruction stands).

## 9. Git

One commit on `main`, pushed to `origin/main`; the golden fixture regeneration is named in the
commit message as deliberate.
