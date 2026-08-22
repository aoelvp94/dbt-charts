"""Shared pytest fixtures for markdown-svg tests."""

from __future__ import annotations

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


@pytest.fixture
def dbt_charts_fonts_dir() -> Path:
    """Path to dbt charts' vendored font files.

    A handful of tests need real variable/italic font files (to instance a
    variable font at a weight, or to prove italic measures narrower than
    regular). dbt charts' vendored fonts are convenient, real-world fixtures
    for that — used read-only, never modified. markdown-svg must remain
    standalone-testable, so any test depending on this fixture skips
    gracefully when the directory isn't present rather than importing
    dbt charts or hard-failing.

    Two path layouts are tried in order:
    - Monorepo: <repo-root>/dbt-charts/src/dbt_charts/core/render/fonts
      (parents[3] = the monorepo root, dbt-charts/ is a named subdir)
    - Standalone export: <repo-root>/src/dbt_charts/core/render/fonts
      (parents[3] = the export repo root, no dbt-charts/ prefix)
    """
    shared_parent = Path(__file__).resolve().parents[3]
    path = (
        shared_parent / "dataface" / "src" / "dbt_charts" / "core" / "render" / "fonts"
    )
    if not path.is_dir():
        path = shared_parent / "src" / "dbt_charts" / "core" / "render" / "fonts"
    if not path.is_dir():
        pytest.skip("dbt charts vendored fonts directory not available")
    return path
