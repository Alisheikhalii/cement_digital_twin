"""The embedded timeline behind the shell's simulated-live playback (directive item 7).

The OT document is a static file, but an executive demo still needs the "plant moves" moment:
values, status pills, equipment states and timestamps that visibly advance while Play is held.
This module builds that timeline **at export time** and embeds it in the document as one
``var OT_TIMELINE = {...}`` literal; the runtime side (:mod:`src.visualization.ot_shell`)
replays it with a few lines of inline JavaScript and no network, no library and no
``Math.random()``.

**How the timeline is built — render, then diff.** For each tick the provider is advanced by
one ``step_minutes`` sample and the same time-indexed views are re-rendered through the very
dispatch the document itself uses (:func:`app.build_view_section`). The fresh render's
``data-otk``-anchored nodes are read back and compared with the previous tick's; only the
anchors whose *rendered* content changed enter the timeline. That guarantees a property no
hand-collected value list could: every patch is, byte for byte, what a real re-render would
have put on the screen — the playback is the renderers' own output, not a parallel
presentation of the same numbers (the wave's constraint 3, applied to playback).

**Which views move.** Only the time-indexed screens: the plant overview (A), the two twins
(B, E), the process detail panels (C, F), energy (G), and — when the model layer is present —
the prediction grid and anomaly verdict of view H. Scenario-level results (the optimizer's
view J, the what-if answer, the PRD §29 presentation overlay) stay static by the wave's rule:
they describe one evaluated operating point, not a time series, and replaying them would imply
a re-optimization that never happened.

**Two patch shapes.** A plain string replaces the anchored element's text (a number, a
timestamp, an identifier). A ``[en, fa, cls]`` triple replaces a bilingual pill: the two
language children are patched and the pill's ``dt-pill--*`` class is swapped, because a status
that moves from OK to WARNING must also move its colour. Both shapes are produced by reading
the renderers' own markup — ``<bdi>``, ``<span>`` and ``<tspan>`` alike — never by
re-formatting a payload value in this module.

**The provider is left where it was found.** The build advances a live clock, which mutates
the session's driver. When the timeline is done the provider is reset and re-advanced to the
timestamp it reported at entry, so the document the caller then renders — the initial state
every panel ships with — is the same instant the caller intended to show. A provider that
cannot be advanced (a stub, a real-plant source) yields a single-tick timeline: the playback
controls are present and honest, and the clock simply never moves.
"""

from __future__ import annotations

import re
from typing import Any, Final, Mapping

from src.visualization import theme
from src.visualization.i18n import STAMP_KEY

#: The view ids whose panels carry time-indexed anchors and therefore move during playback.
#: Views B/E are the twins, C/F the process panels; view D is kiln emissions — a fixed set of
#: slow-moving stack readings the demo timeline also carries, since it renders through the
#: same process renderer as C/F.
TIMELINE_VIEWS: Final[tuple[str, ...]] = ("A", "B", "C", "D", "E", "F", "G", "H")

#: How many samples the embedded timeline holds. A presentation demo moves at 1×–4× with one
#: sample per beat, so 45 samples is under two minutes of 1× playback — enough for an
#: audience to watch trends and status pills move — while the build cost stays bounded: the
#: expensive model-backed views (A's AI tiles, H's forecast grid) are re-rendered once per
#: tick, and 45 ticks of those cost under a minute on the reference machine.
MAX_TICKS: Final[int] = 45

#: One minute, the unit ``provider.advance`` takes. The clock's own ``step_minutes`` is read
#: from the settings instead of assumed here; this is only the fallback for a state that does
#: not expose its step size (a stub).
_DEFAULT_STEP_MINUTES: Final[float] = 1.0

#: The pill class an anchored node carries, captured so a status change can swap it.
_PILL_CLASS = re.compile(r"dt-pill--([a-z_]+)")

#: The two language children of a bilingual node: ``dt-en`` first, ``dt-fa`` second (the pair
#: :func:`src.visualization.i18n.bi` emits, in that order) — as ``<span>`` or ``<tspan>``, so
#: the SVG glyphs the twins render are read the same way the HTML pills are.
_LANG_SPAN = re.compile(
    r'<(?:span|tspan) class="dt-(?:en|fa)"[^>]*>(.*?)</(?:span|tspan)>',
    re.DOTALL,
)
_LANG_SPAN_PAIR = re.compile(
    _LANG_SPAN.pattern + r"\s*" + _LANG_SPAN.pattern
)


def _anchor_text(opening_attrs: str, inner: str) -> tuple[str, ...] | str:
    """The patch payload for one anchored node's rendered HTML.

    A bilingual language-pair — the ``<span>``/``<tspan>`` children :func:`i18n.bi` emits —
    becomes the triple ``(en, fa, cls)``: the two visible words plus the pill class, so the
    runtime can recolour a status pill whose state changed. Anything else is the node's text
    content with tags stripped: a number, a timestamp, an absence glyph. Entities are decoded
    here because the runtime assigns ``textContent``, and the browser does not re-parse
    entities on assignment — the patch must carry the plain word.
    """
    match = _LANG_SPAN_PAIR.search(inner)
    if match:
        pill = _PILL_CLASS.search(opening_attrs)
        return (
            _unescape(match.group(1)),
            _unescape(match.group(2)),
            pill.group(1) if pill else "",
        )
    # A plain host: drop any tags left (an <svg> title, a bidi isolate) and keep the words.
    text = re.sub(r"<[^>]+>", "", inner)
    return _unescape(text.strip())


def _unescape(text: str) -> str:
    """Reverse :func:`theme.html` for the few entities it can produce.

    The runtime sets ``textContent`` — the browser does not decode entities on assignment —
    so a patch must carry the plain word (``Fuel & fan system``), not the escaped markup.
    """
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
    )


#: One anchored node, captured whole. The match starts at the node's own opening bracket so
#: its class attribute (where a pill carries ``dt-pill--ok``) is captured too, then runs to
#: the first ``</bdi>``/``</span>``/``</tspan>`` that follows the anchor attribute. For a
#: plain host that close is the host's own; for a bilingual pill (the anchor sits on the outer
#: span, its children open before any close) the match spans both language children.
_NODE = re.compile(
    r'<([a-z]+)([^>]*data-otk="([^"]+)"[^>]*)>([^<]*(?:<(?!/bdi>)[^<]*)*)</(?:bdi|span|tspan)>'
)


def _anchors(section_html: str) -> dict[str, tuple[str, ...] | str]:
    """Every anchored node in one rendered section, keyed by its playback anchor.

    Nested same-tag closes (a pill inside a pill) do not occur in the renderers' output; the
    goldens pin the markup shapes this reads.
    """
    found: dict[str, tuple[str, ...] | str] = {}
    for match in _NODE.finditer(section_html):
        opening, key, inner = match.group(2), match.group(3), match.group(4)
        found[key] = _anchor_text(opening, inner)
    return found


def _provider_of(state: Any) -> Any:
    """The state's underlying provider, through one layer of request wrappers.

    The OT document's state is an ``app._PresentationRequest`` (or ``_WhatIfRequest``) over
    the real :class:`~src.digital_twin.state.DashboardState`; those wrappers carry the state
    they wrap under ``_state``. Walk at most one level — the wrappers never nest deeper — and
    return ``None`` for a stub state with no provider to drive.
    """
    provider = getattr(state, "_provider", None)
    if provider is None:
        inner = getattr(state, "_state", None)
        if inner is not None:
            provider = getattr(inner, "_provider", None)
    return provider


def build_timeline(
    state: Any,
    *,
    render_view: Any,
    settings: Any,
    ticks: int = MAX_TICKS,
) -> dict[str, Any] | None:
    """Render the moving views once per tick and diff their anchored nodes.

    Returns the timeline as a JSON-ready mapping — ``{"step_minutes": …, "ticks": [{key:
    patch, …}, …]}`` — or ``None`` when the state cannot be advanced at all (a stub provider
    in a test, or a real-plant source with no simulated clock): the shell then embeds an empty
    timeline and the playback controls still render, their clock simply never moving — an
    honest absence, never a frozen clock pretending to run.

    ``render_view`` is the shared dispatch (``app.build_view_section``); calling it here
    means the timeline's every patch is the renderer's own output. ``ticks`` is bounded by
    :data:`MAX_TICKS` — a presentation demo moves at 1×–4× with one sample per beat, so
    45 samples is under two minutes of 1× playback, and the embedded JSON stays a fraction
    of the document (measured ~100 KB with all views diffed).
    """
    provider = _provider_of(state)
    if provider is None:
        return None
    position = getattr(provider, "position", None)
    step_minutes = _DEFAULT_STEP_MINUTES
    if callable(position):
        try:
            step_minutes = float(position().get("step_minutes", _DEFAULT_STEP_MINUTES))
        except Exception:  # noqa: BLE001 - a source with no position keeps the default step
            pass

    # The provider is returned to the timestamp it held on entry (see the module docstring).
    entry_stamp = _timestamp(provider)
    try:
        snapshots = _snapshots(state, render_view, settings, ticks, step_minutes, provider)
    finally:
        _restore(provider, entry_stamp)
    if not snapshots:
        return None

    timeline: list[dict[str, Any]] = []
    previous: dict[str, tuple[str, ...] | str] = {}
    for index, anchors in enumerate(snapshots):
        if index == 0:
            tick = dict(anchors)  # tick 0 ships whole: the baseline the runtime diffs against
        else:
            tick = {key: patch for key, patch in anchors.items() if previous.get(key) != patch}
        timeline.append(tick)
        previous = anchors
    return {"step_minutes": step_minutes, "ticks": timeline}


def _snapshots(
    state: Any,
    render_view: Any,
    settings: Any,
    ticks: int,
    step_minutes: float,
    provider: Any,
) -> list[dict[str, tuple[str, ...] | str]]:
    """One anchored-node snapshot per tick, advancing the provider between renders."""
    from src.digital_twin.provider import CapabilityError  # local: keeps the import lazy

    snapshots: list[dict[str, tuple[str, ...] | str]] = []
    budget = max(0, min(int(ticks), MAX_TICKS))
    for index in range(budget):
        if index > 0:
            try:
                provider.advance(minutes=step_minutes)
            except (CapabilityError, NotImplementedError, ValueError):
                break  # the source ran out of clock; ship what was collected
        try:
            snapshot = _snapshot(state, render_view, settings)
        except RuntimeError:
            if index == 0:
                raise  # the document itself would fail on this state; do not mask it
            break
        snapshots.append(snapshot)
    if len(snapshots) >= 2 and all(s == snapshots[0] for s in snapshots[1:]):
        return snapshots[:1]  # a clock that refuses to move: one frame, not sixty copies
    return snapshots


def _snapshot(
    state: Any, render_view: Any, settings: Any
) -> dict[str, tuple[str, ...] | str]:
    """The union of every timeline view's anchored nodes at the current instant.

    The shared ``stamp`` anchor is taken from view A only: every view stamps the same instant,
    and letting the last view win would leak view H's dataset-prefixed form (``kiln · …``)
    into panels that render the bare timestamp.
    """
    merged: dict[str, tuple[str, ...] | str] = {}
    for view_id in TIMELINE_VIEWS:
        _, section = render_view(state, view_id)
        view_anchors = _anchors(section)
        if view_id != TIMELINE_VIEWS[0]:
            view_anchors.pop(STAMP_KEY, None)
        merged.update(view_anchors)
    return merged


def _timestamp(provider: Any) -> Any:
    """The provider's current timestamp, or ``None`` when it reports none.

    Duck-typed on the method the synthetic provider owns; a stub without one has nothing to
    restore and nothing to read.
    """
    read = getattr(provider, "timestamp", None)
    if not callable(read):
        return None
    try:
        return read()
    except Exception:  # noqa: BLE001 - a source that cannot say, has nothing to restore
        return None


def _restore(provider: Any, entry_stamp: Any) -> None:
    """Return the provider to the position it held before the timeline was built.

    Reset and re-advance by the span the entry timestamp covers — the driver's own
    determinism (every step a pure function of configs, seed, regime and step count, its
    module docstring) makes the re-advanced state identical to the state that was left. A
    provider that reports no timestamp, or refuses the reset, is left as it is: the worst
    case is the document's initial panels showing the timeline's last tick, which is still
    an honest, renderer-produced frame.
    """
    if entry_stamp is None:
        return
    reset = getattr(provider, "reset", None)
    advance = getattr(provider, "advance", None)
    if not callable(reset) or not callable(advance):
        return
    try:
        reset()
        stamp = _timestamp(provider)
        if stamp is not None:
            import pandas as pd

            span = (pd.Timestamp(entry_stamp) - pd.Timestamp(stamp)).total_seconds() / 60.0
            if span > 0:
                advance(minutes=span)
    except Exception:  # noqa: BLE001 - restoration is best-effort, never a failed export
        pass


def timeline_json(timeline: Mapping[str, Any] | None) -> str:
    """The timeline as the ``var OT_TIMELINE = …;`` literal embedded in the shell's script.

    ``</`` is escaped so a value containing the sequence cannot close the ``<script>`` block
    (no renderer produces one today; the escape is the standing guard). ``None`  becomes an
    empty literal so the runtime's "no timeline" branch is a single falsy check.
    """
    import json

    if timeline is None:
        return "null"
    text = json.dumps(timeline, ensure_ascii=True, separators=(",", ":"))
    return text.replace("</", "<\\/")


__all__ = ["MAX_TICKS", "TIMELINE_VIEWS", "build_timeline", "timeline_json"]
