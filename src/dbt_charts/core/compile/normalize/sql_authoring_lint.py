"""Compile-time authoring checks for SQL query strings."""

from __future__ import annotations

import sqlglot
import sqlglot.errors

from dbt_charts.core.compile.sql_guard import sqlglot_dialect


def _sql_parses(sql: str, dialect: str | None) -> bool:
    """Return True if sqlglot.parse succeeds without error, False otherwise."""
    try:
        sqlglot.parse(sql, read=sqlglot_dialect(dialect))
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError):
        return False
    return True


def has_literal_escaped_newlines(sql: str, *, dialect: str | None) -> bool:
    """Return True if sql contains literal \\n that is the cause of a parse failure.

    Three-step parse-replace-parse heuristic:
    1. If '\\n' not in sql → False (fast path, no parse needed)
    2. If sqlglot.parse(sql) succeeds → False (\\n is inside a SQL string literal
       or otherwise accepted — step 1 guards the cost of this parse)
    3. If sqlglot.parse(sql.replace('\\n', newline)) succeeds → True
       (the replacement fixed the failure: author used single-quoted YAML instead of
       a block scalar, so \\n was preserved literally instead of becoming a real newline)
    4. Else → False (genuine syntax/Jinja issue unrelated to \\n; step 4 is the
       absence of step 3)

    Note: SQL with Jinja expressions ({{ ref('orders') }}) bypasses detection — both
    step 2 and step 3 fail to parse Jinja skeletons, so the function returns False
    and the existing UnparseableSqlError path handles it at runtime. This is intentional.

    Args:
        sql: Raw SQL string after YAML parsing.
        dialect: Dataface dialect name (e.g. "duckdb", "sqlserver"), or None for the default.
            Normalised to the sqlglot equivalent via sqlglot_dialect().

    Returns:
        True if the literal-\\n authoring error is detected, False otherwise.
    """
    # Step 1: fast exit — no literal \n present, skip all parsing.
    if "\\n" not in sql:
        return False

    # Step 2: parses fine as-is — \n is inside a SQL string literal or similar.
    if _sql_parses(sql, dialect):
        return False

    # Step 3: parses after replacing literal \n with a real newline — authoring mistake.
    # Step 4 is the implicit False when step 3 also fails (genuine syntax/Jinja issue).
    # Author wrote sql: 'SELECT\n...' in YAML single-quotes instead of sql: | block scalar.
    return _sql_parses(sql.replace("\\n", "\n"), dialect)
