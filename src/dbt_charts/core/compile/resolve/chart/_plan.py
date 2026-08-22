"""The cartesian prelude and postlude every family resolver composes explicitly.

``plan_cartesian`` runs the shared setup (channels, axis cascade bake) every
cartesian family needs before its own stack/zero/domain math.
``build_cartesian_axes`` runs the shared teardown (the two
``ResolvedAxisStyle`` builds, the style tail, and the tooltip-format merge)
once each family has finished mutating its own axis pair; the caller passes
its final, post-mutation axes directly, not a ``CartesianPlan``.
Tick/zero/domain resolution stays in each family's own file — this module
only shares what every family assembles identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from dbt_charts.core.compile.models.chart.authored import MultiplesConfig
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    HeatmapChart,
    LineChart,
    ScatterChart,
)
from dbt_charts.core.compile.models.chart.resolved import ResolvedStyleChannel
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedAxisStyle
from dbt_charts.core.compile.models.style.theme import AxisXStyle, AxisYStyle
from dbt_charts.core.compile.resolve.chart._axes import (
    _bake_cartesian_axes,
    _edge_or_none,
    _extract_axis_overrides,
)
from dbt_charts.core.compile.resolve.chart._channels import _channels_for
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartRows
from dbt_charts.core.compile.resolve.chart._domain import _CartesianTickResolution
from dbt_charts.core.compile.resolve.chart._palette import (
    _cartesian_style_tail,
    _with_color_tokens,
)
from dbt_charts.core.compile.resolve.style.axis_cascade import build_resolved_axis

__all__ = [
    "CartesianPlan",
    "build_cartesian_axes",
    "plan_cartesian",
]


# The five families plan_cartesian serves (histogram reuses BarChart). Not
# ``Chart`` — that wider union also covers non-cartesian families (kpi,
# table, callout, ...) that inherit BaseModel directly rather than the
# shared _CartesianChartFields base _channels_for requires. Every member
# here declares its own ``style``/``x_label``/``y_label`` field, so plan_cartesian
# reads them straight off ``normalized`` instead of taking them as separate
# parameters.
_PlanChart = BarChart | LineChart | AreaChart | ScatterChart | HeatmapChart


class _StyleTail(TypedDict):
    """The ``ResolvedXxxStyle`` kwargs every cartesian family splats in verbatim."""

    tooltip_format: str
    axis_x: ResolvedAxisStyle
    axis_y: ResolvedAxisStyle


@dataclass(frozen=True)
class CartesianPlan:
    """Output of the shared cartesian prelude, before family-specific work.

    ``primary`` stays ``Any``, deliberately not narrowed to
    ``_CartesianChartStyle | None`` (the type ``resolve_y_zero``/
    ``_bake_y_zero``/``_extract_axis_overrides`` already use for this same
    value): four shared helpers every family calls with ``primary``
    (``_effective_palette``, ``_effective_requested_alias_palette``,
    ``_resolved_series_label``, ``_effective_single_series_fill``) instead
    take ``_HasColor | None``, and pyright's Protocol matching for a mutable
    attribute is invariant — ``_CartesianChartStyle.color: ColorStyle | None``
    does not satisfy ``_HasColor.color: ColorStyle | StaticGradientColorStyle
    | None``, even though every real value trivially would. Narrowing
    ``_HasColor`` would under-type pie/geo's own callers (which need the
    wider union); widening ``_CartesianChartStyle.color`` reverses a
    deliberate, documented narrowing on the theme model itself (see the
    ``color`` field override comment on ``_chart_base.py``'s
    ``_PaintedChartStyleBaseAllOptional`` stub). Both are theme/style-model changes
    outside this struct's one field.
    """

    primary: Any
    channels: dict[str, ResolvedStyleChannel]
    ax_merged: AxisXStyle
    ay_merged: AxisYStyle
    ax_band_position: float | None
    ay_band_position: float | None
    ay_format_authored: bool
    ay_format_is_alias: bool


def plan_cartesian(
    normalized: _PlanChart,
    data: ChartRows,
    chart_style_context: ChartStyleContext,
    chart_type: str,
    x_channel_type: str,
    y_channel_type: str,
    multiples: MultiplesConfig | None,
    y: str | list[str] | None,
) -> CartesianPlan:
    """Run the shared cartesian prelude: channels, axis bake.

    ``x_channel_type``/``y_channel_type``/``multiples``/``y`` are
    family-supplied rather than read off ``normalized`` here: heatmap
    hardcodes both channel types to "nominal" instead of classifying the
    data, and histogram passes ``multiples=None, y=None`` regardless of what
    its (reused ``BarChart``-typed) ``normalized.multiples``/``.y`` carry —
    both are family decisions, not branches inside this function.
    """
    primary = _with_color_tokens(normalized.style, chart_style_context)
    channels = _channels_for(normalized, data)
    axis_overrides = _extract_axis_overrides(primary)
    (
        ax_merged,
        ay_merged,
        ax_band_position,
        ay_band_position,
        ay_format_authored,
        ay_format_is_alias,
    ) = _bake_cartesian_axes(
        chart_style_context,
        normalized,
        chart_type,
        x_channel_type,
        y_channel_type,
        axis_overrides,
        multiples=multiples,
        y=y,
    )
    return CartesianPlan(
        primary=primary,
        channels=channels,
        ax_merged=ax_merged,
        ay_merged=ay_merged,
        ax_band_position=ax_band_position,
        ay_band_position=ay_band_position,
        ay_format_authored=ay_format_authored,
        ay_format_is_alias=ay_format_is_alias,
    )


def build_cartesian_axes(
    chart_id: str,
    chart_style_context: ChartStyleContext,
    ax_merged: AxisXStyle,
    ay_merged: AxisYStyle,
    ax_band_position: float | None,
    ay_band_position: float | None,
    ax_edge: Literal["left", "right"] | None,
    ay_format_authored: bool,
    ay_format_is_alias: bool,
    ticks: _CartesianTickResolution,
    column_forming: bool,
    measure_tooltip_format: str | None,
    ay_is_quantitative: bool = True,
) -> tuple[ResolvedAxisStyle, _StyleTail]:
    """Run the shared cartesian postlude: the resolved y-axis + the style tail.

    ``ax`` (the resolved x-axis) is not returned: it only ever feeds
    ``style_tail["axis_x"]`` below, and every call site already reads that
    off the tail rather than the axis object directly.

    ``ax_merged``/``ay_merged`` are the family's own local variables: each
    family's final axes, after whatever family-specific mutation
    (orientation, zero-anchor, log-domain) it ran. This function takes no
    ``CartesianPlan``, so no frozen-struct attribute is in reach here. The
    caller's ``plan`` is still live at the call site, though, so passing
    ``plan.ay_merged`` stays expressible and type-clean: each family unpacks
    the merged axes once below ``plan_cartesian()`` and reads them from that
    local thereafter. That single unpack is a convention, not a guarantee the
    signature can enforce.

    ``ax_band_position``/``ay_band_position`` come straight off
    ``CartesianPlan`` at every call site: no family mutates them after the
    bake, so there is no local variable guarding a stale read the way
    ``ax_merged``/``ay_merged`` need one.

    ``ay_format_authored``/``ay_format_is_alias`` are parameters rather than
    read off a shared struct directly: heatmap and histogram discard the
    cascade's real answer and hardcode ``True``/``False`` (neither axis
    carries a real format), while bar/line/area/scatter pass the cascade's
    own values through.

    ``measure_tooltip_format`` folds the two spellings every family used to
    apply separately (a conditional override in bar/line/area, an
    unconditional override with a fallback in scatter) into the one formula
    below — verified to already produce the same value either way, since
    ``_cartesian_style_tail`` bakes that same fallback as its own default.
    """
    ax = build_resolved_axis(
        ax_merged,
        band_position=ax_band_position,
        edge=ax_edge,
        format_authored=True,
        format_is_alias=False,
        chart_id=chart_id,
    )
    ay = build_resolved_axis(
        ay_merged,
        band_position=ay_band_position,
        edge=_edge_or_none(ay_merged.position),
        tick_values=ticks.ticks,
        format_authored=ay_format_authored,
        format_is_alias=ay_format_is_alias,
        is_quantitative=ay_is_quantitative,
        chart_id=chart_id,
        column_forming=column_forming,
        domain_max=ticks.domain_max if ticks.domain_max is not None else ...,
        domain_min=ticks.domain_min if ticks.domain_min is not None else ...,
    )
    tail = _cartesian_style_tail(chart_style_context, ax, ay)
    style_tail: _StyleTail = {
        "tooltip_format": measure_tooltip_format or tail["tooltip_format"],
        "axis_x": tail["axis_x"],
        "axis_y": tail["axis_y"],
    }
    return ay, style_tail
