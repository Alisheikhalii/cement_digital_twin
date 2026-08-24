"""Panel and topology composition (PRD v1.1.1 17-19; Task #6 directive items 3-6, 9, 12).

*Which* tags a view shows, and *which* equipment and flows exist, are process facts rather than
rendering choices, so they are declared once here - in the domain layer, beside the provider that
serves them - and read by both the payload builder and the HTML/SVG renderer. Three rules hold
for everything in this module:

* every tag name is a :mod:`src.schema` tag, so a typo fails a test rather than silently drawing
  an empty card, and no view can invent a KPI the implementation does not produce (item 9);
* every equipment item is a PRD 8.3 component under its own name - nothing is added (item 2);
* there is no engineering number here. Ranges come from :mod:`src.schema`, alarm bands and
  animation scaling from ``configs/dashboard.yaml``, and the one arithmetic constant
  (:data:`~src.optimization.recommendation.KG_PER_TONNE`) is imported rather than restated
  (NFR-6, AC-12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.optimization.objective import ELECTRIC_TAG, THERMAL_TAG
from src.optimization.recommendation import KG_PER_TONNE
from src.process_models.kiln_core import HEALTH_KEY as KILN_HEALTH_KEY
from src.process_models.mill_units import HEALTH_KEY as MILL_HEALTH_KEY

# =============================================================================
# Panel tag sets
# =============================================================================
#: Kiln panel (PRD 18.2, directive item 5): fuel, feed, BZT, O2, CO, ID fan, production,
#: specific thermal consumption, kiln speed - the manipulated and headline process tags.
KILN_PANEL_TAGS: Final[tuple[str, ...]] = (
    "kiln_fuel_rate_tph",
    "calciner_fuel_rate_tph",
    "kiln_feed_rate_tph",
    "kiln_speed_rpm",
    "burning_zone_temperature",
    "oxygen_percent",
    "CO_ppm",
    "ID_fan_speed",
    "clinker_production_tph",
    THERMAL_TAG,
)

#: The remaining measured fan/process indicators of the kiln line (directive item 5's "other
#: available fan/process indicators"). Shown in the Kiln view's secondary block.
KILN_PROCESS_TAGS: Final[tuple[str, ...]] = (
    "preheater_pressure",
    "preheater_outlet_temperature",
    "calciner_temperature",
    "kiln_inlet_temperature",
    "kiln_inlet_pressure",
    "exhaust_gas_flow",
    "primary_air_flow",
    "secondary_air_flow",
    "tertiary_air_flow",
    "secondary_air_temperature",
    "cooler_outlet_temperature",
    "clinker_temperature",
    "ID_fan_power",
    "ID_fan_current",
    "kiln_motor_current",
    "cooler_fan_power",
    "vibration",
    "bearing_temperature",
    "specific_fuel_consumption",
)

#: Emissions the kiln dataset carries (PRD 12.1). Kept as their own block: they are monitored
#: outputs, not manipulated variables, and directive item 5 asks for CO in the main panel only.
KILN_EMISSION_TAGS: Final[tuple[str, ...]] = ("CO2_percent", "NOx_ppm", "SO2_ppm")

#: Mill panel (PRD 18.3, directive item 6): feed, motor power, separator speed, differential
#: pressure, Blaine, residue, specific electricity - plus the mill speed that drives them.
MILL_PANEL_TAGS: Final[tuple[str, ...]] = (
    "mill_feed_rate_tph",
    "mill_motor_power_kw",
    ELECTRIC_TAG,
    "separator_speed_rpm",
    "mill_speed",
    "mill_differential_pressure",
    "simulated_blaine_cm2_g",
    "residue_percent",
    "cement_production_tph",
)

#: The remaining measured mill/separator/fan indicators (directive item 6's "available mill
#: equipment indicators").
MILL_PROCESS_TAGS: Final[tuple[str, ...]] = (
    "clinker_feed_rate",
    "gypsum_feed_rate",
    "additive_feed_rate",
    "mill_pressure",
    "mill_outlet_temperature",
    "mill_current",
    "mill_vibration",
    "separator_current",
    "separator_pressure",
    "fan_speed",
    "fan_power_kw",
    "gas_flow",
    "product_temperature",
)

# =============================================================================
# KPI groups (directive item 9)
# =============================================================================
KILN_KPI_TITLE: Final = "Kiln"
MILL_KPI_TITLE: Final = "Cement mill"
PLANT_KPI_TITLE: Final = "Plant"

#: Kiln KPIs: fuel rate, thermal energy, burning-zone temperature, O2, clinker production, and
#: the PRD-defined thermal-efficiency indicator (``specific_fuel_consumption``).
KILN_KPI_TAGS: Final[tuple[str, ...]] = (
    "kiln_fuel_rate_tph",
    THERMAL_TAG,
    "specific_fuel_consumption",
    "burning_zone_temperature",
    "oxygen_percent",
    "clinker_production_tph",
)

#: Mill KPIs: motor power, specific power, mill feed, Blaine, residue, differential pressure.
MILL_KPI_TAGS: Final[tuple[str, ...]] = (
    "mill_motor_power_kw",
    ELECTRIC_TAG,
    "mill_feed_rate_tph",
    "simulated_blaine_cm2_g",
    "residue_percent",
    "mill_differential_pressure",
)

#: Plant KPIs: the two specific-energy figures and the two production rates. The *total* energy
#: figures are :data:`DAILY_TOTALS` and are shown beside these, never instead of them (item 12).
PLANT_KPI_TAGS: Final[tuple[str, ...]] = (
    THERMAL_TAG,
    ELECTRIC_TAG,
    "clinker_production_tph",
    "cement_production_tph",
)


# =============================================================================
# Total (as opposed to specific) energy - directive item 12
# =============================================================================
@dataclass(frozen=True, slots=True)
class DailyTotal:
    """A daily energy total derived from two observed rates.

    Directive item 12 is explicit: a dashboard that shows only specific energy can report an
    improvement while total consumption rises, because production rose. So each specific-energy
    KPI is paired with the total it implies - ``intensity x rate x scale x DAILY_HOURS``, computed
    by :func:`~src.optimization.recommendation.daily_total` so the definition of "per day" exists
    once in the system. This is a display aggregation of observed values, not a fifth data source:
    the resulting value keeps :data:`~src.digital_twin.provenance.Provenance.OBSERVED` and names
    the arithmetic in its ``source``.
    """

    tag: str
    unit: str
    description: str
    intensity_tag: str
    rate_tag: str
    scale: float
    dataset: str


#: The two totals the implementation supports, one per energy carrier the twin models.
DAILY_TOTALS: Final[tuple[DailyTotal, ...]] = (
    DailyTotal(
        tag="kiln_thermal_energy_kcal_per_day",
        unit="kcal/day",
        description=(
            "Total kiln thermal energy per day implied by the current specific consumption and "
            "clinker rate (specific energy x production, 24 h basis)"
        ),
        intensity_tag=THERMAL_TAG,
        rate_tag="clinker_production_tph",
        scale=KG_PER_TONNE,
        dataset="kiln",
    ),
    DailyTotal(
        tag="mill_electrical_energy_kwh_per_day",
        unit="kWh/day",
        description=(
            "Total cement-mill electricity per day implied by the current specific power and "
            "cement rate (specific energy x production, 24 h basis)"
        ),
        intensity_tag=ELECTRIC_TAG,
        rate_tag="cement_production_tph",
        scale=1.0,  # kWh/t x t/h is already kW: no unit conversion, unlike the kcal/kg pairing
        dataset="mill",
    ),
)


# =============================================================================
# Plant equipment (PRD 8.3) - directive items 2 and 4
# =============================================================================
#: The two composite twins, spelled as :meth:`PlantTwin.current_state_snapshot` reports them. A
#: test asserts these match ``PlantTwin().units``, so a rename cannot silently orphan a view.
KILN_LINE: Final = "Kiln"
MILL_LINE: Final = "CementMill"

#: The tag that answers "is this line running at all", per line. A component's ``driver`` below is
#: the quantity its *motion* scales with and may legitimately be a temperature (the precalciner's
#: glow follows ``calciner_temperature``), which makes it the wrong reading for an IDLE test. The
#: throughput of the line the component sits on is the right one, and it is the same feed rate the
#: line's own mass balance is written against - not a new indicator.
LINE_THROUGHPUT: Final[dict[str, str]] = {
    KILN_LINE: "kiln_feed_rate_tph",
    MILL_LINE: "mill_feed_rate_tph",
}


@dataclass(frozen=True, slots=True)
class EquipmentSpec:
    """One PRD 8.3 component, named as the twin names it.

    ``detail`` is what this component itself computes - the tags its own ``outputs`` carry - so
    clicking a component in the animated twin (item 4) inspects that component rather than a
    curated selection of the whole line. ``driver`` is the process quantity its motion scales
    with, which may be produced upstream: the cooler's fan spins with the cooling air it draws,
    the finished-cement stream moves with the mill's product rate. Scaling itself is
    :meth:`Value.fraction_of_range` against the :mod:`src.schema` range - there is no speed
    constant here (AC-21).
    """

    name: str
    title: str
    kind: str
    line: str
    dataset: str
    health_key: str
    driver: str
    detail: tuple[str, ...]


#: The nine components of PRD 8.3, in the PRD 8.3 execution order of each line. Nothing may be
#: added: a piece of equipment on a screen that the twin does not model would be a claim about a
#: plant we do not simulate (directive item 2).
EQUIPMENT: Final[tuple[EquipmentSpec, ...]] = (
    EquipmentSpec(
        name="Preheater",
        title="Preheater tower",
        kind="PreheaterModel",
        line=KILN_LINE,
        dataset="kiln",
        health_key=KILN_HEALTH_KEY,
        driver="exhaust_gas_flow",
        detail=("preheater_outlet_temperature", "preheater_pressure", "exhaust_gas_flow"),
    ),
    EquipmentSpec(
        name="Precalciner",
        title="Precalciner",
        kind="PrecalcinerModel",
        line=KILN_LINE,
        dataset="kiln",
        health_key=KILN_HEALTH_KEY,
        driver="calciner_temperature",
        detail=("calciner_temperature", "kiln_inlet_temperature"),
    ),
    EquipmentSpec(
        name="RotaryKiln",
        title="Rotary kiln",
        kind="RotaryKilnModel",
        line=KILN_LINE,
        dataset="kiln",
        health_key=KILN_HEALTH_KEY,
        driver="kiln_speed_rpm",
        detail=(
            "burning_zone_temperature",
            "kiln_feed_rate_tph",
            "kiln_speed_rpm",
            "clinker_production_tph",
            "kiln_motor_current",
            THERMAL_TAG,
            "specific_fuel_consumption",
            "vibration",
            "bearing_temperature",
        ),
    ),
    EquipmentSpec(
        name="Cooler",
        title="Clinker cooler",
        kind="CoolerModel",
        line=KILN_LINE,
        dataset="kiln",
        health_key=KILN_HEALTH_KEY,
        driver="cooler_fan_power",
        detail=(
            "clinker_temperature",
            "cooler_outlet_temperature",
            "secondary_air_temperature",
            "cooler_fan_power",
        ),
    ),
    EquipmentSpec(
        name="FanFuel",
        title="Fuel & fan system",
        kind="FanFuelModel",
        line=KILN_LINE,
        dataset="kiln",
        health_key=KILN_HEALTH_KEY,
        driver="ID_fan_speed",
        detail=(
            "kiln_fuel_rate_tph",
            "calciner_fuel_rate_tph",
            "ID_fan_speed",
            "ID_fan_power",
            "ID_fan_current",
            "primary_air_flow",
            "secondary_air_flow",
            "tertiary_air_flow",
            "kiln_inlet_pressure",
            "oxygen_percent",
            "CO_ppm",
            "CO2_percent",
            "NOx_ppm",
            "SO2_ppm",
        ),
    ),
    EquipmentSpec(
        name="Mill",
        title="Cement mill",
        kind="MillModel",
        line=MILL_LINE,
        dataset="mill",
        health_key=MILL_HEALTH_KEY,
        driver="mill_speed",
        detail=(
            "mill_feed_rate_tph",
            "clinker_feed_rate",
            "gypsum_feed_rate",
            "additive_feed_rate",
            "mill_motor_power_kw",
            "mill_current",
            "mill_speed",
            "mill_differential_pressure",
            "mill_outlet_temperature",
            "mill_vibration",
            "cement_production_tph",
        ),
    ),
    EquipmentSpec(
        name="Separator",
        title="Dynamic separator",
        kind="SeparatorModel",
        line=MILL_LINE,
        dataset="mill",
        health_key=MILL_HEALTH_KEY,
        driver="separator_speed_rpm",
        detail=(
            "separator_speed_rpm",
            "separator_current",
            "simulated_blaine_cm2_g",
            "residue_percent",
        ),
    ),
    EquipmentSpec(
        name="FanFilter",
        title="Mill fan & filter",
        kind="FanFilterModel",
        line=MILL_LINE,
        dataset="mill",
        health_key=MILL_HEALTH_KEY,
        driver="fan_speed",
        detail=("fan_speed", "fan_power_kw", "gas_flow", "mill_pressure", "separator_pressure"),
    ),
    EquipmentSpec(
        name="Product",
        title="Finished cement",
        kind="ProductModel",
        line=MILL_LINE,
        dataset="mill",
        health_key=MILL_HEALTH_KEY,
        driver="cement_production_tph",
        detail=("product_temperature", ELECTRIC_TAG),
    ),
)


# =============================================================================
# Process flows (PRD 8.2/19.4) - directive items 3 and 4
# =============================================================================
#: Stream boundaries: where a flow enters or leaves the modelled plant. They are drawn as
#: labelled terminals rather than as equipment, because the twin models the stream, not a
#: quarry, a fuel yard or a packing plant.
FEED_NODE: Final = "Raw meal feed"
FUEL_NODE: Final = "Fuel"
AIR_NODE: Final = "Combustion air"
STACK_NODE: Final = "Stack"
SILO_NODE: Final = "Clinker silo"
OUTPUT_NODE: Final = "Cement silo"


@dataclass(frozen=True, slots=True)
class FlowSpec:
    """One stream between two nodes, and the simulated rate its animation is scaled by.

    ``rate_tag`` is the whole animation contract of directive item 4: dash speed, particle count
    and stroke width are :meth:`Value.fraction_of_range` of *this tag's current value*, so a
    stream that slows on screen slowed in the simulation. Where the visible rate is a proxy for
    the stream (there is no exported tag for a circulating load) ``note`` says which modelled
    relationship drives it, so nothing is animated on a made-up basis.
    """

    name: str
    title: str
    source: str
    target: str
    rate_tag: str
    kind: str
    dataset: str
    note: str = ""
    buffered: bool = False


#: Every stream the twin simulates, covering the seven directive item 4 requires by name:
#: fuel -> kiln, air -> kiln, material -> preheater -> kiln, clinker -> cooler, clinker -> mill,
#: material -> separator and finished cement -> output.
FLOWS: Final[tuple[FlowSpec, ...]] = (
    FlowSpec(
        name="raw_meal_to_preheater",
        title="Raw meal",
        source=FEED_NODE,
        target="Preheater",
        rate_tag="kiln_feed_rate_tph",
        kind="material",
        dataset="kiln",
    ),
    FlowSpec(
        name="meal_to_precalciner",
        title="Preheated meal",
        source="Preheater",
        target="Precalciner",
        rate_tag="kiln_feed_rate_tph",
        kind="material",
        dataset="kiln",
    ),
    FlowSpec(
        name="meal_to_kiln",
        title="Calcined meal",
        source="Precalciner",
        target="RotaryKiln",
        rate_tag="kiln_feed_rate_tph",
        kind="material",
        dataset="kiln",
    ),
    FlowSpec(
        name="kiln_fuel",
        title="Kiln burner fuel",
        source=FUEL_NODE,
        target="RotaryKiln",
        rate_tag="kiln_fuel_rate_tph",
        kind="fuel",
        dataset="kiln",
    ),
    FlowSpec(
        name="calciner_fuel",
        title="Calciner fuel",
        source=FUEL_NODE,
        target="Precalciner",
        rate_tag="calciner_fuel_rate_tph",
        kind="fuel",
        dataset="kiln",
    ),
    FlowSpec(
        name="primary_air",
        title="Primary air",
        source=AIR_NODE,
        target="RotaryKiln",
        rate_tag="primary_air_flow",
        kind="air",
        dataset="kiln",
    ),
    FlowSpec(
        name="secondary_air",
        title="Secondary air (recuperated)",
        source="Cooler",
        target="RotaryKiln",
        rate_tag="secondary_air_flow",
        kind="air",
        dataset="kiln",
        note="Cooler recuperation: the stream carries secondary_air_temperature into the kiln.",
    ),
    FlowSpec(
        name="tertiary_air",
        title="Tertiary air",
        source="Cooler",
        target="Precalciner",
        rate_tag="tertiary_air_flow",
        kind="air",
        dataset="kiln",
    ),
    FlowSpec(
        name="clinker_to_cooler",
        title="Hot clinker",
        source="RotaryKiln",
        target="Cooler",
        rate_tag="clinker_production_tph",
        kind="material",
        dataset="kiln",
    ),
    FlowSpec(
        name="exhaust_gas",
        title="Exhaust gas (ID fan)",
        source="Preheater",
        target=STACK_NODE,
        rate_tag="exhaust_gas_flow",
        kind="gas",
        dataset="kiln",
        note="Draught set by ID_fan_speed; the flow is the preheater model's own gas balance.",
    ),
    FlowSpec(
        name="clinker_to_silo",
        title="Cooled clinker",
        source="Cooler",
        target=SILO_NODE,
        rate_tag="clinker_production_tph",
        kind="material",
        dataset="kiln",
        buffered=True,
    ),
    FlowSpec(
        name="clinker_to_mill",
        title="Clinker to mill",
        source=SILO_NODE,
        target="Mill",
        rate_tag="clinker_feed_rate",
        kind="material",
        dataset="mill",
        note=(
            "Drawn from the buffer, so the two lines run at independent rates - the PRD 8.3 "
            "clinker-silo ASSUMPTION, not a modelling shortcut in the drawing."
        ),
        buffered=True,
    ),
    FlowSpec(
        name="gypsum_to_mill",
        title="Gypsum",
        source=FEED_NODE,
        target="Mill",
        rate_tag="gypsum_feed_rate",
        kind="material",
        dataset="mill",
    ),
    FlowSpec(
        name="additive_to_mill",
        title="Additive",
        source=FEED_NODE,
        target="Mill",
        rate_tag="additive_feed_rate",
        kind="material",
        dataset="mill",
    ),
    FlowSpec(
        name="mill_to_separator",
        title="Mill discharge",
        source="Mill",
        target="Separator",
        rate_tag="mill_feed_rate_tph",
        kind="material",
        dataset="mill",
        note=(
            "Scaled by mill throughput: the circulating load the separator actually sees is "
            "internal to the mill model and is not one of the PRD 12.2 tags."
        ),
    ),
    FlowSpec(
        name="separator_reject",
        title="Coarse reject",
        source="Separator",
        target="Mill",
        rate_tag="separator_speed_rpm",
        kind="material",
        dataset="mill",
        note=(
            "Scaled by separator speed, the modelled driver of circulating load "
            "(mill_dynamics.yaml circulating_load.separator_speed_exponent): a finer cut "
            "returns more material."
        ),
    ),
    FlowSpec(
        name="mill_vent_gas",
        title="Mill vent gas",
        source="Mill",
        target="FanFilter",
        rate_tag="gas_flow",
        kind="gas",
        dataset="mill",
    ),
    FlowSpec(
        name="filter_to_stack",
        title="Filtered gas",
        source="FanFilter",
        target=STACK_NODE,
        rate_tag="gas_flow",
        kind="gas",
        dataset="mill",
    ),
    FlowSpec(
        name="separator_product",
        title="Finished cement",
        source="Separator",
        target="Product",
        rate_tag="cement_production_tph",
        kind="product",
        dataset="mill",
    ),
    FlowSpec(
        name="product_to_silo",
        title="Cement to silo",
        source="Product",
        target=OUTPUT_NODE,
        rate_tag="cement_production_tph",
        kind="product",
        dataset="mill",
    ),
)


# =============================================================================
# Plant overview chain (directive item 3)
# =============================================================================
@dataclass(frozen=True, slots=True)
class OverviewStage:
    """One stage of ``Quarry/Feed -> Kiln system -> Clinker -> Cement Mill -> Cement Product``.

    ``rate_tag`` is the simulated rate that quantifies the stage, so the overview's arrows move
    with the same values its cards show, and ``equipment`` names the PRD 8.3 components the stage
    groups - the overview is a grouping of the twin, not a second diagram of it.
    """

    name: str
    title: str
    detail: str
    rate_tag: str
    dataset: str
    equipment: tuple[str, ...] = ()


#: The five stages directive item 3 names, in process order.
OVERVIEW_CHAIN: Final[tuple[OverviewStage, ...]] = (
    OverviewStage(
        name="feed",
        title="Quarry / feed",
        detail="Raw meal, gypsum and additive entering the modelled plant",
        rate_tag="kiln_feed_rate_tph",
        dataset="kiln",
    ),
    OverviewStage(
        name="kiln_system",
        title="Kiln system",
        detail="Preheater, precalciner, rotary kiln and clinker cooler",
        rate_tag="clinker_production_tph",
        dataset="kiln",
        equipment=("Preheater", "Precalciner", "RotaryKiln", "Cooler", "FanFuel"),
    ),
    OverviewStage(
        name="clinker",
        title="Clinker",
        detail="Buffer stock that decouples the two lines (PRD 8.3 ASSUMPTION)",
        rate_tag="clinker_feed_rate",
        dataset="mill",
    ),
    OverviewStage(
        name="cement_mill",
        title="Cement mill",
        detail="Closed grinding circuit with dynamic separator",
        rate_tag="mill_feed_rate_tph",
        dataset="mill",
        equipment=("Mill", "Separator", "FanFilter"),
    ),
    OverviewStage(
        name="cement_product",
        title="Cement product",
        detail="Finished cement leaving the modelled plant",
        rate_tag="cement_production_tph",
        dataset="mill",
        equipment=("Product",),
    ),
)


# =============================================================================
# Lookups
# =============================================================================
def equipment_spec(name: str) -> EquipmentSpec:
    """The component called ``name``; raises rather than returning a blank card."""
    for item in EQUIPMENT:
        if item.name == name:
            return item
    raise KeyError(f"{name!r} is not a PRD 8.3 component: {tuple(i.name for i in EQUIPMENT)}")


def flow_spec(name: str) -> FlowSpec:
    """The stream called ``name``; raises rather than animating an unknown path."""
    for item in FLOWS:
        if item.name == name:
            return item
    raise KeyError(f"{name!r} is not a modelled stream")


def equipment_for(line: str) -> tuple[EquipmentSpec, ...]:
    """The components of one line, in PRD 8.3 execution order."""
    return tuple(item for item in EQUIPMENT if item.line == line)


def flows_for(dataset: str) -> tuple[FlowSpec, ...]:
    """The streams whose rate tag belongs to one dataset."""
    return tuple(item for item in FLOWS if item.dataset == dataset)


def boundary_nodes() -> tuple[str, ...]:
    """Nodes that are stream boundaries rather than equipment (drawn as terminals)."""
    known = {item.name for item in EQUIPMENT}
    seen: list[str] = []
    for flow in FLOWS:
        for node in (flow.source, flow.target):
            if node not in known and node not in seen:
                seen.append(node)
    return tuple(seen)


def panel_tags(dataset: str) -> tuple[str, ...]:
    """Every tag a view of ``dataset`` can display, headline block first."""
    if dataset == "kiln":
        return KILN_PANEL_TAGS + KILN_PROCESS_TAGS + KILN_EMISSION_TAGS
    if dataset == "mill":
        return MILL_PANEL_TAGS + MILL_PROCESS_TAGS
    raise KeyError(f"{dataset!r} is not a modelled dataset")


__all__ = [
    "AIR_NODE",
    "DAILY_TOTALS",
    "EQUIPMENT",
    "FEED_NODE",
    "FLOWS",
    "FUEL_NODE",
    "KILN_EMISSION_TAGS",
    "KILN_KPI_TAGS",
    "KILN_KPI_TITLE",
    "KILN_LINE",
    "KILN_PANEL_TAGS",
    "KILN_PROCESS_TAGS",
    "LINE_THROUGHPUT",
    "MILL_KPI_TAGS",
    "MILL_KPI_TITLE",
    "MILL_LINE",
    "MILL_PANEL_TAGS",
    "MILL_PROCESS_TAGS",
    "OUTPUT_NODE",
    "OVERVIEW_CHAIN",
    "PLANT_KPI_TAGS",
    "PLANT_KPI_TITLE",
    "SILO_NODE",
    "STACK_NODE",
    "DailyTotal",
    "EquipmentSpec",
    "FlowSpec",
    "OverviewStage",
    "boundary_nodes",
    "equipment_for",
    "equipment_spec",
    "flow_spec",
    "flows_for",
    "panel_tags",
]
