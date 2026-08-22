"""Regression coverage for a chart-local axis_x/axis_y override reaching the
resolved axis, across every cartesian family (plus histogram).

`_bake_cartesian_axes` (called once from `plan_cartesian()`) always takes the
board-level `chart_style_context`, never a per-chart one: see
`compile/resolve/chart/AGENTS.md`'s "The axis-cascade context" section.
Chart-local `style.axis_x`/`style.axis_y` overrides are `SkipInheritSlots`
fields on `_CartesianChartStyle`, so cascade Layers 1-3 (which read
`ctx.<family>.axis_x`, the one layer that would differ between a board-level
and chart-local context) never see them at all: `_extract_axis_overrides`
pulls them out separately, and Layers 11-13 re-apply that same `AxisOverrides`
patch last-write-wins regardless of which context backed Layers 1-3.

This test does not itself distinguish the board-level and chart-local
spellings; both make the override survive, by the mechanism above, so a
regression that swapped `_bake_cartesian_axes`'s context argument would not
fail this test. What it does pin: the override reaches the resolved axis for
every family today, so a future change to `SkipInheritSlots`, layer ordering,
or `_extract_axis_overrides` that broke that path would.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    Chart,
    HeatmapChart,
    LineChart,
    ScatterChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    BarChartStylePatch,
    HeatmapChartStylePatch,
    LineChartStylePatch,
    ScatterChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

_AXIS_X_COLOR = "#123456"
_AXIS_Y_COLOR = "#654321"

_STYLE_OVERRIDE: dict[str, Any] = {
    "axis_x": {"labels": {"font": {"color": _AXIS_X_COLOR}}},
    "axis_y": {"labels": {"font": {"color": _AXIS_Y_COLOR}}},
}


@pytest.fixture(autouse=True)
def _reset() -> Any:
    reset_config()
    yield
    reset_config()


def _board() -> Any:
    return resolve_chart_style_context(get_theme_style())


def _sql() -> SqlQuery:
    return SqlQuery(sql="SELECT 1", source="t")


def _bar(**kwargs: Any) -> BarChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "bar",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
        "style": BarChartStylePatch.model_validate(_STYLE_OVERRIDE),
    }
    defaults.update(kwargs)
    return BarChart(**defaults)


def _histogram(**kwargs: Any) -> BarChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "histogram",
        "x": "value",
        "y": None,
        "query": _sql(),
        "query_name": "q",
        "style": BarChartStylePatch.model_validate(_STYLE_OVERRIDE),
    }
    defaults.update(kwargs)
    return BarChart(**defaults)


def _line(**kwargs: Any) -> LineChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "line",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
        "style": LineChartStylePatch.model_validate(_STYLE_OVERRIDE),
    }
    defaults.update(kwargs)
    return LineChart(**defaults)


def _area(**kwargs: Any) -> AreaChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "area",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
        "style": AreaChartStylePatch.model_validate(_STYLE_OVERRIDE),
    }
    defaults.update(kwargs)
    return AreaChart(**defaults)


def _scatter(**kwargs: Any) -> ScatterChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "scatter",
        "x": "month_index",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
        "style": ScatterChartStylePatch.model_validate(_STYLE_OVERRIDE),
    }
    defaults.update(kwargs)
    return ScatterChart(**defaults)


def _heatmap(**kwargs: Any) -> HeatmapChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "heatmap",
        "x": "month",
        "y": "category",
        "query": _sql(),
        "query_name": "q",
        "style": HeatmapChartStylePatch.model_validate(_STYLE_OVERRIDE),
    }
    defaults.update(kwargs)
    return HeatmapChart(**defaults)


_BUILDERS: dict[str, Callable[..., Chart]] = {
    "bar": _bar,
    "line": _line,
    "area": _area,
    "scatter": _scatter,
    "heatmap": _heatmap,
    "histogram": _histogram,
}

_DATA: list[dict[str, Any]] = [
    {
        "month": "Jan",
        "month_index": 1,
        "category": "Alpha",
        "revenue": 10.0,
        "value": 1.0,
    },
    {
        "month": "Feb",
        "month_index": 2,
        "category": "Beta",
        "revenue": 20.0,
        "value": 2.0,
    },
]


class TestChartLocalAxisOverrideReachesResolvedAxis:
    """A chart-local axis_x/axis_y font-color override must survive resolve(),
    for every family, regardless of which chart_style_context spelling
    `_bake_cartesian_axes` receives internally."""

    @pytest.mark.parametrize("family", list(_BUILDERS))
    def test_chart_local_axis_override_reaches_resolved_axis(self, family: str) -> None:
        chart = _BUILDERS[family]()
        resolved = resolve(chart, _DATA, _board())
        assert resolved.style.axis_x.labels.font.color == _AXIS_X_COLOR, (
            f"{family}: chart-local style.axis_x.labels.font.color did not "
            f"reach the resolved axis (got "
            f"{resolved.style.axis_x.labels.font.color!r})"
        )
        assert resolved.style.axis_y.labels.font.color == _AXIS_Y_COLOR, (
            f"{family}: chart-local style.axis_y.labels.font.color did not "
            f"reach the resolved axis (got "
            f"{resolved.style.axis_y.labels.font.color!r})"
        )
