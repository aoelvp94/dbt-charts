"""Normalized table chart."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from dbt_charts.core.compile.models.style.authored import TableChartStylePatch

from ._base import _SharedChartFields


class TableChart(_SharedChartFields):
    """Normalized table chart.

    filters, conditional_formatting, link, and description are inherited
    from _BaseChartFields and not re-declared here.
    """

    type: Literal["table"]
    rows: list[str] | None = Field(
        default=None, description="Pivot row dimension fields."
    )
    columns: list[str] | None = Field(
        default=None, description="Pivot column dimension fields."
    )
    values: list[str] | None = Field(default=None, description="Pivot measure fields.")
    height: int | float | None = Field(
        default=None, description="Explicit chart height in pixels."
    )
    width: int | float | None = Field(
        default=None, description="Explicit chart width in pixels."
    )
    min_height: float | None = Field(default=None, description="Minimum height floor.")
    max_height: float | None = Field(
        default=None, description="Maximum height ceiling."
    )
    style: TableChartStylePatch | None = Field(
        default=None, description="Chart-local style overrides."
    )
