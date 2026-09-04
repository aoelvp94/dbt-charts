"""Authored scatter chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.markers import Channel
from dbt_charts.core.compile.models.style.authored import ScatterChartStylePatch

from ._base import _CartesianChartFields, _ConditionalFormattingField
from ._layer import CartesianLayer


class ScatterChart(_CartesianChartFields, _ConditionalFormattingField):
    """Authored patch for scatter charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["scatter"], Field(description="Selects the chart family.")]
    size: Annotated[
        str | None,
        Channel(),
        Field(
            default=None,
            description="Column used to size-encode data points (quantitative).",
        ),
    ]
    shape: Annotated[
        str | None,
        Channel(),
        Field(
            default=None,
            description="Column used to shape-encode data points (categorical).",
        ),
    ]
    style: Annotated[
        ScatterChartStylePatch | None,
        Field(default=None, description="Appearance overrides for this chart alone."),
    ]
    layers: Annotated[
        list[CartesianLayer] | None,
        Field(
            default=None,
            description="Extra marks drawn over this chart, each with its own type and columns.",
        ),
    ]
