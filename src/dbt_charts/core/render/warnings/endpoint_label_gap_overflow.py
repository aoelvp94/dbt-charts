"""Detector: WARN_ENDPOINT_LABEL_GAP_OVERFLOW and WARN_ENDPOINT_LABEL_RAIL_TIED —
see their `doc` entries in `core/diagnostics/codes_render.py`.

Detection rule:
  ``WarningContext.endpoint_label_gap_overflows`` is non-empty for a chart —
  ``recascade_endpoint_labels`` (``render/chart/features/endpoint_labels.py``),
  called from the post-probe correction pass in
  ``render/converters/chart.py``, could not honour the intended pixel gap and
  distributed labels evenly instead.

  The record's ``cause`` picks the code, because the two have different
  remedies: ``gap_did_not_fit`` is fixable with height or fewer series;
  ``no_slope`` is a property of the data and height cannot touch it. Emitting
  one code for both told authors to grow a chart that was already tall enough.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import (
    WARN_ENDPOINT_LABEL_GAP_OVERFLOW,
    WARN_ENDPOINT_LABEL_RAIL_TIED,
    Diagnostic,
)
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart whose endpoint-label rail was degraded."""
    warnings: list[Diagnostic] = []
    for chart_id, overflow in ctx.endpoint_label_gap_overflows.items():
        code = (
            WARN_ENDPOINT_LABEL_GAP_OVERFLOW
            if overflow.cause == "gap_did_not_fit"
            else WARN_ENDPOINT_LABEL_RAIL_TIED
        )
        warnings.append(
            Diagnostic.from_code(
                code,
                chart=chart_id,
                path=f"charts.{chart_id}.style.endpoint_labels",
                message=code.message_template.format(
                    chart_id=chart_id,
                    series_count=overflow.series_count,
                    gap_px=overflow.gap_px,
                ),
                fix=code.fix_template,
            )
        )
    return warnings
