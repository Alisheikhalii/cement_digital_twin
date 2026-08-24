"""Mandated user-facing text (PRD v1.1.1 Sections 21.5, 29, 30, 31, 35; FR-16, FR-23).

Single source of truth for every label, banner and disclaimer the system displays or
writes into an export. Keeping them here (instead of inline in the UI code) is what makes
AC-11 / AC-17 / AC-18 / AC-19 testable: a test can assert that the rendered dashboard
contains these exact strings, and the no-hard-coding audit (Section 34) can allow string
constants from this module while rejecting numeric literals elsewhere.

Nothing in this module is an ``ASSUMPTION``: the two block statements are quoted verbatim
from the PRD and must not be reworded.
"""

from __future__ import annotations

from typing import Final, Literal

# --- System identity ------------------------------------------------------------------
SYSTEM_NAME: Final = "Synthetic Cement Plant Digital Twin + AI Optimization Platform"
SYSTEM_SUBTITLE: Final = "Demonstration Environment"
PRD_VERSION: Final = "1.1.1"

#: Short badge that must appear on every screen and every export (AC-11).
SYNTHETIC_DEMONSTRATION_LABEL: Final = "Synthetic Demonstration"

#: Label for any quantified benefit shown in Factory Presentation Mode (PRD 29).
SIMULATION_ESTIMATE_LABEL: Final = "Simulation Estimate"

#: FR-16 / PRD 30: every AI output carries this label, never "Automatic Control Command".
AI_RECOMMENDATION_LABEL: Final = "AI Recommendation"
DECISION_SUPPORT_LABEL: Final = "Decision Support Only"

#: Phrase that must never appear anywhere in the system (PRD 30, FR-16). Asserted by tests.
FORBIDDEN_CONTROL_LABEL: Final = "Automatic Control Command"

# --- Verbatim statements --------------------------------------------------------------
#: PRD 21.5 - required standing statement (verbatim). Must appear in
#: SIMULATION_ASSUMPTIONS.md, MODEL_CARD.md, Factory Presentation Mode and Limitations.
TRANSFER_STRATEGY_STATEMENT: Final = (
    "The synthetic model is a development and demonstration environment, not a "
    "calibrated representation of any specific cement plant."
)

#: PRD 31 - limitations statement, displayed verbatim wherever results are shown.
LIMITATIONS_STATEMENT: Final = (
    "This is a synthetic demonstration environment. The simulation is not calibrated "
    "against a real cement plant. The AI models are not production-validated. "
    "Energy-saving percentages are simulation results, not guaranteed factory savings. "
    "Real deployment requires real historical data, process-engineering validation, "
    "plant-specific calibration, OT/IT integration, cybersecurity review, operator "
    "validation, safety validation, and commissioning."
)

#: PRD 35 - explicit statement required in MODEL_CARD.md.
MODEL_CARD_VALIDATION_STATEMENT: Final = (
    "This model has not been validated against real cement-plant data."
)

#: PRD 14.3 / 16.1 - fixed, non-removable banner on every Experimental-Mode result.
OUTSIDE_ENVELOPE_BANNER: Final = (
    "Outside calibrated operating envelope — low reliability."
)

#: PRD 15 - anomaly output must be phrased as a hypothesis, never a diagnosis.
ANOMALY_HYPOTHESIS_LABEL: Final = "Likely cause (model-based hypothesis)"
RULE_BASED_SUGGESTION_LABEL: Final = "Suggested action (rule-based suggestion, not a diagnosis)"

#: PRD 14.3 / 30 - what the optimizer says when no candidate survives the gates. The
#: constraints are never relaxed to manufacture a recommendation, so "nothing to
#: recommend" has to be a first-class, displayable outcome rather than an error.
NO_SAFE_RECOMMENDATION: Final = "No safe recommendation found"

#: PRD 14.5 / 30 - the standing caveat on every reported saving. Kept separate from
#: LIMITATIONS_STATEMENT so an optimization panel can show the one-line form beside a
#: number and the full statement once per view.
SIMULATED_SAVING_CAVEAT: Final = (
    "Simulated saving from a synthetic model - not a guaranteed real-world saving."
)

# --- Dashboard wording (PRD 17-19, 29; Task #6 directive items 11, 20) ----------------
#: Shown instead of a cause when Model B's evidence does not separate the readings. Task #6
#: directive item 11: display this rather than inventing a diagnosis. It is the display form of
#: src.anomaly_detection.detector.INCONCLUSIVE_HYPOTHESIS, which stays the full explanation.
EVIDENCE_INCONCLUSIVE_LABEL: Final = "Evidence inconclusive"

#: The two remaining phrases directive item 20 allows a screen to use, kept here so no view can
#: reword them. A number that a simulation produced is a "Simulated result"; a model that has
#: never seen plant data is "Not validated against real plant data".
SIMULATED_RESULT_LABEL: Final = "Simulated result"
NOT_VALIDATED_LABEL: Final = "Not validated against real plant data"

#: Directive item 20: a screen must never imply plant connectivity or automatic control. This is
#: the standing footer of every view, alongside LIMITATIONS_STATEMENT.
NO_PLANT_CONNECTION_STATEMENT: Final = (
    "This dashboard reads a synthetic simulation. It is not connected to any plant, it "
    "reads no plant instrument, and it writes no setpoint: every recommendation is decision "
    "support for a human operator."
)

#: Shown where a panel would otherwise display a model output that has not been trained. A
#: missing model is stated, never filled in with a plausible number (NFR-6).
MODEL_UNAVAILABLE_LABEL: Final = "Model not available"
MODEL_UNAVAILABLE_STATEMENT: Final = (
    "This panel needs a trained model that is not present in this session. Train the model "
    "layer first - the panel shows no number rather than a substitute one."
)

#: The three verdicts a what-if scenario can carry (Task #6 directive item 13). They are display
#: forms of states the what-if engine already reached - ``accepted``, ``simulated`` and the
#: envelope status - not a second judgement of the same scenario.
WHAT_IF_VERDICT_PASS: Final = "PASS / WITHIN ENVELOPE"
WHAT_IF_VERDICT_REJECTED: Final = "REJECTED / OUTSIDE ENVELOPE"
WHAT_IF_VERDICT_NONE: Final = "NO SAFE RECOMMENDATION FOUND"
WHAT_IF_VERDICT_VALUES: Final[tuple[str, ...]] = (
    WHAT_IF_VERDICT_PASS,
    WHAT_IF_VERDICT_REJECTED,
    WHAT_IF_VERDICT_NONE,
)

# --- Categorical vocabularies (FR-23 / PRD 14.4) --------------------------------------
RecommendationQuality = Literal["HIGH", "MEDIUM", "LOW"]
OptimizationMode = Literal["NORMAL", "EXPERIMENTAL"]
EnvelopeStatus = Literal["WITHIN_ENVELOPE", "OUTSIDE_ENVELOPE"]
ConstraintStatus = Literal["PASS", "REJECTED", "FLAGGED_FOR_REVIEW"]

RECOMMENDATION_QUALITY_VALUES: Final[tuple[str, ...]] = ("HIGH", "MEDIUM", "LOW")
OPTIMIZATION_MODE_VALUES: Final[tuple[str, ...]] = ("NORMAL", "EXPERIMENTAL")
ENVELOPE_STATUS_VALUES: Final[tuple[str, ...]] = ("WITHIN_ENVELOPE", "OUTSIDE_ENVELOPE")
CONSTRAINT_STATUS_VALUES: Final[tuple[str, ...]] = ("PASS", "REJECTED", "FLAGGED_FOR_REVIEW")

#: Human-readable gloss for the categorical quality label. FR-23: the UI shows the
#: category and this wording - never a numeric confidence percentage.
RECOMMENDATION_QUALITY_DESCRIPTION: Final[dict[str, str]] = {
    "HIGH": (
        "Tight model-ensemble spread, close agreement between model families, "
        "comfortable margin to every hard constraint, and clearly inside the "
        "training distribution."
    ),
    "MEDIUM": (
        "Moderate ensemble spread, some disagreement between model families, or a "
        "narrow margin to a hard constraint / the edge of the training distribution."
    ),
    "LOW": (
        "Wide ensemble spread, disagreeing model families, a very narrow constraint "
        "margin, or an operating point far from the training distribution."
    ),
}

# --- Alarm / status vocabulary (PRD 17.1 green/amber/red coding) -----------------------
StatusLevel = Literal["NORMAL", "WARNING", "ALARM"]
STATUS_LEVEL_VALUES: Final[tuple[str, ...]] = ("NORMAL", "WARNING", "ALARM")

# --- Equipment state vocabulary (Task #6 directive item 4: "equipment state changes") --
#: The four words an equipment item in the animated twin can be in. They are *readings* of
#: quantities the simulation already produces, never a new threshold: RUNNING/IDLE is the item's
#: line throughput against ``animation.min_rate_fraction`` (a presentation constant in
#: ``configs/dashboard.yaml``), DERATED is ``EquipmentHealthProcess`` health at or below the
#: unit's own ``equipment.health.fault_health_drop`` step-down - the loss PRD 9.5 applies when a
#: mechanical fault lands, so no limit is invented here - and UNKNOWN is the honest answer when
#: the item's driving reading is absent from the payload (NFR-6: a missing number is stated, never
#: replaced by an assumed one). "Health below 1.0" would not do for DERATED: the same config block
#: also decays health continuously at ``degradation_per_day``, so every component would read
#: DERATED within the first hour of any run and RUNNING would be unreachable.
EquipmentState = Literal["RUNNING", "IDLE", "DERATED", "UNKNOWN"]
EQUIPMENT_RUNNING: Final = "RUNNING"
EQUIPMENT_IDLE: Final = "IDLE"
EQUIPMENT_DERATED: Final = "DERATED"
EQUIPMENT_UNKNOWN: Final = "UNKNOWN"
EQUIPMENT_STATE_VALUES: Final[tuple[str, ...]] = (
    EQUIPMENT_RUNNING,
    EQUIPMENT_IDLE,
    EQUIPMENT_DERATED,
    EQUIPMENT_UNKNOWN,
)

#: Task #6 directive item 12, verbatim: "The dashboard must NOT show only the favorable metric."
#: Carried on the plant KPI group so the specific/total pair is always read together - specific
#: energy can fall while the total rises because production rose, and both are shown.
SPECIFIC_VS_TOTAL_NOTE: Final = (
    "Specific energy (per tonne) and total energy (per day) are shown together: specific "
    "energy can fall while the daily total rises because production rose. Neither number is "
    "the whole picture on its own."
)


def presentation_card_label(kind: str = "estimate") -> str:
    """Return the mandatory label for a Factory Presentation Mode KPI card (PRD 29).

    ``kind`` selects between the two allowed labels: ``"synthetic"`` ->
    "Synthetic Demonstration", anything else -> "Simulation Estimate".
    """
    return SYNTHETIC_DEMONSTRATION_LABEL if kind == "synthetic" else SIMULATION_ESTIMATE_LABEL


def full_system_label() -> str:
    """``"<name> - <subtitle> (PRD v<version>)"`` used in headers and export sidecars."""
    return f"{SYSTEM_NAME} — {SYSTEM_SUBTITLE} (PRD v{PRD_VERSION})"


__all__ = [
    "SYSTEM_NAME",
    "SYSTEM_SUBTITLE",
    "PRD_VERSION",
    "SYNTHETIC_DEMONSTRATION_LABEL",
    "SIMULATION_ESTIMATE_LABEL",
    "AI_RECOMMENDATION_LABEL",
    "DECISION_SUPPORT_LABEL",
    "FORBIDDEN_CONTROL_LABEL",
    "TRANSFER_STRATEGY_STATEMENT",
    "LIMITATIONS_STATEMENT",
    "MODEL_CARD_VALIDATION_STATEMENT",
    "OUTSIDE_ENVELOPE_BANNER",
    "ANOMALY_HYPOTHESIS_LABEL",
    "RULE_BASED_SUGGESTION_LABEL",
    "NO_SAFE_RECOMMENDATION",
    "SIMULATED_SAVING_CAVEAT",
    "EVIDENCE_INCONCLUSIVE_LABEL",
    "SIMULATED_RESULT_LABEL",
    "NOT_VALIDATED_LABEL",
    "NO_PLANT_CONNECTION_STATEMENT",
    "SPECIFIC_VS_TOTAL_NOTE",
    "MODEL_UNAVAILABLE_LABEL",
    "MODEL_UNAVAILABLE_STATEMENT",
    "WHAT_IF_VERDICT_PASS",
    "WHAT_IF_VERDICT_REJECTED",
    "WHAT_IF_VERDICT_NONE",
    "WHAT_IF_VERDICT_VALUES",
    "RecommendationQuality",
    "OptimizationMode",
    "EnvelopeStatus",
    "ConstraintStatus",
    "StatusLevel",
    "EquipmentState",
    "EQUIPMENT_RUNNING",
    "EQUIPMENT_IDLE",
    "EQUIPMENT_DERATED",
    "EQUIPMENT_UNKNOWN",
    "EQUIPMENT_STATE_VALUES",
    "RECOMMENDATION_QUALITY_VALUES",
    "OPTIMIZATION_MODE_VALUES",
    "ENVELOPE_STATUS_VALUES",
    "CONSTRAINT_STATUS_VALUES",
    "STATUS_LEVEL_VALUES",
    "RECOMMENDATION_QUALITY_DESCRIPTION",
    "presentation_card_label",
    "full_system_label",
]
