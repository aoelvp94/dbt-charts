"""Heatmap chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import HeatmapChartStyle

if TYPE_CHECKING:

    class HeatmapChartStylePatch(HeatmapChartStyle):  # noqa: F811
        pass

else:
    HeatmapChartStylePatch = build_patch_model(HeatmapChartStyle)
