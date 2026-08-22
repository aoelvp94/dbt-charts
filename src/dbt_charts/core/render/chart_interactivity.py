"""Core-owned chart hover interactivity runtime."""

import json
from importlib.resources import files
from typing import TYPE_CHECKING, Any

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


def generate_chart_interactivity_source(resolved_style: "ResolvedStyle") -> str:
    """Return the chart hover runtime as raw JS with theme values injected.

    For hosts that ship the runtime as a plain HTML <script> beside SVG
    output whose own embedded scripts were sanitized away.
    """
    font_family = str(resolved_style.font.family)
    tooltip_style = _build_tooltip_style_dict(resolved_style)
    script = (
        files("dbt_charts.core.render")
        / "templates"
        / "scripts"
        / "chart_interactivity.js"
    ).read_text(encoding="utf-8")
    script = script.replace('"__DCT_FONT_FAMILY__"', json.dumps(font_family))
    script = script.replace('"__DCT_TOOLTIP_STYLE__"', json.dumps(tooltip_style))
    return script.replace('"__DCT_NULL_DISPLAY__"', json.dumps(NULL_DISPLAY))


def generate_svg_chart_interactivity_script(
    resolved_style: "ResolvedStyle",
) -> str:
    """Embed the chart hover runtime into SVG output."""
    return embed_svg_script(generate_chart_interactivity_source(resolved_style))
