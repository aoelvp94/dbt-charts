"""Regression: bar must keep every time-bucket its data contains, including
null-valued ones, matching line/area.

Vega-Lite's default ordinal-domain inference filters marks (and hence
categories) with an invalid (null) quantitative value out of the scale
domain entirely — a row-level filter, not a per-value one. Line/area don't
show this because their bucketed-calendar x resolves to a continuous
temporal scale (domain = [min, max]), so a filtered-out row doesn't shrink
the domain. Bar's ordinal/nominal (band) x scale has no such cushion: a
filtered row removes its category from the domain outright.

The fix wires Vega-Lite's own ``config.mark.invalid: "break-paths-show-
domains"`` — a native option that keeps every category slot on the axis
and simply draws no mark for the invalid row. This is data-independent (no
computed domain pinned from query rows), so it also fixes the same bug on
a plain nominal-categorical axis and never collides with an authored
``chart.sort`` — see the ``_MARK_INVALID_CONFIG`` docstring in
``emitters/bar.py`` and the ``## Decision`` section of the task above.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.authored import ChartSort
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart
from dbt_charts.core.render.converters.chart import render_vega_spec

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())

_MONTHS = [f"2024-{m:02d}-01" for m in range(1, 13)]


def _monthly_data(
    null_months: set[str], series: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    if not series:
        return [
            {"month": m, "revenue": None if m in null_months else 100 + i}
            for i, m in enumerate(_MONTHS)
        ]
    return [
        {
            "month": m,
            "revenue": None if m in null_months else 100 + i,
            "series": s,
        }
        for i, m in enumerate(_MONTHS)
        for s in series
    ]


def _render(rc: Any, data: list[dict[str, Any]]) -> dict[str, Any]:
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=600)
    assert artifact.kind == "vega_spec"
    return artifact.payload


def _rendered_domain_size(spec: dict[str, Any], axis_label_prefix: str) -> int:
    """The real Vega-Lite compiler's own count of scale domain slots.

    Renders through vl_convert (the real VL/Vega compiler, not our emitted
    spec) and reads the scale cardinality straight out of the SVG's own
    accessibility description ("X-axis for a discrete scale with N values:
    ..."), which vega-scenegraph derives from its compiled scale domain —
    the proof that VL itself, not just our emitted JSON, kept every slot.
    """
    svg = render_vega_spec(
        dict(spec),
        "svg",
        _BOARD_STYLE,
        width=600.0,
        height=None,
        is_placeholder=False,
        chart_id="chart",
    )
    root = ET.fromstring(svg)
    axis_groups = [
        g
        for g in root.iter("{http://www.w3.org/2000/svg}g")
        if g.get("aria-label", "").startswith(axis_label_prefix)
    ]
    assert axis_groups, f"no {axis_label_prefix} group found in rendered SVG"
    match = re.search(
        r"discrete scale with (\d+) values", axis_groups[0].get("aria-label", "")
    )
    assert match, (
        f"unexpected {axis_label_prefix} aria-label: {axis_groups[0].get('aria-label')!r}"
    )
    return int(match.group(1))


def _rendered_x_order(spec: dict[str, Any]) -> list[str]:
    """Each bar mark's aria description, in real rendered left-to-right x order.

    Walks vl_convert's compiled scenegraph (actual Vega layout, not our
    emitted JSON) accumulating each nested group's own x offset — a bar's
    absolute plot position is only correct once every ancestor group's
    translate is summed in, since Vega stores each item's position relative
    to its own parent group. Vega omits a zero-valued numeric field from the
    scenegraph JSON entirely, so offsets read ``.get("x", 0)`` rather than
    ``["x"]``. This is the mechanism for proving an authored ``chart.sort``
    survived into the real render, not just the emitted VL ``sort`` key.
    """
    import vl_convert as vlc

    scenegraph = vlc.vegalite_to_scenegraph(dict(spec))
    bars: list[tuple[float, str]] = []

    def walk(node: Any, x_offset: float, y_offset: float) -> None:
        if isinstance(node, dict):
            nx = x_offset + node.get("x", 0)
            ny = y_offset + node.get("y", 0)
            if node.get("marktype") == "rect":
                for item in node.get("items", []):
                    # Skip BarHoverBandFeature's invisible hover-band rects
                    # (opacity=0). They carry a real "description" -- the band
                    # self-identifies via the same aria-label as its real
                    # sibling, by design (see bar_hover_band.py's module
                    # docstring) -- so "description" presence alone no longer
                    # distinguishes them; opacity does.
                    if "description" in item and item.get("opacity") != 0:
                        bars.append((nx + item.get("x", 0), item["description"]))
                return
            for key, value in node.items():
                if key == "items":
                    walk(value, nx, ny)
                elif isinstance(value, (dict, list)):
                    walk(value, x_offset, y_offset)
        elif isinstance(node, list):
            for item in node:
                walk(item, x_offset, y_offset)

    walk(scenegraph, 0.0, 0.0)
    return [description for _, description in sorted(bars, key=lambda b: b[0])]


_NULL_PATTERNS = [
    (set(), "control — no nulls"),
    ({"2024-01-01"}, "leading null"),
    ({"2024-06-01"}, "single interior null"),
    ({"2024-05-01", "2024-06-01"}, "consecutive interior nulls"),
    ({"2024-12-01"}, "trailing null"),
    (set(_MONTHS), "all-null"),
]


@pytest.mark.parametrize(("null_months", "case"), _NULL_PATTERNS)
def test_vertical_bar_keeps_every_queried_bucket(
    make_chart, null_months: set[str], case: str
) -> None:
    """A vertical bar chart renders every time bucket its data contains, null or not."""
    data = _monthly_data(null_months)
    chart = make_chart("bar", x="month", y="revenue")
    rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = _render(rc, data)

    assert spec["config"]["mark"]["invalid"] == "break-paths-show-domains"
    rendered = _rendered_domain_size(spec, "X-axis")
    assert rendered == 12, (
        f"{case}: expected 12 x-scale domain slots from the real Vega-Lite "
        f"compiler, got {rendered}"
    )


@pytest.mark.parametrize(("null_months", "case"), _NULL_PATTERNS)
def test_vertical_grouped_bar_keeps_every_queried_bucket(
    make_chart, null_months: set[str], case: str
) -> None:
    """A grouped (color-channel, non-stacked) vertical bar keeps every bucket too."""
    data = _monthly_data(null_months, series=("Alpha", "Bravo"))
    chart = make_chart("bar", x="month", y="revenue", color="series")
    rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = _render(rc, data)

    rendered = _rendered_domain_size(spec, "X-axis")
    assert rendered == 12, (
        f"{case}: expected 12 x-scale domain slots from the real Vega-Lite "
        f"compiler, got {rendered}"
    )


@pytest.mark.parametrize(("null_months", "case"), _NULL_PATTERNS)
def test_horizontal_grouped_bar_keeps_every_queried_bucket(
    make_chart, null_months: set[str], case: str
) -> None:
    """A horizontal, series-colored bar keeps every bucket the query returned.

    This is the branch that keeps VL's default (no explicit sort) domain
    order — the one exposed to the invalid-value-filter bug; the single-
    series sort-by-measure default isn't (VL derives that domain from the
    unfiltered aggregate, not the filtered mark dataset).
    """
    data = _monthly_data(null_months, series=("Alpha", "Bravo"))
    chart = make_chart(
        "bar",
        x="month",
        y="revenue",
        color="series",
        style={"orientation": "horizontal"},
    )
    rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = _render(rc, data)

    rendered = _rendered_domain_size(spec, "Y-axis")
    assert rendered == 12, (
        f"{case}: expected 12 y-scale domain slots from the real Vega-Lite "
        f"compiler, got {rendered}"
    )


def test_horizontal_single_series_sort_by_measure_unaffected(make_chart) -> None:
    """The already-correct default-sort horizontal path is untouched by the fix.

    Single-series horizontal bar sorts its category axis by measure
    descending; that domain is derived from VL's own sort aggregate (not the
    filtered mark dataset) and already kept every bucket before this fix.
    """
    data = _monthly_data({"2024-05-01", "2024-06-01"})
    chart = make_chart(
        "bar", x="month", y="revenue", style={"orientation": "horizontal"}
    )
    rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = _render(rc, data)

    assert "domain" not in spec["encoding"]["y"].get("scale", {}), (
        "sort-by-measure horizontal bar must not carry an injected domain override"
    )
    rendered = _rendered_domain_size(spec, "Y-axis")
    assert rendered == 12


def test_nominal_categorical_bar_keeps_every_category(make_chart) -> None:
    """A plain (non-time) nominal-categorical x axis keeps a null-valued category too.

    The computed-domain approach this replaced only pinned a domain for
    bucketed-*time* axes (gated on ``detected_tu``), leaving this shape
    (a nominal field with no time bucketing at all) still exposed to VL's
    invalid-value-filtered default domain. The native ``config.mark.invalid``
    option isn't gated on a detected time unit, so it also closes this gap.
    """
    categories = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
    data = [
        {"dept": c, "revenue": None if c in ("Bravo", "Delta") else 10}
        for c in categories
    ]
    chart = make_chart("bar", x="dept", y="revenue", style={"orientation": "vertical"})
    rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = _render(rc, data)

    rendered = _rendered_domain_size(spec, "X-axis")
    assert rendered == 6, f"expected 6 x-scale domain slots, got {rendered}"


def test_vertical_bar_honors_authored_sort_on_bucketed_time_x(make_chart) -> None:
    """An authored chart.sort on a monthly bar reorders the REAL render.

    Regression for the computed-domain approach this replaced: pinning an
    explicit VL scale.domain (chronological, from the raw x values) on the
    same encoding as an authored field-based `sort` made Vega-Lite silently
    prefer the explicit domain and drop the sort — "top months by revenue"
    rendered calendar-ordered instead of revenue-ordered. The native
    ``config.mark.invalid`` fix pins no domain, so sort is free to win.
    Reads the real vl_convert-compiled bar order, not just the emitted VL
    `sort` key (a pinned-domain spec still carries that key — it's VL that
    silently ignores it).
    """
    data = _monthly_data(set())
    chart = make_chart(
        "bar", x="month", y="revenue", sort=ChartSort(by="revenue", order="desc")
    )
    rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = _render(rc, data)

    order = _rendered_x_order(spec)
    assert len(order) == 12
    # Revenue increases with month index (Jan=100 .. Dec=111), so a
    # descending-by-revenue sort renders Dec first, Jan last.
    assert order[0].startswith("⁡Dec 2024")
    assert order[-1].startswith("⁡Jan 2024")


def test_control_line_and_area_unaffected(make_chart) -> None:
    """Sibling families line/area were never exposed to this bug — pin the
    reason so a future change can't accidentally regress it.

    Line/area's bucketed-calendar x resolves to a *continuous* temporal
    scale (domain = [min, max] of the x values), unlike bar's discrete
    ordinal/nominal (band) scale (domain = the distinct category set). A
    continuous domain has no per-category "slot" for VL's invalid-value
    filter to drop — filtering out one interior row can only ever leave the
    min/max endpoints (both non-null here) unchanged. This is a structural
    guarantee of the resolved x type, so asserting the type is temporal
    (never ordinal/nominal) is the actual regression to pin — a domain
    *slot count* isn't a meaningful concept for a continuous scale.
    """
    data = _monthly_data({"2024-05-01", "2024-06-01"})
    for chart_type in ("line", "area"):
        chart = make_chart(chart_type, x="month", y="revenue")
        rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = _render(rc, data)
        x_enc = spec["encoding"]["x"]
        assert x_enc["type"] == "temporal", (
            f"{chart_type}: expected a continuous temporal x scale, got {x_enc['type']}"
        )
