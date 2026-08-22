"""The table renderer records a static-export page cap into the sink.

STATIC_PAGINATION_CAPPED is driven by what the renderer actually did, not an
estimate. These tests render real tables and assert the sink reflects the
render: a table whose real page count exceeds the pre-render cap records the
cap; a table within the cap records nothing; and with no sink open, recording
is a no-op.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import TableChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import TableChartStylePatch
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.table import (
    _STATIC_MULTI_PAGE_MAX_PAGES,
    render_table_svg,
)
from dbt_charts.core.render.chart.table_static_pagination import (
    StaticPaginationCap,
    collect_static_pagination_caps,
)

_BOARD_RS, _BOARD_CTX = resolve_style_and_context(get_theme_style())


def _data(n: int) -> list[dict[str, Any]]:
    return [{"name": f"row_{i}", "value": i} for i in range(1, n + 1)]


def _render(n_rows: int, sink_open: bool) -> dict[str, StaticPaginationCap]:
    chart = resolve(
        TableChart(
            id="orgs",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            type="table",
            style=TableChartStylePatch(pagination={"enabled": True, "page_rows": 5}),
        ),
        _data(n_rows),
        chart_style_context=_BOARD_CTX,
    )
    if not sink_open:
        render_table_svg(chart, _data(n_rows), width=600, board_style=_BOARD_RS)
        return {}
    with collect_static_pagination_caps() as sink:
        render_table_svg(chart, _data(n_rows), width=600, board_style=_BOARD_RS)
        return sink


def test_table_over_cap_records_it() -> None:
    """More real pages than the cap allows — the sink records the truncation."""
    n_rows = (_STATIC_MULTI_PAGE_MAX_PAGES + 5) * 5  # page_rows=5
    sink = _render(n_rows, sink_open=True)
    assert "orgs" in sink
    cap = sink["orgs"]
    assert cap.rendered_pages == _STATIC_MULTI_PAGE_MAX_PAGES
    assert cap.total_pages == _STATIC_MULTI_PAGE_MAX_PAGES + 5


def test_table_within_cap_records_nothing() -> None:
    """Real page count fits the cap — nothing recorded."""
    sink = _render(20, sink_open=True)  # 4 pages of 5
    assert "orgs" not in sink


def test_no_sink_is_noop() -> None:
    """Rendering without an open sink must not raise (recording is a no-op)."""
    n_rows = (_STATIC_MULTI_PAGE_MAX_PAGES + 5) * 5
    assert _render(n_rows, sink_open=False) == {}
