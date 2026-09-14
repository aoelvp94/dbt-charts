"""ERR-CHART-PAINTED-NO-MARKS must not depend on how long the series is.

The guard fired on a 37-point blank chart and stayed silent on an 11-point one
rendered from the same misconfiguration. The row count is not supposed to be an
input: a chart that received rows and painted nothing is broken at any length.

The hole was in the vote, not the threshold. A line layer with no data at all
emits ``<path stroke=…>`` carrying no ``d``; the measurer read that as geometry
it could not parse and abstained, leaving nothing to vote and an empty vote
reading as "not degenerate". A longer series happened to take a code path whose
SVG also carried a measurable zero-extent mark, so only the long one voted.

Fault injection is the honest way to pin this: the blank render that motivated
the guard is fixed (see ``test_bucket_start_alignment.py``), so the bucket
lookup is put back to its pre-fix form here to produce a genuinely blank chart
on demand, at several lengths.
"""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Any
from unittest.mock import Mock

import pytest

from dbt_charts.core.compile import compile as compile_board
from dbt_charts.core.execute import Executor
from dbt_charts.core.render import render
from dbt_charts.core.render.chart import time_unit_detect

_BOARD = """
queries:
  q:
    sql: SELECT * FROM t
    source: s
charts:
  c:
    title: probe
    query: q
    type: line
    x: x
    y: y
    style:
      axis_x:
        time_unit: yearmonth
rows:
  - c
"""


def _month_end(index: int) -> str:
    year, month = 2023 + index // 12, index % 12 + 1
    return f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"


def _render_blank(rows: list[dict[str, Any]]) -> list[str]:
    result = compile_board(_BOARD)
    assert result.success and result.board is not None, result.errors
    query_result = Mock(
        is_success=True,
        data=rows,
        column_descriptions=None,
        resolved_relations=None,
        truncated_reason=None,
    )
    adapter_registry = Mock()
    adapter_registry.execute.return_value = query_result
    executor = Executor(
        result.board,
        adapter_registry=adapter_registry,
        query_registry=result.query_registry,
    )
    return [e.code for e in render(result.board, executor, format="svg").chart_errors]


@pytest.fixture
def unfloored_bucket_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Key each row at its own date again, so no row matches its bucket."""

    def _raw(date: dt.date, time_unit: str, _fiscal: int, anchor: dt.date) -> dt.date:
        return date

    monkeypatch.setattr(time_unit_detect, "_enclosing_bucket", _raw)


@pytest.mark.usefixtures("unfloored_bucket_lookup")
@pytest.mark.parametrize("n_points", [3, 11, 37])
def test_guard_fires_at_every_series_length(n_points: int) -> None:
    rows: list[dict[str, Any]] = [
        {"x": _month_end(i), "y": 100 + i} for i in range(n_points)
    ]
    assert _render_blank(rows) == ["ERR-CHART-PAINTED-NO-MARKS"]


@pytest.mark.parametrize("n_points", [3, 11, 37])
def test_guard_is_silent_once_the_rows_reach_their_buckets(n_points: int) -> None:
    """The same board without the fault injection: nothing to report."""
    rows: list[dict[str, Any]] = [
        {"x": _month_end(i), "y": 100 + i} for i in range(n_points)
    ]
    assert _render_blank(rows) == []
