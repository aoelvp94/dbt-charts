from collections.abc import Callable

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.config import load_project_sources
from dbt_charts.core.execute import source_registry as source_registry_module
from dbt_charts.core.execute.source_registry import SourceRegistry


def test_source_registry_does_no_io_on_lookup(
    monkeypatch, tmp_path, local_project: Callable[..., FilesystemProject]
):
    """Once given a ProjectSourcesConfig, SourceRegistry never calls the loader."""
    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n  x:\n    type: duckdb\n    path: x.duckdb\n"
    )
    config = load_project_sources(local_project(tmp_path))

    def boom(*args, **kwargs):
        raise AssertionError("SourceRegistry must not call load_project_sources")

    # raising=False: installs the sentinel even though source_registry.py does not
    # currently import load_project_sources. If a future change re-introduces that
    # import, the bomb fires on the first lookup call.
    monkeypatch.setattr(
        source_registry_module, "load_project_sources", boom, raising=False
    )

    reg = SourceRegistry(project_sources=config)
    for _ in range(10):
        reg.runtime_config()
        reg.get("x")
        reg.all()
