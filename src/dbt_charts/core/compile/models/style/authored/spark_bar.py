"""Spark bar chart authored style patches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbt_charts.core.compile.models.factories import build_patch_model
from dbt_charts.core.compile.models.style.theme import (
    SparkBarBarStyle,
    SparkBarChartLabelStyle,
    SparkBarChartStyle,
    SparkBarCountStyle,
)

SparkBarBarStylePatch = build_patch_model(SparkBarBarStyle)
SparkBarChartLabelStylePatch = build_patch_model(SparkBarChartLabelStyle)
SparkBarCountStylePatch = build_patch_model(SparkBarCountStyle)

if TYPE_CHECKING:

    class SparkBarChartStylePatch(SparkBarChartStyle):  # noqa: F811
        pass

else:
    SparkBarChartStylePatch = build_patch_model(SparkBarChartStyle)
