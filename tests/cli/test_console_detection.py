"""Unit tests for cli/_console.py — agent/pipe context detection."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from dbt_charts.cli._console import AGENT_ENV_VARS, dct_console, is_plain_output


@pytest.mark.parametrize("var", AGENT_ENV_VARS)
def test_is_plain_output_true_when_agent_var_set(
    var: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each supported agent env var, alone, triggers plain output even on a TTY."""
    for other in AGENT_ENV_VARS:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(var, "1")
    with patch.object(sys.stdout, "isatty", return_value=True):
        assert is_plain_output() is True


def test_is_plain_output_true_when_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-TTY stdout triggers plain output even without agent vars."""
    for v in AGENT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    with patch.object(sys.stdout, "isatty", return_value=False):
        assert is_plain_output() is True


def test_is_plain_output_false_when_tty_and_no_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY stdout with no agent vars → rich output (not plain)."""
    for v in AGENT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    with patch.object(sys.stdout, "isatty", return_value=True):
        assert is_plain_output() is False


# ---------------------------------------------------------------------------
# dct_console() factory tests
# ---------------------------------------------------------------------------


def test_dct_console_uses_plain_kwargs_when_plain_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In plain mode (CLAUDECODE=1), dct_console() builds a no-color, non-terminal Console."""
    monkeypatch.setenv("CLAUDECODE", "1")
    with patch.object(sys.stdout, "isatty", return_value=True):
        console = dct_console()
    assert console.no_color is True
    assert console.is_terminal is False


def test_dct_console_uses_rich_kwargs_when_plain_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no agent var and a TTY, dct_console() builds a color, terminal Console."""
    for v in AGENT_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    with patch.object(sys.stdout, "isatty", return_value=True):
        console = dct_console()
    assert console.no_color is False
    assert console.is_terminal is True


def test_dct_console_stderr_true_routes_to_stderr() -> None:
    """dct_console(stderr=True) writes to sys.stderr."""
    console = dct_console(stderr=True)
    assert console.file is sys.stderr
