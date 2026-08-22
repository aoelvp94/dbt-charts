"""Tests for pivot_table_data's single-dim single-measure shape and table
chart pivot channels.

The query-level Pivot model has been retired. This file covers:
  - pivot_table_data's single-dim single-measure path with rows omitted
    (inferred): headers, values, row count, missing-cell-as-None, empty
    input, duplicate-cell and missing-key error diagnostics
  - chart-level rows/columns/values survive normalization (replaces old query.pivot tests)
"""

from __future__ import annotations

import pytest


class TestPivotTableDataSingleDimSingleMeasure:
    DATA = [
        {"region": "US", "month": "Jan", "amount": 100},
        {"region": "US", "month": "Feb", "amount": 200},
        {"region": "EU", "month": "Jan", "amount": 150},
        {"region": "EU", "month": "Feb", "amount": 250},
    ]

    def test_headers(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, _, __ = pivot_table_data(
            self.DATA, rows=[], columns=["month"], values=["amount"]
        )
        h = list(wide[0].keys())
        assert "region" in h and "Jan" in h and "Feb" in h
        assert "month" not in h and "amount" not in h

    def test_values(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, _, __ = pivot_table_data(
            self.DATA, rows=[], columns=["month"], values=["amount"]
        )
        us = next(r for r in wide if r["region"] == "US")
        assert us["Jan"] == 100 and us["Feb"] == 200

    def test_row_count(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, _, __ = pivot_table_data(
            self.DATA, rows=[], columns=["month"], values=["amount"]
        )
        assert len(wide) == 2

    def test_missing_cell_is_none(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        sparse = [
            {"region": "US", "month": "Jan", "amount": 100},
            {"region": "EU", "month": "Feb", "amount": 250},
        ]
        wide, _, __ = pivot_table_data(
            sparse, rows=[], columns=["month"], values=["amount"]
        )
        us = next(r for r in wide if r["region"] == "US")
        eu = next(r for r in wide if r["region"] == "EU")
        assert us["Feb"] is None and eu["Jan"] is None


class TestPivotTableDataSingleDimEdgeCases:
    def test_empty_data_returns_empty(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, groups, effective = pivot_table_data(
            [], rows=[], columns=["month"], values=["amount"]
        )
        assert wide == []
        assert groups is None
        assert effective == []

    def test_duplicate_row_col_raises_chart_data_error(self) -> None:
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        duplicate = [
            {"region": "US", "month": "Jan", "amount": 100},
            {"region": "US", "month": "Jan", "amount": 999},  # duplicate key
        ]
        with pytest.raises(ChartDataError, match="duplicate"):
            pivot_table_data(duplicate, rows=[], columns=["month"], values=["amount"])

    def test_duplicate_with_none_first_raises(self) -> None:
        """A None measure value must not bypass duplicate detection."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        duplicate_with_none = [
            {"region": "US", "month": "Jan", "amount": None},
            {"region": "US", "month": "Jan", "amount": 100},
        ]
        with pytest.raises(ChartDataError, match="duplicate"):
            pivot_table_data(
                duplicate_with_none, rows=[], columns=["month"], values=["amount"]
            )

    def test_missing_column_key_raises_chart_data_error(self) -> None:
        """Regression: pivot column not in data rows must raise, not silently no-op."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"date_month": "2024-01", "total_volume": 100},
            {"date_month": "2024-02", "total_volume": 200},
            {"date_month": "2024-03", "total_volume": 300},
        ]
        with pytest.raises(ChartDataError, match="accounts.date_month"):
            pivot_table_data(
                data,
                rows=[],
                columns=["accounts.date_month"],
                values=["connections.total_volume"],
            )

    def test_missing_value_key_raises_chart_data_error(self) -> None:
        """pivot value column not in data rows must raise with a clear diagnostic."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "amount": 100},
        ]
        with pytest.raises(ChartDataError, match="connections.total_volume"):
            pivot_table_data(
                data, rows=[], columns=["month"], values=["connections.total_volume"]
            )


class TestTableChartChannelsSurviveNormalization:
    """chart-level rows/columns/values survive the full compile pipeline."""

    PIVOT_BOARD_YAML = """
title: Pivot Test
queries:
  sales_by_region_month:
    sql: "SELECT region, month, SUM(amount) AS amount FROM t"
    source: test
charts:
  cross_tab:
    type: table
    title: Sales Cross-Tab
    query: sales_by_region_month
    rows:
      - region
    columns:
      - month
    values:
      - amount
rows:
  - cols:
      - cross_tab
"""

    def test_channels_survive_normalization(self) -> None:
        """After normalize_board, chart.rows/columns/values must be preserved."""
        from dbt_charts.core.compile.compiler import compile as compile_board

        result = compile_board(self.PIVOT_BOARD_YAML)
        assert result.errors == [], f"Compile errors: {result.errors}"
        chart = result.board.charts["cross_tab"]
        assert chart.rows == ["region"], "chart.rows lost during normalization"
        assert chart.columns == ["month"], "chart.columns lost during normalization"
        assert chart.values == ["amount"], "chart.values lost during normalization"

    def test_table_without_channels_compiles(self) -> None:
        """A flat table chart (no pivot channels) still compiles cleanly."""
        from dbt_charts.core.compile.compiler import compile as compile_board

        flat_yaml = """
title: Flat Table
queries:
  q:
    sql: "SELECT region, month, amount FROM t"
    source: test
charts:
  flat:
    type: table
    query: q
rows:
  - flat
"""
        result = compile_board(flat_yaml)
        assert result.errors == [], f"Compile errors: {result.errors}"
        chart = result.board.charts["flat"]
        assert chart.rows is None
        assert chart.columns is None
        assert chart.values is None
