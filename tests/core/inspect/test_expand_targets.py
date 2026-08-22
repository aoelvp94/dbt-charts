"""Unit tests for the drill-down target expander.

``_expand_targets`` powers the SCHEMA / TABLE / COLUMN positional args of
the schema resolver. A spec is one or more alternation items separated by ``,`` or
``|``; each item is a literal name or an fnmatch glob.
"""

from __future__ import annotations

from dbt_charts.core.inspect.resolver import _expand_targets, is_exact_target

CANDS = ["id", "requester_id", "status", "email", "created_at"]


class TestExpandTargets:
    def test_star_returns_all(self) -> None:
        assert _expand_targets("*", CANDS) == CANDS
        assert _expand_targets(None, CANDS) == CANDS

    def test_single_literal(self) -> None:
        assert _expand_targets("status", CANDS) == ["status"]
        assert _expand_targets("nope", CANDS) == []

    def test_comma_list(self) -> None:
        assert _expand_targets("id,status", CANDS) == ["id", "status"]

    def test_pipe_alternation(self) -> None:
        assert _expand_targets("id|requester_id|status", CANDS) == [
            "id",
            "requester_id",
            "status",
        ]

    def test_glob(self) -> None:
        assert _expand_targets("*_id", CANDS) == ["requester_id"]

    def test_glob_inside_list(self) -> None:
        assert _expand_targets("id,requester*", CANDS) == ["id", "requester_id"]
        assert _expand_targets("id|requester*", CANDS) == ["id", "requester_id"]

    def test_dedupes_preserving_first_seen(self) -> None:
        assert _expand_targets("id|id|status", CANDS) == ["id", "status"]


class TestIsExactTarget:
    def test_literal_is_exact(self) -> None:
        assert is_exact_target("status")

    def test_list_or_glob_is_not_exact(self) -> None:
        assert not is_exact_target("id,status")
        assert not is_exact_target("id|status")
        assert not is_exact_target("*_id")
        assert not is_exact_target(None)
