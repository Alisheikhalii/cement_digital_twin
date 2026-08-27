# WAVE 3D REPORT — PRD §35 documentation

**Task 6, Wave 3D.** Documentation only. One objective: write the two still-missing PRD §35
documents. No production file was touched.

| | |
|---|---|
| Branch | `task6/wave-3d` (off up-to-date `main` at `b2915e3`) |
| Files added | `docs/DATA_DICTIONARY.md`, `docs/DEMO_GUIDE.md`, `docs/WAVE3D_REPORT.md` |
| Files updated | `docs/PROJECT_STATE.md` |
| Production files touched | **none** |
| Frozen-layer digests | both unchanged — see §4 |

---

## 1. What was derived from `src/schema.py` vs. what needed a cross-reference

### 1.1 Derived mechanically from `schema.py` — and verified by execution, not by eye

Every row of both tag tables comes from the `TagSpec` records in `src/schema.py`. Nothing was
hand-invented. The columns `Tag`, `Process unit`, `Role`, `Unit`, `Documented range`, `Type`,
`Provenance`, `Importance` and `Notes` are one-to-one with the `TagSpec` fields `name`,
`process_unit`, `role`, `unit`, `range_min`/`range_max`, `dtype`, `assumption`, `importance` and
`notes`.

Because a 62-row hand transcription is exactly the kind of thing that silently drifts, the written
tables were **parsed back out of the markdown and compared against `src.schema` programmatically**:

| Check | Result |
|---|---|
| Row count and row order, kiln | doc 37 / schema 37 — **OK** |
| Row count and row order, mill | doc 25 / schema 25 — **OK** |
| `process_unit`, `role`, `dtype`, provenance, `unit` — all 62 rows | **0 mismatches** |
| `range_min` / `range_max` numeric values — all 62 rows | **0 mismatches** |

Also derived directly, with no interpretation:

- **62 columns total** (37 kiln + 25 mill), and the role distribution per dataset.
- **`sampling_interval` is `"1 min"` for all 62 tags** — so it is stated once in §1 rather than
  repeated as a dead column in every row.
- **56 tags carry `assumption=True`; 6 carry `assumption=False`** — and the six are exactly
  `timestamp`, `operating_regime`, `injected_fault` in both datasets.
- `DEBUG_BALANCE_COLUMNS` → §6, documented as debug-only and excluded from `columns_for()` by
  default.
- `FUTURE_DATA_REQUESTS` → §7, with each entry's stated criticality.

### 1.2 Needed a cross-reference outside `schema.py`

`schema.py` carries no energy conversion and no calibrated values, so these came from elsewhere and
are attributed in the document at the point of use:

| What | Source |
|---|---|
| Canonical-unit rule (all internal energy in MJ; kcal/kg is display-only) and `MJ_PER_KCAL = 4.184e-3` | PRD §9.2 + `src/units.py` |
| `lhv_solid_fuel_MJ_per_kg: 26.0`, `lhv_gas_fuel_MJ_per_Nm3: 36.0` | `SIMULATION_ASSUMPTIONS.md` §1 (repo **root**, not `docs/`) |
| `kiln_burner_fuel_share: 0.40`, `stoichiometric_air_Nm3_per_MJ: 0.26`, `combustion_CO2_Nm3_per_MJ: 0.047` | `SIMULATION_ASSUMPTIONS.md` §1 |
| Why mass-based and volume-based LHVs are never summed in native units | PRD §9.2 |
| The measured range deviations (§5) | `SIMULATION_ASSUMPTIONS.md` §8.1–§8.3 |
| Blaine / residue / production targets and the hard constraints | `configs/optimization.yaml` |
| The ranges-are-not-clamps rule | PRD §12 + the two tests that enforce it |
| PRD 10.4 fineness/throughput/power trade-off (§4.1) | PRD §10.4 |

**No number appears in `DATA_DICTIONARY.md` that is not already somewhere in the repo.** Every
`ASSUMPTION`-tagged value was checked back against `configs/` or `SIMULATION_ASSUMPTIONS.md`.

### 1.3 One thing the document says that the schema does *not*

`assumption=False` is easy to misread as "measured". It is not, and the dictionary says so
explicitly in §1.3: the flag means *"no process-reasoned numeric band"* — a clock, a regime label and
a fault label have no engineering range to justify. §1.3 and §9 both carry the standing statement
that **no column in either dataset is a measurement of a real plant.** This distinction was added
because the alternative reading would turn an honest synthetic dataset into a false claim of
instrumentation.

---

## 2. PRD-described capabilities flagged as not-yet-implemented

The directive required flagging rather than writing around. `DEMO_GUIDE.md` §9 carries the
consolidated list; §0 puts the three that change how you open the meeting up front. Ten items:

| # | PRD asks for | State today, as verified |
|---|---|---|
| 1 | Ten rendered dashboard screens (PRD 18) | **2 of 10 rendered** (B, E — the animated SVG twin). The other eight build correct view models, printed as JSON. |
| 2 | Live/interactive dashboard (PRD 19.1 loop) | **No loop, no server, no interactivity.** `app.py` writes one static self-contained HTML file. |
| 3 | Each demo as a single Colab cell (PRD 25 cell 11, §28) | **No `.ipynb` exists in the repo** (confirmed by glob). |
| 4 | Anomaly view's "Inject abnormal condition" control + `DemoInjector` (PRD 15, 28.3) | **Does not exist.** Named in a docstring and in PRD 23's tree; no such symbol. |
| 5 | **Experimental What-if Mode** reachable in the UI (PRD 16.1, 28.5) | **Implemented and tested in the view layer, not exposed.** `DashboardState.view()` passes only `frame`, so `mode` keeps its `"NORMAL"` default; `app.py` has no `--mode`. |
| 6 | Operator-set what-if changes (PRD 16.1) | **No CLI path.** No `--change` flag; CLI view I gets a null change set. |
| 7 | Before/after chart with visible transition delay (PRD 16.2) | **No chart.** Degrades through `missing_chart_html` by design — zero plotting dependencies. Numbers present, picture absent. |
| 8 | **Factory Presentation Mode** (PRD 29) | **Two config keys and a settings reader only.** No view id, no renderer, no KPI cards, no five-stage chain, no refresh loop. |
| 9 | "Run Demo" scripted sequence (PRD 28, directive item 19) | **Not built.** Each demo is run by hand. Reproducible, but not scripted. |
| 10 | An accurate `--skip-models` cost in `app.py`'s docstring | **Docstring says "~0.4 s"; measured 4.5 s.** Left uncorrected — this wave changed no production file. |

### 2.1 Three claims corrected by measurement rather than by reading

Writing the guide from code alone would have shipped three wrong statements. Each was caught by
running the thing:

1. **`--skip-models` costs ~4.5 s, not the ~0.4 s `app.py`'s own docstring advertises.** Two runs
   gave 4.517 s and 4.334 s, `load_frames` dominating. A ten-view build with the model layer on
   measured **21.0 s reported / 25.7 s wall clock** (`model_layer` 11.8 s; view J 5.1 s, I 2.2 s,
   H 1.4 s) and produced a **1.0 MB** HTML file. §0.4 now carries the measured table, plus the
   caveat that `load_frames` was **not stable** across runs (4.1 s, 3.0 s, 0.12 s) and should be
   re-timed locally rather than quoted.
2. **`WhatIfView` has no `headline` field.** The first draft of the §6.2 snippet called
   `normal.view.headline`; that property belongs to `OptimizationView` (view J). Running the snippet
   raised `AttributeError`. View I exposes `verdict`, `action`, `banner`, `notes` — the snippet now
   uses those and is reproduced with its real output.
3. **A −25 % request does not come back `PASS` in Experimental Mode.** This is the substantive one.
   Out-of-bound requests are **clipped, not refused**, and the measured verdict for −25 % is
   `REJECTED / OUTSIDE ENVELOPE` in **both** modes:

   | Request | Mode | Verdict | Banner | Header notices |
   |---|---|---|---|---|
   | −5 % fuel | `NORMAL` | `PASS / WITHIN ENVELOPE` | `None` | 3 |
   | −25 % fuel | `NORMAL` | `REJECTED / OUTSIDE ENVELOPE` | `None` | 3 |
   | −25 % fuel | `EXPERIMENTAL` | `REJECTED / OUTSIDE ENVELOPE` | low-reliability text | **4** |

   Experimental Mode widens the slider band and adds the mandatory banner; it does not make an
   aggressive cut acceptable. The PRD §28.5 script implies otherwise, so the guide says plainly:
   *if your slide says "Experimental Mode approves the aggressive change", change the slide.*

   Two further measured facts went into §6.2 because they will otherwise ambush a presenter:
   `absolute_range` from `schema.py` is a floor **neither** mode crosses (−25 % of 6.240 t/h is
   4.680 t/h, below the 4.975 t/h minimum, so Experimental clipped to 4.975 — −20.27 % — even with
   `enforce_envelope: false`); and the `action` string **lists every manipulated variable, not just
   the one you changed**, because the untouched ones are snapped onto the slider grid. Those are
   grid artefacts, not recommendations, and `notes` says which mechanism fired — snapping vs
   clipping — one line per variable.

The four-notice / three-notice contrast that §6.2 is built around **was confirmed** by execution:
Experimental adds *"Outside calibrated operating envelope — low reliability."* at the header, before
the result is read, and the payload carries its own `banner` too.

### 2.2 What Factory Presentation Mode actually is

PRD §29's ten elements are config keys only, matching `PROJECT_STATE.md` item 17. §7 of the guide
tabulates what exists (`presentation.refresh_seconds: 2.0`, `presentation.headline_decimals: 1`,
`PresentationSettings`, and `labels.presentation_card_label()` — used only for the twin badge)
against what does not (view id, renderer, KPI cards, five-stage chain, refresh loop), then gives a
plant-manager narrative that does **not** claim to be Presentation Mode.

One caution is called out separately: `refresh_seconds: 2.0` is an `ASSUMPTION` about a loop that
does not exist. It is **not** a PRD performance budget — NFR-2's *"what-if round trip under 3 s"* is
the real commitment. The guide says not to quote 2 s as a system response-time promise.

---

## 3. Files changed

| File | Change | Lines |
|---|---|---|
| `docs/DATA_DICTIONARY.md` | **added** | 369 |
| `docs/DEMO_GUIDE.md` | **added** | 685 |
| `docs/WAVE3D_REPORT.md` | **added** | this file |
| `docs/PROJECT_STATE.md` | **updated** — not rewritten | 4 edits |

**Nothing else.** No file under `src/`, `tests/` or `configs/` was modified, added or deleted.

`PROJECT_STATE.md` edits, precisely: the "last updated" pointer moved to Wave 3D; the Current
position table's branch / HEAD / wave-history / regression rows; the `DATA_DICTIONARY.md` and
`DEMO_GUIDE.md` rows flipped from *Missing* to **DONE**; the Item 17 row extended with where its true
extent is now documented; and **two new Open rows** for findings this wave surfaced — the `app.py`
docstring timing error, and Experimental What-if Mode being unreachable from any caller.

Three throwaway HTML files written to the gitignored `reports/` directory during verification
(`_verify_b.html`, `_verify_multi.html`, `_verify_all.html`) were deleted, as was the temporary
verification script. The working tree contains only the four documents above.

---

## 4. Regression result

```
537 passed in 310.33s (0:05:10)
```

**537 passed, 0 failed, 0 xfailed** — identical to the Wave 3C baseline recorded in
`PROJECT_STATE.md`. Regression floor is 428 (directive §4.7); this run is 109 above it. No test was
added, changed, skipped or removed, so the count *should* be unchanged, and it is.

### 4.1 No production drift — the stronger check

A passing suite shows behaviour is intact; the frozen-layer digests show the bytes are. Both were
re-verified after all edits and both match `PROJECT_STATE.md` exactly:

| Layer | Digest | Expected | |
|---|---|---|---|
| `src/models src/process_models src/optimization src/simulation src/features src/data_generation configs pyproject.toml` | `c7a1f54dd578900835596c02cb9a19a0` | `c7a1f54dd578900835596c02cb9a19a0` | ✅ |
| `tests/` excluding `task6` | `53f2aefec33494be5ca22c08ab22b5fd` | `53f2aefec33494be5ca22c08ab22b5fd` | ✅ |

Together with `git status` showing only the four documentation paths, this is conclusive: **Wave 3D
introduced zero production drift.** That is the expected outcome for a documentation-only wave, and
it is the reason the timing error in `app.py`'s docstring and the missing `--mode` flag were
*documented rather than fixed* — both are one-line production edits that belong to a wave that owns
`app.py`.

---

## 5. Branch and git status

| | |
|---|---|
| Branch | **`task6/wave-3d`**, created off up-to-date `main` at `b2915e3` |
| Commits on the branch | 1 — documentation only |
| Pushed | **yes**, `git push -u origin task6/wave-3d` |
| Merged | **no** — `main` untouched, never checked out for writing |
| Pull request | **none opened**, per the directive |

`main` was pulled at session start and not modified. Wave 3C's branch (`task6/wave-3c`) also remains
unmerged and awaiting human review.

---

## 6. Stop

This wave is complete and stops here, per the directive. Nothing in Wave 3D pre-empts a later wave:
both new documents are additive, and every gap they surface is recorded as an Open item in
`PROJECT_STATE.md` rather than acted on.

**What a reviewer should look at first,** in order of consequence:

1. **`WAVE3D_REPORT.md` §2.1, item 3** — the guide now contradicts the PRD's own §28.5 demo script.
   A −25 % fuel request returns `REJECTED / OUTSIDE ENVELOPE` in Experimental Mode, not `PASS`. If
   the PRD's script is the intended behaviour, the *engine* needs changing, not the guide. If the
   engine is right, PRD §28.5 needs an erratum. **This is a product decision, not a doc fix.**
2. **The two new Open items** in `PROJECT_STATE.md` — the docstring timing error and Experimental
   Mode's unreachability. Both are small; both need a wave that owns `app.py`.
3. **`DATA_DICTIONARY.md` §1.3** — the reading of `assumption=False` as *"no process-reasoned numeric
   band"* rather than *"measured"*. This is the document's most load-bearing sentence and worth a
   second opinion.

**Item 15's requirement text remains UNRECOVERED.** Task #6 still cannot be reported complete while
that stands — Wave 3D did not touch it and had no means to.

