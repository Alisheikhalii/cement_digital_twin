# WAVE 3A REPORT — `RealPlantDataProvider` Constructibility

**Date:** 2026-08-25
**Baseline commit:** `e4dee7a` (Wave 2)
**Scope:** ONE objective — make `DashboardState` constructible with `RealPlantDataProvider`, if a
safe fix exists that respects the existing capability contract without inventing new semantics.

---

## 0. Scope correction (two files in the directive's SCOPE list do not exist)

| Directive SCOPE entry | Reality |
|---|---|
| `src/digital_twin/clock.py` | Does not exist. The real file is **`src/visualization/clock.py`**. |
| `src/digital_twin/capabilities.py` | Does not exist. `ProviderCapabilities` lives in **`src/digital_twin/payloads.py:170-202`**. |

The directive's own line references were nevertheless accurate against the real files:
`clock.py:140-141` and `state.py:547-550` are exactly the cited sites. Work proceeded against the
real equivalents. No file outside the corrected scope list was read or modified.

---

## 1. Investigation result

**Reproduced first, before any patch.** `RealPlantDataProvider` itself constructs fine and
`capabilities()` answers (all eight flags `False`, thirteen kinds listed in `missing`). The failure is
at the *next* step:

```
Clock(provider, settings)
  -> src/visualization/clock.py:141  self._last_timestamp = provider.get_current_state().timestamp
  -> src/digital_twin/real_plant.py:209  raise NotImplementedError(...)
```

`DashboardState.__init__` (`state.py:477-488`) is **pure assignment — it calls nothing**. So
`DashboardState` was already constructible; the *only* barrier to construction was `Clock.__init__`.

### Which provider methods are required vs optional under the existing contract

This was the decisive question, and the answer is not symmetric:

| Category | Methods | Gate that exists |
|---|---|---|
| **Optional — may refuse** | `set_mode`, `advance`, `reset`, `scenarios`, `select_scenario`, `seek`, (`window` returns `None`) | Concrete on the ABC, raise `CapabilityError`. `provider.py:15-18` states this explicitly: clock control "is *optional*… a provider that has no simulated time to drive stays valid." |
| **Optional — flag-gated** | `get_truth_state`, `get_history`, `get_predictions`, `get_anomaly_state`, `get_optimization`, `run_what_if`/`what_if_sliders` | A boolean on `ProviderCapabilities`: `truth`, `history`, `predictions`, `anomaly`, `optimization`, `what_if`. |
| **REQUIRED — no gate at all** | `get_current_state`, `get_equipment_status`, `get_kpis`, `get_operating_regime`, `get_sensor_values`, `get_timeseries`, `get_tag_metadata` | **None.** `@abstractmethod` with no capability flag. `_Frame` (`state.py:441`) calls the first four "the provider's **required** surfaces". |

**`ProviderCapabilities.missing` cannot serve as the gate.** Two independent reasons, both verified:

1. **Zero production consumers.** `grep` for `.missing` across `src/` finds it only being serialised
   in `describe()` (`payloads.py:201`). Nothing anywhere branches on it.
2. **Two incompatible vocabularies.** `real_plant.py:161-175` fills it with *data-kind* names
   (`"current_state"`, `"truth_state"`, `"equipment_status"`); `synthetic.py:466-486` and the test
   stub (`conftest.py:693`) fill it with capability-*flag* names (`"history"`, `"truth"`, `"live"`).
   A membership test such as `"current_state" in caps.missing` would therefore fire for exactly one
   provider in the repo and silently never fire for the others. Gating on it would have been
   inventing a contract term, which this wave was forbidden to do.

---

## 2. Root cause

Two — and **only** two — sites in `Clock` read the provider's position without any guard:

1. **`clock.py:141`** (`__init__`) — the eager cache seed. Reached at construction. **This is the
   reported defect.**
2. **`clock.py:164`** (`_sync(None)`) — the re-read after an operation that returns no snapshot.
   Reached from `reset()` and `set_mode()`. `reset()` already catches the provider's
   `CapabilityError` from `provider.reset()` and then crashes one line later on this read. **This
   site was not named in the directive and would have left `RESET` broken.**

Every *other* clock path was already correctly capability-gated and needed no change:
`_can_advance()` reads `capabilities().live`; `_has_replay()` reads `window()`; `_advance_steps`,
`step_back`, `seek_fraction`, `seek` and `scenarios` all early-return or catch `CapabilityError`.

The reason the two sites were missed is that the guard for them **cannot be a flag check** — no flag
exists (§1). The pattern used elsewhere in the same file is therefore the correct one: catch the
contract's own refusal. `CapabilityError` is documented (`provider.py:50-55`) as "a distinct type so
the dashboard can catch it and render the 'not available from this data source' state", and PRD 26.1
has `RealPlantDataProvider` refuse with its parent `NotImplementedError` — so catching the parent
covers both vocabularies. `clock.py` already used exactly this pattern three times
(`_advance_steps`, `reset`, `scenarios`).

### Why a fix is justified rather than declined

Two on-disk sources state that construction is supposed to succeed:

- `real_plant.py:13-18` — "A dashboard can be handed one of these and will get a clear, actionable
  refusal **from whichever panel it asks first** — not an `AttributeError`, and not a number."
- `tests/test_task6_provider_contract.py:361` — "`__init__`, `capabilities()` and `describe()` stay
  live precisely so a dashboard handed one of these degrades every panel instead of **failing at
  construction**."

The pre-fix behaviour satisfied neither: the refusal came from the *constructor*, not from a panel.
The fix moves the refusal to the panel that asks, which is what both sources specify.

---

## 3. Fix applied

One production change, confined to `src/visualization/clock.py` (**+47 / −6**). Nothing in
`state.py`, `real_plant.py`, `provider.py`, `payloads.py` or `synthetic.py` was touched.

1. **New `Clock._read_position() -> str | None`** — the single guarded read. Returns the provider's
   timestamp, or `None` on `NotImplementedError`. Its docstring records why the guard is an exception
   catch and not a flag check, including the two-vocabulary finding, so the next reader does not
   re-derive it.
2. **`__init__`** now seeds from `_read_position()`. Still **eager**, still exactly one call — see §5.
3. **`_sync(None)`** now re-reads through `_read_position()`, fixing the unreported `RESET` site.
4. **`ClockState.timestamp`** widened `str` → `str | None`, with a comment stating that an absent
   position is reported as `None` and never filled in. This field has **no consumer outside
   `clock.py`** (verified by grep; `ClockState` is constructed in exactly one place, `clock.py:224`),
   so the widening has no blast radius and stays JSON-describable for item 21.
5. **`_replay_position()`** treats "no position" like the existing "no window" case, returning the
   same degenerate single sample. Without this, `pd.Timestamp(None)` → `NaT` and the scrubber
   fraction would render as `NaN` — a fabricated number. Verified `pd.Timestamp(None)` is `NaT`
   rather than an error before adding the guard.
6. **`step_back()`** refuses when there is no position, for the same `NaT` reason.

### What the fix deliberately does **not** do

- **No fabricated value, no NaN fill, no silent fallback.** Absence is `None`, and the two `NaT`
  paths were closed rather than opened.
- **No new capability semantics.** No flag added to `ProviderCapabilities`; `missing` is not consumed.
- **`state.py:547-550` (`frame()`) was left alone, deliberately.** The four methods it calls are
  *required* surfaces with no flag between caller and provider (§1). Gating them would mean both
  inventing a capability term and inventing a per-view representation of "no process state at all"
  across ten view builders and nine `frame.snapshot` use sites. Neither exists, and a `frame()` that
  returned an empty or zero-filled snapshot would be a straight NFR-6 / item-20 violation. So
  `frame()`, `views()` and `view(...)` **still raise**, carrying their full actionable refusal — which
  is precisely the behaviour `real_plant.py:15` specifies.

### Verified end state

```
DashboardState(RealPlantDataProvider(...), Clock(...), settings)   -> constructs
  .capabilities()  -> ok (synthetic=False)
  .footer()        -> ok
  .clock_state()   -> ok; timestamp=None, can_play/can_step_back/can_scrub/can_reset all False
  clock.reset() / .tick() / .step_back() / .seek_fraction(0.5)     -> no crash, timestamp stays None
  .frame() / .views() / .view("A")  -> NotImplementedError, TODO + both PRD documents intact
  .history((...,))                 -> () (flag-gated, legitimately empty)
```

---

## 4. Files changed

| File | Change |
|---|---|
| `src/visualization/clock.py` | **modified**, +47 / −6. The whole production fix. |
| `tests/test_task6_real_plant_state.py` | **new**, 7 tests. |
| `docs/WAVE3A_REPORT.md` | **new**, this file. |
| `docs/PROJECT_STATE.md` | **new**, handoff file (did not exist). |

**Frozen layer: byte-identical.** `git ls-files -s` digest over `src/models`, `src/process_models`,
`src/optimization`, `src/simulation`, `src/features`, `src/data_generation`, `configs`,
`pyproject.toml` = `c7a1f54dd578900835596c02cb9a19a0` before **and** after. Digest over all
non-Task-6 test modules = `53f2aefec33494be5ca22c08ab22b5fd` before **and** after.

---

## 5. Tests

`tests/test_task6_real_plant_state.py` — 7 tests. The directive required a test that checks the
actual contract, not just "no exception", so the file asserts in both directions:

| Test | Pins |
|---|---|
| `..._constructible_over_a_provider_that_answers_nothing` | The objective: construction + the three surfaces PRD 26.1 keeps live. |
| `..._states_an_absent_position_rather_than_inventing_one` | `timestamp is None`, is *not* a `str`, and survives a JSON round-trip (item 21). |
| `..._every_transport_control_is_disabled_...` | All four `can_*` are `False`, **and** that `live is False` / `window() is None` are the reasons — so a later change that derives the buttons from the *position* fails here. |
| `..._transport_operations_degrade_instead_of_crashing` | `pause/play/tick/step_forward/step_back/reset/seek_fraction` all return honest absence. Covers the unreported `_sync` site. |
| `..._does_not_buy_itself_by_swallowing_the_panel_refusal` | **The load-bearing anti-regression.** `frame()`/`views()`/`view("A")` still raise *positively*, with `TODO:` + both PRD documents. A future "fix" that made the panels return zeros would pass every other test in the file and fail this one. |
| `..._still_read_exactly_once_at_construction` | The seed stayed **eager**: 1 call at construction, 1 per frame. Guards item 21/23 — a lazy seed would have made `frame()` read the provider twice with two different noise realisations, breaking "every screen shows the same instant". |
| `..._still_reports_its_real_position` | Happy path: a readable source still reports its real timestamp. |

**The test was verified to fail without the fix.** `clock.py` was reverted, the file re-run
(**5 errors, 2 passed** — the 2 being the happy-path stub tests, which correctly pass either way),
then the fix reapplied. A regression test that passes both ways would have been worthless.

---

## 6. Full regression result

Run **once**, at the end, as required:

```
524 passed, 2 xfailed in 352.22s
```

- Baseline was **517 passed, 2 xfailed**. 517 + 7 new = **524**. No pre-existing test changed status.
- The 2 `xfail(strict=True)` B-7 badge pins remain **xfailed** — untouched, as required. Wave 3A did
  not go near either badge site.
- Regression floor (428) comfortably held.

---

## 7. Git status

One commit, made only after the verification above. Working tree otherwise clean; frozen layer
verified byte-identical before and after (§4).

---

## 8. Remaining Task #6 items

Not started in this wave, by instruction:

| Item | Status |
|---|---|
| **B-7 badge** (`state.py:570` + `svg_twin.py:530`) | Open. Both sites hard-code the synthetic badge; 2 strict xfails hold the correct behaviour. Directive D-8. |
| **BUG 2** | Open. |
| **Twin missing-data symmetry** | Open. |
| **`DATA_DICTIONARY.md`** | Missing (PRD §35). |
| **`DEMO_GUIDE.md`** | Missing (PRD §35). |
| **`TestNfr2Budget`** | Not written. |
| **Item 15 requirement text** | **UNRECOVERED** (directive D-1). Task #6 cannot be declared complete while it stands. |
| Items 17, 19, 22 renderers/enforcement | Missing — see `TASK6_DIRECTIVE.md` §1. |

### Raised by this wave (not acted on)

1. **`ProviderCapabilities.missing` is dead and inconsistent.** Two vocabularies, zero consumers
   (§1). It is advertisement text that reads like a contract. Either give it one vocabulary and a
   consumer, or document it as descriptive only. **Not** a Wave 3A change.
2. **The contract has no flag for its seven required surfaces.** `frame()` therefore cannot be
   capability-gated today (§3). Making the ten screens render over a source that supplies no process
   state needs a deliberate design decision — a new capability term *and* a per-view absence
   representation — and is a directive-level question, not a patch.
3. **`RealPlantDataProvider` refuses with bare `NotImplementedError`, not `CapabilityError`.** Since
   `CapabilityError` is the type the contract says the dashboard should catch, and it subclasses
   `NotImplementedError` (so PRD 26.1's wording would still hold), switching would let callers
   distinguish "cannot supply" from a genuine coding error. Left alone: it changes 14 refusal sites
   in a PRD-verbatim deliverable, which is outside this wave's remit.

---

## 9. Stop

Wave 3A complete and stopped here. No other Wave 3 item was started, no background or parallel
subagent was used, the frozen layer is untouched, and the full suite was run exactly once.
