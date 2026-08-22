"""Tests for Project.file_version — the single cheap file-identity token.

file_version is the one token that keys file-source caching (both the
materializer's internal file-table cache and the outer result cache), so it must
change whenever the file's content changes and stay stable while it does not —
without reading the whole file on the FilesystemProject path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject


def _project(tmp_path: Path, relpath: str, content: bytes) -> FilesystemProject:
    dest = tmp_path / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return FilesystemProject(tmp_path)


def test_file_version_stable_for_unchanged_file(tmp_path: Path) -> None:
    project = _project(tmp_path, "data/x.csv", b"a,b\n1,2\n")
    first = project.file_version("data/x.csv")
    second = project.file_version("data/x.csv")
    assert first == second


def test_file_version_changes_when_content_changes(tmp_path: Path) -> None:
    project = _project(tmp_path, "data/x.csv", b"a,b\n1,2\n")
    before = project.file_version("data/x.csv")

    dest = tmp_path / "data/x.csv"
    # Bump mtime forward deterministically so the stat signature must change even
    # if the write lands within the same clock tick as the original.
    dest.write_bytes(b"a,b\n1,2\n3,4\n")
    st = dest.stat()
    os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    after = project.file_version("data/x.csv")
    assert after != before


def test_file_version_missing_file_raises(tmp_path: Path) -> None:
    project = FilesystemProject(tmp_path)
    with pytest.raises(FileNotFoundError):
        project.file_version("data/nope.csv")


def test_file_version_does_not_read_whole_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The local token is a stat signature — it must not read the file bytes."""
    project = _project(tmp_path, "data/x.csv", b"a,b\n1,2\n")

    def _boom(self: FilesystemProject, relpath: str) -> bytes:
        raise AssertionError("file_version must not read file bytes on the stat path")

    monkeypatch.setattr(FilesystemProject, "read_bytes", _boom)
    # Should compute purely from stat, never touching read_bytes.
    assert project.file_version("data/x.csv")
