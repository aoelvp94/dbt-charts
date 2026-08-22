"""Pie/donut chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import PieChartStyle

if TYPE_CHECKING:

    class PieChartStylePatch(PieChartStyle):  # noqa: F811
        pass

else:
    PieChartStylePatch = build_patch_model(PieChartStyle)
