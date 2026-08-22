"""Shared fixtures for agent_api tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters import AdapterRegistry
from dbt_charts.core.project import Project


@pytest.fixture
def empty_registry(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> AdapterRegistry:
    """A bare AdapterRegistry rooted at tmp_path — no adapters registered.

    Used by tests that want to exercise the error path (empty registry
    can't execute) without spinning up a real adapter.
    """
    return AdapterRegistry(project=local_project(tmp_path))


@pytest.fixture
def empty_project(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> Project:
    """A bare Project rooted at tmp_path — no board files on disk.

    Used by tests that call schema() or other verbs that require a Project
    but do not exercise project-file discovery.
    """
    return local_project(tmp_path)
