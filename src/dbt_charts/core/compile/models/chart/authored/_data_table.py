"""CHART.DATA_TABLE — attached mini-table primitive."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

from dbt_charts.core.compile.models.markers import Format
from dbt_charts.core.compile.models.primitives import FormatConfig
from dbt_charts.core.compile.models.schema_names import FormatAlias

ChartDataTableAggregateOp = Literal[
    "sum", "avg", "min", "max", "median", "count", "count_distinct"
]


class ChartDataTableSource(BaseModel):
    """A data_table row that reads a column's raw per-x value."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        description="Query column the row reads from (per-x raw value)."
    )
    format: Annotated[FormatAlias | str | FormatConfig | None, Format()] = Field(
        default=None,
        description="D3 format string or format config object. Optional; inherits the chart measure format when omitted and source matches chart.y.",
    )
    label: str | None = Field(
        default=None,
        description="Left-stub row label. Optional.",
    )


class ChartDataTableAggregate(BaseModel):
    """A data_table row that reads an aggregate of a column grouped by x."""

    model_config = ConfigDict(extra="forbid")

    aggregate: ChartDataTableAggregateOp = Field(
        description=(
            "Aggregate operation applied per x-group. One of: "
            "sum, avg, min, max, median, count, count_distinct. "
            "Exact names only — no aliases (spec G4)."
        ),
    )
    source: str = Field(
        description=(
            "Query column being aggregated. Always required alongside "
            "`aggregate:` (spec G2)."
        ),
    )
    format: Annotated[FormatAlias | str | FormatConfig | None, Format()] = Field(
        default=None,
        description="D3 format string or format config object for the aggregated value. Optional.",
    )
    label: str | None = Field(
        default=None, description="Column header label override for this row."
    )


class ChartDataTablePerSeries(BaseModel):
    """A data_table entry that expands into one row per color: series.

    When ``by_measure=True`` the entry expands into a single row reading the
    named y-field directly, without a color: channel.  This is the expansion
    mode for multi-y charts (``y: [revenue, margin]``) where each measure is
    its own y-axis series rather than a color-encoded pivot.
    """

    model_config = ConfigDict(extra="forbid")

    per_series: str = Field(
        description="Query column the row reads from (per-x, per-series value)."
    )
    by_measure: bool = Field(
        default=False,
        description=(
            "When True, expand one row reading the named measure field directly "
            "(no color: groupby). Required for multi-y charts where each measure "
            "is its own y-field rather than a color-encoded series."
        ),
    )
    label: str | None = Field(
        default=None,
        description=(
            "Row label displayed in the strip's label gutter. "
            "When None and by_measure=True, the per_series column name is used. "
            "Has no effect when by_measure=False (series name is the label)."
        ),
    )
    format: Annotated[FormatAlias | str | FormatConfig | None, Format()] = Field(
        default=None,
        description="D3 format string or format config object. Optional.",
    )


def _discriminate_entry(entry: Any) -> str | None:
    """Tag-selector for the ChartDataTableEntry tagged union."""
    if isinstance(entry, ChartDataTableAggregate):
        return "aggregate"
    if isinstance(entry, ChartDataTablePerSeries):
        return "per_series"
    if isinstance(entry, ChartDataTableSource):
        return "source"
    if isinstance(entry, dict):
        if "aggregate" in entry:
            return "aggregate"
        if "per_series" in entry:
            return "per_series"
        return "source"
    return None


ChartDataTableEntry = Annotated[
    Annotated[ChartDataTableSource, Tag("source")]
    | Annotated[ChartDataTableAggregate, Tag("aggregate")]
    | Annotated[ChartDataTablePerSeries, Tag("per_series")],
    Discriminator(_discriminate_entry),
]


class ChartDataTable(BaseModel):
    """Container for a chart's data_table block."""

    model_config = ConfigDict(extra="forbid")

    entries: list[ChartDataTableEntry] = Field(
        min_length=1,
        description="List of data-table entries (source, aggregate, or per-series rows).",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"entries": data}
        return data


CHART_DATA_TABLE_SUPPORTED_TYPES: frozenset[str] = frozenset({"bar", "line", "area"})


def validate_data_table_shape(entries: list[ChartDataTableEntry]) -> None:
    """Data-free validation of a data_table entry list (spec §3.2)."""
    seen: set[tuple[str, str | None, bool]] = set()
    for entry in entries:
        if isinstance(entry, ChartDataTablePerSeries):
            key: tuple[str, str | None, bool] = (entry.per_series, None, True)
            if key in seen:
                raise ValueError(
                    f"chart.data_table has duplicate per_series entries for "
                    f"{{per_series: {entry.per_series!r}}}. "
                    "Remove the duplicate."
                )
            seen.add(key)
            continue
        agg = entry.aggregate if isinstance(entry, ChartDataTableAggregate) else None
        source = entry.source
        normal_key: tuple[str, str | None, bool] = (source, agg, False)
        if normal_key in seen:
            label = (
                f"{{aggregate: {agg}, source: {source}}}"
                if agg is not None
                else f"{{source: {source}}}"
            )
            raise ValueError(
                f"chart.data_table has duplicate entries for {label}. "
                "Remove the duplicate or differentiate by aggregate operation."
            )
        seen.add(normal_key)
