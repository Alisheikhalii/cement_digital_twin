"""Task #6 directive item 4 / AC-21: the animated SVG twin, pinned against regression.

``TASK6_RECOVERY_PLAN.md`` phase 6F records the twin as **IMPLEMENTED, NOT VERIFIED**: the plan
measured :func:`~src.visualization.svg_twin.twin_document` emitting ~23 KB of self-contained
animated HTML with zero UI dependencies installed, and no test pinned any of it. This file is that
pin. It preserves the twin rather than improving it - every assertion below is a property the
renderer already has, written down so a later change cannot quietly take it away.

Four properties, in the order the directive and the plan ask for them:

* **Determinism** - the same snapshot and equipment rendered twice are byte-identical. The twin
  takes payload objects, not a live provider, so nothing on this path can read a wall clock; the
  test states that as a checkable fact rather than as an inference from the imports.
* **SVG, not GIF** (directive item 4's own words) - the document carries an ``<svg>`` element and
  the three ``@keyframes`` that move it, and carries no raster image, no ``<img>``, no data URI, no
  external asset and no script. This is the rendering-technology decision of PRD 19.3 held as a
  test: a saved ``.html`` must animate in any browser with nothing loaded alongside it (NFR-9).
* **AC-21 parameter provenance** - every animation parameter is
  ``AnimationSettings.scale(pair, Value.fraction_of_range())`` for a ``pair`` read from
  ``configs/dashboard.yaml``. Proved twice over: *behaviourally*, by feeding two different states
  through the renderer and watching the emitted durations, widths and particle counts move; and
  *structurally*, through :func:`~src.visualization.svg_twin.animation_report`, which exposes the
  state -> animation layer as plain data and is exactly the surface the plan asks AC-21 to assert
  against. A tag absent from the payload must read stopped at its range's at-rest end, never at an
  invented speed (NFR-6).
* **Honesty labels** - the twin's own HTML carries the standing no-plant-connection statement, and
  carries neither the forbidden control wording (``labels.FORBIDDEN_CONTROL_LABEL``) nor the word
  "confidence" (FR-23: an ensemble spread is a width, never a confidence percentage).

Deliberately absent: any assertion about the hard-coded ``Synthetic Demonstration`` badge at
``svg_twin.py:530``. That is T1-06 site 2 and it is already held, correctly and bidirectionally, by
``tests/test_task6_provider_contract.py::test_the_animated_twin_badge_is_derived_from_the_providers_synthetic_flag``
as an ``xfail(strict=True)``. Restating it here would double-count one defect and make a phase-6D
fix flip two files instead of one.

Also deliberately absent: any engineering number. Every bound this file checks is read from
``configs/dashboard.yaml`` through :class:`~src.digital_twin.settings.DashboardSettings`, and every
process value is the midpoint of a :mod:`src.schema` range moved by a *fraction*, so the test states
no limit, no speed and no opacity of its own (NFR-6, AC-12).

Speed: the twin renders from payload objects, so this whole file runs against the ``stub_provider``
of ``tests/conftest.py`` and never builds a session, trains a model or touches a process model.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
from dataclasses import replace

import pytest

# =============================================================================
# Fractions of a documented range that the behavioural tests place a state at.
# Fractions, not values: the test may not hold an engineering number, and
# ``fraction_of_range()`` is the only input the animation layer reads anyway.
# =============================================================================
#: A low but *moving* state and a high one. Both are comfortably above
#: ``animation.min_rate_fraction`` (0.02 in the shipped config), so the difference the behavioural
#: test observes is the scaling, not one state being drawn stopped.
LOW_FRACTION = 0.20
HIGH_FRACTION = 0.90

#: The two ends of every configured range, used to check that ``scale`` reaches them exactly.
AT_REST_FRACTION = 0.0
FULL_FRACTION = 1.0

#: The three keyframes ``stylesheet()`` defines - a flowing dash, a turning rotor, a breathing glow.
#: Named rather than counted, so dropping one and adding another would still fail.
KEYFRAME_NAMES: tuple[str, ...] = ("dt-flow-move", "dt-spin", "dt-glow-pulse")

#: The three animated elements, as the ``class`` attributes the SVG actually emits. Spelled with the
#: attribute so a search cannot be satisfied by the *stylesheet*, which carries every one of these
#: names as a selector whether or not a single element is animated.
LIVE_CLASS_ATTRIBUTES: tuple[str, ...] = (
    'class="dt-flow dt-flow--live"',
    'class="dt-rotor"',
    'class="dt-glow dt-glow--pulse"',
)

#: Markup that would mean the twin is *not* a vector animation. ``.gif`` and ``image/gif`` are
#: directive item 4's own prohibition; the rest close the neighbouring escapes - a raster ``<img>``,
#: a base64 payload, an embedded video or canvas, or a script that would animate it imperatively
#: (and would not run from a saved file under a notebook's sanitizer anyway).
NON_VECTOR_MARKERS: tuple[str, ...] = (
    ".gif",
    "image/gif",
    "<img",
    "<picture",
    "<video",
    "<canvas",
    "<iframe",
    "<script",
    "data:image",
    "base64,",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    "background-image",
)

#: The one URL a self-contained SVG document must carry (the SVG namespace) and the one ``url()``
#: reference it may make (its own inlined gradient). Anything else would be an external asset.
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
INTERNAL_GRADIENT_REF = "url(#dt-glow-grad)"

#: FR-23 / PRD 13.1.1: an ensemble spread is a width in the target's own unit. The word below must
#: not appear on a screen, and the twin is a screen.
FORBIDDEN_WORD = "confidence"

#: The ``AnimationSettings`` fields that are ``(at_zero, at_full)`` output ranges - i.e. everything
#: :meth:`AnimationSettings.scale` may be handed. ``min_rate_fraction`` is a threshold, not a range,
#: and is checked separately.
ANIMATION_PAIR_FIELDS: tuple[str, ...] = (
    "flow_period_seconds",
    "particles",
    "flow_opacity",
    "rotation_period_seconds",
    "glow_opacity",
    "stroke_width",
)

#: Bare numbers the AST audit of the three state -> animation functions tolerates, and why. These are
#: *structural*, not animation magnitudes: ``1`` is "a stream needs at least one particle" in
#: :func:`flow_anim`, and ``0`` is the index of a pair's at-rest end in :func:`glow_anim`. Any other
#: literal in those functions would be an animation magnitude that bypassed the config.
STRUCTURAL_LITERALS: frozenset[float] = frozenset({0, 1})

#: The three functions PRD 19.4 makes the whole state -> animation contract, audited by AST below.
BINDING_FUNCTIONS: tuple[str, ...] = ("flow_anim", "glyph_anim", "glow_anim")

#: What to tell whoever breaks the byte-stability test, so a legitimate change to the twin is
#: cheap to land and an accidental one is not. A golden *hash* nobody can regenerate is a liability.
DETERMINISM_HINT = (
    "The animated twin is no longer byte-stable for identical inputs. This is a REGRESSION unless "
    "the twin was deliberately changed. If a wall clock, a random draw, an unordered iteration or "
    "an id() leaked onto the render path, fix that - the twin must render the same bytes for the "
    "same state (TASK6_RECOVERY_PLAN.md phase 6F). Nothing here needs regenerating: the test "
    "compares two renders made in this process, not against a stored golden file."
)


# =============================================================================
# Fixtures - payload objects, not a session (the twin takes the payload directly)
# =============================================================================
@pytest.fixture(scope="module")
def dashboard_settings():
    """``configs/dashboard.yaml`` as the renderer reads it (NFR-6: no bound is written here)."""
    from src.digital_twin.settings import DashboardSettings

    return DashboardSettings.from_config()


@pytest.fixture(scope="module")
def twin_payload(stub_provider_class_module):
    """One ``(snapshot, equipment)`` pair - exactly what :func:`render_twin` takes.

    Built from the Tier-1 stub, whose every value is the *midpoint* of that tag's documented
    :mod:`src.schema` range: ``fraction_of_range()`` is therefore exactly 0.5, which is the input
    the AC-21 scaling reads. Module-scoped and never mutated - the ``at_fraction`` helper below
    returns rebuilt copies rather than editing these.
    """
    provider = stub_provider_class_module()
    return provider.get_current_state(), provider.get_equipment_status()


@pytest.fixture(scope="module")
def stub_provider_class_module():
    """The stub provider *class*, module-scoped.

    ``conftest``'s ``stub_provider`` fixture is function-scoped on purpose (its instances count the
    contract calls they served, and those counters must not leak). Nothing in this file asserts on a
    call count, and every instance built here is thrown away after one read, so taking the cached
    class directly keeps the module's fixtures module-scoped without touching that contract.
    """
    from tests.conftest import stub_provider_class

    return stub_provider_class()


@pytest.fixture(scope="module")
def at_fraction():
    """``(snapshot, equipment, fraction) -> (snapshot, equipment)`` moved to that fraction of range.

    Every :class:`Value` is rebuilt at ``range_min + fraction * span`` of its *own* documented range,
    so the whole payload sits at one known ``fraction_of_range()`` and the animation layer's output
    is predictable from the config alone. A value with no documented range is left untouched - there
    is no honest way to place it, and :meth:`AnimationSettings.scale` already returns the at-rest end
    for it.
    """

    def move_value(value, fraction: float):
        if value is None or value.range_min is None or value.range_max is None:
            return value
        low, high = float(value.range_min), float(value.range_max)
        return replace(value, value=low + (high - low) * float(fraction))

    def move(snapshot, equipment, fraction: float):
        moved = replace(
            snapshot,
            values={tag: move_value(value, fraction) for tag, value in snapshot.values.items()},
        )
        drivers = tuple(replace(item, driver=move_value(item.driver, fraction)) for item in equipment)
        return moved, drivers

    return move


@pytest.fixture(scope="module")
def render(dashboard_settings):
    """``(snapshot, equipment, **kwargs) -> str`` - one standalone twin document.

    :func:`twin_document` rather than :func:`render_twin` because it is the widest surface: it
    inlines the theme stylesheet, the twin CSS and the SVG, which is what the factory demo of
    PRD 19.3/29 exports and therefore what has to be self-contained.
    """
    from src.visualization import svg_twin

    def build(snapshot, equipment, **kwargs):
        return svg_twin.twin_document(snapshot, equipment, settings=dashboard_settings, **kwargs)

    return build


@pytest.fixture(scope="module")
def report(dashboard_settings):
    """``(snapshot, equipment) -> dict`` - the state -> animation binding as plain data."""
    from src.visualization import svg_twin

    def build(snapshot, equipment):
        return svg_twin.animation_report(snapshot, equipment, dashboard_settings)

    return build


def _durations(markup: str) -> tuple[float, ...]:
    """Every ``animation-duration`` the document emits, in document order.

    Parsed rather than asserted structurally because this is the number a *browser* reads: it is the
    end of the pipeline the AC-21 chain has to survive, and a binding that computed correctly but
    printed a constant would pass every structural check and still animate a lie.
    """
    return tuple(float(match) for match in re.findall(r"animation-duration:([0-9.]+)s", markup))


def _stroke_widths(markup: str) -> tuple[float, ...]:
    return tuple(float(match) for match in re.findall(r"stroke-width:([0-9.]+)px", markup))


def _dash_arrays(markup: str) -> tuple[str, ...]:
    return tuple(re.findall(r"stroke-dasharray:([0-9. ]+);", markup))


# =============================================================================
# 1. Determinism (plan phase 6F: "byte-stable output for a fixed seed")
# =============================================================================
def test_the_twin_renders_the_same_bytes_twice_for_the_same_state(twin_payload, render):
    """The same snapshot rendered twice is byte-identical - no clock, no draw, no ordering drift.

    The twin takes a :class:`StateSnapshot` and a tuple of :class:`EquipmentStatus`, never a
    provider, so nothing on this path *can* read a wall clock: the snapshot's own ``timestamp`` is
    a string the provider already fixed. This test says so in bytes rather than by inspection, and
    is the one that would catch a future ``datetime.now()``, ``random`` or set-iteration leaking in.
    """
    snapshot, equipment = twin_payload

    first = render(snapshot, equipment)
    second = render(snapshot, equipment)

    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == (
        hashlib.sha256(second.encode("utf-8")).hexdigest()
    ), DETERMINISM_HINT
    assert first == second, DETERMINISM_HINT


def test_the_twin_is_deterministic_across_freshly_built_payloads(stub_provider_class_module, render):
    """Two independent reads of the same fixed source render the same bytes.

    Stronger than re-rendering one object: the payload is rebuilt from scratch, so an identity-keyed
    cache, a ``sorted`` over object ids, or a dict whose order followed construction would show up
    here and not above. The stub is fixed by construction (``STUB_TIMESTAMP``, midpoint values), so
    any difference is the renderer's.
    """
    first_provider = stub_provider_class_module()
    second_provider = stub_provider_class_module()

    first = render(first_provider.get_current_state(), first_provider.get_equipment_status())
    second = render(second_provider.get_current_state(), second_provider.get_equipment_status())

    assert first == second, DETERMINISM_HINT


def test_the_still_frame_and_the_animated_frame_are_each_deterministic(twin_payload, render):
    """``animate=False`` renders the same state as a still frame, and is stable too (PRD 19.4).

    Worth its own check because the paused branch is what a snapshot test or a paused clock uses,
    and it takes a different path through :func:`_flow_svg` / :func:`_rotor_svg` / :func:`_glow_svg`.
    """
    snapshot, equipment = twin_payload

    still = render(snapshot, equipment, animate=False)
    assert still == render(snapshot, equipment, animate=False), DETERMINISM_HINT
    # The still frame is genuinely a different rendering, not the same string relabelled.
    assert still != render(snapshot, equipment)


def test_no_wall_clock_or_random_source_is_imported_on_the_twins_render_path():
    """The renderer imports no non-deterministic source - stated as a fact about the module.

    Complements the byte-comparison above: that one proves *this* render is stable, this one proves
    there is no mechanism by which a later one could not be. ``svg_twin`` imports ``math.hypot`` and
    the payload/settings/theme layers, and nothing else.
    """
    from src.visualization import svg_twin

    source = inspect.getsource(svg_twin)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"random", "time", "datetime", "uuid", "secrets", "os"}
    assert not (imported & forbidden), (
        f"{svg_twin.__name__} imports {sorted(imported & forbidden)}: the twin must render from the "
        "snapshot it was handed, never from a wall clock or a random draw (AC-21)"
    )
    # And no direct call to one either, however it were reached.
    for pattern in (r"\bdatetime\.now\b", r"\btime\.time\b", r"\brandom\.", r"\bid\("):
        assert not re.search(pattern, source), pattern


# =============================================================================
# 2. SVG + @keyframes, and 3. not a GIF (directive item 4, PRD 19.3)
# =============================================================================
def test_the_document_carries_an_svg_element_and_the_three_keyframes(twin_payload, render):
    """PRD 19.3: the motion is vector geometry plus CSS keyframes, both inline in one file."""
    snapshot, equipment = twin_payload
    document = render(snapshot, equipment)

    assert "<svg" in document and "</svg>" in document
    assert f'xmlns="{SVG_NAMESPACE}"' in document
    assert "viewBox=" in document
    assert document.count("@keyframes") == len(KEYFRAME_NAMES)
    for name in KEYFRAME_NAMES:
        assert f"@keyframes {name}" in document, name
        assert f"animation-name:{name}" in document, name

    # The SVG is actually populated - paths, glyphs and terminals, not an empty canvas.
    assert "<path" in document and "<circle" in document and "<rect" in document and "<text" in document


def test_the_twin_is_vector_animation_and_not_a_prerecorded_raster(twin_payload, render):
    """Directive item 4, verbatim: **SVG, not GIF**.

    A GIF (or any raster) would be a prerecorded loop, which is precisely what AC-21 forbids: it
    could not be a function of the current state. The assertion is on the *rendered document* rather
    than on the source, so an image reaching the page through a label, a theme token or a future
    background would fail it too.
    """
    snapshot, equipment = twin_payload
    document = render(snapshot, equipment).lower()

    for marker in NON_VECTOR_MARKERS:
        assert marker not in document, (
            f"the animated twin emitted {marker!r}: directive item 4 requires SVG, not a "
            "prerecorded raster loop, and PRD 19.3 requires the saved file to animate with no "
            "assets loaded alongside it"
        )


def test_the_document_is_self_contained_with_no_external_asset(twin_payload, render):
    """NFR-9 / PRD 29: a saved ``.html`` animates in any browser with no server and no network.

    The only URL it may contain is the SVG namespace (a declaration, never fetched) and the only
    ``url()`` reference is its own inlined gradient.
    """
    snapshot, equipment = twin_payload
    document = render(snapshot, equipment)

    assert set(re.findall(r"https?://[^\"'\s)>]+", document)) == {SVG_NAMESPACE}
    assert set(re.findall(r"url\([^)]*\)", document)) == {INTERNAL_GRADIENT_REF}
    assert "<defs>" in document and 'id="dt-glow-grad"' in document
    for attribute in ("src=", "href=", "@import", "<link"):
        assert attribute not in document, attribute

    # Everything the page needs is inlined: both stylesheets, and a complete document around them.
    assert document.startswith("<!doctype html>")
    assert document.count("<style>") == 2  # theme tokens + the twin's scoped CSS
    assert "</html>" in document


def test_the_motion_survives_a_reduced_motion_preference_as_a_stated_choice(twin_payload, render):
    """The CSS honours ``prefers-reduced-motion`` - an accessibility fact worth not losing silently."""
    snapshot, equipment = twin_payload
    document = render(snapshot, equipment)

    assert "@media (prefers-reduced-motion: reduce)" in document
    assert "animation:none" in document


# =============================================================================
# 4. AC-21 - behavioural: varying the data varies the animation
# =============================================================================
def test_a_faster_state_visibly_animates_faster_in_the_emitted_markup(
    twin_payload, at_fraction, render
):
    """AC-21 end to end: the numbers a browser reads move when the *state* moves.

    Two renders of the same plant at two different points of its documented range. The durations
    must all fall (the configured ``flow_period_seconds`` / ``rotation_period_seconds`` pairs run
    high-to-low: a faster stream has a shorter dash cycle), and the strokes must all thicken. This
    is the assertion that a prerecorded loop, or a hard-coded duration, could not pass.
    """
    snapshot, equipment = twin_payload
    slow = render(*at_fraction(snapshot, equipment, LOW_FRACTION))
    fast = render(*at_fraction(snapshot, equipment, HIGH_FRACTION))

    assert slow != fast

    slow_durations, fast_durations = _durations(slow), _durations(fast)
    assert slow_durations and len(slow_durations) == len(fast_durations)
    assert all(f < s for s, f in zip(slow_durations, fast_durations)), (
        "every animation duration must shorten as the state rises through its documented range "
        f"(AC-21): {slow_durations} -> {fast_durations}"
    )

    slow_widths, fast_widths = _stroke_widths(slow), _stroke_widths(fast)
    assert slow_widths and len(slow_widths) == len(fast_widths)
    assert all(f >= s for s, f in zip(slow_widths, fast_widths))
    assert any(f > s for s, f in zip(slow_widths, fast_widths))

    # Particle spacing is a function of the same fraction, so the dash patterns differ too.
    assert _dash_arrays(slow) != _dash_arrays(fast)


def test_the_animation_parameters_reach_exactly_the_configured_ends_of_their_ranges(
    twin_payload, at_fraction, report, dashboard_settings
):
    """AC-21 traced to its source: at 0 % and 100 % of range, every parameter *is* the config number.

    This is the strongest available statement that no animation magnitude is hard-coded in
    ``svg_twin.py``: the values the twin computes at the two ends of a state's range are the two
    ends of the ``configs/dashboard.yaml`` pairs, to the float. Change the YAML and these move; a
    literal in the renderer could not track it.
    """
    animation = dashboard_settings.animation
    snapshot, equipment = twin_payload

    at_rest = report(*at_fraction(snapshot, equipment, AT_REST_FRACTION))
    at_full = report(*at_fraction(snapshot, equipment, FULL_FRACTION))

    for flow in at_rest["flows"]:
        if flow["fraction"] is None:  # an unranged tag has no fraction to place
            continue
        assert flow["period_s"] == pytest.approx(animation.flow_period_seconds[0]), flow["flow"]
        assert flow["opacity"] == pytest.approx(animation.flow_opacity[0]), flow["flow"]
        assert flow["width"] == pytest.approx(animation.stroke_width[0]), flow["flow"]
        assert flow["particles"] == round(animation.particles[0]), flow["flow"]

    for flow in at_full["flows"]:
        if flow["fraction"] is None:
            continue
        assert flow["period_s"] == pytest.approx(animation.flow_period_seconds[1]), flow["flow"]
        assert flow["opacity"] == pytest.approx(animation.flow_opacity[1]), flow["flow"]
        assert flow["width"] == pytest.approx(animation.stroke_width[1]), flow["flow"]
        assert flow["particles"] == round(animation.particles[1]), flow["flow"]

    for item in at_full["equipment"]:
        if item["fraction"] is None:
            continue
        assert item["rotation_period_s"] == pytest.approx(
            animation.rotation_period_seconds[1]
        ), item["name"]
        if "glow" in item and item["glow"]["fraction"] is not None:
            assert item["glow"]["opacity"] == pytest.approx(animation.glow_opacity[1]), item["name"]


def test_changing_only_the_configured_bounds_changes_only_the_animation(
    twin_payload, dashboard_settings, at_fraction
):
    """The tunable bounds come from configuration, not from numbers inside ``svg_twin.py``.

    The complement of the test above, run from the other side: hold the *state* fixed and move the
    ``AnimationSettings`` pair. Every emitted duration must scale with it. A literal in the renderer
    would leave the output unchanged.
    """
    from src.visualization import svg_twin

    snapshot, equipment = at_fraction(*twin_payload, HIGH_FRACTION)
    base = dashboard_settings.animation
    doubled = replace(
        base,
        flow_period_seconds=(base.flow_period_seconds[0] * 2.0, base.flow_period_seconds[1] * 2.0),
        rotation_period_seconds=(
            base.rotation_period_seconds[0] * 2.0,
            base.rotation_period_seconds[1] * 2.0,
        ),
    )

    original = svg_twin.render_twin(snapshot, equipment, settings=dashboard_settings)
    slowed = svg_twin.render_twin(
        snapshot, equipment, settings=replace(dashboard_settings, animation=doubled)
    )

    before, after = _durations(original), _durations(slowed)
    assert before and len(before) == len(after)
    assert all(b * 2.0 == pytest.approx(a) for b, a in zip(before, after)), (
        "doubling the configured period pairs must double every emitted duration - if it does not, "
        "an animation magnitude is hard-coded in svg_twin.py rather than read from "
        "configs/dashboard.yaml (AC-21, NFR-6)"
    )


def test_a_missing_reading_is_drawn_stopped_rather_than_at_an_invented_speed(
    twin_payload, dashboard_settings, report
):
    """NFR-6 through the animation: a tag absent from the payload animates nothing.

    :meth:`AnimationSettings.scale` returns the at-rest end for a ``None`` fraction and
    :meth:`AnimationSettings.moving` is false, so the stream is emitted as a faint idle line - still
    state-scaled, but not moving. Fabricating a default speed for a reading nobody has is exactly
    the dishonesty the directive's "nothing is animated on a made-up basis" forbids.
    """
    from src.digital_twin import layout
    from src.visualization import svg_twin

    animation = dashboard_settings.animation
    snapshot, equipment = twin_payload
    dropped = layout.FLOWS[0].rate_tag
    stripped = replace(
        snapshot, values={tag: v for tag, v in snapshot.values.items() if tag != dropped}
    )

    rows = [row for row in report(stripped, equipment)["flows"] if row["rate_tag"] == dropped]
    assert rows, dropped
    for row in rows:
        assert row["fraction"] is None
        assert row["moving"] is False
        assert row["status"] == "UNKNOWN"
        assert row["period_s"] == pytest.approx(animation.flow_period_seconds[0])
        assert row["opacity"] == pytest.approx(animation.flow_opacity[0])
        assert row["width"] == pytest.approx(animation.stroke_width[0])

    # ...and the markup agrees: the stopped streams are idle paths carrying no animation at all.
    markup = svg_twin.render_twin(stripped, equipment, settings=dashboard_settings)
    assert markup.count("dt-flow--idle") == len(rows)
    assert len(_durations(markup)) < len(
        _durations(svg_twin.render_twin(snapshot, equipment, settings=dashboard_settings))
    )


def test_a_glyph_with_no_driver_is_drawn_still_and_says_so(twin_payload, dashboard_settings, report):
    """An equipment item whose driving reading is absent does not spin (directive item 4, NFR-6)."""
    from src.visualization import svg_twin

    snapshot, equipment = twin_payload
    blinded = tuple(replace(item, driver=None) for item in equipment)

    for row in report(snapshot, blinded)["equipment"]:
        assert row["fraction"] is None, row["name"]
        assert row["rotating"] is False, row["name"]
        assert row["status"] == "UNKNOWN", row["name"]
        assert row["rotation_period_s"] == pytest.approx(
            dashboard_settings.animation.rotation_period_seconds[0]
        ), row["name"]

    markup = svg_twin.render_twin(snapshot, blinded, settings=dashboard_settings)
    assert 'class="dt-rotor"' not in markup
    assert svg_twin.theme.NO_VALUE_TEXT in markup  # the reading is stated absent, not zeroed


def test_the_still_frame_withholds_motion_but_keeps_every_state_scaled_value(
    twin_payload, at_fraction, render
):
    """``animate=False`` (PRD 19.4): the same state, drawn as one frame - widths and glows intact."""
    snapshot, equipment = at_fraction(*twin_payload, HIGH_FRACTION)

    still = render(snapshot, equipment, animate=False)
    moving = render(snapshot, equipment, animate=True)

    assert _durations(still) == ()
    # Matched as emitted class *attributes*: the stylesheet always carries the selectors, so a bare
    # substring search would only ever be finding the CSS rule rather than an animated element.
    for element in LIVE_CLASS_ATTRIBUTES:
        assert element not in still, element
        assert element in moving, element
    # The keyframes are still defined (the stylesheet is one object) but nothing references them.
    assert still.count("@keyframes") == len(KEYFRAME_NAMES)
    # State scaling survives: the widths are identical to the animated frame's.
    assert _stroke_widths(still) == _stroke_widths(moving)


def test_a_hot_zone_glows_brighter_without_changing_how_fast_the_kiln_turns(
    twin_payload, report, dashboard_settings
):
    """Each animated element reads *its own* tag - the glow follows temperature, not kiln speed.

    ``GLOW_SOURCES`` binds the kiln's glow to ``burning_zone_temperature`` and the precalciner's to
    ``calciner_temperature``, while the kiln's *rotation* follows its own ``kiln_speed_rpm`` driver.
    Raising only the temperature must move only the glow: a single shared "activity" number driving
    everything would fail this, and would not be the state-bound animation AC-21 asks for.
    """
    from src.visualization import svg_twin

    snapshot, equipment = twin_payload
    glow_tag = svg_twin.GLOW_SOURCES["RotaryKiln"]
    hot_value = snapshot.values[glow_tag]
    low, high = float(hot_value.range_min), float(hot_value.range_max)
    hotter = replace(
        snapshot,
        values={
            **snapshot.values,
            glow_tag: replace(hot_value, value=low + (high - low) * HIGH_FRACTION),
        },
    )

    before = {row["name"]: row for row in report(snapshot, equipment)["equipment"]}
    after = {row["name"]: row for row in report(hotter, equipment)["equipment"]}

    assert after["RotaryKiln"]["glow"]["opacity"] > before["RotaryKiln"]["glow"]["opacity"]
    assert after["RotaryKiln"]["glow"]["pulse_period_s"] < before["RotaryKiln"]["glow"]["pulse_period_s"]
    assert after["RotaryKiln"]["rotation_period_s"] == before["RotaryKiln"]["rotation_period_s"]
    # And nothing else on the diagram moved.
    assert after["Precalciner"]["glow"] == before["Precalciner"]["glow"]
    assert all(
        after[name]["rotation_period_s"] == before[name]["rotation_period_s"] for name in before
    )


# =============================================================================
# 5. AC-21 - structural: animation_report is the traceability surface
# =============================================================================
def test_the_animation_report_covers_every_stream_and_every_component(twin_payload, report):
    """The report is the audit surface, so it has to be exhaustive or the audit means nothing."""
    from src.digital_twin import layout
    from src.visualization import svg_twin

    snapshot, equipment = twin_payload
    data = report(snapshot, equipment)

    assert [row["flow"] for row in data["flows"]] == [flow.name for flow in layout.FLOWS]
    assert [row["rate_tag"] for row in data["flows"]] == [flow.rate_tag for flow in layout.FLOWS]
    assert [row["name"] for row in data["equipment"]] == [item.name for item in equipment]
    assert data["viewBox"] == [0.0, 0.0, svg_twin.VIEWBOX_W, svg_twin.VIEWBOX_H]

    # Every stream names a real schema tag, so nothing is animated against an invented quantity.
    from src import schema

    for row in data["flows"]:
        assert schema.has_tag(row["rate_tag"]), row["flow"]

    # Every glow names the tag that lights it, and only combustion glyphs carry one.
    glowing = {row["name"] for row in data["equipment"] if "glow" in row}
    assert glowing == set(svg_twin.GLOW_SOURCES)
    for row in data["equipment"]:
        if "glow" in row:
            assert row["glow"]["source"] == svg_twin.GLOW_SOURCES[row["name"]]


def test_every_reported_animation_parameter_equals_scale_of_the_configured_pair(
    twin_payload, at_fraction, report, dashboard_settings
):
    """AC-21 stated exactly: parameter == ``scale(pair, fraction_of_range())``, recomputed here.

    The report's numbers are recomputed independently from the config pair and the reported
    fraction, so nothing in the assertion borrows the renderer's own arithmetic. If any parameter
    were a literal, a clamp of its own, or a second scaling rule, this equality would break.
    """
    from src.digital_twin.settings import AnimationSettings

    animation = dashboard_settings.animation
    snapshot, equipment = at_fraction(*twin_payload, LOW_FRACTION)
    data = report(snapshot, equipment)
    checked = 0

    for row in data["flows"]:
        fraction = row["fraction"]
        assert row["period_s"] == pytest.approx(
            AnimationSettings.scale(animation.flow_period_seconds, fraction)
        ), row["flow"]
        assert row["opacity"] == pytest.approx(
            AnimationSettings.scale(animation.flow_opacity, fraction)
        ), row["flow"]
        assert row["width"] == pytest.approx(
            AnimationSettings.scale(animation.stroke_width, fraction)
        ), row["flow"]
        assert row["particles"] == max(
            1, round(AnimationSettings.scale(animation.particles, fraction))
        ), row["flow"]
        assert row["moving"] is animation.moving(fraction), row["flow"]
        checked += 1

    for row in data["equipment"]:
        fraction = row["fraction"]
        assert row["rotation_period_s"] == pytest.approx(
            AnimationSettings.scale(animation.rotation_period_seconds, fraction)
        ), row["name"]
        assert row["rotating"] is (row["rotor"] and animation.moving(fraction)), row["name"]
        if "glow" in row:
            glow = row["glow"]
            assert glow["opacity"] == pytest.approx(
                AnimationSettings.scale(animation.glow_opacity, glow["fraction"])
            ), row["name"]
            assert glow["pulse_period_s"] == pytest.approx(
                AnimationSettings.scale(animation.flow_period_seconds, glow["fraction"])
            ), row["name"]
        checked += 1

    assert checked == len(data["flows"]) + len(data["equipment"]) > 0


def test_the_state_to_animation_functions_hold_no_animation_magnitude_of_their_own():
    """The AST audit the module docstring promises: no bare animation number in the binding layer.

    :func:`flow_anim`, :func:`glyph_anim` and :func:`glow_anim` are the only route from state to an
    animation parameter. Every numeric constant in them must be *structural* - at least one particle,
    the index of a pair's at-rest end - and every magnitude must arrive through
    ``AnimationSettings.scale`` of a named ``AnimationSettings`` field. This is the no-hard-coding
    audit (NFR-6, AC-12) extended to the animation path, which is what AC-21 adds.
    """
    from src.visualization import svg_twin

    tree = ast.parse(inspect.getsource(svg_twin))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in BINDING_FUNCTIONS
    }
    assert set(functions) == set(BINDING_FUNCTIONS)

    scaled_fields: set[str] = set()
    for name, node in functions.items():
        for constant in ast.walk(node):
            if isinstance(constant, ast.Constant) and isinstance(constant.value, (int, float)):
                if isinstance(constant.value, bool):
                    continue
                assert constant.value in STRUCTURAL_LITERALS, (
                    f"{name} holds the literal {constant.value!r}: an animation magnitude must come "
                    "from configs/dashboard.yaml through AnimationSettings.scale, and the only bare "
                    f"numbers allowed here are structural {sorted(STRUCTURAL_LITERALS)} (AC-21)"
                )
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "scale"
            ):
                pair = call.args[0]
                assert isinstance(pair, ast.Attribute), f"{name}: {ast.unparse(pair)}"
                assert pair.attr in ANIMATION_PAIR_FIELDS, f"{name}: {pair.attr}"
                scaled_fields.add(pair.attr)

    # Every configured output range is actually consumed - a pair nobody reads is a dead promise.
    assert scaled_fields == set(ANIMATION_PAIR_FIELDS)


def test_the_scoped_stylesheet_defines_no_duration_colour_or_size_of_its_own():
    """The CSS carries the *shape* of the motion; every magnitude arrives inline from the state.

    A duration in the stylesheet would be a hard-coded animation parameter that no state could move,
    and a hex colour would bypass the theme's single home for a token (NFR-6/AC-12).
    """
    from src.visualization import svg_twin

    css = svg_twin.stylesheet()

    assert "animation-duration" not in css
    assert "animation-delay" not in css
    assert not re.findall(r":\s*[0-9.]+m?s\b", css), "a duration in the CSS is a hard-coded parameter"
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css), "colours come from theme var(--dt-*)"
    # What it does define: the three keyframes and the animation *shape*.
    for name in KEYFRAME_NAMES:
        assert f"@keyframes {name}" in css
    assert "animation-iteration-count:infinite" in css
    assert "var(--dt-" in css


def test_the_only_bare_numbers_in_the_renderer_are_geometry_and_they_are_exported():
    """PRD 19.3: canvas coordinates are a *drawing* fact, declared once and named.

    The module argues that geometry belongs in code, like the theme's colours - so the audit's job
    here is to check the story holds: the canvas is module-level, ``Final``, and part of the public
    surface, rather than a magic number buried in a format string.
    """
    from src.visualization import svg_twin

    assert svg_twin.VIEWBOX_W > 0 and svg_twin.VIEWBOX_H > 0
    assert "VIEWBOX_W" in svg_twin.__all__ and "VIEWBOX_H" in svg_twin.__all__
    assert "animation_report" in svg_twin.__all__  # the AC-21 surface is public, not incidental
    # layout.py carries no coordinate: a viewBox position is a rendering fact, not a process one.
    from src.digital_twin import layout

    assert not [name for name in dir(layout) if "VIEWBOX" in name or name.endswith("_XY")]


# =============================================================================
# 6. Honesty labels survive rendering (item 20; labels.py)
# =============================================================================
def test_the_twin_carries_the_standing_no_plant_connection_statement(
    twin_payload, render, dashboard_settings
):
    """``svg_twin.py:571``: the banner is part of the twin, not of the page that embeds it.

    It has to survive every render path, because :func:`twin_document` is what gets *saved and sent*
    for the factory demo - the copy most likely to be read without the dashboard around it.
    """
    from src import labels
    from src.visualization import svg_twin

    snapshot, equipment = twin_payload
    for markup in (
        render(snapshot, equipment),
        render(snapshot, equipment, animate=False),
        svg_twin.twin_html(snapshot, equipment, settings=dashboard_settings),
    ):
        assert labels.NO_PLANT_CONNECTION_STATEMENT in markup
        assert "dt-banner" in markup


def test_the_twin_never_uses_control_language_or_a_confidence_number(twin_payload, render):
    """FR-16 / PRD 30 and FR-23: no ``Automatic Control Command``, and no "confidence" anywhere.

    Checked on the rendered document rather than the source, so wording reaching the page through a
    label, a tag description or an equipment state word is covered too.
    """
    from src import labels

    snapshot, equipment = twin_payload
    for markup in (render(snapshot, equipment), render(snapshot, equipment, animate=False)):
        assert labels.FORBIDDEN_CONTROL_LABEL not in markup
        assert FORBIDDEN_WORD not in markup.lower()
        for phrase in ("automatic control", "setpoint written", "controls the plant"):
            assert phrase not in markup.lower(), phrase


def test_every_glyph_states_its_component_its_state_word_and_its_live_reading(twin_payload, render):
    """Directive item 4's "equipment state changes": each glyph shows a vocabulary state word.

    The state word comes from :data:`labels.EQUIPMENT_STATE_VALUES` - a reading of quantities the
    simulation already produces - so a screen cannot invent a fifth condition for a machine.
    """
    from src import labels
    from src.digital_twin import layout
    from src.visualization import theme

    snapshot, equipment = twin_payload
    document = render(snapshot, equipment)

    for item in equipment:
        spec = layout.equipment_spec(item.name)
        # Compared in its escaped form: ``_glyph_svg`` writes ``theme.html(spec.title)``, so
        # "Fuel & fan system" reaches the page as "Fuel &amp; fan system". Asserting on the raw
        # title would be asserting that the renderer *fails* to escape.
        assert theme.html(spec.title) in document, item.name
        assert item.state in labels.EQUIPMENT_STATE_VALUES, item.name
    assert any(state in document for state in labels.EQUIPMENT_STATE_VALUES)

    # And the six stream boundaries are drawn and labelled, so nothing enters from nowhere.
    for node in layout.boundary_nodes():
        assert theme.html(node) in document, node


def test_the_document_titles_itself_with_the_full_system_label(twin_payload, render):
    """The exported file names what it is in its own ``<title>`` (AC-11 identity, PRD 29)."""
    from src import labels

    snapshot, equipment = twin_payload
    document = render(snapshot, equipment)

    assert f"<title>{labels.full_system_label()}" in document.replace("&#x27;", "'").replace(
        "&amp;", "&"
    ) or labels.SYSTEM_NAME in document
    assert labels.SYSTEM_NAME in document
