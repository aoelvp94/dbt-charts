"""Tests for render configuration values — structural tests only."""

import pytest

from dbt_charts.core.compile.config import (
    get_config,
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context


@pytest.fixture(autouse=True)
def reset_config_before_each():
    reset_config()
    yield
    reset_config()


class TestSparkConfig:
    """Test spark config — now under style.charts.table.spark."""

    def test_spark_default_color(self):
        # spark.color is cascade-filled from accent; resolve produces a non-None hex value
        ctx = resolve_chart_style_context(get_theme_style())
        assert ctx.table.spark.color is not None and ctx.table.spark.color.startswith(
            "#"
        )


class TestPerModuleDefaultsExtraction:
    """Per-module defaults load from colocated files, not default_config.yml."""

    def test_geo_sources_loaded_from_module_defaults(self):
        """geo_sources config loads from the render geo_defaults.yml."""
        config = get_config()
        assert "us-states" in config.geo_sources
        assert "world-countries" in config.geo_sources

    def test_extracted_sections_absent_from_default_config_yml(self):
        """Sections moved to per-module files must not re-appear in default_config.yml."""
        import yaml

        from .._paths import DBT_CHARTS_PKG_DIR

        raw = yaml.safe_load(
            (
                DBT_CHARTS_PKG_DIR / "core" / "defaults" / "default_config.yml"
            ).read_text()
        )
        assert "inspector" not in raw, (
            "inspector must live in core/inspect/defaults.yml"
        )
        assert "geo_sources" not in raw, (
            "geo_sources must live in core/render/geo_defaults.yml"
        )
        assert "markdown" not in raw, (
            "markdown config was deleted; must not re-appear in default_config.yml"
        )
        assert "terminal" not in raw, (
            "terminal must live in core/render/terminal_defaults.yml"
        )
