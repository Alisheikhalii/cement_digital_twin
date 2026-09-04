# PROJECT STATE — Task #6 handoff

**Purpose:** the file a new session reads first. One line per outstanding Task #6 item, plus the
current commit and test counts. Created at the end of Wave 3A (`docs/WAVE3A_REPORT.md`); last
substantive wave was the **PRD §25 Colab notebook** (`docs/COLAB_NOTEBOOK_IMPLEMENTATION_REPORT.md`,
2026-09-04): `notebooks/00_cement_digital_twin_demo.ipynb` (the twelve §25 cells + the five §28
demos as single cells in its section 11), `tests/test_task6_notebook.py`, and narrow doc
corrections. The renderer inventory stands: **all ten A–J screens have a renderer, plus the
`--view P` Presentation overlay.**

---

## Current position

| | |
|---|---|
| **Branch** | `main` — the PRD §25 notebook wave is the tip; see `git log` for the earlier waves. |
| **HEAD after this wave** | the notebook-wave commit, whose parent is the final gap-audit commit (`655cee1`). Not pinned here: a commit cannot contain its own hash. |
| **Wave history** | `1f8107f` baseline → `0ed5e39` directive persisted → `3fa2e7d` Wave 1 → `e4dee7a` Wave 2 → `440602e` Wave 3A → `8cbda49` Wave 3B → `557b935` Wave 3C → `b2915e3` Wave 3C merge → Wave 3D (`6b27858` merge) → `a056bf9` item 15 reconstruction → Wave View J (`cac1296`) → Wave View J closeout (`89a93ff`) → Wave View J horizon (`963f6d2`) → View H audit (`52ac068`) → Wave View H (`4a70160`) → View H closeout (`cc86f54`) → Wave View A (`8f61802`) → View A closeout pin (`6dfb67b`) → Wave View G (`6ee2d56`) → Wave View I (`091cb4a`) → Wave CDF (`5795e5d`) → Wave View I transition chart (`e057125`) → Wave Item 17 Factory Presentation Mode (`1db6cec`) → final gap audit (`655cee1`) → **PRD §25 notebook + Item 19 + §28 demos** |
| **Full regression** | **731 passed, 0 xfailed** (PRD §25 notebook wave, 2026-09-04: 715 + the 16 tests of `tests/test_task6_notebook.py`; 4 min 39 s). |
| **xfails** | **None.** |
| **Regression floor** | 428 (directive §4.7). Any drop halts the phase and is investigated — never "fixed" by editing a test. |

### Frozen layer — verify before and after every wave

`src/models`, `src/process_models`, `src/optimization`, `src/simulation`, `src/features`,
`src/data_generation`, `configs`, `pyproject.toml`, and all original 17 test modules must stay
byte-identical.

```sh
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# expected: c7a1f54dd578900835596c02cb9a19a0
git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# expected: 53f2aefec33494be5ca22c08ab22b5fd
```

**Why this rule (fixed 2026-09-01).** The digest protects the 19 pre-Task-6 entries under `tests/`
(17 original modules + `conftest.py` + `__init__.py`, all from baseline `1f8107f`) by excluding every
known Task-6-owned path by name: the `test_task6_*.py` modules and the entire `tests/golden/`
fixture directory. The previous convention (`grep -v task6`) was a substring match on the whole
line, so it failed to exclude `tests/golden/view_j_normal.html` when that fixture landed in Wave
View J closeout — running the documented command produced `dfd6d1e9a1a491f17b81af1c0992a35f`
instead of the recorded value, and every future golden fixture (view H, view I, …) would have
shifted it again. The exclusion form is fail-safe in the right direction: anything *not* explicitly
Task-6-owned is counted, so a new or renamed frozen test file changes the digest loudly, while new
Task-6 test modules (by the `test_task6_` naming convention) and new golden fixtures (anywhere in
`tests/golden/`) are excluded automatically. An enumerate-the-17 rule was rejected: it silently
stops protecting any frozen test added later, and renames would masquerade as digest drift.

### Task #6 test modules (not frozen — these are the ones waves may extend)

`test_task6_provider_contract.py` · `test_task6_app_smoke.py` · `test_task6_frame_nan.py` ·
`test_task6_performance.py` · `test_task6_twin.py` · `test_task6_real_plant_state.py` *(Wave 3A)* ·
`test_task6_reproducibility.py` *(Wave 3C)* · `test_task6_optimization_view.py` *(Wave View J)* ·
`test_task6_intelligence_view.py` *(Wave View H)* · `test_task6_overview_view.py` *(Wave View A)* ·
`test_task6_energy_view.py` *(Wave View G)* · `test_task6_what_if_view.py` *(Wave View I)* ·
`test_task6_process_view.py` *(Wave CDF — one module for all three screens)* ·
`test_task6_notebook.py` *(PRD §25 notebook wave — static structural contracts on the .ipynb)*

Plus the stored fixtures the suite owns: `tests/golden/view_j_normal.html` *(Wave View J
closeout)*, `tests/golden/view_h_normal.html` *(Wave View H)*, `tests/golden/view_a_normal.html`
*(Wave View A)*, `tests/golden/view_g_normal.html` *(Wave View G)*,
`tests/golden/view_i_normal.html` *(Wave View I; regenerated for the transition chart and once
more for a tick-anchor fix — Wave View I transition chart; first regeneration after the
settled-state shape fix documented in `VIEWI_AUDIT_AND_IMPLEMENTATION_REPORT.md` §8.6)* and
`tests/golden/view_c_normal.html` / `view_d_normal.html` / `view_f_normal.html` *(Wave CDF)* —
regenerate any of them only after a deliberate renderer change, with the command recorded beside
the `GOLDEN_PATH`/`GOLDEN_PATHS` in the owning test module.

---

## Outstanding Task #6 items

| Item | State | One line |
|---|---|---|
| **Item 15 requirement text** | **DISPLAY NOW EXISTS** (Wave View J) — reconstruction itself unchanged | Directive D-1. The verbatim text is still unrecovered; the labelled Tier E2 reconstruction stands. Its implied display is **now built**: view J's renderer shows the full PRD §14.5 five-row comparison (item 15's Step 0 display-form decision is recorded in `TASK6_DIRECTIVE.md` §1 item 15 — a table, on view J, not the Time-Series Explorer). Accessor: `OptimizationView.baselines()`. Recovering the verbatim item would still supersede the reconstruction. |
| **Items 14 / 15 / 16 / 10 — view J renderer** | **DONE** (Wave View J + closeout + horizon) | `src/visualization/optimization_view.py` renders all four: the recommendation card from `Recommendation.describe()` unchanged (14), the §14.5 five-row table with unavailable rows showing their own reason (15), refusals as a display state with the gates' own words (16), and the item-10 multi-horizon predicted-state grid (10) — one row per target, one column per configured horizon (5/10/15/30 from `configs/ml.yaml`), value with its `±` ensemble spread, never a confidence percentage, in the PREDICTION channel and kept separate from the observed baselines. `app.py` routes view J via one additive duck-typed `elif`. Accessors: `recommendation()`, `baselines()`, `predicted_states()`. 28 tests; see `WAVE_VIEWJ_REPORT.md` and `WAVE_VIEWJ_HORIZON_REPORT.md`. **PRD §17 view 4's three-state comparison (current / multi-horizon / recommended) is now complete on one screen.** |
| **B-7 badge (2 sites)** | **CLOSED** (Wave 3B) | Both sites derive the badge from `capabilities().synthetic` via `labels.presentation_card_label()`: `DashboardState._header` reads it inline, and `svg_twin` threads an explicit `synthetic: bool` through `twin_document`/`twin_html`/`render_twin`/`_header_html`. Both strict xfails removed. |
| **`app.py:123` badge derivation** | **CLOSED** (Wave View J closeout) | `build_document` now passes `synthetic=_source_is_synthetic(state)` to `render_twin` — the same `capabilities().synthetic` derivation `state._header` uses (Wave 3B's pattern). Duck-typed, so a bare `view(view_id)` stub keeps the `True` default and no caller breaks. Mutation-tested regression test in `test_task6_app_smoke.py`; see `WAVE_VIEWJ_CLOSEOUT_REPORT.md` §2. |
| **BUG 2** | **CLOSED** (Wave 3C) | Views I/J were non-reproducible only in `runtime_s` — view J carried it at two depths (`view.runtime_s` *and* `view.payload.runtime_s`). Fixed by **excluding it from comparison**: a `signature()` method on `WhatIfView`/`OptimizationView` and both screen view models, reusing the frozen layer's own `OptimizationResult.NON_REPRODUCIBLE_FIELDS` convention. `synthetic.py` is byte-identical to `main` — zero production change. An AST guard (mutation-tested) fails if production ever hardcodes the duration. Views I/J are now golden-testable; **no golden file written yet.** |
| **Twin missing-data symmetry** | **Closed by evidence (audit wave)** — no directive/PRD/audit text defines this item (it originates in Wave 3A's handoff table, undefined). The nearest evidenced requirements — a missing reading draws stopped, never at an invented speed; a driverless glyph draws still and says so — are implemented and test-pinned (`test_task6_twin.py:520,558`). No recoverable requirement remains unimplemented. |
| **`TestNfr2Budget`** | **DONE — both layers** (verified 2026-09-03, was a stale "Not written") | NFR-2 (< 3 s what-if round trip) is covered twice: engine layer — `class TestNfr2Budget` in `tests/test_optimization.py:1660`, in the frozen layer since baseline `1f8107f` (`git log -S`); dashboard layer — `test_one_what_if_round_trip_is_inside_the_nfr_2_budget` in `tests/test_task6_performance.py:433`, added in Wave 2 (`e4dee7a`). `configs/dashboard.yaml` `refresh_seconds: 2.0` is **not** a PRD budget (directive D-10). |
| **`DATA_DICTIONARY.md`** | **DONE** (Wave 3D) | PRD §35 document. All 62 rows derived from `TagSpec` in `src/schema.py` and verified programmatically against it (0 content mismatches, 0 range mismatches). Canonical MJ conversion per PRD §9.2; every `ASSUMPTION` value cross-checked against `configs/` and `SIMULATION_ASSUMPTIONS.md`. |
| **`DEMO_GUIDE.md`** | **DONE** (Wave 3D) | PRD §35 document. Demos 1–5 + Presentation Mode, grounded in what `app.py` does today. §9 lists 10 PRD demo capabilities not built. Three claims were corrected by measurement — see `WAVE3D_REPORT.md` §2.1. |
| **Item 17 Factory Presentation Mode** | **DONE** (Wave Item 17, 2026-09-04) | `src/visualization/presentation_view.py` re-renders views A + J as the PRD §29 overlay (`--view P` / `presentation`, via `_PresentationRequest` — not an eleventh `VIEWS` row; `len(VIEWS) == 10` stays pinned). Saving cards + anomaly verdict + five-stage chain reuse existing payloads; the two stability cards are honest gaps (no model computes either metric — stated, never invented). §21.5 verbatim, categorical quality only, no confidence %. `presentation.refresh_seconds` stays unconsumed (static export, no refresh loop). Full trace and verdict: `ITEM17_AUDIT_AND_IMPLEMENTATION_REPORT.md`. |
| **`app.py` docstring timing** | **CLOSED** (Wave Item 17) | The module docstring's `--skip-models` claim now reads "~4.5 s measured" (was "~0.4 s"; measured 4.5 s in Wave 3D). Fixed by the wave that owned `app.py` for the presentation dispatch. |
| **Experimental What-if Mode unreachable** | **CLOSED** (Wave View I) | `app.py` now owns the missing surface: `--change NAME=PERCENT` (repeatable, validated against `schema.manipulated_variables()`) and `--mode {NORMAL,EXPERIMENTAL}`, view-I-only — naming either without `--view I` exits 2. A `_WhatIfRequest` wrapper serves view-I ids from `state.what_if(delta_fractions=..., mode=...)` directly and delegates every other view to the generic dispatch, so no dispatch signature changed. `DEMO_GUIDE.md` §6.2's Python-only workaround is now superseded **and the guide's §6 is fixed**
(Wave CDF): the §6.1-warning/§6.2/§6.3 paragraphs now document `--change`/`--mode` with both
commands verified to run. §5's step-3 note and §9's table rows 5–6 were fixed in Wave View I
transition chart — the docs backlog from
`VIEWCDF_AUDIT_AND_IMPLEMENTATION_REPORT.md` §6.5 is now clear. |
| **Item 19 "Run Demo" sequence** | **DONE — notebook path** (PRD §25 notebook wave) | `notebooks/00_cement_digital_twin_demo.ipynb` section 11: the five §28 demos as single, re-runnable cells, no manual setup after cells 1–8 (`Runtime → Run all`). No arbitrary step sequence — each cell is the PRD §28 scenario itself (one configured regime or one what-if change set, the PRD's own views). Regime names come from `configs/scenarios.yaml`; seed from `simulation.seed`. Demo 3 uses the scheduled low-oxygen regime and states the FR-10 inject gap (no `DemoInjector` exists). The CLI path remains five separate commands (out of scope). See `COLAB_NOTEBOOK_IMPLEMENTATION_REPORT.md`. |
| **Item 22 enforcement scans** | **Partial — P2** | Provenance separation (all ten views, `mixed_channels`), determinism (byte-identity + AST guard), the AC-21 animation-path audit (behavioural + `animation_report` + literal AST audit) and per-renderer no-confidence sweeps all exist and are pinned. The repo-wide no-hard-coded-number scan over dashboard-assembly code does **not** exist: its exact rule is not derivable from the PRD without either vacuity or false failures (renderer-layer structural numbers are PRD-§19.3-sanctioned). Do not write a weak scan just to pass. See the audit report §7.B. |
| **PRD §17 non-lettered views** | **Missing — P1/P3** | Views 6 (Time-Series Explorer), 8 (Model Performance), 9 (Data Quality), 10 (Factory Data Requirements) have no internal letter and no payload/view layer (6/8/9 are backend work; 10 is medium). Not Task-6-closed by the A–J renderer count. See the audit report §4. |
| **Stale documentation** | **DONE (audit wave)** | README "Honest status", DEMO_GUIDE §0.2/§0.4/§7/§9/§10 and ARCHITECTURE §6 all described the pre-renderer state ("8 screens as raw JSON", "Presentation Mode not implemented"). Corrected to the current state; no production file touched. |
| **Items 10 / 11 — view H renderer** | **DONE** (Wave View H) | `src/visualization/intelligence_view.py` renders both payloads of `DashboardState.intelligence()`: Model A's own forecast grid from `PredictionSet` (item 10 — the current row's horizons, **not** view J's recommendation-scoped `predicted_state_by_horizon`) with every configured horizon a column, OBSERVED `Current` and PREDICTION horizons badged as two channels, `±` ensemble spread never a confidence %, and missing (target, horizon) pairs as stated absences with the payload's own account; and Model B's verdict from `AnomalyState` in the PRD §15 contract lines (item 11) — WARNING card, "Evidence inconclusive" verbatim where the evidence cannot separate fault from process (the `from_report` branch, previously untested, now pinned), nearest regime shown only as a similarity match, NORMAL rows as "No anomaly detected." `app.py` routes view H via one additive duck-typed `elif`. 22 tests + `tests/golden/view_h_normal.html`; see `VIEWH_IMPLEMENTATION_REPORT.md`. Remaining view-H gaps (trends/prediction-fan chart, inject control, evidence fields) are listed in that report §10. |
| **Items 3 / 9 / 12 + PRD 18.1 — view A renderer** | **DONE** (Wave View A) | `src/visualization/overview_view.py` renders `DashboardState.overview()`: the item-3 five-stage chain (state word, rate, PRD 8.3 equipment — a grouping of the twin, nothing animates), the items-9/12 plant KPI group whole (specific energy + daily totals, the group's own note), and PRD 18.1's two AI tiles — compact `OverviewStatus` summaries **reused** from the view J / view H payloads (`optimization(frame).view` and `_anomaly("kiln", stamp)`, no second computation), with unavailable models stated with their own reason and refusals as display states. `app.py` routes view A via one additive duck-typed `elif` (`_is_overview`: `stages` + `plant`). 23 tests + `tests/golden/view_a_normal.html`; see `VIEWA_IMPLEMENTATION_REPORT.md`. Known gap: PRD 18.1 trend sparklines (no trend channels in the payload — same class of skip as view H's). The perf contract in `test_task6_performance.py` was restated with dated notes (view A reads `get_anomaly_state` + `get_optimization`); the open option — sharing one model read across screens — needs a directive-level decision. |
| **Item 12 — view G renderer** | **DONE** (Wave View G) | `src/visualization/energy_view.py` renders `DashboardState.energy()`: the item-12 pair section — the specific-energy figures, the daily totals they imply and the production rates between them, all three partitions of the one plant KPI group on one screen with the payload's own `SPECIFIC_VS_TOTAL_NOTE` verbatim, so the favorable half can never stand alone (an empty total partition is *stated* beside the specific figures, never hidden) — plus the kiln and cement-mill KPI groups (item 9). `app.py` routes view G via one additive duck-typed `elif` (`_is_energy`: `specific` + `total`). Audit verdict A (`docs/VIEWG_AUDIT.md`); 19 tests + `tests/golden/view_g_normal.html`; see `VIEWG_IMPLEMENTATION_REPORT.md`. Known gap: the payload's trend channels are not rendered (the deferred chart decision, same class as view H's G-6 skip). |
| **Item 13 — view I renderer** | **DONE** (Wave View I) | `src/visualization/what_if_view.py` renders `DashboardState.what_if()`: the item-13 slider cards with configured bounds and exact step sizes (payload text — a `0.0312` step survives `max_decimals: 3`), the three verdicts as display forms of the engine's own `recommendation_status`, the PRD §16.3 panel — requested change (baseline/requested/simulated, clipped·snapped flags, engine notes verbatim), before/after table, settled state, transition summary (window/hold/ramps as numbers) and **the transition chart — now built** (Wave View I transition chart): a self-contained inline SVG of each moved variable's commanded path (baseline through hold at 0%, then the engine's own linear ramp to 100% of its commanded move), hold guide, 0%/100% rails, ticks at hold end and window end, and a legend with true magnitudes; the plant's response path is not on the payload, so no response curve is drawn — stated in the chart's own note, never interpolated; SVG chosen over Plotly per PRD §19.3 (see `VIEWI_TRANSITION_CHART_REPORT.md`), endpoint agreement with the engine's own unconverged warning, savings line + caveat, per-constraint and per-envelope rows. The PRD 16.1 Experimental banner renders from the payload, never awarded by the renderer; a rejected request states there is no trajectory (it was never simulated); unavailable states carry the payload's own reason. `app.py` routes view I via one additive duck-typed `elif` (`_is_whatif`: `sliders` + `view`) and gained `--change`/`--mode` (closing the unreachable item above). Audit verdict A (`VIEWI_AUDIT_AND_IMPLEMENTATION_REPORT.md` §7); 35 tests + `tests/golden/view_i_normal.html` (regenerated for the chart, and once more for a tick-anchor fix). A real model-layer run caught a stub-vs-engine shape mismatch (`settled_state` is `tag → float`, not `{value, unit}`) that had rendered the settled state as unavailable — fixed, regression-tested, documented in that report §8.6. |
| **Items 5 / 6 / 9 + item-4 inspector — views C / D / F renderer** | **DONE** (Wave CDF) | `src/visualization/process_view.py` — **one** renderer for all three process detail screens (`ProcessView` shares one payload shape; the renderer reads no view id). Each component renders as a card: its state word, health, driving variable (the same observed `Value` views B/E animate by) and its own output-tag readout; the grouped panels (kiln process, kiln emissions — CO in the main panel only, per item 5 — and mill process) and the item-9 KPI group render whole. **View D's `panels=()` / `kpis=None` is designed content, not a gap** (no PRD §17 row names view D — D-2; its FanFuel/Cooler readouts carry every tag its registry line promises): the renderer states both absences as facts, never as errors, never filled in. `app.py` routes C/D/F via one additive duck-typed `elif` (`_is_process`: `components` + `panels` — the twin's `panel`-singular/`equipment` near-misses pinned by test). Audit verdicts C/D/F all A; 27 tests + three goldens; see `VIEWCDF_AUDIT_AND_IMPLEMENTATION_REPORT.md`. Known gaps: `EquipmentStatus.constraints` is carried but unrendered — **PRD verdict (Wave View I transition chart): no requirement exists** (no §17 row names views C/D/F per D-2; §18.2/§18.3 list tags, not per-equipment constraint rows; §16.3's constraint banner is view I's, already rendered) — the field is payload capacity the provider does not currently supply (the stub serves `constraints=()`; the real path in `synthetic.py` `_bands.per_component` exists but no source asks for any), same treatment as view D's `panels=()`; documented, not built; no trend channels exist on these screens' payloads (and no source asks for any). |
| **Items 2–13 renderers** | **DONE — all ten screens** (Wave CDF) | Every A–J view now has a renderer: the SVG twin (B/E), view J, view H, view A, view G, view I and — via the one shared `process_view.py` — C, D and F. The payloads were never rewritten; each wave only rendered what they already carried. |
| **View J golden file** | **DONE — regenerated** (Wave View J closeout; regenerated in the horizon wave) | `tests/golden/view_j_normal.html` — the renderer's whole output for the fixed stub payload, compared byte-for-byte (newline-normalised) by 2 tests in `test_task6_optimization_view.py`. The horizon wave changed the renderer by design and regenerated the fixture with the recorded command (never hand-edited). View I gained its own golden in Wave View I (`tests/golden/view_i_normal.html`). |
| **Task #6 overall status (updated by the notebook wave, 2026-09-04)** | **Task #6 as originally scoped (A–J renderers + honesty + payload layer) COMPLETE; the PRD §25 notebook and its §28 demo cells are now built** | Full matrix in `TASK6_FINAL_GAP_AUDIT_REPORT.md`: AC-1…AC-24 verified; 6/10 PRD §17 views + §29 overlay implemented (views 6/8/9/10 unlettered, backend work); §28 demos are now single cells in the §25 notebook **and** remain runnable via CLI; stability metrics are honest backend gaps. Recommended next wave: PRD §17 views 8/9 (Model Performance, Data Quality — both backend-then-renderer work) or the FR-10 inject mechanism, which the audit and the notebook both flag. |

---

## Standing constraints (full text in `docs/TASK6_DIRECTIVE.md` §4)

1. Tasks #1–#5 are frozen — no physics, ML, optimization or threshold changes.
2. Invent no engineering limit; ranges/steps/targets come from existing configuration.
3. Fixes belong in the Task #6 layer (`src/digital_twin/`, `src/visualization/`), never `src/models/`.
4. **A guard must state an absence, never substitute a number.**
5. Honesty is non-negotiable: no claimed plant connectivity, no automatic control, no validated
   savings, no fabricated confidence percentage, no silently dropped refusal.
6. Never loosen a safety constraint to make a demo look better.
7. Do not split `synthetic.py`; do not "fix" the package-level import cycle.

---

## Known contract gaps raised by Wave 3A (documented, not acted on)

1. **`ProviderCapabilities.missing` is dead and inconsistent** — two vocabularies (`real_plant.py`
   emits data-kind names, `synthetic.py`/the stub emit flag names) and zero production consumers.
   It reads like a gate and is not one. Do not gate new code on it without fixing it first.
2. **Seven required provider surfaces have no capability flag** — `get_current_state`,
   `get_equipment_status`, `get_kpis`, `get_operating_regime`, `get_sensor_values`, `get_timeseries`,
   `get_tag_metadata`. Consequently `state.py:frame()` cannot be capability-gated, and
   `DashboardState.frame()/views()/view()` correctly still raise for `RealPlantDataProvider`.
   Changing that needs a directive-level decision, not a patch.
3. **`RealPlantDataProvider` refuses with bare `NotImplementedError`**, not `CapabilityError` — so
   callers cannot distinguish "cannot supply" from a coding error. `CapabilityError` subclasses
   `NotImplementedError`, so switching would still satisfy PRD 26.1's wording.

---

## Process rules that kept previous waves from failing

- One narrowly scoped objective per wave; stop at its edge.
- Reproduce before patching.
- Run the full regression **once**, at the end.
- Files over ~100 lines: write in 2–3 sequential calls, never one giant call.
- Do not paste full file contents or diffs into chat — point to file/line.
- No background or parallel subagents.
- Verify the frozen-layer digests before **and** after.
- Update this file at the end of every wave.
