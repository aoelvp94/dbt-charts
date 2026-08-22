"""Spark chart (sparkline) rendering functions.

Stage: RENDER
Purpose: Render inline spark charts as SVG for table cells.

Variants:
- line:          mini line chart from an array of values
- area:          filled line chart from an array of values
- bar:           single horizontal bar, absolute magnitude, no track
- bar-normalize: single horizontal bar, scaled to explicit max, with track
- column:        single vertical bar, bottom-anchored, scaled to max, no track
- columns:       mini vertical bar chart from an array of values

All functions return SVG strings that can be embedded directly in table cells.
"""

import html
from dataclasses import dataclass
from typing import Any

from dbt_charts.core.compile.models.primitives import FontStyle, SpacingValues
from dbt_charts.core.compile.models.style.resolved import ResolvedChartDefaults
from dbt_charts.core.compile.models.style.theme import SparkStyle

_SPARK_WIDTH = 80.0
_SPARK_HEIGHT = 24.0
_SPARK_BAR_WIDTH = 100.0
_SPARK_BAR_HEIGHT = 16.0
# `column` width/height live in theme (style.spark.column.{width,height})
# rather than as module-level constants — read via resolved_style at call site.


def _resolve_spark_color(call_site_color: str | None, spark_cfg: SparkStyle) -> str:
    """Return the spark line/fill color, preferring the call-site override.

    Raises if neither the call site nor the theme resolves a color — spark
    cells without an accent set are a theme configuration bug, not something
    to silently paper over with a default.
    """
    resolved = call_site_color if call_site_color is not None else spark_cfg.color
    if resolved is None:
        raise ValueError(
            "spark color is unset: theme must set charts.spark.color or the "
            "caller must pass color=... explicitly"
        )
    return resolved


@dataclass
class NormalizedPoints:
    """Pre-computed normalized points for spark chart rendering."""

    points: list[str]
    min_val: float
    max_val: float
    min_idx: int
    max_idx: int
    plot_width: float
    plot_height: float
    padding: SpacingValues


def _normalize_points(
    values: list[int | float],
    width: float | int,
    height: float | int,
    spark_style: SparkStyle,
    padding: SpacingValues | None = None,
) -> NormalizedPoints:
    padding = spark_style.padding if padding is None else padding
    min_val = min(values)
    max_val = max(values)
    value_range = max_val - min_val

    plot_width = width - padding.horizontal
    plot_height = height - padding.vertical

    points: list[str] = []
    num_values = len(values)

    for i, val in enumerate(values):
        x = padding.left + (i / (num_values - 1)) * plot_width
        if value_range > 0:
            y = padding.top + (1 - (val - min_val) / value_range) * plot_height
        else:
            y = padding.top + plot_height / 2
        points.append(f"{x:.1f},{y:.1f}")

    return NormalizedPoints(
        points=points,
        min_val=min_val,
        max_val=max_val,
        min_idx=values.index(min_val),
        max_idx=values.index(max_val),
        plot_width=plot_width,
        plot_height=plot_height,
        padding=padding,
    )


def _svg_wrapper(content: str, width: float | int, height: float | int) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">{content}</svg>'


def _render_empty_spark(
    width: float | int,
    height: float | int,
    spark_style: SparkStyle,
) -> str:
    empty_config = spark_style.empty
    y = height / 2
    content = (
        f'<line x1="{empty_config.inset_x}" y1="{y}" '
        f'x2="{width - empty_config.inset_x}" y2="{y}" '
        f'stroke="{empty_config.stroke.color}" stroke-width="{empty_config.stroke.width}" '
        f'stroke-dasharray="{empty_config.stroke.dasharray}"/>'
    )
    return _svg_wrapper(content, width, height)


def _render_single_value_line(
    width: float | int,
    height: float | int,
    color: str | None,
    stroke_width: float,
    spark_style: SparkStyle,
) -> str:
    single_value = spark_style.single_value
    y = height / 2
    escaped_color = html.escape(color or "")
    content = (
        f'<line x1="{single_value.inset_x}" y1="{y}" x2="{width - single_value.inset_x}" y2="{y}" '
        f'stroke="{escaped_color}" stroke-width="{stroke_width}"/>'
        f'<circle cx="{width / 2}" cy="{y}" r="{single_value.marker_radius}" fill="{escaped_color}"/>'
    )
    return _svg_wrapper(content, width, height)


def render_spark_line(
    values: list[int | float],
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    last_visible: bool = False,
    min_max_visible: bool = False,
    stroke_width: float = 1.5,
    *,
    resolved_style: ResolvedChartDefaults,
) -> str:
    """Render a line sparkline as SVG."""
    spark_cfg = resolved_style.spark
    width = width if width is not None else _SPARK_WIDTH
    height = height if height is not None else _SPARK_HEIGHT
    color = _resolve_spark_color(color, spark_cfg)

    if not values:
        return _render_empty_spark(width, height, spark_cfg)

    if len(values) == 1:
        return _render_single_value_line(width, height, color, stroke_width, spark_cfg)

    norm = _normalize_points(values, width, height, spark_cfg)
    escaped_color = html.escape(color or "")

    polyline = (
        f'<polyline points="{" ".join(norm.points)}" fill="none" '
        f'stroke="{escaped_color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )

    markers = ""
    if last_visible:
        last_point = norm.points[-1].split(",")
        markers += f'<circle cx="{last_point[0]}" cy="{last_point[1]}" r="2.5" fill="{escaped_color}"/>'

    if min_max_visible:
        for idx in [norm.min_idx, norm.max_idx]:
            pt = norm.points[idx].split(",")
            markers += (
                f'<circle cx="{pt[0]}" cy="{pt[1]}" r="2" fill="{escaped_color}"/>'
            )

    return _svg_wrapper(polyline + markers, width, height)


def render_spark_area(
    values: list[int | float],
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    fill_opacity: float | None = None,
    last_visible: bool = False,
    stroke_width: float = 1.5,
    *,
    resolved_style: ResolvedChartDefaults,
) -> str:
    """Render a filled area sparkline as SVG."""
    spark_cfg = resolved_style.spark
    width = width if width is not None else _SPARK_WIDTH
    height = height if height is not None else _SPARK_HEIGHT
    color = _resolve_spark_color(color, spark_cfg)
    fill_opacity = spark_cfg.area.fill_opacity if fill_opacity is None else fill_opacity

    if not values:
        return _render_empty_spark(width, height, spark_cfg)

    if len(values) == 1:
        return _render_single_value_line(width, height, color, stroke_width, spark_cfg)

    norm = _normalize_points(values, width, height, spark_cfg)
    escaped_color = html.escape(color or "")

    bottom_y = height - norm.padding.bottom
    first_x = norm.padding.left
    last_x = norm.padding.left + norm.plot_width
    polygon_points = (
        f"{first_x},{bottom_y} " + " ".join(norm.points) + f" {last_x},{bottom_y}"
    )

    polygon = f'<polygon points="{polygon_points}" fill="{escaped_color}" fill-opacity="{fill_opacity}"/>'
    polyline = (
        f'<polyline points="{" ".join(norm.points)}" fill="none" '
        f'stroke="{escaped_color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )

    markers = ""
    if last_visible:
        last_point = norm.points[-1].split(",")
        markers = f'<circle cx="{last_point[0]}" cy="{last_point[1]}" r="2.5" fill="{escaped_color}"/>'

    return _svg_wrapper(polygon + polyline + markers, width, height)


def render_spark_columns(
    values: list[int | float],
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    gap: float | None = None,
    *,
    resolved_style: ResolvedChartDefaults,
) -> str:
    """Render a multi-value vertical bar sparkline (`spark.type: columns`) as SVG."""
    spark_cfg = resolved_style.spark
    width = width if width is not None else _SPARK_WIDTH
    height = height if height is not None else _SPARK_HEIGHT
    color = _resolve_spark_color(color, spark_cfg)
    gap = spark_cfg.columns.gap if gap is None else gap

    if not values:
        return _render_empty_spark(width, height, spark_cfg)

    min_val = min(values)
    max_val = max(values)
    value_range = max_val - min_val

    padding = spark_cfg.columns.padding
    plot_height = height - (2 * padding)

    num_bars = len(values)
    total_gap = gap * (num_bars - 1)
    bar_width = (width - total_gap) / num_bars

    escaped_color = html.escape(color or "")
    bars: list[str] = []

    for i, val in enumerate(values):
        x = i * (bar_width + gap)
        if value_range > 0:
            bar_height = max(
                spark_cfg.columns.min_bar_height,
                ((val - min_val) / value_range) * plot_height,
            )
        else:
            bar_height = plot_height / 2

        y = height - padding - bar_height
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" fill="{escaped_color}" rx="{spark_cfg.columns.border.radius}"/>'
        )

    return _svg_wrapper("".join(bars), width, height)


def _get_threshold_color(
    value: int | float,
    thresholds: dict[int | float, str],
    spark_style: SparkStyle,
) -> str:
    assert spark_style.bar.color is not None
    color = spark_style.bar.color
    for threshold in sorted(thresholds.keys()):
        if value >= threshold:
            color = thresholds[threshold]
    return color


def render_spark_bar(
    value: int | float,
    max_value: float | None = None,
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    background: str | None = None,
    thresholds: dict[int | float, str] | None = None,
    border_radius: float | None = None,
    value_visible: bool = False,
    value_suffix: str | None = None,
    font: FontStyle | None = None,
    *,
    normalize: bool = False,
    resolved_style: ResolvedChartDefaults,
) -> str:
    """Render a single horizontal bar as SVG.

    Two variants share this renderer:
    - `bar` (normalize=False): no background track. The caller is expected to
      pass a column-scoped `max_value` so widths read as magnitude-proportional.
    - `bar-normalize` (normalize=True): background track always drawn — the
      width reads as "% of max".

    Args:
        value: Single numeric value.
        max_value: Upper bound for width scaling. Falls back to the theme
            `default_max` when None.
        normalize: True → `bar-normalize` (with background track);
            False → `bar` (no track, magnitude only).
        Other args: see field docs.
    """
    spark_cfg = resolved_style.spark
    assert spark_cfg.bar.color is not None
    bar_config = spark_cfg.bar
    max_value = bar_config.default_max if max_value is None else max_value
    width = _SPARK_BAR_WIDTH if width is None else width
    height = _SPARK_BAR_HEIGHT if height is None else height
    background = spark_cfg.bar.background if background is None else background
    border_radius = bar_config.border.radius if border_radius is None else border_radius

    clamped_value = max(0, min(value, max_value))
    fill_pct = (clamped_value / max_value) if max_value > 0 else 0
    fill_width = fill_pct * width

    if color:
        fill_color = color
    elif thresholds:
        fill_color = _get_threshold_color(clamped_value, thresholds, spark_cfg)
    else:
        fill_color = spark_cfg.bar.color

    escaped_fill = html.escape(fill_color)

    bg_rect = ""
    if normalize:
        escaped_bg = html.escape(background)
        bg_rect = (
            f'<rect x="0" y="0" width="{width}" height="{height}" '
            f'fill="{escaped_bg}" rx="{border_radius}"/>'
        )
    fill_rect = (
        f'<rect x="0" y="0" width="{fill_width:.1f}" height="{height}" '
        f'fill="{escaped_fill}" rx="{border_radius}"/>'
        if fill_width > 0
        else ""
    )

    value_label = ""
    if value_visible:
        display = (
            f"{value:g}"
            if isinstance(value, int) or value.is_integer()
            else f"{value:.1f}"
        )
        if value_suffix:
            display += value_suffix
        text_x = width - bar_config.label.inset_x
        text_y = height / 2
        _font_size = font.size if font is not None else None
        fs = (
            _font_size
            if _font_size is not None
            else max(
                bar_config.label.min_size,
                height - bar_config.label.height_offset,
            )
        )
        # inherit graph guarantees table.font.family is non-None after resolve_style
        _label_family = (
            font.family if font is not None else None
        ) or resolved_style.table.font.family
        assert _label_family is not None
        value_label = (
            f'<text x="{text_x}" y="{text_y}" '
            f'font-size="{fs}" fill="{bar_config.label.fill}" fill-opacity="{bar_config.label.fill_opacity}" '
            f'text-anchor="end" dominant-baseline="central" '
            f'font-family="{html.escape(str(_label_family))}" '
            f'style="font-variant-numeric: tabular-nums lining-nums;">'
            f"{html.escape(display)}</text>"
        )

    return _svg_wrapper(bg_rect + fill_rect + value_label, width, height)


def render_spark_column(
    value: int | float,
    max_value: float | None = None,
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    thresholds: dict[int | float, str] | None = None,
    border_radius: float | None = None,
    *,
    resolved_style: ResolvedChartDefaults,
) -> str:
    """Render a single vertical bar (`spark.type: column`) as SVG.

    Bottom-anchored: the rect grows upward from the bottom edge of the cell.
    Fixed-ceiling scaling — `column` is the vertical mirror of `bar-normalize`
    without the background track. Value is clamped to ``max_value`` (theme
    `default_max` if not authored); does NOT auto-scale to the column's
    data max the way `bar` does. Reuses `spark.bar.*` theme tokens (color,
    default_max, border) so authors don't need to theme the two marks
    separately.
    """
    spark_cfg = resolved_style.spark
    assert spark_cfg.bar.color is not None
    bar_config = spark_cfg.bar
    column_config = spark_cfg.column
    max_value = bar_config.default_max if max_value is None else max_value
    width = column_config.width if width is None else width
    height = column_config.height if height is None else height
    border_radius = bar_config.border.radius if border_radius is None else border_radius

    clamped_value = max(0, min(value, max_value))
    fill_pct = (clamped_value / max_value) if max_value > 0 else 0
    fill_height = fill_pct * height

    if color:
        fill_color = color
    elif thresholds:
        fill_color = _get_threshold_color(clamped_value, thresholds, spark_cfg)
    else:
        fill_color = spark_cfg.bar.color

    escaped_fill = html.escape(fill_color)

    fill_rect = (
        f'<rect x="0" y="{(height - fill_height):.1f}" '
        f'width="{width}" height="{fill_height:.1f}" '
        f'fill="{escaped_fill}" rx="{border_radius}"/>'
        if fill_height > 0
        else ""
    )

    return _svg_wrapper(fill_rect, width, height)


def render_spark(
    data: Any,
    spark_type: str,
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    *,
    font: FontStyle | None = None,
    resolved_style: ResolvedChartDefaults,
    **options: Any,
) -> str:
    """Render a spark chart based on type.

    Args:
        spark_type: One of "line", "area", "bar", "bar-normalize", "column",
            "columns".
    """
    spark_cfg = resolved_style.spark
    if spark_type in ("bar", "bar-normalize"):
        w = width or _SPARK_BAR_WIDTH
        h = height or None
        c = color or spark_cfg.bar.color
    elif spark_type == "column":
        w = width or spark_cfg.column.width
        h = height or spark_cfg.column.height
        c = color or spark_cfg.bar.color
    else:
        w = width or _SPARK_WIDTH
        h = height or _SPARK_HEIGHT
        c = color or spark_cfg.color

    if spark_type in ("line", "area", "columns"):
        if data is None:
            values: list[int | float] = []
        elif isinstance(data, (list, tuple)):
            values = list(data)
        else:
            values = [data]

        if spark_type == "line":
            return render_spark_line(
                values,
                width=w,
                height=h,
                color=c,
                last_visible=options.get("last_visible", False),
                min_max_visible=options.get("min_max_visible", False),
                resolved_style=resolved_style,
            )
        elif spark_type == "area":
            return render_spark_area(
                values,
                width=w,
                height=h,
                color=c,
                fill_opacity=options.get("fill_opacity"),
                last_visible=options.get("last_visible", False),
                resolved_style=resolved_style,
            )
        else:  # spark_type == "columns"
            return render_spark_columns(
                values, width=w, height=h, color=c, resolved_style=resolved_style
            )

    if spark_type in ("bar", "bar-normalize", "column"):
        if isinstance(data, (int, float)):
            val = float(data)
        elif isinstance(data, (list, tuple)) and len(data) > 0:
            first = data[0]
            if isinstance(first, (int, float)):
                val = float(first)
            else:
                try:
                    val = float(str(first))
                except (TypeError, ValueError):
                    val = 0.0
        else:
            try:
                val = float(str(data))
            except (TypeError, ValueError):
                val = 0.0

        if spark_type == "column":
            return render_spark_column(
                val,
                max_value=options.get("max"),
                width=w,
                height=h,
                color=c if color else None,
                thresholds=options.get("thresholds"),
                border_radius=options.get("border_radius"),
                resolved_style=resolved_style,
            )

        return render_spark_bar(
            val,
            max_value=options.get("max"),
            width=w,
            height=h,
            color=c if color else None,
            background=options.get("background"),
            thresholds=options.get("thresholds"),
            border_radius=options.get("border_radius"),
            value_visible=options.get("value_visible", False),
            value_suffix=options.get("value_suffix"),
            font=font,
            normalize=(spark_type == "bar-normalize"),
            resolved_style=resolved_style,
        )

    raise ValueError(f"Unknown spark type: {spark_type}")
