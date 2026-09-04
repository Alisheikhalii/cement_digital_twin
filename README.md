# Synthetic Cement Plant Digital Twin + AI Optimization Platform

> **Synthetic Demonstration · Decision Support Only · Not validated against real plant data**

> "The synthetic model is a development and demonstration environment, not a calibrated
> representation of any specific cement plant."
> — PRD v1.1.1 §21.5, required standing statement (`src/labels.py:38`)

A self-contained demonstration of the full path from a **physics-reasoned synthetic cement plant
simulation** through data generation, ML models and constrained optimization to an **operator-facing
digital-twin dashboard**. It exists to show the architecture and the interfaces working end to end
before any real plant is involved.

**What it is not.** It is not connected to a plant, it does not read an instrument, and it writes no
setpoint. Every number it displays comes from its own simulation. `configs/tag_mapping.yaml` is
deliberately empty (`sources: {}`), and `RealPlantDataProvider` exists only as a documented stub whose
fourteen data methods raise `NotImplementedError` with an explanation of what each would need
(`src/digital_twin/real_plant.py`). Nothing here has been validated against real plant data.

---

## Quick start

Python 3.11+ (`pyproject.toml`).

```bash
pip install -r requirements.txt

python app.py                              # builds reports/task6_dashboard.html and opens it
python app.py --view B --skip-models        # kiln twin only, no model layer (fast)
python app.py --view A --view G --theme light --no-browser
python -m pytest -q                        # test suite
```

Useful flags (`python app.py --help`): `--out PATH`, `--view ID` (repeatable, `A`–`J` or key),
`--scenario NAME`, `--seed N`, `--advance MINUTES`, `--theme {dark,light}`, `--no-animate`,
`--replay`, `--skip-models`, `--no-browser`.

The output is a single self-contained HTML file — no server, no external assets, no network calls.
Measured on one developer machine (not a specification): a warm full build ≈ **11.2 s** dominated by
the model layer, `--skip-models` ≈ **0.35 s**, one twin view rendered in ≈ **0.004 s**, output ≈
**25 KB**.

## The ten views

`A` overview · `B` kiln twin · `C` kiln process · `D` clinker cooler · `E` mill twin ·
`F` mill separator · `G` energy · `H` AI prediction & anomaly · `I` what-if · `J` optimization.
`H`, `I` and `J` need the model layer, so they are unavailable under `--skip-models`.

## Layout

```
app.py            dashboard entry point (CLI above)
src/simulation/   seeded synthetic plant: dynamics, delays, disturbances, sensors
src/process_models/   kiln + mill mass/energy balances
src/data_generation/  dataset builders; src/data_processing/  quality report (FR-13)
src/features/     leakage-safe feature engineering
src/models/       Model A (prediction), src/anomaly_detection/  Model B
src/optimization/ Model C: constrained recommendation with envelope + OOD gates
src/digital_twin/ the DataProvider seam, view-models, layout, the real-plant stub
src/visualization/  rendering; src/schema.py  the 62-row tag contract; src/labels.py  fixed wording
configs/          all tunable constants (every presentation number tagged ASSUMPTION)
docs/             PRD, architecture notes, factory data requirements
tests/            pytest suite: physics conservation, causality, leakage, provider contract, UI
```

## Honest status

- The core simulation, data, model and optimization layers (Tasks #1–#5) are complete and covered by
  the test suite.
- The dashboard layer (Task #6) is **substantially complete at the static-export level**: all ten
  A–J views have a validated view-model payload **and a renderer** — the animated SVG twin for
  B/E, designed HTML screens for A, C, D, F, G, H, I, J — plus the Factory Presentation Mode
  overlay (`--view P`, PRD §29). What remains open is recorded in `docs/PROJECT_STATE.md`: the PRD
  §17 non-lettered views (Time-Series Explorer, Model Performance, Data Quality, Factory Data
  Requirements) and PRD §18.1 trend sparklines.
- The dashboard is a **static HTML export**, not a live server: `app.py` writes one self-contained
  file. No refresh loop, no click interactivity — see `docs/DEMO_GUIDE.md` §0.1.
- The PRD §25 Colab notebook exists at `notebooks/00_cement_digital_twin_demo.ipynb`: the twelve
  §25 cells in order plus the five §28 demos as single re-runnable cells in its section 11 —
  thin orchestration over the importable `src/` package (NFR-7). See
  `docs/COLAB_NOTEBOOK_IMPLEMENTATION_REPORT.md`.
- Known architectural notes and deliberate non-fixes are listed in `docs/ARCHITECTURE.md`.

## Path to a real system

Short version: **supply data, then recalibrate, then retrain, then validate — in that order.** The
substitutability seam is one class. `DataProvider` (`src/digital_twin/provider.py`) is a 15-method
abstract contract; `SyntheticDataProvider` implements it today and a real plant would be a second
implementation behind the same contract, so nothing above the provider changes (FR-14).

1. **Map your tags.** Fill in `configs/tag_mapping.yaml` with `canonical_name: your_plant_tag` per
   connection profile (`csv` / `sql` / `opcua` / `historian` / `dcs` / `scada`). The concrete tag list —
   56 requestable tags across 8 process units, with units, roles and importance — is
   **[`docs/FACTORY_DATA_REQUIREMENTS.md`](docs/FACTORY_DATA_REQUIREMENTS.md)**, generated from the
   same `src/schema.py` the simulator writes against.
2. **Implement the adapter.** Fill in the fourteen `RealPlantDataProvider` methods. Each one already
   documents what data it needs and what degrades without it; `capabilities()` lets every panel
   degrade rather than crash.
3. **Assess quality.** Re-run the FR-13 data-quality report against the real export. This is the only
   step of the transition this repository can perform today.
4. **Recalibrate.** Every engineering constant, delay and loss fraction in the simulation is a
   documented `ASSUMPTION` (`SIMULATION_ASSUMPTIONS.md`, NFR-8). Recalibrating them needs plant
   measurements — notably fuel LHV lab results and step-test logs, neither of which any historian tag
   can substitute for.
5. **Retrain and validate.** Models A/B/C are fitted to the simulation. Retrain on plant data through
   the unchanged interfaces, then validate against held-out plant measurements — not against the
   simulation.
6. **Operator validation, then deployment.** PRD §21.4 and §30. Out of scope for this build.

A populated tag mapping makes real data *readable*. It does not make a synthetically-trained model
*correct* on that plant. Steps 3–6 are a project, not a config change.

## What stays true regardless

- The system **writes no setpoint and closes no loop.** Outputs are labelled **AI Recommendation**
  under **Decision Support Only**; "Automatic Control Command" is forbidden vocabulary and is asserted
  against in code (`src/labels.py:29-33`, FR-16, PRD §30).
- Savings are reported as *simulated*: "Simulated saving from a synthetic model - not a guaranteed
  real-world saving" (`src/labels.py:75`).
- Uncertainty is an **ensemble spread** plus a categorical `HIGH`/`MEDIUM`/`LOW` quality. There is no
  confidence-percentage field anywhere in the payload (FR-23, AC-18).
- Where evidence does not separate the readings — sensor drift being the standard case — the display
  reads **"Evidence inconclusive"**, not a diagnosis.
- Operating points outside the training envelope are flagged `OUTSIDE_ENVELOPE`, and
  "No safe recommendation found" is a valid outcome. Constraints are never relaxed to produce advice.

## Documentation

| File | What it covers |
|---|---|
| [`docs/PRD_Synthetic_Cement_Digital_Twin.md`](docs/PRD_Synthetic_Cement_Digital_Twin.md) | The specification (v1.1.1): requirements, acceptance criteria, all engineering sections |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layering, the provider seam, provenance channels, known notes and deliberate non-fixes |
| [`docs/FACTORY_DATA_REQUIREMENTS.md`](docs/FACTORY_DATA_REQUIREMENTS.md) | The tag-level data request a factory would answer (AC-9) |
| [`SIMULATION_ASSUMPTIONS.md`](SIMULATION_ASSUMPTIONS.md) | Every engineering constant, its source, and what measurement would replace it |
| [`MODEL_CARD.md`](MODEL_CARD.md) | Models A/B/C: data, features, metrics, and their validation limits |

---

> **Synthetic Demonstration · Decision Support Only · Not validated against real plant data**
