# VIEWS C / D / F — PROCESS DETAIL SCREENS: AUDIT AND IMPLEMENTATION REPORT

**Date:** 2026-09-03
**Wave:** Views C (Preheater & Kiln), D (Clinker Cooler), F (Mill & Separator) — the process
detail screens (directive items 5, 6, 9; the item-4 inspector half)
**This file is the single report for the whole wave:** audit, verdicts, the shared-renderer
decision, implementation, tests, digests and git state, per the wave brief.

---

## 1. Git verification (wave start)

```
$ git log --oneline -5
091cb4a feat(task6): Wave View I - first renderer for the What-If Simulation screen
6ee2d56 feat(task6): Wave View G - first renderer for the Energy Monitoring screen
6dfb67b docs(task6): pin Wave View A commit hash in the closeout report
8f61802 feat(task6): Wave View A - first renderer for the Plant Overview screen
cc86f54 docs(task6): View H closeout — G-10 settled, full A-J renderer inventory

$ git status        # clean
$ git fetch origin && git status -sb
## main...origin/main     # in sync; HEAD is 091cb4a, the View I wave
```

HEAD at start was `091cb4a` — the View I wave, as the brief expected. **Views C/D/F had no
renderer**: all three fell through `app.py`'s dispatch to `_payload_html` (the JSON fallback),
and no `_is_process`-style check existed. Verified at source, not assumed.

**Frozen-layer digests, before and after (unchanged — see §8):**

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0   (expected — unchanged)

git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd   (expected — unchanged)
```

---

## 2. PRD requirement checklist per view (verified, not invented)

The controlling fact for this wave is the directive's **D-2 discrepancy**: PRD §17's ten-row
table contains **no row for C, D or F**. Its rows map to other screens (view 1 → A, view 4 → J,
view 5 → I, view 7 → H, …; see `PROJECT_STATE.md`'s per-view rows). Views C/D/F come from
**directive item 2's A–J registry** (`state.py:76-87`), and the requirements that actually bear
on them live in the directive items and the PRD's panel specs:

| # | Requirement | Source |
|---|---|---|
| R-C1 | View C shows preheater, precalciner and rotary-kiln detail | directive item 2 (E1, registry line) |
| R-C2 | Kiln panel: fuel rate, feed rate, burning-zone temp, O2, CO, ID fan, production, specific thermal consumption + "other available fan/process indicators"; **CO in the main panel only**; ranges/statuses from existing configuration, no invented limit | PRD §18.2; directive item 5 (E1) |
| R-C3 | Emissions monitored outputs kept as their own block (PRD 12.1's emissions) | directive item 5 (E1, `KILN_EMISSION_TAGS` comment) |
| R-D1 | View D shows the clinker cooler and the fuel/fan system that feeds the burning zone | directive item 2 (E1, registry line) |
| R-F1 | View F shows mill, dynamic separator, fan/filter and finished product detail | directive item 2 (E1, registry line) |
| R-F2 | Mill panel: feed, mill power, separator RPM, pressure, Blaine, residue, specific electricity + "available mill/separator/fan indicators" | PRD §18.3; directive item 6 (E1) |
| R-ALL1 | Equipment state changes shown; every component PRD 8.3 defines, no invented equipment | directive items 2/4 (E1) |
| R-ALL2 | KPI groups from the provider, no invented KPI | directive item 9 (E1) |
| R-ALL3 | No hard-coded/non-traceable number in any panel (NFR-6) | directive item 20 / AC-12 |
| R-ALL4 | Honesty rules: standing statement, absences stated, no confidence % | directive item 20 |

Explicitly **not** requirements (checked): a PRD §17 row per screen (none exists — D-2); KPI
cards or grouped panels **on view D** (no source asks for them — see §4); animation on these
screens (item 4's animation contract belongs to views B/E; the PRD §17 rows 2–3 that demand
animation are the twin screens, not C/D/F); trend charts/sparklines (same deferred decision as
views A/G/H).

---

## 3. Payload trace per view (read-only, before any change)

All three builders return the same frozen dataclass
`ProcessView(header, components, panels, kpis)` (`state.py:370-385`), built by
`_components()` from `frame.equipment_by_name()` + `layout.equipment_spec(name).detail`, plus
`_panel()` from the shared observed snapshot. Traced over both the shared stub provider and a
real model-layer session:

| | View C (`kiln_process`, state.py:831) | View D (`clinker_cooler`, state.py:844) | View F (`mill_separator`, state.py:854) |
|---|---|---|---|
| components | Preheater (3 readout tags), Precalciner (2), RotaryKiln (9) | Cooler (4), FanFuel (14) | Mill (11), Separator (4), FanFilter (5), Product (2) |
| panels | "Kiln process indicators" (`KILN_PROCESS_TAGS`, 19 tags), "Kiln emissions" (`KILN_EMISSION_TAGS`: CO2/NOx/SO2) | **()** | "Mill process indicators" (`MILL_PROCESS_TAGS`, 13 tags) |
| kpis | Kiln KPI group (item 9) | **None** | Cement-mill KPI group (item 9) |

Requirement coverage:

- **R-C2 (kiln panel):** satisfied. The PRD 18.2 headline tags are carried — fuel/feed rates
  and burning-zone temp on RotaryKiln's own readout; O2, CO, ID-fan figures on FanFuel's
  readout (view D) **and** in view C's flow via the process indicators; production and specific
  thermal consumption on RotaryKiln's readout and in the Kiln KPI group. "Other fan/process
  indicators" = the 19-tag process panel. CO sits in the FanFuel readout and nowhere near the
  emissions panel — item 5's "CO in the main panel only" is honoured by the layout, and the
  renderer changes nothing about it.
- **R-C3:** satisfied — the emissions block is its own panel of exactly the three PRD 12.1
  emission tags.
- **R-F2 (mill panel):** satisfied — the PRD 18.3 headline tags are on Mill/Separator's own
  readouts plus the 13-tag process panel and the Cement-mill KPI group.
- **R-ALL1:** satisfied — every component is a `layout.EQUIPMENT` spec (PRD 8.3 kinds only);
  each `EquipmentDetail` carries state word, health, driver and its own readout.
- **R-ALL2/R-ALL3/R-ALL4:** satisfied — KPI groups are the provider's own; every number is a
  `Value` with provenance/source; the header carries the badge and the payload its own notices.
- **Does `ProcessView` lose information the PRD requires?** No field the PRD asks for is
  absent from the shape; nothing in this wave needed an accessor change.

## 4. The View D question: `panels=()` and `kpis=None` — intended content, not a gap

Traced to source, the emptiness is **by design, and no PRD/directive text contradicts it**:

1. **No PRD §17 row names view D** (D-2), and no directive item asks the Clinker Cooler screen
   for a grouped panel or a KPI group. Items 5/6 (the panel requirements) attach to the kiln
   panel and the mill panel — view C and view F respectively.
2. **The payload is not thin.** FanFuel's readout carries 14 tags — the fuel rates, ID-fan
   speed/power/current, all three air flows, inlet pressure, O2, CO, CO2, NOx, SO2 — and
   Cooler's carries the clinker/cooler/secondary-air temperatures plus fan power. That is
   every tag the screen's registry line promises ("clinker cooler and fuel / fan system
   detail") and every tag PRD §12.1 defines for the cooler/fuel/fan system.
3. The KPI groups view D's dataset owns (Kiln) are **view C's** — attaching them to view D too
   would duplicate, not complete.

**Resolution:** render view D as components-only and *state* the two absences as designed
facts ("this screen carries no grouped readout panels / KPI group of its own") — never as an
error, never filled with invented content. No payload change made or needed.

---

## 5. Verdicts and the renderer decision

| View | Verdict | Basis |
|---|---|---|
| **C** | **A — READY** | Payload complete for every traced requirement (R-C1/C2/C3) |
| **D** | **A — READY** | Payload complete for every traced requirement (R-D1); the empty panels/kpis are designed content (§4), not a gap |
| **F** | **A — READY** | Payload complete for every traced requirement (R-F1/F2) |

**Renderer decision: SHARED — one renderer, one dispatch check.** Verified, not assumed:

- All three views return the *same* dataclass with identical field semantics (§3); no field
  means something different per screen — the header names the screen, and every section's
  meaning comes from the payload's own titles.
- No view-specific rendering requirement survives from §2: items 5/6 are "render the panels
  the layout declares", identical work for C and F; D needs the same components rendering with
  the two stated absences, which the *payload's own emptiness* drives — no view-id branch.
- The renderer (`render_process`) never reads `view_id` and would render any fourth
  `ProcessView` unchanged.
- **Discriminator verified:** `_is_process` duck-types on `components` **and** `panels`. No
  other view model carries both — A: `stages`/`plant`; B/E: `line`/`snapshot` (the twin's
  near-miss fields are `panel` *singular* and `equipment`, pinned by test); G:
  `specific`/`total`; H: `predictions`/`anomaly`; I: `sliders`/`view`; J: a `view` with
  `recommendation`/`baselines`. Confirmed by reading each model's dataclass definition and by
  the non-collision test.

---

## 6. Implementation

### 6.1 Files changed

| File | Change |
|---|---|
| `src/visualization/process_view.py` | **new** — the one renderer for C, D and F (plain HTML, no framework, no chart dependency) |
| `app.py` | additive routing only: `process_view` import, the `_is_process` duck type, one `elif` in `build_document`. No CLI change, no existing route touched. |
| `tests/test_task6_process_view.py` | **new** — 27 tests (§6.4) |
| `tests/golden/view_c_normal.html` | **new** — golden fixture, generated by the command recorded beside `GOLDEN_PATHS` |
| `tests/golden/view_d_normal.html` | **new** — golden fixture (pins the designed-emptiness rendering) |
| `tests/golden/view_f_normal.html` | **new** — golden fixture |
| `docs/DEMO_GUIDE.md` | the optional small scope: the stale What-if §6.1-warning/§6.2/§6.3 paragraphs rewritten for `--change`/`--mode` (§6.5) |
| `docs/VIEWCDF_AUDIT_AND_IMPLEMENTATION_REPORT.md` | this file |
| `docs/PROJECT_STATE.md` | wave row + status updates (facts established this wave only) |

No frozen-layer file, no payload/state/insights change (the builders were reused unchanged),
no view A/B/E/G/H/I/J behavior touched.

### 6.2 Renderer behavior (`render_process`)

Reads the frozen view model only; computes nothing; every string through `theme.html`; every
number through `theme.value_text` at `FormatSettings` precision; every status pill is the
payload's own banded status, every provenance badge the payload's own source. Sections, each
with a `data-role` anchor:

- **status strip** — Simulated-result and Not-validated badges, the header timestamp, and the
  header's own notices verbatim where it carries any;
- **components** (item 4's inspector half) — one card per `EquipmentDetail`: the payload's own
  title (the layout spec's), the state word as a pill (RUNNING green / DERATED amber /
  IDLE·UNKNOWN grey — the same mapping view A uses), the model kind and health scalar, the
  driving variable (the same observed `Value` views B/E animate by — AC-21's input, as text),
  and the readout table of the component's own output tags (label = the tag's own schema
  description, tag in muted mono beneath, NFR-6). An absent driver is stated; an empty readout
  is stated; an empty component list is stated;
- **process readouts** (items 5/6) — one card per panel: its own title, one table row per
  `Value`, the panel's own note verbatim. **Empty tuple (view D):** a stated fact — "This
  screen carries no grouped readout panels of its own; every reading it reports lives in the
  component cards above" — deliberately *not* the renderer's `unavailable` honesty word, so a
  designed emptiness reads differently from a provider that answered nothing;
- **KPIs** (item 9) — the group as cards, same shape as the view A/G renderers.
  **`kpis=None` (view D):** stated the same way;
- standing footer: `NO_PLANT_CONNECTION_STATEMENT`.

### 6.3 Routing behavior (`app.py`)

`_is_process(model)`: duck-typed on `components` **and** `panels` (§5's discriminator). One
additive `elif` in `build_document` after `_is_whatif`; all existing routes untouched (pinned
by the non-collision test and the unchanged app-smoke suite).

### 6.4 Tests added (27, all in `tests/test_task6_process_view.py`)

A sections/components/readouts/driver (4) · B view D's designed emptiness: components-only
render, both stated absences present, stated-fact-not-error wording, standing statement (3) ·
C missing/degraded data: empty component list, empty readout, absent driver, absence-glyph
row, empty panel, empty KPI group (6) · D honesty: no confidence/forbidden label, header
notices verbatim, escaping (3) · E determinism (1) · F the shared renderer serves all three
screens, same anchors, own components (1) · G payload layer: `ProcessView.describe()` for both
shapes, the real state builders over the stub provider (all three screens' components, C/F
panels+kpis, D's emptiness at source), real-models-through-renderer (3) · H routing:
`build_document` routes C/D/F, duck-type non-collision vs A/H/I/J and the twin's
`panel`/`equipment` near-misses (2) · goldens, parametrized per view (3) + the golden-model
helper. Covers the brief's A–F list: normal rendering (A), empty/None panels+kpis honestly
(B), missing/degraded component data (C), no fabricated values (D), determinism (E), app
dispatch (F).

### 6.5 The optional DEMO_GUIDE fix (done — small and unambiguous)

The stale What-if paragraphs in §6 (the "Experimental Mode is not reachable from the command
line / no `--mode` flag" warning block, §6.2's "the only way to show Experimental Mode today",
and §6.3's "the mode switch is not yet wired to this export") now describe the View I wave's
`--change`/`--mode` flags, with both guide commands verified to run (the EXPERIMENTAL export
exits 0 and writes a self-contained file; `--change` without `--view I` exits 2 with the
error, as the guide states). §6.2 keeps its executed Python snippet — still valid, and still
the path when you want the raw view model. **Left stale on purpose** (same fact, outside the
brief's named §6.2/§6.3 scope): §5's step-3 note ("no `--change` flag") and §9's table rows
5–6 — docs backlog, flagged here rather than expanded into.

### 6.6 Test and smoke results

- **Focused, before implementation:** `tests/test_task6_app_smoke.py` (the dispatch suite the
  routing change could break) → **18 passed**.
- **Focused, after implementation:** `tests/test_task6_process_view.py` → **27 passed**;
  app-smoke re-run → **18 passed**.
- **Real-app smoke (not a test stub):** `python app.py --view C --view D --view F --seed
  20240101` with the model layer — exits 0, self-contained 47 KB export; all 9 components
  across the three screens render with their readouts, view D's two designed absences state
  correctly, and the no-plant-connection statement appears on every screen plus the document
  footer. Views C/D/F each measured **0.002 s** render (the screens are observed-snapshot
  reads; no model call, no history).
- **Full regression:** run exactly once at the end — see §9.

---

## 7. Remaining gaps per view

1. **No trend channels on C/D/F at all** (unlike view G's payload, which carries `trends`).
   PRD §18 asks for no sparkline on these screens' panels, so nothing is skipped that a source
   asks for — recorded so the next renderer inventory doesn't re-investigate.
2. **The emissions panel shows current readings only** — PRD 12.1's emissions are carried as
   monitored outputs; no emission *trend* is required by any traced source, and none is
   rendered.
3. **`EquipmentStatus.constraints`** is carried by the payload (per-component constraint
  `Value`s) but not rendered — the real provider currently serves `constraints=()` (verified
  in the stub and the layout), so there is nothing to render honestly; a renderer branch for
  it would be dead code today. Flagged for the wave that first serves real constraints.
4. **DEMO_GUIDE §5 note and §9 table rows 5–6** — same staleness class as §6, fixed there but
  out of this wave's named scope (§6.5).

## 8. Frozen-layer digest verification (after the wave)

```
$ git ls-files -s src/models src/process_models src/optimization src/simulation \
    src/features src/data_generation configs pyproject.toml | md5sum
c7a1f54dd578900835596c02cb9a19a0      # expected — UNCHANGED

$ git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
53f2aefec33494be5ca22c08ab22b5fd      # expected — UNCHANGED
```

No frozen file was touched; the wave's only production edits are
`src/visualization/process_view.py` (new) and the additive `app.py` routing. `state.py` /
`insights.py` / `layout.py` were **not** modified.

## 9. Full regression and final git state

- **Full regression, run exactly once at wave end:** `python -m pytest` → result recorded in
  `PROJECT_STATE.md` with this wave's commit (662 before + 27 new = expected 689; the recorded
  number is the run's own). No test was weakened, deleted or skipped.
- **Git:** one commit for the wave; `git diff --stat`, `git status`, `git diff --check` run
  before it; pushed to `origin/main` and re-verified. The commit hash is pinned in
  `PROJECT_STATE.md` (a report committed in its own wave cannot contain its own hash).
