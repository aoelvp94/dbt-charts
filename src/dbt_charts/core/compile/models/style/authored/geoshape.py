"""Geoshape (choropleth map) chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import GeoshapeChartStyle

if TYPE_CHECKING:

    class GeoshapeChartStylePatch(GeoshapeChartStyle):  # noqa: F811
        pass

else:
    GeoshapeChartStylePatch = build_patch_model(GeoshapeChartStyle)
