"""Shared chart title overflow helpers."""

from __future__ import annotations

import re
from typing import Any, Literal

from dbt_charts.core.font_measure import get_font_measurer
from dbt_charts.core.render.chart.text_truncation import record_text_truncation
from mdsvg.fonts import wrap_text_precise

TitleOverflowMode = Literal["clip", "truncate", "wrap-two", "wrap"]
DEFAULT_TITLE_OVERFLOW: TitleOverflowMode = "wrap-two"

# Match the outer Vega chart-group translate, e.g. translate(20,53)
_MAIN_GROUP_X_RE = re.compile(
    r'<g fill="none" stroke-miterlimit="10" transform="translate\(([0-9.]+),'
)
# Match the title inner-group translate, e.g. translate(-71.21,-48)
_TITLE_GROUP_RE = re.compile(
    r'(class="mark-group role-title"><g transform="translate\()(-?[0-9.]+)(,)'
)


def resolve_title_overflow(title_style: Any | None) -> TitleOverflowMode:
    """Return the effective title overflow mode."""
    raw = getattr(title_style, "overflow", None) if title_style is not None else None
    if raw in {"clip", "truncate", "wrap-two", "wrap"}:
        return raw
    return DEFAULT_TITLE_OVERFLOW


def compute_title_limit(width: Any, padding: Any) -> int | None:
    """Return the usable title width after horizontal padding."""
    if not isinstance(width, (int, float)) or width <= 0:
        return None

    left = right = 0.0
    if isinstance(padding, dict):
        left = float(padding.get("left", 0) or 0)
        right = float(padding.get("right", 0) or 0)
    elif isinstance(padding, (int, float)):
        left = right = float(padding)

    limit = int(width - left - right)
    return max(limit, 1) if limit > 0 else None


def prepare_title_text(
    text: str,
    *,
    overflow: TitleOverflowMode,
    limit: int | None,
    font_size: float,
    font_family: str | None = None,
) -> tuple[str, bool]:
    """Return ``(processed_text, truncated)`` with line breaks/clipping applied.

    ``truncated`` is the mdsvg-level flag — immune to authored ellipses and
    whitespace normalization. Only True when the library actually cut text.
    """
    if not text or limit is None:
        return text, False

    measurer = get_font_measurer(font_family)
    if overflow == "clip":
        lines, truncated = wrap_text_precise(
            text, limit, font_size, measurer, max_lines=1, ellipsis=False
        )
        return lines[0] if lines else text, truncated
    if overflow == "truncate":
        lines, truncated = wrap_text_precise(
            text, limit, font_size, measurer, max_lines=1, ellipsis=True
        )
        return lines[0] if lines else text, truncated
    if overflow == "wrap":
        lines, _ = wrap_text_precise(text, limit, font_size, measurer)
        return "\n".join(lines), False
    lines, truncated = wrap_text_precise(
        text, limit, font_size, measurer, max_lines=2, ellipsis=True
    )
    return "\n".join(lines), truncated


def apply_title_overflow_to_spec(
    spec: dict[str, Any],
    title_style: Any | None,
    *,
    chart_id: str = "",
    title_font_size: float | None = None,
    title_font_family: str | None = None,
    available_width: float | None = None,
) -> None:
    """Apply title and subtitle overflow handling to a Vega-Lite spec in place.

    ``available_width`` overrides ``spec["width"]`` as the basis for the
    title/subtitle limit. Needed for hconcat endpoint-label panes: vl-convert
    ignores ``autosize: fit`` on concat children, so pane[0]["width"] there is
    the *data-plot* width alone — the y-axis tick-label gutter renders outside
    it. Vega positions the title/subtitle across that whole visual footprint
    (gutter + plot), not just the plot rect, so callers that know the pane's
    true footprint (target width minus sibling panes, spacing, and the concat
    root's own padding) should pass it here instead of letting this function
    under-count from ``width`` alone.
    """
    title_block = spec.get("title")
    if not isinstance(title_block, dict):
        return

    width_basis = available_width if available_width is not None else spec.get("width")
    limit = compute_title_limit(width_basis, spec.get("padding"))
    if limit is None:
        return

    title_block["limit"] = limit

    style_font_size = (
        getattr(getattr(title_style, "font", None), "size", None)
        if title_style is not None
        else None
    )
    config_font_size = spec.get("config", {}).get("title", {}).get("fontSize")
    effective_title_font_size = float(
        style_font_size or title_font_size or config_font_size or 18
    )

    text = title_block.get("text")
    if isinstance(text, str) and text:
        title_overflow = resolve_title_overflow(title_style)
        result, title_truncated = prepare_title_text(
            text,
            overflow=title_overflow,
            limit=limit,
            font_size=effective_title_font_size,
            font_family=title_font_family,
        )
        if chart_id and title_truncated:
            record_text_truncation(chart_id, "chart_title", text, "title")
        lines = result.split("\n")
        title_block["text"] = lines if len(lines) > 1 else result

    subtitle = title_block.get("subtitle")
    if isinstance(subtitle, str) and subtitle:
        subtitle_style = (
            getattr(title_style, "subtitle", None) if title_style is not None else None
        )
        subtitle_font_size = float(
            getattr(getattr(subtitle_style, "font", None), "size", None)
            or effective_title_font_size
        )
        subtitle_overflow = resolve_title_overflow(subtitle_style)
        subtitle_result, subtitle_truncated = prepare_title_text(
            subtitle,
            overflow=subtitle_overflow,
            limit=limit,
            font_size=subtitle_font_size,
            font_family=title_font_family,
        )
        if chart_id and subtitle_truncated:
            record_text_truncation(chart_id, "chart_title", subtitle, "subtitle")
        subtitle_lines = subtitle_result.split("\n")
        title_block["subtitle"] = (
            subtitle_lines if len(subtitle_lines) > 1 else subtitle_result
        )


def fix_title_alignment(svg: str, padding_left: float) -> str:
    """Move the Vega-rendered title right to ``padding_left`` when leftward drift occurs."""
    main_match = _MAIN_GROUP_X_RE.search(svg)
    if not main_match:
        return svg

    title_match = _TITLE_GROUP_RE.search(svg)
    if not title_match:
        return svg

    main_x = float(main_match.group(1))
    title_x = float(title_match.group(2))
    title_svg_x = main_x + title_x

    if title_svg_x >= padding_left:
        return svg

    new_title_x = padding_left - main_x
    old = title_match.group(1) + title_match.group(2) + title_match.group(3)
    new = title_match.group(1) + f"{new_title_x:.2f}" + title_match.group(3)
    return svg.replace(old, new, 1)
