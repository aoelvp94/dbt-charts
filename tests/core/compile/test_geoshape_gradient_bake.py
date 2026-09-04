"""Regression tests: geoshape's theme-cascade color.gradient must bake
resolved_stops for a named dbt charts palette, the same way resolve/heatmap.py's
color_gradient does — a different construction path than a chart-channel
scale (compile/resolve/chart/channel.py::_parse_channel_scale).
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.merge import merge_onto_base
from dbt_charts.core.compile.models.chart.normalized.geoshape import GeoshapeChart
from dbt_charts.core.compile.models.style.authored import GeoshapeChartStylePatch
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.resolve.chart.geo import _resolve_geoshape
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.compile.resolve.style.palette import palette as resolve_palette

_GEO_KWARGS = {
    "geo_source": "us-states",
    "lookup": "state_id",
    "value": "population",
}


def _board_with_geoshape_color_gradient(palette: str) -> ChartStyleContext:
    compiled = get_theme_style()
    gradient_patch = GeoshapeChartStylePatch.model_validate(
        {"color": {"gradient": {"palette": palette}}}
    )
    new_geoshape = merge_onto_base(compiled.charts.geoshape, gradient_patch)
    custom_charts = compiled.charts.model_copy(update={"geoshape": new_geoshape})
    return resolve_chart_style_context(
        compiled.model_copy(update={"charts": custom_charts})
    )


def test_geoshape_theme_gradient_dbt_charts_named_palette_resolves_to_stops() -> None:
    """A dbt charts named palette set at the theme level (charts.geoshape.color.
    gradient) must bake resolved_stops via _resolve_geoshape's own
    construction site — regression for the CRITICAL boundary bug where only
    the channel-scoped construction path baked resolved_stops, leaving this
    theme-cascade gradient unresolved and crashing render."""
    board_style = _board_with_geoshape_color_gradient("dbt-seq-blue")
    chart = GeoshapeChart(id="geo1", type="geoshape", **_GEO_KWARGS)

    resolved = _resolve_geoshape(chart, [], board_style, 800.0, None)

    assert resolved.style.geoshape is not None
    assert resolved.style.geoshape.color is not None
    gradient = resolved.style.geoshape.color.gradient
    assert gradient is not None
    assert gradient.resolved_stops == tuple(resolve_palette("dbt-seq-blue"))


def test_geoshape_chart_local_gradient_override_does_not_crash_on_named_theme_palette() -> (
    None
):
    """A board-level dbt charts named palette combined with a chart-local
    gradient override to a Vega scheme must resolve cleanly, not crash.
    Regression: baking resolved_stops inside ScaleTargetConfig's own
    validator crashed here, since merge_onto_base inherits the board's stale
    resolved_stops for the *old* palette when the chart-local patch only
    overrides `palette`."""
    board_style = _board_with_geoshape_color_gradient("dbt-seq-blue")
    chart = GeoshapeChart(
        id="geo1",
        type="geoshape",
        **_GEO_KWARGS,
        style=GeoshapeChartStylePatch.model_validate(
            {"color": {"gradient": {"palette": "viridis"}}}
        ),
    )

    resolved = _resolve_geoshape(chart, [], board_style, 800.0, None)

    from dbt_charts.core.compile.models.primitives import (
        ResolvedNamedPaletteScaleTargetConfig,
        ResolvedScaleTargetConfig,
    )

    gradient = resolved.style.geoshape.color.gradient
    assert gradient is not None
    assert gradient.palette == "viridis"
    # Vega scheme names produce a plain ResolvedScaleTargetConfig — no
    # resolved_stops field; the split makes this structurally impossible to
    # confuse with a named-palette that was actually resolved.
    assert type(gradient) is ResolvedScaleTargetConfig
    assert not isinstance(gradient, ResolvedNamedPaletteScaleTargetConfig)
