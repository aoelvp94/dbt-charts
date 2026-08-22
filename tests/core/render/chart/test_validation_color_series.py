"""Null values in a chart's color column must error, never render invisibly.

Regression for the floating-stacked-bar bug: a NULL category was filtered out
of the palette, the color scale, and the legend, while its rows still reached
Vega-Lite's stack transform. The segment reserved vertical space, was never
painted, and was never reported — bars floated off the zero baseline with the
tops in the right place, which reads as a plausible-but-wrong chart rather than
an obvious failure.

Tests drive the real render entry point (``generate_vega_lite_spec``) rather
than calling the validator directly, so the emitter wiring is pinned too:
deleting a ``validate_color_series`` call from an emitter must fail this suite.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    LineChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_render import ERR_COLOR_NULL_SERIES
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_CHART_TYPES = {"bar": BarChart, "line": LineChart, "area": AreaChart}

_STACKED_WITH_NULL: list[dict[str, Any]] = [
    {"quarter": "Q1", "product_line": "Ingestion", "arr": 100},
    {"quarter": "Q1", "product_line": "dbt", "arr": 25},
    {"quarter": "Q1", "product_line": None, "arr": 60},
    {"quarter": "Q2", "product_line": "Ingestion", "arr": 120},
    {"quarter": "Q2", "product_line": "dbt", "arr": 40},
    {"quarter": "Q2", "product_line": None, "arr": 90},
]


def _render(chart_type: str, data: list[dict[str, Any]], **kwargs: Any) -> Any:
    normalized = _CHART_TYPES[chart_type](
        id="arr",
        type=chart_type,
        x="quarter",
        y="arr",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        **kwargs,
    )
    return generate_vega_lite_spec(normalized, data)


@pytest.mark.parametrize("chart_type", ["bar", "line", "area"])
def test_null_series_color_raises_through_the_render_path(chart_type: str) -> None:
    with pytest.raises(ChartDataError) as exc_info:
        _render(chart_type, _STACKED_WITH_NULL, color="product_line")

    assert exc_info.value.code is ERR_COLOR_NULL_SERIES
    message = str(exc_info.value)
    assert "product_line" in message
    assert "2 row(s)" in message


def test_stacked_bar_with_null_series_raises() -> None:
    """The reported shape: `stack: zero` over a color column with a NULL."""
    with pytest.raises(ChartDataError, match="ERR-COLOR-NULL-SERIES|NULL value"):
        _render(
            "bar",
            _STACKED_WITH_NULL,
            color="product_line",
            style=BarChartStylePatch(stack="zero"),
        )


@pytest.mark.parametrize("chart_type", ["bar", "line", "area"])
def test_fully_populated_series_color_renders(chart_type: str) -> None:
    data = [row for row in _STACKED_WITH_NULL if row["product_line"] is not None]
    assert _render(chart_type, data, color="product_line") is not None


def test_null_in_a_quantitative_color_column_renders() -> None:
    """A numeric color is a continuous scale — no palette slot, no legend entry.

    Guards the false positive that scoping to categorical series mode fixes:
    NULL in a metric column is routine and must not fail the board.
    """
    data: list[dict[str, Any]] = [
        {"quarter": "Q1", "arr": 100, "arr_change": None},
        {"quarter": "Q2", "arr": 120, "arr_change": 20.0},
        {"quarter": "Q3", "arr": 140, "arr_change": 20.0},
    ]
    assert _render("bar", data, color="arr_change") is not None


def test_conditional_formatting_with_nulls_still_renders() -> None:
    """`conditional_formatting` installs a color channel with no `color:` authored.

    That channel is `mode="conditional"` over a numeric metric, where NULL is
    routine — no prior period, no rows for a category. Vega-Lite lowers it to a
    condition list a null simply doesn't match, so the mark takes the default
    fill: no palette slot, no legend entry, no stack-space anomaly. Guarding on
    the effective color field alone would hard-fail every such board.
    """
    data: list[dict[str, Any]] = [
        {"quarter": "Q1", "arr": 100, "arr_change": None},
        {"quarter": "Q2", "arr": 120, "arr_change": -5.0},
    ]
    spec = _render(
        "bar",
        data,
        conditional_formatting={
            "arr_change": {"when": [{"lt": 0, "background": "#c00"}]}
        },
    )
    assert spec is not None


def test_chart_without_color_encoding_renders() -> None:
    data: list[dict[str, Any]] = [
        {"quarter": "Q1", "arr": 100},
        {"quarter": "Q2", "arr": 120},
    ]
    assert _render("bar", data) is not None
