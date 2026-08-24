# TASK 6 RECOVERY PLAN

**Date:** 2026-08-24
**Scope:** `src/digital_twin/` (12 modules, 6,196 LOC) + `src/visualization/` (5 modules, 2,224 LOC) = 17 files, 8,420 LOC
**Method:** six independent read-only fan-out audits (Tracks A/B/C2/D/E/F) + independent lead-agent verification against source
**Nothing was implemented, installed, initialized, or deleted while producing this plan.** Integrity verified: 106 files hashed before and after — `CHANGED: NONE  DELETED: NONE  ADDED: NONE`.

---

## 1. Executive conclusion

Task #6 was **never finished, but almost nothing in it needs to be thrown away**. The previous session produced 8,420 LOC of structurally sound, architecturally correct code that is *approximately* half of the required scope, and then stalled — not because the code is wrong, but because **there is no way to run it and no way to test it**. Those two absences are the entire root cause of the context thrashing:

- **No host.** There is no `app.py`, no `__main__.py`, no notebook, no `[project.scripts]` entry, nowhere in the repository that constructs a `DashboardSession` and renders anything. The only `if __name__ == "__main__"` guard in the whole tree is in `src/models/model_card.py:1084`. 8,420 LOC of dashboard exists and cannot be launched.
- **No tests.** Zero of the 428 passing tests touch `src/digital_twin/` or `src/visualization/`. Zero of the PRD's 13 Task #6 acceptance criteria are tested. So every prior session had to re-derive correctness by reading code — which is precisely the behaviour that burns context until the API fails.

The result is a project that *looks* complete when inspected module-by-module and *is* incomplete when judged by the user's own no-false-completion rule. Modules exist, classes import, files are large — none of which is completion.

Two real defects were found and confirmed by measurement, not inference:

- **BUG 1 (P0):** `ValueError: Input X contains NaN` kills roughly **7 % of live frames**. Path: `state.py:747` → `synthetic.py:1235 get_predictions` → `models/model_a.py:213`. Cause: a double outer-join in `_model_history` (`synthetic.py:1171-1189`) injects 267 NaN cells. It is unguarded — `state.py:771-775` catches only `CapabilityError`.
- **BUG 2 (moderate):** wall-clock `runtime_s` injected at `synthetic.py:1372-1374` makes views I and J non-reproducible, so their payloads cannot be golden-tested.

And one measurement changes the shape of the whole plan: **`views()` takes 7.9 s** because it eagerly builds all ten views (`state.py:858-861`), of which H/I/J cost 1.0–4.9 s each. With a stub provider the same call takes **0.4 ms** — so the cost is 100 % provider data-fetching, not view assembly. **Switching to the already-existing lazy `state.view()` API puts 9 of 10 views inside 2.0 s with zero caching added.**

The fastest safe path is therefore not more code — it is **a git baseline, a stub-provider test fixture, and a ~120-line entrypoint**, in that order. After those three things exist, the remaining work becomes independently verifiable and parallelizable, and the thrashing stops.

**Recommended decision: OPTION B — pause and bootstrap first.** See Section 13.

---

## 2. Current Task #6 status

# PARTIALLY IMPLEMENTED

**Why this label and not another.** Two labels were candidates.

*"IMPLEMENTED BUT NOT RUNNABLE"* describes the built subset perfectly — and for that subset it is the dominant condition. But a material fraction of required scope **was never implemented at all**:

| Required | State |
|---|---|
| 4 of 10 PRD views (Time-Series Explorer, Model Performance, Data Quality, Factory Data Requirements) | absent |
| Factory Presentation Mode (directive item 17: *"This is a critical requirement"*) | config keys only, `settings.py:129` |
| Colab notebook (PRD FR-17 / §25, NFR-9) | absent |
| 5 of 7 PRD §35 documents | absent |
| Any test of Task #6 | absent |
| Any rendering for the 8 non-twin views | absent |

Calling that "implemented" would violate the user's own instruction: *"Do not say Task #6 is complete merely because modules exist, classes import, tests pass, files are large."* The same rule cuts the other way too — the code that *does* exist is real and works, so "NOT STARTED" is equally false.

**Evidence for what is genuinely working:**

- All 16 Task #6 modules import cleanly. Import cost 1.27–1.5 s.
- `DashboardSession.build()` completes in 13.3–16.6 s (96.6 % of it the model layer).
- **`twin_document()` already produces 23,288 bytes of self-contained animated HTML** — `@keyframes` and `<svg>` present, **with zero UI dependencies installed**. The single most visually important deliverable in Task #6 works today.
- `DataProvider` ABC is complete and strict: 15 abstract methods, 11 concrete inherited, `SyntheticDataProvider` implementing all of them, `RealPlantDataProvider` raising `NotImplementedError` on all 14 data methods while keeping `capabilities`/`describe`/`__init__` live. This is exactly what directive item 1 asked for.
- Four provenance channels (OBSERVED / TRUTH / PREDICTION / RECOMMENDATION) are modelled and not co-mingled.
- Ten view builders exist and are registered in `state.py:76-87 VIEWS`; a lazy accessor already exists at `state.py:848-856`.

**Approximate completion:** structure ~85 %, required user-facing surface ~35 %, verified surface **0 %**.

---

## 3. What is already good and must NOT be rewritten

These are load-bearing and evidence-backed. Touch them only to add, never to restructure.

| # | Asset | Evidence it is sound | Directive/PRD anchor |
|---|---|---|---|
| 3.1 | **`provider.py` DataProvider ABC** | 15 abstract methods cover all 10 required data kinds; `RealPlantDataProvider` proves substitutability without dashboard changes | directive 1 |
| 3.2 | **`SyntheticDataProvider`** | 62 methods, all contract methods implemented, measured working | directive 1 |
| 3.3 | **Provenance model (`payloads.py`)** | four channels distinct; grep found no payload mixing them | directive 1, NFR-6 |
| 3.4 | **`twin.py` SVG renderer** | `render_twin` (:544) → `twin_html` (:684) → `twin_document` (:705); emits 23 KB working animated HTML with **no dependencies** | directive 4 ("SVG not GIF") |
| 3.5 | **Ten view builders + `VIEWS` registry** | `state.py:76-87` maps A–J exactly onto directive item 2's list | directive 2 |
| 3.6 | **Lazy `state.view()` accessor at :848-856** | already exists; the fix for the 7.9 s problem is to *use* it, not write it | directive 23 |
| 3.7 | **`clock.py` simulation clock** | PLAY/PAUSE/RESET/STEP + speed control present | directive 7 |
| 3.8 | **Plotly optional-import guard** | `charts.py:34-40`; `to_figure` (:445) raises at :451-455, `to_html` (:531) degrades to `missing_chart_html` at :544-545 | NFR-7 |
| 3.9 | **`missing_chart_html` (:555)** | **audit's "dead code" claim REFUTED** — live caller at `charts.py:544-545`, returns a 275-char themed card | — |
| 3.10 | **`DashboardSession.build(training=…, run=…)` fast path** | documented at `session.py:412-414`; correct and currently unused — wire it, don't rewrite it | directive 23 |
| 3.11 | **All of Tasks #1–#5** | 428 tests green; **zero** frozen-layer imports of Task #6 (3 grep hits, all string-literal or docstring) | user freeze directive |

**Explicitly do not do these**, despite audit suggestions:

- **Do not split `synthetic.py`.** `self.mode` is read across 22 of its 62 methods. Splitting it means re-threading mode state through new boundaries with no tests to catch the mistakes. This is the exact "LARGE REFACTOR" the user prohibited absent proof of necessity, and there is no such proof.
- **Do not fix the import "cycle."** A package-level cycle does exist (`session.py:59` and `state.py:68` import `src.visualization.clock`, which imports `digital_twin.payloads/provider/settings`) but the **module graph is acyclic** — no `ImportError` is reachable. It is a layering smell, not a defect.
- **Do not touch `_indexed`.** Audit P1-1 applies only to the REPLAY branch; `_frame` totals 21 ms of a 7,900 ms frame.

---

## 4. What is actually missing

### 4.1 Blocking absences (nothing can be verified without these)

| ID | Missing | Evidence |
|---|---|---|
| M-1 | **Any executable entrypoint** | no `app.py` / `__main__.py` / `main.py` / `dashboard.py` / `*.ipynb` / `run*.py`; no `notebooks/`, `scripts/`, `bin/`, `examples/`, `demo/`; no `[project.scripts]` in `pyproject.toml` |
| M-2 | **Any test of Task #6** | 0 of 428 tests import `digital_twin` or `visualization`; 0 of 13 acceptance criteria tested |
| M-3 | **Version control** | no `.git` in the repo, in `H:/vibe coding`, or in `H:/`; no `.gitignore`; 8,420 LOC with no recovery point |

### 4.2 Missing required scope

| ID | Missing | Anchor |
|---|---|---|
| M-4 | **Renderers for the 8 non-twin views** — builders return payloads; only the twin has a renderer | directive 2, 3, 5, 6 |
| M-5 | **4 PRD views:** Time-Series Explorer, Model Performance, Data Quality, Factory Data Requirements | PRD §17:690 numbered table |
| M-6 | **Factory Presentation Mode** — 10 required elements, config keys only today | directive 17 (*"critical requirement"*), FR-12, PRD §29 |
| M-7 | **Demo scenario controls** (10 named scenarios) + **"Run Demo" 11-step sequence** | directive 18, 19 |
| M-8 | **Historical-mode UI** (timeline, timestamp, play/pause, scrubber, replay speed) | directive 8 |
| M-9 | **Colab notebook** — must render in a cell with no tunnelling | PRD FR-17/§25, NFR-9 |
| M-10 | **5 of 7 PRD §35 documents:** README.md, ARCHITECTURE.md, DATA_DICTIONARY.md, DEMO_GUIDE.md, **FACTORY_DATA_REQUIREMENTS.md**. Only MODEL_CARD.md and SIMULATION_ASSUMPTIONS.md exist | PRD §35:1109-1119 |
| M-11 | **PRD §34:1104 no-hard-coding audit test** (extended: every displayed numeric field *and every animation parameter*) | NFR-6, AC-12, AC-21 |
| M-12 | **Downsampling for long historical windows** | directive 23 |
| M-13 | **The Task #6 directive itself is not on disk** — 25 numbered items, cited 87× in code, recovered only from transcripts | see Section 12.4 |

---

## 5. Critical blockers

Ordered by what stops progress soonest.

### B-1 — No version control on 8,420 LOC (severity: CRITICAL)
Every subsequent phase is unsafe. There is no diff, no revert, no bisect, no way to prove a change didn't break something. Confirmed: Git 2.54.0.windows.1 is installed, global identity is configured (`Ali Sheikhali` / `milad5143@yahoo.com`), no `.git` anywhere in or above the project, no `.gitignore`, no backup artifacts.
**Fix:** phase 6A. **Cannot be initialized without explicit user approval** (see Section 12).

### B-2 — No runnable surface (severity: CRITICAL)
Task #6's deliverable is a *dashboard*. Nothing launches it. Track C2's list of existing files that must change to add a host is **EMPTY** — a new repo-root `app.py` of roughly 120 LOC, using zero new dependencies, is sufficient.
**Fix:** phase 6C.

### B-3 — Zero test coverage of Task #6 (severity: CRITICAL)
No oracle exists, so every session must re-read code to establish correctness. This *is* the thrashing mechanism.
**Fix:** phase 6B (18 Tier-1 P0 tests against a stub provider, target < 1 s total).

### B-4 — BUG 1: NaN crash on ~7 % of live frames (severity: SEVERE / P0)
`ValueError: Input X contains NaN`. `state.py:747` → `synthetic.py:1235` → `models/model_a.py:213`. Double outer-join at `synthetic.py:1171-1189` injects 267 NaN cells. `state.py:771-775` catches only `CapabilityError`, so the exception escapes and kills the frame.
**Fix:** phase 6E, first item. This is a Task #6 data-assembly bug — the guard belongs in `synthetic.py`/`state.py`, **not** in `models/model_a.py`, which is frozen.

### B-5 — Zero UI dependencies installed (severity: HIGH, but self-clearing)
plotly, ipywidgets, IPython, jupyter, notebook, ipykernel, streamlit, dash, panel, bokeh, matplotlib, kaleido — **all missing**. This is only a blocker if the plan depends on them. It does not: `twin_document()` proves the SVG/HTML path needs none of them. Plotly then becomes a **no-code-change upgrade** later, because `charts.py` already degrades gracefully.
**Fix:** phase 6A decides; the recommendation is to build the zero-dependency path first and defer installs.

### B-6 — `views()` eager build costs 7.9 s (severity: HIGH)
`state.py:858-861` builds all ten views per frame. Per-view: A–G 9.6 ms, H 1.04–1.27 s, I 1.86–2.21 s, J 3.17–4.87 s. Against NFR-2's < 3 s budget this fails for any screen.
**Adjudicated:** this is **eagerness, not redundancy** — Track D measured exactly **1** call per frame each to `get_optimization`, `run_what_if`, `get_predictions`, `get_anomaly_state`, refuting audit P0-2.
**Fix:** phase 6E — call the existing `state.view()` (`:848-856`) instead of `views()`. **9 of 10 views land inside 2.0 s with no caching added.**

### B-7 — T1-06 fails today (severity: MODERATE, honesty violation)
A stub provider reporting `capabilities().synthetic = False` still renders "Synthetic Demonstration" because `state.py:570` hard-codes it. That is an NFR-6 violation *and* a directive-20 honesty violation in the same line.
**Fix:** phase 6B surfaces it, 6D fixes it.

---

## 6. Non-critical issues

| ID | Issue | Why it is not a blocker |
|---|---|---|
| N-1 | **BUG 2** — wall-clock `runtime_s` at `synthetic.py:1372-1374` makes views I/J unhashable | affects golden-test strategy only; fix by excluding the field or injecting a clock (phase 6E) |
| N-2 | Package-level import cycle via `visualization.clock` | module graph acyclic; no `ImportError` reachable — layering smell only |
| N-3 | `refresh_seconds: 2.0` in `dashboard.yaml:80` | self-imposed, explicitly tagged `# ASSUMPTION`, and **read by nothing** (only `settings.py` parse/validate/describe). The real budget is NFR-2 < 3 s, **measured at 1.94 s — already passing.** Audit D-4's PRD attribution is an invented requirement. |
| N-4 | `proposed_setpoints` naming risk (audit §6 risk 2) | **0 occurrences** in Task #6 — a latent risk avoided by construction, not a present defect |
| N-5 | 31 of 33 test-label assertions unpinned | audit's "no label text asserted" is wrong in 2 cases (`test_model_b_anomaly.py:351-352`) but the substance holds; a 6H hardening item |
| N-6 | Audit T-5 (`is not None` weakness) | **substantially wrong** — 12 of 13 are type-narrowing guards followed by real assertions |
| N-7 | `.pytest_cache` shows 436 nodeids vs 428 collected | ordinary lag: exactly 8 stale nodeids — 3 from deleted scratch files (`test_zzprobe.py`, `test_zzreport.py`, orphaned `.pyc`), 5 from renamed/removed tests. `--collect-only` = 428 is authoritative. **No action.** |
| N-8 | `real_plant.py:71` cites `FACTORY_DATA_REQUIREMENTS.md`, which does not exist | resolves when 6I creates the file (which PRD §35:1119 mandates anyway) |
| N-9 | `pyproject.toml` has no `[project.scripts]` and no pytest markers | quality-of-life; add the console script in 6C, markers in 6H |

---

## 7. Recommended implementation order

Phases keep the user's 6A–6I labels for traceability; **scope has been restated where evidence demanded it**, and each change is flagged.

### 6A — Repository recovery, Git baseline, dependency decision
**Objective:** make every later phase reversible, and settle the dependency question once.
**Inputs:** current tree (106 files verified clean), `pyproject.toml`, installed-package audit.
**Files:** `.gitignore` (new), `pyproject.toml` (optional `[project.scripts]`), `docs/TASK6_DIRECTIVE.md` (new — persist the recovered directive).
**Dependencies:** none. **Blocks everything.**
**Expected output:** one commit containing the full current state; a written dependency decision; the 25-item directive on disk.
**Tests:** re-run the 428 baseline post-commit (must stay 428); `git status` clean.
**Complexity:** S. **Parallel:** no — strictly serial, first. **Risk:** LOW.
**Notes:** `.gitignore` must exclude `data/` (74 MB), `models/*.joblib` (61 files, 207 MB), `reports/`, `__pycache__`, `.pytest_cache`. **`models/registry.json` must be TRACKED** — it is the envelope training-range source (`envelope.training_range_source`). Largest single data file: `data/synthetic/kiln_truth.csv` at 14.5 MB. Source code is only ~2 MB / 101 files, so the tracked repo stays small.

### 6B — DataProvider verification + stub fixture *(scope changed)*
**Original scope was "implement the DataProvider abstraction." It already exists and is correct (Section 3.1–3.2), so this phase becomes verification.**
**Objective:** create the test oracle that makes every later phase checkable in under a second.
**Inputs:** `provider.py` (15 abstract methods), `synthetic.py`, `real_plant.py`.
**Files:** `tests/conftest.py` (`stub_provider` fixture), `tests/test_task6_provider_contract.py` (new).
**Dependencies:** 6A.
**Expected output:** a stub `DataProvider` returning fixed values; 18 Tier-1 P0 tests running in **< 1 s** (measured basis: `views()` against a stub is 0.4 ms).
**Tests:** the 18 themselves — contract completeness, provenance separation, `RealPlantDataProvider` raising correctly, substitutability, T1-06 (the `state.py:570` honesty failure, expected RED until 6D).
**Complexity:** M. **Parallel:** yes — with 6C. **Risk:** LOW (test-only).

### 6C — Minimal runnable host
**Objective:** make Task #6 launchable.
**Inputs:** `session.py` `build()`, `state.py` `view()`, `twin.py` `twin_document()`.
**Files:** `app.py` at repo root (new, ~120 LOC). **Track C2 confirmed the set of existing files that must change is EMPTY.**
**Dependencies:** 6A.
**Expected output:** `python app.py` writes/serves self-contained HTML including the working animated twin, using **zero new dependencies**.
**Tests:** smoke test — process exits 0, output contains `<svg` and `@keyframes`; 428 unaffected.
**Complexity:** M. **Parallel:** yes — with 6B. **Risk:** LOW (purely additive).

### 6D — Dashboard view renderers
**Objective:** turn payloads into screens.
**Inputs:** the 10 existing builders; the 4 missing PRD views.
**Files:** `src/visualization/` renderers; new builders for Time-Series Explorer, Model Performance, Data Quality, Factory Data Requirements; fix `state.py:570`.
**Dependencies:** 6B (oracle), 6C (host).
**Expected output:** all 14 views render; no literal numerics; `state.py:570` derives the badge from `capabilities()`.
**Tests:** per-view render tests; T1-06 flips GREEN; NFR-6 scan.
**Complexity:** L — the largest phase. **Parallel:** yes — with 6E, 6F. **Risk:** MEDIUM (largest surface, but additive and now test-covered).
**Constraints from the directive:** ranges come from existing configuration (item 5: *"Do NOT hard-code new engineering limits into the UI"*); uncertainty as spread, never a confidence percentage (items 10, 14); show specific **and** total energy (item 12); What-If sliders use the exact configured step sizes (item 13); rejected candidates stay visible (item 16).

### 6E — Frame correctness + render-path performance *(scope changed)*
**Original scope was "caching/performance optimization." Evidence says correctness first, then laziness — and that caching is not needed to hit the budget.**
**Objective:** stop the 7 % frame crash; get views inside NFR-2 without caching.
**Inputs:** BUG 1 path; `state.py:858-861` vs `:848-856`; `session.py:412-414` fast path.
**Files:** `synthetic.py` (`_model_history` NaN guard at :1171-1189, `runtime_s` at :1372-1374), `state.py` (guard at :771-775, prefer `view()` over `views()`), `session.py` (wire the fast path).
**Dependencies:** 6B.
**Expected output:** zero NaN crashes; 9 of 10 views inside 2.0 s; views I/J reproducible.
**Tests:** NaN regression test; per-view timing assertions; determinism/golden tests for I/J.
**Complexity:** S. **Parallel:** yes. **Risk:** LOW-MEDIUM.
**Explicitly:** **add no caching in this phase.** Per the user's rule, classify first (Section 10); measurement says laziness alone suffices.

### 6F — Animated SVG twin verification
**Objective:** prove the twin meets directive item 4 and lock it against regression.
**Inputs:** `render_twin` (:544), `twin_html` (:684), `twin_document` (:705).
**Files:** `tests/test_task6_twin.py` (new); `twin.py` only if a provenance gap is proven.
**Dependencies:** 6B.
**Expected output:** determinism test; **AC-21 animation-provenance test** — every animation parameter traced to a provider/model/snapshot call, no literals.
**Tests:** byte-stable output for a fixed seed; SVG/`@keyframes` presence; no-GIF assertion; PRD §19.4 parameter provenance.
**Complexity:** S/M. **Parallel:** yes — with 6D. **Risk:** LOW (already works; this is mostly pinning it).

### 6G — Factory Presentation Mode
**Objective:** deliver directive item 17 — *"This is a critical requirement."*
**Inputs:** `settings.py:129` config keys; PRD §29; directive items 17, 18, 19.
**Files:** new presentation renderer; scenario controls; the "Run Demo" sequence.
**Dependencies:** 6D, 6F.
**Expected output:** all 10 required elements; the 10 named scenarios; the 11-step demo; *"The user should be able to run a complete demonstration without opening notebooks or developer tools."*
**Tests:** all 10 elements present; scenario switching propagates to twin + anomaly + prediction; sensor-drift still shows **"Evidence inconclusive"**; explicit synthetic disclaimer present.
**Complexity:** L. **Parallel:** yes — with 6H, 6I. **Risk:** MEDIUM.

### 6H — Task #6 §34 tests
**Objective:** satisfy PRD §34:1104 and harden the suite.
**Inputs:** PRD §34; the 16 directive-22 test areas.
**Files:** `tests/test_task6_*` ; pytest markers in `pyproject.toml`.
**Dependencies:** static scans (T4-01/03/06) can start at **6A**; full suite needs 6D/6F/6G.
**Expected output:** the extended no-hard-coding audit test; 13 of 13 acceptance criteria covered; no-"confidence %" and no-"automatic control" language scans.
**Tests:** itself. Suite must end at **≥ 428 passed**.
**Complexity:** M. **Parallel:** yes (static scans very early). **Risk:** LOW.

### 6I — Colab notebook + documentation
**Objective:** NFR-9 and PRD §35.
**Inputs:** the 6C host; PRD §35:1109-1119.
**Files:** `notebooks/demo.ipynb` (new); `README.md`, `docs/ARCHITECTURE.md`, `docs/DATA_DICTIONARY.md`, `docs/DEMO_GUIDE.md`, `docs/FACTORY_DATA_REQUIREMENTS.md`.
**Dependencies:** docs drafting can start at 6A; the notebook needs 6C.
**Expected output:** a notebook rendering in one Colab cell with no tunnelling; the 5 missing §35 documents; documentation of the 8 directive-24 topics.
**Tests:** notebook JSON validity; `FACTORY_DATA_REQUIREMENTS.md` exists (clears N-8).
**Complexity:** M/L. **Parallel:** yes. **Risk:** LOW.
**Honest caveat:** with jupyter/ipykernel not installed, the notebook can be **written and structurally validated** locally but **not executed** locally. Either install jupyter in 6A or accept that Colab is the first real execution — say which in the final report rather than implying local verification.

---

## 8. Parallelization plan

```
WAVE 1  (serial, alone)
        6A  git baseline · .gitignore · dependency decision · persist directive
         │
         ├──────────────┬──────────────────┬─────────────────────┐
WAVE 2   6B             6C                 6H-static             6I-docs
        provider tests  app.py host        T4-01/03/06 scans     draft 5 docs
         │              │
         └──────┬───────┘
                │
         ┌──────┼──────────────┐
WAVE 3   6D     6E             6F
        views   frame fix +    twin verify
                laziness       + AC-21
                │
         ┌──────┼──────────────┐
WAVE 4   6G     6H-full        6I-notebook
        present full §34 suite  Colab
```

**Concurrency-safety notes.**
- 6B ∥ 6C is safe: 6B touches only `tests/`, 6C only adds `app.py`.
- 6D ∥ 6E both touch `state.py` — **6E's edits are small and localized** (`:771-775` guard, `views()`→`view()`), 6D's are additive renderers plus `:570`. Land 6E first within the wave, or assign both to one worker if the git history should stay linear.
- 6H's static scans need no runnable surface at all, so they front-load usefully.
- Only 6A is genuinely serial. Everything else has a parallel partner.

**Per the user's instruction, this is not one giant Task #6 implementation** — nine phases, each independently testable, none requiring the whole system to be correct before it can be verified.

---

## 9. Test strategy

**Baseline is verified and exact:** `python -X utf8 -u -m pytest -q -p no:cacheprovider` → **428 passed in 276.92s, exit 0**. Matches the expected reference precisely; there is no discrepancy to investigate. This is the regression floor: **every phase must end at ≥ 428.**

**Four tiers.**

- **Tier 1 — P0 contract tests (18, target < 1 s, phase 6B).** Stub `DataProvider`; assert contract completeness, the four provenance channels never mixed, `RealPlantDataProvider` raising on all 14 data methods, substitutability, and T1-06 (the `state.py:570` honesty failure — expected RED until 6D). Fast because a stub makes `views()` cost 0.4 ms instead of 7.9 s.
- **Tier 2 — render/payload tests (6D, 6F).** Per-view render; determinism under fixed seed; golden payloads (requires BUG 2 fixed or `runtime_s` excluded); no-literal-numerics per view.
- **Tier 3 — static honesty/provenance scans (can start at 6A).** PRD §34:1104 extended audit: every displayed numeric field **and every animation parameter** (§19.4) traced to a `DataProvider`/model/`Twin.current_state_snapshot()` call. Plus scans for "confidence %", "automatic control", real-connectivity language (directive 20), and the "Synthetic Demonstration" / "Decision Support Only" labels.
- **Tier 4 — integration/acceptance (6G, 6H).** 13 of 13 PRD acceptance criteria (**0 of 13 covered today**); scenario switching propagating to twin + anomaly + prediction; sensor drift still yielding "Evidence inconclusive"; the 11-step demo sequence end to end; NFR-2 timing.

**Speed discipline.** Every Task #6 test must run against a stub provider unless it is explicitly an integration test. The real provider costs 7.9 s per frame; a suite built on it would become unrunnable and the thrashing would return.

**Do not modify existing tests.** They are the regression reference. N-5's unpinned labels are hardened by **adding** assertions, not by editing the 428.

---

## 10. Performance strategy

Per the user's rule, classify **before** caching anything.

| Category | Examples | Cacheable? |
|---|---|---|
| Immutable | config, envelope training ranges, `models/registry.json`, unit metadata | **yes** — safe, load once |
| Deterministic in seed + scenario + timestamp | synthetic truth series, historical windows | **yes**, keyed on `(seed, scenario, window)` |
| Depends on current state | `current_state_snapshot`, KPIs, equipment status | **no** — invalidates every frame |
| Depends on scenario | anomaly state, regime | only within one scenario; must invalidate on switch |
| Depends on timestamp | replay frames | only per exact timestamp |
| Depends on model inference | Model A predictions, Model B scores | keyed on the exact feature vector, or not at all |
| Wall-clock contaminated | `runtime_s` (`synthetic.py:1372-1374`) | **never** — and it must be excluded from any cache key (BUG 2) |

**The finding that makes caching mostly unnecessary.**

- Current: `views()` = **7.9 s** steady-state live (A–G 9.6 ms, H 1.04–1.27 s, I 1.86–2.21 s, J 3.17–4.87 s; render 0.01 s).
- With a stub provider: **0.4 ms.** Therefore the 7.9 s is 100 % provider data-fetching.
- **Laziness alone → 9 of 10 views inside 2.0 s, zero caching added.**
- NFR-2 (< 3 s what-if round trip) is **already MEASURED at 1.94 s — passing today.**
- `refresh_seconds: 2.0` (`dashboard.yaml:80`) is self-imposed, tagged `# ASSUMPTION`, and read by nothing. It is not a PRD requirement and must not drive optimization.

**Sequence:** (1) fix BUG 1 — a crashing frame has no meaningful latency; (2) switch to `state.view()`; (3) wire the unused `session.py:412-414` fast path; (4) **measure again**; (5) add downsampling for long historical windows (directive 23 — *"Do not stream thousands of unnecessary points"*); (6) only then consider caching, and only in the "yes" rows above. View J at 3.17–4.87 s is the sole view still over budget after laziness and is the only justified caching candidate.

**Do not** cache `get_optimization` / `run_what_if` / `get_predictions` / `get_anomaly_state` for redundancy reasons — Track D measured exactly **1** call per frame each. Audit P0-2's redundancy claim is refuted; the defect was eagerness.

---

## 11. Regression protection for Tasks #1–#5

**Frozen and untouched:** process models, model-training pipeline, Model A, Model B, optimization, envelope gating, hard constraints, baselines, what-if core, synthetic physics and configuration. No tuning of thresholds, training ranges, physics, optimization weights, safety constraints, OOD thresholds, the uncertainty ceiling, model targets, or process equations.

**The structural fact that makes this easy:** **zero frozen-layer imports of Task #6.** A grep for backward dependencies returned 3 hits, all string-literal or docstring. Dependency flow is strictly Task #6 → Tasks #1–#5. **Task #6 can be freely restructured without any possibility of regressing the 428.**

**Protections:**

1. **428 gate on every phase.** Any drop stops the phase and is investigated, never "fixed" by editing tests.
2. **BUG 1's guard goes in Task #6 code**, not in `models/model_a.py:213`. Model A raising on NaN input is correct behaviour; supplying NaN is the Task #6 bug.
3. **Config is read-only to Task #6.** Ranges, steps, and limits come from existing configuration (directive 5: *"Do NOT hard-code new engineering limits into the UI"*; directive 13: *"Do not invent ranges"*).
4. **`models/registry.json` stays tracked** in git — `envelope.training_range_source` depends on it. Only the `.joblib` blobs are ignored.
5. **No new physics.** Directive 18: *"Do not invent new physics"*; closing line: *"The dashboard is a presentation and decision-support layer over the existing validated implementation, not a new modeling layer."*
6. **Sensor-drift limitation preserved** — "Evidence inconclusive" stays, and gets a test (directive 11, 18).
7. **Pre/post file-hash manifest** for each phase, as used to verify this plan (106 files, clean).

---

## 12. Git / recovery strategy

### 12.1 Established facts
- **No `.git`** in `H:/vibe coding/digital_Twin`, in `H:/vibe coding`, or in `H:/`. The project is **not** a repository and is **not** inside a parent repository.
- Git **2.54.0.windows.1** installed; global `user.name = Ali Sheikhali`, `user.email = milad5143@yahoo.com`.
- No `.gitignore`, no `.gitattributes`, no backup or snapshot artifacts anywhere.
- **287 MB total** — but only ~2 MB / 101 source files. The bulk: `data/` 74 MB, `models/` 207 MB (61 `.joblib`, 4 parquet, 4 csv, 3 json). Largest single file `data/synthetic/kiln_truth.csv` = 14.5 MB.
- Current tree **verified clean**: 106 files hashed pre/post audit, zero changes.

### 12.2 Recommended procedure (requires explicit user approval — **not performed**)
Per the user's instruction (*"Do NOT initialize Git automatically yet"*), nothing below has been executed.

1. **Write `.gitignore` FIRST**, before any `git init`. Ignore `data/`, `models/*.joblib`, `reports/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`. **Do not ignore `models/registry.json`.**
2. `git init` at `H:/vibe coding/digital_Twin`.
3. `git status` and **review the staged list** — confirm ~101 source files and that no 14 MB CSV or 207 MB of joblib is included.
4. Single baseline commit of the current verified-clean state. This is the recovery point for all of 6B–6I.
5. Re-run the 428 suite post-commit to confirm the commit changed nothing.
6. Branch per phase (`task6/6b-provider-tests`, `task6/6c-host`, …) so each phase is independently revertable.

**Nothing is deleted, reset, or checked out.** The first commit is purely additive; the working tree is already the desired baseline.

### 12.3 If the user declines git
Fall back to a dated full-tree copy before each phase, plus the pre/post hash manifest. This is strictly worse (no diffs, no bisect) and should be presented as such — but it is better than the current zero-recovery state.

### 12.4 Recover the lost requirements document (recommended 6A deliverable)
The authoritative Task #6 directive — **25 numbered items** — is **cited 87 times in the code** and **absent from disk**. It was recovered from Claude transcripts during this audit. It is the only source for roughly a third of Task #6's requirements, including item 17 (Factory Presentation Mode, *"This is a critical requirement"*), items 18–19 (demo scenarios and the 11-step sequence), item 20 (the honesty rules), and item 25 (the 21-field final report).

**Persist it to `docs/TASK6_DIRECTIVE.md` as part of 6A.** If it is lost again, the same traceability gap that helped produce this recovery situation reopens. This is the single highest-leverage low-cost action in the plan.

---

## 13. Definition of Done

Task #6 is done when **all** of the following hold. Anchored on directive item 25's 21 report fields and the PRD's 13 acceptance criteria.

**Runnable surface (the thing that is missing today)**
1. A single documented command launches the dashboard with no notebook and no developer tools (directive 17).
2. All **14** views render: the 10 directive views A–J plus the 4 PRD views (Time-Series Explorer, Model Performance, Data Quality, Factory Data Requirements).
3. The animated SVG twin renders, is deterministic, and is driven by the provider — **not a GIF** (directive 4).
4. Factory Presentation Mode shows all **10** required elements (directive 17).
5. All **10** named demo scenarios switch correctly, and the **11-step** "Run Demo" sequence completes (directive 18, 19).
6. Simulation clock (PLAY/PAUSE/RESET/STEP, speeds 0.25/1/2/5/10) and historical mode (timeline, timestamp, play/pause, scrubber, replay speed) both work (directive 7, 8).
7. The Colab notebook renders in a cell with no tunnelling (NFR-9).

**Correctness**
8. **Zero NaN frame crashes** (BUG 1 fixed) — currently ~7 % of live frames die.
9. Views I and J are reproducible (BUG 2 fixed).
10. No hard-coded display value anywhere — the PRD §34:1104 extended audit passes, covering numeric fields **and** animation parameters (NFR-6, AC-12, AC-21).
11. `state.py:570` derives the synthetic badge from `capabilities()`; T1-06 passes.

**Honesty (directive 20 — non-negotiable)**
12. No "confidence %" anywhere; uncertainty shown only as spread/band (directive 10, 14).
13. No language implying real connectivity, real-time control, validated savings, automatic control, guaranteed optimization, or a validated plant model.
14. "Synthetic Demonstration" / "Decision Support Only" / "Not validated against real plant data" present where required.
15. Rejected recommendations remain visible with their reason — never silently dropped (directive 16).
16. Specific **and** total energy both shown (directive 12).
17. Sensor drift still shows "Evidence inconclusive" (directive 11).

**Verification**
18. Suite ends at **≥ 428 passed** — the 428 baseline never regresses.
19. All **13** PRD acceptance criteria are tested (**0 of 13 today**).
20. All **16** directive-22 test areas covered.
21. NFR-2 (< 3 s) holds with **measured** numbers, not asserted ones. NFR-7 (`src/` importable without UI extras) still holds.

**Reporting (directive 25)**
22. All **21** report fields delivered — including **#17 visual evidence of every major view** and **#18 performance measurements**. Neither is currently possible, because nothing runs.

**Documentation**
23. All **7** PRD §35 documents exist, including `FACTORY_DATA_REQUIREMENTS.md` (which `real_plant.py:71` already references).
24. The 8 directive-24 documentation topics are covered.

**Recovery**
25. Git baseline exists; `docs/TASK6_DIRECTIVE.md` is on disk.

---

## Adjudication of contradictions between audit tracks

The user required independent review rather than merging. Ten conflicts were resolved against source; several audit findings did not survive.

| # | Conflict | Ruling | Basis |
|---|---|---|---|
| 1 | View count: 10 (Track A) vs 14 (Track E) | **Track A right on the inventory; the 4 extra views are still PRD-mandated** | PRD §17:690 says *"Ten required views"* with a numbered table; §18's four sub-panels detail content, not inventory. So the directive's A–J **and** the PRD's 10-row table are both real and only partly overlapping — hence 14 renderable views in 6D. |
| 2 | `missing_chart_html` is dead code | **REFUTED** | live caller `charts.py:544-545` inside `to_html`; returns a 275-char themed card |
| 3 | Import cycle blocks refactor | **Both half-right — not grounds for refactor** | package-level cycle real (`session.py:59`, `state.py:68`); module graph acyclic, no `ImportError` reachable |
| 4 | Audit P0-2: redundant provider calls | **REFUTED** | Track D measured exactly 1 call/frame each; the defect is **eagerness**, not redundancy |
| 5 | Audit P1-1: `_indexed` hot path | **REFUTED for LIVE** | REPLAY branch only; `_frame` = 21 ms of 7,900 ms |
| 6 | Audit §6 risk 2: `proposed_setpoints` | **Latent, not present** | 0 occurrences in Task #6 |
| 7 | Audit D-9: `FACTORY_DATA_REQUIREMENTS.md` not required | **REFUTED** | PRD §35:1119 mandates it explicitly |
| 8 | Audit T-5: `is not None` assertions weak | **Substantially wrong** | 12 of 13 are type-narrowing guards followed by real assertions |
| 9 | Audit: "no label text asserted" (33 cases) | **2 of 33 false, substance holds** | `test_model_b_anomaly.py:351-352` do assert; 31 remain unpinned |
| 10 | Audit D-4: `refresh_seconds` is a PRD budget | **REFUTED — invented requirement** | `dashboard.yaml:80` is tagged `# ASSUMPTION` and read by nothing; the real budget NFR-2 is measured passing at 1.94 s |
| 11 | Split `synthetic.py` | **REJECTED — defer** | `self.mode` spans 22 of 62 methods; no tests to catch re-threading errors; violates SMALL PATCHES |
| 12 | `.pytest_cache` 436 vs 428 | **No discrepancy** | 8 stale nodeids (3 deleted scratch files, 5 renamed/removed); `--collect-only` = 428 authoritative |

---

## FINAL DECISION

# OPTION B — Pause Task #6 and perform recovery/bootstrap first

**Evidence for B:**
1. **8,420 LOC with no version control.** No `.git` anywhere in or above the project. Every further edit is unrecoverable.
2. **Zero tests on Task #6**, so no oracle exists. Correctness can only be established by reading code — which is exactly what consumed the previous session's context until the API failed. Bootstrapping an 18-test, sub-second Tier-1 suite converts that unbounded reading cost into a one-second check.
3. **Nothing runs.** No entrypoint anywhere. Task #6's deliverable cannot be demonstrated, screenshotted, or timed — which alone makes directive-25 fields #17 and #18 impossible today.
4. **Two confirmed defects**, one of which (BUG 1) kills ~7 % of live frames. Building more views on top of a frame pipeline that crashes intermittently multiplies the debugging surface.
5. **The bootstrap is cheap.** `.gitignore` + `git init` + one commit + `tests/conftest.py` + `app.py` (~120 LOC, zero new dependencies, **zero existing files changed**). Small, fast, and it unblocks four phases running in parallel.

**Why not OPTION A (continue immediately):** continuing without git and without tests is precisely the configuration that produced roughly a hundred hours of thrash and an API-error termination. The evidence does not support repeating it. NFR-2 already passing at 1.94 s and `twin_document()` already working mean there is no urgency that justifies skipping the bootstrap.

**Why not OPTION C (rollback/rewrite):** the code does not warrant it. No dead modules. Zero module-level import cycles. Zero backward dependencies from the frozen layer. All 16 modules import. The `DataProvider` abstraction is complete and correct. `twin_document()` produces 23 KB of working animated HTML today with no dependencies installed. Track C2 found the set of existing files that must change to add a host is **EMPTY**. And splitting `synthetic.py` — the main refactor the audit proposed — is measurably risky (`self.mode` across 22 of 62 methods) with no tests to catch mistakes. The user's rule applies directly: *prefer SMALL PATCHES over LARGE REFACTOR unless the evidence proves refactoring is necessary.* It does not.

**What OPTION B costs and returns:** Wave 1 is one small serial phase. It returns reversibility, a one-second correctness oracle, a launchable surface, and four phases that can then proceed in parallel — 6B ∥ 6C ∥ 6H-static ∥ 6I-docs. That is the fastest safe path to a working Task #6, and it stops the thrashing at its cause rather than treating its symptoms.

---

*No production code, tests, dependencies, or Git state were modified in producing this plan. Integrity re-verified after writing: only `TASK6_RECOVERY_PLAN.md` was created.*
