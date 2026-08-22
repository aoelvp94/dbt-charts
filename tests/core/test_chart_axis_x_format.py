"""style.axis_x.format flows to encoding.x.axis.format in the Vega-Lite spec.

The authored axis_x.format field (an AxisXStylePatch attribute) must land
in the Vega-Lite encoding x axis config so temporal x-axes show clean labels.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.normalized import BarChart, Chart
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec


def _temporal_chart(**kwargs) -> Chart:
    defaults = {"id": "test_x_fmt", "type": "bar", "x": "revenue_month", "y": "revenue"}
    defaults.update(kwargs)
    return BarChart(**defaults)


def _month_data() -> list[dict]:
    return [
        {"revenue_month": "2024-01-01", "revenue": 1_000_000},
        {"revenue_month": "2024-02-01", "revenue": 1_100_000},
        {"revenue_month": "2024-03-01", "revenue": 900_000},
    ]


class TestAxisXFormatFlowsToVegaLite:
    def test_axis_x_format_routes_through_label_expr_on_ordinal(self) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            AxisXStylePatch,
            BarChartStylePatch,
            DimensionLabelStylePatch,
        )

        chart = _temporal_chart(
            style=BarChartStylePatch(
                axis_x=AxisXStylePatch(labels=DimensionLabelStylePatch(format="%b %Y"))
            )
        )
        vl_spec = generate_vega_lite_spec(chart, _month_data())

        x_encoding = vl_spec.get("encoding", {}).get("x", {})
        x_axis = x_encoding.get("axis", {})
        # Authored time-format on ordinal axis routes through labelExpr —
        # `formatType: "time"` silently drops labels on string-domain ordinal.
        assert x_axis.get("labelExpr") == "utcFormat(toDate(datum.value), '%b %Y')", (
            f"expected utcFormat labelExpr in encoding.x.axis; got {x_axis}"
        )

    def test_ordinal_default_injects_label_expr(self) -> None:
        # D-002: bucketed-time ordinal axes get a smart default labelExpr that
        # mirrors the temporal-path multi-cadence behavior — under yearmonth,
        # `Jan` shows the year stamped on a second line, every other month is
        # just the month abbreviation. Routes through utcFormat(toDate(...))
        # rather than formatType=time (which silently drops every label on a
        # string-domain ordinal scale).
        chart = _temporal_chart()
        vl_spec = generate_vega_lite_spec(chart, _month_data())

        x_encoding = vl_spec.get("encoding", {}).get("x", {})
        x_axis = x_encoding.get("axis", {})
        label_expr = x_axis.get("labelExpr", "")
        assert "utcmonth(toDate(datum.value)) === 0" in label_expr, (
            f"expected smart yearmonth labelExpr; got {x_axis}"
        )
        assert "utcFormat(toDate(datum.value), '%b')" in label_expr, (
            f"expected month-name format in labelExpr; got {label_expr}"
        )
        assert "utcFormat(toDate(datum.value), '%Y')" in label_expr, (
            f"expected year stamp on Jan in labelExpr; got {label_expr}"
        )
        assert x_axis.get("formatType") != "time"
        assert "format" not in x_axis
