"""Regression: horizontal bar categorical y-axis must not parity-drop labels."""

from __future__ import annotations

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.emitters._cartesian import (
    min_height_for_horizontal_bar_categories,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec, render_chart

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())


def test_horizontal_bar_spec_never_parity_drops_y_labels(make_chart) -> None:
    owners = [f"owner-{i}" for i in range(13)]
    data = [{"owner": o, "count": i + 1} for i, o in enumerate(owners)]
    chart = make_chart(
        "bar",
        x="owner",
        y="count",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    _rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = generate_vega_lite_spec(chart, data, height=300)
    y_axis = spec["encoding"]["y"].get("axis", {})
    assert y_axis.get("labelOverlap") is False
    assert y_axis.get("labelAngle") == 0
    assert spec["height"] is not None and spec["height"] > 300


def test_horizontal_bar_svg_includes_every_category_label(make_chart) -> None:
    owners = ["dave", "christoph", "sr-engineer", "akankaluga"]
    data = [{"owner": o, "count": 10 - i} for i, o in enumerate(owners)]
    chart = make_chart(
        "bar",
        x="owner",
        y="count",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    svg = render_chart(
        chart,
        _BOARD_STYLE,
        _BOARD_CTX,
        data,
        format="svg",
        width=400,
        height=300,
    )
    for owner in owners:
        assert owner in svg, f"missing y-axis label for {owner!r} in rendered SVG"


def test_min_height_scales_with_category_count(make_chart) -> None:
    chart = make_chart("bar", x="owner", y="count")
    resolved = resolve(
        chart,
        [{"owner": "a", "count": 1}, {"owner": "b", "count": 2}],
        chart_style_context=_BOARD_CTX,
    )
    h2 = min_height_for_horizontal_bar_categories(
        2, resolved.style.axis_x, resolved.style.mark.size
    )
    h8 = min_height_for_horizontal_bar_categories(
        8, resolved.style.axis_x, resolved.style.mark.size
    )
    assert h8 > h2
    assert h2 > 0


def test_resolve_chart_postcondition_horizontal_bar_overlap_is_allow(
    make_chart,
) -> None:
    chart = make_chart(
        "bar",
        x="region",
        y="value",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    data = [{"region": "East", "value": 1}]
    # V2 resolves overlap at render time via resolve_axis_x_overlap; check the
    # emitted spec rather than the intermediate resolved model.
    spec = generate_vega_lite_spec(
        chart, data, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    y_axis = spec.get("encoding", {}).get("y", {}).get("axis", {})
    assert y_axis.get("labelOverlap") is False
