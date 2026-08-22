"""FR-001 + FR-002 regression: adapter constructors and build_adapter_registry
require project (and DbtAdapter requires project + dbt_project_path + target) —
no cwd or env fallback."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters.adapter_registry import build_adapter_registry
from dbt_charts.core.execute.adapters.dbt_adapter import DbtAdapter
from dbt_charts.core.execute.adapters.sql_adapter import SqlAdapter


class TestSqlAdapterRequiresProject:
    def test_omitting_project_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            SqlAdapter()  # type: ignore[call-arg]


class TestDbtAdapterRequiresProjectRootAndTarget:
    def test_omitting_project_raises_typeerror(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError):
            DbtAdapter(dbt_project_path=tmp_path, target_name="dev")  # type: ignore[call-arg]

    def test_omitting_dbt_project_path_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            DbtAdapter(target_name="dev")  # type: ignore[call-arg]

    def test_omitting_target_name_raises_typeerror(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        with pytest.raises(TypeError):
            DbtAdapter(project=local_project(tmp_path), dbt_project_path=tmp_path)  # type: ignore[call-arg]

    def test_ignores_dbt_target_env_var(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """target_name is taken from the kwarg, not from DBT_TARGET."""
        with patch.dict(os.environ, {"DBT_TARGET": "prod"}, clear=False):
            adapter = DbtAdapter(
                project=local_project(tmp_path),
                dbt_project_path=tmp_path,
                target_name="dev",
            )
        assert adapter.target_name == "dev"


class TestBuildAdapterRegistryRequiresProjectRoot:
    def test_omitting_project_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            build_adapter_registry()  # type: ignore[call-arg]
