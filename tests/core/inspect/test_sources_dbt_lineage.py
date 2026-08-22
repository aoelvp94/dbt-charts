"""Tests for DbtSchemaSource lineage extraction.

Verifies that profile_table() surfaces upstream (parent_map) and downstream
(child_map) table edges from the dbt manifest, filtered to table-shaped
unique-id prefixes only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.inspect.sources.dbt import DbtSchemaSource

# ---------------------------------------------------------------------------
# Minimal fake adapter (no warehouse calls needed for lineage-only tests)
# ---------------------------------------------------------------------------


@dataclass
class _FakeRelation:
    identifier: str
    schema: str
    type: str = "table"


@dataclass
class _FakeColumn:
    name: str
    dtype: str


@dataclass
class FakeAdapter:
    schemas: dict[str, list[_FakeRelation]] = field(default_factory=dict)
    columns_by_relation: dict[tuple[str, str], list[_FakeColumn]] = field(
        default_factory=dict
    )

    def add_table(
        self,
        schema: str,
        table: str,
        columns: list[tuple[str, str]] | None = None,
    ) -> None:
        self.schemas.setdefault(schema, []).append(
            _FakeRelation(identifier=table, schema=schema)
        )
        cols = columns or []
        self.columns_by_relation[(schema, table)] = [
            _FakeColumn(name=n, dtype=t) for n, t in cols
        ]

    def list_schemas(self, database: Any) -> list[str]:
        return list(self.schemas.keys())

    def list_relations(self, database: Any, schema: str) -> list[_FakeRelation]:
        return list(self.schemas.get(schema, []))

    def get_columns_in_relation(self, relation: _FakeRelation) -> list[_FakeColumn]:
        return list(
            self.columns_by_relation.get((relation.schema, relation.identifier), [])
        )

    def get_column_schema_from_query(self, sql: str) -> list[_FakeColumn]:
        return []

    @classmethod
    def type(cls) -> str:  # noqa: A003 — mirrors dbt adapter classmethod name
        return "duckdb"

    def calculate_freshness_from_metadata(
        self, source: Any, _macro_resolver: Any = None
    ) -> Any:
        raise NotImplementedError

    @contextmanager
    def connection_named(self, name: str) -> Any:
        yield self


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _write_manifest(project_root: Path, manifest: dict[str, Any]) -> None:
    target = project_root / "target"
    target.mkdir(parents=True, exist_ok=True)
    (target / "manifest.json").write_text(json.dumps(manifest))


def _base_manifest(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "nodes": {},
        "sources": {},
        "parent_map": {},
        "child_map": {},
    }
    base.update(overrides)
    return base


def _fixture_users_and_orders() -> dict[str, Any]:
    return _base_manifest(
        nodes={
            "model.test.users": {
                "resource_type": "model",
                "schema": "analytics",
                "name": "users",
            },
            "model.test.orders": {
                "resource_type": "model",
                "schema": "analytics",
                "name": "orders",
            },
        },
        parent_map={
            "model.test.users": [],
            "model.test.orders": ["model.test.users"],
        },
        child_map={
            "model.test.users": ["model.test.orders"],
            "model.test.orders": [],
        },
    )


def _fixture_orders_with_source_and_ref_parents() -> dict[str, Any]:
    return _base_manifest(
        nodes={
            "model.test.users": {
                "resource_type": "model",
                "schema": "analytics",
                "name": "users",
            },
            "model.test.orders": {
                "resource_type": "model",
                "schema": "analytics",
                "name": "orders",
            },
        },
        sources={
            "source.test.raw.events": {
                "resource_type": "source",
                "schema": "raw",
                "source_name": "raw",
                "name": "events",
                "identifier": "events",
            },
        },
        parent_map={
            "model.test.orders": ["model.test.users", "source.test.raw.events"],
        },
        child_map={
            "model.test.users": ["model.test.orders"],
            "source.test.raw.events": ["model.test.orders"],
            "model.test.orders": [],
        },
    )


def _fixture_three_level_chain() -> dict[str, Any]:
    """raw.events → users → orders (three-level chain for depth tests)."""
    return _base_manifest(
        nodes={
            "model.test.users": {
                "resource_type": "model",
                "schema": "analytics",
                "name": "users",
            },
            "model.test.orders": {
                "resource_type": "model",
                "schema": "analytics",
                "name": "orders",
            },
        },
        sources={
            "source.test.raw.events": {
                "resource_type": "source",
                "schema": "raw",
                "source_name": "raw",
                "name": "events",
                "identifier": "events",
            },
        },
        parent_map={
            "model.test.users": ["source.test.raw.events"],
            "model.test.orders": ["model.test.users"],
        },
        child_map={
            "source.test.raw.events": ["model.test.users"],
            "model.test.users": ["model.test.orders"],
            "model.test.orders": [],
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLineageOneHopUpstream:
    def test_upstream_from_ref_and_source(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """orders refs users (model) and raw.events (source). Both appear upstream."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders")
        _write_manifest(
            tmp_path,
            _base_manifest(
                nodes={
                    "model.test.users": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "users",
                    },
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "orders",
                    },
                },
                sources={
                    "source.test.raw.events": {
                        "resource_type": "source",
                        "schema": "raw",
                        "source_name": "raw",
                        "name": "events",
                        "identifier": "events",
                    },
                },
                parent_map={
                    "model.test.orders": [
                        "model.test.users",
                        "source.test.raw.events",
                    ],
                },
                child_map={
                    "model.test.users": ["model.test.orders"],
                    "source.test.raw.events": ["model.test.orders"],
                    "model.test.orders": [],
                },
            ),
        )
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders")
        assert profile is not None
        assert profile["upstream"] == [
            {
                "model_name": "users",
                "schema": "analytics",
                "table": "users",
                "kind": "ref",
            },
            {
                "model_name": "events",
                "schema": "raw",
                "table": "events",
                "kind": "source",
            },
        ]


class TestLineageOneHopDownstream:
    def test_downstream_of_users_is_orders(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """users → orders. Downstream of users is [orders]. kind is always 'ref'."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "users")
        _write_manifest(tmp_path, _fixture_users_and_orders())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="users")
        assert profile is not None
        assert profile["downstream"] == [
            {
                "model_name": "orders",
                "schema": "analytics",
                "table": "orders",
                "kind": "ref",
            },
        ]


class TestLineageDepthTwo:
    def test_depth_two_walks_transitively(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """raw.events → users → orders. depth=2 from raw.events returns both."""
        adapter = FakeAdapter()
        adapter.add_table("raw", "events")
        _write_manifest(tmp_path, _fixture_three_level_chain())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="raw", table="events", lineage_depth=2)
        assert profile is not None
        downstream_names = {r["table"] for r in profile["downstream"]}
        assert downstream_names == {"users", "orders"}

    def test_depth_one_does_not_walk_transitively(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """raw.events → users → orders. depth=1 from raw.events returns only users."""
        adapter = FakeAdapter()
        adapter.add_table("raw", "events")
        _write_manifest(tmp_path, _fixture_three_level_chain())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="raw", table="events", lineage_depth=1)
        assert profile is not None
        downstream_names = {r["table"] for r in profile["downstream"]}
        assert downstream_names == {"users"}


class TestLineageEmptyContracts:
    def test_manifest_absent_returns_empty_lists(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """No manifest.json on disk → upstream/downstream must be [], not None."""
        adapter = FakeAdapter()
        adapter.add_table("public", "anything")
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="public", table="anything")
        assert profile is not None
        assert profile["upstream"] == []
        assert profile["downstream"] == []

    def test_table_not_in_manifest_returns_empty_lists(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Manifest exists but doesn't know this table → [], not None."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "brand_new_model")
        _write_manifest(tmp_path, _fixture_users_and_orders())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="brand_new_model")
        assert profile is not None
        assert profile["upstream"] == []
        assert profile["downstream"] == []

    def test_leaf_table_has_empty_upstream(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """users has no parents → upstream is []."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "users")
        _write_manifest(tmp_path, _fixture_users_and_orders())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="users")
        assert profile is not None
        assert profile["upstream"] == []

    def test_sink_table_has_empty_downstream(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """orders has no dependents → downstream is []."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders")
        _write_manifest(tmp_path, _fixture_users_and_orders())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders")
        assert profile is not None
        assert profile["downstream"] == []


class TestLineageKindDistinction:
    def test_kind_distinguishes_ref_from_source(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Upstream from both ref (users) and source (events). Kinds differ."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders")
        _write_manifest(tmp_path, _fixture_orders_with_source_and_ref_parents())
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders")
        assert profile is not None
        kinds_by_name = {r["table"]: r["kind"] for r in profile["upstream"]}
        assert kinds_by_name == {"users": "ref", "events": "source"}


class TestLineageNonTableFiltering:
    def test_filters_non_table_unique_ids(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """child_map entries with test.*, exposure.*, metric.* must not appear."""
        adapter = FakeAdapter()
        adapter.add_table("a", "orders")
        _write_manifest(
            tmp_path,
            _base_manifest(
                nodes={
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "a",
                        "name": "orders",
                    },
                    "test.test.unique_orders_id": {"resource_type": "test"},
                },
                parent_map={
                    "test.test.unique_orders_id": ["model.test.orders"],
                    "model.test.orders": [],
                },
                child_map={
                    "model.test.orders": [
                        "test.test.unique_orders_id",
                        "exposure.test.weekly_review",
                        "metric.test.revenue",
                    ],
                },
            ),
        )
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="a", table="orders")
        assert profile is not None
        assert profile["downstream"] == []

    def test_filters_non_table_upstream(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """parent_map entries with analysis.*, semantic_model.* don't appear."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders")
        _write_manifest(
            tmp_path,
            _base_manifest(
                nodes={
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "orders",
                    },
                },
                parent_map={
                    "model.test.orders": [
                        "analysis.test.report",
                        "semantic_model.test.revenue",
                        "unit_test.test.check",
                        "saved_query.test.q",
                    ],
                },
                child_map={},
            ),
        )
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders")
        assert profile is not None
        assert profile["upstream"] == []


class TestLineageSeedAndSnapshot:
    def test_seed_appears_as_upstream_ref(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Seeds are table-shaped and should appear as upstream with kind='ref'."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders")
        _write_manifest(
            tmp_path,
            _base_manifest(
                nodes={
                    "seed.test.country_codes": {
                        "resource_type": "seed",
                        "schema": "analytics",
                        "name": "country_codes",
                    },
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "orders",
                    },
                },
                parent_map={
                    "model.test.orders": ["seed.test.country_codes"],
                },
                child_map={
                    "seed.test.country_codes": ["model.test.orders"],
                    "model.test.orders": [],
                },
            ),
        )
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders")
        assert profile is not None
        assert profile["upstream"] == [
            {
                "model_name": "country_codes",
                "schema": "analytics",
                "table": "country_codes",
                "kind": "ref",
            }
        ]


class TestLineageModelNameVsTable:
    def test_model_name_is_dbt_symbol_table_is_warehouse_name(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """When a model has alias != name, model_name is the ref() symbol and
        table is the warehouse table name (identifier/alias). They must differ."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders_v2")  # warehouse table is the alias
        _write_manifest(
            tmp_path,
            _base_manifest(
                nodes={
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "orders",  # dbt symbol: ref('orders')
                        "alias": "orders_v2",  # warehouse table: orders_v2
                    },
                    "model.test.users": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "users",
                    },
                },
                parent_map={"model.test.orders": ["model.test.users"]},
                child_map={
                    "model.test.users": ["model.test.orders"],
                    "model.test.orders": [],
                },
            ),
        )
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders_v2")
        assert profile is not None
        upstream = profile["upstream"]
        assert len(upstream) == 1
        # model_name is the dbt ref() symbol; table is the warehouse name
        assert upstream[0]["model_name"] == "users"
        assert upstream[0]["table"] == "users"

    def test_source_model_name_is_name_table_is_identifier(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """For sources, model_name is source name (alias in source()), table is
        identifier (warehouse table name). They must differ when set."""
        adapter = FakeAdapter()
        adapter.add_table("analytics", "orders")
        _write_manifest(
            tmp_path,
            _base_manifest(
                nodes={
                    "model.test.orders": {
                        "resource_type": "model",
                        "schema": "analytics",
                        "name": "orders",
                    },
                },
                sources={
                    "source.test.raw.ev": {
                        "resource_type": "source",
                        "schema": "raw",
                        "source_name": "raw",
                        "name": "ev",  # alias in source('raw', 'ev')
                        "identifier": "events",  # actual warehouse table
                    },
                },
                parent_map={"model.test.orders": ["source.test.raw.ev"]},
                child_map={
                    "source.test.raw.ev": ["model.test.orders"],
                    "model.test.orders": [],
                },
            ),
        )
        src = DbtSchemaSource(adapter=adapter, project=local_project(tmp_path))
        profile = src.profile_table(schema="analytics", table="orders")
        assert profile is not None
        upstream = profile["upstream"]
        assert len(upstream) == 1
        assert upstream[0]["model_name"] == "ev"  # source alias
        assert upstream[0]["table"] == "events"  # warehouse identifier
        assert upstream[0]["kind"] == "source"
