"""Tests for the neutral CSS/SVG color-validation primitives.

sanitize_color and is_sanitizable_color validate foreign SVG/CSS strings, not
compile policy, so they live in dbt_charts.core.colors (a neutral leaf) rather
than under compile/.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.colors import (
    InvalidColorError,
    is_sanitizable_color,
    sanitize_color,
)


def test_sanitize_color_invalid_raises():
    with pytest.raises(InvalidColorError, match="Invalid color value: 'not-a-color'"):
        sanitize_color("not-a-color")


def test_sanitize_color_none_returns_none():
    assert sanitize_color(None) is None


def test_sanitize_color_valid_hex_passes():
    assert sanitize_color("#fff") == "#fff"
    assert sanitize_color("#FFFFFF") == "#FFFFFF"


def test_sanitize_color_transparent_passes():
    assert sanitize_color("transparent") == "transparent"
    assert sanitize_color("none") == "transparent"


def test_sanitize_color_with_explicit_fallback_for_none():
    """When caller supplies an explicit fallback, None input returns it."""
    assert sanitize_color(None, "#ff0000") == "#ff0000"


def test_is_sanitizable_color_accepts_hex_and_keywords():
    assert is_sanitizable_color("#fff") is True
    assert is_sanitizable_color("#FFFFFF") is True
    assert is_sanitizable_color("transparent") is True
    assert is_sanitizable_color("none") is True


def test_is_sanitizable_color_rejects_invalid():
    assert is_sanitizable_color("not-a-color") is False
