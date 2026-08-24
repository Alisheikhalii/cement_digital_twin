"""Synthetic Cement Plant Digital Twin - Demonstration Environment.

PRD v1.1.1, Section 23: ``src`` is a normal importable Python package so the Colab
notebook and any future standalone app share identical logic - no notebook-only code
paths (NFR-7).

Nothing heavy is imported here on purpose: importing :mod:`src` must stay cheap so
``src.paths`` / ``src.labels`` can be used by documentation tooling and tests without
pulling in scikit-learn or plotly.
"""

from __future__ import annotations

__version__ = "1.1.1"          # tracks the PRD version this build implements
PRD_VERSION = "1.1.1"

__all__ = ["__version__", "PRD_VERSION"]
