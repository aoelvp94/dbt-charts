"""Tests for compile-side sizing helpers: get_board_gap, parse_dimension.

Both are pure functions of Board/theme config or authored strings — no query
data, no executor, no render-phase measurement — so they live in
compile/sizing.py rather than render/sizing.py.
"""

import dataclasses

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.board.normalized import Board, Layout
from dbt_charts.core.compile.sizing import get_board_gap, parse_dimension

from .._board_utils import make_test_board


def _with_gap_override(layout_type: str, gap: float) -> Board:
    """Build a Board whose resolved_style overrides the gap for one layout type.

    Uses model_copy to build a distinctive resolved style (per the
    distinctive-value-plus-propagation test pattern) rather than pinning a
    theme literal.
    """
    board = make_test_board(layout=Layout(type=layout_type))
    rs = board.resolved_style
    new_layout_section = getattr(rs.layout, layout_type).model_copy(update={"gap": gap})
    new_layout = rs.layout.model_copy(update={layout_type: new_layout_section})
    board.resolved_style = dataclasses.replace(rs, layout=new_layout)
    return board


class TestGetBoardGap:
    """get_board_gap dispatches to the correct config key per layout type."""

    def _make_board(self, layout_type: str, card_gap: bool = False) -> Board:
        return make_test_board(layout=Layout(type=layout_type), card_gap=card_gap)

    def test_card_gap_always_zero(self) -> None:
        for layout_type in ("rows", "cols", "grid"):
            board = self._make_board(layout_type, card_gap=True)
            assert get_board_gap(board) == 0.0, (
                f"card_gap=True should be 0 for {layout_type}"
            )

    def test_rows_returns_config_gap(self) -> None:
        board = self._make_board("rows")
        assert get_board_gap(board) == float(get_theme_style().layout.rows.gap)

    def test_cols_returns_config_gap(self) -> None:
        board = self._make_board("cols")
        assert get_board_gap(board) == float(get_theme_style().layout.cols.gap)

    def test_grid_returns_config_gap(self) -> None:
        board = self._make_board("grid")
        assert get_board_gap(board) == float(get_theme_style().layout.grid.gap)

    def test_tabs_returns_zero(self) -> None:
        board = self._make_board("tabs")
        assert get_board_gap(board) == 0.0

    def test_rows_gap_reads_board_resolved_style_not_global_theme(self) -> None:
        """A board-resolved style.layout.rows.gap override must not be dropped.

        Regression for the audit finding: get_board_gap took `board` but ignored
        its resolved_style, always reading the global default theme.
        """
        distinctive_gap = 12345.0
        board = _with_gap_override("rows", distinctive_gap)
        assert get_board_gap(board) == distinctive_gap
        assert get_board_gap(board) != float(get_theme_style().layout.rows.gap)

    def test_cols_gap_reads_board_resolved_style_not_global_theme(self) -> None:
        distinctive_gap = 12345.0
        board = _with_gap_override("cols", distinctive_gap)
        assert get_board_gap(board) == distinctive_gap
        assert get_board_gap(board) != float(get_theme_style().layout.cols.gap)

    def test_grid_gap_reads_board_resolved_style_not_global_theme(self) -> None:
        distinctive_gap = 12345.0
        board = _with_gap_override("grid", distinctive_gap)
        assert get_board_gap(board) == distinctive_gap
        assert get_board_gap(board) != float(get_theme_style().layout.grid.gap)


class TestParseDimension:
    """parse_dimension parses percentage/pixel dimension strings to floats."""

    def test_percent_is_fraction_of_total(self) -> None:
        assert parse_dimension("30%", 200.0) == 60.0

    def test_px_suffix_returns_exact_pixels(self) -> None:
        assert parse_dimension("150px", 200.0) == 150.0

    def test_bare_number_returns_pixels(self) -> None:
        assert parse_dimension("150", 200.0) == 150.0

    def test_none_returns_none(self) -> None:
        assert parse_dimension(None, 200.0) is None

    def test_unparsable_returns_none(self) -> None:
        assert parse_dimension("not-a-dimension", 200.0) is None
