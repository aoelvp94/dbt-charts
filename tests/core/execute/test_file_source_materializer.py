"""Tests for FileSourceMaterializer — CSV/JSON/Parquet → TrivialDuckDBCache.

TDD order: each test was written before its implementation existed.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.models.board.normalized import Board
from dbt_charts.core.compile.models.source import (
    CsvSourceConfig,
    JsonSourceConfig,
    ParquetSourceConfig,
)
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.execute.file_source_materializer import FileSourceMaterializer
from dbt_charts.core.execute.trivial_local_cache import TrivialDuckDBCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    tmp_path: Path,
    files: dict[str, str],
    local_project: Callable[..., FilesystemProject],
) -> FilesystemProject:
    """Create a Project with the given relpath→content mapping on disk."""
    for relpath, content in files.items():
        dest = tmp_path / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    return local_project(tmp_path)


def _make_board(
    sources: dict[str, Any],
    queries: dict[str, Any],
) -> Board:
    """Build a minimal Board from source configs and query objects."""

    board_yaml: dict[str, Any] = {}
    if sources:
        board_yaml["sources"] = sources
    board_yaml["queries"] = {
        name: {"sql": q.sql, "source": q.source} for name, q in queries.items()
    }
    # Compile via the normalizer so we get a proper Board
    import yaml

    board_text = yaml.dump(board_yaml)
    from dbt_charts.core.compile import compile

    result = compile(board_text)
    return result.board


def _csv_source(files: dict[str, str], **kw: Any) -> CsvSourceConfig:
    return CsvSourceConfig(type="csv", files=files, **kw)


def _json_source(files: dict[str, str], **kw: Any) -> JsonSourceConfig:
    return JsonSourceConfig(type="json", files=files, **kw)


# ---------------------------------------------------------------------------
# 1. CSV: materialize and SQL-query
# ---------------------------------------------------------------------------


class TestCsvMaterialize:
    def test_csv_single_table_select_all(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        project = _make_project(
            tmp_path,
            {"data/sales.csv": "region,amount\nNorth,100\nSouth,200\nNorth,150\n"},
            local_project,
        )
        source = _csv_source({"sales": "data/sales.csv"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source, "SELECT * FROM sales ORDER BY amount", {}, "sales"
        )

        # ORDER BY amount ASC: 100 (North), 150 (North), 200 (South)
        assert [r["region"] for r in rows] == ["North", "North", "South"]
        assert [r["amount"] for r in rows] == [100, 150, 200]

    def test_csv_where_filter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        project = _make_project(
            tmp_path,
            {"data/sales.csv": "region,amount\nNorth,100\nSouth,200\nNorth,150\n"},
            local_project,
        )
        source = _csv_source({"sales": "data/sales.csv"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source,
            "SELECT region, amount FROM sales WHERE region = 'North'",
            {},
            "sales",
        )
        assert len(rows) == 2
        assert all(r["region"] == "North" for r in rows)

    def test_csv_delimiter_option(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        project = _make_project(
            tmp_path,
            {"data/pipe.csv": "city|pop\nOslo|700000\nBergen|280000\n"},
            local_project,
        )
        source = _csv_source({"cities": "data/pipe.csv"}, delimiter="|")
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source, "SELECT city FROM cities ORDER BY city", {}, "cities"
        )
        assert [r["city"] for r in rows] == ["Bergen", "Oslo"]


# ---------------------------------------------------------------------------
# 2. JSON: materialize and SQL-query
# ---------------------------------------------------------------------------


class TestJsonMaterialize:
    def test_json_array_of_objects(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        project = _make_project(
            tmp_path, {"data/users.json": json.dumps(data)}, local_project
        )
        source = _json_source({"users": "data/users.json"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source, "SELECT name FROM users ORDER BY id", {}, "users"
        )
        assert [r["name"] for r in rows] == ["Alice", "Bob"]

    def test_ndjson_detected_by_extension(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """.jsonl extension triggers NDJSON parser."""
        ndjson = '{"id": 1}\n{"id": 2}\n'
        project = _make_project(tmp_path, {"data/items.jsonl": ndjson}, local_project)
        source = _json_source({"items": "data/items.jsonl"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source, "SELECT id FROM items ORDER BY id", {}, "items"
        )
        assert [r["id"] for r in rows] == [1, 2]

    def test_json_parse_error_not_confused_with_ndjson(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Malformed .json file reports a JSON parse error, not an NDJSON error."""
        bad_json = '{"key": "value",}'  # trailing comma — invalid JSON
        project = _make_project(tmp_path, {"data/bad.json": bad_json}, local_project)
        source = _json_source({"data": "data/bad.json"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        with pytest.raises(ValueError, match="JSON file is not valid JSON"):
            mat.materialize_and_run(source, "SELECT * FROM data", {}, "data")

    def test_union_by_name_preserves_numeric_type_when_subset_sorts_first(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Numeric column absent in the first (alphabetically-first) file stays BIGINT.

        This is the critical regression direction: if type inference reads only row 0,
        the None-padded value would make the column VARCHAR, breaking numeric queries.
        """
        # a/ sorts before b/ — so a/summary.json is the first file parsed.
        # a/ does NOT have 'score'; b/ has score=42 (integer).
        file_a = '[{"id": 1, "name": "Alice"}]'
        file_b = '[{"id": 2, "name": "Bob", "score": 42}]'
        project = _make_project(
            tmp_path,
            {
                "data/runs/a/summary.json": file_a,
                "data/runs/b/summary.json": file_b,
            },
            local_project,
        )
        source = _json_source(
            {"summaries": "data/runs/*/summary.json"}, union_by_name=True
        )
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        # If score were typed VARCHAR due to row-0 None, SUM(score) would error.
        rows = mat.materialize_and_run(
            source,
            "SELECT SUM(score) AS total FROM summaries",
            {},
            "summaries",
        )
        assert rows[0]["total"] == 42

    def test_union_by_name_pads_missing_columns(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """union_by_name=True pads rows with None for columns absent in that file."""
        file_a = '[{"id": 1, "name": "Alice", "extra": "x"}]'
        file_b = '[{"id": 2, "name": "Bob"}]'
        project = _make_project(
            tmp_path,
            {
                "data/runs/a/summary.json": file_a,
                "data/runs/b/summary.json": file_b,
            },
            local_project,
        )
        source = _json_source(
            {"summaries": "data/runs/*/summary.json"}, union_by_name=True
        )
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source,
            "SELECT id, name, extra FROM summaries ORDER BY id",
            {},
            "summaries",
        )
        assert rows[0] == {"id": 1, "name": "Alice", "extra": "x"}
        assert rows[1]["id"] == 2
        assert rows[1]["name"] == "Bob"
        assert rows[1]["extra"] is None


# ---------------------------------------------------------------------------
# 3. Multi-table JOIN in a single source namespace
# ---------------------------------------------------------------------------


class TestMultiTableJoin:
    def test_two_csv_tables_join(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        project = _make_project(
            tmp_path,
            {
                "data/orders.csv": "order_id,customer_id,amount\n1,10,500\n2,20,300\n",
                "data/customers.csv": "customer_id,name\n10,Alice\n20,Bob\n",
            },
            local_project,
        )
        source = _csv_source(
            {
                "orders": "data/orders.csv",
                "customers": "data/customers.csv",
            }
        )
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source,
            "SELECT c.name, o.amount FROM orders o JOIN customers c ON o.customer_id = c.customer_id ORDER BY o.order_id",
            {},
            "orders",
        )
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert rows[1]["name"] == "Bob"


# ---------------------------------------------------------------------------
# 4. External-access blocked: read_csv('http://...') must fail
# ---------------------------------------------------------------------------


class TestExternalAccessBlocked:
    def test_http_read_csv_in_sql_is_blocked(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Author SQL that tries to read_csv from HTTP must be rejected."""
        project = _make_project(
            tmp_path, {"data/sales.csv": "x,y\n1,2\n"}, local_project
        )
        source = _csv_source({"sales": "data/sales.csv"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        with pytest.raises(
            RuntimeError, match="(?i)(external|access|http|blocked|forbidden)"
        ):
            mat.materialize_and_run(
                source,
                "SELECT * FROM read_csv('http://evil.example.com/data.csv')",
                {},
                "sales",
            )


# ---------------------------------------------------------------------------
# 5. Cache miss → re-materialize: drop the backing table, re-execute, same rows
# ---------------------------------------------------------------------------


class TestCacheMissRehydrate:
    def test_rehydrate_after_cache_drop(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        project = _make_project(
            tmp_path,
            {"data/sales.csv": "x,y\n1,10\n2,20\n"},
            local_project,
        )
        source = _csv_source({"sales": "data/sales.csv"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        sql = "SELECT x, y FROM sales ORDER BY x"
        rows_first = mat.materialize_and_run(source, sql, {}, "sales")
        assert len(rows_first) == 2

        # Drop all _r_ tables to simulate a cold cache
        tables = cache.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '_r_%'"
        ).fetchall()
        for (tbl,) in tables:
            cache.conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')

        # Also drop the views that the materializer registered
        views = cache.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name NOT LIKE '_r_%' AND table_name NOT LIKE '_query%'"
        ).fetchall()
        for (v,) in views:
            with contextlib.suppress(Exception):
                cache.conn.execute(f'DROP VIEW IF EXISTS "{v}"')

        rows_second = mat.materialize_and_run(source, sql, {}, "sales")
        assert rows_second == rows_first


# ---------------------------------------------------------------------------
# 6. Parquet: materialize and SQL-query
# ---------------------------------------------------------------------------


class TestParquetMaterialize:
    def test_parquet_table_queryable(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            pytest.skip("pyarrow not installed")

        table = pa.table({"product": ["A", "B", "C"], "sales": [10, 20, 30]})
        parquet_path = tmp_path / "data" / "products.parquet"
        parquet_path.parent.mkdir(parents=True)
        pq.write_table(table, parquet_path)

        project = local_project(tmp_path)
        source = ParquetSourceConfig(
            type="parquet", files={"products": "data/products.parquet"}
        )
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source,
            "SELECT product, sales FROM products ORDER BY sales DESC",
            {},
            "products",
        )
        assert len(rows) == 3
        assert rows[0]["product"] == "C"


# ---------------------------------------------------------------------------
# 7. Executor integration: SqlQuery with file source routes via materializer
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    def test_executor_routes_file_source_sql_query(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """End-to-end: Executor.execute_query picks up a CSV file source."""
        csv_content = "month,revenue\nJan,1000\nFeb,1500\nMar,1200\n"
        project = _make_project(
            tmp_path, {"data/revenue.csv": csv_content}, local_project
        )

        # D-12: an inline file-path `source:` — no project-level sources
        # registry entry needed. Table name is the file's stem ("revenue").
        # Needs at least one chart for the normalizer to accept it.
        board_yaml = """
queries:
  monthly:
    type: sql
    sql: "SELECT month, revenue FROM revenue ORDER BY revenue DESC"
    source: ./data/revenue.csv
charts:
  rev:
    type: kpi
    query: monthly
    value: revenue
"""
        from dbt_charts.core.compile import compile as df_compile

        result = df_compile(board_yaml, base_dir=project.directory())
        assert result.success, f"Compile failed: {result.errors}"
        board = result.board

        from dbt_charts.core.execute.adapters.adapter_registry import (
            build_adapter_registry,
        )

        registry = build_adapter_registry(project)
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)
        executor = Executor(
            board,
            registry,
            result_cache=cache,
            file_materializer=mat,
        )

        rows = executor.execute_query("monthly")
        assert len(rows) == 3
        assert rows[0]["month"] == "Feb"  # highest revenue
        assert rows[0]["revenue"] == 1500

    def test_file_content_change_produces_fresh_rows(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Editing a data file produces updated rows on the next executor call.

        Regression: the outer result cache (keyed by source config, not file
        content) must NOT shadow the materializer's fingerprinted inner cache.
        If it does, the second query returns stale old_rows even after the file
        is updated.
        """
        csv_v1 = "month,revenue\nJan,1000\n"
        csv_v2 = "month,revenue\nJan,9999\n"

        data_file = tmp_path / "data" / "revenue.csv"
        data_file.parent.mkdir(parents=True)
        data_file.write_text(csv_v1)

        project = _make_project(tmp_path, {}, local_project)  # file already on disk

        # D-12: inline file-path source — table name is the stem ("revenue").
        board_yaml = """
queries:
  monthly:
    type: sql
    sql: "SELECT month, revenue FROM revenue"
    source: ./data/revenue.csv
charts:
  rev:
    type: kpi
    query: monthly
    value: revenue
"""
        from dbt_charts.core.compile import compile as df_compile
        from dbt_charts.core.execute.adapters.adapter_registry import (
            build_adapter_registry,
        )

        result = df_compile(board_yaml, base_dir=project.directory())
        assert result.success
        board = result.board
        registry = build_adapter_registry(project)

        # First render — v1 content
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)
        executor = Executor(board, registry, result_cache=cache, file_materializer=mat)
        rows_v1 = executor.execute_query("monthly")
        assert rows_v1[0]["revenue"] == 1000

        # Update the file on disk
        data_file.write_text(csv_v2)

        # Second render — same persistent cache, new file content.
        # Must return v2 rows, not stale v1 rows.
        mat2 = FileSourceMaterializer(project, cache)
        executor2 = Executor(
            board, registry, result_cache=cache, file_materializer=mat2
        )
        rows_v2 = executor2.execute_query("monthly")
        assert rows_v2[0]["revenue"] == 9999, (
            "Expected fresh rows after file content change, got stale rows"
        )


# ---------------------------------------------------------------------------
# 8. project.read_bytes routes through the file plugin
# ---------------------------------------------------------------------------


class TestProjectReadBytes:
    def test_read_bytes_returns_file_content(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Project.read_bytes delegates to the file plugin."""
        data_path = tmp_path / "data" / "test.csv"
        data_path.parent.mkdir(parents=True)
        data_path.write_bytes(b"col1,col2\n1,2\n")
        project = local_project(tmp_path)
        result = project.read_bytes("data/test.csv")
        assert result == b"col1,col2\n1,2\n"


# ---------------------------------------------------------------------------
# 9. Variable substitution in file-source SQL
# ---------------------------------------------------------------------------


class TestVariableSubstitution:
    def test_file_source_quoted_variable_substitution(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Quoted {{ var }} in file-source SQL must substitute, not match literal string.

        Before fix: WHERE region = '{{ region }}' with region='North' silently
        returns empty rows because DuckDB matches the literal string '{{ region }}'.
        After fix: render_parameterized converts to '$1' with params=['North'], so
        the query correctly returns only matching rows.
        """
        project = _make_project(
            tmp_path,
            {"data/sales.csv": "region,amount\nNorth,100\nSouth,200\nNorth,150\n"},
            local_project,
        )
        source = _csv_source({"sales": "data/sales.csv"})
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)

        rows = mat.materialize_and_run(
            source,
            "SELECT region, amount FROM sales WHERE region = '{{ region }}'",
            {"region": "North"},
            "sales",
        )

        # Should return only North rows, not empty (pre-fix) or all rows
        assert len(rows) == 2
        assert all(r["region"] == "North" for r in rows)


# ---------------------------------------------------------------------------
# 10. Project-level CSV sources route through FileSourceMaterializer
# ---------------------------------------------------------------------------


class TestProjectLevelFileSources:
    def test_executor_routes_project_level_csv_source(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Executor routes a query against a project-level CSV source through
        FileSourceMaterializer, not through the SQL adapter.

        Regression: before fix, `source: kpi_specimens` (defined in
        dbt_charts.yml as type: csv) fell through to the SQL adapter which
        failed with "csv SQL execution failed: Unknown dialect 'csv'".
        """
        csv_content = "name,value\nalpha,10\nbeta,20\n"
        dataface_yml = "sources:\n  kpi_data:\n    type: csv\n    files:\n      kpi_data: data/kpi.csv\n"
        project = _make_project(
            tmp_path,
            {
                "data/kpi.csv": csv_content,
                "dbt_charts.yml": dataface_yml,
            },
            local_project,
        )

        board_yaml = """
queries:
  q:
    type: sql
    sql: "SELECT name, value FROM kpi_data ORDER BY value"
    source: kpi_data
charts:
  c:
    type: kpi
    query: q
    value: value
"""
        from dbt_charts.core.compile import compile as df_compile

        result = df_compile(board_yaml, base_dir=project.directory())
        assert result.success, f"Compile failed: {result.errors}"
        board = result.board

        from dbt_charts.core.execute.adapters.adapter_registry import (
            build_adapter_registry,
        )

        registry = build_adapter_registry(project)
        cache = TrivialDuckDBCache()
        mat = FileSourceMaterializer(project, cache)
        executor = Executor(board, registry, result_cache=cache, file_materializer=mat)

        rows = executor.execute_query("q")
        assert len(rows) == 2, f"Expected 2 rows, got error or wrong count: {rows}"
        assert rows[0]["name"] == "alpha"
        assert rows[1]["name"] == "beta"
