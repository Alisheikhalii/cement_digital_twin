"""Canonical tag schema (PRD v1.1.1 Sections 12.1, 12.2, 27).

This module is the *single* source of truth for every dataset column: the generator builds
its DataFrames from it, the sensor model reads each tag's documented range to size noise and
quantization, the dashboard reads units and ranges from it, ``DATA_DICTIONARY.md`` and
``FACTORY_DATA_REQUIREMENTS.md`` (PRD 27 / FR-18) are rendered from it, and the schema test
in Section 34 compares generated columns against it.

Ranges are the PRD 12 documented "typical range" bands. They are process-reasoned
ASSUMPTIONs for a mid-size precalciner kiln line and a generic closed-circuit cement mill -
not measurements of any real plant (``assumption=True`` on every such row).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Final, Literal

TIMESTAMP_COLUMN: Final = "timestamp"
REGIME_LABEL_COLUMN: Final = "operating_regime"
FAULT_LABEL_COLUMN: Final = "injected_fault"

#: Debug-only columns, exported only when ``debug_balance_export: true`` (PRD 12.1 note).
DEBUG_BALANCE_COLUMNS: Final[tuple[str, ...]] = (
    "energy_balance_residual_pct",
    "mass_balance_residual_pct",
)

DatasetName = Literal["kiln", "mill"]
TagRole = Literal[
    "index",         # timestamp
    "manipulated",   # operator/DCS setpoint (PRD 9.1 / 10.1)
    "disturbance",   # upstream condition, not an operator lever
    "process",       # measured process state
    "quality",       # product-quality indicator
    "emission",      # stack/back-end gas concentration
    "equipment",     # equipment/health variable (PRD 9.5)
    "derived",       # computed from the canonical balance (PRD 9.2/9.3)
    "label",         # ground-truth simulation label
]
Importance = Literal["critical", "important", "optional"]


@dataclass(frozen=True, slots=True)
class TagSpec:
    """One dataset column, documented exactly as PRD 27.1 requires it to be requested."""

    name: str
    description: str
    unit: str
    dataset: DatasetName
    process_unit: str
    role: TagRole
    range_min: float | None = None
    range_max: float | None = None
    dtype: str = "float"
    importance: Importance = "important"
    mandatory: bool = True
    sampling_interval: str = "1 min"
    assumption: bool = True
    notes: str = ""

    @property
    def span(self) -> float | None:
        """Width of the documented operating range (used to size sensor noise, PRD 11.5)."""
        if self.range_min is None or self.range_max is None:
            return None
        return float(self.range_max) - float(self.range_min)

    @property
    def midpoint(self) -> float | None:
        if self.range_min is None or self.range_max is None:
            return None
        return 0.5 * (float(self.range_min) + float(self.range_max))


def _tag(
    name: str,
    description: str,
    unit: str,
    range_min: float | None = None,
    range_max: float | None = None,
    *,
    dataset: DatasetName,
    process_unit: str,
    role: TagRole,
    dtype: str = "float",
    importance: Importance = "important",
    mandatory: bool = True,
    assumption: bool = True,
    notes: str = "",
) -> TagSpec:
    return TagSpec(
        name=name,
        description=description,
        unit=unit,
        dataset=dataset,
        process_unit=process_unit,
        role=role,
        range_min=range_min,
        range_max=range_max,
        dtype=dtype,
        importance=importance,
        mandatory=mandatory,
        assumption=assumption,
        notes=notes,
    )


_kiln = partial(_tag, dataset="kiln", process_unit="Kiln")
_mill = partial(_tag, dataset="mill", process_unit="Cement Mill")

# --- PRD 12.1: kiln dataset (data/synthetic/kiln_raw.parquet) --------------------------
KILN_TAGS: Final[tuple[TagSpec, ...]] = (
    _kiln("timestamp", "UTC timestamp", "-", role="index", dtype="datetime",
          importance="critical", assumption=False),
    _kiln("kiln_feed_rate_tph", "Raw meal feed to kiln system", "t/h", 150.0, 230.0,
          role="manipulated", importance="critical"),
    _kiln("kiln_fuel_rate_tph", "Main kiln burner fuel rate (solid/liquid, MJ/kg basis)",
          "t/h", 3.2, 5.2, role="manipulated", importance="critical",
          process_unit="Fuel",
          notes="Simulated band is a ratio of the energy-balance-derived reference rate; "
                "see SIMULATION_ASSUMPTIONS.md 'Documentation-range deviations'."),
    _kiln("calciner_fuel_rate_tph", "Precalciner fuel rate (solid/liquid, MJ/kg basis)",
          "t/h", 4.0, 7.5, role="manipulated", importance="critical",
          process_unit="Fuel",
          notes="Same documented deviation as kiln_fuel_rate_tph."),
    _kiln("kiln_speed_rpm", "Kiln rotation speed", "rpm", 2.8, 4.5,
          role="manipulated", importance="critical"),
    _kiln("raw_meal_moisture", "Raw meal residual moisture", "%", 0.3, 1.0,
          role="disturbance", importance="important"),
    _kiln("raw_meal_temperature", "Raw meal feed temperature", "C", 40.0, 90.0,
          role="disturbance", importance="important"),
    _kiln("primary_air_flow", "Primary air flow to main burner", "Nm3/h", 15000.0, 25000.0,
          role="process", process_unit="Fans",
          notes="Simulated value is a share of the combustion air derived from the PRD 9.3 "
                "energy balance (~12k Nm3/h at the reference point), so it sits below the "
                "documented band; deviation recorded in SIMULATION_ASSUMPTIONS.md."),
    _kiln("secondary_air_flow", "Secondary air flow from cooler", "Nm3/h", 90000.0, 140000.0,
          role="process", process_unit="Cooler",
          notes="Same derivation and documented deviation as primary_air_flow "
                "(~66k Nm3/h at the reference point)."),
    _kiln("tertiary_air_flow", "Tertiary air flow to calciner", "Nm3/h", 60000.0, 100000.0,
          role="process", process_unit="Precalciner", importance="critical",
          notes="Same derivation and documented deviation as primary_air_flow "
                "(~42k Nm3/h at the reference point)."),
    _kiln("ID_fan_speed", "ID fan speed", "%", 60.0, 95.0,
          role="manipulated", process_unit="Fans", importance="critical"),
    _kiln("ID_fan_power", "ID fan motor power", "kW", 900.0, 2200.0,
          role="equipment", process_unit="Fans"),
    _kiln("kiln_inlet_pressure", "Kiln inlet draught pressure", "mbar", -8.0, -2.0,
          role="process"),
    _kiln("preheater_pressure", "Preheater tower pressure", "mbar", -25.0, -10.0,
          role="process", process_unit="Preheater", importance="critical"),
    _kiln("exhaust_gas_flow", "Stack/preheater exhaust flow", "Nm3/h", 250000.0, 400000.0,
          role="process", process_unit="Preheater",
          notes="Simulated value follows the PRD 9.3 gas balance (~199k Nm3/h at the "
                "reference point); documented deviation recorded in SIMULATION_ASSUMPTIONS.md."),
    _kiln("burning_zone_temperature", "Burning zone (pyrometer/model)", "C", 1400.0, 1500.0,
          role="process", importance="critical"),
    _kiln("kiln_inlet_temperature", "Material temp at kiln inlet", "C", 800.0, 950.0,
          role="process"),
    _kiln("calciner_temperature", "Precalciner outlet temperature", "C", 850.0, 900.0,
          role="process", process_unit="Precalciner", importance="critical"),
    _kiln("preheater_outlet_temperature", "Top-stage cyclone exit temperature", "C", 280.0, 380.0,
          role="process", process_unit="Preheater", importance="critical"),
    _kiln("secondary_air_temperature", "Secondary (cooler recuperated) air temp", "C",
          800.0, 1000.0, role="process", process_unit="Cooler"),
    _kiln("cooler_outlet_temperature", "Clinker cooler discharge temperature", "C", 80.0, 150.0,
          role="process", process_unit="Cooler"),
    _kiln("oxygen_percent", "O2 at kiln inlet/back-end (dry)", "%", 0.7, 4.0,
          role="process", importance="critical"),
    _kiln("CO_ppm", "CO at kiln inlet/back-end", "ppm", 0.0, 300.0,
          role="emission", importance="critical",
          notes="Spikes above the band under fault conditions (PRD 12.1)."),
    _kiln("CO2_percent", "CO2 at kiln inlet/back-end", "%", 28.0, 36.0, role="emission"),
    _kiln("NOx_ppm", "NOx (converted from mg/Nm3, ASSUMPTION conversion factor)", "ppm",
          250.0, 900.0, role="emission", importance="optional", mandatory=False),
    _kiln("SO2_ppm", "SO2 at stack", "ppm", 10.0, 400.0,
          role="emission", importance="optional", mandatory=False,
          notes="Raw-material sulfur dependent."),
    _kiln("clinker_production_tph", "Clinker output rate", "t/h", 95.0, 150.0,
          role="process", importance="critical"),
    _kiln("clinker_temperature", "Clinker discharge temperature", "C", 80.0, 150.0,
          role="process", process_unit="Cooler"),
    _kiln("thermal_energy_kcal_per_kg_clinker",
          "Specific thermal energy - display-unit derivation of the canonical MJ energy "
          "balance (PRD 9.2/9.3)", "kcal/kg", 700.0, 950.0,
          role="derived", importance="critical", process_unit="Fuel"),
    _kiln("specific_fuel_consumption",
          "Duplicate/derived, kept for factory-familiar naming", "kcal/kg", 700.0, 950.0,
          role="derived", importance="optional", mandatory=False, process_unit="Fuel"),
    _kiln("ID_fan_current", "ID fan motor current", "A", 100.0, 260.0,
          role="equipment", process_unit="Fans"),
    _kiln("kiln_motor_current", "Kiln main drive current", "A", 80.0, 180.0, role="equipment"),
    _kiln("cooler_fan_power", "Cooler fans total power", "kW", 400.0, 1100.0,
          role="equipment", process_unit="Cooler"),
    _kiln("vibration", "Kiln drive/support vibration (generic)", "mm/s", 1.0, 8.0,
          role="equipment", notes="Spikes above the band under fault conditions."),
    _kiln("bearing_temperature", "Kiln support roller bearing temperature", "C", 45.0, 75.0,
          role="equipment", notes="Spikes above the band under fault conditions."),
    _kiln(REGIME_LABEL_COLUMN, "Ground-truth regime label (PRD 11.4)", "-",
          role="label", dtype="string", importance="critical", assumption=False,
          notes="Simulation ground truth; a real plant would not supply this."),
    _kiln(FAULT_LABEL_COLUMN, "Ground-truth fault flag/type for anomaly evaluation", "-",
          role="label", dtype="string", importance="critical", assumption=False,
          notes="Null outside an injected fault; set only on the unit the regime perturbs."),
)

# --- PRD 12.2: cement mill dataset (data/synthetic/mill_raw.parquet) -------------------
MILL_TAGS: Final[tuple[TagSpec, ...]] = (
    _mill("timestamp", "UTC timestamp", "-", role="index", dtype="datetime",
          importance="critical", assumption=False),
    _mill("mill_feed_rate_tph", "Total mill feed", "t/h", 80.0, 170.0,
          role="manipulated", importance="critical"),
    _mill("clinker_feed_rate", "Clinker component of feed", "t/h", 70.0, 150.0,
          role="manipulated", importance="critical"),
    _mill("gypsum_feed_rate", "Gypsum component of feed", "t/h", 3.0, 8.0,
          role="manipulated"),
    _mill("additive_feed_rate", "Additive/limestone component", "t/h", 0.0, 20.0,
          role="manipulated"),
    _mill("mill_motor_power_kw", "Main mill motor power", "kW", 2500.0, 5500.0,
          role="process", importance="critical"),
    _mill("mill_current", "Main motor current", "A", 200.0, 420.0, role="equipment"),
    _mill("mill_pressure", "Mill internal pressure (VRM) / shell pressure proxy", "mbar",
          -40.0, -10.0, role="process"),
    _mill("mill_differential_pressure", "Mill dP (loading indicator)", "mbar", 20.0, 90.0,
          role="process", importance="critical",
          notes="Spikes above the band under overload (PRD 12.2)."),
    _mill("mill_outlet_temperature", "Material/gas outlet temperature", "C", 90.0, 120.0,
          role="process"),
    _mill("mill_vibration", "Mill body vibration", "mm/s", 1.0, 10.0,
          role="equipment", notes="Spikes above the band under fault conditions."),
    _mill("mill_speed", "Mill rotational/table speed", "rpm", 12.0, 18.0,
          role="manipulated", notes="Generic circuit (neither VRM- nor ball-mill-specific)."),
    _mill("separator_speed_rpm", "Dynamic separator rotor speed", "rpm", 60.0, 140.0,
          role="manipulated", process_unit="Separator", importance="critical",
          notes="Primary quality lever (PRD 27.2)."),
    _mill("separator_current", "Separator motor current", "A", 30.0, 80.0,
          role="equipment", process_unit="Separator", importance="critical"),
    _mill("separator_pressure", "Separator inlet/outlet pressure", "mbar", -15.0, -5.0,
          role="process", process_unit="Separator", importance="critical"),
    _mill("fan_speed", "Main/circulation fan speed", "%", 60.0, 100.0,
          role="manipulated", process_unit="Fans"),
    _mill("fan_power_kw", "Main fan power", "kW", 400.0, 1200.0,
          role="equipment", process_unit="Fans"),
    _mill("gas_flow", "Circulating gas flow", "Nm3/h", 150000.0, 260000.0, role="process"),
    _mill("cement_production_tph", "Net finished-product rate", "t/h", 75.0, 160.0,
          role="process", importance="critical"),
    _mill("product_temperature", "Finished product temperature", "C", 85.0, 115.0,
          role="process"),
    _mill("simulated_blaine_cm2_g", "Fineness (Blaine surface area)", "cm2/g", 2900.0, 4200.0,
          role="quality", importance="critical"),
    _mill("residue_percent", "45 um sieve residue", "%", 6.0, 18.0,
          role="quality", importance="critical"),
    _mill("specific_power_consumption_kwh_t", "Specific electrical energy", "kWh/t", 26.0, 45.0,
          role="derived", importance="critical"),
    _mill(REGIME_LABEL_COLUMN, "Ground-truth regime label", "-",
          role="label", dtype="string", importance="critical", assumption=False,
          notes="Simulation ground truth; a real plant would not supply this."),
    _mill(FAULT_LABEL_COLUMN, "Ground-truth fault flag/type", "-",
          role="label", dtype="string", importance="critical", assumption=False,
          notes="Null outside an injected fault; set only on the unit the regime perturbs."),
)

ALL_TAGS: Final[tuple[TagSpec, ...]] = KILN_TAGS + MILL_TAGS

_BY_DATASET: Final[dict[str, tuple[TagSpec, ...]]] = {"kiln": KILN_TAGS, "mill": MILL_TAGS}
# Tag names are unique per dataset; ``operating_regime``/``injected_fault``/``timestamp``
# deliberately appear in both, so the global index is keyed by (dataset, name).
_BY_KEY: Final[dict[tuple[str, str], TagSpec]] = {
    (tag.dataset, tag.name): tag for tag in ALL_TAGS
}

KILN_COLUMNS: Final[tuple[str, ...]] = tuple(tag.name for tag in KILN_TAGS)
MILL_COLUMNS: Final[tuple[str, ...]] = tuple(tag.name for tag in MILL_TAGS)


def tags_for(dataset: DatasetName) -> tuple[TagSpec, ...]:
    """All tag specs of one dataset, in canonical column order (PRD 12)."""
    try:
        return _BY_DATASET[dataset]
    except KeyError as exc:
        raise KeyError(f"unknown dataset {dataset!r}; expected 'kiln' or 'mill'") from exc


def columns_for(dataset: DatasetName, *, include_debug_balance: bool = False) -> tuple[str, ...]:
    """Canonical column order of a dataset, optionally plus the debug residual columns."""
    columns = tuple(tag.name for tag in tags_for(dataset))
    return columns + DEBUG_BALANCE_COLUMNS if include_debug_balance else columns


def get_tag(name: str, dataset: DatasetName | None = None) -> TagSpec:
    """Look up one tag spec; ``dataset`` disambiguates the shared label/timestamp columns."""
    if dataset is not None:
        try:
            return _BY_KEY[(dataset, name)]
        except KeyError as exc:
            raise KeyError(f"tag {name!r} is not part of the {dataset} dataset") from exc
    matches = [tag for tag in ALL_TAGS if tag.name == name]
    if not matches:
        raise KeyError(f"unknown tag {name!r}")
    return matches[0]


def has_tag(name: str, dataset: DatasetName | None = None) -> bool:
    """True when ``name`` is part of the (given) dataset schema."""
    if dataset is not None:
        return (dataset, name) in _BY_KEY
    return any(tag.name == name for tag in ALL_TAGS)


def tags_with_role(role: TagRole, dataset: DatasetName | None = None) -> tuple[TagSpec, ...]:
    """All tags of a given role, e.g. every ``manipulated`` variable (PRD 9.1/10.1)."""
    pool = ALL_TAGS if dataset is None else tags_for(dataset)
    return tuple(tag for tag in pool if tag.role == role)


def manipulated_variables(dataset: DatasetName | None = None) -> tuple[str, ...]:
    """Names of the manipulated (setpoint) variables."""
    return tuple(tag.name for tag in tags_with_role("manipulated", dataset))


def numeric_columns(dataset: DatasetName) -> tuple[str, ...]:
    """Float columns only (labels and timestamp excluded) - used by the sensor model."""
    return tuple(tag.name for tag in tags_for(dataset) if tag.dtype == "float")


def tag_range(name: str, dataset: DatasetName | None = None) -> tuple[float, float]:
    """Documented ``(min, max)`` band of a tag; raises when the tag has no numeric range."""
    tag = get_tag(name, dataset)
    if tag.range_min is None or tag.range_max is None:
        raise ValueError(f"tag {name!r} has no documented numeric range")
    return float(tag.range_min), float(tag.range_max)


def dataset_of(name: str) -> DatasetName:
    """Dataset a uniquely-named tag belongs to (raises for the shared label columns)."""
    owners = {tag.dataset for tag in ALL_TAGS if tag.name == name}
    if not owners:
        raise KeyError(f"unknown tag {name!r}")
    if len(owners) > 1:
        raise KeyError(f"tag {name!r} is shared by datasets {sorted(owners)}")
    return next(iter(owners))  # type: ignore[return-value]


# --- PRD 27.2: requested from the factory but deliberately NOT in the v1.1 schema -------
@dataclass(frozen=True, slots=True)
class FutureDataRequest:
    """A tag/dataset the factory is asked for although v1.1 does not simulate it."""

    name: str
    description: str
    process_unit: str
    importance: Importance
    reason: str


FUTURE_DATA_REQUESTS: Final[tuple[FutureDataRequest, ...]] = (
    FutureDataRequest(
        name="fuel_lhv_lab_results",
        description="Lab calorific value (LHV) per fuel stream, on a single MJ basis "
                    "(MJ/kg for solid/liquid, MJ/Nm3 for gas)",
        process_unit="Fuel",
        importance="critical",
        reason="Replaces the lhv_solid_fuel_MJ_per_kg / lhv_gas_fuel_MJ_per_Nm3 ASSUMPTIONs "
               "of PRD 9.2 with measured values.",
    ),
    FutureDataRequest(
        name="section_electrical_energy_meters",
        description="Total plant and per-section electrical energy meters (kWh)",
        process_unit="Electrical system",
        importance="important",
        reason="Optional, high value: enables plant-wide electrical optimization to be "
               "validated later (PRD 27.2).",
    ),
    FutureDataRequest(
        name="raw_mill_circuit_tags",
        description="Raw mill / raw meal preparation circuit tags",
        process_unit="Raw Mill",
        importance="optional",
        reason="Out of scope in v1.1 (PRD 5.2); listed so the factory knows it will "
               "eventually be requested (PRD 27.2, roadmap PRD 32).",
    ),
    FutureDataRequest(
        name="step_test_transient_logs",
        description="Logged responses to known setpoint changes (step tests / transients)",
        process_unit="Kiln, Cement Mill",
        importance="important",
        reason="High-value input for calibrating the per-relationship dead-time + lag "
               "parameters of PRD 9.4/10.3 (PRD 27.3).",
    ),
)


__all__ = [
    "TIMESTAMP_COLUMN",
    "REGIME_LABEL_COLUMN",
    "FAULT_LABEL_COLUMN",
    "DEBUG_BALANCE_COLUMNS",
    "DatasetName",
    "TagRole",
    "Importance",
    "TagSpec",
    "KILN_TAGS",
    "MILL_TAGS",
    "ALL_TAGS",
    "KILN_COLUMNS",
    "MILL_COLUMNS",
    "tags_for",
    "columns_for",
    "get_tag",
    "has_tag",
    "tags_with_role",
    "manipulated_variables",
    "numeric_columns",
    "tag_range",
    "dataset_of",
    "FutureDataRequest",
    "FUTURE_DATA_REQUESTS",
]
