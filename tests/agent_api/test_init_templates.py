"""Validate that init scaffold templates parse correctly and stay in sync with the schema."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from importlib_resources import files

from dbt_charts.agent_api.init import _EXCLUDED_TEMPLATE_NAMES
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.project import (
    CHARTS_SUBDIR,
    META_FILENAMES,
    PROJECT_CONFIG_NAME,
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
    """Scaffold files the engine itself treats as standalone boards."""
    excluded = META_FILENAMES | {PROJECT_CONFIG_NAME}
    return sorted(
        name
        for name in _walk_template_names(_template_pkg())
        if is_board_candidate(name) and Path(name).name not in excluded
    )


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
        from dbt_charts.agent_api.init import init_project
        from dbt_charts.core.board import render_dashboard
        from dbt_charts.core.execute.adapters import build_adapter_registry

        init_project(tmp_path)
        project = local_project(root=tmp_path)
        registry = build_adapter_registry(project, read_only=False)
        board = project.path(name).read_board()
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

    def test_exactly_one_scaffold_board(self) -> None:
        """dct init scaffolds exactly one board."""
        assert [f"{CHARTS_SUBDIR}/guide.yaml"] == _SCAFFOLD_BOARD_NAMES, (
            f"expected exactly one scaffold board (guide.yaml), got {_SCAFFOLD_BOARD_NAMES}"
        )

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
    """init_project() must create charts/guide.yaml, not charts/dbt_charts.yml or charts/hello.yml.

    charts/dbt_charts.yml collides with the DCT_ROOT_MARKERS sentinel in project_roots.py:
    find_project_root walks up from a board, stops at charts/dbt_charts.yml, and
    treats charts/ as the project root — so every chart errors "Source not found".
    """

    def test_init_creates_boards_guide_yaml(self, tmp_path: Path) -> None:
        from dbt_charts.agent_api.init import init_project

        init_project(tmp_path)
        boards_dir = tmp_path / "charts"
        assert (boards_dir / "guide.yaml").exists(), (
            "init_project must create charts/guide.yaml"
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

    def test_init_guide_yaml_covers_key_sections(self, tmp_path: Path) -> None:
        """Template must mention queries, charts, and variables to be a useful guide."""
        from dbt_charts.agent_api.init import init_project

        init_project(tmp_path)
        content = (tmp_path / "charts" / "guide.yaml").read_text()
        assert "queries:" in content, "template must have a queries section"
        assert "charts:" in content, "template must have a charts section"
        assert "variables:" in content, "template must have a variables section"

    def test_guide_yaml_mentions_markdown_boards(self, tmp_path: Path) -> None:
        """The guide tells users markdown files under charts/ are boards too."""
        from dbt_charts.agent_api.init import init_project

        init_project(tmp_path)
        content = (tmp_path / "charts" / "guide.yaml").read_text()
        assert ".md" in content
        assert "chart my_chart" in content


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
