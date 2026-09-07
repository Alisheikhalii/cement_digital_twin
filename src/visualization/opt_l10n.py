"""Display-layer Persian localization of view J's *dynamic* payload text (Final Demo Fix).

The Executive Demo made every *renderer-owned* string bilingual through :mod:`src.visualization.i18n`,
but view J also shows sentences the **frozen layer composed** — the optimizer's envelope reason
("all 4 evaluated PRD 14.3 checks passed in NORMAL mode: …"), the quality gloss and its limiting
factor ("limited by relative_uncertainty_pct"), the spread-ceiling warnings, the four gates' own
reasons, the PRD 14.5 baseline rows' titles and details. Those reached the screen verbatim, so the
Persian side of the AI Optimization panel was English prose. This module translates them **at the
display layer only**:

* **Nothing upstream changes.** ``src/optimization/`` and ``src/labels.py`` are untouched — the
  payloads still carry the frozen layer's exact English wording, and the English side of every
  bilingual pair below is that wording verbatim. Translation happens after the payload is read,
  never inside it.
* **Anchored structure, not global replacement.** The frozen layer composes its sentences from a
  fixed set of f-string shapes; each shape gets one anchored parser that recognises the whole
  sentence and rebuilds it in Persian with the same numbers, tags, statuses and timestamps in
  place. A string that matches no shape and no exact entry renders in English in both modes —
  the visible-fallback discipline :mod:`i18n` already follows, never a blank and never a
  half-guessed rewrite.
* **Canonical identifiers stay canonical.** Technical tokens — ``oxygen_percent``, ``t+30min``,
  ``NORMAL``, gate names, thresholds, list reprs — are re-emitted wrapped in ``<bdi>`` so the RTL
  Persian line can never reorder them, exactly like :func:`i18n.tag_ref`'s secondary reference.
  The words around them are Persian; the identifiers themselves are never renamed.
* **Composite sentences decompose.** The frozen layer joins sentence parts with ``"; "``; the
  composite parser splits, translates each part through the same anchored shapes, and re-joins
  with the Persian semicolon. Greedy longest-first matching keeps a part that itself contains
  ``"; "`` (the spread-ceiling warning's item list) intact.

The public surface is small: :func:`bi_sentence` (one payload sentence as a bilingual pair, or
escaped English when no translation exists), :func:`fa_html` (the rendered Persian side alone, for
callers that compose around it), and the small word dictionaries the pills and badges read.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from src import labels
from src.visualization import theme

#: One piece of a Persian sentence: either Persian prose (escaped when rendered) or a technical
#: token rendered as ``<bdi>…</bdi>`` so RTL layout cannot reorder it. ``("tok", text)``.
Segment = str | tuple[str, str]

#: Rendered-Persian lookup result: ``None`` means "no translation — show English".
Segments = list[Segment] | None


# =============================================================================
# The word dictionaries the pills, badges and parsers share
# =============================================================================
#: Optimization-mode pill words (canonical values stay in the payload; display is bilingual).
MODE_FA: Final[dict[str, str]] = {
    "NORMAL": "نرمال",
    "EXPERIMENTAL": "آزمایشی",
}

#: Recommendation-quality pill words (HIGH / MEDIUM / LOW are the optimizer's own categories).
QUALITY_FA: Final[dict[str, str]] = {
    "HIGH": "بالا",
    "MEDIUM": "متوسط",
    "LOW": "پایین",
}

#: Envelope-status pill words.
ENVELOPE_FA: Final[dict[str, str]] = {
    "WITHIN_ENVELOPE": "درون پوشه",
    "OUTSIDE_ENVELOPE": "بیرون از پوشه",
}

#: Gate-verdict pill words (the gates table's state column). ``REJECT`` is not a frozen-layer
#: state word (the vocabulary is PASS / FAIL / NOT_EVALUATED / BORDERLINE) but the display layer
#: accepts it so a payload that spells it that way still shows a Persian pill word.
GATE_STATE_FA: Final[dict[str, str]] = {
    "PASS": "تأیید",
    "FAIL": "رد",
    "REJECT": "رد",
    "REJECTED": "رد",
    "NOT_EVALUATED": "ارزیابی‌نشده",
    "BORDERLINE": "مرزی",
}

#: "blocking" — the marker a gate that stops the run carries in front of its state.
BLOCKING_FA: Final = "مسدودکننده"

#: The four PRD 14.3 check names (canonical identifiers; Persian display names).
CHECK_FA: Final[dict[str, str]] = {
    "operating_range": "محدودهٔ عملیاتی",
    "feature_space_ood": "فضای ویژگی (OOD)",
    "hard_constraints": "قیود سخت",
    "max_change": "حداکثر تغییر",
}

#: The per-check verdict words as the envelope reason spells them (lower case).
CHECK_STATE_FA: Final[dict[str, str]] = {
    "pass": "تأیید شد",
    "fail": "رد شد",
    "borderline": "مرزی",
    "not evaluated": "ارزیابی‌نشده",
}

#: The four PRD 13.1.1 quality-factor names (``src.models.quality`` keys).
FACTOR_FA: Final[dict[str, str]] = {
    "relative_uncertainty_pct": "درصد پخش نسبی",
    "model_disagreement_pct": "درصد اختلاف خانواده‌های مدل",
    "constraint_margin": "حاشیهٔ قید",
    "ood_score_ratio": "نسبت نمرهٔ OOD",
}


# =============================================================================
# Exact-sentence dictionary — the frozen layer's fixed-wording statements
# =============================================================================
#: Fixed sentences (no interpolated payload value) keyed by their exact English wording. Any
#: sentence the frozen layer spells the same way every time lives here rather than in a parser.
#: Interpolated shapes get the anchored parsers below.
EXACT_FA: Final[dict[str, str]] = {
    # -- mandated labels / honesty statements ------------------------------------------------
    labels.AI_RECOMMENDATION_LABEL: "پیشنهاد هوش مصنوعی",
    labels.NO_SAFE_RECOMMENDATION: "هیچ توصیهٔ ایمنی یافت نشد",
    labels.SIMULATED_SAVING_CAVEAT: (
        "صرفه‌جویی شبیه‌سازی‌شدهٔ یک مدل مصنوعی — نه یک صرفه‌جویی تضمین‌شدهٔ واقعی."
    ),
    labels.OUTSIDE_ENVELOPE_BANNER: "بیرون از پوشهٔ بهره‌برداری کالیبره‌شده — پایایی کم.",
    labels.NO_PLANT_CONNECTION_STATEMENT: (
        "این داشبورد یک شبیه‌سازی مصنوعی را می‌خواند. به هیچ کارخانه‌ای متصل نیست، هیچ ابزار "
        "دقیق کارخانه را نمی‌خواند و هیچ نقطهٔ تنظیمی نمی‌نویسد: هر پیشنهاد، پشتیبان تصمیم "
        "برای اپراتور انسانی است."
    ),
    labels.MODEL_UNAVAILABLE_STATEMENT: (
        "این پنل به مدلی آموزش‌دیده نیاز دارد که در این نشست موجود نیست. ابتدا لایهٔ مدل را "
        "آموزش دهید — پنل به‌جای عدد جایگزین، هیچ عددی نشان نمی‌دهد."
    ),
    # -- the three mandated quality glosses (src.labels RECOMMENDATION_QUALITY_DESCRIPTION) --
    labels.RECOMMENDATION_QUALITY_DESCRIPTION["HIGH"]: (
        "پخش تنگ دستهٔ مدل، هم‌نظری نزدیک میان خانواده‌های مدل، حاشیهٔ آسان تا همهٔ قیدهای "
        "سخت، و کاملاً درون توزیع آموزش."
    ),
    labels.RECOMMENDATION_QUALITY_DESCRIPTION["MEDIUM"]: (
        "پخش متوسط دستهٔ مدل، برخی اختلاف میان خانواده‌های مدل، یا حاشیهٔ تنگ تا یک قید سخت "
        "/ لبهٔ توزیع آموزش."
    ),
    labels.RECOMMENDATION_QUALITY_DESCRIPTION["LOW"]: (
        "پخش وسیع دستهٔ مدل، خانواده‌های مدلِ ناهم‌نظر، حاشیهٔ قید بسیار تنگ، یا نقطهٔ "
        "بهره‌برداری دور از توزیع آموزش."
    ),
    # -- PRD 14.5 baseline titles and sources -------------------------------------------------
    "Current Operating Point": "نقطهٔ بهره‌برداری فعلی",
    "Historical Baseline": "مقدار پایهٔ تاریخی",
    "Best Comparable Historical Condition": "بهترین شرایط تاریخی قابل‌مقایسه",
    "Digital Twin Baseline (rule engine)": "مقدار پایهٔ همزاد دیجیتال (موتور قواعد)",
    "AI-Optimized Operating Point": "نقطهٔ بهره‌برداری بهینه‌شده با هوش مصنوعی",
    "observable_sensor_value": "ارزش حسگری مشاهده‌شده",
    "twin_simulation": "شبیه‌سازی همزاد",
    # -- fixed baseline details ---------------------------------------------------------------
    "Measured operating point at the time of the request.": (
        "نقطهٔ بهره‌برداری اندازه‌گیری‌شده در لحظهٔ درخواست."
    ),
    "Twin steady state of the PRD 14.6 rule engine's suggested setpoints.": (
        "وضعیت مستقرِ همزاد برای نقاط تنظیم پیشنهادیِ موتور قواعد PRD 14.6."
    ),
    "No historian rows available for the trailing window.": (
        "هیچ ردیف تاریخی‌ای برای پنجرهٔ اخیر در دسترس نیست."
    ),
    "No historian rows to search for a comparable condition.": (
        "هیچ ردیف تاریخی‌ای برای یافتن شرایط قابل‌مقایسه وجود ندارد."
    ),
    "The rule engine produced no state to settle.": (
        "موتور قواعد وضعیتی برای مستقرشدن تولید نکرد."
    ),
    "No safe recommendation was produced, so there is no AI-optimized point to show.": (
        "هیچ توصیهٔ ایمنی تولید نشد، بنابراین نقطهٔ بهینه‌شده با هوش مصنوعی برای نمایش وجود "
        "ندارد."
    ),
    # -- the rule engine's hold suggestion (PRD 15, fixed wording) ----------------------------
    "Suggested action (rule-based suggestion, not a diagnosis): no rule threshold is exceeded; "
    "hold the current setpoints.": (
        "اقدام پیشنهادی (پیشنهاد قاعده‌محور، نه تشخیص): هیچ آستانهٔ قاعده‌ای نقض نشده است؛ "
        "نقاط تنظیم فعلی نگه داشته شوند."
    ),
    # -- gates' fixed-wording reasons ----------------------------------------------------------
    "no Model B report was supplied, so anomaly state could not be checked; with no Model B the "
    "PRD 14.3 feature-space check is unevaluated too, which already prevents any candidate from "
    "reaching a full PASS": (
        "هیچ گزارش مدل B ارائه نشده بود، بنابراین وضعیت ناهنجاری قابل بررسی نبود؛ بدون مدل "
        "B، بررسی فضای ویژگی PRD 14.3 نیز ارزیابی‌نشده می‌ماند و همین به‌تنهایی مانع رسیدن "
        "هر نامزد به تأیید کامل است"
    ),
    "no Model A horizon model is available for any dataset with decision variables, so no "
    "candidate's predicted response could be reported - a recommendation without a prediction is "
    "not a recommendation this platform makes": (
        "هیچ مدل افقیِ مدل A برای مجموعه‌داده‌ای با متغیر تصمیم در دسترس نیست، بنابراین پاسخ "
        "پیش‌بینی‌شدهٔ هیچ نامزدی قابل گزارش نبود — توصیه‌ای بدون پیش‌بینی، توصیه‌ای نیست که "
        "این سامانه بدهد"
    ),
    "not evaluated - the search produced no candidate to predict for": (
        "ارزیابی‌نشده — جستجو نامزدی برای پیش‌بینی تولید نکرد"
    ),
    "Model A produced no prediction for the recommended candidate, so its uncertainty could not "
    "be checked and the candidate cannot be presented as safe": (
        "مدل A برای نامزد پیشنهادی پیش‌بینی‌ای تولید نکرد، بنابراین عدم‌قطعیت آن قابل بررسی "
        "نبود و نامزد نمی‌تواند ایمن ارائه شود"
    ),
    # -- the PRD 14.3 checks' fixed-wording reasons --------------------------------------------
    "no evaluated tag has a recorded training range - cannot be verified": (
        "هیچ برچسب ارزیابی‌شده‌ای محدودهٔ آموزش ثبت‌شده ندارد — قابل بررسی نیست"
    ),
    "Model B is unavailable or unfitted - feature-space novelty cannot be verified": (
        "مدل B در دسترس نیست یا برازش نشده — نو‌آوری فضای ویژگی قابل بررسی نیست"
    ),
    "no feature vector supplied for the proposed state": (
        "بردار ویژگی برای وضعیت پیشنهادی ارائه نشده است"
    ),
    "no simulated state supplied for the proposed action": (
        "وضعیت شبیه‌سازی‌شده برای اقدام پیشنهادی ارائه نشده است"
    ),
    "not evaluated - an earlier PRD 14.3 check already rejected this candidate": (
        "ارزیابی‌نشده — بررسی زودترِ PRD 14.3 همین نامزد را رد کرده بود"
    ),
    # -- the renderer's own missing-cell texts (kept bilingual through this module) -----------
    "unavailable": "در دسترس نیست",
    "no trained Model A for this target at this horizon": (
        "مدل A آموزش‌دیده‌ای برای این متغیر هدف در این افق زمانی وجود ندارد"
    ),
    "not carried in this recommendation's payload": (
        "در بارِ این توصیه حمل نمی‌شود"
    ),
}


# =============================================================================
# Anchored parsers — one per composed sentence shape the frozen layer emits
# =============================================================================
def _tok(text: str) -> Segment:
    """A technical token: canonical identifier, number, list repr — rendered inside ``<bdi>``."""
    return ("tok", text)


#: The envelope all-pass sentence — ``EnvelopeReport.reason()`` with no notable checks.
_RE_ENVELOPE_ALL = re.compile(
    r"^all (\d+) evaluated PRD 14\.3 checks passed in ([A-Z_]+) mode: (.+)$"
)


def _p_envelope_all(en: str) -> Segments:
    match = _RE_ENVELOPE_ALL.match(en)
    if match is None:
        return None
    count, mode, tail = match.groups()
    pairs: list[str] = []
    for item in tail.split("; "):
        name, _, state = item.partition(" ")
        if name not in CHECK_FA:
            return None  # an unrecognized check name: the sentence stays English
        pairs.append(f"{CHECK_FA[name]} {CHECK_STATE_FA.get(state, state)}")
    return [
        f"همهٔ {count} بررسی PRD 14.3 در حالت ",
        _tok(mode),
        " تأیید شد: ",
        "؛ ".join(pairs),
    ]


#: One notable check — ``EnvelopeReport.reason()`` with a failure or borderline check.
_RE_ENVELOPE_NOTABLE = re.compile(r"^check (\d+) \((\w+)\): (.+)$", re.DOTALL)


def _p_envelope_notable(en: str) -> Segments:
    match = _RE_ENVELOPE_NOTABLE.match(en)
    if match is None:
        return None
    number, name, inner = match.groups()
    if name not in CHECK_FA:
        return None
    inner_segments = _direct(inner)
    if inner_segments is None:
        return None  # the check's own reason is not translatable: keep the whole line English
    return [f"بررسی {number} (", CHECK_FA[name], "): "] + inner_segments


#: The quality reason's limiting factor — ``_quality_reason`` in the optimizer.
_RE_LIMITED_BY = re.compile(r"^limited by ([a-z_]+)$")


def _p_limited_by(en: str) -> Segments:
    match = _RE_LIMITED_BY.match(en)
    if match is None:
        return None
    factor = match.group(1)
    if factor not in FACTOR_FA:
        return None
    return ["محدودشده توسط ", FACTOR_FA[factor]]


#: The unassessed-factor shapes — ``_quality_reason`` in the optimizer.
_RE_CAPPED = re.compile(r"^capped because \[(.+?)\] could not be assessed$")
_RE_UNASSESSED = re.compile(r"^unassessed factors: \[(.+?)\]$")


def _factor_list(text: str) -> list[str] | None:
    """A Python-list repr of factor names, each translated — or ``None`` if any is unknown."""
    names = [name.strip().strip("'\"") for name in text.split(", ")]
    translated = [FACTOR_FA.get(name) for name in names]
    if None in translated:
        return None
    return [str(item) for item in translated]


def _p_capped(en: str) -> Segments:
    match = _RE_CAPPED.match(en)
    if match is None:
        return None
    factors = _factor_list(match.group(1))
    if factors is None:
        return None
    return ["محدودشده چون ", "، ".join(factors), " قابل ارزیابی نبود"]


def _p_unassessed(en: str) -> Segments:
    match = _RE_UNASSESSED.match(en)
    if match is None:
        return None
    factors = _factor_list(match.group(1))
    if factors is None:
        return None
    return ["عوامل ارزیابی‌نشده: ", "، ".join(factors)]


#: A spread-item list — ``{target} t+{h}min {pct} %`` entries the frozen layer joins with "; ".
_SPREAD_ITEM = re.compile(r"^[\w.]+ t\+\d+min [-\d.]+ %$")


def _spread_items(text: str) -> list[Segment] | None:
    """The reported-only / wide-spread item list, each entry one LTR ``<bdi>`` token."""
    items = text.split("; ")
    if not all(_SPREAD_ITEM.match(item) for item in items):
        return None
    joined: list[Segment] = []
    for index, item in enumerate(items):
        if index:
            joined.append("؛ ")
        joined.append(_tok(item))
    return joined


#: The reported-only warning — ``_quality_reason`` in the optimizer.
_RE_REPORTED_ONLY = re.compile(
    r"^reported-only predictions above the ([\d.]+) % spread ceiling \((.+)\) "
    r"- shown, not hidden, and not claimed as an improvement$"
)


def _p_reported_only(en: str) -> Segments:
    match = _RE_REPORTED_ONLY.match(en)
    if match is None:
        return None
    ceiling, items_text = match.groups()
    items = _spread_items(items_text)
    if items is None:
        return None
    return (
        ["پیش‌بینی‌های صرفاً گزارش‌شده فراتر از سقف پخش ", _tok(ceiling), " ٪ ("]
        + items
        + [") — نمایش داده می‌شوند، نه پنهان؛ و به‌عنوان بهبود ادعا نمی‌شوند"]
    )


#: The anomaly gate's pass sentence, with its optional non-blocking-flag tail.
_RE_ANOMALY_PASS = re.compile(
    r"^all (\d+) Model B report\(s\) are NORMAL"
    r"(; \[(.*?)\] carry a non-blocking Isolation-Forest flag, reported not hidden)?$"
)


def _p_anomaly_pass(en: str) -> Segments:
    match = _RE_ANOMALY_PASS.match(en)
    if match is None:
        return None
    count, _sep, noted = match.groups()
    segments = ["همهٔ ", count, " گزارش مدل B نرمال‌اند"]
    if noted:
        segments += ["؛ ", _tok(noted), " پرچم غیرمسدودکنندهٔ جنگل جداسازی دارند که گزارش شده، نه پنهان"]
    return segments


#: The anomaly gate's fail sentence — an active anomaly blocks the run.
_RE_ANOMALY_FAIL = re.compile(
    r"^Model B reports an active anomaly \((.+)\); an optimization suggestion laid on top of an "
    r"unexplained anomaly would be advice about a plant the models no longer describe$"
)


def _p_anomaly_fail(en: str) -> Segments:
    match = _RE_ANOMALY_FAIL.match(en)
    if match is None:
        return None
    return (
        ["مدل B ناهنجاری فعال گزارش می‌کند (", _tok(match.group(1)), ")؛ پیشنهاد بهینه‌سازی روی "
         "ناهنجاری توضیح‌داده‌نشده، توصیه‌ای دربارهٔ کارخانه‌ای است که مدل‌ها دیگر آن را "
         "توصیف نمی‌کنند"]
    )


#: The model-availability gate's pass and frozen-dataset shapes.
_RE_AVAILABILITY_PASS = re.compile(
    r"^Model A is available for every dataset with decision variables (.+)$"
)
_RE_AVAILABILITY_FROZEN = re.compile(
    r"^Model A is available for (\[.*?\]); (\[.*?\]) has no trained model, so its variables are "
    r"frozen rather than optimized blind$"
)


def _p_availability_pass(en: str) -> Segments:
    match = _RE_AVAILABILITY_PASS.match(en)
    if match is None:
        return None
    return ["مدل A برای هر مجموعه‌داده با متغیرهای تصمیم ", _tok(match.group(1)), " در دسترس است"]


def _p_availability_frozen(en: str) -> Segments:
    match = _RE_AVAILABILITY_FROZEN.match(en)
    if match is None:
        return None
    allowed, frozen = match.groups()
    return (
        ["مدل A برای ", _tok(allowed), " در دسترس است؛ ", _tok(frozen), " مدل آموزش‌دیده "
         "ندارد، بنابراین متغیرهایش منجمد می‌مانند نه کورکورانه بهینه"]
    )


#: The envelope gate — the winner's own PRD 14.3 verdict, or the no-winner refusal.
_RE_ENV_GATE_WINNER = re.compile(
    r"^the recommended candidate is ([A-Z_]+) / ([A-Z_]+) in ([A-Z]+) mode: (.+)$", re.DOTALL
)
_RE_ENV_GATE_NONE = re.compile(
    r"^no candidate passed the PRD 14\.3 gate; holding the current setpoints is itself "
    r"([A-Z_]+) / ([A-Z_]+) - (.+)$",
    re.DOTALL,
)


def _p_env_gate_winner(en: str) -> Segments:
    match = _RE_ENV_GATE_WINNER.match(en)
    if match is None:
        return None
    status, envelope, mode, inner = match.groups()
    inner_segments = _direct(inner)
    if inner_segments is None:
        return None
    return (
        ["نامزد پیشنهادی ", _tok(f"{status} / {envelope}"), " در حالت ", _tok(mode), " است: "]
        + inner_segments
    )


def _p_env_gate_none(en: str) -> Segments:
    match = _RE_ENV_GATE_NONE.match(en)
    if match is None:
        return None
    status, envelope, inner = match.groups()
    inner_segments = _direct(inner)
    if inner_segments is None:
        return None
    return (
        ["هیچ نامزدی از گیت PRD 14.3 نگذشت؛ نگه‌داشتن نقاط تنظیم فعلی خودش ",
         _tok(f"{status} / {envelope}"), " است — "]
        + inner_segments
    )


#: The uncertainty gate's pass / fail shapes — both share the "worst relative prediction spread"
#: head; the pass form carries the reported-only tail sentence.
_RE_SPREAD_PASS = re.compile(
    r"^worst relative prediction spread ([\d.]+) % on the objective targets (\[.*?\]) is within "
    r"the ([\d.]+) % ceiling for a MEDIUM-quality recommendation\. Reported-only targets above "
    r"the same ceiling \((.+)\) do not block, but they cap the Recommendation Quality and are "
    r"shown with their spread$"
)
_RE_SPREAD_FAIL = re.compile(
    r"^worst relative prediction spread ([\d.]+) % on the objective targets (\[.*?\]) exceeds "
    r"the ([\d.]+) % ceiling that configs/ml\.yaml sets for a MEDIUM-quality recommendation, so "
    r"the claimed improvement is not supported by the prediction it rests on$"
)
_RE_SPREAD_NONE = re.compile(
    r"^Model A returned no uncertainty spread for (\[.*?\]), the targets this objective is "
    r"scored on, so the ceiling could not be applied - an unmeasured uncertainty is not a small "
    r"one$"
)


def _p_spread_pass(en: str) -> Segments:
    match = _RE_SPREAD_PASS.match(en)
    if match is None:
        return None
    worst, targets, ceiling, items_text = match.groups()
    items = _spread_items(items_text)
    if items is None:
        return None
    return (
        ["بدترین پخش نسبی پیش‌بینی ", _tok(worst), " ٪ روی متغیرهای هدف ", _tok(targets),
         " درون سقف ", _tok(ceiling), " ٪ برای توصیهٔ با کیفیت متوسط است. اهدافِ صرفاً "
         "گزارش‌شده فراتر از همان سقف ("]
        + items
        + [") مسدود نمی‌کنند، اما کیفیت توصیه را محدود می‌کنند و با پخش خود نمایش داده "
           "می‌شوند"]
    )


def _p_spread_fail(en: str) -> Segments:
    match = _RE_SPREAD_FAIL.match(en)
    if match is None:
        return None
    worst, targets, ceiling = match.groups()
    return (
        ["بدترین پخش نسبی پیش‌بینی ", _tok(worst), " ٪ روی متغیرهای هدف ", _tok(targets),
         " از سقف ", _tok(ceiling), " ٪ که configs/ml.yaml برای توصیهٔ با کیفیت متوسط تعیین "
         "می‌کند فراتر است، بنابراین بهبودِ ادعاشده توسط پیش‌بینیِ تکیه‌گاهش پشتیبانی نمی‌شود"]
    )


def _p_spread_none(en: str) -> Segments:
    match = _RE_SPREAD_NONE.match(en)
    if match is None:
        return None
    return (
        ["مدل A هیچ پخش عدم‌قطعیتی برای ", _tok(match.group(1)), " — متغیرهای هدفی که این "
         "تابع هدف رویشان امتیاز می‌گیرد — برنگرداند، بنابراین سقف قابل اعمال نبود؛ عدم‌قطعیتِ "
         "اندازه‌گیری‌نشده، کوچک نیست"]
    )


#: The refusal message — ``{NO_SAFE_RECOMMENDATION}: {gate} - {reason}`` per blocking gate.
_RE_REFUSAL_MESSAGE = re.compile(r"^No safe recommendation found: (.+)$", re.DOTALL)


def _p_refusal_message(en: str) -> Segments:
    match = _RE_REFUSAL_MESSAGE.match(en)
    if match is None:
        return None
    rest = match.group(1)
    gate, sep, reason = rest.partition(" - ")
    if not sep:
        return None
    reason_segments = _direct(reason)
    if reason_segments is None:
        return None
    return ["هیچ توصیهٔ ایمنی یافت نشد: ", _tok(gate), " — "] + reason_segments


#: The PRD 14.5 baseline rows' composed details.
_RE_MEAN_REGIME = re.compile(
    r"^Mean of the trailing ([\d.]+) h in regime '(.+?)'; (\d+) rows\.$"
)
_RE_MEAN_PLAIN = re.compile(
    r"^Mean of the trailing ([\d.]+) h"
    r"( \(no rows in that regime, so the window is not regime-filtered\))?"
    r"(?:; (\d+) rows\.)?$"
)
_RE_BEST_COMPARABLE = re.compile(
    r"^Best of (\d+) comparable (\d+) min window\(s\) \(within ([\d.]+) % of ([\d.]+) t/h"
    r"(?:, regime '([^']*)')?\), ranked on lowest ([a-z_]+); window ending (.+?)\.$"
)
_RE_TWIN_RECOMMENDED = re.compile(
    r"^Twin steady state of the recommended setpoints \(([A-Z_]+) / ([A-Z_]+), (\w+) mode, "
    r"quality (\w+)\)\.$"
)


def _p_mean_regime(en: str) -> Segments:
    match = _RE_MEAN_REGIME.match(en)
    if match is None:
        return None
    hours, regime, rows = match.groups()
    return [
        f"میانگین {hours} ساعت اخیر در رژیم ",
        _tok(f"'{regime}'"),
        f"؛ {rows} ردیف.",
    ]


def _p_mean_plain(en: str) -> Segments:
    match = _RE_MEAN_PLAIN.match(en)
    if match is None:
        return None
    hours, unfiltered, rows = match.groups()
    segments = [f"میانگین {hours} ساعت اخیر"]
    if unfiltered:
        segments.append(" (در آن رژیم ردیفی نبود، پس پنجره بر اساس رژیم پالایش نشد)")
    if rows:
        segments.append(f"؛ {rows} ردیف.")
    return segments


def _p_best_comparable(en: str) -> Segments:
    match = _RE_BEST_COMPARABLE.match(en)
    if match is None:
        return None
    count, window, tolerance, target, regime, metric, ending = match.groups()
    segments = [
        f"بهترینِ {count} پنجرهٔ {window} دقیقه‌ای قابل‌مقایسه (در حدود ",
        _tok(f"{tolerance} % of {target} t/h"),
    ]
    if regime is not None:
        segments += ["، رژیم ", _tok(f"'{regime}'")]
    segments += [")، بر پایهٔ کمینهٔ ", _tok(metric), "؛ پنجرهٔ پایان‌یافته در ", _tok(ending), "."]
    return segments


def _p_twin_recommended(en: str) -> Segments:
    match = _RE_TWIN_RECOMMENDED.match(en)
    if match is None:
        return None
    status, envelope, mode, quality = match.groups()
    return [
        "وضعیت مستقرِ همزاد برای نقاط تنظیم پیشنهادی (",
        _tok(f"{status} / {envelope}"),
        "، حالت ",
        _tok(mode),
        "، کیفیت ",
        QUALITY_FA.get(quality, quality),
        ").",
    ]


#: The PRD 14.2 hard-constraint aggregate and per-tag reasons.
_RE_CONSTRAINTS_OK = re.compile(
    r"^all (\d+) hard constraints satisfied( \(worst normalized margin (-?[\d.]+)\))?$"
)
_RE_CONSTRAINT_TAG_OK = re.compile(r"^(\w+) = ([-\d.,]+) within (.+)$")
_RE_CONSTRAINT_TAG_MISSING = re.compile(
    r"^(\w+): not available in the evaluated state - cannot be verified$"
)


def _p_constraints_ok(en: str) -> Segments:
    match = _RE_CONSTRAINTS_OK.match(en)
    if match is None:
        return None
    count, _sep, margin = match.groups()
    segments = [f"همهٔ {count} قید سخت برآورده شدند"]
    if margin is not None:
        segments.append(f" (بدترین حاشیهٔ نرمال‌شده {margin})")
    return segments


def _p_constraint_tag_ok(en: str) -> Segments:
    match = _RE_CONSTRAINT_TAG_OK.match(en)
    if match is None:
        return None
    tag, value, band = match.groups()
    return ["مقدار ", _tok(tag), " برابر ", _tok(value), " درون ", _tok(band), " است"]


def _p_constraint_tag_missing(en: str) -> Segments:
    match = _RE_CONSTRAINT_TAG_MISSING.match(en)
    if match is None:
        return None
    return [_tok(match.group(1)), " در وضعیت ارزیابی‌شده موجود نیست — قابل بررسی نیست"]


#: The PRD 14.3 checks' composed reasons (per-dataset scores, per-tag ranges, per-move limits).
_RE_RANGE_OUTSIDE = re.compile(r"^(\w+) = ([-\d.,e+]+) outside training range (\[.*\])$")
_RE_RANGE_ALL_INSIDE = re.compile(
    r"^all (\d+) tags with a recorded training range are inside it$"
)
_RE_IForest = re.compile(
    r"^(\w+) Isolation Forest score ([-\d.e+]+) is (below the|between the|inside the) "
    r"(.*?)( \(ood_ratio ([\d.]+)\))$"
)
_RE_MAX_CHANGE_FAIL = re.compile(
    r"^(\w+) moves ([-\d.]+) % of its current value, beyond the ([\d.]+) % (\w+) limit$"
)
_RE_MAX_CHANGE_PASS = re.compile(
    r"^largest setpoint move is ([\d.]+) % of its current value, within the ([\d.]+) % (\w+) "
    r"limit$"
)


def _p_range_outside(en: str) -> Segments:
    match = _RE_RANGE_OUTSIDE.match(en)
    if match is None:
        return None
    tag, value, bounds = match.groups()
    return ["مقدار ", _tok(tag), " برابر ", _tok(value), " بیرون از محدودهٔ آموزش ", _tok(bounds), " است"]


def _p_range_all_inside(en: str) -> Segments:
    match = _RE_RANGE_ALL_INSIDE.match(en)
    if match is None:
        return None
    return [f"همهٔ {match.group(1)} برچسبِ دارای محدودهٔ آموزش ثبت‌شده درون آن هستند"]


def _p_iforest(en: str) -> Segments:
    match = _RE_IForest.match(en)
    if match is None:
        return None
    dataset, score, relation, thresholds, _sep, ratio = match.groups()
    relation_fa = {"below the": "پایین‌تر از", "between the": "بین", "inside the": "درون"}[relation]
    return [
        "نمرهٔ جنگل جداسازی ",
        _tok(dataset),
        " برابر ",
        _tok(score),
        " ",
        relation_fa,
        " ",
        _tok(thresholds),
        " است",
        f" (ood_ratio {ratio})",
    ]


def _p_max_change_fail(en: str) -> Segments:
    match = _RE_MAX_CHANGE_FAIL.match(en)
    if match is None:
        return None
    name, pct, limit, mode = match.groups()
    return [
        _tok(name),
        f" با {pct} % از مقدار فعلی‌اش حرکت می‌کند، فراتر از حد {limit} % حالت ",
        _tok(mode),
    ]


def _p_max_change_pass(en: str) -> Segments:
    match = _RE_MAX_CHANGE_PASS.match(en)
    if match is None:
        return None
    pct, limit, mode = match.groups()
    return [
        f"بزرگ‌ترین حرکت نقطهٔ تنظیم {pct} % از مقدار فعلی است، درون حد {limit} % حالت ",
        _tok(mode),
    ]


#: The rule engine's moves line — ``{label}: {variable} {cur} -> {prop} (+x %) because {condition}``.
_RE_RULE_MOVE = re.compile(
    r"^(?:(Suggested action \(rule-based suggestion, not a diagnosis\)): )?"
    r"(\w+) ([-\d.]+) -> ([-\d.]+) \(([-\d.+]+) %\) because (.+)$"
)


def _p_rule_move(en: str) -> Segments:
    match = _RE_RULE_MOVE.match(en)
    if match is None:
        return None
    label, variable, current, proposed, step, condition = match.groups()
    segments: list[Segment] = []
    if label:
        segments.append("اقدام پیشنهادی (پیشنهاد قاعده‌محور، نه تشخیص): ")
    segments += [
        _tok(f"{variable} {current} -> {proposed} ({step} %)"),
        " چون ",
        _tok(condition),
    ]
    return segments


#: Every anchored parser, tried in order. Composite "; "-decomposition runs only after all of
#: these fail, so a sentence whose parts contain "; " (the spread warnings) matches whole first.
_PARSERS: Final[tuple[Callable[[str], Segments], ...]] = (
    _p_envelope_all,
    _p_envelope_notable,
    _p_limited_by,
    _p_capped,
    _p_unassessed,
    _p_reported_only,
    _p_anomaly_pass,
    _p_anomaly_fail,
    _p_availability_pass,
    _p_availability_frozen,
    _p_env_gate_winner,
    _p_env_gate_none,
    _p_spread_pass,
    _p_spread_fail,
    _p_spread_none,
    _p_refusal_message,
    _p_mean_regime,
    _p_mean_plain,
    _p_best_comparable,
    _p_twin_recommended,
    _p_constraints_ok,
    _p_constraint_tag_ok,
    _p_constraint_tag_missing,
    _p_range_outside,
    _p_range_all_inside,
    _p_iforest,
    _p_max_change_fail,
    _p_max_change_pass,
    _p_rule_move,
)


def _direct(en: str) -> Segments:
    """Exact dictionary, then the anchored parsers — no composite decomposition."""
    exact = EXACT_FA.get(en)
    if exact is not None:
        return [exact]
    for parser in _PARSERS:
        segments = parser(en)
        if segments is not None:
            return segments
    return None


def _composite(en: str) -> Segments:
    """A ``"; "``-joined composite of independently translatable parts.

    The frozen layer builds ``quality_reason`` and the refusal reasons by joining whole sentences
    with ``"; "`` — and some of those sentences themselves contain ``"; "`` (the spread item
    lists). Greedy longest-first matching over the split parts keeps such a sentence intact:
    the join of every remaining part is tried before any shorter prefix, and only a join that
    translates as a whole is consumed.
    """
    if "; " not in en:
        return None
    parts = en.split("; ")
    chunks: list[list[Segment]] = []
    index = 0
    while index < len(parts):
        matched = False
        for end in range(len(parts), index, -1):
            candidate = "; ".join(parts[index:end])
            segments = _direct(candidate)
            if segments is not None:
                chunks.append(segments)
                index = end
                matched = True
                break
        if not matched:
            return None
    merged: list[Segment] = []
    for position, chunk in enumerate(chunks):
        if position:
            merged.append("؛ ")
        merged.extend(chunk)
    return merged


def fa_segments(en: str) -> Segments:
    """The Persian rendering of one payload sentence, as prose/token segments — or ``None``."""
    if not en:
        return None
    direct = _direct(en)
    if direct is not None:
        return direct
    return _composite(en)


# =============================================================================
# Rendering — segments to HTML, and the bilingual pair the renderers emit
# =============================================================================
def _fa_html(segments: list[Segment]) -> str:
    """Persian segments as HTML: prose escaped, technical tokens isolated in ``<bdi>``."""
    rendered = []
    for segment in segments:
        if isinstance(segment, tuple):
            rendered.append(f"<bdi>{theme.html(segment[1])}</bdi>")
        else:
            rendered.append(theme.html(segment))
    return "".join(rendered)


def fa_html(en: str) -> str | None:
    """The rendered Persian side alone — for callers that compose a sentence around it."""
    segments = fa_segments(en)
    return None if segments is None else _fa_html(segments)


def bi_sentence(en: str) -> str:
    """One payload-verbatim sentence as a bilingual pair — English fallback when untranslatable.

    The English side is the frozen layer's own wording, escaped, unchanged. The Persian side is
    the anchored translation with every canonical identifier, status word, number and timestamp
    re-emitted inside ``<bdi>``. A sentence no shape recognises renders in English in both modes
    — the honest fallback, never a guess.
    """
    segments = fa_segments(en)
    if segments is None:
        return theme.html(en)
    return (
        f'<span class="{theme.LANG_EN_CLASS}" dir="ltr">{theme.html(en)}</span>'
        f'<span class="{theme.LANG_FA_CLASS}" dir="rtl" lang="fa">{_fa_html(segments)}</span>'
    )


__all__ = [
    "BLOCKING_FA",
    "CHECK_FA",
    "ENVELOPE_FA",
    "EXACT_FA",
    "GATE_STATE_FA",
    "MODE_FA",
    "QUALITY_FA",
    "bi_sentence",
    "fa_html",
    "fa_segments",
]
