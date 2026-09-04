"""``rendered_x_domain`` records the domains it leaves in paint order.

The warning detector reads this capture rather than re-deriving the decision,
so these tests pin the one place the decision is made.
"""

from __future__ import annotations

from dbt_charts.core.render.chart.x_domain import rendered_x_domain
from dbt_charts.core.render.chart.x_domain_paint_order import (
    collect_x_domain_paint_orders,
)

_X_ENC = {"field": "month", "type": "nominal"}


def _rows(values):
    return [{"month": v, "y": 1.0} for v in values]


def test_unorderable_union_records_the_paint_order() -> None:
    with collect_x_domain_paint_orders() as captured:
        domain = rendered_x_domain(
            _X_ENC,
            _rows(["Jan", "Mar", "May"]),
            [("month", _rows(["Feb", "Apr", "Jun"]))],
            chart_id="c1",
        )
    assert domain == ["Jan", "Mar", "May", "Feb", "Apr", "Jun"]
    assert captured["c1"].x_field == "month"
    assert captured["c1"].layer_only == ("Feb", "Apr", "Jun")


def test_non_monotonic_base_records_the_paint_order() -> None:
    """Orderable values, unordered base — the base's ORDER BY still wins."""
    with collect_x_domain_paint_orders() as captured:
        domain = rendered_x_domain(
            _X_ENC,
            _rows(["2024-05", "2024-01", "2024-03"]),
            [("month", _rows(["2024-02"]))],
            chart_id="c1",
        )
    assert domain == ["2024-05", "2024-01", "2024-03", "2024-02"]
    assert captured["c1"].layer_only == ("2024-02",)


def test_orderable_union_records_nothing() -> None:
    with collect_x_domain_paint_orders() as captured:
        rendered_x_domain(
            _X_ENC,
            _rows(["2024-01", "2024-03", "2024-05"]),
            [("month", _rows(["2024-02", "2024-04"]))],
            chart_id="c1",
        )
    assert captured == {}


def test_layer_adding_nothing_records_nothing() -> None:
    with collect_x_domain_paint_orders() as captured:
        rendered_x_domain(
            _X_ENC,
            _rows(["Jan", "Feb", "Mar"]),
            [("month", _rows(["Feb"]))],
            chart_id="c1",
        )
    assert captured == {}


def test_authored_sort_records_nothing() -> None:
    """An authored sort states the order — nothing is left unstated."""
    with collect_x_domain_paint_orders() as captured:
        rendered_x_domain(
            {**_X_ENC, "sort": {"field": "y", "order": "descending"}},
            _rows(["Jan", "Mar", "May"]),
            [("month", _rows(["Feb"]))],
            chart_id="c1",
        )
    assert captured == {}


def test_an_empty_base_with_one_layer_query_records_nothing() -> None:
    """One query's own ORDER BY is an order — there is nothing to paint over.

    A base returning no rows contributes no domain, so the union is exactly
    that single layer query's own row order. Reporting paint order there would
    tell an author to join onto a shared spine they already have.
    """
    with collect_x_domain_paint_orders() as captured:
        domain = rendered_x_domain(
            _X_ENC,
            [],
            [("month", _rows(["Jan", "Mar", "Feb"]))],
            chart_id="c1",
        )
    assert domain == ["Jan", "Mar", "Feb"]
    assert captured == {}


def test_an_empty_base_with_two_layer_queries_still_records() -> None:
    """Two independently-ordered result sets — first-seen is paint order again."""
    with collect_x_domain_paint_orders() as captured:
        rendered_x_domain(
            _X_ENC,
            [],
            [("month", _rows(["Jan", "Mar"])), ("month", _rows(["Feb"]))],
            chart_id="c1",
        )
    assert captured["c1"].layer_only == ("Jan", "Mar", "Feb")


def test_no_chart_id_records_nothing() -> None:
    """``_layer_band_anchor`` reads the order without owning the chart."""
    with collect_x_domain_paint_orders() as captured:
        rendered_x_domain(
            _X_ENC,
            _rows(["Jan", "Mar"]),
            [("month", _rows(["Feb"]))],
            chart_id=None,
        )
    assert captured == {}


def test_no_sink_is_noop() -> None:
    assert rendered_x_domain(
        _X_ENC,
        _rows(["Jan", "Mar"]),
        [("month", _rows(["Feb"]))],
        chart_id="c1",
    ) == ["Jan", "Mar", "Feb"]


def test_two_layer_columns_on_one_query_over_an_empty_base_record_nothing() -> None:
    """Two layers reading the same diverging query contribute one order between
    them, so an empty base plus both of them is that query's ORDER BY — not
    paint order. Counting columns instead of contributing datasets would fire.
    """
    rows = [{"m": "Feb"}, {"m": "Apr"}, {"m": "Jun"}]
    with collect_x_domain_paint_orders() as captured:
        domain = rendered_x_domain(
            {"field": "m", "type": "nominal"},
            [],
            [("m", rows), ("m", rows)],
            chart_id="c",
        )
    assert domain == ["Feb", "Apr", "Jun"]
    assert captured == {}
