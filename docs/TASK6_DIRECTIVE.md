# TASK #6 DIRECTIVE — RECOVERED TRACEABILITY DOCUMENT

**Created:** 2026-08-24 (recovery Phase 6A, step 5)
**Git baseline:** `1f8107fbead34228d38553b930681686bdd89493`
**Status of this file:** RECONSTRUCTION, not the original artefact.

---

## 0. Why this file exists, and what it is not

The authoritative Task #6 directive was a numbered list of **25 items**. It was **never persisted to
this repository**. It survives only as citations inside source comments and docstrings, plus prose in
`TASK6_RECOVERY_PLAN.md` (which recovered it from session transcripts). `TASK6_RECOVERY_PLAN.md`
§12.4 records this gap and mandates persisting it here.

**This document is a traceability aid ONLY.**

- It **must not** be used as a specification to rewrite the existing Task #6 implementation.
- It **must not** be treated as the verbatim original. Only the passages marked `VERBATIM` below are
  quoted word-for-word from a source on disk.
- Where evidence was insufficient, the item is marked **UNRECOVERED** rather than guessed.
  **No requirement in this file was invented.** An admitted gap is correct; a plausible fabrication
  is the worst possible outcome for a traceability document.
- **One exception, labelled as one:** item 15 is a **RECONSTRUCTED (Tier E2)** entry — an explicit,
  argued inference from the PRD and the frozen layer, marked at every point as *not recovered and not
  verbatim*, with its own evidence and its own stated weaknesses. It is not a silent guess, and it is
  the only entry of its kind. Everything else is either sourced or marked UNRECOVERED.

### Evidence tiers

| Tier | Meaning |
|---|---|
| **E1 — source-cited** | An in-namespace source file explicitly cites this directive item number and paraphrases or quotes its requirement. Strongest tier. |
| **E2 — corroborated** | No numbered citation, but the subject is unambiguously implemented/configured in the Task #6 layer and anchored in the PRD. |
| **E3 — plan-only** | Attested only by `TASK6_RECOVERY_PLAN.md`, which recovered it from transcripts. No on-disk source citation. Treat the *subject* as reliable and any *count* as unverified. |
| **UNRECOVERED** | No evidence found at any tier. |
| **RECONSTRUCTED** | Requirement text not recovered, but inferred from a PRD requirement that falls inside the item's E1-located band and is claimed by no other item. Always carries the reasoning, the counter-evidence and an instruction to overwrite it if the verbatim item surfaces. Used **once**, for item 15. Never cite it as the directive's words. |

### ⚠ Directive-numbering collision (verified — read before using any citation)

**Directive item numbers are namespaced per task.** More than one task in this project issued a
numbered directive, and the numbers overlap. Conflating them fabricates requirements.

`grep -rnoE "Task #[0-9]+ directive" --include=*.py src tests` → **13 hits, all `Task #6 directive`**;
the explicit prefix therefore only ever means Task #6. But *bare* `directive item N` citations also
appear in frozen Task #1/#4/#5 files and mean something else entirely:

| Out-of-namespace citation | What it actually refers to |
|---|---|
| `tests/test_optimization.py:176` — "directive item 16 — do not tune constraints after seeing results" | optimization directive |
| `tests/test_optimization.py:193` — "without touching physics (directive item 15) or the shipped thresholds (item 16)" | optimization directive |
| `tests/test_optimization.py:369` — "directive items 1-3: gate *before* accepting anything" | optimization directive |
| `tests/test_optimization.py:537`, `:1636` — "Directive item 17: an impossible quality window returns a refusal" | optimization directive |
| `tests/test_optimization.py:1220` — "directive item 12's rule-based baseline" | optimization directive |
| `src/data_generation/conservation.py:171` — "the directive's point 2" | data-generation directive |
| `src/digital_twin/synthetic.py:143` — "the **audit** item 24" | an audit list, not a directive |
| `src/digital_twin/synthetic.py:1343` — "PRD 16, item 17" | a PRD sub-item, not a directive |

**In-namespace (authoritative for Task #6):** everything under `src/digital_twin/` and
`src/visualization/`; `src/labels.py`; `src/optimization/recommendation.py:69` and `:190` (both
explicitly say "Task #6 directive item 12").

Task #6 item 15 **must not** be recovered from `tests/test_optimization.py:193`. Those are different
directives that happen to share an integer.

---

## 1. The 25 items

Status vocabulary: **IMPLEMENTED** · **PARTIAL** · **MISSING** · **NOT VERIFIED** (may exist, no test
proves it) · **UNRECOVERED** (requirement text itself not recovered) · **RECONSTRUCTED** (requirement
text inferred and labelled as an inference — item 15 only).

Recurring qualifier — **"payload only"**: the view-model/data layer is built and correct, but no
renderer turns it into a screen. Only the SVG twin has a renderer today.

---

### Item 1 — DataProvider abstraction, ten data kinds, four provenance channels
**Tier:** E1
**Intent:** All dashboard data arrives through a single `DataProvider` contract covering ten data
kinds, so a real-plant source can be substituted without changing the dashboard. Every displayed
number carries provenance, and the four sources — **OBSERVED / TRUTH / PREDICTION /
RECOMMENDATION** — are *never merged inside one channel*. A provider declares what it can answer via
`capabilities()` so views **degrade instead of crashing**.
**Evidence:** `src/digital_twin/provider.py:10`, `:79` ("directive item 1: the ten data kinds");
`src/digital_twin/provenance.py:3` ("requires the payload to *keep four sources apart*"), `:31`,
`:40`, `:220`; `src/digital_twin/payloads.py:1`, `:172`; `src/digital_twin/real_plant.py:207`;
`src/visualization/theme.py:86`, `:237`, `:384`.
**PRD:** §26.1 (common interface), §8.4, §8.5, NFR-6.
**Status:** **IMPLEMENTED.** Verified: 15 `@abstractmethod` in `provider.py`; **14** `raise
NotImplementedError` statements in `real_plant.py` (:186, :197, :209, :217, :230, :248, :258, :270,
:279, :291, :301, :311, :330, :341 — a 15th grep hit at `:6` is docstring prose, not a statement);
`ProviderCapabilities` (`payloads.py:171-190`) exposes
`synthetic/truth/history/live/predictions/anomaly/optimization/what_if/missing`. **Untested** (0 tests).

### Item 2 — The ten dashboard views, A–J
**Tier:** E1
**Intent:** Ten named screens, ids A–J.
**Evidence:** `src/digital_twin/state.py:71-87` — the `VIEWS` registry, verbatim ids:
A Plant Overview · B Kiln Digital Twin · C Preheater & Kiln · D Clinker Cooler ·
E Cement Mill Digital Twin · F Mill & Separator · G Energy Monitoring ·
H AI Prediction & Anomaly · I What-If Simulation · J AI Optimization.
Also `src/digital_twin/layout.py:1`, `:198`, `:241`.
**PRD:** §17 (ten required views), §18.
**Status:** **PARTIAL.** All ten builders exist and are registered; **8 of 10 have no renderer.**
Separately, PRD §17's ten-row table is only partly the same set — see §2 "View-count discrepancy".

### Item 3 — Plant overview chain, five stages in process order
**Tier:** E1
**Intent:** The overview shows `Quarry/Feed → Kiln system → Clinker → Cement Mill → Cement Product`
as a grouping of the twin, not a second diagram, with each stage quantified by a simulated rate.
**Evidence:** `src/digital_twin/layout.py:624` ("Plant overview chain (directive item 3)"), `:643`
("The five stages directive item 3 names, in process order") → `OVERVIEW_CHAIN`;
`src/digital_twin/state.py` `_stage_state` (RUNNING/IDLE/UNKNOWN "read from its throughput (item 3)").
**PRD:** §8.2, §8.3, §17 view 1.
**Status:** **IMPLEMENTED (payload only).** Renderer MISSING.

### Item 4 — Animated SVG process twin — **SVG, not GIF** — seven named streams, equipment state changes
**Tier:** E1
**Intent:** The twin animates flow. Animation parameters (dash speed, particle count, stroke width)
are `fraction_of_range` of the *current simulated value* of a named `rate_tag`, so "a stream that
slows on screen slowed in the simulation". Where a visible rate is a proxy, the modelled relationship
must be named "so nothing is animated on a made-up basis". Seven streams are required **by name**:
fuel→kiln, air→kiln, material→preheater→kiln, clinker→cooler, clinker→mill, material→separator,
finished cement→output. Equipment state changes are shown.
**Evidence:** `src/digital_twin/layout.py:384`, `:401` ("the whole animation contract of directive
item 4"), `:419` (the seven streams enumerated); `src/labels.py:152` ("directive item 4: 'equipment
state changes'"); renderer `src/visualization/svg_twin.py`.
**PRD:** §19.3 (rendering technology decision), §19.4 (Single Source of Truth & Visualization
Binding, mandatory), §8.2. **AC-2**, **AC-21**.
**Status:** **IMPLEMENTED, NOT VERIFIED.** The plan measured `twin_document()` emitting ~23 KB of
self-contained animated HTML with zero UI dependencies installed. No test pins it; AC-21 parameter
provenance is unproven. **Preserve — do not rewrite.**

### Item 5 — Kiln panel; do NOT hard-code new engineering limits into the UI
**Tier:** E1
**Intent:** The kiln panel shows fuel, feed, burning-zone temperature, O₂, CO, ID fan, production and
other measured kiln-line indicators. Ranges, statuses and targets come from **existing
configuration** — the UI invents no limit and edits no configured range "to make the dashboard tidier".
CO belongs in the main panel only.
**Evidence:** `src/digital_twin/layout.py:30`, `:45`, `:70`; `src/digital_twin/synthetic.py:286`
(the three-authority band resolution, "directive item 5: no new engineering limit in the UI");
`src/digital_twin/provenance.py:190` ("directive item 5 forbids exactly that").
**PRD:** §18.2, NFR-6, **AC-12**.
**Status:** **IMPLEMENTED (payload only).** Renderer MISSING.

### Item 6 — Mill panel
**Tier:** E1
**Intent:** The mill panel shows feed, motor power, separator speed, differential pressure and the
remaining available mill/separator/fan indicators.
**Evidence:** `src/digital_twin/layout.py:73`, `:87`.
**PRD:** §18.3.
**Status:** **IMPLEMENTED (payload only).** Renderer MISSING.

### Item 7 — Simulation clock: PLAY / PAUSE / RESET / STEP + speed control
**Tier:** E1
**Intent:** Transport control over the simulation. STEP advances one sample and pauses first ("a step
is a manual nudge"). RESET returns to the start of the session (pause, zero budget, reseek start).
Selectable speeds.
**Evidence:** `src/visualization/clock.py:2`, `:292`, `:349`, `:402`;
`src/digital_twin/settings.py:111` — `ClockSettings(speeds, default_speed, step_minutes,
max_live_steps)`; `src/digital_twin/provider.py:155`, `:167`; `src/digital_twin/settings.py:138`.
**PRD:** §19.1, §19.2.
**Status:** **PARTIAL.** Clock logic IMPLEMENTED; **no UI control surface.** Speed values come from
config — this document does not restate them (see `configs/dashboard.yaml`).

### Item 8 — Historical mode: timeline, timestamp, play/pause, scrubber, replay speed
**Tier:** E1
**Intent:** REPLAY over a historical window with a scrubber. A live clock has no rewind — only RESET.
**Evidence:** `src/visualization/clock.py:299`, `:374` ("scrubber (REPLAY, directive item 8)"),
`:402`; `src/digital_twin/settings.py:121` — `ReplaySettings(speeds, default_speed, step_minutes)`;
`src/digital_twin/provider.py:179`.
**PRD:** §19.2.
**Status:** **PARTIAL.** Replay logic IMPLEMENTED; **no UI control surface.**

### Item 9 — KPI groups: kiln, mill, plant — no invented KPI
**Tier:** E1
**Intent:** Three labelled KPI groups, containing no KPI the implementation does not already produce.
**Evidence:** `src/digital_twin/layout.py:106` ("KPI groups (directive item 9)") →
`KILN_KPI_TITLE`/`MILL_KPI_TITLE`/`PLANT_KPI_TITLE`; `src/digital_twin/synthetic.py:981`, `:1051`
("The three KPI groups of directive item 9, no invented KPI among them");
`src/digital_twin/payloads.py:134`; `src/digital_twin/provider.py:115`.
**PRD:** §17 view 1, §18.
**Status:** **IMPLEMENTED (payload only).**

### Item 10 — Multi-horizon prediction; uncertainty as a spread, never a confidence percentage
**Tier:** E1
**Intent:** The prediction view receives the **full horizon grid**. Observed `current` and predicted
`by_horizon` stay in **two channels** "precisely so a view cannot render them as one series of
values". Uncertainty is shown as spread/band — never a fabricated numeric confidence.
**Evidence:** `src/digital_twin/insights.py:41`; `src/digital_twin/session.py:245` ("directive item
10 asks the prediction view for the full horizon grid").
**PRD:** §13.1, §13.1.1, §22. **AC-16**, **AC-18**.
**Status:** **IMPLEMENTED (payload only).** No-confidence-% scan MISSING.

### Item 11 — Model B anomaly; sensor drift shows "Evidence inconclusive"
**Tier:** E1 (with a `VERBATIM` display string)
**Intent:** Display Model B's anomaly output. When Model B's own evidence does not separate an
instrument fault from a process deviation — the documented sensor-drift limitation — the *cause*
field reads **"Evidence inconclusive"** instead of naming the nearest regime signature. The nearest
signature is still carried, under its own name, as a *similarity match*, not as a cause. Invent no
diagnosis.
**Evidence:** `src/labels.py:81-83` — `EVIDENCE_INCONCLUSIVE_LABEL = "Evidence inconclusive"`
(`VERBATIM`); `src/digital_twin/insights.py:110`, `:160`.
**PRD:** §15, §11.4 (regime 14 "Sensor drift" — confirmed present in `configs/scenarios.yaml`), §31.
**Status:** **IMPLEMENTED (payload only).** Untested.

### Item 12 — Show specific **and** total energy
**Tier:** E1 — **VERBATIM quote available**
**Intent:** `src/labels.py:175` records the requirement word-for-word:
> **"The dashboard must NOT show only the favorable metric."**

Rationale, from `layout.py:150`: "a dashboard that shows only specific energy can report an
improvement while total consumption rises, because production rose." So each specific-energy KPI is
paired with the daily total it implies (`intensity × rate × scale × DAILY_HOURS`), computed once in
`recommendation.daily_total`. The total is a **display aggregation of observed values, not a fifth
data source** — it keeps `Provenance.OBSERVED` and names its arithmetic in `source`.
**Evidence:** `src/labels.py:175` (verbatim); `src/digital_twin/layout.py:144`, `:150`;
`src/digital_twin/synthetic.py:1018`, `:981`; `src/optimization/recommendation.py:69`, `:190`.
**PRD:** §17 view 1, §18, §9.2.
**Status:** **IMPLEMENTED (payload only).**

### Item 13 — What-if sliders using the exact configured step sizes; three outcomes; invent no ranges
**Tier:** E1 (with `VERBATIM` display strings)
**Intent:** Sliders for the manipulated variables, using the **configured** bounds and step sizes —
do not invent ranges. A what-if answer carries one of exactly **three verdicts**, which are display
forms of states the engine already reached (`accepted`, `simulated`, envelope status) and **not a
second judgement**:
`"PASS / WITHIN ENVELOPE"` · `"REJECTED / OUTSIDE ENVELOPE"` · `"NO SAFE RECOMMENDATION FOUND"`
(all three `VERBATIM`, `src/labels.py:107-112`).
**Evidence:** `src/labels.py:107`; `src/digital_twin/insights.py:301`, `:350` ("directive item 13's
three outcomes are the ones the engine already reached").
**PRD:** §16.1, §16.2, §16.3. **AC-4**, **AC-15**.
**Status:** **PARTIAL.** Payload IMPLEMENTED; **sliders / interactive surface MISSING.**

### Item 14 — Decision-support recommendation card; no fabricated confidence
**Tier:** E1
**Intent:** Render Model C's run as a decision-support card directly from
`OptimizationResult.describe()` **unchanged** — "the panel renders from it and never recomputes an
impact." No fabricated confidence value.
**Evidence:** `src/digital_twin/insights.py:210-215`.
**PRD:** §14.4, §16.3. **AC-7**, **AC-18**.
**Status:** **IMPLEMENTED (payload only).**

### Item 15 — **RECONSTRUCTED (Tier E2 — evidence-based, NOT verbatim)**
**Tier:** **E2 — reconstruction by inference** for the requirement text · **E1** for its subject area
**Reconstructed:** 2026-08-31, documentation-only wave. This section **supersedes** the earlier
**UNRECOVERED** entry; every piece of evidence that entry established is retained below.

> ### ⚠ This is an inference. It was not recovered.
> The requirement stated below is **not** quoted, paraphrased or attested by any transcript, source
> comment or plan document. **No source on disk says what item 15 demands.** What follows is this
> document's **best evidence-based reconstruction**, derived from (a) the E1-located band item 15
> occupies and (b) the one Must-level PRD *display* requirement in that band that no other directive
> item claims. It is a **hypothesis with a strong evidentiary base, not a recovered requirement.**
> Nothing in it may be treated as the directive's own words. If the verbatim item is ever recovered,
> **overwrite this section** — do not reconcile the two.

#### Reconstructed requirement

**The AI-optimized recommendation must be displayed against the full PRD §14.5 baseline set — all
five rows, over one shared metric set, on identical process conditions — per AC-22.** A
recommendation shown on its own, or against a single "before" number, would not satisfy it.

| # | PRD §14.5 row (verbatim title) | `baselines.py` key | Row is |
|---|---|---|---|
| 1 | Current Operating Point | `current_operating_point` | observed |
| 2 | Historical Baseline | `historical_baseline` | observed aggregate |
| 3 | Best Comparable Historical Condition | `best_comparable_historical` | observed aggregate |
| 4 | Digital Twin Baseline (rule engine) | `digital_twin_baseline` | twin simulation |
| 5 | AI-Optimized Operating Point | `ai_optimized_operating_point` | twin simulation |

#### Why this, and not something else — the inference, stated so it can be attacked

1. **The band is E1-fixed.** Item 15 sits between item 14 (the recommendation card) and item 16
   (refusal visibility), inside the Model C / optimization-display group. Three in-namespace sources
   cite item 15, all inside *plural range* citations; they establish **where** item 15 lives and
   **not one states what it demands.** Re-verified at current HEAD:
   `src/digital_twin/synthetic.py:1330` — section header `# -- Model C (PRD 14, 16, 17; items 15-17)`;
   `:1337` — `get_optimization` docstring, "Model C's run at the current operating point, refusals
   included (items 15-16)"; `src/digital_twin/state.py:871` — view J docstring, "the optimizer's
   recommendation or its refusal, as decision support (items 14-16)". Corroborating range:
   `src/digital_twin/state.py:1` — "Task #6 directive items 1-21".
   *(The earlier entry cited `:1303`, `:1310` and `:827`. Those are correct for the pinned baseline
   `1f8107f` and have since drifted; the citations themselves are unchanged.)*
2. **Exactly one Must-level PRD display requirement in that band is unclaimed.** PRD **FR-11**
   (`PRD:104`, priority **Must**) requires the system to "compute **and display**" the
   Current / Historical / Best Comparable / Digital Twin Baseline **vs** AI-Optimized comparison.
   §14.5 (`PRD:631-640`) defines its five rows and requires "the same metric set — energy,
   production, quality, stability, constraints"; **AC-22** (`PRD:1079`) makes it an acceptance
   criterion; §28 demo 2 (`PRD:998`) requires the demo to show the recommendation "compared against
   all five Section 14.5 baselines". Item 14 claims the card; item 16 claims refusals. **Nothing
   else claims this.**
3. **The frozen layer built it, in full, as a deliverable.** `src/optimization/baselines.py:1`
   ("builds exactly those five, always all five"), `:52-71` (the five keys with their verbatim PRD
   titles), `:238-268` (`BaselineSet.build` emits five rows, unavailable ones included and labelled).
   Serialized at `src/optimization/optimizer.py:360` under the `"baselines"` key. Tested by the
   frozen `TestBaselines` (`tests/test_optimization.py:841`; `.baselines.row(...)` at `:873`, `:881`,
   `:1316`) — part of the 428 baseline.
4. **The data already reaches view J, and is then dropped.** `OptimizationView.payload` *is*
   `OptimizationResult.describe()` unchanged (`src/digital_twin/insights.py:321`), so **the complete
   five-row comparison is present in view J's payload today**, under `payload["baselines"]`. What is
   absent is any way to reach or show it: `OptimizationView` (`insights.py:209-260`) exposes
   `recommendation()` but has **no** baselines field or accessor, and the Task #6 layer contains
   **zero** references to `baselines`/`BASELINE` outside two `synthetic.py` docstrings (`:1172`,
   `:1175`) describing the history frame it feeds. A Must-level display requirement whose data is
   already computed, serialized and delivered — but never surfaced — is precisely the shape of a
   directive item that was issued and left unfinished.

#### Limits of this reconstruction — read before relying on it

- **It is weaker than a normal E2.** §0's tier table defines E2 as a subject "unambiguously
  implemented/configured **in the Task #6 layer**". This subject is implemented in the **frozen**
  `src/optimization/` layer and reaches Task #6 only transitively, through `payload`. The PRD
  anchoring is strong; the Task-#6-implementation half of the E2 test is **not** met.
- **The "five rows" framing comes from §14.5 and FR-11, not from AC-22's own wording.** AC-22's
  parenthesis names four *comparators* (Current / Historical / Best Comparable / Digital Twin
  Baseline); the fifth row, AI-Optimized, is the thing being compared *to* them. Same requirement,
  different counting — do not quote "AC-22's five baselines".
- **A competing attribution exists, and it is out of namespace.** `tests/test_optimization.py:842`
  attributes §14.5 to "**Directive item 12** / PRD 14.5". Per §0's collision table that file is the
  **optimization** directive's namespace (whose item 12 is the rule-based baseline, `:1220`) — *not*
  Task #6's item 12, which is specific **and** total energy. The clean reading — *optimization* item
  12 directed the frozen layer to **compute** the comparison, Task #6 item 15 directed this layer to
  **display** it — is consistent with all the evidence, but it is a reading, not an attestation.
- **No exclusivity is claimed.** Items 5, 6, 12 and 20 (traceable numbers, no hard-coded values,
  never only the favourable metric, honesty labelling) all bear on *how* such a table must be
  rendered. This reconstruction assigns item 15 the requirement to **show the comparison**, no more.
- **Knowing the area was never knowing the requirement.** The previous entry's refusal to infer was
  correct on its own terms and is not overturned here: what changed is that the inference is now
  written down *as an inference*, with its evidence and its weaknesses stated, because a labelled
  reconstruction is more useful to the next wave than a blank — and less dangerous than a silent
  guess. It is still not a recovered requirement.
- **Out of namespace — still must not be used as item 15:** `tests/test_optimization.py:193`
  ("directive item 15") belongs to the **optimization** directive (collision table, §0).
  `AUDIT_REPORT.md` contains **zero** occurrences of "directive". `TASK6_RECOVERY_PLAN.md` names
  items 1–14 and 16–25 in various places but **never item 15**.

> **Correction to the first version of this file** (retained — it records a verification failure worth
> not repeating). An earlier version asserted "**No in-namespace citation of item 15**". That was
> **false**, and the fault was the grep, not the repo: both searches used *singular* forms
> (`directive item 15`, `(directive|item)[^a-z0-9]{0,8}15\b`), which cannot match `items 15-17` or
> `items 15-16` — the plural `s` is alphanumeric and blocks the character class. The working form is
> `grep -rniE "\bitems? +[0-9]" --include=*.py src`. With range citations included, in-namespace
> citations cover items **1–23**; only items **24** and **25** have none.

**PRD:** §14.5, §14.6, FR-11, §28 demo 2. **AC-22.**
**Status:** **MISSING — not even payload-reachable.** The five-row comparison is computed by the
frozen layer and delivered in `OptimizationView.payload["baselines"]`, but no accessor exposes it and
**no renderer exists for view J at all** (`src/visualization/` renders only the SVG twin). Closing
this belongs to the **view J renderer wave**, alongside items 14 and 16, which are in the same state.
**Action still open, no longer blocking:** recovering the verbatim item 15 from the original session
transcript, or asking the user, would supersede this section and remains worthwhile. It is **no longer
a blocker** — the reconstruction is actionable, and the work it implies is already queued behind the
eight missing renderers.

### Item 16 — Rejected recommendations stay visible, with their reason
**Tier:** E1
**Intent:** "A refusal is a display state, not an empty card." `refused` and `refusal_reasons` are
first-class. The reasons shown are **the blocking gates' own reasons — the optimizer's words, not a
second explanation.** Never silently drop a rejected recommendation.
**Evidence:** `src/digital_twin/insights.py:213`, `:277`.
**PRD:** §14.3, §30 (non-`PASS` states "shown, not hidden or silently clipped"). **AC-19**.
**Status:** **IMPLEMENTED (payload only).**

### Item 17 — Factory Presentation Mode — *"This is a critical requirement"*
**Tier:** E3 for the wording; E2 for the subject
**Intent (per `TASK6_RECOVERY_PLAN.md:43`, `:106`, `:232`):** A Factory Presentation Mode, flagged in
the directive as *"This is a critical requirement"*. The plan states it requires **10 elements** and
that a user must be able to *"run a complete demonstration without opening notebooks or developer
tools"*. The **10-element count is E3 and UNVERIFIED against any on-disk source.**
**PRD §29 (authoritative, on disk):** a *simplified rendering path, not a separate data path*,
showing `Current Plant State → AI Prediction → Optimization Opportunity → Recommended Action →
Expected Benefit`, with five KPI cards — Potential Thermal Energy Saving, Potential Electrical Energy
Saving, Production Stability, Quality Stability, Anomalies Detected — **every card** labelled
"Synthetic Demonstration" or "Simulation Estimate", plus a visible link to the §21
Synthetic-to-Real disclaimer. It **never** shows raw tag lists, model internals, code, or a numeric
confidence percentage; recommendation quality appears only as the HIGH/MEDIUM/LOW categorical.
**Evidence on disk:** `src/digital_twin/settings.py:129-131` — `PresentationSettings` docstring
"Factory Presentation Mode (PRD 29)", fields `refresh_seconds`, `headline_decimals` **only**;
`src/digital_twin/session.py:13`; `src/digital_twin/provider.py:3`.
**PRD:** §29, **FR-12**, §21.5, §4 Persona 3. **AC-17**, **AC-18**.
**Status:** **MISSING.** Two config keys exist; there is no presentation renderer.
> Note: `configs/dashboard.yaml:80` `refresh_seconds: 2.0` is tagged `# ASSUMPTION` and is read by
> nothing but settings parse/validate/describe. It is **not** a PRD budget and must not drive
> optimization. The real budget is NFR-2 (< 3 s).

### Item 18 — Demo scenarios, taken from configuration only; invent no new physics
**Tier:** E1 for the mechanism; **count is DISPUTED**
**Intent:** Selectable driving scenarios read from **configuration and nothing else**; switching a
scenario pauses and returns to session start. "Do not invent new physics."
**Evidence:** `src/digital_twin/scenario_driver.py:1`, `:147` ("scenario selection (directive item
18: configured scenarios only)"), `scenario_options()` — "The selectable scenarios, read from
`configs/scenarios.yaml` and nothing else"; `src/digital_twin/provider.py:171`, `:175`;
`src/visualization/clock.py:413`, `:420`; `src/digital_twin/synthetic.py:1436`.
**PRD:** §28 (Demo Scenarios), §11.4 (operating regimes).
**Status:** **PARTIAL.** Selection API IMPLEMENTED; **no UI control surface.**
> ⚠ **Count discrepancy — unresolved.** `TASK6_RECOVERY_PLAN.md` claims **10 named scenarios**.
> Neither on-disk source supports that number: `configs/scenarios.yaml` defines **14** named regimes
> (Normal low/medium/high, High fuel, Low oxygen, High oxygen, Fan instability, Feed disturbance,
> Temperature disturbance, Mill overload, Mill underload, High separator speed, Low separator speed,
> Sensor drift), and **PRD §28 defines 5** demo scenarios. **Do not implement "10" as a requirement.**
> The honest implementation reads the count from configuration, which is what the code already does.

### Item 19 — A repeatable "Run Demo" sequence
**Tier:** E1 for existence; **step count is E3**
**Intent:** A scripted demo sequence, deterministic enough to be *"repeatable in front of an
audience."*
**Evidence:** `src/digital_twin/session.py:351` — "what makes the demo sequence of directive item 19
repeatable in front of an audience".
**PRD:** §28 ("Each demo is a single Colab cell (Section 25, cell 11) that requires no manual setup
once earlier cells have run").
**Status:** **MISSING.**
> ⚠ `TASK6_RECOVERY_PLAN.md` says **11 steps**. That count is **E3 / UNVERIFIED** — no on-disk source
> states it. Treat "11" as a transcript recollection, not a requirement, until confirmed.

### Item 20 — Honesty rules (non-negotiable)
**Tier:** E1 — **VERBATIM strings available**
**Intent:** A screen must **never** imply plant connectivity, real-time control, automatic control,
validated savings, guaranteed optimization, or a validated plant model. The permitted vocabulary is
centralised in `src/labels.py` "so no view can reword them":
- `SIMULATED_RESULT_LABEL = "Simulated result"` — for a number a simulation produced
- `NOT_VALIDATED_LABEL = "Not validated against real plant data"` — for a model that has never seen plant data
- `SYNTHETIC_DEMONSTRATION_LABEL` — the badge every view header carries
- `MODEL_UNAVAILABLE_LABEL = "Model not available"` — "A missing model is stated, never filled in with a plausible number"
- `NO_PLANT_CONNECTION_STATEMENT` (`VERBATIM`, the standing footer of every view):
  > "This dashboard reads a synthetic simulation. It is not connected to any plant, it reads no plant
  > instrument, and it writes no setpoint: every recommendation is decision support for a human
  > operator."

**Evidence:** `src/labels.py:79`, `:85-99`; `src/digital_twin/state.py:30-33`.
**PRD:** §21.5 (required standing statement), §30 (FR-16 — "AI Recommendation," never "Automatic
Control Command"), §31. **AC-11**, **AC-17**, **AC-18**.
**Status:** **PARTIAL.** The vocabulary is IMPLEMENTED and centralised. **Enforcement is MISSING** —
no scan proves no view softens it, and there is a live defect:
> 🐞 **Confirmed defect (this session, at source).** `src/digital_twin/state.py:570` sets
> `badge=labels.SYNTHETIC_DEMONSTRATION_LABEL` **unconditionally**, ignoring
> `capabilities().synthetic` (which exists — `payloads.py:181`). A provider reporting
> `synthetic=False` would still be labelled "Synthetic Demonstration". That is simultaneously an
> NFR-6 traceability violation and an item-20 honesty violation.
> **A second site the recovery plan did not record: `src/visualization/svg_twin.py:530` hard-codes
> the same badge.** Any fix must cover **both** sites.

### Item 21 — Clean architecture: one direction of dependency
**Tier:** E1 — dependency diagram reproduced verbatim from source
**Intent:** `src/digital_twin/session.py:3-9` reproduces the required flow:
```
DataProvider  ->  Application / Domain Services  ->  Digital Twin / ML / Optimization
                              |
                              v
                    Dashboard API / State  ->  Visualization
```
A view model is "plain, frozen, JSON-describable", so a test can assert the numbers a screen will
show **without a browser**; a renderer may only *read* a view model — "it holds no process object,
calls no model and owns no limit." The state layer "sits below the HTML/SVG renderer, and its single
job is to turn what a provider can answer into the ten view models … without emitting a byte of HTML."
**Evidence:** `src/digital_twin/session.py:3-16`; `src/digital_twin/state.py:1-9`;
`src/digital_twin/settings.py:138`.
**PRD:** §8.2 (layered design, mandatory), §23, **NFR-7**.
**Status:** **IMPLEMENTED.** Corroborated: the recovery plan found **zero** backward imports from the
frozen Task #1–#5 layer into Task #6 (3 grep hits, all string-literal or docstring).
> Known layering smell, not a defect: a *package-level* import cycle exists via
> `src.visualization.clock`, but the **module graph is acyclic** and no `ImportError` is reachable.
> `TASK6_RECOVERY_PLAN.md` §3 rules explicitly: do not "fix" it.

### Item 22 — Task #6 test areas
**Tier:** E1 for existence; **count (16) is E3**
**Intent:** A named set of test areas for Task #6, including provenance separation and determinism.
Two are directly attested:
- **Provenance separation** — `src/digital_twin/state.py:865` "Provenance-separation audit (directive
  items 1, 22)". `mixed_channels` walks a finished view model and returns any channel that broke the
  rule, "so the item 22 test is a one-liner" (`state.py:1`-block).
- **Determinism** — `src/digital_twin/scenario_driver.py:30` "Determinism (NFR-4, directive item 22):
  every step is a pure function of the configs, the seed, …".
**PRD:** §34 (Testing Strategy), including the extended no-hard-coding audit covering "every
displayed numeric field … *and every visualization-animation parameter*".
**Status:** **MISSING. Zero tests exist for Task #6** — 0 of the 428 touch `src/digital_twin/` or
`src/visualization/`.
> ⚠ The "**16** test areas" figure is E3 / UNVERIFIED. The two named above are E1.

### Item 23 — Performance: downsample; never stream the raw window
**Tier:** E1 — repeated phrasing across five files
**Intent:** "Never stream the raw window" / "Do not stream thousands of unnecessary points." Trends
are downsampled to a configured budget before display; a 10× tick must be "as cheap as a 1× one".
**Evidence:** `src/digital_twin/payloads.py:23` (`Series` — "One downsampled trend channel (directive
item 23: never stream the raw window)"); `src/digital_twin/provider.py:107`;
`src/digital_twin/settings.py:100` — `HistorySettings(max_points, sparkline_points,
live_window_minutes, default_window_hours, downsample_method)`; `src/digital_twin/real_plant.py:252`;
`src/digital_twin/scenario_driver.py:257`.
**PRD:** **NFR-1**, **NFR-2** (< 3 s what-if round trip).
**Status:** **PARTIAL.** Budgets are configured and the `Series` contract exists. A lazy accessor
`DashboardState.view()` already exists (`state.py:848-856`) but the eager `views()`
(`state.py:858-861`) is what gets called, costing ~7.9 s/frame. Downsampling enforcement is
unverified. **Fix by using the existing lazy path — not by adding caching.**

### Item 24 — Documentation topics
**Tier:** E3
**Intent (per `TASK6_RECOVERY_PLAN.md:254`, `:425`):** **8** documentation topics must be covered.
**No in-namespace source citation exists.** The only repo hit near this number,
`src/digital_twin/synthetic.py:143`, says "the **audit** item 24" — a different list (see §0).
**PRD anchor (authoritative, on disk):** §35 requires **7** documents — `README.md`,
`ARCHITECTURE.md`, `DATA_DICTIONARY.md`, `MODEL_CARD.md`, `SIMULATION_ASSUMPTIONS.md`,
`DEMO_GUIDE.md`, `FACTORY_DATA_REQUIREMENTS.md`.
**Status:** **MISSING (5 of 7 PRD documents absent).** Present: `MODEL_CARD.md`,
`SIMULATION_ASSUMPTIONS.md`. Absent: the other five.
> ⚠ The **8 topics** figure is E3 and does **not** equal PRD §35's 7 documents. Do not conflate them.
> `src/digital_twin/real_plant.py:71` already cites `FACTORY_DATA_REQUIREMENTS.md`, which does not
> exist — a dangling reference PRD §35 independently mandates fixing. **AC-9**, **AC-10**.

### Item 25 — Final report fields
**Tier:** E3
**Intent (per `TASK6_RECOVERY_PLAN.md:381`, `:420-421`, `:460`):** a final report of **21 fields**,
including **#17 visual evidence of every major view** and **#18 performance measurements**.
**No in-namespace source citation exists** — nothing in `src/` cites item 25.
**Status:** **NOT VERIFIED / not deliverable today.** Fields #17 and #18 are *structurally*
impossible right now because there is no entrypoint: nothing can be launched, screenshotted or timed.
> ⚠ The **21-field** list itself is **not recovered** — only its existence and two of its fields are
> attested, and those only at E3. **Do not fabricate the remaining 19 field names.**

---

## 2. Cross-cutting discrepancies to carry forward

| # | Discrepancy | Resolution |
|---|---|---|
| D-1 | **Item 15 requirement text unrecovered — now RECONSTRUCTED (Tier E2), no longer blocking** | The verbatim text is still unrecovered. Its *subject area* is E1-located — Model C / optimization display (`synthetic.py:1330`, `:1337`; `state.py:871` at current HEAD; `:1303`, `:1310`, `:827` at `1f8107f`). §1 item 15 now records a labelled, argued **reconstruction**: the AI-optimized recommendation must be displayed against the full PRD §14.5 five-row baseline set, per **AC-22** / FR-11. Marked *inferred, not recovered* throughout; overwrite it if the verbatim item surfaces. Recovery from transcript, or asking the user, is still worthwhile. **Task #6 completeness is no longer gated on this** — what gates it is that the display does not exist, which is the view J renderer wave's work, not a recovery problem. |
| D-2 | **View-count: 10 vs 14** | Both are real and only partly overlapping. Directive item 2's A–J (`state.py:71-87`) and PRD §17's ten-row table are different sets; the union is 14 renderable views. PRD-only additions: **Time-Series Explorer, Model Performance, Data Quality, Factory Data Requirements** (AC-3, AC-9). |
| D-3 | **Scenario count: plan says 10** | Unsupported. Config has **14** regimes; PRD §28 has **5** demos. Read the count from configuration. |
| D-4 | **"Run Demo" 11 steps** | E3 only. Unverified. |
| D-5 | **Item 22 "16 test areas"** | E3 only. Two areas are E1-attested. |
| D-6 | **Item 24 "8 topics" vs PRD §35's 7 documents** | Different lists. PRD §35 is authoritative and on disk. |
| D-7 | **Item 25 "21 fields"** | Existence E3; the field list is unrecovered. |
| D-8 | **Synthetic badge hard-coded at 2 sites** | `state.py:570` **and** `svg_twin.py:530`. The recovery plan records only the first. Both must be fixed. |
| D-9 | **`svg_twin.py` vs "twin.py"** | `TASK6_RECOVERY_PLAN.md` §3.4/§7-6F calls the renderer `twin.py`. The real file is **`src/visualization/svg_twin.py`**. |
| D-10 | **`refresh_seconds: 2.0`** | Self-imposed `# ASSUMPTION`, read by nothing. **Not** a PRD budget. NFR-2 (< 3 s) is the real one. |

---

## 3. PRD acceptance criteria bearing on Task #6

PRD §33 defines **AC-1 … AC-24**. **Fourteen** bear on the Task #6 presentation layer; **none of the
fourteen is tested at the presentation layer today.**

| AC | Requirement (abbreviated) | Directive item(s) |
|---|---|---|
| AC-1 | Plant Overview shows what kiln and mill are each doing now | 2, 3, 9 |
| AC-2 | Twin views **visibly animate** flow, not a static picture | 4 |
| AC-3 | Time-Series Explorer identifies which variables matter | 2 (PRD-only view) |
| AC-4 | What-if produces a visibly different, physically sensible outcome within NFR-2's 3 s | 13, 23 |
| AC-6 | Optimization view's prediction traceable to Model A's saved metrics | 10, 14 |
| AC-7 | Optimization view shows baseline vs proposed, impact, NL reason | 14, 16 |
| AC-9 | Factory Data Requirements lists concrete tags | 2 (PRD-only view), 24 |
| AC-10 | README/ARCHITECTURE explain the path to a real system in < 1 page | 24 |
| AC-11 | **Every** screen and export carries "Synthetic Demonstration"; limitations reachable | 20 |
| AC-12 | **No panel contains a hard-coded / non-traceable number** | 5, 6, 20 |
| AC-17 | Every synthetic performance claim carries the §21 disclaimer; Presentation Mode never implies real validation | 17, 20 |
| AC-18 | **No numeric "confidence %" anywhere**; HIGH/MEDIUM/LOW only | 10, 14, 17 |
| AC-21 | **Every animated element** is driven by live `Twin.current_state_snapshot()`, not prerecorded or hard-coded | 4 |
| AC-22 | AI recommendations are compared against the **full §14.5 baseline set** on identical process conditions | **15** (reconstructed) |

**On AC-22's move into this table.** It was previously counted among the frozen layer's ACs, on the
grounds that the 428-test baseline covers it. That is true of only half of it. AC-22 cites §14.5, and
**FR-11** (`PRD:104`, Must) states the obligation as "compute **and display**":

- the **compute** half is frozen and tested — `src/optimization/baselines.py`, serialized at
  `optimizer.py:360`, covered by `TestBaselines` (`tests/test_optimization.py:841`);
- the **display** half is a Task #6 obligation and **does not exist** — no accessor on
  `OptimizationView`, no renderer for view J. It is mapped here to item 15 (see §1).

The remaining **ten** (AC-5, AC-8, AC-13–16, AC-19, AC-20, AC-23, AC-24) belong to the **frozen** Task
#1–#5 layers and are already covered by the 428-test baseline.

---

## 4. Standing constraints (apply to every remaining Task #6 phase)

1. **Tasks #1–#5 are frozen.** No change to physics, simulation equations, ML equations, Model A,
   Model B, optimization equations or weights, hard constraints, envelope/OOD thresholds, the
   uncertainty ceiling, training ranges, or model targets.
2. **Invent no engineering limit.** Ranges, steps and targets come from existing configuration
   (items 5, 13).
3. **Fixes belong in the Task #6 layer.** Model A raising on NaN input is *correct*; supplying NaN is
   the Task #6 bug. Guards go in `src/digital_twin/`, never `src/models/`.
4. **A guard must state an absence, never substitute a number** (item 20, NFR-6).
5. **Honesty is non-negotiable** (item 20): no claimed real-plant connectivity, no automatic control,
   no validated savings, no fabricated confidence percentage, no silently dropped refusal.
6. **Never loosen a safety constraint to make a demo look better.**
7. **The regression floor is 428 passed.** Any drop halts the phase and is investigated — never
   "fixed" by editing an existing test.
8. **Do not split `synthetic.py`** and **do not "fix" the package-level import cycle**
   (`TASK6_RECOVERY_PLAN.md` §3, adjudications #3 and #11).
9. The application is **SYNTHETIC DEMONSTRATION / DECISION SUPPORT ONLY.**

---

## 5. The directive's closing line — VERBATIM

> **"The dashboard is a presentation and decision-support layer over the existing validated
> implementation, not a new modeling layer."**

**Evidence tier: E2 — attested verbatim.** Quoted word-for-word from `TASK6_RECOVERY_PLAN.md:350`,
which records it as the closing line of the original 25-item directive. It is reproduced here because
this document's sole purpose is preserving the directive's language, and an attested verbatim sentence
absent from it is a preservation gap. It is **not** one of the 25 numbered items and adds no new
requirement — §4 constraints 1 and 3 already carry its substance. It is retained for its force: it is
the single sentence that most directly bounds what Task #6 is permitted to be.

*(Recorded during Wave 1 verification, 2026-08-25. The gap was identified by the directive-verification
pass, which correctly declined to edit outside its own remit; the lead agent added it.)*

---

*Sources: in-namespace citations under `src/digital_twin/`, `src/visualization/`, `src/labels.py` and
`src/optimization/recommendation.py`; `docs/PRD_Synthetic_Cement_Digital_Twin.md`;
`TASK6_RECOVERY_PLAN.md`; `configs/*.yaml`. Line numbers verified against commit `1f8107f`, except
where §1 item 15 gives a re-verified current-HEAD line.
No requirement in this document was invented. Gaps are marked UNRECOVERED; the single inferred entry
is marked RECONSTRUCTED and argues its own case (§1 item 15, added 2026-08-31).*
