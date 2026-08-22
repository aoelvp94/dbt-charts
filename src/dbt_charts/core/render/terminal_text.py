"""ANSI-aware string width helpers for terminal layout joining."""

from __future__ import annotations

from dbt_charts.core.diagnostics.ansi import strip_ansi


def visible_len(text: str) -> int:
    return len(strip_ansi(text))


def pad_visible(text: str, width: int) -> str:
    padding = width - visible_len(text)
    if padding <= 0:
        return text
    return text + (" " * padding)


def truncate_visible(text: str, max_width: int) -> str:
    if visible_len(text) <= max_width:
        return text
    plain = strip_ansi(text)
    if max_width <= 3:
        return plain[:max_width]
    return plain[: max_width - 3] + "..."
