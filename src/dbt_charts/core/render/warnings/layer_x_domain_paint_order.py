"""Detector: WARN_LAYER_X_DOMAIN_PAINT_ORDER — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule (GEOMETRY-dependent):
  ``rendered_x_domain`` declined to place a layer's own x categories into the
  base's order, and recorded that in ``ctx.x_domain_paint_orders``.

The orderable half of this defect is not a warning: ``rendered_x_domain``
places layer-only values into the order the base already states, so a
date-like or numeric axis is fixed rather than reported. Only the residue — a
union the base states no order to absorb — is recorded, and this reports it.

Reading the capture rather than re-deriving the decision is the point. The
render path's guards (categorical x only, a ``sort:`` the emitter actually put
on the x encoding, values canonicalized to the form the emitter unions) all live
upstream of the record, so this detector cannot approximate them wrongly.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_LAYER_X_DOMAIN_PAINT_ORDER, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext

# How many of the layer-contributed categories the message names.
_SAMPLE = 3


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart whose shared x domain is paint-ordered."""
    warnings: list[Diagnostic] = []

    for chart_id, paint_order in ctx.x_domain_paint_orders.items():
        layer_only = paint_order.layer_only
        sample = ", ".join(repr(v) for v in layer_only[:_SAMPLE])
        if len(layer_only) > _SAMPLE:
            sample += ", …"
        warnings.append(
            Diagnostic.from_code(
                WARN_LAYER_X_DOMAIN_PAINT_ORDER,
                chart=chart_id,
                field=paint_order.x_field,
                path=f"charts.{chart_id}.x",
                message=WARN_LAYER_X_DOMAIN_PAINT_ORDER.message_template.format(
                    chart_id=chart_id,
                    n_new=len(layer_only),
                    plural="y" if len(layer_only) == 1 else "ies",
                    x_field=paint_order.x_field,
                    sample=sample,
                ),
                fix=WARN_LAYER_X_DOMAIN_PAINT_ORDER.fix_template,
            )
        )

    return warnings
