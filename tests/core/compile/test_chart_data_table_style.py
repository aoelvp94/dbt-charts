"""Tests for the chart.data_table style cascade.

Spec §4 three-tier cascade, ADR-002 + ADR-006:
  Tier 1: style.charts.data_table.*
  Tier 2: style.charts.<chart_type>.data_table.*
  Tier 3: chart.style.data_table.*

These tests validate STRUCTURE, PRESENCE, and BEHAVIOR-UNDER-OVERRIDE —
they do NOT pin theme scalars (per CLAUDE.md "What NOT to Test").
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.primitives import FontStyle, RuleStyle
from dbt_charts.core.compile.models.style.authored import (
    ChartStylePatch,
)
from dbt_charts.core.compile.models.style.theme import (
    DataTableLabelStyle,
    DataTableRowStyle,
    DataTableStyle,
)
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context


def _theme_with_data_table(**overrides):
    """Build a Style with a tier-1 data_table override on charts."""
    base = get_theme_style()
    return base.model_copy(
        update={
            "charts": base.charts.model_copy(
                update={
                    "data_table": base.charts.data_table.model_copy(update=overrides)
                }
            )
        }
    )


# =============================================================================
# STRUCTURE — data_table nested under charts
# =============================================================================


def test_resolved_charts_style_has_data_table_field():
    resolved = resolve_chart_style_context(get_theme_style())
    assert hasattr(resolved, "data_table")
    assert isinstance(resolved.data_table, DataTableStyle)


def test_compiled_data_table_style_has_all_spec_leaves():
    # Spec §4.3 leaves (structure only — no value pinning).

    s = get_theme_style().charts.data_table
    assert hasattr(s, "font")
    assert isinstance(s.font, FontStyle)
    assert hasattr(s, "divider")
    assert isinstance(s.divider, RuleStyle)
    assert hasattr(s, "row")
    assert isinstance(s.row, DataTableRowStyle)
    assert hasattr(s, "label")
    assert isinstance(s.label, DataTableLabelStyle)
    assert hasattr(s, "padding_top")
    assert hasattr(s, "padding_bottom")


def test_compiled_data_table_style_forbids_header_key():
    # ADR-006 + Q2: the old `header:` block is renamed to `divider:`.
    # Supplying `header:` must raise (extra="forbid").
    with pytest.raises(ValidationError):
        DataTableStyle.model_validate({"header": {"font": {"size": 12}}})


# =============================================================================
# BEHAVIOR UNDER OVERRIDE — cascade merge semantics
# =============================================================================


def test_data_table_tier1_universal_override():
    # Tier 1: theme sets style.charts.data_table.font.size = 99.5;
    # confirm it propagates to the resolved model.
    theme = _theme_with_data_table(font=FontStyle(size=99.5))
    resolved = resolve_chart_style_context(theme)
    assert resolved.data_table.font.size == 99.5


def test_data_table_tier1_override_does_not_cross_into_bar_font():
    # Scope rule (spec §4.4): data_table style does NOT cascade into sibling
    # chart-type styles. Setting data_table.font.size must not touch bar mark.
    theme = _theme_with_data_table(font=FontStyle(size=77.0))
    resolved = resolve_chart_style_context(theme)
    baseline = resolve_chart_style_context(get_theme_style())
    assert resolved.marks.bar.border.width == baseline.marks.bar.border.width


def test_data_table_divider_width_override():
    theme = _theme_with_data_table(divider=RuleStyle(width=3.0, continuous=True))
    resolved = resolve_chart_style_context(theme)
    assert resolved.data_table.divider.width == 3.0


def test_data_table_padding_top_override():
    theme = _theme_with_data_table(padding_top=42.0)
    resolved = resolve_chart_style_context(theme)
    assert resolved.data_table.padding_top == 42.0


# =============================================================================
# TIER-2 CASCADE — per-chart-type override merges over universal (HIGH 4)
# =============================================================================


def test_data_table_tier2_bar_override_merges_over_tier1():
    # HIGH 4: end-to-end three-tier cascade. Set distinct values at tier 1
    # (universal charts.data_table) AND tier 2 (charts.bar.data_table).
    # resolve_effective_data_table_style(charts, "bar") must return a
    # style where tier-2 leaves win and tier-1 leaves fill in the rest.
    from dbt_charts.core.compile.data_table import (
        resolve_effective_data_table_style,
    )
    from dbt_charts.core.compile.models.style.authored import DataTableStylePatch

    # Tier 1: universal sets font.size + padding_top.
    tier1 = get_theme_style().charts.data_table.model_copy(
        update={"font": FontStyle(size=11.0, color="#aaa"), "padding_top": 7.0}
    )
    # Tier 2: bar-specific override bumps font.size AND divider.width, but
    # leaves padding_top alone — expect padding_top to inherit from tier 1.
    tier2 = DataTableStylePatch.model_validate(
        {
            "font": {"size": 23.0},
            "divider": {"width": 4.0},
        }
    )
    base = get_theme_style()
    seed = base.model_copy(
        update={
            "charts": base.charts.model_copy(
                update={
                    "data_table": tier1,
                    "bar": base.charts.bar.model_copy(update={"data_table": tier2}),
                }
            )
        }
    )
    resolved = resolve_chart_style_context(seed)
    effective = resolve_effective_data_table_style(resolved, "bar")
    # Tier 2 wins where set.
    assert effective.font.size == 23.0
    assert effective.divider.width == 4.0
    # Tier 1 inherits where tier 2 is silent.
    assert effective.padding_top == 7.0
    # Tier 1's font.color survives because tier 2 didn't overwrite font.color.
    assert effective.font.color == "#aaa"


def test_data_table_tier2_unset_falls_through_to_tier1():
    # When a chart type has no data_table override (None), the effective
    # style IS tier 1 — no merging.
    from dbt_charts.core.compile.data_table import (
        resolve_effective_data_table_style,
    )

    theme = _theme_with_data_table(font=FontStyle(size=15.0))
    resolved = resolve_chart_style_context(theme)
    effective = resolve_effective_data_table_style(resolved, "bar")
    assert effective.font.size == 15.0


# =============================================================================
# CHART-LOCAL PATCH — `chart.style.data_table`
# =============================================================================


def test_chart_style_patch_accepts_data_table():
    # Tier 3 — authors set chart.style.bar.data_table.* for one-off overrides on cartesian charts.
    patch = ChartStylePatch.model_validate(
        {"bar": {"data_table": {"font": {"weight": 600, "size": 14.0}}}}
    )
    assert patch.bar is not None
    assert patch.bar.data_table is not None
    assert patch.bar.data_table.font is not None
    assert patch.bar.data_table.font.weight == 600
    assert patch.bar.data_table.font.size == 14.0


def test_chart_style_patch_data_table_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        ChartStylePatch.model_validate({"bar": {"data_table": {"foo": "bar"}}})


# =============================================================================
# POSITION FIELD — top / bottom placement knob
# =============================================================================


def test_compiled_data_table_style_has_position_field():
    # New required field: position accepts "top" or "bottom".
    s = get_theme_style().charts.data_table
    assert hasattr(s, "position")
    assert s.position in ("top", "bottom")


def test_data_table_style_rejects_invalid_position():
    # Only "top" and "bottom" are valid; any other string must fail.
    base = get_theme_style().charts.data_table.model_dump()
    base["position"] = "center"
    with pytest.raises(ValidationError):
        DataTableStyle.model_validate(base)


def test_data_table_position_override_via_tier1():
    # Authors can override position at the theme level (tier 1).
    theme = _theme_with_data_table(position="bottom")
    resolved = resolve_chart_style_context(theme)
    assert resolved.data_table.position == "bottom"


def test_chart_style_patch_accepts_position():
    # Tier 3: chart.style.bar.data_table.position overrides theme on cartesian charts.
    patch = ChartStylePatch.model_validate(
        {"bar": {"data_table": {"position": "bottom"}}}
    )
    assert patch.bar is not None
    assert patch.bar.data_table is not None
    assert patch.bar.data_table.position == "bottom"
