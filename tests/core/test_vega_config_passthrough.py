"""Tests for open-ended Vega-Lite config support."""

from __future__ import annotations

from collections.abc import Callable

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.config import (
    get_theme_style,
    load_config,
    reset_config,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())


class TestVegaConfigPassThrough:
    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_custom_default_vega_config_passes_through(
        self, tmp_path, make_chart, local_project: Callable[..., FilesystemProject]
    ) -> None:
        # axis* removed from VegaLiteConfig — project config vega.config no longer
        # accepts axis/axisX/axisY/axisBand/axisQuantitative. Use a still-valid key.
        config_path = tmp_path / "dbt_charts.yml"
        config_path.write_text(
            """
vega:
  config:
    numberFormat: ".4f"
    timeFormat: "%Y-%m"
""".strip()
        )
        load_config(local_project(tmp_path))

        chart = make_chart("bar", x="month", y="revenue")
        data = [
            {"month": "Jan", "revenue": 100},
            {"month": "Feb", "revenue": 120},
        ]

        _rc = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        spec = generate_vega_lite_spec(chart, data)

        assert spec["config"]["numberFormat"] == ".4f"
        assert spec["config"]["timeFormat"] == "%Y-%m"

    def test_default_theme_applies_when_requested(self, make_chart) -> None:
        """Theme values flow into the y-axis gridColor in the encoded spec."""
        chart = make_chart("bar", x="month", y="revenue")
        data = [
            {"month": "Jan", "revenue": 100},
            {"month": "Feb", "revenue": 120},
        ]

        _rc = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        spec = generate_vega_lite_spec(chart, data)

        # Theme styling threads through to axis encoding — not present on unstyled spec.
        assert spec.get("encoding", {}).get("y", {}).get("axis", {}).get("gridColor")

    # test_custom_preset_vega_config_passes_through — removed: style_preset eliminated
