"""Tests for `dct init skills`."""

from __future__ import annotations

from pathlib import Path

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


def test_init_skills_no_markers_errors(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _seed_project()
        result = runner.invoke(cli_main.app, ["init", "skills"])

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
