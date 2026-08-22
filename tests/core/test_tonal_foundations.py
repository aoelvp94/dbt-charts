"""Tests for tonal foundation defaults."""

import re
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.config import get_config, reset_config
from dbt_charts.core.execute.adapters import build_adapter_registry


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _normalize_same_run_svg(svg: str) -> str:
    """Strip content that varies between two renders of the same board in one
    process, but not visually: the random SVG root id, the render timestamp,
    and Vega-Lite's auto-incrementing gradient/clip counters.

    A narrower sibling of tests/visual/discovery.py's normalize_svg, which
    also strips cross-tree-only noise (hitbox rects, editor/authored
    renames) that two same-run renders never disagree on.
    """
    svg = re.sub(r'\s*id="dataface-svg-[^"]*"', "", svg)
    svg = re.sub(r'\s*data-rendered-at="[^"]*"', "", svg)
    svg = re.sub(
        r'<text\s+data-role="render-timestamp"[^>]*>.*?</text>',
        "",
        svg,
        flags=re.DOTALL,
    )
    for pattern in (r"gradient_(\d+)", r"clip_(\d+)", r"clip(\d+)"):
        prefix = pattern.split("(")[0]
        ids = list(dict.fromkeys(re.findall(pattern, svg)))
        id_map = {old: str(new) for new, old in enumerate(ids)}
        svg = re.sub(
            pattern, lambda m, _m=id_map, _p=prefix: f"{_p}{_m[m.group(1)]}", svg
        )
    return svg


class TestTonalFoundationDefaults:
    """Default ink, surface, and canvas colors — structural and cascade tests only."""

    def test_export_formats_inherit_board_background(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Export surfaces do not force a separate page background; the board
        background from the board style propagates into SVG output."""
        from pathlib import Path

        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.execute.adapters import build_adapter_registry
        from dbt_charts.core.render import render

        yaml = (
            "title: T\nstyle:\n  background: '#cc1122'\n"
            "queries:\n  q:\n    type: values\n"
            "    rows:\n      - {month: Jan, revenue: 100}\ncharts:\n  c:\n    query: q\n    type: bar\n"
            "    x: month\n    y: revenue\nrows:\n  - c"
        )
        result = compile(yaml)
        assert result.board is not None
        assert result.query_registry is not None
        assert result.success
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )
        svg = render(result.board, executor, format="svg").output
        assert "#cc1122" in svg

    def test_dft_gray_scale_has_expected_slots(self):
        grays = get_config().dbt_grays
        assert "canvas" in grays
        assert "ink" in grays
        # creams uses the same D-025 vocabulary
        assert "canvas" in get_config().dbt_creams
        assert "ink" in get_config().dbt_creams

    def test_editorial_cream_theme_neutrals_match_dbt_creams_scale(self):
        from dbt_charts.core.compile.config import get_theme_style

        config = get_config()
        creams = config.dbt_creams
        theme = get_theme_style("cream")
        assert theme.background == creams["canvas"]
        assert theme.font.color == creams["ink"]
        assert theme.variables.font.color == creams["muted"]
        assert theme.border.color == creams["border"]
        # Board title softens one step lighter than `heading` in cream — the
        # `inactive` step keeps the board title authoritative without competing
        # with the chart titles below it in the title-inline band. Same pattern
        # the `default` theme applies with dbt-grays.inactive.
        assert theme.title.font.color == creams["inactive"]


class TestHtmlPageCanvas:
    """HTML converter uses the theme's page background as body fallback."""

    _YAML = (
        "title: Test\nqueries:\n  q:\n    type: values\n"
        "    rows:\n      - {month: Jan, revenue: 100}\ncharts:\n  c:\n"
        "    query: q\n    type: bar\n    x: month\n    y: revenue\nrows:\n  - c"
    )

    def _render_html(self, local_project: Callable[..., FilesystemProject], **opts):
        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.render import render

        result = compile(self._YAML)
        assert result.board is not None
        assert result.query_registry is not None
        assert result.success
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )
        return render(result.board, executor, format="html", **opts).output

    def test_html_body_uses_page_background_not_override(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """HTML body always uses page.background; the background option affects SVG only."""
        html = self._render_html(local_project, background="#ff0000")
        # HTML body color comes from page.background (theme), not the SVG canvas override.
        assert "background-color: #ff0000;" not in html

    def test_html_page_background_from_resolved_style(
        self, local_project: Callable[..., FilesystemProject]
    ):
        """Board-level style.page.background flows through the resolved style."""
        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.render import render

        yaml = (
            "title: Test\nstyle:\n  page:\n    background: '#ff0000'\n"
            "queries:\n  q:\n    type: values\n"
            "    rows:\n      - {month: Jan, revenue: 100}\ncharts:\n  c:\n    query: q\n    type: bar\n    x: month\n"
            "    y: revenue\nrows:\n  - c"
        )
        result = compile(yaml)
        assert result.board is not None
        assert result.query_registry is not None
        assert result.success
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )
        html = render(result.board, executor, format="html").output
        assert "background-color: #ff0000;" in html


class TestRenderedSurfaceBackground:
    """Root export surface background — override-based test only."""

    _YAML = (
        "title: Test\nqueries:\n  q:\n    type: values\n"
        "    rows:\n      - {month: Jan, revenue: 100}\ncharts:\n  c:\n"
        "    query: q\n    type: bar\n    x: month\n    y: revenue\nrows:\n  - c"
    )

    def test_png_render_uses_configured_default_scale(
        self, monkeypatch, local_project: Callable[..., FilesystemProject]
    ):
        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.render import renderer as renderer_module

        config = get_config()
        monkeypatch.setattr(config.rendering.png, "scale", 1.5)
        fake_to_png = mock.Mock(return_value=b"png-bytes")
        monkeypatch.setattr(renderer_module, "to_png", fake_to_png)

        result = compile(self._YAML)
        assert result.board is not None
        assert result.query_registry is not None
        assert result.success
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )
        output = renderer_module.render(result.board, executor, format="png").output

        assert output == b"png-bytes"
        fake_to_png.assert_called_once()
        assert fake_to_png.call_args.args[1] == 1.5

    def test_png_conversion_receives_the_viewer_svg(
        self, monkeypatch, local_project: Callable[..., FilesystemProject]
    ):
        """Format selection converts the canonical SVG instead of rerendering it."""
        from dbt_charts.core.compile import compile
        from dbt_charts.core.execute import Executor
        from dbt_charts.core.render import renderer as renderer_module

        yaml = """\
title: Canonical SVG
variables:
  region:
    input: select
    default: North
    options:
      static: [North, South]
queries:
  q:
    type: values
    rows:
      - {month: Jan, revenue: 100}
charts:
  c:
    query: q
    type: bar
    x: month
    y: revenue
rows:
  - c
"""
        result = compile(yaml)
        assert result.board is not None
        assert result.query_registry is not None
        assert result.success
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )
        viewer_svg = renderer_module.render(result.board, executor, format="svg").output
        assert isinstance(viewer_svg, str)

        fake_to_png = mock.Mock(return_value=b"png-bytes")
        monkeypatch.setattr(renderer_module, "to_png", fake_to_png)
        renderer_module.render(result.board, executor, format="png")
        converted_svg = fake_to_png.call_args.args[0]

        assert _normalize_same_run_svg(converted_svg) == _normalize_same_run_svg(
            viewer_svg
        )


class TestResolveStyleCaching:
    """resolve_style caching — must reuse cascade results across repeated calls."""

    def test_reuses_resolved_default_style(self):
        """Repeated default style resolution must return the identical cached object."""
        from dbt_charts.core.compile.config import (
            get_theme_style,
        )
        from dbt_charts.core.compile.resolve.style.board import resolve_style

        style = get_theme_style()
        result1 = resolve_style(style)
        result2 = resolve_style(style)
        result3 = resolve_style(style)
        assert result1 is result2
        assert result1 is result3

    # Shared-instance identity and top-level frozen contract are covered by
    # tests in dbt-charts/tests/core/compile/test_style_cascade.py
    # (TestResolveStyleCacheIdentity). They live in the cascade test module
    # because that is where resolve_style itself is exercised; this class
    # retains only the caching identity test above.
