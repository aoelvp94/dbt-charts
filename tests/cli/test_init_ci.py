"""Tests for `dct init ci` — scaffolds a board-validation GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from dbt_charts.cli import main as cli_main

runner = CliRunner()

WORKFLOW = Path(".github/workflows/dbt-charts.yml")


def _triggers(parsed: dict[str | bool, Any]) -> dict[str, Any]:
    """PyYAML resolves a bare ``on:`` key to True under YAML 1.1; GitHub reads it as "on"."""
    return parsed["on"] if "on" in parsed else parsed[True]


def _seed(root: Path, project_relpath: str = ".") -> Path:
    """A git repo whose dbt/dct project sits at *project_relpath* below the root."""
    (root / ".git").mkdir(exist_ok=True)
    project = root / project_relpath
    project.mkdir(parents=True, exist_ok=True)
    (project / "dbt_project.yml").write_text("name: analytics\n", encoding="utf-8")
    (project / "dbt_charts.yml").write_text("name: analytics\n", encoding="utf-8")
    (project / "charts").mkdir(exist_ok=True)
    return project


def test_init_ci_writes_workflow_at_repo_root(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    result = runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])

    assert result.exit_code == 0, result.output
    workflow = tmp_path / WORKFLOW
    assert workflow.exists()

    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    steps = parsed["jobs"]["validate"]["steps"]
    assert any("dct validate charts" in s.get("run", "") for s in steps)


def test_workflow_paths_are_repo_root_relative_for_a_nested_dbt_root(
    tmp_path: Path,
) -> None:
    """The dbt root is not always the repo root — filters and cwd must carry the full path."""
    project = _seed(tmp_path, "analytics/transform_bi")
    result = runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])

    assert result.exit_code == 0, result.output
    # GitHub only reads workflows from the repo root, never the project dir —
    # and a nested project owns its own filename so a monorepo's projects
    # don't overwrite each other's gate.
    nested = tmp_path / ".github/workflows/dbt-charts-analytics-transform-bi.yml"
    assert nested.exists()
    assert not (project / WORKFLOW).exists()

    parsed = yaml.safe_load(nested.read_text(encoding="utf-8"))
    job = parsed["jobs"]["validate"]
    assert job["defaults"]["run"]["working-directory"] == "analytics/transform_bi"

    # Path filters are always repo-root-relative, so they must be fully qualified.
    filters = _triggers(parsed)["pull_request"]["paths"]
    assert "analytics/transform_bi/charts/**" in filters
    assert "analytics/transform_bi/dbt_charts.yml" in filters


def test_two_nested_projects_get_two_workflows(tmp_path: Path) -> None:
    a = _seed(tmp_path, "analytics/a")
    b = _seed(tmp_path, "analytics/b")
    runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(a)])
    result = runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(b)])

    assert result.exit_code == 0, result.output
    assert "skipped" not in result.output
    assert (tmp_path / ".github/workflows/dbt-charts-analytics-a.yml").exists()
    assert (tmp_path / ".github/workflows/dbt-charts-analytics-b.yml").exists()


def test_a_non_project_dir_fails_loud(tmp_path: Path) -> None:
    """No silent fallback: a typo'd --project-dir must not scaffold a gate
    whose filters point at a directory with no project in it."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "analytcs").mkdir()
    result = runner.invoke(
        cli_main.app, ["init", "ci", "--project-dir", str(tmp_path / "analytcs")]
    )

    assert result.exit_code == 1, result.output
    assert "does not contain a dbt charts or dbt project" in result.output
    assert not (tmp_path / ".github").exists()


def test_no_git_repo_fails_loud(tmp_path: Path) -> None:
    """GitHub reads workflows only at the repo root; with no repo, writing
    anywhere scaffolds a gate that can never fire — refuse instead."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "dbt_charts.yml").write_text("name: p\n", encoding="utf-8")
    result = runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])

    assert result.exit_code == 1, result.output
    assert "No git repository" in result.output
    assert not (project / ".github").exists()


def test_explicit_dir_walked_up_to_an_ancestor_says_so(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    sub = project / "models"
    sub.mkdir()
    result = runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(sub)])

    assert result.exit_code == 0, result.output
    assert "project root resolved to" in result.output


def test_root_project_omits_working_directory(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])

    parsed = yaml.safe_load((tmp_path / WORKFLOW).read_text(encoding="utf-8"))
    assert "defaults" not in parsed["jobs"]["validate"]
    assert "charts/**" in _triggers(parsed)["pull_request"]["paths"]


def test_init_ci_is_idempotent(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])
    (tmp_path / WORKFLOW).write_text("# hand-edited\n", encoding="utf-8")

    result = runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / WORKFLOW).read_text(encoding="utf-8") == "# hand-edited\n"
    assert "already exists" in result.output


def test_init_ci_force_overwrites(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])
    (tmp_path / WORKFLOW).write_text("# hand-edited\n", encoding="utf-8")

    result = runner.invoke(
        cli_main.app, ["init", "ci", "--project-dir", str(project), "--force"]
    )

    assert result.exit_code == 0, result.output
    assert "dct validate charts" in (tmp_path / WORKFLOW).read_text(encoding="utf-8")


def test_workflow_content_comes_from_agent_api(tmp_path: Path) -> None:
    """Thin-wrapper rule: the command file holds no workflow content of its own."""
    from dbt_charts.agent_api.init_ci import ci_workflow, workflow_relpath

    project = _seed(tmp_path, "analytics")
    runner.invoke(cli_main.app, ["init", "ci", "--project-dir", str(project)])

    written = tmp_path / workflow_relpath("analytics")
    assert written.read_text(encoding="utf-8") == ci_workflow(
        project_relpath="analytics"
    )
