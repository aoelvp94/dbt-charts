"""Compile-time concerns for the chart.data_table primitive.

Owns the parts of ``chart.data_table`` that are knowable before any query
runs: row pixel geometry (``row_height``, ``axis_offset``) and which
effective style applies after the per-chart-family cascade
(``resolve_effective_data_table_style``).

Strip height depends on ``series_count``, which is derived from query rows
(the size of the color domain), so ``data_table_strip_height`` is a render
concern — see ``dbt_charts.core.render.chart.data_table_attachment``. Data-aware
validation against the query output (``validate_data_table_against_data``)
and the Vega-Lite layer emission itself (``attach_data_table`` and its
helpers) live there too.
"""

from __future__ import annotations

from dbt_charts.core.compile.merge import merge_onto_base
from dbt_charts.core.compile.models.chart.authored import (
    ChartDataTable,
    ChartDataTablePerSeries,
)
from dbt_charts.core.compile.models.primitives import FormatConfig
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.theme import DataTableStyle
from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style

# Row geometry. These are the compiler's constants — they live here rather
# than on the style model because they are emitter mechanics, not user-facing
# theme tokens. If a theme wants denser rows, padding.vertical lets it.
_ROW_HEIGHT_BASE = 14.0  # per-row pixel height before padding


def row_height(style: DataTableStyle) -> float:
    padding = style.row.padding
    return _ROW_HEIGHT_BASE + padding.vertical * 2.0


def axis_offset(
    chart_style_context: ChartStyleContext,
    style: DataTableStyle,
    x_label_authored: bool,
    chart_type: str,
) -> float:
    """Pixel offset from plot bottom edge to the bottom of the x-axis block.

    Sums whichever axis components are actually visible: a chart with the
    title shown but labels suppressed still needs the title's height to
    sit above the strip, otherwise the strip's first row collides with it.

    label_max_lines × label height is reserved so yearly boundary ticks that
    emit a two-element array (e.g. ['Jan', '2024']) do not overlap the strip
    top edge. style.label_max_lines = 2 is the universal default; themes with
    a year-only cadence may set 1.

    MUST use the fully-merged axis (resolved_axis_style) rather than reading
    charts_style.axis_x directly. ``x_label_authored`` (the caller's own
    ``bool(chart.x_label)`` — truthy, so a blank label reserves no title
    space, matching what the cascade forces) is required, not defaulted, so a caller
    that forgets to thread it fails loudly rather than silently reserving no
    title space. It drives the same Layer-5 label-forcing
    default ``resolved_axis_style`` applies for the emitted VL spec; reading
    the base axis_x (Layers 1+2) misses it, under-reserving title space and
    causing the strip to collide with the rendered axis title.
    """
    # Font metrics come from the base ResolvedAxisStyle (non-None guaranteed).
    # Visibility is read from the fully-merged cascade (includes the Layer-5
    # label-forcing default and every chart-local override) so both label and
    # title heights reflect the actual rendered state.
    merged = resolved_axis_style(
        chart_style_context,
        "axis_x",
        "band",
        chart_type=chart_type,
        label_authored=x_label_authored,
    )
    # labels.padding is always required by build_resolved_axis (the shared
    # ResolvedAxisElementStyle dataclass types it Optional only to let title
    # leave it unset — see AxisTitleStyle).
    assert merged.labels.padding is not None, "axis_x.labels.padding unset"
    label_h = (
        merged.labels.padding + merged.labels.font.size * style.label_max_lines
        if merged.labels.visible is not False and merged.labels.font.size > 0
        else 0.0
    )
    assert merged.title.padding is not None, "axis_x.title.padding unset"
    title_h = (
        merged.title.padding + merged.title.font.size
        if merged.title.visible is not False and merged.title.font.size > 0
        else 0.0
    )
    return label_h + title_h


def resolve_effective_data_table_style(
    chart_style_context: ChartStyleContext, chart_type: str
) -> DataTableStyle:
    """Resolve the effective data_table style for a chart.

    charts_style.data_table carries the global theme value merged with any
    chart-local board override.  apply_inherit pre-fills per-family data_table
    fields from charts.data_table, so this function only needs to apply the
    per-family theme values (tier-2) on top.
    """
    per_type = getattr(chart_style_context, chart_type, None)
    if per_type is None or not hasattr(per_type, "data_table"):
        return chart_style_context.data_table
    return merge_onto_base(chart_style_context.data_table, per_type.data_table)


def apply_measure_format_to_data_table(
    data_table: ChartDataTable, measure_format: str | FormatConfig, y_field: str
) -> ChartDataTable:
    """Inherit measure_format into data_table entries reading y_field with no authored format.

    Shared by normalize_chart()'s _build_cartesian() — both need to
    push the chart's resolved measure format into data_table entries that don't
    author their own. InheritSlot cannot do this: that mechanism is specific to
    the Style model tree, and the condition "only entries reading y_field
    inherit" is a cross-field identity check (entry.source == y_field), not a
    structural position.
    """
    resolved_entries = []
    for entry in data_table.entries:
        source_field = (
            entry.per_series
            if isinstance(entry, ChartDataTablePerSeries)
            else entry.source
        )
        if entry.format is None and source_field == y_field:
            entry = entry.model_copy(update={"format": measure_format})
        resolved_entries.append(entry)
    return data_table.model_copy(update={"entries": resolved_entries})
