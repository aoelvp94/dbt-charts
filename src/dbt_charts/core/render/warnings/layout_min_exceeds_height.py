"""Detector: WARN_LAYOUT_MIN_EXCEEDS_HEIGHT — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart is a horizontal ResolvedBarChart AND
  it has a literal authored height somewhere in its ancestor chain
  (ctx.authored_chart_heights) AND
  min_height_for_horizontal_bar_categories(n, ...) — the same readability
  floor vega_lite.py's _render_vl_artifact applies at render time, where n is
  the whole dataset's distinct category count (the facet operator ordinarily
  resolves the category ordinal scale as shared, so every panel paints the
  union regardless of which rows landed in it — except a panel whose own
  rows carry a proper subset of the category domain, where
  `facet_bound_position_channels` narrows that axis independently and `n`
  narrows to the WIDEST panel's own count, via
  `effective_horizontal_bar_category_count`), then multiplied by the baked
  row-facet cardinality for a faceted `rows:` chart — exceeds that authored
  height.

The authored height comes from ctx.authored_chart_heights, a snapshot of
each chart's real, assigned px slot height taken while it's still intact —
after the sizing pass assigns it, before cols-alignment can re-expand it.
See layout_sizing.py's `_snapshot_authored_slot_heights` for the full
mechanism.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.resolve.chart.adaptive_stroke import (
    panel_axis_cardinality,
)
from dbt_charts.core.diagnostics import WARN_LAYOUT_MIN_EXCEEDS_HEIGHT, Diagnostic
from dbt_charts.core.render.chart.emitters._cartesian import (
    effective_horizontal_bar_category_count,
    facet_extra_axis_width_px,
    min_height_for_horizontal_bar_categories,
)
from dbt_charts.core.render.chart.vl_field_maps import effective_bar_size
from dbt_charts.core.render.warnings.base import (
    WarningContext,
    facet_channel_is_independent,
)


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per horizontal bar whose category floor exceeds
    its nearest ancestor's authored height."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, ResolvedBarChart):
            continue
        if chart.orientation != "horizontal":
            continue

        authored_height = ctx.authored_chart_heights.get(chart_id)
        if authored_height is None:
            continue

        rows = ctx.chart_results.get(chart_id)
        if not rows:
            continue

        # No render-time card width is available in a warning detector (this
        # runs from the already-resolved board, not the renderer's own
        # width/panel_cols locals) — but a columns/grid facet's affordability
        # verdict is recoverable from the emitted spec: `unit["width"]` is
        # already the FINAL, post-decision panel width, so if narrowing
        # applied, adding back the same measured reservation
        # (`facet_extra_axis_width_px`, a pure function of chart+data, no
        # width needed) recovers the pre-narrowing baseline exactly —
        # `_render_vl_artifact`'s own `unnarrowed_panel_width -
        # extra_axis_px` inverted. A rows-only facet (multiples.columns is
        # None) never reaches the affordability branch at all, so `None`
        # there is still correct, not a shortcut.
        unnarrowed_panel_width: float | None = None
        spec = ctx.vega_specs.get(chart_id)
        if (
            spec is not None
            and chart.multiples is not None
            and chart.multiples.columns is not None
        ):
            unit = spec["spec"] if "facet" in spec else spec
            render_width = unit.get("width")
            if isinstance(render_width, int | float):
                if facet_channel_is_independent(spec, "y"):
                    unnarrowed_panel_width = render_width + facet_extra_axis_width_px(
                        chart, chart.multiples, rows
                    )
                else:
                    unnarrowed_panel_width = render_width

        n = effective_horizontal_bar_category_count(chart, rows, unnarrowed_panel_width)
        min_h = min_height_for_horizontal_bar_categories(
            n, chart.style.axis_x, effective_bar_size(chart.style.mark)
        )
        if chart.multiples is not None:
            row_cardinality = panel_axis_cardinality(
                chart.panel_axes, chart.multiples.rows
            )
            min_h *= row_cardinality
        if min_h <= authored_height:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_LAYOUT_MIN_EXCEEDS_HEIGHT,
                chart=chart_id,
                message=WARN_LAYOUT_MIN_EXCEEDS_HEIGHT.message_template.format(
                    chart_id=chart_id,
                    n_categories=n,
                    min_height=min_h,
                    authored_height=authored_height,
                ),
                fix=WARN_LAYOUT_MIN_EXCEEDS_HEIGHT.fix_template,
            )
        )

    return warnings
