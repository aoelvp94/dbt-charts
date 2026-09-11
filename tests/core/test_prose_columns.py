"""The measure a reader actually gets, through the real render path.

Column count and column width are decided together: the count that lands
nearest the target measure wins, and where no integer count is readable the
measure wins and the slot keeps the remainder as white space. These assert the
delivered line length rather than the arithmetic that chose it.
"""

from __future__ import annotations

import dataclasses
import html
import re

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.font_measure import markdown_font_faces, measurer_for_face
from dbt_charts.core.render.prose import render_prose_svg
from dbt_charts.core.render.sizing import body_text_font_family, get_compact_style

LONG = (
    "North America's primary issue is insufficient MQL supply, not a regional "
    "Stage 0 target miss or a broad loss of selling capacity. Event sources "
    "explain most of the decline, while target-aligned Stage 0 remained above "
    "target and the funnel table stays the single source for the counts.\n\n"
    "Paid search held its conversion rate within a point of plan across the "
    "quarter, so the shortfall is concentrated upstream rather than in the "
    "closing motion. Field events, which carried a third of pipeline a year "
    "ago, produced fewer registrations and a materially lower show rate."
)
SHORT = "Revenue grew 12% against a plan of 9%, carried almost entirely by renewals."

WCAG_MAX_LINE_LENGTH = 80


def render(markdown: str, width: float, **column: object) -> str:
    resolved = resolve_style(get_theme_style("clarity"))
    text_style = resolved.text.model_copy(
        update={"column": resolved.text.column.model_copy(update=column)}
    )
    svg, _ = render_prose_svg(markdown, width, text_style, resolved)
    return svg


def longest_line(svg: str) -> int:
    runs = [
        re.sub(r"<[^>]+>", "", t).strip()
        for t in re.findall(r"<text[^>]*>(.*?)</text>", svg, re.S)
    ]
    return max(len(r) for r in runs if r)


def _column_x_offsets(svg: str) -> set[float]:
    """Every column's x offset, including the first.

    The first column sits at x=0, a no-op translate the renderer no longer
    wraps in a `<g>` (see svg_utils.translate_group) -- so it never appears in
    the `translate(x, 0)` matches directly and is added back explicitly.
    """
    return {0.0} | {float(m) for m in re.findall(r"translate\((\d[\d.]*), 0\)", svg)}


def column_count(svg: str) -> int:
    return len(_column_x_offsets(svg))


def second_column_offset(svg: str) -> float:
    offsets = sorted(_column_x_offsets(svg))
    assert len(offsets) >= 2, f"expected at least two columns, got {offsets}"
    return offsets[1]


@pytest.mark.parametrize("width", [1096.0, 900.0, 840.0, 672.0, 533.0, 400.0])
def test_no_board_width_exceeds_the_wcag_cap(width: float) -> None:
    svg = render(LONG, width, max_number=3)
    assert longest_line(svg) <= WCAG_MAX_LINE_LENGTH


def test_a_short_passage_is_held_to_a_narrow_column() -> None:
    """Length is no excuse for line length.

    A 1096px slot is 178 characters of body text. A passage too short to fill
    columns still gets a readable measure -- the slot keeps the rest as white
    space rather than setting one very long line.
    """
    svg = render(SHORT, 1096.0, max_number=3)
    assert column_count(svg) == 1
    assert longest_line(svg) <= WCAG_MAX_LINE_LENGTH


def test_an_author_measure_overrides_the_shipped_one() -> None:
    narrow = render(LONG, 1096.0, max_number=3, max_chars=40)
    wide = render(LONG, 1096.0, max_number=3, max_chars=70)
    assert longest_line(narrow) <= 42
    assert 60 <= longest_line(wide) <= 72


def test_max_number_caps_the_count_an_author_measure_would_derive() -> None:
    """A narrow max_chars would fit four columns; max_number holds it to two."""
    svg = render(LONG, 1096.0, max_number=2, max_chars=40)
    assert column_count(svg) == 2
    assert longest_line(svg) <= 42


def test_authored_gap_is_pixels_not_line_boxes() -> None:
    """An authored column.gap is used as pixels, exactly, not scaled by the line box.

    Doubling an authored gap from 24 to 48 must move the second column by
    exactly 24px -- not by ``24 * line_box`` pixels, which is what
    reinterpreting the field as a line-box multiple would produce.
    """
    narrow_gap_svg = render(LONG, 1096.0, max_number=2, max_chars=40, gap=24.0)
    wide_gap_svg = render(LONG, 1096.0, max_number=2, max_chars=40, gap=48.0)

    delta = second_column_offset(wide_gap_svg) - second_column_offset(narrow_gap_svg)
    assert delta == pytest.approx(24.0, abs=1.0)


class TestAuthoredMeasureFitsTheSlot:
    """An authored measure is an override of the default, not of the card.

    `max_chars` is authored YAML with no upper bound, so nothing stops an author
    asking for a measure wider than the card holding it. The containing SVG is a
    viewport: anything wider is painted over its neighbors or cut at the board
    edge, so the slot is the one bound the author cannot raise.
    """

    @pytest.mark.parametrize(
        ("width", "max_chars"), [(400.0, 120), (500.0, 200), (1128.0, 300)]
    )
    def test_an_oversized_max_chars_is_held_to_the_slot(
        self, width: float, max_chars: int
    ) -> None:
        svg = render(LONG, width, max_chars=max_chars)
        # unescape: the SVG carries &#x27; where one glyph is painted, and
        # measuring the entity instead of the character overstates the line.
        runs = [
            html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
            for t in re.findall(r"<text[^>]*>(.*?)</text>", svg, re.S)
        ]
        resolved = resolve_style(get_theme_style("clarity"))
        style = get_compact_style(resolved)
        face = markdown_font_faces(body_text_font_family(resolved), style).regular
        measurer = measurer_for_face(face)
        widest = max(
            measurer.measure(r, float(style.base_font_size)) for r in runs if r
        )
        assert widest <= width + 0.5, (
            f"max_chars={max_chars} in a {width:.0f}px slot painted {widest:.0f}px "
            f"-- prose spills onto neighboring cards"
        )


class TestAlignmentIsRelativeToTheCard:
    """`align` positions the text within its card, not within its measure.

    Capping the measure introduced a second box between the text and the card.
    Alignment belongs to the outer one: an author writing `align: center` is
    centering the block on the card they can see, and would have no way to
    reason about a measure the renderer chose for them.
    """

    def _anchor(self, width: float, align: str) -> float:
        resolved = resolve_style(get_theme_style("clarity"))
        text_style = resolved.text.model_copy(update={"align": align})
        svg, _ = render_prose_svg(SHORT, width, text_style, resolved)
        xs = [float(x) for x in re.findall(r'<text[^>]*\bx="([\d.]+)"', svg)]
        offsets = [
            float(m) for m in re.findall(r'<g transform="translate\(([\d.]+),', svg)
        ]
        return max(xs) + (max(offsets) if offsets else 0.0)

    @pytest.mark.parametrize("width", [600.0, 900.0, 1128.0])
    def test_centered_prose_centers_on_the_card(self, width: float) -> None:
        assert self._anchor(width, "center") == pytest.approx(width / 2, abs=2.0)

    @pytest.mark.parametrize("width", [600.0, 900.0, 1128.0])
    def test_right_aligned_prose_meets_the_card_edge(self, width: float) -> None:
        assert self._anchor(width, "right") == pytest.approx(width, abs=2.0)


class TestEveryWordSurvivesTheWeight:
    """The renderer must paint every word it was given, at any body weight.

    Columns are drawn by measuring a block, then placing a slice of what was
    measured. If the two halves wrap at different weights the slice is short
    and the tail of the paragraph is never emitted -- with no error, because
    each half is self-consistent. `style.text.font.weight` is authored YAML,
    so a light body weight is a documented way to reach it.
    """

    @pytest.mark.parametrize("weight", [100, 200, 300, 400, 700])
    def test_no_word_is_dropped(self, weight: int) -> None:
        resolved = resolve_style(get_theme_style("clarity"))
        text_style = resolved.text.model_copy(
            update={
                "font": resolved.text.font.model_copy(update={"weight": weight}),
                "column": resolved.text.column.model_copy(update={"max_chars": 50}),
            }
        )
        styled = dataclasses.replace(resolved, text=text_style)
        svg, _ = render_prose_svg(LONG, 1096.0, styled.text, styled)
        painted = " ".join(
            " ".join(
                html.unescape(re.sub(r"<[^>]+>", "", t))
                for t in re.findall(r"<text[^>]*>(.*?)</text>", svg, re.S)
            ).split()
        )
        assert painted.split() == LONG.split(), (
            f"body weight {weight} painted {len(painted.split())} of "
            f"{len(LONG.split())} words -- the tail was measured but never drawn"
        )
