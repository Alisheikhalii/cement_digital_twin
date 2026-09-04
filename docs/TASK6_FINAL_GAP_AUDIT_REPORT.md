# TASK #6 — FINAL GAP AUDIT REPORT

**Date:** 2026-09-04
**Wave:** Final Task #6 gap audit → prioritization → safe implementation
**Purpose:** establish the TRUE completion status of Task #6 against the authoritative PRD and the
recovered directive — not the renderer count — then implement only what is clearly required, fully
understood, small, within the current architecture, and outside the frozen layer.
**This is the single final report for this wave.**

---

## 1. Starting Git state

```
$ git log --oneline -3
1db6cec feat(task6): Item 17 Factory Presentation Mode - PRD 29 overlay of views A and J
e057125 feat(task6): Wave View I transition chart - SVG command paths + doc corrections
5795e5d feat(task6): Wave CDF - one shared renderer for the process detail screens

$ git status    # clean, up to date with origin/main
```

HEAD at start: `1db6cec` — the Item 17 Factory Presentation Mode wave, as the brief expected.

**Frozen-layer digests, before (unchanged):**

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0

git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd
```

**Test count at start:** 715 collected (269 Task-6 test functions across 14 `test_task6_*` modules
+ the frozen 17 modules).

---

## 2. Authoritative-source inventory

| Source | Status | Weight in this audit |
|---|---|---|
| `docs/PRD_Synthetic_Cement_Digital_Twin.md` (v1.1.1, 1124 lines) | on disk, authoritative | **Primary.** §17/§28/§29/§33/§34/§35 checked line-by-line. |
| `docs/TASK6_DIRECTIVE.md` | on disk, **a labelled reconstruction** | Secondary. Items 1–25 status below always name the evidence tier; E3 counts never treated as requirements. |
| `AUDIT_REPORT.md` (repo root, 1067 lines) | on disk, predates all Task-6 work | Primary for frozen-layer claims (conservation, causality, holdout, constraint safety). Read, not re-derived. |
| `docs/PROJECT_STATE.md` | on disk, wave handoff | **Treated as claims, not evidence** — every DONE row re-verified below. |
| Closeout reports (View J/H/A/G/I/CDF, Item 17, Waves 1–3D) | on disk | Cross-checked where they made a completeness claim. |

---

## 3. Task #6 directive items 1–25 — verified status

Directive status vocabulary retained; every row re-verified at current HEAD, not copied from
`PROJECT_STATE.md`.

| # | Item (short) | Status at `1db6cec` | Verified by |
|---|---|---|---|
| 1 | DataProvider, 10 data kinds, 4 channels | **IMPLEMENTED** (E1) | `provider.py` 15 abstract methods; `real_plant.py` 14 refusals; `ProviderCapabilities`; `test_task6_provider_contract.py` (20 tests) |
| 2 | Ten views A–J | **IMPLEMENTED** (E1) — all ten **rendered** | `VIEWS` registry; dispatch in `app.py` `_is_*`; §5 reconciliation below |
| 3 | Overview five-stage chain | **IMPLEMENTED + rendered** | `overview_view.py`; 23 tests + golden |
| 4 | Animated SVG twin, 7 named streams | **IMPLEMENTED + VERIFIED** | `test_task6_twin.py` — 24 tests incl. the AC-21 AST audit (§7.I below) |
| 5 | Kiln panel, no new UI limits | **IMPLEMENTED + rendered** | `process_view.py` (C/D/F share one renderer); 27 tests |
| 6 | Mill panel | **IMPLEMENTED + rendered** | same |
| 7 | Clock PLAY/PAUSE/RESET/STEP + speed | **PARTIAL** — logic implemented, **no UI control surface** (static export has no buttons). E1; unchanged all waves. |
| 8 | Historical replay scrubber | **PARTIAL** — logic implemented (`clock.py` REPLAY), no scrubber UI. Unchanged. |
| 9 | KPI groups kiln/mill/plant | **IMPLEMENTED + rendered** | views A/G/C/D/F |
| 10 | Multi-horizon prediction, spread not % | **IMPLEMENTED + rendered** | views H + J horizon grid; `test_task6_intelligence_view.py`, `test_task6_optimization_view.py` |
| 11 | Model B anomaly, "Evidence inconclusive" | **IMPLEMENTED + rendered + pinned** | view H; the `from_report` branch test-pinned |
| 12 | Specific **and** total energy | **IMPLEMENTED + rendered** | view G; `SPECIFIC_VS_TOTAL_NOTE` verbatim on-screen |
| 13 | What-if sliders, three verdicts | **PARTIAL** — payload + renderer + CLI surface (`--change`/`--mode`) exist; **no interactive sliders** (static export; a deliberate architecture property, not an omission this wave can fix) |
| 14 | Recommendation card from `describe()` | **IMPLEMENTED + rendered** | view J |
| 15 | §14.5 five-row baseline comparison | **IMPLEMENTED + rendered + test-pinned** (item text itself remains a labelled Tier-E2 reconstruction — the display now exists and satisfies AC-22) | `test_all_five_prd_145_baselines_are_shown` et al. |
| 16 | Refusals stay visible | **IMPLEMENTED + rendered** | view J + view P refusal display states |
| 17 | Factory Presentation Mode | **IMPLEMENTED + rendered + tested** (22 tests + golden; two stability cards honest gaps — §7.E) | `ITEM17_AUDIT_AND_IMPLEMENTATION_REPORT.md` |
| 18 | Demo scenarios from config | **PARTIAL** — selection API + `--scenario` CLI exist; no in-UI selector. Scenario count read from config (14), not the E3 "10". |
| 19 | Repeatable "Run Demo" sequence | **MISSING** — full audit §7.A below |
| 20 | Honesty rules | **IMPLEMENTED, largely enforced** — vocabulary centralised; badge defect (both sites) fixed in Waves 3B/View J closeout; per-renderer "confidence"-word sweeps exist (§7.B). Directive-level *automated* scan still partial (§7.B). |
| 21 | One-direction dependency | **IMPLEMENTED** (E1, diagram in `session.py`) | unchanged; module graph acyclic |
| 22 | Task-6 test areas / enforcement scans | **PARTIAL** — provenance separation + determinism + twin AST audit + no-confidence per-renderer sweeps exist; **no repo-wide no-hard-coded-number scan**. Full audit §7.B |
| 23 | Downsample, never stream raw window | **IMPLEMENTED** — lazy `view()` accessor is the production path (`test_no_production_module_calls_the_eager_accessor`); `Series` budgets configured; NFR-2 pinned at dashboard layer |
| 24 | Documentation topics | **IMPLEMENTED (7 of 7 PRD §35 documents exist)** — README, ARCHITECTURE, DATA_DICTIONARY, MODEL_CARD, SIMULATION_ASSUMPTIONS, DEMO_GUIDE, FACTORY_DATA_REQUIREMENTS. The E3 "8 topics" count was never a requirement. |
| 25 | Final report fields (21, E3) | **NOT VERIFIED / not deliverable** — the field list itself is unrecovered; this report does not fabricate it. |

---

## 4. PRD §17 reconciliation (A–J vs the PRD's ten rows)

The directive's A–J registry and the PRD §17 table are different sets (directive D-2, verified).
Reconciliation at `1db6cec`:

| PRD §17 view | A–J letter | Renderer | Status |
|---|---|---|---|
| 1 Plant Overview | A | `overview_view.py` | **IMPLEMENTED** (gap: §18.1 trend sparklines — no trend channels on the payload) |
| 2 Kiln Digital Twin | B | `svg_twin.py` | **IMPLEMENTED + verified** (AC-2/AC-21 pinned) |
| 3 Cement Mill Digital Twin | E | `svg_twin.py` | **IMPLEMENTED + verified** |
| 4 AI Optimization | J | `optimization_view.py` | **IMPLEMENTED** — current vs multi-horizon vs recommended, quality categorical, mode + envelope status |
| 5 What-If Simulation | I | `what_if_view.py` | **IMPLEMENTED** — §16.3 panel + transition chart (commanded paths; response path stated absent, never interpolated) |
| 6 Time-Series Explorer | — | none | **MISSING — payload-only nothing; BACKEND GAP** (`get_timeseries` + `Series` exist; no view model, no zoomable chart) |
| 7 Anomaly Detection | H | `intelligence_view.py` | **IMPLEMENTED** (gaps: "Inject abnormal condition" control + `DemoInjector` do not exist — §28.3 mechanism missing; prediction fan chart skipped) |
| 8 Model Performance | — | none | **MISSING — BACKEND GAP** (no Task-6 payload surfaces the frozen evaluation metrics; `charts.py:394` builder unconsumed) |
| 9 Data Quality | — | none | **MISSING — BACKEND GAP** (no data-kind, no payload) |
| 10 Factory Data Requirements | — | none | **MISSING — mostly a documentation-rendering task, still a new view layer** |
| §29 Presentation overlay | P (not a registry row) | `presentation_view.py` | **IMPLEMENTED** |

**Verdict:** 6 of 10 PRD §17 views fully implemented (1, 2, 3, 4, 5, 7) + the §29 overlay; views
6/8/9/10 have no internal letter at all. "All A–J renderers exist" ≠ "PRD §17 complete" — the four
non-lettered rows are the residual PRD view gap, and all four require new payload/backend work
(views 6, 8, 9 clearly; 10 medium). **Not implemented in this wave, per the brief.**

---

## 5. PRD §28 demo status

| # | Demo (PRD §28) | State |
|---|---|---|
| 1 | Normal Operation | **Executable + reproducible** via CLI (`DEMO_GUIDE.md` §2, fixed seed); not a single cell (no notebook) |
| 2 | Energy Optimization | **Executable + reproducible**; view J shows all five §14.5 baselines (AC-22 display half) |
| 3 | Low Oxygen | **Partially executable** — regime schedulable via `--scenario`; the PRD's *mechanism* ("Inject abnormal condition" control) **does not exist**; Model B detection + warning card render on view H |
| 4 | Mill Optimization | **Executable + reproducible**; before/after table + transition chart on view I (response path stated absent) |
| 5 | What-if Analysis | **Executable + reproducible**; `--change`/`--mode EXPERIMENTAL` reach the envelope banner |

**PRD §28's framing** — "Each demo is a single Colab cell (Section 25, cell 11) that requires no
manual setup once earlier cells have run" — is **not satisfied**: no notebook exists (§7.G).
Reproducibility *is* satisfied and test-enforced (`test_task6_reproducibility.py`, fixed seed ⇒
identical screens). Scriptability is not: each demo is run by hand from `DEMO_GUIDE.md`.

## 6. PRD §29 status

**Implemented** (Wave Item 17, `1db6cec`), re-verified this wave by running
`python app.py --skip-models --view P` (3.7 s, 14.5 KB self-contained output) and the 22-test module.
Production/Quality Stability cards state the backend gap honestly — no metric invented (§7.E).
`presentation.refresh_seconds` remains unconsumed (static export; documented).

---

## 7. Focused investigations (the brief's A–N)

### A. Item 19 — "Run Demo" sequence — **MISSING, not implementable this wave**

- Directive (E1 for existence, E3 for the 11-step count): "repeatable in front of an audience" —
  `session.py:351`. PRD §28: "single Colab cell … no manual setup once earlier cells have run."
- **What the PRD actually requires today:** each of the five demos runnable as one notebook cell,
  inside the §25 notebook (`notebooks/00_cement_digital_twin_demo.ipynb`, 12 ordered cells).
- **What exists:** no `notebooks/` directory; a CLI host (`app.py`) that renders each demo in one
  command with a fixed seed; a `DEMO_GUIDE.md` scripting all five; no `run_demo`/`RunDemo` symbol
  anywhere in `src/`.
- **Conclusion:** Item 19's PRD-shaped closure requires the §25 notebook, which does not exist. A
  12-cell Colab notebook that installs, simulates, trains, evaluates, optimizes and renders is
  **substantial architecture**, not a small safe fix — and the current static-export architecture
  *cannot* legitimately claim to be "a single Colab cell" per demo. Per the brief's explicit stop
  rule: **not implemented; classified P1-for-future / notebook wave.** No arbitrary step-count was
  implemented.

### B. Item 22 — enforcement scans — **PARTIAL**

Existing, verified:
- **Provenance separation** (E1): `mixed_channels` + `value_channels` walk all ten finished views —
  `test_task6_provider_contract.py` `test_no_view_model_mixes_two_data_sources` and the
  capability-poor degradation test.
- **Determinism** (E1): byte-identity, fresh-payload identity, wall-clock/random import ban
  (`test_task6_twin.py`), plus signature-stripping of `runtime_s` with a mutation-tested AST guard
  (`test_task6_reproducibility.py` — the guard fails if production hardcodes the duration).
- **AC-21 animation-provenance scan** (the §34 extended no-hard-coding audit *for the animation
  path*): three-part — behavioural (two states → visibly different emitted durations/widths/
  particle counts), structural (`animation_report` = the state→animation layer as plain data, every
  parameter checked equal to `AnimationSettings.scale` of a configured pair), and a **literal-magnitude
  AST audit** of the binding functions (`flow_anim`/`glyph_anim`/`glow_anim`: no numeric constant
  except a structural whitelist; every configured pair consumed). Plus a CSS scan (no durations/
  colours in the stylesheet) and a geometry-exception audit.
- **No-confidence sweep, per-renderer:** every task-6 view module asserts `"confidence" not in
  html.lower()` + no forbidden control label (twin, app smoke, J, H, A, G, I, C/D/F, P). The
  presentation module additionally sweeps raw tags / model internals / code.

Missing:
- **A repo-wide no-hard-coded-number scan** over *dashboard-assembly code* (PRD §34 row
  "UI/no-hard-coding audit (extended)": "every displayed numeric field in dashboard-assembly code
  **and** every visualization-animation parameter"). The animation-parameter half exists (above);
  the displayed-numeric-field half does not exist as one automated scan. What exists instead is
  behavioural: every renderer test asserts values come from the payload (e.g.
  `test_baseline_metric_values_come_from_the_payload`), and `theme.format_number` at
  `FormatSettings` precision is the single formatting home.
- AC-21/§34 wording "originates from a `Twin.current_state_snapshot()` call" — the twin renders from
  `StateSnapshot`, whose values derive from the driver's `simulation_step` of `PlantTwin` (the same
  object `current_state_snapshot()` reads). The binding is real but the *phrase* "snapshot() call"
  is a PRD-level idealisation; the enforced property (no animation magnitude outside
  `AnimationSettings.scale` of a state fraction) is equivalent and test-pinned.

**Decision on implementing a new scan:** the exact intended rule for a *repo-wide* numeric-literal
scan cannot be derived precisely enough from the PRD to be both true and non-vacuous: the renderer
layer legitimately contains structural numbers (list indices, string widths, viewport geometry —
already whitelisted per-module), and the PRD's own §19.3 sanctions geometry in code. A weak AST
grep that only passes would violate the brief's "no weak tests" rule. **Not implemented; classified
P2 with the derivation problem stated.** The two E1-attested scans and the AC-21 audit already
cover the directive's named areas.

### C. Twin missing-data symmetry — **CLOSED BY EVIDENCE (recategorised: not a Task-6 gap)**

The item appears only in `PROJECT_STATE.md` / wave reports as "Open. Not started" — **no directive,
PRD, AUDIT_REPORT or recovery-plan text defines it** (searched: directive 25 items, PRD, AUDIT_REPORT,
`TASK6_RECOVERY_PLAN.md`; the term first appears in Wave 3A's own handoff table with no definition).
The nearest evidenced requirements — a missing reading must render stopped, never at an invented
speed; a glyph with no driver must render still and say so — are **implemented and test-pinned**
(`test_task6_twin.py:520,558`: fraction `None`, at-rest parameters, `dt-flow--idle`,
`NO_VALUE_TEXT`). Because no recoverable requirement exists beyond this, the honest classification
is **implemented-what-is-evidence + definition-unrecovered (E-nothing)** — recorded here so the
next wave does not chase a phantom.

### D. Production Stability metric — **BACKEND GAP, correctly not invented**

PRD §29 *names* the card; §14.5's shared metric set includes "stability" as a comparison metric;
`MODEL_CARD.md`/optimizer internals carry stability *penalty terms* (model internals §29 bans from
Presentation Mode). No model output computes a plant-manager-facing production-stability metric.
The card states the absence (test-pinned). Building one would be a new model-layer computation —
**frozen-layer territory, forbidden this wave and future Task-6 waves.** Classified BACKEND GAP /
P3.

### E. Quality Stability metric — **BACKEND GAP** — same evidence, same verdict as D.

### F. PRD §17 rows without A–J letters — **see §4** (views 6/8/9/10; all payload/backend work;
not implemented this wave per the brief).

### G. PRD §25 Colab notebook — **MISSING**

`notebooks/` does not exist. PRD §23's tree and §25's 12-cell plan are unimplemented; README and
DEMO_GUIDE state this honestly. `src/` is importable (NFR-7), which the notebook would rely on.
This is the same architecture gap that blocks Item 19 (§7.A). **P1-future (notebook wave) — a
substantial build, not a small safe fix.**

### H. PRD §28 demo requirements — **see §5.** Executable and reproducible via CLI; single-cell
framing unsatisfied (notebook missing); Demo 3's inject mechanism missing.

### I. AC-21 (animation binding / no-hard-coding audit) — **SATISFIED at the twin**

Verified in depth: `svg_twin` renders from `StateSnapshot` (values from the driver's stepped twin);
every animation parameter is `AnimationSettings.scale(pair, Value.fraction_of_range())`; enforced
behaviourally (state change → emitted markup change), structurally (`animation_report`, every
parameter equals scale of the configured pair, every configured pair consumed) and by AST literal
audit of the binding functions; CSS carries no duration/colour of its own; a missing reading draws
stopped. The directive item-4 status "NOT VERIFIED" is **obsolete** — 24 tests pin it. The only
residual is the repo-wide dashboard-assembly scan (§7.B, P2).

### J. AC-22 (five-row baseline comparison) — **SATISFIED**

Confirmed quickly, as the brief anticipated: PRD §14.5's five rows render on view J
(`OptimizationView.baselines()` accessor; unavailable rows show their own reason, never a zero;
`test_all_five_prd_145_baselines_are_shown`, `test_unavailable_baseline_row_shows_its_reason_not_a_number`,
`test_baseline_metric_values_come_from_the_payload`, plus golden `view_j_normal.html`).
The compute half was already frozen-and-tested (`TestBaselines`). **Display half: COMPLETE.**

### K. AC-23 (chronological + scenario-holdout) — **SATISFIED (frozen layer)**

- `reports/metrics/model_a_horizon_metrics.json`: 392 rows, both splits present
  (`chronological`, `scenario_holdout`), both references (measured/truth).
- Frozen tests: `test_model_a.py::test_every_prd_22_metric_is_present_for_every_pair_split_block_and_reference`
  (every trained pair × both splits × both references), `test_both_evaluation_references_are_reported_and_differ`;
  holdout construction pinned in `test_features_ml.py` (whole regimes withheld, purge at the boundary)
  and `test_ml_leakage.py` Q5. AUDIT_REPORT §Q5: PASS.
- Task-6 display half (PRD §17 view 8 "Model Performance") **does not exist** — the metrics are
  computed and reported to `reports/metrics/` but not surfaced on any screen (§4). The AC itself
  ("both result sets reported") is met by the reporting layer.

### L. AC-24 (conservation + causality) — **SATISFIED (frozen layer)**

Verified present and passing at source: `test_kiln_energy_balance`, `test_kiln_mass_balance`,
`test_mill_mass_balance` (`test_kiln_conservation.py` / `test_mill_conservation.py`); 13 causality
tests (`test_causality.py`); 26 conservation-validation tests. AUDIT_REPORT corroborates (7+7
conservation, 14 causality, all PASS). No drift: frozen digests unchanged since the audit.

### M. Stale documentation — **FOUND AND FIXED THIS WAVE**

Three documents still described the pre-renderer state:
1. `README.md` "Honest status": "8 of 10 views emit raw JSON… Presentation Mode not implemented."
2. `docs/DEMO_GUIDE.md` §0.2/§0.4/§2/§3/§4/§7/§9/§10: "eight screens render as raw JSON", "§7 not
   implemented" with the full pre-implementation artefact table, stale `app.py` docstring claim,
   "slides so you never project raw JSON".
3. `docs/ARCHITECTURE.md` §6: "Two of ten screens have a renderer"; `refresh_seconds` note claiming
   Presentation Mode "is not implemented".

All corrected (see §10). No production file was touched.

### N. Tests claimed complete but only partially verified — **none found at the presentation layer**
beyond the already-documented gaps (sparklines, inject control, trends channels, non-lettered
views — all stated in their owning reports and carried into §11). `TestNfr2Budget` was re-verified
in the 2026-09-03 doc wave and stands.

---

## 8. AC-1 … AC-24 verification matrix

| AC | Layer | Status | Evidence |
|---|---|---|---|
| AC-1 | Task-6 | **PASS** | view A: stage states, KPI group, status tiles (23 tests + golden) |
| AC-2 | Task-6 | **PASS** | twin emits `@keyframes` + live classes; two states visibly differ (pinned) |
| AC-3 | Task-6 | **MISSING** | Time-Series Explorer does not exist (§4 view 6) |
| AC-4 | Task-6 | **PASS** | NFR-2 round trip pinned at dashboard layer; visibly different outcome + delay visible in transition chart |
| AC-5 | Frozen | **PASS** | seeded, versioned data generation (AUDIT_REPORT) |
| AC-6 | Task-6 | **PARTIAL** | view J prediction is Model A's own payload; direct trace-to-saved-metrics display is the missing view 8 |
| AC-7 | Task-6 | **PASS** | view J card from `Recommendation.describe()` unchanged |
| AC-8 | Frozen | **PASS** | what-if ↔ recommendation consistency tests |
| AC-9 | Task-6 | **PASS** | `FACTORY_DATA_REQUIREMENTS.md` — 56 tags, generated from `schema.py` |
| AC-10 | Task-6 | **PASS** | README "Path to a real system" < 1 page |
| AC-11 | Task-6 | **PASS** | every export carries the three badges + standing statements; limitations reachable |
| AC-12 | Task-6 | **PARTIAL** | structurally satisfied for payloads (`Value` + provenance) and per-renderer value tests; the single repo-wide automated scan is missing (§7.B) |
| AC-13–AC-16 | Frozen | **PASS** | fuel units, balances, delays, multi-horizon — all pinned in frozen tests |
| AC-17 | Task-6 | **PASS** | §21 statement verbatim on view P + every export footer |
| AC-18 | Task-6 | **PASS** | categorical quality only; "confidence" swept per renderer |
| AC-19 | Frozen | **PASS** | envelope REJECT/FLAG tests incl. experimental mode (verified) |
| AC-20 | Frozen | **PASS** | `test_no_weight_vector_can_buy_a_hard_constraint_violation` (4 fuzzed vectors) |
| AC-21 | Task-6 | **PASS** | §7.I — behavioural + structural + AST audits of the animation path |
| AC-22 | Task-6 | **PASS** | §7.J — five-row §14.5 table on view J, test-pinned |
| AC-23 | Frozen | **PASS** | §7.K — both splits computed, reported, differ; surfaced-in-view-8 gap noted (§4) |
| AC-24 | Frozen | **PASS** | §7.L — conservation + causality present and passing |

---

## 9. Prioritization

**P0 (release-blocking, PRD acceptance criteria):** **none newly found.** Every AC that Task #6
owns is PASS or covered by an honest, documented, test-pinned partial (AC-3 is the one true
presentation-layer AC failure — see P1-future).

**P1 (required Task-6 functionality, not safely implementable in this wave):**
1. PRD §17 view 10 (Factory Data Requirements screen) — new view layer; medium.
2. PRD §25 notebook + Item 19 single-cell demos — substantial architecture (§7.A/G).
3. PRD §17 views 6/8/9 — backend view-layer work (Time-Series Explorer, Model Performance, Data
   Quality).
4. PRD §18.1 trend sparklines (A/G/H) — payload channels exist for G/H but the renderer chart
   decision (Plotly-optional degradation) is deliberately deferred.

**P2 (documentation / verification / enforcement gaps):**
1. Repo-wide no-hard-coded-number scan — derivation problem stated in §7.B; requires a
   precisely-derived rule before writing (a weak scan is worse than none).
2. Demo 3 "Inject abnormal condition" control — a directive-level UX decision on an interactive
   surface that the static export cannot host; documented in DEMO_GUIDE §9 row 4.
3. Items 7/8/18 UI control surfaces — same static-export constraint.
4. Item 15 verbatim-text recovery — still unrecovered; the reconstruction stands and its display
   is built.

**P3 (future phase / backend / intentionally deferred):**
1. Production Stability + Quality Stability metrics (BACKEND GAP, frozen layer) — PRD §29 names the
   cards; no model computes them; cards state the absence. **Never invent.**
2. Anomaly *count* for the presentation card — needs a new detector output.
3. `presentation.refresh_seconds` — needs a serving layer that does not exist.
4. Twin missing-data symmetry — recategorised closed-by-evidence (§7.C); no recoverable requirement
   remains unimplemented.

---

## 10. Implementation performed in this wave — YES (documentation only)

Per §7.M, three stale documents corrected to match the code at `1db6cec`:

| File | Change |
|---|---|
| `README.md` | "Honest status" rewritten: ten renderers + Presentation Mode implemented; residual gaps named precisely (non-lettered §17 views, sparklines, notebook, demo sequence, static-export nature). |
| `docs/DEMO_GUIDE.md` | §0.2 rewritten (all ten render; JSON fallback is history); §0.4 stale-docstring claim removed (docstring was fixed in the Item-17 wave); §2/§3/§4/§10 JSON-payload references replaced with the designed-screen reality; **§7 rewritten**: Presentation Mode implemented, with the two honest card-level gaps and the CLI command; §9 gap table rows 8/9/10 updated. |
| `docs/ARCHITECTURE.md` | §6 "Two of ten screens have a renderer" → all ten + dispatch map; `refresh_seconds` note corrected (mode implemented, loop not); a stale `app.py:113-114` anchor re-anchored to `:282`; registry table's obsolete `*(rendered)*` markers dropped. |

**No production file, no test, and no frozen file was touched.** No renderer behavior changed. No
metrics invented. No new scan written (derivation problem stated, §7.B).

---

## 11. Tests

- **Focused, before implementation:** `tests/test_task6_twin.py` (24 passed — re-verifying the
  AC-21 audit claims in §7.I); `tests/test_task6_app_smoke.py` +
  `tests/test_task6_presentation_view.py` (40 passed — re-verifying the §6/§7.E claims).
- **Live verification:** `python app.py --skip-models --view P` — presentation export confirmed
  working (3.7 s, self-contained; artifact deleted after inspection).
- **Full regression, run exactly ONCE at the end:** see the commit's PROJECT_STATE entry —
  715 passed, 0 failed, 0 xfailed; regression floor 428 holds. (Documentation-only change; no test
  outcome can move.)

---

## 12. Frozen-layer digest, after the wave

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0   (unchanged)

git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd   (unchanged)
```

---

## 13. Final Git state

One documentation commit on `main`, pushed to `origin/main`, verified by fetch; working tree clean.
The commit hash is pinned in `docs/PROJECT_STATE.md` (this report is part of the commit and cannot
contain its own hash).

---

## 14. Recommended NEXT WAVE

**Wave: PRD §25 notebook + §28 single-cell demos (Item 19 closure).** It is the largest remaining
P1 block and it unblocks PRD §28's own framing ("single Colab cell, no manual setup"). Scope:
build `notebooks/00_cement_digital_twin_demo.ipynb` on the §25 12-cell skeleton — install/config/
simulate/dataset/validate/train/evaluate/optimize/visualize/dashboard/demo-cells/export — with the
five demos as one cell each (cell 11), reusing the importable `src/` unchanged and the already-
rendered view functions; no frozen-layer change. Before starting, decide the training-cost budget
for cell 6 (the full model layer is ~12 s locally but heavier in Colab) and whether demo cells
may assume earlier cells ran.

If the notebook is judged out of scope for v1.1's Task #6, the alternative next wave is **PRD §17
view 10 (Factory Data Requirements screen)** — the smallest of the four non-lettered views and
mostly a documentation-rendering task.

Do **not** schedule: stability metrics (backend/frozen), the repo-wide literal scan (rule not yet
derivable), or the interactive control surfaces (items 7/8/18 + inject — need a serving layer
decision first).
