"""TDD tests for flat-prefix → nested-block renames.

Each rename has two tests:
  - new nested form parses correctly
  - old flat form raises ValidationError (extra="forbid")
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.style.authored import (
    BaseScaleStylePatch,
    TableColumnDefaultsConfig,
)
from dbt_charts.core.compile.models.style.theme import (
    BaseScaleStyle,
    DetailsArrowFontStyle,
    DetailsArrowStyle,
    DetailsStyle,
    MeasureGridStyle,
    TableChartStyle,
    TableRowStripeStyle,
    TableRowStyle,
    TableRuleStyle,
)

# ── BaseAxisGridStyle: zero_color / zero_width → zero: {color, width} ──


def test_axis_grid_zero_nested_parses() -> None:
    """New nested zero block is accepted by MeasureGridStyle (y-axis grid)."""
    grid = MeasureGridStyle.model_validate({"zero": {"color": "#ff0000", "width": 2.0}})
    assert grid.zero is not None
    assert grid.zero.color == "#ff0000"
    assert grid.zero.width == 2.0


def test_axis_grid_zero_color_flat_rejected() -> None:
    """Old flat zero_color field is rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        MeasureGridStyle.model_validate({"zero_color": "#ff0000"})


def test_axis_grid_zero_width_flat_rejected() -> None:
    """Old flat zero_width field is rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        MeasureGridStyle.model_validate({"zero_width": 2.0})


# ── TableChartStyle: rule_color → rule: TableRuleStyle {color} ────────────────────


def test_table_rule_style_parses() -> None:
    """New TableRuleStyle sub-model parses correctly."""
    rule = TableRuleStyle.model_validate({"color": "#00bb00"})
    assert rule.color == "#00bb00"


def test_table_rule_color_flat_rejected() -> None:
    """Old flat rule_color field is rejected by TableChartStyle (extra='forbid')."""
    with pytest.raises(ValidationError):
        TableChartStyle.model_validate({"rule_color": "#00bb00"})


# ── DetailsStyle: arrow_x / arrow_font_size → arrow: {x, font: {size}} ───────


def test_details_arrow_style_parses() -> None:
    """New DetailsArrowStyle sub-model parses correctly."""
    arrow = DetailsArrowStyle.model_validate({"x": 14.0, "font": {"size": 13.0}})
    assert arrow.x == 14.0
    assert arrow.font.size == 13.0


def test_details_arrow_font_style_parses() -> None:
    """New DetailsArrowFontStyle sub-model parses correctly."""
    font = DetailsArrowFontStyle.model_validate({"size": 13.0})
    assert font.size == 13.0


def test_details_arrow_x_flat_rejected() -> None:
    """Old flat arrow_x field is rejected by DetailsStyle (extra='forbid')."""
    with pytest.raises(ValidationError):
        DetailsStyle.model_validate({"arrow_x": 14.0})


def test_details_arrow_font_size_flat_rejected() -> None:
    """Old flat arrow_font_size field is rejected by DetailsStyle (extra='forbid')."""
    with pytest.raises(ValidationError):
        DetailsStyle.model_validate({"arrow_font_size": 13.0})


# ── TableRowStyle: stripe_color → stripe: TableRowStripeStyle {color} ─────────


def test_table_row_stripe_style_parses() -> None:
    """New TableRowStripeStyle sub-model parses correctly."""
    stripe = TableRowStripeStyle.model_validate({"color": "#f0f0f0"})
    assert stripe.color == "#f0f0f0"


def test_table_row_stripe_color_flat_rejected() -> None:
    """Old flat stripe_color field is rejected by TableRowStyle (extra='forbid')."""
    with pytest.raises(ValidationError):
        TableRowStyle.model_validate({"stripe_color": "#f0f0f0"})


# ── BaseScaleStyle: max_band_size / min_band_size → mark_size: {min_size, max_size} ─


def test_scale_mark_size_group_rejected() -> None:
    """mark_size scale config was deleted (2026-08 trim) — BaseScaleStyle
    rejects the group entirely, not just its flat predecessor fields."""
    with pytest.raises(ValidationError):
        BaseScaleStyle.model_validate(
            {"mark_size": {"min_size": 5.0, "max_size": 40.0}}
        )


def test_scale_max_band_size_flat_rejected() -> None:
    """Old flat max_band_size field is rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        BaseScaleStyle.model_validate({"max_band_size": 40.0})


def test_scale_min_band_size_flat_rejected() -> None:
    """Old flat min_band_size field is rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        BaseScaleStyle.model_validate({"min_band_size": 5.0})


def test_scale_patch_mark_size_group_rejected() -> None:
    """mark_size scale config was deleted (2026-08 trim) — BaseScaleStylePatch
    rejects the group entirely too."""
    with pytest.raises(ValidationError):
        BaseScaleStylePatch.model_validate({"mark_size": {"min_size": 5.0}})


# ── TableColumnDefaultsConfig: label still supported ─────────────────────────


def test_table_column_defaults_label_accepted() -> None:
    """label field is still supported on TableColumnDefaultsConfig."""
    cfg = TableColumnDefaultsConfig.model_validate({"label": "My Column"})
    assert cfg.label == "My Column"
