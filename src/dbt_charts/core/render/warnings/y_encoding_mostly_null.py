"""Detector: WARN_Y_ENCODING_MOSTLY_NULL — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  NULL count / total rows > 0.5  (strictly greater-than)

Multi-y charts: the rule is evaluated per column; one warning is emitted per
offending column so the consumer can identify exactly which series is broken.

Missing-key semantics: a row that does not contain the y column key at all is
counted as NULL. This matches the rendering behavior — Vega-Lite treats missing
values the same as explicit null.

NULL-only (not NULL+zero): zero is a valid measurement (e.g. count of refunds).
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.resolve.chart._wide_fields import wide_measure_fields
from dbt_charts.core.diagnostics import WARN_Y_ENCODING_MOSTLY_NULL, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

# Strictly-greater-than threshold: null_count / row_count must exceed this.
_NULL_FRACTION_THRESHOLD = 0.5


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per y field that is >50% NULL across result rows."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, _CartesianResolvedChartFields):
            continue
        if not chart.y:
            continue
        # A chart absent from chart_results failed execution; nothing to analyze.
        if chart_id not in ctx.chart_results:
            continue

        rows = ctx.chart_results[chart_id]
        # Zero-row results are handled by the QUERY_RETURNED_ZERO_ROWS detector.
        if not rows:
            continue
        # Wide charts fold y: list via VL's fold transform; query rows carry the
        # authored measure columns, not the synthetic WIDE_VALUE_FIELD.
        if wide_fields := wide_measure_fields(chart):
            y_fields: list[str] = list(wide_fields)
        else:
            # Heatmap is the only remaining family that can still carry a
            # list y (its own multi-measure render path, not the fold).
            y_fields = chart.y if isinstance(chart.y, list) else [chart.y]
        total = len(rows)

        for y_field in y_fields:
            # Rows missing the key entirely are counted as NULL.
            null_count = sum(1 for row in rows if row.get(y_field) is None)
            if null_count / total > _NULL_FRACTION_THRESHOLD:
                warnings.append(
                    Diagnostic.from_code(
                        WARN_Y_ENCODING_MOSTLY_NULL,
                        chart=chart_id,
                        path=f"charts.{chart_id}.y",
                        field=y_field,
                        message=WARN_Y_ENCODING_MOSTLY_NULL.message_template.format(
                            chart_id=chart_id,
                            field=y_field,
                            null_pct=null_count / total,
                            row_count=total,
                        ),
                        fix=WARN_Y_ENCODING_MOSTLY_NULL.fix_template,
                    )
                )

    return warnings
