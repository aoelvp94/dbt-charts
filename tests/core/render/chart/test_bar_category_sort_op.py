"""A bar's authored category sort orders by the sort column's own value.

Vega-Lite folds a category's rows into one aggregate before applying a field
sort, and on a stacked mark it infers ``sum``. A category carrying fewer rows
than its neighbors then ranks by row count rather than by the authored key:
with ``release_seq`` 1/2/3 and one release holding a single series, the axis
reads Aug 25, Feb 26, Nov 25 (sums 2, 3, 4). Bar pins the aggregate instead —
``min``, the category's own value — except where the sort column IS the
measure on a stacked chart, which is a real sort-by-stacked-total.

The order is read out of the real compiled render (vl_convert), not the
emitted JSON: the emitted ``sort`` key can be right while VL's own aggregate
inference still draws something else.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart
from dbt_charts.core.render.chart.x_domain import rendered_x_domain
from dbt_charts.core.render.converters.chart import render_vega_spec

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# The reported shape: release_seq is constant within a release, and Feb 26
# carries one series where the others carry two.
_RAGGED_ROWS: list[dict[str, Any]] = [
    {"release": "Aug 25", "series": "Alpha", "issues": 10, "release_seq": 1},
    {"release": "Aug 25", "series": "Bravo", "issues": 20, "release_seq": 1},
    {"release": "Nov 25", "series": "Alpha", "issues": 30, "release_seq": 2},
    {"release": "Nov 25", "series": "Bravo", "issues": 40, "release_seq": 2},
    {"release": "Feb 26", "series": "Alpha", "issues": 50, "release_seq": 3},
]


def _render(rc: Any, data: list[dict[str, Any]]) -> dict[str, Any]:
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=600)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    assert isinstance(spec, dict)
    return spec


def _rendered_category_domain(spec: dict[str, Any], axis: str) -> list[str]:
    """The band scale's values in real rendered order.

    Read from the axis group's own accessibility description, which
    vega-scenegraph writes from the compiled scale domain — so it states what
    Vega-Lite drew, not what our emitted JSON asked for.
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
    labels = [
        g.get("aria-label", "")
        for g in root.iter("{http://www.w3.org/2000/svg}g")
        if g.get("aria-label", "").startswith(f"{axis}-axis")
    ]
    assert labels, f"no {axis}-axis group found in the rendered SVG"
    match = re.search(r"discrete scale with \d+ values: (.*)$", labels[0])
    assert match, f"unexpected {axis}-axis aria-label: {labels[0]!r}"
    return match.group(1).split(", ")


def _stacked_bar(
    make_chart: Any, sort_by: str, order: str, orientation: str = "vertical"
) -> Any:
    chart = make_chart(
        "bar",
        x="release",
        y="issues",
        color="series",
        sort={"by": sort_by, "order": order},
        style={"stack": "zero", "orientation": orientation},
    )
    return resolve(chart, _RAGGED_ROWS, chart_style_context=_BOARD_CTX)


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("asc", ["Aug 25", "Nov 25", "Feb 26"]),
        ("desc", ["Feb 26", "Nov 25", "Aug 25"]),
    ],
)
def test_stacked_bar_with_ragged_rows_orders_by_the_authored_key(
    make_chart: Any, order: str, expected: list[str]
) -> None:
    """The releases follow release_seq, not each release's row count."""
    spec = _render(_stacked_bar(make_chart, "release_seq", order), _RAGGED_ROWS)
    assert _rendered_category_domain(spec, "X") == expected


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("asc", ["Aug 25", "Nov 25", "Feb 26"]),
        ("desc", ["Feb 26", "Nov 25", "Aug 25"]),
    ],
)
def test_horizontal_stacked_bar_with_ragged_rows_orders_by_the_authored_key(
    make_chart: Any, order: str, expected: list[str]
) -> None:
    """The horizontal emitter's own categorical (VL y) sort, same shape."""
    rc = _stacked_bar(make_chart, "release_seq", order, "horizontal")
    spec = _render(rc, _RAGGED_ROWS)
    assert _rendered_category_domain(spec, "Y") == expected


def test_stacked_bar_sorted_by_its_measure_keeps_stacked_total_order(
    make_chart: Any,
) -> None:
    """Sorting a stack by its own measure is sorting by the stacked total.

    Totals are 30 / 70 / 50; the per-category minima are 10 / 30 / 50, so the
    two orders differ and this pins ``sum`` rather than merely passing under
    either aggregate.
    """
    spec = _render(_stacked_bar(make_chart, "issues", "asc"), _RAGGED_ROWS)
    assert _rendered_category_domain(spec, "X") == ["Aug 25", "Feb 26", "Nov 25"]


def test_grouped_bar_server_domain_matches_the_render(make_chart: Any) -> None:
    """An unstacked grouped bar's read-back domain agrees with what Vega draws.

    ``rendered_x_domain`` reproduces the rendered order from the emitted
    encoding for every downstream consumer (the endpoint rail, band value
    labels, the overlay reconciler). A grouped bar is not a stacking mark, so
    that reproduction has to fold with the category's own value too.
    """
    chart = make_chart(
        "bar",
        x="release",
        y="issues",
        color="series",
        sort={"by": "release_seq", "order": "asc"},
        style={"stack": "none", "orientation": "vertical"},
    )
    rc = resolve(chart, _RAGGED_ROWS, chart_style_context=_BOARD_CTX)
    spec = _render(rc, _RAGGED_ROWS)
    read_back = rendered_x_domain(spec["encoding"]["x"], _RAGGED_ROWS, [], "chart")
    assert read_back == _rendered_category_domain(spec, "X")
    assert read_back == ["Aug 25", "Nov 25", "Feb 26"]
