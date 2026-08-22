"""Unit tests for AdapterRegistry instance methods.

Pins `AdapterRegistry.list_sql_sources` (empty case, in-memory marker,
deterministic sort), `AdapterRegistry.register_source` (synthetic source
registration), and `AdapterRegistry.resolve_source_config`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.config import load_project_sources
from dbt_charts.core.compile.models.source import DuckDBSourceConfig
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.execute.adapters import AdapterRegistry
from dbt_charts.core.execute.adapters.duckdb_adapter import DuckDBAdapter
from dbt_charts.core.execute.adapters.sql_adapter import SqlAdapter


def _registry_with_sources(
    tmp_path: Path, sources_yaml: str, local_project: Callable[..., FilesystemProject]
) -> AdapterRegistry:
    """Build an AdapterRegistry whose SourceRegistry reads from tmp_path."""
    (tmp_path / "dbt_charts.yml").write_text(sources_yaml)
    return AdapterRegistry(
        project=local_project(tmp_path),
        project_sources=load_project_sources(local_project(tmp_path)),
    )


class TestListSqlSources:
    def test_empty_registry_returns_empty_list(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        assert AdapterRegistry(project=local_project(Path())).list_sql_sources() == []

    def test_registry_without_sources_returns_empty_list(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = AdapterRegistry(project=local_project(tmp_path))
        assert registry.list_sql_sources() == []

    def test_in_memory_duckdb_source_gets_in_memory_marker(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = _registry_with_sources(
            tmp_path,
            "sources:\n  mem:\n    type: duckdb\n    path: ':memory:'\n",
            local_project,
        )

        result = registry.list_sql_sources()
        assert result == [
            {"name": "mem", "type": "duckdb", "path": ":memory:", "in_memory": True}
        ]

    def test_file_backed_duckdb_source_omits_in_memory_marker(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        db_path = tmp_path / "warehouse.duckdb"
        registry = _registry_with_sources(
            tmp_path,
            f"sources:\n  warehouse:\n    type: duckdb\n    path: '{db_path}'\n",
            local_project,
        )

        result = registry.list_sql_sources()
        assert result == [{"name": "warehouse", "type": "duckdb", "path": str(db_path)}]

    def test_results_are_sorted_by_name(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = _registry_with_sources(
            tmp_path,
            (
                "sources:\n"
                "  zeta:\n    type: duckdb\n    path: ':memory:'\n"
                "  alpha:\n    type: duckdb\n    path: ':memory:'\n"
                "  mike:\n    type: duckdb\n    path: ':memory:'\n"
            ),
            local_project,
        )

        result: list[dict[str, Any]] = registry.list_sql_sources()
        assert [s["name"] for s in result] == ["alpha", "mike", "zeta"]


class TestRegisterSource:
    """Synthetic source registration lands on the registry, not the adapter."""

    def test_register_source_appears_in_list(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = AdapterRegistry(project=local_project(Path()))
        registry.register_source("synth", {"type": "duckdb", "path": ":memory:"})
        names = [s["name"] for s in registry.list_sql_sources()]
        assert names == ["synth"]

    def test_register_source_is_idempotent_first_wins(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = AdapterRegistry(project=local_project(Path()))
        registry.register_source("synth", {"type": "duckdb", "path": ":memory:"})
        registry.register_source("synth", {"type": "duckdb", "path": "/tmp/a.duckdb"})
        config = registry.resolve_source_config("synth")
        assert config["path"] == ":memory:"

    def test_project_source_wins_over_synthetic(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = _registry_with_sources(
            tmp_path,
            "sources:\n  shared:\n    type: duckdb\n    path: ':memory:'\n",
            local_project,
        )
        registry.register_source(
            "shared", {"type": "duckdb", "path": "/tmp/synth.duckdb"}
        )
        config = registry.resolve_source_config("shared")
        assert config["path"] == ":memory:"


class TestResolveSourceConfig:
    """resolve_source_config must raise when source is None — no lossy fallback."""

    def test_no_source_raises_even_with_duckdb_adapter_registered(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """No default-DuckDB fallback: a real registry built via
        build_adapter_registry() (which registers a DuckDBAdapter) still raises
        for source=None — there is no stored default to fall back to."""
        from dbt_charts.core.diagnostics.codes_execute import ERR_NO_DEFAULT_SOURCE
        from dbt_charts.core.execute.adapters.adapter_registry import (
            build_adapter_registry,
        )

        registry = build_adapter_registry(local_project(Path()))

        with pytest.raises(DbtChartsError) as exc_info:
            registry.resolve_source_config(source=None)
        assert exc_info.value.code is ERR_NO_DEFAULT_SOURCE

    def test_no_source_non_duckdb_raises(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        # Non-DuckDB SqlAdapter has credentials/host/port that source_config_from_url
        # would drop — must raise instead of silently producing a mangled config.
        from dbt_charts.core.diagnostics.codes_execute import ERR_NO_DEFAULT_SOURCE

        registry = AdapterRegistry(project=local_project(Path()))
        registry.register(
            SqlAdapter(
                project=local_project(Path("/tmp")),
                dbt_project_path=None,
                profile_type="postgres",
            )
        )

        with pytest.raises(DbtChartsError) as exc_info:
            registry.resolve_source_config(source=None)
        assert exc_info.value.code is ERR_NO_DEFAULT_SOURCE

    def test_no_source_no_adapter_still_raises(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        # No registry at all — must also raise (not the "no SQL adapter" branch).
        from dbt_charts.core.diagnostics.codes_execute import ERR_NO_DEFAULT_SOURCE

        with pytest.raises(DbtChartsError) as exc_info:
            AdapterRegistry(project=local_project(Path())).resolve_source_config(
                source=None
            )
        assert exc_info.value.code is ERR_NO_DEFAULT_SOURCE
        # No sources configured → `available` is an empty Sequence[str], which the
        # display path renders "none configured" — not "" or a bare list repr.
        assert "none configured" in exc_info.value.message

    def test_no_default_source_error_renders_available_as_joined_names(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """The sourceless-SQL error passes `available` as a Sequence[str] like
        every other ERR-* caller, so the diagnostic joins the configured names
        for display — never a raw Python list repr. Guards this raise site
        against regressing to a pre-joined string, which would diverge from the
        contract and crash the moment this code gains a hint_generator."""
        from dbt_charts.core.diagnostics.codes_execute import ERR_NO_DEFAULT_SOURCE

        registry = _registry_with_sources(
            tmp_path,
            "sources:\n"
            "  alpha:\n    type: duckdb\n    path: ':memory:'\n"
            "  beta:\n    type: duckdb\n    path: ':memory:'\n",
            local_project,
        )

        with pytest.raises(DbtChartsError) as exc_info:
            registry.resolve_source_config(source=None)
        assert exc_info.value.code is ERR_NO_DEFAULT_SOURCE
        message = exc_info.value.message
        assert "alpha" in message and "beta" in message
        assert "['" not in message

    def test_named_source_still_resolves(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = _registry_with_sources(
            tmp_path,
            "sources:\n  mydb:\n    type: duckdb\n    path: ':memory:'\n",
            local_project,
        )

        config = registry.resolve_source_config(source="mydb")
        assert config["type"] == "duckdb"


class TestSourceAwareRouting:
    """Source-aware adapter routing in AdapterRegistry.execute."""

    def test_dbt_jinja_with_unresolved_source_routes_to_dbt_adapter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """SQL with {{ ref() }} and a named source that resolves to None must go
        to DbtAdapter (which owns manifest resolution), not DuckDBAdapter.
        DbtAdapter is registered before DuckDBAdapter, so it wins the source-less
        dbt-jinja case that both are eligible for.
        """
        from unittest.mock import MagicMock, patch

        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.execute.adapters.dbt_adapter import DbtAdapter
        from dbt_charts.core.execute.dbt_jinja import has_dbt_jinja

        registry = AdapterRegistry(project=local_project(tmp_path))

        # Mock DbtAdapter (we check routing, not execution) whose can_execute
        # mirrors the real predicate: source-less SQL that carries dbt jinja.
        dbt_adapter = MagicMock(spec=DbtAdapter)
        dbt_adapter.supported_types = {"sql"}
        dbt_adapter.dbt_project_path = tmp_path
        dbt_adapter.can_execute = lambda q, sc: sc is None and has_dbt_jinja(q.sql)
        dbt_adapter.execute = MagicMock(
            return_value=MagicMock(data=[], error=None, is_success=True)
        )
        registry.register(dbt_adapter)

        duckdb_adapter = DuckDBAdapter(source_config=DuckDBSourceConfig(type="duckdb"))
        registry.register(duckdb_adapter)

        sql_adapter = SqlAdapter(
            project=local_project(tmp_path),
            dbt_project_path=None,
            profile_type="duckdb",
        )
        registry.register(sql_adapter)

        # A query with a string source that won't resolve to any entry in dbt_charts.yml
        # and SQL that contains dbt-jinja {{ ref() }}.
        query = SqlQuery(
            sql="SELECT * FROM {{ ref('orders') }}",
            source="my_unknown_source",
        )

        # Patch the resolver to return None (simulates dbt-context: unknown named source)
        with patch.object(
            registry._resolver,
            "resolve",
            return_value=None,
        ):
            registry.execute(query)

        # DbtAdapter must have been called, not DuckDBAdapter
        dbt_adapter.execute.assert_called_once()

    @pytest.mark.parametrize("source_type", ["duckdb", "sqlite"])
    def test_file_source_seam_closed_when_adapter_absent(
        self,
        tmp_path: Path,
        local_project: Callable[..., FilesystemProject],
        source_type: str,
    ) -> None:
        """A registry that omits the file-engine adapters (as Cloud's
        build_cloud_adapter_registry does) fails closed: a duckdb/sqlite source
        resolves but no adapter claims it, so execute returns 'No adapter found'
        rather than falling back to the warehouse SqlAdapter."""
        from unittest.mock import patch

        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.models.source import (
            DuckDBSourceConfig,
            SQLiteSourceConfig,
        )

        registry = AdapterRegistry(project=local_project(tmp_path))
        # Only the warehouse adapter — no DuckDB/SQLite adapter (the Cloud shape).
        registry.register(
            SqlAdapter(
                project=local_project(tmp_path),
                dbt_project_path=None,
                profile_type="postgres",
            )
        )

        resolved = (
            DuckDBSourceConfig(type="duckdb", path=":memory:")
            if source_type == "duckdb"
            else SQLiteSourceConfig(type="sqlite", path="db.sqlite")
        )
        query = SqlQuery(sql="SELECT 1", source="local_file")
        with patch.object(registry._resolver, "resolve", return_value=resolved):
            result = registry.execute(query)

        assert not result.is_success
        assert "no adapter found" in (result.error or "").lower()

    def test_duckdb_routes_to_duckdb_adapter_not_sql_adapter(
        self,
        tmp_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """DuckDB is owned exclusively by DuckDBAdapter — a registry with both
        registered routes a duckdb source there, never to SqlAdapter's pool."""
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.models.source import DuckDBSourceConfig

        registry = AdapterRegistry(project=local_project(tmp_path))
        duckdb_adapter = DuckDBAdapter(source_config=DuckDBSourceConfig(type="duckdb"))
        registry.register(duckdb_adapter)
        sql_adapter = SqlAdapter(
            project=local_project(tmp_path),
            dbt_project_path=None,
            profile_type="postgres",
        )
        registry.register(sql_adapter)

        query = SqlQuery(sql="SELECT 1", source="local_file")
        resolved = DuckDBSourceConfig(type="duckdb", path=":memory:")
        assert registry.get_adapter(query, resolved) is duckdb_adapter

    def test_sql_adapter_never_claims_duckdb_source(
        self,
        tmp_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        """SqlAdapter._can_execute rejects duckdb sources unconditionally — the
        allow_duckdb escape hatch is gone; DuckDBAdapter owns duckdb exclusively."""
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.models.source import DuckDBSourceConfig

        sql_adapter = SqlAdapter(
            project=local_project(tmp_path),
            dbt_project_path=None,
            profile_type="postgres",
        )
        query = SqlQuery(sql="SELECT 1", source="local_file")
        resolved = DuckDBSourceConfig(type="duckdb", path=":memory:")
        assert sql_adapter._can_execute(query, resolved) is False


class TestClose:
    def test_close_calls_sql_adapter_close(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        registry = AdapterRegistry(project=local_project(tmp_path))
        adapter = SqlAdapter(
            project=local_project(tmp_path),
            dbt_project_path=None,
            profile_type="postgres",
        )
        registry.register(adapter)

        closed = False
        original_close = adapter.close

        def track_close() -> None:
            nonlocal closed
            closed = True
            original_close()

        adapter.close = track_close  # type: ignore[method-assign]
        registry.close()
        assert closed


class TestSourcelessRejectScopedToSql:
    """The closed-allowlist source-less reject fires for SQL queries only.

    A hosted/multi-tenant surface (AllowlistedSourceResolver) rejects a
    source-less SQL query because it would otherwise fall through to the engine's
    fallback DuckDB — an SSRF / local-file-read vector. But inline query types
    (values / http) have no source connection at all, so gating them
    on a registered source is wrong and breaks every KPI / literal-data chart in
    deployed mode. Regression: PR #5113 rejected authored=None for every query
    type at the resolver, so values queries failed to render on the deployed
    playground.
    """

    def _hosted_registry(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> AdapterRegistry:
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.execute.source_resolver import AllowlistedSourceResolver

        (tmp_path / "dbt_charts.yml").write_text(
            "sources:\n  warehouse:\n    type: duckdb\n    path: ':memory:'\n"
        )
        return build_adapter_registry(
            local_project(tmp_path),
            read_only=False,
            resolver=AllowlistedSourceResolver(),
        )

    def test_sourceless_values_query_renders_on_hosted_surface(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.core.compile.models.query.normalized import ValuesQuery

        registry = self._hosted_registry(tmp_path, local_project)
        result = registry.execute(ValuesQuery(rows=[{"metric": "revenue", "n": 42}]))
        assert result.error is None, result.error
        assert result.data == [{"metric": "revenue", "n": 42}]

    def test_sourceless_sql_query_still_rejected_on_hosted_surface(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery

        registry = self._hosted_registry(tmp_path, local_project)
        result = registry.execute(SqlQuery(sql="SELECT 1 AS one", source=None))
        assert result.error is not None
        assert "source name required" in result.error.lower()

    def test_named_non_sql_query_still_resolves_on_hosted_surface(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """The `authored is None` half of the skip predicate is load-bearing.

        A non-SQL query that *names* a source (SchemaQuery(source="x")) is not
        source-less, so it must still route through the resolver — an unknown name
        is rejected on the closed allowlist. A bare `not is_sql_query(query)` skip
        would wrongly bypass this.
        """
        from dbt_charts.core.compile.models.query.normalized import SchemaQuery

        registry = self._hosted_registry(tmp_path, local_project)
        result = registry.execute(SchemaQuery(source="unregistered"))
        assert result.error is not None
        assert "unregistered" in result.error

    def test_execute_threads_query_name_into_source_not_found_message(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """ERR-SOURCE-NOT-FOUND's message_template requires `query_name`.
        `execute()`'s `query_name` kwarg must reach the resolver and appear
        in the rendered error, not just avoid a KeyError.
        """
        from dbt_charts.core.compile.models.query.normalized import SchemaQuery

        registry = self._hosted_registry(tmp_path, local_project)
        result = registry.execute(
            SchemaQuery(source="unregistered"), query_name="my_named_query"
        )
        assert result.error is not None
        assert "my_named_query" in result.error


class TestSourcelessSqlRejectedOnDefaultResolver:
    """execute() itself closes the default-DuckDB fallback — not just
    resolve_source_config(None). Before this fix, a sourceless SqlQuery on
    the plain (non-hosted) DefaultSourceResolver silently ran against the
    build-time :memory: DuckDBAdapter instead of raising."""

    def _registry_with_a_configured_source(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> AdapterRegistry:
        from dbt_charts.core.execute.adapters import build_adapter_registry

        (tmp_path / "dbt_charts.yml").write_text(
            "sources:\n  warehouse:\n    type: duckdb\n    path: ':memory:'\n"
        )
        return build_adapter_registry(local_project(tmp_path), read_only=False)

    def test_sourceless_sql_query_raises_no_default_source(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery

        registry = self._registry_with_a_configured_source(tmp_path, local_project)
        result = registry.execute(SqlQuery(sql="SELECT 1 AS one", source=None))
        assert result.error is not None
        assert "Name a source for the query" in result.error

    def test_sourceless_values_query_still_succeeds(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.core.compile.models.query.normalized import ValuesQuery

        registry = self._registry_with_a_configured_source(tmp_path, local_project)
        result = registry.execute(ValuesQuery(rows=[{"metric": "revenue", "n": 42}]))
        assert result.error is None, result.error
        assert result.data == [{"metric": "revenue", "n": 42}]
