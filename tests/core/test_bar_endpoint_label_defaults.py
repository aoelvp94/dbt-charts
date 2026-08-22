"""What the bar labelling default does, and every case it steps aside for.

A bar names its series directly when it can: a vertical stack labels the last
column's segment midpoints, a horizontal stack takes the top-row rail. It falls
back to a legend wherever the rail could not name every series — see
``_bar_endpoint_labels_for_stack``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.authored._data_table import (
    ChartDataTablePerSeries,
)
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.chart.resolved import ResolvedBarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    BarChartStylePatch,
    EndpointLabelsConfigPatch,
    LegendStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

_Row = dict[str, str | int]

# Well clear of the tiny tier, whose own rule swaps endpoint labels for a top
# legend regardless of orientation.
_WIDTH = 900.0


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_config()
    yield
    reset_config()


# Temporal x → vertical orientation; discrete x → horizontal.
_TEMPORAL_DATA: list[_Row] = [
    {"month": "2024-01-01", "revenue": 10, "stage": "New"},
    {"month": "2024-02-01", "revenue": 8, "stage": "New"},
    {"month": "2024-01-01", "revenue": 5, "stage": "Won"},
    {"month": "2024-02-01", "revenue": 3, "stage": "Won"},
]

_DISCRETE_DATA: list[_Row] = [
    {"region": "East", "revenue": 10, "stage": "New"},
    {"region": "West", "revenue": 8, "stage": "New"},
    {"region": "East", "revenue": 5, "stage": "Won"},
    {"region": "West", "revenue": 3, "stage": "Won"},
]

_DISCRETE_DATA_SERIES_ABSENT_AT_ANCHOR: list[_Row] = [
    {"region": "East", "revenue": 10, "stage": "New"},
    {"region": "West", "revenue": 8, "stage": "New"},
    {"region": "West", "revenue": 3, "stage": "Won"},
]

_NEGATIVE_DATA: list[_Row] = [
    {"month": "2024-01-01", "revenue": 10, "stage": "New"},
    {"month": "2024-02-01", "revenue": 8, "stage": "New"},
    {"month": "2024-01-01", "revenue": -5, "stage": "Won"},
    {"month": "2024-02-01", "revenue": 3, "stage": "Won"},
]


def _resolved(
    x: str,
    data: list[_Row],
    orientation: str | None = None,
    stack: str = "zero",
    endpoint_labels: EndpointLabelsConfigPatch | None = None,
) -> ResolvedBarChart:
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x=x,
        y="revenue",
        color="stage",
        style=BarChartStylePatch(
            stack=stack,
            orientation=orientation,
            # Omitted rather than passed as None: the patch model rejects an
            # explicit None here.
            **({"endpoint_labels": endpoint_labels} if endpoint_labels else {}),
        ),
    )
    resolved = resolve(
        chart, data, resolve_chart_style_context(get_theme_style()), width=_WIDTH
    )
    assert isinstance(resolved, ResolvedBarChart)
    return resolved


def test_vertical_stacked_bar_labels_its_series_directly() -> None:
    resolved = _resolved("month", _TEMPORAL_DATA)

    assert resolved.orientation == "vertical"
    assert resolved.style.endpoint_labels.visible is True


def test_vertical_stacked_bar_drops_the_legend_for_endpoint_labels() -> None:
    """Direct labelling replaces the colour legend, as it does for line/area."""
    resolved = _resolved("month", _TEMPORAL_DATA)

    assert resolved.legend.visible is False


def test_horizontal_bar_gets_the_same_default() -> None:
    """Horizontal bars route to their own label rail, not the vertical cascade.

    The rail places one label per series above the top categorical row. It
    reads cleanly at low series counts and overprints once the labels are
    wider than their segments — an open question, not settled behaviour, so
    this pins only that the default reaches both orientations alike.
    """
    resolved = _resolved("region", _DISCRETE_DATA)

    assert resolved.orientation == "horizontal"
    assert resolved.style.endpoint_labels.visible is True


def test_grouped_bar_keeps_its_legend() -> None:
    """Grouped bars label poorly: every series' last bar ends at a similar
    height, so the cascade compresses all the labels into one another. A
    legend is the honest treatment.
    """
    resolved = _resolved("month", _TEMPORAL_DATA, stack="none")

    assert resolved.stack == "none"
    assert resolved.style.endpoint_labels.visible is False
    assert resolved.legend.visible is not False


def test_grouped_bar_labels_directly_when_the_author_asks_for_it() -> None:
    """Every disqualifier steers the *default*. An author who writes
    ``endpoint_labels.visible: true`` on a grouped bar gets the bar-top labels
    that shape has always rendered, and the legend steps aside for them.
    """
    resolved = _resolved(
        "month",
        _TEMPORAL_DATA,
        stack="none",
        endpoint_labels=EndpointLabelsConfigPatch(visible=True),
    )

    assert resolved.stack == "none"
    assert resolved.style.endpoint_labels.visible is True
    assert resolved.legend.visible is False


def test_author_opt_in_reaches_the_render_layer_raise() -> None:
    """A negative measure is disqualified because render refuses to place a
    cumulative midpoint across zero. An explicit opt-in resolves ``True``
    anyway, so the author meets that refusal by name rather than a chart that
    quietly declines to label.
    """
    resolved = _resolved(
        "month",
        _NEGATIVE_DATA,
        endpoint_labels=EndpointLabelsConfigPatch(visible=True),
    )

    assert resolved.style.endpoint_labels.visible is True


def test_negative_data_bar_keeps_its_legend() -> None:
    """A stacked bar with a negative measure would hit the render-layer
    negative-value raise if endpoint labels defaulted on — the default must
    steer around that failure, not into it.
    """
    resolved = _resolved("month", _NEGATIVE_DATA)

    assert resolved.style.endpoint_labels.visible is False
    assert resolved.legend.visible is not False


def test_horizontal_series_absent_at_anchor_keeps_its_legend() -> None:
    """The horizontal rail has no dodge resolver for a series missing at its
    anchor row (``_every_series_reaches_the_anchor_row``) — its label would
    land on the zero-width seam and overprint the neighbour. The theme's bar
    legend override is what keeps this chart from carrying neither rail nor
    legend.
    """
    resolved = _resolved("region", _DISCRETE_DATA_SERIES_ABSENT_AT_ANCHOR)

    assert resolved.orientation == "horizontal"
    assert resolved.style.endpoint_labels.visible is False
    assert resolved.legend.visible is not False


def test_grouped_bar_legend_sits_on_top_untitled() -> None:
    """Top horizontal, matching the left-to-right reading order of the bars
    themselves. The title auto-hides at top+horizontal, and the entry count is
    left to the renderer rather than clamped to the compact wrap.
    """
    resolved = _resolved("month", _TEMPORAL_DATA, stack="none")

    assert resolved.legend.position == "top"
    assert resolved.legend.direction == "horizontal"
    assert resolved.legend.title.visible is False
    assert resolved.legend.columns == 0


def test_author_can_still_turn_the_legend_off() -> None:
    """Top placement decides *where* a legend goes, not *whether* there is one.

    Grouped bars get a legend by default because they cannot endpoint-label.
    An author who says this chart carries none outranks that.
    """
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="month",
        y="revenue",
        color="stage",
        style=BarChartStylePatch(
            stack="none",
            legend=LegendStylePatch.model_validate({"visible": False}),
        ),
    )
    resolved = resolve(
        chart,
        _TEMPORAL_DATA,
        resolve_chart_style_context(get_theme_style()),
        width=_WIDTH,
    )
    assert isinstance(resolved, ResolvedBarChart)

    assert resolved.legend.visible is False


_ONE_POINT_PER_SERIES: list[_Row] = [
    {"month": "2024-01-01", "revenue": 10, "stage": "New"},
    {"month": "2024-02-01", "revenue": 8, "stage": "Won"},
]

_SERIES_MISSING_FROM_LAST_COLUMN: list[_Row] = [
    {"month": "2024-01-01", "revenue": 10, "stage": "New"},
    {"month": "2024-01-01", "revenue": 5, "stage": "Won"},
    {"month": "2024-02-01", "revenue": 8, "stage": "New"},
]


def test_stacked_bar_keeps_its_rail_when_a_series_misses_the_last_column() -> None:
    """A gap in the anchor column is not a reason to change naming mechanism.

    The absent series anchors on its zero-height stack seam, so it stays named
    and the reader still counts as many names as colours. Disqualifying here
    would switch a chart between rail and legend on a data gap alone — and
    series that start late are ordinary in a stack.
    """
    resolved = _resolved("month", _SERIES_MISSING_FROM_LAST_COLUMN)

    assert resolved.style.endpoint_labels.visible is True


_SINGLE_SERIES_TWO_COLUMNS: list[_Row] = [
    {"month": "2024-01-01", "revenue": 10, "stage": "New"},
    {"month": "2024-02-01", "revenue": 8, "stage": "New"},
]

_ALL_NULL_MEASURE: list[_Row] = [
    {"month": "2024-01-01", "revenue": None, "stage": "New"},
    {"month": "2024-01-01", "revenue": None, "stage": "Won"},
    {"month": "2024-02-01", "revenue": None, "stage": "New"},
]


def test_single_series_bar_falls_back_to_a_legend() -> None:
    """One series across many columns stacks against nothing.

    Its segment spans the whole bar, so a rail would be one name pinned beside
    one band — the legend it already had, moved. Pinned so an edit to the
    disqualifier can't flip it silently.
    """
    resolved = _resolved("month", _SINGLE_SERIES_TWO_COLUMNS)

    assert resolved.style.endpoint_labels.visible is False


def test_all_null_measure_falls_back_to_a_legend() -> None:
    """No row carries a value, so no column stacks and nothing is drawn.

    The rail anchors on segment geometry; with no segments anywhere it would
    pile every name on the baseline of an empty plot.
    """
    resolved = _resolved("month", _ALL_NULL_MEASURE)

    assert resolved.style.endpoint_labels.visible is False


def test_one_point_per_series_falls_back_to_a_legend() -> None:
    """`color:` equal to `x:` gives every series a single, distinct column.

    Nothing stacks, so there are no segments to name and the rail would
    degenerate into a badly-laid-out legend. This is the shape a
    category-coloured bar takes, and it must not sprout a one-entry label.
    """
    resolved = _resolved("month", _ONE_POINT_PER_SERIES)

    assert resolved.style.endpoint_labels.visible is False


_TWO_ROWS: list[_Row] = [
    {"region": "East", "revenue": 10, "stage": "New"},
    {"region": "West", "revenue": 8, "stage": "New"},
    {"region": "West", "revenue": 5, "stage": "Won"},
]


def _horizontal(sort: object = None, stack: str = "zero") -> ResolvedBarChart:
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="region",
        y="revenue",
        color="stage",
        sort=sort,
        style=BarChartStylePatch(stack=stack),
    )
    resolved = resolve(
        chart, _TWO_ROWS, resolve_chart_style_context(get_theme_style()), width=_WIDTH
    )
    assert isinstance(resolved, ResolvedBarChart)
    assert resolved.orientation == "horizontal"
    return resolved


def test_sorted_horizontal_stack_still_labels_directly() -> None:
    """A `sort:` moves the anchor row rather than disqualifying the rail.

    The rail anchors on the first row of the *rendered* domain, so it follows
    the sort instead of refusing it — sorting a stacked bar by value is
    ordinary authoring.
    """
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="region",
        y="revenue",
        color="stage",
        sort={"by": "revenue", "order": "desc"},
        style=BarChartStylePatch(stack="zero"),
    )
    resolved = resolve(
        chart,
        _DISCRETE_DATA,
        resolve_chart_style_context(get_theme_style()),
        width=_WIDTH,
    )
    assert isinstance(resolved, ResolvedBarChart)

    assert resolved.orientation == "horizontal"
    assert resolved.style.endpoint_labels.visible is True


def test_sorted_vertical_stack_still_labels_directly() -> None:
    """Same on the vertical pane, which anchors on the last rendered column."""
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="month",
        y="revenue",
        color="stage",
        sort={"by": "revenue", "order": "desc"},
        style=BarChartStylePatch(stack="zero", orientation="vertical"),
    )
    resolved = resolve(
        chart,
        _TEMPORAL_DATA,
        resolve_chart_style_context(get_theme_style()),
        width=_WIDTH,
    )
    assert isinstance(resolved, ResolvedBarChart)

    assert resolved.orientation == "vertical"
    assert resolved.style.endpoint_labels.visible is True


def test_centre_stacked_horizontal_keeps_its_legend() -> None:
    """The horizontal rail anchors on the cumulative axis, not centre-stack's."""
    resolved = _horizontal(stack="center")

    assert resolved.style.endpoint_labels.visible is False


def test_horizontal_rail_steps_aside_when_a_series_misses_its_anchor_row() -> None:
    """'Won' appears only in the last row; the horizontal rail anchors on the first.

    The vertical rail seats that series on its zero-width seam and lets the
    label cascade push it clear. The horizontal rail has no cascade in V2, so
    the seam label would overprint its neighbour — a legend is the honest
    treatment until the dodge resolver lands. Vertical is unaffected: see
    `test_stacked_bar_keeps_its_rail_when_a_series_misses_the_last_column`.
    """
    resolved = _horizontal()

    assert resolved.style.endpoint_labels.visible is False
    assert resolved.legend.visible is not False


def test_per_series_data_table_already_names_the_series() -> None:
    """A `data_table` with a `per_series:` entry prints one row per series,
    labelled in that series' own ink. The rail would name them twice — and it
    costs the plot both height and the axis side it needs.
    """
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="month",
        y="revenue",
        color="stage",
        data_table=[ChartDataTablePerSeries(per_series="revenue")],
        style=BarChartStylePatch(stack="zero"),
    )
    resolved = resolve(
        chart,
        _TEMPORAL_DATA,
        resolve_chart_style_context(get_theme_style()),
        width=_WIDTH,
    )
    assert isinstance(resolved, ResolvedBarChart)

    assert resolved.style.endpoint_labels.visible is False


def test_histogram_never_draws_an_endpoint_label_rail() -> None:
    """A histogram bins x and aggregates y to a count.

    It reads the bar family's style slot, so the theme default would switch a
    rail on — but there is no per-row value for it to anchor to, and the
    positions would correspond to no rendered mark.
    """
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="histogram",
        x="revenue",
        y="revenue",
        color="stage",
    )
    resolved = resolve(
        chart,
        _TEMPORAL_DATA,
        resolve_chart_style_context(get_theme_style()),
        width=_WIDTH,
    )

    assert resolved.style.endpoint_labels.visible is False


def test_sort_by_a_non_numeric_column_keeps_its_legend() -> None:
    """Both rails reproduce Vega-Lite's domain order by totalling the sort
    column per category. Vega-Lite concatenates strings instead, an order that
    cannot be mirrored — so the default steps aside rather than anchoring the
    rail on a row Vega-Lite does not draw on top.
    """
    chart = BarChart(
        id="t",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        type="bar",
        x="region",
        y="revenue",
        color="stage",
        sort={"by": "region", "order": "desc"},
        style=BarChartStylePatch(stack="zero"),
    )
    resolved = resolve(
        chart,
        _DISCRETE_DATA,
        resolve_chart_style_context(get_theme_style()),
        width=_WIDTH,
    )
    assert isinstance(resolved, ResolvedBarChart)

    assert resolved.style.endpoint_labels.visible is False
    assert resolved.legend.visible is not False
