"""Tests for the REDUNDANT_ENCODING render-warning detector.

Detection rule: fires when one field is bound to >= 2 encoding channels
({x, y, color, size, shape, theta}). The bar x==color case is excluded —
the renderer suppresses the grouped-bar offset and produces valid colored bars.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.diagnostics import WARN_REDUNDANT_ENCODING, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    redundant_encoding as detector,
)

from ...core._board_utils import (
    make_test_resolved_board,
    make_test_resolved_chart,
)


def _make_chart(**kwargs: object) -> Chart:
    return TypeAdapter(Chart).validate_python(
        dict(**{"id": "c1", "query_name": "q", "title": "", **kwargs})
    )


def _make_ctx(chart: Chart) -> WarningContext:
    resolved = make_test_resolved_chart(chart)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board, chart_results={resolved.id: []}, vega_specs={}
    )


def test_fires_when_color_equals_x_on_non_bar() -> None:
    """x==color on a line chart → fires REDUNDANT_ENCODING."""
    chart = _make_chart(type="line", x="category", y="val", color="category")
    warnings = detector.detect(_make_ctx(chart))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_REDUNDANT_ENCODING.code
    assert w.field == "category"
    assert "color" in w.message and "x" in w.message


def test_fires_when_color_equals_y() -> None:
    """y==color → redundant regardless of chart type."""
    chart = _make_chart(type="bar", x="category", y="val", color="val")
    warnings = detector.detect(_make_ctx(chart))
    assert len(warnings) == 1
    assert warnings[0].field == "val"


def test_excludes_bar_x_equals_color() -> None:
    """bar x==color: renderer produces valid colored bars, no warning needed."""
    chart = _make_chart(type="bar", x="category", y="val", color="category")
    assert detector.detect(_make_ctx(chart)) == []


def test_no_fire_when_all_channels_distinct() -> None:
    chart = _make_chart(type="bar", x="category", y="val", color="region")
    assert detector.detect(_make_ctx(chart)) == []


def test_no_fire_with_single_channel() -> None:
    chart = _make_chart(type="bar", x="category", y="val")
    assert detector.detect(_make_ctx(chart)) == []


def test_list_y_multiseries_not_flagged() -> None:
    """Multi-series y fields are not flagged as redundant encoding."""
    chart = _make_chart(type="line", x="month", y=["a", "b"])
    assert detector.detect(_make_ctx(chart)) == []
