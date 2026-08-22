"""Authored area chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.style.authored import AreaChartStylePatch

from ._base import (
    _CartesianChartFields,
    _ConditionalFormattingField,
    reject_multi_series_channel_conflicts,
)
from ._layer import CartesianLayer


class AreaChart(_CartesianChartFields, _ConditionalFormattingField):
    """Authored patch for area charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["area"], Field(description="Area chart type.")]
    style: Annotated[
        AreaChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides."),
    ]
    layers: Annotated[
        list[CartesianLayer] | None,
        Field(default=None, description="Typed overlay layers on this chart."),
    ]

    @model_validator(mode="after")
    def _validate_multi_series(self) -> AreaChart:
        reject_multi_series_channel_conflicts(
            "Area", self.y, self.color, self.layers, self.conditional_formatting
        )
        return self
