"""Tests for string query shorthand.

A bare SQL string under queries: should normalize to {sql: value} and
pick up the board-level default source via the existing propagation path.
"""

from dbt_charts.core.compile.compiler import compile
from dbt_charts.core.compile.models.query.normalized import SqlQuery


class TestStringQueryShorthand:
    def test_string_query_uses_board_source(self):
        """String query compiles using the board-level default source."""
        yaml_content = """
title: Test
source: my_db
queries:
  sales: "SELECT * FROM sales"
charts:
  chart:
    query: sales
    type: table
rows:
  - cols:
    - chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        query = result.board.queries["sales"]
        assert isinstance(query, SqlQuery)
        assert query.sql == "SELECT * FROM sales"
        assert query.source == "my_db"

    def test_string_query_extracts_variable_deps(self):
        """String query with Jinja variables extracts dependencies."""
        yaml_content = """
title: Test
source: my_db
variables:
  region:
    input: text
queries:
  filtered: "SELECT * FROM sales WHERE {{ filter('region', region) }}"
charts:
  chart:
    query: filtered
    type: table
rows:
  - cols:
    - chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        query = result.board.queries["filtered"]
        assert "region" in query.variable_dependencies

    def test_string_query_without_source_raises(self):
        """String query with no board-level source fails with a source error."""
        yaml_content = """
title: Test
queries:
  sales: "SELECT * FROM sales"
charts:
  chart:
    query: sales
    type: table
rows:
  - cols:
    - chart
"""
        result = compile(yaml_content)
        assert not result.success
        assert any("source" in str(e).lower() for e in result.errors)


class TestChartQuerySqlShorthand:
    """chart query: "SELECT ..." auto-promotes to an inline query."""

    def test_select_string_compiles_as_inline_query(self):
        """query: 'SELECT 1 AS n' is equivalent to query: {sql: 'SELECT 1 AS n'}."""
        yaml_content = """
title: Test
source: my_db
charts:
  my_chart:
    query: "SELECT 1 AS n"
    type: table
rows:
  - my_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        chart = result.board.charts["my_chart"]
        assert isinstance(chart.query, SqlQuery)
        assert chart.query.sql == "SELECT 1 AS n"
        assert chart.query_is_inline

    def test_with_cte_string_compiles(self):
        """query: 'WITH x AS (...) SELECT ...' also works."""
        yaml_content = """
title: Test
source: my_db
charts:
  my_chart:
    query: "WITH x AS (SELECT 1) SELECT * FROM x"
    type: table
rows:
  - my_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        chart = result.board.charts["my_chart"]
        assert isinstance(chart.query, SqlQuery)
        assert "WITH x AS" in chart.query.sql

    def test_non_sql_unknown_string_still_raises(self):
        """A bare string that isn't SQL and isn't a known query name raises ReferenceError."""
        yaml_content = """
title: Test
source: my_db
charts:
  my_chart:
    query: doesnt_exist
    type: table
rows:
  - my_chart
"""
        result = compile(yaml_content)
        assert not result.success
        assert any("doesnt_exist" in str(e) for e in result.errors)

    def test_sql_keyword_in_identifier_still_raises_reference_error(self):
        """Unknown identifiers containing SQL words should not be promoted to SQL."""
        yaml_content = """
title: Test
source: my_db
charts:
  my_chart:
    query: with_filter
    type: table
rows:
  - my_chart
"""
        result = compile(yaml_content)
        assert not result.success
        assert any("unknown query 'with_filter'" in str(e) for e in result.errors)

    def test_named_ref_still_resolves(self):
        """Existing named-ref form is unaffected."""
        yaml_content = """
title: Test
source: my_db
queries:
  my_q: "SELECT 1 AS n"
charts:
  my_chart:
    query: my_q
    type: table
rows:
  - my_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        chart = result.board.charts["my_chart"]
        assert chart.query_name == "my_q"

    def test_inline_dict_form_still_works(self):
        """Existing query: {sql: ...} form is unaffected."""
        yaml_content = """
title: Test
source: my_db
charts:
  my_chart:
    query:
      sql: "SELECT 1 AS n"
    type: table
rows:
  - my_chart
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        chart = result.board.charts["my_chart"]
        assert isinstance(chart.query, SqlQuery)
        assert chart.query.sql == "SELECT 1 AS n"

    def test_inline_layout_chart_sql_string_compiles(self):
        """Inline charts in rows accept the same bare SQL shorthand."""
        yaml_content = """
title: Test
source: my_db
rows:
  - query: "SELECT 1 AS n"
    type: table
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        chart = result.board.layout.items[0].chart
        assert isinstance(chart.query, SqlQuery)
        assert chart.query.sql == "SELECT 1 AS n"
        assert chart.query_is_inline
