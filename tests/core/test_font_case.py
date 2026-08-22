"""Tests for font.case pipeline: slug_to_text, apply_font_case, format_display_text.

Written before implementation (TDD). These tests drive:
- slug_to_text: tokenization + unit/abbreviation expansion, NO casing
- apply_font_case: delegates to apply_case via ResolvedFontStyle.case
- format_display_text: two-step pipeline (slug_to_text → apply_font_case)
- Cascade: child font.case overrides root none
- Enum: 'none' is the preserve/no-op value (not 'preserve')
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.models.primitives import FontStyle, ResolvedFontStyle
from dbt_charts.core.utils import slug_to_text

# ---------------------------------------------------------------------------
# slug_to_text: tokenization and suffix/abbreviation expansion only — no casing
# ---------------------------------------------------------------------------


def test_slug_to_text_no_capitalize_applied() -> None:
    """slug_to_text must emit lowercase words (no .capitalize() or title logic)."""
    # Plain snake_case slug with no special tokens
    assert slug_to_text("revenue_by_month") == "revenue by month"


def test_slug_to_text_unit_suffix_preserved() -> None:
    """Unit suffix is expanded but NOT title-cased."""
    # revenue_usd → revenue ($) — lower case 'revenue', suffix expanded
    assert slug_to_text("revenue_usd") == "revenue ($)"


def test_slug_to_text_abbreviation_preserved() -> None:
    """Abbreviations retain their canonical form (ARR, YoY, etc.)."""
    assert slug_to_text("arr_usd") == "ARR ($)"


def test_slug_to_text_yoy_growth() -> None:
    assert slug_to_text("yoy_growth_pct") == "YoY growth (%)"


def test_slug_to_text_empty_string() -> None:
    assert slug_to_text("") == ""


def test_slug_to_text_kebab_case() -> None:
    assert slug_to_text("revenue-by-month") == "revenue by month"


def test_slug_to_text_single_word() -> None:
    assert slug_to_text("revenue") == "revenue"


# ---------------------------------------------------------------------------
# 'none' enum value: no-op after normalization
# ---------------------------------------------------------------------------


def test_font_style_none_case_valid() -> None:
    """FontStyle accepts case='none'."""
    fs = FontStyle(case="none")
    assert fs.case == "none"


def test_merged_font_style_none_case() -> None:
    """ResolvedFontStyle accepts case='none'."""
    mfs = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="none",
        line_height=1.25,
        tabular_figures=False,
    )
    assert mfs.case == "none"


def test_font_style_rejects_preserve() -> None:
    """'preserve' is not a valid case value — use 'none' instead."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FontStyle(case="preserve")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# apply_font_case: thin wrapper over apply_case that reads ResolvedFontStyle.case
# ---------------------------------------------------------------------------


def test_apply_font_case_none_is_noop() -> None:
    """case='none' passes the string through unchanged."""
    from dbt_charts.core.text.case import apply_font_case

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="none",
        line_height=1.25,
        tabular_figures=False,
    )
    assert apply_font_case("quarterly revenue", font) == "quarterly revenue"


def test_apply_font_case_title() -> None:
    """case='title' applies Gruber title case."""
    from dbt_charts.core.text.case import apply_font_case

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="title",
        line_height=1.25,
        tabular_figures=False,
    )
    assert (
        apply_font_case("quarterly revenue by region", font)
        == "Quarterly Revenue by Region"
    )


def test_apply_font_case_upper() -> None:
    from dbt_charts.core.text.case import apply_font_case

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="upper",
        line_height=1.25,
        tabular_figures=False,
    )
    assert apply_font_case("revenue", font) == "REVENUE"


# ---------------------------------------------------------------------------
# format_display_text: full two-step pipeline
# ---------------------------------------------------------------------------


def test_format_display_text_authored_none() -> None:
    """Authored string + case=none passes through unchanged."""
    from dbt_charts.core.text.case import format_display_text

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="none",
        line_height=1.25,
        tabular_figures=False,
    )
    assert (
        format_display_text("Quarterly Revenue", from_slug=False, font=font)
        == "Quarterly Revenue"
    )


def test_format_display_text_authored_title() -> None:
    """Authored string + case=title applies title case."""
    from dbt_charts.core.text.case import format_display_text

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="title",
        line_height=1.25,
        tabular_figures=False,
    )
    assert (
        format_display_text("quarterly revenue by region", from_slug=False, font=font)
        == "Quarterly Revenue by Region"
    )


def test_format_display_text_slug_none() -> None:
    """Slug + case=none: slug_to_text runs (spaces, suffixes) but no casing."""
    from dbt_charts.core.text.case import format_display_text

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="none",
        line_height=1.25,
        tabular_figures=False,
    )
    # revenue_usd → slug_to_text → "revenue ($)" → no case change
    assert (
        format_display_text("revenue_usd", from_slug=True, font=font) == "revenue ($)"
    )


def test_format_display_text_slug_title() -> None:
    """Slug + case=title: slug_to_text then title case."""
    from dbt_charts.core.text.case import format_display_text

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="title",
        line_height=1.25,
        tabular_figures=False,
    )
    # revenue_usd → slug_to_text → "revenue ($)" → title → "Revenue ($)"
    assert (
        format_display_text("revenue_usd", from_slug=True, font=font) == "Revenue ($)"
    )


def test_format_display_text_slug_title_with_abbreviation() -> None:
    """Abbreviations survive slug_to_text + title case."""
    from dbt_charts.core.text.case import format_display_text

    font = ResolvedFontStyle(
        family="sans-serif",
        color="#000000",
        size=12.0,
        weight="400",
        style="normal",
        decoration="none",
        case="title",
        line_height=1.25,
        tabular_figures=False,
    )
    # yoy_growth_pct → "YoY growth (%)" → title → "YoY Growth (%)"
    assert (
        format_display_text("yoy_growth_pct", from_slug=True, font=font)
        == "YoY Growth (%)"
    )


def test_font_case_cascade_none_not_in_theme_resolves() -> None:
    """Theme root case=none cascades to resolved title font."""
    from dbt_charts.core.compile.config import (
        get_config,
        get_theme_style,
    )
    from dbt_charts.core.compile.resolve.style.board import resolve_style

    get_config()  # ensure settings are loaded
    resolved = resolve_style(get_theme_style())
    # Root font has case=none; title font may override
    assert resolved.font.case == "none"
