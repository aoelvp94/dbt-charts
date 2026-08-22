"""Tests for the bundled emoji font file.

Guards that the bundled Noto Emoji (monochrome) font file exists, has the
correct table structure, and reports the expected family name.
"""

from __future__ import annotations

from dbt_charts.core.fonts import (
    NOTO_EMOJI_FONT_FAMILY,
    get_face,
    get_fonts_dir,
)


class TestNotoEmojiBundle:
    def test_ttf_exists(self) -> None:
        assert get_face(NOTO_EMOJI_FONT_FAMILY).measure_path.exists()

    def test_woff2_exists(self) -> None:
        woff2 = get_fonts_dir() / "NotoEmoji-Regular.woff2"
        assert woff2.exists()

    def test_license_exists(self) -> None:
        lic = get_fonts_dir() / "NOTO_EMOJI_LICENSE.txt"
        assert lic.exists()

    def test_font_is_monochrome(self) -> None:
        from fontTools.ttLib import TTFont

        font = TTFont(get_face(NOTO_EMOJI_FONT_FAMILY).measure_path)
        tables = set(font.reader.tables.keys())
        assert "COLR" not in tables, "Color COLR table found — wrong font variant"
        assert "CPAL" not in tables, "Color CPAL table found — wrong font variant"

    def test_font_family_name(self) -> None:
        from fontTools.ttLib import TTFont

        font = TTFont(get_face(NOTO_EMOJI_FONT_FAMILY).measure_path)
        family_names = {r.toUnicode() for r in font["name"].names if r.nameID == 1}
        assert "Noto Emoji" in family_names
