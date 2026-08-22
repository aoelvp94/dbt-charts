"""Every user-visible `dct` command that accepts `--project-dir` must show
the same canonical help string. Pins the shared `ProjectDirOption` alias —
if anyone re-inlines a divergent help string, this test catches it.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dbt_charts.cli.main import app

CANONICAL_HELP = "Project root for resolving board paths and finding project config"

COMMANDS = [
    ["init", "--help"],
    ["init", "mcp", "--help"],
    ["mcp", "serve", "--help"],
    ["describe", "--help"],
    ["render", "--help"],
    ["search", "--help"],
    ["serve", "--help"],
    ["validate", "--help"],
    ["query", "--help"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a[:-1]))
def test_project_dir_help_is_canonical(argv: list[str]) -> None:
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output
    # Click wraps help text into a column; collapse whitespace before searching.
    normalized = " ".join(result.output.split())
    assert CANONICAL_HELP in normalized, (
        f"`dct {' '.join(argv[:-1])} --help` does not contain the canonical "
        f"--project-dir help string.\nExpected: {CANONICAL_HELP!r}\n"
        f"Got:\n{result.output}"
    )
