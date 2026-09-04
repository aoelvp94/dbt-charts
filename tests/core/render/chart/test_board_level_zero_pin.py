"""Board-level ``style.charts.axis_y.scale.continuous.zero`` must reach
line, area, and scatter -- not just the identical pin authored at chart
level.

``resolve_y_zero`` used to read the pin only off the per-chart/family
``_CartesianChartStyle`` patch (``primary.axis_y``), which is None for a
board-level-only pin. The board pin is already present on the cascaded
``ay_merged`` axis by the time the family resolvers run; this file pins that
the pin is read from there.

Data ratio: min/max = 120/204 ~= 0.588 > 0.25, so the smart-zero heuristic
alone returns zero:False -- the discriminating case that proves the board
pin (not the heuristic) drove the result.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.style.authored import StylePatch
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

# ratio = 120/204 ~= 0.588 > 0.25 -> heuristic alone returns zero:False.
_FAR_RATIO_DATA = [
    {"x": "a", "y": 120},
    {"x": "b", "y": 180},
    {"x": "c", "y": 204},
]
# ratio = 6000/33000 ~= 0.18 <= 0.25 -> heuristic alone abstains/anchors.
_CLOSE_TO_ZERO_DATA = [
    {"x": "2024-01", "y": 6000.0},
    {"x": "2024-02", "y": 20000.0},
    {"x": "2024-03", "y": 33000.0},
]


def _spec(chart_type: str, data: list[dict], board_zero: bool) -> dict:
    reset_config()
    patch = TypeAdapter(StylePatch).validate_python(
        {"charts": {"axis_y": {"scale": {"continuous": {"zero": board_zero}}}}}
    )
    board_style, board_ctx = resolve_style_and_context(get_theme_style(), patch)
    payload: dict = {"id": "t", "type": chart_type, "x": "x", "y": "y"}
    chart = TypeAdapter(Chart).validate_python(payload)
    return generate_vega_lite_spec(
        chart, data, width=400, board_style=board_style, chart_style_context=board_ctx
    )


def test_board_level_zero_true_pin_anchors_line() -> None:
    scale = _spec("line", _FAR_RATIO_DATA, board_zero=True)["encoding"]["y"]["scale"]
    assert scale["zero"] is True


def test_chart_level_zero_false_pin_overrides_board_level_zero_true_pin() -> None:
    """A chart-local pin outranks the identical board-level one.

    Proven on area: an unpinned area chart already zero-anchors all-positive
    data unconditionally (`enrich.py`'s non-optional-zero branch), so a board
    pin alone can't tell whether the board pin or the default drove the
    anchor. Only an explicit chart-level ``zero: false`` override, read
    against a conflicting board-level ``zero: true``, can prove precedence:
    the axis must stay zoomed."""
    reset_config()
    board_patch = TypeAdapter(StylePatch).validate_python(
        {"charts": {"axis_y": {"scale": {"continuous": {"zero": True}}}}}
    )
    board_style, board_ctx = resolve_style_and_context(get_theme_style(), board_patch)
    payload: dict = {
        "id": "t",
        "type": "area",
        "x": "x",
        "y": "y",
        "style": {"axis_y": {"scale": {"continuous": {"zero": False}}}},
    }
    chart = TypeAdapter(Chart).validate_python(payload)
    spec = generate_vega_lite_spec(
        chart,
        _FAR_RATIO_DATA,
        width=400,
        board_style=board_style,
        chart_style_context=board_ctx,
    )
    scale = spec["encoding"]["y"]["scale"]
    assert scale["zero"] is False


def test_board_level_zero_true_pin_anchors_scatter() -> None:
    scale = _spec("scatter", _FAR_RATIO_DATA, board_zero=True)["encoding"]["y"]["scale"]
    assert scale["zero"] is True


def test_board_level_zero_false_pin_suppresses_line_on_close_to_zero_data() -> None:
    scale = _spec("line", _CLOSE_TO_ZERO_DATA, board_zero=False)["encoding"]["y"][
        "scale"
    ]
    assert scale["zero"] is False


def test_board_level_zero_false_pin_suppresses_area_on_close_to_zero_data() -> None:
    scale = _spec("area", _CLOSE_TO_ZERO_DATA, board_zero=False)["encoding"]["y"][
        "scale"
    ]
    assert scale["zero"] is False


def test_board_level_zero_false_pin_suppresses_scatter_on_close_to_zero_data() -> None:
    scale = _spec("scatter", _CLOSE_TO_ZERO_DATA, board_zero=False)["encoding"]["y"][
        "scale"
    ]
    assert scale["zero"] is False
