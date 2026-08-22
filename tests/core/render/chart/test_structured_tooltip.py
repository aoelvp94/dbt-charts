"""Golden aria-label tests for the LUT-driven structured tooltip builder.

Walking-skeleton scope: line, multi-series line, bar (vertical + horizontal,
grouped + stacked), and pie/donut. Asserts on the **rendered SVG aria-label**,
following the same pattern as ``test_tooltip_dedup.py`` — the structured
builder's output is VL's native ``description`` channel, not an appended
``encoding.tooltip`` array (see ``emitters/_tooltip.py`` for why).

Header/series rows are role-tagged with zero-width Unicode markers (see
``emitters/_tooltip.py``'s ``ROLE_*`` constants) and carry a bare value with
no field-name prefix — tests assert on the marker + value, not on the old
``"Field: value"`` shape those rows used before this slice.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.authored import ChartTotal
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    HeatmapChart,
    LineChart,
    PieChart,
    ScatterChart,
)
from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    BarChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.emitters._tooltip import (
    MUTED,
    ROLE_HEADER,
    ROLE_HEADER_SWATCHED,
    ROLE_ORDER,
    ROLE_SERIES,
    ROLE_TOTAL,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_RS, _BOARD_CTX = resolve_style_and_context(get_theme_style())


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


def _svg_aria_labels(spec: dict[str, Any]) -> list[str]:
    import vl_convert as vlc

    svg = vlc.vegalite_to_svg(spec)
    return re.findall(r'aria-label="([^"]+)"', svg)


def _svg_string(spec: dict[str, Any]) -> str:
    import vl_convert as vlc

    result: str = vlc.vegalite_to_svg(spec)
    return result


def _render(chart: Any, data: list[dict[str, Any]]) -> list[str]:
    resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = generate_vega_lite_spec(chart, data, width=400)
    return _svg_aria_labels(spec)


_MULTI_SERIES_LINE_DATA = [
    {"month": "2024-01", "revenue": 100.0, "region": "North"},
    {"month": "2024-02", "revenue": 150.0, "region": "North"},
    {"month": "2024-01", "revenue": 80.0, "region": "South"},
    {"month": "2024-02", "revenue": 95.0, "region": "South"},
]


def test_multi_series_line_includes_series_row():
    """Multi-series line: the aria-label must name which series a mark belongs to.

    Series rows drop the field-name prefix (bare value only) but stay tagged
    with ROLE_SERIES so the JS runtime can style them distinctly.
    """
    chart = LineChart(id="t", type="line", x="month", y="revenue", color="region")
    labels = _render(chart, _MULTI_SERIES_LINE_DATA)
    assert any(f"{ROLE_SERIES}North" in lb for lb in labels), labels
    assert any(f"{ROLE_SERIES}South" in lb for lb in labels), labels
    assert not any("Region:" in lb for lb in labels), "field label must be dropped"


def test_multi_series_line_header_before_series_before_value():
    """Structured order: header (identity) -> series row -> dependent value."""
    chart = LineChart(id="t", type="line", x="month", y="revenue", color="region")
    labels = _render(chart, _MULTI_SERIES_LINE_DATA)
    row = next(lb for lb in labels if f"{ROLE_SERIES}North" in lb and "Jan 2024" in lb)
    assert row.index(ROLE_HEADER) < row.index(ROLE_SERIES) < row.index("Revenue")


_ENDPOINT_ORDER_LINE_DATA = [
    {"month": "2024-01", "revenue": 150.0, "region": "South"},
    {"month": "2024-01", "revenue": 90.0, "region": "North"},
    {"month": "2024-01", "revenue": 60.0, "region": "West"},
    {"month": "2024-02", "revenue": 210.0, "region": "South"},
    {"month": "2024-02", "revenue": 130.0, "region": "North"},
    {"month": "2024-02", "revenue": 105.0, "region": "West"},
]


def test_multi_series_line_carries_baked_rank_matching_endpoint_order():
    """Each mark's aria-label must carry a ROLE_ORDER rank matching the SAME
    endpoint order that already drives scale.domain/legend.values -- the
    signal chart_interactivity.js needs to sort the x-unified tooltip
    correctly even when no legend renders (a line with endpoint labels
    instead of a legend, the common default, has no `.role-legend-label`
    DOM for the runtime's other order-reading path)."""
    chart = LineChart(id="t", type="line", x="month", y="revenue", color="region")
    labels = _render(chart, _ENDPOINT_ORDER_LINE_DATA)
    # Feb (last x) ends South(210) > North(130) > West(105) -> that rank order.
    rank_of = {"South": 0, "North": 1, "West": 2}
    for series_name, rank in rank_of.items():
        row = next(lb for lb in labels if f"{ROLE_SERIES}{series_name}" in lb)
        assert f"{ROLE_ORDER}{rank}" in row, (series_name, rank, row)


_SINGLE_VALUE_SERIES_LINE_DATA = [
    {"month": "2024-01", "revenue": 100.0, "region": "North"},
    {"month": "2024-02", "revenue": 150.0, "region": "North"},
]


def test_single_series_line_omits_series_row_when_cardinality_one():
    """A color channel bound to a single distinct value earns no series row."""
    chart = LineChart(id="t", type="line", x="month", y="revenue", color="region")
    labels = _render(chart, _SINGLE_VALUE_SERIES_LINE_DATA)
    assert labels, "expected at least one mark aria-label"
    assert not any(ROLE_SERIES in lb for lb in labels), labels


_SINGLE_SERIES_LINE_DATA = [
    {"month": "2024-01", "revenue": 1234.5},
    {"month": "2024-02", "revenue": 987.6},
]


def test_single_series_line_value_formatted():
    """No color channel at all: value must still be themed-formatted, not raw."""
    chart = LineChart(id="t", type="line", x="month", y="revenue")
    labels = _render(chart, _SINGLE_SERIES_LINE_DATA)
    assert any("Revenue: 1,234.5" in lb for lb in labels), labels


def test_single_series_line_header_is_bare_value_not_labeled():
    """Header row drops the field label entirely -- value only."""
    chart = LineChart(id="t", type="line", x="month", y="revenue")
    labels = _render(chart, _SINGLE_SERIES_LINE_DATA)
    assert any(f"{ROLE_HEADER}Jan 2024" in lb for lb in labels), labels
    assert not any("Month:" in lb for lb in labels), labels


def test_temporal_month_header_uses_friendly_format_not_raw_iso():
    """Month-granularity x ("2024-02") renders as "Feb 2024", not raw ISO.

    Regression for the friendly-date-header slice: infer_vega_type_from_data
    classifies a YYYY-MM bucket string as "ordinal" (not "temporal"), so the
    header must fall back to detect_time_unit to recover the bucket grain --
    same machinery build_cartesian_x_encoding uses for the axis itself.
    """
    chart = LineChart(id="t", type="line", x="month", y="revenue")
    labels = _render(chart, _SINGLE_SERIES_LINE_DATA)
    assert any(f"{ROLE_HEADER}Feb 2024" in lb for lb in labels), labels
    assert not any(f"{ROLE_HEADER}2024-02" in lb for lb in labels), labels


def test_temporal_day_level_header_still_full_date():
    """A genuine day-level ISO date header keeps full precision ("Feb 1, 2024")."""
    chart = LineChart(id="t", type="line", x="day", y="revenue")
    data = [
        {"day": "2024-02-01", "revenue": 100.0},
        {"day": "2024-02-02", "revenue": 150.0},
    ]
    labels = _render(chart, data)
    assert any(f"{ROLE_HEADER}Feb 1, 2024" in lb for lb in labels), labels


def test_bar_temporal_month_header_uses_friendly_format():
    """Same friendly-date fix applies to bar (not just line)."""
    chart = BarChart(id="t", type="bar", x="month", y="revenue")
    data = [
        {"month": "2024-01", "revenue": 100.0},
        {"month": "2024-02", "revenue": 150.0},
    ]
    labels = _render(chart, data)
    assert any(f"{ROLE_HEADER}Feb 2024" in lb for lb in labels), labels
    assert not any(f"{ROLE_HEADER}2024-02" in lb for lb in labels), labels


_GROUPED_BAR_DATA = [
    {"day_name": "Mon", "count": 5.5, "kind": "task"},
    {"day_name": "Mon", "count": 2.0, "kind": "pr"},
    {"day_name": "Tue", "count": 3.3, "kind": "task"},
    {"day_name": "Tue", "count": 1.1, "kind": "pr"},
]


def test_grouped_bar_includes_series_row():
    chart = BarChart(id="t", type="bar", x="day_name", y="count", color="kind")
    labels = _render(chart, _GROUPED_BAR_DATA)
    assert any(f"{ROLE_SERIES}task" in lb for lb in labels), labels
    assert any(f"{ROLE_SERIES}pr" in lb for lb in labels), labels


def test_grouped_bar_header_before_series_before_value():
    chart = BarChart(id="t", type="bar", x="day_name", y="count", color="kind")
    labels = _render(chart, _GROUPED_BAR_DATA)
    row = next(lb for lb in labels if f"{ROLE_SERIES}task" in lb and "Mon" in lb)
    assert row.index(ROLE_HEADER) < row.index(ROLE_SERIES) < row.index("Count")


_FACETED_MULTI_SERIES_DATA = [
    {"day_name": "Mon", "count": 5.0, "kind": "task", "team": "A"},
    {"day_name": "Mon", "count": 2.0, "kind": "pr", "team": "A"},
    {"day_name": "Tue", "count": 3.0, "kind": "task", "team": "A"},
    {"day_name": "Mon", "count": 7.0, "kind": "task", "team": "B"},
    {"day_name": "Mon", "count": 1.0, "kind": "pr", "team": "B"},
    {"day_name": "Tue", "count": 4.0, "kind": "task", "team": "B"},
]


def test_faceted_multi_series_omits_structured_tooltip():
    """Small-multiples (`multiples`) charts render every facet panel inside ONE
    .dbt-chart. The JS x-unified grouping scopes to .dbt-chart and its dedup key
    omits the facet field, so a structured (grouping-eligible) description would
    let a hover in one panel show a sibling panel's values. A faceted chart must
    fall back to the per-mark tooltip: no ROLE_HEADER-tagged description emitted
    (mirrors the chart.layers exclusion)."""
    chart = BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "x": "day_name",
            "y": "count",
            "color": "kind",
            "multiples": {"columns": "team"},
        }
    )
    labels = _render(chart, _FACETED_MULTI_SERIES_DATA)
    assert labels, "expected the faceted chart to render marks"
    assert not any(ROLE_HEADER in lb for lb in labels), labels


_STACKED_BAR_DATA = [
    {"day_name": "Mon", "count": 5.5, "kind": "task"},
    {"day_name": "Mon", "count": 2.0, "kind": "pr"},
    {"day_name": "Tue", "count": 3.3, "kind": "task"},
    {"day_name": "Tue", "count": 1.1, "kind": "pr"},
]


def test_stacked_bar_includes_series_row():
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "zero"}),
    )
    labels = _render(chart, _STACKED_BAR_DATA)
    assert any(f"{ROLE_SERIES}task" in lb for lb in labels), labels


def test_stacked_bar_zero_carries_total_but_no_percent():
    """An ABSOLUTE (stack: zero) stack is commensurable and additive too --
    it gets the same group-total footer as a normalized stack (same
    server-side joinaggregate), but no percent (percent stays normalize-only)."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "zero"}),
    )
    labels = _render(chart, _STACKED_BAR_DATA)
    row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert "Count: 5.5" in row, row
    assert f"{ROLE_TOTAL}Total: 7.5" in row, row  # Mon: task 5.5 + pr 2.0
    assert "Share" not in row, row


_SINGLE_SERIES_BAR_DATA = [
    {"day_name": "Mon", "count": 5.5},
    {"day_name": "Tue", "count": 3.3},
]


def test_single_series_bar_value_formatted_no_series_row():
    chart = BarChart(id="t", type="bar", x="day_name", y="count")
    labels = _render(chart, _SINGLE_SERIES_BAR_DATA)
    assert any("Count: 5.5" in lb for lb in labels), labels
    assert not any(ROLE_SERIES in lb for lb in labels), labels


def test_normalize_stack_carries_percent_raw_and_total():
    """Normalized (100%) stacked bar: % leads, raw beneath, true group total footer."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "normalize"}),
    )
    labels = _render(chart, _STACKED_BAR_DATA)
    # Mon: task=5.5, pr=2.0 -> group total 7.5, task share ~73%.
    row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert "Share: 73%" in row, row
    assert "Count: 5.5" in row, row
    assert f"{ROLE_TOTAL}Total: 7.5" in row, row
    # % leads, raw beneath, total last.
    assert row.index("Share") < row.index("Count") < row.index(f"{ROLE_TOTAL}Total")


def test_stacked_area_total_is_not_nan():
    """Area charts always emit as a mark="layered" VL composite (fill + stroke
    + hover-point sub-layers) via `_translate_layered` -- a distinct assembly
    path from bar's `_translate_standard`. Regression: `_translate_layered`
    dropped `spec.transforms` entirely, so the group-total joinaggregate
    feeding this footer never ran and `__dft_group_total` stayed undefined,
    rendering the footer as "Total: NaN" instead of the true sum."""
    chart = AreaChart(
        id="t",
        type="area",
        x="day_name",
        y="count",
        color="kind",
        style=AreaChartStylePatch.model_validate({"stack": "zero"}),
    )
    labels = _render(chart, _STACKED_BAR_DATA)
    row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert f"{ROLE_TOTAL}Total: 7.5" in row, row
    assert "NaN" not in row, row


def test_normalize_stack_total_is_the_true_group_sum_not_a_single_series():
    """The footer must be the FULL group total (all series), not one series' value."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "normalize"}),
    )
    labels = _render(chart, _STACKED_BAR_DATA)
    tue_total = next(
        lb for lb in labels if f"{ROLE_SERIES}pr" in lb and f"{ROLE_HEADER}Tue" in lb
    )
    assert f"{ROLE_TOTAL}Total: 4.4" in tue_total, tue_total  # 3.3 + 1.1


_COMBO_SINGLE_BASE_DATA = [
    {"month": "2024-01", "revenue": 100.0, "target": 90.0},
    {"month": "2024-02", "revenue": 150.0, "target": 120.0},
]


def test_combo_single_series_base_and_overlay_share_the_same_header():
    """Base and overlay marks must render the IDENTICAL header string for the
    same x -- chart_interactivity.js's collectMatchingMarks groups marks by
    exact header-string equality, so any mismatch (e.g. a friendly-date format
    applied inconsistently) would silently break the unified bubble."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_SINGLE_BASE_DATA)
    base_headers = {
        lb[lb.index(ROLE_HEADER) + 1 : lb.index(";")]
        for lb in labels
        if ROLE_HEADER in lb and "Revenue" in lb
    }
    overlay_headers = {
        lb[lb.index(ROLE_HEADER) + 1 : lb.index(";")]
        for lb in labels
        if ROLE_HEADER in lb and "Target" in lb and "Revenue" not in lb
    }
    assert base_headers and overlay_headers, labels
    assert base_headers == overlay_headers, (base_headers, overlay_headers, labels)


def test_combo_single_series_base_carries_no_total():
    """Single-series base + line overlay: no group to sum, so no Total footer
    anywhere -- neither on the base's own row nor the overlay's."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_SINGLE_BASE_DATA)
    assert not any(ROLE_TOTAL in lb for lb in labels), labels


def test_combo_overlay_row_carries_its_own_formatted_value():
    """The overlay layer's own mark must carry a role-marked description with
    its own (formatted) value -- not the old plain 'Month: ...; Target: ...'
    shape, and not the base's 'revenue' field."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_SINGLE_BASE_DATA)
    overlay_rows = [lb for lb in labels if "Target" in lb and ROLE_SERIES in lb]
    assert overlay_rows, labels
    assert any("90" in lb or "120" in lb for lb in overlay_rows), overlay_rows
    assert not any("revenue" in lb.lower() for lb in overlay_rows), overlay_rows


_COMBO_STACKED_BASE_DATA = [
    {"day_name": "Mon", "count": 5.5, "kind": "task", "target": 20.0},
    {"day_name": "Mon", "count": 2.0, "kind": "pr", "target": 20.0},
    {"day_name": "Tue", "count": 3.3, "kind": "task", "target": 15.0},
    {"day_name": "Tue", "count": 1.1, "kind": "pr", "target": 15.0},
]


def test_combo_stacked_base_carries_total_never_folding_in_the_overlay():
    """A stacked (commensurable/additive) base + line overlay reads
    parts -> Total -> Target. The base's own group-total footer must be the
    SUM OF THE BASE'S OWN SEGMENTS ONLY (7.5 = 5.5 + 2.0 for Mon) -- the
    overlay's target value is never folded into it."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "zero"}),
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_STACKED_BASE_DATA)
    mon_task_row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert f"{ROLE_TOTAL}Total: 7.5" in mon_task_row, mon_task_row
    overlay_rows = [lb for lb in labels if "Target" in lb and "20" in lb]
    assert overlay_rows, labels
    assert not any(ROLE_TOTAL in lb for lb in overlay_rows), overlay_rows


def test_combo_overlay_row_mark_carries_a_color_for_the_tooltip_swatch():
    """The overlay ("Target") row's own mark must resolve to a real fill or
    stroke color, matching how the base tier rows get one -- the JS runtime
    (chart_interactivity.js's markSeriesColor) reads the HOVERED MARK'S OWN
    fill/stroke attribute directly (not the legend), so a swatch-less overlay
    mark means a swatch-less tooltip row. Regression: the overlay's invisible
    hover-point mark (the widest, actually-hovered target) inherited no color
    at all from the wrapper's `color: {datum: label}` encoding -- unlike the
    visible foreground line, which paints via a static mark_props stroke."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "zero"}),
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    spec = generate_vega_lite_spec(
        chart,
        _COMBO_STACKED_BASE_DATA,
        board_style=_BOARD_RS,
        chart_style_context=_BOARD_CTX,
    )
    svg = _svg_string(spec)
    idx = svg.find("⁢Target")
    assert idx != -1, svg
    # The hovered mark is the nearest enclosing <path ...>; its own fill/
    # stroke attribute is what chart_interactivity.js's markSeriesColor reads.
    mark_start = svg.rfind("<path", 0, idx)
    mark_end = svg.find(">", idx)
    mark_tag = svg[mark_start:mark_end]
    has_color = bool(
        re.search(r'fill="(?!none")[^"]+"', mark_tag)
        or re.search(r'stroke="(?!none")[^"]+"', mark_tag)
    )
    assert has_color, mark_tag


def test_combo_grouped_base_carries_no_total():
    """A grouped (unstacked, chart.stack unset) multi-series base is not
    additive -- no Total footer, even with an overlay present."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_STACKED_BASE_DATA)
    assert not any(ROLE_TOTAL in lb for lb in labels), labels


_COMBO_MIXED_UNIT_DATA = [
    {"month": "2024-01", "revenue": 100.0, "growth_pct": 0.05},
    {"month": "2024-02", "revenue": 150.0, "growth_pct": 0.12},
]


def test_combo_mixed_unit_dual_axis_shows_both_values_no_total():
    """Mixed-unit combo (dollars + percent): both values render, each in its
    own unit/format, and no fabricated total ever unifies them."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[
            {
                "type": "line",
                "y": "growth_pct",
                "label": "Growth",
                "style": {"marks": {"line": {}}},
            }
        ],
    )
    labels = _render(chart, _COMBO_MIXED_UNIT_DATA)
    assert not any(ROLE_TOTAL in lb for lb in labels), labels
    assert any("Revenue: 100" in lb for lb in labels), labels
    assert any("Growth" in lb and "0.05" in lb for lb in labels), labels


_COMBO_OVERLAY_FORMAT_DATA = [
    {"month": "2024-01", "revenue": 100.0, "conversion": 0.031},
    {"month": "2024-02", "revenue": 150.0, "conversion": 0.045},
]


def test_combo_overlay_honors_its_own_authored_number_format():
    """An overlay layer's own axis_y.label.format (e.g. a percent d3-format)
    must flow into the combo tooltip's row for that layer -- not the base
    chart's tooltip_format. Regression: the overlay row previously always
    used the BASE chart's format, so an authored percent format on the
    overlay silently vanished and the tooltip showed the raw fraction
    (0.031) instead of the formatted percent (3.1%)."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[
            {
                "type": "line",
                "y": "conversion",
                "label": "Conversion %",
                "axis_y": {"label": {"format": ".1%"}},
            }
        ],
    )
    labels = _render(chart, _COMBO_OVERLAY_FORMAT_DATA)
    overlay_rows = [lb for lb in labels if "Conversion" in lb and ROLE_SERIES in lb]
    assert overlay_rows, labels
    assert any("3.1%" in lb for lb in overlay_rows), overlay_rows
    assert not any("0.031" in lb for lb in overlay_rows), overlay_rows


def test_combo_normalized_stack_base_suppresses_percent_row():
    """Regression: chart_interactivity.js's x-unified grid decides ONCE, for
    the whole bubble, whether a percent column exists (any matched row with 2
    values). A combo overlay's row only ever carries 1 value (its own), so a
    normalized-stack base's usual [Share%, raw] pair would make the grid
    misread the overlay's lone value as the percent column and leave its own
    value column blank. Combo suppresses the percent row (keeps raw + Total)
    rather than mixing 1-value and 2-value rows in one x-unified grid."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "normalize"}),
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_STACKED_BASE_DATA)
    assert not any("Share" in lb for lb in labels), labels
    mon_task_row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert "Count: 5.5" in mon_task_row, mon_task_row
    assert f"{ROLE_TOTAL}Total: 7.5" in mon_task_row, mon_task_row
    overlay_rows = [lb for lb in labels if "Target" in lb and "20" in lb]
    assert overlay_rows, labels


def test_scatter_base_combo_stays_on_old_behavior_not_half_migrated():
    """A scatter base's own tooltip gate (`applies_to`) is unchanged -- scatter
    has no natural x "header" identity for the x-unified bubble (its own role
    model carries two peer VALUE rows, no header). Regression: overlay layers
    must NOT get role-marked content either when the base is scatter, or
    they'd be stranded role-marked marks that can never unify with their own
    (un-role-marked) base -- a half-migrated state, not a real combo."""
    chart = ScatterChart(
        id="t",
        type="scatter",
        x="month",
        y="revenue",
        layers=[{"type": "line", "y": "target", "label": "Target"}],
    )
    labels = _render(chart, _COMBO_SINGLE_BASE_DATA)
    assert labels, "expected at least one mark aria-label"
    assert not any(ROLE_HEADER in lb or ROLE_SERIES in lb for lb in labels), labels


def test_combo_overlay_label_override_wins_in_tooltip():
    """An authored layer `label:` wins over the slug_to_title(layer.y) fallback
    in the overlay's own tooltip row, mirroring its legend/axis label."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[{"type": "line", "y": "target", "label": "Goal"}],
    )
    labels = _render(chart, _COMBO_SINGLE_BASE_DATA)
    assert any("Goal" in lb for lb in labels), labels
    assert not any("Target" in lb for lb in labels), labels


def test_combo_overlay_label_falls_back_to_slug_title():
    """No authored label: falls back to slug_to_title(layer.y), same as the
    layer's own legend/axis label cascade."""
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        layers=[{"type": "line", "y": "target"}],
    )
    labels = _render(chart, _COMBO_SINGLE_BASE_DATA)
    assert any("Target" in lb for lb in labels), labels


_PIE_DATA = [
    {"plan": "starter_monthly", "user_count": 8.5},
    {"plan": "pro_monthly", "user_count": 3.3},
]


def test_pie_header_and_value_present():
    chart = PieChart(
        id="t", type="pie", theta="user_count", color="plan", total=ChartTotal()
    )
    labels = _render(chart, _PIE_DATA)
    assert any(f"{ROLE_HEADER_SWATCHED}starter_monthly" in lb for lb in labels), labels
    assert any("User Count: 8.5" in lb for lb in labels), labels


def test_pie_header_before_value():
    chart = PieChart(
        id="t", type="pie", theta="user_count", color="plan", total=ChartTotal()
    )
    labels = _render(chart, _PIE_DATA)
    row = next(lb for lb in labels if f"{ROLE_HEADER_SWATCHED}starter_monthly" in lb)
    assert row.index(ROLE_HEADER_SWATCHED) < row.index("User Count")


def test_pie_carries_percent_and_grand_total():
    """Pie/donut: % leads, raw beneath, grand total footer (always -- pie
    values are inherently one commensurable unit)."""
    chart = PieChart(id="t", type="pie", theta="user_count", color="plan")
    labels = _render(chart, _PIE_DATA)
    row = next(lb for lb in labels if f"{ROLE_HEADER_SWATCHED}starter_monthly" in lb)
    assert "Share: 72%" in row, row
    assert "User Count: 8.5" in row, row
    assert f"{ROLE_TOTAL}Total: 11.8" in row, row
    assert (
        row.index("Share") < row.index("User Count") < row.index(f"{ROLE_TOTAL}Total")
    )


def test_pie_mutes_raw_count_and_total_but_not_the_share_lead():
    """On a pie the share % is the lead; the raw slice count and the grand
    total are context, so both carry the MUTED marker (rendered low-contrast)
    while the share % and swatched header do not."""
    chart = PieChart(id="t", type="pie", theta="user_count", color="plan")
    labels = _render(chart, _PIE_DATA)
    row = next(lb for lb in labels if f"{ROLE_HEADER_SWATCHED}starter_monthly" in lb)
    # raw count and total are muted (MUTED prepended, composing with ROLE_TOTAL)
    assert f"{MUTED}User Count: 8.5" in row, row
    assert f"{MUTED}{ROLE_TOTAL}Total: 11.8" in row, row
    # the share % lead and the header are NOT muted
    assert f"{MUTED}Share" not in row, row
    assert f"{MUTED}{ROLE_HEADER_SWATCHED}" not in row, row


# --- Edge cases (final slice) ------------------------------------------------

_HEATMAP_DATA = [
    {"day": "Mon", "hour": "9", "visits": 1234.56},
    {"day": "Mon", "hour": "10", "visits": 42.0},
    {"day": "Tue", "hour": "9", "visits": 87.3},
]


def test_heatmap_header_carries_both_x_and_y():
    """Heatmap's identity is the PAIR [x, y] -- both x and y header the cell;
    the colour-encoded value is the sole dependent row, no series/no total."""
    chart = HeatmapChart(id="t", type="heatmap", x="day", y="hour", color="visits")
    labels = _render(chart, _HEATMAP_DATA)
    row = next(
        lb for lb in labels if f"{ROLE_HEADER}Mon" in lb and f"{ROLE_HEADER}9" in lb
    )
    assert "Visits: 1,234.56" in row, row
    assert ROLE_SERIES not in row, row
    assert ROLE_TOTAL not in row, row


def test_heatmap_without_color_channel_does_not_crash():
    """A heatmap with no bound colour channel is a degenerate but valid
    chart (color: str | None) -- structured tooltip must simply not apply
    (matches cartesian's optional-header pattern), never assert-crash."""
    chart = HeatmapChart(id="t", type="heatmap", x="day", y="hour")
    labels = _render(chart, _HEATMAP_DATA)
    assert not any(ROLE_HEADER in lb for lb in labels), labels


def test_heatmap_header_x_before_y_before_value():
    chart = HeatmapChart(id="t", type="heatmap", x="day", y="hour", color="visits")
    labels = _render(chart, _HEATMAP_DATA)
    row = next(
        lb for lb in labels if f"{ROLE_HEADER}Mon" in lb and f"{ROLE_HEADER}9" in lb
    )
    assert row.index("Mon") < row.index("9") < row.index("Visits")


_PLAIN_SCATTER_DATA = [
    {"cost": 10.0, "revenue": 100.0},
    {"cost": 20.0, "revenue": 150.0},
]


def test_plain_scatter_no_header_two_peer_value_rows():
    """Plain scatter (no colour): no header row at all -- y (dependent)
    leads, x (independent) follows as a second peer value row, since
    neither axis alone identifies the point."""
    chart = ScatterChart(id="t", type="scatter", x="cost", y="revenue")
    labels = _render(chart, _PLAIN_SCATTER_DATA)
    assert labels, "expected at least one mark aria-label"
    assert not any(ROLE_HEADER in lb or ROLE_HEADER_SWATCHED in lb for lb in labels), (
        labels
    )
    assert not any(ROLE_SERIES in lb for lb in labels), labels
    row = next(lb for lb in labels if "Revenue: 100" in lb)
    assert "Cost: 10" in row, row
    assert row.index("Revenue") < row.index("Cost"), row


_COLORED_SCATTER_DATA = [
    {"cost": 10.0, "revenue": 100.0, "region": "North"},
    {"cost": 20.0, "revenue": 150.0, "region": "South"},
]


def test_colored_scatter_series_leads_as_swatched_header():
    """Colour channel present: the series identity leads as a swatched
    header-like line (mirrors pie's header_is_swatched), then the two peer
    value rows -- no separate series row, the header IS the series."""
    chart = ScatterChart(id="t", type="scatter", x="cost", y="revenue", color="region")
    labels = _render(chart, _COLORED_SCATTER_DATA)
    row = next(lb for lb in labels if f"{ROLE_HEADER_SWATCHED}North" in lb)
    assert "Revenue: 100" in row, row
    assert "Cost: 10" in row, row
    assert row.index(ROLE_HEADER_SWATCHED) < row.index("Revenue") < row.index("Cost")
    assert not any(ROLE_SERIES in lb for lb in labels), labels


_NEGATIVE_STACK_DATA = [
    {"day_name": "Mon", "count": 5.5, "kind": "task"},
    {"day_name": "Mon", "count": -2.0, "kind": "adjustment"},
    {"day_name": "Tue", "count": 3.3, "kind": "task"},
    {"day_name": "Tue", "count": 1.1, "kind": "adjustment"},
]


def test_normalize_stack_with_negative_value_falls_back_to_raw_only():
    """A negative segment makes percent/total ill-defined for a normalized
    (100%) stack -- fall back to the single raw value row, no % and no
    total footer, rather than emit a confidently-wrong percentage."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "normalize"}),
    )
    labels = _render(chart, _NEGATIVE_STACK_DATA)
    assert labels, "expected at least one aria-label"
    assert not any("Share" in lb for lb in labels), labels
    assert not any(ROLE_TOTAL in lb for lb in labels), labels
    row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert "Count: 5.5" in row, row


def test_zero_stack_with_negative_value_drops_total():
    """The same ill-defined-total guard applies to an absolute stack: a
    negative segment drops the group-total footer, not just the percent."""
    chart = BarChart(
        id="t",
        type="bar",
        x="day_name",
        y="count",
        color="kind",
        style=BarChartStylePatch.model_validate({"stack": "zero"}),
    )
    labels = _render(chart, _NEGATIVE_STACK_DATA)
    assert labels, "expected at least one aria-label"
    assert not any(ROLE_TOTAL in lb for lb in labels), labels
    row = next(
        lb for lb in labels if f"{ROLE_SERIES}task" in lb and f"{ROLE_HEADER}Mon" in lb
    )
    assert "Count: 5.5" in row, row


_SPARSE_SERIES_DATA = [
    {"day_name": "Mon", "count": 5.5, "kind": "task"},
    {"day_name": "Mon", "count": 2.0, "kind": "pr"},
    {"day_name": "Tue", "count": 3.3, "kind": "task"},
    # "pr" has no row at all for Tue -- must be OMITTED, never a placeholder.
]


def test_missing_series_at_x_is_omitted_not_a_placeholder_mark():
    """A series absent at one x must simply produce no mark for that (x,
    series) pair -- the emit layer never synthesizes a placeholder row for a
    combination the query didn't return. Filters to labels carrying a
    ROLE_HEADER marker so axis/legend aria-labels (which never carry the
    zero-width role markers) don't pollute the count."""
    chart = BarChart(id="t", type="bar", x="day_name", y="count", color="kind")
    labels = _render(chart, _SPARSE_SERIES_DATA)
    data_labels = [lb for lb in labels if ROLE_HEADER in lb]
    # No row's own value (5.5, 2.0, 3.3) is tiny relative to the others, so
    # BarHoverBandFeature correctly adds no hover band layer here at all (see
    # bar_hover_band.py's module docstring) -- one aria-labelled entry per
    # real data row, no doubling.
    assert len(data_labels) == len(_SPARSE_SERIES_DATA), data_labels
    assert not any(
        f"{ROLE_HEADER}Tue" in lb and f"{ROLE_SERIES}pr" in lb for lb in data_labels
    ), data_labels
    assert not any("—" in lb for lb in data_labels), data_labels
