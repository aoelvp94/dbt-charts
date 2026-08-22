"""Tests that primary fonts still win for their own glyph ranges after Noto Emoji injection.

Guards:
1. dbt Sans Tabular stays at position 0 in its resolved family stack.
2. 'Noto Emoji' is appended *after* the primary — not inserted before it.
3. Source Serif 4 is primary in cream title stack.
4. The bundled Noto Emoji TTF does NOT claim disputed-codepoint ranges
   (Open Questions #2 and #6): arrow U+2192, text-presentation stars ★☆,
   check ✓. Because these codepoints are absent from the font's cmap,
   vl-convert falls through to the primary font for these glyphs even
   though vl-convert ignores CSS unicode-range directives.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.fonts import NOTO_EMOJI_FONT_FAMILY, get_face

_QUOTED = f"'{NOTO_EMOJI_FONT_FAMILY}'"

# Codepoints that must NOT be in the Noto Emoji cmap so the primary font wins
# for them on the vl-convert / SVG render path (OQ #2 and #6).
_DISPUTED_CODEPOINTS = {
    0x2192: "→ (U+2192 RIGHTWARDS ARROW)",
    0x2606: "☆ (U+2606 WHITE STAR)",
    0x2713: "✓ (U+2713 CHECK MARK)",
    0x2605: "★ (U+2605 BLACK STAR)",
}


class TestPrimaryFontPositionPreserved:
    def test_inter_is_first_in_default_root_stack(self) -> None:
        compiled = get_theme_style()
        resolved = resolve_style(compiled)
        family = resolved.font.family
        inter_pos = family.find("Inter")
        emoji_pos = family.find(NOTO_EMOJI_FONT_FAMILY)
        assert inter_pos >= 0, "Inter not in root font stack"
        assert emoji_pos > inter_pos, (
            f"Noto Emoji should appear after Inter: {family!r}"
        )

    def test_dbt_sans_tabular_is_first_in_kpi_stack(self) -> None:
        compiled = get_theme_style()
        ctx = resolve_chart_style_context(compiled)
        family = ctx.kpi.font.family
        assert family is not None
        assert family.startswith("'dbt Sans Tabular'"), (
            f"dbt Sans Tabular should be first: {family!r}"
        )
        assert _QUOTED in family

    def test_source_serif_4_is_first_in_editorial_cream_title(self) -> None:
        compiled = get_theme_style("cream")
        resolved = resolve_style(compiled)
        family = resolved.title.font.family
        assert family is not None
        assert family.startswith("'Source Serif 4'"), (
            f"Source Serif 4 should be first: {family!r}"
        )
        assert _QUOTED in family

    def test_noto_emoji_appended_not_prepended(self) -> None:
        """Noto Emoji must never be the first entry in any font stack."""
        compiled = get_theme_style()
        resolved = resolve_style(compiled)
        ctx = resolve_chart_style_context(compiled)
        for family in [
            resolved.font.family,
            resolved.title.font.family,
            ctx.font_family,
        ]:
            if family:
                assert not family.startswith(_QUOTED), (
                    f"Noto Emoji should not be first in stack: {family!r}"
                )


class TestDisputedCodepointsAbsentFromNotoEmojiCmap:
    """Closes Open Questions #2 and #6.

    vl-convert ignores CSS unicode-range directives and falls through the
    font-family stack by glyph availability alone. These tests confirm that
    the bundled Noto Emoji TTF does not claim the codepoints most likely to
    be disputed between the primary font and Noto Emoji, so the primary font
    always wins for them on the SVG/PNG export path.
    """

    def test_disputed_codepoints_absent_from_noto_emoji_cmap(self) -> None:
        from fontTools.ttLib import TTFont  # pyright: ignore[reportMissingTypeStubs]

        cmap = TTFont(get_face(NOTO_EMOJI_FONT_FAMILY).measure_path).getBestCmap()
        assert cmap is not None
        for cp, label in _DISPUTED_CODEPOINTS.items():
            assert cp not in cmap, (
                f"{label} is in the Noto Emoji cmap — "
                "the primary font may not win for this codepoint on the vl-convert path. "
                "Update the font subset or add a pixel-level fallback test."
            )
