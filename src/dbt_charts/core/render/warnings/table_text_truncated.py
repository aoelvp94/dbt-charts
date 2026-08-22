"""Detector: WARN_TABLE_TEXT_TRUNCATED — fires when table header labels or cell
values were clipped with an ellipsis during SVG rendering.

Detection rule: ``WarningContext.text_truncations`` contains records with
``surface in {"table_header", "table_cell"}``.  One ``Diagnostic`` fires per
(chart, authored_field) pair with the count of truncated records for that
column, so every column that overflows gets its own squiggle.
"""

from __future__ import annotations

from collections import Counter

from dbt_charts.core.diagnostics import WARN_TABLE_TEXT_TRUNCATED, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

_TABLE_SURFACES = frozenset({"table_header", "table_cell"})


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per (chart, column) with truncated text."""
    warnings: list[Diagnostic] = []
    for chart_id, truncations in ctx.text_truncations.items():
        counts: Counter[str] = Counter(
            t.authored_field for t in truncations if t.surface in _TABLE_SURFACES
        )
        for col, count in counts.items():
            warnings.append(
                Diagnostic.from_code(
                    WARN_TABLE_TEXT_TRUNCATED,
                    chart=chart_id,
                    field=None,
                    path=f"charts.{chart_id}.{col}",
                    message=WARN_TABLE_TEXT_TRUNCATED.message_template.format(
                        chart_id=chart_id,
                        authored_field=col,
                        truncation_count=count,
                    ),
                    fix=WARN_TABLE_TEXT_TRUNCATED.fix_template,
                )
            )
    return warnings
