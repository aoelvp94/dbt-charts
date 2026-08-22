"""Tests for additive chart padding semantics.

Per-chart padding (style.charts.padding) stacks ON TOP of card_padding
rather than replacing it. Theme default is {0,0,0,0} so existing boards
render identically (0 + card_pad = card_pad on all sides).
"""

from __future__ import annotations

import dataclasses

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)

_BOARD_STYLE = resolve_style(get_theme_style())


def test_additive_padding_default_zero_yields_card_padding_on_all_sides():
    """With default charts.padding={0,0,0,0}, final padding == card_pad on all sides."""
    from dbt_charts.core.compile.models.style.theme import PaddingStyle
    from dbt_charts.core.render.chart.spec_builders import additive_padding

    chart_padding = PaddingStyle(left=0, right=0, top=0, bottom=0)
    result = additive_padding(card_pad=16.0, chart_padding=chart_padding)

    assert result == {"left": 16.0, "right": 16.0, "top": 16.0, "bottom": 16.0}


def test_additive_padding_stacks_chart_right_on_card_pad():
    """charts.padding.right=20 + card_padding=16 → right=36, other sides=16."""
    from dbt_charts.core.compile.models.style.theme import PaddingStyle
    from dbt_charts.core.render.chart.spec_builders import additive_padding

    chart_padding = PaddingStyle(left=0, right=20, top=0, bottom=0)
    result = additive_padding(card_pad=16.0, chart_padding=chart_padding)

    assert result["right"] == 36.0
    assert result["left"] == 16.0
    assert result["top"] == 16.0
    assert result["bottom"] == 16.0


def test_additive_padding_all_sides_stack():
    """All 4 sides stack independently."""
    from dbt_charts.core.compile.models.style.theme import PaddingStyle
    from dbt_charts.core.render.chart.spec_builders import additive_padding

    chart_padding = PaddingStyle(left=10, right=20, top=5, bottom=8)
    result = additive_padding(card_pad=16.0, chart_padding=chart_padding)

    assert result == {"left": 26.0, "right": 36.0, "top": 21.0, "bottom": 24.0}


def test_compiled_padding_style_all_fields_required():
    """PaddingStyle requires all 4 sides — no defaults."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.style.theme import PaddingStyle

    with pytest.raises(ValidationError):
        PaddingStyle(left=0, right=0, top=0)  # missing bottom


def test_compiled_charts_style_padding_field_exists():
    """ChartsStyle.padding is a PaddingStyle."""
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.models.style.theme import PaddingStyle

    kpi = get_theme_style("editorial")
    assert isinstance(kpi.charts.padding, PaddingStyle)


def test_theme_corpus_padding_field_compiles(compiled_themes):
    """All production themes compile with the required PaddingStyle field."""
    from dbt_charts.core.compile.models.style.theme import PaddingStyle

    for name, t in compiled_themes.items():
        assert isinstance(t.charts.padding, PaddingStyle), (
            f"Theme {name}: charts.padding is not PaddingStyle"
        )


def test_data_table_strip_and_right_padding_both_survive_pipeline():
    """charts.padding.right and data-table strip both reach the final spec.

    Pipeline: generate_vega_lite_spec with non-zero charts.padding.right.
    Verifies right padding survives the render path.
    """
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.models.chart.normalized import BarChart
    from dbt_charts.core.compile.models.style.theme import PaddingStyle
    from dbt_charts.core.compile.resolve.style.board import resolve_style
    from dbt_charts.core.render.chart.spec_builders import additive_padding
    from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

    compiled = get_theme_style()
    board_style = resolve_style(compiled)
    ctx = resolve_chart_style_context(compiled)
    chart_padding = PaddingStyle(left=0, right=20, top=0, bottom=0)
    ctx_override = dataclasses.replace(ctx, padding=chart_padding)

    card_pad = float(board_style.frame.card_padding)
    threaded_padding = additive_padding(card_pad, chart_padding)

    chart = BarChart(id="t", type="bar", x="month", y="revenue", query_name="q")
    data = [{"month": "Jan", "revenue": 100}]

    spec = generate_vega_lite_spec(
        chart,
        data,
        width=400,
        height=200,
        board_style=board_style,
        chart_style_context=ctx_override,
    )
    # Apply additive padding to the spec to confirm it can be injected.
    spec["padding"] = threaded_padding
    assert spec["padding"]["right"] == card_pad + 20.0, "right padding survived"
    assert spec["padding"]["left"] == card_pad
