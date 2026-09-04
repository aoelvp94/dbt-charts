"""Tests for project_roots resolution helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from dbt_charts.core.project_roots import (
    DCT_ROOT_MARKERS,
    find_dct_root,
    find_project_root,
    find_repo_root,
    find_root,
)


def test_find_root_returns_dir_with_marker(tmp_path: Path) -> None:
    (tmp_path / "marker").write_text("x\n")
    assert find_root(tmp_path, ("marker",)) == tmp_path


def test_find_root_walks_up_from_subdir(tmp_path: Path) -> None:
    (tmp_path / "marker").write_text("x\n")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_root(sub, ("marker",)) == tmp_path


def test_find_root_returns_none_when_no_marker(tmp_path: Path) -> None:
    sub = tmp_path / "empty"
    sub.mkdir()
    assert find_root(sub, ("marker",)) is None


def test_find_root_returns_nearest_marker(tmp_path: Path) -> None:
    (tmp_path / "marker").write_text("outer\n")
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "marker").write_text("inner\n")
    deeper = inner / "deeper"
    deeper.mkdir()
    # Walk stops at the nearest ancestor carrying the marker.
    assert find_root(deeper, ("marker",)) == inner


@pytest.mark.parametrize("marker", DCT_ROOT_MARKERS)
def test_find_dct_root_returns_dir_with_each_marker(
    tmp_path: Path, marker: str
) -> None:
    (tmp_path / marker).write_text("name: x\n")
    assert find_dct_root(tmp_path) == tmp_path


def test_find_dct_root_walks_up_from_subdir(tmp_path: Path) -> None:
    (tmp_path / "dbt_charts.yml").write_text("name: x\n")
    sub = tmp_path / "charts"
    sub.mkdir()
    assert find_dct_root(sub) == tmp_path


def test_find_dct_root_returns_none_when_no_marker(tmp_path: Path) -> None:
    sub = tmp_path / "empty"
    sub.mkdir()
    assert find_dct_root(sub) is None


def test_find_repo_root_finds_git_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "packages" / "x"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == tmp_path


def test_find_repo_root_returns_none_without_git(tmp_path: Path) -> None:
    assert find_repo_root(tmp_path) is None


def test_find_project_root_returns_project_root(tmp_path: Path) -> None:
    """find_project_root walks up to the first real dbt_charts.yml."""
    (tmp_path / "dbt_charts.yml").write_text("sources: {}\n")
    boards = tmp_path / "charts"
    boards.mkdir()

    result = find_project_root(boards, tmp_path)

    assert result == tmp_path
