"""Regression: normalize-stacked bars must default to quartile tick values.

When ``style.stack: normalize`` is used (100% stacked bar), the measure axis
should default to ``axis.values: [0, 0.25, 0.5, 0.75, 1.0]`` so VL renders
exactly five ticks (0%, 25%, 50%, 75%, 100%) instead of auto-picking every 5%
or 10% based on pane width.

The default fires for both vertical (measure on VL y) and horizontal (measure
on VL x after orientation swap). If the board explicitly authors axis_y.values
(or axis_x.values for horizontal), the explicit values win — the engine must
not overwrite them. Non-normalize stacked bars must not get the quartile
default.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    AxisYStylePatch,
    BarChartStylePatch,
    BaseScaleStylePatch,
)
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE = resolve_style(get_theme_style())

_QUARTILE_VALUES = [0, 0.25, 0.5, 0.75, 1.0]

_DATA = [
    {"priority": "high", "status": "new", "ticket_count": 10},
    {"priority": "high", "status": "solved", "ticket_count": 8},
    {"priority": "low", "status": "new", "ticket_count": 5},
    {"priority": "low", "status": "solved", "ticket_count": 3},
]


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _spec(
    orientation: str | None, stack: str | None, style_extra: dict | None = None
) -> dict:
    bar_kwargs: dict = {"orientation": orientation, "stack": stack}
    if style_extra:
        bar_kwargs.update(style_extra)
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="priority",
        y="ticket_count",
        color="status",
        style=BarChartStylePatch(**bar_kwargs),
    )
    return generate_vega_lite_spec(chart, _DATA, width=400, height=300)


def _chart_encoding(spec: dict) -> dict:
    """Extract bar encoding from spec, unwrapping hconcat/vconcat if present."""
    if "vconcat" in spec:
        return spec["vconcat"][1]["encoding"]
    if "hconcat" in spec:
        return spec["hconcat"][0]["encoding"]
    return spec["encoding"]


class TestVertical100QuartileTicks:
    """Vertical 100% stacked bar: measure axis (VL y) gets quartile values default."""

    def test_measure_y_axis_has_quartile_values(self):
        spec = _spec(orientation="vertical", stack="normalize")
        enc = _chart_encoding(spec)
        y_axis = enc["y"].get("axis", {})
        assert y_axis.get("values") == _QUARTILE_VALUES, (
            f"vertical normalize: expected axis.values={_QUARTILE_VALUES!r} on "
            f"encoding.y (the measure axis); got {y_axis.get('values')!r}"
        )

    def test_explicit_axis_y_values_not_overwritten(self):
        """When axis_y.scale.values is authored, engine must not overwrite with quartile default."""
        explicit = [0, 0.5, 1.0]
        chart = BarChart(
            id="t",
            query=SqlQuery(sql="SELECT 1", source="t"),
            query_name="q",
            type="bar",
            x="priority",
            y="ticket_count",
            color="status",
            style=BarChartStylePatch(
                orientation="vertical",
                stack="normalize",
                axis_y=AxisYStylePatch(scale=BaseScaleStylePatch(values=explicit)),
            ),
        )
        spec = generate_vega_lite_spec(chart, _DATA, width=400, height=300)
        enc = _chart_encoding(spec)
        y_axis = enc["y"].get("axis", {})
        assert y_axis.get("values") == explicit, (
            f"explicit axis_y.values must not be overwritten by quartile default; "
            f"expected {explicit!r}, got {y_axis.get('values')!r}"
        )


class TestHorizontal100QuartileTicks:
    """Horizontal 100% stacked bar: measure axis (VL x) gets quartile values default."""

    def test_measure_x_axis_has_quartile_values(self):
        spec = _spec(orientation="horizontal", stack="normalize")
        enc = _chart_encoding(spec)
        x_axis = enc["x"].get("axis", {})
        assert x_axis.get("values") == _QUARTILE_VALUES, (
            f"horizontal normalize: expected axis.values={_QUARTILE_VALUES!r} on "
            f"encoding.x (the measure axis after orientation swap); "
            f"got {x_axis.get('values')!r}"
        )

    def test_categorical_y_axis_has_no_quartile_values(self):
        """Quartile values must only land on the measure channel, not the categorical axis."""
        spec = _spec(orientation="horizontal", stack="normalize")
        enc = _chart_encoding(spec)
        y_axis = enc["y"].get("axis", {}) or {}
        assert "values" not in y_axis or y_axis.get("values") is None, (
            f"horizontal: encoding.y is the categorical axis; quartile values "
            f"must not appear there. got y.axis={y_axis!r}"
        )


class TestNonNormalizeStackNoQuartileDefault:
    """Non-normalize stacked bars must not receive the quartile tick default."""

    def test_stack_zero_no_quartile_values(self):
        spec = _spec(orientation=None, stack="zero")
        enc = _chart_encoding(spec)
        y_axis = enc["y"].get("axis", {})
        assert "values" not in y_axis, (
            f"stack=zero must not get quartile tick default; "
            f"got axis.values={y_axis.get('values')!r}"
        )
