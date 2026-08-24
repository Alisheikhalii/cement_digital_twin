"""``PlantTwin`` - the whole-plant twin (PRD v1.1.1 Sections 8.3, 8.4).

``KilnTwin`` and ``CementMillTwin`` are simulated with **independent, buffered clinker supply**
(PRD 8.3 ASSUMPTION: a real clinker silo decouples kiln and mill dynamics on the minute-to-hour
timescale this environment covers). So this twin deliberately passes *no* signal from the kiln
to the mill: tight kiln->mill coupling is a Phase-2 roadmap item (PRD 32), and inventing it here
would change the correlation structure of the generated datasets.

What the plant level does own is the joint view: one flat output dictionary spanning both PRD
12.1 and 12.2 tag sets, one nested snapshot for the dashboard and the HTML/SVG renderer
(PRD 8.5/19.4), and the combined conservation report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from src.process_models.interfaces import ProcessUnit, UnitBase
from src.process_models.kiln import KilnTwin
from src.process_models.kiln_core import HEALTH_KEY as KILN_HEALTH_KEY
from src.process_models.mill import CementMillTwin
from src.process_models.mill_units import HEALTH_KEY as MILL_HEALTH_KEY

if TYPE_CHECKING:  # keep the pandas import cost off `import src.process_models.plant`
    import pandas as pd

#: Step size used while settling to steady state (PRD 11.2 sampling interval is 1 minute).
STEADY_STATE_STEP_SECONDS = 60.0


class PlantTwin(UnitBase):
    """Kiln line + cement mill as one ``Twin`` (PRD 8.3)."""

    __slots__ = ("_kiln", "_mill")

    def __init__(
        self,
        kiln_config: Mapping[str, Any] | None = None,
        mill_config: Mapping[str, Any] | None = None,
        name: str = "Plant",
    ) -> None:
        super().__init__(name)
        self._kiln = KilnTwin(kiln_config)
        self._mill = CementMillTwin(mill_config)
        self.reset()

    # -- composition ---------------------------------------------------------------------
    @property
    def units(self) -> tuple[ProcessUnit, ...]:
        """The two composite twins; the kiln line runs first, purely for reporting order."""
        return (self._kiln, self._mill)

    @property
    def kiln(self) -> KilnTwin:
        return self._kiln

    @property
    def cement_mill(self) -> CementMillTwin:
        return self._mill

    # -- initialisation ------------------------------------------------------------------
    def reset(self) -> None:
        """Put both twins back exactly on their reference operating points."""
        self._kiln.reset()
        self._mill.reset()
        self.inputs = {**self._kiln.inputs, **self._mill.inputs}
        self.health = {**self._kiln.health, **self._mill.health}
        self.constraints = {**self._kiln.constraints, **self._mill.constraints}
        self._collect()

    def _collect(self) -> None:
        """Refresh the plant's flat state/output/residual view from the two twins.

        Output keys stay unprefixed: every PRD 12.1 and 12.2 tag is produced by exactly one
        unit in the whole plant, so the flat dictionary is the union of both tag sets and the
        dataset writer can slice it per dataset. State keys carry the twin's name on top of the
        sub-unit prefix the twins already apply (``Kiln.RotaryKiln.kiln_inventory_t``), because
        the two lines legitimately hold states of the same name.
        """
        outputs: dict[str, float] = {}
        state: dict[str, float] = {}
        for unit in self.units:
            outputs.update(unit.outputs)
            for key, value in unit.state.items():
                state[f"{unit.name}.{key}"] = value  # type: ignore[attr-defined]
        self.outputs = outputs
        self.state = state
        self.balance_residuals = self._combined_residuals()

    def _combined_residuals(self) -> dict[str, float]:
        """Both closures side by side, plus the two aggregate keys of PRD 8.4.

        The kiln is the only unit with an energy closure (PRD 9.3), so ``energy_pct`` is its
        residual verbatim. ``mass_pct`` reports whichever line is further from closure, so a
        caller that only looks at the plant-level number can never miss a violation in one of
        the two. The per-line keys are kept so NFR-10 can be checked where it is defined.
        """
        kiln = self._kiln.balance_residuals
        mill = self._mill.balance_residuals
        kiln_mass = float(kiln.get("mass_pct", 0.0))
        # CementMillTwin publishes no energy closure (PRD 10.2 defines a mass balance only),
        # hence `.get` rather than `[...]` on every mill key.
        mill_mass = float(mill.get("mass_pct", 0.0))
        residuals = {f"kiln_{key}": float(value) for key, value in kiln.items()}
        residuals.update({f"mill_{key}": float(value) for key, value in mill.items()})
        residuals["energy_pct"] = float(kiln.get("energy_pct", 0.0))
        residuals["mass_pct"] = kiln_mass if abs(kiln_mass) >= abs(mill_mass) else mill_mass
        return residuals

    def set_health(self, health: Mapping[str, float] | None) -> dict[str, float]:
        """Dispatch each health factor to the twin that owns it (PRD 9.5)."""
        super().set_health(health)
        self._kiln.set_health({KILN_HEALTH_KEY: self.health.get(KILN_HEALTH_KEY, 1.0)})
        self._mill.set_health({MILL_HEALTH_KEY: self.health.get(MILL_HEALTH_KEY, 1.0)})
        return self.health

    # -- dynamics ------------------------------------------------------------------------
    def simulation_step(self, inputs: dict[str, float], dt_seconds: float) -> dict[str, float]:
        """Advance both twins by ``dt_seconds``.

        The same external input dictionary is offered to both: each twin picks up the tags it
        knows and holds the rest (``UnitBase.merge_inputs``). Nothing crosses between them -
        the clinker silo between the kiln and the mill is the decoupling assumption of PRD 8.3.
        """
        external = dict(self.merge_inputs(inputs))
        self._kiln.simulation_step(external, dt_seconds)
        self._mill.simulation_step(external, dt_seconds)
        self._collect()
        return self.outputs

    # -- composite Twin methods (PRD 8.4) ------------------------------------------------
    def simulate_scenario(
        self, input_trajectory: "pd.DataFrame", dt_seconds: float
    ) -> "pd.DataFrame":
        """Roll the plant forward over a trajectory of inputs (PRD 8.4; used by 14/16).

        One row of the result per row of ``input_trajectory``, on the same index, holding every
        tag of both datasets plus the conservation residuals - the plant-level aggregates under
        the same column names the two twins use, and each line's own mass residual beside them.
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
            residuals = self.balance_residuals
            outputs["energy_balance_residual_pct"] = residuals["energy_pct"]
            outputs["mass_balance_residual_pct"] = residuals["mass_pct"]
            outputs["kiln_mass_balance_residual_pct"] = residuals["kiln_mass_pct"]
            outputs["mill_mass_balance_residual_pct"] = residuals["mill_mass_pct"]
            records.append(outputs)
        return pd.DataFrame(records, index=input_trajectory.index)

    def to_steady_state(
        self, inputs: dict[str, float], max_minutes: int = 120
    ) -> dict[str, float]:
        """Settle both twins under ``inputs`` (PRD 8.4; optimizer candidate evaluation).

        Delegated to the twins so the convergence test stays where the physics is, and because
        the two lines settle on different time constants: the kiln may still be moving long
        after the mill has stopped, and each is allowed its own iteration count.
        """
        self._kiln.to_steady_state(inputs, max_minutes)
        self._mill.to_steady_state(inputs, max_minutes)
        self._collect()
        return dict(self.outputs)

    def current_state_snapshot(self) -> dict[str, Any]:
        """PRD 8.5 single source of truth; nests both twins' snapshots (Section 19.4)."""
        snapshot = super().current_state_snapshot()
        snapshot["units"] = {
            unit.name: unit.current_state_snapshot()  # type: ignore[attr-defined]
            for unit in self.units
        }
        return snapshot


__all__ = ["STEADY_STATE_STEP_SECONDS", "PlantTwin"]
