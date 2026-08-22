"""Detector: WARN_TOO_MANY_X_CATEGORIES — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  vega_specs[chart_id].encoding.x.type in {"nominal", "ordinal"} (or, for a
  bar chart, also "temporal" — see _BAR_ALLOWED_X_TYPES below)
  AND distinct x values in chart_results > _MAX_CATEGORIES
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.diagnostics import WARN_TOO_MANY_X_CATEGORIES, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext, encoding_channel_type

# Beyond this many categories a band axis is unreadable.
_MAX_CATEGORIES = 50

_CATEGORICAL_TYPES = frozenset({"nominal", "ordinal"})

# A bar draws one band per distinct x value regardless of whether Vega-Lite
# encodes that axis as ordinal or temporal — the density gate that flips
# bucketed temporal data off ordinal above ~60 distinct values does so purely
# to manage axis-label layout, not because the chart stopped being banded.
# Line/area/scatter charts don't get this widening: a dense temporal axis
# there is a continuous draw, not a crowded band, however many points it has.
_BAR_ALLOWED_X_TYPES = _CATEGORICAL_TYPES | frozenset({"temporal"})


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart with an overcrowded categorical x-axis."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, _CartesianResolvedChartFields):
            continue
        if chart.x is None:
            continue
        if chart_id not in ctx.vega_specs or chart_id not in ctx.chart_results:
            continue

        allowed_x_types = (
            _BAR_ALLOWED_X_TYPES
            if isinstance(chart, ResolvedBarChart)
            else _CATEGORICAL_TYPES
        )
        x_type = encoding_channel_type(ctx.vega_specs[chart_id], "x")
        if x_type not in allowed_x_types:
            continue

        x_field: str = chart.x
        distinct = len(
            {row[x_field] for row in ctx.chart_results[chart_id] if x_field in row}
        )
        if distinct <= _MAX_CATEGORIES:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_TOO_MANY_X_CATEGORIES,
                chart=chart_id,
                path=f"charts.{chart_id}.x",
                field=x_field,
                message=WARN_TOO_MANY_X_CATEGORIES.message_template.format(
                    chart_id=chart_id,
                    field=x_field,
                    count=distinct,
                    max_categories=_MAX_CATEGORIES,
                ),
                fix=WARN_TOO_MANY_X_CATEGORIES.fix_template,
            )
        )

    return warnings
