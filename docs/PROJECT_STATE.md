# PROJECT STATE — Task #6 handoff

**Purpose:** the file a new session reads first. One line per outstanding Task #6 item, plus the
current commit and test counts. Created at the end of Wave 3A (`docs/WAVE3A_REPORT.md`); last
substantive wave was **Wave View G** (`docs/VIEWG_IMPLEMENTATION_REPORT.md`, 2026-09-02) — the
first renderer for the Energy Monitoring screen, covering directive items 9 (kiln/mill groups)
and 12 (specific + total energy, VERBATIM).

---

## Current position

| | |
|---|---|
| **Branch** | `main` — the Wave View G commit is the tip; earlier waves 3C/3D were merged via `main` (see `git log`). |
| **HEAD after Wave View G** | the Wave View G commit, whose parent is the Wave View A closeout commit (`6dfb67b`). Not pinned here: a commit cannot contain its own hash. |
| **Wave history** | `1f8107f` baseline → `0ed5e39` directive persisted → `3fa2e7d` Wave 1 → `e4dee7a` Wave 2 → `440602e` Wave 3A → `8cbda49` Wave 3B → `557b935` Wave 3C → `b2915e3` Wave 3C merge → Wave 3D (`6b27858` merge) → `a056bf9` item 15 reconstruction → Wave View J (`cac1296`) → Wave View J closeout (`89a93ff`) → Wave View J horizon (`963f6d2`) → View H audit (`52ac068`) → Wave View H (`4a70160`) → View H closeout (`cc86f54`) → Wave View A (`8f61802`) → View A closeout pin (`6dfb67b`) → **Wave View G** |
| **Full regression** | **631 passed, 0 xfailed** (was 612; the View G wave added 19 tests in the new `test_task6_energy_view.py`, changed none). |
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
`test_task6_energy_view.py` *(Wave View G)*

Plus the stored fixtures the suite owns: `tests/golden/view_j_normal.html` *(Wave View J
closeout)*, `tests/golden/view_h_normal.html` *(Wave View H)*, `tests/golden/view_a_normal.html`
*(Wave View A)* and `tests/golden/view_g_normal.html` *(Wave View G)* — regenerate any of them
only after a deliberate renderer change, with the command recorded beside `GOLDEN_PATH` in the
owning test module.

---

## Outstanding Task #6 items

| Item | State | One line |
|---|---|---|
| **Item 15 requirement text** | **DISPLAY NOW EXISTS** (Wave View J) — reconstruction itself unchanged | Directive D-1. The verbatim text is still unrecovered; the labelled Tier E2 reconstruction stands. Its implied display is **now built**: view J's renderer shows the full PRD §14.5 five-row comparison (item 15's Step 0 display-form decision is recorded in `TASK6_DIRECTIVE.md` §1 item 15 — a table, on view J, not the Time-Series Explorer). Accessor: `OptimizationView.baselines()`. Recovering the verbatim item would still supersede the reconstruction. |
| **Items 14 / 15 / 16 / 10 — view J renderer** | **DONE** (Wave View J + closeout + horizon) | `src/visualization/optimization_view.py` renders all four: the recommendation card from `Recommendation.describe()` unchanged (14), the §14.5 five-row table with unavailable rows showing their own reason (15), refusals as a display state with the gates' own words (16), and the item-10 multi-horizon predicted-state grid (10) — one row per target, one column per configured horizon (5/10/15/30 from `configs/ml.yaml`), value with its `±` ensemble spread, never a confidence percentage, in the PREDICTION channel and kept separate from the observed baselines. `app.py` routes view J via one additive duck-typed `elif`. Accessors: `recommendation()`, `baselines()`, `predicted_states()`. 28 tests; see `WAVE_VIEWJ_REPORT.md` and `WAVE_VIEWJ_HORIZON_REPORT.md`. **PRD §17 view 4's three-state comparison (current / multi-horizon / recommended) is now complete on one screen.** |
| **B-7 badge (2 sites)** | **CLOSED** (Wave 3B) | Both sites derive the badge from `capabilities().synthetic` via `labels.presentation_card_label()`: `DashboardState._header` reads it inline, and `svg_twin` threads an explicit `synthetic: bool` through `twin_document`/`twin_html`/`render_twin`/`_header_html`. Both strict xfails removed. |
| **`app.py:123` badge derivation** | **CLOSED** (Wave View J closeout) | `build_document` now passes `synthetic=_source_is_synthetic(state)` to `render_twin` — the same `capabilities().synthetic` derivation `state._header` uses (Wave 3B's pattern). Duck-typed, so a bare `view(view_id)` stub keeps the `True` default and no caller breaks. Mutation-tested regression test in `test_task6_app_smoke.py`; see `WAVE_VIEWJ_CLOSEOUT_REPORT.md` §2. |
| **BUG 2** | **CLOSED** (Wave 3C) | Views I/J were non-reproducible only in `runtime_s` — view J carried it at two depths (`view.runtime_s` *and* `view.payload.runtime_s`). Fixed by **excluding it from comparison**: a `signature()` method on `WhatIfView`/`OptimizationView` and both screen view models, reusing the frozen layer's own `OptimizationResult.NON_REPRODUCIBLE_FIELDS` convention. `synthetic.py` is byte-identical to `main` — zero production change. An AST guard (mutation-tested) fails if production ever hardcodes the duration. Views I/J are now golden-testable; **no golden file written yet.** |
| **Twin missing-data symmetry** | Open | Not started. |
| **`TestNfr2Budget`** | Not written | NFR-2 (< 3 s what-if round trip) is the real budget; `configs/dashboard.yaml` `refresh_seconds: 2.0` is **not** a PRD budget (directive D-10). |
| **`DATA_DICTIONARY.md`** | **DONE** (Wave 3D) | PRD §35 document. All 62 rows derived from `TagSpec` in `src/schema.py` and verified programmatically against it (0 content mismatches, 0 range mismatches). Canonical MJ conversion per PRD §9.2; every `ASSUMPTION` value cross-checked against `configs/` and `SIMULATION_ASSUMPTIONS.md`. |
| **`DEMO_GUIDE.md`** | **DONE** (Wave 3D) | PRD §35 document. Demos 1–5 + Presentation Mode, grounded in what `app.py` does today. §9 lists 10 PRD demo capabilities not built. Three claims were corrected by measurement — see `WAVE3D_REPORT.md` §2.1. |
| **Item 17 Factory Presentation Mode** | Missing | Two config keys exist, no renderer. Flagged in the directive as "a critical requirement". Its true extent is now tabulated in `DEMO_GUIDE.md` §7 (config keys + `PresentationSettings` + `presentation_card_label()`; no view id, renderer, KPI cards, five-stage chain or refresh loop). |
| **`app.py` docstring timing** | Open (new, Wave 3D) | The module docstring advertises `--skip-models` at "~0.4 s"; measured **4.5 s** across two runs. A ten-view build with models on measured 21.0 s reported / 25.7 s wall. Not fixed — Wave 3D changed no production file. Needs the next wave that owns `app.py`. |
| **Experimental What-if Mode unreachable** | Open (new, Wave 3D) | Fully implemented and tested in the view layer, but no caller can select it: `DashboardState.view()` passes only `frame`, so `mode` keeps its `"NORMAL"` default, and `app.py` has no `--mode` flag (nor `--change`). `DEMO_GUIDE.md` §6.2 documents the Python-only workaround. |
| **Item 19 "Run Demo" sequence** | Missing | Step count (11) is E3/unverified — do not implement a count as a requirement. |
| **Item 22 enforcement scans** | Partial | Provenance-separation + determinism are E1-attested and now partly covered; the no-hard-coded-number and no-confidence-% scans do not exist. (The item-10 grid now *renders* the spread-not-% rule, pinned by tests — but that is not the directive's automated scan.) |
| **Items 10 / 11 — view H renderer** | **DONE** (Wave View H) | `src/visualization/intelligence_view.py` renders both payloads of `DashboardState.intelligence()`: Model A's own forecast grid from `PredictionSet` (item 10 — the current row's horizons, **not** view J's recommendation-scoped `predicted_state_by_horizon`) with every configured horizon a column, OBSERVED `Current` and PREDICTION horizons badged as two channels, `±` ensemble spread never a confidence %, and missing (target, horizon) pairs as stated absences with the payload's own account; and Model B's verdict from `AnomalyState` in the PRD §15 contract lines (item 11) — WARNING card, "Evidence inconclusive" verbatim where the evidence cannot separate fault from process (the `from_report` branch, previously untested, now pinned), nearest regime shown only as a similarity match, NORMAL rows as "No anomaly detected." `app.py` routes view H via one additive duck-typed `elif`. 22 tests + `tests/golden/view_h_normal.html`; see `VIEWH_IMPLEMENTATION_REPORT.md`. Remaining view-H gaps (trends/prediction-fan chart, inject control, evidence fields) are listed in that report §10. |
| **Items 3 / 9 / 12 + PRD 18.1 — view A renderer** | **DONE** (Wave View A) | `src/visualization/overview_view.py` renders `DashboardState.overview()`: the item-3 five-stage chain (state word, rate, PRD 8.3 equipment — a grouping of the twin, nothing animates), the items-9/12 plant KPI group whole (specific energy + daily totals, the group's own note), and PRD 18.1's two AI tiles — compact `OverviewStatus` summaries **reused** from the view J / view H payloads (`optimization(frame).view` and `_anomaly("kiln", stamp)`, no second computation), with unavailable models stated with their own reason and refusals as display states. `app.py` routes view A via one additive duck-typed `elif` (`_is_overview`: `stages` + `plant`). 23 tests + `tests/golden/view_a_normal.html`; see `VIEWA_IMPLEMENTATION_REPORT.md`. Known gap: PRD 18.1 trend sparklines (no trend channels in the payload — same class of skip as view H's). The perf contract in `test_task6_performance.py` was restated with dated notes (view A reads `get_anomaly_state` + `get_optimization`); the open option — sharing one model read across screens — needs a directive-level decision. |
| **Item 12 — view G renderer** | **DONE** (Wave View G) | `src/visualization/energy_view.py` renders `DashboardState.energy()`: the item-12 pair section — the specific-energy figures, the daily totals they imply and the production rates between them, all three partitions of the one plant KPI group on one screen with the payload's own `SPECIFIC_VS_TOTAL_NOTE` verbatim, so the favorable half can never stand alone (an empty total partition is *stated* beside the specific figures, never hidden) — plus the kiln and cement-mill KPI groups (item 9). `app.py` routes view G via one additive duck-typed `elif` (`_is_energy`: `specific` + `total`). Audit verdict A (`docs/VIEWG_AUDIT.md`); 19 tests + `tests/golden/view_g_normal.html`; see `VIEWG_IMPLEMENTATION_REPORT.md`. Known gap: the payload's trend channels are not rendered (the deferred chart decision, same class as view H's G-6 skip). |
| **Items 2–13 renderers** | Payload only | 4 of 10 views have no renderer (C, D, F, I); the SVG twin (B/E), view J, view H, view A and view G do. Payloads are built and correct — **preserve, do not rewrite.** |
| **View J golden file** | **DONE — regenerated** (Wave View J closeout; regenerated in the horizon wave) | `tests/golden/view_j_normal.html` — the renderer's whole output for the fixed stub payload, compared byte-for-byte (newline-normalised) by 2 tests in `test_task6_optimization_view.py`. The horizon wave changed the renderer by design and regenerated the fixture with the recorded command (never hand-edited). View I has no renderer yet, so no golden for it. |

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
