"""Tests for describe_query agent_api verb."""

from __future__ import annotations

from unittest.mock import MagicMock

from dbt.adapters.base.column import Column

from dbt_charts.agent_api.describe_query import (
    DescribeQueryColumn,
    describe_query,
)
from dbt_charts.core.execute.adapters.base import QueryResult


def _registry_with_adapter(monkeypatch, columns=None, raises=None):
    """Fake AdapterRegistry + patched build_adapter for unit isolation.

    Uses a non-DuckDB source type so the dbt adapter path is exercised
    (DuckDB sources use registry.execute() instead of build_adapter).
    """
    from dbt_charts.agent_api import describe_query as mod

    adapter = MagicMock()
    if raises is not None:
        adapter.get_column_schema_from_query.side_effect = raises
    else:
        adapter.get_column_schema_from_query.return_value = columns or []

    def _build_adapter(cfg: dict[str, object], *, read_only: bool = False) -> object:
        return adapter

    monkeypatch.setattr(mod, "build_adapter", _build_adapter)
    registry = MagicMock()
    registry.resolve_source_config.return_value = {
        "type": "bigquery",
        "project": "my-proj",
    }
    return registry, adapter


def _registry_for_duckdb(rows=None, error=None):
    """Fake AdapterRegistry for the DuckDB read-only path (registry.execute())."""
    registry = MagicMock()
    registry.resolve_source_config.return_value = {"type": "duckdb", "path": ":memory:"}
    registry.execute.return_value = QueryResult(data=rows or [], error=error)
    return registry


class TestGating:
    def test_parse_error_short_circuits_and_does_not_call_adapter(self, monkeypatch):
        registry, adapter = _registry_with_adapter(monkeypatch)
        result = describe_query(
            "SELECT * FROM",  # incomplete SELECT — sqlglot parse error
            source="warehouse",
            adapter_registry=registry,
        )
        assert result.success is False
        assert result.columns is None
        assert any(d["code"] == "WARN-PARSE-ERROR" for d in result.diagnostics)
        adapter.get_column_schema_from_query.assert_not_called()

    def test_missing_join_predicate_short_circuits(self, monkeypatch):
        registry, adapter = _registry_with_adapter(monkeypatch)
        result = describe_query(
            "SELECT a.x FROM a JOIN b",
            source="warehouse",
            dialect="duckdb",
            adapter_registry=registry,
        )
        assert result.success is False
        assert any(
            d["code"] == "WARN-MISSING-JOIN-PREDICATE" for d in result.diagnostics
        )
        adapter.get_column_schema_from_query.assert_not_called()

    def test_fanout_warning_does_not_block_adapter_call(self, monkeypatch):
        cols = [
            Column(
                column="x",
                dtype="INTEGER",
                char_size=None,
                numeric_precision=None,
                numeric_scale=None,
            )
        ]
        registry, adapter = _registry_with_adapter(monkeypatch, columns=cols)
        result = describe_query(
            "SELECT SUM(a.x) FROM a JOIN b ON a.id = b.a_id",
            source="warehouse",
            adapter_registry=registry,
        )
        assert result.success is True
        assert result.columns == [DescribeQueryColumn(name="x", type="INTEGER")]
        adapter.get_column_schema_from_query.assert_called_once()


class TestAdapterPath:
    def test_valid_sql_returns_columns(self, monkeypatch):
        cols = [
            Column(
                column="month",
                dtype="DATE",
                char_size=None,
                numeric_precision=None,
                numeric_scale=None,
            ),
            Column(
                column="revenue",
                dtype="DECIMAL",
                char_size=None,
                numeric_precision=18,
                numeric_scale=2,
            ),
        ]
        registry, _ = _registry_with_adapter(monkeypatch, columns=cols)
        result = describe_query(
            "SELECT month, SUM(revenue) AS revenue FROM orders GROUP BY 1",
            source="warehouse",
            adapter_registry=registry,
        )
        assert result.success is True
        assert result.columns is not None
        assert [c.name for c in result.columns] == ["month", "revenue"]
        assert result.columns[1].type == "DECIMAL"
        assert result.error is None

    def test_adapter_exception_surfaces_on_result(self, monkeypatch):
        registry, _ = _registry_with_adapter(
            monkeypatch, raises=RuntimeError("warehouse down")
        )
        result = describe_query(
            "SELECT 1 AS x",
            source="warehouse",
            adapter_registry=registry,
        )
        assert result.success is False
        assert result.columns is None
        assert result.error is not None
        assert "warehouse down" in result.error

    def test_numeric_precision_scale_propagated(self, monkeypatch):
        cols = [
            Column(
                column="price",
                dtype="NUMERIC",
                char_size=None,
                numeric_precision=10,
                numeric_scale=4,
            )
        ]
        registry, _ = _registry_with_adapter(monkeypatch, columns=cols)
        result = describe_query(
            "SELECT price FROM products",
            source="warehouse",
            adapter_registry=registry,
        )
        assert result.success is True
        assert result.columns is not None
        col = result.columns[0]
        assert col.name == "price"
        assert col.numeric_precision == 10
        assert col.numeric_scale == 4

    def test_empty_sql_short_circuits(self, monkeypatch):
        registry, adapter = _registry_with_adapter(monkeypatch)
        result = describe_query("   ", source="warehouse", adapter_registry=registry)
        assert result.success is False
        assert any(d["code"] == "WARN-PARSE-ERROR" for d in result.diagnostics)
        adapter.get_column_schema_from_query.assert_not_called()


class TestDuckDBPath:
    """DuckDB sources use registry.execute() (read-only) instead of build_adapter."""

    def test_duckdb_returns_columns_from_describe(self):
        registry = _registry_for_duckdb(
            rows=[
                {"column_name": "id", "column_type": "INTEGER"},
                {"column_name": "name", "column_type": "VARCHAR"},
            ]
        )
        result = describe_query(
            "SELECT id, name FROM t",
            source="db",
            adapter_registry=registry,
        )
        assert result.success is True
        assert result.columns is not None
        assert [c.name for c in result.columns] == ["id", "name"]
        assert result.columns[0].type == "INTEGER"
        assert result.columns[1].type == "VARCHAR"

    def test_duckdb_execute_error_surfaces(self):
        registry = _registry_for_duckdb(error="table not found")
        result = describe_query(
            "SELECT x FROM missing",
            source="db",
            adapter_registry=registry,
        )
        assert result.success is False
        assert result.error is not None
        assert "table not found" in result.error

    def test_duckdb_does_not_call_build_adapter(self, monkeypatch):
        from dbt_charts.agent_api import describe_query as mod

        called = []

        def _build_adapter(
            cfg: dict[str, object], *, read_only: bool = False
        ) -> object:
            called.append(cfg)
            return None

        monkeypatch.setattr(mod, "build_adapter", _build_adapter)
        registry = _registry_for_duckdb(
            rows=[{"column_name": "x", "column_type": "INTEGER"}]
        )
        describe_query("SELECT 1 AS x", source="db", adapter_registry=registry)
        assert called == [], "build_adapter must not be called for DuckDB sources"
