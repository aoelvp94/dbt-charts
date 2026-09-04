"""CLI smoke tests for `dct examples` — parity with `dct skills`."""

from __future__ import annotations

import json
import re

import yaml
from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


class TestExamplesList:
    def test_lists_specimens_with_title_and_category(self) -> None:
        result = runner.invoke(app, ["examples"])
        assert result.exit_code == 0, result.output
        output = _plain(result.output)
        assert "boards" in output
        assert "kpi-overview" in output
        assert "Revenue Overview" in output

    def test_json_output(self) -> None:
        result = runner.invoke(app, ["examples", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        slugs = [e["slug"] for e in data["examples"]]
        assert "boards/kpi-overview" in slugs

    def test_list_json_omits_yaml_bodies(self) -> None:
        result = runner.invoke(app, ["examples", "--json"])
        data = json.loads(result.output)
        assert all("yaml" not in e for e in data["examples"])


class TestExamplesGet:
    def test_prints_valid_board_yaml(self) -> None:
        result = runner.invoke(app, ["examples", "boards/kpi-overview"])
        assert result.exit_code == 0, result.output
        parsed = yaml.safe_load(result.output)
        assert parsed["title"] == "Revenue Overview"
        assert "charts" in parsed and "rows" in parsed

    def test_json_carries_yaml(self) -> None:
        result = runner.invoke(app, ["examples", "boards/kpi-overview", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["slug"] == "boards/kpi-overview"
        assert "charts:" in data["yaml"]

    def test_unknown_slug_exits_1(self) -> None:
        result = runner.invoke(app, ["examples", "nope/nope"])
        assert result.exit_code == 1


class TestExamplesSearch:
    def test_short_flag_searches(self) -> None:
        result = runner.invoke(app, ["examples", "-s", "kpi"])
        assert result.exit_code == 0, result.output
        assert "kpi-variants" in _plain(result.output)

    def test_search_json(self) -> None:
        result = runner.invoke(app, ["examples", "--search", "kpi", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["query"] == "kpi"
        assert data["hits"]

    def test_no_match_reports_cleanly(self) -> None:
        result = runner.invoke(app, ["examples", "-s", "zzzznotathing"])
        assert result.exit_code == 0, result.output
        assert "No examples matched" in _plain(result.output)

    def test_blank_search_is_a_parameter_error_not_a_traceback(self) -> None:
        result = runner.invoke(app, ["examples", "-s", "   "])
        assert result.exit_code == 2
        assert "Traceback" not in _plain(result.output)

    def test_slug_and_search_together_is_an_error(self) -> None:
        result = runner.invoke(app, ["examples", "boards/kpi-overview", "-s", "kpi"])
        assert result.exit_code == 1
