"""Regression: a ``stack: normalize`` area keeps its percent axis and its
plot from collapsing when an overlay layer without ``axis_y`` shares the
y-scale.

Area already baked the ``[0, 1]`` domain at resolve time (shared with bar via
``_bake_normalize_domain``), so unlike bar this file doesn't re-cover domain.
Two things were still area-specific bugs, fixed by wiring area into the same
shared helpers bar already used (``pin_normalize_axis_format``,
``_cartesian.py``; ``base_stack_normalize``, ``_overlay.py``):

- **Format.** Both of area's own encoding builders (single-metric
  ``_build_area_top_encoding`` and wide/multi-metric
  ``_emit_multi_metric_area``) independently set ``y_enc["stack"]`` but never
  pinned the axis format the way bar does — a shared-scale layer knocked the
  axis back to the theme's plain SI-number default exactly as it did for bar
  before that fix.
- **Collapse.** ``AreaEmitter`` always called ``render_cartesian_overlay``
  with ``base_stack_normalize=False`` (an explicit, commented deferral), so
  bar's clip-the-offending-layer fix never applied to area: a shared-scale
  layer with raw (unnormalized) values collapsed the plot to zero height
  under ``autosize: fit``, identical to the bar bug this whole fix started
  from.

See ``test_normalize_bar_layer_shared_scale.py`` for the fuller domain/
collapse mechanics shared by both families.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
from typing import Any

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE = resolve_style(get_theme_style())
_BOARD_CTX = resolve_chart_style_context(get_theme_style())

_PERCENT_WHOLE_FORMAT = ".0%"

# Single-series data keeps the base emitter's own scale bare, same rationale
# as the bar test's _DATA (no color/status field masking the bug via the
# endpoint-label rail's own scale back-fill).
_DATA = [
    {"month": "jan", "ticket_count": 10, "padding": 100},
    {"month": "feb", "ticket_count": 8, "padding": 0},
]

_WIDE_DATA = [
    {"month": "jan", "a": 10, "b": 5, "padding": 100},
    {"month": "feb", "a": 8, "b": 2, "padding": 0},
]


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _spec(
    layers: list[dict[str, Any]],
    *,
    y: str | list[str] = "ticket_count",
    data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "area",
            "x": "month",
            "y": y,
            "stack": "normalize",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "layers": layers,
        }
    )
    return generate_vega_lite_spec(
        chart,
        data if data is not None else _DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )


def _base_measure_encoding(spec: dict[str, Any], *, field: str) -> dict[str, Any]:
    root_enc = spec.get("encoding", {}).get("y")
    if isinstance(root_enc, dict) and root_enc.get("field") == field:
        return root_enc
    matches = [
        layer["encoding"]["y"]
        for layer in spec["layer"]
        if layer.get("encoding", {}).get("y", {}).get("field") == field
    ]
    assert matches, f"no y encoding for field {field!r} found in spec: {spec!r}"
    return matches[0]


def test_no_layer_still_pins_percent_axis() -> None:
    y_enc = _base_measure_encoding(_spec([]), field="ticket_count")
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT


def test_shared_scale_layer_keeps_percent_axis_format() -> None:
    """An overlay layer with no axis_y and raw (unnormalized) values must
    not knock the axis back to the theme's SI-number default."""
    y_enc = _base_measure_encoding(
        _spec([{"type": "line", "y": "padding"}]), field="ticket_count"
    )
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT, (
        "percent tick format must survive a shared-scale overlay layer; "
        f"got {y_enc['axis'].get('format')!r}"
    )


def test_wide_multi_metric_area_pins_percent_axis() -> None:
    """The wide/multi-metric path (y: [a, b]) has its own encoding builder
    and must pin the same format independently of the single-metric path.
    Wide multi-metric area folds into an hconcat'd spec (color-series
    legend), so the measure encoding lives at hconcat[0], not the plain
    root/layer shape single-metric area and bar use; no layers case exists
    to test here — overlay layers are rejected outright on a multi-y chart
    (a separate, pre-existing constraint, not part of this fix)."""
    spec = _spec([], y=["a", "b"], data=_WIDE_DATA)
    y_enc = spec["hconcat"][0]["encoding"]["y"]
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT


def _rendered_plot_background(
    spec: dict[str, Any],
) -> tuple[element_tree.Element | None, float, float]:
    vl_convert = pytest.importorskip("vl_convert")
    root = element_tree.fromstring(vl_convert.vegalite_to_svg(spec))
    ns = "{http://www.w3.org/2000/svg}"
    canvas_w = float(root.attrib["width"])
    canvas_h = float(root.attrib["height"])
    for path in root.iter(f"{ns}path"):
        if path.attrib.get("class") == "background":
            return path, canvas_w, canvas_h
    return None, canvas_w, canvas_h


def test_shared_scale_layer_out_of_range_does_not_collapse_the_plot() -> None:
    """The padding-layer repro: a shared-scale layer whose values fall far
    outside [0, 1] must not shrink the plot to zero height under
    autosize: fit — the same collapse bar's fix already covers, now wired
    through for area via base_stack_normalize."""
    spec = _spec([{"type": "line", "y": "padding"}])
    bg, canvas_w, canvas_h = _rendered_plot_background(spec)
    assert bg is not None, "expected a plot background rect in the rendered SVG"
    path_d = bg.attrib["d"]
    assert "v0h" not in path_d and "h0v" not in path_d, (
        f"plot collapsed to zero width or height: {path_d!r}"
    )
    dims = re.match(r"M[\d.]+,[\d.]+h([\d.]+)v([\d.]+)h", path_d)
    assert dims is not None, f"unrecognized plot background path: {path_d!r}"
    plot_w, plot_h = float(dims.group(1)), float(dims.group(2))
    assert plot_w < canvas_w and plot_h < canvas_h, (
        "plot fills the entire canvas — the axis/category-label/legend "
        f"furniture has no room left and rendered off-canvas: plot "
        f"{plot_w}x{plot_h} vs. canvas {canvas_w}x{canvas_h}"
    )
