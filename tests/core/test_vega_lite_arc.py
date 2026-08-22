"""Tests for Vega-Lite arc/pie chart behavior.

Split from test_vega_lite.py — arc chart aggregation tests.
"""

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import PieChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE = resolve_style(get_theme_style())


class TestArcChartNoHiddenAggregation:
    """Arc/pie charts should NOT silently aggregate data."""

    def test_pie_with_inner_radius_theta_has_no_aggregate(self, make_chart):
        """Pie chart with inner_radius (donut appearance) should not aggregate."""
        chart = make_chart(
            "pie", x="category", y="value", style={"pie": {"inner_radius": 0.5}}
        )
        data = [{"category": "A", "value": 30}, {"category": "B", "value": 70}]
        spec = generate_vega_lite_spec(chart, data)
        # Pie/donut now layers by default (default labels added at pipeline);
        # the arc encoding lives on layer[0].
        assert "aggregate" not in spec["layer"][0]["encoding"]["theta"]

    def test_pie_theta_has_no_aggregate(self, make_chart):
        chart = make_chart("pie", x="category", y="value")
        data = [{"category": "A", "value": 30}, {"category": "B", "value": 70}]
        spec = generate_vega_lite_spec(chart, data)
        # Pie/donut now layers by default (default labels added at pipeline);
        # the arc encoding lives on layer[0].
        assert "aggregate" not in spec["layer"][0]["encoding"]["theta"]

    def test_arc_type_rejected_by_generate_vega_lite_spec(self):
        """arc is not an authorable chart type (not in the Chart union). A chart
        forced into that state (e.g. by a bug elsewhere) fails fast in resolve()
        rather than silently rendering."""
        chart = PieChart(
            id="t",
            type="pie",
            theta="value",
            color="category",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
        )
        object.__setattr__(chart, "type", "arc")
        data = [{"category": "A", "value": 30}]
        with pytest.raises(ValueError, match="Unknown normalized chart type"):
            generate_vega_lite_spec(chart, data)


class TestArcChartSpacing:
    """Arc radius uses Vega signal expressions so it always fits the view."""

    def test_pie_outerRadius_is_expression(self, make_chart):
        """outerRadius must be a Vega signal expr, not a fixed pixel value, so it
        adapts to the actual view width after legend placement."""
        chart = make_chart("pie", x="category", y="value")
        data = [{"category": "A", "value": 30}, {"category": "B", "value": 70}]
        spec = generate_vega_lite_spec(chart, data, width=300, height=300)

        outer = spec["layer"][0]["mark"]["outerRadius"]
        assert isinstance(outer, dict) and "expr" in outer, (
            "outerRadius must be a Vega ExprRef so the radius adapts to the actual "
            "view dimensions; a fixed pixel value clips the arc when labels are long"
        )

    def test_pie_with_inner_radius_both_radii_are_expressions(self, make_chart):
        """Both outerRadius and innerRadius must be expressions for pie with style.inner_radius."""
        chart = make_chart(
            "pie", x="category", y="value", style={"pie": {"inner_radius": 0.5}}
        )
        data = [{"category": "A", "value": 30}, {"category": "B", "value": 70}]
        spec = generate_vega_lite_spec(chart, data, width=400, height=400)

        mark = spec["layer"][0]["mark"]
        assert (
            isinstance(mark.get("outerRadius"), dict) and "expr" in mark["outerRadius"]
        )
        assert (
            isinstance(mark.get("innerRadius"), dict) and "expr" in mark["innerRadius"]
        )

    def test_pie_landscape_radius_fits_short_axis(self, make_chart):
        """Non-square chart: min(width, height) must use the shorter axis."""
        chart = make_chart("pie", x="category", y="value")
        data = [{"category": "A", "value": 30}, {"category": "B", "value": 70}]
        spec = generate_vega_lite_spec(chart, data, width=600, height=200)

        outer = spec["layer"][0]["mark"]["outerRadius"]
        # Expression must reference both axes so the shorter one constrains the radius
        assert isinstance(outer, dict) and "expr" in outer
        assert (
            "min(" in outer["expr"]
            and "width" in outer["expr"]
            and "height" in outer["expr"]
        )
