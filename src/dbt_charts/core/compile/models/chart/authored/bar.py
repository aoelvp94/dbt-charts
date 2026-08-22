"""Authored bar / histogram chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

from ._base import (
    _CartesianChartFields,
    _ConditionalFormattingField,
    reject_multi_series_channel_conflicts,
)
from ._layer import CartesianLayer


class BarChart(_CartesianChartFields, _ConditionalFormattingField):
    """Authored patch for bar and histogram charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["bar", "histogram"], Field(description="Bar or histogram chart type.")
    ]
    style: Annotated[
        BarChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides."),
    ]
    layers: Annotated[
        list[CartesianLayer] | None,
        Field(default=None, description="Typed overlay layers on this chart."),
    ]

    @model_validator(mode="after")
    def _validate_multi_series(self) -> BarChart:
        # A histogram bins x and derives its measure by counting, so it never
        # reads y at all — the emitter returns into the histogram path before
        # the multi-metric branch. None of these conflicts apply to it.
        if self.type != "bar":
            return self
        reject_multi_series_channel_conflicts(
            "Bar", self.y, self.color, self.layers, self.conditional_formatting
        )
        # Folded measures are grouped side by side within each x band; without
        # an x there are no bands to group them into.
        if isinstance(self.y, list) and self.x is None:
            raise ValueError(
                "Bar chart: multi-metric (y: [...]) charts require an x field."
            )
        return self
