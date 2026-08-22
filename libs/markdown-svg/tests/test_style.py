"""Tests for Style theme presets."""

from __future__ import annotations

from pygments.styles import get_style_by_name

import mdsvg.style as mdsvg_style
from mdsvg.style import Style


def _theme_constants() -> dict[str, Style]:
    """Every module-level `*_THEME` color preset (`LIGHT_THEME`, `DARK_THEME`, ...).

    Discovered by name pattern rather than hand-listed so a future theme
    constant is covered automatically instead of silently skipped.
    """
    return {
        name: value
        for name, value in vars(mdsvg_style).items()
        if name.endswith("_THEME") and isinstance(value, Style)
    }


def _luminance(hex_color: str) -> float:
    """Perceived brightness (Rec. 601 luma) of a ``#rrggbb`` color, 0 (black) to 1 (white).

    Not WCAG relative luminance (that linearizes sRGB with different
    coefficients) — this is a cheap light/dark-direction signal only,
    which is all a binary "does this pairing point the same way" check needs.
    """
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _is_light(hex_color: str) -> bool:
    return _luminance(hex_color) >= 0.5


class TestThemeCodeContrast:
    """A theme's Pygments token palette must point in the same direction as its code box.

    A `code_theme` designed for a dark background (e.g. `github-dark`, whose
    tokens are tuned to read against `#0d1117`) renders unreadably-pale text
    when paired with a light `code_background`, and vice versa. This walks
    every built-in preset and checks the two backgrounds — the author's
    `code_background` and the chosen Pygments style's own
    `background_color` — agree on light vs. dark.
    """

    def test_preset_code_theme_matches_code_background_luminance(self) -> None:
        presets = _theme_constants()
        assert len(presets) >= 3, (
            f"expected at least 3 *_THEME constants, found {presets!r}"
        )
        for name, style in presets.items():
            pygments_style = get_style_by_name(style.code_theme)
            box_is_light = _is_light(style.code_background)
            tokens_is_light = _is_light(pygments_style.background_color)
            assert box_is_light == tokens_is_light, (
                f"{name}: code_background {style.code_background!r} is "
                f"{'light' if box_is_light else 'dark'} but code_theme "
                f"{style.code_theme!r} is a "
                f"{'light' if tokens_is_light else 'dark'}-background Pygments "
                f"style ({pygments_style.background_color!r}) — its tokens are "
                "tuned for the opposite background and will be unreadable."
            )
