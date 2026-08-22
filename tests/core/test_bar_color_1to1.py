"""Regression tests: bar chart with color 1:1 with x renders full-width bars.

When every x category has exactly one color value (color is 1:1 with x),
the VL spec must NOT emit xOffset (vertical) or yOffset (horizontal).
Emitting an offset channel creates N sub-bands per category, one occupied,
producing bars at ~1/N of slot width — razor-thin.

Control: genuine grouped bars (color M:N with x — each x has multiple colors)
must still emit the offset channel for proper side-by-side layout.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import reset_config
from dbt_charts.core.compile.models.chart.authored import MultiplesConfig
from dbt_charts.core.compile.models.chart.normalized import BarChart, Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _chart(*, orientation: str = "vertical", color: str = "orbit_class") -> Chart:
    return BarChart(
        id="test_bar",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="orbit_class",
        y="payloads",
        color=color,
        style=BarChartStylePatch(orientation=orientation),
    )


# 1:1 data: each orbit_class has exactly one color value (same field)
_DATA_COLOR_EQ_X = [
    {"orbit_class": "LEO", "payloads": 120},
    {"orbit_class": "GEO", "payloads": 45},
    {"orbit_class": "MEO", "payloads": 18},
    {"orbit_class": "HEO", "payloads": 7},
]

# 1:1 data: color is a different field but still 1:1 with x (each class → one region)
_DATA_COLOR_1TO1_DIFFERENT_FIELD = [
    {"orbit_class": "LEO", "payloads": 120, "region": "Low"},
    {"orbit_class": "GEO", "payloads": 45, "region": "High"},
    {"orbit_class": "MEO", "payloads": 18, "region": "Mid"},
    {"orbit_class": "HEO", "payloads": 7, "region": "High-Elliptic"},
]

# M:N data: each category has multiple color values → genuinely grouped
_DATA_GENUINE_GROUPED = [
    {"orbit_class": "LEO", "payloads": 80, "region": "North"},
    {"orbit_class": "LEO", "payloads": 40, "region": "South"},
    {"orbit_class": "GEO", "payloads": 30, "region": "North"},
    {"orbit_class": "GEO", "payloads": 15, "region": "South"},
]


def _get_encoding(spec: dict) -> dict:
    if "facet" in spec:
        return _get_encoding(spec["spec"])
    if "encoding" in spec:
        return spec["encoding"]
    layers = spec.get("layer", [])
    return layers[0].get("encoding", {}) if layers else {}


# ---------------------------------------------------------------------------
# Regression: color == x field → no xOffset (full-width bars)
# ---------------------------------------------------------------------------


def test_color_eq_x_vertical_no_xoffset() -> None:
    """color == x on vertical bar must not emit xOffset — bars stay full-width."""
    chart = _chart(color="orbit_class")  # color is exactly the x field
    spec = generate_vega_lite_spec(chart, _DATA_COLOR_EQ_X)
    assert "xOffset" not in _get_encoding(spec), (
        "xOffset must be absent when color == x; full-width bars expected"
    )


def test_color_eq_x_horizontal_no_yoffset() -> None:
    """color == x on horizontal bar must not emit yOffset."""
    chart = _chart(orientation="horizontal", color="orbit_class")
    spec = generate_vega_lite_spec(chart, _DATA_COLOR_EQ_X)
    assert "yOffset" not in _get_encoding(spec), (
        "yOffset must be absent when color == x (horizontal); full-width bars expected"
    )


# ---------------------------------------------------------------------------
# Regression: color 1:1 with x (different field) → no xOffset
# ---------------------------------------------------------------------------


def test_color_1to1_different_field_vertical_no_xoffset() -> None:
    """When color is a different field but 1:1 with x, no xOffset emitted."""
    chart = BarChart(
        id="test_bar",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="orbit_class",
        y="payloads",
        color="region",
    )
    spec = generate_vega_lite_spec(chart, _DATA_COLOR_1TO1_DIFFERENT_FIELD)
    assert "xOffset" not in _get_encoding(spec), (
        "xOffset must be absent when color is 1:1 with x (different fields)"
    )


def test_color_1to1_different_field_horizontal_no_yoffset() -> None:
    """Horizontal: color 1:1 with x (different field) → no yOffset."""
    chart = BarChart(
        id="test_bar",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="orbit_class",
        y="payloads",
        color="region",
        style=BarChartStylePatch(orientation="horizontal"),
    )
    spec = generate_vega_lite_spec(chart, _DATA_COLOR_1TO1_DIFFERENT_FIELD)
    assert "yOffset" not in _get_encoding(spec), (
        "yOffset must be absent when color is 1:1 with x on horizontal bar"
    )


# ---------------------------------------------------------------------------
# Control: genuine grouped bars still get the offset channel
# ---------------------------------------------------------------------------


def test_genuine_grouped_vertical_has_xoffset() -> None:
    """Genuine grouped bars (color M:N with x) must still emit xOffset."""
    chart = BarChart(
        id="test_bar",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="orbit_class",
        y="payloads",
        color="region",
        style=BarChartStylePatch(orientation="vertical"),
    )
    spec = generate_vega_lite_spec(chart, _DATA_GENUINE_GROUPED)
    assert "xOffset" in _get_encoding(spec), (
        "xOffset must be present for genuine grouped bars (color M:N with x)"
    )


def test_genuine_grouped_horizontal_has_yoffset() -> None:
    """Genuine grouped horizontal bars must still emit yOffset."""
    chart = BarChart(
        id="test_bar",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="orbit_class",
        y="payloads",
        color="region",
        style=BarChartStylePatch(orientation="horizontal"),
    )
    spec = generate_vega_lite_spec(chart, _DATA_GENUINE_GROUPED)
    assert "yOffset" in _get_encoding(spec), (
        "yOffset must be present for genuine grouped horizontal bars"
    )


# ---------------------------------------------------------------------------
# Regression: faceted grouped bar, 1:1 PER PANEL but not pooled -> no xOffset
# ---------------------------------------------------------------------------


def test_faceted_per_panel_1to1_but_pooled_not_has_no_xoffset() -> None:
    """Each panel maps one x (rank) to exactly one color (product_name), but
    different panels use different colors for the same rank -- pooled across
    panels that looks M:N (len(unique_pairs) > len(unique_x)), which would
    wrongly emit xOffset and render each panel's single bar per category at
    1/N of slot width in a different sub-band per panel. The suppression
    check must fold per panel (every panel 1:1 => suppress — see
    ``test_one_1to1_panel_does_not_suppress_offset_for_a_grouped_sibling``
    for the mixed-panel case this data shape can't distinguish, since both
    panels here are 1:1), the same grain gap-fill/validation already
    operate on."""
    chart = BarChart(
        id="test_bar",
        query=SqlQuery(sql="SELECT 1", source="test"),
        query_name="q",
        type="bar",
        x="rank",
        y="payloads",
        color="product_name",
        multiples=MultiplesConfig(columns="region"),
    )
    data = [
        {"rank": 1, "product_name": "X", "payloads": 10, "region": "North"},
        {"rank": 2, "product_name": "Y", "payloads": 20, "region": "North"},
        {"rank": 1, "product_name": "Z", "payloads": 30, "region": "South"},
        {"rank": 2, "product_name": "W", "payloads": 40, "region": "South"},
    ]
    spec = generate_vega_lite_spec(chart, data)
    assert "xOffset" not in _get_encoding(spec), (
        "xOffset must be absent when color is 1:1 with x within every panel, "
        "even though the pooled (cross-panel) view looks M:N"
    )


# ---------------------------------------------------------------------------
# Regression: mixed-panel fold — one 1:1 panel does not suppress a
# genuinely-grouped sibling panel.
# ---------------------------------------------------------------------------


def test_one_1to1_panel_does_not_suppress_offset_for_a_grouped_sibling() -> None:
    """P1 is 1:1 (each x maps to one color); P2 genuinely groups two colors
    under the same x. The suppression check must require EVERY panel to be
    1:1, not just one — otherwise P2's two bars draw full-width in the same
    band and one is completely hidden."""
    chart = BarChart.model_validate(
        {
            "id": "test_bar",
            "query_name": "q",
            "type": "bar",
            "x": "orbit_class",
            "y": "payloads",
            "color": "region",
            "multiples": {"columns": "seg"},
            "style": {"orientation": "vertical"},
        }
    )
    data = [
        {"orbit_class": "LEO", "payloads": 80, "region": "North", "seg": "P1"},
        {"orbit_class": "GEO", "payloads": 30, "region": "South", "seg": "P1"},
        {"orbit_class": "LEO", "payloads": 40, "region": "North", "seg": "P2"},
        {"orbit_class": "LEO", "payloads": 15, "region": "South", "seg": "P2"},
    ]
    spec = generate_vega_lite_spec(chart, data)
    assert "xOffset" in _get_encoding(spec), (
        "xOffset must be present when even one panel is genuinely grouped, "
        "even though a sibling panel is individually 1:1"
    )


# ---------------------------------------------------------------------------
# Regression: the 1:1 check reads the PRE-gap-fill dataset, not the
# post-gap-fill rows — a non-faceted, deliberate behavior change from the
# post-gap-fill check this branch replaced.
# ---------------------------------------------------------------------------


def test_1to1_pre_gap_fill_suppresses_offset_even_though_post_fill_looks_grouped() -> (
    None
):
    """Two source rows, each x (bucketed month) mapping to exactly one
    color: 1:1 pre-gap-fill. Ordinal bucketed-time gap-fill cross-joins
    buckets x colors regardless of whether any bucket is missing, so the
    POST-fill data has 4 rows (2 synthesized, all-null) and reads M:N. The
    1:1 check must use the pre-gap-fill dataset — the synthesized rows
    carry no real color-to-x relationship and paint nothing, so counting
    them would suppress genuine full-width rendering for no reason. This
    intentionally differs from generating against post-gap-fill rows, which
    would emit xOffset here."""
    chart = BarChart.model_validate(
        {
            "id": "test_bar",
            "query_name": "q",
            "type": "bar",
            "x": "month",
            "y": "revenue",
            "color": "region",
            "style": {"orientation": "vertical"},
        }
    )
    data = [
        {"month": "2024-01-01", "region": "A", "revenue": 10},
        {"month": "2024-02-01", "region": "B", "revenue": 20},
    ]
    spec = generate_vega_lite_spec(chart, data)
    assert spec["data"]["values"].__len__() == 4, (
        "gap-fill's bucket x color cross-join must have fired (sanity check "
        "that this test exercises the post-fill-looks-M:N shape)"
    )
    assert "xOffset" not in _get_encoding(spec), (
        "xOffset must be absent: color is 1:1 with x in the PRE-gap-fill "
        "source rows, which is what the suppression check reads"
    )


# ---------------------------------------------------------------------------
# Regression: restamp() must restore x/color when either one IS the
# multiples field — dataset.panels[*].rows never carry a partition column,
# so an unrestored lookup silently reads 0 distinct values for it.
# ---------------------------------------------------------------------------


def test_x_is_the_multiples_field_suppresses_offset_when_1to1_per_panel() -> None:
    """x == multiples.rows: x is constant within each panel by construction
    (it's the panel key), so it's stripped from panel rows same as any
    partition column. Each panel here (LEO, GEO) carries exactly ONE color
    -> trivially 1:1 with x within every panel -> the offset must be
    suppressed (full-width bars).

    This is the shape that actually distinguishes restamp() from its
    absence: without restamp() restoring "orbit_class" onto the panel's
    rows first, `x_field in row` is False for every row, so `unique_x`
    stays empty in every panel, `checked` never becomes True, and
    `_is_color_1to1_with_x` returns False regardless of the real data --
    which flips `not _is_color_1to1_with_x(...)` to True and emits xOffset
    anyway (the razor-thin-bar bug: two panels, one occupied sub-band each).
    A prior version of this test asserted xOffset PRESENT with two colors
    in one panel, which holds whether or not restamp() ran (`checked=False`
    also takes the "emit offset" branch) and could not detect the bug.
    """
    chart = BarChart.model_validate(
        {
            "id": "test_bar",
            "query_name": "q",
            "type": "bar",
            "x": "orbit_class",
            "y": "payloads",
            "color": "region",
            "multiples": {"rows": "orbit_class"},
            "style": {"orientation": "vertical"},
        }
    )
    data = [
        {"orbit_class": "LEO", "payloads": 80, "region": "North"},
        {"orbit_class": "GEO", "payloads": 40, "region": "South"},
    ]
    spec = generate_vega_lite_spec(chart, data)
    assert "xOffset" not in _get_encoding(spec), (
        "xOffset must be absent: each panel has exactly one color, "
        "trivially 1:1 with x within every panel"
    )


def test_x_is_the_multiples_field_still_detects_genuine_grouping() -> None:
    """Grouped-sibling control for the test above: x == multiples.rows, but
    the LEO panel carries TWO colors (North, South) -> genuinely grouped (1
    x value : 2 colors) within that panel -> xOffset must still fire.
    """
    chart = BarChart.model_validate(
        {
            "id": "test_bar",
            "query_name": "q",
            "type": "bar",
            "x": "orbit_class",
            "y": "payloads",
            "color": "region",
            "multiples": {"rows": "orbit_class"},
            "style": {"orientation": "vertical"},
        }
    )
    data = [
        {"orbit_class": "LEO", "payloads": 80, "region": "North"},
        {"orbit_class": "LEO", "payloads": 40, "region": "South"},
    ]
    spec = generate_vega_lite_spec(chart, data)
    assert "xOffset" in _get_encoding(spec), (
        "xOffset must be present: one x value maps to two colors within "
        "the panel, a genuine grouping"
    )


def test_color_is_the_multiples_field_always_suppresses_offset() -> None:
    """color == multiples.rows: color is constant within each panel by
    construction, so any x cardinality within a panel is trivially 1:1 with
    that one color value -- grouping by a field already split into panels
    is meaningless, must always suppress. Without restamp() restoring
    "region" onto the panel's rows first, the check would read 0 distinct
    (x, color) pairs (color_field never present in a stripped row), never
    mark the panel "checked", and leave the offset un-suppressed -- the bug
    this test would catch."""
    chart = BarChart.model_validate(
        {
            "id": "test_bar",
            "query_name": "q",
            "type": "bar",
            "x": "orbit_class",
            "y": "payloads",
            "color": "region",
            "multiples": {"rows": "region"},
            "style": {"orientation": "vertical"},
        }
    )
    data = [
        {"orbit_class": "LEO", "payloads": 80, "region": "North"},
        {"orbit_class": "GEO", "payloads": 40, "region": "North"},
    ]
    spec = generate_vega_lite_spec(chart, data)
    assert "xOffset" not in _get_encoding(spec), (
        "xOffset must be absent: color is the multiples field, so it is "
        "trivially 1:1 with x within every panel"
    )


# ---------------------------------------------------------------------------
# Sanity: color encoding still present (just no offset channel)
# ---------------------------------------------------------------------------


def test_color_eq_x_color_encoding_still_present() -> None:
    """Color encoding must still appear in the spec even when offset is suppressed."""
    chart = _chart(color="orbit_class")
    spec = generate_vega_lite_spec(chart, _DATA_COLOR_EQ_X)
    enc = _get_encoding(spec)
    assert "color" in enc, (
        "color encoding must remain present when offset is suppressed"
    )
