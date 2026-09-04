"""Measurement and painting must read the same glyph metrics.

dbt charts measures text with fontTools to decide where lines wrap; the browser paints
that text from the ``@font-face`` files embedded in the board SVG. When the two read
different files the wrap points are computed against the wrong advance widths, and a
full-width prose line overflows its nested ``<svg>`` viewport — which clips by default,
silently destroying the end of the sentence.

These tests pin the invariant that closes that gap: for every family we paint, the file
we measure and the file we paint agree on advance width for every codepoint they share.
"""

from __future__ import annotations

import pytest
from fontTools.ttLib import TTFont  # pyright: ignore[reportMissingTypeStubs]

from dbt_charts.core.fonts import (
    FONT_REGISTRY,
    VendoredFace,
    get_font_path,
    get_fonts_dir,
)


def _advance_widths(path: str) -> dict[int, float]:
    """Return {codepoint: advance width in em} for a font file."""
    font = TTFont(path)
    cmap = font.getBestCmap()
    metrics = font["hmtx"].metrics  # pyright: ignore[reportAttributeAccessIssue]
    upm = font["head"].unitsPerEm  # pyright: ignore[reportAttributeAccessIssue]
    return {
        cp: metrics[glyph][0] / upm for cp, glyph in cmap.items() if glyph in metrics
    }


def assert_same_metrics(measured_path: str, painted_path: str) -> None:
    """Fail if two font files disagree on any shared codepoint's advance width.

    Scoped to the shared cmap on purpose: the shipped ``.woff2`` files are subset to
    the shared text recipe (``fonts.TEXT_SUBSET_RANGES``) while the measured TTFs are
    the full boards, so dbt charts can measure codepoints the browser will not paint from
    our file. For those the browser falls through to the next family in the CSS stack,
    which we cannot measure and do not claim to. That the served file covers every
    recipe codepoint its TTF measures is a separate guard, in
    ``test_font_registry.py`` — this one only pins that shared widths agree.
    """
    measured = _advance_widths(measured_path)
    painted = _advance_widths(painted_path)

    shared = sorted(set(measured) & set(painted))
    assert shared, f"{measured_path} and {painted_path} share no codepoints"

    mismatches = [
        (chr(cp), measured[cp], painted[cp])
        for cp in shared
        if measured[cp] != painted[cp]
    ]
    assert not mismatches, (
        f"Measured {measured_path} but painted {painted_path}: they disagree on "
        f"{len(mismatches)} of {len(shared)} shared codepoints. Wrapping is computed "
        f"from the first and drawn with the second, so every disagreement puts a wrap "
        f"point in the wrong place. First five (char, measured em, painted em): "
        f"{mismatches[:5]}"
    )


def test_source_serif_measures_the_cut_it_paints() -> None:
    """The serif board we measure is the serif board the browser draws.

    Regression test for the clipped-prose bug: measurement read the static
    ``SourceSerif4-Regular.ttf`` while the browser painted the variable
    ``SourceSerif4Variable.woff2``. Same family name, same declared weight,
    different builds — the browser drew ~6.6% wider than we measured, so wide prose
    lines ran past their nested SVG viewport and were cut off mid-word.
    """
    assert_same_metrics(
        get_font_path("Source Serif 4"),
        str(get_fonts_dir() / "SourceSerif4Variable.woff2"),
    )


@pytest.mark.parametrize(
    "board",
    [f for f in FONT_REGISTRY if f.web_file is not None],
    ids=lambda f: f"{f.family}-{f.style}".replace(" ", "-"),
)
def test_every_served_board_measures_the_file_it_paints(board: VendoredFace) -> None:
    """The whole registry holds the invariant, not just the family that broke.

    A future asset swap that updates one column of a registry row and not the other
    fails here rather than shipping mis-wrapped prose to every board using that family.
    """
    assert board.web_file is not None
    assert_same_metrics(str(board.measure_path), str(get_fonts_dir() / board.web_file))
