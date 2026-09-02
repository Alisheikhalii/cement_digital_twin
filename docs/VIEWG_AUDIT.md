# VIEW G AUDIT — Energy Monitoring

**Date:** 2026-09-02
**Scope:** read-only reconnaissance for the View G (Energy Monitoring) renderer wave. No source,
test, fixture or frozen-layer file was changed by the audit itself. This file records the audit
conclusion required before implementation (per the wave brief), and the verdict below gates
Phase 2 of the same session.

---

## 1. What View G is supposed to display

### 1.1 The view's identity

View G is internal id **G — "Energy Monitoring"** in the A–J registry
(`src/digital_twin/state.py:83`, subtitle: *"Specific energy (per tonne) and total energy (per
day), together"*).

**It has no own PRD §17 row.** Per the full A–J inventory
(`docs/VIEWH_CLOSEOUT_AND_INVENTORY.md` §3), View G's PRD content is **view 1's energy KPIs**
(§17 view 1, `PRD:694`: "production, thermal/electrical energy") and **§18.1 / §9.2** — an
internal-only screen (the D-2 discrepancy set) whose subject is anchored in the PRD's energy
requirements rather than a §17 row of its own. This is not an ambiguity: the directive item that
owns the view names its content exactly, and the payload was built to it.

### 1.2 Directive items that belong to View G

* **Item 12 — "Show specific *and* total energy"** (Tier E1, VERBATIM quote available). The
  requirement, recorded word-for-word at `src/labels.py:175`:
  > **"The dashboard must NOT show only the favorable metric."**

  Rationale (`src/digital_twin/layout.py:150`): a dashboard that shows only specific energy can
  report an improvement while total consumption rises, because production rose. Each
  specific-energy KPI is paired with the daily total it implies, computed once in
  `recommendation.daily_total` as a display aggregation of observed values (Provenance.OBSERVED,
  arithmetic named in `source`). PRD anchors: §17 view 1, §18, §9.2.
* **Item 9 — KPI groups, no invented KPI** (shared with view A). View G carries all three groups
  (`plant`, `kiln`, `mill`), each already assembled by the provider with no invented KPI among
  them (`src/digital_twin/synthetic.py:1050`).
* **Item 20 — honesty rules** reach this screen as every screen (standing statements, no
  fabricated values), and bear directly on item 12's favorable/unfavorable pairing.

### 1.3 The honesty requirement this wave must enforce explicitly

The wave brief restates item 12 as a hard rule: the renderer must NOT show only the favorable
energy metric; if both favorable and unfavorable indicators exist in the payload, both are shown;
nothing may be fabricated — no invented energy values, savings, efficiency, trends, baselines,
percentages or recommendations; a missing value renders as `unavailable — <reason>`, never 0,
blank or an estimate. The payload's own design (the provider binds specific + total into one
group under `SPECIFIC_VS_TOTAL_NOTE`, `src/labels.py:178`) makes the renderer's job a matter of
rendering the pair whole rather than re-deriving it.

---

## 2. What already exists — the payload trace

`DashboardState.energy()` (`src/digital_twin/state.py:865-891`) builds a frozen
`EnergyView` (`state.py:391-421`) from one shared `_Frame`:

| `EnergyView` field | Content | Built where |
|---|---|---|
| `header` | the shared `ViewHeader` (badge, notices, regime, timestamp) | `state._header("G", frame)` |
| `plant` | the whole plant `KpiGroup`: the two specific-energy figures, the two production rates, **and the two daily totals bound in** under `SPECIFIC_VS_TOTAL_NOTE` | provider `get_kpis` (`synthetic.py:1050`); totals via `daily_totals()` (`synthetic.py:1017-1048`, arithmetic by `src/optimization/recommendation.py:69/:190`) |
| `specific` | `Panel("Specific energy (per tonne)")` — the intensity tags, partitioned **by tag** against `layout.DAILY_TOTALS`, never a second computation | `state.energy()` |
| `total` | `Panel("Total energy (per day)")` — the daily-total tags, same partition | `state.energy()` |
| `production` | `Panel("Production")` — the rate tags, same partition | `state.energy()` |
| `kiln` / `mill` | the other two item-9 KPI groups (fuel rate, thermal energy, specific fuel, BZT, O₂, clinker rate / motor power, specific power, feed, Blaine, residue, ΔP) | provider `get_kpis` via `frame.kpi(...)` |
| `trends` | downsampled `Series` channels for the specific-energy tags (`self._history(specific_order)`) | provider `get_history`, item-23 budget |

`layout.DAILY_TOTALS` (`layout.py:169-191`) declares the two pairs — thermal
(`thermal_energy_kcal_per_kg_clinker` × `clinker_production_tph` → `kiln_thermal_energy_kcal_per_day`)
and electrical (`specific_power_consumption_kwh_t` × `cement_production_tph` →
`mill_electrical_energy_kwh_per_day`) — one per energy carrier the twin models.

**Accessors:** everything the renderer needs is a field of the frozen view model. Each `Value`
arrives with its own unit, documented range, status, provenance and source; each `Panel`/`KpiGroup`
carries its own note. There is nothing to add and nothing to adapt.

**Renderer conventions to follow:** `src/visualization/overview_view.py` (the closest precedent —
it renders the same plant group on view A), `intelligence_view.py`, `optimization_view.py`:
plain HTML fragments, scoped layout CSS, all colours/type from `theme`, every number through
`theme.format_number`/`value_text` at `FormatSettings` precision, every string through
`theme.html`, absences stated (never zero/blank), deterministic output, no framework, no chart
library. Dispatch follows the additive duck-typed `elif` chain in `app.py:166-201`
(`_is_twin` / `_is_intelligence` / `_is_optimization` / `_is_overview` → `_is_energy`).

**Trends:** the payload carries `Series` channels, but no Task-6 renderer draws charts — view H
skipped its §17 trends sparkline (G-6 class) and view A skipped PRD 18.1's sparklines, both
because wiring a chart into a plain-HTML deterministic renderer forces the Plotly-optional
degradation decision this project has deferred. This wave follows that precedent: the trend
channels are **not** rendered and are recorded as a remaining gap (see the implementation report),
not silently dropped.

---

## 3. Verdict

**A — READY TO IMPLEMENT.**

* Required PRD data (specific + total energy pairs, production rates, the three KPI groups) already
  exists in the payload/backend — computed once in the frozen/provider layer, delivered on the
  frozen view model.
* Required accessors already exist; **no** accessor/adapter work is needed at all (not even the
  trivial presentation accessors category B allows).
* No new model/training/frozen-layer/backend computation is required.
* The renderer is a pure presentation-layer task in the exact shape of the view A/H/J waves.

**Favorable-vs-unfavorable enforcement:** the pairing is structural — the provider binds both
halves into one `plant` group under the item-12 note, and the view model additionally partitions
them into `specific` / `total` panels that this renderer shows on one screen. The renderer will
render the whole plant group (like view A) *and* the partitioned panels, so neither half can stand
alone; the note appears verbatim; a missing half of any pair is stated as an absence, never
substituted.

**Recommended next action:** proceed to Phase 2 in this session — implement
`src/visualization/energy_view.py`, add the `_is_energy` dispatch to `app.py`, add focused tests
plus a golden file, run the test order the brief prescribes, and close out with
`docs/VIEWG_IMPLEMENTATION_REPORT.md`.
