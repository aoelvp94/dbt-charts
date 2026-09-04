"""Compile-level record for editorial-10's in-place meaning changes.

Numeric, bracket, and named-alias spellings remain valid across the refresh,
so schema recognition cannot distinguish a board authored against the previous
colors from one authored against the current family.
"""

from __future__ import annotations

from dbt_charts.core.compile.compiler import compile


def test_unchanged_editorial_tokens_compile_to_refreshed_meanings() -> None:
    result = compile(
        """
extends: clarity
title: Palette migration witness
style:
  background: editorial-10.3
  border:
    color: category[3]
  font:
    color: category.sage
text: unchanged spellings remain accepted
"""
    )

    assert result.success, result.errors
    assert result.board is not None
    style = result.board.resolved_style
    assert style.background == "#608470"
    assert style.border.color == "#608470"
    assert style.font.color == "#a0b6b7"
