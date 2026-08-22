"""Per-dialect session-reset contract.

The pool runs these statements on a connection whose last query created
session-scoped objects, and drops the connection instead when a dialect has
none. Both halves are load-bearing: a dialect that reports a statement it does
not support fails every query after a ``setup_sql`` board, and one that reports
none pays a reconnect it may not need.
"""

from __future__ import annotations

from dbt_charts.core.dialects import get_dialect
from dbt_charts.core.dialects.base import SQLDialect


class _BareDialect(SQLDialect):
    name = "bare"

    def param(self, index: int) -> str:
        return "?"


def test_a_dialect_reports_no_reset_by_default() -> None:
    """Guessing at syntax would send a statement the warehouse rejects per query."""
    assert _BareDialect().session_reset_statements() == ()


def test_postgres_discards_only_temp_objects() -> None:
    """``DISCARD ALL`` would also reset the connection's statement_timeout and role."""
    assert get_dialect("postgres").session_reset_statements() == ("DISCARD TEMP",)


def test_redshift_does_not_inherit_the_postgres_discard() -> None:
    """RedshiftDialect subclasses PostgresDialect, but Redshift's fork has no
    ``DISCARD`` — inheriting it would error on every query following a setup_sql
    board, so the pool must fall back to dropping the connection."""
    assert get_dialect("redshift").session_reset_statements() == ()
