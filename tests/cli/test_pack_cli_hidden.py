"""Guards that dashboard-pack scaffolding is not a public CLI surface."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from dbt_charts.cli.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_pack_command_is_not_registered() -> None:
    result = runner.invoke(app, ["pack", "--help"])

    assert result.exit_code != 0
    assert "No such command" in _plain(result.output + result.stderr)


def test_pack_command_absent_from_root_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    output = _plain(result.output)
    assert not re.search(r"^\s*pack\s", output, flags=re.MULTILINE)
