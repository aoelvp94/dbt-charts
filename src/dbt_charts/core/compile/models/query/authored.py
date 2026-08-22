"""Authored query types — YAML input representation.

Stage: COMPILE (Input)
Purpose: Types that map directly to the YAML query schema.

AuthoredQuery is a discriminated union over per-type models (the chart-family
pattern): each query type carries only its own fields with ``extra="forbid"``,
so cross-type field misuse (``pivots:`` on a ``type: sql`` query) fails at
parse time. The ``type`` discriminator is stamped before validation by
``normalize_query_value`` (refs.py), which infers it from key presence when
the author omits it.

These live here (separate from board/authored.py) because:
- Discriminated-union models (board/authored.py) import AuthoredQuery via QueryOrRef.
- Keeping AuthoredQuery here avoids the discriminated-union module importing itself.
"""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
)

from dbt_charts.core.compile.models.cache import CachePatch
from dbt_charts.core.diagnostics.suppression import validate_suppression_codes

# ============================================================================
# QUERY-LEVEL PRIMITIVES (used by both authored and compiled layers)
# ============================================================================

TimeGrain = Literal["day", "week", "month", "quarter", "year"]

RestMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


# ============================================================================
# AUTHORED QUERY MODELS — one class per query type, discriminated on `type`
# ============================================================================


class _BaseQueryFields(BaseModel):
    """Fields shared by every authored query type.

    Use ``isinstance(obj, _BaseQueryFields)`` to check whether an object is an
    authored query instance — ``AuthoredQuery`` is a union alias, not a class.
    """

    model_config = ConfigDict(extra="forbid")

    # Source name reference or inline file path (e.g. ./data/sales.csv). The dict
    # branch is authored-stage-only: it must NOT reject at the model layer — a
    # dict value has to survive parsing so normalize_query() (normalize/queries.py)
    # can raise the friendly ERR-SOURCE-INLINE-FORBIDDEN, not a generic
    # Pydantic type-mismatch error. Never reaches the normalized SqlQuery.source
    # (str | None) — normalize_query() rejects the dict before constructing it.
    source: str | dict[str, Any] | None = Field(
        default=None,
        description=(
            "Source name reference, or an inline file path (e.g. `./data/sales.csv`). "
            "File paths are detected by `/` or data file extension. An inline "
            "connection-bearing dict (`{type: postgres, ...}`) is rejected at "
            "compile time — reference a named source instead."
        ),
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of the query. Used by AI search and tooling.",
    )
    ignore: list[str] | None = Field(
        default=None,
        description=(
            "Diagnostic codes to suppress for this query "
            "(e.g., ['WARN-FANOUT-RISK', 'WARN-REAGGREGATION'])."
        ),
    )
    cache: CachePatch | None = Field(
        default=None,
        description=(
            "Cache policy override for this query, e.g. cache: 5m — refines "
            "the policy inherited from the source and project scopes; "
            "cache: false opts out of result caching entirely. Queries with "
            "cache: false cannot be used as {{ queries.X.cache }} upstream "
            "references."
        ),
    )

    @field_validator("ignore")
    @classmethod
    def _validate_ignore_codes(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            validate_suppression_codes(v, source="query.ignore")
        return v


class AuthoredSqlQuery(_BaseQueryFields):
    """Raw SQL query — the default query type.

    Example YAML:
        queries:
          sales_by_date:
            sql: SELECT date, SUM(amount) FROM sales GROUP BY date
            source: my_postgres
    """

    type: Literal["sql"] = Field(
        default="sql",
        description="Query adapter type.",
    )
    sql: str | None = Field(
        default=None,
        description="SQL query string. Supports Jinja2 templates referencing variables.",
    )
    setup_sql: str | None = Field(
        default=None,
        description="Non-nestable SQL preamble executed before the main query (e.g., CREATE TEMP FUNCTION).",
    )
    target: str | None = Field(
        default=None,
        description="dbt target name for queries against a dbt_profile source (defaults to 'dev').",
    )


class AuthoredMetricflowQuery(_BaseQueryFields):
    """dbt Semantic Layer (MetricFlow) query.

    Example YAML:
        queries:
          metrics_query:
            type: metricflow
            metrics: [revenue, orders]
            dimensions: [date_day]
    """

    type: Literal["metricflow"] = Field(
        default="metricflow",
        description="Query adapter type.",
    )
    # Chart `model:` sugar constructs this query before chart-channel collection
    # discovers and fills the metric names.
    metrics: list[str] | None = Field(
        default=None,
        description="MetricFlow metric names to query.",
    )
    dimensions: list[str] | None = Field(
        default=None,
        description="MetricFlow dimensions to include in the result.",
    )
    time_grain: TimeGrain | None = Field(
        default=None,
        description="MetricFlow time grain for time-series dimensions (day, week, month, quarter, year).",
    )
    where: list[str] | None = Field(
        default=None,
        description=(
            "SQL predicates over the query's MetricFlow group-by names. Literal "
            "predicates (no Jinja) bake into MetricFlow at compile time and may "
            "reference any dimension; predicates with {{ }} resolve per render "
            "and must reference a selected dimension (in dimensions: or the "
            "time_grain column)."
        ),
    )
    limit: int | None = Field(
        default=None,
        description="Maximum number of rows returned.",
    )


class AuthoredHttpQuery(_BaseQueryFields):
    """REST API query.

    Example YAML:
        queries:
          api_data:
            type: http
            url: https://api.example.com/data
    """

    type: Literal["http"] = Field(
        default="http",
        description="Query adapter type.",
    )
    url: str = Field(
        description="HTTP endpoint URL for REST API queries.",
    )
    method: RestMethod | None = Field(
        default=None,
        description="HTTP method (GET, POST, PUT, DELETE, PATCH).",
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description="HTTP request headers.",
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="HTTP query string parameters.",
    )
    body: dict[str, Any] | str | None = Field(
        default=None,
        description="HTTP request body for POST/PUT queries.",
    )
    limit: int | None = Field(
        default=None,
        description="Maximum number of rows returned.",
    )
    json_path: str | None = Field(
        default=None,
        description="JSONPath expression to extract tabular data from the HTTP response.",
    )


class _AuthoredValuesQueryFields(_BaseQueryFields):
    """Fields shared by both inline-values authoring shapes."""

    type: Literal["values"] = Field(
        default="values",
        description="Query adapter type.",
    )


class AuthoredValuesQuery(_AuthoredValuesQueryFields):
    """Inline data authored as a list of row mappings."""

    rows: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "Inline data rows (list of row dicts). Use the compact "
                "columns-and-values form instead when row values are positional."
            )
        ),
    ]


class AuthoredCompactValuesQuery(_AuthoredValuesQueryFields):
    """Inline data authored as column names plus positional row values."""

    columns: Annotated[
        list[str],
        Field(
            description=(
                "Column names for the compact syntax. Every compact values query "
                "also requires values."
            )
        ),
    ]
    values: Annotated[
        list[list[Any]],
        Field(
            description=(
                "Inline row-oriented data (list of lists) for the compact syntax. "
                "Every compact values query also requires columns."
            )
        ),
    ]


class AuthoredSchemaQuery(_BaseQueryFields):
    """dbt source schema query."""

    # populate_by_name=True: required for schema_name's alias="schema" to accept
    # both the YAML key "schema:" and the Python attribute name "schema_name".
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["schema"] = Field(
        default="schema",
        description="Query adapter type.",
    )
    # alias="schema" so YAML authors write `schema: analytics`; Python code uses
    # schema_name to avoid shadowing BaseModel.schema (a Pydantic v2 legacy classmethod).
    schema_name: str | None = Field(
        default=None,
        alias="schema",
        description="Schema name for schema queries (YAML key: schema).",
    )
    table: str | None = Field(
        default=None,
        description="Table name for schema queries.",
    )
    column: str | None = Field(
        default=None,
        description="Column name for schema queries.",
    )


def _discriminate_authored_query(v: Any) -> str | None:
    """Custom discriminator: return the type tag for the AuthoredQuery union.

    Returns None for unknown or missing type, which triggers Pydantic's
    union_tag_not_found ValidationError — explicit and loud. The tag is
    stamped by normalize_query_value before validation (inferred from key
    presence when the author omits it).
    """
    if isinstance(v, dict):
        t = v.get("type")
    elif isinstance(v, _BaseQueryFields):
        t = getattr(v, "type", None)
    else:
        return None
    if not isinstance(t, str):
        return None
    if t == "values":
        if isinstance(v, AuthoredValuesQuery):
            return "values_rows"
        if isinstance(v, AuthoredCompactValuesQuery):
            return "values_compact"
        return (
            "values_rows" if isinstance(v, dict) and "rows" in v else "values_compact"
        )
    return t


AuthoredQuery = Annotated[
    Annotated[AuthoredSqlQuery, Tag("sql")]
    | Annotated[AuthoredMetricflowQuery, Tag("metricflow")]
    | Annotated[AuthoredHttpQuery, Tag("http")]
    | Annotated[AuthoredValuesQuery, Tag("values_rows")]
    | Annotated[AuthoredCompactValuesQuery, Tag("values_compact")]
    | Annotated[AuthoredSchemaQuery, Tag("schema")],
    Discriminator(_discriminate_authored_query),
]
"""Discriminated union over the authored query types.

AuthoredQuery is a type alias, not a BaseModel. Use TypeAdapter(AuthoredQuery)
for validation and isinstance(obj, _BaseQueryFields) for instance checks.
The `type` tag is stamped by normalize_query_value before validation (inferred
from key presence when omitted), so authors rarely write it explicitly.
"""
