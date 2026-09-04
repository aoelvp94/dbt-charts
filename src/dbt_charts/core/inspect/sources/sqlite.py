"""SQLite-specific SchemaSource for the inspect / schema-browser path.

Uses stdlib ``sqlite3`` only — no new dependencies. SQLite always has a
single schema called ``main`` (plus ``temp`` for temp tables, which we skip).

``sqlite_master`` lists all permanent objects; ``PRAGMA table_info(<table>)``
returns column metadata (cid, name, type, notnull, dflt_value, pk).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from dbt_charts.core.execute.sqlite_utils import SQLITE_USER_TABLES_SQL, sqlite_ro_uri


class SQLiteSchemaSource:
    """SchemaSource backed by a SQLite file via stdlib sqlite3.

    Opens a read-only connection per method call. No persistent connection
    is held — SQLite files are local so per-call overhead is negligible.

    ``generated_at`` is always None (live source; no cache build time).
    ``has_manifest`` is always False (SQLite has no dbt manifest).
    """

    name = "sqlite"
    generated_at: datetime | None = None
    has_manifest: bool = False

    def __init__(self, path: str) -> None:
        if not path:
            raise ValueError("SQLiteSchemaSource requires a non-empty path.")
        self._path = path

    def _connect_ro(self) -> sqlite3.Connection:
        """Open a read-only connection via URI mode."""
        try:
            return sqlite3.connect(sqlite_ro_uri(self._path), uri=True)
        except sqlite3.OperationalError as e:
            raise ValueError(
                f"SQLite: cannot open {self._path!r} in read-only mode: {e}"
            ) from e

    def list_schemas(self) -> dict[str, Any] | None:
        """SQLite always exposes a single user schema: ``main``."""
        return {"schemas": {"main": {}}}

    def list_tables(self, schema: str) -> dict[str, Any] | None:
        """List permanent user tables (not system or temp objects).

        Ignores the ``schema`` argument — SQLite has one namespace (main).
        Returns None if the database has no user tables.

        Filters SQLite's own bookkeeping tables (``sqlite_sequence``,
        ``sqlite_stat1``, etc.) which have ``type='table'`` in
        ``sqlite_master`` but are not user-created.
        """
        conn = self._connect_ro()
        try:
            rows = conn.execute(SQLITE_USER_TABLES_SQL).fetchall()
        finally:
            conn.close()

        if not rows:
            return None
        tables = {row[0]: {"kind": "table"} for row in rows}
        return {"tables": tables}

    def profile_table(
        self, schema: str, table: str, lineage_depth: int = 1
    ) -> dict[str, Any] | None:
        """Return column-level schema info from ``PRAGMA table_info``.

        Returns None when the table does not exist.
        Uses the parameterized ``pragma_table_info(?)`` form to avoid
        string interpolation.
        """
        conn = self._connect_ro()
        try:
            # pragma_table_info is a table-valued function accepting a parameter.
            # Columns: cid, name, type, notnull, dflt_value, pk.
            rows = conn.execute(
                "SELECT name, type FROM pragma_table_info(?)", [table]
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return None

        cols: dict[str, dict[str, Any]] = {}
        for col_name, col_type in rows:
            cols[col_name] = {"actual_type": col_type or "TEXT"}

        return {
            "kind": "table",
            "table_exists": True,
            "columns": cols,
            "upstream": [],
            "downstream": [],
        }
