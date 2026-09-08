"""Tests for text render output format."""

from unittest.mock import MagicMock

from dbt_charts.core.compile.models.board.normalized import Board, Layout, LayoutItem
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.render.renderer import render

from ._board_utils import _default_chart_style_context, _default_resolved_style


def _make_executor(data: list[dict]) -> MagicMock:
    """Create a mock executor that returns the given data for any chart.

    ``cache_hit_ats`` must be a real (empty) list, not the default MagicMock
    attribute: render() now draws the board for every format (not just svg),
    and the svg footer/timestamp code iterates this attribute directly.
    """
    executor = MagicMock(spec=Executor)
    executor.execute_chart.return_value = data
    executor.cache_hit_ats = []
    return executor


def _make_board(charts: list[Chart], title: str = "Test Board") -> Board:
    """Create a Board with chart items in a rows layout."""
    items = [
        LayoutItem(type="chart", chart=chart, width=600, height=300) for chart in charts
    ]
    return Board(
        id="test-board",
        title=title,
        layout=Layout(type="rows", items=items, width=600, height=600),
        resolved_style=_default_resolved_style(),
        chart_style_context=_default_chart_style_context(),
        level=1,
    )


class TestTextFormat:
    def test_board_title_as_heading(self, make_chart):
        """Board title renders as markdown H1."""
        data = [{"month": "Jan", "revenue": 100}, {"month": "Feb", "revenue": 200}]
        chart = make_chart("bar", x="month", y="revenue", title="Revenue")
        board = _make_board([chart], title="Revenue Dashboard")
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert isinstance(result, str)
        assert "# Revenue Dashboard" in result

    def test_chart_type_in_heading(self, make_chart):
        """Chart title renders as H2 with chart type."""
        data = [{"month": "Jan", "revenue": 100}]
        chart = make_chart("bar", x="month", y="revenue", title="Sales Chart")
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "## Sales Chart (bar)" in result

    def test_field_mappings(self, make_chart):
        """Field mappings (x, y) are shown."""
        data = [{"month": "Jan", "revenue": 100}]
        chart = make_chart("bar", x="month", y="revenue")
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "x: month" in result
        assert "y: revenue" in result

    def test_row_count(self, make_chart):
        """Data summary includes row count."""
        data = [{"x": i, "y": i * 10} for i in range(5)]
        chart = make_chart("line", x="x", y="y")
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "5 rows" in result

    def test_numeric_range(self, make_chart):
        """Numeric columns show min-max range."""
        data = [
            {"month": "Jan", "revenue": 100},
            {"month": "Feb", "revenue": 500},
            {"month": "Mar", "revenue": 1200},
        ]
        chart = make_chart("line", x="month", y="revenue")
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "100" in result
        assert "1200" in result

    def test_categorical_few_values(self, make_chart):
        """String columns with <=5 values show the values."""
        data = [
            {"region": "East", "sales": 100},
            {"region": "West", "sales": 200},
            {"region": "North", "sales": 150},
        ]
        chart = make_chart("bar", x="region", y="sales")
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "East" in result
        assert "West" in result
        assert "North" in result

    def test_categorical_many_values(self, make_chart):
        """String columns with >5 values show distinct count only."""
        data = [{"city": f"City{i}", "pop": i * 1000} for i in range(8)]
        chart = make_chart("bar", x="city", y="pop")
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "8 distinct" in result

    def test_kpi_chart(self, make_chart):
        """KPI charts show value = formatted number."""
        data = [{"revenue": 4200000}]
        chart = make_chart("kpi", value="revenue", x=None, y=None)
        board = _make_board([chart])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "kpi" in result.lower()
        # KPI uses chart.title (or empty); the formatted value carries the data.
        assert "4,200,000" in result

    def test_nested_board(self, make_chart):
        """Nested boards use deeper heading levels."""
        data = [{"x": 1, "y": 2}]
        chart = make_chart("bar")
        inner_board = Board(
            id="inner",
            title="Inner Section",
            layout=Layout(
                type="rows",
                items=[LayoutItem(type="chart", chart=chart, width=600, height=300)],
                width=600,
                height=300,
            ),
            resolved_style=_default_resolved_style(),
            chart_style_context=_default_chart_style_context(),
            level=2,
        )
        outer_board = Board(
            id="outer",
            title="Outer Dashboard",
            layout=Layout(
                type="rows",
                items=[
                    LayoutItem(type="board", board=inner_board, width=600, height=300)
                ],
                width=600,
                height=600,
            ),
            resolved_style=_default_resolved_style(),
            chart_style_context=_default_chart_style_context(),
            level=1,
        )
        executor = _make_executor(data)

        result = render(outer_board, executor, format="text").output

        assert "# Outer Dashboard" in result
        assert "## Inner Section" in result

    def test_multiple_charts(self, make_chart):
        """Multiple charts in a board all appear."""
        data = [{"x": 1, "y": 2}]
        chart1 = make_chart("bar", id="chart1", title="Chart One")
        chart2 = make_chart("line", id="chart2", title="Chart Two")
        board = _make_board([chart1, chart2])
        executor = _make_executor(data)

        result = render(board, executor, format="text").output

        assert "Chart One" in result
        assert "Chart Two" in result
        assert "(bar)" in result
        assert "(line)" in result

    def test_max_rows_per_query_summary_shows_truncation(self, make_chart):
        """The data summary states the truncation instead of a bare row count."""
        data = [{"month": f"m{i}", "revenue": i} for i in range(7)]
        board = _make_board([make_chart("bar", x="month", y="revenue")])
        executor = _make_executor(data)

        result = render(board, executor, format="text", max_rows_per_query=2).output

        assert "first 1 and last 1 of 7 rows" in result
