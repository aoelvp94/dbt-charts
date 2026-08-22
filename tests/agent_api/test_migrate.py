from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

from dbt_charts.agent_api.migrate import MigrateError, MigrateSummary, migrate_paths
from dbt_charts.core.compile.errors import ParseError
from dbt_charts.core.project import Project


def test_migrate_summary_exposes_a_machine_readable_success_flag() -> None:
    summary = MigrateSummary(updated=[PurePosixPath("charts/new.yaml")])

    assert summary.success is True


def test_migrate_summary_is_unsuccessful_when_any_file_failed() -> None:
    summary = MigrateSummary(
        errors=[
            MigrateError(path=PurePosixPath("charts/bad.yaml"), message="manual action")
        ]
    )

    assert summary.success is False


def test_migrates_a_project_backed_board_without_a_filesystem_path(
    tmp_path: Path,
    in_memory_project: Callable[[Path, dict[str, str]], Project],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = in_memory_project(tmp_path, {"charts/remote.yaml": "title: Remote\n"})

    from dbt_charts.core.compile import migrations

    def migrate_text(text: str) -> str:
        return text + "# migrated\n"

    monkeypatch.setattr(
        migrations,
        "migrate_board_yaml_text",
        migrate_text,
    )

    summary = migrate_paths(
        [PurePosixPath("remote.yaml")], project=project, dry_run=False
    )

    assert summary.updated == [PurePosixPath("charts/remote.yaml")]
    assert project.read_text("charts/remote.yaml").endswith("# migrated\n")


def test_migrate_paths_records_parse_error_as_migrate_error(
    tmp_path: Path,
    in_memory_project: Callable[[Path, dict[str, str]], Project],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ParseError from migrate_board_yaml_text is recorded as MigrateError, not raised.

    A deletion that empties a board raises ParseError from load_yaml_mapping.
    Before the fix, this escaped migrate_paths' (OSError, ValueError) handler
    and aborted the rest of the migration run.
    """
    project = in_memory_project(
        tmp_path, {"charts/meta.yaml": "style:\n  color: red\n"}
    )

    from dbt_charts.core.compile import migrations

    def migrate_text(text: str) -> str:
        raise ParseError("Empty YAML document")

    monkeypatch.setattr(migrations, "migrate_board_yaml_text", migrate_text)

    summary = migrate_paths(
        [PurePosixPath("meta.yaml")], project=project, dry_run=False
    )

    assert summary.errors == [
        MigrateError(
            path=PurePosixPath("charts/meta.yaml"), message="Empty YAML document"
        )
    ]
    assert not summary.updated
