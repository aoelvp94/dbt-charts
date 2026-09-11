"""Detector: WARN_TOO_MANY_COLOR_CATEGORIES — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  vega_specs[chart_id].encoding.color.type in {"nominal", "ordinal"}
  AND distinct color values in chart_results > _MAX_CATEGORIES
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved import effective_color_field
from dbt_charts.core.compile.resolve.chart._wide_fields import (
    WIDE_MEASURE_FAMILIES,
    raw_wide_series_names,
)
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

        rows = ctx.chart_results[chart_id]
        # The authored key the series come from — what the message names.
        authored_key, authored_field = "color", color_field
        if isinstance(chart, WIDE_MEASURE_FAMILIES) and chart.wide_measures:
            # The fold's series field exists only post-fold: count the pinned
            # domain (measures × dimension values — an all-null measure still
            # holds its palette slot), not the cells that carry a value.
            distinct = len(
                raw_wide_series_names(chart.wide_measures, chart.color, rows)
            )
            if chart.color is None:
                authored_key = authored_field = "y"
            else:
                authored_field = chart.color
        else:
            distinct = len({row[color_field] for row in rows if color_field in row})
        if distinct <= _MAX_CATEGORIES:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_TOO_MANY_COLOR_CATEGORIES,
                chart=chart_id,
                path=f"charts.{chart_id}.{authored_key}",
                field=authored_field,
                message=WARN_TOO_MANY_COLOR_CATEGORIES.message_template.format(
                    chart_id=chart_id,
                    field=authored_field,
                    count=distinct,
                    max_categories=_MAX_CATEGORIES,
                ),
                fix=WARN_TOO_MANY_COLOR_CATEGORIES.fix_template,
            )
        )

    return warnings
