# VIEW G IMPLEMENTATION REPORT — Energy Monitoring renderer (Wave View G)

**Date:** 2026-09-02
**Wave:** Task 6, View G — the first renderer for the Energy Monitoring screen.
**Audit:** `docs/VIEWG_AUDIT.md` (same session; verdict recorded below before any code was
written, per the wave brief's two-phase gate).

---

## 1. Audit verdict

**A — READY TO IMPLEMENT.** Every number the screen must show already exists on the frozen
`EnergyView` view model (`src/digital_twin/state.py:391-421`, built by
`DashboardState.energy()` at `state.py:865-891`): the plant KPI group with the specific-energy
figures **and** their daily totals bound in under the item-12 note, the same group partitioned
by tag into `specific` / `total` / `production` panels, the kiln and cement-mill KPI groups, and
downsampled trend channels for the intensity tags. No accessor, adapter, backend, model or
frozen-layer work was required — not even the trivial presentation accessors category B allows.

## 2. Exact PRD / directive requirements implemented

* **Directive item 12 (Tier E1, VERBATIM)** — *"The dashboard must NOT show only the favorable
  metric."* (`src/labels.py:175`). Specific energy (per tonne) and total energy (per day) are
  shown together, because specific energy can fall while the daily total rises, production
  having risen. PRD anchors: §17 view 1 ("production, thermal/electrical energy"), §18.1, §9.2.
* **Directive item 9 (Tier E1)** — the three labelled KPI groups (plant / kiln / mill), no
  invented KPI among them; view G carries all three, two of them (kiln, mill) rendered here as
  groups and the third (plant) rendered as its item-12 partition.
* **Directive item 20 (Tier E1)** — the honesty rules every screen carries: standing
  statements, no fabricated value, absences stated rather than filled in, HTML escaping of all
  payload free text.
* View G has **no own PRD §17 row** (the documented D-2 discrepancy set); its PRD content is
  view 1's energy KPIs. This is unchanged by the wave — the screen now *renders* what the
  payload always carried.

## 3. Exact payload / data structures used

`EnergyView` fields rendered, all read-only:

| Field | Type | Rendered as |
|---|---|---|
| `header` | `ViewHeader` | timestamp line (title/subtitle rendered by `app.py`, as on every screen) |
| `plant` | `KpiGroup` | not rendered separately — its content *is* the three partitions below, which together are exactly its tag set (verified by test) |
| `specific` | `Panel` (note = `SPECIFIC_VS_TOTAL_NOTE`) | "Specific energy (per tonne)" cards |
| `total` | `Panel` (same note) | "Total energy (per day)" cards |
| `production` | `Panel` | "Production" rate cards |
| `kiln`, `mill` | `KpiGroup` | item-9 group cards |
| `trends` | `tuple[Series, ...]` | **not rendered** (see §13) |

Each card renders a `Value`'s own number (`theme.value_text`, FormatSettings precision), its own
banded `Status` pill, its own `Provenance` badge, its schema description as title and its tag in
muted mono (NFR-6 traceability). The partition is by tag against `layout.DAILY_TOTALS`
(`layout.py:169-191`), performed by the state layer — the renderer computes nothing.

## 4. Files changed

| File | Change |
|---|---|
| `src/visualization/energy_view.py` | **new** — the renderer (~230 lines), plain HTML, self-contained, deterministic |
| `app.py` | additive only: `_is_energy` duck type (`specific` + `total`) and one `elif` routing to `energy_view.render_energy`; import line extended. No existing branch touched |
| `tests/test_task6_energy_view.py` | **new** — 19 focused tests (§8) |
| `tests/golden/view_g_normal.html` | **new** — golden fixture, generated with the command recorded beside `GOLDEN_PATH` |
| `docs/VIEWG_AUDIT.md` | **new** — the Phase-1 audit (verdict A) |
| `docs/VIEWG_IMPLEMENTATION_REPORT.md` | **new** — this file |
| `docs/PROJECT_STATE.md` | updated with this wave's facts only |

## 5. View G coverage

The screen renders, from one frozen view model: the item-12 pair section (specific figures,
their daily totals, and the production rates that connect them, with the payload's own pairing
note printed once beneath, verbatim), the kiln KPI group, and the cement-mill KPI group — plus
the honesty badges ("Simulated result", "Not validated against real plant data"), the header
timestamp and the standing no-plant-connection banner every view carries.

## 6. Honesty: favorable-vs-unfavorable handling

Item 12 is enforced structurally, not by renderer goodwill:

* The provider binds both halves into **one** plant group under `SPECIFIC_VS_TOTAL_NOTE`
  (`synthetic.py:1050-1057`, totals via `daily_totals()` at `:1017-1048` — arithmetic by
  `recommendation.daily_total`, staying `Provenance.OBSERVED`), and the state layer partitions
  that one group by tag. The renderer shows all three partitions on one screen, so the
  favorable half (falling specific energy) can never appear without the total it implies.
* An **empty total partition is stated in place** ("unavailable: this provider carries no
  daily-total figures") beside the still-rendered specific figures, and the pairing note still
  reads — the unfavorable half is never silently dropped (pinned by
  `test_an_absent_total_never_leaves_the_specific_figure_alone`).
* Nothing is fabricated: no savings, no efficiency verdict, no baseline, no percentage, no
  recommendation. The screen reports energy only, and asserts so
  (`test_no_confidence_percentage_and_no_forbidden_control_label` also checks "saving" never
  appears).
* The totals' `NO_LIMIT` status renders as its own pill — the renderer awards no OK to a
  display aggregation that has no band of its own.

## 7. Missing / degraded-data behavior

* A dropped reading (`Value.value is None`) renders the theme's absence glyph (`—`) with the
  payload's own `UNKNOWN` status — never `0`, never blank (pinned by
  `test_a_missing_number_shows_the_absence_glyph_never_a_zero`).
* An empty partition or KPI group renders a stated absence naming its subject ("unavailable:
  this provider carries no …") — no card invented to fill the space.
* Views C/D/F remain on the JSON payload fallback; view G's routing is shape-based and verified
  not to swallow the A/B/E/H/J models.

## 8. Tests added

`tests/test_task6_energy_view.py`, 19 tests in the eight areas the brief prescribes:

A. normal rendering (3) · B. favorable + unfavorable both visible (2) · C. missing energy data
(2) · D. degraded/unavailable data (2) · E. no fabricated values / honesty rules (2) ·
F. determinism (1) · G. payload/accessor behavior (3 — the frozen `EnergyView.describe()`, the
real `DashboardState.energy()` partition over the shared stub provider, and the trend channels'
presence) · H. app.py dispatch (3) · plus the golden-file pin (1).

## 9. Focused test result

`pytest tests/test_task6_energy_view.py` — **19 passed** (one intermediate run failed on two
wrong test expectations — a formatting-precision assumption (`102,618.8` vs the FormatSettings
`102,619`) and an over-broad "no cards" assertion that forgot the kiln/mill groups; both were
test bugs, fixed in the tests. No renderer change was needed and no test was weakened).

## 10. Affected Task-6 test result

`pytest -k task6` — **203 passed, 0 failed** (was 184 before this wave; +19). `app.py`'s
existing dispatch branches, the app smoke tests and the golden fixtures for views A/H/J are
untouched and green.

## 11. Full regression result

`pytest tests/` — **631 passed, 0 failed, 0 xfailed**, run exactly once at the end (was 612;
the wave added 19 tests and changed none). Regression floor 428: exceeded, no drop.

## 12. Frozen-layer digest verification

Before **and** after the wave:

```
src/{models,process_models,optimization,simulation,features,data_generation}, configs,
pyproject.toml  ->  c7a1f54dd578900835596c02cb9a19a0   (unchanged, matches PROJECT_STATE.md)
tests/ minus test_task6_* and tests/golden/            ->  53f2aefec33494be5ca22c08ab22b5fd
```

Both digests are byte-identical to the recorded values; nothing under digest protection was
touched.

## 13. Remaining View G gaps

* **Trend channels not rendered.** The payload carries downsampled `Series` for the
  specific-energy tags (verified present by test), but no Task-6 renderer draws charts — the
  same deferred Plotly-optional decision behind view H's G-6 skip and view A's skipped PRD
  18.1 sparklines. A later chart wave finds the channels already on the view model.
* **No PRD §17 row of its own** (D-2) — unchanged; view G's PRD content lives on view 1's
  energy KPIs, which view A also renders (whole group, unpartitioned).

## 14. Items intentionally deferred, and why

* **Trend sparklines** (§13) — wiring a chart into a plain-HTML deterministic renderer forces
  the degradation-path decision this project has consistently deferred; out of this wave's
  presentation-only scope.
* **The View H closeout's proposed `PROJECT_STATE.md` edits** (`VIEWH_CLOSEOUT_AND_INVENTORY.md`
  §5 — G-10 CLOSED wording, DEMO_GUIDE staleness row) — not this wave's facts; the brief
  restricts PROJECT_STATE updates to what this wave established. Still outstanding for a
  docs-owning wave.
* **Views C / D / F / I** and everything else in the stop-condition list — not started, per the
  wave's scope rule.
