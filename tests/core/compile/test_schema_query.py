"""Tests for SchemaQuery compile-time behavior."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.query.normalized import (
    SchemaQuery,
    SqlQuery,
    is_schema_query,
)


def test_parse_source_only():
    q = SchemaQuery(source="warehouse")
    assert q.source == "warehouse"
    # Python attribute is schema_name; YAML alias is "schema"
    assert q.schema_name is None
    assert q.table is None
    assert q.column is None


def test_parse_all_fields():
    q = SchemaQuery(source="warehouse", schema="analytics", table="orders", column="id")
    assert q.source == "warehouse"
    assert q.schema_name == "analytics"
    assert q.table == "orders"
    assert q.column == "id"


def test_query_type():
    q = SchemaQuery(source="warehouse")
    assert q.query_type == "schema"


def test_source_description_source_only():
    q = SchemaQuery(source="warehouse")
    assert q.source_description == "schema: warehouse"


def test_source_description_with_schema():
    q = SchemaQuery(source="warehouse", schema="analytics")
    assert q.source_description == "schema: warehouse.analytics"


def test_source_description_with_table():
    q = SchemaQuery(source="warehouse", schema="analytics", table="orders")
    assert q.source_description == "schema: warehouse.analytics.orders"


def test_source_description_all_fields():
    q = SchemaQuery(source="warehouse", schema="analytics", table="orders", column="id")
    assert q.source_description == "schema: warehouse.analytics.orders.id"


def test_type_guard_true():
    q = SchemaQuery(source="warehouse")
    assert is_schema_query(q) is True


def test_type_guard_false_sql():
    q = SqlQuery(sql="SELECT 1", source="db")
    assert is_schema_query(q) is False


def test_missing_source_is_valid():
    """source is optional — omitting it means 'list all sources'."""
    q = SchemaQuery()
    assert q.source is None


def test_unknown_key_raises():
    with pytest.raises(ValidationError):
        SchemaQuery(source="warehouse", bogus_key="x")


# ---- Compile-time structural invariants ----


def test_table_without_schema_raises():
    with pytest.raises(ValidationError, match="schema"):
        SchemaQuery(source="warehouse", table="orders")


def test_column_without_table_raises():
    with pytest.raises(ValidationError, match="table"):
        SchemaQuery(source="warehouse", schema="analytics", column="id")


def test_jinja_in_source_raises():
    with pytest.raises(ValidationError, match="Jinja"):
        SchemaQuery(source="{{ source_var }}")


def test_jinja_in_schema_raises():
    with pytest.raises(ValidationError, match="Jinja"):
        SchemaQuery(source="warehouse", schema="{{ schema_var }}")


def test_jinja_in_table_raises():
    with pytest.raises(ValidationError, match="Jinja"):
        SchemaQuery(source="warehouse", schema="analytics", table="{{ tbl }}")


def test_jinja_in_column_raises():
    with pytest.raises(ValidationError, match="Jinja"):
        SchemaQuery(
            source="warehouse", schema="analytics", table="orders", column="{{ col }}"
        )


def test_jinja_block_tag_raises():
    with pytest.raises(ValidationError, match="Jinja"):
        SchemaQuery(source="{% if x %}warehouse{% endif %}")


def test_jinja_comment_raises():
    with pytest.raises(ValidationError, match="Jinja"):
        SchemaQuery(source="{# comment #}")


def test_normalize_query_produces_schema_query():
    from dbt_charts.core.compile.normalize.queries import normalize_query

    q = normalize_query(
        "schemas",
        {"type": "schema", "source": "warehouse", "schema": "analytics"},
        sources={},
    )
    assert isinstance(q, SchemaQuery)
    assert q.source == "warehouse"
    assert q.schema_name == "analytics"


def test_normalize_query_does_not_apply_default_source():
    from dbt_charts.core.compile.normalize.queries import normalize_query

    q = normalize_query(
        "schemas",
        {"type": "schema", "source": "warehouse"},
        default_source="should_be_ignored",
        sources={},
    )
    assert isinstance(q, SchemaQuery)
    assert q.source == "warehouse"
