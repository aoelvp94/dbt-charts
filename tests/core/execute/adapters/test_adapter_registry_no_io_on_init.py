"""Pins: AdapterRegistry.__init__ does no I/O; sources loading happens in
build_adapter_registry (the factory), not inside the registry itself.

The old contract ("build_adapter_registry with no project_sources reads no disk")
is replaced by: "AdapterRegistry.__init__ does no disk reads regardless of what
sources are passed into it — the sources are already-loaded data at that point."
"""

from collections.abc import Callable
from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters import AdapterRegistry, build_adapter_registry


def test_build_adapter_registry_reads_sources_from_project_dbt_charts_yml(
    tmp_path: Path,
    local_project: Callable[..., FilesystemProject],
) -> None:
    """build_adapter_registry reads sources from dbt_charts.yml via project.sources."""
    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n  disk_src:\n    type: duckdb\n    path: disk.duckdb\n"
    )

    registry = build_adapter_registry(local_project(tmp_path))

    names = {s["name"] for s in registry.list_sql_sources()}
    assert "disk_src" in names, (
        f"Registry should reflect the project's dbt_charts.yml sources; got {names!r}"
    )


def test_build_adapter_registry_empty_project_has_no_sources(
    tmp_path: Path,
    local_project: Callable[..., FilesystemProject],
) -> None:
    """A project with no sources in dbt_charts.yml yields a registry with no configured sources."""
    registry = build_adapter_registry(local_project(tmp_path))
    names = {s["name"] for s in registry.list_sql_sources()}
    assert names == set(), f"Empty project should yield no SQL sources; got {names!r}."


def test_adapter_registry_init_does_no_io(
    tmp_path: Path,
    local_project: Callable[..., FilesystemProject],
) -> None:
    """AdapterRegistry.__init__ does no I/O — sources are supplied as already-loaded data.

    Construct an AdapterRegistry directly with a pre-built ProjectSourcesConfig;
    even though tmp_path has a dbt_charts.yml on disk, the registry must use only the
    injected config, not fall back to reading the file.
    """
    from dbt_charts.core.compile.config import ProjectSourcesConfig

    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n  disk_src:\n    type: duckdb\n    path: disk.duckdb\n"
    )

    injected = ProjectSourcesConfig(
        sources={"injected_src": {"type": "duckdb", "path": ":memory:"}},
    )
    # Construct the Cat C AdapterRegistry directly — bypasses build_adapter_registry
    registry = AdapterRegistry(
        project=local_project(tmp_path), project_sources=injected
    )

    names = {s["name"] for s in registry.list_sql_sources()}
    assert names == {"injected_src"}, (
        f"AdapterRegistry.__init__ must use only the injected config; got {names!r}. "
        "A 'disk_src' entry means the registry read from disk."
    )
    assert "disk_src" not in names
