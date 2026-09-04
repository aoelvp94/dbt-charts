"""Regression for Issue 6: each board-path verb resolves correctly from a subdir.

Each test runs from a fixture subdirectory inside a dbt charts project
(containing dbt_charts.yml) and passes only the project-root-relative path.
Before the fix every verb resolved the board against cwd, producing a
'File not found' error from inside a nested directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()

_VALID_BOARD = """
queries:
  revenue:
    sql: SELECT 1 AS month, 100 AS revenue
    source: db
charts:
  rev:
    query: revenue
    type: bar
    x: month
    y: revenue
rows:
  - rev
"""

_SOURCES = 'sources:\n  db:\n    type: duckdb\n    path: ":memory:"\n'


@pytest.fixture
def project_in_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture: project root with dbt_charts.yml, board files under charts/.

    Sets cwd to project/models/ (a subdir with no board files).
    Returns the project root path.
    """
    project = tmp_path / "myproject"
    (project / "charts").mkdir(parents=True)
    (project / "models").mkdir()
    (project / "dbt_charts.yml").write_text(_SOURCES)
    (project / "charts" / "hello.yml").write_text(_VALID_BOARD)
    (project / "charts" / "hello.yaml").write_text(_VALID_BOARD)
    monkeypatch.chdir(project / "models")
    return project


class TestDftValidateWalksUp:
    def test_validate_resolves_from_subdir(self, project_in_subdir: Path) -> None:
        result = runner.invoke(app, ["validate", "charts/hello.yml", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["path"] == "charts/hello.yml"


class TestDftDescribeWalksUp:
    def test_describe_resolves_from_subdir(self, project_in_subdir: Path) -> None:
        result = runner.invoke(app, ["describe", "charts/hello.yml", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["path"] == "charts/hello.yml"


class TestDftQueryWalksUp:
    def test_query_resolves_from_subdir(self, project_in_subdir: Path) -> None:
        result = runner.invoke(app, ["query", "charts/hello.yaml", "revenue", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["path"] == "charts/hello.yaml"


class TestDftValidateWalksUpDirectory:
    def test_validate_directory_resolves_from_subdir(
        self, project_in_subdir: Path
    ) -> None:
        result = runner.invoke(app, ["validate", "charts/"])
        assert result.exit_code == 0, f"from {project_in_subdir}: {result.output}"


class TestDftRenderWalksUp:
    def test_render_resolves_from_subdir(self, project_in_subdir: Path) -> None:
        result = runner.invoke(app, ["render", "charts/hello.yml", "--format", "json"])
        assert result.exit_code == 0, f"from {project_in_subdir}: {result.output}"


def _no_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set cwd to a directory with no project marker at or above it."""
    monkeypatch.chdir(tmp_path)


class TestHintFromNoProject:
    """All project-touching verbs exit 1 with a clean project-discovery error
    (no traceback) when run outside any project and without --project-dir.

    Project discovery now happens once, before the verb body runs — so a
    missing project short-circuits before --json is ever considered.
    """

    def test_validate_emits_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_project_dir(tmp_path, monkeypatch)
        result = runner.invoke(app, ["validate", "charts/nonexistent.yml", "--json"])
        assert result.exit_code == 1
        combined = result.output + (result.stderr or "")
        assert "Traceback" not in combined
        assert "No dbt charts project found" in combined

    def test_describe_emits_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_project_dir(tmp_path, monkeypatch)
        result = runner.invoke(app, ["describe", "charts/nonexistent.yml", "--json"])
        assert result.exit_code == 1
        combined = result.output + (result.stderr or "")
        assert "Traceback" not in combined
        assert "No dbt charts project found" in combined

    def test_query_emits_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_project_dir(tmp_path, monkeypatch)
        result = runner.invoke(
            app, ["query", "charts/nonexistent.yaml", "revenue", "--json"]
        )
        assert result.exit_code == 1
        combined = result.output + (result.stderr or "")
        assert "Traceback" not in combined
        assert "No dbt charts project found" in combined


class TestExplicitProjectDirRejectsNonProject:
    """An explicit --project-dir pointing at an existing dir with no project
    marker exits 1 with a clean error — validated the same as the cwd walk,
    not trusted through to a confusing downstream file-not-found.
    """

    def test_validate_rejects_non_project(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["validate", "charts/x.yml", "--project-dir", str(tmp_path)]
        )
        assert result.exit_code == 1
        # Collapse the rich panel's line wrapping before matching — the phrase
        # spans a wrap boundary at narrow CI terminal widths.
        combined = " ".join((result.output + (result.stderr or "")).split())
        assert "Traceback" not in combined
        assert "is not a dbt charts project" in combined
