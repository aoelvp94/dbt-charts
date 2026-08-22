"""Pie/donut chart emitter for render-v2."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from dbt_charts.core.compile.models.chart.resolved.pie import ResolvedPieChart
from dbt_charts.core.compile.models.primitives import FontStyle
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartDataset
from dbt_charts.core.compile.resolve.chart.label_data import (
    pie_presentation_fingerprint,
    project_pie_table_rows,
    render_pie_label_lines,
)
from dbt_charts.core.diagnostics import (
    ERR_INPUT_INVALID,
    ERR_RESOLVED_PIE_DATA_MISMATCH,
)
from dbt_charts.core.render.chart.emitters._channels import (
    apply_color_legend,
    channel_to_encoding,
)
from dbt_charts.core.render.chart.spec import ChartSpec, RenderBox
from dbt_charts.core.render.chart.vl_field_maps import slice_mark_to_vl
from dbt_charts.core.render.errors import RenderError
from dbt_charts.core.render.utils import normalize_data_types
from dbt_charts.core.text.case import format_display_text

_ARC_TOTAL_FIELD = "__dft_arc_total"
_ARC_ROW_FIELD = "__dft_arc_row"


def _augment_pie_data(
    theta_field: str,
    data: list[dict[str, Any]],
    slice_label_lines: tuple[tuple[str, ...], ...],
) -> list[dict[str, Any]]:
    """Attach arc geometry and the row-aligned labels finalized in resolution.

    Emits __dft_row_idx, __dft_pct, __dft_total, __dft_mid, __dft_top,
    __dft_right, __dft_label, __dft_label_lines.
    """
    data = normalize_data_types(data)
    if len(data) != len(slice_label_lines):
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message="resolved pie label rows do not match the render data row count",
        )

    thetas: list[float] = []
    for row in data:
        raw = row.get(theta_field)
        thetas.append(float(raw) if raw is not None else 0.0)
    total = sum(thetas)

    running = 0.0
    angle_meta = []
    for idx, v in enumerate(thetas):
        share = v / total if total else 0.0
        mid = 2 * math.pi * (running + v / 2.0) / total if total else 0.0
        angle_meta.append(
            {
                "__dft_total": total,
                "__dft_pct": share,
                "__dft_mid": mid,
                "__dft_top": math.cos(mid) >= 0,
                "__dft_right": math.sin(mid) >= 0,
                "__dft_row_idx": idx,
            }
        )
        running += v

    out = []
    for idx, row in enumerate(data):
        merged = dict(row)
        merged.update(angle_meta[idx])
        resolved_lines = slice_label_lines[idx]
        merged["__dft_label"] = list(resolved_lines) if resolved_lines else None
        merged["__dft_label_lines"] = len(resolved_lines) if resolved_lines else 0
        out.append(merged)
    return out


def prepare_pie_render_rows(
    chart: ResolvedPieChart, data: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mechanically project matching runtime rows through frozen pie policy."""
    if pie_presentation_fingerprint(data) != chart.presentation_fingerprint:
        raise RenderError.from_code(
            ERR_RESOLVED_PIE_DATA_MISMATCH,
            chart_id=chart.id,
        )
    color_field = chart.identity_field
    labels = chart.style.slice_mark.labels
    label_lines = (
        render_pie_label_lines(
            chart.theta,
            color_field,
            data,
            labels,
            chart.slice_label_indices,
        )
        if labels is not None
        else tuple(() for _ in data)
    )
    values = [float(row.get(chart.theta, 0) or 0) for row in data]
    total = sum(values)
    shares = [value / total if total else 0.0 for value in values]
    attached_rows = project_pie_table_rows(
        data,
        shares,
        chart.palette,
        color_field,
        chart.theta,
        chart.attached_row_indices,
    )
    return _augment_pie_data(chart.theta, data, label_lines), attached_rows


def _font_to_mark(font: FontStyle) -> dict[str, str | float]:
    """Copy non-None font fields into a VL text mark dict fragment."""
    mark: dict[str, str | float] = {}
    if font.family is not None:
        mark["font"] = font.family
    if font.size is not None:
        mark["fontSize"] = font.size
    if font.weight is not None:
        mark["fontWeight"] = font.weight
    if font.color is not None:
        mark["fill"] = font.color
    return mark


@dataclass
class PieEmitter:
    def emit(
        self,
        chart: ResolvedPieChart,
        box: RenderBox,
        dataset: ChartDataset,
    ) -> ChartSpec:
        data = dataset.all_rows()
        slice_style = chart.style.slice_mark
        labels_style = slice_style.labels
        outer_fraction = chart.outer_fraction

        color_ch = chart.resolved_channels.get("color")
        color_field = color_ch.data_field if color_ch is not None else None

        color_key = ""
        if color_ch is not None and color_ch.data_field:
            color_key = color_ch.data_field

        augmented, _attached_rows = prepare_pie_render_rows(chart, data)

        # ── Arc layer ──────────────────────────────────────────────────────
        arc_mark_props = {
            "tooltip": True,
            **slice_mark_to_vl(slice_style),
            "outerRadius": {"expr": (f"min(width, height) / 2 * {outer_fraction}")},
        }
        if not color_key:
            # No color channel → no VL color encoding paints the wedge. Give
            # it an explicit fill so slice labels have a real color to anchor
            # their dark-companion ink to (chart.palette is guaranteed
            # non-empty for pie charts — see _resolve_pie).
            arc_mark_props["fill"] = chart.palette[0]
        inner_ratio = chart.style.inner_radius
        if inner_ratio > 0:
            arc_mark_props["innerRadius"] = {
                "expr": (f"min(width, height) / 2 * {outer_fraction} * {inner_ratio}")
            }
        else:
            arc_mark_props["innerRadius"] = 0

        legend_font = chart.legend.title.font
        fmt = chart.style.tooltip_format
        theta_enc = {
            "field": chart.theta,
            "type": "quantitative",
            "title": format_display_text(chart.theta, from_slug=True, font=legend_font),
        }
        if fmt:
            theta_enc["format"] = fmt

        arc_encoding = {"theta": theta_enc}

        if color_ch is not None and color_field:
            enc = channel_to_encoding(
                color_ch,
                data,
                title=format_display_text(
                    color_field, from_slug=True, font=legend_font
                ),
            )
            if enc is not None:
                apply_color_legend(enc, chart.legend)
                enc["sort"] = False
                arc_encoding["color"] = enc

        arc_encoding["order"] = {"field": "__dft_row_idx", "type": "quantitative"}

        arc_spec = ChartSpec(
            mark="arc",
            encoding=arc_encoding,
            mark_props=arc_mark_props,
        )

        layers: list[ChartSpec] = [arc_spec]

        # ── Center total layers ────────────────────────────────────────────
        total_renders = chart.total is not None and chart.total.visible
        if total_renders:
            assert chart.total is not None  # narrowed
            total_style = chart.style.total_style
            theta_field = chart.theta

            # Value text layer: joinaggregate sum → __dft_arc_total, show one row.
            value_mark = {
                "type": "text",
                "align": "center",
                "baseline": "bottom",
                "tooltip": False,
                **_font_to_mark(total_style.value.font),
            }
            value_enc: dict[str, Any] = {
                "text": {"field": _ARC_TOTAL_FIELD, "type": "quantitative"},
                "x": {"value": {"expr": "width / 2"}},
                "y": {"value": {"expr": "height / 2"}},
            }
            # chart.total.format is already the resolved d3 spec (baked in
            # _resolve_pie); consume it directly — no compile-time reach-back.
            total_fmt = chart.total.format
            if total_fmt:
                value_enc["text"]["format"] = total_fmt

            value_transforms: list[dict[str, Any]] = [
                {
                    "joinaggregate": [
                        {"op": "sum", "field": theta_field, "as": _ARC_TOTAL_FIELD}
                    ]
                },
                {"window": [{"op": "row_number", "as": _ARC_ROW_FIELD}]},
                {"filter": f"datum.{_ARC_ROW_FIELD} === 1"},
            ]
            layers.append(
                ChartSpec(
                    mark="text",
                    encoding=value_enc,
                    mark_props=value_mark,
                    transforms=value_transforms,
                )
            )

            # Label text layer (caption below the value number).
            if chart.total.label is not None:
                label_mark = {
                    "type": "text",
                    "align": "center",
                    "baseline": "top",
                    "tooltip": False,
                    **_font_to_mark(total_style.label.font),
                }
                label_enc = {
                    "text": {"value": chart.total.label},
                    "x": {"value": {"expr": "width / 2"}},
                    "y": {"value": {"expr": "height / 2"}},
                }
                label_transforms: list[dict[str, Any]] = [
                    {"window": [{"op": "row_number", "as": _ARC_ROW_FIELD}]},
                    {"filter": f"datum.{_ARC_ROW_FIELD} === 1"},
                ]
                layers.append(
                    ChartSpec(
                        mark="text",
                        encoding=label_enc,
                        mark_props=label_mark,
                        transforms=label_transforms,
                    )
                )

        # ── Text label layer (leader lines) ───────────────────────────────
        # Color-driven labels need independent scale resolution; empty dict = no resolve key.
        resolve_block: dict[str, dict[str, str]] = (
            {"scale": {"color": "independent"}}
            if labels_style is not None and color_key
            else {}
        )
        if labels_style is not None:
            text_mark = {
                "baseline": "top",
                "lineHeight": labels_style.line_height,
                "tooltip": False,
                "align": {"expr": "datum.__dft_right ? 'left' : 'right'"},
            }
            f = labels_style.font
            if f.family is not None:
                text_mark["font"] = f.family
            if f.size is not None:
                text_mark["fontSize"] = f.size
            if f.weight is not None:
                text_mark["fontWeight"] = f.weight
            # No color channel → anchor label ink to the dark companion of the
            # same palette[0] the arc mark above is explicitly filled with,
            # unless the author set an explicit font.color (a genuine
            # cascade-managed sentinel: None unless authored at some tier —
            # see SliceLabelsStyle.font's InheritSlot exclude). Mirrors the
            # color-channel branch below, which never reads font.color at all.
            if not color_key:
                text_mark["fill"] = (
                    f.color if f.color is not None else chart.dark_companion_stops[0]
                )

            label_encoding = {
                "text": {"field": "__dft_label", "type": "nominal"},
                "x": {
                    "field": "__dft_x",
                    "type": "quantitative",
                    "scale": None,
                    "axis": None,
                },
                "y": {
                    "field": "__dft_y_anchored",
                    "type": "quantitative",
                    "scale": None,
                    "axis": None,
                },
            }

            if color_key:
                seen: list[str] = []
                for row in augmented:
                    v = row.get(color_key)
                    if v is None:
                        continue
                    s = str(v)
                    if s not in seen:
                        seen.append(s)
                dark_stops = list(chart.dark_companion_stops[: len(seen)])
                label_encoding["color"] = {
                    "field": color_key,
                    "type": "nominal",
                    "scale": {"domain": seen, "range": dark_stops},
                    "sort": False,
                    "legend": None,
                }
            offset = labels_style.offset
            lh = labels_style.line_height
            label_transforms = [
                {"filter": "datum.__dft_label != null"},
                {
                    "calculate": (
                        f"width / 2 + sin(datum.__dft_mid) * "
                        f"(min(width, height) / 2 * {outer_fraction} + {offset})"
                    ),
                    "as": "__dft_x",
                },
                {
                    "calculate": (
                        f"height / 2 - cos(datum.__dft_mid) * "
                        f"(min(width, height) / 2 * {outer_fraction} + {offset})"
                    ),
                    "as": "__dft_y",
                },
                {
                    "calculate": (
                        f"datum.__dft_y + (datum.__dft_top ? "
                        f"-(datum.__dft_label_lines * {lh}) : 0)"
                    ),
                    "as": "__dft_y_anchored",
                },
            ]

            layers.append(
                ChartSpec(
                    mark="text",
                    encoding=label_encoding,
                    mark_props=text_mark,
                    transforms=label_transforms,
                )
            )

        # ── Outer layered spec ─────────────────────────────────────────────
        config = {}
        if chart.palette:
            config["range"] = {"category": list(chart.palette)}

        return ChartSpec(
            mark="layered",
            layers=layers,
            config=config,
            data=augmented,
            resolve=resolve_block,
        )
