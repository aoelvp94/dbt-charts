"""Tests for open_cache() and project_cache_ctx() in dbt_charts.agent_api.cache."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from dbt_charts.agent_api.cache import (
    open_cache,
    project_cache_ctx,
)
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.cache_backend import CacheHit
from dbt_charts.core.execute.trivial_local_cache import TrivialDuckDBCache


class TestOpenCache:
    def test_none_path_opens_in_memory_cache(self) -> None:
        cache = open_cache(None)
        try:
            assert isinstance(cache, TrivialDuckDBCache)
            assert cache.db_path is None
        finally:
            cache.close()

    def test_path_opens_persistent_file_creating_if_absent(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "exist.duckdb"
        assert not db_path.exists()

        cache = open_cache(db_path)
        try:
            assert isinstance(cache, TrivialDuckDBCache)
            assert cache.db_path == db_path
        finally:
            cache.close()
        assert db_path.exists()

    def test_existing_path_is_reused(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cache.duckdb"
        seed = open_cache(db_path)
        seed.put(
            "s" * 16,
            "q" * 16,
            "v" * 16,
            [{"x": 1}],
            board_slug="f",
            query_name="q",
        )
        seed.close()

        cache = open_cache(db_path)
        try:
            hit = cache.get("s" * 16, "q" * 16, "v" * 16)
            assert isinstance(hit, CacheHit)
            assert hit.rows == [{"x": 1}]
        finally:
            cache.close()


class TestProjectCachePrecedence:
    """project_cache_ctx: flag > env > project dbt_charts.yml cache: block.

    These cover which store gets opened. TestProjectCacheCtx below covers the
    context manager's lifecycle (yield / close / close-on-exception) — the two
    do not overlap, so this precedence coverage has no other home.
    """

    def test_no_project_config_defaults_to_in_memory(self, tmp_path: Path) -> None:
        with project_cache_ctx(FilesystemProject(tmp_path)) as cache:
            assert isinstance(cache, TrivialDuckDBCache)
            assert cache.db_path is None

    def test_no_cache_flag_yields_none(self, tmp_path: Path) -> None:
        with project_cache_ctx(FilesystemProject(tmp_path), no_cache=True) as cache:
            assert cache is None

    def test_cache_path_flag_wins_over_disabled_config(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text("cache: false\n")
        explicit = tmp_path / "explicit.duckdb"
        with project_cache_ctx(
            FilesystemProject(tmp_path), cache_path=explicit
        ) as cache:
            assert cache is not None
            assert cache.db_path == explicit

    def test_project_config_disabled_still_opens_the_store(
        self, tmp_path: Path
    ) -> None:
        """A disabled root only defaults the cascade to off — a nearer scope can
        still opt in, so the store is opened either way (only --no-cache skips it)."""
        (tmp_path / "dbt_charts.yml").write_text("cache: false\n")
        with project_cache_ctx(FilesystemProject(tmp_path)) as cache:
            assert cache is not None
            assert cache.db_path is None

    def test_project_config_path_opens_persistent_file(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text("cache:\n  path: .dct/cache.duckdb\n")
        with project_cache_ctx(FilesystemProject(tmp_path)) as cache:
            assert cache is not None
            assert cache.db_path == tmp_path / ".dct" / "cache.duckdb"


class TestProjectCacheCtx:
    def test_no_cache_yields_none_and_is_a_no_op_on_exit(self, tmp_path: Path) -> None:
        with project_cache_ctx(FilesystemProject(tmp_path), no_cache=True) as cache:
            assert cache is None

    def test_enabled_yields_cache_and_closes_on_exit(self, tmp_path: Path) -> None:
        captured: list[TrivialDuckDBCache] = []
        with project_cache_ctx(FilesystemProject(tmp_path)) as cache:
            assert isinstance(cache, TrivialDuckDBCache)
            # Connection is open inside the block
            cache.conn.execute("SELECT 1").fetchone()
            captured.append(cache)

        with pytest.raises(duckdb.ConnectionException):
            captured[0].conn.execute("SELECT 1").fetchone()

    def test_closes_on_exception_inside_with_block(self, tmp_path: Path) -> None:
        captured: list[TrivialDuckDBCache] = []

        def _run() -> None:
            with project_cache_ctx(FilesystemProject(tmp_path)) as cache:
                assert isinstance(cache, TrivialDuckDBCache)
                captured.append(cache)
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            _run()

        with pytest.raises(duckdb.ConnectionException):
            captured[0].conn.execute("SELECT 1").fetchone()
