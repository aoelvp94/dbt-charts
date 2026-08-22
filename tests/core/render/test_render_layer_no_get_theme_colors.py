"""Regression: render layer must not use get_theme_colors (deleted function).

After migration, all render-layer color reads go through ResolvedStyle directly.
get_theme_colors and _theme_color_items have been deleted from colors.py.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style


def test_apply_presentation_defaults_uses_effective_vega_config_as_base():
    """effective_vega_config is used as the compiled base; callers must pass non-None."""
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
    from dbt_charts.core.render.chart.presentation import apply_presentation_defaults

    chart_style = resolve_chart_style_context(get_theme_style())
    sentinel = {"axis": {"grid": False}}
    result = apply_presentation_defaults(
        {}, chart_style.background, effective_vega_config=sentinel
    )
    assert result["config"].get("axis", {}).get("grid") is False
