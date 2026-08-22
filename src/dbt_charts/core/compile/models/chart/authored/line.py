"""Authored line chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.style.authored import LineChartStylePatch

from ._base import _CartesianChartFields, _ConditionalFormattingField
from ._layer import CartesianLayer


class LineChart(_CartesianChartFields, _ConditionalFormattingField):
    """Authored patch for line charts.

    Intentionally excludes size, and shape — these channels are structurally
    impossible on line charts. An attempt to set them raises extra_forbidden.
    """

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["line"], Field(description="Line chart type.")]
    style: Annotated[
        LineChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides."),
    ]
    layers: Annotated[
        list[CartesianLayer] | None,
        Field(default=None, description="Typed overlay layers on this chart."),
    ]
