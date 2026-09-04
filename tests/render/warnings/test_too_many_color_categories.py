"""Tests for the TOO_MANY_COLOR_CATEGORIES render-warning detector.

Detection rule: fires when a nominal/ordinal color encoding has > 12 distinct
values. A quantitative (gradient) color never trips it.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    Chart,
    LineChart,
    ScatterChart,
)
from dbt_charts.core.diagnostics import WARN_TOO_MANY_COLOR_CATEGORIES, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    too_many_color_categories as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"x": i, "val": i, "series": f"s{i}"} for i in range(n)]


def _make_ctx(
    chart: Chart, rows: list[dict[str, Any]], color_type: str
) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"encoding": {"color": {"type": color_type}}}},
    )


def test_fires_above_threshold_on_nominal_color() -> None:
    chart = LineChart(
        id="c1", type="line", query_name="q", x="x", y="val", color="series"
    )
    warnings = detector.detect(_make_ctx(chart, _rows(13), "nominal"))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_TOO_MANY_COLOR_CATEGORIES.code
    assert w.field == "series"
    assert "13" in w.message
    assert w.fix is not None


def test_no_fire_at_threshold() -> None:
    chart = LineChart(
        id="c1", type="line", query_name="q", x="x", y="val", color="series"
    )
    assert detector.detect(_make_ctx(chart, _rows(12), "nominal")) == []


def test_no_fire_on_quantitative_color() -> None:
    """A continuous color gradient is not a categorical legend."""
    chart = ScatterChart(
        id="c1", type="scatter", query_name="q", x="x", y="val", color="series"
    )
    assert detector.detect(_make_ctx(chart, _rows(40), "quantitative")) == []


def test_no_fire_without_color() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", x="x", y="val")
    assert detector.detect(_make_ctx(chart, _rows(40), "nominal")) == []


def _wide_rows(lists: int) -> list[dict[str, Any]]:
    return [
        {"x": i, "list": f"l{j}", "a": i, "b": i, "c": i}
        for i in range(3)
        for j in range(lists)
    ]


def test_fires_on_wide_chart_whose_composite_series_exceed_the_palette() -> None:
    """The series a wide chart renders are its fold's composites (measures ×
    dimension), which no raw row carries — counting must see the unfolded rows."""
    chart = BarChart(
        id="c1", type="bar", query_name="q", x="x", y=["a", "b", "c"], color="list"
    )
    warnings = detector.detect(_make_ctx(chart, _wide_rows(5), "nominal"))
    assert len(warnings) == 1
    assert "15" in warnings[0].message


def test_fires_on_wide_chart_without_color_and_names_y() -> None:
    measures = [f"m{i:02d}" for i in range(13)]
    chart = BarChart(id="c1", type="bar", query_name="q", x="x", y=measures)
    rows = [{"x": i, **dict.fromkeys(measures, i)} for i in range(3)]
    warnings = detector.detect(_make_ctx(chart, rows, "nominal"))
    assert len(warnings) == 1
    assert warnings[0].field == "y"
    assert warnings[0].path == "charts.c1.y"


def test_no_fire_on_wide_chart_within_the_palette() -> None:
    chart = BarChart(
        id="c1", type="bar", query_name="q", x="x", y=["a", "b", "c"], color="list"
    )
    assert detector.detect(_make_ctx(chart, _wide_rows(4), "nominal")) == []
