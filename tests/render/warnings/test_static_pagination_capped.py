"""Tests for the STATIC_PAGINATION_CAPPED render-warning detector.

Fires when a static export's table has more real pages than the renderer
will pre-draw into the artifact. The detector is policy-only: it reads the
real cap the renderer recorded (``WarningContext.static_pagination_caps``)
and emits one warning per capped table. Capturing that state from a real
render is covered by ``test_table_static_pagination_cap_capture.py``.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import TableChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.diagnostics import WARN_STATIC_PAGINATION_CAPPED
from dbt_charts.core.render.chart.table_static_pagination import StaticPaginationCap
from dbt_charts.core.render.warnings import (
    WarningContext,
    static_pagination_capped as detector,
)

from ...core._board_utils import make_test_resolved_board

_BOARD = resolve_chart_style_context(get_theme_style())


def _table_board() -> tuple[str, WarningContext]:
    chart = resolve(
        TableChart(
            id="orgs",
            title="Weekly Skip Rate, by Org",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            type="table",
        ),
        [{"org_id": "act_x", "skips": 1}],
        chart_style_context=_BOARD,
    )
    board = make_test_resolved_board(charts={chart.id: chart})
    return chart.id, WarningContext(
        board_spec=board, chart_results={chart.id: []}, vega_specs={}
    )


def test_fires_when_table_hits_cap() -> None:
    """A recorded cap produces one warning naming the table and both page counts."""
    chart_id, ctx = _table_board()
    ctx = ctx.model_copy(
        update={
            "static_pagination_caps": {
                chart_id: StaticPaginationCap(rendered_pages=20, total_pages=47)
            }
        }
    )
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    w = warnings[0]
    assert w.code == WARN_STATIC_PAGINATION_CAPPED.code
    assert w.chart == chart_id
    assert "20" in w.message and "47" in w.message
    assert w.fix is not None


def test_no_cap_no_warning() -> None:
    """Empty capture (table stayed within the cap) yields nothing."""
    _chart_id, ctx = _table_board()
    assert detector.detect(ctx) == []


def test_one_warning_per_table() -> None:
    """Two capped tables produce two warnings, each keyed to its chart."""
    chart_id, ctx = _table_board()
    ctx = ctx.model_copy(
        update={
            "static_pagination_caps": {
                chart_id: StaticPaginationCap(rendered_pages=20, total_pages=47),
                "other": StaticPaginationCap(rendered_pages=20, total_pages=30),
            }
        }
    )
    warnings = detector.detect(ctx)
    assert {w.chart for w in warnings} == {chart_id, "other"}
