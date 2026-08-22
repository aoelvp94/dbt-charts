"""Unit tests for the mark-extent measurement.

These exist because the sweep that uses it had a hole big enough to drive the whole
scatter and pie families through. `_path_extent` returned None for any path containing a
curve command, and the sweep skipped charts whose mark count was zero — so eighteen
charts passed "every chart draws marks with height" without a single mark being
measured. The measurement looked careful and reported nothing.

Scatter symbols and pie wedges are drawn with elliptical-arc commands, so arcs are the
case to pin hardest. The `<a>`-wrapped case pins a second hole: vl_convert wraps a
`link:`-linked mark's path in `<a xlink:href="…">`, so a scan that only looks at a
`role-mark` group's direct children sees the `<a>` and reports no mark at all.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from dbt_charts.core.render.chart.mark_extents import (
    _measure_role_marks,
    _path_extent,
    all_marks_degenerate,
)

SVG = "http://www.w3.org/2000/svg"


def path(d: str) -> ET.Element:
    return ET.fromstring(f'<path xmlns="{SVG}" d="{d}"/>')


def test_a_bar_drawn_with_relative_commands_is_measured() -> None:
    """Bars are emitted as `M…h…v…h…Z`; a parser that ignores h/v measures nothing."""
    assert _path_extent(path("M14,310h6v-40h-6Z")) == (6, 40)


def test_a_zero_height_bar_reports_zero_height() -> None:
    """The defect this sweep exists to catch: right position, right width, no height."""
    assert _path_extent(path("M14,310h6v0h-6Z")) == (6, 0)


def test_a_scatter_symbol_is_measured_exactly() -> None:
    """A point symbol is two half-circle arcs; its extent is the diameter.

    Bailing here is what made every scatter chart in the corpus invisible to the sweep.
    """
    d = "M3.873,0A3.873,3.873,0,1,1,-3.873,0A3.873,3.873,0,1,1,3.873,0"
    extent = _path_extent(path(d))
    assert extent is not None
    width, height = extent
    assert width == pytest.approx(7.746)
    assert height == pytest.approx(7.746)


def test_a_pie_wedge_is_measured() -> None:
    """A wedge's bulge lies outside its chord, so the arc has to be followed."""
    d = (
        "M139.452,-57.575A3,3,0,0,0,141.057,-61.547A153.9,153.9,0,0,0,"
        "3.06,-153.87A3,3,0,0,0,0,-150.87L0,0Z"
    )
    extent = _path_extent(path(d))
    assert extent is not None
    width, height = extent
    assert width == pytest.approx(141.057, abs=0.5)
    assert height == pytest.approx(153.87, abs=0.5)


def test_an_arc_bulge_is_included_not_just_its_endpoints() -> None:
    """A half circle from (0,0) to (10,0) reaches y=5; the chord alone would say 0."""
    extent = _path_extent(path("M0,0A5,5,0,0,1,10,0"))
    assert extent is not None
    width, height = extent
    assert width == pytest.approx(10)
    assert height == pytest.approx(5)


def test_a_rotated_ellipse_is_refused_rather_than_measured_wrong() -> None:
    """Never emitted by the mark renderers, so a wrong number would go unnoticed."""
    assert _path_extent(path("M0,0A5,3,45,0,1,10,0")) is None


def test_a_rounded_bar_corner_bezier_is_measured() -> None:
    """A cornerRadius bar (grouped columns on a quantitative x, now painting
    real height via the `y.stack: null` fix) emits a cubic Bézier `C` for its
    rounded top corners. A parser that bails on `C` reports the mark
    unmeasurable, and the only other mark left in the vote is the always-zero
    baseline rule — which reads as "every mark degenerate" even though the
    bar painted a real height.
    """
    extent = _path_extent(
        path("M0,10L8,10C8.6,10,9,10.4,9,11L9,20L0,20L0,11C0,10.4,0.4,10,1,10Z")
    )
    assert extent is not None
    width, height = extent
    assert width == pytest.approx(9)
    assert height == pytest.approx(10)


def test_a_quadratic_bezier_is_still_refused() -> None:
    """`Q`/`S`/`T` stay refused — only `C` (the rounded-rect corner shape vega
    actually emits) is measured; a wrong number for a shape not in the corpus
    would go unnoticed.
    """
    assert _path_extent(path("M0,0Q5,10,10,0")) is None


def test_a_relative_cubic_bezier_is_measured_correctly() -> None:
    """`c` (lowercase, relative) control/end points must re-base off the
    running current point across multiple segments, not the path's origin —
    an inverted conversion would still pass a single-segment check.
    """
    extent = _path_extent(path("M10,10c1,5,2,5,3,0,2,-5,4,-5,6,0"))
    assert extent == (9, 10)


def test_a_line_path_is_measured() -> None:
    assert _path_extent(path("M0,0L10,0L10,20")) == (10, 20)


def test_explicit_width_and_height_win() -> None:
    rect = ET.fromstring(f'<rect xmlns="{SVG}" width="12" height="34"/>')
    assert _path_extent(rect) == (12, 34)


def test_a_line_element_is_measured_from_its_endpoints() -> None:
    """`mark-rule` (the always-on zero-baseline) is a plain SVG `<line>`, not a
    `<path>` — a measurer that only understands `d=` sees nothing.
    """
    line = ET.fromstring(f'<line xmlns="{SVG}" x2="502" y2="0"/>')
    assert _path_extent(line) == (502, 0)


def test_a_line_element_with_explicit_start_point_is_measured() -> None:
    line = ET.fromstring(f'<line xmlns="{SVG}" x1="10" y1="5" x2="10" y2="45"/>')
    assert _path_extent(line) == (0, 40)


def test_an_element_with_no_geometry_is_none() -> None:
    assert _path_extent(ET.fromstring(f'<g xmlns="{SVG}"/>')) is None


def test_a_linked_mark_wrapped_in_an_anchor_is_measured() -> None:
    """`link:` wraps the mark's path in `<a xlink:href="…">`; a direct-children-only
    scan of the role-mark group sees only the `<a>` and reports no mark at all.
    """
    group = ET.fromstring(
        f'<g xmlns="{SVG}" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'class="mark-rect role-mark">'
        '<a xlink:href="https://example.com"><path d="M0,0h10v20h-10Z"/></a>'
        "</g>"
    )
    marks = _measure_role_marks(group)
    assert marks == [("mark-rect role-mark", 10, 20)]


def _svg(inner: str) -> str:
    return f'<svg xmlns="{SVG}">{inner}</svg>'


def test_all_marks_degenerate_is_true_with_no_role_mark_group_at_all() -> None:
    """The `xs_num` shape: the chart drew nothing a reader can see."""
    assert all_marks_degenerate(_svg("<g><rect width='10' height='10'/></g>"))


def test_all_marks_degenerate_is_true_when_every_mark_is_zero_extent() -> None:
    svg = _svg(
        '<g class="mark-rect role-mark"><path d="M0,0h0v0h0Z"/></g>'
        '<g class="mark-rect role-mark"><path d="M10,0h0v0h0Z"/></g>'
    )
    assert all_marks_degenerate(svg)


def test_all_marks_degenerate_is_false_when_one_mark_has_real_extent() -> None:
    """One zero-valued bar among several is correct data, not a broken render."""
    svg = _svg(
        '<g class="mark-rect role-mark"><path d="M0,0h0v10h0Z"/></g>'
        '<g class="mark-rect role-mark"><path d="M10,0h10v10h-10Z"/></g>'
    )
    assert not all_marks_degenerate(svg)


def test_all_marks_degenerate_is_false_when_marks_are_unmeasurable() -> None:
    """A rotated ellipse (`A`) is a shape `_path_extent` still refuses to read
    (cubic Béziers — the rounded-rect bar corner — are measured; see
    `test_a_rounded_bar_corner_bezier_is_measured`).

    An unmeasurable mark is not evidence a chart is blank — firing here would
    turn a real, healthy render into an error card for a shape the measurer
    doesn't yet understand.
    """
    svg = _svg('<g class="mark-rect role-mark"><path d="M0,0A5,3,45,0,1,10,0"/></g>')
    assert not all_marks_degenerate(svg)


def test_all_marks_degenerate_when_only_the_baseline_rule_paints() -> None:
    """A bar chart always carries a zero-baseline `mark-rule` layer alongside its
    real bars. If the real bars never painted (the root cause this guard
    exists to catch — a broken date/scale detection collapsing every row),
    the lone baseline rule is the only content, and it conveys nothing: full
    chart width, zero height. This is the `date-format-explorer.yml#
    day_iso_dt_chart` shape.
    """
    svg = _svg('<g class="mark-rule role-mark layer_1_marks"><line x2="502"/></g>')
    assert all_marks_degenerate(svg)


def test_not_degenerate_when_real_bars_accompany_the_baseline_rule() -> None:
    """The common, healthy case: real bars plus the always-on zero rule."""
    svg = _svg(
        '<g class="mark-rect role-mark layer_0_marks">'
        '<path d="M0,0h10v20h-10Z"/>'
        "</g>"
        '<g class="mark-rule role-mark layer_1_marks"><line x2="502"/></g>'
    )
    assert not all_marks_degenerate(svg)


def test_opacity0_bars_excluded_so_blank_bar_with_hover_band_fires_error() -> None:
    """The hover band is an opacity=0 bar with non-zero pixel extent (height * 0.1).

    Without the mark-bar opacity filter, ``all_marks_degenerate`` would never fire
    for a blank bar chart because the band's extent is always non-zero. With the
    filter, only real bars are counted — and if they're all zero, the error fires.
    """
    # Real bars: all zero height (blank chart). Hover band: opacity=0, non-zero extent.
    # VL bar marks render as mark-rect in the SVG (not mark-bar).
    svg = _svg(
        '<g class="mark-rect role-mark layer_0_marks">'
        # real bar, zero height
        '<path d="M0,300h10v0h-10Z"/>'
        "</g>"
        '<g class="mark-rect role-mark layer_1_marks">'
        # hover band, opacity=0, non-zero height
        '<path opacity="0" d="M0,300h10v30h-10Z"/>'
        "</g>"
    )
    assert all_marks_degenerate(svg)


def test_opacity0_symbols_not_excluded_so_line_chart_with_hover_points_passes() -> None:
    """Line chart hover symbols start at opacity=0 (shown only on hover via Vega signals).

    These are not hover band marks — they're the symbol layer of a line chart
    (mark-symbol, not mark-bar). They must not be filtered out, or a healthy
    line chart fires ERR-CHART-PAINTED-NO-MARKS.
    """
    # Line with real stroke, symbols at opacity=0 (hover state, initially hidden).
    svg = _svg(
        '<g class="mark-line role-mark layer_0_marks">'
        '<path d="M0,100L100,50L200,80"/>'
        "</g>"
        '<g class="mark-symbol role-mark layer_1_marks">'
        '<path opacity="0" d="M8.66,0A8.66,8.66,0,1,1,-8.66,0A8.66,8.66,0,1,1,8.66,0Z"/>'
        "</g>"
    )
    assert not all_marks_degenerate(svg)
