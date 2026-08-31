# PROJECT STATE — Task #6 handoff

**Purpose:** the file a new session reads first. One line per outstanding Task #6 item, plus the
current commit and test counts. Created at the end of Wave 3A (`docs/WAVE3A_REPORT.md`); last
substantive wave was **Wave View J horizon** (`docs/WAVE_VIEWJ_HORIZON_REPORT.md`, 2026-08-31) —
the item-10 multi-horizon predicted-state grid on view J, completing PRD §17 view 4's
three-state comparison.

---

## Current position

| | |
|---|---|
| **Branch** | `main` — the Wave View J horizon commit is the tip; earlier waves 3C/3D were merged via `main` (see `git log`). |
| **HEAD after Wave View J horizon** | the Wave View J horizon commit, whose parent is the Wave View J closeout commit (`89a93ff`). Not pinned here: a commit cannot contain its own hash. |
| **Wave history** | `1f8107f` baseline → `0ed5e39` directive persisted → `3fa2e7d` Wave 1 → `e4dee7a` Wave 2 → `440602e` Wave 3A → `8cbda49` Wave 3B → `557b935` Wave 3C → `b2915e3` Wave 3C merge → Wave 3D (`6b27858` merge) → `a056bf9` item 15 reconstruction → Wave View J (`cac1296`) → Wave View J closeout (`89a93ff`) → **Wave View J horizon** |
| **Full regression** | **567 passed, 0 xfailed** (was 557; the horizon wave added 10 tests to `test_task6_optimization_view.py`, changed none). |
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
git ls-files -s tests/ | grep -v task6 | md5sum
# expected: 53f2aefec33494be5ca22c08ab22b5fd
```

### Task #6 test modules (not frozen — these are the ones waves may extend)

`test_task6_provider_contract.py` · `test_task6_app_smoke.py` · `test_task6_frame_nan.py` ·
`test_task6_performance.py` · `test_task6_twin.py` · `test_task6_real_plant_state.py` *(Wave 3A)* ·
`test_task6_reproducibility.py` *(Wave 3C)* · `test_task6_optimization_view.py` *(Wave View J)*

Plus the one stored fixture the suite owns: `tests/golden/view_j_normal.html` *(Wave View J
closeout)* — regenerate it only after a deliberate renderer change, with the command recorded
beside `GOLDEN_PATH` in `test_task6_optimization_view.py`.

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
| **Items 2–13 renderers** | Payload only | 8 of 10 views have no renderer; the SVG twin and now view J do. Payloads are built and correct — **preserve, do not rewrite.** |
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
