"""Data access abstraction (PRD v1.1.1 Sections 8.5, 26; FR-14, FR-20).

:class:`~src.digital_twin.provider.DataProvider` is the only surface the ML pipeline, the
optimization engine and the UI are allowed to read. Two implementations sit behind it:

* :class:`~src.digital_twin.synthetic.SyntheticDataProvider` - complete, and every number it
  serves comes from the simulation of PRD Section 11.
* :class:`~src.digital_twin.real_plant.RealPlantDataProvider` - the PRD 26.1 stub. It satisfies
  the contract and refuses every method, pointing at ``FACTORY_DATA_REQUIREMENTS.md`` and the
  Synthetic-to-Real Transfer Strategy of PRD Section 21.

That pairing is what FR-14 asks for: swapping in real factory data changes the provider and
nothing above it.

``SyntheticDataProvider`` is exported lazily (PEP 562). Importing it pulls in the process models,
the trained models and the optimizer, and a view that only needs the *contract* should not pay
for the *implementation* - if the light layer could not be imported without the heavy one, "the UI
depends only on the abstraction" would be true in the type signatures and false in the import
graph. ``from src.digital_twin import SyntheticDataProvider`` still works and costs the same as it
always did; it is only the modules that never name it that get to skip it.
"""

from __future__ import annotations

from typing import Any

from src.digital_twin.insights import (
    AnomalyState,
    OptimizationView,
    PredictionSet,
    WhatIfView,
)
from src.digital_twin.payloads import (
    LIVE,
    REPLAY,
    EquipmentStatus,
    KpiGroup,
    ProviderCapabilities,
    RegimeState,
    Series,
    StateSnapshot,
)
from src.digital_twin.provenance import Provenance, Status, Value
from src.digital_twin.provider import (
    RESAMPLE_RULES,
    RESAMPLE_SECONDS,
    CapabilityError,
    DataProvider,
)
from src.digital_twin.real_plant import RealPlantDataProvider
from src.digital_twin.settings import DashboardSettings

#: Lazily-resolved exports: attribute name -> submodule that defines it.
_LAZY: dict[str, str] = {"SyntheticDataProvider": "src.digital_twin.synthetic"}


def __getattr__(name: str) -> Any:
    """Resolve the heavy exports on first use (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))


__all__ = [
    "LIVE",
    "REPLAY",
    "RESAMPLE_RULES",
    "RESAMPLE_SECONDS",
    "AnomalyState",
    "CapabilityError",
    "DashboardSettings",
    "DataProvider",
    "EquipmentStatus",
    "KpiGroup",
    "OptimizationView",
    "PredictionSet",
    "Provenance",
    "ProviderCapabilities",
    "RealPlantDataProvider",
    "RegimeState",
    "Series",
    "StateSnapshot",
    "Status",
    "SyntheticDataProvider",
    "Value",
    "WhatIfView",
]
