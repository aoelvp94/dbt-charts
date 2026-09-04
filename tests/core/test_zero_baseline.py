"""Zero-baseline rule mark for bar / area / line charts.

Vega renders axis guides (grid lines) BELOW marks, so area/bar fills cover the
bold zero baseline produced by the conditional ``gridColor`` encoding. A rule
mark layer at the top of the layer stack renders above all fills and restores
the baseline.

Constraints:
- Scope: bar (vertical and horizontal), area, line, and scatter. Other chart
  families (pie, heatmap, ...) don't emit the rule.
- Only emit when 0 is in the measure-axis domain (no rule for line charts
  whose y-domain is e.g. [75000, 183000], or for charts with explicit
  ``scale.domain`` excluding 0).
- Encoding explicitly overrides shared x/x2/color so the rule renders as one
  full-width horizontal line, not a per-series fragment.
- The rule layer ships its own single-row data so VL emits the rule once
  rather than iterating it per parent data row at identical pixel coords.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import BarChart, Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    AxisXStylePatch,
    AxisYStylePatch,
    BarChartStylePatch,
    BaseScaleStylePatch,
    ChartStylePatch,
    LineChartStylePatch,
    MeasureGridStylePatch,
    ScaleContinuousStylePatch,
    ScatterChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())


_RANK_DATA = [
    {"x": 2019 + period, "s": f"S{series}", "y": 1 + ((series + period) % 6)}
    for series in range(6)
    for period in range(5)
]

# Area rejects more than one row per x, so its rank fixture is a single series.
_SINGLE_RANK_DATA = [{"x": 2019 + p, "y": 1 + (p % 6)} for p in range(5)]


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _spec(
    chart_type: str,
    data: list[dict],
    style: ChartStylePatch | None = None,
    color: str | None = None,
) -> dict:
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": chart_type,
            "x": "x",
            "y": "y",
            "color": color,
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "style": style,
        }
    )
    return generate_vega_lite_spec(
        chart, data, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )


def _main_pane(spec: dict) -> dict:
    """Return the main chart pane, unwrapping hconcat if endpoint labels are active."""
    return spec["hconcat"][0] if "hconcat" in spec else spec


def _zero_rule_layer(spec: dict) -> dict | None:
    """Return the zero-rule layer from a layered spec (or None).

    Vertical area/bar charts encode the rule as ``y: datum:0`` (horizontal
    rule); horizontal bars encode it as ``x: datum:0`` (vertical rule).
    When endpoint labels are enabled (editorial default), area/line charts emit
    hconcat; the layers live at hconcat[0] in that case.
    """
    for layer in _main_pane(spec).get("layer", []):
        mark = layer.get("mark", {})
        if not (isinstance(mark, dict) and mark.get("type") == "rule"):
            continue
        enc = layer.get("encoding", {})
        if enc.get("y", {}).get("datum") == 0 or enc.get("x", {}).get("datum") == 0:
            return layer
    return None


_POSITIVE_DATA = [{"x": "a", "y": 5}, {"x": "b", "y": 10}, {"x": "c", "y": 7}]
_STRADDLE_ZERO_DATA = [{"x": "a", "y": 5}, {"x": "b", "y": -3}, {"x": "c", "y": 8}]
_ALL_NEGATIVE_DATA = [{"x": "a", "y": -95}, {"x": "b", "y": -60}, {"x": "c", "y": -17}]
_FLAT_ALL_NEGATIVE_DATA = [
    {"x": "a", "y": -50},
    {"x": "b", "y": -50},
    {"x": "c", "y": -50},
]
# CSV adapters return numeric columns as strings; VL coerces via encoding.type.
# The rule emit must not skip such data (regression: previously dropped because
# _domain_includes_zero scanned only Python-native ints/floats).
_POSITIVE_DATA_CSV_STRINGS = [
    {"x": "a", "y": "5"},
    {"x": "b", "y": "10"},
    {"x": "c", "y": "7"},
]
# Same CSV-string regression, but for area: the smart-zero heuristic now
# genuinely runs on string-coerced data (previously it silently saw an empty
# extent and always fired the rule). Area always zero-anchors positive data
# regardless of ratio, so this and _POSITIVE_DATA_CSV_STRINGS both fire the
# rule — kept as two fixtures for CSV-string coverage at two data shapes.
_NEAR_ZERO_DATA_CSV_STRINGS = [
    {"x": "a", "y": "50"},
    {"x": "b", "y": "480"},
    {"x": "c", "y": "200"},
]
# DuckDB returns SUM/aggregation results as decimal.Decimal (DECIMAL(38,6) type).
# Tight-range ratio ≈ 0.88 replicates the pipeline_compact bug: _pick_scale
# formerly set zero:False for ratio > 0.8, triggering the scan path where
# Decimal values were silently skipped → zero rule dropped.
_TIGHT_RANGE_DECIMAL = [
    {"x": "Paid Search", "y": Decimal("27147.000000")},
    {"x": "Outbound", "y": Decimal("26727.000000")},
    {"x": "Website", "y": Decimal("23880.000000")},
]


# ── Behavioral: when does the rule appear? ────────────────────────────────────


def test_area_starting_near_zero_appends_rule():
    """Area chart with data close to zero (ratio <= 0.25) → zero baseline → rule emitted.

    The smart-auto heuristic doesn't suppress zero when data is close to the
    origin (min/max <= 0.25 threshold), so 0 stays in domain and the rule fires.
    """
    # ratio = 50/480 ≈ 0.10 ≤ 0.25 → no scale override → VL extends to zero
    data_near_zero = [
        {"x": "a", "y": 50},
        {"x": "b", "y": 480},
        {"x": "c", "y": 200},
    ]
    spec = _spec("area", data_near_zero)
    assert _zero_rule_layer(spec) is not None


def test_area_multi_series_straddling_zero_appends_rule():
    """Multi-series area (cream-knockout case) straddling zero → rule appended after halo+fg."""
    spec = _spec("area", _STRADDLE_ZERO_DATA, color="x")
    assert _zero_rule_layer(spec) is not None


def test_area_clustered_above_threshold_still_appends_rule():
    """Area chart with clustered values (ratio > 0.25) still gets the zero rule.

    Area always zero-anchors all-positive data (like bar) regardless of ratio:
    the fill is the magnitude encoding, so a truncated domain would misstate
    the quantity — e.g. CSAT scores (88-96) rendered as a near-solid fill.
    """
    # ratio ≈ 0.92 > 0.25 — no longer suppresses the rule for area.
    data_clustered = [
        {"x": "Jan", "y": 88},
        {"x": "Feb", "y": 91},
        {"x": "Mar", "y": 96},
    ]
    spec = _spec("area", data_clustered)
    assert _zero_rule_layer(spec) is not None


def test_area_negative_values_appends_rule():
    """Area with negative y values → 0 mid-domain → rule emitted."""
    spec = _spec("area", _STRADDLE_ZERO_DATA)
    assert _zero_rule_layer(spec) is not None


def test_bar_vertical_appends_rule():
    """Vertical bar chart → rule emitted at y=0 baseline."""
    spec = _spec("bar", _POSITIVE_DATA)
    assert _zero_rule_layer(spec) is not None


def test_bar_with_csv_string_values_appends_rule():
    """CSV-loaded data has string-typed numerics. The default scale.zero=true
    on bar/area still puts 0 in the domain regardless of data dtype, so the
    rule must be emitted."""
    spec = _spec("bar", _POSITIVE_DATA_CSV_STRINGS)
    assert _zero_rule_layer(spec) is not None


def test_area_with_csv_string_values_appends_rule():
    """Smoke pin: CSV-loaded string-typed measures resolve end to end for area."""
    spec = _spec("area", _NEAR_ZERO_DATA_CSV_STRINGS)
    assert _zero_rule_layer(spec) is not None


def test_line_with_csv_string_values_far_from_zero_skips_rule():
    """CSV-string regression pin for an optional-zero family: line's
    smart-zero heuristic must see the real, parsed extent of string-typed
    measures, not an empty one. ratio = 5/10 = 0.5 > 0.25, so the heuristic
    keeps the domain data-fitted (``zero: False``) and the rule must not
    fire — string values must not silently read as an empty extent that
    fires the rule unconditionally instead."""
    spec = _spec("line", _POSITIVE_DATA_CSV_STRINGS)
    assert _zero_rule_layer(spec) is None


def test_bar_with_tight_range_decimal_values_appends_rule():
    """Regression: DuckDB SUM() returns Decimal values. When min/max ratio was >0.8
    _pick_scale set zero:False, falling to the data scan where Decimal was silently
    skipped → zero rule dropped even though VL still renders 0 for bars.
    Fix: remove the ratio>0.8 rule for non-optional-zero chart types."""
    spec = _spec("bar", _TIGHT_RANGE_DECIMAL)
    assert _zero_rule_layer(spec) is not None


def test_horizontal_bar_with_tight_range_decimal_values_appends_rule():
    """Same regression for horizontal bars (pipeline_compact pattern)."""
    spec = _spec(
        "bar",
        _TIGHT_RANGE_DECIMAL,
        style=BarChartStylePatch(orientation="horizontal"),
    )
    assert _zero_rule_layer(spec) is not None


def test_bar_with_negative_values_appends_rule():
    """Bar chart with negative values → rule mid-chart, on top of bars."""
    spec = _spec("bar", _STRADDLE_ZERO_DATA)
    assert _zero_rule_layer(spec) is not None


def test_bar_horizontal_emits_vertical_rule_at_x_zero():
    """Horizontal bars: zero baseline lives on the quantitative x-axis →
    the rule is a vertical line at x=0 spanning the plot height."""
    spec = _spec(
        "bar",
        _POSITIVE_DATA,
        style=BarChartStylePatch(orientation="horizontal"),
    )
    rule = _zero_rule_layer(spec)
    assert rule is not None
    enc = rule["encoding"]
    assert enc.get("x") == {"datum": 0, "type": "quantitative"}
    assert enc.get("y") == {"value": 0}
    assert enc.get("y2") == {"value": "height"}


def test_line_chart_with_positive_only_data_skips_rule():
    """Line charts with all-positive data do NOT get the zero-baseline rule.

    The pipeline infers ``zero=False`` for positive-data line charts and writes
    it to the VL y-encoding as ``scale.zero: false``.  ``_domain_includes_zero``
    now checks ``resolved_chart.zero`` first, so the zero rule is suppressed —
    avoiding the datum:0 that would expand VL's shared y-scale from
    [data_min, data_max] to [0, data_max] and compress endpoint-label gaps
    below font_size.

    Regression: the old implementation only checked the style cascade's
    ``scale.zero`` (which is None / unset in the theme), so ``None is not False``
    returned True and fired the rule even when the renderer had already set
    ``scale.zero=False`` from the inferred ``resolved_chart.zero``.
    """
    spec = _spec("line", _POSITIVE_DATA)
    assert _zero_rule_layer(spec) is None


def test_line_chart_explicit_domain_excluding_zero_skips_rule():
    """A line chart whose y-domain doesn't include zero (temperature ranges,
    indexed values, etc.) skips the rule. Gated by ``_domain_includes_zero``,
    not the chart-type set."""
    style = LineChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[100, 200])
            )
        )
    )
    spec = _spec("line", _POSITIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


def test_line_chart_descending_domain_excluding_zero_skips_rule():
    """A rank axis runs high-to-low and has no rank 0.

    The bar branch already suppressed the rule for an authored domain that
    excludes zero; line and area went straight to `should_fire = True` unless
    `scale.zero` was explicitly false. On a descending domain the rule has
    nowhere legal to land, so Vega-Lite drew it clamped above the top of the
    plot — a heavy rule floating over a bump chart, at a rank that cannot
    exist.
    """
    style = LineChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[6, 1])
            )
        )
    )
    spec = _spec("line", _RANK_DATA, style=style, color="s")

    assert _zero_rule_layer(spec) is None


def test_area_descending_domain_excluding_zero_skips_rule():
    style = AreaChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[6, 1])
            )
        )
    )

    assert _zero_rule_layer(_spec("area", _SINGLE_RANK_DATA, style=style)) is None


def test_line_chart_domain_spanning_zero_still_appends_rule():
    """The guard keys on the domain excluding zero, not on it being authored."""
    style = LineChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[-2, 6])
            )
        )
    )
    spec = _spec("line", _RANK_DATA, style=style, color="s")

    assert _zero_rule_layer(spec) is not None


def test_line_chart_scale_zero_false_with_positive_only_data_skips_rule():
    """``scale.zero=false`` plus all-positive data → 0 not in domain → no rule
    on a line chart. Same predicate that gates bar/area applies."""
    style = LineChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(continuous=ScaleContinuousStylePatch(zero=False))
        )
    )
    spec = _spec("line", _POSITIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


def test_line_chart_straddling_zero_appends_rule():
    """Line chart whose data straddles 0 → rule must still be emitted.

    Even though the pipeline infers zero=False for line charts, when the data
    actually straddles zero (min<0, max>0) the rule fires to mark the visible
    baseline.  Regression guard for the _domain_includes_zero data-range fallback.
    """
    spec = _spec("line", _STRADDLE_ZERO_DATA)
    assert _zero_rule_layer(spec) is not None


def test_scatter_chart_straddling_zero_gets_rule():
    """Scatter gets the same zero rule as line and area."""
    spec = _spec("scatter", _STRADDLE_ZERO_DATA)
    assert _zero_rule_layer(spec) is not None


def test_scatter_chart_far_from_zero_skips_rule():
    """Same far-from-zero, non-straddling shape as line: no rule, for the same
    reason — the inferred zero=False and the data never touches 0."""
    spec = _spec("scatter", _POSITIVE_DATA)
    assert _zero_rule_layer(spec) is None


def test_scatter_chart_all_negative_skips_rule():
    """All-negative data: resolve's smart-zero heuristic abstains (out of
    scope for all-negative data), so the domain edges get baked from the data
    itself (headroom-expanded, not clamped to 0). 0 is never in that domain,
    so the rule must not fire."""
    spec = _spec("scatter", _ALL_NEGATIVE_DATA)
    assert _zero_rule_layer(spec) is None


def test_scatter_chart_flat_all_negative_skips_rule():
    """Same all-negative abstain case, but with zero span — headroom has
    nothing to expand, so domain_min/domain_max are both left unbaked
    (None). Reading an unbaked edge as 0.0 previously misread this as
    zero-anchored."""
    spec = _spec("scatter", _FLAT_ALL_NEGATIVE_DATA)
    assert _zero_rule_layer(spec) is None


def test_scatter_chart_all_negative_headroom_zero_skips_rule():
    """headroom: 0 is an ordinary authored knob that also leaves
    domain_min/domain_max unbaked for all-negative data — same failure
    shape as the flat case above, reached a different way."""
    style = ScatterChartStylePatch(
        axis_y=AxisYStylePatch(scale=BaseScaleStylePatch(headroom=0))
    )
    spec = _spec("scatter", _ALL_NEGATIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


def test_scatter_chart_all_negative_authored_scale_values_skips_rule():
    """An authored tick ladder bypasses the domain_min/domain_max bake
    entirely (``_resolve_cartesian_ticks`` returns early on an authored
    ladder), so this reaches the same unbaked-edges shape from a third
    direction."""
    style = ScatterChartStylePatch(
        axis_y=AxisYStylePatch(scale=BaseScaleStylePatch(values=[-100, -50, -10]))
    )
    spec = _spec("scatter", _ALL_NEGATIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


# ── 0-not-in-domain: rule must NOT be emitted ─────────────────────────────────


def test_explicit_scale_domain_excluding_zero_skips_rule_area():
    """axis_y.scale.domain=[100, 200] → 0 outside → no rule."""
    style = AreaChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[100, 200])
            )
        )
    )
    spec = _spec("area", _POSITIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


def test_explicit_scale_domain_excluding_zero_skips_rule_bar():
    """Same for bar charts: explicit y-domain excluding 0 → no rule."""
    style = BarChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[100, 200])
            )
        )
    )
    spec = _spec("bar", _POSITIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


def test_scale_zero_false_with_positive_only_data_skips_rule():
    """scale.zero=false + all-positive data → 0 not in domain → no rule."""
    style = AreaChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(continuous=ScaleContinuousStylePatch(zero=False))
        )
    )
    spec = _spec("area", _POSITIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


def test_scale_zero_false_with_data_straddling_zero_emits_rule():
    """scale.zero=false but data has negative + positive → 0 in domain → rule."""
    style = AreaChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(continuous=ScaleContinuousStylePatch(zero=False))
        )
    )
    spec = _spec("area", _STRADDLE_ZERO_DATA, style=style)
    assert _zero_rule_layer(spec) is not None


def test_scale_zero_false_with_decimal_straddling_zero_emits_rule():
    """scale.zero=false + Decimal values straddling zero → rule must fire.

    Regression: _domain_includes_zero scanned only int/float/str, silently
    skipping Decimal → values list empty → returned False even when data
    crossed zero."""
    straddle = [
        {"x": "a", "y": Decimal("10.000000")},
        {"x": "b", "y": Decimal("-3.000000")},
    ]
    style = AreaChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(continuous=ScaleContinuousStylePatch(zero=False))
        )
    )
    spec = _spec("area", straddle, style=style)
    assert _zero_rule_layer(spec) is not None


def test_grid_not_visible_skips_rule():
    """grid.visible=False suppresses the zero rule (same gate as regular gridlines)."""
    style = AreaChartStylePatch(
        axis_y=AxisYStylePatch(
            grid=MeasureGridStylePatch(visible=False),
        ),
    )
    spec = _spec("area", _POSITIVE_DATA, style=style)
    assert _zero_rule_layer(spec) is None


# ── Encoding correctness ──────────────────────────────────────────────────────


def test_zero_rule_has_explicit_x_x2_color_overrides():
    """Rule layer overrides x/x2/color so it renders as one full-width line.

    Without these overrides, the layer inherits shared encoding's x (data-driven)
    and color (series-bound), causing per-series fragmentation.
    Uses straddling-zero data to guarantee the rule is emitted for area.
    """
    spec = _spec("area", _STRADDLE_ZERO_DATA, color="x")
    rule = _zero_rule_layer(spec)
    assert rule is not None
    enc = rule["encoding"]
    # x must be a literal offset (not data-driven) so the rule spans full width.
    # The exact pixel value comes from chart padding; assert the structure.
    x_enc = enc.get("x")
    assert isinstance(x_enc, dict) and "value" in x_enc, (
        f"x must be a literal value offset; got {x_enc!r}"
    )
    assert enc.get("x2") == {"value": "width"}
    color = enc.get("color")
    assert isinstance(color, dict) and "value" in color


def test_zero_rule_layer_carries_single_row_data():
    """Rule layer must override parent data with a single synthetic row so VL
    emits the rule once, not once per parent data row.

    The synthetic row carries the measure field with a finite value because
    VL appends an ``isValid(datum[measure]) && isFinite(+datum[measure])``
    filter derived from the inherited shared encoding — an empty row gets
    filtered out and the rule never reaches the SVG. Test only the structural
    shape: a single-row override scoped to the rule layer.
    """
    spec = _spec("bar", _POSITIVE_DATA)
    rule = _zero_rule_layer(spec)
    assert rule is not None
    rule_data = rule.get("data")
    assert isinstance(rule_data, dict)
    values = rule_data.get("values")
    assert isinstance(values, list) and len(values) == 1, (
        f"rule layer must carry exactly one synthetic row to halt VL data "
        f"iteration; got values={values!r}"
    )


def test_zero_rule_renders_one_line_for_bar_chart():
    """End-to-end: a multi-row bar chart emits exactly one rule-mark line in
    the SVG, not one per parent data row. Without the per-layer single-row
    data override, vl-convert iterates the rule once per inherited parent row
    at identical pixel coords (3 rows → 3 stacked rule lines)."""
    import re

    import vl_convert as vlc

    spec = _spec("bar", _POSITIVE_DATA)
    svg = vlc.vegalite_to_svg(spec)
    rule_lines = re.findall(
        r'<line[^>]*aria-roledescription="rule mark"[^>]*>',
        svg,
    )
    assert len(rule_lines) == 1, (
        f"expected exactly one rule-mark line, got {len(rule_lines)}; "
        ">1 indicates rule layer is inheriting parent data instead of using "
        "the single-row override"
    )


def test_zero_rule_is_last_layer_for_bar():
    """Bar: zero rule must be the LAST layer so it renders on top of bar fills."""
    spec = _spec("bar", _POSITIVE_DATA)
    layers = spec.get("layer", [])
    assert layers
    rule = _zero_rule_layer(spec)
    assert layers[-1] is rule


def test_zero_rule_is_first_layer_for_line():
    """Line: zero rule must be the FIRST layer so strokes render above the baseline.

    The hover overlay (opacity=0) is always last for mouse-event capture.
    The zero rule renders behind strokes so lines cross y=0 without
    being interrupted by the baseline rule.
    """
    spec = _spec("line", _STRADDLE_ZERO_DATA)
    layers = spec.get("layer", [])
    assert layers
    rule = _zero_rule_layer(spec)
    assert layers[0] is rule, (
        f"Zero rule must be the first layer for line charts; "
        f"found at index {layers.index(rule)}"
    )


def test_zero_rule_is_below_area_stroke_layers():
    """Area: zero rule sits between fill layers and stroke (line) layers.

    Layer order: [area_fills..., zero_rule, area_strokes (line marks)..., hover_overlay].
    Fill and stroke are separate layers so the baseline rule appears above the
    fill but below the top-edge stroke — stroke > rule > fill.
    Uses straddling-zero data to guarantee the rule is emitted for area.
    """
    spec = _spec("area", _STRADDLE_ZERO_DATA, color="x")
    main = _main_pane(spec)
    layers = main.get("layer", [])
    rule = _zero_rule_layer(spec)
    assert rule is not None
    rule_idx = layers.index(rule)

    area_fills_before = [
        layer
        for layer in layers[:rule_idx]
        if isinstance(layer.get("mark"), dict) and layer["mark"].get("type") == "area"
    ]
    assert area_fills_before, "No area fill layers found before the zero rule"

    line_strokes_after = [
        layer
        for layer in layers[rule_idx + 1 :]
        if isinstance(layer.get("mark"), dict) and layer["mark"].get("type") == "line"
    ]
    assert line_strokes_after, (
        "No stroke (line) layers found after the zero rule; "
        "area stroke must render above the baseline"
    )

    assert layers[-1] is not rule, (
        "Hover overlay must be the last layer, not the zero rule"
    )


def test_zero_rule_uses_theme_zero_color_and_width():
    """Rule color/width come from the theme's axis_quantitative.grid.zero.*."""
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    resolved = resolve_chart_style_context(get_theme_style("clarity"))
    axis_y = resolved_axis_style(
        resolved, "axis_y", "quantitative", chart_type="", label_authored=False
    )
    assert axis_y.grid.zero is not None
    expected_color = axis_y.grid.zero.color
    expected_width = axis_y.grid.zero.width
    spec = _spec("bar", _POSITIVE_DATA)
    rule = _zero_rule_layer(spec)
    assert rule is not None
    mark = rule["mark"]
    assert mark["color"] == expected_color
    assert mark["strokeWidth"] == expected_width


# ── End-to-end: the rule actually renders as a horizontal line ────────────────


def test_bar_mark_uses_corner_radius_end_so_baseline_is_square():
    """Bars must round only the value-end corners so the bottom edge meets the
    zero rule cleanly. Using ``cornerRadius`` (all four corners) carves wedges
    out of the bottom corners that expose chart background through the rule."""
    spec = _spec("bar", _POSITIVE_DATA)
    layers = spec.get("layer") or [{"mark": spec.get("mark")}]
    bar_mark = next(
        layer["mark"]
        for layer in layers
        if isinstance(layer.get("mark"), dict) and layer["mark"].get("type") == "bar"
    )
    assert "cornerRadius" not in bar_mark
    assert bar_mark.get("cornerRadiusEnd") is not None


def test_bar_tick_values_start_at_zero_with_decimal_data():
    """Bar chart tickValues must start at 0 when data arrives as Decimal (Snowflake).

    Snowflake's dbt adapter returns numeric columns as decimal.Decimal, not
    float. classify_column_type previously classified Decimal as categorical,
    skipping zero inference and tick computation entirely — VL then produced
    dense unlabeled gridlines and omitted the 0 baseline tick.
    """
    from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

    data = [
        {"trade_date": f"2020-12-{10 + i:02d}", "volume_bn": Decimal(str(v))}
        for i, v in enumerate([21.23, 14.56, 13.89, 14.12, 16.45, 13.78, 18.23])
    ]
    style = BarChartStylePatch(
        axis_x=AxisXStylePatch.model_validate(
            {"labels": {"time_unit": "yearmonthdate"}}
        )
    )
    chart = BarChart(
        id="t",
        type="bar",
        x="trade_date",
        y="volume_bn",
        query_name="q",
        style=style,
    )
    _rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = generate_vega_lite_spec(chart, data, width=600)
    y_enc = spec.get("encoding", {}).get("y", {})
    tick_values = y_enc.get("axis", {}).get("values")
    assert tick_values is not None, (
        "no tickValues — Decimal data not profiled as numeric"
    )
    assert tick_values[0] == 0.0, (
        f"bar chart with Decimal data must start ticks at 0; got {tick_values}"
    )


def test_zero_rule_renders_as_one_visible_horizontal_line():
    """Render the spec via vl-convert and verify a single-position rule line.

    This catches the "vertical bars" regression: if the rule layer inherits
    parent data, vl-convert renders one rule per row × series, all at the
    same y but each carrying a per-row description signal. The single-row
    data override collapses to exactly one tagged ``<line>``.
    """
    import re

    import vl_convert as vlc

    spec = _spec("area", _STRADDLE_ZERO_DATA, color="x")
    svg = vlc.vegalite_to_svg(spec)
    rule_lines = re.findall(
        r'<line[^>]*aria-roledescription="rule mark"[^>]*>',
        svg,
    )
    assert len(rule_lines) == 1, (
        f"expected exactly one rule-mark line, got {len(rule_lines)}; "
        ">1 indicates rule layer is inheriting parent data instead of using "
        "the single-row override"
    )
    # Width-spanning: x2 must equal the chart's plot width (> 0)
    x2_match = re.search(r'x2="([0-9.]+)"', rule_lines[0])
    assert x2_match is not None, "rule line missing x2 attribute"
    assert float(x2_match.group(1)) > 0, "rule x2 must be > 0"


def test_zero_rule_fires_for_area_with_overlay() -> None:
    """Regression: area-base + line overlay must still emit the zero baseline rule.

    The zero-rule feature must not be silently skipped when layers are present.
    """
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "area",
            "x": "x",
            "y": "y",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [{"type": "line", "y": "y"}],
        }
    )
    spec = generate_vega_lite_spec(
        chart,
        _STRADDLE_ZERO_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _zero_rule_layer(spec) is not None, (
        "Zero baseline rule must be emitted for area+overlay when data straddles zero"
    )


def test_zero_rule_skipped_for_faceted_chart_under_independent_scale() -> None:
    """A `multiples: {scale: independent}` chart must skip the zero rule the
    same way independent dual-axis does: the rule's straddle-zero verdict is
    decided once from the pooled union of every panel's rows, but under
    independent scale each panel gets its own y-domain — a single chart-wide
    verdict can be wrong for any one panel, so it must not be drawn.
    """
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "x",
            "y": "y",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "multiples": {"rows": "panel", "scale": "independent"},
        }
    )
    rows = [
        {"x": "a", "y": 5, "panel": "P1"},
        {"x": "b", "y": -3, "panel": "P1"},
        {"x": "a", "y": 7, "panel": "P2"},
        {"x": "b", "y": 9, "panel": "P2"},
    ]
    spec = generate_vega_lite_spec(
        chart, rows, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    unit = spec["spec"]
    assert _zero_rule_layer(unit) is None


def test_bar_descending_domain_including_zero_appends_rule():
    """Reading the pair as min/max, not as an ordered low/high.

    A descending domain that spans zero still has a legal place for the rule.
    The bar branch previously tested `d[0] <= 0 <= d[-1]`, which reads False for
    any descending pair and suppressed the rule on an axis that has room for it.
    """
    style = BarChartStylePatch(
        axis_y=AxisYStylePatch(
            scale=BaseScaleStylePatch(
                continuous=ScaleContinuousStylePatch(domain=[100, -10])
            )
        )
    )

    assert _zero_rule_layer(_spec("bar", _POSITIVE_DATA, style=style)) is not None


# ── Dual-axis (independent y-scale) zero baselines ────────────────────────
#
# A dual-axis overlay resolves `resolve.scale.y: independent`, under which
# BaselineFeature bails out entirely (see its `apply()`). These rules are
# instead inserted by `render_cartesian_overlay` itself, nested one level
# inside the specific `vl_layers[i]` entry that owns the scale they bind to
# — never as a floating top-level sibling, which would get its own
# degenerate [0, 0] scale under VL's independent-scale resolution.


def _rule_fields_recursive(vl_layer: dict) -> set[str]:
    """Fields of every zero/x-zero-datum rule mark nested anywhere under
    ``vl_layer`` (its own single-row synthetic data key)."""
    fields: set[str] = set()
    mark = vl_layer.get("mark")
    mtype = mark.get("type") if isinstance(mark, dict) else mark
    if mtype == "rule":
        enc = vl_layer.get("encoding", {})
        if enc.get("y", {}).get("datum") == 0 or enc.get("x", {}).get("datum") == 0:
            data_values = vl_layer.get("data", {}).get("values") or []
            if data_values:
                fields.update(data_values[0].keys())
    for sub in vl_layer.get("layer", []) or []:
        fields |= _rule_fields_recursive(sub)
    return fields


def _nested_zero_rule_fields_by_index(spec: dict) -> dict[int, set[str]]:
    """Zero-rule fields nested one level inside each top-level dual-axis
    layer entry, keyed by that entry's own index (excludes a rule sitting
    directly at the top level, a floating, un-nested sibling).

    Keying by index, not just pooling every field into one flat set, catches
    a rule landing inside the WRONG entry (e.g. both the base's and a
    layer's own rule nested under the base) that a flattened union would
    hide.
    """
    result: dict[int, set[str]] = {}
    for i, top in enumerate(_main_pane(spec).get("layer", [])):
        fields: set[str] = set()
        for sub in top.get("layer", []) or []:
            fields |= _rule_fields_recursive(sub)
        if fields:
            result[i] = fields
    return result


def _dual_axis_bar_line_chart(layer_axis_y: dict) -> dict:
    return {
        "id": "t",
        "type": "bar",
        "x": "x",
        "y": "y",
        "query": SqlQuery(sql="SELECT 1", source="src"),
        "query_name": "q",
        "variable_dependencies": set(),
        "layers": [{"type": "line", "y": "y2", "axis_y": layer_axis_y}],
    }


def _dual_axis_line_base_chart(layer_axis_y: dict) -> dict:
    return {
        "id": "t",
        "type": "line",
        "x": "x",
        "y": "y",
        "query": SqlQuery(sql="SELECT 1", source="src"),
        "query_name": "q",
        "variable_dependencies": set(),
        "layers": [{"type": "bar", "y": "y2", "axis_y": layer_axis_y}],
    }


def _dual_axis_scatter_base_chart(layer_axis_y: dict) -> dict:
    return {
        "id": "t",
        "type": "scatter",
        "x": "x",
        "y": "y",
        "query": SqlQuery(sql="SELECT 1", source="src"),
        "query_name": "q",
        "variable_dependencies": set(),
        "layers": [{"type": "bar", "y": "y2", "axis_y": layer_axis_y}],
    }


_DUAL_AXIS_STRADDLE_DATA = [
    {"x": "a", "y": 5, "y2": 120},
    {"x": "b", "y": -3, "y2": -40},
    {"x": "c", "y": 8, "y2": 90},
]


def test_dual_axis_bar_base_and_line_layer_each_get_own_nested_zero_rule():
    """Bar base (straddles zero) + line layer pinned to the right axis (also
    straddles zero): each independently-scaled series gets its OWN zero rule,
    nested inside its own layer entry — not a shared/floating top-level rule.
    """
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_bar_line_chart({"position": "right"})
    )
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _main_pane(spec).get("resolve", {}).get("scale", {}).get("y") == (
        "independent"
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_overlay_layer_far_from_zero_gets_no_rule():
    """The overlay's own values never approach zero: only the base's rule
    fires. The per-layer straddle-check is real, not an unconditional
    "always fire once independent"."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_bar_line_chart({"position": "right"})
    )
    data = [
        {"x": "a", "y": 5, "y2": 1000},
        {"x": "b", "y": -3, "y2": 1500},
        {"x": "c", "y": 8, "y2": 2000},
    ]
    spec = generate_vega_lite_spec(
        chart, data, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}}


def test_dual_axis_overlay_authored_domain_excluding_zero_suppresses_its_rule():
    """An authored `axis_y.scale.domain` excluding 0 suppresses the overlay's
    own rule even though its data straddles zero; the base's rule is
    unaffected."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_bar_line_chart(
            {"position": "right", "scale": {"domain": [1000, 5000]}}
        )
    )
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}}


def test_dual_axis_overlay_empty_domain_list_does_not_crash():
    """`LayerAxisYScale.domain` has no length constraint: `domain: []` is
    schema-valid, and carries no bounds. Reading it as `(min, max)` must not
    crash; it must fall back to the straddle check, same as unset."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_bar_line_chart({"position": "right", "scale": {"domain": []}})
    )
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_layer_sharing_base_side_keeps_single_shared_rule():
    """A layer with no `axis_y.position` shares the base's own scale (no
    other layer forces a split, so `independent_y` stays False): the
    single shared-scale rule behavior of a non-dual-axis chart."""
    chart = TypeAdapter(Chart).validate_python(_dual_axis_bar_line_chart({}))
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    main = _main_pane(spec)
    assert main.get("resolve", {}).get("scale", {}).get("y") != "independent"
    assert _zero_rule_layer(spec) is not None


_LINE_BASE_CLOSE_TO_ZERO_NO_STRADDLE_DATA = [
    {"x": "a", "y": 4, "y2": 5},
    {"x": "b", "y": 8, "y2": -3},
    {"x": "c", "y": 20, "y2": 8},
]


def test_dual_axis_line_base_fires_zero_rule_even_without_straddle():
    """A line base's own dual-axis zero rule must match `non_bar_zero_rule_
    should_fire`'s real verdict (fires unless `scale.continuous.zero` is
    explicitly False) -- a plain straddle check would silently suppress the
    base's rule whenever its values happened not to straddle zero, even
    though `scale.continuous.zero` was never turned off."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_line_base_chart({"position": "right"})
    )
    spec = generate_vega_lite_spec(
        chart,
        _LINE_BASE_CLOSE_TO_ZERO_NO_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_base_grid_not_visible_skips_its_rule():
    """`axis_y.grid.visible: false` on a dual-axis base must still suppress
    its own rule; a layer authoring its own `grid.visible: true` keeps its
    rule regardless of the base's setting. See
    `test_dual_axis_layer_inherits_base_grid_not_visible_when_unauthored`
    for the fallback an unauthored layer takes instead."""
    chart_dict = _dual_axis_bar_line_chart(
        {"position": "right", "grid": {"visible": True}}
    )
    chart_dict["style"] = {"axis_y": {"grid": {"visible": False}}}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {1: {"y2"}}


def test_dual_axis_layer_inherits_base_grid_not_visible_when_unauthored():
    """A layer with no `axis_y.grid` of its own inherits the base's
    `grid.visible` as a fallback (a separate, pre-existing cascade -- see
    `_overlay.py`'s `layer_grid_visible` computation) -- so a base with
    `grid.visible: false` and an unauthored layer suppresses BOTH rules,
    not just the base's own."""
    chart_dict = _dual_axis_bar_line_chart({"position": "right"})
    chart_dict["style"] = {"axis_y": {"grid": {"visible": False}}}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {}


_DUAL_AXIS_LOG_BASE_DATA = [
    {"x": "a", "y": 5, "y2": 40},
    {"x": "b", "y": 50, "y2": -10},
    {"x": "c", "y": 500, "y2": 20},
]


def test_dual_axis_base_log_scale_skips_its_rule():
    """A log-typed base measure axis can never carry the datum:0 rule (a
    literal 0 breaks a log domain); the overlay's own rule is unaffected."""
    chart_dict = _dual_axis_line_base_chart({"position": "right"})
    chart_dict["style"] = {"axis_y": {"scale": {"continuous": {"type": "log"}}}}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_LOG_BASE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {1: {"y2"}}


def test_dual_axis_scatter_base_gets_its_own_zero_rule():
    """BaselineFeature covers scatter charts; a scatter base under a dual-axis
    scale must too, not be silently excluded from the family gate."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_scatter_base_chart({"position": "right"})
    )
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_scatter_layer_on_bar_base_gets_its_own_zero_rule():
    """A scatter overlay layer on a bar base is a real, working dual-axis
    case: the per-layer gate reads the LAYER's own family, not the base's."""
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "x",
            "y": "y",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [{"type": "scatter", "y": "y2", "axis_y": {"position": "right"}}],
        }
    )
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


_DUAL_AXIS_MULTIPLES_DATA = [
    {"x": "a", "region": "West", "y": 100, "y2": 50},
    {"x": "b", "region": "West", "y": 200, "y2": 80},
    {"x": "a", "region": "East", "y": -30, "y2": -10},
    {"x": "b", "region": "East", "y": 50, "y2": 20},
]


def _any_zero_rule_anywhere(node: object) -> bool:
    """True if a `datum: 0` rule mark sits anywhere in ``node``'s tree."""
    if isinstance(node, dict):
        mark = node.get("mark")
        mtype = mark.get("type") if isinstance(mark, dict) else mark
        if mtype == "rule":
            enc = node.get("encoding", {})
            if enc.get("y", {}).get("datum") == 0 or enc.get("x", {}).get("datum") == 0:
                return True
        return any(_any_zero_rule_anywhere(v) for v in node.values())
    if isinstance(node, list):
        return any(_any_zero_rule_anywhere(v) for v in node)
    return False


def test_dual_axis_independent_multiples_skips_all_zero_rules():
    """`multiples: {scale: independent}` mirrors BaselineFeature's own
    per-panel guard: a single chart-wide zero-rule verdict can be wrong for
    any one panel (West here never crosses zero; East does), so dual-axis
    rule insertion must skip entirely, not just leave the shared-scale path
    (which already bails in BaselineFeature) unrouted."""
    chart_dict = _dual_axis_bar_line_chart({"position": "right"})
    chart_dict["multiples"] = {"rows": "region", "scale": "independent"}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_MULTIPLES_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert not _any_zero_rule_anywhere(spec)


_STREAMGRAPH_DUAL_AXIS_DATA = [
    {"x": "a", "series": "s1", "y": 5, "y2": 40},
    {"x": "a", "series": "s2", "y": 8, "y2": -10},
    {"x": "b", "series": "s1", "y": 3, "y2": 20},
    {"x": "b", "series": "s2", "y": 6, "y2": -5},
]


def test_dual_axis_streamgraph_base_draws_no_zero_rule():
    """A streamgraph base (area, `stack: center`) must draw no zero rule at
    all under dual axis, mirroring `BaselineFeature._apply_zero_or_top`'s
    own carve-out: y=0 is only the silhouette's visual centerline there, not
    a meaningful baseline. The overlay's own rule is unaffected."""
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "area",
            "x": "x",
            "y": "y",
            "color": "series",
            "stack": "center",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [{"type": "bar", "y": "y2", "axis_y": {"position": "right"}}],
        }
    )
    spec = generate_vega_lite_spec(
        chart,
        _STREAMGRAPH_DUAL_AXIS_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {1: {"y2"}}


def test_dual_axis_empty_data_draws_no_zero_rule():
    """An empty dataset must draw no base zero rule, mirroring
    `BaselineFeature._apply_zero_or_top`'s own
    `chart_rows(...).all_rows()` guard. The overlay layer here is a line, whose
    own straddle check happens to return False on empty rows -- see
    `test_dual_axis_empty_data_layer_draws_no_zero_rule` for the bar/area arm,
    which always-fires and so needs its own explicit empty-rows guard."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_bar_line_chart({"position": "right"})
    )
    spec = generate_vega_lite_spec(
        chart, [], width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert not _any_zero_rule_anywhere(spec)


@pytest.mark.parametrize("layer_type", ["bar", "line", "area"])
def test_dual_axis_empty_data_layer_draws_no_zero_rule(layer_type: str):
    """A bar/area overlay layer's own should-fire verdict short-circuits on
    `layer.type in ("bar", "area")` before ever consulting its rows -- an
    empty-rows layer of either type must still be excluded, not merely
    excluded by accident the way a line layer's straddle check is."""
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "x",
            "y": "y",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [
                {"type": layer_type, "y": "y2", "axis_y": {"position": "right"}}
            ],
        }
    )
    spec = generate_vega_lite_spec(
        chart, [], width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert not _any_zero_rule_anywhere(spec)


def test_dual_axis_area_layer_non_straddling_still_gets_zero_rule():
    """The layer's own always-fire arm (`layer.type in ("bar", "area")`)
    covers area too, not just bar -- an area OVERLAY layer whose own values
    never approach zero must still get its own rule."""
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "x",
            "y": "y",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [{"type": "area", "y": "y2", "axis_y": {"position": "right"}}],
        }
    )
    data = [
        {"x": "a", "y": 5, "y2": 1000},
        {"x": "b", "y": -3, "y2": 1500},
        {"x": "c", "y": 8, "y2": 2000},
    ]
    spec = generate_vega_lite_spec(
        chart, data, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def _dual_axis_area_base_chart(layer_axis_y: dict) -> dict:
    return {
        "id": "t",
        "type": "area",
        "x": "x",
        "y": "y",
        "query": SqlQuery(sql="SELECT 1", source="src"),
        "query_name": "q",
        "variable_dependencies": set(),
        "layers": [{"type": "bar", "y": "y2", "axis_y": layer_axis_y}],
    }


def test_dual_axis_area_base_fires_zero_rule_even_without_straddle():
    """An area base is a real member of the family this rule covers: it
    fires by default (mirrors `non_bar_zero_rule_should_fire`'s unconditional
    line/area verdict), even when its own values never straddle zero."""
    chart = TypeAdapter(Chart).validate_python(
        _dual_axis_area_base_chart({"position": "right"})
    )
    data = [
        {"x": "a", "y": 1000, "y2": 5},
        {"x": "b", "y": 1500, "y2": -3},
        {"x": "c", "y": 2000, "y2": 8},
    ]
    spec = generate_vega_lite_spec(
        chart, data, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_same_side_layer_gets_no_rule_of_its_own():
    """`layer_orients[layer_idx] != base_side` gates the per-layer rule: a
    second layer with no authored `axis_y.position` resolves to the base's
    own (left) side and must contribute NO rule of its own, even though its
    own family (bar) would otherwise always-fire -- it relies entirely on
    the base's own injected rule."""
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "bar",
            "x": "x",
            "y": "y",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [
                {"type": "line", "y": "y2", "axis_y": {"position": "right"}},
                {"type": "bar", "y": "y3", "axis_y": {}},
            ],
        }
    )
    data = [
        {"x": "a", "y": 5, "y2": 120, "y3": 9},
        {"x": "b", "y": -3, "y2": -40, "y3": 4},
        {"x": "c", "y": 8, "y2": 90, "y3": 12},
    ]
    spec = generate_vega_lite_spec(
        chart, data, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_rotated_dot_plot_scatter_base_draws_no_base_zero_rule():
    """The base gate must mirror `_y_carries_the_measure` (baseline.py): a
    dot-plot-rotated scatter base (value on x, category on y) has no
    quantitative y for a `datum: 0` rule to bind to. Regression path: a
    CSV-string-numeric category column ("5", "-3", "8") classifies as
    nominal (`is_quantitative=False`, since the raw values are `str`) but
    still parses as numeric under `values_straddle_zero`'s float coercion --
    without the `is_quantitative` gate, the straddle check alone fires and
    nests a quantitative `datum: 0` rule inside the base's nominal-y entry,
    which Vega-Lite cannot render against a categorical scale."""
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": "scatter",
            "x": "value",
            "y": "region",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "variable_dependencies": set(),
            "layers": [{"type": "bar", "y": "y2", "axis_y": {"position": "right"}}],
        }
    )
    data = [
        {"region": "5", "value": "cat_a", "y2": 40},
        {"region": "-3", "value": "cat_b", "y2": -10},
        {"region": "8", "value": "cat_c", "y2": 20},
    ]
    spec = generate_vega_lite_spec(
        chart, data, width=400, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    assert _nested_zero_rule_fields_by_index(spec) == {1: {"y2"}}


_HEADROOM_PIN_DUAL_AXIS_DATA = [
    {"x": "a", "y": 5000, "y2": 100000},
    {"x": "b", "y": 12000, "y2": 150000},
    {"x": "c", "y": 8000, "y2": 200000},
]


def _dual_axis_base_y_scale(base_grid_visible: bool) -> dict:
    """The base's own emitted y-scale VL dict, with its rule nested (grid
    visible, the normal case) or suppressed (grid hidden, mirroring an
    un-nested single-mark scale -- see
    `test_dual_axis_base_grid_not_visible_skips_its_rule`)."""
    chart_dict = _dual_axis_bar_line_chart({"position": "right"})
    if not base_grid_visible:
        chart_dict["style"] = {"axis_y": {"grid": {"visible": False}}}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _HEADROOM_PIN_DUAL_AXIS_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    base_top = _main_pane(spec)["layer"][0]
    base_entry = base_top["layer"][0] if base_grid_visible else base_top
    scale = base_entry["encoding"]["y"]["scale"]
    assert isinstance(scale, dict)
    return scale


def test_dual_axis_nested_base_zero_rule_pins_nice_false_to_keep_headroom_exact():
    """`apply_domain_headroom_bounds` documents its bound as "exact, never
    nice-rounded". Nesting the base's own zero rule (`nest_zero_rule`) puts
    it in a composite Vega-Lite shares a scale across -- and a shared scale's
    compiled Vega default for `nice` is `true` (unset/effectively-false for a
    lone mark), which then rounds the domain PAST an explicit `domainMax`
    headroom pin at render time (confirmed via `vl_convert.vegalite_to_vega`:
    a nested scale with no `nice` pin compiles to `domainMax: 12960, nice:
    true`, rendering past the pin). The un-nested (rule suppressed) and
    nested cases must agree on every bound except `nice` itself, which the
    nested case must pin `False` explicitly."""
    un_nested = _dual_axis_base_y_scale(base_grid_visible=False)
    nested = _dual_axis_base_y_scale(base_grid_visible=True)
    assert un_nested.get("nice") is None
    assert nested.get("nice") is False
    for key in ("domainMax", "domainMin", "zero"):
        assert un_nested.get(key) == nested.get(key), (key, un_nested, nested)


def test_dual_axis_nested_base_zero_rule_compiled_scale_stays_unrounded():
    """End-to-end proof (not just the VL-JSON pin above): the COMPILED Vega
    scale's `nice` flag for the nested case must be `False`, not the
    un-nested case's `None`/absent -- `domainMax` alone doesn't prove this,
    since Vega's compiler carries the authored `domainMax` through
    unchanged either way and only applies `nice` rounding when it lays out
    the axis ticks at render time (confirmed by inspecting `vl_convert`'s
    own compiled output: the nested case's `domainMax` key is identical
    with and without the `nice: false` pin -- only `nice` itself differs)."""
    import vl_convert as vlc

    def _compiled_base_scale(base_grid_visible: bool) -> dict:
        chart_dict = _dual_axis_bar_line_chart({"position": "right"})
        if not base_grid_visible:
            chart_dict["style"] = {"axis_y": {"grid": {"visible": False}}}
        chart = TypeAdapter(Chart).validate_python(chart_dict)
        spec = generate_vega_lite_spec(
            chart,
            _HEADROOM_PIN_DUAL_AXIS_DATA,
            width=400,
            board_style=_BOARD_STYLE,
            chart_style_context=_BOARD_CTX,
        )
        vega = vlc.vegalite_to_vega(spec)
        # Matched by the stacked-bar domain's own field names (Vega-Lite's
        # documented "<field>_start"/"<field>_end" stack-transform naming),
        # not the compiler's internal scale name -- more stable across
        # vl_convert versions than "layer_0_y".
        (base_scale,) = (
            s for s in vega["scales"] if "y_start" in json.dumps(s.get("domain"))
        )
        return base_scale

    un_nested = _compiled_base_scale(False)
    nested = _compiled_base_scale(True)
    assert un_nested.get("nice") in (None, False)
    assert nested.get("nice") is False
    assert un_nested["domainMax"] == nested["domainMax"]


def test_dual_axis_base_authored_domain_excluding_zero_suppresses_its_rule():
    """`_check_layers_y_domain` only rejects a chart-level authored
    `axis_y.scale.domain` when a layer pins `right`; when every layer pins
    `left` instead, the base gets pushed to `right` (`base_side`) and the
    authored domain survives compile intact -- so the base's own
    authored-domain-excludes-zero guard is a real, reachable path here, not
    dead code inherited from the shared-scale case."""
    chart_dict = _dual_axis_bar_line_chart({"position": "left"})
    chart_dict["style"] = {
        "axis_y": {"scale": {"continuous": {"domain": [1000, 5000]}}}
    }
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {1: {"y2"}}


def test_dual_axis_base_authored_domain_including_zero_still_fires():
    """Control for the test above: an authored domain that DOES include 0
    must not accidentally suppress the base's rule -- only a domain that
    excludes 0 is a legal reason to skip it."""
    chart_dict = _dual_axis_bar_line_chart({"position": "left"})
    chart_dict["style"] = {"axis_y": {"scale": {"continuous": {"domain": [-10, 5000]}}}}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _DUAL_AXIS_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {0: {"y"}, 1: {"y2"}}


def test_dual_axis_base_scale_zero_false_without_straddle_suppresses_its_rule():
    """The base's `zero_setting is False` arm of `non_bar_zero_rule_should_
    fire` is reachable on the dual-axis path too (`BaselineFeature`'s own
    tests cannot cover it -- `apply()` bails before reaching it once the
    scale resolves independent): an explicit `scale.continuous.zero: false`
    on a base whose own values never straddle zero must suppress the base's
    rule, not fall back to the "fires unless explicitly off" default."""
    chart_dict = _dual_axis_line_base_chart({"position": "right"})
    chart_dict["style"] = {"axis_y": {"scale": {"continuous": {"zero": False}}}}
    chart = TypeAdapter(Chart).validate_python(chart_dict)
    spec = generate_vega_lite_spec(
        chart,
        _LINE_BASE_CLOSE_TO_ZERO_NO_STRADDLE_DATA,
        width=400,
        board_style=_BOARD_STYLE,
        chart_style_context=_BOARD_CTX,
    )
    assert _nested_zero_rule_fields_by_index(spec) == {1: {"y2"}}
