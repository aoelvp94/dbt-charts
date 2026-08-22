"""Detector: WARN_KPI_LABEL_TRUNCATED — fires when a KPI card label was cut
because it exceeded the two-line layout slot.

Detection rule: ``WarningContext.text_truncations`` contains records with
``surface == "kpi_label"``.  One ``Diagnostic`` fires per chart.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_KPI_LABEL_TRUNCATED, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart whose KPI label was truncated."""
    warnings: list[Diagnostic] = []
    for chart_id, truncations in ctx.text_truncations.items():
        for trunc in truncations:
            if trunc.surface != "kpi_label":
                continue
            warnings.append(
                Diagnostic.from_code(
                    WARN_KPI_LABEL_TRUNCATED,
                    chart=chart_id,
                    field=None,
                    path=f"charts.{chart_id}.{trunc.authored_field}",
                    message=WARN_KPI_LABEL_TRUNCATED.message_template.format(
                        chart_id=chart_id,
                        authored_text=trunc.authored_text,
                    ),
                    fix=WARN_KPI_LABEL_TRUNCATED.fix_template,
                )
            )
    return warnings
