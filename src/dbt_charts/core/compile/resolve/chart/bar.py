"""Bar and histogram chart resolvers."""

from __future__ import annotations

from math import ceil
from typing import Literal

from dbt_charts.core.compile.config import get_chart_rendering
from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.format import resolve_label_format
from dbt_charts.core.compile.merge import merge_onto_base
from dbt_charts.core.compile.models.chart.authored._data_table import (
    ChartDataTablePerSeries,
)
from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
)
from dbt_charts.core.compile.models.chart.resolved import (
    ResolvedBarChart,
)
from dbt_charts.core.compile.models.style.authored import EndpointLabelsConfig
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedBarStyle
from dbt_charts.core.compile.models.style.theme import (
    BarChartStyle,
    BarLabelsStyle,
)
from dbt_charts.core.compile.resolve.chart._axes import (
    _author_asked_for_endpoint_labels,
    _author_hid_legend,
    _bake_ay_orient,
    _bake_ay_position_left,
    _edge_or_none,
    _endpoint_labels_off_for_layers,
    _endpoint_labels_off_for_multiples,
    _reject_dual_axis_layered_endpoint_labels,
    cartesian_series_naming,
)
from dbt_charts.core.compile.resolve.chart._channels import (
    _bar_orientation,
    _classify_to_channel_type,
)
from dbt_charts.core.compile.resolve.chart._chart_rows import (
    ChartDataset,
    ChartRows,
    LayerDatasets,
    fold_panels,
    restamp,
)
from dbt_charts.core.compile.resolve.chart._domain import (
    _authored_axis_y_ticks_count,
    _axis_headroom,
    _bake_normalize_domain,
    _CartesianTickResolution,
    _first_non_numeric_y,
    _numeric_y_values,
    _resolve_cartesian_ticks,
    _resolve_stacked_bar_ticks,
    _shared_y_values,
)
from dbt_charts.core.compile.resolve.chart._kwargs import (
    AutomaticLinkCandidate,
    ChartTextVariables,
    _base_kwargs,
    _cartesian_kwargs,
    _title_font,
)
from dbt_charts.core.compile.resolve.chart._layers import (
    _check_layers_y_domain,
    _resolve_layer_list,
)
from dbt_charts.core.compile.resolve.chart._marks import (
    _label_format_fallback,
    _measure_tooltip_format,
)
from dbt_charts.core.compile.resolve.chart._palette import (
    _effective_palette,
    _effective_requested_alias_palette,
    _effective_single_series_fill,
    _resolved_series_label,
)
from dbt_charts.core.compile.resolve.chart._plan import (
    build_cartesian_axes,
    plan_cartesian,
)
from dbt_charts.core.compile.resolve.chart._wide_fields import (
    bake_wide_measures_kwargs,
    resolve_wide_measure_channels,
)
from dbt_charts.core.compile.resolve.chart.tick_values import (
    apply_headroom,
    stacked_totals_max,
)
from dbt_charts.core.compile.resolve.style.chart_context import (
    build_chart_style_context,
)
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_BAR_LOG_SCALE_NOT_SUPPORTED,
    ERR_BAR_Y_NOT_NUMERIC,
)
from dbt_charts.core.numeric import aspect_ratio_height
from dbt_charts.core.text.format_d3 import is_d3_si_spec
from dbt_charts.core.utils import (
    layered_endpoint_rail_fires,
    layered_endpoint_rail_shape,
    numeric_column_values,
    stacked_x_domain_order,
)

__all__ = [
    "_resolve_bar",
    "_resolve_histogram",
]


def _bar_endpoint_labels_for_stack(
    endpoint_labels: EndpointLabelsConfig,
    normalized: BarChart,
    data: ChartRows,
    stack_mode: str,
    horizontal: bool,
    author_opted_in: bool,
) -> EndpointLabelsConfig:
    """Direct labelling is the default; the disqualifiers below turn it back off.

    Every disqualifier here steers the *default* away from a shape it would
    render badly or not at all. An author who wrote
    ``style.endpoint_labels.visible: true`` on this chart has said they want
    the rail on that shape, so ``author_opted_in`` returns the cascaded value
    untouched: grouped bars label at their bar tops as they always have, and
    the shapes render refuses (a negative measure, a sorted or centre-stacked
    horizontal rail, ``multiples:``) raise there with a message naming the
    conflict. Quietly dropping the rail instead would be neither.
    """
    if author_opted_in:
        return endpoint_labels
    if normalized.data_table is not None and any(
        isinstance(entry, ChartDataTablePerSeries) and not entry.by_measure
        for entry in normalized.data_table.entries
    ):
        # A per-series data table already prints one row per series, labelled
        # in that series' own ink — the rail would name them a second time,
        # and it costs the plot the height and the axis side it needs.
        return endpoint_labels.model_copy(update={"visible": False})
    if stack_mode == "none":
        # Grouped: every series' last bar rises from the same baseline to a
        # similar height, so the collision cascade squashes the labels
        # together. A legend is the honest treatment.
        return endpoint_labels.model_copy(update={"visible": False})
    endpoint_labels = _endpoint_labels_off_for_multiples(
        endpoint_labels, normalized, author_opted_in
    )
    if not endpoint_labels.visible:
        return endpoint_labels
    y_fields = (
        (normalized.y,)
        if isinstance(normalized.y, str)
        else tuple(normalized.y)
        if isinstance(normalized.y, list)
        else ()
    )
    # A negative (zero-crossing) measure breaks the cumulative-midpoint
    # computation; the render layer raises rather than mislabel. Stack mode
    # zero/normalize/center all reach that raise, so this check runs
    # regardless of which one resolved_stack picked.
    if any(v < 0 for v in _numeric_y_values(data, y_fields)):
        return endpoint_labels.model_copy(update={"visible": False})
    # author_opted_in is False by construction here — the opt-in returned above.
    endpoint_labels = _endpoint_labels_off_for_layers(
        endpoint_labels, normalized, author_opted_in
    )
    if not endpoint_labels.visible:
        return endpoint_labels
    if normalized.sort is not None and not numeric_column_values(
        data, normalized.sort.by
    ):
        # Both rails reproduce Vega-Lite's domain order by totalling the sort
        # column per category. On a non-numeric column VL concatenates the
        # strings instead, an order this cannot mirror — so the rail would
        # anchor on a row VL does not draw on top.
        return endpoint_labels.model_copy(update={"visible": False})
    if horizontal and stack_mode == "center":
        # The horizontal rail anchors on the cumulative (0..Σ) axis, which the
        # diverging center-stack domain doesn't have.
        return endpoint_labels.model_copy(update={"visible": False})
    if not _any_column_stacks_more_than_one_series(normalized, data, y_fields):
        return endpoint_labels.model_copy(update={"visible": False})
    if horizontal and not _every_series_reaches_the_anchor_row(
        normalized, data, y_fields
    ):
        return endpoint_labels.model_copy(update={"visible": False})
    return endpoint_labels


def _every_series_reaches_the_anchor_row(
    normalized: BarChart,
    data: ChartRows,
    y_fields: tuple[str, ...],
) -> bool:
    """True when the horizontal rail's anchor row carries a segment for every series.

    The vertical rail can seat a series that is absent from its anchor column on
    the zero-height seam between its neighbours, because the label cascade then
    pushes it clear. The horizontal rail has no such resolver in V2 — its
    ``__dodge_row`` tiers are unimplemented (see the skipped collision tests in
    ``test_horizontal_bar_endpoint_labels.py``) — so a zero-width seam lands
    hard against the neighbouring segment's label and the two overprint.

    Steering the default back to a legend is the honest treatment until the
    dodge resolver lands; delete this the day it does. An explicit
    ``endpoint_labels.visible: true`` still reaches the seam math, which is
    correct and tested — it is only unsafe to *choose* unprompted.
    """
    color = normalized.color
    x = normalized.x
    if not isinstance(color, str) or not isinstance(x, str):
        return True
    sort = normalized.sort
    domain = stacked_x_domain_order(
        data, x, sort.by if sort else "", bool(sort and sort.order == "desc")
    )
    if not domain:
        return True
    anchor_row = domain[0]
    every_series: set[str] = set()
    drawn_at_anchor: set[str] = set()
    for row in data:
        series = row.get(color)
        if series is None:
            continue
        every_series.add(str(series))
        if row.get(x) == anchor_row and any(
            row.get(field) is not None for field in y_fields
        ):
            drawn_at_anchor.add(str(series))
    return drawn_at_anchor == every_series


def _any_column_stacks_more_than_one_series(
    normalized: BarChart,
    data: ChartRows,
    y_fields: tuple[str, ...],
) -> bool:
    """True when at least one column carries segments from two or more series.

    The rail names the segments *within* a stack. When ``color:`` merely
    re-labels ``x:`` — one series per column, the shape a category-coloured bar
    takes — nothing stacks, so there are no segments to name and the rail
    degenerates into a badly-laid-out legend. Hand those back to a legend.

    A series missing from the anchor column does NOT disqualify the rail: it
    anchors on its zero-height stack seam instead (see ``_stacked_midpoints``
    in render/chart/features/endpoint_labels.py), so every series stays named.

    Drawing nothing at all — a single series, or an all-null measure — answers
    this question on its own terms: no column stacks, so the count comparison
    below is False without a special case.
    """
    color = normalized.color
    x = normalized.x
    if not isinstance(color, str) or not isinstance(x, str):
        return True
    drawn: set[tuple[str, str]] = set()
    for row in data:
        series = row.get(color)
        if series is None or not any(row.get(field) is not None for field in y_fields):
            continue
        drawn.add((str(row.get(x)), str(series)))
    columns = {column for column, _ in drawn}
    return len(drawn) > len(columns)


def _estimate_bar_plot_height(
    normalized: BarChart, bar: BarChartStyle, width: float
) -> float:
    """Aspect-ratio-driven card height, needing no query data.

    Shares its clamp arithmetic with render/sizing.py's ``get_chart_content_height``
    via ``numeric.aspect_ratio_height`` — the two differ only in which min/max
    height they clamp to (this resolve step's per-family
    ``chart_local_style_context.bar``, already cascade-resolved with any
    chart-root override, vs. render's board-global ``resolved_style.chart_defaults``),
    a cascade-position difference each caller's own inputs express.
    """
    if normalized.height is not None:
        return float(normalized.height)
    aspect = (
        normalized.aspect_ratio
        if normalized.aspect_ratio is not None
        else bar.aspect_ratio
    )
    if width <= 0 or aspect <= 0:
        return bar.min_height
    min_h = (
        normalized.min_height if normalized.min_height is not None else bar.min_height
    )
    max_h = (
        normalized.max_height if normalized.max_height is not None else bar.max_height
    )
    return aspect_ratio_height(width, aspect, min_h, max_h)


def _distinct_series_count(dataset: ChartDataset, color: str) -> int:
    """Distinct non-null-value count for the legend's color field.

    ``column_values`` reads a partition field straight off the baked axis
    (no row scan needed) and falls back to scanning rows for a non-partition
    field — column-wise/union, correct whether the chart is faceted or not.
    The ``is not None`` filter applies on both paths: ``partition()`` bakes a
    real SQL NULL as its own legitimate panel value (a ``(None,)`` key), so a
    color field that is itself the partition field can surface ``None``
    through the axis path too, same as an ordinary row scan would.
    """
    return len([v for v in dataset.column_values(color) if v is not None])


def _stack_legend_should_yield(
    resolved_stack: str,
    orientation: Literal["vertical", "horizontal"] | None,
    distinct_series: int,
    symbol_limit: int | None,
    plot_height: float,
    legend_is_top: bool,
    legend_columns: int,
) -> bool:
    """True when a stacked bar's legend would squeeze its own segments to zero height.

    Vega-Lite's ``autosize:fit`` divides a card's total height between the
    legend and the plot; past some entry count the legend's demand leaves the
    plot nothing to draw into (ERR-CHART-PAINTED-NO-MARKS). The marks always
    win that contest. Scoped narrowly to the one shape that actually collapses
    this way: a genuine stack (``stack: none`` subdivides width, not height,
    and never hits this collapse), rendered vertically (a horizontal stack's
    plot height is governed by its category count, not its series count — it
    never collapses this way), whose legend has actually moved to a top,
    multi-column layout (``legend_is_top``; a side legend costs width, not
    plot height, and never competes with the plot for it). The row math
    divides entries across ``legend_columns`` — the renderer never lays out
    one row per entry once the legend goes top/compact.
    """
    if (
        resolved_stack == "none"
        or distinct_series == 0
        or orientation == "horizontal"
        or not legend_is_top
    ):
        return False
    entries = min(distinct_series, symbol_limit) if symbol_limit else distinct_series
    rows = ceil(entries / legend_columns)
    bar_cfg = get_chart_rendering().bar
    required = (
        rows * bar_cfg.stack_legend_row_height_px
        + bar_cfg.stack_legend_chrome_height_px
    )
    return required > plot_height


def _resolve_bar(
    normalized: BarChart,
    dataset: ChartDataset,
    chart_style_context: ChartStyleContext,
    width: float,
    datasets: LayerDatasets,
    automatic_link_candidate: AutomaticLinkCandidate,
    variables: ChartTextVariables,
) -> ResolvedBarChart:
    data = dataset.all_rows()
    multiples_scale = (
        normalized.multiples.scale if normalized.multiples is not None else "shared"
    )
    x_ch_type = _classify_to_channel_type(normalized.x, data, is_dimension=True)
    # Bar semantics fix x=category, y=measure regardless of orientation (see
    # the _bake_cartesian_axes docstring above) — the axis cascade hardcodes y
    # to "quantitative" and downstream stack-totals math assumes numeric y. A
    # categorical y silently bakes a NaN axis with zero marks; refuse instead.
    _bar_bad_y = _first_non_numeric_y(normalized.y, data)
    if _bar_bad_y is not None:
        _bar_y_hint = None
        if x_ch_type == "quantitative":
            _bar_y_hint = (
                f"Column {normalized.x!r} looks numeric — did you mean to swap x and y?"
            )
        raise CompilationError.from_code(
            ERR_BAR_Y_NOT_NUMERIC,
            chart_id=normalized.id,
            y_field=_bar_bad_y,
            hint=_bar_y_hint,
        )
    chart_local_style_context = build_chart_style_context(
        chart_style_context, normalized
    )
    plan = plan_cartesian(
        normalized,
        data,
        chart_style_context,
        "bar",
        x_ch_type,
        "quantitative",
        normalized.multiples,
        normalized.y,
    )
    bar = chart_local_style_context.bar
    # Flat chart.stack overrides style.bar.stack; fall through to the merged bar
    # style (which already applied style.bar.stack → board theme cascade) so that
    # per-chart style overrides are respected even when chart.stack is None.
    resolved_stack = normalized.stack if normalized.stack is not None else bar.stack
    is_stacked = resolved_stack not in (None, "none")
    primary = plan.primary
    channels = plan.channels
    channels, wide_measure_series = resolve_wide_measure_channels(
        normalized, channels, "bar", has_layers=bool(normalized.layers)
    )
    ax_merged, ay_merged = plan.ax_merged, plan.ay_merged
    # Orientation depends on ax_merged.time_unit (a pure cascade fact, not
    # data-derived — see _bar_orientation), so it's computable right after
    # the merge, before the axes are built. Computed once, here, and reused
    # both for the categorical axis's edge below and the chart's own
    # resolved `orientation` field at the bottom of this function.
    orientation = _bar_orientation(normalized, data, ax_merged.time_unit is not None)
    # The layered-single-series rail (EndpointLabelFeature._apply_layered_single_series)
    # only ever fires on the vertical right_pane path — a horizontal bar's rail is the
    # colour-series top_rail only (see applies_to()'s horizontal branch, which never
    # reaches the layered fallback), so a horizontal layered bar with no colour must
    # not claim the rail here either, or its legend gets suppressed with nothing to
    # replace it.
    endpoint_label_has_layers = (
        orientation != "horizontal"
        and layered_endpoint_rail_fires(
            layered_endpoint_rail_shape(normalized.x, normalized.y),
            [layer.color is None for layer in normalized.layers],
        )
    )
    # A horizontal bar's colour-series rail (EndpointLabelFeature.applies_to()'s
    # horizontal branch) only ever fires on a genuinely stacked chart — a
    # grouped (stack: none) horizontal bar never gets a rail even with a
    # colour series and endpoint_labels.visible explicitly authored, so
    # letting suppression fire off the colour-series term there would retire
    # the legend with nothing to replace it.
    _horizontal_is_grouped = orientation == "horizontal" and resolved_stack in (
        None,
        "none",
    )
    _horizontal_series_rail_fires = not _horizontal_is_grouped
    # Resolved after orientation: the disqualifier chain below is specific to
    # the horizontal rail.
    naming = cartesian_series_naming(
        normalized,
        channels,
        _author_hid_legend(primary),
        width,
        _bar_endpoint_labels_for_stack(
            bar.endpoint_labels,
            normalized,
            data,
            resolved_stack,
            orientation == "horizontal",
            _author_asked_for_endpoint_labels(normalized.style),
        ),
        endpoint_label_has_layers=endpoint_label_has_layers,
        has_layers=bool(normalized.layers),
        rail_eligible_for_suppression=_horizontal_series_rail_fires,
        suppress_wide_measure_series=wide_measure_series,
        multiples_wide_measure_series=wide_measure_series,
        layers_route_to_top_legend=False,
        unconditional_top_legend=not is_stacked,
    )
    endpoint_labels = naming.endpoint_labels
    _reject_dual_axis_layered_endpoint_labels(
        normalized.id,
        normalized.layers,
        endpoint_labels.visible and endpoint_label_has_layers,
    )
    if orientation == "horizontal":
        # For horizontal bar, ay (the semantic measure axis) maps to VL x,
        # which has no left/right orient — _emit_horizontal pops it entirely.
        # ay.position's only remaining role is supplying the swapped
        # categorical axis's (VL y) orient in emitters/bar.py. The deleted
        # categorical_orient field always defaulted "left" there, statically —
        # the horizontal rail sits above the plot (top-row), never left/right,
        # so it never competes for this axis's side the way the vertical
        # endpoint-label rail does. Preserve the static default via
        # _bake_ay_position_left rather than _bake_ay_orient's
        # endpoint-label-aware auto-resolution.
        ay_merged = _bake_ay_position_left(ay_merged)
    else:
        ay_merged = _bake_ay_orient(
            ay_merged,
            channels,
            endpoint_labels.visible,
            wide_measure_series=wide_measure_series,
            has_layers=endpoint_label_has_layers,
        )
    # Bar's categorical axis (axis_x) only has a left/right edge when the
    # chart is horizontal — it then renders on VL's y channel at ay.position
    # (see emitters/bar.py's own-orient swap; categorical_orient was deleted
    # 2026-08 — position now serves this role too). A vertical bar's x stays
    # bottom-orient — no edge.
    x_edge = _edge_or_none(ay_merged.position) if orientation == "horizontal" else None
    _ay_cont_log = ay_merged.scale.continuous if ay_merged.scale is not None else None
    if _ay_cont_log is not None and _ay_cont_log.type == "log":
        raise CompilationError.from_code(
            ERR_BAR_LOG_SCALE_NOT_SUPPORTED,
            chart_id=normalized.id,
        )
    _ay_cont_zero = ay_merged.scale.continuous if ay_merged.scale is not None else None
    ay_scale_zero = _ay_cont_zero.zero if _ay_cont_zero is not None else None
    # Non-stacked bars anchor at zero by default unless scale.zero is explicitly False.
    # Stacked bars only anchor when scale.zero is explicitly True.
    bar_zero = (not is_stacked and ay_scale_zero is not False) or ay_scale_zero is True
    y_field = normalized.y if isinstance(normalized.y, str) else None
    y_fields = (
        [y_field]
        if y_field
        else list(normalized.y)
        if isinstance(normalized.y, list)
        else []
    )
    x_field = normalized.x if isinstance(normalized.x, str) else None
    bar_domain_max: float | None = None
    bar_domain_min: float | None = None
    authored_y_domain = _ay_cont_zero.domain if _ay_cont_zero is not None else None
    if resolved_stack == "normalize" or not y_fields:
        # normalize-stack domain is always [0,1]; no y_field means no ticks.
        tick_values: tuple[float, ...] = ()
        if resolved_stack == "normalize":
            ay_merged = _bake_normalize_domain(ay_merged)
    elif is_stacked and x_field:
        tick_values = _resolve_stacked_bar_ticks(
            ay_merged, dataset, y_fields, x_field, multiples_scale
        )
        # stacked domainMax baked separately below; domain_min stays None
    else:
        bar_y_values = (
            _shared_y_values(data, y_field, normalized, datasets)
            if y_field
            else _numeric_y_values(data, tuple(y_fields))
        )
        _bar_ticks = _resolve_cartesian_ticks(
            normalized.id,
            ay_merged,
            bar_y_values,
            zero_anchor=bar_zero,
            authored_ticks_count=_authored_axis_y_ticks_count(normalized.style),
            scale=multiples_scale,
        )
        tick_values = _bar_ticks.ticks
        bar_domain_max, bar_domain_min = _bar_ticks.domain_max, _bar_ticks.domain_min
    # Bake stacked_domain_max at resolve: emitter reads the pre-baked value.
    # Only set for regular zero-stacked bars; not normalize, not grouped, not single-series.
    # Headroom applies to the stacked TOTAL max, same as the plain data max.
    # Unlike the non-stacked path (which never emitted a domainMax before
    # headroom existed), stacked bars always pinned the exact stacked total —
    # VL's nice-rounding would otherwise add accidental top margin — so a
    # headroom of 0 keeps the flush-exact-total pin rather than dropping it.
    # A non-positive total (all-negative stacks) is skipped: domainMax 0 on a
    # zero-anchored scale is a degenerate [0, 0] domain; VL auto-fits instead.
    stacked_domain_max: float | None = None
    if is_stacked and resolved_stack != "normalize" and y_fields and x_field:
        # x_field can itself be the multiples field — partition() strips a
        # panel's own partition column from its rows, so restamp it back
        # before grouping, or every row's x_field reads as absent and the
        # stacked total silently folds to None (nothing to sum).
        _raw_stacked_max = fold_panels(
            restamp(dataset, x_field),
            multiples_scale,
            lambda rows: stacked_totals_max(rows, x_field, y_fields),
        )
        if _raw_stacked_max is not None and _raw_stacked_max > 0:
            stacked_domain_max = apply_headroom(
                _raw_stacked_max, _axis_headroom(ay_merged)
            )
    # A horizontal bar's measure axis (this "ay") renders on VL's x channel
    # and forms no column — see build_resolved_axis's column_forming
    # docstring. Every other bar orientation keeps the default (vertical
    # ruler, column-forming).
    ay, style_tail = build_cartesian_axes(
        normalized.id,
        chart_style_context,
        ax_merged,
        ay_merged,
        ax_band_position=plan.ax_band_position,
        ay_band_position=plan.ay_band_position,
        ax_edge=x_edge,
        ay_format_authored=plan.ay_format_authored,
        ay_format_is_alias=plan.ay_format_is_alias,
        ticks=_CartesianTickResolution(tick_values, bar_domain_max, bar_domain_min),
        column_forming=orientation != "horizontal",
        measure_tooltip_format=_measure_tooltip_format(
            normalized, primary, chart_style_context
        ),
        ay_is_quantitative=orientation != "horizontal",
    )
    axis_is_house = (
        ay.labels.format is not None
        and is_d3_si_spec(ay.labels.format)
        and (not plan.ay_format_authored or plan.ay_format_is_alias)
    )
    _tf = _title_font(normalized, chart_local_style_context, width)
    # The legend the classifier judges must be the legend that actually
    # renders: chart_style_context.legend (board+chart-level style.legend)
    # merged with bar.legend (family-scoped style.bar.legend), the same merge
    # _base_kwargs performs internally. Computed once here for the
    # classifier's reads; _base_kwargs still takes the unmerged bar.legend
    # patch (as every other family resolver does) and repeats the same merge
    # internally.
    merged_legend = merge_onto_base(chart_style_context.legend, bar.legend)
    # A wide bar (`y: [m01..m25]`, no color:) folds its measures into a
    # colour channel at render (fold_wide_measures, emitters/_wide.py) and
    # gets one legend entry per measure — normalized.color stays None, so
    # the color-cardinality read below sees nothing. len(y_fields) is that
    # fold's entry count; a plain (non-list) y never folds and has no legend
    # to charge.
    legend_entry_count = (
        _distinct_series_count(dataset, normalized.color)
        if normalized.color is not None
        else len(y_fields)
        if isinstance(normalized.y, list)
        else 0
    )
    legend_is_top = naming.top_legend == "compact"
    bkw = _base_kwargs(
        normalized,
        chart_style_context,
        channels,
        bar.legend,
        _effective_palette(chart_style_context, primary),
        requested_alias_palette=_effective_requested_alias_palette(
            chart_style_context, primary
        ),
        automatic_link_candidate=automatic_link_candidate,
        layout_padding=bar.padding,
        suppress_legend=naming.suppress_legend
        or _stack_legend_should_yield(
            resolved_stack,
            orientation,
            legend_entry_count,
            merged_legend.symbol_limit,
            _estimate_bar_plot_height(normalized, bar, width),
            legend_is_top,
            merged_legend.compact_columns,
        ),
        top_legend=naming.top_legend,
    )
    resolved_layers = _resolve_layer_list(
        normalized.layers,
        chart_style_context,
        "bar",
        bar,
        normalized.query_name,
        0.0,
    )
    if authored_y_domain is not None:
        _check_layers_y_domain(normalized.id, resolved_layers, authored_y_domain)
    # Total label: fall back to axis format when none authored; use resolve_label_format
    # so both branches share the alias-gate register decision.
    raw_total = bar.marks.bar.total_label
    if raw_total.format is None and ay.labels.format is not None:
        resolved_total = raw_total.model_copy(update={"format": ay.labels.format})
        total_label_is_house = axis_is_house
    elif raw_total.format is not None:
        resolved_total_fmt, total_label_is_house = resolve_label_format(
            raw_total.format, chart_style_context.formats
        )
        resolved_total = raw_total.model_copy(update={"format": resolved_total_fmt})
    else:
        total_label_is_house = False
        resolved_total = raw_total
    resolved_labels, label_is_house = _label_format_fallback(
        bar.marks.bar.labels,
        ay.labels.format,
        axis_is_house,
        chart_style_context.formats,
    )
    bar_mark = bar.marks.bar.model_copy(
        update={"labels": resolved_labels, "total_label": resolved_total}
    )
    _ck = _cartesian_kwargs(
        normalized,
        chart_local_style_context,
        variables,
        data,
        "bar",
        panel_axes=dataset.axes,
    )
    _ck, wide_measures = bake_wide_measures_kwargs(normalized.y, _ck)
    return ResolvedBarChart(
        **bkw,
        **_ck,
        wide_measures=wide_measures,
        chart_type="bar",
        stack=resolved_stack,
        stacked_domain_max=stacked_domain_max,
        orientation=orientation,
        style=ResolvedBarStyle(
            series_label=_resolved_series_label(chart_style_context, primary, width),
            stack_order=bar.stack_order,
            mark=bar_mark,
            overlap=bar.overlap,
            single_series_fill=_effective_single_series_fill(
                chart_style_context,
                primary,
                rhythm_slot=normalized.rhythm_slot,
                has_layers=bool(normalized.layers),
            ),
            endpoint_labels=endpoint_labels,
            label_usable_ratio=chart_style_context.label_usable_ratio,
            title_font=_tf,
            label_is_house=label_is_house,
            label_font_size=_effective_label_font_size(
                bar_mark.labels, chart_style_context
            ),
            total_label_is_house=total_label_is_house,
            **style_tail,
        ),
        layers=resolved_layers,
    )


def _effective_label_font_size(
    labels: BarLabelsStyle, chart_style_context: ChartStyleContext
) -> float:
    """Font size the value-label text will actually paint at, in px.

    An unset ``labels.font.size`` is not a gap — the text mark falls through to
    the board's VL text config (``compile/vega_lite/mapping.py``), so that is
    the honest second source. Required post-cascade, like series_label's font
    fields in ``_palette.py``: every theme resolves the text-mark size, and the
    inherit cascade refills an explicitly nulled one, so a None here is a
    broken cascade to name rather than a state for render to tiptoe around.
    """
    if labels.font is not None and labels.font.size is not None:
        return labels.font.size
    size = chart_style_context.marks.text.font.size
    if size is None:
        raise ValueError("marks.text.font.size must be non-None after cascade")
    return size


def _resolve_histogram(
    normalized: BarChart,
    dataset: ChartDataset,
    chart_style_context: ChartStyleContext,
    width: float,
    automatic_link_candidate: AutomaticLinkCandidate,
    variables: ChartTextVariables,
) -> ResolvedBarChart:
    """Resolve a histogram chart through the histogram theme (not bar theme).

    Histogram uses plain bin:True (VL computes extents); resolve bakes mark +
    axes from chart_style_context.histogram.* so histogram.axis_y.title.visible and
    histogram.marks.bar.border apply correctly.
    """
    data = dataset.all_rows()
    x_ch_type = _classify_to_channel_type(normalized.x, data, is_dimension=True)
    chart_local_style_context = build_chart_style_context(
        chart_style_context, normalized
    )
    plan = plan_cartesian(
        normalized,
        data,
        chart_style_context,
        "histogram",
        x_ch_type,
        "quantitative",
        None,
        None,
    )
    primary = plan.primary
    hist = merge_onto_base(chart_style_context.histogram, primary)
    channels = plan.channels
    ax_merged, ay_merged = plan.ax_merged, plan.ay_merged
    ay_merged = _bake_ay_position_left(ay_merged)
    # Histogram's x is always a bottom-orient bin axis — no left/right edge.
    # Neither axis carries tick_values on a histogram (VL computes bins
    # client-side), so tick_label_format's `len(tick_values) >= 2` guard can
    # never pass on either axis — format_authored/format_is_alias below are
    # inert here, not a real provenance read (histogram has no cascade to
    # read one from). The label gate below uses the REAL ay_format_authored
    # from plan_cartesian so the narrative/native decision matches bar's
    # behavior for the same format provenance.
    ay, style_tail = build_cartesian_axes(
        normalized.id,
        chart_style_context,
        ax_merged,
        ay_merged,
        ax_band_position=plan.ax_band_position,
        ay_band_position=plan.ay_band_position,
        ax_edge=None,
        ay_format_authored=True,
        ay_format_is_alias=False,
        ticks=_CartesianTickResolution((), None, None),
        column_forming=True,
        measure_tooltip_format=None,
    )
    hist_axis_is_house = (
        ay.labels.format is not None
        and is_d3_si_spec(ay.labels.format)
        and (not plan.ay_format_authored or plan.ay_format_is_alias)
    )
    # histogram reuses ResolvedBarStyle; these bar-only fields are unread by
    # the histogram emit path (no stack, no endpoint labels, no grouped x offset).
    _tf = _title_font(normalized, chart_local_style_context, width)
    hist_labels, hist_label_is_house = _label_format_fallback(
        hist.marks.bar.labels,
        ay.labels.format,
        hist_axis_is_house,
        chart_style_context.formats,
    )
    hist_mark = hist.marks.bar.model_copy(update={"labels": hist_labels})
    return ResolvedBarChart(
        **_base_kwargs(
            normalized,
            chart_style_context,
            channels,
            hist.legend,
            _effective_palette(chart_style_context, primary),
            requested_alias_palette=_effective_requested_alias_palette(
                chart_style_context, primary
            ),
            automatic_link_candidate=automatic_link_candidate,
            layout_padding=hist.padding,
        ),
        **{
            **_cartesian_kwargs(
                normalized,
                chart_local_style_context,
                variables,
                data,
                "histogram",
                panel_axes=dataset.axes,
            ),
            # Histogram uses aggregate-count on y; authored `y: [a, b]` is legal
            # at the normalize boundary but meaningless here. Strip the list so the
            # narrowed resolved y field (str | None) doesn't fail validation.
            "y": None if isinstance(normalized.y, list) else normalized.y,
        },
        chart_type="histogram",
        stack="none",
        stacked_domain_max=None,
        orientation="vertical",
        style=ResolvedBarStyle(
            series_label=_resolved_series_label(chart_style_context, primary, width),
            stack_order=None,
            mark=hist_mark,
            overlap=None,
            single_series_fill=_effective_single_series_fill(
                chart_style_context,
                primary,
                rhythm_slot=normalized.rhythm_slot,
                has_layers=bool(normalized.layers),
            ),
            # A histogram bins x and aggregates y to a count, so there is no
            # per-row value for a rail to anchor to — it would place labels
            # against a measure the chart never plots. Bar's slot supplies the
            # rest of the style; this one field is off for the family.
            endpoint_labels=chart_style_context.bar.endpoint_labels.model_copy(
                update={"visible": False}
            ),
            label_is_house=hist_label_is_house,
            # Read, but it can never produce a threshold: a histogram emits
            # `{"aggregate": "count", ...}` with no scale key, so _measure_span
            # finds no span and the fit test stands down on the next line.
            label_font_size=_effective_label_font_size(
                hist_mark.labels, chart_style_context
            ),
            total_label_is_house=False,
            label_usable_ratio=chart_style_context.label_usable_ratio,
            title_font=_tf,
            **style_tail,
        ),
    )
