"""CLI tests for `dct docs`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    """Strip ANSI escape codes — CI sets FORCE_COLOR, which makes Rich split
    multi-char substrings like ``--limit`` across escape sequences."""
    return _ANSI_RE.sub("", text)


@pytest.fixture(autouse=True)
def patch_syntax_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch ``_SYNTAX_FILE`` to a controlled corpus for every CLI test."""
    fake = tmp_path / "DBT_CHARTS_SYNTAX.md"
    fake.write_text(
        "# Dataface YAML Syntax\n\n"
        "## Cheatsheet\nOne-screen reference.\n\n"
        "## Board\nThe board is the root dashboard object.\n\n"
        "## Queries\nQueries are the data layer.\n\n"
        "## Charts\nBar chart documentation. Use x and y fields.\n\n"
        "## Layout\nGrid layout for arranging charts.\n\n"
    )
    import dbt_charts.agent_api.docs._loader as _loader

    monkeypatch.setattr(_loader, "_SYNTAX_FILE", fake)


class TestDocsTopicIndex:
    def test_bare_invocation_prints_topic_index(self) -> None:
        result = runner.invoke(app, ["docs"])
        assert result.exit_code == 0, result.output
        assert "dbt-native dashboard layer" in result.output
        assert "offline YAML language reference" in result.output
        assert "Web docs:" in result.output
        assert "DCT_DOCS_URL" in result.output
        assert "Topics" in result.output
        assert "cheatsheet" in result.output
        assert "board" in result.output
        assert "charts" in result.output
        assert "dct docs all" in result.output
        assert "dct skills" in result.output

    def test_docs_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_DOCS_URL", "https://docs.example.test")
        result = runner.invoke(app, ["docs"])
        assert result.exit_code == 0, result.output
        assert "https://docs.example.test/cli/docs/" in result.output

    def test_topic_index_json(self) -> None:
        result = runner.invoke(app, ["docs", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["mode"] == "index"
        slugs = [entry["id"] for entry in data["topics"]]
        assert slugs == ["cheatsheet", "board", "queries", "charts", "layout"]
        for entry in data["topics"]:
            assert set(entry.keys()) >= {"id", "title"}


class TestDocsTopic:
    def test_topic_outputs_markdown(self) -> None:
        result = runner.invoke(app, ["docs", "board"])
        assert result.exit_code == 0, result.output
        assert "The board is the root dashboard object" in result.output

    def test_all_returns_whole_file(self) -> None:
        result = runner.invoke(app, ["docs", "all"])
        assert result.exit_code == 0, result.output
        assert "Dataface YAML Syntax" in result.output
        assert "## Cheatsheet" in result.output
        assert "## Charts" in result.output

    def test_topic_json_envelope(self) -> None:
        result = runner.invoke(app, ["docs", "board", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["mode"] == "topic"
        assert data["topic"]["id"] == "board"
        assert data["topic"]["title"] == "Board"
        assert "content" in data["topic"]


class TestDocsSearch:
    def test_search_long_flag(self) -> None:
        result = runner.invoke(app, ["docs", "--search", "grid"])
        assert result.exit_code == 0, result.output
        assert "layout" in result.output

    def test_search_short_flag(self) -> None:
        result = runner.invoke(app, ["docs", "-s", "grid"])
        assert result.exit_code == 0, result.output
        assert "layout" in result.output

    def test_search_json(self) -> None:
        result = runner.invoke(app, ["docs", "--search", "grid", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["mode"] == "search"
        topics = [hit["topic"] for hit in data["search"]]
        assert "layout" in topics
        for hit in data["search"]:
            assert set(hit.keys()) >= {"topic", "title", "score", "snippet"}


class TestDocsUnknownTopic:
    def test_unknown_topic_exits_one(self) -> None:
        result = runner.invoke(app, ["docs", "zzz"])
        assert result.exit_code == 1

    def test_close_match_appears_in_stderr(self) -> None:
        result = runner.invoke(app, ["docs", "char"])
        assert result.exit_code == 1
        assert "charts" in result.stderr

    def test_unknown_topic_json_envelope(self) -> None:
        result = runner.invoke(app, ["docs", "zzz", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["success"] is False
        assert data["mode"] == "topic"
        assert isinstance(data["errors"], list) and data["errors"]
        assert "Unknown topic: zzz" in data["errors"]
        assert isinstance(data["hints"], list)


class TestDocsLimitBounds:
    @pytest.mark.parametrize("limit", ["1", "5", "50"])
    def test_in_range_limit_accepted(self, limit: str) -> None:
        result = runner.invoke(
            app, ["docs", "--search", "grid", "--limit", limit, "--json"]
        )
        assert result.exit_code == 0, result.output

    def test_zero_limit_exit_two(self) -> None:
        result = runner.invoke(app, ["docs", "--search", "grid", "--limit", "0"])
        assert result.exit_code == 2
        assert "--limit" in _plain(result.stderr)

    def test_oversize_limit_exit_two(self) -> None:
        result = runner.invoke(app, ["docs", "--search", "grid", "--limit", "51"])
        assert result.exit_code == 2
        assert "--limit" in _plain(result.stderr)


class TestDftDocsHelpLayout:
    def test_help_modes_on_separate_lines(self) -> None:
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0
        text = _plain(result.output)
        lines = [line.strip() for line in text.splitlines()]
        for form in (
            "dct docs                    # Topic index (one row per H2 section)",
            "dct docs cheatsheet         # One-page essentials",
            "dct docs all                # Whole reference, unsliced",
            'dct docs --search "grid"    # Substring search across all topics',
        ):
            assert form in lines, (
                f"Docs mode {form!r} not on its own line. Full output:\n{text}"
            )
