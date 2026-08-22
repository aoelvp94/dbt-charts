"""Typed API for rewriting retained board YAML grammars."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.agent_api._paths import resolve_board_relpath
from dbt_charts.core.project import CHARTS_SUBDIR, Project, ProjectPath


class MigrateError(BaseModel):
    """One file that could not be migrated without manual action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: PurePosixPath = Field(
        description="Project-relative path that requires manual action."
    )
    message: str = Field(description="User-ready explanation of the migration failure.")


class MigrateSummary(BaseModel):
    """Results of a migration run, separated by outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    updated: list[PurePosixPath] = Field(
        default_factory=list,
        description="Files that were migrated, or would be migrated during a dry run.",
    )
    current: list[PurePosixPath] = Field(
        default_factory=list,
        description="Files that already satisfy the current YAML grammar.",
    )
    errors: list[MigrateError] = Field(
        default_factory=list,
        description="Files that require manual migration.",
    )

    @property
    def success(self) -> bool:
        return not self.errors


def migrate_paths(
    paths: list[PurePosixPath] | None,
    *,
    project: Project,
    dry_run: bool,
) -> MigrateSummary:
    """Migrate named board files/directories, or all public boards by default."""
    updated: list[PurePosixPath] = []
    current: list[PurePosixPath] = []
    errors: list[MigrateError] = []
    from dbt_charts.core.compile.errors import ParseError
    from dbt_charts.core.compile.migrations import migrate_board_yaml_text
    from dbt_charts.core.compile.parse.parser import parse_yaml

    for board_path in _migration_paths(paths, project):
        path = PurePosixPath(board_path.relpath)
        try:
            original = board_path.read_text()
            migrated = migrate_board_yaml_text(original)
            if migrated == original:
                current.append(path)
                continue
            parse_yaml(migrated)
            if not dry_run:
                project.write_text(board_path.relpath, migrated)
            updated.append(path)
        except (OSError, ValueError, ParseError) as exc:
            errors.append(MigrateError(path=path, message=str(exc)))
    return MigrateSummary(
        updated=updated,
        current=current,
        errors=errors,
    )


def _migration_paths(
    paths: list[PurePosixPath] | None, project: Project
) -> list[ProjectPath]:
    if not paths:
        return [
            path
            for path in project.iter_boards(under=CHARTS_SUBDIR)
            if path.is_yaml and not path.is_private and not path.is_meta
        ]
    resolved: list[ProjectPath] = []
    for path in paths:
        selected = resolve_board_relpath(path, project)
        if selected.is_yaml:
            resolved.append(selected)
            continue
        resolved.extend(
            child
            for child in project.iter_boards(under=selected.relpath)
            if child.is_yaml and not child.is_private and not child.is_meta
        )
    return resolved
