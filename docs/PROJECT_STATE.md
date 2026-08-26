# PROJECT STATE — Task #6 handoff

**Purpose:** the file a new session reads first. One line per outstanding Task #6 item, plus the
current commit and test counts. Created at the end of Wave 3A (`docs/WAVE3A_REPORT.md`); last
updated at the end of Wave 3C (`docs/WAVE3C_REPORT.md`).

---

## Current position

| | |
|---|---|
| **Branch** | `task6/wave-3c` — pushed, **not merged**. Awaiting human review. |
| **HEAD after Wave 3C** | the Wave 3C commit, whose parent is `8cbda49` (`git log --oneline -2`). Not pinned here: a commit cannot contain its own hash. |
| **Wave history** | `1f8107f` baseline → `0ed5e39` directive persisted → `3fa2e7d` Wave 1 → `e4dee7a` Wave 2 → `440602e` Wave 3A → `8cbda49` Wave 3B → Wave 3C |
| **Full regression** | **537 passed, 0 xfailed** (~4m28s). Baseline before Wave 3C was 526 passed; +11 new reproducibility tests. |
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
`test_task6_reproducibility.py` *(new, Wave 3C)*

---

## Outstanding Task #6 items

| Item | State | One line |
|---|---|---|
| **Item 15 requirement text** | **UNRECOVERED** | Directive D-1. Subject area located (Model C / optimization display) but the requirement itself is unknown. Recover from transcript or ask the user. **Task #6 cannot be reported complete while this stands.** |
| **B-7 badge (2 sites)** | **CLOSED** (Wave 3B) | Both sites derive the badge from `capabilities().synthetic` via `labels.presentation_card_label()`: `DashboardState._header` reads it inline, and `svg_twin` threads an explicit `synthetic: bool` through `twin_document`/`twin_html`/`render_twin`/`_header_html`. Both strict xfails removed. |
| **`app.py:123` badge derivation** | Open (new) | Follow-up from Wave 3B. `build_document` calls `render_twin` without `synthetic=`, so production takes the `True` default instead of deriving it. Truthful today (synthetic provider) but not derived. One-line fix — but it widens `build_document`'s documented `view(view_id)`-only contract, so it needs the next wave that owns `app.py`. |
| **BUG 2** | **CLOSED** (Wave 3C) | Views I/J were non-reproducible only in `runtime_s` — view J carried it at two depths (`view.runtime_s` *and* `view.payload.runtime_s`). Fixed by **excluding it from comparison**: a `signature()` method on `WhatIfView`/`OptimizationView` and both screen view models, reusing the frozen layer's own `OptimizationResult.NON_REPRODUCIBLE_FIELDS` convention. `synthetic.py` is byte-identical to `main` — zero production change. An AST guard (mutation-tested) fails if production ever hardcodes the duration. Views I/J are now golden-testable; **no golden file written yet.** |
| **Twin missing-data symmetry** | Open | Not started. |
| **`TestNfr2Budget`** | Not written | NFR-2 (< 3 s what-if round trip) is the real budget; `configs/dashboard.yaml` `refresh_seconds: 2.0` is **not** a PRD budget (directive D-10). |
| **`DATA_DICTIONARY.md`** | Missing | PRD §35 document. |
| **`DEMO_GUIDE.md`** | Missing | PRD §35 document. |
| **Item 17 Factory Presentation Mode** | Missing | Two config keys exist, no renderer. Flagged in the directive as "a critical requirement". |
| **Item 19 "Run Demo" sequence** | Missing | Step count (11) is E3/unverified — do not implement a count as a requirement. |
| **Item 22 enforcement scans** | Partial | Provenance-separation + determinism are E1-attested and now partly covered; the no-hard-coded-number and no-confidence-% scans do not exist. |
| **Items 2–13 renderers** | Payload only | 8 of 10 views have no renderer; only the SVG twin does. Payloads are built and correct — **preserve, do not rewrite.** |

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
