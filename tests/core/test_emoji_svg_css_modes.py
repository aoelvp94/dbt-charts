"""Tests for SVG-embedded CSS per emoji mode.

The emoji board is the one row an emoji mode withdraws, and it is withdrawn where
the board set is chosen (``board_font_face_css``) rather than where the stylesheet
is assembled:

monochrome     → emoji @font-face declared + font-variant-emoji: text
system-default → no emoji @font-face (the reader's own emoji font paints)
disabled       → no emoji @font-face

The text boards are unconditional in all three. They used to ride on the same gate,
so a board with ``emoji: disabled`` declared no ``@font-face`` at all and was
rescued by the HTML page's own copy — which an exported SVG opened on its own never
had.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.render.font_selection import board_font_face_css
from dbt_charts.core.render.svg_utils import generate_svg_styles

_FONT_FACE_MARKER = "@font-face"
_NOTO_EMOJI_WOFF2 = "NotoEmoji-Regular.woff2"
_INTER_WOFF2 = "InterVariable.woff2"
_VARIANT_EMOJI_RULE = "font-variant-emoji: text"


def _url_css(emoji_mode: str) -> str:
    return board_font_face_css("", emoji_mode, frozenset(), embed=False)


class TestMonochromeMode:
    def test_declares_the_emoji_board(self) -> None:
        assert _NOTO_EMOJI_WOFF2 in _url_css("monochrome")

    def test_includes_font_variant_emoji_rule(self) -> None:
        styles = generate_svg_styles(emoji_mode="monochrome", font_face_css="")
        assert _VARIANT_EMOJI_RULE in styles


class TestSystemDefaultMode:
    def test_drops_the_emoji_board(self) -> None:
        assert _NOTO_EMOJI_WOFF2 not in _url_css("system-default")

    def test_drops_font_variant_emoji_rule(self) -> None:
        # No font-variant-emoji: text so disputed codepoints can color-promote
        styles = generate_svg_styles(emoji_mode="system-default", font_face_css="")
        assert _VARIANT_EMOJI_RULE not in styles


class TestDisabledMode:
    def test_drops_the_emoji_board(self) -> None:
        assert _NOTO_EMOJI_WOFF2 not in _url_css("disabled")

    def test_drops_font_variant_emoji_rule(self) -> None:
        styles = generate_svg_styles(emoji_mode="disabled", font_face_css="")
        assert _VARIANT_EMOJI_RULE not in styles


class TestEmbedModeCarvesEmojiOutToo:
    """Embed mode gets the carve-out for free — but "for free" is still a claim.

    The emoji family only enters a font stack under `monochrome`, so a family scan
    of the markup drops it in the other two modes with no rule of its own. Pinned in
    both directions because nothing else exercises `embed=True` here.
    """

    _STACK = "'Inter Variable', 'Noto Emoji', system-ui, sans-serif"

    def test_monochrome_embeds_the_emoji_board(self) -> None:
        css = board_font_face_css(
            f'<text font-family="{self._STACK}">x</text>',
            "monochrome",
            frozenset(),
            embed=True,
        )
        assert "Noto Emoji" in css

    def test_system_default_stack_names_no_emoji_family(self) -> None:
        css = board_font_face_css(
            "<text font-family=\"'Inter Variable', system-ui, sans-serif\">x</text>",
            "system-default",
            frozenset(),
            embed=True,
        )
        assert "Noto Emoji" not in css
        assert "Inter Variable" in css


class TestTextBoardsAreUnconditional:
    """A board that turns emoji off still needs the type it is set in."""

    def test_every_mode_declares_the_text_boards(self) -> None:
        for mode in ("monochrome", "system-default", "disabled"):
            css = _url_css(mode)
            assert _FONT_FACE_MARKER in css, mode
            assert _INTER_WOFF2 in css, mode


class TestStylesheetCarriesWhatItIsGiven:
    """Over all three modes, because the mode-independence *is* the fix.

    The old template wrapped the whole block in `emoji_mode != "disabled"`, which is
    what hid the text boards too. Pinning only `monochrome` would let that gate be
    reintroduced with every test still green.
    """

    @pytest.mark.parametrize("emoji_mode", ["monochrome", "system-default", "disabled"])
    def test_font_face_css_is_embedded_verbatim(self, emoji_mode: str) -> None:
        styles = generate_svg_styles(
            emoji_mode=emoji_mode, font_face_css="@font-face { font-family: 'X'; }"
        )
        assert "@font-face { font-family: 'X'; }" in styles
