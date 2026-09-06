# OT Platform Shell Report — the consolidated management document

**Wave:** Cement Plant OT Platform shell (presentation / information architecture only).
**Date:** 2026-09-06.
**Output:** `reports/cement_plant_ot_platform.html` (self-contained, double-click openable).
**Code:** `src/visualization/ot_shell.py` (new, presentation only) + additive `app.py` wiring
(`--view OT`, `build_view_section`, `build_ot_platform_document`, `DEFAULT_OT_OUT`).
**Frozen layers:** untouched (`src/models/`, `src/notebook_support.py`, `src/process_models/`,
`src/optimization/`, `src/simulation/`, `src/features/`, `src/data_generation/`, `configs/`,
`pyproject.toml`); digests verified before and after (see §11).

---

## 1. What this wave is and is not

The single objective was one consolidated, management-facing HTML artifact that presents the
**existing** project outputs — the ten A–J renderer screens and the PRD §29 presentation
overlay — behind a tabbed, bilingual (English / Persian) navigation shell. The shell is
**information architecture only**: no model, threshold, dataset, target, horizon, split,
optimizer or renderer calculation was changed, and no new number exists anywhere in the
document that a payload did not already carry.

Branding is display-level only. The document's own title/subtitle is *Cement Plant OT
Platform — AI-assisted monitoring, simulation, prediction & optimization* /
پلتفرم فناوری عملیاتی کارخانه سیمان — پایش، شبیه‌سازی، پیش‌بینی و بهینه‌سازی مبتنی بر هوش
مصنوعی. No Python module, package, class, renderer id, PRD term, historical doc or canonical
machine identifier was renamed; the internal "Digital Twin" terminology of the technical
layers is untouched.

## 2. Step 1 audit — what existed before this wave

| Question | Finding | Consequence for the shell |
|---|---|---|
| How does the existing app assemble a page? | `app.build_document` builds each requested view's model and concatenates renderer sections vertically into one HTML document. | The consolidated document is the same assembly with a tab nav: each embedded panel is an unchanged `<section>`. |
| Are renderer outputs embeddable? | Every renderer emits a self-contained fragment (own scoped `<style>`, wrapped in `dt-root`), and `src/visualization` contains no `<script>` at all. | Fragments can be embedded unmodified inside one document with at most one theme `<style>` block. |
| Is there a single place that routes a view id to its renderer? | `app.build_document`'s duck-typed `elif` dispatch (`_is_twin` / `_is_optimization` / `_is_overview` / …). | Extract that dispatch into a shared `build_view_section` so both the old page and the new shell call the same code — zero duplicated routing. |
| Does a management summary already exist? | Yes: the PRD §29 presentation overlay (view P), reached through a `_PresentationRequest` wrapper. | Reuse P as the "Presentation" tab — no second AI-status system was built. |
| Do screens already carry notices? | Yes: every view header's `notices` field. | The Alerts tab can aggregate existing notice text; nothing needs inventing. |
| What honesty labels exist? | `src/labels.py` carries the verbatim PRD standing statements. | The shell re-prints them; it invents none of its own. |

**Verdict:** all ten proposed tabs stand as presentation-only overlays on existing payloads.
No blocker was hit; nothing in the frozen or out-of-scope layers needed to change.

## 3. Final tab architecture

| # | Tab (EN / FA) | Embedded views | Content |
|---|---|---|---|
| 1 | System Guide / راهنمای سامانه | — | New shell-only content: what the platform is, the seven honesty points (synthetic data; no plant connection; no PLC/DCS reads; no commands or setpoint changes; human decides; not validated; predictions are model outputs), before-real-use, and how to use the tabs. |
| 2 | Plant Overview / نمای کلی کارخانه | A | The item-3 five-stage chain + plant KPI group + PRD 18.1 AI tiles. |
| 3 | Kiln / کوره دوار | B **and** C | The animated SVG kiln twin and the kiln/preheater process detail. |
| 4 | Cement Mill / آسیای سیمان | E **and** F | The mill twin and the mill/separator process detail. |
| 5 | Energy / انرژی | G | The specific-vs-total energy pair plus the kiln and mill KPI groups. |
| 6 | AI Prediction / پیش‌بینی هوش مصنوعی | H | Model A's forecast grid and Model B's anomaly verdict. |
| 7 | AI Optimization / بهینه‌سازی هوش مصنوعی | J | Model C's recommendation/refusal, constraints, per-horizon projections. |
| 8 | What-if / تحلیل «اگر-آنگاه» | I | The PRD §16 what-if workspace incl. the transition chart. |
| 9 | Alerts / Health / هشدارها و سلامت فرآیند | — | Aggregation only (see §4). |
| 10 | Presentation / نمای مدیریتی | P | The PRD §29 overlay of views A and J, reused verbatim. |

View D stays a standalone screen (its `panels=()` is designed content — D-2); this wave's
audited mapping puts only B+C and E+F on shared tabs. Every tab opens with a 2–4 sentence
plain-language explanation in both languages, written for a manager who knows cement
operations but not AI/ML.

## 4. Alerts / Process Health verdict

**Aggregation, never computation.** The tab collects exactly four card sources, each named
on the card (`data-source` attribute):

1. **Anomaly verdict — Model B**: view A's own `anomaly_status` tile (status word + detail,
   verbatim; "unavailable" with its own reason if absent).
2. **Optimizer headline — Model C**: view J's payload (headline, message, refusal reasons —
   a refusal is displayed, never dropped or softened).
3. **Operating regime**: the shared frame's own regime label.
4. **Screen header notices**: each screen A–J's standing `notices`, listed per screen;
   screens with no notices are omitted, never padded.

No health score, severity ranking, count or aggregation formula was invented — the wave's
explicit prohibition. The tab carries a traceability note stating this in plain language.

## 5. Presentation / AI-status verdict

View P already is the management AI-status summary (PRD §29: the A/J overlay with the model
registry, qualities and honest availability states). It is embedded verbatim as the tenth
tab; **no second AI-status system was created**, and none of P's internals changed.

## 6. Renderer reuse approach

`app.py`'s duck-typed dispatch was extracted verbatim into
`app.build_view_section(state, view_id, *, settings, ...) -> (model, section_html)`;
`build_document` now calls it (same behaviour, same try/except), and the shell receives it
as an injected `render_view` callable (`ot_shell.build_ot_document`). This keeps the module
dependency one-directional (`app → ot_shell`), reuses the existing routing without
duplicating it, and means every embedded panel is byte-for-byte the dispatch's output —
pinned by test C, which asserts each embedded panel equals the corresponding
`build_view_section` return for the same state.

## 7. Bilingual approach

Two deliberately unequal levels, stated honestly in both languages on every screen:

* **Level 1 — the shell** (English + Persian): title, subtitle, tab labels, the System
  Guide, every tab explanation, the language selector (English | فارسی), footer and honesty
  notes. Persian was written as polished natural prose, not machine translation, following
  the wave glossary.
* **Level 2 — the technical panels**: embedded renderer output stays exactly as the existing
  renderers produced it (English, LTR). Translating renderer internals is a separate future
  wave; the shell instead carries the mandated note in both languages — *"Detailed technical
  panels are currently shown in English. The management guidance and navigation are available
  in English and Persian." / جزئیات فنی پنل‌ها در این نسخه به زبان انگلیسی نمایش داده
  می‌شوند؛ راهنمای مدیریتی و مسیرهای اصلی به دو زبان فارسی و انگلیسی در دسترس هستند."*

Technical identifiers (`kiln_fuel_rate_tph`, MAE, R², kWh/t, …) are never translated. The
honesty labels from `src/labels.py` stay verbatim English — they are PRD wording.

## 8. Language switch and RTL

The switch is **CSS state, not a second document**: both languages always ship in the file.
A few lines of inline JavaScript (`otSetLang`) write `lang` and `dir` on the `<html>`
element (`lang="en" dir="ltr"` ⇄ `lang="fa" dir="rtl"`), update `document.title`, and CSS
rules `html[dir="ltr"] .ot-fa{display:none}` / `html[dir="rtl"] .ot-en{display:none}` toggle
visibility — no reload, no external file, no framework. Tabs switch the same way
(`otShowTab`). Without JavaScript the document degrades gracefully: the script adds a
`ot-js` class to `<body>`, and in its absence all tab panels display in sequence and both
languages show (nothing is hidden behind a script that cannot run).

Every embedded technical panel sits in an `.ot-tech` block pinned to `dir="ltr"`, so RTL
layout can never reorder a technical table, an SVG chart or an identifier. The switch
script addresses only the shell's own `ot-` classes — a test pins that it never references
`dt-` (renderer) classes.

## 9. Self-contained approach

The document embeds the theme stylesheet, its own scoped CSS and its own single inline
`<script>`; it references no network resource (the only absolute URI is the SVG XML
namespace identifier, which browsers never fetch). It opens from the filesystem with a
double click. A test enumerates every external reference shape (`<link`, `<img`,
`@import`, `<script src`, bare `http(s)://`) and fails on any.

## 10. Tests — `tests/test_task6_ot_shell.py` (23 tests)

The wave's A–J list, all green:

* **A — existence**: the document builds; `python app.py --view OT` writes it and exits 0;
  OT is not an eleventh `VIEWS` row (registry stays at 10); `--view OT` with another view
  exits 2 ("on its own").
* **B — tabs**: all ten tabs, in order, each a panel *and* a nav button; Kiln carries B+C
  and Mill E+F; each tab's bilingual explanation present.
* **C — renderer reuse**: every embedded panel byte-identical to the shared dispatch's
  output; the timings map names exactly the embedded views.
* **D/E — both modes**: English is the shipping state (`lang="en" dir="ltr"`, EN
  title/subtitle/labels); Persian fully present (FA title/subtitle/labels/guide headings);
  the switch carries `fa`/`rtl`.
* **F — switching**: pure CSS state; technical panels exist exactly once (never duplicated
  per language); the script never touches panel classes; every panel LTR-pinned.
* **G — self-contained**: zero external assets; exactly one inline script.
* **H — determinism**: two builds over the same state are byte-identical.
* **I — honesty**: all verbatim standing statements and the bilingual technical-panels note
  present; the forbidden control label absent; no "confidence" wording anywhere.
* **J — no fabricated alerts**: the four card sources, in order, each carrying its
  payload-traceable strings; no numeric score on the Alerts tab; the traceability note
  present.

## 11. Verification and git safety

* **Browser verification (honest):** browser automation was not available in this
  environment (Node v24 is present; jsdom and Playwright are not installed, and the
  document must not depend on them anyway). Performed instead: the full static validation
  suite (structure, tag balance via `html.parser`, tab/button pairing, self-containedness,
  entity correctness), plus `node --check` on the extracted inline script — JavaScript
  syntax valid. Click-through of the language and tab switching in a real browser remains a
  manual step for the user; the mechanism is CSS state and inline JS with a no-JS fallback,
  so a failure mode would be visible, not silent.
* **Cell 12:** updated additively — it now also writes the OT artifact via
  `build_ot_platform_document` and adds it to the zip bundle; every existing export and all
  16 `tests/test_task6_notebook.py` contracts unchanged and passing.
* **Frozen digests** (`src/models`, `src/process_models`, `src/optimization`, `src/simulation`,
  `src/features`, `src/data_generation`, `configs`, `pyproject.toml`; frozen pre-Task-6
  tests): re-verified with the commands in `docs/PROJECT_STATE.md` §"Frozen-layer
  protection" — unchanged before and after.
* **Full regression:** run exactly once, at the end; the actual count is recorded in
  `docs/PROJECT_STATE.md` (not assumed from any previous wave).

## 12. Limitations (stated, not hidden)

1. The technical panels are English/LTR in this version (see §7) — translating them is a
   separate future wave with its own glossary work.
2. No browser automation run (see §11); validation is static + JS syntax check.
3. The Alerts tab shows the current system's standing state; it has no history, no
   acknowledgement, no notification — none of which exist in any payload, and inventing
   them was out of scope.
4. The artifact regenerates only via `--view OT` (or notebook cell 12); there is no
   file-watcher/live mode.
5. Persian text renders with system fonts; no webfont is embedded (self-containedness
   forbids fetching one, and embedding a full Persian typeface would bloat the file).

## 13. Recorded future item (not investigated, not fixed)

**Cell 3 startup-transition energy-balance residual.** The data-generation diagnostics in
notebook Cell 3 show a high raw `energy_balance_residual_pct` peak during the
startup-transition period of the simulated plant (the value comes from
`src/process_models/plant.py:152`, `residuals["energy_pct"]`). Per this wave's instructions
this is **recorded only**: it is flagged as a separate future **read-only conservation
review** item — inspect whether the startup transient's raw residual peak is expected
behaviour of the conservation accounting or warrants attention. No analysis, change or fix
was made here, and none should be made outside that review.
