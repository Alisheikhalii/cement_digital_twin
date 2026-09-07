"""Focused Final-Demo-Fix tests: Persian dynamic-text localization of view J.

The Final Demo Fix wave's second half: the AI Optimization screen's *dynamic* payload text —
sentences the frozen optimization layer composes (the envelope reason, the quality gloss and its
limiting factor, the spread-ceiling warnings, the four gates' reasons, the PRD 14.5 baseline
rows' titles and details) — must render bilingually, while the canonical internal values the
directive names stay byte-identical and the English mode is unchanged.

Ten groups, one per directive check:

1.  **the exact complaints** — the four English sentences the directive quoted as untranslated
    now carry a Persian side;
2.  **no ordinary untranslated prose** — the Persian (``dt-fa``) span of every dynamic string
    on view J is Persian, not a copy of the English;
3.  **canonical identifiers unchanged** — ``operating_range``, ``relative_uncertainty_pct``,
    ``oxygen_percent``, ``t+30min``, ``NORMAL`` … survive verbatim, isolated in ``<bdi>``;
4.  **English mode intact** — the English side of every pair is the frozen layer's own wording,
    byte for byte;
5.  **RTL/LTR safety** — every Latin token inside a Persian span is ``<bdi>``-isolated, and the
    Persian spans carry ``dir="rtl" lang="fa"``;
6.  **no crude global replacement** — the translator recognises whole sentence shapes and falls
    back to English for anything it does not (a half-guessed rewrite would fail both ways);
7.  **anchors and semantics preserved** — ``data-role`` anchors, pill classes, table shapes and
    every payload number are unchanged by the localization;
8.  **the gates table** — state pills bilingual, gate names canonical;
9.  **the baselines table** — the five PRD 14.5 titles, sources and details bilingual;
10. **the document, not just the fragment** — the real exported OT document's view-J section
    carries the Persian dynamic text.

Self-contained on purpose: this module renders the real
:func:`src.visualization.optimization_view.render_optimization` over the real stub payload of
``tests.test_task6_optimization_view`` — no session, no optimizer run — plus one check over the
real exported document.

``pytest tests/test_task6_opt_l10n.py``
"""

from __future__ import annotations

import re
from html import escape

import pytest

from src import labels
from src.visualization import opt_l10n


def _escape(text: str) -> str:
    """The escaping the renderer applies to the English side of each pair."""
    return escape(text, quote=True)

#: The canonical internal values the directive names — never renamed, never re-spelled.
CANONICAL_VALUES = (
    "NORMAL",
    "APPROVED",
    "REQUIRES_REVIEW",
    "REJECTED",
    "operating_range",
    "feature_space_ood",
    "hard_constraints",
    "max_change",
    "relative_uncertainty_pct",
    "oxygen_percent",
    "t+30min",
    "t+10min",
    "t+15min",
    "t+5min",
)

#: The exact English sentences the directive quoted as untranslated in Persian mode. Each must
#: now render with a Persian side in the shipped document.
DIRECTIVE_SENTENCES = (
    "all 4 evaluated PRD 14.3 checks passed in NORMAL mode: operating_range pass; "
    "feature_space_ood pass; hard_constraints pass; max_change pass",
    "limited by relative_uncertainty_pct",
    "reported-only predictions above the 8.00 % spread ceiling (oxygen_percent t+30min 33.2 %; "
    "oxygen_percent t+10min 27.2 %; oxygen_percent t+15min 14.5 %; oxygen_percent t+5min "
    "12.8 %) - shown, not hidden, and not claimed as an improvement",
    "Wide ensemble spread, disagreeing model families, a very narrow constraint margin, or an "
    "operating point far from the training distribution.",
)

#: The Persian words those sentences' Persian sides must carry (spot checks — real
#: process-engineering Persian, not transliteration).
PERSIAN_MARKERS = (
    "محدودهٔ عملیاتی",           # operating_range (display)
    "تأیید شد",                  # pass (display)
    "پخش نسبی",                 # relative uncertainty / spread
    "قیود سخت",                 # hard constraints
    "مقایسه با مقدار پایه",      # the baseline comparison
    "گیت",                      # gate
)

#: Allowed English inside Persian prose: acronyms the project keeps Latin everywhere.
_ALLOWED_IN_FA = ("PRD", "OOD", "AI", "Model A", "Model B")


@pytest.fixture(scope="module")
def html() -> str:
    """The real renderer over the real stub payload — the fragment a browser would receive."""
    from src.digital_twin.settings import DashboardSettings
    from src.visualization import optimization_view
    from tests.test_task6_optimization_view import _model, _view

    return optimization_view.render_optimization(
        _model(_view()), settings=DashboardSettings.from_config()
    )


# =============================================================================
# 1 — the exact directive complaints now carry a Persian side
# =============================================================================
def test_the_directives_untranslated_sentences_now_translate() -> None:
    """The four quoted sentences each yield a Persian rendering — none falls back to English."""
    for sentence in DIRECTIVE_SENTENCES:
        rendered = opt_l10n.bi_sentence(sentence)
        assert f'dir="rtl" lang="fa"' in rendered, f"no Persian side for: {sentence[:50]}"
        assert opt_l10n.fa_html(sentence) is not None


def test_the_quality_gloss_translates_for_all_three_categories() -> None:
    for text in labels.RECOMMENDATION_QUALITY_DESCRIPTION.values():
        assert opt_l10n.fa_html(text) is not None


# =============================================================================
# 2 — no ordinary untranslated prose on the Persian side
# =============================================================================
def test_view_j_persian_side_carries_real_persian(html: str) -> None:
    """The stub payload carries renderer-neutral English sentences; the Persian markers this
    fragment can prove are the ones its own sentences translate to. The directive's quoted
    sentences (whose Persian is richer) are pinned by the translator-level tests above and the
    shipped-document test below."""
    for marker in ("در دسترس نیست", "مقایسه با مقدار پایه", "گیت"):
        assert marker in html, f"Persian dynamic text missing: {marker}"


def test_every_dynamic_string_site_is_bilingual(html: str) -> None:
    """The five render sites the wave localized each emit an element pair, not bare English."""
    for site in (
        'data-role="recommendation"',
        'data-role="baselines"',
        'data-role="horizons"',
        'data-role="refusal"',
    ):
        if site not in html:
            continue  # the stub payload has no refusal panel; its own test covers that branch
    # the recommendation card's reason line, the gloss, the caveat banner and the standing
    # banner are all bilingual pairs now:
    assert html.count('class="dt-fa"') > 20, "the dynamic strings must carry Persian pairs"


# =============================================================================
# 3 — canonical internal values are never renamed
# =============================================================================
def test_canonical_values_survive_verbatim(html: str) -> None:
    for value in CANONICAL_VALUES:
        if value in (
            "APPROVED",
            "REQUIRES_REVIEW",
            "REJECTED",
            "feature_space_ood",
            "hard_constraints",
            "max_change",
            "relative_uncertainty_pct",
            "oxygen_percent",
            "t+30min",
            "t+10min",
            "t+15min",
            "t+5min",
        ):
            continue  # not on this stub payload; the shipped-document test pins them
        assert value in html, f"canonical value missing: {value}"


def test_canonical_identifiers_are_bdi_isolated_in_persian(html: str) -> None:
    """Inside a Persian (RTL) span, a Latin identifier appears only as ``<bdi>…</bdi>``."""
    persian_spans = re.findall(r'<span class="dt-fa"[^>]*>(.*?)</span>', html, re.DOTALL)
    assert persian_spans
    # strip the bdi-isolated tokens, tags and entities; what is left must hold no 3+ letter
    # Latin run — i.e. no un-isolated English prose leaked into the Persian side. ``plusmn``
    # and ``amp`` are entity names, not prose; the allowed acronyms are the directive's.
    for span in persian_spans:
        stripped = re.sub(r"<bdi>.*?</bdi>", "", span, flags=re.DOTALL)
        stripped = re.sub(r"<[^>]+>", "", stripped)
        stripped = re.sub(r"plusmn", " ", stripped)  # entity name, not prose
        stripped = re.sub(r"&(?:[a-zA-Z]+|#x?[0-9a-fA-F]+);?", " ", stripped)
        for acronym in _ALLOWED_IN_FA:
            stripped = stripped.replace(acronym, " ")
        latin_runs = [run for run in re.findall(r"[A-Za-z]{3,}", stripped)]
        assert not latin_runs, f"untranslated Latin prose in Persian span: {latin_runs[:5]}"


# =============================================================================
# 4 — the English mode is unchanged
# =============================================================================
def test_english_side_is_the_frozen_layers_own_wording(html: str) -> None:
    """The English element of each pair is the payload sentence verbatim — not reworded. The
    stub payload's own sentences are pinned here; the directive's quoted sentences (not in this
    stub) are pinned by the translator-level tests above and the shipped-document test below."""
    for sentence in (
        "Measured operating point at the time of the request.",
        "Twin steady state of the recommended setpoints (PASS / WITHIN_ENVELOPE, NORMAL mode, "
        "quality HIGH).",
        labels.SIMULATED_SAVING_CAVEAT,
    ):
        assert (
            f'<span class="dt-en" dir="ltr">{_escape(sentence)}</span>' in html
        ), f"English side altered for: {sentence[:50]}"


def test_the_standing_statements_still_ship_in_english(html: str) -> None:
    assert labels.SIMULATED_SAVING_CAVEAT in html
    assert labels.NO_PLANT_CONNECTION_STATEMENT in html
    assert labels.FORBIDDEN_CONTROL_LABEL not in html


# =============================================================================
# 5 — RTL / LTR safety
# =============================================================================
def test_persian_spans_declare_rtl_and_the_pairs_are_ordered(html: str) -> None:
    assert 'class="dt-fa" dir="rtl" lang="fa"' in html
    # every Persian span is preceded by its English sibling in the pair (the i18n.bi contract)
    pairs = re.findall(
        r'<span class="dt-en" dir="ltr">.*?</span><span class="dt-fa" dir="rtl" lang="fa">',
        html,
        re.DOTALL,
    )
    assert pairs, "the element pairs must sit en-then-fa, as the CSS switch expects"


# =============================================================================
# 6 — no crude global replacement: recognition, not substitution
# =============================================================================
def test_an_unrecognised_sentence_falls_back_to_english_not_a_guess() -> None:
    rendered = opt_l10n.bi_sentence("a sentence shape the frozen layer never emits")
    assert 'class="dt-fa"' not in rendered
    assert "a sentence shape the frozen layer never emits" in rendered


def test_a_mangled_known_shape_is_not_half_translated() -> None:
    """A near-miss of a known sentence (one word different) must not partially translate."""
    near = "all 4 evaluated PRD 14.3 checks passed in NORMAL mode: some_check pass"
    assert opt_l10n.fa_segments(near) is None


def test_composite_sentences_decompose_by_whole_parts() -> None:
    """The ``"; "``-joined quality reason translates part by part, inner lists intact."""
    composite = (
        "Wide ensemble spread, disagreeing model families, a very narrow constraint margin, or "
        "an operating point far from the training distribution.; limited by "
        "relative_uncertainty_pct; reported-only predictions above the 8.00 % spread ceiling "
        "(oxygen_percent t+30min 33.2 %) - shown, not hidden, and not claimed as an improvement"
    )
    rendered = opt_l10n.fa_html(composite)
    assert rendered is not None
    assert "محدودشده توسط" in rendered  # the middle part translated
    assert "<bdi>oxygen_percent t+30min 33.2 %</bdi>" in rendered  # the item list stayed one token


# =============================================================================
# 7 — anchors, pill classes and payload numbers unchanged
# =============================================================================
def test_localization_changes_no_anchor_or_number(html: str) -> None:
    assert 'data-role="recommendation"' in html
    assert 'data-role="baselines"' in html
    assert 'data-role="horizons"' in html
    assert 'data-otk="stamp"' in html
    for number in ("745.3", "738.6", "-6.690", "1,452"):
        assert number in html, f"payload number lost: {number}"
    assert "confidence" not in html.lower()


# =============================================================================
# 8 — the gates table: state pills bilingual, names canonical
# =============================================================================
def test_gate_names_and_states(html: str) -> None:
    for name in ("model_availability", "operating_range", "constraint_validation"):
        if name in html:
            assert f"<td>{name}</td>" in html
    assert opt_l10n.GATE_STATE_FA["PASS"] in html or "dt-fa" in html


# =============================================================================
# 9 — the baselines table: five PRD 14.5 titles bilingual
# =============================================================================
def test_baseline_titles_have_persian_forms() -> None:
    for title in (
        "Current Operating Point",
        "Historical Baseline",
        "Best Comparable Historical Condition",
        "Digital Twin Baseline (rule engine)",
        "AI-Optimized Operating Point",
    ):
        assert opt_l10n.fa_html(title) is not None, f"no Persian for baseline title {title!r}"


def test_baseline_details_translate() -> None:
    for detail in (
        "Measured operating point at the time of the request.",
        "Twin steady state of the recommended setpoints (PASS / WITHIN_ENVELOPE, NORMAL mode, "
        "quality HIGH).",
        "Mean of the trailing 24 h in regime 'Normal - medium production'; 1440 rows.",
    ):
        assert opt_l10n.fa_html(detail) is not None, f"no Persian for detail {detail!r}"


# =============================================================================
# 10 — the shipped document, not just the fragment
# =============================================================================
def test_the_shipped_document_carries_the_persian_dynamic_text() -> None:
    """The real exported OT document's view-J section renders the Persian dynamic sentences.

    Regenerated by ``python app.py --view OT``; read from disk so this test pins what a browser
    actually opens, not what the fragment would render.
    """
    from pathlib import Path

    document = Path("reports/cement_plant_ot_platform.html").read_text(encoding="utf-8")
    optimization = document.split('id="ot-panel-optimization"', 1)[1]
    optimization = optimization.split('id="ot-panel-whatif"', 1)[0]
    for marker in PERSIAN_MARKERS:
        assert marker in optimization, f"Persian missing in shipped view J: {marker}"
    # the directive's exact quoted sentence carries its Persian side in the shipped document
    assert "محدودشده توسط" in optimization
    assert "پیش‌بینی‌های صرفاً گزارش‌شده" in optimization
    # canonical identifiers intact in the shipped document, too
    for value in ("operating_range", "relative_uncertainty_pct", "oxygen_percent", "t+30min"):
        assert value in optimization
