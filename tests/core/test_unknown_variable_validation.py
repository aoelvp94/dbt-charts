"""Regression tests for ERR-UNKNOWN-VARIABLE.

Each Jinja template surface that can reference a variable must produce a
structured compile error when the referenced name is not in the registry.
"""

import pytest

from dbt_charts.core.compile.compiler import compile

_BASE_YAML = """
title: Test
queries:
  q:
    sql: "{sql}"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""

_BASE_WITH_SETUP_YAML = """
title: Test
queries:
  q:
    sql: "SELECT 1"
    setup_sql: "CREATE TEMP TABLE _t AS SELECT '{setup_ref}' AS v"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""

_TITLE_YAML = """
title: Test
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    title: "{title}"
    query: q
    type: table
rows:
  - c
"""

_VARIABLE_YAML = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""

_CASCADE_YAML = """
title: Test
source: test_db
variables:
  country:
    input: select
    options:
      static: [us, uk]
  region:
    input: select
    options:
      query: "SELECT r FROM regions WHERE country = {{{{ {ref} }}}}"
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""


def _error_codes(result):
    return [e.code for e in result.errors]


def _hint_texts(result):
    return [e.hint or "" for e in result.errors]


class TestUndefinedVarInChartSqlFailsCheck:
    def test_basic(self):
        yaml_content = _BASE_YAML.format(sql="SELECT * FROM t WHERE r = '{{ regn }}'")
        result = compile(yaml_content)
        assert not result.success
        assert "ERR-UNKNOWN-VARIABLE" in _error_codes(result)

    def test_defined_var_passes(self):
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  q:
    sql: "SELECT * FROM t WHERE r = '{{ region }}'"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert result.success
        assert "ERR-UNKNOWN-VARIABLE" not in _error_codes(result)


class TestDidYouMeanSuggestsNearestRegistryKey:
    def test_suggestion_present(self):
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  q:
    sql: "SELECT * FROM t WHERE r = '{{ regn }}'"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        hints = _hint_texts(result)
        assert any("region" in h for h in hints), (
            f"No 'region' suggestion in hints: {hints}"
        )

    def test_no_suggestion_when_far(self):
        """No 'Did you mean' when the typo is far from all valid names."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  q:
    sql: "SELECT * FROM t WHERE r = '{{ xyzzy_nonexistent }}'"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        errors = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        assert errors
        # "xyzzy_nonexistent" has no close match; no "Did you mean" must appear.
        assert all("Did you mean" not in (e.hint or "") for e in errors)


class TestUndefinedVarInChartTitleFailsCheck:
    def test_title_template(self):
        yaml_content = _TITLE_YAML.format(title="Sales in {{ missing_region }}")
        result = compile(yaml_content)
        assert not result.success
        assert "ERR-UNKNOWN-VARIABLE" in _error_codes(result)

    def test_subtitle_template(self):
        yaml_content = """
title: Test
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    subtitle: "Region: {{ missing_region }}"
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        assert "ERR-UNKNOWN-VARIABLE" in _error_codes(result)


class TestUndefinedVarInQuerySetupSqlFailsCheck:
    def test_setup_sql(self):
        yaml_content = _BASE_WITH_SETUP_YAML.format(setup_ref="{{ regn }}")
        result = compile(yaml_content)
        assert not result.success
        assert "ERR-UNKNOWN-VARIABLE" in _error_codes(result)


class TestUndefinedVarInVariableFilterTemplateFailsCheck:
    def test_cascade_filter_typo(self):
        """{{ regn }} in a cascading-dropdown filter template is an error."""
        yaml_content = _CASCADE_YAML.format(ref="regn")
        result = compile(yaml_content)
        assert not result.success
        assert "ERR-UNKNOWN-VARIABLE" in _error_codes(result)

    def test_cascade_filter_valid_ref_passes(self):
        yaml_content = _CASCADE_YAML.format(ref="country")
        result = compile(yaml_content)
        assert result.success


class TestNestedBoardVarSatisfiesRootCheck:
    def test_nested_var_satisfies_chart_ref(self):
        """Variable declared in a nested board satisfies root-level chart references.

        _collect_variables_recursive propagates nested-board variables to the
        root registry, so {{ region }} declared in the inner board is valid
        from the root's perspective.
        """
        yaml_content = """
title: Root
queries:
  q:
    sql: "SELECT * FROM t WHERE r = '{{ region }}'"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - title: Inner
    variables:
      region:
        input: select
        options:
          static: [north, south]
    rows: []
  - c
"""
        result = compile(yaml_content)
        assert result.success


class TestUrlQueryParamDoesNotSatisfyCheck:
    def test_url_param_not_in_registry(self):
        """URL ?regn=west does not affect compile-time validation; error fires regardless."""
        yaml_content = _BASE_YAML.format(sql="SELECT * FROM t WHERE r = '{{ regn }}'")
        # compile() takes no URL params — confirming the check is purely compile-time
        result = compile(yaml_content)
        assert not result.success
        assert "ERR-UNKNOWN-VARIABLE" in _error_codes(result)


class TestDeadMetaKeyRemoved:
    def test_no_variable_warnings_key_in_meta(self):
        """compiled_board.meta must not contain 'variable_warnings' after the fix."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        # This is a valid board — compilation must succeed.
        assert result.board is not None, result.errors
        assert "variable_warnings" not in result.board.meta

    def test_no_variable_warnings_on_error_case(self):
        yaml_content = _BASE_YAML.format(sql="SELECT * FROM t WHERE r = '{{ regn }}'")
        result = compile(yaml_content)
        # board may be None or present depending on implementation choice;
        # either way, no dead meta key
        if result.board is not None:
            assert "variable_warnings" not in result.board.meta


class TestDiagnosticCarriesDocsTopic:
    def test_docs_topic_variables(self):
        from dbt_charts.core.diagnostics.registry import REGISTRY

        yaml_content = _BASE_YAML.format(sql="SELECT * FROM t WHERE r = '{{ regn }}'")
        result = compile(yaml_content)
        errors = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        assert errors
        assert all(REGISTRY.get(e.code).docs_topic == "variables" for e in errors)


class TestDbtBuiltinsNotFlaggedAsUnknown:
    """dbt SQL Jinja builtins must not raise ERR-UNKNOWN-VARIABLE.

    Each test is a POSITIVE test: the builtin appears in SQL and compilation
    must succeed (or fail only on unrelated errors, not unknown-variable).
    """

    def _assert_no_unknown_var(self, sql: str) -> None:
        yaml_content = f"""
title: Test
queries:
  q:
    sql: "{sql}"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        unknown = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        assert not unknown, f"False positive for SQL {sql!r}: {unknown}"

    def test_ref_not_flagged(self):
        self._assert_no_unknown_var("SELECT * FROM {{ ref('fct_orders') }}")

    def test_source_not_flagged(self):
        self._assert_no_unknown_var("SELECT * FROM {{ source('raw', 'events') }}")

    def test_var_not_flagged(self):
        self._assert_no_unknown_var("SELECT {{ var('my_var') }} AS v")

    def test_env_var_not_flagged(self):
        self._assert_no_unknown_var("SELECT '{{ env_var(\"DB\") }}' AS db")

    def test_config_not_flagged(self):
        self._assert_no_unknown_var("{{ config(materialized='view') }} SELECT 1")

    def test_is_incremental_not_flagged(self):
        self._assert_no_unknown_var(
            "SELECT * FROM t {% if is_incremental() %}WHERE id > 0{% endif %}"
        )

    def test_this_bare_is_flagged(self) -> None:
        """{{ this }} is a bare Name token — never a call — and IS an undefined variable.

        In dbt, 'this' refers to the current model's relation, but dbt compiles
        models before dbt charts sees them. A bare {{ this }} in a dbt charts board
        query SQL is an error, not a dbt-builtin pass-through.
        """
        yaml_content = """
title: Test
queries:
  q:
    sql: "SELECT * FROM {{ this }}"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        codes = [e.code for e in result.errors]
        assert "ERR-UNKNOWN-VARIABLE" in codes, (
            "Expected {{ this }} bare to be flagged as an undefined variable"
        )


class TestTransitiveMisAttribution:
    """Chart loop must only report the chart's OWN undefined variable refs.

    chart.variable_dependencies is post-expansion and includes transitive
    deps from its query. The validator must not blame a chart for an
    undefined variable that belongs to its query or to a cascade variable.
    """

    def test_chart_not_blamed_for_query_undefined_var(self):
        """Query 'q' refs undefined 'missing'; chart 'c' must NOT be the reported owner."""
        yaml_content = """
title: Test
queries:
  q:
    sql: "SELECT * FROM t WHERE x = '{{ missing }}'"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        errors = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        assert errors
        # Owner must be the Query, not the Chart
        for e in errors:
            assert e.fields.get("surface") != "Chart", f"Chart mis-attributed: {e}"
        assert any(e.fields.get("surface") == "Query" for e in errors)

    def test_no_duplicate_when_named_option_query_has_undefined_ref(self) -> None:
        """Named option query with undefined ref: error appears exactly ONCE.

        When a variable's options.query points at a named query already in board.queries,
        the query loop owns validation. The variable loop must not re-extract and
        produce a second identical error with surface='Variable'.
        """
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      query: opt_q
queries:
  opt_q:
    sql: "SELECT r FROM regions WHERE x = '{{ missing }}'"
    source: test_db
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        errors = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        missing_errors = [e for e in errors if e.fields.get("var_name") == "missing"]
        assert len(missing_errors) == 1, (
            f"Expected exactly 1 error for 'missing', got {len(missing_errors)}: {missing_errors}"
        )

    def test_no_duplicate_when_cascade_var_missing(self):
        """Undefined cascade dep is reported once under Variable, not also under Chart."""
        yaml_content = """
title: Test
source: test_db
variables:
  country:
    input: select
    options:
      static: [us, uk]
  region:
    input: select
    options:
      query: "SELECT r FROM regions WHERE country = '{{ country }}' AND x = '{{ missing }}'"
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        errors = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        # 'missing' should be reported exactly once, under Variable, not Chart
        missing_errors = [e for e in errors if e.fields.get("var_name") == "missing"]
        assert len(missing_errors) == 1, f"Expected 1, got: {missing_errors}"
        assert missing_errors[0].fields.get("surface") == "Variable"


class TestReservedVariableNameRejected:
    """Declaring a variable whose name collides with a dbt charts runtime helper must fail.

    'filter', 'filter_date_range', and 'queries' are dbt charts-specific Jinja
    names that users would never intentionally use as variable names. Declaring a
    variable with one of these names shadows the helper, making the helper
    unreachable in templates — so we block them at declaration time.

    dbt SQL builtins (ref, source, var, etc.) are intentionally NOT reserved:
    they are common English words that authors legitimately use as variable names
    (e.g. a "source" dropdown filter), and they appear only in dbt model SQL
    that dbt charts embeds, not in user-authored Jinja expressions.
    """

    @pytest.mark.parametrize(
        "reserved_name",
        ["filter", "filter_date_range", "queries"],
    )
    def test_reserved_name_raises(self, reserved_name: str) -> None:
        yaml_content = f"""
title: Test
variables:
  {reserved_name}:
    input: text
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success, (
            f"Expected failure for reserved name {reserved_name!r}"
        )
        assert any(
            "reserved" in (e.message or "").lower()
            or "reserved" in (e.hint or "").lower()
            for e in result.errors
        ), f"Expected 'reserved' in error message, got: {result.errors}"

    def test_source_is_not_reserved(self) -> None:
        """'source' is a legitimate user variable name (e.g. a data-source filter dropdown).

        Multiple shipped examples use it. dbt SQL builtins are NOT blocked — they
        appear only in embedded dbt model SQL, not in user-authored Jinja expressions.
        """
        yaml_content = """
title: Test
variables:
  source:
    input: text
queries:
  q:
    sql: "SELECT 1"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert result.success, result.errors


class TestInlineChartQuery:
    """Inline chart queries (charts.c.query: {sql: ...}) must be validated too."""

    def test_undefined_var_in_inline_chart_query_fails_check(self) -> None:
        """Undefined variable in an inline chart query fires ERR-UNKNOWN-VARIABLE."""
        yaml_content = """
title: T
charts:
  c:
    query:
      sql: "SELECT * FROM t WHERE r = '{{ regn }}'"
      source: test_db
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        codes = [e.code for e in result.errors]
        assert "ERR-UNKNOWN-VARIABLE" in codes, (
            f"Expected ERR-UNKNOWN-VARIABLE for inline query undefined var, got: {result.errors}"
        )

    def test_inline_chart_query_with_declared_var_passes(self) -> None:
        """Inline chart query whose variable IS declared compiles clean."""
        yaml_content = """
title: T
variables:
  region:
    input: text
charts:
  c:
    query:
      sql: "SELECT * FROM t WHERE r = '{{ region }}'"
      source: test_db
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        assert result.success, result.errors


class TestBareVsCallDbtBuiltin:
    """{{ source }} bare is an undefined variable; {{ source('s','t') }} call is not."""

    def test_bare_dbt_builtin_in_subtitle_fails(self) -> None:
        """{{ source }} bare in a chart subtitle is an undefined variable reference."""
        yaml_content = """
title: Test
queries:
  q:
    sql: "SELECT 1 AS n"
    source: test_db
charts:
  c:
    query: q
    type: table
    subtitle: "Data from: {{ source }}"
rows:
  - c
"""
        result = compile(yaml_content)
        assert not result.success
        codes = [e.code for e in result.errors]
        assert "ERR-UNKNOWN-VARIABLE" in codes, (
            f"Expected ERR-UNKNOWN-VARIABLE, got: {result.errors}"
        )

    def test_dbt_builtin_as_call_not_flagged_unknown(self) -> None:
        """{{ source('schema', 'table') }} as a dbt call must not fire ERR-UNKNOWN-VARIABLE."""
        yaml_content = """
title: Test
queries:
  q:
    sql: "SELECT * FROM {{ source('myschema', 'mytable') }}"
    source: test_db
charts:
  c:
    query: q
    type: table
rows:
  - c
"""
        result = compile(yaml_content)
        unknown = [e for e in result.errors if e.code == "ERR-UNKNOWN-VARIABLE"]
        assert not unknown, (
            f"False positive: {{{{ source('...') }}}} flagged as unknown var: {unknown}"
        )
