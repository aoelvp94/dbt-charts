"""Helpers for reading canonical shipped chart defaults in tests."""

from functools import cache

import yaml

from dbt_charts.core.compile.config import (
    SHIPPED_DEFAULT_THEME_NAME,
    _default_config_path,
    _palettes_dir,
)


@cache
def _shipped_default_config() -> dict:
    """Return the canonical built-in default config document."""
    with _default_config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@cache
def _shipped_migrated_palettes() -> dict[str, list[str]]:
    """Return categorical palettes shipped under defaults/palettes/categorical/."""
    palettes: dict[str, list[str]] = {}
    cat_dir = _palettes_dir / "categorical"
    if cat_dir.is_dir():
        for path in sorted(cat_dir.glob("*.yml")):
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            name = data.get("name")
            colors = data.get("colors")
            if isinstance(name, str) and isinstance(colors, list):
                palettes[name] = list(colors)
    return palettes


def shipped_palette(name: str) -> list[str]:
    """Return a built-in palette by name from defaults/palettes/categorical/."""
    palettes = _shipped_migrated_palettes()
    if name in palettes:
        return list(palettes[name])
    raise KeyError(f"no shipped palette named {name!r}")


def shipped_default_theme_name() -> str:
    """Return the built-in default theme name.

    The default theme is a module constant in config.py (not a default_config.yml
    field). This helper returns that constant so tests stay in sync with what
    the runtime reports.
    """
    return SHIPPED_DEFAULT_THEME_NAME
