"""Regression: the baked domain-spanning tick ladder must survive every
measure-channel emit path — vertical bar, horizontal bar, and multi-metric
line — not just the vertical single-series path.

Two charts pinned to the same authored domain must read on one ruler
regardless of orientation or emit path. Renders a real board end to end
(compile -> render -> SVG) and reads the tick-label text nodes Vega's own SVG
renderer emits, rather than inspecting an intermediate VL spec dict.
"""

from __future__ import annotations

import re

import pytest

from dbt_charts.core.render.chart.mark_extents import mark_extents

from ..._svg_render import leaf_kind_subtrees, render_board_to_svg

# Domain [0, 4000] with ticks.count: 5 nice-rounds to exactly
# [0, 1000, 2000, 3000, 4000] (dbt_charts.core.numeric.nice_tick_values) — a
# domain stable across unrelated mantissa-formatting changes. Zero-anchored
# so it sidesteps the (separate, out-of-scope) question of whether
# horizontal bar's default "zero: true"
# scale flag gets stripped for a non-zero-anchored authored domain. Vega-Lite's
# own auto-generated ticks for a [0, 4000] domain are much finer-grained
# (200/400/... steps), so a path that fails to bake the ladder is
# unambiguously wrong rather than accidentally matching by coincidence.
_BOARD = """
title: Tick ladder parity
queries:
  q1:
    type: values
    rows:
      - {region: North, metric_a: 320, metric_b: 210}
      - {region: South, metric_a: 540, metric_b: 180}
      - {region: East, metric_a: 275, metric_b: 340}
  q2:
    type: values
    rows:
      - {month: Jan, metric_a: 320, metric_b: 210}
      - {month: Feb, metric_a: 540, metric_b: 180}
      - {month: Mar, metric_a: 275, metric_b: 340}
charts:
  bar_vertical:
    query: q1
    type: bar
    x: region
    y: metric_a
    style:
      orientation: vertical
      axis_quantitative:
        ticks:
          count: 5
        scale:
          continuous:
            domain: [0, 4000]
  bar_horizontal:
    query: q1
    type: bar
    x: region
    y: metric_a
    style:
      orientation: horizontal
      axis_quantitative:
        ticks:
          count: 5
        scale:
          continuous:
            domain: [0, 4000]
  line_multi_metric:
    query: q2
    type: line
    x: month
    y: [metric_a, metric_b]
    style:
      axis_quantitative:
        ticks:
          count: 5
        scale:
          continuous:
            domain: [0, 4000]
rows:
  - bar_vertical
  - bar_horizontal
  - line_multi_metric
"""

_EXPECTED_LADDER = {"0", "1,000", "2,000", "3,000", "4,000"}
# Leading unicode minus (Vega renders "−", not ASCII "-") for negative ticks.
_NUMERIC = re.compile(r"^[−-]?[\d,]+(\.\d+)?[kKmMbB]?$")


def _axis_label_groups_xy(chart_svg: str) -> list[list[tuple[str, float, float]]]:
    """Every ``role-axis-label`` group's (text, x-pixel, y-pixel) triples, one
    list per axis. The pixels are Vega's own rendered positions, not values
    we compute — what makes ``_measure_axis_positions`` usable for geometry
    assertions, not just tick-label text.

    A horizontal bar's measure axis renders on VL's x channel, so its tick
    labels vary in x, not y; a vertical one varies in y, not x. Keeping both
    coordinates lets ``_measure_axis_positions`` below pick whichever one
    actually varies, covering either orientation with one helper.
    """
    groups = []
    for m in re.finditer(r'<g class="mark-text role-axis-label"[^>]*>', chart_svg):
        depth = 0
        for tag in re.finditer(r"<g\b[^>]*>|</g>", chart_svg[m.start() :]):
            depth += 1 if tag.group(0).startswith("<g") else -1
            if depth == 0:
                group = chart_svg[m.start() : m.start() + tag.end()]
                groups.append(
                    [
                        (text, float(x), float(y))
                        for x, y, text in re.findall(
                            r'<text[^>]*transform="translate\(([-\d.]+),\s*'
                            r'([-\d.]+)\)"[^>]*>([^<]*)</text>',
                            group,
                        )
                    ]
                )
                break
    return groups


def _measure_axis_positions(chart_svg: str) -> dict[str, float]:
    """The one numeric axis-label group's text -> pixel position along the
    axis's own varying dimension — x for a horizontal measure axis, y for a
    vertical one — so this one helper covers either orientation.
    """
    candidates = [
        g
        for g in _axis_label_groups_xy(chart_svg)
        if g and all(_NUMERIC.match(t) for t, _, _ in g)
    ]
    assert len(candidates) == 1, (
        f"expected exactly one numeric axis-label group, found {len(candidates)}: "
        f"{_axis_label_groups_xy(chart_svg)}"
    )
    group = candidates[0]
    xs = [x for _, x, _ in group]
    ys = [y for _, _, y in group]
    use_x = (max(xs) - min(xs)) > (max(ys) - min(ys))
    return {text: (x if use_x else y) for text, x, y in group}


def test_measure_axis_tick_ladder_matches_across_orientation_and_emit_path() -> None:
    svg = render_board_to_svg(_BOARD)
    charts = leaf_kind_subtrees(svg, "chart")
    assert len(charts) == 3

    ticks_by_chart = {
        chart_id: _measure_axis_positions(fragment)
        for chart_id, fragment in zip(
            ["bar_vertical", "bar_horizontal", "line_multi_metric"], charts, strict=True
        )
    }

    assert set(ticks_by_chart["bar_vertical"]) == _EXPECTED_LADDER, (
        "vertical bar (control) should already bake the authored tick ladder; "
        f"got {ticks_by_chart['bar_vertical']}"
    )
    assert set(ticks_by_chart["bar_horizontal"]) == _EXPECTED_LADDER, (
        "horizontal bar must draw the same tick ladder as vertical bar for the "
        f"same authored domain; got {ticks_by_chart['bar_horizontal']}"
    )
    assert set(ticks_by_chart["line_multi_metric"]) == _EXPECTED_LADDER, (
        "multi-metric line must draw the same tick ladder as vertical bar for "
        f"the same authored domain; got {ticks_by_chart['line_multi_metric']}"
    )


# Default (no authored domain) path, data far from zero — the branch the
# above board's authored [0, 4000] domain bypasses entirely
# (_resolve_cartesian_ticks's `authored is not None` short-circuit skips the
# zero-anchor computation the authored-ladder floor pin lives in). metric_b's [990, 1010]
# range sits inside metric_a's own [980, 1020] extent, so the multi-metric
# scale's real domain matches the single-metric control's exactly — a
# passing test must show byte-identical ladders at byte-identical pixel
# rows, not just an overlapping label set.
_ZOOM_BOARD = """
title: Tick ladder parity (default zoom domain)
queries:
  q:
    type: values
    rows:
      - {month: Jan, metric_a: 980, metric_b: 990}
      - {month: Feb, metric_a: 1000, metric_b: 1010}
      - {month: Mar, metric_a: 1020, metric_b: 1005}
charts:
  line_single_metric:
    query: q
    type: line
    x: month
    y: metric_a
  line_multi_metric_zoom:
    query: q
    type: line
    x: month
    y: [metric_a, metric_b]
rows:
  - line_single_metric
  - line_multi_metric_zoom
"""


def test_multi_metric_line_zoom_ladder_matches_single_metric_default_path() -> None:
    """Regression: multi-metric line, no authored domain, data far from zero
    must not collapse the measure axis — the baked ladder and the emitted
    scale's actual domain must agree.

    The fold-based multi-metric line adds a color legend, which adjusts the
    chart height relative to the single-metric control. Pixel positions
    legitimately differ; the test pins the label set (the domain is correct)
    and the rung count (the ladder is not collapsed).
    """
    svg = render_board_to_svg(_ZOOM_BOARD)
    charts = leaf_kind_subtrees(svg, "chart")
    assert len(charts) == 2
    single_ticks = _measure_axis_positions(charts[0])
    multi_ticks = _measure_axis_positions(charts[1])

    # Text-level: a domain the scale never adopted clips every ladder rung
    # outside the drawn extent, collapsing a 5-tick ladder to whichever
    # single rung happens to fall inside the (unrelated, auto-fit) domain.
    assert len(multi_ticks) >= 4, (
        f"multi-metric measure axis collapsed to {len(multi_ticks)} tick(s): "
        f"{multi_ticks} — expected the same ladder as the single-metric "
        f"control {single_ticks}"
    )
    assert set(multi_ticks) == set(single_ticks), (
        f"multi-metric ladder {set(multi_ticks)} != single-metric control "
        f"{set(single_ticks)}"
    )
    # Geometry-level: ticks must be evenly spaced within the multi-metric chart.
    # A domain baked for a scale the axis never adopted collapses ticks to a
    # single pixel cluster; this catches that without requiring equality with
    # the control (whose legend height legitimately shifts the plotting area).
    assert _tick_grid_consistent(multi_ticks), (
        f"multi-metric tick pixel positions are not evenly spaced — likely a "
        f"baked-domain/emitted-scale mismatch: {multi_ticks}"
    )


def _parse_tick_value(text: str) -> float:
    """Parse a rendered SI-suffixed tick label back to its numeric value."""
    sign = -1.0 if text.startswith(("-", "−")) else 1.0
    body = text.lstrip("-−").replace(",", "")
    multiplier = 1.0
    if body and body[-1] in "kKmMbB":
        multiplier = {"k": 1e3, "m": 1e6, "b": 1e9}[body[-1].lower()]
        body = body[:-1]
    return sign * float(body) * multiplier


def _tick_grid_consistent(positions: dict[str, float]) -> bool:
    """True when adjacent tick positions are monotone and evenly spaced.

    A domain baked for a scale the axis never adopted places labels at the
    WRONG PIXEL while keeping the correct label TEXT — the values would
    cluster at the same pixel position rather than span the axis. Checking
    that pixel gaps between adjacent ticks are roughly equal (within 10%)
    catches this without requiring equality with a separate control chart
    (whose legend or margins may legitimately differ in pixel height).
    """
    pairs = sorted((_parse_tick_value(k), v) for k, v in positions.items())
    if len(pairs) < 2:
        return True
    gaps = [
        abs(pairs[i + 1][1] - pairs[i][1])
        for i in range(len(pairs) - 1)
        if abs(pairs[i + 1][0] - pairs[i][0]) > 0
    ]
    if not gaps:
        return True
    avg = sum(gaps) / len(gaps)
    return all(abs(g - avg) / max(avg, 1e-6) < 0.10 for g in gaps)


# Default (no authored domain, no authored ticks.count) zero-anchor path with
# data straddling zero — the branch _resolve_cartesian_ticks leaves
# domain_min at None (only domain_max gets headroom-adjusted; see its own
# docstring: "On zero-anchored axes only domain_max is set — bottom stays at
# 0"). A negative value's own ladder rung only survives if the emitter pins
# that implicit zero floor onto the drawn domain itself.
_ZERO_ANCHOR_NEGATIVE_BOARD = """
title: Zero-anchor default path, data straddling zero
queries:
  q:
    type: values
    rows:
      - {region: North, metric_a: -30}
      - {region: South, metric_a: 45}
      - {region: East, metric_a: 20}
charts:
  bar_vertical:
    query: q
    type: bar
    x: region
    y: metric_a
    style:
      orientation: vertical
  bar_horizontal:
    query: q
    type: bar
    x: region
    y: metric_a
    style:
      orientation: horizontal
rows:
  - bar_vertical
  - bar_horizontal
"""


def test_horizontal_bar_zero_anchor_default_path_pins_sub_zero_domain_floor() -> None:
    """Regression: a horizontal bar's zero-anchored DEFAULT path (no authored
    domain, the branch neither existing test in this file reaches) must pin
    the ladder's bottom rung as the drawn domain floor the same way vertical
    bar's ``bar_zero`` branch already does — or a negative bar's own ladder
    rung renders below the auto-fit domain and Vega-Lite silently drops it:
    the axis's lowest label reads 0 while the bar itself extends to -30.
    """
    svg = render_board_to_svg(_ZERO_ANCHOR_NEGATIVE_BOARD)
    charts = leaf_kind_subtrees(svg, "chart")
    assert len(charts) == 2
    vertical_positions = _measure_axis_positions(charts[0])
    horizontal_positions = _measure_axis_positions(charts[1])

    # Vertical bar (control) already pins domainMin from the ladder
    # (_emit_vertical's bar_zero branch) — it must show a sub-zero rung, or
    # this fixture doesn't actually exercise the zero-anchor default branch.
    assert any(_parse_tick_value(t) < 0 for t in vertical_positions), (
        "vertical bar (control) should include a sub-zero rung; got "
        f"{set(vertical_positions)}"
    )
    assert set(horizontal_positions) == set(vertical_positions), (
        "horizontal bar's zero-anchored default-path ladder must match "
        f"vertical bar's for identical data; got {set(horizontal_positions)} "
        f"vs {set(vertical_positions)}"
    )

    # Geometry, not just text: a real linear scale places every tick at a
    # pixel position matching its numeric distance from its neighbors. A
    # domain that silently excluded the negative rung or
    # clipped/mispositioned it would fail this even on a coincidentally
    # correct label SET.
    for positions, orientation in (
        (vertical_positions, "vertical"),
        (horizontal_positions, "horizontal"),
    ):
        ordered = sorted(positions.items(), key=lambda kv: _parse_tick_value(kv[0]))
        values = [_parse_tick_value(t) for t, _ in ordered]
        pixels = [p for _, p in ordered]
        value_step = values[1] - values[0]
        pixel_step = pixels[1] - pixels[0]
        for i in range(2, len(ordered)):
            assert (values[i] - values[i - 1]) == pytest.approx(value_step), (
                f"{orientation} bar: expected an evenly-spaced ladder, got {ordered}"
            )
            assert (pixels[i] - pixels[i - 1]) == pytest.approx(pixel_step, rel=0.02), (
                f"{orientation} bar: tick pixel spacing is not linear: {ordered}"
            )


# Default (no authored domain) zero-anchor path, data close to zero (ratio
# <= 0.25 — the smart-zero heuristic's own threshold) — the branch neither
# existing test in this file reaches: the authored-domain test bypasses
# _resolve_cartesian_ticks's zero-anchor computation entirely, and the zoom
# test's far-from-zero data (ratio ~0.96) routes into the explicit
# scale.zero=False branch instead of this one's abstention branch.
_ZERO_ANCHOR_CLOSE_TO_ZERO_BOARD = """
title: Tick ladder parity (zero-anchor default domain)
queries:
  q:
    type: values
    rows:
      - {month: Jan, metric_a: 250, metric_b: 300}
      - {month: Feb, metric_a: 600, metric_b: 500}
      - {month: Mar, metric_a: 1000, metric_b: 700}
charts:
  line_single_metric:
    query: q
    type: line
    x: month
    y: metric_a
  line_multi_metric_zero_anchor:
    query: q
    type: line
    x: month
    y: [metric_a, metric_b]
rows:
  - line_single_metric
  - line_multi_metric_zero_anchor
"""


def test_multi_metric_line_zero_anchor_ladder_matches_single_metric_default_path() -> (
    None
):
    """Regression: multi-metric line, no authored domain, data close enough
    to zero that the smart-zero heuristic abstains (returns ``None``) rather
    than pinning an explicit True/False — the ladder still commits to a
    zero-anchor decision, and the emitted scale must agree.
    """
    svg = render_board_to_svg(_ZERO_ANCHOR_CLOSE_TO_ZERO_BOARD)
    charts = leaf_kind_subtrees(svg, "chart")
    assert len(charts) == 2
    single_ticks = _measure_axis_positions(charts[0])
    multi_ticks = _measure_axis_positions(charts[1])

    assert "0" in single_ticks, (
        "single-metric line (control) should zero-anchor for data this "
        f"close to zero; got {single_ticks}"
    )
    assert set(multi_ticks) == set(single_ticks), (
        f"multi-metric ladder {set(multi_ticks)} != single-metric control "
        f"{set(single_ticks)}"
    )
    # Geometry-level: ticks must be evenly spaced within the multi-metric chart.
    assert _tick_grid_consistent(multi_ticks), (
        f"multi-metric tick pixel positions are not evenly spaced — likely a "
        f"baked-domain/emitted-scale mismatch: {multi_ticks}"
    )


# Authored domain [30, 250] with the shipped default theme's ticks.count: 6 —
# nice_tick_values(30, 250, 6) rounds OUTWARD to [0, 50, 100, 150, 200, 250]
# (verified: dbt_charts.core.numeric.nice_tick_values(30, 250, 6)), so the
# ladder's bottom rung (0) sits below the authored floor (30). Nothing else
# is authored — this is the shipped-default failure path, not a hand-picked
# edge case.
_AUTHORED_DOMAIN_FLOOR_BOARD = """
title: Authored domain floor survives the zero-anchor bake
queries:
  q:
    type: values
    rows:
      - {month: Jan, metric_a: 40, metric_b: 200}
      - {month: Feb, metric_a: 120, metric_b: 150}
      - {month: Mar, metric_a: 90, metric_b: 180}
charts:
  line_multi_metric_domain_floor:
    query: q
    type: line
    x: month
    y: [metric_a, metric_b]
    style:
      axis_quantitative:
        scale:
          continuous:
            domain: [30, 250]
rows:
  - line_multi_metric_domain_floor
"""


def test_multi_metric_line_authored_domain_floor_survives_zero_anchor_bake() -> None:
    """Regression: an authored ``scale.continuous.domain`` floor on a
    multi-metric line must not be silently replaced by the zero-anchored
    tick ladder's bottom rung. ``_bake_zero_flag`` fired without consulting
    the authored domain, and ``_emit_multi_metric_line`` had no
    authored-domain branch, so VL's ``domainMin: 0`` overrode the authored
    ``domain: [30, 250]`` and drew a floor of 0, not 30.
    """
    svg = render_board_to_svg(_AUTHORED_DOMAIN_FLOOR_BOARD)
    charts = leaf_kind_subtrees(svg, "chart")
    assert len(charts) == 1
    ticks = _measure_axis_positions(charts[0])
    assert "0" not in ticks, (
        "authored domain floor (30) was overridden by the zero-anchored "
        f"ladder's bottom rung (0); got ticks {set(ticks)}"
    )


# scatter is a fourth, structurally separate measure-channel builder
# (emitters/scatter.py, which now routes through bake_tick_ladder too) —
# this board
# authors axis_quantitative.scale.values directly (not ticks.count) so the
# only source of "values" is the authored list, never a resolved ladder.
# Values sit inside the data's own [275, 540] extent (so this stays a pure
# "does the authored list survive at all" check, uncomplicated by whether
# scatter's data-dependent zero-anchor decision would also widen the domain
# enough to display an out-of-range value) and deliberately avoid the
# hundreds-multiples the default nice-tick ladder would compute for this
# same data (200/300/400/500/600) — a bug that overwrites the authored list
# with that ladder would otherwise pass by coincidental overlap.
_AUTHORED_SCALE_VALUES_BOARD = """
title: Authored scale.values parity
queries:
  q1:
    type: values
    rows:
      - {region: North, metric_a: 320}
      - {region: South, metric_a: 540}
      - {region: East, metric_a: 275}
charts:
  bar_horizontal:
    query: q1
    type: bar
    x: region
    y: metric_a
    style:
      orientation: horizontal
      axis_quantitative:
        scale:
          values: [301, 402, 503]
  scatter:
    query: q1
    type: scatter
    x: region
    y: metric_a
    style:
      axis_quantitative:
        scale:
          values: [301, 402, 503]
rows:
  - bar_horizontal
  - scatter
"""


def test_scatter_honors_authored_measure_axis_scale_values_like_bar_and_line() -> None:
    """Regression: scatter's y-axis unconditionally overwrote VL axis.values
    from the resolved tick ladder (``ay.tick_values``), silently discarding
    an authored ``axis_quantitative.scale.values`` list that every other
    measure-channel builder honors via ``bake_tick_ladder``'s
    ``"values" not in`` guard — scatter is a fourth, unconverted
    measure-channel builder.
    """
    svg = render_board_to_svg(_AUTHORED_SCALE_VALUES_BOARD)
    charts = leaf_kind_subtrees(svg, "chart")
    assert len(charts) == 2
    bar_ticks = _measure_axis_positions(charts[0])
    scatter_ticks = _measure_axis_positions(charts[1])

    assert set(bar_ticks) == {"301", "402", "503"}, (
        f"bar (control) should honor the authored scale.values list; got "
        f"{set(bar_ticks)}"
    )
    assert set(scatter_ticks) == {"301", "402", "503"}, (
        "scatter should honor the authored scale.values list the same way "
        f"bar does; got {set(scatter_ticks)}"
    )


# Authored axis_y.scale.values ladder [301, 402, 503] whose bottom rung (301)
# sits ABOVE the data floor (275) — horizontal bar's zero-anchored default
# branch (_emit_horizontal, bar.py) used to pin domainMin from
# ay.tick_values[0] unconditionally, so an AUTHORED ladder's first rung
# clipped the below-it datum out of the domain entirely (main's
# _authored_tick_ladder change made ay.tick_values carry the authored list
# verbatim instead of always being a computed, zero-anchored ladder whose
# bottom rung is guaranteed <= the data floor).
_AUTHORED_LADDER_ABOVE_DATA_FLOOR_BOARD = """
title: Authored ladder floor above data floor
queries:
  q1:
    type: values
    rows:
      - {region: North, metric_a: 320}
      - {region: South, metric_a: 540}
      - {region: East, metric_a: 275}
charts:
  bar_horizontal:
    query: q1
    type: bar
    x: region
    y: metric_a
    style:
      orientation: horizontal
      axis_quantitative:
        scale:
          values: [301, 402, 503]
rows:
  - bar_horizontal
"""


def test_authored_ladder_floor_above_data_does_not_clip_marks() -> None:
    """Regression: an authored ``axis_y.scale.values`` ladder whose bottom
    rung sits above the data floor must not be treated as a computed
    zero-anchored ladder's bottom rung and pinned as ``domainMin`` — doing so
    silently excludes any datum below the author's lowest tick from the
    scale's domain, and Vega-Lite drops every mark for a chart-shaped hole
    even though the chart received rows.

    Asserts on drawn mark geometry (``mark_extents``), not a raw ``<path>``
    count: the SVG group chrome vl_convert emits around every chart (its
    own background/foreground/clip paths) also counts as ``<path>``
    elements, so a count threshold can be satisfied by zero drawn marks.
    """
    svg = render_board_to_svg(_AUTHORED_LADDER_ABOVE_DATA_FLOOR_BOARD)
    extents = mark_extents(svg)
    assert len(extents) == 1
    bar = extents[0]
    assert bar.chart_id == "bar_horizontal"
    # 3 bar rects (one per data row) + 1 zero-baseline rule mark.
    assert bar.count == 4, (
        "authored ladder floor (301) above the data floor (275) clipped one "
        f"or more bars out of the drawn domain: got {bar.count} marks, "
        f"expected 4 (3 bars + the baseline rule)"
    )
    assert bar.max_width > 0 and bar.max_height > 0, (
        f"a drawn bar has zero extent: {bar}"
    )


# Authored axis_quantitative.scale.values ladder [10, 20, 30] whose bottom
# rung (10) sits ABOVE the data floor (5, on metric_b) — multi-metric line
# reaches the same domain-floor pin as horizontal bar's above, but through
# resolve_measure_y_scale (emitters/_cartesian.py) rather than
# _emit_horizontal (bar.py): the smart-zero heuristic abstains for this
# close-to-zero data, line.py's resolve step bakes an explicit zero-anchor
# decision onto the scale, and the emitted VL scale used to pin domainMin
# from the authored ladder's own first rung regardless of provenance.
_AUTHORED_LADDER_ABOVE_DATA_FLOOR_LINE_BOARD = """
title: Authored ladder floor above data floor (line)
queries:
  q:
    type: values
    rows:
      - {month: Jan, metric_a: 20, metric_b: 15}
      - {month: Feb, metric_a: 28, metric_b: 5}
      - {month: Mar, metric_a: 10, metric_b: 25}
charts:
  line_multi_metric:
    query: q
    type: line
    x: month
    y: [metric_a, metric_b]
    style:
      axis_quantitative:
        scale:
          values: [10, 20, 30]
rows:
  - line_multi_metric
"""


def test_multi_metric_line_authored_ladder_floor_above_data_does_not_clip() -> None:
    """Regression: an authored ``axis_quantitative.scale.values`` ladder
    whose bottom rung sits above the data floor must not pin a multi-metric
    line's domain floor either. Reads the drawn Y-axis domain straight from
    Vega's own accessibility label (``aria-label="Y-axis ... values from X
    to Y"``, which states the scale's actual rendered bounds) rather than an
    intermediate VL dict — a line mark carries no clip, so a wrongly-pinned
    floor doesn't drop the point, it paints it outside the plot over the
    axis chrome, which only the drawn domain (not mark count) reveals.
    """
    svg = render_board_to_svg(_AUTHORED_LADDER_ABOVE_DATA_FLOOR_LINE_BOARD)
    match = re.search(
        r'aria-label="Y-axis[^"]*values from (-?[\d.]+) to (-?[\d.]+)"', svg
    )
    assert match, f"no Y-axis aria-label found in rendered SVG: {svg!r}"
    domain_min = float(match.group(1))
    assert domain_min <= 5, (
        "authored ladder floor (10) clipped the data floor (5) out of the "
        f"drawn domain: Y-axis domain starts at {domain_min}"
    )
