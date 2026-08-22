"""DuckDB connection config validation shared by query and inspect paths."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ALLOWED_DUCKDB_CONFIG_KEYS: frozenset[str] = frozenset({"enable_external_access"})


def normalize_duckdb_config(
    source_config: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the configured DuckDB config mapping, if any."""
    duckdb_config = source_config.get("duckdb_config")
    if duckdb_config is None:
        return None
    if not isinstance(duckdb_config, dict):
        raise ValueError("duckdb_config must be a mapping")
    unknown = set(duckdb_config) - ALLOWED_DUCKDB_CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"Unsupported duckdb_config keys: {sorted(unknown)}. "
            f"Allowed: {sorted(ALLOWED_DUCKDB_CONFIG_KEYS)}"
        )
    return dict(duckdb_config) if duckdb_config else None
