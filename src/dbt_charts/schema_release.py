"""Release-time writer and verifier for immutable Dataface YAML schemas."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from dbt_charts.core.compile.schema.introspection import introspect
from dbt_charts.core.compile.schema.renderers.json_schema import render_yaml_schema
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaEntry,
    canonical_schema_bytes,
    load_yaml_schema_catalog_from,
)


def freeze_yaml_schema(
    directory: Path,
    *,
    version: str,
    released_at: date,
    candidate: dict[str, Any],
) -> YamlSchemaEntry:
    """Append a changed candidate under its Dataface release version."""
    candidate_bytes = canonical_schema_bytes(candidate)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        catalog = load_yaml_schema_catalog_from(directory)
        if candidate_bytes == canonical_schema_bytes(
            catalog.schema_for(catalog.latest.version)
        ):
            return catalog.latest
        predecessor = catalog.latest.version
    else:
        predecessor = None

    filename = f"{version}.json"
    snapshot_path = directory / filename
    if snapshot_path.exists():
        raise FileExistsError(
            f"Frozen Dataface YAML schema already exists: {snapshot_path}"
        )

    directory.mkdir(parents=True, exist_ok=True)
    frozen = YamlSchemaEntry(
        version=version,
        released_at=released_at,
        filename=filename,
        sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        predecessor=predecessor,
    )
    snapshot_path.write_bytes(candidate_bytes)

    entries = (
        []
        if not manifest_path.exists()
        else json.loads(manifest_path.read_text(encoding="utf-8"))["schemas"]
    )
    entries.append(frozen.as_json())
    manifest_path.write_text(
        json.dumps({"schemas": entries}, indent=2) + "\n", encoding="utf-8"
    )
    return frozen


def verify_released_yaml_schema(
    directory: Path,
    *,
    version: str,
    candidate: dict[str, Any],
) -> None:
    """Ensure the release tag packages the current YAML grammar snapshot."""
    catalog = load_yaml_schema_catalog_from(directory)
    if _version_key(catalog.latest.version) > _version_key(version):
        raise ValueError(
            f"Latest Dataface YAML schema {catalog.latest.version} is newer than "
            f"the Dataface release {version}."
        )
    if canonical_schema_bytes(
        catalog.schema_for(catalog.latest.version)
    ) != canonical_schema_bytes(candidate):
        raise ValueError(
            f"Dataface {version} has an unfrozen YAML grammar. Run "
            f"`just freeze-yaml-schema {version} <released_at>` and commit "
            "the result."
        )


def _version_key(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(
            f"Dataface release version must be MAJOR.MINOR.PATCH, got {version!r}."
        )
    major, minor, patch = parts
    return int(major), int(minor), int(patch)


def main() -> None:
    """Freeze or verify the current authored grammar for a Dataface release."""
    parser = argparse.ArgumentParser(
        description="Append or verify a changed Dataface YAML schema."
    )
    parser.add_argument("version")
    parser.add_argument("released_at", type=date.fromisoformat, nargs="?")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).parent / "data" / "schemas" / "yaml",
    )
    args = parser.parse_args()
    directory: Path = args.directory
    candidate = render_yaml_schema(introspect())
    if args.verify:
        verify_released_yaml_schema(
            directory, version=args.version, candidate=candidate
        )
        return
    if args.released_at is None:
        parser.error("released_at is required unless --verify is used")
    frozen = freeze_yaml_schema(
        directory,
        version=args.version,
        released_at=args.released_at,
        candidate=candidate,
    )
    print(frozen.version)


if __name__ == "__main__":
    main()
