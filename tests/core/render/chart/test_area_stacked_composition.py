"""TDD: area chart stacked/streamgraph composition (design/chart-briefs/area.md).

Stacked and streamgraph area charts (``stack: zero/normalize/center``) get a
solid fill + full-perimeter background-color stroke, dropping the halo
undercoat and the separate top-edge line. Overlap (``stack: false``/unset)
keeps the existing translucent-halo recipe unchanged.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())

_DATA = [
    {"date": "2024-01-01", "value": 100, "series": "Revenue"},
    {"date": "2024-02-01", "value": 120, "series": "Revenue"},
    {"date": "2024-01-01", "value": 80, "series": "Costs"},
    {"date": "2024-02-01", "value": 90, "series": "Costs"},
]

_MULTI_DATA = [
    {"date": "2024-01-01", "revenue": 100, "costs": 80},
    {"date": "2024-02-01", "revenue": 120, "costs": 90},
]


def _make_area_chart(
    make_chart, stack: str | None, style_override: dict[str, Any] | None = None
):
    kwargs: dict[str, Any] = {"stack": stack}
    if style_override is not None:
        kwargs["style"] = style_override
    chart = make_chart("area", x="date", y="value", color="series", **kwargs)
    resolved = resolve(chart, _DATA, chart_style_context=_BOARD_CTX)
    return resolved, _DATA


def _render_spec(resolved_chart, data):
    """Render and return the inner chart spec (unwraps endpoint-label hconcat)."""
    artifact = render_resolved_chart(resolved_chart, data, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    return spec["hconcat"][0] if "hconcat" in spec else spec


def _mark_types(spec: dict[str, Any]) -> list[str]:
    return [layer.get("mark", {}).get("type") for layer in spec.get("layer", [])]


def test_area_stacked_composition_uses_perimeter_stroke(make_chart):
    """stack='zero' emits one area layer with its own stroke, plus a hover point."""
    resolved, data = _make_area_chart(make_chart, stack="zero")
    spec = _render_spec(resolved, data)

    assert _mark_types(spec) == ["area", "point"], _mark_types(spec)
    area_mark = spec["layer"][0]["mark"]
    # Read opacity from the resolved mark rather than pinning the theme literal.
    assert area_mark.get("fillOpacity") == resolved.style.area_mark.opacity
    assert area_mark.get("strokeWidth", 0) > 0
    assert "stroke" in area_mark
    # Native perimeter stroke is NOT suppressed (unlike the overlap recipe's
    # strokeOpacity: 0, which forces a separate top-edge line instead).
    assert area_mark.get("strokeOpacity") != 0


def test_area_overlap_composition_unchanged(make_chart):
    """stack=None (overlap default) keeps halo + fg fill + top-line + hover."""
    resolved, data = _make_area_chart(make_chart, stack=None)
    spec = _render_spec(resolved, data)

    assert _mark_types(spec) == ["area", "line", "area", "line", "point"], _mark_types(
        spec
    )
    fg_area_mark = spec["layer"][2]["mark"]
    assert fg_area_mark.get("strokeOpacity") == 0


def test_area_normalize_composition_uses_perimeter_stroke(make_chart):
    """stack='normalize' gets the same solid-fill composition as stack='zero'."""
    resolved, data = _make_area_chart(make_chart, stack="normalize")
    spec = _render_spec(resolved, data)

    mark_types = _mark_types(spec)
    assert mark_types.count("area") == 1
    assert mark_types.count("line") == 0
    area_mark = spec["layer"][0]["mark"]
    assert area_mark.get("fillOpacity") == resolved.style.area_mark.opacity


def test_streamgraph_composition_and_suppressed_zero_rule(make_chart):
    """stack='center' (streamgraph) uses the solid recipe and drops the zero rule.

    The editorial theme enables area endpoint labels by default; center-stack
    endpoint labels raise ChartDataError (diverging domain).  Suppress them so
    this test isolates composition + zero-rule suppression from that rail.
    """
    resolved, data = _make_area_chart(
        make_chart,
        stack="center",
        style_override={"endpoint_labels": {"visible": False}},
    )
    spec = _render_spec(resolved, data)

    mark_types = _mark_types(spec)
    assert mark_types.count("area") == 1
    assert mark_types.count("line") == 0
    assert "rule" not in mark_types


def test_area_stacked_stroke_color_inherits_theme_background(make_chart):
    """Stacked area's perimeter stroke tracks the resolved theme background."""
    resolved, data = _make_area_chart(make_chart, stack="zero")
    spec = _render_spec(resolved, data)

    area_mark = spec["layer"][0]["mark"]
    assert area_mark["stroke"] == resolved.background


def test_area_mark_stacked_override_cascade(make_chart):
    """A chart-level stacked.stroke.width override merges through to emission."""
    resolved, data = _make_area_chart(
        make_chart,
        stack="zero",
        style_override={"marks": {"area": {"stacked": {"stroke": {"width": 9.0}}}}},
    )
    spec = _render_spec(resolved, data)

    area_mark = spec["layer"][0]["mark"]
    assert area_mark["strokeWidth"] == 9.0


def _make_multi_metric_area_chart(make_chart, stack: str | None):
    chart = make_chart("area", x="date", y=["revenue", "costs"], stack=stack)
    resolved = resolve(chart, _MULTI_DATA, chart_style_context=_BOARD_CTX)
    return resolved, _MULTI_DATA


def test_multi_metric_stacked_area_uses_perimeter_stroke(make_chart):
    """Multi-metric stacked area must emit perimeter strokes, not strokeOpacity:0.

    Regression: before the fix, _emit_multi_metric_area hardcoded
    strokeOpacity:0 even after resolve selected opacity=1.0, producing opaque
    bands with no separator — a split-brain worse than the original overlap.
    """
    resolved, data = _make_multi_metric_area_chart(make_chart, stack="zero")
    artifact = render_resolved_chart(resolved, data, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    spec = _render_spec(resolved, data)

    # Multi-metric areas use one folded unit: the single area mark still draws
    # every measure and receives the shared perimeter stroke.
    area_layers = [
        layer
        for layer in spec.get("layer", [])
        if isinstance(layer.get("mark"), dict) and layer["mark"].get("type") == "area"
    ]
    assert len(area_layers) == 1, area_layers
    # Read opacity from the resolved mark rather than pinning the theme literal.
    expected_opacity = resolved.style.area_mark.opacity
    mark = area_layers[0]["mark"]
    assert mark.get("fillOpacity") == expected_opacity, mark
    assert mark.get("strokeOpacity") != 0, mark
    assert mark.get("strokeWidth", 0) > 0, mark
    assert any(
        transform.get("fold") == ["revenue", "costs"] for transform in spec["transform"]
    )
