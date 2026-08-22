"""Shared SQL type classification for the inspect module.

Provides a single source of truth for categorising database column types
as numeric, string, temporal, or complex.  Used by query_builder,
quality_detector, semantic_detector, and inspector.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Base-type normaliser
# ---------------------------------------------------------------------------

# Postgres-specific aliases → standard SQL type names
_POSTGRES_TYPE_MAP: dict[str, str] = {
    "INT2": "SMALLINT",
    "INT4": "INTEGER",
    "INT8": "BIGINT",
    "FLOAT4": "FLOAT",
    "FLOAT8": "DOUBLE",
    "BOOL": "BOOLEAN",
    "BPCHAR": "CHAR",
    "TIMESTAMPTZ": "TIMESTAMP",
    "TIMETZ": "TIME",
}


def extract_base_type(db_type: str, *, normalize_aliases: bool = False) -> str:
    """Extract base type name without precision, scale, or modifiers.

    Args:
        db_type: Raw database type string, e.g. ``"DECIMAL(18,2) NOT NULL"``.
        normalize_aliases: When True, map Postgres aliases to standard
            names (e.g. ``INT8`` → ``BIGINT``).

    Examples:
        >>> extract_base_type("DECIMAL(18,2)")
        'DECIMAL'
        >>> extract_base_type("int8", normalize_aliases=True)
        'BIGINT'
    """
    base = re.sub(r"\([^)]*\)", "", db_type.upper()).strip()
    for modifier in ("NOT NULL", "NULL", "PRIMARY KEY", "UNIQUE", "DEFAULT", "ARRAY"):
        base = base.replace(modifier, "").strip()
    base = base.split()[0] if base else base
    if normalize_aliases:
        base = _POSTGRES_TYPE_MAP.get(base, base)
    return base


# ---------------------------------------------------------------------------
# Canonical type sets  (superset across all supported databases)
# ---------------------------------------------------------------------------

# Integer types: exact whole-number values; subset of NUMERIC_TYPES.
# Includes all integer variants across supported warehouses (Postgres aliases,
# DuckDB unsigned, BigQuery INT64, MySQL MEDIUMINT, etc.).
INTEGER_TYPES: frozenset[str] = frozenset(
    {
        "INT",
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",  # MySQL
        "INT2",
        "INT4",
        "INT8",
        "INT16",
        "INT32",
        "INT64",  # Postgres aliases + BigQuery
        "HUGEINT",
        "UINTEGER",
        "UBIGINT",
        "USMALLINT",
        "UTINYINT",  # DuckDB unsigned
        "SERIAL",
        "BIGSERIAL",
        "SMALLSERIAL",  # Postgres auto-increment
    }
)

NUMERIC_TYPES: frozenset[str] = INTEGER_TYPES | frozenset(
    {
        "DECIMAL",
        "NUMERIC",
        "FLOAT",
        "DOUBLE",
        "REAL",
        "NUMBER",  # Oracle / Snowflake
        "FLOAT4",
        "FLOAT8",
        "FLOAT64",  # Postgres aliases + BigQuery
        "MONEY",  # Postgres money
    }
)

STRING_TYPES: frozenset[str] = frozenset(
    {
        "VARCHAR",
        "CHAR",
        "TEXT",
        "STRING",
        "CLOB",
        "NVARCHAR",
        "NCHAR",
        "NTEXT",
        "BPCHAR",  # Postgres blank-padded char
    }
)

TEMPORAL_TYPES: frozenset[str] = frozenset(
    {
        "DATE",
        "TIMESTAMP",
        "DATETIME",
        "TIME",
        "TIMESTAMPTZ",
        "TIMETZ",  # Postgres with timezone
        "TIMESTAMP_NTZ",
        "TIMESTAMP_LTZ",
        "TIMESTAMP_TZ",  # Snowflake variants
        "INTERVAL",
    }
)

COMPLEX_TYPES: frozenset[str] = frozenset(
    {
        "ARRAY",
        "STRUCT",
        "RECORD",
        "GEOGRAPHY",
        "GEOMETRY",
        "BYTES",
        "JSON",  # BigQuery
        "VARIANT",
        "OBJECT",  # Snowflake
        "MAP",  # Databricks
    }
)

# Prefixes that indicate a complex parameterised type (e.g. ARRAY<INT64>)
COMPLEX_PREFIXES: tuple[str, ...] = ("ARRAY<", "STRUCT<", "RECORD<", "MAP<")


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def is_numeric(db_type: str) -> bool:
    """Return True if *db_type* is a numeric column type."""
    return extract_base_type(db_type) in NUMERIC_TYPES


def is_string(db_type: str) -> bool:
    """Return True if *db_type* is a string/text column type."""
    return extract_base_type(db_type) in STRING_TYPES


def is_temporal(db_type: str) -> bool:
    """Return True if *db_type* is a date, time, or timestamp type."""
    return extract_base_type(db_type) in TEMPORAL_TYPES


def is_complex(db_type: str) -> bool:
    """Return True if *db_type* is a complex type unsuitable for standard aggregates."""
    upper = db_type.upper()
    if upper.startswith(COMPLEX_PREFIXES):
        return True
    return extract_base_type(db_type) in COMPLEX_TYPES
