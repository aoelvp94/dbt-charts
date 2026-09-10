"""Regression test: per-family theme overrides of _ChartStyleBase fields work.

The editorial theme sets charts.legend.visible: false (global default = suppress all
legends) and charts.bar.legend.visible: true (bar charts always show a legend).
Before the fix, charts.bar.legend.visible: true raised a ValidationError because
_ChartStyleBaseAllOptional used is_recursive=False, keeping nested BaseModel fields
as their compiled types (e.g. LegendStyle with all required fields), so a partial
dict like {visible: true} was rejected.

After the fix:
- _ChartStyleBaseAllOptional uses is_recursive=True, so legend becomes
  LegendStylePatch | None, accepting partial dicts.
- build_chart_style_context applies per-family theme patches when chart_type is given.
- editorial.yaml restores bar.legend.visible: true.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    HeatmapChart,
    LineChart,
    ScatterChart,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


class TestEditorialThemeBarLegend:
    """editorial theme: bar.legend.visible overrides the global visible:false default."""

    def test_editorial_theme_loads_without_validation_error(self):
        """get_theme_style('clarity') must not raise ValidationError."""
        theme = get_theme_style("clarity")
        assert theme is not None

    def test_editorial_global_legend_visible_false(self):
        """editorial global legend has visible: false (suppress legend by default)."""
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )

        resolved = resolve_chart_style_context(get_theme_style("clarity"))
        # Global legend from the theme (not per-chart override)
        assert resolved.legend.visible is False

    def test_editorial_bar_legend_visible_true(self):
        """bar charts in editorial theme should show a legend (visible: true)."""
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.compile.resolve.style.chart_context import (
            build_chart_style_context,
        )

        board = resolve_chart_style_context(get_theme_style("clarity"))
        # No chart-local overrides -- just the theme cascade
        effective = build_chart_style_context(board, BarChart(id="t", type="bar"))
        # bar charts should have visible=True (legend shown), overriding
        # the global visible=False from editorial.charts.legend.visible
        assert effective.legend.visible is True

    def test_editorial_scatter_legend_visible_true(self):
        """scatter charts in editorial theme should show a color legend."""
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.compile.resolve.style.chart_context import (
            build_chart_style_context,
        )

        board = resolve_chart_style_context(get_theme_style("clarity"))
        effective = build_chart_style_context(
            board, ScatterChart(id="t", type="scatter")
        )
        assert effective.legend.visible is True

    def test_editorial_heatmap_legend_visible_true(self):
        """heatmap charts in editorial theme should show a color legend.

        A heatmap encodes its whole measure in color, so it needs a key
        despite editorial's blanket "prefer direct labeling" default.
        """
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.compile.resolve.style.chart_context import (
            build_chart_style_context,
        )

        board = resolve_chart_style_context(get_theme_style("clarity"))
        effective = build_chart_style_context(
            board, HeatmapChart(id="t", type="heatmap")
        )
        assert effective.legend.visible is True

    def test_line_legend_visible_false_inherits_global(self):
        """line charts in editorial theme inherit the global visible: false."""
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.compile.resolve.style.chart_context import (
            build_chart_style_context,
        )

        board = resolve_chart_style_context(get_theme_style("clarity"))
        effective = build_chart_style_context(board, LineChart(id="t", type="line"))
        # line has no per-family legend override -- inherits global visible=False
        assert effective.legend.visible is False

    def test_no_chart_type_returns_base_charts(self):
        """Without per-family legend overrides and no style, returns board.charts unchanged."""
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.compile.resolve.style.chart_context import (
            build_chart_style_context,
        )

        board = resolve_chart_style_context(get_theme_style("clarity"))
        # "line" has no per-family legend patch in editorial, so fast path fires.
        effective = build_chart_style_context(board, LineChart(id="t", type="line"))
        assert effective is board
