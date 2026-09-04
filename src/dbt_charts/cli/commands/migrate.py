"""Migrate command — thin wrapper over :mod:`dbt_charts.agent_api.migrate`."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import typer

from dbt_charts.agent_api import Project
from dbt_charts.cli._console import dct_console
from dbt_charts.cli._project import with_project

if TYPE_CHECKING:
    from dbt_charts.agent_api.migrate import MigrateSummary

_console = dct_console()


@with_project
def migrate_command(
    paths: list[Path] | None,
    *,
    project: Project,
    dry_run: bool,
) -> None:
    """Rewrite supported retired board syntax in the selected paths."""
    from dbt_charts.agent_api import ProjectSession
    from dbt_charts.agent_api._paths import resolve_board_path

    relpaths = (
        [PurePosixPath(resolve_board_path(path, project).relpath) for path in paths]
        if paths
        else None
    )
    with ProjectSession.from_project(project) as project_session:
        summary = project_session.migrate_paths(relpaths, dry_run=dry_run)
    _emit(summary, dry_run=dry_run)


def _emit(summary: MigrateSummary, *, dry_run: bool) -> None:
    action = "Would update" if dry_run else "Updated"
    for path in summary.updated:
        _console.print(f"{action} {path}")
    for note in summary.notes:
        _console.print(f"  {note.path}: {note.message}")
    for path in summary.current:
        _console.print(f"Current {path}")
    for error in summary.errors:
        _console.print(f"Error {error.path}: {error.message}")

    _console.print(
        f"{len(summary.updated)} files {'would be ' if dry_run else ''}updated, "
        f"{len(summary.current)} files already current, "
        f"{len(summary.errors)} files with errors"
    )
    if not summary.success:
        raise typer.Exit(1)
