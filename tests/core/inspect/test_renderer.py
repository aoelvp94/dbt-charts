"""render_inspect_dashboard takes a pre-configured AdapterRegistry.

Registry construction (from the project's `dbt_charts.yml` sources) is the
caller's job, not the renderer's.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

import duckdb

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.inspect.renderer import render_inspect_dashboard


def _template(name: str) -> str:
    return (
        files("dbt_charts.core.inspect.templates").joinpath(f"{name}.yml").read_text()
    )


def test_render_inspect_dashboard_renders_against_injected_registry(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """The renderer resolves/renders against a caller-supplied registry — it
    must not build its own from connection/dialect."""
    db_path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE main.orders AS SELECT 1 AS order_id")
    con.close()

    project = local_project(tmp_path)
    registry = build_adapter_registry(project)
    registry.register_source("orders_db", {"type": "duckdb", "path": str(db_path)})

    html = render_inspect_dashboard(
        _template("model"),
        {"model": "orders"},
        project=project,
        adapter_registry=registry,
    )

    assert "orders" in html


def test_render_inspect_dashboard_with_no_configured_source_surfaces_error(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """A project with zero configured sources resolves an empty source_name;
    the model/schema queries then fail with a clear "no source" error
    embedded in the rendered page — no synthesize-from-connection fallback,
    no crash."""
    project = local_project(tmp_path)
    registry = build_adapter_registry(project)
    assert registry.list_sql_sources() == []

    html = render_inspect_dashboard(
        _template("model"),
        {"model": "orders"},
        project=project,
        adapter_registry=registry,
    )
    assert "No source profiles are configured" in html
