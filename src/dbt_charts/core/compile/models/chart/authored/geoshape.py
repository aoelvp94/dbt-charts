"""Authored map / geoshape chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.style.authored import GeoshapeChartStylePatch

from ._base import _ConditionalFormattingField, _GeoChartFields


class GeoshapeChart(_GeoChartFields, _ConditionalFormattingField):
    """Authored patch for map and geoshape charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["map", "geoshape"], Field(description="Map or geoshape chart type.")
    ]
    style: Annotated[
        GeoshapeChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides."),
    ]
