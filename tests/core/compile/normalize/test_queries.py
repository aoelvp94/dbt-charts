"""Regression tests for sql_guard wiring in normalize.queries.

These tests verify that compile-time SQL validation:
  - Raises CompilationError (wrapping MutatingSqlError) on DROP/DELETE/etc.
  - Raises CompilationError on mutating setup_sql.
  - Catches malicious Jinja branches ({% if x %}DROP{% else %}SELECT{% endif %}).
  - Silently defers (no raise) when SQL contains {% include %} or other nodes
    that the skeleton walker cannot expand (UnparseableSqlError → debug log).
  - Pre-built SqlQuery objects passed directly are also guarded.
  - Bare-SQL-string shorthand path hits the guard.
  - SELECT ... INTO is caught as mutating SQL.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.query.normalized import AnyQuery, SqlQuery
from dbt_charts.core.compile.normalize.queries import (
    normalize_query,
    resolve_external_query,
)
from dbt_charts.core.diagnostics.execution import MutatingSqlError
from dbt_charts.core.project import Project, ProjectDirectory


class TestNormalizeQuerySqlGuardMain:
    """validate_select_only wired into normalize_query."""

    def test_drop_table_raises_compilation_error(self):
        """DROP TABLE in query.sql must raise CompilationError wrapping MutatingSqlError."""
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "my_query",
                {"sql": "DROP TABLE x", "source": "mydb"},
                sources={},
            )
        err = exc_info.value
        assert "my_query" in str(err)
        assert isinstance(err.__cause__, MutatingSqlError)

    def test_select_with_jinja_ref_passes(self):
        """SELECT with {{ ref() }} and {{ user_id }} runs the validator without raising.

        The AST-walk skeleton replaces Jinja output expressions with placeholder
        identifiers so the surrounding SELECT skeleton parses cleanly.
        """
        # Should not raise; result is a SqlQuery (proves validator ran on the full path)
        q = normalize_query(
            "orders_query",
            {
                "sql": "{% for col in cols %}SELECT {{ col }} FROM orders{% endfor %}",
                "source": "mydb",
            },
            sources={},
        )
        assert isinstance(q, SqlQuery)

    def test_malicious_jinja_branch_rejected(self):
        """{% if x %}DROP TABLE x{% else %}SELECT 1{% endif %} must raise CompilationError.

        The AST-walk skeleton includes both branches; the DROP arm fails the allowlist.
        """
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "branch_query",
                {
                    "sql": "{% if some_var %}DROP TABLE x{% else %}SELECT 1{% endif %}",
                    "source": "mydb",
                },
                sources={},
            )
        err = exc_info.value
        assert "branch_query" in str(err)
        assert isinstance(err.__cause__, MutatingSqlError)

    def test_include_silently_deferred(self, caplog):
        """{% include 'helper.sql' %} must NOT raise — UnparseableSqlError is deferred."""
        with caplog.at_level(
            logging.DEBUG, logger="dbt_charts.core.compile.normalize.queries"
        ):
            q = normalize_query(
                "include_query",
                {
                    "sql": "{% include 'helper.sql' %}SELECT 1",
                    "source": "mydb",
                },
                sources={},
            )
        # No exception — query normalizes successfully
        assert "{% include 'helper.sql' %}" in q.sql
        # Debug log should mention the deferral
        assert any("deferred" in r.message.lower() for r in caplog.records)

    def test_prebuilt_sql_query_drop_raises(self):
        """A pre-built SqlQuery(sql='DROP TABLE x') passed directly must be guarded.

        The early-return path for pre-built query objects must also run the guard.
        """
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "prebuilt_q",
                SqlQuery(sql="DROP TABLE x", source="db"),
                sources={},
            )
        err = exc_info.value
        assert "prebuilt_q" in str(err)
        assert isinstance(err.__cause__, MutatingSqlError)

    def test_string_shorthand_drop_raises(self):
        """Bare SQL string shorthand 'DROP TABLE x' must raise CompilationError.

        normalize_query("q", "DROP TABLE x", default_source="db") converts the
        string to {"sql": ..., "source": ...} before building SqlQuery — this path
        must also hit the guard.
        """
        with pytest.raises(CompilationError) as exc_info:
            normalize_query("q", "DROP TABLE x", default_source="db", sources={})
        err = exc_info.value
        assert "q" in str(err)
        assert isinstance(err.__cause__, MutatingSqlError)

    def test_select_into_raises(self):
        """SELECT * INTO exfil FROM users must raise CompilationError wrapping MutatingSqlError.

        SELECT ... INTO is a CTAS-equivalent that creates/modifies tables.
        """
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "exfil_query",
                {"sql": "SELECT * INTO exfil FROM users", "source": "mydb"},
                sources={},
            )
        err = exc_info.value
        assert "exfil_query" in str(err)
        assert isinstance(err.__cause__, MutatingSqlError)


class TestDeadCsvPaths:
    """Dead 'csv' type paths are removed from infer_query_type_from_keys and normalize_query."""

    def test_query_with_file_key_does_not_infer_csv(self) -> None:
        """Legacy 'file:' key no longer infers csv type — falls through to 'sql'."""
        from dbt_charts.core.compile.models.refs import infer_query_type_from_keys

        result = infer_query_type_from_keys({"file": "data.csv", "source": "s"})
        assert result == "sql"

    def test_csv_query_type_not_a_dead_branch_in_normalize_query(self) -> None:
        """Explicit type: csv raises CompilationError (the branch is dead / unreachable).

        After removing the dead 'csv' type branch, a query dict with
        type: csv should fall into the 'unknown type' else branch, not the
        csv-specific error. Both raise CompilationError — the test verifies
        normalize_query raises rather than asserting on the exact message.
        """
        with pytest.raises(CompilationError):
            normalize_query(
                "q", {"type": "csv", "file": "data.csv", "source": "s"}, sources={}
            )


class TestNormalizeQuerySqlGuardSetup:
    """validate_setup_sql wired into normalize_query."""

    def test_drop_in_setup_sql_raises_compilation_error(self):
        """DROP TABLE in setup_sql must raise CompilationError wrapping MutatingSqlError."""
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "setup_query",
                {
                    "sql": "SELECT 1",
                    "setup_sql": "DROP TABLE x",
                    "source": "mydb",
                },
                sources={},
            )
        err = exc_info.value
        assert "setup_query" in str(err)
        assert "setup_sql" in str(err)
        assert isinstance(err.__cause__, MutatingSqlError)

    def test_valid_setup_sql_passes(self):
        """CREATE TEMP TABLE in setup_sql must normalize cleanly."""
        q = normalize_query(
            "temp_query",
            {
                "sql": "SELECT * FROM temp_t",
                "setup_sql": "CREATE TEMP TABLE temp_t AS SELECT 1 AS x",
                "source": "mydb",
            },
            sources={},
        )
        assert q.setup_sql == "CREATE TEMP TABLE temp_t AS SELECT 1 AS x"


class TestResolveExternalQueryCrossTenantIsolation:
    """Regression: two compiles with colliding roots must not share definitions.

    CloudManagedProject passes root=Path() for every tenant, so two tenants
    produce identical cache keys under the old module-level cache. The second
    tenant's compile would receive the first tenant's query definition.
    """

    def test_colliding_roots_each_get_own_definition(
        self, in_memory_project: Callable[[Path, dict[str, str]], Project]
    ) -> None:
        """Two projects with root=Path() and same relpath return their own SQL."""
        shared_yaml_a = """
queries:
  q:
    sql: SELECT 'tenant_a'
    source: db
"""
        shared_yaml_b = """
queries:
  q:
    sql: SELECT 'tenant_b'
    source: db
"""
        project_a = in_memory_project(Path(), {"_shared.yml": shared_yaml_a})
        project_b = in_memory_project(Path(), {"_shared.yml": shared_yaml_b})

        base_dir_a = ProjectDirectory(project_a, ".")
        base_dir_b = ProjectDirectory(project_b, ".")

        registry_a: dict[str, AnyQuery] = {}
        registry_b: dict[str, AnyQuery] = {}

        _key_a, registry_a = resolve_external_query(
            "_shared.yml#q",
            registry_a,
            base_dir_a,
            sources={},
        )
        _key_b, registry_b = resolve_external_query(
            "_shared.yml#q",
            registry_b,
            base_dir_b,
            sources={},
        )

        query_a = registry_a["_shared.yml#q"]
        query_b = registry_b["_shared.yml#q"]

        assert isinstance(query_a, SqlQuery)
        assert isinstance(query_b, SqlQuery)
        assert query_a.sql == "SELECT 'tenant_a'", (
            f"tenant_a got wrong SQL: {query_a.sql!r} — cross-tenant cache hit"
        )
        assert query_b.sql == "SELECT 'tenant_b'", (
            f"tenant_b got wrong SQL: {query_b.sql!r} — cross-tenant cache hit"
        )


class TestResolveExternalQuerySiblingIsolation:
    """Regression: only the referenced query is normalized and registered.

    An external file may contain multiple queries. Only the referenced one
    should enter the registry — a malformed sibling must not cause the board
    referencing only the valid query to fail.
    """

    def test_malformed_sibling_does_not_break_valid_reference(
        self, in_memory_project: Callable[[Path, dict[str, str]], Project]
    ) -> None:
        """External file with valid 'good' and unknown-type 'bad': referencing 'good' succeeds."""
        shared_yaml = """
queries:
  good:
    sql: SELECT 1
    source: db
  bad:
    type: unknown_type_that_does_not_exist
    source: db
"""
        project = in_memory_project(Path(), {"_shared.yml": shared_yaml})
        base_dir = ProjectDirectory(project, ".")
        registry: dict[str, AnyQuery] = {}

        key, registry = resolve_external_query(
            "_shared.yml#good", registry, base_dir, sources={}
        )

        assert key == "_shared.yml#good"
        assert isinstance(registry[key], SqlQuery)
        assert "_shared.yml#bad" not in registry


class TestRemovedDbtModelType:
    """The dbt_model query type is removed end to end.

    It was never executable (no adapter ever claimed the type); the working
    path is a sql query with {{ ref('model') }} against a dbt_profile source.
    """

    def test_model_and_columns_keys_do_not_infer_dbt_model(self) -> None:
        """A type-less dict with model+columns infers 'values' (columns wins).

        `model` stopped being a declared key anywhere when the MetricFlow
        surface was removed, so inference no longer special-cases it; the
        stray key then fails values-query validation loudly.
        """
        from dbt_charts.core.compile.models.refs import infer_query_type_from_keys

        result = infer_query_type_from_keys(
            {"model": "stg_customers", "columns": ["id"]}
        )
        assert result == "values"

    def test_explicit_dbt_model_type_is_unknown(self) -> None:
        """type: dbt_model hits the unknown-type branch and the valid-types list omits it."""
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "customers",
                {"type": "dbt_model", "model": "stg_customers", "columns": ["id"]},
                sources={},
            )
        msg = str(exc_info.value)
        assert "unknown type 'dbt_model'" in msg
        assert "Valid types" in msg

    def test_typeless_model_columns_dict_fails_as_values_not_dbt_model(self) -> None:
        """Without type:, model+columns infers values and board validation rejects it loudly."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.board.authored import AuthoredBoard

        with pytest.raises(ValidationError) as exc_info:
            AuthoredBoard.model_validate(
                {
                    "queries": {
                        "customers": {"model": "stg_customers", "columns": ["id"]}
                    },
                    "rows": [],
                }
            )
        assert "dbt_model" not in str(exc_info.value)


class TestMutatingSqlCodePropagation:
    """`MutatingSqlError` already carries ERR-MUTATING-SQL. Wrapping it in a
    bare CompilationError drops that code and the user sees the ERR-INTERNAL
    fallback instead — the "wrapped raise site" `dbt-charts/AGENTS.md` names.
    """

    def test_mutating_sql_keeps_its_code_through_the_wrapper(self) -> None:
        with pytest.raises(CompilationError) as exc_info:
            normalize_query(
                "my_query", {"sql": "DROP TABLE x", "source": "mydb"}, sources={}
            )

        err = exc_info.value
        assert err.code is not None
        assert err.code.code == "ERR-MUTATING-SQL"
        assert "my_query" in str(err)


class TestTokenizerFailureDeferral:
    """Pin what a tokenizer failure does at compile time.

    Widening `_parse` to catch TokenError changed this caller's behaviour: an
    unterminated string literal used to escape both `except` clauses uncaught,
    and now arrives as UnparseableSqlError and is deferred like any other
    undetermined skeleton. Since a tokenizer failure carries no position by
    design, the squiggle branch can never fire for one — so `dct validate` goes
    from a loud escape to a silent pass. That follows the documented deferral
    policy and is intended; it is asserted here so it stays a decision on the
    record rather than a side effect.
    """

    def test_unterminated_literal_is_deferred_not_raised(self, caplog):
        """An unterminated string literal must defer, not escape as TokenError."""
        with caplog.at_level(
            logging.DEBUG, logger="dbt_charts.core.compile.normalize.queries"
        ):
            q = normalize_query(
                "tokenizer_query",
                {"sql": "SELECT length('''') AS n", "source": "mydb"},
                sources={"mydb": {"type": "bigquery"}},
            )

        assert isinstance(q, SqlQuery)
        assert any("deferred" in r.message.lower() for r in caplog.records)

    def test_tokenizer_failure_shows_no_squiggle(self):
        """No position means no author-facing squiggle, even with a known dialect."""
        q = normalize_query(
            "tokenizer_query",
            {"sql": "SELECT length('''') AS n", "source": "mydb"},
            sources={"mydb": {"type": "bigquery"}},
        )

        assert q.parse_error is None
