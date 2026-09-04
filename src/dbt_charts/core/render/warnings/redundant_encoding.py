"""Detector: WARN_REDUNDANT_ENCODING — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

The bar ``x==color`` case is excluded: the renderer suppresses the grouped-bar
offset and renders full-width category-colored bars, which is a useful pattern.

A ``multiples.rows``/``multiples.columns`` field colliding only with
``color``/``size``/``shape`` is excluded too, for a related reason: those
channels' legends are computed once across the whole faceted dataset and
drawn once, board-wide — never duplicated per panel (see
``facet_bound_position_channels``'s "color/theta/size are never included"
scoping in ``emitters/_cartesian.py``). A field carrying both a legend and
the facet split gives every panel a consistent, identifying color at no
duplication cost, the same way ``x==color`` does. ``x``/``y`` are different:
each panel draws its own axis, so a position channel bound to the facet
field repeats a single value on every panel, and that axis genuinely
duplicates what the panel header already says.

Detection rule:
  any field bound to >= 2 of the encoding channels
  {x, y, color, size, shape, theta, multiples.rows, multiples.columns}.
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

# Legend channels: color/size/shape draw one legend for the whole faceted
# board, never duplicated per panel — see this module's docstring.
_LEGEND_CHANNELS = frozenset({"color", "size", "shape"})
_FACET_CHANNELS = frozenset({"multiples.rows", "multiples.columns"})


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
            if chart.multiples is not None:
                if chart.multiples.rows is not None:
                    field_channels[chart.multiples.rows].append("multiples.rows")
                if chart.multiples.columns is not None:
                    field_channels[chart.multiples.columns].append("multiples.columns")

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
            channel_set = set(channels)
            # Bar x==color: the renderer collapses the offset channel and emits
            # full-width category-colored bars — a valid pattern. Skip here.
            if chart.chart_type == "bar" and channel_set == {"x", "color"}:
                continue
            # A facet channel colliding only with legend channels (color/size/
            # shape) is not redundant — see this module's docstring.
            if channel_set & _FACET_CHANNELS and channel_set <= (
                _FACET_CHANNELS | _LEGEND_CHANNELS
            ):
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
