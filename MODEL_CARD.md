# MODEL_CARD

*Synthetic Cement Plant Digital Twin + AI Optimization Platform — Demonstration Environment (PRD v1.1.1)*

> **This model has not been validated against real cement-plant data.**

> The synthetic model is a development and demonstration environment, not a calibrated representation of any specific cement plant.

Every model described here was trained on **synthetic data produced by this repository's own simulator**. No real plant measurement was used at any point, and no number in this card is evidence about any real cement plant.

---

## Provenance

- **Generated**: 2026-08-18T07:52:36+00:00 (regenerate with `python -m src.models.model_card`)
- **PRD version**: 1.1.1
- **Datasets**: `kiln`, `mill`
- **Metric reports**: `H:\vibe coding\digital_Twin\reports\metrics\model_a_horizon_metrics.json`, `H:\vibe coding\digital_Twin\reports\metrics\model_b_metrics.json`
- **Model registry**: `H:\vibe coding\digital_Twin\models\registry.json`
- **Simulation provenance** (the scalar keys; the full config is stored verbatim on every registry entry and in each dataset's export sidecar):

  - `prd_version`: `1.1.1`
  - `simulation.config_source`: `H:\vibe coding\digital_Twin\configs\scenarios.yaml`
  - `simulation.dt_seconds`: `60.0`
  - `simulation.duration_days`: `30.0`
  - `simulation.duration_minutes`: `43200.0`
  - `simulation.export_steps`: `43200`
  - `simulation.seed`: `20240101`
  - `simulation.start_timestamp`: `2024-01-01T00:00:00+00:00`
  - `simulation.warmup_minutes`: `180.0`
  - `simulation.warmup_steps`: `180`

---

## Model A — multi-horizon prediction (PRD 13.1)

One supervised regressor per (target, horizon) pair. Targets are shifted forward by the horizon and features are strictly at or before `t`, so nothing a model reads was recorded after the minute it is labelling. Rows whose window crosses a split boundary are purged rather than merely cut (PRD 13.3).

### Model A — kiln

#### Model validity domain

- **Training rows** (at the longest horizon, t+30min): 11,706
- **Training data range**: `2024-01-01 07:27:00+00:00` to `2024-01-17 14:19:00+00:00`
- **Operating regimes represented in training**: `Fan instability`, `Feed disturbance`, `High fuel condition`, `High oxygen condition`, `High separator speed`, `Low oxygen condition`, `Low separator speed`, `Mill overload`, `Mill underload`, `Normal - high production`, `Normal - low production`, `Normal - medium production`, `Sensor drift`, `Temperature disturbance`
- **Targets**: `burning_zone_temperature`, `oxygen_percent`, `clinker_production_tph`, `thermal_energy_kcal_per_kg_clinker`
- **Horizons**: t+5min, t+10min, t+15min, t+30min
- **Feature columns**: 79 (16 current-value + lags of 1 min, 5 min, 15 min)

Variable ranges seen in training (the PRD 14.3 check-1 envelope):
| Variable | Min | Max |
|---|---|---|
| `CO_ppm` | 15 | 7,382 |
| `ID_fan_speed` | 70.9 | 87.7 |
| `burning_zone_temperature` | 1,354 | 1,533 |
| `calciner_fuel_rate_tph` | 7.902 | 10.58 |
| `calciner_temperature` | 846.1 | 908.3 |
| `clinker_production_tph` | 100 | 137.4 |
| `exhaust_gas_flow` | 1.726e+05 | 2.326e+05 |
| `kiln_feed_rate_tph` | 158.2 | 217.7 |
| `kiln_fuel_rate_tph` | 5.278 | 7.031 |
| `kiln_speed_rpm` | 3.56 | 3.64 |
| `oxygen_percent` | -0.17 | 5.19 |
| `preheater_outlet_temperature` | 191.1 | 532.8 |
| `preheater_pressure` | -24.4 | -14.2 |
| `raw_meal_moisture` | 0.2834 | 1.167 |
| `raw_meal_temperature` | 43.37 | 71.86 |
| `thermal_energy_kcal_per_kg_clinker` | 612.3 | 1,062 |

#### Method and family selection

One `RandomForestRegressor` (the PRD 13.1 baseline, always trained) and one `GradientBoostingRegressor` per (target, horizon), selected on held-out MAE from the chronological validation block. `LightGBM` is not used: PRD 13.1 admits it only if it measurably beats both, which was never tested here, so it is absent rather than half-integrated. A **persistence reference** is scored alongside but is never selectable.

| Target | Horizon | Selected | random_forest MAE | gradient_boosting MAE | Rule |
|---|---|---|---|---|---|
| `burning_zone_temperature` | t+5min | **random_forest** | 5.497 | 5.545 | mae on 6,384 validation rows |
| `burning_zone_temperature` | t+10min | **gradient_boosting** | 5.695 | 5.655 | mae on 6,378 validation rows |
| `burning_zone_temperature` | t+15min | **random_forest** | 5.967 | 6.027 | mae on 6,361 validation rows |
| `burning_zone_temperature` | t+30min | **random_forest** | 7.096 | 7.266 | mae on 6,343 validation rows |
| `clinker_production_tph` | t+5min | **random_forest** | 0.4802 | 0.4838 | mae on 6,380 validation rows |
| `clinker_production_tph` | t+10min | **gradient_boosting** | 0.5047 | 0.4989 | mae on 6,374 validation rows |
| `clinker_production_tph` | t+15min | **gradient_boosting** | 0.5268 | 0.5168 | mae on 6,357 validation rows |
| `clinker_production_tph` | t+30min | **random_forest** | 0.6612 | 0.6735 | mae on 6,339 validation rows |
| `oxygen_percent` | t+5min | **gradient_boosting** | 0.09547 | 0.08908 | mae on 6,390 validation rows |
| `oxygen_percent` | t+10min | **random_forest** | 0.1213 | 0.1235 | mae on 6,385 validation rows |
| `oxygen_percent` | t+15min | **random_forest** | 0.1611 | 0.1633 | mae on 6,369 validation rows |
| `oxygen_percent` | t+30min | **gradient_boosting** | 0.2827 | 0.2728 | mae on 6,351 validation rows |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | **random_forest** | 3.513 | 3.632 | mae on 6,390 validation rows |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | **random_forest** | 4.816 | 4.848 | mae on 6,384 validation rows |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | **random_forest** | 5.813 | 5.931 | mae on 6,367 validation rows |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | **gradient_boosting** | 8.491 | 8.381 | mae on 6,349 validation rows |

#### Uncertainty method (PRD 13.1.1)

| Target | Horizon | Method | Bootstrap members |
|---|---|---|---|
| `burning_zone_temperature` | t+5min | `random_forest_tree_spread` | n/a |
| `burning_zone_temperature` | t+10min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `burning_zone_temperature` | t+15min | `random_forest_tree_spread` | n/a |
| `burning_zone_temperature` | t+30min | `random_forest_tree_spread` | n/a |
| `clinker_production_tph` | t+5min | `random_forest_tree_spread` | n/a |
| `clinker_production_tph` | t+10min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `clinker_production_tph` | t+15min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `clinker_production_tph` | t+30min | `random_forest_tree_spread` | n/a |
| `oxygen_percent` | t+5min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `oxygen_percent` | t+10min | `random_forest_tree_spread` | n/a |
| `oxygen_percent` | t+15min | `random_forest_tree_spread` | n/a |
| `oxygen_percent` | t+30min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | `random_forest_tree_spread` | n/a |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | `random_forest_tree_spread` | n/a |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | `random_forest_tree_spread` | n/a |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | `gradient_boosting_bootstrap_ensemble` | 20 |

`random_forest_tree_spread` is the spread across a fitted forest's own trees, so it needs no extra fit and has no member count. `gradient_boosting_bootstrap_ensemble` refits the selected gradient-boosting estimator on bootstrap resamples, and is built on first use rather than during training - a member count marked *(config)* is the configured size of an ensemble not yet materialised.

The spread is reported as `value ± spread` in the target's own unit and is turned into the categorical **Recommendation Quality** label (`HIGH` / `MEDIUM` / `LOW`) required by FR-23. It is deliberately **not** rendered as a confidence percentage: the spread of an ensemble is not a calibrated probability, and a synthetic-only model has no basis on which to claim one. The category thresholds live in `configs/ml.yaml`, and any factor that cannot be assessed in the current context caps the label at `MEDIUM` rather than allowing `HIGH`.

- `HIGH` — Tight model-ensemble spread, close agreement between model families, comfortable margin to every hard constraint, and clearly inside the training distribution.
- `MEDIUM` — Moderate ensemble spread, some disagreement between model families, or a narrow margin to a hard constraint / the edge of the training distribution.
- `LOW` — Wide ensemble spread, disagreeing model families, a very narrow constraint margin, or an operating point far from the training distribution.

#### Metrics — Chronological split (PRD 13.3 split 1)

**validation block**

| Target | Horizon | Model | MAE | RMSE | R2 | MAPE % | MAE vs truth | R2 vs truth | Rows |
|---|---|---|---|---|---|---|---|---|---|
| `burning_zone_temperature` | t+5min | gradient_boosting | 5.545 | 7.121 | 0.9017 | 0.3807 | 2.92 | 0.9517 | 6384 |
| `burning_zone_temperature` | t+5min | random_forest | 5.497 | 7.104 | 0.9021 | 0.3774 | 2.708 | 0.9519 | 6384 |
| `burning_zone_temperature` | t+10min | gradient_boosting | 5.655 | 7.367 | 0.8947 | 0.3882 | 3.05 | 0.943 | 6378 |
| `burning_zone_temperature` | t+10min | random_forest | 5.695 | 7.531 | 0.89 | 0.391 | 3.006 | 0.9364 | 6378 |
| `burning_zone_temperature` | t+15min | gradient_boosting | 6.027 | 8.013 | 0.8752 | 0.4137 | 3.478 | 0.9257 | 6361 |
| `burning_zone_temperature` | t+15min | random_forest | 5.967 | 8.153 | 0.8708 | 0.4096 | 3.259 | 0.9197 | 6361 |
| `burning_zone_temperature` | t+30min | gradient_boosting | 7.266 | 10.25 | 0.7954 | 0.4989 | 4.918 | 0.8481 | 6343 |
| `burning_zone_temperature` | t+30min | random_forest | 7.096 | 10.1 | 0.801 | 0.4869 | 4.838 | 0.8445 | 6343 |
| `clinker_production_tph` | t+5min | gradient_boosting | 0.4838 | 0.6182 | 0.9899 | 0.4071 | 0.1573 | 0.9977 | 6380 |
| `clinker_production_tph` | t+5min | random_forest | 0.4802 | 0.6149 | 0.99 | 0.4043 | 0.1357 | 0.9979 | 6380 |
| `clinker_production_tph` | t+10min | gradient_boosting | 0.4989 | 0.65 | 0.9888 | 0.4198 | 0.1662 | 0.9967 | 6374 |
| `clinker_production_tph` | t+10min | random_forest | 0.5047 | 0.6817 | 0.9877 | 0.4242 | 0.1491 | 0.9955 | 6374 |
| `clinker_production_tph` | t+15min | gradient_boosting | 0.5168 | 0.6898 | 0.9874 | 0.4346 | 0.183 | 0.9953 | 6357 |
| `clinker_production_tph` | t+15min | random_forest | 0.5268 | 0.7401 | 0.9855 | 0.4427 | 0.1709 | 0.9935 | 6357 |
| `clinker_production_tph` | t+30min | gradient_boosting | 0.6735 | 1.123 | 0.9668 | 0.5662 | 0.3764 | 0.9745 | 6339 |
| `clinker_production_tph` | t+30min | random_forest | 0.6612 | 1.094 | 0.9685 | 0.5565 | 0.3446 | 0.9763 | 6339 |
| `oxygen_percent` | t+5min | gradient_boosting | 0.08908 | 0.1438 | 0.9852 | n/a | 0.0837 | 0.9813 | 6390 |
| `oxygen_percent` | t+5min | random_forest | 0.09547 | 0.1727 | 0.9787 | n/a | 0.08731 | 0.9747 | 6390 |
| `oxygen_percent` | t+10min | gradient_boosting | 0.1235 | 0.2498 | 0.9554 | n/a | 0.1204 | 0.9507 | 6385 |
| `oxygen_percent` | t+10min | random_forest | 0.1213 | 0.2535 | 0.954 | n/a | 0.1187 | 0.9492 | 6385 |
| `oxygen_percent` | t+15min | gradient_boosting | 0.1633 | 0.3472 | 0.914 | n/a | 0.161 | 0.9099 | 6369 |
| `oxygen_percent` | t+15min | random_forest | 0.1611 | 0.3494 | 0.9129 | n/a | 0.1615 | 0.9082 | 6369 |
| `oxygen_percent` | t+30min | gradient_boosting | 0.2728 | 0.5346 | 0.7966 | n/a | 0.269 | 0.7934 | 6351 |
| `oxygen_percent` | t+30min | random_forest | 0.2827 | 0.5663 | 0.7718 | n/a | 0.284 | 0.7673 | 6351 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | gradient_boosting | 3.632 | 7.835 | 0.8532 | 0.4462 | 2.66 | 0.8606 | 6390 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | random_forest | 3.513 | 7.343 | 0.8711 | 0.4322 | 2.357 | 0.879 | 6390 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | gradient_boosting | 4.848 | 11.37 | 0.6909 | 0.5963 | 4.019 | 0.6929 | 6384 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | random_forest | 4.816 | 10.68 | 0.7272 | 0.5936 | 3.909 | 0.7303 | 6384 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | gradient_boosting | 5.931 | 13.07 | 0.5917 | 0.7296 | 5.175 | 0.5939 | 6367 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | random_forest | 5.813 | 12.79 | 0.6089 | 0.7153 | 5.003 | 0.612 | 6367 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | gradient_boosting | 8.381 | 16.03 | 0.3845 | 1.034 | 7.756 | 0.3864 | 6349 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | random_forest | 8.491 | 16.48 | 0.3496 | 1.049 | 7.871 | 0.3513 | 6349 |

**test block**

| Target | Horizon | Model | MAE | RMSE | R2 | MAPE % | MAE vs truth | R2 vs truth | Rows |
|---|---|---|---|---|---|---|---|---|---|
| `burning_zone_temperature` | t+5min | gradient_boosting | 5.299 | 6.688 | 0.9098 | 0.3638 | 2.334 | 0.9707 | 12807 |
| `burning_zone_temperature` | t+5min | persistence_reference | 6.981 | 8.81 | 0.8434 | 0.4794 | 5.416 | 0.8939 | 12807 |
| `burning_zone_temperature` | t+5min | **random_forest** | 5.308 | 6.735 | 0.9085 | 0.3644 | 2.163 | 0.9696 | 12807 |
| `burning_zone_temperature` | t+10min | **gradient_boosting** | 5.51 | 7.056 | 0.8996 | 0.3783 | 2.457 | 0.9633 | 12806 |
| `burning_zone_temperature` | t+10min | persistence_reference | 7.52 | 9.667 | 0.8115 | 0.5164 | 5.995 | 0.8619 | 12806 |
| `burning_zone_temperature` | t+10min | random_forest | 5.539 | 7.188 | 0.8958 | 0.3801 | 2.412 | 0.9556 | 12806 |
| `burning_zone_temperature` | t+15min | gradient_boosting | 5.863 | 7.722 | 0.8798 | 0.4024 | 2.891 | 0.9432 | 12801 |
| `burning_zone_temperature` | t+15min | persistence_reference | 8.036 | 10.57 | 0.7748 | 0.5518 | 6.612 | 0.8212 | 12801 |
| `burning_zone_temperature` | t+15min | **random_forest** | 5.888 | 7.882 | 0.8747 | 0.4039 | 2.73 | 0.9375 | 12801 |
| `burning_zone_temperature` | t+30min | gradient_boosting | 7.166 | 10.13 | 0.7931 | 0.4918 | 4.439 | 0.8614 | 12797 |
| `burning_zone_temperature` | t+30min | persistence_reference | 9.823 | 13.52 | 0.6317 | 0.6744 | 8.459 | 0.6718 | 12797 |
| `burning_zone_temperature` | t+30min | **random_forest** | 7.108 | 10.01 | 0.7978 | 0.4873 | 4.297 | 0.859 | 12797 |
| `clinker_production_tph` | t+5min | gradient_boosting | 0.4781 | 0.6073 | 0.9911 | 0.3999 | 0.1462 | 0.9981 | 12798 |
| `clinker_production_tph` | t+5min | persistence_reference | 0.651 | 0.8249 | 0.9836 | 0.5448 | 0.4787 | 0.9906 | 12798 |
| `clinker_production_tph` | t+5min | **random_forest** | 0.47 | 0.5988 | 0.9913 | 0.3936 | 0.1182 | 0.9984 | 12798 |
| `clinker_production_tph` | t+10min | **gradient_boosting** | 0.4882 | 0.6302 | 0.9904 | 0.4083 | 0.1486 | 0.9974 | 12797 |
| `clinker_production_tph` | t+10min | persistence_reference | 0.7124 | 0.9597 | 0.9778 | 0.5961 | 0.5465 | 0.9846 | 12797 |
| `clinker_production_tph` | t+10min | random_forest | 0.4943 | 0.6593 | 0.9895 | 0.4126 | 0.1326 | 0.9964 | 12797 |
| `clinker_production_tph` | t+15min | **gradient_boosting** | 0.5032 | 0.6752 | 0.989 | 0.421 | 0.1667 | 0.9959 | 12792 |
| `clinker_production_tph` | t+15min | persistence_reference | 0.7754 | 1.135 | 0.9689 | 0.6488 | 0.6196 | 0.9753 | 12792 |
| `clinker_production_tph` | t+15min | random_forest | 0.5081 | 0.6983 | 0.9882 | 0.4245 | 0.147 | 0.9951 | 12792 |
| `clinker_production_tph` | t+30min | gradient_boosting | 0.637 | 1.064 | 0.9727 | 0.5333 | 0.3393 | 0.9794 | 12788 |
| `clinker_production_tph` | t+30min | persistence_reference | 1.005 | 1.754 | 0.9258 | 0.8408 | 0.8523 | 0.9318 | 12788 |
| `clinker_production_tph` | t+30min | **random_forest** | 0.632 | 1.056 | 0.9731 | 0.5282 | 0.3165 | 0.9797 | 12788 |
| `oxygen_percent` | t+5min | **gradient_boosting** | 0.08812 | 0.1554 | 0.9834 | n/a | 0.07323 | 0.9815 | 12801 |
| `oxygen_percent` | t+5min | persistence_reference | 0.113 | 0.2136 | 0.9686 | n/a | 0.1086 | 0.9653 | 12801 |
| `oxygen_percent` | t+5min | random_forest | 0.08694 | 0.1748 | 0.9789 | n/a | 0.06663 | 0.9776 | 12801 |
| `oxygen_percent` | t+10min | gradient_boosting | 0.1243 | 0.26 | 0.9534 | n/a | 0.1132 | 0.9503 | 12800 |
| `oxygen_percent` | t+10min | persistence_reference | 0.131 | 0.2883 | 0.9427 | n/a | 0.1301 | 0.9367 | 12800 |
| `oxygen_percent` | t+10min | **random_forest** | 0.118 | 0.272 | 0.949 | n/a | 0.1062 | 0.946 | 12800 |
| `oxygen_percent` | t+15min | gradient_boosting | 0.1557 | 0.3419 | 0.9195 | n/a | 0.147 | 0.9165 | 12795 |
| `oxygen_percent` | t+15min | persistence_reference | 0.15 | 0.3571 | 0.9122 | n/a | 0.1443 | 0.909 | 12795 |
| `oxygen_percent` | t+15min | **random_forest** | 0.1612 | 0.3644 | 0.9086 | n/a | 0.1537 | 0.9052 | 12795 |
| `oxygen_percent` | t+30min | **gradient_boosting** | 0.2576 | 0.5165 | 0.8163 | n/a | 0.2508 | 0.8132 | 12791 |
| `oxygen_percent` | t+30min | persistence_reference | 0.2277 | 0.5331 | 0.8043 | n/a | 0.2231 | 0.8002 | 12791 |
| `oxygen_percent` | t+30min | random_forest | 0.2953 | 0.5715 | 0.7751 | n/a | 0.292 | 0.7716 | 12791 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | gradient_boosting | 3.566 | 7.233 | 0.8879 | 0.4381 | 2.538 | 0.8945 | 12802 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | persistence_reference | 3.929 | 7.544 | 0.878 | 0.4834 | 3.221 | 0.8846 | 12802 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | **random_forest** | 3.437 | 7.006 | 0.8948 | 0.4225 | 2.276 | 0.9013 | 12802 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | gradient_boosting | 4.691 | 10.57 | 0.7605 | 0.5772 | 3.856 | 0.7658 | 12801 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | persistence_reference | 5.118 | 10.88 | 0.7462 | 0.6298 | 4.476 | 0.7499 | 12801 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | **random_forest** | 4.8 | 10.55 | 0.7616 | 0.5897 | 3.898 | 0.7666 | 12801 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | gradient_boosting | 5.842 | 12.48 | 0.6663 | 0.7184 | 5.138 | 0.6711 | 12796 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | persistence_reference | 6.242 | 13.33 | 0.6192 | 0.7683 | 5.648 | 0.6216 | 12796 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | **random_forest** | 6.05 | 12.85 | 0.6462 | 0.7436 | 5.265 | 0.6506 | 12796 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | **gradient_boosting** | 8.426 | 15.82 | 0.4637 | 1.036 | 7.834 | 0.468 | 12792 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | persistence_reference | 9.181 | 18.18 | 0.2924 | 1.131 | 8.645 | 0.2922 | 12792 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | random_forest | 8.79 | 16.54 | 0.4142 | 1.082 | 8.174 | 0.4183 | 12792 |

Block composition (why an R-squared reads the way it does):

| Horizon | Train | Validation | Test | Embargo | Purged | Total rows |
|---|---|---|---|---|---|---|
| t+5min | 23,507 rows, 14 regime(s) | 6,404 rows, 14 regime(s) | 12,827 rows, 14 regime(s) | 10 min | 20 | 42738 |
| t+10min | 23,499 rows, 14 regime(s) | 6,398 rows, 14 regime(s) | 12,826 rows, 14 regime(s) | 15 min | 30 | 42723 |
| t+15min | 23,476 rows, 14 regime(s) | 6,381 rows, 14 regime(s) | 12,821 rows, 14 regime(s) | 30 min | 60 | 42678 |
| t+30min | 23,453 rows, 14 regime(s) | 6,363 rows, 14 regime(s) | 12,817 rows, 14 regime(s) | 45 min | 90 | 42633 |


#### Metrics — Scenario-holdout split (PRD 13.3 split 2)

**test block**

| Target | Horizon | Model | MAE | RMSE | R2 | MAPE % | MAE vs truth | R2 vs truth | Rows |
|---|---|---|---|---|---|---|---|---|---|
| `burning_zone_temperature` | t+5min | persistence_reference | 6.795 | 8.508 | 0.5152 | 0.4692 | 4.928 | 0.6637 | 4166 |
| `burning_zone_temperature` | t+5min | **random_forest** | 5.156 | 6.484 | 0.7185 | 0.3563 | 1.917 | 0.9432 | 4166 |
| `burning_zone_temperature` | t+10min | **gradient_boosting** | 5.269 | 6.619 | 0.6947 | 0.3642 | 2.197 | 0.9253 | 4165 |
| `burning_zone_temperature` | t+10min | persistence_reference | 6.941 | 8.786 | 0.4621 | 0.4793 | 5.192 | 0.5954 | 4165 |
| `burning_zone_temperature` | t+15min | persistence_reference | 7.351 | 9.328 | 0.3737 | 0.5076 | 5.576 | 0.4925 | 4166 |
| `burning_zone_temperature` | t+15min | **random_forest** | 5.567 | 7.029 | 0.6444 | 0.3849 | 2.688 | 0.8638 | 4166 |
| `burning_zone_temperature` | t+30min | persistence_reference | 8.86 | 12.02 | 0.02546 | 0.6124 | 7.108 | 0.05702 | 4164 |
| `burning_zone_temperature` | t+30min | **random_forest** | 7.312 | 9.972 | 0.3289 | 0.5062 | 4.965 | 0.4435 | 4164 |
| `clinker_production_tph` | t+5min | persistence_reference | 0.6175 | 0.7726 | -0.5887 | 0.5155 | 0.4324 | -2.214 | 4159 |
| `clinker_production_tph` | t+5min | **random_forest** | 0.4463 | 0.5615 | 0.161 | 0.3724 | 0.05912 | 0.7502 | 4159 |
| `clinker_production_tph` | t+10min | **gradient_boosting** | 0.4483 | 0.563 | 0.1005 | 0.3741 | 0.08067 | 0.6157 | 4159 |
| `clinker_production_tph` | t+10min | persistence_reference | 0.609 | 0.763 | -0.6523 | 0.5084 | 0.4378 | -3.249 | 4159 |
| `clinker_production_tph` | t+15min | **gradient_boosting** | 0.4481 | 0.5663 | 0.07867 | 0.3739 | 0.07418 | 0.4586 | 4159 |
| `clinker_production_tph` | t+15min | persistence_reference | 0.6139 | 0.773 | -0.717 | 0.5126 | 0.447 | -3.869 | 4159 |
| `clinker_production_tph` | t+30min | persistence_reference | 0.6559 | 0.8656 | -0.7134 | 0.5469 | 0.4931 | -1.901 | 4160 |
| `clinker_production_tph` | t+30min | **random_forest** | 0.4872 | 0.6776 | -0.0499 | 0.4061 | 0.1711 | -0.124 | 4160 |
| `oxygen_percent` | t+5min | **gradient_boosting** | 0.2981 | 0.4398 | -1.518 | 14.55 | 0.3036 | -1.528 | 4161 |
| `oxygen_percent` | t+5min | persistence_reference | 0.2879 | 0.4174 | -1.268 | 13.92 | 0.2819 | -1.066 | 4161 |
| `oxygen_percent` | t+10min | persistence_reference | 0.2431 | 0.3657 | -0.7486 | 12.19 | 0.2635 | -0.8923 | 4161 |
| `oxygen_percent` | t+10min | **random_forest** | 0.2672 | 0.4253 | -1.365 | 13.27 | 0.2714 | -1.32 | 4161 |
| `oxygen_percent` | t+15min | persistence_reference | 0.1944 | 0.3151 | -0.2297 | n/a | 0.1734 | 0.01177 | 4161 |
| `oxygen_percent` | t+15min | **random_forest** | 0.3269 | 0.53 | -2.479 | n/a | 0.3019 | -1.913 | 4161 |
| `oxygen_percent` | t+30min | **gradient_boosting** | 0.3053 | 0.4675 | -1.247 | n/a | 0.3025 | -1.202 | 4162 |
| `oxygen_percent` | t+30min | persistence_reference | 0.2679 | 0.4177 | -0.7932 | n/a | 0.2526 | -0.5839 | 4162 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | persistence_reference | 3.203 | 4.825 | 0.7149 | 0.3971 | 2.407 | 0.768 | 4163 |
| `thermal_energy_kcal_per_kg_clinker` | t+5min | **random_forest** | 3.154 | 5.088 | 0.683 | 0.391 | 2.031 | 0.734 | 4163 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | persistence_reference | 3.579 | 5.936 | 0.5843 | 0.4432 | 2.81 | 0.6259 | 4163 |
| `thermal_energy_kcal_per_kg_clinker` | t+10min | **random_forest** | 4.057 | 6.493 | 0.5025 | 0.5024 | 3.221 | 0.5399 | 4163 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | persistence_reference | 3.999 | 6.974 | 0.4618 | 0.4946 | 3.252 | 0.4975 | 4163 |
| `thermal_energy_kcal_per_kg_clinker` | t+15min | **random_forest** | 6.122 | 8.445 | 0.211 | 0.7594 | 5.709 | 0.2335 | 4163 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | **gradient_boosting** | 5.139 | 9.252 | 0.2538 | 0.6364 | 4.455 | 0.2688 | 4162 |
| `thermal_energy_kcal_per_kg_clinker` | t+30min | persistence_reference | 5.371 | 9.655 | 0.1874 | 0.6641 | 4.719 | 0.1983 | 4162 |

Block composition (why an R-squared reads the way it does):

| Horizon | Train | Validation | Test | Embargo | Purged | Total rows |
|---|---|---|---|---|---|---|
| t+5min | 38,378 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 10 min | 210 | 42548 |
| t+10min | 38,268 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 15 min | 315 | 42438 |
| t+15min | 37,938 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 30 min | 630 | 42108 |
| t+30min | 37,608 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 45 min | 945 | 41778 |


### Model A — mill

#### Model validity domain

- **Training rows** (at the longest horizon, t+30min): 11,698
- **Training data range**: `2024-01-01 07:27:00+00:00` to `2024-01-17 14:19:00+00:00`
- **Operating regimes represented in training**: `Fan instability`, `Feed disturbance`, `High fuel condition`, `High oxygen condition`, `High separator speed`, `Low oxygen condition`, `Low separator speed`, `Mill overload`, `Mill underload`, `Normal - high production`, `Normal - low production`, `Normal - medium production`, `Sensor drift`, `Temperature disturbance`
- **Targets**: `mill_motor_power_kw`, `simulated_blaine_cm2_g`, `specific_power_consumption_kwh_t`
- **Horizons**: t+5min, t+10min, t+15min, t+30min
- **Feature columns**: 67 (13 current-value + lags of 1 min, 5 min, 15 min)

Variable ranges seen in training (the PRD 14.3 check-1 envelope):
| Variable | Min | Max |
|---|---|---|
| `additive_feed_rate` | 6.18 | 13.72 |
| `cement_production_tph` | 82.42 | 164.2 |
| `clinker_feed_rate` | 72.88 | 150.7 |
| `fan_speed` | 70.1 | 89 |
| `gas_flow` | 1.854e+05 | 2.168e+05 |
| `gypsum_feed_rate` | 3.226 | 6.756 |
| `mill_differential_pressure` | 32.8 | 77.5 |
| `mill_feed_rate_tph` | 82 | 165 |
| `mill_motor_power_kw` | 2,274 | 4,892 |
| `residue_percent` | 5.3 | 19.4 |
| `separator_speed_rpm` | 69.4 | 130.6 |
| `simulated_blaine_cm2_g` | 2,540 | 4,240 |
| `specific_power_consumption_kwh_t` | 25.58 | 47.3 |

#### Method and family selection

One `RandomForestRegressor` (the PRD 13.1 baseline, always trained) and one `GradientBoostingRegressor` per (target, horizon), selected on held-out MAE from the chronological validation block. `LightGBM` is not used: PRD 13.1 admits it only if it measurably beats both, which was never tested here, so it is absent rather than half-integrated. A **persistence reference** is scored alongside but is never selectable.

| Target | Horizon | Selected | random_forest MAE | gradient_boosting MAE | Rule |
|---|---|---|---|---|---|
| `mill_motor_power_kw` | t+5min | **gradient_boosting** | 32.01 | 30.48 | mae on 6,392 validation rows |
| `mill_motor_power_kw` | t+10min | **gradient_boosting** | 39.09 | 38.8 | mae on 6,386 validation rows |
| `mill_motor_power_kw` | t+15min | **random_forest** | 49.27 | 50.21 | mae on 6,369 validation rows |
| `mill_motor_power_kw` | t+30min | **random_forest** | 86.22 | 88.62 | mae on 6,351 validation rows |
| `simulated_blaine_cm2_g` | t+5min | **gradient_boosting** | 31.09 | 30.65 | mae on 6,393 validation rows |
| `simulated_blaine_cm2_g` | t+10min | **gradient_boosting** | 32.62 | 31.95 | mae on 6,387 validation rows |
| `simulated_blaine_cm2_g` | t+15min | **random_forest** | 35.37 | 35.57 | mae on 6,370 validation rows |
| `simulated_blaine_cm2_g` | t+30min | **random_forest** | 59.33 | 59.76 | mae on 6,352 validation rows |
| `specific_power_consumption_kwh_t` | t+5min | **gradient_boosting** | 0.2041 | 0.2027 | mae on 6,386 validation rows |
| `specific_power_consumption_kwh_t` | t+10min | **gradient_boosting** | 0.2371 | 0.2358 | mae on 6,380 validation rows |
| `specific_power_consumption_kwh_t` | t+15min | **gradient_boosting** | 0.3003 | 0.2926 | mae on 6,363 validation rows |
| `specific_power_consumption_kwh_t` | t+30min | **gradient_boosting** | 0.6886 | 0.6719 | mae on 6,345 validation rows |

#### Uncertainty method (PRD 13.1.1)

| Target | Horizon | Method | Bootstrap members |
|---|---|---|---|
| `mill_motor_power_kw` | t+5min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `mill_motor_power_kw` | t+10min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `mill_motor_power_kw` | t+15min | `random_forest_tree_spread` | n/a |
| `mill_motor_power_kw` | t+30min | `random_forest_tree_spread` | n/a |
| `simulated_blaine_cm2_g` | t+5min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `simulated_blaine_cm2_g` | t+10min | `gradient_boosting_bootstrap_ensemble` | 20 *(config)* |
| `simulated_blaine_cm2_g` | t+15min | `random_forest_tree_spread` | n/a |
| `simulated_blaine_cm2_g` | t+30min | `random_forest_tree_spread` | n/a |
| `specific_power_consumption_kwh_t` | t+5min | `gradient_boosting_bootstrap_ensemble` | 20 |
| `specific_power_consumption_kwh_t` | t+10min | `gradient_boosting_bootstrap_ensemble` | 20 |
| `specific_power_consumption_kwh_t` | t+15min | `gradient_boosting_bootstrap_ensemble` | 20 |
| `specific_power_consumption_kwh_t` | t+30min | `gradient_boosting_bootstrap_ensemble` | 20 |

`random_forest_tree_spread` is the spread across a fitted forest's own trees, so it needs no extra fit and has no member count. `gradient_boosting_bootstrap_ensemble` refits the selected gradient-boosting estimator on bootstrap resamples, and is built on first use rather than during training - a member count marked *(config)* is the configured size of an ensemble not yet materialised.

The spread is reported as `value ± spread` in the target's own unit and is turned into the categorical **Recommendation Quality** label (`HIGH` / `MEDIUM` / `LOW`) required by FR-23. It is deliberately **not** rendered as a confidence percentage: the spread of an ensemble is not a calibrated probability, and a synthetic-only model has no basis on which to claim one. The category thresholds live in `configs/ml.yaml`, and any factor that cannot be assessed in the current context caps the label at `MEDIUM` rather than allowing `HIGH`.

- `HIGH` — Tight model-ensemble spread, close agreement between model families, comfortable margin to every hard constraint, and clearly inside the training distribution.
- `MEDIUM` — Moderate ensemble spread, some disagreement between model families, or a narrow margin to a hard constraint / the edge of the training distribution.
- `LOW` — Wide ensemble spread, disagreeing model families, a very narrow constraint margin, or an operating point far from the training distribution.

#### Metrics — Chronological split (PRD 13.3 split 1)

**validation block**

| Target | Horizon | Model | MAE | RMSE | R2 | MAPE % | MAE vs truth | R2 vs truth | Rows |
|---|---|---|---|---|---|---|---|---|---|
| `mill_motor_power_kw` | t+5min | gradient_boosting | 30.48 | 44.14 | 0.9877 | 0.8961 | 13.4 | 0.9929 | 6392 |
| `mill_motor_power_kw` | t+5min | random_forest | 32.01 | 53.73 | 0.9817 | 0.9418 | 14.11 | 0.9864 | 6392 |
| `mill_motor_power_kw` | t+10min | gradient_boosting | 38.8 | 77.64 | 0.9618 | 1.147 | 22.98 | 0.9657 | 6386 |
| `mill_motor_power_kw` | t+10min | random_forest | 39.09 | 84.19 | 0.9551 | 1.156 | 22.34 | 0.9588 | 6386 |
| `mill_motor_power_kw` | t+15min | gradient_boosting | 50.21 | 119 | 0.9104 | 1.501 | 36.16 | 0.9139 | 6369 |
| `mill_motor_power_kw` | t+15min | random_forest | 49.27 | 119.2 | 0.9101 | 1.469 | 34.59 | 0.9132 | 6369 |
| `mill_motor_power_kw` | t+30min | gradient_boosting | 88.62 | 196.4 | 0.7556 | 2.666 | 80.1 | 0.7593 | 6351 |
| `mill_motor_power_kw` | t+30min | random_forest | 86.22 | 194.6 | 0.76 | 2.59 | 77.43 | 0.7641 | 6351 |
| `simulated_blaine_cm2_g` | t+5min | gradient_boosting | 30.65 | 38.78 | 0.987 | 0.911 | 19.8 | 0.9831 | 6393 |
| `simulated_blaine_cm2_g` | t+5min | random_forest | 31.09 | 40.13 | 0.986 | 0.9246 | 20.37 | 0.9802 | 6393 |
| `simulated_blaine_cm2_g` | t+10min | gradient_boosting | 31.95 | 41.47 | 0.9851 | 0.9504 | 21.6 | 0.9784 | 6387 |
| `simulated_blaine_cm2_g` | t+10min | random_forest | 32.62 | 44.18 | 0.9831 | 0.9708 | 21.81 | 0.9753 | 6387 |
| `simulated_blaine_cm2_g` | t+15min | gradient_boosting | 35.57 | 51.03 | 0.9774 | 1.057 | 26.22 | 0.9633 | 6370 |
| `simulated_blaine_cm2_g` | t+15min | random_forest | 35.37 | 52.04 | 0.9765 | 1.054 | 25.75 | 0.9613 | 6370 |
| `simulated_blaine_cm2_g` | t+30min | gradient_boosting | 59.76 | 115.1 | 0.8846 | 1.789 | 55.25 | 0.8417 | 6352 |
| `simulated_blaine_cm2_g` | t+30min | random_forest | 59.33 | 118.2 | 0.8785 | 1.778 | 55.31 | 0.8334 | 6352 |
| `specific_power_consumption_kwh_t` | t+5min | gradient_boosting | 0.2027 | 0.2787 | 0.9957 | 0.6008 | 0.09958 | 0.9976 | 6386 |
| `specific_power_consumption_kwh_t` | t+5min | random_forest | 0.2041 | 0.3227 | 0.9943 | 0.605 | 0.09521 | 0.996 | 6386 |
| `specific_power_consumption_kwh_t` | t+10min | gradient_boosting | 0.2358 | 0.3904 | 0.9916 | 0.6973 | 0.1387 | 0.9933 | 6380 |
| `specific_power_consumption_kwh_t` | t+10min | random_forest | 0.2371 | 0.4647 | 0.9881 | 0.705 | 0.1313 | 0.9898 | 6380 |
| `specific_power_consumption_kwh_t` | t+15min | gradient_boosting | 0.2926 | 0.6085 | 0.9796 | 0.8645 | 0.204 | 0.981 | 6363 |
| `specific_power_consumption_kwh_t` | t+15min | random_forest | 0.3003 | 0.6649 | 0.9756 | 0.895 | 0.2032 | 0.977 | 6363 |
| `specific_power_consumption_kwh_t` | t+30min | gradient_boosting | 0.6719 | 1.508 | 0.8741 | 2.006 | 0.6163 | 0.8741 | 6345 |
| `specific_power_consumption_kwh_t` | t+30min | random_forest | 0.6886 | 1.602 | 0.8579 | 2.066 | 0.6202 | 0.8578 | 6345 |

**test block**

| Target | Horizon | Model | MAE | RMSE | R2 | MAPE % | MAE vs truth | R2 vs truth | Rows |
|---|---|---|---|---|---|---|---|---|---|
| `mill_motor_power_kw` | t+5min | **gradient_boosting** | 30.49 | 45.9 | 0.9885 | 0.8877 | 13.38 | 0.9928 | 12799 |
| `mill_motor_power_kw` | t+5min | persistence_reference | 47.6 | 83.23 | 0.9622 | 1.374 | 39.59 | 0.9653 | 12799 |
| `mill_motor_power_kw` | t+5min | random_forest | 31.63 | 56.62 | 0.9825 | 0.9145 | 13.33 | 0.9865 | 12799 |
| `mill_motor_power_kw` | t+10min | **gradient_boosting** | 39.57 | 86.04 | 0.9596 | 1.155 | 23.8 | 0.9629 | 12798 |
| `mill_motor_power_kw` | t+10min | persistence_reference | 64.46 | 135.8 | 0.8992 | 1.853 | 56.65 | 0.9017 | 12798 |
| `mill_motor_power_kw` | t+10min | random_forest | 38.5 | 90.73 | 0.955 | 1.118 | 21.46 | 0.9583 | 12798 |
| `mill_motor_power_kw` | t+15min | gradient_boosting | 52.18 | 132.4 | 0.9042 | 1.529 | 38.28 | 0.9075 | 12793 |
| `mill_motor_power_kw` | t+15min | persistence_reference | 79.9 | 175.9 | 0.8309 | 2.3 | 72.32 | 0.8332 | 12793 |
| `mill_motor_power_kw` | t+15min | **random_forest** | 49.69 | 124.2 | 0.9156 | 1.444 | 34.83 | 0.9191 | 12793 |
| `mill_motor_power_kw` | t+30min | gradient_boosting | 91.65 | 199.5 | 0.7824 | 2.682 | 83.24 | 0.7853 | 12789 |
| `mill_motor_power_kw` | t+30min | persistence_reference | 118.3 | 252.4 | 0.6518 | 3.422 | 111 | 0.6529 | 12789 |
| `mill_motor_power_kw` | t+30min | **random_forest** | 87.88 | 194.7 | 0.7927 | 2.559 | 79.37 | 0.7958 | 12789 |
| `simulated_blaine_cm2_g` | t+5min | **gradient_boosting** | 30.41 | 39.16 | 0.9885 | 0.8988 | 16.67 | 0.9877 | 12800 |
| `simulated_blaine_cm2_g` | t+5min | persistence_reference | 44.36 | 58.38 | 0.9744 | 1.31 | 44.33 | 0.9621 | 12800 |
| `simulated_blaine_cm2_g` | t+5min | random_forest | 30.82 | 41.03 | 0.9873 | 0.9105 | 17.63 | 0.9846 | 12800 |
| `simulated_blaine_cm2_g` | t+10min | **gradient_boosting** | 31.76 | 42.11 | 0.9867 | 0.939 | 18.81 | 0.9832 | 12799 |
| `simulated_blaine_cm2_g` | t+10min | persistence_reference | 52.87 | 78.41 | 0.9537 | 1.565 | 53.54 | 0.9307 | 12799 |
| `simulated_blaine_cm2_g` | t+10min | random_forest | 31.66 | 43.82 | 0.9856 | 0.9357 | 18.74 | 0.9815 | 12799 |
| `simulated_blaine_cm2_g` | t+15min | gradient_boosting | 34.95 | 49.94 | 0.9812 | 1.031 | 23.37 | 0.9728 | 12794 |
| `simulated_blaine_cm2_g` | t+15min | persistence_reference | 61.78 | 101 | 0.9231 | 1.833 | 62.88 | 0.892 | 12794 |
| `simulated_blaine_cm2_g` | t+15min | **random_forest** | 34.32 | 50.41 | 0.9809 | 1.016 | 22.25 | 0.9726 | 12794 |
| `simulated_blaine_cm2_g` | t+30min | gradient_boosting | 58.09 | 108.7 | 0.911 | 1.714 | 51.57 | 0.882 | 12790 |
| `simulated_blaine_cm2_g` | t+30min | persistence_reference | 89.51 | 164.3 | 0.7966 | 2.668 | 90.98 | 0.7536 | 12790 |
| `simulated_blaine_cm2_g` | t+30min | **random_forest** | 56.86 | 109.9 | 0.909 | 1.68 | 49.6 | 0.8791 | 12790 |
| `specific_power_consumption_kwh_t` | t+5min | **gradient_boosting** | 0.1985 | 0.28 | 0.9962 | 0.5859 | 0.08908 | 0.9979 | 12806 |
| `specific_power_consumption_kwh_t` | t+5min | persistence_reference | 0.3385 | 0.5574 | 0.9851 | 0.9986 | 0.2922 | 0.986 | 12806 |
| `specific_power_consumption_kwh_t` | t+5min | random_forest | 0.2012 | 0.332 | 0.9947 | 0.5937 | 0.0876 | 0.9963 | 12806 |
| `specific_power_consumption_kwh_t` | t+10min | **gradient_boosting** | 0.2348 | 0.3933 | 0.9926 | 0.6885 | 0.1307 | 0.9941 | 12805 |
| `specific_power_consumption_kwh_t` | t+10min | persistence_reference | 0.4488 | 0.9168 | 0.9598 | 1.325 | 0.4098 | 0.96 | 12805 |
| `specific_power_consumption_kwh_t` | t+10min | random_forest | 0.2323 | 0.4688 | 0.9895 | 0.6839 | 0.1237 | 0.9909 | 12805 |
| `specific_power_consumption_kwh_t` | t+15min | **gradient_boosting** | 0.2903 | 0.5846 | 0.9836 | 0.8456 | 0.1964 | 0.9849 | 12800 |
| `specific_power_consumption_kwh_t` | t+15min | persistence_reference | 0.5666 | 1.258 | 0.9242 | 1.677 | 0.5246 | 0.9242 | 12800 |
| `specific_power_consumption_kwh_t` | t+15min | random_forest | 0.288 | 0.641 | 0.9803 | 0.8447 | 0.188 | 0.9814 | 12800 |
| `specific_power_consumption_kwh_t` | t+30min | **gradient_boosting** | 0.6633 | 1.456 | 0.8983 | 1.945 | 0.6019 | 0.8988 | 12796 |
| `specific_power_consumption_kwh_t` | t+30min | persistence_reference | 0.9385 | 2.108 | 0.7869 | 2.799 | 0.9004 | 0.7864 | 12796 |
| `specific_power_consumption_kwh_t` | t+30min | random_forest | 0.6459 | 1.5 | 0.8921 | 1.903 | 0.5729 | 0.8926 | 12796 |

Block composition (why an R-squared reads the way it does):

| Horizon | Train | Validation | Test | Embargo | Purged | Total rows |
|---|---|---|---|---|---|---|
| t+5min | 23,507 rows, 14 regime(s) | 6,404 rows, 14 regime(s) | 12,827 rows, 14 regime(s) | 10 min | 20 | 42738 |
| t+10min | 23,499 rows, 14 regime(s) | 6,398 rows, 14 regime(s) | 12,826 rows, 14 regime(s) | 15 min | 30 | 42723 |
| t+15min | 23,476 rows, 14 regime(s) | 6,381 rows, 14 regime(s) | 12,821 rows, 14 regime(s) | 30 min | 60 | 42678 |
| t+30min | 23,453 rows, 14 regime(s) | 6,363 rows, 14 regime(s) | 12,817 rows, 14 regime(s) | 45 min | 90 | 42633 |


#### Metrics — Scenario-holdout split (PRD 13.3 split 2)

**test block**

| Target | Horizon | Model | MAE | RMSE | R2 | MAPE % | MAE vs truth | R2 vs truth | Rows |
|---|---|---|---|---|---|---|---|---|---|
| `mill_motor_power_kw` | t+5min | **gradient_boosting** | 27.5 | 39.06 | 0.8765 | 0.7807 | 7.439 | 0.9422 | 4161 |
| `mill_motor_power_kw` | t+5min | persistence_reference | 40.95 | 62.92 | 0.6795 | 1.158 | 31.69 | 0.7204 | 4161 |
| `mill_motor_power_kw` | t+10min | **gradient_boosting** | 32.5 | 63.29 | 0.6021 | 0.9326 | 13.46 | 0.6463 | 4161 |
| `mill_motor_power_kw` | t+10min | persistence_reference | 51.58 | 99.6 | 0.01467 | 1.46 | 42.52 | -0.003079 | 4161 |
| `mill_motor_power_kw` | t+15min | persistence_reference | 63.29 | 135.4 | -0.4577 | 1.824 | 54.84 | -0.5048 | 4162 |
| `mill_motor_power_kw` | t+15min | **random_forest** | 38.94 | 96.57 | 0.2582 | 1.148 | 19.34 | 0.271 | 4162 |
| `mill_motor_power_kw` | t+30min | persistence_reference | 99.66 | 214.1 | -0.4669 | 2.937 | 91.76 | -0.479 | 4162 |
| `mill_motor_power_kw` | t+30min | **random_forest** | 69.14 | 176.1 | 0.007479 | 2.075 | 52.55 | 0.008047 | 4162 |
| `simulated_blaine_cm2_g` | t+5min | **gradient_boosting** | 29.71 | 37.43 | 0.8121 | 0.8706 | 9.941 | 0.828 | 4160 |
| `simulated_blaine_cm2_g` | t+5min | persistence_reference | 42.06 | 53.97 | 0.6094 | 1.231 | 35.25 | 0.2214 | 4160 |
| `simulated_blaine_cm2_g` | t+10min | **gradient_boosting** | 30.24 | 38.56 | 0.6857 | 0.886 | 11.12 | 0.5201 | 4160 |
| `simulated_blaine_cm2_g` | t+10min | persistence_reference | 46.38 | 65.75 | 0.08639 | 1.354 | 40.8 | -1.53 | 4160 |
| `simulated_blaine_cm2_g` | t+15min | persistence_reference | 52.38 | 81.53 | -0.8393 | 1.529 | 47.79 | -2.148 | 4160 |
| `simulated_blaine_cm2_g` | t+15min | **random_forest** | 32.8 | 46.01 | 0.4142 | 0.9598 | 13.55 | 0.1759 | 4160 |
| `simulated_blaine_cm2_g` | t+30min | persistence_reference | 75.76 | 139.4 | -0.8024 | 2.201 | 74.35 | -0.6705 | 4160 |
| `simulated_blaine_cm2_g` | t+30min | **random_forest** | 50.97 | 104.4 | -0.01087 | 1.477 | 36.89 | -0.01604 | 4160 |
| `specific_power_consumption_kwh_t` | t+5min | **gradient_boosting** | 0.3196 | 0.4437 | 0.7731 | 0.9325 | 0.252 | 0.7879 | 4162 |
| `specific_power_consumption_kwh_t` | t+5min | persistence_reference | 0.4643 | 0.6612 | 0.4962 | 1.352 | 0.4411 | 0.4824 | 4162 |
| `specific_power_consumption_kwh_t` | t+10min | **gradient_boosting** | 0.3142 | 0.4712 | 0.5899 | 0.916 | 0.2515 | 0.5854 | 4162 |
| `specific_power_consumption_kwh_t` | t+10min | persistence_reference | 0.4635 | 0.7898 | -0.1523 | 1.345 | 0.4558 | -0.2712 | 4162 |
| `specific_power_consumption_kwh_t` | t+15min | **gradient_boosting** | 0.3404 | 0.6297 | 0.2254 | 0.9885 | 0.2642 | 0.2414 | 4162 |
| `specific_power_consumption_kwh_t` | t+15min | persistence_reference | 0.4793 | 0.9942 | -0.9312 | 1.385 | 0.4431 | -1.011 | 4162 |
| `specific_power_consumption_kwh_t` | t+30min | **gradient_boosting** | 0.6691 | 1.496 | -0.09156 | 1.904 | 0.6096 | -0.09518 | 4160 |
| `specific_power_consumption_kwh_t` | t+30min | persistence_reference | 0.8567 | 1.802 | -0.5835 | 2.454 | 0.8259 | -0.5944 | 4160 |

Block composition (why an R-squared reads the way it does):

| Horizon | Train | Validation | Test | Embargo | Purged | Total rows |
|---|---|---|---|---|---|---|
| t+5min | 38,378 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 10 min | 210 | 42548 |
| t+10min | 38,268 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 15 min | 315 | 42438 |
| t+15min | 37,938 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 30 min | 630 | 42108 |
| t+30min | 37,608 rows, 12 regime(s) | 0 rows | 4,170 rows, 2 regime(s) | 45 min | 945 | 41778 |


---

## Model B — anomaly detection (PRD 13.2, 15)

### Model B — kiln

#### Model validity domain

- **Fitted on**: 20398 normal-regime rows (`injected_fault` null and `operating_regime` in the configured normal set), with the `Startup transition` regime additionally withheld
- **Feature space**: 16 instantaneous tags (7 of them manipulated variables). No lags: the detector answers "is this minute abnormal", so a lagged feature would make its answer depend on a window rather than on the row it labels
- **Sampling interval**: 1 min
- **Statuses emitted**: `NORMAL`, `WARNING`
- **Anomaly kinds emitted**: `none`, `sensor_or_data`, `process`, `undetermined`
- **Affected variables listed**: at most 5

#### Method

**Method 1 (primary, PRD 13.2).** `IsolationForest` fitted on normal-operation rows and scored on all data: 200 trees, contamination `0.03`, seed `42`. Two thresholds are derived from the fitted normal scores and reported in the registry: a flag threshold (-0.5083) that raises the banner and a stricter out-of-distribution threshold (-0.5249, the 2th percentile of the normal scores) that PRD 14.3 check 3 uses as its gate — one implementation, two consumers.

**Method 2 (secondary, always on, PRD 13.2).** Per-tag statistical process control: a 120-minute rolling mean and an EWMA (alpha `0.2`) against ±3.0σ limits, the baseline always `shift(1)`-ed so a sample is never inside its own control limits. This layer answers *which variable is out of band* and ranks the PRD 15 affected-variable list. It does **not** vote on the banner.

That division of labour was measured, not assumed. Every row below is scored on this run's primary block, and all three alternatives are published under `detection.alternates` in `reports/metrics/model_b_metrics.json`, so the choice stays auditable:

| Decision | Precision | Recall | F1 | FPR | Role |
|---|---|---|---|---|---|
| **forest (adopted)** | 0.9 | 0.545 | 0.679 | 0.0316 | PRD 13.2 Method 1, raises the banner |
| `spc_single_sample` | 0.407 | 0.2 | 0.268 | 0.151 | method 2 alone (any single SPC violation) |
| `forest_or_spc_single_sample` | 0.676 | 0.644 | 0.66 | 0.16 | union of both configured methods |
| `out_of_distribution_gate` | 0.919 | 0.464 | 0.617 | 0.0213 | same forest score at the PRD 14.3 gate percentile |

Letting the control charts raise the banner as well buys recall (0.545 → 0.644) but lowers F1 (0.679 → 0.66) at a worse false-positive rate (0.0316 → 0.16), so PRD 13.2's "Method 1 (primary)" is taken literally.

#### Detection metrics (PRD 22)

| Block | Rows scored | Precision | Recall | F1 | FPR | TP | FP | FN |
|---|---|---|---|---|---|---|---|---|
| **all_rows** | 41,451 | 0.9 | 0.545 | 0.679 | 0.0316 | 7725 | 863 | 6450 |
| chronological | 12,576 | 0.927 | 0.556 | 0.695 | 0.0365 | 3166 | 251 | 2532 |
| scenario_holdout | 4,029 | 1 | 0.408 | 0.58 | n/a | 1644 | 0 | 2385 |

Ground truth is `injected_fault` being non-null. `all_rows` is the primary block because it is exactly what PRD 13.2 specifies; the other two are the PRD 13.3 splits applied to the detector, each with its own independent fit. An `n/a` false-positive rate means the block contained no fault-free rows — which is the expected outcome for a scenario holdout whose rows are, by construction, all faulted.

Startup ramp (`Startup transition`, excluded from the table above): 106 of 416 rows reported. Excluded from the metrics above: a legitimate transient that carries no injected_fault and is deliberately not in the training set.

#### Per-regime behaviour

| Regime | Rows | Reported | Rate | Metric | Fault on this unit |
|---|---|---|---|---|---|
| `Fan instability` | 1,988 | 171 | 0.086 | recall | yes |
| `Feed disturbance` | 2,002 | 109 | 0.0544 | recall | yes |
| `High fuel condition` | 2,029 | 1,897 | 0.935 | recall | yes |
| `High oxygen condition` | 2,019 | 1,987 | 0.984 | recall | yes |
| `High separator speed` | 2,249 | 17 | 0.00756 | false_positive_rate | no |
| `Low oxygen condition` | 2,015 | 2,007 | 0.996 | recall | yes |
| `Low separator speed` | 2,000 | 11 | 0.0055 | false_positive_rate | no |
| `Mill overload` | 1,998 | 22 | 0.011 | false_positive_rate | no |
| `Mill underload` | 2,102 | 16 | 0.00761 | false_positive_rate | no |
| `Normal - high production` | 6,013 | 380 | 0.0632 | false_positive_rate | no |
| `Normal - low production` | 6,057 | 304 | 0.0502 | false_positive_rate | no |
| `Normal - medium production` | 6,857 | 113 | 0.0165 | false_positive_rate | no |
| `Sensor drift` | 2,081 | 6 | 0.00288 | recall | yes |
| `Temperature disturbance` | 2,041 | 1,548 | 0.758 | recall | yes |

`injected_fault` is per-unit while `operating_regime` is plant-level, so a regime that perturbs the *other* unit appears here with `metric = false_positive_rate`: those rows are legitimately normal for this unit and a low rate is the good outcome. Read the `Metric` column before reading the rate.

#### Sensor-versus-process discrimination

Positive class: `sensor_or_data`. Sensor-layer regimes: `sensor_drift`.

| Scope | Rows | Precision | Recall | F1 | Base rate | No chart evidence |
|---|---|---|---|---|---|---|
| reported rows (operational) | 7,725 | 0 | 0 | n/a | 0.000777 | 0 |
| all fault rows (diagnostic) | 14,175 | 0.152 | 0.313 | 0.205 | 0.147 | 0 |

**Sensor claim reported to the UI: no.** Three ASSUMPTION signatures of anomaly.sensor_discrimination, measured on information available at the row itself: persistent one-sided displacement of the leading tag's EWMA control chart, quiet manipulated variables, and few corroborating out-of-band tags (PRD 11.4 regime 14 / PRD 15 hypothesis wording). Scored against injected_fault membership of features.sensor_layer_faults.

Compare *Precision* against *Base rate*: the rule is only informative where the former exceeds the latter by more than sampling noise. Neither scope clears it by that margin here (two binomial standard errors of the null), which is why the claim is suppressed. See the limitations section.

#### Output contract (PRD 15)

- **Detected anomaly**
- **Likely cause (model-based hypothesis)**
- **Affected variables**
- **Suggested action (rule-based suggestion, not a diagnosis)**

PRD 15 block. The hypothesis is always hedged and the action is always labelled a rule-based suggestion, never a diagnosis (PRD 15, FR-23).

### Model B — mill

#### Model validity domain

- **Fitted on**: 20633 normal-regime rows (`injected_fault` null and `operating_regime` in the configured normal set), with the `Startup transition` regime additionally withheld
- **Feature space**: 13 instantaneous tags (6 of them manipulated variables). No lags: the detector answers "is this minute abnormal", so a lagged feature would make its answer depend on a window rather than on the row it labels
- **Sampling interval**: 1 min
- **Statuses emitted**: `NORMAL`, `WARNING`
- **Anomaly kinds emitted**: `none`, `sensor_or_data`, `process`, `undetermined`
- **Affected variables listed**: at most 5

#### Method

**Method 1 (primary, PRD 13.2).** `IsolationForest` fitted on normal-operation rows and scored on all data: 200 trees, contamination `0.03`, seed `42`. Two thresholds are derived from the fitted normal scores and reported in the registry: a flag threshold (-0.5006) that raises the banner and a stricter out-of-distribution threshold (-0.5222, the 2th percentile of the normal scores) that PRD 14.3 check 3 uses as its gate — one implementation, two consumers.

**Method 2 (secondary, always on, PRD 13.2).** Per-tag statistical process control: a 120-minute rolling mean and an EWMA (alpha `0.2`) against ±3.0σ limits, the baseline always `shift(1)`-ed so a sample is never inside its own control limits. This layer answers *which variable is out of band* and ranks the PRD 15 affected-variable list. It does **not** vote on the banner.

That division of labour was measured, not assumed. Every row below is scored on this run's primary block, and all three alternatives are published under `detection.alternates` in `reports/metrics/model_b_metrics.json`, so the choice stays auditable:

| Decision | Precision | Recall | F1 | FPR | Role |
|---|---|---|---|---|---|
| **forest (adopted)** | 0.912 | 0.609 | 0.73 | 0.0315 | PRD 13.2 Method 1, raises the banner |
| `spc_single_sample` | 0.482 | 0.182 | 0.265 | 0.105 | method 2 alone (any single SPC violation) |
| `forest_or_spc_single_sample` | 0.768 | 0.658 | 0.709 | 0.106 | union of both configured methods |
| `out_of_distribution_gate` | 0.934 | 0.59 | 0.723 | 0.0223 | same forest score at the PRD 14.3 gate percentile |

Letting the control charts raise the banner as well buys recall (0.609 → 0.658) but lowers F1 (0.73 → 0.709) at a worse false-positive rate (0.0315 → 0.106), so PRD 13.2's "Method 1 (primary)" is taken literally.

#### Detection metrics (PRD 22)

| Block | Rows scored | Precision | Recall | F1 | FPR | TP | FP | FN |
|---|---|---|---|---|---|---|---|---|
| **all_rows** | 41,675 | 0.912 | 0.609 | 0.73 | 0.0315 | 8831 | 856 | 5677 |
| chronological | 12,625 | 0.944 | 0.651 | 0.77 | 0.0363 | 3964 | 237 | 2127 |
| scenario_holdout | 4,068 | 0.876 | 0.0743 | 0.137 | 0.0102 | 149 | 21 | 1856 |

Ground truth is `injected_fault` being non-null. `all_rows` is the primary block because it is exactly what PRD 13.2 specifies; the other two are the PRD 13.3 splits applied to the detector, each with its own independent fit. An `n/a` false-positive rate means the block contained no fault-free rows — which is the expected outcome for a scenario holdout whose rows are, by construction, all faulted.

Startup ramp (`Startup transition`, excluded from the table above): 0 of 423 rows reported. Excluded from the metrics above: a legitimate transient that carries no injected_fault and is deliberately not in the training set.

#### Per-regime behaviour

| Regime | Rows | Reported | Rate | Metric | Fault on this unit |
|---|---|---|---|---|---|
| `Fan instability` | 2,005 | 173 | 0.0863 | recall | yes |
| `Feed disturbance` | 2,016 | 354 | 0.176 | recall | yes |
| `High fuel condition` | 2,055 | 74 | 0.036 | false_positive_rate | no |
| `High oxygen condition` | 2,038 | 137 | 0.0672 | false_positive_rate | no |
| `High separator speed` | 2,262 | 2,174 | 0.961 | recall | yes |
| `Low oxygen condition` | 2,034 | 77 | 0.0379 | false_positive_rate | no |
| `Low separator speed` | 2,026 | 1,984 | 0.979 | recall | yes |
| `Mill overload` | 2,010 | 1,997 | 0.994 | recall | yes |
| `Mill underload` | 2,096 | 2,083 | 0.994 | recall | yes |
| `Normal - high production` | 6,022 | 193 | 0.032 | false_positive_rate | no |
| `Normal - low production` | 6,059 | 243 | 0.0401 | false_positive_rate | no |
| `Normal - medium production` | 6,896 | 110 | 0.016 | false_positive_rate | no |
| `Sensor drift` | 2,093 | 66 | 0.0315 | recall | yes |
| `Temperature disturbance` | 2,063 | 22 | 0.0107 | false_positive_rate | no |

`injected_fault` is per-unit while `operating_regime` is plant-level, so a regime that perturbs the *other* unit appears here with `metric = false_positive_rate`: those rows are legitimately normal for this unit and a low rate is the good outcome. Read the `Metric` column before reading the rate.

#### Sensor-versus-process discrimination

Positive class: `sensor_or_data`. Sensor-layer regimes: `sensor_drift`.

| Scope | Rows | Precision | Recall | F1 | Base rate | No chart evidence |
|---|---|---|---|---|---|---|
| reported rows (operational) | 8,831 | 0 | 0 | n/a | 0.00747 | 0 |
| all fault rows (diagnostic) | 14,508 | 0.144 | 0.324 | 0.2 | 0.144 | 0 |

**Sensor claim reported to the UI: no.** Three ASSUMPTION signatures of anomaly.sensor_discrimination, measured on information available at the row itself: persistent one-sided displacement of the leading tag's EWMA control chart, quiet manipulated variables, and few corroborating out-of-band tags (PRD 11.4 regime 14 / PRD 15 hypothesis wording). Scored against injected_fault membership of features.sensor_layer_faults.

Compare *Precision* against *Base rate*: the rule is only informative where the former exceeds the latter by more than sampling noise. Neither scope clears it by that margin here (two binomial standard errors of the null), which is why the claim is suppressed. See the limitations section.

#### Output contract (PRD 15)

- **Detected anomaly**
- **Likely cause (model-based hypothesis)**
- **Affected variables**
- **Suggested action (rule-based suggestion, not a diagnosis)**

PRD 15 block. The hypothesis is always hedged and the action is always labelled a rule-based suggestion, never a diagnosis (PRD 15, FR-23).

---

## Model C — optimization (PRD 14)

Model C (envelope-protected optimization, PRD 14) is not part of a Model A/B training run and is not described by this card yet. What already exists is the component PRD 14.3 check 3 depends on: Model B's Isolation Forest score, which is the out-of-distribution gate. See *OOD and envelope strategy* below.

---

## OOD and envelope strategy (PRD 14.3)

PRD 14.3 defines three checks before any recommendation is shown. Two of them are properties of the models described above and are therefore stated here:

1. **Training-range check.** Every candidate manipulated-variable value is compared against the *Variable ranges seen in training* table of the relevant Model A pair. Only current-value columns are recorded for this purpose — a candidate setpoint is a value at `t`, not at `t-15 min`.
2. **Constraint check.** Hard constraints are the optimizer's own (Model C, PRD 14.2), not a model property.
3. **Out-of-distribution check.** Model B's Isolation Forest score, thresholded at the configured percentile of the *normal-regime* score distribution. This is a deliberately stricter threshold than the one that raises the anomaly banner: a point can be plausible enough not to alarm an operator and still be too far from the training distribution for a recommendation to be trustworthy.

A candidate that fails check 1 or 3 is either rejected (Normal Mode) or shown with the fixed, non-removable *outside calibrated operating envelope* banner (Experimental Mode). The gate is never a percentage of confidence.

---

## Known limitations

This is a synthetic demonstration environment. The simulation is not calibrated against a real cement plant. The AI models are not production-validated. Energy-saving percentages are simulation results, not guaranteed factory savings. Real deployment requires real historical data, process-engineering validation, plant-specific calibration, OT/IT integration, cybersecurity review, operator validation, safety validation, and commissioning.

### Measured during development

**Sensor drift (PRD 11.4 regime 14) is largely undetectable by either configured method.** Regime 14 adds a slow bias ramp to a reading while leaving the true process untouched. At the magnitudes configured in `configs/scenarios.yaml` (0.45 % O2, 18 K burning-zone temperature, 120 cm2/g Blaine, 6 mbar mill differential pressure, ramped over 3-8 h) the ramp is smaller than each tag's own 1-minute variability, and the SPC layer's 2-hour rolling baseline absorbs most of the offset. On this run the Isolation Forest reports 6 of 2,081 `Sensor drift` rows on `kiln` (recall 0.00288) and 66 of 2,093 `Sensor drift` rows on `mill` (recall 0.0315). The three-signature sensor rule, scored over every fault row that has control-chart evidence, reaches P=0.152 / R=0.313 / F1=0.205 against a 0.147 base rate on `kiln` and P=0.144 / R=0.324 / F1=0.2 against a 0.144 base rate on `mill` - no unit's precision clears its base rate by more than two binomial standard errors of the null, so the rule carries no more information than flagging at the prevalence it is trying to find. Four candidate statistics were measured while building this layer and none separates drift from a genuine process excursion - EWMA chart level, sign persistence of that level, an OLS slope in sigma/hour, and the count of persistently displaced coupled tags all overlap the process-fault distributions. The cause is structural, not a tuning failure: the simulator's own process excursions are themselves smooth dead-time-plus-lag ramps, so "one reading walks one way" does not distinguish an instrument fault from a process deviation. Consequently `anomaly.sensor_discrimination.report_sensor_claim` is **false**: the signature booleans are always reported as evidence, but the PRD 15 hypothesis field says the evidence is inconclusive rather than naming an instrument fault it cannot support. Detecting this regime reliably needs the Phase-2 redundancy/autoencoder method PRD 13.2 defers, or larger configured drift magnitudes.

**R-squared on a narrow evaluation block is a statement about the scenario schedule.** R-squared is measured against the variance of the block being evaluated. A chronological tail that happens to cover one steady regime therefore turns a small MAE into a large negative R-squared. Measured: on a 3-day run `oxygen_percent` at t+30 min scored MAE 0.307 with R-squared -9.3, because the tail's own standard deviation was 0.149 - about a tenth of the training span's 1.55. The same target over the configured 30-day default has a tail containing all 14 regimes and a comparable spread. Every metric row in this card carries a `coverage` block naming the regimes and the target spread of its block, so MAE and R-squared can be read together instead of R-squared alone.

**Metrics are only meaningful at the configured run duration.** A 3-day run does visit all 14 regimes *somewhere*, but any single evaluation block covers only 4-6 of them, and the scenario holdout and the chronological tail are both under-populated - per-regime recall rows come back missing rather than zero. Only the configured `duration_days` (30) gives each block a spread comparable to the training span. Any card generated from a shorter run says so under *Model validity domain* below, and the *Block composition* table states what each block actually contained.

### Inherent to a synthetic environment

- Every relationship the models learned was *written into* the simulator. A model that reproduces it has learned the simulator, which is a necessary condition for being useful on real data and nowhere near a sufficient one.
- The sensor layer's noise, drift, dropout and lag are configured ASSUMPTIONs, so the signal-to-noise ratio the models were trained against is a design choice rather than a measurement of any instrument.
- Fault regimes are injected on a schedule, so their prevalence in the training data (and therefore every precision figure above) reflects `configs/scenarios.yaml`, not a real plant's failure rate.
- No model here has seen a real plant's unmeasured disturbances, raw-material variability, seasonal effects, maintenance history or operator habits.
- Retraining on real data is not a matter of pointing this code at a historian: see the transfer strategy (PRD 21), which requires real historical data, process-engineering validation, plant-specific calibration and operator validation first.

### Additions to and departures from the PRD

- **ADDITION** — A **persistence reference** ("the current measured value, held over the horizon") is scored beside every model on every block. PRD 13.1 names RandomForest as the baseline; the persistence row is extra, and exists so a MAE can be read as better-than-nothing rather than in isolation. It is a reference, not a fitted model, and is never selectable.
- **ADDITION** — Every metric is reported twice: against the sensor-layer **measurement** the model trained on, and against the simulator's noise-free **truth** state. PRD 22 asks for the first; PRD 34 item 2 asks models to be checked against the true state, which only a synthetic environment can do. The second reference is not achievable on real data and is labelled as such in the JSON.
- **ADDITION** — Model B is reported on three row blocks rather than two. PRD 13.2 specifies "fitted on normal-operation windows, scored on all data", which is the `all_rows` block and the primary row; the PRD 13.3 `chronological` and `scenario_holdout` blocks are reported beside it, each with its own independent fit.
- **ADDITION** — The `Startup transition` regime is excluded from Model B's headline precision/recall and reported in its own block. It is a scripted ramp with `injected_fault: null`, is not one of PRD 11.4's 14 regimes, and is deliberately withheld from the forest's fit - so counting it as a false positive would penalise the detector for correctly noticing a transient the PRD does not call a fault.
- **DEVIATION** — PRD 13.2 lists sensor-versus-process discrimination as an output of the detector. It is implemented and always reported as evidence, but the *claim* is suppressed (`report_sensor_claim: false`) because it was measured to be below chance at the configured drift magnitudes - see the first limitation below. This is a reporting choice, not a change to the PRD or to the data.

---

> **This model has not been validated against real cement-plant data.**

> The synthetic model is a development and demonstration environment, not a calibrated representation of any specific cement plant.
