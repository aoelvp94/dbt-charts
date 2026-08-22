"""Detector: WARN_POINT_MAP_NEGATIVE_SIZE_VALUES — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

A bubble_map's `size:` measure drives mark AREA, which cannot be negative.
The emitter (render/chart/emitters/geo.py, PointMapEmitter.emit) drops rows
with a negative size value before Vega-Lite sees them, using the same
row_has_negative_size predicate this detector counts with — so the count
this warning reports always matches what the emitter actually dropped.

Zero is not negative: a zero-valued row is legitimate data with a legitimate
area of nothing, and is neither dropped nor counted here.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved import ResolvedPointMapChart
from dbt_charts.core.diagnostics import WARN_POINT_MAP_NEGATIVE_SIZE_VALUES, Diagnostic
from dbt_charts.core.render.chart.emitters.geo import row_has_negative_size
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one warning per point_map/bubble_map chart with negative `size:` rows."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, ResolvedPointMapChart):
            continue
        if chart.size is None:
            continue
        if chart_id not in ctx.chart_results:
            continue

        rows = ctx.chart_results[chart_id]
        if not rows:
            continue

        negative_count = sum(
            1 for row in rows if row_has_negative_size(row, chart.size)
        )
        if negative_count == 0:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_POINT_MAP_NEGATIVE_SIZE_VALUES,
                chart=chart_id,
                path=f"charts.{chart_id}.size",
                field=chart.size,
                message=WARN_POINT_MAP_NEGATIVE_SIZE_VALUES.message_template.format(
                    chart_id=chart_id,
                    dropped_count=negative_count,
                    total_count=len(rows),
                    size_field=chart.size,
                ),
                fix=WARN_POINT_MAP_NEGATIVE_SIZE_VALUES.fix_template.format(
                    size_field=chart.size
                ),
            )
        )

    return warnings
