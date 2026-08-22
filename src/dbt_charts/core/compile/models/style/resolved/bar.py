"""Bar family resolved style slice."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.primitives import OverlapSpec
from dbt_charts.core.compile.models.style.theme import BarMarkStyle

from ._cartesian import _SeriesCartesianResolvedStyle


class ResolvedBarStyle(_SeriesCartesianResolvedStyle):
    """Bar family style slice — self-contained, globals merged down.

    Every field is concrete after resolve; the bar emitter reads only these.
    Inherits axis_x, axis_y, tooltip_format, series_label,
    endpoint_labels, single_series_fill, label_usable_ratio
    from the cartesian base hierarchy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stack_order: Literal["value", "data", "alphabetical"] | None = Field(
        default=None,
        description=(
            "Z-order of stacked bar segments. "
            "None / 'value' = largest at bottom (VL default)."
        ),
    )
    mark: BarMarkStyle = Field(
        description="Cascade-merged bar mark geometry (padding, size, labels).",
    )
    overlap: OverlapSpec = Field(
        default=None,
        description=(
            "Within-group spacing for grouped bars (resolved from chart-local "
            "style → theme bar default). None → renderer 'auto'."
        ),
    )
    label_is_house: bool = Field(
        default=False,
        description=(
            "True when the bar segment label format should use the house narrative "
            "register (1.2mn). False when the author wrote a literal d3 SI spec."
        ),
    )
    # Required, not Optional: every theme resolves the text-mark size and the
    # inherit cascade refills an explicitly nulled one, so a None here is a
    # broken cascade for the resolver to name — not a state render tiptoes past.
    label_font_size: float = Field(
        description=(
            "Effective value-label font size in px: mark.labels.font.size when "
            "authored, else the board's text-mark size."
        ),
    )
    total_label_is_house: bool = Field(
        default=False,
        description=(
            "True when the bar total label format should use the house narrative "
            "register. Mirrors label_is_house for the separate total-label call site."
        ),
    )


__all__ = ["ResolvedBarStyle"]
