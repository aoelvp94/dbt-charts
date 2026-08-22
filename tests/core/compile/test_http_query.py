"""Tests for HttpQuery compile-time validation.

Covers:
- url is required for http queries
- source and path are not accepted on HttpQuery (extra="forbid")
"""

from __future__ import annotations

from dbt_charts.core.compile import compile


def _board_yaml(query_body: str) -> str:
    return f"""\
title: test
source: _test
queries:
  q:
    type: http
{query_body}
rows: []
"""


class TestHttpQueryUrlRequired:
    def test_url_missing_raises_compile_error(self) -> None:
        """HTTP query without url raises CompilationError at compile time."""

        board_yaml = _board_yaml("    method: GET\n")
        result = compile(board_yaml)
        assert not result.success
        errors = [e.message for e in result.errors]
        assert any("url" in msg.lower() for msg in errors), errors

    def test_url_present_compiles(self) -> None:
        """HTTP query with url compiles successfully."""
        board_yaml = _board_yaml("    url: https://api.example.com/data\n")
        result = compile(board_yaml)
        assert result.success, result.errors

    def test_source_on_http_query_raises(self) -> None:
        """source: field on http query is not accepted (extra="forbid")."""
        board_yaml = _board_yaml(
            "    url: https://api.example.com/data\n    source: my_api\n"
        )
        result = compile(board_yaml)
        assert not result.success
        errors = [e.message for e in result.errors]
        assert any("source" in msg.lower() for msg in errors), errors

    def test_path_on_http_query_raises(self) -> None:
        """path: field on http query is not accepted (extra="forbid")."""
        board_yaml = _board_yaml("    url: https://api.example.com\n    path: /data\n")
        result = compile(board_yaml)
        assert not result.success
        errors = [e.message for e in result.errors]
        assert any("path" in msg.lower() for msg in errors), errors
