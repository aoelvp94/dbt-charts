"""Tests for `dct init skills`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dbt_charts.cli import main as cli_main

runner = CliRunner()


def _seed_project() -> None:
    Path("dbt_charts.yml").write_text("name: test\n", encoding="utf-8")


def test_init_skills_agents_writes_rendered_workflows(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "agents"])

        assert result.exit_code == 0, result.output
        skill_md = Path(".agents/skills/board-build/SKILL.md")
        assert skill_md.exists()
        text = skill_md.read_text(encoding="utf-8")
        assert "{{ s_" not in text
        assert not Path(".cursor/skills").exists()
        assert not Path(".codex/skills").exists()
        assert not (Path(".agents/skills") / "kpi-row").exists()


def test_init_skills_claude_target(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "claude"])

        assert result.exit_code == 0, result.output
        assert Path(".claude/skills/board-build/SKILL.md").exists()


def test_init_skills_all_with_both_markers(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        Path("AGENTS.md").write_text("# agents\n", encoding="utf-8")
        Path("CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        result = runner.invoke(cli_main.app, ["init", "skills", "--all"])

        assert result.exit_code == 0, result.output
        assert Path(".agents/skills/board-build/SKILL.md").exists()
        assert Path(".claude/skills/board-build/SKILL.md").exists()


def test_init_skills_check_dry_run(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "agents", "--check"])

        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert not Path(".agents/skills").exists()


def test_init_skills_no_markers_defaults_to_agents(tmp_path: Path) -> None:
    """FR-69: bare `dct init skills` in a fresh repo (no .cursor/, AGENTS.md,
    CLAUDE.md) must install to the tool-agnostic `agents` target rather than
    erroring — a fresh project legitimately has none of those markers yet, and
    the docs tell users to run this command bare."""
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills"])

        assert result.exit_code == 0, result.output
        assert Path(".agents/skills/board-build/SKILL.md").exists()
        assert not Path(".claude/skills").exists()


def test_init_skills_all_with_no_markers_still_errors(tmp_path: Path) -> None:
    """`--all` keeps its own contract: install to every *detected* target, so
    it still errors with no markers rather than silently falling back to one."""
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "--all"])

        assert result.exit_code == 1, result.output
        assert "No agent skill targets detected" in result.output


def test_init_skills_dir_override(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(
            cli_main.app, ["init", "skills", "--dir", "custom-skills"]
        )

        assert result.exit_code == 0, result.output
        assert Path("custom-skills/board-build/SKILL.md").exists()


def test_init_skills_global_installs_into_home_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    monkeypatch.setenv("HOME", str(home))

    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "--global"])

        assert result.exit_code == 0, result.output
        assert (home / ".claude/skills/board-build/SKILL.md").exists()


def test_init_skills_global_installs_into_home_agents_via_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".codex").mkdir()
    monkeypatch.setenv("HOME", str(home))

    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "--global"])

        assert result.exit_code == 0, result.output
        assert (home / ".agents/skills/board-build/SKILL.md").exists()


def test_init_skills_global_no_markers_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "--global"])

        assert result.exit_code == 1, result.output
        assert "~/.claude/skills" in result.output
        assert "~/.agents/skills" in result.output
        assert "--dir" in result.output


def test_init_skills_global_with_target_errors(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "agents", "--global"])

        assert result.exit_code == 1, result.output


def test_init_skills_global_with_all_errors(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "--all", "--global"])

        assert result.exit_code == 1, result.output


def test_init_skills_global_with_dir_errors(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(
            cli_main.app, ["init", "skills", "--dir", "custom-skills", "--global"]
        )

        assert result.exit_code == 1, result.output


def test_init_mcp_does_not_write_skill_dirs(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        Path(".cursor").mkdir()
        result = runner.invoke(cli_main.app, ["init", "mcp", "cursor"])

        assert result.exit_code == 0, result.output
        assert Path(".cursor/mcp.json").exists()
        assert not Path(".cursor/skills").exists()
        assert not Path(".codex/skills").exists()
        assert not Path(".claude/skills").exists()


def test_init_skills_global_prints_a_home_path_not_a_repo_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills", "--global"])
        assert result.exit_code == 0, result.output
        assert "~/.claude/skills/" in result.output


def test_init_skills_global_ignores_dct_project_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ProjectDirOption reads DCT_PROJECT_DIR; a global install must neither
    refuse on it nor write into that project."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("DCT_PROJECT_DIR", str(project))

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli_main.app, ["init", "skills", "--global"])

        assert result.exit_code == 0, result.output
        assert (home / ".claude/skills/board-build/SKILL.md").exists()
        assert not (project / ".claude").exists()
        assert not (project / ".agents").exists()
