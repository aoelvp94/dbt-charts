"""Tests for the ``dct migrate`` CLI command."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from typer.testing import CliRunner

from dbt_charts.agent_api.migrate import MigrateError, MigrateNote, MigrateSummary
from dbt_charts.cli.commands import migrate as migrate_command
from dbt_charts.cli.main import app

runner = CliRunner()


def test_migrate_help_describes_preview_and_paths() -> None:
    result = runner.invoke(app, ["migrate", "--help"])

    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "PATH" in result.output


def test_migrate_dry_run_reports_would_update_and_forwards_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, object] = {}

    def fake_migrate(
        paths: list[Path] | None, *, project_dir: Path | None, dry_run: bool
    ) -> None:
        received.update(paths=paths, project_dir=project_dir, dry_run=dry_run)
        migrate_command._emit(
            MigrateSummary(updated=[PurePosixPath("charts/revenue.yml")]),
            dry_run=dry_run,
        )

    monkeypatch.setattr(migrate_command, "migrate_command", fake_migrate)

    result = runner.invoke(
        app,
        [
            "migrate",
            "--dry-run",
            "charts/revenue.yml",
            "--project-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Would update charts/revenue.yml" in result.output
    assert "1 files would be updated" in result.output
    assert received == {
        "paths": [Path("charts/revenue.yml")],
        "project_dir": tmp_path,
        "dry_run": True,
    }


def test_migrate_prints_deletion_reason_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_migrate(
        paths: list[Path] | None, *, project_dir: Path | None, dry_run: bool
    ) -> None:
        migrate_command._emit(
            MigrateSummary(
                updated=[PurePosixPath("charts/bar.yaml")],
                notes=[
                    MigrateNote(
                        path=PurePosixPath("charts/bar.yaml"),
                        message="bar has no per-chart card to paint it onto.",
                    )
                ],
            ),
            dry_run=dry_run,
        )

    monkeypatch.setattr(migrate_command, "migrate_command", fake_migrate)

    result = runner.invoke(app, ["migrate"])

    assert result.exit_code == 0, result.output
    assert "Updated charts/bar.yaml" in result.output
    assert (
        "charts/bar.yaml: bar has no per-chart card to paint it onto." in result.output
    )


def test_migrate_reports_each_failed_file_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_migrate(
        paths: list[Path] | None, *, project_dir: Path | None, dry_run: bool
    ) -> None:
        migrate_command._emit(
            MigrateSummary(
                errors=[
                    MigrateError(
                        path=PurePosixPath("charts/revenue.yml"),
                        message="Move the retired field manually.",
                    )
                ]
            ),
            dry_run=dry_run,
        )

    monkeypatch.setattr(migrate_command, "migrate_command", fake_migrate)

    result = runner.invoke(app, ["migrate"])

    assert result.exit_code == 1
    assert "Error charts/revenue.yml: Move the retired field manually." in result.output
    assert "1 files with errors" in result.output
