# Task 6 — Wave View A: Plant Overview renderer (closeout report)

**Date:** 2026-09-02 · **Wave:** View A (PRD §17 view 1 / §18.1 "Plant Overview") ·
**Previous wave:** View H (AI Prediction & Anomaly), see `VIEWH_CLOSEOUT_AND_INVENTORY.md`.

---

## 1. What this wave built

The first renderer for **view A — the Plant Overview**, the dashboard's landing screen:

* the five-stage chain of directive item 3 (`Quarry/Feed → Kiln system → Clinker → Cement
  Mill → Cement Product`), one card per stage with its own state word, its simulated rate
  and the PRD 8.3 equipment it groups — a *grouping of the twin*, not a second diagram:
  every number is the same observed `Value` the animated twin scales by;
* the plant KPI group of items 9/12 rendered whole — the specific energy figures, both
  production rates, and the daily totals the provider binds into that one group, with the
  group's own `SPECIFIC_VS_TOTAL_NOTE` (directive item 12, VERBATIM: the dashboard must
  NOT show only the favorable metric);
* PRD §18.1's two remaining tiles — **AI status** and **Anomaly status** — as compact
  one-line summaries of the view J / view H payloads;
* routing in `app.py` via a new `_is_overview` duck-type (`stages` + `plant`; no other
  screen's model carries both — the energy view has a `plant` group but no stage chain).
  The B/E/H/J dispatch and behavior are untouched.

Renderer: `src/visualization/overview_view.py` (`render_overview`), following the
`intelligence_view` / `optimization_view` conventions — self-contained HTML fragment with
scoped layout CSS, render-only (computes nothing, owns no threshold), every string escaped,
every number at `FormatSettings` precision, every absence stated.

## 2. Step 1 verdict — AI / anomaly status: **reused existing payloads (option a)**

Not a backend gap. Both PRD 18.1 status tiles are one-line readings of payloads that
already exist:

* **AI status** ← `state._ai_status_tile(self.optimization(frame).view)` — Model C's
  `OptimizationView` (the view J payload) on the *same frame*, no second optimizer run;
* **Anomaly status** ← `state._anomaly_status_tile(self._anomaly("kiln", stamp))` — Model
  B's `AnomalyState`, via the existing `_anomaly` accessor (not the full `intelligence()`
  build, so no Model A run is wasted on a tile that shows none of it), gated on
  `capabilities().anomaly`.

The new state-layer surface is deliberately minimal (accessor additions only, no
redesign):

* `OverviewStatus` — a frozen 5-field summary (`title`, `available`, `status`, `detail`,
  `provenance`) whose every word is the payload's own;
* two module-level tile mappers `_ai_status_tile` / `_anomaly_status_tile` in
  `state.py`, applying the mandated vocabulary: refusal → `NO_SAFE_RECOMMENDATION`,
  accepted run → `AI_RECOMMENDATION_LABEL`, absent model → `MODEL_UNAVAILABLE_LABEL`
  with the payload's own `unavailable_reason` — never a reassuring paraphrase;
* `OverviewView` gains `ai_status` / `anomaly_status` fields and their `describe()`
  entries.

Verified end-to-end on the full model layer: the AI tile reads *"AI Recommendation:
kiln_fuel_rate_tph -5.00 %; separator_speed_rpm -2.20 % (PASS / WITHIN_ENVELOPE, quality
LOW)"*; the anomaly tile reads *"No anomaly detected."* (the frozen detector's own NORMAL
wording). Under `--skip-models` both tiles state *"Model not available"* with the model
layer's own reason — nothing is fabricated.

## 3. Step 1 payload verification (the full seven cards)

| PRD 18.1 card | Source | Verdict |
|---|---|---|
| Kiln status | `stages["kiln_system"].state` + its equipment | present |
| Mill status | `stages["cement_mill"].state` + its equipment | present |
| Production | `plant` group (`clinker_production_tph`, `cement_production_tph`) | present |
| Thermal energy | `plant` group (specific kcal/kg + daily kcal total, one pair) | present |
| Electrical energy | `plant` group (specific kWh/t + daily kWh total, one pair) | present |
| AI status | reused view J payload (this wave) | present |
| Anomaly status | reused view H payload (this wave) | present |

## 4. Files changed

| File | Change |
|---|---|
| `src/digital_twin/state.py` | `OverviewStatus`, the two tile mappers, `overview()` reads the two payloads; `OverviewView` + `describe()` extended |
| `src/visualization/overview_view.py` | **new** — the view A renderer (~300 lines) |
| `app.py` | `overview_view` import, `_is_overview`, one `elif` branch, docstring/epilog cost notes |
| `tests/test_task6_overview_view.py` | **new** — 23 focused tests |
| `tests/golden/view_a_normal.html` | **new** — golden fixture (byte-for-byte) |
| `tests/test_task6_performance.py` | contract restated for view A's two model reads (dated Wave View A notes; details §7) |
| `docs/VIEWA_IMPLEMENTATION_REPORT.md` | this report |
| `docs/PROJECT_STATE.md` | wave entry appended |

No frozen-layer file was touched (digests in §8).

## 5. Tests added (23, all passing)

`tests/test_task6_overview_view.py`, self-contained on the View H/J convention (stub
payload → real renderer → assertions + golden file):

* **A — normal rendering:** three `data-role` sections; five stages in process order with
  four arrows; state pills / rates / equipment from the payload's own values; the
  item-12 specific+total pairing (all four tags, the note verbatim, both numbers).
* **B — status tiles:** AI headline; Model B's verdict; refusal as a display state
  (warn pill + gates' own words); normal row in the frozen layer's own words;
  `EVIDENCE_INCONCLUSIVE_LABEL` carried verbatim (item 11); absent model stated with its
  own reason twice, with no invented status.
* **C — degraded data:** missing rate → absence glyph, never a zero; UNKNOWN state →
  honest grey; empty plant group → honest statement, no invented cards.
* **D — honesty:** no "confidence", no `FORBIDDEN_CONTROL_LABEL`, the standing
  no-plant-connection statement, free-text escaping.
* **E — determinism:** two renders byte-identical.
* **F — routing:** view A reaches the renderer in `build_document`; a non-overview stub
  still falls to `_payload_html`; `_is_overview` does not swallow H-shaped or J-shaped
  models.
* **G — state layer:** the real `OverviewView.describe()` carries both tiles; the tile
  mappers map every payload state (available / refused / unavailable; anomaly / normal /
  unavailable).
* **Golden:** the whole render pinned byte-for-byte against
  `tests/golden/view_a_normal.html` (regeneration command recorded in the `GOLDEN_PATH`
  comment, same convention as view H).

Focused results: `tests/test_task6_overview_view.py` — **23 passed**;
`tests/test_task6_performance.py` (re-run after the contract edit) — **19 passed**.

## 6. Known gaps (recorded honestly)

* **Trend sparklines (PRD 18.1).** Each KPI card is specified "with current value, trend
  sparkline, and status color". `OverviewView` carries no trend channels, and adding
  history reads is beyond this wave's "accessor additions only" scope — so the cards
  render value + status color only. Same class of documented skip as view H's §17
  sparkline. Backlog item for the next wave that owns view A.
* **Kiln / mill "status" as a single word.** The PRD card is satisfied by the stage
  chain (state word + equipment states); there is no separate kiln-status computation,
  and none was invented.

## 7. Performance contract restatement (deliberate, dated in-code)

View A's two live tiles read `get_anomaly_state` and `get_optimization` — the same model
surfaces H and J render. That changes three statements `tests/test_task6_performance.py`
used to make, so the module (Task-6-owned and wave-extendable) was updated with dated
Wave View A notes rather than left failing:

1. `MODEL_SURFACES_BY_VIEW["A"]` = `{get_anomaly_state, get_optimization}` — view A is no
   longer a zero-model-surface screen. The rejected alternative (showing only capability
   *pointers* — "anomaly model available" instead of the payload's own verdict) is
   recorded in the table's comment: it would satisfy the letter of the laziness contract
   while failing the directive's own example ("no anomaly" / "1 recommendation
   available"), which asks for the payload's reading.
2. The once-per-frame surface-count test is restated as *once per screen that needs it*:
   on the eager `views()` path `get_anomaly_state` and `get_optimization` are now read
   twice — two screens' needs, not redundancy. Sharing one read across screens would be
   a state-layer redesign (a cache), which this wave's scope and the no-caching ruling
   both forbid. **Open option for a directive-level decision:** a shared per-frame model
   read would halve the eager path's model cost (~3 s of Model C search).
3. View A drops out of the "readout screens are a rounding error" set (six screens
   qualify now; the module docstring keeps the original 9-of-10 measurement as the
   pre-View-A number with a dated supersession note).

Production is unaffected: `app.py` uses the lazy `state.view("A")` accessor, and
`test_no_production_module_calls_the_eager_accessor` still passes. Under `--skip-models`
view A renders instantly with both tiles honestly unavailable.

## 8. Full regression, frozen digests, git

* **Full regression (run once, at the end):** `python -m pytest tests/ -q` →
  **612 passed, 0 failed** in 268 s. Baseline at session start was 589; the 23 new View A
  tests account exactly for the difference. The known intermittent failure did not appear
  this run — nothing flaky to note.
* **Frozen digests (verified this wave, before commit):**
  `git ls-files -s src/models src/process_models src/optimization src/simulation
  src/features src/data_generation configs pyproject.toml | md5sum` →
  `c7a1f54dd578900835596c02cb9a19a0` (unchanged);
  `git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum` →
  `53f2aefec33494be5ca22c08ab22b5fd` (unchanged). The frozen layer is byte-identical.

