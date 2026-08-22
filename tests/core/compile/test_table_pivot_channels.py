"""Tests for table chart pivot encoding channels: rows, columns, values.

TDD: write failing tests first, then implement.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.chart.authored import TableChart


class TestTableChartPivotChannels:
    """TableChart authored model: rows/columns/values fields."""

    def test_channels_absent_is_valid(self) -> None:
        """A bare table chart with no pivot channels is valid (flat display)."""
        chart = TableChart(type="table")
        assert chart.rows is None
        assert chart.columns is None
        assert chart.values is None

    def test_rows_accepted(self) -> None:
        chart = TableChart(type="table", rows=["region", "product"])
        assert chart.rows == ["region", "product"]

    def test_columns_single_field_accepted(self) -> None:
        chart = TableChart(type="table", columns=["quarter"])
        assert chart.columns == ["quarter"]

    def test_values_accepted(self) -> None:
        chart = TableChart(type="table", values=["revenue", "margin"])
        assert chart.values == ["revenue", "margin"]

    def test_all_channels_together(self) -> None:
        chart = TableChart(
            type="table",
            rows=["region"],
            columns=["quarter"],
            values=["revenue"],
        )
        assert chart.rows == ["region"]
        assert chart.columns == ["quarter"]
        assert chart.values == ["revenue"]

    def test_columns_with_two_fields_accepted(self) -> None:
        """Phase 2: multiple columns fields are valid for nested multi-dim pivot."""
        chart = TableChart(type="table", columns=["quarter", "year"])
        assert chart.columns == ["quarter", "year"]

    def test_columns_with_empty_list_accepted(self) -> None:
        """Empty columns list is equivalent to None — no pivot dimension."""
        chart = TableChart(type="table", columns=[])
        assert chart.columns == [] or chart.columns is None  # either is valid

    def test_field_on_rows_and_values_raises(self) -> None:
        """A field may not appear on two channels simultaneously."""
        with pytest.raises(ValidationError, match="region"):
            TableChart(
                type="table",
                rows=["region"],
                values=["region", "revenue"],
            )

    def test_field_on_columns_and_rows_raises(self) -> None:
        with pytest.raises(ValidationError, match="quarter"):
            TableChart(
                type="table",
                rows=["quarter"],
                columns=["quarter"],
                values=["revenue"],
            )

    def test_field_on_columns_and_values_raises(self) -> None:
        with pytest.raises(ValidationError, match="quarter"):
            TableChart(
                type="table",
                columns=["quarter"],
                values=["quarter", "revenue"],
            )

    def test_values_none_is_allowed(self) -> None:
        """values omitted (None) is valid — render infers values:* at render time."""
        chart = TableChart(
            type="table",
            rows=["region"],
            columns=["quarter"],
        )
        assert chart.values is None

    def test_extra_field_forbidden(self) -> None:
        """extra=forbid still enforced."""
        with pytest.raises(ValidationError):
            TableChart(type="table", unknown_field="oops")  # type: ignore[call-arg]


class TestTableChartChannelsRoundTrip:
    """Channels survive normalize_board compilation."""

    BOARD_YAML = """
title: Pivot Test
queries:
  sales:
    sql: "SELECT region, quarter, revenue FROM sales"
    source: test
charts:
  pivot_table:
    type: table
    query: sales
    rows:
      - region
    columns:
      - quarter
    values:
      - revenue
rows:
  - pivot_table
"""

    def test_channels_survive_normalization(self) -> None:
        from dbt_charts.core.compile.compiler import compile as compile_board

        result = compile_board(self.BOARD_YAML)
        assert result.errors == [], f"Compile errors: {result.errors}"
        chart = result.board.charts["pivot_table"]
        assert chart.rows == ["region"]
        assert chart.columns == ["quarter"]
        assert chart.values == ["revenue"]

    def test_no_channels_still_compiles(self) -> None:
        """A table chart with no channels compiles without errors."""
        from dbt_charts.core.compile.compiler import compile as compile_board

        yaml = """
title: Flat table
queries:
  q:
    sql: "SELECT a, b FROM t"
    source: test
charts:
  flat:
    type: table
    query: q
rows:
  - flat
"""
        result = compile_board(yaml)
        assert result.errors == [], f"Compile errors: {result.errors}"
        chart = result.board.charts["flat"]
        assert chart.rows is None
        assert chart.columns is None
        assert chart.values is None


class TestNormalizedChartPivotValidation:
    """Pivot channel invariants are pinned at the normalized trust boundary too,
    not only on the authored TableChart — so directly-built Chart objects must
    respect the no-field-on-two-channels rule."""

    def test_multi_column_accepted_on_normalized_chart(self) -> None:
        """Phase 2: multiple columns fields are valid on normalized Chart."""
        from dbt_charts.core.compile.models.chart.normalized import TableChart

        chart = TableChart(id="c", type="table", columns=["a", "b"])
        assert chart.columns == ["a", "b"]

    def test_field_on_two_channels_rejected_on_normalized_chart(self) -> None:
        with pytest.raises(ValidationError, match="region"):
            TableChart(id="c", type="table", rows=["region"], values=["region"])

    def test_single_column_pivot_accepted_on_normalized_chart(self) -> None:
        chart = TableChart(
            id="c", type="table", rows=["region"], columns=["q"], values=["rev"]
        )
        assert chart.columns == ["q"]
