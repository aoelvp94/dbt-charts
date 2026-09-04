"""The support_table strip stays anchored to the plot it hangs off.

``attach_support_table`` positions every strip layer with a pixel-literal y
(``{"y": {"value": <px>}}``) measured from the spec's explicit ``height`` — a
Vega-Lite constraint, not a choice (``{"y": {"expr": ...}}`` is read as a scaled
data value). The anchor is only true while that height is. When endpoint labels
wrap the chart in an ``hconcat``, ``$df_target_height`` used to tell the
converter to shrink the pane after the fact, sliding the plot bottom up while
the strip stayed put and opening a gap the width of the pane's chrome overhead.
"""

from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.authored import (
    ChartSupportTable,
    ChartSupportTableAggregate,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style_and_context,
)
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE, _ = resolve_style_and_context(get_theme_style())

_MULTI_SERIES = [
    {"date": "2026-01-01", "value": 10, "series": "a"},
    {"date": "2026-02-01", "value": 12, "series": "a"},
    {"date": "2026-03-01", "value": 9, "series": "a"},
    {"date": "2026-01-01", "value": 4, "series": "b"},
    {"date": "2026-02-01", "value": 6, "series": "b"},
    {"date": "2026-03-01", "value": 8, "series": "b"},
]

_SINGLE_SERIES = [
    {"date": "2026-01-01", "value": 10},
    {"date": "2026-02-01", "value": 12},
    {"date": "2026-03-01", "value": 9},
]


def _bottom_positioned_theme():
    """Theme with the strip moved below the plot — the reporter's authoring."""
    theme = get_theme_style()
    charts = theme.charts
    return theme.model_copy(
        update={
            "charts": charts.model_copy(
                update={
                    "support_table": charts.support_table.model_copy(
                        update={"position": "bottom"}
                    )
                }
            )
        }
    )


def _render(make_chart, data, with_color: bool, with_strip: bool):
    """Render the reporter's board shape: line chart, bottom-positioned strip."""
    kwargs: dict = {"x": "date", "y": "value"}
    if with_color:
        kwargs["color"] = "series"
    if with_strip:
        kwargs["support_table"] = ChartSupportTable(
            entries=[ChartSupportTableAggregate(aggregate="sum", source="value")]
        )
    resolved = resolve(
        make_chart("line", **kwargs),
        data,
        chart_style_context=resolve_chart_style_context(_bottom_positioned_theme()),
    )
    artifact = render_resolved_chart(
        resolved, data, _BOARD_STYLE, width=400, height=300
    )
    assert artifact.kind == "vega_spec"
    return artifact.payload


def _strip_drop_below_plot(spec) -> float:
    """How far the topmost strip layer hangs below its pane's plot rect."""
    pane = spec["hconcat"][0] if "hconcat" in spec else spec
    pixel_ys = [
        layer["encoding"]["y"]["value"]
        for layer in pane["layer"]
        if isinstance(layer.get("encoding", {}).get("y"), dict)
        and "value" in layer["encoding"]["y"]
    ]
    assert pixel_ys, "expected pixel-literal strip layers on the chart pane"
    return min(pixel_ys) - pane["height"]


@pytest.fixture
def strip_spec(make_chart):
    """Multi-series line chart with a bottom strip — the reported shape."""
    spec = _render(make_chart, _MULTI_SERIES, with_color=True, with_strip=True)
    assert "hconcat" in spec, (
        "fixture precondition: endpoint labels must wrap a multi-series line "
        "chart in an hconcat, otherwise this test exercises nothing"
    )
    return spec


def test_strip_spec_carries_no_target_height(strip_spec):
    """A pad-mode strip spec must not claim a fixed outer height.

    ``$df_target_height`` means "the outer SVG must end up exactly this tall".
    Under ``autosize: pad`` that is false by construction — the outer SVG is
    deliberately taller than ``spec.height`` by the strip's reserved padding,
    and layout_sizing measures the real height rather than forcing it down.
    """
    assert "$df_target_height" not in strip_spec


def test_strip_spec_still_carries_target_width(strip_spec):
    """Width correction is untouched — the outer width *is* meant to fit the slot."""
    assert "$df_target_width" in strip_spec


def test_conversion_leaves_the_strip_anchor_intact(strip_spec, monkeypatch):
    """The reported symptom: conversion must not move the plot out from under it.

    Drives the real strip spec through ``render_vega_spec`` with a stubbed
    vl-convert that reports the outer SVG overshooting by the strip's own
    reserved padding — exactly what ``autosize: pad`` produces. The pane's
    height must survive untouched, because every strip layer's y is a literal
    measured against it.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    pane = strip_spec["hconcat"][0]
    anchor_height = pane["height"]
    drop = _strip_drop_below_plot(strip_spec)

    # The endpoint-label pane's own rows drive the fake scenegraph's label
    # marks below, so recascade_endpoint_labels has real (distinct) values
    # to measure a slope from — this test cares about the strip anchor, not
    # label positions, but the post-probe recascade runs unconditionally
    # whenever the cascade sentinel is present (see
    # _correct_concat_overshoot's docstring), so the probe must carry a
    # structurally valid label-marks group for it to read.
    label_rows = strip_spec["hconcat"][1]["data"]["values"]
    series_field = strip_spec["$df_endpoint_label_cascade"]["series_field"]
    value_alias = strip_spec["$df_endpoint_label_cascade"]["value_alias"]
    label_leaves = [
        {"text": row[series_field], "y": 100.0 - row[value_alias]} for row in label_rows
    ]

    probe_calls = 0

    def fake_scenegraph(_spec):
        nonlocal probe_calls
        probe_calls += 1
        return {
            "width": 400.0,
            "height": anchor_height + drop,
            "origin": [0, 0],
            "scenegraph": {
                "items": [
                    {
                        "items": [
                            None,
                            {"items": [{"items": [{"items": label_leaves}]}]},
                        ]
                    }
                ]
            },
        }

    monkeypatch.setitem(
        sys.modules,
        "vl_convert",
        types.SimpleNamespace(
            vegalite_to_scenegraph=fake_scenegraph,
            vegalite_to_svg=mock.Mock(return_value="<svg/>"),
        ),
    )
    monkeypatch.setattr(chart_converter, "register_vl_convert_fonts", lambda _vlc: None)

    chart_converter.render_vega_spec(
        strip_spec, "svg", _BOARD_STYLE, 400, anchor_height, False, chart_id="chart"
    )

    # _correct_concat_overshoot swallows probe failures whole, so a stub that
    # stopped being called would leave this test green with nothing detecting
    # the regression. Pin that the correction path actually ran.
    assert probe_calls == 1, (
        f"expected one scenegraph probe, got {probe_calls} — the overshoot "
        "correction never ran, so this test proves nothing"
    )
    assert pane["height"] == anchor_height, (
        f"the plot pane shrank to {pane['height']} after the strip's y literals "
        f"were baked against {anchor_height} — every strip row now floats "
        f"{anchor_height - pane['height']:.0f}px too low"
    )


def test_single_series_strip_is_unaffected(make_chart):
    """No endpoint-label pane, no concat, no sentinel question — must not regress."""
    spec = _render(make_chart, _SINGLE_SERIES, with_color=False, with_strip=True)
    assert "hconcat" not in spec
    assert "$df_target_height" not in spec


def test_concat_chart_without_a_strip_keeps_target_height(make_chart):
    """The height correction still applies where it was always correct.

    Endpoint-label charts with no support_table have no pixel-literal anchors, so
    the converter must keep shrinking their panes to fit the slot.
    """
    spec = _render(make_chart, _MULTI_SERIES, with_color=True, with_strip=False)
    assert "hconcat" in spec
    assert "$df_target_height" in spec


# ---------------------------------------------------------------------------
# Column-block geometry: the transpose of everything above. A stacked
# horizontal bar's endpoint-label rail wraps the chart in vconcat (top_rail,
# rail first, chart pane at index 1) rather than hconcat, and the column
# block's own cells are pixel-literal x positions (position: right measures
# from spec.width itself — see support_table_attachment._column_edges) rather
# than y positions — so it is $df_target_width, not $df_target_height, that
# must not survive to _correct_concat_overshoot.
# ---------------------------------------------------------------------------

_HBAR_STACKED_DATA = [
    {"region": "East", "category": "Apple", "revenue": 100.0},
    {"region": "East", "category": "Banana", "revenue": 50.0},
    {"region": "West", "category": "Apple", "revenue": 200.0},
    {"region": "West", "category": "Banana", "revenue": 80.0},
]


def _render_hbar(make_chart, data, with_color: bool, with_table: bool):
    """Render a horizontal bar, stacked when colored — the top_rail shape."""
    kwargs: dict = {
        "x": "region",
        "y": "revenue",
        "style": {"orientation": "horizontal"},
    }
    if with_color:
        kwargs["color"] = "category"
        kwargs["stack"] = "zero"
    if with_table:
        kwargs["support_table"] = ChartSupportTable(
            entries=[ChartSupportTableAggregate(aggregate="sum", source="revenue")]
        )
    resolved = resolve(
        make_chart("bar", **kwargs),
        data,
        chart_style_context=resolve_chart_style_context(get_theme_style()),
    )
    artifact = render_resolved_chart(
        resolved, data, _BOARD_STYLE, width=400, height=300
    )
    assert artifact.kind == "vega_spec"
    return artifact.payload


@pytest.fixture
def column_spec(make_chart):
    """Stacked horizontal bar with a column block — the reported shape's transpose."""
    spec = _render_hbar(
        make_chart, _HBAR_STACKED_DATA, with_color=True, with_table=True
    )
    assert "vconcat" in spec, (
        "fixture precondition: a stacked horizontal bar with a series color "
        "must wrap in vconcat, otherwise this test exercises nothing"
    )
    return spec


def test_column_spec_carries_no_target_width(column_spec):
    """A pad-mode column block must not claim a fixed outer width, mirroring
    the row strip's height rule above."""
    assert "$df_target_width" not in column_spec


def test_column_spec_still_carries_target_height(column_spec):
    """Height correction is untouched — the outer height *is* meant to fit the slot."""
    assert "$df_target_height" in column_spec


_HBAR_SINGLE_SERIES_DATA = [
    {"region": "East", "revenue": 150.0},
    {"region": "West", "revenue": 280.0},
]


def test_single_series_column_is_unaffected(make_chart):
    """No series color, no rail, no concat, no sentinel question — must not regress."""
    spec = _render_hbar(
        make_chart, _HBAR_SINGLE_SERIES_DATA, with_color=False, with_table=True
    )
    assert "vconcat" not in spec


def test_concat_hbar_without_a_table_keeps_target_width(make_chart):
    """The width correction still applies where it was always correct.

    A stacked horizontal bar with no support_table has no pixel-literal
    column anchors, so the converter must keep shrinking its pane to fit
    the slot.
    """
    spec = _render_hbar(
        make_chart, _HBAR_STACKED_DATA, with_color=True, with_table=False
    )
    assert "vconcat" in spec
    assert "$df_target_width" in spec
