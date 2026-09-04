"""Authored `marks.point` styling must survive the layered render path.

A report claimed that `marks.point.stroke_width` and `.color` are dropped once
a chart gains a `layers:` entry — Looker's hollow-ring target marker rendering
as a solid disc. It does not reproduce: the layered path carries every authored
point channel through, on the base series and on an overlay layer alike
(isolation write-up in the task worksheet).

These tests pin that parity so the reported defect cannot start. Two halves,
because they exercise different emitters:

- the BASE series, which `emitters/line.py` hands to `emit_line_layer` with
  `pin_child_colors`/`inherit_parent_color` flipped by `bool(chart.layers)`;
- an OVERLAY layer's own `style.marks.point`, resolved by
  `compile/resolve/chart/_layers.py` and emitted via `emitters/_overlay.py`.

The base half reads the base's own sub-tree (`spec["layer"][0]`) rather than the
whole spec. Against the whole spec, a same-family overlay emits a mark identical
to the base's, so a base mark that loses its authored ink just drops out of the
filtered list and the overlay's slides into its place — the assertion holds and
the reported defect walks through. (A cross-family overlay emits no authored
point mark, so that shape would have been caught either way; the scoping is what
makes the same-family shape catchable too.)

Each mark is compared on its *effective paint*, not only its `mark.color`: a
layered render also pins the paint channel via `encoding`, and in Vega-Lite the
encoding wins. Comparing mark props alone would miss `pin_child_colors`
regressing the pinned value while `mark.color` stayed authored.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.authored._layer import AreaLayer, LineLayer
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

# The four channels the report's isolation table tracked, plus `size` (which
# gates whether a point sub-layer is emitted at all).
_POINT = {
    "size": 120,
    "filled": False,
    "fill": "#FFFFFF",
    "stroke_width": 3,
    "color": "#003AAB",
}
# What _POINT must become in VL. `fill` rides along only because `filled` is
# False — encoding.color owns the fill channel otherwise (`_emit_point_mark`).
# `paint` is synthesised by `_effective_paint`, not a VL mark prop.
_EXPECTED_VL = {
    "size": 120.0,
    "filled": False,
    "fill": "#FFFFFF",
    "strokeWidth": 3.0,
    "color": "#003AAB",
    "paint": "#003AAB",
}
_MARK_KEYS = ("size", "filled", "fill", "strokeWidth", "color")
_STYLE = {"marks": {"point": _POINT}}


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_config()
    yield
    reset_config()


def _rows() -> list[dict[str, Any]]:
    return [
        {"month": f"2025-{i + 1:02d}-01", "actual": 10.0 + i, "goal": 12.0}
        for i in range(12)
    ]


def _point_specs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Every sub-spec drawing a point a viewer can see, in paint order.

    Returns the enclosing sub-spec rather than the bare mark, because the paint
    a viewer gets depends on the sibling `encoding` as much as on the mark.
    Skips the invisible oversized hover hit-target (`opacity: 0`) that
    `_hover_target_point` appends to every line/area series.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        mark = node.get("mark")
        if isinstance(mark, dict) and mark.get("type") == "point":
            if mark.get("opacity") != 0:
                found.append(node)
        for key in ("layer", "hconcat", "vconcat"):
            for child in node.get(key) or []:
                walk(child)

    walk(spec)
    return found


def _effective_paint(node: dict[str, Any]) -> Any:
    """The colour that actually paints this point's ink.

    A hollow point takes its ink from `stroke`, a filled one from `fill`. The
    layered path pins that channel through `encoding`, which beats the mark
    prop in Vega-Lite, so the encoding value is the answer whenever it exists.
    """
    channel = "fill" if node["mark"].get("filled") is True else "stroke"
    pinned = node.get("encoding", {}).get(channel)
    if isinstance(pinned, dict) and "value" in pinned:
        return pinned["value"]
    return node["mark"].get("color")


def _authored_point_marks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The points carrying authored ink, reduced to the tracked channels.

    Filters on `color`, which drops the background-coloured halo point — the
    theme's own knockout mask, which never carries the authored colour (it does
    carry a scaled copy of the authored `size`, so `size` cannot be the filter).
    """
    out: list[dict[str, Any]] = []
    for node in _point_specs(spec):
        mark = node["mark"]
        if mark.get("color") != _POINT["color"]:
            continue
        tracked = {k: mark[k] for k in _MARK_KEYS if k in mark}
        tracked["paint"] = _effective_paint(node)
        out.append(tracked)
    return out


def _render(chart: Any, rows: list[dict[str, Any]], theme: str) -> dict[str, Any]:
    board_style, ctx = resolve_style_and_context(get_theme_style(theme))
    resolved = resolve(chart, rows, chart_style_context=ctx, width=600.0)
    artifact = render_resolved_chart(resolved, rows, board_style, width=600.0)
    assert artifact.kind == "vega_spec"
    return artifact.payload


def _base_subtree(spec: dict[str, Any]) -> dict[str, Any]:
    """The base series' own sub-spec in a layered render.

    `emitters/_overlay.py` puts the base chart's spec first and appends one
    wrapper per authored layer, so `layer[0]` is the base and nothing below it
    belongs to an overlay.
    """
    sub_layers = spec.get("layer")
    assert isinstance(sub_layers, list) and sub_layers, (
        f"expected a layered spec with the base at layer[0], got keys {sorted(spec)}"
    )
    return sub_layers[0]


# ---------------------------------------------------------------------------
# The base series' own point mark, with and without `layers:`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base_type", ["line", "area"])
@pytest.mark.parametrize("theme", ["stark", "clarity"])
def test_base_point_mark_identical_with_and_without_layers(
    make_chart: Any, base_type: str, theme: str
) -> None:
    """One `layers:` entry must not change the base series' own point mark."""
    rows = _rows()
    unlayered = _authored_point_marks(
        _render(make_chart(base_type, x="month", y="actual", style=_STYLE), rows, theme)
    )
    layered_spec = _render(
        make_chart(
            base_type,
            x="month",
            y="actual",
            style=_STYLE,
            layers=[LineLayer(type="line", y="goal", label="Goal")],
        ),
        rows,
        theme,
    )
    assert unlayered == [_EXPECTED_VL], (
        f"unlayered {base_type} lost authored point channels: {unlayered!r}"
    )
    assert _authored_point_marks(_base_subtree(layered_spec)) == unlayered, (
        f"adding one layer changed the base {base_type}'s own point mark; "
        f"expected {unlayered!r}, got {_point_specs(_base_subtree(layered_spec))!r}"
    )


# ---------------------------------------------------------------------------
# An overlay layer's own authored point mark
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base_type", ["line", "area", "bar"])
@pytest.mark.parametrize(
    ("layer_type", "layer_cls"), [("line", LineLayer), ("area", AreaLayer)]
)
def test_layer_authored_point_mark_reaches_the_spec(
    make_chart: Any, base_type: str, layer_type: str, layer_cls: type[Any]
) -> None:
    """A layer's own `style.marks.point` must emit every authored channel.

    The base chart authors no point style here, so the only mark carrying the
    authored ink is the overlay's own.
    """
    layer = layer_cls(
        type=layer_type,
        y="goal",
        label="Goal",
        style={"marks": {"point": _POINT}},
    )
    spec = _render(
        make_chart(base_type, x="month", y="actual", layers=[layer]), _rows(), "stark"
    )
    assert _authored_point_marks(spec) == [_EXPECTED_VL], (
        f"a {layer_type} layer on a {base_type} chart dropped authored point "
        f"channels: {_point_specs(spec)!r}"
    )
