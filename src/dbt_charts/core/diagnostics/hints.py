"""Hint generators for error codes using difflib close-match suggestions.

`available` is `Sequence[str]` — a raise site writes `available=sorted(...)`,
the expression it naturally reaches for. `DbtChartsError.from_code` joins any
`Sequence[str]` for display at message-format time; `_suggest_close_match`
consumes the sequence directly.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence


def _suggest_close_match(value: str, available: Sequence[str]) -> str | None:
    if isinstance(available, str):
        raise TypeError(
            "available must be a Sequence[str] of candidate names, not a bare "
            "str (which is itself a Sequence[str] of characters and would "
            "silently score character-by-character) — pass "
            "available=['a', 'b'] instead of a joined string."
        )
    candidates = [c.strip() for c in available if c.strip()]
    if not candidates:
        return None
    matches = difflib.get_close_matches(value, candidates, n=1, cutoff=0.5)
    if matches:
        return f"Did you mean {matches[0]!r}?"
    return None


def suggest_close_source(
    source: str,
    available: Sequence[str] = (),
    **_kwargs: object,
) -> str | None:
    """Return a 'Did you mean X?' hint for unknown source names."""
    return _suggest_close_match(source, available)


def suggest_close_theme(
    theme: str,
    available: Sequence[str] = (),
    **_kwargs: object,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unknown theme name."""
    return _suggest_close_match(theme, available)


def suggest_close_format(
    spec: str,
    available: Sequence[str] = (),
    **_kwargs: object,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unresolvable format spec."""
    return _suggest_close_match(spec, available)


def suggest_close_palette(
    name: str,
    available: Sequence[str] = (),
    # ERR-PALETTE-UNKNOWN's remaining field is `field_path`, a str.
    **_kwargs: str,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unknown palette or palette role."""
    return _suggest_close_match(name, available)


def suggest_close_ref(
    ref_name: str,
    available: Sequence[str] = (),
    **_kwargs: object,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unknown dbt ref() target."""
    return _suggest_close_match(ref_name, available)


def suggest_close_source_table(
    source_name: str,
    table_name: str,
    available: Sequence[str] = (),
    **_kwargs: object,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unknown dbt source() reference."""
    return _suggest_close_match(f"{source_name}.{table_name}", available)
