"""Tests for Levenshtein hint generators.

Exercised through `suggest_close_source` — one of the two generators actually
wired to a code's `hint_generator` (ERR-SOURCE-NOT-FOUND in codes_compile).
The three cases below cover the shared `_suggest_close_match` core that
`suggest_close_theme` also runs on. That the wiring survives a real raise is
pinned separately in tests/core/execute/test_source_resolver_diagnostics.py.

`available` is a `Sequence[str]` contract, not a comma-separated string — a
raise site writes `available=sorted(...)`, the expression it naturally
reaches for. `str` is itself a `Sequence[str]` of characters, so passing one
must raise `TypeError` rather than silently scoring single letters.
"""

from __future__ import annotations

import pytest


class TestHints:
    def test_suggest_close_source_hit(self) -> None:
        from dbt_charts.core.diagnostics.hints import suggest_close_source

        hint = suggest_close_source(
            source="postgre", available=["postgres", "duckdb", "bigquery", "snowflake"]
        )
        assert hint is not None
        assert "postgres" in hint

    def test_suggest_close_source_no_hit(self) -> None:
        from dbt_charts.core.diagnostics.hints import suggest_close_source

        hint = suggest_close_source(source="zzzzzzz", available=["postgres", "duckdb"])
        assert hint is None

    def test_suggest_close_source_empty_available(self) -> None:
        from dbt_charts.core.diagnostics.hints import suggest_close_source

        hint = suggest_close_source(source="postgres", available=[])
        assert hint is None

    def test_suggest_close_match_rejects_bare_str(self) -> None:
        """`str` is a `Sequence[str]` of characters — must reject, not silently
        score character-by-character or coerce."""
        from dbt_charts.core.diagnostics.hints import _suggest_close_match

        with pytest.raises(TypeError):
            _suggest_close_match("postgre", "postgres, duckdb")
