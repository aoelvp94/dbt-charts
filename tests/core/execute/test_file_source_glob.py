"""Tests for glob pattern support in file sources.

Covers FileSourceMaterializer glob expansion, Executor cache key correctness
with globs, and the validate-time empty-glob check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from dbt_charts.core.compile.models.source import (
    CsvSourceConfig,
    JsonSourceConfig,
)
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.diagnostics.execution import QueryError
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.execute.file_source_materializer import FileSourceMaterializer
from dbt_charts.core.execute.trivial_local_cache import TrivialDuckDBCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mat(project: Any) -> FileSourceMaterializer:
    return FileSourceMaterializer(project, TrivialDuckDBCache())


class _CountingMaterializer(FileSourceMaterializer):
    """Materializer that counts materialize_and_run calls."""

    def __init__(self, project: Any, cache: TrivialDuckDBCache) -> None:
        super().__init__(project, cache)
        self.run_calls = 0

    def materialize_and_run(  # type: ignore[override]
        self, source: Any, sql: str, variables: dict[str, Any], source_name: str
    ) -> list[dict[str, Any]]:
        self.run_calls += 1
        return super().materialize_and_run(source, sql, variables, source_name)


# ---------------------------------------------------------------------------
# JSON glob — expansion and union
# ---------------------------------------------------------------------------


class TestJsonGlob:
    def test_glob_expands_to_unioned_table(self, in_memory_project: Any) -> None:
        """A JSON glob pattern in files: unions all matched files into one table."""
        project = in_memory_project(
            Path("/test"),
            {
                "runs/a/report.json": '[{"run": "a", "score": 10}]',
                "runs/b/report.json": '[{"run": "b", "score": 20}]',
            },
        )
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        rows = mat.materialize_and_run(
            source, "SELECT run, score FROM reports ORDER BY run", {}, "evals"
        )

        assert [r["run"] for r in rows] == ["a", "b"]
        assert [r["score"] for r in rows] == [10, 20]

    def test_glob_single_object_wraps_to_row(self, in_memory_project: Any) -> None:
        """A JSON file containing a single object (not array) yields a 1-row table.

        Required for evals boards where each report.json / summary.json is a
        single-object result document, not an array.
        """
        project = in_memory_project(
            Path("/test"),
            {
                "runs/a/report.json": '{"run_id": "a", "pass_rate": 0.9}',
                "runs/b/report.json": '{"run_id": "b", "pass_rate": 0.8}',
            },
        )
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        rows = mat.materialize_and_run(
            source, "SELECT run_id, pass_rate FROM reports ORDER BY run_id", {}, "evals"
        )

        assert [r["run_id"] for r in rows] == ["a", "b"]

    def test_non_glob_single_object_wraps_to_row(self, in_memory_project: Any) -> None:
        """A literal (non-glob) JSON file that contains a single object also works."""
        project = in_memory_project(
            Path("/test"),
            {"data/report.json": '{"run_id": "x", "pass_rate": 0.9}'},
        )
        source = JsonSourceConfig(type="json", files={"report": "data/report.json"})
        mat = _mat(project)

        rows = mat.materialize_and_run(source, "SELECT run_id FROM report", {}, "evals")

        assert len(rows) == 1
        assert rows[0]["run_id"] == "x"

    def test_glob_three_files_all_unioned(self, in_memory_project: Any) -> None:
        """Glob matching three files produces three rows (one per file)."""
        project = in_memory_project(
            Path("/test"),
            {
                "runs/x/report.json": '[{"n": 1}]',
                "runs/y/report.json": '[{"n": 2}]',
                "runs/z/report.json": '[{"n": 3}]',
            },
        )
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        rows = mat.materialize_and_run(
            source, "SELECT n FROM reports ORDER BY n", {}, "evals"
        )

        assert [r["n"] for r in rows] == [1, 2, 3]

    def test_empty_glob_raises_at_materialize(self, in_memory_project: Any) -> None:
        """A glob matching no files raises DbtChartsError at materialize time."""
        project = in_memory_project(Path("/test"), {})
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        with pytest.raises(DbtChartsError, match="matched no files"):
            mat.materialize_and_run(source, "SELECT * FROM reports", {}, "evals")


# ---------------------------------------------------------------------------
# CSV glob — expansion and union
# ---------------------------------------------------------------------------


class TestCsvGlob:
    def test_glob_expands_to_unioned_table(self, in_memory_project: Any) -> None:
        """A CSV glob pattern in files: unions all matched files into one table."""
        project = in_memory_project(
            Path("/test"),
            {
                "data/2024/sales.csv": "region,amount\nNorth,100\n",
                "data/2025/sales.csv": "region,amount\nSouth,200\n",
            },
        )
        source = CsvSourceConfig(type="csv", files={"sales": "data/*/sales.csv"})
        mat = _mat(project)

        rows = mat.materialize_and_run(
            source,
            "SELECT region, amount FROM sales ORDER BY amount",
            {},
            "sales_source",
        )

        assert [r["region"] for r in rows] == ["North", "South"]
        assert [r["amount"] for r in rows] == [100, 200]

    def test_empty_csv_glob_raises(self, in_memory_project: Any) -> None:
        """A CSV glob matching no files raises DbtChartsError at materialize time."""
        project = in_memory_project(Path("/test"), {})
        source = CsvSourceConfig(type="csv", files={"sales": "data/*/sales.csv"})
        mat = _mat(project)

        with pytest.raises(DbtChartsError, match="matched no files"):
            mat.materialize_and_run(source, "SELECT * FROM sales", {}, "sales_source")


# ---------------------------------------------------------------------------
# Fan-out cap
# ---------------------------------------------------------------------------


class TestGlobFanoutCap:
    def test_exceeding_default_cap_raises_before_reads(
        self, in_memory_project: Any
    ) -> None:
        """Glob matching more than max_glob_file_count files raises ValueError."""
        from dbt_charts.core.compile.config import get_execution_config

        cap = get_execution_config().max_glob_file_count
        # One more file than the cap to trigger the error.
        files = {
            f"runs/{i:04d}/report.json": f'[{{"id": {i}}}]' for i in range(cap + 1)
        }
        project = in_memory_project(Path("/test"), files)
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        with pytest.raises(DbtChartsError, match=str(cap)):
            mat.materialize_and_run(source, "SELECT * FROM reports", {}, "evals")

    def test_at_cap_succeeds(self, in_memory_project: Any) -> None:
        """Exactly cap files is allowed."""
        from dbt_charts.core.compile.config import get_execution_config

        cap = get_execution_config().max_glob_file_count
        files = {f"runs/{i:04d}/report.json": f'[{{"id": {i}}}]' for i in range(cap)}
        project = in_memory_project(Path("/test"), files)
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        rows = mat.materialize_and_run(
            source, "SELECT count(*) AS n FROM reports", {}, "evals"
        )
        assert rows[0]["n"] == cap


# ---------------------------------------------------------------------------
# Column-key-set consistency check
# ---------------------------------------------------------------------------


class TestGlobColumnConsistency:
    def test_mismatched_columns_raises(self, in_memory_project: Any) -> None:
        """Glob-matched files with different column sets raise a clear error."""
        project = in_memory_project(
            Path("/test"),
            {
                "runs/a/report.json": '[{"id": 1, "score": 10}]',
                "runs/b/report.json": '[{"id": 2, "extra": "oops"}]',
            },
        )
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        with pytest.raises(DbtChartsError, match="different columns"):
            mat.materialize_and_run(source, "SELECT * FROM reports", {}, "evals")

    def test_mismatched_columns_second_has_extra(self, in_memory_project: Any) -> None:
        """Error message names both the offending file and the differing columns."""
        project = in_memory_project(
            Path("/test"),
            {
                "runs/a/report.json": '[{"id": 1}]',
                "runs/b/report.json": '[{"id": 2, "bonus": 99}]',
            },
        )
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        with pytest.raises(DbtChartsError, match="bonus"):
            mat.materialize_and_run(source, "SELECT * FROM reports", {}, "evals")

    def test_matching_columns_succeeds(self, in_memory_project: Any) -> None:
        """Files with identical column sets union correctly."""
        project = in_memory_project(
            Path("/test"),
            {
                "runs/a/report.json": '[{"id": 1, "score": 10}]',
                "runs/b/report.json": '[{"id": 2, "score": 20}]',
            },
        )
        source = JsonSourceConfig(type="json", files={"reports": "runs/*/report.json"})
        mat = _mat(project)

        rows = mat.materialize_and_run(
            source, "SELECT id, score FROM reports ORDER BY id", {}, "evals"
        )
        assert [r["id"] for r in rows] == [1, 2]


# ---------------------------------------------------------------------------
# Executor-level glob cache key correctness
# ---------------------------------------------------------------------------


class TestExecutorGlobCacheKey:
    """Glob sources produce stable cache keys; adding or removing a matched
    file changes the version so warm-cache rows stay fresh."""

    def _project(self, tmp_path: Path, files: dict[str, str]) -> Any:
        from dbt_charts.cli.filesystem_project import FilesystemProject

        for relpath, content in files.items():
            dest = tmp_path / relpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        (tmp_path / "dbt_charts.yml").write_text(
            yaml.dump(
                {
                    "sources": {
                        "runs": {
                            "type": "json",
                            "files": {"reports": "data/*/report.json"},
                        }
                    }
                }
            )
        )
        return FilesystemProject(tmp_path)

    def _board(self) -> Any:
        from dbt_charts.core.compile import compile as compile_board

        board_yaml = {
            "queries": {
                "q": {"sql": "SELECT * FROM reports ORDER BY id", "source": "runs"}
            },
            "charts": {"c": {"query": "q", "type": "table"}},
        }
        board = compile_board(yaml.dump(board_yaml)).board
        assert board is not None
        return board

    def _registry(self, project: Any) -> Any:
        from dbt_charts.core.execute.adapters.adapter_registry import (
            build_adapter_registry,
        )

        return build_adapter_registry(project)

    def test_cold_glob_render_returns_all_matched_rows(self, tmp_path: Path) -> None:
        """Glob source on cold render returns rows from all matched files."""
        project = self._project(
            tmp_path,
            {
                "data/a/report.json": '[{"id": 1}]',
                "data/b/report.json": '[{"id": 2}]',
            },
        )
        board = self._board()
        mat = FileSourceMaterializer(project, TrivialDuckDBCache())
        ex = Executor(
            board,
            adapter_registry=self._registry(project),
            query_registry={"q": board.queries["q"]},
            result_cache=TrivialDuckDBCache(),
            file_materializer=mat,
        )

        rows = ex.execute_query("q")
        assert [r["id"] for r in rows] == [1, 2]

    def test_warm_glob_render_hits_cache(self, tmp_path: Path) -> None:
        """Second render with same glob-matched files hits the result cache."""

        project = self._project(
            tmp_path,
            {
                "data/a/report.json": '[{"id": 1}]',
                "data/b/report.json": '[{"id": 2}]',
            },
        )
        board = self._board()
        result_cache = TrivialDuckDBCache()

        mat1 = _CountingMaterializer(project, TrivialDuckDBCache())
        ex1 = Executor(
            board,
            adapter_registry=self._registry(project),
            query_registry={"q": board.queries["q"]},
            result_cache=result_cache,
            file_materializer=mat1,
        )
        ex1.execute_query("q")
        assert mat1.run_calls == 1

        mat2 = _CountingMaterializer(project, TrivialDuckDBCache())
        ex2 = Executor(
            board,
            adapter_registry=self._registry(project),
            query_registry={"q": board.queries["q"]},
            result_cache=result_cache,
            file_materializer=mat2,
        )
        ex2.execute_query("q")
        # Warm render: result cache hit, materializer never called.
        assert mat2.run_calls == 0

    def test_adding_matching_file_invalidates_cache(self, tmp_path: Path) -> None:
        """Adding a file to the glob match set changes the cache key."""

        project = self._project(
            tmp_path,
            {"data/a/report.json": '[{"id": 1}]'},
        )
        board = self._board()
        result_cache = TrivialDuckDBCache()

        mat1 = _CountingMaterializer(project, TrivialDuckDBCache())
        ex1 = Executor(
            board,
            adapter_registry=self._registry(project),
            query_registry={"q": board.queries["q"]},
            result_cache=result_cache,
            file_materializer=mat1,
        )
        rows1 = ex1.execute_query("q")
        assert [r["id"] for r in rows1] == [1]

        # Add a second matching file.
        new_file = tmp_path / "data" / "b" / "report.json"
        new_file.parent.mkdir(parents=True, exist_ok=True)
        new_file.write_text('[{"id": 2}]')

        mat2 = _CountingMaterializer(project, TrivialDuckDBCache())
        ex2 = Executor(
            board,
            adapter_registry=self._registry(project),
            query_registry={"q": board.queries["q"]},
            result_cache=result_cache,
            file_materializer=mat2,
        )
        rows2 = ex2.execute_query("q")
        # New file added → cache key changed → materializer ran again.
        assert mat2.run_calls == 1
        assert [r["id"] for r in rows2] == [1, 2]


# ---------------------------------------------------------------------------
# Executor error-code propagation for glob failures
# ---------------------------------------------------------------------------


class TestExecutorGlobErrorCodes:
    """Glob errors raised in the materializer surface as QueryError with the
    original ErrorCode preserved, so callers (agent API, Cloud) can branch on
    the structured code without string-matching."""

    def _setup(self, tmp_path: Path, files: dict[str, str]) -> tuple[Any, Any, Any]:
        """Return (project, board, adapter_registry) for a JSON glob board."""
        from dbt_charts.cli.filesystem_project import FilesystemProject

        for relpath, content in files.items():
            dest = tmp_path / relpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        (tmp_path / "dbt_charts.yml").write_text(
            yaml.dump(
                {
                    "sources": {
                        "runs": {
                            "type": "json",
                            "files": {"reports": "data/*/report.json"},
                        }
                    }
                }
            )
        )
        from dbt_charts.core.compile import compile as compile_board
        from dbt_charts.core.execute.adapters.adapter_registry import (
            build_adapter_registry,
        )

        project = FilesystemProject(tmp_path)
        board_yaml = {
            "queries": {"q": {"sql": "SELECT * FROM reports", "source": "runs"}},
            "charts": {"c": {"query": "q", "type": "table"}},
        }
        board = compile_board(yaml.dump(board_yaml)).board
        assert board is not None
        return project, board, build_adapter_registry(project)

    def test_empty_glob_propagates_err_glob_empty_code(self, tmp_path: Path) -> None:
        """Executor.execute_query forwards ERR-GLOB-EMPTY when glob matches nothing."""
        from dbt_charts.core.diagnostics.codes_execute import ERR_GLOB_EMPTY

        project, board, registry = self._setup(tmp_path, {})
        mat = FileSourceMaterializer(project, TrivialDuckDBCache())
        ex = Executor(
            board,
            adapter_registry=registry,
            query_registry={"q": board.queries["q"]},
            result_cache=TrivialDuckDBCache(),
            file_materializer=mat,
        )

        with pytest.raises(QueryError) as exc_info:
            ex.execute_query("q")
        assert exc_info.value.code == ERR_GLOB_EMPTY

    def test_too_many_files_propagates_err_glob_too_many_code(
        self, tmp_path: Path
    ) -> None:
        """Executor.execute_query forwards ERR-GLOB-TOO-MANY when cap is exceeded."""
        from dbt_charts.core.compile.config import get_execution_config
        from dbt_charts.core.diagnostics.codes_execute import ERR_GLOB_TOO_MANY

        cap = get_execution_config().max_glob_file_count
        files = {
            f"data/{i:04d}/report.json": f'[{{"id": {i}}}]' for i in range(cap + 1)
        }
        project, board, registry = self._setup(tmp_path, files)
        mat = FileSourceMaterializer(project, TrivialDuckDBCache())
        ex = Executor(
            board,
            adapter_registry=registry,
            query_registry={"q": board.queries["q"]},
            result_cache=TrivialDuckDBCache(),
            file_materializer=mat,
        )

        with pytest.raises(QueryError) as exc_info:
            ex.execute_query("q")
        assert exc_info.value.code == ERR_GLOB_TOO_MANY
