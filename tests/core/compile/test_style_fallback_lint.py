"""Lint-ban guard: style attribute fallbacks must not creep back into compile/render.

After the convergence deletion sweep, resolved style objects carry no optional
fields that callers need to fill in with hardcoded defaults.  Two patterns are
banned:

1. `.<attr> or <fallback>`  — ``resolved_style.width or 600``
   The cascade fills every attribute; callers must not silently substitute a
   hardcoded literal when an attribute is absent.

2. ``getattr(obj, name, <non-None-literal>)`` where the line contains "style"
   — ``getattr(resolved_style, 'width', 600)``
   The only legitimate third argument is ``None`` (a cascade sentinel meaning
   "not set at this tier").  A non-None literal bypasses the cascade and reintroduces
   the very defaults this sweep removed.

Scope: compile and render sub-packages of the dataface core package.

No D-NN tokens in this file.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

_SCANNED_DIRS = [
    # Use importlib to avoid the compile/render names being shadowed by
    # exported functions in dbt_charts.core.__init__.
    Path(importlib.import_module("dbt_charts.core.compile").__file__).resolve().parent,
    Path(importlib.import_module("dbt_charts.core.render").__file__).resolve().parent,
]

# Pattern 1: style attribute OR'd with a hardcoded literal fallback, multi-level access.
# Matches: `resolved_style.title.font.color or ""`, `charts_style.padding or 12`.
# Requires the `or` operand to start with a quote or digit — only string/number
# literals are banned.  Fallbacks to another style field (`or resolved_style.color`)
# are intentional semantic cascades, not hardcoded defaults.
# Word-boundary alternatives prevent false positives on `stylesheet.url or`.
# Known limitation: ternary fallbacks (`x if x else d`) are covered by review,
# not by this regex.
_STYLE_OR_FALLBACK = re.compile(
    r"(?:\bstyle\b|\b\w+_style\b|\.style)(?:\.[a-zA-Z_]+)+\s+or\s+[\"'\d]"
)

# Pattern 2: getattr on a line containing "style" with a non-None third arg.
# Matches: `getattr(resolved_style, 'width', 600)`
# Does NOT match: `getattr(style, 'key', None)` — None third arg is fine (cascade sentinel).
# Regex: getattr( ... , ... , <not-None> )
# We match: getattr\( then skip to a second comma, then require the third arg starts
# with a non-whitespace, non-None token.
_GETATTR_NON_NONE = re.compile(r"getattr\([^,]+,\s*[^,]+,\s*(?!None\s*\))\S")


def _scan() -> list[tuple[Path, int, str]]:
    """Return (file, lineno, line) for every banned pattern found."""
    hits: list[tuple[Path, int, str]] = []
    for directory in _SCANNED_DIRS:
        for path in sorted(directory.rglob("*.py")):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                # Skip comments and docstrings — pattern might appear in
                # explanatory text (including this very file's docstring).
                if (
                    stripped.startswith("#")
                    or stripped.startswith('"""')
                    or stripped.startswith("'''")
                ):
                    continue
                if _STYLE_OR_FALLBACK.search(line) or (
                    "style" in line and _GETATTR_NON_NONE.search(line)
                ):
                    hits.append((path, lineno, line.rstrip()))
    return hits


def test_no_style_attribute_fallbacks() -> None:
    """Zero occurrences of banned style-fallback patterns in compile/ and render/.

    Banned patterns:
      - `.<attr> or <fallback>` on a resolved style object (style attribute OR'd with a literal)
      - `getattr(<style-expr>, <name>, <non-None-literal>)` (hardcoded default bypasses cascade)

    getattr(..., None) is ALLOWED — None is the cascade sentinel meaning "not set at this tier".
    """
    hits = _scan()
    if not hits:
        return
    lines = "\n".join(f"  {p}:{n}: {ln}" for p, n, ln in hits)
    raise AssertionError(
        f"Found {len(hits)} banned style-fallback pattern(s) in compile/ or render/.\n"
        f"Cascade fills every resolved-style field; hardcoded defaults bypass it.\n"
        f"Violations:\n{lines}"
    )
