"""Normalized geoshape / choropleth map chart."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from dbt_charts.core.compile.models.style.authored import GeoshapeChartStylePatch

from ._base import _GeoChartFields


class GeoshapeChart(_GeoChartFields):
    """Normalized geoshape or choropleth map chart."""

    type: Literal["geoshape", "map"]
    style: GeoshapeChartStylePatch | None = Field(
        default=None, description="Chart-local style overrides."
    )
