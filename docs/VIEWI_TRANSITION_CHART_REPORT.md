# VIEW I TRANSITION CHART REPORT — Wave closeout

**Date:** 2026-09-04 (wave ran 2026-09-03/04)
**Starting HEAD:** `5795e5d` (Wave CDF — one shared renderer for the process detail screens)
**Scope:** close the View I transition chart gap (PRD §16.2/§16.3) + two documentation corrections
(`TestNfr2Budget` staleness in `PROJECT_STATE.md`, stale `DEMO_GUIDE.md` §5/§9) + record the PRD
verdict on `EquipmentStatus.constraints`.

---

## 1. Git verification

- `git log --oneline -8` at session start: HEAD = `5795e5d` (Wave CDF), parent `091cb4a`
  (Wave View I) — matches the expected starting point.
- `git fetch origin`; `git status`: branch `main`, in sync with `origin/main`, tree clean at start.
- Frozen-layer digests **before** the wave (both expected values, unchanged):
  - production digest `c7a1f54dd578900835596c02cb9a19a0`
  - tests digest (excluding task-6-owned paths) `53f2aefec33494be5ca22c08ab22b5fd`

## 2. PRD citation trail — the chart is required, not optional

Direct quotations from `docs/PRD_Synthetic_Cement_Digital_Twin.md`:

- **§16.2** (view-I flow, lines 677–679): "render … the full transition trajectory showing the
  actual dead-time + lag — **NOT an instantaneous jump**".
- **§16.3** (view-I output panel, line 684): "a time-series chart of the transition **that
  visibly shows the delay**".
- **§17 row 5** (line 698): "What-if simulation … shows the visible delay in the transition chart".
- **AC-15** (line 1072): acceptance rests on the transition being shown, delay visible.
- **§28 Demo 4** (line 1000): the demo walks the transition and its delay on view I.

Verdict: the chart is view I's own output-panel contract (§16.3), reinforced by §17 row 5 and
AC-15 — the same class of requirement as the before/after table, not a §18-style nicety. The
Wave View I audit had recorded it as "the deferred Plotly-optional decision"; that deferral was
wrong and is closed by this wave.

## 3. SVG vs Plotly — decision: self-contained inline SVG

- **PRD §19.3** (line 745) sets the rendering precedent: self-contained HTML/CSS/SVG, exportable
  with no runtime dependency (NFR-9). No existing Task-6 renderer (views B/E twin, J, H, A, G, I,
  C/D/F) uses a charting library.
- **Plotly is named only for the Time-Series Explorer** (§17 row 6) — a different view, not view I.
- The payload supports an exact commanded-path chart: `transition.describe()` carries window
  minutes, hold minutes, per-variable ramp minutes, plus each variable's baseline and settled
  value in the change table. What the payload does **not** carry is the plant's response time
  series between the endpoints — so a response curve is never drawn and never interpolated
  (guard rule: state the absence).
- Plotly would add a JS dependency that breaks the §19.3 self-contained convention and could not
  honestly fill the response path anyway. **Decision: inline SVG.**

## 4. Chart implementation (src/visualization/what_if_view.py)

`_transition_chart(transition, requested, fmt)` (~140 lines), wrapped in
`<div class="dt-wi__chartbox" data-role="whatif-transition">` inside the existing response
section:

- One polyline per **moved** variable (baseline != value, ramp known): flat at 0% through the
  hold, then the engine's own linear ramp arithmetic to 100% of that variable's commanded move;
  if the ramp is still running at window end, the line stops at the true partial position and
  the legend says "still ramping at window end".
- Hold guide line (only when 0 < hold < window), 0%/100% rails, x-axis ticks at 0, hold end
  ("X min · hold ends") and window end (anchored `end` so the label cannot overflow the 640-wide
  viewBox), `aria-label` on the SVG.
- Legend per variable: name · ramp minutes · complete/still-ramping · baseline → value with unit
  (true magnitudes, `theme.format_number`).
- **Honest-absence branches:** non-mapping transition or no numeric window → "no numeric
  transition window"; no moved variable → "No manipulated variable moved"; a moved variable
  without a ramp time is *named* in the note, never silently dropped.
- The chart's own note (payload-exact discipline): commanded paths are the engine's hold/ramp
  arithmetic; the plant's response path is not on the payload — only its endpoints and the
  endpoint agreement are — so no response curve is drawn.
- Geometry as user-space numbers; colors via `var(--dt-*)` only (the twin's rule). Engine and
  payload untouched; no new dependency.
- Real-payload smoke (CLI `--view I --change separator_speed_rpm=+5`, exit 0): the chart draws
  from the engine's actual output — 5 polylines, because the engine's own `moved` definition
  includes step-snap on nominally-unchanged variables (190.2 → 190.0), consistent with the
  requested-change table; view-I stage 2.257 s, inside NFR-2.

## 5. TestNfr2Budget finding + PROJECT_STATE.md correction

The `PROJECT_STATE.md` line "Not written" was **stale**. NFR-2 (< 3 s what-if round trip) is
covered at both layers, verified by `git log -S`:

- **Engine layer:** `class TestNfr2Budget` in `tests/test_optimization.py:1660` — present since
  the baseline commit `1f8107f` (pre-Task-6, frozen).
- **Dashboard layer:** `test_one_what_if_round_trip_is_inside_the_nfr_2_budget` in
  `tests/test_task6_performance.py:433` — added in Wave 2 (`e4dee7a`).

The item row now records both layers with file:line and provenance. No test was written this
wave — the truth was that the tests already exist.

## 6. DEMO_GUIDE.md correction (§5 + §9)

- **§5:** the two-limit warning block ("no `--change` flag; chart not yet rendered") is replaced
  by the one remaining true limit (Experimental-mode CLI changes exist but are view-I-only) plus
  a paragraph describing the SVG transition chart and the response-path honesty note; steps 3/4
  now show `--change separator_speed_rpm=+5 --view I`; "On the transition delay" mentions the chart.
- **§9 rows 5–6:** row 5 (mode changes not exposed) and row 6 (what-if deltas not exposed) now
  read as available-via-CLI; rows 1 and 7 updated in passing (10/10 screens render; the view-I
  transition chart is built). Only actually-stale claims were touched.

## 7. EquipmentStatus.constraints — PRD verdict

**No requirement exists.** No §17 row names views C/D/F (directive D-2); §18.2/§18.3 list tags,
not per-equipment constraint rows; §16.3's constraint banner is view I's, already rendered. The
field is payload capacity the provider does not currently supply — the test stub serves
`constraints=()` (`tests/conftest.py:817`) and the real path (`synthetic.py`
`_bands.per_component`, lines 931–979) exists but no source asks for any. Same treatment as view
D's `panels=()`: documented in the existing C/D/F row of `PROJECT_STATE.md`, not built. No
speculative UI was added.

## 8. Tests

- **Added (4)** in `tests/test_task6_what_if_view.py` (module now 35 tests): command-path drawing
  (2 polylines, guide, rails, ticks, legend with formatted numbers), no-variable-moved absence,
  moved-variable-without-ramp named-not-dropped (also covers non-numeric window), and the
  response-path honesty note. The stub `_PANEL` gained `ramp_minutes` for two variables.
- **Focused:** 35/35 pass before and after the change.
- **Full regression — run exactly once, at the end:** **693 passed, 0 xfailed** (279.12 s), up
  from 689 (+4). No test weakened, skipped, or rewritten.
- **Golden:** `tests/golden/view_i_normal.html` regenerated twice via the recorded command
  beside `GOLDEN_PATH` (once for the chart, once for the tick-anchor fix) — never hand-edited.

## 9. Frozen-layer digests — after the wave

Re-run after all edits (expected unchanged, and confirmed unchanged):

- `git ls-files -s src/models src/process_models src/optimization src/simulation src/features
  src/data_generation configs pyproject.toml | md5sum` → `c7a1f54dd578900835596c02cb9a19a0`
- `git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum` →
  `53f2aefec33494be5ca22c08ab22b5fd`

## 10. Final git status (to be the commit)

One commit. Files changed:

- `src/visualization/what_if_view.py` — the chart (production; only file in `src/` touched)
- `tests/test_task6_what_if_view.py` — +4 tests, stub ramp minutes
- `tests/golden/view_i_normal.html` — regenerated
- `docs/DEMO_GUIDE.md` — §5 + §9 corrections
- `docs/PROJECT_STATE.md` — TestNfr2Budget row, regression count 689→693, wave history, view-I
  row (chart built, 35 tests), C/D/F constraints verdict, Experimental-mode row's §5/§9 note,
  golden note, header purpose
- `docs/VIEWI_TRANSITION_CHART_REPORT.md` — this report (new)

