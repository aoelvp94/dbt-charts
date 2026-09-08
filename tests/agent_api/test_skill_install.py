"""Tests for dbt_charts.agent_api.skill_install."""

from __future__ import annotations

from pathlib import Path

import pytest

from dbt_charts.agent_api.skill_install import (
    RETIRED_SKILL_NAMES,
    detect_global_skill_targets,
    detect_legacy_skill_dirs,
    detect_skill_targets,
    install_skills,
    skills_for_file_install,
    target_dir_for,
)
from dbt_charts.agent_api.skills import all_skill_names


@pytest.fixture
def install_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "dbt_charts.yml").write_text("name: test\n")
    return root


def test_skills_for_file_install_excludes_patterns() -> None:
    names = {s.name for s in skills_for_file_install()}
    assert "board-build" in names
    assert "dct-mcp-setup" in names
    assert "kpi-row" not in names
    assert all(s.kind == "workflow" for s in skills_for_file_install())


def test_install_renders_cli_surface(install_root: Path) -> None:
    target = install_root / ".agents/skills"
    result = install_skills(target_dir=target, project_root=install_root)

    assert "board-build" in result.installed
    skill_md = target / "board-build" / "SKILL.md"
    assert skill_md.exists()
    text = skill_md.read_text(encoding="utf-8")
    assert "{{ s_" not in text
    assert "dct validate" in text or "dct check" in text


def test_install_removes_retired_skill_dirs(install_root: Path) -> None:
    target = install_root / ".agents/skills"
    retired = RETIRED_SKILL_NAMES[0]
    (target / retired).mkdir(parents=True)
    (target / retired / "SKILL.md").write_text(
        "---\nname: kpi-row\nmetadata:\n  author: fivetran\n---\nstale\n"
    )

    result = install_skills(target_dir=target, project_root=install_root)

    assert retired in result.retired_removed
    assert not (target / retired).exists()


def test_install_keeps_a_user_authored_dir_that_shares_a_retired_name(
    install_root: Path,
) -> None:
    target = install_root / ".agents/skills"
    retired = RETIRED_SKILL_NAMES[0]
    (target / retired).mkdir(parents=True)
    (target / retired / "SKILL.md").write_text("---\nname: kpi-row\n---\nmine\n")

    result = install_skills(target_dir=target, project_root=install_root)

    assert result.retired_removed == []
    assert (
        target / retired / "SKILL.md"
    ).read_text() == "---\nname: kpi-row\n---\nmine\n"


def test_install_preserves_user_authored_skill(install_root: Path) -> None:
    target = install_root / ".agents/skills"
    custom = target / "my-company-playbook"
    custom.mkdir(parents=True)
    custom_md = custom / "SKILL.md"
    custom_md.write_text(
        "---\nname: my-company-playbook\ndescription: x\nkind: workflow\n---\nbody\n"
    )

    install_skills(target_dir=target, project_root=install_root)

    assert custom_md.read_text(encoding="utf-8") == (
        "---\nname: my-company-playbook\ndescription: x\nkind: workflow\n---\nbody\n"
    )


def test_install_check_writes_nothing(install_root: Path) -> None:
    target = install_root / ".agents/skills"
    result = install_skills(target_dir=target, project_root=install_root, check=True)

    assert result.installed
    assert not target.exists()


def test_install_skips_existing_without_force(install_root: Path) -> None:
    target = install_root / ".agents/skills"
    first = install_skills(target_dir=target, project_root=install_root)
    assert first.installed

    second = install_skills(target_dir=target, project_root=install_root)
    assert len(second.skipped_existing) == len(first.installed)
    assert not second.installed


def test_install_force_rewrites(install_root: Path) -> None:
    target = install_root / ".agents/skills"
    install_skills(target_dir=target, project_root=install_root)
    skill_md = target / "board-build" / "SKILL.md"
    skill_md.write_text("corrupt\n")

    result = install_skills(target_dir=target, project_root=install_root, force=True)
    assert "board-build" in result.installed
    assert "{{ s_" not in skill_md.read_text(encoding="utf-8")


def test_detect_skill_targets_agents_and_claude(install_root: Path) -> None:
    (install_root / "AGENTS.md").write_text("# agents\n")
    (install_root / "CLAUDE.md").write_text("@AGENTS.md\n")
    assert detect_skill_targets(install_root) == ["agents", "claude"]


def test_detect_legacy_skill_dirs(install_root: Path) -> None:
    wheel_names = all_skill_names()
    legacy_dir = install_root / ".cursor/skills" / "board-build"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "SKILL.md").write_text("old\n")

    found = detect_legacy_skill_dirs(install_root, wheel_names)

    assert legacy_dir in found


def test_target_dir_for_aliases() -> None:
    root = Path("/proj")
    assert target_dir_for("agents", project_root=root) == root / ".agents/skills"
    assert target_dir_for("codex", project_root=root) == root / ".agents/skills"
    assert target_dir_for("claude", project_root=root) == root / ".claude/skills"


def test_detect_global_skill_targets_claude_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()

    assert detect_global_skill_targets() == [tmp_path / ".claude" / "skills"]


def test_detect_global_skill_targets_agents_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".agents").mkdir()

    assert detect_global_skill_targets() == [tmp_path / ".agents" / "skills"]


def test_detect_global_skill_targets_codex_signals_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".codex").mkdir()

    assert detect_global_skill_targets() == [tmp_path / ".agents" / "skills"]


def test_detect_global_skill_targets_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert detect_global_skill_targets() == []
