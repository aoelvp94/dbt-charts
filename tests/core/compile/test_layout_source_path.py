"""`LayoutItem.source_path` is the absolute, dotted authoring path.

One spelling, shared with `build_source_index` keys and pydantic `loc` tuples, so a
diagnostic naming an item resolves to a line. Before this, layout items carried a
*relative* fragment in *bracket* spelling (`cols[0]`), which failed to resolve
against the source map twice over — wrong syntax and missing ancestry — and cost
inline charts their error positions.
"""

from __future__ import annotations

from dbt_charts import compile as compile_board
from dbt_charts.core.compile.models.board.normalized import Board, LayoutItem
from dbt_charts.core.compile.parse.source_map import build_source_index

_INLINE_IN_ROW = """source: mem
title: Board
rows:
  - cols:
      - title: Inline Chart
        type: bar
        query:
          sql: SELECT 'a' AS a, 1 AS b
        x: a
        y: b
"""

_NESTED_BOARD = """source: mem
title: Board
rows:
  - title: Section
    cols:
      - title: Deep Chart
        type: bar
        query:
          sql: SELECT 'a' AS a, 1 AS b
        x: a
        y: b
"""


def _source_paths(board: Board) -> list[str]:
    """Every non-empty source_path in the layout tree, depth first."""

    def walk(items: tuple[LayoutItem, ...]) -> list[str]:
        found: list[str] = []
        for item in items:
            if item.source_path:
                found.append(item.source_path)
            if item.board is not None and item.board.layout is not None:
                found.extend(walk(item.board.layout.items))
        return found

    return walk(board.layout.items) if board.layout else []


def test_inline_chart_source_path_is_absolute_and_dotted() -> None:
    """The row is a board in its own right, so both it and the chart are addressed."""
    result = compile_board(_INLINE_IN_ROW)
    assert not result.errors, result.errors
    assert _source_paths(result.board) == ["rows.0", "rows.0.cols.0"]


def test_source_path_resolves_against_the_source_map() -> None:
    """The whole point: a layout item's path is a source-map key."""
    result = compile_board(_INLINE_IN_ROW)
    source_map = build_source_index(_INLINE_IN_ROW, "f.yaml").source_map
    for path in _source_paths(result.board):
        assert path in source_map, f"{path!r} missing from source map"


def test_nested_board_and_its_children_carry_absolute_paths() -> None:
    """A nested board's own path prefixes its children — ancestry is not dropped."""
    result = compile_board(_NESTED_BOARD)
    assert not result.errors, result.errors
    paths = _source_paths(result.board)
    assert paths == ["rows.0", "rows.0.cols.0"]

    source_map = build_source_index(_NESTED_BOARD, "f.yaml").source_map
    for path in paths:
        assert path in source_map, f"{path!r} missing from source map"
