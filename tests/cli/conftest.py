"""Shared fixtures for CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_SOURCES_YAML = "sources:\n  db:\n    type: duckdb\n    path: ':memory:'\n"


@pytest.fixture
def sources_yaml() -> str:
    """In-memory DuckDB dbt_charts.yml sources content for CLI tests."""
    return _SOURCES_YAML


@pytest.fixture
def project_dir(tmp_path: Path, sources_yaml: str) -> Path:
    """Project dir with an in-memory DuckDB source for CLI tests."""
    (tmp_path / "dbt_charts.yml").write_text(sources_yaml)
    return tmp_path


@pytest.fixture
def file_duckdb_project_dir(tmp_path: Path) -> Path:
    """Project dir with a file-backed DuckDB + dbt manifest for schema drill-down tests.

    Tables: users(id, name), orders(order_id, user_id), order_items(item_id, order_id, sku).
    Lineage: orders refs users; order_items refs orders.
    """
    import duckdb

    db_path = tmp_path / "wh.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE users (id INTEGER, name VARCHAR)")
    conn.execute("INSERT INTO users VALUES (1, 'alice'), (2, 'bob')")
    conn.execute("CREATE TABLE orders (order_id INTEGER, user_id INTEGER)")
    conn.execute("INSERT INTO orders VALUES (10, 1), (11, 2)")
    conn.execute(
        "CREATE TABLE order_items (item_id INTEGER, order_id INTEGER, sku VARCHAR)"
    )
    conn.close()

    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(
        json.dumps(
            {
                "nodes": {
                    "model.test.users": {
                        "resource_type": "model",
                        "schema": "main",
                        "name": "users",
                    },
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "main",
                        "name": "orders",
                    },
                    "model.test.order_items": {
                        "resource_type": "model",
                        "schema": "main",
                        "name": "order_items",
                    },
                },
                "sources": {},
                "parent_map": {
                    "model.test.users": [],
                    "model.test.orders": ["model.test.users"],
                    "model.test.order_items": ["model.test.orders"],
                },
                "child_map": {
                    "model.test.users": ["model.test.orders"],
                    "model.test.orders": ["model.test.order_items"],
                    "model.test.order_items": [],
                },
            }
        )
    )
    (tmp_path / "dbt_charts.yml").write_text(
        f"sources:\n  wh:\n    type: duckdb\n    path: '{db_path}'\n"
    )
    return tmp_path
