"""Point map chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import PointMapChartStyle

if TYPE_CHECKING:

    class PointMapChartStylePatch(PointMapChartStyle):  # noqa: F811
        pass

else:
    PointMapChartStylePatch = build_patch_model(PointMapChartStyle)
