"""Tests for core-owned chart hover runtime embedding."""

from collections.abc import Callable
from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.render import render

_TEST_YAML = """
title: Test Dashboard
queries:
  q1:
    type: values
    rows:
      - {month: Jan, revenue: 100}
      - {month: Feb, revenue: 150}
charts:
  c1:
    query: q1
    type: bar
    x: month
    y: revenue
rows:
  - c1
"""


def _compile_board(local_project: Callable[..., FilesystemProject]):
    result = compile(_TEST_YAML)
    assert result.success
    executor = Executor(
        result.board,
        adapter_registry=build_adapter_registry(local_project(Path.cwd())),
        query_registry=result.query_registry,
    )
    return result.board, executor


def test_svg_output_embeds_chart_hover_runtime(
    local_project: Callable[..., FilesystemProject],
):
    board, executor = _compile_board(local_project)

    svg_output = render(board, executor, format="svg").output

    assert "window.__dbtChartsChartHoverState" in svg_output
    assert "function escapeHtml(value)" in svg_output
    assert "className = 'dbt-tooltip'" in svg_output
    assert "document.currentScript" in svg_output


def test_html_output_inherits_chart_hover_runtime_from_svg(
    local_project: Callable[..., FilesystemProject],
):
    board, executor = _compile_board(local_project)

    html_output = render(board, executor, format="html").output

    assert "<!DOCTYPE html>" in html_output
    assert "<svg" in html_output
    assert "window.__dbtChartsChartHoverState" in html_output
