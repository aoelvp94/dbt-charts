"""Shared pytest fixtures for markdown-svg tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from mdsvg.fonts import FontMeasurer, get_system_font


@pytest.fixture
def measurer() -> FontMeasurer:
    """A FontMeasurer over the system's default font, or skip if unavailable."""
    font_path = get_system_font()
    if not font_path:
        pytest.skip("No system font available")
    measurer = FontMeasurer(font_path)
    if not measurer.is_available:
        pytest.skip("FontMeasurer not available")
    return measurer


def _resolve_fonts_dir(root: Path) -> Path:
    """dbt charts' vendored fonts under `root`, or the reason there are none.

    Two layouts are tried in order:
    - Monorepo: <root>/dbt-charts/src/dbt_charts/core/render/fonts
    - Standalone export: <root>/src/dbt_charts/core/render/fonts
      (copy.bara.sky moves dbt-charts/ to the export root, so there is no
      dbt-charts/ directory there)

    Missing fonts mean different things in the two layouts, so they get
    different outcomes: inside the monorepo the fonts are always present, so a
    miss is a stale path in this file and raises. Outside it, markdown-svg is
    being tested standalone and skips.
    """
    tail = ("dbt_charts", "core", "render", "fonts")
    for base in (root / "dbt-charts" / "src", root / "src"):
        path = base.joinpath(*tail)
        if path.is_dir():
            return path
    if (root / "dbt-charts").is_dir():
        raise AssertionError(
            f"vendored fonts missing under {root / 'dbt-charts' / 'src'}"
        )
    pytest.skip("dbt charts vendored fonts directory not available")


@pytest.fixture
def resolve_fonts_dir() -> Callable[[Path], Path]:
    """The resolver itself, so tests can pin it against a synthetic root."""
    return _resolve_fonts_dir


@pytest.fixture
def dbt_charts_fonts_dir() -> Path:
    """Path to dbt charts' vendored font files.

    markdown-svg has no fonts of its own but needs real ones to measure text
    (a FontMeasurer over an actual TTF, and a family with italic as well as
    regular). dbt charts' vendored fonts are convenient, real-world fixtures
    for that — used read-only, never modified.
    """
    return _resolve_fonts_dir(Path(__file__).resolve().parents[3])
