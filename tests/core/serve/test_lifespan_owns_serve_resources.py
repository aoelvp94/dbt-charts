# dbt-charts/tests/core/serve/test_lifespan_owns_serve_resources.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters.adapter_registry import AdapterRegistry
from dbt_charts.core.serve.server import create_server


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "dbt_charts.yml").write_text("name: t\n")
    (tmp_path / "charts").mkdir()
    return tmp_path


def test_lifespan_builds_concrete_project_and_registry(project_dir: Path) -> None:
    """Lifespan stores a concrete FilesystemProject + AdapterRegistry on app.state —
    no ProjectSession, no cast needed to reach the filesystem-only adapter builder."""
    app = create_server(FilesystemProject(project_dir))
    with TestClient(app):
        assert isinstance(app.state.project, FilesystemProject)
        assert app.state.project.root == project_dir.resolve()
        assert isinstance(app.state.adapter_registry, AdapterRegistry)


def test_registry_closed_on_shutdown(project_dir: Path) -> None:
    """Teardown closes the live adapter registry (releasing its warm pool)."""
    app = create_server(FilesystemProject(project_dir))
    with TestClient(app) as client:
        client.get("/")
        registry = app.state.adapter_registry
        registry.close = MagicMock(wraps=registry.close)  # type: ignore[method-assign]
    registry.close.assert_called_once()


def test_independent_create_server_calls_get_independent_state(
    project_dir: Path,
) -> None:
    """No module-global state. Two create_server() calls produce distinct projects
    and registries; one lifespan's resources don't leak into another."""
    app_a = create_server(FilesystemProject(project_dir))
    app_b = create_server(FilesystemProject(project_dir))
    with TestClient(app_a), TestClient(app_b):
        assert app_a.state.project is not app_b.state.project
        assert app_a.state.adapter_registry is not app_b.state.adapter_registry
