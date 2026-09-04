"""Validate that init scaffold templates parse correctly and stay in sync with the schema."""

from __future__ import annotations

import importlib.resources
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.validate import validate_yaml


def _template_pkg():
    return importlib.resources.files("dbt_charts.agent_api._init_templates")


def _board_yml_templates() -> list[str]:
    """Board YAML templates — excludes dbt_charts.yml (project config, not a Board)."""
    pkg = _template_pkg()
    return sorted(
        f.name
        for f in pkg.iterdir()  # type: ignore[union-attr]
        if f.name.endswith(".yml") and f.name != "dbt_charts.yml"
    )


class TestYmlTemplatesValidate:
    @pytest.mark.parametrize("filename", _board_yml_templates())
    def test_yml_template_validates(self, filename: str) -> None:
        content = _template_pkg().joinpath(filename).read_text()
        result = validate_yaml(content)
        assert result["success"], f"{filename} failed validation: {result['errors']}"


class TestReadmeMdTemplate:
    def test_readme_md_has_yaml_frontmatter(self) -> None:
        content = _template_pkg().joinpath("README.md").read_text()
        assert content.startswith("---\n"), "README.md must start with YAML frontmatter"
        parts = content.split("---\n", 2)
        assert len(parts) >= 3, "README.md frontmatter must be closed with ---"
        frontmatter = yaml.safe_load(parts[1])
        assert isinstance(frontmatter, dict), "frontmatter must be a YAML mapping"
        assert "title" in frontmatter

    def test_index_md_template_does_not_exist(self) -> None:
        """index.md must not exist as a template — it would hijack the served root."""
        pkg = _template_pkg()
        names = [f.name for f in pkg.iterdir()]  # type: ignore[union-attr]
        assert "index.md" not in names, (
            "index.md must not exist in _init_templates: it causes dct serve to render "
            "the welcome page at / instead of the directory listing"
        )


class TestBoardYmlTemplate:
    def test_board_yml_parses_as_yaml(self) -> None:
        content = _template_pkg().joinpath("dbt_charts.yml").read_text()
        parsed = yaml.safe_load(content)
        # Mostly comments today — parses to None; must not raise
        assert parsed is None or isinstance(parsed, dict)


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

    def test_init_guide_yaml_validates(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """The charts/guide.yaml template must pass schema validation."""
        from dbt_charts.agent_api.init import init_project
        from dbt_charts.core.validate import validate_yaml

        init_project(tmp_path)
        content = (tmp_path / "charts" / "guide.yaml").read_text()
        result = validate_yaml(
            content, base_dir=local_project(root=tmp_path).directory("charts")
        )
        assert result["success"], (
            f"charts/guide.yaml template failed validation: {result['errors']}"
        )

    def test_init_guide_yaml_covers_key_sections(self, tmp_path: Path) -> None:
        """Template must mention queries, charts, and variables to be a useful guide."""
        from dbt_charts.agent_api.init import init_project

        init_project(tmp_path)
        content = (tmp_path / "charts" / "guide.yaml").read_text()
        assert "queries:" in content, "template must have a queries section"
        assert "charts:" in content, "template must have a charts section"
        assert "variables:" in content, "template must have a variables section"

    def test_readme_md_links_to_guide_not_board(self) -> None:
        """README.md template must link to 'guide', not 'board'."""
        content = _template_pkg().joinpath("README.md").read_text()
        assert "hello" not in content, "README.md must not reference 'hello'"
        assert "guide" in content.lower(), (
            "README.md must reference the 'guide' board (was 'board', renamed to avoid DCT_ROOT_MARKERS collision)"
        )
