"""Data marks must be visible against the canvas they are drawn on.

The palette suite already checks marks against *each other* — the Leonardo
pairwise gate in ``test_editorial_10_palette.py`` asserts CIEDE2000 delta-E
>= 11 between stops under three CVD modes. Nothing checked marks against the
*page*, which is a different question with a different metric, and a stop can
pass one while failing the other: ``editorial-10`` slot 2 scores 20.2 pairwise
against slot 1 (comfortably discriminable) while sitting at 2.75:1 against a
near-white canvas.

Thresholds are tiered on purpose, and the tiers are the point of this module:

``single_series_palette``
    A theme's fixed ink for charts with no color channel. One value per theme,
    deliberately chosen, and the mark most likely to be a lone thin line or a
    small point with nothing beside it to be read against. Held to the 3:1
    non-text floor.

categorical slot 1
    The palette protagonist and the default first series. Same floor.

every other categorical slot
    A much lower "not invisible" floor. WCAG's 3:1 is written for UI component
    boundaries and for graphics that are the sole carrier of meaning; a series
    stop is typically a thick stroke with point markers and a direct label, and
    at that weight the ratio badly under-predicts real legibility. Four current
    ``editorial-10`` stops sit under 3:1 and read correctly in render. Gating
    them at 3:1 would force a palette change to satisfy a threshold that does
    not describe how these marks are used, so this tier only catches a stop
    that has genuinely vanished into the page.

No theme hex is pinned here — the thresholds are floors, not equality checks,
so a retune moves freely until it actually breaks legibility.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.colors import wcag_contrast as _wcag_contrast
from dbt_charts.core.compile.config import get_theme_style, list_built_in_themes

THEMES = [t for t in list_built_in_themes() if not t.startswith(("_", "diagnostics-"))]

MARK_FLOOR = 3.0
VISIBLE_FLOOR = 1.5


@pytest.mark.parametrize("theme", THEMES)
def test_single_series_mark_reads_against_its_canvas(theme: str) -> None:
    style = get_theme_style(theme)
    mark = style.charts.color.categorical.single_series_palette[0]
    contrast = _wcag_contrast(mark, style.background)
    assert contrast >= MARK_FLOOR, (
        f"theme {theme!r}: single-series mark {mark} on background "
        f"{style.background} is {contrast:.2f}:1 — a chart with no color "
        "channel would draw its only mark too faint to read"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_first_categorical_slot_reads_against_its_canvas(theme: str) -> None:
    style = get_theme_style(theme)
    slot_one = style.charts.color.categorical.palette[0]
    contrast = _wcag_contrast(slot_one, style.background)
    assert contrast >= MARK_FLOOR, (
        f"theme {theme!r}: categorical slot 1 {slot_one} on background "
        f"{style.background} is {contrast:.2f}:1 — the first series of every "
        "multi-series chart would be the faintest thing on it"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_no_categorical_stop_vanishes_into_the_canvas(theme: str) -> None:
    style = get_theme_style(theme)
    for slot, stop in enumerate(style.charts.color.categorical.palette, start=1):
        contrast = _wcag_contrast(stop, style.background)
        assert contrast >= VISIBLE_FLOOR, (
            f"theme {theme!r}: categorical slot {slot} {stop} on background "
            f"{style.background} is {contrast:.2f}:1 — that stop has "
            "disappeared into the page, not merely gone quiet"
        )
