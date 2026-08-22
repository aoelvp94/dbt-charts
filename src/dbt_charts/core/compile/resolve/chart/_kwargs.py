"""Shared kwargs assembly for chart resolvers: text templating, width, and the family style-slot map."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal

from dbt_charts.core.compile.merge import merge_onto_base, to_padding_style
from dbt_charts.core.compile.models.chart.authored import ChartDataTable
from dbt_charts.core.compile.models.chart.normalized import (
    Chart,
    KpiChart,
)
from dbt_charts.core.compile.models.chart.normalized._base import (
    _BaseChartFields,
    _CartesianChartFields,
    _GeoChartFields,
    _SharedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved import PartitionAxis
from dbt_charts.core.compile.models.primitives import ResolvedFontStyle
from dbt_charts.core.compile.models.style.authored import (
    LegendStylePatch,
    PaddingStylePatch,
)
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedChartDefaults
from dbt_charts.core.compile.models.style.theme import (
    DataTableStyle,
    LegendStyle,
    PaddingStyle,
)
from dbt_charts.core.compile.resolve.style.palette import substitute_for_alias
from dbt_charts.core.compile.resolve.style.typography import resolve_title_font
from dbt_charts.core.compile.template.jinja import resolve_jinja_template
from dbt_charts.core.text.predefined_formats import (
    PredefinedNumberFormat,
)

__all__ = [
    "AutomaticLinkCandidate",
    "ChartTextVariables",
    "_EMPTY_CHART_TEXT_VARIABLES",
    "_FAMILY_SLOT",
    "_base_kwargs",
    "_cartesian_kwargs",
    "_geo_kwargs",
    "_resolve_text",
    "_shared_kwargs",
    "_title_font",
    "default_chart_width",
    "preferred_chart_width",
    "resolve_chart_display_title",
]


AutomaticLinkCandidate = str | None


def _base_kwargs(
    normalized: _BaseChartFields,
    chart_style_context: ChartStyleContext,
    channels: dict[str, Any],
    legend_patch: LegendStyle | None = None,
    palette: list[str] | None = None,
    *,
    requested_alias_palette: str | None,
    automatic_link_candidate: AutomaticLinkCandidate,
    layout_padding: PaddingStyle | PaddingStylePatch,
    suppress_legend: bool = False,
    top_legend: Literal["compact", "row", "off"] = "off",
) -> dict[str, Any]:
    """Common kwargs for all _BaseResolvedChartFields subclasses.

    Projects palette and legend from the baked cascade into the typed
    shared-envelope fields on _BaseResolvedChartFields. The fat
    ChartStyleContext bag is NOT passed through — only palette, channels,
    and the pre-merged legend are projected.

    legend: caller passes merge_onto_base(chart_style_context.legend, family.legend)
    where family is already the result of merge_onto_base(chart_style_context.<type>, primary).
    The merge layer handles family→chart-local legend cascade declaratively;
    _base_kwargs receives the final resolved value.
    palette: when a chart-local palette override is in effect, pass it here;
    otherwise falls back to chart_style_context.palette.
    requested_alias_palette: pass _effective_requested_alias_palette(chart_style_context,
    primary) — required, no fallback, so a forgotten call site is a type error
    rather than a silently-lost WARN-PALETTE-UNSUPPORTED detector signal.
    layout_padding: pass the caller's already-merged per-family padding (e.g.
    ``bar.padding``) — the same object build_chart_style_context/merge_onto_base
    produced for the rest of that family's style slice.
    suppress_legend: True when endpoint labels replace the colour legend. Folds
    visible=False into the legend patch BEFORE the cascade merge so the resolved
    legend is built once with its final visibility — no post-hoc model_copy.
    top_legend: force the legend above the plot, reading left to right like the
    marks it names. "compact" wraps at compact_columns for cards too narrow to
    hold a row; "row" leaves the entry count to the renderer.
    """
    legend = merge_onto_base(chart_style_context.legend, legend_patch)
    if top_legend != "off":
        top = LegendStylePatch.model_validate(
            {
                "visible": True,
                "position": "top",
                "direction": "horizontal",
                "columns": legend.compact_columns if top_legend == "compact" else 0,
            }
        )
        legend = merge_onto_base(legend, top)
    if suppress_legend:
        hidden = LegendStylePatch.model_validate({"visible": False})
        legend = merge_onto_base(legend, hidden)
    if (
        legend.position == "top"
        and legend.direction == "horizontal"
        and legend.title.visible is None
    ):
        no_title = LegendStylePatch.model_validate({"title": {"visible": False}})
        legend = merge_onto_base(legend, no_title)
    link = normalized.link
    if link is None:
        link = automatic_link_candidate
    return {
        "id": normalized.id,
        "source_path": normalized.source_path,
        "defined_in_other_file": normalized.defined_in_other_file,
        "query": normalized.query,
        "query_name": normalized.query_name,
        "variable_dependencies": normalized.variable_dependencies,
        "description": normalized.description,
        "link": link,
        "conditional_formatting": normalized.conditional_formatting,
        "palette": tuple(
            palette if palette is not None else chart_style_context.palette
        ),
        "requested_alias_palette": requested_alias_palette,
        "requested_alias_substitute": (
            substitute_for_alias(requested_alias_palette)
            if requested_alias_palette is not None
            else None
        ),
        "resolved_channels": channels,
        "legend": legend,
        "layout_padding": to_padding_style(layout_padding),
    }


ChartTextVariables = Mapping[str, Any]
_EMPTY_CHART_TEXT_VARIABLES: ChartTextVariables = MappingProxyType({})


def _resolve_text(value: str, variables: ChartTextVariables) -> str:
    if not variables:
        return value
    return resolve_jinja_template(value, variables, strict=False)


def resolve_chart_display_title(
    normalized: Chart, variables: ChartTextVariables, strict: bool = True
) -> str:
    """Resolve the one title-like field used by normalized terminal charts."""
    value = normalized.label if isinstance(normalized, KpiChart) else normalized.title
    return resolve_jinja_template(value, variables, strict=strict) if value else ""


def _title_font(
    normalized: Chart, chart_local_style_context: ChartStyleContext, width: float
) -> ResolvedFontStyle:
    """Resolve the chart's title font, honoring a chart-local style.title.font override.

    Must receive the chart-local context (``build_chart_style_context``'s
    result), not the board-level one: ``resolve_title_font`` only threads the
    ``family``/``size``/``weight`` triple through its explicit override
    argument — ``color``/``style``/``decoration``/``case``/``line_height``
    are read straight off ``chart_style_context.title.font``, which only
    carries this chart's ``style.title.font`` override once
    ``build_chart_style_context`` has merged it in.
    """
    _s = normalized.style
    _st = getattr(_s, "title", None) if _s is not None else None
    return resolve_title_font(
        chart_local_style_context, width, _st.font if _st is not None else None
    )


def _shared_kwargs(
    normalized: _SharedChartFields,
    variables: ChartTextVariables,
    chart_style_context: ChartStyleContext,
) -> dict[str, Any]:
    """Extra kwargs for _SharedResolvedChartFields subclasses.

    chart_style_context is the chart's own merged style (build_chart_style_context output) —
    background and title overflow are chart-local decisions, so they must
    read the chart-local merge, not the board-level bag.

    ``title``/``subtitle`` are jinja-resolved only, never case-transformed:
    ``chart.title`` also backs non-VL consumers (e.g. the ``data-chart-title``
    wire attribute in rendering.py) that have always emitted the raw authored
    text. Title-case is a VL-presentation-only concern, applied at the VL
    assembly boundary from ``chart.title_style.font.case`` (see
    ``render/chart/translate.py``), not baked in here.
    """
    return {
        "title": _resolve_text(normalized.title, variables),
        "subtitle": _resolve_text(normalized.subtitle, variables),
        "background": chart_style_context.background,
        "title_style": chart_style_context.title,
    }


# Family-style slot on ChartStyleContext per normalized chart type; type
# aliases (donut, map, bubble_map) share their family's slot. layered is absent
# on purpose — it sizes from the board-level charts default.
_FAMILY_SLOT: dict[str, str] = {
    "bar": "bar",
    "histogram": "histogram",
    "line": "line",
    "area": "area",
    "scatter": "scatter",
    "heatmap": "heatmap",
    "pie": "pie",
    "donut": "pie",
    "kpi": "kpi",
    "table": "table",
    "geoshape": "geoshape",
    "map": "geoshape",
    "point_map": "point_map",
    "bubble_map": "point_map",
    "spark_bar": "spark_bar",
    "callout": "callout",
}


def preferred_chart_width(
    normalized: Chart, chart_style_context: ChartStyleContext
) -> float:
    """The preferred width resolve() bakes into ResolvedChart, from config alone.

    Authored chart ``width`` wins; otherwise the chart-local style patch merged
    onto the theme family style supplies ``preferred_width``. Needs no data and
    no full resolution, so the intrinsic-width measurement in
    ``render/sizing.py`` can call it before any chart is resolved.
    """
    authored = normalized.__dict__.get("width")  # cartesian/pie/geo only
    if authored is not None:
        return float(authored)
    family_base = getattr(chart_style_context, _FAMILY_SLOT[normalized.type])
    family = merge_onto_base(family_base, normalized.style)
    return float(family.preferred_width)


def default_chart_width(
    chart_type: str, chart_defaults: ResolvedChartDefaults
) -> float:
    """Board-wide default width for a resolved chart's family, no chart-local patch.

    For render fallback paths that only have a ``ResolvedChart`` in scope —
    no normalized ``Chart``, so no chart-local style patch to merge
    (``render_resolved_chart()``'s public entry point). Callers holding a
    normalized ``Chart`` use ``preferred_chart_width()`` against
    ``ChartStyleContext`` instead, since that also merges any chart-local
    override.
    """
    family_base = getattr(chart_defaults, _FAMILY_SLOT[chart_type])
    return float(family_base.preferred_width)


def _column_is_numeric(data: list[dict[str, Any]], field: str) -> bool:
    """True when the column has values and every non-null one is a real number.

    Gates the compact number-format inheritance below: a string ``y`` column
    (category labels) must NOT get a d3 numeric format grafted on —
    ``format(datum, '.3~s')`` on a string yields NaN and the cell renders
    ``-`` instead of the label. Bools (an ``int`` subclass) are treated as
    non-numeric labels.

    Deliberately stricter than compile's own ``classify_column_type`` — it
    also rejects numeric strings and ``Decimal``, so a value d3 ``format()``
    would choke on renders as its raw label rather than a broken ``-``.
    """
    seen = False
    for row in data:
        raw = row.get(field)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return False
        seen = True
    return seen


def _resolved_data_table(
    data_table: ChartDataTable | None,
    y: str | list[str] | None,
    data: list[dict[str, Any]],
) -> ChartDataTable | None:
    """Bake the final data_table: stamp the theme's default number format
    onto entries reading a single *numeric* string y column that carry no
    authored format.

    Single final value — every cartesian family resolver already receives
    the same query rows render sees, so the "is y actually numeric" gate
    (a string y column must keep format=None so the raw label renders
    rather than a formatted "-") is decidable here instead of at render.
    """
    if data_table is None or not isinstance(y, str) or not _column_is_numeric(data, y):
        return data_table
    # Use the predefined name, not the resolved spec, so downstream callers
    # (apply_measure_format_to_data_table) preserve the house-notation signal.
    number_default = str(PredefinedNumberFormat.number_default)
    # Deferred like the one in _data_table_geometry below: data_table.py imports
    # resolve.style.axis_cascade, so a module-level import here closes a
    # data_table ↔ resolve cycle that only stays quiet while some other module
    # happens to import resolve first.
    from dbt_charts.core.compile.data_table import (  # noqa: PLC0415
        apply_measure_format_to_data_table,
    )

    return apply_measure_format_to_data_table(data_table, number_default, y)


def _data_table_geometry(
    data_table: ChartDataTable | None,
    chart_style_context: ChartStyleContext,
    chart_type: str,
    x_label_authored: bool,
) -> tuple[DataTableStyle | None, float | None]:
    """Bake the data_table strip's compile-owned geometry: the chart's
    effective DataTableStyle and the axis-offset pixel gap the strip
    reserves below the plot.

    Both are pure functions of the per-chart-cascaded ``chart_style_context``
    plus ``x_label_authored`` (the caller's own ``bool(normalized.x_label)``,
    truthy not ``is not None``, driving the axis cascade's Layer-5
    title-forcing default) —
    the same values ``render/chart/data_table_attachment.py`` used to
    recompute at render time by reaching into ``compile/data_table.py`` with
    a full ``ChartStyleContext``. Baking them here closes that reach-back:
    render reads ``resolved.effective_data_table_style``/
    ``.data_table_axis_offset`` directly, never the cascade context.
    """
    if data_table is None:
        return None, None
    from dbt_charts.core.compile.data_table import (  # noqa: PLC0415
        axis_offset,
        resolve_effective_data_table_style,
    )

    effective_style = resolve_effective_data_table_style(
        chart_style_context, chart_type
    )
    return effective_style, axis_offset(
        chart_style_context,
        effective_style,
        x_label_authored=x_label_authored,
        chart_type=chart_type,
    )


def _cartesian_kwargs(
    normalized: _CartesianChartFields,
    chart_style_context: ChartStyleContext,
    variables: ChartTextVariables,
    data: list[dict[str, Any]],
    chart_type: str,
    panel_axes: tuple[PartitionAxis, ...],
) -> dict[str, Any]:
    """Extra kwargs for _CartesianResolvedChartFields subclasses.

    ``chart_type`` is the resolved chart's own ``chart_type`` literal (e.g. "bar",
    "histogram") — not read off ``normalized.type``, which the shared
    ``_CartesianChartFields`` base does not declare (each family subclass declares
    its own ``type`` literal). ``panel_axes`` is the small-multiples partition
    baked once by ``partition()`` at the top of the caller's resolver — every
    cartesian family bakes it here so the field can never be forgotten on a
    new resolver.
    """
    resolved_data_table = _resolved_data_table(
        normalized.data_table, normalized.y, data
    )
    effective_data_table_style, data_table_axis_offset = _data_table_geometry(
        resolved_data_table,
        chart_style_context,
        chart_type,
        bool(normalized.x_label),
    )
    return {
        **_shared_kwargs(normalized, variables, chart_style_context),
        "x": normalized.x,
        "y": normalized.y,
        "color": normalized.color,
        "x_label": normalized.x_label,
        "y_label": normalized.y_label,
        "sort": normalized.sort,
        "multiples": normalized.multiples,
        "panel_axes": panel_axes,
        "data_table": resolved_data_table,
        "effective_data_table_style": effective_data_table_style,
        "data_table_axis_offset": data_table_axis_offset,
        "aspect_ratio": normalized.aspect_ratio,
        "min_height": normalized.min_height,
        "max_height": normalized.max_height,
        "format": normalized.format,
    }


def _geo_kwargs(
    normalized: _GeoChartFields,
    chart_style_context: ChartStyleContext,
    variables: ChartTextVariables,
) -> dict[str, Any]:
    """Extra kwargs for _GeoResolvedChartFields subclasses (projection only)."""
    return {
        **_shared_kwargs(normalized, variables, chart_style_context),
        "projection": normalized.projection,
    }
