"""Hint generators for error codes using difflib close-match suggestions.

`available` is `Sequence[str]` — a raise site writes `available=sorted(...)`,
the expression it naturally reaches for. `DbtChartsError.from_code` joins any
`Sequence[str]` for display at message-format time; `_suggest_close_match`
consumes the sequence directly.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence

# Names this release retired, each pointing at the successor that means what it
# meant. Diagnostic data, not vocabulary: nothing in the format system reads
# this, and a board using one of these still fails with ERR-FORMAT-INVALID.
#
# It exists because a value rename cannot be expressed as a schema migration — a
# `value_map` is declared total over its field's domain and `format:` is an open
# string, so every literal d3 spec an author may write would hard-fail a
# migration that has no business touching it. This hint is the whole migration
# path instead.
#
# Fuzzy matching is actively wrong for a rename: the nearest string to
# `currency_compact` is `currency_whole`, which compiles clean and silently
# drops compaction, so an author who followed that hint would get a changed
# render and no error at all.
#
# Drop an entry once boards predating its rename are no longer in the wild.
RETIRED_FORMAT_SUCCESSORS: dict[str, str] = {
    "currency_compact": "currency",
    "compact": "number",
    "number_default": "number",
}


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


def suggest_close_extends(
    entry: str,
    available: Sequence[str] = (),
    **_kwargs: object,  # type-state: object_annotation — hint_generator is called with every field of the code; the rest are heterogeneous and unread
) -> str | None:
    """Return a 'Did you mean X?' hint for an unresolvable `extends:` entry."""
    return _suggest_close_match(entry, available)


def suggest_close_format(
    spec: str,
    available: Sequence[str] = (),
    **_kwargs: object,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unresolvable format spec.

    A retired name gets its recorded successor rather than a fuzzy match — see
    ``RETIRED_FORMAT_SUCCESSORS`` for why the nearest string is the wrong answer
    for a rename.
    """
    successor = RETIRED_FORMAT_SUCCESSORS.get(spec)
    # Only when the successor is legal *here*: `available` is scoped to the
    # slot's own half of the vocabulary, so offering a number name to a
    # `time_format:` slot would trade a fuzzy wrong answer for a confident one.
    # An empty pool means no name is legal — the `style.formats` alias-target
    # check passes one, and a predefined successor there re-raises on the very
    # next compile.
    if successor is not None and successor in available:
        return f"{spec!r} was renamed to {successor!r}."
    return _suggest_close_match(spec, available)


def suggest_close_palette(
    name: str,
    available: Sequence[str] = (),
    # ERR-PALETTE-UNKNOWN's remaining field is `field_path`, a str.
    **_kwargs: str,
) -> str | None:
    """Return a 'Did you mean X?' hint for an unknown palette or palette role."""
    return _suggest_close_match(name, available)


def suggest_close_column(
    column_name: str,
    available: Sequence[str] = (),
    **_kwargs: object,  # type-state: object_annotation — hint_generator is called with every field of the code; the rest are heterogeneous and unread
) -> str | None:
    """Return a 'Did you mean X?' hint for a column a model no longer produces."""
    return _suggest_close_match(column_name, available)


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
