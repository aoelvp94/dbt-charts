"""Regression tests for Executor cache wiring.

Covers:
- Executor with DuckDB failure cache: adapter not called on cache hit

DCT_CACHE_PATH env-var wiring now lives entirely at the CLI/Typer boundary
(--cache PATH, envvar=DCT_CACHE_PATH); core no longer reads the environment
directly, so there is nothing to test at this layer.

The render_dashboard entry point's own cache wiring (forwarded to Executor
unchanged, never closed by the callee) is covered in
dbt-charts/tests/agent_api/test_dashboards.py::TestRenderDashboardDiagnostics
(test_render_dashboard_threads_result_cache_to_executor,
test_render_dashboard_does_not_close_result_cache) — this module no longer
duplicates that coverage now that compile_and_render is deleted.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dbt_charts.core.compile import compile as df_compile
from dbt_charts.core.execute import Executor, QueryError
from dbt_charts.core.execute.cache_backend import CachedQueryFailure
from dbt_charts.core.execute.duckdb_cache import (
    compute_query_hash,
    compute_source_hash,
    compute_variables_hash,
)
from dbt_charts.core.execute.trivial_local_cache import TrivialDuckDBCache

BOARD_YAML = """\
title: Test
source: memory
queries:
  my_query:
    sql: SELECT 1 as value
charts:
  c:
    query: my_query
    type: kpi
    value: value
rows:
  - c
"""


def _ok_adapter() -> MagicMock:
    """Mock adapter registry that returns one row successfully."""
    ok = MagicMock()
    ok.is_success = True
    ok.data = [{"value": 42}]
    ok.column_descriptions = None
    ok.resolved_relations = None
    ok.truncated_reason = None
    registry = MagicMock()
    registry.execute.return_value = ok
    return registry


class TestExecutorFailureCacheBlocksAdapter:
    """Verify that a pre-seeded DuckDB failure cache prevents adapter execution."""

    def test_failure_cache_hit_adapter_not_called(self, tmp_path: Path) -> None:
        """A cached failure for the query means adapter.execute is never called."""
        db = tmp_path / "cache.duckdb"

        # Seed with the correct source_hash matching what executor computes.
        # BOARD_YAML's `source: memory` is a name reference with no registry
        # entry (D-09: boards can't define sources inline) — board.sources is
        # empty, so compute_source_hash falls back to hashing the bare name.
        seed = TrivialDuckDBCache(db_path=db, failure_ttl_seconds=9000)
        seed.put(
            compute_source_hash("memory", board_sources={}),
            compute_query_hash("SELECT 1 as value"),
            compute_variables_hash({}),
            RuntimeError("pre-seeded failure"),
            board_slug="test",
            query_name="my_query",
        )
        seed.close()

        cache = TrivialDuckDBCache(db_path=db, failure_ttl_seconds=9000)
        result = df_compile(BOARD_YAML)
        adapter = _ok_adapter()
        try:
            executor = Executor(
                result.board,
                adapter_registry=adapter,
                query_registry=result.query_registry,
                result_cache=cache,
            )
            with pytest.raises((CachedQueryFailure, QueryError)):
                executor.execute_query("my_query")

            assert adapter.execute.call_count == 0
        finally:
            cache.close()
