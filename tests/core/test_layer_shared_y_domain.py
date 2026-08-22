"""A shared measure axis spans every layer drawn on it, not just the base ``y``.

The domain used to come from the base ``y`` column alone, so an overlay layer
whose values exceeded the base max was drawn above the axis top — and once the
ratio was large enough, ``autosize: fit`` collapsed the plot height to zero and
the chart rendered as a blank rectangle with no title, no error and no warning.

Actual-vs-goal is the shape that hits this: a Q1 actual against a full-year goal
is several times under by construction.

A layer pinned to ``axis_y.position: right`` has its own scale and must NOT widen
the primary one.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_CTX = resolve_chart_style_context(get_theme_style())

# The numbers from the repro asset: the actual tops out at 6.1%, the goal ramps to
# 25% — a ~4x overshoot, which is where the plot used to collapse entirely.
_ACTUAL_MAX = 0.061
_GOAL_MAX = 0.25
_DATA = [
    {"quarter": "2027-Q1", "actual_share": 0.021, "goal_share": 0.10},
    {"quarter": "2027-Q2", "actual_share": 0.034, "goal_share": 0.15},
    {"quarter": "2027-Q3", "actual_share": 0.048, "goal_share": 0.20},
    {"quarter": "2027-Q4", "actual_share": _ACTUAL_MAX, "goal_share": _GOAL_MAX},
]


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _y_axis(chart_type: str, layer: dict[str, Any]) -> dict[str, Any]:
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": chart_type,
            "x": "quarter",
            "y": "actual_share",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "layers": [layer],
        }
    )
    resolve(chart, _DATA, chart_style_context=_BOARD_CTX)
    spec = generate_vega_lite_spec(chart, _DATA, width=400)
    # A layered chart carries the primary scale on the base sub-layer, not at the
    # spec root; the base series is the one encoding the chart's own ``y``.
    return next(
        layer["encoding"]["y"]
        for layer in spec["layer"]
        if layer.get("encoding", {}).get("y", {}).get("field") == "actual_share"
    )


def _upper_bound(y_enc: dict[str, Any]) -> float:
    """The top of the measure axis, from whichever surface the resolver baked."""
    scale = y_enc.get("scale") or {}
    if scale.get("domainMax") is not None:
        return float(scale["domainMax"])
    if scale.get("domain"):
        return float(scale["domain"][-1])
    return max(float(v) for v in y_enc["axis"]["values"])


@pytest.mark.parametrize("chart_type", ["bar", "line", "area"])
def test_overlay_layer_widens_the_shared_y_domain(chart_type: str) -> None:
    """The overlay's 25% has to fit inside the axis, or it draws outside the plot."""
    y_enc = _y_axis(chart_type, {"type": "line", "y": "goal_share"})
    assert _upper_bound(y_enc) >= _GOAL_MAX


def test_right_axis_layer_does_not_widen_the_primary_domain() -> None:
    """A layer on its own right-hand scale is not drawn against this one."""
    y_enc = _y_axis(
        "bar",
        {"type": "line", "y": "goal_share", "axis_y": {"position": "right"}},
    )
    upper = _upper_bound(y_enc)
    assert upper < _GOAL_MAX
    assert upper >= _ACTUAL_MAX
