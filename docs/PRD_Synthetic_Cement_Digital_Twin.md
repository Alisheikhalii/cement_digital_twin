# Synthetic Cement Plant Digital Twin — Demonstration Environment
## Product Requirements Document (PRD) v1.1.1

**System label (must appear on every screen/report/export):**
> "Synthetic Cement Plant Digital Twin — Demonstration Environment. All values are simulation estimates, not real factory measurements."

| Field | Value |
|---|---|
| Document type | Implementation-ready PRD |
| Intended reader | AI coding agent (e.g. Claude Code CLI), ML engineers, process engineers, reviewers |
| Target runtime | Google Colab (primary) + standalone Python project (secondary) |
| Status | v1.1.1 — engineering-hardening revision of v1.0 plus a terminology-consistency patch, **ready for implementation** |
| Data basis | 100% synthetic, process-aware simulation. No real plant data used or claimed. |

### Revision note (v1.1 → v1.1.1, documentation-only)
The only change in this revision is a terminology-consistency fix: the one remaining ambiguously-worded reference to a recommendation-quality display (Section 29, Factory Presentation Mode) has been tightened so it unambiguously points to the categorical **Recommendation Quality (HIGH/MEDIUM/LOW)** defined in Section 13.1.1/14.4, with no numeric "confidence" anywhere in the system unless a documented probabilistic uncertainty method is implemented (still not the case in v1.1.1 — remains a Phase-2 roadmap item, Section 32). No architecture, scope, interface, or requirement was changed.

### Revision note (v1.0 → v1.1)
v1.1 preserves the full architecture, terminology, interfaces, data schema, project structure, UI requirements, demo scenarios and acceptance criteria of v1.0. It adds engineering rigor and safety discipline in 17 areas: unit-consistent fuel energy handling, explicit mass/energy conservation checks, per-relationship time delays (dead time + lag, no more single universal time constant), multi-horizon prediction, a dedicated Synthetic-to-Real Transfer Strategy section, an honest uncertainty/"Recommendation Quality" scheme replacing fabricated confidence percentages, operating-envelope/out-of-distribution protection for the optimizer, a true multi-objective optimizer with hard constraints structurally separated from soft objectives, a broader and fairer baseline comparison, simulation-state-driven (never hard-coded) visualization, expanded conservation/causality/leakage-prevention testing, a "Model Validity Domain" addition to model cards, and corresponding new acceptance criteria. **No scope has been added or removed** — no predictive maintenance, real PLC/OPC-UA/SCADA/historian integration, reinforcement learning, CFD, full chemical kinetics, or 3D visualization is introduced by this revision; all of those remain explicitly future-phase (Section 32).

### How to use this document (note to the coding agent)
Build strictly in the order of Section 23 (Project Structure) and Section 25 (Colab Architecture). Do not invent process values that are not already given here — where a numeric parameter is required and not specified, it is explicitly marked **ASSUMPTION** with a default value and a calibration note; use that default and leave a `# ASSUMPTION:` comment in code at the point of use. Every module boundary described in Sections 8, 9, 10, 13, 14, 15, 19 is a required interface — implement it as specified so that swapping synthetic data for real plant data later (Section 26) requires no redesign.

---

## 1. Executive Summary

This PRD defines a **Synthetic Cement Plant Digital Twin + AI Optimization Platform** — a demonstration-grade prototype that shows a cement manufacturer, concretely and credibly, what becomes possible once they share historical process data. Because no real factory dataset exists yet, the entire system is bootstrapped from a **process-aware synthetic simulation**: a reduced-order dynamic model of a kiln pyroprocessing line and a cement finish-grinding circuit generates physically plausible, temporally correlated, noisy time-series data, built on explicit **mass and energy conservation checks** and **per-relationship transport delays**, not just independent empirical curves. That data drives three machine-learning layers (multi-horizon prediction, anomaly detection, constrained multi-objective optimization) sitting on top of a proper **digital twin** (not an animated picture), all wrapped in an interactive dashboard with What-if simulation and a factory-presentation mode.

The system is explicitly architected as a **hybrid digital twin**: physics-informed reduced-order process models (with enforced conservation) + Monte-Carlo/scenario-driven synthetic simulation + data-driven ML with honest uncertainty handling + envelope-protected constrained optimization. This combination is deliberately chosen because pure data-driven modeling is impossible without real data, while pure first-principles modeling (CFD, detailed kinetics) is unnecessary for a decision-support demonstrator and too slow for interactive Colab use. A dedicated **Synthetic-to-Real Transfer Strategy** (Section 21) makes explicit and unambiguous that strong performance on synthetic data validates the *architecture and methodology*, not real-plant accuracy.

The deliverable is a Colab-runnable, well-structured Python project that a factory engineer can open and understand within minutes (Section 33, Acceptance Criteria), and that is architected from day one so the **only thing that changes when real data arrives is which `DataProvider` implementation is instantiated** (Section 26).

---

## 2. Problem Statement

Cement kiln and grinding operations are energy-intensive, thermally and electrically, and are typically operated by experienced staff using DCS/SCADA trends, lab results, and heuristics rather than closed-loop optimization. Two problems motivate this project:

1. **Sales/credibility problem**: proposing an AI/digital-twin engagement to a cement plant without a working demonstration is abstract and hard to fund. A live, interactive, physically-grounded prototype is far more persuasive than a slide deck — and a prototype that visibly respects energy/mass conservation and never overstates its own confidence is far more persuasive to a process engineer than one that does not.
2. **Data-availability problem**: no real historical plant data is available yet, so any demo must be built on synthetic data that is *believable to a process engineer* — meaning it must show the correct qualitative relationships (fuel↑ → temperature↑ → O₂↓, etc.), correct orders of magnitude (grounded in published cement-industry benchmarks, see Section 9 and 10), realistic dynamics (distinct delays, noise, drift, disturbances, operating regimes), and internally consistent physics (conservation of mass and energy) rather than random or disconnected numbers.

This PRD solves both: a synthetic-but-disciplined simulation stands in for the real historian until the factory grants access, at which point the same ML/optimization/UI stack keeps working unchanged.

---

## 3. Business Objective

- Produce a **demonstration**, not a production control system, that convincingly shows the full pipeline: Synthetic Process Model → Digital Twin Simulation (with enforced conservation and realistic delays) → Synthetic Time-Series → Multi-Horizon ML → Envelope-Protected AI Optimization/Recommendation → Simulation-State-Driven Interactive Visualization → What-if Simulation → Energy Optimization Demonstration.
- Demonstrate credible optimization potential for: fuel consumption, electrical energy consumption, production throughput, process stability, selected quality indicators (Blaine/residue, free-lime proxy), equipment operating conditions, and (new in v1.1) emissions — via a true multi-objective optimizer (Section 14).
- Maintain a clean **Synthetic ↔ Real Data abstraction** (`DataProvider` interface, Section 26) so the architecture is reusable once the factory supplies DCS/SCADA/Historian/PLC/OPC-UA/PI/CSV/SQL exports.
- Explicitly and repeatedly label all outputs as synthetic/simulated (Section 29 "Factory Presentation Mode", Section 21 "Synthetic-to-Real Transfer Strategy", and the system label above) — never implied as real factory savings or real-plant validated accuracy.

---

## 4. User Personas

| Persona | Goal when using the prototype | Key views used |
|---|---|---|
| **AI/ML engineer (builder)** | Extend models, retrain, evaluate metrics, swap data providers | Model Performance, Data Quality, notebooks |
| **Process engineer (factory side)** | Judge whether the process relationships are physically sane, including conservation and delay realism | Kiln Digital Twin, Mill Digital Twin, Time-Series Explorer |
| **Plant manager / decision maker (factory side)** | Understand potential savings in 5 minutes, decide whether to share real data | Factory Presentation Mode, AI Optimization |
| **Factory IT/OT engineer** | Understand what tags/systems will eventually be requested and how | Factory Data Requirements, Data Quality |
| **Sales/solutions engineer (you)** | Run a live, reliable demo without surprises | Demo Scenarios, Factory Presentation Mode |

---

## 5. System Scope

### 5.1 In scope (v1.1)
- **Unit A — Kiln System**: raw meal feed, preheater, precalciner, rotary kiln, burning zone, clinker cooler, fuel system, primary/secondary/tertiary air, ID fan, exhaust gas, gas analyzers — now with explicit energy and mass balance enforcement (Section 9) and per-relationship delays (Section 9.4).
- **Unit B — Cement Grinding System**: a *generic* closed-circuit mill (parameterized so it can represent either a ball mill or a VRM later), separator, main fan, bag filter, product stream — now with explicit mass balance enforcement (Section 10) and per-relationship delays.
- Synthetic data generation for both units with 14 operating regimes (Section 11).
- Three ML layers: multi-horizon prediction with documented uncertainty, anomaly detection, envelope-protected multi-objective optimization/recommendation.
- Interactive 2D/2.5D digital twin visualization driven strictly by live simulation state (Section 19.4), What-if simulator with Normal and Experimental modes (Section 16), time-series explorer, factory presentation mode.
- A dedicated Synthetic-to-Real Transfer Strategy (Section 21) governing how every synthetic result is framed.
- Google Colab notebook + standalone Python package with identical logic.

### 5.2 Out of scope (v1.1, documented as roadmap in Section 32 — unchanged from v1.0, reaffirmed per the "do not expand scope" directive)
- Raw mill / raw meal preparation circuit (placeholder only in the Factory Data Requirements taxonomy, Section 27).
- CFD or detailed chemical-kinetics combustion/clinkerization modeling.
- Closed-loop automatic control of real equipment (Section 30, hard constraint).
- Deep temporal models (LSTM/GRU/TFT) and autoencoder anomaly detection — documented as justified future extensions (Sections 13, 15), not built in v1.1; multi-horizon prediction (new in v1.1) is achieved with classical ML (Section 13.1), not deep learning.
- Multi-plant / multi-line modeling, electrical single-line diagrams, cost/ERP integration.
- Real DCS/SCADA/Historian/OPC-UA connectivity (interfaces are defined, not implemented, in v1.1 — Section 26).
- Predictive maintenance, reinforcement learning, 3D visualization — none of these existed in v1.0 and none are introduced in v1.1.

---

## 6. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | System shall generate reproducible synthetic time-series for Kiln and Mill units from a seeded simulation. | Must |
| FR-2 | Synthetic data shall encode physical relationships, distinct per-relationship process delays, noise, drift, and disturbances — not independent random columns and not a single universal lag. | Must |
| FR-3 | Synthetic data shall include all 14 operating regimes (Section 11) with ground-truth regime labels. | Must |
| FR-4 | System shall export raw/processed datasets to CSV and Parquet. | Must |
| FR-5 | System shall train and persist Model A (process prediction) for at least 4 kiln targets and 3 mill targets, **at each of the configured prediction horizons (default 5/10/15/30 min)**. | Must |
| FR-6 | System shall train and persist Model B (anomaly detection) using Isolation Forest + statistical process control (SPC) limits. | Must |
| FR-7 | System shall provide Model C (optimization) that proposes a constrained, **envelope-validated, multi-objective** setpoint recommendation with expected impact and a plain-language reason. | Must |
| FR-8 | System shall provide a What-if simulator: user adjusts ≤6 manipulated variables within ±10% (Normal Mode) or beyond, with explicit labeling, in Experimental Mode; sees forecast consequences — **including realistic delay before the new steady state appears** — within seconds. | Must |
| FR-9 | System shall provide an interactive animated digital twin visualization (material/gas/fuel/air flow, equipment state) for both units, **with every animated parameter driven directly by the live simulation state object** (Section 19.4) — no prerecorded or hard-coded animation. | Must |
| FR-10 | System shall provide a demonstration "Inject abnormal condition" control that triggers a labeled fault scenario and shows detection + hypothesis + suggested action. | Must |
| FR-11 | System shall compute and display a **Current Operating Point / Historical Baseline / Best Comparable Historical Condition / Digital Twin Baseline vs AI-Optimized Operating Point** comparison on identical process conditions. | Must |
| FR-12 | System shall provide a Factory Presentation Mode with KPI cards and simplified flow, labeled as synthetic, and linked to the Synthetic-to-Real Transfer Strategy disclaimer (Section 21). | Must |
| FR-13 | System shall provide a Data Quality report (missing values, duplicates, constant sensors, spikes, drift, sync issues). | Must |
| FR-14 | System shall expose a `DataProvider` abstraction with `SyntheticDataProvider` implemented and `RealPlantDataProvider` stubbed. | Must |
| FR-15 | System shall log every experiment (scenario, inputs, predictions per horizon, recommendation, impact, constraints, envelope status, model version) to a reproducible experiment record. | Must |
| FR-16 | System shall never issue an "automatic control command" — every AI output is labeled "AI Recommendation" only. | Must |
| FR-17 | System shall run end-to-end inside a single Google Colab notebook, section by section, on a standard (CPU-only) runtime. | Must |
| FR-18 | System shall generate a Factory Data Requirements document (tag-level) auto-derived from the same schema used for synthetic tags. | Must |
| FR-19 | System shall provide explainability for every AI recommendation (feature importance and/or sensitivity, scenario comparison, and — new in v1.1 — the specific hard constraints and envelope checks that passed/failed). | Should |
| FR-20 | System shall support configurable sampling-interval resampling (1s…5min) to mirror real historian constraints. | Should |
| FR-21 | System shall enforce simplified mass and energy conservation in the Kiln and Mill process models, with configurable loss/recovery parameters and automated balance tests. | Must |
| FR-22 | System shall reject or flag (per mode) any recommendation whose manipulated variables fall outside the calibrated operating envelope of the underlying models. | Must |
| FR-23 | System shall never display a numeric "confidence percentage" without a defined, documented uncertainty methodology; absent such a methodology it shall display a categorical Recommendation Quality (HIGH/MEDIUM/LOW). | Must |
| FR-24 | System shall use a single canonical energy unit (MJ) internally for all fuel-energy calculations, with explicit, tested, documented conversions to any display unit (e.g. kcal/kg). | Must |

---

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Runs on a standard Google Colab CPU runtime (no GPU dependency); GPU optional/unused in v1.1. |
| NFR-2 | A single what-if scenario simulate+predict+optimize round trip completes in **< 3 seconds** on Colab CPU (drives all sizing decisions in Sections 9–11, 14). |
| NFR-3 | Full dataset generation (kiln: 6 months at 1-minute resolution ≈ 260k rows; mill: same horizon) completes in **< 5 minutes** on Colab CPU. |
| NFR-4 | All randomness is seeded; identical config + seed ⇒ byte-identical dataset (reproducibility). |
| NFR-5 | Dependency list stays inside the "mature, Colab-preinstalled or one-line-pip-installable" set defined in Section 24 — no Docker/Kubernetes/external DB/cloud services required for v1.1; uncertainty estimation (Section 13.1.1) and multi-objective optimization (Section 14) must be achieved with the existing scikit-learn/scipy stack, no new heavy dependency. |
| NFR-6 | Every numeric UI value must be traceable to a specific model/simulation output — no hard-coded display values (Section 33, tested in Section 34). This explicitly includes every parameter of the digital-twin animation (Section 19.4). |
| NFR-7 | Code is organized so that `src/` is importable both from the notebook and from a future standalone app (no notebook-only logic). |
| NFR-8 | All engineering constants sourced from public literature or reasoned defaults are tagged `ASSUMPTION` in code and documented in `SIMULATION_ASSUMPTIONS.md`, **including every delay parameter (dead time + lag) and every energy/mass-balance loss/recovery fraction.** |
| NFR-9 | UI/dashboard must render inside a Colab output cell without external tunneling services required for the core demo path (Section 24 justifies the chosen stack). |
| NFR-10 | Energy-balance and mass-balance residuals must stay within a configurable tolerance (default ±3%, ASSUMPTION) across the full simulated horizon, verified automatically (Section 34). |
| NFR-11 | Every optimization decision variable must have a documented valid range, step size, hard constraint (if any), and rationale (verified in the Section 35 final review checklist). |

**NFR-10 implementation note — the three residual-validation regimes.** The requirement above is
unchanged: the configurable tolerance (default ±3 %, ASSUMPTION) still holds across the full
simulated horizon. What the implementation makes explicit is *which statistic* that tolerance is
read with, because a pointwise percentage of the **instantaneous** energy input is not a well-defined
quantity on every row of a Section 11.3/11.4 schedule. Two regimes of the schedule break it, neither
because a balance fails to close: Section 11.4's startup ramp drives the input basis down to a
fraction of the operating point while the accounted outputs are still sized for the operating point
being left, and after any setpoint move the Section 9.4 delay that carries the closure redistributes
energy in *time*. The energy residual is therefore validated in three regimes, classified by cause
(the scheduler's own labels and inputs) and never by outcome:

| Regime | Governing statistic | Bound |
|---|---|---|
| Settled / normal operation | peak \|residual\| ÷ instantaneous energy input | the unchanged configurable tolerance (±3 %) |
| Transient / setpoint change (within `dead_time + 4τ` of the closure relationship) | ∫\|unaccounted\| ÷ ∫input, in aggregate and per episode; the peak bounded separately | the same unchanged tolerance on the integral; `transient_peak_max_fraction` on the peak |
| Startup / near-zero input basis | peak \|unaccounted\| ÷ the **reference** operating point's input basis (fixed, non-zero) | `startup_reference_max_fraction` |
| Whole horizon, nothing excluded | ∫\|unaccounted\| ÷ ∫input over every exported row | the same unchanged tolerance |

Mass conservation is unaffected — Section 9.3/10.2's mass balances are exact discretizations and keep
their single metric on every row, startup included. No physical coefficient, delay or loss fraction
was changed: the methodology's own numbers live in
`configs/kiln_dynamics.yaml → energy_balance.residual_validation`, are tagged ASSUMPTION per NFR-8,
and enter no equation. Implementation: `src/data_generation/conservation.py`; measured values,
reasoning and the superseded earlier wording: `SIMULATION_ASSUMPTIONS.md` §11.5; tests:
`tests/test_conservation_validation.py` and `tests/test_data_generator.py`.

---

## 8. Digital Twin Architecture

### 8.1 Why "Hybrid Digital Twin"
Three digital-twin paradigms exist:

- **Physics-based twin** — first-principles equations (mass/energy balances, CFD, kinetics). High fidelity, but requires calibration data and expertise the project doesn't have yet, and is too slow for interactive Colab what-if loops.
- **Data-driven twin** — purely learned from historical plant data. Impossible today: **no real data exists.**
- **Hybrid twin (chosen)** — a *reduced-order* physics-informed process model (steady-state gain + explicit dead-time/first-order-lag structure + enforced mass/energy conservation, Sections 9–10) generates a physically consistent synthetic dataset; ML models are then trained on top of that dataset exactly as they would be on real historian data. This is the only paradigm that (a) works with zero real data today, (b) produces data an ML pipeline can meaningfully learn from, (c) is a drop-in-compatible foundation for real data tomorrow, and (d) is disciplined enough (conservation-checked, delay-realistic) that a process engineer will trust the qualitative behavior even before real calibration.

### 8.2 Layered design (mandatory — do not collapse layers)

```
Layer 1 — Process Representation (topology, static)
Layer 2 — Dynamic Process Model (physics-informed state evolution, conservation-checked, per-relationship delays)
Layer 3 — AI Intelligence (multi-horizon prediction / anomaly / envelope-protected multi-objective optimization, trained on Layer 2's output)
```

A model is **not** a digital twin unless Layers 1 and 2 exist and Layer 3 sits on top of them. A bare ML predictor is a "Model", not a "Twin" — keep this vocabulary consistent everywhere in code, docs and UI.

### 8.3 Component hierarchy

```
PlantTwin
├── KilnTwin
│   ├── PreheaterModel
│   ├── PrecalcinerModel
│   ├── RotaryKilnModel        (burning zone core; owns the kiln energy & mass balance closure, Section 9.2)
│   ├── CoolerModel
│   └── FanFuelModel           (ID fan, primary/secondary/tertiary air, fuel system; owns FuelProperties, Section 9.2)
└── CementMillTwin
    ├── MillModel               (owns the mill mass balance closure, Section 10.2)
    ├── SeparatorModel
    ├── FanFilterModel
    └── ProductModel
```

`KilnTwin` and `CementMillTwin` are simulated with **independent, buffered clinker supply** in v1.1 (**ASSUMPTION**: real plants buffer clinker through a storage silo, decoupling kiln and mill dynamics on the minute-to-hour timescale relevant here). Tight kiln→mill coupling is listed as a Phase-2 roadmap item (Section 32).

### 8.4 Required interface (every component implements this)

```python
class ProcessUnit(Protocol):
    state: dict[str, float]          # current internal state variables
    inputs: dict[str, float]         # current manipulated/disturbance inputs
    outputs: dict[str, float]        # current measured/derived outputs
    constraints: dict[str, tuple]    # {var_name: (min, max)} — hard constraints, Section 14.2
    health: dict[str, float]         # equipment health/wear indicators (0-1)
    balance_residuals: dict[str, float]   # {"energy_pct": .., "mass_pct": ..} — conservation closure, Section 9.2/10.2

    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        """Advance state by dt_seconds given new inputs (routed through each relationship's
        configured DelayedResponse — Section 9.4); return updated outputs."""
```

`KilnTwin`/`CementMillTwin`/`PlantTwin` all compose sub-units and expose the same `simulation_step()` contract plus:

```python
class Twin(ProcessUnit):
    def simulate_scenario(self, input_trajectory: pd.DataFrame, dt_seconds: float) -> pd.DataFrame:
        """Roll the twin forward over a trajectory of inputs; used by What-if and Optimization."""

    def to_steady_state(self, inputs: dict[str, float], max_minutes: int = 120) -> dict[str, float]:
        """Run until |d(state)/dt| < tolerance or max_minutes elapsed; used by Optimization candidate evaluation."""

    def current_state_snapshot(self) -> dict:
        """Single source of truth read by numeric panels AND the visualization renderer (Section 19.4)."""
```

This interface is what makes What-if (Section 16), Optimization (Section 14), and the visualization layer (Section 19.4) all thin callers of the *same* simulation core — never duplicate physics logic, delay logic, or state anywhere else.

### 8.5 Single source of truth (new in v1.1, mandatory)

```
Simulation State (Twin.current_state_snapshot())
        │
        ├──▶ Numerical Outputs (dashboard panels, Section 18)
        ├──▶ AI Layer (Model A/B/C consume the same state, Sections 13-15)
        └──▶ Visualization (Section 19.4 animation parameters)
```
No component is permitted to maintain a second, independent copy of plant state. This single-source-of-truth requirement is what guarantees the animation, the numbers, and the AI recommendations can never silently disagree.

---

## 9. Kiln Model

### 9.1 Manipulated / disturbance inputs

`kiln_feed_rate_tph`, `kiln_fuel_rate_tph`, `calciner_fuel_rate_tph`, `kiln_speed_rpm`, `ID_fan_speed_pct`, `raw_meal_moisture_pct` (disturbance), `raw_meal_temperature_C` (disturbance).

### 9.2 Canonical fuel-energy units (corrected in v1.1)

All internal thermal-energy computation uses **megajoules (MJ)** as the single canonical energy unit, and power as **MJ/min** (converted to MW only for display if needed). Mass-based and volume-based fuel heating values are never mixed without going through a single, documented `FuelProperties` object:

```python
@dataclass
class FuelProperties:
    lhv_solid_fuel_MJ_per_kg: float = 26.0     # ASSUMPTION — coal/petcoke blend
        # derivation shown for auditability: 6200 kcal/kg * 4.184e-3 MJ/kcal = 25.94 ≈ 26.0 MJ/kg
        # published range for coal/petcoke blends: 24-28 MJ/kg (≈5800-6700 kcal/kg)
    lhv_gas_fuel_MJ_per_Nm3: float = 36.0      # ASSUMPTION — natural gas (optional future fuel), volumetric
        # derivation shown for auditability: 8600 kcal/Nm3 * 4.184e-3 MJ/kcal = 35.98 ≈ 36.0 MJ/Nm3
        # published range for pipeline natural gas: 34-38 MJ/Nm3 (≈8100-9100 kcal/Nm3)

def mj_to_kcal(x_MJ: float) -> float:
    """The ONLY sanctioned conversion path from canonical MJ to the display unit kcal.
    1 kcal = 4.184e-3 MJ  =>  kcal = MJ / 4.184e-3"""
    return x_MJ / 4.184e-3
```
`kiln_fuel_rate_tph`/`calciner_fuel_rate_tph` are mass flows (solid/liquid fuel path, `lhv_solid_fuel_MJ_per_kg`); if/when a gas-fuel stream is modeled, it uses a separate `Nm3/h` flow tag and `lhv_gas_fuel_MJ_per_Nm3` — **the two are never added together in native units**, only after each is converted to MJ/h. Both LHV values are configurable in `configs/kiln_dynamics.yaml`, explicitly marked `ASSUMPTION`, documented in `SIMULATION_ASSUMPTIONS.md`, and covered by a dedicated unit-consistency test (Section 34): `test_fuel_energy_unit_consistency()` — verifies `fuel_flow × LHV` produces a physically consistent thermal power/energy figure and that no code path adds a mass-based and volume-based term without conversion.

```
thermal_input_MJ_per_h = kiln_fuel_rate_tph * 1000 * fuel.lhv_solid_fuel_MJ_per_kg
                        + calciner_fuel_rate_tph * 1000 * fuel.lhv_solid_fuel_MJ_per_kg
                        # (+ gas-fuel term via lhv_gas_fuel_MJ_per_Nm3 if/when a gas stream is configured)
```
The **display** tag `thermal_energy_kcal_per_kg_clinker` (Section 12.1) is computed as `mj_to_kcal(thermal_input_MJ_per_h) / (clinker_production_tph * 1000)` — a single documented conversion at the point of display, never re-derived elsewhere.

### 9.3 Simplified energy and mass balance (new in v1.1, enforced in code, not documentation-only)

**Energy balance** (all terms in MJ/h; enforced inside `RotaryKilnModel.simulation_step()` as an explicit closure calculation, not merely described):

```
Fuel_Energy_Input_MJ_per_h + Recovered_Cooler_Heat_MJ_per_h
    = Useful_Process_Heat_MJ_per_h
    + Exhaust_Gas_Loss_MJ_per_h
    + Radiation_Other_Loss_MJ_per_h
    + Unaccounted_Loss_MJ_per_h

Recovered_Cooler_Heat_MJ_per_h   = cooler_heat_recovery_fraction * Cooler_Available_Heat_MJ_per_h
Radiation_Other_Loss_MJ_per_h    = radiation_other_loss_fraction * Fuel_Energy_Input_MJ_per_h
Exhaust_Gas_Loss_MJ_per_h        = f(exhaust_gas_flow, preheater_outlet_temperature)   # reduced-order, from Section 9.4 relations
Useful_Process_Heat_MJ_per_h     = clinker_production_tph * 1000 * theoretical_clinker_formation_MJ_per_kg
                                    + sensible_heating_of_raw_meal_MJ_per_h   # lumped reduced-order term
Unaccounted_Loss_MJ_per_h        = residual = LHS - (Useful + Exhaust_Loss + Radiation_Loss)
```
`cooler_heat_recovery_fraction` (ASSUMPTION 0.75), `radiation_other_loss_fraction` (ASSUMPTION 0.06 of fuel input), and `unaccounted_loss_max_fraction` (ASSUMPTION 0.03, a **test tolerance bound**, not a free-fit parameter) live in `configs/kiln_dynamics.yaml` under `energy_balance:`. The model's reduced-order gains (Section 9.4) are parameterized so the closure holds at the nominal/reference operating point by construction; during dynamic transients the `Unaccounted_Loss` term is tracked and asserted to stay within `unaccounted_loss_max_fraction` by `test_kiln_energy_balance()` (Section 34).

**Mass balance** (all terms in t/h), tied directly to a physically motivated kiln-inventory state variable that replaces the old free-standing `tau_production` constant:

```
Kiln_Feed_Rate_tph = Clinker_Production_tph + LOI_Loss_tph + Dust_Loss_tph + d(Kiln_Inventory_tph)/dt

d(Kiln_Inventory)/dt = Kiln_Feed_Rate_tph - Calcination_Loss_Rate_tph - Clinker_Discharge_Rate_tph
Clinker_Discharge_Rate_tph = Kiln_Inventory_tph / kiln_residence_time_h    # first-order discharge, physically motivated lag

clinker_factor = 1 - LOI_loss_fraction - dust_loss_fraction
    # clinker_factor = 0.63 (ASSUMPTION, unchanged from v1.0) with dust_loss_fraction = 0.01 (ASSUMPTION)
    # implies LOI_loss_fraction ≈ 0.36 — consistent with typical raw-meal LOI of 35-36% (CO2 + H2O driven off in calcination)
```
`dust_loss_fraction` (ASSUMPTION 0.01) and `kiln_residence_time_min` (ASSUMPTION 35 min, replacing the old blanket `tau_production`) live under `mass_balance:` in `configs/kiln_dynamics.yaml`. `test_kiln_mass_balance()` (Section 34) asserts the balance closes within tolerance across a representative simulated horizon.

### 9.4 Reduced-order relationships with explicit, per-relationship delays (revised in v1.1)

Every derived variable still follows the same steady-state-gain-then-dynamic-response structure as v1.0 (`y_target = f(inputs)`), but the dynamic response is now an explicit `DelayedResponse(dead_time, tau)` — **pure transport dead time followed by a first-order lag** — configured **per causal relationship**, not one universal time constant:

```python
class DelayedResponse:
    """y(t) tracks y_target with a pure transport delay (dead_time_s) then a first-order lag (tau_s)."""
    def __init__(self, dead_time_s: float, tau_s: float): ...
    def step(self, y_target: float, dt_s: float) -> float: ...
```

| Causal relationship | Dead time (ASSUMPTION) | First-order lag τ (ASSUMPTION) | Basis |
|---|---|---|---|
| Fuel → Burning Zone Temperature | 2 min | 25 min | thermal-mass-dominated response (refractory + material bed) |
| Fuel → O2 | 0.5 min | 4 min | fast gas-phase combustion response |
| Feed → Production | 5 min | 8 min | now derived from the kiln-inventory buffer (Section 9.3), not a free parameter |
| Feed → Burning Zone Temperature | 8 min | 20 min | feed must traverse preheater + kiln before affecting flame region (dilution effect) |
| ID Fan → O2 | 0.2 min | 3 min | near-instant draught response |
| ID Fan → Kiln/Preheater Pressure | 0.1 min | 1 min | fastest-responding variable in the system |
| Calciner Fuel → Calciner Temperature | 1 min | 10 min | calciner thermal mass smaller than kiln |
| NOx response to BZT | 1 min | 15 min | thermal-NOx formation lags peak temperature |

All values configurable per relationship in `configs/kiln_dynamics.yaml` under `delays:`; all marked `ASSUMPTION`, to be calibrated from real plant step-test data once available (Section 21). The underlying steady-state gain equations (BZT, O2, CO, NOx, SO2, exhaust flow/pressure, secondary air, cooler outlet — unchanged in functional form from v1.0) are documented in full in `SIMULATION_ASSUMPTIONS.md`; each `y_target = f(inputs)` expression now explicitly routes through its own `DelayedResponse` instead of a shared `tau_y`.

The causal chains this model must reproduce (unchanged from v1.0, now with distinct delays applied to each leg):
- fuel↑ → thermal input↑ → BZT↑ (2 min dead time / 25 min lag) → O2↓ (0.5 min / 4 min) → SFC↑
- ID fan↑ → gas flow↑ → O2↑ (0.2 min / 3 min) → preheater pressure↓ (0.1 min / 1 min) → temperature↓
- kiln feed↑ → production↑ (via the inventory buffer, Section 9.3) → thermal load↑ → fuel demand↑

### 9.5 Equipment/health variables
`kiln_motor_current`, `ID_fan_current`, `cooler_fan_power`, `vibration`, `bearing_temperature` are modeled as noisy functions of load (`kiln_feed_rate_tph`, `ID_fan_speed_pct`) plus a slow degrading `health` scalar (0–1) that very occasionally (Poisson process, configurable rate) dips to simulate a mechanical-fault regime, feeding the anomaly detector's equipment-fault feature set.

---

## 10. Cement Mill Model

### 10.1 Manipulated / disturbance inputs
`mill_feed_rate_tph`, `clinker_feed_rate_tph`, `gypsum_feed_rate_tph`, `additive_feed_rate_tph`, `separator_speed_rpm`, `fan_speed_pct`.

### 10.2 Simplified mass balance (new in v1.1, enforced in code)

```
Mill_Feed_Rate_tph (clinker + gypsum + additive)
    = Cement_Production_tph
    + Reject_Recirculation_tph      # internal to the closed circuit; drives separator/mill load, not a true loss
    + Dust_Bag_Filter_Loss_tph      # ASSUMPTION 0.2-0.5% of feed
    + d(Mill_Inventory_tph)/dt      # near-zero at steady state; the source of realistic response lag under load changes
```
`dust_bag_filter_loss_fraction` (ASSUMPTION 0.003) and the mill-inventory time constant (ASSUMPTION, derived from nominal mill holdup / throughput, replacing the old free-standing mill power/production tau) live under `mass_balance:` in `configs/mill_dynamics.yaml`. `test_mill_mass_balance()` (Section 34) asserts closure within tolerance.

### 10.3 Reduced-order relationships with explicit per-relationship delays (revised in v1.1)

| Causal relationship | Dead time (ASSUMPTION) | First-order lag τ (ASSUMPTION) | Basis |
|---|---|---|---|
| Mill Feed → Mill Power | 0.5 min | 4 min | motor load responds quickly; bed dynamics slightly slower |
| Mill Feed → Mill Differential Pressure | 1 min | 6 min | bed-loading response |
| Separator Speed → Blaine | 3 min | 12 min | recirculating-load / classification-loop transport |
| Separator Speed → Throughput (reject fraction) | 2 min | 8 min | classification-loop transport |
| Fan Speed → Gas Flow | 0.2 min | 2 min | near-instant fan-curve response |

**Mill power** (Bond-work-index-inspired, grounded in published benchmarks: closed-circuit ball-mill finish grinding ≈ 28–42 kWh/t cement; VRM finish grinding ≈ 18–28 kWh/t; overall plant electrical incl. auxiliaries commonly cited at 90–120 kWh/t cement) and the throughput/fineness trade-off equations are otherwise unchanged in functional form from v1.0 (documented fully in `SIMULATION_ASSUMPTIONS.md`), now routed through the per-relationship `DelayedResponse` objects above instead of a single shared `tau`.

### 10.4 Trade-off this model must demonstrate (unchanged from v1.0)
Throughput ↑ (feed↑) tends to push Blaine down (coarser) and reduce specific power consumption per tonne; separator speed↑ raises Blaine (finer) and specific power consumption but lowers net throughput. This throughput/energy/fineness/stability trade-off is exactly the surface the What-if simulator (Section 16) and the multi-objective optimizer (Section 14) explore — now with realistic delay before the new trade-off point is reached.

---

## 11. Synthetic Data Architecture

### 11.1 Design principle
Never sample columns independently. Data is produced by **forward-simulating the Twin** under a **Scenario Schedule** (a time-indexed sequence of manipulated-variable trajectories + regime labels + disturbance events), then passing true state through a **Sensor Model** that adds realistic measurement imperfection. The Twin itself now enforces mass/energy conservation (Sections 9.3, 10.2) and per-relationship delays (Sections 9.4, 10.3), so the resulting correlations, lags, and regime structure are physically disciplined, not just directionally plausible.

### 11.2 Pipeline
```
SimulationConfig (seed, duration, dt, regime schedule)
        │
        ▼
ScenarioScheduler  ──produces──▶  input_trajectory (per-unit, per-minute setpoints + regime label + fault label)
        │
        ▼
Twin.simulate_scenario(input_trajectory, dt)  ──▶  true_state_trajectory (noise-free physical truth;
        │                                           balance_residuals tracked at every step, Section 8.4)
        ▼
SensorModel.apply(true_state_trajectory)  ──▶  measured_trajectory (+ noise, drift, dropout, quantization)
        │
        ▼
raw synthetic dataset  (data/synthetic/kiln_raw.parquet, data/synthetic/mill_raw.parquet)
```

### 11.3 Scenario Scheduler
Generates smooth (ramped, not step-instant) transitions between setpoints using a minimum ramp time (**ASSUMPTION**: 3–15 minutes depending on variable, matching realistic operator/DCS ramp rates), a Poisson-process arrival of disturbance events (feed moisture swings, fuel quality swings, ambient temperature drift), and scheduled dwell-time in each of the 14 operating regimes (Section 11.4) so the resulting dataset contains hours-to-days of each regime — enough for both training and the chronological **and** scenario-based holdout evaluation required in Section 13.3.

### 11.4 Operating regimes (mandatory, with ground-truth label column `operating_regime`)

| # | Regime | How it's induced |
|---|---|---|
| 1 | Normal — low production | feed/fuel near lower nominal band, steady |
| 2 | Normal — medium production | feed/fuel near mid nominal band, steady |
| 3 | Normal — high production | feed/fuel near upper nominal band, steady |
| 4 | High fuel condition | fuel rate pushed above normal band relative to feed |
| 5 | Low oxygen condition | ID fan reduced and/or fuel increased beyond air supply |
| 6 | High oxygen condition | ID fan increased well beyond demand (excess air) |
| 7 | Fan instability | injected oscillation/noise burst on ID fan or mill fan speed |
| 8 | Feed disturbance | step/ramp disturbance on kiln feed or mill feed independent of setpoint |
| 9 | Temperature disturbance | raw meal temperature/moisture disturbance driving BZT excursion |
| 10 | Mill overload | mill feed pushed above nominal capacity |
| 11 | Mill underload | mill feed pushed well below nominal capacity |
| 12 | High separator speed | separator speed pushed above normal band |
| 13 | Low separator speed | separator speed pushed below normal band |
| 14 | Sensor drift | a slow additive bias ramp injected at the **sensor model** layer only (true process stays normal) — tests whether anomaly detection distinguishes process faults from sensor faults |

A `startup-like transition` regime is additionally modeled as a scripted ramp-up sequence (feed 0→nominal, fuel 0→nominal over ~60–90 minutes, **ASSUMPTION**) used specifically in Demo 1 (Section 28) and excluded from steady-state training windows by default.

### 11.5 Sensor Model
Per tag: additive Gaussian noise (`std` proportional to tag's typical operating range, **ASSUMPTION** ≈1–2% of nominal unless literature suggests otherwise, e.g. gas analyzers noisier at low concentration), configurable measurement lag (sensor/transmitter dynamics, separate from and additional to the process delay of Section 9.4/10.3), quantization to realistic instrument resolution, rare missing-value dropout (**ASSUMPTION** 0.1–0.5% of samples), and — only in the "sensor drift" regime — a slow linear/exponential bias ramp on selected tags.

### 11.6 Reproducibility & export
All randomness via `numpy.random.default_rng(seed)` threaded explicitly (no global RNG state). `SimulationConfig` (including seed) is serialized to `configs/*.yaml` and saved alongside every generated dataset. Export formats: CSV (`data/synthetic/*.csv`) and Parquet (`data/synthetic/*.parquet`), plus a JSON sidecar of the config used.

---

## 12. Data Dictionary

Ranges are **process-reasoned ASSUMPTIONs** for a mid-size precalciner kiln (~3,000–4,000 tpd clinker line) and a generic closed-circuit cement mill, grounded in the equations of Sections 9–10 and public cement-engineering benchmarks. They are starting points for the synthetic generator and the placeholders to be replaced/calibrated once real factory data is available (Section 21/26/27).

### 12.1 Kiln dataset (`kiln_raw.parquet`)

| Tag | Description | Unit | Typical range (ASSUMPTION) | Sampling (native sim) | Type |
|---|---|---|---|---|---|
| timestamp | UTC timestamp | – | – | 1 min | datetime |
| kiln_feed_rate_tph | Raw meal feed to kiln system | t/h | 150–230 | 1 min | float |
| kiln_fuel_rate_tph | Main kiln burner fuel rate (solid/liquid, MJ/kg basis) | t/h | 3.2–5.2 | 1 min | float |
| calciner_fuel_rate_tph | Precalciner fuel rate (solid/liquid, MJ/kg basis) | t/h | 4.0–7.5 | 1 min | float |
| kiln_speed_rpm | Kiln rotation speed | rpm | 2.8–4.5 | 1 min | float |
| raw_meal_moisture | Raw meal residual moisture | % | 0.3–1.0 | 1 min | float |
| raw_meal_temperature | Raw meal feed temperature | °C | 40–90 | 1 min | float |
| primary_air_flow | Primary air flow to main burner | Nm³/h | 15,000–25,000 | 1 min | float |
| secondary_air_flow | Secondary air flow from cooler | Nm³/h | 90,000–140,000 | 1 min | float |
| tertiary_air_flow | Tertiary air flow to calciner | Nm³/h | 60,000–100,000 | 1 min | float |
| ID_fan_speed | ID fan speed | % | 60–95 | 1 min | float |
| ID_fan_power | ID fan motor power | kW | 900–2,200 | 1 min | float |
| kiln_inlet_pressure | Kiln inlet draught pressure | mbar | −8 to −2 | 1 min | float |
| preheater_pressure | Preheater tower pressure | mbar | −25 to −10 | 1 min | float |
| exhaust_gas_flow | Stack/preheater exhaust flow | Nm³/h | 250,000–400,000 | 1 min | float |
| burning_zone_temperature | Burning zone (pyrometer/model) | °C | 1,400–1,500 | 1 min | float |
| kiln_inlet_temperature | Material temp at kiln inlet | °C | 800–950 | 1 min | float |
| calciner_temperature | Precalciner outlet temperature | °C | 850–900 | 1 min | float |
| preheater_outlet_temperature | Top-stage cyclone exit temperature | °C | 280–380 | 1 min | float |
| secondary_air_temperature | Secondary (cooler recuperated) air temp | °C | 800–1,000 | 1 min | float |
| cooler_outlet_temperature | Clinker cooler discharge temperature | °C | 80–150 | 1 min | float |
| oxygen_percent | O2 at kiln inlet/back-end (dry) | % | 0.7–4.0 | 1 min | float |
| CO_ppm | CO at kiln inlet/back-end | ppm | 0–300 (spikes higher under fault) | 1 min | float |
| CO2_percent | CO2 at kiln inlet/back-end | % | 28–36 | 1 min | float |
| NOx_ppm | NOx (converted from mg/Nm3, **ASSUMPTION** conversion factor) | ppm | 250–900 | 1 min | float |
| SO2_ppm | SO2 at stack | ppm | 10–400 (raw-material sulfur dependent) | 1 min | float |
| clinker_production_tph | Clinker output rate | t/h | 95–150 | 1 min | float |
| clinker_temperature | Clinker discharge temperature | °C | 80–150 | 1 min | float |
| thermal_energy_kcal_per_kg_clinker | Specific thermal energy — **display-unit derivation of the canonical MJ energy balance, Section 9.2/9.3** | kcal/kg | 700–950 | 1 min | float |
| specific_fuel_consumption | Duplicate/derived, kept for factory-familiar naming | kcal/kg | 700–950 | 1 min | float |
| ID_fan_current | ID fan motor current | A | 100–260 | 1 min | float |
| kiln_motor_current | Kiln main drive current | A | 80–180 | 1 min | float |
| cooler_fan_power | Cooler fans total power | kW | 400–1,100 | 1 min | float |
| vibration | Kiln drive/support vibration (generic) | mm/s | 1–8 (spikes under fault) | 1 min | float |
| bearing_temperature | Kiln support roller bearing temperature | °C | 45–75 (spikes under fault) | 1 min | float |
| operating_regime | Ground-truth regime label (Section 11.4) | – | categorical | 1 min | string |
| injected_fault | Ground-truth fault flag/type for anomaly evaluation | – | categorical/null | 1 min | string |

A separate **debug-only** dataset variant (not part of the core schema above, generated only when `debug_balance_export: true` in `configs/kiln_dynamics.yaml`) additionally carries `energy_balance_residual_pct` and `mass_balance_residual_pct` per row, used exclusively by the conservation tests (Section 34) and not shown in the standard UI/export.

### 12.2 Cement mill dataset (`mill_raw.parquet`)

| Tag | Description | Unit | Typical range (ASSUMPTION) | Sampling (native sim) | Type |
|---|---|---|---|---|---|
| timestamp | UTC timestamp | – | – | 1 min | datetime |
| mill_feed_rate_tph | Total mill feed | t/h | 80–170 | 1 min | float |
| clinker_feed_rate | Clinker component of feed | t/h | 70–150 | 1 min | float |
| gypsum_feed_rate | Gypsum component of feed | t/h | 3–8 | 1 min | float |
| additive_feed_rate | Additive/limestone component | t/h | 0–20 | 1 min | float |
| mill_motor_power_kw | Main mill motor power | kW | 2,500–5,500 | 1 min | float |
| mill_current | Main motor current | A | 200–420 | 1 min | float |
| mill_pressure | Mill internal pressure (VRM) / shell pressure proxy | mbar | −40 to −10 | 1 min | float |
| mill_differential_pressure | Mill ΔP (loading indicator) | mbar | 20–90 (spikes under overload) | 1 min | float |
| mill_outlet_temperature | Material/gas outlet temperature | °C | 90–120 | 1 min | float |
| mill_vibration | Mill body vibration | mm/s | 1–10 (spikes under fault) | 1 min | float |
| mill_speed | Mill rotational/table speed | rpm | 12–18 (generic circuit) | 1 min | float |
| separator_speed_rpm | Dynamic separator rotor speed | rpm | 60–140 | 1 min | float |
| separator_current | Separator motor current | A | 30–80 | 1 min | float |
| separator_pressure | Separator inlet/outlet pressure | mbar | −15 to −5 | 1 min | float |
| fan_speed | Main/circulation fan speed | % | 60–100 | 1 min | float |
| fan_power_kw | Main fan power | kW | 400–1,200 | 1 min | float |
| gas_flow | Circulating gas flow | Nm³/h | 150,000–260,000 | 1 min | float |
| cement_production_tph | Net finished-product rate | t/h | 75–160 | 1 min | float |
| product_temperature | Finished product temperature | °C | 85–115 | 1 min | float |
| simulated_blaine_cm2_g | Fineness (Blaine surface area) | cm²/g | 2,900–4,200 | 1 min | float |
| residue_percent | 45 µm sieve residue | % | 6–18 | 1 min | float |
| specific_power_consumption_kwh_t | Specific electrical energy | kWh/t | 26–45 | 1 min | float |
| operating_regime | Ground-truth regime label | – | categorical | 1 min | string |
| injected_fault | Ground-truth fault flag/type | – | categorical/null | 1 min | string |

Full column-level documentation (including every equation coefficient, every delay parameter, and every conservation-balance parameter and its calibration note) lives in `DATA_DICTIONARY.md` and `SIMULATION_ASSUMPTIONS.md` (Section 35).

---

## 13. ML Architecture

Three independent, purpose-built models — never one black-box model.

### 13.1 Model A — Multi-Horizon Process Prediction (upgraded in v1.1)

- **Targets (Kiln)**: `burning_zone_temperature`, `oxygen_percent`, `clinker_production_tph`, `thermal_energy_kcal_per_kg_clinker`.
- **Targets (Mill)**: `mill_motor_power_kw`, `simulated_blaine_cm2_g`, `specific_power_consumption_kwh_t`.
- **Horizons (mandatory, configurable in `configs/ml.yaml`)**: default **t+5 min, t+10 min, t+15 min, t+30 min**. A separate model is trained per (target, horizon) pair using horizon-appropriate lagged features — this is the reduced-order, classical-ML alternative to a sequence model, and is explicitly required because process changes (fuel/feed/fan adjustments) propagate through the plant over time (Sections 9.4, 10.3): a setpoint change visible in the 5-minute prediction may still be transiting toward the process at the 30-minute horizon, so the optimizer (Section 14) must be able to consult the predicted state at the horizon relevant to its decision, not only the current instantaneous state.
- **Method**: one `RandomForestRegressor` (baseline, always trained) and one `GradientBoostingRegressor` (scikit-learn) per (target, horizon), selected by held-out MAE; `LightGBM` evaluated as an optional stretch model **only if** it measurably beats both (documented comparison table in `MODEL_CARD.md`) — chosen over `XGBoost` for lighter Colab install footprint and native categorical handling of `operating_regime`.
- **Features**: current + lagged (t-1, t-5, t-15 min) values of the relevant manipulated variables and correlated process variables, plus `operating_regime` one-hot/category, sized appropriately per horizon.
- **Why not deep learning by default**: unchanged rationale from v1.0 — dataset size/feature count are small/tabular, tree ensembles give competitive accuracy, native feature importance (needed for Section 15/14 explainability), fast CPU training/inference in Colab, and determinism. LSTM/GRU/Temporal Fusion Transformer remain a documented future extension (Section 32) for when real multi-line/multi-plant sequence data exists.

#### 13.1.1 Uncertainty / "Recommendation Quality" methodology (new in v1.1)
No numeric confidence percentage is displayed anywhere in the system unless backed by a defined method (Section 14.4, FR-23). v1.1's documented method, using only the existing scikit-learn stack (no new dependency, NFR-5):
- `RandomForestRegressor` provides a built-in, low-cost uncertainty proxy: the **spread across individual trees'** predictions for a given input is used as an ensemble-uncertainty estimate.
- For `GradientBoostingRegressor` (which has no built-in per-sample variance), an explicit **bootstrap ensemble** of `N=20` (ASSUMPTION, configurable) models trained on bootstrap-resampled training sets is used; the spread of their predictions is the uncertainty estimate.
- The resulting uncertainty width, together with distance-from-training-distribution (Section 14.3), constraint margin (Section 14.2), and RF/GBM model agreement, is mapped to the categorical **Recommendation Quality: HIGH / MEDIUM / LOW** used everywhere in the UI (Section 14.4, 17, 18) — never a fabricated percentage.
- Full conformal-prediction or calibrated-interval methods are documented as a Phase-2 roadmap item (Section 32) once real data volume justifies them.

### 13.2 Model B — Anomaly Detection
- **Method 1 (primary)**: `IsolationForest` (scikit-learn) trained on normal-regime windows, scored on all data; because the simulator provides ground-truth `operating_regime`/`injected_fault` labels, this is evaluated with real precision/recall/F1 (Section 22) — a rare advantage of the synthetic-data approach.
- **Method 2 (secondary, always-on interpretable layer)**: per-tag statistical process control — rolling mean/EWMA + control limits (e.g. ±3σ), used for the "which variable is out of band" explanation shown alongside the Isolation Forest's overall anomaly score.
- Detects: abnormal fuel conditions, O2 anomalies, temperature anomalies, fan problems, mill instability, sensor drift (regimes 4–14, Section 11.4).
- **Dual role (new in v1.1)**: the same Isolation Forest score also underlies the **operating-envelope / out-of-distribution validation** consumed by the optimizer (Section 14.3) — a single anomaly-scoring component serves both the anomaly-detection UI and the optimizer's safety gating, avoiding duplicated logic.
- Autoencoder-based detection remains a documented optional Phase-2 extension (Section 32).

### 13.3 Leakage Prevention & Evaluation Splits (new in v1.1, formalizes and extends v1.0 Section 20)
Highly autocorrelated time-series data must never be randomly row-split into train/test — this would leak near-identical adjacent samples across the split and produce misleadingly optimistic metrics. The dataset supports, and every model evaluation must report, **both**:
1. **Chronological split** — train on the first ~70% of the simulated timeline, test on the final ~30% (as in v1.0).
2. **Scenario-based holdout** — at least one entire labeled regime or disturbance episode (Section 11.4) is withheld from training entirely (e.g. all "fan instability" episodes) and evaluated separately, to test whether the model generalizes to operating conditions it has never seen, not just to later timestamps of conditions it has seen.

Both result sets are recorded in `MODEL_CARD.md` (Section 13.4/35) so that "the model performs well" is never based on the easier, leakage-prone split alone.

### 13.4 Model registry & experiment tracking
`joblib`-serialized models saved to `models/{kiln,mill}/{model_name}_{target}_{horizon}_{version}.joblib` with a `models/registry.json` recording: timestamp, dataset hash, feature list, hyperparameters, metrics (both split types, Section 13.3), **training data range and operating regimes represented (feeding the Model Validity Domain in `MODEL_CARD.md`, Section 35)**, and simulation config version. Every prediction/recommendation displayed in the UI carries its source model version (Section 15/27, experiment tracking requirement).

---

## 14. Optimization Architecture

### 14.1 Safe, envelope-protected recommendation flow (revised in v1.1)
```
Current State → Digital Twin → Candidate Actions → Simulate Each Action (Twin.to_steady_state)
             → Operating-Envelope / OOD Validation (Section 14.3)
             → Hard-Constraint Evaluation (Section 14.2, structurally separate from objective)
             → Multi-Objective Optimization over surviving candidates (Section 14.2)
             → Recommended Action
```
The optimizer **never** touches real equipment — it only ever produces a `Recommendation` object (Section 14.4).

### 14.2 Multi-objective soft objective, with hard constraints structurally separate (revised in v1.1)

Hard constraints are evaluated **first**, as a pass/fail filter on the candidate set — they are never expressed as penalty terms inside the objective, so they can never be "traded away" for a better objective score:

| Hard constraint | Bound (ASSUMPTION) | Rationale |
|---|---|---|
| `clinker_production_tph` | ≥ production_target × (1 − tol), tol = 1% | production commitment |
| `burning_zone_temperature` | [1420, 1480] °C | clinker quality / refractory safety |
| `oxygen_percent` | [1.0, 3.5] % | combustion safety / fuel efficiency |
| `CO_ppm` | ≤ 200 ppm | combustion completeness / safety |
| `simulated_blaine_cm2_g` | [blaine_target − tol, blaine_target + tol] | product-quality spec |
| `residue_percent` | ≤ residue_max | product-quality spec |
| `mill_differential_pressure`, fan power, motor currents | ≤ rated equipment limits | equipment protection |
| Δ setpoint per manipulated variable | ≤ 10% of current value (Normal Mode only) | operating-envelope discipline, matches What-if bounds (Section 16) |

Only candidates that pass **every** hard constraint and the envelope/OOD validation (Section 14.3) are scored by the soft, weighted multi-objective function:

```
Objective =  w_thermal    * ΔThermal_Energy
           + w_electric   * ΔElectrical_Energy
           + w_production * Production_Penalty
           + w_quality    * Quality_Penalty
           + w_stability  * Stability_Penalty
           + w_emission   * Emission_Penalty
```
All weights default per `configs/optimization.yaml` (**ASSUMPTION**, reflecting a documented typical fuel-vs-electricity-vs-quality priority balance) and are exposed as a UI control in advanced mode; `Production_Penalty`/`Quality_Penalty`/`Stability_Penalty`/`Emission_Penalty` are zero within their respective hard-constraint band and rise smoothly only as a candidate approaches (but does not cross) that band, so the optimizer is naturally discouraged from hugging the edges of a hard limit even though it can never cross it.

### 14.3 Operating-Envelope & Out-of-Distribution Protection (new in v1.1, mandatory)

Before any candidate reaches the objective-scoring step, five checks run in order; failing **any** of them removes the candidate from consideration in Normal Mode:

1. **Operating-range validation** — every proposed manipulated variable must lie within the min/max range actually represented in the training data for the currently active model (recorded per model in `models/registry.json`, Section 13.4). E.g. if `kiln_fuel_rate_tph` was trained on 3.8–4.3 t/h, a candidate of 3.0 t/h fails here — regardless of what the model predicts.
2. **Feature-space / distribution validation and OOD detection** — Model B's Isolation Forest (Section 13.2) scores the full proposed feature vector; a score beyond the configured anomaly threshold fails this check.
3. **Constraint validation** — the Section 14.2 hard-constraint table.
4. **Maximum-change validation** — |Δ setpoint| ≤ 10% of current value per manipulated variable (Normal Mode).
5. Candidates that survive 1–4 proceed to multi-objective scoring (Section 14.2).

A candidate that fails any check is marked `constraint_status = "REJECTED"`; a candidate that is borderline (e.g. just inside the training range but with elevated Isolation Forest score) may be marked `"FLAGGED_FOR_REVIEW"` rather than rejected outright, at the implementer's documented discretion, but is never silently promoted to a full recommendation.

- **Normal Optimization Mode** strictly enforces `Recommended Action ∈ Valid Operating Envelope` — this is the default and only mode for the AI Optimization view (Section 17/18).
- **Experimental What-if Mode** (Section 16, user-initiated only) may explore beyond the ±10% bound or outside the training envelope for exploratory purposes, but every such result carries the fixed, non-removable banner: **"Outside calibrated operating envelope — low reliability."**

### 14.4 Recommendation object (revised in v1.1 — no fabricated confidence)
```python
@dataclass
class Recommendation:
    baseline_state: dict[str, float]
    proposed_state: dict[str, float]
    predicted_state_by_horizon: dict[str, dict[str, float]]   # {"t+5min": {...}, "t+10min": {...}, ...}
    expected_impact: dict[str, float]     # e.g. fuel_saving_pct, thermal_energy_change_pct, production_change_pct,
                                           # O2_change_pct, emission_change_pct
    objective_breakdown: dict[str, float] # per-term contribution (thermal/electric/production/quality/stability/emission)
    recommendation_quality: Literal["HIGH", "MEDIUM", "LOW"]   # from Section 13.1.1 — NOT a numeric percentage
    mode: Literal["NORMAL", "EXPERIMENTAL"]
    envelope_status: Literal["WITHIN_ENVELOPE", "OUTSIDE_ENVELOPE"]
    constraint_status: Literal["PASS", "REJECTED", "FLAGGED_FOR_REVIEW"]
    reason: str                            # natural-language explanation, Section 15/17
    model_version: str
    timestamp: datetime
```

### 14.5 Baseline comparison (broadened in v1.1)
Every optimization demonstration reports, on **identical process conditions and comparable production requirements**:

1. **Current Operating Point** — the live/most-recent simulated state.
2. **Historical Baseline** — the average state over a recent representative simulated window (e.g. trailing 24h) at the same regime.
3. **Best Comparable Historical Condition** — the best-observed simulated window matching the same production target and regime (a legitimate, non-artificial comparator, avoiding the "compare against a deliberately poor baseline" failure mode).
4. **Digital Twin Baseline** — the Section 14.6 rule-engine's recommended state for the same starting condition (i.e., "what a simple rule-based operator heuristic would do").
5. **AI-Optimized Operating Point** — the Section 14.2–14.4 optimizer's output.

All five are reported with the same metric set — energy, production, quality, stability, constraints — so the AI's advantage (if any) is shown transparently against a fair, not a strawman, comparator.

### 14.6 Rule engine (baseline strategy — explicit, documented, distinct from AI, unchanged from v1.0)
A small, fully transparent rule set (e.g. "if `oxygen_percent` < 1.0% and `CO_ppm` rising, flag fuel/air imbalance"; "if `mill_differential_pressure` > threshold, flag overload") implements the constraint/safety layer and doubles as the **Digital Twin Baseline** comparator in Section 14.5. This is the *only* place if/else rule logic is allowed to stand in for a recommendation; the AI-assisted strategy always comes from prediction + simulation + optimization as defined above.

---

## 15. Anomaly Detection
(Method detailed in 13.2.) UI/output contract for a detected or injected anomaly:

```
WARNING
Detected anomaly: <regime name, e.g. "Low Oxygen Condition">
Likely cause (model-based hypothesis): <from SPC-tag attribution + nearest matching regime>
Affected variables: <ranked list from SPC z-scores / Isolation Forest feature contribution>
Suggested action: <from the Section 14.6 rule engine, explicitly labeled as a rule-based suggestion, not a diagnosis>
```
Causal language is avoided; outputs are phrased as **"model-based hypothesis"**, never definitive diagnosis, since ground truth causality is only knowable inside the simulator, not in a real, unvalidated deployment. As noted in Section 13.2, the same anomaly-scoring component also underlies the optimizer's out-of-distribution gate (Section 14.3) — one implementation, two consumers.

---

## 16. What-if Simulation

### 16.1 Manipulated variables, bounds, and mode (revised in v1.1)
`kiln_fuel_rate_tph`, `ID_fan_speed`, `kiln_feed_rate_tph`, `kiln_speed_rpm`, `separator_speed_rpm`, `mill_feed_rate_tph`.

- **Normal What-if Mode** (default): each variable adjustable within **±10%** of current value, and every resulting scenario is passed through the full Section 14.3 envelope/OOD validation before results are shown — a what-if request that would move a variable outside the calibrated range is rejected with an explanation, exactly as the optimizer would reject it.
- **Experimental What-if Mode** (explicit user toggle): allows deltas beyond ±10% and/or outside the calibrated training envelope, for exploratory "what would happen if we went further" questions. Every result in this mode carries the fixed banner **"Outside calibrated operating envelope — low reliability."** and is visually distinguished (e.g. different panel color) from Normal Mode results.

### 16.2 Flow (revised in v1.1 — explicit delayed response)
```
User sets Δ on 1..N variables, selects Normal or Experimental mode
   → build input_trajectory (ramped, matching Scenario Scheduler ramp logic)
   → [Normal Mode only] Operating-Envelope / OOD Validation (Section 14.3)
   → Twin.simulate_scenario(input_trajectory, dt)   # same call optimization uses (Section 8.4),
        routed through each relationship's configured DelayedResponse (Section 9.4/10.3)
   → compare final steady-state vs baseline
   → render: temperature, O2, production, energy consumption, quality indicator, constraint violations,
        estimated savings, and the full transition trajectory showing the actual dead-time + lag —
        NOT an instantaneous jump to the new value
```
Because What-if reuses `Twin.simulate_scenario`/`to_steady_state` exactly as the optimizer does, and both pass through the same envelope validation in Normal Mode, results are guaranteed consistent between "AI Recommendation" and "manual what-if" — this consistency is itself a testable acceptance criterion (Section 33).

### 16.3 Output panel contract
A before/after table (baseline vs scenario) + a time-series chart of the transition **that visibly shows the delay** before the new steady state is reached + a constraint-status banner (PASS/REJECTED/FLAGGED per constraint and per envelope check) + an estimated savings/cost line, all sourced from the same `Recommendation`-shaped object used in Section 14.4 (reused dataclass, `mode` field set accordingly).

---

## 17. UI/UX Specification

Ten required views (unchanged set from v1.0, content updated where noted):

| # | View | Primary content |
|---|---|---|
| 1 | Plant Overview | Kiln + Mill status tiles, production, thermal/electrical energy, AI status, anomaly status |
| 2 | Kiln Digital Twin | Animated process flow (Section 8 topology), **driven strictly by live simulation state (Section 19.4)** + live-looking values + alarms |
| 3 | Cement Mill Digital Twin | Animated process flow, **driven strictly by live simulation state** + live-looking values + alarms |
| 4 | AI Optimization | Current vs **multi-horizon predicted** states vs recommended state, expected impact, **Recommendation Quality (HIGH/MEDIUM/LOW — never a numeric percentage)**, **mode (Normal/Experimental) and envelope status**, reason |
| 5 | What-if Simulation | Sliders (Section 16.1) + Normal/Experimental mode toggle + before/after comparison **with visible delay in the transition chart** |
| 6 | Time-Series Explorer | Zoomable/selectable Plotly charts across all tags, baseline vs optimized overlay |
| 7 | Anomaly Detection | Live anomaly score, "Inject abnormal condition" control, warning card (Section 15) |
| 8 | Model Performance | Metrics tables/plots **per target and per horizon** (Section 22), chronological **and** scenario-holdout results (Section 13.3) |
| 9 | Data Quality | Automated data-quality report |
| 10 | Factory Data Requirements | Rendered tag-level requirements document (Section 27) |

An eleventh **Factory Presentation Mode** (Section 29) is a simplified overlay/alternate rendering of views 1 and 4, not a separate data path, and must preserve the Synthetic-to-Real Transfer Strategy distinction (Section 21).

### 17.1 Visual style
Industrial control/engineering-analytics look, not generic SaaS: dark or light industrial theme, process-diagram iconography, KPI cards, trend sparklines, alarm color coding (green/amber/red), monospace-flavored numeric readouts. Full design tokens are the responsibility of the implementer using the `frontend-design` skill/guidance if a web build is chosen; inside Colab, the equivalent look is achieved via a self-contained HTML/CSS/SVG panel (Section 19.3).

---

## 18. Dashboard Specification

### 18.1 Main screen — Digital Twin Overview
Kiln status, Mill status, Production, Thermal energy, Electrical energy, AI status, Anomaly status — each as a KPI card with current value, trend sparkline, and status color.

### 18.2 Kiln Panel
Fuel rate, Feed rate, Burning zone temperature, O2, CO, ID fan, Production, Specific thermal consumption.

### 18.3 Mill Panel
Feed, Mill power, Separator RPM, Pressure, Blaine, Residue, Specific electricity consumption.

### 18.4 AI Panel (revised in v1.1)
Current state, **Multi-horizon predicted state (5/10/15/30 min)**, Recommended action, Expected savings, **Recommendation Quality (HIGH/MEDIUM/LOW)**, **Mode (Normal/Experimental) and Envelope Status**, Reason for recommendation — directly rendering the `Recommendation` object (Section 14.4).

All four sub-panels are populated exclusively via the `DataProvider` + model-inference calls — no panel may contain a literal/hard-coded number (NFR-6).

---

## 19. Simulation Engine Specification

### 19.1 Simulation loop (revised in v1.1)
```
Current State → Apply Inputs → Calculate Process Dynamics (Section 9/10 equations, each relationship routed
             through its own DelayedResponse, Section 9.4/10.3) → Update State (with energy/mass-balance
             closure tracked, Section 9.3/10.2) → Generate Sensor Measurements (Section 11.5)
             → Feed AI (Model A/B) → Predict Future State (per configured horizon) → Optimize (Model C,
             with envelope validation, Section 14.3) → Display Recommendation
```

### 19.2 Modes
- **Offline simulation**: batch-generates the full synthetic dataset (Section 11) for training/evaluation; vectorized where possible for speed (NFR-3).
- **Interactive simulation**: single-step / short-horizon rollout used by What-if and Optimization, called from the UI; must satisfy NFR-2 (<3s round trip).

### 19.3 Visualization rendering approach (Technology Decision, unchanged from v1.0)
The animated process-flow view (material/gas/fuel/air flow, equipment state) is rendered as **self-contained HTML/CSS/SVG** (animated arrows/particles along predefined paths, rotating equipment glyphs) generated in Python and displayed via `IPython.display.HTML` inside the Colab output cell. This is chosen over a 3D engine and over a server-based framework (avoids Colab tunneling fragility, NFR-9) while still delivering a genuinely animated, non-static impression of an operating plant, exportable as a standalone `.html` file for the factory presentation (Section 29).

### 19.4 Single Source of Truth & Visualization Binding (new in v1.1, mandatory)
The animation is **not** a prerecorded GIF or decorative loop. Every important animated element is bound directly to `Twin.current_state_snapshot()` (Section 8.4/8.5):

```
Fuel increase   → fuel-flow visual (particle density/speed) changes → combustion-intensity glow changes
                → temperature indicator changes → O2 indicator changes → exhaust-flow visual changes
ID Fan change   → gas-flow visual changes → pressure indicator changes → O2 indicator changes
Kiln feed change→ material-flow visual changes → production indicator changes → thermal-load indicator changes
Mill feed change→ material-flow visual changes → mill load/power indicator changes
Separator speed → separator visual (rotation speed) changes → fineness/throughput trade-off indicators change
```
Concretely: the HTML/SVG renderer (Section 19.3) accepts the same state object consumed by the numeric dashboard panels (Section 18) and the AI layer (Sections 13–15) as its only input — animation parameters (flow-particle speed/opacity/density, equipment rotation rate, combustion-glow intensity, alarm coloring) are computed functions of that state, never separately hard-coded constants or a canned sequence. This is a testable requirement: the no-hard-coding audit (Section 34) is explicitly extended to cover the visualization-parameter-generation code path.

---

## 20. Validation Strategy

Because no real plant data exists, validation is performed against (extended in v1.1):

1. **Known process relationships** — directional/monotonicity checks (e.g. fuel↑ ⇒ BZT↑, holding other inputs fixed) asserted in unit tests (Section 34); not required to be perfectly monotonic globally where the reduced-order model contains deliberate nonlinearities (e.g. the CO/O2 relationship, Section 9.4), but directionally correct within each defined operating regime.
2. **Synthetic ground truth** — Model A/B evaluated against the simulator's own true (noise-free) state, not just the noisy measurement, to separate model error from sensor noise.
3. **Held-out simulated scenarios** — both a chronological split and a scenario-based holdout split (Section 13.3), to avoid leakage across the ramped-transition structure and to test generalization to unseen regimes.
4. **Perturbation tests** — apply small input perturbations and confirm twin/ML outputs move in the physically expected direction and roughly expected magnitude, appearing only after the configured dead time (Section 9.4/10.3).
5. **Constraint tests** — the optimizer must never emit a `Recommendation` with `constraint_status` other than `"PASS"`.
6. **Stability tests** — long-duration simulation (multi-month) must not diverge/blow up (bounded-state assertions).
7. **Conservation tests (new)** — energy and mass balance residuals (Section 9.3/10.2) stay within the configured tolerance (NFR-10) across the full simulated horizon, read through the three residual-validation regimes of the NFR-10 implementation note (settled / transient / startup, plus the horizon-wide integral).
8. **Causality/directional tests (new)** — fuel increase raises thermal input and (with the configured dead time) burning-zone temperature; ID fan increase moves gas-flow/draft-related variables in the expected direction; feed increase raises production and thermal demand in the expected direction; separator-speed changes move the mill quality/throughput trade-off in the expected direction — evaluated within defined operating regimes, not as global unconditional monotonicity.
9. **Leakage-prevention tests (new)** — scenario-holdout metrics (Section 13.3) are computed and reported alongside chronological-split metrics, and are checked to be a genuinely harder/different test (not accidentally identical to the chronological split).

The system must display, verbatim, wherever performance is claimed:
> "This prototype demonstrates architecture and methodology, not validated plant performance."

---

## 21. Synthetic-to-Real Transfer Strategy (new section, v1.1)

### 21.1 The core distinction
Excellent ML performance on synthetic data — good MAE/RMSE/R² for Model A, good precision/recall for Model B, plausible-looking energy savings from Model C — **does not demonstrate real-plant performance**. This distinction must be preserved everywhere the system communicates results, including Factory Presentation Mode (Section 29) and every Limitations statement (Section 31).

### 21.2 What the synthetic environment validates
- The end-to-end **architecture**: `DataProvider` abstraction, simulation → data → features → models → optimization → visualization pipeline.
- The **data pipeline**: schema, resampling, data-quality checks, export formats.
- **Feature engineering**: lag-feature construction, multi-horizon feature sets.
- **Model interfaces**: training/inference/registry contracts (Section 13.4), so swapping in real data changes only the `DataProvider` implementation, not the model code.
- **Simulator behavior**: conservation enforcement (Section 9.3/10.2), delay realism (Section 9.4/10.3), regime coverage (Section 11.4).
- **Optimization logic**: hard-constraint separation, envelope/OOD gating (Sections 14.2–14.3), multi-objective weighting mechanics.
- **Anomaly-detection pipeline**: detection + explanation + envelope-gating dual role (Section 13.2).
- **Visualization**: simulation-state-driven rendering (Section 19.4).
- **End-to-end reproducibility**: seeded, versioned, logged (Section 11.6, 13.4).

### 21.3 What the synthetic environment does NOT validate
- Real predictive accuracy of Model A on an actual plant.
- The real magnitude (or even the real sign, under some real-world confounders not modeled here) of any claimed energy saving.
- Real anomaly base rates, false-positive rates, or fault signatures — real sensor/equipment failure modes differ from the simplified fault injection of Section 11.4.
- Any claim of plant-specific calibration — every numeric constant in Sections 9–10 is a documented `ASSUMPTION`, not a measurement of any real kiln or mill.

### 21.4 Transition path (future phase, not built in v1.1)
```
Synthetic Process Model
        ↓
Synthetic Dataset
        ↓
Prototype Validation  (architecture, pipeline, interfaces — this PRD's scope)
        ↓
Real Plant Historical Data  (Section 26/27 — factory-provided)
        ↓
Data Quality Assessment  (Section 11.5-equivalent checks re-run on real data)
        ↓
Plant-Specific Calibration  (every ASSUMPTION in Sections 9-10, 13-14 recalibrated)
        ↓
Retraining  (Model A/B/C retrained on real data through the unchanged interfaces of Section 13.4)
        ↓
Real-Plant Validation  (Section 20-equivalent tests re-run against real held-out data)
        ↓
Operator Validation
        ↓
Production Deployment  (out of scope for this PRD entirely — see Section 30, Safety Constraints)
```

### 21.5 Required standing statement
The following statement must be preserved, verbatim or near-verbatim, in `SIMULATION_ASSUMPTIONS.md`, `MODEL_CARD.md`, Factory Presentation Mode (Section 29), and the Limitations section (Section 31):

> "The synthetic model is a development and demonstration environment, not a calibrated representation of any specific cement plant."

---

## 22. Model Evaluation

| Category | Metrics |
|---|---|
| Regression (Model A) — **per target, per horizon** | MAE, RMSE, R², MAPE (where target is strictly positive and non-near-zero); reported separately for the chronological split and the scenario-holdout split (Section 13.3) |
| Anomaly detection (Model B) | Precision, Recall, F1, False Positive Rate — computed against `injected_fault`/`operating_regime` ground truth |
| Optimization (Model C) | Energy reduction (%) per objective term, production deviation (%), quality deviation, stability deviation, emission deviation, hard-constraint violation count (must be zero for accepted recommendations), envelope-rejection rate, optimization runtime (s) |

Example per-horizon reporting format (`reports/metrics/model_a_horizon_metrics.json`):

| Target | Horizon | MAE | RMSE | R² | Split |
|---|---|---|---|---|---|
| burning_zone_temperature | t+5min | … | … | … | chronological |
| burning_zone_temperature | t+5min | … | … | … | scenario-holdout |
| burning_zone_temperature | t+30min | … | … | … | chronological |
| … | … | … | … | … | … |

All metrics are computed automatically after each training run and written to `reports/metrics/*.json`, and surfaced in the Model Performance view (Section 17, view 8).

---

## 23. Project Structure

```
project/
│
├── notebooks/
│   └── 00_cement_digital_twin_demo.ipynb        # the single Colab entry point (Section 25)
│
├── src/
│   ├── simulation/          # SimulationConfig, ScenarioScheduler, SensorModel, DelayedResponse (Section 9.4/10.3), simulation loop
│   ├── process_models/      # KilnTwin, CementMillTwin, PlantTwin, ProcessUnit interface, FuelProperties (Section 9.2),
│   │                         # energy/mass balance closure logic (Section 9.3/10.2)
│   ├── data_generation/     # dataset builders calling simulation/, export to CSV/Parquet
│   ├── data_processing/     # validation, cleaning, data-quality report
│   ├── features/            # lag-feature builders shared by Model A/B, per-horizon feature sets (Section 13.1)
│   ├── models/               # ModelA (multi-horizon prediction + uncertainty, Section 13.1/13.1.1), ModelB (anomaly),
│   │                         # registry, train/eval scripts, chronological + scenario-holdout evaluation (Section 13.3)
│   ├── optimization/        # objective, hard constraints, envelope/OOD validation (Section 14.3), ModelC optimizer,
│   │                         # rule-engine baseline, baseline-comparison logic (Section 14.5)
│   ├── anomaly_detection/   # IsolationForest + SPC wrappers, DemoInjector (Section 15)
│   ├── digital_twin/        # DataProvider interface + SyntheticDataProvider/RealPlantDataProvider (Section 26)
│   └── visualization/       # HTML/SVG twin renderer bound to Twin.current_state_snapshot() (Section 19.4), Plotly chart builders, dashboard assembly
│
├── data/
│   ├── raw/                 # untouched synthetic exports
│   ├── processed/           # cleaned/validated
│   └── synthetic/           # generator outputs (CSV + Parquet + config sidecars)
│
├── models/                  # joblib artifacts + registry.json
│
├── configs/                 # kiln_dynamics.yaml (now incl. energy_balance:, mass_balance:, delays: blocks),
│                             # mill_dynamics.yaml (now incl. mass_balance:, delays: blocks),
│                             # optimization.yaml (now incl. objective weights + hard-constraint table + envelope thresholds),
│                             # ml.yaml (prediction horizons, uncertainty ensemble size), scenarios.yaml
│
├── reports/                 # metrics/ (per-horizon, per-split), data_quality/, experiments/
│
├── tests/                   # unit + integration + validation + conservation + causality + leakage tests (Section 34)
│
├── requirements.txt
│
└── README.md  (+ ARCHITECTURE.md, DATA_DICTIONARY.md, MODEL_CARD.md, SIMULATION_ASSUMPTIONS.md,
                DEMO_GUIDE.md, FACTORY_DATA_REQUIREMENTS.md — Section 35)
```

`src/` must be a normal importable Python package (`pip install -e .` or notebook `sys.path` insert) — no logic may live only inside notebook cells (NFR-7).

---

## 24. Technology Stack

| Technology | Role | Why chosen |
|---|---|---|
| Python 3.11 | Core language | Universal Colab support, ecosystem fit |
| NumPy, Pandas, SciPy | Simulation core, data handling, `differential_evolution` | Mature, fast, zero-friction in Colab, deterministic with seeded RNG |
| scikit-learn | RandomForest/GradientBoosting (Model A, per horizon), IsolationForest (Model B), bootstrap ensembling for uncertainty (Section 13.1.1) | Interpretable, fast on tabular data, no extra install friction, sufficient for the documented uncertainty methodology — **no new dependency added in v1.1** (NFR-5) |
| LightGBM | Optional stretch model for Model A | Only added if it measurably beats sklearn baselines; lighter than XGBoost for Colab install |
| Plotly | Time-series charts (Section 17 view 6) | Interactive zoom/selection, renders natively in Colab outputs |
| Custom HTML/CSS/SVG (via `IPython.display.HTML`) | Animated digital-twin process view, bound to live simulation state (Section 19.4) | Avoids heavy 3D engines and server/tunnel fragility (Section 19.3), fully exportable for the factory demo |
| ipywidgets | What-if sliders, Normal/Experimental mode toggle, "Inject abnormal condition" buttons | Native Colab interactivity without an external server |
| joblib | Model persistence | Standard, fast, simple |
| PyYAML | Config files (now including delay, balance, uncertainty, and objective-weight blocks) | Human-readable, diffable, calibration-friendly |
| PyArrow (via `pandas.to_parquet`) | Parquet export (FR-4) | Standard, no extra service required |

**Explicitly not used in v1.1** (unchanged reasoning from v1.0): PyTorch/deep learning; Streamlit/Dash as the *primary* interface (offered only as an optional standalone `app.py` for local/offline factory-laptop demos, reusing `src/` unchanged); Docker/Kubernetes/cloud DB/OPC-UA client libraries; conformal-prediction libraries (documented Phase-2 item, Section 32) — v1.1's uncertainty methodology deliberately uses only the existing scikit-learn ensembling already in the stack.

---

## 25. Google Colab Architecture

Single notebook, `notebooks/00_cement_digital_twin_demo.ipynb`, organized into these sections/cells in order:

1. **Installation** — `pip install` only what's missing beyond Colab defaults (e.g. `lightgbm` if used); pin versions.
2. **Configuration** — load/display `configs/*.yaml` (now including delay, balance, uncertainty, and objective-weight blocks), set seed, choose demo duration.
3. **Simulation** — instantiate `PlantTwin`, run `ScenarioScheduler` for the configured horizon; balance residuals tracked per step.
4. **Dataset generation** — run the full synthetic data pipeline (Section 11), export CSV/Parquet.
5. **Data validation** — run the data-quality report, display summary.
6. **ML training** — train Model A (multi-horizon prediction + uncertainty ensembling) and Model B (anomaly detection); save to `models/`.
7. **Model evaluation** — compute and display per-horizon, per-split metrics (Section 22).
8. **Optimization** — instantiate Model C, run one example optimization showing hard-constraint filtering, envelope/OOD validation, multi-objective breakdown, and Recommendation Quality (mirrors the revised AI Decision format, Section 14.4).
9. **Digital Twin visualization** — render the animated Kiln + Mill twin views, bound to live simulation state (Section 19.4).
10. **Interactive dashboard** — assemble Plant Overview / Kiln / Mill / AI panels with ipywidgets controls, including the Normal/Experimental What-if toggle.
11. **Demo scenarios** — one-click cells for Demos 1–5 (Section 28).
12. **Export results** — bundle report artifacts (metrics, recommendation logs, exported HTML twin view) into `reports/`.

---

## 26. Real Factory Data Migration Strategy

### 26.1 Common interface
```python
class DataProvider(ABC):
    @abstractmethod
    def get_timeseries(self, tags: list[str], start: datetime, end: datetime, resample: str | None = None) -> pd.DataFrame: ...
    @abstractmethod
    def get_tag_metadata(self) -> pd.DataFrame: ...   # unit, description, expected range, sampling interval

class SyntheticDataProvider(DataProvider):
    """Wraps the Section 11 simulation pipeline; used by everything in v1.1."""

class RealPlantDataProvider(DataProvider):
    """Stub in v1.1: constructor accepts a connection profile (CSV path / SQL DSN /
    OPC-UA endpoint / Historian export path); raises NotImplementedError per method
    body with a clear TODO pointing to FACTORY_DATA_REQUIREMENTS.md and to the
    Synthetic-to-Real Transfer Strategy (Section 21)."""
```
The ML pipeline, optimization engine, and UI consume only `DataProvider` — never `SyntheticDataProvider` directly — so switching providers is a one-line change (FR-14).

### 26.2 Supported real-source formats (future)
CSV export, DCS export, SCADA export, Historian export (e.g. AVEVA/PI-style), SQL database, OPC-UA — each becomes a thin adapter implementing `RealPlantDataProvider`, converting native tags to the schema in Section 12 via a per-plant tag-mapping config (`configs/tag_mapping.yaml`, not yet populated). Real-data onboarding follows the Section 21.4 transition path.

### 26.3 Resampling
`get_timeseries(..., resample=...)` supports 1s/5s/10s/30s/1min/5min targets (FR-20), since real factories will not uniformly provide 1-minute data for every tag.

---

## 27. Factory Data Requirements

This section is the source content for the standalone `FACTORY_DATA_REQUIREMENTS.md` deliverable (Section 35), organized by process unit exactly as the factory's DCS/Historian is organized, so the request is immediately actionable ("we need these historical tags from your historian/DCS/SCADA").

### 27.1 Structure per requested tag
tag name · description · unit · recommended sampling interval · data type · expected range · process unit · importance (critical/important/optional) · mandatory/optional.

### 27.2 Coverage by process unit
- **Kiln** — all rows in Section 12.1 tagged `process_unit = Kiln`, `importance = critical` for feed/fuel/BZT/O2/production, `important` for currents/vibration, `optional` for SO2/NOx if not currently monitored.
- **Preheater** — `preheater_pressure`, `preheater_outlet_temperature` (critical).
- **Precalciner** — `calciner_fuel_rate_tph`, `calciner_temperature`, `tertiary_air_flow` (critical).
- **Cooler** — `secondary_air_temperature`, `cooler_outlet_temperature`, `cooler_fan_power`, `clinker_temperature` (important).
- **Fuel** — `kiln_fuel_rate_tph`, `calciner_fuel_rate_tph`, plus (optional, not in v1.1 schema but requested if available) fuel calorific value/LHV lab results to replace the `lhv_solid_fuel_MJ_per_kg` / `lhv_gas_fuel_MJ_per_Nm3` **ASSUMPTIONs** in Section 9.2 — this is now a precisely specified ask (a single MJ-basis LHV figure per fuel stream) rather than an ambiguous kcal-based request.
- **Fans** — `ID_fan_speed`, `ID_fan_power`, `ID_fan_current`, mill `fan_speed`, `fan_power_kw` (important).
- **Raw Mill** — *placeholder only in v1.1* (out of scope, Section 5.2); listed as "optional / future phase" so the factory knows it will eventually be requested.
- **Cement Mill** — all rows in Section 12.2, `critical` for feed/power/Blaine/residue/specific power, `important` for pressures/vibration.
- **Separator** — `separator_speed_rpm`, `separator_current`, `separator_pressure` (critical — this is the primary quality lever).
- **Electrical system** — total plant/section kWh meters if available (important; not yet in v1.1 schema, added as an "optional, high value" ask so plant-wide electrical optimization can be validated later).

### 27.3 Requested history depth and format
Prefer **several months** of historical data where available, in whatever native export the factory's historian/DCS/SCADA supports (CSV/SQL/PI/AVEVA/OPC-UA), at the best available native resolution — the system will resample down (Section 26.3), never assumes high-frequency availability for every tag. **If step-test or transient data is available** (e.g. logged responses to a known setpoint change), it is explicitly requested as high-value input for calibrating the per-relationship delay parameters of Section 9.4/10.3.

---

## 28. Demo Scenarios

1. **Normal Operation** — run the twin through the startup-like transition into steady medium production; show Plant Overview settling to green/nominal.
2. **Energy Optimization** — from a stable but sub-optimal steady state (e.g. slightly high fuel relative to feed), run Model C and show the Section 14.4 `Recommendation`: hard-constraint filtering, envelope/OOD validation, the multi-objective breakdown, a positive thermal-energy saving, `constraint_status = PASS`, `recommendation_quality`, and its natural-language reason — compared against all five Section 14.5 baselines.
3. **Low Oxygen** — trigger regime 5 (Section 11.4) via the Anomaly view's "Inject abnormal condition"; show Model B detection, the warning card (Section 15), and the rule-engine suggested action.
4. **Mill Optimization** — change separator speed/feed via What-if (Normal Mode); show the throughput/Blaine/energy trade-off explicitly (before/after table + chart with visible transition delay, Section 16.2).
5. **What-if Analysis** — scripted example: "What happens if we reduce fuel by 5%?" in Normal Mode, then optionally "what if we reduce it by 25%?" in Experimental Mode to show the envelope-warning banner — run through the What-if flow (Section 16) and display the predicted consequences end-to-end.

Each demo is a single Colab cell (Section 25, cell 11) that requires no manual setup once earlier cells have run.

---

## 29. Factory Presentation Mode

A simplified rendering path (not a separate data path — reuses Sections 14/17/18 outputs) that shows only:
```
Current Plant State → AI Prediction → Optimization Opportunity → Recommended Action → Expected Benefit
```
with KPI cards: Potential Thermal Energy Saving, Potential Electrical Energy Saving, Production Stability, Quality Stability, Anomalies Detected — every card explicitly labeled **"Synthetic Demonstration"** or **"Simulation Estimate"**, and the view carries a visible link/footnote to the Section 21 Synthetic-to-Real Transfer Strategy disclaimer. This mode never displays raw tag lists, model internals, code, or a numeric confidence percentage. Where a recommendation-quality indicator is shown, it uses the **Recommendation Quality** categorical (HIGH/MEDIUM/LOW, Section 14.4) only — it is the only view meant for a plant-manager audience (Persona 3, Section 4).

---

## 30. Safety Constraints

- The system **never** issues a control command to real equipment; it is **Decision Support Only**. Every AI output is labeled **"AI Recommendation,"** never "Automatic Control Command" (FR-16).
- **Hard process/safety constraints (Section 14.2) can never be traded away by the soft multi-objective optimization for energy savings** — this is enforced structurally: hard constraints filter candidates *before* objective scoring, they are never expressed as penalty terms the optimizer could offset with a large-enough energy gain.
- **The optimizer rejects or flags any recommendation outside the calibrated operating envelope (Section 14.3)**; it does not extrapolate confidently beyond validated conditions, and Experimental What-if Mode (Section 16.1) is the only path that can explore beyond that envelope, always with an explicit low-reliability warning.
- A future real-world deployment (Section 32) must require explicit operator approval and standard industrial control-system safety mechanisms (interlocks, permissive logic) before any recommendation could influence a real setpoint — this PRD does not build that pathway, it only documents the requirement.
- Optimizer output is always constraint- and envelope-checked (`constraint_status`, `envelope_status`) before display; a non-`PASS`/non-`WITHIN_ENVELOPE` state is shown, not hidden or silently clipped.

---

## 31. Limitations

Displayed verbatim wherever results are shown, and captured in `SIMULATION_ASSUMPTIONS.md` (see also Section 21, Synthetic-to-Real Transfer Strategy, for the full framing):

> This is a synthetic demonstration environment. The simulation is not calibrated against a real cement plant. The AI models are not production-validated. Energy-saving percentages are simulation results, not guaranteed factory savings. Real deployment requires real historical data, process-engineering validation, plant-specific calibration, OT/IT integration, cybersecurity review, operator validation, safety validation, and commissioning.

Additional documented limitations: kiln and mill are simulated with independent/buffered clinker supply (Section 8.3, not tightly coupled); no raw-mill circuit in v1.1; no CFD/detailed kinetics; single generic mill type (not VRM- or ball-mill-specific); all numeric constants — including every delay, every energy/mass-balance loss/recovery fraction, and every fuel LHV — are engineering-reasoned defaults pending real-data calibration (every one tagged `ASSUMPTION`); the v1.1 **Recommendation Quality** classification (Section 13.1.1) is a heuristic derived from documented factors (ensemble spread, envelope distance, constraint margin, model agreement), not a calibrated statistical probability — full conformal-prediction intervals remain a Phase-2 item (Section 32).

---

## 32. Future Roadmap

**Phase 2 (once real data is available):**
- Implement `RealPlantDataProvider` adapters (CSV/SQL/Historian/OPC-UA) per Section 26.2; populate `configs/tag_mapping.yaml`.
- Recalibrate every `ASSUMPTION` constant in Sections 9–10 (including all delay and conservation-balance parameters) against real historian/step-test data; re-validate per Section 20.
- Evaluate LSTM/GRU/Temporal Fusion Transformer for Model A once multi-week/multi-line real sequences exist and a longer-horizon forecasting requirement is confirmed beyond the classical multi-horizon approach of Section 13.1.
- Evaluate autoencoder-based anomaly detection as a complement to Isolation Forest/SPC.
- Evaluate full conformal-prediction or calibrated probabilistic intervals to replace/augment the v1.1 ensemble-spread-based Recommendation Quality heuristic (Section 13.1.1).
- Add raw mill / raw meal preparation circuit modeling.
- Tighten kiln↔mill coupling (real clinker silo buffer dynamics) if the factory wants whole-line optimization.
- Add VRM-specific and ball-mill-specific variants of `MillModel`.
- Refine the energy-balance sub-model with detailed heat-loss components (e.g. separate shell-radiation profile by kiln zone) once real thermal-survey data exists.
- Add real OT/IT integration, cybersecurity review, and an operator-approval workflow ahead of any real control-adjacent use.
- Optional standalone web app (`app.py`, e.g. Streamlit) for factory-laptop demos outside Colab, reusing `src/` unchanged.

---

## 33. Acceptance Criteria

A factory engineer opening the system should, within several minutes, be able to answer the following — restated as testable acceptance criteria. AC-1 through AC-12 are unchanged from v1.0; AC-13 through AC-24 are new in v1.1.

- [ ] AC-1: Plant Overview clearly shows what the kiln and mill are each doing right now (status + key values).
- [ ] AC-2: Kiln/Mill Digital Twin views visibly animate flow, not a static picture.
- [ ] AC-3: Time-Series Explorer lets the user identify which variables matter (via chart selection + Model A feature importance).
- [ ] AC-4: What-if Simulation produces a visibly different, physically sensible outcome when a manipulated variable is changed, within NFR-2's 3-second budget.
- [ ] AC-5: The notebook cell that generates synthetic data is inspectable and its config/seed is visible (reproducibility, FR-1/NFR-4).
- [ ] AC-6: AI Optimization view shows a prediction that is traceable to Model A's saved metrics (Section 22).
- [ ] AC-7: AI Optimization view shows a `Recommendation` (Section 14.4) with baseline vs proposed, expected impact, and a natural-language reason (Section 15).
- [ ] AC-8: What-if and AI Recommendation give consistent results for the same scenario (Section 16.2 consistency requirement).
- [ ] AC-9: Factory Data Requirements view/document lists concrete tags the factory would need to provide.
- [ ] AC-10: README/ARCHITECTURE.md explain, in under one page, how this evolves into a real industrial system (Section 26, Section 21).
- [ ] AC-11: Every screen and export carries the "Synthetic Demonstration" label and the limitations statement (Section 31) is reachable from the UI.
- [ ] AC-12: No panel contains a hard-coded/non-traceable number (NFR-6, verified by the test in Section 34).
- [ ] AC-13: Fuel energy calculations use a single canonical unit (MJ) with documented, tested conversions (Section 9.2); no mixed mass-based/volume-based LHV ambiguity anywhere in the codebase (`test_fuel_energy_unit_consistency` passes).
- [ ] AC-14: Kiln and mill energy/mass balances close within the configured tolerance (`test_kiln_energy_balance`, `test_kiln_mass_balance`, `test_mill_mass_balance` all pass, NFR-10).
- [ ] AC-15: Manipulated-variable→output relationships exhibit distinct, configurable dead-time + lag per relationship (Section 9.4/10.3), not one universal time constant; What-if (Section 16.2) visibly shows a delayed, not instantaneous, response.
- [ ] AC-16: Model A produces predictions at all configured horizons (default 5/10/15/30 min) with per-target, per-horizon metrics reported (Section 22).
- [ ] AC-17: Every synthetic performance claim is accompanied by the Section 21 disclaimer; Factory Presentation Mode never implies real-plant validation.
- [ ] AC-18: No numeric "confidence %" appears anywhere in the UI without a documented uncertainty method (Section 13.1.1); v1.1 displays Recommendation Quality (HIGH/MEDIUM/LOW) only.
- [ ] AC-19: Recommendations outside the calibrated operating envelope are REJECTED (Normal Mode) or clearly FLAGGED with the low-reliability banner (Experimental Mode), never silently accepted (Section 14.3).
- [ ] AC-20: Hard constraints (Section 14.2) are structurally never traded away by the soft multi-objective optimization, verified by a dedicated test (Section 34).
- [ ] AC-21: Every animated element in the Digital Twin view is driven by the live `Twin.current_state_snapshot()`, not a prerecorded or hard-coded animation (Section 19.4, verified by the extended no-hard-coding audit).
- [ ] AC-22: AI recommendations are compared against the full baseline set (Current / Historical / Best Comparable Historical / Digital Twin Baseline) using identical process conditions (Section 14.5).
- [ ] AC-23: ML evaluation includes both a chronological split and at least one fully held-out regime/scenario split, with both result sets reported (Section 13.3).
- [ ] AC-24: Conservation tests (energy, mass) and directional causality tests pass before any demo is considered release-ready (Section 34).

---

## 34. Testing Strategy

| Layer | Tests |
|---|---|
| Unit — fuel energy units (new) | `test_fuel_energy_unit_consistency()` — fuel flow × LHV produces a physically consistent thermal power/energy figure; mass-based and volume-based LHV terms are never summed without going through the documented MJ conversion (Section 9.2). |
| Unit — conservation (new) | `test_kiln_energy_balance()`, `test_kiln_mass_balance()`, `test_mill_mass_balance()` — residuals stay within the configured tolerance (NFR-10) across a representative simulated horizon. |
| Unit — residual-validation methodology (new) | `tests/test_conservation_validation.py` — the three NFR-10 regimes are classified by cause and not by outcome, every bound is read from config, the startup regime forms no metric on a collapsing denominator, mass conservation keeps its single unchanged metric, and a deliberately broken closure still fails (see the NFR-10 implementation note in Section 7). |
| Unit — delay framework (new) | Proves distinct relationships respond with their own configured dead-time/lag (Section 9.4/10.3), not instantaneously and not with a shared universal constant; a step change is not reflected in a delayed output before its dead time elapses. |
| Unit — process models | Directional/monotonicity checks per Section 20.8 (fuel↑⇒BZT↑ after dead time, ID fan↑⇒O2↑, etc.); bounds/hard-constraint enforcement; lag-equation convergence to expected steady state. |
| Unit — sensor model | Noise statistics match configured `std`; drift only appears in the "sensor drift" regime; dropout rate within configured bound. |
| Unit — feature/ML | Feature builder produces no leakage (no target-derived features); model train/predict round-trip on a tiny fixture dataset; per-horizon feature sets are correctly windowed. |
| Integration — simulation pipeline | End-to-end `ScenarioScheduler → Twin → SensorModel → dataset` produces the expected schema (Section 12) and all 14 regime labels are present; balance residuals recorded and within tolerance. |
| Integration — multi-horizon prediction (new) | Every configured horizon produces a value and a metric for every target; a missing horizon is caught as a regression. |
| Integration — envelope/OOD (new) | A candidate outside the training range or beyond the anomaly threshold is `REJECTED` in Normal Mode and `FLAGGED` with the low-reliability banner in Experimental Mode; an excessive Δ setpoint is rejected (Section 14.3). |
| Integration — hard-constraint immutability (new) | Fuzzed objective weights (including an extreme `w_thermal`/`w_electric`) never produce an accepted candidate that violates a hard constraint (Section 14.2). |
| Integration — optimization | Optimizer never returns `constraint_status == "REJECTED"` as its *final* recommendation (only surviving, passing candidates are ever recommended); runtime under NFR-2 budget on a benchmark scenario. |
| Integration — What-if ↔ Recommendation consistency | Running What-if with the optimizer's own proposed deltas reproduces (within tolerance) the optimizer's predicted impact (AC-8). |
| Integration — leakage prevention (new) | Scenario-holdout evaluation numbers (Section 13.3) are computed and differ meaningfully from chronological-split numbers (sanity check that the holdout is genuinely informative, AC-23). |
| Regression | Fixed seed ⇒ fixed dataset hash (NFR-4), checked in CI-style test/notebook assertion. |
| UI/no-hard-coding audit (extended) | Static scan/test asserting every displayed numeric field in dashboard-assembly code *and every visualization-animation parameter* (Section 19.4) originates from a `DataProvider`/model/`Twin.current_state_snapshot()` call, not a literal (NFR-6, AC-12, AC-21). |
| Data quality | Data-quality report correctly flags synthetically-injected missing values, duplicate timestamps, constant sensors, spikes, and drift when deliberately introduced in a test fixture. |

---

## 35. Documentation Requirements

| Document | Audience | Contents |
|---|---|---|
| `README.md` | Everyone | What this is, quick start (Colab link/cell order), system label/limitations banner |
| `ARCHITECTURE.md` | AI/ML engineers, IT/OT engineers | Layered digital-twin design (Section 8), single-source-of-truth data flow (Section 8.5/19.4), `DataProvider` abstraction (Section 26), module map (Section 23) |
| `DATA_DICTIONARY.md` | Process engineers, IT/OT engineers | Full Section 12 tables, one row per tag, including which are `ASSUMPTION`-derived, and the canonical-unit fuel-energy conversion (Section 9.2) |
| `MODEL_CARD.md` | AI/ML engineers, plant managers | Model A/B/C descriptions; **Model Validity Domain per model** — training data range, variables used, target, **all supported prediction horizons**, operating regimes represented, known limitations, **uncertainty method (Section 13.1.1)**, **OOD/envelope strategy (Section 14.3)**, evaluation scenarios (**chronological + scenario-holdout, Section 13.3**), metrics; the explicit statement **"This model has not been validated against real cement-plant data."** |
| `SIMULATION_ASSUMPTIONS.md` | Process engineers | Every `ASSUMPTION` constant from Sections 9–11, **now explicitly including every delay (dead-time + lag) parameter, every energy/mass-balance loss/recovery fraction, and every fuel LHV value with its documented unit conversion**, each with its default value and calibration note |
| `DEMO_GUIDE.md` | Sales/solutions engineer | Step-by-step script for Demos 1–5 (Section 28) and Factory Presentation Mode, including how to demonstrate Normal vs Experimental What-if Mode |
| `FACTORY_DATA_REQUIREMENTS.md` | Factory IT/OT engineers, plant managers | Section 27 content, ready to send to the factory, including the request for fuel LHV lab data and step-test/transient logs for delay calibration |

---

### Closing note
This PRD is intended to be handed directly to a coding agent. Build order: Section 23 skeleton → Section 8–10 process models **with conservation closure and per-relationship delays implemented from the start, and their unit tests written alongside (Section 34)** → Section 11–12 synthetic data pipeline → Section 13–15 ML layer **including multi-horizon targets and the uncertainty/Recommendation-Quality methodology** → Section 14/16 optimization/what-if **including hard-constraint separation, envelope/OOD gating, and multi-objective scoring from the start, not bolted on afterward** → Section 17–19 visualization/dashboard **with every animation parameter wired to live simulation state from the first implementation, not retrofitted** → Section 21 Synthetic-to-Real Transfer Strategy content threaded through Presentation Mode and Limitations → Section 25 Colab notebook assembly → Section 28–29 demo polish → Section 35 documentation pass. Every `ASSUMPTION` is a deliberate, documented placeholder — implement against the given default, do not silently invent a different number.
