"""Task #6 host smoke tests (phase 6C): ``app.py`` assembles a real, self-contained document.

Deliberately bounded. ``DashboardSession.build()`` costs ~11-30 s and ``DashboardState.views()``
another ~8 s, so nothing here builds a session: :func:`app.build_document` takes anything exposing
``view(view_id)``, and these tests hand it local stubs. The *renderer* under test is the real
:mod:`src.visualization.svg_twin`, driven by a real (empty) ``StateSnapshot`` and the real
``configs/dashboard.yaml`` settings - so the ``<svg>``, the ``@keyframes`` and the honesty labels
asserted below are the ones a browser would receive, not fixtures.

Self-contained on purpose: no ``tests/conftest.py`` fixture is used, so this module can be run
alone (``pytest tests/test_task6_app_smoke.py``) while other phases edit the shared conftest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.payloads import StateSnapshot
from src.digital_twin.provenance import Provenance
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import VIEWS

#: The only absolute URI a self-contained document may carry: the SVG XML namespace, which is an
#: identifier the parser matches on, not an asset any browser fetches.
SVG_NAMESPACE = "http://www.w3.org/2000/svg"

REQUIRED_LABELS = (
    labels.SYNTHETIC_DEMONSTRATION_LABEL,
    labels.DECISION_SUPPORT_LABEL,
    labels.NOT_VALIDATED_LABEL,
)


# =============================================================================
# Local stubs - the whole point of build_document taking a `state` argument
# =============================================================================
@dataclass(frozen=True)
class StubHeader:
    title: str = "Kiln Digital Twin"
    subtitle: str = "Animated process twin"


@dataclass(frozen=True)
class StubTwinView:
    """Shaped like :class:`src.digital_twin.state.TwinView`: a ``line`` plus the full state."""

    header: StubHeader = field(default_factory=StubHeader)
    line: str = "kiln"
    snapshot: StateSnapshot = field(
        default_factory=lambda: StateSnapshot(
            timestamp="2024-01-01T00:00:00Z",
            mode="LIVE",
            provenance=Provenance.OBSERVED,
            source="stub",
        )
    )
    equipment: tuple[Any, ...] = ()


@dataclass(frozen=True)
class StubPayloadView:
    """Shaped like any non-twin screen: a header and a ``describe()`` payload, no ``line``."""

    header: StubHeader = field(default_factory=lambda: StubHeader("Energy Monitoring", "kWh/t"))

    def describe(self) -> dict[str, Any]:
        return {"kpis": {"specific_energy": {"value": 101.5, "unit": "kWh/t"}}}


class StubState:
    def __init__(self, models: dict[str, Any]) -> None:
        self._models = models

    def view(self, view_id: str) -> Any:
        model = self._models[view_id]
        if isinstance(model, Exception):
            raise model
        return model


def stub_state(**models: Any) -> StubState:
    return StubState(models)


@pytest.fixture(scope="module")
def settings() -> DashboardSettings:
    """The real dashboard settings - a YAML parse, milliseconds, no session."""
    return DashboardSettings.from_config()


# =============================================================================
# The document
# =============================================================================
def test_twin_document_contains_animated_svg(settings: DashboardSettings) -> None:
    html, timings = app.build_document(stub_state(B=StubTwinView()), ["B"], settings=settings)
    assert html.startswith("<!doctype html>")
    assert "<svg" in html
    assert "@keyframes" in html
    assert list(timings) == ["B"] and timings["B"] >= 0.0


def test_document_is_self_contained(settings: DashboardSettings) -> None:
    html, _ = app.build_document(stub_state(B=StubTwinView()), ["B"], settings=settings)
    external = {uri for uri in re.findall(r"https?://[^\"'\s<>)]+", html) if uri != SVG_NAMESPACE}
    assert not external, f"document references external assets: {sorted(external)}"
    for tag in ("<script", "<link", "<img", "src="):
        assert tag not in html


def test_document_carries_the_required_honesty_labels(settings: DashboardSettings) -> None:
    html, _ = app.build_document(stub_state(B=StubTwinView()), ["B"], settings=settings)
    for text in REQUIRED_LABELS:
        assert text in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html
    assert labels.LIMITATIONS_STATEMENT in html
    assert "confidence" not in html.lower()
    assert labels.FORBIDDEN_CONTROL_LABEL not in html


def test_non_twin_view_renders_its_payload_not_a_substitute(settings: DashboardSettings) -> None:
    html, timings = app.build_document(
        stub_state(B=StubTwinView(), G=StubPayloadView()), ["B", "G"], settings=settings
    )
    assert list(timings) == ["B", "G"]
    assert "specific_energy" in html
    assert "Energy Monitoring" in html
    assert "<svg" in html  # the twin section is still there


def test_meta_rows_are_escaped_into_the_document(settings: DashboardSettings) -> None:
    html, _ = app.build_document(
        stub_state(B=StubTwinView()),
        ["B"],
        settings=settings,
        meta={"seed": 20240101, "scenario": "Low <oxygen> condition"},
    )
    assert "20240101" in html
    assert "Low &lt;oxygen&gt; condition" in html


def test_a_failing_view_is_reported_never_substituted(settings: DashboardSettings) -> None:
    """BUG 1's shape: the view raises, the host names the screen and writes nothing plausible."""
    boom = ValueError("Input X contains NaN")
    with pytest.raises(RuntimeError) as caught:
        app.build_document(stub_state(H=boom), ["H"], settings=settings)
    message = str(caught.value)
    assert "'H'" in message
    assert "Input X contains NaN" in message
    assert caught.value.__cause__ is boom


# =============================================================================
# The CLI
# =============================================================================
def test_parser_accepts_the_documented_flags() -> None:
    parser = app.build_parser(["Normal - low production"])
    args = parser.parse_args(
        [
            "--out", "reports/x.html",
            "--view", "B",
            "--view", "energy",
            "--scenario", "Normal - low production",
            "--seed", "7",
            "--advance", "5",
            "--theme", "light",
            "--no-animate",
            "--replay",
            "--skip-models",
            "--no-browser",
        ]
    )
    assert args.views == ["B", "energy"]
    assert args.seed == 7 and args.advance == pytest.approx(5.0)
    assert args.theme == "light"
    assert args.animate is False and args.browser is False
    assert args.replay is True and args.skip_models is True
    assert str(args.out).endswith("x.html")


def test_defaults_are_the_cheap_twin_only_path() -> None:
    args = app.build_parser().parse_args([])
    assert args.views is None and app.DEFAULT_VIEWS == ("B",)
    assert args.skip_models is False and args.replay is False
    assert args.out == app.DEFAULT_OUT


@pytest.mark.parametrize("argv", [["--view", "Z"], ["--scenario", "not a regime"], ["--seed", "x"]])
def test_invalid_arguments_exit_non_zero(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        app.build_parser(["Normal - low production"]).parse_args(argv)
    assert caught.value.code != 0


def test_help_documents_every_view() -> None:
    text = app.build_parser().format_help()
    for view_id, key, title, _subtitle in VIEWS:
        assert view_id in text and key in text and title in text


def test_scenario_names_come_from_configuration() -> None:
    names = app._scenario_names(app._scenarios_config(None))
    assert len(names) >= 10
    assert all(isinstance(name, str) and name for name in names)


def test_seed_override_replaces_only_the_seed() -> None:
    base = app._scenarios_config(None)
    overridden = app._scenarios_config(123)
    assert overridden.get_path("simulation.seed") == 123
    assert base.get_path("simulation.seed") != 123
    assert overridden.get_path("simulation.dt_seconds") == base.get_path("simulation.dt_seconds")


# =============================================================================
# main() exit codes, with the expensive session replaced
# =============================================================================
class FakeProvider:
    def __init__(self) -> None:
        self.advanced = 0.0

    def advance(self, minutes: float = 1.0) -> None:
        self.advanced += minutes


class FakeSession:
    """Stands in for DashboardSession so main() can be exercised without an 11 s build."""

    raise_on_build: BaseException | None = None

    def __init__(self, settings: DashboardSettings) -> None:
        self.provider = FakeProvider()
        self.settings = settings
        self.training_source = "stub"
        self.replay_source = "not built"

    @classmethod
    def make(cls, settings: DashboardSettings) -> type:
        return type("_Bound", (), {"build": classmethod(lambda _c, **kw: cls(settings))})

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "StubProvider",
            "mode": "LIVE",
            "build_seconds": {"stub": 0.0},
            "capabilities": {"missing": ["predictions"]},
        }

    def notes(self) -> tuple[str, ...]:
        return ("stub session",)


def _patch_session(monkeypatch: pytest.MonkeyPatch, settings: DashboardSettings, state: Any) -> None:
    monkeypatch.setattr(
        "src.digital_twin.session.DashboardSession", FakeSession.make(settings), raising=True
    )
    monkeypatch.setattr(
        "src.digital_twin.state.DashboardState",
        type("_State", (), {"from_session": staticmethod(lambda _s: state)}),
        raising=True,
    )


def test_main_writes_the_file_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, settings: DashboardSettings, tmp_path: Any, capsys: Any
) -> None:
    _patch_session(monkeypatch, settings, stub_state(B=StubTwinView()))
    out = tmp_path / "twin.html"
    assert app.main(["--out", str(out), "--no-browser", "--advance", "3"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html and "@keyframes" in html
    assert all(text in html for text in REQUIRED_LABELS)
    printed = capsys.readouterr().out
    assert "session build" in printed and "view B" in printed and "total" in printed


def test_main_exits_three_and_writes_nothing_when_a_view_fails(
    monkeypatch: pytest.MonkeyPatch, settings: DashboardSettings, tmp_path: Any, capsys: Any
) -> None:
    _patch_session(monkeypatch, settings, stub_state(H=ValueError("Input X contains NaN")))
    out = tmp_path / "twin.html"
    assert app.main(["--out", str(out), "--no-browser", "--view", "H"]) == 3
    assert not out.exists()
    stderr = capsys.readouterr().err
    assert "'H'" in stderr and "Input X contains NaN" in stderr
    assert "no substitute values" in stderr
