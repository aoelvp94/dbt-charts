"""Tests for terminal rendering functionality."""

import logging

import pytest

from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.render.terminal_charts import (
    _terminal_y_field,
    render_chart_terminal,
    render_kpi_terminal,
    render_table_terminal,
)


def test_render_kpi_terminal(make_chart):
    """Test KPI rendering to terminal."""
    chart = make_chart("kpi", value="revenue", label="Total Revenue")

    data = [{"revenue": 1234567.89}]

    output = render_kpi_terminal(chart, data, "Total Revenue")
    # Terminal must consume the finalized title argument; deriving a fallback
    # here would reopen the normalized-to-render boundary.
    assert "Total Revenue" in output
    assert "1234567" in output or "1,234,567" in output


def test_render_kpi_terminal_raises_on_missing_column(make_chart):
    """value: is always a column reference — missing column raises ChartDataError."""
    chart = make_chart("kpi", value="revenue", label="Rev")
    data = [{"total": 100}]
    with pytest.raises(ChartDataError, match="revenue.*not found|not found.*revenue"):
        render_kpi_terminal(chart, data, "Rev")


def test_render_kpi_terminal_honors_empty_final_display_title(make_chart):
    chart = make_chart("kpi", value="revenue", label="{{ region }}")

    output = render_kpi_terminal(
        chart,
        [{"revenue": 100}],
        "",
    )

    assert "{{ region }}" not in output


def test_render_table_terminal(make_chart):
    """Test table rendering to terminal."""
    chart = make_chart("table", title="Test Table")

    data = [
        {"name": "Alice", "age": 30, "score": 95.5},
        {"name": "Bob", "age": 25, "score": 87.0},
    ]

    output = render_table_terminal(chart, data, "Test Table")
    assert "Test Table" in output or "table" in output.lower()
    # Should contain column names or data
    assert "Alice" in output or "Bob" in output or "name" in output.lower()


def test_render_chart_terminal_bar(make_chart):
    """Test bar chart rendering to terminal."""
    chart = make_chart("bar", x="month", y="revenue", title="Revenue by Month")

    data = [
        {"month": "Jan", "revenue": 1000},
        {"month": "Feb", "revenue": 1500},
        {"month": "Mar", "revenue": 1200},
    ]

    # This will use fallback if plotext is not available
    output = render_chart_terminal(chart, data, "Revenue by Month", width=80, height=20)
    assert output  # Should produce some output
    assert "Revenue by Month" in output or "chart" in output.lower()


def test_render_chart_terminal_uses_final_display_title(make_chart):
    chart = make_chart("bar", x="month", y="revenue", title="{{ region }} revenue")
    data = [{"month": "Jan", "revenue": 1000}]

    output = render_chart_terminal(
        chart,
        data,
        "West revenue",
        width=80,
        height=20,
    )

    assert "West revenue" in output
    assert "{{ region }}" not in output


def test_render_chart_terminal_line(make_chart):
    """Test line chart rendering to terminal."""
    chart = make_chart("line", x="date", y="value", title="Value Over Time")

    data = [
        {"date": "2024-01-01", "value": 10},
        {"date": "2024-01-02", "value": 15},
        {"date": "2024-01-03", "value": 12},
    ]

    output = render_chart_terminal(chart, data, "Value Over Time", width=80, height=20)
    assert output  # Should produce some output


def test_render_chart_terminal_empty_data(make_chart):
    """Test chart rendering with empty data."""
    chart = make_chart("bar", x="x", y="y")

    data = []

    output = render_chart_terminal(chart, data, "")
    assert output  # Should handle empty data gracefully


def test_terminal_y_field_warns_when_dropping_extra_series(make_chart, caplog):
    """Terminal rendering should warn when a multi-series chart is reduced to one y."""
    chart = make_chart("line", x="month", y=["revenue", "cost", "profit"])

    with caplog.at_level(logging.WARNING):
        y_field = _terminal_y_field(chart)

    assert y_field == "revenue"
    assert "only supports one y series" in caplog.text
    assert "dropping 2 additional series" in caplog.text


def test_render_chart_item_terminal_isolates_a_bare_dbt_charts_error(make_chart):
    """A DbtChartsError from the terminal chart pipeline degrades to an inline line.

    Pre-existing and unrelated to resolve-time isolation: the terminal branch
    of ``render()`` sits outside every try/except, so an exception escaping
    here propagated all the way out as a crash. ExecutionError/RenderError were
    already softened one level further out; a *bare* DbtChartsError was not,
    which is why that is the family this pins.
    """
    from unittest.mock import MagicMock

    from dbt_charts.core.diagnostics import ERR_INTERNAL
    from dbt_charts.core.diagnostics.base import DbtChartsError
    from dbt_charts.core.execute.executor import Executor
    from dbt_charts.core.render.terminal import render_chart_item_terminal

    chart = make_chart("bar", x="month", y="revenue")
    executor = MagicMock(spec=Executor)
    executor.execute_chart.side_effect = DbtChartsError.from_code(
        ERR_INTERNAL, message="terminal pipeline blew up"
    )

    output = render_chart_item_terminal(chart, executor, {}, 80, 20)

    assert output.startswith(f"[Error rendering {chart.id}:")
    assert "terminal pipeline blew up" in output


def test_render_chart_item_terminal_still_isolates_bug_class_errors(make_chart):
    """The four bug-class types stay caught — this widened, it did not replace."""
    from unittest.mock import MagicMock

    from dbt_charts.core.execute.executor import Executor
    from dbt_charts.core.render.terminal import render_chart_item_terminal

    chart = make_chart("bar", x="month", y="revenue")
    executor = MagicMock(spec=Executor)
    executor.execute_chart.side_effect = ValueError("bad value")

    output = render_chart_item_terminal(chart, executor, {}, 80, 20)

    assert output.startswith(f"[Error rendering {chart.id}:")
