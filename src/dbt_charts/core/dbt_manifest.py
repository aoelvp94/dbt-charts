"""Neutral-leaf dbt manifest loader.

Owns: Project-seam reads, RefIndex derivation, and per-process
content-addressed memo.

LoadedManifest.raw (the plain json.loads dict) is the data contract for all
downstream consumers. Nothing here deserialises through dbt's typed
WritableManifest, so metadata.dbt_schema_version is not read: the handful of
node keys this module touches (resource_type, name, schema, alias,
relation_name, source_name) have been stable across every manifest version,
and gating on the version string only turns a manifest we read correctly into
a hard error. A node whose shape has genuinely drifted is skipped, so the
board author sees ERR-DBT-REF-UNKNOWN-NODE / ERR-DBT-SOURCE-UNKNOWN-TABLE
naming the ref they wrote rather than a KeyError.

Public symbols:
  MANIFEST_CANDIDATES             tuple of candidate relpaths, in order
  load_manifest(project)          -> LoadedManifest | None
  load_manifest_at(project, rel)  -> LoadedManifest
  ref_index(loaded)               -> RefIndex
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dbt_charts.core.diagnostics.codes_execute import ERR_DBT_MANIFEST_UNREADABLE
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
    version: ``project.file_version(relpath)`` at load time — the stable
             identity downstream memos key on (``id(raw)`` can be reused
             after GC, silently serving one manifest's derivation for
             another).
    """

    raw: dict[str, Any]
    relpath: str
    version: str


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

    Raises ExecutionError (ERR-DBT-MANIFEST-UNREADABLE) when a candidate
    exists but is unreadable or corrupt.
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
        name = node.get("name")
        schema = node.get("schema")
        if not name or not schema:
            continue
        if node.get("relation_name"):
            rel = str(node["relation_name"])
        else:
            alias = str(node.get("alias") or name)
            rel = f"{schema}.{alias}"
        refs.setdefault(name, (rel, schema))

    for node in loaded.raw.get("sources", {}).values():
        source_name = node.get("source_name")
        table_name = node.get("name")
        schema = node.get("schema")
        if not source_name or not table_name or not schema:
            continue
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

    Raises ExecutionError (ERR-DBT-MANIFEST-UNREADABLE) on an unreadable file
    or corrupt JSON.
    """
    try:
        version = project.file_version(relpath)
        memo_key = (relpath, version)
        if memo_key in _memo:
            return _memo[memo_key]

        raw_text = project.read_text(relpath)
        raw = json.loads(raw_text)
        if not isinstance(raw, dict):
            raise ExecutionError.from_code(
                ERR_DBT_MANIFEST_UNREADABLE,
                relpath=relpath,
                detail=f"top-level JSON is {type(raw).__name__}, not an object",
            )
    except ExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001 — OSError/JSONDecodeError from the seam
        raise ExecutionError.from_code(
            ERR_DBT_MANIFEST_UNREADABLE,
            relpath=relpath,
            detail=str(exc),
        ) from exc

    loaded = LoadedManifest(raw=raw, relpath=relpath, version=version)
    if len(_memo) >= _MEMO_MAXSIZE:
        _memo.pop(next(iter(_memo)))
    _memo[memo_key] = loaded
    return loaded
