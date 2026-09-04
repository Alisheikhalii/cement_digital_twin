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

### 0.2 All ten screens render; the AI story is now screens, not JSON

All ten views have a renderer: **B (Kiln Digital Twin)** and **E (Cement Mill Digital Twin)** — the
animated SVG twin — plus **J, H, A, G, I** and **C, D, F** (one shared process renderer), and the
**Factory Presentation Mode** overlay (`--view P`, §7). A view that cannot be built is stated as a
failure, never filled in with a substitute number.

| Screen | Use it as | Renderer? |
|---|---|---|
| **B**, **E** | The visual centrepiece. Show these full-screen. | **Yes — animated SVG twin** |
| A, C, D, F, G | The process and energy story, as designed screens. | **Yes** |
| H, I, J | The AI story, as designed screens. | **Yes** |
| **P** | The plant-manager overlay of A + J (PRD 29). | **Yes** |

For a plant-manager audience (PRD Persona 3), **lead with `--view P`** (§7) or with B and E, and
narrate the AI screens from your notes rather than reading every number aloud.

*(History: earlier builds rendered only B and E, printing the other eight as a raw JSON payload.
The JSON fallback still exists in `app.py` as a safety net, but no A–J screen uses it.)*

### 0.3 There is no Colab notebook

PRD 28 specifies each demo as "a single Colab cell (Section 25, cell 11)". **No `.ipynb` exists in
this repository.** Every demo below is therefore a **command-line invocation**. If the customer was
promised a Colab link, reset that expectation before the meeting.

### 0.4 The model layer is slow; budget for it

Measured on the development machine at the time of writing, from `app.py`'s own stderr timings.
**`--skip-models` costs ~4.5 s, not sub-second** — the frame load dominates; `app.py`'s docstring
carries the measured figure.

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
5. Scroll to **view A (Plant Overview)** — a designed screen: the five-stage chain with each stage's
   `RUNNING` / `IDLE` / `UNKNOWN` state word, derived from that stage's own throughput tag.
6. Flip between `d1_start.html` and `d1_steady.html` to show the transition.

### Say this

> "This is a synthetic plant, running the kiln and mill process models with an enforced energy and
> mass balance. Every number you see came out of the simulation — nothing on this screen is a
> placeholder."

### Watch out

- `UNKNOWN` on a stage is **honest**, not broken: it means the provider supplied no throughput value
  for that stage. Say so plainly if it appears.
- View A is a rendered screen (§0.2). Walk the five-stage chain, the plant KPI group, and the two
  AI status tiles (they state their own reason when a model is absent).

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
2. Open `reports/d2_optimization.html`. This is **view J**, a designed screen (§0.2). Walk it in the
   order below; the headline, gates and quality pill are all rendered.
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
     comparison: the **five PRD 14.5 rows** on the shared metric set, unavailable rows showing
     their own reason; beside it the **multi-horizon predicted-state grid**, each value with its
     `±` ensemble spread — never a confidence percentage.
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
5. Scroll to **view H (AI Prediction & Anomaly)** — a designed screen (§0.2). Read out:
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

> **⚠ One limit on this demo as built.**
> 1. **What-if changes are set on the command line** (`--change separator_speed_rpm=+5 --view I`,
>    repeatable, with `--mode NORMAL|EXPERIMENTAL` — see §6.3). A CLI-rendered view I shows the
>    configured sliders and the engine's answer for the change you named on the command line;
>    the Python snippet in §6.2 remains the path when you want the raw view model live.
>
> The transition chart **is** built: view I's export carries a self-contained SVG of each moved
> variable's commanded setpoint path — the hold at the baseline, then the variable's configured
> ramp — so the transition delay is visible as a picture, not only as numbers. The plant's
> *response* path is not carried by the payload (only its settled endpoints are), so the chart
> states that rather than drawing an interpolated curve; read the settled numbers from the
> before/after table beside it.

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
   Open both. Compare the four tags side by side. Same physics, same trade-off, selected by
   scenario — a second way to show the same move the What-if slider makes.
4. For a genuine operator-set change, run the Python snippet in §6.2 live in a terminal — or set
   the change directly on the command line (`--change separator_speed_rpm=+5 --view I`, §6.3) and
   let the export render the transition chart with it.

### Say this

> "Raise separator speed and you get a finer cement — and you pay for it twice, in throughput and in
> kilowatt-hours per tonne. The model won't let you have all three. That's the trade-off the
> optimizer is navigating in Demo 2."

### On the transition delay

PRD 16.2 requires the response to arrive with a **visible delay**, and the model does implement
per-relationship dead time plus lag (PRD 9.4/10.3, every parameter an `ASSUMPTION` documented in
`SIMULATION_ASSUMPTIONS.md` §5). View I's export shows the delay directly: the transition chart
draws the hold at the baseline and each variable's configured ramp as a picture, with the window,
hold and ramp minutes as numbers beneath it. For the *plant's* response building over time, export
the same scenario at increasing `--advance` values (§1.3) — the effect builds over successive
minutes rather than stepping instantly.

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

> **⚠ The CLI reaches both modes as of the View I wave.** `app.py` now accepts
> `--change NAME=PERCENT` (repeatable; percent of the variable's current value) and
> `--mode {NORMAL,EXPERIMENTAL}` — both view-I-only flags, so naming either without
> `--view I` is an error, never a silent no-op. The generic `view()` dispatch still passes
> only `frame`, so the flags ride along through a wrapper at the CLI entry point; a bare
> `--view I` with no `--change` remains the legal "what if we hold?" request in Normal Mode.
> §6.2's Python path still works and is the one to use when you want the raw view model in
> the room; §6.3 is the CLI path.

### 6.2 The Python path — how to show both modes from a REPL

Run this in a terminal (or a Python REPL) with the room watching. Since the View I wave the
CLI path (§6.3) reaches the same two modes without Python; this snippet remains the one to
use when you want the raw view model — the sliders, the notes and the notices — printed
live. **This snippet was executed and its output is reproduced below** — the field
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

### 6.3 The CLI path — the export, with a change and a mode

Since the View I wave, the export itself carries the mode toggle and the operator-set change
(the flags the Python snippet in §6.2 sets by hand):

```sh
# Normal Mode: "reduce fuel by 5 %" — inside the +/-10 % bound
python app.py --no-browser --seed 20240101 --view I \
  --change kiln_fuel_rate_tph=-5 --out reports/d5_whatif_normal.html

# Experimental Mode: "reduce fuel by 25 %" — needs the +/-30 % bound, and is bannered as
# low-reliability everywhere on the screen
python app.py --no-browser --seed 20240101 --view I \
  --change kiln_fuel_rate_tph=-25 --mode EXPERIMENTAL --out reports/d5_whatif_experimental.html
```

`PERCENT` is percent of the variable's current value (so `-5` is the −5 % of §6.2), the name
is validated against the schema's manipulated-variable list at parse time, and the flag is
rejected unless view I is requested — naming `--change` or `--mode` without `--view I` exits
with an error rather than silently ignoring it. The rendered screen is the full view-I panel:
the sliders with their configured bounds and step sizes, the requested-change table with the
engine's snapped/clipped flags and notes verbatim, the before/after comparison, the
constraint and envelope rows, and — in Experimental Mode — the fixed low-reliability banner,
which the renderer draws from the payload and never awards itself. Omit `--change` for the
null "what if we hold?" request, exactly as before the flags existed.

### Say this

> "Normal Mode holds every change inside ±10 % and inside the calibrated envelope. If you want to
> ask a bigger question, you can — but the system stops calling the answer reliable, and it says so
> in a banner it won't let us remove. It never writes a setpoint either way."

---

## 7. Factory Presentation Mode — implemented

**PRD 29** specifies a simplified rendering path for a plant-manager audience (Persona 3), showing
only the chain

```
Current Plant State → AI Prediction → Optimization Opportunity → Recommended Action → Expected Benefit
```

with five KPI cards — Potential Thermal Energy Saving, Potential Electrical Energy Saving, Production
Stability, Quality Stability, Anomalies Detected — every card labelled *"Synthetic Demonstration"* or
*"Simulation Estimate"*, a visible link to the PRD 21 transfer-strategy disclaimer, and no raw tag
lists, model internals, code or numeric confidence percentage anywhere.

**This mode exists now.** It is a re-rendering of views A and J (not a new data path), reachable
from the CLI:

```sh
python app.py --no-browser --seed 20240101 --view P --out reports/presentation.html
```

(Pre-build it — the view needs the model layer, so it is a slow one, like view J.)

What you get, in the PRD's own order:

| Element | What the card shows |
|---|---|
| **Potential Thermal Energy Saving** | view J's `expected_impact` daily-energy delta and per-metric %, labelled "Simulation Estimate" |
| **Potential Electrical Energy Saving** | same, electrical — labelled "Simulation Estimate" |
| **Production Stability** | **stated unavailable** — no model computes this metric; the reason is on the card, never a number |
| **Quality Stability** | **stated unavailable** — same honest gap |
| **Anomalies Detected** | Model B's own per-instant verdict (a verdict, not a count) |
| **The five-stage chain** | the PRD 29 sequence, refusal and unavailable states included as display states |

Every card carries one of the two mandated labels, the §21 disclaimer is quoted verbatim at the
bottom, and nothing on the screen is a raw tag list, a model internal, code, or a confidence
percentage — the sweeps are pinned by tests.

**Two honest limits, stated on the cards themselves:**

1. **The two stability cards carry no number.** PRD 29 *names* Production Stability and Quality
   Stability as cards; no model in this system computes either metric, and the nearest quantities
   (Model A's cross-horizon spread, the optimizer's penalty terms) are model internals this mode
   must not display. The cards state the absence. A number there would be invented.
2. **`presentation.refresh_seconds` is not consumed.** The export is a static HTML file — there is
   no refresh loop, and 2 s is an `ASSUMPTION`, not a response-time commitment. The real budget is
   **NFR-2 (a what-if round trip under 3 s)**.

For a Persona 3 audience this is now the lead screen: run `--view P`, then show the animated twin
(`--view B`, `--theme light`) for the visual.

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
| 1 | Ten rendered dashboard screens (PRD 18) | **10 of 10 rendered** (B, E — the SVG twin; J, H, A, G, I — and C, D, F via one shared process renderer). | None needed — every screen renders. |
| 2 | Live/interactive dashboard (PRD 19.1 loop) | **No loop, no server, no interactivity.** `app.py` writes one static HTML file. | §0.1, §1.3 — re-export with `--advance`. |
| 3 | Each demo as a single Colab cell (PRD 25 cell 11, PRD 28) | **No `.ipynb` exists in the repo.** | Every demo here is a CLI invocation. |
| 4 | Anomaly view's **"Inject abnormal condition"** control + `DemoInjector` (PRD 15, 28.3) | **Does not exist.** Referenced in a docstring and in PRD 23's tree; no such symbol. | §4 — schedule the regime with `--scenario` instead. |
| 5 | **Experimental What-if Mode** reachable in the UI (PRD 16.1, 28.5) | **Exposed.** `--mode {NORMAL,EXPERIMENTAL}` on the CLI (view I only). | §6.3 — the CLI flag. |
| 6 | Operator-set what-if changes (PRD 16.1) | **Exposed.** `--change NAME=PERCENT`, repeatable, validated against the schema's variable list. | §6.3 — the CLI flag. |
| 7 | Before/after **chart** with visible transition delay (PRD 16.2) | **Built for view I** — a self-contained SVG transition chart (each moved variable's commanded setpoint path: hold, then configured ramp; zero plotting dependencies). The plant's response path is not on the payload, so the chart states that instead of drawing an interpolated curve. | §5 — the chart renders in the view I export. |
| 8 | **Factory Presentation Mode** (PRD 29) | **Implemented** (`--view P`): the A + J overlay, five cards (two stability cards honestly unavailable), five-stage chain, §21 verbatim, forbidden-content sweeps test-pinned. See §7. | §7. |
| 9 | **"Run Demo" scripted sequence** (PRD 28, directive item 19) | **Not built.** Each demo is run by hand; PRD's "single Colab cell" framing is unsatisfied because no notebook exists (row 3). | Pre-build artefacts per §1.4. |
| 10 | An accurate `--skip-models` cost in `app.py`'s own docstring | **Fixed** — the docstring says "~4.5 s measured". | §0.4 — the measured table. |

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
- [ ] Views H/I/J pre-opened and walked once — they are designed screens now, but the AI story
      still reads best narrated rather than scanned line by line.
- [ ] If you plan to show Experimental Mode: a terminal open, `src/` importable, §6.2 snippet tested.
- [ ] §9 re-read against `docs/PROJECT_STATE.md` — confirm nothing you plan to show has moved.
- [ ] You can say the three honesty answers in §8 without reading them.

---

**Related documents:** `DATA_DICTIONARY.md` (every tag, unit and assumption you may be asked about) ·
`SIMULATION_ASSUMPTIONS.md` (every constant and what would replace it) ·
`FACTORY_DATA_REQUIREMENTS.md` (what to leave with the customer) · `ARCHITECTURE.md` (the
`DataProvider` answer to "can it run on our data?") · `docs/PROJECT_STATE.md` (what is built today).
