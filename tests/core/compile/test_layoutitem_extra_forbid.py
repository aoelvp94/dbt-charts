"""Regression tests: LayoutItem rejects unknown keys (extra="forbid").

Verifies that typos like `chrt:` or `bogus_key:` on a layout item raise a
clear ValidationError instead of silently passing through.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.normalized import LayoutItem


def test_layoutitem_rejects_unknown_key():
    with pytest.raises(ValidationError, match="bogus_key"):
        LayoutItem(type="chart", bogus_key="x")


def test_layoutitem_rejects_typo_chart_key():
    """Common typo: 'chrt' instead of 'chart'."""
    with pytest.raises(ValidationError, match="chrt"):
        LayoutItem(type="chart", chrt="some_chart_id")


def test_layoutitem_valid_chart_item():
    item = LayoutItem(type="chart", width=400.0, height=300.0)
    assert item.type == "chart"
    assert item.chart is None


def test_layoutitem_valid_board_item():
    item = LayoutItem(type="board", width=600.0, height=400.0)
    assert item.type == "board"
    assert item.board is None
