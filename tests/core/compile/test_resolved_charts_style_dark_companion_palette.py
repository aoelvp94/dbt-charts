"""ResolvedChartsStyle.dark_companion_palette — baked once at board-resolve time.

Render (data_table_attachment.py's per_series label ink) used to call
compile.palette.resolve_dark_companion_stops itself; that decision is now
projected onto the resolved contract so render only reads a field.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.compile.resolve.style.palette import resolve_dark_companion_stops


def test_resolved_charts_style_bakes_dark_companion_palette():
    ctx = resolve_chart_style_context(get_theme_style(get_default_theme_name()))
    assert len(ctx.dark_companion_palette) == len(ctx.palette)
    assert tuple(ctx.dark_companion_palette) == tuple(
        resolve_dark_companion_stops(ctx.palette)
    )


def test_resolved_charts_style_dark_companion_palette_is_positionally_aligned():
    """Each dark_companion_palette[i] is palette[i]'s own companion, not a scan result."""
    ctx = resolve_chart_style_context(get_theme_style(get_default_theme_name()))
    for bright, dark in zip(ctx.palette, ctx.dark_companion_palette, strict=True):
        assert dark == resolve_dark_companion_stops([bright])[0]
