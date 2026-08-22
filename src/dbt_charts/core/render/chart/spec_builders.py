"""Shared Vega-Lite spec builder helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbt_charts.core.text.case import apply_case

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.style.theme import PaddingStyle
    from dbt_charts.core.text.case import CaseValue


def additive_padding(card_pad: float, chart_padding: PaddingStyle) -> dict[str, float]:
    """Add card_padding to per-family chart padding on each side independently.

    ``chart_padding`` is the per-family resolved padding — typically
    ``resolved_chart.layout_padding``, baked in at construction time. It
    already carries board → family fill via InheritSlot and any chart-local
    ``style.<family>.padding`` override merged in by ``build_chart_style_context``.
    Each side stacks ON TOP of card_padding so author-specified insets compose
    with the global card layout rather than replacing it. With no chart-local
    override and board default {0,0,0,0}, this collapses to a uniform
    card_pad on all four sides.
    """
    return {
        "left": card_pad + chart_padding.left,
        "right": card_pad + chart_padding.right,
        "top": card_pad + chart_padding.top,
        "bottom": card_pad + chart_padding.bottom,
    }


def bump_padding_bottom(spec: dict[str, Any], add_px: float) -> None:
    """Increase spec-level `padding.bottom` by add_px in place.

    Assumes the spec already carries a 4-key padding dict. Other sides are left alone.
    """
    padding = dict(spec["padding"])
    padding["bottom"] = float(padding.get("bottom", 0)) + add_px
    spec["padding"] = padding


def bump_padding_top(spec: dict[str, Any], add_px: float) -> None:
    """Increase spec-level `padding.top` by add_px in place.

    Symmetric counterpart to ``bump_padding_bottom`` — used when a strip
    is attached above the plot (``style.data_table.position: top``).
    """
    padding = dict(spec["padding"])
    padding["top"] = float(padding.get("top", 0)) + add_px
    spec["padding"] = padding


def set_chart_title(
    spec: dict[str, Any],
    title: str | None,
    subtitle: str | None = None,
    *,
    case: CaseValue | None = None,
) -> None:
    """Apply a standard title block when a title is present.

    ``case`` is a plain title-case value (``chart.title_style.font.case``),
    not a style bag — title-case is VL-presentation-only: ``chart.title``
    itself stays raw because it also backs non-VL consumers (e.g. the
    ``data-chart-title`` wire attribute) that emit the authored text as-is.
    Subtitle is not case-transformed — chart subtitles have always been
    emitted raw.
    """
    if title and case is not None and case != "none":
        title = apply_case(title, case)
    if title or subtitle:
        title_block: dict[str, Any] = {"text": title or ""}
        if subtitle:
            title_block["subtitle"] = subtitle
        spec["title"] = title_block


def tooltip_entry(
    field: str,
    field_type: str,
    *,
    title: str | None = None,
    format: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a tooltip field definition."""
    entry: dict[str, Any] = {"field": field, "type": field_type}
    if title is not None:
        entry["title"] = title
    if format is not None:
        entry["format"] = format
    entry.update(extra)
    return entry
