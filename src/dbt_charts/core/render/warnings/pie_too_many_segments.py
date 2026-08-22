"""Detector: WARN_PIE_TOO_MANY_SEGMENTS — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart.chart_type == "pie"  AND  len(chart_results[chart_id]) > _MAX_SEGMENTS
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_PIE_TOO_MANY_SEGMENTS, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

# A pie stays legible up to a handful of slices; beyond this, recommend a bar.
_MAX_SEGMENTS = 5


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per pie chart with more than _MAX_SEGMENTS slices."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        # chart_type check covers both V1 ResolvedChart and V2 ResolvedPieChart.
        if chart.chart_type != "pie":
            continue
        if chart_id not in ctx.chart_results:
            continue

        segment_count = len(ctx.chart_results[chart_id])
        if segment_count <= _MAX_SEGMENTS:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_PIE_TOO_MANY_SEGMENTS,
                chart=chart_id,
                path=f"charts.{chart_id}.type",
                message=WARN_PIE_TOO_MANY_SEGMENTS.message_template.format(
                    chart_id=chart_id,
                    segment_count=segment_count,
                    max_segments=_MAX_SEGMENTS,
                ),
                fix=WARN_PIE_TOO_MANY_SEGMENTS.fix_template,
            )
        )

    return warnings
