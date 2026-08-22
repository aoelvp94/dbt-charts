from __future__ import annotations

from dbt_charts.core.compile.models.chart.normalized import Chart

"""Tests for the TOO_MANY_X_CATEGORIES render-warning detector.

Detection rule: fires when a nominal/ordinal x-axis has > 50 distinct values.
A temporal or quantitative x-axis never trips it.
"""

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    LineChart,
    PieChart,
)
from dbt_charts.core.diagnostics import WARN_TOO_MANY_X_CATEGORIES, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    too_many_x_categories as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"cat": f"c{i}", "val": i} for i in range(n)]


def _make_ctx(chart: Chart, rows: list[dict[str, Any]], x_type: str) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"encoding": {"x": {"type": x_type}}}},
    )


def test_fires_above_threshold_on_nominal_x() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    warnings = detector.detect(_make_ctx(chart, _rows(51), "nominal"))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_TOO_MANY_X_CATEGORIES.code
    assert w.field == "cat"
    assert "51" in w.message
    assert w.fix is not None


def test_no_fire_at_threshold() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    assert detector.detect(_make_ctx(chart, _rows(50), "nominal")) == []


def test_no_fire_on_temporal_x_for_line() -> None:
    """A line chart's temporal axis is a continuous draw, not a per-x band —
    density alone is never a defect there, however many points."""
    chart = LineChart(id="c1", type="line", query_name="q", x="cat", y="val")
    assert detector.detect(_make_ctx(chart, _rows(100), "temporal")) == []


def test_fires_on_temporal_x_for_bar_above_threshold() -> None:
    """The density gate flips a bucketed temporal x-axis from ordinal to
    temporal above ~60 points — a bar still draws one band per distinct
    value regardless of the Vega-Lite encoding type, so the crowding warning
    must not go blind when that flip happens.
    """
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    warnings = detector.detect(_make_ctx(chart, _rows(200), "temporal"))
    assert len(warnings) == 1
    assert warnings[0].code == WARN_TOO_MANY_X_CATEGORIES.code
    assert "200" in warnings[0].message


def test_no_fire_on_temporal_x_for_bar_at_low_density() -> None:
    """Below the threshold, a temporal bar axis stays silent same as ordinal."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    assert detector.detect(_make_ctx(chart, _rows(50), "temporal")) == []


def test_no_fire_without_x() -> None:
    chart = PieChart(id="c1", type="pie", query_name="q", theta="val", color="cat")
    assert detector.detect(_make_ctx(chart, _rows(60), "nominal")) == []
