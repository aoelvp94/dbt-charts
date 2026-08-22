"""Regression tests: Layout and Board reject unknown extra keys."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.normalized import Layout

from ._board_utils import make_test_board


def test_layout_rejects_extra_key() -> None:
    with pytest.raises(ValidationError, match="_bogus_key"):
        Layout(type="rows", items=[], _bogus_key="should_fail")


def test_board_rejects_extra_key() -> None:
    with pytest.raises(ValidationError, match="_bogus_key"):
        make_test_board(_bogus_key="should_fail")
