"""Detector: WARN_KPI_ALIGN_OVERFLOW — fires when a KPI authored
``align: center``/``right`` but its value run was wider than the card, so the
renderer kept the run left-aligned instead of shifting it off the viewport.

Detection rule: ``WarningContext.text_truncations`` contains records with
``surface == "kpi_align_overflow"``. One ``Diagnostic`` fires per chart.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import (
    WARN_KPI_ALIGN_OVERFLOW,
    Diagnostic,
)
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart whose authored align could not apply."""
    warnings: list[Diagnostic] = []
    for chart_id, truncations in ctx.text_truncations.items():
        if not any(t.surface == "kpi_align_overflow" for t in truncations):
            continue
        warnings.append(
            Diagnostic.from_code(
                WARN_KPI_ALIGN_OVERFLOW,
                chart=chart_id,
                field=None,
                path=f"charts.{chart_id}.style.align",
                message=WARN_KPI_ALIGN_OVERFLOW.message_template.format(
                    chart_id=chart_id,
                ),
                fix=WARN_KPI_ALIGN_OVERFLOW.fix_template,
            )
        )
    return warnings
