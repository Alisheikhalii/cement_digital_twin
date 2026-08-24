"""``RealPlantDataProvider`` - the PRD 26.1 stub for a real plant historian.

PRD v1.1.1 Section 26.1 specifies this class precisely, and specifies it as a *stub*:

    Stub in v1.1: constructor accepts a connection profile (CSV path / SQL DSN / OPC-UA
    endpoint / Historian export path); raises ``NotImplementedError`` per method body with a
    clear TODO pointing to ``FACTORY_DATA_REQUIREMENTS.md`` and to the Synthetic-to-Real
    Transfer Strategy (Section 21).

So this module implements nothing and reads nothing. That is not an omission - it is the
deliverable. Two properties are worth being explicit about, because both are load-bearing:

**It proves FR-14 structurally.** The class satisfies :class:`~src.digital_twin.provider.DataProvider`
completely: every abstract method is present, so Python will instantiate it. A dashboard can be
handed one of these and will get a clear, actionable refusal from whichever panel it asks first -
not an ``AttributeError``, and not a number. If a future method is added to the contract and not
added here, this module stops importing, which is the check that keeps "switching providers is a
one-line change" true rather than aspirational.

**It refuses instead of approximating.** Every method raises. There is no fallback to the
synthetic source, no zero-filled frame, no empty DataFrame that a chart would render as a flat
line. A provider that cannot answer must say so (NFR-6), and here that answer also carries the
two documents a reader needs next: what to ask the factory for, and what has to happen to the
models afterwards.

The second half of that message matters more than the first. A populated
``configs/tag_mapping.yaml`` would make real data *readable*; it would not make a
synthetically-trained Model A, B or C *valid*. PRD 21.4 puts data-quality assessment,
plant-specific recalibration of every ASSUMPTION, retraining and real-plant validation between
"real data arrives" and anything being believed. Wiring a historian into this class without those
steps would produce a dashboard that looks correct and is not - which is exactly the failure this
whole Synthetic-to-Real boundary exists to prevent.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import pandas as pd

from src.digital_twin.insights import AnomalyState, OptimizationView, PredictionSet, WhatIfView
from src.digital_twin.payloads import (
    EquipmentStatus,
    KpiGroup,
    ProviderCapabilities,
    RegimeState,
    Series,
    StateSnapshot,
)
from src.digital_twin.provenance import Value
from src.digital_twin.provider import DataProvider

#: Shown in the dashboard header, so the source is named on screen and not inferred (item 20).
PROVIDER_NAME: Final = "RealPlantDataProvider"

#: The connection-profile kinds PRD 26.1 says the constructor accepts, each mapped to the
#: keyword that carries its target. PRD 26.2 lists the native export formats these become thin
#: adapters for (CSV / DCS / SCADA / Historian / SQL / OPC-UA).
PROFILE_KINDS: Final[Mapping[str, str]] = {
    "csv": "path",
    "dcs": "path",
    "scada": "path",
    "historian": "path",
    "sql": "dsn",
    "opcua": "endpoint",
}

#: The two documents PRD 26.1 requires every refusal to point at.
REQUIREMENTS_DOC: Final = "FACTORY_DATA_REQUIREMENTS.md"
TRANSFER_SECTION: Final = "PRD Section 21 (Synthetic-to-Real Transfer Strategy)"

#: The tag-mapping config of PRD 26.2. Named here rather than opened: the file exists and is
#: deliberately unpopulated, and this class is the thing that would read it once it is not.
TAG_MAPPING_CONFIG: Final = "configs/tag_mapping.yaml"


def _todo(method: str, detail: str) -> str:
    """The refusal text of one method - the PRD 26.1 "clear TODO", assembled in one place.

    One place, so no method can drift into a vaguer message than its neighbours, and so the two
    mandatory pointers cannot be forgotten on a method added later.
    """
    return (
        f"TODO: {PROVIDER_NAME}.{method}() is a v1.1 stub and reads no plant data.\n"
        f"  What it would do: {detail}\n"
        f"  Before it can: supply the historical tags requested by {REQUIREMENTS_DOC} "
        f"(PRD Section 27), then map this plant's own tag names onto the PRD Section 12 schema "
        f"in {TAG_MAPPING_CONFIG} (PRD 26.2, currently unpopulated by design).\n"
        f"  Before its numbers can be believed: follow {TRANSFER_SECTION}. PRD 21.4 requires "
        f"data-quality assessment, plant-specific recalibration of every ASSUMPTION in PRD "
        f"Sections 9-10 and 13-14, retraining of Models A/B/C on real data, and real-plant "
        f"validation - in that order. Reading real tags through a synthetic-trained model is not "
        f"a supported configuration.\n"
        f"  For a working provider today, use SyntheticDataProvider "
        f"(src/digital_twin/synthetic.py): every number it serves is simulated, and it says so."
    )


class RealPlantDataProvider(DataProvider):
    """A real plant behind the PRD 26.1 contract - constructor only, every method refuses."""

    name = PROVIDER_NAME

    def __init__(
        self,
        profile: Mapping[str, Any] | str | Path | None = None,
        *,
        kind: str | None = None,
        path: str | Path | None = None,
        dsn: str | None = None,
        endpoint: str | None = None,
        tag_mapping: Mapping[str, str] | None = None,
    ) -> None:
        """Accept a connection profile and hold it. Nothing is opened, resolved or validated.

        PRD 26.1 asks the constructor to accept "a CSV path / SQL DSN / OPC-UA endpoint /
        Historian export path", so all four arrive either as one ``profile`` mapping or as the
        keyword that fits the source. A bare string or :class:`~pathlib.Path` is read as a path,
        because that is the one profile kind with an unambiguous shorthand.

        Deliberately no connection attempt and no existence check: a stub that failed at
        construction would be indistinguishable from a misconfigured real adapter, and the
        refusal this class exists to give would never be reached. The profile is kept so
        :meth:`describe` can show what was configured.
        """
        if isinstance(profile, (str, Path)):
            profile = {"kind": kind or "csv", "path": profile}
        settings: dict[str, Any] = dict(profile or {})
        for key, value in (("kind", kind), ("path", path), ("dsn", dsn), ("endpoint", endpoint)):
            if value is not None:
                settings[key] = value
        self.profile: Mapping[str, Any] = settings
        self.kind: str | None = str(settings["kind"]) if "kind" in settings else None
        self.tag_mapping: Mapping[str, str] = dict(tag_mapping or {})

    # -- what this provider can answer (which is nothing) -----------------------------------
    def capabilities(self) -> ProviderCapabilities:
        """Every capability ``False``, so a dashboard degrades every panel instead of failing.

        The one method that does *not* raise. A view asks this first precisely so it can find out
        what is unavailable without triggering an exception per panel, and a stub that refused
        here too would force the caller into a try/except around every single call - which is the
        pattern :class:`~src.digital_twin.provider.CapabilityError` exists to avoid.

        ``synthetic=False`` is the honest answer and it is also the useful one: it is how the
        header of item 20 knows not to print the synthetic-data banner for this source. It does
        not mean real numbers are available - none are.
        """
        return ProviderCapabilities(
            name=self.name,
            synthetic=False,
            truth=False,
            history=False,
            live=False,
            predictions=False,
            anomaly=False,
            optimization=False,
            what_if=False,
            missing=(
                "timeseries",
                "tag_metadata",
                "current_state",
                "truth_state",
                "sensor_values",
                "history",
                "equipment_status",
                "kpis",
                "operating_regime",
                "anomaly",
                "predictions",
                "optimization",
                "what_if",
            ),
        )

    # -- PRD 26.1: the two mandated methods -------------------------------------------------
    def get_timeseries(
        self,
        tags: Sequence[str],
        start: datetime,
        end: datetime,
        resample: str | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError(
            _todo(
                "get_timeseries",
                "read the plant's own tags for [start, end] from the configured source, rename "
                "them to the PRD Section 12 schema, and resample to one of the PRD 26.3 targets "
                "(1s/5s/10s/30s/1min/5min) since a real historian will not hold every tag at "
                "1-minute resolution",
            )
        )

    def get_tag_metadata(self) -> pd.DataFrame:
        raise NotImplementedError(
            _todo(
                "get_tag_metadata",
                "return one row per available tag with the plant's own unit, description, "
                "expected range and native sampling interval - the plant's metadata, not the "
                "synthetic schema's, because a real instrument's range is a fact about that "
                "instrument",
            )
        )

    # -- directive item 1: the ten data kinds -----------------------------------------------
    def get_current_state(self, dataset: str | None = None) -> StateSnapshot:
        raise NotImplementedError(
            _todo(
                "get_current_state",
                "read the newest row of each mapped tag and return it in the observable channel",
            )
        )

    def get_truth_state(self, dataset: str | None = None) -> StateSnapshot:
        raise NotImplementedError(
            _todo(
                "get_truth_state",
                "nothing - and it never will. A real plant has no noise-free channel: there is "
                "no simulator behind it holding the true value, only instruments with error. "
                "This method exists on the contract because a synthetic source can honour it, "
                "and a real source must refuse it rather than return its measurements relabelled "
                "as truth (that relabelling is exactly what PRD 20's evaluation-against-truth "
                "tests would silently lose)",
            )
        )

    def get_sensor_values(self, tags: Sequence[str]) -> tuple[Value, ...]:
        raise NotImplementedError(
            _todo(
                "get_sensor_values",
                "return the named readings at the newest timestamp, each with the plant's unit "
                "and range and a status banded against the plant's own limits",
            )
        )

    def get_history(
        self,
        tags: Sequence[str],
        *,
        minutes: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        max_points: int | None = None,
        truth: bool = False,
    ) -> tuple[Series, ...]:
        raise NotImplementedError(
            _todo(
                "get_history",
                "return downsampled trends for the UI's point budget - a real historian window "
                "is far larger than a chart can draw, so the downsampling of directive item 23 "
                "matters more here than it does for a synthetic run, not less",
            )
        )

    def get_equipment_status(self) -> tuple[EquipmentStatus, ...]:
        raise NotImplementedError(
            _todo(
                "get_equipment_status",
                "report each component's state from the plant's own running/stopped signals. "
                "Note that PRD 9.5's health scalar has no real-plant equivalent to read: it is a "
                "simulation input, so on a real plant equipment condition has to be derived from "
                "measurements (vibration, bearing temperature, drive current) and calibrated per "
                "plant - a PRD 21.4 recalibration item, not a mapping item",
            )
        )

    def get_kpis(self) -> tuple[KpiGroup, ...]:
        raise NotImplementedError(
            _todo(
                "get_kpis",
                "compute the kiln, mill and plant KPI groups from mapped tags, keeping specific "
                "and total energy shown together as PRD 18.1 requires",
            )
        )

    def get_operating_regime(self) -> RegimeState:
        raise NotImplementedError(
            _todo(
                "get_operating_regime",
                "report which operating regime the plant is in. On the synthetic source this is "
                "a configured label read straight from the scenario schedule; on a real plant "
                "there is no such label to read, so it has to be derived from the operating "
                "point and agreed with the plant's own operating definitions - a PRD 21.4 "
                "calibration item",
            )
        )

    def get_anomaly_state(self, dataset: str = "kiln") -> AnomalyState:
        raise NotImplementedError(
            _todo(
                "get_anomaly_state",
                "run Model B on the current row - after Model B has been retrained on this "
                "plant's normal-regime history. A detector whose control limits came from "
                "simulated data would flag this plant's ordinary behaviour as anomalous",
            )
        )

    def get_predictions(self, dataset: str = "kiln") -> PredictionSet:
        raise NotImplementedError(
            _todo(
                "get_predictions",
                "run Model A's horizon models on the current row - after retraining on this "
                "plant's data. A synthetic-trained Model A would be predicting the simulation's "
                "dynamics, including its per-relationship delay ASSUMPTIONs, not this plant's",
            )
        )

    def get_optimization(self, *, mode: str = "NORMAL") -> OptimizationView:
        raise NotImplementedError(
            _todo(
                "get_optimization",
                "run Model C at the current operating point. This is the method to be most "
                "careful with: the optimizer's envelope, hard-constraint and OOD gates are "
                "calibrated against the synthetic plant, so on real data they would be gating "
                "against the wrong limits while still producing confident-looking setpoint "
                "advice. PRD Section 30's safety constraints and the operator-validation step of "
                "PRD 21.4 both stand between this method and any real recommendation",
            )
        )

    def run_what_if(
        self,
        changes: Mapping[str, float] | None = None,
        *,
        delta_fractions: Mapping[str, float] | None = None,
        mode: str = "NORMAL",
    ) -> WhatIfView:
        raise NotImplementedError(
            _todo(
                "run_what_if",
                "answer an operator what-if by simulating the change. This needs a *calibrated "
                "process model of this plant*, not a tag mapping: the answer comes from the twin, "
                "so it is only as valid as that twin's fit to this plant (PRD 21.4 "
                "plant-specific calibration)",
            )
        )

    def what_if_sliders(self, *, mode: str = "NORMAL") -> tuple[Mapping[str, Any], ...]:
        raise NotImplementedError(
            _todo(
                "what_if_sliders",
                "return each manipulated variable's slider bounds and step, taken from this "
                "plant's own operating limits as agreed with its process engineers - never from "
                "the synthetic configs",
            )
        )

    # -- self-description (item 20: the source is always named) -----------------------------
    def describe(self) -> dict[str, Any]:
        """What was configured and what it can do. Never raises - a header must always render."""
        payload = super().describe()
        payload["implemented"] = False
        payload["profile_kind"] = self.kind
        payload["profile_keys"] = sorted(self.profile)
        payload["mapped_tags"] = len(self.tag_mapping)
        payload["tag_mapping_config"] = TAG_MAPPING_CONFIG
        payload["requirements_doc"] = REQUIREMENTS_DOC
        payload["transfer_strategy"] = TRANSFER_SECTION
        payload["status"] = (
            f"v1.1 stub per PRD 26.1: no plant data is read. See {REQUIREMENTS_DOC} for the tags "
            f"to request and {TRANSFER_SECTION} for what must happen to the models before real "
            f"numbers mean anything."
        )
        return payload


__all__ = [
    "PROFILE_KINDS",
    "PROVIDER_NAME",
    "REQUIREMENTS_DOC",
    "TAG_MAPPING_CONFIG",
    "TRANSFER_SECTION",
    "RealPlantDataProvider",
]
