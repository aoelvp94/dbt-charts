"""Validate that init scaffold templates parse correctly and stay in sync with the schema."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from importlib_resources import files

from dbt_charts.agent_api.init import _EXCLUDED_TEMPLATE_NAMES
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters import AdapterRegistry
from dbt_charts.core.project import (
    CHARTS_SUBDIR,
    META_FILENAMES,
    PROJECT_CONFIG_NAME,
    BoardFile,
    is_board_candidate,
)

if TYPE_CHECKING:
    from importlib_resources.abc import Traversable


def _template_pkg() -> Traversable:
    return files("dbt_charts.agent_api._init_templates")


def _walk_template_names(node: Traversable, prefix: str = "") -> Iterator[str]:
    """Yield every template file's relative posix path, recursively."""
    for entry in node.iterdir():
        if entry.name in _EXCLUDED_TEMPLATE_NAMES:
            continue
        rel = f"{prefix}{entry.name}"
        if entry.is_dir():
            yield from _walk_template_names(entry, f"{rel}/")
        else:
            yield rel


def _scaffold_board_names() -> list[str]:
    """Scaffold files the engine itself treats as standalone boards: board
    candidates under charts/ (the root README.md is project prose)."""
    excluded = META_FILENAMES | {PROJECT_CONFIG_NAME}
    return sorted(
        name
        for name in _walk_template_names(_template_pkg())
        if name.startswith(f"{CHARTS_SUBDIR}/")
        and is_board_candidate(name)
        and Path(name).name not in excluded
    )


def _scaffold_board(
    tmp_path: Path, local_project: Callable[..., FilesystemProject], name: str
) -> tuple[BoardFile, FilesystemProject, AdapterRegistry]:
    """A fresh scaffold's board *name*, ready to render."""
    from dbt_charts.agent_api.init import init_project
    from dbt_charts.core.execute.adapters import build_adapter_registry

    init_project(tmp_path)
    project = local_project(root=tmp_path)
    registry = build_adapter_registry(project, read_only=False)
    return project.path(name).read_board(), project, registry


# Computed once at collection time; parametrize IDs are the relative paths.
_SCAFFOLD_BOARD_NAMES = _scaffold_board_names()


class TestScaffoldBoardsValidate:
    @pytest.mark.parametrize("name", _SCAFFOLD_BOARD_NAMES)
    def test_scaffold_board_renders(
        self,
        name: str,
        tmp_path: Path,
        local_project: Callable[..., FilesystemProject],
    ) -> None:
        # SVG format so chart emission (the arm a stale scaffold broke on Cloud)
        # actually runs, not just query execution. Render subsumes validation:
        # a schema-invalid template fails here with the same validation_errors.
        from dbt_charts.core.board import render_dashboard

        board, project, registry = _scaffold_board(tmp_path, local_project, name)
        result = render_dashboard(
            board=board,
            project=project,
            adapter_registry=registry,
            result_cache=None,
            format="svg",
        )
        assert result.status == "ok", (
            f"{name} failed to render: "
            f"validation_errors={[e.message for e in result.validation_errors]} "
            f"chart_errors={result.chart_errors} board_error={result.board_error}"
        )
        # The scaffold is the first YAML a user copies from; it must not model
        # anything the engine's own lint flags.
        assert result.warnings == [], [
            f"{w.code}: {w.message}" for w in result.warnings
        ]

    def test_guide_variable_reaches_the_render(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """The starter's control changes what the board shows: a control that
        renders but moves nothing teaches that controls are decoration."""
        from dbt_charts.core.board import render_dashboard

        board, project, registry = _scaffold_board(
            tmp_path, local_project, f"{CHARTS_SUBDIR}/guide.yml"
        )

        def rendered(variables: dict[str, Any] | None) -> str:
            result = render_dashboard(
                board=board,
                project=project,
                adapter_registry=registry,
                result_cache=None,
                format="html",
                variables=variables,
            )
            assert result.status == "ok", result.chart_errors
            assert isinstance(result.data, str)
            return result.data

        assert "Region control: All" in rendered(None)
        assert "Region control: West" in rendered({"region": "West"})

    def test_guide_derived_figures_match_the_monthly_rows(self) -> None:
        """The KPI row and the product breakdown are hand-derived from the
        monthly rows; an edit to one must not leave the others stale."""
        guide = yaml.safe_load(
            _template_pkg().joinpath(f"{CHARTS_SUBDIR}/guide.yml").read_text()
        )
        queries = guide["queries"]
        monthly = [
            dict(zip(queries["monthly_by_product"]["columns"], row, strict=True))
            for row in queries["monthly_by_product"]["values"]
        ]
        assert {p for p, _ in queries["by_product"]["values"]} == {
            r["product"] for r in monthly
        }
        for product, revenue in queries["by_product"]["values"]:
            assert revenue == sum(
                r["revenue"] for r in monthly if r["product"] == product
            ), product
        months = sorted({r["month"] for r in monthly})
        totals = {
            m: (
                sum(r["revenue"] for r in monthly if r["month"] == m),
                sum(r["orders"] for r in monthly if r["month"] == m),
            )
            for m in months
        }
        (revenue, orders), (prior_revenue, _) = totals[months[-1]], totals[months[-2]]
        latest = dict(
            zip(
                queries["latest_month"]["columns"],
                queries["latest_month"]["values"][0],
                strict=True,
            )
        )
        assert latest["revenue"] == revenue
        assert latest["orders"] == orders
        assert latest["avg_order"] == round(revenue / orders, 1)
        assert latest["revenue_change"] == round(revenue / prior_revenue - 1, 3)

    def test_exactly_one_scaffold_board(self) -> None:
        """dct init scaffolds exactly one board."""
        assert [f"{CHARTS_SUBDIR}/guide.yml"] == _SCAFFOLD_BOARD_NAMES, (
            f"expected exactly one scaffold board (guide.yml), got {_SCAFFOLD_BOARD_NAMES}"
        )

    def test_scaffold_ships_no_data_files(self) -> None:
        """The starter renders from inline rows."""
        names = list(_walk_template_names(_template_pkg()))
        data_files = [n for n in names if n.endswith((".csv", ".json", ".parquet"))]
        assert data_files == [], data_files

    def test_index_md_template_does_not_exist(self) -> None:
        """index.md must not exist as a template — it would hijack the served root."""
        names = list(_walk_template_names(_template_pkg()))
        assert "charts/index.md" not in names and "index.md" not in names, (
            "index.md must not exist in _init_templates: it causes dct serve to render "
            "the welcome page at / instead of the directory listing"
        )


class TestBoardYmlTemplate:
    def test_board_yml_parses_as_yaml(self) -> None:
        content = _template_pkg().joinpath("dbt_charts.yml").read_text()
        parsed = yaml.safe_load(content)
        # Mostly comments today — parses to None; must not raise
        assert parsed is None or isinstance(parsed, dict)

    def test_board_yml_shows_sources_registry(self) -> None:
        """A non-dbt cold start (a bare DuckDB/Postgres) is the common case;
        the scaffold must show the `sources:` shape, not only dbt profiles."""
        content = _template_pkg().joinpath("dbt_charts.yml").read_text()
        assert "sources:" in content
        assert "type: duckdb" in content
        assert "type: postgres" in content


class TestInitCreatesGuide:
    """init_project() must create charts/guide.yml, not charts/dbt_charts.yml or charts/hello.yml.

    charts/dbt_charts.yml collides with the DCT_ROOT_MARKERS sentinel in project_roots.py:
    find_project_root walks up from a board, stops at charts/dbt_charts.yml, and
    treats charts/ as the project root — so every chart errors "Source not found".
    """

    def test_init_creates_boards_guide_yaml(self, tmp_path: Path) -> None:
        from dbt_charts.agent_api.init import init_project

        init_project(tmp_path)
        boards_dir = tmp_path / "charts"
        assert (boards_dir / "guide.yml").exists(), (
            "init_project must create charts/guide.yml"
        )

    def test_init_does_not_create_board_yml(self, tmp_path: Path) -> None:
        """charts/dbt_charts.yml must not be scaffolded — it collides with DCT_ROOT_MARKERS."""
        from dbt_charts.agent_api.init import init_project

        init_project(tmp_path)
        assert not (tmp_path / "charts" / "dbt_charts.yml").exists(), (
            "charts/dbt_charts.yml must not be created by init_project: it collides with "
            "the dbt_charts.yml DCT_ROOT_MARKERS sentinel in project_roots.py, causing "
            "find_project_root to stop at charts/ and treat it as the project root"
        )

    def test_init_does_not_create_agent_markdown(self, tmp_path: Path) -> None:
        from dbt_charts.agent_api.init import init_project

        result = init_project(tmp_path)

        assert not (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / "CLAUDE.md").exists()
        assert Path("AGENTS.md") not in result.created_files
        assert Path("CLAUDE.md") not in result.created_files


class TestScaffoldTreeMatchesTemplates:
    """Drift guard: the scaffolded tree is exactly the template tree, no maintained list."""

    def test_fresh_init_creates_exactly_the_template_tree(self, tmp_path: Path) -> None:
        from dbt_charts.agent_api.init import init_project

        result = init_project(tmp_path)
        template_paths = set(_walk_template_names(_template_pkg()))
        created_paths = {p.as_posix() for p in result.created_files} - {".gitignore"}
        assert created_paths == template_paths

    def test_scaffold_paths_equals_fresh_created_files(self, tmp_path: Path) -> None:
        from dbt_charts.agent_api.init import SCAFFOLD_PATHS, init_project

        result = init_project(tmp_path)
        created = {p.as_posix() for p in result.created_files}
        assert set(SCAFFOLD_PATHS) == created
        assert PROJECT_CONFIG_NAME in SCAFFOLD_PATHS


class TestScaffoldConventions:
    def test_yaml_templates_use_yml_suffix(self) -> None:
        """The scaffold is the convention a new project inherits: `.yml`, like
        `dbt_charts.yml` and every dbt file. Both suffixes stay accepted; only
        our own files are pinned."""
        offenders = [
            name
            for name in _walk_template_names(_template_pkg())
            if name.endswith(".yaml")
        ]
        assert offenders == [], f"scaffold templates must use .yml: {offenders}"

    def test_readme_created_but_never_refreshed(self, tmp_path: Path) -> None:
        """A project README is the user's file the moment it exists: `--force`
        refreshes engine-owned scaffold files, never a README."""
        from dbt_charts.agent_api.init import init_project

        first = init_project(tmp_path)
        assert Path("README.md") in first.created_files
        readme = tmp_path / "README.md"
        readme.write_text("# mine\n", encoding="utf-8")

        forced = init_project(tmp_path, force=True)
        assert readme.read_text(encoding="utf-8") == "# mine\n"
        assert Path("README.md") not in forced.refreshed_files
        assert Path(f"{CHARTS_SUBDIR}/guide.yml") in forced.refreshed_files
