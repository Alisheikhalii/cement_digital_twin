# WAVE 3B REPORT — B-7 Honesty Badge Derivation

**Objective (single):** make the "Synthetic Demonstration" / "Simulation Estimate" badge derive from
`provider.capabilities().synthetic` via `labels.presentation_card_label()` at **both** sites, clearing
the two `xfail(strict=True)` pins for T1-06 in `tests/test_task6_provider_contract.py`.

**Outcome:** both sites fixed, both xfail markers removed, full regression green.

| | |
|---|---|
| **Baseline** | `440602e` — 524 passed, 2 xfailed |
| **After Wave 3B** | **526 passed, 0 xfailed** (385 s) |
| **Frozen layer** | byte-identical before and after (digests re-verified, below) |
| **Scope** | 3 files, all inside the Task #6 layer |

---

## 1. Investigation result

Reproduced before patching. `pytest -k badge_is_derived --runxfail` gave the two real failures:

**Site 1 — `src/digital_twin/state.py`, `DashboardState._header` (was line 570).**
`badge=labels.SYNTHETIC_DEMONSTRATION_LABEL`, unconditional. Against a provider reporting
`synthetic=False`:

```
AssertionError: overview
assert 'Synthetic Demonstration' == 'Simulation Estimate'
```

The failure hits on the *first* view (`overview`) and would have hit all ten — the badge is written
once in `_header`, which every view header goes through.

**Site 2 — `src/visualization/svg_twin.py`, `_header_html` (was line 530).**
Failed one assertion earlier than site 1 — not on the wrong string, but on the *absence of any way to
ask*:

```
AssertionError: svg_twin.render_twin takes no capability argument, so _header_html cannot know
whether its source is synthetic ...; expected one of ('capabilities', 'caps',
'provider_capabilities', 'synthetic')
```

`_header_html(snapshot, title)` had no capability parameter, and neither did `render_twin`,
`twin_html` or `twin_document`. So the flag had to be threaded down the whole export path, as the
directive predicted. The directive's description of both sites was accurate; the only correction is
that the line numbers cited in `PROJECT_STATE.md` (`svg_twin.py:530`) and the old xfail reason were
one or two lines off from the current file, and have shifted again after this fix — the report and
tests now name the *functions* instead, which does not go stale.

Two things checked before committing to the approach, because either would have made the site-2 fix
unverifiable:

- **No other emitted string contains the badge substring.** `NO_PLANT_CONNECTION_STATEMENT` (which
  the fragment always carries) says "reads a synthetic simulation", not "Synthetic Demonstration",
  so the test's `label not in render(honest)` assertion is genuinely satisfiable.
- **`capabilities()` costs ~4.8 µs** on `SyntheticDataProvider`, against ~1.5 ms for the four
  surfaces one `_Frame` reads. That decided site 1's shape (see below).

---

## 2. Fix applied at each site

Both sites now call the same helper, `labels.presentation_card_label("synthetic" if … else
"estimate")`, so the two allowed wordings stay owned by `src/labels.py` and neither site can invent a
third.

### Site 1 — `src/digital_twin/state.py`

`_header` reads `self._provider.capabilities().synthetic` inline and derives the badge from it. One
call per view header (~10 per render, ~48 µs).

*Why inline and not carried on `_Frame`:* `_Frame` would have been the cheaper shape (one read per
frame instead of ten), but `tests/test_task6_performance.py:123` documents `_Frame` as "the four
surfaces one `_Frame` reads". Adding a fifth would have falsified a statement in a test module this
wave is not scoped to edit. Inline also matches the four existing inline `capabilities()` reads
already in this class (lines 519, 535, 750, 820, 843), and the cost is 3 % of one frame read.

### Site 2 — `src/visualization/svg_twin.py`

Added an explicit keyword-only `synthetic: bool` threaded down the full export path:

```
twin_document(…, synthetic=True) → twin_html(…, synthetic=…) → render_twin(…, synthetic=…)
                                 → _header_html(snapshot, title, *, synthetic)   # required, no default
```

`_header_html` takes it as **required** — it is private with one caller, so there is no reason to let
a caller omit it. The three public functions default to `synthetic=True`.

*Two deliberate choices, both worth flagging:*

- **Explicit flag, not inferred.** The directive required this and it is also correct on the merits:
  `snapshot.provenance` is per-*value* (OBSERVED / TRUTH / …) and says nothing about whether the
  source is a simulation. Inferring "synthetic" from it would have invented semantics.
- **`default=True`, not required.** Every current render path *is* the synthetic demonstration, so
  the default states the truth for all of them; a caller over a source reporting `synthetic=False`
  must say so and then gets "Simulation Estimate". Making it required instead would have broken
  `app.py:123` and roughly six call sites in `tests/test_task6_twin.py`, none of which this wave may
  edit. **This is a fail-open default and should be read as one** — see the follow-up below.

### Follow-up this wave deliberately did *not* take (out of scope)

`app.py:123` (`build_document`) calls `render_twin` without the new flag, so the production render
still gets the `True` default rather than a derived value. It is truthful today — that path runs
`SyntheticDataProvider`, whose `synthetic` is `True` — but it is not *derived*. The one-line fix is
`synthetic=state.capabilities().synthetic`, and it was left out because `build_document` documents
its `state` parameter as "any object exposing `view(view_id)`" (`app.py:60`); calling
`capabilities()` on it widens that contract and could break fakes in modules outside this wave's
scope. It is also not yet reachable in practice: per `PROJECT_STATE.md` gap 2, `DashboardState.frame()`
still raises for `RealPlantDataProvider`, so no real-plant provider can render a twin at all. **Recommended
as the first item of the next wave that touches `app.py`.**

---

## 3. Files changed

| File | Change |
|---|---|
| `src/digital_twin/state.py` | +9/−1 — `_header` derives the badge; comment explains why not on `_Frame` |
| `src/visualization/svg_twin.py` | +43/−8 — `synthetic` threaded through 4 functions; docstrings updated |
| `tests/test_task6_provider_contract.py` | +21/−35 — 2 xfail markers + `BADGE_XFAIL_REASON` removed; stale present-tense defect prose corrected |

No new files. No frozen-layer file touched.

Beyond the markers themselves, the test edits removed statements that the fix had made **false**:
the module docstring's "two `xfail(strict=True)` tests holding the *correct* behaviour", the
`BADGE_XFAIL_REASON` constant (unused once both markers went, and its text asserted the defect was
live), `_twin_capability_kwargs`'s "today no such keyword exists anywhere on the render path", and
the two stale `file:line` citations. Leaving those in place would have left the suite documenting a
defect it no longer has.

---

## 4. Tests

**xfail markers:** both removed. `grep -n xfail tests/test_task6_provider_contract.py` now returns
only one hit — a historical note in the module docstring, no marker.

| Run | Result |
|---|---|
| `-k badge_is_derived` before fix | 2 xfailed (strict, as expected) |
| `-k badge_is_derived --runxfail` before fix | **2 failed** — the two failures quoted in §1 |
| `-k badge_is_derived --runxfail` after fix | 2 passed |
| `tests/test_task6_provider_contract.py` (whole module) | 20 passed, **0 xfailed** |
| twin + app-smoke + real-plant-state modules | 47 passed |
| **Full regression (once, at the end)** | **526 passed, 0 xfailed** in 385 s |

526 = the previous 524 passed + the 2 formerly-xfailed. Nothing else moved: no new test was added, no
test was skipped, and the count reconciles exactly. Regression floor is 428 (directive §4.7) —
well clear.

`ruff` is not installed in this environment (`No module named ruff`), so no lint run is claimed.

**Frozen-layer digests, re-verified after the change:**

```
c7a1f54dd578900835596c02cb9a19a0   # src/models … pyproject.toml   (expected: match)
53f2aefec33494be5ca22c08ab22b5fd   # tests/ minus task6            (expected: match)
```

Both match the values recorded in `PROJECT_STATE.md`.

---

## 5. Git status

One commit, on `main`, parent `440602e`. Working tree clean at commit time; the three files above are
its entire content. Nothing pushed.

---

## 6. Remaining Task #6 items

Unchanged by this wave except that **B-7 is now closed**. See `docs/PROJECT_STATE.md` for the live
list. Still open:

| Item | State |
|---|---|
| **Item 15 requirement text** | **UNRECOVERED** — Task #6 cannot be reported complete while this stands |
| BUG 2 | Not started |
| Twin missing-data symmetry | Not started |
| `TestNfr2Budget` | Not written |
| `DATA_DICTIONARY.md` | Missing (PRD §35) |
| `DEMO_GUIDE.md` | Missing (PRD §35) |
| Item 17 Factory Presentation Mode | Missing renderer |
| Item 19 "Run Demo" sequence | Missing |
| Item 22 enforcement scans | Partial |
| Items 2–13 renderers | Payload only — 8 of 10 views |
| *New:* `app.py:123` badge derivation | Follow-up from this wave (§2) |

---

## 7. Stop

Wave 3B is complete and stops here. No other Wave 3 item was started, no background or parallel
agents were used, and the full suite was run once.
