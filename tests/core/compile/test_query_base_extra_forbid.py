"""Regression tests: Query base and subtypes reject unknown keys (extra="forbid").

Verifies that bogus fields raise ValidationError for each query subtype.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.query.normalized import (
    HttpQuery,
    SqlQuery,
    ValuesQuery,
)


def test_sql_query_rejects_unknown_key():
    with pytest.raises(ValidationError, match="bogus_key"):
        SqlQuery(sql="SELECT 1", bogus_key="x", source="my_db")


def test_sql_query_rejects_profile_field():
    """profile is not a SqlQuery field; source is the correct connection field."""
    with pytest.raises(ValidationError, match="profile"):
        SqlQuery(sql="SELECT 1", profile="test_profile", source="my_db")


def test_values_query_rejects_unknown_key():
    with pytest.raises(ValidationError, match="bogus_key"):
        ValuesQuery(rows=[{"a": 1}], bogus_key="x")


def test_http_query_rejects_unknown_key():
    with pytest.raises(ValidationError, match="bogus_key"):
        HttpQuery(url="http://example.com", bogus_key="x")


def test_normalize_query_skips_source_propagation_for_values_query():
    """Values queries are inline data; default_source must not be injected.

    Regression: normalize/queries.py was unconditionally propagating
    board-level default_source to all query types, including ValuesQuery which
    has no source field. The guard (query_type != "values") prevents this.
    """
    from dbt_charts.core.compile.normalize.queries import normalize_query

    query = normalize_query(
        name="inline",
        query_def={"type": "values", "rows": [{"a": 1}]},
        default_source="my_db",
        sources={},
    )
    assert isinstance(query, ValuesQuery)
    # ValuesQuery has no source field — injecting default_source would
    # violate extra="forbid" and indicates the guard was bypassed.
    assert not hasattr(query, "source")


class TestFiltersAndLimitOffTheBase:
    """Declarative filters: is removed; filters/limit live per-family, not on the base.

    The authored base holds identity/plumbing only (source, description, cache,
    ignore). limit:
    survives only on the families whose query language cannot express it in-band
    (http).
    """

    def test_authored_sql_query_rejects_filters(self) -> None:
        from dbt_charts.core.compile.models.query.authored import AuthoredSqlQuery

        with pytest.raises(ValidationError, match="filters"):
            AuthoredSqlQuery(sql="SELECT 1", source="db", filters={"region": "r"})

    def test_authored_sql_query_rejects_limit(self) -> None:
        from dbt_charts.core.compile.models.query.authored import AuthoredSqlQuery

        with pytest.raises(ValidationError, match="limit"):
            AuthoredSqlQuery(sql="SELECT 1", source="db", limit=5)

    def test_authored_values_query_rejects_limit(self) -> None:
        from dbt_charts.core.compile.models.query.authored import AuthoredValuesQuery

        with pytest.raises(ValidationError, match="limit"):
            AuthoredValuesQuery(rows=[{"a": 1}], limit=5)

    def test_limit_survives_on_http(self) -> None:
        from dbt_charts.core.compile.models.query.authored import AuthoredHttpQuery

        assert AuthoredHttpQuery(url="https://api.example.com", limit=20).limit == 20

    def test_board_level_sql_filters_rejected_at_parse(self) -> None:
        """The user-visible surface: filters: on a sql query in board YAML fails to compile."""
        from dbt_charts.core.compile import compile

        result = compile(
            """
title: t
variables:
  region_pick:
    input: text
queries:
  sales:
    sql: SELECT 1 AS a
    source: db
    filters:
      region: region_pick
charts:
  c:
    query: sales
    type: table
rows:
  - c
"""
        )
        assert not result.success
        assert "filters" in str(result.errors)
