"""The Cement Plant OT Platform shell — one bilingual, tabbed, management-facing document.

This module is **presentation only**. It reuses, verbatim, the HTML the existing A–J renderers
(and the PRD §29 presentation overlay) already produce: the caller hands in a ``render_view``
callable — :func:`app.build_view_section`, the same shared dispatch :func:`app.build_document`
uses — and every technical panel below is that function's output, embedded unmodified. Nothing
here recomputes a process value, runs a model, scores an anomaly or invents a limit (standing
constraints 3–5); the shell's only job is information architecture: tabs, plain-language
explanations, and a language switch.

User-facing branding (this wave): **Cement Plant OT Platform** —
*AI-assisted monitoring, simulation, prediction & optimization* /
پلتفرم فناوری عملیاتی کارخانه سیمان — پایش، شبیه‌سازی، پیش‌بینی و بهینه‌سازی مبتنی بر هوش
مصنوعی. The branding is display-level only: no Python module, package, class, renderer id,
PRD term or canonical machine identifier is renamed, and the internal "Digital Twin"
terminology the technical layers use is untouched.

Bilingual scope (two levels, deliberately unequal):

* **Level 1 — this shell.** Title, subtitle, tab labels, the System Guide, every tab's
  plain-language explanation, the language selector, the footer and the honesty notes exist in
  English and Persian. The switch is CSS-only state (``<html lang dir>`` plus ``.ot-en`` /
  ``.ot-fa`` visibility rules) driven by a few lines of inline JavaScript — no reload, no
  external file, no framework.
* **Level 2 — the technical panels.** The embedded renderer output stays exactly as the
  existing renderers produced it (English, LTR). The shell states this honestly in both
  languages rather than translating renderer internals — that is a separate future wave. Each
  embedded panel sits in an ``.ot-tech`` block pinned to ``dir="ltr"`` so Persian RTL layout
  cannot reorder a technical table, an SVG or an identifier such as ``kiln_fuel_rate_tph``.

The Alerts / Process Health tab is an **aggregation, never a computation**: it collects what
the current system already says — Model B's anomaly verdict (view A's status tile), Model C's
optimizer headline and refusal reasons (view J's payload), the shared frame's operating regime,
and each screen's standing header notices — and displays each entry with its source. No health
score, no count, no severity ranking is invented; an entry that does not exist in a payload is
omitted, never extrapolated.

Self-contained by construction: the document embeds the theme stylesheet, its own scoped CSS
and its own inline JavaScript, and references no network resource — it opens from the
filesystem with a double click.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Final

from src import labels
from src.visualization import playback, theme

#: What the caller hands in: build one screen's view model and render it. This is
#: :func:`app.build_view_section` (the dispatch :func:`app.build_document` shares), injected so
#: this module never imports the application host and never re-implements the routing.
RenderView = Callable[[Any, str], tuple[Any, str]]

# =============================================================================
# Branding (user-facing display text only — see the module docstring)
# =============================================================================
TITLE_EN: str = "Cement Plant OT Platform"
TITLE_FA: str = "پلتفرم فناوری عملیاتی کارخانه سیمان"
SUBTITLE_EN: str = "AI-assisted monitoring, simulation, prediction & optimization"
SUBTITLE_FA: str = "پایش، شبیه‌سازی، پیش‌بینی و بهینه‌سازی مبتنی بر هوش مصنوعی"

#: The honest statement about the two language levels, in both languages (wave-mandated wording).
#: The wave's localization made every panel bilingual, so the note now states what remains
#: English by design: the canonical technical identifiers, kept intact for traceability.
TECHNICAL_PANELS_NOTE_EN: str = (
    "Technical identifiers (tag names such as mill_motor_power_kw) are kept in their canonical "
    "English form so every value stays traceable to its source; the panels, labels and "
    "descriptions around them are available in English and Persian."
)
TECHNICAL_PANELS_NOTE_FA: str = (
    "شناسه‌های فنی (نام تگ‌هایی مانند mill_motor_power_kw) به شکل استاندارد انگلیسی حفظ "
    "می‌شوند تا هر مقدار به منبع خودش قابل ردیابی بماند؛ پنل‌ها، برچسب‌ها و توضیحات "
    "پیرامون آن‌ها به دو زبان فارسی و انگلیسی در دسترس هستند."
)

#: The one global demo-mode disclosure (the wave's exact mandated wording) — in the header and
#: the footer, replacing the per-panel synthetic labels the renderers used to repeat.
DEMO_DISCLOSURE_EN: str = (
    "Demo Mode — All displayed process data is synthetic and this demo is not connected to a "
    "real plant."
)
DEMO_DISCLOSURE_FA: str = (
    "حالت نمایشی — تمام داده‌های فرایندی این نسخه مصنوعی است و این دمو به کارخانه واقعی "
    "متصل نیست."
)

#: The playback bar's honest label: simulated, never "LIVE"/"REAL-TIME" (the wave's rule).
PLAYBACK_LABEL_EN: str = "SIMULATED LIVE DEMO"
PLAYBACK_LABEL_FA: str = "شبیه‌سازی زنده نمایشی"

# =============================================================================
# Tabs: key -> (English label, Persian label) and key -> (English, Persian) explanation
# =============================================================================
#: The tab architecture this wave's audit settled on. Each row is ``(tab_key, view_ids)``: the
#: renderer screens embedded in that tab, in display order. ``guide`` and ``alerts`` carry no
#: view ids — the guide is shell-only content, and the alerts tab aggregates information from
#: the models the other tabs already built (never a new computation).
TABS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("guide", ()),
    ("overview", ("A",)),
    ("kiln", ("B", "C")),
    ("mill", ("E", "F")),
    ("energy", ("G",)),
    ("prediction", ("H",)),
    ("optimization", ("J",)),
    ("whatif", ("I",)),
    ("alerts", ()),
    ("presentation", ("P",)),
)

TAB_LABELS: dict[str, tuple[str, str]] = {
    "guide": ("System Guide", "راهنمای سامانه"),
    "overview": ("Plant Overview", "نمای کلی کارخانه"),
    "kiln": ("Kiln", "کوره دوار"),
    "mill": ("Cement Mill", "آسیای سیمان"),
    "energy": ("Energy", "انرژی"),
    "prediction": ("AI Prediction", "پیش‌بینی هوش مصنوعی"),
    "optimization": ("AI Optimization", "بهینه‌سازی هوش مصنوعی"),
    "whatif": ("What-if", "تحلیل «اگر-آنگاه»"),
    "alerts": ("Alerts / Health", "هشدارها و سلامت فرآیند"),
    "presentation": ("Presentation", "نمای مدیریتی"),
}

#: One plain-language explanation per tab (2–4 short sentences), for a factory manager who
#: knows cement operations but not AI/ML. English first, Persian second — both rendered, one
#: visible at a time.
TAB_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "overview": (
        "This is the overall operational picture of the simulated plant. It gives a quick view "
        "of the current plant state and helps identify where attention may be needed. Use it as "
        "the starting point before opening the deeper views.",
        "نمای کلی وضعیت بهره‌برداری کارخانهٔ شبیه‌سازی‌شده. این بخش تصویری سریع از وضعیت فعلی "
        "کارخانه به دست می‌دهد و نشان می‌دهد توجه بیشتر کجای خط لازم است. از این بخش به‌عنوان "
        "نقطهٔ شروع، پیش از ورود به نماهای جزئی‌تر، استفاده کنید.",
    ),
    "kiln": (
        "This section shows the simulated kiln condition. The first panel is a visual, animated "
        "representation of the operating state; the second provides more detailed kiln and "
        "preheater process information. Together they help understand temperature, oxygen, fuel "
        "and related operating variables. Values are simulated, not real sensor readings.",
        "این بخش وضعیت شبیه‌سازی‌شدهٔ کوره را نشان می‌دهد. پنل اول بازنمایی بصری و متحرک وضعیت "
        "بهره‌برداری است و پنل دوم اطلاعات فرآیندی دقیق‌تر کوره و پیش‌گرم‌کننده ارائه می‌کند. این "
        "دو با هم درک دما، اکسیژن، سوخت و متغیرهای مرتبط را آسان می‌کنند. مقادیر شبیه‌سازی‌شده‌اند، "
        "نه قرائت سنسور واقعی.",
    ),
    "mill": (
        "This section shows the simulated cement mill condition. The first panel is the visual "
        "mill state; the second provides mill and separator process detail. Together they help "
        "understand operating load, power-related variables and separator behaviour.",
        "این بخش وضعیت شبیه‌سازی‌شدهٔ آسیای سیمان را نشان می‌دهد. پنل اول وضعیت بصری آسیا و پنل "
        "دوم جزئیات فرآیندی آسیا و جداکننده است. این دو با هم درک بار بهره‌برداری، متغیرهای "
        "مرتبط با توان مصرفی و رفتار جداکننده را آسان می‌کنند.",
    ),
    "energy": (
        "This is where the plant's energy-related operating information is shown: specific energy "
        "(per tonne) and total energy (per day), always displayed together. Energy is one of the "
        "largest cost items in cement production, so spotting inefficient operating conditions "
        "matters. All values are simulated; they can help identify where consumption looks "
        "unusual, but no actual energy saving is claimed.",
        "در این بخش اطلاعات بهره‌برداری مرتبط با انرژی کارخانه نمایش داده می‌شود: انرژی ویژه "
        "(بر حسب هر تن) و انرژی کل (روزانه)، همیشه کنار هم. انرژی یکی از بزرگ‌ترین اقلام هزینه "
        "در تولید سیمان است، بنابراین شناسایی شرایط بهره‌برداری ناکارآمد اهمیت دارد. همهٔ "
        "مقادیر شبیه‌سازی‌شده‌اند و می‌توانند نشان دهند مصرف در کجا غیرعادی به نظر می‌رسد، اما "
        "هیچ صرفه‌جویی واقعی ادعا نمی‌شود.",
    ),
    "prediction": (
        "The system uses trained models to estimate selected future process behaviour, and a "
        "separate model flags unusual patterns in the current readings. Predictions are model "
        "outputs, not guaranteed future outcomes, and anomaly indications are hypotheses that "
        "should be reviewed by an operator.",
        "سامانه با مدل‌های آموزش‌دیده رفتار آیندهٔ بخشی از فرآیند را برآورد می‌کند و مدلی "
        "جداگانه الگوهای غیرعادی در قرائت‌های فعلی را شناسایی می‌کند. پیش‌بینی‌ها خروجی مدل "
        "هستند، نه نتایج تضمین‌شدهٔ آینده، و نشانه‌های ناهنجاری فرضیه‌هایی هستند که باید توسط "
        "اپراتور بررسی شوند.",
    ),
    "optimization": (
        "The optimizer evaluates possible operating changes and checks safety and operating "
        "constraints before recommending anything. The recommendation is decision support for a "
        "human operator — the system changes nothing by itself. A rejected recommendation is "
        "also useful: it shows that the constraints prevented the proposed action.",
        "بهینه‌ساز تغییرهای ممکن در بهره‌برداری را ارزیابی می‌کند و پیش از هر پیشنهاد، قیدهای "
        "ایمنی و بهره‌برداری را بررسی می‌کند. پیشنهاد صرفاً پشتیبان تصمیم‌گیری برای اپراتور "
        "انسانی است — سامانه خودش هیچ چیزی را تغییر نمی‌دهد. پیشنهاد ردشده نیز مفید است: نشان "
        "می‌دهد قیدها مانع اجرای آن اقدام شده‌اند.",
    ),
    "whatif": (
        "Here you can explore hypothetical operating changes and see the simulated consequence, "
        "including whether the change stays inside the calibrated operating envelope. NORMAL and "
        "EXPERIMENTAL modes offer different operating envelopes where the system already "
        "supports them. This changes nothing in a real plant.",
        "در این بخش می‌توانید تغییرهای فرضی بهره‌برداری را بررسی کنید و نتیجهٔ شبیه‌سازی‌شدهٔ آن "
        "را ببینید؛ از جمله اینکه آیا تغییر درون پوشهٔ بهره‌برداری کالیبره‌شده باقی می‌ماند یا "
        "خیر. حالت‌های NORMAL و EXPERIMENTAL در جایی که سامانه پشتیبانی می‌کند پوشه‌های "
        "بهره‌برداری متفاوتی دارند. این تحلیل هیچ تغییری در کارخانهٔ واقعی ایجاد نمی‌کند.",
    ),
    "alerts": (
        "These are warnings and notices the current system already generates: the AI anomaly "
        "verdict, the optimizer's status, the active operating regime, and the standing notices "
        "each screen carries. This is an aggregation of existing, traceable information, not a "
        "newly invented plant-wide health score. It helps focus attention; final interpretation "
        "remains with the operator.",
        "این‌ها هشدارها و اعلان‌هایی هستند که سامانهٔ فعلی از قبل تولید می‌کند: حکم ناهنجاری "
        "هوش مصنوعی، وضعیت بهینه‌ساز، رژیم بهره‌برداری فعال و اعلان‌های ثابت هر صفحه. این بخش "
        "یک تجمیع از اطلاعات موجود و قابل ردیابی است، نه یک شاخص سلامت جدید برای کل کارخانه. "
        "به تمرکز توجه کمک می‌کند؛ تفسیر نهایی همچنان با اپراتور است.",
    ),
    "presentation": (
        "This tab embeds the existing Factory Presentation Mode (PRD §29): the management-level "
        "summary that overlays the Plant Overview and AI Optimization screens — the plant state, "
        "the AI recommendation in plain terms, and the expected benefit with its standing "
        "caveat. It is the same view the system already provides; this shell adds no second "
        "AI-status system.",
        "این زبانه، «حالت نمایش مدیریتی» موجود (PRD §29) را در خود جای می‌دهد: خلاصهٔ مدیریتی که "
        "نمای کلی کارخانه و بهینه‌سازی هوش مصنوعی را روی هم می‌آید — وضعیت کارخانه، توصیهٔ هوش "
        "مصنوعی به زبان ساده و منفعت مورد انتظار همراه با تبصرهٔ همیشگی آن. این همان نمای "
        "موجود سامانه است؛ این پوسته هیچ سامانهٔ وضعیت دومِ هوش مصنوعی اضافه نمی‌کند.",
    ),
}

# =============================================================================
# System Guide content — shell-only, bilingual
# =============================================================================
#: Each guide block is ``(heading_en, heading_fa, [(line_en, line_fa), ...])``.
GUIDE_BLOCKS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "What is this platform?",
        "این پلتفرم چیست؟",
        (
            (
                "This is an Operational Technology (OT) oriented decision-support platform for a "
                "cement plant. It monitors simulated kiln and cement-mill operating conditions, "
                "uses trained AI/ML models to estimate selected future process behaviour and to "
                "flag unusual patterns, proposes optimization recommendations, and supports "
                "What-if analysis of hypothetical operating changes. It is intended to help "
                "people understand operating conditions and possible actions — the final "
                "decision always rests with the human operator.",
                "این یک پلتفرم پشتیبان تصمیم‌گیری با رویکرد فناوری عملیاتی (OT) برای کارخانه "
                "سیمان است. این سامانه وضعیت بهره‌برداری شبیه‌سازی‌شدهٔ کوره و آسیای سیمان را "
                "پایش می‌کند، با مدل‌های آموزش‌دیدهٔ هوش مصنوعی رفتار آیندهٔ بخشی از فرآیند را "
                "برآورد می‌کند و الگوهای غیرعادی را شناسایی می‌کند، پیشنهادهایی برای بهینه‌سازی "
                "ارائه می‌دهد و تحلیل «اگر-آنگاه» برای بررسی تغییرات فرضی را ممکن می‌سازد. هدف "
                "آن کمک به درک شرایط بهره‌برداری و گزینه‌های ممکن است؛ تصمیم نهایی همیشه با "
                "اپراتور انسانی است.",
            ),
        ),
    ),
    (
        "Important — what this is not",
        "نکتهٔ مهم — این سامانه چه نیست",
        (
            (
                "This demonstration is based on synthetic (simulated) data.",
                "این نسخه نمایشی بر پایهٔ داده‌های شبیه‌سازی‌شده است.",
            ),
            (
                "It is NOT connected to a real cement factory.",
                "به هیچ کارخانهٔ سیمان واقعی متصل نیست.",
            ),
            (
                "It does NOT read real PLC/DCS/historian data.",
                "دادهٔ PLC/DCS یا مورخ‌دادهٔ (historian) واقعی نمی‌خواند.",
            ),
            (
                "It does NOT send commands to equipment.",
                "هیچ فرمانی به تجهیزات ارسال نمی‌کند.",
            ),
            (
                "It does NOT automatically change setpoints.",
                "نقطهٔ تنظیم (ست‌پوینت) تجهیزات را به‌طور خودکار تغییر نمی‌دهد.",
            ),
            (
                "Recommendations are decision support for a human operator.",
                "پیشنهادها صرفاً پشتیبان تصمیم‌گیری برای اپراتور انسانی هستند.",
            ),
            (
                "This is not a validated production control system.",
                "این سامانه یک سامانهٔ کنترل تولیدیِ اعتبارسنجی‌شده نیست.",
            ),
        ),
    ),
    (
        "Before real operational use",
        "پیش از استفادهٔ بهره‌برداری واقعی",
        (
            (
                "Real deployment requires real historical plant data, process-engineering "
                "validation, plant-specific calibration, OT/IT integration, cybersecurity "
                "review, operator validation, safety validation, and commissioning.",
                "استفادهٔ عملیاتی واقعی نیازمند داده‌های تاریخی واقعی کارخانه، اعتبارسنجی توسط "
                "مهندسی فرآیند، کالیبراسیون مخصوص کارخانه، یکپارچه‌سازی OT/IT، بازبینی "
                "امنیت سایبری، تأیید اپراتور، اعتبارسنجی ایمنی و راه‌اندازی است.",
            ),
        ),
    ),
    (
        "How to use this document",
        "نحوهٔ استفاده از این سند",
        (
            (
                "1. Select the language — English or فارسی — with the selector at the top; the "
                "guidance, panels and labels all switch.",
                "۱. زبان را — انگلیسی یا فارسی — با گزینهٔ بالای صفحه انتخاب کنید؛ راهنما، "
                "پنل‌ها و برچسب‌ها همه تغییر می‌کنند.",
            ),
            (
                "2. The simulated playback starts by itself when the document is opened: the "
                "plant clock, values and status colours advance through a pre-recorded "
                "simulation, loop back to the first minute at the end, and keep going. Speed "
                "can be set to 1x, 2x or 4x; Pause holds; Play resumes; Reset returns to the "
                "first minute and, while playing, immediately continues from there.",
                "۲. پخش شبیه‌سازی‌شده با باز شدن سند به‌طور خودکار آغاز می‌شود: ساعت کارخانه، "
                "مقادیر و رنگ وضعیت‌ها در طول یک شبیه‌سازی از پیش ضبط‌شده پیش می‌روند، در پایان "
                "به دقیقهٔ اول بازمی‌گردند و ادامه می‌یابند. سرعت را می‌توان روی ۱x، ۲x یا ۴x "
                "گذاشت؛ Pause نگه می‌دارد؛ Play ادامه می‌دهد؛ Reset به دقیقهٔ اول برمی‌گردد و "
                "در حالت پخش بلافاصله از همان‌جا ادامه می‌دهد.",
            ),
            (
                "3. Explore the views with the tabs above — from the plant overview to the "
                "AI prediction, optimization and what-if tabs. Each opens with a short "
                "plain-language explanation before the technical panels.",
                "۳. نماهای مختلف را با زبانه‌های بالا کاوش کنید — از نمای کلی کارخانه تا "
                "زبانه‌های پیش‌بینی، بهینه‌سازی و «اگر-آنگاه» هوش مصنوعی. هر زبانه با توضیح "
                "کوتاه و ساده‌ای پیش از پنل‌های فنی آغاز می‌شود.",
            ),
        ),
    ),
)


# =============================================================================
# Small rendering helpers
# =============================================================================
def _bi(en: str, fa: str, *, tag: str = "span") -> str:
    """One shell string in both languages: an ``.ot-en`` and an ``.ot-fa`` element pair.

    Both are always present in the document (so the file itself is bilingual data); which one is
    visible is pure CSS state on ``<html dir>`` — the language switch never re-renders, never
    reloads and never touches the embedded technical panels.
    """
    return (
        f'<{tag} class="ot-en">{theme.html(en)}</{tag}>'
        f'<{tag} class="ot-fa">{theme.html(fa)}</{tag}>'
    )


def _bi_lines(pairs: Sequence[tuple[str, str]], *, tag: str = "li") -> str:
    return "".join(_bi(en, fa, tag=tag) for en, fa in pairs)


#: The anomaly verdict's pill colours — Model B's own level words, mapped the same way the view A
#: tile and the presentation overlay map them. Anything else (the unavailable label included)
#: falls to honest grey.
_STATUS_PILL: dict[str, str] = {"NORMAL": "ok", "WARNING": "warn", "ALARM": "alarm"}


def _pill(text: object, kind: str) -> str:
    return f'<span class="dt-pill dt-pill--{kind}">{theme.html(text)}</span>'


def _badge(text: object) -> str:
    return f'<span class="dt-badge dt-badge--configuration">{theme.html(text)}</span>'


# =============================================================================
# The System Guide tab (shell-only content)
# =============================================================================
def _guide_html() -> str:
    blocks = "".join(
        f'<div class="dt-card"><h3 class="dt-title">{_bi(heading_en, heading_fa)}</h3>'
        + (
            f"<ul>{_bi_lines(lines)}</ul>"
            if len(lines) > 1
            else _bi(lines[0][0], lines[0][1], tag="p")
        )
        + "</div>"
        for heading_en, heading_fa, lines in GUIDE_BLOCKS
    )
    return (
        '<div class="ot-guide">'
        f"{blocks}"
        f'<div class="dt-banner">{_bi(TECHNICAL_PANELS_NOTE_EN, TECHNICAL_PANELS_NOTE_FA, tag="span")}</div>'
        "</div>"
    )


# =============================================================================
# The Alerts / Process Health tab — an aggregation of existing, traceable information
# =============================================================================
#: Why the optimizer card can be the honest headline even when the optimizer refused: the
#: refusal itself is a display state (directive item 16), carried with the blocking gates' own
#: words, never dropped and never softened.
ALERTS_TRACEABILITY_NOTE: str = (
    "Every entry on this tab is copied from an existing payload field of the current system: "
    "view A's anomaly status tile, view J's optimizer payload, the shared frame's operating "
    "regime, and each screen's standing header notices. Nothing here is computed, ranked or "
    "invented, and there is no plant-wide health score."
)


def _anomaly_alert_card(anomaly: Any) -> str:
    """Model B's verdict, in its own words — or its own unavailable reason."""
    if anomaly is None:
        body = '<p class="dt-mono">unavailable</p><p class="dt-muted">view A carried no anomaly status tile in this session.</p>'
        head = _pill("UNKNOWN", "unknown")
    else:
        status = str(getattr(anomaly, "status", ""))
        head = _pill(status, _STATUS_PILL.get(status, "unknown"))
        detail = getattr(anomaly, "detail", "") or ""
        available = bool(getattr(anomaly, "available", False))
        body = (
            f'<p class="dt-mono">{theme.html(status)}</p><p>{theme.html(detail)}</p>'
            if available
            else f'<p class="dt-mono">{theme.html(status)}</p><p class="dt-muted">{theme.html(detail)}</p>'
        )
    return (
        '<div class="dt-card" data-role="alert-card" data-source="view A anomaly status tile">'
        f'<h3 class="dt-title">Anomaly verdict &mdash; Model B</h3><div>{head}</div>{body}</div>'
    )


def _optimizer_alert_card(view: Any) -> str:
    """Model C's own headline and message — refusal reasons included, never dropped."""
    if view is None:
        body = '<p class="dt-mono">unavailable</p><p class="dt-muted">view J carried no optimizer payload in this session.</p>'
        head = _pill("UNKNOWN", "unknown")
    else:
        headline = str(getattr(view, "headline", "") or "")
        refused = bool(getattr(view, "refused", False))
        available = bool(getattr(view, "available", False))
        kind = "unknown" if not available else ("warn" if refused else "ok")
        head = _pill(headline, kind)
        body = f"<p>{theme.html(getattr(view, 'message', '') or headline)}</p>"
        reasons = tuple(getattr(view, "refusal_reasons", ()) or ())
        body += "".join(
            f'<p class="dt-muted">{theme.html(reason)}</p>' for reason in reasons
        )
    return (
        '<div class="dt-card" data-role="alert-card" data-source="view J optimizer payload">'
        f'<h3 class="dt-title">Optimizer status &mdash; Model C</h3><div>{head}</div>{body}</div>'
    )


def _regime_alert_card(regime: Any) -> str:
    """The shared frame's operating regime — the scheduler's own label, and any injected fault."""
    if regime is None:
        body = '<p class="dt-mono">unavailable</p><p class="dt-muted">no regime was carried on this session\'s headers.</p>'
    else:
        label = str(getattr(regime, "label", "") or "")
        fault = getattr(regime, "injected_fault", None)
        body = f'<p class="dt-mono">{theme.html(label)}</p>'
        if fault:
            body += f'<p class="dt-muted">Injected fault: {theme.html(fault)}</p>'
    return (
        '<div class="dt-card" data-role="alert-card" data-source="shared frame operating regime">'
        f'<h3 class="dt-title">Operating regime</h3>{body}</div>'
    )


def _notices_alert_card(models: Mapping[str, Any]) -> str:
    """Every screen's standing header notices, each row naming the screen it came from."""
    rows: list[str] = []
    for view_id in ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J"):
        model = models.get(view_id)
        header = getattr(model, "header", None)
        if header is None:
            continue
        notices = tuple(getattr(header, "notices", ()) or ())
        if not notices:
            continue
        title = str(getattr(header, "title", "") or view_id)
        joined = "; ".join(str(notice) for notice in notices)
        rows.append(
            f"<tr><th>{theme.html(view_id)} &mdash; {theme.html(title)}</th>"
            f"<td>{theme.html(joined)}</td></tr>"
        )
    table = (
        '<table class="dt-table">'
        + "".join(rows)
        + "</table>"
        if rows
        else '<p class="dt-muted">No screen carried a standing notice in this session.</p>'
    )
    return (
        '<div class="dt-card" data-role="alert-card" data-source="screen header notices">'
        '<h3 class="dt-title">Standing notices by screen</h3>'
        f"{table}"
        f'<p class="dt-muted">{theme.html(ALERTS_TRACEABILITY_NOTE)}</p></div>'
    )


def _alerts_html(models: Mapping[str, Any]) -> str:
    """The Alerts tab: four cards, every one a copy of something a payload already said."""
    overview = models.get("A")
    anomaly = getattr(overview, "anomaly_status", None)
    optimization = models.get("J")
    optimizer_view = getattr(optimization, "view", None)
    header = getattr(overview, "header", None)
    if header is None:
        header = getattr(models.get("B"), "header", None)
    regime = getattr(header, "regime", None)
    return (
        '<div class="ot-alerts">'
        f"{_anomaly_alert_card(anomaly)}"
        f"{_optimizer_alert_card(optimizer_view)}"
        f"{_regime_alert_card(regime)}"
        f"{_notices_alert_card(models)}"
        "</div>"
    )


# =============================================================================
# The shell document: scoped CSS, the language switch, tab switching
# =============================================================================
def _shell_style() -> str:
    """The shell's own scoped CSS. Geometry and language state only — colours and type come
    from the theme variables the embedded ``dt-root`` fragments already carry."""
    return (
        "<style>"
        # -- language state: one rule pair does the whole switch --------------------------
        'html[dir="ltr"] .ot-fa{display:none !important;}'
        'html[dir="rtl"] .ot-en{display:none !important;}'
        # -- chrome ------------------------------------------------------------------------
        ".ot-shell{max-width:75rem;margin:0 auto;padding:var(--dt-gap);display:flex;"
        "flex-direction:column;gap:var(--dt-gap);}"
        ".ot-header h1{margin:0 0 .2em;font-size:1.6em;}"
        ".ot-header .ot-subtitle{margin:0 0 .6em;color:var(--dt-text-muted);}"
        ".ot-langbar{display:flex;flex-wrap:wrap;gap:.4em;align-items:center;}"
        ".ot-langbtn,.ot-tabs button{font:inherit;color:var(--dt-text);"
        "background:var(--dt-surface);border:var(--dt-border-width) solid var(--dt-border);"
        "border-radius:var(--dt-radius-sm);padding:.25em .8em;cursor:pointer;}"
        ".ot-langbtn.ot-on,.ot-tabs button.ot-on{border-color:var(--dt-accent);"
        "color:var(--dt-accent);font-weight:600;}"
        # -- tabs: LTR order under ltr, RTL order under rtl (the browser mirrors the flex
        #    row from <html dir> — nothing is hand-reversed) -------------------------------
        ".ot-tabs{display:flex;flex-wrap:wrap;gap:.35em;}"
        ".ot-tabs button:hover{border-color:var(--dt-accent-alt);}"
        # -- panels: visible one at a time once JavaScript is on; with scripting off,
        #    every panel stays visible so no content is unreachable ------------------------
        "body.ot-js .ot-tabpanel{display:none;}"
        "body.ot-js .ot-tabpanel.ot-on{display:block;}"
        ".ot-tabpanel{margin:0;}"
        ".ot-expl{border:var(--dt-border-width) solid var(--dt-border);"
        "border-radius:var(--dt-radius);padding:var(--dt-gap-sm) var(--dt-pad);"
        "background:var(--dt-surface-alt);margin:0 0 var(--dt-gap);max-width:60em;}"
        # -- the technical panels stay LTR and left-aligned whatever the shell direction is,
        #    so RTL never reorders a table, an SVG or an identifier -------------------------
        ".ot-tech{direction:ltr;text-align:left;overflow-x:auto;}"
        ".ot-guide,.ot-alerts{display:flex;flex-direction:column;gap:var(--dt-gap);}"
        ".ot-guide ul,.ot-alerts ul{margin:.2em 0;padding-inline-start:1.4em;}"
        ".ot-badges{display:flex;flex-wrap:wrap;gap:.4em;margin:.4em 0;}"
        # -- the simulated-playback bar (directive item 7): one row, honest label, controls ---
        ".ot-play{display:flex;flex-wrap:wrap;gap:.5em;align-items:center;"
        "border:var(--dt-border-width) solid var(--dt-border);border-radius:var(--dt-radius);"
        "padding:var(--dt-gap-sm) var(--dt-pad);background:var(--dt-surface);margin:0 0 "
        "var(--dt-gap);}"
        ".ot-play .ot-playlabel{font-size:var(--dt-size-label);color:var(--dt-accent);"
        "font-weight:600;}"
        ".ot-play .ot-clock{font-family:var(--dt-font-mono);color:var(--dt-text);"
        "border-inline-start:var(--dt-border-width) solid var(--dt-border);"
        "padding-inline-start:.8em;}"
        ".ot-play .ot-clock .ot-en{color:var(--dt-text-muted);font-size:var(--dt-size-label);}"
        ".ot-play button{font:inherit;color:var(--dt-text);background:var(--dt-surface);"
        "border:var(--dt-border-width) solid var(--dt-border);"
        "border-radius:var(--dt-radius-sm);padding:.25em .9em;cursor:pointer;}"
        ".ot-play button.ot-on{border-color:var(--dt-accent);color:var(--dt-accent);"
        "font-weight:600;}"
        ".ot-play .ot-progress{flex:1 1 8em;height:.4em;border-radius:.2em;"
        "background:var(--dt-surface-alt);overflow:hidden;min-width:6em;}"
        ".ot-play .ot-progress i{display:block;height:100%;width:0;"
        "background:var(--dt-accent);}"
        ".ot-meta{border-collapse:collapse;font-size:var(--dt-size-label);"
        "color:var(--dt-text-muted);direction:ltr;text-align:left;}"
        ".ot-meta th,.ot-meta td{padding:.1em .8em .1em 0;font-weight:400;}"
        ".ot-footer{display:flex;flex-direction:column;gap:.4em;max-width:60em;}"
        ".ot-disclosure{max-width:60em;margin:.2em 0 .2em;}"
        ".ot-disclosure p{margin:0;color:var(--dt-text-muted);font-size:var(--dt-size-label);}"
        "@media (max-width:48rem){.ot-shell{padding:var(--dt-gap-sm);}"
        ".ot-header h1{font-size:1.25em;}}"
        "</style>"
    )


def _js_string(text: str) -> str:
    """One shell string as a JavaScript double-quoted literal.

    Deliberately *not* :func:`theme.html`: an HTML entity inside a JS string would be assigned
    verbatim (``document.title`` would display ``&amp;``), because the browser decodes entities
    when parsing markup, not when a script assigns a string. Only the two characters that can
    break the literal are escaped.
    """
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


#: The beat interval of the playback timer, in milliseconds. One beat advances one sample at
#: 1x — a deliberately unhurried cadence so a presenter can talk over it; 2x/4x halve/quarter
#: the beat rather than multiplying the step, which keeps every tick on the same sample grid.
_PLAYBACK_BEAT_MS: Final[int] = 1500

#: The speeds the playback bar offers (the wave's mandated 1x / 2x / 4x).
_PLAYBACK_SPEEDS: Final[tuple[float, ...]] = (1.0, 2.0, 4.0)


def _playback_bar() -> str:
    """The simulated-playback bar: honest label, transport, clock, speed, progress.

    Present even when no timeline was embedded — with the same controls and a clock that
    stays on the document's opening timestamp. The bar is labelled "SIMULATED LIVE DEMO" /
    "شبیه‌سازی زنده نمایشی" in both languages; the word "live" is never used alone, and the
    playback is never called real-time.
    """
    buttons = "".join(
        f'<button type="button" class="ot-speed{" ot-on" if speed == 1.0 else ""}" '
        f'data-speed="{speed:g}" onclick="otSetSpeed({speed:g})">{speed:g}x</button>'
        for speed in _PLAYBACK_SPEEDS
    )
    return (
        '<div class="ot-play" data-role="playback-bar">'
        f'<span class="ot-playlabel">{_bi(PLAYBACK_LABEL_EN, PLAYBACK_LABEL_FA)}</span>'
        '<button type="button" class="ot-playtoggle" onclick="otTogglePlay()" '
        f'>{_bi("Play", "پخش")}</button>'
        '<button type="button" onclick="otResetPlayback()" '
        f'>{_bi("Reset", "بازنشانی")}</button>'
        f"{buttons}"
        f'<span class="ot-progress"><i data-role="playback-progress"></i></span>'
        f'<span class="ot-clock"><span class="ot-en">sim time:</span>'
        f'<span class="ot-fa">زمان شبیه‌سازی:</span> '
        f'<bdi data-role="playback-clock"></bdi></span>'
        "</div>"
    )


def _shell_script(timeline_json: str) -> str:
    """The whole runtime: a language switch, a tab switch, the simulated playback. No libraries.

    ``otSetLang`` writes ``<html lang>`` and ``<html dir>`` — the same attributes the CSS
    language rules read — so the switch is one attribute write, never a re-render: the embedded
    technical panels are not touched. ``otShowTab`` toggles one ``.ot-on`` class per panel.
    The playback replays the embedded ``OT_TIMELINE`` — the renderers' own output, diffed per
    tick at export time — by patching ``data-otk``-anchored nodes: plain strings replace
    ``textContent``, ``[en, fa, cls]`` triples patch the two language children of a bilingual
    pill and swap its ``dt-pill--*`` class so a status change also changes its colour. No
    ``Math.random``, no network, no library: the same embedded data replays identically every
    time. The ``body.ot-js`` class is added only by this script, so with scripting disabled
    every panel remains visible and the document degrades to one long, complete page.

    The executive demo's transport contract: playback **starts on its own** the moment the
    document opens, and when the final tick is reached it wraps to tick 0 and keeps going —
    an unattended loop a presenter never has to drive. ``otPlaying`` doubles as the autoplay
    state: it is on from load, stays on across the wrap, and only a manual Pause turns it off
    (a manual Play turns it back on). Reset honours it — while playing it returns to tick 0
    and immediately resumes, so Reset is never required to keep the demo running; while paused
    it holds at tick 0 as before. Manual Play at the end of the timeline restarts from tick 0
    rather than doing nothing, so the loop is reachable by hand too.
    """
    return (
        "<script>\n"
        "var OT_TIMELINE=" + timeline_json + ";\n"
        f"var OT_BEAT_MS={_PLAYBACK_BEAT_MS};\n"
        "function otSetLang(lang){\n"
        '  var root=document.documentElement;\n'
        '  root.lang=lang;\n'
        '  root.dir=(lang==="fa")?"rtl":"ltr";\n'
        '  document.title=(lang==="fa")?'
        f'"{_js_string(TITLE_FA)} — {_js_string(SUBTITLE_FA)}":'
        f'"{_js_string(TITLE_EN)} — {_js_string(SUBTITLE_EN)}";\n'
        '  var buttons=document.querySelectorAll(".ot-langbtn");\n'
        "  for(var i=0;i<buttons.length;i++){"
        'buttons[i].classList.toggle("ot-on",buttons[i].getAttribute("data-lang")===lang);}\n'
        "}\n"
        "function otShowTab(key){\n"
        '  var panels=document.querySelectorAll(".ot-tabpanel");\n'
        "  for(var i=0;i<panels.length;i++){"
        'panels[i].classList.toggle("ot-on",panels[i].getAttribute("data-tab")===key);}\n'
        '  var tabs=document.querySelectorAll(".ot-tabs button");\n'
        "  for(var i=0;i<tabs.length;i++){"
        'tabs[i].classList.toggle("ot-on",tabs[i].getAttribute("data-tab")===key);}\n'
        "}\n"
        # -- simulated playback (directive item 7) ------------------------------------------
        "var otTicks=OT_TIMELINE?OT_TIMELINE.ticks:[],\n"
        "    otIndex=0,otPlaying=false,otTimer=null,otSpeed=1;\n"
        "function otStamp(){var t=otTicks[otIndex];return t&&t.stamp?String(t.stamp):\"\";}\n"
        "function otClockText(){\n"
        '  var nodes=document.querySelectorAll("[data-role=playback-clock]");\n'
        "  var text=otStamp();\n"
        "  for(var i=0;i<nodes.length;i++){nodes[i].textContent=text||nodes[i].textContent;}\n"
        "}\n"
        "function otApply(tick){\n"
        '  var nodes=document.querySelectorAll("[data-otk]"),i,node,key,patch;\n'
        "  for(i=0;i<nodes.length;i++){\n"
        "    node=nodes[i];key=node.getAttribute(\"data-otk\");\n"
        "    if(!Object.prototype.hasOwnProperty.call(tick,key)){continue;}\n"
        "    patch=tick[key];\n"
        "    if(typeof patch===\"string\"){node.textContent=patch;continue;}\n"
        '    var kids=node.querySelectorAll(".dt-en,.dt-fa");\n'
        "    if(kids.length>=2){\n"
        "      kids[0].textContent=patch[0];kids[1].textContent=patch[1];\n"
        "    }\n"
        '    if(patch[2]){node.className=node.className.replace(/dt-pill--[a-z_]+/g,"");\n'
        '      node.className+=" dt-pill--"+patch[2];}\n'
        "  }\n"
        "}\n"
        "function otFrame(){\n"
        "  if(otIndex>=otTicks.length-1){otIndex=-1;}\n"
        "  otIndex++;otApply(otTicks[otIndex]);otClockText();otProgress();\n"
        "}\n"
        "function otProgress(){\n"
        '  var bars=document.querySelectorAll("[data-role=playback-progress]");\n'
        "  var f=otTicks.length>1?otIndex/(otTicks.length-1):0;\n"
        "  for(var i=0;i<bars.length;i++){bars[i].style.width=(100*f)+\"%\";}\n"
        '  var toggle=document.querySelector(".ot-playtoggle");\n'
        "  if(toggle&&toggle.classList){\n"
        '    toggle.classList.toggle("ot-on",otPlaying);}\n'
        "}\n"
        "function otTogglePlay(){if(otPlaying){otPause();}else{otPlay();}}\n"
        "function otPlay(){\n"
        "  if(!otTicks.length){return;}\n"
        "  if(otIndex>=otTicks.length-1){"
        "otIndex=0;otApply(otTicks[0]);otClockText();}\n"
        "  otPlaying=true;\n"
        '  if(otTimer){clearInterval(otTimer);}\n'
        '  otTimer=setInterval(otFrame,OT_BEAT_MS/otSpeed);\n'
        "  otProgress();\n"
        "}\n"
        "function otPause(){\n"
        "  otPlaying=false;\n"
        '  if(otTimer){clearInterval(otTimer);otTimer=null;}\n'
        "  otProgress();\n"
        "}\n"
        "function otResetPlayback(){\n"
        "  if(!otTicks.length){return;}\n"
        "  otIndex=0;otApply(otTicks[0]);otClockText();\n"
        "  if(otPlaying){otPlay();}else{otPause();}\n"
        "}\n"
        "function otSetSpeed(speed){\n"
        "  otSpeed=speed;\n"
        '  var buttons=document.querySelectorAll(".ot-speed");\n'
        "  for(var i=0;i<buttons.length;i++){"
        'buttons[i].classList.toggle("ot-on",parseFloat(buttons.getAttribute("data-speed"))===speed);}\n'
        "  if(otPlaying){otPlay();}\n"
        "}\n"
        'document.body.classList.add("ot-js");\n'
        'if(otTicks.length){otApply(otTicks[0]);}\n'
        "otClockText();otProgress();\n"
        # autoplay: the demo starts itself, and loops, the moment the document opens. Only a
        # timeline that can move (>1 tick) auto-starts; a single-frame timeline has nothing to
        # advance, so it stays on its opening frame with the controls honest and unpressed.
        "if(otTicks.length>1){otPlay();}\n"
        'otShowTab("presentation");\n'
        "</script>"
    )


def _tab_button(tab_key: str) -> str:
    en, fa = TAB_LABELS[tab_key]
    return (
        f'<button type="button" data-tab="{theme.html(tab_key)}" '
        f'onclick="otShowTab({theme.html(tab_key)!r})">{_bi(en, fa)}</button>'
    )


def _tab_panel(tab_key: str, inner: str) -> str:
    return (
        f'<section class="ot-tabpanel" data-tab="{theme.html(tab_key)}" '
        f'id="ot-panel-{theme.html(tab_key)}">{inner}</section>'
    )


def _explanation_html(tab_key: str) -> str:
    en, fa = TAB_EXPLANATIONS[tab_key]
    return f'<div class="ot-expl">{_bi(en, fa, tag="p")}</div>'


# =============================================================================
# Entry point
# =============================================================================
def build_ot_document(
    state: Any,
    *,
    settings: Any,
    render_view: RenderView,
    theme_name: str = theme.DARK,
    meta: Mapping[str, object] | None = None,
    build_timeline: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, float]]:
    """Assemble the consolidated management document and return it with per-view timings.

    ``state`` is anything exposing ``view(view_id)`` (the real :class:`DashboardState`, already
    wrapped for the presentation id by the caller — see :func:`app.build_ot_platform_document`).
    ``render_view`` is the shared per-screen dispatch (``app.build_view_section``): it builds
    one screen's view model and returns it with its rendered HTML section, and this shell embeds
    that section verbatim — no renderer is called a second way and no payload is recomputed.
    Every view that raises is re-raised as :class:`RuntimeError` naming the screen, exactly as
    :func:`app.build_document` does: a broken tab fails the document, it is never replaced by a
    placeholder.

    ``build_timeline``, when handed in, is :func:`src.visualization.playback.build_timeline`
    over the same ``render_view``: the simulated-playback timeline is built once here and
    embedded as the script's ``OT_TIMELINE`` literal, so every playback patch is the
    renderers' own output. The callable is injected rather than imported so a stub state in a
    test can decline playback without this module needing to know what a provider is.

    The returned mapping is ``view_id -> seconds`` for the build-plus-render of that screen,
    measured with :func:`time.perf_counter` — reported, never estimated.
    """
    sections: list[str] = []
    models: dict[str, Any] = {}
    timings: dict[str, float] = {}
    for tab_key, view_ids in TABS:
        if tab_key == "guide":
            sections.append(_tab_panel("guide", _guide_html()))
            continue
        if tab_key == "alerts":
            sections.append(_tab_panel("alerts", _explanation_html("alerts") + _alerts_html(models)))
            continue
        blocks: list[str] = [_explanation_html(tab_key)]
        for view_id in view_ids:
            started = time.perf_counter()
            try:
                model, section_html = render_view(state, view_id)
            except Exception as exc:  # noqa: BLE001 - reported honestly, never substituted
                raise RuntimeError(
                    f"view {view_id!r} could not be built: {type(exc).__name__}: {exc}"
                ) from exc
            timings[view_id] = time.perf_counter() - started
            models[view_id] = model
            blocks.append(f'<div class="ot-tech" dir="ltr">{section_html}</div>')
        sections.append(_tab_panel(tab_key, "".join(blocks)))

    timeline: Mapping[str, Any] | None = None
    if build_timeline is not None:
        timeline = build_timeline(state, render_view=render_view, settings=settings)

    rows = "".join(
        f"<tr><th>{theme.html(key)}</th><td>{theme.html(value)}</td></tr>"
        for key, value in (meta or {}).items()
    )
    badges = "".join(
        _badge(text)
        for text in (
            labels.SYNTHETIC_DEMONSTRATION_LABEL,
            labels.DECISION_SUPPORT_LABEL,
            labels.NOT_VALIDATED_LABEL,
        )
    )
    statements = "".join(
        f"<p>{theme.html(text)}</p>"
        for text in (
            labels.NO_PLANT_CONNECTION_STATEMENT,
            labels.LIMITATIONS_STATEMENT,
            labels.TRANSFER_STRATEGY_STATEMENT,
        )
    )
    tabs = "".join(_tab_button(tab_key) for tab_key, _ in TABS)
    footer_note = _bi(
        "Cement Plant OT Platform — a management shell over the existing technical views. "
        "Generated from the existing renderers; this shell performs no new calculation.",
        "پلتفرم فناوری عملیاتی کارخانه سیمان — پوستهٔ مدیریتی روی نماهای فنی موجود. این سند از "
        "رندرکننده‌های موجود تولید شده و هیچ محاسبهٔ جدیدی انجام نمی‌دهد.",
        tag="p",
    )
    return (
        (
            '<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{theme.html(TITLE_EN)} — {theme.html(SUBTITLE_EN)}</title>"
            f"{theme.style_tag()}{_shell_style()}</head>"
            f'<body style="margin:0"><div class="{theme.theme_class(theme_name)} ot-shell">'
            '<header class="ot-header">'
            f"<h1>{_bi(TITLE_EN, TITLE_FA)}</h1>"
            f'<p class="ot-subtitle">{_bi(SUBTITLE_EN, SUBTITLE_FA)}</p>'
            '<div class="ot-langbar">'
            + _bi("Language:", "زبان:")
            + '<button type="button" class="ot-langbtn ot-on" data-lang="en" '
            'onclick="otSetLang(\'en\')">English</button>'
            '<button type="button" class="ot-langbtn" data-lang="fa" '
            'onclick="otSetLang(\'fa\')">فارسی</button></div>'
            f'<div class="ot-badges">{badges}</div>'
            f'<div class="ot-disclosure" data-role="demo-disclosure">{_bi(DEMO_DISCLOSURE_EN, DEMO_DISCLOSURE_FA, tag="p")}</div>'
            f'<table class="ot-meta">{rows}</table>'
            "</header>"
            f"{_playback_bar()}"
            f'<nav class="ot-tabs">{tabs}</nav>'
            f"{''.join(sections)}"
            '<footer class="ot-footer">'
            f"{statements}"
            f'{_bi(DEMO_DISCLOSURE_EN, DEMO_DISCLOSURE_FA, tag="p")}'
            f'{_bi(TECHNICAL_PANELS_NOTE_EN, TECHNICAL_PANELS_NOTE_FA, tag="p")}'
            f"{footer_note}</footer>"
            "</div>"
            f"{_shell_script(playback.timeline_json(timeline))}</body></html>"
        ),
        timings,
    )


__all__ = [
    "ALERTS_TRACEABILITY_NOTE",
    "DEMO_DISCLOSURE_EN",
    "DEMO_DISCLOSURE_FA",
    "PLAYBACK_LABEL_EN",
    "PLAYBACK_LABEL_FA",
    "RenderView",
    "SUBTITLE_EN",
    "SUBTITLE_FA",
    "TABS",
    "TAB_EXPLANATIONS",
    "TAB_LABELS",
    "TECHNICAL_PANELS_NOTE_EN",
    "TECHNICAL_PANELS_NOTE_FA",
    "TITLE_EN",
    "TITLE_FA",
    "build_ot_document",
]
