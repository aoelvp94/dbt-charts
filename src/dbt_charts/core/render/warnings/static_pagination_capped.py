"""Detector: WARN_STATIC_PAGINATION_CAPPED — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Tables are a custom SVG renderer, not Vega-Lite, so there is no spec to
inspect. Instead the renderer records the cap at the exact point it decides
to stop pre-rendering pages into ``WarningContext.static_pagination_caps``
(see ``render/chart/table_static_pagination.py``). This detector is
policy-only: it reads that captured state, so the warning fires on exactly
what rendered — no second page-count computation to drift from the
renderer's.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_STATIC_PAGINATION_CAPPED, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one warning per table whose static export hit the page cap."""
    warnings: list[Diagnostic] = []

    for chart_id, cap in ctx.static_pagination_caps.items():
        warnings.append(
            Diagnostic.from_code(
                WARN_STATIC_PAGINATION_CAPPED,
                chart=chart_id,
                message=WARN_STATIC_PAGINATION_CAPPED.message_template.format(
                    chart_id=chart_id,
                    rendered_pages=cap.rendered_pages,
                    total_pages=cap.total_pages,
                ),
                fix=WARN_STATIC_PAGINATION_CAPPED.fix_template,
            )
        )

    return warnings
