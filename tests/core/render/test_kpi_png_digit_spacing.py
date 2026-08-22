"""Integration test: KPI PNG digit spacing with Source Serif 4 font stack.

Verifies that a KPI rendered with the editorial theme's font stack
(''Source Serif 4', Georgia, ...) produces a PNG where the digit cluster
width is proportional-serif narrow, NOT Noto Emoji emoji-grid wide.

Root cause guard: normalize_svg_font_families_for_vl_convert must NOT
rename 'Source Serif 4' to 'Source Serif 4 Variable'.  When the rename
was active, vl-convert failed to bind the renamed family, fell through
to Noto Emoji in the stack, and rendered digits with ~1.27em monospaced
advances instead of ~0.5em proportional-serif advances.
"""

from __future__ import annotations

import io
from typing import cast

import pytest


def test_kpi_editorial_font_digits_are_proportional_width_not_emoji_grid() -> None:
    """'40' rendered via Source Serif 4 must be narrower than 1.5 * font_size.

    Noto Emoji renders each ASCII digit at ~1.27em monospaced advance width,
    so '40' (two digits) occupies ~2.54 * font_size.  Source Serif 4 renders
    digits at ~0.5em, so '40' occupies ~1em.  The threshold 1.5 * font_size
    admits proportional-serif while rejecting emoji-grid.
    """
    pytest.importorskip("vl_convert")
    Image = pytest.importorskip("PIL.Image")

    from dbt_charts.core.render.converters.png import to_png

    font_size = 40.0
    # editorial.yaml sets:  "'Source Serif 4', Georgia, 'Times New Roman', serif"
    # merged.py prepends Noto Emoji for emoji coverage — the full stack is:
    font_family = "'Source Serif 4', 'Noto Emoji', Georgia, 'Times New Roman', serif"
    width = int(font_size * 4)
    # Height is 4× font_size (not 2×) so glyphs with tall ascenders or deep
    # descenders are never clipped — a clipped image could produce a spuriously
    # narrow ink span that silently passes even under the broken normalizer.
    height = int(font_size * 4)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="white"/>'
        f'<text x="0" y="{int(font_size * 1.5)}" '
        f'font-family="{font_family}" '
        f'font-size="{font_size}" '
        f'fill="black">40</text>'
        f"</svg>"
    )
    png_bytes = to_png(svg, scale=2.0)

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    width_px, height_px = image.size

    # Find every column and row that contains ink (non-white pixels).
    # Scale=2.0 → pixel coords are 2× the SVG units.
    ink_cols: list[int] = []
    ink_rows: list[int] = []
    for col in range(width_px):
        for row in range(height_px):
            r, g, b = cast(tuple[int, int, int], image.getpixel((col, row)))
            if r < 200 and g < 200 and b < 200:  # darker than antialiasing = ink
                ink_cols.append(col)
                break
    for row in range(height_px):
        for col in range(width_px):
            r, g, b = cast(tuple[int, int, int], image.getpixel((col, row)))
            if r < 200 and g < 200 and b < 200:
                ink_rows.append(row)
                break

    assert ink_cols, "No ink found in rendered PNG — SVG rendering produced blank image"
    # Guard: enough vertical ink to distinguish real glyph rendering from a stray pixel.
    assert max(ink_rows) - min(ink_rows) >= font_size * 0.4 * 2, (
        "Vertical ink span too small — glyphs may have been clipped or not rendered"
    )

    digit_span_px = max(ink_cols) - min(ink_cols) + 1
    # scale=2 → 1 SVG unit = 2 pixels
    digit_span_svg_units = digit_span_px / 2.0
    threshold = 1.5 * font_size  # generous: admits serif, rejects emoji-grid

    assert digit_span_svg_units < threshold, (
        f"Digit cluster width {digit_span_svg_units:.1f} svg-units "
        f"exceeds threshold {threshold:.1f} svg-units (font_size={font_size}). "
        f"This indicates vl-convert fell through to Noto Emoji instead of "
        f"Source Serif 4 — check that normalize_svg_font_families_for_vl_convert "
        f"is NOT renaming 'Source Serif 4' to 'Source Serif 4 Variable'."
    )
