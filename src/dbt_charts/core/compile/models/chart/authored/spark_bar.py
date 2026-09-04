"""Authored spark_bar chart (compact horizontal bars)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.markers import Channel
from dbt_charts.core.compile.models.style.authored import SparkBarChartStylePatch

from ._base import _SharedChartFields


class SparkBarChart(_SharedChartFields):
    """Authored patch for spark_bar charts (compact horizontal bars)."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[
        Literal["spark_bar"], Field(description="Selects the chart family.")
    ]
    # None = auto-detected from query columns.
    x: Annotated[
        str | None,
        Channel(),
        Field(default=None, description="Bar-magnitude (numeric) column name."),
    ]
    y: Annotated[
        str | list[str] | None,
        Channel(),
        Field(default=None, description="Bar-label (category) column name(s)."),
    ]
    style: Annotated[
        SparkBarChartStylePatch | None,
        Field(default=None, description="Appearance overrides for this chart alone."),
    ]

    @model_validator(mode="after")
    def _validate_single_series(self) -> SparkBarChart:
        # A spark bar is one row of bars against one label column; there is no
        # second encoding to separate a second series by.
        if isinstance(self.y, list) and len(self.y) != 1:
            raise ValueError(
                f"SparkBar chart requires a single y column; got {len(self.y)}: "
                f"{self.y!r}. Use one y field per spark_bar chart."
            )
        return self
