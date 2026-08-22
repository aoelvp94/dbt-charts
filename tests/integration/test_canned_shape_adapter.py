"""Unit tests for canned_row_for_sql internals."""

from __future__ import annotations

import pytest
import sqlglot.errors

from dbt_charts.core.compile.models.query.normalized import SqlQuery

from .canned_shape_adapter import canned_row_for_sql


def _sql_query(sql: str) -> SqlQuery:
    return SqlQuery.model_validate({"sql": sql, "source": "warehouse"})


class TestCannedRowForSql:
    def test_count_alias_is_numeric(self) -> None:
        q = _sql_query("SELECT region, COUNT(*) AS count FROM t GROUP BY region")
        rows = canned_row_for_sql(q)
        assert rows[0]["count"] == 1
        assert rows[0]["region"] == "a"

    def test_plain_select_returns_string_defaults(self) -> None:
        q = _sql_query("SELECT region, month FROM sales")
        assert canned_row_for_sql(q) == [{"region": "a", "month": "a"}]

    def test_unparseable_sql_raises(self) -> None:
        """SQL that cannot be parsed raises ParseError — not silently swallowed."""
        q = _sql_query("NOT VALID SQL !!!")
        with pytest.raises(sqlglot.errors.ParseError):
            canned_row_for_sql(q)

    def test_select_star_returns_star_key(self) -> None:
        """SELECT * — alias_or_name gives '*'; documents current behavior."""
        q = _sql_query("SELECT * FROM t")
        rows = canned_row_for_sql(q)
        assert len(rows) == 1
        assert "*" in rows[0]

    def test_count_without_alias_returns_one_column(self) -> None:
        q = _sql_query("SELECT COUNT(*) FROM t")
        rows = canned_row_for_sql(q)
        assert len(rows) == 1 and len(rows[0]) == 1

    def test_cte_extracts_outer_select_columns(self) -> None:
        q = _sql_query(
            "WITH base AS (SELECT id, SUM(amount) AS total FROM t GROUP BY id) "
            "SELECT id, total FROM base"
        )
        rows = canned_row_for_sql(q)
        assert "id" in rows[0] and "total" in rows[0]
        assert rows[0]["total"] == 1

    def test_uses_source_dialect_for_parsing(self) -> None:
        q = _sql_query("SELECT id, SUM(amount) AS total FROM t GROUP BY id")
        assert canned_row_for_sql(q, dialect="snowflake")[0]["total"] == 1
