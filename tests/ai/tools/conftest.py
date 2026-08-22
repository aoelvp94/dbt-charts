"""Shared fixtures for dbt_charts.ai.tools dispatch tests.

Builds a DbtChartsAIContext rooted at the test's tmp_path. Tests pass extra
kwargs (server_port, dashboards_directory, …) when they need to override the
default; the project session is constructed once per test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dbt_charts.agent_api import ProjectSession
from dbt_charts.ai.context import DbtChartsAIContext


@pytest.fixture
def make_context(tmp_path: Path) -> Callable[..., DbtChartsAIContext]:
    """Return a factory that builds a DbtChartsAIContext for this test's tmp_path."""

    def _make(**overrides: Any) -> DbtChartsAIContext:
        if "project_session" not in overrides:
            overrides["project_session"] = ProjectSession.open(
                tmp_path, read_only=False
            )
        return DbtChartsAIContext(**overrides)

    return _make


@pytest.fixture
def context(make_context: Callable[..., DbtChartsAIContext]) -> DbtChartsAIContext:
    """Default DbtChartsAIContext with a tmp_path-rooted project session."""
    return make_context()
