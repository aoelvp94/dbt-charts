"""Smoke tests for the `dct search` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()


_SEARCH_BOARD = """\
title: Revenue Dashboard
description: Monthly revenue trends
queries:
  revenue:
    sql: "select month, sum(revenue) from orders group by 1"
charts:
  rev_chart:
    query: revenue
    type: bar
    x: month
    y: revenue
rows:
  - rev_chart
"""


@pytest.fixture
def dashboard_dir(tmp_path: Path) -> Path:
    (tmp_path / "dbt_charts.yml").write_text("# project marker\n")
    boards = tmp_path / "charts"
    boards.mkdir()
    (boards / "revenue.yml").write_text(_SEARCH_BOARD)
    return tmp_path


class TestSearchJsonOutput:
    def test_hit_json(self, dashboard_dir: Path) -> None:
        result = runner.invoke(
            app, ["search", "revenue", "--json", "--project-dir", str(dashboard_dir)]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert len(data["results"]) >= 1
        assert data["results"][0]["title"] == "Revenue Dashboard"

    def test_json_validates_against_model(self, dashboard_dir: Path) -> None:
        from dbt_charts.agent_api.search import SearchResult

        result = runner.invoke(
            app, ["search", "revenue", "--json", "--project-dir", str(dashboard_dir)]
        )
        assert result.exit_code == 0
        parsed = SearchResult.model_validate_json(result.output)
        assert parsed.success is True

    def test_empty_query_returns_empty(self, dashboard_dir: Path) -> None:
        result = runner.invoke(
            app,
            ["search", "xyznotfound", "--json", "--project-dir", str(dashboard_dir)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["results"] == []


class TestSearchRichOutput:
    def test_hit_shows_title_and_path(self, dashboard_dir: Path) -> None:
        result = runner.invoke(
            app, ["search", "revenue", "--project-dir", str(dashboard_dir)]
        )
        assert result.exit_code == 0
        assert "Revenue Dashboard" in result.output

    def test_no_results_message(self, dashboard_dir: Path) -> None:
        result = runner.invoke(
            app, ["search", "xyznotfound", "--project-dir", str(dashboard_dir)]
        )
        assert result.exit_code == 0
        assert "No results" in result.output


class TestSearchHelpText:
    def test_help_contains_query_description(self) -> None:
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "keyword" in result.output.lower()
