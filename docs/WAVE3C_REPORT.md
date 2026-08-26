# Wave 3C — BUG 2: non-reproducible `runtime_s`

**Branch:** `task6/wave-3c` · **Base:** `8cbda49` (Wave 3B) · **Scope:** BUG 2 only.

**Objective:** make views I and J reproducible so they can be golden-tested, without changing what
`runtime_s` means to a real consumer.

---

## 1. Investigation result

Reproduced before touching anything, on the **real** provider (`DashboardSession.build(replay=False)`),
calling each view twice on **one shared frame** so nothing but the view could legitimately differ:

| View | Changed leaf fields across two identical calls | Values |
|---|---|---|
| **I** (`what_if`) | 1 — `view.runtime_s` | 2.905 s → 2.506 s |
| **J** (`optimization`) | 2 — `view.runtime_s` **and** `view.payload.runtime_s` | 6.268 s → 4.629 s |

**Nothing else differed in either payload.** The views were already deterministic; a single
wall-clock measurement was the only obstacle to a golden test.

Two findings the recovery plan did not record:

1. **View J carries the same measurement at two depths.** `OptimizationView.payload` *is*
   `OptimizationResult.describe()`, which has its own `runtime_s` (`optimizer.py:344`). An
   outer-only strip would pass a naive `"runtime_s" not in signature` check and still leave view J
   non-reproducible. This is pinned by its own test.
2. **The frozen layer already solved this exact problem for this exact field.**
   `optimizer.py:363-378` defines `OptimizationResult.NON_REPRODUCIBLE_FIELDS = ("runtime_s",)` and
   `signature()` = `describe()` minus that field, reasoning that "`runtime_s` is a measurement of the
   machine, not of the optimization". Task #6 had simply not reused the convention.

View I's `panel` carries no duration — verified by measurement, not assumed, and consistent with
`WhatIfView.from_result`'s note that a reproducible engine cannot own such a field.

---

## 2. Fix applied: **exclude from comparison**, not inject-a-clock

Added a `signature()` method — `describe()` minus the wall clock — mirroring the frozen layer's
existing convention, at both the view level and the screen level.

Chosen over clock injection because:

1. **It reuses the answer the layer below already gives.** Injecting a clock would introduce a second,
   divergent answer to "what does reproducible exclude?" into the same repository.
2. **It changes no production behaviour whatsoever.** `synthetic.py` is **byte-identical to `main`** —
   `git diff src/digital_twin/synthetic.py` is empty. No new constructor parameter, no changed call
   signature, nothing to thread through.
3. **It fabricates nothing.** A clock injected for tests would write a *fake* duration into the
   golden payload, so the golden file would pin a number production never emits. The directive
   forbids fabricating a duration, and "fabricated only under test" is still a fabricated number in
   the artefact a reviewer reads.

`describe()` is unchanged and still reports the real measured duration — a panel showing how long the
search took is stating a true fact about that run. Only the *comparison* excludes it.

### The honesty risk this created, and the guard for it

"Make views I/J reproducible" has an illegitimate one-line solution: `runtime_s=0.0` in production.
It would have passed every other test in this module. So the fix ships with a structural guard
(`test_production_still_measures_a_real_duration_and_does_not_fabricate_one`) that parses
`run_what_if`'s AST and asserts the argument is still a `perf_counter` subtraction, not a constant.

**The guard was mutation-tested:** production was temporarily changed to `runtime_s=0.0`, the test
failed with the intended message, and `synthetic.py` was then restored and confirmed byte-identical.
A guard that cannot fail is worthless; this one demonstrably fails.

---

## 3. Files changed

| File | Change | Lines |
|---|---|---|
| `src/digital_twin/insights.py` | `ClassVar` import; `NON_REPRODUCIBLE_FIELDS` + `signature()` on `OptimizationView` (strips both depths) and `WhatIfView` (strips one) | +50 / −1 |
| `src/digital_twin/state.py` | `signature()` on `WhatIfViewModel` and `OptimizationViewModel`, each delegating to its view | +23 |
| `tests/test_task6_reproducibility.py` | **new** — 11 tests across four tiers | +305 |

`src/digital_twin/synthetic.py` — **inspected, deliberately not modified.** The wall-clock measurement
at `:1390-1402` is correct as written, and its own docstring at `:1377-1379` already states the design
intent: the number is a property of this machine on this run.

### Scope note (flagged, not hidden)

The directive's inspect-list named `synthetic.py` and `state.py`. The fix also required
**`insights.py`**, which the list did not name, because that is where `runtime_s` is *declared* and
where `describe()` is built. The alternative — implementing the strip only in `state.py` by popping
keys out of another module's payload dict — would have put knowledge of `insights.py`'s field names
into `state.py` and duplicated the frozen layer's pattern at the wrong layer. Both edits are purely
additive; no existing line in either file changed except the `typing` import.

---

## 4. Tests and regression result

**New module `tests/test_task6_reproducibility.py` — 11 tests, four tiers:**

- **Tier 1 (view level, microseconds).** Two views differing *only* in measured duration have equal
  `signature()` and unequal `describe()`; the strip reaches every depth while `describe()` keeps the
  field; view J's nested `payload.runtime_s` is stripped *and* the rest of `payload` survives;
  `signature()` does not mutate the view it is called on.
- **Tier 2 (screen level, stub provider).** The level a golden test actually compares. The screen is
  built through the real `DashboardState.view` dispatch, then its inner view swapped for one carrying
  a measured duration — the stub reports `runtime_s=None` by design (`conftest.py:903`), so the swap
  is what makes this a test about a real wall clock rather than about `None`.
- **Tier 3 (honesty guard).** The AST mutation-tested guard described in §2.
- **Tier 4 (real provider, ~25 s, skipped when artefacts absent).** BUG 2's original reproduction
  kept as a test, asserting the **strong** form: after excluding the duration the two payloads are
  equal leaf for leaf, so *any* new wall clock, counter or random draw in views I/J fails here — which
  no constructed-payload test would catch. Also asserts the duration is still a real positive float,
  so a `None` cannot make the reproducibility claim vacuous.

**Full regression, run once at the end: `537 passed, 0 failed, 0 xfailed` (268 s).**
Baseline was 526 passed; 526 + 11 new = 537. No pre-existing test changed behaviour.

**Frozen layer verified before and after — both digests unchanged:**

```
c7a1f54dd578900835596c02cb9a19a0   src/models … pyproject.toml
53f2aefec33494be5ca22c08ab22b5fd   tests/ minus task6
```

---

## 5. Branch and git status

- **Branch:** `task6/wave-3c`, created off `8cbda49`.
- `main` was never checked out after branching, never merged into, never pushed to.
- Pushed with `-u`; **no pull request opened, nothing merged** — the human reviews and merges.
- The throw-away reproduction script (`repro_bug2.py`) was deleted before committing.

---

## 6. Remaining Task #6 items

Unchanged by this wave except BUG 2, now closed:

| Item | State |
|---|---|
| **Item 15 requirement text** | **UNRECOVERED** — Task #6 cannot be reported complete while this stands |
| `app.py:123` badge derivation | Open — needs the next wave that owns `app.py` |
| **BUG 2** | **CLOSED (this wave)** |
| Twin missing-data symmetry | Open, not started |
| `TestNfr2Budget` | Not written |
| `DATA_DICTIONARY.md`, `DEMO_GUIDE.md` | Missing (PRD §35) |
| Item 17 Factory Presentation Mode | Missing renderer |
| Item 19 "Run Demo" sequence | Missing |
| Item 22 enforcement scans | Partial |
| Items 2–13 renderers | Payload only — preserve, do not rewrite |

### Follow-up this wave enables but did not do

Views I and J are now golden-testable but **no golden file was written** — that is Tier 2 of the plan's
test strategy and a separate objective. `signature()` is the seam it would use. Views A–H were not
examined for reproducibility; if a golden suite is written, the Tier 4 pattern here (strong leaf-for-leaf
equality on one shared frame) is the form that would catch a second non-deterministic field.

## 7. Stop

Wave 3C is complete and stops here.
