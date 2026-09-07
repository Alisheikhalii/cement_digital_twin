"""Centralized display-layer localization: English / Persian (Executive Demo / UX wave).

This module is the ONE place a renderer asks for a Persian display label. It exists so the
Executive Demo / UX wave's bilingual rule is enforceable the same way :mod:`src.labels`
enforces the mandated honesty strings and :mod:`src.visualization.theme` enforces the design
tokens: a renderer composes :func:`bi` pairs and dictionary lookups and never writes a
Persian literal of its own, so a missing translation is a visible English fallback rather
than a silently untranslated screen.

Scope, stated honestly:

* **Display only.** The dictionaries map *canonical English display text* to Persian. They
  never rename a canonical technical identifier: ``mill_motor_power_kw``,
  ``kiln_feed_rate_tph``, ``burning_zone_temperature`` and every other tag keep their exact
  spelling everywhere (data structures, payloads, tests, source code) and remain visible as
  a *secondary* technical reference under the tag — ``شناسه فنی: mill_motor_power_kw``
  (:func:`tag_ref`), wrapped in ``<bdi>`` so the Latin identifier is never corrupted by
  bidi reordering.
* **CSS-state bilingualism.** :func:`bi` emits an English and a Persian element pair
  (``.dt-en`` / ``.dt-fa``). Which one is visible is pure CSS on ``<html dir>`` — the rules
  live in :func:`src.visualization.theme.stylesheet` so every document that includes the
  theme (standalone per-view exports and the OT Platform shell alike) gets the same switch
  with English the default in a document that declares no direction.
* **Fallback, never a blank.** An English string without a Persian entry renders in English
  in both modes (:func:`title_bi`). Payload-verbatim wording — the PRD honesty statements
  of :mod:`src.labels`, the what-if engine's own notes, Model C's own messages — is
  deliberately NOT translated here: it is the frozen layer's own voice, and re-wording it
  in translation would be a second judgement this presentation layer must not make.

The Persian is written as natural process-engineering prose (not machine translation),
following the cement-process vocabulary the wave glossary settled: کوره دوار (rotary kiln),
پیش‌گرم‌کننده (preheater), پیش‌کلسینر (precalciner), کلینکر (clinker), آسیای سیمان
(cement mill), جداکنندهٔ دینامیک (dynamic separator), نرمی بلین (Blaine fineness), باقیماندهٔ
الک (sieve residue), انرژی ویژه (specific energy).
"""

from __future__ import annotations

from typing import Final, Mapping

from src import labels
from src.digital_twin.provenance import Provenance, Status, Value
from src.visualization import theme

#: The language-pair classes, imported from :mod:`src.visualization.theme` — the stylesheet
#: is their single authority (see ``theme.LANG_EN_CLASS`` / ``theme.LANG_FA_CLASS``).
EN_CLASS: Final = theme.LANG_EN_CLASS
FA_CLASS: Final = theme.LANG_FA_CLASS


def bi(en: str, fa: str, *, tag: str = "span") -> str:
    """One string in both languages: an English and a Persian element pair.

    Both are always present in the document; which is visible is CSS state on ``<html dir>``.
    The Persian element carries ``dir="rtl" lang="fa"`` so Persian renders right-to-left
    correctly even inside a table the shell pins to ``dir="ltr"`` (the wave's allowance:
    controlled LTR structure, Persian labels RTL within it). ``tag`` lets an SVG caller emit
    the same pair as ``<tspan>`` elements (SVG text has no ``span``).
    """
    return (
        f'<{tag} class="{EN_CLASS}" dir="ltr">{theme.html(en)}</{tag}>'
        f'<{tag} class="{FA_CLASS}" dir="rtl" lang="fa">{theme.html(fa)}</{tag}>'
    )


# =============================================================================
# Playback anchor keys — the shared convention the renderers emit and the
# timeline extractor reads, in one place so the two can never drift apart.
# =============================================================================
def value_key(tag: str) -> str:
    """The anchor key of one tag's formatted reading (plain text, patched by ``textContent``)."""
    return f"v:{tag}"


def status_key(tag: str) -> str:
    """The anchor key of one tag's status pill (bilingual text + pill class)."""
    return f"s:{tag}"


def equipment_state_key(name: str) -> str:
    """The anchor key of one equipment unit's state word (bilingual text + pill class)."""
    return f"e:{name}"


def equipment_health_key(name: str) -> str:
    """The anchor key of one equipment unit's health figure (plain text)."""
    return f"h:{name}"


def stage_state_key(name: str) -> str:
    """The anchor key of one overview stage's state word (bilingual text + pill class)."""
    return f"g:{name}"


def prediction_value_key(target: str, minutes: int) -> str:
    """The anchor key of one forecast cell's number (plain text)."""
    return f"p:{target}:{int(minutes)}"


def prediction_spread_key(target: str, minutes: int) -> str:
    """The anchor key of one forecast cell's ensemble spread (plain text)."""
    return f"u:{target}:{int(minutes)}"


def anomaly_status_key() -> str:
    """The anchor key of Model B's verdict pill (bilingual text + pill class)."""
    return "an:status"


def anomaly_score_key() -> str:
    """The anchor key of Model B's anomaly score figure (plain text)."""
    return "an:score"


def anomaly_detail_key() -> str:
    """The anchor key of the one-line anomaly account (plain text)."""
    return "an:detail"


STAMP_KEY: Final = "stamp"
"""The anchor key of every visible simulation timestamp (plain text, one entry patches all)."""


# =============================================================================
# Status and equipment-state words (the payload's own words, translated)
# =============================================================================
#: :class:`Status` -> Persian. The English side is the enum's own word, so the pill shows the
#: payload's verdict, never a renderer's paraphrase of it.
STATUS_FA: Final[Mapping[str, str]] = {
    "OK": "نرمال",
    "NORMAL": "نرمال",
    "WARNING": "هشدار",
    "ALARM": "آلارم",
    "NO_LIMIT": "بدون حد",
    "UNKNOWN": "نامشخص",
}

#: Equipment-state words (``labels.EQUIPMENT_*``) -> Persian.
STATE_FA: Final[Mapping[str, str]] = {
    labels.EQUIPMENT_RUNNING: "در حال کار",
    labels.EQUIPMENT_IDLE: "خاموش",
    labels.EQUIPMENT_DERATED: "با ظرفیت کاهش‌یافته",
    labels.EQUIPMENT_UNKNOWN: "نامشخص",
}


def status_bi(status: object, *, tag: str = "span") -> str:
    """One :class:`Status` (or its word) as a bilingual pill label."""
    word = str(status)
    return bi(word, STATUS_FA.get(word, word), tag=tag)


def state_bi(state: object, *, tag: str = "span") -> str:
    """One equipment-state word as a bilingual label."""
    word = str(state)
    return bi(word, STATE_FA.get(word, word), tag=tag)


# =============================================================================
# Canonical tag -> Persian display label (the schema description, translated)
# =============================================================================
#: The tags the panels display, keyed by their canonical identifier. Every entry is the
#: Persian rendering of the tag's own :mod:`src.schema` description — the number, unit and
#: meaning are untouched; only the words are Persian. The two daily-total tags have no schema
#: row (their descriptions live in :mod:`src.digital_twin.layout`), so they are translated
#: here from that wording.
TAG_FA: Final[Mapping[str, str]] = {
    # -- kiln dataset ---------------------------------------------------------------------
    "kiln_feed_rate_tph": "خوراک مواد خام به سامانهٔ کوره",
    "kiln_fuel_rate_tph": "نرخ سوخت مشعل اصلی کوره",
    "calciner_fuel_rate_tph": "نرخ سوخت پیش‌کلسینر",
    "kiln_speed_rpm": "سرعت دوران کوره",
    "raw_meal_moisture": "رطوبت باقیماندهٔ مواد خام",
    "raw_meal_temperature": "دمای خوراک مواد خام",
    "primary_air_flow": "دبی هوای اولیهٔ مشعل اصلی",
    "secondary_air_flow": "دبی هوای ثانویه از کولر",
    "tertiary_air_flow": "دبی هوای ثالث به پیش‌کلسینر",
    "ID_fan_speed": "سرعت فن دودکش (ID)",
    "ID_fan_power": "توان موتور فن دودکش",
    "ID_fan_current": "جریان موتور فن دودکش",
    "kiln_inlet_pressure": "فشار درافت ورودی کوره",
    "preheater_pressure": "فشار برج پیش‌گرم‌کننده",
    "exhaust_gas_flow": "دبی گاز خروجی دودکش / پیش‌گرم‌کننده",
    "burning_zone_temperature": "دمای ناحیهٔ احتراق (پیرامتر / مدل)",
    "kiln_inlet_temperature": "دمای مواد در ورودی کوره",
    "calciner_temperature": "دمای خروجی پیش‌کلسینر",
    "preheater_outlet_temperature": "دمای خروجی سیکلون طبقهٔ بالا",
    "secondary_air_temperature": "دمای هوای ثانویه (بازیابی‌شده از کولر)",
    "cooler_outlet_temperature": "دمای تخلیهٔ کلینکر از کولر",
    "oxygen_percent": "اکسیژن ورودی / انتهای کوره (خشک)",
    "CO_ppm": "CO ورودی / انتهای کوره",
    "CO2_percent": "CO2 ورودی / انتهای کوره",
    "NOx_ppm": "NOx (تبدیل‌شده از mg/Nm3)",
    "SO2_ppm": "SO2 دودکش",
    "clinker_production_tph": "نرخ تولید کلینکر",
    "clinker_temperature": "دمای تخلیهٔ کلینکر",
    "thermal_energy_kcal_per_kg_clinker": "انرژی حرارتی ویژه",
    "specific_fuel_consumption": "مصرف سوخت ویژه",
    "kiln_motor_current": "جریان درایو اصلی کوره",
    "cooler_fan_power": "توان کل فن‌های کولر",
    "vibration": "ارتعاش درایو / تکیه‌گاه کوره",
    "bearing_temperature": "دمای بلبرینگ غلتک تکیه‌گاه کوره",
    # -- mill dataset ----------------------------------------------------------------------
    "mill_feed_rate_tph": "خوراک کل آسیا",
    "clinker_feed_rate": "سهم کلینکر از خوراک",
    "gypsum_feed_rate": "سهم گچ از خوراک",
    "additive_feed_rate": "سهم افزودنی / سنگ آهک",
    "mill_motor_power_kw": "توان موتور اصلی آسیا",
    "mill_current": "جریان موتور اصلی آسیا",
    "mill_pressure": "فشار داخلی آسیا (VRM)",
    "mill_differential_pressure": "اختلاف فشار آسیا (شاخص بار)",
    "mill_outlet_temperature": "دمای خروجی مواد / گاز",
    "mill_vibration": "ارتعاش بدنهٔ آسیا",
    "mill_speed": "سرعت دوران / میز آسیا",
    "separator_speed_rpm": "سرعت روتور جداکنندهٔ دینامیک",
    "separator_current": "جریان موتور جداکننده",
    "separator_pressure": "فشار ورودی / خروجی جداکننده",
    "fan_speed": "سرعت فن اصلی / گردشی",
    "fan_power_kw": "توان فن اصلی",
    "gas_flow": "دبی گاز گردشی",
    "cement_production_tph": "نرخ محصول نهایی",
    "product_temperature": "دمای محصول نهایی",
    "simulated_blaine_cm2_g": "نرمی (سطح ویژهٔ بلین)",
    "residue_percent": "باقیمانده روی الک ۴۵ میکرون",
    "specific_power_consumption_kwh_t": "انرژی الکتریکی ویژه",
    # -- the two directive-item-12 daily totals (layout-owned descriptions) ----------------
    "kiln_thermal_energy_kcal_per_day": "انرژی حرارتی کل کوره در روز",
    "mill_electrical_energy_kwh_per_day": "برق کل آسیای سیمان در روز",
}


def tag_title(value: Value) -> str:
    """A payload ``Value``'s display title in both languages.

    The English side is the payload's own description (the schema wording); the Persian side
    is the dictionary entry for the canonical tag, falling back to the English description
    when a tag has no entry yet — a visible fallback, never a blank and never a renamed tag.
    """
    en = value.description or value.tag
    return bi(en, TAG_FA.get(value.tag, en))


def tag_ref(tag: str) -> str:
    """The secondary technical reference line: the canonical identifier, always intact.

    English mode shows the bare identifier; Persian mode prefixes it ``شناسه فنی:`` ("technical
    identifier"). The identifier itself is wrapped in ``<bdi>`` inside the RTL label so bidi
    reordering can never scramble it — constraint: canonical identifiers are never renamed,
    and in Persian mode they may appear only as this visually secondary reference.
    """
    return (
        f'<span class="{EN_CLASS}" dir="ltr">{theme.html(tag)}</span>'
        f'<span class="{FA_CLASS}" dir="rtl" lang="fa">شناسه فنی: <bdi>{theme.html(tag)}</bdi></span>'
    )


# =============================================================================
# English display titles / UI strings -> Persian
# =============================================================================
#: Canonical English display text (view, panel, section, equipment, stage and UI strings the
#: renderers own) -> Persian. Keyed by the exact English string the payload or renderer
#: carries, so a lookup never has to know where a title came from. An entry that is missing
#: renders in English (see :func:`title_bi`) — the honest fallback, never a blank.
TITLE_FA: Final[Mapping[str, str]] = {
    # -- the ten view titles + the PRD 29 overlay -----------------------------------------
    "Plant Overview": "نمای کلی کارخانه",
    "Kiln Digital Twin": "همزاد دیجیتال کوره",
    "Preheater & Kiln": "پیش‌گرم‌کننده و کوره",
    "Clinker Cooler": "کولر کلینکر",
    "Cement Mill Digital Twin": "همزاد دیجیتال آسیای سیمان",
    "Mill & Separator": "آسیا و جداکننده",
    "Energy Monitoring": "پایش انرژی",
    "AI Prediction & Anomaly": "پیش‌بینی و ناهنجاری با هوش مصنوعی",
    "What-If Simulation": "شبیه‌سازی «اگر-آنگاه»",
    "AI Optimization": "بهینه‌سازی هوش مصنوعی",
    "Factory Presentation Mode": "حالت نمایش کارخانه‌ای",
    # -- the ten view subtitles (VIEWS' own wording, translated) ----------------------------
    "Quarry / feed → kiln system → clinker → cement mill → product":
        "معدن / خوراک → سامانهٔ کوره → کلینکر → آسیای سیمان → محصول",
    "Animated process twin — kiln line, driven by simulated state":
        "همزاد فرایندی متحرک — خط کوره، به‌فاصلهٔ وضعیت شبیه‌سازی‌شده",
    "Preheater, precalciner and rotary-kiln detail":
        "جزئیات پیش‌گرم‌کننده، پیش‌کلسینر و کورهٔ دوار",
    "Clinker cooler and fuel / fan system detail":
        "جزئیات کولر کلینکر و سامانهٔ سوخت / فن",
    "Animated process twin — closed grinding circuit":
        "همزاد فرایندی متحرک — مدار خردایش حلقه‌بسته",
    "Mill, dynamic separator, fan / filter and finished product":
        "آسیا، جداکنندهٔ دینامیک، فن / فیلتر و محصول نهایی",
    "Specific energy (per tonne) and total energy (per day), together":
        "انرژی ویژه (بر حسب تن) و انرژی کل (روزانه)، همیشه با هم",
    "Model A multi-horizon forecast and Model B anomaly hypothesis":
        "پیش‌بینی چندافقی مدل A و فرضیهٔ ناهنجاری مدل B",
    "Operator-set changes evaluated by the validated what-if engine":
        "تغییرهای تعیین‌شدهٔ اپراتور، ارزیابی‌شده توسط موتور «اگر-آنگاه» اعتبارسنجی‌شده",
    "Decision support only — the system writes no setpoint":
        "فقط پشتیبان تصمیم — این سامانه هیچ نقطهٔ تنظیمی می‌نویسد",
    # -- panels / sections ------------------------------------------------------------------
    "Kiln process indicators": "شاخص‌های فرایندی کوره",
    "Kiln emissions": "گازهای خروجی کوره",
    "Mill process indicators": "شاخص‌های فرایندی آسیا",
    "Specific energy (per tonne)": "انرژی ویژه (بر حسب تن)",
    "Total energy (per day)": "انرژی کل (روزانه)",
    "Production": "تولید",
    "Kiln": "کوره",
    "Cement mill": "آسیای سیمان",
    "Plant": "کارخانه",
    "Components": "تجهیزات",
    "Process readouts": "قرائت‌های فرایندی",
    "KPIs": "شاخص‌های کلیدی",
    "Plant overview chain": "زنجیرهٔ نمای کلی کارخانه",
    "Plant KPIs": "شاخص‌های کلیدی کارخانه",
    "AI & anomaly status": "وضعیت هوش مصنوعی و ناهنجاری",
    "AI status": "وضعیت هوش مصنوعی",
    "Anomaly status": "وضعیت ناهنجاری",
    "Model A prediction": "پیش‌بینی مدل A",
    "Anomaly detection": "تشخیص ناهنجاری",
    "Specific energy vs total energy": "انرژی ویژه در برابر انرژی کل",
    # -- equipment titles (PRD 8.3) ----------------------------------------------------------
    "Preheater tower": "برج پیش‌گرم‌کننده",
    "Precalciner": "پیش‌کلسینر",
    "Rotary kiln": "کوره دوار",
    "Clinker cooler": "کولر کلینکر",
    "Fuel & fan system": "سامانهٔ سوخت و فن",
    "Dynamic separator": "جداکنندهٔ دینامیک",
    "Mill fan & filter": "فن و فیلتر آسیا",
    "Finished cement": "سیمان نهایی",
    # -- overview stages (directive item 3) ---------------------------------------------------
    "Quarry / feed": "معدن / خوراک",
    "Kiln system": "سامانهٔ کوره",
    "Clinker": "کلینکر",
    "Cement product": "محصول سیمان",
    "Raw meal, gypsum and additive entering the modelled plant": (
        "مواد خام، گچ و افزودنی وارد شده به کارخانهٔ مدل‌شده"
    ),
    "Preheater, precalciner, rotary kiln and clinker cooler": (
        "پیش‌گرم‌کننده، پیش‌کلسینر، کورهٔ دوار و کولر کلینکر"
    ),
    "Buffer stock that decouples the two lines (PRD 8.3 ASSUMPTION)": (
        "ذخیرهٔ میانگیری که دو خط را از هم مستقل می‌کند (فرض PRD 8.3)"
    ),
    "Closed grinding circuit with dynamic separator": "مدار خردایش بسته با جداکنندهٔ دینامیک",
    "Finished cement leaving the modelled plant": "سیمان نهایی خارج‌شده از کارخانهٔ مدل‌شده",
    # -- presentation mode (PRD 29) ------------------------------------------------------------
    "Current Plant State": "وضعیت فعلی کارخانه",
    "AI Prediction": "پیش‌بینی هوش مصنوعی",
    "Optimization Opportunity": "فرصت بهینه‌سازی",
    "Recommended Action": "اقدام پیشنهادی",
    "Expected Benefit": "منفعت مورد انتظار",
    "Potential Thermal Energy Saving": "صرفه‌جویی بالقوهٔ انرژی حرارتی",
    "Potential Electrical Energy Saving": "صرفه‌جویی بالقوهٔ انرژی الکتریکی",
    "Production Stability": "پایداری تولید",
    "Quality Stability": "پایداری کیفیت",
    "Anomalies Detected": "ناهنجاری‌های شناسایی‌شده",
    "KPI cards": "کارت‌های شاخص کلیدی",
    "From plant state to expected benefit": "از وضعیت کارخانه تا منفعت مورد انتظار",
    "Thermal energy": "انرژی حرارتی",
    "Electrical energy": "انرژی الکتریکی",
    # -- twin legend / kinds -------------------------------------------------------------------
    "Material": "مواد",
    "Fuel": "سوخت",
    "Air": "هوا",
    "Gas": "گاز",
    "Product": "محصول",
    # -- table headers ----------------------------------------------------------------------------
    "Indicator": "شاخص",
    "Reading": "قرائت",
    "Status": "وضعیت",
    "Target": "متغیر هدف",
    "Current": "مقدار فعلی",
    "Metric": "شاخص",
    "Baseline": "مقدار پایه",
    "Proposed": "پیشنهادی",
    "Scenario": "سناریو",
    "Setpoint": "نقطهٔ تنظیم",
    "Constraint": "قید",
    "State": "وضعیت",
    "Value": "مقدار",
    "Limit": "حد",
    "Detail": "جزئیات",
    "Gate": "گیت",
    "Verdict": "نتیجه",
    "Reason": "دلیل",
    "Variable": "متغیر",
    "Requested": "درخواستی",
    "Simulated": "شبیه‌سازی‌شده",
    "Mode bounds": "محدودهٔ حالت",
    "Step": "گام",
    "Flags": "نشانه‌ها",
    "Settled value": "مقدار مستقر",
    "Unit": "یکا",
    "Tag": "شناسه",
    "Minimum": "حداقل",
    "Maximum": "حداکثر",
    "Max Δ fraction": "حداکثر کسر تغییر",
    "unavailable: this provider carries no slider specifications. No bounds or steps are "
    "shown rather than invented ones.": (
        "در دسترس نیست: این ارائه‌دهنده مشخصهٔ اسلایدر ندارد. به‌جای حدود و گام‌های "
        "ساختگی، هیچ حد یا گامی نمایش داده نمی‌شود."
    ),
    "Bounds, step and the mode's change limit are the engine's own configured numbers; "
    "a request is set in the engine's steps, never in a step of this screen's.": (
        "حدود، گام و سقف تغییرِ حالت، عددهای پیکربندی‌شدهٔ خود موتورند؛ درخواست در گام‌های "
        "خود موتور تنظیم می‌شود، هرگز در گامی از این صفحه."
    ),
    "unavailable: this panel carries no before/after rows. No comparison numbers are "
    "shown rather than substituted ones.": (
        "در دسترس نیست: این پنل ردیف قبل/بعد ندارد. به‌جای اعداد جایگزین، هیچ عدد "
        "مقایسه‌ای نمایش داده نمی‌شود."
    ),
    "unavailable: the panel carries no settled state. No predicted values are shown "
    "rather than substituted ones.": (
        "در دسترس نیست: این پنل وضعیت مستقر ندارد. به‌جای مقادیر جایگزین، هیچ مقدار "
        "پیش‌بینی‌شده‌ای نمایش داده نمی‌شود."
    ),
    "unavailable: this panel carries no constraint or envelope rows. No constraint is "
    "shown as satisfied rather than substituted ones.": (
        "در دسترس نیست: این پنل ردیف قید یا پوشه ندارد. به‌جای اعداد جایگزین، هیچ قیدی "
        "برآورده‌شده نمایش داده نمی‌شود."
    ),
    "Envelope check": "بررسی پوشه",
    "Source": "منبع",
    # -- what-if / optimization section titles ------------------------------------------------------
    "Manipulated variables (PRD 16.1)": "متغیرهای دستکاری (PRD 16.1)",
    "Requested change": "تغییر درخواستی",
    "Predicted response": "پاسخ پیش‌بینی‌شده",
    "Before / after (settled state vs baseline)": "قبل / بعد (وضعیت مستقر در برابر پایه)",
    "Transition (PRD 16.2 — the delay is in the trajectory)": (
        "گذار (PRD 16.2 — تأخیر در خود مسیر دیده می‌شود)"
    ),
    "Constraints & envelope checks": "قیدها و بررسی‌های پوشه",
    "Recommended setpoints": "نقاط تنظیم پیشنهادی",
    "Expected impact": "اثر مورد انتظار",
    "Gates (PRD 14.3, in evaluation order)": "گیت‌ها (PRD 14.3، به ترتیب ارزیابی)",
    "Predicted state by horizon (Model A)": "وضعیت پیش‌بینی‌شده بر حسب افق زمانی (مدل A)",
    "Baseline comparison (PRD 14.5)": "مقایسه با مقدار پایه (PRD 14.5)",
    "Baseline comparison (PRD 14.5, identical process conditions)": (
        "مقایسه با مقدار پایه (PRD 14.5، شرایط فرایندی یکسان)"
    ),
    "Baseline (PRD 14.5)": "مقدار پایه (PRD 14.5)",
    # -- optimization (view J) ------------------------------------------------------------------------
    "Model not available": "مدل در دسترس نیست",
    "No safe recommendation found": "هیچ توصیهٔ ایمنی یافت نشد",
    "candidate(s) evaluated": "نامزد ارزیابی شد،",
    "rejected by the gates. ": "توسط گیت‌ها رد شد. ",
    "The constraints were not relaxed to manufacture a recommendation.": (
        "قیدها برای ساختن یک توصیه ساختگی شل نشدند."
    ),
    "the optimizer ran without building the baseline comparison for this request. "
    "No baseline numbers are shown rather than substituted ones.": (
        "بهینه‌ساز بدون ساختن مقایسهٔ مقدار پایه برای این درخواست اجرا شد. به‌جای اعداد "
        "جایگزین، هیچ عدد پایه‌ای نمایش داده نمی‌شود."
    ),
    "this recommendation carries no Model A horizon predictions. No predicted values "
    "are shown rather than substituted ones.": (
        "این توصیه هیچ پیش‌بینی افق زمانی مدل A ندارد. به‌جای مقادیر جایگزین، هیچ مقدار "
        "پیش‌بینی‌شده‌ای نمایش داده نمی‌شود."
    ),
    "Model A prediction of the recommended operating point — the prediction channel, kept "
    "separate from the observed values of the baseline comparison. The &plusmn; figure is the "
    "model's own ensemble spread (PRD 13.1.1), shown as a spread and never as a percentage.": (
        "پیش‌بینی مدل A برای نقطهٔ بهره‌برداری پیشنهادی — کانال پیش‌بینی، جدا از مقادیر "
        "مشاهده‌شدهٔ مقایسهٔ پایه. عدد &plusmn; پخش خودِ دسته مدل است (PRD 13.1.1) که به‌صورت "
        "پخش نمایش داده می‌شود، هرگز به‌صورت درصد."
    ),
    "Missing rows": "ردیف‌های غایب",
    # -- small renderer-owned words -----------------------------------------------------------------
    "driver": "محرک",
    "health": "سلامت",
    "unavailable": "در دسترس نیست",
    "Anomaly score:": "امتیاز ناهنجاری:",
    "Detected anomaly:": "ناهنجاری شناسایی‌شده:",
    "Affected variables:": "متغیرهای متأثر:",
    "No anomaly detected.": "ناهنجاری شناسایی نشد.",
    "Model version:": "نسخهٔ مدل:",
    "Missing models:": "مدل‌های غایب:",
    "out of distribution": "خارج از توزیع",
    "WARNING": "هشدار",
    "Hold the current setpoints.": "نگه‌داشتن نقاط تنظیم فعلی.",
    "This screen carries no grouped readout panels of its own; every reading it reports "
    "lives in the component cards above.": (
        "این صفحه پنل قرائت گروهی مخصوص خود را ندارد؛ هر قرائتی که گزارش می‌کند در "
        "کارت‌های تجهیزات بالا آمده است."
    ),
    "This screen carries no KPI group of its own.": "این صفحه گروه شاخص کلیدی مخصوص خود را ندارد.",
    "driver unavailable: no driving variable is reported": (
        "محرک در دسترس نیست: هیچ متغیر محرکی گزارش نشده است"
    ),
    "unavailable: this provider reports none of the components this screen focuses on. "
    "No card is invented to fill the space.": (
        "در دسترس نیست: این ارائه‌دهنده هیچ‌یک از تجهیزات مورد تمرکز این صفحه را گزارش "
        "نمی‌کند. هیچ کارتی برای پر کردن این فضا ساخته نمی‌شود."
    ),
    "unavailable: this provider carries no readings for this panel. No value is invented "
    "to fill the space.": (
        "در دسترس نیست: این ارائه‌دهنده قرائتی برای این پنل ندارد. هیچ مقداری برای پر "
        "کردن این فضا ساخته نمی‌شود."
    ),
    "unavailable: this provider carries no KPI group here. No card is invented to fill "
    "the space.": (
        "در دسترس نیست: این ارائه‌دهنده گروه شاخص کلیدی‌ای در اینجا ندارد. هیچ کارتی "
        "برای پر کردن این فضا ساخته نمی‌شود."
    ),
    "unavailable: this provider carries no plant KPI group. No production or energy card "
    "is invented to fill the space.": (
        "در دسترس نیست: این ارائه‌دهنده گروه شاخص کلیدی کارخانه را ندارد. هیچ کارت "
        "تولید یا انرژی‌ای برای پر کردن این فضا ساخته نمی‌شود."
    ),
    "unavailable: this prediction payload carries no forecasts. No predicted values are "
    "shown rather than substituted ones.": (
        "در دسترس نیست: این بارِ پیش‌بینی پیش‌بینی‌ای حمل نمی‌کند. به‌جای مقادیر جایگزین، "
        "هیچ مقدار پیش‌بینی‌شده‌ای نمایش داده نمی‌شود."
    ),
    "Nearest regime signature (similarity match, not a cause): ": (
        "نزدیک‌ترین امضای رژیم (مطابقت شباهت، نه علت): "
    ),
    "unavailable: this provider carries no stage chain.": (
        "در دسترس نیست: این ارائه‌دهنده زنجیرهٔ مراحل را ندارد."
    ),
    "the optimizer was not run or refused every candidate, so there is no recommended "
    "action to predict from.": (
        "بهینه‌ساز اجرا نشد یا همهٔ نامزدها را رد کرد، بنابراین اقدام پیشنهادی‌ای برای "
        "پیش‌بینی بر پایهٔ آن وجود ندارد."
    ),
    "this recommendation carries no horizon predictions.": (
        "این توصیه پیش‌بینی افق زمانی‌ای حمل نمی‌کند."
    ),
    "Synthetic-to-Real Transfer Strategy (PRD §21)": (
        "راهبرد انتقال از مصنوعی به واقعی (PRD §21)"
    ),
    "Every number on this screen is a synthetic demonstration or a simulation estimate, "
    "not a validated real-plant result — the full transfer strategy is Section 21 of the "
    "PRD.": (
        "هر عدد روی این صفحه یک نمایش مصنوعی یا یک برآورد شبیه‌سازی است، نه نتیجهٔ "
        "اعتبارسنجی‌شدهٔ کارخانهٔ واقعی — متن کامل راهبرد انتقال، بخش ۲۱ PRD است."
    ),
    "No model in this system computes a production-stability metric. Rather than invent a "
    "score, this card states the gap; the nearest real quantity (Model A's cross-horizon "
    "spread, view J) is a model spread, not a stability measure.": (
        "هیچ مدلی در این سامانه شاخص پایداری تولید محاسبه نمی‌کند. به‌جای ساختن نمره‌ای "
        "ساختگی، این کارت همین خلأ را بیان می‌کند؛ نزدیک‌ترین کمیت واقعی (پخش بین‌افق "
        "مدل A، نمای J) یک پخش مدل است، نه سنجهٔ پایداری."
    ),
    "No model in this system computes a quality-stability metric. Rather than invent a "
    "score, this card states the gap; quality appears where it is real — as the "
    "recommendation's Blaine / residue impact on view J.": (
        "هیچ مدلی در این سامانه شاخص پایداری کیفیت محاسبه نمی‌کند. به‌جای ساختن نمره‌ای "
        "ساختگی، این کارت همین خلأ را بیان می‌کند؛ کیفیت آن‌جا که واقعی است دیده می‌شود "
        "— یعنی اثر بلین / باقیماندهٔ توصیه در نمای J."
    ),
    "Model B reports one verdict per instant, not a running count — the current verdict "
    "is shown as it was issued; no count is invented.": (
        "مدل B در هر لحظه یک حکم گزارش می‌کند، نه شمارندهٔ تجمعی — حکم فعلی همان‌گونه که "
        "صادر شده نمایش داده می‌شود؛ هیچ شمارشی ساخته نمی‌شود."
    ),
    "One-line summaries of the AI Prediction & Anomaly screen (view H) and the AI "
    "Optimization screen (view J) at this instant — the same payloads those screens "
    "render, not a second computation. The full cards live there.": (
        "خلاصه‌های یک‌خطی از صفحهٔ «پیش‌بینی و ناهنجاری هوش مصنوعی» (نمای H) و صفحهٔ "
        "«بهینه‌سازی هوش مصنوعی» (نمای J) در این لحظه — همان بارهایی که آن صفحه‌ها "
        "نمایش می‌دهند، نه محاسبه‌ای دوباره. کارت‌های کامل آنجا هستند."
    ),
    "unavailable: this component carries no readout of its own. No reading is invented "
    "to fill the space.": (
        "در دسترس نیست: این تجهیزات قرائت مخصوص خود را ندارد. هیچ قرائتی برای پر کردن "
        "این فضا ساخته نمی‌شود."
    ),
    "Model unavailable": "مدل در دسترس نیست",
    "no trained Model A for this target at this horizon": (
        "مدل A آموزش‌دیده‌ای برای این متغیر هدف در این افق زمانی وجود ندارد"
    ),
    "not carried in this prediction payload": "در این بارِ پیش‌بینی حمل نمی‌شود",
    "Model A forecasts": "مدل A پیش‌بینی می‌کند",
    "plant values": "مقدار فرایندی",
    "for the recommended action over": "برای اقدام پیشنهادی در بازهٔ",
    "The full forecast grid is on the AI Prediction & Anomaly and AI Optimization "
    "screens (views H and J).": (
        "جدول کامل پیش‌بینی در صفحه‌های «پیش‌بینی و ناهنجاری هوش مصنوعی» و «بهینه‌سازی "
        "هوش مصنوعی» (نماهای H و J) است."
    ),
}


def title_fa(en: str) -> str | None:
    """The Persian entry for an English display title, or ``None`` when none exists yet."""
    return TITLE_FA.get(en)


def title_bi(en: str, *, tag: str = "span") -> str:
    """One English display title as a bilingual pair — English fallback when unknown.

    Used for payload-provided titles (panel titles, KPI-group titles, equipment titles) whose
    English wording the renderer receives rather than owns. ``tag`` lets an SVG caller emit
    the pair as ``<tspan>`` elements.
    """
    fa = TITLE_FA.get(en)
    if fa is None:
        return theme.html(en)
    return bi(en, fa, tag=tag)


def kpi_group_title(group_title: str) -> str:
    """``"{Kiln|Cement mill|Plant} KPIs"`` — the grouped-KPI heading, bilingual."""
    return bi(
        f"{group_title} KPIs",
        f"شاخص‌های کلیدی {TITLE_FA.get(group_title, group_title)}",
    )


#: KPI-group titles that can appear in the composed empty-KPI sentence, so the Persian side
#: names the group the sentence speaks about. Same membership as the group titles above.
_KPI_GROUP_FA: Final[Mapping[str, str]] = {
    "Kiln": "کوره",
    "Cement mill": "آسیای سیمان",
    "Plant": "کارخانه",
}

#: Panel titles that can appear in the composed empty-panel sentence, so the Persian side
#: names the panel the sentence speaks about. The process view's grouped panels are a fixed
#: set (its own three, view D's none), so this is dictionary-keyed.
_PANEL_TITLE_FA: Final[Mapping[str, str]] = {
    "Kiln process indicators": "شاخص‌های فرایندی کوره",
    "Kiln emissions": "انتشارهای کوره",
    "Mill process indicators": "شاخص‌های فرایندی آسیا",
}


def kpi_group_empty_bi(group_title: str) -> str:
    """The composed "unavailable: this provider carries no {group} KPI group" sentence, bilingual.

    The process view's KPI-group card names its own group (the payload's title), so the absence
    sentence is composed rather than dictionary-keyed — this helper keeps that composition (and
    its Persian) in this module, so the renderer writes no Persian literal of its own.
    """
    fa_group = _KPI_GROUP_FA.get(group_title, group_title)
    return bi(
        f"unavailable: this provider carries no {group_title} KPI group. "
        "No card is invented to fill the space.",
        f"در دسترس نیست: این ارائه‌دهنده گروه شاخص کلیدی {fa_group} را ندارد. "
        "هیچ کارتی برای پر کردن این فضا ساخته نمی‌شود.",
    )


def panel_empty_bi(panel_title: str) -> str:
    """The composed "unavailable: this provider carries no {title} readings" sentence, bilingual.

    The process view's panel card names its own panel (the payload's title), so the absence
    sentence is composed rather than dictionary-keyed — this helper keeps that composition (and
    its Persian) in this module, so the renderer writes no Persian literal of its own.
    """
    fa_title = _PANEL_TITLE_FA.get(panel_title, panel_title)
    return bi(
        f"unavailable: this provider carries no {panel_title} readings. "
        "No value is invented to fill the space.",
        f"در دسترس نیست: این ارائه‌دهنده قرائت‌های {fa_title} را ندارد. "
        "هیچ مقداری برای پر کردن این فضا ساخته نمی‌شود.",
    )


#: Empty-panel subjects (the energy view's three partitions) -> Persian, for the one composed
#: absence sentence a dynamic subject makes unavoidable. Keyed by the exact English subject
#: phrase the renderer passes.
EMPTY_SUBJECT_FA: Final[Mapping[str, str]] = {
    "specific-energy figures": "ارقام انرژی ویژه",
    "daily-total figures": "ارقام مجموع روزانه",
    "production rates": "نرخ‌های تولید",
}


def provider_empty_bi(subject_en: str) -> str:
    """The composed "unavailable: this provider carries no {subject}" sentence, bilingual.

    The energy view's three partitions each name their own absent subject, so the sentence is
    composed rather than dictionary-keyed — this helper keeps that composition (and its
    Persian) in this module, so a renderer still writes no Persian literal of its own.
    """
    fa_subject = EMPTY_SUBJECT_FA.get(subject_en, subject_en)
    return bi(
        f"unavailable: this provider carries no {subject_en}. "
        "No value is invented to fill the space.",
        f"در دسترس نیست: این ارائه‌دهنده {fa_subject} را ندارد. "
        "هیچ مقداری برای پر کردن این فضا ساخته نمی‌شود.",
    )


def prediction_grid_note() -> str:
    """The forecast-grid footnote (the two provenance channels and the ± figure), bilingual.

    The English side names the two channels by their provenance labels so the footnote and the
    badges on screen say the same words; the Persian side describes the same two channels —
    the provenance labels themselves stay English everywhere (they are mandated wording), so
    the Persian sentence names their meaning instead of transliterating them.
    """
    observed = theme.provenance_label(Provenance.OBSERVED)
    prediction = theme.provenance_label(Provenance.PREDICTION)
    observed_badge = (
        f'<span class="dt-badge dt-badge--{theme.provenance_slug(Provenance.OBSERVED)}">'
        f"{theme.html(observed)}</span>"
    )
    return bi(
        f"The <em>Current</em> column is the {observed_badge} value of each target; every "
        f"other column is Model A's forecast of it ({theme.html(prediction)}). The &plusmn; "
        "figure is the model's own ensemble spread (PRD 13.1.1), shown as a spread and never "
        "as a percentage.",
        "ستون «مقدار فعلی» مقدار مشاهده‌شدهٔ هر متغیر هدف است؛ هر ستون دیگر پیش‌بینی مدل A "
        "از همان متغیر است. رقم ± پخش دستهٔ خود مدل (PRD 13.1.1) است که به‌صورت پخش "
        "نمایش داده می‌شود و هرگز به‌صورت درصد نیست.",
    )


__all__ = [
    "EMPTY_SUBJECT_FA",
    "EN_CLASS",
    "FA_CLASS",
    "kpi_group_empty_bi",
    "panel_empty_bi",
    "STAMP_KEY",
    "STATE_FA",
    "STATUS_FA",
    "TAG_FA",
    "TITLE_FA",
    "anomaly_detail_key",
    "anomaly_score_key",
    "anomaly_status_key",
    "bi",
    "equipment_health_key",
    "equipment_state_key",
    "kpi_group_title",
    "prediction_grid_note",
    "prediction_spread_key",
    "prediction_value_key",
    "provider_empty_bi",
    "stage_state_key",
    "state_bi",
    "status_bi",
    "status_key",
    "tag_ref",
    "tag_title",
    "title_bi",
    "title_fa",
    "value_key",
]
