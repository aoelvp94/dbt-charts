"""build_adapter_registry detects an external dbt_project_dir.

The sibling rule in adapter_registry.py must check FilesystemProject.dbt_root
(and its nested `dbt_project` seam), not the dct project root, so a
dbt_project.yml that lives outside the dct project (a monorepo layout, or a
separate repo entirely) is still detected and wired into DbtAdapter/
DuckDBAdapter/SqlAdapter's dbt_project_path.
"""

from __future__ import annotations

from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters.adapter_registry import build_adapter_registry
from dbt_charts.core.execute.adapters.dbt_adapter import DbtAdapter


def test_registers_dbt_adapter_from_external_dbt_root(tmp_path: Path) -> None:
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    external_dbt = tmp_path / "external_dbt"
    external_dbt.mkdir()
    (external_dbt / "dbt_project.yml").write_text("name: x\nprofile: x\n")

    project = FilesystemProject(project_root, dbt_root=external_dbt)
    registry = build_adapter_registry(project)

    dbt_adapters = [a for a in registry.adapters if isinstance(a, DbtAdapter)]
    assert len(dbt_adapters) == 1
    assert dbt_adapters[0].dbt_project_path == external_dbt.resolve()


def test_registers_no_dbt_adapter_when_external_dir_has_no_dbt_project(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    external_dbt = tmp_path / "external_dbt"
    external_dbt.mkdir()  # no dbt_project.yml

    project = FilesystemProject(project_root, dbt_root=external_dbt)
    registry = build_adapter_registry(project)

    assert not any(isinstance(a, DbtAdapter) for a in registry.adapters)


def test_sibling_rule_unchanged_when_dbt_root_equals_project_root(
    tmp_path: Path,
) -> None:
    """No dbt_project_dir override -> same-dir sibling behavior as before."""
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    (project_root / "dbt_project.yml").write_text("name: x\nprofile: x\n")

    project = FilesystemProject(project_root)
    registry = build_adapter_registry(project)

    dbt_adapters = [a for a in registry.adapters if isinstance(a, DbtAdapter)]
    assert len(dbt_adapters) == 1
    assert dbt_adapters[0].dbt_project_path == project_root.resolve()
