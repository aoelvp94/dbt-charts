"""Authored heatmap chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.style.authored import HeatmapChartStylePatch

from ._base import _CartesianChartFields


class HeatmapChart(_CartesianChartFields):
    """Authored patch for heatmap charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["heatmap"], Field(description="Selects the chart family.")]
    style: Annotated[
        HeatmapChartStylePatch | None,
        Field(default=None, description="Appearance overrides for this chart alone."),
    ]
