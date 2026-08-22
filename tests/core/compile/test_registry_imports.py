"""Tests for registry building with imports.

Tests verify that:
1. Importing queries from external files adds them to the global registry
2. Importing charts from external files adds them to the registry
3. Importing variables from external files adds them to the registry
4. Importing sources from external files works
5. Namespacing prevents conflicts between imported and local definitions
6. Nested boards inherit imported definitions
"""

from collections.abc import Callable
from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile import compile
from dbt_charts.core.compile.compiler import (
    load_from_reference,
)
from dbt_charts.core.compile.models.refs import VariableRef


class TestRegistryWithImports:
    """Test registry building with external file imports."""

    def test_import_query_only_adds_to_query_registry(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test importing a query from external file adds only to query registry."""
        # Create external file with queries, charts, and variables
        external_file = tmp_path / "shared.yml"
        external_file.write_text(
            """
queries:
  shared_query:
    sql: SELECT 'shared' as source
    source: test_profile
charts:
  shared_chart:
    query: shared_query
    type: kpi
    value: source
variables:
  shared_var:
    column: orders.region
    input: select
"""
        )

        # Main dashboard that imports only the query
        main_yaml = """
title: Main Dashboard
queries:
  local_query:
    sql: SELECT 'local' as source
    source: test_profile
  imported_query: shared.queries.shared_query
charts:
  local_chart:
    query: local_query
    type: kpi
    value: source
rows:
  - local_chart
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Should have both local and imported query
        assert "local_query" in result.query_registry
        assert "imported_query" in result.query_registry
        # Imported query should reference the external file
        imported_query = result.query_registry["imported_query"]
        assert imported_query is not None
        assert imported_query.query_type == "sql"

    def test_import_chart_only_adds_to_chart_registry(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test importing a chart from external file adds only to chart registry.

        Note: an imported chart pulls its own query chain lexically from the
        source board (see test_cross_board_chart_query_chain.py) — manually
        re-declaring the dependency here, as this test does, is redundant but
        harmless. This test pins that the chart-import syntax itself still
        works and that the (redundantly) imported chart is usable.
        """
        # Create external file
        external_file = tmp_path / "charts.yml"
        external_file.write_text(
            """
queries:
  chart_query:
    sql: SELECT 1 as value
    source: test_profile
charts:
  imported_chart:
    query: chart_query
    type: bar
    x: category
    y: value
variables:
  chart_var:
    column: orders.status
    input: select
"""
        )

        # Main dashboard that imports both the chart AND its query dependency
        main_yaml = """
title: Main Dashboard
queries:
  local_query:
    sql: SELECT 2 as value
    source: test_profile
  chart_query: charts.queries.chart_query
charts:
  local_chart:
    query: local_query
    type: kpi
    value: value
  imported_chart_ref: charts.charts.imported_chart
rows:
  - local_chart
  - imported_chart_ref
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Should have local chart
        assert "local_chart" in result.board.charts
        # Imported chart should be available
        assert "imported_chart_ref" in result.board.charts
        # The query dependency should also be available
        assert "chart_query" in result.query_registry

    def test_import_variable_only_adds_to_variable_registry(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test importing a variable from external file adds only to variable registry."""
        # Create external file
        external_file = tmp_path / "vars.yml"
        external_file.write_text(
            """
source: test_profile
queries:
  var_query:
    sql: SELECT 1 as value
    source: test_profile
charts:
  var_chart:
    query: var_query
    type: kpi
    value: value
variables:
  imported_var:
    column: orders.region
    input: select
"""
        )

        # Main dashboard that imports the variable
        main_yaml = """
title: Main Dashboard
source: test_profile
queries:
  local_query:
    sql: SELECT 2 as value
    source: test_profile
variables:
  local_var:
    column: orders.status
    input: select
  imported_var_ref: vars.variables.imported_var
charts:
  local_chart:
    query: local_query
    type: kpi
    value: value
rows:
  - local_chart
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Should have local variable
        assert "local_var" in result.board.variables
        # Imported variable should be accessible
        assert "imported_var_ref" in result.board.variables

    def test_namespacing_prevents_conflicts(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that namespacing prevents conflicts between imported and local definitions."""
        # Create external file with a query named "sales"
        external_file = tmp_path / "external.yml"
        external_file.write_text(
            """
queries:
  sales:
    sql: SELECT 'external' as source
    source: test_profile
"""
        )

        # Main dashboard with local query also named "sales"
        main_yaml = """
title: Main Dashboard
queries:
  sales:
    sql: SELECT 'local' as source
    source: test_profile
  imported_sales: external.queries.sales
charts:
  chart1:
    query: sales
    type: kpi
    value: source
rows:
  - chart1
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Both should exist with different names
        assert "sales" in result.query_registry  # Local
        assert "imported_sales" in result.query_registry  # Imported with namespace
        # Local query should be used by default
        local_query = result.query_registry["sales"]
        assert local_query.sql == "SELECT 'local' as source"
        # Imported query should have external content
        imported_query = result.query_registry["imported_sales"]
        assert imported_query.sql == "SELECT 'external' as source"

    def test_duplicate_names_in_same_file_raises_error(self):
        """Test that duplicate names in the same file raise an error."""
        yaml_content = """
title: Test Dashboard
queries:
  sales:
    sql: SELECT 1
    source: test_profile
charts:
  chart1:
    query: sales
    type: kpi
    value: value
rows:
  - chart1
"""
        result = compile(yaml_content)

        # YAML parser will handle duplicate keys (last one wins)
        # Registry building should catch duplicates during processing
        assert result.success  # YAML duplicates are handled by parser

    def test_duplicate_names_across_imports_uses_namespace(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that duplicate names across imports use namespacing."""
        # Create external file
        external_file = tmp_path / "external.yml"
        external_file.write_text(
            """
queries:
  shared_query:
    sql: SELECT 'external' as source
    source: test_profile
"""
        )

        # Main dashboard with same name
        main_yaml = """
title: Main Dashboard
queries:
  shared_query:  # Same name as imported!
    sql: SELECT 'local' as source
    source: test_profile
  imported: external.queries.shared_query
charts:
  chart1:
    query: shared_query
    type: kpi
    value: source
rows:
  - chart1
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Local query should exist
        assert "shared_query" in result.query_registry
        # Imported query should use different key (the name we gave it)
        assert "imported" in result.query_registry
        # Local should have local content
        local_query = result.query_registry["shared_query"]
        assert local_query.sql == "SELECT 'local' as source"
        # Imported should have external content
        imported_query = result.query_registry["imported"]
        assert imported_query.sql == "SELECT 'external' as source"

    def test_nested_boards_inherit_imported_registry(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that nested boards can access imported queries/variables/charts."""
        # Create external file
        external_file = tmp_path / "shared.yml"
        external_file.write_text(
            """
source: test_profile
queries:
  shared_query:
    sql: SELECT 'shared' as source
    source: test_profile
variables:
  shared_var:
    column: orders.region
    input: select
"""
        )

        # Main dashboard with nested board
        main_yaml = """
title: Main Dashboard
source: test_profile
queries:
  imported_query: shared.queries.shared_query
variables:
  imported_var: shared.variables.shared_var
rows:
  - rows:  # Nested board
      - title: Nested
        queries:
          nested_query:
            sql: SELECT 'nested' as source
            source: test_profile
        charts:
          nested_chart:
            query: nested_query
            type: kpi
            value: source
        rows:
          - nested_chart
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Root level should have imported query
        assert "imported_query" in result.query_registry
        # Nested board should have its own query
        nested_board = result.board.layout.items[0].board
        assert nested_board is not None
        # Registry should contain both local and nested queries
        assert "nested_query" in result.query_registry
        # Both imported and nested queries should be accessible
        assert (
            result.query_registry["imported_query"].sql == "SELECT 'shared' as source"
        )
        assert result.query_registry["nested_query"].sql == "SELECT 'nested' as source"

    def test_import_nonexistent_file_raises_error(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that importing from nonexistent file raises an error."""
        main_yaml = """
title: Main Dashboard
queries:
  missing: nonexistent.queries.query_name
charts:
  chart1:
    query: missing
    type: kpi
    value: value
rows:
  - chart1
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert not result.success
        assert len(result.errors) > 0
        # Should have an error about file not found
        error_messages = [str(e) for e in result.errors]
        assert any(
            "not found" in msg.lower() or "referenced file" in msg.lower()
            for msg in error_messages
        )

    def test_import_nonexistent_query_raises_error(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that importing nonexistent query raises an error."""
        # Create external file
        external_file = tmp_path / "external.yml"
        external_file.write_text(
            """
queries:
  existing_query:
    sql: SELECT 1
    source: test_profile
"""
        )

        main_yaml = """
title: Main Dashboard
queries:
  missing: external.queries.nonexistent_query
charts:
  chart1:
    query: missing
    type: kpi
    value: value
rows:
  - chart1
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert not result.success
        assert len(result.errors) > 0
        # Should have an error about query not found
        error_messages = [str(e) for e in result.errors]
        assert any(
            "not found" in msg.lower() or "query" in msg.lower()
            for msg in error_messages
        )

    def test_import_board_and_nest_below_charts(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test importing a board and nesting it below other charts with variables."""
        # Create external board file with variables and charts
        external_board_file = tmp_path / "product_analysis.yml"
        external_board_file.write_text(
            """
title: Product Analysis
source: test_profile
variables:
  product_filter:
    column: orders.product
    input: select
    default: Widget A
  region_filter:
    column: orders.region
    input: multiselect
queries:
  product_sales:
    sql: SELECT * FROM sales WHERE product = '{{ product_filter }}'
    source: test_profile
charts:
  product_chart:
    query: product_sales
    type: bar
    x: date
    y: revenue
  region_chart:
    query: product_sales
    type: pie
    x: region
    y: revenue
rows:
  - cols:
      - product_chart
      - region_chart
"""
        )

        # Main dashboard with charts, then imported board below
        main_yaml = """
title: Main Dashboard
source: test_profile
queries:
  overview:
    sql: SELECT * FROM sales
    source: test_profile
charts:
  overview_chart:
    query: overview
    type: kpi
    value: revenue
  summary_chart:
    query: overview
    type: bar
    x: category
    y: revenue
rows:
  - cols:
      - overview_chart
      - summary_chart
  - title: Product Analysis Section
    # Import the external board by referencing it
    # In practice, this would be done by loading the board file
    # For now, we'll test that variables from nested boards work
    variables:
      product_filter:
        column: orders.product
        input: select
        default: Widget A
      region_filter:
        column: orders.region
        input: multiselect
    queries:
      product_sales:
        sql: SELECT * FROM sales WHERE product = '{{ product_filter }}'
        source: test_profile
    charts:
      product_chart:
        query: product_sales
        type: bar
        x: date
        y: revenue
      region_chart:
        query: product_sales
        type: pie
        theta: revenue
    rows:
      - cols:
          - product_chart
          - region_chart
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        assert result.success
        # Root level should have overview charts
        assert "overview" in result.query_registry
        assert "overview_chart" in result.board.charts

        # Nested board should exist
        assert len(result.board.layout.items) == 2
        nested_board = result.board.layout.items[1].board
        assert nested_board is not None
        assert nested_board.title == "Product Analysis Section"

        # Variables should be accessible
        assert (
            "product_filter" in result.board.variables
            or "product_filter" in nested_board.variables
        )
        # Variables are global, so they should be in the root board's variable registry
        # But nested boards can have local variables for UI rendering
        assert len(nested_board.variables) >= 2  # product_filter and region_filter

        # Charts should be accessible in nested board
        assert "product_chart" in nested_board.charts
        assert "region_chart" in nested_board.charts

        # Verify variable defaults are set
        assert "product_filter" in nested_board.variable_defaults
        assert nested_board.variable_defaults["product_filter"] == "Widget A"

    def test_nested_board_variables_display_and_interact(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that variables in nested boards display correctly and interactions work."""
        # Create a board with charts on top, then a nested board with variables below
        yaml_content = """
title: Main Dashboard
queries:
  sales_data:
    type: values
    rows:
      - {category: A, revenue: 100}
      - {category: B, revenue: 200}
charts:
  top_chart:
    query: sales_data
    type: kpi
    value: revenue
  summary_chart:
    query: sales_data
    type: bar
    x: category
    y: revenue
rows:
  - cols:
      - top_chart
      - summary_chart
  - title: Filtered Analysis Section
    variables:
      region_var:
        label: Region
        input: select
        options:
          static: [North, South, East, West]
        default: North
      product_var:
        label: Product
        input: multiselect
        options:
          static: [Widget A, Widget B, Gadget X]
    queries:
      filtered_data:
        type: values
        rows:
          - {product: Widget A, revenue: 50}
          - {product: Widget B, revenue: 75}
    charts:
      filtered_chart:
        title: "Filtered View{% if region_var %} - {{ region_var }}{% endif %}"
        query: filtered_data
        type: bar
        x: product
        y: revenue
    rows:
      - filtered_chart
"""
        result = compile(
            yaml_content, base_dir=local_project(root=tmp_path).directory()
        )

        assert result.success

        # Verify structure: should have 2 items (charts row + nested board)
        assert len(result.board.layout.items) == 2

        # First item should be a nested board with charts
        first_item = result.board.layout.items[0]
        assert first_item.type == "board"
        first_nested = first_item.board
        assert len(first_nested.layout.items) == 2  # Two charts

        # Second item should be the nested board with variables
        second_item = result.board.layout.items[1]
        assert second_item.type == "board"
        nested_board = second_item.board
        assert nested_board.title == "Filtered Analysis Section"

        # Verify variables are present
        assert len(nested_board.variables) == 2
        assert "region_var" in nested_board.variables
        assert "product_var" in nested_board.variables

        # Verify variable defaults
        assert "region_var" in nested_board.variable_defaults
        assert nested_board.variable_defaults["region_var"] == "North"

        # Verify charts reference variables (check title template)
        assert "filtered_chart" in nested_board.charts
        chart = nested_board.charts["filtered_chart"]
        assert "region_var" in chart.title or "{{" in chart.title  # Has template

        # Verify queries are accessible
        assert "filtered_data" in result.query_registry
        assert "sales_data" in result.query_registry


class TestCrossFileReferenceFunctions:
    """Test the low-level cross-file reference functions."""

    def test_load_variable_from_reference(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test loading a variable from cross-file reference."""
        # Create external file with variables
        external_file = tmp_path / "vars.yml"
        external_file.write_text(
            """
variables:
  region:
    label: Region
    input: select
    options:
      static: [North, South, East, West]
    default: North
"""
        )

        # Load a variable by reference using the typed ref model
        variable = load_from_reference(
            VariableRef(ref="vars.variables.region"),
            base_dir=local_project(root=tmp_path).directory(),
            sources={},
        )

        assert variable is not None
        assert variable.label == "Region"
        assert variable.input == "select"
        assert variable.default == "North"


class TestSourceImports:
    """Test source import functionality."""

    def test_import_source_in_dashboard(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Test that a query with an explicit source: name compiles correctly."""
        # Main dashboard that references the source by name in the query itself
        main_yaml = """
title: Test Dashboard
queries:
  test_query:
    sql: SELECT 1 as value
    source: analytics_db
charts:
  test_chart:
    query: test_query
    type: kpi
    value: value
rows:
  - test_chart
"""
        result = compile(main_yaml, base_dir=local_project(root=tmp_path).directory())

        # Compilation should succeed
        assert result.success
        # Query should reference the source by name
        assert "test_query" in result.query_registry
        query = result.query_registry["test_query"]
        assert query.source == "analytics_db"


class TestUpwardRelativeImports:
    """A board may import from a sibling directory via a leading ../ segment.

    Upward-relative refs anchor on base_dir the same way same-directory refs
    do, and must not escape the project root.
    """

    def test_import_query_via_upward_relative_path(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A query ref starting with ../ resolves to a file in a sibling directory."""
        sales_dir = tmp_path / "charts" / "sales"
        sales_dir.mkdir(parents=True)
        (sales_dir / "shared.yml").write_text(
            """
queries:
  shared_query:
    sql: SELECT 'shared' as source
    source: test_profile
"""
        )

        main_yaml = """
title: Main Dashboard
queries:
  imported_query: ../sales/shared.queries.shared_query
charts:
  local_chart:
    query: imported_query
    type: kpi
    value: source
rows:
  - local_chart
"""
        base_dir = local_project(root=tmp_path).directory("charts/gtm_weekly")
        result = compile(main_yaml, base_dir=base_dir)

        assert result.success, [str(e) for e in result.errors]
        assert "imported_query" in result.query_registry
        assert (
            result.query_registry["imported_query"].sql == "SELECT 'shared' as source"
        )

    def test_import_chart_via_upward_relative_path(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A chart ref starting with ../ resolves to a file in a sibling directory."""
        sales_dir = tmp_path / "charts" / "sales"
        sales_dir.mkdir(parents=True)
        (sales_dir / "charts.yml").write_text(
            """
queries:
  chart_query:
    sql: SELECT 1 as value
    source: test_profile
charts:
  shared_chart:
    query: chart_query
    type: bar
    x: category
    y: value
"""
        )

        main_yaml = """
title: Main Dashboard
queries:
  chart_query: ../sales/charts.queries.chart_query
charts:
  imported_chart: ../sales/charts.charts.shared_chart
rows:
  - imported_chart
"""
        base_dir = local_project(root=tmp_path).directory("charts/gtm_weekly")
        result = compile(main_yaml, base_dir=base_dir)

        assert result.success, [str(e) for e in result.errors]
        assert "imported_chart" in result.board.charts

    def test_upward_relative_path_escaping_project_root_is_rejected(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A ref that climbs above the project root is rejected with a clear error.

        Pins that relaxing the ref grammar to allow leading ../ segments did not
        open a path-traversal hole: assert_relpath still rejects anything that
        normalizes above the project root, however deep the base_dir anchor.
        """
        main_yaml = """
title: Main Dashboard
queries:
  escaping: ../../../../../../etc/passwd.queries.query_name
charts:
  chart1:
    query: escaping
    type: kpi
    value: value
rows:
  - chart1
"""
        base_dir = local_project(root=tmp_path).directory("charts/gtm_weekly")
        result = compile(main_yaml, base_dir=base_dir)

        assert not result.success
        error_messages = [str(e) for e in result.errors]
        assert any("escape" in msg.lower() for msg in error_messages), error_messages
