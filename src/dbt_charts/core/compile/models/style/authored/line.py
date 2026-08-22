"""Line chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import LineChartStyle

if TYPE_CHECKING:

    class LineChartStylePatch(LineChartStyle):  # noqa: F811
        pass

else:
    LineChartStylePatch = build_patch_model(LineChartStyle)
