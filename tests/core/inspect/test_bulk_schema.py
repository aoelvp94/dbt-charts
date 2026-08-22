"""Tests for the bulk_schema primitive.

bulk_schema must enumerate the whole source in a SINGLE query
(INFORMATION_SCHEMA), not a per-schema walk — that is the N+1 it exists to
kill. Executed end-to-end against a real DuckDB file so the SQL, execution, and
row parsing are all exercised.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.inspect.bulk_schema import bulk_schema, format_bulk_schema


def _duckdb_registry(tmp_path: Path, local_project: Callable[..., FilesystemProject]):
    """A registry over a DuckDB file with two schemas and three tables."""
    db_path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE SCHEMA sales")
        con.execute("CREATE SCHEMA marketing")
        con.execute("CREATE TABLE sales.orders (id INTEGER, amount DECIMAL(10,2))")
        con.execute("CREATE TABLE sales.customers (id INTEGER, name VARCHAR)")
        con.execute("CREATE TABLE marketing.campaigns (id INTEGER, channel VARCHAR)")
    finally:
        con.close()

    (tmp_path / "dbt_charts.yml").write_text(
        f"sources:\n  wh:\n    type: duckdb\n    path: {db_path}\n",
        encoding="utf-8",
    )
    project = local_project(tmp_path)
    return build_adapter_registry(project, read_only=True)


def test_bulk_schema_returns_all_schemas_tables_columns(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    registry = _duckdb_registry(tmp_path, local_project)
    schema = bulk_schema(source="wh", adapter_registry=registry)

    assert set(schema) >= {"sales", "marketing"}
    assert set(schema["sales"]) == {"orders", "customers"}
    assert set(schema["marketing"]) == {"campaigns"}
    # Columns with types, ordered.
    assert list(schema["sales"]["orders"]) == ["id", "amount"]
    assert schema["sales"]["orders"]["id"].upper().startswith("INT")


def test_bulk_schema_issues_exactly_one_query(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """The whole point: one query for the entire source, not one per schema."""
    registry = _duckdb_registry(tmp_path, local_project)
    calls = 0
    real_execute = registry.execute

    def counting_execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_execute(*args, **kwargs)

    registry.execute = counting_execute  # type: ignore[method-assign]
    bulk_schema(source="wh", adapter_registry=registry)
    assert calls == 1


def test_bulk_schema_raises_when_execution_max_rows_truncates_it(
    tmp_path: Path,
    local_project: Callable[..., FilesystemProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A silently truncated schema tree would omit columns and corrupt AI
    prompt assembly — bulk_schema must raise loudly instead of returning a
    partial tree when execution.max_rows/DCT_MAX_ROWS_CEILING fires."""
    monkeypatch.setenv("DCT_MAX_ROWS_CEILING", "1")
    registry = _duckdb_registry(tmp_path, local_project)

    with pytest.raises(RuntimeError, match="truncated"):
        bulk_schema(source="wh", adapter_registry=registry)


def test_bulk_schema_over_sqlite_source(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """SQLite has no information_schema; the pragma_table_info path must still
    return tables + columns in one query (regression: cacheless SQLite context)."""
    import sqlite3

    db_path = tmp_path / "shop.sqlite"
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("CREATE TABLE customer (id INTEGER, plan TEXT)")
    finally:
        con.close()
    (tmp_path / "dbt_charts.yml").write_text(
        f"sources:\n  shop:\n    type: sqlite\n    path: {db_path}\n", encoding="utf-8"
    )
    registry = build_adapter_registry(local_project(tmp_path), profile_type="sqlite")

    schema = bulk_schema(source="shop", adapter_registry=registry)
    assert "customer" in schema["main"]
    assert list(schema["main"]["customer"]) == ["id", "plan"]


def test_format_bulk_schema_renders_tables_and_columns(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    registry = _duckdb_registry(tmp_path, local_project)
    schema = bulk_schema(source="wh", adapter_registry=registry)
    text = format_bulk_schema(schema, source="wh", dialect="duckdb")

    assert "wh" in text
    assert "sales.orders" in text
    assert "customers" in text
    assert "channel" in text
