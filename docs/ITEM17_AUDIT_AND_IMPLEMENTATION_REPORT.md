# ITEM 17 — FACTORY PRESENTATION MODE (PRD §29): AUDIT AND IMPLEMENTATION REPORT

**Date:** 2026-09-04
**Wave:** Task 6, Item 17 — Factory Presentation Mode, the plant-manager overlay of views A
(Plant Overview) and J (AI Optimization)
**This file is the single report for the whole wave:** audit, per-card trace, verdict,
implementation, tests, digests and git state, per the wave brief.

---

## 1. Git verification (wave start)

```
$ git log --oneline -3
e057125 feat(task6): Wave View I transition chart - SVG command paths + doc corrections
5795e5d feat(task6): Wave CDF - one shared renderer for the process detail screens
091cb4a feat(task6): Wave View I - first renderer for the What-If Simulation screen

$ git status        # clean
```

HEAD at start was `e057125` — the View I transition-chart wave, as the brief expected.
**Item 17 was not implemented:** `src/visualization/` held no `presentation_view.py`, `app.py`
had no presentation dispatch, and `DEMO_GUIDE.md` §7 confirmed only the two config keys
(`presentation.refresh_seconds`, `presentation.headline_decimals`), `PresentationSettings` and
`labels.presentation_card_label()` existed — no view id, renderer, cards or chain. Verified at
source, not assumed.

**Frozen-layer digests, before (see §7 for after):**

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0   (expected — unchanged)

git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd   (expected — unchanged)
```

---

## 2. PRD §29 / §21 checklist — only what the PRD states

PRD §29 defines the mode as "a simplified overlay/alternate rendering of views 1 and 4" — i.e.
View A (Plant Overview) and View J (AI Optimization), **not a separate data path**. Its stated
requirements, in the PRD's own words (no invented layout):

| # | Requirement (PRD §29) |
|---|---|
| 1 | Five KPI cards: Potential Thermal Energy Saving, Potential Electrical Energy Saving, Production Stability, Quality Stability, Anomalies Detected |
| 2 | The five-stage chain: Current Plant State → AI Prediction → Optimization Opportunity → Recommended Action → Expected Benefit |
| 3 | An overlay/alternate rendering of views 1 and 4 — no new data path |
| 4 | Never raw tag lists, model internals, or code |
| 5 | No numeric confidence percentage; model quality categorical only (HIGH/MEDIUM/LOW) |
| 6 | Visible link/footnote to the §21 disclaimer (§21.5 statement verbatim) |
| 7 | Simplified for a plant-manager audience (no simulation-science detail) |

Supporting requirements: §21.5's standing statement ("The synthetic model is a development and
demonstration environment, not a calibrated representation of any specific cement plant."),
FR-12/FR-23/AC-18 (categorical quality, never a numeric confidence), §17.1 line 705 (the mode
is configuration on top of the existing screens).

---

## 3. Per-card and per-stage trace to existing View A / View J data

No code changed during tracing. Every row below names the existing field the requirement maps
to, or states the gap.

| Card / stage (PRD §29) | Existing source | Status |
|---|---|---|
| Potential Thermal Energy Saving | View J `payload["recommendation"]["expected_impact"]["thermal_energy_kcal_per_day"]` + per-metric `delta_pct` for `thermal_energy_kcal_per_kg_clinker` | COMPLETE-VIA-REUSE |
| Potential Electrical Energy Saving | View J `expected_impact.electrical_energy_kwh_per_day` + per-metric `delta_pct` for `specific_power_consumption_kwh_t` | COMPLETE-VIA-REUSE |
| Production Stability | **No model output computes a production-stability metric.** `predicted_variability_pct` (view J) is Model A's cross-horizon spread, not a stability measure; the optimizer's stability/quality penalty terms are model internals §29 bans from this mode | BACKEND-GAP |
| Quality Stability | **No model output computes a quality-stability metric.** Same evidence as above; `objective_breakdown` is equally model internals | BACKEND-GAP |
| Anomalies Detected | View A's anomaly tile: `AnomalyState` verdict (NORMAL / WARNING / anomaly label) via the existing `_anomaly_status_tile` mapper. The system has a per-instant verdict, **no anomaly count** — none invented | COMPLETE-VIA-REUSE (verdict, not a count) |
| Current Plant State | View A stage strip: five `OverviewStageView`s (state words RUNNING/IDLE, rates) | COMPLETE-VIA-REUSE |
| AI Prediction | View J `predicted_state_by_horizon` — summarised as "N plant values over t+5min … t+10min", no raw tag table | COMPLETE-VIA-REUSE |
| Optimization Opportunity | View J headline pill (ok/warn/unknown), message, `refusal_reasons` — refusals are display states (item 16) | COMPLETE-VIA-REUSE |
| Recommended Action | View J `delta_fractions` moves ("kiln_fuel_rate_tph −5.00 %"), `recommendation_quality` categorical, hold state | COMPLETE-VIA-REUSE |
| Expected Benefit | View J `expected_impact` daily-energy rows + standing `SIMULATED_SAVING_CAVEAT` | COMPLETE-VIA-REUSE |

---

## 4. Verdict

**Mixed, resolved per-card as the brief allows:**

- **Cards 1, 2, 5 and all five chain stages — verdict A (pure overlay):** every quantity exists
  in View A / View J payloads today; the mode is a re-rendering, no new data path.
- **Cards 3 and 4 (Production / Quality Stability) — verdict C (backend gap) for those cards
  only:** no model in this system computes either metric, and the nearest quantities are model
  internals §29 forbids from this mode. Per the brief they render as explicit "unavailable"
  cards with the real reason — **no stability score was invented.**
- **One small verdict-B element (documented prerequisite, not backend work):** a `presentation()`
  composition builder in `state.py` (calls the existing `overview()` and `optimization()` builders,
  computes nothing new) plus an optional `optimization=` kwarg on `overview()` so the optimizer
  runs once, not twice. This is view-model plumbing in the Task-6 layer, which the wave scope
  allows (`state.py` accessor).

---

## 5. Implementation

**New: `src/visualization/presentation_view.py`** — the renderer, following the established
conventions (plain HTML fragment, scoped `<style>`, theme tokens, `theme.html` escaping,
`data-role` attributes, dt-card/dt-pill/dt-badge classes, provenance badges,
`NO_PLANT_CONNECTION_STATEMENT` banner):

- **KPI section (`data-role="kpis"`), five cards in the PRD's order:**
  - the two saving cards carry `expected_impact`'s own daily-energy deltas at
    `presentation.headline_decimals` precision (NaN-safe, thousands-grouped), plus the per-metric
    `delta_pct` and the basis hours, labelled **"Simulation Estimate"** via
    `labels.presentation_card_label("estimate")`;
  - the two stability cards are **honest gaps**: `PRODUCTION_GAP_REASON` / `QUALITY_GAP_REASON`
    state that no model in this system computes the metric and why the nearest quantity doesn't
    qualify; label "Synthetic Demonstration";
  - the anomaly card carries Model B's own verdict (status pill + label + detail) — a per-instant
    verdict; **no count exists and none is invented**.
- **Chain section (`data-role="chain"`):** the five stages in the PRD's order with arrow
  separators. Each stage handles three shapes: normal values, refusal (item 16 display state,
  `NO_SAFE_RECOMMENDATION` + gate reasons) and unavailable model (own reason, never a blank).
- **Transfer-strategy section (`data-role="transfer-strategy"`):** §21.5's statement **verbatim**
  (`labels.TRANSFER_STRATEGY_STATEMENT`), titled "Synthetic-to-Real Transfer Strategy (PRD §21)"
  — the visible §21 footnote the PRD mandates (the export is a static file, so the link is a
  visible footnote block naming Section 21).
- **What never appears:** no numeric confidence percentage anywhere (quality is HIGH/MEDIUM/LOW),
  no raw tag readout lists, no model internals (`objective_breakdown`, `delta_fractions` as a
  dump, `state_sources`, OOD diagnostics), no code, no "Automatic Control Command" label.

**`src/digital_twin/state.py`** (Task-6 layer, allowed): `PresentationViewModel` dataclass +
`presentation()` builder; `_PRESENTATION_ROW` header row (beside the registry — **the overlay is
not an eleventh `VIEWS` row**, `len(VIEWS) == 10` stays pinned); `overview()` gained an optional
`optimization=` kwarg so the composed pass runs the optimizer once. Default behavior unchanged.

**`app.py`:** duck-typed `_is_presentation(model)` + dispatch branch beside the existing
`_is_*` checks; `_PresentationRequest` wrapper (the established `_WhatIfRequest` pattern)
serving `--view P` / `--view presentation` by delegating everything else to the real state;
epilog documents the mode. Also the brief's optional fix: the module docstring's stale
"~0.4 s" total-runtime claim is now "~4.5 s measured".

**`presentation.refresh_seconds`** (2.0, an ASSUMPTION in the config) is **not consumed**:
the export is a static HTML file, so there is no refresh loop; the report and the renderer
docstring state this rather than inventing client-side behavior. Only `headline_decimals` is
read, via `settings.presentation`.

**Files changed:** `src/visualization/presentation_view.py` (new), `src/digital_twin/state.py`,
`app.py`, `tests/test_task6_presentation_view.py` (new), `tests/golden/view_p_normal.html`
(new), this report, `docs/PROJECT_STATE.md`.

---

## 6. Remaining gaps (stated, not hidden)

1. **Production Stability and Quality Stability cards** — backend gap (verdict C, per-card).
   Needs a real stability metric from the model layer before the cards can carry a number;
   until then they state the absence. **Do not fabricate.**
2. **Anomaly count** — the anomaly detector produces a per-instant verdict, not a counted
   history; the card shows the verdict. A count would need a new detector output (out of scope,
   frozen layer).
3. **Auto-refresh** — `presentation.refresh_seconds` stays an unconsumed assumption; a static
   export cannot refresh. A future serving layer (if ever built) would consume it.
4. **§21 "link"** — satisfied as a visible footnote block naming Section 21 and quoting the
   statement verbatim, since the artifact is a static HTML file with no site navigation.

---

## 7. Frozen-layer digests, after the wave (unchanged — verified)

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0   (expected — unchanged)

git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd   (expected — unchanged)
```

No file under the frozen layer (models / process_models / optimization / simulation / features /
data_generation / configs / pyproject.toml / pre-Task-6 tests) was modified: `git status` shows
only the seven files listed in §5.

---

## 8. Final git state and tests

**Tests (focused, then full regression exactly once):**

- Focused before implementation: `tests/test_task6_overview_view.py` +
  `test_task6_optimization_view.py` (51 passed), then `+ test_task6_provider_contract.py`
  (71 passed) after the `state.py` change.
- New module `tests/test_task6_presentation_view.py`: **22 passed** (22 new; no existing test
  touched or weakened). Covers: normal render of the 5 cards + 5 chain stages; card values,
  labels and `headline_decimals`; honest-unavailable for the gap/unavailable/refusal shapes;
  §21 verbatim; forbidden-content sweep (no confidence %, no raw tags, no internals, no code);
  determinism; `app.build_document` dispatch + `_PresentationRequest` + CLI `--view P`; the
  `len(VIEWS) == 10` pin; real-`DashboardState` composition (one optimizer pass); and the
  golden fixture `tests/golden/view_p_normal.html` (byte-for-byte, newline-normalised, with the
  regeneration command recorded beside `GOLDEN_PATH`).
- Full regression, run exactly once after everything: **715 passed, 0 xfailed, 0 failed** in
  284 s (was 693; +22, all new, no existing test changed or weakened; regression floor 428
  holds).

**Git:** one commit on `main`, pushed to `origin/main`, verified by fetch. The commit hash is
recorded in `docs/PROJECT_STATE.md` (this report is part of that commit, so it cannot contain
its own hash).
