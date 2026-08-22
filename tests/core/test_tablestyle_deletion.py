"""Regression: TableChartStylePatch.table-level overrides reach build_chart_style_context.

After migrating from ChartStylePatch to per-family style patches, chart-local
table overrides must use TableChartStylePatch directly on a TableChart.
"""


def test_chart_local_table_nested_header_reaches_resolved_style():
    """TableChartStylePatch with nested header.background produces correct resolved_style."""
    from dbt_charts.core.compile.models.chart.normalized import TableChart
    from dbt_charts.core.compile.models.style.authored import TableChartStylePatch
    from dbt_charts.core.compile.models.style.theme import TableChartStyle
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context as _build_resolved_style,
    )

    patch = TableChartStylePatch.model_validate({"header": {"background": "#ff0000"}})
    es = _build_resolved_style(None, TableChart(id="t", type="table", style=patch))

    assert isinstance(es.table, TableChartStyle)
    assert es.table.header.background == "#ff0000"


def test_chart_local_table_nested_row_height():
    """TableChartStylePatch with nested row.height reaches resolved_style.table.row.height."""
    from dbt_charts.core.compile.models.chart.normalized import TableChart
    from dbt_charts.core.compile.models.style.authored import TableChartStylePatch
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context as _build_resolved_style,
    )

    patch = TableChartStylePatch.model_validate({"row": {"height": 28.0}})
    es = _build_resolved_style(None, TableChart(id="t", type="table", style=patch))
    assert es.table.row.height == 28.0


def test_chart_local_table_nested_font_size():
    """TableChartStylePatch with nested font.size reaches resolved_style.table.font.size."""
    from dbt_charts.core.compile.models.chart.normalized import TableChart
    from dbt_charts.core.compile.models.style.authored import TableChartStylePatch
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context as _build_resolved_style,
    )

    patch = TableChartStylePatch.model_validate({"font": {"size": 11.0}})
    es = _build_resolved_style(None, TableChart(id="t", type="table", style=patch))
    assert es.table.font.size == 11.0
