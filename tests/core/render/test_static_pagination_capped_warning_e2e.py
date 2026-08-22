"""End-to-end: STATIC_PAGINATION_CAPPED surfaces from render() for a table
whose static export exceeds the pre-render page cap.

Proves the full seam — the table renderer records the real cap it hit, then
renderer.py threads that capture into the WarningContext, and the detector's
warning lands on RenderResult.warnings — and that a table within the cap,
and non-SVG formats, stay silent.
"""

from __future__ import annotations

from unittest.mock import Mock

from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.render import render
from dbt_charts.core.render.chart.table import _STATIC_MULTI_PAGE_MAX_PAGES


def _rows(n: int) -> list[dict[str, object]]:
    return [{"name": f"row_{i}", "value": i} for i in range(1, n + 1)]


def _make_executor(
    board: object, query_registry: object, rows: list[dict[str, object]]
):
    ok = Mock()
    ok.is_success = True
    ok.data = rows
    ok.column_descriptions = None
    ok.resolved_relations = None
    ok.truncated_reason = None
    mock_registry = Mock()
    mock_registry.execute.return_value = ok
    return Executor(
        board, adapter_registry=mock_registry, query_registry=query_registry
    )


_BOARD = """
title: Big table
charts:
  orgs:
    query: q
    type: table
    style:
      pagination:
        enabled: true
        page_rows: 5
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
rows:
  - orgs
"""


def test_table_beyond_cap_warns() -> None:
    """More real pages than the cap allows — the warning fires with both counts."""
    result = compile(_BOARD)
    assert result.success and result.board is not None, result.errors
    n_rows = (_STATIC_MULTI_PAGE_MAX_PAGES + 5) * 5
    executor = _make_executor(result.board, result.query_registry, _rows(n_rows))

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-STATIC-PAGINATION-CAPPED" in codes
    warning = next(
        w for w in render_result.warnings if w.code == "WARN-STATIC-PAGINATION-CAPPED"
    )
    assert warning.chart == "orgs"
    assert warning.fix
    assert str(_STATIC_MULTI_PAGE_MAX_PAGES) in warning.message


def test_table_within_cap_silent() -> None:
    """A table whose real page count fits the cap stays quiet."""
    result = compile(_BOARD)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows(20))

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-STATIC-PAGINATION-CAPPED" not in codes


def test_non_svg_format_silent() -> None:
    """JSON output never rasterizes a table, so it captures no page cap."""
    result = compile(_BOARD)
    assert result.success and result.board is not None, result.errors
    n_rows = (_STATIC_MULTI_PAGE_MAX_PAGES + 5) * 5
    executor = _make_executor(result.board, result.query_registry, _rows(n_rows))

    render_result = render(result.board, executor, format="json")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-STATIC-PAGINATION-CAPPED" not in codes
