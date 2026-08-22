"""Area chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import AreaChartStyle

if TYPE_CHECKING:

    class AreaChartStylePatch(AreaChartStyle):  # noqa: F811
        pass

else:
    AreaChartStylePatch = build_patch_model(AreaChartStyle)
