"""Scatter chart emitter for render-v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dbt_charts.core.compile.models.chart.resolved.scatter import ResolvedScatterChart
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartDataset
from dbt_charts.core.render.chart.emitters._cartesian import (
    apply_domain_headroom_bounds,
    build_palette_config,
    canonicalize_cartesian_x_data,
    chart_sort_to_vl,
    resolve_cartesian_x,
)
from dbt_charts.core.render.chart.emitters._channels import (
    apply_color_legend,
    channel_to_encoding,
    field_encoding,
    infer_vega_type_from_data,
)
from dbt_charts.core.render.chart.emitters._layers import emit_scatter_layer
from dbt_charts.core.render.chart.spec import ChartSpec, RenderBox
from dbt_charts.core.render.chart.type_inference import (
    _utc_time_label_expr,
    apply_x_tick_cadence,
)
from dbt_charts.core.render.chart.vl_field_maps import (
    axis_to_vl,
    bake_tick_ladder,
    compose_axis_label_expr,
    emit_resolved_scale_vl,
    measure_axis_to_vl,
)
from dbt_charts.core.render.utils import normalize_data_types
from dbt_charts.core.text.case import format_display_text
from dbt_charts.core.text.format_d3 import is_time_format


@dataclass
class ScatterEmitter:
    def emit(
        self,
        chart: ResolvedScatterChart,
        box: RenderBox,
        dataset: ChartDataset,
        datasets: dict[str | None, list[dict[str, Any]]] | None = None,
    ) -> ChartSpec:
        data = dataset.all_rows()
        ax = chart.style.axis_x
        ay = chart.style.axis_y
        encoding: dict[str, Any] = {}

        x_transformed = False
        if chart.x:
            # Decided from the RAW rows, before canonicalization ever runs:
            # canonicalize_cartesian_x_data's normalize_labeled_temporal
            # applies an is_year_shaped heuristic meant for bar/line/area's
            # dimension x (year-shaped integers ARE years there); scatter's
            # canonical x is a continuous measure, where that same heuristic
            # would misread a numeric column in the 1900-2100 band as a date
            # axis. The common scatter case: two continuous measures. Never
            # route this through resolve_axis_x_overlap's own directive —
            # its quantitative fast path unconditionally asserts
            # labelOverlap: false (never hide a label), which disables
            # Vega-Lite's own adaptive thinning of a crowded numeric axis.
            # That directive is fine for bar/line/area/heatmap, whose
            # typical x is temporal/categorical, but scatter's canonical
            # x is exactly the case it never gets tested against — a
            # dense quantitative axis reads as overlapping digits with it
            # forced on. Keep Vega-Lite's own default here, as before.
            if infer_vega_type_from_data(data, chart.x) == "quantitative":
                x_type = "quantitative"
                x_axis = axis_to_vl(ax)
                if ax.labels.angle is None:
                    x_axis["labelAngle"] = 0.0
                # Authored tick cadence still applies: this branch skips
                # build_cartesian_x_encoding, so it reaches the shared emitter
                # itself or ticks.count/step resolve and then vanish.
                apply_x_tick_cadence(x_axis, ax, chart.x, x_type)
                x_time_unit = None
            else:
                # Labeled bucket strings ("Q1 2024") and non-date-only temporal
                # values (datetime.datetime) reach resolve_cartesian_x's
                # axis.values/labelExpr/timeUnit unparseable by Vega's JS Date
                # otherwise — bar/line/area canonicalize their x rows before the
                # same call; scatter has no gap-fill scaffold of its own, so it
                # needs the same two-step precondition directly.
                data, x_transformed = canonicalize_cartesian_x_data(
                    data, chart.x, ax.time_unit
                )
                # resolve_cartesian_x is the shared bar/line/area resolver
                # (overlap → axis_to_vl → build_cartesian_x_encoding);
                # mark_type "scatter" joins line/area's always-continuous-
                # temporal rule for a bucketed-calendar grain (a scatter
                # point needs its real position, not a band-snapped one),
                # which is also what gets it bar/line's Jan/2024 label
                # vocabulary instead of falling through to Vega-Lite's own
                # default temporal formatter.
                x_res = resolve_cartesian_x(
                    chart.x,
                    data,
                    ax,
                    chart.style.label_usable_ratio,
                    box.width,
                    chart.id,
                    "scatter",
                )
                x_type, x_axis, x_time_unit = x_res.vl_type, x_res.axis, x_res.time_unit
            x_scale = emit_resolved_scale_vl(ax.scale, include_x_only=True)
            # Use axis title font to match oracle (effective.axis_x.title.font).
            x_enc: dict[str, Any] = {
                "field": chart.x,
                "type": x_type,
                "title": (
                    chart.x_label
                    if chart.x_label
                    else format_display_text(
                        chart.x, from_slug=True, font=ax.title.font
                    )
                ),
            }
            if x_time_unit:
                x_enc["timeUnit"] = x_time_unit
            if x_axis:
                x_enc["axis"] = x_axis
            if x_scale:
                x_enc["scale"] = x_scale
            encoding["x"] = x_enc

        y_plain: str | None = None
        if chart.y:
            y_type = infer_vega_type_from_data(data, chart.y)
            y_axis = measure_axis_to_vl(ay, data, (chart.y,))
            y_axis = compose_axis_label_expr(y_axis, ay.ruler, ay)
            # A d3 axis format applied to categorical tick labels makes Vega
            # coerce every category string to NaN. For a nominal/ordinal y a
            # time-format routes through a UTC labelExpr (mirrors the x-axis path
            # in build_cartesian_x_encoding); every other format is simply
            # dropped so categories render as their string values.
            y_fmt = y_axis.get("format")
            if y_type in ("nominal", "ordinal") and isinstance(y_fmt, str):
                if is_time_format(y_fmt) and "labelExpr" not in y_axis:
                    y_axis["labelExpr"] = _utc_time_label_expr(y_fmt)
                y_axis.pop("format", None)
                y_axis.pop("formatType", None)
            # orient is baked at resolve time (ay.position is concrete, never "auto")

            bake_tick_ladder(y_axis, ay.tick_values)

            y_scale = emit_resolved_scale_vl(ay.scale)
            if y_type == "quantitative" and "domain" not in y_scale:
                # Exact headroom-applied bounds baked at resolve(); an authored
                # `domain` (mapped above) always wins outright.
                y_scale = apply_domain_headroom_bounds(
                    y_scale, ay.domain_max, ay.domain_min
                )
            # Held as plain text: the overlay uses it as the base series' legend
            # label, which must stay a primitive even once this family's axis
            # title gets display-wrapped like the cartesian ones.
            y_plain = (
                chart.y_label
                if chart.y_label
                else format_display_text(chart.y, from_slug=True, font=ay.title.font)
            )
            y_enc: dict[str, Any] = {
                "field": chart.y,
                "type": y_type,
                "title": y_plain,
            }
            if y_axis:
                y_enc["axis"] = y_axis
            if y_scale:
                y_enc["scale"] = y_scale
            # A categorical y (dot plot) honours an authored chart.sort to order
            # its band domain — mirrors the bar categorical-axis path. A numeric y
            # is a continuous scale where sort does not apply.
            if y_type in ("nominal", "ordinal"):
                y_sort = chart_sort_to_vl(chart.sort)
                if y_sort is not None:
                    y_enc["sort"] = y_sort

            # Tooltip format goes on the measure encoding only: a numeric format on a
            # categorical y coerces its category strings to NaN in the tooltip.
            fmt = chart.style.tooltip_format
            if fmt and y_type == "quantitative":
                y_enc["format"] = fmt

            encoding["y"] = y_enc

        color_ch = chart.resolved_channels.get("color")
        if color_ch is not None:
            color_title = (
                format_display_text(
                    color_ch.data_field, from_slug=True, font=ay.title.font
                )
                if color_ch.data_field
                else None
            )
            enc = channel_to_encoding(color_ch, data, title=color_title)
            if enc is not None:
                apply_color_legend(enc, chart.legend)
                encoding["color"] = enc

        if chart.size:
            size_enc = field_encoding(chart.size, "quantitative")
            size_enc["title"] = format_display_text(
                chart.size, from_slug=True, font=ay.title.font
            )
            apply_color_legend(size_enc, chart.legend)
            encoding["size"] = size_enc

        if chart.shape:
            encoding["shape"] = field_encoding(chart.shape, "nominal")

        # mark_props: base point shape + tooltip + optional single-series fill.
        # When a color encoding is present it drives fill; suppress the default.
        # When no color encoding, use the single_series_fill baked at resolve time.
        mark_props = emit_scatter_layer(
            chart.style.point_mark,
            color_ch is not None,
            chart.style.single_series_fill,
        )

        config: dict[str, Any] = {**build_palette_config(chart.palette)}

        spec = ChartSpec(
            mark="point",
            encoding=encoding,
            layers=[],
            config=config,
            mark_props=mark_props,
        )
        # When x canonicalization fired, stamp transformed rows onto the spec
        # so the session does not overwrite with raw query data.
        if x_transformed:
            spec.data = normalize_data_types(data)

        if chart.layers:
            from dbt_charts.core.render.chart.emitters._overlay import (
                render_cartesian_overlay,
            )

            spec = render_cartesian_overlay(
                spec,
                chart.layers,
                data,
                chart_id=chart.id,
                axis_x=chart.style.axis_x,
                axis_y=chart.style.axis_y,
                base_y_title_suppressed=(
                    bool(chart.y_label) and chart.style.axis_y.title.visible is False
                ),
                # Scatter's own base (above) canonicalizes x unconditionally,
                # regardless of an authored axis_x.type: temporal — it never
                # consults gap_fill_ordinal_time's escape hatch the way
                # bar/line/area do, so an own-query overlay layer here must
                # never skip either.
                base_x_authored_temporal=False,
                tooltip_format=chart.style.tooltip_format,
                background=chart.background,
                single_series_fill=chart.style.single_series_fill,
                legend=chart.legend,
                config=config,
                # The endpoint-label rail never applies to scatter as a base
                # chart (EndpointLabelFeature.applies_to() only covers
                # line/area/bar) — a scatter base has no rail to be
                # load-bearing for.
                layered_rail_may_fire=False,
                base_query_name=chart.query_name,
                base_mark_type="scatter",
                base_label=y_plain,
                datasets=datasets,
            )

        return spec
