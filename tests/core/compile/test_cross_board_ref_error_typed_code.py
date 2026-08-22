"""Cross-board reference resolution failures must raise a typed ERR-* code,
never the ERR-INTERNAL fallback.

Three distinct failure modes for a `<file>.queries.<name>` /
`<file>.charts.<name>` cross-board ref:
1. the target board file doesn't exist at the resolved path (wrong dir)
2. the ref escapes the project root entirely (one too many `../`)
3. the file exists but the named query/chart isn't declared in it

All three must resolve to `ERR-UNRESOLVED-REFERENCE` with a non-None
`.range`/`.path`, naming the resolved path and the offending ref — see the
task worksheet for the full defect description.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.compiler import compile, compile_file


class TestCrossBoardRefFileNotFound:
    """A cross-board ref pointing at a wrong directory (bad `../`)."""

    def test_wrong_directory_query_ref_carries_typed_code(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        source = tmp_path / "sales" / "wbr.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            """
title: Weekly business review
queries:
  revenue:
    sql: "SELECT 1 AS month, 2 AS revenue"
    source: db
"""
        )
        main_yaml = """
title: Slide
queries:
  revenue: wrongdir/wbr.yaml.queries.revenue
charts:
  rev_chart:
    type: bar
    query: revenue
    x: month
    y: revenue
rows:
  - rev_chart
"""
        result = compile(
            main_yaml,
            base_dir=local_project(root=tmp_path).directory(),
            file="slide.yaml",
        )

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE", (
            f"Expected ERR-UNRESOLVED-REFERENCE but got {err.code!r}"
        )
        assert "wrongdir/wbr.yaml" in err.message
        assert "revenue" in err.message
        assert err.range is not None
        assert err.range.file == "slide.yaml"
        assert err.path == "queries.revenue"

    def test_wrong_directory_chart_ref_carries_typed_code(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        source = tmp_path / "sales" / "wbr.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            """
title: Weekly business review
queries:
  revenue:
    sql: "SELECT 1 AS month, 2 AS revenue"
    source: db
charts:
  rev_chart:
    type: bar
    query: revenue
    x: month
    y: revenue
"""
        )
        main_yaml = """
title: Slide
charts:
  rev_chart: wrongdir/wbr.yaml.charts.rev_chart
rows:
  - rev_chart
"""
        result = compile(
            main_yaml,
            base_dir=local_project(root=tmp_path).directory(),
            file="slide.yaml",
        )

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE", (
            f"Expected ERR-UNRESOLVED-REFERENCE but got {err.code!r}"
        )
        assert "wrongdir/wbr.yaml" in err.message
        assert err.range is not None
        assert err.path == "charts.rev_chart"


class TestCrossBoardRefEscapesProjectRoot:
    """A cross-board ref with one too many `../` — the dominant authoring
    mistake the task's Problem section names — climbs above the project
    root entirely, a distinct failure from "wrong dir but still in-project"."""

    def test_extra_dotdot_query_ref_carries_typed_code(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        source = tmp_path / "sales" / "wbr.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            """
title: Weekly business review
queries:
  revenue:
    sql: "SELECT 1 AS month, 2 AS revenue"
    source: db
"""
        )
        # base_dir is the project root; one extra "../" climbs above it.
        main_yaml = """
title: Slide
queries:
  revenue: ../../wbr.yaml.queries.revenue
charts:
  rev_chart:
    type: bar
    query: revenue
    x: month
    y: revenue
rows:
  - rev_chart
"""
        result = compile(
            main_yaml,
            base_dir=local_project(root=tmp_path).directory(),
            file="slide.yaml",
        )

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE", (
            f"Expected ERR-UNRESOLVED-REFERENCE but got {err.code!r}"
        )
        assert "../../wbr.yaml" in err.message
        assert err.range is not None
        assert err.path == "queries.revenue"


class TestCrossBoardRefUnknownName:
    """A cross-board ref to a real file but an undeclared query/chart name."""

    def test_unknown_query_name_in_valid_file_carries_typed_code(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        source = tmp_path / "sales" / "wbr.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            """
title: Weekly business review
queries:
  revenue:
    sql: "SELECT 1 AS month, 2 AS revenue"
    source: db
"""
        )
        main_yaml = """
title: Slide
queries:
  revenue: sales/wbr.yaml.queries.typo_revenue
charts:
  rev_chart:
    type: bar
    query: revenue
    x: month
    y: revenue
rows:
  - rev_chart
"""
        result = compile(
            main_yaml,
            base_dir=local_project(root=tmp_path).directory(),
            file="slide.yaml",
        )

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE", (
            f"Expected ERR-UNRESOLVED-REFERENCE but got {err.code!r}"
        )
        assert "sales/wbr.yaml" in err.message
        assert "typo_revenue" in err.message
        assert err.range is not None
        assert err.path == "queries.revenue"

    def test_unknown_chart_name_in_valid_file_carries_typed_code(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        source = tmp_path / "sales" / "wbr.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            """
title: Weekly business review
queries:
  revenue:
    sql: "SELECT 1 AS month, 2 AS revenue"
    source: db
charts:
  rev_chart:
    type: bar
    query: revenue
    x: month
    y: revenue
"""
        )
        main_yaml = """
title: Slide
charts:
  rev_chart: sales/wbr.yaml.charts.typo_chart
rows:
  - rev_chart
"""
        result = compile(
            main_yaml,
            base_dir=local_project(root=tmp_path).directory(),
            file="slide.yaml",
        )

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE", (
            f"Expected ERR-UNRESOLVED-REFERENCE but got {err.code!r}"
        )
        assert "sales/wbr.yaml" in err.message
        assert "typo_chart" in err.message
        assert err.range is not None
        assert err.path == "charts.rev_chart"


class TestCrossBoardRefFileStampedViaCompileFile:
    """`compile_file` (the on-disk entry point) stamps `.range.file` on every
    compile error — including the typed cross-board reference error, since
    it's a plain Diagnostic like any other raise site."""

    def test_unknown_query_name_carries_file(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        source = tmp_path / "sales" / "wbr.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            """
title: Weekly business review
queries:
  revenue:
    sql: "SELECT 1 AS month, 2 AS revenue"
    source: db
"""
        )
        main = tmp_path / "slide.yaml"
        main.write_text(
            """
title: Slide
queries:
  revenue: sales/wbr.yaml.queries.typo_revenue
charts:
  rev_chart:
    type: bar
    query: revenue
    x: month
    y: revenue
rows:
  - rev_chart
"""
        )
        project = local_project(root=tmp_path)
        result = compile_file(project.path("slide.yaml").read_board())

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE"
        assert err.range is not None
        assert err.range.file == "slide.yaml"
        assert err.path == "queries.revenue"
