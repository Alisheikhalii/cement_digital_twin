# SIMULATION_ASSUMPTIONS.md

> "The synthetic model is a development and demonstration environment, not a calibrated
> representation of any specific cement plant."
> — PRD v1.1.1 Section 21.5, required standing statement

**Audience:** process engineers (PRD Section 35).

**Purpose:** NFR-8 requires that every engineering constant sourced from public literature or
reasoned defaults is tagged `ASSUMPTION` in code *and* documented here — explicitly including
every delay parameter (dead time + lag), every energy/mass-balance loss and recovery fraction,
and every fuel LHV with its unit conversion.

Nothing in this file is a measurement of any real kiln or mill. Every value is a starting point
to be replaced by calibration against real historian / step-test data (PRD Sections 21, 26, 27).

**Scope of this revision.** Sections 9–10 (kiln and cement-mill process models) and Sections
11–12 (scenario scheduler, sensor model, data pipeline and export) are implemented and documented
below. Later sections are added to this file as each layer is built, per the PRD build order.

**Where the numbers live.** The process-model numbers are all in `configs/kiln_dynamics.yaml` and
`configs/mill_dynamics.yaml`; the scheduler and sensor-model numbers are all in
`configs/scenarios.yaml`. None are hard-coded in `src/`, with one documented exception: the FR-13
data-quality thresholds of §11.6 are module constants in `src/data_processing/quality.py`, because
that report is deliberately independent of the simulator so PRD 21 can re-run it on real plant
data. Each point of use in code carries an `# ASSUMPTION:` comment. The tables below give the
config path, the default value, and the calibration note — *what measurement would replace this
number*.

---

## 1. Fuel energy and the canonical unit (PRD 9.2)

All internal energy is **MJ**, all thermal power **MJ/h**. The single documented conversion is
`MJ_PER_KCAL = 4.184e-3` (`src/process_models/fuel.py`); kcal/kg appears only as a *display* unit
on `thermal_energy_kcal_per_kg_clinker`. Mass-based and volume-based LHVs are never summed in
native units — each stream is converted to MJ/h first (`test_fuel_energy_unit_consistency`).

| Config path (`kiln_dynamics.yaml`) | Default | Calibration note |
|---|---|---|
| `fuel.lhv_solid_fuel_MJ_per_kg` | 26.0 | Coal/petcoke blend (6200 kcal/kg × 4.184e-3 = 25.94). Replace with the fuel-lab LHV per fuel stream, **on an MJ basis**. Published range 24–28 MJ/kg. |
| `fuel.lhv_gas_fuel_MJ_per_Nm3` | 36.0 | Natural gas, volumetric (8600 kcal/Nm³). Unused stream in v1.1; kept so the volumetric path is exercised and unit-tested. |
| `fuel.kiln_burner_fuel_share` | 0.40 | 40 % main burner / 60 % calciner. Replace with the plant's own flow-meter split; typical precalciner 35–45 / 55–65. |
| `fuel.stoichiometric_air_Nm3_per_MJ` | 0.26 | Solid fuel; published 0.25–0.27. Replace from ultimate fuel analysis. |
| `fuel.combustion_CO2_Nm3_per_MJ` | 0.047 | ≈2.4 kg CO₂/kg fuel at 26 MJ/kg. Replace from ultimate analysis; note this is *combustion* CO₂ only — calcination CO₂ comes from the mass balance (`LOI_CO2_mass_share`). |

Reference fuel rates are **not** configured: they are solved from the energy balance at load time
(`src/process_models/kiln_reference.py`), so the reference point cannot drift out of energy
consistency when one of these constants is edited.

## 2. Kiln energy balance (PRD 9.3)

`Fuel_Energy_Input + Recovered_Cooler_Heat = Useful_Process_Heat + Exhaust_Gas_Loss +
Radiation_Other_Loss + Unaccounted_Loss`, all terms MJ/h, owned by `RotaryKilnModel`.

The closure is **enforced, not reported**: the exhaust-loss term is inverted into a preheater
outlet temperature (`balances.preheater_outlet_temperature_from_energy`), which is then published
through the `energy_closure_to_preheater_temperature` delay. See §7 for the residual behaviour
this produces.

| Config path (`energy_balance.*`) | Default | Calibration note |
|---|---|---|
| `cooler_heat_recovery_fraction` | 0.75 | Grate-cooler recuperation to secondary + tertiary air. Replace from a cooler heat balance (air flows and temperatures). |
| `radiation_other_loss_fraction` | 0.06 | Shell radiation + convection, as a fraction of fuel energy input. Replace from a shell-scanner survey. |
| `unaccounted_loss_max_fraction` | 0.03 | **Test tolerance bound, never a fit parameter** (NFR-10). It is the pass/fail limit of `test_kiln_energy_balance`, not a term the model tunes. |
| `clinker_formation_MJ_per_kg` | 1.75 | Theoretical clinkering enthalpy; published 1.70–1.80 MJ/kg clinker. Replace from the raw-mix chemistry. |
| `cp_clinker_kJ_per_kgK` | 1.05 | Mean cp of clinker to 1400 °C. |
| `cp_raw_meal_kJ_per_kgK` | 0.90 | Mean cp of raw meal. |
| `cp_exhaust_gas_kJ_per_Nm3K` | 1.40 | Mean cp of preheater exhaust gas. Replace with a composition-weighted value from gas analysis. |
| `water_evaporation_MJ_per_kg` | 2.44 | Latent + sensible heat to 100 °C for raw-meal moisture. |
| `clinker_exit_temperature_offset_K` | 50.0 | Clinker leaves the kiln 50 K below burning-zone temperature. Replace from a clinker-temperature measurement at the kiln discharge. |
| `min_preheater_outlet_temperature_C` | 150.0 | Numerical floor for the inverted closure — a guard against non-physical solutions in extreme what-ifs, not a process limit. It is *not* a clamp on normal operation (PRD 11.4). |

## 3. Kiln mass balance (PRD 9.3)

`Kiln_Feed = Clinker_Production + LOI_Loss + Dust_Loss + d(Kiln_Inventory)/dt`, all terms t/h.
The kiln inventory is a real state variable, which is why the closure holds to machine precision
during transients (`test_kiln_mass_balance` asserts < 1e-9 %, far inside the 3 % tolerance).

| Config path (`mass_balance.*`) | Default | Calibration note |
|---|---|---|
| `clinker_factor` | 0.63 | t clinker per t raw meal. Replace with the plant's own factor (feed and clinker weighfeeders). |
| `dust_loss_fraction` | 0.01 | Dust leaving with the exhaust gas. Replace from bag-filter/EP dust collection records. |
| `LOI_loss_fraction` | 0.36 | **DERIVED** `= 1 − clinker_factor − dust_loss_fraction`; consistent with raw-meal LOI 35–36 %. Not independently configurable — the three terms must sum to 1. |
| `LOI_CO2_mass_share` | 0.95 | CO₂ share of the LOI mass (remainder H₂O). Replace from raw-meal LOI/TGA analysis. |
| `kiln_residence_time_min` | 35.0 | Material residence time; the physical origin of the feed→production lag. **Supersedes** the 8 min "Feed → Production" lag of the PRD 9.4 table, whose own basis note says that lag is "derived from the kiln-inventory buffer" — modelling it twice would double-count it. Replace with a tracer/step test. |
| `CO2_density_kg_per_Nm3` | 1.977 | Physical constant at 0 °C / 101.325 kPa — not an assumption. |
| `H2O_vapour_density_kg_per_Nm3` | 0.804 | Physical constant at 0 °C / 101.325 kPa — not an assumption. |
| `tolerance_pct` | 3.0 | Closure tolerance (NFR-10); a test bound, not a model parameter. |

## 4. Mill mass balance (PRD 10.2)

`Mill_Feed = Cement_Production + Dust_Bag_Filter_Loss + d(Mill_Inventory)/dt`, all terms t/h.
Reject recirculation is **internal to the closed circuit** (PRD 10.2: "not a true loss"): it is
published as a tag but never appears as a closure term
(`test_reject_recirculation_is_not_a_closure_term`).

| Config path (`mass_balance.*`, `mill_dynamics.yaml`) | Default | Calibration note |
|---|---|---|
| `dust_bag_filter_loss_fraction` | 0.003 | PRD 10.2 band 0.2–0.5 % of feed. Replace from bag-filter dust collection records. |
| `mill_holdup_t` | 12.0 | Nominal material holdup. Gives the inventory time constant `holdup / throughput ≈ 5.8 min` at the reference feed rate — i.e. the feed→production lag is *physical*, not an invented τ. **ASSUMPTION** (this derivation, and the reuse of the same holdup to set the varying time constant as circulating load moves, is our modelling choice). Replace by a mill crash-stop holdup measurement. |
| `tolerance_pct` | 3.0 | Closure tolerance (NFR-10); a test bound, not a model parameter. |

## 5. Per-relationship delays (PRD 9.4, 10.3)

Every causal relationship owns its **own** `DelayedResponse` instance — pure transport dead time
followed by an exact zero-order-hold first-order lag `α = 1 − exp(−dt/τ)`. There is no shared
universal time constant anywhere in the twin (AC-15, `test_delays.py`). `tau_min: null` means the
relationship is a pure transport queue whose lag comes from a *physical inventory* instead.

A target offered during a step is released one dead time **after** that step, so on 1-minute steps
a 2-minute dead time first moves the output at minute 3.

### 5.1 Kiln (`kiln_dynamics.yaml → delays`)

Rows marked "PRD 9.4" are the PRD table verbatim; the rest are relationships the PRD describes
functionally but does not tabulate, assigned on the same physical reasoning — gas-side fast,
material/thermal-mass side slow. All values in minutes.

| Relationship | Dead time | τ | Source / basis |
|---|---|---|---|
| `fuel_to_burning_zone_temperature` | 2.0 | 25.0 | PRD 9.4 — combustion + kiln thermal mass |
| `fuel_to_oxygen` | 0.5 | 4.0 | PRD 9.4 — gas-side, fast |
| `feed_to_production` | 5.0 | *null* | PRD 9.4 — lag from `kiln_residence_time_min` (PRD 9.3) |
| `feed_to_burning_zone_temperature` | 8.0 | 20.0 | PRD 9.4 — preheater transport then thermal load |
| `id_fan_to_oxygen` | 0.2 | 3.0 | PRD 9.4 |
| `id_fan_to_pressure` | 0.1 | 1.0 | PRD 9.4 — near-immediate draught response |
| `calciner_fuel_to_calciner_temperature` | 1.0 | 10.0 | PRD 9.4 |
| `burning_zone_temperature_to_NOx` | 1.0 | 15.0 | PRD 9.4 — thermal NOx follows BZT |
| `oxygen_to_CO` | 0.5 | 2.0 | ASSUMPTION — same gas path as `fuel_to_oxygen` |
| `oxygen_to_SO2` | 1.0 | 6.0 | ASSUMPTION — sulfur release is slower than CO formation |
| `fuel_to_CO2` | 0.5 | 3.0 | ASSUMPTION — combustion CO₂, gas-side |
| `energy_closure_to_preheater_temperature` | 1.0 | 4.0 | ASSUMPTION — carries the energy closure; see §7 |
| `fuel_to_exhaust_flow` | 0.2 | 2.0 | ASSUMPTION — gas volume responds with the fan path |
| `feed_to_exhaust_flow` | 5.0 | 8.0 | ASSUMPTION — calcination gas follows material transport |
| `clinker_to_secondary_air_temperature` | 2.0 | 8.0 | ASSUMPTION — cooler recuperation |
| `clinker_to_cooler_outlet_temperature` | 3.0 | 10.0 | ASSUMPTION — cooler thermal mass |
| `calciner_to_kiln_inlet_temperature` | 4.0 | 12.0 | ASSUMPTION — riser transport |
| `load_to_electrical` | 0.2 | 2.0 | ASSUMPTION — motor load follows process load quickly |
| `load_to_vibration` | 1.0 | 10.0 | ASSUMPTION — mechanical response |
| `load_to_bearing_temperature` | 5.0 | 30.0 | ASSUMPTION — slowest relationship in the twin; sets the 4 h test horizon (§8) |

### 5.2 Cement mill (`mill_dynamics.yaml → delays`)

| Relationship | Dead time | τ | Source / basis |
|---|---|---|---|
| `feed_to_mill_power` | 0.5 | 4.0 | PRD 10.3 |
| `feed_to_differential_pressure` | 1.0 | 6.0 | PRD 10.3 |
| `separator_to_blaine` | 3.0 | 12.0 | PRD 10.3 — sampling + classification |
| `separator_to_throughput` | 2.0 | 8.0 | PRD 10.3 |
| `fan_to_gas_flow` | 0.2 | 2.0 | PRD 10.3 |
| `feed_to_production` | 1.0 | *null* | ASSUMPTION — lag from `mill_holdup_t / throughput` (PRD 10.2) |
| `power_to_outlet_temperature` | 2.0 | 12.0 | ASSUMPTION — grinding heat into mill thermal mass |
| `load_to_electrical` | 0.2 | 2.0 | ASSUMPTION — own instance, not shared with the kiln's row of the same name |
| `load_to_vibration` | 1.0 | 8.0 | ASSUMPTION |
| `fan_to_pressure` | 0.1 | 1.0 | ASSUMPTION |

Replace all of the above with step-test / bump-test identification per relationship; PRD 20.4
requires that the identified dead time be reproduced by the twin.

## 6. Reduced-order gains, gas side and equipment

These are the steady-state sensitivities the delays are applied to. They are *reasoned* from the
equations of PRD 9–10 and public benchmarks, then checked for direction and magnitude by the
PRD 20.1/20.8 tests (`tests/test_causality.py`) — never fitted to data, because there is no data.

**Gain-suffix convention** (`src/process_models/gains.py`, ASSUMPTION — our naming rule, not the
PRD's): `K_per_pct_<x>` is per **relative** percent of the reference value of `x`;
`K_per_pct_point_<x>` is per **absolute** percentage point of `x` (used where `x` is itself a
percentage, e.g. raw-meal moisture); `K_per_K_<x>` is per kelvin of `x`. Mixing the two readings
would silently rescale a gain by a factor of the reference value, so the suffix is load-bearing.

Kiln (`kiln_dynamics.yaml`):

* `gains.burning_zone_temperature.*` — the fuel gains sum to 10.2 K per % of total fuel (+5 %
  fuel at constant feed ⇒ ≈ +51 K BZT), against −9.6 K per % feed. Replace by step tests.
* `gains.CO_ppm.*` — a deliberately **nonlinear** CO/O₂ relationship (PRD 9.4/20.1): CO rises
  steeply as O₂ approaches `O2_floor_pct` (0.6 %). This is why the PRD calls the causality tests
  directional *within a regime* rather than globally monotonic.
* `gains.NOx_ppm.*`, `gains.SO2_ppm.*` — Arrhenius-like thermal-NOx sensitivity
  (`exp_per_100K_BZT` 0.8) and an SO₂ release threshold at O₂ < 1.5 %.
* `gas_and_combustion.*` — the fan/air path: `air_supply_fan_exponent` 1.3 (combined fan curve and
  system resistance), `gas_displacement_factor` 0.15 (calcination gas displacing combustion air at
  constant fan speed), `false_air_fraction` 0.25 entering **downstream** of the back-end O₂
  analyser (published typical 10–30 %), and the primary/secondary/tertiary air shares
  0.10/0.55/0.35. `oxygen_in_dry_air_pct` 20.9 and `normal_temperature_K` 273.15 are physical
  constants, not assumptions.
* `equipment.*` — fan static pressure 100 mbar and efficiency 0.72; motor voltages 6 kV (kiln ID
  fan and mill main drive) and 400 V (separator); vibration and bearing-temperature baselines and
  their load/health gains; `health.*` degradation, Poisson fault arrival (0.02/day), fault
  health drop and recovery. Health is an **input** to the equipment signals, never a hidden fudge
  factor on the process model (PRD 9.5, `test_health_loss_raises_vibration_and_bearing_temperature`).

Mill (`mill_dynamics.yaml`): `gains.mill_power.specific_power_kwh_t_ref` 28.0 kWh/t anchored on
published closed-circuit ball-mill finish grinding (28–42 kWh/t; VRM 18–28 kWh/t), with
`blaine_exponent` 1.3; fan-law exponents 3.0 (power), 2.0 (pressure), 1.0 (flow);
`gains.circulating_load.ratio_ref` 1.8 with `separator_speed_exponent` 1.2; residue exponent 2.5.
The mill is deliberately parameterized to be able to represent either a ball mill or a VRM
(PRD 5.1); no VRM/ball-specific variant exists in v1.1 (PRD 32).

## 7. Transient energy-balance residual

At the reference operating point both closures are **exactly** zero, by construction. During
transients the energy residual is dominated by
`energy_closure_to_preheater_temperature` (1.0 / 4.0 min), which is the relationship that carries
the closure. Measured over 40 minutes after a +10 % kiln-fuel step, with the 1-minute simulation
step of PRD 11.2:

| | Configured delay | Delay reconfigured to instantaneous |
|---|---|---|
| Step the setpoint moves on | 2.763 % | 2.763 % (identical) |
| Next step | 2.763 % | ≈ 0 (< 1e-6 %) |
| Peak after that first step | 2.115 % | 0.037 % |
| Residual accumulated over the horizon | 11.98 | 0.189 |

Two distinct effects, both bounded and both documented rather than tuned away:

1. **The closure delay** — the whole of the decaying transient, and the reason the residual takes
   tens of minutes to return to zero. Removing it collapses the transient by ~60× (integral).
2. **Execution order** (**ASSUMPTION**, PRD 8.3) — on the single step a setpoint moves, the
   rotary kiln reads the preheater gas state one step old, because the preheater is executed
   *after* the kiln. This term is identical with and without the closure delay, and disappears on
   the following step. Removing it would require an iterative within-step solve, which PRD 8.3's
   sequential-unit architecture does not specify.

The worst case stays inside `unaccounted_loss_max_fraction` (3 %) across the horizon, which is
what NFR-10 requires and what `test_kiln_energy_balance` asserts; the settled tail is required to
be < 1e-3 %, so a *persistent* offset — a balance being reported rather than enforced — fails.
`test_transient_energy_residual_is_dominated_by_the_closure_delay` pins all of the above.

Over a whole generated horizon these same two effects are excited by regime ramps far wider than
the +10 % fuel step measured here, and the pointwise percentage then needs to be read regime by
regime. §11.5 is that methodology; the settling window it uses — `dead_time + 4τ` of the closure
relationship above, 17 min — is derived from this table's delay and from nothing else.

## 8. Documentation-range deviations

PRD 11.4 and 12.1 are explicit that the documented ranges are *process-reasoned ASSUMPTIONs*, and
that the model must never be silently clamped to them. Where a PRD 12.1/12.2 band cannot hold
simultaneously with the PRD 9–10 equations, **the physics is kept and the deviation is documented
here** — the alternative (bending a coefficient to land inside a band) would be exactly the
"silently invent a different number" the PRD forbids.

### 8.1 Kiln fuel rates

| Tag | PRD 12.1 band | Reference value | Why |
|---|---|---|---|
| `kiln_fuel_rate_tph` | 3.2–5.2 t/h | 6.219 t/h | Solved from the energy balance |
| `calciner_fuel_rate_tph` | 4.0–7.5 t/h | 9.328 t/h | Solved from the energy balance |

The four PRD statements — clinker 95–150 t/h (12.1), clinker factor 0.63 (9.3), LHV 26 MJ/kg (9.2)
and specific heat consumption 700–950 kcal/kg (12.1) — cannot all hold with the fuel bands:
119.7 t/h clinker at 807 kcal/kg needs 15.55 t/h of 26 MJ/kg fuel, against a fuel-band maximum of
12.7 t/h (which would imply ≈ 660 kcal/kg, below the PRD's own band). The energy balance and the
specific-consumption benchmark are kept; the absolute fuel bands are not. Consequently the fuel
`operating_ranges` in `kiln_dynamics.yaml` are expressed as **ratios** of the derived reference
rates (0.80–1.20) rather than as absolute t/h.

### 8.2 Kiln air and exhaust flows

| Tag | PRD 12.1 band | Reference value |
|---|---|---|
| `primary_air_flow` | 15,000–25,000 Nm³/h | 12,086 |
| `secondary_air_flow` | 90,000–140,000 Nm³/h | 66,472 |
| `tertiary_air_flow` | 60,000–100,000 Nm³/h | 42,301 |
| `exhaust_gas_flow` | 250,000–400,000 Nm³/h | 199,248 |

All four follow from one quantity: combustion air = fuel energy × `stoichiometric_air_Nm3_per_MJ`
(0.26) × `excess_air_ratio` (1.15) = 120,859 Nm³/h, split 10/55/35 %. Raising `excess_air_ratio`
until those bands are reached takes λ ≈ 1.45 (secondary air 89,143 Nm³/h, exhaust 250,773 Nm³/h) —
at which point back-end O₂ is **5.39 %**, well outside the PRD's own 0.7–4.0 % band; even λ = 1.30
already gives 3.91 % while still leaving every flow below its band. The O₂ band and the
stoichiometry are kept; the flow bands are treated as belonging to a larger and leakier line than
the one these coefficients describe. The tag values remain mutually consistent (air split, false
air, exhaust flow and the ID-fan power/current all derive from the same figure).

`id_fan_motor_voltage_V` = 6000 is not a deviation but a *derived* choice: 6 kV is the
medium-voltage level that keeps `ID_fan_current` (201.7 A at reference) inside the PRD 12.1 band
100–260 A at the ≈ 1.78 MW reference shaft power. PRD 12.1 documents no voltage band.

### 8.3 Excursions outside a band are permitted, by design

`separator_current` sits at 59.4 A at reference (PRD 12.2 band 30–80 A) and reaches **84.29 A**
when the separator is held 15 % above reference — outside the documented band. This is the
intended behaviour: PRD 11.4 needs the abnormal regimes to actually leave the normal envelope, and
`test_constraints_are_ranges_not_clamps` / `test_kiln_is_not_clamped_to_its_documented_ranges`
assert that no documented range acts as a limiter. The optimizer's envelope (Section 14) is the
layer that refuses to *recommend* such a point; the twin will still simulate it.

## 9. Structural assumptions

* **Kiln and mill are decoupled** (PRD 8.3, verbatim ASSUMPTION): "real plants buffer clinker
  through a storage silo, decoupling kiln and mill dynamics on the minute-to-hour timescale
  relevant here." `PlantTwin` therefore composes two independent lines and owns only the joint
  view; `test_plant_does_not_couple_the_kiln_to_the_mill` asserts that a +25 % kiln-fuel
  disturbance leaves the mill line bit-for-bit identical. Tight kiln→mill coupling is a Phase-2
  roadmap item (PRD 32).
* **Sequential unit execution** within a line (PRD 8.3 order), with no iterative within-step
  solve — see §7 for the one measurable consequence.
* **The plant-level `mass_pct` residual** is reported as the worse of the two lines' mass
  closures, and `energy_pct` as the kiln's (the mill model defines a mass closure only, PRD 10.2 —
  publishing a fabricated mill `energy_pct` would be a false claim).
* **`specific_thermal_energy_kcal_per_kg` returns 0.0 at zero clinker production** rather than
  `inf`, so the tag stays finite through a startup ramp (PRD 11.3 startup regime).

## 10. Test-harness assumptions

* `HORIZON_MINUTES = 240` (`tests/conftest.py`, **ASSUMPTION**): 4 h covers the slowest configured
  relationship (`load_to_bearing_temperature`, τ = 30 min) several times over, so a conservation
  test that passes over this horizon has seen the full transient settle.
* `STEP_SECONDS = 60.0`: the PRD 11.2 sampling interval.
* Both closure tolerances are read from config by fixture (`unaccounted_loss_max_fraction`,
  `mass_balance.tolerance_pct`) and never hard-coded in a test, so tightening the configured bound
  tightens the tests with it.
* `HORIZON_DAYS = 3.0` (`tests/test_data_generator.py`, **ASSUMPTION**): long enough for the
  scheduler to visit all 14 PRD 11.4 regimes plus the startup ramp, short enough to keep the
  module inside a few seconds.
* `HORIZON_DAYS = 1.0` (`tests/test_conservation_validation.py`, **ASSUMPTION**): the NFR-10
  methodology tests need all three validation regimes of §11.5 populated, not all 14 regimes. One
  day yields 1,010 settled / 355 transient / 75 startup rows with many separate transient episodes,
  and is cheap enough to re-run per test with a deliberately broken closure.
* The four `energy_balance.residual_validation` numbers are read from config by
  `ValidationBounds.from_config` and never hard-coded in a test, and a config missing the block is
  an error rather than a silent default (§11.5).

## 11. Data pipeline (PRD 11.2–11.6, 12)

### 11.1 What leaves the generator

`DatasetGenerator.run()` is a pure function of the configs and the seed — no wall-clock, no global
RNG, no filesystem access (`src/data_generation/export.py` does the writing). Three conventions
follow from PRD 11.2/12 and are asserted in `tests/test_data_generator.py`:

* **The warm-up window never leaves the module.** `start_timestamp` is the *first exported*
  sample, so the settling window occupies negative time. The sensor model runs on the exported
  rows only, so `warmup_minutes` cannot shift a single measured number — the strict form of NFR-4:
  two runs differing only in warm-up length produce **equal frames**, not merely similar ones.
* **`commanded` is what the instruments see.** Regime 8's unmeasured feed disturbance and PRD
  11.3's fuel-quality swing are invisible to the DCS by definition, so the twin is driven with
  `schedule.inputs` while the dataset's setpoint-feedback tags carry `schedule.commanded`. The
  driven values survive in the ground-truth frame, which is what makes those events
  learnable-but-unlabelled the way a real unmeasured disturbance is.
* **Ground truth is a separate file, never an extra column.** PRD 12.1/12.2's column tables end at
  `injected_fault`, so the noise-free state, the PRD 9.5 health scalar and fault flag, the
  unmeasured disturbances (`ambient_temperature_C`, `feed_moisture_swing_pct_abs`,
  `fuel_lhv_swing_pct`) and the episode bookkeeping go to `*_truth.{csv,parquet}` beside the
  dataset (PRD 34 item 2: models are evaluated against the simulator's own true state).

The debug variant of PRD 12.1 appends only the residuals a unit actually closes: two columns for
the kiln, **one** for the mill, because PRD 10.2 gives the mill a mass balance and no energy
balance. Publishing a fabricated mill `energy_pct` would be a false claim (cf. §9).

### 11.2 Scenario scheduler (PRD 11.3, 11.4)

Regime setpoints are stored as **ratios of the reference operating point**, never as absolute
tonnes or rpm, so re-anchoring `kiln_dynamics.yaml`'s reference point cannot silently push a regime
outside the PRD 6 operating band. Every ratio's inline comment carries the absolute value it
resolves to today and the PRD band it sits in.

* **Episode ordering** is `share_deficit` (**ASSUMPTION**): the scheduler repeatedly picks the
  regime with the largest remaining share deficit and draws its length uniformly from
  `dwell_hours`. This is deterministic for a given seed and self-correcting, so the realized regime
  mix converges on the configured `share` without a random-choice tail that could omit a regime on
  a short horizon — FR-3 requires all 14 to be present.
* **The shares sum to exactly 1.00** (0.14 + 0.16 + 0.14 for the three normal regimes, 0.05 for
  each of the eleven off-normal ones, 0.01 for the startup ramp). The startup ramp is *not* one of
  the 14: it is the PRD 11.4 trailing-paragraph transition, labelled `Startup transition`, and
  `configs/ml.yaml training.drop_startup_regime` excludes it from steady-state windows by default.
* **Ramp times** are 3–15 min (`ramp_times_min`, **ASSUMPTION** per PRD 11.3's stated window),
  fastest for VFDs and drives and slowest for the upstream raw-meal properties, which are
  disturbances rather than commands. `mill_speed` is held at the 3-min floor rather than below it
  even though no regime moves it.
* **`affects` splits the two label columns.** `operating_regime` is the plant-level label on *both*
  datasets (FR-3), while `injected_fault` is set only on the unit the regime actually perturbs, so
  the PRD 22 precision/recall figures are not diluted by rows where the labelled fault is happening
  in the other building.
* **Regime 14 ("Sensor drift") carries `sensor_layer_only: true`.** The process stays normal and
  the bias ramp is applied by the sensor model. That separation is the whole point of the PRD 34
  check that Model B can tell an instrument fault from a process fault.
* **Disturbances arrive by Poisson process** (`feed_moisture_swing` 6/day, `fuel_quality_swing`
  3/day, both **ASSUMPTION**) independently of the regime schedule, so a record contains
  unlabelled-but-learnable structure the way real historian data does. Ambient temperature is a
  diurnal sine (6 K amplitude) plus a 1.5 K/day random walk.

### 11.3 Sensor model (PRD 11.5)

Applied in the PRD 11.5 order — measurement lag → drift bias → Gaussian noise → quantization →
stuck/frozen → dropout — on the **exported** rows only, which is what makes the NFR-4 warm-up
invariant of §11.1 hold. Measurement lag is *separate from and additional to* the process delays
of PRD 9.4/10.3: the first is a transmitter, the second is the plant.

* **Noise is specified against the tag's documented range**, not as a bare sigma:
  `noise_pct_of_range` 1.0 % default (**ASSUMPTION**, PRD 11.5's "≈1–2 % of nominal"), with
  `noise_absolute` and `noise_pct_of_value` overrides where an instrument class behaves otherwise.
  The single source of every range is `src/schema.py`; the sensor config never repeats one.
* **Gas analysers are noisier at low concentration** — PRD 11.5 calls this out explicitly — so
  `CO_ppm` carries a proportional term (8 % of value) on top of a floor, and all analysers get a
  45–60 s lag.
* **Lab-style quality proxies** (`simulated_blaine_cm2_g`, `residue_percent`) get coarse
  quantization and a 300 s lag (**ASSUMPTION**): a laboratory turnaround standing in for an online
  analyser. Actuator feedbacks are measured almost exactly (5 s, tiny sigma) because a DCS reads
  its own drive back.
* **Quantization steps** are the display resolution of the instrument class (0.01 % O₂, 1 ppm,
  1 K, 0.1 mbar, 10 cm²/g). They are the reason `%.6g` is safe as a CSV float format (§11.4).
* **The drift bias ramp is linear over the episode** to a configured end-of-episode offset per tag
  (**ASSUMPTION**: 0.45 % O₂, 18 K BZT, 120 cm²/g Blaine, 6 mbar mill dP) and is applied *only*
  inside regime 14.
* **Stuck/frozen transmitters are an addition to PRD 11.5**, which does not list them. FR-13
  requires the data-quality report to detect frozen signals, so the generator has to be able to
  produce them: Poisson arrival at 0.02/day/tag with a 15–180 min hold (**ASSUMPTION**). This is
  recorded here as a deliberate, documented superset of PRD 11.5 rather than a silent extra.
* **Dropouts are the only NaNs in a dataset** (0.2 %/sample default, inside PRD 11.5's 0.1–0.5 %
  band). The ground-truth frame has none, except `injected_fault`, which is null on every row where
  nothing is injected — that is an absent label, not a missing measurement, which is why
  `tests/test_data_generator.py` counts it separately before comparing against the sensor model's
  own tally.

### 11.4 Export (PRD 11.6)

CSV `float_format` is `%.6g` (**ASSUMPTION**): far finer than any PRD 11.5 quantization step, so a
measured number cannot be lost, while keeping the file free of 17-digit binary-rounding noise that
would make two identical runs *look* different. CSV timestamps are ISO-8601 UTC to whole seconds.
The JSON sidecar is written with sorted keys and carries no wall-clock, so two runs of one seed
produce byte-identical sidecars and a seed-regression test can diff them.

### 11.5 The energy residual over a generated horizon — the three validation regimes

NFR-10 asks for ±3 % "across the full simulated horizon". The **requirement is unchanged**; what
this section fixes is the *statistic* it is read with. Taken as a pointwise percentage of the
instantaneous energy input, that one statistic is not well defined everywhere on a PRD 11.3/11.4
schedule, for two reasons that have nothing to do with whether the balance closes:

1. **The denominator is not always a valid scale.** PRD 11.4's startup transition ramps fuel and
   feed up from zero, so the input basis falls to a fraction of the operating point (measured
   minimum: **23.55 %** of the reference basis, its floor being the recovered cooler heat) while the
   accounted output terms are still sized for the operating point the kiln is leaving. The ratio
   then reports the *mismatch of two operating points*, magnified by a shrinking denominator.
2. **A delay transient is not a steady-state offset.** After a setpoint move the accounted outputs
   lag the inputs by the configured `energy_closure_to_preheater_temperature` dead time and time
   constant (§7). Energy is redistributed in *time*; the honest statistic over such a window is an
   integral, not the worst single step.

So the horizon is judged in three regimes, each by a statistic that is numerically valid there.
The implementation is `src/data_generation/conservation.py`; the methodology's own tests are
`tests/test_conservation_validation.py`.

| Regime | Rows are in it because | Governing statistic | Bound | Measured (seed 20240101, dt 60 s, warm-up 180 min) |
|---|---|---|---|---|
| **Settled / normal operation** | neither of the below | peak \|residual\| ÷ **instantaneous** input | `unaccounted_loss_max_fraction` — the unchanged **3 %** | **0.8510 %** (3-day) / **0.8550 %** (30-day) |
| **Transient / setpoint change** | a driven kiln input moved on this step or within the settling window `dead_time + 4τ` of the closure relationship = **17 min** | ∫\|unaccounted\| ÷ ∫input, over the regime **and per episode** | the same unchanged **3 %**, applied to the integral | aggregate **0.3668 %** / **0.3665 %**; worst single episode **2.7907 %** |
| | | peak \|residual\| ÷ instantaneous input | `transient_peak_max_fraction` = 20 % — a bound on the *peak of a transient*, not on steady-state closure | **12.1027 %** / **12.1029 %** |
| **Startup / near-zero input basis** | the scheduler's `is_startup` label, **or** an input basis below `near_zero_input_fraction` = 30 % of the reference basis | peak \|unaccounted\| ÷ the **reference** input basis (533,822.7 MJ/h, fixed and non-zero) | `startup_reference_max_fraction` = 60 % | **44.7332 %** (peak absolute loss 238,796 MJ/h) |
| **Whole horizon**, nothing excluded | — | ∫\|unaccounted\| ÷ ∫input over every exported row | the same unchanged **3 %** | **0.3198 %** (3-day) / **0.1518 %** (30-day) |

Four properties make this a sharpening of NFR-10 rather than a relaxation of it:

* **Classification is by cause, never by outcome.** A row is never moved out of `settled` because
  its residual is large. `classify()` does not take the residual as an argument at all — the regimes
  are decided by the schedule (a startup label, a driven input that moved) and by the input basis;
  `test_the_classifier_cannot_see_the_residual_it_is_classifying` pins that structurally.
* **The horizon-wide claim survives intact**, in the one form that is valid on every row: the
  energy-weighted integral over the whole export, startup rows included, against the same 3 %. At
  0.15–0.32 % it has two decimal orders of headroom.
* **The settled bound does not depend on the transient window.** Collapse the window to a single
  simulation step — the PRD 8.3 execution-order term alone, no settling tail — and the settled peak
  is still inside 3 % (**2.4412 %** at 3 days, **2.6719 %** at 30 days).
  `test_the_settled_bound_holds_without_the_delay_tails_help` asserts exactly that.
* **A genuine regression still fails.** Raising the closure's numerical floor
  `min_preheater_outlet_temperature_C` from 150 °C to 450 °C — above the reference outlet of 360 °C,
  so the exhaust-loss term no longer matches what the balance computes — breaks the settled peak
  (7.15 %), the transient integral, the worst episode *and* the horizon integral. Widening the
  transient window to 9τ does not rescue it. Injected drifts are caught the same way, including one
  confined to the startup rows: that regime has an absolute bound and it bites.

**Why the percentage metric is invalid in the startup regime.** The peak instantaneous-basis
percentage on those rows is **184.1378 %**, and it is still *reported* — `peak_relative_pct` stays
in the JSON beside the bound it would fail — but no check is formed on it. The number is an
arithmetic artefact of the ratio, not a conservation failure: the absolute unaccounted loss peaks at
238,796 MJ/h, which is 44.7 % of the *reference* input basis and shrinking, while the instantaneous
denominator is simultaneously falling to 23.55 % of that basis. Dividing a residual sized by the
outgoing operating point by an input basis sized by the incoming one measures the transition, not
the closure. The reference basis is the fixed alternative: it is the already-solved PRD 9.3
reference point's own energy input (`src/process_models/kiln_reference.py`), so using it introduces
**no new physical coefficient**.

**Nothing physical changed.** The four methodology numbers live in
`kiln_dynamics.yaml → energy_balance.residual_validation` and are **ASSUMPTION**s that decide only
how a row is *judged*; none enters an equation. Deleting the block, or replacing all four values,
leaves the trajectory bit-for-bit identical (`test_the_validation_block_changes_no_physical_number`).
Three of the five bounds are the pre-existing `unaccounted_loss_max_fraction` reused; the settling
window is derived from the configured closure delay; the startup denominator is the reference point.
The two genuinely new bounds are `transient_peak_max_fraction` (0.20, observed 0.121) and
`startup_reference_max_fraction` (0.60, observed 0.447) — both bound quantities that the previous
methodology bounded with *nothing at all*.

**Mass conservation is unchanged**: PRD 9.3/10.2's mass balances are exact discretizations, so they
keep their single metric (peak relative residual against `mass_balance.tolerance_pct`) on **every**
row, startup included, and stay at machine precision — kiln ≤ 1.0e-10 %, mill ≤ 2.0e-13 %.

*Superseded by this section: the earlier note that the startup denominator "collapses toward zero"
behind "an 8-minute dead time". Both details were wrong. The basis floors at 23.55 % of reference
rather than at zero, and the delay that carries the closure is
`energy_closure_to_preheater_temperature` (1.0 / 4.0 min); the 8-minute figure belongs to
`feed_to_burning_zone_temperature`. The earlier 2.83 % settled figure was a 5-day measurement made
with a one-step transient window and is superseded by the table above.*

### 11.6 FR-13 data-quality thresholds

All six FR-13 checks live in `src/data_processing/quality.py` with every threshold as a module
constant, because PRD 21 re-runs this same report on the factory's real data. Each is an
**ASSUMPTION**:

| Constant | Value | Reasoning |
|---|---|---|
| `MISSING_WARN_FRACTION` / `MISSING_ERROR_FRACTION` | 0.005 / 0.05 | PRD 11.5's configured dropout rate is per-tag and small; 0.5 % is above noise, 5 % means a tag is unusable for training |
| `CONSTANT_RELATIVE_RANGE` | 1e-9 | A dead tag, distinguished from a merely quiet one by relative range |
| `STUCK_MIN_RUN` | 30 samples | 30 min of a perfectly unchanging reading at the PRD 11.2 interval — no noisy analogue instrument does this, though a quantized integer tag legitimately can, so the run length is reported rather than judged |
| `SPIKE_MAD_THRESHOLD` | 8 σ_MAD **of the first difference** | Far outside the PRD 11.5 Gaussian band. Differencing is what separates a one-sample glitch from a legitimate ramp, which moves the level a long way one small step at a time |
| `DRIFT_WINDOW_FRACTION`, `DRIFT_WARN_SIGMAS` / `DRIFT_ERROR_SIGMAS` | 0.1, 3 / 6 σ | Head-vs-tail median shift in robust σ. On a multi-regime record a regime change also shows here — FR-13 is a *report*, not an alarm |
| `SYNC_INTERVAL_TOLERANCE` | 1 % of the modal interval | Catches clock skew, a lost historian connection (one long gap) and a resampled section (many short ones) |

Robust (MAD-based) scale is used throughout rather than the sample standard deviation, because the
defects being looked for inflate the latter and would then hide themselves — a spike raising its
own detection threshold. The report describes and counts; it never repairs. On synthetic data it
is *expected* to fire: a clean report on a generated dataset would mean the PRD 11.5 sensor model
was not running.

**The two label columns are excluded from the per-column checks by default**
(`DEFAULT_EXCLUDED_COLUMNS`). `injected_fault` is null on every row where nothing is injected —
about two thirds of a healthy record — and that is an *absent label*, not a lost reading. Counted
as a missing-value fraction it clears `MISSING_ERROR_FRACTION` on every dataset and outranks every
real instrument finding in the report. A real-plant caller with no label columns passes
`exclude=()`, which is also how `tests/test_data_quality.py` pins the distinction.

**What the shipped 30-day dataset reports** (seed 20240101, 43 200 rows) — worst severity
`warning`, no errors, on both datasets:

| Check | Kiln | Mill | Reading |
|---|---|---|---|
| `missing_values` | 34 tags | 22 tags | PRD 11.5 dropouts, ≈0.25 % per tag: all `info` |
| `constant_sensors` | 13 tags | 9 tags | All `stuck_run`, 33–170 samples: the configured 0.02/day/tag frozen transmitters. No tag is dead |
| `spikes` | 15 tags | 9 tags | See below |
| `duplicates`, `sync` | 0 | 0 | A generated clock is regular and monotonic by construction |
| `drift` | 0 | 0 | On a 30-day extract the head and tail windows each average over many regimes, so the regime-14 bias episodes wash out of a head-vs-tail statistic. They *are* visible on a short extract (a 2-day run reports them), which is the honest limitation of a net-shift test rather than a defect |

Three tags dominate the spike count and none of them indicates a broken instrument: `ID_fan_speed`
and `fan_speed` (≈3.8 % of samples) are regime 7's fan-instability burst, which *is* per-sample
noise superimposed on a fan speed; `CO_ppm` (≈17 %) is the deliberately nonlinear CO/O₂
relationship of §6 — CO rises steeply near the 0.6 % oxygen floor, so its step-to-step
distribution is heavy-tailed and a robust threshold flags its tail. The spike check is therefore
capped at `warning`, and the threshold was left at 8 σ_MAD rather than raised until the synthetic
data looked clean.

## 12. ML layer (PRD 13.1–13.3, 22)

Every configured number for this layer lives in `configs/ml.yaml`, each marked `ASSUMPTION` on its own
line; that file is the reference and is not restated here. This section records what was *discovered*
while building and testing the layer: one implementation defect, one limit on what the holdout purge
can guarantee, one reproducibility caveat, and one PRD-versus-implementation inconsistency.

### 12.1 `window_touches` orientation — a defect found and fixed

The helper that widens a boolean flag into the window `[i - back, i + forward]` originally padded the
two sides the wrong way round. Both call sites — the PRD 11.4 startup exclusion and the PRD 13.3
scenario-holdout purge — pass `back=max_lag_steps, forward=horizon_steps`, which are equal only when
the longest lag equals the horizon. At t+30 min with a 15-minute longest lag the purge therefore
reached 15 minutes forward and 30 back instead of 30 forward and 15 back, leaving part of the label
window unpurged.

Fixed in `src/features/lag_features.py`, and pinned *asymmetrically* by
`tests/test_features_ml.py::test_window_touches_marks_the_whole_lag_and_horizon_window`: with
`back == forward` an inverted pad is invisible, which is how it survived the first version of that
test. Every number in `MODEL_CARD.md` and `reports/metrics/` was regenerated after the fix.

### 12.2 What the scenario-holdout purge can and cannot guarantee

`scenario_holdout_split` flags the withheld regimes among the **retained** rows of the feature matrix
and purges every row whose `[t - max_lag, t + h]` window touches one. Three statements follow, and all
three are checked exhaustively in `tests/test_ml_leakage.py`: no training row carries a withheld
regime label; no training row's label is an observation from inside a withheld regime; no training
row's lag columns read a minute from inside a withheld regime.

**The residual, as an ASSUMPTION.** The purge can only see withheld minutes that survived into the
matrix. A withheld minute dropped earlier — a PRD 11.5 dropout hole, or a row whose own label was
missing — is invisible to it, and a nearby training row's lag column may still read that minute's
tags. Such a minute enters as an *input* observation, never as a withheld label paired with its own
features, so it cannot inflate the holdout metrics; it is a caveat on the phrase "never trained on",
not a leak. Left as it is rather than fixed by re-deriving the purge over source rows, which would
withhold training rows on account of minutes the model layer never sees.

### 12.3 Reproducibility under `models.random_forest.n_jobs: -1`

NFR-4 asks for reproducible runs. Measured on this stack (scikit-learn 1.9.0, joblib 1.5.3, numpy
2.5.1), two runs from the same seed:

| Quantity | Result |
|---|---|
| Fitted tree structure (`estimators_` thresholds, split features, leaf values) | **bit-identical** |
| Feature matrices, splits, SPC statistics, isolation-forest scores | **bit-identical** |
| `RandomForestRegressor.predict` | differs by ≈3.6e-15 |

The prediction difference is not model drift. A *single* fitted forest differs from itself by the same
≈3.6e-15 between two of its own `predict` calls, because each tree's contribution accumulates into one
shared array in whatever order the workers finish, so the summation order varies. With `n_jobs: 1` it
is exact.

`n_jobs: -1` is kept. The difference is many orders of magnitude below the PRD 11.5 sensor resolution
and cannot appear in a reported metric, and editing a config to make a test pass is the wrong
direction of causation. `tests/test_model_a.py` therefore asserts tree-structure equality *exactly*
and compares derived floats at `rel=1e-12` (`REPRODUCIBILITY_RTOL`), with this measurement written
down beside the constant.

### 12.4 Which Model B method decides

PRD 13.2 names the isolation forest "Method 1 (primary)" and SPC as the secondary, always-on layer.
The headline decision — the PRD 15 banner, the PRD 22 detection metrics and the PRD 14.3 OOD gate — is
therefore the forest alone, at two thresholds of the same score (`ood_threshold < flag_threshold`, so
the two decisions are strictly nested and the gate is the stricter one).

The three decisions the banner could have been are scored on the same rows on every run and published
under `detection["alternates"]`: `spc_single_sample` (method 2 alone), `forest_or_spc_single_sample`
(the union of the two configured methods) and `out_of_distribution_gate` (the same forest score at the
gate percentile). `MODEL_CARD.md` prints them as a table and derives its verdict sentence from those
numbers, so a run in which the union actually won would say so rather than repeat this one's
conclusion. Because the union flags a superset of the forest's rows, its false-positive rate can never
be lower; what the extra flags buy in recall is a per-run measurement, printed in `MODEL_CARD.md`
rather than asserted here. An earlier development measurement tried a 4-of-7 SPC run rule inside the
union instead of a single-sample violation; it reached the same conclusion, and that rule is not in the
codebase, so the published comparison uses the two methods that are.

The startup ramp is excluded from the headline detection metrics and reported in its own
`startup_ramp` block. It carries no `injected_fault` label, so counting it as a negative would score
the detector for not alarming during a scripted 75-minute transient in which almost every tag is
legitimately far from its normal-operation range.

### 12.5 Sensor drift (PRD 11.4 regime 14) is not separable — an open inconsistency

PRD 13.2 and PRD 15 ask Model B to distinguish a *sensor/data* anomaly from a *process* anomaly, and
PRD 11.4 provides regime 14 (`sensor_layer_only: true`) as the case that tests it. Measured on the
generated data, the three configured signatures (run-rule monotonicity, quiet manipulated variables,
few corroborating tags) do not separate the two: scored as a classifier over every fault row carrying
control-chart evidence, precision does not clear the base rate of those rows by more than sampling
noise, and the base rate is the threshold a rule has to beat to carry any information at all. On the
shipped 30-day run that is P = 0.152 against a 0.147 base rate over 4,276 called rows (kiln — an
excess of 0.005 inside a ±0.011 two-sigma band) and P = 0.144 against a 0.144 base rate over 4,696
called rows (mill). The comparison in the generated card uses that two-standard-error margin
deliberately: a bare `precision > base_rate` inequality would read the kiln's 0.005 as the rule having
become informative.

Method 1 compounds it: the forest barely detects regime 14 in the first place — 6 of 2,081 drift rows
on the kiln and 66 of 2,093 on the mill on that same run — so on the rows an operator actually sees a
banner for, the discriminator has almost nothing to work with. Those figures are duration-dependent
(a 3-day run gives 0 of 328 and 31 of 329, and a different rule score), which is why **the numbers
above are a snapshot and `MODEL_CARD.md` is the authority**: the card's regime-14 limitation and its
*Sensor-versus-process discrimination* table are generated from the run being carded, including the
verdict sentence, so a run on which the rule became informative would say so instead of repeating this
paragraph.

The implemented behaviour is therefore `report_sensor_claim: false`: the report states that the
evidence is inconclusive rather than naming a reading it cannot support, which is what PRD 15's
"Likely cause (model-based hypothesis)" wording requires. The separation is still *measured* on every
run and published, so the claim is falsifiable rather than hidden.

**This is reported as an inconsistency, not resolved unilaterally.** Two changes would plausibly fix
it, and both are outside what the ML task authorises:

- raising the configured regime-14 drift magnitudes in `configs/scenarios.yaml` — that changes the
  synthetic data-generation assumptions;
- adding the PRD Phase-2 redundancy/autoencoder method — that adds scope beyond PRD 13.2's two
  configured methods.

Nothing in `configs/scenarios.yaml` was changed to improve the number, and no metric was tuned against
it.








