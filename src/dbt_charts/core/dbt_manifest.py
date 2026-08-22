"""Neutral-leaf dbt manifest loader.

Owns: Project-seam reads, schema-version validation gate, RefIndex
derivation, and per-process content-addressed memo.

LoadedManifest.raw (the plain json.loads dict) is the data contract for all
downstream consumers. WritableManifest.is_compatible_version gates on schema
version; the typed round-trip (upgrade_schema_version / from_dict) is NOT
called on the runtime path because from_dict requires top-level keys
(macros, docs, exposures, …) that no consumer reads, and a manifest missing
any one of them would turn a routine degrade (no lineage, no FK links) into
a hard ERR-DBT-MANIFEST-INCOMPATIBLE. The round-trip belongs in the test
canary that pins the dbt-core version range (see test_dbt_manifest.py).

Public symbols:
  MANIFEST_CANDIDATES             tuple of candidate relpaths, in order
  load_manifest(project)          -> LoadedManifest | None
  load_manifest_at(project, rel)  -> LoadedManifest
  ref_index(loaded)               -> RefIndex

The dbt.contracts import is function-local — `dct --help` pays nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dbt_charts.core.diagnostics.codes_execute import ERR_DBT_MANIFEST_INCOMPATIBLE
from dbt_charts.core.diagnostics.execution import ExecutionError

if TYPE_CHECKING:
    from dbt_charts.core.project import Project

# Candidate paths, checked in this order. `dbt parse`/`dbt compile`/`dbt run`
# all write target/manifest.json; there is no committed-snapshot fallback —
# a project without one is manifest-missing.
MANIFEST_CANDIDATES: tuple[str, ...] = ("target/manifest.json",)

# Node kinds ref() addresses.
_REFABLE_RESOURCE_TYPES = frozenset({"model", "seed", "snapshot"})

# Per-process memo: (relpath, file_version) → LoadedManifest.
# FIFO-evicting at _MEMO_MAXSIZE; relpath in key avoids collisions when two
# candidates share identical content.
_MEMO_MAXSIZE = 16
_memo: dict[tuple[str, str], LoadedManifest] = {}


@dataclass(frozen=True)
class LoadedManifest:
    """Transport wrapper for a loaded dbt manifest.

    raw:     Plain json.loads dict — the data contract for all downstream
             consumers. dbt 1.11.x mashumaro union types ALL test nodes as
             SingularTest, so test_metadata is inaccessible on typed nodes;
             raw dict access is the only reliable path.
    relpath: Which candidate path was used to load this manifest.
    """

    raw: dict[str, Any]
    relpath: str


@dataclass(frozen=True)
class RefIndex:
    """Compact derived index for ref()/source() resolution and did-you-mean.

    refs:              name → (relation_name, schema) for model/seed/snapshot.
    sources:           (source_name, table) → (relation_name, schema).
    available_refs:    sorted ref names for unknown-ref diagnostics.
    available_sources: sorted "source.table" strings for unknown-source diagnostics.
    """

    refs: dict[str, tuple[str, str]]
    sources: dict[tuple[str, str], tuple[str, str]]
    available_refs: list[str]
    available_sources: list[str]


def load_manifest(project: Project) -> LoadedManifest | None:
    """Load and parse the project's dbt manifest through the Project seam.

    Checks candidates in order, returns the first one that exists. Returns
    None when no candidate exists.

    Raises ExecutionError (ERR-DBT-MANIFEST-INCOMPATIBLE) when a candidate
    exists but is corrupt or incompatible with the installed dbt-core.
    """
    for relpath in MANIFEST_CANDIDATES:
        if not project.exists(relpath):
            continue
        return load_manifest_at(project, relpath)
    return None


def ref_index(loaded: LoadedManifest) -> RefIndex:
    """Derive the compact ref/source index from a LoadedManifest.

    Reads from loaded.raw (the pre-upgrade dict). First-wins for cross-package
    name collisions, matching the order nodes appear in the manifest.
    """
    refs: dict[str, tuple[str, str]] = {}
    sources: dict[tuple[str, str], tuple[str, str]] = {}

    for node in loaded.raw.get("nodes", {}).values():
        if node.get("resource_type") not in _REFABLE_RESOURCE_TYPES:
            continue
        name: str = node["name"]
        schema: str = node["schema"]
        if node.get("relation_name"):
            rel = str(node["relation_name"])
        else:
            alias = str(node.get("alias") or name)
            rel = f"{schema}.{alias}"
        refs.setdefault(name, (rel, schema))

    for node in loaded.raw.get("sources", {}).values():
        source_name = node.get("source_name")
        table_name = node.get("name")
        if not source_name or not table_name:
            continue
        schema = str(node["schema"])
        if node.get("relation_name"):
            rel = str(node["relation_name"])
        else:
            rel = f"{schema}.{table_name}"
        sources.setdefault((source_name, table_name), (rel, schema))

    available_refs = sorted(refs)
    available_sources = sorted(f"{s}.{t}" for s, t in sources)
    return RefIndex(
        refs=refs,
        sources=sources,
        available_refs=available_refs,
        available_sources=available_sources,
    )


def load_manifest_at(project: Project, relpath: str) -> LoadedManifest:
    """Load and parse a manifest from a specific project-relative path.

    Memoised per process on project.file_version(relpath). Use this when
    a caller needs to load a specific path independently of which candidate
    was used for the dev load.

    Raises ExecutionError (ERR-DBT-MANIFEST-INCOMPATIBLE) on corrupt JSON,
    unreadable file, or incompatible schema version.
    """
    from dbt.contracts.graph.manifest import WritableManifest  # noqa: PLC0415

    try:
        version = project.file_version(relpath)
        memo_key = (relpath, version)
        if memo_key in _memo:
            return _memo[memo_key]

        raw_text = project.read_text(relpath)
        raw: dict[str, Any] = json.loads(raw_text)

        metadata = raw.get("metadata")
        schema_version = metadata.get("dbt_schema_version") if metadata else None
        # WritableManifest.is_compatible_version carries no type annotations in
        # dbt-core (no py.typed marker); Any is the honest boundary type here,
        # not a laundered ignore.
        is_compatible_version: Any = WritableManifest.is_compatible_version
        if schema_version and not is_compatible_version(schema_version):
            raise ExecutionError.from_code(
                ERR_DBT_MANIFEST_INCOMPATIBLE,
                relpath=relpath,
                detail=(
                    f"schema version {schema_version!r} is not compatible "
                    "with the installed dbt-core"
                ),
            )
    except ExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001 — OSError/JSONDecodeError/AttributeError
        raise ExecutionError.from_code(
            ERR_DBT_MANIFEST_INCOMPATIBLE,
            relpath=relpath,
            detail=str(exc),
        ) from exc

    loaded = LoadedManifest(raw=raw, relpath=relpath)
    if len(_memo) >= _MEMO_MAXSIZE:
        _memo.pop(next(iter(_memo)))
    _memo[memo_key] = loaded
    return loaded
