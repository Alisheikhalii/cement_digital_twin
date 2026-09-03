# VIEW I — WHAT-IF SIMULATION: AUDIT AND IMPLEMENTATION REPORT

**Date:** 2026-09-03
**Wave:** View I — the What-If Simulation screen (PRD §17 view 5, directive item 13)
**This file is the single report for the whole wave:** audit, verdict, implementation, tests,
digests and git state, per the wave brief.

---

## 1. Current Git / commit verification

Run at wave start (2026-09-03):

```
$ git log --oneline -5
6ee2d56 feat(task6): Wave View G - first renderer for the Energy Monitoring screen
6dfb67b docs(task6): pin Wave View A commit hash in the closeout report
8f61802 feat(task6): Wave View A - first renderer for the Plant Overview screen
cc86f54 docs(task6): View H closeout — G-10 settled, full A-J renderer inventory
4a70160 feat(task6): Wave View H — first renderer for the AI Prediction & Anomaly screen

$ git status        # clean
$ git fetch origin && git status -sb
## main...origin/main     # in sync; HEAD is the View G closeout commit 6ee2d56
```

HEAD at start was `6ee2d56` — the View G wave, as the brief expected. **No View I
implementation existed**; view I rendered through `_payload_html` (the JSON fallback) and no
`--mode`/`--change` CLI surface existed. Verified at source, not assumed.

**Frozen-layer digests, before and after (unchanged — see §11):**

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0   (expected — unchanged)

git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd   (expected — unchanged)
```

---

## 2. PRD requirement checklist (verified, not invented)

Only requirements actually present in the PRD / directive, with their source:

| # | Requirement | Source |
|---|---|---|
| R1 | Sliders for the six PRD 16.1 manipulated variables (`kiln_fuel_rate_tph`, `ID_fan_speed`, `kiln_feed_rate_tph`, `kiln_speed_rpm`, `separator_speed_rpm`, `mill_feed_rate_tph`), using the **configured** bounds and step sizes — invent no ranges | PRD §16.1; directive item 13 (E1) |
| R2 | Normal What-if Mode (default): ±10 % of current value, every scenario through §14.3 envelope/OOD validation; out-of-range requests rejected with an explanation | PRD §16.1 |
| R3 | Experimental What-if Mode (explicit user toggle): beyond ±10 %/outside envelope; **every** result carries the fixed banner "Outside calibrated operating envelope — low reliability." and is visually distinguished | PRD §16.1 |
| R4 | Verdict is one of exactly three outcomes (display forms of engine states, not a second judgement) | Directive item 13 (E1, VERBATIM strings, `labels.py:110-112`) |
| R5 | Render: temperature, O2, production, energy consumption, quality indicator, constraint violations, estimated savings | PRD §16.2 render line |
| R6 | Before/after table (baseline vs scenario) | PRD §16.3 |
| R7 | Time-series chart of the transition **that visibly shows the delay** | PRD §16.2 / §16.3 / §17 view 5 |
| R8 | Constraint-status banner (PASS/REJECTED/FLAGGED per constraint and per envelope check) | PRD §16.3 |
| R9 | Estimated savings/cost line, from the same `Recommendation`-shaped object as §14.4 | PRD §16.3 |
| R10 | Normal/Experimental mode toggle on the view | PRD §17 view 5 |
| R11 | AC-4: what-if produces a visibly different, physically sensible outcome within NFR-2's 3 s | PRD §33 AC-4 |
| R12 | Honesty: no fabricated confidence %, no plant-connection implication, refusals visible | directive item 20; PRD §30 |

Explicitly **not** requirements (checked, not assumed): a specific chart library (PRD §17.1
delegates rendering; §19.3 fixes only the *twin* to SVG); an interactive drag surface in the
HTML export (the export is a static self-contained file by design — `app.py`'s whole contract);
"Run Demo" sequencing (item 19, separate).

---

## 3. What-if engine trace (read-only, before any change)

1. **Engine:** `src/optimization/what_if.py` (frozen layer, tested by
   `tests/test_optimization.py`). `WhatIfEngine.run()` follows PRD 16.2 step for step: request
   geometry (snap to configured step, clip to mode bound for slider-shaped callers),
   `Optimizer.assess_setpoints` (the *same* chain the optimizer's own winner travels — the
   PRD 16.2 consistency guarantee is structural), then a second, independent trajectory
   computation (`_simulate` via `Twin.simulate_scenario` through the real `DelayedResponse`
   delays), with `endpoint_agreement` measuring the disagreement between the two routes.
2. **Input:** `changes` (absolute targets) or `delta_fractions` (signed fractions), one mode
   string. A rejected request is an answer, not an error — it returns a full
   `WhatIfResult` whose `constraint_status` may be `REJECTED`, and it is never simulated
   (no trajectory to mistake for a prediction).
3. **Output:** `WhatIfResult.panel()` — the PRD 16.3 contract under ten keyed elements:
   `mode`, `action`, `requested_change` (baseline/requested/value/bounds/step/clipped/snapped/
   note per variable), `baseline_state`, `observed_state`, `predicted_process_response`
   (settled state, by-horizon, transition summary, endpoint agreement),
   `before_after` (the §14.5 metric set), `energy_impact` (thermal/electrical per day,
   savings line, caveat), `production_impact`, `quality_impact`, `uncertainty`,
   `constraint_status` + `constraint_rows`, `envelope_status`/`ood_status` +
   `envelope_rows`, `recommendation_status` (accepted/simulated/blocked_by/quality),
   `banner`, `notes`.
4. **Provider surface:** `SyntheticDataProvider.run_what_if` (`synthetic.py:1363`) wraps the
   engine with `clip_to_bounds=True` (every caller is slider-shaped), measures `runtime_s`
   outside the engine, and returns `WhatIfView.unavailable(...)` with its own reason when the
   model layer is absent or no operating point exists. `what_if_sliders` (`synthetic.py:1405`)
   returns one slider spec per manipulated variable from the engine's own `DecisionSpace`.
5. **View layer:** `insights.WhatIfView` (`insights.py:361`) — `from_result` reads the verdict
   from the panel's own `recommendation_status` (never recomputes), carries the panel
   unchanged, and has a `signature()` that strips `runtime_s` (BUG 2 fix, Wave 3C).
6. **State layer:** `DashboardState.what_if(changes, delta_fractions, mode)`
   (`state.py:957`) — accepts everything, capability-gated, unavailable states carried.
   `WhatIfViewModel` (`state.py:485`) = header + mode + `view` + `sliders`, with
   `signature()` for golden testing.

**Payload-vs-requirement coverage (R1–R12):** every requirement except R7's *picture* is
already in the payload. The transition *data* (rows/minutes/hold/ramps/endpoint agreement) is
there; only no renderer drew it.

---

## 4. Reachability / routing analysis (the "unreachable" question)

- `DashboardState.view("I")` (`state.py:1009`) dispatches `what_if(frame=frame)` — **no
  changes, no mode**: the engine runs a null change set in Normal Mode. So view I was
  *reachable* in the weak sense (the §6.3 CLI fallback), but **no caller could select
  Experimental Mode or set a change** — the state recorded in `PROJECT_STATE.md` as
  "Experimental What-if Mode unreachable" (Wave 3D finding) and in `DEMO_GUIDE.md` §9 rows
  5–6.
- `app.py` had `_is_twin` / `_is_intelligence` / `_is_optimization` / `_is_overview` /
  `_is_energy` — no `_is_whatif`; view I fell to `_payload_html`.
- **Conclusion:** the engine is complete and tested; the payload is complete; the missing
  pieces are (a) a renderer and (b) a minimal application surface to pass a mode and a change
  set. Both are presentation-layer.

---

## 5. Gap matrix

| Requirement | PRD source | Existing implementation | Payload available | Renderer needed | Routing needed | Status |
|---|---|---|---|---|---|---|
| R1 sliders, configured bounds/steps | 16.1 / item 13 | `WhatIfEngine.slider` + `what_if_sliders` | yes (`sliders`) | yes | no | **RENDERER ONLY** |
| R2 Normal mode ±10 % + envelope validation | 16.1 | engine, frozen, tested | yes | — | — | **COMPLETE (backend)** |
| R3 Experimental mode + fixed banner | 16.1 | engine + `_decision_notices` | yes (`banner`, header notices) | yes (banner card) | yes (mode selection) | **ROUTING + RENDERER** |
| R4 three verdicts | item 13 VERBATIM | `WhatIfView.from_result` | yes (`verdict`) | yes | no | **RENDERER ONLY** |
| R5 render response figures | 16.2 | `panel` keys | yes | yes | no | **RENDERER ONLY** |
| R6 before/after table | 16.3 | `panel["before_after"]` | yes | yes | no | **RENDERER ONLY** |
| R7 transition chart with visible delay | 16.2/16.3 | `Transition` + `charts.transition` builder (`charts.py:347`, unconsumed) | data yes; chart builder exists but needs Plotly | chart only | no | **OPTIONAL / DEFERRED** (see §9) |
| R8 per-constraint / per-check banner | 16.3 | `constraint_rows` / `envelope_rows` | yes | yes | no | **RENDERER ONLY** |
| R9 savings line | 16.3 | `savings_line()` with caveat | yes | yes | no | **RENDERER ONLY** |
| R10 mode toggle | 17 view 5 | engine + state layer | n/a | n/a | yes (CLI) | **ROUTING ONLY** |
| R11 < 3 s round trip | AC-4 / NFR-2 | engine; measured in `run_what_if` | n/a | n/a | no | **COMPLETE (backend)**; `TestNfr2Budget` still not written (pre-existing open item) |
| R12 honesty rules | item 20 | labels centralised | yes | yes | no | **RENDERER ONLY** |

## 6. The distinction the brief asked for, answered explicitly

- **A. Is the engine complete enough for view I?** Yes — frozen, tested (`tests/test_optimization.py`,
  16 what-if-focused tests re-run this wave: 16 passed), PRD 16.2/16.3 conforming.
- **B. Is the view-I payload already available?** Yes — `DashboardState.what_if()` builds the
  full `WhatIfViewModel` including sliders, and it is reproducible (`signature()`, tested).
- **C. Is the only missing piece routing/mode selection?** No — two pieces: routing (mode +
  change selection) **and** a renderer. Both presentation-layer.
- **D. Does view I require new backend/model computation?** No.
- **E. The transition chart?** The PRD requires it (R7), but the *data* half is satisfied and
  the `ChartSpec` builder exists; drawing it needs the Plotly-optional degradation decision
  this project has deferred three times (view H G-6, view G trends, view A sparklines).
  Deferred with documentation, not silently dropped — see §9.

## 7. Verdict: **A — READY TO IMPLEMENT** (renderer) + small routing prerequisite

The routing prerequisite is presentation-layer only (no backend work), i.e. the "small B"
case the brief allows to be implemented in the same wave. Implemented in this session; see §8.

---

## 8. Implementation

### 8.1 Files changed

| File | Change |
|---|---|
| `src/visualization/what_if_view.py` | **new** — the view I renderer (plain HTML, no framework, no chart dependency) |
| `app.py` | additive routing: `what_if_view` import, `_is_whatif` duck type, one `elif` in `build_document`; CLI: `--mode`, `--change NAME=PERCENT` (repeatable), the `_WhatIfRequest` wrapper, `_parse_changes`, parse-time validation against `schema.manipulated_variables()`; docstring/epilog examples |
| `tests/test_task6_what_if_view.py` | **new** — 31 tests (§8.4) |
| `tests/golden/view_i_normal.html` | **new** — golden fixture, generated by the command recorded beside `GOLDEN_PATH` |
| `docs/VIEWI_AUDIT_AND_IMPLEMENTATION_REPORT.md` | this file |
| `docs/PROJECT_STATE.md` | wave row + status updates (facts established this wave only) |

No frozen-layer file, no view B/E/H/J/A/G behavior, no engine internals touched.

### 8.2 Renderer behavior (`render_what_if`)

Reads the frozen view model only; computes nothing; every string through `theme.html`; every
number through `theme.format_number` at `FormatSettings` precision — **except slider steps**,
which render as the payload's own text (`_spec_text`): item 13's "exact configured step
sizes" is contractual, and a step of `0.0312` would lose its fourth digit to
`max_decimals: 3`. Sections, each with a `data-role` anchor:

- **status strip** — provenance badge, mode pill, verdict pill (PASS=ok / REJECTED=alarm /
  NO-SAFE-RECOMMENDATION=warn; a refusal is a display state, item 16's rule carried to view I);
- **banner** — the payload's own `banner` (the fixed PRD 16.1 Experimental wording) in the
  warn style, visually distinct from Normal-Mode results; never awarded by the renderer;
- **sliders** (item 13) — one card per payload slider: current, mode bounds (the engine's
  `minimum`/`maximum`, falling back to the stub shape's `min`/`max`, then `absolute_range`),
  step (payload text), max Δ fraction. Empty sliders ⇒ stated absence (a slider whose bounds
  nothing owns would be a made-up limit, item 5);
- **requested change** — the action line and one row per variable: baseline / requested /
  simulated / Δ % / mode bounds / step / flags (clipped·snapped·moved), plus every engine
  note verbatim — a trimmed request is shown as trimmed (PRD 30: never hide a clip);
- **predicted response** — the before/after table (§14.5 metric set), the settled state, the
  transition summary as text (window/rows/dt/hold/ramps — the delay as numbers, §9 explains
  the missing picture), the endpoint-agreement figure *with the engine's own
  too-short-window warning when unconverged*, the savings line and its caveat;
  `transition: None` ⇒ stated "rejected before any simulation ran, so there is no transition
  to show" — a rejected request is never simulated, so no trajectory is invented;
- **constraints & envelope checks** — per-constraint rows (state/value/limit/detail) and
  per-check rows in the validator's own words; aggregate statuses as pills; empty ⇒ stated,
  never shown as if every constraint had passed;
- **unavailable** — the payload's own `unavailable_reason` (never a substitute panel), with
  the sliders' stated absence beside it;
- standing footer: `NO_PLANT_CONNECTION_STATEMENT`.

### 8.3 Routing behavior (`app.py`)

- `_is_whatif(model)`: duck-typed on `sliders` **and** `view` — a combination no other view
  model carries (verified: A=stages/plant, B/E=line/snapshot, C/D/F=components/panels,
  G=specific/total, H=predictions/anomaly, J=view+quality_descriptions). One additive `elif`
  in `build_document`; all existing routes untouched (pinned by test).
- `--change NAME=PERCENT` (repeatable) and `--mode {NORMAL,EXPERIMENTAL}`: view-I-only flags.
  `_parse_changes` converts percent to the engine's `delta_fractions` and validates names
  against `schema.manipulated_variables()` — the schema's list, not one restated in `app.py`.
  Naming the flags without requesting view I is an error (exit 2), never a silent no-op.
- `_WhatIfRequest`: a wrapper that serves `"I"`/`"what_if"` from
  `state.what_if(delta_fractions=..., mode=...)` and delegates every other view to the generic
  `view()` dispatch — the smallest surface that reaches the mode toggle **without changing any
  dispatch signature**. A bare `--view I` still goes through the generic dispatch (null
  change set, Normal Mode) exactly as before.
- `--skip-models` view I now renders the honest unavailable panel (verified by CLI smoke:
  "Model not available", "no slider specifications", mode badge still shown).

### 8.4 Tests added (31, all in `tests/test_task6_what_if_view.py`)

A sections/verdict/mode/action (4) · B sliders bounds+steps, absent sliders (2) · C
requested-change table + trimming shown + notes verbatim (1) · D before/after, transition
summary, rejected-no-trajectory, savings caveat, endpoint-agreement warning (5) · E constraint
rows + absent rows (2) · F experimental banner visually distinct (1) · G unavailable panel,
empty before/after, empty settled state (3) · H no-confidence/no-forbidden-label, escaping
(2) · I determinism (1) · J state builder over stub provider + absent capability (2) · K
routing: build_document route, duck-type non-collision, `_WhatIfRequest` delegation, parser
flags, `_parse_changes` valid/invalid, mode-or-change-without-view-I error (7) · the engine's
flat-float settled state renders (1 — see §8.6) · golden (1).

Covers the brief's A–J list: normal rendering (A), manipulated-change display (B), predicted
response (C), expected impact (D-savings line), missing/unavailable simulation (E),
invalid/rejected change (rejected-no-trajectory test), constraint rows (G), no fabricated
values (H), determinism (I), routing/reachability (J).

### 8.5 Test results

- **Focused, before implementation:** `tests/test_optimization.py -k "WhatIf or what_if"` →
  **16 passed** (the frozen engine's own tests; 74 deselected).
- **Focused, after implementation:** `tests/test_task6_what_if_view.py` → **31 passed**;
  `tests/test_task6_app_smoke.py` + `tests/test_task6_provider_contract.py` → **38 passed**;
  `tests/test_task6_reproducibility.py` → **11 passed**.
- **CLI smoke (real app, not a test stub):** `--skip-models` degraded path and a full
  model-layer run with `--change kiln_fuel_rate_tph=-5 --seed 20240101` — both exited 0 and
  wrote self-contained exports; the real run renders the engine's actual panel (verdict
  PASS / WITHIN ENVELOPE, before/after rows, settled state, transition summary, constraint
  rows), and the view-I stage of that run measured **2.6 s** — inside NFR-2's 3 s budget
  (R11's runtime half; see the open item in §10).
- **Full regression:** run exactly once at the end — see §11.

### 8.6 What the real-payload run caught (and the focused tests could not)

The first real model-layer run exposed a shape mismatch the stub had encoded wrongly:
`proposed_state` — the panel's `settled_state` — is `Mapping[str, float]` (tag → plain
number), while the test stub had assumed `{value, unit}` mappings. The renderer's shape
check dropped every real entry, so a full settled state rendered as "unavailable" — the
exact "silently hide a required section" failure the brief forbids. Fixed by making
`_settled_table` accept both shapes (a flat entry's unit cell stays blank — the payload
states no unit, and none is guessed); the stub was corrected to the engine's real shape and
a regression test (`test_the_engines_flat_float_settled_state_renders`) now pins it. The
golden fixture was regenerated via the command recorded beside `GOLDEN_PATH` — a deliberate
renderer change, per the fixture's own convention. This is why §8.5 runs the real app as
smoke, not only the test stubs: the stubs prove honesty against what the tests *think* the
payload looks like; only a real run proves it against what the engine actually sends.

---

## 9. Remaining View I gaps (open, documented — not silently dropped)

1. **The transition chart (R7).** PRD §16.2/§16.3 requires a time-series chart of the
   transition that visibly shows the delay. The payload half is complete (window, rows, dt,
   hold, per-variable ramp minutes, endpoint agreement) and an unconsumed `ChartSpec` builder
   exists (`charts.py:347`, `transition`), but no Task-6 renderer draws charts — that is the
   project-wide deferred Plotly-optional decision (same class as view H's G-6 skip, view G's
   trend channels, view A's sparklines). This wave renders the transition as text so the delay
   information is carried as numbers; a rejected request states that no trajectory exists.
   Drawing the picture needs the chart-library decision first, and belongs to a wave that owns
   it — not smuggled into this one.
2. **`by_horizon` not rendered.** The panel carries `predicted_state_by_horizon`; PRD §16
   asks view I for the settled response and the transition, not a horizon grid, and view J
   already renders horizon grids from its own payload. Not rendered rather than duplicated.
3. **NFR-2 test still unwritten.** The real run measured view I at 2.6 s (< 3 s budget), but
   `TestNfr2Budget` remains a pre-existing open item (see `PROJECT_STATE.md`).
4. **`DEMO_GUIDE.md` §6.2/§6.3** still documents the old Python-only workaround and "no
   `--mode`/`--change` flags" state — now stale. Docs backlog; this wave records the change
   here and in `PROJECT_STATE.md` rather than silently editing the guide.
5. **A graphical slider surface** (drag controls in the browser) is not and cannot be the
   export's shape — `app.py`'s contract is a static self-contained HTML file. The CLI surface
   is the mode/variable selection mechanism, per PRD §17.1's delegation.

## 10. Frozen-layer digest verification (after the wave)

```
$ git ls-files -s src/models src/process_models src/optimization src/simulation \
    src/features src/data_generation configs pyproject.toml | md5sum
c7a1f54dd578900835596c02cb9a19a0      # expected — UNCHANGED

$ git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
53f2aefec33494be5ca22c08ab22b5fd      # expected — UNCHANGED
```

No frozen file was touched; the wave's only production edits are `src/visualization/what_if_view.py`
(new), `app.py` (routing + CLI), `src/digital_twin/insights.py` and `src/digital_twin/state.py`
were **not** modified (the payload/accessors already existed and were reused unchanged).

## 11. Full regression and final git state

- **Full regression, run exactly once at wave end:** `python -m pytest` →
  **662 passed, 0 xfailed** (was 631; this wave added the 31 tests of
  `tests/test_task6_what_if_view.py` and changed no existing test). No test was weakened,
  deleted or skipped.
- **Git:** one commit for the wave; `git diff --stat`, `git status`, `git diff --check` run
  before it; pushed to `origin/main` and re-verified (`git fetch origin` + `git status` +
  `git log --oneline -3`). The commit hash and the post-push verification are recorded in
  `PROJECT_STATE.md` (a report committed in its own wave cannot contain its own hash).
