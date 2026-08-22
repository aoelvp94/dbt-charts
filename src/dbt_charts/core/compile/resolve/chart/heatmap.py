"""Heatmap chart resolver."""

from __future__ import annotations

from dbt_charts.core.compile.merge import merge_onto_base
from dbt_charts.core.compile.models.chart.normalized import (
    HeatmapChart,
)
from dbt_charts.core.compile.models.chart.resolved import (
    ResolvedHeatmapChart,
)
from dbt_charts.core.compile.models.primitives import (
    ScaleTargetConfig,
    bake_scale_target_stops,
)
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedHeatmapStyle
from dbt_charts.core.compile.resolve.chart._axes import (
    _NO_RAIL_ENDPOINT_LABELS,
    _author_hid_legend,
    _bake_ay_position_left,
    cartesian_series_naming,
)
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartDataset
from dbt_charts.core.compile.resolve.chart._domain import _CartesianTickResolution
from dbt_charts.core.compile.resolve.chart._kwargs import (
    AutomaticLinkCandidate,
    ChartTextVariables,
    _base_kwargs,
    _cartesian_kwargs,
    _title_font,
)
from dbt_charts.core.compile.resolve.chart._palette import (
    _effective_palette,
    _effective_requested_alias_palette,
)
from dbt_charts.core.compile.resolve.chart._plan import (
    build_cartesian_axes,
    plan_cartesian,
)
from dbt_charts.core.compile.resolve.style.chart_context import (
    build_chart_style_context,
)

__all__ = [
    "_resolve_heatmap",
]


def _resolve_heatmap(
    normalized: HeatmapChart,
    dataset: ChartDataset,
    chart_style_context: ChartStyleContext,
    width: float,
    automatic_link_candidate: AutomaticLinkCandidate,
    variables: ChartTextVariables,
) -> ResolvedHeatmapChart:
    data = dataset.all_rows()
    chart_local_style_context = build_chart_style_context(
        chart_style_context, normalized
    )
    plan = plan_cartesian(
        normalized,
        data,
        chart_style_context,
        "heatmap",
        "nominal",
        "nominal",
        normalized.multiples,
        normalized.y,
    )
    primary = plan.primary
    heatmap = merge_onto_base(chart_style_context.heatmap, primary)
    channels = plan.channels
    ax_merged, ay_merged = plan.ax_merged, plan.ay_merged
    naming = cartesian_series_naming(
        normalized,
        channels,
        _author_hid_legend(primary),
        width,
        _NO_RAIL_ENDPOINT_LABELS,
        endpoint_label_has_layers=False,
        has_layers=False,
        rail_eligible_for_suppression=False,
        suppress_wide_measure_series=False,
        multiples_wide_measure_series=False,
        layers_route_to_top_legend=False,
        unconditional_top_legend=False,
    )
    ay_merged = _bake_ay_position_left(ay_merged)
    # Heatmap's column axis (axis_x) is always a bottom-orient nominal band —
    # no left/right edge to resolve inward/outward align against.
    # Neither axis carries tick_values on a heatmap (both channels are
    # nominal), so the non-compacting bake can't fire on either --
    # format_authored=True is inert here, not a real provenance read.
    _ay, style_tail = build_cartesian_axes(
        normalized.id,
        chart_style_context,
        ax_merged,
        ay_merged,
        ax_band_position=plan.ax_band_position,
        ay_band_position=plan.ay_band_position,
        ax_edge=None,
        ay_format_authored=True,
        ay_format_is_alias=False,
        ticks=_CartesianTickResolution((), None, None),
        column_forming=True,
        measure_tooltip_format=None,
    )
    _tf = _title_font(normalized, chart_local_style_context, width)
    return ResolvedHeatmapChart(
        **_base_kwargs(
            normalized,
            chart_style_context,
            channels,
            heatmap.legend,
            _effective_palette(chart_style_context, primary),
            requested_alias_palette=_effective_requested_alias_palette(
                chart_style_context, primary
            ),
            automatic_link_candidate=automatic_link_candidate,
            layout_padding=heatmap.padding,
            suppress_legend=naming.suppress_legend,
            top_legend=naming.top_legend,
        ),
        **_cartesian_kwargs(
            normalized,
            chart_local_style_context,
            variables,
            data,
            "heatmap",
            panel_axes=dataset.axes,
        ),
        chart_type="heatmap",
        style=ResolvedHeatmapStyle(
            color_gradient=(
                bake_scale_target_stops(
                    ScaleTargetConfig.model_validate(
                        heatmap.color.gradient.model_dump(exclude_none=True)
                    )
                )
                if heatmap.color is not None and heatmap.color.gradient is not None
                else None
            ),
            rect_mark=heatmap.marks.rect,
            label_usable_ratio=chart_style_context.label_usable_ratio,
            title_font=_tf,
            **style_tail,
        ),
    )
