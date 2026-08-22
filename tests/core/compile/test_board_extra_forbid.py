"""Regression tests: AuthoredBoard rejects unknown top-level keys (extra="forbid").

Verifies that YAML typos and unknown fields at the board root raise a clear
ValidationError instead of being silently dropped.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.authored import AuthoredBoard


def test_board_rejects_unknown_key():
    with pytest.raises(ValidationError, match="bogus_key"):
        AuthoredBoard(title="t", rows=["chart1"], bogus_key="x")


def test_board_rejects_text_typo():
    """Common typo: 'tex' instead of 'text'."""
    with pytest.raises(ValidationError, match="tex"):
        AuthoredBoard(title="t", rows=["chart1"], tex="some markdown")


def test_board_valid_construction():
    board = AuthoredBoard(title="t", rows=["chart1"])
    assert board.title == "t"
    assert board.rows == ["chart1"]
