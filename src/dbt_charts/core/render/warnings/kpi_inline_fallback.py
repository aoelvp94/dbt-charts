"""Detector: WARN_KPI_INLINE_VARIANT_FALLBACK_TO_STACKED — fires when an
inline KPI's assembled value/label/support run did not fit the card and the
renderer fell back to the stacked arrangement for it.

Detection rule: ``WarningContext.text_truncations`` contains records with
``surface == "kpi_inline_fallback"``. One ``Diagnostic`` fires per chart.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import (
    WARN_KPI_INLINE_VARIANT_FALLBACK_TO_STACKED,
    Diagnostic,
)
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart whose inline KPI fell back to stacked."""
    warnings: list[Diagnostic] = []
    for chart_id, truncations in ctx.text_truncations.items():
        for trunc in truncations:
            if trunc.surface != "kpi_inline_fallback":
                continue
            warnings.append(
                Diagnostic.from_code(
                    WARN_KPI_INLINE_VARIANT_FALLBACK_TO_STACKED,
                    chart=chart_id,
                    field=None,
                    path=f"charts.{chart_id}.{trunc.authored_field}",
                    message=WARN_KPI_INLINE_VARIANT_FALLBACK_TO_STACKED.message_template.format(
                        chart_id=chart_id,
                        authored_text=trunc.authored_text,
                    ),
                    fix=WARN_KPI_INLINE_VARIANT_FALLBACK_TO_STACKED.fix_template,
                )
            )
    return warnings
