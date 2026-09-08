"""`dct init skills` thin wrapper: parse args, call agent_api.skill_install."""

from __future__ import annotations

from pathlib import Path

import typer

from dbt_charts.agent_api import skill_install
from dbt_charts.cli._project import resolve_skill_install_root

_VALID_TARGETS = skill_install.SKILL_INSTALL_TARGETS


def _resolve_targets(
    target: str | None,
    *,
    all_targets: bool,
    dir_override: Path | None,
    project_root: Path,
) -> list[Path]:
    if dir_override is not None:
        return [dir_override.resolve()]

    if target is not None:
        key = target.lower()
        if key not in _VALID_TARGETS:
            typer.echo(
                f"Unknown target: {target}. "
                f"Supported: {', '.join(sorted(_VALID_TARGETS))}",
                err=True,
            )
            raise typer.Exit(1)
        return [skill_install.target_dir_for(key, project_root=project_root)]

    detected = skill_install.detect_skill_targets(project_root)
    if all_targets:
        if not detected:
            typer.echo(
                "No agent skill targets detected (.cursor/, AGENTS.md, CLAUDE.md).\n"
                "Pass an explicit target: dct init skills agents | claude",
                err=True,
            )
            raise typer.Exit(1)
        keys = detected
    elif detected:
        keys = detected
    else:
        # Bare `dct init skills` with nothing detected is the documented
        # onboarding path for a fresh repo, which by definition has none of
        # these markers yet -- error here would contradict the docs. Default
        # to "agents", the tool-agnostic target every other client discovers.
        keys = ["agents"]

    return [skill_install.target_dir_for(k, project_root=project_root) for k in keys]


def _display_path(path: Path, project_root: Path, global_install: bool) -> Path:
    """Repo-relative for a repo install; `~/...` for a global one, so the two
    never print the same `.claude/skills/` line."""
    if global_install:
        return Path("~") / path.relative_to(project_root)
    try:
        return path.relative_to(project_root)
    except ValueError:
        return path


def _format_legacy_note(
    legacy_dirs: list[Path], project_root: Path, global_install: bool
) -> str | None:
    if not legacy_dirs:
        return None
    rel = _display_path(legacy_dirs[0], project_root, global_install)
    rerun = "dct init skills --global" if global_install else "dct init skills agents"
    return (
        f"Legacy skill install detected at {rel} — "
        f"re-run `{rerun}` and remove the legacy dir manually."
    )


def run_init_skills(
    target: str | None,
    all_targets: bool,
    dir_override: Path | None,
    global_install: bool,
    force: bool,
    check: bool,
    project_dir: Path | None = None,
) -> None:
    """Shared implementation for ``dct init skills``."""
    modes_given = sum(
        [target is not None, all_targets, dir_override is not None, global_install]
    )
    if modes_given > 1:
        typer.echo(
            "Specify one of: a target name, --all, --dir, or --global, not combined.",
            err=True,
        )
        raise typer.Exit(1)

    if global_install:
        target_dirs = skill_install.detect_global_skill_targets()
        if not target_dirs:
            typer.echo(
                "No user-level agent directories detected (~/.claude/, "
                "~/.agents/, ~/.codex/).\n"
                "Supported install targets: ~/.claude/skills, ~/.agents/skills.\n"
                "Pass an explicit target: dct init skills --dir PATH",
                err=True,
            )
            raise typer.Exit(1)
        project_root = Path.home()
    else:
        project_root = resolve_skill_install_root(
            project_dir if project_dir is not None else Path.cwd()
        )
        target_dirs = _resolve_targets(
            target,
            all_targets=all_targets,
            dir_override=dir_override,
            project_root=project_root,
        )

    prefix = "Would install" if check else "Installed"
    any_legacy = False
    for target_dir in target_dirs:
        result = skill_install.install_skills(
            target_dir=target_dir,
            project_root=project_root,
            force=force,
            check=check,
        )
        rel = _display_path(target_dir, project_root, global_install)
        if result.installed:
            typer.echo(f"  {prefix} workflow skills ({len(result.installed)}) → {rel}/")
            for name in sorted(result.installed):
                typer.echo(f"    ✓ {name}")
        elif result.skipped_existing:
            typer.echo(
                f"  Workflow skills unchanged ({len(result.skipped_existing)}) → {rel}/"
            )
        if result.retired_removed:
            typer.echo(f"  Removed retired: {', '.join(result.retired_removed)}")
        if result.skipped_existing:
            typer.echo(f"  Unchanged (identical): {', '.join(result.skipped_existing)}")
        legacy_note = _format_legacy_note(
            result.legacy_dirs_detected, project_root, global_install
        )
        if legacy_note:
            any_legacy = True
            typer.echo(f"  {legacy_note}")

    if check:
        typer.echo("")
        typer.echo("  Dry run — no files written.")
    elif any_legacy:
        typer.echo("")
        typer.echo(
            "  Re-run after removing legacy .cursor/skills or .codex/skills dirs."
        )
