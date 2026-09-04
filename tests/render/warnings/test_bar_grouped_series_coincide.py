"""Tests for the BAR_GROUPED_SERIES_COINCIDE render-warning detector.

Detection rule: fires on a vertical color-grouped bar (color + stack: none)
whose x is emitted as a continuous VL type (quantitative, or a temporal
channel with no timeUnit) — Vega-Lite's xOffset sub-scale has no band to
divide series within there, so every series paints at the identical position,
each one occluding the series drawn before it.

Horizontal bars are out of scope by construction: `_emit_horizontal` types its
categorical channel "nominal" at its only construction site, so the defect
cannot arise there.

The `_emitted_ctx` tests at the bottom run real specs through the emitter. They
are the ones that pin layer-walking: every real bar spec — flat or layered —
wraps its mark in a `layer` array, so a detector reading only the top-level
encoding fires on none of them.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import BarChart, LineChart
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.diagnostics import WARN_BAR_GROUPED_SERIES_COINCIDE, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    bar_grouped_series_coincide as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _numeric_rows(n_x: int, n_series: int) -> list[dict[str, Any]]:
    return [
        {"x_num": x, "series": f"s{s}", "val": x + s}
        for x in range(n_x)
        for s in range(n_series)
    ]


def _ctx(
    chart: Any,
    rows: list[dict[str, Any]],
    cat_type: str = "quantitative",
    offset_field: str | None = "series",
) -> WarningContext:
    """Build a ctx whose vega_specs mirrors what the bar emitter actually
    emits for a flat color-grouped bar: x's own VL type, plus an xOffset
    channel present whenever the band is genuinely subdivided.
    """
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    encoding: dict[str, Any] = {"x": {"type": cat_type}}
    if offset_field is not None:
        encoding["xOffset"] = {"field": offset_field, "type": "nominal"}
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"mark": {"type": "bar"}, "encoding": encoding}},
    )


def test_fires_on_quantitative_x_grouped_bar() -> None:
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="x_num",
        y="val",
        color="series",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _numeric_rows(n_x=12, n_series=5)
    warnings = detector.detect(_ctx(chart, rows))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_BAR_GROUPED_SERIES_COINCIDE.code
    assert w.field == "x_num"
    assert w.path == "charts.c1.x"


def test_no_fire_on_categorical_x_grouped_bar() -> None:
    """The classic grouped-bar shape (nominal x) must not fire — VL genuinely
    offsets bars apart there."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        color="series",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = [
        {"month": f"m{x}", "series": f"s{s}", "val": x + s}
        for x in range(3)
        for s in range(2)
    ]
    assert detector.detect(_ctx(chart, rows, cat_type="nominal")) == []


def test_no_fire_on_bucketed_temporal_x() -> None:
    """A timeUnit-bucketed temporal x still has a real band scale."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="week",
        y="val",
        color="series",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _numeric_rows(n_x=12, n_series=5)
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={
            resolved.id: {
                "encoding": {
                    "x": {"type": "temporal", "timeUnit": "yearweek"},
                    "xOffset": {"field": "series", "type": "nominal"},
                },
                "mark": {"type": "bar"},
            }
        },
    )
    assert detector.detect(ctx) == []


def test_no_fire_without_offset_channel() -> None:
    """No xOffset (single series, or color 1:1 with x) — nothing to coincide."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="x_num",
        y="val",
        color="series",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _numeric_rows(n_x=12, n_series=5)
    assert detector.detect(_ctx(chart, rows, offset_field=None)) == []


def test_no_fire_on_stacked_bar() -> None:
    """Stacked bars never emit xOffset — the emitter's own stacking IS the
    disambiguation mechanism, no coincidence to warn about."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="x_num",
        y="val",
        color="series",
        stack="normalize",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _numeric_rows(n_x=12, n_series=5)
    assert detector.detect(_ctx(chart, rows, offset_field=None)) == []


def test_no_fire_on_non_bar_chart() -> None:
    chart = LineChart(id="c1", type="line", query_name="q", x="x_num", y="val")
    rows = _numeric_rows(n_x=12, n_series=5)
    assert detector.detect(_ctx(chart, rows)) == []


def test_no_fire_without_x() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", y="val")
    assert detector.detect(_ctx(chart, [{"val": 1}])) == []


def test_no_fire_when_chart_not_in_vega_specs() -> None:
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="x_num",
        y="val",
        color="series",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _numeric_rows(n_x=12, n_series=5)
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board, chart_results={resolved.id: rows}, vega_specs={}
    )
    assert detector.detect(ctx) == []


def _emitted_ctx(chart: Any, rows: list[dict[str, Any]]) -> WarningContext:
    """Build a ctx from a REALLY EMITTED spec, not a hand-built encoding dict.

    The hand-built specs above pin the detector's rule; this pins that the rule
    matches what the emitter actually produces. A layered grouped bar hoists
    only `x` to the root and leaves `xOffset` down on the bar layer, so a
    detector reading the top-level encoding alone sees nothing here.
    """
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve import resolve
    from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
    from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

    _, board_style = resolve_style_and_context(get_theme_style())
    resolve(chart, rows, chart_style_context=board_style)
    spec = generate_vega_lite_spec(chart, rows)
    resolved = make_test_resolved_chart(chart, rows)
    return WarningContext(
        board_spec=make_test_resolved_board(charts={resolved.id: resolved}),
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: spec},
    )


def _numeric_bar(**kwargs: Any) -> BarChart:
    from dbt_charts.core.compile.models.query.normalized import SqlQuery

    return BarChart(
        id="c1",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="x_num",
        y="val",
        color="series",
        stack=None,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
        **kwargs,
    )


def test_fires_on_an_emitted_flat_grouped_bar() -> None:
    rows = _numeric_rows(n_x=12, n_series=5)
    warnings = detector.detect(_emitted_ctx(_numeric_bar(), rows))
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_GROUPED_SERIES_COINCIDE.code


def test_fires_on_an_emitted_layered_grouped_bar() -> None:
    """The shape that occludes most visibly: full-width bars stacked on one
    pixel column with a line overlay, which reads as a legitimate
    single-series chart rather than an obviously broken one."""
    from dbt_charts.core.compile.models.chart.authored._layer import LineLayer

    rows = _numeric_rows(n_x=12, n_series=5)
    chart = _numeric_bar(layers=[LineLayer(type="line", y="val")])
    ctx = _emitted_ctx(chart, rows)

    # Guard the premise: xOffset really is absent from the top level here, so
    # this test would pass vacuously if the emitter ever stopped hoisting.
    assert "xOffset" not in ctx.vega_specs["c1"].get("encoding", {}), (
        "layered spec unexpectedly carries xOffset at the top level — this "
        "test no longer covers the layer-walking path"
    )

    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_GROUPED_SERIES_COINCIDE.code
    assert warnings[0].field == "x_num"


def test_no_fire_on_an_emitted_layered_categorical_grouped_bar() -> None:
    """Same layered shape on a nominal x — VL genuinely offsets bars there."""
    from dbt_charts.core.compile.models.chart.authored._layer import LineLayer
    from dbt_charts.core.compile.models.query.normalized import SqlQuery

    rows = [
        {"month": f"m{x}", "series": f"s{s}", "val": x + s}
        for x in range(6)
        for s in range(3)
    ]
    chart = BarChart(
        id="c1",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="month",
        y="val",
        color="series",
        stack=None,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
        layers=[LineLayer(type="line", y="val")],
    )
    assert detector.detect(_emitted_ctx(chart, rows)) == []


def test_fires_on_an_emitted_endpoint_label_concat_grouped_bar() -> None:
    """The shape that misleads most: an endpoint-label rail names all five
    series while only the last-drawn one is actually visible.

    `_wrap_endpoint_labels` (render/chart/translate.py) wraps the whole spec in
    an `hconcat` before it is stored, so the bar layer sits two containers deep.
    `resolve/chart/bar.py` turns the rail off by default for `stack: none`, but
    an explicit `endpoint_labels.visible: true` preserves it — a documented
    authoring surface.
    """
    from dbt_charts.core.compile.models.query.normalized import SqlQuery

    rows = _numeric_rows(n_x=6, n_series=5)
    chart = BarChart(
        id="c1",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="x_num",
        y="val",
        color="series",
        stack=None,
        style=BarChartStylePatch.model_validate(
            {"orientation": "vertical", "endpoint_labels": {"visible": True}}
        ),
    )
    ctx = _emitted_ctx(chart, rows)

    # Guard the premise: the root really is concat-wrapped, so this test would
    # pass vacuously if the rail ever stopped firing for this shape.
    spec = ctx.vega_specs["c1"]
    assert "hconcat" in spec or "vconcat" in spec, (
        f"expected a concat-wrapped root, got keys {sorted(spec)} — this test "
        "no longer covers the concat-walking path"
    )
    assert "encoding" not in spec, "a concat root must carry no shared encoding"

    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_GROUPED_SERIES_COINCIDE.code
    assert warnings[0].field == "x_num"
