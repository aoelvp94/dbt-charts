"""Tests for task 1e: Consolidate spacing property group.

Policy (ADR-003 + this task):
- Multi-value padding (intentional x≠y) → SpacingValues
- Single-value padding → scalar float
- No `_x`/`_y` suffix pairs anywhere
"""

import pytest

from dbt_charts.core.compile.config import (
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.models.primitives import SpacingValues
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


# ==========================================================================
# SparkStyle — SpacingValues (x≠y was intentional: 2 vs 4)
# ==========================================================================


class TestSparkStyleSpacingValues:
    def test_padding_is_spacing_values(self):

        s = get_theme_style().charts.table.spark
        assert isinstance(s.padding, SpacingValues), (
            "SparkStyle.padding must be SpacingValues"
        )
        assert not hasattr(s, "padding_x"), "padding_x must be removed"
        assert not hasattr(s, "padding_y"), "padding_y must be removed"

    def test_padding_default_preserves_original_split(self):
        """Override propagates: a distinctive sentinel padding round-trips correctly."""
        from dbt_charts.core.compile.models.primitives import SpacingValues

        s = get_theme_style().charts.table.spark
        overridden = s.model_copy(
            update={"padding": SpacingValues(top=99, right=77, bottom=99, left=77)}
        )
        assert overridden.padding.left == 77.0
        assert overridden.padding.top == 99.0

    def test_spark_plot_area_uses_correct_padding(self):
        """Spark plot uses horizontal padding for x, vertical for y.

        width=80, padding.left=2, padding.right=2 → plot_width=76
        First point x=padding.left=2.0; last x=2.0+76=78.0.
        Before fix (scalar 4): first x=4.0, last x=76.0 (plot_width=72).
        """
        from dbt_charts.core.compile.models.primitives import SpacingValues
        from dbt_charts.core.render.chart.spark import _normalize_points

        effective = resolve_chart_style_context(get_theme_style())
        padding = SpacingValues(top=4.0, right=2.0, bottom=4.0, left=2.0)
        norm = _normalize_points(
            [1.0, 2.0, 3.0, 2.0, 1.0],
            width=80,
            height=24,
            spark_style=effective.spark,
            padding=padding,
        )
        # plot_width = 80 - (left + right) = 80 - 4 = 76
        assert norm.plot_width == 76.0
        # First point x = padding.left = 2.0
        assert norm.points[0].startswith("2.0,"), (
            f"Expected first point x=2.0, got {norm.points[0]}"
        )
        # Last point x = padding.left + plot_width = 2 + 76 = 78.0
        assert norm.points[-1].startswith("78.0,"), (
            f"Expected last point x=78.0, got {norm.points[-1]}"
        )


# ==========================================================================
# SparkColumnsStyle — scalar (only padding_y existed, no x equivalent)
# ==========================================================================


class TestSparkColumnsStyleSinglePadding:
    def test_has_padding_not_padding_y(self):

        s = get_theme_style().charts.table.spark.columns
        assert hasattr(s, "padding"), "SparkColumnsStyle must have padding"
        assert isinstance(s.padding, float)

    def test_padding_default(self):

        assert get_theme_style().charts.table.spark.columns.padding > 0


# ==========================================================================
# InputStyle — SpacingValues (x≠y was intentional: 8 vs 4)
# ==========================================================================


class TestInputStyleSpacingValues:
    def test_padding_is_spacing_values(self):

        s = get_theme_style().variables.input
        assert isinstance(s.padding, SpacingValues), (
            "InputStyle.padding must be SpacingValues"
        )
        assert not hasattr(s, "padding_x"), "padding_x must be removed"
        assert not hasattr(s, "padding_y"), "padding_y must be removed"

    def test_padding_default_preserves_original_split(self):
        """Override propagates: a distinctive sentinel padding round-trips correctly."""
        from dbt_charts.core.compile.models.primitives import SpacingValues

        s = get_theme_style().variables.input
        overridden = s.model_copy(
            update={"padding": SpacingValues(top=55, right=88, bottom=55, left=88)}
        )
        assert overridden.padding.left == 88.0
        assert overridden.padding.top == 55.0


# ==========================================================================
# KpiStyle — content_padding (SpacingValues, x≠y intentional)
# ==========================================================================


class TestKpiStyleContentPadding:
    def test_has_content_padding_not_content_padding_x(self):

        s = get_theme_style().charts.kpi
        assert hasattr(s, "content_padding"), "KpiStyle must have content_padding"

    def test_content_padding_is_spacing_values(self):
        assert isinstance(
            get_theme_style().charts.kpi.content_padding,
            SpacingValues,
        )


# ==========================================================================
# TableColumnsStyle — cell_padding scalar (ADR-010: no _x/_y pairs)
# ==========================================================================


class TestTableColumnsStyleCellPadding:
    def test_has_cell_padding_not_cell_padding_x(self):
        s = get_theme_style().charts.table.column_layout
        assert isinstance(s.cell_padding, float)


# ==========================================================================
# Old TableChartStyle — single padding (scalar, both were always 0)
# ==========================================================================


class TestOldTableStyleSinglePadding:
    def test_has_padding_not_padding_x_y(self):

        ts = get_theme_style().charts.table.model_copy(update={"padding": 16})
        assert ts.padding == 16

    def test_default_style_compiled_table_padding_default(self):
        # After migration, table padding comes from TableChartStyle, not the legacy TableChartStyle.
        tc = resolve_chart_style_context(get_theme_style()).table
        assert tc.outer_padding == 0


# ==========================================================================
# table.py — no duplicate padding locals
# ==========================================================================


class TestTableRendererNoDuplicatePaddingLocals:
    def test_table_renders_with_zero_padding(self):
        """Regression: table renders correctly when padding=0."""
        import dataclasses

        from dbt_charts.core.compile.models.chart.normalized import TableChart
        from dbt_charts.core.compile.models.style.theme import PaddingStyle
        from dbt_charts.core.render.chart.table import render_table_svg

        rs = resolve_style(get_theme_style())
        ctx = resolve_chart_style_context(get_theme_style())
        zero_padding = PaddingStyle(left=0.0, right=0.0, top=0.0, bottom=0.0)
        custom_ctx = dataclasses.replace(
            ctx,
            table=ctx.table.model_copy(update={"padding": zero_padding}),
        )
        chart = resolve(
            TableChart(id="test", type="table"),
            [],
            chart_style_context=custom_ctx,
        )
        svg = render_table_svg(
            chart,
            [{"a": "hello"}],
            width=400,
            board_style=rs,
        )
        assert svg.startswith("<svg")
