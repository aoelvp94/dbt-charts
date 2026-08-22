"""Regression tests for stacked-bar scale.domainMax pinning.

stacked_bar_totals_max computes the per-category stacked total and pins it as
scale.domainMax (times the theme's measure-axis headroom multiplier, 2026-07-16)
so the measure axis spans the full bar extent plus a bit of top breathing room.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style_and_context,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec


def _make_stacked_bar_spec(data, orientation="vertical", theme="cream"):
    reset_config()
    rs, ctx = resolve_style_and_context(get_theme_style(theme))
    chart_kwargs: dict[str, object] = {
        "id": "stacked_bar",
        "type": "bar",
        "x": "category",
        "y": "value",
        "color": "series",
        "query": SqlQuery(sql="SELECT 1", source="src"),
        "query_name": "q",
    }
    chart_kwargs["style"] = BarChartStylePatch.model_validate(
        {"orientation": orientation, "stack": "zero"}
    )
    chart = BarChart(**chart_kwargs)
    return generate_vega_lite_spec(
        chart, data, width=400, board_style=rs, chart_style_context=ctx
    )


def _chart_pane(spec: dict) -> dict:
    """Extract the chart pane from a potentially endpoint-label-wrapped spec.

    Vertical stacked bar with endpoint labels wraps in hconcat: chart is [0].
    Horizontal stacked bar with endpoint labels wraps in vconcat: chart is [1]
    (rail pane is [0]).
    """
    if "hconcat" in spec:
        return spec["hconcat"][0]
    if "vconcat" in spec:
        return spec["vconcat"][1]
    return spec


# un-stacked max = 20 (B/series1), stacked max = 32 (B total)
_DATA = [
    {"category": "A", "series": "s1", "value": 10},
    {"category": "A", "series": "s2", "value": 8},
    {"category": "B", "series": "s1", "value": 20},
    {"category": "B", "series": "s2", "value": 12},
]
_STACKED_MAX = 32


def _expected_stacked_domain_max(theme: str) -> float:
    """Stacked total times the theme's measure-axis headroom (0 if unset)."""
    ctx = resolve_chart_style_context(get_theme_style(theme))
    headroom = ctx.axis_y.scale.headroom if ctx.axis_y.scale else None
    return _STACKED_MAX * (1 + (headroom or 0))


def test_stacked_bar_scale_domain_max_covers_stacked_total():
    spec = _make_stacked_bar_spec(_DATA)
    chart = _chart_pane(spec)
    y_scale = chart.get("encoding", {}).get("y", {}).get("scale", {})
    domain_max = y_scale.get("domainMax")
    expected = _expected_stacked_domain_max("cream")
    assert domain_max is not None, f"scale.domainMax must be set; got scale={y_scale}"
    assert domain_max == expected, (
        f"scale.domainMax must equal the headroom-applied stacked total ({expected}), "
        f"not the un-stacked raw max (20) or the bare stacked total ({_STACKED_MAX}); "
        f"got domainMax={domain_max}"
    )


def test_stacked_bar_horizontal_scale_domain_max_covers_stacked_total():
    spec = _make_stacked_bar_spec(_DATA, orientation="horizontal")
    chart = _chart_pane(spec)
    x_scale = chart.get("encoding", {}).get("x", {}).get("scale", {})
    domain_max = x_scale.get("domainMax")
    expected = _expected_stacked_domain_max("cream")
    assert domain_max is not None, (
        f"scale.domainMax must be set on x-axis (measure) for horizontal "
        f"stacked bar; got x.scale={x_scale}"
    )
    assert domain_max == expected, (
        f"x.scale.domainMax must equal the headroom-applied stacked total "
        f"({expected}); got domainMax={domain_max}"
    )
