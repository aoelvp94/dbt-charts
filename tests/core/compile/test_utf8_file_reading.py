"""Regression test: compile_file reads board YAML as UTF-8 regardless of locale.

On Windows the default locale encoding is cp1252. Before the fix, bare
read_text() calls in compile_file() would misread UTF-8 non-ASCII bytes —
em-dashes, box-drawing characters, arrows — producing garbled YAML that
failed to parse or produced garbage title/text content.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.compiler import compile_file


@pytest.fixture
def utf8_board(tmp_path: Path) -> Path:
    """Write a board YAML file containing non-ASCII UTF-8 characters."""
    board = tmp_path / "test.yml"
    # Write explicitly as UTF-8 — the point is that compile_file must read it
    # as UTF-8 regardless of the process locale.
    board.write_text(
        "title: Revenue — Q1\nrows: []\n",  # em-dash U+2014
        encoding="utf-8",
    )
    return board


@pytest.mark.windows
def test_compile_file_reads_non_ascii_title(
    utf8_board: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    project = local_project(utf8_board.parent)
    result = compile_file(project.path("test.yml").read_board())
    assert result.success, result.errors
    assert result.board is not None
    assert "—" in result.board.title
