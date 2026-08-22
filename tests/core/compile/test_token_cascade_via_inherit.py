"""Regression tests: cascade sentinels filled via Inherit graph, not imperatively.

Each test:
  1. Builds a theme with a distinctive token value.
  2. Applies apply_inherit directly.
  3. Asserts the sentinel field received the token value.

Note: spark color fields (spark.color, spark.bar.color, spark_bar.bar.color) are seeded
from single_series_palette[0] in _seed_spark_colors(), not via Inherit.  Those are
covered by test_semantic_color_tokens.py.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.resolve.style.inherit_graph import get_inherit_graph
from dbt_charts.core.compile.resolve.style.inherit_resolver import apply_inherit


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


_ACCENT = "#aabbcc"


def _resolve_via_graph_only(accent: str = _ACCENT):
    """Apply inherit graph WITHOUT running _apply_token_cascade."""
    style = get_theme_style("stark").model_copy(update={"accent": accent})
    return apply_inherit(style, get_inherit_graph())


class TestAccentSentinelsViaInherit:
    def test_input_focus_color_filled_from_accent(self) -> None:
        resolved = _resolve_via_graph_only()
        assert resolved.variables.input.focus_color == _ACCENT


_FONT_COLOR = "#112233"


def _theme_with_cleared_rule_stroke(font_color: str):
    """Build theme with specific font.color and rule stroke.color cleared to None.

    stark.yaml sets rule stroke.color explicitly (= font.color).  Clear that
    explicit value so the Inherit marker is the only source of truth -- letting the
    test verify that apply_inherit fills stroke.color from Style.font.color rather
    than from the pre-set theme value.
    """
    base = get_theme_style("stark")
    new_font = base.font.model_copy(update={"color": font_color})
    marks = base.charts.marks
    new_rule = marks.rule.model_copy(
        update={"stroke": marks.rule.stroke.model_copy(update={"color": None})}
    )
    new_marks = marks.model_copy(update={"rule": new_rule})
    return base.model_copy(
        update={
            "font": new_font,
            "charts": base.charts.model_copy(update={"marks": new_marks}),
        }
    )


class TestStrokeSentinelsViaInherit:
    """rule stroke.color inherits from Style.font.color via FontColorStrokeStyle."""

    def test_rule_stroke_color_filled_from_font_color(self) -> None:
        style = _theme_with_cleared_rule_stroke(_FONT_COLOR)
        resolved = apply_inherit(style, get_inherit_graph())
        assert resolved.charts.marks.rule.stroke is not None
        assert resolved.charts.marks.rule.stroke.color == _FONT_COLOR


_DT_COLOR = "#778899"


def _theme_with_data_table_font_color(color: str):
    base = get_theme_style("stark")
    dt = base.charts.data_table
    new_dt = dt.model_copy(update={"font": dt.font.model_copy(update={"color": color})})
    return base.model_copy(
        update={"charts": base.charts.model_copy(update={"data_table": new_dt})}
    )


class TestDataTableInheritViaSlot:
    """Per-family data_table fields inherit from charts.data_table via InheritSlot."""

    def test_bar_data_table_font_color_filled_from_charts_data_table(self) -> None:
        style = _theme_with_data_table_font_color(_DT_COLOR)
        resolved = apply_inherit(style, get_inherit_graph())
        assert resolved.charts.bar.data_table is not None
        assert resolved.charts.bar.data_table.font is not None
        assert resolved.charts.bar.data_table.font.color == _DT_COLOR

    def test_line_data_table_font_color_filled_from_charts_data_table(self) -> None:
        style = _theme_with_data_table_font_color(_DT_COLOR)
        resolved = apply_inherit(style, get_inherit_graph())
        assert resolved.charts.line.data_table is not None
        assert resolved.charts.line.data_table.font is not None
        assert resolved.charts.line.data_table.font.color == _DT_COLOR
