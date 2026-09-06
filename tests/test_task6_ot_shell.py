"""The Cement Plant OT Platform shell — tests for the consolidated management document.

Deliberately bounded, like ``test_task6_app_smoke.py`` and ``test_task6_presentation_view.py``:
nothing here builds a session or trains a model. The document under test is the real
:func:`app.build_ot_platform_document`, which feeds a real :class:`~src.digital_twin.state.
DashboardState` over the shared ``stub_provider`` fixture through the *same* per-view dispatch
(``app.build_view_section``) that ``app.build_document`` uses — so what is asserted below is
what a browser would receive from a real run, at stub cost, and the embedded panels are the
existing renderers' own output.

Covers the wave's test list A–J:

* **A — existence**: the document builds, and the CLI (``--view OT``) writes it;
* **B — tabs**: all ten audited tabs, in order, each a panel and a nav button;
* **C — renderer reuse**: every embedded panel is byte-for-byte a ``build_view_section``
  output for the same state (the shell renders nothing of its own);
* **D/E — English and Persian modes**: title, subtitle and tab labels exist in both
  languages, the document ships ``lang="en" dir="ltr"``, and the switch mechanism carries
  ``fa`` / ``rtl``;
* **F — language switching**: the switch is CSS state on ``<html dir>`` plus
  ``.ot-en``/``.ot-fa`` visibility, and never duplicates or touches the technical panels;
* **G — self-contained**: no external script, stylesheet, image or CDN reference;
* **H — determinism**: two builds over the same state are byte-identical;
* **I — honesty**: the verbatim standing statements and mandated labels are present, the
  forbidden control label and any "confidence" wording are not;
* **J — no fabricated alerts**: every alerts entry is copied from a payload the state layer
  already built (Model B's status word, Model C's own headline, the frame's regime label), and
  no numeric health score exists.

Self-contained on purpose beyond the documented ``stub_provider`` factory, so this module runs
alone (``pytest tests/test_task6_ot_shell.py``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import VIEWS, DashboardState
from src.visualization import ot_shell, theme
from src.visualization.clock import Clock
from tests.conftest import stub_provider_class

#: The only absolute URI a self-contained document may carry: the SVG XML namespace, which is an
#: identifier the parser matches on, not an asset any browser fetches.
SVG_NAMESPACE = "http://www.w3.org/2000/svg"

#: The view ids the shell embeds, in tab order (view D stays a standalone screen — the wave's
#: audited mapping puts B+C on the Kiln tab and E+F on the Mill tab).
EMBEDDED_VIEWS: tuple[str, ...] = ("A", "B", "C", "E", "F", "G", "H", "I", "J", "P")


# =============================================================================
# Fixtures — a real state layer over the shared stub provider
# =============================================================================
@pytest.fixture(scope="module")
def settings() -> DashboardSettings:
    """The real dashboard settings - a YAML parse, milliseconds, no session."""
    return DashboardSettings.from_config()


@pytest.fixture(scope="module")
def state(settings: DashboardSettings) -> DashboardState:
    """A real DashboardState over a fresh stub provider (module-scoped: the stub is fixed-value
    and deterministic, so one instance serves every test)."""
    provider = stub_provider_class()()
    return DashboardState(provider, Clock(provider, settings), settings)


@pytest.fixture(scope="module")
def document(state: DashboardState, settings: DashboardSettings) -> str:
    """The consolidated management document, built once for the assertions below."""
    html, _ = app.build_ot_platform_document(state, settings=settings)
    return html


# =============================================================================
# A — the shell exists and the CLI writes it
# =============================================================================
def test_a_the_document_builds(document: str) -> None:
    assert document.startswith("<!doctype html>")
    assert document.endswith("</html>")
    assert ot_shell.TITLE_EN in document


def test_a_the_cli_writes_the_artifact(
    monkeypatch: pytest.MonkeyPatch,
    settings: DashboardSettings,
    tmp_path: Path,
) -> None:
    """``python app.py --view OT`` writes the consolidated document and exits zero."""
    provider = stub_provider_class()()
    state = DashboardState(provider, Clock(provider, settings), settings)
    monkeypatch.setattr(
        "src.digital_twin.session.DashboardSession", _FakeSession.make(settings), raising=True
    )
    monkeypatch.setattr(
        "src.digital_twin.state.DashboardState",
        type("_State", (), {"from_session": staticmethod(lambda _session: state)}),
        raising=True,
    )
    monkeypatch.chdir(tmp_path)
    assert app.main(["--view", "OT", "--no-browser"]) == 0
    out = tmp_path / "reports" / "cement_plant_ot_platform.html"
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert ot_shell.TITLE_EN in html and ot_shell.TITLE_FA in html


def test_a_the_ot_id_is_not_an_eleventh_screen() -> None:
    """The OT document is a shell over the ten screens, not a registry row: ``VIEWS`` stays at
    its directive-item-2 ten, and no OT id joined it."""
    assert len(VIEWS) == 10
    registered_ids = {row[0] for row in VIEWS} | {row[1] for row in VIEWS}
    assert not ({"OT", "ot-platform"} & registered_ids)


def test_a_ot_cannot_be_combined_with_other_views(capsys: pytest.CaptureFixture[str]) -> None:
    """Naming OT beside another view would silently ignore the other view — an error instead."""
    assert app.main(["--view", "OT", "--view", "B"]) == 2
    assert "on its own" in capsys.readouterr().err


# =============================================================================
# B — the audited tabs
# =============================================================================
def test_b_all_audited_tabs_exist_in_order(document: str) -> None:
    tab_keys = [tab_key for tab_key, _ in ot_shell.TABS]
    assert tab_keys == [
        "guide", "overview", "kiln", "mill", "energy",
        "prediction", "optimization", "whatif", "alerts", "presentation",
    ]
    panels = re.findall(r'<section class="ot-tabpanel" data-tab="([^"]+)"', document)
    assert panels == tab_keys
    buttons = re.findall(r'<button type="button" data-tab="([^"]+)"', document)
    assert buttons == tab_keys


def _panel(document: str, tab_key: str) -> str:
    """One tab's panel content: from its ``<section>`` opening to the next panel's (or the end).

    Split on the section opening — not on ``data-tab`` alone — because the nav buttons carry the
    same attribute and sit earlier in the document.
    """
    after = document.split(f'<section class="ot-tabpanel" data-tab="{tab_key}"', 1)[1]
    return after.split('<section class="ot-tabpanel"', 1)[0]


def test_b_each_tab_carries_its_audited_views(document: str) -> None:
    """The Kiln tab embeds both B and C; the Mill tab both E and F — never only one."""
    for view_id in ("B", "C"):
        assert f">{view_id} — " in _panel(document, "kiln"), f"view {view_id} missing from the Kiln tab"
    for view_id in ("E", "F"):
        assert f">{view_id} — " in _panel(document, "mill"), f"view {view_id} missing from the Mill tab"
    assert ">A — " in _panel(document, "overview")
    assert ">G — " in _panel(document, "energy")
    assert ">H — " in _panel(document, "prediction")
    assert ">J — " in _panel(document, "optimization")
    assert ">I — " in _panel(document, "whatif")
    assert ">P — " in _panel(document, "presentation")
    # the guide and alerts tabs carry no renderer section at all
    assert "dt-app" not in _panel(document, "guide")
    assert "dt-app" not in _panel(document, "alerts")


def test_b_every_tab_opens_with_a_bilingual_explanation(document: str) -> None:
    """Every explanation exists in the document in both languages (HTML-escaped, as rendered)."""
    assert set(ot_shell.TAB_EXPLANATIONS) == {key for key, _ in ot_shell.TABS} - {"guide"}
    for tab_key, (en, fa) in ot_shell.TAB_EXPLANATIONS.items():
        assert theme.html(en) in document, f"English explanation missing on tab {tab_key}"
        assert theme.html(fa) in document, f"Persian explanation missing on tab {tab_key}"


# =============================================================================
# C — renderer reuse: the panels are the existing renderers' own output
# =============================================================================
def test_c_every_embedded_panel_is_the_shared_dispatch_output(
    state: DashboardState, settings: DashboardSettings, document: str
) -> None:
    """Each panel in the shell is byte-for-byte the section ``build_view_section`` returns for
    the same state — the shell renders nothing of its own and never reformats a renderer."""
    wrapped = app._PresentationRequest(state)
    for view_id in EMBEDDED_VIEWS:
        _, section = app.build_view_section(wrapped, view_id, settings=settings)
        assert section in document, f"view {view_id}'s renderer output is not embedded verbatim"


def test_c_the_timings_name_every_embedded_view(
    state: DashboardState, settings: DashboardSettings
) -> None:
    _, timings = app.build_ot_platform_document(state, settings=settings)
    assert set(timings) == set(EMBEDDED_VIEWS)
    assert all(seconds >= 0.0 for seconds in timings.values())


# =============================================================================
# D / E / F — bilingual shell, both languages, the switch
# =============================================================================
def test_d_english_mode_is_the_shipping_state(document: str) -> None:
    assert '<html lang="en" dir="ltr">' in document
    assert ot_shell.TITLE_EN in document
    assert theme.html(ot_shell.SUBTITLE_EN) in document
    for en, _ in ot_shell.TAB_LABELS.values():
        assert f">{theme.html(en)}<" in document, f"English tab label missing: {en}"


def test_e_persian_mode_is_fully_present(document: str) -> None:
    assert ot_shell.TITLE_FA in document
    assert theme.html(ot_shell.SUBTITLE_FA) in document
    for _, fa in ot_shell.TAB_LABELS.values():
        assert f">{theme.html(fa)}<" in document, f"Persian tab label missing: {fa}"
    for heading_en, heading_fa, _ in ot_shell.GUIDE_BLOCKS:
        assert theme.html(heading_fa) in document, f"Persian guide heading missing: {heading_fa}"


def test_e_the_switch_carries_fa_and_rtl(document: str) -> None:
    """The mechanism itself names the Persian language and the RTL direction."""
    assert 'data-lang="fa"' in document
    assert "فارسی" in document
    assert '"rtl"' in document and '"ltr"' in document
    assert 'root.lang=lang' in document


def test_f_the_switch_is_css_state_not_a_second_copy(
    state: DashboardState, settings: DashboardSettings, document: str
) -> None:
    """Both languages always ship in one document; visibility is pure CSS on ``<html dir>``,
    and the technical panels exist exactly once — the switch cannot touch them."""
    assert 'html[dir="ltr"] .ot-fa{display:none' in document.replace(" !important;", "")
    assert 'html[dir="rtl"] .ot-en{display:none' in document.replace(" !important;", "")
    assert 'class="ot-en"' in document and 'class="ot-fa"' in document
    wrapped = app._PresentationRequest(state)
    _, section_b = app.build_view_section(wrapped, "B", settings=settings)
    assert document.count(section_b) == 1, "the technical panels must not be duplicated per language"
    # the switch script addresses only the shell's own classes — never a panel
    script = document.split("<script>", 1)[1]
    assert "ot-tech" not in script and "dt-" not in script


def test_f_the_technical_panels_stay_ltr(document: str) -> None:
    """Every embedded renderer section sits in an ``.ot-tech`` block pinned to ``dir="ltr"``,
    so RTL layout can never reorder a technical table, an SVG or an identifier."""
    blocks = re.findall(r'<div class="ot-tech" dir="ltr">', document)
    assert len(blocks) == len(EMBEDDED_VIEWS)


# =============================================================================
# G — self-contained
# =============================================================================
def test_g_the_document_is_self_contained(document: str) -> None:
    external = {
        uri for uri in re.findall(r"https?://[^\"'\s<>)]+", document) if uri != SVG_NAMESPACE
    }
    assert not external, f"document references external assets: {sorted(external)}"
    assert "<link" not in document
    assert "<img" not in document
    assert "@import" not in document
    # the only script is inline: every <script> tag opens without a src attribute
    assert "<script src" not in document
    assert document.count("<script>") == 1


# =============================================================================
# H — deterministic structure
# =============================================================================
def test_h_two_builds_are_byte_identical(
    state: DashboardState, settings: DashboardSettings, document: str
) -> None:
    again, _ = app.build_ot_platform_document(state, settings=settings)
    assert again == document


# =============================================================================
# I — honesty
# =============================================================================
def test_i_the_mandated_honesty_content_is_present(document: str) -> None:
    for text in (
        labels.SYNTHETIC_DEMONSTRATION_LABEL,
        labels.DECISION_SUPPORT_LABEL,
        labels.NOT_VALIDATED_LABEL,
        labels.NO_PLANT_CONNECTION_STATEMENT,
        labels.LIMITATIONS_STATEMENT,
        labels.TRANSFER_STRATEGY_STATEMENT,
        ot_shell.TECHNICAL_PANELS_NOTE_EN,
        ot_shell.TECHNICAL_PANELS_NOTE_FA,
    ):
        assert text in document, f"honesty text missing: {text[:40]}..."


def test_i_no_forbidden_claim(document: str) -> None:
    assert labels.FORBIDDEN_CONTROL_LABEL not in document
    assert "confidence" not in document.lower()


# =============================================================================
# J — no fabricated alerts
# =============================================================================
def test_j_every_alert_is_copied_from_an_existing_payload(
    state: DashboardState, document: str
) -> None:
    """The four alert cards carry data a payload already held: Model B's own status word (view
    A's anomaly tile), Model C's own headline (view J's payload), the frame's own regime label,
    and the screens' own header notices — each card names its source."""
    cards = re.findall(r'<div class="dt-card" data-role="alert-card" data-source="([^"]+)">', document)
    assert cards == [
        "view A anomaly status tile",
        "view J optimizer payload",
        "shared frame operating regime",
        "screen header notices",
    ]
    overview = state.view("A")
    assert overview.anomaly_status.status in document
    assert overview.anomaly_status.detail in document or not overview.anomaly_status.detail
    optimization = state.view("J")
    assert optimization.view.headline in document
    assert overview.header.regime.label in document
    # every notice row names the screen it came from and quotes that screen's own notices
    for view_id in ("H", "I", "J"):
        header = state.view(view_id).header
        joined = "; ".join(header.notices)
        if joined:
            assert joined in document, f"view {view_id}'s own notices are missing from the alerts tab"


def test_j_no_invented_health_score(document: str) -> None:
    """No numeric health/quality score exists on the Alerts tab: the word "score" appears only
    inside sentences that state there is none. (The technical panels are not scanned — view H
    legitimately shows Model B's own anomaly score, which is existing payload data.)"""
    alerts = _panel(document, "alerts")
    scored = re.findall(r"score[^<]{0,40}\d", alerts, flags=re.IGNORECASE)
    assert not scored, f"a numeric score is displayed on the Alerts tab: {scored}"
    assert theme.html(ot_shell.ALERTS_TRACEABILITY_NOTE) in alerts


# =============================================================================
# The CLI surface
# =============================================================================
def test_the_parser_accepts_the_ot_id() -> None:
    args = app.build_parser().parse_args(["--view", "OT"])
    assert args.views == ["OT"]


def test_the_parser_still_accepts_every_registered_view() -> None:
    text = app.build_parser().format_help()
    for view_id, key, title, _subtitle in VIEWS:
        assert view_id in text and key in text and title in text
    assert "--view OT" in text and app.OT_PLATFORM_IDS == frozenset({"OT", "ot-platform"})


def test_the_default_artifact_path_is_the_wave_path() -> None:
    assert app.DEFAULT_OT_OUT == Path("reports") / "cement_plant_ot_platform.html"


# =============================================================================
# Local stand-ins (the FakeSession pattern from test_task6_app_smoke.py)
# =============================================================================
class _FakeProvider:
    def advance(self, minutes: float = 1.0) -> None:  # pragma: no cover - unused by the OT path
        raise NotImplementedError


class _FakeSession:
    """Stands in for DashboardSession so main() can be exercised without an 11 s build."""

    def __init__(self, settings: DashboardSettings) -> None:
        self.provider = _FakeProvider()
        self.settings = settings
        self.training_source = "stub"
        self.replay_source = "not built"

    @classmethod
    def make(cls, settings: DashboardSettings) -> type:
        return type("_Bound", (), {"build": classmethod(lambda _cls, **kw: cls(settings))})

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "StubProvider",
            "mode": "LIVE",
            "build_seconds": {"stub": 0.0},
            "capabilities": {"missing": []},
        }

    def notes(self) -> tuple[str, ...]:
        return ()
