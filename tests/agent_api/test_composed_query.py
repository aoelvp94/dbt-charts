"""Regression tests for composed-query execution and validate paths.

Root causes fixed here:
1. `dct query BOARD NAME` failed on any query containing `{{ queries.X }}`
   with "Undefined variable: 'queries' is undefined".
2. `--validate` on a named query passed raw Jinja template text to sqlglot,
   producing false WARN-PARSE-ERROR on working SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters import AdapterRegistry, build_adapter_registry

# ---------------------------------------------------------------------------
# Fixture — reproduction board from the task worksheet (DuckDB :memory:)
# ---------------------------------------------------------------------------

_DBT_CHARTS_YML = "sources:\n  mem:\n    type: duckdb\n    path: ':memory:'\n"

_PROBE_BOARD = """\
title: probe
source: mem
variables:
  n:
    input: number
    default: 3
queries:
  base:
    sql: SELECT 1 AS one, 7 AS seven
  wrapper:
    sql: "SELECT seven, {{ n }} AS n FROM {{ queries.base }}"
  plain:
    sql: SELECT {{ n }} AS n
charts:
  k:
    query: wrapper
    type: kpi
    value: seven
"""


@pytest.fixture
def probe_registry(
    tmp_path: Path,
    local_project: Callable[..., FilesystemProject],
) -> AdapterRegistry:
    (tmp_path / "dbt_charts.yml").write_text(_DBT_CHARTS_YML)
    return build_adapter_registry(local_project(tmp_path), read_only=False)


@pytest.fixture
def probe_board_path(tmp_path: Path) -> Path:
    path = tmp_path / "probe.yml"
    path.write_text(_PROBE_BOARD)
    return path


# ---------------------------------------------------------------------------
# Root cause 1: execute path handles {{ queries.X }} composition
# ---------------------------------------------------------------------------


class TestComposedQueryExecution:
    """dct query BOARD NAME must run a query that references {{ queries.X }}."""

    def test_composed_query_returns_expected_rows(
        self,
        tmp_path: Path,
        probe_registry: AdapterRegistry,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        from dbt_charts.agent_api.query import query_board

        result = query_board(
            "wrapper",
            probe_board_path,
            local_project(tmp_path),
            adapter_registry=probe_registry,
        )
        assert result.success is True, result.errors
        # wrapper: SELECT seven, {{ n }} AS n FROM {{ queries.base }}
        # With n=3 (default): SELECT seven, 3 AS n FROM (SELECT 1 AS one, 7 AS seven) AS base
        assert result.columns == ["seven", "n"]
        assert result.data == [{"seven": 7, "n": 3}]

    def test_composed_query_matches_render_path_value(
        self,
        tmp_path: Path,
        probe_registry: AdapterRegistry,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """The KPI value on the render path is 7; the query path must produce 7 too."""
        from dbt_charts.agent_api.query import query_board

        result = query_board(
            "wrapper",
            probe_board_path,
            local_project(tmp_path),
            adapter_registry=probe_registry,
        )
        assert result.success is True, result.errors
        seven_values = [row["seven"] for row in result.data]
        assert seven_values == [7]

    def test_plain_query_still_works(
        self,
        tmp_path: Path,
        probe_registry: AdapterRegistry,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """Non-composed queries must still execute correctly."""
        from dbt_charts.agent_api.query import query_board

        result = query_board(
            "plain",
            probe_board_path,
            local_project(tmp_path),
            adapter_registry=probe_registry,
        )
        assert result.success is True, result.errors
        assert result.data == [{"n": 3}]

    def test_var_override_on_composed_query(
        self,
        tmp_path: Path,
        probe_registry: AdapterRegistry,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """--var overrides should apply when executing a composed query."""
        from dbt_charts.agent_api.query import query_board

        result = query_board(
            "wrapper",
            probe_board_path,
            local_project(tmp_path),
            adapter_registry=probe_registry,
            vars={"n": 9},
        )
        assert result.success is True, result.errors
        assert result.data == [{"seven": 7, "n": 9}]

    def test_undefined_variable_still_fails(
        self,
        tmp_path: Path,
        probe_registry: AdapterRegistry,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """The fix must not make every unknown name resolve silently."""
        board_yaml = """\
source: mem
queries:
  bad:
    sql: SELECT {{ undefined_var }} AS x
charts:
  c:
    query: bad
    type: kpi
    value: x
"""
        path = tmp_path / "bad.yml"
        path.write_text(board_yaml)
        (tmp_path / "dbt_charts.yml").write_text(_DBT_CHARTS_YML)

        from dbt_charts.agent_api.query import query_board

        result = query_board(
            "bad",
            path,
            local_project(tmp_path),
            adapter_registry=probe_registry,
        )
        assert result.success is False
        # Pin the loud path: the failure must name the missing variable, not
        # be any incidental error.
        assert any("undefined_var" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# Root cause 2: validate path renders template before linting
# ---------------------------------------------------------------------------


class TestComposedQueryValidate:
    """--validate must render the SQL template before handing it to sqlglot."""

    def test_validate_on_composed_query_reports_no_parse_error(
        self,
        tmp_path: Path,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        from dbt_charts.agent_api.query import lookup_board_query_sql
        from dbt_charts.agent_api.validate_query import validate_query

        lr = lookup_board_query_sql(
            "wrapper", probe_board_path, project=local_project(tmp_path)
        )
        assert lr.success is True, lr.errors
        diagnostics = validate_query(lr.sql)
        # No WARN-PARSE-ERROR — the linter received valid SQL, not a Jinja template
        codes = {d.code for d in diagnostics}
        assert "WARN-PARSE-ERROR" not in codes, (
            f"validate returned a parse error on composed query: {diagnostics}"
        )

    def test_validate_with_var_override_binds_value(
        self,
        tmp_path: Path,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """--var n=9 should produce SQL with 9, not {{ n }}."""
        from dbt_charts.agent_api.query import lookup_board_query_sql

        lr = lookup_board_query_sql(
            "wrapper",
            probe_board_path,
            project=local_project(tmp_path),
            vars={"n": 9},
        )
        assert lr.success is True, lr.errors
        # The rendered SQL should not contain any Jinja tokens
        assert "{{" not in lr.sql
        assert "}}" not in lr.sql

    def test_lookup_plain_query_renders_variable(
        self,
        tmp_path: Path,
        probe_board_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """Even a non-composed query's variables should be rendered."""
        from dbt_charts.agent_api.query import lookup_board_query_sql

        lr = lookup_board_query_sql(
            "plain", probe_board_path, project=local_project(tmp_path)
        )
        assert lr.success is True, lr.errors
        assert "{{" not in lr.sql
