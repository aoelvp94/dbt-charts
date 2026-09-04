"""Load immutable dbt charts YAML schemas packaged with dbt charts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from types import NoneType
from typing import Literal, Protocol, TypeAlias

from importlib_resources import files

JsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | Literal[None]
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


class _SchemaResource(Protocol):
    def joinpath(self, *_: str) -> _SchemaResource: ...

    def read_bytes(self) -> bytes: ...

    def read_text(self, encoding: str) -> str: ...


@dataclass(frozen=True)
class YamlSchemaEntry:
    """One immutable board-YAML grammar snapshot."""

    version: str
    released_at: date
    filename: str
    sha256: str
    predecessor: str | Literal[None]

    @classmethod
    def from_json(cls, value: JsonObject) -> YamlSchemaEntry:
        predecessor = value["predecessor"]
        if not isinstance(predecessor, (str, NoneType)):
            raise ValueError(
                "dbt charts YAML schema manifest predecessor must be a string or null."
            )
        return cls(
            version=_manifest_string(value, "version"),
            released_at=_manifest_date(value, "released_at"),
            filename=_manifest_string(value, "file"),
            sha256=_manifest_string(value, "sha256"),
            predecessor=predecessor,
        )

    def as_json(self) -> JsonObject:
        return {
            "version": self.version,
            "released_at": self.released_at.isoformat(),
            "file": self.filename,
            "sha256": self.sha256,
            "predecessor": self.predecessor,
        }


@dataclass(frozen=True)
class YamlSchemaCatalog:
    """Frozen dbt charts YAML schemas indexed by version, newest to oldest.

    ``current_schema`` is the live JSON schema generated from the Pydantic models right
    now — it is never written to disk, never sha256-checked, and may differ from the
    latest frozen snapshot when unreleased model changes are in flight.  Use it wherever
    "what does the current grammar accept?" is the question (recognition, migration
    target check), not "what does a specific release accept?"
    """

    entries: tuple[YamlSchemaEntry, ...]
    _schemas: dict[str, JsonObject]
    current_schema: JsonObject

    @property
    def latest(self) -> YamlSchemaEntry:
        return self.entries[0]

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(entry.version for entry in self.entries)

    def schema_for(self, version: str) -> JsonObject:
        return self._schemas[version]


def _manifest_string(value: JsonObject, key: str) -> str:
    result = value[key]
    if not isinstance(result, str):
        raise ValueError(f"dbt charts YAML schema manifest {key} must be a string.")
    return result


def _manifest_date(value: JsonObject, key: str) -> date:
    try:
        return date.fromisoformat(_manifest_string(value, key))
    except ValueError as error:
        raise ValueError(
            f"dbt charts YAML schema manifest {key} must be an ISO date."
        ) from error


_DOTTED_VERSION_RE = re.compile(r"^(\d{1,9})\.(\d{1,9})\.(\d{1,9})\Z", re.ASCII)


def parse_dotted_version(value: str) -> tuple[int, int, int] | None:
    """Parse an ``X.Y.Z`` version string; ``None`` if it isn't exactly that shape.

    Never raises. Shared by the migration-stamp and diagnostic-hint call
    sites that compare a manifest version (always this shape) against a
    value that might not be (a hand-authored ``_schema_version``, migration
    test fixtures) -- one strict parser so "genuinely newer", "not
    comparable", and "malformed" agree between the two, rather than each
    risking its own definition of "close enough". A strict ASCII-digit
    regex, not ``int()`` directly: ``int()`` also accepts leading/trailing
    whitespace, a leading ``+``, ``_`` digit-group separators, and
    non-ASCII decimal digits, any of which would otherwise produce a
    confidently wrong comparison. ``\\Z``, not ``$``, anchors the end: ``$``
    also matches immediately before a trailing newline.
    """
    match = _DOTTED_VERSION_RE.match(value)
    if match is None:
        return None
    return (int(match[1]), int(match[2]), int(match[3]))


def canonical_schema_bytes(schema: JsonObject) -> bytes:
    """Serialize a schema once so release comparisons are byte-for-byte stable."""
    return (json.dumps(schema, separators=(",", ":"), sort_keys=True) + "\n").encode()


def load_yaml_schema_catalog() -> YamlSchemaCatalog:
    """Load the package's immutable dbt charts YAML schemas."""
    return load_yaml_schema_catalog_from(
        files("dbt_charts") / "data" / "schemas" / "yaml"
    )


def load_yaml_schema_catalog_from(
    directory: _SchemaResource,
) -> YamlSchemaCatalog:
    """Load and verify a catalog directory; intended for package data and tests."""
    manifest: JsonValue = json.loads(
        directory.joinpath("manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(manifest, dict) or "schemas" not in manifest:
        raise ValueError("dbt charts YAML schema manifest has no schemas.")
    raw_entries = manifest["schemas"]
    if not isinstance(raw_entries, list):
        raise ValueError("dbt charts YAML schema manifest schemas must be a list.")
    if not raw_entries:
        raise ValueError("dbt charts YAML schema manifest has no schemas.")

    entries = tuple(
        YamlSchemaEntry.from_json(value)
        for value in raw_entries
        if isinstance(value, dict)
    )
    if len(entries) != len(raw_entries):
        raise ValueError("dbt charts YAML schema manifest entries must be objects.")
    if len({entry.version for entry in entries}) != len(entries):
        raise ValueError("dbt charts YAML schema manifest has duplicate versions.")

    schemas: dict[str, JsonObject] = {}
    predecessor: str | Literal[None] = None
    previous_date: date | Literal[None] = None
    for entry in entries:
        if entry.predecessor != predecessor:
            raise ValueError(
                f"dbt charts YAML schema {entry.version} has predecessor "
                f"{entry.predecessor!r}, expected {predecessor!r}."
            )
        if previous_date is not None and entry.released_at < previous_date:
            raise ValueError(
                "dbt charts YAML schema manifest release dates must be chronological."
            )
        contents = directory.joinpath(entry.filename).read_bytes()
        digest = hashlib.sha256(contents).hexdigest()
        if digest != entry.sha256:
            raise ValueError(
                f"dbt charts YAML schema {entry.filename} sha256 does not match its manifest."
            )
        schema: JsonValue = json.loads(contents)
        if not isinstance(schema, dict):
            raise ValueError(
                f"dbt charts YAML schema {entry.filename} must be an object."
            )
        schemas[entry.version] = schema
        predecessor = entry.version
        previous_date = entry.released_at

    return YamlSchemaCatalog(
        tuple(reversed(entries)), schemas, _compute_current_schema()
    )


def _compute_current_schema() -> JsonObject:
    """Generate the live JSON schema from the current Pydantic models."""
    from dbt_charts.core.compile.schema.introspection import introspect
    from dbt_charts.core.compile.schema.renderers.json_schema import render_yaml_schema

    return render_yaml_schema(introspect())
