"""Tests for variable dependency extraction and tracking.

Tests the extract_variable_dependencies function and the variable_dependencies
field on queries and charts computed during normalization.
"""

from dbt_charts.core.compile.compiler import compile
from dbt_charts.core.compile.template.jinja import extract_variable_dependencies

from .conftest import compile_with_board_sources


class TestExtractVariableDependencies:
    """Tests for the extract_variable_dependencies function."""

    def test_simple_variable(self):
        """Test extraction of simple {{ var }} reference."""
        result = extract_variable_dependencies(
            "SELECT * FROM orders WHERE region = '{{ region }}'"
        )
        assert result == {"region"}

    def test_multiple_variables(self):
        """Test extraction of multiple variables."""
        template = """
        SELECT * FROM orders
        WHERE region = '{{ region }}'
          AND category = '{{ category }}'
          AND date >= '{{ start_date }}'
        """
        result = extract_variable_dependencies(template)
        assert result == {"region", "category", "start_date"}

    def test_conditional_if(self):
        """Test extraction from {% if var %} conditionals."""
        template = "SELECT * {% if region %}WHERE region = '{{ region }}'{% endif %}"
        result = extract_variable_dependencies(template)
        assert result == {"region"}

    def test_filter_helper(self):
        """Test extraction with filter() helper - should find var, not 'filter'."""
        template = "SELECT * FROM orders WHERE {{ filter('region', region) }}"
        result = extract_variable_dependencies(template)
        assert result == {"region"}
        assert "filter" not in result

    def test_filter_date_range_helper(self):
        """Test extraction with filter_date_range() helper."""
        template = (
            "SELECT * FROM orders WHERE {{ filter_date_range('date', date_range) }}"
        )
        result = extract_variable_dependencies(template)
        assert result == {"date_range"}
        assert "filter_date_range" not in result

    def test_queries_namespace(self):
        """Test that queries namespace is filtered out."""
        template = (
            "SELECT * FROM {{ queries.base_query }} WHERE region = '{{ region }}'"
        )
        result = extract_variable_dependencies(template)
        assert result == {"region"}
        assert "queries" not in result

    def test_no_variables(self):
        """Test plain string with no Jinja syntax."""
        result = extract_variable_dependencies(
            "SELECT * FROM orders WHERE status = 'active'"
        )
        assert result == set()

    def test_empty_string(self):
        """Test empty string."""
        result = extract_variable_dependencies("")
        assert result == set()

    def test_none_input(self):
        """Test None input."""
        result = extract_variable_dependencies(None)
        assert result == set()

    def test_complex_sql(self):
        """Test complex SQL with multiple patterns."""
        template = """
        SELECT
          o.order_id,
          o.revenue
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        WHERE o.order_date >= '{{ start_date }}'
          AND o.order_date <= '{{ end_date }}'
          {% if region %}AND o.region = '{{ region }}'{% endif %}
          {% if category %}AND p.category = '{{ category }}'{% endif %}
          {% if min_revenue %}AND o.revenue >= {{ min_revenue }}{% endif %}
        ORDER BY o.order_date
        """
        result = extract_variable_dependencies(template)
        assert result == {"start_date", "end_date", "region", "category", "min_revenue"}

    def test_title_template(self):
        """Test extraction from chart title template."""
        template = "Sales Report{% if region %} - {{ region }}{% endif %}"
        result = extract_variable_dependencies(template)
        assert result == {"region"}

    def test_invalid_syntax_returns_empty(self):
        """Test that invalid Jinja syntax returns empty set (doesn't crash)."""
        result = extract_variable_dependencies("Hello {{ name ")  # unclosed
        assert result == set()

    def test_dbt_builtin_as_call_not_in_deps(self):
        """{{ source('schema', 'table') }} — source used as a call — is not a user dep."""
        result = extract_variable_dependencies(
            "SELECT * FROM {{ source('myschema', 'mytable') }}"
        )
        assert "source" not in result

    def test_dbt_builtin_bare_is_in_deps(self):
        """{{ source }} as a bare name ref IS an (undefined) user dep."""
        result = extract_variable_dependencies("SELECT * FROM {{ source }}")
        assert "source" in result

    def test_ref_as_call_not_in_deps(self):
        """{{ ref('model') }} — ref used as a call — is not a user dep."""
        result = extract_variable_dependencies("SELECT * FROM {{ ref('fct_orders') }}")
        assert "ref" not in result


class TestQueryVariableDependencies:
    """Tests for variable_dependencies on compiled queries."""

    def test_sql_query_dependencies(self):
        """Test that SQL query extracts dependencies from SQL."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
  start_date:
    input: date
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE region = '{{ region }}' AND date >= '{{ start_date }}'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"

        query = result.board.queries["test_query"]
        assert query.variable_dependencies == {"region", "start_date"}

    def test_query_with_filter_helper(self):
        """Test query using filter() helper."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE {{ filter('region', region) }}"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        query = result.board.queries["test_query"]
        assert query.variable_dependencies == {"region"}

    def test_query_no_variables(self):
        """Test query with no variable references."""
        yaml_content = """
title: Test
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE status = 'active'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        query = result.board.queries["test_query"]
        assert query.variable_dependencies == set()


class TestChartVariableDependencies:
    """Tests for variable_dependencies on compiled charts."""

    def test_chart_inherits_query_dependencies(self):
        """Test that chart inherits dependencies from its query."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE region = '{{ region }}'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: bar
    x: category
    y: revenue
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        chart = result.board.charts["test_chart"]
        assert "region" in chart.variable_dependencies

    def test_chart_title_dependencies(self):
        """Test that chart extracts dependencies from its title."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders"
    source: test_db
charts:
  test_chart:
    title: "Sales{% if region %} in {{ region }}{% endif %}"
    query: test_query
    type: bar
    x: category
    y: revenue
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        chart = result.board.charts["test_chart"]
        assert "region" in chart.variable_dependencies

    def test_chart_subtitle_dependencies(self):
        """Test that chart extracts dependencies from its subtitle."""
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: bar
    title: "Sales"
    subtitle: "Current {{ region }} snapshot"
    x: category
    y: revenue
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        chart = result.board.charts["test_chart"]
        assert "region" in chart.variable_dependencies

    def test_chart_combined_dependencies(self):
        """Test chart with deps from BOTH title AND query."""
        yaml_content = """
title: Test
variables:
  start_date:
    input: date
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE date >= '{{ start_date }}'"
    source: test_db
charts:
  test_chart:
    title: "Sales in {{ region }}"
    query: test_query
    type: bar
    x: category
    y: revenue
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        chart = result.board.charts["test_chart"]
        # From query SQL
        assert "start_date" in chart.variable_dependencies
        # From title
        assert "region" in chart.variable_dependencies


class TestVariableRegistry:
    """Tests for variable_registry on Board."""

    def test_variable_registry_built_on_root(self):
        """Test that variable_registry is built on root board."""
        yaml_content = """
title: Test
variables:
  region:
    label: Region
    input: select
  category:
    label: Category
    input: select
queries:
  test_query:
    sql: "SELECT * FROM orders"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success

        assert result.board.variable_registry is not None
        assert "region" in result.board.variable_registry
        assert "category" in result.board.variable_registry

    def test_variable_registry_includes_nested_board_variables(self):
        """Test that variable_registry includes variables from nested boards."""
        yaml_content = """
title: Test
variables:
  global_var:
    label: Global
    input: text
rows:
  - title: Nested Section
    variables:
      nested_var:
        label: Nested
        input: select
    text: Nested text
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"

        assert result.board.variable_registry is not None
        assert "global_var" in result.board.variable_registry
        assert "nested_var" in result.board.variable_registry


class TestVariableValidation:
    """Tests for validation of variable references."""

    def test_no_errors_when_all_vars_defined(self):
        """No ERR-UNKNOWN-VARIABLE errors when all referenced variables are defined."""
        yaml_content = """
title: Test
variables:
  region:
    label: Region
    input: select
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE region = '{{ region }}'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success
        assert not any(e.code == "ERR-UNKNOWN-VARIABLE" for e in result.errors)

    def test_error_for_undefined_variable_in_query(self):
        """ERR-UNKNOWN-VARIABLE error when query references undefined variable."""
        yaml_content = """
title: Test
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE region = '{{ undefined_var }}'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert not result.success
        assert any(
            e.code == "ERR-UNKNOWN-VARIABLE" and "undefined_var" in e.message
            for e in result.errors
        )

    def test_error_for_undefined_variable_in_chart_title(self):
        """ERR-UNKNOWN-VARIABLE error when chart title references undefined variable."""
        yaml_content = """
title: Test
queries:
  test_query:
    sql: "SELECT * FROM orders"
    source: test_db
charts:
  test_chart:
    title: "Sales in {{ missing_region }}"
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert not result.success
        assert any(
            e.code == "ERR-UNKNOWN-VARIABLE" and "missing_region" in e.message
            for e in result.errors
        )


class TestVariableDependenciesAreFrozen:
    """variable_dependencies must be a frozenset, not a mutable set, on every
    model that carries it — matching the resolved/_base.py precedent.

    Chart/Variable go through post-construction reassignment
    (`normalize/variables.py`, `normalize/queries.py`), which pydantic does
    not type-coerce; these tests catch a regression to plain `set` at that
    boundary, not just at the field-annotation level.
    """

    def test_query_variable_dependencies_is_frozenset(self):
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE region = '{{ region }}'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: table
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"

        query = result.board.queries["test_query"]
        assert isinstance(query.variable_dependencies, frozenset)

    def test_chart_variable_dependencies_is_frozenset(self):
        yaml_content = """
title: Test
variables:
  region:
    input: select
    options:
      static: [north, south]
queries:
  test_query:
    sql: "SELECT * FROM orders WHERE region = '{{ region }}'"
    source: test_db
charts:
  test_chart:
    query: test_query
    type: bar
    x: category
    y: revenue
rows:
  - cols:
    - test_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"

        chart = result.board.charts["test_chart"]
        assert isinstance(chart.variable_dependencies, frozenset)

    def test_cascading_variable_dependencies_is_frozenset(self):
        """Variable.variable_dependencies, populated by
        compute_variable_dependencies via cascading-dropdown options queries,
        must land as a frozenset at the reassignment site."""
        yaml_content = """
title: Cascading Test

sources:
  db:
    type: duckdb
    path: ":memory:"

variables:
  country:
    input: select
    options:
      query: country_options
      column: country

  state:
    input: select
    options:
      query: state_options
      column: state

queries:
  country_options:
    sql: SELECT DISTINCT country FROM locations
    source: db

  state_options:
    sql: |
      SELECT DISTINCT state FROM locations
      WHERE {{ filter('country', country) }}
    source: db

charts:
  map:
    title: Locations
    type: bar
    query:
      sql: SELECT * FROM locations WHERE {{ filter('country', country) }} AND {{ filter('state', state) }}
      source: db
    x: city
    y: population

rows:
  - map
"""
        result = compile_with_board_sources(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"

        state_var = result.board.variables["state"]
        assert isinstance(state_var.variable_dependencies, frozenset)

        map_chart = result.board.charts["map"]
        assert isinstance(map_chart.variable_dependencies, frozenset)
