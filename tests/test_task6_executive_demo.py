"""Focused Executive-Demo regression tests: the six directive guarantee groups.

Bounded on purpose, like ``test_task6_ot_shell.py``: nothing here trains a model or builds a
session. The document under test is the real :func:`app.build_ot_platform_document` over the
shared ``stub_provider`` fixture, at stub cost, with the real per-view dispatch — so every
assertion below checks what a browser would receive from a real export, minus the model layer.

The six groups (the wave's constraint 15):

* **Localization** — the technical panels are bilingual (``dt-en``/``dt-fa`` pairs), the Persian
  side is real cement-process Persian (spot-checked words), and a canonical technical
  identifier never appears renamed;
* **RTL/LTR** — the shipping state is ``lang="en" dir="ltr"``, the switch writes ``fa``/``rtl``,
  and the CSS language rules key off ``html[dir]`` (the same attribute) — one mechanism, both
  documents;
* **Tables** — the global three-column-stability fix (``minmax(min(...,100%),1fr)`` floors and
  ``min-width:0`` cards) is present in the shared stylesheet and in the per-view layout CSS the
  renderers carry;
* **Simulated live** — exactly one inline script; it embeds a non-empty ``OT_TIMELINE`` built
  from the renderers' own output; the playback bar carries Play/Pause/Reset, 1x/2x/4x, a clock
  and a progress element; the timestamp visibly advances across ticks; and ``Math.random`` /
  ``setInterval`` misuse are absent;
* **Honesty** — the exact global disclosure wording (EN and FA) appears; the playback label is
  the mandated "SIMULATED LIVE DEMO" pair and never bare "LIVE"/"REAL-TIME"; the per-panel
  synthetic badges are *gone* (one disclosure, not one per screen);
* **Self-contained** — no external URL, no ``<link>``, no ``<img>``, no ``@import``, no script
  ``src``; only the SVG namespace identifier.

Plus the playback-honesty edge the stub exercises: a state whose provider cannot move yields
``OT_TIMELINE=null`` and the controls still render (never a frozen clock pretending to run).

Self-contained on purpose, so this module runs alone
(``pytest tests/test_task6_executive_demo.py``).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

import app
from src import labels
from src.digital_twin.settings import DashboardSettings
from src.digital_twin.state import DashboardState
from src.visualization import ot_shell, playback, theme
from src.visualization.i18n import FA_CLASS
from src.visualization.clock import Clock
from tests.conftest import stub_provider_class

#: The only absolute URI a self-contained document may carry (the SVG XML namespace).
SVG_NAMESPACE = "http://www.w3.org/2000/svg"

#: A canonical machine identifier that must survive every localization untouched.
CANONICAL_ID = "mill_motor_power_kw"


# =============================================================================
# Fixtures — a real state layer over the shared stub provider
# =============================================================================
@pytest.fixture(scope="module")
def settings() -> DashboardSettings:
    """The real dashboard settings - a YAML parse, milliseconds, no session."""
    return DashboardSettings.from_config()


@pytest.fixture(scope="module")
def state(settings: DashboardSettings) -> DashboardState:
    """A real DashboardState over a fresh stub provider (fixed-value, deterministic)."""
    provider = stub_provider_class()()
    return DashboardState(provider, Clock(provider, settings), settings)


@pytest.fixture(scope="module")
def document(state: DashboardState, settings: DashboardSettings) -> str:
    """The consolidated management document, built once for the assertions below."""
    html, _ = app.build_ot_platform_document(state, settings=settings)
    return html


def _script(document: str) -> str:
    """The document's one inline script (the self-contained group asserts there is exactly one)."""
    return document.split("<script>", 1)[1]


def _timeline_literal(document: str) -> dict[str, Any]:
    """The ``OT_TIMELINE`` literal parsed back out of the script (JSON, ``<\\/`` un-escaped)."""
    import json

    match = re.search(r"var OT_TIMELINE=(.*?);\n", _script(document), re.DOTALL)
    assert match, "the script must define OT_TIMELINE"
    return json.loads(match.group(1).replace("<\\/", "</"))


# =============================================================================
# Localization — bilingual technical panels, canonical identifiers intact
# =============================================================================
def test_localization_the_technical_panels_ship_both_languages(document: str) -> None:
    """The embedded panels carry ``dt-en``/``dt-fa`` pairs — the panels themselves are bilingual,
    not only the shell around them."""
    assert document.count(f'class="{FA_CLASS}"') > 100, "the technical panels must carry Persian"


def test_localization_persian_is_real_cement_process_persian(document: str) -> None:
    """Spot-checks of technically correct cement-process Persian, not transliteration."""
    for word in (
        "کورهٔ دوار",           # rotary kiln
        "آسیای سیمان",        # cement mill
        "کلینکر",             # clinker
        "پیش‌گرم‌کننده",        # preheater
        "جداکننده",           # separator
    ):
        assert word in document, f"Persian process term missing: {word}"


def test_localization_canonical_identifiers_are_never_renamed(document: str) -> None:
    """A canonical machine identifier appears intact (canonical English form), and in the Persian
    reference form ``شناسه فنی: <bdi>mill_motor_power_kw</bdi>`` — never a renamed tag."""
    assert CANONICAL_ID in document
    assert f"شناسه فنی: <bdi>{CANONICAL_ID}</bdi>" in document


def test_localization_every_view_title_is_bilingual(document: str) -> None:
    """Every *embedded* view heading renders as a bilingual title pair (``dt-mono`` id + ``dt-en``
    / ``dt-fa`` title), and the Persian dictionary covers all ten titles the registry carries.
    (View D stays a standalone screen by the audited tab mapping, so it is not embedded — that
    is the shell's own test's pin, not this one's.)"""
    from src.digital_twin.state import VIEWS
    from src.visualization.i18n import TITLE_FA

    embedded = {view_id for _, ids in ot_shell.TABS for view_id in ids}
    for view_id, _key, title, _subtitle in VIEWS:
        assert title in TITLE_FA, f"Persian translation missing for view title {title!r}"
        if view_id not in embedded:
            continue
        needle = f'>{view_id}</span> — <span class="dt-en" dir="ltr">{theme.html(title)}</span>'
        assert needle in document, f"bilingual heading missing for view {view_id}"


# =============================================================================
# RTL / LTR — one mechanism, both documents
# =============================================================================
def test_rtl_the_shipping_state_is_ltr_and_the_switch_reaches_rtl(document: str) -> None:
    assert '<html lang="en" dir="ltr">' in document
    assert 'data-lang="fa"' in document
    script = _script(document)
    assert 'root.lang=lang' in script
    assert '"rtl"' in script and '"ltr"' in script


def test_rtl_the_css_language_rules_key_off_html_dir(document: str) -> None:
    """The shared stylesheet's language rules and the shell's own rules both read ``html[dir]``
    — the same attribute ``otSetLang`` writes — so one attribute write switches everything."""
    assert 'html[dir="rtl"]' in document
    assert 'html:not([dir="rtl"])' in document


def test_rtl_numbers_and_identifiers_are_bidi_isolated(document: str) -> None:
    """``<bdi>`` isolation wraps the canonical identifier reference and the playback clock, so
    RTL layout can never reorder a number or an identifier."""
    assert "شناسه فنی: <bdi>" in document
    assert '<bdi data-role="playback-clock"></bdi>' in document


# =============================================================================
# Tables — the global three-column-stability fix
# =============================================================================
def test_tables_the_shared_stylesheet_fixes_grid_overflow(document: str) -> None:
    """The shared stylesheet carries the global table/grid stability rules: capped grid floors
    and ``min-width:0`` cards, so a long identifier can never blow a track into its neighbour."""
    assert "min-width:0" in document
    assert "overflow-wrap:anywhere" in document


def test_tables_every_kpi_grid_uses_a_capped_floor(document: str) -> None:
    """The per-view layout CSS carries ``minmax(min(...,100%),1fr)`` floors — the fix that made
    the three-column KPI grids collapse instead of overflowing."""
    capped = re.findall(r"minmax\(min\([^)]+\),1fr\)", document)
    assert len(capped) >= 6, "the capped-grid floor must appear across the views' layout CSS"


# =============================================================================
# Simulated live playback — controls, clock, advancing timeline, no randomness
# =============================================================================
def test_simulated_live_the_document_embeds_one_inline_runtime(document: str) -> None:
    script = _script(document)
    assert document.count("<script>") == 1
    assert "var OT_TIMELINE=" in script
    assert "Math.random" not in script
    assert "document.body.classList" in script  # the JS-gated reveal, not a second copy


def test_simulated_live_the_playback_bar_carries_the_mandated_controls(document: str) -> None:
    bar = document.split('data-role="playback-bar"', 1)[1].split("</div>", 1)[0]
    assert "otTogglePlay()" in bar
    assert "otResetPlayback()" in bar
    assert 'data-role="playback-clock"' in document
    assert 'data-role="playback-progress"' in document
    for speed in ("1x", "2x", "4x"):
        assert f">{speed}</button>" in document, f"speed button {speed} missing"
    assert 'data-speed="4"' in document


def test_simulated_live_the_clock_visibly_advances(document: str) -> None:
    """A provider whose clock moves yields a timeline whose stamps strictly advance, and the
    runtime's clock reads the ``stamp`` anchor and advances frame-by-frame (``otIndex++`` then
    ``otApply(otTicks[otIndex])``). The stub build's provider is fixed-value, so this property
    is exercised on a minimal fake state whose render output changes per tick — the same
    render-then-diff path the real export takes."""
    stamp = {"value": 0}

    class _MovingProvider:
        def advance(self, minutes: float = 1.0) -> None:
            stamp["value"] += int(minutes)

        def timestamp(self):
            import datetime as dt

            return dt.datetime(2026, 1, 1) + dt.timedelta(minutes=stamp["value"])

        def position(self):
            return {"step_minutes": 1.0}

    class _MovingState:
        """The shape ``_provider_of`` walks: a state whose ``_provider`` attribute is the clock."""

        _provider = _MovingProvider()

    def render_view(_state: Any, _view_id: str) -> tuple[Any, str]:
        import datetime as dt

        now = (dt.datetime(2026, 1, 1) + dt.timedelta(minutes=stamp["value"])).isoformat()
        return None, (
            f'<span><bdi data-otk="stamp">{now}</bdi></span>'
            f'<span><bdi data-otk="v:mill_motor_power_kw">{stamp["value"]}</bdi></span>'
        )

    timeline = playback.build_timeline(
        _MovingState(), render_view=render_view, settings=None, ticks=4
    )
    assert timeline is not None, "a provider whose clock moves must yield a timeline"
    stamps = [tick["stamp"] for tick in timeline["ticks"]]
    assert len(stamps) == 4
    assert stamps == sorted(stamps) and len(set(stamps)) == 4, "the simulated clock must advance"
    # tick 1+ ship only the delta: the stamp and the value patch, not a second full frame
    assert timeline["ticks"][1] == {
        "stamp": "2026-01-01T00:01:00",
        "v:mill_motor_power_kw": "1",
    }
    assert timeline["ticks"][2] == {
        "stamp": "2026-01-01T00:02:00",
        "v:mill_motor_power_kw": "2",
    }
    # the runtime clock reads the stamp anchor, and each frame advances before applying
    script = _script(document)
    assert 't.stamp?String(t.stamp)' in script
    assert "otIndex++;otApply(otTicks[otIndex]);otClockText();otProgress();" in script


def test_simulated_live_a_movable_state_yields_patches_from_the_renderers(
    state: DashboardState, settings: DashboardSettings
) -> None:
    """The timeline is built by re-rendering the moving views per tick: the stub provider's
    fixed values mean no anchored value changes, so the diff is honest — the tick-0 frame ships
    whole and later ticks stay empty, never fabricated."""
    timeline = playback.build_timeline(
        app._PresentationRequest(state),
        render_view=lambda s, v: app.build_view_section(s, v, settings=settings),
        settings=settings,
    )
    assert timeline is not None
    assert timeline["ticks"] and "stamp" in timeline["ticks"][0]
    for tick in timeline["ticks"][1:]:
        assert tick == {}, "a fixed-value provider must not produce fabricated patches"


def test_simulated_live_a_state_that_cannot_move_is_honest(
    state: DashboardState, settings: DashboardSettings
) -> None:
    """With no advanceable provider the shell embeds ``OT_TIMELINE=null`` and the controls still
    render — the clock stays on the opening timestamp, never pretending to run. (The timeline
    builder is injected into the shell, so a None-returning builder reproduces the stub case
    without another state class.)"""
    html, _ = ot_shell.build_ot_document(
        app._PresentationRequest(state),
        settings=settings,
        render_view=lambda s, v: app.build_view_section(s, v, settings=settings),
        build_timeline=lambda *a, **k: None,
    )
    assert "var OT_TIMELINE=null;" in html
    assert 'data-role="playback-bar"' in html
    assert 'data-role="playback-clock"' in html


# =============================================================================
# Honesty — the one global disclosure, honest playback label, no per-panel repetition
# =============================================================================
def test_honesty_the_exact_global_disclosure_ships_twice(document: str) -> None:
    """The directive's exact disclosure wording (EN and FA) in the header and the footer."""
    for text in (ot_shell.DEMO_DISCLOSURE_EN, ot_shell.DEMO_DISCLOSURE_FA):
        assert document.count(theme.html(text)) == 2, f"disclosure must ship once per language: {text[:40]}"


def test_honesty_the_playback_label_is_the_mandated_pair(document: str) -> None:
    assert theme.html(ot_shell.PLAYBACK_LABEL_EN) in document
    assert theme.html(ot_shell.PLAYBACK_LABEL_FA) in document
    # bare "LIVE" / "REAL-TIME" claims are forbidden — only the simulated forms may appear
    for forbidden in ('>LIVE<', '"LIVE"', ">Real-time<", 'alt="REAL-TIME"'):
        assert forbidden not in document, f"forbidden live claim: {forbidden!r}"
    assert "REAL-TIME" not in document


def test_honesty_the_per_panel_synthetic_labels_are_gone(document: str) -> None:
    """The repetitive per-screen badges are removed: the simulated/not-validated wording now
    lives once per document (the shell's header badges and the global disclosure), not once per
    screen. The "Synthetic Demonstration" words that remain are PRD 29's mandatory per-KPI-card
    labels inside the presentation overlay plus the one header badge — pinned by their own
    tests. The standing per-view no-plant-connection banner stays (PRD-verbatim)."""
    assert theme.html(labels.SIMULATED_RESULT_LABEL) not in document
    assert document.count(theme.html(labels.NOT_VALIDATED_LABEL)) == 1  # the header badge
    presentation = document.split('<section class="ot-tabpanel" data-tab="presentation"', 1)[1]
    presentation = presentation.split('<section class="ot-tabpanel"', 1)[0]
    outside = document.replace(presentation, "")
    # outside the presentation overlay: the one header badge plus the twins' (B/E) own
    # ``dt-twin__meta`` badges — the source-flag labels their own tests pin — and nothing else
    assert outside.count(theme.html(labels.SYNTHETIC_DEMONSTRATION_LABEL)) == 3
    assert outside.count('dt-twin__meta"><span class="dt-badge') == 2
    assert document.count(theme.html(labels.NO_PLANT_CONNECTION_STATEMENT)) >= 5


def test_honesty_the_disclosure_is_in_the_presentation_landing_tab(document: str) -> None:
    """The landing tab's how-to names the three mandated steps in both languages."""
    script = _script(document)
    assert 'otShowTab("presentation")' in script  # presentation is the landing tab
    guide = document.split('<section class="ot-tabpanel" data-tab="guide"', 1)[1]
    guide = guide.split('<section class="ot-tabpanel"', 1)[0]
    # the three mandated steps, bilingual: language, playback, tabs
    for needle in (
        "Select the language", "زبان را",  # step 1
        "Start the simulated playback", "پخش شبیه‌سازی‌شده",  # step 2
        "Explore the views with the tabs", "زبانه‌های بالا",  # step 3
    ):
        assert theme.html(needle) in guide, f"how-to step missing: {needle}"


# =============================================================================
# Self-contained — opens from the filesystem with a double click
# =============================================================================
def test_self_contained_no_external_reference(document: str) -> None:
    external = {
        uri for uri in re.findall(r"https?://[^\"'\s<>)]+", document) if uri != SVG_NAMESPACE
    }
    assert not external, f"document references external assets: {sorted(external)}"
    for forbidden in ("<link", "<img", "@import", "<script src"):
        assert forbidden not in document, f"external asset marker present: {forbidden!r}"
    # every url(...) a stylesheet or SVG carries must be a fragment reference (url(#…)), never a
    # fetched file — url(#dt-glow-grad) is the twins' own embedded gradient
    fetched = [u for u in re.findall(r"url\(([^)]*)\)", document) if not u.strip().startswith("#")]
    assert not fetched, f"stylesheets reference fetched assets: {fetched}"
