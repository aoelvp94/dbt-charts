"""Render-path tests: per_series support_table labels and legend interaction.

When a per_series support_table is attached and the chart has a visible color
legend, the legend is suppressed (not the labels).  The labels and the
legend encode the same series information; showing both is redundant ink,
but we keep the labels (table-oriented layout) and drop the side legend.

With endpoint labels both label pane and support table labels are visible.

Series ordering in the strip reflects the chart's visual top-to-bottom:
  - bar (stacked, value order): smallest global sum first (top of stack)
  - bar (stacked, alphabetical): Z-first (top of alphabetical stack)
  - line/area: highest last-x y value first
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from dbt_charts.core.compile.config import reset_config
from dbt_charts.core.compile.models.chart.authored import (
    ChartSupportTable,
)
from dbt_charts.core.compile.models.chart.normalized import BarChart, Chart, LineChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec


def _multi_series_data():
    return [
        {"month": "Jan", "rev": 100, "series": "A"},
        {"month": "Feb", "rev": 200, "series": "A"},
        {"month": "Jan", "rev": 50, "series": "B"},
        {"month": "Feb", "rev": 80, "series": "B"},
    ]


def _chart_spec(
    chart_type: str = "bar",
    data: list[dict[str, Any]] | None = None,
    support_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reset_config()
    if data is None:
        data = _multi_series_data()
    if support_table is None:
        support_table = {"entries": [{"per_series": "rev"}]}
    payload: dict[str, Any] = {
        "id": "t",
        "type": chart_type,
        "x": "month",
        "y": "rev",
        "color": "series",
        "query": SqlQuery(sql="SELECT 1", source="src"),
        "query_name": "q",
        "support_table": ChartSupportTable.model_validate(support_table),
    }
    if chart_type == "bar":
        # "month" is a categorical string x, which auto-resolves to horizontal;
        # support_table is unsupported there, so pin vertical explicitly.
        payload["style"] = {"orientation": "vertical"}
    chart = TypeAdapter(Chart).validate_python(payload)
    return generate_vega_lite_spec(
        chart,
        data,
        width=400,
    )


def _chart_inner(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the chart body spec, unwrapping hconcat if endpoint labels fired."""
    if "hconcat" in spec:
        return spec["hconcat"][0]
    return spec


def _label_layers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    inner = _chart_inner(spec)
    return [
        layer
        for layer in inner.get("layer", [])
        if isinstance(layer.get("mark"), dict)
        and layer["mark"].get("type") == "text"
        and layer.get("encoding", {}).get("text", {}).get("field") == "__label"
    ]


def _color_legend(spec: dict[str, Any]) -> Any:
    inner = _chart_inner(spec)
    return inner.get("encoding", {}).get("color", {}).get("legend")


def _label_layer_names(spec: dict[str, Any]) -> list[str]:
    """Return series names from label layers in visual reading order (top-to-bottom).

    Each per_series label layer carries its own inline data:
    {"values": [{"__label": "<series_name>"}]}.

    For position:top (default), strip rows have negative y values; more negative =
    higher on screen = visually first.  Sorting by y ascending (most negative first)
    gives the visual top-to-bottom reading order so callers can assert order[0] =
    the series at the top of the strip.
    """
    layers_with_y: list[tuple[float | None, str]] = []
    for layer in _chart_inner(spec).get("layer", []):
        if not (
            isinstance(layer.get("mark"), dict) and layer["mark"].get("type") == "text"
        ):
            continue
        enc = layer.get("encoding", {})
        if enc.get("text", {}).get("field") != "__label":
            continue
        data_vals = layer.get("data", {}).get("values", [])
        if not data_vals:
            continue
        label_val = data_vals[0].get("__label")
        if label_val is None:
            continue
        y_val = (
            enc.get("y", {}).get("value") if isinstance(enc.get("y"), dict) else None
        )
        layers_with_y.append((y_val, str(label_val)))

    # Sort by y ascending: most negative y = highest on screen = first in reading order.
    layers_with_y.sort(key=lambda item: item[0] if item[0] is not None else 0.0)
    return [name for _, name in layers_with_y]


def test_per_series_labels_shown_legend_suppressed():
    # Legend visible + per_series support_table → labels SHOW, legend suppressed.
    # The support table provides the series legend; a side legend is redundant.
    spec = _chart_spec()
    assert _label_layers(spec), "per_series labels must be visible in the strip"
    assert _color_legend(spec) is None, (
        "color legend must be suppressed when per_series support_table is present; "
        f"got legend={_color_legend(spec)!r}"
    )


def test_aggregate_support_table_does_not_suppress_legend():
    # aggregate entries have no per-series rows — legend stays visible.
    reset_config()
    data = _multi_series_data()
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="rev",
        color="series",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
        support_table=ChartSupportTable.model_validate(
            {"entries": [{"aggregate": "sum", "source": "rev"}]}
        ),
        style={"orientation": "vertical"},
    )
    spec = generate_vega_lite_spec(
        chart,
        data,
        width=400,
    )
    # An aggregate-only table has no series labels; legend must not be
    # explicitly suppressed (key absent or non-null is fine; explicit None = suppressed).
    color_enc = spec.get("encoding", {}).get("color", {})
    assert color_enc.get("legend", "visible") is not None, (
        "aggregate-only support_table must not suppress the color legend; "
        f"got color.legend={color_enc.get('legend')!r}"
    )


def test_bar_stacked_value_order_smallest_sum_first():
    # Default stack_order (value): largest-sum series sits at the baseline
    # (bottom of visual stack); smallest-sum series is at the top.
    # Support table row order must be top-to-bottom, so smallest sum = row 0.
    # A has sum=300, B has sum=130 → B is topmost → B appears as first label layer.
    # stack="zero" makes it explicitly stacked (stack=None → grouped side-by-side).
    data = [
        {"month": "Jan", "rev": 100, "series": "A"},
        {"month": "Feb", "rev": 200, "series": "A"},
        {"month": "Jan", "rev": 50, "series": "B"},
        {"month": "Feb", "rev": 80, "series": "B"},
    ]
    reset_config()
    chart = BarChart(
        id="t",
        type="bar",
        x="month",
        y="rev",
        color="series",
        stack="zero",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
        support_table=ChartSupportTable.model_validate(
            {"entries": [{"per_series": "rev"}]}
        ),
        style={"orientation": "vertical"},
    )
    spec = generate_vega_lite_spec(
        chart,
        data,
        width=400,
    )
    label_names = _label_layer_names(spec)
    assert label_names, "per_series label layers must be present"
    assert label_names[0] == "B", (
        "B has the smaller global sum (130 vs 300) — it sits at the top of "
        f"the stacked bar, so it must be the first label row; got {label_names!r}"
    )


def test_line_series_order_highest_last_x_first():
    # Line chart: series with highest y at the last x point should be the
    # first row (top of strip), matching endpoint-label top-to-bottom order.
    # At month=Feb: A=200, B=80 → A has higher last-x y → A is first.
    data = [
        {"month": "Jan", "rev": 100, "series": "A"},
        {"month": "Feb", "rev": 200, "series": "A"},
        {"month": "Jan", "rev": 50, "series": "B"},
        {"month": "Feb", "rev": 80, "series": "B"},
    ]
    reset_config()
    chart = LineChart(
        id="t",
        type="line",
        x="month",
        y="rev",
        color="series",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
        support_table=ChartSupportTable.model_validate(
            {"entries": [{"per_series": "rev"}]}
        ),
    )
    spec = generate_vega_lite_spec(
        chart,
        data,
        width=400,
    )
    label_names = _label_layer_names(spec)
    assert label_names, "per_series label layers must be present"
    assert label_names[0] == "A", (
        "A has the higher y at last x (200 vs 80) — it sits at the top of "
        f"the endpoint label pane, so it must be the first label row; got {label_names!r}"
    )
