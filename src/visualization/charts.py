"""Chart builders for the Plotly-backed views (PRD v1.1.1 Sections 17 views 4-8).

PRD 17 names Plotly for the zoomable Time-Series Explorer (view 6) and the Model Performance
plots (view 8), and views 4 and 5 need a prediction fan and a before/after comparison. This module
builds them, and it splits the work in two so the split survives a box without Plotly installed:

* A **builder** turns a provider payload into a :class:`ChartSpec` - a pure description of traces,
  axes and reference lines. It imports no chart library, computes no process number, and reads a
  :class:`~src.digital_twin.provenance.Value` only through its own fields. Every builder is unit
  testable by inspecting the spec it returns (which trace, which colour, which range), which is
  how the no-hard-coding audit reaches the chart code path.
* An **adapter** (:func:`to_figure`, :func:`to_html`) materialises a spec into a Plotly figure.
  Plotly is imported lazily and optionally: if it is absent the builders still run and the adapter
  renders :func:`missing_chart_html` - an honest "this chart needs Plotly" panel - rather than
  raising, so the dashboard degrades one chart instead of failing to import (NFR-6, NFR-9).

Colour comes from :mod:`src.visualization.theme`: a trace tagged with a
:class:`~src.digital_twin.provenance.Provenance` is drawn in that channel's hue, so an observed
line and a predicted line are never the same colour and a chart cannot blur the Synthetic-to-Real
or observed/predicted distinction the payloads keep apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.digital_twin.insights import PredictionSet
from src.digital_twin.payloads import Series
from src.digital_twin.provenance import Provenance, Value
from src.digital_twin.settings import FormatSettings
from src.visualization import theme

# -- optional Plotly --------------------------------------------------------------------------
try:  # Plotly is a view-time dependency, not an import-time one (NFR-9).
    import plotly.graph_objects as go

    PLOTLY_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only where Plotly is not installed
    go = None  # type: ignore[assignment]
    PLOTLY_AVAILABLE = False


#: Default chart heights (px). Design tokens, like the sizes in :mod:`theme` - chart geometry is a
#: look, not a measurement, so it lives with the other look constants and never as a view literal.
HEIGHT_TREND: int = 320
HEIGHT_FAN: int = 300
HEIGHT_BARS: int = 340
HEIGHT_SPARK: int = 40
HEIGHT_TRANSITION: int = 300


@dataclass(frozen=True, slots=True)
class Trace:
    """One line, marker set, bar group or uncertainty band on a chart.

    ``provenance`` is how the trace gets its colour when ``color`` is not given: an observed
    channel, a prediction and a recommendation each resolve to their own hue in
    :mod:`theme`, so the four data sources stay visually distinct without any view choosing a
    colour. ``kind="band"`` uses ``y_upper``/``y_lower`` instead of ``y`` and renders as a filled
    envelope - the ensemble spread of PRD 13.1.1, never a confidence percentage.
    """

    name: str
    x: tuple[Any, ...]
    y: tuple[float | None, ...] = ()
    kind: str = "line"  # line | marker | bar | band
    y_upper: tuple[float | None, ...] = ()
    y_lower: tuple[float | None, ...] = ()
    color: str | None = None
    provenance: Provenance | None = None
    dash: str | None = None  # None | dash | dot
    width: float | None = None
    opacity: float | None = None
    show_markers: bool = False

    def resolved_color(self, palette: theme.Palette) -> str:
        """The trace colour: an explicit one, else its provenance hue, else the accent."""
        if self.color is not None:
            return self.color
        if self.provenance is not None:
            return theme.provenance_color(self.provenance, palette)
        return palette.accent


@dataclass(frozen=True, slots=True)
class Marker:
    """A labelled vertical reference line - e.g. where a setpoint move begins, or where a delayed
    response reaches half travel. This is what makes "visible delay" (PRD view 5) a drawn thing."""

    x: Any
    label: str
    color: str | None = None


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """A chart as pure data, ready for :func:`to_figure` but complete without it."""

    title: str
    traces: tuple[Trace, ...]
    x_title: str = ""
    y_title: str = ""
    x_kind: str = "time"  # time | category | numeric
    x_ticktext: tuple[str, ...] = ()
    unit: str = ""
    height: int | None = None
    theme_name: str = theme.DARK
    minimal: bool = False  # sparkline: strip axes, legend, margins
    markers: tuple[Marker, ...] = ()
    note: str = ""

    def describe(self) -> dict[str, Any]:
        """A JSON-friendly summary - what a test asserts against instead of a rendered figure."""
        return {
            "title": self.title,
            "x_title": self.x_title,
            "y_title": self.y_title,
            "x_kind": self.x_kind,
            "unit": self.unit,
            "theme": self.theme_name,
            "minimal": self.minimal,
            "traces": [
                {
                    "name": t.name,
                    "kind": t.kind,
                    "points": len(t.y) or len(t.y_upper),
                    "provenance": str(t.provenance) if t.provenance else None,
                    "color": t.color,
                }
                for t in self.traces
            ],
            "markers": [{"x": m.x, "label": m.label} for m in self.markers],
        }


# -- builders (pure) --------------------------------------------------------------------------
def _series_trace(
    series: Series,
    *,
    name: str | None = None,
    color: str | None = None,
    dash: str | None = None,
    show_markers: bool = False,
) -> Trace:
    """One :class:`Series` as a line trace, coloured by the series' own provenance."""
    return Trace(
        name=name or series.tag,
        x=series.timestamps,
        y=series.values,
        kind="line",
        color=color,
        provenance=series.provenance,
        dash=dash,
        show_markers=show_markers,
    )


def trend(
    series: Sequence[Series],
    *,
    title: str,
    unit: str = "",
    theme_name: str = theme.DARK,
    height: int | None = None,
) -> ChartSpec:
    """A multi-tag time-series chart (view 6). Each channel keeps its provenance colour."""
    return ChartSpec(
        title=title,
        traces=tuple(_series_trace(s) for s in series),
        x_title="Time",
        y_title=unit,
        unit=unit,
        x_kind="time",
        height=height or HEIGHT_TREND,
        theme_name=theme_name,
    )


def sparkline(series: Series, *, theme_name: str = theme.DARK) -> ChartSpec:
    """A tiny axis-free trend for a KPI card (PRD 18.1). One channel, no chrome."""
    return ChartSpec(
        title=series.tag,
        traces=(_series_trace(series),),
        x_kind="time",
        height=HEIGHT_SPARK,
        theme_name=theme_name,
        minimal=True,
    )


def baseline_vs_optimized(
    baseline: Series,
    optimized: Series,
    *,
    title: str = "",
    unit: str = "",
    theme_name: str = theme.DARK,
) -> ChartSpec:
    """The baseline-vs-optimized overlay of PRD view 6.

    Baseline is drawn muted and dashed, optimized in the recommendation hue: the eye reads the
    optimized line as the proposed one and the baseline as the reference, without a legend having
    to say so. Neither line is recomputed here - both are provider series.
    """
    palette = theme.theme(theme_name)
    base = _series_trace(baseline, name="Baseline", color=palette.text_muted, dash="dash")
    opt = _series_trace(
        optimized, name="Optimized", color=theme.provenance_color(Provenance.RECOMMENDATION, palette)
    )
    return ChartSpec(
        title=title or f"{baseline.tag}: baseline vs optimized",
        traces=(base, opt),
        x_title="Time",
        y_title=unit or baseline.unit,
        unit=unit or baseline.unit,
        x_kind="time",
        height=HEIGHT_TREND,
        theme_name=theme_name,
    )


def prediction_fan(
    prediction: PredictionSet,
    target: str,
    *,
    theme_name: str = theme.DARK,
) -> ChartSpec:
    """Model A's multi-horizon path for one target, with its ensemble-spread band (view 4).

    The current observed value anchors the path at horizon 0 in the observed hue; the predicted
    points continue it in the prediction hue; the band is each point's ``value ± uncertainty``
    (:meth:`Value.interval`) - the spread the ensemble reported, drawn as an envelope and never
    relabelled as a confidence percentage (FR-23, AC-18). ``x`` is horizon minutes so the widening
    band reads as "less certain further out".
    """
    palette = theme.theme(theme_name)
    current = next((v for v in prediction.current if v.tag == target), None)
    row = prediction.target_row(target)  # predictions, ascending horizon

    xs: list[float] = []
    ys: list[float | None] = []
    uppers: list[float | None] = []
    lowers: list[float | None] = []
    if current is not None:
        xs.append(0.0)
        ys.append(current.value)
        uppers.append(None)
        lowers.append(None)
    for value in row:
        minutes = float(value.horizon_min) if value.horizon_min is not None else float(len(xs))
        xs.append(minutes)
        ys.append(value.value)
        interval = value.interval
        uppers.append(interval[1] if interval else None)
        lowers.append(interval[0] if interval else None)

    traces: list[Trace] = []
    if any(u is not None for u in uppers):
        traces.append(
            Trace(
                name="Ensemble spread",
                x=tuple(xs),
                y_upper=tuple(uppers),
                y_lower=tuple(lowers),
                kind="band",
                provenance=Provenance.PREDICTION,
                opacity=0.18,
            )
        )
    traces.append(
        Trace(
            name="Prediction",
            x=tuple(xs),
            y=tuple(ys),
            kind="line",
            provenance=Provenance.PREDICTION,
            show_markers=True,
        )
    )
    if current is not None:
        traces.append(
            Trace(
                name="Current (observed)",
                x=(0.0,),
                y=(current.value,),
                kind="marker",
                provenance=Provenance.OBSERVED,
            )
        )
    unit = current.unit if current else (row[0].unit if row else "")
    ticks = ("Current",) + tuple(
        f"t+{int(x)}" for x in xs[1:]
    )
    return ChartSpec(
        title=f"{target}: current + predicted",
        traces=tuple(traces),
        x_title="Horizon (minutes)",
        y_title=unit,
        unit=unit,
        x_kind="numeric",
        x_ticktext=ticks,
        height=HEIGHT_FAN,
        theme_name=theme_name,
    )


def before_after_bars(
    rows: Sequence[Mapping[str, Any]],
    *,
    settings: FormatSettings,
    title: str = "Before / after",
    theme_name: str = theme.DARK,
) -> ChartSpec:
    """Grouped before/after bars from a what-if panel's ``before_after`` list (view 5).

    Each ``row`` is a before/after dict carrying ``tag``, ``baseline`` (before) and the after
    number under either ``value`` (a :meth:`Value.describe`) or ``proposed`` (a
    :meth:`~src.optimization.recommendation.MetricDelta.describe`, which is what the what-if panel
    and the optimization expected-impact list actually emit). Reading both keys lets one builder
    serve every producer without a per-call-site remap. Each pair is one category; nothing is
    recomputed - the numbers are the engine's.
    """
    tags = tuple(str(r.get("tag", "")) for r in rows)
    before = tuple(_as_float(r.get("baseline")) for r in rows)
    after = tuple(_as_float(r.get("value", r.get("proposed"))) for r in rows)
    palette = theme.theme(theme_name)
    return ChartSpec(
        title=title,
        traces=(
            Trace(name="Before", x=tags, y=before, kind="bar", color=palette.text_muted),
            Trace(
                name="After",
                x=tags,
                y=after,
                kind="bar",
                color=theme.provenance_color(Provenance.RECOMMENDATION, palette),
            ),
        ),
        x_title="",
        x_kind="category",
        height=HEIGHT_BARS,
        theme_name=theme_name,
    )


def transition(
    minutes: Sequence[float],
    commanded: Sequence[float | None],
    responded: Sequence[float | None],
    *,
    tag: str,
    unit: str = "",
    markers: Sequence[Marker] = (),
    theme_name: str = theme.DARK,
) -> ChartSpec:
    """Commanded setpoint vs the plant's delayed response over the what-if window (view 5).

    The two lines and the gap between them *are* the dead time plus lag (PRD 16.2): the command
    steps, the response follows late. This builder takes explicit series rather than a payload so
    it stays decoupled from where the trajectory is plumbed and testable on synthetic curves.
    ``markers`` draws the reference lines that make the delay a measured quantity, not a visual one.
    """
    palette = theme.theme(theme_name)
    return ChartSpec(
        title=f"{tag}: commanded vs response",
        traces=(
            Trace(
                name="Commanded",
                x=tuple(minutes),
                y=tuple(commanded),
                kind="line",
                color=palette.accent_alt,
                dash="dash",
            ),
            Trace(
                name="Response",
                x=tuple(minutes),
                y=tuple(responded),
                kind="line",
                provenance=Provenance.OBSERVED,
            ),
        ),
        x_title="Minutes from setpoint move",
        y_title=unit,
        unit=unit,
        x_kind="numeric",
        markers=tuple(markers),
        height=HEIGHT_TRANSITION,
        theme_name=theme_name,
    )


def model_performance_bars(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    title: str = "",
    theme_name: str = theme.DARK,
) -> ChartSpec:
    """Per-target / per-horizon metric bars for view 8 (PRD 22).

    ``rows`` each carry ``target``, ``horizon_min`` and the metric value under ``metric``. One bar
    per (target, horizon); the values are the model card's own, read not recomputed.
    """
    labels = tuple(
        f"{r.get('target', '')} · t+{int(r.get('horizon_min', 0))}" for r in rows
    )
    values = tuple(_as_float(r.get(metric)) for r in rows)
    palette = theme.theme(theme_name)
    return ChartSpec(
        title=title or f"{metric} per target and horizon",
        traces=(Trace(name=metric, x=labels, y=values, kind="bar", color=palette.accent),),
        y_title=metric,
        x_kind="category",
        height=HEIGHT_BARS,
        theme_name=theme_name,
    )


def _as_float(value: Any) -> float | None:
    """A cell as a float, or ``None`` for a missing / non-numeric one (a bar simply omits it)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


# -- adapter (Plotly, optional) ---------------------------------------------------------------
def _axis(palette: theme.Palette, title: str, *, minimal: bool) -> dict[str, Any]:
    if minimal:
        return {"visible": False}
    return {
        "title": {"text": title, "font": {"size": 11, "color": palette.text_muted}},
        "gridcolor": palette.grid,
        "zerolinecolor": palette.grid,
        "linecolor": palette.border,
        "tickfont": {"color": palette.text_muted, "size": 10},
    }


def to_figure(spec: ChartSpec) -> Any:
    """Materialise a :class:`ChartSpec` into a Plotly figure. Requires Plotly to be installed.

    Kept deliberately thin: every decision that matters - which trace, which colour, which range -
    was already made in the builder, so this only translates the spec into Plotly's vocabulary.
    """
    if not PLOTLY_AVAILABLE:  # pragma: no cover
        raise RuntimeError(
            "to_figure needs Plotly, which is not installed. Use to_html, which degrades to a "
            "missing-chart panel instead of raising (NFR-9)."
        )
    palette = theme.theme(spec.theme_name)
    fig = go.Figure()
    for tr in spec.traces:
        color = tr.resolved_color(palette)
        if tr.kind == "band":
            fig.add_trace(
                go.Scatter(
                    x=tr.x, y=tr.y_upper, mode="lines", line={"width": 0},
                    hoverinfo="skip", showlegend=False, name=tr.name,
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=tr.x, y=tr.y_lower, mode="lines", line={"width": 0}, fill="tonexty",
                    fillcolor=_rgba(color, tr.opacity or 0.18), hoverinfo="skip",
                    showlegend=False, name=tr.name,
                )
            )
        elif tr.kind == "bar":
            fig.add_trace(go.Bar(x=tr.x, y=tr.y, name=tr.name, marker_color=color, opacity=tr.opacity or 1.0))
        elif tr.kind == "marker":
            fig.add_trace(
                go.Scatter(
                    x=tr.x, y=tr.y, mode="markers", name=tr.name,
                    marker={"color": color, "size": 9, "line": {"width": 1, "color": palette.bg}},
                )
            )
        else:  # line
            mode = "lines+markers" if tr.show_markers else "lines"
            fig.add_trace(
                go.Scatter(
                    x=tr.x, y=tr.y, mode=mode, name=tr.name,
                    line={"color": color, "width": tr.width or 2, "dash": tr.dash or "solid"},
                    opacity=tr.opacity or 1.0,
                )
            )
    for mark in spec.markers:
        fig.add_vline(
            x=mark.x, line={"color": mark.color or palette.text_muted, "width": 1, "dash": "dot"},
            annotation_text=mark.label, annotation_font={"size": 10, "color": palette.text_muted},
        )
    xaxis = _axis(palette, spec.x_title, minimal=spec.minimal)
    fig.update_layout(
        title=None if spec.minimal else {"text": spec.title, "font": {"color": palette.text, "size": 14}},
        height=spec.height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": TOKENS_FONT, "color": palette.text},
        margin={"l": 8, "r": 8, "t": 4, "b": 4} if spec.minimal else {"l": 56, "r": 16, "t": 40, "b": 44},
        showlegend=not spec.minimal and len(spec.traces) > 1,
        legend={"orientation": "h", "y": -0.2, "font": {"size": 10, "color": palette.text_muted}},
        barmode="group",
        xaxis=xaxis,
        yaxis=_axis(palette, spec.y_title, minimal=spec.minimal),
    )
    if spec.x_ticktext and not spec.minimal:
        # ticks positioned on the first trace's x (all traces share the horizon axis)
        base = spec.traces[0].x if spec.traces else ()
        fig.update_xaxes(tickmode="array", tickvals=list(base), ticktext=list(spec.x_ticktext))
    return fig


#: Font family handed to Plotly - the same monospace-adjacent sans the panels use.
TOKENS_FONT = theme.TOKENS.font_sans


def _rgba(hex_color: str, alpha: float) -> str:
    """A ``#rrggbb`` colour as an ``rgba(...)`` string at ``alpha`` - for the translucent band."""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, alpha))})"


def to_html(
    spec: ChartSpec,
    *,
    include_plotlyjs: bool | str = False,
    div_id: str | None = None,
) -> str:
    """A chart as an HTML fragment. Falls back to :func:`missing_chart_html` without Plotly.

    ``include_plotlyjs`` follows Plotly's own contract: ``False`` embeds no library (the dashboard
    loads it once), ``"inline"`` bundles it for a standalone ``.html`` export (PRD 29 / 19.3), and
    ``"cdn"`` links it. The default embeds nothing, so a page with twenty charts carries the
    library once, not twenty times.
    """
    if not PLOTLY_AVAILABLE:
        return missing_chart_html(spec)
    fig = to_figure(spec)
    return fig.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        div_id=div_id,
        config={"displayModeBar": False, "responsive": True} if spec.minimal else {"responsive": True},
    )


def missing_chart_html(spec: ChartSpec) -> str:
    """A themed placeholder shown where a chart would be if Plotly were installed.

    An honest absence, not a blank space: it names the chart and says why it is not drawn, so a
    Plotly-less environment degrades one panel to a caption instead of failing (NFR-6, NFR-9).
    """
    return (
        f'<div class="dt-card dt-card--alt" style="min-height:{spec.height or HEIGHT_TREND}px">'
        f'<div class="dt-title">{theme.html(spec.title)}</div>'
        f'<div class="dt-muted">Chart needs Plotly, which is not installed in this session. '
        f"The numbers behind it are shown in the panel's table; install plotly to draw it.</div>"
        f"</div>"
    )


__all__ = [
    "PLOTLY_AVAILABLE",
    "ChartSpec",
    "Marker",
    "Trace",
    "baseline_vs_optimized",
    "before_after_bars",
    "missing_chart_html",
    "model_performance_bars",
    "prediction_fan",
    "sparkline",
    "to_figure",
    "to_html",
    "transition",
    "trend",
]
