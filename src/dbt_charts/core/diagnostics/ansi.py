"""ANSI escape handling for strings that leave the terminal.

Two callers, two reasons, one regex: the diagnostics registry scrubs sqlglot's
underlining before a message reaches a browser tooltip or an LSP client, and
the terminal renderer measures visible width for layout.

It lives here rather than in `core/text/` because `core/diagnostics/` is
pinned `depends_on = []` — a deliberate leaf, which is what keeps
compile/execute/render from being reachable *through* it. Render may import
diagnostics, so the one direction that works is this one.
"""

from __future__ import annotations

import re

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Drop ANSI SGR escapes so a string is safe for any non-terminal surface."""
    return _ANSI_ESCAPE_RE.sub("", text)
