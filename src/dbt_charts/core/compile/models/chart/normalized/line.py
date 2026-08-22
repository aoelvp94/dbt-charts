"""Normalized line chart."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from dbt_charts.core.compile.models.chart.authored._layer import CartesianLayer
from dbt_charts.core.compile.models.style.authored import LineChartStylePatch

from ._base import _CartesianChartFields


class LineChart(_CartesianChartFields):
    """Normalized line chart."""

    type: Literal["line"]
    style: LineChartStylePatch | None = Field(
        default=None, description="Chart-local style overrides."
    )
    layers: list[CartesianLayer] = Field(
        default_factory=list, description="Typed overlay layers on this chart."
    )
