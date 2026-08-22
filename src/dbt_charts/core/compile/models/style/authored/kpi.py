"""KPI chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model_ext
from dbt_charts.core.compile.models.style.theme import KpiChartStyle

if TYPE_CHECKING:

    class KpiChartStylePatch(KpiChartStyle):  # noqa: F811
        pass

else:
    KpiChartStylePatch = build_patch_model_ext(KpiChartStyle)
