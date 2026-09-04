"""Tests for `dct impact` — thin wrapper over agent_api.impact."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dbt_charts.cli import main as cli_main

runner = CliRunner()

_BOARD = """\
title: Sales
source: db
queries:
  o: SELECT customer_id, amount FROM orders
charts:
  c:
    query: o
    type: table
rows:
  - c
"""


def _seed(tmp_path: Path) -> None:
    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n  db:\n    type: duckdb\n    path: ':memory:'\n"
    )
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "sales.yaml").write_text(_BOARD)


def test_impact_lists_referencing_boards(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = runner.invoke(
        cli_main.app, ["impact", "customer_id", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "charts/sales.yaml" in result.output
    assert "orders" in result.output


def test_impact_json_is_typed(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = runner.invoke(
        cli_main.app,
        ["impact", "customer_id", "--json", "--project-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["hits"] == [
        {
            "board": "charts/sales.yaml",
            "query": "o",
            "table": "orders",
            "column": "customer_id",
        }
    ]


def test_impact_no_hits_says_so(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = runner.invoke(
        cli_main.app, ["impact", "nonexistent", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "No board queries reference" in result.output


def test_impact_indeterminate_boards_are_surfaced(tmp_path: Path) -> None:
    _seed(tmp_path)
    (tmp_path / "charts" / "star.yaml").write_text(
        "title: S\nsource: db\nqueries:\n  q: SELECT * FROM orders\n"
        "charts:\n  c:\n    query: q\n    type: table\nrows:\n  - c\n"
    )
    result = runner.invoke(
        cli_main.app, ["impact", "customer_id", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "charts/star.yaml" in result.output
    assert "Could not be analyzed" in result.output


def test_bracketed_paths_survive_rich_markup(tmp_path: Path) -> None:
    """A board at charts/[archive]/x.yaml must print verbatim — unescaped
    Rich markup would swallow the bracket segment or raise MarkupError."""
    _seed(tmp_path)
    archive = tmp_path / "charts" / "[archive]"
    archive.mkdir()
    (archive / "old.yaml").write_text(_BOARD)
    result = runner.invoke(
        cli_main.app, ["impact", "customer_id", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "[archive]" in result.output


def test_zero_boards_message(tmp_path: Path) -> None:
    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n  db:\n    type: duckdb\n    path: ':memory:'\n"
    )
    result = runner.invoke(
        cli_main.app, ["impact", "customer_id", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "No boards found under charts/" in result.output
