"""Detector: WARN_BAR_GROUPED_SERIES_COINCIDE — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart is a (non-horizontal) ResolvedBarChart AND
  some bar mark unit in vega_specs[chart_id] carries an `xOffset` channel AND
  that unit's effective `x` encoding is NOT banded — its VL type is not
  nominal/ordinal and it carries no timeUnit — so the offset channel has no
  band scale to divide series within and every series paints at the identical
  position and width.

Reads the emitted spec's own offset decision rather than re-deriving "is this
grouped" from resolved fields, for the reason spelled out in
`bar_band_width_too_narrow.py`'s `_grouped_series_count`: the bar emitter is
the single source of truth for whether a band is subdivided, and re-deriving
the predicate drifted from it in both directions.

Walks every mark unit (`iter_mark_units`) rather than reading the top-level
encoding alone. A grouped bar with authored `layers:` hoists only the shared
`x` to the root and leaves `xOffset` on the bar layer, so a top-level-only
read misses exactly the layered shape — the one where the bars paint at full
opacity and full width on top of each other, which reads as a legitimate
single-series chart rather than an obviously broken one.

Horizontal bars are out of scope by construction, not by omission:
`_emit_horizontal` types its categorical (y) channel "nominal" at its only
construction site, so a horizontal grouped bar always has a real band scale
and this defect cannot arise there.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.diagnostics import WARN_BAR_GROUPED_SERIES_COINCIDE, Diagnostic
from dbt_charts.core.render.chart.emitters._cartesian import x_encoding_is_banded
from dbt_charts.core.render.warnings.base import (
    WarningContext,
    iter_mark_units,
    unit_mark_type,
)


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per grouped bar chart whose series coincide."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, ResolvedBarChart):
            continue
        if chart.orientation == "horizontal":
            continue
        # x is the category field on both orientations — resolve refuses a
        # bar whose y is non-numeric, so it is never the categorical one.
        if chart.x is None:
            continue
        if chart_id not in ctx.vega_specs:
            continue

        if not any(
            unit_mark_type(unit) == "bar"
            and isinstance(encoding.get("xOffset"), dict)
            and isinstance(x_enc := encoding.get("x"), dict)
            and not x_encoding_is_banded(x_enc)
            for unit, encoding in iter_mark_units(ctx.vega_specs[chart_id])
        ):
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_BAR_GROUPED_SERIES_COINCIDE,
                chart=chart_id,
                path=f"charts.{chart_id}.x",
                field=chart.x,
                message=WARN_BAR_GROUPED_SERIES_COINCIDE.message_template.format(
                    chart_id=chart_id, field=chart.x
                ),
                fix=WARN_BAR_GROUPED_SERIES_COINCIDE.fix_template,
            )
        )

    return warnings
