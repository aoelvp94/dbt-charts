"""Zero-baseline rule mark for bar / area / line charts.

Vega renders axis guides (grid lines) BELOW marks, so area/bar fills cover the
bold zero baseline produced by the conditional ``gridColor`` encoding. A rule
mark layer at the top of the layer stack renders above all fills and restores
the baseline.

Constraints:
- Scope: bar (vertical and horizontal), area, and line. Scatter and other
  chart families don't emit the rule.
- Only emit when 0 is in the measure-axis domain (no rule for line charts
  whose y-domain is e.g. [75000, 183000], or for charts with explicit
  ``scale.domain`` excluding 0).
- Encoding explicitly overrides shared x/x2/color so the rule renders as one
  full-width horizontal line, not a per-series fragment.
- The rule layer ships its own single-row data so VL emits the rule once
  rather than iterating it per parent data row at identical pixel coords.
"""

from __future__ import annotations

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
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())


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
# CSV adapters return numeric columns as strings; VL coerces via encoding.type.
# The rule emit must not skip such data (regression: previously dropped because
# _domain_includes_zero scanned only Python-native ints/floats).
_POSITIVE_DATA_CSV_STRINGS = [
    {"x": "a", "y": "5"},
    {"x": "b", "y": "10"},
    {"x": "c", "y": "7"},
]
# Same CSV-string regression, but for area (an optional-zero chart type): the
# smart-zero heuristic now genuinely runs on string-coerced data (previously it
# silently saw an empty extent and always fired the rule) — ratio must stay
# <= 0.25 for the rule to fire, mirroring test_area_starting_near_zero_appends_rule.
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


def test_area_clustered_above_threshold_skips_rule():
    """Area chart with clustered values (ratio > 0.25) → zero not in domain → no rule.

    Smart-auto heuristic sets scale.zero=False so VL fits the domain to data.
    With all-positive data and zero excluded, the zero rule is not emitted.
    This prevents the near-solid-fill visual artifact for e.g. CSAT scores (88-96).
    """
    # ratio ≈ 0.92 > 0.25 → smart-auto sets zero:False → 0 outside domain
    data_clustered = [
        {"x": "Jan", "y": 88},
        {"x": "Feb", "y": 91},
        {"x": "Mar", "y": 96},
    ]
    spec = _spec("area", data_clustered)
    assert _zero_rule_layer(spec) is None


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
    """Same regression for area charts: the smart-zero heuristic must parse
    string-typed measures just like real floats. Area is optional-zero, so
    (unlike bar) this only fires when the ratio is close enough to zero."""
    spec = _spec("area", _NEAR_ZERO_DATA_CSV_STRINGS)
    assert _zero_rule_layer(spec) is not None


def test_area_with_csv_string_values_far_from_zero_skips_rule():
    """Regression for the fix itself: before it, string-typed measures were
    invisible to the smart-zero heuristic, so the rule fired unconditionally
    regardless of ratio. Now a far-from-zero ratio suppresses it, exactly as
    it does for the equivalent float data (test_area_clustered_above_threshold_skips_rule).
    """
    spec = _spec("area", _POSITIVE_DATA_CSV_STRINGS)
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


def test_scatter_chart_skips_rule():
    """Scatter charts don't get the rule."""
    spec = _spec("scatter", _POSITIVE_DATA)
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

    resolved = resolve_chart_style_context(get_theme_style("editorial"))
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
