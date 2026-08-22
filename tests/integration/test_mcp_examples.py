"""Integration tests against the dbt-charts/examples/ directory.

Exercises list_boards / get_board against real example dashboards
to catch regressions that would only surface against full-shape YAML.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.agent_api.boards import list_boards
from dbt_charts.core.project import Project

from .._paths import DBT_CHARTS_DIR


class TestIntegrationWithExamples:
    """Integration tests using the examples directory."""

    @pytest.fixture
    def playground_dir(self) -> Path:
        """Get the path to the playground example project (has a charts/ dir)."""
        return DBT_CHARTS_DIR / "examples" / "playground"

    def test_list_boards_examples(
        self, playground_dir: Path, local_project: Callable[..., Project]
    ) -> None:
        """Test listing dashboards in a real example project."""
        if not playground_dir.exists():
            pytest.skip("dbt-charts/examples/playground directory not found")

        result = list_boards(local_project(playground_dir))

        assert len(result.boards) > 0
        assert all(
            (playground_dir / dash.file.relpath).exists() for dash in result.boards
        )
