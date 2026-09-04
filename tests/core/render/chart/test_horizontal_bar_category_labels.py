"""Regression: horizontal bar categorical y-axis must not parity-drop labels."""

from __future__ import annotations

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.emitters._cartesian import (
    effective_horizontal_bar_category_count,
    min_height_for_horizontal_bar_categories,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec, render_chart
from dbt_charts.core.render.chart.vl_field_maps import effective_bar_size

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())


def test_horizontal_bar_spec_never_parity_drops_y_labels(make_chart) -> None:
    owners = [f"owner-{i}" for i in range(13)]
    data = [{"owner": o, "count": i + 1} for i, o in enumerate(owners)]
    chart = make_chart(
        "bar",
        x="owner",
        y="count",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    _rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = generate_vega_lite_spec(chart, data, height=300)
    y_axis = spec["encoding"]["y"].get("axis", {})
    assert y_axis.get("labelOverlap") is False
    assert y_axis.get("labelAngle") == 0
    assert spec["height"] is not None and spec["height"] > 300


def test_horizontal_bar_svg_includes_every_category_label(make_chart) -> None:
    owners = ["dave", "christoph", "sr-engineer", "akankaluga"]
    data = [{"owner": o, "count": 10 - i} for i, o in enumerate(owners)]
    chart = make_chart(
        "bar",
        x="owner",
        y="count",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    svg = render_chart(
        chart,
        _BOARD_STYLE,
        _BOARD_CTX,
        data,
        format="svg",
        width=400,
        height=300,
    )
    for owner in owners:
        assert owner in svg, f"missing y-axis label for {owner!r} in rendered SVG"


def test_min_height_scales_with_category_count(make_chart) -> None:
    chart = make_chart("bar", x="owner", y="count")
    resolved = resolve(
        chart,
        [{"owner": "a", "count": 1}, {"owner": "b", "count": 2}],
        chart_style_context=_BOARD_CTX,
    )
    h2 = min_height_for_horizontal_bar_categories(
        2, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    h8 = min_height_for_horizontal_bar_categories(
        8, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    assert h8 > h2
    assert h2 > 0


def test_effective_horizontal_bar_category_count_narrows_when_x_is_the_rows_facet_field() -> (
    None
):
    """A rows-only facet whose ``x`` IS the facet field holds exactly one
    category per panel, by construction of the row split — the count must
    reflect that, not the whole-dataset union."""
    categories = [f"cat-{i}" for i in range(5)]
    data = [{"cat": c, "count": i + 1} for i, c in enumerate(categories)]

    chart = BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "count",
            "multiples": {"rows": "cat"},
            "style": {"orientation": "horizontal"},
        }
    )
    resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
    assert effective_horizontal_bar_category_count(resolved, data, None) == 1

    unfaceted = BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "count",
            "style": {"orientation": "horizontal"},
        }
    )
    unfaceted_resolved = resolve(unfaceted, data, chart_style_context=_BOARD_CTX)
    assert effective_horizontal_bar_category_count(
        unfaceted_resolved, data, None
    ) == len(categories)


def test_horizontal_bar_rows_facet_on_its_own_x_does_not_inflate_height() -> None:
    """Regression: WARN_LAYOUT_MIN_EXCEEDS_HEIGHT and the render-time height
    floor both used to budget the whole-dataset category union for every
    panel, even when the row facet already narrows each panel to one
    category — inflating a card's height 3x past what the panel it actually
    paints needs, and misinstructing the author to grow an already-
    sufficient height. Compares against faceting on an unrelated field
    whose every panel still carries the FULL category domain (same row
    cardinality, same total category count, but genuinely not narrowed —
    not just differently named) to isolate the effect of the narrowing
    itself, not a name coincidence."""
    categories = [f"cat-{i}" for i in range(6)]

    narrowed_data = [{"cat": c, "count": i + 1} for i, c in enumerate(categories)]
    narrowed_chart = BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "count",
            "multiples": {"rows": "cat"},
            "style": {"orientation": "horizontal"},
        }
    )
    narrowed_spec = generate_vega_lite_spec(narrowed_chart, narrowed_data, height=300)

    # "grp" has the same 6-value cardinality as "cat" (matching row_cardinality
    # above), but every grp panel carries ALL 6 categories — a genuine full
    # domain per panel, not a differently-named alias for the same 1:1 split.
    unnarrowed_data = [
        {"cat": c, "grp": g, "count": i + 1}
        for g in categories
        for i, c in enumerate(categories)
    ]
    unnarrowed_chart = BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "count",
            "multiples": {"rows": "grp"},
            "style": {"orientation": "horizontal"},
        }
    )
    unnarrowed_spec = generate_vega_lite_spec(
        unnarrowed_chart, unnarrowed_data, height=300
    )

    assert narrowed_spec["spec"]["height"] < unnarrowed_spec["spec"]["height"]


def test_resolve_chart_postcondition_horizontal_bar_overlap_is_allow(
    make_chart,
) -> None:
    chart = make_chart(
        "bar",
        x="region",
        y="value",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    data = [{"region": "East", "value": 1}]
    # V2 resolves overlap at render time via resolve_axis_x_overlap; check the
    # emitted spec rather than the intermediate resolved model.
    spec = generate_vega_lite_spec(
        chart, data, board_style=_BOARD_STYLE, chart_style_context=_BOARD_CTX
    )
    y_axis = spec.get("encoding", {}).get("y", {}).get("axis", {})
    assert y_axis.get("labelOverlap") is False
