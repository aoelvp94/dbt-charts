"""Regression tests: Board.layout and Board.resolved_style are required fields.

Both were previously defaulted via `default_factory=lambda:` expressions.
After the fix they are required — constructing Board without them must raise.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.board.normalized import Board, Layout
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)


def _resolved_style() -> ResolvedStyle:
    return resolve_style(get_theme_style())


def _chart_style_context() -> ChartStyleContext:
    return resolve_chart_style_context(get_theme_style())


class TestBoardRequiredFields:
    def test_layout_is_required(self) -> None:
        """Board without layout must raise ValidationError."""
        with pytest.raises(ValidationError):
            Board(id="test", resolved_style=_resolved_style(), level=0)

    def test_resolved_style_is_required(self) -> None:
        """Board without resolved_style must raise ValidationError."""
        with pytest.raises(ValidationError):
            Board(id="test", layout=Layout(type="rows"), level=0)

    def test_level_is_required(self) -> None:
        """Board without level must raise ValidationError.

        Every Board is constructed by the normalizer (which computes level from
        titled-ancestor count) or by a call site that derives it from
        parent_level. Skipping it is a bug, not a default.
        """
        with pytest.raises(ValidationError):
            Board(
                id="test",
                layout=Layout(type="rows"),
                resolved_style=_resolved_style(),
            )

    def test_board_constructs_when_all_provided(self) -> None:
        """Providing all required fields constructs Board without error."""
        board = Board(
            id="test",
            layout=Layout(type="rows"),
            resolved_style=_resolved_style(),
            chart_style_context=_chart_style_context(),
            level=0,
        )
        assert board.level == 0
