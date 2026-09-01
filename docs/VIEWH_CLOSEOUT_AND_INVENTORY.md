# VIEW H CLOSEOUT AND FULL A–J RENDERER INVENTORY

**Date:** 2026-09-01
**Scope:** read-only and docs-only. No code, test, fixture or frozen-layer file was changed; the
only product of this pass is this file. Frozen-layer digests were not re-run because nothing under
digest protection was touched (verified by `git status` — clean before and after).

This file does three things: settles the last open View H gap (G-10), tabulates the full A–J
renderer inventory against PRD §17, and ranks the next view to build. A proposed
`docs/PROJECT_STATE.md` update is included in §5 — **proposed only**; it gets applied in the next
implementation wave, not this one.

---

## 1. Settled gaps — carried, not re-investigated

Per the brief, three of the four View H gaps were already decided; their reasoning is carried
forward unchanged:

- **G-6 (prediction-fan chart)** — conscious skip during Wave View H: wiring a Plotly-optional
  chart (`charts.py:223`) into a plain-HTML deterministic renderer would add a degradation path the
  wave was not asked to build, and the horizon grid carries the item-10 requirement. `prediction_fan`
  remains dead code; a later wave must wire it or remove it.
- **G-8 ("Inject abnormal condition" control)** — classified in `docs/VIEWH_AUDIT.md` as
  directive-level, not renderer scope: no UI control or CLI flag exists anywhere; fault injection
  happens only through the scenario schedule (`configs/scenarios.yaml`, `scenario_driver.py`).
  Same class as item 13's sliders and item 17's presentation mode.
- **Quality field (HIGH/MEDIUM/LOW)** — belongs to the `Recommendation` (view J's data), per the
  §13.1.1 distinction already drawn in the audit; `PredictionSet`'s `Value` carries no quality
  field, and none was fabricated. Its absence on view H is correct, not an omission.

---

## 2. G-10 verdict — `AnomalyReport` evidence fields vs PRD §15

**Question:** which evidence fields exist on the frozen `AnomalyReport` vs what reaches
`AnomalyState` vs what PRD §15 actually requires to be **displayed**.

### 2.1 The trace

`AnomalyReport` (`src/anomaly_detection/detector.py:169-185`, frozen) carries 14 fields. What
happens to each, field by field:

| `AnomalyReport` field | Reaches `AnomalyState`? (`insights.py:156-194`) | Rendered on view H? | PRD display requirement |
|---|---|---|---|
| `status` | yes — `status` | yes — WARNING banner / "No anomaly detected." | **§15 line 1** (the `WARNING` line, `PRD:651`) |
| `detected_anomaly` | yes — `display_cause` + `nearest_regime` (with the item-11 inconclusive mapping) | yes — "Detected anomaly: …" + similarity-match note | **§15 line 2** (`PRD:652`) |
| `hypothesis` | yes — `hypothesis` | yes — "Likely cause (model-based hypothesis): …" | **§15 line 3** (`PRD:653`) |
| `affected_variables` | yes — same tuple | yes — ranked list, frozen `render()` presentation | **§15 line 4** (`PRD:654`) |
| `suggested_action` | yes — `suggested_action` | yes — "Suggested action …" | **§15 line 5** (`PRD:655`) |
| `anomaly_score` | yes — `score` | yes — the panel's own number | **§17 view 7** "Live anomaly score" (`PRD:700`) |
| `out_of_distribution` | yes | yes — OOD pill | not required (shown anyway) |
| `anomaly_kind`, `regime_similarity` | yes (kind, similarity) | drives the inconclusive branch / cosine display | not required displayed (internal classification) |
| `flagged` | **no — dropped by `from_report`** | no | **none** — see §2.2 |
| `ood_ratio` | **no — dropped** | no (only the boolean pill) | **none** |
| `evidence` | **no — dropped** | no | **none** |
| `dataset`, `timestamp` | yes | payload context | none |

### 2.2 What PRD §15 and §17 view 7 actually require on screen

- **§15 (PRD:647-657)** is titled "UI/output contract" and enumerates **exactly five displayed
  lines** (quoted in full in `docs/VIEWH_AUDIT.md` §1): the WARNING status, Detected anomaly,
  Likely cause, Affected variables, Suggested action. Its closing rule concerns *causal language*
  ("model-based hypothesis", never definitive diagnosis) — wording, not additional fields. **None
  of `flagged`, `ood_ratio`, `evidence` appears in §15's display contract.**
- **§17 view 7 (PRD:700)** adds two display elements: "Live anomaly score" and the warning card
  (which is §15), plus the inject *control* (gap G-8, directive-level, settled above). Again:
  none of the three dropped fields is named.
- The remaining PRD mentions of these fields are **not UI contracts**: §13.2 describes the
  detection *method* (SPC + Isolation Forest + nearest-regime cosine), §14.3 uses the OOD gate
  inside the optimizer, §22 covers offline evaluation reporting. `evidence` in particular is
  Model B's internal diagnostic bundle (`detector.py:209-226` serializes it for offline/JSON use).

### 2.3 Verdict: **CLOSED**

Every field PRD §15 and §17 view 7 require to be **displayed** reaches `AnomalyState` and is
rendered by `src/visualization/intelligence_view.py`. The three dropped fields are **Optional at
most** — internal diagnostics whose display no PRD section demands. No implementation work is
logged as required; an additive `AnomalyState` extension (the `baselines()` precedent) remains a
possible *enhancement*, never a requirement.

**One collateral backlog item (docs, small):** `DEMO_GUIDE.md:301-303` is now doubly stale — it
calls view H "JSON payload" (false since Wave View H added the renderer) and tells presenters to
read out "the evidence fields the detector used" (which `AnomalyState.describe()` never carried,
so neither the JSON fallback nor the renderer ever showed them). The next docs-owning wave should
rewrite that demo step around the rendered §15 card. Logged in §5.

---

## 3. Full A–J renderer inventory

Internal view letters are the directive's A–J registry (`src/digital_twin/state.py:76-86`).
Renderer status reflects `app.py`'s dispatch (`app.py:166-179`): B/E via `_is_twin` (svg_twin),
H via `_is_intelligence`, J via `_is_optimization` — everything else falls to `_payload_html`
(`app.py:112-123`, "no renderer for this screen yet"). Directive item numbers refer to
`docs/TASK6_DIRECTIVE.md` §1.

| Letter | Internal view | PRD §17 view | Renderer status | Directive items covered | Remaining build complexity |
|---|---|---|---|---|---|
| **A** | Plant Overview | **view 1** (PRD:694) | **missing** — JSON fallback | 3 (five-stage chain), 9 (three KPI groups), 12 (specific + total energy) | **small** — `OverviewView` payload exists (`state.py:634`); a plain-HTML renderer in the H/J pattern; the view-1 "AI status / anomaly status" tiles read the already-built intelligence payloads |
| **B** | Kiln Digital Twin | **view 2** (PRD:695) | **implemented** (`svg_twin`), **not verified** — directive item 4 status "IMPLEMENTED, NOT VERIFIED" | 4 (animated SVG twin, seven streams), 5 (kiln panel) | **small** — no build; a *verification* wave: tests pinning AC-2/AC-21 animation provenance, plus the open "twin missing-data symmetry" item |
| **C** | Preheater & Kiln | **none** — internal-only (D-2 discrepancy) | **missing** | 5 (kiln-line indicators) | **small** — `ProcessView` payload exists (`state.py:714`); no PRD §17 anchor, so value is internal completeness, not PRD coverage |
| **D** | Clinker Cooler | **none** — internal-only (D-2) | **missing** | 5 (kiln-line indicators) | **small** — `ProcessView` payload exists (`state.py:727`) |
| **E** | Cement Mill Digital Twin | **view 3** (PRD:696) | **implemented** (`svg_twin`), **not verified** | 4, 6 (mill panel) | **small** — same class as B |
| **F** | Mill & Separator | **none** — internal-only (D-2) | **missing** | 6 (mill/separator indicators) | **small** — `ProcessView` payload exists (`state.py:737`) |
| **G** | Energy Monitoring | **none directly** — its content is view 1's energy KPIs / §9.2; no own §17 row | **missing** | 12 — **VERBATIM** "The dashboard must NOT show only the favorable metric." | **small** — `EnergyView` payload exists (`state.py:748`) with the specific+total pairs already computed |
| **H** | AI Prediction & Anomaly | **view 7** (PRD:700) | **implemented** (Wave View H, 22 tests + golden) | 10, 11 | **small (backlog only)** — G-6 fan chart, §17 view-7 trends sparkline, G-8 inject control (directive-level) |
| **I** | What-If Simulation | **view 5** (PRD:698) | **partial** — payload and view layer built and tested, but **no renderer** and **unreachable** (no `--mode`/`--change` surface; experimental mode has no caller) | 13 (sliders, three outcomes), 23 (lazy path) | **medium** — renderer + `app.py` routing + the item-13 interactive surface; the §16.3 before/after + transition **charts** have unconsumed `ChartSpec` builders (`charts.py:308`, `charts.py:347`) needing Plotly-optional wiring |
| **J** | AI Optimization | **view 4** (PRD:697) | **implemented** (Wave View J + closeout + horizon; golden current) | 14, 15 (reconstructed), 16, 10 (recommendation-scoped grid) | **none** — done |

**Coverage totals:** 4 of 10 internal views render (B, E, H, J); of those, only H and J are
test-pinned. 6 of 10 are payload-only with renderers missing (A, C, D, F, G, I). Of PRD §17's ten
required views, the A–J set covers 1, 2, 3, 4, 5, 7 — **six**; views 6, 8, 9, 10 have no internal
letter at all (the documented D-2 discrepancy).

**PRD-only views (no letter — not part of the A–J table, recorded for honesty):**

| PRD §17 view | What exists today | Complexity if built |
|---|---|---|
| 6 Time-Series Explorer (PRD:699) | `get_timeseries` provider surface + `Series` downsampled channel exist; no view model, no builder, no zoomable chart | **large** — new backend view layer plus the heaviest chart requirement in the PRD |
| 8 Model Performance (PRD:701) | `model_performance_bars` chart builder exists (`charts.py:394`, unconsumed); frozen evaluation results exist in the ML layer but no Task-6 payload surfaces them | **large** — new payload + provider surface first |
| 9 Data Quality (PRD:702) | nothing — no data-kind, no payload | **large** |
| 10 Factory Data Requirements (PRD:703) | `real_plant.py:71` already cites the missing document; §27 content exists as PRD text only | **medium** — mostly a documentation-rendering task, but still a new view layer |

---

## 4. Top-3 recommendation — which view to build next

Ranked by PRD dependency/value against build complexity, **not** alphabetically:

1. **View A — Plant Overview.** It is PRD §17's landing view (view 1), the screen every one of the
   five §28 demos starts from, and AC-1's subject — yet it renders as raw JSON; the payload
   (items 3, 9, 12) is fully built, so this is exactly the H/J-shaped job: one plain-HTML renderer
   plus one additive `app.py` `elif`, the smallest possible wave with the widest demo value.
2. **View I — What-If Simulation.** PRD §17 view 5 is the only *interactive* screen and the spine
   of demos 2 and 4 (§28), and the payload plus view layer are already built and tested — but no
   caller can reach the experimental mode and there is no renderer, so the work is routing +
   renderer + the item-13 slider surface rather than new data. Ranked second, not first, only
   because the §16.3 transition-chart requirement makes it a medium wave, and the chart
   (`ChartSpec` builders already exist) forces a Plotly-optional degradation decision this project
   has so far deferred (the G-6 skip).
3. **View G — Energy Monitoring.** Item 12 carries one of the directive's few VERBATIM requirements
   — "The dashboard must NOT show only the favorable metric." — and the `EnergyView` payload
   already computes the specific+total pairs that satisfy it; nobody can see them. Smallest of the
   remaining waves, and it directly strengthens the honesty story the project leads with.

**Why not the others:** B and E need verification, not building — valuable, but a different kind of
wave than "next renderer". C, D and F have no PRD §17 anchor (internal-only views), so they rank
below every PRD-backed screen. The four PRD-only views (6, 8, 9, 10) are the largest gaps in PRD
terms but each needs new backend work first — they should be queued once the payload-only internal
views are rendered. View H's own leftovers (G-6, trends) are backlog polish, not a wave.

---

## 5. Proposed `docs/PROJECT_STATE.md` update — apply in the NEXT wave, not this one

This pass changes no other file, per the brief. The next implementation wave should apply:

1. **Wave history** — append this docs-only closeout after "View H audit → Wave View H".
2. **"Items 2–13 renderers" row** — update the count language from "6 of 10 views have no
   renderer" to: *"6 of 10 views have no renderer (A, C, D, F, G, I); the SVG twin (B/E), view J
   and view H do. B/E are implemented but unverified (no tests pin AC-2/AC-21). Full A–J inventory
   with PRD §17 mapping and per-view complexity: `docs/VIEWH_CLOSEOUT_AND_INVENTORY.md` §3."*
3. **View H row (items 10/11)** — trim its "Remaining view-H gaps" tail to reference this file, and
   mark **G-10 CLOSED** (no PRD-required display field is dropped; `flagged`/`ood_ratio`/`evidence`
   are optional internal diagnostics — see §2 above).
4. **New row — DEMO_GUIDE staleness (small, docs):** `DEMO_GUIDE.md:301-303` still calls view H a
   "JSON payload" (false since Wave View H) and claims presenters can read "the evidence fields the
   detector used" (never carried by `AnomalyState`). Rewrite Demo 3's step 5 around the rendered
   §15 card.
5. **New row — renderer inventory** (optional, if the table is preferred over prose): carry the
   §3 table's status column forward so each future wave can update one row instead of re-auditing.

Nothing else in `PROJECT_STATE.md` changes: test counts, digests, and the frozen-layer section are
untouched by this pass.

---

*Products of this pass: this file only. No code, test, fixture or frozen-layer change. Git: one
commit on `main`, pushed and verified against `origin/main`.*
