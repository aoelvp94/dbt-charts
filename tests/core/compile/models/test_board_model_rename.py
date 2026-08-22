"""Pins the compile-triple rename contract: AuthoredBoard/Board/ResolvedBoard/
BoardPatch import from models/board/ with their invariants intact."""

from __future__ import annotations

import dataclasses


def test_new_board_symbols_import() -> None:
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard
    from dbt_charts.core.compile.models.board.normalized import Board
    from dbt_charts.core.compile.models.board.patch import BoardPatch
    from dbt_charts.core.compile.models.board.resolved import ResolvedBoard

    assert AuthoredBoard.model_config.get("extra") == "forbid"
    assert Board.model_config.get("extra") == "forbid"
    assert dataclasses.is_dataclass(ResolvedBoard)
    assert BoardPatch is not None
