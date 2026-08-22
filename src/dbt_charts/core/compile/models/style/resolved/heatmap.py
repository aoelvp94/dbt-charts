"""Heatmap family resolved style slice."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.primitives import ResolvedScaleTarget
from dbt_charts.core.compile.models.style.theme import RectMarkStyle

from ._cartesian import _CartesianResolvedStyle


class ResolvedHeatmapStyle(_CartesianResolvedStyle):
    """Heatmap family style slice — self-contained, globals merged down.

    Inherits axis_x, axis_y, tooltip_format from _CartesianResolvedStyle.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    color_gradient: ResolvedScaleTarget | None = Field(
        default=None,
        description="Gradient scale config for the heatmap color encoding (palette/scheme + domain).",
    )
    rect_mark: RectMarkStyle = Field(
        description="Cascade-merged rect mark geometry (opacity, stroke)."
    )
    label_usable_ratio: float = Field(
        description="Usable-width ratio for the categorical-axis overlap heuristic."
    )


__all__ = ["ResolvedHeatmapStyle"]
