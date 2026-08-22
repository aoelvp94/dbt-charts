"""Resolved line/area mark builders and label-format helpers."""

from __future__ import annotations

from typing import Any, TypeVar

from dbt_charts.core.compile.format import resolve_format, resolve_label_format
from dbt_charts.core.compile.models.chart.normalized import (
    Chart,
)
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import (
    ResolvedAreaLineStyle,
    ResolvedAreaMarkStyle,
    ResolvedLineMarkStyle,
    ResolvedStrokeStyle,
)
from dbt_charts.core.compile.models.style.theme import (
    AreaLineStyle,
    AreaMarkStyle,
    LineMarkStyle,
    MarkLabelsStyle,
)
from dbt_charts.core.compile.resolve.style.chart_context import (
    chart_authored_axis_format,
)

__all__ = [
    "_build_resolved_area_line",
    "_build_resolved_area_mark",
    "_build_resolved_line_mark",
    "_label_format_fallback",
    "_measure_tooltip_format",
]


def _measure_tooltip_format(
    normalized: Chart,
    primary: Any,
    chart_style_context: ChartStyleContext,
    y_channel_type: str = "quantitative",
) -> str | None:
    """Resolve the chart-authored measure (y-axis) tooltip format, if any.

    Precedence: chart_authored_axis_format (style.number_format / chart.format)
    → the already-baked axis_y.format. Returns None when neither is set, so
    callers fall back to the board default tooltip format themselves.
    ``y_channel_type`` matters for scatter, whose y can be nominal (dot plot) —
    chart_authored_axis_format returns None for non-quantitative/temporal
    channels, so a nominal y correctly skips the measure-format fallback.
    """
    fmt = chart_authored_axis_format(normalized, y_channel_type)
    if (
        fmt is None
        and primary is not None
        and primary.axis_y is not None
        and primary.axis_y.labels is not None
    ):
        fmt = primary.axis_y.labels.format
    return resolve_format(fmt, chart_style_context.formats) if fmt else None


_LabelsT = TypeVar("_LabelsT", bound=MarkLabelsStyle)


def _label_format_fallback(
    labels: _LabelsT,
    axis_format: str | None,
    axis_is_house: bool,
    formats: dict[str, str] | None,
) -> tuple[_LabelsT, bool]:
    """Fall an unset value-label format back to the resolved measure-axis format.

    Returns ``(updated_labels, is_house)`` where ``is_house`` controls whether
    the render layer wraps the SI format in the narrative register (1.2mn) or
    passes it straight to Vega (raw d3: 1.2M).

    An explicit label format is decided by predefined-membership alone
    (``resolve_label_format``): a raw format string that is an engine-
    predefined name (``ALL_PREDEFINED_NAMES``) takes house rules; a
    ``style.formats`` alias or a literal d3 spec is a native opt-out
    (``is_house=False``). The fallback branch (no label format authored) instead inherits
    ``axis_is_house`` as callers compute it — ``is_d3_si_spec(axis_format) and
    (not axis_format_authored or axis_format_is_alias)`` — the same
    authored-or-alias rule axis itself uses for its non-compacting tick label,
    since inheriting a label must agree with what its own axis renders,
    including the axis's own authored-literal escape hatch.

    Unlike ``axis_format`` (already resolved via ``resolve_format``), an explicit
    ``labels.format`` passes through ``resolve_label_format`` for both alias
    resolution and round-aware trimming — so ``format: currency`` resolves to
    ``$,.2f`` here, not the literal alias key.
    """
    if labels.format is not None:
        resolved, is_house = resolve_label_format(labels.format, formats)
        return labels.model_copy(update={"format": resolved}), is_house
    if axis_format is None:
        return labels, False
    return labels.model_copy(update={"format": axis_format}), axis_is_house


def _build_resolved_line_mark(merged: LineMarkStyle) -> ResolvedLineMarkStyle:
    """Build a ResolvedLineMarkStyle from an already-merged LineMarkStyle."""
    if merged.stroke is None or merged.stroke.width is None:
        raise ValueError(
            "line.marks.line.stroke.width is None after cascade — check theme defaults"
        )
    if merged.halo_multiplier is None:
        raise ValueError(
            "line.marks.line.halo_multiplier is None after cascade — check theme defaults"
        )
    return ResolvedLineMarkStyle(
        stroke=ResolvedStrokeStyle(
            width=merged.stroke.width,
            color=merged.stroke.color,
            cap=merged.stroke.cap,
            join=merged.stroke.join,
            dasharray=merged.stroke.dasharray,
        ),
        halo_multiplier=merged.halo_multiplier,
        curve=merged.curve,
        connect=merged.connect,
        disconnected_cap=merged.disconnected_cap,
        labels=merged.labels,
    )


def _build_resolved_area_mark(merged: AreaMarkStyle) -> ResolvedAreaMarkStyle:
    """Build a ResolvedAreaMarkStyle (fill only) from an already-merged AreaMarkStyle."""
    if merged.opacity is None:
        raise ValueError(
            "area.marks.area.opacity is None after cascade — check theme defaults"
        )
    if merged.backdrop is None:
        raise ValueError(
            "area.marks.area.backdrop is None after cascade — check theme defaults"
        )
    return ResolvedAreaMarkStyle(
        opacity=merged.opacity, curve=merged.curve, backdrop=merged.backdrop
    )


def _build_resolved_area_line(merged: AreaLineStyle) -> ResolvedAreaLineStyle:
    """Build a ResolvedAreaLineStyle from an already-merged AreaLineStyle.

    Area's top-edge line: stroke/halo geometry + value labels. Mirrors
    _build_resolved_line_mark minus curve/connect (owned solely by
    ResolvedAreaMarkStyle.curve — see AreaLineStyle's docstring).
    """
    if merged.stroke is None or merged.stroke.width is None:
        raise ValueError(
            "area.marks.line.stroke.width is None after cascade — check theme defaults"
        )
    if merged.halo_multiplier is None:
        raise ValueError(
            "area.marks.line.halo_multiplier is None after cascade — check theme defaults"
        )
    return ResolvedAreaLineStyle(
        stroke=ResolvedStrokeStyle(
            width=merged.stroke.width,
            color=merged.stroke.color,
            cap=merged.stroke.cap,
            join=merged.stroke.join,
            dasharray=merged.stroke.dasharray,
        ),
        halo_multiplier=merged.halo_multiplier,
        labels=merged.labels,
    )
