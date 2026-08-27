# DEMO_GUIDE.md

**Audience:** sales / solutions engineer (PRD Section 35).

**Purpose:** a step-by-step script for Demos 1–5 (PRD Section 28) and Factory Presentation Mode
(PRD Section 29), including how to demonstrate Normal vs Experimental What-if Mode (PRD 16.1).

---

## 0. READ THIS FIRST — what you are actually demonstrating today

This guide is written against **what `app.py` and the view modules do right now**, not against the
PRD's target state. Four facts change how you should run the meeting. None of them is a defect to
hide — the honesty is the product — but walking in expecting a live web dashboard will cost you the
room.

### 0.1 It is a one-shot HTML export, not a live dashboard

`python app.py` builds a session, renders the screens you named, and writes **one self-contained
`.html` file** (default `reports/task6_dashboard.html`) that opens in any browser with no server, no
network and no assets. There is **no refresh loop, no server, and nothing to click.**

The SVG twin *does* animate — inline SVG plus CSS `@keyframes` — but it animates around a **process
state frozen at the moment of export**. Motion on screen means "this stream is flowing at the rate
sampled at export time", not "this is updating live". To show change over time you **re-export**
with `--advance` (see §1.3). Say "exported snapshot", never "live feed".

### 0.2 Eight of the ten screens render as raw JSON, not as a designed screen

Only **B (Kiln Digital Twin)** and **E (Cement Mill Digital Twin)** have a renderer — the animated
SVG twin. The other eight views (**A, C, D, F, G, H, I, J**) are **fully built and correct view
models**, but `app.py` prints them as an indented JSON payload in a `<pre>` block, under the label
*"View-model payload (no renderer for this screen yet)"*.

This is deliberate (`app.py:_payload_html`): the alternative was a prettier screen built from
invented numbers. **The numbers are real; the presentation is not built.** Plan accordingly:

| Screen | Use it as | Renderer? |
|---|---|---|
| **B**, **E** | The visual centrepiece. Show these full-screen. | **Yes — animated SVG twin** |
| A, C, D, F, G | Talk-over evidence: point at a value in the JSON to substantiate a claim. | No — JSON payload |
| H, I, J | The AI story. Read the headline fields out loud; do not project the raw JSON to a non-technical room. | No — JSON payload |

For a plant-manager audience (PRD Persona 3), **lead with B and E** and narrate H/I/J from your own
notes rather than projecting them.

### 0.3 There is no Colab notebook

PRD 28 specifies each demo as "a single Colab cell (Section 25, cell 11)". **No `.ipynb` exists in
this repository.** Every demo below is therefore a **command-line invocation**. If the customer was
promised a Colab link, reset that expectation before the meeting.

### 0.4 The model layer is slow; budget for it

Measured on the development machine at the time of writing, from `app.py`'s own stderr timings.
**Do not trust the "~0.4 s" figure in `app.py`'s module docstring for `--skip-models` — it is wrong
by an order of magnitude.** The docstring was not corrected in this wave because this wave changed no
production file; it is logged as a gap in §9.

| Invocation | Measured | Gets you |
|---|---|---|
| `--skip-models`, 1 view | **4.5 s** (`load_frames` 4.1 s) | Views A–G only. H/I/J report "no model" — honestly, not blankly. |
| `--skip-models`, 4 views + `--advance 30` | **4.6 s** (`load_frames` 3.0 s) | Extra views cost ~0.005 s each; the frame load dominates. |
| default (models on), all 10 views | **21.0 s** reported / **25.7 s** wall clock | All ten views. `model_layer` alone is 11.8 s; view J 5.1 s, I 2.2 s, H 1.4 s. |
| `--replay` | **+ a second full simulation run** | The recorded replay window. Slow — only if asked. |

Two things worth knowing before you quote any of these:

- **`load_frames` is not stable between runs** — it came in at 4.1 s, 3.0 s and 0.12 s across three
  runs of the same command family. Treat the numbers above as an order of magnitude, not a spec.
  Re-time on your own machine the morning of the demo (§1.1) rather than quoting this table.
- **Wall clock is ~5 s longer than the reported total** — interpreter start-up and imports happen
  before `app.py` starts its own stopwatch. The customer experiences the wall clock.

A full ten-view build produces a **~1.0 MB** self-contained HTML file. That opens fine locally; it is
large for an email attachment.

**Never run a full build in front of a customer without warning them.** Pre-build every artefact
before the meeting (§1.4) and present from files.

---

## 1. Setup

### 1.1 Smoke test (do this the morning of the demo)

```sh
python app.py --skip-models --no-browser --out reports/smoke.html
```

Expected: timing lines for the session build and view `B`, then
`wrote …/reports/smoke.html (N bytes, self-contained)`. If that works, the twin works.

### 1.2 The flags you will actually use

```
--view ID        screen to render, repeatable. Takes the id (B) or the key (kiln_twin).
--scenario NAME  operating regime to drive the session with (from configs/scenarios.yaml)
--seed N         override configs/scenarios.yaml simulation.seed — makes a demo repeatable
--advance MIN    step the live clock this many simulated minutes before rendering
--theme          dark (default) | light  — use light for a projector in a bright room
--no-animate     render a still frame (for a screenshot or a slide)
--skip-models    seconds instead of tens of seconds; H/I/J report no model
--no-browser     do not auto-open the file
--out PATH       output file
--replay         also build the recorded replay window (a second simulation run — slow)
--help           every flag, every valid view and scenario
```

`python app.py --help` lists all ten views and every selectable scenario name. Trust it over this
guide if they ever disagree — it reads `src.digital_twin.state.VIEWS` and
`configs/scenarios.yaml` directly.

### 1.3 Showing change over time

`--advance MINUTES` steps the simulated clock **before** rendering. Two exports at different
`--advance` values, same `--seed`, are the same run at two different times — that is how you show a
transition:

```sh
python app.py --skip-models --no-browser --seed 20240101 --advance 0  --out reports/t0.html
python app.py --skip-models --no-browser --seed 20240101 --advance 30 --out reports/t30.html
```

Open both in adjacent browser tabs and flip between them.

### 1.4 Pre-build everything (recommended)

```sh
# fast artefacts — the visual centrepieces
python app.py --skip-models --no-browser --seed 20240101 --view B --view E --out reports/demo_twins.html
python app.py --skip-models --no-browser --seed 20240101 --view A --view G --out reports/demo_overview.html

# the slow one — the AI story. Run this once, well before the meeting.
python app.py --no-browser --seed 20240101 --view H --view I --view J --out reports/demo_ai.html
```

Fixing `--seed 20240101` matters: it makes every rehearsal identical to the live run. Reproducibility
is enforced by `tests/test_task6_reproducibility.py`, so the same seed really does give the same
screens.

**If a model-layer view cannot be built, `app.py` writes nothing at all** and prints the reason to
stderr — no partial file, no substituted numbers. That is the designed behaviour (directive rule:
*a guard must state an absence, never substitute a number*). If it happens in rehearsal, fall back
to `--skip-models` and present Demos 1, 3 and 4's process story without the model panels.

### 1.5 The scenario names you may pass to `--scenario`

Read verbatim from `configs/scenarios.yaml`. These are the PRD 11.4 operating regimes:

| Group | Names |
|---|---|
| Normal | `Normal - low production` · `Normal - medium production` · `Normal - high production` |
| Kiln abnormal | `High fuel condition` · `Low oxygen condition` · `High oxygen condition` · `Fan instability` · `Feed disturbance` · `Temperature disturbance` |
| Mill abnormal | `Mill overload` · `Mill underload` · `High separator speed` · `Low separator speed` |
| Cross-cutting | `Sensor drift` · `Startup transition` |

---

## 2. Demo 1 — Normal Operation

**PRD 28.1.** *Run the twin through the startup-like transition into steady medium production; show
Plant Overview settling to green/nominal.*

**What it proves:** the twin is a running process simulation with conservation closure, not a
mock-up.

### Steps

1. **Start from the startup transition.**
   ```sh
   python app.py --skip-models --no-browser --seed 20240101 \
       --scenario "Startup transition" --advance 0 \
       --view B --view A --out reports/d1_start.html
   ```
2. **Then the settled state.**
   ```sh
   python app.py --skip-models --no-browser --seed 20240101 \
       --scenario "Normal - medium production" --advance 30 \
       --view B --view A --out reports/d1_steady.html
   ```
3. Open `reports/d1_steady.html`. Lead with **view B, the animated kiln twin.** Let it run for a few
   seconds before you speak — the motion does the work.
4. Walk the material path on screen: feed → preheater → precalciner → rotary kiln → cooler → clinker.
   Note that **every animation parameter is bound to simulated state**, never to a decorative
   constant: a stream's motion is driven by that tag's fraction of its documented range.
5. Scroll to **view A (Plant Overview)** — JSON payload. Point at each stage's `state` field:
   `RUNNING` / `IDLE` / `UNKNOWN`, derived from that stage's own throughput tag.
6. Flip between `d1_start.html` and `d1_steady.html` to show the transition.

### Say this

> "This is a synthetic plant, running the kiln and mill process models with an enforced energy and
> mass balance. Every number you see came out of the simulation — nothing on this screen is a
> placeholder."

### Watch out

- `UNKNOWN` on a stage is **honest**, not broken: it means the provider supplied no throughput value
  for that stage. Say so plainly if it appears.
- View A is JSON (§0.2). Don't apologise for it — say the presentation layer for the overview screen
  is the next build increment, and the data behind it is what you're showing.

---

## 3. Demo 2 — Energy Optimization

**PRD 28.2.** *From a stable but sub-optimal steady state, run Model C and show the Recommendation:
hard-constraint filtering, envelope/OOD validation, the multi-objective breakdown, a positive
thermal-energy saving, `constraint_status = PASS`, `recommendation_quality`, and its natural-language
reason — compared against all five baselines.*

**What it proves:** the optimizer refuses to trade away a hard constraint, and reports quality as a
category rather than a fabricated percentage.

**Needs the model layer — pre-build this.** A ten-view build measured 25.7 s wall clock; views H/I/J
alone are the expensive part (§0.4). Never build this one live.

### Steps

1. **Pre-build, before the meeting:**
   ```sh
   python app.py --no-browser --seed 20240101 \
       --scenario "High fuel condition" --view J \
       --out reports/d2_optimization.html
   ```
   `High fuel condition` is the "stable but sub-optimal — slightly high fuel relative to feed" state
   PRD 28.2 asks for.
2. Open `reports/d2_optimization.html`. This is **view J**, a JSON payload (§0.2). Read the fields
   out loud rather than projecting them raw.
3. **Lead with the header notices.** View J always carries `AI Recommendation`, `Decision Support
   Only`, and *"Simulated saving from a synthetic model — not a guaranteed real-world saving."* Read
   the third one verbatim. It is the most credible thing you will say all meeting.
4. Walk the payload in this order:
   - `headline` / `message` — the recommendation in plain language.
   - `gates` — the PRD 14.3 checks. Each has a `blocking` flag. **This is the envelope/OOD story:**
     candidates are filtered *before* scoring, so a large energy gain cannot buy its way past a
     safety limit.
   - `evaluated` and `rejected_candidates` — how many candidates were considered and how many the
     hard constraints threw out. The rejection count is the proof that filtering happened.
   - `payload.recommendation` — the setpoint changes, the objective breakdown, and the baseline
     comparison.
   - `recommendation_quality` — **HIGH / MEDIUM / LOW**, glossed by `quality_descriptions` in the
     same payload.

### The one thing you must not say

There is **no confidence percentage anywhere in this system**, by design (PRD 14.4, FR-23). Quality
is the categorical HIGH/MEDIUM/LOW only, and it is a **heuristic** derived from documented factors
(ensemble spread, envelope distance, constraint margin, model agreement) — *not* a calibrated
statistical probability. If asked for a percentage:

> "We deliberately don't produce one. A confidence number from an uncalibrated model is worse than
> no number, because it invites a decision it can't support. Conformal prediction intervals are a
> Phase-2 item."

### If the optimizer refuses

`refused: true` with `refusal_reasons` and the headline *"No safe recommendation found"* is a
**first-class success state**, not a failure. Demo it deliberately if it comes up:

> "It just declined to recommend anything, and told us which gate blocked it. That's the behaviour
> you want from decision support near a safety limit."

---

## 4. Demo 3 — Low Oxygen

**PRD 28.3.** *Trigger regime 5 via the Anomaly view's "Inject abnormal condition"; show Model B
detection, the warning card, and the rule-engine suggested action.*

> **⚠ The PRD's mechanism does not exist.** There is **no "Inject abnormal condition" control**, and
> **no `DemoInjector`** — the class is referenced in a module docstring and in PRD 23's directory
> tree, but **no such symbol exists in the codebase**. There is no interactive injection, because
> there is no interactive UI at all (§0.1).
>
> **What to do instead:** select the regime up front with `--scenario "Low oxygen condition"`. The
> abnormal condition is then **scheduled** by the scenario driver rather than injected mid-demo. The
> observable end state is the same; the theatre of pushing a button is not available.

**Needs the model layer for the detection story — pre-build.**

### Steps

1. **Establish the normal baseline** (fast, can be live):
   ```sh
   python app.py --skip-models --no-browser --seed 20240101 \
       --scenario "Normal - medium production" --advance 30 \
       --view B --out reports/d3_normal.html
   ```
2. **Pre-build the abnormal state with the model layer on:**
   ```sh
   python app.py --no-browser --seed 20240101 \
       --scenario "Low oxygen condition" --advance 30 \
       --view B --view H --out reports/d3_lowo2.html
   ```
3. Show `d3_normal.html` view B first. Note `oxygen_percent` sitting inside its 0.7–4.0 % band.
4. Switch to `d3_lowo2.html` view B. **Point at `oxygen_percent` and `CO_ppm` together** — the
   physical signature of the regime. `CO_ppm` will run above its 0–300 ppm band; that is the
   documented, intended behaviour under fault, not a simulation error.
5. Scroll to **view H (AI Prediction & Anomaly)** — JSON payload. Read out:
   - the **anomaly hypothesis**, labelled as a hypothesis, never as a diagnosis;
   - the **rule-engine suggested action**, labelled as rule-based and explicitly distinct from the
     AI recommendation;
   - the evidence fields the detector used.
6. If the evidence is inconclusive, the view says so (`Evidence inconclusive`). Read it as-is.

### Say this

> "Two independent channels agree something is wrong: the process reading left its documented band,
> and the anomaly model flagged it. The system calls that a hypothesis, not a diagnosis — and the
> suggested action next to it is from the explicit rule engine, not from the model."

### Watch out

Model B's label output is *not* the `injected_fault` column. That column is **simulator ground
truth** and exists only so the model can be scored offline (see `DATA_DICTIONARY.md` §1.3). A real
plant has no such column — which is exactly why PRD 21.3 says this environment **cannot** validate
real-world detection performance. Never point at `injected_fault` as evidence the detector works.

---

## 5. Demo 4 — Mill Optimization

**PRD 28.4.** *Change separator speed/feed via What-if (Normal Mode); show the throughput / Blaine /
energy trade-off explicitly (before/after table + chart with visible transition delay).*

**What it proves:** the mill model demonstrates a real trade-off — there is no free lunch.

> **⚠ Two limits on this demo as built.**
> 1. **You cannot set what-if changes from the command line.** `app.py` has no `--change` flag, and
>    `DashboardState.view("I")` dispatches without a change set — so a CLI-rendered view I shows the
>    **configured sliders and the engine's answer for a null change set**, not a change you chose in
>    the room. To set an actual change you must use the Python snippet in §6.2.
> 2. **There is no chart.** Any view wanting one degrades through
>    `src.visualization.charts.missing_chart_html` rather than importing a plotting library. The
>    before/after **numbers** are in the payload; the **chart is not built**. Bring your own slide if
>    the room needs a picture.

### Steps

1. **Show the mill twin first** — this one is a real rendered screen:
   ```sh
   python app.py --skip-models --no-browser --seed 20240101 \
       --scenario "Normal - medium production" --advance 30 \
       --view E --out reports/d4_mill.html
   ```
   Walk the closed grinding circuit: feed → mill → separator → fines to product, coarse recirculated.
2. **Name the four tags that carry the trade-off** and read them off the mill panel:

   | Tag | Unit | Role in the trade-off |
   |---|---|---|
   | `separator_speed_rpm` | rpm | **the lever** — the primary quality control |
   | `simulated_blaine_cm2_g` | cm²/g | fineness — goes **up** as the lever goes up |
   | `cement_production_tph` | t/h | throughput — goes **down** |
   | `specific_power_consumption_kwh_t` | kWh/t | energy per tonne — goes **up** |

3. **Demonstrate the trade-off by scenario**, which the CLI *can* do:
   ```sh
   python app.py --skip-models --no-browser --seed 20240101 \
       --scenario "High separator speed" --advance 30 --view E --out reports/d4_fine.html
   python app.py --skip-models --no-browser --seed 20240101 \
       --scenario "Low separator speed"  --advance 30 --view E --out reports/d4_coarse.html
   ```
   Open both. Compare the four tags side by side. **This is the honest CLI substitute for the
   What-if slider**: same physics, same trade-off, selected by scenario instead of by slider.
4. For a genuine operator-set change, run the Python snippet in §6.2 live in a terminal.

### Say this

> "Raise separator speed and you get a finer cement — and you pay for it twice, in throughput and in
> kilowatt-hours per tonne. The model won't let you have all three. That's the trade-off the
> optimizer is navigating in Demo 2."

### On the transition delay

PRD 16.2 requires the response to arrive with a **visible delay**, and the model does implement
per-relationship dead time plus lag (PRD 9.4/10.3, every parameter an `ASSUMPTION` documented in
`SIMULATION_ASSUMPTIONS.md` §5). Show it by exporting the same scenario at increasing `--advance`
values (§1.3) — the effect builds over successive minutes rather than stepping instantly.

---

## 6. Demo 5 — What-if Analysis, and Normal vs Experimental Mode

**PRD 28.5.** *"What happens if we reduce fuel by 5 %?" in Normal Mode, then optionally "what if we
reduce it by 25 %?" in Experimental Mode to show the envelope-warning banner.*

**This is the demo that shows the safety architecture.** It is also the one that most needs the
Python path.

### 6.1 What the two modes are

Straight from `configs/optimization.yaml → modes:`:

| | **Normal** | **Experimental** |
|---|---|---|
| Max change per setpoint | `max_delta_fraction: 0.10` — **±10 %** of current | `max_delta_fraction: 0.30` — **±30 %** |
| Envelope enforced? | `enforce_envelope: true` — all four PRD 14.3 checks | `enforce_envelope: false` |
| Banner | none | **mandatory**: *"Outside calibrated operating envelope — low reliability."* |
| Source of the bound | PRD 14.2/14.3/16.1 | **`ASSUMPTION`** — an exploration bound for the UI sliders, not a PRD number |

The PRD's own script asks for **−5 %** (inside Normal's ±10 % bound) and then **−25 %** (which
exceeds ±10 %). That contrast is the whole point: Experimental Mode is the **only** path that can
explore beyond the calibrated envelope, and it always carries the low-reliability banner.

> **⚠ A request outside the bound is clipped, not refused — and −25 % does *not* come back `PASS`.**
> This was measured, not inferred (see the table in §6.2). The engine snaps every requested change
> onto the slider grid and then clips it to the mode bound; the resulting verdict is
> `REJECTED / OUTSIDE ENVELOPE` in **both** modes for −25 %. Experimental Mode does not make a −25 %
> cut acceptable — it widens the slider band and adds the banner. If your slide says "Experimental
> Mode approves the aggressive change", change the slide.
>
> There is also a floor **neither** mode crosses: the tag's absolute range from `src/schema.py`.
> −25 % of 6.240 t/h is 4.680 t/h, below `kiln_fuel_rate_tph`'s absolute minimum of 4.975 t/h, so
> Experimental clipped to 4.975 (−20.27 %) even with `enforce_envelope: false`. That is a good thing
> to say out loud: *"even the exploration mode will not leave the physical range of the tag."*

> **⚠ Experimental Mode is not reachable from the command line.** `DashboardState.view(view_id)`
> dispatches as `getattr(self, key)(frame=frame)` — it passes **only** `frame`, so `mode` keeps its
> `"NORMAL"` default. `app.py` exposes **no `--mode` flag**. Both modes are fully implemented and
> tested in the view layer; only the *CLI surface* is missing. Use §6.2.

### 6.2 The Python path — how to actually demonstrate both modes

Run this in a terminal (or a Python REPL) with the room watching. It is the only way to show
Experimental Mode today. **This snippet was executed and its output is reproduced below** — the field
names are the real ones, not plausible ones.

> **Run it from the repository root.** `import src...` resolves against the current directory in a
> REPL, but if you save this as a script somewhere else, Python puts *that file's* directory on
> `sys.path` and the import fails with `ModuleNotFoundError: No module named 'src'`. Either paste it
> into a REPL started in the repo root, or set `PYTHONPATH` to the repo root first.

```python
from src.config import SCENARIOS, Config, load_config
from src.digital_twin.session import DashboardSession
from src.digital_twin.state import DashboardState

# same fixed seed as the pre-built artefacts, so the numbers match your slides
raw = load_config(SCENARIOS).to_dict()
raw["simulation"]["seed"] = 20240101
session = DashboardSession.build(live=True, scenarios=Config(raw, source="demo"))
state = DashboardState.from_session(session)


def show(label, vm):
    print(f"{label}: mode={vm.mode}")
    print(f"   verdict = {vm.view.verdict!r}")
    print(f"   action  = {vm.view.action!r}")
    print(f"   banner  = {vm.view.banner!r}")
    for n in vm.header.notices:
        print("   notice:", n)
    for n in vm.view.notes:
        print("   note:", n)


# --- Normal Mode: "reduce fuel by 5 %" -> inside the +/-10 % bound -------------------
show("NORMAL", state.what_if(delta_fractions={"kiln_fuel_rate_tph": -0.05}, mode="NORMAL"))

# --- Experimental Mode: "reduce fuel by 25 %" -> needs the +/-30 % bound -------------
show("EXPERIMENTAL", state.what_if(delta_fractions={"kiln_fuel_rate_tph": -0.25}, mode="EXPERIMENTAL"))
```

`WhatIfView` has **no `headline` field** — that property belongs to `OptimizationView` (view J). What
view I gives you is `verdict`, `action`, `banner`, `notes`.

**Measured outcomes** — what actually comes back, so nothing surprises you live:

| Request | `mode` | `verdict` | `banner` | Header notices |
|---|---|---|---|---|
| −5 % fuel | `NORMAL` | `PASS / WITHIN ENVELOPE` | `None` | 3 |
| −25 % fuel | `NORMAL` | `REJECTED / OUTSIDE ENVELOPE` | `None` | 3 |
| −25 % fuel | `EXPERIMENTAL` | `REJECTED / OUTSIDE ENVELOPE` | the low-reliability text | **4** |

**What to point at:** the Normal run carries three standing notices (`AI Recommendation`,
`Decision Support Only`, the simulated-saving caveat). The Experimental run carries **a fourth** —
*"Outside calibrated operating envelope — low reliability."* That banner is added by
`_decision_notices` whenever the mode is `EXPERIMENTAL`, at the header, **before** the result is even
read, and the payload carries its own `banner` field too. It cannot be dismissed and cannot be
configured away. This is the strongest honesty moment in the whole demo — use it.

**What not to be caught out by**, all of it visible in the output above:

- **The `action` string lists every manipulated variable, not just the one you changed.** Asking for
  −5 % on `kiln_fuel_rate_tph` still prints small moves on `kiln_feed_rate_tph` (190.2 → 190 t/h,
  −0.12 %), `kiln_speed_rpm`, `separator_speed_rpm` and `mill_feed_rate_tph`. Those are **the current
  values snapped onto the slider grid**, not recommendations. The `notes` list says so explicitly, one
  line per variable — read a note aloud if anyone asks. Do not present those four as advice.
- **`notes` distinguishes snapping from clipping.** `"snapped to the 1 t/h slider step"` is grid
  alignment; `"clipped to the [5.616, 6.864] mode bound"` is the ±10 % limit refusing to go further.
  Two different mechanisms, and the note names which one fired.
- **The verdict comes from the engine** (`PASS` / `REJECTED` / `NO SAFE RECOMMENDATION`) — the view
  reads it, never recomputes it.

Also show `vm.sliders` — six of them, and they **change with the mode**, which makes the mode switch
visible in data rather than only in a banner. For `kiln_fuel_rate_tph` at a current 6.240 t/h:

| Field | `NORMAL` | `EXPERIMENTAL` |
|---|---|---|
| `minimum` / `maximum` | 5.616 / 6.864 (±10 %) | 4.975 / 7.462 (the absolute range) |
| `max_delta_fraction` | `0.1` | `0.3` |
| `absolute_range` | 4.975 / 7.462 — **identical in both** | 4.975 / 7.462 |
| `step` | 0.0312 t/h — **identical in both** | 0.0312 t/h |

Each slider carries the **exact configured step size** the engine offers, so a caller sets changes in
the engine's steps and never in a step of its own. Note that `absolute_range` does not widen: the
schema range is the floor and ceiling in both modes.

### 6.3 If you cannot run Python in the room

Fall back to view I from the CLI and be explicit about what it is:

```sh
python app.py --no-browser --seed 20240101 --view I --out reports/d5_whatif.html
```

This shows the configured sliders, their bounds and step sizes, and the engine's answer for a null
change set, in Normal Mode. Say: *"these are the levers and the bounds the engine will accept; the
mode switch is implemented in the engine and not yet wired to this export."* Do **not** imply you
changed something.

### Say this

> "Normal Mode holds every change inside ±10 % and inside the calibrated envelope. If you want to
> ask a bigger question, you can — but the system stops calling the answer reliable, and it says so
> in a banner it won't let us remove. It never writes a setpoint either way."

---

## 7. Factory Presentation Mode — **not implemented**

**PRD 29** specifies a simplified rendering path for a plant-manager audience (Persona 3), showing
only the chain

```
Current Plant State → AI Prediction → Optimization Opportunity → Recommended Action → Expected Benefit
```

with five KPI cards — Potential Thermal Energy Saving, Potential Electrical Energy Saving, Production
Stability, Quality Stability, Anomalies Detected — every card labelled *"Synthetic Demonstration"* or
*"Simulation Estimate"*, a visible link to the PRD 21 transfer-strategy disclaimer, and no raw tag
lists, model internals, code or numeric confidence percentage anywhere.

> ### ⚠ This mode does not exist yet. Do not promise it or demo around it.
>
> **What exists:** exactly two configuration keys and their typed reader.
>
> | Artefact | Where | State |
> |---|---|---|
> | `presentation.refresh_seconds: 2.0` | `configs/dashboard.yaml` | `ASSUMPTION` — wall-clock cadence of the presentation loop. **The loop it configures does not exist.** |
> | `presentation.headline_decimals: 1` | `configs/dashboard.yaml` | `ASSUMPTION` — rounding of the headline KPI numbers. **The headline KPIs do not exist.** |
> | `PresentationSettings` | `src/digital_twin/settings.py` | Reads the two keys above. Nothing consumes it. |
> | `labels.presentation_card_label()` | `src/labels.py` | Owns the two mandatory card labels. **Currently used only for the twin header badge**, not for any presentation card. |
>
> **What does not exist:** the view itself. There is **no view id**, no renderer, no KPI cards, no
> five-stage chain, no refresh loop, and no presentation entry point in `app.py`. None of the five
> PRD 29 KPI cards is computed anywhere.
>
> `refresh_seconds: 2.0` is worth one extra caution: it is an `ASSUMPTION` about a presentation
> loop's cadence, and it is **not** a PRD performance budget. The real budget is **NFR-2: a what-if
> round trip in under 3 s**. Do not quote 2 s as a system response-time commitment.

### What to do for a plant-manager audience instead

You can approximate PRD 29's *narrative* with what is built, as long as you don't call it
Presentation Mode:

1. **Current Plant State** → view **B** or **E**, the animated twin. This is the one screen that
   genuinely looks like a product. Show it full-screen, `--theme light` for a bright room.
2. **AI Prediction** → view **H**. Read the forecast out loud from your notes; do not project JSON.
3. **Optimization Opportunity / Recommended Action / Expected Benefit** → view **J**. Read the
   headline, the quality category, and the simulated-saving caveat.
4. Every exported file already carries the three honesty badges (*Synthetic Demonstration*,
   *Decision Support Only*, *Not validated against real plant data*) in its header and the three
   standing PRD statements in its footer — so the labelling requirement of PRD 29 is met by the
   export, even though the layout is not.

Steps 2 and 3 mean projecting JSON to a plant manager, which PRD 29 explicitly rules out ("never
displays raw tag lists, model internals, code"). **So for a Persona 3 audience: show the twin, and
narrate the AI story from slides you prepared from the payload.** That is the honest shape of this
demo today.

---

## 8. Honesty script — the lines that must be said, and the ones that must not

Every exported file carries these automatically. Know them, because a customer will ask.

**In the header of every export:** `Synthetic Demonstration` · `Decision Support Only` ·
`Not validated against real plant data`

**In the footer of every export**, verbatim from `src/labels.py`:

> This dashboard reads a synthetic simulation. It is not connected to any plant, it reads no plant
> instrument, and it writes no setpoint: every recommendation is decision support for a human
> operator.

> This is a synthetic demonstration environment. The simulation is not calibrated against a real
> cement plant. The AI models are not production-validated. Energy-saving percentages are simulation
> results, not guaranteed factory savings. Real deployment requires real historical data,
> process-engineering validation, plant-specific calibration, OT/IT integration, cybersecurity
> review, operator validation, safety validation, and commissioning.

> The synthetic model is a development and demonstration environment, not a calibrated representation
> of any specific cement plant.

### Never say

| ✗ Do not say | ✓ Say instead |
|---|---|
| "connected to the plant" | "reads a synthetic simulation" |
| "automatic control" / "closed loop" | "decision support only — it writes no setpoint" |
| "we'll save you 4 %" | "the simulation shows a 4 % saving — not a guaranteed factory saving" |
| "the model is 87 % confident" | "recommendation quality is HIGH — a category, not a probability. We deliberately publish no confidence percentage." |
| "validated" | "not validated against real cement-plant data" |
| "live dashboard" | "exported snapshot of a running simulation" |

The phrase **"Automatic Control Command"** is forbidden system-wide (PRD 30, FR-16) and asserted
against by tests. Every AI output is labelled **"AI Recommendation"**.

### The three questions you will get

**"Is this our plant's data?"**
> "No. It's a synthetic plant built from published cement-engineering benchmarks. Every range is a
> documented assumption — they're all listed in `DATA_DICTIONARY.md`, and each one names the
> measurement that would replace it. Calibrating against your historian is the first step of a real
> engagement."

**"What would it take to run this on our data?"**
> "One interface. The whole dashboard reads a `DataProvider`, and there's already a second
> implementation pointing at a real-plant source. What we'd need from you is in
> `FACTORY_DATA_REQUIREMENTS.md` — the highest-value items are fuel LHV lab results and step-test
> logs, because those replace the two assumptions sitting under every energy number here."

**"Can it control the kiln?"**
> "No, and that's a design decision, not a gap. It never issues a control command. A real deployment
> would need explicit operator approval plus standard industrial interlocks and permissive logic
> before any recommendation could touch a setpoint — this system documents that requirement and
> deliberately doesn't build the pathway."

---

## 9. Consolidated gap list — every PRD demo capability not built yet

Flagged rather than written around, per the directive. Check this against `docs/PROJECT_STATE.md`
before each demo; items move.

| # | PRD asks for | State today | Workaround in this guide |
|---|---|---|---|
| 1 | Ten rendered dashboard screens (PRD 18) | **2 of 10 rendered** (B, E — the SVG twin). The other eight are correct view models printed as JSON. | §0.2 — lead with B/E, narrate the rest. |
| 2 | Live/interactive dashboard (PRD 19.1 loop) | **No loop, no server, no interactivity.** `app.py` writes one static HTML file. | §0.1, §1.3 — re-export with `--advance`. |
| 3 | Each demo as a single Colab cell (PRD 25 cell 11, PRD 28) | **No `.ipynb` exists in the repo.** | Every demo here is a CLI invocation. |
| 4 | Anomaly view's **"Inject abnormal condition"** control + `DemoInjector` (PRD 15, 28.3) | **Does not exist.** Referenced in a docstring and in PRD 23's tree; no such symbol. | §4 — schedule the regime with `--scenario` instead. |
| 5 | **Experimental What-if Mode** reachable in the UI (PRD 16.1, 28.5) | **Implemented in the view layer, not exposed.** `view()` passes only `frame`; `app.py` has no `--mode`. | §6.2 — the Python snippet. |
| 6 | Operator-set what-if changes (PRD 16.1) | **No CLI path.** No `--change` flag; CLI view I gets a null change set. | §6.2 Python, or §5 step 3 scenario substitute. |
| 7 | Before/after **chart** with visible transition delay (PRD 16.2) | **No chart.** Degrades through `missing_chart_html` by design — zero plotting dependencies. Numbers are present; the picture is not. | §5 — read the numbers, bring a slide. |
| 8 | **Factory Presentation Mode** (PRD 29) | **Two config keys and a settings reader only.** No view, no renderer, no KPI cards, no refresh loop. | §7 — approximate the narrative; do not call it Presentation Mode. |
| 9 | **"Run Demo" scripted sequence** (PRD 28, directive item 19) | **Not built.** Each demo is run by hand. | Pre-build artefacts per §1.4. |
| 10 | An accurate `--skip-models` cost in `app.py`'s own docstring | **The docstring says "~0.4 s"; measured 4.5 s.** Not corrected here — this wave changed no production file. | §0.4 — the measured table. |

**One more caution.** PRD 28 assumes the demos are *scripted and reproducible*. They are reproducible
— fix `--seed` and the screens are identical, enforced by `tests/test_task6_reproducibility.py`. They
are **not** scripted: there is no single command that runs Demo 1 through Demo 5. Pre-building per
§1.4 is the substitute.

---

## 10. Pre-demo checklist

- [ ] `python app.py --skip-models --no-browser --out reports/smoke.html` succeeds.
- [ ] Every artefact in §1.4 pre-built with a **fixed `--seed`**, opened once, and confirmed to render.
- [ ] The slow model-layer build (Demo 2, Demo 3) done **well before** the meeting — never live.
- [ ] `--theme light` exports ready if the room is bright.
- [ ] Slides prepared for views H/I/J so you never project raw JSON to a non-technical audience.
- [ ] If you plan to show Experimental Mode: a terminal open, `src/` importable, §6.2 snippet tested.
- [ ] §9 re-read against `docs/PROJECT_STATE.md` — confirm nothing you plan to show has moved.
- [ ] You can say the three honesty answers in §8 without reading them.

---

**Related documents:** `DATA_DICTIONARY.md` (every tag, unit and assumption you may be asked about) ·
`SIMULATION_ASSUMPTIONS.md` (every constant and what would replace it) ·
`FACTORY_DATA_REQUIREMENTS.md` (what to leave with the customer) · `ARCHITECTURE.md` (the
`DataProvider` answer to "can it run on our data?") · `docs/PROJECT_STATE.md` (what is built today).
