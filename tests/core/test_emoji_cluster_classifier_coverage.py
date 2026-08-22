"""Cross-package coverage: mdsvg's hand-rolled emoji classifier vs our curated set.

Every individual emoji authored in the curated chart-emoji groups must be
recognized as a single cluster that consumes exactly its own codepoints -- not
merely "some non-zero recognition", which cannot see a classifier that folds a
cluster short and leaves a codepoint orphaned (an orphaned codepoint still
makes the non-zero check pass on the *next* position).
"""

from __future__ import annotations

import pytest

from dbt_charts.core.fonts import (
    _EMOJI_DOCS,
    _EMOJI_FACES,
    _EMOJI_MARKS,
    _EMOJI_MONEY,
    _EMOJI_OPS,
    _EMOJI_ORG_GEO,
    _EMOJI_STATUS,
    _EMOJI_TIME,
    _EMOJI_TREND,
    _EMOJI_WEATHER,
)
from mdsvg.fonts import _emoji_cluster_length

_VARIATION_SELECTOR_16 = "️"

# Codepoints a curated group is not expected to contain today. A bare ZWJ,
# keycap mark, or lone regional-indicator half each already make
# `_authored_spellings` produce a spelling `_emoji_cluster_length` measures as
# 0 -- the test below catches those for free, no guard needed. A skin-tone
# modifier is the one shape that would NOT be caught: it sits inside the
# pictograph range, so `_authored_spellings` reads it as its own
# independently-valid one-codepoint spelling instead of as an extension of the
# preceding base, and the oracle would report the group as covered while never
# exercising the fold. All four are guarded together anyway, so the failure
# mode is "update this splitter" rather than a silent pass either way.
_UNEXPECTED_JOINER_CODEPOINTS = frozenset(
    {0x200D, 0x20E3, *range(0x1F1E6, 0x1F200), *range(0x1F3FB, 0x1F400)}
)

_CURATED_GROUPS = (
    _EMOJI_STATUS,
    _EMOJI_TREND,
    _EMOJI_TIME,
    _EMOJI_MONEY,
    _EMOJI_OPS,
    _EMOJI_ORG_GEO,
    _EMOJI_MARKS,
    _EMOJI_DOCS,
    _EMOJI_FACES,
    _EMOJI_WEATHER,
)


def _authored_spellings(group: str) -> list[str]:
    """Split a curated group string into its individual authored spellings.

    Each spelling is one base codepoint plus an optional immediately-following
    VS16 -- the only shape these groups contain today (no keycap, no ZWJ, no
    flag, no skin tone). Raises if that assumption stops holding, rather than
    silently mis-splitting a shape it wasn't built to handle.
    """
    for char in group:
        if ord(char) in _UNEXPECTED_JOINER_CODEPOINTS:
            raise ValueError(
                f"curated group contains U+{ord(char):04X}, a joiner/modifier "
                "this splitter doesn't model -- update _authored_spellings "
                "(and its test) before trusting this oracle for it"
            )

    spellings: list[str] = []
    i = 0
    while i < len(group):
        j = i + 1
        if j < len(group) and group[j] == _VARIATION_SELECTOR_16:
            j += 1
        spellings.append(group[i:j])
        i = j
    return spellings


def test_authored_spellings_raises_on_a_skin_tone_modifier() -> None:
    """The one shape the guard exists for: a skin-tone modifier would
    otherwise be read as its own independently-valid spelling instead of an
    extension of the preceding base, silently passing without ever
    exercising the fold."""
    with pytest.raises(ValueError, match="U\\+1F3FD"):
        _authored_spellings("\U0001f44d\U0001f3fd")  # thumbs up + medium skin tone


def test_every_curated_emoji_spelling_is_fully_consumed_as_one_cluster() -> None:
    spellings = [s for group in _CURATED_GROUPS for s in _authored_spellings(group)]
    assert spellings, "curated groups must contain at least one authored spelling"

    wrong = {
        spelling: _emoji_cluster_length(spelling, 0)
        for spelling in spellings
        if _emoji_cluster_length(spelling, 0) != len(spelling)
    }
    assert not wrong, (
        "curated emoji spellings not fully consumed as a single cluster "
        "(spelling -> codepoints consumed): "
        + ", ".join(f"{s!r} -> {n}" for s, n in wrong.items())
    )
