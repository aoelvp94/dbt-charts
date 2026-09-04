"""X-axis label crowding must measure the real plot width, not the card slot.

``resolve_axis_x_overlap`` decides tilt/skip by comparing label footprints
against ``chart_width * label_usable_ratio`` (``_label_overlap.py``). That
decision runs inside the family emitter, before the endpoint-label rail
(``features/endpoint_labels.py``) claims its share of the card — so a chart
with a wide series-label rail concludes its x labels fit flat when the real
plot left for them is much narrower. Mirrors the corpus regression cell
``13-label-length-x-width.yml#lbl_long_sp9`` (registered in
``matrix_known_defects.yml``): 5 series with ~39-character names on a 450px
bar card, 12 monthly x points.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.authored import (
    ChartSupportTable,
    ChartSupportTableAggregate,
)
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    LineChart,
)
from dbt_charts.core.compile.models.chart.resolved import (
    ResolvedAreaChart,
    ResolvedBarChart,
    ResolvedLineChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.emitters._endpoint_rail import (
    resolve_endpoint_rail_span,
)
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_LONG_SERIES = [f"Series {i:02d} with a long descriptive label" for i in range(1, 6)]
_MONTHS = [f"2024-{m:02d}-01" for m in range(1, 13)]


def _long_label_rail_data() -> list[dict[str, str | float]]:
    return [
        {"month": month, "value": float(10 * (i + 1)), "series": series}
        for i, series in enumerate(_LONG_SERIES)
        for month in _MONTHS
    ]


_LONG_WIDE_FIELDS = [
    "Revenue with a long descriptive label",
    "Expenses with a long descriptive label",
]


def _long_wide_rail_data() -> list[dict[str, str | float]]:
    """Wide shape: a list ``y:`` takes its series names from the FIELD names,
    so the rail's width comes from these, not from a ``series`` column."""
    return [
        {"month": month, _LONG_WIDE_FIELDS[0]: 10.0, _LONG_WIDE_FIELDS[1]: 20.0}
        for month in _MONTHS
    ]


def _resolved_bar(width: float) -> tuple[ResolvedBarChart, object]:
    chart = BarChart(
        id="lbl_long_sp9",
        source_path="charts.lbl_long_sp9",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="month",
        y="value",
        color="series",
        style=BarChartStylePatch(stack="zero"),
    )
    rs, ctx = resolve_style_and_context(get_theme_style())
    resolved = resolve(
        chart, _long_label_rail_data(), chart_style_context=ctx, width=width
    )
    assert isinstance(resolved, ResolvedBarChart)
    return resolved, rs


def test_wide_rail_thins_monthly_labels_it_previously_left_flat() -> None:
    """lbl_long_sp9: a 450px bar card with a wide series-label rail must not
    conclude its 12 monthly x labels fit flat at full monthly cadence — the
    real plot left for them (after the rail) is far narrower than 0.8 * 450.

    Before the fix, ``resolve_axis_x_overlap`` sees 12 short month
    abbreviations "fit" in 0.8*450=360px (the card, not the plot) and never
    thins past ``"yearmonth"`` — even though the rail leaves far less room
    than that, and the labels genuinely overprint. Pinned through
    ``render_resolved_chart`` (not a resolver-level re-derivation) so that
    reverting the ``reserved_width``/``chart_width`` wiring in the emitters
    actually fails this test: without the fix the emitted ``labelExpr``
    stops at ``utcmonth(...) === 0`` (every month) and ``ticks`` is
    ``False``; with the fix it thins to ``utcmonth(...) % 3 === 0``
    (quarterly) and ``ticks`` is ``True``.
    """
    resolved, rs = _resolved_bar(450.0)
    data = _long_label_rail_data()
    rail = resolve_endpoint_rail_span(resolved, data, 450.0)
    assert rail > 0.0, "this fixture must carry a real endpoint-label rail"

    artifact = render_resolved_chart(resolved, data, rs, width=450.0)
    spec = artifact.payload
    axis = spec["hconcat"][0]["encoding"]["x"]["axis"]

    assert "utcmonth(toDate(datum.value)) % 3 === 0" in axis["labelExpr"], (
        "12 monthly labels must thin to quarterly cadence once the rail's "
        f"{rail:.1f}px is subtracted from the plot width; got "
        f"labelExpr={axis['labelExpr']!r}"
    )
    assert axis["ticks"] is True


def test_no_rail_chart_is_unaffected_by_the_rail_span_fix() -> None:
    """A single-series bar (no endpoint-label rail at all) must resolve the
    same overlap decision whether or not the rail-span subtraction exists —
    reserved_width is always 0.0 for it.
    """
    chart = BarChart(
        id="no_rail",
        source_path="charts.no_rail",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="month",
        y="value",
        style=BarChartStylePatch(stack="zero"),
    )
    data = [{"month": month, "value": 10.0} for month in _MONTHS]
    rs, ctx = resolve_style_and_context(get_theme_style())
    resolved = resolve(chart, data, chart_style_context=ctx, width=450.0)
    assert isinstance(resolved, ResolvedBarChart)

    artifact = render_resolved_chart(resolved, data, rs, width=450.0)
    spec = artifact.payload
    assert "hconcat" not in spec, "single-series bar must not grow a rail pane"
    assert resolve_endpoint_rail_span(resolved, data, 450.0) == 0.0


def test_line_chart_wide_rail_reserved_width_matches_the_feature_pass() -> None:
    """The pre-crowding rail-width estimate (line/area path) is the same
    figure the endpoint-label feature pass bakes into the final spec's
    hconcat pane — one measurement, not two independently-computed ones.
    """
    chart = LineChart(
        id="line_long_rail",
        source_path="charts.line_long_rail",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="line",
        x="month",
        y="value",
        color="series",
    )
    data = _long_label_rail_data()
    rs, ctx = resolve_style_and_context(get_theme_style())
    resolved = resolve(chart, data, chart_style_context=ctx, width=450.0)
    assert isinstance(resolved, ResolvedLineChart)

    artifact = render_resolved_chart(resolved, data, rs, width=450.0)
    spec = artifact.payload
    assert "hconcat" in spec
    pane_width = spec["hconcat"][1]["width"]
    label_offset = resolved.style.endpoint_labels.label_offset
    estimated_span = resolve_endpoint_rail_span(resolved, data, 450.0)
    assert estimated_span == pane_width + label_offset


@pytest.mark.parametrize(
    ("family", "chart_cls", "resolved_cls", "y_field", "color_field"),
    [
        ("line", LineChart, ResolvedLineChart, "value", "series"),
        ("line-wide", LineChart, ResolvedLineChart, _LONG_WIDE_FIELDS, None),
        ("area", AreaChart, ResolvedAreaChart, "value", "series"),
        ("area-wide", AreaChart, ResolvedAreaChart, _LONG_WIDE_FIELDS, None),
    ],
)
def test_wide_rail_thins_labels_the_card_width_alone_would_not(
    family: str,
    chart_cls: Any,
    resolved_cls: Any,
    y_field: Any,
    color_field: str | None,
) -> None:
    """Each ``reserved_width`` wiring point, pinned individually.

    There are five: ``bar.py`` (covered by the bar test above), ``line.py``
    twice and ``area.py`` twice. A single case exercises only one of them, so
    deleting any of the other four changes real board output with nothing to
    notice — which is exactly what a review round found after the first fix
    covered two of the five.

    The ``-wide`` shapes matter on their own: a list ``y:`` gets a synthetic
    series-colour channel injected unconditionally (``_wide_fields.py``), so
    it carries an endpoint-label rail with no authored opt-in at all, and the
    theme switches the rail on by default regardless.

    At 500px this fixture's rail makes the real plot narrower than the
    quarterly-cadence threshold while the full 500px card is not. Without the
    subtraction the axis stays at monthly and emits
    ``(datum.index === 0 || utcmonth(...) === 0)`` — all twelve months.
    """
    kwargs: dict[str, Any] = {
        "id": f"{family}_long_rail_500",
        "source_path": f"charts.{family}_long_rail_500",
        "query": SqlQuery(sql="SELECT 1", source="t"),
        "query_name": "q",
        "type": "area" if family.startswith("area") else "line",
        "x": "month",
        "y": y_field,
    }
    if color_field is not None:
        kwargs["color"] = color_field
    chart = chart_cls(**kwargs)

    data = (
        _long_wide_rail_data() if family.endswith("-wide") else _long_label_rail_data()
    )
    rs, ctx = resolve_style_and_context(get_theme_style())
    resolved = resolve(chart, data, chart_style_context=ctx, width=500.0)
    assert isinstance(resolved, resolved_cls)
    rail = resolve_endpoint_rail_span(resolved, data, 500.0)
    assert rail > 0.0, f"{family} must carry a real endpoint-label rail"

    spec = render_resolved_chart(resolved, data, rs, width=500.0).payload
    axis = spec["hconcat"][0]["encoding"]["x"]["axis"]

    assert "utcmonth(toDate(datum.value)) % 3 === 0" in axis["labelExpr"], (
        f"{family}: 12 monthly labels must thin to quarterly once the rail's "
        f"{rail:.1f}px is subtracted from the plot width; got "
        f"labelExpr={axis['labelExpr']!r}"
    )


def _strip_text_layers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The attached support_table's per-band text-mark layers."""
    layer = spec["hconcat"][0]["layer"]
    return [
        entry
        for entry in layer
        if isinstance(entry.get("mark"), dict) and entry["mark"].get("type") == "text"
    ]


def test_endpoint_rail_and_support_table_strip_agree_on_visible_labels() -> None:
    """A ``support_table`` strip attached to an endpoint-labelled chart must
    mirror the axis's own label-period thinning, not the card's full width.

    ``_label_period_filter_expr`` (support_table_attachment.py) reads
    ``spec.get("width")`` to decide whether the strip should thin its cells
    to label-period openers — but that spec is ``hconcat[0]``, whose
    ``"width"`` is still the unreduced card width (the pane shrink happens
    later, in the converter's overshoot correction). The axis's own crowding
    decision, by contrast, already subtracts the endpoint-label rail's span
    before it decides to thin. The two must land on the same cadence: when
    the axis thins its 12 monthly labels to quarterly, the strip must gain a
    matching ``filter`` transform restricting its cells to the same 4
    quarterly openers — not keep all 12.
    """
    chart = LineChart(
        id="line_long_rail_dt",
        source_path="charts.line_long_rail_dt",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="line",
        x="month",
        y="value",
        color="series",
        support_table=ChartSupportTable(
            entries=[ChartSupportTableAggregate(aggregate="sum", source="value")]
        ),
    )
    data = _long_label_rail_data()
    rs, ctx = resolve_style_and_context(get_theme_style())
    resolved = resolve(chart, data, chart_style_context=ctx, width=500.0)
    assert isinstance(resolved, ResolvedLineChart)
    rail = resolve_endpoint_rail_span(resolved, data, 500.0)
    assert rail > 0.0, "this fixture must carry a real endpoint-label rail"

    artifact = render_resolved_chart(resolved, data, rs, width=500.0)
    spec = artifact.payload
    axis = spec["hconcat"][0]["encoding"]["x"]["axis"]
    axis_thins_to_quarterly = (
        "utcmonth(toDate(datum.value)) % 3 === 0" in axis["labelExpr"]
    )
    assert axis_thins_to_quarterly, (
        "fixture must reproduce the axis's own quarterly thinning; got "
        f"labelExpr={axis['labelExpr']!r}"
    )

    text_layers = _strip_text_layers(spec)
    assert text_layers, "support_table must attach at least one text-mark layer"
    strip_has_matching_filter = any(
        any(
            isinstance(step, dict)
            and "filter" in step
            and "% 3 === 0" in str(step["filter"])
            for step in layer.get("transform", [])
        )
        for layer in text_layers
    )
    assert strip_has_matching_filter, (
        "the axis thinned its 12 monthly labels to quarterly, but no "
        "support_table text layer carries a matching quarterly-opener filter — "
        "the strip is still measuring the unreduced card width and will "
        "paint one cell per month while the axis shows one label per "
        f"quarter. Layers: {text_layers!r}"
    )
