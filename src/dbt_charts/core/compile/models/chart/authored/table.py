"""Authored table chart."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from dbt_charts.core.compile.models.markers import Channel
from dbt_charts.core.compile.models.style.authored import TableChartStylePatch

from ._base import _ConditionalFormattingField, _SharedChartFields


class TableChart(_SharedChartFields, _ConditionalFormattingField):
    """Authored patch for table charts."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["table"], Field(description="Table chart type.")]
    style: Annotated[
        TableChartStylePatch | None,
        Field(default=None, description="Chart-local style overrides."),
    ]
    rows: Annotated[
        list[str] | None,
        Channel(),
        Field(
            default=None,
            description=(
                "Fields whose distinct values form the row dimension of a pivot cross-tab. "
                "Each string is a column name from the query result. "
                "Omit for flat (non-pivot) tables."
            ),
        ),
    ]
    columns: Annotated[
        list[str] | None,
        Channel(),
        Field(
            default=None,
            description=(
                "Fields whose distinct values become column headers in a pivot cross-tab. "
                "Multiple fields create a nested multi-dimension pivot (outer → inner). "
                "Omit for flat tables."
            ),
        ),
    ]
    values: Annotated[
        list[str] | None,
        Channel(),
        Field(
            default=None,
            description=(
                "Measure fields that fill pivot cells. "
                "Each string is a column name from the query result. "
                "When omitted, all query columns not claimed by rows or columns are used."
            ),
        ),
    ]

    @model_validator(mode="after")
    def _validate_pivot_channels(self) -> TableChart:
        # A field may appear on at most one channel.
        seen: dict[str, str] = {}
        for channel, fields in (
            ("rows", self.rows or []),
            ("columns", self.columns or []),
            ("values", self.values or []),
        ):
            for f in fields:
                if f in seen:
                    raise ValueError(
                        f"Field {f!r} appears on both '{seen[f]}' and '{channel}' channels. "
                        "A field may appear on at most one of rows/columns/values."
                    )
                seen[f] = channel
        return self
