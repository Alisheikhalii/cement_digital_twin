"""``CementMillTwin`` - the composite cement-mill twin (PRD v1.1.1 Sections 8.3, 8.4).

Sub-unit execution order follows the material and gas path through the closed circuit:

``FanFilter -> Mill -> Separator -> Product``

Two signals close the classification loop back to the mill, which has already run in the
current step, so they are read one step old - which is what a discrete plant model physically
is:

* ``simulated_blaine_cm2_g`` -> ``Mill`` (the fineness term of the grinding power), and
* ``circulating_load_ratio`` -> ``Mill`` (how much material the closed circuit is holding, hence
  the inventory time constant and the differential pressure).

At steady state the one-step-old values equal the current ones exactly, so the PRD 10.2 mass
residual is zero; during a transient it stays exactly zero as well, because the closure is a
property of the mill's own discretization and not of the loop (Section 10.2, NFR-10).

The twin owns no physics of its own: it wires units together, keeps a flat state/output view
for the dashboard and the dataset writer, and implements the three composite methods of
PRD 8.4 (``simulate_scenario``, ``to_steady_state``, ``current_state_snapshot``).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Mapping

from src.process_models.interfaces import ProcessUnit, UnitBase
from src.process_models.mill_reference import MillReferencePoint
from src.process_models.mill_units import (
    HEALTH_KEY,
    FanFilterModel,
    MillModel,
    ProductModel,
    SeparatorModel,
    mill_context,
)
from src.simulation.delays import SECONDS_PER_MINUTE

if TYPE_CHECKING:  # keep the pandas import cost off `import src.process_models.mill`
    import pandas as pd

#: ASSUMPTION convergence bound of :meth:`CementMillTwin.to_steady_state`: the largest relative
#: change of any output over one minute. Purely numerical, so it is a module constant rather
#: than a process parameter (the kiln twin uses the same bound).
STEADY_STATE_TOLERANCE = 1e-6

#: Step size used while settling to steady state (PRD 11.2 sampling interval is 1 minute).
STEADY_STATE_STEP_SECONDS = 60.0


class CementMillTwin(UnitBase):
    """Fan/filter + mill + separator + product as one ``Twin`` (PRD 8.3)."""

    __slots__ = ("_cfg", "_fanfilter", "_mill", "_product", "_ref", "_separator")

    def __init__(
        self,
        mill_config: Mapping[str, Any] | None = None,
        reference: MillReferencePoint | None = None,
        name: str = "CementMill",
    ) -> None:
        super().__init__(name)
        mill_config, reference = mill_context(mill_config, reference)
        self._cfg = mill_config
        self._ref = reference
        self._fanfilter = FanFilterModel(mill_config, reference)
        self._mill = MillModel(mill_config, reference)
        self._separator = SeparatorModel(mill_config, reference)
        self._product = ProductModel(mill_config, reference)
        self.reset()

    # -- composition ---------------------------------------------------------------------
    @property
    def units(self) -> tuple[ProcessUnit, ...]:
        """Sub-units in execution order (PRD 8.3)."""
        return (self._fanfilter, self._mill, self._separator, self._product)

    @property
    def fan_filter(self) -> FanFilterModel:
        return self._fanfilter

    @property
    def mill(self) -> MillModel:
        return self._mill

    @property
    def separator(self) -> SeparatorModel:
        return self._separator

    @property
    def product(self) -> ProductModel:
        return self._product

    @property
    def reference(self) -> MillReferencePoint:
        return self._ref


    # -- initialisation ------------------------------------------------------------------
    def reset(self) -> None:
        """Put every sub-unit back exactly on the reference operating point."""
        for unit in self.units:
            unit.reset()  # type: ignore[attr-defined]
        ref = self._ref
        self.inputs = {
            "mill_feed_rate_tph": ref.feed_rate_tph,
            "separator_speed_rpm": ref.separator_speed_rpm,
            "fan_speed_pct": ref.fan_speed_pct,
            "mill_speed_rpm": ref.mill_speed_rpm,
        }
        self.health = dict(self._mill.health)
        self.constraints = {
            key: value for unit in self.units for key, value in unit.constraints.items()
        }
        self._collect()

    def _collect(self) -> None:
        """Refresh the twin's flat state/output/residual view from the sub-units.

        Output keys are unique across the units by construction (each PRD 12.2 tag is produced
        by exactly one unit); state keys are prefixed because several units legitimately hold a
        state of the same name (the gas flow in both FanFilter and Mill, the circulating load in
        both Mill and Separator).
        """
        outputs: dict[str, float] = {}
        state: dict[str, float] = {}
        for unit in self.units:
            outputs.update(unit.outputs)
            for key, value in unit.state.items():
                state[f"{unit.name}.{key}"] = value  # type: ignore[attr-defined]
        self.outputs = outputs
        self.state = state
        self.balance_residuals = dict(self._mill.balance_residuals)

    def set_health(self, health: Mapping[str, float] | None) -> dict[str, float]:
        """Forward equipment health to the unit that owns health-driven signals (PRD 9.5)."""
        super().set_health(health)
        self._mill.set_health({HEALTH_KEY: self.health.get(HEALTH_KEY, 1.0)})
        return self.health


    # -- dynamics ------------------------------------------------------------------------
    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        """Advance all four sub-units by ``dt_seconds`` in the PRD 8.3 execution order.

        External ``inputs`` are offered to every sub-unit, but the internal coupling signals
        always win: a scenario column may set ``mill_feed_rate_tph``, it may not overwrite the
        cement rate the mill's own mass balance just produced.
        """
        external = dict(self.merge_inputs(inputs))
        separator_outputs = self._separator.outputs
        separator_state = self._separator.state

        # 1. Circulation fan and bag filter: the gas flow and draughts everything else sees.
        fanfilter_outputs = self._fanfilter.simulation_step(external, dt_seconds)
        gas_flow = fanfilter_outputs["gas_flow"]

        # 2. The mill, and with it the PRD 10.2 mass closure. The classification loop's Blaine
        #    and circulating load are one step old; at steady state they are exactly consistent.
        mill_outputs = self._mill.simulation_step(
            {
                **external,
                "gas_flow_Nm3_per_h": gas_flow,
                "simulated_blaine_cm2_g": separator_outputs["simulated_blaine_cm2_g"],
                "circulating_load_ratio": separator_state["circulating_load_ratio"],
            },
            dt_seconds,
        )

        # 3. Separator, on the product the mill just discharged.
        self._separator.simulation_step(
            {
                **external,
                "gas_flow_Nm3_per_h": gas_flow,
                "mill_feed_rate_tph": mill_outputs["mill_feed_rate_tph"],
                "cement_production_tph": mill_outputs["cement_production_tph"],
            },
            dt_seconds,
        )

        # 4. Finished product: transport temperature and the circuit's specific power.
        self._product.simulation_step(
            {
                **external,
                "cement_production_tph": mill_outputs["cement_production_tph"],
                "mill_outlet_temperature": mill_outputs["mill_outlet_temperature"],
                "mill_motor_power_kw": mill_outputs["mill_motor_power_kw"],
                "separator_power_kW": self._separator.state["separator_power_kW"],
                "fan_power_kw": fanfilter_outputs["fan_power_kw"],
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
        output plus the PRD 10.2 mass residual - so What-if, the optimizer and the dataset
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
        """How many consecutive quiet steps actually prove convergence (PRD 10.3).

        A change still travelling through a relationship's transport dead time moves *nothing*,
        so one quiet step is not evidence of a settled twin - it is just as likely to be the gap
        before the step arrives. The criterion therefore has to hold for longer than the longest
        dead time this twin carries, read from the same ``delays`` block the
        ``DelayedResponse`` instances are built from.
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


__all__ = ["STEADY_STATE_STEP_SECONDS", "STEADY_STATE_TOLERANCE", "CementMillTwin"]
