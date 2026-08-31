# WAVE VIEW J REPORT — first renderer for the AI Optimization screen

**Date:** 2026-08-31
**Branch:** `main` (committed directly per wave instruction; see Git below)
**Objective:** the first renderer for view J, covering directive items 14, 15 and 16 together —
they share one screen and one `OptimizationView` payload.

---

## 1. What was built

| File | Change |
|---|---|
| `docs/TASK6_DIRECTIVE.md` | Step 0: one paragraph in the item 15 entry recording the chosen display form and why view J, not the Time-Series Explorer, is its home. Documentation only. |
| `src/digital_twin/insights.py` | `OptimizationView.baselines()` accessor (14 lines). Same pattern as the existing `recommendation()`: reads `payload["baselines"]`, returns the Mapping or `None`. No new data, no recomputation. |
| `src/visualization/optimization_view.py` | **New** (~330 lines). Plain-HTML renderer for view J: status strip, recommendation card, PRD §14.5 five-row baseline table, gates table, refusal panel, unavailable panel, standing statement. |
| `app.py` | Smallest additive change: one `_is_optimization()` duck-type predicate (three-attribute check on `model.view`) and one `elif` branch in `build_document` routing to the new renderer. No refactor, no rename. |
| `tests/test_task6_optimization_view.py` | **New** — 16 tests (list in §4). |
| `docs/PROJECT_STATE.md` | End-of-wave update. |

## 2. Design decisions

**Step 0 — where the §14.5 comparison lives.** PRD §17 row 6 (Time-Series Explorer,
"baseline vs optimized overlay") is a generic tag-chart requirement tied to AC-3 (chart selection
+ Model A feature importance); it names no five-row set and nothing specific to Model C. §14.5
opens "Every **optimization demonstration** reports …", and §17 view 4 is the AI Optimization
screen — so view J is the home. Recorded in the directive's item 15 entry.

**Display form: a five-row table, not overlaid curves.** §14.5 asks for five named *conditions*
compared over one shared metric set, not time series; the values are steady-state or window
aggregates, so an overlay would imply a time axis the data does not have. Rows render from
`BaselineComparison.describe()` verbatim (`rows`, with each row's `title`, `source`, `detail`,
`metrics`). This is an implementation decision inside PRD §17.1's delegated latitude.

**Honesty rules, verified against the real run:**
- An unavailable row spans the metric columns with `unavailable — <the row's own detail reason>`,
  never a zero or blank (`UNAVAILABLE_ROW_TEXT` + the frozen layer's `detail`).
- `baselines() is None` (optimizer ran without building the comparison) renders a stated
  absence, no table.
- The unavailable-model panel states `MODEL_UNAVAILABLE_LABEL` + reason, no numbers.
- Quality is the categorical HIGH/MEDIUM/LOW with its gloss; no numeric confidence anywhere.
- The refusal panel shows the headline, the blocking gates' own reasons and the rejection count.
- Free text is escaped (`theme.html`); numbers are formatted at `FormatSettings` precision
  (4 sig digits / 3 decimals from `configs/dashboard.yaml`), never re-derived.

**Renderer conventions** follow `svg_twin.py` where they apply: scoped `<style>` with geometry
only (colours/type from theme variables), `data-role` anchors for tests, `theme.html` on every
string, self-contained (no external assets). Plain HTML by design — nothing on this screen
animates, so item 4 / AC-21 do not reach it.

## 3. Tests and regression

- New module: **16 passed** (`pytest tests/test_task6_optimization_view.py`).
- **Full regression: 553 passed, 0 failed, 0 xfailed** (was 537; +16 new, none changed/removed).
- Real end-to-end render: `python app.py --view J --out reports/viewj_smoke.html` — 17,131 bytes
  self-contained; all five §14.5 rows present, recommendation card, baselines table (real
  9-tag metric set), gates table, no forbidden labels, no JSON fallback. In the real run all five
  baseline rows were available (live session has historian history), so the unavailable-row path
  is pinned by the stub tests, not the smoke run.

## 4. The 16 new tests

Items 15 (5): all five PRD titles + all metric tags shown; unavailable row shows its reason not a
number; missing-row names summarised; absent baselines stated never invented; payload values
rendered verbatim. Item 14 (3): quality category + gloss, no confidence %; impact numbers are the
payload's own; free text escaped. Item 16 (2): refusal headline + gates' own reasons; blocking
gate marked. Item 20 (2): standing statement + caveat, no control claim; unavailable model stated.
Accessor (2): exposes the payload mapping with all five rows; `None` when absent. Routing (2):
view J routes to the renderer (no JSON fallback, all five titles present); other non-twin views
keep the payload fallback unchanged.

## 5. Frozen layer

Verified before **and** after the wave — both digests unchanged:

```
src/models src/process_models src/optimization src/simulation src/features
src/data_generation configs pyproject.toml -> c7a1f54dd578900835596c02cb9a19a0
tests/ (non-task6)                               -> 53f2aefec33494be5ca22c08ab22b5fd
```

## 6. Still open for view J

1. **Golden file** — views I/J have been golden-testable since Wave 3C (`signature()`); this wave
   did not write one. The renderer output is deterministic given the payload, so a golden HTML
   fixture is now straightforward.
2. **`app.py:123` badge derivation** (carried from Wave 3B) — `render_twin` still called without
   `synthetic=`; unchanged, out of scope.
3. **Experimental What-if Mode unreachable** (carried from Wave 3D) — `DashboardState.view()`
   still passes only `frame`, so view J renders in NORMAL mode only; the renderer itself handles
   either mode if ever routed.
4. **Multi-horizon prediction display (item 10)** — `predicted_state_by_horizon` is in the
   recommendation payload but not yet rendered as a table/chart; deferred, this wave's scope was
   items 14/15/16.
5. **PRD §17 view 4's "current vs multi-horizon predicted vs recommended state"** as a full
   three-state comparison view — partially covered (baseline + recommended); the horizon grid
   needs the item-10 treatment above.

## 7. Git

One commit on `main`: renderer + accessor + dispatch + tests + docs.
