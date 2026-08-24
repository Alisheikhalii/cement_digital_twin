"""``KilnTwin`` - the composite kiln twin (PRD v1.1.1 Sections 8.3, 8.4).

Sub-unit execution order follows the energy chain, fuel to stack:

``FanFuel -> Precalciner -> RotaryKiln -> Cooler -> Preheater``

Three signals close loops back to units that have already run in the current step, so they are
read one step old - which is what a discrete plant model physically is:

* ``burning_zone_temperature`` -> ``FanFuel`` (thermal NOx),
* ``preheater_outlet_temperature`` -> ``FanFuel`` (the ID fan's *actual* volumetric duty) and
  -> ``RotaryKiln`` (the exhaust-loss term of the energy balance),
* ``recovered_cooler_heat`` -> ``RotaryKiln`` (the input side of the energy balance).

At steady state the one-step-old values equal the current ones exactly, so both PRD 9.3
residuals are zero; during a transient they are bounded by the delay that carries the closure
(``energy_closure_to_preheater_temperature``), which is the intended behaviour of NFR-10.

The twin owns no physics of its own: it wires units together, keeps a flat state/output view
for the dashboard and the dataset writer, and implements the three composite methods of
PRD 8.4 (``simulate_scenario``, ``to_steady_state``, ``current_state_snapshot``).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Mapping

from src.process_models.fuel import FuelProperties
from src.process_models.interfaces import ProcessUnit, UnitBase
from src.process_models.kiln_core import (
    HEALTH_KEY,
    CoolerModel,
    PrecalcinerModel,
    RotaryKilnModel,
)
from src.process_models.kiln_gas import FanFuelModel, PreheaterModel, kiln_context
from src.process_models.kiln_reference import KilnReferencePoint
from src.simulation.delays import SECONDS_PER_MINUTE

if TYPE_CHECKING:  # keep the pandas import cost off `import src.process_models.kiln`
    import pandas as pd

#: ASSUMPTION convergence bound of :meth:`KilnTwin.to_steady_state`: the largest relative
#: change of any output over one minute. Purely numerical (like the reference-point solve
#: tolerance), so it is a module constant rather than a process parameter.
STEADY_STATE_TOLERANCE = 1e-6

#: Step size used while settling to steady state (PRD 11.2 sampling interval is 1 minute).
STEADY_STATE_STEP_SECONDS = 60.0


class KilnTwin(UnitBase):
    """Preheater + precalciner + rotary kiln + cooler + fans/fuel as one ``Twin`` (PRD 8.3)."""

    __slots__ = ("_cfg", "_cooler", "_fanfuel", "_fuel", "_kiln", "_precalciner", "_preheater", "_ref")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        reference: KilnReferencePoint | None = None,
        name: str = "Kiln",
    ) -> None:
        super().__init__(name)
        kiln_config, reference = kiln_context(kiln_config, reference)
        self._cfg = kiln_config
        self._ref = reference
        # One FuelProperties instance for the whole twin: PRD 8.3 gives the fuel properties to
        # FanFuelModel, and RotaryKilnModel must convert fuel to MJ/h the very same way.
        self._fuel = FuelProperties.from_config(kiln_config)
        self._fanfuel = FanFuelModel(kiln_config, reference, self._fuel)
        self._precalciner = PrecalcinerModel(kiln_config, reference)
        self._kiln = RotaryKilnModel(kiln_config, reference, self._fuel)
        self._cooler = CoolerModel(kiln_config, reference)
        self._preheater = PreheaterModel(kiln_config, reference)
        self.reset()

    # -- composition ---------------------------------------------------------------------
    @property
    def units(self) -> tuple[ProcessUnit, ...]:
        """Sub-units in execution order (PRD 8.3)."""
        return (self._fanfuel, self._precalciner, self._kiln, self._cooler, self._preheater)

    @property
    def fan_fuel(self) -> FanFuelModel:
        return self._fanfuel

    @property
    def precalciner(self) -> PrecalcinerModel:
        return self._precalciner

    @property
    def rotary_kiln(self) -> RotaryKilnModel:
        return self._kiln

    @property
    def cooler(self) -> CoolerModel:
        return self._cooler

    @property
    def preheater(self) -> PreheaterModel:
        return self._preheater

    @property
    def reference(self) -> KilnReferencePoint:
        return self._ref

    # -- initialisation ------------------------------------------------------------------
    def reset(self) -> None:
        """Put every sub-unit back exactly on the reference operating point."""
        for unit in self.units:
            unit.reset()  # type: ignore[attr-defined]
        ref = self._ref
        self.inputs = {
            "kiln_feed_rate_tph": ref.feed_rate_tph,
            "kiln_fuel_rate_tph": ref.kiln_fuel_rate_tph,
            "calciner_fuel_rate_tph": ref.calciner_fuel_rate_tph,
            "kiln_speed_rpm": ref.kiln_speed_rpm,
            "ID_fan_speed_pct": ref.ID_fan_speed_pct,
            "raw_meal_moisture_pct": ref.raw_meal_moisture_pct,
            "raw_meal_temperature_C": ref.raw_meal_temperature_C,
        }
        self.health = dict(self._kiln.health)
        self.constraints = {
            key: value for unit in self.units for key, value in unit.constraints.items()
        }
        self._collect()

    def _collect(self) -> None:
        """Refresh the twin's flat state/output/residual view from the sub-units.

        Output keys are unique across the units by construction (each PRD 12.1 tag is produced
        by exactly one unit); state keys are prefixed because several units legitimately hold a
        state of the same name (e.g. the exhaust gas volume in both FanFuel and Preheater).
        """
        outputs: dict[str, float] = {}
        state: dict[str, float] = {}
        for unit in self.units:
            outputs.update(unit.outputs)
            for key, value in unit.state.items():
                state[f"{unit.name}.{key}"] = value  # type: ignore[attr-defined]
        self.outputs = outputs
        self.state = state
        self.balance_residuals = dict(self._kiln.balance_residuals)

    def set_health(self, health: Mapping[str, float] | None) -> dict[str, float]:
        """Forward equipment health to the unit that owns health-driven signals (PRD 9.5)."""
        super().set_health(health)
        self._kiln.set_health({HEALTH_KEY: self.health.get(HEALTH_KEY, 1.0)})
        return self.health

    # -- dynamics ------------------------------------------------------------------------
    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        """Advance all five sub-units by ``dt_seconds`` in the PRD 8.3 execution order.

        External ``inputs`` are offered to every sub-unit, but the internal coupling signals
        always win: a scenario column may set ``kiln_feed_rate_tph``, it may not overwrite the
        clinker rate the kiln's own mass balance just produced.
        """
        external = dict(self.merge_inputs(inputs))
        kiln_outputs = self._kiln.outputs
        preheater_outputs = self._preheater.outputs

        # 1. Fans and fuel. Feedback: BZT (thermal NOx) and preheater outlet temperature (the
        #    ID fan moves actual, thermally expanded volume) - both one step old.
        self._fanfuel.simulation_step(
            {
                **external,
                "burning_zone_temperature_C": kiln_outputs["burning_zone_temperature"],
                "preheater_outlet_temperature_C": preheater_outputs[
                    "preheater_outlet_temperature"
                ],
            },
            dt_seconds,
        )
        fanfuel_state = self._fanfuel.state

        # 2. Precalciner (its own fuel and the feed rate).
        precalciner_outputs = self._precalciner.simulation_step(external, dt_seconds)

        # 3. Rotary kiln - both conservation closures. Cooler heat and the preheater's gas
        #    state are one step old; at steady state they are exactly consistent.
        self._kiln.simulation_step(
            {
                **external,
                "calciner_temperature_C": precalciner_outputs["calciner_temperature"],
                "recovered_cooler_heat_MJ_per_h": self._cooler.state[
                    "recovered_cooler_heat_MJ_per_h"
                ],
                "exhaust_gas_flow_Nm3_per_h": preheater_outputs["exhaust_gas_flow"],
                "preheater_outlet_temperature_C": preheater_outputs[
                    "preheater_outlet_temperature"
                ],
            },
            dt_seconds,
        )

        # 4. Cooler, on the clinker the kiln just discharged.
        self._cooler.simulation_step(
            {
                **external,
                "clinker_production_tph": kiln_outputs["clinker_production_tph"],
                "clinker_exit_temperature_C": kiln_outputs["clinker_exit_temperature_C"],
            },
            dt_seconds,
        )

        # 5. Preheater, carrying the energy-balance closure (PRD 9.3).
        self._preheater.simulation_step(
            {
                **external,
                "combustion_air_Nm3_per_h": fanfuel_state["combustion_air_Nm3_per_h"],
                "calcination_CO2_Nm3_per_h": fanfuel_state["calcination_CO2_Nm3_per_h"],
                "calcination_H2O_Nm3_per_h": fanfuel_state["calcination_H2O_Nm3_per_h"],
                "preheater_outlet_temperature_target_C": kiln_outputs[
                    "preheater_outlet_temperature_target_C"
                ],
            },
            dt_seconds,
        )

        self._collect()
        return self.outputs

    # -- composite Twin methods (PRD 8.4) ------------------------------------------------
    def simulate_scenario(
        self, input_trajectory: "pd.DataFrame", dt_seconds: float
    ) -> "pd.DataFrame":
        """Roll the twin forward over a trajectory of inputs (PRD 8.4; used by 14/16).

        One row of the result per row of ``input_trajectory``, on the same index, holding every
        output plus the two PRD 9.3 residuals - so What-if, the optimizer and the dataset
        writer all see identical numbers from identical code (Section 8.5).
        """
        import pandas as pd

        records: list[dict[str, float]] = []
        for _, row in input_trajectory.iterrows():
            step_inputs = {
                key: float(value)
                for key, value in row.items()
                if isinstance(value, (int, float)) and value == value  # drop NaN / non-numeric
            }
            outputs = dict(self.simulation_step(step_inputs, dt_seconds))
            outputs["energy_balance_residual_pct"] = self.balance_residuals["energy_pct"]
            outputs["mass_balance_residual_pct"] = self.balance_residuals["mass_pct"]
            records.append(outputs)
        return pd.DataFrame(records, index=input_trajectory.index)

    def to_steady_state(
        self, inputs: dict[str, float], max_minutes: int = 120
    ) -> dict[str, float]:
        """Hold ``inputs`` until the outputs stop moving (PRD 8.4; optimizer candidate eval).

        Convergence is measured on the outputs rather than on the raw states because that is
        what the caller compares: the optimizer scores candidate setpoints on the settled tags.
        """
        previous = dict(self.outputs)
        needed = self._quiet_steps()
        quiet = 0
        for _ in range(int(max_minutes)):
            outputs = self.simulation_step(inputs, STEADY_STATE_STEP_SECONDS)
            largest = 0.0
            for key, value in outputs.items():
                scale = max(1.0, abs(previous.get(key, value)))
                largest = max(largest, abs(value - previous.get(key, value)) / scale)
            previous = dict(outputs)
            quiet = quiet + 1 if largest < STEADY_STATE_TOLERANCE else 0
            if quiet >= needed:
                break
        return dict(self.outputs)

    def _quiet_steps(self) -> int:
        """How many consecutive quiet steps actually prove convergence (PRD 9.4).

        A change that is still travelling through a relationship's transport dead time moves
        *nothing*, so one quiet step is not evidence of a settled twin - it is just as likely
        to be the gap before the step arrives. The criterion therefore has to hold for longer
        than the longest dead time this twin carries, which is read from the same
        ``delays`` block the ``DelayedResponse`` instances are built from.
        """
        delays = self._cfg.get("delays") or {}
        longest_min = max(
            (float(spec.get("dead_time_min", 0.0) or 0.0) for spec in delays.values()),
            default=0.0,
        )
        return int(math.ceil(longest_min * SECONDS_PER_MINUTE / STEADY_STATE_STEP_SECONDS)) + 1

    def current_state_snapshot(self) -> dict[str, Any]:
        """PRD 8.5 single source of truth; nests the sub-units' own snapshots (Section 19.4)."""
        snapshot = super().current_state_snapshot()
        snapshot["units"] = {
            unit.name: unit.current_state_snapshot()  # type: ignore[attr-defined]
            for unit in self.units
        }
        snapshot["reference"] = self._ref.as_dict()
        return snapshot


__all__ = ["STEADY_STATE_STEP_SECONDS", "STEADY_STATE_TOLERANCE", "KilnTwin"]
