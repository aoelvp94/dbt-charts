"""`lookup_board_query_sql` previews the SQL execution would send: the same
variable coercion, and the filter helpers spelled for the source's dialect."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dbt_charts.agent_api.query import lookup_board_query_sql
from dbt_charts.cli.filesystem_project import FilesystemProject

BOARD = """
variables:
  year:
    input: select
    data_type: number
    options:
      query: years
  span:
    input: daterange
    default: ['2024-01-01', '2024-01-31']
queries:
  years:
    sql: SELECT 2024 AS year
    source: db
  main:
    sql: |
      SELECT * FROM t WHERE {{ filter('year', year) }}
      AND {{ filter_date_range('day', span) }}
    source: db
charts:
  c:
    type: kpi
    query: main
    value: year
"""


def _project(
    tmp_path: Path, local_project: Callable[..., FilesystemProject], source_type: str
) -> FilesystemProject:
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "b.yml").write_text(BOARD)
    detail = "profile: p" if source_type == "dbt_profile" else "path: x.db"
    (tmp_path / "dbt_charts.yml").write_text(
        f"sources:\n  db:\n    type: {source_type}\n    {detail}\n"
    )
    return local_project(tmp_path)


def test_preview_spells_helpers_for_the_sources_dialect(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    project = _project(tmp_path, local_project, "sqlite")
    result = lookup_board_query_sql("main", Path("charts/b.yml"), project=project)
    assert result.success, result.errors
    assert result.sql is not None
    assert "DATE(day) BETWEEN" in result.sql


def test_preview_coerces_values_like_execution(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    project = _project(tmp_path, local_project, "sqlite")
    result = lookup_board_query_sql(
        "main", Path("charts/b.yml"), project=project, vars={"year": "twenty"}
    )
    assert not result.success
    assert any("must be numeric" in e for e in result.errors), result.errors


def test_preview_of_a_source_without_a_knowable_dialect_uses_the_default(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """A `dbt_profile` source's warehouse is only known at execute; the
    preview still renders, in the default dialect's spelling."""
    project = _project(tmp_path, local_project, "dbt_profile")
    result = lookup_board_query_sql("main", Path("charts/b.yml"), project=project)
    assert result.success, result.errors
    assert result.sql is not None
    assert "CAST(day AS DATE) BETWEEN" in result.sql
