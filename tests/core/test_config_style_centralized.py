"""Tests for all visual properties under get_theme_style() — cascade and behavior tests only."""

import pytest

from dbt_charts.core.compile.config import (
    get_config,
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.resolve.style.board import resolve_style


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


class TestStyleTitleSection:
    """Title cascade tests."""

    def test_title_font_cascades_from_root(self):
        """When title.font fields are None, cascade fills them from root font."""
        from dbt_charts.core.compile.models.primitives import FontStyle

        base = get_theme_style()
        new_font = base.font.model_copy(
            update={
                "family": "RootFont",
                "color": "#FF0000",
                "size": 14.0,
                "weight": "400",
            }
        )
        seed = base.model_copy(
            update={
                "font": new_font,
                "title": base.title.model_copy(
                    update={"font": FontStyle(family="TitleFont")}
                ),
            }
        )
        resolved = resolve_style(seed)
        # title.font.family was set; cascade must not overwrite it
        assert resolved.title.font.family.startswith("TitleFont")
        # title.font.color was None; cascade fills from root
        assert resolved.title.font.color == "#FF0000"

    def test_title_font_theme_color_survives_cascade(self):
        """Theme-set title.font.color is not overridden by cascade."""
        get_config()  # ensure settings initialised
        resolved = resolve_style(get_theme_style())
        # cascade must preserve whatever the theme set, not overwrite it
        assert resolved.title.font.color == get_theme_style().title.font.color


class TestStyleVariablesSection:
    """Variable controls — feature-behavior tests only."""

    def test_variables_visible_true_by_default(self):
        # was variables.hidden: false — positive-renamed to visible: true (D-022)
        assert get_theme_style().variables.visible is True


class TestPhase0bRegressions:
    """Regression tests for get_theme_style() migration bugs."""

    def test_spark_bar_respects_width_param(self):
        """render_spark_bar must use its width arg, not hardcode 100."""
        from dbt_charts.core.render.chart.spark import render_spark_bar

        eff = resolve_style(get_theme_style()).chart_defaults
        svg_narrow = render_spark_bar(50, width=50, normalize=True, resolved_style=eff)
        svg_wide = render_spark_bar(50, width=200, normalize=True, resolved_style=eff)
        assert 'width="50"' in svg_narrow
        assert 'width="200"' in svg_wide
