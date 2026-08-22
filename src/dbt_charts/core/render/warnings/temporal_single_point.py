"""Detector: WARN_TEMPORAL_SINGLE_POINT — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart.chart_type in {"line", "area"}
  AND ctx.vega_specs[chart_id].encoding.x.type == "temporal"
  AND len(ctx.chart_results[chart_id]) == 1
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.diagnostics import WARN_TEMPORAL_SINGLE_POINT, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

# Chart types where a single temporal data point is misleading.
_TEMPORAL_LINE_TYPES = frozenset({"line", "area"})


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per line/area chart with a single temporal data point."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, _CartesianResolvedChartFields):
            continue
        if chart.chart_type not in _TEMPORAL_LINE_TYPES:
            continue
        # Respect the sparse vega_specs contract — non-Vega charts are omitted.
        if chart_id not in ctx.vega_specs:
            continue
        # Orphan charts (query not in pre_executed_query_names) are absent from chart_results.
        if chart_id not in ctx.chart_results:
            continue

        vega_x_type: str = (
            ctx.vega_specs[chart_id].get("encoding", {}).get("x", {}).get("type", "")
        )
        if vega_x_type != "temporal":
            continue

        if len(ctx.chart_results[chart_id]) != 1:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_TEMPORAL_SINGLE_POINT,
                chart=chart_id,
                path=f"charts.{chart_id}.x",
                field=chart.x,
                message=WARN_TEMPORAL_SINGLE_POINT.message_template.format(
                    chart_id=chart_id, chart_type=chart.chart_type
                ),
                fix=WARN_TEMPORAL_SINGLE_POINT.fix_template,
            )
        )

    return warnings
