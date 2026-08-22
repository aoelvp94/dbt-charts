"""Tests for the host-agnostic inbound-link scanner used by move_file.

TDD: written before dbt_charts.agent_api._link_scan exists.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dbt_charts.agent_api._link_scan import board_slug, rewrite_links, scan_links
from dbt_charts.core.project import Project


class TestBoardSlug:
    def test_strips_boards_prefix_and_suffix(self) -> None:
        assert board_slug("charts/finance/rev.yml") == "finance/rev"

    def test_returns_none_outside_boards(self) -> None:
        assert board_slug("models/revenue.sql") is None


class TestScanLinks:
    def test_link_field_reference_is_exact(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(
            tmp_path,
            {
                "charts/exec.yml": (
                    "title: Exec\ncharts:\n  a:\n    type: kpi\n    link: finance/rev\n"
                ),
            },
        )
        result = scan_links(project, "finance/rev")
        assert [h.path for h in result.exact] == ["charts/exec.yml"]
        assert result.fuzzy == []

    def test_bare_basename_prose_mention_is_fuzzy(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(
            tmp_path,
            {"charts/notes.yml": "title: Notes\ndescription: see the rev dashboard\n"},
        )
        result = scan_links(project, "finance/rev")
        assert result.exact == []
        assert [h.path for h in result.fuzzy] == ["charts/notes.yml"]

    def test_markdown_link_reference_is_exact(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(
            tmp_path,
            {"charts/notes.md": "See the [revenue board](finance/rev) for detail.\n"},
        )
        result = scan_links(project, "finance/rev")
        assert [h.path for h in result.exact] == ["charts/notes.md"]

    def test_rooted_link_field_with_query_string_is_exact(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(
            tmp_path,
            {
                "charts/exec.yml": ('link: "/finance/rev?month={{ month }}"\n'),
            },
        )
        result = scan_links(project, "finance/rev")
        assert [h.path for h in result.exact] == ["charts/exec.yml"]

    def test_scan_is_scoped_to_boards_tree(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(
            tmp_path,
            {"models/revenue.sql": "-- link: finance/rev\n"},
        )
        result = scan_links(project, "finance/rev")
        assert result.exact == []
        assert result.fuzzy == []

    def test_same_folder_relative_link_is_fuzzy_not_exact(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        """A bare relative reference (``link: rev``, no ``finance/`` prefix)
        is found by the basename grep but never classified EXACT -- only a
        full-slug match is rewritten; a relative reference is reported as
        fuzzy and left untouched (out of scope: see module docstring)."""
        project = in_memory_project(
            tmp_path,
            {
                "charts/finance/exec.yml": (
                    "charts:\n  a:\n    type: kpi\n    link: rev\n"
                ),
            },
        )
        result = scan_links(project, "finance/rev")
        assert result.exact == []
        assert [h.path for h in result.fuzzy] == ["charts/finance/exec.yml"]


class TestRewriteLinks:
    def test_rewrites_exact_link_field_in_place(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(
            tmp_path,
            {"charts/exec.yml": "charts:\n  a:\n    link: finance/rev\n"},
        )
        result = rewrite_links(project, "finance/rev", "growth/rev")
        assert len(result.exact) == 1
        assert project.read_text("charts/exec.yml") == (
            "charts:\n  a:\n    link: growth/rev\n"
        )

    def test_leaves_fuzzy_hit_byte_identical(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        original = "title: Notes\ndescription: see the rev dashboard\n"
        project = in_memory_project(tmp_path, {"charts/notes.yml": original})
        result = rewrite_links(project, "finance/rev", "growth/rev")
        assert len(result.fuzzy) == 1
        assert project.read_text("charts/notes.yml") == original

    def test_no_exact_hits_is_a_no_op(
        self,
        tmp_path: Path,
        in_memory_project: Callable[[Path, dict[str, str]], Project],
    ) -> None:
        project = in_memory_project(tmp_path, {"charts/exec.yml": "title: Exec\n"})
        result = rewrite_links(project, "finance/rev", "growth/rev")
        assert result.exact == []
        assert result.fuzzy == []
