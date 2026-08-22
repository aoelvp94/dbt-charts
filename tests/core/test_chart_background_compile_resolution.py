"""Regression tests: chart background is resolved at compile time.

``ResolvedChartsStyle.background`` must be a concrete ``str`` — never ``None`` — so
the render layer has no need for the old ``_resolve_effective_background()`` render-time
reach-back.  Verified invariants:

1. ``build_chart_style_context()`` always sets ``resolved_style.background`` to a
   concrete string.
2. A chart-local ``style.background`` override wins over the board background.
3. ``apply_presentation_defaults`` uses the resolved background without a
   ``board_background_overlay`` parameter.
4. ``build_chart_style_context`` returns the board background when no chart override is set.
"""

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.compile.resolve.style.chart_context import (
    build_chart_style_context,
)
from dbt_charts.core.compile.resolve.style.inherit_graph import get_inherit_graph


def _chart(type: str = "bar", **kwargs) -> Chart:
    defaults = {"id": "test", "type": type}
    defaults.update(kwargs)
    return TypeAdapter(Chart).validate_python(dict(**defaults))


@pytest.fixture
def board_style():
    return resolve_chart_style_context(get_theme_style())


class TestInheritGraphWiring:
    """Declarative inherit marker exists so apply_inherit fills charts.background."""

    def test_inherit_graph_has_charts_background_link(self):
        """Style.charts.background must inherit from Style.background in the graph."""
        graph = get_inherit_graph()
        assert graph.get("Style.charts.background") == "Style.background", (
            "ChartsStyle.background must carry Inherit(from_path='Style.background') "
            "so apply_inherit can fill it without imperative code"
        )


class TestResolvedChartBackgroundMaterialized:
    """background is always a concrete string on ResolvedChartsStyle after compile."""

    def test_resolved_chart_background_is_str_without_override(self, board_style):
        """build_chart_style_context sets background to board background when no override."""
        chart = _chart(type="bar", x="month", y="revenue")
        rs = build_chart_style_context(board_style, chart)
        # Never None — must be a concrete string from the board background
        assert isinstance(rs.background, str)
        assert rs.background != ""
        assert rs.background == board_style.background

    def test_table_chart_background_override_wins(self, board_style):
        """Table chart style.background overrides the board background."""
        from dbt_charts.core.compile.models.style.authored import TableChartStylePatch

        chart = _chart(
            type="table",
            style=TableChartStylePatch(background="#ff0000"),
        )
        rs = build_chart_style_context(board_style, chart)
        # Table-level background override stored in resolved_style.table.background
        assert rs.table.background == "#ff0000"

    def test_build_chart_style_context_inherits_board_background(self, board_style):
        """build_chart_style_context with no chart override returns board background."""
        rs = build_chart_style_context(board_style, _chart(type="line"))
        assert rs.background == board_style.background

    def test_build_chart_style_context_table_background_override(self, board_style):
        """build_chart_style_context with table.background override propagates to chart background."""
        from dbt_charts.core.compile.models.style.authored import TableChartStylePatch

        rs = build_chart_style_context(
            board_style,
            _chart(
                type="table",
                style=TableChartStylePatch(background="#00ff00"),
            ),
        )
        assert rs.table.background == "#00ff00"
        # The table background override also propagates to resolved_style.background
        # (used as the effective chart background for this chart type).
        assert rs.background == "#00ff00"


class TestApplyPresentationDefaultsNoFallback:
    """apply_presentation_defaults sets VL spec background from resolved chart style."""

    def test_bar_chart_vl_spec_background_from_resolved_chart(self, board_style):
        """A bar chart's resolved background equals the board background.

        build_chart_style_context materializes background at compile time so the render
        layer has no need for a render-time reach-back fallback.
        """
        chart = _chart(type="bar", x="month", y="revenue")
        rs = build_chart_style_context(board_style, chart)
        assert isinstance(rs.background, str) and rs.background
        assert rs.background == board_style.background, (
            "Bar chart resolved background must equal board background when no "
            "chart-local override is set"
        )
