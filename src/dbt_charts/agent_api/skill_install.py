"""File-based install of wheel workflow skills into agent skill directories."""

from __future__ import annotations

import shutil
from collections.abc import Set
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.agent_api.skill_render import render_skill_body
from dbt_charts.agent_api.skills import Skill, all_skill_names, list_skills

# Pattern skills are not file-installed; tombstone retired dirs on re-run.
RETIRED_SKILL_NAMES: tuple[str, ...] = (
    "before-after-comparison",
    "drill-down-link",
    "faceted-small-multiples",
    "filter-bar-with-variables",
    "kpi-row",
    "single-metric-bignum",
    "table-heavy-ops-dashboard",
    "time-series-trend",
    "top-n-with-detail",
    "two-by-two-grid-overview",
)

_LEGACY_SKILL_ROOTS: tuple[Path, ...] = (
    Path(".cursor/skills"),
    Path(".codex/skills"),
)

_SKILL_TARGET_DIRS: dict[str, Path] = {
    "agents": Path(".agents/skills"),
    "codex": Path(".agents/skills"),
    "claude": Path(".claude/skills"),
}

SKILL_INSTALL_TARGETS: frozenset[str] = frozenset(_SKILL_TARGET_DIRS)


class InstallSkillsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    installed: list[str] = Field(default_factory=list)
    retired_removed: list[str] = Field(default_factory=list)
    skipped_existing: list[str] = Field(default_factory=list)
    legacy_dirs_detected: list[Path] = Field(default_factory=list)


def skills_for_file_install() -> list[Skill]:
    """Workflow skills exposed on the CLI surface.

    All file-backed by construction: no ``project``/``extra_skills`` is passed,
    so only wheel built-ins are listed.
    """
    return sorted(
        (s for s in list_skills(surface="cli").skills if s.kind == "workflow"),
        key=lambda s: s.name,
    )


def target_dir_for(target: str, *, project_root: Path) -> Path:
    rel = _SKILL_TARGET_DIRS[target]
    return project_root / rel


def detect_skill_targets(project_root: Path) -> list[str]:
    """Return install target keys detected under ``project_root``."""
    targets: list[str] = []
    if (project_root / ".cursor").is_dir() or (project_root / "AGENTS.md").is_file():
        targets.append("agents")
    if (project_root / "CLAUDE.md").is_file():
        targets.append("claude")
    return targets


def detect_global_skill_targets() -> list[Path]:
    """Return user-level skill dirs detected under ``Path.home()``.

    Mirrors ``detect_skill_targets`` but at the machine level: installs into
    each agent's directory whose parent config dir exists. An existing
    ``~/.codex/`` also signals ``~/.agents/skills``, since Codex's older
    ``~/.codex/skills`` is deprecated in favor of the shared location.
    """
    home = Path.home()
    targets: list[Path] = []
    if (home / ".claude").is_dir():
        targets.append(home / ".claude" / "skills")
    if (home / ".agents").is_dir() or (home / ".codex").is_dir():
        targets.append(home / ".agents" / "skills")
    return targets


def detect_legacy_skill_dirs(
    project_root: Path, wheel_skill_names: Set[str]
) -> list[Path]:
    """Legacy triplicate dirs that still contain a wheel skill name."""
    found: list[Path] = []
    for rel_root in _LEGACY_SKILL_ROOTS:
        root = project_root / rel_root
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and child.name in wheel_skill_names:
                found.append(child)
    return found


def _rendered_skill_md(skill: Skill) -> str:
    # Narrowing only — skills_for_file_install lists built-ins, which always
    # have a directory; a file-less one would raise on the `/` below anyway.
    assert skill.directory is not None
    raw = (skill.directory / "SKILL.md").read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{skill.directory / 'SKILL.md'}: missing frontmatter")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{skill.directory / 'SKILL.md'}: malformed frontmatter")
    rendered_body = render_skill_body(skill.body, surface="cli")
    return f"---{parts[1]}---\n{rendered_body}"


def _is_wheel_authored(skill_md: Path) -> bool:
    """Only a SKILL.md this tool wrote carries the wheel's author line; a
    user's own skill that happens to share a retired name is not ours to sweep."""
    return skill_md.is_file() and "author: fivetran" in skill_md.read_text(
        encoding="utf-8"
    )


def install_skills(
    *,
    target_dir: Path,
    project_root: Path,
    force: bool = False,
    check: bool = False,
) -> InstallSkillsResult:
    """Install CLI-rendered workflow skills into ``target_dir``."""
    wheel_names = all_skill_names()
    legacy = detect_legacy_skill_dirs(project_root, wheel_names)
    retired_removed: list[str] = []
    installed: list[str] = []
    skipped_existing: list[str] = []

    if not check:
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in RETIRED_SKILL_NAMES:
            retired_path = target_dir / name
            if _is_wheel_authored(retired_path / "SKILL.md"):
                shutil.rmtree(retired_path)
                retired_removed.append(name)

    for skill in skills_for_file_install():
        dest_dir = target_dir / skill.name
        dest_md = dest_dir / "SKILL.md"
        content = _rendered_skill_md(skill)
        if check:
            installed.append(skill.name)
            continue
        if dest_md.is_file() and not force:
            skipped_existing.append(skill.name)
            continue
        if dest_dir.is_dir():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_md.write_text(content, encoding="utf-8")
        installed.append(skill.name)

    return InstallSkillsResult(
        installed=installed,
        retired_removed=retired_removed,
        skipped_existing=skipped_existing,
        legacy_dirs_detected=legacy,
    )
