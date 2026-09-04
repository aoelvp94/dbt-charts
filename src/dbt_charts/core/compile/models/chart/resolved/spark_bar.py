"""Resolved spark_bar chart model."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from dbt_charts.core.compile.models.chart.authored import ChartSort
from dbt_charts.core.compile.models.style.resolved import ResolvedSparkBarStyle

from ._base import _SharedResolvedChartFields


class ResolvedSparkBarChart(_SharedResolvedChartFields):
    """Render-ready spark bar chart."""

    chart_type: Literal["spark_bar"] = Field(
        description="Discriminator key; always 'spark_bar'.",
    )
    x: str | None = Field(
        default=None,
        description="Bar-magnitude (numeric) column.",
    )
    y: str | None = Field(
        default=None,
        description="Bar-label (category) column.",
    )
    color: str | None = Field(
        default=None,
        description="Color-encoding column.",
    )
    sort: ChartSort | None = Field(
        default=None,
        description="Sort config.",
    )
    style: ResolvedSparkBarStyle = Field(
        description="SparkBar family style slice.",
    )
