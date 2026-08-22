"""Tests for the LAYOUT_MIN_EXCEEDS_HEIGHT render-warning detector.

Detection rule: fires on a horizontal bar chart when the category-count
readability floor (min_height_for_horizontal_bar_categories — the same
floor vega_lite.py's _render_vl_artifact applies at render time) exceeds
ctx.authored_chart_heights' entry for that chart.

These are unit tests for the comparison logic only, driven by a hand-set
authored_chart_heights value — they do NOT prove renderer.py actually
computes that value correctly for a real board (a hand-built WarningContext
can pass while the real pipeline stays silent). The end-to-end gate for
that is dbt-charts/tests/core/render/test_layout_min_exceeds_height_warning_e2e.py,
which goes through compile() -> render() and reads RenderResult.warnings.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import BarChart, LineChart
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.diagnostics import WARN_LAYOUT_MIN_EXCEEDS_HEIGHT, Diagnostic
from dbt_charts.core.render.chart.emitters._cartesian import (
    min_height_for_horizontal_bar_categories,
)
from dbt_charts.core.render.warnings import (
    WarningContext,
    layout_min_exceeds_height as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"cat": f"c{i:02d}", "val": i} for i in range(n)]


def _horizontal_bar() -> BarChart:
    return BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="cat",
        y="val",
        # model_construct, not the normal constructor: BarChartStylePatch's
        # TYPE_CHECKING stub aliases the full (non-optional) BarChartStyle, so
        # pyright demands every theme field here in this strictly-swept dir.
        style=BarChartStylePatch.model_construct(orientation="horizontal"),
    )


def _ctx(
    chart: Any,
    rows: list[dict[str, Any]],
    authored_height: float | None,
) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    authored_chart_heights = (
        {resolved.id: authored_height} if authored_height is not None else {}
    )
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={},
        authored_chart_heights=authored_chart_heights,
    )


def test_fires_when_authored_height_below_category_floor() -> None:
    """17 categories exceed the theme's category-count floor; the row
    authored only 280px, well under it."""
    chart = _horizontal_bar()
    rows = _rows(17)
    ctx = _ctx(chart, rows, authored_height=280.0)
    resolved = ctx.board_spec.charts["c1"]
    assert isinstance(resolved, ResolvedBarChart)
    expected_min_h = min_height_for_horizontal_bar_categories(
        17, resolved.style.axis_x, resolved.style.mark.size
    )
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_LAYOUT_MIN_EXCEEDS_HEIGHT.code
    assert w.chart == "c1"
    assert "17" in w.message
    assert f"{expected_min_h:.0f}" in w.message
    assert "280" in w.message
    assert w.fix is not None


def test_silent_when_authored_height_comfortably_above_floor() -> None:
    """3 categories need ~189px; the row authored 900px — nowhere near the floor."""
    chart = _horizontal_bar()
    rows = _rows(3)
    assert detector.detect(_ctx(chart, rows, authored_height=900.0)) == []


def test_silent_when_nothing_was_authored() -> None:
    """No entry in authored_chart_heights at all -> nothing was overridden."""
    chart = _horizontal_bar()
    rows = _rows(17)
    assert detector.detect(_ctx(chart, rows, authored_height=None)) == []


def test_silent_on_vertical_bar() -> None:
    """Vertical bars band along width, not height — this detector doesn't apply."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="cat",
        y="val",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _rows(17)
    assert detector.detect(_ctx(chart, rows, authored_height=280.0)) == []


def test_silent_on_non_bar_chart() -> None:
    chart = LineChart(id="c1", type="line", query_name="q", x="cat", y="val")
    rows = _rows(17)
    assert detector.detect(_ctx(chart, rows, authored_height=280.0)) == []


def test_silent_when_chart_has_no_authored_height_entry() -> None:
    """A chart absent from authored_chart_heights has no cap to violate."""
    chart = _horizontal_bar()
    rows = _rows(17)
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={},
        authored_chart_heights={},
    )
    assert detector.detect(ctx) == []


def test_silent_without_chart_results() -> None:
    """No executed rows means no category count to judge."""
    chart = _horizontal_bar()
    assert detector.detect(_ctx(chart, [], authored_height=280.0)) == []
