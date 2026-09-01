# VIEW H AUDIT — AI Prediction & Anomaly (items 10 + 11) — reconnaissance only

**Date:** 2026-09-01
**Scope:** read-only. No code, test, fixture or frozen-layer file was changed for this audit;
the only product of this step is this file. View H is **not** implemented here.

View H is "AI Prediction & Anomaly" — directive **items 10 and 11**, both **Tier E1** in
`docs/TASK6_DIRECTIVE.md` §1 (lines 187–207): unlike item 15, nothing here needs reconstruction;
the requirement text is recovered and the payloads are built. What is missing is the renderer, in
exactly the state view J was in before Wave View J (`docs/WAVE_VIEWJ_REPORT.md`).

Mapping, stated once so it cannot drift: view H carries **Model A's own forecast grid** (item 10)
plus **Model B's anomaly verdict** (item 11, PRD §17 view 7's anomaly content). PRD §17 view 4
(view J) carries the *recommendation's* `predicted_state_by_horizon`. Two different fields, two
different views — see §2.

---

## 1. PRD anchors, verified at HEAD

- **§13.1 (line 523):** Model A targets — kiln `burning_zone_temperature`, `oxygen_percent`,
  `clinker_production_tph`, `thermal_energy_kcal_per_kg_clinker`; mill `mill_motor_power_kw`,
  `simulated_blaine_cm2_g`, `specific_power_consumption_kwh_t`. Horizons **t+5/10/15/30 min,
  mandatory, configurable** — confirmed in `configs/ml.yaml:14` (`horizons_min: [5, 10, 15, 30]`,
  commented "PRD 13.1 mandatory default horizons").
- **§13.1.1 (line 532):** uncertainty is the RF tree-spread / GBM bootstrap-ensemble spread
  (N=20), mapped to categorical **HIGH/MEDIUM/LOW** Recommendation Quality — "never a fabricated
  percentage". In the payload the spread is `Value.uncertainty` (`src/digital_twin/provenance.py:117`,
  with `interval` at `:125` documented as "an ensemble spread (PRD 13.1.1), never a confidence %").
- **§15 (lines 647–657), the anomaly UI/output contract, quoted exactly:**

  ```
  WARNING
  Detected anomaly: <regime name, e.g. "Low Oxygen Condition">
  Likely cause (model-based hypothesis): <from SPC-tag attribution + nearest matching regime>
  Affected variables: <ranked list from SPC z-scores / Isolation Forest feature contribution>
  Suggested action: <from the Section 14.6 rule engine, explicitly labeled as a rule-based suggestion, not a diagnosis>
  ```

  plus §15's closing rule: outputs are phrased as "model-based hypothesis", never definitive
  diagnosis. The frozen layer already has this block verbatim in shape and wording:
  `AnomalyReport.render()` (`src/anomaly_detection/detector.py:191-207`).
- **§14.4 (line 618):** `predicted_state_by_horizon` is a field of the `Recommendation` object —
  Model A output that reaches the *optimization* view inside the recommendation payload. It is
  **not** view H's data. View H's own Model A payload is `PredictionSet`
  (`src/digital_twin/insights.py:39`), built directly from the current row, not from any
  recommendation. The distinction is already documented from the view-J side
  (`insights.py:253-269`, `predicted_states()`) and from the view-H side (`state.py:777-799`,
  `intelligence()` reads `provider.get_predictions`, never the optimizer). **This separation holds
  at HEAD; a view-H renderer must not conflate them.**
- **§17 view 7 (line 700):** "Live anomaly score, 'Inject abnormal condition' control, warning
  card (Section 15)". See gap G-8: the inject *control* does not exist anywhere; injection happens
  through the scenario schedule only.
- **§13.4 (line 554):** "Every prediction/recommendation displayed in the UI carries its source
  model version" — `PredictionSet.model_version` exists (`synthetic.py:1321`, `:1324`).

## 2. What already exists (payload, accessors, plumbing, tests)

### Payloads — complete; preserve, do not rewrite

| Piece | Where | Notes |
|---|---|---|
| `PredictionSet` | `insights.py:39` | Model A's full horizon grid. Two channels by construction: `current` is OBSERVED, `by_horizon` is PREDICTION (`insights.py:44-46`). Accessors `horizon()` `:62`, `target_row()` `:65`, `targets()` `:74`, `describe()` `:82`, `unavailable()` `:98`. Carries `uncertainty` per forecast `Value`, `missing` (target,horizon) pairs, `model_version`. |
| `AnomalyState` | `insights.py:108` | Model B's row output as a panel reads it. `from_report()` `:156` implements item 11's display rule: when evidence cannot separate instrument fault from process deviation, `display_cause` reads `EVIDENCE_INCONCLUSIVE_LABEL` ("Evidence inconclusive", VERBATIM, `labels.py:83`) while the nearest regime signature stays as `nearest_regime`, a similarity match, never a cause. |
| Screen model `IntelligenceView` | `state.py:355` | Holds both payloads plus `columns` (`horizon_labels()`, `insights.py:458`) and `rows` of `PredictionRow` (`state.py:329`) — one per target, `current` and `horizon` as **two fields**, not one row of "values". |
| Builder `DashboardState.intelligence()` | `state.py:777` | Capability-gated on `caps.predictions` / `caps.anomaly` (`payloads.py:184-185`); `ValueError` (model refusal: NaN feature row, too-short lag window) and `CapabilityError` both become unavailable states carrying the model's own words (`state.py:801-825`). |
| Provider surface | `provider.py:122/126`, `synthetic.py:1223/1245` | `get_anomaly_state` scores the row under the cursor; `get_predictions` builds the grid from the current row, keeping observed and predicted apart and refusing to fill gaps (`synthetic.py:1264-1280`). |
| Frozen layer | `detector.py:169-231` | `AnomalyReport` in exactly the §15 fields; `render()` is the §15 block verbatim. |
| Labels | `labels.py:64-65, 83` | `ANOMALY_HYPOTHESIS_LABEL`, `RULE_BASED_SUGGESTION_LABEL` (both VERBATIM §15 wording), `EVIDENCE_INCONCLUSIVE_LABEL`. |
| Chart spec | `charts.py:223` | `prediction_fan(prediction: PredictionSet, …)` — the §17 view-4/5 prediction fan as a `ChartSpec`, provenance-coloured. Exists, **untested, and consumed by nothing** (see G-6). |

### Tests — the payload layer is pinned; the display layer is not

| Coverage | Where |
|---|---|
| Two-channel separation of `PredictionSet` (OBSERVED current / PREDICTION horizons, spread not %) | `test_task6_provider_contract.py:241` |
| Capability-poor provider degrades to unavailable states on view H | `test_task6_provider_contract.py:477-478` |
| `mixed_channels` audit clean across all ten views (view H included) | `test_task6_provider_contract.py:301-308` |
| Model refusal (NaN row / short window) becomes a display state, not a crash; refusal distinguished from absent capability; no fabricated number, no 0.0 "all clear"; guard invisible when nothing raises; `TypeError` still surfaces | `test_task6_frame_nan.py` — 12 tests, view H is that module's subject (`:227-366`) |
| View H routing raises honestly on a broken stub / NaN exit code 3 | `test_task6_app_smoke.py:151-153, 340-343` |
| View H build time (~1.0 s, the most expensive screen) | `test_task6_performance.py:24` |
| **`from_report`'s "Evidence inconclusive" branch — zero tests** | directive item 11 status: "IMPLEMENTED (payload only). **Untested.**" |
| `prediction_fan` / `sparkline` chart builders — zero tests | no hits for either name in `tests/` |

### What renders today

Nothing. `app.py` routes view H into the JSON payload fallback: `_payload_html()`
(`app.py:112-123`, "no renderer for this screen yet"), because `build_document` only special-cases
the twin (`_is_twin`, `app.py:62`) and view J (`_is_optimization`, `app.py:71`, `:165`).
`DEMO_GUIDE.md:301` documents this honestly ("view H … JSON payload").

---

## 3. Gap matrix — what a View H renderer wave must add

Same convention as the View J reconnaissance: **payload exists and is correct → the gap is display
only**, unless flagged otherwise.

| # | Gap | Anchor | What is missing |
|---|---|---|---|
| G-1 | View H renderer module | §17 view 7, items 10–11 | No `src/visualization/` renderer for view H (only `svg_twin` and `optimization_view` exist). Pattern to follow: `optimization_view.py` — scoped `<style>`, `data-role` anchors, `theme.html` on every string, numbers at `FormatSettings` precision, plain HTML (nothing on this screen animates, so item 4/AC-21 do not reach it). |
| G-2 | Forecast grid (item 10) | §13.1/§13.1.1, AC-16 | Rows/columns are pre-built in the payload (`PredictionRow`, `horizon_labels()`); nothing renders them. Must show every configured horizon as a column (5/10/15/30 from `configs/ml.yaml`, not hardcoded), value with its `±` ensemble spread, and OBSERVED/PREDICTION provenance badges so the two channels are visibly separate (the view-J precedent: `test_task6_optimization_view.py:428`). Never a confidence %. |
| G-3 | PRD §15 warning card (item 11) | §15 (quoted in §1 above) | All five contract lines' data is on `AnomalyState`; nothing renders the card. The frozen layer's `AnomalyReport.render()` gives the exact wording/shape to follow; `hypothesis_label`/`action_label` carry the two VERBATIM §15 labels. NORMAL rows render "No anomaly detected", not a blank card. |
| G-4 | Item 11's inconclusive display, tested | item 11, §11.4 regime 14 | `from_report`'s "Evidence inconclusive" branch is implemented but untested (directive status). The renderer wave must pin it: cause reads the label, `nearest_regime` still shown as a similarity match, never as a cause. |
| G-5 | Unavailable panels | item 5, NFR-6 | Both payloads have unavailable states with the model's own reason; nothing renders them. Must state `MODEL_UNAVAILABLE_LABEL` + reason, no numbers (the refusal-vs-absent distinction `test_task6_frame_nan.py:255` protects must stay visible). |
| G-6 | Chart builders wired or consciously skipped | §17 views 4–8 | `prediction_fan` (`charts.py:223`) exists for a `PredictionSet` but is consumed by nothing and untested. The renderer wave decides: render the fan (Plotly optional per `to_html`/`missing_chart_html` degradation) or state the skip explicitly. Either way, do not leave it dead code untested. |
| G-7 | Golden fixture + reproducibility | Wave 3C convention | No `signature()` on `IntelligenceView` — probably **not needed**: unlike views I/J the view-H payload carries no `runtime_s` and no wall-clock of its own (timestamps come from the frame), so `describe()` may already be golden-testable as-is. Verify during implementation before adding one; if a non-reproducible leaf exists, follow `WhatIfViewModel.signature()` (`state.py:408`). Golden would live in `tests/golden/` (excluded from the frozen digest by the 2026-09-01 convention fix). |
| G-8 | "Inject abnormal condition" control | §17 view 7 | **Does not exist anywhere** — no UI control, no CLI flag; fault injection happens only through the scenario schedule (`configs/scenarios.yaml` regimes 4–14, `scenario_driver.py:174`). Same class of gap as item 13's sliders and item 17's presentation mode: interactive surface, not renderer data. A directive-level decision, not a renderer-wave default. Out of scope unless the wave instruction says otherwise. |
| G-9 | `app.py` dispatch | — | One additive duck-typed predicate + `elif`, mirroring `_is_optimization` (`app.py:71`, `:165`). No refactor. |
| G-10 | `AnomalyReport` fields dropped by `from_report` | §15 "Affected variables … Isolation Forest feature contribution" | `AnomalyReport.describe()` carries `flagged`, `ood_score_ratio`, `evidence` (`detector.py:209-231`); `AnomalyState` keeps none of them. Decision point for the wave: extend `AnomalyState` additively (the `baselines()` precedent — additive accessor, no rewrite) or state the absence. Note `DEMO_GUIDE.md:303` already tells presenters the JSON shows "the evidence fields the detector used", which today it does not — that sentence will need correcting whichever way the decision goes. |

## 4. Explicitly out of scope / already owned elsewhere

- **Item 22 scans** (no-hard-coded-number, no-confidence-%) — project-level open item, not view H's.
- **Item 17 Factory Presentation Mode** — separate directive-flagged gap.
- **View J's horizon grid** — built (Wave View J horizon); nothing here touches it.
- **Frozen layer** — `src/anomaly_detection/`, `src/models/` untouched by any of the above; the
  renderer reads `AnomalyState`/`PredictionSet`, never `AnomalyReport` directly.

## 5. Frozen layer

Verified before this audit with the corrected convention (`docs/PROJECT_STATE.md`):

```
src/models src/process_models src/optimization src/simulation src/features
src/data_generation configs pyproject.toml -> c7a1f54dd578900835596c02cb9a19a0
tests/ (test_task6_* and tests/golden/ excluded)            -> 53f2aefec33494be5ca22c08ab22b5fd
```

This step changed documentation only; both digests are unaffected.
