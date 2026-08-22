"""Tests for the TEMPORAL_SINGLE_POINT render-warning detector.

Detection rule: fires on line/area charts with a temporal x-axis when the
query result has exactly one row (a trend chart that's a single dot/vertical line).
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from dbt_charts.core.compile.models.chart.normalized import BarChart, Chart
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.diagnostics import WARN_TEMPORAL_SINGLE_POINT, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    temporal_single_point as detector,
)

from ...core._board_utils import (
    make_test_resolved_board,
    make_test_resolved_chart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LINE_CHART_DEFAULTS = {
    "id": "c1",
    "type": "line",
    "query_name": "q",
    "title": "",
}


def _make_chart(**kwargs: object) -> Chart:
    return TypeAdapter(Chart).validate_python(
        dict(**{**_LINE_CHART_DEFAULTS, **kwargs})
    )


def _make_ctx(
    chart: Chart,
    rows: list[dict[str, Any]],
    x_vega_type: str = "temporal",
) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    x_field = (
        resolved.x if isinstance(resolved, _CartesianResolvedChartFields) else None
    )
    vega_spec: dict[str, Any] = {
        "mark": resolved.chart_type,
        "encoding": {
            "x": {"field": x_field or "date", "type": x_vega_type},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: vega_spec},
    )


# One row of temporal data.
_ONE_ROW = [{"date": "2024-01-01", "value": 42}]
# Ten rows of temporal data.
_TEN_ROWS = [{"date": f"2024-01-{i:02d}", "value": i * 10} for i in range(1, 11)]


# ---------------------------------------------------------------------------
# True-positive: line + temporal + exactly 1 row
# ---------------------------------------------------------------------------


def test_fires_for_line_temporal_one_row() -> None:
    """Canonical case: line chart with temporal x and a single data point."""
    chart = _make_chart(x="date")
    ctx = _make_ctx(chart, _ONE_ROW)
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_TEMPORAL_SINGLE_POINT.code
    assert w.chart == "c1"
    assert w.field == "date"
    assert w.message
    assert w.fix


# ---------------------------------------------------------------------------
# True-positive: area + temporal + exactly 1 row
# ---------------------------------------------------------------------------


def test_fires_for_area_temporal_one_row() -> None:
    """Area chart with temporal x and a single data point must also fire."""
    chart = _make_chart(id="c2", type="area", x="date")
    ctx = _make_ctx(chart, _ONE_ROW)
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    w = warnings[0]
    assert w.code == WARN_TEMPORAL_SINGLE_POINT.code
    assert w.chart == "c2"


# ---------------------------------------------------------------------------
# True-negative: line + temporal + 2+ rows
# ---------------------------------------------------------------------------


def test_no_fire_for_line_temporal_ten_rows() -> None:
    """Multiple data points — no single-point pathology."""
    chart = _make_chart(x="date")
    ctx = _make_ctx(chart, _TEN_ROWS)
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# True-negative: line + ordinal x + 1 row
# ---------------------------------------------------------------------------


def test_no_fire_for_line_ordinal_one_row() -> None:
    """Ordinal x-axis (categorical) with one row must not fire."""
    chart = _make_chart(x="category")
    ctx = _make_ctx(chart, [{"category": "A", "value": 10}], x_vega_type="ordinal")
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# True-negative: bar chart with temporal x + 1 row
# ---------------------------------------------------------------------------


def test_no_fire_for_bar_temporal_one_row() -> None:
    """Bar charts are out of scope for this detector."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="date")
    ctx = _make_ctx(chart, _ONE_ROW)
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# True-negative: line + temporal + 0 rows
# ---------------------------------------------------------------------------


def test_no_fire_for_line_temporal_zero_rows() -> None:
    """Zero rows does not trigger the single-point warning."""
    chart = _make_chart(x="date")
    ctx = _make_ctx(chart, [])
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# Guard: chart id absent from chart_results
# ---------------------------------------------------------------------------


def test_no_fire_when_chart_not_in_chart_results() -> None:
    """Charts absent from chart_results (failed execution) must be skipped."""
    chart = _make_chart(x="date")
    resolved = make_test_resolved_chart(chart)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    vega_spec: dict[str, Any] = {
        "mark": "line",
        "encoding": {
            "x": {"field": "date", "type": "temporal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    ctx = WarningContext(
        board_spec=board,
        chart_results={},  # chart absent from results
        vega_specs={resolved.id: vega_spec},
    )
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# Guard: chart id absent from vega_specs
# ---------------------------------------------------------------------------


def test_no_fire_when_chart_not_in_vega_specs() -> None:
    """Detector must skip charts absent from ctx.vega_specs (sparse dict)."""
    chart = _make_chart(x="date")
    resolved = make_test_resolved_chart(chart, _ONE_ROW)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: _ONE_ROW},
        vega_specs={},  # chart absent from vega_specs
    )
    assert detector.detect(ctx) == []
