"""Console factory and agent/pipe context detection for the dct CLI."""

from __future__ import annotations

import os
import sys

from rich.console import Console

# The list of env vars to check is fixed at module load; values are looked
# up per call via os.environ.get.
AGENT_ENV_VARS = (
    "CLAUDECODE",  # Claude Code (official)
    "GEMINI_CLI",  # Gemini CLI (official)
    "CLINE_ACTIVE",  # Cline v3.24+ (official)
    "CURSOR_AGENT",  # Cursor (acknowledged, undocumented)
    "COPILOT_CLI",  # GitHub Copilot CLI (community-observed)
    "GOOSE_TERMINAL",  # Goose (official)
    "AGENT",  # Goose + Amp + emerging cross-agent convention
    "AI_AGENT",  # Vercel-proposed universal fallback
)


def is_plain_output() -> bool:
    """Return True when output should be plain (no Rich chrome).

    True when running inside a known AI agent or when stdout is not a TTY
    (e.g. piped to cat, redirected to a file).
    """
    return any(os.environ.get(v) for v in AGENT_ENV_VARS) or not sys.stdout.isatty()


def dct_console(*, stderr: bool = False) -> Console:
    """Build a Rich Console that honors is_plain_output() at call time.

    Use this in CLI command modules instead of bare Console(...) so that
    agent-PTY and piped contexts (CLAUDECODE=1, stdout-to-file, ...) get
    plain output uniformly.
    """
    plain = is_plain_output()
    return Console(
        stderr=stderr,
        force_terminal=not plain,
        no_color=plain,
    )


__all__ = ["AGENT_ENV_VARS", "dct_console", "is_plain_output"]
