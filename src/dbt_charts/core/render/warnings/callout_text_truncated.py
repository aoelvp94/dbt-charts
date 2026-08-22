"""Detector: WARN_CALLOUT_TEXT_TRUNCATED — fires when a callout card's hint
or message text was cut with an ellipsis during SVG rendering.

Detection rule: ``WarningContext.text_truncations`` contains records with
``surface == "callout_text"``.  One ``Diagnostic`` fires per (chart,
authored_field) pair.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_CALLOUT_TEXT_TRUNCATED, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per (chart, authored_field) whose callout text was truncated."""
    warnings: list[Diagnostic] = []
    seen: set[tuple[str, str]] = set()
    for chart_id, truncations in ctx.text_truncations.items():
        for trunc in truncations:
            if trunc.surface != "callout_text":
                continue
            key = (chart_id, trunc.authored_field)
            if key in seen:
                continue
            seen.add(key)
            warnings.append(
                Diagnostic.from_code(
                    WARN_CALLOUT_TEXT_TRUNCATED,
                    chart=chart_id,
                    field=None,
                    path=f"charts.{chart_id}.{trunc.authored_field}",
                    message=WARN_CALLOUT_TEXT_TRUNCATED.message_template.format(
                        chart_id=chart_id,
                        authored_field=trunc.authored_field,
                        authored_text=trunc.authored_text,
                    ),
                    fix=WARN_CALLOUT_TEXT_TRUNCATED.fix_template,
                )
            )
    return warnings
