"""Regression tests for non-mapping YAML (list, scalar) board files.

Before the fix, compile_file() would crash when the YAML parsed as a list
instead of a dict.  All four tests below must pass without raising an
exception — they must return structured errors instead.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from dbt_charts.cli.filesystem_project import FilesystemProject

from .._paths import DBT_CHARTS_DIR

# Path to the intentionally-broken fixture, relative to _PROJECT_DIR.
# Do NOT prefix with the project dir here — resolve_scoped_path joins it in.
_PARSE_ERROR = Path("errors/parse-error.yml")
_PROJECT_DIR = DBT_CHARTS_DIR / "tests" / "fixtures" / "non_mapping_yaml"


class TestValidateNonMappingYaml:
    """validate() returns a structured error, not a crash, for list-valued YAML."""

    def test_validate_returns_structured_error_not_exception(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.agent_api.validate import validate

        # Must not raise — must return success=False with an informative error.
        result = validate(_PARSE_ERROR, project=local_project(_PROJECT_DIR))

        assert result.success is False
        assert len(result.errors) >= 1
        msg = result.errors[0].message.lower()
        assert "mapping" in msg or "list" in msg, (
            f"Error message should mention 'mapping' or 'list', got: {result.errors[0].message!r}"
        )


class TestDescribeBoardNonMappingYaml:
    """describe_board() returns a structured error, not a crash, for list-valued YAML."""

    def test_describe_board_returns_structured_error_not_exception(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.agent_api.describe import describe_board

        # Must not raise — must return success=False with errors populated.
        result = describe_board(_PARSE_ERROR, project=local_project(_PROJECT_DIR))

        assert result.success is False
        assert len(result.errors) >= 1


class TestValidatePathWithNonMappingYaml:
    """validate_path() on a directory continues past a broken file, not crash."""

    def test_validate_path_does_not_abort_on_non_mapping_file(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.agent_api.validate import validate_paths

        # validate_paths over the whole errors/ directory: parse-error.yml must
        # produce success=False, but other files still validate (directory walk
        # must not abort on the bad file).
        results = validate_paths(
            [Path("errors/")],
            project=local_project(_PROJECT_DIR),
        )

        # There must be at least the parse-error.yml result
        assert len(results) >= 1

        # The parse-error.yml result must be a failure, not an exception.
        parse_error_results = [
            r for r in results if PurePosixPath(r.path).name == "parse-error.yml"
        ]
        assert len(parse_error_results) == 1
        assert parse_error_results[0].success is False

        # At least one other file in the directory should succeed (proves walk continues).
        other_results = [
            r for r in results if PurePosixPath(r.path).name != "parse-error.yml"
        ]
        assert any(r.success for r in other_results), (
            "Expected at least one successful result from other files in errors/"
        )


class TestCliValidateNonMappingYaml:
    """CLI: dct validate on a list-valued YAML exits non-zero with no traceback."""

    def test_cli_exits_nonzero_without_traceback(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "dct",
                "validate",
                "errors/parse-error.yml",
                "--project-dir",
                str(_PROJECT_DIR),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert result.returncode != 0, "Expected non-zero exit for invalid board"
        combined = result.stdout + result.stderr
        assert "Traceback" not in combined, (
            f"CLI should not print a traceback for a structural YAML error.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
