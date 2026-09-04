"""ChartStylePatch title font tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import (
    get_theme_style,
)

# ---------------------------------------------------------------------------
# ChartStylePatch
# ---------------------------------------------------------------------------


class TestChartStylePatchTitleFontNested:
    """BarChartStylePatch.title.font.color replaces flat title_color."""

    def test_flat_title_color_rejected(self) -> None:
        from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

        with pytest.raises(ValidationError):
            BarChartStylePatch.model_validate({"title_color": "#ff0000"})

    def test_title_font_color_accepted(self) -> None:
        from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

        p = BarChartStylePatch.model_validate({"title": {"font": {"color": "#ff0000"}}})
        assert p.title is not None
        assert p.title.font is not None
        assert p.title.font.color == "#ff0000"

    def test_title_defaults_to_none(self) -> None:
        from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

        p = BarChartStylePatch()
        assert p.title is None

    # `BarChartStylePatch.font` is gone: bar has no per-chart card to paint a
    # font onto. Its rejection is pinned by
    # test_chart_discriminated_union.py::test_card_style_dead_family_rejects_style_font,
    # and the "font is an object, not a string" shape by
    # test_kpi_still_accepts_style_font in the same file.


# ---------------------------------------------------------------------------
# Integration: ChartStylePatch title propagates through _build_resolved_style
# ---------------------------------------------------------------------------


class TestChartStylePatchTitlePropagation:
    """title.font.color on BarChartStylePatch reaches the resolved title after merge."""

    def test_title_font_color_propagates(self) -> None:
        from dbt_charts.core.compile.models.style.authored import (
            BarChartStylePatch,
        )
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.compile.resolve.style.chart_context import (
            build_chart_style_context as _build_resolved_style,
        )

        # Use a sentinel that won't appear in any theme defaults
        sentinel_color = "#abcde1"
        bar_patch = BarChartStylePatch.model_validate(
            {"title": {"font": {"color": sentinel_color}}}
        )
        base = resolve_chart_style_context(get_theme_style())
        from dbt_charts.core.compile.models.chart.normalized import BarChart

        effective = _build_resolved_style(
            base, BarChart(id="t", type="bar", style=bar_patch)
        )
        assert effective.title.font.color == sentinel_color
