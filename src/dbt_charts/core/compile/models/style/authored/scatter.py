"""Scatter chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import ScatterChartStyle

if TYPE_CHECKING:

    class ScatterChartStylePatch(ScatterChartStyle):  # noqa: F811
        pass

else:
    ScatterChartStylePatch = build_patch_model(ScatterChartStyle)
