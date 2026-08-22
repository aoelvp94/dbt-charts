"""CLI parity test for dct query --describe — pins the JSON wire contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()


@pytest.fixture
def project_dir(tmp_path: Path, sources_yaml: str) -> Path:
    (tmp_path / "dbt_charts.yml").write_text(sources_yaml)
    return tmp_path


class TestDescribeQueryCliJson:
    def test_json_shape_matches_describe_query_result(self, project_dir: Path) -> None:
        from dbt_charts.agent_api.describe_query import DescribeQueryResult

        result = runner.invoke(
            app,
            [
                "query",
                "db",
                "SELECT 1 AS x",
                "--describe",
                "--project-dir",
                str(project_dir),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # Validate against the Pydantic model — parity with MCP wire shape
        parsed = DescribeQueryResult.model_validate(data)
        assert parsed.success is True
        assert parsed.columns is not None
        assert parsed.columns[0].name == "x"

    def test_parse_error_json_exits_nonzero(self, project_dir: Path) -> None:
        result = runner.invoke(
            app,
            [
                "query",
                "db",
                "SELECT * FROM",
                "--describe",
                "--project-dir",
                str(project_dir),
                "--json",
            ],
        )
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["success"] is False
        assert any(d["code"] == "WARN-PARSE-ERROR" for d in data["diagnostics"])

    def test_no_sql_exits_nonzero(self, project_dir: Path) -> None:
        result = runner.invoke(
            app,
            [
                "query",
                "--describe",
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code != 0

    def test_file_flag(self, project_dir: Path, tmp_path: Path) -> None:
        sql_file = tmp_path / "q.sql"
        sql_file.write_text("SELECT 2 AS y")
        result = runner.invoke(
            app,
            [
                "query",
                "db",
                "--file",
                str(sql_file),
                "--describe",
                "--project-dir",
                str(project_dir),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["columns"][0]["name"] == "y"

    @pytest.mark.parametrize("dialect", ["duckdb", "bigquery"])
    def test_dialect_option_on_describe(self, project_dir: Path, dialect: str) -> None:
        """--dialect <value> is forwarded on source SQL --describe; exits 0."""
        from dbt_charts.agent_api.describe_query import DescribeQueryResult

        result = runner.invoke(
            app,
            [
                "query",
                "db",
                "SELECT 1 AS x",
                "--describe",
                "--dialect",
                dialect,
                "--project-dir",
                str(project_dir),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        parsed = DescribeQueryResult.model_validate(json.loads(result.output))
        assert parsed.success is True

    def test_undefined_source_returns_failure_envelope(self, project_dir: Path) -> None:
        """Unknown source context on --describe returns success=False."""
        from dbt_charts.agent_api.describe_query import DescribeQueryResult

        result = runner.invoke(
            app,
            [
                "query",
                "undefined_source",
                "SELECT 1 AS x",
                "--describe",
                "--project-dir",
                str(project_dir),
                "--json",
            ],
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        parsed = DescribeQueryResult.model_validate(data)
        assert parsed.success is False
        assert parsed.error is not None
