"""Authored pie / donut chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from dbt_charts.core.compile.models.style.authored import PieChartStylePatch

from ._base import _ConditionalFormattingField, _RadialChartFields


class PieChart(_RadialChartFields, _ConditionalFormattingField):
    """Authored patch for pie and donut charts.

    Pie charts use theta (angular) and color (segment) channels.
    x/y/format/sort and other cartesian fields are not valid here.
    """

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["pie", "donut"], Field(description="Pie or donut chart type.")
    ]
    style: Annotated[
        PieChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides."),
    ]
