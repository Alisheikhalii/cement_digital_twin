# Independent Engineering Audit — Cement Plant Digital Twin

**Repository:** `H:\vibe coding\digital_Twin`
**Audit date:** 2026-08-24
**Auditor:** Independent Claude Code session (PID 11476), read-only
**Method:** Six parallel fan-out subagents (tracks A–F) + lead-reviewer synthesis
**Files changed by this audit:** none. This file is the only artifact created.

---

## 1. Executive Summary

Tasks #1–#5 are in genuinely good shape. The test suite is real, the safety
architecture is sound, and I found **no confirmed data leakage** and **no path by
which an unsafe recommendation can win the optimizer**. Both of those were traced
independently to source, not taken on trust from prior reports.

Task #6 is a different story, and the headline is not the one expected:

> **Task #6 is not running. It is not slow, and it is not stuck in a loop. The
> process is dead.** The Claude Code session driving it terminated on an API
> error at `2026-08-24T04:45:18.394Z` (08:15 local) and never resumed. At audit
> time exactly one `claude.exe` exists on this machine — PID 11476, this audit
> session — and **zero** Python processes.

The reported ~100 hours is elapsed wall-clock across three transcripts, not 100
hours of compute. The dominant cost was **context-window thrash**: 70 automatic
compactions across the three sessions, driven by source modules too large to hold
in context (`synthetic.py` 70 KB, `state.py` 41 KB, `optimizer.py` 82 KB). One
session performed 89 file reads and 94 shell invocations to produce 26 edits and
10 writes in 13h48m. There is no infinite loop to find.

Three findings matter more than the process question:

1. **Task #6 has no runnable surface.** No `notebooks/`, no `app.py`, no
   `__main__.py`, no dashboard renderer. `ipywidgets` and `IPython` appear only
   inside docstrings — never imported. ~7,400–8,400 LOC of provider, state, chart
   and SVG library code exists with nothing to host it.
2. **Task #6 has zero test coverage.** Not thin coverage — zero. No test imports
   any `src/digital_twin/*` or `src/visualization/*` module, even transitively.
   The green 428/428 result says nothing about 29% of the codebase.
3. **The dashboard is ~4× too slow for its own configured clock.** `views()`
   costs ≈8.1 s per frame against `refresh_seconds: 2.0`
   (`configs/dashboard.yaml:80`), and there is **no caching anywhere** in the
   Task #6 layer — a grep for `lru_cache|cached_property|functools.cache|memo`
   across 260 KB of Task #6 code returns zero hits.

Additionally: **this repository is not under version control.** `git rev-parse
--is-inside-work-tree` exits 128. Roughly 7,400+ LOC of Task #6 work has no
recovery point of any kind.

**Recommended action: C — pause and fix before continuing Task #6.** Tasks #1–#5
need nothing. See §13.

---

## 2. Repository State

| Item | Value |
|---|---|
| Path | `H:\vibe coding\digital_Twin` |
| Version control | **None.** `git rev-parse --is-inside-work-tree` → exit 128 |
| Python | 3.14.0 |
| pytest | 9.1.1 |
| Core deps installed | pandas 3.0.5, numpy 2.5.1, scikit-learn 1.9.0, scipy 1.18.0, joblib 1.5.3, PyYAML 6.0.3, pydantic 2.13.4, pyarrow |
| Declared `ui` extra | `plotly>=5.18`, `ipywidgets>=8.1` — **both MISSING** |
| Also missing | `IPython`, pytest-timeout, pytest-xdist, pytest-cov, ruff, mypy, pyflakes, vulture, pylint, bandit |
| `data/` | ≈74 MB |
| `models/` | ≈206 MB |
| `models/registry.json` | 2,032,761 B, 28 entries |
| Newest source file | `src/digital_twin/state.py` — 2026-08-23 23:04:30 |
| Newest non-cache file | `_smoke1.py` (repo root) — 2026-08-23 21:13 |
| `notebooks/` | **Does not exist** (though `src/paths.py:16` defines `NOTEBOOKS_DIR`) |

**Git-derived questions are unanswerable.** Change attribution, branch state,
`git diff`, and blame were all requested in the audit brief. Because there is no
repository, I reconstructed change attribution from file mtimes instead. I am
stating this rather than fabricating git output.

**LOC discrepancy — unresolved.** My own census counted 25,620 LOC in `src/`
(`digital_twin` 5,464 + `visualization` 1,940 = 7,404 for Task #6). Subagent E
counted `digital_twin` 6,189 + `visualization` 2,231 = 8,420 within a
"29,268-LOC codebase". The methods differ (blank/comment handling). Both agree
Task #6 is ≈29% of `src/`. I am reporting both figures rather than picking one.

`_smoke1.py` at repo root is dead ad-hoc scaffolding (3,201 B, a "three-outcome
band rule" script). It instantiates `PlantTwin()` and prints five tables with
**no `if __name__ == "__main__"` guard**, so importing it runs a full twin solve.
It is the only file in the repo that exercises `src.digital_twin.layout`. Not
deleted, per the audit constraints.

---

## 3. Test Results — and whether they mean anything

### 3.1 The run

Authoritative run, performed by me in the main session:

```
python -X utf8 -u -m pytest -q -p no:cacheprovider --durations=30
→ 428 passed in 213.94s (0:03:33)   exit code 0
```

Zero failed, zero skipped, zero xfailed, zero errors, zero warnings surfaced.
Subagent E independently ran the suite and also got **428 passed** (364.65 s on a
loaded machine). `--collect-only` → **428 collected in 1.41 s**.

`-p no:cacheprovider` was used on every run so the shared `.pytest_cache` was
never written. Note: the cache contained **436** nodeids, stale from 2026-08-20.
Subagent D flagged the 436-vs-428 gap as undetermined; my `--collect-only` run
resolves it — the true count is 428 and the 436 file is stale.

Slowest durations (all *setup*, i.e. fixture cost, not test cost):

| Time | Kind | Test |
|---|---|---|
| 68.73 s | setup | `test_optimization.py::TestDecisionSpace::test_exactly_the_six_prd_16_1_variables` |
| 32.47 s | setup | `test_model_a.py::test_a_prediction_carries_a_spread_in_the_targets_own_unit` |
| 22.57 s | setup | `test_ml_leakage.py::test_each_fitted_model_trained_on_the_purged_positions_it_was_handed` |
| 10.37 s | setup | `test_ml_leakage.py::test_the_forest_score_at_row_i_is_unchanged_when_the_future_changes` |
| 7.70 s | call | `test_model_a.py::test_the_targets_argument_filters_and_refuses_an_empty_selection` |
| 7.47 s | setup | `test_model_a.py::test_a_repeated_run_fits_bit_identical_models` |

Roughly 145 s of the 214 s total is session-fixture construction
(`tests/conftest.py:166,208,241,255,315,349,442`) — real model training, not
overhead.

Per-module collection: optimization 90, sensor_model 39, scenario_scheduler 34,
data_generator 31, process_model_interfaces 28, equipment_health 27,
model_b_anomaly 26, conservation_validation 26, model_a 22, data_quality 20,
features_ml 18, ml_leakage 18, delays 14, causality 14, kiln_conservation 7,
mill_conservation 7, fuel_energy_units 7.

### 3.2 Do the tests meaningfully validate the system?

**For Tasks #1–#5: substantially yes. For Task #6: not at all.**

**The green result is partly illusory, but the illusion is narrow and locatable.**
It covers exactly one region: everything Task #6 touches.

I verified the zero-coverage claim myself rather than accepting it. Grepping
`tests/` for `digital_twin|visualization|DashboardState|SyntheticDataProvider|
svg_twin|DataProvider|presentation|labels\.` produced exactly one file,
`tests/test_scenario_scheduler.py`, at lines 94, 98, 273, 274 — and reading those
four lines shows all are `plan.labels` DataFrame column accesses, not references
to `src/labels.py` or any Task #6 module. **Confirmed: 428 tests, zero touch
Task #6.**

Genuine strengths, verified in source:

- `tests/test_ml_leakage.py:9-13,112` proves causality **by measurement** — it
  perturbs future rows and asserts the score at row *i* is unchanged — and
  asserts the converse too, so it fails if the mechanism is removed.
- `tests/test_causality.py:33-42,180-184` likewise.
- `tests/test_model_b_anomaly.py:146` asserts precision *above prevalence*, which
  a trivial detector cannot satisfy.
- `tests/test_optimization.py:558` fuzzes four weight vectors including
  `{thermal: 1e6}` and all-zeros against the hard-constraint barrier.

Genuine weaknesses, verified in source:

- **A tautology.** `tests/test_data_generator.py:81` asserts `dataset_columns ==
  schema.columns_for(...)` — but per `src/data_generation/generator.py:219-220`
  the former *is* the latter. The assertion cannot fail.
- **Protocol checks that check nothing.** `tests/test_process_model_interfaces.py:43,46,54`
  use `isinstance` against `runtime_checkable` Protocols
  (`src/process_models/interfaces.py:40-41,59-60`), which verifies attribute
  *presence* only — not signature, not behaviour.
- **Vacuous label assertions.** `tests/test_optimization.py:1600-1616,1621-1623,32-44`
  assert labels exist without asserting their text. Separately: **no test
  anywhere asserts the text of any safety label in `src/labels.py`** — the
  `SYNTHETIC_DEMONSTRATION_LABEL` and `FORBIDDEN_CONTROL_LABEL` strings could be
  emptied and the suite would stay green.
- **`is not None` as the whole assertion**, at `test_optimization.py:808,846,872,926,
  1051,1080,1172,1386,1600,1676,394,613` and `test_model_b_anomaly.py:436`.

**The suite is hermetic**, which is a real strength: no test reads the 74 MB
`data/` tree or the 206 MB `models/` tree. It would pass on a clean checkout with
both directories empty. That also means the shipped artifacts are unvalidated by
the suite.

**Determinism holds.** `tests/conftest.py:131` pins the timestamp to
`"2026-01-01"`; seeds are fixed throughout; `test_optimization.py:703,724,731`
assert field-for-field agreement across two independently constructed optimizers.

---

## 4. Task-by-Task Audit

Status vocabulary: PASS / PASS WITH WARNINGS / NEEDS REVIEW / FAIL / UNKNOWN.

| Task | Scope | Status | Basis |
|---|---|---|---|
| **#1** Process models & simulation | kiln + mill models, conservation, dead-time delays | **PASS** | 7 kiln + 7 mill conservation tests, 26 conservation-validation, 14 delay tests all pass; mass balances close to machine precision (`test_data_generator.py:1.50s call`); `test_conservation_validation.py` asserts the validation block changes no physical number |
| **#2** Data generation & sensor model | 14 regimes, noise/dropout/drift, data quality | **PASS** | 31 generator + 39 sensor-model + 34 scheduler + 20 data-quality tests; all 14 regimes asserted present (`test_scenario_scheduler.py:test_all_fourteen_regimes_are_present`); `test_equipment_health.py::test_the_global_numpy_rng_is_never_used` is a strong hygiene guard. One tautology (`test_data_generator.py:81`) |
| **#3** Feature engineering & splits | lags, purge/embargo, scenario holdout | **PASS** | Independently traced: label `shift(-h)` at `lag_features.py:463`; exactly one negative shift in the ML layer; purge/embargo strict and conservative (see §5) |
| **#4** ML models (A & B) | forecasting, anomaly detection, uncertainty | **PASS WITH WARNINGS** | No confirmed leakage. Two warnings: Model B `ALL_ROWS` in-sample negatives; prediction-interval coverage never computed. See §5 |
| **#5** Optimization & decision support | objective/constraints, gates, baselines | **PASS** | Proven: no unsafe candidate can win. See §6 |
| **#6** DataProvider, dashboard, SVG twin, Presentation Mode | PRD §17-19, §21, §26, §29 | **FAIL — incomplete** | No host, no tests, 4× over its cadence budget, 4 of 10 PRD views missing, Factory Presentation Mode absent. See §7 |

Note on the numbering itself (Subagent A): **the PRD never defines "Tasks #1–#6."**
`docs/PRD_Synthetic_Cement_Digital_Twin.md` (108,209 B, the only document in
`docs/`) contains no such numbering. The scheme is external to the PRD,
reconstructible only from the build order in the Closing note at **line 1124**.
The mapping above is therefore my reconstruction, and Task #6 maps to PRD §17-19
+ §21 + §26 + §29 (FR-9, FR-12, FR-13, FR-14, FR-20; AC-1, AC-12, AC-21).

---

## 5. Task #4 ML Audit

Ten questions, traced to source by Subagent B and reported with file:line
evidence throughout.

| # | Question | Verdict |
|---|---|---|
| Q1 | Target alignment / off-by-one | **PASS** |
| Q2 | Feature causality (no future data) | **PASS** |
| Q3 | Lag/horizon collision | **PASS** |
| Q4 | Splits + embargo correctness | **PASS** |
| Q5 | Scenario holdout integrity | **PASS** |
| Q6 | Preprocessing leakage | **PASS** |
| Q7 | Anomaly contamination | **PASS WITH WARNINGS** |
| Q8 | Uncertainty calibration | **WARNING — coverage never measured** |
| Q9 | Metric correctness | **PASS** |
| Q10 | Synthetic-truth leakage | **PASS**, one suspicion |

**Confirmed leakage: none** in Model A's feature/label/split path.

**Alignment (Q1).** `src/features/lag_features.py:463` does
`values[target].shift(-horizon_steps)`; features at row *p* include the
unshifted current value (`:364`, `:374`), so the label is the value at
*p + horizon_steps*. Horizons are in **minutes** (`configs/ml.yaml:14` →
`[5,10,15,30]`), converted by `FeatureSpec._steps` (`:162-169`), which **raises**
if the minutes are not a whole multiple of the interval measured from the data
itself (`_sampling_interval_min`, `:539-550`, which also rejects non-uniform
stamps). No off-by-one.

**Causality (Q2).** Exactly **one** negative shift exists in the entire ML layer —
the label at `:463` — plus `regime.shift(-horizon_steps)` at `:400`, which
populates `target_regime`, a reporting field that never enters `features`
(`FeatureMatrix.X` returns `self.features` only, `:221`). No `bfill`, `backfill`,
`interpolate`, or `center=` anywhere in scope. Gap filling is `ffill(limit=...)`
(`:536`). SPC statistics are `rolling(...).mean().shift(1)` /
`.std().shift(1)` (`src/anomaly_detection/spc.py:201-203`) — shifted, therefore
causal.

**Embargo (Q4), with actual numbers.** Splits are chronological, not random
(`src/features/splits.py:123-129`). `configs/ml.yaml:116` is `null`, so the
embargo is computed as `horizon_min + max_lag_min` (`splits.py:86`). With
`lag_sizing: horizon_scaled` (`lag_features.py:327`):

| Horizon | Lags | Embargo |
|---|---|---|
| 5 min | {1, 5} | **10 min** |
| 10 min | {1, 5} | **15 min** |
| 15 min | {1, 5, 15} | **30 min** |
| 30 min | {1, 5, 15} | **45 min** |

The mathematically required separation is `max(h, max_lag)`; the code enforces
`h + max_lag + 1`. Conservative, and in the safe direction. Purge is
`ceil(minutes/interval)` steps (`:238`), and `_purge_tail` keeps only
`positions[block] < boundary[0] - purge` (`:251-252`) — a strict inequality,
measured against **source-frame** positions so earlier row drops cannot silently
shrink it.

**Preprocessing (Q6).** There is no scaler, imputer, pipeline, or feature
selector anywhere in `model_a.py` / `train.py` / `uncertainty.py` — a grep for
`Scaler|Imputer|Pipeline|fit_transform|SelectK` returns nothing. Tree models
only. The two whole-dataset pre-split transforms are both row-local: `ffill`
(`lag_features.py:365`) and the one-hot, whose category list comes from
**config**, not from the data (`:444-455`) — which is the correct way to avoid a
category-set leak.

### Warnings — "tested" vs. "actually proven by the tests"

**Q7 — Model B's headline block scores in-sample negatives.** The *primary*
reported block is `ALL_ROWS` (`src/models/train.py:229`, `:196-201`): fitted on
the first 70% and scored on **every** row — and that is the shipped detector.
Positives are safe (`normal_rows` excludes fault rows from the fit, asserted at
`tests/test_model_b_anomaly.py:90`), but roughly 70% of the **negative** class is
in-sample, so the headline `false_positive_rate` and `precision` are optimistic.
This is disclosed in the docstring at `train.py:170-173` and a clean
`chronological` block is also reported — so it is honest, not hidden. But the
number a reader sees first is the flattering one.

**Q8 — prediction intervals are unvalidated.** `BootstrapEnsemble.fit` resamples
the **training** rows (`model_a.py:261`, `_training=(matrix, train)` at `:555`;
`uncertainty.py:113-135`) — in-sample spread, no held-out calibration step. More
seriously: **no empirical interval coverage is computed anywhere in the
codebase.** Grepping `src/` for `interval_coverage|pi_coverage|within_interval|
nominal` returns nothing; `split_coverage` (`model_a.py:384`) is row/regime
coverage, a different quantity. The code disclaims calibration at
`model_a.py:122`, so this is documented — but the intervals are **tested for
shape and never proven correct**. Concretely: *if the interval width were made
10× too narrow, no test would fail* (`tests/test_ml_leakage.py:396-411` only
checks finiteness, `>= 0`, `> 0` somewhere, and `high-low == 2×uncertainty`).

**Q10 suspicion — a regime oracle.** `include_operating_regime: true` one-hots
the `operating_regime` label, whose categories include the fault regimes
themselves (`configs/ml.yaml:119-121`). The column genuinely exists in
`kiln_raw.csv`, so this is not synthetic-truth leakage in the strict sense. But a
real plant has no live oracle announcing "Fan instability." This is
label-adjacent side information for Model A and would not transfer.

**One more silent gap:** if the MAPE near-zero guard (`metrics.py:62-71`) were
removed, no test would fail — `tests/test_model_a.py:186` only asserts a reason
exists *when* MAPE is already `None`.

### What could not be verified

- Prediction-interval coverage at any nominal level — **no such computation
  exists to audit.**
- Whether the runtime frames are truly 1-minute sampled (asserted at runtime by
  `lag_features.py:539-550`; the CSVs were not loaded).
- Mill config/target consistency beyond header presence.

---

## 6. Task #5 Optimization Audit

Eight questions, traced by Subagent C. **Section brief required distinguishing
"tested" from "actually proven by the tests" — the distinction is drawn per row
in the test-strength table below.**

| # | Question | Verdict |
|---|---|---|
| Q1 | Hard constraints are a filter, not a penalty | **PASS** |
| Q2 | No silent relaxation / best-effort fallback | **PASS** |
| Q3 | Gate coverage across all entry points | **PASS** |
| Q4 | What-if cannot bypass gates | **PASS WITH WARNINGS** |
| Q5 | Rule engine cannot override gates | **PASS** (untested — see risk 1) |
| Q6 | No future data in the optimization path | **PASS** |
| Q7 | Determinism | **PASS** |
| Q8 | Baseline fairness | **PASS WITH WARNINGS** |

### Can an unsafe candidate win? **No — and this is a proof, not an impression.**

The chain, each link read in source:

1. `optimizer.py:1776-1785` `_pick` skips any candidate where
   `candidate.accepted` is false.
2. `optimizer.py:238-242` `CandidateOutcome.accepted` = `envelope.accepted and
   settled and score is not None`.
3. `optimizer.py:1163-1166` — `if report.accepted and settled:` is the **only**
   place `score` is ever assigned; otherwise `score=None`. So a rejected
   candidate is unscoreable, not merely low-scoring.
4. `envelope.py:144-146` `accepted` requires `constraint_status == "PASS"`
   exactly.
5. `envelope.py:684-709` `_resolve_status` returns `"PASS"` only when zero checks
   failed, none borderline, and **none unevaluated** — the comment at `:706-709`
   is right: "a check nobody could run is not evidence of safety."
6. `envelope.py:79` — `CHECK_HARD_CONSTRAINTS` is **not** in `_ENVELOPE_CHECKS`,
   so EXPERIMENTAL mode's `enforce=False` downgrade (`:690`, `:703-705`) cannot
   reach it. **Hard constraints stay fatal in every mode.**
7. `optimizer.py:747-758` additionally requires `not blocking` before
   `_recommend` is called at all.

No weight vector can buy a violation: hard constraints are pass/fail
(`constraints.py:381-383`, `:115-127`), and the objective's only
constraint-derived terms are comfort-band *approach* penalties
(`objective.py:257-274`) computed on a separate normalized-margin quantity.
`tests/test_optimization.py:306` enforces that disjointness by asserting no hard
constraint tag is an objective weight. Inside the differential-evolution
refinement, inadmissible candidates receive `inf` (`optimizer.py:152-154`,
`:1069`) — not a finite penalty that could be outweighed.

**No silent relaxation (Q2).** Grepping `src/optimization/` for
`fallback|best_effort|relax|infeasible|candidates[0]` returns only docstrings and
labels. `_pick` returns `None` when nothing is accepted; `optimize` then appends
a blocking envelope gate and sets `winner = None` (`:745-747`). Only two `except`
clauses exist in the optimization path — `:1083` (budget, returns without a
candidate) and `:1526` (fail-closed on `KeyError, ValueError`). A missing config
key raises `ConfigError` (`config.py:96-104`); a constraint with neither min nor
max raises (`constraints.py:60-62`); an absent tag or non-finite value yields
`evaluated=False, satisfied=False` (`:92-101,105-114`).

### Gate coverage matrix

| Entry point | envelope | OOD | anomaly | uncertainty | constraints |
|---|---|---|---|---|---|
| `Optimizer.optimize` (`optimizer.py:661`) | ✓ :745 | ✓ (check 2 in :1149) | ✓ :723 | ✓ :749 | ✓ :1163 |
| `Optimizer.assess_setpoints` (`:802`) | ✓ :858 | ✓ | ✓ :856 | ✓ :862-866 | ✓ :1163 |
| `WhatIfEngine.run` (`what_if.py:495`) | delegates → `assess_setpoints` :536 | ✓ | ✓ | ✓ | ✓ |
| `WhatIfEngine.replay` (`:567`) | via `run` :583 | ✓ | ✓ | ✓ | ✓ |
| `RuleEngine.evaluate` (`rule_engine.py:396`) | — | — | — | — | — (emits no `Recommendation`) |
| `BaselineSet.build` (`baselines.py:238`) | n/a | n/a | n/a | n/a | n/a (comparison rows only) |

**No entry point skips a gate.** The single asymmetry is deliberate:
`assess_setpoints` *always* returns a `Recommendation` object (docstring
`optimizer.py:393-400`), but `SetpointAssessment.accepted` (`:419-421`) requires
`candidate.accepted and not blocking`.

**Determinism (Q7)** is explicit rather than incidental: `_better` requires
`score < incumbent.score - SCORE_EPSILON` (`:1774`), so ties keep the earlier
candidate; generation order is fixed nested loops over config-ordered names
(`:955-968`, `:1092-1102`, `:1104-1113` using `dict.fromkeys`); RNG seeded
(`:970`); DE seeded with `init="sobol"`, `polish=False` (`:1076-1080`); the settle
memo is cleared at the start of every run (`:693`) so counters are stable;
`_key` rounds to 9 dp (`:1761-1763`).

### Test strength — proven vs. merely exercised

| Mechanism | Delete it → does a test fail? | Test |
|---|---|---|
| Score-only-if-accepted (`:1163`) | **YES** | `test_the_winner_is_the_best_scoring_accepted_candidate` :1411 (asserts `all(score is None for rejected)` at :1418) |
| `envelope.accepted == "PASS"` | **YES — strong** | `test_no_weight_vector_can_buy_a_hard_constraint_violation` :558, four fuzzed vectors incl. `{thermal: 1e6}` |
| No-fallback refusal path | **YES** | `test_the_envelope_gate_names_the_absence_of_a_survivor` :534 |
| Anomaly gate | **YES**, both paths | :469 (`optimize`), :486-496 (`assess_setpoints`) |
| Availability gate | **YES** | :507, :518 |
| Uncertainty gate | **YES** | :619-641, :643-664, :666-680 |
| Envelope hard-constraint check | **YES** | :399, :431-467 |
| What-if delegation | **PARTIAL** | :1005, :1167 — **no test asserts `run` cannot build a recommendation outside `assess_setpoints`**; a parallel path added to `what_if.py` would pass |
| **Rule engine cannot override** | **NO TEST WOULD FAIL** | :1313 asserts baseline-row wiring only |
| No future lags | **YES**, strong | :759 — but exercises `sustained=False` only; production uses `sustained=True` |
| Determinism | **YES** | :703, :724, :731 |

Weak-form tests flagged in this track: `:1017`/`:1034` (panel element *presence*
only), `:717` (set-difference against the object's own `describe()`), `:1381`
(objective re-derived via the production weights — same-code re-derivation).

### Top 5 optimization risks

1. **No test guards Q5.** A future change that let `rules.proposed_setpoints`
   reach `_recommend` would pass the entire suite. `optimizer.py:764` is
   currently comparison-only, but nothing enforces that.
2. **`SetpointAssessment.recommendation` is always populated** (`:393-400`,
   `:878-887`), even when REJECTED. Any consumer reading `.proposed_setpoints`
   without checking `.accepted` surfaces an unsafe move. Enforced by convention
   only — and Task #6 is exactly the consumer layer that would do this.
3. **The leakage test covers `sustained=False`; production uses `sustained=True`**
   (`prediction.py:273`, test at `:759`). The actually-used branch is untested for
   row provenance. (Not itself leakage: `sustained=True` fills lag blocks with the
   candidate's own values, a counterfactual documented at `prediction.py:17-23`,
   reading no future observation.)
4. **`envelope.flag_instead_of_reject_when_borderline`** (`envelope.py:686`,
   `:703`) converts BORDERLINE to FLAGGED rather than REJECTED. Safe today
   (FLAGGED ≠ accepted), but it is a config-reachable softening switch with no
   test asserting FLAGGED stays unacceptable for a borderline *hard* constraint.
5. **Baseline horizon asymmetry** (`baselines.py:303-393`): `historical` and
   `best_comparable` are window *means* while the AI row is a settled steady
   state. No test asserts the horizons are comparable. Baselines are otherwise
   not strawmen — `best_comparable` is the lowest-`rank_metric` window filtered
   to ±`production_match_tolerance_fraction` of the same production target
   (`:331-393`), a genuinely strong opponent.

### Could not verify

- Whether `hard_constraints` can ever be marked BORDERLINE (envelope check-3
  construction not read).
- Actual weight values in `configs/optimization.yaml` — not read. Q1's proof is
  weight-independent by construction, so this does not weaken it.
- `objective.py:290-400` term-by-term arithmetic.

---

## 7. Task #6 Current-State Audit  *(mandatory)*

### 7.1 Is the process healthy, slow, or stuck?

**None of those. It is dead.** Evidence:

| Check | Result |
|---|---|
| `claude.exe` processes | **Exactly one** — PID 11476, this audit session |
| `python.exe` processes | **Zero** |
| Task #6 transcript `bab77965-….jsonl`, last entry | `2026-08-24T04:45:18.394Z │ assistant │ API Error: API returned an empty or malformed response (HTTP 200)` |
| Audit session start | ≈`05:18Z` — **33 minutes after** Task #6 died |

Local time is UTC+3:30, so Task #6 terminated at **08:15 local** and this audit
opened at **08:48 local**. The failure mode is not hypothetical: **six of my own
subagents died with the same two error signatures** during this audit ("The
response stopped arriving" / "API returned an empty or malformed response (HTTP
200)"), which is what let me identify the cause with confidence. It is a
gateway/capacity failure under large contexts, not a repository defect.

### 7.2 Where did ~100 hours go?

**Not to compute.** The audit brief asked me to check specifically for infinite
loops, repeated regeneration, dependency reinstalls, stuck subprocesses,
excessive polling, recursive file generation, watcher rebuild loops, tests
invoking server startup, CLI waiting on input, browser automation, and infinite
retry. **I found none of these.** There is no orphaned process, no watcher, no
retry loop, no browser automation, and no server anywhere in the repository.

What the transcripts actually show:

| Measurement | Value |
|---|---|
| Automatic context compactions, three transcripts | **70** (`577862ec`=55, `bab77965`=10, `b3961a1b`=5) |
| Session `bab77965` duration | 13 h 48 m |
| …its Edits | 26 |
| …its Writes | 10 |
| …its Reads | 89 |
| …its shell invocations | 94 |
| Longest single idle gap | **497.9 minutes** (8.3 h — user asleep) |
| Notable stretch | 52 minutes re-running `python -c "import src.digital_twin.synthetic"` **six times** |

Fifty-five compactions in one session is the finding. Each compaction discards
working context and forces re-reading. The modules being edited are too large to
hold: `synthetic.py` 70,197 B / 1,508 LOC / ~67 methods, `state.py` 41,042 B /
968 LOC, `optimizer.py` 82,226 B / 1,847 LOC. A session that must re-read a 70 KB
file after every compaction spends most of its budget re-orienting. The
89-reads-to-26-edits ratio is the signature.

**Elapsed wall-clock ≈100 h is consistent with the user's report** once all three
transcripts and the idle gaps are included. **Compute time was a small fraction
of it.** I cannot give an exact productive-work figure — per-turn API latency is
not recorded in the transcripts — and per the brief I am saying so rather than
guessing.

### 7.3 LIKELY ROOT CAUSE

```
LIKELY ROOT CAUSE   Context-window thrash caused by oversized source modules,
                    terminated by an unrelated API/gateway failure.
                    There is NO infinite loop and NO runaway process.

EVIDENCE            70 automatic compactions across three transcripts
                    (577862ec=55, bab77965=10, b3961a1b=5).
                    Session bab77965: 89 Reads + 94 shell calls → 26 Edits +
                    10 Writes in 13h48m.
                    52-minute stretch re-running
                    `python -c "import src.digital_twin.synthetic"` six times.
                    One 497.9-minute idle gap (not compute).
                    Final transcript entry 2026-08-24T04:45:18.394Z:
                    "API Error: API returned an empty or malformed response
                    (HTTP 200)".
                    Zero python.exe and one claude.exe at audit time.

AFFECTED FILE       src/digital_twin/synthetic.py   (70,197 B / 1,508 LOC)
                    src/digital_twin/state.py       (41,042 B /   968 LOC)
                    src/optimization/optimizer.py   (82,226 B / 1,847 LOC)

AFFECTED FUNCTION   SyntheticDataProvider (whole class, ~67 methods)
                    DashboardState.views()  (state.py:858)

WHY IT TAKES SO     Editing a 70 KB god class requires the whole file in
LONG                context. Each compaction evicts it; the next edit re-reads
                    it. The cost is O(compactions x file size), and it does not
                    converge, because the file grows as the task proceeds. The
                    absence of version control compounds this: with no diff to
                    consult, the session had to re-derive current state by
                    reading rather than by inspecting changes.

SAFE FIX            (a) Split SyntheticDataProvider along its existing seams —
                        the provider already separates history/model/optimizer/
                        what-if concerns by method group; extract each into its
                        own module under src/digital_twin/providers/.
                    (b) Split DashboardState.views() so each view builder is
                        independently editable.
                    (c) `git init` + an initial commit, so future sessions read
                        diffs instead of whole files.
                    NONE OF THESE ARE APPLIED. See §14.

RISK OF FIX         (a) and (b) are mechanical moves but touch every Task #6
                    call site, and Task #6 has ZERO test coverage — so there is
                    no safety net to catch a mistake. Both should be deferred
                    until smoke tests exist (§14 item 3). Doing (c) first is
                    zero-risk and makes (a)/(b) recoverable.
```

### 7.4 What actually exists, and what does not

**Exists and is decent work:**

- `DataProvider` ABC + `SyntheticDataProvider` (`provider.py`, `synthetic.py`) —
  the abstraction is sound and read-only by construction.
- `RealPlantDataProvider` (`real_plant.py`, 17,189 B) — an intentional refusal
  stub. All 14 data methods `raise NotImplementedError` (lines 186, 196/197,
  208/209, 216/217, 229/230, 248, 257/258, 269/270, 278/279, 290/291, 300/301,
  310/311, 330, 340/341). `__init__` (106-136) opens nothing.
- `DashboardState.views()` (`state.py:858`) — builds ten views.
- Provenance channels OBSERVED / TRUTH / PREDICTION / RECOMMENDATION, with
  walkers at `state.py:928-935`.
- `svg_twin.py` (32,535 B / 753 LOC) — 9 glyphs, viewBox 1040×640. **The
  animation is browser CSS keyframes at `:669-671`, not a per-frame Python
  loop.** I checked this specifically because a Python render loop would have
  been a prime 100-hour suspect. It is a verified negative — this design is
  correct.
- `charts.py` — 8 chart builders, Plotly import guarded at `:36-39`.

**Does not exist:**

| Missing | Evidence |
|---|---|
| **Any host for the UI** | No `notebooks/`, no `app.py`, no `__main__.py`, no `dashboard.py`, no `render*.py` anywhere in `src/` |
| **Factory Presentation Mode** | Config exists (`configs/dashboard.yaml` `presentation.*`); no implementation |
| **`ipywidgets` dashboard loop** | `ipywidgets`/`IPython` appear **only in docstrings** — `clock.py:16`, `svg_twin.py:4,695`, `theme.py:20`. Never imported. Neither package is installed |
| **4 of 10 PRD views** | `state.py:76-87` defines views A–J; four PRD views are absent and four non-PRD views were added instead |
| **`DemoInjector`** | Claimed in comments; no such symbol exists |
| **Any Task #6 test** | Confirmed by independent grep (§3.2) |
| **`FACTORY_DATA_REQUIREMENTS.md`** | Cited by `real_plant.py:71` as the reason for refusal. The file does not exist |
| **The synthetic-banner mechanism** | `real_plant.py:147-149` claims one exists. It does not |

**Runtime consequence of the missing `ui` extra:** all sixteen Task #6 modules
**do** import cleanly — I verified each one individually — because
`charts.py:36-39` guards Plotly behind `except Exception`. But `to_figure()`
**raises `RuntimeError` at `charts.py:452`** when Plotly is absent.
`missing_chart_html()` at `:555` is a proper graceful-degradation path that says
"install plotly to draw it" — **and it has no caller**, because no renderer
exists to call it. So: the library imports, and cannot draw.

**One correctness bug worth naming:** `state.py:570` hardcodes
`SYNTHETIC_DEMONSTRATION_LABEL` and **never reads `capabilities().synthetic`**.
The banner is right today only because the only working provider is the synthetic
one. It is a hardcoded constant masquerading as a derived fact.

### 7.5 Safety verdict — can this system touch a real plant?

**No. Definitively no.** This is the strongest result in the audit, and I traced
it independently rather than trusting the claim.

- **No industrial protocol client anywhere** — no OPC-UA, Modbus, MQTT, S7, or
  DNP3 library imported or vendored.
- **No network capability in `src/`** — no `socket`, `requests`, `httpx`,
  `urllib`, `asyncio` server, or subprocess-based egress.
- **`configs/tag_mapping.yaml` is empty of endpoints** — `sources: {}` at line
  80, comments only, and `meta.status` (48-50) states plainly that no plant is
  connected. No IP, hostname, endpoint, or credential appears anywhere in the
  file.
- **`RealPlantDataProvider` refuses all 14 methods** (§7.4).
- **`DataProvider` is read-only by construction** — the ABC exposes no write,
  send, publish, or setpoint-commit method.
- **`scenario_driver.py:174` exposes fault injection only** — no FR-10 control
  surface.

Security posture is clean: `yaml.safe_load` only (`config.py:147`), no `eval`,
no `exec`, no `shell=True`, no hardcoded secrets. One LOW-severity item:
`src/models/registry.py:267-268` builds `folder / filename` from `registry.json`
without sanitisation — a path-traversal vector only if an attacker can already
write `registry.json`, which is a weaker position than needed to do worse.

---

## 8. Performance Findings

Priorities: **P0** blocks the feature as designed · **P1** materially degrades it
· **P2** wasteful, user-visible under load · **P3** cleanliness.

Measurement provenance is stated per finding. Where a figure is extrapolated
rather than measured, it says so.

---

### P0-1 — The dashboard is ~4× slower than its own configured refresh rate

- **Evidence:** `DashboardState.views()` costs **≈8.1 s** per full frame
  (measured). `configs/dashboard.yaml:80` sets `presentation.refresh_seconds:
  2.0`.
- **Affected file:** `src/digital_twin/state.py:858`
- **Affected operation:** building all ten views for one dashboard frame.
- **Estimated impact:** the presentation clock cannot be met. Every tick starts
  ≈6 s behind and the deficit compounds — a 60-frame presentation would drift
  ≈6 minutes. **This is the defect that would have surfaced first if a runnable
  dashboard existed.** It does not, which is why it has gone unnoticed.
- **Recommended fix:** cache per-frame model output (see P0-2) and raise
  `refresh_seconds` to exceed measured frame cost. **Not applied** — changing
  `refresh_seconds` alone would hide the problem rather than fix it, and §14 is
  report-only.

### P0-2 — Zero caching in the entire Task #6 layer

- **Evidence:** grepping `lru_cache|cached_property|functools.cache|memo` across
  ≈260 KB of Task #6 source returns **zero hits**. Meanwhile
  `src/digital_twin/synthetic.py` recomputes, **per call**: the optimizer
  (`:1309`), what-if (`:1336`), Model A (`:1235`), and Model B (`:1213`).
- **Affected file:** `src/digital_twin/synthetic.py`
- **Affected operation:** every provider read that any view performs.
- **Estimated impact:** the dominant term in P0-1. Several views request the same
  optimizer result within a single frame, and each request re-runs it. This is
  also a *correctness* smell: two views in one frame can disagree if any
  non-determinism exists.
- **Recommended fix:** memoize per `(provider, frame_timestamp)`. Correctness
  precondition — the memo key must include the frame stamp, or stale results will
  outlive their frame.

### P1-1 — `_indexed()` re-indexes the full frame on every call

- **Evidence:** `src/digital_twin/synthetic.py:557` calls `set_index` on the
  whole DataFrame per invocation.
- **Affected operation:** every history lookup.
- **Estimated impact:** O(n log n) repeated where O(1) would do. Amplified by
  P0-2, since nothing caches the result.
- **Recommended fix:** index once at provider construction.

### P1-2 — `_model_history` performs a double outer-join per call

- **Evidence:** `src/digital_twin/synthetic.py:1171`
- **Estimated impact:** allocates a new joined frame on every model-history read,
  of which a frame performs several.
- **Recommended fix:** single join, cached per frame.

### P1-3 — `observed_history` copies the frame on every call

- **Evidence:** `src/digital_twin/scenario_driver.py:387` — `frame.copy()`
- **Estimated impact:** a full DataFrame copy per call. Defensive copying is a
  reasonable instinct; per-call is the wrong granularity.
- **Recommended fix:** return a read-only view, or copy once per frame.

### P2-1 — `_measure_pending` is O(n) per tick → O(n²) over a run

- **Evidence:** `src/digital_twin/scenario_driver.py:354`, with
  `max_live_steps: 4320` in config.
- **Estimated impact:** **EXTRAPOLATED, NOT MEASURED.** The O(n) per-tick scan is
  visible in source and 4320 steps is the configured ceiling, so O(n²) growth
  follows. I did not run a 4320-step live session to time it, and I am not
  quoting a number I did not measure.
- **Recommended fix:** maintain a running index of pending measurements instead
  of rescanning.

### P2-2 — `models/registry.json` duplicates `simulation_config` 28 times

- **Evidence:** file is 2,032,761 B for 28 entries; `simulation_config` is
  27,606 B and appears verbatim in each — **≈773 KB of pure duplication.**
- **Affected file:** `models/registry.json`
- **Estimated impact:** every registry read parses ≈2 MB of JSON to reach
  ≈1.2 MB of distinct content.
- **Recommended fix:** store `simulation_config` once and reference it by hash.

### P3-1 — First provider import costs 7.53 s

- **Evidence:** measured. `src.digital_twin.provider` → 7.53 s; all fifteen
  subsequent Task #6 module imports → ≤0.08 s each.
- **Assessment:** **this is not a Task #6 defect.** It is the one-time cost of
  pandas + scikit-learn cold import, paid by whichever module imports first.
  Recorded so it is not misread as a provider problem.

### P3-2 — `_smoke1.py` runs a full twin solve on import

- **Evidence:** `_smoke1.py` instantiates `PlantTwin()` and prints five tables
  with **no `if __name__ == "__main__"` guard.**
- **Estimated impact:** none today (nothing imports it). It is a trap for anything
  that later globs the repo root — including test collection, were `testpaths`
  ever widened from `["tests"]`.

### Verified negative — the SVG animation is *not* a performance problem

`src/visualization/svg_twin.py:669-671` implements animation as **browser CSS
keyframes**, not a Python per-frame render loop. A Python loop here would have
been the leading suspect for a 100-hour run. It isn't one. Scaled parameters at
`:247, :279, :309, :576` are computed once. **This design is correct and should
not be changed.**

---

## 9. Architecture Findings

**A-1 — God classes.** `SyntheticDataProvider` (`synthetic.py`, 1,508 LOC,
~67 methods) is the primary offender; `DashboardState` (`state.py`, 968 LOC) and
`Optimizer` (`optimizer.py`, 1,847 LOC) follow. This is the direct mechanical
cause of the Task #6 slowdown (§7.3), not merely a style concern.

**A-2 — An import cycle, worked around rather than resolved.**
`state.py:68` imports `src.visualization.clock`, and
`synthetic.py:230` carries a function-local import commented `"# local: keeps
import graph acyclic"`. The comment is honest — the cycle is real and being
dodged. Function-local imports also hide dependency cost inside call paths.

**A-3 — Nine silent config-default drift sites.** `src/config.py:89-104`
`get_path` fails loudly **only when no default is supplied**. Nine call sites
supply a default that differs from the YAML value, so a missing or renamed key
degrades silently to the wrong number:

| Site | Code default | YAML value | Severity |
|---|---|---|---|
| `anomaly_detection/spc.py:58` | `min_sigma_fraction` 0.0 | 0.001 | **SAFETY** — the floor is used at `spc.py:204`; 0.0 removes it |
| `models/model_a.py:372` | `min_rows` 0 | 400 | **SAFETY-adjacent** — 0 permits training on an empty frame |
| `models/model_a.py:373` | `max_rows` 0 | 20000 | Medium |
| `models/uncertainty.py:171` | `random_state` 0 | 42 | Medium — silently breaks reproducibility |
| `features/lag_features.py:426` | `ffill_limit_min` 0.0 | 5 | Medium |
| `features/lag_features.py:322` | `lag_sizing` `"all"` | `"horizon_scaled"` | Medium — changes the embargo (§5) |
| `features/splits.py:111` | `chronological_validation_fraction` 0.0 | 0.15 | Medium |
| `models/model_card.py:320` | `bootstrap_ensemble_size` `None` | 20 | Low |
| `models/model_card.py:963` | `simulation.duration_days` `None` | 30 | Low |

The mechanism at `config.py:89-110` is correctly built — `require()` at `:106-110`
exists precisely for this. These nine sites simply don't use it.

**A-4 — Model artifacts do not record their own environment.**
`models/registry.json` captures `dataset_hash`, `trained_at`, and
`hyperparameters` but **no scikit-learn, numpy, or Python version.** Combined
with joblib loading (`registry.py:92,97,268`) and 206 MB of stored models, a
version bump can silently alter or break deserialization with nothing to detect
it. This matters more than usual here: the environment is Python **3.14** with
scikit-learn **1.9.0**, both recent.

**A-5 — Dead path constants.** `src/paths.py:16` `NOTEBOOKS_DIR` points at a
directory that does not exist; `:32` `REPORTS_EXPERIMENTS_DIR` is referenced by
no other module. `paths.py` is otherwise exemplary — all-pathlib, anchored on
`Path(__file__).resolve().parent`, no `os.path`, no `os.getcwd`, no hardcoded
`H:\`.

**A-6 — Documentation asserts mechanisms that don't exist.**
`real_plant.py:71` cites `FACTORY_DATA_REQUIREMENTS.md` (absent);
`real_plant.py:147-149` describes a synthetic-banner mechanism (absent);
comments reference `DemoInjector` (absent); `clock.py:16` describes an
`ipywidgets` loop (absent). Individually trivial; collectively they make the
codebase read as more complete than it is, which is precisely the failure mode
this audit was commissioned to check.

**A-7 — No version control.** Not an architecture finding in the usual sense, but
it is the highest-leverage structural defect in the repository. 7,400+ LOC of
untested Task #6 work has no recovery point, and its absence measurably slowed
the Task #6 session (§7.3).

---

## 10. Test Quality Findings

**T-1 — 29% of `src/` is untested, and it is exactly the newest 29%.**
All of `src/digital_twin/` and `src/visualization/` — 7,404 LOC by my count,
8,420 by Subagent E's — is never imported by any test, even transitively.
Independently confirmed (§3.2).

**T-2 — A tautological assertion.** `tests/test_data_generator.py:81` asserts
`dataset_columns == schema.columns_for(...)`, but per
`src/data_generation/generator.py:219-220` the former *is* the latter. It cannot
fail.

**T-3 — Protocol conformance is not actually checked.**
`tests/test_process_model_interfaces.py:43,46,54` use `isinstance` against
`runtime_checkable` Protocols (`src/process_models/interfaces.py:40-41,59-60`),
which validates attribute *presence* only. A method with the wrong signature —
or one that raises unconditionally — passes.

**T-4 — Safety label text is never asserted.** `src/labels.py` (246 LOC) defines
`SYNTHETIC_DEMONSTRATION_LABEL` (`:23`), `FORBIDDEN_CONTROL_LABEL` (`:33`),
Literal vocabularies (`:120-128`), and `presentation_card_label()` (`:185`).
Tests import it as a symbol source, and **no test asserts the text of any label.**
Every safety string could be replaced with `""` and the suite would stay green.
For a system whose entire safety story is "it is clearly labelled as synthetic
and decision-support-only," this is the most consequential test gap in the repo.

**T-5 — `is not None` used as a complete assertion**, at
`tests/test_optimization.py:808,846,872,926,1051,1080,1172,1386,1600,1676,394,613`
and `tests/test_model_b_anomaly.py:436`. These confirm a code path ran; they
confirm nothing about what it produced.

**T-6 — Two silent-mutation gaps, established by track:** a 10× too-narrow
prediction interval fails no test (§5); removing the MAPE near-zero guard fails
no test (§5); letting rule-engine setpoints become a recommendation fails no test
(§6).

**T-7 — Fixture cost is concentrated and correct.** ≈145 s of the 214 s runtime
is session-scoped fixture construction (`tests/conftest.py:166,208,241,255,315,
349,442`). These train real models — appropriate, not waste. But
`conftest.py:436-451` shares session-scoped **mutables** across tests, so an
in-place mutation in one test could leak into another. `:401` correctly copies
off a throwaway twin.

**T-8 — Missing test categories:** no performance/timing tests (which is why P0-1
went undetected), no property-based tests, no integration test that exercises a
provider→state→view path, and no test asserting that Task #6 modules import
without the `ui` extra (the condition that actually holds on this machine).

**Counter-evidence, stated fairly.** The suite is not weak overall.
`tests/test_ml_leakage.py:9-13,112` proves causality by measurement and asserts
the converse. `tests/test_causality.py:33-42,180-184` does likewise.
`tests/test_model_b_anomaly.py:146` asserts precision above prevalence.
`tests/test_optimization.py:558` fuzzes weight vectors against the safety
barrier. `test_equipment_health.py::test_the_global_numpy_rng_is_never_used` is a
genuinely thoughtful hygiene guard. Whoever wrote the leakage and causality tests
knew exactly what a real test is. That standard simply never reached Task #6.

---

## 11. PRD Deviations

Deviations are listed **only** where the PRD states a requirement the code does
not meet. No requirements are invented here. Where I could not establish a PRD
basis, the row says so.

| # | PRD basis | Requirement | Actual | Severity |
|---|---|---|---|---|
| D-1 | §17-19 (FR-12, FR-13) | Dashboard renders the specified views | Ten views are *built* as data (`state.py:76-87`); **nothing renders them** — no host module exists | **HIGH** |
| D-2 | §17-19 | The specified PRD view set | **4 of 10 PRD views missing**; 4 non-PRD views added in their place (`state.py:76-87`) | **HIGH** |
| D-3 | §21, §26 (AC-12) | Factory Presentation Mode | Config keys exist (`configs/dashboard.yaml` `presentation.*`); **no implementation** | **HIGH** |
| D-4 | §21 | Presentation refresh cadence | `refresh_seconds: 2.0` configured (`dashboard.yaml:80`); actual frame cost ≈8.1 s — **cannot be met** | **HIGH** |
| D-5 | §29 (AC-1) | Synthetic-data provenance surfaced from provider capability | `state.py:570` **hardcodes** the label and never reads `capabilities().synthetic` | **MEDIUM** |
| D-6 | §17-19 | Interactive dashboard controls | `ipywidgets` declared in `pyproject.toml [ui]`, **never imported**, not installed | **MEDIUM** |
| D-7 | Model-card / reproducibility sections | Model provenance is recorded | `registry.json` records dataset hash + hyperparameters but **no library or Python version** (A-4) | **MEDIUM** |
| D-8 | FR-9 (DataProvider abstraction) | Provider abstraction with a real-plant path | Abstraction **is** implemented correctly; the real-plant path is an explicit refusal stub. Reported as a deviation only in the sense that the path is not functional — **which appears intentional and correct given no plant exists** | **NONE — by design** |
| D-9 | — | — | `real_plant.py:71` cites `FACTORY_DATA_REQUIREMENTS.md`, which does not exist. **No PRD basis established for that filename** — recorded as a broken reference, not a PRD deviation | **LOW** |

**A caveat that constrains this section.** The PRD (108,209 B) does not use the
task numbering this audit is organized around; the mapping is reconstructed from
the build order at line 1124. Task-to-PRD attributions above are therefore my
reading, not the PRD's own statement. Requirement *text* is the PRD's;
requirement *numbering* is reconstructed.

---

## 12. Critical Findings

Ordered by consequence.

**C-1 — Task #6 is far less complete than "nearly done."**
No host, no Presentation Mode, 4 of 10 PRD views missing, no widget layer, zero
tests. What exists is a rendering *library* with no application. Any plan that
treats Task #6 as ready to finish in a short session is working from a wrong
premise.

**C-2 — Task #6 has zero test coverage, and it is the only part of the system
that does.** The 428-green result is being read as validation of the whole
repository. It validates 71% of it.

**C-3 — The repository is not under version control.** 7,400+ LOC of untested
work, no recovery point, no diff, no blame. This also measurably slowed the
Task #6 session (§7.3). **This is the cheapest high-value fix available and it is
not applied** (§14).

**C-4 — The dashboard cannot meet its own configured clock** (P0-1), and the
Task #6 layer contains no caching at all (P0-2).

**C-5 — Nine silent config-default drift sites, two of them safety-relevant.**
`spc.py:58` disables the sigma floor used at `spc.py:204`; `model_a.py:372`
permits training on an empty frame. Both fail *silently* on a missing key
(A-3).

**C-6 — Model B's headline anomaly metrics are optimistic.** ~70% of the negative
class is in-sample on the shipped `ALL_ROWS` detector. Disclosed at
`train.py:170-173`, but it is the first number a reader sees (§5).

**C-7 — Prediction intervals are never validated.** No coverage computation
exists anywhere, and a 10×-too-narrow interval would fail no test (§5).

**C-8 — Safety labels are asserted by no test.** For a system whose safety case
rests on labelling, the labels are the untested part (T-4).

### Explicitly NOT critical — findings that came back clean

Stated because a report that only lists problems misrepresents the system:

- **The system cannot control or touch a real plant.** Traced independently and
  confirmed definitively (§7.5).
- **No unsafe recommendation can win the optimizer.** Proven through a seven-link
  chain in source (§6).
- **No confirmed data leakage** in Model A's feature/label/split path, and the
  embargo is conservative in the safe direction (§5).
- **Security is clean** — `safe_load` only, no `eval`/`exec`/`shell=True`, no
  secrets. One LOW path-traversal item requiring pre-existing write access.
- **The SVG animation design is correct** — browser CSS keyframes, not a Python
  render loop (§8).
- **Determinism holds** across the ML and optimization paths.
- **No infinite loop, no runaway process, no orphaned subprocess** anywhere.

---

## 13. Recommended Action

> ## **C — PAUSE AND FIX**
> **(before continuing Task #6. Tasks #1–#5 require no action.)**

Option **A** (continue unchanged) would resume building on 8,000 untested LOC,
with no version control, against a cadence the frame cost cannot meet, using the
same oversized modules that produced 70 compactions. The failure would repeat.

Option **B** (continue after a small correction) understates it. The gap is not
one line: no host module, zero tests, no caching layer, no VCS.

Option **D** (stop and redesign) overstates it. The architecture is *sound* — the
`DataProvider` ABC is a correct abstraction, provenance channels are a good
design, the refusal stub is exactly right, and CSS-keyframe animation is the
right call. Redesigning would discard good work to fix problems that are
additive, not structural.

Hence **C**. The prerequisite work, in dependency order:

1. **`git init` + initial commit.** Zero risk, immediately makes everything below
   recoverable. Should happen before any other change.
2. **Install the `ui` extra** (`pip install -e ".[ui]"`) so the rendering layer
   can actually draw.
3. **Add Task #6 smoke tests** — provider contract, `views()` completeness,
   provenance-channel integrity, import-without-`ui`. These are the safety net
   for items 4–5.
4. **Add per-frame caching** to the provider layer, keyed on frame timestamp
   (fixes P0-2, most of P0-1).
5. **Then** split `synthetic.py` and `state.py` along their existing seams — with
   tests and VCS in place, this becomes routine rather than risky.
6. **Only then** resume Task #6 feature work: the host module, the 4 missing PRD
   views, Factory Presentation Mode.

Sequencing matters: doing 5 before 1 and 3 is how this repository arrived at its
current state.

---

## 14. Safe Fixes — **LISTED ONLY. NOT IMPLEMENTED.**

> **No authorization to implement any fix has been given, and none has been
> applied.** No file in this repository was created, modified, or deleted by this
> audit. This file is the only artifact.
>
> Each entry below is a proposal awaiting explicit authorization.

| # | Fix | Files | Risk | Why safe |
|---|---|---|---|---|
| **F-1** | `git init`, `.gitignore`, initial commit | repo root | **None** | Adds a recovery point. Touches no source. Do this first |
| **F-2** | `pip install -e ".[ui]"` | environment only | **None** | Installs already-declared deps. No source change |
| **F-3** | Close the 9 silent-default drift sites — drop the second `get_path` argument (or use `require()`, `config.py:106-110`) so a missing key **raises** | the 9 sites in A-3 | **Low, but not zero** | Converts silent wrong-value into a loud failure. **Caveat: if any key is genuinely absent from YAML, this turns a passing run into a hard error.** Verify each key exists before applying. Fix `spc.py:58` and `model_a.py:372` first — those two are safety-relevant |
| **F-4** | Add Task #6 smoke tests (provider contract, `views()` completeness, provenance integrity, import-without-`ui`) | new files under `tests/` | **None** | Test-only. Adds the missing net |
| **F-5** | Add per-frame caching keyed on `(provider, frame_timestamp)` | `synthetic.py` | **Medium** | Addresses P0-1/P0-2. **Requires F-4 first** — this is Task #6 production code with no coverage. Key must include the frame stamp or results go stale |
| **F-6** | Index once at construction instead of per call | `synthetic.py:557` | **Low** | Pure memoization of an idempotent operation. Requires F-4 |
| **F-7** | Assert safety-label text (T-4) | new `tests/` | **None** | Test-only. Closes the largest safety-test gap |
| **F-8** | Add a prediction-interval coverage metric (C-7) | `src/models/` + tests | **Medium** | **New measurement only — must not change any threshold or model.** Note it may reveal that current intervals are miscalibrated; that is information, not a regression |
| **F-9** | Deduplicate `simulation_config` in `registry.json` (P2-2, ≈773 KB) | `models/registry.json` | **Medium** | Touches a 206 MB artifact tree. Requires F-1 first |
| **F-10** | Record library + Python versions in the registry (A-4) | `registry.py` | **Low** | Additive metadata on newly written entries |
| **F-11** | Add `if __name__ == "__main__":` to `_smoke1.py`, or delete it (P3-2) | `_smoke1.py` | **Low** | Dead scaffolding. **Deliberately not deleted** per audit constraints |
| **F-12** | Read `capabilities().synthetic` instead of hardcoding (D-5) | `state.py:570` | **Low** | Makes the banner reflect reality. Requires F-4 |
| **F-13** | Fix or remove the four documentation claims for absent mechanisms (A-6) | `real_plant.py:71,147-149`, `clock.py:16` | **None** | Comments only |
| **F-14** | Replace the tautology (T-2) and strengthen Protocol checks (T-3) | `test_data_generator.py:81`, `test_process_model_interfaces.py:43,46,54` | **None** | Test-only. **May newly fail — that is the point** |
| **F-15** | Add a test that rule-engine setpoints cannot become a recommendation (§6 risk 1) | `tests/test_optimization.py` | **None** | Test-only. Guards a currently-unguarded safety property |

**Explicitly excluded from this list**, per the audit constraints: no physics
equation, simulation assumption, ML threshold, optimization constraint, safety
gate, training range, benchmark condition, or PRD requirement is proposed for
change. No test is proposed for disabling. F-8 adds a measurement without
touching a threshold. Nothing here makes a result prettier.

---

## 15. Final Verdict

> # **PAUSE AND FIX**

Scoped precisely:

**Tasks #1–#5 — HEALTHY.** 428 tests pass and, on inspection, they largely
deserve their green. No confirmed leakage. No path by which an unsafe
recommendation reaches a user. The system cannot touch a real plant, and that
conclusion is definitive rather than probable. The embargo is conservative, the
gates fail closed, determinism holds, security is clean. The leakage and
causality tests are, in places, better than typical. Warnings in §5, §6, and §10
are real and should be addressed — none of them undermines the system.

**Task #6 — PAUSE.** Not because the design is wrong; because the design is
sound and the execution is incomplete in ways the test suite cannot see. No host,
zero coverage, ~4× over its own cadence budget, 4 of 10 PRD views absent, no
Presentation Mode, and no version control beneath any of it.

**On the ~100 hours — the question that prompted this audit:**

**Task #6 is not stuck, not looping, and not running.** The process is dead — it
terminated on an API error at `2026-08-24T04:45:18.394Z`, 33 minutes before this
audit began. There is no runaway process to find, no infinite loop, no orphaned
subprocess, and no repeated regeneration. The time went to context-window thrash:
**70 compactions** against 70 KB and 41 KB source modules, plus ordinary idle
time including one 8.3-hour gap. The single most effective response is not a
performance fix but a **structural** one — `git init`, then split the god
modules — and per this audit's constraints, neither has been applied.

**What this audit changed in the repository: nothing.**

---

*Audit performed with six independent read-only fan-out subagents (tracks A–F:
PRD/requirements, ML/leakage, optimization safety, Task #6
performance/architecture, test quality, code quality/security). Every subagent
was given `Explore`-class tooling with no write capability, so read-only was
enforced at the tool level rather than by instruction. All six were instructed
not to trust prior reports; the central claims in §3.2, §5, §6, §7.1, and §7.5
were independently re-verified by the lead reviewer in the main session.
Divergences between subagent findings and my own measurements — the 436-vs-428
test count and the two LOC censuses — are reported in §3.1 and §2 rather than
silently reconciled.*
