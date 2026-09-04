"""Tests for grouped border: BorderStylePatch | None on ChartStylePatch.

TDD pre-condition: these tests must fail before any production-code edit and
pass only after the migration is complete. Run with:
    just test dbt-charts/tests/core/compile/test_chart_border_grouped.py

Exercised against kpi, not bar: kpi draws its own card by hand and its
``border`` slot is a full stroke (width/color/radius/dash). bar, line, area,
scatter, histogram, heatmap, pie, and donut have no per-chart card to paint a
border onto — they emit via Vega-Lite with no card surface separate from the
board frame — so they structurally reject ``style.border`` and their patch
types have no border field to test. spark_bar is unsuitable for a different
reason: it draws a card, but its ``border`` slot is corner rounding only.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.chart.normalized import Chart, KpiChart
from dbt_charts.core.compile.models.primitives import BorderStylePatch
from dbt_charts.core.compile.models.style.authored import (
    ChartStylePatch,
    KpiChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context


def _board():
    return resolve_chart_style_context(get_theme_style())


def _chart(**kwargs) -> Chart:
    defaults = {"id": "test", "type": "kpi", "value": "b"}
    defaults.update(kwargs)
    return KpiChart(**defaults)


def test_chartstylepatch_border_grouped():
    """Dict form parses; all three fields readable on the resulting patch."""
    patch = KpiChartStylePatch(border={"radius": 6.0, "color": "#aaa", "width": 1.0})
    assert isinstance(patch.border, BorderStylePatch)
    assert patch.border.radius == 6.0
    assert patch.border.color == "#aaa"
    assert patch.border.width == 1.0


def test_chartstylepatch_border_css_shorthand():
    """CSS shorthand string parses via BorderStylePatch.from_css."""
    patch = KpiChartStylePatch(border="2px #aaa")
    assert isinstance(patch.border, BorderStylePatch)
    assert patch.border.width == 2.0
    assert patch.border.color == "#aaa"


def test_chartstylepatch_rejects_flat_border_color():
    """border_color at chart-level raises extra='forbid' ValidationError."""
    assert ChartStylePatch.model_config.get("extra") == "forbid", (
        "ChartStylePatch must declare extra='forbid' for this test to be meaningful"
    )
    with pytest.raises(ValidationError, match="border_color"):
        ChartStylePatch.model_validate({"border_color": "#aaa"})


def test_chartstylepatch_rejects_flat_border_radius():
    """border_radius at chart-level raises extra='forbid' ValidationError."""
    with pytest.raises(ValidationError, match="border_radius"):
        ChartStylePatch.model_validate({"border_radius": 4})


def test_chart_local_border_does_not_cascade():
    """A kpi-chart-level border does NOT propagate to a nested table.border.

    Proves the chart-local-only contract: box properties reset per level and
    are not inherited by nested elements.
    """
    board = _board()
    # The whole slot, not a field off it: table inherits the shared card border
    # (None when unauthored) rather than declaring its own.
    theme_table_border = board.table.border

    chart = _chart(
        style=KpiChartStylePatch(border={"radius": 99.0, "color": "#abc", "width": 3.0})
    )
    resolve(chart, [{"b": 1}], chart_style_context=board)

    # The KPI chart's chart-local border must NOT bleed into table.border:
    # box properties reset per level and are not inherited by nested elements.
    assert board.table.border == theme_table_border


def test_resolved_chart_border_falls_back_to_theme_when_unauthored():
    """When a chart has no border block, the resolved border uses the board's distinctive value.

    Uses a sentinel radius to prove cascade rather than reading both values from
    the same object (which would not exercise the cascade at all).
    """
    from dbt_charts.core.compile.config import reset_config

    reset_config()
    base_style = get_theme_style()
    _SENTINEL_RADIUS = 42.0
    patched_style = base_style.model_copy(
        update={
            "charts": base_style.charts.model_copy(
                update={
                    "border": base_style.charts.border.model_copy(
                        update={"radius": _SENTINEL_RADIUS}
                    )
                }
            )
        }
    )
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    board = resolve_chart_style_context(patched_style)
    chart = _chart()  # no authored border
    resolve(chart, [{"b": 1}], chart_style_context=board)

    # The sentinel radius must propagate from the board (charts.border.radius).
    assert board.border.radius == _SENTINEL_RADIUS
