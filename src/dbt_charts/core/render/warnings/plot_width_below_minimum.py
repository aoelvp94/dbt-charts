"""Detector: WARN_PLOT_WIDTH_BELOW_MINIMUM — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Unlike the height floor's detector, this one carries no resolve-time bake:
the fact ("the column block already claims most of the card's width") only
exists once the column block's own font-measured width is known, which
needs the executed query's rows — a render concern
(``render/chart/plot_width_floor_record.py``'s ContextVar sink), not
something `Resolved*` can carry. See that module's docstring for why the
sink is opened at both the sizing pass and the main render pass.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_PLOT_WIDTH_BELOW_MINIMUM, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart whose support_table column block
    already claims most of the card's width."""
    warnings: list[Diagnostic] = []

    for chart_id, share in ctx.plot_width_share_warnings.items():
        warnings.append(
            Diagnostic.from_code(
                WARN_PLOT_WIDTH_BELOW_MINIMUM,
                chart=chart_id,
                message=WARN_PLOT_WIDTH_BELOW_MINIMUM.message_template.format(
                    chart_id=chart_id,
                    block_width=share.column_block_width_px,
                    card_width=share.card_width_px,
                    plot_width=share.plot_width_px,
                ),
                fix=WARN_PLOT_WIDTH_BELOW_MINIMUM.fix_template,
            )
        )

    return warnings
