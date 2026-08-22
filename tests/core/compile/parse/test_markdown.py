"""Tests for markdown report file loading and transformation."""

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.parse.markdown import (
    is_markdown_board_content,
    markdown_to_yaml,
    parse_chart_embeds,
)


class TestParseChartEmbeds:
    """Tests for splitting markdown body into text blocks and chart embed tokens."""

    def test_no_embeds(self):
        body = "# Hello\n\nSome text.\n"
        blocks = parse_chart_embeds(body)
        assert blocks == [("text", "# Hello\n\nSome text.")]

    def test_single_embed(self):
        body = "Intro.\n\n{{ chart rev_line }}\n\nOutro.\n"
        blocks = parse_chart_embeds(body)
        assert blocks == [
            ("text", "Intro."),
            ("chart", "rev_line"),
            ("text", "Outro."),
        ]

    def test_multiple_embeds(self):
        body = "A\n\n{{ chart foo }}\n\nB\n\n{{ chart bar }}\n\nC\n"
        blocks = parse_chart_embeds(body)
        assert blocks == [
            ("text", "A"),
            ("chart", "foo"),
            ("text", "B"),
            ("chart", "bar"),
            ("text", "C"),
        ]

    def test_embed_at_start(self):
        body = "{{ chart first }}\n\nText after.\n"
        blocks = parse_chart_embeds(body)
        assert blocks == [
            ("chart", "first"),
            ("text", "Text after."),
        ]

    def test_embed_at_end(self):
        body = "Text before.\n\n{{ chart last }}\n"
        blocks = parse_chart_embeds(body)
        assert blocks == [
            ("text", "Text before."),
            ("chart", "last"),
        ]

    def test_whitespace_variants(self):
        """Tokens with varying whitespace should still parse."""
        body = "A\n\n{{chart foo}}\n\nB\n"
        blocks = parse_chart_embeds(body)
        assert blocks == [
            ("text", "A"),
            ("chart", "foo"),
            ("text", "B"),
        ]

    def test_empty_body(self):
        blocks = parse_chart_embeds("")
        assert blocks == []

    def test_whitespace_only_body(self):
        blocks = parse_chart_embeds("   \n\n  ")
        assert blocks == []


class TestMarkdownToYaml:
    """Tests for transforming a markdown board file into YAML for the compiler."""

    def test_simple_report(self):
        md = """\
---
board:
  title: Report
  queries:
    revenue:
      sql: SELECT 1 as n
      type: sql
  charts:
    rev_line:
      type: line
      query: revenue
      x: n
      y: n
---

# Report

Revenue improved.

{{ chart rev_line }}

More narrative.
"""
        yaml_str = markdown_to_yaml(md)
        data = yaml.safe_load(yaml_str)
        assert data["title"] == "Report"
        assert "queries" in data
        assert "charts" in data
        # Should produce rows layout with content and chart ref
        assert "rows" in data
        rows = data["rows"]
        assert len(rows) == 3
        # First row: content block
        assert isinstance(rows[0], dict) and "text" in rows[0]
        assert "# Report" in rows[0]["text"]
        # Second row: chart reference
        assert rows[1] == "rev_line"
        # Third row: content block
        assert isinstance(rows[2], dict) and "text" in rows[2]
        assert "More narrative" in rows[2]["text"]

    def test_content_only_report(self):
        """Markdown with no embeds and a board: title produces a single content row."""
        md = """\
---
board:
  title: Notes
---

# Just text

No charts here.
"""
        yaml_str = markdown_to_yaml(md)
        data = yaml.safe_load(yaml_str)
        assert data["title"] == "Notes"
        assert "rows" in data
        assert len(data["rows"]) == 1
        assert "# Just text" in data["rows"][0]["text"]

    def test_missing_frontmatter_treats_entire_file_as_body(self):
        md = "# No frontmatter\n\nJust markdown.\n"
        yaml_str = markdown_to_yaml(md)
        data = yaml.safe_load(yaml_str)
        assert data["rows"] == [{"text": "# No frontmatter\n\nJust markdown."}]

    def test_empty_frontmatter_treats_body_as_content(self):
        md = "---\n---\n\n# Empty\n"
        yaml_str = markdown_to_yaml(md)
        data = yaml.safe_load(yaml_str)
        assert data["rows"] == [{"text": "# Empty"}]

    def test_preserves_variables(self):
        md = """\
---
board:
  title: Vars
  variables:
    region:
      input: select
      default: NA
      options: ["NA", "EMEA"]
---

Hello {{ region }}.
"""
        yaml_str = markdown_to_yaml(md)
        data = yaml.safe_load(yaml_str)
        assert "variables" in data
        assert data["variables"]["region"]["input"] == "select"

    def test_preserves_style_and_theme(self):
        md = """\
---
board:
  title: Styled
  theme: neon
  style:
    background: "#000"
---

Content.
"""
        yaml_str = markdown_to_yaml(md)
        data = yaml.safe_load(yaml_str)
        assert data["theme"] == "neon"
        assert data["style"]["background"] == "#000"


class TestIsMarkdownBoard:
    """Tests for detecting whether a .md file is a Dataface markdown report,
    via the ``ProjectPath.is_markdown`` (suffix) + ``is_markdown_board_content``
    (content) twin the compiler uses."""

    def test_md_with_dataface_frontmatter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("---\ntitle: R\ncharts:\n  c:\n    type: kpi\n---\n# Hi\n")
        project = local_project(tmp_path)
        assert project.path("charts/report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=True) is True

    def test_md_in_boards_dir(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("---\ntitle: R\n---\n# Hi\n")
        project = local_project(tmp_path)
        assert project.path("charts/report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=True) is True

    def test_md_in_boards_dir_without_frontmatter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("# Just markdown\n")
        project = local_project(tmp_path)
        assert project.path("charts/report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=True) is True

    def test_md_in_boards_dir_with_empty_frontmatter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("---\n---\n\n# Just markdown\n")
        project = local_project(tmp_path)
        assert project.path("charts/report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=True) is True

    def test_md_without_frontmatter_outside_boards(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        p = tmp_path / "report.md"
        p.write_text("# Just a readme\n\nNo frontmatter.\n")
        project = local_project(tmp_path)
        assert project.path("report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=False) is False

    def test_non_md_file(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        p = tmp_path / "data.yml"
        p.write_text("---\ntitle: R\n---\n")
        project = local_project(tmp_path)
        assert project.path("data.yml").is_markdown is False

    def test_md_with_board_key_outside_boards(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A .md file with a top-level board: key is detected as a board outside charts/."""
        p = tmp_path / "report.md"
        p.write_text("---\nboard:\n  title: My Report\n---\n# Report\n")
        project = local_project(tmp_path)
        assert project.path("report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=False) is True

    def test_md_with_queries_only_outside_boards_not_detected(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A .md file with queries: at top level but no board: is NOT detected outside charts/."""
        p = tmp_path / "research.md"
        p.write_text("---\nqueries:\n  - what is the revenue\n---\n# Research\n")
        project = local_project(tmp_path)
        assert project.path("research.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=False) is False

    def test_plain_md_outside_boards(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A plain .md file without Dataface keys outside charts/ is not detected."""
        p = tmp_path / "README.md"
        p.write_text("---\nauthor: me\n---\n# README\n")
        project = local_project(tmp_path)
        assert project.path("README.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=False) is False

    def test_project_path_is_markdown_is_lexical_no_io(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """ProjectPath.is_markdown is a pure suffix check: relpaths that never
        exist on disk must still resolve correctly (no I/O)."""
        project = local_project(tmp_path)
        assert project.path("reports/summary.md").is_markdown is True
        assert project.path("nested/dir/notes.markdown").is_markdown is True
        assert project.path("data/table.csv").is_markdown is False
        assert project.path("README.MD").is_markdown is True


class TestCompileFileMarkdown:
    """Integration: compile_file() with .md board files."""

    def test_compile_md_board(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        from dbt_charts.core.compile.compiler import compile_file

        md = """\
---
board:
  title: MD Report
  source: warehouse
  queries:
    data:
      sql: SELECT 1 as n
      type: sql
  charts:
    kpi:
      type: kpi
      query: data
      value: n
---

# Report Title

Intro text.

{{ chart kpi }}

Closing.
"""
        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text(md)

        project = local_project(tmp_path)
        result = compile_file(project.path("charts/report.md").read_board())
        assert result.success, f"Errors: {result.errors}"
        assert result.board is not None
        assert result.board.title == "MD Report"
        # Should have queries and charts in registries
        assert "data" in result.query_registry

    def test_compile_md_missing_frontmatter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        from dbt_charts.core.compile.compiler import compile_file

        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("# No frontmatter\n")

        project = local_project(tmp_path)
        result = compile_file(project.path("charts/report.md").read_board())
        assert result.success, f"Errors: {result.errors}"
        assert result.board is not None

    def test_compile_md_empty_frontmatter(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        from dbt_charts.core.compile.compiler import compile_file

        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("---\n---\n\n# Empty frontmatter\n")

        project = local_project(tmp_path)
        result = compile_file(project.path("charts/report.md").read_board())
        assert result.success, f"Errors: {result.errors}"
        assert result.board is not None

    def test_iter_boards_finds_md_and_yml_in_boards_dir(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:

        boards_dir = tmp_path / "charts"
        boards_dir.mkdir()
        (boards_dir / "report.md").write_text(
            "---\ntitle: R\ncharts:\n  c:\n    type: kpi\n---\n# Hi\n"
        )
        (boards_dir / "dashboard.yml").write_text(
            "queries:\n  q:\n    sql: SELECT 1\n    type: sql\nrows:\n  - q\n"
        )

        relpaths = {pf.relpath for pf in local_project(tmp_path).iter_boards()}
        assert "charts/report.md" in relpaths
        assert "charts/dashboard.yml" in relpaths

    def test_is_markdown_board_true_under_boards(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        p = tmp_path / "charts" / "report.md"
        p.parent.mkdir(parents=True)
        p.write_text("---\ntitle: R\n---\n# Hi\n")
        project = local_project(tmp_path)
        assert project.path("charts/report.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=True) is True

    def test_is_markdown_board_false_for_plain_readme(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        p = tmp_path / "README.md"
        p.write_text("# Just a readme\n")
        project = local_project(tmp_path)
        assert project.path("README.md").is_markdown is True
        assert is_markdown_board_content(p.read_text(), in_boards=False) is False

    def test_plain_md_compile_error_is_not_board_file(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """Plain .md (no frontmatter) must error with 'not a Dataface board file', not 'missing opening ---'.

        Regression: compiler called markdown_to_yaml unconditionally on all .md files,
        exposing an internal parse error to users who pass a README.md.
        """
        from dbt_charts.core.compile.compiler import compile_file

        p = tmp_path / "README.md"
        p.write_text("# README\n\nJust docs.\n")

        project = local_project(tmp_path)
        result = compile_file(project.path("README.md").read_board())
        assert not result.success
        error_text = " ".join(str(e) for e in result.errors).lower()
        assert "not a dataface board file" in error_text, (
            f"Expected 'not a Dataface board file' but got: {result.errors}"
        )
        # Must NOT bubble up the internal parse error
        assert "missing opening ---" not in error_text

    def test_plain_md_with_frontmatter_outside_boards_is_not_board(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ):
        """A plain .md with frontmatter but no Dataface keys outside charts/ is not a board."""
        from dbt_charts.core.compile.compiler import compile_file

        p = tmp_path / "notes.md"
        p.write_text("---\nauthor: me\ntitle: Notes\n---\n# Notes\n")

        project = local_project(tmp_path)
        result = compile_file(project.path("notes.md").read_board())
        assert not result.success
        error_text = " ".join(str(e) for e in result.errors).lower()
        assert "not a dataface board file" in error_text


class TestBoardApiMarkdownGuard:
    """Regression: rendering a plain .md board must raise ValueError with clear message."""

    def test_plain_md_raises_clear_valueerror(self, tmp_path: Path):
        """Rendering a plain .md must raise ValueError mentioning 'not a Dataface board file'."""

        from ..._svg_render import render_board_file

        p = tmp_path / "README.md"
        p.write_text("# README\n\nNot a board.\n")

        with pytest.raises(ValueError, match="(?i)not a dataface board file"):
            render_board_file(p)
