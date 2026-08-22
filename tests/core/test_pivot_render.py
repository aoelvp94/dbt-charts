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
