"""Core-owned chart hover interactivity runtime."""

import json
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from dbt_charts.core.compile.config import get_chart_rendering
from dbt_charts.core.render.script_embedding import embed_svg_script
from dbt_charts.core.text.format_d3 import NULL_DISPLAY

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.style.resolved import ResolvedStyle


def _build_tooltip_style_dict(resolved_style: "ResolvedStyle") -> dict[str, Any]:
    """Build the camelCase JSON dict consumed by the JS tooltip runtime."""
    t = resolved_style.chart_defaults.tooltip
    return {
        "background": t.background,
        "lineHeight": t.line_height,
        "maxWidth": t.max_width,
        "gap": t.gap,
        "font": {"size": t.font.size},
        "padding": {
            "top": t.padding.top,
            "bottom": t.padding.bottom,
            "left": t.padding.left,
            "right": t.padding.right,
        },
        "label": {
            "font": {
                "color": t.label.font.color,
                "weight": t.label.font.weight,
            }
        },
        "value": {
            "font": {
                "color": t.value.font.color,
                "weight": t.value.font.weight,
            }
        },
        "border": {
            "color": t.border.color,
            "width": t.border.width,
            "radius": t.border.radius,
        },
        "shadow": {"visible": t.shadow.visible},
        "swatch": {"size": t.swatch.size, "radius": t.swatch.radius},
        "activeMarker": t.active_marker,
    }


def _build_hover_emphasis_dict(
    resolved_style: "ResolvedStyle",
) -> dict[str, bool | float | str]:
    """Build the JSON dict consumed by the JS hover-emphasis runtime.

    Three sources, deliberately: `visible` and the drop-line color/width are
    theme-cascaded (a theme decides whether hover emphasis happens at all,
    and picks its own neutral drop-line paint), while `opacity` is engine
    config (picking the bar/arc recession strength is ours -- there is no
    wide range of settings that read well).

    The bar/arc recession color still rides no wire of its own: it is the
    chart's own background, which Vega already paints into each chart's SVG
    as the view's background rect, read there by the runtime. The drop line
    is a different mechanism (a scaffold line added by the runtime, not a
    recede-in-place), so its paint has no such rendered fact to read off and
    is carried explicitly instead.
    """
    hover_emphasis = resolved_style.chart_defaults.hover_emphasis
    return {
        "visible": hover_emphasis.visible,
        "opacity": get_chart_rendering().hover_emphasis.dimmed_opacity,
        "dropLineColor": hover_emphasis.drop_line_color,
        "dropLineWidth": hover_emphasis.drop_line_width,
    }


def generate_chart_interactivity_source(resolved_style: "ResolvedStyle") -> str:
    """Return the chart hover runtime as raw JS with theme values injected.

    For hosts that ship the runtime as a plain HTML <script> beside SVG
    output whose own embedded scripts were sanitized away.
    """
    font_family = str(resolved_style.font.family)
    tooltip_style = _build_tooltip_style_dict(resolved_style)
    hover_emphasis = _build_hover_emphasis_dict(resolved_style)
    script = (
        files("dbt_charts.core.render")
        / "templates"
        / "scripts"
        / "chart_interactivity.js"
    ).read_text(encoding="utf-8")
    script = script.replace('"__DCT_FONT_FAMILY__"', json.dumps(font_family))
    script = script.replace('"__DCT_TOOLTIP_STYLE__"', json.dumps(tooltip_style))
    script = script.replace('"__DCT_HOVER_EMPHASIS__"', json.dumps(hover_emphasis))
    return script.replace('"__DCT_NULL_DISPLAY__"', json.dumps(NULL_DISPLAY))


def generate_svg_chart_interactivity_script(
    resolved_style: "ResolvedStyle",
) -> str:
    """Embed the chart hover runtime into SVG output."""
    return embed_svg_script(generate_chart_interactivity_source(resolved_style))
