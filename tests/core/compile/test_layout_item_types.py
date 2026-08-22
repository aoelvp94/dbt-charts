"""Tests for typed layout item models: ChartRef, dict[str, AuthoredChart].

authored.py and the corresponding updates to normalize/layout.py and compiler.py.
Also covers rejection of removed ChartRef `chart:` layout shorthand.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.errors import ParseError
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.chart.authored import _SharedChartFields
from dbt_charts.core.compile.normalize.dispatch import normalize_board
from dbt_charts.core.compile.parse.parser import parse_yaml


class TestChartRefRejected:
    """YAML using removed `chart:` layout shorthand raises a clear ParseError."""

    def test_chart_ref_in_rows_raises_parse_error(self):
        content = """
title: Test
charts:
  c1:
    type: bar
    query:
      sql: "SELECT x, y FROM t"
      source: test
    x: x
    y: y
rows:
  - chart: c1
    height: 600
"""
        with pytest.raises(ParseError) as exc_info:
            parse_yaml(content)
        msg = str(exc_info.value)
        assert "chart:" in msg
        assert "rows:" in msg or "nested board" in msg.lower()

    def test_chart_ref_with_width_in_cols_raises_parse_error(self):
        content = """
title: Test
charts:
  c1:
    type: bar
    query:
      sql: "SELECT x, y FROM t"
      source: test
    x: x
    y: y
cols:
  - chart: c1
    width: 30%
"""
        with pytest.raises(ParseError) as exc_info:
            parse_yaml(content)
        msg = str(exc_info.value)
        assert "chart:" in msg

    def test_bare_chart_name_in_rows_still_valid(self):
        """Bare chart name (not ChartRef) must still work."""
        content = """
title: Test
charts:
  c1:
    type: bar
    query:
      sql: "SELECT x, y FROM t"
      source: test
    x: x
    y: y
rows:
  - c1
"""
        board = parse_yaml(content)
        assert board.rows == ["c1"]

    def test_nested_board_with_height_still_valid(self):
        """Nested board (AuthoredBoard with height + rows) is the replacement and must work."""
        content = """
title: Test
charts:
  c1:
    type: bar
    query:
      sql: "SELECT x, y FROM t"
      source: test
    x: x
    y: y
rows:
  - height: 600
    rows:
      - c1
"""
        board = parse_yaml(content)
        assert board.rows is not None
        assert len(board.rows) == 1
        nested = board.rows[0]
        assert isinstance(nested, AuthoredBoard)
        assert nested.height == 600


class TestNamedChartDict:
    """dict[str, AuthoredChart] in rows is accepted when the value is a valid AuthoredChart."""

    def test_named_chart_parses_in_authored_board_rows(self):
        """A dict with one key mapping to a AuthoredChart is valid in rows."""
        board = AuthoredBoard.model_validate(
            {
                "title": "T",
                "queries": {"q": "SELECT 1"},
                "rows": [
                    {"my_chart": {"query": "q", "type": "bar", "x": "m", "y": "r"}}
                ],
            }
        )
        assert len(board.rows) == 1
        row_item = board.rows[0]
        assert isinstance(row_item, dict)
        assert "my_chart" in row_item
        assert isinstance(row_item["my_chart"], _SharedChartFields)

    def test_bogus_dict_rejected_in_authored_board_rows(self):
        """A dict that is not ChartRef or dict[str,AuthoredChart] is rejected."""
        with pytest.raises(ValidationError):
            AuthoredBoard.model_validate(
                {
                    "title": "T",
                    "rows": [{"bogus_key": "value"}],
                }
            )


class TestInlineSectionHeader:
    """Title-only AuthoredBoard items in layout act as section headers."""

    def test_title_only_in_rows_parses_as_authored_board(self):
        """{title: X} in rows parses as AuthoredBoard, not AuthoredChart or ChartRef."""
        board = AuthoredBoard.model_validate(
            {
                "title": "T",
                "queries": {"q": "SELECT 1"},
                "rows": [{"title": "My Section"}],
            }
        )
        assert len(board.rows) == 1
        assert isinstance(board.rows[0], AuthoredBoard)
        assert board.rows[0].title == "My Section"

    def test_title_only_authored_board_text_is_none(self):
        """A title-only inline board has text=None (not empty string)."""
        board = AuthoredBoard(title="Q1 Results")
        assert board.text is None

    def test_section_header_resolves_to_board_item(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        content = """
title: Test Board
charts:
  revenue:
    type: bar
    query:
      sql: "SELECT month, revenue FROM t"
      source: test
    x: month
    y: revenue
rows:
  - title: Q1 Results
  - revenue
"""
        board = parse_yaml(content)
        compiled = normalize_board(
            board, base_dir=local_project(root=tmp_path).directory()
        )
        assert len(compiled.layout.items) == 2
        header_item = compiled.layout.items[0]
        assert header_item.type == "board"
        assert header_item.board.title == "Q1 Results"

    def test_section_header_with_description_compiles(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        content = """
title: Test Board
charts:
  revenue:
    type: bar
    query:
      sql: "SELECT month, revenue FROM t"
      source: test
    x: month
    y: revenue
rows:
  - title: Q1 Results
    description: "Sales in Q1"
  - revenue
"""
        board = parse_yaml(content)
        compiled = normalize_board(
            board, base_dir=local_project(root=tmp_path).directory()
        )
        header_item = compiled.layout.items[0]
        assert header_item.type == "board"
        assert header_item.board.title == "Q1 Results"
        assert header_item.description == "Sales in Q1"
