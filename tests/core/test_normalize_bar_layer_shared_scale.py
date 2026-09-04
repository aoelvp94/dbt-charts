"""Regression: a ``stack: normalize`` bar keeps its [0, 1] percent axis even
when an overlay layer without ``axis_y`` shares the y-scale — or when no
layer is present at all.

Three independent things break once anything shares a normalize-stack bar's
y-scale (an overlay layer with no ``axis_y``, the common invisible
padding/reference-layer case):

- **Domain.** Vega-Lite infers ``[0, 1]`` from its own ``stack: normalize``
  transform on a lone series, but that inference is data-driven once the
  scale is shared — a layer's raw (unnormalized) values pull the rendered
  range away from ``[0, 1]``. Fixed by baking ``ay.scale.continuous.domain``
  at resolve time (``_bake_normalize_domain``, ``compile/resolve/chart/
  _domain.py``) so every measure-channel emitter picks it up via
  ``resolve_measure_y_scale``/``emit_resolved_scale_vl``, same as every
  other family.
- **Format.** Vega-Lite also auto-formats a lone normalize-stack axis as a
  percent, but that inference is dropped once the axis merges with a
  sibling layer's own axis config — the theme's plain-number default then
  wins, rendering a raw SI-abbreviated share axis (``250m`` instead of
  ``25%``). A normalize-stacked axis is *always* a 0-100% share axis — that
  is what ``stack: normalize`` means, unconditionally, not a default an
  author's own ``axis_y.labels.format`` can opt out of (confirmed empirically:
  authoring a custom format has no visible effect on an unlayered normalize
  stack either, since Vega-Lite's own inference already ignores
  ``axis.format`` there). Fixed by unconditionally pinning the percent
  format render-locally, on the VL axis dict only (``pin_normalize_axis_format``,
  ``emitters/_cartesian.py``, shared with area), NOT on the shared resolved ``ay.labels.format``,
  which value labels/stack-total labels/tooltips also read as their own
  fallback; baking the percent format there once corrupted every raw count
  into a percent (e.g. ``300`` → ``30000%``) — a value label on a
  normalize-stacked bar shows its own count, not the axis's share.
- **Collapse.** Pinning the domain to a fixed ``[0, 1]`` on a scale shared
  with an *unclipped* layer whose raw values fall outside it leaves that
  layer's marks painting past the plot bounds — under this repo's
  ``autosize: fit``, Vega shrinks the whole plot to fit every mark's paint,
  so the plot collapses to zero height (or width, horizontal) instead of
  just spilling past the axis (exactly the padding-layer repro this file
  exists to cover). Fixed by clipping only that layer's own marks
  (``_clip_layer_marks``, ``emitters/_overlay.py``, threaded via
  ``render_cartesian_overlay``'s ``base_stack_normalize`` param), gated on
  the layer's own row values actually falling outside the pinned domain —
  not merely on sharing the scale, which would also clip an in-range
  layer's marks/labels for no reason. The same per-mark ``clip: true``
  idiom this codebase already uses for the same autosize risk elsewhere
  (``CLIP_TO_PLOT`` in ``emitters/_layers.py``) — with one addition: a
  clipped `bar`-type layer also needs its corner-radius mark props
  stripped, since a rounded rect's local corner clip-path still reports
  its full unclipped bounds to `autosize: fit` regardless of the outer
  plot clip. An earlier attempt clipped
  the shared VL *view* instead, which does stop the collapse but also
  defeats ``autosize: fit``'s own bounds calculation for every other mark —
  the axis, category labels, and legend rendered entirely off-canvas.

Domain and collapse-handling are gated on "did the author already set this
themselves" — an explicit ``axis_y.scale``/``axis_y.position`` always wins.
Format is the one exception: it is unconditional, because a normalize-stack
axis's percent presentation is not something an author can opt out of.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
    resolve_style_and_context,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE = resolve_style(get_theme_style())
_BOARD_CTX = resolve_chart_style_context(get_theme_style())

_QUARTILE_VALUES = [0, 0.25, 0.5, 0.75, 1.0]
_PERCENT_WHOLE_FORMAT = ".0%"

# No `color`/`status` field: a series-colour channel opts a vertical bar into
# the endpoint-label rail, which independently back-fills encoding.y.scale as
# a side effect of positioning its labels — masking the bug this test exists
# to catch. Single-series data keeps the base emitter's own scale bare.
_DATA = [
    {"priority": "high", "ticket_count": 10, "padding": 100},
    {"priority": "low", "ticket_count": 8, "padding": 0},
]


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _spec(
    layers: list[dict[str, Any]],
    *,
    orientation: str = "vertical",
    axis_y: dict[str, Any] | None = None,
    data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    style: dict[str, Any] = {"orientation": orientation}
    if axis_y is not None:
        style["axis_y"] = axis_y
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "priority",
            "y": "ticket_count",
            "stack": "normalize",
            "style": style,
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


def _base_measure_encoding(
    spec: dict[str, Any], *, channel: str = "y"
) -> dict[str, Any]:
    """The base series' own measure encoding (``y`` for vertical, ``x`` for
    horizontal — horizontal swaps the measure onto VL's x channel).

    A shared-encoding template lives at the spec root (used by every sub-mark
    that doesn't override it, e.g. the baseline rules); an authored overlay
    layer with its own ``y``/``x`` column instead carries its own encoding
    under ``layer``. Prefer the root encoding when it already names the base
    measure; otherwise it's per-layer.
    """
    root_enc = spec.get("encoding", {}).get(channel)
    if isinstance(root_enc, dict) and root_enc.get("field") == "ticket_count":
        return root_enc
    return next(
        layer["encoding"][channel]
        for layer in spec["layer"]
        if layer.get("encoding", {}).get(channel, {}).get("field") == "ticket_count"
    )


def test_no_layer_still_pins_zero_to_one_percent_axis() -> None:
    """Baseline: even with no layers, domain and format are explicit."""
    y_enc = _base_measure_encoding(_spec([]))
    assert y_enc["scale"]["domain"] == [0, 1]
    assert y_enc["axis"]["values"] == _QUARTILE_VALUES
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_shared_scale_layer_with_out_of_range_values_keeps_percent_axis(
    orientation: str,
) -> None:
    """An overlay layer with no axis_y and raw (unnormalized) values must not
    leak into the base's percent domain, knock out its quartile ticks, or
    lose its percent tick format (VL drops its own normalize-format
    inference once the axis merges with the layer's own axis config)."""
    y_enc = _base_measure_encoding(
        _spec([{"type": "line", "y": "padding"}], orientation=orientation),
        channel="x" if orientation == "horizontal" else "y",
    )
    assert y_enc["scale"]["domain"] == [0, 1], (
        "shared-scale overlay layer values must not widen the normalize-stack "
        f"domain away from [0, 1]; got {y_enc['scale'].get('domain')!r}"
    )
    assert y_enc["axis"]["values"] == _QUARTILE_VALUES, (
        "percent-quartile ticks must survive a shared-scale overlay layer; "
        f"got {y_enc['axis'].get('values')!r}"
    )
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT, (
        "percent tick format must survive a shared-scale overlay layer, not "
        f"fall back to the theme's SI-number default; got {y_enc['axis'].get('format')!r}"
    )


def test_dual_axis_layer_unaffected() -> None:
    """A layer that pins axis_y.position already resolves an independent
    scale; pinning the base domain/format must not change that."""
    spec = _spec([{"type": "line", "y": "padding", "axis_y": {"position": "right"}}])
    assert spec.get("resolve", {}).get("scale", {}).get("y") == "independent"
    y_enc = _base_measure_encoding(spec)
    assert y_enc["scale"]["domain"] == [0, 1]
    assert y_enc["axis"]["values"] == _QUARTILE_VALUES
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT


def _has_plain_zero_rule(node: Any) -> bool:
    """True if a `datum: 0` rule mark sits anywhere in ``node``'s tree."""
    if isinstance(node, dict):
        mark = node.get("mark")
        mtype = mark.get("type") if isinstance(mark, dict) else mark
        if mtype == "rule":
            enc = node.get("encoding", {})
            if enc.get("y", {}).get("datum") == 0 or enc.get("x", {}).get("datum") == 0:
                return True
        return any(_has_plain_zero_rule(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_plain_zero_rule(v) for v in node)
    return False


def test_dual_axis_normalize_base_draws_no_plain_zero_rule() -> None:
    """A normalize-stacked base wants 0%/100% top rules, not a plain zero
    rule. Drawing those under an independent dual-axis scale is out of
    scope, so the base must get neither rather than the wrong reference
    line."""
    spec = _spec([{"type": "line", "y": "padding", "axis_y": {"position": "right"}}])
    # render_cartesian_overlay's paint-order contract: base first (bottom),
    # authored layers after in authored order; see its own docstring.
    base_layer = spec["layer"][0]
    assert not _has_plain_zero_rule(base_layer)


def test_authored_domain_is_not_overridden() -> None:
    """An author's own axis_y.scale.domain must win over the [0, 1] bake —
    the bake only fills in what the author left unset."""
    y_enc = _base_measure_encoding(
        _spec([], axis_y={"scale": {"continuous": {"domain": [0, 0.6]}}})
    )
    assert y_enc["scale"]["domain"] == [0, 0.6]


def test_authored_domain_survives_a_shared_scale_layer() -> None:
    """Same override, now with a shared-scale layer in the mix."""
    y_enc = _base_measure_encoding(
        _spec(
            [{"type": "line", "y": "padding"}],
            axis_y={"scale": {"continuous": {"domain": [0, 0.6]}}},
        )
    )
    assert y_enc["scale"]["domain"] == [0, 0.6]


@pytest.mark.parametrize(
    "authored_format",
    [
        pytest.param(",.2%", id="literal_percent_precision"),
        pytest.param("currency", id="unrelated_alias"),
        pytest.param("number", id="matches_theme_default"),
    ],
)
def test_authored_format_has_no_effect(authored_format: str) -> None:
    """A normalize-stack axis is always a 0-100% share axis — that's what
    `stack: normalize` means, unconditionally, not a default an author's own
    `axis_y.labels.format` can opt out of. Confirmed unconditional regardless
    of what's authored: an unrelated precision tweak, an alias for a totally
    different kind of number, or literally the theme's own default spelled
    out by hand."""
    y_enc = _base_measure_encoding(
        _spec([], axis_y={"labels": {"format": authored_format}})
    )
    assert y_enc["axis"]["format"] == _PERCENT_WHOLE_FORMAT


def _find_clip_specs(node: Any) -> list[Any]:
    """Every VL mark dict in ``node`` carrying ``clip: true``, found by
    walking the whole spec — used to tell "this layer was clipped" apart
    from "this layer wasn't", independent of exactly where in the spec tree
    the mark ended up."""
    found: list[Any] = []
    if isinstance(node, dict):
        if node.get("clip") is True:
            found.append(node)
        found.extend(c for v in node.values() for c in _find_clip_specs(v))
    elif isinstance(node, list):
        found.extend(c for v in node for c in _find_clip_specs(v))
    return found


def test_in_range_shared_scale_layer_is_not_clipped() -> None:
    """A shared-scale layer whose values are already fractions inside
    [0, 1] must render exactly as it would with no clip at all — gating the
    clip on "shares the scale" alone (rather than on the layer's own values
    actually falling outside the domain) would cut off an in-range value
    sitting right at the domain edge (a label, or half a stroke width). A
    `bar`-type layer has no pre-existing clip of its own (unlike line/area,
    whose halo and hover-target sub-marks are always clipped), so any `clip`
    key found here is the gate's own doing, not a mark that was always
    clipped regardless of this fix."""
    data = [
        {"priority": "high", "ticket_count": 10, "target": 1.0},
        {"priority": "low", "ticket_count": 8, "target": 0.5},
    ]
    spec = _spec([{"type": "bar", "y": "target"}], data=data)
    assert not _find_clip_specs(spec), "in-range shared-scale bar layer was clipped"


def test_clip_gate_reads_the_authored_domain_not_a_hardcoded_unit_range() -> None:
    """The clip gate must test a layer's values against the axis's actual
    pinned domain, not a hardcoded [0, 1] — an authored wider domain must
    not clip an in-authored-range value, and an authored narrower domain
    must clip a value that's in [0, 1] but outside the authored range.
    `bar`-type layer (see `test_in_range_shared_scale_layer_is_not_clipped`
    for why any found `clip` is provably this gate's own doing)."""
    wider_spec = _spec(
        [{"type": "bar", "y": "target"}],
        axis_y={"scale": {"continuous": {"domain": [0, 1.2]}}},
        data=[
            {"priority": "high", "ticket_count": 10, "target": 1.1},
            {"priority": "low", "ticket_count": 8, "target": 0.9},
        ],
    )
    assert not _find_clip_specs(wider_spec), (
        "value inside an authored wider domain [0, 1.2] was clipped"
    )

    narrower_spec = _spec(
        [{"type": "bar", "y": "target"}],
        axis_y={"scale": {"continuous": {"domain": [0, 0.6]}}},
        data=[
            {"priority": "high", "ticket_count": 10, "target": 0.8},
            {"priority": "low", "ticket_count": 8, "target": 0.5},
        ],
    )
    assert _find_clip_specs(narrower_spec), (
        "value inside [0, 1] but outside an authored narrower domain [0, 0.6] "
        "was not clipped"
    )


def test_clip_gate_normalizes_a_descending_authored_domain() -> None:
    """An authored domain's two arms aren't guaranteed ascending (nothing on
    the authoring path enforces low <= high) — the gate's sibling helper
    `effective_measure_domain` and the baseline gate both normalize with
    min()/max() for exactly this reason. An unnormalized `not lo <= f <= hi`
    is True for every finite value once lo > hi, clipping every shared-scale
    layer regardless of its actual values. `bar`-type layer (see
    `test_in_range_shared_scale_layer_is_not_clipped` for why)."""
    data = [
        {"priority": "high", "ticket_count": 10, "target": 0.5},
        {"priority": "low", "ticket_count": 8, "target": 0.4},
    ]
    spec = _spec(
        [{"type": "bar", "y": "target"}],
        axis_y={"scale": {"continuous": {"domain": [1, 0]}}},
        data=data,
    )
    assert not _find_clip_specs(spec), (
        "an in-range value under a descending authored domain [1, 0] was clipped"
    )


@pytest.mark.parametrize(
    "padding_values",
    [
        pytest.param(["n/a", "n/a"], id="non_numeric_string"),
        pytest.param([Decimal("NaN"), Decimal("NaN")], id="decimal_nan"),
        pytest.param([10**400, 10**400], id="huge_int_overflow"),
    ],
)
def test_shared_scale_layer_with_uncomparable_values_is_not_clipped(
    padding_values: list[Any],
) -> None:
    """A shared-scale layer bound to a column with a value this check can't
    treat as a finite number in [0, 1] — not a real number at all, a NaN, or
    (an authored inline `values:` query preserves an arbitrary-precision
    YAML int all the way to this check) too large to represent as a float —
    must not raise, and must not be clipped either: nothing paints outside
    the plot, so there's no collapse risk to guard against. A naive Python
    type check (isinstance int/float/Decimal) passes `Decimal("NaN")`
    through, and `Decimal("NaN") <= 1` itself raises; `float(10**400)`
    raises `OverflowError` (an `ArithmeticError`) — the check has to mirror
    VL's own isFinite filter, not just "is this a numeric type". `bar`-type
    layer (see `test_in_range_shared_scale_layer_is_not_clipped` for why)."""
    data = [
        {"priority": "high", "ticket_count": 10, "padding": padding_values[0]},
        {"priority": "low", "ticket_count": 8, "padding": padding_values[1]},
    ]
    spec = _spec([{"type": "bar", "y": "padding"}], data=data)
    assert not _find_clip_specs(spec), (
        f"a value VL itself would drop ({padding_values[0]!r}) triggered a clip"
    )


def test_shared_scale_layer_with_numeric_string_is_clipped() -> None:
    """A numeric *string* (e.g. a ::text-cast or CSV-sourced column) is
    exactly as real a number to Vega-Lite as an int or float — VL's own
    quantitative encoding parses and paints it. A gate that only recognizes
    Python int/float/Decimal misses this case entirely, so the layer never
    gets clipped and the plot collapses under autosize: fit exactly as if
    the domain were never pinned. `bar`-type layer (see
    `test_in_range_shared_scale_layer_is_not_clipped` for why) — the found
    clip is provably this gate's own doing, not a pre-existing one."""
    data = [
        {"priority": "high", "ticket_count": 10, "padding": "100"},
        {"priority": "low", "ticket_count": 8, "padding": "0"},
    ]
    spec = _spec([{"type": "bar", "y": "padding"}], data=data)
    assert _find_clip_specs(spec), "out-of-range numeric-string layer was not clipped"


def _rendered_plot_background(
    spec: dict[str, Any],
) -> tuple[element_tree.Element | None, float, float]:
    """The SVG <path class="background"> for the chart's own plot area — the
    first one Vega emits, before any legend/axis background rects. A spec
    assertion alone can't see this: a pinned-but-unclipped domain still
    reports the "correct" domain/format while the rendered chart is broken
    in a way no spec field describes (see the module docstring's "Collapse"
    case) — the plot can shrink to zero height, or (view-level clipping,
    rather than per-mark) the axis/legend furniture can be pushed off the
    rendered canvas entirely while the plot itself fills it."""
    vl_convert = pytest.importorskip("vl_convert")
    root = element_tree.fromstring(vl_convert.vegalite_to_svg(spec))
    ns = "{http://www.w3.org/2000/svg}"
    canvas_w = float(root.attrib["width"])
    canvas_h = float(root.attrib["height"])
    for path in root.iter(f"{ns}path"):
        if path.attrib.get("class") == "background":
            return path, canvas_w, canvas_h
    return None, canvas_w, canvas_h


@pytest.mark.parametrize("layer_type", ["bar", "line", "area", "scatter"])
@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_shared_scale_layer_out_of_range_does_not_collapse_the_plot(
    layer_type: str, orientation: str
) -> None:
    """The padding-layer repro itself: a shared-scale layer whose values fall
    far outside [0, 1] must not break the rendered chart, on any layer mark
    type or orientation. Domain and format assertions alone don't catch this
    — the axis can render correctly on a plot that has shrunk to zero
    height (or zero width, horizontal), or the plot can fill the whole
    canvas because clipping the shared VL view (rather than just the
    offending layer's marks) pushed every other mark — axis, category
    labels, legend — off-canvas along with it. A `bar` layer needs its own
    case: a clipped-but-rounded bar mark's local corner-radius clip-path
    still reports its full unclipped bounds to `autosize: fit`, collapsing
    the plot exactly like an unclipped mark would — clip alone isn't
    sufficient for that mark type, only clip-plus-square-corners is."""
    spec = _spec([{"type": layer_type, "y": "padding"}], orientation=orientation)
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


def test_value_labels_survive_the_percent_axis_format() -> None:
    """Value labels on a normalize-stack bar must keep printing the raw
    column value (e.g. "300"), not the axis's percent format (e.g. "30000%")
    — the two surfaces share ay.labels.format when unauthored, so a fix that
    bakes the percent format onto that shared field corrupts labels even
    though every domain/format axis assertion still passes."""
    compiled = get_theme_style("clarity")
    new_labels = compiled.charts.marks.bar.labels.model_copy(update={"visible": True})
    new_bar = compiled.charts.marks.bar.model_copy(update={"labels": new_labels})
    new_marks = compiled.charts.marks.model_copy(update={"bar": new_bar})
    charts = compiled.charts.model_copy(update={"marks": new_marks})
    board_style, board_ctx = resolve_style_and_context(
        compiled.model_copy(update={"charts": charts})
    )
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "priority",
            "y": "ticket_count",
            "color": "status",
            "stack": "normalize",
            "style": {"orientation": "vertical"},
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "layers": [],
        }
    )
    data = [
        {"priority": "high", "status": "new", "ticket_count": 300},
        {"priority": "low", "status": "new", "ticket_count": 100},
    ]
    spec = generate_vega_lite_spec(
        chart, data, width=400, board_style=board_style, chart_style_context=board_ctx
    )
    vl_convert = pytest.importorskip("vl_convert")
    root = element_tree.fromstring(vl_convert.vegalite_to_svg(spec))
    ns = "{http://www.w3.org/2000/svg}"
    texts = {t.text for t in root.iter(f"{ns}text")}
    assert "300" in texts and "100" in texts, (
        f"expected raw value labels 300/100 in the rendered SVG; got {texts!r}"
    )
    axis_percent_ticks = {"0%", "25%", "50%", "75%", "100%"}
    leaked = {t for t in texts if t and t.endswith("%")} - axis_percent_ticks
    assert not leaked, (
        f"a value label rendered as a percent (axis-format leak): {leaked!r}"
    )
