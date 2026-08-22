"""describe_query verb — return column schema for a SQL string without fetching rows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.execute.adapters import AdapterRegistry
from dbt_charts.core.execute.adapters.dbt_adapter_factory import build_adapter
from dbt_charts.core.inspect.query_validator import validate_query


class DescribeQueryArgs(BaseModel):
    """Return the column schema (names + types) for a SQL string without executing it for data.

    Gates on validate_query first — short-circuits on parse errors and missing join
    predicates with actionable diagnostics; otherwise returns columns alongside any
    non-error diagnostics (e.g. WARN-FANOUT-RISK warnings) so the agent can read them
    without being blocked from the column shape.
    """

    sql: str = Field(..., description="SQL query to describe.")
    source: str | None = Field(
        None, description="Data source name to describe against."
    )
    dialect: str | None = Field(
        None, description="SQL dialect hint for the validator (duckdb, bigquery, etc.)."
    )


class DescribeQueryColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    char_size: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None


class DescribeQueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    columns: list[DescribeQueryColumn] | None = None
    diagnostics: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Dialect-specific diagnostic messages from the query runner.",
    )
    error: str | None = None


def describe_query(
    sql: str,
    *,
    source: str | None = None,
    dialect: str | None = None,
    adapter_registry: AdapterRegistry,
) -> DescribeQueryResult:
    """Return the column schema for a SQL string using the dbt adapter.

    Runs validate_query first; short-circuits on error-severity diagnostics
    (WARN-PARSE-ERROR, WARN-MISSING-JOIN-PREDICATE) without calling the warehouse.
    Non-error diagnostics are surfaced on the result alongside the column schema.
    """
    try:
        diags = validate_query(sql, dialect=dialect)

        error_diags = [d for d in diags if d.severity == "error"]
        if error_diags:
            return DescribeQueryResult(
                success=False,
                columns=None,
                diagnostics=[d.to_dict() for d in diags],
                error=error_diags[0].message,
            )

        cfg = adapter_registry.resolve_source_config(source)

        if cfg.get("type") == "duckdb":
            # Run DESCRIBE via the registry's existing read-only DuckDBAdapter so
            # we don't open a writable dbt-duckdb connection that would conflict
            # with dct serve.
            cols = _duckdb_describe(sql, source, adapter_registry)
        else:
            adapter = build_adapter(cfg, read_only=True)
            with adapter.connection_named("dbt_charts_describe"):
                raw = adapter.get_column_schema_from_query(sql)
            cols = [
                DescribeQueryColumn(
                    name=c.name,
                    type=c.dtype,
                    char_size=c.char_size,
                    numeric_precision=c.numeric_precision,
                    numeric_scale=c.numeric_scale,
                )
                for c in raw
            ]

        return DescribeQueryResult(
            success=True,
            columns=cols,
            diagnostics=[d.to_dict() for d in diags],
        )

    except Exception as e:  # noqa: BLE001 — adapter boundary, mirrors execute_query
        return DescribeQueryResult(
            success=False,
            error=str(e),
        )


def _duckdb_describe(
    sql: str, source: str | None, adapter_registry: AdapterRegistry
) -> list[DescribeQueryColumn]:
    """Run DESCRIBE ({sql}) via the registry's read-only DuckDBAdapter."""
    result = adapter_registry.execute(SqlQuery(sql=f"DESCRIBE ({sql})", source=source))
    if result.error:
        raise RuntimeError(result.error)
    return [
        DescribeQueryColumn(name=row["column_name"], type=row["column_type"])
        for row in result.data
    ]
