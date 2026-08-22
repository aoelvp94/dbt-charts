"""Detector: WARN_POINT_MAP_OUT_OF_PROJECTION — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

albersUsa is hard-coded for CONUS + Alaska + Hawaii. d3-geo places coordinates
outside these three regions at an undefined/clamped position; the emitter drops
those rows from spec.data before Vega-Lite sees them. This warning tells the
author why points are missing from the map (and names the count that was dropped).

Detection rule (albersUsa only):
  chart.chart_type == "point_map"
  AND chart.geo_projection_type in BOUNDED_PROJECTIONS
  AND at least one row has lat/lon outside all three albersUsa regions.

Reads chart_results (pre-filter raw data) so the count matches exactly what
the emitter dropped.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.resolved import ResolvedPointMapChart
from dbt_charts.core.diagnostics import WARN_POINT_MAP_OUT_OF_PROJECTION, Diagnostic
from dbt_charts.core.render.chart.emitters.geo import (
    BOUNDED_PROJECTIONS,
    row_in_projection,
)
from dbt_charts.core.render.warnings.base import WarningContext


def _count_out_of_projection(
    rows: list[dict[str, Any]],
    lat_field: str,
    lon_field: str,
) -> int:
    return sum(
        1 for row in rows if row_in_projection(row, lat_field, lon_field) is False
    )


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one warning per point_map chart with out-of-projection points."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, ResolvedPointMapChart):
            continue

        if chart.geo_projection_type not in BOUNDED_PROJECTIONS:
            continue

        lat_field = chart.latitude
        lon_field = chart.longitude
        if lat_field is None or lon_field is None:
            continue

        rows = ctx.chart_results.get(chart_id, [])
        out_count = _count_out_of_projection(rows, lat_field, lon_field)
        if out_count == 0:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_POINT_MAP_OUT_OF_PROJECTION,
                chart=chart_id,
                path=f"charts.{chart_id}.projection",
                message=WARN_POINT_MAP_OUT_OF_PROJECTION.message_template.format(
                    chart_id=chart_id,
                    dropped_count=out_count,
                    total_count=len(rows),
                    projection=chart.geo_projection_type,
                ),
                fix=WARN_POINT_MAP_OUT_OF_PROJECTION.fix_template,
            )
        )

    return warnings
