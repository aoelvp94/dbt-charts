"""Callout chart authored style patch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import CalloutChartStyle

if TYPE_CHECKING:

    class CalloutChartStylePatch(CalloutChartStyle):  # noqa: F811
        pass

else:
    CalloutChartStylePatch = build_patch_model(CalloutChartStyle)
