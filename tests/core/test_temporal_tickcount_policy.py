"""Regression tests for temporal x-axis tick cadence policy.

After removing the per-data-bucket tickCount cap, temporal x-axes must NOT
emit an *automatic* tickCount derived from the data's bucket count — VL's
smart default produces ~8 ticks aligned with the label cadence instead of one
tick per data bucket.

This is distinct from an *authored* ``axis_x.ticks.count`` on a genuinely
VL-type-temporal x scale (continuous, or ordinal-density-gate-flipped): that
explicit author input DOES map to VL's ``axis.tickCount`` (see
``test_authored_ticks_count_reaches_tickcount_on_density_flipped_temporal``
below) — VL's time-scale tick logic honors a plain numeric tickCount as a
target, unlike the advisory tickCount on quantitative scales. The tests above
all resolve to VL type "ordinal" (24 months < MAX_ORDINAL_BUCKETS), where
ticks.count has no meaning (a discrete-domain scale has no "count" concept)
regardless of whether it was authored or auto-derived.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_RS, _BOARD_CTX = resolve_style_and_context(get_theme_style())


def _monthly_data(n: int = 24) -> list[dict]:
    rows = []
    for i in range(n):
        year = 2023 + i // 12
        month = (i % 12) + 1
        rows.append({"month": f"{year}-{month:02d}-01", "revenue": i * 100})
    return rows


def test_temporal_axis_does_not_emit_tickcount():
    """Temporal x-axis must NOT set tickCount — VL owns the cadence."""
    chart = BarChart(id="test", type="bar", x="month", y="revenue")
    data = _monthly_data(24)
    resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = render_resolved_chart(resolved, data, _BOARD_RS).payload

    x_axis = spec.get("encoding", {}).get("x", {}).get("axis", {})
    assert "tickCount" not in x_axis, (
        f"Temporal x-axis must not emit tickCount; got axis={x_axis}"
    )


def test_temporal_axis_tickcount_absent_for_small_datasets():
    """tickCount cap must not be applied even for small temporal datasets."""
    chart = BarChart(id="test", type="bar", x="month", y="revenue")
    data = _monthly_data(3)
    resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = render_resolved_chart(resolved, data, _BOARD_RS).payload

    x_axis = spec.get("encoding", {}).get("x", {}).get("axis", {})
    assert "tickCount" not in x_axis, (
        f"tickCount must not be emitted even for small datasets; got axis={x_axis}"
    )


def test_axis_x_ticks_count_does_not_affect_ordinal_x():
    """ticks.count set on axis_x must not emit tickCount on an ordinal x-axis.

    24 monthly buckets stay under MAX_ORDINAL_BUCKETS, so this bucketed-time
    axis resolves to VL type "ordinal" — a discrete-domain scale where
    tickCount has no meaning. Authored count only takes effect once the axis
    is genuinely VL-type-temporal (see
    test_authored_ticks_count_reaches_tickcount_on_density_flipped_temporal).
    """
    from dbt_charts.core.compile.models.style.authored import (
        AxisXStylePatch,
        BarChartStylePatch,
        DimensionTicksStylePatch,
    )

    chart = BarChart(
        id="test",
        type="bar",
        x="month",
        y="revenue",
        style=BarChartStylePatch(
            axis_x=AxisXStylePatch(ticks=DimensionTicksStylePatch(count=6))
        ),
    )
    data = _monthly_data(24)
    resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = render_resolved_chart(resolved, data, _BOARD_RS).payload

    x_axis = spec.get("encoding", {}).get("x", {}).get("axis", {})
    # tickCount must not appear — ordinal scales have no tick-count concept.
    assert "tickCount" not in x_axis, (
        f"Ordinal x-axis must not emit tickCount; got axis={x_axis}"
    )


def test_authored_ticks_count_reaches_tickcount_on_density_flipped_temporal():
    """Authored axis_x.ticks.count DOES reach VL tickCount once the density gate
    flips a bucketed monthly axis to genuine VL type "temporal" (> MAX_ORDINAL_
    BUCKETS buckets) — this is the behavior task GRAPH_LIBRARY-TEMPORAL_AXES_
    IGNORE_TICKSTEP_TICKVALUES_AND_TICKS_COUNT fixes. Contrast with the ordinal
    tests above, where ticks.count has no effect because the scale never
    becomes VL-type-temporal.
    """
    from dbt_charts.core.compile.models.style.authored import (
        AxisXStylePatch,
        BarChartStylePatch,
        DimensionTicksStylePatch,
    )

    chart = BarChart(
        id="test",
        type="bar",
        x="month",
        y="revenue",
        style=BarChartStylePatch(
            axis_x=AxisXStylePatch(ticks=DimensionTicksStylePatch(count=8))
        ),
    )
    data = _monthly_data(
        72
    )  # 6 years > MAX_ORDINAL_BUCKETS (60) -> density gate flips to temporal
    resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = render_resolved_chart(resolved, data, _BOARD_RS).payload

    x_enc = spec.get("encoding", {}).get("x", {})
    assert x_enc.get("type") == "temporal"
    assert x_enc.get("axis", {}).get("tickCount") == 8
