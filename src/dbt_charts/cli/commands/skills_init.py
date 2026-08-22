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
        typer.echo(
            "No agent skill targets detected (.cursor/, AGENTS.md, CLAUDE.md).\n"
            "Specify a target or pass --dir:\n"
            "  dct init skills agents\n"
            "  dct init skills claude\n"
            "  dct init skills --all\n"
            "  dct init skills --dir .agents/skills",
            err=True,
        )
        raise typer.Exit(1)

    return [skill_install.target_dir_for(k, project_root=project_root) for k in keys]


def _format_legacy_note(legacy_dirs: list[Path], project_root: Path) -> str | None:
    if not legacy_dirs:
        return None
    first = legacy_dirs[0]
    try:
        rel = first.relative_to(project_root)
    except ValueError:
        rel = first
    return (
        f"Legacy skill install detected at {rel} — "
        "re-run `dct init skills agents` and remove the legacy dir manually."
    )


def run_init_skills(
    target: str | None,
    all_targets: bool,
    dir_override: Path | None,
    force: bool,
    check: bool,
    project_dir: Path | None = None,
) -> None:
    """Shared implementation for ``dct init skills``."""
    if target is not None and (all_targets or dir_override is not None):
        typer.echo(
            "Specify one of: a target name, --all, or --dir — not combined.",
            err=True,
        )
        raise typer.Exit(1)
    if all_targets and dir_override is not None:
        typer.echo("Specify either --all or --dir, not both.", err=True)
        raise typer.Exit(1)

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
        try:
            rel = target_dir.relative_to(project_root)
        except ValueError:
            rel = target_dir
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
        legacy_note = _format_legacy_note(result.legacy_dirs_detected, project_root)
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
