"""Regression tests for vendored monospace font availability.

Before the fix, `get_mono_font_path()` delegated to `mdsvg.fonts.get_system_mono_font()`,
which returns `None` on slim Linux containers (no system monospace installed).
After the fix, it returns the vendored SourceCodePro-Regular.ttf path unconditionally.
"""

from __future__ import annotations

import pathlib

import pytest


def test_mono_font_path_returns_vendored_source_code_pro() -> None:
    """get_mono_font_path() must return a .ttf file that exists on disk."""

    from dbt_charts.core.fonts import get_mono_font_path

    path = get_mono_font_path()

    assert path.endswith(".ttf"), f"Expected a .ttf file, got: {path}"
    assert pathlib.Path(path).exists(), f"Vendored mono font not found on disk: {path}"


def test_svg_renderer_mono_measurement_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SVGRenderer with get_mono_font_path() must measure code-containing markdown without raising.

    Regression: on slim Linux containers where no system monospace font is installed,
    _ensure_mono_char_width() raised RuntimeError because get_system_mono_font() returned
    None and no vendored fallback was provided.

    The monkeypatch eliminates the system-font fallback so this test catches the regression
    on macOS dev machines (where a system mono font exists) as well as slim Linux CI.
    """
    from dbt_charts.core.fonts import get_mono_font_path
    from mdsvg.parser import parse
    from mdsvg.renderer import SVGRenderer

    # Simulate a slim Linux container: no system mono font available anywhere.
    # mdsvg.renderer.get_system_mono_font is the load-bearing patch — SVGRenderer
    # calls it when mono_font_path is None, so a reverted get_mono_font_path()
    # would hit the patched None and raise.  The mdsvg.fonts patch guards against
    # any future re-introduction of a system-font fallback in get_mono_font_path().
    monkeypatch.setattr("mdsvg.fonts.get_system_mono_font", lambda: None)
    monkeypatch.setattr("mdsvg.renderer.get_system_mono_font", lambda: None)

    renderer = SVGRenderer(mono_font_path=str(get_mono_font_path()))
    blocks = parse("Use `some_function()` inline code here.")
    size = renderer.measure(blocks, width=400)
    assert size.height > 0
