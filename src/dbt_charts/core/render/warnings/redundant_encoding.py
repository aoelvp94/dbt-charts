"""Detector: WARN_REDUNDANT_ENCODING — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

The bar ``x==color`` case is excluded: the renderer suppresses the grouped-bar
offset and renders full-width category-colored bars, which is a useful pattern.

Detection rule:
  any field bound to >= 2 of the encoding channels {x, y, color, size, shape, theta}.
  (A list-valued ``y`` is multi-series — intentionally distinct fields — and is
  skipped.)
"""

from __future__ import annotations

from collections import defaultdict

from dbt_charts.core.compile.models.chart.resolved import effective_color_field
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved.pie import ResolvedPieChart
from dbt_charts.core.compile.models.chart.resolved.scatter import ResolvedScatterChart
from dbt_charts.core.diagnostics import (
    WARN_REDUNDANT_ENCODING,
    Diagnostic,
    RelatedLocation,
)
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per field bound to >= 2 channels of a chart."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        field_channels: dict[str, list[str]] = defaultdict(list)

        # x, y: cartesian V2 families.
        if isinstance(chart, _CartesianResolvedChartFields):
            if isinstance(chart.x, str):
                field_channels[chart.x].append("x")
            # List-valued y is multi-series (distinct fields) — skip.
            if isinstance(chart.y, str):
                field_channels[chart.y].append("y")

        # size, shape: scatter V2.
        if isinstance(chart, ResolvedScatterChart):
            if isinstance(chart.size, str):
                field_channels[chart.size].append("size")
            if isinstance(chart.shape, str):
                field_channels[chart.shape].append("shape")

        # theta: pie V2.
        if isinstance(chart, ResolvedPieChart):
            field_channels[chart.theta].append("theta")
        # Color is in resolved_channels, not a direct field on ResolvedChart.
        color_field = effective_color_field(chart)
        if color_field is not None:
            field_channels[color_field].append("color")

        for field, channels in field_channels.items():
            if len(channels) < 2:
                continue
            # Bar x==color: the renderer collapses the offset channel and emits
            # full-width category-colored bars — a valid pattern. Skip here.
            if chart.chart_type == "bar" and set(channels) == {"x", "color"}:
                continue
            channel_list = ", ".join(sorted(channels))
            # The complaint is about the *pair*, so marking one channel alone
            # tells half of it. Anchor the first and carry every other one as a
            # related location, each labelled with the channel it is.
            first, *rest = sorted(channels)
            warnings.append(
                Diagnostic.from_code(
                    WARN_REDUNDANT_ENCODING,
                    chart=chart_id,
                    field=field,
                    path=f"charts.{chart_id}.{first}",
                    related=tuple(
                        RelatedLocation(
                            path=f"charts.{chart_id}.{channel}",
                            message=(
                                f"also bound to {field!r} — this is the "
                                "redundant binding"
                            ),
                        )
                        for channel in rest
                    ),
                    message=WARN_REDUNDANT_ENCODING.message_template.format(
                        chart_id=chart_id, field=field, channels=channel_list
                    ),
                    fix=WARN_REDUNDANT_ENCODING.fix_template,
                )
            )

    return warnings
