"""Tests for render/svg_utils.py helpers."""

from dbt_charts.core.compile.models.primitives import BorderStyle
from dbt_charts.core.render.svg_utils import border_dash_attrs


def test_border_dash_attrs_empty_when_solid():
    border = BorderStyle(width=1, color="#333", radius=0)
    assert border_dash_attrs(border) == ""


def test_border_dash_attrs_dasharray_only():
    border = BorderStyle(width=1, color="#333", radius=0, dash_array=[4, 4])
    assert border_dash_attrs(border) == ' stroke-dasharray="4,4"'


def test_border_dash_attrs_full():
    border = BorderStyle(
        width=1,
        color="#333",
        radius=0,
        dash_array=[8, 4, 1, 4],
        line_cap="round",
        dash_offset=2.0,
    )
    assert border_dash_attrs(border) == (
        ' stroke-dasharray="8,4,1,4" stroke-linecap="round" stroke-dashoffset="2"'
    )
