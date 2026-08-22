"""Regression tests: --project-dir validates the path at parse time (P4).

Click's Path type with exists=True, file_okay=False, dir_okay=True,
resolve_path=True must reject a non-existent or non-directory path before any
application code runs, returning exit code 2 and an "Invalid value" message.

One test per affected command is sufficient — all ten sites share Click's
Path validation code path.
"""

from __future__ import annotations

from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()

_BAD = "/nonexistent_typer_conventions_regression_path"


class TestProjectDirValidation:
    """--project-dir must reject bad paths at CLI parse time, not later."""

    def test_validate_rejects_nonexistent_project_dir(self) -> None:
        result = runner.invoke(app, ["validate", "--project-dir", _BAD])
        assert result.exit_code == 2, result.stderr
        assert "Invalid value" in result.stderr

    def test_search_rejects_nonexistent_project_dir(self) -> None:
        result = runner.invoke(app, ["search", "revenue", "--project-dir", _BAD])
        assert result.exit_code == 2, result.stderr
        assert "Invalid value" in result.stderr
