"""KPI SVG regression guard: render path must stay byte-identical across calls.

Both sides resolve from the SAME authored chart dict via the real pipeline
(normalize -> resolve). Never hand-construct ResolvedKpiChart directly —
that would hide gaps in the KPI resolver.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.models.query.normalized import ValuesQuery
from dbt_charts.core.compile.resolve import resolve


def _styles() -> tuple[Any, Any]:
    from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context

    return resolve_style_and_context(get_theme_style(get_default_theme_name()))


def _oracle_svg(
    chart_def: dict[str, Any],
    query_registry: dict[str, Any],
    data: list[dict[str, Any]],
    board_rs: Any,
    board_ctx: Any,
) -> str:
    """Reference path: authored dict -> normalize_chart -> resolve -> render_kpi_svg."""
    from dbt_charts.core.compile.normalize.charts import normalize_chart
    from dbt_charts.core.render.chart.kpi import render_kpi_svg

    flat = normalize_chart("chart1", chart_def, query_registry, sources={})
    resolved = resolve(flat, data, chart_style_context=board_ctx)
    return render_kpi_svg(resolved, data, board_style=board_rs)


def _v2_svg(
    chart_def: dict[str, Any],
    query_registry: dict[str, Any],
    data: list[dict[str, Any]],
    board_rs: Any,
    board_ctx: Any,
) -> str:
    """render path: authored dict -> normalize_chart -> resolve -> render_kpi_svg."""
    from dbt_charts.core.compile.models.chart.resolved.kpi import ResolvedKpiChart
    from dbt_charts.core.compile.normalize.charts import normalize_chart
    from dbt_charts.core.compile.resolve import resolve
    from dbt_charts.core.render.chart.kpi import render_kpi_svg

    compiled = normalize_chart("chart1", chart_def, query_registry, sources={})
    resolved = resolve(compiled, data, chart_style_context=board_ctx)
    assert isinstance(resolved, ResolvedKpiChart)
    return render_kpi_svg(resolved, data, board_style=board_rs)


_QUERY_REGISTRY = {"q": ValuesQuery(rows=[{"revenue": 128_000, "delta": 0.12}])}
_DATA = _QUERY_REGISTRY["q"].rows

_FIXTURES: dict[str, dict[str, Any]] = {
    "plain_value": {
        "type": "kpi",
        "query": "q",
        "value": "revenue",
    },
    "value_label_support": {
        "type": "kpi",
        "query": "q",
        "value": "revenue",
        "label": "Revenue",
        "support": {
            "value": "delta",
            "label": "vs last month",
            "glyph": "▲",
        },
    },
    "tone_glyph": {
        "type": "kpi",
        "query": "q",
        "value": "revenue",
        "label": "Revenue",
        "style": {
            "glyph": {"character": "▲"},
        },
        "support": {
            "label": "vs last month",
            "tone": "positive",
        },
    },
    "conditional_formatting": {
        "type": "kpi",
        "query": "q",
        "value": "revenue",
        "label": "Revenue",
        "conditional_formatting": {
            "revenue": {
                "when": [
                    {"gt": 100_000, "font": {"color": "#00aa00"}},
                    {"lte": 100_000, "font": {"color": "#ff0000"}},
                ]
            }
        },
    },
}


def test_kpi_card_border_dash_array_emits_svg_dasharray() -> None:
    """style.border.dash_array on a KPI card reaches the card chrome's stroke."""
    chart_def: dict[str, Any] = {
        "type": "kpi",
        "query": "q",
        "value": "revenue",
        "label": "Revenue",
        "style": {
            "border": {
                "width": 1,
                "color": "#333333",
                "radius": 4,
                "dash_array": [4, 4],
                "line_cap": "round",
            },
        },
    }
    board_rs, board_ctx = _styles()
    svg = _v2_svg(chart_def, _QUERY_REGISTRY, _DATA, board_rs, board_ctx)
    assert 'stroke-dasharray="4,4"' in svg
    assert 'stroke-linecap="round"' in svg


@pytest.mark.parametrize("fixture_name", sorted(_FIXTURES))
def test_v2_kpi_svg_byte_identical(fixture_name: str) -> None:
    chart_def = _FIXTURES[fixture_name]
    board_rs, board_ctx = _styles()
    oracle = _oracle_svg(chart_def, _QUERY_REGISTRY, _DATA, board_rs, board_ctx)
    result = _v2_svg(chart_def, _QUERY_REGISTRY, _DATA, board_rs, board_ctx)
    assert oracle == result, (
        f"KPI SVG parity FAILED for fixture={fixture_name!r}\nORACLE=\n{oracle}\n\nV2=\n{result}"
    )


@pytest.mark.parametrize("variant", ["stacked", "inline", "compact"])
def test_v2_kpi_svg_byte_identical_across_variants(variant: str) -> None:
    chart_def = {
        "type": "kpi",
        "query": "q",
        "value": "revenue",
        "label": "Revenue",
        "variant": variant,
        "support": {
            "value": "delta",
            "label": "vs last month",
        },
    }
    board_rs, board_ctx = _styles()
    oracle = _oracle_svg(chart_def, _QUERY_REGISTRY, _DATA, board_rs, board_ctx)
    result = _v2_svg(chart_def, _QUERY_REGISTRY, _DATA, board_rs, board_ctx)
    assert oracle == result, (
        f"KPI SVG parity FAILED for variant={variant!r}\nORACLE=\n{oracle}\n\nV2=\n{result}"
    )
