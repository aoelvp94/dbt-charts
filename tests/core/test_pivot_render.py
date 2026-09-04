"""Tests for render-layer multi-measure pivot (Step 2 of Phase 1).

Covers:
- pivot_table_data: multi-measure reshape correctness
- single-measure backward-compat: column names are col-values, 1-row header
- multi-measure SVG has a 2-row header with group spans and measure sub-labels
- duplicate-cell ChartDataError message hints "move the extra field onto rows or columns"
- values:* inference when values=None
- empty data falls through to normal empty-state
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import TableChart
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_style,
    resolve_style_and_context,
)
from dbt_charts.core.diagnostics.chart_data import ChartDataError

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _board_style() -> Any:
    return resolve_style(get_theme_style())


def _make_pivot_resolved_chart(
    rows: list[str],
    columns: list[str],
    values: list[str] | None,
    make_chart: Any,
) -> Any:
    """Build a ResolvedChart with pivot channels set on source_chart."""
    from dbt_charts.core.compile.models.chart.normalized import TableChart
    from dbt_charts.core.compile.models.query.normalized import SqlQuery

    # Build a Chart directly with rows/columns/values set.
    chart = TableChart(
        id="pivot_test",
        type="table",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        rows=rows,
        columns=columns,
        values=values,
    )
    return resolve(chart, [], chart_style_context=_BOARD_CTX)


# ---------------------------------------------------------------------------
# Unit tests for pivot_table_data
# ---------------------------------------------------------------------------


class TestPivotTableDataNotAPivot:
    """No column dimension → not a pivot; the rows pass through untouched.

    This is the shared gate: the renderer and the layout sizer both call
    unconditionally, so neither owns a private predicate for "is this a pivot?"
    """

    DATA = [{"region": "US", "amount": 100}, {"region": "EU", "amount": 150}]

    @pytest.mark.parametrize("columns", [None, []])
    def test_rows_pass_through(self, columns: list[str] | None) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, groups, effective_values = pivot_table_data(
            self.DATA, rows=[], columns=columns, values=None
        )
        assert wide == self.DATA
        assert groups is None
        assert effective_values == []


class TestPivotTableDataSingleMeasure:
    """Single-measure pivot: leaf names are col-values (backward compat)."""

    DATA = [
        {"region": "US", "month": "Jan", "amount": 100},
        {"region": "US", "month": "Feb", "amount": 200},
        {"region": "EU", "month": "Jan", "amount": 150},
        {"region": "EU", "month": "Feb", "amount": 250},
    ]

    def test_leaf_columns_are_col_values(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, groups, _ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["amount"]
        )
        keys = list(wide[0].keys())
        assert "region" in keys
        assert "Jan" in keys
        assert "Feb" in keys
        assert "month" not in keys
        assert "amount" not in keys

    def test_cell_values_land_correctly(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["amount"]
        )
        us = next(r for r in wide if r["region"] == "US")
        assert us["Jan"] == 100
        assert us["Feb"] == 200

    def test_groups_is_none_for_single_measure(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["amount"]
        )
        assert groups is None

    def test_row_count(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["amount"]
        )
        assert len(wide) == 2

    def test_sparse_cell_is_none(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        sparse = [
            {"region": "US", "month": "Jan", "amount": 100},
            {"region": "EU", "month": "Feb", "amount": 250},
        ]
        wide, *_ = pivot_table_data(
            sparse, rows=["region"], columns=["month"], values=["amount"]
        )
        us = next(r for r in wide if r["region"] == "US")
        eu = next(r for r in wide if r["region"] == "EU")
        assert us["Feb"] is None
        assert eu["Jan"] is None


class TestPivotTableDataMultiMeasure:
    """Multi-measure pivot: leaf names are (col_value, measure) tuples encoded in key."""

    DATA = [
        {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
        {"region": "US", "month": "Feb", "revenue": 200, "cost": 110},
        {"region": "EU", "month": "Jan", "revenue": 150, "cost": 90},
        {"region": "EU", "month": "Feb", "revenue": 250, "cost": 140},
    ]

    def test_leaf_count_equals_distinct_cols_times_measures(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        row = wide[0]
        # row_dim keys + 2 cols × 2 measures = 1 + 4 leaf cols
        assert len(row) == 5  # region + Jan_revenue + Jan_cost + Feb_revenue + Feb_cost

    def test_cell_values_land_correctly(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        us = next(r for r in wide if r["region"] == "US")
        # Leaf keys format: col_val + separator + measure (implementation detail tested
        # via values, not via key names — key names are internal)
        # Find the key whose value is 100 (US/Jan/revenue)
        jan_rev_keys = [k for k, v in us.items() if v == 100]
        assert len(jan_rev_keys) == 1, (
            f"Expected exactly one key with value 100, got {us}"
        )
        jan_cost_keys = [k for k, v in us.items() if v == 60]
        assert len(jan_cost_keys) == 1, (
            f"Expected exactly one key with value 60, got {us}"
        )

    def test_groups_returned_for_multi_measure(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        assert groups is not None
        # Single col-dim + multi-measure → 1 group-header level (col-dim only).
        # No measure level: the leaf row already shows measure names.
        assert len(groups) == 1
        # The one level: col-dim spans (Jan, Feb).
        col_level = groups[0]
        labels = [g[0] for g in col_level]
        assert "Jan" in labels
        assert "Feb" in labels

    def test_each_group_spans_n_measure_leaves(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        assert groups is not None
        col_level = groups[0]
        for label, _first_idx, n_leaves in col_level:
            assert n_leaves == 2, (
                f"Group {label!r} should span 2 measures, got {n_leaves}"
            )

    def test_sparse_cell_is_none(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        sparse = [
            {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
            {"region": "EU", "month": "Feb", "revenue": 250, "cost": 140},
        ]
        wide, *_ = pivot_table_data(
            sparse, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        us = next(r for r in wide if r["region"] == "US")
        eu = next(r for r in wide if r["region"] == "EU")
        # US/Feb and EU/Jan should both be None for both measures
        feb_keys = [k for k in us if "Feb" in str(k)]
        for k in feb_keys:
            assert us[k] is None, f"US/Feb/{k} should be None for sparse data"
        jan_keys = [k for k in eu if "Jan" in str(k)]
        for k in jan_keys:
            assert eu[k] is None, f"EU/Jan/{k} should be None for sparse data"


class TestPivotTableDataInference:
    """values=None should infer all columns not in rows or column."""

    def test_values_inference_omits_rows_and_column_field(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
            {"region": "EU", "month": "Jan", "revenue": 150, "cost": 90},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=None
        )
        # With values=None, inferred = ["revenue", "cost"]
        # Single-measure inference only when exactly 1 value — but here 2 values
        # so we get multi-measure layout. Let's just check cell counts.
        # 1 row dim + 1 col (Jan) × 2 measures = 1 + 2 = 3 keys per row
        assert len(wide[0]) == 3

    def test_values_inference_single_remaining_column(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "revenue": 100},
            {"region": "EU", "month": "Jan", "revenue": 150},
        ]
        # With values=None, inferred = ["revenue"] → single-measure path
        wide, groups, _ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=None
        )
        assert groups is None, "Single inferred value should use single-measure path"
        # Keys: region + Jan
        assert "Jan" in wide[0]

    def test_values_inference_preserves_query_column_order(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "z_last": 1, "a_first": 2},
        ]
        # Inferred values should be ["z_last", "a_first"] (query column order)
        wide, groups, _ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=None
        )
        assert (
            groups is not None
        )  # 2 values → multi-measure; 1 group-header level (col-dim only, no measure level)
        # The one level = col-dim (month): one span for "Jan" covering 2 measure leaves.
        col_level = groups[0]
        assert len(col_level) == 1
        _, first_idx, n = col_level[0]
        assert n == 2


class TestPivotColumnOrder:
    """Pivot leaf columns follow the dimension's canonical order, not first-seen.

    A reader assumes a time pivot's columns are chronological (they are in
    every reference tool), so first-seen order is actively misleading there.
    Dimensions without a canonical order (plain strings, mixed content) keep
    first-seen (query) order — that's the documented lever for
    business-ordered categories and the trailing "Total" column pattern.
    """

    def _leaf_keys(self, wide: list[dict[str, Any]], row_dims: list[str]) -> list[str]:
        return [k for k in wide[0] if k not in row_dims]

    def test_temporal_string_columns_sort_chronologically(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # Dashboard-2223 shape: the result set first mentions months out of order.
        data = [
            {"region": "US", "month": "2026-06", "amount": 1},
            {"region": "US", "month": "2026-05", "amount": 2},
            {"region": "US", "month": "2026-07", "amount": 3},
            {"region": "EU", "month": "2026-05", "amount": 4},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["amount"]
        )
        assert self._leaf_keys(wide, ["region"]) == ["2026-05", "2026-06", "2026-07"]

    def test_non_lex_sortable_temporal_columns_sort_chronologically(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # "Mon YYYY" buckets sort lex-incorrectly (Aug < Jan) — the sort must
        # be chronological, not lexical.
        data = [
            {"region": "US", "month": "Aug 2026", "amount": 1},
            {"region": "US", "month": "Jan 2026", "amount": 2},
            {"region": "US", "month": "Mar 2026", "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["amount"]
        )
        assert self._leaf_keys(wide, ["region"]) == [
            "Jan 2026",
            "Mar 2026",
            "Aug 2026",
        ]

    def test_date_object_columns_sort_chronologically(self) -> None:
        import datetime as dt

        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "day": dt.date(2026, 3, 2), "amount": 1},
            {"region": "US", "day": dt.date(2026, 1, 15), "amount": 2},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["day"], values=["amount"]
        )
        assert self._leaf_keys(wide, ["region"]) == ["2026-01-15", "2026-03-02"]

    def test_numeric_columns_sort_ascending(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quantile": 10, "amount": 1},
            {"region": "US", "quantile": 2, "amount": 2},
            {"region": "US", "quantile": 5, "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["quantile"], values=["amount"]
        )
        # Numeric sort, not lexical ("10" < "2" lexically).
        assert self._leaf_keys(wide, ["region"]) == ["2", "5", "10"]

    def test_plain_string_columns_keep_first_seen_order(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # Bare month names have no parseable canonical order — the query's
        # ORDER BY stays the lever, so first-seen order must be preserved
        # (a lexical sort would scramble Jan/Feb into Feb/Jan).
        data = [
            {"region": "US", "month": "Jan", "amount": 1},
            {"region": "US", "month": "Feb", "amount": 2},
            {"region": "US", "month": "Mar", "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["amount"]
        )
        assert self._leaf_keys(wide, ["region"]) == ["Jan", "Feb", "Mar"]

    def test_mixed_temporal_and_total_keeps_first_seen_order(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # The documented trailing-"Total" column pattern: a dimension mixing
        # parseable dates with an unparseable literal has no canonical order,
        # so query order (which places "Total" last) is preserved.
        data = [
            {"region": "US", "month": "2026-05", "amount": 1},
            {"region": "US", "month": "2026-06", "amount": 2},
            {"region": "US", "month": "Total", "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["amount"]
        )
        assert self._leaf_keys(wide, ["region"]) == ["2026-05", "2026-06", "Total"]

    def test_null_column_value_sorts_last_in_temporal_dim(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": None, "amount": 1},
            {"region": "US", "month": "2026-06", "amount": 2},
            {"region": "US", "month": "2026-05", "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["amount"]
        )
        assert self._leaf_keys(wide, ["region"]) == ["2026-05", "2026-06", "None"]

    def test_multi_measure_group_levels_follow_sorted_order(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "2026-06", "revenue": 1, "cost": 2},
            {"region": "US", "month": "2026-05", "revenue": 3, "cost": 4},
        ]
        _, groups, __ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        assert groups is not None
        assert [g[0] for g in groups[0]] == ["2026-05", "2026-06"]
        # Spans must be re-derived from the sorted order: first group starts
        # at leaf 0, each spans the 2 measures.
        assert groups[0][0][1] == 0
        assert all(n == 2 for _, __, n in groups[0])

    def test_multi_dim_sorted_outer_groups_first_seen_inner(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # Outer dim (month) sorts chronologically; inner dim (tier, plain
        # strings) follows one consistent first-seen order across all groups.
        # Interleaved first-seen tuples must regroup into contiguous outer
        # spans.
        data = [
            {"region": "US", "month": "2026-06", "tier": "gold", "amount": 1},
            {"region": "US", "month": "2026-05", "tier": "gold", "amount": 2},
            {"region": "US", "month": "2026-06", "tier": "basic", "amount": 3},
            {"region": "US", "month": "2026-05", "tier": "basic", "amount": 4},
        ]
        wide, groups, _ = pivot_table_data(
            data, rows=["region"], columns=["month", "tier"], values=["amount"]
        )
        assert groups is not None
        assert [g[0] for g in groups[0]] == ["2026-05", "2026-06"]
        leaf_keys = [k for k in wide[0] if k != "region"]
        assert leaf_keys.index("2026-05\x1egold") < leaf_keys.index("2026-06\x1egold")

    def test_unsortable_outer_dim_keeps_contiguous_first_seen_groups(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # Unsortable OUTER dim + sortable inner dim: the outer dim must keep
        # its first-seen order as contiguous groups (gold before basic), with
        # months sorted within each. A sort ignoring the outer dim's
        # first-seen key would order by month alone and shatter the outer
        # spans (basic, gold, basic).
        data = [
            {"region": "US", "tier": "gold", "month": "2026-06", "amount": 1},
            {"region": "US", "tier": "basic", "month": "2026-05", "amount": 2},
            {"region": "US", "tier": "gold", "month": "2026-05", "amount": 3},
            {"region": "US", "tier": "basic", "month": "2026-06", "amount": 4},
        ]
        wide, groups, _ = pivot_table_data(
            data, rows=["region"], columns=["tier", "month"], values=["amount"]
        )
        assert groups is not None
        assert [g[0] for g in groups[0]] == ["gold", "basic"]
        leaf_keys = [k for k in wide[0] if k != "region"]
        assert leaf_keys == [
            "gold\x1e2026-05",
            "gold\x1e2026-06",
            "basic\x1e2026-05",
            "basic\x1e2026-06",
        ]

    def test_all_unsortable_dims_pass_through_untouched(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # No dimension has a canonical order → the col-tuples must come back
        # in exact first-seen order, interleaved outer values included: a
        # regroup by per-dim first-seen keys would move (US, basic) before
        # (EU, gold).
        data = [
            {"region": "r1", "team": "US", "tier": "gold", "amount": 1},
            {"region": "r1", "team": "EU", "tier": "gold", "amount": 2},
            {"region": "r1", "team": "US", "tier": "basic", "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["team", "tier"], values=["amount"]
        )
        leaf_keys = [k for k in wide[0] if k != "region"]
        assert leaf_keys == ["US\x1egold", "EU\x1egold", "US\x1ebasic"]

    def test_decimal_nan_dim_keeps_first_seen_order_without_crashing(self) -> None:
        from decimal import Decimal

        from dbt_charts.core.render.chart.table import pivot_table_data

        # Decimal("NaN") raises decimal.InvalidOperation under ordering
        # comparison — a NaN anywhere in the dimension must drop it to
        # first-seen order, not crash the render.
        data = [
            {"region": "US", "bucket": Decimal("2"), "amount": 1},
            {"region": "US", "bucket": Decimal("NaN"), "amount": 2},
            {"region": "US", "bucket": Decimal("1"), "amount": 3},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["bucket"], values=["amount"]
        )
        assert [k for k in wide[0] if k != "region"] == ["2", "NaN", "1"]

    def test_bool_dim_keeps_first_seen_order(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        # Bools are int subclasses but not values a reader ranks — the
        # documented contract sorts only dates and numbers, so a bool
        # dimension follows query order.
        data = [
            {"region": "US", "is_returning": True, "amount": 1},
            {"region": "US", "is_returning": False, "amount": 2},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["is_returning"], values=["amount"]
        )
        assert [k for k in wide[0] if k != "region"] == ["True", "False"]

    def test_cell_values_follow_sorted_columns(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "2026-06", "amount": 60},
            {"region": "US", "month": "2026-05", "amount": 50},
        ]
        wide, *_ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["amount"]
        )
        # Assert over items() so the ORDER of (key, value) pairs is pinned —
        # a lookup by key would pass on unsorted columns too.
        assert list(wide[0].items()) == [
            ("region", "US"),
            ("2026-05", 50),
            ("2026-06", 60),
        ]


class TestPivotTableDataErrors:
    """Duplicate cells and missing keys raise ChartDataError with helpful messages."""

    def test_duplicate_cell_raises_with_hint(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        duplicate = [
            {"region": "US", "month": "Jan", "revenue": 100},
            {"region": "US", "month": "Jan", "revenue": 999},  # duplicate
        ]
        with pytest.raises(
            ChartDataError, match="move the extra field onto rows or columns"
        ):
            pivot_table_data(
                duplicate, rows=["region"], columns=["month"], values=["revenue"]
            )

    def test_duplicate_cell_multi_measure_raises_with_hint(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        duplicate = [
            {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
            {"region": "US", "month": "Jan", "revenue": 999, "cost": 70},
        ]
        with pytest.raises(
            ChartDataError, match="move the extra field onto rows or columns"
        ):
            pivot_table_data(
                duplicate,
                rows=["region"],
                columns=["month"],
                values=["revenue", "cost"],
            )

    def test_empty_data_returns_empty(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, groups, _ = pivot_table_data(
            [], rows=["region"], columns=["month"], values=["revenue"]
        )
        assert wide == []
        assert groups is None


# ---------------------------------------------------------------------------
# SVG integration tests
# ---------------------------------------------------------------------------


class TestPivotSingleMeasureSVG:
    """Single-measure pivot: SVG has 1-row header with col-value column names."""

    DATA = [
        {"region": "US", "month": "Jan", "amount": 100},
        {"region": "US", "month": "Feb", "amount": 200},
        {"region": "EU", "month": "Jan", "amount": 150},
        {"region": "EU", "month": "Feb", "amount": 250},
    ]

    def test_single_measure_pivot_renders(self) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = TableChart(
            id="pivot_test",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["month"],
            values=["amount"],
        )
        resolved = resolve(chart, [], chart_style_context=_BOARD_CTX)
        board = _board_style()
        svg = render_table_svg(resolved, self.DATA, width=600, board_style=board)
        assert isinstance(svg, str)
        assert "<svg" in svg
        # Col-value column headers "Jan" and "Feb" must appear as header labels
        # (slug_to_text may title-case them; just check case-insensitively)
        assert "jan" in svg.lower(), (
            "Single-measure pivot must show col-value 'Jan' as column header"
        )
        assert "feb" in svg.lower(), (
            "Single-measure pivot must show col-value 'Feb' as column header"
        )

    def test_conditional_formatting_keys_by_col_value(self) -> None:
        """Conditional formatting keyed by col-value (e.g. game-of-life c1..c32)."""
        from dbt_charts.core.compile.models.chart.authored import (
            ConditionalRule,
            FieldConditionalFormatting,
        )
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        data = [
            {"row_key": "r1", "col": "c1", "val": "#"},
            {"row_key": "r2", "col": "c1", "val": "."},
        ]
        cf = {
            "c1": FieldConditionalFormatting(
                when=[ConditionalRule(eq="#", background="#000000")]
            )
        }
        chart = TableChart(
            id="cf_test",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["row_key"],
            columns=["col"],
            values=["val"],
            conditional_formatting=cf,
        )
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        board = _board_style()
        svg = render_table_svg(resolved, data, width=400, board_style=board)
        # Must render without error; background fill #000000 must appear
        assert "#000000" in svg, (
            "Conditional formatting must apply to pivot col-value columns"
        )


class TestPivotMultiMeasureSVG:
    """Multi-measure pivot: SVG must have a 2-row header structure."""

    DATA = [
        {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
        {"region": "US", "month": "Feb", "revenue": 200, "cost": 110},
        {"region": "EU", "month": "Jan", "revenue": 150, "cost": 90},
        {"region": "EU", "month": "Feb", "revenue": 250, "cost": 140},
    ]

    def _get_svg(self) -> str:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = TableChart(
            id="multi_pivot_test",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["month"],
            values=["revenue", "cost"],
        )
        resolved = resolve(chart, [], chart_style_context=_BOARD_CTX)
        board = _board_style()
        return render_table_svg(resolved, self.DATA, width=800, board_style=board)

    def test_svg_renders_without_error(self) -> None:
        svg = self._get_svg()
        assert isinstance(svg, str)
        assert "<svg" in svg

    def test_group_labels_in_svg(self) -> None:
        svg = self._get_svg()
        # Group labels are the distinct month values
        assert "Jan" in svg, "Group label 'Jan' must appear in multi-measure pivot SVG"
        assert "Feb" in svg, "Group label 'Feb' must appear in multi-measure pivot SVG"

    def test_measure_sub_labels_in_svg(self) -> None:
        svg = self._get_svg()
        # Measure sub-labels appear in the bottom header row
        # slug_to_text("revenue") → "revenue" or "Revenue" depending on case
        assert "revenue" in svg.lower(), (
            "Measure sub-label 'revenue' must appear in SVG"
        )
        assert "cost" in svg.lower(), "Measure sub-label 'cost' must appear in SVG"

    def test_data_values_in_svg(self) -> None:
        svg = self._get_svg()
        # Cell values must appear in SVG
        assert "100" in svg
        assert "60" in svg

    def test_group_header_spans_appear_before_leaf_headers(self) -> None:
        """Group-span rect/text elements appear earlier in SVG than leaf header text."""
        svg = self._get_svg()
        # Both Jan and Feb appear in SVG; group labels are rendered before leaf labels
        jan_pos = svg.find("Jan")
        feb_pos = svg.find("Feb")
        # revenue/cost appear after at least one of the group labels
        rev_pos = svg.lower().find("revenue")
        assert jan_pos >= 0 and rev_pos >= 0
        # Group labels must appear before or concurrent with measure labels
        # (we just assert both are present; exact ordering is layout-dependent)
        assert min(jan_pos, feb_pos) < rev_pos, (
            "Group labels must appear in SVG before measure sub-labels"
        )


class TestPivotMultiMeasureHeaderNotDuplicated:
    """Regression: single-dim multi-measure must render measure names ONCE (not twice).

    Phase-2 bug: measure level was added to group-header descriptor AND the leaf
    row already shows measure names → measures appeared twice in SVG.
    """

    DATA = [
        {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
        {"region": "EU", "month": "Jan", "revenue": 150, "cost": 90},
    ]

    def test_measure_names_appear_exactly_once_in_header(self) -> None:
        """'revenue' must appear exactly once in the SVG header text."""
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = TableChart(
            id="no_dup_test",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["month"],
            values=["revenue", "cost"],
        )
        resolved = resolve(chart, [], chart_style_context=_BOARD_CTX)
        svg = render_table_svg(
            resolved, self.DATA, width=800, board_style=_board_style()
        )
        # Count how many times "revenue" appears as a header text element.
        # The leaf header (1 occurrence) is all that's allowed — group-header level
        # for month (Jan) must NOT emit "revenue" a second time.
        revenue_count = svg.lower().count("revenue")
        assert revenue_count == 1, (
            f"'revenue' must appear exactly once in SVG (leaf header only), "
            f"but appeared {revenue_count} times — measure level probably duplicated"
        )

    def test_exactly_one_group_header_row_emitted(self) -> None:
        """Single-dim multi-measure: exactly one group-header row (col-dim)."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        assert groups is not None
        assert len(groups) == 1, (
            f"Expected exactly 1 group-header level (col-dim), got {len(groups)}"
        )


class TestPivotEmptyData:
    """Empty data falls through to the normal empty-state (no pivot attempted)."""

    def test_empty_data_renders_no_data_state(self) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = TableChart(
            id="empty_pivot",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["month"],
            values=["amount"],
        )
        resolved = resolve(chart, [], chart_style_context=_BOARD_CTX)
        board = _board_style()
        svg = render_table_svg(resolved, [], width=400, board_style=board)
        # Must render without error; the normal empty state should appear
        assert "<svg" in svg


class TestPivotStyleColumnsIsStylingOnly:
    """`style.columns` on a pivot styles the columns it names and nothing else.

    The old semantics read an authored mapping whose keys were all real
    post-pivot columns as the complete show-list, silently collapsing the
    cross-tab. Hiding is the explicit `visible: false`; naming only a subset
    of the post-pivot columns, with no `visible:` anywhere, styles that
    subset and renders every column same as any other subset.
    """

    DATA = [
        {"region": "East", "quarter": "Q1", "amt": 10},
        {"region": "East", "quarter": "Q2", "amt": 20},
        {"region": "West", "quarter": "Q1", "amt": 30},
        {"region": "West", "quarter": "Q2", "amt": 40},
    ]

    def _render(self, style_columns: dict[str, Any] | None) -> str:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import render_table_svg

        kwargs: dict[str, Any] = {}
        if style_columns is not None:
            kwargs["style"] = {"columns": style_columns}
        chart = TableChart(
            id="pivcol",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["quarter"],
            values=["amt"],
            **kwargs,
        )
        resolved = resolve(chart, self.DATA, chart_style_context=_BOARD_CTX)
        return render_table_svg(
            resolved, self.DATA, width=600, board_style=_board_style()
        )

    def test_styling_the_row_group_field_still_renders_the_cross_tab(self) -> None:
        svg = self._render({"region": {"label": "Rgn"}})
        assert "Q1" in svg and "Q2" in svg
        assert ">40<" in svg, "the cross-tab body must still render"
        assert "rgn" in svg.lower()

    def test_naming_only_some_pivoted_columns_still_renders_all(self) -> None:
        svg = self._render({"region": {"label": "Rgn"}, "Q1": {"align": "right"}})
        assert "Q2" in svg
        assert ">40<" in svg, "the un-named pivoted column must still render"

    def test_leaf_keyed_subset_without_visible_still_renders_the_row_dimension(
        self,
    ) -> None:
        """Naming only the pivoted values used to hide the `rows:` dimension
        under the old show-list shape. style.columns is styling-only: the row
        dimension renders regardless of what is named."""
        svg = self._render({"Q1": {"align": "right"}, "Q2": {"align": "right"}})
        assert "Q1" in svg and "Q2" in svg
        assert ">40<" in svg, "the cross-tab body must still render"
        assert "East" in svg, "the row dimension renders unless hidden explicitly"

    def test_row_dimension_renders_unless_visible_false_hides_it(self) -> None:
        """`visible: false` is the explicit way to hide a sort-key dimension."""
        svg = self._render({"region": {"visible": False}, "Q1": {"align": "right"}})
        assert "Q1" in svg and "Q2" in svg
        assert ">40<" in svg
        assert "East" not in svg

    def test_visible_false_hides_a_named_post_pivot_column(self) -> None:
        svg = self._render({"Q1": {"visible": False}})
        assert "Q2" in svg
        assert ">40<" in svg, "Q2's cross-tab body must still render"
        assert "Q1" not in svg

    def test_styling_every_post_pivot_column_renders(self) -> None:
        svg = self._render(
            {
                "region": {"label": "Rgn"},
                "Q1": {"align": "right"},
                "Q2": {"align": "right"},
            }
        )
        assert "Q1" in svg and "Q2" in svg
        assert ">40<" in svg, "the cross-tab body must still render"
        assert "East" in svg, "the styled row dimension must still render"
        assert "rgn" in svg.lower()

    def test_case_a_no_style_columns_unaffected(self) -> None:
        svg = self._render(None)
        assert "Q1" in svg and "Q2" in svg
        assert "East" in svg and ">40<" in svg

    def test_pre_pivot_measure_name_styling_still_renders_every_column(self) -> None:
        """`amt` names a measure, consumed by the pivot reshape rather than a
        post-transform column — styling it never hides anything else."""
        svg = self._render({"amt": {"align": "right"}})
        assert "Q1" in svg and "Q2" in svg
        assert "East" in svg and ">40<" in svg

    def test_flat_table_style_columns_never_hides_an_unnamed_column(self) -> None:
        """Not a pivot — style.columns is styling-only here too."""
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import render_table_svg

        data = [{"region": "East", "amt": 10, "helper": "x"}]
        chart = TableChart(
            id="flat",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            style={"columns": {"region": {"label": "Rgn", "visible": True}}},
        )
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        svg = render_table_svg(resolved, data, width=600, board_style=_board_style())
        assert "rgn" in svg.lower()
        assert ">x<" in svg, "helper wasn't marked visible: false — it must render"

    def test_flat_table_visible_false_hides_the_helper_column(self) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import render_table_svg

        data = [{"region": "East", "amt": 10, "helper": "x"}]
        chart = TableChart(
            id="flathidden",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            style={"columns": {"helper": {"visible": False}}},
        )
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        svg = render_table_svg(resolved, data, width=600, board_style=_board_style())
        assert "East" in svg
        assert ">x<" not in svg

    def test_empty_data_with_style_columns_renders_the_authored_header(self) -> None:
        """Zero rows: there is no post-pivot key space to read a column list
        from, so the empty-state render falls back to the resolved mapping's
        keys and still shows the declared header."""
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import render_table_svg

        chart = TableChart(
            id="pivempty",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["quarter"],
            values=["amt"],
            style={"columns": {"region": {"label": "Rgn"}}},
        )
        resolved = resolve(chart, self.DATA, chart_style_context=_BOARD_CTX)
        svg = render_table_svg(resolved, [], width=600, board_style=_board_style())
        assert "rgn" in svg.lower()

    def test_empty_data_flat_table_with_style_columns_renders(self) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import render_table_svg

        chart = TableChart(
            id="flatempty",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            style={"columns": {"region": {"label": "Rgn", "visible": True}}},
        )
        resolved = resolve(
            chart, [{"region": "East", "amt": 10}], chart_style_context=_BOARD_CTX
        )
        svg = render_table_svg(resolved, [], width=600, board_style=_board_style())
        assert "rgn" in svg.lower()

    def test_a_pivoted_value_colliding_with_the_measure_name_renders(self) -> None:
        """The measure field is consumed by the reshape, so a pivoted value
        that collides with its name is an ordinary new column — it renders
        (the #7712 guard that raised here is deleted)."""
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.render.chart.table import render_table_svg

        data = [
            {"region": "East", "quarter": "amt", "amt": 10},
            {"region": "East", "quarter": "Q2", "amt": 20},
        ]
        chart = TableChart(
            id="collide",
            type="table",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            rows=["region"],
            columns=["quarter"],
            values=["amt"],
            style={"columns": {"region": {"label": "Rgn"}}},
        )
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        svg = render_table_svg(resolved, data, width=600, board_style=_board_style())
        assert "East" in svg
        assert ">10<" in svg and ">20<" in svg
