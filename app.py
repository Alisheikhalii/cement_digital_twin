"""Task #6 runnable host: export the dashboard as one self-contained HTML file.

Nothing in ``src/`` launches itself - every screen is a frozen view model and every drawing is a
string-returning function. This module is the missing entrypoint, and it is deliberately thin: it
builds a :class:`~src.digital_twin.session.DashboardSession`, asks
:class:`~src.digital_twin.state.DashboardState` for the screens the caller named, renders the
animated SVG twin with :func:`~src.visualization.svg_twin.render_twin`, and writes one ``.html``
file that animates in any browser with no server, no network and no assets.

**Zero new dependencies.** No plotly, streamlit, dash, jupyter or matplotlib: the twin is inline
SVG plus CSS ``@keyframes``, and any view that would want a chart degrades through
``src.visualization.charts.missing_chart_html`` instead of importing a plotting library.

How to launch it
----------------
::

    python app.py                                   # the animated twin (view B) -> reports/
    python app.py --view B --view E --out twin.html  # both twin screens
    python app.py --skip-models --no-browser        # ~0.4 s: twin only, no model layer
    python app.py --view J --scenario "Low oxygen condition" --seed 20240101
    python app.py --help                            # every flag, every valid view and scenario

Cost of each flag, measured on this machine (see ``TASK6_RECOVERY_PLAN.md`` sections 5 B-6 and 10):
the model layer dominates a full build (~30 s here; the plan records 13.3-16.6 s), the replay run
is the other expensive step, and one view costs 1.5 ms (C-G) to a few seconds (H/I/J, and A's
AI/anomaly status tiles, which read the same payloads H and J render - ~3 s with the model layer
present, instant under ``--skip-models`` where both tiles honestly report the models as absent).
So this host uses the fast path documented at ``session.py`` in ``DashboardSession.build`` -
``replay`` off by default, and the lazy ``DashboardState.view()`` accessor rather than ``views()``,
which would eagerly build all ten screens. Every timing it prints is measured, never estimated.

Honesty
-------
Everything this file emits carries "Synthetic Demonstration", "Decision Support Only" and "Not
validated against real plant data", plus the verbatim PRD statements from :mod:`src.labels`. This
dashboard reads a synthetic simulation: no plant connection, no instrument, no setpoint written, no
confidence percentage, no validated saving. A view that cannot be built is reported as a failure -
never filled in with a substitute number.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src import labels
from src.config import SCENARIOS, Config, load_config
from src.digital_twin.state import VIEWS
from src.visualization import (
    energy_view,
    intelligence_view,
    optimization_view,
    overview_view,
    svg_twin,
    theme,
)

DEFAULT_OUT = Path("reports") / "task6_dashboard.html"
DEFAULT_VIEWS = ("B",)


# =============================================================================
# HTML assembly - importable, and testable against any object exposing ``view(view_id)``
# =============================================================================
def _is_twin(model: Any) -> bool:
    """True for the animated-twin screens (B / E), which carry a ``line`` plus the full state.

    Duck-typed on the two fields :class:`~src.digital_twin.state.TwinView` adds over the other
    screens, so this module needs no import-time knowledge of which ids are twins.
    """
    return hasattr(model, "line") and hasattr(model, "snapshot")


def _is_optimization(model: Any) -> bool:
    """True for the AI Optimization screen (J), whose view model carries an ``OptimizationView``.

    Duck-typed on the accessors that view's inner view exposes and no other screen's does
    (:meth:`~src.digital_twin.insights.OptimizationView.recommendation` / ``baselines`` /
    ``blocking_gates``), so the routing stays shape-based like :func:`_is_twin`.
    """
    view = getattr(model, "view", None)
    return (
        hasattr(view, "recommendation")
        and hasattr(view, "baselines")
        and hasattr(view, "blocking_gates")
    )


def _is_intelligence(model: Any) -> bool:
    """True for the AI Prediction & Anomaly screen (H), whose view model carries both payloads.

    Duck-typed on the two fields :class:`~src.digital_twin.state.IntelligenceView` adds over
    the other screens (``predictions`` and ``anomaly``), so the routing stays shape-based like
    :func:`_is_twin` and :func:`_is_optimization` — and no other screen's model carries both.
    """
    return hasattr(model, "predictions") and hasattr(model, "anomaly")


def _is_overview(model: Any) -> bool:
    """True for the Plant Overview screen (A), whose view model carries the stage chain.

    Duck-typed on the two fields :class:`~src.digital_twin.state.OverviewView` adds over the
    other screens (``stages`` and ``plant``), so the routing stays shape-based like
    :func:`_is_twin`, :func:`_is_intelligence` and :func:`_is_optimization` — no other screen's
    model carries both (the energy view has a ``plant`` group but no stage chain).
    """
    return hasattr(model, "stages") and hasattr(model, "plant")


def _is_energy(model: Any) -> bool:
    """True for the Energy Monitoring screen (G), whose view model carries the item-12 partition.

    Duck-typed on the two fields :class:`~src.digital_twin.state.EnergyView` adds over the other
    screens (the ``specific`` and ``total`` panels of the item-12 partition — the view's whole
    reason to exist), so the routing stays shape-based like :func:`_is_twin` and
    :func:`_is_overview`. No other screen's model carries a ``specific``/``total`` pair: the
    overview exposes the same plant group whole, not partitioned.
    """
    return hasattr(model, "specific") and hasattr(model, "total")


def _source_is_synthetic(state: Any) -> bool:
    """The rendering source's own ``synthetic`` flag (B-7 site 2, the Wave 3B ``state._header`` fix).

    Read from ``state.capabilities().synthetic`` — the same derivation ``DashboardState._header``
    uses — rather than left to :func:`~src.visualization.svg_twin.render_twin`'s ``True`` default,
    so a document exported over a provider reporting ``synthetic=False`` cannot claim a synthetic
    origin. Duck-typed: a stub state exposing only ``view(view_id)`` has no capabilities to ask,
    and every such stub stands in for the synthetic demonstration, so the answer falls back to
    ``True`` — the renderer's own documented default — instead of failing the render.
    """
    capabilities = getattr(state, "capabilities", None)
    if callable(capabilities):
        return bool(capabilities().synthetic)
    return True


def _heading_html(model: Any, view_id: str) -> str:
    header = getattr(model, "header", None)
    title = theme.html(getattr(header, "title", None) or view_id)
    subtitle = theme.html(getattr(header, "subtitle", "") or "")
    return (
        f'<h2 class="dt-app__title">{theme.html(view_id)} — {title}</h2>'
        f'<p class="dt-muted">{subtitle}</p>'
    )


def _payload_html(model: Any) -> str:
    """A non-twin screen as its own view-model payload: the numbers, unrendered but not invented.

    Phase 6D owns the per-view renderers. Until they exist this host shows the frozen view model
    verbatim rather than a prettier screen built from values it made up.
    """
    payload = model.describe() if hasattr(model, "describe") else model
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    return (
        '<p class="dt-muted">View-model payload (no renderer for this screen yet — '
        f"{theme.html(labels.SIMULATED_RESULT_LABEL)}).</p>"
        f'<pre class="dt-mono dt-app__payload">{theme.html(text)}</pre>'
    )


def build_document(
    state: Any,
    view_ids: Sequence[str],
    *,
    settings: Any,
    theme_name: str = theme.DARK,
    animate: bool = True,
    meta: Mapping[str, object] | None = None,
) -> tuple[str, dict[str, float]]:
    """Assemble one self-contained HTML document from ``state`` and return it with its timings.

    ``state`` is anything exposing ``view(view_id)`` - a real
    :class:`~src.digital_twin.state.DashboardState`, or a stub in a test. When it also exposes
    ``capabilities()`` (as the real one does), the twin's source badge is derived from
    ``capabilities().synthetic`` (:func:`_source_is_synthetic`); a bare ``view(view_id)`` stub
    keeps the synthetic default. ``settings`` is the
    :class:`~src.digital_twin.settings.DashboardSettings` the twin reads its animation ranges from,
    so no animation parameter is written here. The returned mapping is ``view_id -> seconds`` for
    the build-plus-render of that one screen, measured with :func:`time.perf_counter`.

    A view that raises is re-raised as :class:`RuntimeError` naming the screen. It is never replaced
    by a placeholder number.
    """
    sections: list[str] = []
    timings: dict[str, float] = {}
    for view_id in view_ids:
        started = time.perf_counter()
        try:
            model = state.view(view_id)
            if _is_twin(model):
                body = svg_twin.render_twin(
                    model.snapshot,
                    getattr(model, "equipment", ()),
                    settings=settings,
                    theme_name=theme_name,
                    animate=animate,
                    synthetic=_source_is_synthetic(state),
                )
            elif _is_intelligence(model):
                body = intelligence_view.render_intelligence(
                    model, settings=settings, theme_name=theme_name
                )
            elif _is_optimization(model):
                body = optimization_view.render_optimization(
                    model, settings=settings, theme_name=theme_name
                )
            elif _is_overview(model):
                body = overview_view.render_overview(
                    model, settings=settings, theme_name=theme_name
                )
            elif _is_energy(model):
                body = energy_view.render_energy(
                    model, settings=settings, theme_name=theme_name
                )
            else:
                body = _payload_html(model)
        except Exception as exc:  # noqa: BLE001 - reported honestly, never substituted
            raise RuntimeError(
                f"view {view_id!r} could not be built: {type(exc).__name__}: {exc}"
            ) from exc
        timings[view_id] = time.perf_counter() - started
        sections.append(
            f'<section class="dt-app__view">{_heading_html(model, view_id)}{body}</section>'
        )
    return _document(sections, theme_name=theme_name, meta=meta or {}), timings


def _document(
    sections: Sequence[str],
    *,
    theme_name: str = theme.DARK,
    meta: Mapping[str, object] | None = None,
) -> str:
    """Wrap rendered sections in a standalone document: inline styles, honesty labels, no assets."""
    heading = theme.html(labels.full_system_label())
    badges = "".join(
        f'<span class="dt-badge dt-badge--configuration">{theme.html(text)}</span>'
        for text in (
            labels.SYNTHETIC_DEMONSTRATION_LABEL,
            labels.DECISION_SUPPORT_LABEL,
            labels.NOT_VALIDATED_LABEL,
        )
    )
    rows = "".join(
        f"<tr><th>{theme.html(key)}</th><td>{theme.html(value)}</td></tr>"
        for key, value in (meta or {}).items()
    )
    statements = "".join(
        f"<p>{theme.html(text)}</p>"
        for text in (
            labels.NO_PLANT_CONNECTION_STATEMENT,
            labels.LIMITATIONS_STATEMENT,
            labels.TRANSFER_STRATEGY_STATEMENT,
        )
    )
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{heading}</title>{theme.style_tag()}"
        "<style>.dt-app__view{margin:0 0 2rem;}.dt-app__payload{overflow-x:auto;"
        "white-space:pre-wrap;}.dt-app table{border-collapse:collapse;}"
        ".dt-app th,.dt-app td{padding:.15rem .75rem .15rem 0;text-align:left;"
        "font-weight:400;vertical-align:top;}</style>"
        '</head><body style="margin:0">'
        f'<main class="{theme.theme_class(theme_name)} dt-app" style="padding:1rem">'
        f"<h1>{heading}</h1><p>{badges}</p>"
        f'<table class="dt-mono dt-muted">{rows}</table>'
        f"{''.join(sections)}"
        f'<footer class="dt-muted">{statements}</footer>'
        "</main></body></html>"
    )


# =============================================================================
# CLI
# =============================================================================
def _scenario_names(scenarios: Config) -> tuple[str, ...]:
    """The selectable scenario names, read from ``configs/scenarios.yaml`` and nowhere else."""
    return tuple(str(regime["name"]) for regime in scenarios.get_path("regime_schedule.regimes"))


def _scenarios_config(seed: int | None) -> Config:
    """``configs/scenarios.yaml``, with only the seed replaced when ``--seed`` was given."""
    scenarios = load_config(SCENARIOS)
    if seed is None:
        return scenarios
    raw = scenarios.to_dict()
    raw["simulation"]["seed"] = int(seed)
    return Config(raw, source=f"{scenarios.source} (+ --seed {seed})")


def build_parser(scenario_names: Sequence[str] = ()) -> argparse.ArgumentParser:
    """The documented CLI. View ids/keys come from :data:`src.digital_twin.state.VIEWS`."""
    view_lines = "\n".join(f"  {row[0]}  {row[1]:<13} {row[2]}" for row in VIEWS)
    example = "  python app.py --view J --seed 20240101"
    if scenario_names:
        example += f" --scenario {scenario_names[0]!r}"
    parser = argparse.ArgumentParser(
        prog="python app.py",
        description=(
            "Export the Task #6 dashboard as one self-contained HTML file, animated SVG twin "
            "included. Synthetic Demonstration / Decision Support Only / Not validated against "
            "real plant data."
        ),
        epilog=(
            f"views (--view takes the id or the key, repeatable):\n{view_lines}\n\n"
            "H, I and J need the model layer, so they are unavailable under --skip-models and "
            "will say so rather than show a substitute number. View A renders either way, but "
            "its AI status and anomaly status tiles read the model layer too, so under "
            "--skip-models they state the models' own unavailable reason.\n\n"
            "examples:\n"
            "  python app.py\n"
            "  python app.py --skip-models --no-browser\n"
            "  python app.py --view B --view E --out reports/twins.html\n"
            f"{example}\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output file (default: {DEFAULT_OUT})")
    parser.add_argument(
        "--view",
        dest="views",
        action="append",
        metavar="ID",
        choices=[row[0] for row in VIEWS] + [row[1] for row in VIEWS],
        help=f"screen to render, repeatable (default: {' '.join(DEFAULT_VIEWS)} — the animated twin)",
    )
    parser.add_argument(
        "--scenario", metavar="NAME", choices=list(scenario_names) or None,
        help="operating regime to drive the live session with (from configs/scenarios.yaml)",
    )
    parser.add_argument("--seed", type=int, help="override configs/scenarios.yaml simulation.seed")
    parser.add_argument(
        "--advance", type=float, default=0.0, metavar="MINUTES",
        help="step the live clock this many simulated minutes before rendering (default: 0)",
    )
    parser.add_argument("--theme", default=theme.DARK, choices=[theme.DARK, theme.LIGHT], help="palette")
    parser.add_argument("--no-animate", dest="animate", action="store_false", help="render a still frame")
    parser.add_argument(
        "--replay", action="store_true",
        help="also build the recorded replay window (a second simulation run — slow)",
    )
    parser.add_argument(
        "--skip-models", action="store_true",
        help="skip the model layer: seconds instead of tens of seconds; H/I/J report no model",
    )
    parser.add_argument("--no-browser", dest="browser", action="store_false", help="do not open the file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build, render, write, report. Returns 0, or non-zero with a one-line reason on stderr."""
    scenarios = _scenarios_config(None)
    args = build_parser(_scenario_names(scenarios)).parse_args(argv)
    view_ids = tuple(args.views or DEFAULT_VIEWS)
    if args.seed is not None:
        scenarios = _scenarios_config(args.seed)

    from src.digital_twin.session import DashboardSession, ModelLayer
    from src.digital_twin.state import DashboardState

    started = time.perf_counter()
    try:
        session = DashboardSession.build(
            live=True,
            replay=args.replay,
            scenarios=scenarios,
            regime=args.scenario,
            models=ModelLayer() if args.skip_models else None,
        )
        if args.advance:
            session.provider.advance(args.advance)
    except Exception as exc:  # noqa: BLE001
        print(f"error: could not build the session: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    build_seconds = time.perf_counter() - started

    described = session.describe()
    meta = {
        "provider": f"{described['provider']} · mode {described['mode']}",
        "training data": session.training_source,
        "replay window": session.replay_source,
        "scenario": args.scenario or "as scheduled by configs/scenarios.yaml",
        "seed": args.seed if args.seed is not None else scenarios.get_path("simulation.seed"),
        "unavailable": ", ".join(described["capabilities"]["missing"]) or "nothing",
    }
    try:
        html, view_seconds = build_document(
            DashboardState.from_session(session),
            view_ids,
            settings=session.settings,
            theme_name=args.theme,
            animate=args.animate,
            meta=meta,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "no output was written and no substitute values were shown. If this is "
            "'Input X contains NaN', it is the known Task #6 data-assembly defect on the model "
            "history path; --view B (the twin) does not touch it.",
            file=sys.stderr,
        )
        return 3

    out = args.out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    print(f"session build   {build_seconds:8.3f} s  {json.dumps(described['build_seconds'])}")
    for view_id, seconds in view_seconds.items():
        print(f"view {view_id:<10} {seconds:8.3f} s")
    print(f"total           {time.perf_counter() - started:8.3f} s")
    print(f"wrote {out} ({out.stat().st_size} bytes, self-contained)")
    for note in session.notes():
        print(f"note: {note}")
    if args.browser:
        import webbrowser

        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
