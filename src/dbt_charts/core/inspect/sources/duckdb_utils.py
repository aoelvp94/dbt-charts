"""DuckDB-specific helpers for schema inspection.

When a DuckDB adapter connects to a file (e.g. ``dundersign.duckdb``),
the database is attached under a non-system name (e.g. ``dundersign``).
Passing ``None`` to ``adapter.list_relations(None, schema)`` returns an
empty list for file-backed databases — the database argument must be the
actual attach name.

``PRAGMA database_list`` is the authoritative source: each row is
``(seq, name, file)``.  We skip the two system databases (``system`` and
``temp``); the remaining row is the user's attached database.  For
``path=None`` or ``path=':memory:'`` the attach name is always ``memory``.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TID251 — resolves a DuckDB database file path
from typing import Any


def duckdb_resolve_database(adapter: Any, db_path: str | Path | None) -> str:
    """Return the DuckDB attach name that ``list_relations`` must receive.

    Reads ``PRAGMA database_list`` from the already-open adapter connection.
    The caller must be inside a ``connection_named`` context.

    ``db_path`` is the configured file path (or ``None`` / ``':memory:'`` for
    in-memory).  When the path is in-memory we short-circuit and return
    ``'memory'`` without a PRAGMA round-trip.

    For file-backed databases we prefer the row whose ``file`` column matches
    the absolute ``db_path``; if no row matches (e.g. path is relative or
    symlinked) we fall back to the first non-system entry.

    Raises ``ValueError`` if no non-system database is found in the pragma
    output — this would indicate a DuckDB connection without an attached
    database, which should be impossible for a live adapter.
    """
    path_str = str(db_path) if db_path is not None else None
    if path_str is None or path_str == ":memory:":
        return "memory"

    _, result = adapter.execute("PRAGMA database_list", fetch=True)
    # Rows are (seq, name, file).  Column order is stable in DuckDB.
    # System databases to skip: 'system' and 'temp'.
    _SKIP = frozenset({"system", "temp"})

    abs_path = str(Path(path_str).resolve())
    candidates: list[str] = []
    for row in result.rows:
        name = str(row[1])
        file_col = str(row[2])
        if name in _SKIP:
            continue
        # Prefer exact match on resolved absolute path.
        if file_col == abs_path:
            return name
        candidates.append(name)

    if candidates:
        return candidates[0]

    raise ValueError(
        f"PRAGMA database_list returned no non-system database for path {path_str!r}. "
        "This is unexpected for a live DuckDB file-backed adapter."
    )
