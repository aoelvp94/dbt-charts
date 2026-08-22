"""Tests for the `dct playground` Typer wiring.

`dct playground` is wired into the root Typer at import time via `add_typer`
when `dbt_charts_playground` is installed, and falls back to a stub command
that prints an install hint when it isn't. The contract:

- `dct playground --help` renders the real Typer-generated option table
  (`--port`, `--host`, `--base-dir`, `--data`, `--openai-key`, `--no-open`,
  `--reload`) plus the `OPENAI_API_KEY` envvar binding — not a hand-written
  prose list.
- `dct playground --port 1234 …` dispatches to `dbt_charts_playground.cli.main`
  with parsed options.
- When `dbt_charts_playground` is not importable, the stub command exits 1
  with `pip install dbt-charts[playground]` on stderr — no traceback.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import os
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import dbt_charts.cli.main as cli_main
from dbt_charts.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """CLI dispatch mutates os.environ directly; restore after each test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_playground_help_renders_real_typer_options() -> None:
    """`dct playground --help` shows the real options, not the old stub prose."""
    result = runner.invoke(app, ["playground", "--help"])
    assert result.exit_code == 0, result.output
    out = _plain(result.output)

    # Every option declared on dbt_charts_playground.cli.main appears in help.
    for flag in (
        "--port",
        "--host",
        "--data",
        "--base-dir",
        "--openai-key",
        "--no-open",
        "--reload",
    ):
        assert flag in out, f"missing {flag} in --help output:\n{out}"

    # Typer documents the envvar binding on --openai-key automatically.
    assert "OPENAI_API_KEY" in out


def test_playground_dispatch_passes_parsed_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dct playground <opts>` reaches uvicorn with the parsed kwargs."""
    import uvicorn

    # Sandbox env + cwd so the body doesn't read the worktree's .env or
    # leak DCT_PLAYGROUND_MODE / BASE_DIR / OPENAI_API_KEY into other tests.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DCT_PLAYGROUND_MODE", raising=False)
    monkeypatch.delenv("DCT_PLAYGROUND_BASE_DIR", raising=False)
    monkeypatch.delenv("DCT_CACHE_PATH", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch.object(uvicorn, "run") as mock_run:
        result = runner.invoke(
            app,
            [
                "playground",
                "--port",
                "9999",
                "--no-open",
                "--host",
                "127.0.0.99",
                "--base-dir",
                str(tmp_path),
                "--openai-key",
                "sk-test-abc",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args.args, mock_run.call_args.kwargs
    assert args[0] == "dbt_charts_playground.app:app"
    assert kwargs["port"] == 9999
    assert kwargs["host"] == "127.0.0.99"
    assert kwargs["reload"] is False
    assert kwargs["reload_dirs"] is None
    # --base-dir and --openai-key are forwarded via env vars (the only
    # observable seam without booting uvicorn).
    assert os.environ.get("DCT_PLAYGROUND_BASE_DIR") == str(tmp_path)
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-abc"


def test_playground_missing_package_exits_one_with_install_hint() -> None:
    """When dbt_charts_playground is not installed, stub delegates to require_extras."""
    real_find_spec = importlib.util.find_spec

    def _absent_for_playground(
        name: str, package: str | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if name == "dbt_charts_playground":
            return None
        return real_find_spec(name, package)

    try:
        with patch.object(
            importlib.util, "find_spec", side_effect=_absent_for_playground
        ):
            reloaded = importlib.reload(cli_main)
            result = runner.invoke(reloaded.app, ["playground"])
    finally:
        importlib.reload(cli_main)

    assert result.exit_code == 1
    output = result.output + (result.stderr or "")
    # require_extras renders a Rich Panel naming the missing dist and the extra.
    assert "dbt-charts-playground" in output
    assert "[playground]" in output
    assert "Traceback" not in output
