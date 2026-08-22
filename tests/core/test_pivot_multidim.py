"""Phase 2 multi-dimension pivot tests.

TDD: these tests were written BEFORE the implementation. Each test
covers a distinct contract:

- compile accepts 2+ column dims (authored + normalized models)
- pivot_table_data with 2 column dims: correct leaf count, cell placement,
  nested group descriptor structure
- N-row header in SVG (spans structure)
- single-dim regression (game-of-life style): still works identically
- duplicate-cell error carries hint
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

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _board_style() -> Any:
    from dbt_charts.core.compile.config import get_theme_style

    return resolve_style(get_theme_style())


def _make_resolved_chart(
    rows: list[str] | None,
    columns: list[str],
    values: list[str] | None,
) -> Any:
    from dbt_charts.core.compile.models.chart.normalized import TableChart
    from dbt_charts.core.compile.models.query.normalized import SqlQuery

    chart = TableChart(
        id="multidim_test",
        type="table",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        rows=rows,
        columns=columns,
        values=values,
    )
    return resolve(chart, [], chart_style_context=_BOARD_CTX)


# ---------------------------------------------------------------------------
# 1. Compile: 2+ columns fields accepted
# ---------------------------------------------------------------------------


class TestCompileAcceptsMultipleColumnFields:
    """Both authored and normalized models must accept len(columns) >= 2."""

    def test_authored_table_chart_accepts_two_column_fields(self) -> None:
        from dbt_charts.core.compile.models.chart.authored import TableChart

        chart = TableChart(type="table", columns=["region", "quarter"])
        assert chart.columns == ["region", "quarter"]

    def test_authored_table_chart_accepts_three_column_fields(self) -> None:
        from dbt_charts.core.compile.models.chart.authored import TableChart

        chart = TableChart(type="table", columns=["year", "quarter", "month"])
        assert chart.columns == ["year", "quarter", "month"]

    def test_normalized_chart_accepts_two_column_fields(self) -> None:
        chart = TableChart(id="c", type="table", columns=["region", "quarter"])
        assert chart.columns == ["region", "quarter"]

    def test_normalized_chart_accepts_three_column_fields(self) -> None:
        chart = TableChart(id="c", type="table", columns=["year", "q", "month"])
        assert chart.columns == ["year", "q", "month"]

    def test_field_on_two_channels_still_rejected(self) -> None:
        """The no-field-on-two-channels invariant must survive the limit lift."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.chart.authored import TableChart

        with pytest.raises(ValidationError, match="region"):
            TableChart(
                type="table",
                rows=["region"],
                columns=["region", "quarter"],
            )

    def test_field_on_two_channels_rejected_through_compile(self) -> None:
        # The invariant is enforced at the authored/compile boundary (the
        # normalized model is trusted and does not re-validate). Route through
        # normalize_chart to confirm the full compile path rejects it.
        from dbt_charts.core.compile.errors import CompilationError
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.normalize.charts import normalize_chart

        registry = {"q": SqlQuery(sql="SELECT 1", source="test")}
        with pytest.raises(CompilationError, match="region"):
            normalize_chart(
                "c",
                {
                    "type": "table",
                    "query": "q",
                    "rows": ["region"],
                    "columns": ["region", "q"],
                },
                registry,
                sources={},
            )

    def test_channels_survive_normalize_board_with_two_column_dims(self) -> None:
        """Two column dims round-trip through the full compiler."""
        from dbt_charts.core.compile.compiler import compile as compile_board

        yaml = """
title: Multi-dim Pivot
queries:
  sales:
    sql: "SELECT region, year, quarter, revenue FROM sales"
    source: test
charts:
  pivot_table:
    type: table
    query: sales
    rows:
      - region
    columns:
      - year
      - quarter
    values:
      - revenue
rows:
  - pivot_table
"""
        result = compile_board(yaml)
        assert result.errors == [], f"Compile errors: {result.errors}"
        chart = result.board.charts["pivot_table"]
        assert chart.columns == ["year", "quarter"]


# ---------------------------------------------------------------------------
# 2. pivot_table_data with 2 column dimensions
# ---------------------------------------------------------------------------

# Long-form data: region × year × quarter × revenue
_MULTIDIM_DATA = [
    {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100},
    {"region": "US", "year": "2024", "quarter": "Q2", "revenue": 200},
    {"region": "US", "year": "2025", "quarter": "Q1", "revenue": 150},
    {"region": "US", "year": "2025", "quarter": "Q2", "revenue": 250},
    {"region": "EU", "year": "2024", "quarter": "Q1", "revenue": 90},
    {"region": "EU", "year": "2024", "quarter": "Q2", "revenue": 180},
    {"region": "EU", "year": "2025", "quarter": "Q1", "revenue": 120},
    {"region": "EU", "year": "2025", "quarter": "Q2", "revenue": 220},
]


class TestPivotTableDataTwoColDims:
    """pivot_table_data with columns=[year, quarter] single-measure."""

    def test_leaf_count_equals_product_of_distinct_values(self) -> None:
        """2 years × 2 quarters × 1 measure = 4 leaves + 1 row dim = 5 keys."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        # 1 row-dim key (region) + 4 leaf columns
        assert len(wide[0]) == 5

    def test_row_count_equals_distinct_row_dim_values(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        assert len(wide) == 2  # US, EU

    def test_cell_values_land_at_correct_position(self) -> None:
        """US/2024/Q1/revenue = 100 must be in the US row."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        us = next(r for r in wide if r["region"] == "US")
        eu = next(r for r in wide if r["region"] == "EU")
        # Find leaves whose values match the known data points
        assert 100 in us.values(), "US/2024/Q1/revenue=100 must appear in US row"
        assert 200 in us.values(), "US/2024/Q2/revenue=200 must appear in US row"
        assert 90 in eu.values(), "EU/2024/Q1/revenue=90 must appear in EU row"

    def test_leaf_order_outer_col_varies_slowest(self) -> None:
        """Leaves ordered: (2024,Q1), (2024,Q2), (2025,Q1), (2025,Q2)."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, groups, _ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        us = next(r for r in wide if r["region"] == "US")
        leaf_keys = [k for k in us if k != "region"]
        assert len(leaf_keys) == 4
        # The four leaves must encode the 2×2 outer×inner combination
        # (we test by checking the US values are in the correct positions)
        values_in_order = [us[k] for k in leaf_keys]
        assert values_in_order == [100, 200, 150, 250], (
            f"Expected [100, 200, 150, 250] (2024/Q1, 2024/Q2, 2025/Q1, 2025/Q2) "
            f"but got {values_in_order}"
        )

    def test_group_descriptor_has_one_level(self) -> None:
        """Two column dims, single measure → ONE group-header level (outer dim only).
        The innermost dim is the leaf row — emitting it as a group level would double it.
        """
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        assert groups is not None
        # Only the outer col-dim level; inner dim is the leaf label.
        assert len(groups) == 1, f"Expected 1 group-header level, got {len(groups)}"

    def test_outer_level_has_two_year_spans(self) -> None:
        """Outer dim (year) level: 2 spans each covering 2 leaves (quarters)."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        assert groups is not None
        outer = groups[0]  # year level (the only level)
        assert len(outer) == 2, f"Expected 2 year spans, got {len(outer)}"
        for label, _first_idx, n_leaves in outer:
            assert n_leaves == 2, (
                f"Year span {label!r} should cover 2 leaves (quarters)"
            )

    def test_inner_spans_are_contiguous_and_start_at_correct_index(self) -> None:
        """Leaf order must be contiguous: outer level spans idx 0..1 and 2..3."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            _MULTIDIM_DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        assert groups is not None
        outer = groups[0]
        first_idxs = [span[1] for span in outer]
        assert first_idxs == [0, 2], f"Outer span start indices: {first_idxs}"


class TestPivotTableDataTwoColDimsMultiMeasure:
    """pivot_table_data with columns=[year, quarter], values=[revenue, cost]."""

    DATA = [
        {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100, "cost": 40},
        {"region": "US", "year": "2024", "quarter": "Q2", "revenue": 200, "cost": 80},
        {"region": "EU", "year": "2024", "quarter": "Q1", "revenue": 90, "cost": 30},
        {"region": "EU", "year": "2024", "quarter": "Q2", "revenue": 180, "cost": 70},
    ]

    def test_leaf_count_equals_cols_times_measures(self) -> None:
        """2 years×quarters = 2 col-tuples, × 2 measures = 4 leaves + 1 row dim."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            self.DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue", "cost"],
        )
        # 1 row dim + 2 col-tuples × 2 measures = 1 + 4
        assert len(wide[0]) == 5

    def test_group_descriptor_has_two_levels(self) -> None:
        """2 col dims + multi-measure → 2 group-header levels (both col dims).
        No measure level: the leaf row shows measures (leaf label = measure name).
        """
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue", "cost"],
        )
        assert groups is not None
        # Only col-dim levels; no measure level.
        assert len(groups) == 2, f"Expected 2 group-header levels, got {len(groups)}"

    def test_outermost_level_spans_all_leaves_under_it(self) -> None:
        """year level: each year span covers n_quarters × n_measures leaves."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue", "cost"],
        )
        assert groups is not None
        outer = groups[0]  # year level
        assert len(outer) == 1  # only 2024 in this fixture
        label, first_idx, n_leaves = outer[0]
        assert label == "2024"
        assert first_idx == 0
        assert n_leaves == 4  # 2 quarters × 2 measures

    def test_innermost_col_dim_level_spans_per_measure(self) -> None:
        """Quarter level (inner col-dim): each span covers n_measures leaves."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue", "cost"],
        )
        assert groups is not None
        inner = groups[1]  # quarter level (innermost col-dim)
        assert len(inner) == 2  # Q1, Q2 (2 col-tuples in this fixture)
        for label, _first_idx, n_leaves in inner:
            assert n_leaves == 2, f"Quarter {label!r} should span 2 measure leaves"


class TestSparseMultiDimData:
    """Sparse data must not produce phantom columns (HIGH 2 regression)."""

    def test_no_phantom_columns_for_asymmetric_data(self) -> None:
        """Only observed (outer, inner) combinations appear as leaves."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        # Only (2024, Q1) and (2025, Q2) are present — (2024,Q2) and (2025,Q1) absent.
        sparse = [
            {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100},
            {"region": "US", "year": "2025", "quarter": "Q2", "revenue": 250},
            {"region": "EU", "year": "2024", "quarter": "Q1", "revenue": 90},
            {"region": "EU", "year": "2025", "quarter": "Q2", "revenue": 220},
        ]
        wide, *_ = pivot_table_data(
            sparse,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        # Should have 2 col-tuples (2024/Q1 and 2025/Q2), NOT 4 from Cartesian product.
        leaf_keys = [k for k in wide[0] if k != "region"]
        assert len(leaf_keys) == 2, (
            f"Sparse data should produce 2 leaves (observed combos only), "
            f"got {len(leaf_keys)}: {leaf_keys}"
        )

    def test_sparse_multi_measure_no_phantom_columns(self) -> None:
        """Sparse multi-dim multi-measure: no phantom columns."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        sparse = [
            {
                "region": "US",
                "year": "2024",
                "quarter": "Q1",
                "revenue": 100,
                "cost": 40,
            },
            {
                "region": "US",
                "year": "2025",
                "quarter": "Q2",
                "revenue": 250,
                "cost": 90,
            },
        ]
        wide, *_ = pivot_table_data(
            sparse,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue", "cost"],
        )
        # 2 observed col-tuples × 2 measures = 4 leaves + 1 row dim = 5 total.
        leaf_keys = [k for k in wide[0] if k != "region"]
        assert len(leaf_keys) == 4, (
            f"Expected 4 leaves (2 col-tuples × 2 measures), got {len(leaf_keys)}"
        )

    def test_sparse_outer_level_has_correct_span_count(self) -> None:
        """Outer level spans should match observed outer-dim values, not Cartesian."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        sparse = [
            {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100},
            {"region": "US", "year": "2025", "quarter": "Q2", "revenue": 250},
        ]
        _, groups, __ = pivot_table_data(
            sparse,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        assert groups is not None
        outer = groups[0]  # year level
        outer_labels = [s[0] for s in outer]
        assert "2024" in outer_labels
        assert "2025" in outer_labels
        # No phantom year values
        assert len(outer_labels) == 2


class TestPivotTableDataReturnsEffectiveValues:
    """pivot_table_data return includes effective values (HIGH 3 fix)."""

    def test_effective_values_returned_for_explicit_single_measure(self) -> None:
        """Single-measure multi-dim: effective_values == the one measure."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [{"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100}]
        _, __, effective = pivot_table_data(
            data,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        assert effective == ["revenue"]

    def test_effective_values_returned_for_multi_measure(self) -> None:
        """Multi-measure: effective_values == the measures list."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
        ]
        _, __, effective = pivot_table_data(
            data,
            rows=["region"],
            columns=["month"],
            values=["revenue", "cost"],
        )
        assert effective == ["revenue", "cost"]

    def test_effective_values_returned_single_dim_single_measure(self) -> None:
        """Single-dim single-measure path also returns effective_values."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "amount": 100},
        ]
        _, __, effective = pivot_table_data(
            data,
            rows=["region"],
            columns=["month"],
            values=["amount"],
        )
        assert effective == ["amount"]

    def test_effective_values_inferred_when_values_none(self) -> None:
        """values=None: effective_values are the inferred columns."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "z_last": 1, "a_first": 2},
        ]
        _, __, effective = pivot_table_data(
            data,
            rows=["region"],
            columns=["month"],
            values=None,
        )
        assert effective == ["z_last", "a_first"]


class TestPivotTableDataTwoColDimsErrors:
    """Duplicate-cell detection works for multi-dim column key."""

    def test_duplicate_cell_raises_with_hint(self) -> None:
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        duplicate = [
            {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100},
            {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 999},
        ]
        with pytest.raises(ChartDataError, match="move the extra field"):
            pivot_table_data(
                duplicate,
                rows=["region"],
                columns=["year", "quarter"],
                values=["revenue"],
            )


# ---------------------------------------------------------------------------
# 2b. rows omitted → row dims inferred from the remaining query columns
#     (CRITICAL regression: a table chart with columns/values but no rows
#     used to render — every detail row keyed to () and collided).
# ---------------------------------------------------------------------------


class TestPivotTableDataRowsOmitted:
    DATA = [
        {"region": "US", "month": "Jan", "amount": 100},
        {"region": "US", "month": "Feb", "amount": 200},
        {"region": "EU", "month": "Jan", "amount": 150},
        {"region": "EU", "month": "Feb", "amount": 250},
    ]

    def test_rows_inferred_from_remaining_columns(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, groups, effective = pivot_table_data(
            self.DATA, rows=[], columns=["month"], values=["amount"]
        )
        assert groups is None
        assert effective == ["amount"]
        assert len(wide) == 2, "rows should be inferred as region, not collapsed to one"
        us = next(r for r in wide if r["region"] == "US")
        eu = next(r for r in wide if r["region"] == "EU")
        assert us["Jan"] == 100 and us["Feb"] == 200
        assert eu["Jan"] == 150 and eu["Feb"] == 250

    def test_svg_renders_without_rows_declared(self) -> None:
        """End-to-end: a table chart with columns/values but no rows must
        render (rows are inferred), not raise ChartDataError."""
        from dbt_charts.core.render.chart.table import render_table_svg

        resolved = _make_resolved_chart(
            rows=None,
            columns=["month"],
            values=["amount"],
        )
        svg = render_table_svg(
            resolved,
            self.DATA,
            width=600,
            board_style=_board_style(),
        )
        assert "<svg" in svg
        assert "US" in svg and "EU" in svg


# ---------------------------------------------------------------------------
# 2c. Up-front field validation — a typo'd values/columns field must raise a
#     ChartDataError, not silently produce blank cells or a raw KeyError.
# ---------------------------------------------------------------------------


class TestPivotTableDataValidatesFields:
    DATA = [
        {"region": "US", "quarter": "Q1", "revenue": 100},
        {"region": "EU", "quarter": "Q1", "revenue": 90},
    ]

    def test_misspelled_value_raises_not_blank_cells(self) -> None:
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        with pytest.raises(ChartDataError, match="revenu"):
            pivot_table_data(
                self.DATA, rows=["region"], columns=["quarter"], values=["revenu"]
            )

    def test_missing_column_raises_chart_data_error_not_keyerror(self) -> None:
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        with pytest.raises(ChartDataError, match="qtr"):
            pivot_table_data(
                self.DATA, rows=["region"], columns=["qtr"], values=["revenue"]
            )

    def test_misspelled_declared_row_raises(self) -> None:
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        with pytest.raises(ChartDataError, match="regoin"):
            pivot_table_data(
                self.DATA, rows=["regoin"], columns=["quarter"], values=["revenue"]
            )

    def test_literal_role_spec_raises_under_pivot(self) -> None:
        """A literal role value (``row.role: total``) used where a column name
        belongs must raise — under a pivot it would resolve every row to that
        role and silently drop the reshape."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        with pytest.raises(ChartDataError, match="literal role"):
            pivot_table_data(
                self.DATA,
                rows=["region"],
                columns=["quarter"],
                values=["revenue"],
                row_role_spec="total",  # literal, not a query column
            )

    def test_absent_role_column_renders_roleless_under_pivot(self) -> None:
        """``row.role`` is a cascading theme/board setting, so an absent column
        name must behave under a pivot exactly as it does for a flat table —
        every row resolves to "value", no crash. A pivot whose query lacks the
        board-wide role column must render, not hard-fail."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, _, values = pivot_table_data(
            self.DATA,
            rows=["region"],
            columns=["quarter"],
            values=["revenue"],
            row_role_spec="_df_row_role",  # not present in DATA — roleless
        )
        assert values == ["revenue"]
        # No total row was synthesized: one wide row per region, no merge.
        assert len(wide) == 2
        assert {r["region"] for r in wide} == {"US", "EU"}

    def test_both_rows_and_values_omitted_raises(self) -> None:
        """With only `columns` given, rows vs measures can't be inferred — the
        row dimension would be silently turned into a measure. Raise instead."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        with pytest.raises(ChartDataError, match="at least one of"):
            pivot_table_data(self.DATA, rows=[], columns=["quarter"], values=None)

    def test_empty_values_list_raises_not_indexerror(self) -> None:
        """An explicit `values: []` must raise ChartDataError, not reach the
        `effective_values[0]` access as a raw IndexError."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        with pytest.raises(ChartDataError, match="no measure"):
            pivot_table_data(self.DATA, rows=["region"], columns=["quarter"], values=[])

    def test_conflicting_roles_in_one_bucket_raises(self) -> None:
        """Two tidy rows that merge into the same wide-row bucket but resolve to
        different roles are ambiguous — raise rather than keep first-seen."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 1, "role": "value"},
            {"region": "US", "quarter": "Q2", "revenue": 3, "role": "summary"},
        ]
        with pytest.raises(ChartDataError, match="conflicting row roles"):
            pivot_table_data(
                data,
                rows=["region"],
                columns=["quarter"],
                values=["revenue"],
                row_role_spec="role",
            )

    def test_undeclared_columns_dropped_when_rows_explicit(self) -> None:
        """With `rows` declared, a query column that is neither a row dim, a
        pivot column, nor a measure is dropped — rows/columns/values is a
        complete declaration. Pins the semantics against a silent refactor."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "note": "x", "quarter": "Q1", "amount": 1},
            {"region": "US", "note": "y", "quarter": "Q2", "amount": 2},
        ]
        wide, _, effective = pivot_table_data(
            data, rows=["region"], columns=["quarter"], values=["amount"]
        )
        assert effective == ["amount"]
        assert len(wide) == 1, "both US rows merge; `note` is not a row dimension"
        assert "note" not in wide[0]
        assert wide[0]["Q1"] == 1 and wide[0]["Q2"] == 2


# ---------------------------------------------------------------------------
# 3. N-row header in SVG
# ---------------------------------------------------------------------------


class TestMultiDimPivotSVGHeader:
    """SVG rendered from 2-col-dim pivot has N-row header structure."""

    def _get_svg(self) -> str:
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        resolved = _make_resolved_chart(
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
        )
        return render_table_svg(
            resolved,
            _MULTIDIM_DATA,
            width=900,
            board_style=_board_style(),
        )

    def test_svg_renders_without_error(self) -> None:
        svg = self._get_svg()
        assert isinstance(svg, str)
        assert "<svg" in svg

    def test_outer_group_labels_present(self) -> None:
        """Year labels (outer dim) must appear in SVG."""
        svg = self._get_svg()
        assert "2024" in svg, "Outer dim label '2024' must appear in SVG"
        assert "2025" in svg, "Outer dim label '2025' must appear in SVG"

    def test_inner_group_labels_present(self) -> None:
        """Quarter labels (inner dim) must appear in SVG."""
        svg = self._get_svg()
        assert "Q1" in svg, "Inner dim label 'Q1' must appear in SVG"
        assert "Q2" in svg, "Inner dim label 'Q2' must appear in SVG"

    def test_data_values_present(self) -> None:
        svg = self._get_svg()
        assert "100" in svg
        assert "90" in svg

    def test_outer_labels_appear_before_inner_labels(self) -> None:
        """Year labels must come before quarter labels in SVG output."""
        svg = self._get_svg()
        year_pos = svg.find("2024")
        q1_pos = svg.find("Q1")
        assert year_pos >= 0 and q1_pos >= 0
        assert year_pos < q1_pos, "Year group label must appear before quarter label"


class TestMultiDimMultiMeasureSVGHeader:
    """SVG from 2-col-dim + 2-measure pivot has 3-row header structure."""

    DATA = [
        {"region": "US", "year": "2024", "quarter": "Q1", "revenue": 100, "cost": 40},
        {"region": "EU", "year": "2024", "quarter": "Q1", "revenue": 90, "cost": 30},
    ]

    def _get_svg(self) -> str:
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        resolved = _make_resolved_chart(
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue", "cost"],
        )
        return render_table_svg(
            resolved,
            self.DATA,
            width=900,
            board_style=_board_style(),
        )

    def test_svg_renders_without_error(self) -> None:
        svg = self._get_svg()
        assert "<svg" in svg

    def test_year_quarter_and_measure_labels_all_present(self) -> None:
        svg = self._get_svg()
        assert "2024" in svg
        assert "Q1" in svg
        assert "revenue" in svg.lower()
        assert "cost" in svg.lower()


# ---------------------------------------------------------------------------
# 4. Single-dim regression: game-of-life style
# ---------------------------------------------------------------------------


class TestSingleDimRegressionUnchanged:
    """A single column dim keeps the plain single-dim reshape shape."""

    DATA = [
        {"region": "US", "month": "Jan", "amount": 100},
        {"region": "US", "month": "Feb", "amount": 200},
        {"region": "EU", "month": "Jan", "amount": 150},
        {"region": "EU", "month": "Feb", "amount": 250},
    ]

    def test_single_measure_groups_is_none(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        _, groups, __ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["amount"]
        )
        assert groups is None

    def test_single_dim_leaf_columns_are_col_values(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        wide, *_ = pivot_table_data(
            self.DATA, rows=["region"], columns=["month"], values=["amount"]
        )
        assert "Jan" in wide[0]
        assert "Feb" in wide[0]

    def test_single_dim_multi_measure_groups_has_one_col_dim_level(self) -> None:
        """Multi-measure single-dim: groups has exactly 1 level (the col-dim).
        No measure level — the leaf row already shows measure names.
        """
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "month": "Jan", "revenue": 100, "cost": 60},
            {"region": "EU", "month": "Jan", "revenue": 150, "cost": 90},
        ]
        _, groups, __ = pivot_table_data(
            data, rows=["region"], columns=["month"], values=["revenue", "cost"]
        )
        assert groups is not None
        # Single col dim + multi-measure → 1 group-header level (col-dim only).
        # Leaf row shows "revenue"/"cost" — no need for a second measure level.
        assert len(groups) == 1

    def test_single_dim_svg_renders(self) -> None:
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        resolved = _make_resolved_chart(
            rows=["region"],
            columns=["month"],
            values=["amount"],
        )
        svg = render_table_svg(
            resolved,
            self.DATA,
            width=600,
            board_style=_board_style(),
        )
        assert "<svg" in svg
        assert "jan" in svg.lower() or "Jan" in svg


# ---------------------------------------------------------------------------
# 5. Totals: total rows (column totals) + trailing total column (row totals).
#
# Tidy contract:
#   (a) A total row is tagged via the SAME row-role spec column flat tables
#       already use (style.table.row.role, resolved with resolve_row_role /
#       is_total_role). Total-role rows bucket by their rows-dim tuple like
#       every other row — nothing special about the keying — and keep first-seen
#       (query) order. So a single grand total (one consistent rows-dim label,
#       e.g. literal "Total") merges into ONE row, while distinct total labels
#       (per-group subtotals) stay distinct rows. Placement is the query's job:
#       render never reorders (chart AGENTS.md #3), so an `ORDER BY` decides
#       where totals land. The rows-dim cell values pass through verbatim from
#       the query — render never merges, re-labels, or invents them.
#   (b) A row total (trailing "Total" column) is a literal, case-sensitive
#       "Total" value in a columns-dimension field — it reshapes into a
#       trailing leaf column via the SAME col-tuple enumeration used for every
#       other column value. No extra render code; duplicate-cell detection
#       already guards it like any other column value.
# ---------------------------------------------------------------------------


class TestPivotColumnTotalsBottomRow:
    """`_df_row_role='total'` tidy rows bucket by their rows-dim tuple like every
    other row and keep first-seen (query) order: one consistent total label → one
    merged row, distinct labels → distinct rows. Placement is the query's job
    (chart AGENTS.md #3: no chart-layer reordering) — an `ORDER BY` puts totals
    where they belong.
    """

    def test_single_dim_total_row_merges_and_keeps_query_order(self) -> None:
        """A single grand total (one consistent rows-dim label) merges into ONE
        row even when its tidy rows are scattered mid-dataset: the total rows
        share their rows-dim tuple, so they bucket together — at the position of
        their first appearance. The renderer never reorders; the query decides
        placement.
        """
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100, "_df_row_role": "value"},
            {"region": "US", "quarter": "Q2", "revenue": 200, "_df_row_role": "value"},
            {
                "region": "Total",
                "quarter": "Q1",
                "revenue": 190,
                "_df_row_role": "total",
            },
            {"region": "EU", "quarter": "Q1", "revenue": 90, "_df_row_role": "value"},
            {"region": "EU", "quarter": "Q2", "revenue": 180, "_df_row_role": "value"},
            {
                "region": "Total",
                "quarter": "Q2",
                "revenue": 380,
                "_df_row_role": "total",
            },
        ]
        wide, levels, effective_values = pivot_table_data(
            data,
            rows=["region"],
            columns=["quarter"],
            values=["revenue"],
            row_role_spec="_df_row_role",
        )
        assert len(wide) == 3, "US, EU, and ONE merged Total row despite scatter"
        # First-seen order: US, then Total (first appears mid-dataset), then EU.
        # The renderer does not sort totals to the bottom — that is the query's
        # job via ORDER BY.
        assert [r["region"] for r in wide] == ["US", "Total", "EU"]
        total_row = next(r for r in wide if r["region"] == "Total")
        assert total_row["_df_row_role"] == "total"
        assert total_row["Q1"] == 190
        assert total_row["Q2"] == 380
        assert wide[0]["_df_row_role"] == "value", (
            "every wide row carries its role marker (the caller strips it from"
            " the rendered header) so non-total roles keep their styling"
        )
        assert levels is None, "single-dim single-measure fast-path shape preserved"
        assert effective_values == ["revenue"]

    def test_distinct_total_labels_render_as_separate_rows(self) -> None:
        """Total-role rows key by their rows-dim tuple like every other row, so
        two DIFFERENT total labels (per-group subtotals over disjoint columns)
        render as separate rows carrying their own data — each where the query
        interleaved it — never fabricated into a single row under a first-seen
        label. Root AGENTS.md §4: a wrong result that looks right is worse than a
        crash.
        """
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100, "_df_row_role": "value"},
            {
                "region": "US Total",
                "quarter": "Q1",
                "revenue": 100,
                "_df_row_role": "total",
            },
            {"region": "EU", "quarter": "Q2", "revenue": 90, "_df_row_role": "value"},
            {
                "region": "EU Total",
                "quarter": "Q2",
                "revenue": 90,
                "_df_row_role": "total",
            },
        ]
        wide, _, _ = pivot_table_data(
            data,
            rows=["region"],
            columns=["quarter"],
            values=["revenue"],
            row_role_spec="_df_row_role",
        )
        by_region = {r["region"]: r for r in wide}
        assert set(by_region) == {"US", "EU", "US Total", "EU Total"}
        # EU's subtotal stays under EU Total — not fabricated onto US Total.
        assert by_region["US Total"]["Q1"] == 100
        assert by_region["US Total"]["Q2"] is None
        assert by_region["EU Total"]["Q2"] == 90
        assert by_region["EU Total"]["Q1"] is None
        # Each subtotal renders where the query interleaved it (first-seen order):
        # the US subtotal directly under US, the EU subtotal under EU. The
        # renderer never herds totals to the bottom (chart AGENTS.md #3) — that
        # would make a per-group subtotal meaningless.
        regions = [r["region"] for r in wide]
        assert regions == ["US", "US Total", "EU", "EU Total"]

    def test_multidim_total_row_appended_at_bottom(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        detail = [{**row, "_df_row_role": "value"} for row in _MULTIDIM_DATA]
        totals = [
            {
                "region": "Total",
                "year": "2024",
                "quarter": "Q1",
                "revenue": 190,
                "_df_row_role": "total",
            },
            {
                "region": "Total",
                "year": "2024",
                "quarter": "Q2",
                "revenue": 380,
                "_df_row_role": "total",
            },
            {
                "region": "Total",
                "year": "2025",
                "quarter": "Q1",
                "revenue": 270,
                "_df_row_role": "total",
            },
            {
                "region": "Total",
                "year": "2025",
                "quarter": "Q2",
                "revenue": 470,
                "_df_row_role": "total",
            },
        ]
        wide, levels, _ = pivot_table_data(
            detail + totals,
            rows=["region"],
            columns=["year", "quarter"],
            values=["revenue"],
            row_role_spec="_df_row_role",
        )
        assert len(wide) == 3, "US, EU, and one merged Total row"
        assert wide[-1]["region"] == "Total"
        assert wide[-1]["_df_row_role"] == "total"
        leaf_keys = [k for k in wide[-1] if k not in ("region", "_df_row_role")]
        assert len(leaf_keys) == 4
        assert sorted(wide[-1][k] for k in leaf_keys) == [190, 270, 380, 470]
        assert levels is not None and len(levels) == 1, (
            "group-header descriptor shape is unaffected by the total row"
        )

    def test_duplicate_total_cell_raises(self) -> None:
        """Two total rows with the SAME rows-dim label collide on the same leaf
        — a genuine duplicate cell — and raise like any other duplicate."""
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100, "_df_row_role": "value"},
            {
                "region": "Total",
                "quarter": "Q1",
                "revenue": 100,
                "_df_row_role": "total",
            },
            {
                "region": "Total",
                "quarter": "Q1",
                "revenue": 999,
                "_df_row_role": "total",
            },
        ]
        with pytest.raises(ChartDataError, match="move the extra field"):
            pivot_table_data(
                data,
                rows=["region"],
                columns=["quarter"],
                values=["revenue"],
                row_role_spec="_df_row_role",
            )

    def test_role_column_excluded_from_inferred_effective_values(self) -> None:
        """When values=None, the role marker column must not be swept in as a measure."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100, "_df_row_role": "value"},
            {"region": "EU", "quarter": "Q1", "revenue": 90, "_df_row_role": "value"},
        ]
        _, __, effective_values = pivot_table_data(
            data,
            rows=["region"],
            columns=["quarter"],
            values=None,
            row_role_spec="_df_row_role",
        )
        assert effective_values == ["revenue"]

    def test_no_role_spec_leaves_shape_unchanged(self) -> None:
        """Omitting row_role_spec (default None) pins the plain reshape shape."""
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100},
            {"region": "EU", "quarter": "Q1", "revenue": 90},
        ]
        wide, levels, _ = pivot_table_data(
            data, rows=["region"], columns=["quarter"], values=["revenue"]
        )
        assert len(wide) == 2
        assert levels is None

    def test_summary_role_row_keeps_its_marker_not_downgraded(self) -> None:
        """A `summary`-tagged tidy row must carry its role through the reshape.

        A `summary` row buckets by its rows-dim key (not the total sentinel);
        if the marker were dropped it would resolve to "value" downstream —
        silently losing its styling and re-entering the conditional-formatting
        scale (root AGENTS.md §4: a wrong result that looks right is worse than
        a crash).
        """
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100, "_df_row_role": "value"},
            {"region": "US", "quarter": "Q2", "revenue": 200, "_df_row_role": "value"},
            {
                "region": "US subtotal",
                "quarter": "Q1",
                "revenue": 100,
                "_df_row_role": "summary",
            },
            {
                "region": "US subtotal",
                "quarter": "Q2",
                "revenue": 200,
                "_df_row_role": "summary",
            },
        ]
        wide, _, _ = pivot_table_data(
            data,
            rows=["region"],
            columns=["quarter"],
            values=["revenue"],
            row_role_spec="_df_row_role",
        )
        by_region = {r["region"]: r for r in wide}
        assert by_region["US"]["_df_row_role"] == "value"
        assert by_region["US subtotal"]["_df_row_role"] == "summary", (
            "summary row must not be silently downgraded to a plain data row"
        )


class TestPivotRowTotalsTrailingColumn:
    """A query-provided literal "Total" pivot-column value reshapes into a
    trailing leaf column naturally — no render-side aggregation or detection."""

    def test_total_column_value_becomes_trailing_leaf(self) -> None:
        from dbt_charts.core.render.chart.table import pivot_table_data

        data = [
            {"region": "US", "quarter": "Q1", "revenue": 100},
            {"region": "US", "quarter": "Q2", "revenue": 200},
            {"region": "US", "quarter": "Total", "revenue": 300},
            {"region": "EU", "quarter": "Q1", "revenue": 90},
            {"region": "EU", "quarter": "Q2", "revenue": 180},
            {"region": "EU", "quarter": "Total", "revenue": 270},
        ]
        wide, levels, _ = pivot_table_data(
            data, rows=["region"], columns=["quarter"], values=["revenue"]
        )
        us = next(r for r in wide if r["region"] == "US")
        leaf_keys = [k for k in us if k != "region"]
        assert leaf_keys[-1] == "Total"
        assert us["Total"] == 300
        assert levels is None
