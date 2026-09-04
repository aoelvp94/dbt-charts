"""A sparse series paints a band in a stacked area chart.

An area mark sweeps *between* vertices, so a series contributing a single point has
no segment and paints nothing, while the stack still reserves its height — a
wedge-shaped hole, and a series named in the rail with nothing to read it against.

A stacked area therefore asks Vega-Lite to fill every missing (x, series) pair with
zero, giving the band vertices to return to. Rows whose measure is null are dropped
first, so an explicit NULL and an absent row reach the same wedge. Both steps sit on
the fill/edge marks only: the per-datum hover overlay must not gain tooltip targets
at columns the series never reported.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE = resolve_style(get_theme_style())
_CHART_STYLE_CONTEXT = resolve_chart_style_context(get_theme_style())

# "Costs" reports only in February — the degenerate case.
_SPARSE = [
    {"date": "2024-01-01", "value": 100, "series": "Revenue"},
    {"date": "2024-02-01", "value": 120, "series": "Revenue"},
    {"date": "2024-03-01", "value": 110, "series": "Revenue"},
    {"date": "2024-02-01", "value": 90, "series": "Costs"},
]

_DENSE = [
    {"date": "2024-01-01", "value": 100, "series": "Revenue"},
    {"date": "2024-02-01", "value": 120, "series": "Revenue"},
    {"date": "2024-01-01", "value": 80, "series": "Costs"},
    {"date": "2024-02-01", "value": 90, "series": "Costs"},
]


def _render(make_chart, data, stack: str | None):
    chart = make_chart("area", x="date", y="value", color="series", stack=stack)
    resolved = resolve(chart, data, chart_style_context=_CHART_STYLE_CONTEXT)
    artifact = render_resolved_chart(resolved, data, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    return spec["hconcat"][0] if "hconcat" in spec else spec


def _area_layer(spec: dict[str, Any]) -> dict[str, Any]:
    for layer in spec.get("layer", []):
        if layer.get("mark", {}).get("type") == "area":
            return layer
    raise AssertionError("no area layer in spec")


def _impute(layer: dict[str, Any]) -> dict[str, Any] | None:
    for step in layer.get("transform", []):
        if "impute" in step:
            return step
    return None


def test_stacked_area_imputes_missing_rows_to_zero(make_chart):
    """The area layer carries an impute keyed on x and grouped by the series field."""
    spec = _render(make_chart, _SPARSE, stack="zero")
    step = _impute(_area_layer(spec))
    assert step is not None, "stacked area emits no impute — a sparse band cannot draw"
    assert step["impute"] == "value"
    assert step["key"] == "date"
    assert step["value"] == 0


def test_impute_groups_by_series_and_stack_order(make_chart):
    """groupby must retain both fields that identify a stacked band.

    Vega-Lite folds every encoded nominal channel into a line/area impute's
    groupby. A per-row-distinct channel there explodes it to one group per row and
    fragments the path (see ``translate.py::_apply_structured_tooltip``), so the
    groupby is stated explicitly rather than inferred.
    """
    spec = _render(make_chart, _SPARSE, stack="zero")
    step = _impute(_area_layer(spec))
    assert step is not None
    assert step["groupby"] == ["series", "__df_series_order"]


def test_null_measures_are_dropped_before_imputing(make_chart):
    """An explicit NULL must reach the same wedge as an absent row.

    ``impute`` fills only *missing* key/group pairs, so a row that exists with a
    null measure would survive untouched and the band would still not draw. The
    filter ahead of it makes both inputs the same shape.
    """
    spec = _render(make_chart, _SPARSE, stack="zero")
    transform = _area_layer(spec).get("transform", [])
    kinds = [next(iter(step)) for step in transform]
    assert "filter" in kinds, "no null filter ahead of the impute"
    assert kinds.index("filter") < kinds.index("impute")


def test_hover_overlay_does_not_impute(make_chart):
    """Imputed rows are synthetic — they must not become hover targets.

    The per-datum point layer tracks the cursor for tooltips. If it saw imputed
    rows, a sparse series would offer zero-value tooltips at every column it never
    reported.
    """
    spec = _render(make_chart, _SPARSE, stack="zero")
    for layer in spec.get("layer", []):
        if layer.get("mark", {}).get("type") == "point":
            assert _impute(layer) is None


def test_streamgraph_and_normalize_impute_too(make_chart):
    """Every stacked mode has the same degenerate-band problem."""
    for stack in ("center", "normalize"):
        spec = _render(make_chart, _SPARSE, stack=stack)
        assert _impute(_area_layer(spec)) is not None, f"stack={stack} has no impute"


def test_overlap_area_does_not_impute(make_chart):
    """Unstacked area is left alone — the stacked argument does not reach it.

    A stack is a sum, so it already places every band above a missing series as
    though that series contributed zero; painting the zero only makes an existing
    commitment visible. An overlap chart sums nothing, so forcing a missing point
    to zero is a new claim, and it turns a series sampled at irregular intervals
    into a sawtooth.
    """
    spec = _render(make_chart, _SPARSE, stack=None)
    for layer in spec.get("layer", []):
        assert _impute(layer) is None


def test_dense_data_is_unaffected(make_chart):
    """The impute is a no-op when nothing is missing, but is still emitted.

    Emitting it unconditionally keeps the spec shape stable; Vega-Lite fills no
    rows when every (x, series) pair is already present.
    """
    spec = _render(make_chart, _DENSE, stack="zero")
    assert _impute(_area_layer(spec)) is not None


def test_area_chart_without_a_measure_still_renders(make_chart):
    """An area chart authored with no `y:` must not crash the emitter.

    The normalizer accepts it — `ResolvedAreaChart.y` is optional and nothing infers
    a measure — so the emitter has to cope. The impute needs a measure field to key
    on and is simply skipped when there is none.
    """
    data = [{"date": "2024-01-01", "series": "Revenue"}]
    chart = make_chart("area", x="date", y=None, color="series", stack="zero")
    resolved = resolve(chart, data, chart_style_context=_CHART_STYLE_CONTEXT)
    artifact = render_resolved_chart(resolved, data, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    pane = spec["hconcat"][0] if "hconcat" in spec else spec
    for layer in pane.get("layer", []):
        assert _impute(layer) is None


_MULTI = [
    {"date": "2024-01-01", "revenue": 100, "costs": 80},
    {"date": "2024-02-01", "revenue": 120, "costs": None},
    {"date": "2024-03-01", "revenue": 110, "costs": 90},
]


def test_multi_metric_impute_groups_by_every_channel_vega_lite_facets_on(make_chart):
    """`y: [a, b]` folds to synthetic color and order channels.

    The impute's groupby has to retain both, or an imputed row missing one of
    the fields Vega-Lite stacks by becomes a phantom band.
    """
    chart = make_chart("area", x="date", y=["revenue", "costs"], stack="zero")
    resolved = resolve(chart, _MULTI, chart_style_context=_CHART_STYLE_CONTEXT)
    artifact = render_resolved_chart(resolved, _MULTI, _BOARD_STYLE, width=400)
    spec = artifact.payload
    pane = spec["hconcat"][0] if "hconcat" in spec else spec

    order_field = pane.get("encoding", {}).get("order", {}).get("field")
    assert order_field
    color_field = pane.get("encoding", {}).get("color", {}).get("field")
    assert color_field, (
        "multi-metric area is expected to carry a color (series) channel"
    )

    step = _impute(_area_layer(pane))
    assert step is not None, "multi-metric stacked area emits no impute"
    assert color_field in step["groupby"], (
        f"impute groupby {step['groupby']} omits the color channel {color_field!r} — "
        "Vega-Lite will facet on it and the imputed rows become a phantom band"
    )
    assert order_field in step["groupby"]
