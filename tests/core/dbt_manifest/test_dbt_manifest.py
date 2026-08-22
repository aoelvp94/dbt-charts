"""Tests for core/dbt_manifest.py — the neutral-leaf manifest loader.

Covers: candidate order, file_version-keyed memo (hit / invalidation / FIFO
eviction), error paths (incompatible schema version, corrupt JSON), manifests
that are missing dbt-internal top-level keys, and the upgrade_schema_version
drift canary that pins the installed dbt-core version range.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import dbt_charts.core.dbt_manifest as _mod
from dbt_charts.core.dbt_manifest import (
    MANIFEST_CANDIDATES,
    load_manifest,
    load_manifest_at,
    ref_index,
)
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.project import Project

from ..._paths import DBT_CHARTS_DIR

_FIXTURES = DBT_CHARTS_DIR / "tests" / "fixtures"
_DBT_CORE_MANIFEST_PATH = _FIXTURES / "dbt_core_manifest" / "manifest.json"
_FUSION_MANIFEST_PATH = _FIXTURES / "fusion_manifest" / "manifest.json"

_MINIMAL_MANIFEST = json.dumps(
    {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
        },
        "nodes": {
            "model.analytics.orders": {
                "resource_type": "model",
                "name": "orders",
                "schema": "analytics",
                "alias": "orders",
            }
        },
        "sources": {},
    }
)

_FUTURE_VERSION_MANIFEST = json.dumps(
    {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v999.json"
        },
        "nodes": {
            "model.analytics.orders": {
                "resource_type": "model",
                "name": "orders",
                "schema": "analytics",
            }
        },
        "sources": {},
    }
)


@pytest.fixture(autouse=True)
def clear_manifest_memo() -> None:
    """Isolate each test from prior memo entries."""
    _mod._memo.clear()


class TestManifestCandidate:
    """target/manifest.json is the only candidate — no committed-snapshot fallback."""

    def test_target_manifest_loads(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        project = in_memory_project(
            tmp_path, {"target/manifest.json": _MINIMAL_MANIFEST}
        )

        loaded = load_manifest(project)

        assert loaded is not None
        assert loaded.relpath == "target/manifest.json"

    def test_snapshot_only_project_is_manifest_missing(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        """A project carrying only manifest.snapshot.json is manifest-missing —
        the candidate was removed, not aliased (no read-fallback)."""
        project = in_memory_project(
            tmp_path, {"manifest.snapshot.json": _MINIMAL_MANIFEST}
        )

        assert load_manifest(project) is None

    def test_stray_snapshot_file_is_ignored_when_target_manifest_present(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        """A leftover manifest.snapshot.json alongside target/manifest.json is
        never consulted — target/ wins regardless of what else sits beside it.
        (The regression detector for the removed candidate itself is
        test_snapshot_only_project_is_manifest_missing above.)"""
        target_content = json.dumps(
            {
                "metadata": {
                    "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
                },
                "nodes": {},
                "sources": {},
            }
        )
        snapshot_content = json.dumps(
            {
                "metadata": {
                    "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
                },
                "nodes": {
                    "model.x.sentinel": {
                        "resource_type": "model",
                        "name": "sentinel",
                        "schema": "s",
                    }
                },
                "sources": {},
            }
        )
        project = in_memory_project(
            tmp_path,
            {
                "target/manifest.json": target_content,
                "manifest.snapshot.json": snapshot_content,
            },
        )

        loaded = load_manifest(project)

        assert loaded is not None
        assert loaded.relpath == "target/manifest.json"
        assert "sentinel" not in {
            n["name"] for n in loaded.raw.get("nodes", {}).values()
        }

    def test_returns_none_when_no_manifest_present(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        project = in_memory_project(tmp_path, {})

        assert load_manifest(project) is None

    def test_manifest_candidates_contains_only_target(self) -> None:
        assert MANIFEST_CANDIDATES == ("target/manifest.json",)


class TestMemo:
    """file_version-keyed memo: hit → no re-read; invalidation on version change."""

    def test_same_version_returns_same_object(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        project = in_memory_project(
            tmp_path, {"target/manifest.json": _MINIMAL_MANIFEST}
        )

        first = load_manifest(project)
        second = load_manifest(project)

        assert first is second

    def test_memo_hit_skips_read(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = in_memory_project(
            tmp_path, {"target/manifest.json": _MINIMAL_MANIFEST}
        )

        read_count = 0
        real_read = project.read_text

        def counting_read(relpath: str) -> str:
            nonlocal read_count
            read_count += 1
            return real_read(relpath)

        monkeypatch.setattr(project, "read_text", counting_read)

        load_manifest(project)
        assert read_count == 1

        load_manifest(project)
        assert read_count == 1  # second call hit the memo — no re-read

    def test_changed_version_invalidates_memo(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        files: dict[str, str] = {"target/manifest.json": _MINIMAL_MANIFEST}
        project = in_memory_project(tmp_path, files)

        first = load_manifest(project)

        # Change content → new file_version hash
        new_content = json.dumps(
            {
                "metadata": {
                    "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
                },
                "nodes": {
                    "model.analytics.customers": {
                        "resource_type": "model",
                        "name": "customers",
                        "schema": "analytics",
                    }
                },
                "sources": {},
            }
        )
        files["target/manifest.json"] = new_content

        second = load_manifest(project)

        assert second is not first
        assert "customers" in {n["name"] for n in second.raw["nodes"].values()}  # type: ignore[union-attr]

    def test_memo_fifo_eviction_at_maxsize(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        """When _MEMO_MAXSIZE entries are present, adding one more evicts the oldest."""
        from dbt_charts.core.dbt_manifest import _MEMO_MAXSIZE

        # Fill the memo to capacity using distinct relpaths
        for i in range(_MEMO_MAXSIZE):
            content = json.dumps(
                {
                    "metadata": {
                        "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
                    },
                    "nodes": {
                        f"model.x.m{i}": {
                            "resource_type": "model",
                            "name": f"m{i}",
                            "schema": "s",
                        }
                    },
                    "sources": {},
                }
            )
            project = in_memory_project(tmp_path, {f"path{i}.json": content})
            load_manifest_at(project, f"path{i}.json")

        assert len(_mod._memo) == _MEMO_MAXSIZE

        # The key for path0 (the first one loaded) should be in the memo still
        first_key = next(iter(_mod._memo))

        # One more entry evicts the oldest
        extra_content = json.dumps(
            {
                "metadata": {
                    "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
                },
                "nodes": {},
                "sources": {},
            }
        )
        project = in_memory_project(tmp_path, {"extra.json": extra_content})
        load_manifest_at(project, "extra.json")

        assert len(_mod._memo) == _MEMO_MAXSIZE
        assert first_key not in _mod._memo


class TestErrorPaths:
    """Incompatible schema version and corrupt JSON both raise ERR-DBT-MANIFEST-INCOMPATIBLE."""

    def test_future_schema_version_raises_incompatible(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        project = in_memory_project(
            tmp_path, {"target/manifest.json": _FUTURE_VERSION_MANIFEST}
        )

        with pytest.raises(DbtChartsError) as exc_info:
            load_manifest(project)

        assert exc_info.value.code is not None
        assert exc_info.value.code.code == "ERR-DBT-MANIFEST-INCOMPATIBLE"
        assert "v999" in str(exc_info.value)

    def test_corrupt_json_raises_incompatible(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        project = in_memory_project(
            tmp_path, {"target/manifest.json": "{ not valid json {{"}
        )

        with pytest.raises(DbtChartsError) as exc_info:
            load_manifest(project)

        assert exc_info.value.code is not None
        assert exc_info.value.code.code == "ERR-DBT-MANIFEST-INCOMPATIBLE"

    def test_incompatible_error_names_the_relpath(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        """load_manifest_at names whatever relpath the caller passed — not
        restricted to MANIFEST_CANDIDATES entries."""
        project = in_memory_project(
            tmp_path, {"custom/manifest.json": _FUTURE_VERSION_MANIFEST}
        )

        with pytest.raises(DbtChartsError) as exc_info:
            load_manifest_at(project, "custom/manifest.json")

        assert "custom/manifest.json" in str(exc_info.value)


class TestMissingTopLevelKeys:
    """A manifest without macros/docs/exposures/etc. loads successfully.

    The runtime path reads the raw dict — it does NOT call
    WritableManifest.from_dict (which requires those keys). This test pins
    that invariant so a future refactor that accidentally re-introduces the
    typed round-trip on the runtime path fails loudly.
    """

    def test_manifest_without_dbt_internal_keys_loads_successfully(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        bare = json.dumps(
            {
                "metadata": {
                    "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
                },
                "nodes": {
                    "model.analytics.orders": {
                        "resource_type": "model",
                        "name": "orders",
                        "schema": "analytics",
                        "relation_name": "analytics.orders",
                    }
                },
                "sources": {},
                # deliberately omitted: macros, docs, exposures, metrics,
                # groups, child_map, parent_map, …
            }
        )
        project = in_memory_project(tmp_path, {"target/manifest.json": bare})

        loaded = load_manifest(project)

        assert loaded is not None
        index = ref_index(loaded)
        assert "orders" in index.refs

    def test_ref_index_from_minimal_manifest(
        self,
        in_memory_project: Callable[..., Project],
        tmp_path: Path,
    ) -> None:
        project = in_memory_project(
            tmp_path, {"target/manifest.json": _MINIMAL_MANIFEST}
        )
        loaded = load_manifest(project)
        assert loaded is not None

        index = ref_index(loaded)

        assert "orders" in index.refs
        assert index.refs["orders"][1] == "analytics"
        assert "orders" in index.available_refs


class TestWritableManifestUpgradeSchemaVersionCanary:
    """Drift canary: both real fixtures must round-trip through
    WritableManifest.upgrade_schema_version without error.

    If dbt-core drops support for v12 manifests, or the installed version
    changes the is_compatible_version range, this test fails — a clear signal
    to update the pin in dbt-charts/pyproject.toml and regenerate the fixtures.
    """

    def test_dbt_core_manifest_is_compatible_and_upgrades(self) -> None:
        from dbt.contracts.graph.manifest import WritableManifest

        raw = json.loads(_DBT_CORE_MANIFEST_PATH.read_text())
        schema_version = raw["metadata"]["dbt_schema_version"]

        assert WritableManifest.is_compatible_version(schema_version), (
            f"dbt-Core fixture schema version {schema_version!r} is no longer "
            "compatible with the installed dbt-core — update the pin"
        )

        upgraded = WritableManifest.upgrade_schema_version(raw)
        assert isinstance(upgraded, WritableManifest)

    def test_fusion_manifest_is_compatible(self) -> None:
        from dbt.contracts.graph.manifest import WritableManifest

        raw = json.loads(_FUSION_MANIFEST_PATH.read_text())
        schema_version = raw["metadata"]["dbt_schema_version"]

        assert WritableManifest.is_compatible_version(schema_version), (
            f"fusion fixture schema version {schema_version!r} is no longer "
            "compatible with the installed dbt-core — update the pin"
        )
