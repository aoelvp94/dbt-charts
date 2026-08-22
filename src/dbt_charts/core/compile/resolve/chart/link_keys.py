"""Select URL-safe identity keys from factual column metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_VALID_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIXED_POINT_BASES: frozenset[str] = frozenset({"NUMBER", "DECIMAL", "NUMERIC"})
_UUID_TYPES: frozenset[str] = frozenset({"UUID"})
_STRING_KEY_TYPES: frozenset[str] = frozenset(
    {
        "VARCHAR",
        "CHAR",
        "TEXT",
        "STRING",
        "CLOB",
        "NVARCHAR",
        "NCHAR",
        "NTEXT",
        "BPCHAR",
    }
)
_INTEGER_KEY_TYPES: frozenset[str] = frozenset(
    {
        "INT",
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",
        "INT2",
        "INT4",
        "INT8",
        "INT16",
        "INT32",
        "INT64",
        "HUGEINT",
        "UINTEGER",
        "UBIGINT",
        "USMALLINT",
        "UTINYINT",
        "SERIAL",
        "BIGSERIAL",
        "SMALLSERIAL",
    }
)
_COMPLEX_KEY_TYPES: frozenset[str] = frozenset(
    {
        "ARRAY",
        "STRUCT",
        "RECORD",
        "GEOGRAPHY",
        "GEOMETRY",
        "BYTES",
        "JSON",
        "VARIANT",
        "OBJECT",
        "MAP",
    }
)
_COMPLEX_KEY_PREFIXES: tuple[str, ...] = ("ARRAY<", "STRUCT<", "RECORD<", "MAP<")


def _extract_base_type(db_type: str) -> str:
    base = re.sub(r"\([^)]*\)", "", db_type.upper()).strip()
    for modifier in ("NOT NULL", "NULL", "PRIMARY KEY", "UNIQUE", "DEFAULT", "ARRAY"):
        base = base.replace(modifier, "").strip()
    return base.split()[0] if base else base


def is_complex_db_type(db_type: str) -> bool:
    upper = db_type.upper()
    if upper.startswith(_COMPLEX_KEY_PREFIXES):
        return True
    return _extract_base_type(db_type) in _COMPLEX_KEY_TYPES


def _fixed_point_scale(db_type: str) -> int:
    match = re.search(r"\(\s*\d+\s*,\s*(\d+)\s*\)", db_type)
    return int(match.group(1)) if match else 0


def is_identity_keyable(db_type: str) -> bool:
    """Whether a value round-trips exactly through a URL equality parameter."""
    if is_complex_db_type(db_type):
        return False
    base = _extract_base_type(db_type)
    if base in _STRING_KEY_TYPES or base in _INTEGER_KEY_TYPES or base in _UUID_TYPES:
        return True
    if base in _FIXED_POINT_BASES:
        return _fixed_point_scale(db_type) == 0
    return False


def is_string_key(db_type: str) -> bool:
    """Whether an identity-key value needs URL percent-encoding."""
    if is_complex_db_type(db_type):
        return False
    base = _extract_base_type(db_type)
    return base in _STRING_KEY_TYPES or base in _UUID_TYPES


def is_valid_column_identifier(name: str) -> bool:
    return bool(_VALID_ID_RE.match(name))


def plan_link_keys(
    rows: Sequence[Mapping[str, str]],
) -> list[dict[str, str | bool]]:
    """Pick the minimal row-identity key for an index-to-detail link."""
    candidates = [
        row
        for row in rows
        if is_valid_column_identifier(row["name"])
        and is_identity_keyable(row["actual_type"])
        and (row["name"] == "id" or row["name"].endswith("_id"))
    ]
    exact = [row for row in candidates if row["name"] == "id"]
    chosen = exact if exact else candidates
    return [
        {
            "name": row["name"],
            "encode": is_string_key(row["actual_type"]),
        }
        for row in chosen
    ]
