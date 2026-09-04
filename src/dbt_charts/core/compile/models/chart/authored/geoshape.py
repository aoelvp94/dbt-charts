"""Authored map / geoshape chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.style.authored import GeoshapeChartStylePatch

from ._base import _ConditionalFormattingField, _GeoChartFields


class GeoshapeChart(_GeoChartFields, _ConditionalFormattingField):
    """Authored patch for map and geoshape charts; the two type spellings are synonyms."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["map", "geoshape"],
        Field(description="Selects the chart family."),
    ]
    style: Annotated[
        GeoshapeChartStylePatch | None,
        Field(default=None, description="Appearance overrides for this chart alone."),
    ]
