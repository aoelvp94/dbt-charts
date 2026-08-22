"""Tests for ANSI-aware terminal string width helpers."""

from dbt_charts.core.render.terminal_text import (
    pad_visible,
    strip_ansi,
    truncate_visible,
    visible_len,
)


def test_visible_len_ignores_ansi() -> None:
    text = "\x1b[32mRevenue\x1b[0m"
    assert visible_len(text) == len("Revenue")
    assert strip_ansi(text) == "Revenue"


def test_pad_visible_aligns_colored_text() -> None:
    line = "\x1b[32mOK\x1b[0m"
    padded = pad_visible(line, 10)
    assert visible_len(padded) == 10
    assert padded.endswith("       ")


def test_truncate_visible_strips_ansi_when_narrow() -> None:
    line = "\x1b[31m" + ("x" * 20) + "\x1b[0m"
    out = truncate_visible(line, 8)
    assert visible_len(out) == 8
    assert out.endswith("...")
