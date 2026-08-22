"""Regression tests for geo clip + out-of-projection warning.

Bug: albersUsa point_map with a Pacific coordinate (e.g. Kwajalein lat=9, lon=168)
renders a stray dot at the chart's top-left corner instead of being suppressed.

Three fixes ship together:
  1. clip: true on the circle mark — VL clips geo-positioned marks to the
     projection's viewport so out-of-bounds points never bleed into unrelated
     chart regions.
  2. Data filtering in the emitter — out-of-projection rows are dropped from
     spec.data before Vega-Lite sees them, because clip:true cannot hide a mark
     whose CENTER is exactly at (0,0) (the corner quarter still paints).
  3. POINT_MAP_OUT_OF_PROJECTION warning — tells the author N point(s) fall
     outside the projection bounds so they can fix the data or switch projection.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import PointMapChart
from dbt_charts.core.diagnostics import WARN_POINT_MAP_OUT_OF_PROJECTION
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec
from dbt_charts.core.render.warnings import (
    WarningContext,
    point_map_out_of_projection as detector,
)

from ._board_utils import make_test_resolved_board, make_test_resolved_chart

# US points clearly within albersUsa (continental US)
_US_ROWS: list[dict[str, Any]] = [
    {"lat": 34.05, "lng": -118.25},  # Los Angeles
    {"lat": 40.71, "lng": -74.01},  # New York
    {"lat": 41.88, "lng": -87.63},  # Chicago
]

# Mix: 3 US + 1 Pacific (Kwajalein Atoll, Marshall Islands)
_MIXED_ROWS: list[dict[str, Any]] = [
    *_US_ROWS,
    {"lat": 9.0, "lng": 168.0},  # Kwajalein — outside albersUsa projection
]


def _make_point_map(projection: str = "albersUsa") -> PointMapChart:
    return PointMapChart(
        id="c1",
        type="point_map",
        query_name="q",
        latitude="lat",
        longitude="lng",
        projection=projection,
    )


def _make_ctx(chart: PointMapChart, rows: list[dict[str, Any]]) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={},  # point_map not in vega_specs; detector reads chart_results
    )


# ---------------------------------------------------------------------------
# 1. clip: true on the point mark
# ---------------------------------------------------------------------------


def test_point_map_mark_has_clip_true() -> None:
    """Circle mark for a point_map must carry clip: true.

    Without clip, albersUsa clamped out-of-projection points to the top-left
    corner of the chart canvas instead of hiding them.
    """
    chart = _make_point_map()
    spec = generate_vega_lite_spec(chart, _MIXED_ROWS)

    # No background — spec is a direct circle mark (not layered)
    assert spec["mark"]["type"] == "circle", f"Expected circle mark, got {spec['mark']}"
    assert spec["mark"].get("clip") is True, (
        f"clip: true missing from point_map mark; mark = {spec['mark']}"
    )


def test_point_map_with_background_circle_layer_has_clip_true(make_chart) -> None:
    """Even when a geo background is present, the circle layer must have clip: true."""
    chart = make_chart(
        "point_map",
        latitude="lat",
        longitude="lng",
        geo_source="us-states",
    )
    spec = generate_vega_lite_spec(chart, _MIXED_ROWS)

    assert "layer" in spec, "Expected layered spec with background"
    circle_layer = spec["layer"][1]
    assert circle_layer["mark"]["type"] == "circle"
    assert circle_layer["mark"].get("clip") is True, (
        f"clip: true missing from circle layer; mark = {circle_layer['mark']}"
    )

    # The row filter runs before the background branch, so the layered path
    # must also carry filtered data — not just the direct (no-background) path.
    data_values: list[dict[str, Any]] = circle_layer["data"]["values"]
    lons = {row["lng"] for row in data_values}
    assert 168.0 not in lons, (
        f"Kwajalein should be filtered from the layered circle layer too; "
        f"data = {data_values}"
    )


# ---------------------------------------------------------------------------
# 2. POINT_MAP_OUT_OF_PROJECTION warning
# ---------------------------------------------------------------------------


def test_fires_on_out_of_projection_point() -> None:
    """albersUsa + Pacific coordinate → POINT_MAP_OUT_OF_PROJECTION fires."""
    chart = _make_point_map("albersUsa")
    ctx = _make_ctx(chart, _MIXED_ROWS)
    warnings = detector.detect(ctx)

    assert len(warnings) == 1
    w = warnings[0]
    assert w.code == WARN_POINT_MAP_OUT_OF_PROJECTION.code
    assert w.chart == "c1"
    assert "1" in w.message  # 1 out-of-projection point
    assert "albersUsa" in w.message
    assert w.fix is not None


def test_no_warning_for_all_us_points() -> None:
    """All points within albersUsa bounds → no warning."""
    chart = _make_point_map("albersUsa")
    ctx = _make_ctx(chart, _US_ROWS)
    assert detector.detect(ctx) == []


def test_no_warning_for_unbounded_projection() -> None:
    """mercator covers the whole world — no out-of-projection check applied."""
    chart = _make_point_map("mercator")
    ctx = _make_ctx(chart, _MIXED_ROWS)
    assert detector.detect(ctx) == []


def test_warning_count_reflects_multiple_out_of_projection_points() -> None:
    """Warning message reports the correct count of out-of-projection points."""
    pacific_rows = [
        {"lat": 9.0, "lng": 168.0},  # Kwajalein
        {"lat": -17.7, "lng": 168.3},  # Vanuatu
        {"lat": 34.05, "lng": -118.25},  # LA — in bounds
    ]
    chart = _make_point_map("albersUsa")
    ctx = _make_ctx(chart, pacific_rows)
    warnings = detector.detect(ctx)

    assert len(warnings) == 1
    assert "2" in warnings[0].message


def test_no_warning_when_lat_lon_fields_missing_from_data() -> None:
    """If rows don't contain lat/lon keys, detector skips gracefully (no crash)."""
    chart = _make_point_map("albersUsa")
    rows = [{"something_else": 1}]
    ctx = _make_ctx(chart, rows)
    # Should not raise; rows with missing lat/lon columns are skipped
    warnings = detector.detect(ctx)
    assert warnings == []


# ---------------------------------------------------------------------------
# 3. Emitter drops out-of-projection rows from spec.data
# ---------------------------------------------------------------------------


def test_out_of_projection_row_filtered_from_emitted_spec() -> None:
    """Kwajalein row must not appear in the emitted VL data.values for albersUsa.

    clip: true cannot hide a mark centered exactly at (0,0) — the inner quarter
    still paints. Pre-filtering the data ensures nothing is placed at (0,0).
    """
    chart = _make_point_map("albersUsa")
    spec = generate_vega_lite_spec(chart, _MIXED_ROWS)

    data_values: list[dict[str, Any]] = spec["data"]["values"]
    lons = {row["lng"] for row in data_values}
    assert 168.0 not in lons, (
        f"Kwajalein (lon=168) should have been filtered out; data = {data_values}"
    )
    # In-projection rows must survive
    assert len(data_values) == len(_US_ROWS)


def test_in_projection_rows_not_filtered() -> None:
    """All-US rows are kept intact — filtering must not drop in-projection points."""
    chart = _make_point_map("albersUsa")
    spec = generate_vega_lite_spec(chart, _US_ROWS)

    data_values: list[dict[str, Any]] = spec["data"]["values"]
    assert len(data_values) == len(_US_ROWS)


def test_unbounded_projection_does_not_filter() -> None:
    """mercator is unbounded — all rows including Pacific coords pass through."""
    chart = _make_point_map("mercator")
    spec = generate_vega_lite_spec(chart, _MIXED_ROWS)

    data_values: list[dict[str, Any]] = spec["data"]["values"]
    lons = {row["lng"] for row in data_values}
    assert 168.0 in lons, "mercator should not filter any rows"
    assert len(data_values) == len(_MIXED_ROWS)


def test_neighborhood_geo_source_relies_on_clip_not_prefilter(make_chart) -> None:
    """sf-neighborhoods (a shipped regional geo_source) resolves to `mercator`.

    The repo already ships tightly-bounded neighborhood-level geo sets
    (sf-neighborhoods, nyc-neighborhoods, chicago-neighborhoods,
    la-neighborhoods — see geo_defaults.yml). They all use projection type
    `mercator` with a `center`/`scale` zoom, not `albersUsa`. Unlike albersUsa,
    mercator never collapses an out-of-region coordinate to a degenerate point
    on the viewport boundary — it's a continuous projection, so a far-away
    point (here, New York) projects to a real off-canvas pixel and is fully
    hidden by `clip: true` alone. That's why BOUNDED_PROJECTIONS only lists
    albersUsa: pre-filtering exists for the (0,0)-collapse defect, which these
    regional mercator sources don't have.
    """
    chart = make_chart(
        "point_map",
        latitude="lat",
        longitude="lng",
        geo_source="sf-neighborhoods",
    )

    rows = [
        {"lat": 37.7749, "lng": -122.4194},  # San Francisco — in region
        {"lat": 40.71, "lng": -74.01},  # New York — far outside the SF frame
    ]
    spec = generate_vega_lite_spec(chart, rows)

    circle_layer = spec["layer"][1] if "layer" in spec else spec
    proj = circle_layer.get("projection", spec.get("projection"))
    assert proj["type"] == "mercator", f"expected mercator projection, got {proj}"
    assert circle_layer["mark"].get("clip") is True

    data_values: list[dict[str, Any]] = circle_layer["data"]["values"]
    assert len(data_values) == len(rows), (
        f"mercator-based regional sources are not pre-filtered; data = {data_values}"
    )
