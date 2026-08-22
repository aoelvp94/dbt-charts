"""Pygments-driven syntax highlighting for fenced code blocks.

Pygments is a hard dependency of the `dbt-charts` wheel this module ships
inside, so it is always importable there. Callers must still treat a
``None`` return from :func:`highlight_code` as "render the plain
single-fill block" — the fence's language not being a known Pygments lexer
alias is a best-effort miss, not an error.

A bad `theme` name is different: it's a caller config error, so
``pygments.util.ClassNotFound`` from the theme lookup is allowed to
propagate uncaught.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

# One (text, color) pair per token; color is a CSS hex string ("#rrggbb").
CodeSegment = Tuple[str, str]


def _token_color(pygments_style: Any, token_type: Any) -> Optional[str]:
    """Resolve a token's color, walking up to a parent token type on KeyError.

    A theme's style table only has entries for token types it names
    explicitly (plus Pygments' STANDARD_TYPES); lexer-specific leaf tokens
    (e.g. YAML's ``Literal.Scalar.Plain``) can miss. Walking to `.parent` on
    a miss mirrors the same fallback Pygments' own
    Terminal256Formatter/HtmlFormatter use, and always terminates at the
    root `Token` type, which every style defines.

    Both params are boundary values from the untyped `pygments` package
    (a Style instance and a Token type), hence `Any`.
    """
    ttype = token_type
    while True:
        try:
            return pygments_style.style_for_token(ttype)["color"]
        except KeyError:
            ttype = ttype.parent


def highlight_code(
    code: str, language: str, theme: str
) -> Optional[List[List[CodeSegment]]]:
    """Tokenize `code` with Pygments and return per-source-line colored segments.

    Returns one list per line of `code.split("\\n")` (same count, same
    joined text) so callers can zip the result against the plain-text line
    list. Returns None when Pygments isn't importable or `language` isn't a
    recognized lexer alias — both are falls-through-to-plain-text cases.

    Args:
        code: The raw fenced-code-block text.
        language: The fence's info-string language (e.g. ``"python"``).
        theme: A Pygments theme name (e.g. ``"monokai"``).

    Returns:
        Per-line lists of (token_text, "#rrggbb") segments, or None to signal
        "render this block as plain, unhighlighted text".

    Raises:
        pygments.util.ClassNotFound: if `theme` isn't a known Pygments style
            name. Unlike an unresolvable lexer, a bad theme is a caller
            config error and must not be swallowed.
    """
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        from pygments.styles import get_style_by_name
        from pygments.util import ClassNotFound
    except ImportError:
        return None

    try:
        # stripall/stripnl/ensurenl all mutate the input (strip leading/trailing
        # whitespace, force a trailing newline) — disabled so the token stream
        # reconstructs byte-identical to `code`, keeping per-line alignment with
        # the plain-text `code.split("\n")` the renderer wraps/measures against.
        lexer = get_lexer_by_name(
            language, stripall=False, stripnl=False, ensurenl=False
        )
    except ClassNotFound:
        return None

    pygments_style = get_style_by_name(theme)  # bad theme: let ClassNotFound raise

    lines: List[List[CodeSegment]] = [[]]
    for token_type, value in lex(code, lexer):
        color = _token_color(pygments_style, token_type)
        fill = f"#{color}" if color else ""
        for i, part in enumerate(value.split("\n")):
            if i > 0:
                lines.append([])
            if part:
                lines[-1].append((part, fill))
    return lines
