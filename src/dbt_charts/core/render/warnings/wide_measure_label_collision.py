"""Detector: WARN_WIDE_MEASURE_LABEL_COLLISION -- see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Known from `y: [...]` alone, no data needed -- ``resolve_wide_measure_
labels`` (``compile/resolve/chart/_wide_fields.py``) is the one place that
computes a wide chart's measure labels; every reader, including this
detector, calls it fresh from ``chart.wide_measures``.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.area import ResolvedAreaChart
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.chart.resolved.line import ResolvedLineChart
from dbt_charts.core.compile.resolve.chart._wide_fields import (
    resolve_wide_measure_labels,
)
from dbt_charts.core.diagnostics import WARN_WIDE_MEASURE_LABEL_COLLISION, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

_WIDE_MEASURE_FAMILIES = (ResolvedBarChart, ResolvedAreaChart, ResolvedLineChart)


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart per group of wide y: measures that
    humanize to the same legend/axis label."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, _WIDE_MEASURE_FAMILIES):
            continue
        if not chart.wide_measures:
            continue

        _, collision_groups = resolve_wide_measure_labels(chart.wide_measures)
        for label, measures in collision_groups.items():
            warnings.append(
                Diagnostic.from_code(
                    WARN_WIDE_MEASURE_LABEL_COLLISION,
                    chart=chart_id,
                    path=f"charts.{chart_id}.y",
                    message=WARN_WIDE_MEASURE_LABEL_COLLISION.message_template.format(
                        chart_id=chart_id,
                        measures=", ".join(repr(m) for m in measures),
                        label=label,
                    ),
                    fix=WARN_WIDE_MEASURE_LABEL_COLLISION.fix_template,
                )
            )

    return warnings
