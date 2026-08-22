"""Tests for the registered view expansion pipeline.

Purpose: Validate that a matched registered view + query results are rendered
         into a valid AuthoredBoard, that board-SQL Jinja survives template
         rendering intact, that missing template variables fail loudly, and
         that error messages are contextual.
"""

from __future__ import annotations

import textwrap
from typing import Any

import pytest

from dbt_charts.core.registered_views.expander import (
    ExpansionError,
    TemplateLoadError,
    expand_registered_view,
    load_template,
    render_template,
)
from dbt_charts.core.registered_views.models import RegisteredView
from dbt_charts.core.registered_views.query_runner import ViewQueryResult
from dbt_charts.core.registered_views.router import RouteMatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_view(
    name: str = "data_table",
    route: str = "/data/<source>/<schema>/<table>/",
    template: str = "data/table-index.yaml",
    queries: dict[str, Any] | None = None,
) -> RegisteredView:
    return RegisteredView(
        name=name,
        route=route,
        template=template,
        queries=queries,
    )


def _make_match(
    path_params: dict[str, str] | None = None,
    view: RegisteredView | None = None,
) -> RouteMatch:
    return RouteMatch(
        view=view or _make_view(),
        path_params=(
            {"source": "dw", "schema": "analytics", "table": "orders"}
            if path_params is None
            else path_params
        ),
    )


# ---------------------------------------------------------------------------
# load_template
# ---------------------------------------------------------------------------


class TestLoadTemplate:
    def test_loads_existing_package_template(self) -> None:
        """load_template returns non-empty text for a template that exists."""
        text = load_template("data/table-index.yaml")
        assert text.strip() != ""

    def test_missing_template_raises_template_load_error(self) -> None:
        """load_template raises TemplateLoadError for a non-existent path."""
        with pytest.raises(TemplateLoadError, match="does_not_exist"):
            load_template("_test/does_not_exist.yaml")


class TestLoadTemplateContainment:
    """Pin the containment guard's security property across its implementation.

    load_template's containment check may be implemented however it likes
    (str(Traversable)+resolve() vs relpath-segment validation) but must keep
    rejecting every traversal/absolute/empty rel_path while still accepting
    genuine same-tree relative paths.
    """

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "../../../etc/passwd",
            "/etc/passwd",
            "data/../../../etc/passwd",
            "..",
            "data/..",
            "",
            ".",
        ],
    )
    def test_malicious_paths_rejected(self, malicious_path: str) -> None:
        with pytest.raises(TemplateLoadError):
            load_template(malicious_path)

    def test_legitimate_nested_path_accepted(self) -> None:
        text = load_template("data/table-index.yaml")
        assert text.strip() != ""


# ---------------------------------------------------------------------------
# _sql_identifier — dialect-aware quoting
# ---------------------------------------------------------------------------


class TestSqlIdentifierDialect:
    """BigQuery/MySQL use backticks, not ANSI double quotes — the root cause
    of the /data/ 404 this module fixes: `_sql_identifier` used to be
    dialect-blind and always emitted double quotes, which BigQuery parses as
    a string literal, not an identifier.
    """

    def test_bigquery_dialect_uses_backticks(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("dundersign", "bigquery") == "`dundersign`"

    def test_postgres_dialect_keeps_double_quotes(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("dundersign", "postgres") == '"dundersign"'

    def test_duckdb_dialect_keeps_double_quotes(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("dundersign", "duckdb") == '"dundersign"'

    def test_none_dialect_defaults_to_ansi_double_quotes(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("dundersign", None) == '"dundersign"'

    def test_dotted_identifier_is_accepted(self) -> None:
        """A dot is legal inside a quoted identifier on every supported dialect
        (e.g. a BigQuery dataset.table-style registered view name) — reject-by-
        denylist must not turn this into a 500 on a page the /data/ index links to."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("orders.v2", "postgres") == '"orders.v2"'

    def test_non_ascii_identifier_is_accepted(self) -> None:
        """Non-ASCII letters are legal in a quoted identifier; the round-2
        ASCII-only allowlist rejected these and broke real warehouse table names."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("ventas_señor", "postgres") == '"ventas_señor"'

    def test_space_in_identifier_is_accepted(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("my col", "postgres") == '"my col"'

    def test_hash_and_percent_in_identifier_are_accepted(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        assert _sql_identifier("col#1", "postgres") == '"col#1"'
        assert _sql_identifier("col%done", "postgres") == '"col%done"'

    def test_embedded_double_quote_is_rejected(self) -> None:
        """Runtime-boundary validation, not escaping: a quote char in an
        identifier is rejected outright rather than doubled — sqlglot's
        per-dialect escaping is a formatting step, not a security boundary
        (see test_backslash_payload_is_rejected_not_escaped below)."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier('bad"name', "postgres")

    def test_embedded_backtick_is_rejected(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("bad`name", "bigquery")

    def test_backslash_payload_is_rejected_not_escaped(self) -> None:
        """The exact review payload: sqlglot's BigQuery quoting doubles an
        embedded backtick but leaves a backslash untouched (its
        IDENTIFIER_ESCAPES is empty), so `a\\`,other.secrets#` can round-trip
        through `.sql(dialect="bigquery")` as a different identifier than the
        one quoted. Reject it at the runtime boundary instead of trusting the
        code generator to escape it."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("a\\`,other.secrets#", "bigquery")

    def test_embedded_single_quote_is_rejected(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("bad'name", "postgres")

    def test_embedded_bracket_is_rejected(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("bad[name]", "postgres")

    def test_control_character_is_rejected(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("bad\tname", "postgres")

    def test_c1_control_character_is_rejected(self) -> None:
        """C1 controls (\\x80-\\x9f) pass the route regex and would reach PyYAML,
        which raises a raw ReaderError — reject them at the boundary instead."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("bad\x82name", "postgres")

    def test_jinja_delimiters_are_rejected(self) -> None:
        """Board SQL is re-rendered as Jinja downstream in a non-sandboxed env.
        SchemaQuery._no_jinja blocks this today for every current route, but that
        gate lives in another package — deny braces here so a future registered
        view without a schema pre-query can't lose it silently."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        for payload in ("{{ 7*7 }}", "{% raw %}", "a{b"):
            with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
                _sql_identifier(payload, "postgres")

    def test_trailing_newline_is_rejected(self) -> None:
        """A `.match()` + `$` check would accept a trailing newline; the
        validation boundary must reject it outright."""
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("orders\n", "bigquery")

    def test_empty_identifier_is_rejected(self) -> None:
        from dbt_charts.core.registered_views.expander import _sql_identifier

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            _sql_identifier("", "postgres")


# ---------------------------------------------------------------------------
# render_template — isolated unit tests
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_path_namespace_injected(self) -> None:
        """[[ path.source ]] resolves to the path param value."""
        tmpl = "title: [[ path.source ]]"
        result = render_template(
            tmpl, path_params={"source": "snowflake"}, query_results={}
        )
        assert result == "title: snowflake"

    def test_queries_namespace_injected(self) -> None:
        """[[ queries.cols.rows | length ]] resolves from query results."""
        tmpl = "count: [[ queries.cols.rows | length ]]"
        cols = ViewQueryResult(rows=[{"name": "id"}, {"name": "status"}])
        result = render_template(tmpl, path_params={}, query_results={"cols": cols})
        assert result == "count: 2"

    def test_for_loop_over_query_rows(self) -> None:
        """[% for %] iterates over query rows to build YAML structure."""
        tmpl = textwrap.dedent(
            """\
            variables:
            [% for col in queries.cols.rows %]
              [[ col.name ]]: {type: string}
            [% endfor %]
            """
        )
        cols = ViewQueryResult(rows=[{"name": "id"}, {"name": "status"}])
        result = render_template(tmpl, path_params={}, query_results={"cols": cols})
        assert "id:" in result
        assert "status:" in result

    def test_board_sql_jinja_survives_unchanged(self) -> None:
        """{{ queries.revenue }} style board-SQL Jinja is not processed by the template renderer."""
        tmpl = 'sql: "SELECT {{ queries.revenue }}"'
        result = render_template(tmpl, path_params={}, query_results={})
        assert result == 'sql: "SELECT {{ queries.revenue }}"'

    def test_standard_jinja_blocks_pass_through(self) -> None:
        """{{ variable }} and {% if %} board-SQL syntax passes through intact."""
        tmpl = "sql: '{% if x %}SELECT {{ x }}{% endif %}'"
        result = render_template(tmpl, path_params={}, query_results={})
        assert result == "sql: '{% if x %}SELECT {{ x }}{% endif %}'"

    def test_missing_path_param_raises_expansion_error(self) -> None:
        """[[ path.missing ]] raises ExpansionError when the param is absent."""
        tmpl = "title: [[ path.missing ]]"
        with pytest.raises(ExpansionError, match="missing"):
            render_template(tmpl, path_params={}, query_results={})

    def test_missing_query_result_raises_expansion_error(self) -> None:
        """[[ queries.nope.rows ]] raises ExpansionError when the query is absent."""
        tmpl = "count: [[ queries.nope.rows | length ]]"
        with pytest.raises(ExpansionError, match="nope"):
            render_template(tmpl, path_params={}, query_results={})

    def test_syntax_error_raises_expansion_error(self) -> None:
        """A malformed template expression raises ExpansionError."""
        tmpl = "[[ unclosed "
        with pytest.raises(ExpansionError):
            render_template(tmpl, path_params={}, query_results={})

    def test_tojson_filter_escapes_special_chars(self) -> None:
        """tojson filter on path params produces valid, injection-safe YAML scalars.

        A path param containing quotes and colons (legal URL characters) must not
        break the YAML scalar or inject new YAML keys.
        """
        import yaml

        tmpl = "title: [[ path.source | tojson ]]"
        result = render_template(
            tmpl, path_params={"source": 'foo"bar:baz'}, query_results={}
        )
        parsed = yaml.safe_load(result)
        assert parsed["title"] == 'foo"bar:baz'
        assert list(parsed.keys()) == ["title"]  # no injected keys


# ---------------------------------------------------------------------------
# expand_registered_view — integration: template -> AuthoredBoard
# ---------------------------------------------------------------------------


def _table_index_columns(*names: str) -> dict[str, ViewQueryResult]:
    """Minimal columns query result for table-index.yaml (requires pre-template 'columns')."""
    return {
        "columns": ViewQueryResult(
            rows=[{"name": n, "actual_type": "VARCHAR"} for n in names]
        )
    }


class TestExpandRegisteredView:
    def test_expands_to_authored_board(self) -> None:
        """expand_registered_view returns an AuthoredBoard for a valid template."""
        from dbt_charts.core.compile.models.board.authored import AuthoredBoard

        match = _make_match(
            path_params={"source": "dw", "schema": "analytics", "table": "orders"}
        )
        board = expand_registered_view(
            match, query_results=_table_index_columns("id", "status")
        )
        assert isinstance(board, AuthoredBoard)

    def test_generated_board_passes_validator(self) -> None:
        """The generated AuthoredBoard is accepted by the normal board validator."""
        from dbt_charts.core.compile.validate.dispatch import validate_board

        match = _make_match(
            path_params={"source": "dw", "schema": "analytics", "table": "orders"}
        )
        board = expand_registered_view(
            match, query_results=_table_index_columns("id", "status")
        )
        errors = validate_board(board)
        assert errors == [], f"Validation errors: {errors}"

    def test_path_params_visible_in_generated_board(self) -> None:
        """Path params rendered in the template appear in the generated board fields."""
        match = _make_match(
            path_params={"source": "snowflake", "schema": "raw", "table": "events"}
        )
        board = expand_registered_view(match, query_results=_table_index_columns("id"))
        assert board.title is not None
        assert (
            "snowflake" in board.title
            or "raw" in board.title
            or "events" in board.title
        )

    def test_query_rows_shape_generated_board(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Query results looped in a template produce the expected board variable structure.

        Drives expand_registered_view end-to-end via a monkeypatched load_template
        so the full pipeline (render + parse) is exercised.
        """
        import dbt_charts.core.registered_views.expander as expander_mod

        cols = ViewQueryResult(rows=[{"name": "order_id"}, {"name": "status"}])
        tmpl = textwrap.dedent(
            """\
            title: [[ path.source | tojson ]]
            variables:
            [% for col in queries.cols.rows %]
              [[ col.name ]]:
                input: text
            [% endfor %]
            """
        )
        match = _make_match(
            path_params={"source": "dw"},
            view=_make_view(
                route="/data/<source>/",
                template="data/table-index.yaml",
            ),
        )

        monkeypatch.setattr(expander_mod, "load_template", lambda _path: tmpl)
        board = expand_registered_view(match, query_results={"cols": cols})

        assert board.variables is not None
        assert "order_id" in board.variables
        assert "status" in board.variables

    def test_invalid_generated_yaml_raises_expansion_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ParseError from parse_yaml is re-raised as ExpansionError naming the template."""
        import dbt_charts.core.registered_views.expander as expander_mod

        broken_tmpl = "this is not: valid: board: yaml: : :\n  bad: [unclosed bracket\n"
        match = _make_match(
            path_params={},
            view=_make_view(template="data/table-index.yaml"),
        )

        monkeypatch.setattr(expander_mod, "load_template", lambda _path: broken_tmpl)
        with pytest.raises(ExpansionError, match="data/table-index.yaml"):
            expand_registered_view(match, query_results={})

    def test_expansion_error_names_template(self) -> None:
        """ExpansionError from expand_registered_view includes the template path."""
        # Use table-index.yaml with empty path_params so rendering fails —
        # the error must name the template.
        match = _make_match(
            path_params={},
            view=_make_view(template="data/table-index.yaml"),
        )
        with pytest.raises(ExpansionError) as exc_info:
            expand_registered_view(match, query_results={})
        assert "data/table-index.yaml" in str(exc_info.value)

    def test_missing_path_param_in_template_raises_expansion_error(self) -> None:
        """A template referencing [[ path.X ]] for an absent X raises ExpansionError."""
        match = _make_match(
            path_params={},
            view=_make_view(template="data/table-index.yaml"),
        )
        with pytest.raises(ExpansionError):
            expand_registered_view(match, query_results={})

    def test_table_index_sql_injection_in_path_params_is_rejected(self) -> None:
        """SQL injection chars in path.schema / path.table are rejected outright.

        The route regex allows [^\\s/]+ so chars like '"', ';', '--' can appear
        in URL path segments. table-index.yaml calls sql_identifier() on both,
        and an identifier outside the safe charset is a runtime-boundary
        validation failure — not a value to escape and pass through.
        """
        match = _make_match(
            path_params={
                "source": "dw",
                "schema": '"analytics"; DROP TABLE users; --',
                "table": '" OR 1=1; --',
            }
        )
        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            expand_registered_view(match, query_results=_table_index_columns("id"))

    def test_accepted_but_hostile_name_stays_inside_the_quoted_identifier(
        self,
    ) -> None:
        """`;` and `--` survive the denylist (they can't close a quote), so the
        quoting itself is what keeps them inert. Pin that: strip the quoted
        regions and no bare `;` or `--` may remain.
        """
        import re as _re

        board = expand_registered_view(
            _make_match(path_params={"source": "dw", "schema": "a;b", "table": "c--d"}),
            query_results=_table_index_columns("id"),
        )
        assert board.queries is not None
        rows_query = board.queries.get("rows")
        assert rows_query is not None
        sql_text: str = rows_query.sql  # type: ignore[union-attr]
        assert '"a;b"' in sql_text
        assert '"c--d"' in sql_text
        stripped = _re.sub(r'"(?:[^"]|"")*"', "", sql_text)
        assert ";" not in stripped, f"bare ';' outside quoted identifiers: {sql_text!r}"
        assert "--" not in stripped, (
            f"bare '--' outside quoted identifiers: {sql_text!r}"
        )


class TestExpandRegisteredViewDialect:
    """Regression for the /data/ 404 on BigQuery-backed projects: table-index.yaml
    must quote identifiers for the *matched source's* dialect, not always ANSI.
    """

    def _match(self) -> RouteMatch:
        return _make_match(
            path_params={
                "source": "dundersign",
                "schema": "dundersign",
                "table": "documents",
            }
        )

    def test_bigquery_dialect_emits_backticked_identifiers(self) -> None:
        """The exact prod repro: 'dundersign'.'documents' must be backticked, never ANSI-quoted."""
        board = expand_registered_view(
            self._match(),
            query_results=_table_index_columns("id"),
            resolve_dialect=lambda: "bigquery",
        )
        assert board.queries is not None
        rows_query = board.queries.get("rows")
        assert rows_query is not None
        sql_text: str = rows_query.sql  # type: ignore[union-attr]
        assert "`dundersign`" in sql_text
        assert "`documents`" in sql_text
        assert '"dundersign"' not in sql_text

    @pytest.mark.parametrize("dialect", ["postgres", "duckdb"])
    def test_ansi_dialects_still_emit_double_quotes(self, dialect: str) -> None:
        board = expand_registered_view(
            self._match(),
            query_results=_table_index_columns("id"),
            resolve_dialect=lambda: dialect,
        )
        assert board.queries is not None
        rows_query = board.queries.get("rows")
        assert rows_query is not None
        sql_text: str = rows_query.sql  # type: ignore[union-attr]
        assert '"dundersign"' in sql_text
        assert '"documents"' in sql_text
        assert "`dundersign`" not in sql_text

    def test_bigquery_backtick_payload_is_rejected(self) -> None:
        """A backtick-injection path param is rejected, not doubled and passed through."""
        match = _make_match(
            path_params={
                "source": "dundersign",
                "schema": "bad`schema",
                "table": "documents",
            }
        )
        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            expand_registered_view(
                match,
                query_results=_table_index_columns("id"),
                resolve_dialect=lambda: "bigquery",
            )

    def test_backslash_payload_in_schema_is_rejected_through_real_router(self) -> None:
        """The exact review payload, driven through the real router: `a\\`,other
        .secrets#` as the schema param — BigQuery's backtick escaping does not
        hold for backslashes (sqlglot's IDENTIFIER_ESCAPES is empty there), so
        the fix rejects the identifier at the runtime boundary instead of
        emitting SQL whose parsed meaning differs from the URL that produced it.
        """
        from dbt_charts.core.registered_views.loader import load_builtin_registry
        from dbt_charts.core.registered_views.router import RouteRouter

        router = RouteRouter(load_builtin_registry())
        payload = "a\\`,other.secrets#"
        match = router.match(f"/data/wh/{payload}/documents/")
        assert match is not None
        assert match.path_params["schema"] == payload

        with pytest.raises(ExpansionError, match="not a valid SQL identifier"):
            expand_registered_view(
                match,
                query_results=_table_index_columns("id"),
                resolve_dialect=lambda: "bigquery",
            )
