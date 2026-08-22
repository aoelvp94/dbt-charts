"""Detector: WARN_TOO_MANY_COLOR_CATEGORIES — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  vega_specs[chart_id].encoding.color.type in {"nominal", "ordinal"}
  AND distinct color values in chart_results > _MAX_CATEGORIES
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved import effective_color_field
from dbt_charts.core.diagnostics import WARN_TOO_MANY_COLOR_CATEGORIES, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext, encoding_channel_type

# Categorical palettes lose distinguishability past roughly a dozen hues.
_MAX_CATEGORIES = 12

_CATEGORICAL_TYPES = frozenset({"nominal", "ordinal"})


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart with too many categorical color values."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        color_field = effective_color_field(chart)
        if color_field is None:
            continue
        if chart_id not in ctx.vega_specs or chart_id not in ctx.chart_results:
            continue

        color_type = encoding_channel_type(ctx.vega_specs[chart_id], "color")
        if color_type not in _CATEGORICAL_TYPES:
            continue

        distinct = len(
            {
                row[color_field]
                for row in ctx.chart_results[chart_id]
                if color_field in row
            }
        )
        if distinct <= _MAX_CATEGORIES:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_TOO_MANY_COLOR_CATEGORIES,
                chart=chart_id,
                path=f"charts.{chart_id}.color",
                field=color_field,
                message=WARN_TOO_MANY_COLOR_CATEGORIES.message_template.format(
                    chart_id=chart_id,
                    field=color_field,
                    count=distinct,
                    max_categories=_MAX_CATEGORIES,
                ),
                fix=WARN_TOO_MANY_COLOR_CATEGORIES.fix_template,
            )
        )

    return warnings
