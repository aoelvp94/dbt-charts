"""Tests for runtime config defaults after config consolidation."""

from __future__ import annotations

from dbt_charts.core.compile.config import (
    get_config,
    get_default_theme_name,
    get_palette,
    reset_config,
)
from dbt_charts.core.compile.vega_lite import VEGA_LITE_SCHEMA_URL

from .chart_default_expectations import (
    shipped_default_theme_name,
    shipped_palette,
)


class TestChartConfigStack:
    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_runtime_config_defaults_are_available(self) -> None:
        config = get_config()

        assert config.vega.schema == VEGA_LITE_SCHEMA_URL
        # vega.default_theme was removed from config; theme name lives in the
        # config module constant _default_theme_name, via get_default_theme_name().
        assert get_default_theme_name() == shipped_default_theme_name()
        # The helper-backed comparisons below verify the runtime loader mirrors
        # the shipped defaults document without repeating every palette inline.
        assert config.palettes.tableau[0] == shipped_palette("tableau")[0]
        assert get_palette("vivid-10") == shipped_palette("vivid-10")
        assert get_palette("hero-6")[0] == shipped_palette("hero-6")[0]

    def test_get_palette_default_reads_theme_categorical_palette(self) -> None:
        from dbt_charts.core.compile.config import get_theme_style

        _cat = get_theme_style().charts.color.categorical
        assert _cat is not None and _cat.palette is not None
        assert get_palette("default") == list(_cat.palette)
        assert get_palette() == get_palette("default")
