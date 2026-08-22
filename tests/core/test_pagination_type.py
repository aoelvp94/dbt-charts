"""Regression: ResolvedChartDefaults.pagination must be typed PaginationConfig | None."""

from __future__ import annotations

import typing

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import TableChart


def test_pagination_field_is_paginationconfig():
    from dbt_charts.core.compile.models.style.authored import PaginationConfig
    from dbt_charts.core.compile.models.style.resolved import (
        ResolvedChartDefaults,
    )

    hints = typing.get_type_hints(ResolvedChartDefaults)
    ann = hints["pagination"]
    args = getattr(ann, "__args__", ())
    assert PaginationConfig in args, (
        f"ResolvedChartDefaults.pagination annotation should be PaginationConfig | None, got {ann}"
    )


def test_chart_local_pagination_propagates_via_cascade():
    """Chart-local style.pagination flows through build_chart_style_context onto
    resolved_style.pagination — the renderer reads the merged value from
    there, no separate "primary vs default" resolver helper required.
    """
    from dbt_charts.core.compile.models.style.authored import (
        TableChartStylePatch,
    )
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context,
    )

    board = resolve_chart_style_context(get_theme_style())
    patch = TableChartStylePatch(pagination={"enabled": True, "page_rows": 25})
    merged = build_chart_style_context(
        board, TableChart(id="t", type="table", style=patch)
    )
    assert merged.pagination is not None
    assert merged.pagination.page_rows == 25
