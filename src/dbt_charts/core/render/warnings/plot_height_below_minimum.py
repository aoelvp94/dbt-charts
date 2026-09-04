"""Detector: WARN_PLOT_HEIGHT_BELOW_MINIMUM — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart is a ``ResolvedBarChart`` AND ``chart.style.plot_height_below_floor``
  is True — set at resolve time by ``bar.py``'s ``_resolve_bar``.

The detector itself does no height math: the estimate already happened at
resolve, in the same function that has the card's width, its authored
chrome, and its legend cardinality all in scope. This is a
placement-sensitive fact — a chart id placed at two different widths can be
tiny in one and not the other — so this walks ``ctx.layout_charts`` (each
chart's real, placement-matched instance) rather than ``ctx.board_spec.charts``
(the catalog, which can hold a different placement's resolution for the same
id). See ``pie_total_exceeds_inner_radius.py`` and
``legend_position_width_fallback.py`` for the same width-accuracy reasoning.

Fires on every composition ``_resolve_bar`` produces the fact for, since the
fact is stamped once on the resolved chart before any Vega-Lite composition
choice is made: flat, layered (``layers:``), faceted (``multiples:``),
stacked, horizontal, and a chart whose legend later gets wrapped into an
hconcat/vconcat endpoint-label pane at render. ``_resolve_histogram`` does
not compute the fact (leaves the field at its ``False`` default), so
histograms never fire here -- out of scope, not silently missed.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.resolve.chart.plot_height_floor import (
    plot_height_floor_px,
)
from dbt_charts.core.diagnostics import WARN_PLOT_HEIGHT_BELOW_MINIMUM, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per bar chart whose plot is starved for height."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.layout_charts.items():
        if not isinstance(chart, ResolvedBarChart):
            continue
        if not chart.style.plot_height_below_floor:
            continue

        card_height = chart.style.estimated_card_height_px
        warnings.append(
            Diagnostic.from_code(
                WARN_PLOT_HEIGHT_BELOW_MINIMUM,
                chart=chart_id,
                message=WARN_PLOT_HEIGHT_BELOW_MINIMUM.message_template.format(
                    chart_id=chart_id,
                    plot_height=chart.style.estimated_plot_height_px,
                    card_height=card_height,
                    floor_px=plot_height_floor_px(card_height),
                ),
                fix=WARN_PLOT_HEIGHT_BELOW_MINIMUM.fix_template,
            )
        )

    return warnings
