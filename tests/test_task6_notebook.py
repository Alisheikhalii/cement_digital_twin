"""Task #6 — PRD §25: the Colab notebook exists, is structured, and orchestrates only.

What this module pins
---------------------
``notebooks/00_cement_digital_twin_demo.ipynb`` is the single PRD §23/§25 Colab entry point.
PRD §25 lists the twelve cells in order; PRD §28 requires five demos that are "a single Colab
cell … that requires no manual setup once earlier cells have run". NFR-7 forbids application
logic living only inside notebook cells. This module enforces all three as **static structural
contracts** on the committed file:

- it exists at the PRD §23 path and is a valid nbformat-4 notebook (tests A–B);
- the twelve §25 sections appear, in order, each with at least one code cell (test C);
- section 11 contains exactly five self-contained demo cells, every ``regime=`` name is a
  *configured* ``configs/scenarios.yaml`` name (never an invented one), and Demo 3 states the
  FR-10 inject-mechanism gap rather than fabricating one (tests D);
- every ``app`` / ``src`` symbol the notebook imports actually exists — the notebook may only
  orchestrate real entry points (test E);
- no hard-coded local absolute path, no drive letters, no ``Users\\`` (test F);
- the seed is *read from* the config (``get_path("simulation.seed")``) and never restated as a
  literal anywhere in a code cell (test G);
- no business-logic duplication: no sklearn/scipy/numpy import, no direct ``PlantTwin`` /
  ``SensorModel`` / scheduler instantiation — the twin is driven only through ``DatasetGenerator``
  and ``DashboardSession`` (test H);
- every code cell compiles, and no cell uses wall-clock time or randomness — the notebook is
  rerunnable and deterministic by construction (test I, first half).

What this module deliberately does NOT do
-----------------------------------------
It does **not** execute the notebook. A full run is the real 30-day pipeline — measured at
roughly 35 minutes locally, dominated by ``train_all`` — which has no place in a regression
suite that runs in minutes. The controlled execution that *does* happen is a once-per-wave
``nbconvert --execute`` of the committed notebook in an isolated fresh clone (no ``data/``, no
joblib blobs — exactly what a Colab runtime sees), recorded in
``docs/COLAB_NOTEBOOK_IMPLEMENTATION_REPORT.md``. Real execution *on Colab itself* cannot be
verified from this environment and is claimed nowhere.

Static here means: the file's structure, its imports and its configuration statements are
checked; nothing is run, so a green suite is never mistaken for "the notebook executed".
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.config import SCENARIOS, load_config
from src.paths import PROJECT_ROOT

#: PRD §23: the notebook's committed path and name.
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "00_cement_digital_twin_demo.ipynb"

#: PRD §25: the twelve sections, in the order the PRD lists them. A header in the notebook is
#: ``## <n> — <title>``, so the order pin is a regex over the leading number, not the titles —
#: titles may be reworded, the sequence may not be reshuffled.
PRD_25_SECTIONS = tuple(range(1, 13))

#: PRD §28: the five demos, identifiable in section 11 by their ``PRD 28 demo`` meta label.
PRD_28_DEMOS = tuple(range(1, 6))

_SECTION_HEADER = re.compile(r"^## (\d+) — ", re.MULTILINE)


@pytest.fixture(scope="module")
def notebook() -> dict[str, Any]:
    """The committed notebook as a parsed JSON document."""
    assert NOTEBOOK_PATH.is_file(), f"PRD 23 path missing: {NOTEBOOK_PATH}"
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cells(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    return list(notebook["cells"])


@pytest.fixture(scope="module")
def code_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [cell for cell in cells if cell["cell_type"] == "code"]


@pytest.fixture(scope="module")
def sections(cells: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Cells grouped by the ``## <n> —`` markdown header they follow (0 = before section 1)."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    current = 0
    for cell in cells:
        if cell["cell_type"] == "markdown":
            match = _SECTION_HEADER.search(_source(cell))
            if match:
                current = int(match.group(1))
        grouped.setdefault(current, []).append(cell)
    return grouped


def _source(cell: dict[str, Any]) -> str:
    """Cell source as one string, whether nbformat stored it as a list of lines or a string."""
    source = cell["source"]
    return "".join(source) if isinstance(source, list) else str(source)


# -- A: the file exists at the PRD 23 path -------------------------------------------------


def test_a_notebook_exists_at_prd_23_path() -> None:
    """PRD §23 commits exactly one notebook, at exactly this path."""
    assert NOTEBOOK_PATH.is_file()
    notebooks = sorted((PROJECT_ROOT / "notebooks").glob("*.ipynb"))
    assert notebooks == [NOTEBOOK_PATH], "PRD 23 names one notebook; nothing else may appear"


# -- B: valid ipynb JSON --------------------------------------------------------------------


def test_b_notebook_is_valid_ipynb(notebook: dict[str, Any], cells: list[dict[str, Any]]) -> None:
    """nbformat >= 4 structure: cells, metadata, and the keys each cell type requires."""
    assert int(notebook["nbformat"]) == 4
    assert "metadata" in notebook and "kernelspec" in notebook["metadata"]
    assert cells, "a notebook with no cells is not a demo environment"
    for index, cell in enumerate(cells):
        assert cell["cell_type"] in ("code", "markdown"), f"cell {index}: unknown type"
        assert _source(cell).strip(), f"cell {index}: empty source"
        if cell["cell_type"] == "code":
            assert "outputs" in cell and "execution_count" in cell, f"cell {index}: not v4 code"


# -- C: the twelve PRD 25 sections, in order, each with a code cell -------------------------


def test_c_prd_25_sections_in_order(sections: dict[int, list[dict[str, Any]]]) -> None:
    """The section headers run 1..12 with no gap, no repeat, no extra numbered section.

    Section 0 is the title preamble — markdown only, so nothing executes before installation.
    """
    assert sorted(sections) == [0, *PRD_25_SECTIONS]
    assert all(cell["cell_type"] == "markdown" for cell in sections[0]), (
        "a code cell before the installation section would run without the setup"
    )
    for number in PRD_25_SECTIONS:
        cells_in_section = sections[number]
        assert any(cell["cell_type"] == "code" for cell in cells_in_section), (
            f"PRD 25 section {number} has no code cell"
        )


# -- D: the five PRD 28 demo cells -----------------------------------------------------------


def test_d_section_11_has_five_self_contained_demo_cells(
    sections: dict[int, list[dict[str, Any]]],
) -> None:
    """Section 11 is five standalone demo cells — each renders project views and exports HTML."""
    demo_cells = [cell for cell in sections[11] if cell["cell_type"] == "code"]
    assert len(demo_cells) == len(PRD_28_DEMOS)
    for index, cell in enumerate(demo_cells, start=1):
        source = _source(cell)
        assert "render(" in source, f"demo {index}: does not render through the project renderer"
        assert "save_demo(" in source, f"demo {index}: does not export its HTML (PRD 25 cell 12)"
        assert f'"PRD 28 demo": "{index} -' in source, f"demo {index}: not labelled as PRD 28 demo {index}"


def test_d_demo_regimes_are_configured_names(code_cells: list[dict[str, Any]]) -> None:
    """Every ``regime="..."`` the notebook passes is a name configured in scenarios.yaml.

    PRD 28's scenarios come from the config (Task #6 directive item 18); a regime string that
    is not in ``regime_schedule.regimes`` would be an invented scenario, and
    ``ScenarioDriver._resolve`` would refuse it at runtime anyway.
    """
    configured = {
        str(regime["name"]) for regime in load_config(SCENARIOS).get_path("regime_schedule.regimes")
    }
    used = set(re.findall(r'regime="([^"]+)"', "\n".join(_source(cell) for cell in code_cells)))
    assert used, "no demo drives a configured regime"
    assert used <= configured, f"invented regime names: {sorted(used - configured)}"


def test_d_demo_3_states_the_inject_gap_honestly(
    sections: dict[int, list[dict[str, Any]]],
) -> None:
    """Demo 3's cell says the inject mechanism does not exist (FR-10) and names the substitute.

    The PRD 28.3 wording is "inject a low oxygen condition"; the repository has no inject API.
    The notebook must say so rather than implying an injection happened.
    """
    demo_cells = [cell for cell in sections[11] if cell["cell_type"] == "code"]
    source = _source(demo_cells[2])
    assert "FR-10" in source and "inject" in source
    assert "scheduled regime" in source, "the substitute mechanism must be named, not implied"

# -- E: the notebook orchestrates real entry points only ------------------------------------


def _project_imports(code_cells: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Every ``(module, name)`` the notebook imports from ``app`` or ``src.*``."""
    found: set[tuple[str, str]] = set()
    for cell in code_cells:
        for node in ast.walk(ast.parse(_source(cell))):
            if isinstance(node, ast.ImportFrom) and (
                node.module == "app" or (node.module or "").startswith("src.")
            ):
                for alias in node.names:
                    found.add((node.module or "", alias.name))
    return found


def test_e_project_imports_all_resolve(code_cells: list[dict[str, Any]]) -> None:
    """Each ``from app`` / ``from src...`` name exists at runtime — the notebook may only call
    real entry points (NFR-7), so a typo'd import must fail here, not on Colab."""
    import importlib

    imports = _project_imports(code_cells)
    assert imports, "the notebook imports nothing from the project — it would be a dead demo"
    for module_name, attribute in sorted(imports):
        module = importlib.import_module(module_name)
        assert hasattr(module, attribute), f"{module_name}.{attribute} does not exist"


# -- F: no hard-coded local absolute paths ----------------------------------------------------


def test_f_no_local_absolute_paths(code_cells: list[dict[str, Any]]) -> None:
    """No drive letters, no ``Users\\``, no ``/home/``, no machine-specific path anywhere.

    A fresh Colab runtime has none of this machine's directories; PRD 25's setup must work from
    the notebook's own location (and the clone URL) alone.
    """
    joined = "\n".join(_source(cell) for cell in code_cells)
    for pattern in (r"[A-Za-z]:\\", r"Users\\", "/home/", "/Users/", "vibe coding"):
        assert not re.search(pattern, joined), f"hard-coded local path pattern {pattern!r} found"


# -- G: deterministic configuration -------------------------------------------------------------


def test_g_seed_comes_from_the_config(code_cells: list[dict[str, Any]]) -> None:
    """The seed is read via ``get_path("simulation.seed")`` and never restated as a literal.

    NFR-4's byte-identical-dataset guarantee is anchored in the config; a seed literal in a
    notebook cell would be a second source of truth that can drift from ``scenarios.yaml``.
    """
    joined = "\n".join(_source(cell) for cell in code_cells)
    assert 'get_path("simulation.seed")' in joined
    configured_seed = str(load_config(SCENARIOS).get_path("simulation.seed"))
    assert configured_seed not in joined, "the configured seed value is restated as a literal"


def test_g_no_wall_clock_or_randomness(code_cells: list[dict[str, Any]]) -> None:
    """No ``time``/``datetime``/``random`` usage in any code cell (Step 9: rerunnable,
    deterministic — no time-based randomness anywhere in the demo path)."""
    forbidden = ("import time", "from time", "datetime", "import random", "from random")
    for index, cell in enumerate(code_cells):
        source = _source(cell)
        for token in forbidden:
            assert token not in source, f"code cell {index}: {token!r} breaks determinism"


# -- H: no business-logic duplication (NFR-7) ----------------------------------------------------


def test_h_no_ml_or_solver_logic_in_cells(
    code_cells: list[dict[str, Any]],
    sections: dict[int, list[dict[str, Any]]],
) -> None:
    """No sklearn/scipy/numpy import and no estimator or splitter name in any cell.

    Model A/B training, uncertainty and the optimizer belong to ``src.models`` /
    ``src.optimization``; the notebook calls ``train_all`` and renders view J. Any of these
    tokens in a cell would mean the layer was copied rather than orchestrated. The one
    exception is PRD 25 section 1: the installation cell's *job* is naming pip packages
    (``"sklearn": "scikit-learn"``), so module-name tokens are checked everywhere but there —
    estimator names are checked everywhere, installation cell included.
    """
    module_tokens = ("sklearn", "scipy", "import numpy", "from numpy")
    estimator_tokens = ("RandomForest", "GradientBoosting", "IsolationForest",
                        "IsotonicRegression", "train_test_split", "GridSearchCV")
    install_cells = {id(cell) for cell in sections.get(1, ()) if cell["cell_type"] == "code"}
    for index, cell in enumerate(code_cells):
        source = _source(cell)
        tokens = estimator_tokens if id(cell) in install_cells else module_tokens + estimator_tokens
        for token in tokens:
            assert token not in source, f"code cell {index}: business logic {token!r} duplicated"


def test_h_twin_driven_only_through_public_layers(code_cells: list[dict[str, Any]]) -> None:
    """No direct ``PlantTwin`` / ``SensorModel`` / scheduler construction: the plant is stepped
    by ``DatasetGenerator`` (PRD 25 cell 3) and by ``DashboardSession`` (cells 8+), never by
    notebook code re-implementing the simulation loop."""
    forbidden = ("PlantTwin(", "SensorModel(", "ScenarioScheduler(", "ScenarioDriver(")
    for index, cell in enumerate(code_cells):
        source = _source(cell)
        for token in forbidden:
            assert token not in source, f"code cell {index}: direct simulation layer use {token!r}"


def test_h_third_party_limited_to_orchestration(code_cells: list[dict[str, Any]]) -> None:
    """Only display/orchestration libraries outside the project: pandas (tables), IPython,
    ipywidgets (PRD 25 cell 10's controls), and the standard library."""
    allowed_prefixes = ("json", "os", "sys", "subprocess", "importlib", "pathlib", "zipfile",
                        "ast", "pandas", "IPython", "ipywidgets", "collections", "typing")
    for index, cell in enumerate(code_cells):
        for node in ast.walk(ast.parse(_source(cell))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed_prefixes, f"cell {index}: unexpected import {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in ("app", "src"):
                    continue  # covered by test E
                assert root in allowed_prefixes, f"cell {index}: unexpected import from {node.module}"


# -- I: every cell compiles; the network stays in the installation cell -------------------------


def test_i_every_code_cell_compiles(code_cells: list[dict[str, Any]]) -> None:
    """Syntax-valid now rather than a Colab ``SyntaxError`` later. (Executed once per wave in an
    isolated clone — see the module docstring; this suite stays static and fast.)"""
    for index, cell in enumerate(code_cells):
        compile(_source(cell), f"<cell {index}>", "exec")


def test_i_subprocess_only_in_the_installation_cell(
    sections: dict[int, list[dict[str, Any]]],
) -> None:
    """``subprocess`` (git clone / pip) appears only in PRD 25 section 1: no network and no
    shell in the configuration, simulation, demo or export cells (Step 9)."""
    for number, cells_in_section in sections.items():
        for cell in cells_in_section:
            if cell["cell_type"] != "code":
                continue
            source = _source(cell)
            if "subprocess" in source:
                assert number == 1, f"subprocess use outside the installation cell (section {number})"


def test_i_honesty_banner_in_the_title(cells: list[dict[str, Any]]) -> None:
    """The title cell carries the PRD 21/30/31 synthetic-data disclaimer verbatim in spirit:
    simulation estimates, not real factory measurements."""
    title = _source(cells[0])
    assert "Synthetic Cement Plant Digital Twin" in title
    assert "not real factory measurements" in title
