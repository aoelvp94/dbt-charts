"""A horizontal single-series bar's value-descending category sort must
survive into the real compiled render for mixed-sign data.

The emitted VL JSON's ``encoding.y.sort`` and ``scale.domain`` can be
correct while Vega-Lite's own layered-view compilation still produces a
different rendered order for a mixed-sign base bar mark, which splits
into sign-filtered sub-layers. These tests walk the actual compiled Vega
scenegraph rather than asserting on the emitted spec, so a change that
gets the JSON right but the real render wrong cannot pass silently.
"""

from __future__ import annotations

import re
from typing import Any

import vl_convert as vlc
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
    {"segment": "Churn", "arr": -900_000},
    {"segment": "Expansion", "arr": 2_000_000},
    {"segment": "Contraction", "arr": -500_000},
    {"segment": "New", "arr": 1_400_000},
]


def _rendered_category_order(spec: dict[str, Any]) -> list[str]:
    """Each bar mark's own category value, top-to-bottom, in the real render."""
    scenegraph = vlc.vegalite_to_scenegraph(dict(spec))
    bars: list[tuple[float, str]] = []

    def walk(node: Any, y_offset: float) -> None:
        if isinstance(node, dict):
            ny = y_offset + node.get("y", 0)
            if node.get("marktype") == "rect":
                for item in node.get("items", []):
                    # Skip BarHoverBandFeature's invisible hover-band rects
                    # (opacity=0) -- see test_bar_null_bucket_axis.py's
                    # _rendered_x_order, which guards the same thing.
                    if "description" in item and item.get("opacity") != 0:
                        bars.append((ny + item.get("y", 0), item["description"]))
                return
            for key, value in node.items():
                if key == "items":
                    walk(value, ny)
                elif isinstance(value, (dict, list)):
                    walk(value, y_offset)
        elif isinstance(node, list):
            for item in node:
                walk(item, y_offset)

    walk(scenegraph, 0.0)
    bars.sort(key=lambda b: b[0])
    categories: list[str] = []
    for _, description in bars:
        match = re.search(r"[A-Za-z]+", description)
        assert match, f"no category name found in bar description {description!r}"
        categories.append(match.group())
    return categories


def _render(style: dict[str, Any]) -> dict[str, Any]:
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "b1",
            "query": _QUERY,
            "query_name": "q",
            "type": "bar",
            "x": "segment",
            "y": "arr",
            "style": style,
        }
    )
    resolved = resolve(chart, _DATA, chart_style_context=_BOARD_CONTEXT)
    artifact = render_resolved_chart(resolved, _DATA, _BOARD_STYLE)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    assert isinstance(spec, dict)
    return spec


def _assert_value_descending(spec: dict[str, Any]) -> None:
    assert spec["encoding"]["y"]["sort"] == {"field": "arr", "order": "descending"}, (
        "precondition: the emitted spec's own outer y.sort must already be "
        "value-descending -- if this fails, emitters/bar.py's sort default "
        "changed and this test needs to change with it"
    )
    order = _rendered_category_order(spec)
    assert order == ["Expansion", "New", "Contraction", "Churn"], (
        "the real Vega-Lite compiled render must keep value-descending "
        f"category order for mixed-sign data, got {order!r}"
    )


def test_horizontal_bar_mixed_sign_keeps_value_descending_sort() -> None:
    """No color channel, no value labels -- the minimal mixed-sign repro."""
    _assert_value_descending(_render({"orientation": "horizontal"}))


def test_horizontal_bar_with_value_labels_keeps_value_descending_sort() -> None:
    """The same shape with a value-label text layer also present."""
    _assert_value_descending(
        _render(
            {
                "orientation": "horizontal",
                "marks": {"bar": {"labels": {"visible": True, "position": "above"}}},
            }
        )
    )
