"""Detector: WARN_PALETTE_UNSUPPORTED — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart.requested_alias_palette is not None — the chart authored a palette
  name on the known WARN-PALETTE-UNSUPPORTED anti-pattern list (e.g.
  "RdYlGn", "parula"). palette() resolves the substitute silently at compile
  time (see core/compile/resolve/style/palette.py); this detector is the only place the
  nudge surfaces, once per chart's compiled value — not once per internal
  palette() call during resolution. chart.requested_alias_substitute is a
  resolved-chart field computed once from requested_alias_palette (see
  compile/resolve/chart/_kwargs.py::_base_kwargs), so this detector never calls
  compile.palette itself.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import WARN_PALETTE_UNSUPPORTED, Diagnostic
from dbt_charts.core.render.warnings.base import WarningContext


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart authoring an anti-pattern palette alias."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        requested = chart.requested_alias_palette
        if requested is None:
            continue
        assert chart.requested_alias_substitute is not None, (
            "requested_alias_substitute must be baked whenever "
            "requested_alias_palette is set"
        )

        warnings.append(
            Diagnostic.from_code(
                WARN_PALETTE_UNSUPPORTED,
                chart=chart_id,
                # `requested_alias_palette` is set on CategoricalColorStyle, so
                # the authored key is under `style.color.categorical` — either
                # `palette` or `single_series_palette`. Naming the common one
                # walks up one level for the other, which is still the right
                # block. There is no `scale` node on ColorStyle.
                path=f"charts.{chart_id}.style.color.categorical.palette",
                field="palette",
                message=WARN_PALETTE_UNSUPPORTED.message_template.format(
                    chart_id=chart_id,
                    requested=requested,
                    resolved=chart.requested_alias_substitute,
                ),
                fix=WARN_PALETTE_UNSUPPORTED.fix_template,
            )
        )

    return warnings
