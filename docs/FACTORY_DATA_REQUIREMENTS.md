# FACTORY_DATA_REQUIREMENTS.md

*Synthetic Cement Plant Digital Twin + AI Optimization Platform — Demonstration Environment (PRD v1.1.1)*

> **Synthetic Demonstration · Decision Support Only · Not validated against real plant data**

> "The synthetic model is a development and demonstration environment, not a calibrated
> representation of any specific cement plant."
> — PRD v1.1.1 Section 21.5, required standing statement (`src/labels.py:38`)

**Audience:** factory IT/OT engineers and plant managers (PRD §35, `docs/PRD_Synthetic_Cement_Digital_Twin.md:1119`).

**Source sections:** PRD §27 (Factory Data Requirements, `:971-993`), PRD §26 (Real Factory Data
Migration Strategy, `:942-969`), PRD §21 (Synthetic-to-Real Transfer Strategy, `:782-832`).
**Acceptance criterion:** AC-9 — "Factory Data Requirements view/document lists concrete tags the
factory would need to provide" (PRD `:1064`). Task #6 directive item 24 (`docs/TASK6_DIRECTIVE.md:413`).

---

## 0. What this document is, and what it is not

This is a **specification for a future integration**. It is the list of historical tags a cement
plant would have to supply so that `SyntheticDataProvider` (`src/digital_twin/synthetic.py`) could
be replaced by a working `RealPlantDataProvider` (`src/digital_twin/real_plant.py`).

Three statements govern everything below, and none of them is a formality:

1. **No plant connection exists.** This build reads no plant instrument, opens no historian, and
   writes no setpoint. `configs/tag_mapping.yaml` is deliberately unpopulated (`sources: {}`,
   `configs/tag_mapping.yaml:80`) and `RealPlantDataProvider` implements nothing —
   all fourteen of its data methods raise `NotImplementedError`
   (`real_plant.py:186, 197, 209, 217, 230, 248, 258, 270, 279, 291, 301, 311, 330, 341`).
2. **Nothing here has been validated against real plant data.** Every band in the tables below is a
   process-reasoned `ASSUMPTION` from PRD §12, declared in `src/schema.py` with `assumption=True`
   on every numeric row (`src/schema.py:9-11`). They are *starting points and sanity checks*, not
   measurements of any plant, and not limits any plant is expected to match.
3. **Supplying this data does not make the system valid on that plant.** A populated tag mapping
   makes real data *readable*; it does not make a synthetically-trained Model A, B or C *correct*.
   PRD §21.4 (`:809-832`) puts data-quality assessment, plant-specific recalibration of every
   `ASSUMPTION`, retraining and real-plant validation between "real data arrives" and any number
   being believed. `real_plant.py:79-98` repeats that ordering in every refusal message it emits.

**This document invents no tag.** Every canonical tag name, unit, role and band below is read from
`src/schema.py` (which PRD §27/FR-18 names as the source the document is derived from,
`src/schema.py:5-7`). No plant tag name appears anywhere, because none is known — that is exactly
the column the factory fills in.

---

## 1. What we are asking for, in one paragraph

Historical data from your historian / DCS / SCADA for the **kiln line and cement mill**, covering the
tags in §5, at whatever native resolution each tag is actually stored at, exported in whatever format
your system already produces (CSV, SQL, PI/AVEVA-style historian export, or an OPC-UA endpoint).
Several months is preferred where available (PRD §27.3, `:991`). Alongside it, two lab/engineering
items that no historian tag can substitute for: **fuel LHV lab results on a single MJ basis**, and
**step-test or transient logs** where a known setpoint change was recorded (§6). We do not need
1-second data for everything and we do not assume you have it — the system resamples downward and
refuses to resample upward (`src/digital_twin/provider.py:188-206`).

---

## 2. Connection profiles we can accept

`RealPlantDataProvider.__init__` accepts one connection profile (PRD §26.1, `real_plant.py:106-136`).
The kinds and the keyword each one carries are declared in `real_plant.py:61-68`:

| `kind` | Carried as | What it points at (PRD §26.2, `:966`) |
|---|---|---|
| `csv` | `path` | a directory or file of historian CSV exports |
| `dcs` | `path` | a DCS export location |
| `scada` | `path` | a SCADA export location |
| `historian` | `path` | an AVEVA/PI-style export location |
| `sql` | `dsn` | a database connection string |
| `opcua` | `endpoint` | an OPC-UA server URL |

Each becomes a thin adapter behind the same `DataProvider` contract. Nothing above the provider
changes when one is added — that is FR-14, and it is why the request can be answered in your native
export format rather than ours.

**No credentials are requested by this document.** OT/IT integration and cybersecurity review are
named as separate prerequisites in the PRD §31 limitations statement (`src/labels.py:44-51`) and are
out of scope here.

---

## 3. Sampling, resolution and history depth

| Item | What the system expects | Source |
|---|---|---|
| Resample targets accepted | `1s`, `5s`, `10s`, `30s`, `1min`, `5min` | `provider.py:42` (`RESAMPLE_RULES`), PRD §26.3 / FR-20 |
| Upsampling | **Refused.** A rule finer than the source's own sampling interval raises rather than interpolating: "upsampling would invent samples that were never measured" | `provider.py:201-205` |
| Native interval of the synthetic reference | 1 min for every tag | `src/schema.py:60` (`sampling_interval` default), PRD §12.1/12.2 |
| Per-source native interval | Declared per profile as `native_interval_seconds` | `configs/tag_mapping.yaml:70` |
| Preferred history depth | Several months where available | PRD §27.3 (`:991`) |
| Timezone | UTC assumed; declare `timezone:` per profile if the native stamps are not UTC | `configs/tag_mapping.yaml:69` |

`ASSUMPTION` (this document): where a real tag's native interval is coarser than another tag's, they
are aligned by resampling to the coarsest rule that satisfies every requested tag, because
`check_resample` refuses the alternative. This alignment rule is *not* implemented — it is a
specification for the adapter that does not exist yet.

---

## 4. The fourteen methods, and what each one needs from you

`RealPlantDataProvider` satisfies the 15-method `DataProvider` contract
(`src/digital_twin/provider.py:58-218`) structurally: every abstract method is present, so Python
instantiates the class and a dashboard gets a clear refusal rather than an `AttributeError`
(`real_plant.py:13-18`). One method — `capabilities()` — answers today, reporting every capability
`False` so a view degrades instead of failing (`real_plant.py:139-176`). The other **fourteen raise**.

Each subsection below is one of those fourteen: what the method would do, what data that needs, at
what granularity, and what degrades on the dashboard if the data is absent. The "what it would do"
text is the method's own TODO message, not a restatement invented here.

### 4.1 `get_timeseries(tags, start, end, resample=None)` — `real_plant.py:179`

- **Would do:** read your own tags for `[start, end]` from the configured source, rename them to the
  PRD §12 schema, and resample to one of the PRD §26.3 targets "since a real historian will not hold
  every tag at 1-minute resolution" (`real_plant.py:189-192`).
- **Needs:** the bulk historical export itself — the §5 tags over the requested window, timestamped.
- **Granularity:** native; the system resamples down. One of `1s/5s/10s/30s/1min/5min`.
- **Absent:** this is the foundational read. Without it there is no history, no model retraining
  corpus and no replay — every downstream method in this section is blocked.

### 4.2 `get_tag_metadata()` — `real_plant.py:196`

- **Would do:** return one row per available tag with **the plant's own** unit, description, expected
  range and native sampling interval — "the plant's metadata, not the synthetic schema's, because a
  real instrument's range is a fact about that instrument" (`real_plant.py:200-204`).
- **Needs:** your instrument list: tag name, engineering unit, description, the instrument's own
  calibrated range, and its stored sampling interval.
- **Granularity:** static, one row per tag. No time series.
- **Absent:** every displayed value loses its unit and its range. Because a panel reads range and
  status off the `Value` the provider attaches (`src/digital_twin/provenance.py:16-19`) and holds no
  limit of its own, missing metadata means no alarm banding and no animation scaling at all — not
  wrong scaling.

> **This is the single most important row of the request.** The bands in §5 are ours and are
> `ASSUMPTION`s; the bands in *your* metadata are facts about your instruments, and they replace
> ours rather than being checked against them.

### 4.3 `get_current_state(dataset=None)` — `real_plant.py:208`

- **Would do:** "read the newest row of each mapped tag and return it in the observable channel"
  (`real_plant.py:212`).
- **Needs:** the newest available sample of each mapped tag. Not a live feed — the newest *stored*
  row is sufficient and is what a historian export gives.
- **Granularity:** one row, newest timestamp, native interval.
- **Absent:** **nothing renders at all.** This is the hard floor, and it is stricter than the
  contract's other capabilities. Verified in this repo: `Clock.__init__` calls
  `provider.get_current_state().timestamp` unconditionally (`src/visualization/clock.py:141`), and
  `DashboardState.frame()` calls it unguarded (`src/digital_twin/state.py:546-551`). Constructing a
  dashboard around a provider that refuses this method raises before any view is built.

### 4.4 `get_truth_state(dataset=None)` — `real_plant.py:216`

- **Would do:** *nothing — "and it never will."* The method's own message is the clearest statement in
  the module and is worth quoting in full (`real_plant.py:220-226`):

  > "A real plant has no noise-free channel: there is no simulator behind it holding the true value,
  > only instruments with error. This method exists on the contract because a synthetic source can
  > honour it, and a real source must refuse it rather than return its measurements relabelled as
  > truth (that relabelling is exactly what PRD 20's evaluation-against-truth tests would silently
  > lose)."

- **Needs:** **nothing. This is not a request.** No plant can supply a noise-free channel, and the
  `TRUTH` provenance channel (`src/digital_twin/provenance.py:5`) is permanently unavailable on real
  data. It is listed here only so its absence is understood as designed rather than as a gap.
- **Absent:** correct behaviour. `capabilities().truth = False` (`real_plant.py:154`) and any
  truth-vs-observed comparison is simply not offered.

### 4.5 `get_sensor_values(tags)` — `real_plant.py:229`

- **Would do:** "return the named readings at the newest timestamp, each with the plant's unit and
  range and a **status banded against the plant's own limits**" (`real_plant.py:233-235`).
- **Needs:** two things beyond the readings — your engineering unit per tag (see §4.2) **and your own
  operating/alarm limits per tag**. The demonstration bands its colours as a fraction of a
  variable's documented span (`configs/dashboard.yaml:23`, `:25`), never against a limit written into
  a panel; on real data the limits must be yours.
- **Granularity:** one value per requested tag, newest timestamp.
- **Absent:** values can still be shown but carry no status. A panel will not substitute a limit —
  `configs/tag_mapping.yaml:22-26` records the reasoning: a mapping file that also carried ranges
  "would give a plant two contradictory authorities for the same band."

### 4.6 `get_history(tags, minutes=…, start=…, end=…, max_points=…, truth=False)` — `real_plant.py:238`

- **Would do:** "return downsampled trends for the UI's point budget — a real historian window is far
  larger than a chart can draw, so the downsampling of directive item 23 matters more here than it
  does for a synthetic run, not less" (`real_plant.py:251-253`).
- **Needs:** the same export as §4.1, queryable by tag and window.
- **Granularity:** whatever is stored; the system downsamples to its configured budget before
  display — `history.max_points: 600` and `sparkline_points: 60`
  (`configs/dashboard.yaml:41-42`, both marked `ASSUMPTION`), method `minmax` "preserves excursions
  a plain mean would hide" (`configs/dashboard.yaml:45`).
- **Absent:** **clean, verified degradation.** `capabilities().history = False` makes
  `DashboardState._history` return an empty tuple (`state.py:535-541`), so every trend and every KPI
  sparkline renders empty. No screen fails, and no flat line is drawn from zero-filled data.

### 4.7 `get_equipment_status()` — `real_plant.py:257`

- **Would do:** "report each component's state from the plant's own running/stopped signals"
  (`real_plant.py:261`). The method then flags a genuine mismatch that a tag mapping cannot fix
  (`real_plant.py:262-266`): PRD §9.5's **health scalar has no real-plant equivalent to read** — it is
  a simulation *input*, so on a real plant equipment condition "has to be derived from measurements
  (vibration, bearing temperature, drive current) and calibrated per plant — a PRD 21.4
  recalibration item, not a mapping item."
- **Needs:** (a) running/stopped or drive-status signals for the nine PRD §8.3 components
  (`src/digital_twin/layout.py:242`, "Nothing may be added: a piece of equipment on a screen that the
  twin does not model would be a claim about a plant we do not simulate"); (b) the condition
  measurements the health derivation would be built from — `vibration`, `bearing_temperature`,
  `kiln_motor_current`, `ID_fan_current`, `mill_vibration`, `mill_current`, `separator_current`;
  (c) the line-throughput tags that answer "is this line running at all" — `kiln_feed_rate_tph` and
  `mill_feed_rate_tph` (`layout.py:210-213`).
- **Granularity:** native interval; status signals at whatever rate they are logged.
- **Absent:** `frame()` calls this unguarded (`state.py:548`), so like §4.3 it blocks every view. The
  four equipment states the twin can show are `RUNNING / IDLE / DERATED / UNKNOWN`
  (`src/labels.py:163-173`), and `UNKNOWN` is the documented honest answer when a component's driving
  reading is absent — "a missing number is stated, never replaced by an assumed one."

### 4.8 `get_kpis()` — `real_plant.py:269`

- **Would do:** "compute the kiln, mill and plant KPI groups from mapped tags, keeping specific and
  total energy shown together as PRD 18.1 requires" (`real_plant.py:273-275`).
- **Needs:** no new tags — the KPI groups are computed from tags already in §5. The exact sets are
  declared once, in `src/digital_twin/layout.py:114-140`:
  - **Kiln:** `kiln_fuel_rate_tph`, `thermal_energy_kcal_per_kg_clinker`, `specific_fuel_consumption`,
    `burning_zone_temperature`, `oxygen_percent`, `clinker_production_tph`
  - **Cement mill:** `mill_motor_power_kw`, `specific_power_consumption_kwh_t`, `mill_feed_rate_tph`,
    `simulated_blaine_cm2_g`, `residue_percent`, `mill_differential_pressure`
  - **Plant:** `thermal_energy_kcal_per_kg_clinker`, `specific_power_consumption_kwh_t`,
    `clinker_production_tph`, `cement_production_tph`
- **Granularity:** derived per row from the tags above.
- **Absent:** `frame()` calls this unguarded (`state.py:549`) — blocks every view.
- **Note on honesty, not on data:** directive item 12 is explicit that "the dashboard must NOT show
  only the favorable metric" (`src/labels.py:175`). Specific energy can fall while the daily total
  rises because production rose, so each specific figure is paired with the total it implies
  (`layout.py:169-193`). If your plant has **section-level kWh meters**, they are requested in §6 —
  they would let the total be *measured* rather than implied.

### 4.9 `get_operating_regime()` — `real_plant.py:278`

- **Would do:** "report which operating regime the plant is in. On the synthetic source this is a
  configured label read straight from the scenario schedule; on a real plant there is no such label
  to read, so it has to be derived from the operating point and **agreed with the plant's own
  operating definitions** — a PRD 21.4 calibration item" (`real_plant.py:282-287`).
- **Needs:** not a tag. A **written definition, from your process engineers, of what your operating
  regimes are** and which measurable conditions distinguish them. The schema's own
  `operating_regime` column is simulation ground truth and is marked as such: "a real plant would not
  supply this" (`src/schema.py:203-205`).
- **Granularity:** definitions are static; the derived label would be per row.
- **Absent:** `frame()` calls this unguarded (`state.py:550`) — blocks every view.

### 4.10 `get_anomaly_state(dataset="kiln")` — `real_plant.py:290`

- **Would do:** "run Model B on the current row — **after Model B has been retrained on this plant's
  normal-regime history.** A detector whose control limits came from simulated data would flag this
  plant's ordinary behaviour as anomalous" (`real_plant.py:294-296`).
- **Needs:** a curated window of **normal operation** from your history, long enough to fit the
  detector — plus, ideally, your maintenance/event log so real fault episodes can be identified. PRD
  §21.3 records why the synthetic run cannot stand in: "real anomaly base rates, false-positive rates,
  or fault signatures — real sensor/equipment failure modes differ from the simplified fault
  injection of Section 11.4" (PRD `:805`).
- **Granularity:** several months at native interval; the normal window identified by you, not
  guessed by us. The schema's `injected_fault` column is simulation ground truth and is not requested
  (`src/schema.py:206-208`).
- **Absent:** `capabilities().anomaly = False`; the AI Prediction & Anomaly screen (view H) shows
  "Model not available" and the statement "This panel needs a trained model that is not present in
  this session … the panel shows no number rather than a substitute one"
  (`src/labels.py:101-105`). Where a detector runs but its evidence does not separate the readings,
  the display is **"Evidence inconclusive"** (`src/labels.py:83`) rather than an invented diagnosis —
  which is also how sensor drift is reported.

### 4.11 `get_predictions(dataset="kiln")` — `real_plant.py:300`

- **Would do:** "run Model A's horizon models on the current row — **after retraining on this plant's
  data.** A synthetic-trained Model A would be predicting the simulation's dynamics, including its
  per-relationship delay `ASSUMPTION`s, not this plant's" (`real_plant.py:304-307`).
- **Needs:** enough continuous history to build lag features and label every configured horizon. The
  demonstration's horizons are 5/10/15/30 min (FR-5, PRD `:98`), and its features are current values
  plus lags of 1/5/15 min (`MODEL_CARD.md`, Model A feature description). A history whose gaps are
  longer than the longest lag cannot produce a training row there.
- **Granularity:** native interval, continuous. Gaps and duplicate timestamps matter more than
  absolute resolution — they are exactly what the FR-13 data-quality report checks
  (`src/data_processing/quality.py`), and PRD §21.4 re-runs that report on real data as the *first*
  step after delivery.
- **Absent:** `capabilities().predictions = False`; view H's prediction panel shows the
  "Model not available" state (`src/labels.py:101-105`).
- **On uncertainty:** predictions are shown with an **ensemble spread**, and the recommendation
  quality is a category — `HIGH` / `MEDIUM` / `LOW` (`src/labels.py:120-146`). FR-23 and AC-18 forbid
  displaying a numeric confidence percentage, and `src/digital_twin/insights.py:8-11` records that
  there is "no confidence-percentage field anywhere" in the payload. Nothing in this request would
  change that.

### 4.12 `get_optimization(mode="NORMAL")` — `real_plant.py:310`

- **Would do:** "run Model C at the current operating point." The method names itself as the most
  dangerous of the fourteen, and the wording is worth preserving (`real_plant.py:314-319`):

  > "This is the method to be most careful with: the optimizer's envelope, hard-constraint and OOD
  > gates are calibrated against the synthetic plant, so on real data they would be gating against the
  > wrong limits while still producing confident-looking setpoint advice. PRD Section 30's safety
  > constraints and the operator-validation step of PRD 21.4 both stand between this method and any
  > real recommendation."

- **Needs:** not tags — **your engineering limits.** Specifically: the hard process/safety constraints
  that must never be traded away (PRD §14.2/§30), and the operating envelope within which your
  process engineers consider advice meaningful. Both must be supplied and agreed, not inferred from
  the history.
- **Granularity:** static, per manipulated variable, with the rationale for each (NFR-11 requires
  every optimization decision variable to have a documented range, step size, hard constraint and
  rationale — PRD `:135`).
- **Absent:** `capabilities().optimization = False`; view J shows no recommendation. "No safe
  recommendation found" is a first-class displayable outcome and constraints are never relaxed to
  manufacture advice (`src/labels.py:67-70`).
- **Standing caveat, unchanged by any data delivery:** every reported saving carries
  "Simulated saving from a synthetic model - not a guaranteed real-world saving"
  (`src/labels.py:75-77`), every AI output is labelled "AI Recommendation" and "Decision Support
  Only", and the phrase "Automatic Control Command" is forbidden system-wide and asserted against by
  tests (`src/labels.py:29-33`, FR-16, PRD §30). The system writes no setpoint.

### 4.13 `run_what_if(changes=…, delta_fractions=…, mode="NORMAL")` — `real_plant.py:323`

- **Would do:** "answer an operator what-if by simulating the change. This needs a **calibrated
  process model of this plant**, not a tag mapping: the answer comes from the twin, so it is only as
  valid as that twin's fit to this plant (PRD 21.4 plant-specific calibration)"
  (`real_plant.py:333-337`).
- **Needs:** the highest-value non-historian item in this whole request — **step-test / transient
  logs**: recorded responses to a known setpoint change. PRD §27.3 asks for them explicitly as
  "high-value input for calibrating the per-relationship delay parameters of Section 9.4/10.3"
  (PRD `:991`), and `src/schema.py:386-393` carries the same ask as a structured
  `FutureDataRequest`. Also needed: the raw-mix chemistry and a cooler/thermal survey if the
  energy-balance fractions are to be recalibrated rather than left as `ASSUMPTION`s (see
  `SIMULATION_ASSUMPTIONS.md` §2, whose calibration notes name the measurement that would replace
  each constant).
- **Granularity:** per step test — the setpoint move, its timestamp, and the affected measurements at
  the finest resolution available through the settling period. A move logged only at 5-minute
  resolution cannot resolve a dead time shorter than 5 minutes.
- **Absent:** `capabilities().what_if = False`; view I offers no scenario evaluation.
- **Why this is not a mapping item:** every delay in the twin is a documented `ASSUMPTION`
  (NFR-8, PRD `:132`), and PRD §21.3 lists "any claim of plant-specific calibration" among the things
  the synthetic environment does **not** validate (PRD `:798-802`). Without step-test data the delays
  stay assumptions no matter how many tags arrive.

### 4.14 `what_if_sliders(mode="NORMAL")` — `real_plant.py:340`

- **Would do:** "return each manipulated variable's slider bounds and step, taken from this plant's
  own operating limits **as agreed with its process engineers — never from the synthetic configs**"
  (`real_plant.py:344-347`).
- **Needs:** for each of the **12 manipulated variables** (`src/schema.py`, via
  `schema.manipulated_variables()`): the operator-adjustable range, the step size the DCS actually
  uses, and any hard constraint. The twelve are `kiln_feed_rate_tph`, `kiln_fuel_rate_tph`,
  `calciner_fuel_rate_tph`, `kiln_speed_rpm`, `ID_fan_speed`, `mill_feed_rate_tph`,
  `clinker_feed_rate`, `gypsum_feed_rate`, `additive_feed_rate`, `mill_speed`,
  `separator_speed_rpm`, `fan_speed`.
- **Granularity:** static, one row per variable.
- **Absent:** no sliders are offered. This is the cleanest illustration of the whole document's
  point: the demonstration's slider bounds come from `src/schema.py` and the units' own `constraints`
  blocks in `configs/kiln_dynamics.yaml` / `configs/mill_dynamics.yaml`, and directive item 13 forbids
  inventing ranges. On your plant those numbers are yours, and until they are supplied the control
  cannot be drawn honestly.

### 4.15 The one method that answers today — `capabilities()` — `real_plant.py:139`

Not a request; included so the set of fifteen is complete. It returns every capability `False` with a
`missing` tuple of thirteen names (`real_plant.py:161-175`) so that a view "degrades every panel
instead of failing". Note `synthetic=False` is the honest answer for a real source and is what stops
the header printing the synthetic-data banner for it — "It does not mean real numbers are available -
none are" (`real_plant.py:147-149`).

**Coverage note:** thirteen `missing` names cover fourteen methods, because `what_if_sliders` is
reported under the same `what_if` capability as `run_what_if`.

---

## 5. The concrete tag list (AC-9)

This section is the actual data request. Every row below is generated from `src/schema.py` - the same
schema the synthetic generator uses to produce its columns - so the canonical names, units, bands,
roles and importance levels in this document and in the running code cannot drift apart. FR-18 states
the requirement plainly: this document is "auto-derived from the same schema used for synthetic tags"
(PRD `:111`), and `src/schema.py:5-7` names itself as "the contract three things share: what the
simulator writes, what the models expect, and what a factory would have to supply".

**How to read the table.**

- **Canonical tag** - the internal name. Your DCS name will differ; that is what
  `configs/tag_mapping.yaml` is for. Map `your_plant_tag -> canonical_name` there; nothing in the code
  needs renaming.
- **Description / Unit** - what the number means and the unit the code expects. If your historian
  exports a different unit, say so; do not pre-convert silently. Two units are already known
  conversions rather than raw measurements: `NOx_ppm` is "converted from mg/Nm3, ASSUMPTION conversion
  factor", and `thermal_energy_kcal_per_kg_clinker` is a "display-unit derivation of the canonical MJ
  energy balance".
- **Documented band (`ASSUMPTION`)** - the range this demonstration works within. **Every band on this
  page is an `ASSUMPTION`**: `src/schema.py:9-11` records that the ranges are "documented plant
  ASSUMPTIONs, not measurements", and all 56 rows below carry `assumption=True`. Read them as
  "roughly the region the demo was built for", never as a specification your plant must satisfy. If
  your plant runs outside a band, the band is wrong for your plant - the plant is not wrong. Tell us
  the real one; the system has an explicit `OUTSIDE_ENVELOPE` state for operating points beyond what
  it was built for (`src/labels.py:59`).
- **Role** - `manipulated` (an operator/DCS setpoint), `process`, `quality` (usually a lab result),
  `emission`, `equipment`, `disturbance` (arrives from upstream, not chosen), `derived` (computed from
  others, so it can be recomputed if you cannot export it).
- **Importance / Mandatory** - `critical` tags are needed for the core path; `important` ones enable
  specific panels; `optional` ones are nice to have. Only three tags in the whole schema are
  non-mandatory: `NOx_ppm`, `SO2_ppm` and `specific_fuel_consumption`. The last is a deliberate
  duplicate "kept for factory-familiar naming" of `thermal_energy_kcal_per_kg_clinker` - supply
  whichever your plant actually records.
- **Dataset** - `kiln` or `mill`. The two are separate exports and can be supplied independently; a
  kiln-only delivery leaves the mill views degraded rather than broken.

**Totals.** 56 requestable tags: 25 `critical`, 28 `important`, 3 `optional`; 12 of them are
manipulated variables. (The schema holds 62 rows in total; the six not listed here are the timestamp
index and the two ground-truth label columns per dataset — `operating_regime` and `injected_fault` —
which no factory can supply and which are exactly the
`TRUTH` channel a real deployment does without - see 4.4.) Every row's declared sampling interval in
the schema is `1 min`; see section 3 for what the code will accept instead.

**A blank column you should add.** Copy this table, add one column headed *"our tag name / our unit /
not available"*, and fill it in. A row marked *not available* is a useful answer - it tells us which
panel to degrade rather than which number to guess.

#### Kiln - 16 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `kiln_feed_rate_tph` | Raw meal feed to kiln system | t/h | 150 - 230 | manipulated | critical | yes | kiln |
| `kiln_speed_rpm` | Kiln rotation speed | rpm | 2.8 - 4.5 | manipulated | critical | yes | kiln |
| `raw_meal_moisture` | Raw meal residual moisture | % | 0.3 - 1 | disturbance | important | yes | kiln |
| `raw_meal_temperature` | Raw meal feed temperature | C | 40 - 90 | disturbance | important | yes | kiln |
| `kiln_inlet_pressure` | Kiln inlet draught pressure | mbar | -8 - -2 | process | important | yes | kiln |
| `burning_zone_temperature` | Burning zone (pyrometer/model) | C | 1400 - 1500 | process | critical | yes | kiln |
| `kiln_inlet_temperature` | Material temp at kiln inlet | C | 800 - 950 | process | important | yes | kiln |
| `oxygen_percent` | O2 at kiln inlet/back-end (dry) | % | 0.7 - 4 | process | critical | yes | kiln |
| `CO_ppm` | CO at kiln inlet/back-end | ppm | 0 - 300 | emission | critical | yes | kiln |
| `CO2_percent` | CO2 at kiln inlet/back-end | % | 28 - 36 | emission | important | yes | kiln |
| `NOx_ppm` | NOx (converted from mg/Nm3, ASSUMPTION conversion factor) | ppm | 250 - 900 | emission | optional | NO | kiln |
| `SO2_ppm` | SO2 at stack | ppm | 10 - 400 | emission | optional | NO | kiln |
| `clinker_production_tph` | Clinker output rate | t/h | 95 - 150 | process | critical | yes | kiln |
| `kiln_motor_current` | Kiln main drive current | A | 80 - 180 | equipment | important | yes | kiln |
| `vibration` | Kiln drive/support vibration (generic) | mm/s | 1 - 8 | equipment | important | yes | kiln |
| `bearing_temperature` | Kiln support roller bearing temperature | C | 45 - 75 | equipment | important | yes | kiln |

#### Preheater - 3 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `preheater_pressure` | Preheater tower pressure | mbar | -25 - -10 | process | critical | yes | kiln |
| `exhaust_gas_flow` | Stack/preheater exhaust flow | Nm3/h | 250000 - 400000 | process | important | yes | kiln |
| `preheater_outlet_temperature` | Top-stage cyclone exit temperature | C | 280 - 380 | process | critical | yes | kiln |

#### Precalciner - 2 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `tertiary_air_flow` | Tertiary air flow to calciner | Nm3/h | 60000 - 100000 | process | critical | yes | kiln |
| `calciner_temperature` | Precalciner outlet temperature | C | 850 - 900 | process | critical | yes | kiln |

#### Cooler - 5 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `secondary_air_flow` | Secondary air flow from cooler | Nm3/h | 90000 - 140000 | process | important | yes | kiln |
| `secondary_air_temperature` | Secondary (cooler recuperated) air temp | C | 800 - 1000 | process | important | yes | kiln |
| `cooler_outlet_temperature` | Clinker cooler discharge temperature | C | 80 - 150 | process | important | yes | kiln |
| `clinker_temperature` | Clinker discharge temperature | C | 80 - 150 | process | important | yes | kiln |
| `cooler_fan_power` | Cooler fans total power | kW | 400 - 1100 | equipment | important | yes | kiln |

#### Fuel - 4 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `kiln_fuel_rate_tph` | Main kiln burner fuel rate (solid/liquid, MJ/kg basis) | t/h | 3.2 - 5.2 | manipulated | critical | yes | kiln |
| `calciner_fuel_rate_tph` | Precalciner fuel rate (solid/liquid, MJ/kg basis) | t/h | 4 - 7.5 | manipulated | critical | yes | kiln |
| `thermal_energy_kcal_per_kg_clinker` | Specific thermal energy - display-unit derivation of the canonical MJ energy balance (PRD 9.2/9.3) | kcal/kg | 700 - 950 | derived | critical | yes | kiln |
| `specific_fuel_consumption` | Duplicate/derived, kept for factory-familiar naming | kcal/kg | 700 - 950 | derived | optional | NO | kiln |

#### Fans - 6 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `primary_air_flow` | Primary air flow to main burner | Nm3/h | 15000 - 25000 | process | important | yes | kiln |
| `ID_fan_speed` | ID fan speed | % | 60 - 95 | manipulated | critical | yes | kiln |
| `ID_fan_power` | ID fan motor power | kW | 900 - 2200 | equipment | important | yes | kiln |
| `ID_fan_current` | ID fan motor current | A | 100 - 260 | equipment | important | yes | kiln |
| `fan_speed` | Main/circulation fan speed | % | 60 - 100 | manipulated | important | yes | mill |
| `fan_power_kw` | Main fan power | kW | 400 - 1200 | equipment | important | yes | mill |

#### Cement Mill - 17 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mill_feed_rate_tph` | Total mill feed | t/h | 80 - 170 | manipulated | critical | yes | mill |
| `clinker_feed_rate` | Clinker component of feed | t/h | 70 - 150 | manipulated | critical | yes | mill |
| `gypsum_feed_rate` | Gypsum component of feed | t/h | 3 - 8 | manipulated | important | yes | mill |
| `additive_feed_rate` | Additive/limestone component | t/h | 0 - 20 | manipulated | important | yes | mill |
| `mill_motor_power_kw` | Main mill motor power | kW | 2500 - 5500 | process | critical | yes | mill |
| `mill_current` | Main motor current | A | 200 - 420 | equipment | important | yes | mill |
| `mill_pressure` | Mill internal pressure (VRM) / shell pressure proxy | mbar | -40 - -10 | process | important | yes | mill |
| `mill_differential_pressure` | Mill dP (loading indicator) | mbar | 20 - 90 | process | critical | yes | mill |
| `mill_outlet_temperature` | Material/gas outlet temperature | C | 90 - 120 | process | important | yes | mill |
| `mill_vibration` | Mill body vibration | mm/s | 1 - 10 | equipment | important | yes | mill |
| `mill_speed` | Mill rotational/table speed | rpm | 12 - 18 | manipulated | important | yes | mill |
| `gas_flow` | Circulating gas flow | Nm3/h | 150000 - 260000 | process | important | yes | mill |
| `cement_production_tph` | Net finished-product rate | t/h | 75 - 160 | process | critical | yes | mill |
| `product_temperature` | Finished product temperature | C | 85 - 115 | process | important | yes | mill |
| `simulated_blaine_cm2_g` | Fineness (Blaine surface area) | cm2/g | 2900 - 4200 | quality | critical | yes | mill |
| `residue_percent` | 45 um sieve residue | % | 6 - 18 | quality | critical | yes | mill |
| `specific_power_consumption_kwh_t` | Specific electrical energy | kWh/t | 26 - 45 | derived | critical | yes | mill |

#### Separator - 3 tags

| Canonical tag | Description | Unit | Documented band (ASSUMPTION) | Role | Importance | Mandatory | Dataset |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `separator_speed_rpm` | Dynamic separator rotor speed | rpm | 60 - 140 | manipulated | critical | yes | mill |
| `separator_current` | Separator motor current | A | 30 - 80 | equipment | critical | yes | mill |
| `separator_pressure` | Separator inlet/outlet pressure | mbar | -15 - -5 | process | critical | yes | mill |

### 5.1 Tags that are deliberately absent

The schema has no tag for raw-mix chemistry (LSF/SR/AR), no clinker free-lime measurement, no
raw-mill circuit, and no per-section electrical meter. Those are not oversights; the first two would
change what the twin claims to model, and the last two are listed as future requests in section 6.
The demonstration also has no `Raw Mill` process unit at all - the eight units above are the whole of
it. Do not read this list as a description of a complete cement plant; it is the subset this
demonstration simulates.

---

## 6. Four items no historian tag can substitute for

These are declared in the schema itself as `FUTURE_DATA_REQUESTS` (`src/schema.py:360-394`) and in
PRD §27.2. They are listed separately because each one replaces an `ASSUMPTION` that no amount of
process history can replace.

| Request | What it is | Unit / form | Importance | What `ASSUMPTION` it retires |
|---|---|---|---|---|
| `fuel_lhv_lab_results` | Lab calorific value (LHV) per fuel stream, **on a single MJ basis** | MJ/kg solid or liquid, MJ/Nm3 gas | `critical` | "Replaces the `lhv_solid_fuel_MJ_per_kg` / `lhv_gas_fuel_MJ_per_Nm3` ASSUMPTIONs of PRD 9.2 with measured values." |
| `step_test_transient_logs` | Logged responses to known setpoint changes (step tests / transients) | per test, finest available resolution through settling | `important` | "High-value input for calibrating the per-relationship dead-time + lag parameters of PRD 9.4/10.3 (PRD 27.3)." |
| `section_electrical_energy_meters` | Total plant and per-section electrical energy meters | kWh | `important` | "Optional, high value: enables plant-wide electrical optimization to be validated later (PRD 27.2)." Not in the v1.1 schema. |
| `raw_mill_circuit_tags` | Raw mill / raw meal preparation circuit tags | as per your historian | `optional` | Nothing yet — "Out of scope in v1.1 (PRD 5.2); listed so the factory knows it will eventually be requested (PRD 27.2, roadmap PRD 32)." |

**Why the "single MJ basis" wording matters.** Fuel energy is the one place where a plant's own
reporting convention (kcal/kg, GCV vs. NCV, as-received vs. dry) changes the number materially. The
demonstration carries a single canonical MJ energy balance and derives the kcal/kg display from it
(`thermal_energy_kcal_per_kg_clinker`, see §5). Send the lab basis along with the value; do not
convert to match this document.

**Why step tests are asked for at all.** Every process delay in the twin is a documented `ASSUMPTION`
(NFR-8). A step test is the only supplied artefact that can turn one into a measurement. Without them,
`run_what_if` (§4.13) stays uncalibrated no matter how many months of steady-state history arrive —
steady-state data constrains the *gains*, not the *dynamics*.

---

## 7. What happens after the data arrives

Mapping tags is step one of seven, and the six that follow are not built. PRD §21.4's transition path
(`:804-832`) is:

```
Synthetic Process Model
        ↓
Synthetic Dataset
        ↓
Prototype Validation  (architecture, pipeline, interfaces - this PRD's scope)
        ↓
Real Plant Historical Data  (Section 26/27 - factory-provided)     <-- this document
        ↓
Data Quality Assessment  (Section 11.5-equivalent checks re-run on real data)
        ↓
Plant-Specific Calibration  (every ASSUMPTION in Sections 9-10, 13-14 recalibrated)
        ↓
Retraining  (Model A/B/C retrained on real data through the unchanged interfaces of Section 13.4)
        ↓
Real-Plant Validation  (Section 20-equivalent tests re-run against real held-out data)
        ↓
Operator Validation
        ↓
Production Deployment  (out of scope for this PRD entirely - see Section 30, Safety Constraints)
```

Only the box marked `<-- this document` is what a factory is being asked for. The step below it is the
FR-13 data-quality report (`src/data_processing/quality.py`) re-run against real data; everything below
*that* is a project, not a config change.

The mechanical part — the part this document directly enables — is spelled out in
`configs/tag_mapping.yaml:28-41`:

1. The factory returns the tag list requested by this document, per process unit, in the plant's own
   words.
2. One `sources:` block is written per connection profile.
3. `RealPlantDataProvider` reads it and presents the plant behind the same `DataProvider` contract the
   synthetic source already satisfies — "switching providers is a one-line change, not a rewrite of
   the layers above" (FR-14).
4. "Everything downstream is then RECALIBRATED and RETRAINED on real data (PRD 21.4). **A tag mapping
   alone does not make a synthetic-trained model valid on a real plant**, and nothing in this file
   should be read as suggesting it does."

Two practical notes on step 2. Tags your plant does not have should be listed under `unavailable:`
rather than left out, "so a missing critical tag surfaces as a documented gap instead of an empty
column" (`configs/tag_mapping.yaml:75-78`). And the mapping file carries **no** ranges, units or
process limits by design — those stay in `src/schema.py` and in the units' own `constraints` blocks,
because "a mapping file that also carried ranges would give a plant two contradictory authorities for
the same band" (`configs/tag_mapping.yaml:22-26`).

### 7.1 What will still not be true after all seven steps

Stated plainly, because an admitted limitation is correct where a plausible overstatement is not:

- The system **writes no setpoint and closes no loop.** "Automatic Control Command" is forbidden
  vocabulary, asserted against in code (`src/labels.py:33`, FR-16, PRD §30). Every model output is an
  **AI Recommendation** under **Decision Support Only**, for a human to accept or reject.
- Every reported saving remains a *simulated* saving until validated on the plant itself:
  "Simulated saving from a synthetic model - not a guaranteed real-world saving"
  (`src/labels.py:75-77`).
- Uncertainty is reported as an **ensemble spread** plus a categorical `HIGH`/`MEDIUM`/`LOW` quality —
  never as a confidence percentage (FR-23, AC-18, `src/digital_twin/insights.py:8-11`).
- Where a detector's evidence does not separate the readings — sensor drift being the standard case —
  the display is **"Evidence inconclusive"** (`src/labels.py:83`), not a diagnosis.
- Operating points beyond what the models were fitted for are flagged `OUTSIDE_ENVELOPE`
  (`src/labels.py:59`) and may yield "No safe recommendation found" (`src/labels.py:70`). Constraints
  are never relaxed to produce advice.
- OT/IT integration, cybersecurity review, and the site-specific safety case are prerequisites that
  live entirely outside this repository (PRD §31 limitations statement, `src/labels.py:44-51`).

---

## 8. Where to reply, and the smallest useful answer

There is no intake endpoint in this build — nothing here uploads, transmits or stores plant data. The
deliverable this document expects is a filled-in copy of the §5 tables plus whatever of §6 exists,
handed to whoever is running the evaluation.

The **smallest useful answer** is not the whole list. It is:

1. The `critical` rows of §5 for **one** unit (kiln *or* mill), with your tag names and units.
2. The native resolution and timezone of that export.
3. A frank `unavailable` list.
4. If it exists at all: one step test.

That is enough to run the FR-13 data-quality report against real data, which is the first step of PRD
§21.4 and the only step this repository could actually perform today.

---

*Every band, interval and count on this page is read from `src/schema.py`, `src/digital_twin/`,
`configs/` or the PRD, at the line anchors given. No plant-specific figure appears anywhere in this
document, because none is known to this repository.*

> **Synthetic Demonstration · Decision Support Only · Not validated against real plant data**
