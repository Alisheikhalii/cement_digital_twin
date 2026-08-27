# DATA_DICTIONARY.md

> This is a synthetic demonstration environment. The simulation is not calibrated against a real
> cement plant. Every "typical range" below is a **process-reasoned ASSUMPTION**, not a measurement
> of any plant.
> — PRD v1.1.1 Section 31

**Audience:** process engineers, IT/OT engineers (PRD Section 35).

**Purpose:** PRD 35 requires one document carrying the full Section 12 tables, **one row per tag**,
recording **which rows are `ASSUMPTION`-derived**, plus **the canonical-unit fuel-energy conversion
of Section 9.2**. This file is that document.

**Source of truth.** Every row below is derived from `src/schema.py`, which the PRD 8.5 single-
source-of-truth rule makes the *only* place a column may be declared. The generator builds its
DataFrames from it, the sensor model sizes noise from its ranges, the dashboard reads its units, and
the Section 34 schema test compares generated columns against it. Nothing in this file is
hand-entered independently of that module: if a row here and `src/schema.py` disagree, **the module
is right and this file is stale**.

---

## 1. How to read these tables

`src/schema.py` declares each column as a frozen `TagSpec`. The table columns map onto its fields:

| Column here | `TagSpec` field | Meaning |
|---|---|---|
| Tag | `name` | The exact column name in the Parquet export. |
| Unit | `unit` | Native unit of the stored value. Never converted silently on the way to a panel. |
| Process unit | `process_unit` | Which physical section of the line the tag belongs to. |
| Role | `role` | What the tag *is* to the models (see §1.1). |
| Documented range | `range_min`–`range_max` | The PRD 12 "typical range" band. **See §1.2 — this is not a limiter.** |
| Type | `dtype` | `float`, `datetime` or `string`. |
| Provenance | `assumption` | `ASSUMPTION`, `ground truth` or `clock` (see §1.3). |
| Importance | `importance`, `mandatory` | What PRD 27.1 asks the factory to prioritise. |

**Sampling interval.** `TagSpec.sampling_interval` is a per-tag field, and it is **`1 min` for all
62 tags** in v1.1 — the native simulation step. It is therefore stated once here rather than
repeated down a column of identical values. PRD 26.3 resampling is the layer that changes it for
real sources.

**Counts.** 37 kiln columns + 25 mill columns = **62 tag specs**. `timestamp`,
`operating_regime` and `injected_fault` deliberately appear in *both* datasets, so the global index
in `schema.py` is keyed by `(dataset, name)` and `get_tag(name)` needs a `dataset` argument to
disambiguate those three.

### 1.1 Roles

| Role | Count | What it means |
|---|---|---|
| `index` | 2 | The timestamp column. |
| `manipulated` | 12 | An operator/DCS **setpoint** — a lever the optimizer and What-if may move (PRD 9.1 / 10.1). |
| `disturbance` | 2 | An upstream condition that changes, but **not** an operator lever. |
| `process` | 23 | Measured process state. |
| `quality` | 2 | Product-quality indicator. |
| `emission` | 4 | Stack / back-end gas concentration. |
| `equipment` | 10 | Equipment/health variable (PRD 9.5). |
| `derived` | 3 | Computed from the canonical balance (PRD 9.2 / 9.3) — not independently simulated. |
| `label` | 4 | Simulation ground truth. **A real plant would not supply these.** |

`manipulated` is the set the What-if engine and the optimizer are allowed to move; query it in code
with `schema.manipulated_variables(dataset)` rather than re-listing it.

### 1.2 A documented range is a range, not a clamp

The bands below size the sensor model's noise and drive the dashboard's status banding. They are
**not** enforced as limits. PRD 11.4 requires the abnormal regimes to genuinely leave the normal
envelope, and two frozen-layer tests —
`test_constraints_are_ranges_not_clamps` and `test_kiln_is_not_clamped_to_its_documented_ranges` —
assert that no documented range ever acts as a limiter. Tags marked *"spikes under fault"* below
are the ones the PRD explicitly expects to exceed their band.

Consequently **some tags sit outside their own documented band at the reference operating point.**
That is a known, deliberate, documented deviation, not a defect — §5 records every case and the
reasoning, and `SIMULATION_ASSUMPTIONS.md` §8 is the authority.

### 1.3 Provenance — what `ASSUMPTION` means here, and what it does not

PRD 35 asks specifically which rows are `ASSUMPTION`-derived. `TagSpec.assumption` answers it, and
**56 of the 62 tags are `assumption=True`**. The six that are not are *not* measurements:

| Provenance | Tags | Reading |
|---|---|---|
| `ASSUMPTION` | the other **56** | The *documented range* is a process-reasoned band for a mid-size precalciner kiln (~3,000–4,000 tpd) and a generic closed-circuit cement mill. Grounded in the Sections 9–10 equations and public cement-engineering benchmarks; **not** measured. Replace by calibration against real historian data (PRD 21/26/27). |
| `clock` | `timestamp` (kiln, mill) | The simulation clock. Carries no engineering range to assume. |
| `ground truth` | `operating_regime`, `injected_fault` (kiln, mill) | **Simulator ground truth: a real plant would not supply this.** `assumption=False` because there is no range to assume — *not* because the value is measured. These four columns exist so PRD 22 can score Model B against a known answer, and they must never be treated as an available real-plant input. |

So: `assumption=False` means **"this row has no process-reasoned numeric band"**, never "this row is
measured". **No column in this dataset is a measurement of a real plant.** The honest summary is
that all 62 are synthetic; 56 additionally carry an assumed engineering range.

---

## 2. Canonical fuel-energy conversion (PRD 9.2) — required by PRD 35

All internal thermal energy is **megajoules (MJ)**; all thermal power is **MJ/h**. `kcal/kg` exists
**only** as a display unit, on `thermal_energy_kcal_per_kg_clinker` and its duplicate
`specific_fuel_consumption`. The single sanctioned conversion constant is
`MJ_PER_KCAL = 4.184e-3`, defined once in `src/process_models/fuel.py`.

```
mj_to_kcal(x_MJ) = x_MJ / 4.184e-3
```

**Mass-based and volume-based heating values are never added in native units.** Each fuel stream is
converted to MJ/h first; `test_fuel_energy_unit_consistency` (PRD 34) asserts that no code path
violates this.

```
thermal_input_MJ_per_h = kiln_fuel_rate_tph     * 1000 * lhv_solid_fuel_MJ_per_kg
                       + calciner_fuel_rate_tph * 1000 * lhv_solid_fuel_MJ_per_kg
                       # + a gas stream via lhv_gas_fuel_MJ_per_Nm3, if/when one is configured

thermal_energy_kcal_per_kg_clinker = mj_to_kcal(thermal_input_MJ_per_h)
                                     / (clinker_production_tph * 1000)
```

That last line is the **only** place the display unit is derived. It is never re-derived elsewhere.

### 2.1 The heating values, and their auditable derivation

Both live in `configs/kiln_dynamics.yaml` under `fuel:`, both tagged `ASSUMPTION`, both documented
in `SIMULATION_ASSUMPTIONS.md` §1.

| Config key | Default | Derivation shown for auditability | Published range | Status in v1.1 |
|---|---|---|---|---|
| `fuel.lhv_solid_fuel_MJ_per_kg` | **26.0** MJ/kg | 6200 kcal/kg × 4.184e-3 = 25.94 ≈ 26.0 | 24–28 MJ/kg (≈5700–6700 kcal/kg), coal/petcoke blend | **In use** — the solid/liquid path for both fuel tags. |
| `fuel.lhv_gas_fuel_MJ_per_Nm3` | **36.0** MJ/Nm³ | 8600 kcal/Nm³ × 4.184e-3 = 35.98 ≈ 36.0 | 34–38 MJ/Nm³ (≈8100–9100 kcal/Nm³), pipeline natural gas | **Unused stream.** Kept so the volumetric path stays exercised and unit-tested. No gas-fuel tag exists in the v1.1 schema. |

`kiln_fuel_rate_tph` and `calciner_fuel_rate_tph` are **mass** flows on the solid/liquid path, so
both use `lhv_solid_fuel_MJ_per_kg`. A future gas stream would arrive as its own `Nm3/h` tag and use
`lhv_gas_fuel_MJ_per_Nm3` — and the two would be summed only after each became MJ/h.

**What replaces these numbers:** measured lab calorific value per fuel stream, on a single MJ basis.
That is exactly the `fuel_lhv_lab_results` request in §6 / PRD 27.2 — it is listed as `critical`
because these two ASSUMPTIONs sit underneath every thermal-energy figure the demo shows.

### 2.2 The other fuel-side constants that reach these tags

Also `ASSUMPTION`, also in `configs/kiln_dynamics.yaml` under `fuel:` (full calibration notes in
`SIMULATION_ASSUMPTIONS.md` §1):

| Config key | Default | Note |
|---|---|---|
| `fuel.kiln_burner_fuel_share` | 0.40 | 40 % main burner / 60 % calciner. Typical precalciner 35–45 / 55–65. Replace with the plant's flow-meter split. |
| `fuel.stoichiometric_air_Nm3_per_MJ` | 0.26 | Solid fuel; published 0.25–0.27. Drives all four air/exhaust flow tags (see §5.2). |
| `fuel.combustion_CO2_Nm3_per_MJ` | 0.047 | ≈2.4 kg CO₂/kg fuel at 26 MJ/kg. **Combustion CO₂ only** — calcination CO₂ comes from the mass balance (`LOI_CO2_mass_share`). |

The **reference fuel rates are deliberately not configured.** They are solved from the energy
balance at load time (`src/process_models/kiln_reference.py`), so the reference point cannot drift
out of energy consistency when one of the constants above is edited. This is why the fuel tags'
`operating_ranges` are expressed as *ratios* of the derived reference rather than absolute t/h —
see §5.1.

---

## 3. Kiln dataset — `data/synthetic/kiln_raw.parquet`

37 columns, in canonical order (`schema.KILN_COLUMNS`). PRD 12.1. Sampling 1 min throughout.
Provenance per §1.3. All ranges are `ASSUMPTION` bands, **not limiters** (§1.2).

| # | Tag | Process unit | Role | Unit | Documented range | Type | Provenance | Importance | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `timestamp` | Kiln | index | – | – | datetime | clock | critical | UTC timestamp. |
| 2 | `kiln_feed_rate_tph` | Kiln | manipulated | t/h | 150–230 | float | ASSUMPTION | critical | Raw meal feed to kiln system. |
| 3 | `kiln_fuel_rate_tph` | **Fuel** | manipulated | t/h | 3.2–5.2 | float | ASSUMPTION | critical | Main burner, solid/liquid on the MJ/kg basis of §2. **Simulated band is a *ratio* of the energy-balance-derived reference rate — see §5.1.** |
| 4 | `calciner_fuel_rate_tph` | **Fuel** | manipulated | t/h | 4.0–7.5 | float | ASSUMPTION | critical | Precalciner fuel, same MJ/kg basis. **Same documented deviation as row 3 (§5.1).** |
| 5 | `kiln_speed_rpm` | Kiln | manipulated | rpm | 2.8–4.5 | float | ASSUMPTION | critical | Kiln rotation speed. |
| 6 | `raw_meal_moisture` | Kiln | disturbance | % | 0.3–1.0 | float | ASSUMPTION | important | Residual moisture. Not an operator lever. |
| 7 | `raw_meal_temperature` | Kiln | disturbance | °C | 40–90 | float | ASSUMPTION | important | Feed temperature. Not an operator lever. |
| 8 | `primary_air_flow` | Fans | process | Nm³/h | 15,000–25,000 | float | ASSUMPTION | important | Primary air to main burner. **Sits below its band at reference (~12,086) — §5.2.** |
| 9 | `secondary_air_flow` | Cooler | process | Nm³/h | 90,000–140,000 | float | ASSUMPTION | important | Recuperated air from cooler. **Below band at reference (~66,472) — §5.2.** |
| 10 | `tertiary_air_flow` | Precalciner | process | Nm³/h | 60,000–100,000 | float | ASSUMPTION | critical | Air to calciner. **Below band at reference (~42,301) — §5.2.** |
| 11 | `ID_fan_speed` | Fans | manipulated | % | 60–95 | float | ASSUMPTION | critical | Induced-draught fan speed. |
| 12 | `ID_fan_power` | Fans | equipment | kW | 900–2,200 | float | ASSUMPTION | important | ID fan motor power. |
| 13 | `kiln_inlet_pressure` | Kiln | process | mbar | −8 to −2 | float | ASSUMPTION | important | Inlet draught. Negative by convention. |
| 14 | `preheater_pressure` | Preheater | process | mbar | −25 to −10 | float | ASSUMPTION | critical | Tower pressure. Negative by convention. |
| 15 | `exhaust_gas_flow` | Preheater | process | Nm³/h | 250,000–400,000 | float | ASSUMPTION | important | Stack/preheater exhaust. **Below band at reference (~199,248) — §5.2.** |
| 16 | `burning_zone_temperature` | Kiln | process | °C | 1,400–1,500 | float | ASSUMPTION | critical | Pyrometer/model. A PRD 14.2 hard-constraint variable (1,420–1,480). |
| 17 | `kiln_inlet_temperature` | Kiln | process | °C | 800–950 | float | ASSUMPTION | important | Material temp at kiln inlet. |
| 18 | `calciner_temperature` | Precalciner | process | °C | 850–900 | float | ASSUMPTION | critical | Precalciner outlet. |
| 19 | `preheater_outlet_temperature` | Preheater | process | °C | 280–380 | float | ASSUMPTION | critical | Top-stage cyclone exit. **Not free: inverted from the PRD 9.3 energy closure** (`balances.preheater_outlet_temperature_from_energy`), then published through the `energy_closure_to_preheater_temperature` delay. |
| 20 | `secondary_air_temperature` | Cooler | process | °C | 800–1,000 | float | ASSUMPTION | important | Recuperated air temperature. |
| 21 | `cooler_outlet_temperature` | Cooler | process | °C | 80–150 | float | ASSUMPTION | important | Clinker cooler discharge. |
| 22 | `oxygen_percent` | Kiln | process | % | 0.7–4.0 | float | ASSUMPTION | critical | O₂ at kiln inlet/back-end, dry. A PRD 14.2 hard constraint (1.0–3.5). **This band is *kept* where it conflicts with the air-flow bands — §5.2.** |
| 23 | `CO_ppm` | Kiln | emission | ppm | 0–300 | float | ASSUMPTION | critical | **Spikes above the band under fault** (PRD 12.1). Hard constraint max 200. |
| 24 | `CO2_percent` | Kiln | emission | % | 28–36 | float | ASSUMPTION | important | Combustion + calcination CO₂ (see §2.2). |
| 25 | `NOx_ppm` | Kiln | emission | ppm | 250–900 | float | ASSUMPTION | optional, **not mandatory** | Converted from mg/Nm³ by an **ASSUMPTION conversion factor**. |
| 26 | `SO2_ppm` | Kiln | emission | ppm | 10–400 | float | ASSUMPTION | optional, **not mandatory** | Raw-material sulfur dependent. |
| 27 | `clinker_production_tph` | Kiln | process | t/h | 95–150 | float | ASSUMPTION | critical | Clinker output. Hard-constrained against `production_target_tph` 119.7 ± 1 %. |
| 28 | `clinker_temperature` | Cooler | process | °C | 80–150 | float | ASSUMPTION | important | Clinker discharge temperature. |
| 29 | `thermal_energy_kcal_per_kg_clinker` | **Fuel** | **derived** | kcal/kg | 700–950 | float | ASSUMPTION | critical | **Display-unit derivation of the canonical MJ balance — §2.** Not independently simulated. |
| 30 | `specific_fuel_consumption` | **Fuel** | **derived** | kcal/kg | 700–950 | float | ASSUMPTION | optional, **not mandatory** | **Duplicate of row 29**, kept only for factory-familiar naming. Carries no independent information. |
| 31 | `ID_fan_current` | Fans | equipment | A | 100–260 | float | ASSUMPTION | important | 201.7 A at reference, on the derived 6 kV bus (§5.2). |
| 32 | `kiln_motor_current` | Kiln | equipment | A | 80–180 | float | ASSUMPTION | important | Main drive current. |
| 33 | `cooler_fan_power` | Cooler | equipment | kW | 400–1,100 | float | ASSUMPTION | important | Cooler fans, total. |
| 34 | `vibration` | Kiln | equipment | mm/s | 1–8 | float | ASSUMPTION | important | Drive/support, generic. **Spikes above the band under fault.** |
| 35 | `bearing_temperature` | Kiln | equipment | °C | 45–75 | float | ASSUMPTION | important | Support roller bearing. **Spikes above the band under fault.** |
| 36 | `operating_regime` | Kiln | **label** | – | categorical | string | **ground truth** | critical | PRD 11.4 regime label. **A real plant would not supply this.** |
| 37 | `injected_fault` | Kiln | **label** | – | categorical / null | string | **ground truth** | critical | Null outside an injected fault; set **only on the unit the regime perturbs**. **A real plant would not supply this.** |

---

## 4. Cement mill dataset — `data/synthetic/mill_raw.parquet`

25 columns, in canonical order (`schema.MILL_COLUMNS`). PRD 12.2. Sampling 1 min throughout.
A **generic closed-circuit** mill — deliberately neither VRM- nor ball-mill-specific (PRD 31).

| # | Tag | Process unit | Role | Unit | Documented range | Type | Provenance | Importance | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `timestamp` | Cement Mill | index | – | – | datetime | clock | critical | UTC timestamp. |
| 2 | `mill_feed_rate_tph` | Cement Mill | manipulated | t/h | 80–170 | float | ASSUMPTION | critical | Total mill feed. A What-if / optimizer lever. |
| 3 | `clinker_feed_rate` | Cement Mill | manipulated | t/h | 70–150 | float | ASSUMPTION | critical | Clinker component of feed. |
| 4 | `gypsum_feed_rate` | Cement Mill | manipulated | t/h | 3–8 | float | ASSUMPTION | important | Gypsum component. |
| 5 | `additive_feed_rate` | Cement Mill | manipulated | t/h | 0–20 | float | ASSUMPTION | important | Additive/limestone component. Lower bound is a true 0. |
| 6 | `mill_motor_power_kw` | Cement Mill | process | kW | 2,500–5,500 | float | ASSUMPTION | critical | Main mill motor power. |
| 7 | `mill_current` | Cement Mill | equipment | A | 200–420 | float | ASSUMPTION | important | Main motor current. |
| 8 | `mill_pressure` | Cement Mill | process | mbar | −40 to −10 | float | ASSUMPTION | important | VRM internal / shell pressure proxy. |
| 9 | `mill_differential_pressure` | Cement Mill | process | mbar | 20–90 | float | ASSUMPTION | critical | Mill ΔP, the loading indicator. **Spikes above the band under overload** (PRD 12.2). |
| 10 | `mill_outlet_temperature` | Cement Mill | process | °C | 90–120 | float | ASSUMPTION | important | Material/gas outlet temperature. |
| 11 | `mill_vibration` | Cement Mill | equipment | mm/s | 1–10 | float | ASSUMPTION | important | Mill body. **Spikes above the band under fault.** |
| 12 | `mill_speed` | Cement Mill | manipulated | rpm | 12–18 | float | ASSUMPTION | important | Rotational/table speed. **Generic circuit** — neither VRM- nor ball-mill-specific. |
| 13 | `separator_speed_rpm` | Separator | manipulated | rpm | 60–140 | float | ASSUMPTION | critical | Dynamic separator rotor. **The primary quality lever** (PRD 27.2) and the headline What-if lever for Demo 4. |
| 14 | `separator_current` | Separator | equipment | A | 30–80 | float | ASSUMPTION | critical | 59.4 A at reference; reaches **84.29 A** when the separator is held 15 % above reference — **outside the band, by design (§5.3).** |
| 15 | `separator_pressure` | Separator | process | mbar | −15 to −5 | float | ASSUMPTION | critical | Separator inlet/outlet. |
| 16 | `fan_speed` | Fans | manipulated | % | 60–100 | float | ASSUMPTION | important | Main/circulation fan speed. |
| 17 | `fan_power_kw` | Fans | equipment | kW | 400–1,200 | float | ASSUMPTION | important | Main fan power. |
| 18 | `gas_flow` | Cement Mill | process | Nm³/h | 150,000–260,000 | float | ASSUMPTION | important | Circulating gas flow. |
| 19 | `cement_production_tph` | Cement Mill | process | t/h | 75–160 | float | ASSUMPTION | critical | Net finished-product rate. The throughput side of the PRD 10.4 trade-off. |
| 20 | `product_temperature` | Cement Mill | process | °C | 85–115 | float | ASSUMPTION | important | Finished product temperature. |
| 21 | `simulated_blaine_cm2_g` | Cement Mill | **quality** | cm²/g | 2,900–4,200 | float | ASSUMPTION | critical | Fineness (Blaine surface area). Target 3,400 ± 150. The quality side of the PRD 10.4 trade-off. |
| 22 | `residue_percent` | Cement Mill | **quality** | % | 6–18 | float | ASSUMPTION | critical | 45 µm sieve residue. Constrained max 14.0. |
| 23 | `specific_power_consumption_kwh_t` | Cement Mill | **derived** | kWh/t | 26–45 | float | ASSUMPTION | critical | Specific electrical energy. The energy side of the PRD 10.4 trade-off. |
| 24 | `operating_regime` | Cement Mill | **label** | – | categorical | string | **ground truth** | critical | Regime label. **A real plant would not supply this.** |
| 25 | `injected_fault` | Cement Mill | **label** | – | categorical / null | string | **ground truth** | critical | Null outside an injected fault; set only on the perturbed unit. **A real plant would not supply this.** |

### 4.1 The trade-off these three tags exist to demonstrate

PRD 10.4 requires the mill model to show a real trade-off rather than a free lunch. Rows 13, 19, 21
and 23 are the four tags that carry it: raising `separator_speed_rpm` raises
`simulated_blaine_cm2_g` (finer product) while *reducing* `cement_production_tph` and *raising*
`specific_power_consumption_kwh_t`. Demo 4 in `DEMO_GUIDE.md` is the scripted walk-through.

---

## 5. Documented-range deviations — tags that sit outside their own band

**Read this section before quoting any range above as an operating fact.**

PRD 11.4 and 12.1 are explicit that the documented ranges are process-reasoned ASSUMPTIONs and that
the model must never be silently clamped to them. Where a PRD 12 band cannot hold simultaneously
with the PRD 9–10 equations, **the physics is kept and the deviation is documented** — bending a
coefficient to land inside a band would be exactly the "silently invent a different number" the PRD
forbids. `SIMULATION_ASSUMPTIONS.md` §8 is the authority; this is the tag-level index into it.

### 5.1 Kiln fuel rates (rows 3–4)

| Tag | Documented band | Reference value | Why |
|---|---|---|---|
| `kiln_fuel_rate_tph` | 3.2–5.2 t/h | **6.219 t/h** | Solved from the energy balance |
| `calciner_fuel_rate_tph` | 4.0–7.5 t/h | **9.328 t/h** | Solved from the energy balance |

Four PRD statements cannot all hold at once: clinker 95–150 t/h (12.1), clinker factor 0.63 (9.3),
LHV 26 MJ/kg (9.2), and specific heat consumption 700–950 kcal/kg (12.1). 119.7 t/h of clinker at
807 kcal/kg needs **15.55 t/h** of 26 MJ/kg fuel, against a fuel-band maximum of 12.7 t/h — which
would itself imply ≈660 kcal/kg, *below the PRD's own band*. The energy balance and the
specific-consumption benchmark are kept; the absolute fuel bands are not. The fuel `operating_ranges`
in `kiln_dynamics.yaml` are therefore **ratios** of the derived reference (0.80–1.20), not absolute
t/h.

### 5.2 Kiln air and exhaust flows (rows 8, 9, 10, 15)

| Tag | Documented band | Reference value |
|---|---|---|
| `primary_air_flow` | 15,000–25,000 Nm³/h | **12,086** |
| `secondary_air_flow` | 90,000–140,000 Nm³/h | **66,472** |
| `tertiary_air_flow` | 60,000–100,000 Nm³/h | **42,301** |
| `exhaust_gas_flow` | 250,000–400,000 Nm³/h | **199,248** |

All four follow from one quantity: combustion air = fuel energy × `stoichiometric_air_Nm3_per_MJ`
(0.26) × `excess_air_ratio` (1.15) = **120,859 Nm³/h**, split 10 / 55 / 35 %. Reaching those bands
takes λ ≈ 1.45, at which point back-end O₂ is **5.39 %** — well outside the PRD's own 0.7–4.0 %
band (row 22); even λ = 1.30 gives 3.91 % while still leaving every flow below its band. **The O₂
band and the stoichiometry are kept**; the flow bands are treated as belonging to a larger, leakier
line than these coefficients describe. The four tags remain mutually consistent, since air split,
false air, exhaust flow and the ID-fan power/current all derive from the same figure.

`id_fan_motor_voltage_V` = 6000 is **not** a deviation but a *derived* choice: 6 kV is the
medium-voltage level that keeps `ID_fan_current` (row 31, 201.7 A at reference) inside its 100–260 A
band at the ≈1.78 MW reference shaft power. PRD 12.1 documents no voltage band.

### 5.3 Excursions outside a band are permitted, by design

`separator_current` (row 14) reaches **84.29 A** against a 30–80 A band when the separator is held
15 % above reference. This is the *intended* behaviour, not drift: PRD 11.4 needs the abnormal
regimes to actually leave the normal envelope. The optimizer's envelope (PRD 14.3) is the layer that
refuses to **recommend** such a point — the twin will still **simulate** it. Tags marked "spikes
under fault" in §3–§4 (`CO_ppm`, `vibration`, `bearing_temperature`,
`mill_differential_pressure`, `mill_vibration`) behave the same way.

---

## 6. Debug-only columns — not part of the core schema

`schema.DEBUG_BALANCE_COLUMNS`. Exported **only** when `debug_balance_export: true` in
`configs/kiln_dynamics.yaml`, and consumed **exclusively** by the PRD 34 conservation tests. Never
shown in the UI and never in a standard export. Request them with
`schema.columns_for(dataset, include_debug_balance=True)`.

| Column | Unit | Purpose |
|---|---|---|
| `energy_balance_residual_pct` | % | Per-row closure residual of the PRD 9.3 energy balance. Asserted within `unaccounted_loss_max_fraction` (ASSUMPTION 0.03 — a **test tolerance bound, not a free-fit parameter**) by `test_kiln_energy_balance()`. |
| `mass_balance_residual_pct` | % | Per-row closure residual of the PRD 9.3 mass balance. Asserted by `test_kiln_mass_balance()`. |

The mass-balance constants these residuals are measured against, all `ASSUMPTION`, all in
`configs/kiln_dynamics.yaml` under `mass_balance:`:

| Config key | Default | Note |
|---|---|---|
| `clinker_factor` | 0.63 | Unchanged from v1.0. |
| `dust_loss_fraction` | 0.01 | |
| `LOI_loss_fraction` | 0.36 | **DERIVED** = 1 − 0.63 − 0.01. Consistent with typical raw-meal LOI of 35–36 % (CO₂ + H₂O driven off in calcination). |
| `kiln_residence_time_min` | 35.0 | Replaces v1.0's free-standing `tau_production` with a physically motivated first-order discharge lag. |

---

## 7. Requested from the factory but deliberately **not** in the v1.1 schema

`schema.FUTURE_DATA_REQUESTS` (PRD 27.2). These are tags the factory is asked for even though v1.1
does not simulate them. `FACTORY_DATA_REQUIREMENTS.md` is the send-ready version of this request.

| Request | Process unit | Importance | Why it is asked for |
|---|---|---|---|
| `fuel_lhv_lab_results` | Fuel | **critical** | Lab calorific value (LHV) per fuel stream on a single MJ basis (MJ/kg solid/liquid, MJ/Nm³ gas). **Replaces the `lhv_solid_fuel_MJ_per_kg` / `lhv_gas_fuel_MJ_per_Nm3` ASSUMPTIONs of §2.1 with measured values** — the single highest-leverage number in this document. |
| `section_electrical_energy_meters` | Electrical system | important | Total plant and per-section electrical energy meters (kWh). Optional but high value: lets plant-wide electrical optimization be validated later. |
| `raw_mill_circuit_tags` | Raw Mill | optional | Raw mill / raw meal preparation circuit. Out of scope in v1.1 (PRD 5.2); listed so the factory knows it will eventually be requested (roadmap PRD 32). |
| `step_test_transient_logs` | Kiln, Cement Mill | important | Logged responses to known setpoint changes. High-value input for calibrating the per-relationship dead-time + lag parameters of PRD 9.4/10.3 (PRD 27.3). |

---

## 8. What would replace the assumptions in this file

| Layer | Where the numbers are now | What replaces them |
|---|---|---|
| Fuel LHV, air stoichiometry, combustion CO₂ | `configs/kiln_dynamics.yaml → fuel:` (§2) | Fuel-lab ultimate analysis + calorific value per stream (`fuel_lhv_lab_results`). |
| Documented tag ranges (56 tags) | `src/schema.py`, `range_min`/`range_max` | Percentile bands computed from real historian data over a representative horizon (PRD 26/27). |
| Energy/mass-balance fractions | `configs/kiln_dynamics.yaml → energy_balance:`, `mass_balance:` | Plant heat-balance survey; measured clinker factor and dust return. |
| Per-relationship delays | `kiln_dynamics.yaml`/`mill_dynamics.yaml → delays:` | Step-test / transient logs (`step_test_transient_logs`). |
| Sensor noise and quantization | `configs/scenarios.yaml` | Instrument datasheets + observed historian noise floor. |
| Regime definitions & labels | `configs/scenarios.yaml` | Operator logs / DCS alarm history. **The `operating_regime` and `injected_fault` columns disappear entirely** — a real plant has no ground-truth label, which is precisely why PRD 21.3 says the synthetic environment cannot validate real-world detection performance. |

Full per-constant calibration notes — *what measurement would replace this number* — live in
`SIMULATION_ASSUMPTIONS.md`. This file is the tag-level view; that file is the constant-level view.

---

## 9. Standing statement

> This is a synthetic demonstration environment. The simulation is not calibrated against a real
> cement plant. The AI models are not production-validated. Energy-saving percentages are simulation
> results, not guaranteed factory savings. Real deployment requires real historical data,
> process-engineering validation, plant-specific calibration, OT/IT integration, cybersecurity
> review, operator validation, safety validation, and commissioning.
> — PRD v1.1.1 Section 31, displayed verbatim wherever results are shown

**Related documents:** `SIMULATION_ASSUMPTIONS.md` (every ASSUMPTION constant with its calibration
note) · `FACTORY_DATA_REQUIREMENTS.md` (PRD 27, send-ready) · `ARCHITECTURE.md` (the `DataProvider`
abstraction these tags flow through) · `DEMO_GUIDE.md` (how the tags appear on screen).
