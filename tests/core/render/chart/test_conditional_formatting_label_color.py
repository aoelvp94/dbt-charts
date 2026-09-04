"""A bar chart's value labels keep their own color under conditional_formatting.

conditional_formatting compiles to a chart-level ``encoding.color`` condition
array. Vega-Lite lets an inherited encoding channel beat a static mark prop, so
a label layer that carries its color only as ``mark.color`` gets repainted in
its own bar's fill — invisible when the label sits inside the bar.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE, _BOARD_CONTEXT = resolve_style_and_context(get_theme_style())
_QUERY = SqlQuery(sql="SELECT 1", source="test")
_DATA = [
    {"category": "Increase", "arr": 2_000_000},
    {"category": "Decrease", "arr": -500_000},
]
_AUTHORED = "#F7B068"
# No chart here authors a background, so every one resolves to the board's
# — which is what an inside-bar label pins for contrast.
_BACKGROUND = _BOARD_CONTEXT.background
_CF = {
    "arr": {
        "when": [
            {"gt": 0, "background": "#007FFF"},
            {"lte": 0, "background": "#7B7B7B"},
        ]
    }
}


def _spec(
    *,
    conditional_formatting: dict[str, Any] | None = None,
    label_color: str | None = None,
    position: str | None = None,
    stack: str | None = None,
) -> dict[str, Any]:
    labels: dict[str, Any] = {"visible": True}
    if label_color is not None:
        labels["font"] = {"color": label_color}
    if position is not None:
        labels["position"] = position
    chart: dict[str, Any] = {
        "id": "b1",
        "query": _QUERY,
        "query_name": "q",
        "type": "bar",
        "x": "category",
        "y": "arr",
        "style": {"marks": {"bar": {"labels": labels}}},
    }
    if conditional_formatting is not None:
        chart["conditional_formatting"] = conditional_formatting
    if stack is not None:
        chart["stack"] = stack
        chart["color"] = "category"
    resolved = resolve(
        TypeAdapter(Chart).validate_python(chart),
        _DATA,
        chart_style_context=_BOARD_CONTEXT,
    )
    return render_resolved_chart(resolved, _DATA, _BOARD_STYLE).payload


def _text_layer(spec: dict[str, Any]) -> dict[str, Any]:
    layers = [
        layer
        for layer in spec.get("layer", [])
        if (layer.get("mark") or {}).get("type") == "text"
    ]
    assert len(layers) == 1, f"expected exactly one text layer, got {len(layers)}"
    return layers[0]


def _label_color(spec: dict[str, Any]) -> Any:
    return _text_layer(spec).get("encoding", {}).get("color")


def test_authored_label_color_survives_conditional_formatting():
    spec = _spec(conditional_formatting=_CF, label_color=_AUTHORED)
    assert spec["encoding"]["color"].get("condition"), (
        "precondition: conditional_formatting must emit a chart-level color "
        "condition array for the label layer to inherit"
    )
    assert _label_color(spec) == {"value": _AUTHORED}, (
        "the authored labels.font.color must be pinned on the label layer's own "
        "encoding — as a static mark prop the inherited condition array beats it "
        "and each label takes its own bar's fill"
    )


def test_authored_label_color_is_pinned_without_conditional_formatting_too():
    """The pin is unconditional: nothing else may claim the label's ink either."""
    assert _label_color(_spec(label_color=_AUTHORED)) == {"value": _AUTHORED}


def test_an_unauthored_outside_label_still_inherits_the_series_color():
    """No authored color is no claim — the label keeps inheriting, as before.

    ``above`` is the one position that sits clear of the fill; the theme's own
    default is ``top``, which is inside it and pins the background.
    """
    assert _label_color(_spec(conditional_formatting=_CF, position="above")) is None


@pytest.mark.parametrize("position", ["top", "middle", "bottom", "middle_aligned"])
def test_an_inside_position_pins_its_legibility_color(position):
    """Inside-bar labels take the background for contrast; that must be pinned."""
    color = _label_color(_spec(conditional_formatting=_CF, position=position))
    assert color == {"value": _BACKGROUND}, (
        f"position {position!r} sits inside the fill and needs the background "
        f"pinned as its own color, else conditional_formatting paints it in "
        f"that fill"
    )


def test_a_stacked_label_still_pins_a_color_with_none_authored():
    """The stacked branch's existing unconditional pin is unaffected."""
    color = _label_color(_spec(stack="zero", position="middle"))
    assert color == {"value": _BACKGROUND}
