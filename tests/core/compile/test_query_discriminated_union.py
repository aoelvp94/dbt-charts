"""AuthoredQuery is a per-type discriminated union, not a flat god model.

Mirrors the chart-family pattern (test_chart_discriminated_union.py): each
query type carries only its own fields with extra="forbid", so cross-type
field misuse fails at parse time, and the generated YAML reference documents
each type's fields in its own section instead of one merged table.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from dbt_charts.core.compile.models.query.authored import (
    AuthoredQuery,
    AuthoredSqlQuery,
)
from dbt_charts.core.compile.models.refs import normalize_query_value

_ADAPTER: TypeAdapter[object] = TypeAdapter(AuthoredQuery)


def _validate(query_dict: dict[str, object]) -> object:
    """Parse through the same path production uses: stamp type, then validate."""
    return _ADAPTER.validate_python(normalize_query_value(query_dict))


def test_bare_sql_string_shorthand_still_parses() -> None:
    query = _ADAPTER.validate_python(normalize_query_value("SELECT 1"))
    assert isinstance(query, AuthoredSqlQuery)
    assert query.sql == "SELECT 1"
