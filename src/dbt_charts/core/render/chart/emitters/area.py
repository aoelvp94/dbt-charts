"""Area chart emitter for render-v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dbt_charts.core.compile.models.chart.resolved._channel import ResolvedStyleChannel
from dbt_charts.core.compile.models.chart.resolved.area import ResolvedAreaChart
from dbt_charts.core.compile.models.style.resolved._marks import ResolvedAreaMarkStyle
from dbt_charts.core.compile.models.style.resolved.area import ResolvedAreaStyle
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartDataset, restripe
from dbt_charts.core.compile.resolve.chart._wide_fields import WIDE_LABEL_FIELD
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters._cartesian import (
    NATIVE_STACK_ORDER,
    CartesianXResolution,
    build_cartesian_y_encoding,
    build_palette_config,
    build_x_enc,
    distinct_series_values,
    resolve_cartesian_x,
    resolve_xy_titles,
    sorted_series_by_last_value,
    sorted_series_by_stack_order,
    spatial_color_scale,
    wide_measures_title,
)
from dbt_charts.core.render.chart.emitters._channels import (
    apply_color_legend,
    channel_to_encoding,
    gap_fill_ordinal_time_per_panel,
    pin_legend_display_order,
)
from dbt_charts.core.render.chart.emitters._layers import (
    emit_area_layer,
    sparse_band_transforms,
)
from dbt_charts.core.render.chart.emitters._overlay import (
    overlay_uses_band_step,
    render_cartesian_overlay,
)
from dbt_charts.core.render.chart.emitters._wide import (
    fold_wide_measures,
    unfold_wide_rows,
)
from dbt_charts.core.render.chart.spec import ChartSpec, RenderBox
from dbt_charts.core.render.chart.step_band import (
    BAND_STEP_CURVE,
    apply_step_band,
    is_band_step,
)
from dbt_charts.core.render.chart.time_unit_detect import normalize_labeled_temporal
from dbt_charts.core.render.chart.validation import (
    validate_color_series,
    validate_preaggregated_data_per_panel,
)
from dbt_charts.core.render.chart.vl_field_maps import (
    compose_axis_label_expr,
    measure_axis_to_vl,
)
from dbt_charts.core.render.utils import normalize_data_types
from dbt_charts.core.utils import (
    layered_endpoint_rail_fires,
    layered_endpoint_rail_shape,
)


def _normalize_area_data(
    chart: ResolvedAreaChart,
    dataset: ChartDataset,
    data: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Apply labeled-temporal normalization and ordinal-time gap-fill.

    Returns (data, transformed, x_authored_temporal). ``transformed`` is
    True when either step changed the rows — the caller stamps those rows
    onto the spec so the session does not overwrite them with raw query
    data. This must fire for labeled-temporal normalization alone (e.g.
    "Q1 2020" rewritten to an ISO bucket) even when gap-fill itself is
    skipped, or the session re-stamps unparsed labels onto a temporal
    encoding. ``x_authored_temporal`` is gap_fill_ordinal_time's own
    verdict, threaded to the caller's render_cartesian_overlay call instead
    of re-derived there.

    ``dataset`` is ``data`` (``dataset.all_rows()``) still in panel-shaped
    form — passed to ``gap_fill_ordinal_time_per_panel`` via ``restripe()``
    when normalization mutated ``data``, since ``chart.x`` can itself be the
    multiples field and re-deriving panels from the mutated value would
    fail to match the pre-mutation baked axis.
    """
    transformed = False
    mutated_dataset = dataset
    if chart.x:
        # Rewrite labeled/year-shaped x to ISO first (same as line.py/bar.py) so
        # build_cartesian_x_encoding sees date-shaped values and the mark-type
        # split routes area → temporal, not a quantitative fractional-year axis.
        normalized = normalize_labeled_temporal(data, chart.x)
        if normalized is not data:
            data = normalized
            transformed = True
            mutated_dataset = restripe(dataset, data)
    densified, x_authored_temporal = gap_fill_ordinal_time_per_panel(
        chart.style.axis_x,
        chart.x,
        chart.color,
        mutated_dataset,
        "area",
        chart.style.area_mark.curve == BAND_STEP_CURVE,
        True,
    )
    if densified is not None:
        data = densified
        transformed = True
    return data, transformed, x_authored_temporal


def _area_spatial_order(
    chart: ResolvedAreaChart, data: list[dict[str, Any]], series_field: str
) -> tuple[list[str], list[str]]:
    """Resolve area's distinct series and spatial legend order in one pass.

    Returns ``(series, order)``. Stacked: ``order`` mirrors the SAME order
    Vega-Lite's own default stack sort already paints with (area wires no
    authored stack_order — NATIVE_STACK_ORDER reproduces that native
    descending sort without adding a mark-order channel). Unstacked
    (overlap): stable order by each series' most-recent non-null value.
    ``order`` is empty when there's no series, or no x/y anchor to order by
    — the caller treats that as "nothing to reorder."
    """
    series = distinct_series_values(data, series_field)
    if not series:
        return series, []
    if chart.stack not in (None, "none"):
        # Top-of-stack-first: reverse the baseline-first order.
        return series, list(
            reversed(
                sorted_series_by_stack_order(
                    series, data, series_field, NATIVE_STACK_ORDER
                )
            )
        )
    if chart.x and isinstance(chart.y, str):
        return series, sorted_series_by_last_value(
            series, data, chart.x, chart.y, series_field
        )
    return series, []


def _apply_area_color_encoding(
    chart: ResolvedAreaChart,
    data: list[dict[str, Any]],
    top_encoding: VLDict,
) -> ResolvedStyleChannel | None:
    """Apply color encoding to top_encoding in-place.

    Returns the resolved color channel (or None) for use in sub-layer assembly.
    """
    color_ch = chart.resolved_channels.get("color")
    if color_ch is not None:
        enc = channel_to_encoding(color_ch, data)
        if enc is not None:
            apply_color_legend(enc, chart.legend)
            if (
                color_ch.mode == "series"
                and enc.get("type") == "nominal"
                and color_ch.data_field
                and chart.palette
            ):
                series, order = _area_spatial_order(chart, data, color_ch.data_field)
                if order:
                    enc["scale"] = spatial_color_scale(series, chart.palette, order)
                    pin_legend_display_order(enc, order)
            top_encoding["color"] = enc
    return color_ch


def _apply_area_step_band(
    chart: ResolvedAreaChart,
    data: list[dict[str, Any]],
    top_encoding: VLDict,
    area_mark: ResolvedAreaMarkStyle,
    x_type: str | None,
) -> list[dict[str, Any]] | None:
    """Apply band-aware step row doubling when curve is step on a band x-axis."""
    if is_band_step(area_mark.curve, x_type):
        # Area always renders as a continuous silhouette.
        return apply_step_band(data, top_encoding, chart_id=chart.id, connect=True)
    return None


def _build_area_top_encoding(
    chart: ResolvedAreaChart,
    data: list[dict[str, Any]],
    style: ResolvedAreaStyle,
    box: RenderBox,
) -> tuple[VLDict, ResolvedStyleChannel | None, str | None, str | None]:
    """Build the VL encoding dict, color channel, and resolved x VL type
    (None when the chart has no x channel at all) for an area chart.

    Tooltip *content* is a separate concern, built after emission by
    ``features/structured_tooltip.py`` from the chart-axes LUT.
    """
    ax, ay = style.axis_x, style.axis_y
    x_res = (
        resolve_cartesian_x(
            chart.x,
            data,
            ax,
            style.label_usable_ratio,
            box.width,
            chart.id,
            "area",
            style.area_mark.curve,
            overlay_uses_band_step(chart.layers),
        )
        if chart.x
        else CartesianXResolution("nominal", {}, {})
    )
    vl_type, ax_vl, x_scale = x_res.vl_type, x_res.axis, x_res.scale
    titles = resolve_xy_titles(
        chart.x,
        chart.y if isinstance(chart.y, str) else None,
        chart.x_label,
        chart.y_label,
        ax,
        ay,
        box,
        chart.id,
    )
    x_title, y_title = titles.x_title, titles.y_title
    y_field = chart.y if isinstance(chart.y, str) else None
    ay_vl = measure_axis_to_vl(ay, data, (y_field,) if y_field else ())
    ay_vl = compose_axis_label_expr(ay_vl, ay.ruler, ay)
    y_enc = build_cartesian_y_encoding(
        chart.y, ay, ay_vl, y_title, style.tooltip_format
    )
    # Area always needs explicit stack to override VL's implicit stacking default.
    y_enc["stack"] = chart.stack if chart.stack not in (None, "none") else None
    top_encoding: VLDict = {}
    if chart.x:
        top_encoding["x"] = build_x_enc(
            chart.x, vl_type, x_title, ax_vl, x_scale, x_res.time_unit
        )
    if chart.y:
        top_encoding["y"] = y_enc
    color_ch = _apply_area_color_encoding(chart, data, top_encoding)
    x_type = vl_type if chart.x else None
    return top_encoding, color_ch, x_type, titles.y_plain


def _emit_multi_metric_area(
    chart: ResolvedAreaChart,
    data: list[dict[str, Any]],
    box: RenderBox,
) -> ChartSpec:
    """Emit a folded unit spec for a multi-metric (y: [a, b, ...]) area chart."""
    assert chart.wide_measures
    style = chart.style
    area_mark = style.area_mark
    ax, ay = style.axis_x, style.axis_y
    x_res = (
        resolve_cartesian_x(
            chart.x, data, ax, style.label_usable_ratio, box.width, chart.id, "area"
        )
        if chart.x
        else CartesianXResolution("nominal", {}, {})
    )
    if is_band_step(area_mark.curve, x_res.vl_type if chart.x else None):
        raise ChartDataError(
            f"Area chart '{chart.id}': band-aware step curve is not supported "
            "for multi-metric (y: [...]) charts -- use a single y field or "
            "choose a different curve style."
        )
    measures = list(chart.wide_measures)
    # Same order computation area's authored-color path uses (_area_spatial_order,
    # above), fed a long-form view of the wide data — a wide area's series order
    # (both stacked baseline and unstacked/overlap paint order) must match what
    # an authored color: field of the same data would produce. Area's authored
    # path never uses a separate WIDE_ORDER_FIELD mark-order channel for either
    # shape (VL's stack transform reads the color domain order directly), so
    # baseline_order stays None here — unlike bar, which does need one.
    folded = unfold_wide_rows(data, measures)
    _series, order = _area_spatial_order(chart, folded, WIDE_LABEL_FIELD)
    display_order = order if order else sorted(measures)
    is_stacked = chart.stack not in (None, "none")
    wide = fold_wide_measures(
        measures,
        chart.palette,
        chart.legend,
        display_order=display_order,
        # Stacked: VL's native stack transform reads color.scale.domain
        # directly (see the comment above) -- the fold's own row order is
        # visually inert, keep it as authored. Unstacked/overlap: no such
        # mechanism exists, so the fold order IS the front-to-back paint order.
        fold_order=measures if is_stacked else display_order,
    )
    ay_vl = measure_axis_to_vl(ay, data, chart.wide_measures)
    ay_vl = compose_axis_label_expr(ay_vl, ay.ruler, ay)
    # Wide/folded y has no single measure field to title from — fall back to
    # the joined, humanized measure names, same as an authored y_label always
    # would (an authored y_label still wins outright).
    y_label_effective = chart.y_label or wide_measures_title(
        chart.wide_measures, ay.title.font
    )
    y_title = resolve_xy_titles(
        None, None, None, y_label_effective, ax, ay, box, chart.id
    ).y_title
    y_enc = build_cartesian_y_encoding(
        wide.value_field, ay, ay_vl, y_title, style.tooltip_format
    )
    y_enc["stack"] = chart.stack if chart.stack not in (None, "none") else None
    top_encoding: VLDict = {}
    if chart.x:
        x_title = resolve_xy_titles(
            chart.x, None, chart.x_label, None, ax, ay, box, chart.id
        ).x_title
        top_encoding["x"] = build_x_enc(
            chart.x,
            x_res.vl_type,
            x_title,
            x_res.axis,
            x_res.scale,
            x_res.time_unit,
        )
    top_encoding["y"] = y_enc
    top_encoding["color"] = wide.color
    if wide.order:
        top_encoding["order"] = wide.order
    stacked = chart.stack not in (None, "none")
    facet_fields = [f for f in (wide.color.get("field"), wide.order.get("field")) if f]
    band_transforms = (
        sparse_band_transforms(chart.x, wide.value_field, facet_fields)
        if stacked and chart.x and facet_fields
        else []
    )
    sub_layers = emit_area_layer(
        style.area_mark,
        style.line_mark,
        style.point_mark,
        chart.background,
        style.single_series_fill,
        True,
        wide.color,
        [],
        stacked,
        band_transforms,
        pin_child_colors=True,
    )
    return ChartSpec(
        mark="layered",
        encoding=top_encoding,
        layers=sub_layers,
        config=build_palette_config(chart.palette),
        transforms=wide.transforms,
    )


@dataclass
class AreaEmitter:
    def emit(
        self,
        chart: ResolvedAreaChart,
        box: RenderBox,
        dataset: ChartDataset,
        datasets: dict[str | None, list[dict[str, Any]]] | None = None,
    ) -> ChartSpec:
        data = dataset.all_rows()
        validate_preaggregated_data_per_panel(chart, dataset)
        validate_color_series(chart, data)
        # Normalize labeled temporal strings and fill ordinal-time gaps before
        # any path — multi-metric needs this as much as single-series.
        data, transformed, base_x_authored_temporal = _normalize_area_data(
            chart, dataset, data
        )
        if chart.wide_measures:
            spec = _emit_multi_metric_area(chart, data, box)
            if transformed:
                spec.data = normalize_data_types(data)
            return spec
        style = chart.style
        top_encoding, color_ch, x_type, y_plain = _build_area_top_encoding(
            chart, data, style, box
        )
        step_band_data = _apply_area_step_band(
            chart, data, top_encoding, style.area_mark, x_type
        )
        is_stacked = chart.stack not in (None, "none")
        # No per-layer tooltip array: structured tooltip content (base's own,
        # and -- when chart.layers is set -- the base's role content wired
        # onto this same spec) is set after emission by StructuredTooltipFeature
        # via VL's description channel. See features/structured_tooltip.py.
        measure_field = chart.y if isinstance(chart.y, str) else None
        series_field = (
            top_encoding["color"].get("field") if color_ch is not None else None
        )
        band_transforms = (
            sparse_band_transforms(chart.x, measure_field, [series_field])
            if is_stacked and chart.x and measure_field and series_field
            else []
        )
        sub_layers = emit_area_layer(
            style.area_mark,
            style.line_mark,
            style.point_mark,
            chart.background,
            style.single_series_fill,
            color_ch is not None,
            top_encoding["color"] if color_ch is not None else {},
            [],
            is_stacked,
            band_transforms,
            band_step=step_band_data is not None,
            pin_child_colors=color_ch is not None or bool(chart.layers),
            inherit_parent_color=bool(chart.layers),
        )
        spec = ChartSpec(
            mark="layered",
            encoding=top_encoding,
            layers=sub_layers,
            config=build_palette_config(chart.palette),
            data=step_band_data,
        )
        # Stamp transformed rows so the session does not overwrite with raw
        # query data. Preserve step-band-expanded rows when gap-fill also fired.
        if transformed:
            spec.data = normalize_data_types(
                step_band_data if step_band_data is not None else data
            )

        if chart.layers:
            base_label = y_plain
            spec = render_cartesian_overlay(
                spec,
                chart.layers,
                data,
                chart_id=chart.id,
                axis_x=style.axis_x,
                axis_y=style.axis_y,
                base_y_title_suppressed=(
                    bool(chart.y_label) and chart.style.axis_y.title.visible is False
                ),
                base_x_authored_temporal=base_x_authored_temporal,
                tooltip_format=style.tooltip_format,
                background=chart.background,
                single_series_fill=style.single_series_fill,
                legend=chart.legend,
                config=build_palette_config(chart.palette),
                layered_rail_may_fire=(
                    style.endpoint_labels.visible
                    and layered_endpoint_rail_fires(
                        layered_endpoint_rail_shape(chart.x, chart.y),
                        [layer.color is None for layer in chart.layers],
                    )
                ),
                base_query_name=chart.query_name,
                base_mark_type="area",
                base_label=base_label,
                datasets=datasets,
            )

        return spec
