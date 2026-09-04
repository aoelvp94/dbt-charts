"""Detector: WARN_CATEGORY_COLOR_PIN_UNSEEN — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  any CategoryColorScale bound to a chart on the board carries a non-empty
  `unseen_pins` mapping — a pin `_seatable_pins`
  (compile/resolve/style/category_colors.py) dropped because this render's
  rows never draw the pinned value.

One diagnostic per FIELD, not per chart and not per value: the identical
bound scale is attached to every chart that draws the field
(`_bound_scales` in compile/resolve/chart/_kwargs.py), so a naive per-chart
walk would fire once per chart for the same dropped pin.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_CATEGORY_COLOR_PIN_UNSEEN, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per field carrying a dropped category-color pin."""
    warnings: list[Diagnostic] = []
    seen_fields: set[str] = set()

    for chart in ctx.board_spec.charts.values():
        for scale in chart.category_colors:
            if not scale.unseen_pins or scale.field in seen_fields:
                continue
            seen_fields.add(scale.field)
            values = ", ".join(f"`{value}`" for value in scale.unseen_pins)
            warnings.append(
                Diagnostic.from_code(
                    WARN_CATEGORY_COLOR_PIN_UNSEEN,
                    chart=None,
                    path=f"style.charts.category_colors.{scale.field}",
                    field=scale.field,
                    message=WARN_CATEGORY_COLOR_PIN_UNSEEN.message_template.format(
                        field=scale.field, values=values
                    ),
                    fix=WARN_CATEGORY_COLOR_PIN_UNSEEN.fix_template,
                )
            )

    return warnings
