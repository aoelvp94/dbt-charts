"""Detector: WARN_SPARK_LABEL_TRUNCATED — fires when one or more spark bar
row labels were truncated because they exceeded the configured label width.

Detection rule: ``WarningContext.text_truncations`` contains records with
``surface == "spark_label"``.  One ``Diagnostic`` fires per chart with the
count of truncated labels.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_SPARK_LABEL_TRUNCATED, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart with truncated spark bar labels."""
    warnings: list[Diagnostic] = []
    for chart_id, truncations in ctx.text_truncations.items():
        spark_trunc = [t for t in truncations if t.surface == "spark_label"]
        if not spark_trunc:
            continue
        # Use authored_field from the first record — it's always "y".
        authored_field = spark_trunc[0].authored_field
        warnings.append(
            Diagnostic.from_code(
                WARN_SPARK_LABEL_TRUNCATED,
                chart=chart_id,
                field=None,
                path=f"charts.{chart_id}.{authored_field}",
                message=WARN_SPARK_LABEL_TRUNCATED.message_template.format(
                    chart_id=chart_id,
                    truncation_count=len(spark_trunc),
                ),
                fix=WARN_SPARK_LABEL_TRUNCATED.fix_template,
            )
        )
    return warnings
