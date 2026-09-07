# Executive Demo / UX Wave Report

**Wave:** Executive Demo / UX — bilingual technical panels, table layout, simulated-live
playback, single global disclosure, executive polish of the OT document.
**Date:** 2026-09-07.
**Output:** `reports/cement_plant_ot_platform.html` (self-contained, double-click openable,
built by `python app.py --view OT`).
**Code:** `src/visualization/i18n.py` + `src/visualization/playback.py` (both new,
presentation only); edits confined to `src/visualization/` renderers, `src/visualization/theme.py`,
`app.py` (heading only), `src/digital_twin/state.py` (view-H header notices only — no payload
computation changed), and `tests/` (needles, goldens, the new focused module).
**Frozen layers:** untouched — both digests re-verified after all changes (see §9).

---

## 1. Audit (step 1)

| Issue | Root cause | Fix layer |
|---|---|---|
| Technical panels English-only while the shell offered a Persian mode | Renderers emitted single-language strings; no central localization existed | New `src/visualization/i18n.py` + per-renderer `dt-en`/`dt-fa` pairs |
| Three-column tables collapse/overflow with long identifiers | Fixed `minmax(Nem,1fr)` grid floors force tracks wider than the card | Capped floors `minmax(min(…,100%),1fr)` + `min-width:0` + `overflow-wrap:anywhere` in the shared stylesheet and per-view layout CSS |
| No "plant moves" moment for an executive demo | Static export only; renderer layer has no script by design | Export-time timeline (`playback.py`) + minimal inline JS runtime in the shell |
| Repetitive synthetic labels on every screen | Each renderer printed the same two badges | One global disclosure in the shell header + footer; per-screen badges removed |
| Persian/RTL bidi hazards | Raw identifiers/numbers inside RTL text | `<bdi>` isolation on identifiers, values, clock; panels pinned `dir="ltr"` |

**Verdict:** all five fixes live in the Task-6 presentation layer. No model, threshold,
dataset, split, optimizer or provenance semantics was touched.

## 2. Changes

| File | Change |
|---|---|
| `src/visualization/i18n.py` (new) | Central EN/FA localization: `bi()` pair helper, `tag_title`/`tag_ref` (canonical ids preserved, Persian secondary reference `شناسه فنی: <bdi>…</bdi>`), status/state dictionaries, the ten view titles + subtitles, anchor key builders (`data-otk`), `title_bi` |
| `src/visualization/playback.py` (new) | Timeline extractor: render-then-diff over views A–H (45 ticks), provider restore, `timeline_json` embedding |
| `src/visualization/ot_shell.py` | Playback bar + runtime script, global disclosure (exact directive wording, header + footer), identifier-retention note, bilingual three-step how-to, `MAX_TICKS` wiring |
| `src/visualization/theme.py` | Global table/grid stability rules (`min-width:0`, `overflow-wrap:anywhere`), the `html[dir]` language-visibility rules |
| `overview/energy/process/intelligence/optimization/presentation_view.py`, `svg_twin.py`, `what_if_view.py` | Bilingual titles/labels/tables via `i18n`; per-screen synthetic badges removed; capped grid floors in layout CSS |
| `app.py` | `_heading_html` bilingual; `build_ot_platform_document` passes `playback.build_timeline` |
| `src/digital_twin/state.py` | View H's header notices drop the two now-global labels (payload computation unchanged) |
| `tests/` | Needles updated for bilingual markup; 9 goldens regenerated; new `tests/test_task6_executive_demo.py` |

## 3. Localization

Persian is **technically correct cement-process Persian**, written as natural prose
(کورهٔ دوار rotary kiln, آسیای سیمان cement mill, پیش‌گرم‌کننده preheater, جداکننده separator,
کلینکر clinker, پیش‌بینی چندافقی multi-horizon forecast, …). Canonical technical identifiers
are **never renamed**: Persian mode shows them only as the secondary reference
`شناسه فنی: mill_motor_power_kw`, `<bdi>`-isolated so bidi never scrambles them. Centralized in
one module — no crude global replace; an entry missing from the dictionary renders in English
(the honest fallback, never a blank).

## 4. RTL / LTR

Shipping state `lang="en" dir="ltr"`; the switch writes `lang`/`dir` on `<html>`. The shared
stylesheet's rules key off `html[dir]` — the same attribute the shell's `otSetLang` writes — so
one mechanism switches the shell *and* every embedded panel. Technical panels sit in
`dir="ltr"`-pinned `.ot-tech` blocks so RTL layout can never reorder a table, an SVG or an
identifier. No second document: both languages always ship; visibility is pure CSS.

## 5. Simulated live playback

The timeline is built **at export time by render-then-diff**: per tick the provider advances
one `step_minutes`, the time-indexed views (A–H) re-render through the same
`app.build_view_section` dispatch, and only anchors whose rendered content changed enter the
timeline — every patch is byte-for-byte what a real re-render would show. The runtime patches
`[data-otk]` nodes: plain strings replace `textContent`; `[en, fa, cls]` triples patch the two
language children of a bilingual pill and swap its `dt-pill--*` class so a status change also
changes its colour. Controls: Play/Pause, Reset, 1×/2×/4×, sim clock, progress bar. The label
is the mandated pair "SIMULATED LIVE DEMO" / "شبیه‌سازی زنده نمایشی" — never bare "LIVE" or
"REAL-TIME". No `Math.random`, no network, no library; one inline `<script>`. Views I/J/P stay
static by rule (scenario-level results). A state that cannot be advanced embeds
`OT_TIMELINE=null` and the controls render honestly with a still clock.

## 6. Tables

The three-column collapse is fixed globally: capped grid floors
`repeat(auto-fit,minmax(min(13em,100%),1fr))` on the KPI grids (with the 26em/12em/15em
cousins where the layout calls for them), `min-width:0` on cards, and
`overflow-wrap:anywhere` on monospace identifier spans — a long tag can wrap inside its cell
but can never blow its track into the neighbouring card. Applied in the shared stylesheet and
each view's scoped layout CSS.

## 7. Honesty / provenance

One global disclosure — "Demo Mode — All displayed process data is synthetic and this demo is
not connected to a real plant." / the exact Persian counterpart — ships in the header and the
footer (the directive's exact wording). The per-screen "Simulated result" /
"Not validated against real plant data" badge pairs were removed from every renderer; what
remains by design: the PRD-verbatim no-plant-connection banners per view (test-pinned), the
twins' own source-flag badges, the PRD 29 per-KPI-card labels in the presentation overlay, and
the shell's header badges. The playback label is honest; the clock and every patch are
renderer output, never fabricated.

## 8. Tests

* **New focused module** `tests/test_task6_executive_demo.py` (19 tests) — the six guarantee
  groups: Localization (bilingual panels, real Persian, canonical ids, all ten titles),
  RTL/LTR (shipping state, switch mechanism, bidi isolation), Tables (global fix present,
  capped floors), Simulated live (one inline script, non-null timeline, mandated controls,
  strictly advancing clock, delta-only ticks, honest null case, no `Math.random`), Honesty
  (exact disclosure ×2, mandated playback label, per-panel labels gone, landing-tab how-to),
  Self-contained (no external URI/`<link>`/`<img>`/`@import`/`<script src`; `url(…)` only as
  fragment references).
* **Needles updated** in the view test modules for the bilingual markup shapes (heading
  wrappers, pill language pairs).
* **Goldens regenerated** (all 9) via each test module's own stub builders with
  `DashboardSettings.from_config()` — the recorded regeneration pattern, never hand-edited.
* **Full regression:** 784 passed, 0 failed, 0 xfailed (was 765 before the wave; +19 focused
  tests, needle updates only elsewhere — no test was loosened to pass).
* **Browser automation** was unavailable in this environment (Playwright/jsdom not installed);
  validation is the static suite above plus the shell wave's established `node --check` on the
  inline script. Click-through in a real browser remains a manual step; the mechanism is CSS
  state + inline JS with a no-JS fallback, so a failure would be visible, not silent.

## 9. Frozen layers (digests, verified after all changes)

```
git ls-files -s src/models src/process_models src/optimization src/simulation \
  src/features src/data_generation configs pyproject.toml | md5sum
# c7a1f54dd578900835596c02cb9a19a0  ✓ unchanged
git ls-files -s tests/ | grep -v -E "test_task6_|tests/golden/" | md5sum
# 53f2aefec33494be5ca22c08ab22b5fd  ✓ unchanged
```

`src/notebook_support.py`, hyperparameters, feature engineering, splits, purge/embargo,
checkpoints, optimization math, simulation equations, targets, model artifacts and provenance
semantics: untouched.

## 10. Git

Commit: this wave's commit (see `git log -1`). Tree: clean after the commit; the artifact
`reports/cement_plant_ot_platform.html` is rebuilt from the final code (45-tick timeline,
bilingual headings, single disclosure). Push status: not pushed from this session — the user
pushes when ready.

## 11. Limitations (stated, not hidden)

1. Persian renders with system fonts; no webfont is embedded (self-containedness forbids
   fetching one; embedding a full Persian typeface would bloat the file).
2. No browser automation run (see §8); validation is static + JS syntax check.
3. The playback timeline is pre-recorded at export time (45 samples at 1-minute steps): an
   honest simulated demo, never a live feed — labelled as such everywhere.
4. Views I/J/P deliberately do not move during playback (scenario-level results, the wave's
   rule 8).
