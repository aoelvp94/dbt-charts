"""Regression tests for bar edge rounding with negative values.

cornerRadiusEnd in Vega clips from the wrong end for negative bars — it rounds the
baseline (zero-axis) end instead of the tip, creating a visual gap.  The fix picks
the correct explicit corner-radius properties based on data sign:

  all-positive → cornerRadiusEnd (top for vertical, right for horizontal)
  all-negative → cornerRadiusBottomLeft/Right (vertical) or TopLeft/BottomLeft (horizontal)
  mixed        → two-layer spec: positive layer uses cornerRadiusEnd,
                 negative layer uses explicit tip corners
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import reset_config
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_POS_DATA = [{"cat": "A", "val": 5}, {"cat": "B", "val": 3}]
_NEG_DATA = [{"cat": "A", "val": -5}, {"cat": "B", "val": -3}]
_MIX_DATA = [{"cat": "A", "val": 5}, {"cat": "B", "val": -3}]
# Mixed stacked: two series (direction), one always positive, one always negative.
_STACKED_MIX_DATA = [
    {"month": "Jan", "direction": "up", "val": 5},
    {"month": "Jan", "direction": "down", "val": -3},
    {"month": "Feb", "direction": "up", "val": 7},
    {"month": "Feb", "direction": "down", "val": -2},
]


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    reset_config()
    monkeypatch.setenv("DCT_DEFAULT_THEME", "stark")
    yield
    reset_config()


def _bar_spec(data: list[dict], orientation: str = "vertical") -> dict:
    style = BarChartStylePatch.model_validate({"orientation": orientation})
    chart = BarChart(
        id="t",
        type="bar",
        x="cat",
        y="val",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
        style=style,
    )
    return generate_vega_lite_spec(chart, data, width=400)


def _mark(spec: dict) -> dict:
    mark = spec.get("mark", spec.get("layer", [{}])[0].get("mark", {}))
    return mark if isinstance(mark, dict) else {}


# ── vertical bar ──────────────────────────────────────────────────────────────


def test_positive_bars_use_cornerRadiusEnd():
    """All-positive bars keep cornerRadiusEnd (rounds the top / value end)."""
    mark = _mark(_bar_spec(_POS_DATA))
    assert "cornerRadiusEnd" in mark, f"expected cornerRadiusEnd; got {mark}"
    assert "cornerRadiusBottomLeft" not in mark
    assert "cornerRadiusBottomRight" not in mark


def test_negative_bars_use_bottom_corner_radius():
    """All-negative bars use cornerRadiusBottomLeft/Right (rounds the tip, not baseline)."""
    mark = _mark(_bar_spec(_NEG_DATA))
    assert "cornerRadiusEnd" not in mark, (
        f"cornerRadiusEnd must not appear for negative bars; got {mark}"
    )
    assert "cornerRadiusBottomLeft" in mark
    assert "cornerRadiusBottomRight" in mark
    assert "cornerRadiusTopLeft" not in mark
    assert "cornerRadiusTopRight" not in mark


def test_negative_bars_corner_radius_value_matches_theme():
    """The rounding value on negative bars equals what positive bars would get."""
    pos_mark = _mark(_bar_spec(_POS_DATA))
    neg_mark = _mark(_bar_spec(_NEG_DATA))
    assert neg_mark["cornerRadiusBottomLeft"] == pytest.approx(
        pos_mark["cornerRadiusEnd"]
    )
    assert neg_mark["cornerRadiusBottomRight"] == pytest.approx(
        pos_mark["cornerRadiusEnd"]
    )


def test_mixed_bars_two_layer_spec():
    """Mixed-sign vertical bars produce a layered spec with pos/neg bar layers.

    Layer 0 (positive bars) keeps cornerRadiusEnd.
    Layer 1 (negative bars) uses cornerRadiusBottomLeft/Right.
    Each bar layer carries the correct filter transform.
    (Additional layers — the hover band with opacity=0 and any rule layers —
    may also be present and are excluded from the visible-bar count.)
    """
    spec = _bar_spec(_MIX_DATA)
    layers = spec.get("layer")
    assert layers is not None and len(layers) >= 2, (
        f"mixed bars must produce a layered spec; got {spec.keys()}"
    )

    # Filter to visible bar layers (exclude the invisible hover band with opacity=0).
    bar_layers = [
        la
        for la in layers
        if (la.get("mark") or {}).get("type") == "bar"
        and (la.get("mark") or {}).get("opacity") != 0
    ]
    assert len(bar_layers) == 2, f"expected 2 visible bar layers; got {bar_layers}"
    pos_layer, neg_layer = bar_layers[0], bar_layers[1]

    pos_mark = pos_layer.get("mark", {})
    assert "cornerRadiusEnd" in pos_mark, (
        f"positive layer must have cornerRadiusEnd; got {pos_mark}"
    )
    assert "cornerRadiusBottomLeft" not in pos_mark

    neg_mark = neg_layer.get("mark", {})
    assert "cornerRadiusEnd" not in neg_mark, (
        f"negative layer must not have cornerRadiusEnd; got {neg_mark}"
    )
    assert "cornerRadiusBottomLeft" in neg_mark
    assert "cornerRadiusBottomRight" in neg_mark

    pos_transforms = pos_layer.get("transform", [])
    assert any("filter" in t for t in pos_transforms), (
        f"positive layer missing filter; got {pos_transforms}"
    )
    neg_transforms = neg_layer.get("transform", [])
    assert any("filter" in t for t in neg_transforms), (
        f"negative layer missing filter; got {neg_transforms}"
    )


def test_mixed_bars_preserve_category_order():
    """The mixed-sign two-layer split must NOT reorder categories by sign.

    Regression: splitting into pos/neg filtered layers let VL infer the shared
    category domain per-layer and union them (positives first, then negatives),
    destroying original row order. The split must pin the category domain to the
    full-data order so bars render in the authored/data sequence.
    """
    # Categories in a deliberately non-alphabetical order, signs interleaved.
    data = [
        {"cat": "Zeta", "val": 10},
        {"cat": "Alpha", "val": -5},
        {"cat": "Mu", "val": 8},
        {"cat": "Beta", "val": -2},
    ]
    spec = _bar_spec(data)
    assert "layer" in spec, "mixed-sign bars should be a layered spec"
    x_scale = spec.get("encoding", {}).get("x", {}).get("scale", {})
    assert x_scale.get("domain") == ["Zeta", "Alpha", "Mu", "Beta"], (
        "mixed-sign split must pin the x category domain to data order, not "
        f"sign-grouped/alphabetical; got {x_scale.get('domain')}"
    )


# ── horizontal bar ────────────────────────────────────────────────────────────


def test_positive_horizontal_bars_use_cornerRadiusEnd():
    """Horizontal all-positive bars keep cornerRadiusEnd (rounds right end)."""
    mark = _mark(_bar_spec(_POS_DATA, "horizontal"))
    assert "cornerRadiusEnd" in mark


def test_negative_horizontal_bars_use_left_corner_radius():
    """Horizontal all-negative bars use cornerRadiusTopLeft/BottomLeft (tip = left end)."""
    mark = _mark(_bar_spec(_NEG_DATA, "horizontal"))
    assert "cornerRadiusEnd" not in mark
    assert "cornerRadiusTopLeft" in mark
    assert "cornerRadiusBottomLeft" in mark
    assert "cornerRadiusTopRight" not in mark
    assert "cornerRadiusBottomRight" not in mark


def test_mixed_horizontal_bars_two_layer_spec():
    """Mixed-sign horizontal bars produce a layered spec with pos/neg bar layers.

    Layer 0 (positive bars) keeps cornerRadiusEnd.
    Layer 1 (negative bars) uses cornerRadiusTopLeft/BottomLeft.
    (The hover band layer with opacity=0 is excluded from the visible-bar count.)
    """
    spec = _bar_spec(_MIX_DATA, "horizontal")
    layers = spec.get("layer")
    assert layers is not None and len(layers) >= 2, (
        f"mixed horizontal bars must produce a layered spec; got {spec.keys()}"
    )

    # Filter to visible bar layers (exclude the invisible hover band with opacity=0).
    bar_layers = [
        la
        for la in layers
        if (la.get("mark") or {}).get("type") == "bar"
        and (la.get("mark") or {}).get("opacity") != 0
    ]
    assert len(bar_layers) == 2, f"expected 2 visible bar layers; got {bar_layers}"
    pos_layer, neg_layer = bar_layers[0], bar_layers[1]

    pos_mark = pos_layer.get("mark", {})
    assert "cornerRadiusEnd" in pos_mark
    assert "cornerRadiusTopLeft" not in pos_mark

    neg_mark = neg_layer.get("mark", {})
    assert "cornerRadiusEnd" not in neg_mark
    assert "cornerRadiusTopLeft" in neg_mark
    assert "cornerRadiusBottomLeft" in neg_mark
    assert "cornerRadiusTopRight" not in neg_mark
    assert "cornerRadiusBottomRight" not in neg_mark


# ── stacked diverging bars ────────────────────────────────────────────────────


def _stacked_bar_spec(data: list[dict]) -> dict:
    """Bar chart with color grouping + stack:zero (diverging stacked bars)."""
    style = BarChartStylePatch.model_validate(
        {"orientation": "vertical", "stack": "zero"}
    )
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="val",
        color="direction",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
        style=style,
    )
    return generate_vega_lite_spec(chart, data, width=400)


def test_stacked_mixed_bars_get_corner_radius():
    """Stacked diverging bars respect border.radius — two-layer split includes z-order.

    Regression: previously the z_transforms guard suppressed corner rounding for
    any stacked bar with mixed-sign data; the radius was silently ignored.
    (The hover band layer with opacity=0 is excluded from the visible-bar count.)
    """
    spec = _stacked_bar_spec(_STACKED_MIX_DATA)
    layers = spec.get("layer")
    assert layers is not None, (
        f"stacked mixed bars must produce a layered spec; got {spec.keys()}"
    )

    # Filter to visible bar layers (exclude the invisible hover band with opacity=0).
    bar_layers = [
        la
        for la in layers
        if (la.get("mark") or {}).get("type") == "bar"
        and (la.get("mark") or {}).get("opacity") != 0
    ]
    assert len(bar_layers) == 2, f"expected 2 visible bar layers; got {bar_layers}"

    pos_mark = bar_layers[0].get("mark", {})
    assert "cornerRadiusEnd" in pos_mark, (
        f"positive layer must have cornerRadiusEnd; got {pos_mark}"
    )
    neg_mark = bar_layers[1].get("mark", {})
    assert "cornerRadiusBottomLeft" in neg_mark, (
        f"negative layer must have tip corners; got {neg_mark}"
    )
