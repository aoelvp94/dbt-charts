"""End-to-end: TABLE_COLUMNS_OVERFLOW surfaces from render() for a cramped table.

Proves the full seam — the table renderer records its real slot overflow, then
renderer.py threads that capture into the WarningContext, and the detector's
warning lands on RenderResult.warnings — that a table with room to render
stays silent, and that a data format (json/text/yaml/data) reports the same
warning as svg: every format draws the board before choosing what to emit, so
the capture that feeds this detector is never empty just because the caller
asked for data instead of svg.
"""

from __future__ import annotations

from unittest.mock import Mock

from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.render import render


def _rows(n: int) -> list[dict[str, object]]:
    return [
        {
            "org_id": "act_2zGAXPCi8w3MckVTMpVT3OSQ3Ni",
            "table_name": "weekly_skip_events",
            "skips": 175000,
            "clones": 226,
            "views": 439000000,
        }
        for _ in range(n)
    ]


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


_NARROW = """
title: Cramped table
charts:
  orgs:
    query: q
    type: table
  filler_text:
    query: q
    type: kpi
    value: skips
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
cols:
  - id: narrow
    width: 220
    rows:
      - orgs
  - filler_text
"""

_ROOMY = """
title: Roomy table
charts:
  orgs:
    query: q
    type: table
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
rows:
  - orgs
"""


def test_cramped_table_warns() -> None:
    """Five wide columns forced into a 220px tile overflow it — the warning fires."""
    result = compile(_NARROW)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows(5))

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-TABLE-COLUMNS-OVERFLOW" in codes, (
        "five wide columns crammed into a 220px tile overflow it — the warning "
        "must surface on warnings"
    )
    warning = next(
        w for w in render_result.warnings if w.code == "WARN-TABLE-COLUMNS-OVERFLOW"
    )
    assert warning.chart == "orgs"
    assert warning.fix


def test_roomy_table_silent() -> None:
    """A table with a full-width row has room; the warning stays quiet."""
    result = compile(_ROOMY)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows(5))

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-TABLE-COLUMNS-OVERFLOW" not in codes


def test_non_svg_format_reports_same_warning_as_svg() -> None:
    """JSON output draws the board the same as svg, so it reports the same
    overflow warning — not the empty capture a data walk alone would produce.
    """
    result = compile(_NARROW)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows(5))

    render_result = render(result.board, executor, format="json")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-TABLE-COLUMNS-OVERFLOW" in codes
