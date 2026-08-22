"""Tests for _classify_columns: the compact-vs-text classifier.

A column is compact when its measured demand <= _COMPACT_DEMAND_CEILING (~220px)
OR it has a spark config (spark columns own their width; they're not measured).
Everything else is a text column.
"""

from __future__ import annotations


class TestClassifyColumns:
    """Direct unit tests for _classify_columns."""

    def test_all_compact_columns(self):
        """Columns whose demand <= ceiling are all compact."""
        from dbt_charts.core.render.chart.table_support import _classify_columns

        demands = {"amount": 120.0, "count": 85.0, "rate": 95.0, "stage": 150.0}
        compact, text = _classify_columns(demands, {})
        assert compact == {"amount", "count", "rate", "stage"}
        assert text == set()

    def test_all_text_columns(self):
        """Columns whose demand > ceiling are all text."""
        from dbt_charts.core.render.chart.table_support import (
            _COMPACT_DEMAND_CEILING,
            _classify_columns,
        )

        d = _COMPACT_DEMAND_CEILING + 1
        demands = {"notes": d + 200, "description": d + 100, "summary": d + 50}
        compact, text = _classify_columns(demands, {})
        assert compact == set()
        assert text == {"notes", "description", "summary"}

    def test_mixed_columns(self):
        """Mixed table: compact and text columns classified correctly."""
        from dbt_charts.core.render.chart.table_support import _classify_columns

        demands = {
            "csm_name": 150.0,
            "account": 180.0,
            "arr": 100.0,
            "stage": 130.0,
            "plan_type": 120.0,
            "next_steps": 2500.0,
        }
        compact, text = _classify_columns(demands, {})
        assert compact == {"csm_name", "account", "arr", "stage", "plan_type"}
        assert text == {"next_steps"}

    def test_demand_exactly_at_ceiling_is_compact(self):
        """Demand exactly at the ceiling is compact (boundary condition)."""
        from dbt_charts.core.render.chart.table_support import (
            _COMPACT_DEMAND_CEILING,
            _classify_columns,
        )

        demands = {"col": float(_COMPACT_DEMAND_CEILING)}
        compact, text = _classify_columns(demands, {})
        assert "col" in compact
        assert "col" not in text

    def test_demand_one_above_ceiling_is_text(self):
        """Demand one pixel above ceiling is text."""
        from dbt_charts.core.render.chart.table_support import (
            _COMPACT_DEMAND_CEILING,
            _classify_columns,
        )

        demands = {"col": float(_COMPACT_DEMAND_CEILING) + 1.0}
        compact, text = _classify_columns(demands, {})
        assert "col" in text
        assert "col" not in compact

    def test_spark_column_is_compact_regardless_of_demand(self):
        """Spark columns are compact at their declared size, not measured."""
        from dbt_charts.core.compile.models.chart.authored import (
            SparkConfig,
            TableColumnConfig,
        )
        from dbt_charts.core.render.chart.table_support import _classify_columns

        column_configs = {
            "trend": TableColumnConfig(spark=SparkConfig(type="line", width=120))
        }
        # Even if the demand were huge, spark columns are compact
        demands = {"trend": 9999.0, "notes": 9999.0}
        compact, text = _classify_columns(demands, column_configs)
        assert "trend" in compact
        assert "notes" in text

    def test_empty_demands(self):
        """Empty demands returns empty sets."""
        from dbt_charts.core.render.chart.table_support import _classify_columns

        compact, text = _classify_columns({}, {})
        assert compact == set()
        assert text == set()

    def test_single_compact_column(self):
        """Single compact column: compact set has it, text set is empty."""
        from dbt_charts.core.render.chart.table_support import _classify_columns

        compact, text = _classify_columns({"amount": 100.0}, {})
        assert compact == {"amount"}
        assert text == set()

    def test_single_text_column(self):
        """Single text column: text set has it, compact set is empty."""
        from dbt_charts.core.render.chart.table_support import (
            _COMPACT_DEMAND_CEILING,
            _classify_columns,
        )

        demands = {"next_steps": float(_COMPACT_DEMAND_CEILING) * 10}
        compact, text = _classify_columns(demands, {})
        assert compact == set()
        assert text == {"next_steps"}
