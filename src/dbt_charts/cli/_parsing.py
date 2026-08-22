"""Parse repeatable `--flag key=value` options into a dict."""

from __future__ import annotations

from collections.abc import Iterable

import typer


def parse_kv_pairs(items: Iterable[str], flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"{flag} expects key=value, got: {item!r}")
        k, v = item.split("=", 1)
        out[k] = v
    return out
