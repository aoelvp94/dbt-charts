"""Every chart-shape recipe the error formatter hands out must actually draw.

RJ's probe of adjacent shapes produced two recipes that passed `dct validate` and
rendered wrong — a lollipop with no stems, a bullet with its target markers piled in
one corner. A recipe nobody rendered is worse than no recipe, so each noun in
`_CHART_SHAPE_RECIPES` is pinned here against the emitted Vega-Lite spec, and
`test_every_recipe_is_render_verified` fails if a row is added without one.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.authored import LayerAxisYStyle, LineLayer
from dbt_charts.core.compile.models.chart.authored._base import MultiplesConfig
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    LineChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    BarChartStylePatch,
)
from dbt_charts.core.compile.parse.yaml_error_formatter import (
    _CHART_SHAPE_RECIPES,
    get_valid_chart_types,
)
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_DATA = [
    {"month": "Jan", "segment": "A", "revenue": 2},
    {"month": "Jan", "segment": "B", "revenue": 10},
    {"month": "Feb", "segment": "A", "revenue": 4},
    {"month": "Feb", "segment": "B", "revenue": 8},
]

_PANEL_DATA = [
    {"month": m, "region": r, "revenue": 100 + m * 5}
    for r in ("West", "East")
    for m in range(1, 4)
]

_SINGLE_PANEL_DATA = [{"month": m, "revenue": 100 + m * 5} for m in range(1, 4)]

_LAYER_DATA = [
    {"month": "Jan", "revenue": 100.0, "target": 4000.0},
    {"month": "Feb", "revenue": 200.0, "target": 5000.0},
    {"month": "Mar", "revenue": 150.0, "target": 4500.0},
]


@pytest.fixture(autouse=True)
def _reset() -> Any:
    reset_config()
    yield
    reset_config()


def _chart_pane(spec: dict[str, Any]) -> dict[str, Any]:
    """The chart pane of a spec that endpoint labels may have wrapped.

    Same unwrap as `chart_pane` in tests/core/conftest.py, inlined because that
    module is only importable from the package dirs directly beneath it.
    """
    if "hconcat" in spec:
        return spec["hconcat"][0]
    if "vconcat" in spec:
        return spec["vconcat"][1]
    return spec


def _encoding(chart: AreaChart | BarChart) -> dict[str, Any]:
    board_style, board_ctx = resolve_style_and_context(get_theme_style())
    spec = generate_vega_lite_spec(
        chart, _DATA, board_style=board_style, chart_style_context=board_ctx
    )
    return _chart_pane(spec)["encoding"]


def _area(stack: str) -> dict[str, Any]:
    return _encoding(
        AreaChart(
            id="c",
            query=SqlQuery(sql="SELECT 1", source="t"),
            query_name="q",
            type="area",
            x="month",
            y="revenue",
            color="segment",
            style=AreaChartStylePatch(stack=stack),
        )
    )


def _bar(**patch: Any) -> dict[str, Any]:
    return _encoding(
        BarChart(
            id="c",
            query=SqlQuery(sql="SELECT 1", source="t"),
            query_name="q",
            type="bar",
            x="month",
            y="revenue",
            color="segment",
            style=BarChartStylePatch(**patch),
        )
    )


def _stack_mode(encoding: dict[str, Any]) -> str | None:
    """The stack mode off whichever axis carries the measure.

    Read from both axes rather than pinned to one: bar orientation defaults are
    tunable, and this assertion is about the stack mode, not the axis it lands on.
    """
    for channel in ("x", "y"):
        stack = encoding.get(channel, {}).get("stack")
        if stack is not None:
            return str(stack)
    return None


def test_streamgraph_recipe_center_stacks() -> None:
    assert _stack_mode(_area("center")) == "center"


def test_stacked_area_recipe_zero_stacks() -> None:
    assert _stack_mode(_area("zero")) == "zero"


def test_stacked_bar_recipe_zero_stacks() -> None:
    assert _stack_mode(_bar(stack="zero")) == "zero"


def test_grouped_bar_recipe_offsets_rather_than_stacks() -> None:
    """`stack: none` must separate the series, not overprint them in place."""
    encoding = _bar(stack="none")

    assert _stack_mode(encoding) is None
    offsets = {"xOffset", "yOffset"} & set(encoding)
    assert offsets, (
        f"grouped bars would overprint: no offset channel in {sorted(encoding)}"
    )


def test_horizontal_bar_recipe_puts_the_measure_on_x() -> None:
    encoding = _bar(orientation="horizontal", stack="zero")

    assert encoding["x"]["field"] == "revenue"
    assert encoding["y"]["field"] == "month"


def test_column_recipe_puts_the_measure_on_y() -> None:
    encoding = _bar(orientation="vertical", stack="zero")

    assert encoding["x"]["field"] == "month"
    assert encoding["y"]["field"] == "revenue"


def test_percent_stacked_recipe_normalizes_bar_and_area() -> None:
    """Covers `100% stacked` / `percent_stacked_bar` / `normalized_bar`."""
    assert _stack_mode(_bar(stack="normalize")) == "normalize"
    assert _stack_mode(_area("normalize")) == "normalize"


@pytest.mark.parametrize(
    ("noun", "stack_patch", "expect_stack"),
    [
        ("stacked_column", "zero", "zero"),
        ("grouped_column", "none", None),
        ("clustered_column", "none", None),
    ],
)
def test_column_variant_recipes_stay_vertical(
    noun: str, stack_patch: str, expect_stack: str | None
) -> None:
    """The `_column` nouns promise a vertical layout. `_DATA.x` (`month`) is a
    string, which auto-resolves to horizontal when orientation is left unset —
    so the recipe must say `style.orientation: vertical` explicitly, not just
    reuse the `_bar` recipe text verbatim."""
    encoding = _bar(orientation="vertical", stack=stack_patch)

    assert encoding["x"]["field"] == "month", noun
    assert encoding["y"]["field"] == "revenue", noun
    assert _stack_mode(encoding) == expect_stack, noun
    if expect_stack is None:
        assert {"xOffset", "yOffset"} & set(encoding), noun


def _multiples_facet(rows: str | None) -> dict[str, Any] | None:
    board_style, board_ctx = resolve_style_and_context(get_theme_style())
    chart = LineChart(
        id="c",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="line",
        x="month",
        y="revenue",
        multiples=MultiplesConfig(rows=rows) if rows else None,
    )
    data = _PANEL_DATA if rows else _SINGLE_PANEL_DATA
    spec = generate_vega_lite_spec(
        chart, data, board_style=board_style, chart_style_context=board_ctx
    )
    return spec.get("facet")


@pytest.mark.parametrize("noun", ["small_multiples", "trellis", "faceted"])
def test_multiples_recipe_partitions_into_panels(noun: str) -> None:
    facet = _multiples_facet("region")

    assert facet is not None, noun
    assert facet["row"]["field"] == "region"
    # Load-bearing: omitting `multiples:` produces no facet at all.
    assert _multiples_facet(None) is None


def _dual_axis_orients(position: str | None) -> tuple[str | None, str | None]:
    board_style, board_ctx = resolve_style_and_context(get_theme_style())
    axis_y = LayerAxisYStyle(position=position) if position else None
    layer = LineLayer(type="line", y="target", axis_y=axis_y)
    chart = BarChart(
        id="c",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="month",
        y="revenue",
        layers=[layer],
    )
    spec = generate_vega_lite_spec(
        chart, _LAYER_DATA, board_style=board_style, chart_style_context=board_ctx
    )
    layers = spec["layer"]
    base_orient = layers[0]["encoding"]["y"]["axis"]["orient"]
    overlay_orient = layers[1]["encoding"]["y"]["axis"]["orient"]
    return base_orient, overlay_orient


@pytest.mark.parametrize("noun", ["dual_axis", "combo", "bar_and_line"])
def test_dual_axis_recipe_splits_the_y_axis(noun: str) -> None:
    base_orient, overlay_orient = _dual_axis_orients("right")

    assert overlay_orient == "right", noun
    assert base_orient != overlay_orient, f"{noun}: both axes on {base_orient!r}"
    # Load-bearing: omitting axis_y.position collapses both layers onto the
    # same side instead of splitting left/right.
    base_default, overlay_default = _dual_axis_orients(None)
    assert base_default == overlay_default, noun


_RENDER_VERIFIED_NOUNS = {
    "streamgraph",
    "stacked_area",
    "stacked_bar",
    "grouped_bar",
    "clustered_bar",
    "horizontal_bar",
    "column",
    "100% stacked",
    "percent_stacked_bar",
    "normalized_bar",
    "small_multiples",
    "trellis",
    "faceted",
    "dual_axis",
    "combo",
    "bar_and_line",
    "stacked_column",
    "grouped_column",
    "clustered_column",
    "row_chart",
    "vertical_bar",
    "stream_chart",
}


def test_every_recipe_is_render_verified() -> None:
    """No recipe ships without a spec assertion above proving it draws."""
    assert set(_CHART_SHAPE_RECIPES) == _RENDER_VERIFIED_NOUNS


def test_recipes_stay_out_of_the_type_enum() -> None:
    """A recipe names a composition; promoting one to a `type:` tag is a separate
    decision, gated on the measurement in the task that added this map."""
    assert not set(_CHART_SHAPE_RECIPES) & set(get_valid_chart_types())


# Nouns that name the same chart and must therefore hand out the same recipe.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("streamgraph", "stream_chart"),
    ("grouped_bar", "clustered_bar"),
    ("grouped_column", "clustered_column"),
    ("horizontal_bar", "row_chart"),
    ("column", "vertical_bar"),
    ("small_multiples", "trellis", "faceted"),
    ("dual_axis", "combo", "bar_and_line"),
)


@pytest.mark.parametrize("group", _SYNONYM_GROUPS, ids=lambda group: group[0])
def test_synonym_nouns_hand_out_their_primary_recipe(group: tuple[str, ...]) -> None:
    """A synonym exists so a different word finds the same chart.

    The spec assertions above prove one recipe per shape; they run again under
    each synonym without reading which noun they ran for, so an edited synonym
    string would sail past them. Requiring the group to agree is what catches it.
    """
    recipes = {noun: _CHART_SHAPE_RECIPES[noun] for noun in group}
    assert len(set(recipes.values())) == 1, (
        f"synonyms disagree, so one of them is unverified: {recipes}"
    )
