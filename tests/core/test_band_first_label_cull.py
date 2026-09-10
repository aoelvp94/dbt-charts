"""Vega culls a band scale's FIRST axis label at isolated plot widths.

Given an explicit ``axis.values`` list and a band x scale with no outer
padding, Vega drops the label on the first band at scattered widths — present
at one width, gone half a pixel later, present again half a pixel after that.
Because it is width-dependent it does not survive a resize, so an author who
notices the gap and drags the window watches it come back.

Characterized against vl_convert 1.9.0 over thousands of half-pixel widths:

* it is always the FIRST band and never any other;
* it fires for any ``values`` list containing that band — a full-domain list
  and a thinned cadence list alike (and the cadence ladder always anchors the
  first label, so thinned axes are not spared);
* it is unaffected by ``labelOverlap``, ``labelBound``, ``labelFlush``,
  ``labelLimit``, ``labelSeparation``, and by the label's own text (a
  one-word label drops exactly as a two-line one does);
* it does not reproduce with no ``values`` at all, nor with Vega-Lite's
  default scale padding — only against the zero outer padding dbt charts
  emits so bars sit flush to the plot edges.

This is a separate defect from the layered-domain bug in
``test_layer_extended_x_domain_labels.py``: it needs no overlay, and covering
the full domain does not cure it. ``nudge_band_scale_off_range_start`` fixes it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import vl_convert as vlc

from dbt_charts.core.compile.models.chart.authored._layer import LineLayer
from dbt_charts.core.compile.models.chart.normalized import BarChart as NBarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.chart._chart_rows import regroup
from dbt_charts.core.font_measure import RESERVATION_GUARD
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters.bar import BarEmitter
from dbt_charts.core.render.chart.spec import RenderBox
from dbt_charts.core.render.chart.translate import translate_to_vl


def _months(count: int) -> list[str]:
    out, year, month = [], 2026, 1
    for _ in range(count):
        out.append(f"{year}-{month:02d}-01")
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return out


_MONTHS = _months(13)
_BASE = [{"month": m, "revenue": 100.0 + i * 10} for i, m in enumerate(_MONTHS[:8])]
_GOAL = [{"month": m, "goal": 150.0 + i * 10} for i, m in enumerate(_MONTHS)]


def _default_board_style():
    from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    return resolve_chart_style_context(get_theme_style(get_default_theme_name()))


def _emit(layered: bool = True, style: dict | None = None, n_bands: int = 13) -> VLDict:
    rows = (
        _BASE
        if layered
        else [
            {"month": m, "revenue": 100.0 + i * 10}
            for i, m in enumerate(_months(n_bands))
        ]
    )
    chart = NBarChart(
        id="bar1",
        type="bar",
        x="month",
        y="revenue",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        variable_dependencies=set(),
        layers=[LineLayer(type="line", y="goal", query="goals")] if layered else [],
        **({"style": style} if style else {}),
    )
    resolved = resolve(chart, rows, _default_board_style())
    return translate_to_vl(
        BarEmitter().emit(
            resolved,
            RenderBox(width=600.0, height=300.0),
            regroup((), rows),
            datasets={"goals": _GOAL} if layered else None,
        )
    )


def _first_label(vl: VLDict, plot_width: float) -> str:
    """The leftmost x-axis label Vega actually paints at this plot width.

    Walks the compiled scenegraph, not the spec: whether the label survives to
    the canvas is the entire question, and the spec cannot answer it. Numeric
    y-axis ticks interleave in scenegraph order, and a right-edge y-axis pads
    its labels with the digit-field device — strip that before the digit test
    or a padded "0" reads as non-numeric and leaks in.
    """
    spec = json.loads(json.dumps(vl))
    spec["width"] = plot_width
    scenegraph = vlc.vega_to_scenegraph(vlc.vegalite_to_vega(json.dumps(spec)))

    def walk(node: Any) -> Iterator[tuple[float, str]]:
        if isinstance(node, dict):
            if node.get("marktype") == "text" and node.get("role") == "axis-label":
                for item in node["items"]:
                    text = item["text"]
                    yield (
                        item["x"],
                        (" ".join(text) if isinstance(text, list) else text),
                    )
            for child in node.get("items", []):
                yield from walk(child)
        elif isinstance(node, list):
            for child in node:
                yield from walk(child)

    pad = RESERVATION_GUARD
    labels = [
        text
        for _, text in sorted(walk(scenegraph["scenegraph"]), key=lambda p: p[0])
        if not text.strip(pad).replace(",", "").replace(".", "").lstrip("-").isdigit()
    ]
    assert labels, f"no x-axis labels at all at plot width {plot_width}"
    return labels[0]


def test_flush_band_scale_is_nudged_off_its_range_start() -> None:
    """The mechanism: a flush-to-edge band scale carrying explicit tick values
    gets an epsilon of outer padding, lifting the first band off the exact
    range start where Vega's rounding drops its label."""
    scale = _emit()["encoding"]["x"]["scale"]
    assert scale["padding"] == 0
    assert scale["paddingOuter"] > 0


def test_authored_outer_padding_is_left_exactly_as_authored() -> None:
    """An authored outer padding already puts the first band off the range
    start, so there is nothing to fix and the nudge must not overwrite the
    author's value. A guard, not a regression test — it passes either way."""
    scale = _emit(style={"axis_x": {"scale": {"padding": 0.3}}})["encoding"]["x"][
        "scale"
    ]
    assert scale["padding"] == 0.3
    assert "paddingOuter" not in scale


# The widths reported from the affected board, crossed with band counts —
# which width bites depends on the band count, since the fault is a rounding
# accident at the first band's position. On the unfixed emitter 482.0 drops at
# 19 bands and 481.5 drops at 25; a single band count would leave the reported
# widths passing for the wrong reason.
@pytest.mark.parametrize("n_bands", [13, 19, 25])
@pytest.mark.parametrize("plot_width", [481.5, 482.0, 482.5])
def test_first_label_renders_at_reported_widths(
    plot_width: float, n_bands: int
) -> None:
    label = _first_label(_emit(layered=False, n_bands=n_bands), plot_width)
    assert label.startswith("Jan")


# Two-pixel steps across the neighborhood. On the unfixed emitter the
# leading label vanishes at 27 of the 100 half-pixel widths here, scattered
# rather than banded, so a single spot check cannot hold this — but every
# width costs a vega→scenegraph round trip, and sampling 25 of them still
# catches the scatter.
@pytest.mark.parametrize("plot_width", [w / 2 for w in range(900, 1000, 4)])
def test_first_label_renders_across_a_width_sweep(plot_width: float) -> None:
    assert _first_label(_emit(), plot_width).startswith("Jan")


@pytest.mark.parametrize("plot_width", [465.0, 478.0, 480.0, 484.5, 486.5])
def test_first_label_renders_without_any_overlay(plot_width: float) -> None:
    """The cull needs no overlay — a plain single-series bar chart whose axis
    carries tick values drops its first label at exactly the same widths. The
    layered-domain fix and this one are genuinely separate defects."""
    assert _first_label(_emit(layered=False), plot_width).startswith("Jan")


def test_bar_base_with_a_step_layer_is_exempt_from_the_nudge() -> None:
    """The exemption has to fire on the LAYER's curve, not just the base's.

    A bar base carrying a ``curve: step`` line layer band-doubles this same
    shared scale, so adjacent band edges are load-bearing even though the
    base itself draws plain bars. This is the path ``overlay_uses_band_step``
    exists for — the sibling test below authors the curve on the chart's own
    mark and reaches a different, pre-existing gate instead.
    """
    from dbt_charts.core.compile.models.chart.authored._layer import (
        LineLayer as _LineLayer,
    )

    rows = [{"month": m, "revenue": 10.0 + i} for i, m in enumerate(_months(13))]
    goal = [{"month": m, "goal": 20.0 + i} for i, m in enumerate(_months(13))]
    chart = NBarChart(
        id="bar1",
        type="bar",
        x="month",
        y="revenue",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        variable_dependencies=set(),
        layers=[
            _LineLayer(
                type="line",
                y="goal",
                query="goals",
                style={"marks": {"line": {"curve": "step"}}},
            )
        ],
    )
    resolved = resolve(chart, rows, _default_board_style())
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            RenderBox(width=600.0, height=300.0),
            regroup((), rows),
            datasets={"goals": goal},
        )
    )
    assert "paddingOuter" not in vl["encoding"]["x"].get("scale", {})


def test_band_step_curve_is_exempt_from_the_nudge() -> None:
    """The band-aware ``step`` curve doubles each row onto its band's two edges
    and puts the riser on the boundary the next band shares, so it depends on
    those two coordinates being the same float. Outer padding — at any size —
    separates them and lands risers on the wrong edge, which showed up as
    41.56px plateau shifts on the ``quick-guide_5`` golden. The nudge must not
    fire here; the plateau geometry outranks the first label."""
    from dbt_charts.core.compile.models.chart.normalized import LineChart
    from dbt_charts.core.render.chart.emitters import get_emitter

    rows = [
        {"m": f"2026-{i:02d}-01", "v": v}
        for i, v in zip(range(1, 7), [10, 40, 25, 60, 35, 50], strict=True)
    ]
    chart = LineChart(
        id="line1",
        type="line",
        x="m",
        y="v",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        variable_dependencies=set(),
        style={"axis_x": {"type": "ordinal"}, "marks": {"line": {"curve": "step"}}},
    )
    resolved = resolve(chart, rows, _default_board_style())
    vl = translate_to_vl(
        get_emitter(resolved).emit(
            resolved, RenderBox(width=520.0, height=300.0), regroup((), rows)
        )
    )
    assert "xOffset" in vl["encoding"], "expected the band-doubled step geometry"
    assert "paddingOuter" not in vl["encoding"]["x"].get("scale", {})


@pytest.mark.parametrize("base_type", ["line", "area"])
def test_continuous_base_with_a_step_layer_is_exempt_from_the_nudge(
    base_type: str,
) -> None:
    """The exemption has to reach the line/area path too, not just bar.

    A line base drawing a plain curve, carrying a ``curve: step`` layer, still
    band-doubles this shared scale — `resolve_cartesian_x` only sees the
    BASE's curve, so without the layer verdict threaded in it nudges a scale
    whose adjacent edges are load-bearing. Fails if the `band_doubled or` half
    of that condition is removed.
    """
    from dbt_charts.core.compile.models.chart.authored._layer import (
        LineLayer as _LineLayer,
    )
    from dbt_charts.core.compile.models.chart.normalized import AreaChart, LineChart
    from dbt_charts.core.render.chart.emitters import get_emitter

    rows = [{"month": m, "v": 10.0 + i} for i, m in enumerate(_months(13))]
    goal = [{"month": m, "goal": 20.0 + i} for i, m in enumerate(_months(13))]
    family = LineChart if base_type == "line" else AreaChart
    chart = family(
        id=f"{base_type}1",
        type=base_type,
        x="month",
        y="v",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        variable_dependencies=set(),
        style={"axis_x": {"type": "ordinal"}},
        layers=[
            _LineLayer(
                type="line",
                y="goal",
                query="goals",
                style={"marks": {"line": {"curve": "step"}}},
            )
        ],
    )
    resolved = resolve(chart, rows, _default_board_style())
    vl = translate_to_vl(
        get_emitter(resolved).emit(
            resolved,
            RenderBox(width=600.0, height=300.0),
            regroup((), rows),
            datasets={"goals": goal},
        )
    )
    assert "paddingOuter" not in vl["encoding"]["x"].get("scale", {})


def test_a_y_less_step_layer_does_not_exempt_the_scale() -> None:
    """``overlay_uses_band_step`` must agree with what the overlay actually
    draws. A layer with no ``y:`` is authorable and ``render_cartesian_overlay``
    skips it outright — nothing is doubled, so there is no shared band edge to
    protect. Exempting on it would silently reinstate the cull this task
    removes, on a chart that never band-doubles anything.
    """
    from dbt_charts.core.compile.models.chart.authored._layer import (
        LineLayer as _LineLayer,
    )
    from dbt_charts.core.compile.models.chart.normalized import LineChart
    from dbt_charts.core.render.chart.emitters._overlay import overlay_uses_band_step

    rows = [{"month": m, "v": 10.0 + i} for i, m in enumerate(_months(13))]
    chart = LineChart(
        id="line1",
        type="line",
        x="month",
        y="v",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        variable_dependencies=set(),
        style={"axis_x": {"type": "ordinal"}},
        layers=[_LineLayer(type="line", style={"marks": {"line": {"curve": "step"}}})],
    )
    resolved = resolve(chart, rows, _default_board_style())
    assert not overlay_uses_band_step(resolved.layers)
