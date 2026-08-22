"""Validate-and-error-fast tests for the histogram V2 emitter.

Guards that a histogram with a missing or non-numeric x field raises
ChartDataError before reaching vl_convert, rather than crashing. Also guards
the inverse data-grain mistake: feeding a histogram pre-aggregated (one row
per x value) data instead of raw rows.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.resolve.chart._chart_rows import regroup
from dbt_charts.core.render.chart.spec import RenderBox

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.diagnostics.chart_data import ChartDataError


def _make_resolved_histogram(
    x: str | None, data: list[dict] | None = None
) -> ResolvedBarChart:
    """Build a minimal resolved histogram for emitter-level testing."""
    from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
    from dbt_charts.core.compile.models.query.normalized import ValuesQuery
    from dbt_charts.core.compile.normalize.charts import normalize_chart
    from dbt_charts.core.compile.resolve import resolve
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    board_style = resolve_chart_style_context(get_theme_style(get_default_theme_name()))
    chart_def: dict = {"type": "histogram", "query": "q"}
    if x is not None:
        chart_def["x"] = x
    if data is None:
        data = [{"price": 10, "name": "A"}, {"price": 20, "name": "B"}]
    q = {"q": ValuesQuery(rows=data)}
    compiled = normalize_chart("t", chart_def, q, sources={})
    return resolve(compiled, data, chart_style_context=board_style)  # type: ignore[return-value]


def _run_emit(chart: ResolvedBarChart, data: list) -> None:
    from dbt_charts.core.render.chart.emitters.bar import BarEmitter

    BarEmitter().emit(chart, _DEFAULT_BOX, regroup((), data))


def test_histogram_missing_x_raises_chart_data_error() -> None:
    """Histogram with no x field must raise ChartDataError, not crash vl_convert."""
    from dbt_charts.core.diagnostics.codes_render import ERR_HISTOGRAM_NON_NUMERIC

    data = [{"price": 10, "name": "A"}]
    chart = _make_resolved_histogram(x=None)
    with pytest.raises(ChartDataError) as exc_info:
        _run_emit(chart, data)
    assert exc_info.value.code is ERR_HISTOGRAM_NON_NUMERIC
    assert "requires a numeric x field" in str(exc_info.value)


def test_histogram_non_numeric_x_raises_chart_data_error() -> None:
    """Histogram with a nominal (string) x field must raise ChartDataError."""
    from dbt_charts.core.diagnostics.codes_render import ERR_HISTOGRAM_NON_NUMERIC

    data = [{"price": 10, "name": "A"}, {"price": 20, "name": "B"}]
    chart = _make_resolved_histogram(x="name")
    with pytest.raises(ChartDataError) as exc_info:
        _run_emit(chart, data)
    assert exc_info.value.code is ERR_HISTOGRAM_NON_NUMERIC
    assert "name" in str(exc_info.value)


def test_histogram_decimal_x_does_not_raise() -> None:
    """Histogram over a Decimal column (BigQuery NUMERIC, DuckDB DECIMAL) must
    render — Decimal is numeric, not nominal (regression: the column was
    misclassified nominal and raised ERR-HISTOGRAM-NON-NUMERIC)."""
    from decimal import Decimal

    data = [
        {"price": Decimal("10.50"), "name": "A"},
        {"price": Decimal("20.25"), "name": "B"},
    ]
    chart = _make_resolved_histogram(x="price")
    _run_emit(chart, data)  # must not raise


def test_histogram_preaggregated_data_raises_chart_data_error() -> None:
    """A histogram fed one-row-per-x pre-aggregated data (e.g. the output of
    `SELECT days_to_hire, count(*) AS hires ... GROUP BY 1`) must raise, not
    silently hand each already-counted bucket to Vega-Lite's own count
    aggregate (which would recount every bucket as 1, discarding the real
    count carried in the unused `hires` column). `days_to_hire` is a gapless
    run of whole numbers (1..5) — exactly what `GROUP BY` over an integer
    bucket produces."""
    from dbt_charts.core.diagnostics.codes_render import ERR_HISTOGRAM_PREAGGREGATED

    data = [{"days_to_hire": n, "hires": n * 3} for n in range(1, 6)]
    chart = _make_resolved_histogram(x="days_to_hire", data=data)
    with pytest.raises(ChartDataError) as exc_info:
        _run_emit(chart, data)
    assert exc_info.value.code is ERR_HISTOGRAM_PREAGGREGATED
    assert "days_to_hire" in str(exc_info.value)
    assert "type: bar" in str(exc_info.value)


def test_histogram_preaggregated_data_with_multiple_aggregates_raises() -> None:
    """A pre-aggregated table with more than one leftover aggregate column
    (`SELECT days, count(*) AS c, avg(salary) AS s ... GROUP BY 1`) must still
    raise — the guard must not require *exactly* one spare column, or a
    second aggregate column silently defeats it."""
    from dbt_charts.core.diagnostics.codes_render import ERR_HISTOGRAM_PREAGGREGATED

    data = [
        {"days": n, "hires": n * 2, "avg_salary": 50000 + n * 1000} for n in range(1, 8)
    ]
    chart = _make_resolved_histogram(x="days", data=data)
    with pytest.raises(ChartDataError) as exc_info:
        _run_emit(chart, data)
    assert exc_info.value.code is ERR_HISTOGRAM_PREAGGREGATED


def test_histogram_gapless_run_below_minimum_length_does_not_raise() -> None:
    """A gapless integer run shorter than `_MIN_RUN_FOR_GROUP_BY_SHAPE` (4
    rows, one below the 5-row floor) must not raise — short runs are too
    common by chance in genuine raw data to act on."""
    data = [{"days_to_hire": n, "hires": n * 3} for n in range(1, 5)]  # 4 rows
    chart = _make_resolved_histogram(x="days_to_hire", data=data)
    _run_emit(chart, data)  # must not raise


def test_histogram_raw_rows_with_duplicates_does_not_raise() -> None:
    """A genuine raw-row histogram with a leftover numeric column — many rows
    sharing x values, the shape histograms are meant to bin — must render
    unaffected by the new guard (the duplicates rule out a gapless run)."""
    data = [{"days_to_hire": n % 7, "employee_id": n} for n in range(30)]
    chart = _make_resolved_histogram(x="days_to_hire", data=data)
    _run_emit(chart, data)  # must not raise


def test_histogram_continuous_x_with_one_spare_column_does_not_raise() -> None:
    """The false-positive this guard must never produce: a genuine raw-row
    histogram over a *continuous* measure (the primary histogram use case —
    every value naturally distinct) with exactly one other numeric column
    (an id, a second measure). Zero duplicates in a continuous field is
    routine, not evidence of pre-aggregation — only a gapless whole-number
    run is. 200 raw rows, nothing aggregated."""
    data = [
        {"price": 50 + (n * 7.31) % 40, "weight": 1.0 + (n * 3.7) % 9}
        for n in range(200)
    ]
    chart = _make_resolved_histogram(x="price", data=data)
    _run_emit(chart, data)  # must not raise


def test_histogram_continuous_x_with_two_spare_columns_does_not_raise() -> None:
    """Same shape as above with a wider raw fact table (`SELECT * FROM
    orders`) — several extra attributes, continuous revenue x — must also
    render unaffected."""
    data = [
        {"revenue": 10.0 + n * 0.13, "order_id": n, "quantity": n % 3 + 1}
        for n in range(50)
    ]
    chart = _make_resolved_histogram(x="revenue", data=data)
    _run_emit(chart, data)  # must not raise


def test_histogram_sparse_distinct_integers_with_spare_column_does_not_raise() -> None:
    """Distinct, *gapped* integers — not a dense run — with a spare numeric
    column must not raise. This is the case that actually exercises
    `_forms_gapless_integer_run`'s final range check (every other test in
    this file is decided by an earlier branch: too-short, has-duplicates, or
    non-integer) — e.g. `SELECT order_id, total_cents FROM orders` where
    order totals are distinct but scattered, not a dense sequence."""
    data = [
        {"order_id": order_id, "total_cents": total_cents}
        for order_id, total_cents in enumerate(
            [199, 450, 1099, 2599, 3100, 7650, 12000], start=1
        )
    ]
    chart = _make_resolved_histogram(x="total_cents", data=data)
    _run_emit(chart, data)  # must not raise


def test_histogram_no_extra_column_does_not_raise() -> None:
    """A histogram over just its x column — no leftover numeric field at all
    — must not trip the guard regardless of row count or duplicates."""
    data = [{"days_to_hire": n} for n in range(1, 6)]  # 5 rows, all distinct
    chart = _make_resolved_histogram(x="days_to_hire", data=data)
    _run_emit(chart, data)  # must not raise
