"""Tests for the PIE_TOO_MANY_SEGMENTS render-warning detector.

Detection rule: fires on pie charts whose query returns more than _MAX_SEGMENTS
(5) slices — too many angles to compare.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import BarChart, Chart, PieChart
from dbt_charts.core.diagnostics import WARN_PIE_TOO_MANY_SEGMENTS, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    pie_too_many_segments as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _make_pie(**kwargs: object) -> Chart:
    return PieChart(**{"id": "c1", "type": "pie", "query_name": "q", **kwargs})


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"category": f"cat{i}", "amount": 10} for i in range(n)]


def _make_ctx(chart: Chart, rows: list[dict[str, Any]]) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"mark": "arc"}},
    )


def test_fires_when_more_than_five_segments() -> None:
    chart = _make_pie(theta="amount", color="category")
    warnings = detector.detect(_make_ctx(chart, _rows(6)))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_PIE_TOO_MANY_SEGMENTS.code
    assert w.chart == "c1"
    assert "6" in w.message
    assert w.fix is not None


def test_no_fire_at_five_segments() -> None:
    chart = _make_pie(theta="amount", color="category")
    assert detector.detect(_make_ctx(chart, _rows(5))) == []


def test_no_fire_for_non_pie() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", x="category", y="amount")
    assert detector.detect(_make_ctx(chart, _rows(20))) == []


def test_no_fire_when_chart_absent_from_results() -> None:
    chart = _make_pie(theta="amount", color="category")
    resolved = make_test_resolved_chart(chart, _rows(6))
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(board_spec=board, chart_results={}, vega_specs={})
    assert detector.detect(ctx) == []
