"""``MODEL_CARD.md`` generation (PRD v1.1.1 Sections 13.4, 22, 35).

PRD 35 requires the card to state, per model, the *Model Validity Domain*: training data range,
variables used, target, every supported horizon, the operating regimes represented, the uncertainty
method (13.1.1), the OOD/envelope strategy (14.3), both evaluation splits (13.3) with their metrics,
the known limitations, and the verbatim sentence "This model has not been validated against real
cement-plant data."

The card is *generated from a training run*, never hand-maintained. A hand-written card drifts away
from ``reports/metrics/*.json`` the first time a hyperparameter changes, and a validity domain that
no longer matches the fitted model is worse than no validity domain at all. Every number below is
read back out of the objects the run produced.

Anything the generator cannot read from a run - a limitation whose *explanation* is structural, a
deviation from the PRD, an addition beyond it - lives in :data:`MEASURED_LIMITATIONS`,
:data:`DRIFT_LIMITATION` and :data:`DEVIATIONS` in this module, so that the prose and the tables are
at least reviewed in the same file. Where such a statement rests on a measurement, the measurement
itself is still taken from the run: see :func:`_drift_measurements` and :func:`_union_verdict`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.anomaly_detection import AnomalyEvaluation
from src.config import ML, SCENARIOS, Config, load_config
from src.features.lag_features import (
    regime_categories,
    sensor_layer_regime_names,
    startup_regime_name,
)
from src.features.splits import CHRONOLOGICAL, SCENARIO_HOLDOUT
from src.labels import (
    LIMITATIONS_STATEMENT,
    MODEL_CARD_VALIDATION_STATEMENT,
    RECOMMENDATION_QUALITY_DESCRIPTION,
    TRANSFER_STRATEGY_STATEMENT,
    full_system_label,
)
from src.models.metrics import MEASURED, TRUTH
from src.models.model_a import (
    GRADIENT_BOOSTING,
    RANDOM_FOREST,
    BOOTSTRAP_ENSEMBLE,
    TREE_SPREAD,
    ModelAResult,
)
from src.models.train import ALL_ROWS, TrainingRun
from src.paths import MODEL_CARD_PATH

#: Model C exists from Task 5 onward; until then the card says so rather than describing a model
#: that is not in the run. PRD 35 asks for "Model A/B/C descriptions", and an honest "not present in
#: this training run" is the only description available before the optimizer is wired in.
MODEL_C_PENDING = (
    "Model C (envelope-protected optimization, PRD 14) is not part of a Model A/B training run and "
    "is not described by this card yet. What already exists is the component PRD 14.3 check 3 "
    "depends on: Model B's Isolation Forest score, which is the out-of-distribution gate. See "
    "*OOD and envelope strategy* below."
)

#: The PRD 11.4 regime-14 limitation. Its *numbers* are read off the run being carded by
#: :func:`_drift_measurements` and substituted into ``{measured}``, so a run on which drift became
#: detectable reports its own figures instead of repeating a development measurement. Only the
#: structural explanation - which is a property of the simulator, not of one run - is fixed here.
DRIFT_LIMITATION: tuple[str, str] = (
    "Sensor drift (PRD 11.4 regime 14) is largely undetectable by either configured method",
    "Regime 14 adds a slow bias ramp to a reading while leaving the true process untouched. At "
    "the magnitudes configured in `configs/scenarios.yaml` (0.45 % O2, 18 K burning-zone "
    "temperature, 120 cm2/g Blaine, 6 mbar mill differential pressure, ramped over 3-8 h) the "
    "ramp is smaller than each tag's own 1-minute variability, and the SPC layer's 2-hour rolling "
    "baseline absorbs most of the offset. {measured} Four candidate statistics were measured while "
    "building this layer and none separates drift from a genuine process excursion - EWMA chart "
    "level, sign persistence of that level, an OLS slope in sigma/hour, and the count of "
    "persistently displaced coupled tags all overlap the process-fault distributions. The cause is "
    "structural, not a tuning failure: the simulator's own process excursions are themselves "
    "smooth dead-time-plus-lag ramps, so \"one reading walks one way\" does not distinguish an "
    "instrument fault from a process deviation. Consequently `anomaly.sensor_discrimination."
    "report_sensor_claim` is **false**: the signature booleans are always reported as evidence, "
    "but the PRD 15 hypothesis field says the evidence is inconclusive rather than naming an "
    "instrument fault it cannot support. Detecting this regime reliably needs the Phase-2 "
    "redundancy/autoencoder method PRD 13.2 defers, or larger configured drift magnitudes.",
)

#: Limitations that were *measured* while building the ML layer, not inherited from the PRD. Each
#: entry is (title, prose). They are stated here rather than in the generated prose so that changing
#: one is a reviewed code change with the measurement attached. :data:`DRIFT_LIMITATION` is rendered
#: ahead of these and is the one entry whose figures come from the run.
MEASURED_LIMITATIONS: tuple[tuple[str, str], ...] = (
    (
        "R-squared on a narrow evaluation block is a statement about the scenario schedule",
        "R-squared is measured against the variance of the block being evaluated. A chronological "
        "tail that happens to cover one steady regime therefore turns a small MAE into a large "
        "negative R-squared. Measured: on a 3-day run `oxygen_percent` at t+30 min scored MAE 0.307 "
        "with R-squared -9.3, because the tail's own standard deviation was 0.149 - about a tenth of "
        "the training span's 1.55. The same target over the configured 30-day default has a tail "
        "containing all 14 regimes and a comparable spread. Every metric row in this card carries a "
        "`coverage` block naming the regimes and the target spread of its block, so MAE and "
        "R-squared can be read together instead of R-squared alone.",
    ),
    (
        "Metrics are only meaningful at the configured run duration",
        "A 3-day run does visit all 14 regimes *somewhere*, but any single evaluation block covers "
        "only 4-6 of them, and the scenario holdout and the chronological tail are both "
        "under-populated - per-regime recall rows come back missing rather than zero. Only the "
        "configured `duration_days` (30) gives each block a spread comparable to the training span. "
        "Any card generated from a shorter run says so under *Model validity domain* below, and the "
        "*Block composition* table states what each block actually contained.",
    ),
)

#: Additions beyond the PRD's letter and departures from it, both listed so a reviewer can object.
#: Nothing here changes simulator physics or a generated-data assumption.
DEVIATIONS: tuple[tuple[str, str], ...] = (
    (
        "ADDITION",
        "A **persistence reference** (\"the current measured value, held over the horizon\") is "
        "scored beside every model on every block. PRD 13.1 names RandomForest as the baseline; the "
        "persistence row is extra, and exists so a MAE can be read as better-than-nothing rather "
        "than in isolation. It is a reference, not a fitted model, and is never selectable.",
    ),
    (
        "ADDITION",
        "Every metric is reported twice: against the sensor-layer **measurement** the model trained "
        "on, and against the simulator's noise-free **truth** state. PRD 22 asks for the first; PRD "
        "34 item 2 asks models to be checked against the true state, which only a synthetic "
        "environment can do. The second reference is not achievable on real data and is labelled as "
        "such in the JSON.",
    ),
    (
        "ADDITION",
        "Model B is reported on three row blocks rather than two. PRD 13.2 specifies \"fitted on "
        "normal-operation windows, scored on all data\", which is the `all_rows` block and the "
        "primary row; the PRD 13.3 `chronological` and `scenario_holdout` blocks are reported "
        "beside it, each with its own independent fit.",
    ),
    (
        "ADDITION",
        "The `Startup transition` regime is excluded from Model B's headline precision/recall and "
        "reported in its own block. It is a scripted ramp with `injected_fault: null`, is not one of "
        "PRD 11.4's 14 regimes, and is deliberately withheld from the forest's fit - so counting it "
        "as a false positive would penalise the detector for correctly noticing a transient the PRD "
        "does not call a fault.",
    ),
    (
        "DEVIATION",
        "PRD 13.2 lists sensor-versus-process discrimination as an output of the detector. It is "
        "implemented and always reported as evidence, but the *claim* is suppressed "
        "(`report_sensor_claim: false`) because it was measured to be below chance at the configured "
        "drift magnitudes - see the first limitation below. This is a reporting choice, not a change "
        "to the PRD or to the data.",
    ),
)


# -- small markdown helpers -------------------------------------------------------------------
def _fmt(value: Any, digits: int = 4) -> str:
    """A number for a markdown cell; ``n/a`` for anything absent, non-finite or non-numeric.

    ``None`` is used throughout the metric payloads to mean "deliberately not computed" (MAPE near
    zero, a false-positive rate with no fault-free rows), so it must render as a visible gap rather
    than as ``0``.
    """
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number or number in (float("inf"), float("-inf")):
        return "n/a"
    return f"{number:,.{digits}g}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    """A GitHub-flavoured markdown table, or a single italic line when there are no rows."""
    if not rows:
        return ["*No rows.*"]
    lines = [
        "| " + " | ".join(str(head) for head in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def _bullet_list(items: Sequence[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- *(none)*"]


def _coverage_note(coverage: Mapping[str, Any] | None) -> str:
    """``"839 rows, 5 regimes"`` - the one-line form of a :func:`split_coverage` block."""
    if not coverage:
        return "n/a"
    rows = coverage.get("rows", 0)
    if not rows:
        return "0 rows"
    regimes = coverage.get("regimes")
    return f"{int(rows):,} rows, {regimes} regime(s)" if regimes else f"{int(rows):,} rows"


# -- Model A ----------------------------------------------------------------------------------
def _metric_rows(
    result: ModelAResult, *, split: str, block: str, reference: str
) -> list[dict[str, Any]]:
    """The subset of ``metric_rows`` one table shows, ordered target-then-horizon-then-model."""
    selected = [
        row
        for row in result.metric_rows
        if row["split"] == split and row["block"] == block and row["reference"] == reference
    ]
    return sorted(selected, key=lambda row: (row["target"], row["horizon_min"], row["model"]))


def _validity_domain(result: ModelAResult) -> list[str]:
    """PRD 35's *Model Validity Domain*: what the fitted models actually saw.

    Read off the longest-horizon model of each dataset - the training block shrinks slightly with the
    horizon (a row needs a label at ``t+h``), so the longest horizon is the conservative statement.
    """
    if not result.models:
        return ["*No models were trained for this dataset.*"]
    longest = max(result.horizons_min)
    model = result.models[(result.targets[0], longest)]
    domain = model.training_domain
    ranges = domain.get("variable_ranges", {})
    stamps = domain.get("timestamp_range", [None, None])
    lines = [
        f"- **Training rows** (at the longest horizon, t+{longest}min): "
        f"{int(domain.get('rows', 0)):,}",
        f"- **Training data range**: `{stamps[0]}` to `{stamps[1]}`",
        f"- **Operating regimes represented in training**: "
        + (", ".join(f"`{name}`" for name in domain.get("operating_regimes", [])) or "*(none)*"),
        f"- **Targets**: " + ", ".join(f"`{name}`" for name in result.targets),
        f"- **Horizons**: " + ", ".join(f"t+{value}min" for value in result.horizons_min),
        f"- **Feature columns**: {len(model.spec.feature_names)} "
        f"({len(model.spec.base_columns)} current-value + lags of "
        f"{', '.join(f'{lag:g} min' for lag in model.spec.lags_min)})",
    ]
    lines.append("")
    lines.append("Variable ranges seen in training (the PRD 14.3 check-1 envelope):")
    lines += _table(
        ["Variable", "Min", "Max"],
        [[f"`{name}`", _fmt(low), _fmt(high)] for name, (low, high) in sorted(ranges.items())],
    )
    return lines


def _selection_table(result: ModelAResult) -> list[str]:
    """PRD 13.1's required comparison table: which family won each pair, on validation MAE."""
    rows: list[list[Any]] = []
    for (target, horizon), model in sorted(result.models.items(), key=lambda item: item[0]):
        selection = model.selection
        scores = selection.get("validation_mae", {})
        rows.append(
            [
                f"`{target}`",
                f"t+{horizon}min",
                f"**{model.selected_family}**",
                _fmt(scores.get(RANDOM_FOREST)),
                _fmt(scores.get(GRADIENT_BOOSTING)),
                f"{selection.get('metric', 'mae')} on {selection.get('validation_rows', 0):,} "
                "validation rows",
            ]
        )
    return _table(
        [
            "Target", "Horizon", "Selected",
            f"{RANDOM_FOREST} MAE", f"{GRADIENT_BOOSTING} MAE", "Rule",
        ],
        rows,
    )


def _horizon_metric_table(result: ModelAResult, *, split: str, block: str) -> list[str]:
    """One PRD 22 table: every model of every pair on one block, both references side by side."""
    measured = _metric_rows(result, split=split, block=block, reference=MEASURED)
    truth = {
        (row["target"], row["horizon_min"], row["model"]): row
        for row in _metric_rows(result, split=split, block=block, reference=TRUTH)
    }
    rows: list[list[Any]] = []
    for row in measured:
        key = (row["target"], row["horizon_min"], row["model"])
        against_truth = truth.get(key, {})
        rows.append(
            [
                f"`{row['target']}`",
                row["horizon"],
                ("**" + row["model"] + "**") if row["selected"] else row["model"],
                _fmt(row.get("mae")),
                _fmt(row.get("rmse")),
                _fmt(row.get("r2")),
                _fmt(row.get("mape")),
                _fmt(against_truth.get("mae")),
                _fmt(against_truth.get("r2")),
                int(row.get("rows", 0)),
            ]
        )
    return _table(
        [
            "Target", "Horizon", "Model",
            "MAE", "RMSE", "R2", "MAPE %",
            "MAE vs truth", "R2 vs truth", "Rows",
        ],
        rows,
    )


def _uncertainty_block(result: ModelAResult, *, config: Config | None = None) -> list[str]:
    """PRD 13.1.1: the ensemble-spread method, per pair, and what it is *not*."""
    ml = config if config is not None else load_config(ML)
    configured_members = ml.get_path("uncertainty.bootstrap_ensemble_size", None)
    rows: list[list[Any]] = []
    for (target, horizon), model in sorted(result.models.items(), key=lambda item: item[0]):
        described = model.describe()["uncertainty"]
        members = described.get("bootstrap_members")
        if members is None and described["method"] == BOOTSTRAP_ENSEMBLE:
            # The ensemble is fitted on first use, so a card rendered straight after training reads
            # ``None`` here. The configured size is the number that will be used, marked as such.
            members = None if configured_members is None else f"{int(configured_members)} *(config)*"
        rows.append(
            [
                f"`{target}`",
                f"t+{horizon}min",
                f"`{described['method']}`",
                members if isinstance(members, str) else _fmt(members),
            ]
        )
    lines = _table(["Target", "Horizon", "Method", "Bootstrap members"], rows)
    lines.append("")
    lines += [
        f"`{TREE_SPREAD}` is the spread across a fitted forest's own trees, so it needs no extra "
        f"fit and has no member count. `{BOOTSTRAP_ENSEMBLE}` refits the selected gradient-boosting "
        "estimator on bootstrap resamples, and is built on first use rather than during training - a "
        "member count marked *(config)* is the configured size of an ensemble not yet materialised.",
        "",
    ]
    lines += [
        "The spread is reported as `value ± spread` in the target's own unit and is turned into the "
        "categorical **Recommendation Quality** label (`HIGH` / `MEDIUM` / `LOW`) required by FR-23. "
        "It is deliberately **not** rendered as a confidence percentage: the spread of an ensemble "
        "is not a calibrated probability, and a synthetic-only model has no basis on which to claim "
        "one. The category thresholds live in `configs/ml.yaml`, and any factor that cannot be "
        "assessed in the current context caps the label at `MEDIUM` rather than allowing `HIGH`.",
        "",
    ]
    lines += [
        f"- `{label}` — {text}" for label, text in RECOMMENDATION_QUALITY_DESCRIPTION.items()
    ]
    return lines


def model_a_section(
    dataset: str, result: ModelAResult, *, short_run: bool, config: Config | None = None
) -> list[str]:
    """The Model A part of the card for one dataset."""
    lines = [f"### Model A — {dataset}", ""]
    lines += ["#### Model validity domain", ""]
    lines += _validity_domain(result)
    if short_run:
        lines += [
            "",
            "> **This card was generated from a short run.** It is shorter than the configured "
            "`duration_days`, or some PRD 11.4 regime is missing from the chronological split "
            "entirely. Either way the tables below are structurally correct but their values are not "
            "the ones to quote — see *Block composition* for what each evaluation block contains.",
        ]
    lines += ["", "#### Method and family selection", ""]
    lines += [
        "One `RandomForestRegressor` (the PRD 13.1 baseline, always trained) and one "
        "`GradientBoostingRegressor` per (target, horizon), selected on held-out MAE from the "
        "chronological validation block. `LightGBM` is not used: PRD 13.1 admits it only if it "
        "measurably beats both, which was never tested here, so it is absent rather than "
        "half-integrated. A **persistence reference** is scored alongside but is never selectable.",
        "",
    ]
    lines += _selection_table(result)
    lines += ["", "#### Uncertainty method (PRD 13.1.1)", ""]
    lines += _uncertainty_block(result, config=config)
    for split, title in (
        (CHRONOLOGICAL, "Chronological split (PRD 13.3 split 1)"),
        (SCENARIO_HOLDOUT, "Scenario-holdout split (PRD 13.3 split 2)"),
    ):
        lines += ["", f"#### Metrics — {title}", ""]
        for block in ("validation", "test"):
            table = _horizon_metric_table(result, split=split, block=block)
            if table == ["*No rows.*"]:
                continue
            lines += [f"**{block} block**", ""]
            lines += table
            lines.append("")
        lines += _split_coverage_lines(result, split)
    return lines


def _split_coverage_lines(result: ModelAResult, split: str) -> list[str]:
    """Per-horizon block sizes, regime counts and purge width - how to read the table above."""
    rows: list[list[Any]] = []
    for horizon in sorted(result.splits):
        described = result.splits[horizon].get(split)
        if described is None:
            continue
        sizes = described.get("sizes", {})
        coverage = described.get("coverage", {})
        rows.append(
            [
                f"t+{horizon}min",
                _coverage_note(coverage.get("train")),
                _coverage_note(coverage.get("validation")),
                _coverage_note(coverage.get("test")),
                f"{described.get('embargo_min', 0):g} min",
                f"{described.get('purged_rows', 0):,}",
                sum(int(value) for value in sizes.values()),
            ]
        )
    return [
        "Block composition (why an R-squared reads the way it does):",
        "",
        *_table(
            ["Horizon", "Train", "Validation", "Test", "Embargo", "Purged", "Total rows"], rows
        ),
        "",
    ]


# -- Model B ----------------------------------------------------------------------------------
def _detection_table(evaluations: Mapping[str, AnomalyEvaluation]) -> list[str]:
    """PRD 22's Model B row for every block, primary first."""
    order = [ALL_ROWS] + [name for name in evaluations if name != ALL_ROWS]
    rows: list[list[Any]] = []
    for name in order:
        block = evaluations.get(name)
        if block is None:
            continue
        detection = block.detection
        confusion = detection.get("confusion", {})
        rows.append(
            [
                f"**{name}**" if name == ALL_ROWS else name,
                f"{block.scored_rows:,}",
                _fmt(detection.get("precision"), 3),
                _fmt(detection.get("recall"), 3),
                _fmt(detection.get("f1"), 3),
                _fmt(detection.get("false_positive_rate"), 3),
                confusion.get("true_positive", 0),
                confusion.get("false_positive", 0),
                confusion.get("false_negative", 0),
            ]
        )
    return _table(
        ["Block", "Rows scored", "Precision", "Recall", "F1", "FPR", "TP", "FP", "FN"], rows
    )


def _decision_comparison(primary: AnomalyEvaluation | None) -> list[str]:
    """The banner decision beside the ones it could have been, measured on the shipped run.

    PRD 13.2's "Method 1 (primary)" is a design choice, so the card states it as a *measured*
    trade-off rather than a preference: every number below comes from ``primary.detection`` and its
    ``alternates`` on this run, and the verdict sentence is derived from those numbers, so a run in
    which the union actually won would say so instead of repeating this one's conclusion.
    """
    if primary is None:
        return ["The primary block was not evaluated on this run, so no comparison is available."]
    detection = primary.detection
    alternates = detection.get("alternates", {})
    labels = {
        "spc_single_sample": "method 2 alone (any single SPC violation)",
        "forest_or_spc_single_sample": "union of both configured methods",
        "out_of_distribution_gate": "same forest score at the PRD 14.3 gate percentile",
    }
    rows: list[list[Any]] = [
        [
            "**forest (adopted)**",
            _fmt(detection.get("precision"), 3),
            _fmt(detection.get("recall"), 3),
            _fmt(detection.get("f1"), 3),
            _fmt(detection.get("false_positive_rate"), 3),
            "PRD 13.2 Method 1, raises the banner",
        ]
    ]
    for name, note in labels.items():
        payload = alternates.get(name)
        if payload is None:
            continue
        rows.append(
            [
                f"`{name}`",
                _fmt(payload.get("precision"), 3),
                _fmt(payload.get("recall"), 3),
                _fmt(payload.get("f1"), 3),
                _fmt(payload.get("false_positive_rate"), 3),
                note,
            ]
        )
    return [
        *_table(["Decision", "Precision", "Recall", "F1", "FPR", "Role"], rows),
        "",
        _union_verdict(detection, alternates.get("forest_or_spc_single_sample")),
    ]


def _union_verdict(detection: Mapping[str, Any], union: Mapping[str, Any] | None) -> str:
    """One sentence about the union, derived from the two rows rather than remembered."""
    if union is None:
        return (
            "The union of the two methods was not scored on this run, so the choice of Method 1 as "
            "the banner is stated here as a design decision only."
        )
    kept, other = detection.get("f1"), union.get("f1")
    kept_fpr, other_fpr = detection.get("false_positive_rate"), union.get("false_positive_rate")
    if kept is None or other is None:
        return (
            "F1 is undefined for at least one of the two decisions on this block, so the comparison "
            "is left to the table above."
        )
    recall = f"{_fmt(detection.get('recall'), 3)} → {_fmt(union.get('recall'), 3)}"
    cost = f"false-positive rate ({_fmt(kept_fpr, 3)} → {_fmt(other_fpr, 3)})"
    if other > kept and (kept_fpr is None or other_fpr is None or other_fpr <= kept_fpr):
        return (
            f"**On this run the union wins outright** (F1 {_fmt(kept, 3)} → {_fmt(other, 3)}, "
            f"{cost}). That contradicts the shipped choice of the forest alone as the banner and is "
            "reported here rather than hidden: the decision rule should be revisited."
        )
    if other > kept:
        return (
            f"Letting the control charts raise the banner as well buys recall ({recall}) and a "
            f"higher F1 ({_fmt(kept, 3)} → {_fmt(other, 3)}) at a materially worse {cost} — it "
            "trades rather than wins, so PRD 13.2's \"Method 1 (primary)\" is taken literally."
        )
    return (
        f"Letting the control charts raise the banner as well buys recall ({recall}) but lowers F1 "
        f"({_fmt(kept, 3)} → {_fmt(other, 3)}) at a worse {cost}, so PRD 13.2's "
        "\"Method 1 (primary)\" is taken literally."
    )


def _regime_recall_table(evaluation: AnomalyEvaluation) -> list[str]:
    """Per-regime recall, with the per-unit / plant-level label asymmetry made explicit."""
    rows: list[list[Any]] = []
    for name, entry in sorted(evaluation.per_regime_recall.items()):
        rows.append(
            [
                f"`{name}`",
                f"{int(entry.get('rows', 0)):,}",
                f"{int(entry.get('flagged', 0)):,}",
                _fmt(entry.get("recall"), 3),
                entry.get("metric", "recall"),
                "yes" if entry.get("injected_fault_on_this_unit") else "no",
            ]
        )
    return [
        *_table(
            ["Regime", "Rows", "Reported", "Rate", "Metric", "Fault on this unit"], rows
        ),
        "",
        "`injected_fault` is per-unit while `operating_regime` is plant-level, so a regime that "
        "perturbs the *other* unit appears here with `metric = false_positive_rate`: those rows are "
        "legitimately normal for this unit and a low rate is the good outcome. Read the `Metric` "
        "column before reading the rate.",
    ]


def model_b_section(dataset: str, result: Any) -> list[str]:
    """The Model B part of the card for one dataset (``result`` is a :class:`ModelBResult`)."""
    described = result.detector.describe()
    forest = described["isolation_forest"]
    hyper = forest.get("hyperparameters", {})
    limits = described["spc"].get("limits", {})
    primary = result.evaluations.get(ALL_ROWS)

    lines = [f"### Model B — {dataset}", ""]
    lines += ["#### Model validity domain", ""]
    lines += [
        f"- **Fitted on**: {forest.get('training_rows', 'n/a')} normal-regime rows "
        f"(`injected_fault` null and `operating_regime` in the configured normal set), with the "
        f"`{described['startup_regime_excluded_from_training']}` regime additionally withheld",
        f"- **Feature space**: {len(described['tags'])} instantaneous tags "
        f"({len(described['manipulated_variables'])} of them manipulated variables). No lags: the "
        "detector answers \"is this minute abnormal\", so a lagged feature would make its answer "
        "depend on a window rather than on the row it labels",
        f"- **Sampling interval**: {described['sampling_interval_min']:g} min",
        f"- **Statuses emitted**: {', '.join(f'`{value}`' for value in described['status_values'])}",
        f"- **Anomaly kinds emitted**: "
        + ", ".join(f"`{value}`" for value in described["anomaly_kinds"]),
        f"- **Affected variables listed**: at most {described['affected_variables_max']}",
    ]
    lines += ["", "#### Method", ""]
    lines += [
        "**Method 1 (primary, PRD 13.2).** `IsolationForest` fitted on normal-operation rows and "
        f"scored on all data: {hyper.get('n_estimators', 'n/a')} trees, contamination "
        f"`{hyper.get('contamination', 'n/a')}`, seed `{hyper.get('random_state', 'n/a')}`. Two "
        f"thresholds are derived from the fitted normal scores and reported in the registry: a flag "
        f"threshold ({_fmt(forest.get('flag_threshold'))}) that raises the banner and a stricter "
        f"out-of-distribution threshold ({_fmt(forest.get('ood_threshold'))}, the "
        f"{_fmt(forest.get('ood_threshold_percentile'))}th percentile of the normal scores) that PRD "
        "14.3 check 3 uses as its gate — one implementation, two consumers.",
        "",
        "**Method 2 (secondary, always on, PRD 13.2).** Per-tag statistical process control: a "
        f"{limits.get('window_min', 'n/a')}-minute rolling mean and an EWMA "
        f"(alpha `{limits.get('ewma_alpha', 'n/a')}`) against "
        f"±{limits.get('sigma_limit', 'n/a')}σ limits, the baseline always `shift(1)`-ed so a sample "
        "is never inside its own control limits. This layer answers *which variable is out of band* "
        "and ranks the PRD 15 affected-variable list. It does **not** vote on the banner.",
        "",
        "That division of labour was measured, not assumed. Every row below is scored on this run's "
        "primary block, and all three alternatives are published under `detection.alternates` in "
        "`reports/metrics/model_b_metrics.json`, so the choice stays auditable:",
        "",
        *_decision_comparison(primary),
    ]
    lines += ["", "#### Detection metrics (PRD 22)", ""]
    lines += _detection_table(result.evaluations)
    lines += [
        "",
        "Ground truth is `injected_fault` being non-null. `all_rows` is the primary block because it "
        "is exactly what PRD 13.2 specifies; the other two are the PRD 13.3 splits applied to the "
        "detector, each with its own independent fit. An `n/a` false-positive rate means the block "
        "contained no fault-free rows — which is the expected outcome for a scenario holdout whose "
        "rows are, by construction, all faulted.",
    ]
    if primary is not None:
        ramp = primary.detection.get("startup_ramp", {})
        lines += [
            "",
            f"Startup ramp (`{ramp.get('regime')}`, excluded from the table above): "
            f"{ramp.get('flagged', 0)} of {ramp.get('rows', 0)} rows reported. "
            f"{ramp.get('detail', '')}",
            "",
            "#### Per-regime behaviour",
            "",
        ]
        lines += _regime_recall_table(primary)
        lines += ["", "#### Sensor-versus-process discrimination", ""]
        lines += _discrimination_lines(primary)
    lines += ["", "#### Output contract (PRD 15)", ""]
    contract = described["output_contract"]
    lines += [f"- **{field}**" for field in contract["fields"]]
    lines += ["", contract["detail"]]
    return lines


def _discrimination_lines(evaluation: AnomalyEvaluation) -> list[str]:
    """The PRD 11.4 regime-14 test, scored in both scopes with the claim state stated."""
    block = evaluation.sensor_discrimination
    rows: list[list[Any]] = []
    for scope, label in (
        ("on_reported_rows", "reported rows (operational)"),
        ("on_all_fault_rows", "all fault rows (diagnostic)"),
    ):
        payload = block.get(scope, {})
        rows.append(
            [
                label,
                f"{int(payload.get('rows', 0)):,}",
                _fmt(payload.get("precision"), 3),
                _fmt(payload.get("recall"), 3),
                _fmt(payload.get("f1"), 3),
                _fmt(payload.get("positive_rate_actual"), 3),
                payload.get("no_control_chart_evidence_rows", 0),
            ]
        )
    return [
        f"Positive class: `{block.get('positive_class')}`. Sensor-layer regimes: "
        + (", ".join(f"`{name}`" for name in block.get("sensor_layer_faults", [])) or "*(none)*")
        + ".",
        "",
        *_table(
            [
                "Scope", "Rows", "Precision", "Recall", "F1",
                "Base rate", "No chart evidence",
            ],
            rows,
        ),
        "",
        f"**Sensor claim reported to the UI: "
        f"{'yes' if block.get('sensor_claim_reported') else 'no'}.** "
        + block.get("detail", ""),
        "",
        "Compare *Precision* against *Base rate*: the rule is only informative where the former "
        f"exceeds the latter by more than sampling noise. {_precision_vs_base(block)} See the "
        "limitations section.",
    ]


def _precision_vs_base(block: Mapping[str, Any]) -> str:
    """Whether the rule beat its own base rate on this run - checked, not asserted."""
    beaten: list[str] = []
    checked = 0
    for scope, label in (
        ("on_reported_rows", "the reported rows"),
        ("on_all_fault_rows", "all fault rows"),
    ):
        verdict = _beats_base_rate(block.get(scope, {}))
        if verdict is None:  # nothing flagged in that scope; precision is undefined
            continue
        checked += 1
        if verdict:
            beaten.append(label)
    if not checked:
        return "Neither scope flagged anything here, so precision is undefined in both."
    if not beaten:
        return (
            "Neither scope clears it by that margin here (two binomial standard errors of the "
            "null), which is why the claim is suppressed."
        )
    return (
        f"On this run {_and_list(beaten)} clears it by that margin (two binomial standard errors of "
        "the null), which the suppressed claim does not reflect: `report_sensor_claim` should be "
        "re-examined against these numbers."
    )


# -- the card ---------------------------------------------------------------------------------
def _header(run: TrainingRun, *, config: Config, simulation: Mapping[str, Any] | None) -> list[str]:
    lines = [
        "# MODEL_CARD",
        "",
        f"*{full_system_label()}*",
        "",
        f"> **{MODEL_CARD_VALIDATION_STATEMENT}**",
        "",
        f"> {TRANSFER_STRATEGY_STATEMENT}",
        "",
        "Every model described here was trained on **synthetic data produced by this repository's "
        "own simulator**. No real plant measurement was used at any point, and no number in this "
        "card is evidence about any real cement plant.",
        "",
        "---",
        "",
        "## Provenance",
        "",
        f"- **Generated**: {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
        "(regenerate with `python -m src.models.model_card`)",
        f"- **PRD version**: {config.get_path('meta.prd_version', '1.1.1')}",
        f"- **Datasets**: " + ", ".join(f"`{name}`" for name in sorted(run.model_a)),
        f"- **Metric reports**: "
        + ", ".join(f"`{path}`" for path in sorted(str(value) for value in run.reports.values())),
        f"- **Model registry**: " + (f"`{run.registry}`" if run.registry else "*not written*"),
    ]
    if simulation:
        lines += [
            "- **Simulation provenance** (the scalar keys; the full config is stored verbatim on "
            "every registry entry and in each dataset's export sidecar):",
            "",
            *_provenance_lines(simulation),
        ]
    return lines


def _provenance_lines(payload: Mapping[str, Any]) -> list[str]:
    """The scalar provenance keys, plus the scalars of the ``simulation`` block, as bullets.

    Deliberately not the whole payload: the generator's provenance carries every loaded config
    verbatim, which is the right thing for a registry entry and the wrong thing for a document a
    person reads. The full version is in the registry and in each dataset's export sidecar.
    """
    def scalars(block: Mapping[str, Any], prefix: str = "") -> list[str]:
        return [
            f"  - `{prefix}{key}`: `{value}`"
            for key, value in sorted(block.items())
            if not isinstance(value, (Mapping, list, tuple, set))
        ]

    lines = scalars(payload)
    nested = payload.get("simulation")
    if isinstance(nested, Mapping):
        lines += scalars(nested, prefix="simulation.")
    return lines or ["  - *(no scalar provenance keys)*"]


def _ood_section() -> list[str]:
    """PRD 35 asks the card to state the OOD/envelope strategy (PRD 14.3) explicitly."""
    return [
        "## OOD and envelope strategy (PRD 14.3)",
        "",
        "PRD 14.3 defines three checks before any recommendation is shown. Two of them are properties "
        "of the models described above and are therefore stated here:",
        "",
        "1. **Training-range check.** Every candidate manipulated-variable value is compared against "
        "the *Variable ranges seen in training* table of the relevant Model A pair. Only "
        "current-value columns are recorded for this purpose — a candidate setpoint is a value at "
        "`t`, not at `t-15 min`.",
        "2. **Constraint check.** Hard constraints are the optimizer's own (Model C, PRD 14.2), not a "
        "model property.",
        "3. **Out-of-distribution check.** Model B's Isolation Forest score, thresholded at the "
        "configured percentile of the *normal-regime* score distribution. This is a deliberately "
        "stricter threshold than the one that raises the anomaly banner: a point can be plausible "
        "enough not to alarm an operator and still be too far from the training distribution for a "
        "recommendation to be trustworthy.",
        "",
        "A candidate that fails check 1 or 3 is either rejected (Normal Mode) or shown with the "
        "fixed, non-removable *outside calibrated operating envelope* banner (Experimental Mode). "
        "The gate is never a percentage of confidence.",
        "",
    ]


def _and_list(items: Sequence[str]) -> str:
    """``"a"`` / ``"a and b"`` / ``"a, b and c"`` - so generated prose reads as prose."""
    values = list(items)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + " and " + values[-1]


def _beats_base_rate(payload: Mapping[str, Any]) -> bool | None:
    """Whether precision clears the block's base rate by more than sampling noise allows.

    A rule is only informative where its precision exceeds the base rate of the rows it scores, but a
    bare ``precision > base_rate`` comparison flips on margins far inside the noise of a few thousand
    rows - the 30-day kiln run scores 0.152 against a 0.147 base rate, which is not evidence of
    anything. The excess therefore has to clear two binomial standard errors of the null "flag at the
    same rate, independently of the label". ``None`` where the comparison cannot be made: nothing was
    flagged, so precision is undefined.
    """
    precision = payload.get("precision")
    base = payload.get("positive_rate_actual")
    confusion = payload.get("confusion", {})
    called = int(confusion.get("true_positive", 0)) + int(confusion.get("false_positive", 0))
    if precision is None or base is None or called <= 0:
        return None
    rate = min(max(float(base), 0.0), 1.0)
    margin = 2.0 * math.sqrt(rate * (1.0 - rate) / called)
    return bool(float(precision) > rate + margin)


def _drift_measurements(run: TrainingRun, *, scenarios: Config | None = None) -> str:
    """The regime-14 figures, read off the run being carded rather than remembered.

    Two measurements: what Method 1 does with the sensor-layer regimes, and whether the
    three-signature rule beats the base rate it has to beat to carry any information. The closing
    clause is derived from that comparison as well, so a run on which the rule became informative
    would say so instead of reading as if the suppression were still justified.

    The two halves are keyed differently and deliberately so: the per-regime breakdown is keyed by
    ``operating_regime`` while the rule is scored against ``injected_fault`` membership, which is why
    the regime names come from config rather than from the discrimination block's fault list.
    """
    regimes = sensor_layer_regime_names(scenarios)
    recalls: list[str] = []
    rules: list[str] = []
    informative: list[str] = []
    for dataset in sorted(run.model_b):
        primary = run.model_b[dataset].evaluations.get(ALL_ROWS)
        if primary is None:
            continue
        for name in regimes:
            entry = primary.per_regime_recall.get(str(name))
            if entry is None:  # the regime never occurred in this run
                continue
            recalls.append(
                f"{int(entry.get('flagged', 0)):,} of {int(entry.get('rows', 0)):,} `{name}` rows "
                f"on `{dataset}` ({entry.get('metric', 'recall')} {_fmt(entry.get('recall'), 3)})"
            )
        scope = primary.sensor_discrimination.get("on_all_fault_rows", {})
        precision, base = scope.get("precision"), scope.get("positive_rate_actual")
        if precision is None or base is None:
            continue
        rules.append(
            f"P={_fmt(precision, 3)} / R={_fmt(scope.get('recall'), 3)} / "
            f"F1={_fmt(scope.get('f1'), 3)} against a {_fmt(base, 3)} base rate on `{dataset}`"
        )
        if _beats_base_rate(scope):
            informative.append(f"`{dataset}`")

    parts: list[str] = []
    if recalls:
        parts.append(f"On this run the Isolation Forest reports {_and_list(recalls)}.")
    if rules:
        verdict = (
            "precision clears the base rate by more than two binomial standard errors on "
            + _and_list(informative)
            + ", which is *not* what this limitation was written against: the suppression of the "
            "claim should be re-examined against these numbers"
            if informative
            else "no unit's precision clears its base rate by more than two binomial standard "
            "errors of the null, so the rule carries no more information than flagging at the "
            "prevalence it is trying to find"
        )
        parts.append(
            "The three-signature sensor rule, scored over every fault row that has control-chart "
            f"evidence, reaches {_and_list(rules)} - {verdict}."
        )
    if not parts:
        return (
            "Model B's primary block was not evaluated on this run, so this run contributes no "
            "drift figures; the structural argument below is what remains."
        )
    return " ".join(parts)


def _limitations_section(run: TrainingRun) -> list[str]:
    lines = ["## Known limitations", "", f"{LIMITATIONS_STATEMENT}", ""]
    lines += ["### Measured during development", ""]
    drift_title, drift_prose = DRIFT_LIMITATION
    lines += [f"**{drift_title}.** {drift_prose.format(measured=_drift_measurements(run))}", ""]
    for title, prose in MEASURED_LIMITATIONS:
        lines += [f"**{title}.** {prose}", ""]
    lines += ["### Inherent to a synthetic environment", ""]
    lines += _bullet_list(
        [
            "Every relationship the models learned was *written into* the simulator. A model that "
            "reproduces it has learned the simulator, which is a necessary condition for being "
            "useful on real data and nowhere near a sufficient one.",
            "The sensor layer's noise, drift, dropout and lag are configured ASSUMPTIONs, so the "
            "signal-to-noise ratio the models were trained against is a design choice rather than a "
            "measurement of any instrument.",
            "Fault regimes are injected on a schedule, so their prevalence in the training data "
            "(and therefore every precision figure above) reflects `configs/scenarios.yaml`, not a "
            "real plant's failure rate.",
            "No model here has seen a real plant's unmeasured disturbances, raw-material "
            "variability, seasonal effects, maintenance history or operator habits.",
            "Retraining on real data is not a matter of pointing this code at a historian: see the "
            "transfer strategy (PRD 21), which requires real historical data, process-engineering "
            "validation, plant-specific calibration and operator validation first.",
        ]
    )
    lines.append("")
    lines += ["### Additions to and departures from the PRD", ""]
    for kind, prose in DEVIATIONS:
        lines += [f"- **{kind}** — {prose}"]
    lines.append("")
    return lines


def _short_run(
    run: TrainingRun,
    *,
    simulation: Mapping[str, Any] | None = None,
    scenarios: Config | None = None,
) -> bool:
    """Was this card generated from a run shorter than the configured one?

    Two independent triggers, either of which makes the tables structurally correct but not worth
    quoting:

    1. **Duration.** ``simulation.duration_days`` from the generator's provenance is below the
       ``simulation.duration_days`` configured in ``configs/scenarios.yaml``. This is the trigger
       that fires in practice, and it is a comparison against a configured number rather than an
       invented threshold.
    2. **Regime coverage.** Some PRD 11.4 regime never appears anywhere in the chronological split.
       Measured across all three blocks - the scenario holdout withholds regimes from training on
       purpose and the startup ramp is dropped from the feature matrix by design, so neither absence
       says anything about run length. This is a weaker signal than it looks: a 3-day run already
       visits all 14 regimes *somewhere*, while covering only 4-6 of them in any single block. The
       per-block counts are what the reader needs, and those are tabulated per horizon in
       :func:`_split_coverage_lines` rather than collapsed into this boolean.
    """
    if isinstance(simulation, Mapping):
        block = simulation.get("simulation")
        actual = block.get("duration_days") if isinstance(block, Mapping) else None
        configured = load_config(SCENARIOS).get_path("simulation.duration_days", None)
        if actual is not None and configured is not None and float(actual) < float(configured):
            return True
    startup = startup_regime_name(scenarios)
    expected = {name for name in regime_categories(scenarios) if name != startup}
    if not expected:
        return False
    seen: set[str] = set()
    for result in run.model_a.values():
        for horizon in result.splits.values():
            coverage = horizon.get(CHRONOLOGICAL, {}).get("coverage", {})
            for block in coverage.values():
                seen.update(str(name) for name in block.get("regime_rows", {}))
    return not expected <= seen


def render_model_card(
    run: TrainingRun,
    *,
    config: Config | None = None,
    simulation: Mapping[str, Any] | None = None,
) -> str:
    """The whole ``MODEL_CARD.md`` text for one training run."""
    ml = config if config is not None else load_config(ML)
    short = _short_run(run, simulation=simulation)
    lines = _header(run, config=ml, simulation=simulation)
    lines += ["", "---", "", "## Model A — multi-horizon prediction (PRD 13.1)", ""]
    lines += [
        "One supervised regressor per (target, horizon) pair. Targets are shifted forward by the "
        "horizon and features are strictly at or before `t`, so nothing a model reads was recorded "
        "after the minute it is labelling. Rows whose window crosses a split boundary are purged "
        "rather than merely cut (PRD 13.3).",
        "",
    ]
    for dataset in sorted(run.model_a):
        lines += model_a_section(dataset, run.model_a[dataset], short_run=short, config=ml)
        lines.append("")
    lines += ["---", "", "## Model B — anomaly detection (PRD 13.2, 15)", ""]
    for dataset in sorted(run.model_b):
        lines += model_b_section(dataset, run.model_b[dataset])
        lines.append("")
    lines += ["---", "", "## Model C — optimization (PRD 14)", "", MODEL_C_PENDING, ""]
    lines += ["---", ""]
    lines += _ood_section()
    lines += ["---", ""]
    lines += _limitations_section(run)
    lines += [
        "---",
        "",
        f"> **{MODEL_CARD_VALIDATION_STATEMENT}**",
        "",
        f"> {TRANSFER_STRATEGY_STATEMENT}",
        "",
    ]
    return "\n".join(lines)


def write_model_card(
    run: TrainingRun,
    *,
    path: Path | str | None = None,
    config: Config | None = None,
    simulation: Mapping[str, Any] | None = None,
) -> Path:
    """Render the card and write it (default: ``MODEL_CARD.md`` at the project root)."""
    destination = Path(path) if path is not None else MODEL_CARD_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_model_card(run, config=config, simulation=simulation), encoding="utf-8"
    )
    return destination


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - CLI entry point
    """Generate data, train both models and write the card - ``python -m src.models.model_card``."""
    import argparse

    from src.data_generation.generator import DatasetGenerator
    from src.models.train import train_all
    from src.simulation.simulation_config import SimulationConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration-days",
        type=float,
        default=None,
        help="override the configured run length (the default visits all 14 regimes)",
    )
    parser.add_argument("--output", type=Path, default=None, help="card path")
    parser.add_argument(
        "--no-register", action="store_true", help="skip writing models/ and registry.json"
    )
    args = parser.parse_args(argv)

    simulation = SimulationConfig.from_config(
        **({} if args.duration_days is None else {"duration_minutes": args.duration_days * 1440.0})
    )
    generated = DatasetGenerator(simulation).run()
    run = train_all(
        generated.datasets,
        truth=generated.truth,
        register=not args.no_register,
        simulation=generated.provenance,
    )
    destination = write_model_card(run, path=args.output, simulation=generated.provenance)
    print(f"wrote {destination}")
    return 0


__all__ = [
    "DEVIATIONS",
    "DRIFT_LIMITATION",
    "MEASURED_LIMITATIONS",
    "MODEL_C_PENDING",
    "model_a_section",
    "model_b_section",
    "render_model_card",
    "write_model_card",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())












