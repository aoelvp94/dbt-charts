"""Detector: WARN_PIE_DOMINANT_SEGMENT — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart.chart_type == "pie"
  AND theta field present and numeric across rows
  AND max(theta) / sum(theta) >= _DOMINANT_SHARE
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.pie import ResolvedPieChart
from dbt_charts.core.diagnostics import WARN_PIE_DOMINANT_SEGMENT, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

# One slice at or above this share makes the rest visually negligible.
_DOMINANT_SHARE = 0.95


def _is_positive_number(value: object) -> bool:
    """True for a real (non-bool) number strictly greater than zero."""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value > 0


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per pie chart dominated by a single segment."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, ResolvedPieChart):
            continue
        theta_field = chart.theta
        if chart_id not in ctx.chart_results:
            continue
        values = [
            float(row[theta_field])
            for row in ctx.chart_results[chart_id]
            if theta_field in row and _is_positive_number(row[theta_field])
        ]
        # Need at least two positive slices for "dominant" to mean anything.
        if len(values) < 2:
            continue

        total = sum(values)
        share = max(values) / total
        if share < _DOMINANT_SHARE:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_PIE_DOMINANT_SEGMENT,
                chart=chart_id,
                path=f"charts.{chart_id}.type",
                field=theta_field,
                message=WARN_PIE_DOMINANT_SEGMENT.message_template.format(
                    chart_id=chart_id, dominant_field=theta_field, dominant_share=share
                ),
                fix=WARN_PIE_DOMINANT_SEGMENT.fix_template,
            )
        )

    return warnings
