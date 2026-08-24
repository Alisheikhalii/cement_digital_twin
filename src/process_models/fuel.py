"""Canonical fuel-energy units (PRD v1.1.1 Section 9.2, FR-24, AC-13).

Every thermal computation in the project is done in **megajoules**. Mass-based
(``MJ/kg``) and volume-based (``MJ/Nm3``) heating values are never added in native units -
each stream is converted to ``MJ/h`` inside :class:`FuelProperties` first. ``mj_to_kcal`` is
the *only* sanctioned conversion to the display unit ``kcal``, used once at the point of
display (the ``thermal_energy_kcal_per_kg_clinker`` tag), never re-derived elsewhere.

Covered by ``test_fuel_energy_unit_consistency`` (Section 34).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping

#: 1 kcal = 4.184e-3 MJ (thermochemical calorie). The single conversion constant.
MJ_PER_KCAL: Final = 4.184e-3

#: t/h -> kg/h.
KG_PER_TONNE: Final = 1000.0


def mj_to_kcal(x_MJ: float) -> float:
    """The ONLY sanctioned conversion path from canonical MJ to the display unit kcal.

    ``1 kcal = 4.184e-3 MJ  =>  kcal = MJ / 4.184e-3`` (PRD 9.2).
    """
    return float(x_MJ) / MJ_PER_KCAL


def kcal_to_mj(x_kcal: float) -> float:
    """Inverse of :func:`mj_to_kcal`; used only to document/derive LHV ASSUMPTIONs."""
    return float(x_kcal) * MJ_PER_KCAL


@dataclass(frozen=True, slots=True)
class FuelProperties:
    """Fuel heating values and combustion factors (PRD 9.2, ``configs/kiln_dynamics.yaml``).

    Both LHVs are ASSUMPTIONs pending real lab data (``fuel_lhv_lab_results`` in
    :mod:`src.schema`'s future-data requests) and are documented in
    ``SIMULATION_ASSUMPTIONS.md``.
    """

    lhv_solid_fuel_MJ_per_kg: float = 26.0
    # ASSUMPTION coal/petcoke blend: 6200 kcal/kg * 4.184e-3 = 25.94 ~ 26.0 MJ/kg
    # published range 24-28 MJ/kg (~5800-6700 kcal/kg)
    lhv_gas_fuel_MJ_per_Nm3: float = 36.0
    # ASSUMPTION natural gas (optional future stream, volumetric):
    # 8600 kcal/Nm3 * 4.184e-3 = 35.98 ~ 36.0 MJ/Nm3; published range 34-38 MJ/Nm3
    kiln_burner_fuel_share: float = 0.40
    stoichiometric_air_Nm3_per_MJ: float = 0.26
    combustion_CO2_Nm3_per_MJ: float = 0.047

    @classmethod
    def from_config(cls, kiln_config: Mapping[str, Any] | None = None) -> FuelProperties:
        """Read the ``fuel:`` block of ``configs/kiln_dynamics.yaml`` (never hard-coded)."""
        if kiln_config is None:
            from src.config import KILN, load_config

            kiln_config = load_config(KILN)
        fuel = kiln_config["fuel"]
        return cls(
            lhv_solid_fuel_MJ_per_kg=float(fuel["lhv_solid_fuel_MJ_per_kg"]),
            lhv_gas_fuel_MJ_per_Nm3=float(fuel["lhv_gas_fuel_MJ_per_Nm3"]),
            kiln_burner_fuel_share=float(fuel["kiln_burner_fuel_share"]),
            stoichiometric_air_Nm3_per_MJ=float(fuel["stoichiometric_air_Nm3_per_MJ"]),
            combustion_CO2_Nm3_per_MJ=float(fuel["combustion_CO2_Nm3_per_MJ"]),
        )

    # -- per-stream conversions to the canonical unit -----------------------------------
    def solid_fuel_energy_MJ_per_h(self, mass_flow_tph: float) -> float:
        """Thermal power of a solid/liquid fuel stream given as a **mass** flow (t/h)."""
        return float(mass_flow_tph) * KG_PER_TONNE * self.lhv_solid_fuel_MJ_per_kg

    def gas_fuel_energy_MJ_per_h(self, volume_flow_Nm3_per_h: float) -> float:
        """Thermal power of a gas fuel stream given as a **volume** flow (Nm3/h).

        Kept structurally separate from :meth:`solid_fuel_energy_MJ_per_h` so a mass flow and
        a volume flow can only ever meet after both are in MJ/h (PRD 9.2, AC-13).
        """
        return float(volume_flow_Nm3_per_h) * self.lhv_gas_fuel_MJ_per_Nm3

    def thermal_input_MJ_per_h(
        self,
        kiln_fuel_rate_tph: float,
        calciner_fuel_rate_tph: float,
        gas_fuel_flow_Nm3_per_h: float = 0.0,
    ) -> float:
        """Total kiln-system thermal input (PRD 9.2), summed only in MJ/h."""
        return (
            self.solid_fuel_energy_MJ_per_h(kiln_fuel_rate_tph)
            + self.solid_fuel_energy_MJ_per_h(calciner_fuel_rate_tph)
            + self.gas_fuel_energy_MJ_per_h(gas_fuel_flow_Nm3_per_h)
        )

    def solid_fuel_rate_tph(self, energy_MJ_per_h: float) -> float:
        """Inverse of :meth:`solid_fuel_energy_MJ_per_h`.

        Used by :mod:`src.process_models.kiln_reference` to turn the energy-balance-derived
        reference thermal input into the reference fuel *mass* flows, so the reference point
        can never drift out of energy consistency (PRD 9.3).
        """
        return float(energy_MJ_per_h) / (KG_PER_TONNE * self.lhv_solid_fuel_MJ_per_kg)

    def split_fuel_rates_tph(self, total_fuel_rate_tph: float) -> tuple[float, float]:
        """Split a total solid-fuel rate into ``(kiln_burner, calciner)`` (PRD 9.2)."""
        kiln = float(total_fuel_rate_tph) * self.kiln_burner_fuel_share
        return kiln, float(total_fuel_rate_tph) - kiln

    # -- combustion side ----------------------------------------------------------------
    def stoichiometric_air_Nm3_per_h(self, thermal_input_MJ_per_h: float) -> float:
        """Stoichiometric combustion-air demand of a thermal input (PRD 9.4 gas side)."""
        return float(thermal_input_MJ_per_h) * self.stoichiometric_air_Nm3_per_MJ

    def combustion_CO2_Nm3_per_h(self, thermal_input_MJ_per_h: float) -> float:
        """CO2 released by fuel combustion (calcination CO2 is handled by the mass balance)."""
        return float(thermal_input_MJ_per_h) * self.combustion_CO2_Nm3_per_MJ


def specific_thermal_energy_kcal_per_kg(
    thermal_input_MJ_per_h: float, clinker_production_tph: float
) -> float:
    """The display tag ``thermal_energy_kcal_per_kg_clinker`` (PRD 9.2/12.1).

    Single documented conversion at the point of display; returns 0.0 when no clinker is
    being produced (start-up), so the tag never becomes ``inf`` in the dataset.
    """
    clinker_kg_per_h = float(clinker_production_tph) * KG_PER_TONNE
    if clinker_kg_per_h <= 0.0:
        return 0.0
    return mj_to_kcal(float(thermal_input_MJ_per_h)) / clinker_kg_per_h


__all__ = [
    "MJ_PER_KCAL",
    "KG_PER_TONNE",
    "mj_to_kcal",
    "kcal_to_mj",
    "FuelProperties",
    "specific_thermal_energy_kcal_per_kg",
]
